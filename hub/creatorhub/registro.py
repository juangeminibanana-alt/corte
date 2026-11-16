"""Registro del hub sin secretos (BUILD_SPEC §6.1; 03 §1, §7.6; 04 §A.2).

- `FormatterLimpio`: aplica `comun.limpiar()` a la cadena FINAL (mensaje + args + traceback + stack) con los secretos
  vivos de la bóveda, y además el filtro de 04 §A.2 (tapa `access_token`, `refresh_token`, `app_secret` con `:` o `=`
  y TODO lo que sigue a `Authorization:` en la línea). Un `logging.Filter` sobre `record.msg` no basta (v07).
- `logs/hub-AAAAMMDD.log`: un archivo por día, máx. 5 MB por archivo (después `hub-AAAAMMDD-2.log`, …), se conservan 7 días.
- `sys.excepthook` y `threading.excepthook` van al registro; si `sys.stdout`/`sys.stderr` son None (exe sin consola),
  se redirigen al registro y `faulthandler` escribe en el archivo del día.
- Nada de `print`: todo el hub usa `logging.getLogger('creatorhub.<modulo>')`.
"""
from __future__ import annotations

import faulthandler
import logging
import os
import re
import sys
import threading
import time
from typing import Any, Callable, Iterable

from .comun import limpiar
from .interfaces import Rutas

FORMATO = '%(asctime)s %(levelname)s %(name)s [%(threadName)s] %(message)s'
DIAS_RETENCION = 7
MAX_BYTES_ARCHIVO = 5 * 1024 * 1024
_RE_ARCHIVO = re.compile(r'^hub-(\d{8})(?:-(\d+))?\.log$')

# Filtro de 04 §A.2 (complementa limpiar(): formas «clave: valor» sin comillas y la cabecera Authorization completa).
_A2_CLAVE = re.compile(r"(?<![A-Za-z0-9_])(access_token|refresh_token|app_secret|auth_code)\s*[:=]\s*(?!\*\*\*)"
                       r"[^\s,;&'\"}\]]+", re.IGNORECASE)
_A2_AUTORIZACION = re.compile(r'(authorization)\s*[:=][^\r\n]*', re.IGNORECASE)


def filtro_a2(texto: str) -> str:
    texto = _A2_AUTORIZACION.sub(lambda m: f'{m.group(1)}: ***', texto)
    return _A2_CLAVE.sub(lambda m: f'{m.group(1)}=***', texto)


class FormatterLimpio(logging.Formatter):
    """Formatter que limpia la cadena final. `secretos_vivos` devuelve los valores literales a tapar (bóveda, claves
    de dispositivos); se puede fijar después con `fijar_secretos_vivos()`."""

    def __init__(self, fmt: str | None = FORMATO, datefmt: str | None = None,
                 secretos_vivos: Callable[[], Iterable[str]] | None = None) -> None:
        super().__init__(fmt, datefmt)
        self.secretos_vivos = secretos_vivos

    def format(self, record: logging.LogRecord) -> str:
        texto = super().format(record)
        vivos: Iterable[str] = ()
        if self.secretos_vivos is not None:
            try:
                vivos = tuple(self.secretos_vivos())
            except Exception:  # noqa: BLE001 - el registro nunca debe tumbar al hub
                vivos = ()
        return filtro_a2(limpiar(texto, vivos))


class _ManejadorDiario(logging.Handler):
    """`hub-AAAAMMDD.log` (fecha local del equipo), 5 MB por archivo, purga de lo que tenga más de 7 días."""

    def __init__(self, carpeta: str, dias: int = DIAS_RETENCION, max_bytes: int = MAX_BYTES_ARCHIVO) -> None:
        super().__init__()
        self.carpeta = carpeta
        self.dias = dias
        self.max_bytes = max_bytes
        self._fecha: str | None = None
        self._parte = 1
        self._f: Any = None
        self.ruta_actual: str | None = None
        os.makedirs(carpeta, exist_ok=True)
        self._abrir(time.strftime('%Y%m%d'))

    def _nombre(self, fecha: str, parte: int) -> str:
        return f'hub-{fecha}.log' if parte == 1 else f'hub-{fecha}-{parte}.log'

    def _abrir(self, fecha: str) -> None:
        if self._f is not None:
            self._f.close()
        self._fecha, self._parte = fecha, 1
        while True:      # al reabrir el mismo día se sigue en la última parte que no esté llena
            ruta = os.path.join(self.carpeta, self._nombre(fecha, self._parte))
            if not os.path.exists(ruta) or os.path.getsize(ruta) < self.max_bytes:
                break
            self._parte += 1
        self.ruta_actual = ruta
        self._f = open(ruta, 'a', encoding='utf-8', errors='backslashreplace', newline='\n')
        self.purgar()

    def purgar(self) -> None:
        limite = time.strftime('%Y%m%d', time.localtime(time.time() - (self.dias - 1) * 86400))
        try:
            nombres = os.listdir(self.carpeta)
        except OSError:
            return
        for n in nombres:
            m = _RE_ARCHIVO.match(n)
            if m and m.group(1) < limite:
                try:
                    os.remove(os.path.join(self.carpeta, n))
                except OSError:
                    pass

    def emit(self, record: logging.LogRecord) -> None:
        try:
            texto = self.format(record)
            fecha = time.strftime('%Y%m%d')
            if fecha != self._fecha:
                self._abrir(fecha)
            elif self._f.tell() >= self.max_bytes:
                self._f.close()
                self._parte += 1
                self.ruta_actual = os.path.join(self.carpeta, self._nombre(fecha, self._parte))
                self._f = open(self.ruta_actual, 'a', encoding='utf-8', errors='backslashreplace', newline='\n')
            self._f.write(texto + '\n')
            self._f.flush()
        except Exception:  # noqa: BLE001
            self.handleError(record)

    def handleError(self, record: logging.LogRecord) -> None:
        # El manejador por omisión imprime el registro (con sus args) en stderr: podría filtrar un secreto.
        pass

    def close(self) -> None:
        self.acquire()
        try:
            if self._f is not None:
                self._f.close()
                self._f = None
        finally:
            self.release()
        super().close()


class _FlujoAlRegistro:
    """Sustituye a sys.stdout/sys.stderr cuando son None (exe sin consola): cada línea va al registro limpio."""

    encoding = 'utf-8'
    errors = 'backslashreplace'

    def __init__(self, nombre: str, nivel: int) -> None:
        self._log = logging.getLogger(nombre)
        self._nivel = nivel
        self._pendiente = ''
        self._dentro = threading.local()

    def write(self, texto: str) -> int:
        if getattr(self._dentro, 'activo', False):
            return len(texto)
        self._dentro.activo = True
        try:
            self._pendiente += str(texto)
            *lineas, self._pendiente = self._pendiente.split('\n')
            for linea in lineas:
                if linea.strip():
                    self._log.log(self._nivel, '%s', linea.rstrip('\r'))
        finally:
            self._dentro.activo = False
        return len(texto)

    def flush(self) -> None:
        if self._pendiente.strip():
            linea, self._pendiente = self._pendiente, ''
            self.write(linea + '\n')

    def isatty(self) -> bool:
        return False

    def writable(self) -> bool:
        return True


class _Estado:
    def __init__(self) -> None:
        self.manejadores: list[logging.Handler] = []
        self.formatters: list[FormatterLimpio] = []
        self.nivel_raiz: int | None = None
        self.excepthook_previo: Any = None
        self.threading_previo: Any = None
        self.stdout_previo: Any = None
        self.stderr_previo: Any = None
        self.redirigido = False
        self.archivo_fallos: Any = None


_estado = _Estado()
_candado = threading.Lock()


def _excepthook(tipo: type[BaseException], valor: BaseException, tb: Any) -> None:
    if issubclass(tipo, KeyboardInterrupt):
        sys.__excepthook__(tipo, valor, tb)
        return
    logging.getLogger('creatorhub').critical('Excepción no controlada', exc_info=(tipo, valor, tb))


def _threading_excepthook(args: threading.ExceptHookArgs) -> None:
    if args.exc_type is SystemExit:
        return
    nombre = args.thread.name if args.thread is not None else '?'
    logging.getLogger('creatorhub').error('Excepción no controlada en el hilo %s', nombre,
                                          exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def configurar_registro(rutas: Rutas, depurar: bool = False) -> None:
    """Instala el registro limpio en la raíz de logging. Idempotente: una segunda llamada reemplaza a la primera."""
    with _candado:
        _cerrar_sin_candado()
        nivel = logging.DEBUG if depurar else logging.INFO
        formatter = FormatterLimpio(FORMATO)
        archivo = _ManejadorDiario(rutas.logs)
        archivo.setFormatter(formatter)
        archivo.setLevel(nivel)
        raiz = logging.getLogger()
        _estado.nivel_raiz = raiz.level
        raiz.setLevel(nivel)
        raiz.addHandler(archivo)
        _estado.manejadores.append(archivo)
        _estado.formatters.append(formatter)
        if depurar and sys.stderr is not None:
            consola = logging.StreamHandler(sys.stderr)
            f2 = FormatterLimpio(FORMATO)
            consola.setFormatter(f2)
            consola.setLevel(nivel)
            raiz.addHandler(consola)
            _estado.manejadores.append(consola)
            _estado.formatters.append(f2)
        _estado.excepthook_previo = sys.excepthook
        _estado.threading_previo = threading.excepthook
        sys.excepthook = _excepthook
        threading.excepthook = _threading_excepthook
        if sys.stdout is None or sys.stderr is None:
            _estado.stdout_previo, _estado.stderr_previo = sys.stdout, sys.stderr
            if sys.stdout is None:
                sys.stdout = _FlujoAlRegistro('creatorhub.stdout', logging.INFO)  # type: ignore[assignment]
            if sys.stderr is None:
                sys.stderr = _FlujoAlRegistro('creatorhub.stderr', logging.WARNING)  # type: ignore[assignment]
            _estado.redirigido = True
            try:
                _estado.archivo_fallos = open(archivo.ruta_actual or os.path.join(rutas.logs, 'hub-fallos.log'), 'a',
                                              encoding='utf-8')
                faulthandler.enable(file=_estado.archivo_fallos)
            except (OSError, ValueError):
                _estado.archivo_fallos = None


def fijar_secretos_vivos(fuente: Callable[[], Iterable[str]] | None) -> None:
    """hub.py la llama con `boveda.secretos_vivos` (y las claves de dispositivos) en cuanto existe la bóveda."""
    with _candado:
        for f in _estado.formatters:
            f.secretos_vivos = fuente


def ruta_registro_actual() -> str | None:
    for m in _estado.manejadores:
        if isinstance(m, _ManejadorDiario):
            return m.ruta_actual
    return None


def _cerrar_sin_candado() -> None:
    raiz = logging.getLogger()
    for m in _estado.manejadores:
        raiz.removeHandler(m)
        try:
            m.close()
        except Exception:  # noqa: BLE001
            pass
    _estado.manejadores.clear()
    _estado.formatters.clear()
    if _estado.nivel_raiz is not None:
        raiz.setLevel(_estado.nivel_raiz)
        _estado.nivel_raiz = None
    if _estado.excepthook_previo is not None:
        sys.excepthook = _estado.excepthook_previo
        _estado.excepthook_previo = None
    if _estado.threading_previo is not None:
        threading.excepthook = _estado.threading_previo
        _estado.threading_previo = None
    if _estado.redirigido:
        sys.stdout, sys.stderr = _estado.stdout_previo, _estado.stderr_previo
        _estado.redirigido = False
        if _estado.archivo_fallos is not None:
            try:
                faulthandler.disable()
                _estado.archivo_fallos.close()
            except (OSError, ValueError):
                pass
            _estado.archivo_fallos = None


def cerrar_registro() -> None:
    """Quita lo que instaló configurar_registro (manejadores, ganchos y redirecciones). Lo usan las pruebas y el cierre."""
    with _candado:
        _cerrar_sin_candado()
