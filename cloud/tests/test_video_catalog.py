"""Catálogo de videos sin depender de las ventas (rev. 6): GET /api/catalogo/videos y /api/catalogo/videos/{id}.

Corre un hub REAL en modo nube con los transportes falsos de la demo (TikTok Shop y Display API: datos sintéticos,
sin firmas ni red) y una sincronización completa. Nunca lee una conexión del operador ni llama a TikTok: las portadas
usan un descargador sin red y, mientras corre cada clase, resolver un nombre fuera de esta máquina falla la prueba.
"""
from __future__ import annotations

import gzip
import itertools
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'hub'))

from cloud.display_import import import_display
from creatorhub.analitica import display as display_api
from creatorhub.analitica.vista import Vista
from creatorhub.demo import sinteticos
from creatorhub.demo.transporte import USUARIO_DEMO, TransporteApiFalsa
from creatorhub.hub import iniciar_hub
from creatorhub.imagenes.claves import ErrorImagen
from creatorhub.interfaces import CTX_UI, OpcionesHub
from creatorhub.tiktok_dev import datos as D
from creatorhub.tiktok_dev.boveda import datos_demo
from creatorhub.tiktok_dev.cliente import SCOPES
from creatorhub.tiktok_dev.demo import VIDEOS_SIN_VENTA, TransporteDisplayDemo

# Campos de VideoCatalogo que solo aporta la Display API (null cuando no se saben; nunca ceros).
CAMPOS_DISPLAY = ('descripcion', 'publicado_at', 'duracion_s', 'vistas', 'likes', 'comentarios', 'compartidos',
                  'metricas_at')
ETAG_LECTURA = r'^W/"dv\d+-lr\d+-ir\d+-[0-9a-f]{12}"$'      # forma visible de las lecturas compuestas
LOCALES = frozenset({None, '', 'localhost', '127.0.0.1', '::1', '0.0.0.0'})
ESQUEMA = (ROOT / 'hub' / 'creatorhub' / 'almacen' / 'schema.sql').read_text(encoding='utf-8')


def _sin_red(url: str) -> bytes:
    """Descargador de imágenes de las pruebas: nunca sale a la red (la portada se queda en '?v=0')."""
    raise ErrorImagen('sin_red_en_pruebas', permanente=True)


class GuardiaDeRed:
    """Mientras está activa, resolver un nombre fuera de esta máquina falla y queda anotado."""

    def __init__(self) -> None:
        self.intentos: list[str] = []
        real = socket.getaddrinfo

        def resolver(host, *args, **kwargs):
            nombre = host.decode('ascii', 'replace') if isinstance(host, bytes) else host
            if nombre not in LOCALES:
                self.intentos.append(str(nombre))
                raise OSError(f'Red bloqueada en las pruebas: {nombre}')
            return real(host, *args, **kwargs)
        self._parche = patch('socket.getaddrinfo', resolver)

    def activar(self) -> None:
        self._parche.start()

    def desactivar(self) -> None:
        self._parche.stop()


class HubSintetico(unittest.TestCase):
    """Hub REAL en modo nube con TikTok Shop sintético y una sincronización completa por clase. Cada subclase elige la
    Display API en `preparar_display`."""

    @classmethod
    def preparar_display(cls, ahora: int) -> None:
        raise NotImplementedError

    @classmethod
    def setUpClass(cls) -> None:
        cls.red = GuardiaDeRed()
        cls.red.activar()
        cls.addClassCleanup(cls.red.desactivar)

        def sin_intentos_de_red() -> None:
            if cls.red.intentos:
                raise AssertionError(f'Las pruebas intentaron salir a la red: {sorted(set(cls.red.intentos))}')
        cls.addClassCleanup(sin_intentos_de_red)
        cls.carpeta = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.carpeta.cleanup)
        cls.env = patch.dict(os.environ, {'CORTE_PUBLIC_URL': 'https://corte.example',
                                          'CORTE_ENCRYPTION_KEY': 'synthetic-master-' * 4})
        cls.env.start()
        cls.addClassCleanup(cls.env.stop)
        with patch('creatorhub.imagenes.servicio.DescargadorHttps', return_value=_sin_red):
            cls.hub = iniciar_hub(OpcionesHub(modo='real', nube=True, sin_lan=True, raiz_datos=cls.carpeta.name,
                                              sync_al_iniciar=False))
        cls.addClassCleanup(cls.hub.detener, 10)       # las limpiezas corren al revés: el hub se detiene primero
        ahora = int(time.time())
        futuro = ahora + 86400
        cls.hub.boveda.mutar(lambda d: d.update(
            app_key='synthetic-app-key', app_secret='SyntheticSecretForTests123456',
            access_token='synthetic-access-token', refresh_token='synthetic-refresh-token',
            open_id='synthetic-open-id', access_expira_at=futuro, refresh_expira_at=futuro + 86400 * 30,
            user_type=1, granted_scopes=['creator.affiliate.info'], origen='importado'), cambia_credenciales=True)
        cls.hub.auth._espejar()
        cls.hub.cliente.transporte = TransporteApiFalsa(sinteticos.generar(ahora), cls.hub.reloj)
        cls.hub.cliente.cubeta.tomar = lambda cancelar=None: False
        cls.hub.cliente._esperar = lambda segundos, path=None: None
        cls.preparar_display(ahora)
        cls.sincronizar('completa')

    @classmethod
    def sincronizar(cls, tipo: str = 'incremental') -> None:
        cls.hub.sincronizador.iniciar(tipo, 'usuario')
        if not cls.hub.sincronizador._actual.fin.wait(600):
            raise AssertionError('La sincronización sintética no terminó')

    def api(self, ruta: str, consulta: str = '', cabeceras: dict | None = None):
        r = self.hub.despachador.despachar('GET', ruta, consulta, cabeceras or {}, b'', CTX_UI)
        cuerpo = gzip.decompress(r.cuerpo) if r.cuerpo[:2] == b'\x1f\x8b' else r.cuerpo
        return r.status, dict(r.cabeceras), json.loads(cuerpo or b'null')

    def catalogo(self, consulta: str = 'limite=2000') -> dict:
        status, _, cuerpo = self.api('/api/catalogo/videos', consulta)
        self.assertEqual(status, 200, cuerpo)
        return cuerpo

    def ids_catalogo(self, consulta: str = 'limite=2000') -> set[str]:
        return {i['content_id'] for i in self.catalogo(consulta)['items']}

    def legado(self) -> dict:
        status, _, cuerpo = self.api('/api/analitica/videos', 'limite=1000')
        self.assertEqual(status, 200, cuerpo)
        return {f['content_id']: f for f in cuerpo['items']}

    def escribir(self, sql: str, params=()) -> None:
        with self.hub.almacen.escritor() as db:
            db.execute(sql, params)

    def respaldar(self, tabla: str, ids: list[str]) -> tuple[list[str], list[tuple]]:
        with self.hub.almacen.lector() as db:
            columnas = [d[0] for d in db.execute(f'SELECT * FROM {tabla} LIMIT 0').description]
            filas = db.execute(f'SELECT * FROM {tabla} WHERE video_id IN ({",".join("?" * len(ids))})',
                               ids).fetchall()
        return columnas, [tuple(f) for f in filas]

    def restaurar(self, tabla: str, respaldo: tuple[list[str], list[tuple]]) -> None:
        columnas, filas = respaldo
        with self.hub.almacen.escritor() as db:
            db.executemany(f'INSERT OR REPLACE INTO {tabla}({", ".join(columnas)}) '
                           f'VALUES ({", ".join("?" * len(columnas))})', filas)


class ConSyncSintetica(HubSintetico):
    """Display API de la demo: los 90 videos con venta más 30 públicos sin ventas, de la cuenta del creador."""

    @classmethod
    def preparar_display(cls, ahora: int) -> None:
        cls.hub.display.boveda.mutar(lambda d: d.update(datos_demo(ahora)), cambia_credenciales=True)
        cls.hub.display.cliente.transporte = TransporteDisplayDemo(cls.hub.reloj)

    def _ids_display(self) -> list[str]:
        with self.hub.almacen.lector() as db:
            return [r[0] for r in db.execute('SELECT video_id FROM videos_tiktok ORDER BY video_id')]

    def cursor_display(self) -> tuple[str, int]:
        with self.hub.almacen.lector() as db:
            return tuple(db.execute("SELECT valor, actualizado_at FROM sync_cursores "
                                    "WHERE clave = 'display.ultima_sync'").fetchone())

    def poner_cursor(self, valor: dict | None, actualizado_at: int) -> None:
        if valor is None:
            self.escribir("DELETE FROM sync_cursores WHERE clave = 'display.ultima_sync'")
        else:
            self.escribir('INSERT OR REPLACE INTO sync_cursores(clave, valor, actualizado_at) VALUES (?, ?, ?)',
                          ('display.ultima_sync', json.dumps(valor), actualizado_at))


class CatalogoTests(ConSyncSintetica):
    def test_une_videos_publicados_y_con_ventas_sin_tocar_la_lista_de_ventas(self) -> None:
        cat, legado = self.catalogo(), self.legado()
        items = {i['content_id']: i for i in cat['items']}
        self.assertEqual(cat['total'], len(items))
        self.assertEqual(cat['display']['misma_cuenta'], True)
        self.assertIsInstance(cat['display']['ultima_sync_at'], int)
        con_ventas = {cid for cid, i in items.items() if i['ventas'] is not None}
        self.assertEqual(con_ventas, set(legado))                       # el legado sigue igual: solo videos vendidos
        organicos = [i for i in items.values() if i['origen'] == 'display']
        self.assertGreaterEqual(len(organicos), VIDEOS_SIN_VENTA)
        for i in organicos:
            self.assertIsNone(i['ventas'])
            self.assertEqual(i['publicacion'], 'publico')
        # La Display API de la demo lista los 90 videos vendidos: cada uno trae las mismas cifras que su FilaVideo.
        comunes = (*CAMPOS_DISPLAY, 'portada')
        for cid in con_ventas:
            self.assertEqual(items[cid]['ventas'], legado[cid])          # la fila de ventas es la de siempre
            self.assertEqual(items[cid]['origen'], 'display_y_ventas')
            self.assertEqual({k: items[cid][k] for k in comunes}, {k: legado[cid][k] for k in comunes}, cid)
        with self.hub.almacen.lector() as db:
            filas = {str(r[0]): r for r in db.execute(
                'SELECT video_id, titulo, descripcion, duracion_s, creado_at, vistas, likes, comentarios, compartidos, '
                'visto_at FROM videos_tiktok')}
        for i in organicos:                                             # los sin ventas, contra su fila de la Display API
            f = filas[i['content_id']]
            esperado = {'descripcion': f[1] or f[2], 'duracion_s': f[3], 'publicado_at': f[4], 'vistas': f[5],
                        'likes': f[6], 'comentarios': f[7], 'compartidos': f[8], 'metricas_at': f[9]}
            self.assertEqual({k: i[k] for k in esperado}, esperado, i['content_id'])
        for cid, i in items.items():
            self.assertIsInstance(cid, str)
            self.assertTrue(i['portada'] and i['portada'].startswith(f'/img/v/{cid}'), i['portada'])
        self.assertRegex(cat['pedidos_desde'], r'^\d{4}-\d{2}-\d{2}$')

    def test_orden_y_limite(self) -> None:
        publicado = self.catalogo()['items']
        fechas = [i['publicado_at'] for i in publicado if i['publicado_at'] is not None]
        self.assertEqual(fechas, sorted(fechas, reverse=True))
        vistas = [i['vistas'] for i in self.catalogo('orden=vistas&limite=2000')['items'] if i['vistas'] is not None]
        self.assertEqual(vistas, sorted(vistas, reverse=True))
        comision = self.catalogo('orden=comision&limite=2000')['items']
        vendidos = [i['ventas']['comision_estimada_centavos'] for i in comision if i['ventas'] is not None]
        self.assertEqual(vendidos, sorted(vendidos, reverse=True))
        self.assertTrue(all(i['ventas'] is not None for i in comision[:len(vendidos)]))
        corto = self.catalogo('limite=5')
        self.assertEqual(len(corto['items']), 5)
        self.assertEqual(corto['total'], self.catalogo()['total'])

    def test_lista_blanca_de_parametros(self) -> None:
        for consulta in ('desde=2026-01-01', 'orden=fecha', 'incluir=todo', 'limite=0', 'limite=2001'):
            with self.subTest(consulta):
                status, _, cuerpo = self.api('/api/catalogo/videos', consulta)
                self.assertEqual(status, 400)
                self.assertEqual(cuerpo['error']['codigo'], 'parametros_invalidos')

    def test_detalle_de_un_video_sin_ventas_y_de_uno_con_ventas(self) -> None:
        items = self.catalogo()['items']
        organico = next(i for i in items if i['origen'] == 'display')
        vendido = next(i for i in items if i['ventas'] is not None)['content_id']

        status, _, cuerpo = self.api(f"/api/videos/{organico['content_id']}")
        self.assertEqual(status, 404)                                 # la ruta de ventas no cambia
        status, _, cuerpo = self.api(f"/api/catalogo/videos/{organico['content_id']}")
        self.assertEqual(status, 200)
        self.assertEqual(cuerpo['video'], organico)                   # el detalle repite el mismo VideoCatalogo
        self.assertIsNone(cuerpo['ventas'])
        self.assertTrue(cuerpo['tendencia'])

        status, _, legado = self.api(f'/api/videos/{vendido}')
        self.assertEqual(status, 200)
        status, _, cuerpo = self.api(f'/api/catalogo/videos/{vendido}')
        self.assertEqual(status, 200)
        for clave in ('video', 'serie', 'productos'):
            self.assertEqual(cuerpo['ventas'][clave], legado[clave])
        self.assertNotIn('tendencia', cuerpo['ventas'])
        self.assertEqual(cuerpo['tendencia'], legado['tendencia'])

    def test_ids_desconocidos_o_invalidos(self) -> None:
        status, _, cuerpo = self.api('/api/catalogo/videos/7000000000000000000')
        self.assertEqual(status, 404)
        self.assertEqual(cuerpo['error']['detalle'], {'recurso': 'video'})
        status, _, cuerpo = self.api('/api/catalogo/videos/no-es-id')
        self.assertEqual(status, 400)

    def test_etag_y_304(self) -> None:
        cid = self._ids_display()[0]
        for ruta, consulta in (('/api/catalogo/videos', 'limite=10'), (f'/api/catalogo/videos/{cid}', '')):
            with self.subTest(ruta=ruta):
                status, cabeceras, _ = self.api(ruta, consulta)
                self.assertEqual(status, 200)
                self.assertRegex(cabeceras['ETag'], ETAG_LECTURA)      # la marca de la Display API solo entra al hash
                status, otras, _ = self.api(ruta, consulta, {'if-none-match': cabeceras['ETag']})
                self.assertEqual((status, otras['ETag']), (304, cabeceras['ETag']))

    def test_la_sesion_anuncia_la_capacidad(self) -> None:
        status, _, cuerpo = self.api('/api/session')
        self.assertEqual(status, 200)
        self.assertIs(cuerpo['capacidades']['catalogo_videos'], True)


class CatalogoCuentaEHistorialTests(ConSyncSintetica):
    """Cada prueba cambia la base y la deja como estaba."""

    def test_otra_cuenta_de_display_no_lista_videos_sin_ventas(self) -> None:
        with self.hub.almacen.lector() as db:
            previo = db.execute('SELECT username FROM perfil_tiktok WHERE id = 1').fetchone()[0]
        try:
            self.escribir("UPDATE perfil_tiktok SET username = 'otra_cuenta' WHERE id = 1")
            cat = self.catalogo()
            self.assertIs(cat['display']['misma_cuenta'], False)
            self.assertFalse([i for i in cat['items'] if i['origen'] == 'display'])
            self.assertEqual({i['content_id'] for i in cat['items']}, set(self.legado()))
            organico = next(cid for cid in self._ids_display() if cid not in self.legado())
            status, _, _ = self.api(f'/api/catalogo/videos/{organico}')
            self.assertEqual(status, 404)
            self.escribir('UPDATE perfil_tiktok SET username = NULL WHERE id = 1')
            self.assertIsNone(self.catalogo()['display']['misma_cuenta'])   # sin nombre no se puede comprobar
            self.assertFalse([i for i in self.catalogo()['items'] if i['origen'] == 'display'])
        finally:
            self.escribir('UPDATE perfil_tiktok SET username = ? WHERE id = 1', (previo,))
        self.assertIs(self.catalogo()['display']['misma_cuenta'], True)

    def test_un_video_que_solo_conserva_historial(self) -> None:
        legado = self.legado()
        cid = next(c for c in self._ids_display() if c not in legado)
        respaldo = self.respaldar('videos_tiktok', [cid])
        with self.hub.almacen.lector() as db:
            ultima = db.execute('SELECT vistas, likes, comentarios, compartidos, actualizado_at FROM videos_tiktok_dias '
                                'WHERE video_id = ? ORDER BY fecha DESC LIMIT 1', (cid,)).fetchone()
            usuario = db.execute('SELECT username FROM perfil_tiktok WHERE id = 1').fetchone()[0]
        try:
            self.escribir('DELETE FROM videos_tiktok WHERE video_id = ?', (cid,))   # dejó de ser público
            self.assertNotIn(cid, self.ids_catalogo())
            item = {i['content_id']: i for i in self.catalogo('incluir=historial&limite=2000')['items']}[cid]
            self.assertEqual((item['publicacion'], item['origen']), ('no_publico', 'display'))
            self.assertEqual([item[k] for k in ('vistas', 'likes', 'comentarios', 'compartidos', 'metricas_at')],
                             list(ultima))
            self.assertIsNone(item['descripcion'])
            status, _, cuerpo = self.api(f'/api/catalogo/videos/{cid}')
            self.assertEqual(status, 200)
            self.assertEqual(cuerpo['video'], item)
            self.assertTrue(cuerpo['tendencia'])
            for otro in ('otra_cuenta', None):          # Display API de otra cuenta, o sin nombre para comprobarlo
                with self.subTest(username=otro):
                    self.escribir('UPDATE perfil_tiktok SET username = ? WHERE id = 1', (otro,))
                    self.assertNotIn(cid, self.ids_catalogo('incluir=historial&limite=2000'))
                    self.assertEqual(self.api(f'/api/catalogo/videos/{cid}')[0], 404)
        finally:
            self.escribir('UPDATE perfil_tiktok SET username = ? WHERE id = 1', (usuario,))
            self.restaurar('videos_tiktok', respaldo)

    def test_un_video_vendido_que_dejo_de_ser_publico_es_igual_en_toda_vista(self) -> None:
        cid = next(c for c in self._ids_display() if c in self.legado())
        respaldo = self.respaldar('videos_tiktok', [cid])
        with self.hub.almacen.lector() as db:
            ultima = db.execute('SELECT vistas, likes, comentarios, compartidos, actualizado_at FROM videos_tiktok_dias '
                                'WHERE video_id = ? ORDER BY fecha DESC LIMIT 1', (cid,)).fetchone()
            usuario = db.execute('SELECT username FROM perfil_tiktok WHERE id = 1').fetchone()[0]
        try:
            self.escribir('DELETE FROM videos_tiktok WHERE video_id = ?', (cid,))   # privado o borrado: queda su historial
            # Por ID exacto, su última foto es del creador: se muestra igual sea cual sea la cuenta de la Display API.
            for otro, misma in ((usuario, True), ('otra_cuenta', False), (None, None)):
                with self.subTest(misma_cuenta=misma):
                    self.escribir('UPDATE perfil_tiktok SET username = ? WHERE id = 1', (otro,))
                    cat = self.catalogo()
                    self.assertIs(cat['display']['misma_cuenta'], misma)
                    por_omision = {i['content_id']: i for i in cat['items']}[cid]
                    con_historial = {i['content_id']: i
                                     for i in self.catalogo('incluir=historial&limite=2000')['items']}[cid]
                    status, _, cuerpo = self.api(f'/api/catalogo/videos/{cid}')
                    self.assertEqual(status, 200)
                    self.assertEqual(con_historial, por_omision)
                    self.assertEqual(cuerpo['video'], por_omision)
                    self.assertEqual((por_omision['origen'], por_omision['publicacion']),
                                     ('display_y_ventas', 'no_publico'))
                    self.assertEqual([por_omision[k] for k in ('vistas', 'likes', 'comentarios', 'compartidos',
                                                               'metricas_at')], list(ultima))
                    self.assertIsNone(por_omision['publicado_at'])      # lo que solo da el listado ya no se sabe
                    self.assertEqual(por_omision['ventas'], self.legado()[cid])
        finally:
            self.escribir('UPDATE perfil_tiktok SET username = ? WHERE id = 1', (usuario,))
            self.restaurar('videos_tiktok', respaldo)

    def test_videos_vendidos_que_la_display_api_no_tiene(self) -> None:
        vendidos = sorted(self.legado().values(), key=lambda f: (f['ultima_venta'], f['content_id']))
        nuevo, viejo = vendidos[-1], vendidos[0]
        self.assertLess(viejo['ultima_venta'], nuevo['ultima_venta'])
        ids = [nuevo['content_id'], viejo['content_id']]
        respaldos = {t: self.respaldar(t, ids) for t in ('videos_tiktok', 'videos_tiktok_dias')}
        try:
            self.escribir('DELETE FROM videos_tiktok WHERE video_id IN (?, ?)', ids)        # privados, borrados o
            self.escribir('DELETE FROM videos_tiktok_dias WHERE video_id IN (?, ?)', ids)   # fuera del tope, sin fotos
            items = self.catalogo()['items']
            por_id = {i['content_id']: i for i in items}
            legado = self.legado()
            for cid in ids:
                i = por_id[cid]
                self.assertEqual((i['origen'], i['publicacion']), ('ventas', 'desconocido'))
                self.assertEqual({k: i[k] for k in CAMPOS_DISPLAY}, dict.fromkeys(CAMPOS_DISPLAY))   # null, no ceros
                self.assertEqual(i['ventas'], legado[cid])
            self.assertEqual([i['content_id'] for i in items[-2:]], ids)   # sin fecha: al final, venta más reciente 1.º
            por_vistas = self.catalogo('orden=vistas&limite=2000')['items']
            self.assertEqual({i['content_id'] for i in por_vistas[-2:]}, set(ids))
            status, _, cuerpo = self.api(f'/api/catalogo/videos/{ids[0]}')
            self.assertEqual((status, cuerpo['video']), (200, por_id[ids[0]]))
            self.assertEqual(cuerpo['tendencia'], [])           # Display API conectada, sin fotos de este video
        finally:
            for tabla, respaldo in respaldos.items():
                self.restaurar(tabla, respaldo)

    def publicacion(self, cid: str) -> str:
        item = {i['content_id']: i for i in self.catalogo()['items']}[cid]
        status, _, cuerpo = self.api(f'/api/catalogo/videos/{cid}')
        self.assertEqual((status, cuerpo['video']), (200, item))
        self.assertIsNotNone(item['vistas'])                    # sigue guardado: conserva sus cifras
        return item['publicacion']

    def test_publicacion_sigue_la_ultima_pasada(self) -> None:
        cid = next(c for c in self._ids_display() if c not in self.legado())
        with self.hub.almacen.lector() as db:
            visto, tope = db.execute('SELECT (SELECT visto_at FROM videos_tiktok WHERE video_id = ?), '
                                     'MAX(visto_at) FROM videos_tiktok', (cid,)).fetchone()
        cursor = self.cursor_display()
        pasada = json.loads(cursor[0])
        self.assertEqual(visto, pasada['at'])
        self.assertEqual(pasada['visto_tope'], tope)          # la sync guarda el tope en la misma transacción
        ultima = pasada['at']
        try:
            self.escribir('UPDATE videos_tiktok SET visto_at = ? WHERE video_id = ?', (ultima - 1, cid))
            self.assertEqual(self.publicacion(cid), 'no_confirmado')     # la última pasada no lo vio
            self.escribir('UPDATE videos_tiktok SET visto_at = ? WHERE video_id = ?', (ultima + 60, cid))
            self.assertEqual(self.publicacion(cid), 'publico')           # lo vio una pasada posterior, en curso o interrumpida
            self.poner_cursor(None, 0)
            self.assertEqual(self.publicacion(cid), 'publico')           # la primera pasada no terminó: salió en ella
            self.assertIsNone(self.catalogo()['display']['ultima_sync_at'])
        finally:
            self.escribir('UPDATE videos_tiktok SET visto_at = ? WHERE video_id = ?', (visto, cid))
            self.poner_cursor(pasada, cursor[1])

    def test_publicacion_no_depende_de_que_el_reloj_avance(self) -> None:
        cid = next(c for c in self._ids_display() if c not in self.legado())
        with self.hub.almacen.lector() as db:
            visto = db.execute('SELECT visto_at FROM videos_tiktok WHERE video_id = ?', (cid,)).fetchone()[0]
        cursor = self.cursor_display()
        pasada = json.loads(cursor[0])
        ultima = pasada['at']
        try:
            # El reloj se atrasó una hora: la pasada registrada empezó ANTES que la anterior, no terminó y no vio este
            # video, que conserva el visto_at de la anterior (igual al tope guardado con el cursor).
            self.poner_cursor(dict(pasada, at=ultima - 3600, visto_tope=ultima, estado='parcial', completa=False),
                              cursor[1])
            self.assertEqual(self.publicacion(cid), 'no_confirmado')
            self.escribir('UPDATE videos_tiktok SET visto_at = ? WHERE video_id = ?', (ultima - 3600, cid))
            self.assertEqual(self.publicacion(cid), 'publico')           # lo vio la pasada registrada
            self.escribir('UPDATE videos_tiktok SET visto_at = ? WHERE video_id = ?', (ultima + 5, cid))
            self.assertEqual(self.publicacion(cid), 'publico')           # lo vio una pasada posterior al tope
            # Un cursor anterior a la rev. 6 no trae visto_tope: cuenta su instante.
            self.poner_cursor({k: v for k, v in pasada.items() if k != 'visto_tope'}, cursor[1])
            self.assertEqual(self.publicacion(cid), 'publico')
            self.escribir('UPDATE videos_tiktok SET visto_at = ? WHERE video_id = ?', (ultima - 1, cid))
            self.assertEqual(self.publicacion(cid), 'no_confirmado')
        finally:
            self.escribir('UPDATE videos_tiktok SET visto_at = ? WHERE video_id = ?', (visto, cid))
            self.poner_cursor(pasada, cursor[1])

    def test_publicacion_reconoce_una_pasada_sin_registrar_aunque_el_reloj_se_atrase(self) -> None:
        cid = next(c for c in self._ids_display() if c not in self.legado())
        with self.hub.almacen.lector() as db:
            visto = db.execute('SELECT visto_at FROM videos_tiktok WHERE video_id = ?', (cid,)).fetchone()[0]
        ultima = json.loads(self.cursor_display()[0])['at']
        try:
            # Con el reloj atrasado cinco minutos, una pasada empezó, guardó este video y se canceló sin registrarse.
            self.escribir('UPDATE videos_tiktok SET visto_at = ? WHERE video_id = ?', (ultima - 300, cid))
            self.assertEqual(self.publicacion(cid), 'no_confirmado')      # sin saber de esa pasada
            antes = self.api('/api/catalogo/videos', 'limite=10')[1]['ETag']
            self.escribir('INSERT INTO sync_cursores(clave, valor, actualizado_at) VALUES (?, ?, ?)',
                          (D.CLAVE_SIN_REGISTRAR, json.dumps([ultima - 300]), ultima))
            self.assertEqual(self.publicacion(cid), 'publico')            # salió en una pasada posterior a la registrada
            status, cabeceras, _ = self.api('/api/catalogo/videos', 'limite=10', {'if-none-match': antes})
            self.assertEqual(status, 200)                                 # y la ETag del catálogo lo sabe
            self.assertRegex(cabeceras['ETag'], ETAG_LECTURA)
        finally:
            self.escribir('UPDATE videos_tiktok SET visto_at = ? WHERE video_id = ?', (visto, cid))
            self.escribir('DELETE FROM sync_cursores WHERE clave = ?', (D.CLAVE_SIN_REGISTRAR,))

    def rutas_etag(self) -> dict[str, str]:
        return {'/api/catalogo/videos': 'limite=10', f'/api/catalogo/videos/{self._ids_display()[0]}': ''}

    def assertEtagRenovada(self, antes: dict[str, str]) -> None:
        for r, q in self.rutas_etag().items():
            with self.subTest(ruta=r):
                status, cabeceras, _ = self.api(r, q, {'if-none-match': antes[r]})
                self.assertEqual(status, 200)
                self.assertNotEqual(cabeceras['ETag'], antes[r])
                self.assertRegex(cabeceras['ETag'], ETAG_LECTURA)

    def test_la_etag_del_catalogo_sigue_cada_pasada_de_la_display_api(self) -> None:
        cursor = self.cursor_display()
        antes = {r: self.api(r, q)[1]['ETag'] for r, q in self.rutas_etag().items()}
        legado = self.api('/api/analitica/videos', 'limite=10')[1]['ETag']
        pasada = json.loads(cursor[0])
        try:
            self.poner_cursor(dict(pasada, at=pasada['at'] + 60, estado='error'), cursor[1])   # no cambió ningún video
            self.assertEtagRenovada(antes)
            cuerpo = self.catalogo('limite=10')
            self.assertEqual(cuerpo['display']['ultima_sync_at'], pasada['at'] + 60)
            self.assertEqual({i['publicacion'] for i in cuerpo['items']}, {'no_confirmado'})
            status, _, _ = self.api('/api/analitica/videos', 'limite=10', {'if-none-match': legado})
            self.assertEqual(status, 304)                        # las demás lecturas conservan su ETag
        finally:
            self.poner_cursor(pasada, cursor[1])
        status, _, _ = self.api('/api/catalogo/videos', 'limite=10', {'if-none-match': antes['/api/catalogo/videos']})
        self.assertEqual(status, 304)

    def test_la_etag_del_catalogo_sigue_las_paginas_de_una_pasada_interrumpida(self) -> None:
        with self.hub.almacen.lector() as db:
            pagina = [r[0] for r in db.execute('SELECT video_id FROM videos_tiktok ORDER BY creado_at DESC LIMIT 20')]
        antes = {r: self.api(r, q)[1]['ETag'] for r, q in self.rutas_etag().items()}
        legado = self.api('/api/analitica/videos', 'limite=10')[1]['ETag']
        marcas = ','.join('?' * len(pagina))
        try:
            # Una pasada guardó su primera página (visto_at nuevo, mismas cifras) y se canceló sin escribir el cursor.
            self.escribir(f'UPDATE videos_tiktok SET visto_at = visto_at + 60 WHERE video_id IN ({marcas})', pagina)
            self.assertEtagRenovada(antes)
            status, _, _ = self.api('/api/analitica/videos', 'limite=10', {'if-none-match': legado})
            self.assertEqual(status, 304)
        finally:
            self.escribir(f'UPDATE videos_tiktok SET visto_at = visto_at - 60 WHERE video_id IN ({marcas})', pagina)
        for r, q in self.rutas_etag().items():
            self.assertEqual(self.api(r, q, {'if-none-match': antes[r]})[0], 304, r)


# ---------------------------------------------------------------------- de quién es lo guardado de la Display API
APP_1, APP_2, SECRETO = 'appdepruebauno1', 'appdepruebados2', 'SecretoDePruebaDisplay_123'
CUENTA_PERSONAL = {'open_id': 'OPEN_ID_CUENTA_PERSONAL', 'union_id': 'UNION_ID_PERSONAL', 'username': 'cuenta_personal',
                   'videos': ('6100000000000000001', '6100000000000000002', '6100000000000000003')}
CUENTA_CREADOR = {'open_id': 'OPEN_ID_CREADOR', 'union_id': 'UNION_ID_CREADOR', 'username': USUARIO_DEMO,
                  'videos': ('6200000000000000001', '6200000000000000002')}
# La misma cuenta del creador en la app de OTRO desarrollador: otro open_id y otro union_id, los mismos videos.
CREADOR_OTRO_DESARROLLADOR = dict(CUENTA_CREADOR, open_id='OPEN_ID_CREADOR_DEV2', union_id='UNION_ID_CREADOR_DEV2')
CUENTA_OTRA = {'open_id': 'OPEN_ID_OTRA', 'union_id': 'UNION_ID_OTRA', 'username': 'otra_cuenta',
               'videos': ('6300000000000000001',)}                     # tampoco es la de la tienda
SOLO_HISTORIAL = '6200000000000000099'          # un video del creador que ya solo conserva historial
SIN_PERFIL = tuple(s for s in SCOPES if s != 'user.info.profile')     # sin 'los datos de tu perfil': no llega el nombre
SIN_VIDEOS = tuple(s for s in SCOPES if s != 'video.list')            # sin 'la lista de tus videos'


class DisplayDeDosCuentas:
    """Display API falsa (sin red) que responde como la cuenta que elija la prueba: open_id, union_id, nombre, permisos
    y videos propios. Como TikTok, user/info devuelve solo los campos pedidos (los de los permisos concedidos) y
    video/query solo los videos de la cuenta autorizada."""

    def __init__(self, reloj) -> None:
        self.reloj = reloj
        self.cuenta: dict = CUENTA_PERSONAL
        self.perfil = 'normal'                 # 'normal' · 'falla' (HTTP 503) · 'vacio' ({'user': {}})
        self.consulta_falla = False
        self.consultas: list[list[str]] = []
        self.emitidos: dict[str, list[str]] = {}       # open_id -> access_tokens entregados
        self.revocados: list[str] = []
        self.al_consultar = None               # gancho de una vez al empezar un video/query (para forzar carreras)
        self.al_listar = None                  # gancho de una vez al empezar un video/list
        self.al_perfil = None                  # gancho de una vez al empezar un user/info
        self._n = itertools.count(1)

    @staticmethod
    def _ok(data: dict):
        return 200, {'data': data, 'error': {'code': 'ok', 'message': '', 'log_id': 'prueba'}}

    @staticmethod
    def _falla():
        return 503, {'data': {}, 'error': {'code': 'internal_error', 'message': '', 'log_id': 'prueba'}}

    def _video(self, vid: str, n: int, ahora: int) -> dict:
        c = self.cuenta
        return {'id': vid, 'create_time': ahora - 86400 * (n + 1), 'title': f"Video de {c['username']} {n}",
                'duration': 15, 'view_count': 1000 + n, 'like_count': 50, 'comment_count': 3, 'share_count': 1}

    def manejar(self, metodo, url, cabeceras, cuerpo):
        u = urlsplit(url)
        ruta, c, ahora = u.path, self.cuenta, int(self.reloj.ahora())
        if ruta == '/v2/oauth/token/':
            n = next(self._n)
            self.emitidos.setdefault(c['open_id'], []).append(f'act.prueba-{n}')
            return 200, {'access_token': f'act.prueba-{n}', 'refresh_token': f'rft.prueba-{n}', 'expires_in': 7200,
                         'refresh_expires_in': 180 * 86400, 'open_id': c['open_id'],
                         'scope': ','.join(c.get('scopes', SCOPES)), 'token_type': 'Bearer'}
        if ruta == '/v2/oauth/revoke/':
            self.revocados += parse_qs((cuerpo or b'').decode('utf-8')).get('token', [])
            return 200, {}
        if ruta == '/v2/user/info/':
            gancho, self.al_perfil = self.al_perfil, None
            if gancho is not None:
                gancho()                       # `c` ya es la cuenta de ESTA llamada, aunque el gancho la cambie
            if self.perfil == 'falla':
                return self._falla()
            if self.perfil == 'vacio':
                return self._ok({'user': {}})
            campos = (parse_qs(u.query).get('fields') or [''])[0].split(',')
            user = {'open_id': c['open_id'], 'union_id': c['union_id'], 'display_name': c['username'],
                    'username': c['username'], 'follower_count': 10, 'following_count': 2, 'likes_count': 30,
                    'video_count': len(c['videos'])}
            return self._ok({'user': {k: v for k, v in user.items() if k in campos}})
        if ruta == '/v2/video/list/':
            gancho, self.al_listar = self.al_listar, None
            if gancho is not None:
                gancho()
            return self._ok({'videos': [self._video(v, n, ahora) for n, v in enumerate(c['videos'])], 'cursor': 0,
                             'has_more': False})
        if ruta == '/v2/video/query/':
            gancho, self.al_consultar = self.al_consultar, None
            if gancho is not None:
                gancho()                       # `c` ya es la cuenta de ESTA llamada, aunque el gancho la cambie
            if self.consulta_falla:
                return self._falla()
            pedidos = json.loads(cuerpo)['filters']['video_ids']
            self.consultas.append(list(pedidos))
            return self._ok({'videos': [self._video(v, n, ahora) for n, v in enumerate(c['videos']) if v in pedidos]})
        return 404, {'data': {}, 'error': {'code': 'invalid_params', 'message': '', 'log_id': 'prueba'}}


class CambioDeCuentaDisplayTests(HubSintetico):
    """La conexión de métricas pasa por el OAuth real (iniciar_conexion → callback → canje) contra una Display API
    falsa. Lo guardado solo se borra cuando se comprueba que es de otra cuenta (nunca aparece en el catálogo del
    creador), y nunca si se comprueba que es del creador: entonces se rechaza la cuenta nueva sin tocar nada."""

    @classmethod
    def preparar_display(cls, ahora: int) -> None:
        cls.falsa = DisplayDeDosCuentas(cls.hub.reloj)
        cls.hub.display.cliente.transporte = cls.falsa
        cls.hub.display.al_conectar = None              # cada prueba decide cuándo sincronizar

    def setUp(self) -> None:
        self.hub.display.desconectar(borrar_datos=True)
        self.hub.display.guardar_credenciales(APP_1, SECRETO)
        self.falsa.perfil, self.falsa.consulta_falla, self.falsa.consultas = 'normal', False, []
        self.falsa.emitidos, self.falsa.revocados, self.falsa.al_consultar, self.falsa.al_listar = {}, [], None, None
        self.falsa.al_perfil = None

    def reconectar_desde_otra_pestana(self, cuenta: dict, estados: list[int]) -> None:
        """Lo que haría otra pestaña a mitad de una sync: autorizar `cuenta` por el OAuth real (sin asserts: puede
        correr en el hilo de la sync)."""
        url = self.hub.display.iniciar_conexion()['url']
        self.falsa.cuenta = cuenta
        estados.append(self.hub.display.callback(urlencode({'state': parse_qs(urlsplit(url).query)['state'][0],
                                                            'code': 'codigo-de-otra-pestana'}))[0])

    def conectar(self, cuenta: dict, perfil: str = 'normal', consulta_falla: bool = False) -> int:
        self.falsa.cuenta, self.falsa.perfil, self.falsa.consulta_falla = cuenta, perfil, consulta_falla
        try:
            url = self.hub.display.iniciar_conexion()['url']
            state = parse_qs(urlsplit(url).query)['state'][0]
            status, _ = self.hub.display.callback(urlencode({'state': state, 'code': 'codigo-de-prueba'}))
        finally:
            self.falsa.perfil, self.falsa.consulta_falla = 'normal', False
        if status == 200:
            self.assertEqual(self.hub.display.boveda.leer().get('open_id'), cuenta['open_id'])
        return status

    def sincronizar_con(self, perfil: str) -> None:
        self.falsa.perfil = perfil
        try:
            self.sincronizar()
        finally:
            self.falsa.perfil = 'normal'

    def guardados(self) -> set[str]:
        with self.hub.almacen.lector() as db:
            return {r[0] for r in db.execute('SELECT video_id FROM videos_tiktok UNION '
                                             'SELECT video_id FROM videos_tiktok_dias')}

    def sembrar_historial(self, solo_historial: bool = True) -> None:
        """Hace siete días: una foto de cada video guardado, la del perfil y la de un video que ya solo conserva
        historial. La Display API no puede devolver nada de esto otra vez."""
        hace = int(self.hub.reloj.ahora()) - 7 * 86400
        fecha = self.sembrada = D.fecha_mx(hace)
        with self.hub.almacen.lector() as db:
            ids = [r[0] for r in db.execute('SELECT video_id FROM videos_tiktok ORDER BY video_id')]
        with self.hub.almacen.escritor() as db:
            for n, vid in enumerate([*ids, *([SOLO_HISTORIAL] if solo_historial else [])]):
                db.execute('INSERT INTO videos_tiktok_dias(video_id, fecha, vistas, likes, comentarios, compartidos, '
                           'actualizado_at) VALUES (?, ?, ?, 40, 2, 1, ?)', (vid, fecha, 900 + n, hace))
            db.execute('INSERT INTO perfil_tiktok_dias(fecha, seguidores, siguiendo, likes_total, videos_total, '
                       'actualizado_at) VALUES (?, 9, 2, 25, 2, ?)', (fecha, hace))

    def historial(self) -> tuple:
        """Las filas exactas del día sembrado (las de hoy las reescribe cada sync; cruzar la medianoche no cambia nada)."""
        with self.hub.almacen.lector() as db:
            return (tuple(tuple(r) for r in db.execute(
                        'SELECT video_id, fecha, vistas, likes, comentarios, compartidos FROM videos_tiktok_dias '
                        'WHERE fecha = ? ORDER BY video_id', (self.sembrada,))),
                    tuple(tuple(r) for r in db.execute(
                        'SELECT fecha, seguidores, siguiendo, likes_total, videos_total FROM perfil_tiktok_dias '
                        'WHERE fecha = ?', (self.sembrada,))))

    def creador_con_historial(self) -> tuple:
        self.assertEqual(self.conectar(CUENTA_CREADOR), 200)
        self.sincronizar()
        self.sembrar_historial()
        historial = self.historial()
        self.assertEqual(len(historial[0]), len(CUENTA_CREADOR['videos']) + 1)
        self.assertEqual(len(historial[1]), 1)
        return historial

    def assertSinVideosDe(self, cuenta: dict) -> None:
        ajenos = set(cuenta['videos'])
        self.assertFalse(self.guardados() & ajenos)
        for consulta in ('limite=2000', 'incluir=historial&limite=2000'):
            self.assertFalse(self.ids_catalogo(consulta) & ajenos, consulta)
        for vid in ajenos:
            self.assertEqual(self.api(f'/api/catalogo/videos/{vid}')[0], 404)

    def assertRechazada(self, mensaje: str = D.MSG_OTRA_CUENTA) -> None:
        conexion = self.hub.display.boveda.leer()
        self.assertFalse(conexion.get('access_token') or conexion.get('refresh_token') or conexion.get('open_id'))
        self.assertEqual(conexion['ultimo_error']['codigo'], 'solicitud_rechazada')
        self.assertEqual(conexion['ultimo_error']['mensaje'], mensaje)

    def assertSinDecidir(self) -> None:
        conexion = self.hub.display.boveda.leer()
        self.assertEqual((conexion['ultimo_error']['codigo'], conexion['ultimo_error']['mensaje']),
                         ('solicitud_rechazada', D.MSG_SIN_COMPROBAR))

    def username_guardado(self) -> str | None:
        with self.hub.almacen.lector() as db:
            return db.execute('SELECT username FROM perfil_tiktok WHERE id = 1').fetchone()[0]

    # ----------------------------------------------------------- otra cuenta sobre la del creador: se rechaza
    def test_autorizar_otra_cuenta_no_toca_el_historial_del_creador(self) -> None:
        historial = self.creador_con_historial()
        self.hub.display.desconectar(borrar_datos=False)                   # la opción por omisión de la interfaz
        self.falsa.revocados = []                                          # desconectar ya revocó la del creador
        self.assertEqual(self.conectar(CUENTA_PERSONAL), 409)
        self.assertRechazada()
        self.assertEqual(self.historial(), historial)
        self.assertFalse(self.guardados() & set(CUENTA_PERSONAL['videos']))
        self.assertEqual(self.falsa.revocados, self.falsa.emitidos[CUENTA_PERSONAL['open_id']])   # se revocó en TikTok
        self.assertEqual(self.conectar(CUENTA_CREADOR), 200)              # vuelve la cuenta correcta: todo sigue
        self.sincronizar()
        self.assertEqual(self.historial(), historial)
        cat = self.catalogo('incluir=historial&limite=2000')
        self.assertIs(cat['display']['misma_cuenta'], True)
        solo = {i['content_id']: i for i in cat['items']}[SOLO_HISTORIAL]
        self.assertEqual((solo['origen'], solo['publicacion']), ('display', 'no_publico'))

    def test_autorizar_otra_cuenta_estando_conectado_no_cambia_nada(self) -> None:
        historial = self.creador_con_historial()
        self.assertEqual(self.conectar(CUENTA_PERSONAL), 409)             # sin desconectar: la misma app, otro open_id
        conexion = self.hub.display.boveda.leer()
        self.assertEqual(conexion.get('open_id'), CUENTA_CREADOR['open_id'])   # la conexión del creador sigue igual
        self.assertTrue(conexion.get('access_token'))
        self.assertEqual((conexion['ultimo_error']['codigo'], conexion['ultimo_error']['mensaje']),
                         ('solicitud_rechazada', D.MSG_OTRA_CUENTA))
        self.assertEqual(self.historial(), historial)
        self.assertEqual(self.falsa.consultas, [])                       # misma app y otro open_id: no hizo falta preguntar
        self.assertEqual(self.falsa.revocados, self.falsa.emitidos[CUENTA_PERSONAL['open_id']])   # nunca la del creador
        self.falsa.cuenta = CUENTA_CREADOR
        self.sincronizar()                                               # y sigue sincronizando la cuenta del creador
        self.assertEqual(self.historial(), historial)
        self.assertIsNone(self.hub.display.boveda.leer().get('ultimo_error'))

    def test_la_sincronizacion_rechaza_otra_cuenta_sin_tocar_el_historial_del_creador(self) -> None:
        historial = self.creador_con_historial()
        self.hub.display.desconectar(borrar_datos=False)
        # Ni el perfil ni TikTok respondieron al conectar: no se decidió nada y la autorización quedó guardada.
        self.assertEqual(self.conectar(CUENTA_PERSONAL, perfil='falla', consulta_falla=True), 200)
        self.assertEqual(self.historial(), historial)
        self.falsa.revocados = []
        self.sincronizar()
        self.assertRechazada()
        self.assertEqual(self.falsa.revocados, self.falsa.emitidos[CUENTA_PERSONAL['open_id']])   # la de esa conexión
        self.assertEqual(self.historial(), historial)
        self.assertFalse(self.guardados() & set(CUENTA_PERSONAL['videos']))

    def test_otra_cuenta_sin_perfil_sobre_datos_del_creador_se_rechaza_al_conectar(self) -> None:
        historial = self.creador_con_historial()
        self.hub.display.desconectar(borrar_datos=False)
        self.falsa.revocados = []
        # Sin perfil no se sabe su nombre, pero TikTok ya prueba que los videos guardados no son suyos: son del creador.
        self.assertEqual(self.conectar(CUENTA_PERSONAL, perfil='falla'), 409)
        self.assertRechazada()
        self.assertEqual(self.falsa.revocados, self.falsa.emitidos[CUENTA_PERSONAL['open_id']])
        self.assertEqual(self.historial(), historial)

    def test_el_creador_puede_volver_tras_una_autorizacion_ajena_sin_decidir(self) -> None:
        historial = self.creador_con_historial()
        self.hub.display.desconectar(borrar_datos=False)
        self.assertEqual(self.conectar(CUENTA_PERSONAL, perfil='falla', consulta_falla=True), 200)   # sin decidir
        self.assertEqual(self.conectar(CUENTA_CREADOR), 200)          # la bóveda recuerda la ajena; lo guardado no es de ella
        self.assertEqual(self.historial(), historial)

    def test_rechazar_olvida_tambien_la_autorizacion_sin_decidir_de_esa_cuenta(self) -> None:
        historial = self.creador_con_historial()
        self.hub.display.desconectar(borrar_datos=False)
        self.falsa.revocados = []                                          # desconectar ya revocó la del creador
        # Sin el permiso de videos no se puede preguntar a TikTok: queda guardada, sin decidir y sin perfil.
        self.assertEqual(self.conectar(dict(CUENTA_PERSONAL, scopes=SIN_VIDEOS)), 200)
        self.assertEqual(self.username_guardado(), USUARIO_DEMO)
        self.assertEqual(self.conectar(CUENTA_PERSONAL), 409)               # con todos los permisos, se comprueba
        self.assertRechazada()                                             # y se olvida también la anterior
        self.assertEqual(sorted(self.falsa.revocados), sorted(self.falsa.emitidos[CUENTA_PERSONAL['open_id']]))
        self.assertEqual(self.historial(), historial)
        self.sincronizar()                                                 # sin conexión: nada que sincronizar
        self.assertRechazada()

    def test_si_la_conexion_cambia_mientras_la_sync_decide_no_anota_nada(self) -> None:
        historial = self.creador_con_historial()
        cursor = self.hub.almacen.lector
        with cursor() as db:
            antes = db.execute("SELECT valor FROM sync_cursores WHERE clave = 'display.ultima_sync'").fetchone()[0]
        self.hub.display.desconectar(borrar_datos=False)
        self.assertEqual(self.conectar(CUENTA_PERSONAL, perfil='falla', consulta_falla=True), 200)   # sin decidir
        estados: list[int] = []

        def el_creador_vuelve() -> None:     # dentro del video/query de la sync: el creador se reconecta en otra pestaña
            url = self.hub.display.iniciar_conexion()['url']
            self.falsa.cuenta = CUENTA_CREADOR
            estados.append(self.hub.display.callback(urlencode({'state': parse_qs(urlsplit(url).query)['state'][0],
                                                                'code': 'otro-codigo'}))[0])
        self.falsa.cuenta, self.falsa.al_consultar = CUENTA_PERSONAL, el_creador_vuelve
        self.sincronizar()
        self.assertEqual(estados, [200])
        conexion = self.hub.display.boveda.leer()
        self.assertEqual(conexion.get('open_id'), CUENTA_CREADOR['open_id'])
        self.assertIsNone(conexion.get('ultimo_error'))                    # nada de «otra cuenta» sobre la del creador
        with cursor() as db:
            despues = db.execute("SELECT valor FROM sync_cursores WHERE clave = 'display.ultima_sync'").fetchone()[0]
        self.assertEqual(despues, antes)                                   # esa pasada no se registró
        with cursor() as db:
            resumen = json.loads(db.execute('SELECT resumen_json FROM sync_ejecuciones '
                                            'ORDER BY sync_id DESC LIMIT 1').fetchone()[0])
        self.assertEqual(resumen['videos_tiktok']['codigo'], 'sin_conexion')   # terminó por el cambio, no por un rechazo
        self.assertEqual(self.historial(), historial)

    def test_lo_que_la_sync_leyo_de_otra_conexion_no_se_guarda(self) -> None:
        historial = self.creador_con_historial()
        self.hub.display.desconectar(borrar_datos=False)
        self.assertEqual(self.conectar(CUENTA_PERSONAL, perfil='falla', consulta_falla=True), 200)   # sin decidir
        estados: list[int] = []
        # La sync lee el perfil de la cuenta ajena; mientras tanto el creador se reconecta, y su video/query ya va con
        # el token del creador (devuelve sus videos). Nada de lo leído con la conexión anterior debe guardarse.
        self.falsa.cuenta = CUENTA_PERSONAL
        self.falsa.al_perfil = lambda: self.reconectar_desde_otra_pestana(CUENTA_CREADOR, estados)
        self.sincronizar()
        self.assertEqual(estados, [200])
        self.assertEqual(self.username_guardado(), USUARIO_DEMO)        # el perfil ajeno no pisó al del creador
        conexion = self.hub.display.boveda.leer()
        self.assertEqual((conexion.get('open_id'), conexion.get('ultimo_error')), (CUENTA_CREADOR['open_id'], None))
        self.assertEqual(self.historial(), historial)

    def test_una_pagina_traida_con_otra_conexion_no_se_guarda(self) -> None:
        self.creador_con_historial()
        uno = CUENTA_CREADOR['videos'][0]
        with self.hub.almacen.lector() as db:
            visto = db.execute('SELECT visto_at FROM videos_tiktok WHERE video_id = ?', (uno,)).fetchone()[0]
        estados: list[int] = []
        self.falsa.cuenta = CUENTA_CREADOR
        self.falsa.al_listar = lambda: self.reconectar_desde_otra_pestana(CUENTA_CREADOR, estados)   # sube la época
        real = self.hub.reloj.ahora
        with patch.object(self.hub.reloj, 'ahora', lambda: real() + 100):
            self.sincronizar()
        self.assertEqual(estados, [200])
        with self.hub.almacen.lector() as db:
            self.assertEqual(db.execute('SELECT visto_at FROM videos_tiktok WHERE video_id = ?', (uno,)).fetchone()[0],
                             visto)                                        # esa página no se escribió
        self.assertIsNone(self.hub.display.boveda.leer().get('ultimo_error'))

    def test_una_respuesta_sin_nombre_no_borra_la_prueba_de_que_los_datos_son_del_creador(self) -> None:
        historial = self.creador_con_historial()
        self.sincronizar_con('vacio')
        self.assertEqual(self.username_guardado(), USUARIO_DEMO)
        self.hub.display.desconectar(borrar_datos=False)
        self.assertEqual(self.conectar(dict(CUENTA_CREADOR, scopes=SIN_PERFIL)), 200)   # misma app, sin el permiso
        self.assertEqual(self.username_guardado(), USUARIO_DEMO)
        self.assertEqual(self.conectar(CUENTA_PERSONAL), 409)
        self.assertEqual(self.historial(), historial)

    def test_datos_del_creador_sin_nombre_tampoco_se_borran_por_otra_cuenta(self) -> None:
        self.assertEqual(self.conectar(dict(CUENTA_CREADOR, scopes=SIN_PERFIL)), 200)   # nunca dio el permiso de perfil
        self.sincronizar()
        self.sembrar_historial()
        historial = self.historial()
        self.assertIsNone(self.username_guardado())
        self.assertEqual(self.conectar(CUENTA_PERSONAL), 409)       # otra cuenta que tampoco es la de la tienda
        self.assertEqual(self.historial(), historial)
        self.assertFalse(self.guardados() & set(CUENTA_PERSONAL['videos']))

    def test_otra_cuenta_que_tampoco_es_la_de_la_tienda_no_borra_nada(self) -> None:
        self.assertEqual(self.conectar(CUENTA_PERSONAL), 200)
        self.sincronizar()
        self.hub.display.desconectar(borrar_datos=False)
        self.assertEqual(self.conectar(CUENTA_OTRA), 409)
        self.assertEqual(self.guardados(), set(CUENTA_PERSONAL['videos']))   # borrar no protegía nada
        self.assertRechazada()

    # ----------------------------------------------------------- sin pruebas: no se decide nada
    def test_sin_videos_que_comprobar_no_se_borra_ni_se_rechaza_nada(self) -> None:
        self.assertEqual(self.conectar(dict(CUENTA_CREADOR, scopes=SIN_VIDEOS)), 200)   # solo perfil y su historial
        self.sincronizar()
        self.sembrar_historial(solo_historial=False)
        historial = self.historial()
        self.assertFalse(self.guardados())
        self.hub.display.desconectar(borrar_datos=False)
        self.assertEqual(self.conectar(dict(CREADOR_OTRO_DESARROLLADOR, scopes=SIN_PERFIL)), 200)
        self.assertEqual(self.falsa.consultas, [])                     # nada que preguntar
        self.assertEqual(self.historial(), historial)
        self.sincronizar()
        self.assertSinDecidir()
        self.assertEqual(self.historial(), historial)

    def test_sin_videos_que_comprobar_el_creador_no_queda_rechazado(self) -> None:
        self.assertEqual(self.conectar(dict(CUENTA_CREADOR, scopes=SIN_VIDEOS)), 200)
        self.sincronizar()
        self.sembrar_historial(solo_historial=False)
        historial = self.historial()
        self.hub.display.desconectar(borrar_datos=False)
        self.assertEqual(self.conectar(CREADOR_OTRO_DESARROLLADOR, perfil='falla'), 200)   # antes: 409 a su propia cuenta
        self.sincronizar()                                             # con el perfil completo: el mismo nombre
        self.assertEqual(self.historial(), historial)
        self.assertIsNone(self.hub.display.boveda.leer().get('ultimo_error'))

    def test_videos_que_ya_no_son_publicos_no_prueban_otra_cuenta(self) -> None:
        historial = self.creador_con_historial()
        self.escribir('DELETE FROM videos_tiktok')                      # todos pasaron a privados: solo queda historial
        self.hub.display.desconectar(borrar_datos=False)
        privado = dict(CREADOR_OTRO_DESARROLLADOR, scopes=SIN_PERFIL, videos=())   # TikTok ya no los devuelve
        self.assertEqual(self.conectar(privado), 200)
        self.assertTrue(self.falsa.consultas)                          # preguntó, pero TikTok no devuelve los privados
        self.assertEqual(self.historial(), historial)
        self.falsa.cuenta = privado
        self.sincronizar()
        self.assertSinDecidir()
        self.assertEqual(self.historial(), historial)

    def test_sin_decidir_no_se_guarda_el_perfil_nuevo(self) -> None:
        self.assertEqual(self.conectar(CUENTA_PERSONAL), 200)
        self.sincronizar()
        self.hub.display.desconectar(borrar_datos=False)
        self.assertEqual(self.conectar(CREADOR_OTRO_DESARROLLADOR, consulta_falla=True), 200)   # perfil sí, TikTok no
        self.assertEqual(self.username_guardado(), CUENTA_PERSONAL['username'])
        self.assertIs(self.catalogo()['display']['misma_cuenta'], False)   # nada de la otra cuenta pasa por del creador
        self.assertEqual(self.guardados(), set(CUENTA_PERSONAL['videos']))

    # ----------------------------------------------------------- el borrado y la autorización van juntos
    def test_si_lo_guardado_cambia_antes_de_borrar_se_vuelve_a_decidir(self) -> None:
        self.assertEqual(self.conectar(CUENTA_PERSONAL), 200)
        self.sincronizar()
        self.hub.display.desconectar(borrar_datos=False)
        coordinador = self.hub.display.coordinador
        original = coordinador.mutacion_segura

        def y_mientras_tanto(*args):
            original(*args)
            self.escribir('UPDATE perfil_tiktok SET username = ? WHERE id = 1', (USUARIO_DEMO,))   # ahora es del creador
        with patch.object(coordinador, 'mutacion_segura', y_mientras_tanto):
            self.assertEqual(self.conectar(CUENTA_CREADOR), 200)
        self.assertEqual(self.guardados(), set(CUENTA_PERSONAL['videos']))   # la nueva decisión fue 'misma'

    def test_si_la_conexion_cambia_antes_de_guardar_no_se_borra_nada(self) -> None:
        self.assertEqual(self.conectar(CUENTA_PERSONAL), 200)
        self.sincronizar()
        self.hub.display.desconectar(borrar_datos=False)
        coordinador = self.hub.display.coordinador
        original = coordinador.mutacion_segura

        def y_mientras_tanto(*args):
            original(*args)
            self.hub.display.guardar_credenciales(APP_2, SECRETO)     # otra pestaña cambia la app
        with patch.object(coordinador, 'mutacion_segura', y_mientras_tanto):
            self.assertEqual(self.conectar(CUENTA_CREADOR), 409)
        self.assertEqual(self.guardados(), set(CUENTA_PERSONAL['videos']))   # el borrado se deshizo con el 409

    # ----------------------------------------------------------- el cursor de cada pasada
    def test_el_cursor_guarda_el_visto_at_mas_reciente_y_la_pasada_en_curso(self) -> None:
        self.creador_con_historial()
        uno = CUENTA_CREADOR['videos'][0]
        with self.hub.almacen.lector() as db:
            tope = db.execute('SELECT MAX(visto_at) FROM videos_tiktok').fetchone()[0]
        self.escribir('UPDATE videos_tiktok SET visto_at = visto_at - 50 WHERE video_id = ?', (uno,))
        real = self.hub.reloj.ahora
        with patch.object(self.hub.reloj, 'ahora', lambda: real() + 100):
            self.sincronizar_con('falla')                             # pasada registrada que no vio ningún video
        with self.hub.almacen.lector() as db:
            pasada = json.loads(db.execute("SELECT valor FROM sync_cursores "
                                           "WHERE clave = 'display.ultima_sync'").fetchone()[0])
            pendiente = db.execute('SELECT 1 FROM sync_cursores WHERE clave = ?', (D.CLAVE_SIN_REGISTRAR,)).fetchone()
        self.assertGreater(pasada['at'], tope)
        self.assertEqual(pasada['visto_tope'], tope)                   # el MÁXIMO de visto_at, no el instante ni el mínimo
        self.assertIsNone(pendiente)
        vistas: list = []

        def mirar() -> None:                                           # durante el listado de la siguiente pasada
            with self.hub.almacen.lector() as db:
                vistas.append(D.pasadas_sin_registrar(db))
        self.falsa.al_listar = mirar
        self.sincronizar()
        self.assertEqual(len(vistas), 1)
        self.assertEqual(len(vistas[0]), 1)                            # su propio instante, mientras no se registra
        with self.hub.almacen.lector() as db:
            self.assertEqual(D.pasadas_sin_registrar(db), [])          # y se borra al registrarla

    # ----------------------------------------------------------- otra cuenta comprobada: se borra
    def test_desconectar_sin_borrar_y_conectar_al_creador_borra_la_otra_cuenta(self) -> None:
        self.assertEqual(self.conectar(CUENTA_PERSONAL), 200)
        self.sincronizar()
        self.assertEqual(self.guardados(), set(CUENTA_PERSONAL['videos']))
        self.assertIs(self.catalogo()['display']['misma_cuenta'], False)
        self.assertFalse(self.ids_catalogo('incluir=historial&limite=2000') & set(CUENTA_PERSONAL['videos']))
        self.hub.display.desconectar(borrar_datos=False)
        self.assertEqual(self.guardados(), set(CUENTA_PERSONAL['videos']))  # conserva los datos…
        self.assertIsNone(self.hub.display.boveda.leer().get('open_id'))    # …pero olvida la cuenta
        self.assertEqual(self.conectar(CUENTA_CREADOR), 200)
        self.assertSinVideosDe(CUENTA_PERSONAL)
        self.assertTrue(self.falsa.consultas)                            # TikTok confirmó que no eran del creador
        self.sincronizar()
        cat = self.catalogo()
        self.assertIs(cat['display']['misma_cuenta'], True)
        propios = {i['content_id']: i for i in cat['items'] if i['origen'] == 'display'}
        self.assertEqual(set(propios), set(CUENTA_CREADOR['videos']))
        self.assertEqual({i['publicacion'] for i in propios.values()}, {'publico'})
        self.assertSinVideosDe(CUENTA_PERSONAL)

    def test_cambiar_de_app_y_conectar_al_creador_borra_la_otra_cuenta(self) -> None:
        self.assertEqual(self.conectar(CUENTA_PERSONAL), 200)
        self.sincronizar()
        self.hub.display.guardar_credenciales(APP_2, SECRETO)       # los tokens y el open_id eran de la app anterior
        self.assertIsNone(self.hub.display.boveda.leer().get('open_id'))
        self.assertEqual(self.conectar(CUENTA_CREADOR), 200)
        self.assertSinVideosDe(CUENTA_PERSONAL)

    def test_si_el_perfil_falla_al_conectar_decide_la_sincronizacion(self) -> None:
        self.assertEqual(self.conectar(CUENTA_PERSONAL), 200)
        self.sincronizar()
        self.hub.display.desconectar(borrar_datos=False)
        self.assertEqual(self.conectar(CUENTA_CREADOR, perfil='falla'), 200)
        self.assertTrue(self.falsa.consultas)                        # TikTok dijo «no son míos»…
        self.assertEqual(self.guardados(), set(CUENTA_PERSONAL['videos']))   # …pero sin nombre no se sabe si es la tienda
        self.sincronizar()
        self.assertEqual(self.guardados(), set(CUENTA_CREADOR['videos']))
        self.assertSinVideosDe(CUENTA_PERSONAL)
        self.assertIs(self.catalogo()['display']['misma_cuenta'], True)

    def test_sin_poder_comprobar_al_conectar_decide_la_sincronizacion(self) -> None:
        self.assertEqual(self.conectar(CUENTA_PERSONAL), 200)
        self.sincronizar()
        self.hub.display.desconectar(borrar_datos=False)
        coordinador = self.hub.display.coordinador
        with patch.object(coordinador, 'mutacion_segura', wraps=coordinador.mutacion_segura) as detener:
            self.assertEqual(self.conectar(CUENTA_CREADOR, perfil='falla', consulta_falla=True), 200)
        detener.assert_called_once_with(None, 'nada')        # ninguna pasada en curso usa una autorización sin decidir
        self.assertEqual(self.guardados(), set(CUENTA_PERSONAL['videos']))   # sin decidir no se borra ni se guarda…
        self.assertIs(self.catalogo()['display']['misma_cuenta'], False)     # …ni se lista nada sin ventas
        self.sincronizar()
        self.assertEqual(self.guardados(), set(CUENTA_CREADOR['videos']))
        self.assertSinVideosDe(CUENTA_PERSONAL)
        self.assertIs(self.catalogo()['display']['misma_cuenta'], True)

    def test_una_respuesta_de_perfil_vacia_no_abre_la_puerta_a_otra_cuenta(self) -> None:
        self.assertEqual(self.conectar(CUENTA_PERSONAL), 200)
        self.sincronizar()
        self.sincronizar_con('vacio')                                 # el perfil guardado se queda solo con el open_id
        self.hub.display.desconectar(borrar_datos=False)
        self.assertEqual(self.conectar(CUENTA_CREADOR), 200)
        self.assertSinVideosDe(CUENTA_PERSONAL)

    # ----------------------------------------------------------- la misma cuenta: se conserva
    def test_la_misma_cuenta_conserva_su_historial(self) -> None:
        historial = self.creador_con_historial()
        self.hub.display.desconectar(borrar_datos=False)
        self.assertEqual(self.conectar(CUENTA_CREADOR), 200)
        self.assertEqual(self.historial(), historial)
        self.sincronizar()
        self.assertEqual(self.historial(), historial)
        self.hub.display.guardar_credenciales(APP_2, SECRETO)
        self.assertEqual(self.conectar(dict(CUENTA_CREADOR, open_id='OPEN_ID_CREADOR_EN_APP_2')), 200)
        self.assertEqual(self.historial(), historial)
        self.sincronizar()
        self.assertEqual(self.guardados(), set(CUENTA_CREADOR['videos']) | {SOLO_HISTORIAL})
        self.assertEqual(self.historial(), historial)

    def test_sin_poder_comprobar_al_conectar_la_sincronizacion_reconoce_al_creador_por_su_nombre(self) -> None:
        historial = self.creador_con_historial()
        self.hub.display.guardar_credenciales(APP_2, SECRETO)
        self.assertEqual(self.conectar(CREADOR_OTRO_DESARROLLADOR, perfil='falla', consulta_falla=True), 200)
        self.assertEqual(self.historial(), historial)
        self.sincronizar()                                           # otro open_id y union_id, el mismo nombre
        self.assertEqual(self.historial(), historial)

    def test_la_misma_cuenta_con_otro_nombre_en_app_de_otro_desarrollador_conserva_su_historial(self) -> None:
        historial = self.creador_con_historial()
        self.escribir("UPDATE perfil_tiktok SET username = 'creador_demo_antes' WHERE id = 1")   # se guardó con su nombre anterior
        self.hub.display.guardar_credenciales(APP_2, SECRETO)
        self.assertEqual(self.conectar(CREADOR_OTRO_DESARROLLADOR), 200)
        self.assertTrue(self.falsa.consultas)                        # ningún identificador coincidía: preguntó a TikTok
        self.assertEqual(self.historial(), historial)
        self.sincronizar()
        self.assertEqual(self.historial(), historial)
        self.assertIs(self.catalogo()['display']['misma_cuenta'], True)

    def test_la_misma_cuenta_sin_permiso_de_perfil_en_app_de_otro_desarrollador_conserva_su_historial(self) -> None:
        historial = self.creador_con_historial()
        self.hub.display.guardar_credenciales(APP_2, SECRETO)
        self.assertEqual(self.conectar(dict(CREADOR_OTRO_DESARROLLADOR, scopes=SIN_PERFIL)), 200)
        self.assertEqual(self.historial(), historial)
        self.sincronizar()
        self.assertEqual(self.historial(), historial)

    def test_una_respuesta_de_perfil_vacia_no_borra_el_historial(self) -> None:
        historial = self.creador_con_historial()
        self.sincronizar_con('vacio')                                 # sin open_id ni nombre: vale el de la conexión
        self.assertEqual(self.historial(), historial)
        self.assertEqual(self.falsa.consultas, [])                   # el open_id de la conexión bastó para decidir
        with self.hub.almacen.lector() as db:
            self.assertEqual(db.execute('SELECT open_id FROM perfil_tiktok WHERE id = 1').fetchone()[0],
                             CUENTA_CREADOR['open_id'])                 # y el perfil guardado no lo pierde
        self.sincronizar()
        self.assertEqual(self.historial(), historial)
        self.assertIs(self.catalogo()['display']['misma_cuenta'], True)

    def test_una_respuesta_de_perfil_vacia_al_conectar_no_borra_el_historial(self) -> None:
        historial = self.creador_con_historial()
        self.hub.display.desconectar(borrar_datos=False)
        self.assertEqual(self.conectar(CUENTA_CREADOR, perfil='vacio'), 200)
        self.assertEqual(self.historial(), historial)
        self.assertEqual(self.falsa.consultas, [])                   # el open_id del canje bastó para decidir
        with self.hub.almacen.lector() as db:
            self.assertEqual(db.execute('SELECT open_id FROM perfil_tiktok WHERE id = 1').fetchone()[0],
                             CUENTA_CREADOR['open_id'])

    # ----------------------------------------------------------- la importación de la nube usa la misma regla
    def archivo(self, cuenta: dict, client_key: str) -> dict:
        ahora = int(self.hub.reloj.ahora())
        return {'client_key': client_key, 'client_secret': SECRETO, 'access_token': 'act.prueba-importada-1',
                'refresh_token': 'rft.prueba-importada-1', 'access_expira_at': ahora + 86400,
                'refresh_expira_at': ahora + 30 * 86400, 'open_id': cuenta['open_id'], 'scopes': list(SCOPES),
                'conectada_at': ahora - 60, 'origen': 'importado'}

    def test_importar_al_creador_borra_lo_guardado_sin_nombre_de_otra_cuenta(self) -> None:
        self.assertEqual(self.conectar(dict(CUENTA_PERSONAL, scopes=SIN_PERFIL)), 200)
        self.sincronizar()
        with self.hub.almacen.lector() as db:
            self.assertIsNone(db.execute('SELECT username FROM perfil_tiktok WHERE id = 1').fetchone()[0])
        self.hub.display.desconectar(borrar_datos=False)
        self.falsa.cuenta = CUENTA_CREADOR
        self.assertTrue(import_display(self.hub, self.archivo(CUENTA_CREADOR, APP_1))['ok'])
        self.assertSinVideosDe(CUENTA_PERSONAL)
        self.sincronizar()
        self.assertEqual(self.guardados(), set(CUENTA_CREADOR['videos']))
        self.assertIs(self.catalogo()['display']['misma_cuenta'], True)

    def test_importar_al_creador_que_cambio_de_nombre_conserva_su_historial(self) -> None:
        historial = self.creador_con_historial()
        self.hub.display.desconectar(borrar_datos=False)
        renombrado = dict(CUENTA_CREADOR, username='creador_renombrado')
        self.escribir("UPDATE cuenta SET username = 'creador_renombrado' WHERE id = 1")   # la tienda ya tiene el nuevo
        try:
            self.falsa.cuenta = renombrado
            self.assertTrue(import_display(self.hub, self.archivo(renombrado, APP_1))['ok'])   # misma app y open_id
            self.assertEqual(self.historial(), historial)
            self.assertEqual(self.username_guardado(), 'creador_renombrado')
            self.assertIs(self.catalogo()['display']['misma_cuenta'], True)
        finally:
            self.escribir('UPDATE cuenta SET username = ? WHERE id = 1', (USUARIO_DEMO,))

    def test_importar_al_creador_conserva_su_historial_guardado_sin_nombre(self) -> None:
        self.assertEqual(self.conectar(dict(CUENTA_CREADOR, scopes=SIN_PERFIL)), 200)
        self.sincronizar()
        self.sembrar_historial()
        historial = self.historial()
        self.hub.display.desconectar(borrar_datos=False)
        self.falsa.cuenta = CREADOR_OTRO_DESARROLLADOR
        self.assertTrue(import_display(self.hub, self.archivo(CREADOR_OTRO_DESARROLLADOR, APP_2))['ok'])
        self.assertEqual(self.historial(), historial)


class ComparacionDeCuentaTests(unittest.TestCase):
    """Las reglas de `datos`, sobre el esquema real en memoria."""

    def base(self, tienda: str | None = 'creador_demo', perfil: tuple | None = None, videos: tuple = (),
             historial: tuple = (), vendidos: tuple = ()) -> sqlite3.Connection:
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript(ESQUEMA)
        if tienda:
            db.execute("INSERT INTO cuenta(id, creator_open_id, username, actualizado_at) VALUES (1, 'shop', ?, 1)",
                       (tienda,))
        if perfil is not None:
            db.execute('INSERT INTO perfil_tiktok(id, open_id, union_id, username, actualizado_at) VALUES (1, ?, ?, ?, 1)',
                       perfil)
        for n, vid in enumerate(videos):
            db.execute('INSERT INTO videos_tiktok(video_id, visto_at, primera_vez_at, actualizado_at) VALUES (?, ?, 1, 1)',
                       (vid, 100 + n))
        for n, vid in enumerate(historial):
            db.execute('INSERT INTO videos_tiktok_dias(video_id, fecha, actualizado_at) VALUES (?, ?, 1)',
                       (vid, f'2026-10-{n + 1:02d}'))
        if vendidos:
            db.execute("INSERT INTO ordenes(order_id, creada_at, estado, huella, actualizado_at) "
                       "VALUES ('O1', 1, 'SETTLED', 'h', 1)")
            for n, vid in enumerate(vendidos):
                db.execute("INSERT INTO orden_lineas(order_id, linea_n, product_id, cantidad, tipo_contenido, content_id) "
                           "VALUES ('O1', ?, 'P1', 1, 'VIDEO', ?)", (n, vid))
        return db

    def test_los_perfiles_solo_prueban_la_misma_cuenta(self) -> None:
        creador = ('OID_1', 'UID_1', 'creador_demo')
        casos = [
            ('mismo open_id, nombre nuevo', {'open_id': 'OID_1', 'username': 'nombre_nuevo'}, 'misma'),
            ('otra app del mismo desarrollador', {'open_id': 'OID_2', 'union_id': 'UID_1'}, 'misma'),
            ('otra app, mismo nombre', {'open_id': 'OID_2', 'union_id': 'UID_2', 'username': '@Creador_Demo'}, 'misma'),
            ('otro nombre: pudo cambiarlo', {'open_id': 'OID_2', 'union_id': 'UID_2', 'username': 'cuenta_personal'},
             None),
            ('sin nombre para comparar', {'open_id': 'OID_2'}, None),
        ]
        for nombre, nuevo, esperado in casos:
            with self.subTest(nombre):
                self.assertEqual(D.comparar_cuenta(self.base(perfil=creador), nuevo), esperado)

    def test_ambos_verificablemente_del_creador_son_la_misma_cuenta(self) -> None:
        sin_nombre = ('OID_X', None, None)
        nuevo = {'open_id': 'OID_Y', 'username': 'creador_demo'}
        self.assertEqual(D.comparar_cuenta(self.base(perfil=sin_nombre, videos=('7001',), vendidos=('7001',)), nuevo),
                         'misma')
        self.assertIsNone(D.comparar_cuenta(self.base(perfil=sin_nombre, videos=('7001',)), nuevo))
        self.assertIsNone(D.comparar_cuenta(self.base(perfil=sin_nombre, videos=('7001',), vendidos=('7001',)),
                                            {'open_id': 'OID_Y', 'username': 'cuenta_personal'}))
        self.assertIsNone(D.comparar_cuenta(self.base(tienda=None, perfil=sin_nombre, videos=('7001',),
                                                      vendidos=('7001',)), nuevo))

    def test_datos_del_creador(self) -> None:
        self.assertTrue(D.datos_del_creador(self.base(perfil=('O', None, '@Creador_Demo'))))
        self.assertTrue(D.datos_del_creador(self.base(perfil=('O', None, None), historial=('7002',),
                                                      vendidos=('7002',))))        # un video con ventas, solo en historial
        self.assertFalse(D.datos_del_creador(self.base(perfil=('O', None, 'cuenta_personal'), videos=('7003',))))
        self.assertFalse(D.datos_del_creador(self.base(tienda=None, perfil=('O', None, 'creador_demo'))))

    def test_videos_para_comprobar(self) -> None:
        db = self.base(videos=('7100', '7200', '0123'), historial=('7300', '7100', '7' * 21))
        self.assertEqual(D.videos_para_comprobar(db), ['7200', '7100', '7300'])   # visto más reciente primero
        muchos = self.base(videos=tuple(str(7_000 + n) for n in range(30)))
        self.assertEqual(len(D.videos_para_comprobar(muchos)), D.MAX_IDS_COMPROBAR)

    def test_alguno_publico(self) -> None:
        db = self.base(videos=('7100',), historial=('7200',))
        self.assertTrue(D.alguno_publico(db, ['7200', '7100']))
        self.assertFalse(D.alguno_publico(db, ['7200']))                # solo historial: TikTok no lo devolvería
        self.assertFalse(D.alguno_publico(db, []))

    def test_guardar_perfil_conserva_la_identidad_solo_de_la_misma_cuenta(self) -> None:
        db = self.base(perfil=('OID', 'UID', 'creador_demo'))
        D.guardar_perfil(db, {'open_id': 'OID', 'seguidores': 5}, 1_795_000_000, conservar_identidad=True)
        self.assertEqual(tuple(db.execute('SELECT open_id, union_id, username, seguidores FROM perfil_tiktok').fetchone()),
                         ('OID', 'UID', 'creador_demo', 5))             # sin el permiso de perfil no se pierde la prueba
        D.guardar_perfil(db, {'open_id': 'OID2'}, 1_795_000_000)        # sin decidir «misma»: lo que diga la respuesta
        self.assertEqual(tuple(db.execute('SELECT open_id, union_id, username FROM perfil_tiktok').fetchone()),
                         ('OID2', None, None))

    def test_una_foto_del_dia_sin_cifras_no_pisa_la_real(self) -> None:
        db = self.base()
        D.guardar_perfil(db, {'open_id': 'OID', 'seguidores': 10, 'likes_total': 30}, 1_795_000_000)
        D.guardar_perfil(db, {'open_id': 'OID'}, 1_795_000_100)
        self.assertEqual(db.execute('SELECT seguidores, likes_total FROM perfil_tiktok_dias').fetchall(), [(10, 30)])

    def test_hay_datos(self) -> None:
        self.assertFalse(D.hay_datos(self.base()))
        self.assertTrue(D.hay_datos(self.base(historial=('7001',))))
        self.assertTrue(D.hay_datos(self.base(perfil=(None, None, None))))


class FotosSinVideoTests(unittest.TestCase):
    def test_mas_de_500_ids_llegan_completos_con_su_foto_mas_reciente(self) -> None:
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript(ESQUEMA)
        if hasattr(db, 'setlimit'):                     # el límite clásico de 999 variables: exige las tandas
            db.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
        ids = [str(7_000_000_000_000_000_000 + n) for n in range(1_201)]
        db.executemany('INSERT INTO videos_tiktok_dias VALUES (?, ?, ?, ?, ?, ?, ?)',
                       [f for n, v in enumerate(ids)
                        for f in ((v, '2026-11-01', n, 0, 0, 0, 100), (v, '2026-11-10', n + 10_000, 1, 2, 3, 200))])
        listado = ids[-1]                               # sigue en videos_tiktok: no es un video «sin video»
        db.execute('INSERT INTO videos_tiktok(video_id, visto_at, primera_vez_at, actualizado_at) VALUES (?, 1, 1, 1)',
                   (listado,))
        fotos = display_api.fotos_sin_video(db, ids=[*ids, ids[700], '7999999999999999999'])   # 3 tandas
        esperados = ids[:-1]
        self.assertEqual([v for v in esperados if v not in fotos], [])
        self.assertEqual(sorted(set(fotos) - set(esperados)), [])
        self.assertEqual([v for n, v in enumerate(esperados)
                          if fotos[v] != {'fecha': '2026-11-10', 'vistas': n + 10_000, 'likes': 1, 'comentarios': 2,
                                          'compartidos': 3, 'actualizado_at': 200}], [])


class OrdenCatalogoTests(unittest.TestCase):
    def test_sin_fecha_ni_vistas_van_al_final(self) -> None:
        def item(cid: str, publicado: int | None, vistas: int | None, venta: str | None, comision: int = 0) -> dict:
            return {'content_id': cid, 'publicado_at': publicado, 'vistas': vistas,
                    'ventas': {'ultima_venta': venta, 'comision_estimada_centavos': comision} if venta else None}
        items = [item('1', None, None, '2026-01-01', 50), item('2', 100, 5, None), item('3', None, None, '2026-02-01', 300),
                 item('4', 200, 9, '2026-03-01', 100)]

        def orden(o: str) -> list[str]:
            return [i['content_id'] for i in Vista._orden_catalogo(items, o)]
        self.assertEqual(orden('publicado'), ['4', '2', '3', '1'])   # sin fecha al final, la venta más reciente primero
        self.assertEqual(orden('vistas'), ['4', '2', '1', '3'])      # sin vistas al final
        self.assertEqual(orden('comision'), ['3', '4', '1', '2'])    # sin ventas al final


class UsuarioNormalizadoTests(unittest.TestCase):
    def test_normaliza_y_rechaza_valores_raros(self) -> None:
        self.assertEqual(D.usuario_normalizado(' @Creador.Demo_1 '), 'creador.demo_1')
        for raro in (None, '', '@', 'con espacio', 'ñandú', 7, 'x' * 129):
            with self.subTest(raro=raro):
                self.assertEqual(D.usuario_normalizado(raro), '')


if __name__ == '__main__':
    unittest.main()
