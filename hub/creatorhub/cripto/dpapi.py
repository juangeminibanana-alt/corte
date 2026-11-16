"""DPAPI por ctypes (04 §A.10; verificado en spec/verificacion/v04_cripto.py §3).

`CryptProtectData`/`CryptUnprotectData` en el ámbito del usuario actual, con `CRYPTPROTECT_UI_FORBIDDEN` y una entropía
constante por propósito (no es secreta: separa usos). Los búferes de entrada y salida se ponen en cero al terminar
(Python no deja borrar la copia inmutable que se devuelve).
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

ENTROPIA_CREDENCIALES = b'CreatorHub/credenciales/v1'
ENTROPIA_TLS = b'CreatorHub/tls/v1'
CRYPTPROTECT_UI_FORBIDDEN = 0x1
_DESCRIPCION = 'Creator Hub'          # 03_datos_api §7.1 (solo metadato del blob; no interviene al descifrar)


class ErrorDpapi(OSError):
    """DPAPI no pudo cifrar o descifrar (entropía distinta, datos alterados, perfil de otra PC)."""


class _Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


_crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_crypt32.CryptProtectData.argtypes = [ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob), ctypes.c_void_p,
                                      ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
_crypt32.CryptProtectData.restype = wintypes.BOOL
_crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(_Blob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(_Blob),
                                        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
_crypt32.CryptUnprotectData.restype = wintypes.BOOL
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]
_kernel32.LocalFree.restype = ctypes.c_void_p


def _llamar(datos: bytes, entropia: bytes, proteger: bool) -> bytes:
    if not isinstance(datos, (bytes, bytearray)) or not isinstance(entropia, (bytes, bytearray)):
        raise TypeError('datos y entropia deben ser bytes')
    b_datos = (ctypes.c_ubyte * max(1, len(datos))).from_buffer_copy(bytes(datos) or b'\0')
    b_ent = (ctypes.c_ubyte * max(1, len(entropia))).from_buffer_copy(bytes(entropia) or b'\0')
    entrada = _Blob(len(datos), ctypes.cast(b_datos, ctypes.POINTER(ctypes.c_ubyte)))
    ent = _Blob(len(entropia), ctypes.cast(b_ent, ctypes.POINTER(ctypes.c_ubyte)))
    salida = _Blob()
    try:
        if proteger:
            ok = _crypt32.CryptProtectData(ctypes.byref(entrada), _DESCRIPCION, ctypes.byref(ent), None, None,
                                           CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(salida))
        else:
            ok = _crypt32.CryptUnprotectData(ctypes.byref(entrada), None, ctypes.byref(ent), None, None,
                                             CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(salida))
        if not ok:
            codigo = ctypes.get_last_error()
            raise ErrorDpapi(codigo, 'DPAPI no pudo ' + ('cifrar' if proteger else 'descifrar') + f' (error {codigo})')
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.memset(b_datos, 0, max(1, len(datos)))
        if salida.pbData:
            ctypes.memset(salida.pbData, 0, salida.cbData)
            _kernel32.LocalFree(salida.pbData)


def proteger(datos: bytes, entropia: bytes) -> bytes:
    """Cifra `datos` para el usuario actual de Windows."""
    return _llamar(datos, entropia, True)


def desproteger(blob: bytes, entropia: bytes) -> bytes:
    """Descifra un blob de `proteger`. ErrorDpapi si la entropía no coincide o el blob está alterado."""
    return _llamar(blob, entropia, False)
