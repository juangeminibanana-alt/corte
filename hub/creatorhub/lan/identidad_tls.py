"""Identidad TLS del hub para la LAN (03 §6.6, §7.1; 04 §C.3): ECDSA P-256 autofirmada generada con CNG por
`creatorhub.cripto.tls_cng` (hub-andamio) UNA vez, al activar la LAN.

- `secretos/tls_llave.pem`: PKCS#8 CIFRADO · `secretos/tls_clave.dpapi`: su contraseña con DPAPI · `tls/hub_cert.pem`.
- `contexto(rutas)` -> (ssl.SSLContext de servidor TLS ≥ 1.2 con ALPN http/1.1, huella hex del DER). OpenSSL descifra la
  llave en memoria: nunca queda en claro en disco.
- Si la identidad guardada no se puede usar (otro perfil de Windows, archivo dañado), se aparta con el sufijo
  `.ilegible-<epoch>` (nunca se sobrescribe) y se genera otra: los celulares tendrán que volver a emparejarse.
"""
from __future__ import annotations

import logging
import os
import ssl
import threading
import time

from ..cripto import dpapi, tls_cng
from ..interfaces import Rutas

_log = logging.getLogger('creatorhub.lan.identidad')
_candado = threading.Lock()


def _archivos(rutas: Rutas) -> tuple[str, str, str]:
    return (os.path.join(rutas.secretos, tls_cng.NOMBRE_LLAVE), os.path.join(rutas.secretos, tls_cng.NOMBRE_CLAVE),
            os.path.join(rutas.tls, tls_cng.NOMBRE_CERT))


def existe(rutas: Rutas) -> bool:
    return tls_cng.existe_identidad(rutas.secretos, rutas.tls)


def huella_guardada(rutas: Rutas) -> str | None:
    """Huella (SHA-256 hex del DER) del certificado guardado, o None si todavía no hay identidad."""
    ruta = _archivos(rutas)[2]
    try:
        with open(ruta, 'rb') as f:
            return tls_cng.huella_de_pem(f.read())
    except (OSError, ValueError):
        return None


def _apartar(rutas: Rutas) -> None:
    sufijo = f'.ilegible-{int(time.time())}'
    for ruta in _archivos(rutas):
        if os.path.exists(ruta):
            try:
                os.replace(ruta, ruta + sufijo)
            except OSError:
                _log.warning('No se pudo apartar %s', os.path.basename(ruta))


def contexto(rutas: Rutas) -> tuple[ssl.SSLContext, str]:
    """Carga (o genera la primera vez) la identidad y devuelve (contexto de servidor, huella hex)."""
    with _candado:
        if existe(rutas):
            try:
                return tls_cng.contexto_servidor(rutas.secretos, rutas.tls)
            except (ssl.SSLError, dpapi.ErrorDpapi, OSError, ValueError) as e:
                _log.warning('La identidad TLS guardada no se puede usar (%s): se genera otra', type(e).__name__)
                _apartar(rutas)
        huella = tls_cng.generar_y_guardar(rutas.secretos, rutas.tls)
        _log.info('Identidad TLS nueva para la LAN (huella %s…)', huella[:12])
        return tls_cng.contexto_servidor(rutas.secretos, rutas.tls)


def borrar(rutas: Rutas) -> None:
    """Quita la identidad (Borrar todo): los celulares tendrán que volver a emparejarse."""
    with _candado:
        for ruta in _archivos(rutas):
            try:
                os.remove(ruta)
            except FileNotFoundError:
                pass
