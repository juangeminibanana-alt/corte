"""orders/trace/search se retiró (15/08/2026): Corte deja de llamarla y conserva su histórico sin reescribirlo.

Corre un hub REAL en modo nube con el transporte falso de la demo (datos sintéticos, sin firmas ni red) y una
sincronización completa. Nunca lee una conexión del operador ni llama a TikTok: las imágenes usan un descargador sin
red y, mientras corre la clase, resolver un nombre fuera de esta máquina falla la prueba.
"""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'hub'))

from creatorhub import sincronizador_ficha
from creatorhub.analitica.vista import FUENTE_ORIGEN_HISTORICO, Vista
from creatorhub.api.rutas import REV_SNAPSHOT
from creatorhub.demo import sinteticos
from creatorhub.demo.transporte import TransporteApiFalsa
from creatorhub.hub import iniciar_hub
from creatorhub.imagenes.claves import ErrorImagen
from creatorhub.interfaces import CTX_UI, OpcionesHub

RUTA_RETIRADA = '/affiliate_creator/202505/orders/trace/search'
P_HISTORICO = '1729000000000000001'          # producto que solo existe en el histórico de trazas
FASES = ('recuperadas', 'etiquetas', 'dirigidas', 'parecidos')
CAMPOS_DISPLAY = ('descripcion', 'publicado_at', 'duracion_s', 'vistas', 'likes', 'comentarios', 'compartidos',
                  'metricas_at')
LOCALES = frozenset({None, '', 'localhost', '127.0.0.1', '::1', '0.0.0.0'})


def _sin_red(url: str) -> bytes:
    """Descargador de imágenes de las pruebas: nunca sale a la red (la imagen se queda en '?v=0')."""
    raise ErrorImagen('sin_red_en_pruebas', permanente=True)


def _bloquear_red(intentos: list[str]):
    """Parche de socket.getaddrinfo: resolver un nombre fuera de esta máquina falla y queda anotado."""
    real = socket.getaddrinfo

    def resolver(host, *args, **kwargs):
        nombre = host.decode('ascii', 'replace') if isinstance(host, bytes) else host
        if nombre not in LOCALES:
            intentos.append(str(nombre))
            raise OSError(f'Red bloqueada en las pruebas: {nombre}')
        return real(host, *args, **kwargs)
    return patch('socket.getaddrinfo', resolver)


class RetiroTrazasEnSyncTests(unittest.TestCase):
    """Una sincronización completa con los datos sintéticos de la demo, una sola vez para toda la clase."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.intentos_de_red: list[str] = []
        cls.red = _bloquear_red(cls.intentos_de_red)
        cls.red.start()
        try:
            cls.carpeta = tempfile.TemporaryDirectory()
            cls.env = patch.dict(os.environ, {'CORTE_PUBLIC_URL': 'https://corte.example',
                                              'CORTE_ENCRYPTION_KEY': 'synthetic-master-' * 4})
            cls.env.start()
            with patch('creatorhub.imagenes.servicio.DescargadorHttps', return_value=_sin_red):
                cls.hub = iniciar_hub(OpcionesHub(modo='real', nube=True, sin_lan=True, raiz_datos=cls.carpeta.name,
                                                  sync_al_iniciar=False))
        except BaseException:
            cls.red.stop()
            raise
        try:
            cls.ahora = int(time.time())
            futuro = cls.ahora + 86400
            credenciales = {'app_key': 'synthetic-app-key', 'app_secret': 'SyntheticSecretForTests123456',
                            'access_token': 'synthetic-access-token', 'refresh_token': 'synthetic-refresh-token',
                            'open_id': 'synthetic-open-id', 'access_expira_at': futuro,
                            'refresh_expira_at': futuro + 86400 * 30, 'user_type': 1,
                            'granted_scopes': ['creator.affiliate.info'], 'origen': 'importado'}
            cls.hub.boveda.mutar(lambda d: d.update(credenciales), cambia_credenciales=True)
            cls.hub.auth._espejar()
            dia = 86400
            cls.historico = [
                ('H1', 0, 'S1', P_HISTORICO, 'VIDEO', 'GENERAL', cls.ahora - 10 * dia, cls.ahora - 9 * dia),
                ('H1', 1, 'S2', P_HISTORICO, 'LIVE', None, cls.ahora - 10 * dia, cls.ahora - 9 * dia),
                ('H2', 0, 'S3', P_HISTORICO, 'VIDEO', 'SPECIFIC', cls.ahora - 5 * dia, cls.ahora - 4 * dia),
            ]
            with cls.hub.almacen.escritor() as db:
                db.executemany('INSERT INTO orden_trazas(order_id, linea_n, sku_id, product_id, tipo_contenido, '
                               'traza_tipo, creada_at, actualizado_at) VALUES (?,?,?,?,?,?,?,?)', cls.historico)
                db.execute("INSERT INTO sync_cursores(clave, valor, actualizado_at) VALUES ('trazas.estado', "
                           "'sin_permiso', ?)", (cls.ahora - 4 * dia,))

            falso = TransporteApiFalsa(sinteticos.generar(cls.ahora), cls.hub.reloj)
            cls.rutas: list[str] = []

            def manejar(metodo, url, cabeceras, cuerpo):
                cls.rutas.append(urlsplit(url).path)
                return falso.manejar(metodo, url, cabeceras, cuerpo)
            cls.hub.cliente.transporte = type('Registro', (), {'manejar': staticmethod(manejar)})()
            cls.hub.cliente.cubeta.tomar = lambda cancelar=None: False   # sin esperas del límite de peticiones
            cls.hub.cliente._esperar = lambda segundos, path=None: None   # sin esperas de reintento

            cls.hub.sincronizador.iniciar('completa', 'usuario')
            if not cls.hub.sincronizador._actual.fin.wait(600):
                raise AssertionError('La sincronización sintética no terminó')
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.hub.detener(10)
            cls.env.stop()
            cls.carpeta.cleanup()
        finally:
            cls.red.stop()
        if cls.intentos_de_red:
            raise AssertionError(f'Las pruebas intentaron salir a la red: {sorted(set(cls.intentos_de_red))}')

    def api(self, ruta: str, consulta: str = ''):
        r = self.hub.despachador.despachar('GET', ruta, consulta, {}, b'', CTX_UI)
        cuerpo = gzip.decompress(r.cuerpo) if r.cuerpo[:2] == b'\x1f\x8b' else r.cuerpo
        return r.status, dict(r.cabeceras), json.loads(cuerpo or b'null')

    def test_la_sync_no_llama_la_ruta_retirada_y_las_demas_fases_si_corren(self) -> None:
        self.assertNotIn(RUTA_RETIRADA, self.rutas)
        self.assertFalse([r for r in self.rutas if 'trace' in r])
        self.assertIn('/affiliate_creator/202410/orders/search', self.rutas)
        self.assertIn('/affiliate_creator/202405/open_collaborations/products/search', self.rutas)
        with self.hub.almacen.lector() as db:
            estado, resumen = db.execute('SELECT estado, resumen_json FROM sync_ejecuciones '
                                         'ORDER BY sync_id DESC LIMIT 1').fetchone()
        self.assertIn(estado, ('ok', 'parcial'))
        fases = json.loads(resumen)['fases']
        self.assertEqual(list(fases), list(FASES))
        # Una fase que falla queda en 'error' sin volver parcial la sync: cada una debe terminar bien y llamar a TikTok.
        self.assertEqual({f: (v['estado'], v['llamadas'] > 0) for f, v in fases.items()},
                         dict.fromkeys(FASES, ('ok', True)))

    def test_el_historico_queda_intacto(self) -> None:
        with self.hub.almacen.lector() as db:
            filas = db.execute('SELECT order_id, linea_n, sku_id, product_id, tipo_contenido, traza_tipo, creada_at, '
                               'actualizado_at FROM orden_trazas ORDER BY order_id, linea_n').fetchall()
        self.assertEqual([tuple(f) for f in filas], self.historico)

    def test_el_origen_historico_lleva_procedencia_y_no_afirma_ausencia_de_enlace(self) -> None:
        with self.hub.almacen.lector() as db:
            origen = Vista(db, self.hub.reloj.ahora()).origen_ventas(P_HISTORICO)
        self.assertEqual(origen['lineas'], 3)
        self.assertEqual(origen['pedidos'], 2)
        self.assertEqual(origen['fuente'], FUENTE_ORIGEN_HISTORICO)
        self.assertEqual((origen['desde_at'], origen['hasta_at']), (self.historico[0][6], self.historico[2][6]))
        enlace = {c['tipo']: (c['texto'], c['lineas']) for c in origen['por_tipo_enlace']}
        self.assertEqual(enlace, {'GENERAL': ('Enlace general', 1), 'SPECIFIC': ('Enlace para un publicador', 1),
                                  None: ('Sin enlace reportado', 1)})

    def test_el_historico_llega_a_la_ficha_y_a_la_copia_del_snapshot(self) -> None:
        status, _, snapshot = self.api('/api/snapshot')
        self.assertEqual(status, 200)
        en_copia = set((snapshot.get('extras') or {}).get('productos') or {})
        with self.hub.almacen.lector() as db:
            con_lineas = {r[0] for r in db.execute('SELECT DISTINCT product_id FROM orden_lineas '
                                                   'WHERE product_id IS NOT NULL')}
            sin_historico = db.execute('SELECT product_id FROM orden_lineas WHERE product_id IS NOT NULL '
                                       'ORDER BY product_id LIMIT 1').fetchone()[0]   # el de la prueba del aviso
        pid = sorted((en_copia & con_lineas) - {sin_historico})[0]
        creada = self.ahora - 3 * 86400
        with self.hub.almacen.escritor() as db:
            db.execute('INSERT INTO orden_trazas(order_id, linea_n, sku_id, product_id, tipo_contenido, traza_tipo, '
                       "creada_at, actualizado_at) VALUES ('HX', 0, 'SX', ?, 'VIDEO', 'GENERAL', ?, ?)",
                       (pid, creada, creada))
        try:
            esperado = {'fuente': FUENTE_ORIGEN_HISTORICO, 'lineas': 1, 'pedidos': 1, 'desde_at': creada,
                        'hasta_at': creada}
            status, _, cuerpo = self.api(f'/api/productos/{pid}')
            self.assertEqual(status, 200)
            origen = cuerpo['extendido']['origen_ventas']
            self.assertEqual({k: origen[k] for k in esperado}, esperado)
            self.assertIsNone(cuerpo['extendido']['origen_ventas_aviso'])
            status, _, snapshot = self.api('/api/snapshot')
            self.assertEqual(status, 200)
            copia = snapshot['extras']['productos'][pid]['origen_ventas']
            self.assertEqual({k: copia[k] for k in esperado}, esperado)
        finally:
            with self.hub.almacen.escritor() as db:
                db.execute("DELETE FROM orden_trazas WHERE order_id = 'HX'")

    def test_el_catalogo_sin_display_api_solo_trae_videos_con_ventas(self) -> None:
        status, _, legado = self.api('/api/analitica/videos', 'limite=1000')
        self.assertEqual(status, 200)
        status, _, cat = self.api('/api/catalogo/videos', 'limite=2000')
        self.assertEqual(status, 200)
        self.assertIsNone(cat['display'])                       # nunca se conectó la Display API
        self.assertEqual({i['content_id'] for i in cat['items']}, {f['content_id'] for f in legado['items']})
        for i in cat['items']:
            self.assertEqual((i['origen'], i['publicacion']), ('ventas', 'desconocido'))
            self.assertEqual({k: i[k] for k in CAMPOS_DISPLAY}, dict.fromkeys(CAMPOS_DISPLAY))   # null, nunca ceros
        cid = cat['items'][0]['content_id']
        status, _, detalle = self.api(f'/api/catalogo/videos/{cid}')
        self.assertEqual(status, 200)
        self.assertEqual(detalle['video'], cat['items'][0])
        self.assertIsNone(detalle['tendencia'])

    def test_la_ficha_ya_no_avisa_un_permiso_aunque_quede_el_cursor_viejo(self) -> None:
        with self.hub.almacen.lector() as db:
            pid = db.execute("SELECT product_id FROM orden_lineas WHERE product_id IS NOT NULL "
                             "ORDER BY product_id LIMIT 1").fetchone()[0]
            cursor = db.execute("SELECT valor FROM sync_cursores WHERE clave = 'trazas.estado'").fetchone()[0]
        self.assertEqual(cursor, 'sin_permiso')                 # el cursor antiguo sigue ahí y ya no se lee
        status, _, cuerpo = self.api(f'/api/productos/{pid}')
        self.assertEqual(status, 200)
        self.assertIsNone(cuerpo['extendido']['origen_ventas'])
        self.assertIsNone(cuerpo['extendido']['origen_ventas_aviso'])
        status, _, snapshot = self.api('/api/snapshot')
        self.assertEqual(status, 200)
        avisos = [p.get('origen_ventas_aviso') for p in ((snapshot.get('extras') or {}).get('productos') or {}).values()]
        self.assertTrue(avisos)
        self.assertEqual(set(avisos), {None})

    def test_la_etag_del_snapshot_cambia_de_representacion(self) -> None:
        self.assertEqual(REV_SNAPSHOT, 'f4')
        status, cabeceras, _ = self.api('/api/snapshot')
        self.assertEqual(status, 200)
        self.assertIn('-f4-', cabeceras['ETag'])


class FaseRetiradaTests(unittest.TestCase):
    def test_la_ficha_ya_no_tiene_fase_ni_ruta_de_trazas(self) -> None:
        self.assertEqual(sincronizador_ficha.ORDEN_FASES, ('recuperadas', 'etiquetas', 'dirigidas', 'parecidos'))
        self.assertNotIn('trazas', sincronizador_ficha.TEXTOS_FASES)
        self.assertFalse(hasattr(sincronizador_ficha.FasesFicha, '_fase_trazas'))
        self.assertFalse(hasattr(sincronizador_ficha, 'P_TRAZAS'))
        self.assertIn(105005, sincronizador_ficha.CODIGOS_SIN_PERMISO)      # lo siguen usando las otras fases
        self.assertEqual(sincronizador_ficha.MAX_PAGINAS_DIRIGIDAS, 10)


if __name__ == '__main__':
    unittest.main()
