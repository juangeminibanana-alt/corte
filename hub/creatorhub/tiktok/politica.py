"""Política de errores de la Open API (03 §2.1, tabla «Política de errores»). Configurable.

El cuerpo trae `code` y el HTTP casi siempre es 200. `Politica.decidir(http, codigo, sin_json)` devuelve la `Regla`:

| Código | Decisión | Reintentos | Notas |
|---|---|---|---|
| 0 | — | — | éxito |
| 105002, 105001 | refrescar_token | 1 refresh + 1 reintento | 105002 tras un refresh exitoso → token_rechazado; 105001 → reautorizar |
| 105005, 16501011 | omitir_paso | 0 | falta un permiso |
| 101000 | reautorizar | 0 | token de otra identidad |
| 16015006, 16015007, 16504002, 18001405 | abortar | 0 | auth_estado = cuenta_sin_region |
| 36009002 | reintentar | 5 | base 2 s, respeta Retry-After acotado a [1, 120] s |
| 36009003 | reintentar | 3 | base 1 s |
| 36009004 | reintentar | 3 | no documentado; si persiste, omitir_paso transitorio |
| 98001004 | reintentar_lento | 2 | base 15 s, tope 60 s; si persiste, omitir_paso transitorio |
| CODIGOS_VALIDACION | omitir_paso | 0 | estado no aceptado: el sincronizador lo anota en sync_cursores |
| HTTP 429 / 5xx / no JSON | reintentar | 3 | base 1 s |
| red | reintentar | 3 (≈ 1, 3, 9 s) | si persiste: abortar (sin_internet) |
| otro | omitir_paso | 0 | se registra y no se insiste |

Backoff *full jitter*: espera = uniform(0, min(tope, base · 2^(intento−1))), tope 60 s.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Iterable, Mapping

DECISIONES = frozenset({'refrescar_token', 'omitir_paso', 'reautorizar', 'abortar', 'reintentar', 'reintentar_lento'})


@dataclass(frozen=True)
class Regla:
    decision: str
    reintentos: int = 0
    base_s: float = 1.0
    tope_s: float = 60.0
    efecto: str | None = None          # 'cuenta_sin_region' · 'validacion'
    respeta_retry_after: bool = False

    def __post_init__(self) -> None:
        if self.decision not in DECISIONES:
            raise ValueError(f'decisión desconocida: {self.decision!r}')
        if self.reintentos < 0 or self.base_s < 0 or self.tope_s < 0:
            raise ValueError('reintentos, base y tope deben ser ≥ 0')


SIN_REGION = (16015006, 16015007, 16504002, 18001405)

POLITICA: dict[int, Regla] = {
    105002: Regla('refrescar_token', 1),
    105001: Regla('refrescar_token', 1),
    105005: Regla('omitir_paso', 0),
    16501011: Regla('omitir_paso', 0),
    101000: Regla('reautorizar', 0),
    **{c: Regla('abortar', 0, efecto='cuenta_sin_region') for c in SIN_REGION},
    36009002: Regla('reintentar', 5, base_s=2.0, respeta_retry_after=True),
    36009003: Regla('reintentar', 3, base_s=1.0),
    36009004: Regla('reintentar', 3, base_s=1.0),          # NO documentado: transitorio conservador
    98001004: Regla('reintentar_lento', 2, base_s=15.0, tope_s=60.0),   # NO documentado
}
"""Tabla por omisión (03 §2.1). Cópiala y pásala a `Politica(tabla=…)` para cambiarla sin tocar este módulo."""

CODIGOS_VALIDACION: frozenset[int] = frozenset()
"""Códigos de «parámetro no válido» (un application_status que la API no acepta). La documentación no los da: vacío
por omisión, configurable con `Politica(codigos_validacion=…)`."""

REGLA_TRANSITORIO = Regla('reintentar', 3, base_s=1.0)                # HTTP 429 / 5xx / cuerpo no JSON
REGLA_RED = Regla('reintentar', 3, base_s=1.0, tope_s=9.0)            # DNS, conexión, timeout (≈ 1, 3, 9 s)
REGLA_DESCONOCIDO = Regla('omitir_paso', 0)
REGLA_VALIDACION = Regla('omitir_paso', 0, efecto='validacion')
RETRY_AFTER_MIN_S = 1.0
RETRY_AFTER_MAX_S = 120.0


@dataclass
class Politica:
    """Política configurable: `tabla` (código → Regla) y `codigos_validacion`."""
    tabla: Mapping[int, Regla] = field(default_factory=lambda: dict(POLITICA))
    codigos_validacion: Iterable[int] = field(default_factory=lambda: set(CODIGOS_VALIDACION))
    regla_transitorio: Regla = REGLA_TRANSITORIO
    regla_red: Regla = REGLA_RED
    regla_desconocido: Regla = REGLA_DESCONOCIDO

    def __post_init__(self) -> None:
        self.tabla = dict(self.tabla)
        self.codigos_validacion = frozenset(self.codigos_validacion)

    def decidir(self, http: int | None, codigo: object, sin_json: bool = False) -> Regla:
        """Regla para una respuesta que NO fue éxito (code ≠ 0 o cuerpo no JSON)."""
        if sin_json or (http is not None and (http >= 500 or http == 429)):
            return self.regla_transitorio
        if isinstance(codigo, bool) or not isinstance(codigo, int):
            return self.regla_desconocido
        if codigo in self.codigos_validacion:
            return REGLA_VALIDACION
        return self.tabla.get(codigo, self.regla_desconocido)


def espera_full_jitter(azar: random.Random, intento: int, base_s: float, tope_s: float = 60.0) -> float:
    """uniform(0, min(tope, base · 2^(intento−1))) — *full jitter* (03 §2.1)."""
    techo = min(tope_s, base_s * (2 ** max(0, intento - 1)))
    return azar.uniform(0.0, techo) if techo > 0 else 0.0


def acotar_retry_after(valor: str | None) -> float | None:
    """Segundos de `Retry-After` (solo la forma numérica) acotados a [1, 120]; None si no viene o no es número."""
    if valor is None:
        return None
    try:
        s = float(str(valor).strip())
    except ValueError:
        return None
    if s != s:      # NaN
        return None
    return max(RETRY_AFTER_MIN_S, min(RETRY_AFTER_MAX_S, s))
