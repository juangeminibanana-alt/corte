"""Navegación de la ventana de Corte (BUILD_SPEC §6.4, §6.6, C43; 04 §A.9).

Tres ganchos de `CoreWebView2`, todos en el hilo de la interfaz:

- `NavigationStarting` (marco principal, 04 §A.9): el origen local (`http://127.0.0.1:<p>/…`), `about:blank` y `data:`
  pasan; todo lo demás se CANCELA y, si es https a un host de la lista de §6.4, se abre en el navegador del sistema.
- `NewWindowRequested` (`window.open`, `target=_blank`, C43): SIEMPRE `Handled = True` (nunca se abre una ventana de
  WebView2); solo si el host está en la lista se abre en el navegador. Un host fuera de la lista no abre NADA.
- `FrameNavigationStarting` (iframes, C43): solo `https://www.tiktok.com/…` (el reproductor oficial). Ojo, interfaz:
  se cancela cualquier otra navegación de iframe que WebView2 avise (`about:blank`, `about:srcdoc`, `data:`, otros
  hosts), así que en Windows no hay que contar con iframes para medir texto, imprimir ni aislar contenido; el único que
  carga es el de `ReproductorTikTok`.

pywebview 6.2.1 engancha su propio `NewWindowRequested` (que llama `webbrowser.open` con CUALQUIER URL) dentro de
`EdgeChrome.on_webview_ready`. `instalar_en_pywebview()` reemplaza, antes de crear la ventana, ese manejador por el
nuestro y envuelve `on_webview_ready` para enganchar los otros dos en cuanto existe `CoreWebView2`, antes de la primera
navegación. Como defensa adicional el shell pone `OPEN_EXTERNAL_LINKS_IN_BROWSER = False`.

Las decisiones son funciones puras (`decidir_*`) para poder probarlas sin WebView2. Nunca se registra una URL completa
(puede traer el token de `/boot?t=`): solo el host y la decisión.
"""
from __future__ import annotations

import logging
import os
import threading
import urllib.parse
from typing import Any, Callable

from creatorhub import config

_log = logging.getLogger('creatorhub.plataforma.navegacion')

HOSTS_PERMITIDOS: frozenset[str] = config.HOSTS_PERMITIDOS          # 03 §7.7 + §6.4 (exactamente estos 5)
HOST_AVISO_WEBVIEW2: str = config.HOST_AVISO_WEBVIEW2               # solo el aviso de WebView2, desde el shell
HOST_REPRODUCTOR = 'www.tiktok.com'
MAX_URL = 2048

PERMITIR = 'permitir'
CANCELAR = 'cancelar'
ABRIR_FUERA = 'abrir_fuera'


def _partes(url: Any) -> urllib.parse.SplitResult | None:
    """urlsplit de una URL bien formada (texto, ≤ 2048, sin espacios ni caracteres de control), o None."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL:
        return None
    if any(ord(c) <= 32 or ord(c) == 127 for c in url):
        return None
    try:
        partes = urllib.parse.urlsplit(url)
        partes.port                                                  # noqa: B018 - ValueError si el puerto no es válido
    except ValueError:
        return None
    return partes


def _https_al_host(url: Any, hosts: frozenset[str] | set[str]) -> bool:
    p = _partes(url)
    if p is None or p.scheme.lower() != 'https' or p.username is not None or p.password is not None:
        return False
    try:
        puerto = p.port
    except ValueError:
        return False
    if puerto not in (None, 443):
        return False
    return (p.hostname or '') in hosts


def url_externa_permitida(url: Any, con_aviso_webview2: bool = False) -> bool:
    """True si `url` es https (puerto 443, sin usuario) a uno de los hosts EXACTOS de §6.4. `go.microsoft.com` solo
    cuenta con `con_aviso_webview2` (el aviso de WebView2 lo abre el shell, nunca la interfaz)."""
    hosts = HOSTS_PERMITIDOS | {HOST_AVISO_WEBVIEW2} if con_aviso_webview2 else HOSTS_PERMITIDOS
    return _https_al_host(url, hosts)


def es_marco_permitido(url: Any) -> bool:
    """FrameNavigationStarting (C43): solo `https://www.tiktok.com/…`."""
    return _https_al_host(url, {HOST_REPRODUCTOR})


def es_navegacion_local(url: Any, origen: str) -> bool:
    """Lo que puede cargar el marco principal sin salir de la app (04 §A.9)."""
    if not isinstance(url, str):
        return False
    if url == 'about:blank' or url.startswith('data:'):
        return True
    return bool(origen) and (url == origen or url.startswith(origen + '/'))


def decidir_navegacion(url: Any, origen: str) -> str:
    if es_navegacion_local(url, origen):
        return PERMITIR
    return ABRIR_FUERA if url_externa_permitida(url) else CANCELAR


def decidir_ventana_nueva(url: Any) -> str:
    """NewWindowRequested: nunca una ventana de WebView2; abrir fuera solo con host permitido."""
    return ABRIR_FUERA if url_externa_permitida(url) else CANCELAR


def decidir_marco(url: Any) -> str:
    return PERMITIR if es_marco_permitido(url) else CANCELAR


def host_de(url: Any) -> str:
    p = _partes(url)
    if p is None:
        return '(inválida)'
    if p.scheme in ('about', 'data', 'blob', 'javascript'):
        return p.scheme + ':'
    return p.hostname or p.scheme + ':'


def abrir_en_navegador(url: str) -> None:
    """Navegador predeterminado de Windows. Solo se llama con una URL que ya pasó la lista de §6.4."""
    os.startfile(url)                                                # type: ignore[attr-defined]  (solo Windows)


class Navegacion:
    """Manejadores de CoreWebView2. `origen` es 'http://127.0.0.1:<puerto>' (o una función que lo devuelve).
    `abrir` recibe solo URLs permitidas. `decisiones` guarda (evento, decisión, host) para diagnóstico y pruebas."""

    MAX_DECISIONES = 200

    def __init__(self, origen: str | Callable[[], str], abrir: Callable[[str], None] = abrir_en_navegador) -> None:
        self._origen = origen
        self._abrir = abrir
        self._candado = threading.Lock()
        self.decisiones: list[tuple[str, str, str]] = []
        self.enganchado = False

    @property
    def origen(self) -> str:
        return self._origen() if callable(self._origen) else self._origen

    def _anotar(self, evento: str, decision: str, url: str) -> None:
        with self._candado:
            self.decisiones.append((evento, decision, host_de(url)))
            del self.decisiones[:-self.MAX_DECISIONES]
        if decision != PERMITIR:
            _log.info('%s: %s (%s)', evento, decision, host_de(url))

    def _abrir_fuera(self, url: str) -> None:
        if not url_externa_permitida(url):                           # segunda barrera: nunca abrir algo fuera de la lista
            return
        try:
            self._abrir(url)
        except OSError as e:
            _log.warning('No se pudo abrir el navegador (%s)', type(e).__name__)

    # ------------------------------------------------------------------ manejadores (hilo de la interfaz)
    def al_navegar(self, _remitente: Any, args: Any) -> None:
        try:
            url = str(args.Uri)
            decision = decidir_navegacion(url, self.origen)
            if decision != PERMITIR:
                args.Cancel = True
            self._anotar('navegacion', decision, url)
            if decision == ABRIR_FUERA:
                self._abrir_fuera(url)
        except Exception:  # noqa: BLE001 - un error aquí nunca debe dejar pasar la navegación
            args.Cancel = True
            _log.exception('Error en NavigationStarting: navegación cancelada')

    def al_pedir_ventana(self, _remitente: Any, args: Any) -> None:
        try:
            args.Handled = True                                      # nunca una ventana nueva de WebView2
            url = str(args.Uri)
            decision = decidir_ventana_nueva(url)
            self._anotar('ventana_nueva', decision, url)
            if decision == ABRIR_FUERA:
                self._abrir_fuera(url)
        except Exception:  # noqa: BLE001
            _log.exception('Error en NewWindowRequested: no se abrió nada')

    def al_navegar_marco(self, _remitente: Any, args: Any) -> None:
        try:
            url = str(args.Uri)
            decision = decidir_marco(url)
            if decision != PERMITIR:
                args.Cancel = True
            self._anotar('marco', decision, url)
        except Exception:  # noqa: BLE001
            args.Cancel = True
            _log.exception('Error en FrameNavigationStarting: navegación del marco cancelada')

    def enganchar(self, core: Any) -> None:
        """Engancha NavigationStarting y FrameNavigationStarting en `CoreWebView2` (hilo de la interfaz) y apaga lo que
        la app no usa (autollenado y guardado de contraseñas)."""
        core.NavigationStarting += self.al_navegar
        core.FrameNavigationStarting += self.al_navegar_marco
        try:
            ajustes = core.Settings
            ajustes.IsGeneralAutofillEnabled = False
            ajustes.IsPasswordAutosaveEnabled = False
        except Exception:  # noqa: BLE001 - propiedades de versiones nuevas del SDK: opcionales
            _log.debug('Ajustes opcionales de WebView2 no disponibles', exc_info=True)
        self.enganchado = True
        _log.info('Ganchos de navegación instalados')


# ---------------------------------------------------------------------- integración con pywebview 6.2.1
_navegacion_activa: Navegacion | None = None


def instalar_en_pywebview(nav: Navegacion) -> None:
    """Debe llamarse ANTES de `webview.create_window`/`start`. Reemplaza `EdgeChrome.on_new_window_request` y envuelve
    `EdgeChrome.on_webview_ready` (pywebview los engancha con `self.<método>`, que se resuelve en la clase)."""
    global _navegacion_activa
    from webview.platforms import edgechromium as ec               # carga el CLR: solo después de «listo»

    _navegacion_activa = nav
    clase: Any = ec.EdgeChrome
    original = getattr(clase, '_ch_on_webview_ready_original', None)
    if original is None:
        original = clase.on_webview_ready
        clase._ch_on_webview_ready_original = original

    def on_webview_ready(self: Any, sender: Any, args: Any) -> None:
        original(self, sender, args)
        activa = _navegacion_activa
        if activa is None:
            return
        try:
            if args.IsSuccess:
                activa.enganchar(sender.CoreWebView2)
        except Exception:  # noqa: BLE001
            _log.exception('No se pudieron instalar los ganchos de navegación')

    def on_new_window_request(self: Any, sender: Any, args: Any) -> None:
        activa = _navegacion_activa
        if activa is None:                                           # sin shell: igual nunca abre nada a ciegas
            args.Handled = True
            return
        activa.al_pedir_ventana(sender, args)

    clase.on_webview_ready = on_webview_ready
    clase.on_new_window_request = on_new_window_request
