"""Ventana de Corte con pywebview 6.2.1 + Edge WebView2 (04 §A.1, §A.4, §A.6; BUILD_SPEC §6.3.4, §6.6, C23, C40, C44).

- Título «Corte»; tamaño inicial `min(1440, 0.9·ancho) × min(900, 0.9·alto)` centrado; mínimo 960×640; posición y tamaño
  recordados en `config.json['ventana']` (se restauran solo si caben en alguna pantalla); `background_color` = lienzo
  del tema; `private_mode=False` + `storage_path=<datos>\\webview`; texto seleccionable y zoom; menú contextual y DevTools
  solo con `--depurar`; barra de título pintada con DWM; `gui='edgechromium'` siempre.
- X → ocultar (bandeja). Primer cierre (C23): si `AjustesPc.segundo_plano` es None se cancela el cierre, se muestra la
  ventana y se publica `ventana.preguntar_cierre`; la interfaz responde con PATCH /api/ajustes/pc + `ventana_ocultar()` o
  `ventana_cerrar()`. Con `segundo_plano = False` la X cierra del todo. Válvula: si la interfaz no contestó y la X se
  vuelve a pulsar dentro de 20 s, se oculta (la X nunca queda sin efecto; la bandeja tiene «Salir»).
- Bandeja: «Abrir Corte» · «Sincronizar ahora» · «Salir»; clic → mostrar. Globos programados con temporizador propio.
- Hilos `activar` (evento `…Activar`: mostrar y traer al frente, C40) y `salir` (evento `…Salir`: cierre ordenado).
- `GanchosVentana` (§6.2): inicio con Windows (Run + StartupApproved), `notificar` (globo), `parpadear` (FlashWindowEx si
  la ventana no tiene el foco) y `ventana_visible`.
- `--medir`: escribe `%TEMP%\\CreatorHub-medir\\medicion.json` cuando la interfaz llama `lista()` y sale.

pywebview y pythonnet se importan SOLO dentro de `correr()` (después de «listo»). `VentanaPywebview` adapta la ventana de
pywebview y su formulario WinForms; las pruebas usan un doble con los mismos métodos.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import tempfile
import threading
import time
import urllib.parse
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from creatorhub import config
from creatorhub.interfaces import ArchivoConfig, Rutas
from creatorhub.plataforma.windows import bandeja as bandeja_mod
from creatorhub.plataforma.windows import dwm, inicio_windows, navegacion, notificaciones
from creatorhub.plataforma.windows.instancia import ms_desde_inicio_proceso
from creatorhub.plataforma.windows.js_api import ApiPywebview, escribir_portapapeles

_log = logging.getLogger('creatorhub.plataforma.ventana')

TITULO = 'Corte'
TAMANO_PREFERIDO = (1440, 900)
FRACCION_PANTALLA = 0.9
TAMANO_MINIMO = (960, 640)
FRANJA_VISIBLE = (160, 24)               # de la barra de título que debe caer en una pantalla para restaurar la posición
ANTIRREBOTE_GEOMETRIA_S = 1.0
ESPERA_RESPUESTA_CIERRE_S = 20.0
CARPETA_MEDIR = os.path.join(tempfile.gettempdir(), 'CreatorHub-medir')
TOPE_MEDIR_S = 25.0
TOPE_ARRANQUE_UI_S = 60.0

SW_RESTORE = 9
FLASHW_ALL = 0x3
FLASHW_TIMERNOFG = 0xC
MONITORINFOF_PRIMARY = 0x1
WAIT_OBJECT_0 = 0x0


# ---------------------------------------------------------------------- user32
class FLASHWINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.UINT), ('hwnd', wintypes.HWND), ('dwFlags', wintypes.DWORD),
                ('uCount', wintypes.UINT), ('dwTimeout', wintypes.DWORD)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT), ('rcWork', wintypes.RECT),
                ('dwFlags', wintypes.DWORD)]


_MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                      wintypes.LPARAM)


def user32() -> Any:
    u = ctypes.WinDLL('user32', use_last_error=True)
    for nombre in ('IsWindowVisible', 'IsIconic', 'SetForegroundWindow'):
        getattr(u, nombre).argtypes = [wintypes.HWND]
        getattr(u, nombre).restype = wintypes.BOOL
    u.GetForegroundWindow.restype = wintypes.HWND
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.FlashWindowEx.argtypes = [ctypes.POINTER(FLASHWINFO)]
    u.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    u.GetDpiForWindow.argtypes = [wintypes.HWND]
    u.GetDpiForWindow.restype = wintypes.UINT
    u.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, _MONITORENUMPROC, wintypes.LPARAM]
    u.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
    return u


def kernel32() -> Any:
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    return k


def parpadear_hwnd(hwnd: int, u32: Any) -> None:
    info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, FLASHW_ALL | FLASHW_TIMERNOFG, 0, 0)
    u32.FlashWindowEx(ctypes.byref(info))


# ---------------------------------------------------------------------- geometría
@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    ancho: int
    alto: int


@dataclass(frozen=True)
class Geometria:
    ancho: int
    alto: int
    x: int | None                 # None = centrada por WinForms (CenterScreen)
    y: int | None
    maximizada: bool


def pantallas(u32: Any = None) -> list[Rect]:
    """Áreas de trabajo de las pantallas (la principal primero), en píxeles lógicos (el proceso aún no es DPI-aware
    cuando se llama, antes de crear la ventana)."""
    u = u32 or user32()
    halladas: list[tuple[bool, Rect]] = []

    def cb(hmon: Any, _hdc: Any, _rc: Any, _dato: Any) -> bool:
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if u.GetMonitorInfoW(hmon, ctypes.byref(info)):
            w = info.rcWork
            halladas.append((bool(info.dwFlags & MONITORINFOF_PRIMARY),
                             Rect(w.left, w.top, w.right - w.left, w.bottom - w.top)))
        return True

    try:
        u.EnumDisplayMonitors(None, None, _MONITORENUMPROC(cb), 0)
    except (OSError, ctypes.ArgumentError):
        _log.debug('No se pudieron enumerar las pantallas', exc_info=True)
    halladas.sort(key=lambda t: not t[0])
    return [r for _p, r in halladas]


def _franja_visible(r: Rect, p: Rect) -> bool:
    ancho = min(r.x + r.ancho, p.x + p.ancho) - max(r.x, p.x)
    alto = min(r.y + FRANJA_VISIBLE[1], p.y + p.alto) - max(r.y, p.y)
    return ancho >= FRANJA_VISIBLE[0] and alto >= FRANJA_VISIBLE[1] and r.y >= p.y - 8


def pantalla_que_contiene(r: Rect, lista: list[Rect]) -> Rect | None:
    for p in lista:
        if _franja_visible(r, p):
            return p
    return None


def _entero(v: Any) -> int | None:
    return int(v) if isinstance(v, int) and not isinstance(v, bool) else None


def geometria_inicial(guardada: Any, lista: list[Rect]) -> Geometria:
    principal = lista[0] if lista else Rect(0, 0, 1366, 728)
    ancho = max(TAMANO_MINIMO[0], min(TAMANO_PREFERIDO[0], int(principal.ancho * FRACCION_PANTALLA)))
    alto = max(TAMANO_MINIMO[1], min(TAMANO_PREFERIDO[1], int(principal.alto * FRACCION_PANTALLA)))
    omision = Geometria(ancho, alto, None, None, False)
    if not isinstance(guardada, Mapping):
        return omision
    maximizada = guardada.get('maximizada') is True
    valores = [_entero(guardada.get(k)) for k in ('x', 'y', 'ancho', 'alto')]
    if any(v is None for v in valores):
        return Geometria(ancho, alto, None, None, maximizada)
    gx, gy, ga, gl = (int(v) for v in valores)                       # type: ignore[arg-type]
    ga, gl = max(TAMANO_MINIMO[0], ga), max(TAMANO_MINIMO[1], gl)
    p = pantalla_que_contiene(Rect(gx, gy, ga, gl), lista)
    if p is None:
        return Geometria(ancho, alto, None, None, maximizada)
    ga = max(TAMANO_MINIMO[0], min(ga, p.ancho))
    gl = max(TAMANO_MINIMO[1], min(gl, p.alto))
    return Geometria(ga, gl, gx, gy, maximizada)


def ruta_icono() -> str | None:
    """`_internal\\recursos\\CreatorHub.ico` en el exe; en desarrollo, el que dejó build-empaquetado."""
    if getattr(sys, 'frozen', False):
        candidatos = [os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(sys.executable)), 'recursos',
                                   'CreatorHub.ico')]
    else:
        proyecto = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), *(['..'] * 4)))
        candidatos = [os.path.join(proyecto, 'build', 'windows', 'iconos', 'CreatorHub.ico'),
                      os.path.join(proyecto, 'branding', 'CreatorHub.ico')]
    return next((c for c in candidatos if os.path.isfile(c)), None)


def _reloj_de(hub: Any) -> Callable[[], float]:
    """Con --ahora el reloj del hub va adelantado/atrasado: los globos se programan contra ESE reloj."""
    reloj = getattr(hub, 'reloj', None)
    ahora = getattr(reloj, 'ahora', None)
    return ahora if callable(ahora) else time.time


# ---------------------------------------------------------------------- adaptador de pywebview
class VentanaPywebview:
    """Envuelve `webview.Window` y su formulario WinForms. Todo lo que toca el formulario corre en su hilo."""

    def __init__(self, ventana: Any, u32: Any = None) -> None:
        self.v = ventana
        self._u32 = u32

    def form(self) -> Any:
        return getattr(self.v, 'native', None)

    def en_ui(self, fn: Callable[[], Any], esperar: bool = True) -> Any:
        """Corre `fn` en el hilo del formulario (Invoke, o BeginInvoke sin esperar). Sin formulario (todavía no se creó,
        o en pruebas sin WinForms) se corre aquí mismo."""
        form = self.form()
        caja: dict[str, Any] = {}

        def cuerpo() -> None:
            try:
                caja['v'] = fn()
            except Exception as e:  # noqa: BLE001
                caja['e'] = e

        if form is None or not form.InvokeRequired:
            cuerpo()
        else:
            from System import Action                                # pythonnet (ya cargado por pywebview)
            if not esperar:
                form.BeginInvoke(Action(cuerpo))
                return None
            form.Invoke(Action(cuerpo))
        if 'e' in caja:
            raise caja['e']
        return caja.get('v')

    def hwnd(self) -> int:
        form = self.form()
        try:
            return int(form.Handle.ToInt64()) if form is not None else 0
        except Exception:  # noqa: BLE001
            return 0

    def mostrar(self) -> None:
        def _mostrar() -> None:
            f = self.form()
            f.Show()
            f.Activate()
        self.en_ui(_mostrar)

    def ocultar(self) -> None:
        self.en_ui(lambda: self.form().Hide())

    def cerrar(self) -> None:
        self.en_ui(lambda: self.form().Close(), esperar=False)

    def dialogo(self, tipo: str, nombre: str, file_types: tuple[str, ...]) -> tuple[str, ...] | None:
        """Diálogo de pywebview en el hilo de la interfaz (WinForms exige STA; los hilos de js_api no lo son)."""
        import webview
        clase = webview.FileDialog.OPEN if tipo == 'abrir' else webview.FileDialog.SAVE
        return self.en_ui(lambda: self.v.create_file_dialog(clase, '', False, nombre, file_types))

    def geometria_actual(self, u32: Any = None) -> dict[str, Any] | None:
        u = u32 or self._u32 or user32()

        def leer() -> dict[str, Any]:
            f = self.form()
            estado = str(f.WindowState)
            b = f.Bounds if estado == 'Normal' else f.RestoreBounds
            dpi = u.GetDpiForWindow(int(f.Handle.ToInt64())) or 96
            escala = dpi / 96.0
            return {'x': int(round(b.X / escala)), 'y': int(round(b.Y / escala)), 'ancho': int(round(b.Width / escala)),
                    'alto': int(round(b.Height / escala)), 'maximizada': estado == 'Maximized'}
        return self.en_ui(leer)


# ---------------------------------------------------------------------- shell
class ShellVentana:
    """La ventana de Corte, su bandeja y sus globos. Implementa `GanchosVentana` (BUILD_SPEC §6.2)."""

    def __init__(self, hub: Any, rutas: Rutas, *, instancia: Any = None, depurar: bool = False, oculta: bool = False,
                 medir: bool = False, t_hub_listo_ms: int | None = None, cfg: ArchivoConfig | None = None,
                 ventana: Any = None, bandeja: Any = None, abrir_url: Callable[[str], None] | None = None,
                 portapapeles: Callable[[str], bool] | None = None, u32: Any = None,
                 inicio: inicio_windows.InicioWindows | None = None, ahora: Callable[[], float] | None = None,
                 icono: str | None = None) -> None:
        self.hub = hub
        self.rutas = rutas
        self.instancia = instancia
        self.depurar = depurar
        self.oculta = oculta
        self.medir = medir
        self.t_hub_listo_ms = t_hub_listo_ms
        self.t_ventana_ms: int | None = None
        self.t_pagina_ms: int | None = None
        self.cfg: ArchivoConfig = cfg if cfg is not None else (getattr(hub, 'cfg', None) or config.abrir_config(rutas))
        self.ventana = ventana
        self.bandeja = bandeja
        self.inicio = inicio or inicio_windows.InicioWindows()
        self.icono = icono if icono is not None else ruta_icono()
        self.api = ApiPywebview(self)
        self.programador = notificaciones.Programador(self.mostrar_globo, ahora=ahora or _reloj_de(hub))
        self.nav: navegacion.Navegacion | None = None
        self.codigo_salida = 0
        self.ui_lista = threading.Event()
        self._abrir = abrir_url or navegacion.abrir_en_navegador
        self._portapapeles = portapapeles or escribir_portapapeles
        self._u32 = u32
        self._saliendo = False
        self._terminado = threading.Event()
        self._tema: str | None = None
        self._pregunta_at: float | None = None
        self._monotonico: Callable[[], float] = time.monotonic
        self._candado = threading.Lock()
        self._temporizador_geometria: threading.Timer | None = None
        self._medicion_escrita = False
        self._hilos: list[threading.Thread] = []

    # ================================================================== utilidades
    @property
    def origen(self) -> str:
        return f'http://{config.HOST_UI}:{self.hub.puerto_ui}'

    @property
    def saliendo(self) -> bool:
        return self._saliendo

    def _user32(self) -> Any:
        if self._u32 is None:
            self._u32 = user32()
        return self._u32

    def _hwnd(self) -> int:
        return self.ventana.hwnd() if self.ventana is not None else 0

    def _publicar(self, evento: Mapping[str, Any]) -> None:
        try:
            self.hub.bus.publicar(dict(evento))
        except Exception:  # noqa: BLE001
            _log.warning('No se pudo publicar %s', evento.get('tipo'), exc_info=True)

    def _leer_ventana(self) -> dict[str, Any]:
        try:
            v = self.cfg.leer('ventana', {}) or {}
        except Exception:  # noqa: BLE001
            v = {}
        return dict(v) if isinstance(v, Mapping) else {}

    def _guardar_ventana(self, cambios: Mapping[str, Any]) -> None:
        try:
            self.cfg.escribir({'ventana': dict(cambios)})
        except Exception:  # noqa: BLE001
            _log.warning('No se pudo guardar el estado de la ventana', exc_info=True)

    # ================================================================== GanchosVentana (§6.2)
    def estado_inicio_windows(self) -> tuple[bool, bool]:
        return self.inicio.estado()

    def aplicar_inicio_windows(self, activo: bool) -> None:
        self.inicio.aplicar(bool(activo))

    def notificar(self, titulo: str, texto: str, ruta: str) -> None:
        n = notificaciones.desde_dict({'id': 'hub', 'titulo': titulo, 'texto': texto, 'at': 1, 'ruta': ruta})
        if n is not None:
            self.mostrar_globo(n)

    def parpadear(self) -> None:
        """FlashWindowEx solo si la ventana no tiene el foco (C40, C44)."""
        hwnd = self._hwnd()
        if not hwnd:
            return
        u = self._user32()
        if u.GetForegroundWindow() == hwnd:
            return
        parpadear_hwnd(hwnd, u)

    def ventana_visible(self) -> bool:
        hwnd = self._hwnd()
        if not hwnd:
            return False
        u = self._user32()
        return bool(u.IsWindowVisible(hwnd)) and not bool(u.IsIconic(hwnd))

    # ================================================================== lo que usa js_api
    def aplicar_tema(self, modo: str) -> None:
        if modo not in dwm.MODOS:
            return
        self._tema = modo
        hwnd = self._hwnd()
        if hwnd:
            dwm.aplicar_tema(hwnd, modo)
        if self._leer_ventana().get('tema') != modo:
            self._guardar_ventana({'tema': modo})

    def abrir_url(self, url: str) -> None:
        if navegacion.url_externa_permitida(url):
            self._abrir(url)

    def copiar_texto(self, texto: str) -> bool:
        return bool(self._portapapeles(texto))

    def mostrar_globo(self, n: notificaciones.Notificacion) -> None:
        b, v = self.bandeja, self.ventana
        if b is None or v is None:
            _log.info('Globo omitido: la bandeja todavía no existe')
            return
        v.en_ui(lambda: b.globo(n.titulo, n.texto, n.ruta), esperar=False)

    def ocultar(self) -> None:
        if self.ventana is not None:
            self.ventana.ocultar()

    def cerrar_del_todo(self) -> None:
        self.salir()

    def dialogo(self, tipo: str, nombre: str, file_types: tuple[str, ...]) -> tuple[str, ...] | None:
        if self.ventana is None:
            return None
        return self.ventana.dialogo(tipo, nombre, file_types)

    def interfaz_lista(self) -> None:
        primera = not self.ui_lista.is_set()
        self.ui_lista.set()
        if primera and self.medir:
            self.t_pagina_ms = ms_desde_inicio_proceso()
            self._escribir_medicion()
            self.salir()

    # ================================================================== acciones
    def mostrar(self, ruta: str | None = None) -> None:
        if ruta is not None and notificaciones.ruta_valida(ruta):
            self._publicar({'tipo': 'ventana.mostrar_ruta', 'ruta': ruta})
        if self.ventana is None:
            return
        self.ventana.mostrar()
        hwnd = self._hwnd()
        if not hwnd:
            return
        u = self._user32()
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, SW_RESTORE)
        u.SetForegroundWindow(hwnd)
        if u.GetForegroundWindow() != hwnd:                           # Windows no siempre cede el primer plano
            parpadear_hwnd(hwnd, u)

    def al_clic_globo(self, ruta: str) -> None:
        self.mostrar(ruta)

    def sincronizar(self) -> None:
        self.hub.sincronizar_ahora('usuario')

    def salir(self) -> None:
        """«Salir» de la bandeja, `--salir`, evento Salir o «Cerrar por completo»: cierre ordenado."""
        self._saliendo = True
        if self.ventana is not None:
            self.ventana.cerrar()

    # ================================================================== cierre (events.closing, hilo de la interfaz)
    def al_cerrar(self) -> bool:
        """True deja cerrar; False cancela (pywebview)."""
        if self._saliendo:
            self._despedirse()
            return True
        try:
            segundo_plano = self.hub.ajustes_pc().get('segundo_plano')
        except Exception:  # noqa: BLE001
            _log.warning('No se pudieron leer los ajustes de la PC al cerrar', exc_info=True)
            segundo_plano = None
        if segundo_plano is False:                                    # «Cerrar por completo»
            self._saliendo = True
            self._despedirse()
            return True
        if segundo_plano is None:
            ahora = self._monotonico()
            sin_respuesta = self._pregunta_at is not None and ahora - self._pregunta_at < ESPERA_RESPUESTA_CIERRE_S
            if not sin_respuesta:                                     # C23: primera vez → la interfaz pregunta
                self._pregunta_at = ahora
                self._publicar({'tipo': 'ventana.preguntar_cierre'})
                threading.Thread(target=self.mostrar, name='mostrar', daemon=True).start()
                return False
            _log.info('La interfaz no respondió la pregunta de cierre: la ventana se oculta')
        self._pregunta_at = None
        threading.Thread(target=self.ocultar, name='ocultar', daemon=True).start()
        return False

    def _despedirse(self) -> None:
        """Al cerrar de verdad (hilo de la interfaz): guarda la geometría y quita el ícono de la bandeja."""
        self._cancelar_guardado_geometria()
        self._guardar_geometria()
        if self.bandeja is not None:
            try:
                self.bandeja.quitar()
            except Exception:  # noqa: BLE001
                _log.debug('No se pudo quitar la bandeja', exc_info=True)

    def al_terminar_sesion(self, *_args: Any) -> None:
        """Windows cierra la sesión o se apaga: la X ya no debe cancelar el cierre."""
        self._saliendo = True

    # ================================================================== geometría recordada
    def programar_guardado_geometria(self, *_args: Any) -> None:
        with self._candado:
            if self._temporizador_geometria is not None:
                self._temporizador_geometria.cancel()
            t = threading.Timer(ANTIRREBOTE_GEOMETRIA_S, self._guardar_geometria)
            t.daemon = True
            self._temporizador_geometria = t
            t.start()

    def _cancelar_guardado_geometria(self) -> None:
        with self._candado:
            if self._temporizador_geometria is not None:
                self._temporizador_geometria.cancel()
                self._temporizador_geometria = None

    def _guardar_geometria(self) -> None:
        if self.ventana is None:
            return
        try:
            g = self.ventana.geometria_actual()
        except Exception:  # noqa: BLE001
            _log.debug('No se pudo leer la geometría de la ventana', exc_info=True)
            return
        if not g:
            return
        actual = self._leer_ventana()
        if any(actual.get(k) != g.get(k) for k in ('x', 'y', 'ancho', 'alto', 'maximizada')):
            self._guardar_ventana(g)

    # ================================================================== --medir
    def _al_mostrarse(self) -> None:
        if self.t_ventana_ms is None:
            self.t_ventana_ms = ms_desde_inicio_proceso()

    def _escribir_medicion(self) -> None:
        if self._medicion_escrita:
            return
        self._medicion_escrita = True
        os.makedirs(CARPETA_MEDIR, exist_ok=True)
        datos = {'t_hub_listo_ms': self.t_hub_listo_ms, 't_ventana_ms': self.t_ventana_ms,
                 't_pagina_ms': self.t_pagina_ms, 'version': config.VERSION}
        destino = os.path.join(CARPETA_MEDIR, 'medicion.json')
        with open(destino + '.nuevo', 'w', encoding='utf-8') as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
        os.replace(destino + '.nuevo', destino)
        _log.info('Medición escrita: hub %s ms · ventana %s ms · página %s ms', self.t_hub_listo_ms, self.t_ventana_ms,
                  self.t_pagina_ms)

    def _tope_medir(self) -> None:
        if self._terminado.wait(TOPE_MEDIR_S) or self.ui_lista.is_set():
            return
        _log.error('--medir: la interfaz no avisó «lista» en %.0f s', TOPE_MEDIR_S)
        self.codigo_salida = 1
        self._escribir_medicion()
        self.salir()

    # ================================================================== hilos activar / salir (C40, 04 §A.5)
    def _vigilar(self, handle: Any, accion: Callable[[], None], nombre: str, una_vez: bool) -> None:
        k32 = kernel32()
        while not self._terminado.is_set():
            if k32.WaitForSingleObject(handle, 500) == WAIT_OBJECT_0:
                if self._terminado.is_set():
                    return
                _log.info('Evento %s recibido', nombre)
                try:
                    accion()
                except Exception:  # noqa: BLE001
                    _log.exception('Error al atender el evento %s', nombre)
                if una_vez:
                    return

    def iniciar_vigilancia(self) -> None:
        if self.instancia is None:
            return
        for nombre, handle, accion, una_vez in (('activar', self.instancia.activar, self.mostrar, False),
                                                ('salir', self.instancia.salir, self.salir, True)):
            h = threading.Thread(target=self._vigilar, args=(handle, accion, nombre, una_vez), name=nombre, daemon=True)
            self._hilos.append(h)
            h.start()

    # ================================================================== ciclo de vida con pywebview
    def _preparar_en_ui(self) -> None:
        """En el hilo de la interfaz, en cuanto existe el formulario: barra de título, bandeja y fin de sesión."""
        hwnd = self._hwnd()
        if hwnd and self._tema:
            dwm.aplicar_tema(hwnd, self._tema)
        if self.bandeja is not None:
            try:
                self.bandeja.crear()
            except Exception:  # noqa: BLE001
                _log.exception('No se pudo crear el ícono de la bandeja')
        try:
            from Microsoft.Win32 import SystemEvents
            SystemEvents.SessionEnding += self.al_terminar_sesion
        except Exception:  # noqa: BLE001
            _log.debug('No se pudo escuchar el fin de sesión de Windows', exc_info=True)

    def _post_arranque(self) -> None:
        """Hilo que lanza `webview.start`: espera el formulario y prepara todo lo que no es la página."""
        v = self.ventana.v
        if not v.events.before_show.wait(TOPE_ARRANQUE_UI_S):
            _log.error('La ventana no se creó en %.0f s', TOPE_ARRANQUE_UI_S)
            return
        try:
            self.ventana.en_ui(self._preparar_en_ui)
        except Exception:  # noqa: BLE001
            _log.exception('Error preparando la ventana')
        self.programador.iniciar()
        self.iniciar_vigilancia()
        threading.Thread(target=self.revisar_boot, name='revisar-boot', daemon=True).start()
        if self.medir:
            threading.Thread(target=self._tope_medir, name='medir', daemon=True).start()

    def revisar_boot(self, tope_s: float = 2 * TOPE_ARRANQUE_UI_S) -> bool:
        """El token de `/boot?t=` vale 60 s y un uso. Si WebView2 tardó más en cargar (primer arranque con Defender),
        la página se queda en el 403 de /boot: se pide un enlace nuevo. True si hubo que recargar."""
        v = self.ventana.v if self.ventana is not None else None
        if v is None or not v.events.loaded.wait(tope_s) or self._terminado.is_set():
            return False
        try:
            url = v.get_current_url() or ''
        except Exception:  # noqa: BLE001
            return False
        if urllib.parse.urlsplit(url).path != '/boot':
            return False
        _log.warning('El enlace de inicio venció antes de cargar la interfaz: se pide otro')
        v.load_url(self.hub.url_arranque())
        return True

    def correr(self) -> int:
        """Crea la ventana y bloquea el hilo principal en `webview.start()` hasta que se cierre."""
        import webview

        webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False   # defensa: nunca webbrowser.open a ciegas
        webview.settings['ALLOW_DOWNLOADS'] = False
        webview.settings['OPEN_DEVTOOLS_IN_DEBUG'] = False
        self.nav = navegacion.Navegacion(lambda: self.origen, self.abrir_url)
        navegacion.instalar_en_pywebview(self.nav)                   # importa edgechromium: CLR y WebView2 Core

        guardado = self._leer_ventana()
        geo = geometria_inicial(guardado, pantallas())
        self._tema = dwm.tema_inicial(guardado.get('tema'))
        w = webview.create_window(
            TITULO, self.hub.url_arranque(), js_api=self.api, width=geo.ancho, height=geo.alto, x=geo.x, y=geo.y,
            min_size=TAMANO_MINIMO, hidden=self.oculta, maximized=geo.maximizada and not self.oculta,
            background_color=dwm.color_fondo(self._tema), text_select=True, zoomable=True)
        self.ventana = VentanaPywebview(w)
        w.events.closing += self.al_cerrar
        w.events.shown += self._al_mostrarse
        for evento in (w.events.moved, w.events.resized, w.events.maximized, w.events.restored):
            evento += self.programar_guardado_geometria
        if self.bandeja is None:
            self.bandeja = bandeja_mod.Bandeja(self.icono, self.mostrar, self.sincronizar, self.salir,
                                               self.al_clic_globo)
        _log.info('Abriendo la ventana (%dx%d%s)', geo.ancho, geo.alto, ', oculta' if self.oculta else '')
        try:
            webview.start(func=self._post_arranque, gui='edgechromium', debug=self.depurar, private_mode=False,
                          storage_path=self.rutas.webview, icon=self.icono)
        finally:
            self._terminado.set()
            self._cancelar_guardado_geometria()
            self.programador.detener()
            for h in self._hilos:
                h.join(1.0)
        _log.info('Ventana cerrada')
        return self.codigo_salida
