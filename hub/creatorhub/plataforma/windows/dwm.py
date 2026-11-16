"""Barra de título nativa pintada con DWM (04 §A.4; 02 §11.1) y tema del sistema (C24).

`DWMWA_USE_IMMERSIVE_DARK_MODE` (20), `DWMWA_BORDER_COLOR` (34) = lienzo, `DWMWA_CAPTION_COLOR` (35) = lienzo y
`DWMWA_TEXT_COLOR` (36) = `--text-2` del tema (`spec/tokens.css`). En Windows 10 los atributos 34–36 no existen y
DwmSetWindowAttribute devuelve un error sin consecuencias: queda el modo oscuro inmersivo.
"""
from __future__ import annotations

import ctypes
import logging
import winreg
from ctypes import wintypes
from typing import Any

_log = logging.getLogger('creatorhub.plataforma.dwm')

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36

MODOS = ('claro', 'oscuro')
# --bg-canvas y --text-2 de spec/tokens.css 1.1.1 (02 §3.2)
COLORES: dict[str, dict[str, str]] = {
    'oscuro': {'fondo': '#0C0F0D', 'texto': '#C0C5C2'},     # grafito-50 / grafito-800
    'claro': {'fondo': '#F2F4F2', 'texto': '#454946'},      # grafito-950 / grafito-850
}
CLAVE_TEMA = r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'


def colorref(hex_rgb: str) -> int:
    """'#RRGGBB' → COLORREF (0x00BBGGRR)."""
    h = hex_rgb.lstrip('#')
    if len(h) != 6:
        raise ValueError(f'color inválido: {hex_rgb!r}')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r | (g << 8) | (b << 16)


def color_fondo(modo: str) -> str:
    return COLORES['claro' if modo == 'claro' else 'oscuro']['fondo']


def atributos(modo: str) -> list[tuple[int, int]]:
    """(atributo, valor) que se aplican para `modo`, en orden."""
    c = COLORES['claro' if modo == 'claro' else 'oscuro']
    return [(DWMWA_USE_IMMERSIVE_DARK_MODE, 0 if modo == 'claro' else 1),
            (DWMWA_CAPTION_COLOR, colorref(c['fondo'])),
            (DWMWA_BORDER_COLOR, colorref(c['fondo'])),
            (DWMWA_TEXT_COLOR, colorref(c['texto']))]


def _dwmapi() -> Any:
    dll = ctypes.WinDLL('dwmapi')
    dll.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    dll.DwmSetWindowAttribute.restype = ctypes.c_long
    return dll


def aplicar_tema(hwnd: int, modo: str, dwmapi: Any = None) -> bool:
    """Pinta la barra de título de `hwnd`. True si DWM aceptó los cuatro atributos (Windows 11)."""
    if modo not in MODOS or not hwnd:
        return False
    dll = dwmapi or _dwmapi()
    ok = True
    for atributo, valor in atributos(modo):
        v = ctypes.c_int(valor)
        hr = dll.DwmSetWindowAttribute(hwnd, atributo, ctypes.byref(v), ctypes.sizeof(v))
        ok = ok and hr == 0
    if not ok:
        _log.debug('DWM no aceptó todos los atributos (Windows 10 o sin composición)')
    return ok


def tema_del_sistema() -> str | None:
    """'claro' | 'oscuro' según «Modo de aplicación» de Windows; None si no se sabe."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE_TEMA) as k:
            valor, _tipo = winreg.QueryValueEx(k, 'AppsUseLightTheme')
    except OSError:
        return None
    return 'claro' if valor else 'oscuro'


def tema_inicial(guardado: Any) -> str:
    """El último tema que pidió la interfaz; si no hay, el del sistema; sin dato del sistema, oscuro (C24)."""
    if guardado in MODOS:
        return str(guardado)
    return tema_del_sistema() or 'oscuro'
