"""Cruce de ventas con las métricas de la Display API (rev. 5, 15/11/2026), dentro de la MISMA transacción de lectura.

El `video_id` de la Display API ES el `content_id` de las líneas de orders/search. Reglas de los campos OPCIONALES:
- Si nunca se trajo nada de la Display API (tablas vacías), los campos NO se envían (respuestas idénticas a la rev. 4).
- Si hay datos y un video no está en la Display API (privado, borrado o de otra cuenta), sus campos van en null.
- «Pedidos por 1,000 vistas» = pedidos válidos ÷ vistas × 1,000 (2 decimales) y «comisión por 1,000 vistas» = comisión
  estimada (centavos) ÷ vistas × 1,000 (entero). En FilaVideo se usan las cifras de TODA la vida del video (aunque la
  lista venga filtrada por periodo: las vistas no tienen periodo); en VideoDeProducto, las de ESE producto en el video.
  Con 0 vistas o sin vistas: null.
- Portada: '/img/v/<video_id>?v=…' con la regla C45 (null si TikTok no dio portada).
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

Json = dict[str, Any]
CAMPOS_FILA_VIDEO: tuple[str, ...] = ('vistas', 'likes', 'comentarios', 'compartidos', 'portada', 'descripcion',
                                      'duracion_s', 'publicado_at', 'metricas_at', 'pedidos_por_mil_vistas',
                                      'comision_por_mil_vistas_centavos')
CAMPOS_VIDEO_PRODUCTO: tuple[str, ...] = ('vistas', 'likes', 'comentarios', 'compartidos', 'portada',
                                          'pedidos_por_mil_vistas', 'comision_por_mil_vistas_centavos')
MAX_TENDENCIA = 400


@dataclass
class DatosDisplay:
    videos: dict[str, Json] = field(default_factory=dict)
    perfil: Json | None = None


def cargar(conn: sqlite3.Connection) -> DatosDisplay | None:
    """None si nunca hubo datos de la Display API (o si la base aún no tiene sus tablas)."""
    try:
        filas = conn.execute('SELECT video_id, titulo, descripcion, duracion_s, creado_at, vistas, likes, comentarios, '
                             'compartidos, visto_at FROM videos_tiktok').fetchall()
        perfil = conn.execute('SELECT username, nombre, seguidores, siguiendo, likes_total, videos_total, actualizado_at '
                              'FROM perfil_tiktok WHERE id = 1').fetchone()
    except sqlite3.OperationalError:
        return None
    if not filas and perfil is None:
        return None
    videos = {str(f[0]): {'titulo': f[1], 'descripcion': f[2], 'duracion_s': f[3], 'creado_at': f[4], 'vistas': f[5],
                          'likes': f[6], 'comentarios': f[7], 'compartidos': f[8], 'visto_at': f[9]} for f in filas}
    p = None
    if perfil is not None:
        p = dict(zip(('username', 'nombre', 'seguidores', 'siguiendo', 'likes_total', 'videos_total', 'actualizado_at'),
                     tuple(perfil)))
    return DatosDisplay(videos=videos, perfil=p)


def por_mil(valor: int | float | None, vistas: int | None, decimales: int | None) -> int | float | None:
    if valor is None or not vistas or vistas <= 0:
        return None
    x = Decimal(str(valor)) * 1000 / Decimal(vistas)
    if decimales is None:
        return int(x.quantize(Decimal(1), ROUND_HALF_UP))
    return float(x.quantize(Decimal(1).scaleb(-decimales), ROUND_HALF_UP))


def campos_fila_video(d: DatosDisplay, cid: str, pedidos_validos: int, comision_centavos: int,
                      portada: str | None) -> Json:
    """Campos opcionales de FilaVideo para `cid` (null si el video no está en la Display API)."""
    v = d.videos.get(cid)
    if v is None:
        return {k: None for k in CAMPOS_FILA_VIDEO}
    vistas = v['vistas']
    return {'vistas': vistas, 'likes': v['likes'], 'comentarios': v['comentarios'], 'compartidos': v['compartidos'],
            'portada': portada, 'descripcion': v['titulo'] or v['descripcion'], 'duracion_s': v['duracion_s'],
            'publicado_at': v['creado_at'], 'metricas_at': v['visto_at'],
            'pedidos_por_mil_vistas': por_mil(pedidos_validos, vistas, 2),
            'comision_por_mil_vistas_centavos': por_mil(comision_centavos, vistas, None)}


def campos_video_producto(d: DatosDisplay, cid: str, pedidos_validos: int, comision_centavos: int,
                          portada: str | None) -> Json:
    v = d.videos.get(cid)
    if v is None:
        return {k: None for k in CAMPOS_VIDEO_PRODUCTO}
    vistas = v['vistas']
    return {'vistas': vistas, 'likes': v['likes'], 'comentarios': v['comentarios'], 'compartidos': v['compartidos'],
            'portada': portada, 'pedidos_por_mil_vistas': por_mil(pedidos_validos, vistas, 2),
            'comision_por_mil_vistas_centavos': por_mil(comision_centavos, vistas, None)}


def _entero_positivo(v: Any, minimo: int = 1) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= minimo else None


def ultima_sync(conn: sqlite3.Connection) -> tuple[int | None, int | None]:
    """(instante, tope) de la última pasada REGISTRADA de la Display API (sync_cursores 'display.ultima_sync'). `tope` =
    el visto_at más reciente cuando se escribió ese cursor (un cursor anterior a la rev. 6 no lo trae: vale el
    instante). (None, None) si nunca hubo."""
    try:
        r = conn.execute("SELECT valor FROM sync_cursores WHERE clave = 'display.ultima_sync'").fetchone()
    except sqlite3.OperationalError:
        return None, None
    if r is None:
        return None, None
    try:
        valor = json.loads(r[0])
        at, tope = valor.get('at'), valor.get('visto_tope')
    except (ValueError, AttributeError):
        return None, None
    at = _entero_positivo(at)
    if at is None:
        return None, None
    tope = _entero_positivo(tope, 0)
    return at, (at if tope is None else tope)


def ultima_sync_at(conn: sqlite3.Connection) -> int | None:
    """Instante de la última pasada registrada de la Display API; None si nunca hubo."""
    return ultima_sync(conn)[0]


def pasadas_sin_registrar(conn: sqlite3.Connection) -> frozenset[int]:
    """Instantes de las pasadas que empezaron desde la última registrada (en curso o interrumpidas): los videos que
    guardaron sí salieron en una pasada posterior a la registrada, sea cual sea el reloj."""
    from ..tiktok_dev.datos import pasadas_sin_registrar as leer
    return frozenset(leer(conn))


def huella_vistos(conn: sqlite3.Connection) -> str:
    """Resumen de visto_at de los videos guardados: cambia también con las páginas que guarda una pasada aún sin
    registrar (en curso o interrumpida), que mueven `metricas_at` y `publicacion` del catálogo (para su ETag)."""
    try:
        n, suma, maximo = conn.execute('SELECT COUNT(*), COALESCE(SUM(visto_at), 0), COALESCE(MAX(visto_at), 0) '
                                       'FROM videos_tiktok').fetchone()
    except sqlite3.OperationalError:
        return '0.0.0'
    return f'{n}.{suma}.{maximo}'


def fotos_sin_video(conn: sqlite3.Connection, solo: str | None = None,
                    ids: list[str] | None = None) -> dict[str, Json]:
    """Videos que ya no están en videos_tiktok (dejaron de ser públicos tras un listado completo) pero conservan
    historial diario: su foto más reciente {fecha, vistas, likes, comentarios, compartidos, actualizado_at}.
    `solo`: limita la búsqueda a un ID (el detalle no recorre todo el historial); `ids`: a esos IDs (por la llave
    primaria, en tandas de 500)."""
    if ids is not None:
        unicos = list(dict.fromkeys(ids))
        tandas = [unicos[i:i + 500] for i in range(0, len(unicos), 500)]
    else:
        tandas = [[solo] if solo is not None else []]
    fotos: dict[str, Json] = {}
    for tanda in tandas:
        filtro = f'AND video_id IN ({",".join("?" * len(tanda))})' if tanda else ''
        try:
            filas = conn.execute(f"""SELECT d.video_id, d.fecha, d.vistas, d.likes, d.comentarios, d.compartidos,
                                            d.actualizado_at
                                     FROM videos_tiktok_dias d
                                     JOIN (SELECT video_id, MAX(fecha) AS fecha FROM videos_tiktok_dias
                                           WHERE video_id NOT IN (SELECT video_id FROM videos_tiktok) {filtro}
                                           GROUP BY video_id) m ON m.video_id = d.video_id AND m.fecha = d.fecha""",
                                 tanda).fetchall()
        except sqlite3.OperationalError:
            return {}
        fotos.update({str(f[0]): {'fecha': f[1], 'vistas': f[2], 'likes': f[3], 'comentarios': f[4],
                                  'compartidos': f[5], 'actualizado_at': f[6]} for f in filas})
    return fotos


def tendencia(conn: sqlite3.Connection, cid: str) -> list[Json]:
    """Fotos diarias guardadas de un video (escalonadas: un día solo aparece si alguna cifra cambió), de la más vieja a
    la más nueva; máx. 400."""
    filas = conn.execute('SELECT fecha, vistas, likes, comentarios, compartidos FROM videos_tiktok_dias WHERE video_id = ? '
                         'ORDER BY fecha DESC LIMIT ?', (cid, MAX_TENDENCIA)).fetchall()
    return [{'fecha': f[0], 'vistas': f[1], 'likes': f[2], 'comentarios': f[3], 'compartidos': f[4]}
            for f in reversed(filas)]


def resumen_perfil(conn: sqlite3.Connection, d: DatosDisplay, hoy: dt.date) -> Json | None:
    """ResumenPerfilTikTok para Inicio: cifras actuales y su cambio contra la foto de hace 7 días (o la más vieja
    posterior, si aún no hay 7 días de historial); null mientras no haya con qué comparar."""
    p = d.perfil
    if p is None:
        return None
    hace7 = (hoy - dt.timedelta(days=7)).isoformat()
    base = conn.execute('SELECT seguidores, likes_total FROM perfil_tiktok_dias WHERE fecha <= ? ORDER BY fecha DESC '
                        'LIMIT 1', (hace7,)).fetchone()
    if base is None:
        base = conn.execute('SELECT seguidores, likes_total FROM perfil_tiktok_dias WHERE fecha < ? ORDER BY fecha '
                            'LIMIT 1', (hoy.isoformat(),)).fetchone()

    def cambio(actual: int | None, previo: int | None) -> int | None:
        return None if actual is None or previo is None else int(actual) - int(previo)
    return {'username': p['username'], 'nombre': p['nombre'], 'seguidores': p['seguidores'], 'siguiendo': p['siguiendo'],
            'likes_total': p['likes_total'], 'videos_total': p['videos_total'],
            'seguidores_cambio_7d': cambio(p['seguidores'], base[0] if base else None),
            'likes_cambio_7d': cambio(p['likes_total'], base[1] if base else None),
            'actualizado_at': p['actualizado_at']}


__all__ = ['DatosDisplay', 'cargar', 'campos_fila_video', 'campos_video_producto', 'tendencia', 'resumen_perfil',
           'ultima_sync', 'ultima_sync_at', 'pasadas_sin_registrar', 'huella_vistos', 'fotos_sin_video', 'por_mil',
           'CAMPOS_FILA_VIDEO',
           'CAMPOS_VIDEO_PRODUCTO']
