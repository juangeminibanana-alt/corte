"""Estado de la conexión con TikTok (sin secretos), compartido por `tiktok.cliente` y `auth` (03 §2.1, §2.2, §7.1).

- La fila `auth_estado` (id = 1) es el espejo NO secreto de la bóveda más las banderas que deben sobrevivir a un
  reinicio: `estado` ('reautorizar' · 'cuenta_sin_region'), `refresh_aviso`, rechazos seguidos y el último error
  (siempre pasado por `limpiar()`).
- `construir_conexion()` arma `Conexion` (contrato.ts) a partir de la bóveda, la fila y el reloj corregido.
- `construir_cuenta()` arma `Cuenta` desde la tabla `cuenta` con la regla de imágenes de C45 para el avatar.

`refresh_aviso` ∈ {None, 'renovacion_pendiente', 'token_rechazado', 'panel_anterior'}. 'panel_anterior' = el refresh
terminó en reautorizar o token_rechazado menos de 72 h después de importar el archivo anterior (C42).
"""
from __future__ import annotations

import json
import math
import sqlite3
from typing import Any, Mapping

from ..boveda import APP_KEY_PUBLICA
from ..comun import limpiar
from ..interfaces import Json

ESTADOS = ('sin_credenciales', 'sin_autorizar', 'conectada', 'reautorizar', 'cuenta_sin_region')
ORIGENES = ('importado', 'oauth', 'manual', 'demo')
AVISOS_REFRESH = ('renovacion_pendiente', 'token_rechazado', 'panel_anterior')

SCOPES_MINIMOS: tuple[str, ...] = ('creator.affiliate.info', 'creator.affiliate_collaboration.read')
SCOPES_USADOS: tuple[str, ...] = SCOPES_MINIMOS + ('creator.showcase.read',)
NOMBRE_PERMISO: Mapping[str, str] = {           # 01 §4.14 A (la clave original solo va en «Datos técnicos»)
    'creator.affiliate.info': 'Ver tu perfil de creador',
    'creator.affiliate_collaboration.read': 'Ver tus colaboraciones de afiliado',
    'creator.showcase.read': 'Ver tu vitrina',
    'creator.showcase.write': 'Administrar tu vitrina',
    'creator.affiliate.link.write': 'Crear enlaces de afiliado',
}

VENTANA_C42_S = 72 * 3600
AVISO_VENCE_DIAS = 7
DESFASE_AVISO_S = 120

TEXTO_C42 = ('Tu conexión se venció, quizá porque el panel anterior también la usa. Vuelve a conectar desde Corte '
             'y deja de usar el panel anterior.')
AVISO_VENCIDA = 'Tu conexión con TikTok venció. Vuelve a conectar.'
AVISO_SIN_REGION = ('Tu cuenta de TikTok no tiene región de venta o permiso para vender. Revísalo en TikTok Shop y '
                    'vuelve a conectar.')
AVISO_RECHAZADA = 'TikTok no aceptó la conexión renovada. Lo intentaremos de nuevo en unos minutos.'
AVISO_RENOVACION = 'No pudimos renovar la conexión, lo intentaremos de nuevo.'
AVISO_RELOJ = 'La hora de tu PC no coincide con la de TikTok. Revisa la fecha y la hora de Windows.'

COLUMNAS: frozenset[str] = frozenset({
    'app_key', 'app_secret_presente', 'tokens_presentes', 'open_id', 'user_type', 'seller_name', 'granted_scopes_json',
    'access_expira_at', 'refresh_expira_at', 'estado', 'origen', 'ultimo_refresh_at', 'refresh_rechazos_seguidos',
    'refresh_aviso', 'ultimo_error_codigo', 'ultimo_error_mensaje'})
_SELECT = ('SELECT app_key, app_secret_presente, tokens_presentes, open_id, user_type, seller_name, granted_scopes_json, '
           'access_expira_at, refresh_expira_at, estado, origen, ultimo_refresh_at, refresh_rechazos_seguidos, '
           'refresh_aviso, ultimo_error_codigo, ultimo_error_mensaje, actualizado_at FROM auth_estado WHERE id = 1')
_NOMBRES = ('app_key', 'app_secret_presente', 'tokens_presentes', 'open_id', 'user_type', 'seller_name',
            'granted_scopes_json', 'access_expira_at', 'refresh_expira_at', 'estado', 'origen', 'ultimo_refresh_at',
            'refresh_rechazos_seguidos', 'refresh_aviso', 'ultimo_error_codigo', 'ultimo_error_mensaje', 'actualizado_at')


# ------------------------------------------------------------------ fila auth_estado y meta
def leer_fila(conn: sqlite3.Connection) -> dict[str, Any] | None:
    r = conn.execute(_SELECT).fetchone()
    return None if r is None else {n: r[i] for i, n in enumerate(_NOMBRES)}


def actualizar_fila(conn: sqlite3.Connection, ahora: int, app_key_omision: str | None = None, /,
                    **campos: Any) -> None:
    """Crea la fila si falta y actualiza `campos` (nombres de la lista blanca COLUMNAS; nunca de la entrada)."""
    malas = set(campos) - COLUMNAS
    if malas:
        raise ValueError(f'columnas no permitidas en auth_estado: {sorted(malas)}')
    if 'estado' in campos and campos['estado'] not in ESTADOS:
        raise ValueError('estado de conexión desconocido')
    if 'ultimo_error_mensaje' in campos and campos['ultimo_error_mensaje'] is not None:
        campos['ultimo_error_mensaje'] = limpiar(str(campos['ultimo_error_mensaje']))[:300]
    conn.execute('INSERT INTO auth_estado(id, app_key, actualizado_at) VALUES (1, ?, ?) ON CONFLICT(id) DO NOTHING',
                 (campos.get('app_key') or app_key_omision or APP_KEY_PUBLICA, int(ahora)))
    if campos:
        nombres = sorted(campos)
        conn.execute('UPDATE auth_estado SET ' + ', '.join(f'{n} = ?' for n in nombres) + ', actualizado_at = ? '
                     'WHERE id = 1', (*(campos[n] for n in nombres), int(ahora)))


def leer_meta(conn: sqlite3.Connection, clave: str) -> str | None:
    r = conn.execute('SELECT valor FROM meta WHERE clave = ?', (clave,)).fetchone()
    return None if r is None else r[0]


def escribir_meta(conn: sqlite3.Connection, clave: str, valor: str) -> None:
    conn.execute('INSERT INTO meta(clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor',
                 (clave, str(valor)))


def meta_entero(conn: sqlite3.Connection, clave: str) -> int | None:
    v = leer_meta(conn, clave)
    try:
        return int(v) if v is not None else None
    except ValueError:
        return None


# ------------------------------------------------------------------ espejo de la bóveda
def _entero(v: Any) -> int | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def tiene_tokens(datos: Mapping[str, Any]) -> bool:
    return bool(datos.get('access_token') and datos.get('refresh_token'))


def scopes_de(datos: Mapping[str, Any]) -> list[str]:
    s = datos.get('granted_scopes') or []
    return [str(x) for x in s] if isinstance(s, (list, tuple)) else []


def espejo(datos: Mapping[str, Any]) -> dict[str, Any]:
    """Columnas de auth_estado que se derivan de la bóveda (presencia, nunca valores secretos)."""
    origen = datos.get('origen')
    return {
        'app_key': datos.get('app_key') or APP_KEY_PUBLICA,
        'app_secret_presente': int(bool(datos.get('app_secret'))),
        'tokens_presentes': int(tiene_tokens(datos)),
        'open_id': datos.get('open_id') or None,
        'user_type': _entero(datos.get('user_type')),
        'seller_name': datos.get('seller_name') or None,
        'granted_scopes_json': json.dumps(scopes_de(datos), ensure_ascii=False, separators=(',', ':')),
        'access_expira_at': _entero(datos.get('access_expira_at')),
        'refresh_expira_at': _entero(datos.get('refresh_expira_at')),
        'origen': origen if origen in ORIGENES else None,
    }


def estado_base(datos: Mapping[str, Any]) -> str:
    if not datos.get('app_secret'):
        return 'sin_credenciales'
    if not tiene_tokens(datos):
        return 'sin_autorizar'
    return 'conectada'


def estado_conexion(datos: Mapping[str, Any], fila: Mapping[str, Any] | None, ahora: int) -> str:
    base = estado_base(datos)
    if base != 'conectada':
        return base
    if fila is not None and fila.get('estado') in ('reautorizar', 'cuenta_sin_region'):
        return str(fila['estado'])
    r = _entero(datos.get('refresh_expira_at'))
    if r is not None and r <= ahora:
        return 'reautorizar'
    return 'conectada'


def aviso_vence(dias: int) -> str:
    if dias <= 1:
        return 'Tu conexión con TikTok vence en 1 día. Vuelve a conectar.'
    return f'Tu conexión con TikTok vence en {dias} días. Vuelve a conectar.'


def construir_conexion(datos: Mapping[str, Any], fila: Mapping[str, Any] | None, ahora: int,
                       desfase_s: float = 0.0) -> Json:
    """`Conexion` de contrato.ts. `ahora` = reloj corregido por el desfase con TikTok."""
    estado = estado_conexion(datos, fila, ahora)
    con_tokens = tiene_tokens(datos)
    scopes = scopes_de(datos) if con_tokens else []
    faltantes = [s for s in SCOPES_USADOS if s not in scopes] if con_tokens else []
    refresh_aviso = (fila or {}).get('refresh_aviso')
    r_exp = _entero(datos.get('refresh_expira_at')) if con_tokens else None
    aviso: str | None = None
    if refresh_aviso == 'panel_anterior' and estado in ('reautorizar', 'conectada'):
        aviso = TEXTO_C42
    elif estado == 'reautorizar':
        aviso = AVISO_VENCIDA
    elif estado == 'cuenta_sin_region':
        aviso = AVISO_SIN_REGION
    elif estado == 'conectada' and refresh_aviso == 'token_rechazado':
        aviso = AVISO_RECHAZADA
    elif estado == 'conectada' and refresh_aviso == 'renovacion_pendiente':
        aviso = AVISO_RENOVACION
    elif estado == 'conectada' and r_exp is not None and r_exp - ahora < AVISO_VENCE_DIAS * 86400:
        aviso = aviso_vence(max(1, math.ceil((r_exp - ahora) / 86400)))
    elif con_tokens and abs(desfase_s) > DESFASE_AVISO_S:
        aviso = AVISO_RELOJ
    origen = datos.get('origen') or (fila or {}).get('origen')
    return {
        'estado': estado,
        'access_expira_at': _entero(datos.get('access_expira_at')) if con_tokens else None,
        'refresh_expira_at': r_exp,
        'scopes': scopes,
        'scopes_faltantes': faltantes,
        'aviso': aviso,
        'origen': origen if origen in ORIGENES else None,
    }


# ------------------------------------------------------------------ cuenta (perfil) con la regla de imágenes C45
SQL_UPSERT_CUENTA = (
    'INSERT INTO cuenta(id, creator_open_id, username, avatar_url, selection_region, register_region, user_type, '
    'seller_type, permisos_json, actualizado_at) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET '
    'creator_open_id = excluded.creator_open_id, username = excluded.username, avatar_url = excluded.avatar_url, '
    'selection_region = excluded.selection_region, register_region = excluded.register_region, '
    'user_type = excluded.user_type, seller_type = excluded.seller_type, permisos_json = excluded.permisos_json, '
    'actualizado_at = excluded.actualizado_at')


def fila_cuenta_de_perfil(perfil: Mapping[str, Any]) -> tuple[Any, ...]:
    """Valores de `cuenta` desde `data` de GET /affiliate_creator/202508/profiles (mismas columnas que motor_ref)."""
    avatar = perfil.get('avatar') or {}
    permisos = perfil.get('permissions') or []
    return (str(perfil.get('creator_user_open_id') or ''), str(perfil.get('username') or ''),
            avatar.get('url') if isinstance(avatar, dict) else None,
            perfil.get('selection_region'), perfil.get('register_region'),
            None if perfil.get('user_type') is None else str(perfil.get('user_type')),
            None if perfil.get('seller_type') is None else str(perfil.get('seller_type')),
            json.dumps([str(p) for p in permisos] if isinstance(permisos, list) else [], ensure_ascii=False,
                       separators=(',', ':')))


def guardar_cuenta(conn: sqlite3.Connection, perfil: Mapping[str, Any], ahora: int) -> bool:
    """Escribe la fila `cuenta` solo si cambió algo (sin contar actualizado_at). True si escribió."""
    valores = fila_cuenta_de_perfil(perfil)
    previo = conn.execute('SELECT creator_open_id, username, avatar_url, selection_region, register_region, user_type, '
                          'seller_type, permisos_json FROM cuenta WHERE id = 1').fetchone()
    if previo is not None and tuple(previo) == valores:
        return False
    conn.execute(SQL_UPSERT_CUENTA, (*valores, int(ahora)))
    return True


def url_avatar(conn: sqlite3.Connection) -> str | None:
    """C45: estado 'ok' → '/img/a/cuenta?v=<versión>'; con url_origen y otro estado → '?v=0'; si no, None."""
    r = conn.execute("SELECT estado, version, url_origen FROM imagenes WHERE img_key = 'a:cuenta'").fetchone()
    if r is None:
        return None
    if r[0] == 'ok' and r[1]:
        return f'/img/a/cuenta?v={r[1]}'
    if r[2]:
        return '/img/a/cuenta?v=0'
    return None


def construir_cuenta(conn: sqlite3.Connection) -> Json | None:
    r = conn.execute('SELECT username, selection_region, permisos_json FROM cuenta WHERE id = 1').fetchone()
    if r is None or not r[0]:
        return None
    try:
        permisos = json.loads(r[2] or '[]')
    except ValueError:
        permisos = []
    return {'username': str(r[0]), 'avatar': url_avatar(conn), 'region': str(r[1] or ''),
            'permisos': [str(p) for p in permisos] if isinstance(permisos, list) else []}


def cuenta_de_perfil(perfil: Mapping[str, Any]) -> Json | None:
    """`Cuenta` armada directamente del perfil (sin avatar: la imagen solo se sirve desde la caché del hub)."""
    if not perfil.get('username'):
        return None
    permisos = perfil.get('permissions') or []
    return {'username': str(perfil['username']), 'avatar': None, 'region': str(perfil.get('selection_region') or ''),
            'permisos': [str(p) for p in permisos] if isinstance(permisos, list) else []}
