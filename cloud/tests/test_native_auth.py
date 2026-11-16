"""Synthetic native enrollment, owner isolation and browser compatibility."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from cloud.app import Settings, create_app
from cloud.firebase_service import FirebaseServices
from cloud.native_auth import NativeAuth, NativeAuthError, challenge


class NativeRegistryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.clock = [1_800_000_000]
        self.owner = {'uid': 'synthetic-owner', 'email': 'owner@example.test', 'auth_time': self.clock[0] - 60}
        self.live = True
        self.service = NativeAuth(str(Path(self.folder.name) / 'native.sqlite'), 'synthetic-key-' * 4,
                                  'https://corte.example', lambda *_: self.owner if self.live else None,
                                  lambda: self.clock[0])
        self.verifier = 'A' * 64

    def tearDown(self):
        self.folder.cleanup()

    def start(self):
        return self.service.start({'platform': 'android', 'name': 'Mi dispositivo sintético',
                                   'code_challenge': challenge(self.verifier)})

    def approve(self, request):
        self.service.decide({'user_code': request['user_code']}, self.owner, True)

    def poll(self, request):
        return self.service.poll({'request_id': request['request_id'], 'code_verifier': self.verifier})

    def test_pkce_pending_delivery_once_hash_only_and_persistence(self):
        request = self.start()
        self.assertEqual(request['expires_in'], 600)
        self.assertEqual(request['interval'], 3)
        self.assertTrue(request['verification_uri'].startswith('https://corte.example/conectar-dispositivo?codigo='))
        self.assertEqual(self.poll(request), ({'estado': 'pendiente'}, 202))
        with self.assertRaises(NativeAuthError) as caught:
            self.poll(request)
        self.assertEqual(caught.exception.status, 429)
        self.approve(request)
        result, status = self.poll(request)
        self.assertEqual(status, 200)
        self.assertEqual(result['owner']['uid'], self.owner['uid'])
        self.assertEqual(result['expires_at'], self.clock[0] + 30 * 86400)
        self.assertIsNotNone(self.service.authenticate(result['token']))
        raw = Path(self.service.path).read_bytes()
        for secret in [result['token'], request['request_id'], request['user_code'], self.verifier]:
            self.assertNotIn(secret.encode(), raw)
        with self.assertRaises(NativeAuthError) as caught:
            self.poll(request)
        self.assertEqual(caught.exception.code, 'autorizacion_entregada')
        restarted = NativeAuth(self.service.path, 'synthetic-key-' * 4, self.service.public_url,
                               lambda *_: self.owner, lambda: self.clock[0])
        self.assertEqual(restarted.authenticate(result['token'])['device_id'], result['device_id'])
        self.assertNotIn('token_hash', restarted.devices(self.owner['uid'])[0])

    def test_invalid_proof_never_consumes_request_and_expiry_denial(self):
        request = self.start()
        self.approve(request)
        for verifier in ['x' * 42, 'x' * 129, '\n' + 'x' * 63, 'B' * 64]:
            with self.assertRaises(NativeAuthError):
                self.service.poll({'request_id': request['request_id'], 'code_verifier': verifier})
        result, _ = self.poll(request)
        self.assertIsNotNone(self.service.authenticate(result['token']))
        denied = self.start()
        self.service.decide({'user_code': denied['user_code']}, self.owner, False)
        with self.assertRaises(NativeAuthError) as caught:
            self.poll(denied)
        self.assertEqual(caught.exception.code, 'solicitud_denegada')
        expired = self.start()
        self.clock[0] += 601
        with self.assertRaises(NativeAuthError) as caught:
            self.poll(expired)
        self.assertEqual(caught.exception.status, 410)

    def test_concurrent_delivery_has_exactly_one_token(self):
        request = self.start()
        self.approve(request)
        def exchange(_):
            try:
                return self.poll(request)[1]
            except NativeAuthError as exc:
                return exc.status
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(exchange, range(8)))
        self.assertEqual(results.count(200), 1)
        self.assertEqual(results.count(409), 7)
        self.assertEqual(len(self.service.devices(self.owner['uid'])), 1)

    def test_device_ownership_revocation_disabled_owner_and_expiry(self):
        request = self.start()
        self.approve(request)
        grant, _ = self.poll(request)
        self.assertFalse(self.service.revoke('other-owner', grant['device_id']))
        self.assertIsNotNone(self.service.authenticate(grant['token']))
        self.live = False
        self.assertIsNone(self.service.authenticate(grant['token']))
        self.live = True
        self.assertTrue(self.service.revoke(self.owner['uid'], grant['device_id']))
        self.assertIsNone(self.service.authenticate(grant['token']))
        second = self.start()
        self.approve(second)
        grant, _ = self.poll(second)
        self.clock[0] += 30 * 86400 + 1
        self.assertIsNone(self.service.authenticate(grant['token']))

    def test_validation_caps_and_keyed_rate_limit(self):
        for changed in [{'platform': 'web'}, {'name': '\nunsafe'}, {'name': ''}, {'name': 'x' * 81},
                        {'code_challenge': 'not-sha256'}, {'extra': 'ignored'}]:
            with self.assertRaises(NativeAuthError):
                self.service.start({'platform': 'windows', 'name': 'PC', 'code_challenge': challenge(self.verifier), **changed})
        for _ in range(10):
            self.service.limit('start', '198.51.100.2')
        with self.assertRaises(NativeAuthError) as caught:
            self.service.limit('start', '198.51.100.2')
        self.assertEqual(caught.exception.status, 429)
        self.assertTrue(all('198.51.100.2' not in key for key in self.service._attempts))

    def test_callback_grants_are_bound_to_device_path_and_live_owner(self):
        request = self.start()
        self.approve(request)
        grant, _ = self.poll(request)
        state = 'synthetic-state-' + 'A' * 32
        self.service.register_callback(state, '/oauth/shop', grant['device_id'])
        self.assertEqual(self.service.callback_owner(state, '/oauth/shop'), self.owner)
        self.assertIsNone(self.service.callback_owner(state, '/oauth/tiktok'))
        self.assertIsNone(self.service.callback_owner('unknown-state-' + 'B' * 32, '/oauth/shop'))
        self.service.revoke(self.owner['uid'], grant['device_id'])
        self.assertIsNone(self.service.callback_owner(state, '/oauth/shop'))

    def test_approval_is_single_decision_and_revocation_during_identity_check_wins(self):
        request = self.start()
        self.approve(request)
        with self.assertRaises(NativeAuthError) as caught:
            self.service.decide({'user_code': request['user_code']}, self.owner, False)
        self.assertEqual(caught.exception.status, 409)
        grant, _ = self.poll(request)
        def revoke_while_validating(*_):
            self.service.revoke(self.owner['uid'], grant['device_id'])
            return self.owner
        self.service._owner = revoke_while_validating
        self.assertIsNone(self.service.authenticate(grant['token']))


class NativeWebTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.base = 'https://corte.example'
        self.headers = {'Origin': self.base, 'X-CH-Hub': '1'}
        self.claims = {'uid': 'synthetic-owner', 'sub': 'synthetic-owner', 'email': 'owner@example.test',
                       'email_verified': True, 'auth_time': int(time.time()) - 60,
                       'firebase': {'sign_in_provider': 'google.com'}}
        self.firebase = object.__new__(FirebaseServices)
        self.firebase.owner_uid = self.claims['uid']
        self.firebase.owner_email = self.claims['email']
        self.firebase.app = Mock()
        self.firebase.auth = Mock()
        self.user = SimpleNamespace(disabled=False, email_verified=True, email=self.claims['email'],
                                    tokens_valid_after_timestamp=0, provider_data=[SimpleNamespace(provider_id='google.com')])
        self.firebase.auth.get_user.return_value = self.user
        self.firebase.verify_session = lambda cookie: dict(self.claims) if cookie == 'synthetic-owner-cookie' else None
        self.firebase.web_config = {'authDomain': 'corte-test.firebaseapp.com'}
        self.hub = Mock()
        self.hub._candado_mutacion = threading.RLock()
        self.hub.despachador.despachar.return_value = SimpleNamespace(status=200, cuerpo=b'{"ok":true}', archivo=None, cabeceras=[])
        settings = Settings(self.base, 'synthetic-session-key-' * 4, '', self.folder.name, self.folder.name,
                            auth_provider='firebase')
        self.app = create_app(settings, self.hub, self.firebase)
        self.client = self.app.test_client()
        self.owner = self.app.test_client()
        self.owner.set_cookie('__session', 'synthetic-owner-cookie', domain='corte.example', secure=True)
        self.verifier = 'A' * 64

    def tearDown(self):
        self.folder.cleanup()

    def start(self):
        return self.client.post('/api/native/auth/start', json={'platform': 'windows', 'name': 'PC sintética',
                                'code_challenge': challenge(self.verifier)}, headers=self.headers, base_url=self.base).json

    def grant(self):
        request = self.start()
        approved = self.owner.post('/api/native/auth/approve', json={'user_code': request['user_code']},
                                   headers=self.headers, base_url=self.base)
        self.assertEqual(approved.status_code, 200)
        result = self.client.post('/api/native/auth/poll', json={'request_id': request['request_id'],
                                  'code_verifier': self.verifier}, headers=self.headers, base_url=self.base)
        self.assertEqual(result.status_code, 200)
        return result.json

    def test_browser_csrf_owner_gate_and_native_cannot_approve_or_admin_sessions(self):
        self.assertEqual(self.client.post('/api/native/auth/start', json={}, base_url=self.base).status_code, 403)
        request = self.start()
        path = '/api/native/auth/request?codigo=' + request['user_code']
        self.assertEqual(self.client.get(path, base_url=self.base).status_code, 401)
        self.assertEqual(self.owner.get(path, base_url=self.base).json['name'], 'PC sintética')
        self.assertEqual(self.owner.post('/api/native/auth/approve', json={'user_code': request['user_code']},
                                         base_url=self.base).status_code, 403)
        grant = self.grant()
        headers = {**self.headers, 'Authorization': 'Bearer ' + grant['token']}
        for path in ['/api/native/auth/approve', '/api/native/auth/deny', '/api/cloud/login', '/api/cloud/logout']:
            self.assertEqual(self.client.post(path, json={}, headers=headers, base_url=self.base).status_code, 403)
        for path in ['/api/native/devices', '/api/cloud/session', '/api/cloud/config']:
            self.assertEqual(self.client.get(path, headers=headers, base_url=self.base).status_code, 403)
        self.assertTrue(self.owner.get('/api/cloud/session', base_url=self.base).json['authenticated'])
        self.assertFalse(self.client.get('/api/cloud/session', base_url=self.base).json['authenticated'])

    def test_bearer_business_images_and_owner_revoke(self):
        grant = self.grant()
        headers = {**self.headers, 'Authorization': 'Bearer ' + grant['token']}
        for path in ['/api/session', '/api/snapshot', '/img/p/123']:
            self.assertEqual(self.client.get(path, headers=headers, base_url=self.base).status_code, 200)
            self.assertNotIn('Authorization', self.hub.despachador.despachar.call_args.args[3])
        session = self.client.get('/api/native/session', headers=headers, base_url=self.base)
        self.assertEqual(session.json['owner']['uid'], self.claims['uid'])
        self.assertNotIn('token', session.json)
        devices = self.owner.get('/api/native/devices', base_url=self.base).json['devices']
        self.assertEqual(devices[0]['device_id'], grant['device_id'])
        revoked = self.owner.post('/api/native/devices/' + grant['device_id'] + '/revoke', json={},
                                  headers=self.headers, base_url=self.base)
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(self.client.get('/api/snapshot', headers=headers, base_url=self.base).status_code, 401)

    def test_native_mutation_csrf_wrong_owner_and_private_identity(self):
        grant = self.grant()
        bearer = {'Authorization': 'Bearer ' + grant['token']}
        self.hub.boveda.leer.return_value = {'open_id': 'synthetic-creator-id', 'access_token': 'never-echo-this'}
        self.hub.auth.cuenta.return_value = {'username': 'synthetic-name'}
        native = self.client.get('/api/native/session', headers=bearer, base_url=self.base)
        self.assertEqual(native.json['tiktok_open_id'], 'synthetic-creator-id')
        self.assertEqual(native.json['username'], 'synthetic-name')
        self.assertNotIn('never-echo-this', native.text)
        self.assertEqual(self.owner.get('/api/native/session', base_url=self.base).status_code, 401)
        self.hub.despachador.despachar.reset_mock()
        for extra in [{}, {'Origin': 'https://evil.example', 'X-CH-Hub': '1'}, {'Origin': self.base}]:
            result = self.client.post('/api/local/ops', json={'ops': []}, headers={**bearer, **extra}, base_url=self.base)
            self.assertEqual(result.status_code, 403)
        self.hub.despachador.despachar.assert_not_called()
        denied = self.client.post('/api/native/devices/' + grant['device_id'] + '/revoke', json={},
                                  headers={**self.headers, **bearer}, base_url=self.base)
        self.assertEqual(denied.status_code, 403)

    def test_self_revoke_and_live_firebase_owner_checks(self):
        grant = self.grant()
        headers = {**self.headers, 'Authorization': 'Bearer ' + grant['token']}
        for field, value in [('disabled', True), ('email_verified', False), ('email', 'other@example.test'),
                             ('tokens_valid_after_timestamp', int(time.time() * 1000)), ('provider_data', [])]:
            old = getattr(self.user, field)
            setattr(self.user, field, value)
            self.assertEqual(self.client.get('/api/native/session', headers=headers, base_url=self.base).status_code, 401)
            setattr(self.user, field, old)
        self.firebase.owner_uid = 'another-owner'
        self.assertEqual(self.client.get('/api/native/session', headers=headers, base_url=self.base).status_code, 401)

    def test_provider_outage_preserves_device_and_has_no_false_revocation(self):
        grant = self.grant()
        headers = {**self.headers, 'Authorization': 'Bearer ' + grant['token']}
        self.firebase.auth.get_user.side_effect = TimeoutError('synthetic-upstream-with-no-user-data')
        result = self.client.get('/api/native/session', headers=headers, base_url=self.base)
        self.assertEqual(result.status_code, 503)
        self.assertNotIn('synthetic-upstream', result.text)
        self.firebase.auth.get_user.side_effect = None
        self.assertEqual(self.client.get('/api/native/session', headers=headers, base_url=self.base).status_code, 200)
        self.firebase.owner_uid = self.claims['uid']
        self.assertEqual(self.client.post('/api/native/devices/self/revoke', json={}, headers=headers,
                                          base_url=self.base).status_code, 200)
        self.assertEqual(self.client.get('/api/native/session', headers=headers, base_url=self.base).status_code, 401)

    def test_unknown_callback_stays_private_registered_native_state_reaches_existing_handler(self):
        self.assertEqual(self.client.get('/oauth/shop?code=synthetic&state=unknown', base_url=self.base).status_code, 401)
        grant = self.grant()
        state = 'synthetic-native-state-' + 'A' * 32
        self.hub.despachador.despachar.return_value.cuerpo = json.dumps({'url': 'https://shop.tiktok.com/auth?state=' + state}).encode()
        headers = {**self.headers, 'Authorization': 'Bearer ' + grant['token']}
        result = self.client.post('/api/auth/link', json={'abrir_navegador': False}, headers=headers, base_url=self.base)
        self.assertEqual(result.status_code, 200)
        self.hub.auth.canjear.return_value = {'ok': True}
        callback = self.client.get('/oauth/shop?code=synthetic&state=' + state, base_url=self.base)
        self.assertEqual(callback.status_code, 303)
        self.hub.auth.canjear.assert_called_once()
        self.assertEqual(self.client.get('/api/session', base_url=self.base).status_code, 401)

    def test_gateway_forwards_only_well_formed_native_bearer(self):
        from cloud.gateway import GatewaySettings, create_app as gateway_app
        from cloud.tests.test_gateway import upstream
        transport = Mock()
        transport.request.return_value = upstream()
        gateway = gateway_app(GatewaySettings('http://10.73.0.10:8080', self.base), transport).test_client()
        valid = 'Bearer corte_native_v1_' + 'A' * 43
        for authorization, forwarded in [(valid, True), ('Bearer random-google-token', False),
                                          ('Basic secret', False), (valid + ' extra', False),
                                          ('Bearer corte_native_v1_' + 'A' * 42, False)]:
            gateway.get('/api/session', headers={'Authorization': authorization}, base_url=self.base)
            sent = transport.request.call_args.kwargs['headers']
            self.assertEqual('Authorization' in sent, forwarded)
            if forwarded:
                self.assertEqual(sent['Authorization'], valid)

    def test_native_import_requires_creator_bound_to_live_connected_account(self):
        grant = self.grant()
        headers = {**self.headers, 'Authorization': 'Bearer ' + grant['token']}
        expected = 'synthetic-creator-before'
        self.hub.boveda.leer.return_value = {'open_id': expected}
        self.hub.auth.conexion.return_value = {'estado': 'conectada'}
        payload = {'formato': 'corte-local', 'version': 1, 'planes': []}
        for value in [None, '', ' ', 'x' * 257, 'invalid\tvalue', 'non-ascii-\u00e1']:
            extra = {'X-Corte-Expected-Creator': value} if value is not None else {}
            result = self.client.post('/api/cloud/import', json=payload, headers={**headers, **extra}, base_url=self.base)
            self.assertEqual(result.status_code, 409)
            self.assertEqual(result.json['error']['codigo'], 'cuenta_cambio_sin_importar')
        bound = {**headers, 'X-Corte-Expected-Creator': expected}
        for stored, connection in [({'open_id': 'synthetic-creator-after'}, {'estado': 'conectada'}),
                                   ({}, {'estado': 'conectada'}),
                                   ({'open_id': expected}, {'estado': 'sin_autorizar'}),
                                   ({'open_id': expected}, {'estado': 'reautorizar'})]:
            self.hub.boveda.leer.return_value = stored
            self.hub.auth.conexion.return_value = connection
            result = self.client.post('/api/cloud/import', json=payload, headers=bound, base_url=self.base)
            self.assertEqual(result.status_code, 409)
            self.assertNotIn(expected, result.text)
            self.assertNotIn('synthetic-creator-after', result.text)
        self.hub.local.importar.assert_not_called()

    def test_matching_import_holds_coordinator_rlock_and_browser_contract_is_preserved(self):
        grant = self.grant()
        expected = 'synthetic-matching-creator'
        self.hub.boveda.leer.return_value = {'open_id': expected}
        self.hub.auth.conexion.return_value = {'estado': 'conectada'}
        payload = {'formato': 'corte-local', 'version': 1, 'notas': []}
        def import_under_lock(data):
            self.assertTrue(self.hub._candado_mutacion._is_owned())
            # The actual coordinator is reentrant; import never takes or keeps
            # the vault lock while acquiring the SQLite writer.
            with self.hub._candado_mutacion:
                self.assertEqual(data, payload)
            return {'importados': {'notas': 0}, 'omitidos': 0}
        self.hub.local.importar.side_effect = import_under_lock
        result = self.client.post('/api/cloud/import', json=payload, base_url=self.base,
                                  headers={**self.headers, 'Authorization': 'Bearer ' + grant['token'],
                                           'X-Corte-Expected-Creator': expected})
        self.assertEqual(result.status_code, 200)
        self.hub.local.importar.side_effect = None
        self.hub.local.importar.return_value = {'importados': {'notas': 0}, 'omitidos': 0}
        self.hub.local.importar.reset_mock()
        browser = self.owner.post('/api/cloud/import', json=payload, base_url=self.base, headers=self.headers)
        self.assertEqual(browser.status_code, 200)
        self.hub.local.importar.assert_called_once_with(payload)

    def test_creator_changed_while_native_import_waited_for_mutex_is_not_imported(self):
        grant = self.grant()
        before, after = 'synthetic-before-race', 'synthetic-after-race'
        self.hub.boveda.leer.return_value = {'open_id': before}
        self.hub.auth.conexion.return_value = {'estado': 'conectada'}
        waiting = threading.Event()
        class SignaledLock:
            def __init__(self): self.inner = threading.RLock()
            def __enter__(self): waiting.set(); self.inner.acquire(); return self
            def __exit__(self, *_): self.inner.release()
        lock = SignaledLock()
        self.hub._candado_mutacion = lock
        def import_in_other_thread():
            return self.app.test_client().post('/api/cloud/import', json={'formato': 'corte-local', 'version': 1},
                                               base_url=self.base, headers={**self.headers,
                                               'Authorization': 'Bearer ' + grant['token'],
                                               'X-Corte-Expected-Creator': before})
        with ThreadPoolExecutor(max_workers=1) as pool:
            lock.inner.acquire()
            try:
                future = pool.submit(import_in_other_thread)
                self.assertTrue(waiting.wait(5), 'request did not reach coordinator lock')
                self.hub.boveda.leer.return_value = {'open_id': after}
            finally:
                lock.inner.release()
            result = future.result(timeout=5)
        self.assertEqual(result.status_code, 409)
        self.hub.local.importar.assert_not_called()

    def test_gateway_creator_binding_header_requires_well_formed_native_bearer(self):
        from cloud.gateway import GatewaySettings, create_app as gateway_app
        from cloud.tests.test_gateway import upstream
        transport = Mock()
        transport.request.return_value = upstream()
        gateway = gateway_app(GatewaySettings('http://10.73.0.10:8080', self.base), transport).test_client()
        valid = 'Bearer corte_native_v1_' + 'A' * 43
        for authorization, forwarded in [(valid, True), ('Bearer arbitrary', False), ('', False)]:
            gateway.post('/api/cloud/import', json={}, base_url=self.base,
                         headers={'Authorization': authorization, 'X-Corte-Expected-Creator': 'synthetic-creator'})
            sent = transport.request.call_args.kwargs['headers']
            self.assertEqual('X-Corte-Expected-Creator' in sent, forwarded)
            if forwarded:
                self.assertEqual(sent['X-Corte-Expected-Creator'], 'synthetic-creator')


if __name__ == '__main__':
    unittest.main()
