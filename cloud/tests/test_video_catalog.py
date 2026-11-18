"""Catálogo de videos sin depender de las ventas (rev. 6): GET /api/catalogo/videos y /api/catalogo/videos/{id}.

Corre un hub REAL en modo nube con los transportes falsos de la demo (TikTok Shop y Display API: datos sintéticos,
sin firmas ni red) y una sincronización completa. Nunca lee una conexión del operador ni llama a TikTok.
"""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'hub'))

from creatorhub.demo import sinteticos
from creatorhub.demo.transporte import TransporteApiFalsa
from creatorhub.hub import iniciar_hub
from creatorhub.interfaces import CTX_UI, OpcionesHub
from creatorhub.tiktok_dev.boveda import datos_demo
from creatorhub.tiktok_dev.datos import usuario_normalizado
from creatorhub.tiktok_dev.demo import VIDEOS_SIN_VENTA, TransporteDisplayDemo


class ConSyncSintetica(unittest.TestCase):
    """Una sincronización completa (TikTok Shop + Display API de la demo) por clase."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.carpeta = tempfile.TemporaryDirectory()
        cls.env = patch.dict(os.environ, {'CORTE_PUBLIC_URL': 'https://corte.example',
                                          'CORTE_ENCRYPTION_KEY': 'synthetic-master-' * 4})
        cls.env.start()
        cls.hub = iniciar_hub(OpcionesHub(modo='real', nube=True, sin_lan=True, raiz_datos=cls.carpeta.name,
                                          sync_al_iniciar=False))
        try:
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
            cls.hub.display.boveda.mutar(lambda d: d.update(datos_demo(ahora)), cambia_credenciales=True)
            cls.hub.display.cliente.transporte = TransporteDisplayDemo(cls.hub.reloj)
            cls.hub.sincronizador.iniciar('completa', 'usuario')
            if not cls.hub.sincronizador._actual.fin.wait(600):
                raise AssertionError('La sincronización sintética no terminó')
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.hub.detener(10)
        cls.env.stop()
        cls.carpeta.cleanup()

    def api(self, ruta: str, consulta: str = '', cabeceras: dict | None = None):
        r = self.hub.despachador.despachar('GET', ruta, consulta, cabeceras or {}, b'', CTX_UI)
        cuerpo = gzip.decompress(r.cuerpo) if r.cuerpo[:2] == b'\x1f\x8b' else r.cuerpo
        return r.status, dict(r.cabeceras), json.loads(cuerpo or b'null')

    def catalogo(self, consulta: str = 'limite=2000') -> dict:
        status, _, cuerpo = self.api('/api/catalogo/videos', consulta)
        self.assertEqual(status, 200, cuerpo)
        return cuerpo

    def legado(self) -> dict:
        status, _, cuerpo = self.api('/api/analitica/videos', 'limite=1000')
        self.assertEqual(status, 200, cuerpo)
        return {f['content_id']: f for f in cuerpo['items']}

    def escribir(self, sql: str, params=()) -> None:
        with self.hub.almacen.escritor() as db:
            db.execute(sql, params)


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
            self.assertIsNotNone(i['vistas'])
            self.assertEqual(i['publicacion'], 'publico')
        for cid in con_ventas:
            self.assertEqual(items[cid]['ventas'], legado[cid])          # la fila de ventas es la de siempre
            self.assertIn(items[cid]['origen'], ('ventas', 'display_y_ventas'))
        for cid, i in items.items():
            self.assertIsInstance(cid, str)
            self.assertTrue(i['portada'] is None or i['portada'].startswith(f'/img/v/{cid}'), i['portada'])
        self.assertRegex(cat['pedidos_desde'], r'^\d{4}-\d{2}-\d{2}$')

    def test_orden_y_limite(self) -> None:
        publicado = self.catalogo()['items']
        fechas = [i['publicado_at'] for i in publicado if i['publicado_at'] is not None]
        self.assertEqual(fechas, sorted(fechas, reverse=True))
        sin_fecha = [n for n, i in enumerate(publicado) if i['publicado_at'] is None]
        self.assertTrue(all(n >= len(fechas) for n in sin_fecha))
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
        organico = next(i for i in items if i['origen'] == 'display')['content_id']
        vendido = next(i for i in items if i['ventas'] is not None)['content_id']

        status, _, cuerpo = self.api(f'/api/videos/{organico}')
        self.assertEqual(status, 404)                                 # la ruta de ventas no cambia
        status, _, cuerpo = self.api(f'/api/catalogo/videos/{organico}')
        self.assertEqual(status, 200)
        self.assertIsNone(cuerpo['video']['ventas'])
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
        status, cabeceras, _ = self.api('/api/catalogo/videos', 'limite=10')
        self.assertEqual(status, 200)
        status, _, _ = self.api('/api/catalogo/videos', 'limite=10', {'if-none-match': cabeceras['ETag']})
        self.assertEqual(status, 304)

    def test_la_sesion_anuncia_la_capacidad(self) -> None:
        status, _, cuerpo = self.api('/api/session')
        self.assertEqual(status, 200)
        self.assertIs(cuerpo['capacidades']['catalogo_videos'], True)


class CatalogoCuentaEHistorialTests(ConSyncSintetica):
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
        with self.hub.almacen.lector() as db:
            fila = db.execute('SELECT * FROM videos_tiktok WHERE video_id = ?', (cid,)).fetchone()
            columnas = [d[0] for d in db.execute('SELECT * FROM videos_tiktok LIMIT 0').description]
            ultima = db.execute('SELECT vistas FROM videos_tiktok_dias WHERE video_id = ? ORDER BY fecha DESC LIMIT 1',
                                (cid,)).fetchone()[0]
        try:
            self.escribir('DELETE FROM videos_tiktok WHERE video_id = ?', (cid,))   # dejó de ser público
            self.assertNotIn(cid, {i['content_id'] for i in self.catalogo()['items']})
            con_historial = {i['content_id']: i for i in self.catalogo('incluir=historial&limite=2000')['items']}
            item = con_historial[cid]
            self.assertEqual((item['publicacion'], item['origen']), ('no_publico', 'display'))
            self.assertEqual(item['vistas'], ultima)
            self.assertIsNone(item['descripcion'])
            status, _, cuerpo = self.api(f'/api/catalogo/videos/{cid}')
            self.assertEqual(status, 200)
            self.assertTrue(cuerpo['tendencia'])
        finally:
            self.escribir(f'INSERT INTO videos_tiktok({", ".join(columnas)}) VALUES ({", ".join("?" * len(columnas))})',
                          tuple(fila))

    def _ids_display(self) -> list[str]:
        with self.hub.almacen.lector() as db:
            return [r[0] for r in db.execute('SELECT video_id FROM videos_tiktok ORDER BY video_id')]


class UsuarioNormalizadoTests(unittest.TestCase):
    def test_normaliza_y_rechaza_valores_raros(self) -> None:
        self.assertEqual(usuario_normalizado(' @Creador.Demo_1 '), 'creador.demo_1')
        for raro in (None, '', '@', 'con espacio', 'ñandú', 7, 'x' * 129):
            with self.subTest(raro=raro):
                self.assertEqual(usuario_normalizado(raro), '')


if __name__ == '__main__':
    unittest.main()
