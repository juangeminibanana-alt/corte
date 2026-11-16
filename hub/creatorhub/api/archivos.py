"""Archivos que elige el usuario (BUILD_SPEC §6.3.4 «Archivos del usuario», C46).

`leer_json_usuario(ruta, max_bytes)`: la ruta la devolvió el selector nativo (`elegirArchivo`) y solo viaja al hub.
Reglas: ruta absoluta LOCAL con letra de unidad (sin `\\\\servidor`, `\\\\?\\` ni `\\\\.\\`, sin flujos alternos `:`,
sin caracteres de control, sin unidades de red mapeadas), archivo regular que no sea un enlace simbólico, extensión
`.json`, tamaño ≤ tope, UTF-8 y `json.loads`. Errores: `archivo_no_encontrado` (404) y `archivo_invalido` (400 si la
ruta no sirve, 422 si el contenido no sirve). El contenido nunca vuelve a la interfaz ni se registra.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import stat
from typing import Any

from ..errores import ErrorDominio

_log = logging.getLogger('creatorhub.api.archivos')

MAX_PLAN_BYTES = 20 * 1024 * 1024           # POST /api/local/importar (C46)
MAX_CREDENCIALES_BYTES = 1024 * 1024        # auth.importar (lo valida importador_legado, hub-nucleo)
MAX_RUTA = 1024

_RE_UNIDAD = re.compile(r'^[A-Za-z]:\\')
_DRIVE_NO_ROOT_DIR = 1
_DRIVE_REMOTE = 4

MSG_RUTA = 'Elige un archivo .json que esté guardado en esta PC.'
MSG_NO_EXISTE = 'No encontramos ese archivo. ¿Lo moviste o lo borraste?'
MSG_GRANDE = 'Ese archivo es demasiado grande para importarlo.'
MSG_CONTENIDO = 'Ese archivo no se puede leer: no es un archivo .json válido.'


def _invalido(mensaje: str = MSG_RUTA, http: int = 400) -> ErrorDominio:
    return ErrorDominio('archivo_invalido', mensaje, http=http)


def _tipo_unidad(raiz: str) -> int | None:
    """GetDriveTypeW de la unidad (None fuera de Windows o si falla)."""
    try:
        return int(ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(raiz)))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return None


def validar_ruta(ruta: Any) -> str:
    """Devuelve la ruta normalizada o lanza ErrorDominio('archivo_invalido', http=400). No toca el contenido."""
    if not isinstance(ruta, str):
        raise _invalido()
    r = ruta.strip()
    if not r or len(r) > MAX_RUTA or any(ord(c) < 32 or ord(c) == 127 for c in r):
        raise _invalido()
    r = r.replace('/', '\\')
    if r.startswith('\\\\'):                                    # UNC, \\?\ y \\.\ (dispositivos)
        raise _invalido()
    if not _RE_UNIDAD.match(r):                                 # solo absoluta con letra de unidad
        raise _invalido()
    if ':' in r[2:]:                                            # flujos alternos de NTFS (archivo.json:otro)
        raise _invalido()
    normal = os.path.normpath(r)
    if not _RE_UNIDAD.match(normal) or os.path.splitext(normal)[1].lower() != '.json':
        raise _invalido()
    if _tipo_unidad(normal[:3]) in (_DRIVE_REMOTE, _DRIVE_NO_ROOT_DIR):
        raise _invalido()
    return normal


def leer_json_usuario(ruta: str, max_bytes: int) -> Any:
    """Lee y parsea el JSON que eligió el usuario. Nunca registra la ruta completa ni el contenido."""
    p = validar_ruta(ruta)
    try:
        info = os.lstat(p)
    except FileNotFoundError:
        raise ErrorDominio('archivo_no_encontrado', MSG_NO_EXISTE, http=404) from None
    except OSError:
        raise _invalido() from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise _invalido()
    if info.st_size > max_bytes:
        raise _invalido(MSG_GRANDE, http=422)
    try:
        with open(p, 'rb') as f:
            datos = f.read(max_bytes + 1)
    except FileNotFoundError:
        raise ErrorDominio('archivo_no_encontrado', MSG_NO_EXISTE, http=404) from None
    except OSError as e:
        _log.info('No se pudo leer el archivo elegido (%s)', type(e).__name__)
        raise _invalido() from None
    if len(datos) > max_bytes:                                  # creció entre lstat y read
        raise _invalido(MSG_GRANDE, http=422)
    try:
        return json.loads(datos.decode('utf-8-sig'))
    except (UnicodeDecodeError, ValueError):
        raise _invalido(MSG_CONTENIDO, http=422) from None
