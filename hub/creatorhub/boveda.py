"""Bóveda de credenciales con DPAPI (03 §7.1, §2.6; BUILD_SPEC §6.2 `Boveda`, §6.3.1 paso 4).

`crear_boveda(rutas, modo)`:
- **real**: `<secretos>\\credenciales.dpapi` = sobre JSON `{"v":1, "generacion":N, "blob":"<base64>"}` con el blob de
  `CryptProtectData(json_utf8, 'Creator Hub', entropía b'CreatorHub/credenciales/v1', CRYPTPROTECT_UI_FORBIDDEN)`
  (usuario actual; `creatorhub.cripto.dpapi`).
- **demo**: en memoria, `origen='demo'`, app_key pública y valores FALSOS que nunca se escriben a disco (los que
  verifica el transporte falso del modo demo).
- **autoprueba**: DPAPI real en la carpeta temporal, VACÍA: escribe y vuelve a leer un sobre vacío (prueba DPAPI).

Reglas:
- `candado` (RLock) = **candado_auth**. `mutar(fn, cambia_credenciales)` sube `generacion` en CADA escritura y
  `epoca_credenciales` solo en canje, importación, cambio de clave, desconectar y borrar. Persiste ANTES de publicar
  en memoria: si no se pudo escribir, la mutación no ocurre.
- `guardar_si(gen0, cambios)`: persiste un refresh solo si nadie escribió mientras el refresh estaba en la red.
- Escritura: `credenciales.dpapi.nuevo` + flush + fsync → `os.replace`. Si `os.replace` da `PermissionError`
  (antivirus o indexador), 10 reintentos con 50 ms·2^i (tope 1 s); si aún falla, se CONSERVA `.nuevo` (gana al
  arrancar por mayor `generacion`) y se reintenta en la siguiente lectura o escritura (o en el tic que llame a
  `reintentar_pendiente()`).
- `candado_auth` es el mismo RLock que `candado` (nombre de 03 §2.6, para el cierre ordenado de hub-api).
- Al arrancar, si `.nuevo` descifra y tiene mayor `generacion`, gana. Un archivo **ilegible** (otro perfil de Windows,
  reinstalación, daño) se renombra a `credenciales.dpapi.ilegible-<epoch>`, NUNCA se sobrescribe, y la bóveda queda
  vacía (`ilegible_at`): auth_estado = 'sin_credenciales'.
- Contenido: app_key, app_secret, access_token, refresh_token, access_expira_at, refresh_expira_at, open_id,
  user_type, granted_scopes, seller_name, origen, epoca_credenciales, generacion, actualizado_at.
- Nunca se registra un valor: solo presencia («clave de la app: guardada»).
- Rev. 5 (15/11/2026): `ENTROPIA` y `CAMPOS_SECRETOS` son atributos de clase para que la bóveda de la Display API
  (`tiktok_dev/boveda.py`, archivo y entropía propios) herede EXACTAMENTE las mismas garantías de escritura y lectura.
"""
from __future__ import annotations

import base64
import copy
import json
import logging
import os
import threading
import time
from typing import Any, Callable, Mapping

from .interfaces import Boveda, ModoHub, Rutas

_log = logging.getLogger('creatorhub.boveda')

APP_KEY_PUBLICA = '6jq7150miuhvr'       # app de Partner Center (CONTEXTO): pública, viaja en el enlace de autorización
NOMBRE_ARCHIVO = 'credenciales.dpapi'
VERSION_SOBRE = 1
MAX_SOBRE_BYTES = 1024 * 1024
INTENTOS_REEMPLAZO = 10
CAMPOS_SECRETOS = ('app_secret', 'access_token', 'refresh_token')

# Valores FALSOS del modo demo: son los que firma y verifica el transporte falso (spec/verificacion/fixtures_api.py).
# No son credenciales de nadie y nunca se escriben a disco.
SECRETO_DEMO = 'secreto-de-prueba-no-real'
ACCESO_DEMO = 'demo-access'
RENOVACION_DEMO = 'demo-refresh'
OPEN_ID_DEMO = 'OPEN_ID_DEMO'
SCOPES_DEMO = ('creator.affiliate.info', 'creator.affiliate_collaboration.read', 'creator.showcase.read')


class _Ilegible(Exception):
    """El sobre existe pero no se puede leer o descifrar."""


def _dpapi() -> Any:
    from .cripto import dpapi          # carga crypt32 solo cuando hace falta
    return dpapi


class BovedaDpapi:
    """Implementa `Boveda`. Con `ruta=None` vive solo en memoria (modo demo)."""

    ENTROPIA: bytes | None = None                         # None = dpapi.ENTROPIA_CREDENCIALES
    CAMPOS_SECRETOS: tuple[str, ...] = CAMPOS_SECRETOS    # valores que el registro y los errores tapan

    @classmethod
    def _entropia(cls) -> bytes:
        return cls.ENTROPIA if cls.ENTROPIA is not None else _dpapi().ENTROPIA_CREDENCIALES

    def __init__(self, ruta: str | None, datos: Mapping[str, Any] | None = None, vacia: bool = False,
                 origen_demo: bool = False) -> None:
        self.ruta = ruta
        self.candado = threading.RLock()                  # candado_auth (orden: sync → auth → escritor)
        self.candado_auth = self.candado                  # mismo RLock con el nombre de 03 §2.6 (cierre ordenado)
        self.ilegible_at: int | None = None
        self.apartado: str | None = None
        self.reemplazo_pendiente = False
        self.origen_demo = origen_demo
        self._anclado = False
        self._dormir: Callable[[float], None] = time.sleep
        self._reemplazar: Callable[[str, str], None] = os.replace
        if datos is not None:
            base = copy.deepcopy(dict(datos))
        elif ruta is not None and not vacia:
            base = self._cargar()
        else:
            base = {}
        base.setdefault('generacion', 0)
        base.setdefault('epoca_credenciales', 0)
        self._datos: dict[str, Any] = base
        self.generacion: int = int(base['generacion'])

    # ================================================================ lectura del disco
    @classmethod
    def _leer_sobre(cls, ruta: str) -> dict[str, Any]:
        with open(ruta, 'rb') as f:
            crudo = f.read(MAX_SOBRE_BYTES + 1)
        if len(crudo) > MAX_SOBRE_BYTES:
            raise _Ilegible('demasiado grande')
        try:
            sobre = json.loads(crudo.decode('utf-8'))
            if (not isinstance(sobre, dict) or sobre.get('v') != VERSION_SOBRE
                    or not isinstance(sobre.get('generacion'), int) or not isinstance(sobre.get('blob'), str)):
                raise _Ilegible('sobre con forma desconocida')
            blob = base64.b64decode(sobre['blob'], validate=True)
            plano = _dpapi().desproteger(blob, cls._entropia())
            datos = json.loads(plano.decode('utf-8'))
        except _Ilegible:
            raise
        except (ValueError, UnicodeDecodeError, OSError) as e:      # ErrorDpapi es OSError
            raise _Ilegible(type(e).__name__) from None
        if not isinstance(datos, dict):
            raise _Ilegible('contenido no es un objeto')
        datos['generacion'] = int(sobre['generacion'])
        return datos

    def _intentar(self, ruta: str) -> dict[str, Any] | None | _Ilegible:
        try:
            return self._leer_sobre(ruta)
        except FileNotFoundError:
            return None
        except _Ilegible as e:
            return e
        except OSError as e:
            return _Ilegible(type(e).__name__)

    def _apartar(self, ruta: str) -> None:
        """Renombra un archivo ilegible a `.ilegible-<epoch>` (nunca se sobrescribe ni se borra)."""
        base = f'{ruta}.ilegible-{int(time.time())}'
        destino, n = base, 1
        while os.path.exists(destino):
            n += 1
            destino = f'{base}-{n}'
        try:
            os.rename(ruta, destino)
            self.apartado = destino
        except OSError as e:
            _log.error('No se pudo apartar el archivo de credenciales ilegible (%s)', type(e).__name__)
            raise
        self.ilegible_at = int(time.time())
        _log.warning('Credenciales ilegibles (otro usuario de Windows, reinstalación o archivo dañado): se apartaron '
                     'como %s y la conexión queda sin credenciales', os.path.basename(destino))

    def _cargar(self) -> dict[str, Any]:
        assert self.ruta is not None
        os.makedirs(os.path.dirname(self.ruta) or '.', exist_ok=True)
        nuevo = self.ruta + '.nuevo'
        principal = self._intentar(self.ruta)
        candidato = self._intentar(nuevo)
        if isinstance(candidato, dict) and (not isinstance(principal, dict)
                                            or candidato['generacion'] > principal['generacion']):
            if isinstance(principal, _Ilegible):
                self._apartar(self.ruta)
            try:
                self._reemplazo_con_reintentos(nuevo)
            except OSError:
                self.reemplazo_pendiente = True
            _log.info('Se recuperó la última escritura de credenciales (generación %d)', candidato['generacion'])
            return candidato
        if os.path.exists(nuevo):
            try:
                os.remove(nuevo)                           # escritura vieja o a medias: no aporta nada
            except OSError:
                pass
        if isinstance(principal, dict):
            return principal
        if isinstance(principal, _Ilegible):
            self._apartar(self.ruta)
        return {}

    # ================================================================ escritura
    def _reemplazo_con_reintentos(self, nuevo: str) -> None:
        assert self.ruta is not None
        for i in range(INTENTOS_REEMPLAZO):
            try:
                self._reemplazar(nuevo, self.ruta)
                return
            except PermissionError:
                if i == INTENTOS_REEMPLAZO - 1:
                    raise
                self._dormir(min(1.0, 0.05 * (2 ** i)))

    def _persistir(self, datos: Mapping[str, Any]) -> None:
        assert self.ruta is not None
        os.makedirs(os.path.dirname(self.ruta) or '.', exist_ok=True)
        plano = json.dumps(datos, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode('utf-8')
        blob = _dpapi().proteger(plano, self._entropia())
        sobre = json.dumps({'v': VERSION_SOBRE, 'generacion': int(datos['generacion']),
                            'blob': base64.b64encode(blob).decode('ascii')}, separators=(',', ':')).encode('ascii')
        nuevo = self.ruta + '.nuevo'
        try:
            with open(nuevo, 'wb') as f:
                f.write(sobre)
                f.flush()
                os.fsync(f.fileno())
        except BaseException:
            try:
                os.remove(nuevo)
            except OSError:
                pass
            raise
        try:
            self._reemplazo_con_reintentos(nuevo)
            self.reemplazo_pendiente = False
        except PermissionError:
            # Se conserva `.nuevo`: al arrancar gana por generación y se reintenta en la siguiente escritura.
            self.reemplazo_pendiente = True
            _log.warning('No se pudo reemplazar el archivo de credenciales (en uso); se reintentará')
        except BaseException:
            # Otra falla (disco lleno, …): la mutación NO ocurre y no debe resucitar al arrancar.
            try:
                os.remove(nuevo)
            except OSError:
                pass
            raise

    def _reintentar_pendiente(self) -> None:
        if not self.reemplazo_pendiente or self.ruta is None:
            return
        nuevo = self.ruta + '.nuevo'
        if not os.path.exists(nuevo):
            self.reemplazo_pendiente = False
            return
        try:
            self._reemplazar(nuevo, self.ruta)
            self.reemplazo_pendiente = False
            _log.info('Se completó el reemplazo pendiente del archivo de credenciales')
        except PermissionError:
            pass

    def reintentar_pendiente(self) -> bool:
        """«Se reintenta en el siguiente tic» (03 §7.1): un intento de `os.replace` del `.nuevo` conservado. También se
        intenta en cada `leer()` y en cada escritura. True si ya no queda nada pendiente."""
        with self.candado:
            self._reintentar_pendiente()
            return not self.reemplazo_pendiente

    # ================================================================ Protocol Boveda
    def leer(self) -> Mapping[str, Any]:
        with self.candado:
            if self.reemplazo_pendiente:                   # un solo intento, sin esperas (no frena la lectura)
                self._reintentar_pendiente()
            return copy.deepcopy(self._datos)

    def mutar(self, fn: Callable[[dict[str, Any]], None], cambia_credenciales: bool = False) -> None:
        with self.candado:
            self._reintentar_pendiente()
            gen, epoca = int(self._datos.get('generacion', 0)), int(self._datos.get('epoca_credenciales', 0))
            nuevo = copy.deepcopy(self._datos)
            fn(nuevo)
            nuevo['generacion'] = gen + 1
            nuevo['epoca_credenciales'] = epoca + (1 if cambia_credenciales else 0)
            nuevo['actualizado_at'] = int(time.time())
            if self.ruta is not None:
                self._persistir(nuevo)                     # persistir ANTES de publicar en memoria
            self._datos = nuevo
            self.generacion = nuevo['generacion']
            if cambia_credenciales:
                self.ilegible_at = None

    def guardar_si(self, gen0: int, cambios: Mapping[str, Any]) -> bool:
        with self.candado:
            if self._datos.get('generacion') != gen0 or not self._datos.get('refresh_token'):
                return False
            self.mutar(lambda d: d.update(copy.deepcopy(dict(cambios))))
            return True

    def secretos_vivos(self) -> tuple[str, ...]:
        with self.candado:
            return tuple(v for k in self.CAMPOS_SECRETOS if isinstance(v := self._datos.get(k), str) and len(v) >= 8)

    def tiene_app_secret(self) -> bool:
        with self.candado:
            return bool(self._datos.get('app_secret'))

    def tiene_tokens(self) -> bool:
        with self.candado:
            return bool(self._datos.get('access_token') and self._datos.get('refresh_token'))

    # ================================================================ extras
    @property
    def origen(self) -> str | None:
        with self.candado:
            o = self._datos.get('origen')
            return o if isinstance(o, str) else None

    def resumen(self) -> dict[str, bool]:
        """Solo presencia (para registros): nunca valores."""
        with self.candado:
            return {'app_secret': bool(self._datos.get('app_secret')),
                    'tokens': bool(self._datos.get('access_token') and self._datos.get('refresh_token'))}

    def eliminar(self) -> None:
        """«Borrar todo» (01 §4.14 G): borra `credenciales.dpapi` (y `.nuevo`) y vacía la bóveda; sube generación y
        época. Lo usa el coordinador (hub-api) con alcance 'todo'."""
        with self.candado:
            gen, epoca = int(self._datos.get('generacion', 0)), int(self._datos.get('epoca_credenciales', 0))
            if self.ruta is not None:
                for r in (self.ruta, self.ruta + '.nuevo'):
                    try:
                        os.remove(r)
                    except FileNotFoundError:
                        pass
            self._datos = {'generacion': gen + 1, 'epoca_credenciales': epoca + 1, 'actualizado_at': int(time.time())}
            self.generacion = gen + 1
            self.reemplazo_pendiente = False

    def anclar_demo(self, ahora: int) -> None:
        """Modo demo: fija las expiraciones falsas relativas al reloj del hub (que puede arrancar en `--ahora`)."""
        if not self.origen_demo:
            return
        with self.candado:
            if self._anclado:
                return
            self._anclado = True
            self._datos['access_expira_at'] = int(ahora) + 3 * 86400
            self._datos['refresh_expira_at'] = int(ahora) + 200 * 86400


def datos_demo(ahora: int | None = None) -> dict[str, Any]:
    t = int(time.time() if ahora is None else ahora)
    return {'app_key': APP_KEY_PUBLICA, 'app_secret': SECRETO_DEMO, 'access_token': ACCESO_DEMO,
            'refresh_token': RENOVACION_DEMO, 'access_expira_at': t + 3 * 86400, 'refresh_expira_at': t + 200 * 86400,
            'open_id': OPEN_ID_DEMO, 'user_type': 1, 'granted_scopes': list(SCOPES_DEMO), 'seller_name': '',
            'origen': 'demo', 'generacion': 1, 'epoca_credenciales': 1}


def crear_boveda(rutas: Rutas, modo: ModoHub) -> Boveda:
    """real → DPAPI en <secretos>\\credenciales.dpapi · demo → memoria con valores falsos · autoprueba → DPAPI real en
    la carpeta temporal, vacía (escribe y relee un sobre vacío para probar DPAPI)."""
    if modo == 'demo':
        return BovedaDpapi(None, datos=datos_demo(), origen_demo=True)
    ruta = os.path.join(rutas.secretos, NOMBRE_ARCHIVO)
    if modo == 'real':
        return BovedaDpapi(ruta)
    if modo == 'autoprueba':
        b = BovedaDpapi(ruta, vacia=True)
        b.mutar(lambda d: None)
        releida = BovedaDpapi._leer_sobre(ruta)
        if releida.get('generacion') != b.generacion:
            raise OSError('DPAPI no devolvió lo que se cifró (autoprueba)')
        return b
    raise ValueError(f'modo desconocido: {modo!r}')
