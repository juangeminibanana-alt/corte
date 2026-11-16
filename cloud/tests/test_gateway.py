from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import requests
from requests.structures import CaseInsensitiveDict
from urllib3._collections import HTTPHeaderDict
from urllib3.exceptions import ProtocolError

from cloud.gateway import GatewaySettings, MAX_BYTES, create_app


def upstream(body=b'{"ok":true}', status=200, headers=None, cookies=()):
    response = Mock()
    response.status_code = status
    response.headers = CaseInsensitiveDict({'Content-Type': 'application/json', **(headers or {})})
    response.raw = Mock()
    response.raw.headers = HTTPHeaderDict()
    for cookie in cookies:
        response.raw.headers.add('Set-Cookie', cookie)
    response.raw.stream.return_value = iter([body])
    return response


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.settings = GatewaySettings('http://10.73.0.10:8080', 'https://corte-test.web.app')
        self.transport = Mock()
        self.transport.request.return_value = upstream()
        self.client = create_app(self.settings, self.transport).test_client()
        self.base = self.settings.public_url

    def test_upstream_is_fixed_private_ip_and_rejects_ssrf_targets(self):
        for target in ['http://169.254.169.254:8080', 'http://127.0.0.1:8080', 'http://localhost:8080',
                       'https://10.73.0.10:8080', 'http://10.73.0.10:8080/path', 'http://8.8.8.8:8080',
                       'http://owner@10.73.0.10:8080', 'http://10.73.0.10:80']:
            with self.assertRaises(ValueError):
                GatewaySettings(target, self.base)
        result = self.client.get('/api/dashboard?url=https://evil.example/', base_url=self.base)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(self.transport.request.call_args.args[1].startswith('http://10.73.0.10:8080/api/dashboard?'))
        self.assertFalse(self.transport.request.call_args.kwargs['allow_redirects'])
        for path in ['/private', '/metadata', '/assets/app.js']:
            self.assertEqual(self.client.get(path, base_url=self.base).status_code, 404)

    def test_identity_headers_are_normalized_and_csrf_headers_are_not_fabricated(self):
        self.client.set_cookie('__session', 'synthetic-owner-cookie', domain='corte-test.web.app')
        self.client.set_cookie('other_app', 'must-not-forward', domain='corte-test.web.app')
        result = self.client.post('/api/plan', json={'titulo': 'synthetic'}, base_url=self.base,
                                  headers={'Origin': self.base, 'X-CH-Hub': '1', 'X-Forwarded-For': '169.254.169.254',
                                           'X-Forwarded-Proto': 'http', 'Authorization': 'Bearer not-forwarded',
                                           'Forwarded': 'host=evil.example'})
        self.assertEqual(result.status_code, 200)
        sent = self.transport.request.call_args.kwargs['headers']
        self.assertEqual(sent['Host'], 'corte-test.web.app')
        self.assertEqual(sent['X-Forwarded-Proto'], 'https')
        self.assertEqual(sent['X-Forwarded-For'], '127.0.0.1')
        self.assertEqual(sent['Cookie'], '__session=synthetic-owner-cookie')
        self.assertEqual(sent['Origin'], self.base)
        self.assertEqual(sent['X-Ch-Hub'], '1')
        self.assertNotIn('Authorization', sent)
        self.assertNotIn('Forwarded', sent)
        self.client.get('/api/session', base_url=self.base)
        sent = self.transport.request.call_args.kwargs['headers']
        self.assertNotIn('Origin', sent)
        self.assertNotIn('X-CH-Hub', sent)

    def test_cookies_redirects_and_no_store_are_preserved_without_following(self):
        self.transport.request.return_value = upstream(b'', 303,
            {'Location': '/#/inicio', 'Connection': 'keep-alive, X-Remove', 'X-Remove': 'remove', 'Content-Length': '0'},
            ['__session=synthetic; Secure; HttpOnly; SameSite=Lax'])
        result = self.client.get('/oauth/shop?code=synthetic&state=synthetic', base_url=self.base)
        self.assertEqual(result.status_code, 303)
        self.assertEqual(result.headers['Location'], '/#/inicio')
        self.assertEqual(result.headers.getlist('Set-Cookie'), ['__session=synthetic; Secure; HttpOnly; SameSite=Lax'])
        self.assertEqual(result.headers['Cache-Control'], 'private, no-store')
        self.assertNotIn('X-Remove', result.headers)
        self.assertNotIn('Connection', result.headers)
        self.transport.request.assert_called_once()

    def test_sessions_are_per_request_and_never_reuse_an_owner_cookie_jar(self):
        first, second = Mock(), Mock()
        first.request.return_value = upstream(cookies=['__session=synthetic-owner; Secure; HttpOnly'])
        second.request.return_value = upstream(b'{"error":{"codigo":"sesion_requerida"}}', status=401)
        with patch('cloud.gateway.requests.Session', side_effect=[first, second]) as factory:
            app = create_app(self.settings)
            client = app.test_client()
            self.assertEqual(client.post('/api/cloud/login', json={'id_token': 'synthetic'}, base_url=self.base).status_code, 200)
            # A completely separate visitor to the same gateway has no session.
            anonymous = app.test_client()
            result = anonymous.get('/api/session', base_url=self.base)
            self.assertEqual(result.status_code, 401)
            self.assertEqual(factory.call_count, 2)
            self.assertNotIn('Cookie', second.request.call_args.kwargs['headers'])
            self.assertFalse(first.trust_env)
            first.close.assert_called_once()
            second.close.assert_called_once()

    def test_timeouts_body_interruptions_and_size_limits_return_json(self):
        self.transport.request.side_effect = requests.Timeout('synthetic failure')
        result = self.client.get('/api/session', base_url=self.base)
        self.assertEqual(result.status_code, 504)
        self.assertIsNotNone(result.json['error'])
        self.transport.request.side_effect = None
        interrupted = upstream()
        interrupted.raw.stream.side_effect = ProtocolError('synthetic interruption')
        self.transport.request.return_value = interrupted
        result = self.client.get('/api/session', base_url=self.base)
        self.assertEqual(result.status_code, 502)
        self.assertIsNotNone(result.json['error'])
        interrupted.close.assert_called_once()
        self.transport.request.reset_mock()
        result = self.client.post('/api/cloud/import', data=b'x' * (MAX_BYTES + 1), base_url=self.base)
        self.assertEqual(result.status_code, 413)
        self.transport.request.assert_not_called()
        self.transport.request.return_value = upstream(b'x' * (MAX_BYTES + 1))
        self.assertEqual(self.client.get('/api/snapshot', base_url=self.base).status_code, 502)

    def test_compressed_response_bytes_are_not_silently_decoded(self):
        compressed = b'\x1f\x8bsynthetic-compressed-bytes'
        self.transport.request.return_value = upstream(compressed, headers={'Content-Encoding': 'gzip'})
        result = self.client.get('/api/session', base_url=self.base)
        self.assertEqual(result.data, compressed)
        self.assertEqual(result.headers['Content-Encoding'], 'gzip')
        self.transport.request.return_value.raw.stream.assert_called_once_with(64 * 1024, decode_content=False)

    def test_sse_silent_read_budget_fits_hosting_timeout_and_closes_upstream(self):
        clock = [0]
        response = upstream(headers={'Content-Type': 'text/event-stream'})
        def delayed_lines(**_kwargs):
            yield b'retry: 3000'
            clock[0] = 34
            yield b''
            # Simulate one final silent read bounded by the configured 17s.
            clock[0] += 17
            yield b'data: late-event'
        response.iter_lines.side_effect = delayed_lines
        self.transport.request.return_value = response
        with patch('cloud.gateway.time.monotonic', side_effect=lambda: clock[0]):
            result = self.client.get('/api/events', base_url=self.base)
            self.assertEqual(result.data, b'retry: 3000\n\n')
        self.assertLess(clock[0], 55)
        self.assertEqual(self.transport.request.call_args.kwargs['timeout'], (3, 17))
        response.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
