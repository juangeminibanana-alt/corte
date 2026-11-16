"""`window.pywebview.api` de Corte: EXACTAMENTE `ApiPywebview` de spec/ui_firmas/plataforma.d.ts (BUILD_SPEC §6.6).

tema · abrir_externo · copiar · notificar · programar_notificaciones · ventana_ocultar · ventana_cerrar · guardar_imagen ·
guardar_archivo · elegir_archivo · lista. Nada más es público: pywebview expone TODO método público y recorre los
atributos públicos que sean objetos, así que el estado vive en atributos con guion bajo.

Reglas comunes: cada método valida sus argumentos, nunca lanza hacia la interfaz (devuelve el valor de error de su firma)
y nunca devuelve ni registra secretos ni contenidos (solo el tipo de error). pywebview llama cada método en un hilo
aparte; lo que toca la interfaz nativa lo resuelve la ventana (`_shell`).

`_shell` es la ventana (`ventana.ShellVentana`) o un doble en las pruebas. Usa: `hub` (HubProto), `aplicar_tema(modo)`,
`abrir_url(url)`, `copiar_texto(texto) -> bool`, `mostrar_globo(Notificacion)`, `programador` (`notificaciones.Programador`),
`ocultar()`, `cerrar_del_todo()`, `dialogo(tipo, nombre, file_types) -> tuple[str, ...] | None` (tipo 'abrir'|'guardar')
e `interfaz_lista()`.
"""
from __future__ import annotations

import ctypes
import logging
import os
import re
import shutil
import time
from ctypes import wintypes
from typing import Any, Callable, TypeVar

from creatorhub.plataforma.windows import navegacion, notificaciones

_log = logging.getLogger('creatorhub.plataforma.js_api')

T = TypeVar('T')

METODOS: tuple[str, ...] = ('tema', 'abrir_externo', 'copiar', 'notificar', 'programar_notificaciones',
                            'ventana_ocultar', 'ventana_cerrar', 'guardar_imagen', 'guardar_archivo', 'elegir_archivo',
                            'lista')
FILTRO_JSON = 'Archivos JSON (*.json)'                     # C46 / §6.6: create_file_dialog(OPEN_DIALOG, file_types=(…,))
FILTRO_CSV = 'Archivos CSV (*.csv)'
FILTROS_IMAGEN: dict[str, str] = {'.webp': 'Imagen WebP (*.webp)', '.jpg': 'Imagen JPEG (*.jpg)',
                                  '.jpeg': 'Imagen JPEG (*.jpeg)', '.png': 'Imagen PNG (*.png)',
                                  '.gif': 'Imagen GIF (*.gif)'}
MIMES: dict[str, tuple[str, str]] = {'application/json': ('.json', FILTRO_JSON), 'text/csv': ('.csv', FILTRO_CSV)}
MAX_TEXTO_COPIAR = 1024 * 1024
MAX_CONTENIDO = 50 * 1024 * 1024
MAX_NOMBRE = 120
_RE_INVALIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVADOS = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}


def _seguro(nombre: str, valor_error: T, fn: Callable[..., T], *args: Any) -> T:
    """Ningún error sale hacia la interfaz: se registra el TIPO (nunca el mensaje ni los argumentos). Los métodos
    públicos conservan su firma real (pywebview la lee con inspect.getfullargspec)."""
    try:
        return fn(*args)
    except Exception as e:  # noqa: BLE001
        _log.warning('js_api.%s falló (%s)', nombre, type(e).__name__)
        return valor_error


def nombre_seguro(nombre: Any, extension: str, omision: str = 'archivo') -> str:
    """Nombre sugerido para un diálogo Guardar: sin caracteres inválidos de Windows, ≤ 120, con `extension`."""
    base = nombre if isinstance(nombre, str) else ''
    base = _RE_INVALIDOS.sub(' ', base).strip().rstrip('. ')
    raiz, ext = os.path.splitext(base)
    if ext.lower() in (extension.lower(), '.json', '.csv', *FILTROS_IMAGEN):
        base = raiz.rstrip('. ')
    base = re.sub(r'\s+', ' ', base)[:MAX_NOMBRE].rstrip('. ') or omision
    if base.split('.')[0].upper() in _RESERVADOS:
        base = '_' + base
    return base + extension


def con_extension(ruta: str, extension: str) -> str:
    return ruta if ruta.lower().endswith(extension.lower()) else ruta + extension


def escribir_atomico_texto(ruta: str, datos: bytes) -> None:
    temporal = ruta + '.nuevo'
    try:
        with open(temporal, 'wb') as f:
            f.write(datos)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporal, ruta)
    except BaseException:
        try:
            os.remove(temporal)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------- portapapeles (escritura; nunca se lee aquí)
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _dlls_portapapeles() -> tuple[Any, Any]:
    u32 = ctypes.WinDLL('user32', use_last_error=True)
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    u32.OpenClipboard.argtypes = [wintypes.HWND]
    u32.OpenClipboard.restype = wintypes.BOOL
    u32.EmptyClipboard.restype = wintypes.BOOL
    u32.CloseClipboard.restype = wintypes.BOOL
    u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u32.SetClipboardData.restype = wintypes.HANDLE
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalAlloc.restype = wintypes.HGLOBAL
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    return u32, k32


def escribir_portapapeles(texto: str, dlls: tuple[Any, Any] | None = None, intentos: int = 10) -> bool:
    """Pone `texto` (CF_UNICODETEXT) en el portapapeles. Funciona desde cualquier hilo (no requiere STA)."""
    u32, k32 = dlls or _dlls_portapapeles()
    datos = (texto + '\x00').encode('utf-16-le')
    for _ in range(intentos):                                        # otra app puede tenerlo abierto un instante
        if u32.OpenClipboard(None):
            break
        time.sleep(0.03)
    else:
        return False
    try:
        if not u32.EmptyClipboard():
            return False
        h = k32.GlobalAlloc(GMEM_MOVEABLE, len(datos))
        if not h:
            return False
        p = k32.GlobalLock(h)
        if not p:
            k32.GlobalFree(h)
            return False
        try:
            ctypes.memmove(p, datos, len(datos))
        finally:
            k32.GlobalUnlock(h)
        if not u32.SetClipboardData(CF_UNICODETEXT, h):
            k32.GlobalFree(h)
            return False
        return True                                                  # el portapapeles ya es dueño de la memoria
    finally:
        u32.CloseClipboard()


# ---------------------------------------------------------------------- ApiPywebview
class ApiPywebview:
    """window.pywebview.api (04 §A.4 + BUILD_SPEC §6.6). Todos los métodos se usan con await desde la interfaz."""

    def __init__(self, shell: Any) -> None:
        self._shell = shell

    # ------------------------------------------------------------------ públicos (exactamente los 11 de la firma)
    def tema(self, modo: str) -> None:
        return _seguro('tema', None, self._tema, modo)

    def abrir_externo(self, url: str) -> bool:
        return _seguro('abrir_externo', False, self._abrir_externo, url)

    def copiar(self, texto: str) -> bool:
        return _seguro('copiar', False, self._copiar, texto)

    def notificar(self, titulo: str, texto: str, ruta: str) -> None:
        return _seguro('notificar', None, self._notificar, titulo, texto, ruta)

    def programar_notificaciones(self, lista_json: str) -> None:
        return _seguro('programar_notificaciones', None, self._programar_notificaciones, lista_json)

    def ventana_ocultar(self) -> None:
        return _seguro('ventana_ocultar', None, lambda: self._shell.ocultar())

    def ventana_cerrar(self) -> None:
        return _seguro('ventana_cerrar', None, lambda: self._shell.cerrar_del_todo())

    def guardar_imagen(self, ruta_img: str, nombre: str) -> str:
        return _seguro('guardar_imagen', 'error', self._guardar_imagen, ruta_img, nombre)

    def guardar_archivo(self, nombre: str, mime: str, contenido: str) -> str:
        return _seguro('guardar_archivo', 'error', self._guardar_archivo, nombre, mime, contenido)

    def elegir_archivo(self, titulo: str, filtros: list[str]) -> str | None:
        """C46: diálogo Abrir nativo con filtro de JSON. Devuelve la RUTA (solo viaja al hub) o None si canceló."""
        return _seguro('elegir_archivo', None, self._elegir_archivo, titulo, filtros)

    def lista(self) -> None:
        return _seguro('lista', None, lambda: self._shell.interfaz_lista())

    # ------------------------------------------------------------------ implementación
    def _tema(self, modo: Any) -> None:
        if modo in ('claro', 'oscuro'):
            self._shell.aplicar_tema(modo)

    def _abrir_externo(self, url: Any) -> bool:
        if not navegacion.url_externa_permitida(url):
            _log.info('abrir_externo rechazado (%s)', navegacion.host_de(url))
            return False
        self._shell.abrir_url(url)
        return True

    def _copiar(self, texto: Any) -> bool:
        if not isinstance(texto, str) or len(texto) > MAX_TEXTO_COPIAR:
            return False
        return bool(self._shell.copiar_texto(texto))

    def _notificar(self, titulo: Any, texto: Any, ruta: Any) -> None:
        n = notificaciones.desde_dict({'id': 'inmediata', 'titulo': titulo, 'texto': texto, 'at': 1, 'ruta': ruta})
        if n is None:
            _log.info('notificar: datos inválidos, se omite')
            return
        self._shell.mostrar_globo(n)

    def _programar_notificaciones(self, lista_json: Any) -> None:
        lista = notificaciones.validar_lista(lista_json)
        pendientes = self._shell.programador.programar(lista)
        _log.info('Notificaciones programadas: %d', pendientes)

    def _guardar_imagen(self, ruta_img: Any, nombre: Any) -> str:
        if not isinstance(ruta_img, str):
            return 'error'
        origen = self._shell.hub.ruta_imagen_original(ruta_img)       # '/img/p/<id>?v=…' → original de la caché
        if not origen or not os.path.isfile(origen):
            return 'error'
        ext = os.path.splitext(origen)[1].lower()
        filtro = FILTROS_IMAGEN.get(ext)
        if filtro is None:
            return 'error'
        elegido = self._shell.dialogo('guardar', nombre_seguro(nombre, ext, 'imagen'), (filtro,))
        if not elegido:
            return 'cancelado'
        destino = con_extension(str(elegido[0]), ext)
        if os.path.normcase(os.path.abspath(destino)) == os.path.normcase(os.path.abspath(origen)):
            return 'guardado'
        temporal = destino + '.nuevo'
        try:
            shutil.copyfile(origen, temporal)
            os.replace(temporal, destino)
        except BaseException:
            try:
                os.remove(temporal)
            except OSError:
                pass
            raise
        return 'guardado'

    def _guardar_archivo(self, nombre: Any, mime: Any, contenido: Any) -> str:
        if mime not in MIMES or not isinstance(contenido, str) or len(contenido) > MAX_CONTENIDO:
            return 'error'
        ext, filtro = MIMES[mime]
        elegido = self._shell.dialogo('guardar', nombre_seguro(nombre, ext), (filtro,))
        if not elegido:
            return 'cancelado'
        destino = con_extension(str(elegido[0]), ext)
        datos = contenido.encode('utf-8')
        if ext == '.csv':
            datos = b'\xef\xbb\xbf' + datos                          # BOM: Excel en es-MX abre bien los acentos
        escribir_atomico_texto(destino, datos)
        return 'guardado'

    def _elegir_archivo(self, titulo: Any, filtros: Any) -> str | None:
        """pywebview 6.2.1 no permite fijar el título del diálogo Abrir: `titulo` se ignora. Solo existe el filtro
        'json' (elegirArchivo(titulo, Array<'json'>)): siempre 'Archivos JSON (*.json)'."""
        if filtros is not None and not isinstance(filtros, (list, tuple)):
            return None
        elegido = self._shell.dialogo('abrir', '', (FILTRO_JSON,))
        if not elegido:
            return None
        ruta = str(elegido[0])
        return ruta if os.path.isabs(ruta) else None
