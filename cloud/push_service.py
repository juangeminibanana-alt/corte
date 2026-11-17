"""Private sale notification ledger and FCM outbox. No TikTok/API calls here.

SQLite commits the observed sale and its delivery together. FCM is contacted only
after commit. Provider acceptance is at least once: receivers deduplicate by the
stable event_id. A notification is never evidence of a settled commission.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import base64
import hashlib
import json
import logging
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any, Callable

from cryptography.fernet import Fernet

from creatorhub.errores import ErrorDominio

_log = logging.getLogger('corte.push')
_SCOPE = re.compile('[a-f0-9]{64}')
_TOKEN = re.compile(r'[A-Za-z0-9_:\-]{20,4096}')
_ID = re.compile(r'[0-9]{1,25}')
PAID_STATES = ('To-SETTLE', 'SETTLED')
ALERT_TTL_SECONDS = 24 * 3600


def _invalid() -> ErrorDominio:
    return ErrorDominio('parametros_invalidos', 'Los datos del aviso no son válidos.', http=422)


def _money(value: int | None) -> str:
    return 'no informada' if value is None else f'${value / 100:,.2f} MXN'


def paid_snapshot(hub: Any) -> dict[str, Any]:
    """Use complete committed paid orders; the legacy `valida` includes unpaid orders."""
    with hub.almacen.lector() as db:
        awaiting = [r[0] for r in db.execute("SELECT order_id FROM ordenes WHERE estado='AWAITING PAYMENT'")]
        rows = db.execute("""SELECT v.order_id,v.product_id,v.producto_nombre,v.creada_at,v.unidades_netas,
                   l.precio_centavos,l.com_estimada_centavos,l.moneda
            FROM v_lineas v JOIN ordenes o USING(order_id)
            JOIN orden_lineas l ON l.order_id=v.order_id AND l.linea_n=v.linea_n
            WHERE o.estado IN ('To-SETTLE','SETTLED') AND o.huella<>'incompleta'
              AND NOT v.es_pedido_muestra AND v.unidades_netas>0 AND l.moneda='MXN'""").fetchall()
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        oid, pid = row['order_id'], row['product_id']
        if not isinstance(oid, str) or not isinstance(pid, str) or not _ID.fullmatch(oid) or not _ID.fullmatch(pid):
            continue
        item = grouped.setdefault((oid, pid), {
            'order_id': oid, 'product_id': pid, 'nombre': str(row['producto_nombre'] or 'Producto')[:100],
            'creada_at': int(row['creada_at']), 'cantidad': 0, 'venta_centavos': 0,
            'comision_estimada_centavos': 0, 'moneda': 'MXN',
        })
        qty = max(0, int(row['unidades_netas']))
        item['cantidad'] += qty
        for target, value in (('venta_centavos', None if row['precio_centavos'] is None else row['precio_centavos'] * qty),
                              ('comision_estimada_centavos', row['com_estimada_centavos'])):
            if item[target] is not None:
                item[target] = None if value is None else item[target] + int(value)
    return {'sales': list(grouped.values()), 'awaiting': awaiting}


class PushService:
    def __init__(self, path: str, secret: str,
                 snapshot: Callable[[str], dict[str, Any]],
                 device_active: Callable[[str, str], bool],
                 send: Callable[[str, dict[str, str]], None] | None = None,
                 clock: Callable[[], float] = time.time,
                 delivery_guard: Callable[..., Any] | None = None) -> None:
        self.path, self.snapshot, self.device_active, self.send, self.clock = path, snapshot, device_active, send, clock
        self.delivery_guard = delivery_guard or (lambda *identity: nullcontext(True))
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._provider_backoff_until = 0
        key = hashlib.sha256(('corte.push.tokens.v1\0' + secret).encode()).digest()
        self._cipher = Fernet(base64.urlsafe_b64encode(key))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS subscriptions (
                    uid TEXT NOT NULL,scope TEXT NOT NULL,device TEXT NOT NULL,platform TEXT NOT NULL,
                    enabled INTEGER NOT NULL,token BLOB,token_hash TEXT,enabled_at INTEGER NOT NULL,
                    cursor INTEGER NOT NULL DEFAULT 0,updated_at INTEGER NOT NULL,
                    PRIMARY KEY(uid,scope,device));
                CREATE INDEX IF NOT EXISTS subscription_tokens ON subscriptions(token_hash);
                CREATE TABLE IF NOT EXISTS observed_sales (
                    uid TEXT NOT NULL,scope TEXT NOT NULL,device TEXT NOT NULL,
                    order_id TEXT NOT NULL,product_id TEXT NOT NULL,
                    PRIMARY KEY(uid,scope,device,order_id,product_id));
                CREATE TABLE IF NOT EXISTS awaiting_orders (
                    uid TEXT NOT NULL,scope TEXT NOT NULL,device TEXT NOT NULL,order_id TEXT NOT NULL,
                    PRIMARY KEY(uid,scope,device,order_id));
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,uid TEXT NOT NULL,scope TEXT NOT NULL,device TEXT NOT NULL,
                    order_id TEXT NOT NULL,product_id TEXT NOT NULL,at INTEGER NOT NULL,payload TEXT NOT NULL,
                    acked INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,next_at INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(uid,scope,device,order_id,product_id));
                CREATE INDEX IF NOT EXISTS events_feed ON events(uid,scope,device,id);
            ''')
        Path(path).chmod(0o600)

    @contextmanager
    def _db(self):
        with self._lock:
            db = sqlite3.connect(self.path, timeout=5)
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()

    @staticmethod
    def _identity(uid: str, scope: str, device: str) -> tuple[str, str, str]:
        if (not isinstance(uid, str) or not 1 <= len(uid) <= 128
                or not isinstance(scope, str) or _SCOPE.fullmatch(scope) is None
                or not isinstance(device, str) or re.fullmatch(r'[A-Za-z0-9_-]{24}', device) is None):
            raise _invalid()
        return uid, scope, device

    def register(self, uid: str, scope: str, device: str, body: Any) -> dict[str, Any]:
        identity = self._identity(uid, scope, device)
        if (not isinstance(body, dict) or set(body) - {'platform', 'token', 'permission'}
                or body.get('platform') not in ('android', 'windows') or body.get('permission') != 'concedido'):
            raise _invalid()
        platform, token = body['platform'], body.get('token')
        if platform == 'android':
            if not isinstance(token, str) or _TOKEN.fullmatch(token) is None:
                raise _invalid()
        elif token is not None:
            raise _invalid()
        snapshot = self.snapshot(uid)
        if snapshot.get('scope') != scope:
            raise ErrorDominio('cuenta_cambio_sin_aplicar', 'La cuenta cambió. Actualiza Corte.', http=409)
        now = int(self.clock())
        encrypted = self._cipher.encrypt(token.encode()) if token is not None else None
        fingerprint = hashlib.sha256(token.encode()).hexdigest() if token is not None else None
        with self._db() as db:
            previous = db.execute('SELECT enabled,token_hash FROM subscriptions WHERE uid=? AND scope=? AND device=?',
                                  identity).fetchone()
            activating = previous is None or not previous['enabled']
            if activating:
                # Existing paid orders are a baseline, including history fetched after initial app setup.
                db.executemany('INSERT OR IGNORE INTO observed_sales VALUES(?,?,?,?,?)',
                    [(*identity, s['order_id'], s['product_id']) for s in snapshot.get('sales', [])])
                db.executemany('INSERT OR IGNORE INTO awaiting_orders VALUES(?,?,?,?)',
                    [(*identity, oid) for oid in snapshot.get('awaiting', [])])
                cursor = db.execute('SELECT COALESCE(MAX(id),0) FROM events WHERE uid=? AND scope=? AND device=?',
                                    identity).fetchone()[0]
                db.execute("UPDATE events SET acked=1,state='disabled' WHERE uid=? AND scope=? AND device=?", identity)
                db.execute('''INSERT INTO subscriptions VALUES(?,?,?,?,1,?,?,?,?,?)
                    ON CONFLICT(uid,scope,device) DO UPDATE SET platform=excluded.platform,enabled=1,
                    token=excluded.token,token_hash=excluded.token_hash,enabled_at=excluded.enabled_at,
                    cursor=excluded.cursor,updated_at=excluded.updated_at''',
                           (*identity, platform, encrypted, fingerprint, now, cursor, now))
            else:
                db.execute('UPDATE subscriptions SET platform=?,token=?,token_hash=?,updated_at=? '
                           'WHERE uid=? AND scope=? AND device=?', (platform, encrypted, fingerprint, now, *identity))
                if fingerprint != previous['token_hash']:
                    db.execute("UPDATE events SET attempts=0,next_at=0,state='pending' WHERE uid=? AND scope=? "
                               "AND device=? AND acked=0 AND state<>'sent'", identity)
            if fingerprint:
                # A registration belongs to one authenticated device/scope at a time.
                db.execute('UPDATE subscriptions SET enabled=0,token=NULL,token_hash=NULL WHERE token_hash=? '
                           'AND NOT(uid=? AND scope=? AND device=?)', (fingerprint, *identity))
        return self.status(*identity)

    def disable(self, uid: str, device: str, scope: str | None = None) -> None:
        clause, args = 'uid=? AND device=?', (uid, device)
        if scope is not None:
            clause, args = clause + ' AND scope=?', (*args, scope)
        with self._db() as db:
            db.execute('UPDATE subscriptions SET enabled=0,token=NULL,token_hash=NULL WHERE ' + clause, args)
            db.execute("UPDATE events SET acked=1,state='disabled' WHERE " + clause, args)

    def status(self, uid: str, scope: str, device: str) -> dict[str, Any]:
        identity = self._identity(uid, scope, device)
        with self._db() as db:
            sub = db.execute('SELECT enabled,platform,cursor FROM subscriptions WHERE uid=? AND scope=? AND device=?',
                             identity).fetchone()
            unread = db.execute('SELECT count(*) FROM events WHERE uid=? AND scope=? AND device=? AND acked=0 AND at>?',
                                (*identity, int(self.clock()) - ALERT_TTL_SECONDS)).fetchone()[0]
        return {'enabled': bool(sub and sub['enabled']), 'platform': sub['platform'] if sub else None,
                'cursor': str(sub['cursor']) if sub else '0', 'unread': unread,
                'android_push_configured': self.send is not None}

    def events(self, uid: str, scope: str, device: str, after: str) -> dict[str, Any]:
        identity = self._identity(uid, scope, device)
        if not isinstance(after, str) or re.fullmatch(r'[0-9]{1,16}', after) is None or int(after) > 2**53 - 1:
            raise _invalid()
        with self._db() as db:
            sub = db.execute('SELECT enabled FROM subscriptions WHERE uid=? AND scope=? AND device=?', identity).fetchone()
            rows = db.execute('SELECT id,payload FROM events WHERE uid=? AND scope=? AND device=? '
                              'AND acked=0 AND id>? AND at>? ORDER BY id LIMIT 51',
                              (*identity, int(after), int(self.clock()) - ALERT_TTL_SECONDS)).fetchall() if sub and sub[0] else []
        selected = rows[:50]
        return {'items': [dict(json.loads(row['payload']), id=str(row['id'])) for row in selected],
                'cursor': str(selected[-1]['id']) if selected else after, 'has_more': len(rows) > 50,
                'enabled': bool(sub and sub[0])}

    def ack(self, uid: str, scope: str, device: str, body: Any) -> dict[str, Any]:
        identity = self._identity(uid, scope, device)
        ids = body.get('ids') if isinstance(body, dict) and set(body) == {'ids'} else None
        if (not isinstance(ids, list) or len(ids) > 100 or any(not isinstance(v, str)
                or re.fullmatch(r'[0-9]{1,16}', v) is None or int(v) > 2**53 - 1 for v in ids)):
            raise _invalid()
        with self._db() as db:
            db.executemany('UPDATE events SET acked=1 WHERE uid=? AND scope=? AND device=? AND id=?',
                           [(*identity, int(eid)) for eid in ids])
            first = db.execute('SELECT MIN(id) FROM events WHERE uid=? AND scope=? AND device=? AND acked=0',
                               identity).fetchone()[0]
            cursor = db.execute('SELECT COALESCE(MAX(id),0) FROM events WHERE uid=? AND scope=? AND device=? '
                                'AND acked=1 AND (? IS NULL OR id<?)', (*identity, first, first)).fetchone()[0]
            db.execute('UPDATE subscriptions SET cursor=MAX(cursor,?) WHERE uid=? AND scope=? AND device=?',
                       (cursor, *identity))
        return self.status(*identity)

    def tick(self) -> None:
        now = int(self.clock())
        with self._db() as db:
            # Expire notification deliveries only; sales in the hub are untouched.
            db.execute("UPDATE events SET state='expired',acked=1 WHERE at<=? AND state<>'expired'",
                       (now - ALERT_TTL_SECONDS,))
            subscriptions = [dict(r) for r in db.execute('SELECT * FROM subscriptions WHERE enabled=1')]
        snapshots: dict[str, dict[str, Any]] = {}
        for sub in subscriptions:
            identity = sub['uid'], sub['scope'], sub['device']
            if not self.device_active(sub['uid'], sub['device']):
                self.disable(sub['uid'], sub['device'])
                continue
            if sub['uid'] not in snapshots:
                snapshots[sub['uid']] = self.snapshot(sub['uid'])
            snapshot = snapshots[sub['uid']]
            if snapshot.get('scope') != sub['scope']:
                self.disable(sub['uid'], sub['device'], sub['scope'])
                continue
            with self._db() as db:
                live = db.execute('SELECT enabled FROM subscriptions WHERE uid=? AND scope=? AND device=?', identity).fetchone()
                if not live or not live[0]:
                    continue
                db.executemany('INSERT OR IGNORE INTO awaiting_orders VALUES(?,?,?,?)',
                               [(*identity, oid) for oid in snapshot.get('awaiting', [])])
                awaiting = {r[0] for r in db.execute('SELECT order_id FROM awaiting_orders WHERE uid=? AND scope=? AND device=?', identity)}
                for sale in snapshot.get('sales', []):
                    if sale['creada_at'] > now + 300:
                        continue
                    key = (*identity, sale['order_id'], sale['product_id'])
                    fresh = db.execute('INSERT OR IGNORE INTO observed_sales VALUES(?,?,?,?,?)', key).rowcount
                    if not fresh:
                        continue
                    # Previously unknown historical rows are not a new sale. A known unpaid order may become paid later.
                    if sale['creada_at'] < sub['enabled_at'] and sale['order_id'] not in awaiting:
                        continue
                    nombre = re.sub(r'[\x00-\x1f\x7f]', ' ', str(sale.get('nombre') or 'Producto'))[:100]
                    qty = int(sale['cantidad'])
                    if qty <= 0:
                        continue
                    payload = {**sale, 'titulo': 'Nueva venta en TikTok Shop',
                        'texto': f'{nombre} · {qty} {"unidad" if qty == 1 else "unidades"} · Venta {_money(sale.get("venta_centavos"))}. '
                                 f'Comisión estimada {_money(sale.get("comision_estimada_centavos"))}.',
                        'ruta': '#/ventas', 'at': now}
                    db.execute('INSERT OR IGNORE INTO events(uid,scope,device,order_id,product_id,at,payload) VALUES(?,?,?,?,?,?,?)',
                               (*key, now, json.dumps(payload, ensure_ascii=False, separators=(',', ':'))))
        self._send_due(now)

    def _send_due(self, now: int) -> None:
        if self.send is None or now < self._provider_backoff_until:
            return
        with self._db() as db:
            due = [dict(r) for r in db.execute('''SELECT e.*,s.token FROM events e JOIN subscriptions s
                ON e.uid=s.uid AND e.scope=s.scope AND e.device=s.device
                WHERE s.enabled=1 AND s.platform='android' AND s.token IS NOT NULL AND e.acked=0
                  AND e.state IN ('pending','retry','sending') AND e.next_at<=? AND e.at>?
                ORDER BY e.id LIMIT 20''', (now, now - ALERT_TTL_SECONDS))]
        batch_limit = time.monotonic() + 12
        for event in due:
            if now < self._provider_backoff_until or time.monotonic() + 10 > batch_limit:
                break
            identity = event['uid'], event['scope'], event['device']
            # Fresh identity validation may contact Google Auth; do it before
            # taking the creator-mutation lock. Native revoke then clears the
            # subscription under that same lock before the state recheck below.
            if not self.device_active(event['uid'], event['device']):
                self.disable(event['uid'], event['device'], event['scope'])
                continue
            # Production holds the same creator/revocation lock from identity
            # validation through provider acceptance. No SQLite transaction spans the send.
            with self.delivery_guard(*identity) as allowed:
                if not allowed:
                    self.disable(event['uid'], event['device'], event['scope'])
                    continue
                with self._db() as db:
                    send_now = int(self.clock())
                    if event['at'] <= send_now - ALERT_TTL_SECONDS:
                        db.execute("UPDATE events SET state='expired',acked=1 WHERE id=?", (event['id'],))
                        continue
                    live_token = db.execute('SELECT token,token_hash FROM subscriptions WHERE uid=? AND scope=? '
                                            'AND device=? AND enabled=1', identity).fetchone()
                    if live_token is None or live_token['token'] is None:
                        continue
                    claimed = db.execute("UPDATE events SET state='sending',next_at=? WHERE id=? AND acked=0 AND next_at<=? "
                        'AND EXISTS(SELECT 1 FROM subscriptions WHERE uid=? AND scope=? AND device=? AND enabled=1)',
                        (now + 60, event['id'], now, *identity)).rowcount
                if not claimed:
                    continue
                payload = json.loads(event['payload'])
                data = {'type': 'sale', 'event_id': str(event['id']), 'cache_scope': event['scope'],
                        'titulo': payload['titulo'], 'texto': payload['texto'], 'ruta': '#/ventas',
                        'order_id': event['order_id'], 'product_id': event['product_id'],
                        'expires_at': str(event['at'] + ALERT_TTL_SECONDS)}
                try:
                    token = self._cipher.decrypt(live_token['token']).decode('utf-8')
                    self.send(token, data)
                except ExpiredNotification:
                    with self._db() as db:
                        db.execute("UPDATE events SET state='expired',acked=1 WHERE id=?", (event['id'],))
                except Exception as error:
                    permanent = type(error).__name__ in ('UnregisteredError', 'SenderIdMismatchError')
                    if permanent:
                        # A stale provider response must not disable a freshly rotated token.
                        with self._db() as db:
                            current = db.execute('SELECT token_hash FROM subscriptions WHERE uid=? AND scope=? AND device=?',
                                                 identity).fetchone()
                            if current is not None and current[0] == live_token['token_hash']:
                                db.execute('UPDATE subscriptions SET enabled=0,token=NULL,token_hash=NULL '
                                           'WHERE uid=? AND scope=? AND device=?', identity)
                                db.execute("UPDATE events SET acked=1,state='disabled' WHERE uid=? AND scope=? AND device=?", identity)
                            else:
                                db.execute("UPDATE events SET state='retry',next_at=? WHERE id=? AND acked=0", (now, event['id']))
                    else:
                        self._provider_backoff_until = now + 30
                        delay = min(3600, 30 * 2 ** min(event['attempts'], 7))
                        with self._db() as db:
                            db.execute("UPDATE events SET state='retry',attempts=attempts+1,next_at=? WHERE id=? AND acked=0",
                                       (now + delay, event['id']))
                    _log.warning('Sale push provider failed (%s)', type(error).__name__)
                else:
                    with self._db() as db:
                        db.execute("UPDATE events SET state='sent',attempts=attempts+1 WHERE id=? AND acked=0", (event['id'],))

    def start(self) -> None:
        if self._thread is not None:
            return
        def loop() -> None:
            while not self._stop.wait(15):
                try:
                    self.tick()
                except Exception as error:
                    _log.warning('Sale push update unavailable (%s)', type(error).__name__)
        self._thread = threading.Thread(target=loop, name='corte-sale-push', daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)


class UnregisteredError(Exception):
    pass


class SenderIdMismatchError(Exception):
    pass


class ExpiredNotification(Exception):
    pass


def firebase_sender(firebase: Any) -> Callable[[str, dict[str, str]], None]:
    """Official FCM HTTP v1 with Firebase's ADC, bounded I/O and no hidden retries.

    Admin SDK's public send() has no per-call retry setting and its default
    transport retries 500/503 up to four times. This transport leaves retrying to
    our durable outbox instead of holding the creator lock for those retries.
    """
    def send(token: str, data: dict[str, str]) -> None:
        import requests
        from google.auth.credentials import with_scopes_if_required
        from google.auth.transport.requests import AuthorizedSession, Request
        project = firebase.app.project_id
        if not isinstance(project, str) or re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]', project) is None:
            raise RuntimeError('FCM project configuration unavailable')
        credential = with_scopes_if_required(firebase.app.credential.get_credential(),
                                             ['https://www.googleapis.com/auth/firebase.messaging'])
        deadline = time.monotonic() + 10
        expires = data.get('expires_at')
        ttl = min(ALERT_TTL_SECONDS, max(0, int(expires) - int(time.time()))) if expires is not None else ALERT_TTL_SECONDS
        if ttl <= 0:
            raise ExpiredNotification()
        with requests.Session() as auth_session:
            auth_session.trust_env = False
            auth_session.mount('https://', requests.adapters.HTTPAdapter(max_retries=0))
            request = Request(session=auth_session)
            def bounded_auth_request(*args, **kwargs):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise requests.Timeout('FCM authorization deadline')
                kwargs['timeout'] = min(3, remaining)
                return request(*args, **kwargs)
            with AuthorizedSession(credential, max_refresh_attempts=0, refresh_timeout=3,
                                   auth_request=bounded_auth_request) as session:
                session.trust_env = False
                session.mount('https://', requests.adapters.HTTPAdapter(max_retries=0))
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise requests.Timeout('FCM send deadline')
                response = session.post(f'https://fcm.googleapis.com/v1/projects/{project}/messages:send',
                    json={'message': {'token': token, 'data': data, 'android': {'priority': 'HIGH', 'ttl': f'{ttl}s'}}},
                    timeout=(min(2, remaining), min(5, remaining)), max_allowed_time=remaining, allow_redirects=False)
                try:
                    if time.monotonic() > deadline:
                        raise requests.Timeout('FCM send deadline')
                    if response.status_code == 200:
                        return
                    try:
                        details = response.json().get('error', {}).get('details', [])
                        code = next((d.get('errorCode') for d in details if isinstance(d, dict)
                                     and d.get('@type') == 'type.googleapis.com/google.firebase.fcm.v1.FcmError'), None)
                    except (ValueError, TypeError, AttributeError):
                        code = None
                    if code == 'UNREGISTERED':
                        raise UnregisteredError()
                    if code == 'SENDER_ID_MISMATCH':
                        raise SenderIdMismatchError()
                    raise RuntimeError('FCM provider unavailable')
                finally:
                    response.close()
    return send
