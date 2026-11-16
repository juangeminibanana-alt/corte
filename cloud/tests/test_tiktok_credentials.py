"""Credenciales de Partner Center sintéticas; ninguna petición real a TikTok."""
from __future__ import annotations

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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'hub'))

from cloud.app import Settings, create_app
from creatorhub.boveda import APP_KEY_PUBLICA
from creatorhub.errores import ErrorApi, ErrorDominio
from creatorhub.hub import iniciar_hub
from creatorhub.interfaces import OpcionesHub
from creatorhub.nube import BovedaNube
from creatorhub.tiktok.firma import generar_firma


class TikTokCredentialsTests(unittest.TestCase):
    KEY = 'synthetic-app-key-2026'
    SECRET = 'SyntheticSecretForTests123456'
    ROTATED = 'RotatedSyntheticSecret123456'

    @classmethod
    def setUpClass(cls) -> None:
        cls.password_hash = generate_password_hash('synthetic-test-password')

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'CORTE_PUBLIC_URL': 'https://corte.example',
                                          'CORTE_ENCRYPTION_KEY': 'synthetic-master-' * 4})
        self.env.start()
        self.hub = iniciar_hub(OpcionesHub(modo='real', nube=True, sin_lan=True,
                                          raiz_datos=self.folder.name, sync_al_iniciar=False))
        # Fail immediately on an accidental external request in these tests.
        self.transport = Mock()
        self.transport.manejar.side_effect = AssertionError('No network is allowed in credential tests')
        self.hub.cliente.transporte = self.transport
        self.base = 'https://corte.example'
        self.headers = {'Origin': self.base, 'X-CH-Hub': '1'}
        settings = Settings(self.base, 'synthetic-session-' * 4, self.password_hash,
                            self.folder.name, self.folder.name)
        self.client = create_app(settings, self.hub).test_client()
        result = self.client.post('/api/cloud/login', json={'password': 'synthetic-test-password'},
                                  base_url=self.base, headers=self.headers)
        self.assertEqual(result.status_code, 200)

    def tearDown(self) -> None:
        self.hub.detener(10)
        self.env.stop()
        self.folder.cleanup()

    def save(self, key=None, secret=None):
        return self.client.put('/api/cloud/tiktok/credentials',
                               json={'app_key': self.KEY if key is None else key,
                                     'app_secret': self.SECRET if secret is None else secret},
                               base_url=self.base, headers=self.headers)

    def authorize(self, **changes):
        data = {'access_token': 'synthetic-access-token', 'refresh_token': 'synthetic-refresh-token',
                'open_id': 'synthetic-open-id', 'access_expira_at': int(time.time()) + 86400,
                'refresh_expira_at': int(time.time()) + 86400 * 30}
        data.update(changes)
        self.hub.boveda.mutar(lambda d: d.update(data), cambia_credenciales=True)

    def legacy(self):
        return {'app_key': self.KEY, 'app_secret': self.SECRET,
                'access_token': 'synthetic-access-token-previous',
                'refresh_token': 'synthetic-refresh-token-previous',
                'access_token_expire_in': int(time.time()) + 86400,
                'refresh_token_expire_in': int(time.time()) + 86400 * 30,
                'open_id': 'synthetic-open-id', 'user_type': 1,
                'granted_scopes': ['creator.affiliate.info', 'creator.affiliate_collaboration.read']}

    def import_legacy(self, payload):
        return self.client.post('/api/cloud/tiktok/import', json=payload,
                                base_url=self.base, headers=self.headers)

    def test_custom_pair_is_encrypted_and_used_for_link_exchange_and_signed_requests(self):
        response = self.save()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['app_key'], self.KEY)
        self.assertTrue(response.json['ok'])
        self.assertTrue(response.json['app_secret_configurado'])
        self.assertNotIn(self.SECRET, response.get_data(as_text=True))
        file = Path(self.hub.boveda.ruta)
        self.assertNotIn(self.SECRET.encode(), file.read_bytes())
        self.assertNotIn(self.KEY.encode(), file.read_bytes())
        restored = BovedaNube(str(file), 'synthetic-master-' * 4, 'shop').leer()
        self.assertEqual((restored['app_key'], restored['app_secret']), (self.KEY, self.SECRET))
        link = self.hub.auth.link(False)
        self.assertEqual(parse_qs(urlsplit(link['url']).query)['app_key'], [self.KEY])

        self.transport.manejar.side_effect = None
        self.transport.manejar.return_value = (200, {'code': 0, 'data': {}})
        self.hub.cliente.canjear_codigo('synthetic-authorization-code')
        query = parse_qs(urlsplit(self.transport.manejar.call_args.args[1]).query)
        self.assertEqual(query['app_key'], [self.KEY])
        self.assertEqual(query['app_secret'], [self.SECRET])
        self.authorize()
        path = '/affiliate_creator/202508/profiles'
        self.hub.cliente.llamar('GET', path, {'app_key': 'untrusted-request-value'})
        query = {k: v[0] for k, v in parse_qs(urlsplit(self.transport.manejar.call_args.args[1]).query).items()}
        self.assertEqual(query['app_key'], self.KEY)
        signature = query.pop('sign')
        self.assertEqual(signature, generar_firma(path, query, None, self.SECRET))
        self.assertNotEqual(query['app_key'], APP_KEY_PUBLICA)

    def test_partial_invalid_and_extra_payloads_do_not_write(self):
        before = self.hub.boveda.leer()
        payloads = [{}, {'app_key': self.KEY}, {'app_secret': self.SECRET}, [], None,
                    {'app_key': self.KEY, 'app_secret': self.SECRET, 'access_token': 'injected'},
                    {'app_key': 'bad key', 'app_secret': self.SECRET},
                    {'app_key': self.KEY + '\n', 'app_secret': self.SECRET},
                    {'app_key': self.KEY, 'app_secret': 'too-short'},
                    {'app_key': self.KEY, 'app_secret': self.SECRET + '\n'},
                    {'app_key': 1234, 'app_secret': self.SECRET}]
        for payload in payloads:
            with self.subTest(payload=payload):
                response = self.client.put('/api/cloud/tiktok/credentials', data=json.dumps(payload),
                                           content_type='application/json', base_url=self.base, headers=self.headers)
                self.assertEqual(response.status_code, 422)
                self.assertNotIn(self.SECRET, response.get_data(as_text=True))
                self.assertEqual(self.hub.boveda.leer(), before)

    def test_expired_or_partial_authorization_blocks_key_change_without_mutation(self):
        self.save()
        self.authorize(access_expira_at=1, refresh_expira_at=1)
        before = self.hub.boveda.leer()
        response = self.save(key='another-synthetic-key')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json['error']['codigo'], 'app_key_en_uso')
        self.assertEqual(self.hub.boveda.leer(), before)
        self.hub.boveda.mutar(lambda d: d.pop('access_token'))
        before = self.hub.boveda.leer()
        self.assertEqual(self.save(key='another-synthetic-key').status_code, 409)
        self.assertEqual(self.hub.boveda.leer(), before)
        self.transport.manejar.assert_not_called()

    def test_disconnect_then_key_change_preserves_identity_and_saved_data(self):
        self.save()
        self.authorize()
        with self.hub.almacen.escritor() as conn:
            conn.execute("INSERT INTO preferencias(clave,valor_json,actualizado_at) VALUES ('sentinel','true',1)")
        self.hub.auth.desconectar(False)
        self.assertEqual(self.save(key='another-synthetic-key').status_code, 200)
        self.assertEqual(self.hub.boveda.leer()['open_id'], 'synthetic-open-id')
        with self.hub.almacen.lector() as conn:
            self.assertEqual(conn.execute("SELECT valor_json FROM preferencias WHERE clave='sentinel'").fetchone()[0],
                             'true')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM oauth_states').fetchone()[0], 0)
        self.assertFalse(self.hub.boveda.tiene_tokens())

    def test_same_key_rotation_verifies_and_never_echoes_secret(self):
        self.save()
        self.authorize()
        verifier = Mock(return_value='ok')
        self.hub.cliente.verificar_app_secret = verifier
        with self.assertLogs('creatorhub.auth', level='INFO') as logs:
            response = self.save(secret=self.ROTATED)
        verifier.assert_called_once_with(self.ROTATED)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.ROTATED, response.get_data(as_text=True) + ''.join(logs.output))
        self.assertEqual(self.hub.boveda.leer()['app_secret'], self.ROTATED)
        self.assertEqual(self.hub.boveda.leer()['access_token'], 'synthetic-access-token')
        before = self.hub.boveda.leer()
        for failure in ['rechazada', ErrorApi(-1, 'synthetic upstream failure', 'abortar')]:
            verifier.side_effect = failure if isinstance(failure, Exception) else None
            verifier.return_value = failure
            response = self.save(secret=self.SECRET)
            self.assertEqual(response.status_code, 503 if isinstance(failure, Exception) else 422)
            self.assertNotIn(self.SECRET, response.get_data(as_text=True))
            self.assertEqual(self.hub.boveda.leer(), before)

    def test_concurrent_new_authorization_cannot_be_overwritten_by_rotation(self):
        self.save()
        self.authorize()
        def concurrent_connection(_candidate):
            self.authorize(open_id='new-synthetic-open-id')
            return 'ok'
        self.hub.cliente.verificar_app_secret = Mock(side_effect=concurrent_connection)
        response = self.save(secret=self.ROTATED)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json['error']['codigo'], 'credenciales_cambiaron')
        self.assertEqual(self.hub.boveda.leer()['app_secret'], self.SECRET)
        self.assertEqual(self.hub.boveda.leer()['open_id'], 'new-synthetic-open-id')

    def test_persistence_failure_cannot_write_only_half_the_pair(self):
        self.save()
        before = self.hub.boveda.leer()
        envelope = Path(self.hub.boveda.ruta).read_bytes()
        with patch.object(self.hub.boveda, '_persistir', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                self.hub.auth.guardar_credenciales_app('another-synthetic-key', self.ROTATED)
        self.assertEqual(self.hub.boveda.leer(), before)
        self.assertEqual(Path(self.hub.boveda.ruta).read_bytes(), envelope)

    def test_legacy_cloud_route_is_disabled_and_pair_endpoint_requires_owner_and_csrf(self):
        legacy = self.client.put('/api/credenciales/app-secret', json={'app_secret': self.SECRET},
                                  base_url=self.base, headers=self.headers)
        self.assertEqual(legacy.status_code, 410)
        self.assertEqual(self.client.put('/api/cloud/tiktok/credentials', json={}, base_url=self.base).status_code, 403)
        outsider = self.client.application.test_client()
        self.assertEqual(outsider.put('/api/cloud/tiktok/credentials', json={},
                                     base_url=self.base, headers=self.headers).status_code, 401)

    def test_cloud_does_not_offer_inherited_app_key_or_accept_secret_without_key(self):
        self.assertEqual(self.hub.auth.credenciales_estado()['app_key'], '')
        self.hub.boveda.mutar(lambda d: d.update(app_secret=self.SECRET))
        with self.assertRaises(ErrorDominio) as context:
            self.hub.auth.link(False)
        self.assertEqual(context.exception.codigo, 'sin_credenciales')
        self.hub.auth.nube = False
        self.hub.auth.rutas_legado = [str(Path(self.folder.name, 'missing-native-legacy.json'))]
        self.assertEqual(self.hub.auth.credenciales_estado()['app_key'], APP_KEY_PUBLICA)

    def test_oauth_cannot_mix_previous_app_tokens_after_concurrent_app_change(self):
        self.save()
        link = self.hub.auth.link(False)
        payload = self.legacy()
        def change_app_during_exchange(_code):
            self.hub.auth.guardar_credenciales_app('another-synthetic-key', self.ROTATED)
            return payload
        self.hub.cliente.canjear_codigo = Mock(side_effect=change_app_during_exchange)
        with self.assertRaises(ErrorDominio) as context:
            self.hub.auth.canjear({'url_o_codigo': f"{self.base}/oauth/shop?code=synthetic-code&state={link['state']}"})
        self.assertEqual(context.exception.codigo, 'credenciales_cambiaron')
        self.assertEqual(self.hub.boveda.leer()['app_key'], 'another-synthetic-key')
        self.assertFalse(self.hub.boveda.tiene_tokens())
        self.assertNotIn('open_id', self.hub.boveda.leer())

    def test_import_checks_real_profile_saves_pair_and_tokens_without_echo_then_starts_sync(self):
        payload = {**self.legacy(), 'last_state': 'discarded-synthetic-state', 'unexpected': 'discarded-value'}
        self.transport.manejar.side_effect = None
        self.transport.manejar.return_value = (200, {'code': 0, 'data': {'username': 'synthetic_creator',
                                                                       'creator_open_id': 'synthetic-open-id'}})
        self.hub.sincronizador.iniciar = Mock(return_value={'sync_id': 1})
        with self.hub.almacen.escritor() as conn:
            conn.execute("INSERT INTO preferencias(clave,valor_json,actualizado_at) VALUES ('sentinel','true',1)")
        response = self.import_legacy(payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['ok'])
        self.assertEqual(response.json['verificacion'], 'ok')
        self.assertTrue(response.json['sync_iniciada'])
        self.assertNotIn('_revision_credenciales', response.json)
        self.hub.sincronizador.iniciar.assert_called_once_with('completa', 'usuario')
        self.transport.manejar.assert_called_once()
        signed = parse_qs(urlsplit(self.transport.manejar.call_args.args[1]).query)
        self.assertEqual(signed['app_key'], [self.KEY])
        saved = self.hub.boveda.leer()
        self.assertEqual(saved['app_secret'], self.SECRET)
        self.assertEqual(saved['access_token'], payload['access_token'])
        self.assertEqual(saved['origen'], 'importado')
        self.assertNotIn('last_state', saved)
        self.assertNotIn('unexpected', saved)
        for field in ['app_secret', 'access_token', 'refresh_token']:
            self.assertNotIn(payload[field], response.get_data(as_text=True))
            self.assertNotIn(payload[field].encode(), Path(self.hub.boveda.ruta).read_bytes())
        with self.hub.almacen.lector() as conn:
            self.assertEqual(conn.execute("SELECT valor_json FROM preferencias WHERE clave='sentinel'").fetchone()[0],
                             'true')
        before = self.hub.boveda.leer()
        repeated = self.import_legacy(payload)
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(repeated.json['error']['codigo'], 'conexion_existente')
        self.assertEqual(self.hub.boveda.leer(), before)

    def test_import_invalid_expired_or_different_account_does_not_write(self):
        before = self.hub.boveda.leer()
        for invalid in [{}, {**self.legacy(), 'app_secret': ''}, {**self.legacy(), 'user_type': 2},
                        {**self.legacy(), 'refresh_token_expire_in': 1},
                        {**self.legacy(), 'access_token': self.legacy()['access_token'] + '\n'},
                        {**self.legacy(), 'granted_scopes': []}]:
            response = self.import_legacy(invalid)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(self.hub.boveda.leer(), before)
            self.assertNotIn(self.SECRET, response.get_data(as_text=True))
        self.hub.boveda.mutar(lambda d: d.update(open_id='another-synthetic-identity'))
        before = self.hub.boveda.leer()
        response = self.import_legacy(self.legacy())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json['error']['codigo'], 'cuenta_distinta')
        self.assertEqual(self.hub.boveda.leer(), before)
        self.transport.manejar.assert_not_called()

    def test_import_network_failure_is_explicit_keeps_encrypted_config_and_does_not_start_sync(self):
        self.hub.auth._traer_perfil = Mock(return_value=None)
        self.hub.sincronizador.iniciar = Mock()
        response = self.import_legacy(self.legacy())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['ok'])
        self.assertEqual(response.json['verificacion'], 'fallo')
        self.assertFalse(response.json['sync_iniciada'])
        self.hub.sincronizador.iniciar.assert_not_called()
        self.assertTrue(self.hub.boveda.tiene_tokens())
        self.assertNotIn(self.SECRET.encode(), Path(self.hub.boveda.ruta).read_bytes())

    def test_import_limit_authentication_and_csrf(self):
        oversized = {**self.legacy(), 'padding': 'x' * (64 * 1024)}
        self.assertEqual(self.import_legacy(oversized).status_code, 413)
        self.assertEqual(self.client.post('/api/cloud/tiktok/import', json={}, base_url=self.base).status_code, 403)
        outsider = self.client.application.test_client()
        self.assertEqual(outsider.post('/api/cloud/tiktok/import', json={},
                                      base_url=self.base, headers=self.headers).status_code, 401)
        self.assertFalse(self.hub.boveda.tiene_tokens())

    def test_import_empty_success_response_is_not_a_verified_profile(self):
        self.transport.manejar.side_effect = None
        self.transport.manejar.return_value = (200, {'code': 0})
        self.hub.sincronizador.iniciar = Mock()
        response = self.import_legacy(self.legacy())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['ok'])
        self.assertEqual(response.json['verificacion'], 'fallo')
        self.assertFalse(response.json['sync_iniciada'])
        self.hub.sincronizador.iniciar.assert_not_called()
        self.assertIsNone(self.hub.auth.cuenta())

    def test_import_cannot_publish_old_profile_after_disconnect_during_verification(self):
        def disconnect_during_profile():
            self.hub.auth.desconectar(False)
            return {'username': 'old_synthetic_creator'}
        self.hub.auth._traer_perfil = Mock(side_effect=disconnect_during_profile)
        self.hub.sincronizador.iniciar = Mock()
        response = self.import_legacy(self.legacy())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json['error']['codigo'], 'credenciales_cambiaron')
        self.assertIsNone(self.hub.auth.cuenta())
        self.assertFalse(self.hub.boveda.tiene_tokens())
        self.hub.sincronizador.iniciar.assert_not_called()

    def test_import_does_not_start_sync_if_account_changes_after_verification(self):
        self.hub.auth._traer_perfil = Mock(return_value={'username': 'synthetic_creator'})
        original = self.hub.auth.importar_credenciales_nube
        def disconnect_after_verification(payload):
            result = original(payload)
            self.hub.auth.desconectar(False)
            return result
        self.hub.auth.importar_credenciales_nube = disconnect_after_verification
        self.hub.sincronizador.iniciar = Mock()
        response = self.import_legacy(self.legacy())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json['error']['codigo'], 'credenciales_cambiaron')
        self.hub.sincronizador.iniciar.assert_not_called()


if __name__ == '__main__':
    unittest.main()
