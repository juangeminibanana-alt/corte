"""Composición del hub (BUILD_SPEC §6.3.1, rev. 3.1): `iniciar_hub(op)` → `Hub` (implementa `HubProto` y `Coordinador`).

Orden EXACTO de §6.3.1 (nada de red ni de PIL antes de que el servidor escuche):
 1. validar OpcionesHub (con `sys.frozen`: `dev`, `fuente_demo='fixtures_reales'` y `dir_ui` → ValueError) · rutas
 2. config · reloj · bus
 3. almacén (DDL/migración, semillas, reparar) · `bus.iniciar_versiones`
 4. bóveda (real DPAPI · demo memoria · autoprueba DPAPI temporal)
 5. transporte (real · demo con la fuente · autoprueba sintéticos) · cliente
 6. imágenes (sin iniciar; descargador de demo salvo en real)
 7. estado local + `sembrar()` · analítica
 8. Hub · auth (recibe al Hub como Coordinador) · rev. 5: bóveda, transporte y servicio de la Display API (métricas
    de tus videos; `hub.display`), enlazados al sincronizador con `fijar_display` y al servidor de interfaz con
    `/api/display/*` (despachador local) y `GET /oauth/tiktok`
 9. Dependencias · sincronizador · planificador + tareas (auto_sync, recordatorios, volcado, enlaces_cortos,
    retencion, purga_states) · `configurar(sync_auto, intervalo)`
10. despachador · LAN · `fijar_despachador`
11. bind SÍNCRONO del servidor de interfaz → «listo» (`t_listo_ms`) → `iniciar_hub` devuelve
12. en segundo plano: LAN (salvo sin_lan/demo/autoprueba) · planificador · a los 2 s `imagenes.iniciar()` · sync de
    arranque a los `retraso_sync_s` (regla de 03 §4.4: solo si la última `ok` tiene más de 15 min)
`detener(tope_s)`: cancelar sync → planificador → LAN → imágenes (vuelca accesos) → servidor → `almacen.cerrar()`,
todo dentro del tope (lo que no termine a tiempo queda en hilos daemon).

Coordinador (03 §2.6): `mutacion_segura` = cancelar la sync y esperar hasta 40 s · vaciar la cola de imágenes ·
bajo `candado_auth`: mutar la bóveda y borrar (el almacén hace un BEGIN IMMEDIATE con época += 1) · purgar la caché ·
`datos.cambiaron` con todas las secciones.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping

from . import config, registro
from .almacen import crear_almacen
from .analitica import crear_analitica
from .api import rutas as rutas_api
from .api.estaticos import Estaticos
from .api.rutas_display import crear_despachador_display
from .api.servidor import ServidorLocal
from .api.sesion import GestorSesiones
from .api.sse import CanalEventos
from .auth import crear_auth
from .boveda import crear_boveda
from .comun import TZ_MX
from .demo import crear_descargador_demo, crear_transporte_demo
from .errores import ErrorDominio
from .eventos import SECCIONES, crear_bus
from .imagenes import crear_imagenes
from .interfaces import (Almacen, Analitica, ArchivoConfig, Boveda, Bus, ClienteTikTok, Contexto, Dependencias,
                         EstadoLocal, GanchosVentana, HubProto, Imagenes, Json, OpcionesHub, PedidoImagen, Reloj, Rutas)
from .lan import crear_servicio_lan
from .local import crear_estado_local
from .planificador import crear_planificador
from .productos_evidencia import ServicioEvidencia
from .reloj import crear_reloj
from .sincronizador import crear_sincronizador
from .tiktok.carga_video import CargaVideosShop
from .tiktok.agenda_publicaciones import AgendaPublicaciones
from .tiktok.cliente import crear_cliente
from .tiktok.marketplace import MarketplaceCreator
from .tiktok.publicaciones import PublicacionesShop
from .tiktok.registro_publicacion import RegistroPublicacion
from .tiktok.showcase import ShowcaseCreator
from .tiktok.affiliate_links import AffiliateLinksCreator
from .tiktok.transporte import crear_transporte_real
from .tiktok_dev.boveda import crear_boveda_display
from .tiktok_dev.servicio import crear_servicio_display, crear_transporte_display

_log = logging.getLogger('creatorhub.hub')

# ------------------------------------------------------------------ tiempos (BUILD §6.3.1, 03 §2.5 y §4.4)
RETRASO_IMAGENES_S = 2.0                 # C3: PIL solo después de «listo»
TIC_S = 30
VOLCADO_S = 60
ENLACES_S = 60
RETENCION_S = 86400
SYNC_ARRANQUE_SI_MAS_DE_S = 15 * 60
ESPERA_CANCELAR_SYNC_S = 40.0            # 03 §2.6: cancelar + join de 40 s
RETENCION_OPS_S = 30 * 86400
MAX_API_ERRORES = 500
ENLACES_POR_TIC = 5

TITULO_MUESTRA_NUEVA = 'Llegó una muestra nueva'
RUTA_MUESTRAS = '#/muestras'
_DIAS = ('lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom')
_MESES = ('ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic')

# Enlaces cortos de video (C30, §6.3.4)
HOSTS_ENLACE_CORTO = frozenset({'vm.tiktok.com', 'vt.tiktok.com', 'www.tiktok.com'})
MAX_REDIRECCIONES_ENLACE = 3
TIMEOUT_ENLACE_S = 5
_RE_CONTENT_ID = re.compile(r'/video/(\d{8,25})(?:[/?#]|$)')
_RE_RUTA_IMG = re.compile(r'^/img/([pagmv])/(\d{1,25}(?:-\d{1,2})?|cuenta)$')  # rev. 4: g y m · rev. 5: portada v


def fecha_corta(epoch: int | None) -> str | None:
    """'sáb 21 nov' en hora de México (UTC−6 fijo), como los textos de 01 §5.5."""
    if epoch is None:
        return None
    d = dt.datetime.fromtimestamp(int(epoch), TZ_MX)
    return f'{_DIAS[d.weekday()]} {d.day} {_MESES[d.month - 1]}'


def _abrir_en_navegador(url: str) -> None:
    os.startfile(url)                    # type: ignore[attr-defined]  (solo Windows; la URL ya pasó la lista de §6.4)


class _RedireccionAcotada(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECCIONES_ENLACE

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        u = urllib.parse.urlsplit(newurl)
        if u.scheme != 'https' or (u.hostname or '').lower() not in HOSTS_ENLACE_CORTO:
            raise urllib.error.HTTPError(newurl, code, 'redirección fuera de TikTok', headers, fp)
        nuevo = super().redirect_request(req, fp, code, msg, headers, newurl)
        if nuevo is not None:
            nuevo.method = req.get_method()      # HEAD sigue siendo HEAD; nunca se manda cuerpo
        return nuevo


def content_id_de_url(url: str) -> str | None:
    m = _RE_CONTENT_ID.search(urllib.parse.urlsplit(url).path + '/')
    return m.group(1) if m else None


def resolver_enlace_corto(enlace: str) -> str | None:
    """`vm.tiktok.com/…` → content_id siguiendo como máximo 3 redirecciones dentro de los hosts de TikTok (HEAD y, si
    no lo aceptan, GET sin leer el cuerpo; tope de 5 s). None si no se pudo. Nunca registra el enlace."""
    u = urllib.parse.urlsplit(enlace.strip())
    if u.scheme != 'https' or (u.hostname or '').lower() not in HOSTS_ENLACE_CORTO:
        return None
    directo = content_id_de_url(enlace)
    if directo:
        return directo
    abridor = urllib.request.build_opener(_RedireccionAcotada())
    for metodo in ('HEAD', 'GET'):
        req = urllib.request.Request(enlace, method=metodo, headers={'User-Agent': f'CreatorHub/{config.VERSION}'})
        try:
            with abridor.open(req, timeout=TIMEOUT_ENLACE_S) as resp:
                cid = content_id_de_url(resp.geturl())
                if cid:
                    return cid
        except urllib.error.HTTPError as e:
            cid = content_id_de_url(getattr(e, 'filename', '') or '')
            if cid:
                return cid
            if e.code not in (403, 405):
                return None
        except (urllib.error.URLError, OSError, ValueError) as e:
            _log.info('No se pudo resolver un enlace corto de video (%s)', type(e).__name__)
            return None
    return None


def _con_tope(nombre: str, fn: Callable[[], Any], tope_s: float) -> bool:
    """Corre `fn` en un hilo daemon y espera como máximo `tope_s`. True si terminó a tiempo."""
    hecho = threading.Event()

    def correr() -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001 - el cierre nunca se detiene por una pieza
            _log.exception('Error al detener %s', nombre)
        finally:
            hecho.set()

    threading.Thread(target=correr, name=f'detener-{nombre}', daemon=True).start()
    if not hecho.wait(max(0.01, tope_s)):
        _log.warning('%s no terminó dentro del tope de cierre', nombre)
        return False
    return True


class Hub:
    """Implementa `HubProto` (windows-shell programa contra esto) y `Coordinador` (auth y api lo usan para mutar)."""

    def __init__(self, op: OpcionesHub, rutas: Rutas, cfg: ArchivoConfig, reloj: Reloj, bus: Bus, almacen: Almacen,
                 boveda: Boveda, cliente: ClienteTikTok | None, imagenes: Imagenes, local: EstadoLocal,
                 analitica: Analitica) -> None:
        self.op = op
        self.modo = op.modo
        self.rutas = rutas
        self.cfg = cfg
        self.reloj = reloj
        self.bus = bus
        self.almacen = almacen
        self.boveda = boveda
        self.cliente = cliente
        self.imagenes = imagenes
        self.local = local
        self.analitica = analitica
        # se enlazan después (orden de §6.3.1)
        self.auth: Any = None
        self.marketplace = (MarketplaceCreator(cliente, boveda, lambda: self.auth.conexion())
                            if op.nube and op.modo == 'real' and cliente is not None else None)
        self.showcase = (ShowcaseCreator(cliente, boveda, lambda: self.auth.conexion(), almacen, reloj.ahora)
                         if op.nube and op.modo == 'real' and cliente is not None else None)
        self.affiliate_links = (AffiliateLinksCreator(cliente, boveda, lambda: self.auth.conexion())
                                if op.nube and op.modo == 'real' and cliente is not None else None)
        self.publicaciones_shop = (PublicacionesShop(cliente, boveda, lambda: self.auth.conexion(), almacen,
                                                     RegistroPublicacion(almacen, reloj.ahora))
                                   if op.nube and op.modo == 'real' and cliente is not None else None)
        self.carga_videos_shop = (CargaVideosShop(cliente, self.publicaciones_shop)
                                  if cliente is not None and self.publicaciones_shop is not None else None)
        self.agenda_shop = (AgendaPublicaciones(self.publicaciones_shop, almacen, reloj.ahora)
                            if self.publicaciones_shop is not None else None)
        self.sincronizador: Any = None
        self.planificador: Any = None
        self.lan: Any = None
        self.despachador: Any = None
        self.display: Any = None                 # rev. 5: ServicioDisplay (Display API; solo la ventana local)
        self.ganchos: GanchosVentana | None = None
        # servidor de interfaz
        self.sesiones = GestorSesiones()
        self.canal = CanalEventos(bus, reloj)
        self.servidor: ServidorLocal | None = None
        self.puerto_ui: int = 0
        self.puerto_respaldo: bool = False
        self.t0 = time.monotonic()
        self.t_listo_ms: float | None = None
        # colaboradores sustituibles en pruebas (nunca red en las pruebas)
        self.abrir_url: Callable[[str], None] = _abrir_en_navegador
        self.resolver_enlace: Callable[[str], str | None] = resolver_enlace_corto
        self._candado_mutacion = threading.RLock()
        self.evidencia = ServicioEvidencia(almacen, imagenes, bus, reloj, self._candado_mutacion)
        self._parar = threading.Event()
        self._hilos: list[threading.Thread] = []
        self._sub_eventos: Any = None
        self._avisadas: set[int] = set()
        self._detenido = False
        self._registro_propio = False
        self.cliente_nativo: Any = None

    # ================================================================== HubProto
    def url_arranque(self) -> str:
        """'http://127.0.0.1:<p>/boot?t=<token de 60 s y un solo uso>'."""
        return f'http://{config.HOST_UI}:{self.puerto_ui}/boot?t={self.sesiones.crear_token()}'

    def sincronizar_ahora(self, origen: str = 'usuario') -> None:
        if self.cliente_nativo is not None:
            try:
                self.cliente_nativo.remoto('POST', '/api/sync', {'tipo': 'incremental'})
                self.cliente_nativo.despertar.set()
            except Exception:
                _log.info('No se pudo solicitar la sincronización en Google')
            return
        try:
            self.sincronizador.iniciar('incremental', origen)
        except ErrorDominio as e:
            _log.info('No se inició la sincronización pedida (%s)', e.codigo)

    def ruta_imagen_original(self, ruta_img: str) -> str | None:
        """'/img/p/<id>?v=…' → archivo original de la caché (para «Guardar imagen»), o None."""
        if not isinstance(ruta_img, str):
            return None
        if self.cliente_nativo is not None and ruta_img.startswith('/img/'):
            return self.cliente_nativo.archivo_imagen(ruta_img)
        m = _RE_RUTA_IMG.match(urllib.parse.urlsplit(ruta_img).path)
        if m is None:
            return None
        return self.imagenes.ruta_original(m.group(1), m.group(2))

    def registrar_ganchos(self, ganchos: GanchosVentana) -> None:
        self.ganchos = ganchos

    def ajustes_pc(self) -> Json:
        """AjustesPc completo: config.json + `iniciar_con_windows`/`…_bloqueado` según los ganchos del shell."""
        a = config.ajustes_pc_guardados(self.cfg)
        if a.get('sync_intervalo_min') not in config.INTERVALOS_SYNC_MIN:
            a['sync_intervalo_min'] = config.AJUSTES_PC_OMISION['sync_intervalo_min']
        bloqueado = False
        if self.ganchos is not None:
            try:
                activo, bloqueado = self.ganchos.estado_inicio_windows()
                a['iniciar_con_windows'] = bool(activo)
            except Exception:  # noqa: BLE001
                _log.warning('No se pudo leer el inicio con Windows', exc_info=True)
        return {'sync_auto': bool(a['sync_auto']), 'sync_intervalo_min': int(a['sync_intervalo_min']),
                'segundo_plano': a['segundo_plano'], 'iniciar_con_windows': bool(a['iniciar_con_windows']),
                'iniciar_con_windows_bloqueado': bool(bloqueado), 'densidad': a['densidad']}

    def detener(self, tope_s: float = 3.0) -> None:
        if self._detenido:
            return
        self._detenido = True
        limite = time.monotonic() + max(0.1, float(tope_s))

        def resto(fraccion: float = 1.0) -> float:
            return max(0.05, (limite - time.monotonic()) * fraccion)

        self._parar.set()
        if self.cliente_nativo is not None:
            self.cliente_nativo.detener()
        if self.sincronizador is not None:
            _con_tope('sincronizacion', lambda: self.sincronizador.cancelar(resto(0.3)), resto(0.35))
        if self.planificador is not None:
            _con_tope('planificador', self.planificador.detener, resto(0.3))
        if self.lan is not None:
            _con_tope('lan', self.lan.detener, resto(0.3))
        _con_tope('imagenes', self.imagenes.detener, resto(0.4))
        if self.servidor is not None:
            servidor = self.servidor
            _con_tope('servidor', lambda: servidor.detener(resto(0.5)), resto(0.6))
        sub = self._sub_eventos
        if sub is not None:
            with contextlib.suppress(Exception):
                sub.cerrar()
        candado = getattr(self.boveda, 'candado_auth', None)
        if candado is not None and candado.acquire(timeout=resto(0.3)):     # una escritura de credenciales en curso
            candado.release()
        candado = getattr(getattr(self.display, 'boveda', None), 'candado', None)
        if candado is not None and candado.acquire(timeout=resto(0.2)):     # ídem en la bóveda de la Display API
            candado.release()
        _con_tope('almacen', self.almacen.cerrar, resto(0.9))
        for h in self._hilos:
            if h is not threading.current_thread():
                h.join(max(0.0, min(0.2, limite - time.monotonic())))
        _log.info('Hub detenido')
        if self._registro_propio:
            registro.cerrar_registro()

    # ================================================================== Coordinador (03 §2.6)
    def mutacion_segura(self, mutar_boveda: Callable[[], None] | None,
                        borrar: str) -> None:
        if borrar not in ('nada', 'tiktok', 'todo', 'imagenes'):
            raise ValueError(f'alcance desconocido: {borrar!r}')
        with self._candado_mutacion:
            if self.sincronizador is not None:
                self.sincronizador.cancelar(ESPERA_CANCELAR_SYNC_S)
            try:
                self.imagenes.vaciar_cola()
            except Exception:  # noqa: BLE001
                _log.exception('No se pudo vaciar la cola de imágenes')
            candado = getattr(self.boveda, 'candado_auth', None) or getattr(self.boveda, 'candado', None)
            with (candado if candado is not None else contextlib.nullcontext()):
                if mutar_boveda is not None:
                    mutar_boveda()
                if borrar != 'nada':
                    self.almacen.borrar(borrar)           # BEGIN IMMEDIATE: época += 1, borrar y dv_pendiente
            if borrar != 'nada':
                try:
                    self.imagenes.purgar(self._max_mb())  # sin filas que los referencien, los archivos se van
                except Exception:  # noqa: BLE001
                    _log.exception('No se pudo purgar la caché de imágenes')
                self.bus.notificar_cambio(self.almacen.versiones(), list(SECCIONES))

    # ================================================================== lo que usa el Despachador
    def salud(self) -> Json:
        try:
            self.almacen.versiones()
            db_ok = True
        except Exception:  # noqa: BLE001
            db_ok = False
        return {'ok': True, 'version': config.VERSION, 'protocolo': 1,
                'modo': 'real' if self.modo == 'real' else 'demo', 'hora_servidor': int(self.reloj.ahora()),
                'uptime_s': int(time.monotonic() - self.t0), 'db_ok': db_ok}

    def _hay_datos(self) -> bool:
        try:
            with self.almacen.lector() as c:
                r = c.execute('SELECT EXISTS(SELECT 1 FROM muestras) OR EXISTS(SELECT 1 FROM ordenes)').fetchone()
            return bool(r[0])
        except Exception:  # noqa: BLE001
            return False

    def sesion(self, ctx: Contexto) -> Json:
        """SessionResponse (compone auth + sync + almacén + LAN). `lan` y `servidor` solo para la ventana local."""
        estado = self.sincronizador.estado()
        dv, lr, _ir = self.almacen.versiones()
        local = ctx.origen == 'ui'
        conexion = self.auth.conexion()
        cuenta = self.auth.cuenta()
        vitrina, vitrina_escribir = (self.showcase.capacidades(conexion)
                                    if local and self.showcase is not None else (False, False))
        r: Json = {
            'cuenta': cuenta, 'conexion': conexion, 'sync': estado,
            'datos': {'data_version': dv, 'local_rev': lr, 'ultima_sync_ok_at': estado.get('ultima_ok_at'),
                      'hay_datos': self._hay_datos()},
            'plataforma': 'windows' if local else ctx.plataforma,
            'modo': 'real' if self.modo == 'real' else 'demo',
            'capacidades': {'auth': local, 'lan_admin': local and not self.op.nube,
                            'portapapeles': local and not self.op.nube,
                            'escribir': ctx.puede_escribir, 'sincronizar': ctx.puede_escribir,
                            'catalogo_videos': True,
                            'display_video_actualizar': bool(
                                self.op.nube and local and conexion.get('estado') == 'conectada'
                                and self.display is not None
                                and self.display.puede_actualizar_video((cuenta or {}).get('username') or '')),
                            'vitrina_creator': vitrina,
                            'vitrina_creator_escribir': vitrina_escribir,
                            'enlaces_afiliado_creator': (local and self.affiliate_links is not None
                                                         and self.affiliate_links.disponible(conexion)),
                            'marketplace_creator': (local and self.marketplace is not None
                                                    and self.marketplace.disponible(conexion))},
        }
        if local:
            r['lan'] = self.lan.resumen() if self.lan is not None else {
                'activo': False, 'dispositivos_activos': 0, 'puerto': None}
            r['servidor'] = {'version': config.VERSION, 'puerto_ui': self.puerto_ui,
                             'puerto_respaldo': self.puerto_respaldo}
        if self.op.nube:
            r['cloud'] = True
        return r

    def uso_datos(self) -> Json:
        tamano = getattr(self.almacen, 'tamano_bytes', None)
        if callable(tamano):
            datos = int(tamano())
        else:
            datos = sum(os.path.getsize(self.almacen.ruta + s) for s in ('', '-wal', '-shm')
                        if os.path.isfile(self.almacen.ruta + s))
        registros = 0
        with contextlib.suppress(OSError):
            for n in os.listdir(self.rutas.logs):
                p = os.path.join(self.rutas.logs, n)
                if os.path.isfile(p):
                    registros += os.path.getsize(p)
        return {'datos_bytes': datos, 'imagenes_bytes': int(self.imagenes.uso_bytes()), 'registros_bytes': registros}

    def cambiar_ajustes_pc(self, cambios: Mapping[str, Any]) -> Json:
        """PATCH /api/ajustes/pc (AjustesPcCambios). `iniciar_con_windows_bloqueado` no se puede escribir."""
        validos: dict[str, Callable[[Any], bool]] = {
            'sync_auto': lambda v: isinstance(v, bool),
            'sync_intervalo_min': lambda v: not isinstance(v, bool) and v in config.INTERVALOS_SYNC_MIN,
            'segundo_plano': lambda v: v is None or isinstance(v, bool),
            'iniciar_con_windows': lambda v: isinstance(v, bool),
            'densidad': lambda v: v in ('comoda', 'compacta'),
        }
        if not isinstance(cambios, Mapping):
            raise ErrorDominio('parametros_invalidos', 'Los datos de la petición no son válidos.', http=400)
        for k, v in cambios.items():
            if k not in validos or not validos[k](v):
                raise ErrorDominio('parametros_invalidos', 'Ese ajuste no es válido.', http=422, detalle={'campo': k})
        if 'iniciar_con_windows' in cambios and self.ganchos is not None:
            self.ganchos.aplicar_inicio_windows(bool(cambios['iniciar_con_windows']))
        if cambios:
            self.cfg.escribir({'ajustes_pc': dict(cambios)})
        if ('sync_auto' in cambios or 'sync_intervalo_min' in cambios) and self.planificador is not None:
            a = self.ajustes_pc()
            self.planificador.configurar(a['sync_auto'], a['sync_intervalo_min'])
        return self.ajustes_pc()

    def abrir_enlace(self, url: str) -> None:
        try:
            self.abrir_url(url)
        except OSError as e:
            _log.warning('No se pudo abrir el enlace en el navegador (%s)', type(e).__name__)
            raise ErrorDominio('error_interno', 'No pudimos abrir tu navegador. Inténtalo de nuevo.', http=500) from None

    def borrar_datos(self, alcance: str) -> None:
        """POST /api/datos/borrar (03 §3.4). 'todo' además borra credenciales, identidad TLS, config.json y registros, y
        deja la PC como nueva: ajustes por omisión en el planificador y las 11 plantillas sembradas otra vez (§4.3)."""
        self.mutacion_segura(self._vaciar_boveda if alcance == 'todo' else None, alcance)
        if alcance == 'todo':
            if self.display is not None:                    # rev. 5: también la bóveda de la Display API
                try:
                    self.display.olvidar_todo()
                except Exception:  # noqa: BLE001
                    _log.exception('No se pudo borrar la conexión de la Display API')
            if self.lan is not None:
                with contextlib.suppress(Exception):
                    self.lan.detener()
            try:
                from .lan import identidad_tls
                identidad_tls.borrar(self.rutas)
            except Exception:  # noqa: BLE001
                _log.exception('No se pudo borrar la identidad TLS')
            try:
                self.cfg.escribir({'ajustes_pc': None, 'ventana': None, 'lan': None, 'imagenes': None})
            except Exception:  # noqa: BLE001
                _log.exception('No se pudo vaciar config.json')
            if self.planificador is not None:                # config.json vacío = ajustes por omisión (C36)
                a = self.ajustes_pc()
                self.planificador.configurar(a['sync_auto'], a['sync_intervalo_min'])
            try:
                self.local.sembrar()     # «todo» borró plantillas y preferencias: vuelven las 11 predeterminadas (§4.3)
            except Exception:  # noqa: BLE001
                _log.exception('No se pudieron volver a sembrar las plantillas')
            self._vaciar_registros()
            try:
                self.bus.publicar({'tipo': 'conexion.cambio', 'conexion': self.auth.conexion()})
            except Exception:  # noqa: BLE001
                _log.warning('No se pudo publicar conexion.cambio tras borrar todo')
        _log.info('Datos borrados (alcance %s)', alcance)

    def _vaciar_boveda(self) -> None:
        eliminar = getattr(self.boveda, 'eliminar', None)
        if callable(eliminar):
            eliminar()
            return
        conservar = ('generacion', 'epoca_credenciales')
        self.boveda.mutar(lambda d: [d.pop(k) for k in list(d) if k not in conservar], cambia_credenciales=True)

    def _vaciar_registros(self) -> None:
        actual = registro.ruta_registro_actual()
        with contextlib.suppress(OSError):
            for n in os.listdir(self.rutas.logs):
                p = os.path.join(self.rutas.logs, n)
                if not os.path.isfile(p):
                    continue
                try:
                    if actual and os.path.normcase(os.path.abspath(p)) == os.path.normcase(os.path.abspath(actual)):
                        with open(p, 'r+b') as f:
                            f.truncate(0)
                    else:
                        os.remove(p)
                except OSError:
                    pass

    def encolar_avatar(self) -> None:
        """Tras el canje: encola la foto de la cuenta para el «¿Eres tú?» (Cuenta.avatar llega sin esperar a la sync)."""
        try:
            with self.almacen.lector() as c:
                r = c.execute('SELECT avatar_url FROM cuenta WHERE id = 1').fetchone()
            if r is not None and r[0]:
                self.imagenes.encolar([PedidoImagen(tipo='a', ref_id='cuenta', url=str(r[0]), prioridad=0,
                                                    fuente='perfil')])
        except Exception as e:  # noqa: BLE001
            _log.info('No se pudo encolar la foto de la cuenta (%s)', type(e).__name__)

    def sincronizar_tras_conectar(self) -> None:
        try:
            self.sincronizador.iniciar('completa', 'usuario')
        except ErrorDominio as e:
            _log.info('No se inició la sincronización tras importar (%s)', e.codigo)

    def _max_mb(self) -> int:
        v = self.cfg.leer('imagenes', {})
        mb = v.get('max_mb') if isinstance(v, Mapping) else None
        return int(mb) if isinstance(mb, int) and not isinstance(mb, bool) and mb > 0 else config.IMAGENES_MAX_MB_PC

    # ================================================================== tareas del planificador
    def registrar_tareas(self) -> None:
        p = self.planificador
        p.registrar_tarea('auto_sync', TIC_S, lambda: self.cliente_nativo.despertar.set()
                         if self.cliente_nativo is not None else self.sincronizador.iniciar('incremental', 'auto'))
        p.registrar_tarea('recordatorios', TIC_S, self._tarea_recordatorios)
        p.registrar_tarea('volcado', VOLCADO_S, self._tarea_volcado)
        if self.modo == 'real':                     # §6.3.4: nunca en demo ni autoprueba
            p.registrar_tarea('enlaces_cortos', ENLACES_S, self._tarea_enlaces_cortos)
        p.registrar_tarea('retencion', RETENCION_S, self._tarea_retencion)
        p.registrar_tarea('purga_states', TIC_S, self._tarea_purga_states)
        if self.agenda_shop is not None:
            p.registrar_tarea('publicar_videos_programados', TIC_S, self._tarea_publicar_video)

    def _tarea_publicar_video(self) -> None:
        with self._candado_mutacion:
            if not self._parar.is_set() and self.agenda_shop is not None:
                self.agenda_shop.ejecutar_siguiente()

    def _tarea_recordatorios(self) -> None:
        """C44: publica recordatorio.vencido (marca notificado_at) y hace parpadear la ventana. Nunca un globo."""
        vencidos = self.local.recordatorios_vencidos(self.reloj.ahora())
        for r in vencidos:
            self.bus.publicar({'tipo': 'recordatorio.vencido', 'recordatorio': r})
        g = self.ganchos
        if vencidos and g is not None:
            try:
                g.parpadear()                       # FlashWindowEx solo si la ventana no tiene el foco (shell)
            except Exception:  # noqa: BLE001
                _log.warning('No se pudo hacer parpadear la ventana', exc_info=True)

    def _tarea_volcado(self) -> None:
        self.imagenes.volcar_accesos()
        if self.lan is not None:
            self.lan.volcar_accesos()

    def _tarea_enlaces_cortos(self) -> None:
        for plan_id, enlace in list(self.local.enlaces_por_resolver())[:ENLACES_POR_TIC]:
            if self._parar.is_set():
                return
            cid = self.resolver_enlace(enlace)
            if cid:
                self.local.guardar_content_id(plan_id, cid)

    def _tarea_retencion(self) -> None:
        """03 §3.4: caché de imágenes (LRU 400 MB y 90 días), ops_aplicadas 30 días, api_errores últimas 500."""
        self.imagenes.purgar(self._max_mb())
        ahora = self.reloj.ahora()
        with self.almacen.escritor() as c:
            c.execute('DELETE FROM ops_aplicadas WHERE recibida_at < ?', (ahora - RETENCION_OPS_S,))
            c.execute('DELETE FROM api_errores WHERE id <= (SELECT MAX(id) - ? FROM api_errores)', (MAX_API_ERRORES,))

    def _tarea_purga_states(self) -> None:
        self.auth.purgar_states()
        reintentar = getattr(self.boveda, 'reintentar_pendiente', None)
        if callable(reintentar):
            reintentar()                            # 03 §7.1: el .nuevo que no pudo reemplazar se reintenta en el tic
        if self.display is not None:
            self.display.purgar()                   # rev. 5: intentos de conexión vencidos + .nuevo de su bóveda

    # ================================================================== rev. 5: Display API (solo la ventana local)
    def secretos_vivos(self) -> tuple[str, ...]:
        """Los de la bóveda de TikTok Shop y los de la Display API (para el registro y los errores)."""
        vivos = tuple(self.boveda.secretos_vivos())
        if self.display is not None:
            try:
                vivos += tuple(self.display.secretos_vivos())
            except Exception:  # noqa: BLE001
                pass
        if self.cliente_nativo is not None:
            vivos += tuple(self.cliente_nativo.vault.secretos_vivos())
        return vivos

    def callback_oauth(self, consulta: str) -> tuple[int, bytes]:
        """GET /oauth/tiktok (lo encamina el servidor de interfaz): (status, página HTML)."""
        if self.display is None:
            from .tiktok_dev.servicio import PAG_NO_CORRESPONDE, pagina_html
            return 404, pagina_html(PAG_NO_CORRESPONDE, False)
        return self.display.callback(consulta)

    # ================================================================== fin de sync con novedades (§6.3.4)
    def _nuevas_por_vencer(self, sync_id: int) -> list[str]:
        with self.almacen.lector() as c:
            r = c.execute('SELECT resumen_json FROM sync_ejecuciones WHERE sync_id = ?', (sync_id,)).fetchone()
        try:
            resumen = json.loads(r[0] or '{}') if r is not None else {}
        except ValueError:
            return []
        ids = resumen.get('muestras_nuevas_por_vencer') if isinstance(resumen, dict) else None
        return [str(i) for i in ids] if isinstance(ids, list) else []

    def avisar_fin_sync(self, estado: Json) -> bool:
        """Si la ventana está oculta y llegó al menos una muestra nueva por vencer: UNA notificación por sync."""
        g = self.ganchos
        sid = estado.get('sync_id') if isinstance(estado, Mapping) else None
        if g is None or not isinstance(sid, int) or sid in self._avisadas:
            return False
        self._avisadas.add(sid)
        try:
            if g.ventana_visible():
                return False
            ids = self._nuevas_por_vencer(sid)
            if not ids:
                return False
            m = self.analitica.muestra_detalle(ids[0]).get('muestra') or {}
        except Exception:  # noqa: BLE001
            _log.warning('No se pudo preparar el aviso de muestra nueva', exc_info=True)
            return False
        prod = m.get('producto') or {}
        producto = prod.get('titulo_corto') or prod.get('titulo') or 'Una muestra'
        tienda = (m.get('tienda') or {}).get('nombre') or 'tu tienda'
        fecha = fecha_corta(m.get('fecha_limite_at'))
        texto = f'{producto} de {tienda}. Vence el {fecha}.' if fecha else f'{producto} de {tienda}.'
        try:
            g.notificar(TITULO_MUESTRA_NUEVA, texto, RUTA_MUESTRAS)
        except Exception:  # noqa: BLE001
            _log.warning('No se pudo mostrar el aviso de muestra nueva', exc_info=True)
            return False
        return True

    def _bucle_eventos(self) -> None:
        while not self._parar.is_set():
            sub = self._sub_eventos
            if sub is None:
                return
            try:
                ev = sub.siguiente(1.0)
            except Exception:  # noqa: BLE001
                _log.exception('Error leyendo el bus en el hub')
                continue
            if ev is not None:
                if ev.get('tipo') == 'sync.fin':
                    self.avisar_fin_sync(ev.get('estado') or {})
            elif getattr(sub, 'cerrada', False) and not self._parar.is_set():
                self._sub_eventos = self.bus.suscribir(1000)

    # ================================================================== arranque (pasos 11 y 12)
    def iniciar_servidor(self, dir_ui: str) -> None:
        self.despachador = self.despachador or rutas_api.crear_despachador(self)
        self.servidor = ServidorLocal(self.despachador, self.sesiones, Estaticos(dir_ui), self.canal, self.op.puerto_ui,
                                      dev=self.op.dev, despachador_local=(self.despachador if self.op.cliente_nube
                                                                        else crear_despachador_display(self)),
                                      oauth=self.callback_oauth)
        self.puerto_ui = self.servidor.puerto
        self.puerto_respaldo = self.servidor.respaldo
        self.servidor.iniciar()

    def _arrancar_en_fondo(self) -> None:
        listo = time.monotonic()
        self._sub_eventos = self.bus.suscribir(1000)
        eventos = threading.Thread(target=self._bucle_eventos, name='hub-eventos', daemon=True)

        def correr() -> None:
            con_lan = not self.op.sin_lan and self.modo == 'real'
            if con_lan and self.lan is not None:
                try:
                    self.lan.iniciar_si_activo()
                except Exception:  # noqa: BLE001
                    _log.exception('No se pudo iniciar la LAN')
            try:
                self.planificador.iniciar()
            except Exception:  # noqa: BLE001
                _log.exception('No se pudo iniciar el planificador')
            pendientes: list[tuple[float, str]] = [(RETRASO_IMAGENES_S, 'imagenes')]
            if self.op.sync_al_iniciar:
                pendientes.append((max(0.0, float(self.op.retraso_sync_s)), 'sync'))
            for retraso, que in sorted(pendientes):
                if self._parar.wait(max(0.0, listo + retraso - time.monotonic())):
                    return
                try:
                    if que == 'imagenes':
                        self.imagenes.iniciar()
                        self.imagenes.purgar(self._max_mb())
                    else:
                        self._sync_de_arranque()
                except Exception:  # noqa: BLE001
                    _log.exception('Falló el paso de arranque %s', que)

        arranque = threading.Thread(target=correr, name='hub-arranque', daemon=True)
        self._hilos = [eventos, arranque]
        eventos.start()
        arranque.start()

    def _sync_de_arranque(self) -> None:
        """03 §4.4: incremental (completa si nunca hubo barrido) si la última ok tiene más de 15 min."""
        if self.op.cliente_nube:
            return
        ultima = (self.sincronizador.estado() or {}).get('ultima_ok_at')
        if isinstance(ultima, int) and self.reloj.ahora() - ultima <= SYNC_ARRANQUE_SI_MAS_DE_S:
            _log.info('Sync de arranque omitida: la última terminó hace menos de 15 min')
            return
        try:
            self.sincronizador.iniciar('incremental', 'arranque')
        except ErrorDominio as e:
            _log.info('No se inició la sincronización de arranque (%s)', e.codigo)


# ====================================================================== composición
def _validar_opciones(op: OpcionesHub) -> None:
    if op.modo not in ('real', 'demo', 'autoprueba'):
        raise ValueError(f'modo desconocido: {op.modo!r}')
    if op.cliente_nube and (op.nube or op.modo != 'real'):
        raise ValueError('El cliente Windows y el servidor de nube son modos distintos.')
    if op.cliente_nube:
        op.sin_lan = True
        op.sync_al_iniciar = False
    if op.fuente_demo not in ('sinteticos', 'fixtures_reales'):
        raise ValueError(f'fuente de demo desconocida: {op.fuente_demo!r}')
    if getattr(sys, 'frozen', False):
        if op.dev:
            raise ValueError('--dev no existe en el ejecutable')
        if op.fuente_demo == 'fixtures_reales':
            raise ValueError("La fuente 'fixtures_reales' solo existe en desarrollo")
        if op.dir_ui is not None:
            raise ValueError('--ui no existe en el ejecutable')
    if op.ahora_fijo is not None and op.modo == 'real':
        raise ValueError('--ahora solo se admite con --demo o --autoprueba')


def _dir_ui(op: OpcionesHub) -> str:
    if op.dir_ui is not None:
        return os.path.abspath(op.dir_ui)
    if getattr(sys, 'frozen', False):
        return os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(sys.executable)), 'ui')
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'ui', 'dist')


def iniciar_hub(op: OpcionesHub) -> HubProto:
    """Compone el hub en el orden de BUILD_SPEC §6.3.1 y devuelve en cuanto el servidor de interfaz escucha."""
    t_inicio = time.monotonic()
    # 1
    _validar_opciones(op)
    rutas = config.rutas_para(op.modo, op.raiz_datos)
    registro_propio = False
    if registro.ruta_registro_actual() is None:            # el shell pudo configurarlo antes (con --depurar)
        registro.configurar_registro(rutas, depurar=logging.getLogger().isEnabledFor(logging.DEBUG))
        registro_propio = True
    # 2
    cfg = config.abrir_config(rutas)
    reloj = crear_reloj(op.ahora_fijo)
    bus = crear_bus()
    almacen = None
    imagenes = None
    try:
        # 3
        almacen = crear_almacen(rutas.db, reloj)
        bus.iniciar_versiones(almacen.versiones())
        # 4
        if op.nube:
            from .nube import crear_boveda_nube
            boveda = crear_boveda_nube(rutas, display=False)
        else:
            boveda = crear_boveda(rutas, op.modo)
        registro.fijar_secretos_vivos(boveda.secretos_vivos)
        # 5
        if op.modo == 'real':
            transporte = crear_transporte_real()
        elif op.modo == 'demo':
            transporte = crear_transporte_demo(op.fuente_demo, reloj)
        else:
            transporte = crear_transporte_demo('sinteticos', reloj)
        cliente = crear_cliente(boveda, transporte, reloj, almacen, bus)
        # 6
        fuente = op.fuente_demo if op.modo == 'demo' else 'sinteticos'
        imagenes = crear_imagenes(almacen, bus, reloj, rutas.cache_img,
                                  None if op.modo == 'real' else crear_descargador_demo(fuente))
        # 7
        local = crear_estado_local(almacen, bus, reloj)
        local.sembrar()
        analitica = crear_analitica(almacen, reloj)
        # 8
        hub = Hub(op, rutas, cfg, reloj, bus, almacen, boveda, cliente, imagenes, local, analitica)
        hub._registro_propio = registro_propio
        hub.auth = crear_auth(boveda, cliente, almacen, bus, reloj, hub, op.modo)
        # 8 b · rev. 5: Display API de TikTok for Developers (métricas de tus videos). Bóveda y transporte PROPIOS.
        boveda_display = crear_boveda_nube(rutas, display=True) if op.nube else crear_boveda_display(rutas, op.modo)
        registro.fijar_secretos_vivos(lambda: (*boveda.secretos_vivos(), *boveda_display.secretos_vivos()))
        hub.display = crear_servicio_display(boveda_display, crear_transporte_display(op.modo, reloj), almacen, bus,
                                             reloj, hub, op.modo)
        hub.display.puerto = lambda: hub.puerto_ui            # redirect_uri = http://127.0.0.1:<puerto real>/oauth/tiktok
        if op.nube:
            from .nube import configurar_auth_nube
            configurar_auth_nube(hub)
        hub.display.al_conectar = lambda: hub.sincronizar_ahora('usuario')
        # 9
        dep = Dependencias(modo=op.modo, rutas=rutas, config=cfg, reloj=reloj, bus=bus, almacen=almacen, boveda=boveda,
                           cliente=cliente, imagenes=imagenes, local=local, coordinador=hub)
        hub.sincronizador = crear_sincronizador(dep)
        fijar_display = getattr(hub.sincronizador, 'fijar_display', None)
        if callable(fijar_display):
            fijar_display(hub.display)                       # rev. 5: paso «videos_tiktok» dentro de 'videos'
        hub.planificador = crear_planificador(reloj, bus)
        hub.registrar_tareas()
        ajustes = hub.ajustes_pc()
        hub.planificador.configurar(ajustes['sync_auto'], ajustes['sync_intervalo_min'])
        # 10
        hub.despachador = rutas_api.crear_despachador(hub)
        if op.cliente_nube:
            from .cliente_nativo import ClienteNativo, DespachadorNativo
            hub.cliente_nativo = ClienteNativo(hub)
            hub.despachador = DespachadorNativo(hub.cliente_nativo, hub.despachador)
            registro.fijar_secretos_vivos(hub.secretos_vivos)
        if not op.nube and not op.cliente_nube:
            hub.lan = crear_servicio_lan(dep)
            hub.lan.fijar_despachador(hub.despachador)
        # 11
        if not op.nube:
            hub.iniciar_servidor(_dir_ui(op))
    except BaseException:
        if imagenes is not None:
            with contextlib.suppress(Exception):
                imagenes.detener()
        if almacen is not None:
            with contextlib.suppress(Exception):
                almacen.cerrar()
        if registro_propio:
            registro.cerrar_registro()
        raise
    hub.t_listo_ms = (time.monotonic() - t_inicio) * 1000.0
    _log.info('Hub listo (nube=%s, modo %s, %.0f ms)', op.nube, op.modo, hub.t_listo_ms)
    # 12
    hub._arrancar_en_fondo()
    if hub.cliente_nativo is not None:
        hub.cliente_nativo.iniciar()
    return hub
