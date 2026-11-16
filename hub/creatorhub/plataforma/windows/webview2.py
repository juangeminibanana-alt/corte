"""¿Está Microsoft Edge WebView2? (04 §A.2 paso 5).

Se busca `pv` en `EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}` (HKLM WOW6432Node, HKLM y HKCU). Si falta,
un MessageBox dice «Corte necesita Microsoft Edge WebView2. Te llevamos a la descarga oficial.» y se abre la descarga
oficial (`go.microsoft.com`, único host extra de la lista de §6.4, solo desde el shell). El shell fuerza
`gui='edgechromium'` para que pywebview nunca caiga a MSHTML.
"""
from __future__ import annotations

import ctypes
import logging
import winreg
from typing import Any, Callable, Iterable

from creatorhub.plataforma.windows import navegacion

_log = logging.getLogger('creatorhub.plataforma.webview2')

GUID_RUNTIME = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
CLAVES: tuple[tuple[Any, str], ...] = (
    (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients' + '\\' + GUID_RUNTIME),
    (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\EdgeUpdate\Clients' + '\\' + GUID_RUNTIME),
    (winreg.HKEY_CURRENT_USER, r'Software\Microsoft\EdgeUpdate\Clients' + '\\' + GUID_RUNTIME),
)
URL_DESCARGA = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703'
TITULO = 'Corte'
TEXTO_FALTA = 'Corte necesita Microsoft Edge WebView2. Te llevamos a la descarga oficial.'
MB_OK, MB_ICONINFORMATION, MB_SETFOREGROUND = 0x0, 0x40, 0x10000


def _leer_pv(raiz: Any, clave: str) -> str | None:
    try:
        with winreg.OpenKey(raiz, clave, 0, winreg.KEY_READ) as k:
            valor, _tipo = winreg.QueryValueEx(k, 'pv')
    except OSError:
        return None
    return str(valor) if valor else None


def version_instalada(claves: Iterable[tuple[Any, str]] = CLAVES,
                      leer: Callable[[Any, str], str | None] = _leer_pv) -> str | None:
    """Versión de WebView2 ('157.0.…') o None si no está (o quedó como '0.0.0.0' tras desinstalarse)."""
    for raiz, clave in claves:
        pv = leer(raiz, clave)
        if pv and pv.strip() and pv.strip() != '0.0.0.0':
            return pv.strip()
    return None


def mostrar_mensaje(titulo: str, texto: str) -> None:
    u32 = ctypes.WinDLL('user32', use_last_error=True)
    u32.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    u32.MessageBoxW(None, texto, titulo, MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND)


def avisar_falta(mensaje: Callable[[str, str], None] = mostrar_mensaje,
                 abrir: Callable[[str], None] = navegacion.abrir_en_navegador) -> None:
    """MessageBox y, al cerrarlo, la descarga oficial en el navegador."""
    _log.error('Microsoft Edge WebView2 no está instalado')
    mensaje(TITULO, TEXTO_FALTA)
    if navegacion.url_externa_permitida(URL_DESCARGA, con_aviso_webview2=True):
        try:
            abrir(URL_DESCARGA)
        except OSError as e:
            _log.warning('No se pudo abrir la descarga de WebView2 (%s)', type(e).__name__)
