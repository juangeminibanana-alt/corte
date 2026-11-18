"""Vista de lectura de la analítica sobre UNA conexión (una transacción de lectura por respuesta compuesta).

Port de spec/verificacion/analitica_ref.Analitica (03 §5) con las reglas de 01 v1.1 que v05 comparó contra ux_reglas.py:
grupo y etapa (vista v_muestras), pendiente, prioridad y razones (§2.6), tarjeta de video (§4.3), salud con nombre (§2.7),
plantilla sugerida (§4.8), precio ≈ y comisión por venta mínima (§6.0). Cambios de la rev. 3.1:
- imágenes con la regla C45 (`ResolutorImagenes`, SQL sobre `imagenes` en la misma transacción), nunca sha1(url);
- Las portadas de video salen exclusivamente de su propia clave `v:<content_id>`; un producto asociado nunca
  sustituye a la portada del video. La miniatura heredada también apunta a esa misma imagen real.
- objetos locales con las claves exactas del contrato (creatorhub.local.serial) y cohorte COALESCE(plan, muestra);
- nombre corto del usuario (PlanVideo.nombre_corto) gana sobre el calculado (01 §6.0 regla 5).
Rev. 4 (15/11): `producto_detalle` agrega `extendido` (ProductoExtendido del contrato: galería de vitrina, precios de la
vitrina, elegibilidad de muestra, solicitudes recuperadas, planes dirigidos, comisión real por tasa, parecidos y origen
de cada venta), armado en la MISMA transacción de lectura que el resto de la ficha.
Rev. 5 (15/11): métricas de la Display API (analitica/display.py) — FilaVideo y VideoDeProducto agregan vistas, likes,
comentarios, compartidos, portada '/img/v/…' y conversión por 1,000 vistas; el detalle de video, `tendencia`; el tablero,
`perfil_tiktok`. Todo opcional: ausente si nunca se trajo nada de la Display API, null si el video no está en ella.
Rev. 6 (18/11): orders/trace/search se retiró; `origen_ventas` es un histórico cerrado con procedencia y periodo, y
`origen_ventas_aviso` siempre va en null.

Todo se carga de forma perezosa: una lectura simple (p. ej. /api/ordenes) no toca las vistas de muestras.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import sqlite3
import urllib.parse
from decimal import ROUND_HALF_UP, Decimal
from functools import cached_property
from typing import Any, Iterable, Mapping

from .. import comun
from ..local import serial
from . import display as display_api
from .actualidad import resumen_actualidad
from . import filtros as F
from . import reglas as R
from .display import DatosDisplay as DisplayDatos
from .imagenes import ResolutorImagenes

Json = dict[str, Any]
_MAX_FECHA = dt.date.max

# ------------------------------------------------------------------ rev. 4: textos de la ficha completa de producto
MAX_GALERIA = 12                        # = imagenes.claves.MAX_GALERIA (fotos de la galería de vitrina por producto)
AGOTADO: frozenset[str] = frozenset({'SOLD_OUT', 'OUT_OF_STOCK'})
TEXTO_MOTIVO_SKU: dict[str, str] = {
    'IS_PREORDER': 'Es preventa: no tiene muestra gratis', 'IS_GIFT': 'Es un regalo: no tiene muestra gratis',
    'OUT_OF_STOCK': 'Agotado', 'EXCEED_CB_PRICE_THRESHOLD': 'Su precio pasa el límite para pedir muestra',
    'ALREADY_APPLYED': 'Ya pediste esta variante', 'UNKNOWN': 'No disponible como muestra'}
TEXTO_TIPO_SOLICITUD: dict[str, str] = {'FREE_SAMPLE': 'Muestra gratis', 'SAMPLE_COUPON': 'Cupón de muestra'}
TEXTO_CUMPLIMIENTO: dict[str, str] = {
    'PENDING': 'Por publicar', 'ONGOING': 'Tu video está en revisión', 'SUCCEED': 'Video entregado',
    'REPEATED': 'Video entregado', 'OVERDUE': 'Venció el plazo para publicar', 'FAILED': 'TikTok no aceptó el video',
    'SUSPEND': 'Plazo en pausa', 'CANCELLED': 'Cancelada', 'EXEMPTED': 'Exenta: no tienes que publicar'}
TEXTO_PLAN_DIRIGIDO: dict[str, str] = {'LIVE': 'Activo', 'EXPIRED': 'Vencido', 'DELETED': 'Eliminado', 'ENDED': 'Terminado'}
TEXTO_TIPO_CONTENIDO: dict[str, str] = {
    'VIDEO': 'Video', 'LIVE': 'En vivo', 'SHOP': 'Tienda', 'PRE_LIVE': 'Antes del en vivo',
    'PROMOTION_PAGE': 'Página de promoción', 'LINKSHARE': 'Enlace compartido'}
TEXTO_TIPO_ENLACE: dict[str, str] = {'GENERAL': 'Enlace general', 'SPECIFIC': 'Enlace para un publicador'}
FUENTE_ORIGEN_HISTORICO = 'orders_trace_search_202505_retirada'   # OrigenVentas.fuente (contrato rev. 6)
FUENTE_ORIGEN_ACTUAL = 'orders_search_202410'                     # OrigenVentasActual.fuente (contrato rev. 7)
# Un pedido que ya está en el histórico cerrado (orden_trazas) se queda solo ahí: nunca cuenta en los dos bloques.
_FUERA_DEL_HISTORICO = 'l.order_id NOT IN (SELECT order_id FROM orden_trazas)'


def texto_elegibilidad(puede: bool | None, estado: str | None, limite: bool | None) -> str:
    """Frase de samples/labels para la ficha (status: UNKNOWN | TO_APPLY | ONGOING | COMPLETE)."""
    if estado == 'ONGOING':
        return 'Ya la pediste; sigue en proceso'
    if estado == 'COMPLETE':
        return 'Ya la pediste y se completó'
    if limite:
        return 'Llegaste al límite de solicitudes de muestra'
    if puede is True:
        return 'Puedes pedir muestra'
    if puede is False:
        return 'Por ahora no puedes pedir muestra'
    return 'TikTok no dio este dato'


def _redondear(x: float) -> int:
    """ROUND de SQLite (mitad hacia arriba en positivos), no el redondeo bancario de Python."""
    return int(Decimal(str(x)).quantize(Decimal(1), ROUND_HALF_UP))


class Vista:
    def __init__(self, conn: sqlite3.Connection, ahora: int) -> None:
        self.conn = conn
        self.ahora = int(ahora)
        self.hoy = R.hoy_local(self.ahora)
        self._com: dict[tuple[str | None, int | None], int] = {}
        self._videos_cache: dict[tuple[Any, Any], list[Json]] = {}
        self._productos_cache: dict[tuple[Any, Any], list[Json]] = {}
        self._periodo_cache: dict[tuple[Any, Any], tuple[int, dict[str, int], dict[str, set[str]]]] = {}
        self._tarjeta: dict[str, str | None] = {}
        self._salud: dict[str, str] = {}

    # ================================================================== utilidades SQL
    def filas(self, sql: str, params: Iterable[Any] = ()) -> list[Json]:
        return serial.filas(self.conn, sql, params)

    def fila(self, sql: str, params: Iterable[Any] = ()) -> Json | None:
        return serial.fila(self.conn, sql, params)

    # ================================================================== carga perezosa
    @cached_property
    def img(self) -> ResolutorImagenes:
        return ResolutorImagenes(self.conn)

    @cached_property
    def meta(self) -> dict[str, str]:
        return {f['clave']: f['valor'] for f in self.filas('SELECT clave, valor FROM meta')}

    def _meta_int(self, clave: str) -> int:
        try:
            return int(self.meta.get(clave, 0))
        except (TypeError, ValueError):
            return 0

    @property
    def data_version(self) -> int:
        return self._meta_int('data_version')

    @property
    def local_rev(self) -> int:
        return self._meta_int('local_rev')

    @property
    def img_rev(self) -> int:
        return self._meta_int('img_rev')

    @cached_property
    def username(self) -> str | None:
        f = self.fila('SELECT username FROM cuenta WHERE id = 1')
        return f['username'] if f and f['username'] else None

    def enlace_video(self, content_id: str) -> str:
        if self.username:
            return f'https://www.tiktok.com/@{self.username}/video/{content_id}'
        return f'https://www.tiktok.com/video/{content_id}'

    @cached_property
    def L(self) -> list[Json]:
        # Mismo orden de lectura que analitica_ref (sin ORDER BY): de él dependen tienda/título de la fila de producto.
        lineas = self.filas('SELECT * FROM v_lineas')
        for r in lineas:
            r['_d'] = dt.date.fromisoformat(r['fecha'])
        return lineas

    @cached_property
    def L_producto(self) -> dict[str, list[Json]]:
        d: dict[str, list[Json]] = collections.defaultdict(list)
        for r in self.L:
            d[r['product_id']].append(r)
        return d

    @cached_property
    def L_tienda(self) -> dict[str | None, list[Json]]:
        d: dict[str | None, list[Json]] = collections.defaultdict(list)
        for r in self.L:
            d[r['tienda_key']].append(r)
        return d

    @cached_property
    def primera_fecha(self) -> dt.date | None:
        return min((r['_d'] for r in self.L), default=None)

    @cached_property
    def M(self) -> list[Json]:
        ms = self.filas('SELECT * FROM v_muestras ORDER BY application_id')
        for m in ms:
            m['pistas'] = set(json.loads(m['pistas_json'] or '[]'))
            m['sol_d'] = comun.ts_local(m['solicitada_at']).date() if m['solicitada_at'] else None
            m['descartadas'] = set(json.loads(m['sugerencias_descartadas_json'] or '[]'))
        return ms

    @cached_property
    def por_id(self) -> dict[str, Json]:
        return {m['application_id']: m for m in self.M}

    @cached_property
    def M_tienda(self) -> dict[str | None, list[Json]]:
        d: dict[str | None, list[Json]] = collections.defaultdict(list)
        for m in self.M:
            d[m['tienda_key']].append(m)
        return d

    @cached_property
    def S(self) -> dict[str, Json]:
        return {r['tienda_key']: r for r in self.filas('SELECT * FROM v_salud_tiendas')}

    @cached_property
    def avisos(self) -> list[Json]:
        return serial.leer_avisos(self.conn)

    @cached_property
    def avisos_por_muestra(self) -> dict[str, list[Json]]:
        d: dict[str, list[Json]] = collections.defaultdict(list)
        for a in self.avisos:
            for aid in dict.fromkeys(list(a['solicitud_ids']) + list(a['compromisos'])):
                d[aid].append(a)
        return d

    @cached_property
    def vitrina_conocida(self) -> bool:
        return self.fila("SELECT 1 AS x FROM sync_pasos WHERE paso = 'vitrina' AND estado = 'ok' LIMIT 1") is not None

    @cached_property
    def en_vitrina(self) -> set[str]:
        return {f['product_id'] for f in self.filas('SELECT product_id FROM vitrina')}

    @cached_property
    def productos_tabla(self) -> dict[str, Json]:
        return {f['product_id']: f for f in self.filas('SELECT * FROM productos')}

    @cached_property
    def portadas(self) -> dict[str, str | None]:
        return {f['content_id']: f['portada_product_id'] for f in self.filas('SELECT content_id, portada_product_id FROM videos')}

    @cached_property
    def titulo_por_lineas(self) -> dict[str, str | None]:
        """product_name de la línea más reciente de cada producto (respaldo del título)."""
        sql = """SELECT product_id, producto_nombre FROM (
                   SELECT l.product_id, l.producto_nombre,
                          ROW_NUMBER() OVER (PARTITION BY l.product_id ORDER BY o.creada_at DESC, l.order_id DESC, l.linea_n)
                            AS rn
                   FROM orden_lineas l JOIN ordenes o USING (order_id)) WHERE rn = 1"""
        return {f['product_id']: f['producto_nombre'] for f in self.filas(sql)}

    @cached_property
    def nombres_propios(self) -> dict[str, str]:
        """PlanVideo.nombre_corto que escribió el usuario, por application_id (01 §6.0 regla 5)."""
        return {f['application_id']: f['nombre_corto'] for f in self.filas(
            'SELECT application_id, nombre_corto FROM plan_videos WHERE eliminado = 0 AND application_id IS NOT NULL '
            'AND nombre_corto IS NOT NULL AND nombre_corto <> \'\'')}

    @cached_property
    def planes(self) -> list[Json]:
        return serial.leer_planes(self.conn)

    @cached_property
    def notas(self) -> list[Json]:
        return serial.leer_notas(self.conn)

    @cached_property
    def recordatorios(self) -> list[Json]:
        return serial.leer_recordatorios(self.conn)

    @cached_property
    def plantillas(self) -> list[Json]:
        return serial.leer_plantillas(self.conn)

    @cached_property
    def preferencias(self) -> Json:
        return serial.leer_preferencias(self.conn)

    @cached_property
    def ultima_sync_ok(self) -> int | None:
        f = self.fila("SELECT MAX(sync_id) AS s FROM sync_ejecuciones WHERE estado = 'ok'")
        return f['s'] if f else None

    @cached_property
    def conexion_guardada(self) -> Json | None:
        return self.fila('SELECT estado, refresh_expira_at FROM auth_estado WHERE id = 1')

    # ================================================================== ventas
    def desde(self, n: int) -> dt.date:
        """Primer día de 'últimos n días' = [hoy − (n − 1), hoy] (01 §6.0)."""
        return self.hoy - dt.timedelta(days=n - 1)

    def lineas(self, desde: dt.date | None = None, hasta: dt.date | None = None,
               base: list[Json] | None = None) -> list[Json]:
        fuente = self.L if base is None else base
        if desde is None and hasta is None:
            return fuente
        return [r for r in fuente if (desde is None or r['_d'] >= desde) and (hasta is None or r['_d'] <= hasta)]

    def comision(self, tk: str | None = None, dias: int | None = None) -> int:
        """Σ comisión estimada de líneas VÁLIDAS (de una tienda o de todas) en los últimos `dias` (None = todo)."""
        clave = (tk, dias)
        if clave not in self._com:
            d0 = self.desde(dias) if dias else dt.date.min
            fuente = self.L if tk is None else self.L_tienda.get(tk, [])
            self._com[clave] = sum(r['com_estimada_centavos'] for r in fuente if r['valida'] and d0 <= r['_d'] <= self.hoy)
        return self._com[clave]

    def es_socio(self, tk: str | None) -> bool:
        if not tk:
            return False
        c90, t90 = self.comision(tk, 90), self.comision(None, 90)
        return c90 >= R.UMBRAL_SOCIO_CENTAVOS or (t90 > 0 and c90 / t90 >= R.UMBRAL_SOCIO_PARTICIPACION)

    def kpis(self, desde: dt.date | None, hasta: dt.date | None) -> Json:
        L = self.lineas(desde, hasta)
        val = [r for r in L if r['valida']]
        pedidos = {r['order_id'] for r in L}
        reemb = {r['order_id'] for r in L if r['estado'] == 'REFUNDED'}
        validos = {r['order_id'] for r in val}
        ventas = sum(r['ventas_linea_centavos'] for r in val)
        base = sum(r['base_centavos'] for r in val)
        total = sum(r['comision_centavos'] for r in L)
        return {
            'pedidos': len(pedidos), 'pedidos_reembolsados': len(reemb), 'pedidos_validos': len(validos),
            'tasa_reembolso': round(len(reemb) / len(pedidos), 4) if pedidos else 0,
            'unidades': sum(r['unidades_netas'] for r in val), 'ventas_centavos': ventas,
            'comision_total_centavos': total,
            'comision_estimada_centavos': sum(r['com_estimada_centavos'] for r in val),
            'comision_liquidada_centavos': sum(r['com_real_centavos'] for r in L if r['estado'] == 'SETTLED'),
            'comision_por_liquidar_centavos': sum(r['com_estimada_centavos'] for r in L
                                                  if r['estado'] in ('To-SETTLE', 'AWAITING PAYMENT')),
            'comision_retenida_centavos': sum(r['com_estimada_centavos'] for r in L if r['estado'] == 'FROZEN'),
            'comision_perdida_reembolsos_centavos': sum(r['com_estimada_centavos'] for r in L if r['estado'] == 'REFUNDED'),
            'ticket_promedio_centavos': round(ventas / len(validos)) if validos else None,
            'tasa_comision_efectiva': round(total / base, 4) if base else None,
            'videos_con_venta': len({r['content_id'] for r in val if r['tipo_contenido'] == 'VIDEO' and r['content_id']}),
            'tiendas_con_venta': len({r['tienda_key'] for r in val if r['tienda_key']}),
            'productos_con_venta': len({r['product_id'] for r in val}),
        }

    @staticmethod
    def serie_de(lineas: list[Json], granularidad: str) -> list[Json]:
        col = {'mes': 'mes', 'semana': 'semana', 'dia': 'fecha'}[granularidad]
        g: dict[str, list[Json]] = collections.defaultdict(list)
        for r in lineas:
            g[r[col]].append(r)
        out = []
        for clave in sorted(g):
            L = g[clave]
            val = [r for r in L if r['valida']]
            out.append({'clave': clave, 'etiqueta': R.etiqueta_punto(granularidad, clave),
                        'pedidos': len({r['order_id'] for r in L}),
                        'pedidos_reembolsados': len({r['order_id'] for r in L if r['estado'] == 'REFUNDED'}),
                        'unidades': sum(r['unidades_netas'] for r in val),
                        'ventas_centavos': sum(r['ventas_linea_centavos'] for r in val),
                        'comision_estimada_centavos': sum(r['com_estimada_centavos'] for r in val),
                        'comision_liquidada_centavos': sum(r['com_real_centavos'] for r in L if r['estado'] == 'SETTLED')})
        return out

    def serie(self, granularidad: str, desde: dt.date | None, hasta: dt.date | None) -> list[Json]:
        return self.serie_de(self.lineas(desde, hasta), granularidad)

    # ================================================================== muestras: avisos y promesas (01 §2.5)
    def avisos_de(self, aid: str) -> list[Json]:
        return self.avisos_por_muestra.get(aid, [])

    def promesa(self, aid: str) -> str | None:
        enviados = [a for a in self.avisos_de(aid) if a['marcado_enviado_at'] and not a['quitado_at'] and aid in a['compromisos']]
        return max(enviados, key=lambda a: a['marcado_enviado_at'])['compromisos'][aid] if enviados else None

    def promesa_vencida(self, m: Json) -> bool:
        p = self.promesa(m['application_id'])
        return bool(p) and self.hoy > dt.date.fromisoformat(p) and m['etapa'] != 'publicada'

    def avisado(self, aid: str) -> bool:
        return any(a['marcado_enviado_at'] and not a['quitado_at'] for a in self.avisos_de(aid))

    # ================================================================== videos, prioridad, razones (§2.6, §4.3)
    def videos_producto(self, pid: str) -> dict[str, list[Json]]:
        """{content_id: [líneas]} de VIDEO que vendieron el producto (todas las líneas, como M17), sin pedidos de muestra."""
        v: dict[str, list[Json]] = collections.defaultdict(list)
        for r in self.L_producto.get(pid, []):
            if r['tipo_contenido'] == 'VIDEO' and r['content_id'] and not r['es_pedido_muestra']:
                v[r['content_id']].append(r)
        return v

    def tarjeta_video(self, m: Json) -> str | None:
        aid = m['application_id']
        if aid in self._tarjeta:
            return self._tarjeta[aid]
        vids = self.videos_producto(m['product_id'])
        ocupados = {x['plan_content_id'] for x in self.M if x['plan_content_id'] and x['application_id'] != aid
                    and (not m['main_order_id'] or x['main_order_id'] != m['main_order_id'])}
        vids = {k: v for k, v in vids.items() if k not in m['descartadas'] and k not in ocupados}
        r: str | None
        if not vids:
            r = None
        elif not m['sol_d']:
            r = 'sin_fecha'
        else:
            primeras = [min(x['_d'] for x in rs) for rs in vids.values()]
            if m['grupo'] in ('por_vencer', 'en_revision'):
                posible = any(f >= m['sol_d'] for f in primeras)
            else:
                posible = any(f >= m['sol_d'] + dt.timedelta(days=R.DIAS_POSIBLE_VIDEO) for f in primeras)
            r = 'posible_video' if posible else ('video_previo' if m['grupo'] == 'vencida' else None)
        self._tarjeta[aid] = r
        return r

    def prioridad(self, m: Json) -> str:
        if m['grupo'] == 'por_vencer':
            return 'urgente'
        if not m['promocionable']:
            return 'no_se_puede_etiquetar'
        us = m['unidades_vendidas'] or 0
        if self.comision(m['tienda_key'], 180) > 0 or us >= 10000:
            return 'alta'
        if us >= 1000 or (m['comision_por_venta_centavos'] or 0) >= R.UMBRAL_BUENA_COMISION:
            return 'media'
        return 'baja'

    def razones(self, m: Json) -> list[str]:
        out = []
        if self.promesa(m['application_id']):
            out.append('promesa')
        if self.tarjeta_video(m) == 'posible_video':
            out.append('posible_video')
        if self.comision(m['tienda_key'], 180) > 0:
            out.append('ya_vendes_con_esta_tienda')
        if self.videos_producto(m['product_id']):
            out.append('ya_lo_vendes')
        if (m['comision_por_venta_centavos'] or 0) >= R.UMBRAL_BUENA_COMISION:
            out.append('buena_comision')
        us = m['unidades_vendidas'] or 0
        if us >= 10000:
            out.append('muy_vendido')
        elif us >= 1000:
            out.append('se_vende_bien')
        if m['main_order_id'] and sum(1 for x in self.M if x['main_order_id'] == m['main_order_id']) > 1:
            out.append('paquete')
        if m['suspension_s']:
            out.append('tuvo_pausa')
        return out

    def pendientes(self) -> list[Json]:
        return [m for m in self.M if m['pendiente']]

    def cola(self) -> list[Json]:
        def clave(m: Json) -> tuple:
            nivel = self.prioridad(m)
            return (0 if m['fijada'] else 1, R.NIVELES.index(nivel),
                    (m['fecha_limite_at'] or 2 ** 40) if nivel == 'urgente' else 0,
                    -self.comision(m['tienda_key'], 180), m['sol_d'] or dt.date.min, m['application_id'])
        return sorted(self.pendientes(), key=clave)

    @cached_property
    def posiciones(self) -> dict[str, int]:
        return {m['application_id']: i + 1 for i, m in enumerate(self.cola())}

    # ================================================================== salud con nombre (§2.7)
    def salud(self, tk: str) -> str:
        if tk in self._salud:
            return self._salud[tk]
        s = self.S.get(tk) or {}
        socio = self.es_socio(tk)
        prom_venc = sum(1 for m in self.M_tienda.get(tk, []) if m['pendiente'] and self.promesa_vencida(m))
        urgentes = (s.get('pendientes_por_planear') or 0) > 0 or prom_venc > 0
        if socio and urgentes:
            r = 'socio_con_pendientes'
        elif urgentes:
            r = 'con_pendientes'
        elif s.get('pendientes'):
            r = 'con_plan'
        elif socio:
            r = 'socio'
        elif (s.get('entregadas') or 0) + (s.get('exentas') or 0) + (s.get('publicadas') or 0) > 0:
            r = 'al_dia'
        elif not s.get('recibidas') and (s.get('pedidos_validos') or 0) > 0:
            r = 'vende_contigo'
        elif s.get('solicitudes'):
            r = 'solo_solicitudes'
        else:
            r = 'solo_reembolsos'
        self._salud[tk] = r
        return r

    def salud_porque(self, tk: str, salud: str) -> str:
        s = self.S[tk]
        n = s['pendientes']
        t90 = self.comision(None, 90)
        pct = round(100 * self.comision(tk, 90) / t90) if t90 else 0
        if salud in ('socio_con_pendientes', 'con_pendientes'):
            base = f"{n} {R.plural(n, 'muestra')} sin video"
            if self.es_socio(tk):
                return f'{base} · {pct} % de tu comisión en 90 días'
            return f"{base} · ≈ ${round(s['valor_debido_centavos'] / 100):,} en producto recibido"
        if salud == 'con_plan':
            fechas = sorted(m['fecha_plan'] for m in self.M_tienda.get(tk, []) if m['pendiente'] and m['fecha_plan'])
            return f'Todo planeado · siguiente video el {R.fecha_corta(fechas[0])}' if fechas else 'Todo planeado'
        if salud == 'socio':
            ultima = f" · última venta {R.fecha_corta(comun.fecha_local(s['ultima_venta_at']))}" if s['ultima_venta_at'] else ''
            return f'{pct} % de tu comisión en 90 días{ultima}'
        if salud == 'al_dia':
            k = s['entregadas'] + s['exentas'] + s['publicadas']
            return f"Cumpliste con {k} {R.plural(k, 'muestra')}"
        if salud == 'vende_contigo':
            return f'${round(self.comision(tk) / 100):,} de comisión · sin muestras'
        if salud == 'solo_solicitudes':
            return 'No te ha enviado muestras'
        k = s['pedidos']
        return '1 pedido, reembolsado' if k == 1 else f'{k} pedidos, todos reembolsados'

    # ================================================================== vistas de muestra
    def producto(self, m: Json) -> Json:
        pid = m['product_id']
        titulo = m['titulo'] or self.titulo_por_lineas.get(pid)
        return {'product_id': pid, 'titulo': titulo,
                'titulo_corto': R.nombre_corto(titulo, self.nombres_propios.get(m['application_id'])),
                'imagen': self.img.producto(pid), 'enlace': m['enlace'],
                'precio_min_centavos': m['precio_min_centavos'], 'precio_max_centavos': m['precio_max_centavos'],
                'precio_venta_min_centavos': m['precio_venta_min_centavos'],
                'precio_venta_max_centavos': m['precio_venta_max_centavos'],
                'precio_fuente': m['precio_fuente'], 'comision_bp': m['comision_bp'],
                'comision_por_venta_centavos': m['comision_por_venta_centavos'],
                'comision_por_venta_max_centavos': m['comision_por_venta_max_centavos'],
                'unidades_vendidas_global': m['unidades_vendidas'],
                'en_colaboracion_abierta': bool(m['en_colaboracion_abierta']) if m['en_colaboracion_abierta'] is not None else False,
                'en_vitrina': bool(m['en_vitrina']) if self.vitrina_conocida else None, 'categoria': m['categoria']}

    def resumen_avisos(self, m: Json) -> Json:
        aid = m['application_id']
        av = self.avisos_de(aid)
        copiados = [a for a in av if a['copiado_at'] and not a['marcado_enviado_at'] and not a['quitado_at']
                    and self.ahora - a['copiado_at'] < 7 * 86400]
        enviados = [a['marcado_enviado_at'] for a in av if a['marcado_enviado_at'] and not a['quitado_at']]
        cs = max(copiados, key=lambda a: a['copiado_at']) if copiados else None
        return {'promesa': self.promesa(aid), 'promesa_vencida': self.promesa_vencida(m),
                'copiado_sin_confirmar': {'aviso_id': cs['id'], 'copiado_at': cs['copiado_at']} if cs else None,
                'ultimo_enviado_at': max(enviados) if enviados else None}

    def ventas_producto_muestra(self, pid: str) -> list[Json]:
        return [r for r in self.L_producto.get(pid, []) if r['valida'] and not r['es_pedido_muestra']]

    def muestra_vista(self, m: Json) -> Json:
        tk = m['tienda_key'] or ''
        en_cola = bool(m['pendiente'])
        vids = self.videos_producto(m['product_id'])
        ventas = self.ventas_producto_muestra(m['product_id'])
        return {
            'application_id': m['application_id'], 'grupo': m['grupo'], 'motivo': R.MOTIVO_DE_SUBESTADO[m['subestado']],
            'clase': m['clase'], 'subestado': m['subestado'], 'etiqueta': R.ETIQUETA[m['subestado']],
            'estado_api': m['estado_api'], 'cumplimiento': m['cumplimiento'], 'tipo': m['tipo'], 'variante': m['variante'] or None,
            'solicitada_at': m['solicitada_at'], 'fecha_limite_at': m['fecha_limite_at'],
            'dias_restantes': R.dias_restantes(m['fecha_limite_at'], self.ahora), 'recibida': bool(m['recibida']),
            'filtros_que_la_devolvieron': sorted(m['pistas']), 'producto': self.producto(m),
            'tienda': {'tienda_key': tk, 'nombre': m['tienda_nombre'] or '', 'shop_id': m['shop_id'],
                       'salud': self.salud(tk) if tk else 'solo_solicitudes', 'es_socio': self.es_socio(tk) if tk else False},
            'prioridad': self.prioridad(m) if en_cola else None,
            'razones': self.razones(m) if en_cola else ([] if not self.promesa(m['application_id']) else ['promesa']),
            'posicion_cola': self.posiciones.get(m['application_id']),
            'tarjeta_video': self.tarjeta_video(m) if en_cola else None,
            'avance': {'plan_id': m['plan_id'], 'etapa': m['etapa'], 'fecha_planeada': m['fecha_plan'],
                       'programada_para_at': m['programada_para_at'], 'fecha_publicada': m['fecha_publicada'],
                       'content_id': m['plan_content_id'], 'vinculo_origen': m['vinculo_origen'], 'fijada': bool(m['fijada']),
                       'rev': m['plan_rev']},
            'avisos': self.resumen_avisos(m),
            'ventas_producto': {'pedidos_validos': len({r['order_id'] for r in ventas}),
                                'comision_estimada_centavos': sum(r['com_estimada_centavos'] for r in ventas),
                                'videos': len(vids)},
        }

    def conteos(self) -> tuple[Json, Json]:
        conteos = {k: 0 for k in R.CLASES}
        por_grupo = {g: 0 for g in R.GRUPOS}
        for m in self.M:
            conteos[m['clase']] += 1
            por_grupo[m['grupo']] += 1
        return conteos, por_grupo

    def muestras_filtradas(self, f: F.FiltrosMuestras) -> list[Json]:
        filas = [m for m in self.M
                 if (not f.grupos or m['grupo'] in f.grupos) and (not f.clases or m['clase'] in f.clases)
                 and (f.tienda is None or m['tienda_key'] == f.tienda)
                 and (f.recibidas is None or bool(m['recibida']) == f.recibidas)]
        if f.q:
            q = f.q.casefold()
            def coincide(m: Json) -> bool:
                campos = (m['application_id'], m['product_id'], m['titulo'] or self.titulo_por_lineas.get(m['product_id']),
                          m['tienda_nombre'], m['variante'], self.nombres_propios.get(m['application_id']))
                return any(q in str(c).casefold() for c in campos if c)
            filas = [m for m in filas if coincide(m)]
        pos = self.posiciones
        sin_pos = 10 ** 6
        if f.orden == 'prioridad':
            filas.sort(key=lambda m: (pos.get(m['application_id'], sin_pos), m['application_id']))
        elif f.orden in ('solicitud_asc', 'solicitud_desc'):
            desc = f.orden == 'solicitud_desc'
            filas.sort(key=lambda m: m['application_id'])
            filas.sort(key=lambda m: m['solicitada_at_efectiva'] or 0, reverse=desc)
        elif f.orden == 'valor_desc':
            filas.sort(key=lambda m: (-(m['valor_muestra_centavos'] or 0), m['application_id']))
        else:  # 'tienda'
            filas.sort(key=lambda m: ((m['tienda_nombre'] or '').casefold(), pos.get(m['application_id'], sin_pos),
                                      m['application_id']))
        return filas

    def plantilla_sugerida(self, m: Json) -> str:
        """01 §4.8 con la precedencia de 03 §5.10."""
        if self.promesa_vencida(m):
            return 'nueva_fecha'
        if m['etapa'] == 'publicada':
            return 'ya_publique'
        if m['etapa'] == 'no_se_puede':
            return R.PLANTILLA_NO_SE_PUEDE.get(m['motivo_no_se_puede'], 'disculpa_sin_fecha')
        if m['pendiente'] and not m['promocionable']:
            return 'producto_no_disponible'
        if m['pendiente'] and self.tarjeta_video(m) == 'video_previo':
            return 'ya_tengo_video'
        if m['grupo'] == 'por_vencer':
            return 'ya_la_recibi'
        if m['pendiente']:
            pend_tienda = (self.S.get(m['tienda_key']) or {}).get('pendientes') or 0
            return 'varias_muestras' if pend_tienda >= 2 else 'disculpa_y_fecha'
        if m['tienda_key'] and self.es_socio(m['tienda_key']):
            return 'gracias_por_las_ventas'
        return 'disculpa_y_fecha'

    # ================================================================== tiendas
    @cached_property
    def productos_por_tienda(self) -> dict[str | None, list[str]]:
        """product_id de cada tienda (tabla productos), del de más comisión estimada válida al de menos."""
        com: dict[str, int] = collections.defaultdict(int)
        for r in self.L:
            if r['valida']:
                com[r['product_id']] += r['com_estimada_centavos'] or 0
        d: dict[str | None, list[str]] = collections.defaultdict(list)
        for pid, f in self.productos_tabla.items():
            d[f['tienda_key']].append(pid)
        for lista in d.values():
            lista.sort(key=lambda p: (-com.get(p, 0), p))
        return d

    def imagen_tienda(self, tk: str) -> str | None:
        """Foto del producto con más comisión de la tienda (la API no da logotipos) que tenga imagen según C45."""
        for pid in self.productos_por_tienda.get(tk, []):
            u = self.img.producto(pid)
            if u:
                return u
        return None

    def _periodo(self, desde: dt.date | None, hasta: dt.date | None) -> tuple[int, dict[str, int], dict[str, set[str]]]:
        clave = (desde, hasta)
        if clave not in self._periodo_cache:
            tot = 0
            com: dict[str, int] = collections.defaultdict(int)
            ped: dict[str, set[str]] = collections.defaultdict(set)
            for r in self.lineas(desde, hasta):
                if r['valida']:
                    tot += r['com_estimada_centavos']
                    com[r['tienda_key']] += r['com_estimada_centavos']
                    ped[r['tienda_key']].add(r['order_id'])
            self._periodo_cache[clave] = (tot, com, ped)
        return self._periodo_cache[clave]

    def fila_tienda(self, tk: str, desde: dt.date | None = None, hasta: dt.date | None = None) -> Json:
        s = self.S[tk]
        salud = self.salud(tk)
        ms = self.M_tienda.get(tk, [])
        pend = [m for m in ms if m['pendiente']]
        promesas = [(m, self.promesa(m['application_id'])) for m in ms]
        tot_periodo, com_tiendas, ped_tiendas = self._periodo(desde, hasta)
        com_periodo = com_tiendas.get(tk, 0)
        t90 = self.comision(None, 90)
        return {
            'tienda_key': tk, 'nombre': s['nombre'], 'shop_id': s['shop_id'], 'imagen': self.imagen_tienda(tk),
            'salud': salud, 'salud_porque': self.salud_porque(tk, salud), 'es_socio': self.es_socio(tk),
            'por_avisar': any(not self.avisado(m['application_id']) for m in pend),
            'promesas': {'vigentes': sum(1 for m, p in promesas if p and m['etapa'] != 'publicada'
                                         and self.hoy <= dt.date.fromisoformat(p)),
                         'vencidas': sum(1 for m, p in promesas if p and self.promesa_vencida(m)),
                         'cumplidas': sum(1 for m, p in promesas if p and m['etapa'] == 'publicada' and m['fecha_publicada']
                                          and m['fecha_publicada'] <= p)},
            'muestras': {'recibidas': s['recibidas'], 'pendientes': s['pendientes'], 'entregadas': s['entregadas'],
                         'debidas': s['debidas'], 'debidas_con_plan': s['pendientes_con_plan'], 'exentas': s['exentas'],
                         'abiertas': s['abiertas'], 'canceladas': s['canceladas'], 'nunca_enviadas': s['nunca_enviadas'],
                         'sin_envio': s['sin_envio'], 'valor_debido_centavos': s['valor_debido_centavos'],
                         'valor_recibido_min_centavos': s['valor_recibido_min_centavos'],
                         'valor_recibido_max_centavos': s['valor_recibido_max_centavos']},
            'ventas': {'pedidos_validos': len(ped_tiendas.get(tk, ())), 'comision_estimada_centavos': com_periodo,
                       'participacion': round(com_periodo / tot_periodo, 4) if tot_periodo else 0,
                       'participacion_90d': round(self.comision(tk, 90) / t90, 4) if t90 else 0,
                       'comision_180d_centavos': self.comision(tk, 180), 'ultima_venta_at': s['ultima_venta_at']},
        }

    def tiendas(self, orden: str = 'atencion', desde: dt.date | None = None, hasta: dt.date | None = None) -> list[Json]:
        filas = [self.fila_tienda(tk, desde, hasta) for tk in self.S]
        claves = {'atencion': lambda f: (-f['promesas']['vencidas'], R.ORDEN_SALUD.index(f['salud']),
                                         -f['ventas']['comision_180d_centavos'], f['tienda_key']),
                  'comision': lambda f: (-f['ventas']['comision_estimada_centavos'], f['tienda_key']),
                  'deuda': lambda f: (-f['muestras']['pendientes'], -f['muestras']['valor_debido_centavos'], f['tienda_key']),
                  'nombre': lambda f: (f['nombre'].casefold(), f['tienda_key'])}
        return sorted(filas, key=claves[orden])

    def resolver_tienda(self, tk: str) -> str | None:
        if tk in self.S:
            return tk
        f = self.fila('SELECT tienda_key FROM tienda_alias WHERE alias = ?', (tk,))
        return f['tienda_key'] if f and f['tienda_key'] in self.S else None

    # ================================================================== resumen y alertas
    def conversion(self) -> Json:
        """Productos de muestras RECIBIDAS con ≥ 1 línea válida desde la solicitud efectiva (fecha local), sin pedidos de
        muestra; 'activados' = sin ventas válidas anteriores."""
        ref: dict[str, dt.date] = {}
        for m in self.M:
            if m['recibida']:
                f = comun.ts_local(m['solicitada_at_efectiva']).date()
                ref[m['product_id']] = min(ref.get(m['product_id'], _MAX_FECHA), f)
        con_venta = activados = 0
        for pid, f in ref.items():
            ls = self.ventas_producto_muestra(pid)
            if any(r['_d'] >= f for r in ls):
                con_venta += 1
                activados += not any(r['_d'] < f for r in ls)
        return {'productos_recibidos': len(ref), 'productos_con_venta': con_venta, 'productos_activados': activados}

    def resumen_muestras(self) -> Json:
        conteos, por_grupo = self.conteos()
        deb = [m for m in self.M if m['clase'] == 'debe_video']
        abiertas = [m for m in deb if m['deuda_estado'] not in ('saldada', 'no_se_puede')]
        rec = [m for m in self.M if m['recibida']]
        pend = self.pendientes()
        e, saldadas = conteos['entregada'], sum(1 for m in deb if m['saldada'])
        prox = min((m for m in self.M if m['fecha_limite_at'] and m['fecha_limite_at'] > self.ahora and m['pendiente']),
                   key=lambda m: m['fecha_limite_at'], default=None)
        return {'total': len(self.M), 'por_clase': conteos, 'por_grupo': por_grupo, 'recibidas': len(rec),
                'tiendas_recibidas': len({m['tienda_key'] for m in rec}),
                'debe_video': {'n': len(deb), 'tiendas': len({m['tienda_key'] for m in deb}),
                               'valor_min_centavos': sum(m['valor_muestra_centavos'] for m in abiertas),
                               'valor_max_centavos': sum(m['valor_muestra_max_centavos'] for m in abiertas),
                               'con_plan': sum(1 for m in abiertas if m['etapa'] != 'por_planear'), 'saldadas': saldadas},
                'pendientes': len(pend),
                'tiendas_por_avisar': len({m['tienda_key'] for m in pend if not self.avisado(m['application_id'])}),
                'promesas_vencidas': sum(1 for m in self.M if self.promesa_vencida(m)),
                'cumplimiento': round((e + saldadas) / (e + len(deb)), 4) if e + len(deb) else None,
                'proxima_fecha_limite': ({'application_id': prox['application_id'], 'fecha_limite_at': prox['fecha_limite_at']}
                                         if prox else None),
                'conversion': self.conversion()}

    def alertas(self, rm: Json, tiendas_periodo: list[Json], k: Json, conexion: Mapping[str, Any] | None) -> list[Json]:
        out: list[Json] = []
        n, pend, sald = rm['debe_video']['n'], rm['pendientes'], rm['debe_video']['saldadas']
        if pend:
            t = len({m['tienda_key'] for m in self.pendientes()})
            titulo = (f'Te faltan {pend} de {n}; ya publicaste {sald}' if sald else
                      f"Tienes {pend} {R.plural(pend, 'muestra')} sin video de {t} {R.plural(t, 'tienda')}")
            out.append({'id': 'pendientes', 'nivel': 'critica', 'titulo': titulo,
                        'texto': 'TikTok ya las marca como vencidas. Empieza por las de arriba y avísale a cada tienda cuándo publicarás.',
                        'accion': {'etiqueta': 'Ver pendientes', 'ruta': '/muestras'}})
        for f in tiendas_periodo:
            p = f['muestras']['pendientes']
            if p and f['ventas']['participacion'] >= R.UMBRAL_TIENDA_CLAVE:
                vnv = self.S[f['tienda_key']]['video_no_vinculado']
                extra = f' Ya tienes video de {vnv}: pídele que lo acepte.' if vnv else ''
                out.append({'id': f"tienda_clave:{f['tienda_key']}", 'nivel': 'critica',
                            'titulo': f"{f['nombre']} espera {p} {R.plural(p, 'video')}",
                            'texto': f"Es tu tienda más importante: te deja el {round(f['ventas']['participacion'] * 100)} % de tu comisión.{extra}",
                            'accion': {'etiqueta': 'Ver tienda', 'ruta': '/tiendas/' + urllib.parse.quote(f['tienda_key'], safe='')}})
        ult = self.ultima_sync_ok
        for m in self.pendientes():
            fl = m['fecha_limite_at']
            if fl and fl > self.ahora and ult is not None and m['cumplimiento_vista_en_sync'] == ult:
                dias = R.dias_restantes(fl, self.ahora)
                if dias is not None and dias <= 7:
                    cuando = 'hoy' if dias == 0 else 'mañana' if dias == 1 else f'en {dias} días'
                    titulo_p = R.nombre_corto(m['titulo'] or self.titulo_por_lineas.get(m['product_id']),
                                              self.nombres_propios.get(m['application_id']))
                    out.append({'id': f"limite:{m['application_id']}", 'nivel': 'critica' if dias <= 3 else 'aviso',
                                'titulo': f'Vence {cuando}: {titulo_p}',
                                'texto': 'Todavía cuenta para TikTok: publícalo antes de la fecha límite.',
                                'accion': {'etiqueta': 'Ver muestra', 'ruta': f"/muestras/m/{m['application_id']}"}})
        if rm['promesas_vencidas']:
            pv = rm['promesas_vencidas']
            out.append({'id': 'promesas_vencidas', 'nivel': 'critica',
                        'titulo': f"{pv} {R.plural(pv, 'promesa vencida', 'promesas vencidas')}",
                        'texto': 'Le dijiste a la tienda una fecha que ya pasó. Avísale la nueva fecha.',
                        'accion': {'etiqueta': 'Avisar a mis tiendas', 'ruta': '/muestras/avisos'}})
        if conexion and conexion.get('estado') == 'reautorizar':
            out.append({'id': 'conexion', 'nivel': 'critica', 'titulo': 'Vuelve a conectar TikTok',
                        'texto': 'TikTok ya no acepta la conexión de esta app.',
                        'accion': {'etiqueta': 'Conectar', 'ruta': '/ajustes/tiktok'}})
        elif conexion and conexion.get('refresh_expira_at') and conexion['refresh_expira_at'] - self.ahora < 7 * 86400:
            out.append({'id': 'conexion', 'nivel': 'aviso', 'titulo': 'Tu conexión con TikTok vence pronto',
                        'texto': 'Vuelve a conectar tu cuenta para que no se detengan las actualizaciones.',
                        'accion': {'etiqueta': 'Conectar', 'ruta': '/ajustes/tiktok'}})
        # reembolsos: solo periodos MADUROS (pedidos de hace ≥ 30 días; los To-SETTLE tardan hasta 56 días en definirse)
        fin = self.hoy - dt.timedelta(days=30)
        a = self.kpis(fin - dt.timedelta(days=29), fin)
        b = self.kpis(fin - dt.timedelta(days=59), fin - dt.timedelta(days=30))
        if a['pedidos'] and b['pedidos'] and a['tasa_reembolso'] - b['tasa_reembolso'] >= 0.05:
            out.append({'id': 'reembolsos', 'nivel': 'aviso', 'titulo': 'Subieron tus reembolsos',
                        'texto': f"{round(a['tasa_reembolso'] * 100)} % de los pedidos de hace 1 a 2 meses se reembolsaron "
                                 f"(antes {round(b['tasa_reembolso'] * 100)} %).",
                        'accion': {'etiqueta': 'Ver productos', 'ruta': '/productos'}})
        if k['comision_por_liquidar_centavos']:
            out.append({'id': 'por_liquidar', 'nivel': 'info',
                        'titulo': f"{comun.fmt_mxn(k['comision_por_liquidar_centavos'])} por liquidar",
                        'texto': 'Comisión de pedidos que TikTok todavía no te paga.', 'accion': None})
        sin_estado = len({r['order_id'] for r in self.L if r['estado'] == 'UNSPECIFIED'})
        if sin_estado:
            out.append({'id': 'sin_estado', 'nivel': 'aviso',
                        'titulo': f"{sin_estado} {R.plural(sin_estado, 'pedido')} sin estado",
                        'texto': 'TikTok no informa su estado; no se suman a tu comisión hasta que lo haga.',
                        'accion': {'etiqueta': 'Ver ventas', 'ruta': '/ventas'}})
        return out

    # ================================================================== videos y productos
    def miniatura_video(self, content_id: str) -> tuple[str | None, str | None]:
        """Identidad exacta del video. Sin portada conocida, ninguna foto de producto ocupa su lugar."""
        return self.img.url('v', content_id), None

    def videos_todos(self, desde: dt.date | None, hasta: dt.date | None) -> list[Json]:
        clave = (desde, hasta)
        if clave in self._videos_cache:
            return self._videos_cache[clave]
        periodo = self.lineas(desde, hasta)
        L = [r for r in periodo if r['tipo_contenido'] == 'VIDEO' and r['content_id']]
        tot = sum(r['com_estimada_centavos'] for r in periodo if r['valida'])
        g: dict[str, list[Json]] = collections.defaultdict(list)
        for r in L:
            g[r['content_id']].append(r)
        vinculadas: dict[str, list[str]] = collections.defaultdict(list)
        for m in self.M:
            if m['plan_content_id']:
                vinculadas[m['plan_content_id']].append(m['application_id'])
        filas = []
        self.img.cargar(f'v:{cid}' for cid in g)
        for cid, rs in g.items():
            val = [r for r in rs if r['valida']]
            com = sum(r['com_estimada_centavos'] for r in val)
            por_tienda: collections.Counter[str] = collections.Counter()
            for r in val:
                por_tienda[r['tienda_nombre']] += r['com_estimada_centavos']
            ped, vped = {r['order_id'] for r in rs}, {r['order_id'] for r in val}
            miniatura, origen = self.miniatura_video(cid)
            filas.append({'content_id': cid, 'titulo': None, 'miniatura': miniatura, 'miniatura_origen': origen,
                          'portada': miniatura,
                          'producto_principal_id': self.portadas.get(cid),
                          'enlace': self.enlace_video(cid),
                          'pedidos': len(ped), 'pedidos_validos': len(vped), 'unidades': sum(r['unidades_netas'] for r in val),
                          'ventas_centavos': sum(r['ventas_linea_centavos'] for r in val), 'comision_estimada_centavos': com,
                          'tasa_reembolso': round(1 - len(vped) / len(ped), 4) if ped else 0,
                          'participacion': round(com / tot, 4) if tot else 0,
                          'primera_venta': min(r['fecha'] for r in rs), 'ultima_venta': max(r['fecha'] for r in rs),
                          'productos': len({r['product_id'] for r in rs}),
                          'tienda_principal': por_tienda.most_common(1)[0][0] if por_tienda else None,
                          'muestras_vinculadas': sorted(vinculadas.get(cid, []))})
        filas.sort(key=lambda f: (-f['comision_estimada_centavos'], f['content_id']))
        self._agregar_display(filas, desde, hasta)            # rev. 5: solo si hay datos de la Display API
        self._videos_cache[clave] = filas
        return filas

    def videos(self, desde: dt.date | None, hasta: dt.date | None, limite: int = 50) -> tuple[list[Json], int]:
        filas = self.videos_todos(desde, hasta)
        return filas[:limite], len(filas)

    def productos_todos(self, desde: dt.date | None, hasta: dt.date | None) -> list[Json]:
        clave = (desde, hasta)
        if clave in self._productos_cache:
            return self._productos_cache[clave]
        g: dict[str, list[Json]] = collections.defaultdict(list)
        for r in self.lineas(desde, hasta):
            g[r['product_id']].append(r)
        mu_por_producto: dict[str, list[Json]] = collections.defaultdict(list)
        for m in self.M:
            mu_por_producto[m['product_id']].append(m)
        filas = [self.fila_producto(pid, rs, mu_por_producto.get(pid, [])) for pid, rs in g.items()]
        filas.sort(key=lambda f: (-f['comision_estimada_centavos'], f['product_id']))
        self._productos_cache[clave] = filas
        return filas

    def fila_producto(self, pid: str, rs: list[Json], mu: list[Json]) -> Json:
        val = [r for r in rs if r['valida']]
        p = self.productos_tabla.get(pid)
        titulo = (p['titulo'] if p and p['origen'] == 'api' else None) or rs[-1]['producto_nombre']
        ped, vped = {r['order_id'] for r in rs}, {r['order_id'] for r in val}
        bps = [r['comision_bp'] for r in rs if r['comision_bp'] is not None]
        return {'product_id': pid, 'titulo': titulo, 'titulo_corto': R.nombre_corto(titulo),
                'imagen': self.img.producto(pid),
                'tienda_key': rs[-1]['tienda_key'], 'tienda_nombre': rs[-1]['tienda_nombre'],
                'pedidos': len(ped), 'pedidos_validos': len(vped), 'unidades': sum(r['unidades_netas'] for r in val),
                'ventas_centavos': sum(r['ventas_linea_centavos'] for r in val),
                'comision_estimada_centavos': sum(r['com_estimada_centavos'] for r in val),
                'tasa_reembolso': round(1 - len(vped) / len(ped), 4) if ped else 0,
                'comision_bp': round(sum(bps) / len(bps)) if bps else None,
                'videos': len({r['content_id'] for r in rs if r['tipo_contenido'] == 'VIDEO' and r['content_id']}),
                'es_muestra': bool(mu),
                'clase_muestra': (min((m['clase'] for m in mu), key=lambda k: (k != 'debe_video', R.CLASES.index(k)))
                                  if mu else None),
                'con_ficha': bool(p and p['origen'] == 'api'),
                'en_vitrina': (pid in self.en_vitrina) if self.vitrina_conocida else None}

    def productos(self, desde: dt.date | None, hasta: dt.date | None, limite: int = 50) -> tuple[list[Json], int]:
        filas = self.productos_todos(desde, hasta)
        return filas[:limite], len(filas)

    def ficha_producto(self, pid: str) -> Json | None:
        """ProductoResumen de un producto con ficha (origen 'api'); el de su muestra si tiene una (mismas cifras que la
        tarjeta), si no, precio de venta ≈ por vitrina → commission.amount ÷ tasa → lista (01 §6.0)."""
        p = self.productos_tabla.get(pid)
        if not p or p['origen'] != 'api':
            return None
        mu = [m for m in self.M if m['product_id'] == pid]
        if mu:
            return self.producto(mu[0])
        # Misma cadena que v_muestras, sin la fuente 'variante' (sin SKU de muestra no hay precio pagado por variante).
        v = self.fila('SELECT precio_desc_min_centavos, precio_desc_max_centavos FROM vitrina WHERE product_id = ?', (pid,))
        bp = p['comision_bp']
        dmin = v['precio_desc_min_centavos'] if v else None
        dmax = v['precio_desc_max_centavos'] if v else None
        pcmin = comun.precio_venta_por_comision(p['comision_monto_min_centavos'], bp) if bp and bp > 0 else None
        pcmax = comun.precio_venta_por_comision(p['comision_monto_max_centavos'], bp) if bp and bp > 0 else None
        lmin, lmax = p['precio_min_centavos'], p['precio_max_centavos']
        if dmin is not None:
            fuente, vmin, vmax = 'vitrina', dmin, (dmax if dmax is not None else dmin)
        elif pcmin is not None:
            fuente, vmin, vmax = 'comision', pcmin, (pcmax if pcmax is not None else pcmin)
        elif lmin is not None:
            fuente, vmin, vmax = 'lista', lmin, (lmax if lmax is not None else lmin)
        else:
            fuente, vmin, vmax = None, None, None
        cmin = p['comision_monto_min_centavos']
        base_min = dmin if dmin is not None else lmin
        if cmin is None and bp is not None and base_min is not None:
            cmin = _redondear(base_min * bp / 10000)
        cmax = p['comision_monto_max_centavos'] if p['comision_monto_max_centavos'] is not None else p['comision_monto_min_centavos']
        base_max = dmax if dmax is not None else lmax
        if cmax is None and bp is not None and base_max is not None:
            cmax = _redondear(base_max * bp / 10000)
        return {'product_id': pid, 'titulo': p['titulo'], 'titulo_corto': R.nombre_corto(p['titulo']),
                'imagen': self.img.producto(pid), 'enlace': p['enlace'],
                'precio_min_centavos': p['precio_min_centavos'], 'precio_max_centavos': p['precio_max_centavos'],
                'precio_venta_min_centavos': vmin, 'precio_venta_max_centavos': vmax, 'precio_fuente': fuente,
                'comision_bp': bp, 'comision_por_venta_centavos': cmin, 'comision_por_venta_max_centavos': cmax,
                'unidades_vendidas_global': p['unidades_vendidas'],
                'en_colaboracion_abierta': bool(p['en_colaboracion_abierta']),
                'en_vitrina': (pid in self.en_vitrina) if self.vitrina_conocida else None, 'categoria': p['categoria']}

    # ================================================================== órdenes
    def ordenes(self, f: F.FiltrosOrdenes, desde_at: int | None = None, max_items: int | None = None) -> Json:
        where, args = [], []
        if f.desde:
            where.append('o.creada_at >= ?')
            args.append(R.inicio_dia_epoch(f.desde))
        if f.hasta:
            where.append('o.creada_at < ?')
            args.append(R.inicio_dia_epoch(f.hasta + dt.timedelta(days=1)))
        if desde_at is not None:
            where.append('o.creada_at >= ?')
            args.append(desde_at)
        if f.estados:
            where.append('o.estado IN (' + ','.join('?' * len(f.estados)) + ')')
            args.extend(f.estados)
        lineas_cond, lineas_args = [], []
        if f.tienda:
            lineas_cond.append('COALESCE(ta.tienda_key, l.tienda_key) = ?')
            lineas_args.append(f.tienda)
        if f.producto:
            lineas_cond.append('l.product_id = ?')
            lineas_args.append(f.producto)
        if f.video:
            lineas_cond.append("l.content_id = ? AND l.tipo_contenido = 'VIDEO'")
            lineas_args.append(f.video)
        for cond, arg in zip(lineas_cond, lineas_args):
            where.append('EXISTS (SELECT 1 FROM orden_lineas l LEFT JOIN tienda_alias ta ON ta.alias = l.tienda_key '
                         f'WHERE l.order_id = o.order_id AND {cond})')
            args.append(arg)
        if f.q:
            patron = '%' + f.q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            where.append("(o.order_id LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM orden_lineas l WHERE l.order_id = o.order_id "
                         "AND (l.producto_nombre LIKE ? ESCAPE '\\' OR l.tienda_nombre LIKE ? ESCAPE '\\' "
                         "OR l.content_id LIKE ? ESCAPE '\\' OR l.product_id LIKE ? ESCAPE '\\')))")
            args.extend([patron] * 5)
        cond = (' WHERE ' + ' AND '.join(where)) if where else ''
        total = self.fila('SELECT COUNT(*) AS n FROM ordenes o' + cond, args)['n']  # type: ignore[index]
        por_pagina = f.por_pagina if max_items is None else max_items
        offset = (f.pagina - 1) * por_pagina
        ordenes = self.filas('SELECT o.* FROM ordenes o' + cond + ' ORDER BY o.creada_at DESC, o.order_id LIMIT ? OFFSET ?',
                             [*args, por_pagina, offset])
        lineas_por_orden: dict[str, list[Json]] = collections.defaultdict(list)
        if ordenes:
            ids = [o['order_id'] for o in ordenes]
            for i in range(0, len(ids), 500):
                lote = ids[i:i + 500]
                for l in self.filas('SELECT * FROM orden_lineas WHERE order_id IN (' + ','.join('?' * len(lote)) + ') '
                                    'ORDER BY order_id, linea_n', lote):
                    lineas_por_orden[l['order_id']].append(l)
        out = []
        for o in ordenes:
            lineas = []
            for l in lineas_por_orden.get(o['order_id'], []):
                lineas.append({'sku_id': l['sku_id'] or '', 'product_id': l['product_id'], 'producto': l['producto_nombre'],
                               'imagen': self.img.producto(l['product_id']), 'tienda_nombre': l['tienda_nombre'],
                               'precio_centavos': l['precio_centavos'], 'cantidad': l['cantidad'],
                               'reembolsadas': l['reembolsadas'], 'devueltas': l['devueltas'], 'comision_bp': l['comision_bp'],
                               'comision_std_bp': l['comision_std_bp'], 'comision_ads_bp': l['comision_ads_bp'],
                               'comision_bono_bp': l['comision_bono_bp'],
                               'com_estimada_centavos': l['com_estimada_centavos'] or 0,
                               'com_real_centavos': l['com_real_centavos'] or 0,
                               'base_estimada_centavos': l['base_estimada_centavos'], 'base_real_centavos': l['base_real_centavos'],
                               'isr_centavos': l['isr_centavos'], 'iva_centavos': l['iva_centavos'],
                               'compartido_agencia_centavos': l['compartido_centavos'], 'tipo_contenido': l['tipo_contenido'],
                               'content_id': l['content_id'], 'actualizada_at': l['linea_actualizada_at'],
                               'es_carrusel': None if l['es_carrusel'] is None else bool(l['es_carrusel'])})
            out.append({'order_id': o['order_id'], 'creada_at': o['creada_at'], 'fecha': comun.fecha_local(o['creada_at']),
                        'estado': o['estado'], 'estado_etiqueta': R.ETIQ_ORDEN.get(o['estado'], o['estado']),
                        'total_centavos': sum((x['precio_centavos'] or 0) * max(0, x['cantidad'] - max(x['reembolsadas'],
                                                                                                        x['devueltas']))
                                              for x in lineas),
                        'comision_estimada_centavos': sum(x['com_estimada_centavos'] for x in lineas),
                        'comision_real_centavos': sum(x['com_real_centavos'] for x in lineas), 'lineas': lineas})
        return {'items': out, 'total': total, 'pagina': f.pagina, 'por_pagina': por_pagina, 'data_version': self.data_version}

    # ================================================================== estado local en respuestas compuestas
    def notas_de(self, entidad: str, entidad_id: str) -> list[Json]:
        return [n for n in self.notas if n['entidad'] == entidad and n['entidad_id'] == entidad_id]

    def planes_de(self, aid: str) -> list[Json]:
        return [p for p in self.planes if p['application_id'] == aid]

    def recordatorios_de_muestra(self, aid: str) -> list[Json]:
        planes = {p['id'] for p in self.planes_de(aid)}
        return [r for r in self.recordatorios if (r['entidad'] == 'muestra' and r['entidad_id'] == aid)
                or (r['entidad'] == 'plan' and r['entidad_id'] in planes)]

    def avisos_vista(self, aid: str | None = None, tk: str | None = None) -> list[Json]:
        return [dict(a) for a in self.avisos if not ((aid and aid not in a['solicitud_ids']) or (tk and a['tienda_key'] != tk))]

    # ================================================================== respuestas compuestas
    def videos_del_producto(self, pid: str) -> list[Json]:
        vids = []
        d = self.display                                       # rev. 5: métricas de la Display API (si hay)
        por_video = self.videos_producto(pid)
        self.img.cargar(f'v:{cid}' for cid in por_video)
        for cid, rs in por_video.items():
            com = sum(r['com_estimada_centavos'] for r in rs if r['valida'])
            portada = self.miniatura_video(cid)[0]
            v = {'content_id': cid, 'miniatura': portada, 'portada': portada, 'enlace': self.enlace_video(cid),
                 'primera_venta': min(r['fecha'] for r in rs), 'comision_estimada_centavos': com}
            if d is not None:
                campos = display_api.campos_video_producto(d, cid, len({r['order_id'] for r in rs if r['valida']}), com,
                                                           portada)
                campos.pop('portada', None)  # La caché real no depende de disponer también de métricas.
                v.update(campos)
            vids.append(v)
        vids.sort(key=lambda v: (v['primera_venta'], v['content_id']), reverse=True)
        return vids

    def historial(self, aid: str) -> list[Json]:
        return [{'campo': h['campo'], 'antes': h['antes'], 'despues': h['despues'], 'at': h['at']}
                for h in self.filas('SELECT campo, antes, despues, at FROM muestras_historial WHERE application_id = ? '
                                    'ORDER BY at, id', (aid,))]

    def muestra_detalle(self, aid: str) -> Json:
        m = self.por_id.get(aid)
        if m is None:
            raise F.no_encontrado('No encontramos esa muestra.')
        otras = [{'application_id': x['application_id'], 'grupo': x['grupo'], 'etiqueta': R.ETIQUETA[x['subestado']],
                  'producto': self.producto(x)} for x in self.M_tienda.get(m['tienda_key'], []) if x['application_id'] != aid]
        return {'muestra': self.muestra_vista(m), 'historial': self.historial(aid), 'notas': self.notas_de('muestra', aid),
                'planes': self.planes_de(aid), 'recordatorios': self.recordatorios_de_muestra(aid),
                'avisos': self.avisos_vista(aid=aid), 'plantilla_sugerida': self.plantilla_sugerida(m),
                'videos_del_producto': self.videos_del_producto(m['product_id']), 'otras_de_la_tienda': otras}

    def plantilla_tienda(self, tk: str, es_socio: bool) -> str | None:
        pend = [m for m in self.M_tienda.get(tk, []) if m['pendiente']]
        return ('varias_muestras' if len(pend) >= 2 else self.plantilla_sugerida(pend[0]) if pend
                else 'gracias_por_las_ventas' if es_socio else None)

    def serie_tienda(self, tk: str) -> list[Json]:
        return self.serie_de([r for r in self.L_tienda.get(tk, []) if r['_d'] <= self.hoy], 'mes')

    def tienda_detalle(self, tk: str, desde: dt.date | None = None, hasta: dt.date | None = None) -> Json:
        f = self.fila_tienda(tk, desde, hasta)
        ms = self.M_tienda.get(tk, [])
        prods = [p for p in self.productos_todos(None, None) if p['tienda_key'] == tk]
        return {'tienda': f, 'muestras': [self.muestra_vista(m) for m in ms], 'serie': self.serie_tienda(tk),
                'productos': prods, 'notas': self.notas_de('tienda', tk), 'avisos': self.avisos_vista(tk=tk),
                'plantilla_sugerida': self.plantilla_tienda(tk, f['es_socio'])}

    def video_detalle(self, cid: str) -> Json:
        fila = next((v for v in self.videos_todos(None, None) if v['content_id'] == cid), None)
        if fila is None:
            raise F.no_encontrado('No encontramos ventas de ese video.')
        lineas = [r for r in self.L if r['content_id'] == cid and r['tipo_contenido'] == 'VIDEO']
        pids = {r['product_id'] for r in lineas}
        r = {'video': fila, 'serie': self.serie_de(lineas, 'semana'),
             'productos': [p for p in self.productos_todos(None, None) if p['product_id'] in pids]}
        if self.display is not None:                           # rev. 5: fotos diarias de vistas, likes, …
            r['tendencia'] = display_api.tendencia(self.conn, cid)
        return r

    def producto_detalle(self, pid: str) -> Json:
        p = self.productos_tabla.get(pid)
        lineas = self.L_producto.get(pid, [])
        mu = [m for m in self.M if m['product_id'] == pid]
        if p is None and not lineas and not mu and self.fila(
                "SELECT 1 AS x FROM vitrina WHERE product_id = ? UNION ALL SELECT 1 FROM solicitudes_recuperadas "
                "WHERE product_id = ? AND estado = 'ok' LIMIT 1", (pid, pid)) is None:
            raise F.no_encontrado('No encontramos ese producto.')
        ficha = self.ficha_producto(pid)
        con_ficha = ficha is not None and p is not None
        fila = next((x for x in self.productos_todos(None, None) if x['product_id'] == pid), None)
        cids = {r['content_id'] for r in lineas if r['tipo_contenido'] == 'VIDEO' and r['content_id']}
        return {'product_id': pid, 'ficha': ficha,
                'con_inventario': (None if p['con_inventario'] is None else bool(p['con_inventario'])) if con_ficha else None,
                'categoria_ruta': (p['categoria'].replace(' > ', ' › ') if p['categoria'] else None) if con_ficha else None,
                'comision_anuncios_bp': p['shop_ads_bp'] if con_ficha else None,
                'fila': fila, 'serie': self.serie_de([r for r in lineas if r['_d'] <= self.hoy], 'mes'),
                'videos': [v for v in self.videos_todos(None, None) if v['content_id'] in cids],
                'muestras': [self.muestra_vista(m) for m in mu], 'notas': self.notas_de('producto', pid),
                'extendido': self.producto_extendido(pid)}

    # ================================================================== rev. 4 (15/11): ficha completa de producto
    def producto_extendido(self, pid: str) -> Json:
        """ProductoExtendido (contrato rev. 4): todo lo que la API oficial de afiliados da de un producto y que la ficha
        básica no traía. Cada parte es null (o []) mientras su fase de la sync no haya traído datos."""
        origen = self.origen_ventas(pid)
        from ..productos_evidencia import leer_evidencia
        evidencia = leer_evidencia(self.conn, self.img, pid)
        # orders/trace/search se retiró (15/08/2026): ya no hay un permiso pendiente que avisar. El aviso conserva su
        # tipo por compatibilidad y siempre va en null; `origen_ventas` solo lee el histórico cerrado de orden_trazas.
        return {'galeria': self.galeria_vitrina(pid), 'vitrina': self.vitrina_extendida(pid),
                'tabla_tallas': evidencia['tabla_tallas'], 'resenas': evidencia['resenas'],
                'evidencia_rev': evidencia['rev'],
                'muestra': self.elegibilidad_muestra(pid), 'solicitudes_recuperadas': self.solicitudes_recuperadas(pid),
                'planes_dirigidos': self.planes_dirigidos(pid), 'comision_real': self.comision_real(pid),
                'parecidos': self.parecidos(pid), 'origen_ventas': origen, 'origen_ventas_aviso': None,
                'origen_ventas_actual': self.origen_ventas_actual(pid)}

    def galeria_vitrina(self, pid: str) -> list[str]:
        v = self.fila('SELECT galeria_json FROM vitrina WHERE product_id = ?', (pid,))
        try:
            urls = json.loads(v['galeria_json']) if v and v['galeria_json'] else []
        except ValueError:
            urls = []
        n = min(len(urls) if isinstance(urls, list) else 0, MAX_GALERIA)
        self.img.cargar([f'g:{pid}-{i}' for i in range(n)])
        return [u for u in (self.img.url('g', f'{pid}-{i}') for i in range(n)) if u]

    def vitrina_extendida(self, pid: str) -> Json | None:
        v = self.fila('SELECT * FROM vitrina WHERE product_id = ?', (pid,))
        if v is None:
            return None
        inv = v['inventario']
        return {'inventario': inv, 'con_existencias': (True if inv == 'IN_STOCK' else False if inv in AGOTADO else None),
                'precio_lista_min_centavos': v['precio_min_centavos'], 'precio_lista_max_centavos': v['precio_max_centavos'],
                'precio_venta_min_centavos': v['precio_desc_min_centavos'],
                'precio_venta_max_centavos': v['precio_desc_max_centavos'],
                'precio_plataforma_min_centavos': v['precio_plat_min_centavos'],
                'precio_plataforma_max_centavos': v['precio_plat_max_centavos'],
                'comision_bp': v['comision_bp'], 'oculto': None if v['oculto'] is None else bool(v['oculto'])}

    def elegibilidad_muestra(self, pid: str) -> Json | None:
        e = self.fila('SELECT * FROM muestra_etiquetas WHERE product_id = ?', (pid,))
        if e is None or e['huella'] is None:
            return None
        try:
            skus = json.loads(e['skus_json'] or '[]')
        except ValueError:
            skus = []
        puede = None if e['puede_solicitar'] is None else bool(e['puede_solicitar'])
        limite = None if e['limite_alcanzado'] is None else bool(e['limite_alcanzado'])
        out_skus = []
        for s in skus if isinstance(skus, list) else []:
            props = [{'nombre': str(x.get('nombre') or ''), 'valor': str(x.get('valor') or '')}
                     for x in s.get('propiedades') or [] if isinstance(x, dict)]
            motivo = s.get('motivo') if s.get('disponible') is False else None
            out_skus.append({'sku_id': str(s.get('sku_id') or ''), 'propiedades': props,
                             'variante': ' / '.join(p['valor'] for p in props if p['valor']) or None,
                             'precio_centavos': s.get('precio_centavos'), 'disponible': s.get('disponible'),
                             'motivo_no_disponible': motivo,
                             'motivo_texto': (TEXTO_MOTIVO_SKU.get(motivo, 'No disponible como muestra') if motivo
                                              else ('No disponible como muestra' if s.get('disponible') is False
                                                    else None))})
        return {'puede_solicitar': puede, 'estado': e['estado'],
                'estado_texto': texto_elegibilidad(puede, e['estado'], limite), 'application_id': e['application_id'],
                'limite_alcanzado': limite, 'skus': out_skus,
                'consultado_at': e['consultado_at'] if e['error_codigo'] is None else e['actualizado_at']}

    def solicitudes_recuperadas(self, pid: str) -> list[Json]:
        filas = self.filas("""SELECT r.application_id, r.sku_id, r.variante, r.tipo, r.solicitada_at, c.estado AS cumplimiento
                              FROM solicitudes_recuperadas r LEFT JOIN v_cumplimiento_vigente c USING (application_id)
                              WHERE r.product_id = ? AND r.estado = 'ok'
                                AND r.application_id NOT IN (SELECT application_id FROM muestras)
                              ORDER BY COALESCE(r.solicitada_at, 0) DESC, r.application_id""", (pid,))
        return [{'application_id': f['application_id'], 'sku_id': f['sku_id'], 'variante': f['variante'],
                 'tipo': f['tipo'], 'tipo_texto': TEXTO_TIPO_SOLICITUD.get(f['tipo'] or '', None),
                 'solicitada_at': f['solicitada_at'], 'cumplimiento': f['cumplimiento'],
                 'cumplimiento_texto': TEXTO_CUMPLIMIENTO.get(f['cumplimiento'] or '', None)} for f in filas]

    def planes_dirigidos(self, pid: str) -> list[Json]:
        filas = self.filas("""SELECT d.collab_id, d.nombre, d.estado, d.comision_bp, d.comision_monto_centavos,
                                     t.nombre AS tienda_nombre
                              FROM colaboraciones_dirigidas d LEFT JOIN tiendas t ON t.shop_id = d.shop_id
                              WHERE d.product_id = ?
                              ORDER BY (d.estado = 'LIVE') DESC, COALESCE(d.comision_bp, 0) DESC, d.collab_id""", (pid,))
        return [{'collab_id': f['collab_id'], 'nombre': f['nombre'], 'estado': f['estado'],
                 'estado_texto': TEXTO_PLAN_DIRIGIDO.get(f['estado'] or '', 'Sin estado'), 'activo': f['estado'] == 'LIVE',
                 'comision_bp': f['comision_bp'], 'comision_monto_centavos': f['comision_monto_centavos'],
                 'tienda_nombre': f['tienda_nombre']} for f in filas]

    def comision_real(self, pid: str) -> Json | None:
        """Tasa que de verdad pagaron TUS ventas de este producto (commission_rate de cada línea válida, sin pedidos de
        muestra), agrupada por tasa; se compara con el plan abierto vigente (puede ser distinta: campaña o plan dirigido)."""
        lineas = [r for r in self.L_producto.get(pid, [])
                  if r['valida'] and not r['es_pedido_muestra'] and r['comision_bp'] is not None]
        if not lineas:
            return None
        campana = {(f['order_id'], f['linea_n']): f['campaign_id'] for f in self.filas(
            "SELECT order_id, linea_n, campaign_id FROM orden_lineas WHERE product_id = ? AND campaign_id IS NOT NULL "
            "AND campaign_id NOT IN ('', '0')", (pid,))}
        g: dict[int, dict[str, int]] = {}
        for r in lineas:
            x = g.setdefault(int(r['comision_bp']), {'lineas': 0, 'unidades': 0, 'com': 0, 'campana': 0})
            x['lineas'] += 1
            x['unidades'] += int(r['unidades_netas'] or 0)
            x['com'] += int(r['com_estimada_centavos'] or 0)
            x['campana'] += int((r['order_id'], r['linea_n']) in campana)
        total = len(lineas)
        por_tasa = [{'comision_bp': bp, 'lineas': x['lineas'], 'unidades': x['unidades'],
                     'comision_estimada_centavos': x['com'], 'participacion': round(x['lineas'] / total, 4),
                     'lineas_con_campana': x['campana']}
                    for bp, x in sorted(g.items(), key=lambda kv: (-kv[1]['lineas'], -kv[0]))]
        p = self.productos_tabla.get(pid)
        plan = p['comision_bp'] if p and p['origen'] == 'api' and p['en_colaboracion_abierta'] else None
        return {'lineas': total, 'por_tasa': por_tasa, 'tasa_principal_bp': por_tasa[0]['comision_bp'],
                'plan_abierto_bp': plan, 'campanas': len(set(campana.values()))}

    def parecidos(self, pid: str) -> Json | None:
        c = self.fila('SELECT palabras_json, consultado_at, huella, error_codigo FROM parecidos_consultas '
                      'WHERE product_id = ?', (pid,))
        if c is None or c['huella'] is None:
            return None
        filas = self.filas('SELECT * FROM productos_parecidos WHERE product_id = ? ORDER BY posicion', (pid,))
        self.img.cargar([f"m:{f['parecido_id']}" for f in filas])
        propios = set(self.productos_tabla) | self.en_vitrina | set(self.L_producto) | {m['product_id'] for m in self.M}
        items = []
        for f in filas:
            bp = f['comision_bp']
            pcmin = comun.precio_venta_por_comision(f['comision_monto_min_centavos'], bp) if bp and bp > 0 else None
            pcmax = comun.precio_venta_por_comision(f['comision_monto_max_centavos'], bp) if bp and bp > 0 else None
            if pcmin is not None:
                fuente, vmin, vmax = 'comision', pcmin, (pcmax if pcmax is not None else pcmin)
            elif f['precio_min_centavos'] is not None:
                fuente, vmin = 'lista', f['precio_min_centavos']
                vmax = f['precio_max_centavos'] if f['precio_max_centavos'] is not None else vmin
            else:
                fuente, vmin, vmax = None, None, None
            items.append({'product_id': f['parecido_id'], 'titulo': f['titulo'], 'titulo_corto': R.nombre_corto(f['titulo']),
                          'tienda_nombre': f['tienda_nombre'], 'imagen': self.img.url('m', f['parecido_id']),
                          'precio_min_centavos': f['precio_min_centavos'], 'precio_max_centavos': f['precio_max_centavos'],
                          'precio_venta_min_centavos': vmin, 'precio_venta_max_centavos': vmax, 'precio_fuente': fuente,
                          'comision_bp': bp, 'comision_por_venta_centavos': f['comision_monto_min_centavos'],
                          'comision_por_venta_max_centavos': f['comision_monto_max_centavos'],
                          'unidades_vendidas_global': f['unidades_vendidas'], 'enlace': f['enlace'],
                          'tiene_ficha': f['parecido_id'] in propios})
        try:
            palabras = [str(w) for w in json.loads(c['palabras_json'] or '[]')]
        except ValueError:
            palabras = []
        return {'palabras': palabras, 'consultado_at': c['consultado_at'], 'items': items}

    def origen_ventas(self, pid: str) -> Json | None:
        """Histórico CERRADO de orders/trace/search (retirada el 15/08/2026): conteos por línea SKU de lo que esa ruta
        llegó a registrar, con su procedencia y periodo. Nunca se extrapola a ventas posteriores. Una línea sin `trace`
        es «sin enlace reportado», no una prueba de que la venta no viniera de un enlace."""
        filas = self.filas('SELECT tipo_contenido, traza_tipo, COUNT(*) AS n FROM orden_trazas WHERE product_id = ? '
                           'GROUP BY tipo_contenido, traza_tipo', (pid,))
        if not filas:
            return None
        periodo = self.fila('SELECT MIN(creada_at) AS desde, MAX(creada_at) AS hasta, COUNT(DISTINCT order_id) AS pedidos '
                            'FROM orden_trazas WHERE product_id = ?', (pid,))
        contenido: dict[str | None, int] = collections.Counter()
        enlace: dict[str | None, int] = collections.Counter()
        for f in filas:
            contenido[f['tipo_contenido']] += int(f['n'])
            enlace[f['traza_tipo']] += int(f['n'])

        def lista(cuenta: Mapping[str | None, int], textos: Mapping[str, str], sin: str) -> list[Json]:
            return [{'tipo': t, 'texto': textos.get(t or '', t or sin) if t else sin, 'lineas': n}
                    for t, n in sorted(cuenta.items(), key=lambda kv: (-kv[1], kv[0] or '~'))]
        return {'lineas': sum(contenido.values()),
                'por_tipo_contenido': lista(contenido, TEXTO_TIPO_CONTENIDO, 'Sin dato'),
                'por_tipo_enlace': lista(enlace, TEXTO_TIPO_ENLACE, 'Sin enlace reportado'),
                'fuente': FUENTE_ORIGEN_HISTORICO, 'pedidos': int(periodo['pedidos']),
                'desde_at': periodo['desde'], 'hasta_at': periodo['hasta']}

    def origen_ventas_actual(self, pid: str) -> Json | None:
        """rev. 7 · Enlaces que reporta orders/search 202410 (trace_info.type) en las líneas de este producto que el paso
        de pedidos observó en una ventana completa (orden_lineas_traza). Es un bloque APARTE del histórico: los pedidos
        que ya están en orden_trazas se quedan solo en el histórico (cerrado y estable), así que ningún pedido cuenta en
        los dos y nunca se suman. traza_tipo NULL = «Sin enlace reportado» (no es «orgánico» ni «vino de un video»). Las
        líneas sin fila son «sin dato»: no entran en los conteos y solo se informan aparte, y solo las de pedidos creados
        desde el inicio del periodo del bloque que TikTok todavía devuelve: las anteriores esperan al barrido completo y un
        NO_DEVUELTA nunca se volverá a observar. None si no hay ninguna línea observada (antes de la primera sync de la
        rev. 7, o un producto sin pedidos)."""
        filas = self.filas('SELECT t.traza_tipo, COUNT(*) AS n FROM orden_lineas l '
                           'JOIN orden_lineas_traza t ON t.order_id = l.order_id AND t.linea_n = l.linea_n '
                           f'WHERE l.product_id = ? AND {_FUERA_DEL_HISTORICO} GROUP BY t.traza_tipo', (pid,))
        if not filas:
            return None
        periodo = self.fila('SELECT MIN(o.creada_at) AS desde, MAX(o.creada_at) AS hasta, '
                            'COUNT(DISTINCT l.order_id) AS pedidos, MAX(t.capturada_at) AS capturada FROM orden_lineas l '
                            'JOIN orden_lineas_traza t ON t.order_id = l.order_id AND t.linea_n = l.linea_n '
                            'JOIN ordenes o ON o.order_id = l.order_id '
                            f'WHERE l.product_id = ? AND {_FUERA_DEL_HISTORICO}', (pid,))
        sin_dato = self.fila('SELECT COUNT(*) AS n FROM orden_lineas l JOIN ordenes o ON o.order_id = l.order_id '
                             'LEFT JOIN orden_lineas_traza t ON t.order_id = l.order_id AND t.linea_n = l.linea_n '
                             "WHERE l.product_id = ? AND t.order_id IS NULL AND o.estado <> 'NO_DEVUELTA' "
                             f'AND o.creada_at >= ? AND {_FUERA_DEL_HISTORICO}', (pid, periodo['desde']))
        enlace: dict[str | None, int] = collections.Counter()
        for f in filas:
            enlace[f['traza_tipo']] += int(f['n'])
        lineas = sum(enlace.values())
        return {'lineas': lineas, 'con_enlace': lineas - enlace.get(None, 0),
                'por_tipo_enlace': [{'tipo': t, 'texto': TEXTO_TIPO_ENLACE.get(t, t) if t else 'Sin enlace reportado',
                                     'lineas': n} for t, n in sorted(enlace.items(), key=lambda kv: (-kv[1], kv[0] or '~'))],
                'lineas_sin_dato': int(sin_dato['n']), 'pedidos': int(periodo['pedidos']), 'fuente': FUENTE_ORIGEN_ACTUAL,
                'desde_at': periodo['desde'], 'hasta_at': periodo['hasta'], 'capturada_at': periodo['capturada']}

    def dashboard(self, clave: str, conexion: Mapping[str, Any] | None) -> Json:
        per = F.resolver_periodo(clave, self.hoy, self.primera_fecha)
        k = self.kpis(per.desde, per.hasta)
        ka = self.kpis(per.anterior_desde, per.anterior_hasta) if per.anterior_desde else None
        rm = self.resumen_muestras()
        ts = self.tiendas('atencion', per.desde, per.hasta)
        vs, _ = self.videos(per.desde, per.hasta, 5)
        ps, _ = self.productos(per.desde, per.hasta, 5)
        return {'periodo': {'clave': per.clave, 'desde': str(per.desde), 'hasta': str(per.hasta),
                            'anterior_desde': str(per.anterior_desde) if per.anterior_desde else None,
                            'anterior_hasta': str(per.anterior_hasta) if per.anterior_hasta else None},
                'kpis': k, 'kpis_anterior': ka, 'muestras': rm,
                'serie': {'granularidad': per.granularidad, 'puntos': self.serie(per.granularidad, per.desde, per.hasta)},
                'top_tiendas': ts[:5], 'top_videos': vs, 'top_productos': ps,
                'alertas': self.alertas(rm, ts, k, conexion), 'data_version': self.data_version, 'generado_at': self.ahora,
                'actualidad': resumen_actualidad(self.conn, self.ahora),
                **self._perfil_tiktok()}

    # ================================================================== rev. 5 (15/11): Display API (métricas de tus videos)
    @cached_property
    def display(self) -> DisplayDatos | None:
        """Métricas de la Display API leídas en la MISMA transacción; None si nunca se trajo nada (campos ausentes)."""
        return display_api.cargar(self.conn)

    def _agregar_display(self, filas: list[Json], desde: dt.date | None, hasta: dt.date | None) -> None:
        d = self.display
        if d is None:
            return
        base = filas if (desde, hasta) == (None, None) else self.videos_todos(None, None)
        vida = {f['content_id']: (f['pedidos_validos'], f['comision_estimada_centavos']) for f in base}
        self.img.cargar(f"v:{f['content_id']}" for f in filas)
        for f in filas:
            cid = f['content_id']
            ped, com = vida.get(cid, (f['pedidos_validos'], f['comision_estimada_centavos']))
            campos = display_api.campos_fila_video(d, cid, ped, com, f['portada'])
            campos.pop('portada', None)  # Nunca reemplazar una portada real cacheada por un campo opcional ausente.
            f.update(campos)

    def _perfil_tiktok(self) -> Json:
        d = self.display
        resumen = display_api.resumen_perfil(self.conn, d, self.hoy) if d is not None else None
        return {'perfil_tiktok': resumen} if resumen is not None else {}

    # ================================================================== rev. 6 (18/11): catálogo de videos
    def misma_cuenta_display(self) -> bool | None:
        """¿La cuenta de la Display API es la del creador de TikTok Shop? Compara nombres de usuario normalizados.
        None si falta alguno de los dos (no se puede comprobar)."""
        from ..tiktok_dev.datos import usuario_normalizado
        d = self.display
        shop = usuario_normalizado(self.username)
        propia = usuario_normalizado((d.perfil or {}).get('username')) if d is not None else ''
        if not shop or not propia:
            return None
        return shop == propia

    def _catalogo_items(self, incluir_historial: bool, solo: str | None = None) -> tuple[list[Json], Json | None]:
        """VideoCatalogo de cada video PUBLICADO (Display API) o CON VENTAS, unidos por ID exacto (video_id de la
        Display API == content_id de las líneas VIDEO). Los videos sin ventas solo entran si la cuenta de la Display
        API es la del creador; con ventas entran siempre. Nunca se inventa una cifra: lo que no se sabe va en null y
        un video sin pedidos lleva `ventas: null`, no ceros. `solo`: arma únicamente ese ID (detalle).
        `incluir_historial` solo decide si entran los videos SIN ventas que únicamente conservan historial: un video
        con ventas que dejó de ser público lleva su última foto en toda vista (lista, historial y detalle coinciden).
        -> (items sin ordenar, bloque `display` | None)."""
        d = self.display
        vendidos = {f['content_id']: f for f in self.videos_todos(None, None)}
        organicos: Mapping[str, Json] = {}
        historial: dict[str, Json] = {}
        bloque: Json | None = None
        ultima_at: int | None = None
        tope: int | None = None
        sin_registrar: frozenset[int] = frozenset()
        if d is not None:
            ultima_at, tope = display_api.ultima_sync(self.conn)
            sin_registrar = display_api.pasadas_sin_registrar(self.conn)
            misma = self.misma_cuenta_display()
            bloque = {'ultima_sync_at': ultima_at, 'misma_cuenta': misma}
            if misma is True:
                organicos = d.videos
            if misma is True and incluir_historial:
                historial = display_api.fotos_sin_video(self.conn, solo=solo)
            else:
                # Por ID exacto: la foto de un video con ventas solo pudo venir de la cuenta del creador.
                faltan = [c for c in vendidos if c not in d.videos and (solo is None or c == solo)]
                historial = display_api.fotos_sin_video(self.conn, ids=faltan) if faltan else {}
        vinculadas: dict[str, list[str]] = collections.defaultdict(list)
        for m in self.M:
            if m['plan_content_id']:
                vinculadas[m['plan_content_id']].append(m['application_id'])
        ids = list(dict.fromkeys([*vendidos, *organicos, *historial]))
        if solo is not None:
            ids = [solo] if solo in ids else []
        self.img.cargar(f'v:{cid}' for cid in ids)
        items: list[Json] = []
        for cid in ids:
            venta = vendidos.get(cid)
            v = d.videos.get(cid) if d is not None and (venta is not None or cid in organicos) else None
            h = historial.get(cid) if v is None else None
            if v is not None:
                # Salió en la pasada registrada (visto_at == su instante) o en una POSTERIOR en curso o interrumpida:
                # visto_at mayor que el tope guardado con el cursor, o el instante de una pasada aún sin registrar (vale
                # aunque el reloj se haya atrasado). Sin cursor, la primera pasada no terminó y todo salió en ella.
                publicacion = ('publico' if ultima_at is None or v['visto_at'] == ultima_at
                               or (tope is not None and v['visto_at'] > tope) or v['visto_at'] in sin_registrar
                               else 'no_confirmado')
            elif h is not None:
                publicacion = 'no_publico'
            else:
                publicacion = 'desconocido'
            fuente = v if v is not None else h
            items.append({
                'content_id': cid,
                'origen': 'display_y_ventas' if venta is not None and fuente is not None
                          else 'ventas' if venta is not None else 'display',
                'publicacion': publicacion,
                'descripcion': (v['titulo'] or v['descripcion']) if v is not None else None,
                'portada': self.miniatura_video(cid)[0],
                'enlace': self.enlace_video(cid),
                'publicado_at': v['creado_at'] if v is not None else None,
                'duracion_s': v['duracion_s'] if v is not None else None,
                'vistas': fuente['vistas'] if fuente is not None else None,
                'likes': fuente['likes'] if fuente is not None else None,
                'comentarios': fuente['comentarios'] if fuente is not None else None,
                'compartidos': fuente['compartidos'] if fuente is not None else None,
                'metricas_at': (v['visto_at'] if v is not None else h['actualizado_at'] if h is not None else None),
                'ventas': venta,
                'muestras_vinculadas': venta['muestras_vinculadas'] if venta is not None
                                       else sorted(vinculadas.get(cid, []))})
        return items, bloque

    @staticmethod
    def _orden_catalogo(items: list[Json], orden: str) -> list[Json]:
        def ultima_venta(i: Json) -> int:
            return -dt.date.fromisoformat(i['ventas']['ultima_venta']).toordinal() if i['ventas'] else 0
        if orden == 'vistas':
            clave = lambda i: (i['vistas'] is None, -(i['vistas'] or 0), i['content_id'])  # noqa: E731
        elif orden == 'comision':
            clave = lambda i: (i['ventas'] is None,  # noqa: E731
                               -(i['ventas']['comision_estimada_centavos'] if i['ventas'] else 0), i['content_id'])
        else:                                       # 'publicado': lo más nuevo primero; sin fecha, por última venta
            clave = lambda i: (i['publicado_at'] is None, -(i['publicado_at'] or 0), ultima_venta(i),  # noqa: E731
                               i['content_id'])
        return sorted(items, key=clave)

    def videos_catalogo(self, orden: str, incluir_historial: bool, limite: int) -> Json:
        """CatalogoVideosResponse (rev. 6). Las rutas de ventas (/api/analitica/videos, /api/videos/{id}) no cambian."""
        items, bloque = self._catalogo_items(incluir_historial)
        items = self._orden_catalogo(items, orden)
        return {'items': items[:limite], 'total': len(items), 'data_version': self.data_version, 'display': bloque,
                'pedidos_desde': self.primera_fecha.isoformat() if self.primera_fecha else None}

    def video_catalogo_detalle(self, cid: str) -> Json:
        """VideoCatalogoDetalleResponse (rev. 6): sirve también para videos sin ventas y para los que solo conservan
        historial. `ventas` = el detalle de ventas de siempre (sin `tendencia`) o null."""
        items, _ = self._catalogo_items(incluir_historial=True, solo=cid)
        item = next((i for i in items if i['content_id'] == cid), None)
        if item is None:
            raise F.no_encontrado('No encontramos ese video.', {'recurso': 'video'})
        ventas = None
        if item['ventas'] is not None:
            ventas = self.video_detalle(cid)
            ventas.pop('tendencia', None)
        return {'video': item, 'ventas': ventas,
                'tendencia': display_api.tendencia(self.conn, cid) if self.display is not None else None}
