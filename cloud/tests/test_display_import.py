"""Real portable vault and provider-client behavior with synthetic credentials."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from werkzeug.security import generate_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'hub'))
from cloud.app import Settings, create_app, opaque_client_scopes
from creatorhub.errores import ErrorRed
from creatorhub.hub import iniciar_hub
from creatorhub.interfaces import OpcionesHub
from creatorhub.tiktok_dev import datos as D
from creatorhub.tiktok_dev.errores import ErrorDisplay


VIDEO = '7000000000000000001'
OTRO_VIDEO = '7000000000000000002'


class DisplayImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = generate_password_hash('synthetic-password')

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'CORTE_PUBLIC_URL': 'https://corte.example',
                                          'CORTE_ENCRYPTION_KEY': 'synthetic-master-key-' * 4})
        self.env.start()
        self.hub = iniciar_hub(OpcionesHub(modo='real', nube=True, sin_lan=True,
                                          raiz_datos=self.folder.name, sync_al_iniciar=False))
        self.hub.boveda.mutar(lambda d: d.update(app_key='synthetic-shop-key', open_id='shop-namespace-id',
                                               access_token='synthetic-shop-access', refresh_token='synthetic-shop-refresh'), True)
        self.hub.auth.cuenta = Mock(return_value={'username': 'creador_sintetico'})
        self.hub.auth.conexion = Mock(return_value={'estado': 'conectada'})
        self.hub.sincronizador.iniciar = Mock(return_value={'ya_en_curso': False})
        self.transport = Mock()
        self.transport.manejar.return_value = self.profile()
        self.hub.display.cliente.transporte = self.transport
        self.base = 'https://corte.example'
        self.headers = {'Origin': self.base, 'X-CH-Hub': '1'}
        self.app = create_app(Settings(self.base, 'synthetic-session-' * 4, self.password,
                                       self.folder.name, self.folder.name), self.hub)
        self.client = self.app.test_client()
        self.client.post('/api/cloud/login', json={'password': 'synthetic-password'}, headers=self.headers, base_url=self.base)

    def tearDown(self):
        self.hub.detener(10)
        self.env.stop()
        self.folder.cleanup()

    def payload(self):
        now = int(time.time())
        return {'client_key': 'SyntheticDisplayKey2026', 'client_secret': 'SyntheticDisplaySecret2026',
                'access_token': 'act.synthetic-access-display', 'refresh_token': 'rft.synthetic-refresh-display',
                'access_expira_at': now + 86400, 'refresh_expira_at': now + 30 * 86400,
                'open_id': 'display-namespace-id',
                'scopes': ['user.info.basic', 'user.info.profile', 'user.info.stats', 'video.list'],
                'conectada_at': now - 60, 'origen': 'importado'}

    def profile(self, name='creador_sintetico'):
        return 200, {'data': {'user': {'open_id': 'display-namespace-id', 'username': name,
                                      'display_name': 'Creador sintético', 'video_count': 2}}, 'error': {'code': 'ok'}}

    def send(self, data=None):
        return self.client.post('/api/cloud/display/import', json=self.payload() if data is None else data,
                                headers=self.headers, base_url=self.base)

    def test_verified_same_creator_is_saved_encrypted_without_cross_namespace_oid_comparison(self):
        payload = self.payload()
        result = self.send(payload)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json['ok'])
        self.assertTrue(result.json['sync_iniciada'])
        self.assertEqual(result.json['display']['usuario']['username'], 'creador_sintetico')
        self.assertEqual(self.hub.display.boveda.leer()['open_id'], 'display-namespace-id')
        raw = Path(self.hub.display.boveda.ruta).read_bytes()
        for field in ('client_key', 'client_secret', 'access_token', 'refresh_token', 'open_id'):
            self.assertNotIn(payload[field], result.text)
            self.assertNotIn(payload[field].encode(), raw)
        self.hub.sincronizador.iniciar.assert_called_once_with('incremental', 'usuario')

    def test_wrong_or_missing_profile_is_rejected_before_persisting_any_token(self):
        before = self.hub.display.boveda.leer()
        for response in [self.profile('otra_cuenta_sintetica'), (200, {'data': {'user': {}}, 'error': {'code': 'ok'}})]:
            self.transport.manejar.return_value = response
            result = self.send()
            self.assertEqual(result.status_code, 409)
            self.assertEqual(self.hub.display.boveda.leer(), before)
            self.assertFalse(Path(self.hub.display.boveda.ruta).exists())
        self.hub.sincronizador.iniciar.assert_not_called()

    def test_existing_destination_authorization_is_not_overwritten(self):
        self.hub.display.boveda.mutar(lambda d: d.update(client_key='ExistingSyntheticKey',
                                                       access_token='existing-synthetic-access'), True)
        before = self.hub.display.boveda.leer()
        self.assertEqual(self.send().status_code, 409)
        self.assertEqual(self.hub.display.boveda.leer(), before)
        self.transport.manejar.assert_not_called()

    def test_validation_csrf_and_owner_protection_never_call_provider(self):
        before = self.hub.display.boveda.leer()
        payload = self.payload()
        for changed in [{'access_token': 'unsafe\nvalue'}, {'refresh_expira_at': int(time.time()) - 1},
                        {'access_expira_at': True}, {'scopes': ['video.list']}, {'origen': 'demo'},
                        {'server_path': '/private/file'}]:
            result = self.send({**payload, **changed})
            self.assertEqual(result.status_code, 422)
            self.assertEqual(self.hub.display.boveda.leer(), before)
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.post('/api/cloud/display/import', json=payload,
                                        headers=self.headers, base_url=self.base).status_code, 401)
        self.assertEqual(self.client.post('/api/cloud/display/import', json=payload, base_url=self.base).status_code, 403)
        self.transport.manejar.assert_not_called()

    def test_revoked_access_refreshes_once_then_verifies_rotated_identity_before_encryption(self):
        now = int(time.time())
        self.transport.manejar.side_effect = [
            (401, {'error': {'code': 'access_token_invalid'}}),
            (200, {'access_token': 'act.synthetic-rotated-access', 'refresh_token': 'rft.synthetic-rotated-refresh',
                   'expires_in': 86400, 'refresh_expires_in': 30 * 86400, 'open_id': 'display-namespace-id',
                   'scope': ','.join(self.payload()['scopes'])}), self.profile(),
        ]
        result = self.send()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.transport.manejar.call_count, 3)
        current = self.hub.display.boveda.leer()
        self.assertEqual(current['refresh_token'], 'rft.synthetic-rotated-refresh')
        self.assertGreater(current['access_expira_at'], now)
        self.assertNotIn('synthetic-rotated', result.text)

    def test_provider_failure_and_concurrent_account_or_destination_change_do_not_overwrite(self):
        before = self.hub.display.boveda.leer()
        self.transport.manejar.side_effect = ErrorRed('synthetic-network')
        self.assertEqual(self.send().status_code, 503)
        self.assertEqual(self.hub.display.boveda.leer(), before)
        def change_destination(*_):
            self.hub.display.boveda.mutar(lambda d: d.update(client_key='NewSyntheticKey',
                                                           client_secret='NewSyntheticSecret'), True)
            return self.profile()
        self.transport.manejar.side_effect = change_destination
        self.assertEqual(self.send().status_code, 409)
        self.assertEqual(self.hub.display.boveda.leer()['client_key'], 'NewSyntheticKey')
        self.assertNotIn('access_token', self.hub.display.boveda.leer())
        self.hub.sincronizador.iniciar.assert_not_called()

    def test_shop_changed_during_provider_verification_cannot_receive_display_import(self):
        def change_shop(*_):
            self.hub.boveda.mutar(lambda d: d.update(open_id='other-shop-namespace'), True)
            return self.profile()
        self.transport.manejar.side_effect = change_shop
        result = self.send()
        self.assertEqual(result.status_code, 409)
        self.assertNotIn('access_token', self.hub.display.boveda.leer())
        self.hub.sincronizador.iniciar.assert_not_called()

    def test_old_oauth_callback_cannot_overwrite_newer_import_or_app_change(self):
        service = self.hub.display
        service.boveda.mutar(lambda d: d.update(client_key=self.payload()['client_key'],
                                               client_secret=self.payload()['client_secret']), True)
        intent = service.iniciar_conexion(False)
        state = parse_qs(urlsplit(intent['url']).query)['state'][0]
        def stale_exchange(*_):
            service.boveda.mutar(lambda d: d.update(client_key='NewerSyntheticKey',
                                                   access_token='newer-synthetic-token'), True)
            return {'access_token': 'stale-synthetic-token', 'refresh_token': 'stale-refresh',
                    'open_id': 'display-namespace-id'}
        service.cliente.canjear = Mock(side_effect=stale_exchange)
        status, body = service.callback('state=' + state + '&code=synthetic-code')
        self.assertEqual(status, 409)
        self.assertNotIn(b'stale-synthetic-token', body)
        self.assertEqual(service.boveda.leer()['access_token'], 'newer-synthetic-token')
        self.hub.sincronizador.iniciar.assert_not_called()

    def test_second_provider_rejection_after_one_refresh_never_persists(self):
        rejected = (401, {'error': {'code': 'access_token_invalid'}})
        self.transport.manejar.side_effect = [rejected,
            (200, {'access_token': 'act.synthetic-rotated-access', 'refresh_token': 'rft.synthetic-rotated-refresh',
                   'expires_in': 86400, 'refresh_expires_in': 30 * 86400, 'open_id': 'display-namespace-id',
                   'scope': ','.join(self.payload()['scopes'])}), rejected]
        result = self.send()
        self.assertEqual(result.status_code, 422)
        self.assertEqual(self.transport.manejar.call_count, 3)
        self.assertNotIn('access_token', self.hub.display.boveda.leer())
        self.hub.sincronizador.iniciar.assert_not_called()

    def test_old_oauth_failure_does_not_mark_a_newer_connection_as_failed(self):
        service = self.hub.display
        service.boveda.mutar(lambda d: d.update(client_key=self.payload()['client_key'],
                                               client_secret=self.payload()['client_secret']), True)
        state = parse_qs(urlsplit(service.iniciar_conexion(False)['url']).query)['state'][0]
        def stale_failure(*_):
            service.boveda.mutar(lambda d: d.update(client_key='NewerSyntheticKey',
                                                   access_token='newer-synthetic-token', ultimo_error=None), True)
            raise ErrorDisplay('reautorizar')
        service.cliente.canjear = Mock(side_effect=stale_failure)
        self.assertEqual(service.callback('state=' + state + '&code=synthetic')[0], 409)
        self.assertIsNone(service.boveda.leer()['ultimo_error'])

    def preparar_actualizacion(self):
        self.assertEqual(self.send().status_code, 200)
        self.publicado_at = int(self.hub.reloj.ahora()) - 600
        with self.hub.almacen.escritor() as db:
            db.execute('INSERT INTO cuenta(id, creator_open_id, username, actualizado_at) VALUES (1, ?, ?, ?)',
                       ('shop-namespace-id', 'creador_sintetico', self.publicado_at))
            D.guardar_videos(db, [D.normalizar_video({'id': vid, 'view_count': 100, 'like_count': 7,
                                                      'cover_image_url': 'https://img.example/portada'})
                                 for vid in (VIDEO, OTRO_VIDEO)], self.publicado_at)
            db.execute('INSERT INTO sync_cursores (clave, valor, actualizado_at) VALUES (?, ?, ?)',
                       (D.CLAVE_ULTIMA_SYNC, json.dumps({'at': self.publicado_at, 'visto_tope': self.publicado_at}),
                        self.publicado_at))
        self.transport.manejar.reset_mock()

    @staticmethod
    def respuesta_video(*videos):
        return 200, {'data': {'videos': list(videos)}, 'error': {'code': 'ok'}}

    def actualizar_video(self, vid=VIDEO, **kwargs):
        return self.client.post(f'/api/catalogo/videos/{vid}/actualizar',
                                headers=self.headers, base_url=self.base, **kwargs)

    def cifras_video(self, vid):
        with self.hub.almacen.lector() as db:
            return tuple(D.leer_metricas_video(db, vid))

    def test_actualiza_contadores_y_foto_diaria_sin_cambiar_publicacion_ni_otra_ficha(self):
        self.preparar_actualizacion()
        self.assertTrue(self.client.get('/api/session', base_url=self.base).json['capacidades']['display_video_actualizar'])
        otro_antes = self.cifras_video(OTRO_VIDEO)
        data_version = self.hub.almacen.versiones()[0]
        self.transport.manejar.return_value = self.respuesta_video(
            {'id': VIDEO, 'view_count': 271, 'comment_count': 3},
            {'id': OTRO_VIDEO, 'view_count': 999})

        response = self.actualizar_video(json={})
        self.assertEqual((response.status_code, response.json), (200, {'actualizado': True}))
        method, url, _, body = self.transport.manejar.call_args.args
        self.assertEqual((method, urlsplit(url).path), ('POST', '/v2/video/query/'))
        self.assertEqual(json.loads(body), {'filters': {'video_ids': [VIDEO]}})
        self.assertEqual(self.cifras_video(OTRO_VIDEO), otro_antes)
        self.assertEqual(self.cifras_video(VIDEO)[:5], (271, 7, 3, None, self.publicado_at))
        self.assertEqual(self.hub.almacen.versiones()[0], data_version + 1)
        with self.hub.almacen.lector() as db:
            fila = db.execute('SELECT portada_url FROM videos_tiktok WHERE video_id=?', (VIDEO,)).fetchone()
            self.assertEqual(fila['portada_url'], 'https://img.example/portada')
            dia = db.execute('SELECT vistas, likes FROM videos_tiktok_dias WHERE video_id=? ORDER BY fecha DESC LIMIT 1',
                             (VIDEO,)).fetchone()
            self.assertEqual(tuple(dia), (271, 7))
        ficha = self.client.get(f'/api/catalogo/videos/{VIDEO}', base_url=self.base)
        self.assertEqual(ficha.status_code, 200, ficha.json)
        detalle = ficha.json
        self.assertEqual(detalle['video']['publicacion'], 'publico')
        self.assertEqual(detalle['video']['vistas'], 271)
        self.assertGreater(detalle['video']['metricas_at'], self.publicado_at)

    def test_video_omitido_o_respuesta_sin_cifras_no_borra_ni_refresca_metricas(self):
        self.preparar_actualizacion()
        antes = self.cifras_video(VIDEO)
        self.transport.manejar.return_value = self.respuesta_video()
        self.assertEqual(self.actualizar_video().status_code, 404)
        self.transport.manejar.return_value = self.respuesta_video({'id': VIDEO})
        self.assertEqual(self.actualizar_video().status_code, 502)
        self.assertEqual(self.cifras_video(VIDEO), antes)

    def test_revisa_permisos_cuenta_video_y_cuerpo_antes_de_llamar_a_tiktok(self):
        self.preparar_actualizacion()
        self.assertEqual(self.actualizar_video('012').status_code, 422)
        self.assertEqual(self.actualizar_video('703').status_code, 404)
        self.assertEqual(self.actualizar_video(json={'forzar': True}).status_code, 422)
        self.hub.auth.cuenta.return_value = {'username': 'otro_creador'}
        self.assertEqual(self.actualizar_video().status_code, 409)
        self.hub.auth.cuenta.return_value = {'username': 'creador_sintetico'}
        self.hub.display.boveda.mutar(lambda d: d.update(scopes=['user.info.profile']))
        self.assertEqual(self.actualizar_video().status_code, 403)
        self.assertFalse(self.client.get('/api/session', base_url=self.base).json['capacidades']['display_video_actualizar'])
        self.transport.manejar.assert_not_called()

    def test_cambio_de_identidad_durante_consulta_descarta_resultado(self):
        self.preparar_actualizacion()
        antes = self.cifras_video(VIDEO)

        def respuesta_despues_de_cambiar(*_):
            self.hub.display.boveda.mutar(lambda d: d.update(open_id='otra-cuenta-display'), True)
            return self.respuesta_video({'id': VIDEO, 'view_count': 888})

        self.transport.manejar.side_effect = respuesta_despues_de_cambiar
        self.assertEqual(self.actualizar_video().status_code, 409)
        self.assertEqual(self.cifras_video(VIDEO), antes)

    def test_firebase_exige_scope_vigente_antes_y_despues_de_tiktok(self):
        self.preparar_actualizacion()
        firebase = Mock()
        firebase.web_config = {'authDomain': 'corte-test.firebaseapp.com'}
        claims = {'uid': 'owner-test'}
        firebase.verify_session.return_value = claims
        settings = Settings(self.base, 'synthetic-session-' * 4, '', self.folder.name, self.folder.name,
                            auth_provider='firebase')
        client = create_app(settings, self.hub, firebase).test_client()
        client.set_cookie('__session', 'synthetic-session', domain='corte.example')
        route = f'/api/catalogo/videos/{VIDEO}/actualizar'
        self.assertEqual(client.post(route, headers=self.headers, base_url=self.base).status_code, 409)
        self.transport.manejar.assert_not_called()
        scope = opaque_client_scopes(claims, 'shop-namespace-id')['cache_scope']
        self.transport.manejar.return_value = self.respuesta_video({'id': VIDEO, 'view_count': 555})
        headers = {**self.headers, 'X-Corte-Cache-Scope': scope}
        self.assertEqual(client.post(route, headers=headers, base_url=self.base).status_code, 200)
        self.assertEqual(self.cifras_video(VIDEO)[0], 555)

        def respuesta_despues_de_cambiar(*_):
            self.hub.boveda.mutar(lambda d: d.update(open_id='otra-cuenta-shop'), True)
            return self.respuesta_video({'id': VIDEO, 'view_count': 888})

        self.transport.manejar.side_effect = respuesta_despues_de_cambiar
        self.assertEqual(client.post(route, headers=headers, base_url=self.base).status_code, 409)
        self.assertEqual(self.cifras_video(VIDEO)[0], 555)


if __name__ == '__main__':
    unittest.main()
