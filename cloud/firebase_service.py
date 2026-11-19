"""Firebase Google identity and private Storage. Admin credentials never reach UI."""
from __future__ import annotations

from datetime import timedelta
import json
import os
from pathlib import Path
import re
import hashlib
import sqlite3
from contextlib import closing
import time
from typing import Any
from uuid import uuid4


class FirebaseAccessError(Exception):
    pass


class SessionRevocations:
    """Corte-only cookie revocation; no project-wide Firebase user mutation."""
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=5)) as connection, connection:
            connection.execute('CREATE TABLE IF NOT EXISTS revoked (fingerprint TEXT PRIMARY KEY, expires_at INTEGER NOT NULL)')

    def revoked(self, cookie: str) -> bool:
        with closing(sqlite3.connect(self.path, timeout=5)) as connection, connection:
            connection.execute('DELETE FROM revoked WHERE expires_at <= ?', (int(time.time()),))
            return connection.execute('SELECT 1 FROM revoked WHERE fingerprint = ?',
                                      (hashlib.sha256(cookie.encode()).hexdigest(),)).fetchone() is not None

    def revoke(self, cookie: str, expires_at: int) -> None:
        with closing(sqlite3.connect(self.path, timeout=5)) as connection, connection:
            connection.execute('INSERT OR REPLACE INTO revoked VALUES (?, ?)',
                               (hashlib.sha256(cookie.encode()).hexdigest(), expires_at))


class FirebaseServices:
    def __init__(self) -> None:
        import firebase_admin
        from firebase_admin import auth, credentials, storage
        self.auth = auth
        self.storage = storage
        self.revocations = SessionRevocations(str(Path(os.environ.get('CORTE_DATA_DIR', '/var/lib/corte')) / 'sesiones.sqlite'))
        self.owner_uid = os.environ.get('CORTE_OWNER_UID', '').strip()
        self.owner_email = os.environ.get('CORTE_OWNER_EMAIL', '').strip().lower()
        if not self.owner_uid and not self.owner_email:
            raise ValueError('Configura CORTE_OWNER_UID o CORTE_OWNER_EMAIL antes de habilitar Google.')
        try:
            config = json.loads(os.environ.get('CORTE_FIREBASE_WEB_CONFIG', '{}'))
            self.web_config = {key: str(config[key]) for key in ('apiKey', 'authDomain', 'projectId', 'storageBucket', 'appId')}
            if not all(self.web_config.values()):
                raise ValueError('empty')
        except (ValueError, TypeError, KeyError):
            raise ValueError('Falta CORTE_FIREBASE_WEB_CONFIG con la configuración pública de la app web.') from None
        self.bucket_name = self.web_config['storageBucket']
        if not re.fullmatch(r'[A-Za-z0-9.-]+', self.web_config['authDomain']):
            raise ValueError('Firebase authDomain no es válido.')
        if '/' in self.bucket_name or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{2,221}', self.bucket_name):
            raise ValueError('El nombre de Firebase Storage no debe contener gs:// ni rutas.')
        project = self.web_config['projectId']
        if os.environ.get('CORTE_FIREBASE_PROJECT_ID', project) != project:
            raise ValueError('La configuración web y el proyecto de Firebase no coinciden.')
        raw_service_account = os.environ.get('CORTE_FIREBASE_SERVICE_ACCOUNT_JSON')
        try:
            credential = credentials.Certificate(json.loads(raw_service_account)) if raw_service_account else credentials.ApplicationDefault()
            if raw_service_account and json.loads(raw_service_account).get('project_id') != project:
                raise ValueError('project mismatch')
            try:
                self.app = firebase_admin.get_app('corte-cloud')
                if self.app.project_id != project:
                    raise ValueError('project mismatch')
            except ValueError as exc:
                if str(exc) == 'project mismatch':
                    raise
                self.app = firebase_admin.initialize_app(credential, {'projectId': project, 'storageBucket': self.bucket_name,
                                                                      'httpTimeout': 15},
                                                         name='corte-cloud')
        except Exception:
            raise ValueError('No se pudo inicializar Firebase Admin. Revisa el proyecto y su credencial privada.') from None

    def allowed(self, claims: dict[str, Any]) -> bool:
        uid = claims.get('uid') or claims.get('sub')
        email = claims.get('email')
        return bool(isinstance(uid, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', uid)
                    and claims.get('email_verified') is True
                    and claims.get('firebase', {}).get('sign_in_provider') == 'google.com'
                    and (not self.owner_uid or uid == self.owner_uid)
                    and (not self.owner_email or isinstance(email, str) and email.lower() == self.owner_email))

    def verify_recent_google(self, id_token: str) -> dict[str, Any]:
        try:
            claims = self.auth.verify_id_token(id_token, check_revoked=True, app=self.app)
            age = time.time() - float(claims.get('auth_time', 0))
            if not self.allowed(claims) or not -60 <= age <= 300:
                raise FirebaseAccessError()
            return claims
        except Exception:
            raise FirebaseAccessError('No pudimos autorizar esta cuenta de Google para Corte.') from None

    def create_session(self, id_token: str) -> str:
        self.verify_recent_google(id_token)
        try:
            return self.auth.create_session_cookie(id_token, expires_in=timedelta(hours=12), app=self.app)
        except Exception:
            raise FirebaseAccessError('No pudimos autorizar esta cuenta de Google para Corte.') from None

    def verify_session(self, cookie: str) -> dict[str, Any] | None:
        try:
            if self.revocations.revoked(cookie):
                return None
            claims = self.auth.verify_session_cookie(cookie, check_revoked=True, app=self.app)
            return claims if self.allowed(claims) else None
        except Exception:
            return None

    def revoke(self, claims: dict[str, Any], cookie: str) -> None:
        if not cookie:
            raise ValueError('Missing session cookie.')
        self.revocations.revoke(cookie, int(claims.get('exp') or time.time() + 12 * 3600))

    def _bucket(self):
        return self.storage.bucket(app=self.app)

    @staticmethod
    def _prefix(claims: dict[str, Any]) -> str:
        return 'users/' + str(claims.get('uid') or claims['sub']) + '/corte/'

    def list_backups(self, claims: dict[str, Any]) -> list[dict[str, Any]]:
        prefix = self._prefix(claims) + 'backups/'
        items = []
        # Reverse timestamps put newest objects first in GCS lexicographic listings.
        for blob in self._bucket().list_blobs(prefix=prefix, max_results=50, timeout=20, retry=None):
            identifier = blob.name[len(prefix):].removesuffix('.json')
            if not re.fullmatch(r'\d{10}-[a-f0-9]{32}', identifier):
                continue
            items.append({'id': identifier, 'created_at': 9_999_999_999 - int(identifier[:10]), 'size_bytes': int(blob.size or 0)})
        return sorted(items, key=lambda item: item['created_at'], reverse=True)[:50]

    def backup(self, claims: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        created_at = int(time.time())
        identifier = f'{9_999_999_999 - created_at:010d}-{uuid4().hex}'
        blob = self._bucket().blob(self._prefix(claims) + 'backups/' + identifier + '.json')
        raw = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if len(raw) > 20 * 1024 * 1024:
            raise ValueError('La copia supera el límite de 20 MB.')
        blob.cache_control = 'private, no-store'
        blob.upload_from_string(raw, content_type='application/json', if_generation_match=0, timeout=30, retry=None)
        return {'id': identifier, 'created_at': created_at, 'size_bytes': len(raw)}

    def restore(self, claims: dict[str, Any], identifier: str) -> dict[str, Any]:
        if not isinstance(identifier, str) or not re.fullmatch(r'\d{10}-[a-f0-9]{32}', identifier):
            raise ValueError('La copia seleccionada no es válida.')
        blob = self._bucket().blob(self._prefix(claims) + 'backups/' + identifier + '.json')
        blob.reload(timeout=10, retry=None)
        if not blob.size or blob.size > 20 * 1024 * 1024:
            raise ValueError('La copia supera el límite permitido.')
        return json.loads(blob.download_as_bytes(timeout=30, if_generation_match=blob.generation, retry=None))

    def store_image(self, claims: dict[str, Any], relative_path: str, path: str) -> None:
        """Save the existing validated image-cache file without public download tokens."""
        from creatorhub.imagenes.claves import nombre_de_cache
        parts = relative_path.replace('\\', '/').split('/')
        if (len(parts) != 3 or parts[0] not in ('p', 'a', 'g', 'm', 'v')
                or not re.fullmatch(r'[a-z0-9]{1,2}', parts[1]) or not nombre_de_cache(parts[-1])
                or Path(path).stat().st_size > 10 * 1024 * 1024):
            raise ValueError('Imagen no válida.')
        blob = self._bucket().blob(self._prefix(claims) + 'images/' + '/'.join(parts))
        if not blob.exists(timeout=10, retry=None):
            blob.cache_control = 'private, no-store'
            blob.upload_from_filename(path, if_generation_match=0, timeout=30, retry=None)
