"""Bóveda de la Display API (rev. 5): `<secretos>\\tiktok_display.dpapi`.

Es `boveda.BovedaDpapi` con OTRO archivo y OTRA entropía (`CreatorHub/tiktok_display/v1`): mismas garantías que las
credenciales de TikTok Shop (sobre JSON con el blob de CryptProtectData del usuario actual; escritura `.nuevo` + flush +
fsync + `os.replace` con reintentos; al arrancar gana el `.nuevo` de mayor generación; un archivo ilegible se aparta y
nunca se sobrescribe; `generacion` sube en cada escritura y `epoca_credenciales` en cada cambio de credenciales).
Vive aparte de la de TikTok Shop a propósito: una escritura aquí NO mueve la generación que el refresh de TikTok Shop
compara con `guardar_si` (si la moviera, ese refresh descartaría sus tokens rotados).

Contenido: client_key, client_secret, access_token, refresh_token, access_expira_at, refresh_expira_at, open_id,
scopes, conectada_at, reautorizar, ultimo_error {codigo, mensaje, at}, origen ('oauth' | 'demo'), generacion,
epoca_credenciales, actualizado_at. Secretos que el registro y los errores tapan: client_secret, access_token y
refresh_token. El client_key tampoco sale del hub (solo viaja, inevitablemente, en el enlace de autorización).

Modos: real → DPAPI · demo → memoria con valores FALSOS (los que entiende el transporte de `tiktok_dev/demo.py`) ·
autoprueba → DPAPI en la carpeta temporal, vacía (no escribe nada).
"""
from __future__ import annotations

import os
from typing import Any

from ..boveda import BovedaDpapi
from ..interfaces import ModoHub, Rutas

NOMBRE_ARCHIVO = 'tiktok_display.dpapi'
ENTROPIA_DISPLAY = b'CreatorHub/tiktok_display/v1'
CAMPOS_SECRETOS_DISPLAY = ('client_secret', 'access_token', 'refresh_token')
CAMPOS_TOKENS = ('access_token', 'refresh_token', 'access_expira_at', 'refresh_expira_at', 'open_id', 'scopes',
                 'conectada_at', 'reautorizar')

# Valores FALSOS del modo demo (nunca se escriben a disco ni son de nadie).
CLIENT_KEY_DEMO = 'democlientkey0000'
CLIENT_SECRET_DEMO = 'secreto-display-de-prueba'
ACCESO_DEMO = 'act.demo-display-acceso'
RENOVACION_DEMO = 'rft.demo-display-renovacion'
OPEN_ID_DEMO = 'OPEN_ID_DISPLAY_DEMO'
SCOPES_DEMO = ('user.info.basic', 'user.info.profile', 'user.info.stats', 'video.list')


class BovedaDisplay(BovedaDpapi):
    """Implementa `interfaces.Boveda` (con `tiene_app_secret` = hay client_secret) y agrega `configurada`/`conectada`."""

    ENTROPIA = ENTROPIA_DISPLAY
    CAMPOS_SECRETOS = CAMPOS_SECRETOS_DISPLAY

    def configurada(self) -> bool:
        with self.candado:
            return bool(self._datos.get('client_key') and self._datos.get('client_secret'))

    def conectada(self) -> bool:
        with self.candado:
            return bool(self._datos.get('access_token') and self._datos.get('refresh_token'))

    def tiene_app_secret(self) -> bool:
        with self.candado:
            return bool(self._datos.get('client_secret'))

    def resumen(self) -> dict[str, bool]:
        """Solo presencia (para registros): nunca valores."""
        return {'credenciales': self.configurada(), 'tokens': self.conectada()}

    def anclar_demo(self, ahora: int) -> None:
        """Modo demo: vencimientos falsos relativos al reloj del hub (que puede arrancar en `--ahora`)."""
        if not self.origen_demo:
            return
        with self.candado:
            if self._anclado:
                return
            self._anclado = True
            self._datos['access_expira_at'] = int(ahora) + 86400
            self._datos['refresh_expira_at'] = int(ahora) + 180 * 86400
            self._datos['conectada_at'] = int(ahora) - 3600


def datos_demo(ahora: int) -> dict[str, Any]:
    return {'client_key': CLIENT_KEY_DEMO, 'client_secret': CLIENT_SECRET_DEMO, 'access_token': ACCESO_DEMO,
            'refresh_token': RENOVACION_DEMO, 'access_expira_at': ahora + 86400, 'refresh_expira_at': ahora + 180 * 86400,
            'open_id': OPEN_ID_DEMO, 'scopes': list(SCOPES_DEMO), 'conectada_at': ahora - 3600, 'reautorizar': False,
            'ultimo_error': None, 'origen': 'demo', 'generacion': 1, 'epoca_credenciales': 1}


def crear_boveda_display(rutas: Rutas, modo: ModoHub) -> BovedaDisplay:
    """real → DPAPI en <secretos>\\tiktok_display.dpapi · demo → memoria con valores falsos · autoprueba → vacía."""
    if modo == 'demo':
        import time
        return BovedaDisplay(None, datos=datos_demo(int(time.time())), origen_demo=True)
    ruta = os.path.join(rutas.secretos, NOMBRE_ARCHIVO)
    if modo == 'real':
        return BovedaDisplay(ruta)
    if modo == 'autoprueba':
        return BovedaDisplay(ruta, vacia=True)
    raise ValueError(f'modo desconocido: {modo!r}')


__all__ = ['BovedaDisplay', 'crear_boveda_display', 'datos_demo', 'NOMBRE_ARCHIVO', 'ENTROPIA_DISPLAY',
           'CAMPOS_SECRETOS_DISPLAY', 'CAMPOS_TOKENS']
