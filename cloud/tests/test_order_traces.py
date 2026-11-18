"""rev. 7 · trace_info de orders/search 202410 (etapa 2 de docs/ORDER_TRACE_RETIREMENT.md).

Corre un hub REAL en modo nube con el transporte falso de la demo (datos sintéticos, sin firmas ni red) y comprueba:
- qué guarda cada línea observada (GENERAL, SPECIFIC, un valor desconocido, null, {}, tipo vacío, tipo no textual, id
  sin tipo, minúsculas) y que trace_info.id nunca llega a la base;
- que una ventana incompleta no escribe trazas y que un pedido sin cambios sin trazas se rellena UNA vez desde la misma
  respuesta, sin contarse como pedido cambiado;
- que el bloque actual de la ficha va aparte del histórico cerrado: un pedido nunca cuenta en los dos;
- la migración 6 → 7 (datos intactos, copia .bak-v6, FK en cascada) y que la tabla nueva es idéntica en una base nueva.
Nunca lee una conexión del operador ni llama a TikTok: resolver un nombre fuera de esta máquina falla la prueba.
"""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'hub'))

from creatorhub import sincronizador as S
from creatorhub.almacen import crear_almacen, leer_recurso_sql
from creatorhub.analitica.vista import FUENTE_ORIGEN_ACTUAL, FUENTE_ORIGEN_HISTORICO
from creatorhub.demo import sinteticos
from creatorhub.demo.transporte import TransporteApiFalsa
from creatorhub.hub import iniciar_hub
from creatorhub.imagenes.claves import ErrorImagen
from creatorhub.interfaces import CTX_UI, OpcionesHub

LOCALES = frozenset({None, '', 'localhost', '127.0.0.1', '::1', '0.0.0.0'})
ID_SECRETO = 'ID-DE-TERCERO-QUE-NO-SE-GUARDA'
DDL_TRAZA = re.compile(r'CREATE TABLE IF NOT EXISTS orden_lineas_traza\s*\(.*?\) STRICT;', re.S)


def _sin_red(url: str) -> bytes:
    raise ErrorImagen('sin_red_en_pruebas', permanente=True)


def _bloquear_red(intentos: list[str]):
    real = socket.getaddrinfo

    def resolver(host, *args, **kwargs):
        nombre = host.decode('ascii', 'replace') if isinstance(host, bytes) else host
        if nombre not in LOCALES:
            intentos.append(str(nombre))
            raise OSError(f'Red bloqueada en las pruebas: {nombre}')
        return real(host, *args, **kwargs)
    return patch('socket.getaddrinfo', resolver)


class TipoTrazaTests(unittest.TestCase):
    def test_lo_que_se_puede_afirmar_de_cada_forma_de_trace_info(self) -> None:
        casos = [
            ({'trace_info': {'id': '1', 'type': 'GENERAL'}}, (True, 'GENERAL')),
            ({'trace_info': {'type': 'SPECIFIC'}}, (True, 'SPECIFIC')),
            ({'trace_info': {'type': ' general '}}, (True, 'GENERAL')),
            ({'trace_info': {'type': 'RARO'}}, (True, 'RARO')),
            ({}, (True, None)),
            ({'trace_info': None}, (True, None)),
            ({'trace_info': {}}, (True, None)),
            ({'trace_info': {'type': ''}}, (True, None)),
            ({'trace_info': {'id': '99'}}, (True, None)),
            ({'trace_info': {'type': ['x']}}, (False, None)),
            ({'trace_info': {'type': {'a': 1}}}, (False, None)),
            ({'trace_info': {'type': True}}, (False, None)),
            ({'trace_info': 'GENERAL'}, (False, None)),
            ({'trace': {'type': 'GENERAL'}}, (True, None)),          # la clave retirada nunca se usa de respaldo
            ({'trace_info': {'type': 1}}, (True, '1')),              # un número se guarda como texto, tal cual
        ]
        for linea, esperado in casos:
            with self.subTest(linea=linea):
                self.assertEqual(S.tipo_traza(linea), esperado)


class TrazasEnSyncTests(unittest.TestCase):
    """Una sync completa, después incrementales, con la matriz de casos en pedidos recientes."""

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

            datos = sinteticos.generar(cls.ahora)
            recientes = sorted((o for o in datos.ordenes if o['create_time'] >= cls.ahora - 5 * 86400),
                               key=lambda o: (-o['create_time'], o['id']))
            productos_usados: set[str] = set()
            elegidos: list[dict] = []
            for o in recientes:                                   # pedidos con productos que no comparten con otros
                pids = {s['product_id'] for s in o['skus']}
                if pids & productos_usados:
                    continue
                productos_usados |= pids
                elegidos.append(o)
                if len(elegidos) == 12:
                    break
            assert len(elegidos) == 12, 'los sintéticos deben traer pedidos recientes suficientes'
            casos = {
                'GENERAL': 'GENERAL', 'SPECIFIC': 'SPECIFIC', 'RARO': {'type': 'RARO'}, 'VACIO': {},
                'NULL': '__null__', 'TIPO_VACIO': {'type': ''}, 'NO_TEXTUAL': {'type': ['x']},
                'ID_SIN_TIPO': {'id': ID_SECRETO}, 'MINUSCULAS': {'id': ID_SECRETO, 'type': 'general'},
            }
            cls.pedido: dict[str, dict] = {}
            for (clave, valor), o in zip(casos.items(), elegidos):
                datos.trazas[o['id']] = [valor] * len(o['skus'])
                cls.pedido[clave] = o
            # Pedido que ya está en el histórico cerrado: debe quedarse solo allá.
            cls.pedido['HISTORICO'] = o_h = elegidos[9]
            datos.trazas[o_h['id']] = ['SPECIFIC'] * len(o_h['skus'])
            cls.pedido['INCOMPLETO'] = elegidos[10]
            cls.pedido['RELLENO'] = elegidos[11]
            datos.trazas[elegidos[11]['id']] = ['GENERAL'] * len(elegidos[11]['skus'])
            with cls.hub.almacen.escritor() as db:
                db.executemany('INSERT INTO orden_trazas(order_id, linea_n, sku_id, product_id, tipo_contenido, '
                               'traza_tipo, creada_at, actualizado_at) VALUES (?,?,?,?,?,?,?,?)',
                               [(o_h['id'], i, s.get('id'), s['product_id'], s.get('content_type'), 'GENERAL',
                                 o_h['create_time'], o_h['create_time']) for i, s in enumerate(o_h['skus'])])

            cls.falso = TransporteApiFalsa(datos, cls.hub.reloj)
            cls.rutas: list[str] = []

            def manejar(metodo, url, cabeceras, cuerpo):
                from urllib.parse import urlsplit
                cls.rutas.append(urlsplit(url).path)
                return cls.falso.manejar(metodo, url, cabeceras, cuerpo)
            cls.hub.cliente.transporte = type('Registro', (), {'manejar': staticmethod(manejar)})()
            cls.hub.cliente.cubeta.tomar = lambda cancelar=None: False
            cls.hub.cliente._esperar = lambda segundos, path=None: None
            cls.resumen_completa = cls.sincronizar('completa')
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

    @classmethod
    def sincronizar(cls, tipo: str) -> dict:
        cls.hub.sincronizador.iniciar(tipo, 'usuario')
        if not cls.hub.sincronizador._actual.fin.wait(600):
            raise AssertionError('La sincronización sintética no terminó')
        with cls.hub.almacen.lector() as db:
            estado, resumen = db.execute('SELECT estado, resumen_json FROM sync_ejecuciones '
                                         'ORDER BY sync_id DESC LIMIT 1').fetchone()
        assert estado in ('ok', 'parcial'), estado
        return json.loads(resumen)

    def trazas_de(self, clave: str) -> list[tuple]:
        with self.hub.almacen.lector() as db:
            return [tuple(r) for r in db.execute('SELECT linea_n, traza_tipo FROM orden_lineas_traza WHERE order_id=? '
                                                 'ORDER BY linea_n', (self.pedido[clave]['id'],))]

    def ficha(self, pid: str) -> dict:
        r = self.hub.despachador.despachar('GET', f'/api/productos/{pid}', '', {}, b'', CTX_UI)
        cuerpo = gzip.decompress(r.cuerpo) if r.cuerpo[:2] == b'\x1f\x8b' else r.cuerpo
        self.assertEqual(r.status, 200)
        return json.loads(cuerpo)

    def test_cada_linea_observada_guarda_lo_que_reporto_tiktok(self) -> None:
        esperados = {'GENERAL': 'GENERAL', 'SPECIFIC': 'SPECIFIC', 'RARO': 'RARO', 'VACIO': None, 'NULL': None,
                     'TIPO_VACIO': None, 'ID_SIN_TIPO': None, 'MINUSCULAS': 'GENERAL'}
        for clave, tipo in esperados.items():
            with self.subTest(caso=clave):
                n = len(self.pedido[clave]['skus'])
                self.assertEqual(self.trazas_de(clave), [(i, tipo) for i in range(n)])
        # Un tipo que no es texto no se convierte en «sin traza reportada»: la línea queda sin dato.
        self.assertEqual(self.trazas_de('NO_TEXTUAL'), [])

    def test_trace_info_id_nunca_llega_a_la_base(self) -> None:
        with self.hub.almacen.lector() as db:
            columnas = [r[1] for r in db.execute('PRAGMA table_info(orden_lineas_traza)')]
            volcado = '\n'.join(db.iterdump())
        self.assertEqual(columnas, ['order_id', 'linea_n', 'traza_tipo', 'capturada_at'])
        self.assertNotIn(ID_SECRETO, volcado)

    def test_el_resumen_cuenta_lo_que_trae_la_api_sin_guardar_respuestas(self) -> None:
        r = self.resumen_completa['trazas_202410']
        self.assertGreater(r['lineas_observadas'], 0)
        self.assertEqual(r['lineas_observadas'], r['escritas'] + r['tipo_no_textual'])
        self.assertGreaterEqual(r['tipo_no_textual'], 1)
        self.assertGreaterEqual(r['id_sin_tipo'], 1)
        self.assertEqual(r['clave_trace_antigua'], 0)
        # Separa «TikTok no manda el campo» de «lo manda vacío»: casi todas las líneas sintéticas no traen la clave.
        self.assertGreater(r['clave_trace_info'], 0)
        self.assertLess(r['clave_trace_info'], r['lineas_observadas'])
        for tipo in ('GENERAL', 'SPECIFIC', 'RARO', 'SIN_TRAZA'):
            self.assertIn(tipo, r['por_tipo'])
        calidad = self.resumen_completa['ordenes_calidad']
        self.assertGreater(calidad['lineas'], 0)
        self.assertEqual(calidad['moneda_precio_no_mxn'], 0)
        self.assertEqual(calidad['estados_desconocidos'], {})
        self.assertNotIn('/affiliate_creator/202505/orders/trace/search', self.rutas)

    def test_el_bloque_actual_va_aparte_del_historico(self) -> None:
        o_h = self.pedido['HISTORICO']
        pid = o_h['skus'][0]['product_id']
        x = self.ficha(pid)['extendido']
        historico, actual = x['origen_ventas'], x['origen_ventas_actual']
        self.assertEqual(historico['fuente'], FUENTE_ORIGEN_HISTORICO)
        self.assertEqual(historico['pedidos'], 1)
        # El pedido del histórico no cuenta en el bloque actual aunque ahora traiga SPECIFIC.
        with self.hub.almacen.lector() as db:
            del_producto = {r[0] for r in db.execute('SELECT DISTINCT order_id FROM orden_lineas WHERE product_id=?',
                                                     (pid,))}
        if del_producto == {o_h['id']}:
            self.assertIsNone(actual)
        else:
            self.assertEqual(actual['fuente'], FUENTE_ORIGEN_ACTUAL)
            self.assertNotIn('SPECIFIC', [c['tipo'] for c in actual['por_tipo_enlace']])

    def test_ningun_pedido_cuenta_en_los_dos_bloques(self) -> None:
        with self.hub.almacen.lector() as db:
            dobles = db.execute('SELECT COUNT(*) FROM orden_lineas_traza t WHERE t.order_id IN '
                                '(SELECT order_id FROM orden_trazas)').fetchone()[0]
        self.assertGreater(dobles, 0, 'el pedido del histórico también se observó en la sync')
        for clave in ('GENERAL', 'SPECIFIC', 'HISTORICO'):
            pid = self.pedido[clave]['skus'][0]['product_id']
            x = self.ficha(pid)['extendido']
            pedidos_h = (x['origen_ventas'] or {}).get('pedidos', 0)
            pedidos_a = (x['origen_ventas_actual'] or {}).get('pedidos', 0)
            with self.hub.almacen.lector() as db:
                total = db.execute('SELECT COUNT(DISTINCT order_id) FROM orden_lineas WHERE product_id=?',
                                   (pid,)).fetchone()[0]
            self.assertLessEqual(pedidos_h + pedidos_a, total, clave)

    def test_la_ficha_rotula_y_no_inventa_negativos(self) -> None:
        pid = self.pedido['GENERAL']['skus'][0]['product_id']
        actual = self.ficha(pid)['extendido']['origen_ventas_actual']
        self.assertEqual(actual['fuente'], FUENTE_ORIGEN_ACTUAL)
        self.assertEqual(sum(c['lineas'] for c in actual['por_tipo_enlace']), actual['lineas'])
        self.assertEqual(actual['con_enlace'], sum(c['lineas'] for c in actual['por_tipo_enlace'] if c['tipo']))
        textos = {c['tipo']: c['texto'] for c in actual['por_tipo_enlace']}
        self.assertEqual(textos.get('GENERAL'), 'Enlace general')
        self.assertEqual(textos.get(None, 'Sin enlace reportado'), 'Sin enlace reportado')

        def rotulos(clave: str) -> dict:
            x = self.ficha(self.pedido[clave]['skus'][0]['product_id'])['extendido']['origen_ventas_actual']
            return {c['tipo']: c['texto'] for c in x['por_tipo_enlace']}
        self.assertEqual(rotulos('SPECIFIC').get('SPECIFIC'), 'Enlace para un publicador')
        self.assertEqual(rotulos('RARO').get('RARO'), 'RARO')            # un valor nuevo se muestra tal cual
        for clave in ('NULL', 'VACIO', 'TIPO_VACIO', 'ID_SIN_TIPO'):      # observadas, sin enlace reportado
            with self.subTest(caso=clave):
                self.assertEqual(rotulos(clave).get(None), 'Sin enlace reportado')
        for clave in ('desde_at', 'hasta_at', 'capturada_at'):
            self.assertIsInstance(actual[clave], int)
        # El pedido con tipo no textual queda sin dato: no entra en los conteos.
        pid_nt = self.pedido['NO_TEXTUAL']['skus'][0]['product_id']
        x = self.ficha(pid_nt)['extendido']['origen_ventas_actual']
        if x is not None:
            self.assertGreaterEqual(x['lineas_sin_dato'], len(self.pedido['NO_TEXTUAL']['skus']))

    def test_sin_dato_solo_cuenta_lo_que_aun_se_puede_observar(self) -> None:
        from creatorhub.analitica.vista import Vista
        pid = self.pedido['GENERAL']['skus'][0]['product_id']

        def actual() -> dict:
            with self.hub.almacen.lector() as db:
                return Vista(db, self.ahora).origen_ventas_actual(pid)
        base = actual()
        desde, hasta = base['desde_at'], base['hasta_at']
        # Sin fila de traza: uno que TikTok ya no devuelve y uno anterior al bloque (no cuentan); uno dentro del periodo y
        # uno más reciente que el último observado (cuentan: se observarán en una próxima ventana completa).
        falsos = {'SINDATO-NODEV': ('NO_DEVUELTA', desde), 'SINDATO-VIEJO': ('SETTLED', desde - 30 * 86400),
                  'SINDATO-DENTRO': ('SETTLED', desde), 'SINDATO-NUEVO': ('To-SETTLE', hasta + 3600)}
        try:
            with self.hub.almacen.escritor() as db:
                for oid, (estado, creada) in falsos.items():
                    db.execute('INSERT INTO ordenes(order_id, creada_at, estado, huella, actualizado_at) VALUES (?,?,?,?,?)',
                               (oid, creada, estado, 'h', creada))
                    db.execute('INSERT INTO orden_lineas(order_id, linea_n, product_id, cantidad) VALUES (?,?,?,?)',
                               (oid, 0, pid, 1))
            despues = actual()
            self.assertEqual(despues['lineas_sin_dato'], base['lineas_sin_dato'] + 2)
            self.assertEqual((despues['lineas'], despues['desde_at'], despues['hasta_at']), (base['lineas'], desde, hasta))
        finally:
            with self.hub.almacen.escritor() as db:
                db.executemany('DELETE FROM ordenes WHERE order_id=?', [(o,) for o in falsos])

    def test_relleno_una_sola_vez_y_ventana_incompleta_sin_trazas(self) -> None:
        base = self.sincronizar('incremental')                     # estable: solo se rellena el pedido sin dato
        rellenos_base = base.get('trazas_202410', {}).get('pedidos_rellenados', 0)
        cambiados_base = base['ordenes']['cambiados']
        self.assertLessEqual(rellenos_base, 1, 'solo el pedido de tipo no textual vuelve a intentarse')

        # Un pedido guardado antes de la rev. 7 (sin trazas) se rellena desde la respuesta, sin contarse como cambiado.
        o_r = self.pedido['RELLENO']
        with self.hub.almacen.escritor() as db:
            db.execute('DELETE FROM orden_lineas_traza WHERE order_id=?', (o_r['id'],))
        r = self.sincronizar('incremental')
        self.assertEqual(r['trazas_202410']['pedidos_rellenados'], rellenos_base + 1)
        self.assertEqual(r['ordenes']['cambiados'], cambiados_base)
        self.assertEqual(self.trazas_de('RELLENO'), [(i, 'GENERAL') for i in range(len(o_r['skus']))])

        # Ventana incompleta: el pedido nuevo se guarda con sus líneas, pero sin trazas (sin dato).
        o_i = self.pedido['INCOMPLETO']
        with self.hub.almacen.escritor() as db:
            db.execute('DELETE FROM ordenes WHERE order_id=?', (o_i['id'],))
        original = S._Sincronizador._bajar_ventana

        def incompleta(sync, ge, lt):
            por_orden, total, n, anom = original(sync, ge, lt)
            if o_i['id'] in por_orden:
                return por_orden, n + 1, n, anom               # TikTok anuncia una línea más de las que llegaron
            return por_orden, total, n, anom
        with patch.object(S._Sincronizador, '_bajar_ventana', incompleta):
            self.sincronizar('incremental')
        with self.hub.almacen.lector() as db:
            lineas = db.execute('SELECT COUNT(*) FROM orden_lineas WHERE order_id=?', (o_i['id'],)).fetchone()[0]
            huella = db.execute('SELECT huella FROM ordenes WHERE order_id=?', (o_i['id'],)).fetchone()[0]
        self.assertEqual(lineas, len(o_i['skus']))
        self.assertEqual(huella, 'incompleta')
        self.assertEqual(self.trazas_de('INCOMPLETO'), [])
        # La siguiente ventana completa lo reescribe con sus trazas.
        self.sincronizar('incremental')
        self.assertEqual(len(self.trazas_de('INCOMPLETO')), len(o_i['skus']))


class MigracionTrazasTests(unittest.TestCase):
    def base_v6(self, carpeta: str) -> Path:
        ruta = Path(carpeta) / 'synthetic-v6.sqlite'
        esquema = leer_recurso_sql('schema.sql')
        legado, n = DDL_TRAZA.subn('', esquema)
        self.assertEqual(n, 1)
        legado, n = re.subn(r'PRAGMA user_version\s*=\s*\d+\s*;', 'PRAGMA user_version = 6;', legado)
        self.assertEqual(n, 1)
        db = sqlite3.connect(ruta)
        db.executescript(legado)
        db.execute("INSERT INTO ordenes(order_id, creada_at, estado, huella, actualizado_at) "
                   "VALUES ('O1', 1800000000, 'SETTLED', 'h', 1800000000)")
        db.executemany('INSERT INTO orden_lineas(order_id, linea_n, product_id, cantidad) VALUES (?,?,?,?)',
                       [('O1', 0, 'P1', 1), ('O1', 1, 'P1', 2)])
        db.execute("INSERT INTO notas(id,entidad,entidad_id,texto,creado_at,actualizado_at) "
                   "VALUES('n1','producto','P1','Nota sintética',1800000000,1800000000)")
        db.commit()
        db.close()
        return ruta

    def test_migracion_6_a_7_conserva_todo_y_agrega_la_tabla_con_cascada(self) -> None:
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = self.base_v6(carpeta)
            almacen = crear_almacen(str(ruta), SimpleNamespace(ahora=lambda: 1_800_000_000))
            try:
                with almacen.lector() as db:
                    self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 7)
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM orden_lineas').fetchone()[0], 2)
                    self.assertEqual(db.execute('SELECT texto FROM notas').fetchone()[0], 'Nota sintética')
                    fk = {(r[2], r[3], r[4], r[6]) for r in db.execute('PRAGMA foreign_key_list(orden_lineas_traza)')}
                self.assertEqual(fk, {('orden_lineas', 'order_id', 'order_id', 'CASCADE'),
                                      ('orden_lineas', 'linea_n', 'linea_n', 'CASCADE')})
                self.assertTrue(Path(str(ruta) + '.bak-v6').is_file())
                with almacen.escritor() as db:
                    db.executemany('INSERT INTO orden_lineas_traza(order_id, linea_n, traza_tipo, capturada_at) '
                                   'VALUES (?,?,?,?)', [('O1', 0, 'GENERAL', 1), ('O1', 1, None, 1)])
                    with self.assertRaises(sqlite3.IntegrityError):  # una traza sin su línea no se acepta
                        db.execute("INSERT INTO orden_lineas_traza VALUES ('O1', 9, NULL, 1)")
                    db.execute("DELETE FROM orden_lineas WHERE order_id='O1' AND linea_n=0")
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM orden_lineas_traza').fetchone()[0], 1)
                    db.execute("DELETE FROM ordenes WHERE order_id='O1'")    # purga de 400 días: cascada completa
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM orden_lineas_traza').fetchone()[0], 0)
            finally:
                almacen.cerrar()

    def test_borrar_los_datos_de_tiktok_vacia_las_trazas(self) -> None:
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = self.base_v6(carpeta)
            almacen = crear_almacen(str(ruta), SimpleNamespace(ahora=lambda: 1_800_000_000))
            try:
                with almacen.escritor() as db:
                    db.execute("INSERT INTO orden_lineas_traza VALUES ('O1', 0, 'GENERAL', 1)")
                almacen.borrar('tiktok')
                with almacen.lector() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM orden_lineas_traza').fetchone()[0], 0)
                    self.assertEqual(db.execute('SELECT texto FROM notas').fetchone()[0], 'Nota sintética')
            finally:
                almacen.cerrar()

    def test_la_tabla_nueva_es_identica_en_una_base_nueva_y_en_una_migrada(self) -> None:
        with tempfile.TemporaryDirectory() as carpeta:
            migrada = crear_almacen(str(self.base_v6(carpeta)), SimpleNamespace(ahora=lambda: 1_800_000_000))
            nueva = crear_almacen(str(Path(carpeta) / 'nueva.sqlite'), SimpleNamespace(ahora=lambda: 1_800_000_000))
            try:
                sql = []
                for almacen in (migrada, nueva):
                    with almacen.lector() as db:
                        sql.append(db.execute("SELECT sql FROM sqlite_master WHERE name='orden_lineas_traza'").fetchone()[0])
                self.assertEqual(sql[0], sql[1])
                self.assertEqual(DDL_TRAZA.search(leer_recurso_sql('schema.sql')).group(0),
                                 DDL_TRAZA.search(leer_recurso_sql('migraciones/007.sql')).group(0))
            finally:
                migrada.cerrar()
                nueva.cerrar()


if __name__ == '__main__':
    unittest.main()
