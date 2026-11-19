"""Contratos Creator de vitrina y límites de la sesión, sin tráfico a TikTok."""
from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'hub'))

from creatorhub.api.rutas import DespachadorHub
from creatorhub.errores import ErrorApi
from creatorhub.interfaces import CTX_UI, Contexto, ContextoSync
from creatorhub.sincronizador import P_VITRINA, VITRINA_MUTACIONES, _Sincronizador
from creatorhub.tiktok.cliente import ClienteTikTokReal
from creatorhub.tiktok.showcase import AGREGAR, FIJAR, QUITAR, SCOPE_ESCRIBIR, ShowcaseCreator
from creatorhub.tiktok.transporte import TransporteHttps


class VitrinaTests(unittest.TestCase):
    def setUp(self):
        self.conexion = {'estado': 'conectada'}
        self.grant = {'user_type': 1, 'open_id': 'user-test', 'epoca_credenciales': 2,
                      'granted_scopes': ['creator.showcase.read', SCOPE_ESCRIBIR]}
        self.cliente = Mock()
        self.cliente.llamar.return_value = {'code': 0}
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        with self.db:
            self.db.execute('CREATE TABLE sync_cursores(clave TEXT PRIMARY KEY, valor TEXT, actualizado_at INTEGER)')
            self.db.execute("INSERT INTO sync_cursores VALUES ('vitrina.at','17',17)")
        self.almacen = Mock()
        self.almacen.epoca.return_value = 7
        self.almacen.escritor.return_value = self.db
        self.vitrina = ShowcaseCreator(self.cliente, SimpleNamespace(leer=lambda: dict(self.grant)),
                                      lambda: self.conexion, self.almacen, lambda: 55)
        self.api = DespachadorHub(SimpleNamespace(showcase=self.vitrina))

    def request(self, metodo='GET', accion='', body=None, query=None, ctx=CTX_UI):
        r = self.api.despachar(metodo, '/api/catalogo/vitrina' + accion, urlencode(query or {}),
                               {}, b'' if body is None else json.dumps(body).encode(), ctx)
        return r.status, dict(r.cabeceras), json.loads(r.cuerpo)

    def test_lee_pagina_en_orden_con_campos_visibles(self):
        self.cliente.llamar.return_value = {
            'products': [{'id': '100', 'title': ' Mini lámpara  ', 'shop': {'name': 'Tienda'},
                          'status': {'inventory_status': 'SOLD_OUT', 'review_status': 'APPROVED'},
                          'price': {'platform_discount_price': {'minimum_amount': '100.01'},
                                    'original_price': {'minimum_amount': '110', 'maximum_amount': '120',
                                                       'currency': 'MXN'}},
                          'main_images': [{'url': 'https://bad.example/photo.png'}],
                          'addition': {'customized_main_images': [
                              {'url': 'https://p16-test.ibyteimg.com/synthetic.jpg'}]}},
                         {'id': '9', 'status': {'is_hidden': True}}],
            'total_count': 24, 'next_page_token': 'next+/=',
        }
        status, headers, r = self.request(query={'limit': 2, 'cursor': 'previous+/='})
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual((r['total'], r['cursor_siguiente']), (24, 'next+/='))
        self.assertEqual(r['productos'][0], {'product_id': '100', 'titulo': 'Mini lámpara', 'tienda': 'Tienda',
                                             'precio_min': '110', 'precio_max': '120', 'moneda': 'MXN',
                                             'imagen_url': 'https://p16-test.ibyteimg.com/synthetic.jpg',
                                             'estado': 'SOLD_OUT'})
        self.assertEqual(r['productos'][1]['estado'], 'HIDDEN')
        args, kwargs = self.cliente.llamar.call_args
        self.assertEqual(args, ('GET', P_VITRINA, {'origin': 'SHOWCASE', 'page_size': '2',
                                                 'page_token': 'previous+/='}, None))
        self.assertEqual(kwargs['ctx'].open_id, 'user-test')

    def test_agregar_parcial_invalida_cache_aunque_el_codigo_exterior_sea_cero(self):
        self.cliente.llamar.return_value = {'errors': [
            {'code': 16001001, 'message': 'detalle sin confianza', 'detail': {'product_id': '9'}}]}
        status, _, r = self.request('POST', '/agregar', {'product_ids': ['100', '9']})
        self.assertEqual(status, 200)
        self.assertEqual([(p['product_id'], p['ok'], p['codigo']) for p in r['resultados']],
                         [('100', True, None), ('9', False, 16001001)])
        self.assertNotIn('detalle sin confianza', str(r))
        self.assertEqual(self.cliente.llamar.call_args.args,
                         ('POST', AGREGAR, None, {'add_type': 'PRODUCT_ID', 'product_ids': ['100', '9']}))
        self.assertFalse(self.cliente.llamar.call_args.kwargs['reintentar'])
        filas = self.db.execute('SELECT * FROM sync_cursores').fetchall()
        self.assertEqual(filas, [(VITRINA_MUTACIONES, '2', 55)])

    def test_quitar_y_fijar_envian_lote_con_ids_sin_cambiar_el_orden(self):
        for accion, ruta, metodo in (('/quitar', QUITAR, 'DELETE'), ('/fijar', FIJAR, 'POST')):
            with self.subTest(accion=accion):
                status, _, r = self.request('POST', accion, {'product_ids': ['100', '9']})
                self.assertEqual(status, 200)
                self.assertEqual([(p['product_id'], p['ok']) for p in r['resultados']], [('100', True), ('9', True)])
                self.assertEqual(self.cliente.llamar.call_args.args, (metodo, ruta, None, {'product_ids': ['100', '9']}))
                self.assertFalse(self.cliente.llamar.call_args.kwargs['reintentar'])

    def test_no_declara_exito_si_tiktok_no_confirma_o_no_identifica_los_fallos(self):
        self.cliente.llamar.return_value = {'errors': [{'detail': {}}]}
        status, _, r = self.request('POST', '/agregar', {'product_ids': ['100', '9']})
        self.assertEqual(status, 200)
        self.assertTrue(all(not p['ok'] for p in r['resultados']))
        self.cliente.llamar.return_value = {}
        status, _, r = self.request('POST', '/fijar', {'product_ids': ['100', '9']})
        self.assertEqual((status, r['error']['codigo']), (502, 'tiktok_no_disponible'))
        self.cliente.llamar.side_effect = ErrorApi(16015001, 'detalle sin confianza', 'abortar')
        status, _, r = self.request('POST', '/quitar', {'product_ids': ['100', '9']})
        self.assertEqual(status, 200)
        self.assertEqual([(p['ok'], p['codigo']) for p in r['resultados']], [(False, 16015001)] * 2)

    def test_permisos_datos_malformados_y_lan_no_llaman_a_tiktok(self):
        self.assertEqual(self.vitrina.capacidades(self.conexion), (True, True))
        for ids in ([], ['1'] * 21, ['a'], [1], ['1', '1']):
            self.assertEqual(self.request('POST', '/agregar', {'product_ids': ids})[0], 400)
        self.assertEqual(self.request(query={'cursor': 'x x'})[0], 400)
        self.assertEqual(self.request(metodo='POST')[0], 405)
        self.assertEqual(self.request(ctx=Contexto(origen='lan'))[0], 403)
        self.grant['granted_scopes'] = ['creator.video.write']
        self.assertEqual(self.vitrina.capacidades(self.conexion), (True, False))
        self.assertEqual(self.request('POST', '/agregar', {'product_ids': ['1']})[0], 403)
        self.grant['granted_scopes'] = [SCOPE_ESCRIBIR]
        self.assertEqual(self.vitrina.capacidades(self.conexion), (False, False))
        self.assertEqual(self.request()[0], 403)
        self.cliente.llamar.assert_not_called()

    def test_descarta_resultado_de_cuenta_distinta_sin_invalidar_su_cache(self):
        def cambia_cuenta(*args, **kwargs):
            self.grant.update(open_id='otra-cuenta', epoca_credenciales=3)
            return {'code': 0}

        self.cliente.llamar.side_effect = cambia_cuenta
        status, _, r = self.request('POST', '/quitar', {'product_ids': ['100']})
        self.assertEqual((status, r['error']['codigo']), (409, 'cuenta_cambio_sin_aplicar'))
        self.almacen.escritor.assert_called_once_with(7)

    def test_sync_completa_reconcilia_filas_tras_mutar_y_una_superpuesta_no_cierra_cache(self):
        self.request('POST', '/quitar', {'product_ids': ['100']})
        with self.db:
            self.db.execute('CREATE TABLE vitrina(product_id TEXT, vista_en_sync INTEGER)')
            self.db.execute("INSERT INTO vitrina VALUES ('100',1)")

        def cursor(clave):
            fila = self.db.execute('SELECT valor FROM sync_cursores WHERE clave=?', (clave,)).fetchone()
            return fila[0] if fila else None

        def sync(pagina):
            lector_vitrina = SimpleNamespace(
                _leer_cursor=cursor, _leer=lambda _: [], _llamar=pagina, _tx=lambda: self.db,
                _encolar=Mock(), _poner_cursor=_Sincronizador._poner_cursor, _avance=Mock(),
                sid=2, ahora=55, cambios=0, alm=self.almacen)
            return _Sincronizador._paso_vitrina(lector_vitrina)

        def pagina_superpuesta(*args):
            self.request('POST', '/agregar', {'product_ids': ['101']})
            return {'products': [], 'total_count': 0}

        self.assertEqual(sync(pagina_superpuesta), (0, 0, 0))
        self.assertIsNone(cursor('vitrina.at'))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM vitrina').fetchone()[0], 1)
        self.assertEqual(sync(lambda *args: {'products': [], 'total_count': 0}), (0, 1, 0))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM vitrina').fetchone()[0], 0)
        self.assertEqual(cursor('vitrina.at'), '55')


class VitrinaTransporteTests(unittest.TestCase):
    def test_delete_con_cuerpo_firmado_y_timeout_sin_reenviar(self):
        grant = {'open_id': 'user-test', 'epoca_credenciales': 2, 'app_secret': 'synthetic-secret',
                 'access_token': 'synthetic-access-token'}
        boveda = SimpleNamespace(leer=lambda: dict(grant), secretos_vivos=lambda: ())
        reloj = SimpleNamespace(ahora=lambda: 100, monotonico=lambda: 100.0, esperar=Mock())
        transporte = TransporteHttps()
        opener = Mock()
        transporte.opener = lambda: opener
        respuesta = Mock(status=200)
        respuesta.getheaders.return_value = []
        respuesta.read.return_value = b'{"code":0,"data":{"code":0}}'
        opener.open.return_value = respuesta
        cli = ClienteTikTokReal(boveda, transporte, reloj, Mock(), Mock())
        cli.volcar_errores = Mock()
        ctx = ContextoSync(None, 'user-test', 2, 7)
        self.assertEqual(cli.llamar('DELETE', QUITAR, body={'product_ids': ['8']},
                                    ctx=ctx, reintentar=False), {'code': 0})
        pedido = opener.open.call_args.args[0]
        self.assertEqual(pedido.get_method(), 'DELETE')
        self.assertEqual(json.loads(pedido.data), {'product_ids': ['8']})
        self.assertEqual(urlsplit(pedido.full_url).path, QUITAR)
        self.assertIn('sign=', urlsplit(pedido.full_url).query)
        opener.open.reset_mock()
        respuesta.read.side_effect = OSError('simulated timeout')
        with self.assertRaises(ErrorApi) as exc:
            cli.llamar('POST', FIJAR, body={'product_ids': ['8']}, ctx=ctx, reintentar=False)
        self.assertTrue(exc.exception.transitorio)
        self.assertEqual(exc.exception.codigo, -1)
        opener.open.assert_called_once()
        reloj.esperar.assert_not_called()


class VitrinaHttpTests(unittest.TestCase):
    def setUp(self):
        from cloud.tests import test_native_auth as native_tests

        self.fixture = native_tests.NativeWebTests
        self.fixture.setUp(self)
        self.hub.boveda.leer.return_value = {'open_id': 'synthetic-creator'}

    def tearDown(self):
        self.fixture.tearDown(self)

    def start(self):
        return self.fixture.start(self)

    def test_post_necesita_scope_vigente_para_web_y_app(self):
        scope = self.owner.get('/api/cloud/session', base_url=self.base).json['cache_scope']
        token = self.fixture.grant(self)['token']
        ruta = '/api/catalogo/vitrina/fijar'
        for cliente, auth in ((self.owner, {}), (self.client, {'Authorization': 'Bearer ' + token})):
            for extra in ({}, {'X-Corte-Cache-Scope': 'a' * 64}):
                self.hub.despachador.despachar.reset_mock()
                r = cliente.post(ruta, json={'product_ids': ['1']}, base_url=self.base,
                                 headers={**self.headers, **auth, **extra})
                self.assertEqual(r.status_code, 409)
                self.hub.despachador.despachar.assert_not_called()
            r = cliente.post(ruta, json={'product_ids': ['1']}, base_url=self.base,
                             headers={**self.headers, **auth, 'X-Corte-Cache-Scope': scope})
            self.assertEqual(r.status_code, 200)
        self.hub.boveda.leer.return_value = {'open_id': 'synthetic-creator-new'}
        self.hub.despachador.despachar.reset_mock()
        r = self.owner.post(ruta, json={'product_ids': ['1']}, base_url=self.base,
                            headers={**self.headers, 'X-Corte-Cache-Scope': scope})
        self.assertEqual(r.status_code, 409)
        self.hub.despachador.despachar.assert_not_called()
