"""AES-GCM con Windows CNG (bcrypt.dll) por ctypes (v04_cripto.py §4; protocolo_lan.py).

Clave de 16/24/32 bytes, nonce de 12 bytes, etiqueta de 16 bytes. La salida es `cifrado || etiqueta`, igual que
`javax.crypto` `AES/GCM/NoPadding` en Android. Los búferes son locales a cada llamada: una misma instancia se puede usar
desde varios hilos. Una etiqueta que no coincide lanza `ErrorCng` con `args[0] == STATUS_AUTH_TAG_MISMATCH`.
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

STATUS_AUTH_TAG_MISMATCH = 0xC000A002
_bcrypt = ctypes.WinDLL('bcrypt')
_H = ctypes.c_void_p


class ErrorCng(OSError):
    """Una llamada a CNG devolvió un NTSTATUS distinto de 0."""


class _AuthInfo(ctypes.Structure):   # BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO
    _fields_ = [('cbSize', wintypes.ULONG), ('dwInfoVersion', wintypes.ULONG),
                ('pbNonce', ctypes.c_void_p), ('cbNonce', wintypes.ULONG),
                ('pbAuthData', ctypes.c_void_p), ('cbAuthData', wintypes.ULONG),
                ('pbTag', ctypes.c_void_p), ('cbTag', wintypes.ULONG),
                ('pbMacContext', ctypes.c_void_p), ('cbMacContext', wintypes.ULONG),
                ('cbAAD', wintypes.ULONG), ('cbData', ctypes.c_ulonglong), ('dwFlags', wintypes.ULONG)]


def _nt(st: int, que: str) -> None:
    st &= 0xFFFFFFFF
    if st:
        raise ErrorCng(st, f'{que}: NTSTATUS 0x{st:08X}')


_alg: _H | None = None
_candado_alg = threading.Lock()


def _proveedor() -> _H:
    global _alg
    with _candado_alg:
        if _alg is None:
            h = _H()
            _nt(_bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(h), ctypes.c_wchar_p('AES'), None, 0), 'OpenAlgorithm')
            modo = ctypes.create_unicode_buffer('ChainingModeGCM')
            _nt(_bcrypt.BCryptSetProperty(h, ctypes.c_wchar_p('ChainingMode'), modo, ctypes.sizeof(modo), 0),
                'SetProperty')
            _alg = h
        return _alg


class AesGcm:
    """AES-GCM sobre una clave CNG. `cifrar(nonce, claro, aad) -> cifrado||tag` · `descifrar(nonce, cifrado||tag, aad)`."""

    def __init__(self, clave: bytes) -> None:
        if len(clave) not in (16, 24, 32):
            raise ValueError('la clave AES debe tener 16, 24 o 32 bytes')
        self._k = _H()
        kb = ctypes.create_string_buffer(bytes(clave), len(clave))
        try:
            _nt(_bcrypt.BCryptGenerateSymmetricKey(_proveedor(), ctypes.byref(self._k), None, 0, kb, len(clave), 0),
                'GenerateKey')
        finally:
            ctypes.memset(kb, 0, len(clave))

    def __del__(self) -> None:
        k = getattr(self, '_k', None)
        if k:
            _bcrypt.BCryptDestroyKey(k)
            self._k = None

    @staticmethod
    def _info(nonce: bytes, aad: bytes, tag: ctypes.Array) -> tuple[_AuthInfo, tuple]:
        if len(nonce) != 12:
            raise ValueError('el nonce de GCM debe tener 12 bytes')
        i = _AuthInfo()
        i.cbSize, i.dwInfoVersion = ctypes.sizeof(_AuthInfo), 1
        bufs = (ctypes.create_string_buffer(nonce, len(nonce)), ctypes.create_string_buffer(aad, max(1, len(aad))), tag)
        i.pbNonce, i.cbNonce = ctypes.cast(bufs[0], ctypes.c_void_p), len(nonce)
        if aad:
            i.pbAuthData, i.cbAuthData = ctypes.cast(bufs[1], ctypes.c_void_p), len(aad)
        i.pbTag, i.cbTag = ctypes.cast(tag, ctypes.c_void_p), 16
        return i, bufs

    def cifrar(self, nonce: bytes, claro: bytes, aad: bytes = b'') -> bytes:
        tag = ctypes.create_string_buffer(16)
        info, _bufs = self._info(nonce, aad, tag)
        ent = ctypes.create_string_buffer(claro, max(1, len(claro)))
        sal = ctypes.create_string_buffer(max(1, len(claro)))
        n = wintypes.ULONG()
        try:
            _nt(_bcrypt.BCryptEncrypt(self._k, ent if claro else None, len(claro), ctypes.byref(info), None, 0,
                                      sal if claro else None, len(claro), ctypes.byref(n), 0), 'Encrypt')
            return sal.raw[:len(claro)] + tag.raw
        finally:
            ctypes.memset(ent, 0, max(1, len(claro)))

    def descifrar(self, nonce: bytes, cifrado_y_tag: bytes, aad: bytes = b'') -> bytes:
        if len(cifrado_y_tag) < 16:
            raise ValueError('cifrado demasiado corto')
        ct, t = cifrado_y_tag[:-16], cifrado_y_tag[-16:]
        tag = ctypes.create_string_buffer(t, 16)
        info, _bufs = self._info(nonce, aad, tag)
        ent = ctypes.create_string_buffer(ct, max(1, len(ct)))
        sal = ctypes.create_string_buffer(max(1, len(ct)))
        n = wintypes.ULONG()
        _nt(_bcrypt.BCryptDecrypt(self._k, ent if ct else None, len(ct), ctypes.byref(info), None, 0,
                                  sal if ct else None, len(ct), ctypes.byref(n), 0), 'Decrypt')
        return sal.raw[:len(ct)]


def cifrar(clave: bytes, nonce: bytes, claro: bytes, aad: bytes = b'') -> bytes:
    return AesGcm(clave).cifrar(nonce, claro, aad)


def descifrar(clave: bytes, nonce: bytes, cifrado_y_tag: bytes, aad: bytes = b'') -> bytes:
    return AesGcm(clave).descifrar(nonce, cifrado_y_tag, aad)
