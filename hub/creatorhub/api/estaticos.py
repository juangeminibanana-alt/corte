"""Estáticos de la interfaz (`ui/dist` de Vite) para la ventana local (BUILD_SPEC §6.4; 04 §A.3).

- `index.html` (y el respaldo de SPA): `Cache-Control: no-store` + la CSP de §6.4 SOLO como cabecera. Si el archivo
  trajera un `<meta http-equiv="Content-Security-Policy">` se quita al servirlo (C47b: nunca en <meta>).
- `/assets/*`: `public, max-age=31536000, immutable` (nombres con hash de Vite). El resto (p. ej. `/tema-inicial.js`,
  `/licencias.json` si existe): `no-cache`.
- Respaldo de SPA: una ruta sin extensión que no existe sirve index.html; un archivo con extensión que no existe → 404.
- Nunca sale de la carpeta: segmentos `.`/`..`, barras invertidas, `:` y bytes de control → 404; `realpath` dentro de
  la carpeta. `/api`, `/img`, `/boot` y `/lan` nunca llegan aquí (los atiende el servidor).
"""
from __future__ import annotations

import logging
import os
import re
import urllib.parse
from dataclasses import dataclass, field

from .seguridad import CSP_PAGINA_HUB, CSP_WINDOWS

_log = logging.getLogger('creatorhub.api.estaticos')

INMUTABLE = 'public, max-age=31536000, immutable'
TIPOS: dict[str, str] = {
    '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.map': 'application/json; charset=utf-8',
    '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp',
    '.gif': 'image/gif', '.ico': 'image/x-icon', '.avif': 'image/avif', '.woff2': 'font/woff2', '.woff': 'font/woff',
    '.ttf': 'font/ttf', '.otf': 'font/otf', '.txt': 'text/plain; charset=utf-8', '.wasm': 'application/wasm',
    '.webmanifest': 'application/manifest+json',
}
_RE_META_CSP = re.compile(rb'<meta\b[^>]*http-equiv\s*=\s*["\']?\s*content-security-policy[^>]*>\s*', re.IGNORECASE)
PREFIJOS_RESERVADOS = ('/api', '/img', '/boot', '/lan')

PAGINA_SIN_INTERFAZ = ('<!doctype html><html lang="es-MX"><head><meta charset="utf-8"><title>Corte</title></head><body>'
                       '<main><h1>Corte</h1><p>No encontramos la interfaz de Corte. Vuelve a instalar Corte.</p></main>'
                       '</body></html>').encode('utf-8')


@dataclass
class Estatico:
    status: int
    cabeceras: list[tuple[str, str]] = field(default_factory=list)
    cuerpo: bytes = b''
    archivo: str | None = None


def _no_encontrado() -> Estatico:
    return Estatico(404, [('Content-Type', 'application/json; charset=utf-8'), ('Cache-Control', 'no-store')],
                    '{"error":{"codigo":"no_encontrado","mensaje":"No encontramos lo que buscas."}}'.encode('utf-8'))


class Estaticos:
    """Resuelve una ruta de URL a un archivo de `dir_ui` con sus cabeceras."""

    def __init__(self, dir_ui: str) -> None:
        self.dir_ui = os.path.abspath(dir_ui)
        self._raiz_real = os.path.realpath(self.dir_ui)
        self._aviso_meta = False

    # ------------------------------------------------------------------ utilidades
    def _ruta_local(self, ruta_url: str) -> str | None:
        """Ruta absoluta dentro de dir_ui o None si la URL intenta salir de la carpeta."""
        try:
            segmentos = [urllib.parse.unquote(s, errors='strict') for s in ruta_url.split('/')[1:]]
        except UnicodeDecodeError:
            return None
        for s in segmentos:
            if s in ('.', '..') or '\\' in s or ':' in s or '/' in s or any(ord(c) < 32 or ord(c) == 127 for c in s):
                return None
        candidato = os.path.join(self.dir_ui, *[s for s in segmentos if s])
        real = os.path.realpath(candidato)
        if real != self._raiz_real and not real.startswith(self._raiz_real + os.sep):
            return None
        return candidato

    def _index(self) -> Estatico:
        ruta = os.path.join(self.dir_ui, 'index.html')
        try:
            with open(ruta, 'rb') as f:
                cuerpo = f.read()
        except OSError:
            _log.error('No hay index.html en la carpeta de la interfaz')
            return Estatico(503, [('Content-Type', 'text/html; charset=utf-8'), ('Cache-Control', 'no-store'),
                                  ('Content-Security-Policy', CSP_PAGINA_HUB)], PAGINA_SIN_INTERFAZ)
        if _RE_META_CSP.search(cuerpo):
            cuerpo = _RE_META_CSP.sub(b'', cuerpo)
            if not self._aviso_meta:
                self._aviso_meta = True
                _log.warning('index.html traía la CSP en <meta>: se quitó (la CSP va solo como cabecera, C47b)')
        return Estatico(200, [('Content-Type', 'text/html; charset=utf-8'), ('Cache-Control', 'no-store'),
                              ('Content-Security-Policy', CSP_WINDOWS)], cuerpo)

    # ------------------------------------------------------------------ resolver
    def resolver(self, ruta_url: str) -> Estatico:
        if not ruta_url.startswith('/') or any(ruta_url == p or ruta_url.startswith(p + '/')
                                               for p in PREFIJOS_RESERVADOS):
            return _no_encontrado()
        if ruta_url in ('/', '/index.html'):
            return self._index()
        local = self._ruta_local(ruta_url)
        if local is None:
            return _no_encontrado()
        ultimo = ruta_url.rstrip('/').rsplit('/', 1)[-1]
        if os.path.isfile(local):
            ext = os.path.splitext(local)[1].lower()
            if ext == '.html' and os.path.basename(local).lower() == 'index.html':
                return self._index()
            cache = INMUTABLE if ruta_url.startswith('/assets/') else 'no-cache'
            cab = [('Content-Type', TIPOS.get(ext, 'application/octet-stream')), ('Cache-Control', cache)]
            if ext == '.html':
                cab.append(('Content-Security-Policy', CSP_WINDOWS))
            return Estatico(200, cab, archivo=local)
        if '.' not in ultimo and not ruta_url.startswith('/assets/'):
            return self._index()                            # respaldo de SPA (#/… no llega al servidor, pero /x sí)
        return _no_encontrado()
