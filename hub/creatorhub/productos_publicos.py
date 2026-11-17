"""Read the public Mexico product page, without TikTok credentials or private APIs.

The public SSR structure was checked against a real MX product. It currently
contains the seller's size-guide image and a *preview* of buyer reviews. The
preview is not the full review history: its reported total is kept separately.
No script from the page is executed, and verification pages are never retried.
"""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import http.client
import json
import math
import re
import time
import urllib.parse
from typing import Any

from .errores import ErrorDominio
from .imagenes.claves import url_permitida

MAX_HTML_BYTES = 4 * 1024 * 1024
MAX_SEGUNDOS = 15
MAX_REDIRECTS = 3
MAX_RESENAS = 100
MAX_IMAGENES_RESENA = 10
_MAX_DOCUMENTO_BYTES = 180 * 1024
_PID = re.compile(r'[0-9]{1,25}')
_PATH = re.compile(r'/mx/pdp/(?:[A-Za-z0-9_-]+/)?([0-9]{1,25})/?')
_RID = re.compile(r'[A-Za-z0-9_-]{1,128}')
_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_REDIRECTS = frozenset({301, 302, 303, 307, 308})


def _error(codigo: str, mensaje: str) -> ErrorDominio:
    return ErrorDominio(codigo, mensaje, http=503)


def _pid(pid: str) -> str:
    if not isinstance(pid, str) or _PID.fullmatch(pid) is None:
        raise ErrorDominio('parametros_invalidos', 'El identificador del producto no es válido.', http=422)
    return pid


def _url(url: Any, pid: str) -> str:
    """Keep every request on the exact public host, MX PDP path and product ID."""
    if (not isinstance(url, str) or not url.isascii() or len(url) > 2048
            or any(ord(c) < 33 or ord(c) == 127 or c == '\\' for c in url)):
        raise _error('fuente_respuesta_invalida', 'TikTok no devolvió un enlace público válido del producto.')
    try:
        u = urllib.parse.urlsplit(url)
        path = _PATH.fullmatch(u.path)
        if (u.scheme != 'https' or u.hostname != 'shop.tiktok.com'
                or u.username is not None or u.password is not None
                or u.port not in (None, 443) or u.fragment or path is None or path[1] != pid):
            raise ValueError
    except ValueError:
        raise _error('fuente_respuesta_invalida', 'TikTok no devolvió un enlace público válido del producto.') from None
    return urllib.parse.urlunsplit(('https', 'shop.tiktok.com', u.path, u.query, ''))


def _sin_query(url: str) -> str:
    u = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, '', ''))


def _restante(limite: float) -> float:
    remaining = limite - time.monotonic()
    if remaining <= 0:
        raise _error('fuente_no_disponible', 'TikTok tardó demasiado en responder. Inténtalo más tarde.')
    return remaining


def _descargar(url: str, pid: str) -> tuple[bytes, str]:
    """One bounded request chain. No proxy, cookies, authentication or retries."""
    limite = time.monotonic() + MAX_SEGUNDOS
    actual = _url(url, pid)
    for numero in range(MAX_REDIRECTS + 1):
        conn = http.client.HTTPSConnection('shop.tiktok.com', timeout=_restante(limite))
        try:
            conn.connect()  # default certificate and hostname validation
            # Keep the socket reference: HTTPConnection may detach it after a
            # Connection: close response while HTTPResponse is still reading.
            sock = conn.sock
            if sock is not None:
                sock.settimeout(_restante(limite))
            parsed = urllib.parse.urlsplit(actual)
            target = parsed.path + ('?' + parsed.query if parsed.query else '')
            # http.client supplies only Host/Accept-Encoding; no browser fingerprint is copied.
            conn.request('GET', target)
            if sock is not None:
                sock.settimeout(_restante(limite))
            response = conn.getresponse()
            if response.status in _REDIRECTS:
                if numero == MAX_REDIRECTS:
                    raise _error('fuente_respuesta_invalida', 'TikTok redirigió la ficha demasiadas veces.')
                location = response.getheader('Location')
                if not location:
                    raise _error('fuente_respuesta_invalida', 'TikTok devolvió una redirección incompleta.')
                actual = _url(urllib.parse.urljoin(actual, location), pid)
                continue
            if response.status in (401, 403, 429):
                raise _error('fuente_verificacion_requerida',
                             'TikTok solicita una verificación para consultar esta ficha. La información anterior se conserva.')
            if response.status != 200:
                raise _error('fuente_no_disponible', 'La ficha pública de TikTok no está disponible en este momento.')
            content_type = response.getheader('Content-Type', '').split(';', 1)[0].strip().lower()
            if content_type not in ('text/html', 'application/xhtml+xml'):
                raise _error('fuente_respuesta_invalida', 'TikTok no devolvió una ficha pública válida.')
            encoding = response.getheader('Content-Encoding', '').strip().lower()
            if encoding not in ('', 'identity'):
                raise _error('fuente_respuesta_invalida', 'TikTok devolvió un formato de página no compatible.')
            length = response.getheader('Content-Length')
            if length is not None and (not length.isdigit() or int(length) > MAX_HTML_BYTES):
                raise _error('fuente_respuesta_invalida', 'La ficha pública supera el tamaño permitido.')
            chunks: list[bytes] = []
            recibidos = 0
            while True:
                if sock is not None:
                    sock.settimeout(_restante(limite))
                # read1 returns after one underlying read, so the deadline is checked during streaming.
                chunk = response.read1(min(64 * 1024, MAX_HTML_BYTES + 1 - recibidos))
                _restante(limite)
                if not chunk:
                    break
                chunks.append(chunk)
                recibidos += len(chunk)
                if recibidos > MAX_HTML_BYTES:
                    raise _error('fuente_respuesta_invalida', 'La ficha pública supera el tamaño permitido.')
            return b''.join(chunks), actual
        except ErrorDominio:
            raise
        except (OSError, http.client.HTTPException, ValueError):
            raise _error('fuente_no_disponible', 'No pudimos consultar la ficha pública de TikTok. Inténtalo más tarde.') from None
        finally:
            conn.close()
    raise _error('fuente_respuesta_invalida', 'TikTok no devolvió una ficha pública válida.')


class _ScriptsPublicos(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.script = False
        self.scripts: list[str] = []
        self._partes: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == 'script':
            self.script = dict(attrs).get('id') == '__MODERN_ROUTER_DATA__'
            if self.script:
                self._partes = []

    def handle_data(self, data: str) -> None:
        if self.script:
            self._partes.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == 'script' and self.script:
            self.scripts.append(''.join(self._partes))
            self.script = False


def _mapa(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _texto(value: Any, maximo: int) -> str | None:
    if not isinstance(value, str):
        return None
    return _CONTROL.sub('', value).strip()[:maximo] or None


def _entero(value: Any, minimo: int = 0, maximo: int = 1_000_000_000) -> int | None:
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 15:
        value = int(value)
    return value if isinstance(value, int) and not isinstance(value, bool) and minimo <= value <= maximo else None


def _promedio(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and 1 <= value <= 5 else None


def _fecha(value: Any, ahora: int) -> int | None:
    stamp = _entero(value, 1, 99_999_999_999_999)
    if stamp is None:
        return None
    if stamp >= 100_000_000_000:  # observed public review_time is milliseconds
        stamp //= 1000
    return stamp if stamp <= ahora + 300 else None


def _imagenes(value: Any, maximo: int = MAX_IMAGENES_RESENA) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for url in value[:100]:
        if url_permitida(url) is not None and url not in out:
            out.append(url)
            if len(out) >= maximo:
                break
    return out


def _resena(value: Any, pid: str, ahora: int) -> dict[str, Any] | None:
    row = _mapa(value)
    if not row or ('product_id' in row and row['product_id'] != pid):
        return None
    texto = _texto(row.get('review_text'), 5000) or ''
    estrellas = _entero(row.get('review_rating'), 1, 5)
    imagenes = _imagenes(row.get('review_images'))
    if not texto and estrellas is None and not imagenes:
        return None
    fecha = _fecha(row.get('review_time'), ahora)
    variante = _texto(row.get('sku_specification'), 200)
    rid = row.get('review_id')
    if not isinstance(rid, str) or _RID.fullmatch(rid) is None:
        identity = json.dumps([pid, texto, estrellas, fecha, variante, imagenes], ensure_ascii=False, separators=(',', ':'))
        rid = 'public-' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:32]
    verificada = row.get('is_verified_purchase')
    return {'id': rid, 'texto': texto, 'estrellas': estrellas, 'fecha': fecha,
            'variante': variante, 'compra_verificada': verificada if isinstance(verificada, bool) else None,
            'imagenes': imagenes}


def extraer_evidencia_publica(html: str | bytes, product_id: str, url: str, ahora: int) -> dict[str, Any]:
    """Normalize only the product's public SSR component; never execute page JS."""
    pid = _pid(product_id)
    canonical = _sin_query(_url(url, pid))
    if isinstance(html, bytes):
        if len(html) > MAX_HTML_BYTES:
            raise _error('fuente_respuesta_invalida', 'La ficha pública supera el tamaño permitido.')
        html = html.decode('utf-8', errors='replace')
    if not isinstance(html, str) or len(html.encode('utf-8')) > MAX_HTML_BYTES:
        raise _error('fuente_respuesta_invalida', 'La ficha pública supera el tamaño permitido.')
    if re.search(r'<title\b[^>]*>\s*(?:security check|captcha|access denied|just a moment)', html, re.I):
        raise _error('fuente_verificacion_requerida', 'TikTok solicita una verificación para consultar esta ficha.')
    parser = _ScriptsPublicos()
    try:
        parser.feed(html)
        if not parser.scripts and re.search(r'Verify to continue|captcha-verify-image', html, re.I):
            raise _error('fuente_verificacion_requerida', 'TikTok solicita una verificación para consultar esta ficha.')
        if len(parser.scripts) != 1:
            raise _error('fuente_sin_datos', 'La ficha no incluye información pública de tallas o reseñas que Corte pueda leer.')
        data = json.loads(parser.scripts[0])
    except (ValueError, RecursionError):
        raise _error('fuente_respuesta_invalida', 'La información pública de TikTok no tiene el formato esperado.') from None
    loaders = _mapa(_mapa(data).get('loaderData'))
    component: dict[str, Any] = {}
    for page in list(loaders.values())[:20]:
        page = _mapa(page)
        components = _mapa(page.get('page_config')).get('components_map')
        if not isinstance(components, list):
            continue
        for candidate in components[:100]:
            candidate = _mapa(_mapa(candidate).get('component_data'))
            product = _mapa(candidate.get('product_info'))
            if product.get('product_id') != pid:
                continue
            route = _mapa(page.get('route_info'))
            if route.get('route_product_id', pid) != pid:
                raise _error('fuente_respuesta_invalida', 'La ficha pública corresponde a otro producto.')
            if route.get('canonical_url'):
                canonical = _sin_query(_url(route['canonical_url'], pid))
            component = candidate
            break
        if component:
            break
    if not component:
        raise _error('fuente_sin_datos', 'No encontramos los datos de este producto en su ficha pública.')
    fuente = {'tipo': 'captura_tiktok', 'url': canonical, 'nombre': 'TikTok Shop México'}
    cabecera = {'estado': 'disponible', 'fuente': fuente, 'consultado_at': ahora}
    out: dict[str, Any] = {}
    product = _mapa(component.get('product_info'))
    # url_list contains CDN alternatives for one image, not several separate charts.
    chart_images = _imagenes(_mapa(_mapa(product.get('size_guide')).get('image')).get('url_list'), 1)
    if chart_images:
        out['tabla_tallas'] = dict(cabecera, tabla={'columnas': [], 'filas': [], 'unidad': None,
                                                  'imagenes': chart_images})
    reviews = _mapa(component.get('review_info'))
    ratings = _mapa(reviews.get('review_ratings'))
    total = _entero(reviews.get('total_reviews'))
    if total is None:
        total = _entero(ratings.get('review_count'))
    average = _promedio(ratings.get('overall_score'))
    if average is None:
        average = _promedio(_mapa(product.get('review')).get('product_rating'))
    items, ids = [], set()
    original_items = reviews.get('product_reviews')
    for value in original_items[:1000] if isinstance(original_items, list) else []:
        row = _resena(value, pid, ahora)
        if row is not None and row['id'] not in ids:
            items.append(row)
            ids.add(row['id'])
        if len(items) >= MAX_RESENAS:
            break
    if items or total is not None or (reviews and average is not None):
        if total is not None and total < len(items):
            total = None  # inconsistent source is not repaired by inventing a total
        if total == 0:
            average = None
        out['resenas'] = dict(cabecera, promedio=average, total=total, items=items)
    if not out:
        raise _error('fuente_sin_datos', 'La ficha no incluye una tabla de tallas o reseñas legibles para este producto.')
    # Respect the evidence service's document limit even for unusually long public reviews.
    while len(json.dumps(out, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) > _MAX_DOCUMENTO_BYTES:
        if not out.get('resenas', {}).get('items'):
            raise _error('fuente_respuesta_invalida', 'La información pública supera el tamaño permitido.')
        out['resenas']['items'].pop()
    return out


def obtener_producto_publico(product_id: str, ahora: int, url: str | None = None) -> dict[str, Any]:
    """Fetch a public PDP by its observed numeric MX link, then normalize its SSR."""
    pid = _pid(product_id)
    body, final_url = _descargar(url or f'https://shop.tiktok.com/mx/pdp/{pid}', pid)
    return extraer_evidencia_publica(body, pid, final_url, ahora)


consultar_producto = obtener_producto_publico
