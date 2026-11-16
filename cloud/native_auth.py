"""Owner-approved native clients. Public enrollment proves possession with PKCE.

No Google/TikTok credential or native bearer is persisted here. A successful
poll delivers its token exactly once; a lost response requires a new approval.
SQLite transactions serialize approval, delivery and revocation across threads.
"""
from __future__ import annotations

import base64
import collections
from contextlib import contextmanager
import hashlib
import hmac
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from typing import Any, Callable
from urllib.parse import urlencode

TOKEN_PATTERN = r'corte_native_v1_[A-Za-z0-9_-]{43}'
BEARER_RE = re.compile(r'Bearer (' + TOKEN_PATTERN + r')\Z')
VERIFIER_RE = re.compile(r'[A-Za-z0-9._~-]{43,128}\Z')
ID_RE = re.compile(r'[A-Za-z0-9_-]{43}\Z')
CODE_RE = re.compile(r'[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}\Z')
PENDING_TTL = 600
DEVICE_TTL = 30 * 86400
INTERVAL = 3


class NativeAuthError(Exception):
    def __init__(self, code: str, message: str, status: int, retry_after: int | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.retry_after = code, message, status, retry_after


def invalid() -> NativeAuthError:
    return NativeAuthError('parametros_invalidos', 'La solicitud de conexión no es válida.', 422)


def body_fields(body: Any, fields: set[str]) -> dict[str, Any]:
    if not isinstance(body, dict) or set(body) != fields:
        raise invalid()
    return body


def challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')


class NativeAuth:
    def __init__(self, path: str, secret: str, public_url: str,
                 validate_owner: Callable[[str, str, int], dict[str, Any] | None],
                 clock: Callable[[], float] = time.time):
        self.path, self.public_url = path, public_url
        self._secret = secret.encode('utf-8')
        self._owner = validate_owner
        self._clock = clock
        self._lock = threading.Lock()
        self._attempts: dict[str, collections.deque[float]] = {}
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS requests (
                    request_hash TEXT PRIMARY KEY, code_hash TEXT UNIQUE NOT NULL,
                    challenge TEXT NOT NULL, platform TEXT NOT NULL, name TEXT NOT NULL,
                    created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pendiente', last_poll REAL NOT NULL DEFAULT 0,
                    owner_uid TEXT, owner_email TEXT, auth_time INTEGER
                );
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
                    platform TEXT NOT NULL, name TEXT NOT NULL, owner_uid TEXT NOT NULL,
                    owner_email TEXT NOT NULL, auth_time INTEGER NOT NULL,
                    created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, revoked_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS callbacks (
                    state_hash TEXT PRIMARY KEY, path TEXT NOT NULL,
                    device_id TEXT NOT NULL, expires_at INTEGER NOT NULL
                );
            ''')
        Path(path).chmod(0o600)

    @contextmanager
    def _db(self, write: bool = False):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                if write:
                    db.execute('BEGIN IMMEDIATE')
                yield db
        finally:
            db.close()

    def _hash(self, purpose: str, value: str) -> str:
        return hmac.new(self._secret, (purpose + '\0' + value).encode('utf-8'), hashlib.sha256).hexdigest()

    def limit(self, action: str, address: str) -> None:
        # HMAC avoids retaining raw IPs; both keys and buckets have fixed bounds.
        per_ip, global_cap = {'start': (10, 100), 'poll': (360, 6000), 'owner': (120, 1200)}[action]
        now = self._clock()
        own_key = action + ':' + self._hash('rate', address)
        with self._lock:
            self._attempts = {k: v for k, v in self._attempts.items() if v and v[-1] > now - 900}
            if own_key not in self._attempts and len(self._attempts) >= 2048:
                raise NativeAuthError('demasiados_intentos', 'Espera antes de volver a intentarlo.', 429, 900)
            own = self._attempts.setdefault(own_key, collections.deque())
            total = self._attempts.setdefault(action + ':*', collections.deque())
            for bucket in (own, total):
                while bucket and bucket[0] <= now - 900:
                    bucket.popleft()
            if len(own) >= per_ip or len(total) >= global_cap:
                raise NativeAuthError('demasiados_intentos', 'Espera antes de volver a intentarlo.', 429, 900)
            own.append(now)
            total.append(now)

    def start(self, body: Any) -> dict[str, Any]:
        data = body_fields(body, {'platform', 'name', 'code_challenge'})
        platform, name, proof = data['platform'], data['name'], data['code_challenge']
        if (platform not in ('windows', 'android') or not isinstance(name, str) or not 1 <= len(name.strip()) <= 80
                or any(ord(c) < 32 or ord(c) == 127 for c in name)
                or not isinstance(proof, str) or not ID_RE.fullmatch(proof)):
            raise invalid()
        if base64.urlsafe_b64encode(base64.urlsafe_b64decode(proof + '=')).rstrip(b'=').decode() != proof:
            raise invalid()
        now = int(self._clock())
        request_id = secrets.token_urlsafe(32)
        alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
        with self._db(True) as db:
            db.execute('DELETE FROM requests WHERE expires_at <= ?', (now - 3600,))
            db.execute('DELETE FROM devices WHERE expires_at <= ?', (now - 90 * 86400,))
            if db.execute('SELECT COUNT(*) FROM requests').fetchone()[0] >= 256:
                raise NativeAuthError('demasiados_intentos', 'Hay demasiadas conexiones pendientes. Inténtalo después.', 429, 600)
            for _ in range(8):
                raw_code = ''.join(secrets.choice(alphabet) for _ in range(8))
                code = raw_code[:4] + '-' + raw_code[4:]
                try:
                    db.execute('INSERT INTO requests(request_hash,code_hash,challenge,platform,name,created_at,expires_at) '
                               'VALUES(?,?,?,?,?,?,?)', (self._hash('request', request_id), self._hash('code', code),
                                                        proof, platform, name.strip(), now, now + PENDING_TTL))
                    break
                except sqlite3.IntegrityError:
                    continue
            else:
                raise NativeAuthError('servicio_no_disponible', 'Vuelve a iniciar la conexión.', 503)
        return {'request_id': request_id, 'user_code': code, 'verification_uri': self.public_url +
                '/conectar-dispositivo?' + urlencode({'codigo': code}), 'expires_in': PENDING_TTL, 'interval': INTERVAL}

    def _by_code(self, db, code: Any):
        if not isinstance(code, str) or not CODE_RE.fullmatch(code):
            raise invalid()
        row = db.execute('SELECT * FROM requests WHERE code_hash=?', (self._hash('code', code),)).fetchone()
        self._alive(row)
        return row

    def _alive(self, row) -> None:
        if row is None or row['expires_at'] <= self._clock():
            raise NativeAuthError('solicitud_vencida', 'Este código venció. Inicia otra conexión desde la app.', 410)

    def describe(self, code: Any) -> dict[str, Any]:
        with self._db() as db:
            row = self._by_code(db, code)
            return {'user_code': code, 'platform': row['platform'], 'name': row['name'],
                    'expires_at': row['expires_at'], 'estado': row['state']}

    def decide(self, body: Any, claims: dict[str, Any], approve: bool) -> dict[str, Any]:
        code = body_fields(body, {'user_code'})['user_code']
        uid, email = claims.get('uid') or claims.get('sub'), claims.get('email')
        auth_time = claims.get('auth_time')
        if not isinstance(uid, str) or not isinstance(email, str) or not isinstance(auth_time, (int, float)):
            raise NativeAuthError('cuenta_no_autorizada', 'Vuelve a entrar con Google.', 401)
        with self._db(True) as db:
            row = self._by_code(db, code)
            if row['state'] != 'pendiente':
                raise NativeAuthError('solicitud_resuelta', 'Esta solicitud ya fue resuelta. Vuelve a la app.', 409)
            state = 'aprobado' if approve else 'denegado'
            db.execute('UPDATE requests SET state=?,owner_uid=?,owner_email=?,auth_time=? WHERE request_hash=? '
                       "AND state='pendiente'", (state, uid, email, int(auth_time), row['request_hash']))
        return {'estado': state}

    def poll(self, body: Any) -> tuple[dict[str, Any], int]:
        data = body_fields(body, {'request_id', 'code_verifier'})
        rid, verifier = data['request_id'], data['code_verifier']
        if (not isinstance(rid, str) or not ID_RE.fullmatch(rid) or not isinstance(verifier, str)
                or not VERIFIER_RE.fullmatch(verifier)):
            raise invalid()
        fingerprint = self._hash('request', rid)
        # Validate identity without a database write lock around Firebase's network call.
        with self._db() as db:
            row = db.execute('SELECT * FROM requests WHERE request_hash=?', (fingerprint,)).fetchone()
        self._alive(row)
        if not hmac.compare_digest(challenge(verifier), row['challenge']):
            raise NativeAuthError('prueba_invalida', 'No pudimos verificar esta app. Inicia otra conexión.', 403)
        owner = None
        if row['state'] == 'aprobado':
            owner = self._owner(row['owner_uid'], row['owner_email'], row['auth_time'])
            if owner is None:
                raise NativeAuthError('cuenta_no_autorizada', 'Esta cuenta ya no puede autorizar el dispositivo.', 401)
        with self._db(True) as db:
            row = db.execute('SELECT * FROM requests WHERE request_hash=?', (fingerprint,)).fetchone()
            self._alive(row)
            if row['state'] == 'denegado':
                raise NativeAuthError('solicitud_denegada', 'La conexión del dispositivo fue rechazada.', 403)
            if row['state'] == 'entregado':
                raise NativeAuthError('autorizacion_entregada', 'La autorización ya se entregó. Si no llegó, inicia otra conexión.', 409)
            if row['state'] == 'pendiente' or owner is None:
                now = self._clock()
                if row['last_poll'] and now - row['last_poll'] < INTERVAL:
                    raise NativeAuthError('espera_sondeo', 'Espera antes de comprobar la conexión.', 429, INTERVAL)
                db.execute('UPDATE requests SET last_poll=? WHERE request_hash=?', (now, fingerprint))
                return {'estado': 'pendiente'}, 202
            now = int(self._clock())
            if db.execute('SELECT COUNT(*) FROM devices WHERE owner_uid=? AND revoked_at IS NULL AND expires_at>?',
                          (row['owner_uid'], now)).fetchone()[0] >= 64:
                raise NativeAuthError('limite_dispositivos', 'Revoca un dispositivo antes de conectar otro.', 409)
            token = 'corte_native_v1_' + secrets.token_urlsafe(32)
            device_id = secrets.token_urlsafe(18)
            expires = now + DEVICE_TTL
            db.execute('INSERT INTO devices VALUES(?,?,?,?,?,?,?,?,?,NULL)',
                       (device_id, hashlib.sha256(token.encode('ascii')).hexdigest(), row['platform'], row['name'],
                        row['owner_uid'], row['owner_email'], row['auth_time'], now, expires,))
            db.execute("UPDATE requests SET state='entregado' WHERE request_hash=? AND state='aprobado'", (fingerprint,))
        return {'estado': 'autorizado', 'device_id': device_id, 'token': token, 'expires_at': expires,
                'owner': {'uid': owner['uid'], 'email': owner['email']}}, 200

    def authenticate(self, token: str) -> dict[str, Any] | None:
        if not re.fullmatch(TOKEN_PATTERN, token):
            return None
        with self._db() as db:
            row = db.execute('SELECT * FROM devices WHERE token_hash=? AND revoked_at IS NULL AND expires_at>?',
                             (hashlib.sha256(token.encode('ascii')).hexdigest(), int(self._clock()))).fetchone()
        if row is None:
            return None
        claims = self._owner(row['owner_uid'], row['owner_email'], row['auth_time'])
        if claims is None:
            return None
        # Revocation may happen while Firebase validates the owner; recheck after it.
        with self._db() as db:
            live = db.execute('SELECT 1 FROM devices WHERE device_id=? AND revoked_at IS NULL AND expires_at>?',
                              (row['device_id'], int(self._clock()))).fetchone()
        return {'claims': claims, 'device_id': row['device_id'], 'expires_at': row['expires_at']} if live else None

    def devices(self, uid: str) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute('SELECT device_id,platform,name,created_at,expires_at,revoked_at FROM devices '
                              'WHERE owner_uid=? ORDER BY created_at DESC LIMIT 100', (uid,)).fetchall()
            return [dict(row) for row in rows]

    def revoke(self, uid: str, device_id: str) -> bool:
        if not isinstance(device_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{24}', device_id):
            raise invalid()
        with self._db(True) as db:
            return bool(db.execute('UPDATE devices SET revoked_at=COALESCE(revoked_at,?) WHERE device_id=? AND owner_uid=?',
                                   (int(self._clock()), device_id, uid)).rowcount)

    def register_callback(self, state: str, path: str, device_id: str) -> None:
        if path not in ('/oauth/shop', '/oauth/tiktok') or not re.fullmatch(r'[A-Za-z0-9_-]{16,256}', state):
            raise invalid()
        with self._db(True) as db:
            db.execute('DELETE FROM callbacks WHERE expires_at<=?', (int(self._clock()),))
            if db.execute('SELECT COUNT(*) FROM callbacks').fetchone()[0] >= 256:
                raise NativeAuthError('demasiados_intentos', 'Espera antes de crear otro enlace de conexión.', 429, 600)
            db.execute('INSERT OR REPLACE INTO callbacks VALUES(?,?,?,?)',
                       (self._hash('callback', state), path, device_id, int(self._clock()) + PENDING_TTL))

    def callback_owner(self, state: str, path: str) -> dict[str, Any] | None:
        if not isinstance(state, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,256}', state):
            return None
        with self._db() as db:
            row = db.execute('SELECT d.* FROM callbacks c JOIN devices d ON c.device_id=d.device_id '
                             'WHERE c.state_hash=? AND c.path=? AND c.expires_at>? AND d.expires_at>? '
                             'AND d.revoked_at IS NULL', (self._hash('callback', state), path,
                                                         int(self._clock()), int(self._clock()))).fetchone()
        # The provider's existing callback handler still checks/consumes its own
        # one-use state and Display PKCE. This only permits the external browser
        # to reach that handler, for a state started by this authorized device.
        if row is None:
            return None
        claims = self._owner(row['owner_uid'], row['owner_email'], row['auth_time'])
        if claims is None:
            return None
        with self._db() as db:
            live = db.execute('SELECT 1 FROM callbacks c JOIN devices d ON c.device_id=d.device_id '
                              'WHERE c.state_hash=? AND c.path=? AND c.expires_at>? AND d.expires_at>? '
                              'AND d.revoked_at IS NULL', (self._hash('callback', state), path,
                                                          int(self._clock()), int(self._clock()))).fetchone()
        return claims if live else None
