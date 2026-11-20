"""Recorrido HTTP de publicación con identidades sintéticas y sin tráfico a TikTok."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from cloud.tests import test_native_auth
from creatorhub.almacen import crear_almacen
from creatorhub.api.rutas import DespachadorHub
from creatorhub.interfaces import Contexto
from creatorhub.tiktok.publicaciones import PublicacionesShop
from creatorhub.tiktok.registro_publicacion import RegistroPublicacion


BASE = '/api/publicaciones/shop/'
VIDEO = {'file_id': 'file-clip-01', 'titulo': 'Mi abrigo', 'product_id': '123', 'titulo_ancla': 'Abrigo'}


class RutasPublicacionesTests(unittest.TestCase):
    def setUp(self):
        self.web = test_native_auth.NativeWebTests()
        self.web.setUp()
        self.addCleanup(self.web.tearDown)
        self.hub = self.web.hub
        self.cliente = Mock()
        self.grant = {'open_id': 'synthetic-creator', 'user_type': 1, 'epoca_credenciales': 2,
                      'granted_scopes': ['creator.video.write']}
        self.hub.boveda.leer.side_effect = lambda: self.grant.copy()
        self.hub.auth.conexion.return_value = {'estado': 'conectada'}
        reloj = SimpleNamespace(ahora=lambda: 123456)
        almacen = crear_almacen(str(Path(self.web.folder.name) / 'videos.sqlite'), reloj)
        self.addCleanup(almacen.cerrar)
        self.hub.publicaciones_shop = PublicacionesShop(self.cliente, self.hub.boveda, self.hub.auth.conexion,
                                                        almacen, RegistroPublicacion(almacen, reloj.ahora))
        self.hub.despachador = DespachadorHub(self.hub)

    def request(self, metodo, accion, cliente=None, cabeceras=None, **kw):
        return (cliente or self.web.owner).open(BASE + accion, method=metodo, base_url=self.web.base,
                                                headers={**self.web.headers, **(cabeceras or {})}, **kw)

    def scope(self):
        session = self.web.owner.get('/api/cloud/session', base_url=self.web.base)
        return {'X-Corte-Cache-Scope': session.json['cache_scope']}

    def test_preparar_y_capacidades_sin_permiso_no_contactan_a_tiktok(self):
        self.grant['granted_scopes'] = []
        capacidades = self.request('GET', 'capacidades')
        self.assertEqual(capacidades.status_code, 200)
        self.assertEqual(capacidades.json, {'scope_requerido': 'creator.video.write', 'scope_concedido': False,
                                            'cuenta_creator_conectada': True})
        preparado = self.request('POST', 'preparar', json=VIDEO)
        self.assertEqual(preparado.status_code, 200)
        self.assertEqual(preparado.json['autorizacion'], capacidades.json)
        self.assertEqual(preparado.json['payload']['product_link_info'], {'product_id': '123', 'title': 'Abrigo'})
        self.assertIn('no-store', preparado.headers['Cache-Control'])
        self.assertFalse(self.cliente.mock_calls)

    def test_sesion_scope_e_identidad_se_validan_en_web_y_app(self):
        actual = self.scope()
        token = self.web.grant()['token']
        operaciones = [('POST', 'publicar', {'json': {**VIDEO, 'confirmar': True}}), ('GET', '789/estado', {})]
        for metodo, accion, kw in operaciones:
            self.assertEqual(self.request(metodo, accion, self.web.client, actual, **kw).status_code, 401)
            for sesion, headers in ((self.web.owner, {}), (self.web.client, {'Authorization': 'Bearer ' + token})):
                for invalido in ({}, {'X-Corte-Cache-Scope': 'a' * 64}):
                    with self.subTest(metodo=metodo, nativo=bool(headers), scope=bool(invalido)):
                        r = self.request(metodo, accion, sesion, {**headers, **invalido}, **kw)
                        self.assertEqual((r.status_code, r.json['error']['codigo']), (409, 'cuenta_cambio_sin_aplicar'))
        self.grant['open_id'] = 'otro-creador'
        for metodo, accion, kw in operaciones:
            r = self.request(metodo, accion, cabeceras=actual, **kw)
            self.assertEqual((r.status_code, r.json['error']['codigo']), (409, 'cuenta_cambio_sin_aplicar'))
        self.assertFalse(self.cliente.mock_calls)

    def test_la_entrada_rechaza_solicitudes_invalidas_sin_enviar(self):
        scope = self.scope()
        casos = [
            ('GET', 'capacidades?extra=1', {}, 400),
            ('GET', '789/estado', {'data': b'{}'}, 400),
            ('POST', 'preparar', {'data': b'{', 'content_type': 'application/json'}, 400),
            ('POST', 'publicar', {'json': []}, 400),
            ('POST', 'publicar', {'json': {**VIDEO, 'confirmar': True, 'extra': 'dato'}}, 400),
            ('POST', 'publicar', {'json': VIDEO}, 400),
            ('POST', 'publicar', {'data': 'video', 'content_type': 'text/plain'}, 415),
            ('DELETE', '789/estado', {}, 405),
        ]
        for metodo, accion, kw, esperado in casos:
            with self.subTest(metodo=metodo, accion=accion, kw=kw):
                r = self.request(metodo, accion, cabeceras=scope, **kw)
                self.assertEqual(r.status_code, esperado, r.get_data(as_text=True))
        r = self.request('POST', 'publicar', cabeceras={**scope, 'Origin': 'https://otro.example'}, json=VIDEO)
        self.assertEqual(r.status_code, 403)
        self.assertFalse(self.cliente.mock_calls)

    def test_web_publica_y_app_recupera_el_mismo_envio_y_su_estado(self):
        scope = self.scope()
        nativo = {**scope, 'Authorization': 'Bearer ' + self.web.grant()['token']}
        self.cliente.llamar.side_effect = [
            {'video': {'id': '789'}, 'quota': '3/day'},
            {'video': {'id': '789', 'post_status': 'SUCCESS', 'post_time': 100}},
        ]
        body = {**VIDEO, 'confirmar': True}
        primero = self.request('POST', 'publicar', cabeceras=scope, json=body)
        self.assertEqual(primero.status_code, 200, primero.json)
        self.assertEqual(primero.json, {'video_id': '789', 'estado': 'aceptada', 'cuota': '3/day'})
        repetido = self.request('POST', 'publicar', self.web.client, nativo, json=body)
        self.assertEqual((repetido.status_code, repetido.json), (200, primero.json))
        self.cliente.llamar.assert_called_once()
        self.assertEqual(self.cliente.llamar.call_args.args[:2], ('POST', '/affiliate_creator/202607/videos'))
        estado = self.request('GET', '789/estado', self.web.client, nativo)
        self.assertEqual((estado.status_code, estado.json), (200, {'video_id': '789', 'estado': 'publicada',
                                                                  'publicado_en': 100}))
        self.assertEqual(self.cliente.llamar.call_args.args[:2], ('GET', '/affiliate_creator/202509/videos/789/status'))

    def test_los_segmentos_de_rutas_de_lectura_se_decodifican_una_sola_vez(self):
        self.hub.display.estado.return_value = {'conectada': False}
        display = self.web.owner.get('/api/display/%65stado', base_url=self.web.base)
        self.assertEqual((display.status_code, display.json), (200, {'conectada': False}))
        scope = self.scope()
        self.cliente.llamar.return_value = {'video': {'id': '789', 'post_status': 'PROCESSING'}}
        estado = self.request('GET', '%37%38%39/estado', cabeceras=scope)
        self.assertEqual((estado.status_code, estado.json), (200, {'video_id': '789', 'estado': 'procesando'}))
        literal = self.request('GET', '%2537%2538%2539/estado', cabeceras=scope)
        self.assertEqual((literal.status_code, literal.json['error']['codigo']), (400, 'parametros_invalidos'))
        self.cliente.llamar.assert_called_once()

    def test_lan_no_puede_usar_las_cuatro_operaciones_y_demo_no_ofrece_servicio(self):
        ctx = Contexto(origen='lan', permisos='lectura_escritura')
        for metodo, accion in [('GET', 'capacidades'), ('POST', 'preparar'), ('POST', 'publicar'), ('GET', '789/estado')]:
            r = self.hub.despachador.despachar(metodo, BASE + accion, '', {}, b'', ctx)
            self.assertEqual((r.status, json.loads(r.cuerpo)['error']['codigo']), (403, 'solo_local'))
        self.hub.publicaciones_shop = None
        r = self.request('GET', 'capacidades')
        self.assertEqual((r.status_code, r.json['error']['codigo']), (404, 'no_encontrado'))
        self.assertFalse(self.cliente.mock_calls)
