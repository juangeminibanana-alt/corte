"""Sincronizador con TikTok Shop (BUILD_SPEC C34/§6.3.2; 03 §2.6, §3.2, §4). Portado de spec/verificacion/motor_ref.py.

Orden de C34 (manda sobre 03 §4.1), con dos PUNTOS DE CONTROL:
  perfil → muestras → cumplimientos → productos (de las muestras) → [PC1: clasificación parcial + confirmar
  data_version + datos.cambiaron(muestras, tiendas, productos)] → ordenes (las 26 ventanas semanales más recientes, de la
  más reciente a la más antigua) → [PC2: ídem con (ordenes, tiendas, videos, productos, muestras)] → vitrina → detalles
  → ordenes_anteriores (el resto hasta 400 días; en incremental 'omitido') → productos_ventas → videos (portadas sin red,
  C4) → imagenes (encola faltantes/cambiadas) → clasificacion (final + muestras.en_cohorte_desde_at).
  Cada punto de control se publica ANTES de marcar 'ok' su paso: «cumplimientos y productos ok» (W3 [Continuar]) ya
  implica las muestras clasificadas (las debe_video y sus tiendas ya calculadas) y datos.cambiaron enviado.
  Las automáticas (origen 'auto' o 'arranque') se rechazan con ErrorDominio si la conexión está en reautorizar o
  cuenta_sin_region (03 §4.4), sin llamar a TikTok.

Invariantes (03 §2.6): nunca hay red dentro de una transacción ni con el escritor tomado; cada transacción de la sync
usa `almacen.escritor(epoca)` (si cambió la cuenta o se borraron los datos, ROLLBACK y se aborta); data_version sube
por transacción CONFIRMADA con cambios (dv_pendiente) y el `finally` confirma lo que quede. `imagenes.encolar()` se
llama después de confirmar la página (perfil, productos, vitrina), nunca dentro de una transacción.

Una sync a la vez, en su propio hilo; cancelación cooperativa (ContextoSync.cancelar: termina la página o ventana en
curso); reanudación de pedidos por el cursor de cobertura (sync_pasos 'ordenes'.cursor_json) si la anterior quedó
'error' (incluida 'interrumpida') o 'cancelada' hace < 1 h.

Nota de esquema: el CHECK de sync_pasos.paso (schema.sql v1, idéntico al de base_de_prueba) no admite
'productos_ventas' ni 'ordenes_anteriores'. Esos dos pasos se guardan en sync_ejecuciones.resumen_json['pasos_extra'];
los otros diez, en sync_pasos como siempre.

Rev. 4 (15/11/2026, ficha completa de producto): `productos_ventas` termina con las FASES de sincronizador_ficha.py
(solicitudes recuperadas desde su cumplimiento, elegibilidad de muestra, planes dirigidos, parecidos del marketplace y
origen de cada venta), con TTL y topes por sync. No son pasos nuevos de `PasoSync` (el contrato no cambia): sus cifras
van a resumen_json['fases'] y su avance ocupa la segunda mitad de `productos_ventas`. La vitrina guarda además la
galería (main_images[], fotos diferidas 'g:<id>-<n>'), status.inventory_status, platform_discount_price y el resto de
campos de showcases/products que ya llegaban; tras la migración a la rev. 4 se vuelve a leer una vez ('vitrina.rev').

Rev. 5 (15/11/2026, Display API): el paso «videos_tiktok» (sincronizador_videos.py) corre dentro del paso público
`videos`, después de las portadas C4, solo si hub.py enlazó el servicio (`fijar_display`) y hay conexión; si no, se salta
en silencio y el paso `videos` queda exactamente como en la rev. 4. `PasoSync` no cambia.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import threading
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import clasificador as cl
from . import planificador as plan
from .comun import fecha_local, huella, norm_estado, norm_tienda, parse_monto, parse_rango
from .errores import ErrorApi, ErrorAuthTransitorio, ErrorDominio, ErrorRed
from .interfaces import ContextoSync, Dependencias, Json, PedidoImagen, Sincronizador
from .sincronizador_ficha import MAX_GALERIA, ORDEN_FASES, TEXTOS_FASES, FasesFicha
from .sincronizador_videos import PasoVideosTikTok

_log = logging.getLogger('creatorhub.sincronizador')

# ------------------------------------------------------------------ rutas de la API de creador
P_PERFIL = '/affiliate_creator/202508/profiles'
P_MUESTRAS = '/affiliate_creator/202412/sample_applications/search'
P_DETALLE = '/affiliate_creator/202412/sample_applications/single_query'
P_CUMPL = '/affiliate_creator/202409/sample_applications/fulfillments/search'
P_PRODUCTOS = '/affiliate_creator/202509/open_collaborations/products'
P_ORDENES = '/affiliate_creator/202410/orders/search'
P_VITRINA = '/affiliate_creator/202405/showcases/products'

# ------------------------------------------------------------------ pasos (C34, §6.3.2)
ORDEN_PASOS: tuple[str, ...] = ('perfil', 'muestras', 'cumplimientos', 'productos', 'ordenes', 'vitrina', 'detalles',
                                'ordenes_anteriores', 'productos_ventas', 'videos', 'imagenes', 'clasificacion')
PASOS_TABLA: tuple[str, ...] = ('perfil', 'muestras', 'cumplimientos', 'detalles', 'productos', 'ordenes', 'vitrina',
                                'videos', 'imagenes', 'clasificacion')          # los que admite el CHECK de sync_pasos
PASOS_EXTRA: tuple[str, ...] = ('ordenes_anteriores', 'productos_ventas')
PESOS: dict[str, int] = {'perfil': 2, 'muestras': 15, 'cumplimientos': 5, 'productos': 4, 'ordenes': 28, 'vitrina': 2,
                         'detalles': 8, 'ordenes_anteriores': 24, 'productos_ventas': 4, 'videos': 2, 'imagenes': 2,
                         'clasificacion': 4}
PESO_DETALLES_SIN_PENDIENTES = 1
TEXTOS: dict[str, str] = {
    'perfil': 'Revisando tu perfil…',
    'muestras': 'Buscando tus muestras…',
    'cumplimientos': 'Revisando el estado de cada muestra…',
    'productos': 'Trayendo productos e imágenes…',
    'ordenes': 'Tus ventas recientes: semana {n} de {N}…',
    'vitrina': 'Revisando tu vitrina…',
    'detalles': 'Completando detalles de muestras…',
    'ordenes_anteriores': 'Ventas anteriores: semana {n} de {N}…',
    'productos_ventas': 'Trayendo fichas de productos de tus ventas…',
    'videos': 'Preparando portadas de tus videos…',
    'imagenes': 'Guardando imágenes…',
    'clasificacion': 'Ordenando tus pendientes…',
}
TEXTO_LISTO = 'Todo al día'
TEXTOS_FIN: dict[str, str] = {'cancelada': 'Sincronización cancelada', 'error': 'No se pudo terminar la sincronización'}
TEXTOS_ERROR: dict[str, str] = {
    'sin_internet': 'Sin conexión a internet', 'reautorizar': 'Conexión con TikTok vencida',
    'token_rechazado': 'Conexión con TikTok vencida', 'cuenta_sin_region': 'Tu cuenta no tiene permiso de ventas en México',
    'credenciales_cambiaron': 'Cambió la cuenta durante la sincronización', 'interrumpida': 'La sincronización se interrumpió',
    'renovacion_pendiente': 'No pudimos renovar la conexión; lo intentaremos de nuevo',
    'sin_credenciales': 'Conecta tu cuenta de TikTok para traer tus datos',
    'error_interno': 'Ocurrió un error interno al sincronizar'}
SECCIONES_PC1: tuple[str, ...] = ('muestras', 'tiendas', 'productos')
SECCIONES_PC2: tuple[str, ...] = ('ordenes', 'tiendas', 'videos', 'productos', 'muestras')
PUNTOS_DE_CONTROL: dict[str, tuple[int, tuple[str, ...]]] = {'productos': (1, SECCIONES_PC1), 'ordenes': (2, SECCIONES_PC2)}
SECCIONES_TIKTOK: tuple[str, ...] = ('muestras', 'ordenes', 'productos', 'tiendas', 'videos', 'cuenta')
SECCIONES_DE_PASO: dict[str, tuple[str, ...]] = {
    'perfil': ('cuenta',), 'muestras': ('muestras', 'tiendas'), 'cumplimientos': ('muestras', 'tiendas'),
    'productos': ('productos', 'muestras', 'tiendas'), 'ordenes': ('ordenes', 'tiendas', 'videos', 'productos'),
    'vitrina': ('productos', 'muestras'), 'detalles': ('muestras',),
    'ordenes_anteriores': ('ordenes', 'tiendas', 'videos', 'productos'),
    'productos_ventas': ('productos', 'tiendas', 'ordenes'), 'videos': ('videos',), 'imagenes': (),
    'clasificacion': ('muestras', 'tiendas')}

TIPOS: tuple[str, ...] = ('incremental', 'completa')
ORIGENES: tuple[str, ...] = ('auto', 'usuario', 'arranque', 'telefono', 'demo')
ORIGENES_AUTOMATICOS: tuple[str, ...] = ('auto', 'arranque')
SEMANA_S = 7 * 86400
DIA_S = 86400
VENTANAS_RECIENTES = 26
DIAS_HISTORIA = 400
BARRIDO_COMPLETO_CADA_S = 7 * DIA_S
REANUDAR_DENTRO_DE_S = 3600
INTERVALO_PROGRESO_S = 0.3
MAX_EJECUCIONES = 200
LOTE_PRODUCTOS = 20
SIN_REGION: frozenset[int] = frozenset({16015006, 16015007, 16504002, 18001405})
CODIGOS_OMITIR_PASO: frozenset[Any] = frozenset({105005, 16501011})
# Códigos que significan «parámetro inválido» (p. ej. un application_status que la API no acepta). La doc no los
# especifica: la lista es configurable (03 §2.1). -10005 es el que simula el transporte falso.
CODIGOS_VALIDACION: frozenset[Any] = frozenset({-10005})
RE_ID_IMAGEN = re.compile(r'^\d{1,25}$')
RE_REF_GALERIA = re.compile(r'^\d{1,25}-(?:\d|1[01])$')      # 'g:<product_id>-<n>' (rev. 4)
ESTADOS_VALIDOS: tuple[str, ...] = ('SETTLED', 'To-SETTLE', 'AWAITING PAYMENT')
REV_VITRINA = '4'                       # sync_cursores 'vitrina.rev': con otro valor la vitrina se vuelve a leer

_SQL_PORTADAS = f"""
WITH lv AS (
  SELECT l.content_id, l.product_id,
         COUNT(DISTINCT CASE WHEN o.estado IN {ESTADOS_VALIDOS!r} THEN l.order_id END)           AS pedidos_validos,
         SUM(CASE WHEN o.estado IN {ESTADOS_VALIDOS!r} THEN COALESCE(l.com_estimada_centavos, 0) ELSE 0 END)
                                                                                                  AS comision_estimada,
         MIN(CASE WHEN o.estado IN {ESTADOS_VALIDOS!r} THEN o.creada_at END)                      AS primera_venta_at
  FROM orden_lineas l JOIN ordenes o USING (order_id)
  WHERE l.tipo_contenido = 'VIDEO' AND l.content_id IS NOT NULL AND l.product_id IS NOT NULL
  GROUP BY l.content_id, l.product_id),
r AS (
  SELECT content_id, product_id,
         MIN(primera_venta_at) OVER (PARTITION BY content_id)                                     AS primera_venta_at,
         ROW_NUMBER() OVER (PARTITION BY content_id
                            ORDER BY pedidos_validos DESC, comision_estimada DESC,
                                     length(product_id), product_id)                              AS rn
  FROM lv)
SELECT content_id, product_id, primera_venta_at FROM r WHERE rn = 1 ORDER BY content_id
"""
_SQL_COHORTE = f"""
UPDATE muestras SET en_cohorte_desde_at = ?
WHERE en_cohorte_desde_at IS NULL
  AND application_id IN (SELECT application_id FROM v_muestras WHERE grupo IN {tuple(sorted(cl.GRUPOS_PENDIENTES))!r})
"""
_SQL_NUEVAS_POR_VENCER = """
SELECT v.application_id FROM v_muestras v JOIN muestras m USING (application_id)
WHERE v.grupo = 'por_vencer' AND m.en_cohorte_desde_at = ?
ORDER BY v.fecha_limite_at, v.application_id
"""


class _Cancelada(Exception):
    """La sincronización se canceló (ContextoSync.cancelar)."""


def huella_url(url: str | None) -> str | None:
    """sha1(host + path) sin la query volátil (x-expires): la misma imagen no cambia de huella (03 §2.3)."""
    if not url:
        return None
    u = urllib.parse.urlsplit(url)
    return hashlib.sha1(((u.hostname or '') + u.path).encode('utf-8')).hexdigest()


def urls_galeria(main_images: Any) -> list[str]:
    """URLs de showcases/products main_images[] (≈ 9 por producto), en su orden, máx. MAX_GALERIA."""
    out: list[str] = []
    for i in main_images if isinstance(main_images, list) else []:
        u = i.get('url') if isinstance(i, dict) else None
        if isinstance(u, str) and u:
            out.append(u)
        if len(out) >= MAX_GALERIA:
            break
    return out


def huella_galeria(galeria_json: str | None) -> list[str | None]:
    """La galería por host + path: una firma nueva en la query no es un cambio (se actualiza sin contarlo)."""
    try:
        urls = json.loads(galeria_json) if galeria_json else []
    except ValueError:
        urls = []
    return [huella_url(u) for u in urls if isinstance(u, str)]


def ventanas(desde: int, hasta_excl: int) -> list[tuple[int, int]]:
    """Ventanas semanales [ge, lt) desde `desde` hacia adelante (los mismos bordes que motor_ref), la última recortada."""
    out, t = [], desde
    while t < hasta_excl:
        out.append((t, min(t + SEMANA_S, hasta_excl)))
        t += SEMANA_S
    return out


def restar_cobertura(lista: list[tuple[int, int]], cubierto: tuple[int, int] | None) -> list[tuple[str, int, int]]:
    """Segmentos de la más reciente a la más antigua: ('bajar', ge, lt) lo que falta y ('cubierto', ge, lt) lo que la
    corrida anterior ya bajó completo."""
    out: list[tuple[str, int, int]] = []
    for ge, lt in sorted(lista, key=lambda v: -v[0]):
        if cubierto is None:
            out.append(('bajar', ge, lt))
            continue
        d, t = cubierto
        if lt > t:
            out.append(('bajar', max(ge, t), lt))
        if min(lt, t) > max(ge, d):
            out.append(('cubierto', max(ge, d), min(lt, t)))
        if ge < d:
            out.append(('bajar', ge, min(lt, d)))
    return out


def _paso_vacio(paso: str) -> dict[str, Any]:
    return {'paso': paso, 'estado': 'pendiente', 'hechos': 0, 'total': None, 'nuevos': 0, 'cambiados': 0, 'error': None}


@dataclass
class _Corrida:
    """Estado en memoria de una sincronización (SyncEstado.en_curso sale de aquí, nunca de la tabla)."""
    sync_id: int
    tipo: str
    origen: str
    iniciada_at: int
    ahora: int
    ctx: ContextoSync
    pasos: dict[str, dict[str, Any]] = field(default_factory=dict)
    fraccion: dict[str, float] = field(default_factory=dict)
    pesos: dict[str, int] = field(default_factory=lambda: dict(PESOS))
    paso_actual: str | None = None
    texto: str = ''
    progreso: float = 0.0
    terminada: bool = False
    estado_final: str | None = None
    error: dict[str, Any] | None = None
    hilo: threading.Thread | None = None
    fin: threading.Event = field(default_factory=threading.Event)


class _Sincronizador(FasesFicha, PasoVideosTikTok):
    """Implementa `Sincronizador` (interfaces.py). Las fases de la ficha completa (rev. 4) vienen de FasesFicha y el
    paso «videos_tiktok» de la Display API (rev. 5), de PasoVideosTikTok (`fijar_display`)."""

    def __init__(self, dep: Dependencias) -> None:
        self.dep = dep
        self.alm = dep.almacen
        self.cli = dep.cliente
        self.bus = dep.bus
        self.reloj = dep.reloj
        self.imagenes = dep.imagenes
        self.boveda = dep.boveda
        self.config = dep.config
        self.codigos_validacion = set(CODIGOS_VALIDACION)
        self._candado = threading.Lock()
        self._actual: _Corrida | None = None
        self._ultima: _Corrida | None = None
        self._ultimo_progreso_t = -1e18
        # estado de la corrida (solo lo toca el hilo de la sync)
        self._c: _Corrida | None = None

    # ================================================================== API pública (Protocol)
    def iniciar(self, tipo: str, origen: str) -> Json:
        if tipo not in TIPOS:
            raise ErrorDominio('parametros_invalidos', 'El tipo de sincronización no es válido.')
        if origen not in ORIGENES:
            raise ErrorDominio('parametros_invalidos', 'El origen de la sincronización no es válido.')
        with self._candado:
            actual = self._actual
            if actual is not None and not actual.terminada:
                return {'sync_id': actual.sync_id, 'ya_en_curso': True, 'estado': self._estado_sin_candado()}
            if self.alm.solo_lectura():
                raise ErrorDominio('base_de_version_nueva', 'Esta base es de una versión más nueva de Corte. '
                                   'Actualiza Corte para seguir sincronizando.', http=409)
            if not self.boveda.tiene_tokens():
                raise ErrorDominio('sin_credenciales', 'Conecta tu cuenta de TikTok para traer tus datos.', http=409)
            self._validar_automatica(origen)
            tipo = self._tipo_efectivo(tipo, origen)
            corrida = self._crear_corrida(tipo, origen)
            self._actual = corrida
            hilo = threading.Thread(target=self._correr, args=(corrida,), name=f'sync-{corrida.sync_id}', daemon=True)
            corrida.hilo = hilo
            respuesta = {'sync_id': corrida.sync_id, 'ya_en_curso': False, 'estado': self._estado_sin_candado()}
        hilo.start()
        return respuesta

    def estado(self) -> Json:
        with self._candado:
            return self._estado_sin_candado()

    def cancelar(self, esperar_s: float = 40.0) -> None:
        with self._candado:
            corrida = self._actual
        if corrida is None or corrida.terminada:
            return
        corrida.ctx.cancelar.set()
        corrida.fin.wait(max(0.0, esperar_s))

    def esperar(self, tope_s: float = 60.0) -> bool:
        """Espera a que termine la sync en curso (si hay). True si no queda ninguna en curso. No es del Protocol."""
        with self._candado:
            corrida = self._actual
        if corrida is None:
            return True
        return corrida.fin.wait(max(0.0, tope_s))

    def ejecutar(self, tipo: str, origen: str) -> int:
        """Sincroniza en ESTE hilo y devuelve el sync_id (pruebas y herramientas). Respeta «una sync a la vez»."""
        if tipo not in TIPOS or origen not in ORIGENES:
            raise ErrorDominio('parametros_invalidos', 'Tipo u origen de sincronización no válidos.')
        with self._candado:
            if self._actual is not None and not self._actual.terminada:
                raise ErrorDominio('conflicto', 'Ya hay una sincronización en curso.', http=409)
            self._validar_automatica(origen)
            corrida = self._crear_corrida(self._tipo_efectivo(tipo, origen), origen)
            self._actual = corrida
        self._correr(corrida)
        return corrida.sync_id

    def historial(self, limite: int = 20) -> Json:
        limite = max(1, min(200, int(limite)))
        with self.alm.lector() as db:
            filas = db.execute('SELECT * FROM sync_ejecuciones ORDER BY sync_id DESC LIMIT ?', (limite,)).fetchall()
        items = []
        for f in filas:
            try:
                resumen_crudo = json.loads(f['resumen_json'] or '{}')
            except ValueError:
                resumen_crudo = {}
            resumen = {p: {'nuevos': int(v.get('nuevos', 0)), 'cambiados': int(v.get('cambiados', 0)),
                           'hechos': int(v.get('hechos', 0))}
                       for p, v in resumen_crudo.items() if p in ORDEN_PASOS and isinstance(v, dict)}
            terminada = f['terminada_at']
            items.append({
                'sync_id': f['sync_id'], 'tipo': f['tipo'], 'origen': f['origen'], 'estado': f['estado'],
                'iniciada_at': f['iniciada_at'], 'terminada_at': terminada,
                'duracion_s': (terminada - f['iniciada_at']) if terminada is not None else None,
                'llamadas_api': f['llamadas_api'], 'reintentos': f['reintentos'], 'cambios': f['cambios'],
                'resumen': resumen,
                'error': ({'codigo': f['error_codigo'], 'mensaje': f['error_mensaje'] or ''}
                          if f['error_codigo'] else None)})
        return {'items': items}

    def cobertura(self) -> Json:
        with self.alm.lector() as db:
            uno = lambda sql, *a: db.execute(sql, a).fetchone()  # noqa: E731
            perfil = uno('SELECT COUNT(*) FROM cuenta')[0] > 0
            muestras = uno('SELECT COUNT(*) FROM muestras')[0]
            cumplimientos = uno('SELECT COUNT(DISTINCT application_id) FROM cumplimientos')[0]
            detalles = uno("SELECT COUNT(*) FROM muestras WHERE detalle_estado = 'ok'")[0]
            con_imagen = uno("""SELECT COUNT(DISTINCT m.product_id) FROM muestras m
                                JOIN imagenes i ON i.img_key = 'p:' || m.product_id AND i.estado = 'ok'""")[0]
            fichas = uno("""SELECT COUNT(DISTINCT l.product_id),
                                   COUNT(DISTINCT CASE WHEN p.origen = 'api' THEN l.product_id END)
                            FROM orden_lineas l LEFT JOIN productos p USING (product_id)""")
            pedidos = uno("SELECT COUNT(*), MIN(creada_at) FROM ordenes WHERE estado <> 'NO_DEVUELTA'")
            vit_err = uno("SELECT valor FROM sync_cursores WHERE clave = 'vitrina.error'")
            vit_ok = uno("SELECT valor FROM sync_cursores WHERE clave = 'vitrina.at'")
            vitrina = None if (vit_err is not None or vit_ok is None) else uno('SELECT COUNT(*) FROM vitrina')[0]
            portadas = uno("""SELECT COUNT(*),
                                     COUNT(CASE WHEN i.estado = 'ok' THEN 1 END)
                              FROM videos v LEFT JOIN imagenes i ON i.img_key = 'v:' || v.content_id""")
        return {'perfil': perfil, 'muestras': muestras, 'cumplimientos': cumplimientos, 'detalles': detalles,
                'productos_con_imagen': con_imagen, 'fichas_ventas': {'con_ficha': fichas[1], 'total': fichas[0]},
                'pedidos': pedidos[0], 'pedidos_desde': fecha_local(pedidos[1]) if pedidos[1] else None,
                'vitrina': vitrina, 'portadas_videos': {'con_foto': portadas[1], 'total': portadas[0]}}

    # ================================================================== estado (SyncEstado)
    def _estado_sin_candado(self) -> Json:
        c = self._actual if self._actual is not None and not self._actual.terminada else None
        ultimo = self._ultimo_terminado()
        base = {'en_curso': c is not None, 'sync_id': None, 'tipo': None, 'origen': None, 'progreso': 0.0,
                'paso_actual': None, 'texto': '', 'pasos': [], 'iniciada_at': None,
                'ultima_ok_at': ultimo['ultima_ok_at'], 'ultima_estado': ultimo['ultima_estado'],
                'proxima_auto_at': self._proxima_auto(ultimo), 'ultimo_error': ultimo['ultimo_error']}
        corrida = c or self._ultima
        if corrida is not None:
            base.update(sync_id=corrida.sync_id, tipo=corrida.tipo, origen=corrida.origen,
                        progreso=round(corrida.progreso, 4), paso_actual=corrida.paso_actual if c else None,
                        texto=corrida.texto, iniciada_at=corrida.iniciada_at,
                        pasos=[copy.deepcopy(corrida.pasos[p]) for p in ORDEN_PASOS if p in corrida.pasos])
        elif ultimo['sync_id'] is not None:
            base.update(sync_id=ultimo['sync_id'], tipo=ultimo['tipo'], origen=ultimo['origen'],
                        progreso=1.0 if ultimo['ultima_estado'] in ('ok', 'parcial') else 0.0,
                        texto=ultimo['texto'], iniciada_at=ultimo['iniciada_at'], pasos=ultimo['pasos'])
        return base

    def _ultimo_terminado(self) -> dict[str, Any]:
        vacio = {'sync_id': None, 'tipo': None, 'origen': None, 'iniciada_at': None, 'ultima_ok_at': None,
                 'ultima_estado': None, 'ultimo_error': None, 'terminada_at': None, 'codigo': None, 'fallos': 0,
                 'texto': '', 'pasos': [], 'auth_estado': None}
        try:
            with self.alm.lector() as db:
                filas = db.execute("""SELECT sync_id, tipo, origen, estado, iniciada_at, terminada_at, error_codigo,
                                             error_mensaje, resumen_json FROM sync_ejecuciones
                                      WHERE estado <> 'en_curso' ORDER BY sync_id DESC LIMIT 12""").fetchall()
                ok = db.execute("SELECT MAX(terminada_at) FROM sync_ejecuciones WHERE estado IN ('ok','parcial')"
                                ).fetchone()[0]
                auth = db.execute('SELECT estado FROM auth_estado WHERE id = 1').fetchone()
                pasos = self._pasos_de_bd(db, filas[0]) if filas else []
        except Exception:                                       # almacén cerrado (apagado): solo memoria
            _log.debug('No se pudo leer el historial de syncs', exc_info=True)
            return vacio
        out = dict(vacio, ultima_ok_at=ok, auth_estado=auth[0] if auth else None, pasos=pasos)
        if not filas:
            return out
        f = filas[0]
        fallos = 0
        for g in filas:
            if g['estado'] == 'error' and g['error_codigo'] in plan.CODIGOS_REINTENTO:
                fallos += 1
            else:
                break
        estado = f['estado']
        out.update(sync_id=f['sync_id'], tipo=f['tipo'] if f['tipo'] in TIPOS else 'completa', origen=f['origen'],
                   iniciada_at=f['iniciada_at'], ultima_estado=estado, terminada_at=f['terminada_at'],
                   codigo=f['error_codigo'] if estado == 'error' else None, fallos=fallos,
                   texto=(TEXTO_LISTO if estado in ('ok', 'parcial')
                          else TEXTOS_ERROR.get(f['error_codigo'] or '', TEXTOS_FIN.get(estado, ''))))
        if estado == 'error' and f['error_codigo']:
            out['ultimo_error'] = {'codigo': f['error_codigo'], 'mensaje': f['error_mensaje'] or '',
                                   'at': f['terminada_at'] or f['iniciada_at']}
        return out

    def _pasos_de_bd(self, db: Any, ejecucion: Any) -> list[Json]:
        filas = {r['paso']: r for r in db.execute('SELECT * FROM sync_pasos WHERE sync_id = ?', (ejecucion['sync_id'],))}
        try:
            extra = (json.loads(ejecucion['resumen_json'] or '{}') or {}).get('pasos_extra') or {}
        except ValueError:
            extra = {}
        out = []
        for p in ORDEN_PASOS:
            if p in filas:
                r = filas[p]
                out.append({'paso': p, 'estado': r['estado'], 'hechos': r['hechos'], 'total': r['total'],
                            'nuevos': r['nuevos'], 'cambiados': r['cambiados'],
                            'error': ({'codigo': r['error_codigo'], 'mensaje': r['error_mensaje'] or ''}
                                      if r['error_codigo'] else None)})
            elif p in extra:
                e = extra[p]
                out.append({'paso': p, 'estado': e.get('estado', 'pendiente'), 'hechos': e.get('hechos', 0),
                            'total': e.get('total'), 'nuevos': e.get('nuevos', 0), 'cambiados': e.get('cambiados', 0),
                            'error': e.get('error')})
        return out

    def _proxima_auto(self, ultimo: dict[str, Any]) -> int | None:
        try:
            ajustes = self.config.leer('ajustes_pc', {}) or {}
        except Exception:
            ajustes = {}
        return plan.calcular_proxima_auto(
            sync_auto=bool(ajustes.get('sync_auto', plan.SYNC_AUTO_OMISION)),
            intervalo_min=int(ajustes.get('sync_intervalo_min', plan.INTERVALO_OMISION_MIN)),
            ultimo_fin_at=ultimo['terminada_at'], ultimo_codigo=ultimo['codigo'], fallos_seguidos=ultimo['fallos'],
            auth_estado=ultimo['auth_estado'])

    # ================================================================== preparación
    def _leer_cursor(self, clave: str) -> str | None:
        with self.alm.lector() as db:
            r = db.execute('SELECT valor FROM sync_cursores WHERE clave = ?', (clave,)).fetchone()
        return r[0] if r else None

    def _validar_automatica(self, origen: str) -> None:
        """03 §4.4: con la conexión en `reautorizar` o `cuenta_sin_region` no hay syncs AUTOMÁTICAS (temporizador ni
        arranque). Red de seguridad para el arranque, cuando el planificador todavía no oyó ningún conexion.cambio: la
        rechaza sin llamar a TikTok (el planificador se suspende al recibir este ErrorDominio)."""
        if origen not in ORIGENES_AUTOMATICOS:
            return
        with self.alm.lector() as db:
            fila = db.execute('SELECT estado FROM auth_estado WHERE id = 1').fetchone()
        estado = fila[0] if fila else None
        if estado == 'reautorizar':
            raise ErrorDominio('reautorizar', 'Tu conexión con TikTok venció. Vuelve a conectarla para que tus datos '
                               'se actualicen solos.', http=409)
        if estado == 'cuenta_sin_region':
            raise ErrorDominio('sin_permiso_tiktok', 'Tu cuenta no tiene permiso de ventas en México.', http=409)

    def _tipo_efectivo(self, tipo: str, origen: str) -> str:
        """03 §4.4: la automática y la de arranque son completas si nunca hubo barrido completo o tiene > 7 días."""
        if tipo == 'incremental' and origen in ('auto', 'arranque'):
            barrido = self._leer_cursor('ordenes.barrido_completo_at')
            if barrido is None or self.reloj.ahora() - int(barrido) > BARRIDO_COMPLETO_CADA_S:
                return 'completa'
        return tipo

    def _crear_corrida(self, tipo: str, origen: str) -> _Corrida:
        ahora = self.reloj.ahora()
        with self.alm.escritor() as db:
            sid = db.execute('INSERT INTO sync_ejecuciones(tipo, origen, estado, iniciada_at) VALUES (?,?,?,?)',
                             (tipo, origen, 'en_curso', ahora)).lastrowid
            for i, p in enumerate(p for p in ORDEN_PASOS if p in PASOS_TABLA):
                db.execute("INSERT INTO sync_pasos(sync_id, paso, orden, estado) VALUES (?,?,?,'pendiente')", (sid, p, i))
        epoca = self.alm.epoca()
        b = self.boveda.leer()
        ctx = ContextoSync(sync_id=sid, open_id=b.get('open_id'), epoca_credenciales=int(b.get('epoca_credenciales') or 0),
                           epoca_datos=epoca)
        corrida = _Corrida(sync_id=sid, tipo=tipo, origen=origen, iniciada_at=ahora, ahora=ahora, ctx=ctx)
        for p in ORDEN_PASOS:
            corrida.pasos[p] = _paso_vacio(p)
            corrida.fraccion[p] = 0.0
        if tipo == 'incremental':                       # no cuenta en el progreso: ya se sabe que se omite
            corrida.pesos['ordenes_anteriores'] = 0
        corrida.texto = TEXTOS['perfil']
        return corrida

    # ================================================================== corrida
    def _correr(self, c: _Corrida) -> None:
        self._c = c
        self.epoca = c.ctx.epoca_datos
        self.ahora = c.ahora
        self.sid = c.sync_id
        self.tipo = c.tipo
        self.cambios = 0
        self.resumen: dict[str, Any] = {}
        self.parciales: set[str] = set()
        self.secciones: set[str] = set()
        self._cobertura: tuple[int, int] | None = None
        self._segmentos: dict[str, list[tuple[str, int, int]]] = {}
        self._cursor_desde: int | None = None
        self._tope: int | None = None
        self._productos_de_esta_sync: set[str] = set()
        self._nuevas_en_esta_sync: set[str] = set()
        self._escala: dict[str, tuple[float, float]] = {}      # paso -> (base, factor) del avance (fases de la ficha)
        self._forma_parecidos = 'lista'
        self._error_fatal: ErrorApi | None = None
        self._ultimo_progreso_t = -1e18
        estado_final, err, codigo_err, mensaje_err = 'ok', None, None, None
        try:
            self._publicar_progreso(forzar=True)
            for paso in ORDEN_PASOS:
                self._comprobar_cancelacion()
                if paso == 'ordenes_anteriores' and c.tipo == 'incremental':
                    self._marcar(paso, 'omitido')
                    continue
                if paso == 'vitrina' and c.tipo == 'incremental' and not self._vitrina_vencida():
                    self._marcar(paso, 'omitido')
                    continue
                resultado = self._correr_paso(paso)
                if resultado == 'fatal':
                    estado_final = 'error'
                    err = self._error_fatal
                    break
                if resultado == 'cancelada':
                    raise _Cancelada()
                if resultado == 'parcial':
                    estado_final = 'parcial'
        except _Cancelada:
            estado_final = 'cancelada'
            if c.paso_actual and c.pasos[c.paso_actual]['estado'] == 'en_curso':
                self._marcar(c.paso_actual, 'omitido', error={'codigo': 'cancelada',
                                                             'mensaje': 'Se canceló la sincronización'})
        except ErrorApi as e:                           # p. ej. credenciales_cambiaron en un punto de control
            estado_final, err = 'error', e
        except Exception:
            _log.exception('Error interno durante la sincronización %s', c.sync_id)
            estado_final, codigo_err, mensaje_err = 'error', 'error_interno', TEXTOS_ERROR['error_interno']
            if c.paso_actual and c.pasos[c.paso_actual]['estado'] == 'en_curso':
                try:                                    # el paso no queda «en curso» para siempre
                    self._marcar(c.paso_actual, 'error', error={'codigo': codigo_err, 'mensaje': mensaje_err},
                                 terminado_at=self.reloj.ahora())
                except Exception:
                    _log.exception('No se pudo marcar el paso %s con error', c.paso_actual)
        finally:
            if err is not None:
                codigo_err = self._codigo_error(err)
                # texto para la persona (los de TikTok vienen en inglés); si no hay uno propio, el mensaje limpio
                mensaje_err = TEXTOS_ERROR.get(codigo_err) or err.mensaje
            self._cerrar_corrida(c, estado_final, codigo_err, mensaje_err)

    def _correr_paso(self, paso: str) -> str:
        """Ejecuta un paso con su contabilidad. Devuelve 'ok' | 'parcial' | 'omitido' | 'fatal' | 'cancelada'."""
        c = self._c
        assert c is not None
        with self._candado:
            c.paso_actual = paso
            # «Tus ventas recientes: semana {n} de {N}…»: hasta conocer N se muestra solo «Tus ventas recientes…»
            c.texto = TEXTOS[paso].split(':')[0] + '…' if '{' in TEXTOS[paso] else TEXTOS[paso]
        self._marcar(paso, 'en_curso', iniciado_at=self.reloj.ahora())
        ll0, re0 = c.ctx.llamadas, c.ctx.reintentos
        try:
            nuevos, camb, hechos = getattr(self, f'_paso_{paso}')()
            if nuevos + camb:
                self.secciones.update(SECCIONES_DE_PASO.get(paso, ()))
            if paso in PUNTOS_DE_CONTROL:
                # ANTES de marcar el paso 'ok': «cumplimientos y productos ok» (W3 [Continuar]) ya implica el punto de
                # control publicado, sin una ventana en la que la interfaz lea muestras sin clasificar.
                self._punto_control(*PUNTOS_DE_CONTROL[paso])
        except _Cancelada:
            raise
        except ErrorRed as e:                            # el cliente no debería dejarla escapar: sin internet
            if c.ctx.cancelar.is_set():
                return 'cancelada'
            self._error_fatal = ErrorApi(-1, f'Sin conexión ({type(e).__name__})', 'abortar', transitorio=True)
            self._terminar_paso(paso, 'error', ll0, re0, error=self._error_fatal)
            return 'fatal'
        except ErrorApi as e:
            if c.ctx.cancelar.is_set():
                return 'cancelada'
            # Una renovación transitoria que se escape del cliente (ErrorAuthTransitorio) también detiene la sync: el
            # planificador la reintenta (renovacion_pendiente, 03 §4.4).
            fatal = e.decision in ('reautorizar', 'abortar') or isinstance(e, ErrorAuthTransitorio)
            self._terminar_paso(paso, 'error' if fatal else 'omitido', ll0, re0, error=e)
            if fatal:
                self._error_fatal = e
                self._actualizar_auth(e)
                return 'fatal'
            if paso == 'vitrina':
                self._poner_cursor_tx('vitrina.error', str(self.ahora))
            if paso in PUNTOS_DE_CONTROL:       # el paso se omitió (p. ej. sin permiso): el punto de control igual sale
                self._punto_control(*PUNTOS_DE_CONTROL[paso])
            return 'parcial'
        est = 'parcial' if paso in self.parciales else 'ok'
        self._terminar_paso(paso, est, ll0, re0, nuevos=nuevos, cambiados=camb, hechos=hechos)
        self.resumen[paso] = {'nuevos': nuevos, 'cambiados': camb, 'hechos': hechos}
        return est

    def _cerrar_corrida(self, c: _Corrida, estado_final: str, codigo: str | None, mensaje: str | None) -> None:
        dv_nuevo = None
        try:
            dv_nuevo = self.alm.confirmar_data_version()
            if dv_nuevo is not None:
                self.bus.notificar_cambio(self.alm.versiones(), sorted(self.secciones) or list(SECCIONES_TIKTOK))
        except Exception:
            _log.exception('No se pudo confirmar data_version al cerrar la sync %s', c.sync_id)
        try:
            dv_final = self.alm.versiones()[0]
            with self.alm.escritor() as db:
                db.execute("""UPDATE sync_ejecuciones SET estado=?, terminada_at=?, llamadas_api=?, reintentos=?, cambios=?,
                              resumen_json=?, error_codigo=?, error_mensaje=?, data_version_final=? WHERE sync_id=?""",
                           (estado_final, self.reloj.ahora(), c.ctx.llamadas, c.ctx.reintentos, self.cambios,
                            json.dumps(self.resumen, ensure_ascii=False), codigo, mensaje, dv_final, c.sync_id))
                db.execute('DELETE FROM sync_ejecuciones WHERE sync_id <= (SELECT MAX(sync_id) - ? FROM sync_ejecuciones)',
                           (MAX_EJECUCIONES,))
        except Exception:
            _log.exception('No se pudo guardar el final de la sync %s', c.sync_id)
        with self._candado:
            c.estado_final = estado_final
            c.paso_actual = None
            if estado_final in ('ok', 'parcial'):
                c.progreso = 1.0
                c.texto = TEXTO_LISTO
            else:
                c.texto = TEXTOS_ERROR.get(codigo or '', TEXTOS_FIN.get(estado_final, ''))
            c.error = {'codigo': codigo, 'mensaje': mensaje or ''} if codigo else None
            c.terminada = True
            self._ultima = c
            estado = self._estado_sin_candado()
        self._c = None
        c.fin.set()
        try:
            self.bus.publicar({'tipo': 'sync.fin', 'estado': estado})
        except Exception:
            _log.exception('No se pudo publicar sync.fin')

    @staticmethod
    def _codigo_error(e: ErrorApi) -> str:
        if e.codigo in (-1, 'sin_internet'):
            return 'sin_internet'
        if e.codigo in SIN_REGION:
            return 'cuenta_sin_region'
        if e.decision == 'reautorizar' and e.codigo != 'credenciales_cambiaron':
            return 'reautorizar'
        return str(e.codigo)

    def _actualizar_auth(self, e: ErrorApi) -> None:
        """Como motor_ref: un `reautorizar` definitivo o un error de región dejan auth_estado en ese estado (el cliente
        de hub-nucleo también lo hace y publica conexion.cambio; aquí solo se asegura el estado)."""
        nuevo = None
        if e.codigo in SIN_REGION:
            nuevo = 'cuenta_sin_region'
        elif e.decision == 'reautorizar' and e.codigo != 'credenciales_cambiaron':
            nuevo = 'reautorizar'
        if nuevo is None:
            return
        try:
            with self.alm.escritor() as db:
                db.execute('UPDATE auth_estado SET estado=?, ultimo_error_codigo=?, ultimo_error_mensaje=?, actualizado_at=? '
                           'WHERE id=1', (nuevo, e.codigo if isinstance(e.codigo, int) else None, e.mensaje,
                                          self.reloj.ahora()))
        except Exception:
            _log.exception('No se pudo actualizar auth_estado')

    # ================================================================== contabilidad de pasos y progreso
    def _marcar(self, paso: str, estado: str, error: dict[str, Any] | None = None, **campos: Any) -> None:
        c = self._c
        assert c is not None
        with self._candado:
            c.pasos[paso]['estado'] = estado
            if error is not None:
                c.pasos[paso]['error'] = error
            if estado in ('ok', 'parcial', 'omitido', 'error'):
                c.fraccion[paso] = 1.0
        self._guardar_paso(paso, estado, error=error, **campos)
        self._publicar_progreso()

    def _terminar_paso(self, paso: str, estado: str, ll0: int, re0: int, error: ErrorApi | None = None,
                       nuevos: int = 0, cambiados: int = 0, hechos: int | None = None) -> None:
        c = self._c
        assert c is not None
        with self._candado:
            p = c.pasos[paso]
            p['nuevos'], p['cambiados'] = nuevos, cambiados
            if hechos is not None:
                p['hechos'] = hechos
        err = {'codigo': str(error.codigo), 'mensaje': error.mensaje} if error is not None else None
        self._marcar(paso, estado, error=err, terminado_at=self.reloj.ahora(), nuevos=nuevos, cambiados=cambiados,
                     hechos=c.pasos[paso]['hechos'], total=c.pasos[paso]['total'],
                     llamadas=c.ctx.llamadas - ll0, reintentos=c.ctx.reintentos - re0)

    def _guardar_paso(self, paso: str, estado: str, error: dict[str, Any] | None = None, **campos: Any) -> None:
        c = self._c
        assert c is not None
        if error is not None:
            campos['error_codigo'] = error['codigo']
            campos['error_mensaje'] = error['mensaje']
        if paso in PASOS_TABLA:
            columnas = ['estado', *campos]
            sets = ', '.join(f'{k}=?' for k in columnas)        # nombres de columnas fijos de este módulo
            with self.alm.escritor() as db:
                db.execute(f'UPDATE sync_pasos SET {sets} WHERE sync_id=? AND paso=?',
                           (estado, *campos.values(), c.sync_id, paso))
            return
        extra = self.resumen.setdefault('pasos_extra', {})
        e = extra.setdefault(paso, {})
        e.update({k: v for k, v in campos.items() if k not in ('error_codigo', 'error_mensaje')})
        e['estado'] = estado
        if error is not None:
            e['error'] = dict(error)
        with self.alm.escritor() as db:
            db.execute('UPDATE sync_ejecuciones SET resumen_json=? WHERE sync_id=?',
                       (json.dumps(self.resumen, ensure_ascii=False), c.sync_id))

    def _avance(self, paso: str, fraccion: float, hechos: int | None = None, total: int | None = None,
                texto: str | None = None) -> None:
        c = self._c
        assert c is not None
        escala = getattr(self, '_escala', {}).get(paso)
        if escala is not None:                          # rev. 4: tramo del paso que ocupa una fase de la ficha
            fraccion = escala[0] + escala[1] * min(1.0, max(0.0, fraccion))
        with self._candado:
            c.fraccion[paso] = max(c.fraccion.get(paso, 0.0), min(1.0, max(0.0, fraccion)))
            if hechos is not None:
                c.pasos[paso]['hechos'] = hechos
            if total is not None:
                c.pasos[paso]['total'] = total
            if texto is not None:
                c.texto = texto
        self._publicar_progreso()

    def _publicar_progreso(self, forzar: bool = False) -> None:
        c = self._c
        if c is None:
            return
        with self._candado:
            total = sum(c.pesos.values()) or 1
            p = sum(c.pesos[k] * c.fraccion.get(k, 0.0) for k in c.pesos) / total
            c.progreso = max(c.progreso, min(1.0, p))
            t = self.reloj.monotonico()
            if not forzar and t - self._ultimo_progreso_t < INTERVALO_PROGRESO_S:
                return
            self._ultimo_progreso_t = t
            estado = self._estado_sin_candado()
        try:
            self.bus.publicar({'tipo': 'sync.progreso', 'estado': estado})
        except Exception:
            _log.exception('No se pudo publicar sync.progreso')

    def _comprobar_cancelacion(self) -> None:
        if self._c is not None and self._c.ctx.cancelar.is_set():
            raise _Cancelada()

    def _error_de_control(self, e: BaseException) -> bool:
        """Errores que detienen la sync aunque ocurran en una fase de la ficha (rev. 4): cancelación, sin internet,
        reautorizar/abortar (incluido el cambio de cuenta del escritor con época) y la renovación transitoria."""
        if isinstance(e, (_Cancelada, ErrorRed)):
            return True
        if isinstance(e, ErrorApi):
            return (e.decision in ('reautorizar', 'abortar') or isinstance(e, ErrorAuthTransitorio)
                    or (self._c is not None and self._c.ctx.cancelar.is_set()))
        return False

    # ================================================================== utilidades de datos
    def _llamar(self, metodo: str, path: str, query: dict[str, Any] | None = None, body: Json | None = None) -> Json:
        self._comprobar_cancelacion()
        assert self._c is not None
        return self.cli.llamar(metodo, path, query, body, ctx=self._c.ctx)

    def _tx(self) -> Any:
        return self.alm.escritor(self.epoca)

    def _leer(self, sql: str, args: Iterable[Any] = ()) -> list[Any]:
        with self.alm.lector() as db:
            return db.execute(sql, tuple(args)).fetchall()

    @staticmethod
    def _poner_cursor(db: Any, clave: str, valor: str, ahora: int) -> None:
        db.execute('INSERT INTO sync_cursores(clave, valor, actualizado_at) VALUES (?,?,?) ON CONFLICT(clave) '
                   'DO UPDATE SET valor=excluded.valor, actualizado_at=excluded.actualizado_at', (clave, valor, ahora))

    def _poner_cursor_tx(self, clave: str, valor: str) -> None:
        try:
            with self._tx() as db:
                self._poner_cursor(db, clave, valor, self.ahora)
        except ErrorApi:
            pass

    def _tienda(self, db: Any, nombre: str | None, shop_id: str | None = None) -> str | None:
        k = norm_tienda(nombre)
        if not k:
            return None
        db.execute('INSERT INTO tiendas(tienda_key, nombre, shop_id, primera_vez_at, actualizado_at) VALUES (?,?,?,?,?) '
                   'ON CONFLICT(tienda_key) DO NOTHING', (k, (nombre or '').strip(), shop_id, self.ahora, self.ahora))
        return k

    def _encolar(self, pedidos: list[PedidoImagen]) -> None:
        """Registra imágenes en hub-imagenes DESPUÉS de confirmar la transacción de la página (nunca con el escritor)."""
        validos = [p for p in pedidos if p.url and (p.ref_id == 'cuenta' or RE_ID_IMAGEN.match(p.ref_id)
                                                    or (p.tipo == 'g' and RE_REF_GALERIA.match(p.ref_id)))]
        if not validos:
            return
        try:
            self.imagenes.encolar(validos)
        except Exception:
            _log.exception('No se pudieron encolar %d imágenes', len(validos))

    # ================================================================== puntos de control
    def _punto_control(self, n: int, secciones: tuple[str, ...]) -> None:
        self._comprobar_cancelacion()
        self._clasificar(parcial=True)
        self.alm.confirmar_data_version()
        self.bus.notificar_cambio(self.alm.versiones(), list(secciones))
        self.secciones.difference_update(secciones)
        self.resumen.setdefault('puntos_de_control', []).append({'n': n, 'at': self.reloj.ahora()})
        _log.info('Punto de control %d publicado (sync %s)', n, self.sid)

    # ================================================================== pasos
    def _paso_perfil(self) -> tuple[int, int, int]:
        d = self._llamar('GET', P_PERFIL)
        previo = self._leer('SELECT username FROM cuenta WHERE id=1')
        nuevo = not previo
        cambio = (not nuevo) and previo[0]['username'] != d.get('username')
        avatar = (d.get('avatar') or {}).get('url')
        with self._tx() as db:
            db.execute("""INSERT INTO cuenta(id, creator_open_id, username, avatar_url, selection_region, register_region,
                          user_type, seller_type, permisos_json, actualizado_at) VALUES (1,?,?,?,?,?,?,?,?,?)
                          ON CONFLICT(id) DO UPDATE SET creator_open_id=excluded.creator_open_id, username=excluded.username,
                          avatar_url=excluded.avatar_url, selection_region=excluded.selection_region,
                          register_region=excluded.register_region, user_type=excluded.user_type,
                          seller_type=excluded.seller_type, permisos_json=excluded.permisos_json,
                          actualizado_at=excluded.actualizado_at""",
                       (d.get('creator_user_open_id', ''), d.get('username', ''), avatar, d.get('selection_region'),
                        d.get('register_region'), None if d.get('user_type') is None else str(d.get('user_type')),
                        None if d.get('seller_type') is None else str(d.get('seller_type')),
                        json.dumps(d.get('permissions') or []), self.ahora))
            if nuevo or cambio:
                self.alm.marcar_data_version(db)
        if avatar:                                       # URL firmada (x-expires): se encola de inmediato
            self._encolar([PedidoImagen(tipo='a', ref_id='cuenta', url=avatar, prioridad=0, fuente='perfil')])
        self.cambios += int(nuevo) + int(cambio)
        self._avance('perfil', 1.0, hechos=1, total=1)
        return (1 if nuevo else 0), (1 if cambio else 0), 1

    def _es_validacion(self, e: ErrorApi) -> bool:
        return e.http == 400 or e.codigo in self.codigos_validacion

    def _bajar_filtro_muestras(self, variante: str, estado: str, destino: list[dict[str, Any]]) -> None:
        token, vistos, ids_filtro = None, set(), set()
        for _ in range(40):                                      # tope de seguridad por estado
            q: dict[str, Any] = {'page_size': 50}
            if token:
                q['page_token'] = token
            d = self._llamar('POST', P_MUESTRAS, q, {'application_statuses': [variante]})
            items = d.get('sample_applications') or []
            nuevos_en_pagina = [it for it in items if it.get('id') not in ids_filtro]
            for it in items:
                ids_filtro.add(it.get('id'))
                destino.append(dict(it, _estado_consulta=estado))
            token = d.get('next_page_token') or ''
            # la API no vacía el token al final: vuelve a la 1.ª página -> parar si la página no trae nada nuevo
            if not items or not nuevos_en_pagina or not token or token in vistos:
                break
            vistos.add(token)

    def _paso_muestras(self) -> tuple[int, int, int]:
        rechazados = set(json.loads(self._leer_cursor('muestras.estados_rechazados') or '[]'))
        filas: list[dict[str, Any]] = []
        fallidos: list[str] = []
        estados = cl.ESTADOS_SOLICITUD
        for k_estado, st in enumerate(estados):
            self._avance('muestras', k_estado / len(estados))
            if st in rechazados and self.tipo != 'completa':
                continue
            variantes = [st] + (['OPS_ COMPLETED'] if st == 'OPS_COMPLETED' else [])   # la doc lo escribe con espacio
            for k, var in enumerate(variantes):
                try:
                    self._bajar_filtro_muestras(var, st, filas)
                    rechazados.discard(st)
                    break
                except ErrorApi as e:
                    if e.decision in ('reautorizar', 'abortar') or e.codigo in CODIGOS_OMITIR_PASO:
                        raise
                    if self._es_validacion(e):
                        if k == len(variantes) - 1:
                            rechazados.add(st)                   # no se vuelve a pedir hasta la siguiente completa
                        continue
                    fallidos.append(st)                          # cualquier otro error: evidencia incompleta
                    break
        por_id, _ids, comodin, pistas = cl.unificar_muestras(filas)
        self.resumen['muestras_filtros_comodin'] = sorted(comodin)
        if fallidos:
            self.parciales.add('muestras')
            self.resumen['muestras_filtros_fallidos'] = fallidos
        nuevos = camb = 0
        with self._tx() as db:
            for aid, m in por_id.items():
                sp = m.get('sample_product') or {}
                variante = ' / '.join(sp.get('sku_sale_property_value_names') or [])
                estado = norm_estado(m.get('status')) or 'UNKNOWN'
                prev = db.execute('SELECT huella, estado_api, pistas_json FROM muestras WHERE application_id=?',
                                  (aid,)).fetchone()
                p_aid = set(pistas[aid])
                if prev is not None and fallidos:     # conservar las pistas que daban los filtros que fallaron
                    p_aid |= set(json.loads(prev['pistas_json'])) & set(fallidos)
                h = huella(estado, cl.main_order(m), sp.get('id'), sp.get('sku_id'), variante, sorted(p_aid))
                if prev is None:
                    nuevos += 1
                    db.execute("""INSERT INTO muestras(application_id, product_id, sku_id, variante, main_order_id, activity_id,
                                  estado_api, pistas_json, clase, subestado, clase_desde_at, vista_en_sync, primera_vez_at,
                                  huella, actualizado_at) VALUES (?,?,?,?,?,?,?,?,'nunca_enviada','sin_clasificar',?,?,?,?,?)""",
                               (aid, sp.get('id'), sp.get('sku_id'), variante, cl.main_order(m), m.get('activity_id') or None,
                                estado, json.dumps(sorted(p_aid)), self.ahora, self.sid, self.ahora, h, self.ahora))
                elif prev['huella'] != h:
                    camb += 1
                    if prev['estado_api'] != estado:
                        db.execute('INSERT INTO muestras_historial(application_id, sync_id, campo, antes, despues, at) '
                                   'VALUES (?,?,?,?,?,?)', (aid, self.sid, 'estado_api', prev['estado_api'], estado,
                                                            self.ahora))
                    db.execute("""UPDATE muestras SET estado_api=?, main_order_id=?, sku_id=?, variante=?, pistas_json=?,
                                  huella=?, vista_en_sync=?, actualizado_at=? WHERE application_id=?""",
                               (estado, cl.main_order(m), sp.get('sku_id'), variante, json.dumps(sorted(p_aid)),
                                h, self.sid, self.ahora, aid))
                else:
                    db.execute('UPDATE muestras SET vista_en_sync=? WHERE application_id=?', (self.sid, aid))
            self._poner_cursor(db, 'muestras.estados_rechazados', json.dumps(sorted(rechazados)), self.ahora)
            if nuevos + camb:
                self.alm.marcar_data_version(db)
        self.cambios += nuevos + camb
        self._avance('muestras', 1.0, hechos=len(por_id))
        return nuevos, camb, len(por_id)

    def _upsert_cumplimiento(self, db: Any, e: dict[str, Any]) -> str | None:
        """Upsert por fulfillment_id (sin UNIQUE por solicitud). Devuelve 'nuevo' | 'cambiado' | None."""
        estado = norm_estado(e.get('status')) or 'DESCONOCIDO'
        limite = cl.fecha_limite(estado, e.get('expiration_time'), e['_hora'])
        prev = db.execute('SELECT huella, estado, shop_id, estado_producto, tipo FROM cumplimientos WHERE fulfillment_id=?',
                          (e['id'],)).fetchone()
        shop = e.get('shop_id') or (prev['shop_id'] if prev else None)
        bps = e.get('bound_product_status') or (prev['estado_producto'] if prev else None)
        tipo = e.get('sample_application_type') or (prev['tipo'] if prev else None)
        h = huella(estado, limite, int(e.get('total_suspend_duration') or 0), bps, shop)
        if prev is not None and prev['huella'] == h:
            db.execute('UPDATE cumplimientos SET vista_en_sync=? WHERE fulfillment_id=?', (self.sid, e['id']))
            return None
        if prev is not None and prev['estado'] != estado:
            db.execute('INSERT INTO muestras_historial(application_id, sync_id, campo, antes, despues, at) VALUES (?,?,?,?,?,?)',
                       (e['application_id'], self.sid, 'cumplimiento', prev['estado'], estado, self.ahora))
        db.execute("""INSERT INTO cumplimientos(fulfillment_id, application_id, product_id, shop_id, tipo, estado,
                      fecha_limite_at, suspension_s, estado_producto, vista_en_sync, huella, actualizado_at)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(fulfillment_id) DO UPDATE SET
                      estado=excluded.estado, fecha_limite_at=excluded.fecha_limite_at, suspension_s=excluded.suspension_s,
                      estado_producto=excluded.estado_producto, shop_id=excluded.shop_id, tipo=excluded.tipo,
                      vista_en_sync=excluded.vista_en_sync, huella=excluded.huella, actualizado_at=excluded.actualizado_at""",
                   (e['id'], e['application_id'], e.get('product_id'), shop, tipo, estado, limite,
                    int(e.get('total_suspend_duration') or 0), bps, self.sid, h, self.ahora))
        if tipo:   # si cambia el tipo (p. ej. a SAMPLE_COUPON) se reinician los intentos del detalle
            db.execute("""UPDATE muestras SET tipo=?, detalle_intentos=0, detalle_reintento_at=NULL, detalle_espera_s=NULL,
                          detalle_estado=CASE WHEN detalle_estado='ok' THEN 'ok' ELSE 'pendiente' END
                          WHERE application_id=? AND tipo<>?""", (tipo, e['application_id'], tipo))
        return 'nuevo' if prev is None else 'cambiado'

    def _paso_cumplimientos(self) -> tuple[int, int, int]:
        regs: dict[str, dict[str, Any]] = {}
        estados = cl.ESTADOS_CUMPLIMIENTO
        for k_estado, st in enumerate(estados):
            self._avance('cumplimientos', 0.9 * k_estado / len(estados))
            token, vistos = None, set()
            for _ in range(40):
                q: dict[str, Any] = {'sort_field': 'create_time', 'sort_order': 'DESC'}
                if token:
                    q['page_token'] = token
                d = self._llamar('POST', P_CUMPL, q, {'fulfillment_statuses': [st]})
                hora = int(self.cli.ahora())
                for e in d.get('fulfillments') or []:
                    regs[e['id']] = dict(e, _hora=hora)
                token = d.get('next_page_token') or ''                # la doc no pagina; se sigue si llegara
                if not token or token in vistos:
                    break
                vistos.add(token)
        nuevos = camb = 0
        with self._tx() as db:
            for e in regs.values():
                r = self._upsert_cumplimiento(db, e)
                nuevos += r == 'nuevo'
                camb += r == 'cambiado'
            if nuevos + camb:
                self.alm.marcar_data_version(db)
        self.cambios += nuevos + camb
        # Abiertos que esta corrida NO vio (pasaron a REPEATED u otro estado no filtrable): confirmar con single_query.
        obs = self._leer("""SELECT c.fulfillment_id, c.application_id, c.product_id, COALESCE(c.tipo, m.tipo) AS tipo,
                                   m.main_order_id FROM cumplimientos c LEFT JOIN muestras m USING (application_id)
                            WHERE c.estado IN ('PENDING','ONGOING','SUSPEND')
                              AND (c.vista_en_sync IS NULL OR c.vista_en_sync <> ?)""", (self.sid,))
        for o in obs:
            tipo = o['tipo'] or 'FREE_SAMPLE'
            body: dict[str, Any] = {'product_id': o['product_id'], 'application_type': tipo,
                                    'application_id': o['application_id']}
            if tipo != 'FREE_SAMPLE' and o['main_order_id']:
                body['main_order_id'] = o['main_order_id']
            try:
                d = self._llamar('POST', P_DETALLE, None, body)
                cf = (d.get('sample_application') or {}).get('creator_fulfillment') or {}
            except ErrorApi as e:
                if e.decision in ('reautorizar', 'abortar'):
                    raise
                cf = {}
            hora = int(self.cli.ahora())
            desconocido = ("UPDATE cumplimientos SET estado='DESCONOCIDO', fecha_limite_at=NULL, vista_en_sync=?, "
                           "huella='desconocido', actualizado_at=? WHERE fulfillment_id=?")
            with self._tx() as db:
                if cf.get('id') and cf.get('status'):
                    cambio = cf['id'] != o['fulfillment_id']
                    if cambio:            # la solicitud tiene otro cumplimiento: el anterior deja de ser vigente
                        db.execute(desconocido, (self.sid, self.ahora, o['fulfillment_id']))
                    r = self._upsert_cumplimiento(db, {'id': cf['id'], 'application_id': o['application_id'],
                                                       'product_id': o['product_id'], 'status': cf['status'],
                                                       'expiration_time': cf.get('expiration_time'),
                                                       'total_suspend_duration': cf.get('total_suspend_duration'),
                                                       'sample_application_type': tipo, '_hora': hora})
                    cambio = cambio or r is not None
                else:
                    db.execute(desconocido, (self.sid, self.ahora, o['fulfillment_id']))
                    cambio = True
                if cambio:
                    self.alm.marcar_data_version(db)
            camb += int(cambio)
            self.cambios += int(cambio)
        self.resumen['cumplimientos_confirmados_por_detalle'] = len(obs)
        self._avance('cumplimientos', 1.0, hechos=len(regs))
        return nuevos, camb, len(regs)

    # ------------------------------------------------------------------ productos (de muestras y de ventas)
    def _paso_productos(self) -> tuple[int, int, int]:
        if self.tipo == 'completa':
            filas = self._leer('SELECT DISTINCT product_id FROM muestras')
        else:
            filas = self._leer("""SELECT DISTINCT m.product_id FROM muestras m LEFT JOIN productos p USING (product_id)
                                  WHERE p.product_id IS NULL OR p.consultado_at IS NULL OR p.consultado_at < ?""",
                               (self.ahora - DIA_S,))
        ids = sorted({r[0] for r in filas if r[0]})
        return self._bajar_productos('productos', ids, prioridad=0)

    def _paso_productos_ventas(self) -> tuple[int, int, int]:
        """Fichas de los productos de ventas, vitrina y cumplimientos (primera mitad del avance) y, después, las fases
        de la ficha completa de producto (rev. 4, sincronizador_ficha.py; segunda mitad). Si las fichas fallan sin ser
        un error de control, las fases corren igual y luego el paso se marca como siempre."""
        error: ErrorApi | None = None
        self._escala['productos_ventas'] = (0.0, 0.5)
        try:
            r = self._fichas_de_ventas()
        except ErrorApi as e:
            if self._error_de_control(e):
                raise
            error, r = e, (0, 0, 0)
        finally:
            self._escala.pop('productos_ventas', None)
        self._correr_fases_ficha('productos_ventas', 0.5)
        if error is not None:
            raise error
        return r

    def _fichas_de_ventas(self) -> tuple[int, int, int]:
        limite = self.ahora if self.tipo == 'completa' else self.ahora - DIA_S
        # rev. 4: también los productos de cumplimientos (una solicitud recuperada puede no estar en muestras)
        filas = self._leer("""SELECT x.product_id FROM (SELECT product_id FROM orden_lineas UNION SELECT product_id FROM vitrina
                                                        UNION SELECT product_id FROM cumplimientos) x
                              LEFT JOIN productos p USING (product_id)
                              WHERE p.product_id IS NULL OR p.consultado_at IS NULL OR p.consultado_at < ?""", (limite,))
        ids = sorted({r[0] for r in filas if r[0] and RE_ID_IMAGEN.match(str(r[0]))})
        nuevos, camb, hechos = self._bajar_productos('productos_ventas', ids, prioridad=1)
        # Fichas mínimas creadas en el paso 4 (producto de una muestra fuera de colaboración abierta) cuando aún no
        # había pedidos: ahora se completan con el nombre y la tienda de su línea más reciente (como motor_ref).
        with self._tx() as db:
            pend = db.execute("""SELECT p.product_id, p.titulo, p.tienda_key FROM productos p
                                 WHERE p.origen = 'orden' AND (p.titulo IS NULL OR p.tienda_key IS NULL)
                                   AND EXISTS (SELECT 1 FROM orden_lineas l WHERE l.product_id = p.product_id)""").fetchall()
            completadas = 0
            for f in pend:
                ult = db.execute("""SELECT producto_nombre, tienda_nombre FROM orden_lineas l JOIN ordenes o USING(order_id)
                                    WHERE product_id=? ORDER BY o.creada_at DESC LIMIT 1""", (f['product_id'],)).fetchone()
                titulo = f['titulo'] if f['titulo'] is not None else ult['producto_nombre']
                tienda = f['tienda_key'] if f['tienda_key'] is not None else self._tienda(db, ult['tienda_nombre'])
                if (titulo, tienda) != (f['titulo'], f['tienda_key']):
                    db.execute('UPDATE productos SET titulo=?, tienda_key=?, actualizado_at=? WHERE product_id=?',
                               (titulo, tienda, self.ahora, f['product_id']))
                    completadas += 1
            if completadas:
                self.alm.marcar_data_version(db)
        self.cambios += completadas
        self.resumen['fichas_minimas_completadas'] = completadas
        return nuevos, camb + completadas, hechos

    def _bajar_productos(self, paso: str, ids: list[str], prioridad: int) -> tuple[int, int, int]:
        nuevos = camb = 0
        lotes = [ids[k:k + LOTE_PRODUCTOS] for k in range(0, len(ids), LOTE_PRODUCTOS)]
        self._avance(paso, 0.0, hechos=0, total=len(ids))
        for n_lote, lote in enumerate(lotes):
            d = self._llamar('POST', P_PRODUCTOS, {'product_ids': ','.join(lote)}, None)
            vistos: set[str] = set()
            n_l = c_l = 0
            imagen_ficha: dict[str, str | None] = {}
            with self._tx() as db:
                for p in d.get('products') or []:
                    vistos.add(p['id'])
                    op = p.get('original_price') or {}
                    com = p.get('commission') or {}
                    cmin, cmax = parse_rango(com.get('amount'))
                    cats = p.get('category_chains') or []
                    fila = (p.get('title'), self._tienda(db, (p.get('shop') or {}).get('name')), p.get('main_image_url'),
                            p.get('detail_link'), parse_monto(op.get('minimum_amount')), parse_monto(op.get('maximum_amount')),
                            op.get('currency') or None, com.get('rate'), cmin, cmax,
                            (p.get('shop_ads_commission') or {}).get('rate'), p.get('units_sold'),
                            None if p.get('has_inventory') is None else int(bool(p['has_inventory'])),
                            ' > '.join(x.get('local_name', '') for x in cats) or None, cats[-1]['id'] if cats else None,
                            p.get('sale_region'))
                    h = huella(*fila)
                    prev = db.execute('SELECT huella, en_colaboracion_abierta, origen FROM productos WHERE product_id=?',
                                      (p['id'],)).fetchone()
                    n_l += prev is None
                    # cambio = otra huella, o volvió a colaboración abierta (antes ficha mínima o fuera de ella)
                    c_l += prev is not None and (prev['huella'] != h or prev['en_colaboracion_abierta'] != 1
                                                 or prev['origen'] != 'api')
                    db.execute("""INSERT INTO productos(product_id, titulo, tienda_key, imagen_url, enlace, precio_min_centavos,
                                  precio_max_centavos, moneda, comision_bp, comision_monto_min_centavos, comision_monto_max_centavos,
                                  shop_ads_bp, unidades_vendidas, con_inventario, categoria, categoria_hoja_id, region,
                                  en_colaboracion_abierta, origen, consultado_at, huella, actualizado_at)
                                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,'api',?,?,?)
                                  ON CONFLICT(product_id) DO UPDATE SET titulo=excluded.titulo, tienda_key=excluded.tienda_key,
                                  imagen_url=excluded.imagen_url, enlace=excluded.enlace, precio_min_centavos=excluded.precio_min_centavos,
                                  precio_max_centavos=excluded.precio_max_centavos, moneda=excluded.moneda, comision_bp=excluded.comision_bp,
                                  comision_monto_min_centavos=excluded.comision_monto_min_centavos,
                                  comision_monto_max_centavos=excluded.comision_monto_max_centavos, shop_ads_bp=excluded.shop_ads_bp,
                                  unidades_vendidas=excluded.unidades_vendidas, con_inventario=excluded.con_inventario,
                                  categoria=excluded.categoria, categoria_hoja_id=excluded.categoria_hoja_id, region=excluded.region,
                                  en_colaboracion_abierta=1, origen='api', consultado_at=excluded.consultado_at, huella=excluded.huella,
                                  actualizado_at=CASE WHEN productos.huella IS excluded.huella THEN productos.actualizado_at
                                                      ELSE excluded.actualizado_at END""",
                               (p['id'], *fila, self.ahora, h, self.ahora))
                    imagen_ficha[p['id']] = p.get('main_image_url')
                for pid in lote:
                    if pid in vistos:
                        continue
                    # no está en colaboración abierta: conservar lo último o crear ficha mínima desde su pedido
                    ult = db.execute("""SELECT producto_nombre, tienda_nombre FROM orden_lineas l JOIN ordenes o USING(order_id)
                                        WHERE product_id=? ORDER BY o.creada_at DESC LIMIT 1""", (pid,)).fetchone()
                    prev = db.execute('SELECT origen FROM productos WHERE product_id=?', (pid,)).fetchone()
                    if prev is None:
                        n_l += 1
                        db.execute("""INSERT INTO productos(product_id, titulo, tienda_key, en_colaboracion_abierta, origen,
                                      consultado_at, actualizado_at) VALUES (?,?,?,0,'orden',?,?)""",
                                   (pid, ult['producto_nombre'] if ult else None,
                                    self._tienda(db, ult['tienda_nombre']) if ult else None, self.ahora, self.ahora))
                    else:
                        # salió de colaboración abierta: se conserva lo último; el cambio de bandera sí cuenta
                        c_l += db.execute('UPDATE productos SET en_colaboracion_abierta=0, actualizado_at=? '
                                          'WHERE product_id=? AND en_colaboracion_abierta<>0', (self.ahora, pid)).rowcount
                        db.execute('UPDATE productos SET consultado_at=? WHERE product_id=?', (self.ahora, pid))
                    imagen_ficha[pid] = None
                vit = {r[0]: r[1] for r in db.execute(
                    f"SELECT product_id, imagen_url FROM vitrina WHERE product_id IN ({','.join('?' * len(lote))})",
                    tuple(lote))}
                if n_l + c_l:
                    self.alm.marcar_data_version(db)
            nuevos, camb = nuevos + n_l, camb + c_l
            self.cambios += n_l + c_l
            self._productos_de_esta_sync.update(lote)
            # Cascada C39 (sin target_collaborations): ficha → vitrina → (mosaico en la interfaz).
            pedidos = []
            for pid in lote:
                if imagen_ficha.get(pid):
                    pedidos.append(PedidoImagen('p', pid, imagen_ficha[pid] or '', prioridad, 'ficha'))
                elif vit.get(pid):
                    pedidos.append(PedidoImagen('p', pid, vit[pid] or '', prioridad, 'vitrina'))
            self._encolar(pedidos)
            self._avance(paso, (n_lote + 1) / len(lotes), hechos=min(len(ids), (n_lote + 1) * LOTE_PRODUCTOS))
        return nuevos, camb, len(ids)

    # ------------------------------------------------------------------ pedidos (ordenes y ordenes_anteriores)
    def _planear_ventanas(self) -> None:
        """Ventanas de la sync (bordes de motor_ref) partidas en recientes (26) y anteriores, menos lo que una corrida
        anterior interrumpida ya bajó completo (reanudación por cursor_json)."""
        tope = self.ahora + 1
        if self.tipo == 'completa':
            desde = self.ahora - DIAS_HISTORIA * DIA_S
        else:
            r = self._leer('SELECT MIN(creada_at) FROM ordenes WHERE es_final = 0')[0][0]   # NO_DEVUELTA es final
            desde = min(self.ahora - 35 * DIA_S, (r - DIA_S) if r else self.ahora)
            desde = max(desde, self.ahora - DIAS_HISTORIA * DIA_S)
        todas = sorted(ventanas(desde, tope), key=lambda v: -v[0])          # de la más reciente a la más antigua
        if self.tipo == 'completa':
            recientes, anteriores = todas[:VENTANAS_RECIENTES], todas[VENTANAS_RECIENTES:]
        else:
            recientes, anteriores = todas, []
        self._cobertura = self._cobertura_reanudable()
        self._segmentos = {'ordenes': restar_cobertura(recientes, self._cobertura),
                           'ordenes_anteriores': restar_cobertura(anteriores, self._cobertura)}
        self._tope = tope
        self._cursor_desde = tope
        if self._cobertura is not None:
            self.resumen['ordenes_reanudadas'] = {'desde': self._cobertura[0], 'hasta': self._cobertura[1]}

    def _cobertura_reanudable(self) -> tuple[int, int] | None:
        filas = self._leer("""SELECT e.sync_id, e.estado, e.terminada_at, p.cursor_json FROM sync_ejecuciones e
                              LEFT JOIN sync_pasos p ON p.sync_id = e.sync_id AND p.paso = 'ordenes'
                              WHERE e.sync_id < ? ORDER BY e.sync_id DESC LIMIT 1""", (self.sid,))
        if not filas:
            return None
        f = filas[0]
        if f['estado'] not in ('error', 'cancelada') or not f['terminada_at'] or not f['cursor_json']:
            return None
        if self.ahora - f['terminada_at'] > REANUDAR_DENTRO_DE_S:
            return None
        try:
            cur = json.loads(f['cursor_json'])
            d, t = int(cur['desde']), int(cur['tope'])
        except (ValueError, KeyError, TypeError):
            return None
        return (d, t) if d < t else None

    def _paso_ordenes(self) -> tuple[int, int, int]:
        self._planear_ventanas()
        return self._procesar_segmentos('ordenes')

    def _paso_ordenes_anteriores(self) -> tuple[int, int, int]:
        if not self._segmentos:
            self._planear_ventanas()
        r = self._procesar_segmentos('ordenes_anteriores')
        assert self._c is not None
        if self.tipo == 'completa' and self._c.pasos['ordenes']['estado'] == 'ok':
            with self._tx() as db:
                self._poner_cursor(db, 'ordenes.barrido_completo_at', str(self.ahora), self.ahora)
                limite = self.ahora - DIAS_HISTORIA * DIA_S
                if db.execute('DELETE FROM orden_trazas WHERE creada_at < ?', (limite,)).rowcount:   # rev. 4: 400 días
                    self.alm.marcar_data_version(db)
                purgadas = db.execute('DELETE FROM ordenes WHERE creada_at < ?', (limite,)).rowcount
                if purgadas:
                    db.execute("""DELETE FROM productos WHERE origen = 'orden'
                                  AND product_id NOT IN (SELECT product_id FROM orden_lineas)
                                  AND product_id NOT IN (SELECT product_id FROM muestras)
                                  AND product_id NOT IN (SELECT product_id FROM vitrina)""")
                    self.alm.marcar_data_version(db)
                    self.resumen['ordenes_purgadas'] = purgadas
        return r

    def _guardar_cursor_ordenes(self, db: Any) -> None:
        db.execute("UPDATE sync_pasos SET cursor_json=? WHERE sync_id=? AND paso='ordenes'",
                   (json.dumps({'tope': self._tope, 'desde': self._cursor_desde, 'tipo': self.tipo}), self.sid))

    def _procesar_segmentos(self, paso: str) -> tuple[int, int, int]:
        segmentos = self._segmentos.get(paso, [])
        a_bajar = [s for s in segmentos if s[0] == 'bajar']
        N = len(a_bajar)
        nuevos = camb = hechos = 0
        avisos: list[dict[str, Any]] = []
        n = 0
        if N == 0:
            self._avance(paso, 1.0, hechos=0, total=0)
        for tipo_seg, ge, lt in segmentos:
            self._comprobar_cancelacion()
            if tipo_seg == 'cubierto':
                if lt == self._cursor_desde:
                    self._cursor_desde = ge
                    with self.alm.escritor() as db:
                        self._guardar_cursor_ordenes(db)
                continue
            n += 1
            self._avance(paso, (n - 1) / N, texto=TEXTOS[paso].format(n=n, N=N))
            n_v, c_v, h_v, aviso = self._bajar_y_guardar_ventana(ge, lt)
            nuevos, camb, hechos = nuevos + n_v, camb + c_v, hechos + h_v
            if aviso:
                avisos.append(aviso)
            self._avance(paso, n / N, hechos=hechos)
        if avisos:
            self.resumen.setdefault('ordenes_ventanas_con_aviso', []).extend(avisos)
        self.resumen.setdefault('ordenes_ventanas', {})[paso] = N
        return nuevos, camb, hechos

    def _bajar_ventana(self, ge: int, lt: int) -> tuple[dict[str, dict[str, Any]], int, int, list[str]]:
        """(por_orden, total_count, líneas_tras_fusionar, anomalías). Fusiona por CONCATENACIÓN (sku.id no es id de
        línea) y para en cuanto las líneas fusionadas alcanzan total_count; detecta la vuelta de página."""
        por_orden: dict[str, dict[str, Any]] = {}
        total, token, vistos, ultima, anomalias = None, None, set(), None, []
        tam_pagina, pagina_anterior_llena = 100, False
        for _ in range(200):
            q: dict[str, Any] = {'page_size': tam_pagina}
            if token:
                q['page_token'] = token
            d = self._llamar('POST', P_ORDENES, q, {'create_time_ge': ge, 'create_time_lt': lt})
            if total is None:
                total = int(d.get('total_count') or 0)
            ordenes = d.get('orders') or []
            if not ordenes:
                break
            # una orden solo puede continuar en esta página si la anterior venía LLENA (se partió en el borde)
            continua = pagina_anterior_llena and ordenes[0]['id'] == ultima
            if all(o['id'] in por_orden for o in ordenes) and not continua:
                anomalias.append('vuelta')                       # la página solo trae pedidos ya vistos
                break
            for k, o in enumerate(ordenes):
                oid, skus = o['id'], list(o.get('skus') or [])
                if oid in por_orden:
                    actual = por_orden[oid]
                    if not (k == 0 and continua):               # repetida y no es continuación: no duplicar líneas
                        anomalias.append('orden_repetida')
                        continue
                    actual['skus'] += skus
                    actual['status'] = o.get('status', actual['status'])
                else:
                    por_orden[oid] = dict(o, skus=skus)
                ultima = oid
            pagina_anterior_llena = sum(len(o.get('skus') or []) for o in ordenes) >= tam_pagina
            n = sum(len(x['skus']) for x in por_orden.values())
            if total and n >= total:
                break
            token = d.get('next_page_token') or ''
            if not token or token in vistos:
                break
            vistos.add(token)
        n = sum(len(x['skus']) for x in por_orden.values())
        if total is not None and n > total:
            anomalias.append('exceso')
        return por_orden, total or 0, n, anomalias

    @staticmethod
    def _huella_orden(o: dict[str, Any]) -> str:
        skus = o.get('skus') or []
        return huella(o.get('status'), o.get('delivery_time'), sorted(
            (s.get('id'), s.get('product_id'), (s.get('price') or {}).get('amount'), s.get('quantity'),
             (s.get('estimated_commission') or {}).get('amount'), (s.get('actual_commission') or {}).get('amount'),
             s.get('refunded_quantity'), s.get('returned_quantity'), s.get('content_id'), s.get('last_update_time'))
            for s in skus))

    def _insertar_lineas(self, db: Any, oid: str, skus: list[dict[str, Any]]) -> None:
        db.execute('DELETE FROM orden_lineas WHERE order_id=?', (oid,))
        for i, s in enumerate(skus):
            tk = self._tienda(db, s.get('shop_name'))
            db.execute("""INSERT INTO orden_lineas(order_id, linea_n, sku_id, product_id, producto_nombre, tienda_nombre, tienda_key,
                          precio_centavos, moneda, cantidad, reembolsadas, devueltas, comision_bp, comision_std_bp,
                          comision_ads_bp, comision_bono_bp, com_estimada_centavos, com_real_centavos,
                          base_estimada_centavos, base_real_centavos, isr_centavos, iva_centavos, compartido_centavos,
                          tipo_contenido, content_id, campaign_id, open_collab_id, target_collab_id, es_carrusel,
                          linea_actualizada_at)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (oid, i, s.get('id') or None, s.get('product_id'), s.get('product_name'), s.get('shop_name'), tk,
                        parse_monto((s.get('price') or {}).get('amount')), (s.get('price') or {}).get('currency'),
                        int(s.get('quantity') or 0), int(s.get('refunded_quantity') or 0), int(s.get('returned_quantity') or 0),
                        s.get('commission_rate'), s.get('standard_commission_rate'), s.get('shop_ads_commission_rate'),
                        s.get('commission_bonus_rate'),
                        parse_monto((s.get('estimated_commission') or {}).get('amount')),
                        parse_monto((s.get('actual_commission') or {}).get('amount')),
                        parse_monto((s.get('estimated_commission_base') or {}).get('amount')),
                        parse_monto((s.get('actual_commission_base') or {}).get('amount')),
                        parse_monto((s.get('isr') or {}).get('amount')), parse_monto((s.get('iva') or {}).get('amount')),
                        parse_monto((s.get('shared_with_partner') or {}).get('amount')),
                        s.get('content_type'), s.get('content_id') or None, s.get('campaign_id'),
                        s.get('open_collaboration_id'), s.get('target_collaboration_id'),
                        None if s.get('is_carousel') is None else int(bool(s.get('is_carousel'))), s.get('last_update_time')))

    def _bajar_y_guardar_ventana(self, ge: int, lt: int) -> tuple[int, int, int, dict[str, Any] | None]:
        por_orden, total, n, anom = self._bajar_ventana(ge, lt)
        if n < total:                                      # incompleta: un reintento de la ventana
            por_orden, total, n, anom = self._bajar_ventana(ge, lt)
        completa = n >= total
        aviso = ({'ge': ge, 'lt': lt, 'total': total, 'lineas': n, 'anomalias': sorted(set(anom))}
                 if (not completa or anom) else None)
        n_v = c_v = hechos = 0
        with self._tx() as db:
            for oid, o in por_orden.items():
                hechos += 1
                estado = o.get('status') or 'UNSPECIFIED'
                prev = db.execute('SELECT huella, estado FROM ordenes WHERE order_id=?', (oid,)).fetchone()
                if not completa and prev is not None:
                    # ventana incompleta: NO se tocan las líneas ya guardadas; solo el estado (es del pedido)
                    if prev['estado'] != estado:
                        db.execute('UPDATE ordenes SET estado=?, vista_en_sync=?, actualizado_at=? WHERE order_id=?',
                                   (estado, self.sid, self.ahora, oid))
                        c_v += 1
                    else:
                        db.execute('UPDATE ordenes SET vista_en_sync=? WHERE order_id=?', (self.sid, oid))
                    continue
                h = self._huella_orden(o) if completa else 'incompleta'
                if prev is not None and prev['huella'] == h:
                    db.execute('UPDATE ordenes SET vista_en_sync=? WHERE order_id=?', (self.sid, oid))
                    continue
                n_v += prev is None
                c_v += prev is not None
                db.execute("""INSERT INTO ordenes(order_id, creada_at, entregada_at, estado, vista_en_sync, huella, actualizado_at)
                              VALUES (?,?,?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET estado=excluded.estado,
                              entregada_at=excluded.entregada_at, vista_en_sync=excluded.vista_en_sync, huella=excluded.huella,
                              actualizado_at=excluded.actualizado_at""",
                           (oid, int(o['create_time']), o.get('delivery_time') or None, estado, self.sid, h, self.ahora))
                self._insertar_lineas(db, oid, o.get('skus') or [])
            if completa:
                # ventana bajada completa: lo que está en la base y TikTok ya no devuelve deja de contar
                vistas = set(por_orden)
                for r in db.execute("SELECT order_id FROM ordenes WHERE creada_at >= ? AND creada_at < ? "
                                    "AND estado <> 'NO_DEVUELTA'", (ge, lt)).fetchall():
                    if r['order_id'] not in vistas:
                        db.execute("UPDATE ordenes SET estado='NO_DEVUELTA', huella='no_devuelta', vista_en_sync=?, "
                                   "actualizado_at=? WHERE order_id=?", (self.sid, self.ahora, r['order_id']))
                        c_v += 1
                if lt == self._cursor_desde:               # cobertura contigua desde el tope: reanudable
                    self._cursor_desde = ge
            if n_v + c_v:
                self.alm.marcar_data_version(db)
            self._guardar_cursor_ordenes(db)
        self.cambios += n_v + c_v                          # se cuentan al CONFIRMAR cada ventana
        return n_v, c_v, hechos, aviso

    # ------------------------------------------------------------------ vitrina, detalles, videos, imágenes
    def _vitrina_vencida(self) -> bool:
        """Incremental: la vitrina se revisa cada 24 h (03 §4.1) y una vez tras migrar a la rev. 4 ('vitrina.rev')."""
        at = self._leer_cursor('vitrina.at')
        if self._leer_cursor('vitrina.rev') != REV_VITRINA:
            return True
        return at is None or self.ahora - int(at) >= DIA_S

    def _paso_vitrina(self) -> tuple[int, int, int]:
        token, vistos, total, nuevos_v, cambios_v = None, set(), 0, 0, 0
        muestras = {r[0] for r in self._leer('SELECT DISTINCT product_id FROM muestras')}
        for _ in range(100):
            q: dict[str, Any] = {'page_size': 20, 'origin': 'SHOWCASE'}
            if token:
                q['page_token'] = token
            d = self._llamar('GET', P_VITRINA, q)
            prods = d.get('products') or []
            total += len(prods)
            pedidos = []
            with self._tx() as db:
                n_pag = c_pag = 0
                for p in prods:
                    pr = p.get('price') or {}
                    op, dp = pr.get('original_price') or {}, pr.get('seller_discount_price') or {}
                    pp = pr.get('platform_discount_price') or {}              # rev. 4
                    st = p.get('status') or {}
                    colab = p.get('collaboration') or {}
                    nombre = (p.get('shop') or {}).get('name')
                    imgs = p.get('main_images') or []
                    url = (imgs[0] or {}).get('url') if imgs else None
                    galeria = urls_galeria(imgs)
                    galeria_json = json.dumps(galeria, ensure_ascii=False) if galeria else None
                    fila = (p.get('title'), nombre, norm_tienda(nombre), url,
                            parse_monto(op.get('minimum_amount')), parse_monto(op.get('maximum_amount')),
                            parse_monto(dp.get('minimum_amount')), parse_monto(dp.get('maximum_amount')),
                            p.get('detail_link'),
                            # rev. 4: lo que showcases/products ya traía y se tiraba
                            st.get('inventory_status') or None, (p.get('commission') or {}).get('rate'),
                            st.get('review_status') or None,
                            None if st.get('is_hidden') is None else int(bool(st.get('is_hidden'))),
                            st.get('added_status') or None, p.get('source') or None,
                            None if colab.get('type') in (None, '') else str(colab.get('type')),
                            parse_monto(pp.get('minimum_amount')), parse_monto(pp.get('maximum_amount')))
                    prev = db.execute("""SELECT titulo, tienda_nombre, tienda_key, imagen_url, precio_min_centavos,
                                                precio_max_centavos, precio_desc_min_centavos, precio_desc_max_centavos, enlace,
                                                inventario, comision_bp, revision, oculto, agregado, fuente,
                                                colaboracion_tipo, precio_plat_min_centavos, precio_plat_max_centavos,
                                                galeria_json
                                         FROM vitrina WHERE product_id=?""", (p.get('id'),)).fetchone()
                    if (prev is not None and tuple(prev)[:-1] == fila
                            and huella_galeria(prev['galeria_json']) == huella_galeria(galeria_json)):
                        # sin cambios: no se reescribe (una corrida repetida escribe 0 filas); una firma nueva en las
                        # URL de la galería se guarda sin contarla como cambio
                        db.execute('UPDATE vitrina SET vista_en_sync=?, galeria_json=? WHERE product_id=?',
                                   (self.sid, galeria_json, p.get('id')))
                    else:
                        n_pag += prev is None
                        c_pag += prev is not None
                        db.execute("""INSERT INTO vitrina(product_id, titulo, tienda_nombre, tienda_key, imagen_url, precio_min_centavos,
                                      precio_max_centavos, precio_desc_min_centavos, precio_desc_max_centavos, enlace,
                                      inventario, comision_bp, revision, oculto, agregado, fuente, colaboracion_tipo,
                                      precio_plat_min_centavos, precio_plat_max_centavos, galeria_json, vista_en_sync,
                                      actualizado_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                                      ON CONFLICT(product_id) DO UPDATE SET
                                      titulo=excluded.titulo, tienda_nombre=excluded.tienda_nombre, tienda_key=excluded.tienda_key,
                                      imagen_url=excluded.imagen_url, precio_min_centavos=excluded.precio_min_centavos,
                                      precio_max_centavos=excluded.precio_max_centavos, precio_desc_min_centavos=excluded.precio_desc_min_centavos,
                                      precio_desc_max_centavos=excluded.precio_desc_max_centavos, enlace=excluded.enlace,
                                      inventario=excluded.inventario, comision_bp=excluded.comision_bp,
                                      revision=excluded.revision, oculto=excluded.oculto, agregado=excluded.agregado,
                                      fuente=excluded.fuente, colaboracion_tipo=excluded.colaboracion_tipo,
                                      precio_plat_min_centavos=excluded.precio_plat_min_centavos,
                                      precio_plat_max_centavos=excluded.precio_plat_max_centavos,
                                      galeria_json=excluded.galeria_json,
                                      vista_en_sync=excluded.vista_en_sync, actualizado_at=excluded.actualizado_at""",
                                   (p.get('id'), *fila, galeria_json, self.sid, self.ahora))
                    if p.get('id') and RE_ID_IMAGEN.match(str(p['id'])):
                        # rev. 4: galería diferida ('g:<id>-<n>'): solo se registra; se baja cuando alguien abre la ficha
                        pedidos += [PedidoImagen('g', f"{p['id']}-{n}", u, 2, 'galeria') for n, u in enumerate(galeria)]
                    if url and p.get('id'):
                        ficha = db.execute('SELECT imagen_url, consultado_at FROM productos WHERE product_id=?',
                                           (p['id'],)).fetchone()
                        # C39: la vitrina solo aporta la imagen si la ficha ya se consultó y no trae foto
                        if ficha is not None and ficha['consultado_at'] is not None and not ficha['imagen_url']:
                            pedidos.append(PedidoImagen('p', str(p['id']), url, 0 if p['id'] in muestras else 1,
                                                        'vitrina'))
                if n_pag + c_pag:
                    self.alm.marcar_data_version(db)
                nuevos_v += n_pag
                cambios_v += c_pag
            self._encolar(pedidos)
            token = d.get('next_page_token') or ''
            if not prods or not token or token in vistos:
                break
            vistos.add(token)
        with self._tx() as db:
            self._poner_cursor(db, 'vitrina.at', str(self.ahora), self.ahora)
            self._poner_cursor(db, 'vitrina.rev', REV_VITRINA, self.ahora)
            db.execute("DELETE FROM sync_cursores WHERE clave = 'vitrina.error'")
        self.cambios += nuevos_v + cambios_v
        self._avance('vitrina', 1.0, hechos=total)
        return nuevos_v, cambios_v, total

    def _paso_detalles(self) -> tuple[int, int, int]:
        pend = self._leer("""SELECT application_id, product_id, tipo, main_order_id, detalle_espera_s FROM muestras
                             WHERE detalle_estado <> 'ok' AND detalle_intentos < 5
                               AND (detalle_reintento_at IS NULL OR detalle_reintento_at <= ?)""", (self.ahora,))
        c = self._c
        assert c is not None
        if not pend:
            with self._candado:
                c.pesos['detalles'] = PESO_DETALLES_SIN_PENDIENTES
        self._avance('detalles', 0.0, hechos=0, total=len(pend))
        hechos = camb = 0
        for k, m in enumerate(pend):
            body: dict[str, Any] = {'product_id': m['product_id'], 'application_type': m['tipo'] or 'FREE_SAMPLE',
                                    'application_id': m['application_id']}
            if body['application_type'] != 'FREE_SAMPLE' and m['main_order_id']:
                body['main_order_id'] = m['main_order_id']
            try:
                d = self._llamar('POST', P_DETALLE, None, body)
                sa = d.get('sample_application') or {}
                ct = int(sa.get('create_time') or 0) or None
                with self._tx() as db:
                    db.execute("""UPDATE muestras SET solicitada_at=?, detalle_estado='ok', detalle_reintento_at=NULL,
                                  detalle_espera_s=NULL WHERE application_id=?""", (ct, m['application_id']))
                    self.alm.marcar_data_version(db)
                hechos += 1
                camb += 1
                self.cambios += 1
            except ErrorApi as e:
                if e.decision in ('reautorizar', 'abortar'):
                    raise
                with self._tx() as db:
                    if e.transitorio:      # no gasta intentos: se reprograma con espera creciente (1 h -> 7 días)
                        espera = min(7 * DIA_S, max(3600, 2 * (m['detalle_espera_s'] or 1800)))
                        db.execute("UPDATE muestras SET detalle_estado='error', detalle_reintento_at=?, detalle_espera_s=? "
                                   "WHERE application_id=?", (self.ahora + espera, espera, m['application_id']))
                    else:
                        db.execute("UPDATE muestras SET detalle_estado='error', detalle_intentos=detalle_intentos+1 "
                                   "WHERE application_id=?", (m['application_id'],))
            self._avance('detalles', (k + 1) / len(pend), hechos=hechos)
        return 0, camb, hechos

    def _paso_videos(self) -> tuple[int, int, int]:
        """Portadas C4 (sin red) y, si la Display API está conectada, el paso «videos_tiktok» (rev. 5,
        sincronizador_videos.py) en la segunda mitad del avance. Las cifras del paso público siguen siendo las de C4."""
        if not self._videos_tiktok_activo():
            return self._portadas_c4()                  # sin Display API: exactamente como en la rev. 4
        self._escala['videos'] = (0.0, 0.5)
        try:
            r = self._portadas_c4()
        finally:
            self._escala.pop('videos', None)
        self._correr_videos_tiktok('videos', 0.5)
        return r

    def _portadas_c4(self) -> tuple[int, int, int]:
        """Registra los videos con ventas y su producto principal histórico. La columna heredada
        portada_product_id conserva la relación; las portadas visibles solo salen de la caché v:<content_id>."""
        filas = self._leer(_SQL_PORTADAS)
        nuevos = camb = 0
        with self._tx() as db:
            for f in filas:
                prev = db.execute('SELECT portada_product_id, primera_venta_at FROM videos WHERE content_id=?',
                                  (f['content_id'],)).fetchone()
                if prev is None:
                    nuevos += 1
                    db.execute('INSERT INTO videos(content_id, primera_venta_at, portada_product_id, actualizado_at) '
                               'VALUES (?,?,?,?)', (f['content_id'], f['primera_venta_at'], f['product_id'], self.ahora))
                elif (prev['portada_product_id'], prev['primera_venta_at']) != (f['product_id'], f['primera_venta_at']):
                    camb += 1
                    db.execute('UPDATE videos SET portada_product_id=?, primera_venta_at=?, actualizado_at=? '
                               'WHERE content_id=?', (f['product_id'], f['primera_venta_at'], self.ahora, f['content_id']))
            if nuevos + camb:
                self.alm.marcar_data_version(db)
        self.cambios += nuevos + camb
        self._avance('videos', 1.0, hechos=len(filas), total=len(filas))
        return nuevos, camb, len(filas)

    def _paso_imagenes(self) -> tuple[int, int, int]:
        """Encola (asíncrono) las imágenes que faltan o cambiaron con la cascada C39: ficha → vitrina. El avatar ya se
        encoló en el paso perfil."""
        filas = self._leer("""
            WITH ids AS (SELECT product_id, 0 AS prioridad FROM muestras
                         UNION ALL SELECT product_id, 1 FROM orden_lineas
                         UNION ALL SELECT product_id, 1 FROM vitrina),
                 x AS (SELECT product_id, MIN(prioridad) AS prioridad FROM ids WHERE product_id IS NOT NULL GROUP BY product_id)
            SELECT x.product_id, x.prioridad, p.imagen_url AS ficha, v.imagen_url AS vit, i.url_origen
            FROM x LEFT JOIN productos p USING (product_id) LEFT JOIN vitrina v USING (product_id)
                   LEFT JOIN imagenes i ON i.img_key = 'p:' || x.product_id""")
        pedidos = []
        for f in filas:
            url, fuente = (f['ficha'], 'ficha') if f['ficha'] else (f['vit'], 'vitrina')
            if not url:
                continue
            if f['url_origen'] and huella_url(f['url_origen']) == huella_url(url):
                continue
            pedidos.append(PedidoImagen('p', str(f['product_id']), url, int(f['prioridad']), fuente))
        self._encolar(pedidos)
        self._avance('imagenes', 1.0, hechos=len(pedidos), total=len(filas))
        return len(pedidos), 0, len(pedidos)

    def _paso_clasificacion(self) -> tuple[int, int, int]:
        camb, n = self._clasificar(parcial=False)
        self._avance('clasificacion', 1.0, hechos=n, total=n)
        return 0, camb, n

    # ------------------------------------------------------------------ clasificación (parcial y final)
    def _clasificar(self, parcial: bool) -> tuple[int, int]:
        """Una transacción: tiendas por shop_id (alias si cambió de nombre; 'shop:<id>' si solo se conoce el id) y
        clase/subestado con el cumplimiento VIGENTE y la solicitud efectiva. La final escribe en_cohorte_desde_at."""
        camb = 0
        with self._tx() as db:
            tiendas_cambio = 0
            pares = db.execute("""SELECT DISTINCT p.tienda_key, c.shop_id FROM cumplimientos c JOIN productos p USING (product_id)
                                  WHERE c.shop_id IS NOT NULL AND p.tienda_key IS NOT NULL""").fetchall()
            for tk, sid in pares:
                dueno = db.execute('SELECT tienda_key FROM tiendas WHERE shop_id=?', (sid,)).fetchone()
                if dueno is None:
                    tiendas_cambio += db.execute('UPDATE tiendas SET shop_id=? WHERE tienda_key=? AND shop_id IS NULL',
                                                 (sid, tk)).rowcount
                elif dueno[0] != tk:
                    if dueno[0].startswith('shop:'):          # ya sabemos el nombre: la clave por nombre manda
                        db.execute('UPDATE tiendas SET shop_id=NULL WHERE tienda_key=?', (dueno[0],))
                        db.execute('UPDATE tiendas SET shop_id=? WHERE tienda_key=?', (sid, tk))
                        db.execute('INSERT OR IGNORE INTO tienda_alias(alias, tienda_key, creado_at) VALUES (?,?,?)',
                                   (dueno[0], tk, self.ahora))
                        tiendas_cambio += 1
                    else:                                     # cambió de nombre: el nombre nuevo es alias de la clave vieja
                        tiendas_cambio += db.execute('INSERT OR IGNORE INTO tienda_alias(alias, tienda_key, creado_at) '
                                                     'VALUES (?,?,?)', (tk, dueno[0], self.ahora)).rowcount
                        nombre = db.execute('SELECT nombre FROM tiendas WHERE tienda_key=?', (tk,)).fetchone()[0]
                        tiendas_cambio += db.execute('UPDATE tiendas SET nombre=?, actualizado_at=? WHERE tienda_key=? '
                                                     'AND nombre IS NOT ?', (nombre, self.ahora, dueno[0], nombre)).rowcount
            for (sid,) in db.execute("""SELECT DISTINCT c.shop_id FROM cumplimientos c LEFT JOIN productos p USING (product_id)
                                        WHERE c.shop_id IS NOT NULL AND p.tienda_key IS NULL
                                          AND NOT EXISTS (SELECT 1 FROM tiendas t WHERE t.shop_id = c.shop_id)""").fetchall():
                tiendas_cambio += db.execute('INSERT OR IGNORE INTO tiendas(tienda_key, nombre, shop_id, primera_vez_at, '
                                             'actualizado_at) VALUES (?,?,?,?,?)',
                                             (f'shop:{sid}', f'Tienda …{sid[-4:]}', sid, self.ahora, self.ahora)).rowcount
            filas = db.execute("""SELECT m.application_id, m.estado_api, m.main_order_id, m.pistas_json, m.clase, m.subestado,
                                         m.primera_vez_at,
                                         COALESCE(m.solicitada_at, (SELECT o.creada_at FROM ordenes o
                                                                    WHERE o.order_id = m.main_order_id)) AS sol_real,
                                         c.estado AS cumpl
                                  FROM muestras m LEFT JOIN v_cumplimiento_vigente c USING (application_id)""").fetchall()
            escritas = 0
            for f in filas:
                aid = f['application_id']
                pistas = set(json.loads(f['pistas_json']))
                clase, sub, _regla = cl.clasificar_regla(f['estado_api'], f['main_order_id'], f['cumpl'], f['sol_real'],
                                                        self.ahora, pistas, primera_vez_at=f['primera_vez_at'],
                                                        parcial=parcial)
                if parcial and f['sol_real'] is None and f['subestado'] != 'sin_clasificar':
                    # Ya clasificada por una final: si la diferencia es solo la fecha provisional (regla 25 vs 26),
                    # se conserva lo que dijo la final (no oscila entre puntos de control y final).
                    final = cl.clasificar(f['estado_api'], f['main_order_id'], f['cumpl'], None, self.ahora, pistas,
                                          primera_vez_at=f['primera_vez_at'])
                    if final != (clase, sub):
                        continue
                # Una muestra que llegó en ESTA sync (la clasificó por primera vez un punto de control) es nueva para
                # el historial: si la final corrige la provisional, no es «cambió de estado» ni deja historial.
                nueva = f['subestado'] == 'sin_clasificar' or aid in self._nuevas_en_esta_sync
                if parcial and f['subestado'] == 'sin_clasificar':
                    self._nuevas_en_esta_sync.add(aid)
                if (clase, sub) != (f['clase'], f['subestado']):
                    escritas += 1
                    if not nueva:
                        camb += 1
                        if f['clase'] != clase:
                            db.execute('INSERT INTO muestras_historial(application_id, sync_id, campo, antes, despues, '
                                       'at) VALUES (?,?,?,?,?,?)', (aid, self.sid, 'clase', f['clase'], clase, self.ahora))
                    db.execute('UPDATE muestras SET clase=?, subestado=?, clase_desde_at=CASE WHEN clase<>? THEN ? '
                               'ELSE clase_desde_at END WHERE application_id=?', (clase, sub, clase, self.ahora, aid))
            cohorte = 0 if parcial else db.execute(_SQL_COHORTE, (self.ahora,)).rowcount
            if not parcial:
                # Para el aviso de fin de sync de hub.py (BUILD §6.3.4, 01 §5.5): las que ENTRARON por vencer en esta sync.
                self.resumen['muestras_nuevas_por_vencer'] = [r[0] for r in db.execute(_SQL_NUEVAS_POR_VENCER,
                                                                                       (self.ahora,))]
            if escritas or cohorte or tiendas_cambio:
                self.alm.marcar_data_version(db)
        self.cambios += camb
        if escritas or tiendas_cambio:
            self.secciones.update(('muestras', 'tiendas'))
        return camb, len(filas)


def crear_sincronizador(dep: Dependencias) -> Sincronizador:
    return _Sincronizador(dep)


__all__: list[str] = ['crear_sincronizador', 'ORDEN_PASOS', 'PASOS_TABLA', 'PASOS_EXTRA', 'PESOS', 'TEXTOS',
                      'TEXTO_LISTO', 'SECCIONES_PC1', 'SECCIONES_PC2', 'huella_url', 'ventanas', 'restar_cobertura',
                      'ORDEN_FASES', 'TEXTOS_FASES', 'urls_galeria', 'huella_galeria', 'REV_VITRINA']
