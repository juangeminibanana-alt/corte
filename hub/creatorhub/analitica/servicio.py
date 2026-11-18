"""Analitica (BUILD_SPEC §6.2): lecturas compuestas del contrato REST, cada una en UNA transacción de lectura del almacén.

Solo lectura. Cada método valida su query contra listas blancas (filtros.py), abre `almacen.lector()`, arma la respuesta
con `Vista` y agrega `meta_imagenes` (regla C45) con las URLs que trae esa misma respuesta. `etag()` lee las tres
versiones en una transacción: 'dv<N>-lr<M>-ir<K>' (C45).
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Callable, Mapping

from ..interfaces import Almacen, Json, Reloj
from . import display as display_api
from . import filtros as F
from . import reglas as R
from .vista import Vista

_log = logging.getLogger('creatorhub.analitica')

TOP_VIDEOS_COPIA = 100           # SnapshotResponse.videos: top 100 por comisión
DIAS_ORDENES_COPIA = 90          # SnapshotResponse.ordenes_recientes: últimos 90 días…
MAX_ORDENES_COPIA = 500          # …máximo 500 pedidos (los más recientes)
MAX_FICHAS_COPIA = 100           # Galería/SKU ya almacenados; muestras pendientes primero, sin red.


class AnaliticaSqlite:
    """Implementa interfaces.Analitica sobre el almacén SQLite (vistas v_lineas, v_muestras, v_salud_tiendas)."""

    def __init__(self, almacen: Almacen, reloj: Reloj) -> None:
        self.almacen = almacen
        self.reloj = reloj

    # -------------------------------------------------------------- utilidades
    def _leer(self, armar: Callable[[Vista], Json], con_meta: bool = True) -> Json:
        with self.almacen.lector() as conn:
            v = Vista(conn, self.reloj.ahora())
            resp = armar(v)
            if con_meta:
                resp['meta_imagenes'] = v.img.meta_para(resp)
            return resp

    # -------------------------------------------------------------- Protocol Analitica
    def dashboard(self, periodo: str) -> Json:
        clave = F.periodo(periodo)
        return self._leer(lambda v: v.dashboard(clave, v.conexion_guardada))

    def muestras(self, filtros: Mapping[str, str]) -> Json:
        f = F.muestras(filtros)

        def armar(v: Vista) -> Json:
            items = [v.muestra_vista(m) for m in v.muestras_filtradas(f)]
            conteos, por_grupo = v.conteos()
            return {'items': items, 'total': len(items), 'conteos': conteos, 'por_grupo': por_grupo,
                    'data_version': v.data_version}
        return self._leer(armar)

    def muestra_detalle(self, application_id: str) -> Json:
        aid = F.id_muestra(application_id)
        return self._leer(lambda v: v.muestra_detalle(aid))

    def tiendas(self, filtros: Mapping[str, str]) -> Json:
        orden, desde, hasta = F.tiendas(filtros)

        def armar(v: Vista) -> Json:
            items = v.tiendas(orden, desde, hasta)
            return {'items': items, 'total': len(items), 'data_version': v.data_version}
        return self._leer(armar)

    def tienda_detalle(self, tienda_key: str, filtros: Mapping[str, str]) -> Json:
        tk = F.clave_tienda(tienda_key)
        desde, hasta = F.solo_rango(filtros)

        def armar(v: Vista) -> Json:
            real = v.resolver_tienda(tk)
            if real is None:
                raise F.no_encontrado('No encontramos esa tienda.')
            return v.tienda_detalle(real, desde, hasta)
        return self._leer(armar)

    def serie(self, filtros: Mapping[str, str]) -> Json:
        gran, desde, hasta = F.serie(filtros)

        def armar(v: Vista) -> Json:
            h = hasta or v.hoy
            d = desde or min(v.primera_fecha or h, h)
            if d > h:
                raise F.invalido('«desde» no puede ser posterior a «hasta».', 'desde')
            g = gran or R.granularidad_para(d, h)
            return {'granularidad': g, 'desde': d.isoformat(), 'hasta': h.isoformat(), 'puntos': v.serie(g, d, h)}
        return self._leer(armar, con_meta=False)        # SerieResponse no lleva meta_imagenes

    def videos(self, filtros: Mapping[str, str]) -> Json:
        desde, hasta, limite = F.con_limite(filtros)

        def armar(v: Vista) -> Json:
            items, total = v.videos(desde, hasta, limite)
            return {'items': items, 'total': total, 'data_version': v.data_version}
        return self._leer(armar)

    def video_detalle(self, content_id: str) -> Json:
        cid = F.id_numerico(content_id, 'video')
        return self._leer(lambda v: v.video_detalle(cid))

    def catalogo_videos(self, filtros: Mapping[str, str]) -> Json:
        """rev. 6: videos publicados y videos con ventas en una sola lista (GET /api/catalogo/videos)."""
        orden, historial, limite = F.catalogo(filtros)
        return self._leer(lambda v: v.videos_catalogo(orden, historial, limite))

    def video_catalogo(self, content_id: str) -> Json:
        """rev. 6: detalle de un video del catálogo, tenga o no ventas (GET /api/catalogo/videos/{content_id})."""
        cid = F.id_numerico(content_id, 'video')
        return self._leer(lambda v: v.video_catalogo_detalle(cid))

    def productos(self, filtros: Mapping[str, str]) -> Json:
        desde, hasta, limite = F.con_limite(filtros)

        def armar(v: Vista) -> Json:
            items, total = v.productos(desde, hasta, limite)
            return {'items': items, 'total': total, 'data_version': v.data_version}
        return self._leer(armar)

    def producto_detalle(self, product_id: str) -> Json:
        pid = F.id_numerico(product_id, 'producto')
        return self._leer(lambda v: v.producto_detalle(pid))

    def ordenes(self, filtros: Mapping[str, str]) -> Json:
        f = F.ordenes(filtros)
        return self._leer(lambda v: v.ordenes(f))

    def snapshot(self, cuenta: Json | None, conexion: Json, sync: Json) -> Json:
        conexion = dict(conexion or {})
        sync = dict(sync or {})

        def armar(v: Vista) -> Json:
            con = conexion if conexion.get('estado') else dict(v.conexion_guardada or {}, aviso=None)
            todo = F.resolver_periodo('todo', v.hoy, v.primera_fecha)
            muestras = [v.muestra_vista(m) for m in v.muestras_filtradas(F.muestras({}))]
            tiendas = v.tiendas('atencion')
            desde_ord = v.hoy - dt.timedelta(days=DIAS_ORDENES_COPIA - 1)
            f_ord = F.FiltrosOrdenes(desde=desde_ord, hasta=None, estados=None, tienda=None, producto=None, video=None,
                                     q=None, pagina=1, por_pagina=200)
            pendientes = v.pendientes()
            productos = v.productos_todos(None, None)
            tiendas_extra = {m['tienda_key'] for m in pendientes if m['tienda_key']}
            tiendas_extra |= {a['tienda_key'] for a in v.avisos if a['tienda_key'] in v.S}
            extras = {
                'muestras': {m['application_id']: {'plantilla_sugerida': v.plantilla_sugerida(m),
                                                   'videos_del_producto': v.videos_del_producto(m['product_id']),
                                                   'historial': v.historial(m['application_id'])}
                             for m in pendientes},
                'tiendas': {tk: {'plantilla_sugerida': v.plantilla_tienda(tk, v.es_socio(tk)), 'serie': v.serie_tienda(tk)}
                            for tk in sorted(tiendas_extra) if tk in v.S},
                'productos': self._productos_copia(v, pendientes, muestras, productos),
            }
            cuenta_out = None
            if cuenta:
                cuenta_out = {k: cuenta.get(k) for k in ('username', 'avatar', 'region', 'permisos')}
                cuenta_out['avatar'] = v.img.avatar()        # C45: la analítica emite la URL de la imagen
                cuenta_out['permisos'] = list(cuenta_out['permisos'] or [])
            return {
                'version_esquema': 1, 'data_version': v.data_version, 'local_rev': v.local_rev, 'img_rev': v.img_rev,
                'generado_at': v.ahora, 'cuenta': cuenta_out,
                'conexion': {'estado': con.get('estado') or 'sin_credenciales', 'aviso': con.get('aviso')},
                'sync': {'ultima_ok_at': sync.get('ultima_ok_at'), 'ultima_estado': sync.get('ultima_estado')},
                'dashboard': {'30d': v.dashboard('30d', con), 'todo': v.dashboard('todo', con)},
                'muestras': muestras, 'tiendas': tiendas,
                'videos': v.videos(None, None, TOP_VIDEOS_COPIA)[0],
                'productos': productos,
                'ordenes_recientes': v.ordenes(f_ord, max_items=MAX_ORDENES_COPIA)['items'],
                'series': {'mes': v.serie('mes', todo.desde, todo.hasta), 'semana': v.serie('semana', todo.desde, todo.hasta)},
                'local': {'planes': v.planes, 'notas': v.notas, 'recordatorios': v.recordatorios, 'avisos': v.avisos_vista(),
                          'plantillas': v.plantillas, 'preferencias': v.preferencias},
                'extras': extras,
            }

        with self.almacen.lector() as conn:
            v = Vista(conn, self.reloj.ahora())
            resp = armar(v)
            meta = v.img.meta_para(resp)
            resp['meta_imagenes'] = meta
            resp['imagenes'] = [u + '&t=sm' for u in meta]   # solo las ya descargadas (C45): el celular precarga 'sm'
            return resp

    @staticmethod
    def _productos_copia(v: Vista, pendientes: list[Json], muestras: list[Json], productos: list[Json]) -> Json:
        """Sólo fichas representadas en la copia y con vitrina/SKU ya consultados. No consulta TikTok.

        La galería conserva sus URLs versionadas para que meta_para/imagenes incluyan también las fotos 'g'.
        El límite evita convertir una copia de trabajo en una descarga del catálogo completo.
        """
        cacheados = {r['product_id'] for r in v.filas(
            'SELECT product_id FROM vitrina UNION SELECT product_id FROM muestra_etiquetas WHERE huella IS NOT NULL '
            'UNION SELECT product_id FROM producto_evidencia')}
        candidatos = [m['product_id'] for m in pendientes]
        candidatos += [m['producto']['product_id'] for m in muestras]
        candidatos += [p['product_id'] for p in productos]
        salida: Json = {}
        for pid in candidatos:
            if pid not in cacheados or pid in salida:
                continue
            salida[pid] = v.producto_extendido(pid)
            if len(salida) >= MAX_FICHAS_COPIA:
                break
        return salida

    def etag(self, con_display: bool = False) -> str:
        """'dv<N>-lr<M>-ir<K>'. `con_display` (rutas del catálogo, rev. 6) agrega '|d<instante de la última pasada de la
        Display API>-<huella de visto_at>[-p<pasadas sin registrar>]', leído en LA MISMA transacción: `publicacion`,
        `metricas_at` y `display.ultima_sync_at` dependen de cada pasada, aunque no cambie data_version (una pasada sin
        videos nuevos ni cambiados no la sube) y aunque se interrumpa después de guardar alguna página."""
        with self.almacen.lector() as conn:
            dv, lr, ir = self.almacen.versiones(conn)
            marca = ''
            if con_display:
                pendientes = '.'.join(str(x) for x in sorted(display_api.pasadas_sin_registrar(conn)))
                marca = (f'|d{display_api.ultima_sync_at(conn) or 0}-{display_api.huella_vistos(conn)}'
                         + (f'-p{pendientes}' if pendientes else ''))
        return f'dv{dv}-lr{lr}-ir{ir}{marca}'


def crear(almacen: Almacen, reloj: Reloj) -> AnaliticaSqlite:
    return AnaliticaSqlite(almacen, reloj)
