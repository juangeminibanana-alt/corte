"""Inicio con Windows (04 §A.7): `HKCU\\…\\Run\\CreatorHub` + `…\\Explorer\\StartupApproved\\Run\\CreatorHub`.

- Encender: escribe `Run\\CreatorHub` = `"<exe>" --inicio-windows` y borra `StartupApproved\\Run\\CreatorHub` (si el
  usuario lo había apagado desde el Administrador de tareas, encenderlo desde la app lo vuelve a habilitar).
- Estado real: `(activo, bloqueado)`. Si el primer byte de StartupApproved es impar (0x03) el usuario lo apagó desde el
  Administrador de tareas: la interfaz lo muestra apagado (`iniciar_con_windows_bloqueado`).
- `--desinstalar` borra los dos valores. Sin administrador: todo es HKCU.

Las claves son parámetros de `InicioWindows` para que las pruebas usen una subclave propia que borran al terminar.
"""
from __future__ import annotations

import logging
import os
import sys
import winreg
from typing import Any

_log = logging.getLogger('creatorhub.plataforma.inicio')

CLAVE_RUN = r'Software\Microsoft\Windows\CurrentVersion\Run'
CLAVE_APROBADO = r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
VALOR = 'CreatorHub'
BANDERA = '--inicio-windows'


def comando_inicio() -> str:
    """Lo que Windows ejecuta al iniciar sesión. Exe: `"…\\CreatorHub.exe" --inicio-windows`. Desde el código (solo
    desarrollo): `pythonw.exe` del entorno con la ruta de `__main__.py` (que se agrega `hub\\` a sys.path solo)."""
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}" {BANDERA}'
    carpeta = os.path.dirname(sys.executable)
    pythonw = os.path.join(carpeta, 'pythonw.exe')
    interprete = pythonw if os.path.isfile(pythonw) else sys.executable
    principal = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '__main__.py')
    return f'"{interprete}" "{principal}" {BANDERA}'


class InicioWindows:
    def __init__(self, clave_run: str = CLAVE_RUN, clave_aprobado: str = CLAVE_APROBADO, valor: str = VALOR,
                 comando: str | None = None, raiz: Any = winreg.HKEY_CURRENT_USER) -> None:
        self.clave_run = clave_run
        self.clave_aprobado = clave_aprobado
        self.valor = valor
        self._comando = comando
        self.raiz = raiz

    @property
    def comando(self) -> str:
        return self._comando if self._comando is not None else comando_inicio()

    # ------------------------------------------------------------------ registro
    def _leer(self, clave: str) -> tuple[Any, int] | None:
        try:
            with winreg.OpenKey(self.raiz, clave, 0, winreg.KEY_READ) as k:
                return winreg.QueryValueEx(k, self.valor)
        except FileNotFoundError:
            return None
        except OSError as e:
            _log.warning('No se pudo leer el registro (%s)', type(e).__name__)
            return None

    def _borrar(self, clave: str) -> None:
        try:
            with winreg.OpenKey(self.raiz, clave, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, self.valor)
        except FileNotFoundError:
            pass

    # ------------------------------------------------------------------ API
    def estado(self) -> tuple[bool, bool]:
        """(activo, bloqueado por el Administrador de tareas)."""
        run = self._leer(self.clave_run)
        if run is None or not str(run[0]).strip():
            return False, False
        aprobado = self._leer(self.clave_aprobado)
        bloqueado = False
        if aprobado is not None:
            datos, tipo = aprobado
            if tipo == winreg.REG_BINARY and isinstance(datos, (bytes, bytearray)) and len(datos) > 0:
                bloqueado = bool(datos[0] & 1)
        return (not bloqueado), bloqueado

    def aplicar(self, activo: bool) -> None:
        if activo:
            with winreg.CreateKeyEx(self.raiz, self.clave_run, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, self.valor, 0, winreg.REG_SZ, self.comando)
            self._borrar(self.clave_aprobado)
            _log.info('Inicio con Windows encendido')
        else:
            self._borrar(self.clave_run)
            self._borrar(self.clave_aprobado)
            _log.info('Inicio con Windows apagado')

    def borrar(self) -> None:
        """--desinstalar: quita los dos valores (sin error si no existen)."""
        for clave in (self.clave_run, self.clave_aprobado):
            try:
                self._borrar(clave)
            except OSError as e:
                _log.warning('No se pudo borrar un valor del registro (%s)', type(e).__name__)
