"""Descarga real por HTTPS (03 §2.3). Es el `Descargador` que usa el hub cuando `crear_imagenes(..., descargar=None)`.

- Solo `https` y hosts de la lista blanca del CDN (`claves.url_permitida`), validado en CADA salto.
- Redirecciones a mano (sin `HTTPRedirectHandler`): máx. 3, todas dentro de la lista blanca y en https.
- Respuesta 200 con `Content-Type: image/*`; `Content-Length` > 10 MB se rechaza sin leer el cuerpo y el cuerpo se lee
  por bloques hasta 10 MB + 1 (sin `Content-Length` también se corta).
- TLS con la verificación por omisión de `ssl.create_default_context()`. Tiempos: conexión 10 s, cada lectura 20 s y
  tope total de 60 s por imagen.
- Nunca registra la URL (las del avatar llevan firma). Las fallas salen como `ErrorImagen(codigo, permanente)`.
- `ssl` y `http.client` se importan al descargar, no al cargar el módulo (arranque del hub, C3). `conectar` es
  inyectable: las pruebas simulan el servidor sin red.
"""
from __future__ import annotations

import socket
import time
import urllib.parse
from typing import Any, Callable

from .. import config
from .claves import ErrorImagen, url_permitida

TIMEOUT_CONEXION_S = 10.0
TIMEOUT_LECTURA_S = 20.0
TOPE_TOTAL_S = 60.0
BLOQUE = 64 * 1024
REDIRECCIONES = frozenset({301, 302, 303, 307, 308})
_contexto_tls: Any = None


def _conectar_https(host: str, timeout: float) -> Any:
    import http.client
    import ssl

    global _contexto_tls
    if _contexto_tls is None:
        _contexto_tls = ssl.create_default_context()
    return http.client.HTTPSConnection(host, 443, timeout=timeout, context=_contexto_tls)


class DescargadorHttps:
    """Callable `url -> bytes` (interfaces.Descargador)."""

    def __init__(self, conectar: Callable[[str, float], Any] | None = None,
                 max_bytes: int = config.IMAGEN_MAX_BYTES,
                 max_redirecciones: int = config.IMAGEN_MAX_REDIRECCIONES,
                 monotonico: Callable[[], float] = time.monotonic) -> None:
        self.conectar = conectar or _conectar_https
        self.max_bytes = max_bytes
        self.max_redirecciones = max_redirecciones
        self.monotonico = monotonico

    def __call__(self, url: str) -> bytes:
        t0 = self.monotonico()
        actual = url
        for salto in range(self.max_redirecciones + 1):
            host = url_permitida(actual)
            if host is None:
                raise ErrorImagen('host_no_permitido' if salto == 0 else 'redireccion_no_permitida', permanente=True)
            siguiente = self._una_peticion(actual, host, t0)     # bytes o la URL del siguiente salto
            if isinstance(siguiente, bytes):
                return siguiente
            actual = siguiente
        raise ErrorImagen('demasiadas_redirecciones')

    # ------------------------------------------------------------------ una petición
    def _una_peticion(self, url: str, host: str, t0: float) -> bytes | str:
        import http.client

        u = urllib.parse.urlsplit(url)
        ruta = (u.path or '/') + (f'?{u.query}' if u.query else '')
        cabeceras = {'Host': host, 'User-Agent': f'CreatorHub/{config.VERSION}',
                     'Accept': 'image/webp,image/*;q=0.8', 'Accept-Encoding': 'identity'}
        con = self.conectar(host, TIMEOUT_CONEXION_S)
        try:
            try:
                conectar = getattr(con, 'connect', None)
                if callable(conectar):
                    conectar()
                sock = getattr(con, 'sock', None)
                if sock is not None:
                    sock.settimeout(TIMEOUT_LECTURA_S)
                con.request('GET', ruta, headers=cabeceras)
                r = con.getresponse()
            except (TimeoutError, socket.timeout):
                raise ErrorImagen('tiempo_agotado') from None
            except (OSError, http.client.HTTPException):
                raise ErrorImagen('sin_conexion') from None

            if r.status in REDIRECCIONES:
                destino = r.getheader('Location')
                if not destino:
                    raise ErrorImagen('redireccion_invalida')
                return urllib.parse.urljoin(url, destino.strip())
            if r.status != 200:
                raise ErrorImagen(f'http_{int(r.status)}', permanente=False)
            tipo = (r.getheader('Content-Type') or '').split(';', 1)[0].strip().lower()
            if not tipo.startswith('image/'):
                raise ErrorImagen('tipo_no_imagen')
            largo = r.getheader('Content-Length')
            if largo is not None:
                try:
                    if int(largo.strip()) > self.max_bytes:
                        raise ErrorImagen('demasiado_grande', permanente=True)
                except ValueError:
                    raise ErrorImagen('respuesta_invalida') from None
            return self._leer_acotado(r, t0)
        finally:
            try:
                con.close()
            except OSError:
                pass

    def _leer_acotado(self, r: Any, t0: float) -> bytes:
        import http.client

        partes: list[bytes] = []
        total = 0
        try:
            while True:
                if self.monotonico() - t0 > TOPE_TOTAL_S:
                    raise ErrorImagen('tiempo_agotado')
                bloque = r.read(min(BLOQUE, self.max_bytes + 1 - total))
                if not bloque:
                    break
                partes.append(bloque)
                total += len(bloque)
                if total > self.max_bytes:
                    raise ErrorImagen('demasiado_grande', permanente=True)
        except (TimeoutError, socket.timeout):
            raise ErrorImagen('tiempo_agotado') from None
        except (OSError, http.client.HTTPException):
            raise ErrorImagen('sin_conexion') from None
        if not total:
            raise ErrorImagen('respuesta_vacia')
        return b''.join(partes)
