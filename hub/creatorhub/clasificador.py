"""Clasificación de muestras (03 §4.3 + modo parcial de BUILD_SPEC §6.3.2). Funciones puras, solo librería estándar.

Principio: cumplimiento > pista específica > estado_api, salvo que la evidencia POSITIVA de entrega (SUCCEED/REPEATED o
COMPLETED) y la exención ganan siempre. Primera regla que aplica gana (26 reglas; la 8 tiene dos subestados).
`grupo` y `motivo` son función pura del subestado (el mismo CASE que la vista v_muestras).

Modo PARCIAL (puntos de control de la primera sincronización, C34): mismas reglas, salvo que una muestra sin
`solicitada_at` real ni fecha de su pedido de muestra se clasifica con la regla 26 (`sin_respuesta`) en vez de la 25: la
fecha provisional `primera_vez_at` (= hoy) la haría parecer «La tienda todavía no responde». La clasificación final corrige.
Portado de spec/verificacion/comun.py (implementación de referencia; 38 casos en v01).
"""
from __future__ import annotations

import collections
from typing import Any, Iterable, Mapping

from .comun import norm_estado, ts_local

# ------------------------------------------------------------------ estados de la API
# Estados de solicitud documentados (sample_applications/search 202412). 'OPS_ COMPLETED' viene con un espacio en la doc:
# se envía también con ese espacio si la API rechaza la variante sin espacio.
ESTADOS_SOLICITUD: tuple[str, ...] = (
    'PENDING', 'AWAITING_SHIPMENT', 'SHIPPED', 'CONTENT_PENDING', 'COMPLETED', 'FULFILLMENT_SUSPEND',
    'REJECT_CANCELLED', 'OVERDUE_CANCELLED', 'UNFULFILL_CANCELLED', 'DEL_OPEN_COLLAB',
    'SELLER_NOT_SHIP_CANCELLED', 'WITHDRAW_CANCELLED', 'UNFULFILLABLE_CANCELLED',
    'OPS_CANCELLED', 'OPS_FAILED', 'OPS_COMPLETED', 'TO_BE_POST', 'POST_IN_REVIEW', 'POST_FAILED', 'CANCELED',
)
ESTADOS_CUMPLIMIENTO: tuple[str, ...] = ('PENDING', 'ONGOING', 'SUCCEED', 'FAILED', 'OVERDUE', 'SUSPEND', 'CANCELLED',
                                        'EXEMPTED')
# La obligación sigue viva (la clase es 'pendiente_abierta' aunque estado_api diga otra cosa).
CUMPLIMIENTO_ABIERTO: frozenset[str] = frozenset({'PENDING', 'ONGOING', 'SUSPEND'})
# Únicos estados en los que expiration_time es la fecha límite real (en SUSPEND el reloj está detenido; en cerrados la
# API manda la hora de la consulta).
CON_FECHA_LIMITE: frozenset[str] = frozenset({'PENDING', 'ONGOING'})
GUARDIA_EXPIRATION_S = 120
# Prioridad para elegir el cumplimiento VIGENTE (igual que la vista v_cumplimiento_vigente).
PRIORIDAD_CUMPLIMIENTO: Mapping[str, int] = {'PENDING': 0, 'ONGOING': 0, 'SUSPEND': 0, 'SUCCEED': 1, 'REPEATED': 1,
                                             'EXEMPTED': 2, 'FAILED': 3, 'OVERDUE': 3, 'CANCELLED': 4, 'DESCONOCIDO': 5}
# Estados de solicitud «gruesos»: no dicen el motivo; ahí la pista (filtro específico) lo revela.
GENERICOS: frozenset[str] = frozenset({'UNKNOWN', 'CANCELED'})
# Filtros que en la API ignoran el filtro (devuelven casi todas las solicitudes). La regla general detecta otros.
COMODINES_CONOCIDOS: frozenset[str] = frozenset({'CONTENT_PENDING', 'OVERDUE_CANCELLED', 'DEL_OPEN_COLLAB',
                                                 'UNFULFILLABLE_CANCELLED'})
# Orden en que una pista sustituye a un estado genérico (lo más avanzado del ciclo primero).
PRECEDENCIA_PISTAS: tuple[str, ...] = (
    'OPS_COMPLETED', 'COMPLETED', 'POST_FAILED', 'OPS_FAILED', 'UNFULFILL_CANCELLED', 'POST_IN_REVIEW',
    'FULFILLMENT_SUSPEND', 'TO_BE_POST', 'CONTENT_PENDING', 'SHIPPED', 'AWAITING_SHIPMENT', 'PENDING',
    'SELLER_NOT_SHIP_CANCELLED', 'OVERDUE_CANCELLED', 'UNFULFILLABLE_CANCELLED', 'DEL_OPEN_COLLAB', 'OPS_CANCELLED',
    'REJECT_CANCELLED', 'WITHDRAW_CANCELLED')
# Con estado_api = CANCELED solo valen pistas compatibles con una cancelación o un cierre (nunca un estado abierto).
PISTAS_COMPATIBLES_CANCELED: frozenset[str] = frozenset(
    {p for p in PRECEDENCIA_PISTAS if p.endswith('CANCELLED')} | {'COMPLETED', 'OPS_COMPLETED', 'POST_FAILED', 'OPS_FAILED'})
CANCELACIONES_CON_PEDIDO: frozenset[str] = frozenset({'CANCELED', 'UNFULFILLABLE_CANCELLED', 'OPS_CANCELLED',
                                                      'DEL_OPEN_COLLAB', 'OVERDUE_CANCELLED'})
CANCELADAS_ANTES_DE_ENVIAR: frozenset[str] = frozenset({'OVERDUE_CANCELLED', 'DEL_OPEN_COLLAB', 'UNFULFILLABLE_CANCELLED',
                                                        'OPS_CANCELLED', 'CANCELED'})
DIAS_SIN_RESPUESTA = 30          # solicitud sin pedido de muestra y sin respuesta de la tienda (supuesto configurable)

# ------------------------------------------------------------------ grupo y motivo (01_ux §2.2)
GRUPO_DE_SUBESTADO: Mapping[str, str] = {
    'video_aprobado': 'entregada', 'exenta_por_tiktok': 'exenta', 'video_en_revision': 'en_revision',
    'por_grabar': 'por_vencer', 'video_borrado_con_plazo': 'por_vencer', 'pausada': 'pausada',
    'vencida_sin_video': 'vencida', 'video_no_cumplio': 'vencida', 'video_borrado': 'vencida',
    'esperando_aprobacion': 'esperando_aprobacion', 'esperando_respuesta': 'esperando_aprobacion',
    'por_enviar': 'en_camino', 'en_camino': 'en_camino', 'aprobada_esperando_envio': 'en_camino',
    'tienda_no_envio': 'sin_envio', 'cancelada_sin_detalle': 'pedido_cancelado',
    'cumplimiento_cancelado': 'pedido_cancelado', 'rechazada': 'sin_envio', 'retirada': 'sin_envio',
    'cancelada_antes_de_enviar': 'sin_envio', 'sin_respuesta': 'sin_envio',
}
MOTIVO_DE_SUBESTADO: Mapping[str, str] = {
    'video_aprobado': 'Cumplida', 'exenta_por_tiktok': 'Exenta: no tienes que publicar',
    'video_en_revision': 'Tu video está en revisión', 'por_grabar': 'Falta tu video',
    'video_borrado_con_plazo': 'Falta tu video: borraste el anterior', 'pausada': 'Pausada',
    'vencida_sin_video': 'Vencida sin video', 'video_no_cumplio': 'TikTok no aceptó el video',
    'video_borrado': 'Borraste el video antes de cumplir', 'esperando_aprobacion': 'Esperando aprobación de la tienda',
    'esperando_respuesta': 'La tienda todavía no responde', 'por_enviar': 'Aprobada: la tienda debe enviarla',
    'en_camino': 'En camino a tu domicilio', 'aprobada_esperando_envio': 'Aprobada: esperando el envío',
    'tienda_no_envio': 'La tienda no la envió a tiempo', 'cancelada_sin_detalle': 'Se canceló el pedido de la muestra',
    'cumplimiento_cancelado': 'Se canceló el pedido de la muestra', 'rechazada': 'La tienda rechazó la solicitud',
    'retirada': 'Retiraste la solicitud', 'cancelada_antes_de_enviar': 'Se canceló antes del envío',
    'sin_respuesta': 'Sin pedido de muestra',
}
GRUPOS_PENDIENTES: frozenset[str] = frozenset({'por_vencer', 'vencida', 'pausada'})       # 01_ux §2.5
GRUPOS_RECIBIDA: frozenset[str] = frozenset({'entregada', 'exenta', 'en_revision', 'por_vencer', 'pausada', 'vencida'})
CLASES: frozenset[str] = frozenset({'debe_video', 'entregada', 'exenta', 'cancelada', 'nunca_enviada',
                                    'pendiente_abierta'})


def grupo_de(subestado: str) -> str:
    return GRUPO_DE_SUBESTADO[subestado]


def motivo_de(subestado: str) -> str:
    return MOTIVO_DE_SUBESTADO[subestado]


# ------------------------------------------------------------------ comodines y estado efectivo
def filtros_comodin(ids_por_filtro: Mapping[str, set[str]], estado_por_id: Mapping[str, str],
                    sembrados: Iterable[str] = COMODINES_CONOCIDOS) -> set[str]:
    """Filtros que la API ignora (devuelven todo). F es comodín si (a) está sembrado, (b) devolvió ≥ 1 solicitud cuyo
    estado_api es ESPECÍFICO (no genérico) y distinto de F, o (c) devolvió ≥ 95 % de las solicitudes únicas y al menos
    otros 2 filtros devolvieron exactamente el mismo conjunto. Funciona también en una cuenta nueva con solo
    UNKNOWN + COMPLETED."""
    comodin = {f for f in sembrados if f in ids_por_filtro}
    for f, ids in ids_por_filtro.items():
        if any(estado_por_id[i] not in GENERICOS and estado_por_id[i] != f for i in ids):
            comodin.add(f)
    unicos: set[str] = set().union(*ids_por_filtro.values()) if ids_por_filtro else set()
    if unicos:
        grandes = [f for f, ids in ids_por_filtro.items() if len(ids) >= 0.95 * len(unicos)]
        por_conjunto = collections.Counter(frozenset(ids_por_filtro[f]) for f in grandes)
        for f in grandes:
            if por_conjunto[frozenset(ids_por_filtro[f])] >= 3:
                comodin.add(f)
    return comodin


def estado_efectivo(estado_api: Any, pistas: Iterable[str] = ()) -> str:
    """estado_api si es específico; si es genérico (UNKNOWN/CANCELED), la pista de mayor precedencia. Las pistas son solo
    evidencia POSITIVA: que una solicitud no aparezca en un filtro no prueba nada."""
    a = norm_estado(estado_api) or 'UNKNOWN'
    if a not in GENERICOS:
        return a
    normalizadas = {norm_estado(p) for p in pistas}
    for p in PRECEDENCIA_PISTAS:
        if p in normalizadas and (a == 'UNKNOWN' or p in PISTAS_COMPATIBLES_CANCELED):
            return p
    return a


# ------------------------------------------------------------------ reglas (03 §4.3)
def clasificar_regla(estado_api: Any, main_order_id: str | None, cumplimiento: Any, solicitada_at: int | None,
                     ahora: int, pistas: Iterable[str] = (), *, primera_vez_at: int | None = None,
                     parcial: bool = False) -> tuple[str, str, int]:
    """(clase, subestado, número de regla de 03 §4.3).

    estado_api    : status de sample_applications/search ('UNKNOWN' es frecuente)
    main_order_id : None si la API devolvió '0' o vacío
    cumplimiento  : estado del cumplimiento VIGENTE (o None; 'DESCONOCIDO' cuenta como None)
    solicitada_at : fecha REAL de la solicitud: create_time de single_query o, si falta, la del pedido de muestra
    primera_vez_at: primera vez que se vio la muestra; en modo final completa la solicitada efectiva (03 §4.2)
    parcial       : modo de los puntos de control: sin fecha real no se usa primera_vez_at (regla 26 en vez de 25)
    pistas        : filtros ESPECÍFICOS (no comodín) bajo los que apareció la solicitud
    """
    a = estado_efectivo(estado_api, pistas)
    f = norm_estado(cumplimiento)
    if f == 'DESCONOCIDO':
        f = None
    con_pedido = bool(main_order_id)
    efectiva = solicitada_at if solicitada_at else (None if parcial else primera_vez_at)
    # 1-2) evidencia positiva
    if f in ('SUCCEED', 'REPEATED') or a in ('COMPLETED', 'OPS_COMPLETED'):
        return 'entregada', 'video_aprobado', 1
    if f == 'EXEMPTED':
        return 'exenta', 'exenta_por_tiktok', 2
    # 3-6) cumplimiento ABIERTO: todavía hay plazo, aunque estado_api diga POST_FAILED u otra cosa
    if f in CUMPLIMIENTO_ABIERTO:
        if f == 'ONGOING':
            return 'pendiente_abierta', 'video_en_revision', 3
        if f == 'SUSPEND':
            return 'pendiente_abierta', 'pausada', 4
        if a == 'POST_FAILED':
            return 'pendiente_abierta', 'video_borrado_con_plazo', 5
        return 'pendiente_abierta', 'por_grabar', 6
    # 7-9) cumplimiento CERRADO
    if f == 'FAILED':
        return 'debe_video', 'video_no_cumplio', 7
    if f == 'OVERDUE':
        return 'debe_video', ('video_borrado' if a == 'POST_FAILED' else 'vencida_sin_video'), 8
    if f == 'CANCELLED':
        return 'cancelada', 'cumplimiento_cancelado', 9
    # 10-18) sin cumplimiento: estado efectivo (estado_api o pista)
    por_estado = {
        'POST_FAILED': ('debe_video', 'video_borrado', 10), 'OPS_FAILED': ('debe_video', 'video_no_cumplio', 11),
        'UNFULFILL_CANCELLED': ('debe_video', 'vencida_sin_video', 12),
        'POST_IN_REVIEW': ('pendiente_abierta', 'video_en_revision', 13),
        'FULFILLMENT_SUSPEND': ('pendiente_abierta', 'pausada', 14),
        'CONTENT_PENDING': ('pendiente_abierta', 'por_grabar', 15), 'TO_BE_POST': ('pendiente_abierta', 'por_grabar', 15),
        'SHIPPED': ('pendiente_abierta', 'en_camino', 16), 'AWAITING_SHIPMENT': ('pendiente_abierta', 'por_enviar', 17),
        'PENDING': ('pendiente_abierta', 'esperando_aprobacion', 18),
    }
    if a in por_estado:
        return por_estado[a]
    # 19-21) la tienda no la envió / rechazó / retiraste (con o sin pedido de muestra; 01_ux §2.2 reglas 9 y 12)
    if a == 'SELLER_NOT_SHIP_CANCELLED':
        return ('cancelada' if con_pedido else 'nunca_enviada'), 'tienda_no_envio', 19
    if a == 'REJECT_CANCELLED':
        return 'nunca_enviada', 'rechazada', 20
    if a == 'WITHDRAW_CANCELLED':
        return 'nunca_enviada', 'retirada', 21
    # 22-23) con pedido de muestra y sin obligación
    if con_pedido:
        if a in CANCELACIONES_CON_PEDIDO:
            return 'cancelada', 'cancelada_sin_detalle', 22
        return 'pendiente_abierta', 'aprobada_esperando_envio', 23     # UNKNOWN con pedido y sin cumplimiento
    # 24-26) sin pedido de muestra
    if a in CANCELADAS_ANTES_DE_ENVIAR:
        return 'nunca_enviada', 'cancelada_antes_de_enviar', 24
    if efectiva and ahora - efectiva < DIAS_SIN_RESPUESTA * 86400:
        return 'pendiente_abierta', 'esperando_respuesta', 25
    return 'nunca_enviada', 'sin_respuesta', 26


def clasificar(estado_api: Any, main_order_id: str | None, cumplimiento: Any, solicitada_at: int | None, ahora: int,
               pistas: Iterable[str] = (), *, primera_vez_at: int | None = None,
               parcial: bool = False) -> tuple[str, str]:
    """(clase, subestado). Con la firma de comun.clasificar de la referencia: `solicitada_at` ya efectiva."""
    clase, sub, _ = clasificar_regla(estado_api, main_order_id, cumplimiento, solicitada_at, ahora, pistas,
                                     primera_vez_at=primera_vez_at, parcial=parcial)
    return clase, sub


# ------------------------------------------------------------------ fechas y recepción
def fecha_limite(estado: Any, expiration_time: Any, hora_respuesta: int) -> int | None:
    """Fecha límite real o None. Solo en PENDING/ONGOING y nunca si se parece a la hora de la consulta (guardia
    universal, también para el creator_fulfillment de search/single_query)."""
    if norm_estado(estado) not in CON_FECHA_LIMITE or not expiration_time:
        return None
    e = int(expiration_time)
    if e <= hora_respuesta or abs(e - hora_respuesta) <= GUARDIA_EXPIRATION_S:
        return None
    return e


def dias_restantes(fecha_limite_at: int | None, ahora: int) -> int | None:
    """Días CALENDARIO locales (UTC−6): 0 = vence hoy, 1 = mañana, −1 = venció ayer."""
    if not fecha_limite_at:
        return None
    return (ts_local(fecha_limite_at).date() - ts_local(ahora).date()).days


def recibida(clase: str, cumplimiento: Any) -> bool:
    """RECIBIDA si existe registro de cumplimiento (TikTok lo crea al recibirla) o si su clase implica recepción.
    main_order_id no basta: se genera al APROBAR, no al recibir."""
    return cumplimiento is not None or clase in ('debe_video', 'entregada', 'exenta')


# ------------------------------------------------------------------ búsqueda de muestras
def main_order(m: Mapping[str, Any]) -> str | None:
    v = str(m.get('main_order_id') or '').strip()
    return None if v in ('', '0') else v


def unificar_muestras(filas_busqueda: Iterable[Mapping[str, Any]]
                      ) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]], set[str], dict[str, set[str]]]:
    """Deduplica filas de sample_applications/search (repetidas entre filtros y DENTRO de un mismo filtro). Cada fila trae
    `_estado_consulta` (el filtro con que se pidió). Devuelve (por_id, ids_por_filtro, comodines, pistas)."""
    por_id: dict[str, dict[str, Any]] = {}
    ids_por_filtro: dict[str, set[str]] = {}
    for fila in filas_busqueda:
        i = fila['id']
        filtro = norm_estado(fila.get('_estado_consulta')) or 'UNKNOWN'
        ids_por_filtro.setdefault(filtro, set()).add(i)
        previo = por_id.get(i)
        if previo is None:
            por_id[i] = dict(fila)
        else:   # conservar el creator_fulfillment más informativo (distinto de UNKNOWN)
            cf_n = (fila.get('creator_fulfillment') or {}).get('status')
            cf_p = (previo.get('creator_fulfillment') or {}).get('status')
            if cf_p in (None, 'UNKNOWN') and cf_n not in (None, 'UNKNOWN'):
                por_id[i] = dict(fila)
    estado_por_id = {i: norm_estado(m.get('status')) or 'UNKNOWN' for i, m in por_id.items()}
    comodin = filtros_comodin(ids_por_filtro, estado_por_id)
    pistas: dict[str, set[str]] = {i: set() for i in por_id}
    for f, ids in ids_por_filtro.items():
        if f in comodin:
            continue
        for i in ids:
            pistas[i].add(f)
    return por_id, ids_por_filtro, comodin, pistas
