"""Primitivas criptográficas del hub sin dependencias (BUILD_SPEC C29): solo stdlib + Windows por ctypes.

- `dpapi`: CryptProtectData/CryptUnprotectData (usuario actual, entropía por propósito).
- `cng_aesgcm`: AES-GCM con bcrypt.dll (CNG), seguro entre hilos.
- `kdf`: HKDF-SHA256 (RFC 5869) y PBKDF2-HMAC-SHA256.
- `tls_cng`: identidad TLS (ECDSA P-256 + X.509 autofirmado + PKCS#8 cifrado) generada con CNG.

Los submódulos cargan sus DLL al importarse: este paquete no importa ninguno para no pesar en el arranque.
"""
from __future__ import annotations
