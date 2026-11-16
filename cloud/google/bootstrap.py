"""Runs inside the app image as a short-lived root helper on the COS VM.

Reads only VM metadata and two exact Secret Manager version resources. Writes
the runtime env into /run (tmpfs), never into the persistent data disk or logs.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.request
import google_crc32c

METADATA = 'http://metadata.google.internal/computeMetadata/v1/'
ALLOWED_PUBLIC = frozenset({
    'CORTE_PUBLIC_URL', 'CORTE_AUTH_PROVIDER', 'CORTE_FIREBASE_WEB_CONFIG', 'CORTE_FIREBASE_PROJECT_ID',
    'CORTE_OWNER_EMAIL', 'CORTE_OWNER_UID', 'CORTE_TRUST_PROXY', 'CORTE_PROXY_HOPS',
    'CORTE_DATA_DIR', 'GOOGLE_CLOUD_PROJECT',
})
SECRET_KEYS = frozenset({'CORTE_SESSION_SECRET', 'CORTE_ENCRYPTION_KEY'})


def read_url(url: str, headers: dict[str, str]) -> bytes:
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.read(64 * 1024)
        except Exception:
            if attempt == 3:
                raise RuntimeError('Google configuration could not be read; check VM IAM and network.') from None
            time.sleep(2 ** attempt)
    raise AssertionError('unreachable')


def environment() -> dict[str, str]:
    metadata_headers = {'Metadata-Flavor': 'Google'}
    config = json.loads(read_url(METADATA + 'instance/attributes/corte-config', metadata_headers))
    secret_versions = config.pop('_secret_versions', {})
    if set(config) != ALLOWED_PUBLIC or set(secret_versions) != SECRET_KEYS:
        raise ValueError('Unexpected Corte runtime configuration.')
    project = config['GOOGLE_CLOUD_PROJECT']
    if not re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]', project):
        raise ValueError('Invalid Google project.')
    token = json.loads(read_url(METADATA + 'instance/service-accounts/default/token', metadata_headers))['access_token']
    for key, resource in secret_versions.items():
        expected_name = {'CORTE_SESSION_SECRET': 'corte-session-secret', 'CORTE_ENCRYPTION_KEY': 'corte-encryption-key'}[key]
        if not re.fullmatch(r'projects/' + re.escape(project) + '/secrets/' + expected_name + r'/versions/[1-9][0-9]*', resource):
            raise ValueError('Invalid secret version reference.')
        result = json.loads(read_url('https://secretmanager.googleapis.com/v1/' + resource + ':access',
                                     {'Authorization': 'Bearer ' + token}))
        raw = base64.b64decode(result['payload']['data'], validate=True)
        if int(result['payload']['dataCrc32c']) != google_crc32c.value(raw):
            raise ValueError('Secret payload integrity check failed.')
        value = raw.decode('utf-8')
        if len(value) < 32:
            raise ValueError('A runtime secret is too short.')
        config[key] = value
    if any(not isinstance(value, str) or '\n' in value or '\r' in value or '\x00' in value for value in config.values()):
        raise ValueError('Invalid environment value.')
    if config['CORTE_AUTH_PROVIDER'] != 'firebase' or config['CORTE_TRUST_PROXY'] != '1' or config['CORTE_PROXY_HOPS'] != '1':
        raise ValueError('The Google deployment requires Firebase and its single normalized gateway hop.')
    return config


def main() -> int:
    try:
        config = environment()
        path = Path('/run/corte/runtime.env')
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w', encoding='utf-8') as output:
            output.write('\n'.join(key + '=' + value for key, value in sorted(config.items())) + '\n')
            output.flush()
            os.fsync(output.fileno())
        os.chmod(path, 0o600)
        print('Runtime configuration loaded using VM identity.')
        return 0
    except Exception:
        # Do not emit exception bodies: they may contain credential payloads.
        print('Corte bootstrap failed. Verify metadata, exact secret versions and VM IAM.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
