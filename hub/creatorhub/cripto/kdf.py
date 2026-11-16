"""Derivación de claves (04 §C.6; 03 §7.5): HKDF-SHA256 (RFC 5869) y PBKDF2-HMAC-SHA256, solo hashlib/hmac."""
from __future__ import annotations

import hashlib
import hmac

ITERACIONES_EMPAREJAMIENTO = 200_000


def hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, n: int = 32) -> bytes:
    """HKDF-SHA256 (extract + expand). salt vacío = 32 ceros (igual que ProtocoloLan.java: Java no admite llave HMAC
    vacía y RFC 5869 define el salt ausente como HashLen ceros)."""
    if not 0 < n <= 255 * 32:
        raise ValueError('longitud HKDF fuera de rango')
    prk = hmac.new(salt or b'\x00' * 32, ikm, hashlib.sha256).digest()
    okm, t, i = b'', b'', 1
    while len(okm) < n:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
        i += 1
    return okm[:n]


def pbkdf2_sha256(clave: bytes | str, sal: bytes | str, iteraciones: int, n: int = 32) -> bytes:
    """PBKDF2-HMAC-SHA256. Las cadenas se codifican en UTF-8."""
    if iteraciones < 1:
        raise ValueError('iteraciones debe ser ≥ 1')
    c = clave.encode('utf-8') if isinstance(clave, str) else clave
    s = sal.encode('utf-8') if isinstance(sal, str) else sal
    return hashlib.pbkdf2_hmac('sha256', c, s, iteraciones, n)


def hmac_sha256(clave: bytes, datos: bytes) -> bytes:
    return hmac.new(clave, datos, hashlib.sha256).digest()
