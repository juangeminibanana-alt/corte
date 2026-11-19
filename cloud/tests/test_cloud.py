"""Pruebas públicas con cuentas vacías y valores sintéticos; nunca datos reales."""
from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
import sys
import subprocess
import textwrap
import threading
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'hub'))

from cloud.app import Settings, create_app
from creatorhub.comun import epoch_de_fecha_local
from creatorhub.nube import BovedaNube, BovedaDisplayNube
from creatorhub.interfaces import OpcionesHub


class VaultTests(unittest.TestCase):
    def test_roundtrip_encryption_and_compare_and_swap(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            file = str(Path(folder) / 'vault.aesgcm')
            vault = BovedaNube(file, 'test-master-' * 6, 'shop')
            vault.mutar(lambda data: data.update(app_secret='synthetic-secret', refresh_token='synthetic-refresh'), True)
            revision = vault.generacion
            self.assertNotIn(b'synthetic-secret', Path(file).read_bytes())
            self.assertTrue(vault.guardar_si(revision, {'access_token': 'synthetic-access'}))
            self.assertFalse(vault.guardar_si(revision, {'access_token': 'stale-refresh'}))
            reread = BovedaNube(file, 'test-master-' * 6, 'shop')
            self.assertEqual(reread.leer()['access_token'], 'synthetic-access')
            self.assertEqual(reread.leer()['epoca_credenciales'], 1)

    def test_wrong_key_or_purpose_fails_without_replacing_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            file = str(Path(folder) / 'vault.aesgcm')
            vault = BovedaNube(file, 'test-master-' * 6, 'shop')
            vault.mutar(lambda data: data.update(app_secret='synthetic-secret'))
            original = Path(file).read_bytes()
            for key, purpose in [('wrong-master-' * 6, 'shop'), ('test-master-' * 6, 'display')]:
                with self.assertRaises(RuntimeError):
                    BovedaNube(file, key, purpose)
                self.assertEqual(Path(file).read_bytes(), original)

    def test_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'vault.aesgcm'
            BovedaNube(str(file), 'test-master-' * 6, 'shop').mutar(lambda data: data.update(app_secret='synthetic-secret'))
            envelope = json.loads(file.read_text())
            envelope['blob'] = ('A' if envelope['blob'][0] != 'A' else 'B') + envelope['blob'][1:]
            file.write_text(json.dumps(envelope))
            with self.assertRaises(RuntimeError):
                BovedaNube(str(file), 'test-master-' * 6, 'shop')

    def test_display_preserves_display_specific_methods(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            vault = BovedaDisplayNube(str(Path(folder) / 'display'), 'test-master-' * 6, 'display')
            vault.mutar(lambda data: data.update(client_key='synthetic-key', client_secret='synthetic-secret'))
            self.assertTrue(vault.configurada())
            self.assertFalse(vault.conectada())
            self.assertTrue(vault.tiene_app_secret())


class WebSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.password_hash = generate_password_hash('synthetic-password-for-tests')

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        Path(self.folder.name, 'index.html').write_text('<html lang="es"><title>Corte</title></html>')
        self.hub = Mock()
        self.hub.salud.return_value = {'db_ok': True}
        self.hub.reloj.ahora.return_value = epoch_de_fecha_local('2026-11-18')
        self.settings = Settings('https://corte.example', 'test-session-secret-' * 4, self.password_hash,
                                 self.folder.name, self.folder.name)
        self.app = create_app(self.settings, self.hub)
        self.client = self.app.test_client()
        self.base = 'https://corte.example'
        self.headers = {'Origin': self.base, 'X-CH-Hub': '1'}

    def tearDown(self) -> None:
        self.folder.cleanup()

    def login(self):
        return self.client.post('/api/cloud/login', json={'password': 'synthetic-password-for-tests'},
                                headers=self.headers, base_url=self.base)

    def test_public_gate_and_private_api(self) -> None:
        self.assertEqual(self.client.get('/api/cloud/session', base_url=self.base).json,
                         {'cloud': True, 'authenticated': False})
        for route in ['/api/session', '/api/dashboard', '/img/p/123', '/oauth/shop?code=synthetic&state=synthetic']:
            self.assertEqual(self.client.get(route, base_url=self.base).status_code, 401)
        self.assertEqual(self.client.get('/api/health', base_url=self.base).status_code, 200)
        self.assertEqual(self.client.get('/', base_url=self.base).status_code, 200)

    def test_login_cookie_logout_and_wrong_password(self) -> None:
        bad = self.client.post('/api/cloud/login', json={'password': 'wrong'}, headers=self.headers, base_url=self.base)
        self.assertEqual(bad.status_code, 401)
        response = self.login()
        self.assertEqual(response.status_code, 200)
        cookie = response.headers['Set-Cookie']
        for flag in ['Secure', 'HttpOnly', 'SameSite=Lax']:
            self.assertIn(flag, cookie)
        self.assertNotIn('synthetic-password', cookie)
        self.assertTrue(self.client.get('/api/cloud/session', base_url=self.base).json['authenticated'])
        self.assertEqual(self.client.post('/api/cloud/logout', json={}, headers=self.headers,
                                          base_url=self.base).status_code, 200)
        self.assertEqual(self.client.get('/api/session', base_url=self.base).status_code, 401)

    def test_cross_site_login_and_mutation_are_rejected(self) -> None:
        for headers in [{}, {'Origin': 'https://evil.example', 'X-CH-Hub': '1'}, {'Origin': self.base}]:
            response = self.client.post('/api/cloud/login', json={'password': 'synthetic-password-for-tests'},
                                        headers=headers, base_url=self.base)
            self.assertEqual(response.status_code, 403)
        self.login()
        response = self.client.post('/api/sync', json={}, headers={'Origin': 'https://evil.example', 'X-CH-Hub': '1'},
                                    base_url=self.base)
        self.assertEqual(response.status_code, 403)
        self.hub.despachador.despachar.assert_not_called()

    def test_additional_web_origin_keeps_host_and_mutation_checks(self) -> None:
        alias = 'https://app.cutgc.com.mx'
        client = create_app(replace(self.settings, additional_web_origin=alias), self.hub).test_client()
        headers = {'Origin': alias, 'X-CH-Hub': '1'}
        response = client.post('/api/cloud/login', json={'password': 'synthetic-password-for-tests'},
                               headers=headers, base_url=self.base)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.get('/api/cloud/session', base_url=alias).status_code, 400)

        self.hub.local.importar.return_value = {'ok': True}
        for rejected in [{}, {'Origin': alias}, {'Origin': alias + '.example', 'X-CH-Hub': '1'}]:
            response = client.post('/api/cloud/import', json={}, headers=rejected, base_url=self.base)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json['error']['codigo'], 'origen_invalido')
        self.hub.local.importar.assert_not_called()

        payload = {'version': 1, 'plan': []}
        response = client.post('/api/cloud/import', json=payload, headers=headers, base_url=self.base)
        self.assertEqual(response.status_code, 200)
        self.hub.local.importar.assert_called_once_with(payload)

    def test_additional_web_origin_environment_requires_exact_https(self) -> None:
        alias = 'https://app.cutgc.com.mx'
        env = {
            'CORTE_PUBLIC_URL': self.base,
            'CORTE_SESSION_SECRET': self.settings.session_secret,
            'CORTE_ENCRYPTION_KEY': 'synthetic-encryption-key-' * 3,
            'CORTE_AUTH_PROVIDER': 'password',
            'CORTE_PASSWORD_HASH': self.password_hash,
        }
        with patch.dict(os.environ, {**env, 'CORTE_ADDITIONAL_WEB_ORIGIN': alias}, clear=True):
            self.assertEqual(Settings.from_env().additional_web_origin, alias)
        for invalid in ('http://app.cutgc.com.mx', 'https://*.cutgc.com.mx', f'{alias}/path', f'{alias}?query',
                        'https://user@app.cutgc.com.mx', f'{alias},https://other.example'):
            with self.subTest(invalid=invalid):
                with patch.dict(os.environ, {**env, 'CORTE_ADDITIONAL_WEB_ORIGIN': invalid}, clear=True):
                    with self.assertRaisesRegex(ValueError, 'CORTE_ADDITIONAL_WEB_ORIGIN'):
                        Settings.from_env()

    def test_host_and_https_are_enforced(self) -> None:
        self.assertEqual(self.client.get('/api/cloud/session', base_url='https://evil.example').status_code, 400)
        self.assertEqual(self.client.get('/api/cloud/session', base_url='http://corte.example').status_code, 400)

    def test_google_health_check_can_use_http_without_opening_private_api(self) -> None:
        self.assertEqual(self.client.get('/api/health', base_url='http://corte.example').status_code, 200)
        self.assertEqual(self.client.get('/api/session', base_url='http://corte.example').status_code, 400)

    def test_explicit_proxy_configuration_uses_only_trusted_final_ips(self) -> None:
        from flask import request
        settings = Settings(self.base, self.settings.session_secret, self.password_hash, self.folder.name,
                            self.folder.name, trust_proxy=True, proxy_hops=2)
        app = create_app(settings, self.hub)
        @app.get('/test-address')
        def address():
            return {'address': request.remote_addr}
        result = app.test_client().get('/test-address', base_url='http://corte.example',
                                       headers={'X-Forwarded-Proto': 'https',
                                                'X-Forwarded-For': '198.51.100.99, 203.0.113.10, 35.191.0.1'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['address'], '203.0.113.10')

    def test_rate_limit_and_no_local_filesystem_or_lan(self) -> None:
        self.login()
        for route in ['/api/lan/estado', '/api/auth/portapapeles', '/api/credenciales/importar', '/api/local/importar']:
            self.assertEqual(self.client.get(route, base_url=self.base).status_code, 410)
        for _ in range(10):
            response = self.client.post('/api/cloud/login', json={'password': 'bad'},
                                        headers=self.headers, base_url=self.base)
        self.assertEqual(response.status_code, 429)

    def test_password_change_invalidates_existing_session(self) -> None:
        self.login()
        changed = Settings(self.base, self.settings.session_secret, generate_password_hash('changed-password'),
                           self.folder.name, self.folder.name)
        second = create_app(changed, self.hub).test_client()
        cookie = self.client.get_cookie('corte_session', domain='corte.example')
        second.set_cookie('corte_session', cookie.value, domain='corte.example', secure=True)
        self.assertFalse(second.get('/api/cloud/session', base_url=self.base).json['authenticated'])

    def test_import_reads_json_instead_of_server_path(self) -> None:
        self.login()
        self.hub.local.importar.return_value = {'ok': True}
        payload = {'version': 1, 'plan': []}
        response = self.client.post('/api/cloud/import', json=payload, headers=self.headers, base_url=self.base)
        self.assertEqual(response.status_code, 200)
        self.hub.local.importar.assert_called_once_with(payload)

    def test_revision_is_private_stable_and_tracks_real_changes(self) -> None:
        self.assertEqual(self.client.get('/api/cloud/revision', base_url=self.base).status_code, 401)
        self.login()
        self.hub.almacen.versiones.return_value = (1, 2, 3)
        self.hub.auth.conexion.return_value = {'estado': 'conectada', 'access_expira_at': 2000000000}
        self.hub.display.estado.return_value = {'estado': 'sin_conectar'}
        sync = {'en_curso': False, 'sync_id': None, 'progreso': 0, 'pasos': [], 'ultima_ok_at': None}
        self.hub.sincronizador.estado.return_value = sync
        first = self.client.get('/api/cloud/revision', base_url=self.base)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json['sync'], sync)
        with patch('cloud.app.time.time', return_value=time.time() + 60):
            same = self.client.get('/api/cloud/revision', base_url=self.base)
        self.assertEqual(first.json['revision'], same.json['revision'])
        self.hub.almacen.versiones.return_value = (1, 3, 3)
        changed = self.client.get('/api/cloud/revision', base_url=self.base)
        self.assertNotEqual(first.json['revision'], changed.json['revision'])
        self.hub.auth.conexion.return_value = {'estado': 'reautorizar'}
        auth_changed = self.client.get('/api/cloud/revision', base_url=self.base)
        self.assertNotEqual(changed.json['revision'], auth_changed.json['revision'])
        self.hub.display.estado.return_value = {'estado': 'conectada'}
        display_changed = self.client.get('/api/cloud/revision', base_url=self.base)
        self.assertNotEqual(auth_changed.json['revision'], display_changed.json['revision'])
        self.hub.sincronizador.estado.return_value = {**sync, 'en_curso': True, 'progreso': 0.25}
        active = self.client.get('/api/cloud/revision', base_url=self.base)
        self.assertNotEqual(display_changed.json['revision'], active.json['revision'])
        self.hub.sincronizador.estado.return_value = {**sync, 'en_curso': True, 'progreso': 0.5}
        progress = self.client.get('/api/cloud/revision', base_url=self.base)
        self.assertEqual(active.json['revision'], progress.json['revision'])
        self.assertEqual(progress.json['sync']['progreso'], 0.5)

    def test_revision_refreshes_open_dashboard_at_mexico_midnight(self) -> None:
        self.assertEqual(self.login().status_code, 200)
        self.hub.almacen.versiones.return_value = (1, 2, 3)
        self.hub.auth.conexion.return_value = {'estado': 'conectada'}
        self.hub.display.estado.return_value = {'estado': 'sin_conectar'}
        self.hub.sincronizador.estado.return_value = {'en_curso': False, 'pasos': []}
        midnight = epoch_de_fecha_local('2026-11-18', hora=0)

        def revision_at(now: int) -> str:
            self.hub.reloj.ahora.return_value = now
            response = self.client.get('/api/cloud/revision', base_url=self.base)
            self.assertEqual(response.status_code, 200)
            return response.json['revision']

        previous_day = revision_at(midnight - 7 * 3600)
        self.assertEqual(previous_day, revision_at(midnight - 1))
        current_day = revision_at(midnight)
        self.assertNotEqual(previous_day, current_day)
        self.assertEqual(current_day, revision_at(midnight + 3600))


class RealHubTests(unittest.TestCase):
    def test_cloud_startup_never_calls_windows_apis(self) -> None:
        script = textwrap.dedent('''
            import ctypes, json, os, sys, tempfile
            from unittest.mock import patch
            def forbidden(*args, **kwargs):
                raise AssertionError('A Windows API was called in cloud mode')
            class NoWindows:
                def __getattr__(self, name):
                    return forbidden
            ctypes.WinDLL = forbidden
            ctypes.windll = NoWindows()
            sys.modules['winreg'] = None
            from creatorhub.hub import iniciar_hub
            from creatorhub.interfaces import OpcionesHub, CTX_UI
            with tempfile.TemporaryDirectory() as folder:
                with patch.dict(os.environ, {'CORTE_PUBLIC_URL':'https://corte.example',
                                             'CORTE_ENCRYPTION_KEY':'synthetic-master-' * 4}):
                    hub = iniciar_hub(OpcionesHub(modo='real', nube=True, sin_lan=True,
                                                 raiz_datos=folder, sync_al_iniciar=False))
                    try:
                        assert hub.servidor is None and hub.lan is None
                        assert hub.despachador.despachar('GET','/api/session','',{},b'',CTX_UI).status == 200
                    finally:
                        hub.detener(10)
        ''')
        env = {**os.environ, 'PYTHONPATH': str(ROOT / 'hub')}
        result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))

    def test_cloud_has_no_local_listener_or_lan_and_keeps_saved_notes(self) -> None:
        from creatorhub.hub import iniciar_hub
        with tempfile.TemporaryDirectory() as folder:
            env = {'CORTE_PUBLIC_URL': 'https://corte.example', 'CORTE_ENCRYPTION_KEY': 'synthetic-master-' * 4}
            with patch.dict(os.environ, env):
                options = OpcionesHub(modo='real', nube=True, sin_lan=True, raiz_datos=folder,
                                       sync_al_iniciar=False)
                hub = iniciar_hub(options)
                try:
                    self.assertIsNone(hub.lan)
                    self.assertIsNone(hub.servidor)
                    from creatorhub.interfaces import CTX_UI
                    response = hub.despachador.despachar('GET', '/api/session', '', {}, b'', CTX_UI)
                    self.assertEqual(response.status, 200)
                    data = json.loads(response.cuerpo)
                    self.assertTrue(data['cloud'])
                    self.assertFalse(data['capacidades']['lan_admin'])
                    self.assertFalse(data['capacidades']['portapapeles'])
                    self.assertFalse(data['datos']['hay_datos'])
                    hub.boveda.mutar(lambda data: data.update(app_secret='synthetic-secret'))
                    with hub.almacen.escritor() as conn:
                        conn.execute("INSERT INTO preferencias(clave, valor_json, actualizado_at) VALUES ('cloud.test', 'true', 1)")
                finally:
                    hub.detener(10)
                reopened = iniciar_hub(options)
                try:
                    self.assertEqual(reopened.boveda.leer()['app_secret'], 'synthetic-secret')
                    with reopened.almacen.lector() as conn:
                        self.assertEqual(conn.execute("SELECT valor_json FROM preferencias WHERE clave='cloud.test'").fetchone()[0], 'true')
                finally:
                    reopened.detener(10)


class FirebaseTests(unittest.TestCase):
    def service(self):
        from cloud.firebase_service import FirebaseServices
        service = object.__new__(FirebaseServices)
        service.owner_uid = 'owner-uid'
        service.owner_email = 'owner@example.com'
        service.app = Mock()
        service.auth = Mock()
        service.revocations = Mock()
        service.revocations.revoked.return_value = False
        return service

    def claims(self):
        return {'uid': 'owner-uid', 'sub': 'owner-uid', 'email': 'owner@example.com', 'email_verified': True,
                'firebase': {'sign_in_provider': 'google.com'}, 'auth_time': int(time.time())}

    def test_only_verified_owner_google_account_is_allowed(self):
        service = self.service()
        self.assertTrue(service.allowed(self.claims()))
        variants = [{'uid': 'outsider'}, {'email': 'outsider@example.com'}, {'email_verified': False},
                    {'firebase': {'sign_in_provider': 'password'}}, {'uid': '../other'}]
        for changed in variants:
            self.assertFalse(service.allowed({**self.claims(), **changed}))

    def test_google_token_requires_recent_auth_and_checks_revocation(self):
        from cloud.firebase_service import FirebaseAccessError
        service = self.service()
        service.auth.verify_id_token.return_value = self.claims()
        service.auth.create_session_cookie.return_value = 'synthetic-cookie'
        self.assertEqual(service.create_session('synthetic-id-token'), 'synthetic-cookie')
        service.auth.verify_id_token.assert_called_with('synthetic-id-token', check_revoked=True, app=service.app)
        service.auth.verify_id_token.return_value = {**self.claims(), 'auth_time': int(time.time()) - 301}
        with self.assertRaises(FirebaseAccessError):
            service.create_session('synthetic-id-token')
        service.auth.verify_session_cookie.return_value = self.claims()
        self.assertIsNotNone(service.verify_session('synthetic-cookie'))
        service.auth.verify_session_cookie.assert_called_with('synthetic-cookie', check_revoked=True, app=service.app)
        service.auth.verify_session_cookie.side_effect = ValueError('revoked')
        self.assertIsNone(service.verify_session('synthetic-cookie'))

    def test_storage_rejects_arbitrary_paths(self):
        service = self.service()
        for identifier in ['../other', 'users/someone/private.json', '', None]:
            with self.assertRaises(ValueError):
                service.restore(self.claims(), identifier)

    def test_storage_roundtrip_stays_in_owner_namespace_and_limits_listing(self):
        service = self.service()
        service.storage = Mock()
        bucket = Mock()
        service.storage.bucket.return_value = bucket
        backup_data = {'formato': 'corte-local', 'version': 1, 'planes': []}
        result = service.backup(self.claims(), backup_data)
        object_path = bucket.blob.call_args.args[0]
        self.assertTrue(object_path.startswith('users/owner-uid/corte/backups/'))
        blob = bucket.blob.return_value
        self.assertEqual(blob.upload_from_string.call_args.kwargs['if_generation_match'], 0)
        blob.size = 100
        blob.generation = 123
        blob.download_as_bytes.return_value = json.dumps(backup_data).encode('utf-8')
        self.assertEqual(service.restore(self.claims(), result['id']), backup_data)
        bucket.list_blobs.return_value = []
        self.assertEqual(service.list_backups(self.claims()), [])
        self.assertEqual(bucket.list_blobs.call_args.kwargs['max_results'], 50)

    def test_logout_revocation_is_local_and_survives_restart(self):
        from cloud.firebase_service import SessionRevocations
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'sessions.sqlite')
            registry = SessionRevocations(path)
            registry.revoke('synthetic-cookie-corte', int(time.time()) + 3600)
            self.assertTrue(SessionRevocations(path).revoked('synthetic-cookie-corte'))
            self.assertFalse(registry.revoked('synthetic-cookie-other-app'))
            self.assertNotIn(b'synthetic-cookie-corte', Path(path).read_bytes())

    def test_web_config_google_login_and_revoking_logout(self):
        with tempfile.TemporaryDirectory() as folder:
            firebase = Mock()
            firebase.web_config = {'apiKey': 'public-api-key', 'authDomain': 'corte-test.firebaseapp.com',
                                   'projectId': 'corte-test', 'storageBucket': 'corte-test.firebasestorage.app', 'appId': 'public-app-id'}
            firebase.create_session.return_value = 'synthetic-firebase-cookie'
            claims = self.claims()
            firebase.verify_session.return_value = claims
            hub = Mock()
            hub._candado_mutacion = threading.RLock()
            settings = Settings('https://corte.example', 'test-session-secret-' * 4, '', folder, folder,
                                auth_provider='firebase')
            client = create_app(settings, hub, firebase).test_client()
            self.assertEqual(client.get('/api/cloud/config', base_url=settings.public_url).json,
                             {'auth_provider': 'firebase', 'firebase': firebase.web_config})
            self.assertFalse(client.get('/api/cloud/session', base_url=settings.public_url).json['authenticated'])
            response = client.post('/api/cloud/login', json={'id_token': 'synthetic-id-token-value'},
                                   headers={'Origin': settings.public_url, 'X-CH-Hub': '1'}, base_url=settings.public_url)
            self.assertEqual(response.status_code, 200)
            self.assertIn('HttpOnly', response.headers['Set-Cookie'])
            self.assertIn('Secure', response.headers['Set-Cookie'])
            self.assertEqual(len(response.headers.getlist('Set-Cookie')), 1)
            self.assertTrue(response.headers['Set-Cookie'].startswith('__session='))
            self.assertTrue(client.get('/api/cloud/session', base_url=settings.public_url).json['authenticated'])
            logout = client.post('/api/cloud/logout', json={}, headers={'Origin': settings.public_url, 'X-CH-Hub': '1'},
                                 base_url=settings.public_url)
            self.assertEqual(logout.status_code, 200)
            self.assertEqual(len(logout.headers.getlist('Set-Cookie')), 1)
            self.assertTrue(logout.headers['Set-Cookie'].startswith('__session='))
            firebase.revoke.assert_called_once_with(claims, 'synthetic-firebase-cookie')


if __name__ == '__main__':
    unittest.main()
