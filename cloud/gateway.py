"""Firebase Hosting -> Cloud Run -> one fixed private Corte backend.

This gateway holds no user data, Firebase keys or TikTok credentials. Cloud Run
must enforce a 55-second request timeout; Hosting's rewrite limit is 60 seconds.
"""
from __future__ import annotations

from dataclasses import dataclass
from http.cookies import SimpleCookie
import ipaddress
import os
import time
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, request, stream_with_context
import requests
from urllib3.exceptions import HTTPError as UpstreamHTTPError

MAX_BYTES = 20 * 1024 * 1024
HOP_HEADERS = frozenset({'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
                         'te', 'trailer', 'transfer-encoding', 'upgrade', 'content-length'})
FORWARD_HEADERS = frozenset({'accept', 'content-type', 'origin', 'x-ch-hub', 'if-none-match', 'last-event-id'})


@dataclass(frozen=True)
class GatewaySettings:
    upstream_url: str
    public_url: str

    def __post_init__(self) -> None:
        upstream = urlsplit(self.upstream_url)
        public = urlsplit(self.public_url)
        private_ranges = [ipaddress.ip_network(block) for block in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]
        try:
            address = ipaddress.ip_address(upstream.hostname or '')
            valid_ip = any(address in block for block in private_ranges)
        except ValueError:
            valid_ip = False
        if (upstream.scheme != 'http' or not valid_ip or upstream.port != 8080 or upstream.username
                or upstream.password or upstream.path or upstream.query or upstream.fragment):
            raise ValueError('Gateway requires one fixed RFC1918 backend IP on port 8080, without a path.')
        if (public.scheme != 'https' or not public.hostname or public.username or public.password
                or public.port not in (None, 443) or public.path or public.query or public.fragment):
            raise ValueError('Gateway requires the exact public HTTPS origin.')

    @classmethod
    def from_env(cls):
        return cls(os.environ['CORTE_UPSTREAM_URL'].rstrip('/'), os.environ['CORTE_PUBLIC_URL'].rstrip('/'))


def create_app(settings: GatewaySettings | None = None, transport=None) -> Flask:
    settings = settings or GatewaySettings.from_env()
    app = Flask(__name__, static_folder=None)
    app.config['MAX_CONTENT_LENGTH'] = MAX_BYTES
    upstream_host = urlsplit(settings.public_url).netloc

    def failure(message: str, status: int):
        return jsonify(error={'codigo': 'conexion_no_disponible', 'mensaje': message}), status

    @app.after_request
    def private_headers(response):
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['Vary'] = 'Cookie, Origin'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.errorhandler(413)
    def too_large(_error):
        return failure('Los datos superan el límite de 20 MB.', 413)

    @app.route('/<path:path>', methods=['GET', 'HEAD', 'POST', 'PATCH', 'PUT', 'DELETE'])
    def proxy(path: str):
        if not request.path.startswith(('/api/', '/img/', '/oauth/')) or '\\' in request.path:
            return failure('No encontramos esa ruta.', 404)
        headers = {key: value for key, value in request.headers.items() if key.lower() in FORWARD_HEADERS}
        headers['Host'] = upstream_host
        headers['X-Forwarded-Proto'] = 'https'
        # Never trust client-supplied Forwarded/X-Forwarded-* values. Pass exactly
        # the gateway's observed network peer; the VM trusts this single hop.
        try:
            headers['X-Forwarded-For'] = str(ipaddress.ip_address(request.remote_addr or ''))
        except ValueError:
            headers['X-Forwarded-For'] = '0.0.0.0'
        headers['Accept-Encoding'] = 'identity'
        cookie = request.cookies.get('__session')
        if cookie:
            only_session = SimpleCookie()
            only_session['__session'] = cookie
            headers['Cookie'] = only_session.output(header='').strip()
        suffix = request.path
        if request.query_string:
            suffix += '?' + request.query_string.decode('ascii', errors='replace')
        body = request.get_data()
        started = time.monotonic()
        # Never share a Requests cookie jar between visitors: a login response
        # could otherwise attach an owner's cookie to a later anonymous request.
        client = transport or requests.Session()
        owned_client = transport is None
        if owned_client:
            client.trust_env = False
        try:
            upstream = client.request(request.method, settings.upstream_url + suffix,
                                         headers=headers, data=body, stream=True,
                                         allow_redirects=False, timeout=(3, 17 if request.path == '/api/events' else 50))
        except requests.RequestException:
            if owned_client:
                client.close()
            return failure('No pudimos conectar con Corte. Inténtalo de nuevo.', 504)
        response_headers = []
        connection_headers = {part.strip().lower() for part in upstream.headers.get('Connection', '').split(',')}
        for key, value in upstream.headers.items():
            if key.lower() not in HOP_HEADERS | connection_headers | {'set-cookie'}:
                response_headers.append((key, value))
        # Requests combines repeated Set-Cookie in its dictionary. Preserve them
        # individually, especially session creation and logout expiry.
        for value in upstream.raw.headers.getlist('Set-Cookie'):
            response_headers.append(('Set-Cookie', value))
        is_stream = upstream.headers.get('Content-Type', '').split(';')[0] == 'text/event-stream'
        if is_stream:
            response_headers = [(key, value) for key, value in response_headers if key.lower() != 'content-encoding']
            @stream_with_context
            def events():
                total = 0
                try:
                    # Small line reads preserve SSE framing; no 64KB buffering of pings.
                    for line in upstream.iter_lines(chunk_size=1):
                        # A final silent read is bounded by 17s: 35 + 17 < Run's 55s.
                        if time.monotonic() - started >= 35:
                            break
                        total += len(line) + 1
                        if total > MAX_BYTES:
                            break
                        yield line + b'\n'
                except requests.RequestException:
                    pass
                finally:
                    upstream.close()
                    if owned_client:
                        client.close()
            return Response(events(), status=upstream.status_code, headers=response_headers)
        try:
            body = bytearray()
            # Raw bytes preserve Content-Encoding if an upstream unexpectedly compresses.
            for chunk in upstream.raw.stream(64 * 1024, decode_content=False):
                if time.monotonic() - started >= 52:
                    return failure('Corte tardó en responder. Inténtalo de nuevo.', 504)
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    return failure('La respuesta supera el límite permitido.', 502)
            return Response(bytes(body), status=upstream.status_code, headers=response_headers)
        except (requests.RequestException, UpstreamHTTPError, OSError):
            return failure('La conexión con Corte se interrumpió. Inténtalo de nuevo.', 502)
        finally:
            upstream.close()
            if owned_client:
                client.close()

    return app
