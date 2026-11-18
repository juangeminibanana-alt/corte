"""Fases de la FICHA COMPLETA DE PRODUCTO (rev. 4, 15/11/2026; 03 §4.2 «Ficha completa»). Todo es de LECTURA de la API
oficial de afiliados (los endpoints de escritura nunca se tocan). El comportamiento se validó antes con un script de
exploración aparte (fuera de este paquete); no es dependencia.

Corren DENTRO del paso público `productos_ventas` (después de las fichas), en este orden, sin cambiar `PasoSync` del
contrato: sus cifras van a `sync_ejecuciones.resumen_json['fases'][<fase>]` = {estado, hechos, nuevos, cambiados,
errores, llamadas, codigo} con estado 'ok' | 'parcial' | 'sin_permiso' | 'error'. Sus errores NUNCA vuelven parcial la
sync (lo que falle se reintenta en otra), salvo los de control (cancelar, sin internet, reautorizar, abortar o cambio de
cuenta), que se propagan como en cualquier paso.

  1. recuperadas  POST 202412/sample_applications/single_query para las solicitudes que solo se conocen por su
                  cumplimiento (no salen en sample_applications/search): application_id + el sample_application_type
                  del cumplimiento (y si falla, el otro tipo). Así sale su SKU y su variante. Máx. 30 por sync; si falla,
                  se reintenta a 1, 2, 4… días (máx. 5 intentos).
  2. etiquetas    GET 202412/samples/labels?product_id= para los productos en vitrina, con muestra o recuperados:
                  can_apply, status, application_id, reach_limit y sample_sku_list. TTL 72 h (24 h si falló), máx. 60.
  3. dirigidas    POST 202405/target_collaborations/search (query page_size, body {shop_id}) para las tiendas con
                  shop_id (de cumplimientos): planes dirigidos y, por producto, commission.rate (centésimas de % =
                  puntos base) y amount. Semanal (24 h si falló), máx. 50 tiendas por sync.
  4. parecidos    POST 202405/open_collaborations/products/search (query page_size=20; body {title_keywords: [palabras]}
                  y, si falla, como texto): «parecidos por palabras del título» (la relevancia la decide TikTok). TTL 7 días
                  (24 h si falló), máx. 20 productos por sync y 20 parecidos por producto. Sus fotos van como 'm:<id>'.
La antigua fase 5 «trazas» (POST 202505/orders/trace/search) se quitó el 18/11/2026: TikTok retiró esa ruta para todos
los mercados el 15/08/2026 y llamarla solo producía errores en cada sync. `orden_trazas` queda como histórico cerrado:
nada la escribe ni la reescribe, y solo la purga de 400 días y los borrados explícitos la vacían
(docs/ORDER_TRACE_RETIREMENT.md).

Tres fallas seguidas (que no sean «sin permiso») detienen la fase en esa sync: no se insiste contra un endpoint caído.
Nunca hay red con una transacción abierta (03 §2.6 invariante 1) y las fotos se encolan después de confirmar.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from .comun import huella, norm_estado, parse_monto, parse_rango
from .errores import ErrorApi
from .interfaces import PedidoImagen

_log = logging.getLogger('creatorhub.sincronizador')

P_DETALLE = '/affiliate_creator/202412/sample_applications/single_query'
P_ETIQUETAS = '/affiliate_creator/202412/samples/labels'
P_DIRIGIDAS = '/affiliate_creator/202405/target_collaborations/search'
P_MARKETPLACE = '/affiliate_creator/202405/open_collaborations/products/search'

DIA_S = 86400
TTL_ETIQUETAS_S = 72 * 3600
TTL_DIRIGIDAS_S = 7 * DIA_S
TTL_PARECIDOS_S = 7 * DIA_S
TTL_ERROR_S = DIA_S
MAX_ETIQUETAS = 60
MAX_TIENDAS_DIRIGIDAS = 50
MAX_PRODUCTOS_PARECIDOS = 20
MAX_PARECIDOS = 20
MAX_RECUPERADAS = 30
MAX_INTENTOS_RECUPERADA = 5
MAX_PAGINAS_DIRIGIDAS = 10
FALLAS_SEGUIDAS_MAX = 3
CODIGOS_SIN_PERMISO: frozenset[Any] = frozenset({105005, 16501011})
TIPOS_SOLICITUD: tuple[str, ...] = ('FREE_SAMPLE', 'SAMPLE_COUPON')
RE_ID = re.compile(r'^[0-9]{1,25}$')
MAX_GALERIA = 12

ORDEN_FASES: tuple[str, ...] = ('recuperadas', 'etiquetas', 'dirigidas', 'parecidos')
TEXTOS_FASES: dict[str, str] = {
    'recuperadas': 'Completando datos de tus muestras…',
    'etiquetas': 'Revisando si puedes pedir muestra…',
    'dirigidas': 'Revisando planes de comisión de tus tiendas…',
    'parecidos': 'Buscando productos parecidos…',
}

_VACIAS = frozenset({'para', 'con', 'de', 'del', 'la', 'el', 'los', 'las', 'y', 'en', 'por', 'una', 'un', 'ideal', 'uso',
                     'diario', 'casual', 'hombre', 'mujer', 'prenda', 'tejido', 'duradero', 'cierre', 'unisex', 'nuevo',
                     'nueva', 'pieza', 'piezas', 'color', 'colores', 'talla', 'tallas', 'moda', 'estilo', 'calidad'})
_RE_PALABRA = re.compile(r'[A-Za-zÁÉÍÓÚÑÜáéíóúñü]{4,}')
_RE_PROMO = re.compile(r'【[^】]*】|\[[^\]]*\]')


# ====================================================================== utilidades puras
def palabras_clave(titulo: str | None, n: int = 4) -> list[str]:
    """Hasta `n` palabras útiles del título (≥ 4 letras, sin palabras vacías ni prefijos «【Buen Fin】»)."""
    texto = _RE_PROMO.sub(' ', titulo or '')
    out: list[str] = []
    vistos: set[str] = set()
    for w in _RE_PALABRA.findall(texto):
        k = w.lower()
        if k in _VACIAS or k in vistos:
            continue
        vistos.add(k)
        out.append(w)
        if len(out) >= n:
            break
    return out


def main_order(valor: Any) -> str | None:
    """main_order_id con '0' o '' -> None (03 §4.2)."""
    s = str(valor or '').strip()
    return None if s in ('', '0') else s


def _bool(valor: Any) -> int | None:
    return None if valor is None else int(bool(valor))


def _entero(valor: Any) -> int | None:
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


def skus_muestra(label: dict[str, Any]) -> list[dict[str, Any]]:
    """sample_product.sample_sku_list normalizado (sale_properties color/talla, precio en centavos, disponibilidad).
    `motivo` (unavailable_reason) solo se conserva cuando is_available es false (la doc: UNKNOWN también sale con true)."""
    out: list[dict[str, Any]] = []
    for s in ((label.get('sample_product') or {}).get('sample_sku_list') or []):
        if not isinstance(s, dict):
            continue
        props = [{'nombre': str(x.get('name') or x.get('id') or ''), 'valor': str(x.get('value_name') or '')}
                 for x in (s.get('sale_properties') or []) if isinstance(x, dict)]
        precio = s.get('price') or {}
        disp = s.get('is_available')
        out.append({'sku_id': str(s.get('id') or ''), 'propiedades': props,
                    'precio_centavos': parse_monto(precio.get('amount')), 'moneda': precio.get('currency') or None,
                    'disponible': None if disp is None else bool(disp),
                    'motivo': (str(s.get('unavailable_reason') or '') or None) if disp is False else None})
    return out


@dataclass
class ResultadoFase:
    estado: str = 'ok'
    hechos: int = 0
    nuevos: int = 0
    cambiados: int = 0
    errores: int = 0
    llamadas: int = 0
    codigo: str | None = None
    _seguidas: int = 0

    def exito(self) -> None:
        self.hechos += 1
        self._seguidas = 0

    def falla(self, e: ErrorApi) -> bool:
        """Anota un error de un elemento. -> True si hay que detener la fase (3 seguidas)."""
        self.errores += 1
        self.codigo = str(e.codigo)
        self._seguidas += 1
        if self._seguidas >= FALLAS_SEGUIDAS_MAX:
            self.estado = 'error' if self.hechos == 0 else 'parcial'
            return True
        self.estado = 'parcial'
        return False

    def sin_permiso(self, e: ErrorApi) -> None:
        self.estado = 'sin_permiso'
        self.codigo = str(e.codigo)

    def como_dict(self) -> dict[str, Any]:
        return {'estado': self.estado, 'hechos': self.hechos, 'nuevos': self.nuevos, 'cambiados': self.cambiados,
                'errores': self.errores, 'llamadas': self.llamadas, 'codigo': self.codigo}


# ====================================================================== mixin del sincronizador
class FasesFicha:
    """Lo usa `_Sincronizador` (sincronizador.py), que aporta _llamar, _tx, _leer, _encolar, _avance, _poner_cursor,
    _comprobar_cancelacion, _error_de_control, alm, ahora, tipo, sid, resumen, cambios, secciones y _escala."""

    # ------------------------------------------------------------------ orquestación
    def _correr_fases_ficha(self, paso: str, desde: float) -> None:
        resumen = self.resumen.setdefault('fases', {})
        tramo = (1.0 - desde) / len(ORDEN_FASES)
        for i, fase in enumerate(ORDEN_FASES):
            self._comprobar_cancelacion()
            self._escala[paso] = (desde + i * tramo, tramo)
            self._avance(paso, 0.0, texto=TEXTOS_FASES[fase])
            r = ResultadoFase()
            ll0 = self._c.ctx.llamadas
            try:
                getattr(self, f'_fase_{fase}')(r)
            except Exception as e:  # noqa: BLE001 - una falla de la ficha nunca tumba la sync (salvo las de control)
                if self._error_de_control(e):
                    raise
                if isinstance(e, ErrorApi):
                    r.falla(e)
                    r.estado = 'error' if r.hechos == 0 else 'parcial'
                else:
                    _log.exception('Falla interna en la fase %s de la ficha de producto (sync %s)', fase, self.sid)
                    r.estado, r.codigo = 'error', 'error_interno'
                    r.errores += 1
            r.llamadas = self._c.ctx.llamadas - ll0
            resumen[fase] = r.como_dict()
            if r.nuevos + r.cambiados:
                self.cambios += r.nuevos + r.cambiados
                self.secciones.add('productos')
            self._avance(paso, 1.0)
        self._escala.pop(paso, None)

    def _falla_o_permiso(self, r: ResultadoFase, e: ErrorApi) -> bool:
        """Clasifica un ErrorApi de un elemento. -> True si la fase debe detenerse (sin permiso o 3 fallas seguidas).
        Los errores de control (cancelar, reautorizar, abortar, cambio de cuenta) se propagan."""
        if self._error_de_control(e):
            raise e
        if e.codigo in CODIGOS_SIN_PERMISO:
            r.sin_permiso(e)
            return True
        return r.falla(e)

    @staticmethod
    def _ids(filas: list[Any], tope: int) -> list[str]:
        return [str(f[0]) for f in filas if f[0] is not None and RE_ID.match(str(f[0]))][:tope]

    # ------------------------------------------------------------------ 1. solicitudes recuperadas desde su cumplimiento
    def _fase_recuperadas(self, r: ResultadoFase) -> None:
        filas = self._leer("""
            SELECT c.application_id, c.product_id, c.fulfillment_id, c.tipo, COALESCE(x.intentos, 0) AS intentos,
                   x.estado AS estado_previo
            FROM v_cumplimiento_vigente c LEFT JOIN solicitudes_recuperadas x USING (application_id)
            WHERE c.application_id NOT IN (SELECT application_id FROM muestras)
              AND (x.application_id IS NULL
                   OR (x.estado <> 'ok' AND x.intentos < ? AND (x.reintento_at IS NULL OR x.reintento_at <= ?)))
            ORDER BY c.application_id""", (MAX_INTENTOS_RECUPERADA, self.ahora))
        filas = [f for f in filas if f['application_id'] and f['product_id'] and RE_ID.match(str(f['product_id']))]
        for f in filas[:MAX_RECUPERADAS]:
            aid, pid = str(f['application_id']), str(f['product_id'])
            tipo0 = f['tipo'] if f['tipo'] in TIPOS_SOLICITUD else 'FREE_SAMPLE'
            sa: dict[str, Any] | None = None
            tipo_ok, error = tipo0, None
            for t in [tipo0] + [x for x in TIPOS_SOLICITUD if x != tipo0]:
                try:
                    d = self._llamar('POST', P_DETALLE, None, {'product_id': pid, 'application_id': aid,
                                                               'application_type': t})
                    sa, tipo_ok = (d.get('sample_application') or d), t
                    break
                except ErrorApi as e:
                    if self._error_de_control(e):
                        raise
                    if e.codigo in CODIGOS_SIN_PERMISO:
                        r.sin_permiso(e)
                        return
                    error = e
            if sa is None:
                assert error is not None
                with self._tx() as db:
                    espera = min(7 * DIA_S, DIA_S * (2 ** int(f['intentos'])))
                    db.execute("""INSERT INTO solicitudes_recuperadas(application_id, product_id, fulfillment_id, tipo,
                                  estado, intentos, reintento_at, actualizado_at) VALUES (?,?,?,?,'error',1,?,?)
                                  ON CONFLICT(application_id) DO UPDATE SET estado='error', intentos=intentos+1,
                                  reintento_at=excluded.reintento_at""",
                               (aid, pid, f['fulfillment_id'], f['tipo'], self.ahora + espera, self.ahora))
                if r.falla(error):
                    return
                continue
            sp = sa.get('sample_product') or {}
            nombres = [str(x) for x in (sp.get('sku_sale_property_value_names') or []) if x not in (None, '')]
            datos = (str(sp.get('id') or pid), f['fulfillment_id'], sa.get('type') or tipo_ok,
                     str(sp['sku_id']) if sp.get('sku_id') else None, ' / '.join(nombres) or None,
                     main_order(sa.get('main_order_id')), norm_estado(sa.get('status')),
                     int(sa.get('create_time') or 0) or None)
            with self._tx() as db:
                prev = db.execute("""SELECT product_id, fulfillment_id, tipo, sku_id, variante, main_order_id, estado_api,
                                            solicitada_at, estado FROM solicitudes_recuperadas WHERE application_id=?""",
                                  (aid,)).fetchone()
                nuevo = prev is None or prev['estado'] != 'ok'
                cambio = not nuevo and tuple(prev)[:8] != datos
                db.execute("""INSERT INTO solicitudes_recuperadas(application_id, product_id, fulfillment_id, tipo, sku_id,
                              variante, main_order_id, estado_api, solicitada_at, estado, intentos, reintento_at,
                              actualizado_at) VALUES (?,?,?,?,?,?,?,?,?,'ok',0,NULL,?)
                              ON CONFLICT(application_id) DO UPDATE SET product_id=excluded.product_id,
                              fulfillment_id=excluded.fulfillment_id, tipo=excluded.tipo, sku_id=excluded.sku_id,
                              variante=excluded.variante, main_order_id=excluded.main_order_id,
                              estado_api=excluded.estado_api, solicitada_at=excluded.solicitada_at, estado='ok',
                              intentos=0, reintento_at=NULL, actualizado_at=excluded.actualizado_at""",
                           (aid, *datos, self.ahora))
                if nuevo or cambio:
                    self.alm.marcar_data_version(db)
            r.nuevos += int(nuevo)
            r.cambiados += int(cambio)
            r.exito()

    # ------------------------------------------------------------------ 2. elegibilidad de muestra (samples/labels)
    def _fase_etiquetas(self, r: ResultadoFase) -> None:
        filas = self._leer("""
            WITH x AS (SELECT product_id FROM vitrina UNION SELECT product_id FROM muestras
                       UNION SELECT product_id FROM solicitudes_recuperadas WHERE estado = 'ok'),
                 s AS (SELECT product_id, COUNT(*) AS n FROM orden_lineas GROUP BY product_id)
            SELECT x.product_id FROM x LEFT JOIN muestra_etiquetas e USING (product_id) LEFT JOIN s USING (product_id)
            WHERE e.product_id IS NULL
               OR e.consultado_at <= ? - CASE WHEN e.error_codigo IS NULL THEN ? ELSE ? END
            ORDER BY e.consultado_at IS NOT NULL, e.consultado_at, COALESCE(s.n, 0) DESC, x.product_id""",
                           (self.ahora, TTL_ETIQUETAS_S, TTL_ERROR_S))
        for pid in self._ids(filas, MAX_ETIQUETAS):
            try:
                d = self._llamar('GET', P_ETIQUETAS, {'product_id': pid})
            except ErrorApi as e:
                detener = self._falla_o_permiso(r, e)
                if r.estado == 'sin_permiso':
                    return
                with self._tx() as db:      # se reintenta a las 24 h; lo último bueno (si lo hay) se conserva
                    db.execute("""INSERT INTO muestra_etiquetas(product_id, error_codigo, consultado_at, actualizado_at)
                                  VALUES (?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET
                                  error_codigo=excluded.error_codigo, consultado_at=excluded.consultado_at""",
                               (pid, str(e.codigo), self.ahora, self.ahora))
                if detener:
                    return
                continue
            label = d.get('label') or {}
            skus = skus_muestra(label)
            datos = (_bool(label.get('can_apply')), norm_estado(label.get('status')),
                     str(label['application_id']) if label.get('application_id') else None,
                     _bool(label.get('reach_limit')), json.dumps(skus, ensure_ascii=False, separators=(',', ':')))
            h = huella(*datos)
            with self._tx() as db:
                prev = db.execute('SELECT huella FROM muestra_etiquetas WHERE product_id=?', (pid,)).fetchone()
                nuevo = prev is None or prev['huella'] is None
                cambio = not nuevo and prev['huella'] != h
                db.execute("""INSERT INTO muestra_etiquetas(product_id, puede_solicitar, estado, application_id,
                              limite_alcanzado, skus_json, error_codigo, consultado_at, huella, actualizado_at)
                              VALUES (?,?,?,?,?,?,NULL,?,?,?) ON CONFLICT(product_id) DO UPDATE SET
                              puede_solicitar=excluded.puede_solicitar, estado=excluded.estado,
                              application_id=excluded.application_id, limite_alcanzado=excluded.limite_alcanzado,
                              skus_json=excluded.skus_json, error_codigo=NULL, consultado_at=excluded.consultado_at,
                              huella=excluded.huella,
                              actualizado_at=CASE WHEN muestra_etiquetas.huella IS excluded.huella
                                                  THEN muestra_etiquetas.actualizado_at ELSE excluded.actualizado_at END""",
                           (pid, *datos, self.ahora, h, self.ahora))
                if nuevo or cambio:
                    self.alm.marcar_data_version(db)
            r.nuevos += int(nuevo)
            r.cambiados += int(cambio)
            r.exito()

    # ------------------------------------------------------------------ 3. planes dirigidos por tienda
    def _bajar_dirigidas(self, shop_id: str) -> list[dict[str, Any]]:
        colabs: list[dict[str, Any]] = []
        token, vistos, ids = None, set(), set()
        for _ in range(MAX_PAGINAS_DIRIGIDAS):
            q: dict[str, Any] = {'page_size': 50}
            if token:
                q['page_token'] = token
            d = self._llamar('POST', P_DIRIGIDAS, q, {'shop_id': shop_id})
            items = [c for c in (d.get('target_collaborations') or []) if isinstance(c, dict)]
            nuevos = [c for c in items if str(c.get('id')) not in ids]
            for c in nuevos:
                ids.add(str(c.get('id')))
                colabs.append(c)
            token = d.get('next_page_token') or ''
            if not items or not nuevos or not token or token in vistos:
                break
            vistos.add(token)
        return colabs

    def _fase_dirigidas(self, r: ResultadoFase) -> None:
        filas = self._leer("""
            SELECT s.shop_id FROM (SELECT DISTINCT shop_id FROM cumplimientos WHERE shop_id IS NOT NULL) s
            LEFT JOIN dirigidas_tiendas d USING (shop_id)
            WHERE d.shop_id IS NULL OR d.consultado_at <= ? - CASE WHEN d.error_codigo IS NULL THEN ? ELSE ? END
            ORDER BY d.consultado_at IS NOT NULL, d.consultado_at, s.shop_id""",
                           (self.ahora, TTL_DIRIGIDAS_S, TTL_ERROR_S))
        for sid in self._ids(filas, MAX_TIENDAS_DIRIGIDAS):
            try:
                colabs = self._bajar_dirigidas(sid)
            except ErrorApi as e:
                detener = self._falla_o_permiso(r, e)
                if r.estado == 'sin_permiso':
                    return
                with self._tx() as db:
                    db.execute("""INSERT INTO dirigidas_tiendas(shop_id, error_codigo, consultado_at) VALUES (?,?,?)
                                  ON CONFLICT(shop_id) DO UPDATE SET error_codigo=excluded.error_codigo,
                                  consultado_at=excluded.consultado_at""", (sid, str(e.codigo), self.ahora))
                if detener:
                    return
                continue
            nuevas: dict[tuple[str, str], tuple[Any, ...]] = {}
            for c in colabs:
                cid = str(c.get('id') or '')
                if not cid:
                    continue
                for p in c.get('products') or []:
                    pid = str((p or {}).get('id') or '')
                    if not RE_ID.match(pid):
                        continue
                    com = p.get('commission') or {}
                    nuevas[(cid, pid)] = (sid, c.get('name') or None, norm_estado(c.get('status')),
                                          _entero(com.get('rate')), parse_monto(com.get('amount')),
                                          com.get('currency') or None, p.get('title') or None)
            n_t = c_t = 0
            with self._tx() as db:
                previas = {(f['collab_id'], f['product_id']): tuple(f)[2:]
                           for f in db.execute("""SELECT collab_id, product_id, shop_id, nombre, estado, comision_bp,
                                                         comision_monto_centavos, moneda, titulo
                                                  FROM colaboraciones_dirigidas WHERE shop_id=?""", (sid,))}
                for k, fila in nuevas.items():
                    if previas.get(k) == fila:
                        continue
                    n_t += k not in previas
                    c_t += k in previas
                    db.execute("""INSERT OR REPLACE INTO colaboraciones_dirigidas(collab_id, product_id, shop_id, nombre,
                                  estado, comision_bp, comision_monto_centavos, moneda, titulo, actualizado_at)
                                  VALUES (?,?,?,?,?,?,?,?,?,?)""", (*k, *fila, self.ahora))
                for k in set(previas) - set(nuevas):
                    c_t += 1
                    db.execute('DELETE FROM colaboraciones_dirigidas WHERE collab_id=? AND product_id=?', k)
                db.execute("""INSERT INTO dirigidas_tiendas(shop_id, planes, error_codigo, consultado_at) VALUES (?,?,NULL,?)
                              ON CONFLICT(shop_id) DO UPDATE SET planes=excluded.planes, error_codigo=NULL,
                              consultado_at=excluded.consultado_at""", (sid, len(colabs), self.ahora))
                if n_t + c_t:
                    self.alm.marcar_data_version(db)
            r.nuevos += n_t
            r.cambiados += c_t
            r.exito()

    # ------------------------------------------------------------------ 4. parecidos del marketplace
    def _buscar_parecidos(self, palabras: list[str]) -> dict[str, Any]:
        """Primero {title_keywords: [palabras]}; si falla (sin ser de control ni «sin permiso»), como texto. La forma que
        funcionó se prueba primero el resto de la sync."""
        formas = ['lista', 'texto'] if getattr(self, '_forma_parecidos', 'lista') == 'lista' else ['texto', 'lista']
        error: ErrorApi | None = None
        for forma in formas:
            cuerpo = {'title_keywords': list(palabras) if forma == 'lista' else ' '.join(palabras)}
            try:
                d = self._llamar('POST', P_MARKETPLACE, {'page_size': MAX_PARECIDOS}, cuerpo)
                self._forma_parecidos = forma
                return d
            except ErrorApi as e:
                if self._error_de_control(e) or e.codigo in CODIGOS_SIN_PERMISO:
                    raise
                error = e
        assert error is not None
        raise error

    def _fase_parecidos(self, r: ResultadoFase) -> None:
        # Primero lo que nunca se consultó; luego vitrina, ventas y muestras; dentro de cada grupo, lo que más vende.
        filas = self._leer("""
            WITH x AS (SELECT product_id, 0 AS pri FROM vitrina UNION ALL SELECT product_id, 1 FROM orden_lineas
                       UNION ALL SELECT product_id, 2 FROM muestras),
                 y AS (SELECT product_id, MIN(pri) AS pri FROM x WHERE product_id IS NOT NULL GROUP BY product_id),
                 s AS (SELECT product_id, COUNT(*) AS n FROM orden_lineas GROUP BY product_id)
            SELECT y.product_id, COALESCE(p.titulo, v.titulo) AS titulo
            FROM y LEFT JOIN productos p USING (product_id) LEFT JOIN vitrina v USING (product_id)
                   LEFT JOIN parecidos_consultas c USING (product_id) LEFT JOIN s USING (product_id)
            WHERE COALESCE(p.titulo, v.titulo) IS NOT NULL
              AND (c.product_id IS NULL OR c.consultado_at <= ? - CASE WHEN c.error_codigo IS NULL THEN ? ELSE ? END)
            ORDER BY c.consultado_at IS NOT NULL, y.pri, COALESCE(s.n, 0) DESC, c.consultado_at, y.product_id""",
                           (self.ahora, TTL_PARECIDOS_S, TTL_ERROR_S))
        titulos = {str(f['product_id']): f['titulo'] for f in filas}
        for pid in self._ids(filas, MAX_PRODUCTOS_PARECIDOS):
            palabras = palabras_clave(titulos.get(pid))
            items: list[tuple[Any, ...]] = []
            if palabras:
                try:
                    d = self._buscar_parecidos(palabras)
                except ErrorApi as e:
                    detener = self._falla_o_permiso(r, e)
                    if r.estado == 'sin_permiso':
                        return
                    with self._tx() as db:
                        db.execute("""INSERT INTO parecidos_consultas(product_id, palabras_json, error_codigo, consultado_at)
                                      VALUES (?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET
                                      error_codigo=excluded.error_codigo, consultado_at=excluded.consultado_at""",
                                   (pid, json.dumps(palabras, ensure_ascii=False), str(e.codigo), self.ahora))
                    if detener:
                        return
                    continue
                vistos: set[str] = set()
                for p in d.get('products') or []:
                    if not isinstance(p, dict):
                        continue
                    otro = str(p.get('id') or '')
                    if not RE_ID.match(otro) or otro == pid or otro in vistos:
                        continue
                    vistos.add(otro)
                    com = p.get('commission') or {}
                    cmin, cmax = parse_rango(com.get('amount'))
                    op = p.get('original_price') or {}
                    items.append((otro, len(items), p.get('title') or None, (p.get('shop') or {}).get('name') or None,
                                  p.get('main_image_url') or None, parse_monto(op.get('minimum_amount')),
                                  parse_monto(op.get('maximum_amount')), _entero(com.get('rate')), cmin, cmax,
                                  _entero(p.get('units_sold')), p.get('detail_link') or None))
                    if len(items) >= MAX_PARECIDOS:
                        break
            h = huella(palabras, items)
            with self._tx() as db:
                prev = db.execute('SELECT huella FROM parecidos_consultas WHERE product_id=?', (pid,)).fetchone()
                nuevo = (prev is None or prev['huella'] is None) and bool(items)
                cambio = prev is not None and prev['huella'] is not None and prev['huella'] != h
                if prev is None or prev['huella'] != h:
                    db.execute('DELETE FROM productos_parecidos WHERE product_id=?', (pid,))
                    db.executemany("""INSERT INTO productos_parecidos(product_id, parecido_id, posicion, titulo,
                                      tienda_nombre, imagen_url, precio_min_centavos, precio_max_centavos, comision_bp,
                                      comision_monto_min_centavos, comision_monto_max_centavos, unidades_vendidas,
                                      enlace) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", [(pid, *it) for it in items])
                db.execute("""INSERT INTO parecidos_consultas(product_id, palabras_json, resultados, error_codigo,
                              consultado_at, huella) VALUES (?,?,?,NULL,?,?) ON CONFLICT(product_id) DO UPDATE SET
                              palabras_json=excluded.palabras_json, resultados=excluded.resultados, error_codigo=NULL,
                              consultado_at=excluded.consultado_at, huella=excluded.huella""",
                           (pid, json.dumps(palabras, ensure_ascii=False), len(items), self.ahora, h))
                if nuevo or cambio:
                    self.alm.marcar_data_version(db)
            # fotos de los parecidos: diferidas (solo se bajan si alguien abre la ficha)
            self._encolar([PedidoImagen('m', it[0], it[4], 2, 'parecido') for it in items if it[4]])
            r.nuevos += int(nuevo)
            r.cambiados += int(cambio)
            r.exito()


__all__ = ['FasesFicha', 'ResultadoFase', 'ORDEN_FASES', 'TEXTOS_FASES', 'palabras_clave', 'skus_muestra', 'main_order',
           'P_ETIQUETAS', 'P_DIRIGIDAS', 'P_MARKETPLACE', 'TTL_ETIQUETAS_S', 'TTL_PARECIDOS_S',
           'TTL_DIRIGIDAS_S', 'MAX_ETIQUETAS', 'MAX_PRODUCTOS_PARECIDOS', 'MAX_PARECIDOS', 'MAX_GALERIA',
           'CODIGOS_SIN_PERMISO']
