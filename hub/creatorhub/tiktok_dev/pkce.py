"""PKCE y state para el Login Kit de ESCRITORIO de TikTok for Developers (rev. 5).

- code_verifier: 43–128 caracteres del alfabeto sin reserva de RFC 7636 ([A-Za-z0-9-._~]), nuevo en cada intento.
- code_challenge (code_challenge_method=S256): en escritorio TikTok pide el SHA-256 del verifier codificado en HEX
  (minúsculas), NO en base64url como dice RFC 7636 para web/móvil.
- state: 32 bytes aleatorios en base64url (≈ 43 caracteres), de un solo uso.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import string

ALFABETO = string.ascii_letters + string.digits + '-._~'
LARGO_VERIFIER = 64
MIN_VERIFIER, MAX_VERIFIER = 43, 128
_RE_VERIFIER = re.compile(r'[A-Za-z0-9\-._~]{43,128}')


def nuevo_verifier(largo: int = LARGO_VERIFIER) -> str:
    """code_verifier aleatorio (secrets) de `largo` caracteres del alfabeto permitido."""
    if isinstance(largo, bool) or not isinstance(largo, int) or not MIN_VERIFIER <= largo <= MAX_VERIFIER:
        raise ValueError('el code_verifier debe medir de 43 a 128 caracteres')
    return ''.join(secrets.choice(ALFABETO) for _ in range(largo))


def verifier_valido(verifier: object) -> bool:
    return isinstance(verifier, str) and _RE_VERIFIER.fullmatch(verifier) is not None


def challenge_hex(verifier: str) -> str:
    """SHA-256 del verifier en hexadecimal (64 caracteres en minúsculas): el code_challenge de escritorio."""
    if not verifier_valido(verifier):
        raise ValueError('code_verifier inválido')
    return hashlib.sha256(verifier.encode('ascii')).hexdigest()


def nuevo_state() -> str:
    return secrets.token_urlsafe(32)


__all__ = ['nuevo_verifier', 'verifier_valido', 'challenge_hex', 'nuevo_state', 'ALFABETO', 'LARGO_VERIFIER']
