"""Carga HTTP de videos desde web y app nativa, con un servidor de TikTok simulado."""
import hashlib
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from cloud.tests import test_native_auth
from creatorhub.tiktok.carga_video import CargaVideosShop, INICIAR, PARTE_MAX, VIDEO_MAX
from creatorhub.tiktok.cliente import API, P_ARCHIVO_VIDEO, ClienteTikTokReal
from creatorhub.tiktok.firma import generar_firma
from creatorhub.tiktok.publicaciones import POST_VIDEO, PublicacionesShop
from creatorhub.tiktok.transporte import TransporteHttps

BASE = '/api/publicaciones/shop/archivo'
MP4 = bytes.fromhex('000000186674797069736f6d0000020069736f6d69736f32')
URL = API + '/file/v1/upload?ruta=prueba'


class CargaVideoTests(unittest.TestCase):
    def setUp(self):
        self.web = test_native_auth.NativeWebTests()
        self.web.setUp()
        self.addCleanup(self.web.tearDown)
        self.hub = self.web.hub
        self.grant = {'app_key': 'test-app', 'app_secret': 'test-secret', 'access_token': 'test-access',
                      'open_id': 'creadora', 'epoca_credenciales': 1, 'user_type': 1,
                      'granted_scopes': ['creator.video.write']}
        self.hub.boveda.leer.side_effect = lambda: dict(self.grant)
        self.hub.auth.conexion.return_value = {'estado': 'conectada'}
        self.hub.almacen.epoca.return_value = 1
        reloj = SimpleNamespace(ahora=lambda: 600, monotonico=lambda: 600, esperar=Mock())
        transporte = TransporteHttps()
        self.opener = Mock()
        transporte.opener = lambda: self.opener
        self.cliente = ClienteTikTokReal(self.hub.boveda, transporte, reloj, self.hub.almacen, Mock())
        self.cliente.volcar_errores = Mock()
        self.hub.publicaciones_shop = PublicacionesShop(self.cliente, self.hub.boveda, self.hub.auth.conexion,
                                                       self.hub.almacen, Mock())
        self.hub.carga_videos_shop = CargaVideosShop(self.cliente, self.hub.publicaciones_shop)
        self.scope = self.web.owner.get('/api/cloud/session', base_url=self.web.base).json['cache_scope']
        self.headers = {**self.web.headers, 'X-Corte-Cache-Scope': self.scope}

    def http(self, method, path, headers=None, session=None, **kwargs):
        return (session or self.web.owner).open(BASE + path, method=method, base_url=self.web.base,
                                                headers=self.headers if headers is None else headers, **kwargs)

    def proveedor(self, *respuestas):
        envios = []
        for data in respuestas:
            r = Mock(status=200)
            r.getheaders.return_value = []
            r.read.return_value = json.dumps({'code': 0, 'data': data}).encode()
            envios.append(r)
        self.opener.open.side_effect = envios

    def subir(self, nombre='mi prenda.mp4', datos=MP4, **kwargs):
        return self.http('POST', '', data={'archivo': (io.BytesIO(datos), nombre)}, **kwargs)

    def iniciar(self, tamano=PARTE_MAX + 11, nombre='mi look.mp4', **kwargs):
        return self.http('POST', '/iniciar', json={'bytes': tamano, 'nombre': nombre}, **kwargs)

    def parte(self, ident, numero, datos, **kwargs):
        return self.http('PUT', f'/{ident}/partes/{numero}', data=datos,
                         content_type='application/octet-stream', **kwargs)

    def test_directa_envia_el_binario_y_firma_solo_los_parametros(self):
        self.proveedor({'video_file': {'id': 'archivo123', 'md5': hashlib.md5(MP4).hexdigest()}})
        token = self.web.grant()['token']
        r = self.subir(headers={**self.headers, 'Authorization': 'Bearer ' + token}, session=self.web.client)
        self.assertEqual((r.status_code, r.json), (200, {'file_id': 'archivo123'}))
        self.opener.open.assert_called_once()
        req = self.opener.open.call_args.args[0]
        url = urlsplit(req.full_url)
        self.assertEqual((req.method, url.path), ('POST', P_ARCHIVO_VIDEO))
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.assertEqual(query['sign'], generar_firma(P_ARCHIVO_VIDEO, query, None, 'test-secret'))
        self.assertEqual(req.get_header('X-tts-access-token'), 'test-access')
        self.assertIn(b'name="data"; filename="video.mp4"', req.data)
        self.assertNotIn(b'mi prenda', req.data)
        self.assertIn(MP4, req.data)

    def test_grande_completa_sin_repetir_partes_y_conserva_enrutamiento(self):
        self.proveedor({'upload_url': URL, 'upload_token': 'token-sintetico'},
                       {'part_id': 'parte1'}, {'resource_id': 'video-completo'})
        tamano = PARTE_MAX + 11
        r = self.iniciar(tamano)
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual(set(r.json), {'carga_id', 'partes'})
        self.assertEqual(r.json['partes'], 2)
        ident = r.json['carga_id']
        req = self.opener.open.call_args.args[0]
        self.assertEqual(urlsplit(req.full_url).path, INICIAR)
        self.assertEqual(json.loads(req.data), {'file_size': tamano, 'file_type': 'video', 'file_name': 'video.mp4',
                                                'total_chunk_count': 2, 'target_path': '[POST]' + POST_VIDEO})
        primero = MP4.ljust(tamano // 2, b'A')
        ultimo = b'B' * (tamano - len(primero))
        self.assertEqual(self.parte(ident, 2, ultimo).status_code, 409)
        self.assertEqual(self.parte(ident, 1, primero).json, {'recibida': 1})
        self.assertEqual(self.parte(ident, 1, primero).json, {'recibida': 1})
        self.assertEqual(self.parte(ident, 2, ultimo).json, {'file_id': 'video-completo'})
        self.assertEqual(self.parte(ident, 2, ultimo).json, {'file_id': 'video-completo'})
        self.assertEqual(self.opener.open.call_count, 3)
        req = self.opener.open.call_args.args[0]
        self.assertEqual((req.method, req.data, req.get_header('Content-type')), ('PUT', ultimo, 'video/mp4'))
        self.assertEqual(parse_qs(urlsplit(req.full_url).query),
                         {'ruta': ['prueba'], 'chunk_num': ['2'], 'app_key': ['test-app'], 'upload_token': ['token-sintetico']})

    def test_sesion_cuenta_scope_formato_y_limites_se_validan_antes_de_enviar(self):
        self.assertEqual(self.subir(session=self.web.client).status_code, 401)
        self.assertEqual(self.subir(headers={**self.headers, 'Origin': 'https://otro.example'}).status_code, 403)
        self.assertEqual(self.subir(headers=self.web.headers).status_code, 409)
        self.assertEqual(self.subir(nombre='prenda.jpg').status_code, 422)
        self.assertEqual(self.subir(datos=b'\xff\xd8\xff' + b'x' * 24).status_code, 422)
        self.assertEqual(self.subir(datos=MP4[:8] + b'heic' + MP4[12:]).status_code, 422)
        self.assertEqual(self.iniciar(VIDEO_MAX + 1).status_code, 422)
        self.assertEqual(self.iniciar(PARTE_MAX, 'clip.avi').status_code, 422)
        self.assertEqual(self.http('POST', '', json={'url': 'video'}).status_code, 415)
        self.grant['granted_scopes'] = []
        self.assertEqual(self.subir().status_code, 403)
        self.assertEqual(self.iniciar().status_code, 403)
        self.opener.open.assert_not_called()

    def test_rechaza_sesion_de_otra_cuenta_o_generacion(self):
        self.proveedor({'upload_url': URL, 'upload_token': 'token-sintetico'})
        ident = self.iniciar(PARTE_MAX).json['carga_id']
        self.grant['epoca_credenciales'] = 2
        r = self.parte(ident, 1, b'x')
        self.assertEqual((r.status_code, r.json['error']['codigo']), (409, 'cuenta_cambio_sin_aplicar'))
        self.opener.open.assert_called_once()

    def test_validacion_checksum_y_respuesta_final(self):
        self.proveedor({'video_file': {'id': 'x', 'md5': '0'*32}},
                       {'upload_url': URL, 'upload_token': 'token-sintetico'}, {'part_id': 'incompleto'})
        self.assertEqual(self.subir().status_code, 502)
        ident = self.iniciar(PARTE_MAX).json['carga_id']
        self.assertEqual(self.parte(ident, 1, MP4.ljust(PARTE_MAX, b'x')).status_code, 502)
        self.assertEqual(self.parte(ident, 1, b'x').status_code, 404)

    def test_url_de_carga_ajena_nunca_recibe_las_credenciales(self):
        self.proveedor({'upload_url': 'https://otro.example/upload', 'upload_token': 'token-sintetico'})
        ident = self.iniciar(PARTE_MAX).json['carga_id']
        self.assertEqual(self.parte(ident, 1, MP4.ljust(PARTE_MAX, b'x')).status_code, 502)
        self.opener.open.assert_called_once()

    def test_peticiones_grandes_no_amplian_el_limite_de_otras_rutas(self):
        self.proveedor({'video_file': {'id': 'archivo-grande'}})
        self.assertEqual(self.subir(datos=MP4.ljust(320_000, b'x')).status_code, 200)
        r = self.web.owner.post('/api/publicaciones/shop/preparar', data=b'x' * 320_000,
                                content_type='application/json', base_url=self.web.base, headers=self.headers)
        self.assertEqual(r.status_code, 413)
