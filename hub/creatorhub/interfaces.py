"""Interfaces entre paquetes del hub (BUILD_SPEC §6.2, rev. 3.1). Solo tipos y FIRMAS DE FÁBRICAS: cada paquete
implementa lo suyo y prueba contra los dobles de hub/pruebas/dobles.py. Los Json son dicts con las claves EXACTAS de
spec/contrato.ts. hub.py (hub-api) es el único que llama a las fábricas, en el orden de BUILD_SPEC §6.3.1."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal, Mapping, Protocol, Sequence

Json = dict[str, Any]
Alcance = Literal['tiktok', 'todo', 'imagenes']
ModoHub = Literal['real', 'demo', 'autoprueba']
FuenteDemo = Literal['sinteticos', 'fixtures_reales']
Versiones = tuple[int, int, int]                                    # (data_version, local_rev, img_rev)
Descargador = Callable[[str], bytes]                                # url -> bytes (modo demo: sin red)


# ------------------------------------------------------------------ arranque
@dataclass(frozen=True)
class Rutas:
    """config.rutas_para() las arma y crea las carpetas (03 §1, 04 §A.10)."""
    raiz: str            # %LOCALAPPDATA%\CreatorHub · …\CreatorHub\demo · %TEMP%\CreatorHub-autoprueba · o OpcionesHub.raiz_datos
    config_json: str     # <raiz>\config.json (AjustesPc, ventana, lan.activo, imagenes.max_mb)
    db: str              # <raiz>\datos\hub.sqlite
    secretos: str        # <raiz>\secretos
    tls: str             # <raiz>\tls
    cache_img: str       # <raiz>\cache\img
    logs: str            # <raiz>\logs
    webview: str         # <raiz>\webview


@dataclass
class OpcionesHub:
    modo: ModoHub = 'real'
    dev: bool = False                   # Origin http://localhost:5173 + GET /boot/dev. ValueError si sys.frozen
    ahora_fijo: int | None = None       # --ahora: el reloj ARRANCA en ese instante y avanza (solo demo/autoprueba)
    puerto_ui: int | None = None        # None = 39229 con respaldo 39228…39220 · 0 = aleatorio (autoprueba)
    raiz_datos: str | None = None       # None = la de rutas_para(modo)
    dir_ui: str | None = None           # None = sys._MEIPASS\ui (congelado) o <proyecto>\ui\dist (desarrollo). ValueError si sys.frozen y viene
    sin_lan: bool = False               # demo y autoprueba van siempre sin LAN
    fuente_demo: FuenteDemo = 'sinteticos'   # 'fixtures_reales' (lee research/datos-reales) → ValueError si sys.frozen
    sync_al_iniciar: bool = True        # False en --medir y --autoprueba
    retraso_sync_s: float = 5.0         # 60 con --inicio-windows y segundo plano
    nube: bool = False                 # Web privada: sin shell, listener local ni emparejamiento LAN.
    cliente_nube: bool = False         # App Windows local con datos/autorización centralizados en Google.


@dataclass(frozen=True)
class Contexto:
    """Quién pide: la ventana local ('ui') o un celular emparejado ('lan')."""
    origen: Literal['ui', 'lan']
    plataforma: Literal['windows', 'android'] = 'windows'
    device_id: str | None = None
    permisos: Literal['lectura', 'lectura_escritura'] | None = None

    @property
    def puede_escribir(self) -> bool:
        return self.origen == 'ui' or self.permisos == 'lectura_escritura'


CTX_UI = Contexto(origen='ui')


@dataclass
class ContextoSync:
    """Viaja con cada llamada de una sincronización (contadores y cancelación cooperativa)."""
    sync_id: int | None  # None para una consulta directa fuera de la sincronización.
    open_id: str | None
    epoca_credenciales: int
    epoca_datos: int
    cancelar: threading.Event = field(default_factory=threading.Event)
    llamadas: int = 0
    reintentos: int = 0


@dataclass
class RespuestaHttp:
    status: int
    cabeceras: list[tuple[str, str]] = field(default_factory=list)
    cuerpo: bytes = b''
    archivo: str | None = None          # ruta a enviar por bloques (imágenes); excluye `cuerpo`


@dataclass
class RespuestaImagen:
    status: int
    cabeceras: list[tuple[str, str]]
    archivo: str | None = None


@dataclass(frozen=True)
class PedidoImagen:
    tipo: Literal['p', 'a', 'g', 'm', 'v', 'e']   # 'e' = evidencia aportada por el dueño; nunca fotos simuladas
    ref_id: str                         # numérico, 'cuenta', '<pid>-<n>' (g) o '<pid>-<16hex>' (e)
    url: str                            # url de origen (CDN de la lista blanca)
    prioridad: int = 0                  # 0 = muestras/avatar · 1 = ventas/vitrina · 2 = resto
    fuente: str = ''                    # 'ficha' | 'vitrina' | 'perfil' | 'galeria' | 'parecido'


# ------------------------------------------------------------------ hub-andamio
class Reloj(Protocol):                                              # reloj.crear_reloj(ahora_fijo)
    def ahora(self) -> int: ...                                     # epoch UTC s del equipo (ClienteTikTok.ahora() corrige el desfase)
    def monotonico(self) -> float: ...
    def esperar(self, segundos: float, cancelar: threading.Event | None = None) -> bool: ...   # True = se canceló


class ArchivoConfig(Protocol):                                      # config.abrir_config(rutas): <raiz>\config.json
    def leer(self, clave: str, omision: Any = None) -> Any: ...     # 'ajustes_pc' | 'ventana' | 'lan' | 'imagenes'
    def escribir(self, cambios: Mapping[str, Any]) -> None: ...     # mezcla + .nuevo + fsync + os.replace (con reintentos)


class Suscripcion(Protocol):
    def siguiente(self, timeout_s: float) -> Json | None: ...       # un EventoHub o None
    def cerrar(self) -> None: ...


class Bus(Protocol):                                                # eventos.crear_bus()
    def iniciar_versiones(self, versiones: Versiones) -> None: ...  # hub.py, al abrir la base
    def publicar(self, evento: Json) -> None: ...                   # EventoHub completo {'tipo': …}
    def suscribir(self, max_cola: int = 100) -> Suscripcion: ...
    def notificar_cambio(self, versiones: Versiones, secciones: Sequence[str]) -> None: ...
        # publica {'tipo':'datos.cambiaron', data_version, local_rev, img_rev, secciones} y despierta esperar_cambio
    def esperar_cambio(self, vistas: Versiones, timeout_s: float) -> Json | None: ...
        # {data_version, local_rev, img_rev, secciones} en cuanto difiera de `vistas` (o de inmediato); None al agotar.
        # img_rev < 0 en `vistas` = no comparar img_rev. api agrega sync_en_curso para formar CambiosResponse.


# ------------------------------------------------------------------ hub-nucleo
class Transporte(Protocol):                                         # real: tiktok/transporte.py · demo: demo/
    def manejar(self, metodo: str, url: str, cabeceras: Mapping[str, str], cuerpo: bytes | None) -> tuple[int, Json | None]: ...


class Boveda(Protocol):                                             # boveda.crear_boveda(rutas, modo)
    generacion: int
    def leer(self) -> Mapping[str, Any]: ...
    def mutar(self, fn: Callable[[dict[str, Any]], None], cambia_credenciales: bool = False) -> None: ...
    def guardar_si(self, gen0: int, cambios: Mapping[str, Any]) -> bool: ...
    def secretos_vivos(self) -> tuple[str, ...]: ...
    def tiene_app_secret(self) -> bool: ...
    def tiene_tokens(self) -> bool: ...


class ClienteTikTok(Protocol):                                      # tiktok.cliente.crear_cliente(...)
    def llamar(self, metodo: Literal['GET', 'POST', 'DELETE'], path: str, query: Mapping[str, str] | None = None,
               body: Json | None = None, *, ctx: ContextoSync | None = None,
               reintentar: bool = True, reemitir_tras_refresh: bool = True,
               antes_de_enviar: Callable[[], None] | None = None,
               archivo_multipart: tuple[str, bytes] | None = None) -> Json: ...  # data{} o ErrorApi
    def subir_parte_video(self, url: str, token: str, numero: int, tipo: str, datos: bytes, *,
                          ctx: ContextoSync, antes_de_enviar: Callable[[], None]) -> Json: ...
    def refrescar(self, token_visto: str | None = None) -> bool: ...
    def ahora(self) -> int: ...                                     # reloj corregido por el desfase con TikTok


class ServicioAuth(Protocol):                                       # auth.crear_auth(...)
    def conexion(self) -> Json: ...                                 # Conexion
    def cuenta(self) -> Json | None: ...                            # Cuenta
    def link(self, abrir_navegador: bool) -> Json: ...              # AuthLinkResponse (state de 10 min, C37)
    def portapapeles(self) -> Json: ...                             # PortapapelesResponse
    def canjear(self, req: Json) -> Json: ...                       # AuthCanjearResponse (cambio de cuenta → coordinador)
    def guardar_credenciales_app(self, app_key: str, app_secret: str) -> Json: ...
    def importar_credenciales_nube(self, req: Json) -> Json: ...
    def refrescar(self) -> Json: ...                                # AuthEstadoResponse
    def desconectar(self, borrar_datos: bool) -> Json: ...          # AuthEstadoResponse (→ coordinador)
    def credenciales_estado(self) -> Json: ...                      # CredencialesEstado
    def importar(self, req: Json) -> Json: ...                      # ImportarResponse (req['ruta'] opcional, C46)
    def guardar_app_secret(self, app_secret: str) -> Json: ...      # CredencialesEstado
    def borrar_legado(self) -> Json: ...                            # BorrarLegadoResponse
    def purgar_states(self) -> None: ...


# ------------------------------------------------------------------ hub-sync
class Almacen(Protocol):                                            # almacen.crear_almacen(ruta_db, reloj)
    ruta: str
    def lector(self) -> AbstractContextManager[sqlite3.Connection]: ...                 # BEGIN … COMMIT, query_only
    def escritor(self, epoca: int | None = None) -> AbstractContextManager[sqlite3.Connection]: ...  # BEGIN IMMEDIATE
    def epoca(self) -> int: ...
    def versiones(self, conn: sqlite3.Connection | None = None) -> Versiones: ...       # en la misma transacción
    def marcar_data_version(self, conn: sqlite3.Connection) -> None: ...                # dv_pendiente = '1' (03 §3.2)
    def confirmar_data_version(self) -> int | None: ...     # tx propia: si dv_pendiente → data_version += 1 y lo devuelve; si no, None
    def subir_local_rev(self, conn: sqlite3.Connection) -> int: ...
    def subir_img_rev(self, conn: sqlite3.Connection) -> int: ...                       # hub-imagenes, al cerrar un lote (C45)
    def borrar(self, alcance: Alcance) -> None: ...                                     # época += 1, sin restos
    def solo_lectura(self) -> bool: ...                                                 # base de versión más nueva
    def cerrar(self) -> None: ...


class Sincronizador(Protocol):                                      # sincronizador.crear_sincronizador(dep)
    def iniciar(self, tipo: Literal['incremental', 'completa'], origen: str) -> Json: ...  # SyncIniciarResponse
    def estado(self) -> Json: ...                                   # SyncEstado (en_curso desde memoria)
    def cancelar(self, esperar_s: float = 40.0) -> None: ...
    def historial(self, limite: int = 20) -> Json: ...              # SyncHistorialResponse
    def cobertura(self) -> Json: ...                                # CoberturaResponse


class Planificador(Protocol):                                       # planificador.crear_planificador(reloj, bus)
    def iniciar(self) -> None: ...
    def detener(self) -> None: ...
    def configurar(self, sync_auto: bool, intervalo_min: int) -> None: ...
    def registrar_tarea(self, nombre: str, cada_s: int, fn: Callable[[], None]) -> None: ...


# ------------------------------------------------------------------ hub-analitica
class Analitica(Protocol):                                          # analitica.crear_analitica(almacen, reloj). Solo lectura.
    def dashboard(self, periodo: str) -> Json: ...
    def muestras(self, filtros: Mapping[str, str]) -> Json: ...     # query cruda validada contra listas blancas
    def muestra_detalle(self, application_id: str) -> Json: ...
    def tiendas(self, filtros: Mapping[str, str]) -> Json: ...
    def tienda_detalle(self, tienda_key: str, filtros: Mapping[str, str]) -> Json: ...
    def serie(self, filtros: Mapping[str, str]) -> Json: ...
    def videos(self, filtros: Mapping[str, str]) -> Json: ...
    def video_detalle(self, content_id: str) -> Json: ...
    def catalogo_videos(self, filtros: Mapping[str, str]) -> Json: ...  # rev. 6: publicados + con ventas
    def video_catalogo(self, content_id: str) -> Json: ...          # rev. 6: detalle, tenga o no ventas
    def productos(self, filtros: Mapping[str, str]) -> Json: ...
    def producto_detalle(self, product_id: str) -> Json: ...
    def ordenes(self, filtros: Mapping[str, str]) -> Json: ...
    def snapshot(self, cuenta: Json | None, conexion: Json, sync: Json) -> Json: ...
    def etag(self, con_display: bool = False) -> str: ...           # 'dv<N>-lr<M>-ir<K>' (+ '|d<at>' de la última pasada
                                                                    # de la Display API) leído en la misma transacción


class EvidenciaProducto(Protocol):
    """Datos aportados explícitamente por el dueño; no implica extracción automática del proveedor."""
    def leer(self, product_id: str) -> Json: ...
    def resenas(self, product_id: str, query: Mapping[str, str]) -> Json: ...
    def guardar(self, product_id: str, datos: Json, ctx: Contexto) -> Json: ...
    def extraer(self, product_id: str, datos: Json, ctx: Contexto) -> Json: ...


class EstadoLocal(Protocol):                                        # local.crear_estado_local(almacen, bus, reloj)
    def sembrar(self) -> None: ...                                  # ÚNICO que siembra: 11 plantillas + preferencias (idempotente)
    def plan_listar(self, filtros: Mapping[str, str]) -> Json: ...
    def plan_crear(self, datos: Json, ctx: Contexto) -> Json: ...   # copia muestras.en_cohorte_desde_at
    def plan_editar(self, plan_id: str, cambios: Json, ctx: Contexto) -> Json: ...
    def plan_borrar(self, plan_id: str, rev: int, ctx: Contexto) -> None: ...
    def avisos_listar(self, filtros: Mapping[str, str]) -> Json: ...
    def aviso_crear(self, datos: Json, ctx: Contexto) -> Json: ...
    def aviso_editar(self, aviso_id: str, cambios: Json, ctx: Contexto) -> Json: ...
    def plantillas_listar(self) -> Json: ...
    def plantilla_editar(self, plantilla_id: str, cambios: Json, ctx: Contexto) -> Json: ...
    def plantilla_restaurar(self, plantilla_id: str, ctx: Contexto) -> Json: ...
    def preferencias_leer(self) -> Json: ...
    def preferencias_editar(self, cambios: Json, ctx: Contexto) -> Json: ...
    def notas_listar(self, filtros: Mapping[str, str]) -> Json: ...
    def nota_crear(self, datos: Json, ctx: Contexto) -> Json: ...
    def nota_editar(self, nota_id: str, cambios: Json, ctx: Contexto) -> Json: ...
    def nota_borrar(self, nota_id: str, rev: int, ctx: Contexto) -> None: ...
    def recordatorios_listar(self, filtros: Mapping[str, str]) -> Json: ...
    def recordatorio_crear(self, datos: Json, ctx: Contexto) -> Json: ...
    def recordatorio_editar(self, rec_id: str, cambios: Json, ctx: Contexto) -> Json: ...
    def recordatorio_borrar(self, rec_id: str, rev: int, ctx: Contexto) -> None: ...
    def aplicar_ops(self, ops: Sequence[Json], ctx: Contexto) -> Json: ...              # OpsResponse
    def exportar(self) -> Json: ...                                                     # ExportacionLocal
    def importar(self, datos: Json) -> Json: ...                                        # ImportacionLocalResponse (ya leído y parseado por api)
    def recordatorios_vencidos(self, ahora: int) -> list[Json]: ...                     # marca notificado_at
    def enlaces_por_resolver(self) -> list[tuple[str, str]]: ...                        # (plan_id, enlace corto)
    def guardar_content_id(self, plan_id: str, content_id: str) -> None: ...
    # Conflicto de rev: ErrorDominio('conflicto', …, http=409, vigente=<objeto vigente>) (errores.py)


# ------------------------------------------------------------------ hub-imagenes
class Imagenes(Protocol):                                           # imagenes.crear_imagenes(almacen, bus, reloj, raiz_cache, descargar)
    def iniciar(self) -> None: ...                                  # trabajadores; hub.py lo llama 2 s después de "listo" (C3)
    def detener(self) -> None: ...
    def encolar(self, pedidos: Sequence[PedidoImagen]) -> None: ... # registra url_origen en SU transacción (nunca con el escritor
                                                                    # tomado) aunque no haya iniciado: la analítica ya emite '?v=0'
    def servir(self, tipo: str, ref_id: str, v: str | None, t: str | None) -> RespuestaImagen: ...   # reglas de §6.3.3
    def ruta_original(self, tipo: str, ref_id: str) -> str | None: ...
    def meta_de(self, urls: Iterable[str]) -> Json: ...             # MetaImagenes (solo imágenes en estado 'ok')
    def vaciar_cola(self) -> None: ...
    def volcar_accesos(self) -> None: ...
    def purgar(self, max_mb: int) -> None: ...
    def uso_bytes(self) -> int: ...


# ------------------------------------------------------------------ hub-api / hub-lan / windows-shell
class Despachador(Protocol):                                        # api/rutas.py (hub-api); lo usa servidor_lan
    def despachar(self, metodo: str, ruta: str, consulta: str, cabeceras: Mapping[str, str], cuerpo: bytes,
                  ctx: Contexto) -> RespuestaHttp: ...


class ServicioLan(Protocol):                                        # lan.crear_servicio_lan(dep)
    def fijar_despachador(self, d: Despachador) -> None: ...        # enlace tardío: hub.py, antes de iniciar_si_activo()
    def iniciar_si_activo(self) -> None: ...
    def detener(self) -> None: ...
    def resumen(self) -> Json: ...                                  # LanResumen
    def estado(self) -> Json: ...                                   # LanEstado
    def activar(self, activo: bool) -> Json: ...
    def cambiar(self, cambios: Json) -> Json: ...
    def emparejar(self) -> Json: ...                                # EmparejarResponse
    def estado_emparejamiento(self, pair_id: str) -> Json: ...
    def decidir(self, pair_id: str, decision: Json) -> Json: ...
    def cambiar_dispositivo(self, device_id: str, cambios: Json) -> Json: ...
    def revocar(self, device_id: str) -> None: ...
    def revocar_todos(self) -> None: ...
    def firewall_diagnostico(self) -> Json: ...                     # DiagnosticoFirewall
    def firewall_configurar(self, req: Json) -> Json: ...           # FirewallResponse
    def volcar_accesos(self) -> None: ...


class Coordinador(Protocol):                                        # hub.py (hub-api): 03 §2.6 «mutaciones»
    def mutacion_segura(self, mutar_boveda: Callable[[], None] | None, borrar: Literal['nada', 'tiktok', 'todo', 'imagenes']) -> None: ...


class GanchosVentana(Protocol):                                     # plataforma/windows (windows-shell)
    def estado_inicio_windows(self) -> tuple[bool, bool]: ...       # (activo, bloqueado por el Administrador de tareas)
    def aplicar_inicio_windows(self, activo: bool) -> None: ...
    def notificar(self, titulo: str, texto: str, ruta: str) -> None: ...   # solo fin de sync con novedades y ventana oculta
    def parpadear(self) -> None: ...                                # FlashWindowEx si la ventana no tiene el foco (C40, C44)
    def ventana_visible(self) -> bool: ...


class HubProto(Protocol):                                           # hub.iniciar_hub(op) (hub-api). windows-shell programa contra esto
    puerto_ui: int
    puerto_respaldo: bool
    bus: Bus
    evidencia: EvidenciaProducto
    def url_arranque(self) -> str: ...                  # 'http://127.0.0.1:<p>/boot?t=<token 60 s, un uso>'
    def sincronizar_ahora(self, origen: str = 'usuario') -> None: ...
    def ruta_imagen_original(self, ruta_img: str) -> str | None: ...   # '/img/p/<id>?v=…' → archivo og de la caché
    def registrar_ganchos(self, ganchos: GanchosVentana) -> None: ...
    def ajustes_pc(self) -> Json: ...                                  # AjustesPc completo (con iniciar_con_windows_bloqueado)
    def detener(self, tope_s: float = 3.0) -> None: ...


@dataclass
class Dependencias:
    """Lo que hub.py ya construyó cuando llama a crear_sincronizador y crear_servicio_lan (orden de BUILD §6.3.1)."""
    modo: ModoHub
    rutas: Rutas
    config: ArchivoConfig
    reloj: Reloj
    bus: Bus
    almacen: Almacen
    boveda: Boveda
    cliente: ClienteTikTok
    imagenes: Imagenes
    local: EstadoLocal
    coordinador: Coordinador


# ------------------------------------------------------------------ FÁBRICAS: firma EXACTA (test_api_fabricas.py la compara con inspect)
FABRICAS: dict[str, str] = {
    'creatorhub.config.rutas_para': '(modo: ModoHub, raiz: str | None = None) -> Rutas',
    'creatorhub.config.abrir_config': '(rutas: Rutas) -> ArchivoConfig',
    'creatorhub.reloj.crear_reloj': '(ahora_fijo: int | None = None) -> Reloj',
    'creatorhub.eventos.crear_bus': '() -> Bus',
    'creatorhub.registro.configurar_registro': '(rutas: Rutas, depurar: bool = False) -> None',
    'creatorhub.boveda.crear_boveda': '(rutas: Rutas, modo: ModoHub) -> Boveda',
    'creatorhub.tiktok.transporte.crear_transporte_real': '() -> Transporte',
    'creatorhub.tiktok.cliente.crear_cliente': '(boveda: Boveda, transporte: Transporte, reloj: Reloj, almacen: Almacen, bus: Bus) -> ClienteTikTok',
    'creatorhub.auth.crear_auth': '(boveda: Boveda, cliente: ClienteTikTok, almacen: Almacen, bus: Bus, reloj: Reloj, coordinador: Coordinador, modo: ModoHub) -> ServicioAuth',
    'creatorhub.almacen.crear_almacen': '(ruta_db: str, reloj: Reloj) -> Almacen',
    'creatorhub.demo.crear_transporte_demo': '(fuente: FuenteDemo, reloj: Reloj) -> Transporte',
    'creatorhub.demo.crear_descargador_demo': '(fuente: FuenteDemo) -> Descargador',
    'creatorhub.sincronizador.crear_sincronizador': '(dep: Dependencias) -> Sincronizador',
    'creatorhub.planificador.crear_planificador': '(reloj: Reloj, bus: Bus) -> Planificador',
    'creatorhub.local.crear_estado_local': '(almacen: Almacen, bus: Bus, reloj: Reloj) -> EstadoLocal',
    'creatorhub.analitica.crear_analitica': '(almacen: Almacen, reloj: Reloj) -> Analitica',
    'creatorhub.imagenes.crear_imagenes': '(almacen: Almacen, bus: Bus, reloj: Reloj, raiz_cache: str, descargar: Descargador | None = None) -> Imagenes',
    'creatorhub.lan.crear_servicio_lan': '(dep: Dependencias) -> ServicioLan',
    'creatorhub.hub.iniciar_hub': '(op: OpcionesHub) -> HubProto',
}
