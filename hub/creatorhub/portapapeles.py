"""Portapapeles de Windows para la URL de autorización (04 §A.8; 03 §2.2 paso 3, §7.8).

Reglas (las aplica `auth`, que es el único que usa este módulo):
- Solo se lee si hay un `state` vivo (sin usar y no vencido) y en modo real; si no, ni se abre el portapapeles.
- Solo cuenta un texto que coincida EXACTAMENTE con el host de retorno registrado y traiga `code` y `state`.
- El texto nunca se guarda ni se registra; el `code` queda en memoria hasta el canje inmediato y nunca viaja a
  JavaScript. La respuesta solo trae `detectado`, `vista_previa` (`project-…web.app/?code=••••&state=✓`) y
  `state_coincide`.
- `GetClipboardSequenceNumber()` evita releer el mismo contenido.
- La app nunca escribe en el portapapeles nada de TikTok: solo lo VACÍA tras el canje si sigue teniendo la URL.

`numero_secuencia()` y `hay_texto()` no leen el contenido del usuario (solo metadatos).
"""
from __future__ import annotations

import logging
import re
import time
import urllib.parse
from typing import Any

_log = logging.getLogger('creatorhub.portapapeles')

CF_UNICODETEXT = 13
HOST_RETORNO = 'project-9ed73120-63d7-4d11-9b0.web.app'
URL_AUTH = re.compile(r'^\s*https://project-9ed73120-63d7-4d11-9b0\.web\.app/\?\S{1,2048}\s*$')
MAX_CARACTERES = 4096
VISTA_COINCIDE = 'project-…web.app/?code=••••&state=✓'
VISTA_NO_COINCIDE = 'project-…web.app/?code=••••&state=✗'


def analizar_url_retorno(texto: str | None) -> tuple[str, str] | None:
    """(code, state) si `texto` es exactamente la URL de retorno registrada con `code` y `state`; si no, None."""
    if not texto or not URL_AUTH.match(texto):
        return None
    try:
        u = urllib.parse.urlsplit(texto.strip())
    except ValueError:
        return None
    if u.scheme != 'https' or (u.hostname or '').lower() != HOST_RETORNO or u.port not in (None, 443) or u.username:
        return None
    q = urllib.parse.parse_qs(u.query, keep_blank_values=False)
    code, state = (q.get('code') or [''])[0], (q.get('state') or [''])[0]
    if not code or not state:
        return None
    return code, state


def vista_previa(state_coincide: bool) -> str:
    return VISTA_COINCIDE if state_coincide else VISTA_NO_COINCIDE


class PortapapelesWindows:
    """Acceso por ctypes a user32/kernel32 (04 §A.8). Las DLL se cargan en el primer uso."""

    def __init__(self) -> None:
        self._u32: Any = None
        self._k32: Any = None

    def _dll(self) -> tuple[Any, Any]:
        if self._u32 is None:
            import ctypes
            from ctypes import wintypes
            u32 = ctypes.WinDLL('user32', use_last_error=True)
            k32 = ctypes.WinDLL('kernel32', use_last_error=True)
            u32.OpenClipboard.argtypes = [wintypes.HWND]
            u32.OpenClipboard.restype = wintypes.BOOL
            u32.CloseClipboard.argtypes = []
            u32.CloseClipboard.restype = wintypes.BOOL
            u32.EmptyClipboard.argtypes = []
            u32.EmptyClipboard.restype = wintypes.BOOL
            u32.GetClipboardData.argtypes = [wintypes.UINT]
            u32.GetClipboardData.restype = wintypes.HANDLE
            u32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
            u32.IsClipboardFormatAvailable.restype = wintypes.BOOL
            u32.GetClipboardSequenceNumber.argtypes = []
            u32.GetClipboardSequenceNumber.restype = wintypes.DWORD
            k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
            k32.GlobalLock.restype = ctypes.c_void_p
            k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
            k32.GlobalUnlock.restype = wintypes.BOOL
            k32.GlobalSize.argtypes = [wintypes.HGLOBAL]
            k32.GlobalSize.restype = ctypes.c_size_t
            self._u32, self._k32 = u32, k32
        return self._u32, self._k32

    def numero_secuencia(self) -> int:
        """Número de secuencia del portapapeles (cambia con cada copia). No lee el contenido."""
        u32, _ = self._dll()
        return int(u32.GetClipboardSequenceNumber())

    def hay_texto(self) -> bool:
        """¿Hay texto Unicode en el portapapeles? No lee el contenido."""
        u32, _ = self._dll()
        return bool(u32.IsClipboardFormatAvailable(CF_UNICODETEXT))

    def _abrir(self) -> bool:
        u32, _ = self._dll()
        for _ in range(5):                          # otra app puede tenerlo abierto un instante
            if u32.OpenClipboard(None):
                return True
            time.sleep(0.03)
        return False

    def leer_texto(self, maximo: int = MAX_CARACTERES) -> str | None:
        """Texto del portapapeles (máx. `maximo` caracteres) o None. Quien llama nunca lo guarda ni lo registra."""
        import ctypes
        u32, k32 = self._dll()
        if not u32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        if not self._abrir():
            return None
        try:
            h = u32.GetClipboardData(CF_UNICODETEXT)
            p = k32.GlobalLock(h) if h else None
            if not p:
                return None
            try:
                return ctypes.wstring_at(p, min(k32.GlobalSize(h) // 2, maximo)).split('\x00', 1)[0]
            finally:
                k32.GlobalUnlock(h)
        finally:
            u32.CloseClipboard()

    def vaciar(self) -> bool:
        """Vacía el portapapeles (no escribe nada). True si lo logró."""
        u32, _ = self._dll()
        if not self._abrir():
            return False
        try:
            return bool(u32.EmptyClipboard())
        finally:
            u32.CloseClipboard()


def crear_portapapeles() -> PortapapelesWindows:
    return PortapapelesWindows()
