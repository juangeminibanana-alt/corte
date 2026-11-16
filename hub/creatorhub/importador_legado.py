"""Importación única del `config.json` del panel anterior (03 §8; BUILD_SPEC C42, C46).

- Ruta conocida: `%USERPROFILE%\\OneDrive\\Documents\\PROJECTS\\API de Affiliate Creator\\config.json` y variantes
  (`%OneDrive%`, `%OneDriveConsumer%`, «Documentos», sin OneDrive). O `req['ruta']` del selector nativo (C46), que se
  valida ANTES de tocar el disco: absoluta con letra de unidad, sin UNC (`\\\\`, `\\\\?\\`, `//`), sin flujos
  alternos, extensión `.json`, unidad local (no de red), sin enlaces simbólicos ni uniones en el camino, archivo
  regular y ≤ 1 MB. Errores: `archivo_no_encontrado` (404) y `archivo_invalido`.
- Contenido: objeto JSON UTF-8 (con o sin BOM). Campos conocidos: app_key, app_secret, access_token, refresh_token,
  access_token_expire_in (epoch), refresh_token_expire_in (epoch), open_id, seller_name, user_type, granted_scopes;
  `last_state` se ignora. Se valida SIN imprimir: app_secret 16–128 alfanuméricos, tokens 20–2048 sin espacios,
  user_type = 1 si viene, expiraciones enteras. Si falla → 422 `archivo_invalido` con el CAMPO, nunca su valor.
- Cuenta: si el open_id del archivo difiere del guardado → 409 `cuenta_distinta`.
- Para no pisar algo mejor: app_secret solo si la bóveda no tiene; tokens solo si la bóveda no tiene o el archivo
  vence después. Si no hay nada que importar NO se toca nada (idempotente).
- Guardar: `coordinador.mutacion_segura(boveda.mutar(…, cambia_credenciales=True), 'nada')`, auth_estado
  (`origen='importado'`), `meta.legado_importado_at` y `meta.legado_sha256` (de los bytes del archivo).
- Nunca modifica ni borra el archivo original (borrarlo es `auth.borrar_legado`, a la Papelera).
- Los registros solo dicen qué se importó (sí/no), nunca un valor.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import stat
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .errores import ErrorDominio
from .tiktok import conexion as cx

_log = logging.getLogger('creatorhub.importador_legado')

PARTES_RUTA = ('PROJECTS', 'API de Affiliate Creator', 'config.json')
MAX_BYTES = 1024 * 1024                         # C46: ≤ 1 MB para credenciales
_RE_SECRETO = re.compile(r'^[A-Za-z0-9]{16,128}$')
_RE_TOKEN = re.compile(r'^\S{20,2048}$')
_RE_APP_KEY = re.compile(r'^[A-Za-z0-9_\-]{4,64}$')
_RE_RUTA = re.compile(r'^[A-Za-z]:\\')
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_REPARSE_PROHIBIDOS = {0xA000000C, 0xA0000003}  # IO_REPARSE_TAG_SYMLINK, IO_REPARSE_TAG_MOUNT_POINT (unión)
_DRIVE_NO_ROOT_DIR, _DRIVE_REMOTE = 1, 4

MSG_RUTA_INVALIDA = 'Elige un archivo .json de esta PC (no de una carpeta de red) de 1 MB o menos.'
MSG_NO_ENCONTRADO = 'No encontramos el archivo del panel anterior. Elige el archivo con «Importar desde archivo…».'
MSG_CONTENIDO = 'El archivo no parece el config.json del panel anterior: revisa que sea el correcto.'
MSG_CAMPO = 'El archivo anterior tiene un dato que no reconocemos. Revisa que sea el config.json del panel anterior.'
MSG_CUENTA = ('Este archivo es de otra cuenta de TikTok. Para usarla, desconecta la cuenta actual y borra sus datos '
              'desde Conexión y ajustes.')
AVISO_ONEDRIVE = ('Tus llaves ya están guardadas y cifradas en esta PC. El archivo config.json anterior sigue en '
                  'OneDrive sin cifrar: te recomendamos borrarlo.')
AVISO_LOCAL = ('Tus llaves ya están guardadas y cifradas en esta PC. El archivo config.json anterior sigue en tu PC '
               'sin cifrar: te recomendamos borrarlo.')


# ------------------------------------------------------------------ rutas conocidas
def rutas_conocidas(entorno: Mapping[str, str] | None = None) -> list[str]:
    """Candidatos en orden de preferencia; el primero es el de 03 §8. No toca el disco."""
    env = os.environ if entorno is None else entorno
    perfil = env.get('USERPROFILE') or os.path.expanduser('~')
    bases = [os.path.join(perfil, 'OneDrive'), env.get('OneDrive'), env.get('OneDriveConsumer')]
    candidatos: list[str] = []
    for base in bases:
        if base:
            for docs in ('Documents', 'Documentos'):
                candidatos.append(os.path.join(base, docs, *PARTES_RUTA))
    for docs in ('Documents', 'Documentos'):
        candidatos.append(os.path.join(perfil, docs, *PARTES_RUTA))
    vistos: set[str] = set()
    unicos = []
    for c in candidatos:
        k = os.path.normcase(os.path.normpath(c))
        if k not in vistos:
            vistos.add(k)
            unicos.append(os.path.normpath(c))
    return unicos


def ruta_por_omision(candidatos: list[str]) -> str:
    """El primer candidato que existe como archivo; si ninguno, el de 03 §8."""
    for c in candidatos:
        if os.path.isfile(c):
            return c
    return candidatos[0]


# ------------------------------------------------------------------ validación de la ruta (C46)
def _invalida(motivo: str) -> ErrorDominio:
    return ErrorDominio('archivo_invalido', MSG_RUTA_INVALIDA, http=400, detalle={'motivo': motivo})


def _tipo_unidad(raiz: str) -> int:
    try:
        import ctypes
        f = ctypes.WinDLL('kernel32', use_last_error=True).GetDriveTypeW
        f.argtypes = [ctypes.c_wchar_p]
        f.restype = ctypes.c_uint
        return int(f(raiz))
    except (OSError, AttributeError):
        return 0


def validar_sintaxis(ruta: Any) -> str:
    """Valida sin tocar el disco. Devuelve la ruta normalizada (con '\\')."""
    if not isinstance(ruta, str) or not ruta or len(ruta) > 1024:
        raise _invalida('ruta')
    if any(ord(ch) < 32 for ch in ruta):
        raise _invalida('ruta')
    r = ruta.replace('/', '\\')
    if r.startswith('\\\\') or ruta.startswith('//'):
        raise _invalida('unc')
    if not _RE_RUTA.match(r):
        raise _invalida('no_absoluta')
    if ':' in r[2:]:
        raise _invalida('flujo_alterno')
    if not r.lower().endswith('.json'):
        raise _invalida('extension')
    norm = os.path.normpath(r)
    if not _RE_RUTA.match(norm) or norm.startswith('\\\\'):
        raise _invalida('no_absoluta')
    return norm


def validar_ruta(ruta: Any, tipo_unidad: Callable[[str], int] = _tipo_unidad) -> str:
    """C46 completo: sintaxis, unidad local, camino sin enlaces, archivo regular, ≤ 1 MB."""
    norm = validar_sintaxis(ruta)
    if tipo_unidad(norm[:3]) in (_DRIVE_REMOTE, _DRIVE_NO_ROOT_DIR):
        raise _invalida('unidad_de_red')
    # Cada carpeta del camino se revisa con lstat ANTES de entrar: un enlace o unión podría llevar a una carpeta de red.
    partes = norm[3:].split('\\')
    actual = norm[:3]
    for parte in partes[:-1]:
        actual = os.path.join(actual, parte)
        try:
            st = os.lstat(actual)
        except FileNotFoundError:
            raise ErrorDominio('archivo_no_encontrado', MSG_NO_ENCONTRADO, http=404) from None
        except OSError:
            raise _invalida('ruta') from None
        if getattr(st, 'st_reparse_tag', 0) in _REPARSE_PROHIBIDOS or stat.S_ISLNK(st.st_mode):
            raise _invalida('enlace')
        if not stat.S_ISDIR(st.st_mode):
            raise ErrorDominio('archivo_no_encontrado', MSG_NO_ENCONTRADO, http=404)
    try:
        st = os.lstat(norm)
    except FileNotFoundError:
        raise ErrorDominio('archivo_no_encontrado', MSG_NO_ENCONTRADO, http=404) from None
    except OSError:
        raise _invalida('ruta') from None
    if getattr(st, 'st_reparse_tag', 0) in _REPARSE_PROHIBIDOS or stat.S_ISLNK(st.st_mode):
        raise _invalida('enlace')
    if not stat.S_ISREG(st.st_mode):
        raise _invalida('no_es_archivo')
    if st.st_size > MAX_BYTES:
        raise _invalida('tamano')
    return norm


def leer_json(ruta_validada: str) -> tuple[bytes, dict[str, Any]]:
    """Bytes (≤ 1 MB) y objeto JSON. UTF-8 con o sin BOM."""
    try:
        with open(ruta_validada, 'rb') as f:
            datos = f.read(MAX_BYTES + 1)
    except FileNotFoundError:
        raise ErrorDominio('archivo_no_encontrado', MSG_NO_ENCONTRADO, http=404) from None
    except OSError:
        raise _invalida('lectura') from None
    if len(datos) > MAX_BYTES:
        raise _invalida('tamano')
    try:
        obj = json.loads(datos.decode('utf-8-sig'))
    except (UnicodeDecodeError, ValueError):
        raise ErrorDominio('archivo_invalido', MSG_CONTENIDO, http=422, detalle={'campo': '(archivo)'}) from None
    if not isinstance(obj, dict):
        raise ErrorDominio('archivo_invalido', MSG_CONTENIDO, http=422, detalle={'campo': '(archivo)'})
    return datos, obj


# ------------------------------------------------------------------ campos
def _campo_malo(nombre: str) -> ErrorDominio:
    return ErrorDominio('archivo_invalido', MSG_CAMPO, http=422, detalle={'campo': nombre})


def _vacio(v: Any) -> bool:
    return v is None or v == '' or v == [] or (isinstance(v, int) and not isinstance(v, bool) and v == 0)


def validar_campos(obj: Mapping[str, Any]) -> dict[str, Any]:
    """Campos normalizados con nombres de la bóveda. Los vacíos ("" / 0 / None, como trae el panel anterior sin
    conectar) cuentan como ausentes. Nunca incluye un valor en el error."""
    out: dict[str, Any] = {}
    v = obj.get('app_key')
    if not _vacio(v):
        if not isinstance(v, str) or not _RE_APP_KEY.match(v):
            raise _campo_malo('app_key')
        out['app_key'] = v
    v = obj.get('app_secret')
    if not _vacio(v):
        if not isinstance(v, str) or not _RE_SECRETO.match(v):
            raise _campo_malo('app_secret')
        out['app_secret'] = v
    for clave in ('access_token', 'refresh_token'):
        v = obj.get(clave)
        if not _vacio(v):
            if not isinstance(v, str) or not _RE_TOKEN.match(v):
                raise _campo_malo(clave)
            out[clave] = v
    for origen, destino in (('access_token_expire_in', 'access_expira_at'),
                            ('refresh_token_expire_in', 'refresh_expira_at')):
        v = obj.get(origen)
        if not _vacio(v):
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise _campo_malo(origen)
            out[destino] = v
    v = obj.get('user_type')
    if v is not None and v != '':
        if v != 1 or isinstance(v, bool):
            raise _campo_malo('user_type')
        out['user_type'] = 1
    for clave in ('open_id', 'seller_name'):
        v = obj.get(clave)
        if not _vacio(v):
            if not isinstance(v, str) or len(v) > 256:
                raise _campo_malo(clave)
            out[clave] = v
    v = obj.get('granted_scopes')
    if not _vacio(v):
        if not isinstance(v, list) or not all(isinstance(s, str) and 0 < len(s) <= 128 for s in v):
            raise _campo_malo('granted_scopes')
        out['granted_scopes'] = list(v)
    tiene_a, tiene_r = 'access_token' in out, 'refresh_token' in out
    if tiene_a != tiene_r:
        raise _campo_malo('refresh_token' if tiene_a else 'access_token')
    if tiene_a and ('access_expira_at' not in out or 'refresh_expira_at' not in out):
        raise _campo_malo('access_token_expire_in' if 'access_expira_at' not in out else 'refresh_token_expire_in')
    if 'app_secret' not in out and not tiene_a:
        raise _campo_malo('app_secret')
    return out


# ------------------------------------------------------------------ Papelera (auth.borrar_legado, C25)
FO_DELETE = 0x0003
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400


def hay_papelera(ruta: str) -> bool:
    """¿La unidad de `ruta` tiene Papelera? (SHQueryRecycleBinW sobre la raíz)."""
    import ctypes
    from ctypes import wintypes

    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('i64Size', ctypes.c_longlong), ('i64NumItems', ctypes.c_longlong)]

    shell32 = ctypes.WinDLL('shell32', use_last_error=True)
    shell32.SHQueryRecycleBinW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(SHQUERYRBINFO)]
    shell32.SHQueryRecycleBinW.restype = ctypes.c_long
    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
    return shell32.SHQueryRecycleBinW(os.path.splitdrive(os.path.abspath(ruta))[0] + '\\', ctypes.byref(info)) == 0


def mover_a_papelera(ruta: str) -> None:
    """Envía `ruta` a la Papelera con SHFileOperationW (FO_DELETE + FOF_ALLOWUNDO, sin diálogos). Si la unidad no tiene
    Papelera NO borra (lanza OSError): el archivo nunca se elimina sin poder recuperarlo."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [('hwnd', wintypes.HWND), ('wFunc', wintypes.UINT), ('pFrom', wintypes.LPCWSTR),
                    ('pTo', wintypes.LPCWSTR), ('fFlags', ctypes.c_ushort), ('fAnyOperationsAborted', wintypes.BOOL),
                    ('hNameMappings', ctypes.c_void_p), ('lpszProgressTitle', wintypes.LPCWSTR)]

    completa = os.path.abspath(ruta)
    if not hay_papelera(completa):
        raise OSError('La unidad no tiene Papelera')
    shell32 = ctypes.WinDLL('shell32', use_last_error=True)
    shell32.SHFileOperationW.argtypes = [ctypes.POINTER(SHFILEOPSTRUCTW)]
    shell32.SHFileOperationW.restype = ctypes.c_int
    origen = ctypes.create_unicode_buffer(completa + '\0')      # lista terminada en doble NUL
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = ctypes.cast(origen, wintypes.LPCWSTR)
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    r = shell32.SHFileOperationW(ctypes.byref(op))
    if r != 0 or op.fAnyOperationsAborted:
        raise OSError(f'SHFileOperationW devolvió {r}')


# ------------------------------------------------------------------ importación
@dataclass
class ResultadoImportacion:
    importado: dict[str, Any] = field(default_factory=lambda: {'app_secret': False, 'access_token': False,
                                                                'refresh_token': False, 'scopes': 0})
    cambio: bool = False
    ruta: str = ''
    tokens_en_boveda: bool = False

    @property
    def aviso_archivo_original(self) -> str:
        return AVISO_ONEDRIVE if 'onedrive' in self.ruta.lower() else AVISO_LOCAL


def planificar(actual: Mapping[str, Any], campos: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(cambios para la bóveda, banderas `importado`) con las reglas de 03 §8.4."""
    cambios: dict[str, Any] = {}
    importado: dict[str, Any] = {'app_secret': False, 'access_token': False, 'refresh_token': False, 'scopes': 0}
    if 'app_secret' in campos and not actual.get('app_secret'):
        cambios['app_secret'] = campos['app_secret']
        importado['app_secret'] = True
    if 'app_key' in campos and not actual.get('app_key'):
        cambios['app_key'] = campos['app_key']
    if 'access_token' in campos:
        sin_tokens = not (actual.get('access_token') and actual.get('refresh_token'))
        guardado = actual.get('access_expira_at')
        mas_nuevo = not isinstance(guardado, int) or campos['access_expira_at'] > guardado
        if sin_tokens or mas_nuevo:
            for k in ('access_token', 'refresh_token', 'access_expira_at', 'refresh_expira_at'):
                cambios[k] = campos[k]
            for k in ('open_id', 'seller_name', 'user_type'):
                if k in campos:
                    cambios[k] = campos[k]
            cambios['granted_scopes'] = list(campos.get('granted_scopes') or [])
            importado.update(access_token=True, refresh_token=True, scopes=len(cambios['granted_scopes']))
    if cambios:
        cambios['origen'] = 'importado'
    return cambios, importado


def importar(ruta: str | None, candidatos: list[str], boveda: Any, almacen: Any, coordinador: Any, ahora: int,
             tipo_unidad: Callable[[str], int] = _tipo_unidad) -> ResultadoImportacion:
    """Lee, valida e importa. `ruta=None` → la conocida (`candidatos`). Lanza ErrorDominio."""
    elegida = ruta if ruta else ruta_por_omision(candidatos)
    validada = validar_ruta(elegida, tipo_unidad)
    crudo, obj = leer_json(validada)
    campos = validar_campos(obj)
    huella = hashlib.sha256(crudo).hexdigest()
    del crudo, obj
    actual = boveda.leer()
    with almacen.lector() as c:
        fila = cx.leer_fila(c)
    guardado = actual.get('open_id') or (fila or {}).get('open_id')
    if campos.get('open_id') and guardado and campos['open_id'] != guardado and 'access_token' in campos:
        raise ErrorDominio('cuenta_distinta', MSG_CUENTA, http=409)
    cambios, importado = planificar(actual, campos)
    resultado = ResultadoImportacion(importado=importado, cambio=bool(cambios), ruta=validada)
    if not cambios:
        resultado.tokens_en_boveda = boveda.tiene_tokens()
        _log.info('Importación del archivo anterior: no había nada nuevo que importar')
        return resultado
    coordinador.mutacion_segura(lambda: boveda.mutar(lambda d: d.update(cambios), cambia_credenciales=True), 'nada')
    datos = boveda.leer()
    with almacen.escritor() as c:
        previo = cx.leer_fila(c)
        campos_fila = cx.espejo(datos)
        if importado['access_token']:
            campos_fila.update(estado=cx.estado_base(datos), refresh_rechazos_seguidos=0, refresh_aviso=None,
                               ultimo_error_codigo=None, ultimo_error_mensaje=None)
        else:
            estado = cx.estado_base(datos)
            if estado == 'conectada' and (previo or {}).get('estado') in ('reautorizar', 'cuenta_sin_region'):
                estado = previo['estado']
            campos_fila['estado'] = estado
        cx.actualizar_fila(c, ahora, datos.get('app_key'), **campos_fila)
        cx.escribir_meta(c, 'legado_importado_at', str(int(ahora)))
        cx.escribir_meta(c, 'legado_sha256', huella)
    resultado.tokens_en_boveda = boveda.tiene_tokens()
    _log.info('Importación del archivo anterior: clave de la app %s; conexión %s',
              'importada' if importado['app_secret'] else 'sin cambio',
              'importada' if importado['access_token'] else 'sin cambio')
    return resultado
