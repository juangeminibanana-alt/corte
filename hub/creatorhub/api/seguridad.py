"""Seguridad del servidor de interfaz (BUILD_SPEC §6.4 y C9; 03 §7.3 y §7.7; 04 §A.3).

- `Host` ∈ {127.0.0.1:<p>, localhost:<p>} o 421 (DNS rebinding).
- `Origin` presente y distinto del propio → 403 (en --dev también http://localhost:5173, C31). Sin CORS: el hub nunca
  manda cabeceras `Access-Control-*`.
- CSP única, SOLO como cabecera HTTP de index.html (C47b); `nosniff` y `Referrer-Policy: no-referrer` en todo.
- Cubetas de fichas: 50/s por sesión en /api/* y una cubeta APARTE de 400/s para /img/* y estáticos.
- `validar_url_abrir`: regla de 03 §7.7 para POST /api/sistema/abrir (https, sin usuario, puerto 443, host exacto).
"""
from __future__ import annotations

import threading
import time
import urllib.parse
from typing import Iterable

from .. import config
from ..errores import ErrorDominio

CSP_WINDOWS = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
               "font-src 'self'; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; "
               "form-action 'none'; frame-ancestors 'none'; frame-src https://www.tiktok.com")
# Páginas propias del hub que no son la interfaz (p. ej. «este enlace de inicio ya no sirve»): nada externo.
CSP_PAGINA_HUB = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"

CABECERAS_BASE: tuple[tuple[str, str], ...] = (('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'no-referrer'))
METODOS_MUTACION = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})

MSG_HOST = 'Esta dirección no es la de Corte.'
MSG_ORIGEN = 'Esta petición no viene de Corte.'
MSG_SESION = 'Tu sesión con Corte terminó. Cierra y vuelve a abrir Corte.'
MSG_CABECERA_HUB = 'Esta petición no viene de Corte.'
MSG_TASA = 'Demasiadas solicitudes seguidas. Espera un momento e inténtalo de nuevo.'
MSG_URL = 'Ese enlace no se puede abrir desde Corte.'


def hosts_validos(puerto: int) -> frozenset[str]:
    return frozenset({f'127.0.0.1:{puerto}', f'localhost:{puerto}'})


def host_valido(host: str | None, puerto: int) -> bool:
    return bool(host) and host.strip().lower() in hosts_validos(puerto)


def origenes_validos(puerto: int, dev: bool) -> frozenset[str]:
    propios = {f'http://127.0.0.1:{puerto}', f'http://localhost:{puerto}'}
    if dev:
        propios.add(config.ORIGEN_DEV)
    return frozenset(propios)


def origen_valido(origin: str | None, puerto: int, dev: bool) -> bool:
    """Sin Origin vale (navegación directa y GET del mismo origen). Con Origin, solo el propio (o el de Vite en --dev)."""
    if origin is None:
        return True
    return origin.strip().lower() in origenes_validos(puerto, dev)


def es_mutacion(metodo: str) -> bool:
    return metodo.upper() in METODOS_MUTACION


def sin_cors(cabeceras: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """Quita cualquier Access-Control-* que un servicio hubiera puesto (no hay CORS en el hub)."""
    return [(k, v) for k, v in cabeceras if not k.lower().startswith('access-control-')]


# ------------------------------------------------------------------ enlaces externos (03 §7.7)
def validar_url_abrir(url: object, hosts: frozenset[str] = config.HOSTS_PERMITIDOS) -> str:
    """Devuelve la URL RECONSTRUIDA con urlunsplit o lanza ErrorDominio(400 parametros_invalidos)."""
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise ErrorDominio('parametros_invalidos', MSG_URL, http=400)
    if '\\' in url or any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise ErrorDominio('parametros_invalidos', MSG_URL, http=400)
    try:
        u = urllib.parse.urlsplit(url)
        puerto = u.port
    except ValueError:
        raise ErrorDominio('parametros_invalidos', MSG_URL, http=400) from None
    host = (u.hostname or '').lower()
    if (u.scheme != 'https' or u.username is not None or u.password is not None or '@' in u.netloc
            or puerto not in (None, 443) or host not in hosts):
        raise ErrorDominio('parametros_invalidos', MSG_URL, http=400)
    return urllib.parse.urlunsplit(('https', host, u.path, u.query, u.fragment))


# ------------------------------------------------------------------ límites de tasa
class Cubeta:
    """Cubeta de fichas (tasa por segundo, ráfaga = tasa). `tomar()` no duerme: True si hay ficha."""

    def __init__(self, tasa: float, rafaga: float | None = None) -> None:
        self.tasa = float(tasa)
        self.capacidad = float(rafaga if rafaga is not None else tasa)
        self.fichas = self.capacidad
        self.t = time.monotonic()
        self._candado = threading.Lock()

    def tomar(self) -> bool:
        with self._candado:
            ahora = time.monotonic()
            self.fichas = min(self.capacidad, self.fichas + max(0.0, ahora - self.t) * self.tasa)
            self.t = ahora
            if self.fichas >= 1.0:
                self.fichas -= 1.0
                return True
            return False
