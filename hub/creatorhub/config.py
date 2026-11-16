"""Configuración del hub (BUILD_SPEC §6.1, §6.4, §6.5; 03 §1, §2.3, §7.3; 04 §1, §A.10).

- `VERSION`: de `importlib.resources.files('creatorhub') / 'version.json'` (exe: build-empaquetado lo agrega como dato)
  o, en desarrollo, de `<proyecto>/version.json`.
- `rutas_para(modo, raiz)`: arma y CREA las carpetas de datos.
- `abrir_config(rutas)`: `<raiz>/config.json` con escritura atómica (.nuevo + fsync + os.replace con reintentos).
- Constantes: puertos (C8), límites del servidor de interfaz (03 §7.3), hosts permitidos (§6.4), lista blanca del CDN
  (03 §2.3) y `AJUSTES_PC_OMISION` (C23/C36).
"""
from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
import time
from importlib import resources
from types import MappingProxyType
from typing import Any, Mapping

from .comun import escribir_atomico
from .interfaces import ArchivoConfig, ModoHub, Rutas

_log = logging.getLogger('creatorhub.config')

# ------------------------------------------------------------------ versión
_PROYECTO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))


def _leer_version() -> dict[str, Any]:
    try:
        recurso = resources.files('creatorhub') / 'version.json'
        if recurso.is_file():
            return json.loads(recurso.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, TypeError):
        _log.warning('version.json empaquetado ilegible; se usa el del proyecto')
    ruta = os.path.join(_PROYECTO, 'version.json')
    try:
        with open(ruta, encoding='utf-8-sig') as f:
            return json.load(f)
    except (OSError, ValueError):
        _log.error('No se encontró version.json (ni empaquetado ni en %s)', _PROYECTO)
        return {'version': '0.0.0', 'android_version_code': 0}


_VERSION_JSON = _leer_version()
VERSION: str = str(_VERSION_JSON.get('version', '0.0.0'))
ANDROID_VERSION_CODE: int = int(_VERSION_JSON.get('android_version_code', 0))

# ------------------------------------------------------------------ nombres (BUILD §1)
NOMBRE_VISIBLE = 'Corte'
NOMBRE_TECNICO = 'CreatorHub'
APP_LAN = 'creator-hub'
PROTOCOLO_LAN = 1

# ------------------------------------------------------------------ puertos (C8; 04 §1)
HOST_UI = '127.0.0.1'
PUERTO_UI = 39229
PUERTOS_UI_RESPALDO: tuple[int, ...] = tuple(range(39228, 39219, -1))      # 39228…39220
PUERTO_LAN = 39230
PUERTOS_LAN_RESPALDO: tuple[int, ...] = tuple(range(39232, 39240))         # 39232–39239
PUERTO_UDP = 39231
ORIGEN_DEV = 'http://localhost:5173'                                       # solo con --dev (C31), nunca congelado

# ------------------------------------------------------------------ límites del servidor de interfaz (03 §7.3, §6.4)
MAX_CUERPO_BYTES = 256 * 1024
MAX_CABECERAS_BYTES = 8 * 1024
TIMEOUT_LECTURA_S = 15
TASA_API_POR_S = 50          # por sesión, /api/* -> 429
TASA_ESTATICOS_POR_S = 400   # cubeta aparte para /img/* y estáticos
ESPERA_CAMBIOS_MAX_S = 25    # /api/cambios?espera_s≤25
VIGENCIA_TOKEN_BOOT_S = 60   # /boot?t=<token de un uso>

# ------------------------------------------------------------------ hosts permitidos para abrir enlaces (§6.4, 03 §7.7)
HOSTS_PERMITIDOS: frozenset[str] = frozenset({
    'shop.tiktok.com', 'www.tiktok.com', 'affiliate.tiktok.com', 'seller-mx.tiktok.com', 'partner.tiktokshop.com',
    'corte-e-book-21589.web.app'})
HOST_AVISO_WEBVIEW2 = 'go.microsoft.com'                                   # solo el aviso de WebView2, desde el shell
HOSTS_PERMITIDOS_SHELL: frozenset[str] = HOSTS_PERMITIDOS | {HOST_AVISO_WEBVIEW2}

# ------------------------------------------------------------------ imágenes (03 §2.3, C11)
SUFIJOS_CDN: tuple[str, ...] = ('.ibyteimg.com', '.byteimg.com', '.tiktokcdn.com', '.tiktokcdn-us.com')
IMAGEN_MAX_BYTES = 10 * 1024 * 1024
IMAGEN_MAX_REDIRECCIONES = 3
IMAGEN_MAX_PIXELES = 40_000_000
IMAGENES_MAX_MB_PC = 400


def host_cdn_permitido(host: str | None) -> bool:
    """True si `host` termina en uno de los sufijos de la lista blanca del CDN (03 §2.3)."""
    h = (host or '').strip().lower().rstrip('.')
    return bool(h) and any(h.endswith(s) for s in SUFIJOS_CDN)


# ------------------------------------------------------------------ ajustes de la PC (C23, C36)
AJUSTES_PC_OMISION: Mapping[str, Any] = MappingProxyType({
    'sync_auto': True, 'sync_intervalo_min': 30, 'segundo_plano': None, 'iniciar_con_windows': False,
    'densidad': 'comoda'})
INTERVALOS_SYNC_MIN: tuple[int, ...] = (15, 30, 60)


def ajustes_pc_guardados(cfg: ArchivoConfig) -> dict[str, Any]:
    """AJUSTES_PC_OMISION mezclado con lo guardado en config.json['ajustes_pc'] (sin iniciar_con_windows_bloqueado,
    que lo calcula el shell)."""
    guardado = cfg.leer('ajustes_pc', {}) or {}
    return {k: guardado.get(k, v) for k, v in AJUSTES_PC_OMISION.items()}


# ------------------------------------------------------------------ rutas (03 §1, 04 §A.10, BUILD §6.5)
def _local_appdata() -> str:
    return os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Local')


def rutas_para(modo: ModoHub, raiz: str | None = None) -> Rutas:
    """Arma las rutas del modo y crea sus carpetas. real -> %LOCALAPPDATA%\\CreatorHub · demo -> …\\CreatorHub\\demo ·
    autoprueba -> %TEMP%\\CreatorHub-autoprueba · `raiz` explícita (OpcionesHub.raiz_datos / --datos) gana siempre."""
    if modo not in ('real', 'demo', 'autoprueba'):
        raise ValueError(f'modo desconocido: {modo!r}')
    if raiz:
        base = os.path.abspath(raiz)
    elif modo == 'real':
        base = os.path.join(_local_appdata(), NOMBRE_TECNICO)
    elif modo == 'demo':
        base = os.path.join(_local_appdata(), NOMBRE_TECNICO, 'demo')
    else:
        base = os.path.join(tempfile.gettempdir(), NOMBRE_TECNICO + '-autoprueba')
    r = Rutas(raiz=base,
              config_json=os.path.join(base, 'config.json'),
              db=os.path.join(base, 'datos', 'hub.sqlite'),
              secretos=os.path.join(base, 'secretos'),
              tls=os.path.join(base, 'tls'),
              cache_img=os.path.join(base, 'cache', 'img'),
              logs=os.path.join(base, 'logs'),
              webview=os.path.join(base, 'webview'))
    for carpeta in (r.raiz, os.path.dirname(r.db), r.secretos, r.tls, r.cache_img, r.logs, r.webview):
        os.makedirs(carpeta, exist_ok=True)
    return r


# ------------------------------------------------------------------ config.json
def _mezclar(base: dict[str, Any], cambios: Mapping[str, Any]) -> dict[str, Any]:
    """Mezcla profunda: los dicts se combinan clave por clave; cualquier otro valor (incluido None) reemplaza."""
    out = dict(base)
    for k, v in cambios.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), dict):
            out[k] = _mezclar(out[k], v)
        else:
            out[k] = copy.deepcopy(dict(v) if isinstance(v, Mapping) else v)
    return out


class _ArchivoConfig:
    """Implementa ArchivoConfig. Claves de primer nivel: 'ajustes_pc' | 'ventana' | 'lan' | 'imagenes'. Nunca secretos."""

    def __init__(self, ruta: str) -> None:
        self.ruta = ruta
        self._candado = threading.Lock()
        self._datos = self._cargar()

    def _cargar(self) -> dict[str, Any]:
        try:
            with open(self.ruta, encoding='utf-8') as f:
                datos = json.load(f)
            if isinstance(datos, dict):
                return datos
            raise ValueError('config.json no es un objeto')
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            apartado = f'{self.ruta}.ilegible-{int(time.time())}'
            try:
                os.replace(self.ruta, apartado)
            except OSError:
                apartado = '(no se pudo apartar)'
            _log.warning('config.json ilegible: se apartó como %s y se usan los valores por omisión',
                         os.path.basename(apartado))
            return {}

    def leer(self, clave: str, omision: Any = None) -> Any:
        with self._candado:
            if clave not in self._datos:
                return omision
            return copy.deepcopy(self._datos[clave])

    def escribir(self, cambios: Mapping[str, Any]) -> None:
        with self._candado:
            nuevo = _mezclar(self._datos, cambios)
            texto = json.dumps(nuevo, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
            os.makedirs(os.path.dirname(self.ruta) or '.', exist_ok=True)
            escribir_atomico(self.ruta, texto.encode('utf-8'))
            self._datos = nuevo


def abrir_config(rutas: Rutas) -> ArchivoConfig:
    """`<raiz>/config.json`. Si está dañado se aparta (`.ilegible-<epoch>`) y se empieza con los valores por omisión."""
    return _ArchivoConfig(rutas.config_json)
