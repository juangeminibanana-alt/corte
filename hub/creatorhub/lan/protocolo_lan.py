"""Protocolo LAN 1 del lado del hub (spec/contrato.ts «Protocolo LAN 1 · NORMATIVO»; 04 §C.4–§C.7; 03 §6.6 y §7.5).

Portado de spec/pruebas/protocolo_lan/protocolo_lan.py con la MISMA salida byte a byte (vectores en
spec/pruebas/protocolo_lan/vectores_emparejamiento.json y spec/verificacion/vectores_ch1.json, que también verifica
ProtocoloLan.java del APK). Las primitivas son las de `creatorhub.cripto` (HKDF/PBKDF2 con hashlib y AES-256-GCM con
CNG) y la canonicalización CH1 es `creatorhub.comun.canonico_ruta_query`.

Única diferencia de comportamiento con la referencia: el alias por omisión es «PC » + host_id[0:4] en mayúsculas
(BUILD §1, C38), el MISMO en hello, UDP, LanPaquete y LanEstado. El formato del datagrama no cambia.

Nada de este módulo registra ni devuelve en texto un secreto: el código, K_pair, la prueba, device_key y el paquete solo
viajan como valores de retorno.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import urllib.parse
from typing import Any, Sequence

from ..comun import canonico_ruta_query
from ..cripto import cng_aesgcm, kdf

PROTOCOLO = 1
APP = 'creator-hub'
ESQUEMA_AUTH = 'CH1-HMAC-SHA256'
CROCKFORD = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'       # base32 de Crockford: sin I, L, O ni U
SAL_K_PAIR = 'creatorhub-pair-v1|'
SAL_K_MAC = b'creatorhub/lan/v1'
INFO_K_MAC = b'mac'
INFO_K_ENC = b'CH1-PAQUETE'
ITERACIONES_K_PAIR = kdf.ITERACIONES_EMPAREJAMIENTO   # 200 000 (04 §C.6)
MAX_IPS_QR = 3
MAX_ALIAS = 40
MAX_NOMBRE_CELULAR = 40
MAX_PREGUNTA_UDP = 160
MAX_RESPUESTA_UDP = 512

_RE_CODIGO = re.compile(r'^[0-9A-HJKMNP-TV-Z]{12}$')
_RE_HEX32 = re.compile(r'^[0-9a-f]{32}$')
_RE_HEX64 = re.compile(r'^[0-9a-f]{64}$')
_RE_B64U = re.compile(r'^[A-Za-z0-9_-]*$')
_RE_NONCE_CH1 = re.compile(r'^[A-Za-z0-9_-]{16,64}$')
_RE_SIG = re.compile(r'^[A-Za-z0-9_-]{43}$')


# ------------------------------------------------------------------ utilidades
def b64u(b: bytes) -> str:
    """base64url SIN relleno (así viaja todo en el protocolo)."""
    return base64.urlsafe_b64encode(b).rstrip(b'=').decode('ascii')


def b64u_dec(s: str) -> bytes:
    if not isinstance(s, str) or not _RE_B64U.match(s) or len(s) % 4 == 1:
        raise ValueError('base64url inválido')
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def es_host_id(s: Any) -> bool:
    return isinstance(s, str) and bool(_RE_HEX32.match(s))


def es_huella(s: Any) -> bool:
    return isinstance(s, str) and bool(_RE_HEX64.match(s))


def huella_a_b64u(huella_hex: str) -> str:
    if not es_huella(huella_hex):
        raise ValueError('huella inválida')
    return b64u(bytes.fromhex(huella_hex))


def huella_a_hex(f: str) -> str:
    b = b64u_dec(f)
    if len(b) != 32:
        raise ValueError('huella inválida')
    return b.hex()


def nuevo_nonce() -> str:
    """nonce_c / nonce_s / nonce de CH1: b64url sin relleno de 16 bytes aleatorios (22 caracteres)."""
    return b64u(secrets.token_bytes(16))


def nonce_emparejamiento_valido(n: Any) -> bool:
    try:
        return isinstance(n, str) and len(b64u_dec(n)) == 16
    except ValueError:
        return False


def nuevo_host_id() -> str:
    return secrets.token_hex(16)


# ------------------------------------------------------------------ código manual (C6, 04 §C.4)
def generar_codigo() -> str:
    """12 caracteres Crockford al azar (60 bits), normalizado y sin guiones."""
    return ''.join(secrets.choice(CROCKFORD) for _ in range(12))


def formatear_codigo(codigo: str) -> str:
    """'K7QM3XRA9TPF' -> 'K7QM-3XRA-9TPF' (EmparejarResponse.codigo_manual)."""
    c = c_norm(codigo)
    return f'{c[:4]}-{c[4:8]}-{c[8:]}'


def c_norm(codigo: str) -> str:
    """Mayúsculas, sin guiones ni espacios, O→0, I/L→1. Debe quedar en 12 caracteres Crockford (sin I L O U)."""
    if not isinstance(codigo, str):
        raise ValueError('código inválido')
    s = codigo.upper().replace('-', '').replace(' ', '').replace('O', '0').replace('I', '1').replace('L', '1')
    if not _RE_CODIGO.match(s):
        raise ValueError('código inválido')
    return s


# ------------------------------------------------------------------ emparejamiento (04 §C.6)
def k_pair(codigo: str, host_id: str) -> bytes:
    """PBKDF2-HMAC-SHA256(C_norm, 'creatorhub-pair-v1|' + host_id, 200 000, 32)."""
    if not es_host_id(host_id):
        raise ValueError('host_id inválido')
    return kdf.pbkdf2_sha256(c_norm(codigo).encode('ascii'), (SAL_K_PAIR + host_id).encode('ascii'),
                             ITERACIONES_K_PAIR, 32)


def prueba(kp: bytes, nonce_c: str, huella_hex: str, nombre: str) -> str:
    """b64url(HMAC-SHA256(K_pair, 'CH1-PAIR|' + nonce_c + '|' + huella_observada_hex + '|' + nombre))."""
    return b64u(kdf.hmac_sha256(kp, f'CH1-PAIR|{nonce_c}|{huella_hex}|{nombre}'.encode('utf-8')))


def prueba_correcta(kp: bytes, nonce_c: str, huella_hex: str, nombre: str, recibida: str) -> bool:
    """Compara en tiempo constante con la prueba calculada con la huella PROPIA del hub (04 §C.6)."""
    if not isinstance(recibida, str):
        return False
    return hmac.compare_digest(prueba(kp, nonce_c, huella_hex, nombre).encode('ascii'),
                               recibida.encode('utf-8', 'replace'))


def sas(kp: bytes, nonce_c: str, nonce_s: str) -> str:
    """Número de verificación de 4 dígitos que muestran la PC y el celular."""
    d = kdf.hmac_sha256(kp, f'CH1-SAS|{nonce_c}|{nonce_s}'.encode('ascii'))
    return '%04d' % (int.from_bytes(d[:4], 'big') % 10000)


def k_enc(kp: bytes, nonce_c: str, nonce_s: str) -> bytes:
    """HKDF-SHA256(K_pair, salt = nonce_c ‖ nonce_s (decodificados), info = 'CH1-PAQUETE', 32)."""
    return kdf.hkdf_sha256(kp, b64u_dec(nonce_c) + b64u_dec(nonce_s), INFO_K_ENC)


def sellar(clave: bytes, iv: bytes, claro: bytes, aad: str) -> str:
    """b64url( iv(12) || AES-256-GCM(clave, iv, claro, aad=UTF-8(aad)) ) con cifrado||etiqueta(16)."""
    if len(iv) != 12:
        raise ValueError('iv de 12 bytes')
    return b64u(iv + cng_aesgcm.AesGcm(clave).cifrar(iv, claro, aad.encode('utf-8')))


def abrir(clave: bytes, sellado: str, aad: str) -> bytes:
    crudo = b64u_dec(sellado)
    if len(crudo) < 12 + 16:
        raise ValueError('paquete demasiado corto')
    return cng_aesgcm.AesGcm(clave).descifrar(crudo[:12], crudo[12:], aad.encode('utf-8'))


def paquete_claro(device_id: str, device_key: bytes, host_id: str, nombre_equipo: str, puerto: int, permisos: str,
                  huella_hex: str) -> bytes:
    """LanPaquete en JSON UTF-8 compacto, con el orden de claves de los vectores."""
    return json.dumps({'device_id': device_id, 'device_key': b64u(device_key), 'host_id': host_id,
                       'nombre_equipo': nombre_equipo, 'puerto': int(puerto), 'protocolo': PROTOCOLO,
                       'permisos': permisos, 'huella_tls': huella_hex},
                      separators=(',', ':'), ensure_ascii=False).encode('utf-8')


# ------------------------------------------------------------------ CH1 (firma de cada petición, 04 §C.7)
def canon_ruta_query(ruta_query: str) -> str:
    """RFC 3986 de 03 §6.6: idéntica a comun.canonico_ruta_query y a ProtocoloLan.canonRutaQuery (vectores_ch1.json)."""
    return canonico_ruta_query(ruta_query)


def canonico(metodo: str, ruta_query: str, ts: int, nonce: str, cuerpo: bytes) -> bytes:
    return '\n'.join(['CH1', metodo.upper(), canon_ruta_query(ruta_query), str(ts), nonce,
                      hashlib.sha256(cuerpo or b'').hexdigest()]).encode('utf-8')


def k_mac(device_key: bytes) -> bytes:
    return kdf.hkdf_sha256(device_key, SAL_K_MAC, INFO_K_MAC)


def firma(kmac: bytes, canon: bytes) -> str:
    return b64u(kdf.hmac_sha256(kmac, canon))


def firmar(device_id: str, device_key: bytes, metodo: str, ruta_query: str, cuerpo: bytes, ts: int, nonce: str) -> str:
    """Cabecera Authorization completa (la usa el cliente; el hub solo verifica)."""
    sig = firma(k_mac(device_key), canonico(metodo, ruta_query, ts, nonce, cuerpo))
    return f'{ESQUEMA_AUTH} device={device_id}, ts={ts}, nonce={nonce}, sig={sig}'


def leer_autorizacion(cabecera: str) -> dict[str, Any]:
    """-> {device, ts, nonce, sig}. ValueError si el formato no es EXACTO (campos device, ts, nonce, sig)."""
    if not isinstance(cabecera, str) or len(cabecera) > 512:
        raise ValueError('cabecera')
    esquema, _, resto = cabecera.partition(' ')
    if esquema != ESQUEMA_AUTH:
        raise ValueError('esquema')
    campos: dict[str, Any] = {}
    for parte in resto.split(','):
        k, sep, v = parte.strip().partition('=')
        if not sep or k in campos:
            raise ValueError('campo')
        campos[k] = v
    if set(campos) != {'device', 'ts', 'nonce', 'sig'} or not (campos['ts'].isascii() and campos['ts'].isdigit()) \
            or len(campos['ts']) > 12:
        raise ValueError('campos')
    if not _RE_NONCE_CH1.match(campos['nonce']) or not _RE_SIG.match(campos['sig']):
        raise ValueError('nonce o firma')
    campos['ts'] = int(campos['ts'])
    return campos


# ------------------------------------------------------------------ QR / enlace (04 §C.4)
def qr_texto(host_id: str, ips: Sequence[str], puerto: int, codigo: str, huella_hex: str) -> str:
    """creatorhub://pair?v=1&h=<host_id>&a=<ip>[,<ip>…≤3]&p=<puerto>&s=<código 12>&f=<huella b64url 43>."""
    return (f'creatorhub://pair?v={PROTOCOLO}&h={host_id}&a={",".join(list(ips)[:MAX_IPS_QR])}&p={int(puerto)}'
            f'&s={c_norm(codigo)}&f={huella_a_b64u(huella_hex)}')


def leer_qr(texto: str) -> dict[str, Any]:
    u = urllib.parse.urlsplit(texto)
    if u.scheme != 'creatorhub' or u.netloc != 'pair':
        raise ValueError('no es un enlace de emparejamiento')
    q = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True))
    if q.get('v') != '1' or not es_host_id(q.get('h', '')):
        raise ValueError('versión o host_id')
    ips = [x for x in q.get('a', '').split(',') if x][:MAX_IPS_QR]
    return {'v': 1, 'host_id': q['h'], 'ips': ips, 'puerto': int(q['p']), 'codigo': c_norm(q['s']),
            'huella_hex': huella_a_hex(q['f'])}


# ------------------------------------------------------------------ descubrimiento UDP
def pregunta_descubrimiento(nonce_hex: str) -> bytes:
    if not es_host_id(nonce_hex):                        # mismo formato: 32 hex minúsculas
        raise ValueError('nonce')
    return f'CREATORHUB_DESCUBRIR {PROTOCOLO} {nonce_hex}'.encode('ascii')


def leer_pregunta(datos: bytes) -> str | None:
    """-> nonce o None (se ignora en silencio todo lo que no sea exacto)."""
    if len(datos) > MAX_PREGUNTA_UDP:
        return None
    partes = datos.decode('ascii', 'replace').split(' ')
    if len(partes) != 3 or partes[0] != 'CREATORHUB_DESCUBRIR' or partes[1] != '1' or not es_host_id(partes[2]):
        return None
    return partes[2]


def respuesta_descubrimiento(host_id: str, nombre_equipo: str, puerto: int, huella_hex: str, nonce_hex: str) -> bytes:
    return json.dumps({'app': APP, 'v': PROTOCOLO, 'host_id': host_id, 'nombre_equipo': nombre_equipo,
                       'puerto': int(puerto), 'huella': huella_hex, 'nonce': nonce_hex},
                      separators=(',', ':'), ensure_ascii=False).encode('utf-8')


# ------------------------------------------------------------------ alias de la PC (BUILD §1, C38)
def alias_por_omision(host_id: str) -> str:
    """'PC ' + host_id[0:4] en mayúsculas («PC 3F2A»). NUNCA el nombre de Windows ni del usuario."""
    return 'PC ' + host_id[:4].upper()


def validar_alias(nombre: Any) -> str:
    """LanCambios.nombre_equipo: 1–40 caracteres imprimibles, sin saltos de línea (se recortan los espacios)."""
    if not isinstance(nombre, str) or not nombre.isprintable():      # ningún salto de línea ni control, ni en orillas
        raise ValueError('alias')
    n = nombre.strip(' ')
    if not 1 <= len(n) <= MAX_ALIAS:
        raise ValueError('alias')
    return n


def validar_nombre_celular(nombre: Any) -> str:
    """LanPairStartRequest.nombre: texto exacto del JSON (entra en la prueba), 1–40 caracteres imprimibles."""
    if not isinstance(nombre, str) or not 1 <= len(nombre) <= MAX_NOMBRE_CELULAR or not nombre.isprintable() \
            or not nombre.strip():
        raise ValueError('nombre')
    return nombre
