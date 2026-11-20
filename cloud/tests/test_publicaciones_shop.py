"""Publicación con grant Creator sintético y transporte sin red."""
from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'hub'))

from creatorhub.errores import ErrorApi, ErrorDominio
from creatorhub.tiktok.cliente import ClienteTikTokReal
from creatorhub.tiktok.publicaciones import POST_VIDEO, SCOPE, STATUS_VIDEO, PublicacionesShop
from creatorhub.tiktok.transporte import TransporteHttps


class PublicacionesShopTests(unittest.TestCase):
    def setUp(self):
        self.grant = {'user_type': 1, 'open_id': 'creator-test', 'epoca_credenciales': 2,
                      'granted_scopes': [SCOPE], 'app_secret': 'synthetic-secret', 'access_token': 'synthetic-access'}
        self.conexion = {'estado': 'conectada'}
        self.boveda = SimpleNamespace(leer=lambda: dict(self.grant), secretos_vivos=lambda: ())
        self.almacen = Mock()
        self.almacen.epoca.return_value = 7
        self.registro = Mock()
        self.registro.iniciar.return_value = None
        self.cliente = Mock()
        self.servicio = self.crear_servicio(self.cliente)
        self.body = {'file_id': 'clip-01', 'titulo': 'Mi abrigo 🧥 #moda', 'product_id': '123', 'titulo_ancla': 'Abrigo'}
        self.solicitud = dict(self.body, confirmar=True)
        self.payload = {'video_info': {'file_id': 'clip-01', 'title': 'Mi abrigo 🧥 #moda'},
                        'product_link_info': {'product_id': '123', 'title': 'Abrigo'}}

    def crear_servicio(self, cliente):
        return PublicacionesShop(cliente, self.boveda, lambda: self.conexion, self.almacen, self.registro)

    def error(self, codigo, http, operacion, *args):
        with self.assertRaises(ErrorDominio) as exc:
            operacion(*args)
        self.assertEqual((exc.exception.codigo, exc.exception.http), (codigo, http))
        return exc.exception

    def test_preparar_es_local_y_proyecta_solo_el_contrato_y_permisos(self):
        capacidad = {'scope_requerido': SCOPE, 'scope_concedido': True, 'cuenta_creator_conectada': True}
        self.assertEqual(self.servicio.capacidades(), capacidad)
        self.assertEqual(self.servicio.preparar(self.body), {'payload': self.payload, 'autorizacion': capacidad})
        self.grant['granted_scopes'] = []
        self.assertEqual(self.servicio.preparar(self.body)['autorizacion'], dict(capacidad, scope_concedido=False))
        self.grant.clear()
        self.assertEqual(self.servicio.preparar(self.body), {'payload': self.payload, 'autorizacion':
                         dict(capacidad, scope_concedido=False, cuenta_creator_conectada=False)})
        self.cliente.llamar.assert_not_called()
        self.registro.iniciar.assert_not_called()

    def test_unidades_utf16_normalizacion_de_ancla_y_declaracion_de_ia(self):
        for bandera in (True, False):
            with self.subTest(bandera=bandera):
                body = dict(self.body, titulo='🎥' * 2000, titulo_ancla='  Saco de algodo\u0301n ', is_ai_generated=bandera)
                p = self.servicio.preparar(body)['payload']
                self.assertEqual(p['product_link_info']['title'], 'Saco de algodón')
                self.assertEqual(p['video_info']['title'], '🎥' * 2000)
                self.assertIs(p['video_info']['is_ai_generated'], bandera)
        self.assertEqual(self.servicio.preparar(dict(self.body, titulo='', titulo_ancla='A' * 29))['payload']
                         ['product_link_info']['title'], 'A' * 29)

    def test_campos_invalidos_no_reservan_ni_envian(self):
        for campo, valor in [('file_id', ''), ('file_id', 'archivo con espacio'), ('file_id', 'https://example.test/f'),
                             ('titulo', '🎥' * 2001), ('titulo', chr(0xD800)), ('titulo', None),
                             ('product_id', 123), ('product_id', 'x/123'), ('product_id', '１２３'),
                             ('titulo_ancla', ' '), ('titulo_ancla', 'A' * 30), ('titulo_ancla', 'Abrigo 🧥'),
                             ('titulo_ancla', 'Abrigo!'), ('is_ai_generated', 1), ('privacy_level', 'PUBLIC')]:
            with self.subTest(campo=campo, tipo=type(valor)):
                self.error('parametros_invalidos', 400, self.servicio.publicar, dict(self.solicitud, **{campo: valor}))
        for campo in self.body:
            with self.subTest(ausente=campo):
                self.error('parametros_invalidos', 400, self.servicio.preparar,
                           {k: v for k, v in self.body.items() if k != campo})
        for confirmacion in [1, None, False, 'true']:
            self.error('parametros_invalidos', 400, self.servicio.publicar, dict(self.body, confirmar=confirmacion))
        self.error('parametros_invalidos', 400, self.servicio.preparar, self.solicitud)
        self.error('parametros_invalidos', 400, self.servicio.publicar, self.body)
        self.registro.iniciar.assert_not_called()
        self.cliente.llamar.assert_not_called()

    def test_conexion_creator_y_scope_exigidos_antes_de_reservar_o_consultar(self):
        for estado, tipo, scopes, error, http in [
                ('reautorizar', 1, [SCOPE], 'reautorizar', 409),
                ('sin_autorizar', 1, [SCOPE], 'sin_credenciales', 409),
                ('conectada', True, [SCOPE], 'sin_permiso_tiktok', 403),
                ('conectada', 0, [SCOPE], 'sin_permiso_tiktok', 403),
                ('conectada', 1, ['video.publish'], 'sin_permiso_tiktok', 403)]:
            with self.subTest(estado=estado, tipo=tipo, scopes=scopes):
                self.conexion['estado'] = estado
                self.grant.update(user_type=tipo, granted_scopes=scopes)
                self.error(error, http, self.servicio.publicar, self.solicitud)
                self.error(error, http, self.servicio.estado, '789')
        self.cliente.llamar.assert_not_called()
        self.registro.iniciar.assert_not_called()

    def test_aceptacion_es_distinta_de_publicacion_y_se_reproduce_desde_el_registro(self):
        self.cliente.llamar.return_value = {'video': {'id': '789', 'datos_extra': 'oculto'}, 'quota': '3/day'}
        esperado = {'video_id': '789', 'estado': 'aceptada', 'cuota': '3/day'}
        self.assertEqual(self.servicio.publicar(self.solicitud), esperado)
        args, kwargs = self.cliente.llamar.call_args
        ctx = kwargs['ctx']
        self.assertEqual((ctx.open_id, ctx.epoca_credenciales, ctx.epoca_datos), ('creator-test', 2, 7))
        self.assertEqual(args, ('POST', POST_VIDEO, None, self.payload))
        self.assertFalse(kwargs['reintentar'])
        self.assertFalse(kwargs['reemitir_tras_refresh'])
        self.registro.iniciar.assert_called_once_with(ctx, 'clip-01', self.payload)
        self.registro.confirmar.assert_called_once_with(ctx, 'clip-01', esperado)
        self.registro.iniciar.return_value = esperado
        self.assertEqual(self.servicio.publicar(self.solicitud), esperado)
        self.assertEqual(self.cliente.llamar.call_count, 1)
        self.assertEqual(self.registro.confirmar.call_count, 1)
        self.registro.liberar_sin_envio.assert_not_called()

    def test_reserva_conflictiva_no_repite_ni_libera_el_envio(self):
        self.registro.iniciar.side_effect = ErrorDominio('conflicto', 'Envío en curso.', http=409)
        self.error('conflicto', 409, self.servicio.publicar, self.solicitud)
        self.cliente.llamar.assert_not_called()
        self.registro.confirmar.assert_not_called()
        self.registro.liberar_sin_envio.assert_not_called()

    def test_cambio_entre_reserva_y_cliente_libera_solo_su_reserva(self):
        self.registro.iniciar.side_effect = lambda *args: self.grant.update(epoca_credenciales=3)
        self.error('cuenta_cambio_sin_aplicar', 409, self.servicio.publicar, self.solicitud)
        self.cliente.llamar.assert_not_called()
        self.registro.confirmar.assert_not_called()
        self.registro.liberar_sin_envio.assert_called_once_with(*self.registro.iniciar.call_args.args)

    def test_cambio_de_cuenta_grant_o_base_durante_el_envio_es_incierto_y_no_expone_el_id(self):
        grant_inicial = dict(self.grant)
        for cambio in (lambda: self.grant.update(open_id='nuevo-creator'),
                       lambda: self.grant.update(granted_scopes=[]), lambda: self.grant.clear(),
                       lambda: setattr(self.almacen.epoca, 'return_value', 8)):
            self.grant.update(grant_inicial)
            self.almacen.epoca.return_value = 7

            def envio(*args, **kwargs):
                kwargs['antes_de_enviar']()
                cambio()
                return {'video': {'id': '789'}}

            self.cliente.llamar.side_effect = envio
            e = self.error('publicacion_sin_confirmar', 503, self.servicio.publicar, self.solicitud)
            self.assertNotIn('789', str(e.a_respuesta()))
        self.registro.confirmar.assert_not_called()
        self.registro.liberar_sin_envio.assert_not_called()

    def test_fallo_de_persistencia_tras_aceptacion_es_incierto_y_conserva_reserva(self):
        self.cliente.llamar.return_value = {'video': {'id': '789'}}
        for fallo in (sqlite3.OperationalError('synthetic-storage-detail'),
                      ErrorApi('credenciales_cambiaron', 'synthetic-storage-detail', 'abortar'),
                      ErrorDominio('conflicto', 'synthetic-storage-detail', http=409),
                      RuntimeError('synthetic-storage-detail')):
            with self.subTest(fallo=type(fallo)):
                self.registro.confirmar.side_effect = fallo
                e = self.error('publicacion_sin_confirmar', 503, self.servicio.publicar, self.solicitud)
                self.assertNotIn('789', str(e.a_respuesta()))
                self.assertNotIn('synthetic-storage-detail', str(e.a_respuesta()))
                self.assertIn('cuenta de TikTok Shop', e.mensaje)
        self.registro.liberar_sin_envio.assert_not_called()

    def test_respuesta_sin_id_sigue_reservada_y_se_filtra_cuota_opaca(self):
        for data in [None, {}, {'video': {}}, {'video': {'id': 789}}, {'video': {'id': '../id'}}]:
            with self.subTest(data=data):
                self.cliente.llamar.return_value = data
                self.error('publicacion_sin_confirmar', 503, self.servicio.publicar, self.solicitud)
        self.registro.confirmar.assert_not_called()
        self.registro.liberar_sin_envio.assert_not_called()
        self.cliente.llamar.return_value = {'video': {'id': '789'}, 'quota': 'texto opaco del proveedor'}
        self.assertEqual(self.servicio.publicar(self.solicitud), {'video_id': '789', 'estado': 'aceptada'})

    def test_estado_verifica_id_y_valores_y_solo_devuelve_fecha_de_publicacion(self):
        for situacion, esperado in [('PROCESSING', 'procesando'), ('SUCCESS', 'publicada'), ('FAIL', 'fallida')]:
            with self.subTest(situacion=situacion):
                self.cliente.llamar.return_value = {'video': {'id': '789', 'post_status': situacion, 'post_time': 100}}
                r = self.servicio.estado('789')
                if situacion == 'SUCCESS':
                    self.assertEqual(r.pop('publicado_en'), 100)
                self.assertEqual(r, {'video_id': '789', 'estado': esperado})
                self.assertEqual(self.cliente.llamar.call_args.args, ('GET', STATUS_VIDEO.format(video_id='789')))
        for data in [None, {'video': {'id': '790', 'post_status': 'SUCCESS'}},
                     {'video': {'id': '789', 'post_status': 'UNKNOWN'}}, {'video': {'id': '789', 'post_status': []}}]:
            self.cliente.llamar.return_value = data
            self.error('tiktok_no_disponible', 502, self.servicio.estado, '789')
        self.cliente.reset_mock()
        for video_id in ['../789', '789?q=x', 789, '']:
            self.error('parametros_invalidos', 400, self.servicio.estado, video_id)
        self.cliente.llamar.assert_not_called()
        self.registro.iniciar.assert_not_called()

    def transporte_simulado(self):
        reloj = SimpleNamespace(ahora=lambda: 100, monotonico=lambda: 100., esperar=Mock())
        transporte = TransporteHttps()
        opener = Mock()
        transporte.opener = lambda: opener
        respuesta = Mock(status=200)
        respuesta.getheaders.return_value = []
        opener.open.return_value = respuesta
        cliente = ClienteTikTokReal(self.boveda, transporte, reloj, self.almacen, Mock())
        cliente.volcar_errores = Mock()
        cliente._refrescar_desde_llamada = Mock()
        return self.crear_servicio(cliente), cliente, opener, respuesta

    def test_un_solo_post_firmado_aun_si_caduca_token_hay_timeout_o_error_transitorio(self):
        for http, codigo, timeout, esperado, status in [(200, 105002, False, 'reautorizar', 409),
                                                       (200, 105001, False, 'reautorizar', 409),
                                                       (200, 0, True, 'publicacion_sin_confirmar', 503),
                                                       (503, 0, False, 'publicacion_sin_confirmar', 503),
                                                       (429, 36009006, False, 'publicacion_sin_confirmar', 503),
                                                       (403, 105005, False, 'sin_permiso_tiktok', 403)]:
            with self.subTest(http=http, codigo=codigo, timeout=timeout):
                servicio, cliente, opener, respuesta = self.transporte_simulado()
                respuesta.status = http
                respuesta.read.return_value = json.dumps({'code': codigo, 'message': 'detalle opaco',
                                                           'data': {'video': {'id': '999'}}}).encode()
                if timeout:
                    respuesta.read.side_effect = TimeoutError()
                e = self.error(esperado, status, servicio.publicar, self.solicitud)
                self.assertNotIn('opaco', str(e.a_respuesta()))
                opener.open.assert_called_once()
                req = opener.open.call_args.args[0]
                self.assertEqual((req.get_method(), urlsplit(req.full_url).path), ('POST', POST_VIDEO))
                self.assertIn('sign=', urlsplit(req.full_url).query)
                self.assertEqual(json.loads(req.data), self.payload)
                cliente._refrescar_desde_llamada.assert_not_called()
                self.registro.liberar_sin_envio.assert_not_called()
                self.registro.confirmar.assert_not_called()

    def test_scope_revocado_en_la_espera_no_llega_al_transporte(self):
        servicio, cliente, opener, _ = self.transporte_simulado()
        cliente._tomar_ficha = lambda path: self.grant.update(granted_scopes=[])
        self.registro.liberar_sin_envio.side_effect = ErrorApi('credenciales_cambiaron', 'época', 'abortar')
        self.error('sin_permiso_tiktok', 403, servicio.publicar, self.solicitud)
        self.registro.liberar_sin_envio.assert_called_once_with(*self.registro.iniciar.call_args.args)
        opener.open.assert_not_called()
        self.registro.confirmar.assert_not_called()
