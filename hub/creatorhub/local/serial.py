"""Filas SQLite del estado local -> objetos de spec/contrato.ts con las claves EXACTAS (PlanVideo, AvisoTienda,
PlantillaMensaje, PreferenciasSincronizadas, Nota, Recordatorio). Los usan EstadoLocal y la analítica (detalle de
muestra y de tienda, copia sin conexión), así un objeto se ve igual en todas las respuestas.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable, Mapping

# PreferenciasSincronizadas por omisión (01 §7.2 = analitica_ref.PREFERENCIAS_POR_OMISION) + apariencia (C24).
PREFERENCIAS_POR_OMISION: dict[str, Any] = {
    'capacidad_videos_dia': 3, 'dias_videos': [0, 1, 2, 3, 4, 5], 'programo_mis_videos': False, 'firma': '',
    'recordatorio_diario': True, 'hora_recordatorio': '10:00', 'aviso_por_vencer': True, 'aviso_promesas': True,
    'aviso_atrasados': True, 'resumen_semanal': False, 'orden_plan': 'sugerido', 'umbral_publicado_sin_ventas_dias': 14,
    'tema': 'sistema', 'reducir_animaciones': 'sistema',
}
CLAVES_PREFERENCIAS = tuple(PREFERENCIAS_POR_OMISION)

CAMPOS_PLAN = ('id', 'application_id', 'product_id', 'tienda_key', 'titulo', 'fecha_plan', 'estado', 'fecha_video_listo',
               'programada_para_at', 'fecha_publicada', 'content_id', 'enlace_video', 'vinculo_origen',
               'sugerencias_descartadas', 'motivo_no_se_puede', 'motivo_texto', 'fijada', 'nombre_corto', 'notas', 'orden',
               'en_cohorte_desde_at', 'creado_at', 'actualizado_at', 'rev', 'dispositivo_id')
CAMPOS_AVISO = ('id', 'tienda_key', 'solicitud_ids', 'plantilla_id', 'texto', 'compromisos', 'fecha_anterior', 'origen',
                'copiado_at', 'marcado_enviado_at', 'quitado_at', 'creado_at', 'actualizado_at', 'rev', 'dispositivo_id')
CAMPOS_PLANTILLA = ('id', 'nombre', 'cuerpo', 'predeterminada', 'creado_at', 'actualizado_at', 'rev', 'dispositivo_id')
CAMPOS_NOTA = ('id', 'entidad', 'entidad_id', 'texto', 'fijada', 'creado_at', 'actualizado_at', 'rev', 'dispositivo_id')
CAMPOS_RECORDATORIO = ('id', 'entidad', 'entidad_id', 'titulo', 'vence_at', 'repetir', 'estado', 'pospuesto_hasta',
                       'notificado_at', 'creado_at', 'actualizado_at', 'rev', 'dispositivo_id')

# Cohorte (BUILD §4.3): la del plan si la tiene; si no, la de la muestra.
SQL_PLANES = """
SELECT pl.*, COALESCE(pl.en_cohorte_desde_at, m.en_cohorte_desde_at) AS cohorte
FROM plan_videos pl LEFT JOIN muestras m ON m.application_id = pl.application_id
WHERE pl.eliminado = 0
"""


def filas(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    """Filas como dict, sin depender del row_factory de la conexión del almacén."""
    cur = conn.execute(sql, tuple(params))
    nombres = [d[0] for d in cur.description or ()]
    return [dict(zip(nombres, r)) for r in cur.fetchall()]


def fila(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    r = filas(conn, sql, params)
    return r[0] if r else None


def _json(texto: Any, omision: Any) -> Any:
    if texto in (None, ''):
        return omision
    try:
        return json.loads(texto)
    except (TypeError, ValueError):
        return omision


def plan(f: Mapping[str, Any]) -> dict[str, Any]:
    """PlanVideo. `cohorte` (si viene de SQL_PLANES) = COALESCE(plan, muestra)."""
    d = {k: f.get(k) for k in CAMPOS_PLAN if k not in ('sugerencias_descartadas', 'fijada')}
    d['sugerencias_descartadas'] = [str(x) for x in _json(f.get('sugerencias_descartadas_json'), [])]
    d['fijada'] = bool(f.get('fijada'))
    if 'cohorte' in f:
        d['en_cohorte_desde_at'] = f['cohorte']
    return {k: d[k] for k in CAMPOS_PLAN}


def aviso(f: Mapping[str, Any]) -> dict[str, Any]:
    d = {k: f.get(k) for k in CAMPOS_AVISO}
    d['solicitud_ids'] = [str(x) for x in _json(f.get('solicitud_ids_json'), [])]
    d['compromisos'] = {str(k): str(v) for k, v in dict(_json(f.get('compromisos_json'), {})).items()}
    return d


def plantilla(f: Mapping[str, Any]) -> dict[str, Any]:
    d = {k: f.get(k) for k in CAMPOS_PLANTILLA}
    d['predeterminada'] = bool(f.get('predeterminada'))
    return d


def nota(f: Mapping[str, Any]) -> dict[str, Any]:
    d = {k: f.get(k) for k in CAMPOS_NOTA}
    d['fijada'] = bool(f.get('fijada'))
    return d


def recordatorio(f: Mapping[str, Any]) -> dict[str, Any]:
    return {k: f.get(k) for k in CAMPOS_RECORDATORIO}


def preferencias(f: Mapping[str, Any] | None) -> dict[str, Any]:
    """PreferenciasSincronizadas: lo guardado sobre las omisiones (siempre con tema y reducir_animaciones) + rev.
    Sin fila (aún no se sembró): las omisiones con rev 0."""
    guardado = _json(f.get('valor_json'), {}) if f else {}
    base = dict(PREFERENCIAS_POR_OMISION)
    base.update({k: v for k, v in dict(guardado).items() if k in PREFERENCIAS_POR_OMISION})
    base['dias_videos'] = list(base['dias_videos'])
    base['rev'] = int(f['rev']) if f else 0
    return base


# ---------------------------------------------------------------------- lecturas compartidas (dentro de una transacción)
def leer_planes(conn: sqlite3.Connection, where: str = '', params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    return [plan(f) for f in filas(conn, SQL_PLANES + where + ' ORDER BY pl.orden, pl.id', params)]


def leer_avisos(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [aviso(f) for f in filas(conn, 'SELECT * FROM avisos_tienda ORDER BY creado_at, id')]


def leer_plantillas(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [plantilla(f) for f in filas(conn, 'SELECT * FROM plantillas ORDER BY rowid')]


def leer_notas(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [nota(f) for f in filas(conn, 'SELECT * FROM notas WHERE eliminado = 0 ORDER BY creado_at, id')]


def leer_recordatorios(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [recordatorio(f) for f in filas(conn, 'SELECT * FROM recordatorios WHERE eliminado = 0 ORDER BY vence_at, id')]


def leer_preferencias(conn: sqlite3.Connection) -> dict[str, Any]:
    return preferencias(fila(conn, 'SELECT valor_json, rev FROM preferencias_sinc WHERE id = 1'))


def local_rev(conn: sqlite3.Connection) -> int:
    f = fila(conn, "SELECT valor FROM meta WHERE clave = 'local_rev'")
    return int(f['valor']) if f else 0
