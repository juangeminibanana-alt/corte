"""Corte privado en HTTPS. El hub conserva sincronización, analítica y SQLite.

Arrancar con: gunicorn -c cloud/gunicorn.conf.py 'cloud.app:create_app()'
Un proceso y varios hilos: las renovaciones OAuth y el planificador tienen un dueño.
"""
from __future__ import annotations

import atexit
import collections
import gzip
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time
from dataclasses import dataclass
from contextlib import contextmanager
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from flask import Flask, Response, g, jsonify, redirect, request, send_file, session, stream_with_context
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'hub'))

from creatorhub.api.estaticos import Estaticos
from creatorhub.api.rutas_display import crear_despachador_display, es_ruta_display
from creatorhub.api.seguridad import CSP_WINDOWS
from creatorhub.api.sse import formatear
from creatorhub.comun import fecha_local
from creatorhub.errores import ErrorDominio
from creatorhub.interfaces import CTX_UI, OpcionesHub
from creatorhub.tiktok_dev.servicio import pagina_html
from cloud.native_auth import BEARER_RE, NativeAuth, NativeAuthError
from cloud.firebase_service import FirebaseAccessError


@dataclass(frozen=True)
class Settings:
    public_url: str
    session_secret: str
    password_hash: str
    data_dir: str
    ui_dir: str
    allow_http: bool = False
    trust_proxy: bool = False
    auth_provider: str = 'password'
    proxy_hops: int = 1

    @classmethod
    def from_env(cls) -> 'Settings':
        public_url = os.environ.get('CORTE_PUBLIC_URL', '').rstrip('/')
        public = urlsplit(public_url)
        allow_http = os.environ.get('CORTE_ALLOW_HTTP') == '1'
        local = public.hostname in ('localhost', '127.0.0.1', '::1')
        if (not public.hostname or public.username or public.password or public.path or public.query or public.fragment
                or (public.scheme != 'https' and not (allow_http and local and public.scheme == 'http'))):
            raise ValueError('Configura CORTE_PUBLIC_URL con el origen HTTPS de tu servicio.')
        session_secret = os.environ.get('CORTE_SESSION_SECRET', '')
        password_hash = os.environ.get('CORTE_PASSWORD_HASH', '')
        provider = os.environ.get('CORTE_AUTH_PROVIDER', 'firebase')
        proxy_hops = int(os.environ.get('CORTE_PROXY_HOPS', '1'))
        if proxy_hops not in (1, 2):
            raise ValueError('CORTE_PROXY_HOPS debe ser 1 o 2 para la topología documentada.')
        if len(session_secret) < 32:
            raise ValueError('Falta CORTE_SESSION_SECRET (al menos 32 caracteres aleatorios).')
        if provider not in ('firebase', 'password'):
            raise ValueError('CORTE_AUTH_PROVIDER debe ser firebase o password.')
        if provider == 'password' and (not password_hash.startswith(('scrypt:', 'pbkdf2:sha256:')) or password_hash.count('$') != 2):
            raise ValueError('Falta CORTE_PASSWORD_HASH. Genéralo con python -m cloud.setup.')
        if len(os.environ.get('CORTE_ENCRYPTION_KEY', '')) < 32:
            raise ValueError('Falta CORTE_ENCRYPTION_KEY (al menos 32 caracteres aleatorios).')
        return cls(public_url, session_secret, password_hash,
                   os.environ.get('CORTE_DATA_DIR', '/var/lib/corte'),
                   os.environ.get('CORTE_UI_DIR', str(ROOT / 'ui' / 'dist')),
                   allow_http, os.environ.get('CORTE_TRUST_PROXY') == '1', provider, proxy_hops)


class LoginLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._attempts: dict[str, collections.deque[float]] = {}

    def allow(self, address: str) -> bool:
        now = time.monotonic()
        with self._lock:
            self._attempts = {k: v for k, v in self._attempts.items() if v and v[-1] > now - 900}
            # Bound memory, and enforce a process-wide budget as well as the IP budget.
            if address not in self._attempts and len(self._attempts) >= 1024:
                return False
            own = self._attempts.setdefault(address, collections.deque())
            total = self._attempts.setdefault('*', collections.deque())
            for bucket in (own, total):
                while bucket and bucket[0] <= now - 900:
                    bucket.popleft()
            if len(own) >= 10 or len(total) >= 60:
                return False
            own.append(now)
            total.append(now)
            return True


def opaque_client_scopes(claims: Any, creator: Any = None) -> dict[str, str]:
    """Opaque cache namespaces, bound to verified Google identity and creator."""
    uid = (claims.get('uid') or claims.get('sub')) if isinstance(claims, dict) else None
    if not isinstance(uid, str) or not uid:
        return {}
    scopes = {'owner_scope': hashlib.sha256(('corte-owner:' + uid).encode('utf-8')).hexdigest()}
    if isinstance(creator, str) and creator:
        scopes['cache_scope'] = hashlib.sha256(('corte-cache-v1\0' + uid + '\0' + creator).encode('utf-8')).hexdigest()
    return scopes


def create_app(settings: Settings | None = None, hub: Any = None, firebase: Any = None, push: Any = None) -> Flask:
    owned_hub = hub is None
    settings = settings or Settings.from_env()
    app = Flask(__name__, static_folder=None)
    if settings.auth_provider == 'firebase' and firebase is None:
        from cloud.firebase_service import FirebaseServices
        firebase = FirebaseServices()
    public = urlsplit(settings.public_url)
    app.config.update(SECRET_KEY=settings.session_secret, SESSION_COOKIE_NAME='corte_session',
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SECURE=not settings.allow_http,
                      SESSION_COOKIE_SAMESITE='Lax', PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
                      SESSION_REFRESH_EACH_REQUEST=False, MAX_CONTENT_LENGTH=20 * 1024 * 1024,
                      TRUSTED_HOSTS=[public.hostname])
    if settings.trust_proxy:
        # Production's gateway normalizes one hop; direct VM ingress is blocked by firewall.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=settings.proxy_hops, x_proto=1, x_host=0, x_port=0, x_prefix=0)
    if hub is None:
        from creatorhub.hub import iniciar_hub
        hub = iniciar_hub(OpcionesHub(modo='real', nube=True, sin_lan=True,
                                      raiz_datos=settings.data_dir, dir_ui=settings.ui_dir))
        atexit.register(hub.detener, 35.0)
    app.extensions['corte_hub'] = hub
    display = crear_despachador_display(hub)
    static = Estaticos(settings.ui_dir)
    limiter = LoginLimiter()
    streams = threading.BoundedSemaphore(8)
    auth_version = hashlib.sha256(settings.password_hash.encode('utf-8')).hexdigest()

    def native_owner(uid: str, email: str, auth_time: int) -> dict[str, Any] | None:
        if settings.auth_provider != 'firebase':
            return None
        try:
            user = firebase.auth.get_user(uid, app=firebase.app)
        except Exception as exc:
            not_found = getattr(firebase.auth, 'UserNotFoundError', None)
            if isinstance(not_found, type) and isinstance(exc, not_found):
                return None
            # A temporary provider outage must not look like a revoked device:
            # clients keep their encrypted credential and retry on 503.
            raise NativeAuthError('identidad_no_disponible',
                                  'No pudimos comprobar tu cuenta. Conserva la conexión y vuelve a intentarlo.', 503) from None
        try:
            if (user.disabled or not user.email_verified or not isinstance(user.email, str)
                    or user.email.lower() != email.lower()
                    or user.tokens_valid_after_timestamp / 1000 > auth_time
                    or not any(p.provider_id == 'google.com' for p in user.provider_data)):
                return None
            claims = {'uid': uid, 'sub': uid, 'email': user.email, 'email_verified': True,
                      'auth_time': auth_time, 'firebase': {'sign_in_provider': 'google.com'}}
            return claims if firebase.allowed(claims) else None
        except Exception:
            # Malformed identity records fail closed, without upstream details.
            return None

    native = NativeAuth(str(Path(settings.data_dir) / 'native.sqlite'), settings.session_secret,
                        settings.public_url, native_owner) if settings.auth_provider == 'firebase' else None
    app.extensions['corte_native'] = native

    if push is None and owned_hub and native is not None:
        from cloud.push_service import PushService, firebase_sender, paid_snapshot

        def push_snapshot(uid: str) -> dict[str, Any]:
            with hub._candado_mutacion:
                stored = hub.boveda.leer()
                creator = stored.get('open_id') if isinstance(stored, dict) else None
                result = paid_snapshot(hub)
                result['scope'] = opaque_client_scopes({'uid': uid}, creator).get('cache_scope')
                return result

        def push_device_active(uid: str, device_id: str) -> bool:
            return native.device_active(uid, device_id)

        @contextmanager
        def push_delivery_guard(uid: str, scope: str, device_id: str):
            with hub._candado_mutacion:
                stored = hub.boveda.leer()
                creator = stored.get('open_id') if isinstance(stored, dict) else None
                current = opaque_client_scopes({'uid': uid}, creator).get('cache_scope')
                yield current == scope

        push = PushService(str(Path(settings.data_dir) / 'push.sqlite'), settings.session_secret,
                           push_snapshot, push_device_active, firebase_sender(firebase),
                           delivery_guard=push_delivery_guard)
        push.start()
        atexit.register(push.close)
    app.extensions['corte_push'] = push
    from cloud.push_routes import install_push_routes
    install_push_routes(app, push, hub, native, opaque_client_scopes)

    def authenticated() -> bool:
        if settings.auth_provider == 'firebase':
            if not hasattr(g, 'firebase_claims'):
                cookie = request.cookies.get('__session')
                g.firebase_claims = firebase.verify_session(cookie) if cookie else None
            return g.firebase_claims is not None
        version = session.get('auth_version')
        return isinstance(version, str) and hmac.compare_digest(version, auth_version)

    def error(code: str, message: str, status: int) -> tuple[Response, int]:
        return jsonify(error={'codigo': code, 'mensaje': message}), status

    @app.before_request
    def protect() -> Any:
        request.max_content_length = 20 * 1024 * 1024 if request.path == '/api/cloud/import' else 256 * 1024
        if request.path == '/api/native/auth/google':
            request.max_content_length = 18 * 1024
        elif request.path.startswith('/api/native/'):
            request.max_content_length = 4096
        # Private readiness checks use HTTP to the backend with the configured domain Host.
        # This endpoint exposes only readiness; private API routes still require HTTPS/auth.
        if request.path == '/api/health' and request.method in ('GET', 'HEAD'):
            return None
        if request.host.lower() != public.netloc.lower():
            return error('origen_invalido', 'Esta dirección no corresponde a Corte.', 421)
        if not settings.allow_http and not request.is_secure:
            return error('https_requerido', 'Abre Corte con su dirección HTTPS.', 400)
        g.native_actor = None
        authorization = request.headers.get('Authorization')
        if authorization:
            match = BEARER_RE.fullmatch(authorization)
            actor = native.authenticate(match[1]) if match and native else None
            if actor is None:
                return error('sesion_nativa_invalida', 'Vuelve a conectar esta app con tu cuenta de Corte.', 401)
            if (request.path in ('/api/cloud/login', '/api/cloud/logout', '/api/cloud/session', '/api/cloud/config')
                    or request.path.startswith('/api/native/') and request.path not in
                    ('/api/native/session', '/api/native/devices/self/revoke')):
                return error('solo_navegador', 'Administra las autorizaciones desde tu navegador.', 403)
            g.native_actor, g.firebase_claims = actor, actor['claims']
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            if request.headers.get('Origin') != settings.public_url or request.headers.get('X-CH-Hub') != '1':
                return error('origen_invalido', 'La solicitud debe venir de Corte.', 403)
            if request.data and request.mimetype != 'application/json':
                return error('formato_invalido', 'Envía los datos en formato JSON.', 415)
        public_paths = ('/api/cloud/session', '/api/cloud/config', '/api/cloud/login', '/api/health',
                        '/api/native/auth/start', '/api/native/auth/poll', '/api/native/auth/google')
        if (request.path.startswith(('/api/', '/img/', '/oauth/')) and request.path not in public_paths
                and not authenticated()):
            if (native and request.method == 'GET' and request.path in ('/oauth/shop', '/oauth/tiktok')
                    and len(request.args) <= 16 and len(request.args.getlist('state')) == 1):
                claims = native.callback_owner(request.args.get('state', ''), request.path)
                if claims is not None:
                    g.firebase_claims = claims
                    return None
            return error('sesion_requerida', 'Inicia sesión para continuar.', 401)

    @app.errorhandler(NativeAuthError)
    def native_error(exc: NativeAuthError) -> Any:
        response, status = error(exc.code, exc.message, exc.status)
        if exc.retry_after:
            response.headers['Retry-After'] = str(exc.retry_after)
        return response, status

    def require_native_service() -> NativeAuth:
        if native is None:
            raise NativeAuthError('no_disponible', 'El acceso de dispositivos requiere Google en Corte Cloud.', 409)
        return native

    @app.post('/api/native/auth/start')
    def native_start() -> Any:
        service = require_native_service()
        service.limit('start', request.remote_addr or 'unknown')
        return jsonify(service.start(request.get_json()))

    @app.post('/api/native/auth/poll')
    def native_poll() -> Any:
        service = require_native_service()
        service.limit('poll', request.remote_addr or 'unknown')
        result, status = service.poll(request.get_json())
        return jsonify(result), status

    @app.post('/api/native/auth/google')
    def native_google() -> Any:
        service = require_native_service()
        service.limit('google', request.remote_addr or 'unknown')
        try:
            grant = service.exchange_google(request.get_json(silent=True), firebase.verify_recent_google)
        except FirebaseAccessError:
            return error('cuenta_no_autorizada', 'Esta cuenta de Google no tiene acceso a Corte.', 401)
        return jsonify(grant)

    @app.get('/api/native/auth/request')
    def native_request() -> Any:
        service = require_native_service()
        service.limit('owner', request.remote_addr or 'unknown')
        return jsonify(service.describe(request.args.get('codigo')))

    @app.post('/api/native/auth/approve')
    @app.post('/api/native/auth/deny')
    def native_decide() -> Any:
        service = require_native_service()
        service.limit('owner', request.remote_addr or 'unknown')
        return jsonify(service.decide(request.get_json(), g.firebase_claims, request.path.endswith('/approve')))

    @app.get('/api/native/session')
    def native_session() -> Any:
        actor = g.native_actor
        if actor is None:
            return error('sesion_nativa_requerida', 'Abre este acceso desde la app de Corte.', 401)
        # Native broker uses the provider's stable identity to guard optional
        # legacy-data migration. It must never forward this identity to JS.
        stored = hub.boveda.leer()
        account = hub.auth.cuenta()
        identity = stored.get('open_id') if isinstance(stored, dict) else None
        username = account.get('username') if isinstance(account, dict) else None
        return jsonify(authenticated=True, device_id=actor['device_id'], expires_at=actor['expires_at'],
                       owner={'uid': actor['claims']['uid'], 'email': actor['claims']['email']},
                       **opaque_client_scopes(actor['claims'], identity),
                       **({'tiktok_open_id': identity} if isinstance(identity, str) and identity else {}),
                       **({'username': username} if isinstance(username, str) and username else {}))

    @app.get('/api/native/devices')
    def native_devices() -> Any:
        return jsonify(devices=require_native_service().devices(g.firebase_claims['uid']))

    @app.post('/api/native/devices/<device_id>/revoke')
    def native_revoke(device_id: str) -> Any:
        service = require_native_service()
        if device_id == 'self':
            if not g.native_actor:
                return error('sesion_nativa_requerida', 'Abre este acceso desde la app de Corte.', 401)
            device_id = g.native_actor['device_id']
        with hub._candado_mutacion:
            if not service.revoke(g.firebase_claims['uid'], device_id):
                return error('no_encontrado', 'No encontramos ese dispositivo.', 404)
            if push is not None:
                push.disable(g.firebase_claims['uid'], device_id)
        return jsonify(revoked=True)

    @app.after_request
    def headers(response: Response) -> Response:
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        csp = CSP_WINDOWS
        if settings.auth_provider == 'firebase':
            domain = firebase.web_config['authDomain']
            csp = csp.replace("script-src 'self'", "script-src 'self' https://apis.google.com https://www.gstatic.com")
            csp = csp.replace("connect-src 'self'", "connect-src 'self' https://identitytoolkit.googleapis.com "
                              "https://securetoken.googleapis.com https://www.googleapis.com https://" + domain)
            csp = csp.replace('frame-src https://www.tiktok.com',
                              'frame-src https://www.tiktok.com https://' + domain)
        response.headers['Content-Security-Policy'] = csp
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        if not settings.allow_http:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        if request.path.startswith(('/api/', '/img/', '/oauth/')):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(413)
    def too_large(_error: Any) -> Any:
        return error('cuerpo_demasiado_grande', 'El archivo o los datos superan el límite permitido.', 413)

    @app.errorhandler(400)
    def invalid_request(_error: Any) -> Any:
        return error('solicitud_invalida', 'La solicitud no es válida.', 400)

    @app.get('/api/health')
    def health() -> Any:
        try:
            healthy = bool(hub.salud().get('db_ok'))
        except Exception:
            healthy = False
        return jsonify(ok=healthy, cloud=True), 200 if healthy else 503

    @app.get('/api/cloud/session')
    def cloud_session() -> Any:
        active = authenticated()
        scopes = {}
        if active and isinstance(getattr(g, 'firebase_claims', None), dict):
            with hub._candado_mutacion:
                stored = hub.boveda.leer()
                creator = stored.get('open_id') if isinstance(stored, dict) else None
                scopes = opaque_client_scopes(getattr(g, 'firebase_claims', None), creator)
        return jsonify(cloud=True, authenticated=active, **scopes)

    @app.get('/api/cloud/config')
    def cloud_config() -> Any:
        result = {'auth_provider': settings.auth_provider}
        if settings.auth_provider == 'firebase':
            result['firebase'] = firebase.web_config
        return jsonify(result)

    @app.get('/api/cloud/revision')
    def cloud_revision() -> Any:
        sync = hub.sincronizador.estado()
        # Sales and the calendar depend on the Mexican day. Within that day,
        # use only stable state so polling does not force constant refreshes.
        state = {
            'fecha_mx': fecha_local(hub.reloj.ahora()),
            'versiones': list(hub.almacen.versiones()),
            'conexion': hub.auth.conexion(),
            'display': hub.display.estado() if hub.display is not None else None,
            # Progress has its own response field; it should update progress UI
            # without invalidating every table on each 3-second active-sync poll.
            'sync': {key: sync.get(key) for key in ('en_curso', 'sync_id', 'ultima_estado', 'ultima_ok_at', 'ultimo_error')},
        }
        scopes = {}
        if isinstance(getattr(g, 'firebase_claims', None), dict):
            with hub._candado_mutacion:
                stored = hub.boveda.leer()
                creator = stored.get('open_id') if isinstance(stored, dict) else None
                scopes = opaque_client_scopes(g.firebase_claims, creator)
        state['cache_scope'] = scopes.get('cache_scope')
        revision = hashlib.sha256(json.dumps(state, sort_keys=True, separators=(',', ':'),
                                             ensure_ascii=False).encode('utf-8')).hexdigest()
        return jsonify(revision=revision, sync=sync, **scopes)

    @app.post('/api/cloud/login')
    def login() -> Any:
        if not limiter.allow(request.remote_addr or 'unknown'):
            response, status = error('demasiados_intentos', 'Espera 15 minutos antes de volver a intentarlo.', 429)
            response.headers['Retry-After'] = '900'
            return response, status
        body = request.get_json(silent=True)
        if settings.auth_provider == 'firebase':
            token = body.get('id_token') if isinstance(body, dict) else None
            if not isinstance(token, str) or not 20 <= len(token) <= 16384:
                return error('sesion_google_invalida', 'Vuelve a iniciar sesión con Google.', 401)
            try:
                cookie = firebase.create_session(token)
            except Exception:
                return error('cuenta_no_autorizada', 'Esta cuenta de Google no tiene acceso a Corte.', 401)
            response = jsonify(authenticated=True)
            response.set_cookie('__session', cookie, max_age=12 * 3600, httponly=True,
                                secure=not settings.allow_http, samesite='Lax', path='/')
            return response
        password = body.get('password') if isinstance(body, dict) else None
        if (not isinstance(password, str) or not 1 <= len(password) <= 1024
                or not check_password_hash(settings.password_hash, password)):
            return error('clave_incorrecta', 'La contraseña no es correcta.', 401)
        session.clear()
        session.permanent = True
        session['auth_version'] = auth_version
        session['nonce'] = secrets.token_hex(16)
        return jsonify(authenticated=True)

    @app.post('/api/cloud/logout')
    def logout() -> Any:
        if settings.auth_provider == 'firebase':
            # Revoke only this Corte cookie, preserving other apps in the shared Firebase project.
            try:
                firebase.revoke(g.firebase_claims, request.cookies.get('__session', ''))
            except Exception:
                return error('servicio_no_disponible', 'No pudimos cerrar la sesión. Inténtalo de nuevo.', 503)
        if settings.auth_provider == 'password':
            session.clear()
        response = jsonify(authenticated=False)
        if settings.auth_provider == 'firebase':
            response.delete_cookie('__session', secure=not settings.allow_http, httponly=True, samesite='Lax')
        return response

    @app.get('/api/events')
    def events() -> Any:
        if not streams.acquire(blocking=False):
            return error('demasiadas_conexiones', 'Cierra otra pestaña de Corte e inténtalo de nuevo.', 429)
        @stream_with_context
        def generate() -> Any:
            sub = hub.bus.suscribir(100)
            # Periodic reconnect revalidates the signed browser session.
            deadline = time.monotonic() + 50
            try:
                yield b'retry: 3000\n\n'
                while time.monotonic() < deadline and not hub._parar.is_set():
                    event = sub.siguiente(min(5, max(0, deadline - time.monotonic())))
                    if event is not None:
                        yield formatear(event)
                    elif getattr(sub, 'cerrada', False):
                        break
                    else:
                        yield formatear({'tipo': 'ping', 't': hub.reloj.ahora()})
            finally:
                sub.cerrar()
                streams.release()
        return Response(generate(), mimetype='text/event-stream', headers={'X-Accel-Buffering': 'no'})

    @app.get('/oauth/tiktok')
    def display_callback() -> Any:
        status, body = hub.callback_oauth(request.query_string.decode('utf-8', errors='replace'))
        return Response(body, status=status, mimetype='text/html')

    @app.get('/oauth/shop')
    def shop_callback() -> Any:
        # The state is checked and consumed by the existing auth service.
        if not request.args.get('state') or len(request.args) > 16:
            return Response(pagina_html('Este intento de conexión no es válido. Vuelve a Corte.', False),
                            status=400, mimetype='text/html')
        try:
            hub.auth.canjear({'url_o_codigo': settings.public_url + request.full_path})
            hub.encolar_avatar()
            hub.sincronizar_tras_conectar()
        except ErrorDominio as exc:
            # Sanitized domain messages only; never reflect code/state or external errors.
            return Response(pagina_html(exc.mensaje, False), status=exc.http, mimetype='text/html')
        return redirect('/#/inicio', code=303)

    @app.post('/api/cloud/tiktok/import')
    def shop_import() -> Any:
        if request.content_length is not None and request.content_length > 64 * 1024:
            return error('cuerpo_demasiado_grande', 'El archivo de conexión supera el límite permitido.', 413)
        body = request.get_data(cache=True)
        if len(body) > 64 * 1024:
            return error('cuerpo_demasiado_grande', 'El archivo de conexión supera el límite permitido.', 413)
        try:
            result = hub.auth.importar_credenciales_nube(request.get_json())
            revision = result.pop('_revision_credenciales')
            result['sync_iniciada'] = False
            if result['verificacion'] == 'ok':
                # Serialize against disconnect/account changes without holding
                # the vault lock while starting the synchronization thread.
                with hub._candado_mutacion:
                    actual = hub.boveda.leer()
                    if (actual.get('app_key'), actual.get('epoca_credenciales', 0)) != revision:
                        raise ErrorDominio('credenciales_cambiaron', 'La conexión cambió antes de sincronizar. '
                                           'Revisa la cuenta actual e inténtalo de nuevo.', http=409)
                    hub.encolar_avatar()
                    hub.sincronizador.iniciar('completa', 'usuario')
                    result['sync_iniciada'] = True
            return jsonify(result)
        except ErrorDominio as exc:
            return jsonify(exc.a_respuesta(hub.secretos_vivos())), exc.http

    @app.put('/api/cloud/tiktok/credentials')
    def shop_credentials() -> Any:
        body = request.get_json()
        if not isinstance(body, dict) or set(body) != {'app_key', 'app_secret'}:
            return error('parametros_invalidos', 'Escribe el App Key y el App Secret de la misma app de Partner Center.',
                         422)
        try:
            return jsonify(hub.auth.guardar_credenciales_app(body['app_key'], body['app_secret']))
        except ErrorDominio as exc:
            # A validation error must never echo submitted credentials.
            return jsonify(exc.a_respuesta(hub.secretos_vivos())), exc.http

    @app.post('/api/cloud/display/import')
    def display_import() -> Any:
        if len(request.get_data(cache=True)) > 64 * 1024:
            return error('cuerpo_demasiado_grande', 'El archivo de conexión de videos supera el límite permitido.', 413)
        from cloud.display_import import import_display, _shop_identity
        try:
            result = import_display(hub, request.get_json())
            revision = result.pop('_revision')
            shop_revision = result.pop('_shop_revision')
            result['sync_iniciada'] = False
            with hub._candado_mutacion:
                if _shop_identity(hub) != shop_revision:
                    return error('credenciales_cambiaron', 'La cuenta de TikTok Shop cambió antes de sincronizar. Revisa su estado.', 409)
                actual = hub.display.boveda.leer()
                if (actual.get('client_key'), actual.get('open_id'), actual.get('epoca_credenciales', 0)) != revision:
                    return error('credenciales_cambiaron', 'La conexión de videos cambió antes de sincronizar. Revisa su estado.', 409)
                started = hub.sincronizador.iniciar('incremental', 'usuario')
                result['sync_iniciada'] = not started.get('ya_en_curso', False)
                result['sync_en_curso'] = bool(started.get('ya_en_curso', False))
                result['display'] = hub.display.estado()
            return jsonify(result)
        except ErrorDominio as exc:
            # New credentials may not yet belong to secretos_vivos; never
            # include submitted values, upstream details, or log identifiers.
            return error(exc.codigo, exc.mensaje, exc.http)
        except Exception:
            return error('servicio_no_disponible', 'No pudimos completar la recuperación. Revisa el estado de la '
                         'conexión antes de volver a intentarlo.', 503)

    @app.post('/api/cloud/import')
    def import_local() -> Any:
        try:
            data = request.get_json()
            if g.native_actor:
                expected = request.headers.get('X-Corte-Expected-Creator')
                if (not isinstance(expected, str) or not 1 <= len(expected) <= 256
                        or any(not 33 <= ord(c) <= 126 for c in expected)):
                    return error('cuenta_cambio_sin_importar',
                                 'Conecta tu cuenta de TikTok y vuelve a iniciar la importación desde esta app.', 409)
                # Credential/account mutations take this same RLock. Never hold
                # the vault lock across an import: read it after acquiring the
                # coordinator, then let the normal SQLite writer import while
                # account changes remain excluded. No network call occurs here.
                with hub._candado_mutacion:
                    stored = hub.boveda.leer()
                    current = stored.get('open_id') if isinstance(stored, dict) else None
                    connection = hub.auth.conexion()
                    if (not isinstance(current, str) or not current
                            or not isinstance(connection, dict) or connection.get('estado') != 'conectada'
                            or not hmac.compare_digest(current.encode('utf-8'), expected.encode('ascii'))):
                        return error('cuenta_cambio_sin_importar',
                                     'La cuenta de TikTok cambió o aún no está conectada. No importamos datos. '
                                     'Revisa la cuenta y vuelve a intentarlo.', 409)
                    return jsonify(hub.local.importar(data))
            return jsonify(hub.local.importar(data))
        except ErrorDominio as exc:
            return jsonify(exc.a_respuesta(hub.secretos_vivos())), exc.http

    @app.get('/api/cloud/storage')
    def storage_status() -> Any:
        if settings.auth_provider != 'firebase':
            return jsonify(enabled=False, backups=[])
        try:
            return jsonify(enabled=True, backups=firebase.list_backups(g.firebase_claims))
        except Exception:
            return error('almacenamiento_no_disponible', 'No pudimos consultar tus copias en Firebase.', 503)

    @app.post('/api/cloud/storage/backup')
    def storage_backup() -> Any:
        if settings.auth_provider != 'firebase':
            return error('almacenamiento_no_configurado', 'Firebase Storage no está configurado.', 409)
        try:
            result = firebase.backup(g.firebase_claims, hub.local.exportar())
            return jsonify(result), 201
        except Exception:
            return error('almacenamiento_no_disponible', 'No pudimos guardar la copia. Tus datos siguen en Corte.', 503)

    @app.post('/api/cloud/storage/restore')
    def storage_restore() -> Any:
        if settings.auth_provider != 'firebase':
            return error('almacenamiento_no_configurado', 'Firebase Storage no está configurado.', 409)
        body = request.get_json(silent=True)
        identifier = body.get('id') if isinstance(body, dict) else None
        try:
            data = firebase.restore(g.firebase_claims, identifier)
            return jsonify(hub.local.importar(data))
        except ValueError:
            return error('archivo_invalido', 'La copia seleccionada no es válida.', 422)
        except ErrorDominio as exc:
            return jsonify(exc.a_respuesta(hub.secretos_vivos())), exc.http
        except Exception:
            return error('almacenamiento_no_disponible', 'No pudimos importar la copia de Firebase.', 503)

    @app.post('/api/cloud/storage/image')
    def storage_image() -> Any:
        if settings.auth_provider != 'firebase':
            return error('almacenamiento_no_configurado', 'Firebase Storage no está configurado.', 409)
        from creatorhub.imagenes.claves import ref_valido
        body = request.get_json(silent=True)
        tipo, ref = (body.get('tipo'), body.get('ref_id')) if isinstance(body, dict) else (None, None)
        if not ref_valido(tipo, ref):
            return error('imagen_invalida', 'Selecciona una imagen válida de Corte.', 422)
        path = hub.imagenes.ruta_original(tipo, ref)
        if not path:
            return error('no_encontrado', 'La imagen todavía no está descargada.', 404)
        try:
            relative = str(Path(path).resolve().relative_to(Path(hub.rutas.cache_img).resolve()))
            firebase.store_image(g.firebase_claims, relative, path)
            return jsonify(stored=True)
        except Exception:
            return error('almacenamiento_no_disponible', 'No pudimos guardar la imagen en Firebase.', 503)

    @app.route('/api/<path:path>', methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'])
    @app.get('/img/<path:path>')
    def api(path: str) -> Any:
        route = request.path
        disabled = ('/api/lan', '/api/auth/portapapeles', '/api/credenciales/importar',
                    '/api/credenciales/legado', '/api/credenciales/app-secret',
                    '/api/local/importar', '/api/sistema/abrir')
        if any(route == item or route.startswith(item + '/') for item in disabled):
            return error('no_disponible_en_nube', 'Esta función pertenece a la aplicación de escritorio.', 410)
        dispatcher = display if es_ruta_display(route) else hub.despachador
        business_headers = {key: value for key, value in request.headers.items() if key.lower() != 'authorization'}
        def dispatch_business() -> Any:
            return dispatcher.despachar(request.method, route, request.query_string.decode('utf-8', errors='replace'),
                                         business_headers, request.get_data(), CTX_UI)

        expected_scope = request.headers.get('X-Corte-Cache-Scope')
        evidence_write = ((request.method == 'PUT'
                           and re.fullmatch(r'/api/productos/[0-9]{1,25}/evidencia', route) is not None)
                          or (request.method == 'POST'
                              and re.fullmatch(r'/api/productos/[0-9]{1,25}/extraer', route) is not None))
        creator_write = request.method == 'POST' and route in (
            '/api/catalogo/vitrina/agregar', '/api/catalogo/vitrina/quitar', '/api/catalogo/vitrina/fijar',
            '/api/catalogo/enlaces-afiliado',
        )
        if (evidence_write or creator_write) and expected_scope is None:
            message = ('Actualiza la ficha antes de importar información del producto.' if evidence_write
                       else 'Actualiza la cuenta conectada antes de realizar la acción.')
            return error('cuenta_cambio_sin_aplicar', message, 409)
        if evidence_write or creator_write or (
            route == '/api/local/ops' and request.method == 'POST' and expected_scope is not None
        ):
            # New clients bind pending operations to the exact owner + creator.
            # Keep the comparison and mutation atomic with account changes.
            with hub._candado_mutacion:
                stored = hub.boveda.leer()
                creator = stored.get('open_id') if isinstance(stored, dict) else None
                current_scope = opaque_client_scopes(getattr(g, 'firebase_claims', None), creator).get('cache_scope')
                if (len(expected_scope) != 64 or any(c not in '0123456789abcdef' for c in expected_scope)
                        or current_scope is None or not hmac.compare_digest(expected_scope, current_scope)):
                    return error('cuenta_cambio_sin_aplicar', 'La cuenta cambió. Tus cambios anteriores se conservan sin aplicar.', 409)
                result = dispatch_business()
        else:
            result = dispatch_business()
        if (g.native_actor and request.method == 'POST' and result.status == 200
                and route in ('/api/auth/link', '/api/display/conectar')):
            try:
                compressed = any(key.lower() == 'content-encoding' and value == 'gzip' for key, value in result.cabeceras)
                payload = json.loads(gzip.decompress(result.cuerpo) if compressed else result.cuerpo)
                state = parse_qs(urlsplit(payload['url']).query, max_num_fields=16)['state'][0]
                native.register_callback(state, '/oauth/shop' if route == '/api/auth/link' else '/oauth/tiktok',
                                         g.native_actor['device_id'])
            except (ValueError, KeyError, TypeError):
                return error('conexion_no_disponible', 'No pudimos preparar el regreso del navegador. Inténtalo de nuevo.', 503)
        response = send_file(result.archivo) if result.archivo else Response(result.cuerpo, status=result.status)
        response.status_code = result.status
        for name, value in result.cabeceras:
            response.headers[name] = value
        return response

    @app.get('/')
    @app.get('/<path:path>')
    def interface(path: str = '') -> Any:
        result = static.resolver('/' + path)
        response = send_file(result.archivo) if result.archivo else Response(result.cuerpo, status=result.status)
        response.status_code = result.status
        for name, value in result.cabeceras:
            response.headers[name] = value
        return response

    return app


if __name__ == '__main__':
    # Development only. Production uses gunicorn and its single-worker configuration.
    create_app().run(host='127.0.0.1', port=int(os.environ.get('PORT', '10000')), threaded=True, debug=False)
