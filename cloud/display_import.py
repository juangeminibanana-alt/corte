"""Import an existing Display authorization after verifying its creator.

Provider verification (including the existing single refresh/retry) uses an
in-memory vault. Neither submitted nor rotated tokens reach disk before the
creator and destination revisions have been checked.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from creatorhub.errores import ErrorDominio
from creatorhub.tiktok_dev import datos as D
from creatorhub.tiktok_dev.boveda import BovedaDisplay
from creatorhub.tiktok_dev.cliente import ClienteDisplay
from creatorhub.tiktok_dev.errores import ErrorDisplay

REQUIRED = frozenset({'client_key', 'client_secret', 'access_token', 'refresh_token',
                      'access_expira_at', 'refresh_expira_at', 'open_id', 'scopes'})
OPTIONAL = frozenset({'conectada_at', 'origen'})
MIN_SCOPES = frozenset({'user.info.basic', 'user.info.profile', 'video.list'})


def _error(code: str, message: str, status: int = 422):
    return ErrorDominio(code, message, http=status)


def _visible(value: Any, minimum: int, maximum: int) -> bool:
    return isinstance(value, str) and minimum <= len(value) <= maximum and all(33 <= ord(c) <= 126 for c in value)


def username(value: Any) -> str:
    """Same normalization the video catalog uses to keep Display content on the Shop creator's account."""
    return D.usuario_normalizado(value)


def validate(body: Any, now: int) -> dict[str, Any]:
    if not isinstance(body, dict) or not REQUIRED <= set(body) or set(body) - REQUIRED - OPTIONAL:
        raise _error('archivo_invalido', 'Elige el archivo de conexión de las métricas de videos de tu aplicación anterior.')
    if (not isinstance(body['client_key'], str) or not re.fullmatch(r'[A-Za-z0-9]{8,64}', body['client_key'])
            or not isinstance(body['client_secret'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', body['client_secret'])
            or not all(_visible(body[k], 10, 8192) for k in ('access_token', 'refresh_token'))
            or not _visible(body['open_id'], 1, 256)):
        raise _error('archivo_invalido', 'El archivo no contiene una conexión válida de TikTok Display.')
    for key in ('access_expira_at', 'refresh_expira_at'):
        if type(body[key]) is not int or not 1 <= body[key] <= 9_007_199_254_740_991:
            raise _error('archivo_invalido', 'Las fechas de la conexión anterior no son válidas.')
    if body['refresh_expira_at'] <= now:
        raise _error('reautorizar', 'La conexión anterior de videos venció. Vuelve a autorizarla desde Corte.')
    scopes = body['scopes']
    if (not isinstance(scopes, list) or len(scopes) > 32
            or any(not isinstance(s, str) or not re.fullmatch(r'[a-z0-9._]{1,128}', s) for s in scopes)
            or not MIN_SCOPES <= set(scopes)):
        raise _error('sin_permiso_tiktok', 'La conexión anterior necesita permisos de perfil y videos para comprobar tus portadas.')
    if body.get('origen', 'oauth') not in ('oauth', 'importado'):
        raise _error('archivo_invalido', 'El archivo debe contener una conexión real de TikTok.')
    if 'conectada_at' in body and (type(body['conectada_at']) is not int or not 1 <= body['conectada_at'] <= now + 300):
        raise _error('archivo_invalido', 'La fecha de conexión anterior no es válida.')
    data = {key: body[key] for key in REQUIRED}
    data.update(scopes=list(dict.fromkeys(scopes)), origen='importado', reautorizar=False,
                ultimo_error=None, conectada_at=body.get('conectada_at', now))
    return data


def _shop_identity(hub: Any) -> tuple[tuple[Any, ...], str]:
    shop = hub.boveda.leer()
    account = hub.auth.cuenta() or {}
    name = username(account.get('username'))
    if not name or hub.auth.conexion().get('estado') != 'conectada' or not shop.get('open_id'):
        raise _error('cuenta_requerida', 'Conecta primero tu cuenta de TikTok Shop para verificar las métricas de esa misma cuenta.', 409)
    return (shop.get('app_key'), shop.get('open_id'), shop.get('epoca_credenciales', 0)), name


def _destination(data: Mapping[str, Any], incoming: Mapping[str, Any], profile: Mapping[str, Any] | None,
                 expected_name: str) -> None:
    if data.get('access_token') or data.get('refresh_token'):
        raise _error('conexion_existente', 'Corte ya tiene una conexión de videos. Desconéctala antes de importar otra.', 409)
    if (data.get('open_id') and data.get('client_key') == incoming['client_key']
            and data['open_id'] != incoming['open_id']):
        raise _error('cuenta_distinta', 'La conexión de videos guardada pertenece a otra cuenta. No se cambió.', 409)
    if profile:
        previous_name = username(profile.get('username'))
        if previous_name and previous_name != expected_name:
            raise _error('cuenta_distinta', 'Las métricas guardadas pertenecen a otra cuenta. No se cambiaron.', 409)


def import_display(hub: Any, body: Any) -> dict[str, Any]:
    now = int(hub.reloj.ahora())
    data = validate(body, now)
    service = hub.display
    with hub._candado_mutacion:
        identity, expected_name = _shop_identity(hub)
        before = service.boveda.leer()
        with hub.almacen.lector() as db:
            history = D.leer_perfil(db)
        _destination(before, data, history, expected_name)

    temporary = BovedaDisplay(None, datos=data)
    client = ClienteDisplay(temporary, service.cliente.transporte, hub.reloj)
    try:
        profile = D.normalizar_usuario(client.usuario())
    except ErrorDisplay as exc:
        # These messages are our own sanitized messages, never TikTok's payload.
        message = ('TikTok no aceptó la conexión anterior de videos. El archivo original se conserva.'
                   if exc.codigo == 'credenciales_rechazadas' else exc.mensaje)
        raise _error(exc.codigo, message, 503 if exc.transitorio else 422) from None
    checked = temporary.leer()
    if (username(profile.get('username')) != expected_name or not profile.get('open_id')
            or profile['open_id'] != checked.get('open_id')):
        raise _error('cuenta_distinta', 'La conexión de videos no corresponde a la cuenta de TikTok Shop actual. No se guardó.', 409)
    if not MIN_SCOPES <= set(checked.get('scopes') or []):
        raise _error('sin_permiso_tiktok', 'La conexión renovada no tiene los permisos necesarios de perfil y videos.')

    with hub._candado_mutacion:
        current_identity, current_name = _shop_identity(hub)
        if (current_identity, current_name) != (identity, expected_name):
            raise _error('credenciales_cambiaron', 'La cuenta de TikTok Shop cambió durante la verificación. No se importó la conexión.', 409)
        with service.boveda.candado:
            # CAS uses every vault write, including refresh/secret rotation;
            # no concurrent authorization is silently overwritten.
            actual = service.boveda.leer()
            if actual.get('generacion', 0) != before.get('generacion', 0):
                raise _error('credenciales_cambiaron', 'La conexión de videos cambió durante la verificación. No se importó.', 409)
            with hub.almacen.lector() as db:
                history = D.leer_perfil(db)
            _destination(actual, checked, history, expected_name)
            fields = {key: checked[key] for key in REQUIRED}
            fields.update(origen='importado', reautorizar=False, ultimo_error=None,
                          conectada_at=data['conectada_at'])
            service.boveda.mutar(lambda target: target.update(fields), cambia_credenciales=True)
            revision = (fields['client_key'], fields['open_id'], actual.get('epoca_credenciales', 0) + 1)
            with hub.almacen.escritor() as db:
                if D.guardar_perfil(db, profile, now):
                    hub.almacen.marcar_data_version(db)
        hub.almacen.confirmar_data_version()
        with service._candado:
            service._intentos.clear()
            service._terminados.clear()
        service.publicar()
    return {'ok': True, 'verificacion': 'ok', '_revision': revision,
            '_shop_revision': (identity, expected_name)}
