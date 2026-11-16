"""Sesión de la ventana local (BUILD_SPEC §6.4; 03 §6.1 y §7.3; 04 §A.3).

- `crear_token()`: token de arranque de UN uso y 60 s para `GET /boot?t=` (lo pide HubProto.url_arranque()).
- `/boot?t=` válido → sesión nueva y cookie `ch_s` (`HttpOnly; SameSite=Strict; Path=/`). `/boot/dev` solo con --dev.
- `/api/*` e `/img/*` exigen la cookie (salvo /api/health). Cada sesión tiene su cubeta de 50/s para /api/* y otra
  APARTE de 400/s para /img/* y estáticos (una cuadrícula de ~100 fotos por 6 conexiones no recibe 429).
Los valores de token y cookie nunca se registran.
"""
from __future__ import annotations

import collections
import secrets
import threading
import time

from .. import config
from .seguridad import Cubeta

MAX_SESIONES = 32
MAX_TOKENS = 16
NOMBRE_COOKIE = 'ch_s'


class _Sesion:
    __slots__ = ('api', 'img', 'creada')

    def __init__(self) -> None:
        self.api = Cubeta(config.TASA_API_POR_S)
        self.img = Cubeta(config.TASA_ESTATICOS_POR_S)
        self.creada = time.monotonic()


class GestorSesiones:
    """Tokens de arranque y sesiones en memoria (se pierden al cerrar el hub: cada arranque abre con /boot?t=)."""

    def __init__(self, vigencia_token_s: float = config.VIGENCIA_TOKEN_BOOT_S) -> None:
        self.vigencia_token_s = float(vigencia_token_s)
        self._candado = threading.Lock()
        self._tokens: dict[str, float] = {}
        self._sesiones: collections.OrderedDict[str, _Sesion] = collections.OrderedDict()
        self._anonima = _Sesion()                         # estáticos sin cookie (la propia página de /boot)

    # ------------------------------------------------------------------ token de arranque
    def crear_token(self) -> str:
        token = secrets.token_urlsafe(32)
        ahora = time.monotonic()
        with self._candado:
            self._tokens = {t: v for t, v in self._tokens.items() if v > ahora}
            while len(self._tokens) >= MAX_TOKENS:
                self._tokens.pop(next(iter(self._tokens)))
            self._tokens[token] = ahora + self.vigencia_token_s
        return token

    def consumir_token(self, token: str | None) -> bool:
        """True una sola vez por token y solo dentro de su vigencia."""
        if not token:
            return False
        with self._candado:
            vence = self._tokens.pop(token, None)
        return vence is not None and vence >= time.monotonic()

    # ------------------------------------------------------------------ sesiones
    def nueva_sesion(self) -> str:
        valor = secrets.token_urlsafe(32)
        with self._candado:
            while len(self._sesiones) >= MAX_SESIONES:
                self._sesiones.popitem(last=False)
            self._sesiones[valor] = _Sesion()
        return valor

    @staticmethod
    def cookie(valor: str) -> str:
        return f'{NOMBRE_COOKIE}={valor}; HttpOnly; SameSite=Strict; Path=/'

    @staticmethod
    def valor_cookie(cabecera: str | None) -> str | None:
        for parte in (cabecera or '').split(';'):
            k, _, v = parte.strip().partition('=')
            if k == NOMBRE_COOKIE and v:
                return v.strip()
        return None

    def sesion(self, cabecera_cookie: str | None) -> str | None:
        """El valor de la sesión si la cookie corresponde a una viva; None si no."""
        valor = self.valor_cookie(cabecera_cookie)
        if valor is None:
            return None
        with self._candado:
            return valor if valor in self._sesiones else None

    def permitir(self, sesion: str | None, tipo: str) -> bool:
        """Cubeta 'api' (50/s) o 'img' (400/s, también estáticos). Sin sesión: la cubeta anónima de estáticos."""
        with self._candado:
            s = self._sesiones.get(sesion) if sesion is not None else None
        if s is None:
            s = self._anonima
        return (s.api if tipo == 'api' else s.img).tomar()
