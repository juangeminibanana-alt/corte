"""Firma de las llamadas a la Open API de TikTok Shop (03 §2.1, pasos 1–3).

Réplica exacta de `research/referencia/server_anterior.generate_sign` (documentación oficial «Sign your API request»):

    base = path + concat(sorted(k + v for k, v in query if k not in {sign, access_token})) + cuerpo
    sign = HMAC_SHA256(app_secret, app_secret + base + app_secret).hex()

El cuerpo se firma con los MISMOS bytes que se envían (salvo multipart/form-data, que no se firma). Nunca se registra
la firma ni la URL firmada.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Mapping

EXCLUIDAS = frozenset({'sign', 'access_token'})


def generar_firma(path: str, query: Mapping[str, Any], cuerpo: bytes | None, app_secret: str,
                  tipo_contenido: str = 'application/json') -> str:
    """Firma HMAC-SHA256 en hexadecimal (minúsculas) de una llamada a la Open API."""
    claves = sorted(k for k in query.keys() if k not in EXCLUIDAS)
    base = path + ''.join(f'{k}{query[k]}' for k in claves)
    if tipo_contenido != 'multipart/form-data' and cuerpo:
        base += cuerpo.decode('utf-8')
    envuelto = f'{app_secret}{base}{app_secret}'
    return hmac.new(app_secret.encode('utf-8'), envuelto.encode('utf-8'), hashlib.sha256).hexdigest()


def serializar_cuerpo(body: Any) -> bytes | None:
    """Bytes exactos que se firman y se envían: JSON compacto UTF-8 sin escapar (como server_anterior); sin cuerpo si
    `body` es None, {} o []."""
    if body in (None, {}, []):
        return None
    return json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
