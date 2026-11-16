"""Constantes y reglas puras de la analítica (03 §5, 01 §2 y §6.0). Portado de spec/verificacion/analitica_ref.py y
ux_reglas.py sin dependencias de spec/ ni de research/ (solo librería estándar y creatorhub.comun).
"""
from __future__ import annotations

import datetime as dt
import re

from .. import comun

MESES = ('ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic')
CLASES = ('debe_video', 'entregada', 'exenta', 'cancelada', 'nunca_enviada', 'pendiente_abierta')
GRUPOS = ('entregada', 'exenta', 'en_revision', 'por_vencer', 'pausada', 'vencida', 'esperando_aprobacion', 'en_camino',
          'pedido_cancelado', 'sin_envio')
GRUPOS_PENDIENTES = ('por_vencer', 'vencida', 'pausada')
NIVELES = ('urgente', 'alta', 'media', 'baja', 'no_se_puede_etiquetar')
ORDEN_SALUD = ('socio_con_pendientes', 'con_pendientes', 'con_plan', 'socio', 'al_dia', 'vende_contigo', 'solo_solicitudes',
               'solo_reembolsos')
ESTADOS_ORDEN = ('SETTLED', 'REFUNDED', 'To-SETTLE', 'AWAITING PAYMENT', 'FROZEN', 'UNSPECIFIED', 'NO_DEVUELTA')
GRANULARIDADES = ('dia', 'semana', 'mes')
ORDENES_MUESTRAS = ('prioridad', 'solicitud_asc', 'solicitud_desc', 'valor_desc', 'tienda')
ORDENES_TIENDAS = ('atencion', 'comision', 'deuda', 'nombre')

DIAS_POSIBLE_VIDEO = 7
UMBRAL_SOCIO_CENTAVOS = 100000         # $1,000 en 90 días
UMBRAL_SOCIO_PARTICIPACION = 0.05
UMBRAL_BUENA_COMISION = 4000           # $40 por venta (mínimo de commission.amount)
UMBRAL_TIENDA_CLAVE = 0.20             # alerta tienda_clave (03 §5.11)

ETIQUETA = {
    'vencida_sin_video': 'Vencida sin video', 'video_no_cumplio': 'TikTok no aceptó el video',
    'video_borrado': 'Video borrado antes de cumplir', 'video_aprobado': 'Video entregado',
    'exenta_por_tiktok': 'Exenta de video', 'tienda_no_envio': 'La tienda no la envió', 'cancelada_sin_detalle': 'Cancelada',
    'cumplimiento_cancelado': 'Compromiso cancelado', 'rechazada': 'Rechazada por la tienda', 'retirada': 'La retiraste tú',
    'cancelada_antes_de_enviar': 'Cancelada antes de enviarse', 'sin_respuesta': 'Sin respuesta de la tienda',
    'esperando_aprobacion': 'Esperando aprobación', 'esperando_respuesta': 'Esperando respuesta',
    'por_enviar': 'Aprobada, por enviar', 'en_camino': 'En camino', 'aprobada_esperando_envio': 'Aprobada, esperando envío',
    'por_grabar': 'Te llegó: graba tu video', 'video_borrado_con_plazo': 'Borraste el video: aún hay plazo',
    'video_en_revision': 'Video en revisión', 'pausada': 'Pausada',
}
# Texto del motivo de cada grupo (01 §2.2), función pura del subestado (= comun.MOTIVO_DE_SUBESTADO de spec/verificacion).
MOTIVO_DE_SUBESTADO = {
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
# Estado del pedido (01 §2.8).
ETIQ_ORDEN = {'SETTLED': 'Liquidado', 'REFUNDED': 'Reembolsado', 'To-SETTLE': 'Por liquidar', 'AWAITING PAYMENT': 'Esperando pago',
              'FROZEN': 'Congelado', 'UNSPECIFIED': 'Sin estado', 'NO_DEVUELTA': 'Ya no aparece en TikTok'}
# Etiquetas visibles de grupos y salud (ux_reglas.GRUPO_UI / SALUD_UI, 01 §2.2 y §2.7).
GRUPO_UI = {'entregada': 'Entregada', 'exenta': 'Exenta', 'en_revision': 'En revisión', 'por_vencer': 'Por vencer',
            'pausada': 'Pausada', 'vencida': 'Vencida', 'esperando_aprobacion': 'Esperando aprobación',
            'en_camino': 'En camino', 'pedido_cancelado': 'Pedido de muestra cancelado', 'sin_envio': 'Sin envío'}
SALUD_UI = {'socio_con_pendientes': 'Socio con pendientes', 'con_pendientes': 'Con pendientes', 'con_plan': 'Con plan',
            'socio': 'Socio', 'al_dia': 'Al día', 'vende_contigo': 'Vende contigo',
            'solo_solicitudes': 'Solo solicitudes', 'solo_reembolsos': 'Solo reembolsos'}
# Plantilla sugerida según el motivo de "No se puede" (03 §5.10).
PLANTILLA_NO_SE_PUEDE = {'agotado': 'producto_no_disponible', 'desactivado': 'producto_no_disponible',
                         'no_llego': 'no_me_llego_completa', 'incompleta': 'no_me_llego_completa',
                         'no_va_con_mi_contenido': 'prefiero_otro_producto'}

_PREFIJO = re.compile(r'^\s*(?:(?:BUEN FIN\s*)?(?:【[^】]{0,40}】|\[[^\]]{0,40}\])\s*)+', re.IGNORECASE)


def nombre_corto(titulo: str | None, propio: str | None = None) -> str | None:
    """01 §6.0 «Nombre corto» (≤ 49 caracteres): sin prefijos 【】/[], hasta la primera , . ; | o ' - '. El nombre corto
    que escribió el usuario (`propio`) siempre gana."""
    if propio:
        return propio
    if not titulo:
        return titulo
    limpio = _PREFIJO.sub('', titulo).strip() or titulo.strip()
    t = re.split(r'[,.;|]| - ', limpio, maxsplit=1)[0].strip()
    if len(t) > 48:
        t = t[:48].rsplit(' ', 1)[0].rstrip() + '…'
    if len(t) < 12:
        t = limpio[:48].rstrip()
    return t


def fecha_corta(fecha: str | dt.date) -> str:
    """'2026-11-12' -> '12 nov'."""
    d = dt.date.fromisoformat(str(fecha)[:10])
    return f'{d.day} {MESES[d.month - 1]}'


def etiqueta_punto(granularidad: str, clave: str) -> str:
    """Etiqueta de PuntoSerie: 'nov 26' (mes) · 'sem 10 nov' (semana) · '12 nov' (día)."""
    if granularidad == 'mes':
        return f'{MESES[int(clave[5:7]) - 1]} {clave[2:4]}'
    d = dt.date.fromisoformat(clave)
    return f'sem {d.day} {MESES[d.month - 1]}' if granularidad == 'semana' else f'{d.day} {MESES[d.month - 1]}'


def dias_restantes(fecha_limite_at: int | None, ahora: int) -> int | None:
    """Días CALENDARIO locales (UTC−6) hasta la fecha límite: 0 = vence hoy, 1 = mañana, −1 = venció ayer."""
    return comun.dias_calendario(fecha_limite_at, ahora)


def plural(n: int, singular: str, plural_: str | None = None) -> str:
    return singular if n == 1 else (plural_ or singular + 's')


def hoy_local(ahora: int) -> dt.date:
    return comun.ts_local(ahora).date()


def granularidad_para(desde: dt.date, hasta: dt.date) -> str:
    """Día (≤ 31 días), semana (≤ 92), mes (resto) (03 §5.1)."""
    dias = (hasta - desde).days + 1
    return 'dia' if dias <= 31 else 'semana' if dias <= 92 else 'mes'


def inicio_dia_epoch(fecha: dt.date) -> int:
    """00:00 local de `fecha` en epoch UTC."""
    return comun.epoch_de_fecha_local(fecha.isoformat(), hora=0)
