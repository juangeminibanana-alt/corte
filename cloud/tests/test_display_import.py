"""Real portable vault and provider-client behavior with synthetic credentials."""
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
from cloud.app import Settings, create_app
from creatorhub.errores import ErrorRed
from creatorhub.hub import iniciar_hub
from creatorhub.interfaces import OpcionesHub
from creatorhub.tiktok_dev.errores import ErrorDisplay


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


if __name__ == '__main__':
    unittest.main()
