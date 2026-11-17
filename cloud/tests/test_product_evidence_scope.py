"""Authenticated evidence writes bind to the Google owner and exact TikTok creator.

The shared fixture is called through its module, not inherited/imported as a test
class, so discovery does not run the unrelated native suite a second time.
"""
import unittest

from cloud.app import opaque_client_scopes
from cloud.tests import test_native_auth as native_tests


class ProductEvidenceScopeTests(unittest.TestCase):
    def setUp(self):
        native_tests.NativeWebTests.setUp(self)
        self.hub.boveda.leer.return_value = {'open_id': 'synthetic-creator-current'}
        self.path = '/api/productos/100/evidencia'
        self.body = {'rev': 0, 'resenas': {'estado': 'pendiente'}}

    tearDown = native_tests.NativeWebTests.tearDown
    start = native_tests.NativeWebTests.start
    grant = native_tests.NativeWebTests.grant

    def scope(self):
        return self.owner.get('/api/cloud/session', base_url=self.base).json['cache_scope']

    def test_owner_write_requires_scope_even_with_valid_cookie_and_csrf_headers(self):
        self.hub.despachador.despachar.reset_mock()
        result = self.owner.put(self.path, json=self.body, headers=self.headers, base_url=self.base)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json['error']['codigo'], 'cuenta_cambio_sin_aplicar')
        self.hub.despachador.despachar.assert_not_called()

    def test_malformed_or_incorrect_scope_never_reaches_business_dispatcher(self):
        for invalid in ('', 'invalid', 'A' * 64, '0' * 63, '0' * 65, '0' * 64):
            with self.subTest(scope=invalid):
                self.hub.despachador.despachar.reset_mock()
                result = self.owner.put(self.path, json=self.body,
                                        headers={**self.headers, 'X-Corte-Cache-Scope': invalid},
                                        base_url=self.base)
                self.assertEqual(result.status_code, 409)
                self.assertEqual(result.json['error']['codigo'], 'cuenta_cambio_sin_aplicar')
                self.hub.despachador.despachar.assert_not_called()

    def test_creator_changed_after_page_loaded_rejects_old_import_without_dispatch(self):
        previous = self.scope()
        self.hub.boveda.leer.return_value = {'open_id': 'synthetic-creator-new'}
        self.hub.despachador.despachar.reset_mock()
        result = self.owner.put(self.path, json=self.body,
                                headers={**self.headers, 'X-Corte-Cache-Scope': previous}, base_url=self.base)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json['error']['codigo'], 'cuenta_cambio_sin_aplicar')
        self.hub.despachador.despachar.assert_not_called()

    def test_scope_from_another_google_owner_or_disconnected_creator_is_rejected(self):
        valid = self.scope()
        foreign = opaque_client_scopes({'uid': 'other-synthetic-owner'}, 'synthetic-creator-current')['cache_scope']
        for scope, connection in ((foreign, {'open_id': 'synthetic-creator-current'}), (valid, {})):
            with self.subTest(disconnected=not connection):
                self.hub.boveda.leer.return_value = connection
                self.hub.despachador.despachar.reset_mock()
                result = self.owner.put(self.path, json=self.body,
                                        headers={**self.headers, 'X-Corte-Cache-Scope': scope}, base_url=self.base)
                self.assertEqual(result.status_code, 409)
                self.assertEqual(result.json['error']['codigo'], 'cuenta_cambio_sin_aplicar')
                self.hub.despachador.despachar.assert_not_called()

    def test_current_owner_creator_scope_allows_authenticated_cookie_write(self):
        current = self.scope()
        self.hub.despachador.despachar.reset_mock()
        result = self.owner.put(self.path, json=self.body,
                                headers={**self.headers, 'X-Corte-Cache-Scope': current}, base_url=self.base)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data, b'{"ok":true}')
        self.hub.despachador.despachar.assert_called_once()
        self.assertEqual(self.hub.despachador.despachar.call_args.args[:2], ('PUT', self.path))

    def test_native_write_needs_same_scope_and_does_not_forward_bearer_secret(self):
        current = self.scope()
        grant = self.grant()
        headers = {**self.headers, 'Authorization': 'Bearer ' + grant['token']}
        self.hub.despachador.despachar.reset_mock()
        rejected = self.client.put(self.path, json=self.body, headers=headers, base_url=self.base)
        self.assertEqual(rejected.status_code, 409)
        self.hub.despachador.despachar.assert_not_called()
        accepted = self.client.put(self.path, json=self.body,
                                   headers={**headers, 'X-Corte-Cache-Scope': current}, base_url=self.base)
        self.assertEqual(accepted.status_code, 200)
        self.hub.despachador.despachar.assert_called_once()
        business_headers = self.hub.despachador.despachar.call_args.args[3]
        self.assertFalse(any(key.lower() == 'authorization' for key in business_headers))

    def test_scope_header_cannot_replace_authentication(self):
        current = self.scope()
        for extra in ({}, {'X-Corte-Cache-Scope': current}, {'X-Corte-Cache-Scope': 'invalid'}):
            with self.subTest(extra=extra):
                self.hub.despachador.despachar.reset_mock()
                result = self.client.put(self.path, json=self.body,
                                         headers={**self.headers, **extra}, base_url=self.base)
                self.assertEqual(result.status_code, 401)
                self.hub.despachador.despachar.assert_not_called()

    def test_read_does_not_require_write_scope_but_remains_authenticated(self):
        for path in (self.path, '/api/productos/100/resenas?cursor=20'):
            with self.subTest(path=path):
                self.hub.despachador.despachar.reset_mock()
                anonymous = self.client.get(path, base_url=self.base)
                self.assertEqual(anonymous.status_code, 401)
                self.hub.despachador.despachar.assert_not_called()
                allowed = self.owner.get(path, base_url=self.base)
                self.assertEqual(allowed.status_code, 200)
                self.hub.despachador.despachar.assert_called_once()
                self.assertEqual(self.hub.despachador.despachar.call_args.args[0], 'GET')

    def test_public_extraction_post_requires_current_scope_without_dispatch(self):
        path = '/api/productos/100/extraer'
        previous = self.scope()
        self.hub.boveda.leer.return_value = {'open_id': 'synthetic-creator-after-page-load'}
        for extra in ({}, {'X-Corte-Cache-Scope': 'invalid'}, {'X-Corte-Cache-Scope': previous}):
            with self.subTest(extra=extra):
                self.hub.despachador.despachar.reset_mock()
                result = self.owner.post(path, json={'rev': 0}, headers={**self.headers, **extra},
                                         base_url=self.base)
                self.assertEqual(result.status_code, 409)
                self.assertEqual(result.json['error']['codigo'], 'cuenta_cambio_sin_aplicar')
                self.hub.despachador.despachar.assert_not_called()
        current = self.scope()
        accepted = self.owner.post(path, json={'rev': 0},
                                   headers={**self.headers, 'X-Corte-Cache-Scope': current}, base_url=self.base)
        self.assertEqual(accepted.status_code, 200)
        self.hub.despachador.despachar.assert_called_once()
        self.assertEqual(self.hub.despachador.despachar.call_args.args[:2], ('POST', path))

    def test_public_extraction_native_post_requires_scope_and_does_not_forward_bearer(self):
        path = '/api/productos/100/extraer'
        current = self.scope()
        grant = self.grant()
        headers = {**self.headers, 'Authorization': 'Bearer ' + grant['token']}
        self.hub.despachador.despachar.reset_mock()
        rejected = self.client.post(path, json={'rev': 0}, headers=headers, base_url=self.base)
        self.assertEqual(rejected.status_code, 409)
        self.hub.despachador.despachar.assert_not_called()
        accepted = self.client.post(path, json={'rev': 0},
                                    headers={**headers, 'X-Corte-Cache-Scope': current}, base_url=self.base)
        self.assertEqual(accepted.status_code, 200)
        self.hub.despachador.despachar.assert_called_once()
        self.assertEqual(self.hub.despachador.despachar.call_args.args[:2], ('POST', path))
        business_headers = self.hub.despachador.despachar.call_args.args[3]
        self.assertFalse(any(key.lower() == 'authorization' for key in business_headers))

    def test_public_extraction_scope_never_replaces_authentication(self):
        self.hub.despachador.despachar.reset_mock()
        response = self.client.post('/api/productos/100/extraer', json={'rev': 0},
                                    headers={**self.headers, 'X-Corte-Cache-Scope': self.scope()}, base_url=self.base)
        self.assertEqual(response.status_code, 401)
        self.hub.despachador.despachar.assert_not_called()


if __name__ == '__main__':
    unittest.main()
