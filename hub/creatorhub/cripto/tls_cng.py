"""Identidad TLS del hub SIN dependencias nuevas (03 §7.4; 04 §A.10, §C.3). Portado de spec/verificacion/tls_cng.py y
spec/pruebas/tls_hub_min/generar_certificado.py.

ECDSA P-256 y AES-256-CBC con Windows CNG (bcrypt.dll, ctypes); X.509 v3 autofirmado y PKCS#8 CIFRADO (PBES2:
PBKDF2-HMAC-SHA256 + AES-256-CBC) armados en DER a mano. `ssl.SSLContext.load_cert_chain(cert, llave, password=…)` carga
el resultado: la llave privada NUNCA queda en claro en disco; su contraseña aleatoria va con DPAPI.

Archivos (03 §1): `secretos/tls_llave.pem` (PKCS#8 cifrado) · `secretos/tls_clave.dpapi` (contraseña, entropía
"CreatorHub/tls/v1") · `tls/hub_cert.pem` (público; su SHA-256 del DER es la huella que fija el celular).

Plan B de 04 §F.6 (si Conscrypt rechazara el DER armado a mano): generar el certificado con
`CertCreateSelfSignCertificate` (crypt32) y exportar la llave por CNG. Está AISLADO en `_generar_identidad_plan_b` y
solo se usa si el orquestador lo pide tras la prueba Conscrypt de android-shell (`activar_plan_b(True)`); hoy no está
implementado y `generar_identidad()` usa siempre el camino probado.
"""
from __future__ import annotations

import base64
import ctypes
import datetime as dt
import hashlib
import os
import secrets
import ssl
from ctypes import wintypes
from typing import NamedTuple

from ..comun import escribir_atomico
from . import dpapi

CN_POR_OMISION = 'Creator Hub (PC)'
NOMBRE_LLAVE = 'tls_llave.pem'
NOMBRE_CLAVE = 'tls_clave.dpapi'
NOMBRE_CERT = 'hub_cert.pem'
_bcrypt = ctypes.WinDLL('bcrypt')
_H = ctypes.c_void_p
BCRYPT_BLOCK_PADDING = 0x1


class IdentidadTls(NamedTuple):
    cert_pem: bytes
    llave_pem: bytes          # PKCS#8 cifrado (ENCRYPTED PRIVATE KEY)
    contrasena: bytes         # 43 caracteres base64url (32 bytes aleatorios): se guarda SOLO con DPAPI
    huella: str               # SHA-256 del DER del certificado, hex minúsculas (64)


def _nt(st: int, que: str) -> None:
    st &= 0xFFFFFFFF
    if st:
        raise OSError(st, f'{que}: NTSTATUS 0x{st:08X}')


# ------------------------------------------------------------------ DER mínimo
def _len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, 'big')
    return bytes([0x80 | len(b)]) + b


def tlv(tag: int, v: bytes) -> bytes:
    return bytes([tag]) + _len(len(v)) + v


def seq(*xs: bytes) -> bytes:
    return tlv(0x30, b''.join(xs))


def conj(*xs: bytes) -> bytes:
    return tlv(0x31, b''.join(xs))


def entero(i: int | bytes) -> bytes:
    if isinstance(i, bytes):
        i = int.from_bytes(i, 'big')
    b = i.to_bytes(max(1, (i.bit_length() + 7) // 8), 'big')
    if b[0] & 0x80:
        b = b'\x00' + b
    return tlv(0x02, b)


def oid(s: str) -> bytes:
    a = [int(x) for x in s.split('.')]
    out = bytearray([40 * a[0] + a[1]])
    for n in a[2:]:
        parte = [n & 0x7F]
        n >>= 7
        while n:
            parte.append(0x80 | (n & 0x7F))
            n >>= 7
        out += bytes(reversed(parte))
    return tlv(0x06, bytes(out))


def bits(b: bytes) -> bytes:
    return tlv(0x03, b'\x00' + b)


def octetos(b: bytes) -> bytes:
    return tlv(0x04, b)


def ctx(n: int, v: bytes) -> bytes:
    return tlv(0xA0 | n, v)


def utf8(s: str) -> bytes:
    return tlv(0x0C, s.encode('utf-8'))


def utc(t: dt.datetime) -> bytes:
    return tlv(0x17, t.strftime('%y%m%d%H%M%SZ').encode())


NULO = b'\x05\x00'
VERDADERO = b'\x01\x01\xff'
OID_EC, OID_P256, OID_ECDSA_SHA256 = '1.2.840.10045.2.1', '1.2.840.10045.3.1.7', '1.2.840.10045.4.3.2'


# ------------------------------------------------------------------ CNG
def _generar_ecdsa_p256() -> tuple[_H, _H, bytes, bytes, bytes]:
    """-> (proveedor, llave, x, y, d). La llave se genera en CNG; d se exporta solo para cifrarla de inmediato."""
    alg, k = _H(), _H()
    _nt(_bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(alg), ctypes.c_wchar_p('ECDSA_P256'), None, 0), 'OpenAlgorithm')
    try:
        _nt(_bcrypt.BCryptGenerateKeyPair(alg, ctypes.byref(k), 256, 0), 'GenerateKeyPair')
        _nt(_bcrypt.BCryptFinalizeKeyPair(k, 0), 'FinalizeKeyPair')
        n = wintypes.ULONG()
        _nt(_bcrypt.BCryptExportKey(k, None, ctypes.c_wchar_p('ECCPRIVATEBLOB'), None, 0, ctypes.byref(n), 0),
            'ExportKey(tam)')
        buf = ctypes.create_string_buffer(n.value)
        _nt(_bcrypt.BCryptExportKey(k, None, ctypes.c_wchar_p('ECCPRIVATEBLOB'), buf, n.value, ctypes.byref(n), 0),
            'ExportKey')
        raw = buf.raw[:n.value]
        ctypes.memset(buf, 0, n.value)
    except BaseException:
        if k:
            _bcrypt.BCryptDestroyKey(k)
        _bcrypt.BCryptCloseAlgorithmProvider(alg, 0)
        raise
    cb = int.from_bytes(raw[4:8], 'little')                 # BCRYPT_ECCKEY_BLOB {dwMagic, cbKey} + X + Y + d
    return alg, k, raw[8:8 + cb], raw[8 + cb:8 + 2 * cb], raw[8 + 2 * cb:8 + 3 * cb]


def _firmar_sha256(k: _H, datos: bytes) -> bytes:
    h = hashlib.sha256(datos).digest()
    hb = ctypes.create_string_buffer(h, 32)
    sig = ctypes.create_string_buffer(64)
    n = wintypes.ULONG()
    _nt(_bcrypt.BCryptSignHash(k, None, hb, 32, sig, 64, ctypes.byref(n), 0), 'SignHash')
    return seq(entero(sig.raw[:32]), entero(sig.raw[32:64]))       # ECDSA-Sig-Value (DER)


def _aes256_cbc(clave: bytes, iv: bytes, claro: bytes) -> bytes:
    alg, k = _H(), _H()
    _nt(_bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(alg), ctypes.c_wchar_p('AES'), None, 0), 'OpenAlgorithm')
    try:
        modo = ctypes.create_unicode_buffer('ChainingModeCBC')
        _nt(_bcrypt.BCryptSetProperty(alg, ctypes.c_wchar_p('ChainingMode'), modo, ctypes.sizeof(modo), 0), 'SetProperty')
        kb = ctypes.create_string_buffer(clave, len(clave))
        _nt(_bcrypt.BCryptGenerateSymmetricKey(alg, ctypes.byref(k), None, 0, kb, len(clave), 0), 'GenerateKey')
        ctypes.memset(kb, 0, len(clave))
        ent = ctypes.create_string_buffer(claro, len(claro))
        ivb = ctypes.create_string_buffer(iv, 16)             # CNG modifica el IV: copia
        n_sal = len(claro) + 16 - len(claro) % 16
        sal = ctypes.create_string_buffer(n_sal)
        n = wintypes.ULONG()
        _nt(_bcrypt.BCryptEncrypt(k, ent, len(claro), None, ivb, 16, sal, n_sal, ctypes.byref(n), BCRYPT_BLOCK_PADDING),
            'Encrypt')
        ctypes.memset(ent, 0, len(claro))
        return sal.raw[:n.value]
    finally:
        if k:
            _bcrypt.BCryptDestroyKey(k)
        _bcrypt.BCryptCloseAlgorithmProvider(alg, 0)


def _pem(etiqueta: str, der: bytes) -> bytes:
    b = base64.b64encode(der).decode()
    return (f'-----BEGIN {etiqueta}-----\n' + '\n'.join(b[i:i + 64] for i in range(0, len(b), 64))
            + f'\n-----END {etiqueta}-----\n').encode()


def huella_de_pem(cert_pem: bytes) -> str:
    """SHA-256 (hex) del DER de un certificado PEM: la identidad que fija el celular."""
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert_pem.decode('ascii'))).hexdigest()


# ------------------------------------------------------------------ plan B (04 §F.6), aislado
_PLAN_B = False


def activar_plan_b(activo: bool) -> None:
    """Solo si el orquestador lo pide tras la prueba Conscrypt de android-shell (BUILD §7.3)."""
    global _PLAN_B
    _PLAN_B = bool(activo)


def plan_b_activo() -> bool:
    return _PLAN_B


def _generar_identidad_plan_b(cn: str, anios: int, ahora: dt.datetime | None, iteraciones: int) -> IdentidadTls:
    """Punto aislado del plan B: CertCreateSelfSignCertificate (crypt32) + llave exportada por CNG. Sin implementar
    mientras la prueba Conscrypt no lo exija; el resto del hub no cambia (misma IdentidadTls, mismos archivos)."""
    raise NotImplementedError('Plan B de 04 §F.6 (CertCreateSelfSignCertificate) sin activar: lo decide el orquestador '
                              'después de la prueba Conscrypt de android-shell.')


# ------------------------------------------------------------------ identidad
def generar_identidad(cn: str = CN_POR_OMISION, anios: int = 10, ahora: dt.datetime | None = None,
                      iteraciones: int = 100_000) -> IdentidadTls:
    """-> IdentidadTls(cert_pem, llave_pem_cifrada, contrasena, huella_hex). Se desempaca como la tupla de referencia."""
    if _PLAN_B:
        return _generar_identidad_plan_b(cn, anios, ahora, iteraciones)
    ahora = ahora or dt.datetime.now(dt.timezone.utc)
    alg, k, x, y, d = _generar_ecdsa_p256()
    try:
        pub = b'\x04' + x + y
        spki = seq(seq(oid(OID_EC), oid(OID_P256)), bits(pub))
        nombre = seq(conj(seq(oid('2.5.4.3'), utf8(cn))))
        alg_firma = seq(oid(OID_ECDSA_SHA256))
        validez = seq(utc(ahora - dt.timedelta(days=2)), utc(ahora + dt.timedelta(days=365 * anios)))  # relojes atrasados
        exts = ctx(3, seq(
            seq(oid('2.5.29.19'), VERDADERO, octetos(seq())),                       # basicConstraints CA=false
            seq(oid('2.5.29.15'), VERDADERO, octetos(tlv(0x03, b'\x07\x80'))),      # keyUsage digitalSignature
            seq(oid('2.5.29.37'), octetos(seq(oid('1.3.6.1.5.5.7.3.1')))),          # extKeyUsage serverAuth
            seq(oid('2.5.29.14'), octetos(octetos(hashlib.sha1(pub).digest()))),    # subjectKeyIdentifier
        ))
        serie = int.from_bytes(secrets.token_bytes(16), 'big') >> 1
        tbs = seq(ctx(0, entero(2)), entero(serie), alg_firma, nombre, validez, nombre, spki, exts)
        cert_der = seq(tbs, alg_firma, bits(_firmar_sha256(k, tbs)))
        pkcs8 = seq(entero(0), seq(oid(OID_EC), oid(OID_P256)), octetos(seq(entero(1), octetos(d), ctx(1, bits(pub)))))
    finally:
        _bcrypt.BCryptDestroyKey(k)
        _bcrypt.BCryptCloseAlgorithmProvider(alg, 0)
    contrasena = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=')
    sal, iv = secrets.token_bytes(16), secrets.token_bytes(16)
    clave = hashlib.pbkdf2_hmac('sha256', contrasena, sal, iteraciones, 32)
    cifrado = _aes256_cbc(clave, iv, pkcs8)
    pbes2 = seq(oid('1.2.840.113549.1.5.13'), seq(
        seq(oid('1.2.840.113549.1.5.12'), seq(octetos(sal), entero(iteraciones), seq(oid('1.2.840.113549.2.9'), NULO))),
        seq(oid('2.16.840.1.101.3.4.1.42'), octetos(iv))))
    llave_pem = _pem('ENCRYPTED PRIVATE KEY', seq(pbes2, octetos(cifrado)))
    return IdentidadTls(_pem('CERTIFICATE', cert_der), llave_pem, contrasena, hashlib.sha256(cert_der).hexdigest())


# ------------------------------------------------------------------ disco
def guardar_identidad(identidad: IdentidadTls, dir_secretos: str, dir_tls: str) -> None:
    """Escribe llave cifrada y contraseña (DPAPI) en `dir_secretos` y el certificado en `dir_tls` (escritura atómica)."""
    if b'ENCRYPTED PRIVATE KEY' not in identidad.llave_pem or b'BEGIN PRIVATE KEY' in identidad.llave_pem:
        raise ValueError('la llave debe ir cifrada (PKCS#8 ENCRYPTED PRIVATE KEY)')
    os.makedirs(dir_secretos, exist_ok=True)
    os.makedirs(dir_tls, exist_ok=True)
    escribir_atomico(os.path.join(dir_secretos, NOMBRE_LLAVE), identidad.llave_pem)
    escribir_atomico(os.path.join(dir_secretos, NOMBRE_CLAVE), dpapi.proteger(identidad.contrasena, dpapi.ENTROPIA_TLS))
    escribir_atomico(os.path.join(dir_tls, NOMBRE_CERT), identidad.cert_pem)


def generar_y_guardar(dir_secretos: str, dir_tls: str) -> str:
    """Genera una identidad nueva, la guarda y devuelve SOLO la huella (pública)."""
    identidad = generar_identidad()
    guardar_identidad(identidad, dir_secretos, dir_tls)
    return identidad.huella


def existe_identidad(dir_secretos: str, dir_tls: str) -> bool:
    return all(os.path.isfile(p) for p in (os.path.join(dir_secretos, NOMBRE_LLAVE),
                                            os.path.join(dir_secretos, NOMBRE_CLAVE), os.path.join(dir_tls, NOMBRE_CERT)))


def contexto_servidor(dir_secretos: str, dir_tls: str) -> tuple[ssl.SSLContext, str]:
    """Carga la identidad guardada en un `ssl.SSLContext` de servidor (TLS ≥ 1.2, ALPN http/1.1). OpenSSL descifra la
    llave en memoria con la contraseña de DPAPI. -> (contexto, huella_hex). ssl.SSLError si la contraseña no sirve."""
    ruta_cert = os.path.join(dir_tls, NOMBRE_CERT)
    ruta_llave = os.path.join(dir_secretos, NOMBRE_LLAVE)
    with open(os.path.join(dir_secretos, NOMBRE_CLAVE), 'rb') as f:
        contrasena = dpapi.desproteger(f.read(), dpapi.ENTROPIA_TLS)
    with open(ruta_cert, 'rb') as f:
        huella = huella_de_pem(f.read())
    ctx_srv = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx_srv.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx_srv.set_alpn_protocols(['http/1.1'])
    ctx_srv.load_cert_chain(ruta_cert, ruta_llave, password=contrasena)
    return ctx_srv, huella
