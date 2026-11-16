from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import patch

import google_crc32c

from cloud.google import bootstrap


class GoogleBootstrapTests(unittest.TestCase):
    def config(self):
        config = {key: 'synthetic-public-value' for key in bootstrap.ALLOWED_PUBLIC}
        config.update(GOOGLE_CLOUD_PROJECT='synthetic-project', CORTE_AUTH_PROVIDER='firebase',
                      CORTE_TRUST_PROXY='1', CORTE_PROXY_HOPS='1')
        config['_secret_versions'] = {
            'CORTE_SESSION_SECRET': 'projects/synthetic-project/secrets/corte-session-secret/versions/1',
            'CORTE_ENCRYPTION_KEY': 'projects/synthetic-project/secrets/corte-encryption-key/versions/1',
        }
        return config

    def responses(self, config, bad_crc=False):
        secret = b'synthetic-random-value-for-tests-only-12345'
        return [json.dumps(config).encode(), b'{"access_token":"synthetic-metadata-access"}',
                json.dumps({'payload': {'data': base64.b64encode(secret).decode(),
                                        'dataCrc32c': '0' if bad_crc else str(google_crc32c.value(secret))}}).encode(),
                json.dumps({'payload': {'data': base64.b64encode(secret).decode(),
                                        'dataCrc32c': str(google_crc32c.value(secret))}}).encode()]

    def test_only_expected_secret_versions_are_read_using_vm_identity(self):
        with patch.object(bootstrap, 'read_url', side_effect=self.responses(self.config())) as fetch:
            env = bootstrap.environment()
            self.assertEqual(env['CORTE_AUTH_PROVIDER'], 'firebase')
            self.assertNotIn('_secret_versions', env)
            self.assertNotIn('GOOGLE_APPLICATION_CREDENTIALS', env)
            self.assertEqual(fetch.call_count, 4)
            self.assertEqual(fetch.call_args_list[2].args[0],
                             'https://secretmanager.googleapis.com/v1/projects/synthetic-project/secrets/corte-session-secret/versions/1:access')

    def test_cross_project_secret_and_extra_env_are_rejected(self):
        config = self.config()
        config['_secret_versions']['CORTE_SESSION_SECRET'] = 'projects/other-project/secrets/corte-session-secret/versions/1'
        with patch.object(bootstrap, 'read_url', side_effect=self.responses(config)):
            with self.assertRaises(ValueError):
                bootstrap.environment()
        config = self.config()
        config['GOOGLE_APPLICATION_CREDENTIALS'] = '/tmp/unsafe-key.json'
        with patch.object(bootstrap, 'read_url', return_value=json.dumps(config).encode()):
            with self.assertRaises(ValueError):
                bootstrap.environment()

    def test_secret_checksum_and_newline_injection_are_rejected(self):
        with patch.object(bootstrap, 'read_url', side_effect=self.responses(self.config(), bad_crc=True)):
            with self.assertRaises(ValueError):
                bootstrap.environment()
        config = self.config()
        config['CORTE_OWNER_EMAIL'] = 'owner@example.com\nCORTE_ALLOW_HTTP=1'
        with patch.object(bootstrap, 'read_url', side_effect=self.responses(config)):
            with self.assertRaises(ValueError):
                bootstrap.environment()
