"""Exercise push routes through the real native auth/CSRF/scope middleware."""
from pathlib import Path
import unittest

from cloud.app import Settings, create_app, opaque_client_scopes
from cloud.push_service import PushService
from cloud.tests import test_native_auth as native_tests


class PushRouteTests(unittest.TestCase):
    def setUp(self):
        self.fixture = native_tests.NativeWebTests(methodName='runTest')
        self.fixture.setUp()
        f = self.fixture
        self.scope = opaque_client_scopes(f.claims, 'synthetic-creator')['cache_scope']
        f.hub.boveda.leer.return_value = {'open_id': 'synthetic-creator'}
        self.push = PushService(str(Path(f.folder.name) / 'push.sqlite'), 'test-push-secret' * 4,
            lambda uid: {'scope': self.scope, 'sales': [], 'awaiting': []}, lambda uid, device: True)
        settings = Settings(f.base, 'synthetic-session-key-' * 4, '', f.folder.name, f.folder.name, auth_provider='firebase')
        f.app = create_app(settings, f.hub, f.firebase, push=self.push)
        f.client, f.owner = f.app.test_client(), f.app.test_client()
        f.owner.set_cookie('__session', 'synthetic-owner-cookie', domain='corte.example', secure=True)
        self.grant = f.grant()
        self.headers = {**f.headers, 'Authorization': 'Bearer ' + self.grant['token'], 'X-Corte-Cache-Scope': self.scope}

    def tearDown(self):
        self.push.close()
        self.fixture.tearDown()

    def call(self, method, path, body=None, headers=None):
        return self.fixture.client.open(path, method=method, json=body,
            headers=self.headers if headers is None else headers, base_url=self.fixture.base)

    def test_register_status_feed_ack_disable_are_native_and_no_store(self):
        body = {'platform': 'windows', 'permission': 'concedido'}
        first = self.call('GET', '/api/push/status')
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json['enabled'])
        registered = self.call('POST', '/api/push/register', body)
        self.assertEqual(registered.status_code, 200)
        self.assertTrue(registered.json['enabled'])
        self.assertEqual(registered.headers['Cache-Control'], 'no-store')
        self.assertEqual(self.call('GET', '/api/push/events?after=0').json['items'], [])
        self.assertEqual(self.call('POST', '/api/push/ack', {'ids': []}).status_code, 200)
        disabled = self.call('DELETE', '/api/push/register')
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.json['enabled'])

    def test_anonymous_and_browser_cookie_cannot_register_or_read_push_feed(self):
        f = self.fixture
        for path in ('/api/push/status', '/api/push/events'):
            self.assertEqual(self.call('GET', path, headers={}).status_code, 401)
            self.assertEqual(f.owner.get(path, headers={'X-Corte-Cache-Scope': self.scope}, base_url=f.base).status_code, 401)
        denied = f.owner.post('/api/push/register', json={'platform': 'windows', 'permission': 'concedido'},
                              headers={**f.headers, 'X-Corte-Cache-Scope': self.scope}, base_url=f.base)
        self.assertEqual(denied.status_code, 401)

    def test_scope_is_mandatory_for_reads_and_writes_and_creator_change_rejects(self):
        missing = {k: v for k, v in self.headers.items() if k != 'X-Corte-Cache-Scope'}
        for method, path, body in [('GET', '/api/push/status', None), ('GET', '/api/push/events', None),
                                  ('POST', '/api/push/register', {'platform': 'windows', 'permission': 'concedido'}),
                                  ('POST', '/api/push/ack', {'ids': []}), ('DELETE', '/api/push/register', None)]:
            with self.subTest(path=path):
                self.assertEqual(self.call(method, path, body, missing).status_code, 409)
        self.fixture.hub.boveda.leer.return_value = {'open_id': 'another-creator'}
        self.assertEqual(self.call('GET', '/api/push/status').status_code, 409)

    def test_platform_permissions_csrf_and_cursor_validation(self):
        for body in ({'platform': 'android', 'token': 'synthetic-fcm-value' * 4, 'permission': 'concedido'},
                     {'platform': 'windows', 'permission': 'denegado'},
                     {'platform': 'windows', 'permission': 'concedido', 'uid': 'another-owner'}):
            self.assertEqual(self.call('POST', '/api/push/register', body).status_code, 422)
        self.assertEqual(self.call('POST', '/api/push/register', {},
            {'Authorization': self.headers['Authorization'], 'X-Corte-Cache-Scope': self.scope}).status_code, 403)
        for query in ('after=-1', 'after=1&after=2', 'unexpected=1'):
            self.assertEqual(self.call('GET', '/api/push/events?' + query).status_code, 422)

    def test_native_self_revoke_also_disables_push_subscription(self):
        self.call('POST', '/api/push/register', {'platform': 'windows', 'permission': 'concedido'})
        result = self.call('POST', '/api/native/devices/self/revoke', {})
        self.assertEqual(result.status_code, 200)
        self.assertFalse(self.push.status(self.fixture.claims['uid'], self.scope, self.grant['device_id'])['enabled'])
        self.assertEqual(self.call('GET', '/api/push/status').status_code, 401)


if __name__ == '__main__':
    unittest.main()
