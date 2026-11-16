"""Errores de la Display API (rev. 5).

`ErrorDisplay(codigo)` lleva un código corto propio y el mensaje en español de México que puede ver la persona. NUNCA
guarda el texto que manda TikTok (viene en inglés y podría repetir datos de la petición) ni un secreto; de TikTok solo
se conserva su `log_id` (identificador de la petición, útil para soporte) y el estado HTTP.

Códigos: sin_credenciales · sin_conexion · reautorizar · credenciales_rechazadas · codigo_vencido · solicitud_rechazada
· token_invalido (interno: dispara un refresh y un reintento) · permiso_faltante · limite · sin_internet ·
tiktok_no_disponible · respuesta_invalida · error_interno.
"""
from __future__ import annotations

MENSAJES: dict[str, str] = {
    'sin_credenciales': 'Escribe el Client key y el Client secret de tu app de TikTok for Developers.',
    'sin_conexion': 'Todavía no conectas tu cuenta de TikTok para traer las vistas de tus videos.',
    'reautorizar': 'La conexión para ver las vistas de tus videos venció. Vuelve a conectar desde Ajustes.',
    'credenciales_rechazadas': ('TikTok no reconoció el Client key o el Client secret. Revísalos en TikTok for '
                                'Developers y vuelve a escribirlos.'),
    'codigo_vencido': 'El enlace de autorización ya caducó o ya se usó. Vuelve a conectar desde Corte.',
    'solicitud_rechazada': 'TikTok rechazó la solicitud de conexión. Vuelve a conectar desde Corte.',
    'token_invalido': 'La conexión con TikTok ya no es válida. Vuelve a conectar desde Ajustes.',
    'permiso_faltante': 'Falta un permiso de TikTok. Vuelve a conectar y deja activados todos los permisos.',
    'limite': 'TikTok pidió esperar un momento. Lo intentaremos en la siguiente sincronización.',
    'sin_internet': 'No pudimos hablar con TikTok. Revisa tu internet e inténtalo de nuevo.',
    'tiktok_no_disponible': 'TikTok no respondió. Inténtalo de nuevo en unos minutos.',
    'respuesta_invalida': 'TikTok respondió de forma incompleta. Inténtalo de nuevo.',
    'error_interno': 'Algo salió mal en Corte. Inténtalo de nuevo.',
}
TRANSITORIOS = frozenset({'limite', 'sin_internet', 'tiktok_no_disponible'})


class ErrorDisplay(Exception):
    """Falla de la Display API. `reautorizar=True`: hace falta volver a conectar (la bóveda ya quedó marcada)."""

    def __init__(self, codigo: str, mensaje: str | None = None, http: int | None = None, log_id: str | None = None,
                 reautorizar: bool = False) -> None:
        self.codigo = codigo if codigo in MENSAJES else 'error_interno'
        self.mensaje = mensaje or MENSAJES[self.codigo]
        self.http = http if isinstance(http, int) and not isinstance(http, bool) else None
        self.log_id = log_id if isinstance(log_id, str) and len(log_id) <= 80 and log_id.isprintable() else None
        self.reautorizar = bool(reautorizar or self.codigo == 'reautorizar')
        self.transitorio = self.codigo in TRANSITORIOS
        super().__init__(self.codigo)

    def como_dict(self, at: int) -> dict[str, object]:
        """{codigo, mensaje, at}: lo único que se guarda y se muestra (EstadoDisplay.ultimo_error)."""
        return {'codigo': self.codigo, 'mensaje': self.mensaje, 'at': int(at)}


__all__ = ['ErrorDisplay', 'MENSAJES', 'TRANSITORIOS']
