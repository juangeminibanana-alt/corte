"""Consulta dirigida de videos propios por ID (POST /v2/video/query/) en el cliente Display.

Usan el cliente real con la bóveda cifrada de la nube (archivo temporal y llave sintética) o la bóveda demo en
memoria, siempre con un transporte sintético: nunca leen una conexión del operador ni llaman a TikTok.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'hub'))

from creatorhub.errores import ErrorRed, ErrorTimeoutLectura
from creatorhub.nube import BovedaDisplayNube
from creatorhub.tiktok_dev.boveda import BovedaDisplay, datos_demo
from creatorhub.tiktok_dev.cliente import (API, CAMPOS_VIDEO, MAX_IDS_CONSULTA, P_CONSULTA_VIDEOS, P_TOKEN,
                                           crear_cliente_display, validar_ids_video)
from creatorhub.tiktok_dev.demo import TransporteDisplayDemo
from creatorhub.tiktok_dev.errores import MENSAJES, ErrorDisplay

AHORA = 1_790_000_000
ID_A = '7312345678901234567'            # más de 2^53: como número se corrompe en JavaScript
ID_B = '7400000000000000001'
ID_INT64 = '9223372036854775808'        # 2^63: ni siquiera cabe en un entero de 64 bits con signo
TEXTO_TIKTOK = 'Synthetic upstream text that must never be stored'
CREDENCIALES = {'client_key': 'synthetic-client-key', 'client_secret': 'synthetic-client-secret',
                'access_token': 'synthetic-access-token', 'refresh_token': 'synthetic-refresh-token',
                'access_expira_at': AHORA + 7200, 'refresh_expira_at': AHORA + 180 * 86400,
                'open_id': 'synthetic-open-id', 'scopes': ['user.info.basic', 'video.list'], 'reautorizar': False}


class RelojFijo:
    def __init__(self, ahora: int) -> None:
        self._ahora = ahora

    def ahora(self) -> int:
        return self._ahora

    def monotonico(self) -> float:
        return float(self._ahora)

    def esperar(self, segundos: float, cancelar=None) -> bool:
        return False


def ok(videos: list) -> tuple[int, dict]:
    return 200, {'data': {'videos': videos}, 'error': {'code': 'ok', 'message': '', 'log_id': 'synthetic-log-ok'}}


def fallo(status: int, codigo: str) -> tuple[int, dict]:
    return status, {'data': {}, 'error': {'code': codigo, 'message': TEXTO_TIKTOK, 'log_id': 'synthetic-log-error'}}


def video(vid, vistas: int = 10) -> dict:
    return {'id': vid, 'create_time': AHORA - 86400, 'title': f'Video {vid}', 'view_count': vistas,
            'like_count': 3, 'comment_count': 1, 'share_count': 0, 'duration': 15,
            'share_url': f'https://www.tiktok.com/@synthetic/video/{vid}'}


class ConClienteNube(unittest.TestCase):
    """Cliente Display de la nube con la bóveda AES-GCM real en una carpeta temporal."""

    def setUp(self) -> None:
        self.carpeta = tempfile.TemporaryDirectory()
        ruta = str(Path(self.carpeta.name) / 'tiktok_display.aesgcm')
        self.boveda = BovedaDisplayNube(ruta, 'synthetic-master-' * 4, 'display')
        self.boveda.mutar(lambda d: d.update(CREDENCIALES), cambia_credenciales=True)
        self.transporte = Mock()
        self.transporte.manejar.side_effect = AssertionError('Petición inesperada en una prueba sintética')
        self.cliente = crear_cliente_display(self.boveda, self.transporte, RelojFijo(AHORA))

    def tearDown(self) -> None:
        self.carpeta.cleanup()

    def responder(self, *respuestas) -> None:
        self.transporte.manejar.side_effect = list(respuestas)

    def llamadas(self) -> list[tuple]:
        return [c.args for c in self.transporte.manejar.call_args_list]


class ContratoConsultaVideosTests(ConClienteNube):
    def test_envia_post_con_filters_video_ids_en_texto_y_los_campos_de_video(self) -> None:
        self.responder(ok([video(ID_B), video(ID_A)]))

        self.cliente.consultar_videos([ID_A, ID_B])

        ((metodo, url, cabeceras, cuerpo),) = self.llamadas()
        u = urlsplit(url)
        self.assertEqual(metodo, 'POST')
        self.assertEqual(f'{u.scheme}://{u.netloc}{u.path}', API + P_CONSULTA_VIDEOS)
        self.assertEqual(API + P_CONSULTA_VIDEOS, 'https://open.tiktokapis.com/v2/video/query/')
        self.assertEqual(parse_qs(u.query), {'fields': [','.join(CAMPOS_VIDEO)]})
        self.assertEqual(cabeceras, {'Authorization': 'Bearer synthetic-access-token',
                                     'Content-Type': 'application/json'})
        self.assertEqual(json.loads(cuerpo), {'filters': {'video_ids': [ID_A, ID_B]}})
        self.assertIn(f'"{ID_A}"'.encode('ascii'), cuerpo)              # cadena JSON, nunca número
        self.assertNotIn(f':{ID_A}'.encode('ascii'), cuerpo)

    def test_devuelve_solo_lo_pedido_en_el_orden_pedido_con_ids_en_texto(self) -> None:
        ajeno = '7999999999999999999'
        self.responder(ok([video(ID_B, 20), 'no-es-video', {'title': 'sin id'}, video(ajeno), video(True),
                           video(int(ID_A), 30), video(ID_B, 99)]))

        videos = self.cliente.consultar_videos([ID_A, ID_B, ID_INT64])

        self.assertEqual([v['id'] for v in videos], [ID_A, ID_B])
        self.assertTrue(all(type(v['id']) is str for v in videos))
        self.assertEqual([v['view_count'] for v in videos], [30, 20])  # el primero de cada ID, campos intactos
        self.assertEqual(videos[1]['share_url'], f'https://www.tiktok.com/@synthetic/video/{ID_B}')

    def test_ids_repetidos_viajan_una_sola_vez(self) -> None:
        self.responder(ok([video(ID_A)]))

        self.cliente.consultar_videos((ID_A, ID_B, ID_A))

        self.assertEqual(json.loads(self.llamadas()[0][3]), {'filters': {'video_ids': [ID_A, ID_B]}})

    def test_lote_de_veinte_ids_es_valido(self) -> None:
        ids = [str(7300000000000000000 + i) for i in range(MAX_IDS_CONSULTA)]
        self.responder(ok([video(i) for i in ids]))

        self.assertEqual([v['id'] for v in self.cliente.consultar_videos(ids)], ids)
        self.assertEqual(json.loads(self.llamadas()[0][3])['filters']['video_ids'], ids)

    def test_una_sola_llamada_aunque_la_respuesta_traiga_cursor_y_has_more(self) -> None:
        self.responder((200, {'data': {'videos': [video(ID_A)], 'cursor': 1790000000000, 'has_more': True},
                              'error': {'code': 'ok', 'message': '', 'log_id': 'synthetic-log-ok'}}))

        self.assertEqual([v['id'] for v in self.cliente.consultar_videos([ID_A, ID_B])], [ID_A])
        self.assertEqual(len(self.llamadas()), 1)

    def test_respuesta_sin_videos_es_una_lista_vacia(self) -> None:
        for data in ({}, {'videos': None}, {'videos': {'id': ID_A}}):
            with self.subTest(data=data):
                self.responder((200, {'data': data, 'error': {'code': 'ok', 'message': '', 'log_id': 'x'}}))
                self.assertEqual(self.cliente.consultar_videos([ID_A]), [])


class ValidacionLoteTests(ConClienteNube):
    def test_rechaza_lotes_invalidos_antes_de_tocar_la_red(self) -> None:
        invalidos = {
            'vacío': [],
            'veintiuno': [str(7300000000000000000 + i) for i in range(MAX_IDS_CONSULTA + 1)],
            'entero': [int(ID_A)],
            'booleano': [True],
            'None': [None],
            'letras': ['73123a'],
            'espacios': [f' {ID_A}'],
            'signo': [f'-{ID_A}'],
            'dígitos no ASCII': ['٧٣١٢'],
            'cero a la izquierda': ['0012'],
            'cero': ['0'],
            'veintiún dígitos': ['1' + '0' * 20],
            'demasiado largo': ['7' * 26],
            'cadena suelta': ID_A,
            'conjunto': {ID_A},
            'nada': None,
            'bytes': ID_A.encode('ascii'),
        }
        for nombre, lote in invalidos.items():
            with self.subTest(nombre):
                with self.assertRaises(ValueError):
                    self.cliente.consultar_videos(lote)
        self.transporte.manejar.assert_not_called()

    def test_validar_ids_conserva_el_texto_exacto(self) -> None:
        veinte_digitos = '1' + '0' * 19
        self.assertEqual(validar_ids_video([ID_INT64, '12', ID_INT64, veinte_digitos]), [ID_INT64, '12', veinte_digitos])
        self.assertEqual(validar_ids_video((ID_A,)), [ID_A])

    def test_scope_video_list_no_concedido_responde_permiso_faltante_sin_red(self) -> None:
        self.boveda.mutar(lambda d: d.update(scopes=['user.info.basic', 'user.info.stats']))

        with self.assertRaises(ErrorDisplay) as ctx:
            self.cliente.consultar_videos([ID_A])

        self.assertEqual(ctx.exception.codigo, 'permiso_faltante')
        self.transporte.manejar.assert_not_called()
        self.assertFalse(self.boveda.leer().get('reautorizar'))

    def test_scopes_desconocidos_no_bloquean_la_consulta(self) -> None:
        self.boveda.mutar(lambda d: d.update(scopes=[]))           # bóvedas antiguas sin la lista de scopes
        self.responder(ok([video(ID_A)]))

        self.assertEqual([v['id'] for v in self.cliente.consultar_videos([ID_A])], [ID_A])
        self.assertEqual(len(self.llamadas()), 1)


class ErroresConsultaVideosTests(ConClienteNube):
    def assert_error_limpio(self, e: ErrorDisplay, codigo: str, http: int | None) -> None:
        self.assertEqual(e.codigo, codigo)
        self.assertEqual(e.http, http)
        self.assertEqual(e.mensaje, MENSAJES[codigo])
        self.assertNotIn(TEXTO_TIKTOK, f'{e} {e.mensaje} {e.como_dict(AHORA)}')

    def test_parametros_rechazados_conserva_solo_codigo_http_y_log_id(self) -> None:
        self.responder(fallo(400, 'invalid_params'))

        with self.assertRaises(ErrorDisplay) as ctx:
            self.cliente.consultar_videos([ID_A])

        self.assert_error_limpio(ctx.exception, 'respuesta_invalida', 400)
        self.assertEqual(ctx.exception.log_id, 'synthetic-log-error')
        self.assertEqual(len(self.llamadas()), 1)                         # sin reintentos
        self.assertFalse(self.boveda.leer().get('reautorizar'))

    def test_limite_y_caida_son_transitorios_y_no_marcan_reautorizar(self) -> None:
        for respuesta, codigo in ((fallo(429, 'rate_limit_exceeded'), 'limite'),
                                  (fallo(500, 'internal_error'), 'tiktok_no_disponible')):
            with self.subTest(codigo):
                self.responder(respuesta)
                with self.assertRaises(ErrorDisplay) as ctx:
                    self.cliente.consultar_videos([ID_A])
                self.assert_error_limpio(ctx.exception, codigo, respuesta[0])
                self.assertTrue(ctx.exception.transitorio)
        self.assertFalse(self.boveda.leer().get('reautorizar'))

    def test_red_caida_o_timeout_se_clasifican_sin_reintentar(self) -> None:
        for excepcion, codigo in ((ErrorRed('synthetic'), 'sin_internet'),
                                  (ErrorTimeoutLectura('synthetic'), 'tiktok_no_disponible')):
            with self.subTest(codigo):
                self.transporte.manejar.reset_mock()
                self.responder(excepcion)
                with self.assertRaises(ErrorDisplay) as ctx:
                    self.cliente.consultar_videos([ID_A])
                self.assert_error_limpio(ctx.exception, codigo, None)
                self.assertEqual(len(self.llamadas()), 1)

    def test_token_vencido_renueva_guarda_la_rotacion_y_reintenta_una_vez(self) -> None:
        renovado = (200, {'access_token': 'synthetic-access-token-2', 'refresh_token': 'synthetic-refresh-token-2',
                          'expires_in': 7200, 'refresh_expires_in': 180 * 86400, 'open_id': 'synthetic-open-id',
                          'scope': 'user.info.basic,video.list', 'token_type': 'Bearer'})
        self.responder(fallo(401, 'access_token_invalid'), renovado, ok([video(ID_A)]))

        videos = self.cliente.consultar_videos([ID_A])

        self.assertEqual([v['id'] for v in videos], [ID_A])
        consulta1, renovacion, consulta2 = self.llamadas()
        self.assertTrue(consulta1[1].startswith(API + P_CONSULTA_VIDEOS))
        self.assertEqual(renovacion[1], API + P_TOKEN)
        self.assertEqual(parse_qs(renovacion[3].decode('ascii'))['grant_type'], ['refresh_token'])
        self.assertEqual(consulta2[2]['Authorization'], 'Bearer synthetic-access-token-2')
        self.assertEqual(consulta2[3], consulta1[3])                      # mismo lote en el reintento
        guardado = self.boveda.leer()
        self.assertEqual(guardado['refresh_token'], 'synthetic-refresh-token-2')
        self.assertFalse(guardado.get('reautorizar'))

    def test_token_rechazado_dos_veces_marca_reautorizar(self) -> None:
        renovado = (200, {'access_token': 'synthetic-access-token-2', 'refresh_token': 'synthetic-refresh-token-2',
                          'expires_in': 7200, 'refresh_expires_in': 180 * 86400, 'open_id': 'synthetic-open-id',
                          'scope': 'user.info.basic,video.list'})
        self.responder(fallo(401, 'access_token_invalid'), renovado, fallo(401, 'access_token_invalid'))

        with self.assertRaises(ErrorDisplay) as ctx:
            self.cliente.consultar_videos([ID_A])

        self.assert_error_limpio(ctx.exception, 'reautorizar', 401)
        self.assertTrue(self.boveda.leer()['reautorizar'])
        self.assertEqual(len(self.llamadas()), 3)

    def test_el_registro_no_contiene_ids_tokens_ni_texto_de_tiktok(self) -> None:
        self.responder(fallo(429, 'rate_limit_exceeded'))

        with self.assertLogs('creatorhub', level='DEBUG') as registro, self.assertRaises(ErrorDisplay):
            self.cliente.consultar_videos([ID_A, ID_B])

        texto = '\n'.join(registro.output)
        self.assertIn('limite', texto)
        for prohibido in (ID_A, ID_B, 'synthetic-access-token', 'synthetic-refresh-token', TEXTO_TIKTOK):
            self.assertNotIn(prohibido, texto)

    def test_sin_conexion_no_toca_la_red(self) -> None:
        self.boveda.mutar(lambda d: d.update(access_token=None, refresh_token=None), cambia_credenciales=True)

        with self.assertRaises(ErrorDisplay) as ctx:
            self.cliente.consultar_videos([ID_A])

        self.assertEqual(ctx.exception.codigo, 'sin_conexion')
        self.transporte.manejar.assert_not_called()


class ClasificacionPermisosTests(ConClienteNube):
    """TikTok manda scope_not_authorized con HTTP 401: es un permiso que falta, no un token vencido."""

    RENOVADO = (200, {'access_token': 'synthetic-access-token-2', 'refresh_token': 'synthetic-refresh-token-2',
                      'expires_in': 7200, 'refresh_expires_in': 180 * 86400, 'open_id': 'synthetic-open-id',
                      'scope': 'user.info.basic,video.list'})

    def assert_permiso_sin_renovar(self, ctx, http: int) -> None:
        self.assertEqual(ctx.exception.codigo, 'permiso_faltante')
        self.assertEqual(ctx.exception.http, http)
        self.assertEqual(ctx.exception.log_id, 'synthetic-log-error')
        self.assertFalse(ctx.exception.reautorizar)
        self.assertEqual(len(self.llamadas()), 1)                         # sin /v2/oauth/token/ ni reintento
        guardado = self.boveda.leer()
        self.assertEqual(guardado['refresh_token'], 'synthetic-refresh-token')
        self.assertFalse(guardado.get('reautorizar'))

    def test_scope_no_autorizado_401_en_la_consulta(self) -> None:
        self.responder(fallo(401, 'scope_not_authorized'))
        with self.assertRaises(ErrorDisplay) as ctx:
            self.cliente.consultar_videos([ID_A])
        self.assert_permiso_sin_renovar(ctx, 401)

    def test_scope_permission_missed_400(self) -> None:
        self.responder(fallo(400, 'scope_permission_missed'))
        with self.assertRaises(ErrorDisplay) as ctx:
            self.cliente.consultar_videos([ID_A])
        self.assert_permiso_sin_renovar(ctx, 400)

    def test_scope_no_autorizado_401_en_perfil_y_listado(self) -> None:
        llamadas = {'perfil': self.cliente.usuario,
                    'listado': lambda: [p for p in self.cliente.listar_videos(tope=20)]}
        for nombre, llamar in llamadas.items():
            with self.subTest(nombre):
                self.transporte.manejar.reset_mock()
                self.responder(fallo(401, 'scope_not_authorized'))
                with self.assertRaises(ErrorDisplay) as ctx:
                    llamar()
                self.assert_permiso_sin_renovar(ctx, 401)

    def test_401_sin_codigo_sigue_renovando_y_reintentando(self) -> None:
        self.responder((401, None), self.RENOVADO, ok([video(ID_A)]))

        self.assertEqual([v['id'] for v in self.cliente.consultar_videos([ID_A])], [ID_A])
        self.assertEqual([urlsplit(c[1]).path for c in self.llamadas()],
                         [P_CONSULTA_VIDEOS, P_TOKEN, P_CONSULTA_VIDEOS])

    def test_403_sin_codigo_es_permiso_faltante(self) -> None:
        self.responder((403, None))
        with self.assertRaises(ErrorDisplay) as ctx:
            self.cliente.consultar_videos([ID_A])
        self.assertEqual(ctx.exception.codigo, 'permiso_faltante')
        self.assertEqual(len(self.llamadas()), 1)


class DemoConsultaVideosTests(unittest.TestCase):
    """El transporte demo entiende video/query con los mismos videos sintéticos de video/list."""

    def setUp(self) -> None:
        reloj = RelojFijo(AHORA)
        self.transporte = TransporteDisplayDemo(reloj)
        boveda = BovedaDisplay(None, datos=datos_demo(AHORA), origen_demo=True)
        self.cliente = crear_cliente_display(boveda, self.transporte, reloj)

    def test_devuelve_los_videos_demo_pedidos_y_omite_los_ajenos(self) -> None:
        listado = [v for pagina in self.cliente.listar_videos(tope=40) for v in pagina]
        elegidos = [str(listado[5]['id']), str(listado[0]['id'])]

        videos = self.cliente.consultar_videos([elegidos[0], '7000000000000000000', elegidos[1]])

        self.assertEqual([v['id'] for v in videos], elegidos)
        por_id = {str(v['id']): v for v in listado}
        for v in videos:
            self.assertEqual(v['view_count'], por_id[v['id']]['view_count'])
        self.assertEqual(self.transporte.llamadas['/v2/video/query/'], 1)

    def test_lote_invalido_que_llegara_al_transporte_demo_es_invalid_params(self) -> None:
        status, cuerpo = self.transporte.manejar(
            'POST', API + P_CONSULTA_VIDEOS + '?fields=id', {'Authorization': 'Bearer act.demo-display-acceso'},
            json.dumps({'filters': {'video_ids': [7300000000000000000]}}).encode('utf-8'))

        self.assertEqual(status, 400)
        self.assertEqual(cuerpo['error']['code'], 'invalid_params')


if __name__ == '__main__':
    unittest.main()
