"""Respuestas de la Display API → tablas de la migración 005 (rev. 5). Sin red: cada función recibe una conexión con
una transacción del escritor YA abierta (la sync usa `almacen.escritor(epoca)`; el callback, la suya).

Tablas: `videos_tiktok` (uno por video PÚBLICO; video_id = content_id de orders/search), `videos_tiktok_dias` (foto
diaria de vistas, likes, comentarios y compartidos; solo se agrega un día si alguna cifra cambió respecto a la última
foto guardada, así que la serie es escalonada), `perfil_tiktok` (una fila) y `perfil_tiktok_dias` (una foto por día).
Historial: 400 días. Nunca se guarda una respuesta cruda ni el avatar (URL firmada que caduca).
"""
from __future__ import annotations

import datetime as dt
import re
import sqlite3
import urllib.parse
from typing import Any, Iterable, Mapping

from ..comun import TZ_MX

DIAS_HISTORIAL = 400
MAX_TEXTO = 4000
MAX_URL = 2048
_RE_ID = re.compile(r'[0-9]{1,25}')
TABLAS_DISPLAY: tuple[str, ...] = ('videos_tiktok_dias', 'videos_tiktok', 'perfil_tiktok_dias', 'perfil_tiktok')
CLAVE_ULTIMA_SYNC = 'display.ultima_sync'          # sync_cursores: resumen JSON de la última pasada


def fecha_mx(epoch: int) -> str:
    return dt.datetime.fromtimestamp(int(epoch), TZ_MX).date().isoformat()


def _entero(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if v >= 0 else None
    if isinstance(v, str) and v.isascii() and v.isdigit() and len(v) <= 18:
        return int(v)
    return None


def _texto(v: Any, tope: int = MAX_TEXTO) -> str | None:
    if not isinstance(v, str):
        return None
    t = v.replace('\x00', '').strip()
    return t[:tope] or None


def _url_https(v: Any) -> str | None:
    if not isinstance(v, str) or not v or len(v) > MAX_URL or not v.isascii():
        return None
    try:
        u = urllib.parse.urlsplit(v)
    except ValueError:
        return None
    if u.scheme != 'https' or not u.hostname or u.username or u.password:
        return None
    return v


def usuario_normalizado(valor: Any) -> str:
    """Nombre de usuario de TikTok comparable entre la Display API y TikTok Shop: sin '@', sin espacios y en
    minúsculas. '' si no es un nombre de usuario válido (así nunca coinciden dos valores vacíos o raros)."""
    if not isinstance(valor, str):
        return ''
    normalizado = valor.strip().removeprefix('@').lower()
    return normalizado if re.fullmatch(r'[a-z0-9._]{1,128}', normalizado) else ''


def normalizar_video(v: Mapping[str, Any]) -> dict[str, Any] | None:
    """Un elemento de video/list → fila de videos_tiktok (sin marcas de tiempo). None si no trae un id válido."""
    vid = v.get('id')
    vid = str(vid) if isinstance(vid, (str, int)) and not isinstance(vid, bool) else ''
    if not _RE_ID.fullmatch(vid):
        return None
    return {'video_id': vid, 'titulo': _texto(v.get('title'), 500), 'descripcion': _texto(v.get('video_description')),
            'duracion_s': _entero(v.get('duration')), 'creado_at': _entero(v.get('create_time')),
            'share_url': _url_https(v.get('share_url')), 'embed_link': _url_https(v.get('embed_link')),
            'vistas': _entero(v.get('view_count')), 'likes': _entero(v.get('like_count')),
            'comentarios': _entero(v.get('comment_count')), 'compartidos': _entero(v.get('share_count')),
            'portada_url': _url_https(v.get('cover_image_url'))}


def normalizar_usuario(u: Mapping[str, Any]) -> dict[str, Any]:
    """`data.user` de user/info → fila de perfil_tiktok. Cada campo puede faltar (depende de los scopes)."""
    verificada = u.get('is_verified')
    return {'open_id': _texto(u.get('open_id'), 200), 'union_id': _texto(u.get('union_id'), 200),
            'username': _texto(u.get('username'), 200), 'nombre': _texto(u.get('display_name'), 200),
            'bio': _texto(u.get('bio_description'), 1000), 'enlace_perfil': _url_https(u.get('profile_deep_link')),
            'verificada': None if not isinstance(verificada, bool) else int(verificada),
            'seguidores': _entero(u.get('follower_count')), 'siguiendo': _entero(u.get('following_count')),
            'likes_total': _entero(u.get('likes_count')), 'videos_total': _entero(u.get('video_count'))}


_CAMPOS_PERFIL = ('open_id', 'union_id', 'username', 'nombre', 'bio', 'enlace_perfil', 'verificada', 'seguidores',
                  'siguiendo', 'likes_total', 'videos_total')
_CIFRAS_PERFIL = ('seguidores', 'siguiendo', 'likes_total', 'videos_total')
_CAMPOS_VIDEO = ('titulo', 'descripcion', 'duracion_s', 'creado_at', 'share_url', 'embed_link', 'vistas', 'likes',
                 'comentarios', 'compartidos')
_CIFRAS_VIDEO = ('vistas', 'likes', 'comentarios', 'compartidos')


def guardar_perfil(db: sqlite3.Connection, perfil: Mapping[str, Any], ahora: int) -> bool:
    """Upsert de perfil_tiktok + foto del día en perfil_tiktok_dias. True si algo cambió (para data_version)."""
    p = {k: perfil.get(k) for k in _CAMPOS_PERFIL}
    previo = db.execute(f'SELECT {", ".join(_CAMPOS_PERFIL)} FROM perfil_tiktok WHERE id = 1').fetchone()
    cambio = previo is None or tuple(previo) != tuple(p[k] for k in _CAMPOS_PERFIL)
    if cambio:
        db.execute(f"""INSERT INTO perfil_tiktok(id, {', '.join(_CAMPOS_PERFIL)}, actualizado_at)
                       VALUES (1, {', '.join('?' * len(_CAMPOS_PERFIL))}, ?)
                       ON CONFLICT(id) DO UPDATE SET {', '.join(f'{k}=excluded.{k}' for k in _CAMPOS_PERFIL)},
                       actualizado_at=excluded.actualizado_at""", (*[p[k] for k in _CAMPOS_PERFIL], ahora))
    hoy = fecha_mx(ahora)
    cifras = tuple(p[k] for k in _CIFRAS_PERFIL)
    dia = db.execute('SELECT seguidores, siguiendo, likes_total, videos_total FROM perfil_tiktok_dias WHERE fecha = ?',
                     (hoy,)).fetchone()
    if dia is None or tuple(dia) != cifras:
        db.execute("""INSERT INTO perfil_tiktok_dias(fecha, seguidores, siguiendo, likes_total, videos_total, actualizado_at)
                      VALUES (?,?,?,?,?,?) ON CONFLICT(fecha) DO UPDATE SET seguidores=excluded.seguidores,
                      siguiendo=excluded.siguiendo, likes_total=excluded.likes_total,
                      videos_total=excluded.videos_total, actualizado_at=excluded.actualizado_at""", (hoy, *cifras, ahora))
        cambio = True
    return cambio


def guardar_videos(db: sqlite3.Connection, videos: Iterable[Mapping[str, Any]], ahora: int) -> tuple[int, int]:
    """Upsert de una página de videos ya normalizados + su foto del día. -> (nuevos, cambiados). Una firma nueva en
    la URL de la portada (caduca en ~6 h) se guarda pero no cuenta como cambio."""
    nuevos = cambiados = 0
    hoy = fecha_mx(ahora)
    for v in videos:
        vid = v['video_id']
        previo = db.execute(f'SELECT {", ".join(_CAMPOS_VIDEO)}, portada_url FROM videos_tiktok WHERE video_id = ?',
                            (vid,)).fetchone()
        valores = tuple(v.get(k) for k in _CAMPOS_VIDEO)
        if previo is None:
            nuevos += 1
            db.execute(f"""INSERT INTO videos_tiktok(video_id, {', '.join(_CAMPOS_VIDEO)}, portada_url, portada_url_at,
                           visto_at, primera_vez_at, actualizado_at)
                           VALUES (?, {', '.join('?' * len(_CAMPOS_VIDEO))}, ?, ?, ?, ?, ?)""",
                       (vid, *valores, v.get('portada_url'), ahora if v.get('portada_url') else None, ahora, ahora, ahora))
        else:
            distinto = tuple(previo[k] for k in _CAMPOS_VIDEO) != valores
            if distinto:
                cambiados += 1
            db.execute(f"""UPDATE videos_tiktok SET {', '.join(f'{k}=?' for k in _CAMPOS_VIDEO)}, portada_url=?,
                           portada_url_at=CASE WHEN ? IS NULL THEN portada_url_at ELSE ? END, visto_at=?,
                           actualizado_at=CASE WHEN ? THEN ? ELSE actualizado_at END WHERE video_id=?""",
                       (*valores, v.get('portada_url') or previo['portada_url'], v.get('portada_url'), ahora, ahora,
                        int(distinto), ahora, vid))
        cifras = tuple(v.get(k) for k in _CIFRAS_VIDEO)
        ultimo = db.execute('SELECT fecha, vistas, likes, comentarios, compartidos FROM videos_tiktok_dias '
                            'WHERE video_id = ? ORDER BY fecha DESC LIMIT 1', (vid,)).fetchone()
        if ultimo is None or ultimo['fecha'] == hoy or tuple(ultimo)[1:] != cifras:
            db.execute("""INSERT INTO videos_tiktok_dias(video_id, fecha, vistas, likes, comentarios, compartidos,
                          actualizado_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(video_id, fecha) DO UPDATE SET
                          vistas=excluded.vistas, likes=excluded.likes, comentarios=excluded.comentarios,
                          compartidos=excluded.compartidos, actualizado_at=excluded.actualizado_at""",
                       (vid, hoy, *cifras, ahora))
    return nuevos, cambiados


def quitar_no_vistos(db: sqlite3.Connection, vistos: set[str]) -> int:
    """Tras un listado COMPLETO: los videos que ya no salen (privados o borrados) dejan de estar en videos_tiktok (su
    historial diario se conserva hasta la poda). -> cuántos se quitaron."""
    quitar = [r[0] for r in db.execute('SELECT video_id FROM videos_tiktok') if r[0] not in vistos]
    for i in range(0, len(quitar), 500):
        trozo = quitar[i:i + 500]
        db.execute(f'DELETE FROM videos_tiktok WHERE video_id IN ({",".join("?" * len(trozo))})', trozo)
    return len(quitar)


def podar_historial(db: sqlite3.Connection, ahora: int) -> int:
    limite = (dt.datetime.fromtimestamp(int(ahora), TZ_MX).date() - dt.timedelta(days=DIAS_HISTORIAL)).isoformat()
    n = db.execute('DELETE FROM videos_tiktok_dias WHERE fecha < ?', (limite,)).rowcount
    n += db.execute('DELETE FROM perfil_tiktok_dias WHERE fecha < ?', (limite,)).rowcount
    return n


def borrar_todo(db: sqlite3.Connection) -> None:
    """Desconectar con «borrar datos» o cambio de cuenta: fuera lo descargado de la Display API y sus portadas."""
    for t in TABLAS_DISPLAY:
        db.execute(f'DELETE FROM {t}')                   # nombres de una tupla fija, nunca de la entrada
    db.execute("DELETE FROM imagenes WHERE tipo = 'v'")
    db.execute("DELETE FROM sync_cursores WHERE clave LIKE 'display.%'")


def leer_perfil(db: sqlite3.Connection) -> dict[str, Any] | None:
    r = db.execute(f'SELECT {", ".join(_CAMPOS_PERFIL)}, actualizado_at FROM perfil_tiktok WHERE id = 1').fetchone()
    if r is None:
        return None
    d = {k: r[k] for k in (*_CAMPOS_PERFIL, 'actualizado_at')}
    d['verificada'] = None if d['verificada'] is None else bool(d['verificada'])
    return d


__all__ = ['usuario_normalizado', 'normalizar_video', 'normalizar_usuario', 'guardar_perfil', 'guardar_videos', 'quitar_no_vistos',
           'podar_historial', 'borrar_todo', 'leer_perfil', 'fecha_mx', 'TABLAS_DISPLAY', 'CLAVE_ULTIMA_SYNC',
           'DIAS_HISTORIAL']
