"""Excepciones del hub (BUILD_SPEC §6.2, «Excepciones»).

- ErrorDominio: error de negocio que la API convierte en ErrorRespuesta (contrato.ts). El mensaje pasa por limpiar();
  `vigente` solo viaja en `error.vigente` cuando codigo == 'conflicto' (409, C26).
- ErrorApi / ErrorAuthTransitorio: respuesta de TikTok clasificada por la política de errores (semántica de
  spec/verificacion/motor_ref.py). El mensaje se limpia y se recorta a 300 caracteres al construirse.
- ErrorRed / ErrorTimeoutLectura: fallas del transporte (semántica de spec/verificacion/fixtures_api.py). El timeout de
  lectura significa que la petición SALIÓ (TikTok pudo procesarla) pero la respuesta no llegó.
"""
from __future__ import annotations

from typing import Any

from .comun import limpiar

P_REFRESH = '/api/v2/token/refresh'


class ErrorDominio(Exception):
    """Error de negocio con código de contrato.ts (CodigoError) y estado HTTP."""

    def __init__(self, codigo: str, mensaje: str, http: int = 400, detalle: dict[str, Any] | None = None,
                 reintentar_en_s: int | None = None, vigente: dict[str, Any] | None = None) -> None:
        mensaje = limpiar(mensaje or '')
        super().__init__(f'{codigo}: {mensaje}')
        self.codigo = codigo
        self.mensaje = mensaje
        self.http = http
        self.detalle = detalle
        self.reintentar_en_s = reintentar_en_s
        self.vigente = vigente

    def a_respuesta(self, secretos_vivos: tuple[str, ...] = ()) -> dict[str, Any]:
        """Cuerpo ErrorRespuesta: {'error': {codigo, mensaje, detalle?, reintentar_en_s?, vigente?}}."""
        error: dict[str, Any] = {'codigo': self.codigo, 'mensaje': limpiar(self.mensaje, secretos_vivos)}
        if self.detalle:
            error['detalle'] = {k: (limpiar(v, secretos_vivos) if isinstance(v, str) else v)
                                for k, v in self.detalle.items()}
        if self.reintentar_en_s is not None:
            error['reintentar_en_s'] = self.reintentar_en_s
        if self.codigo == 'conflicto' and self.vigente is not None:
            error['vigente'] = self.vigente
        return {'error': error}


class ErrorApi(Exception):
    """Error de TikTok o del cliente. decision ∈ {'reintentar', 'refrescar_token', 'omitir_paso', 'abortar',
    'reautorizar'}; transitorio=True si conviene reintentar más tarde (red, 5xx, códigos 3600900x agotados)."""

    def __init__(self, codigo: Any, mensaje: str, decision: str, http: int | None = None, request_id: str | None = None,
                 path: str | None = None, transitorio: bool = False) -> None:
        mensaje = limpiar(mensaje or '')[:300]          # nunca guardar ni responder texto con secretos
        super().__init__(f'{codigo}: {mensaje}')
        self.codigo, self.mensaje, self.decision = codigo, mensaje, decision
        self.http, self.request_id, self.path, self.transitorio = http, request_id, path, transitorio


class ErrorAuthTransitorio(ErrorApi):
    """Fallo de red / 429 / 5xx / cuerpo no JSON / timeout al renovar: NO cambia auth_estado."""

    def __init__(self, mensaje: str) -> None:
        super().__init__('renovacion_pendiente', mensaje, 'reintentar', path=P_REFRESH, transitorio=True)


class ErrorRed(Exception):
    """Sin conexión (DNS, conexión rechazada, timeout de conexión). El texto se limpia por si trae una URL."""

    def __init__(self, *args: Any) -> None:
        super().__init__(*(limpiar(a) if isinstance(a, str) else a for a in args))


class ErrorTimeoutLectura(ErrorRed):
    """La petición salió (y TikTok pudo procesarla) pero la respuesta no llegó a tiempo."""
