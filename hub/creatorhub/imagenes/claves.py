"""Claves, rutas y validaciones de la caché de imágenes (03 §2.3 y §6.5; BUILD_SPEC §6.3.3). Solo stdlib, sin PIL.

- Claves `p:<product_id>` y `a:cuenta`. `ref_id` se valida (`^[0-9]{1,25}$`, o `cuenta` en `a`) ANTES de armar rutas.
  Rev. 4 (15/11, ficha completa de producto): `g:<product_id>-<n>` = foto n (0–11) de la galería de la vitrina
  (showcases/products main_images[]) y `m:<product_id>` = foto de un producto parecido del marketplace. Las dos son
  DIFERIDAS: se registran al sincronizar y solo se descargan cuando alguien las pide (`/img/g/<id>-<n>`, `/img/m/<id>`).
  Rev. 5 (15/11): `v:<video_id>` = portada del video que da la Display API (cover_image_url, firmada y válida ~6 h). NO
  es diferida: se descarga y se cachea en cuanto la sync la registra (antes de que la URL caduque); `/img/v/<video_id>`.
- URL de origen: solo `https`, sin usuario ni contraseña, puerto 443 y host de la lista blanca del CDN
  (`config.SUFIJOS_CDN`). Solo ASCII; nada de barras invertidas, espacios ni caracteres de control.
- `url_huella = sha1(host + path)`: la query (firma, `x-expires`) es volátil y no cuenta como cambio de imagen.
- Rutas en disco, relativas a `cache\\img`: `<tipo>\\<2 primeros caracteres>\\<ref_id>_<version>_<variante>.<ext>`
  (`og` con la extensión del formato detectado; `xs`/`sm`/`md` siempre `.webp`). La versión va en el nombre para que
  una versión nueva nunca pise un archivo que el servidor está enviando (en Windows, `os.replace` sobre un archivo
  abierto falla).
- `ruta_segura(raiz, ruta_rel)`: la ruta real (`realpath`) debe quedar DENTRO de la raíz de la caché; si no, None.
"""
from __future__ import annotations

import hashlib
import os
import re
import urllib.parse
from typing import NamedTuple

from .. import config

TIPOS: tuple[str, ...] = ('p', 'a', 'g', 'm', 'v')  # rev. 5: 'v' = portada de la Display API (reservada hasta la rev. 4)
TIPOS_DIFERIDOS: tuple[str, ...] = ('g', 'm')       # rev. 4: se descargan solo cuando alguien las pide
MAX_GALERIA = 12                                    # fotos de la galería de vitrina que se guardan por producto
REF_CUENTA = 'cuenta'
_RE_REF = re.compile(r'[0-9]{1,25}')                # dígitos ASCII (\d de Python aceptaría dígitos Unicode)
_RE_GALERIA = re.compile(r'[0-9]{1,25}-(?:[0-9]|1[01])')   # '<product_id>-<n>' con n en 0..11 (MAX_GALERIA)
_RE_VERSION = re.compile(r'[0-9a-f]{8}')
_RE_OG = re.compile(r'^(?P<base>.+)_og\.(?P<ext>jpg|png|webp|gif)$')
_RE_ARCHIVO = re.compile(r'^(?:[0-9]{1,25}(?:-[0-9]{1,2})?|cuenta)_[0-9a-f]{8}_(?:og|xs|sm|md)\.(?:jpg|png|webp|gif)$')
_PROHIBIDOS_URL = frozenset('\\ \t\r\n\x0b\x0c"<>`{}|^')
MAX_LARGO_URL = 4096

# Variantes por ancho (03 §2.3, 02 §8.2): nombre -> (ancho en px, calidad WebP).
VARIANTES: dict[str, tuple[int, int]] = {'xs': (96, 78), 'sm': (240, 80), 'md': (720, 82)}
# Lista blanca de formatos detectados -> extensión (nunca de la cabecera). MPO = JPEG con varias imágenes (fotos de
# celular); Pillow lo abre con su decodificador JPEG y el archivo es un JPEG válido para el navegador.
EXTENSIONES: dict[str, str] = {'JPEG': 'jpg', 'MPO': 'jpg', 'PNG': 'png', 'WEBP': 'webp', 'GIF': 'gif'}
MIMES: dict[str, str] = {'jpg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp', 'gif': 'image/gif'}


class ErrorImagen(Exception):
    """Falla al descargar o procesar una imagen. `codigo` es corto y sin datos (nunca la URL); `permanente=True`
    deja la fila en 'bloqueada' (no se reintenta mientras no cambie la URL)."""

    def __init__(self, codigo: str, permanente: bool = False) -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.permanente = permanente


# ------------------------------------------------------------------ claves
def ref_valido(tipo: object, ref_id: object) -> bool:
    if not isinstance(ref_id, str):
        return False
    if tipo in ('p', 'm', 'v'):
        return _RE_REF.fullmatch(ref_id) is not None
    if tipo == 'a':
        return ref_id == REF_CUENTA
    if tipo == 'g':
        return _RE_GALERIA.fullmatch(ref_id) is not None
    return False


def es_diferida(tipo: object) -> bool:
    """Galería de vitrina y parecidos: se registran al sincronizar pero solo se bajan cuando alguien las pide."""
    return tipo in TIPOS_DIFERIDOS


def ref_galeria(product_id: str, n: int) -> str:
    """'<product_id>-<n>' (foto n de la galería de vitrina). ValueError si no es válida."""
    ref = f'{product_id}-{int(n)}'
    if not ref_valido('g', ref):
        raise ValueError('foto de galería inválida')
    return ref


def clave(tipo: str, ref_id: str) -> str:
    """'p:<product_id>', 'a:cuenta', 'g:<product_id>-<n>', 'm:<product_id>' o 'v:<video_id>'. ValueError si no vale."""
    if not ref_valido(tipo, ref_id):
        raise ValueError('clave de imagen inválida')
    return f'{tipo}:{ref_id}'


def partes(img_key: str) -> tuple[str, str]:
    tipo, _, ref_id = img_key.partition(':')
    if not ref_valido(tipo, ref_id):
        raise ValueError('clave de imagen inválida')
    return tipo, ref_id


def version_valida(v: object) -> bool:
    return isinstance(v, str) and _RE_VERSION.fullmatch(v) is not None


# ------------------------------------------------------------------ URL de origen
def url_permitida(url: object) -> str | None:
    """Host en minúsculas si la URL se puede descargar (https + lista blanca + sin usuario + puerto 443); si no, None."""
    if not isinstance(url, str) or not url or len(url) > MAX_LARGO_URL or not url.isascii():
        return None                                     # sin ASCII: IDNA/NFKC podrían cambiar el host al conectar
    if any(c in _PROHIBIDOS_URL or ord(c) < 32 or ord(c) == 127 for c in url):
        return None
    try:
        u = urllib.parse.urlsplit(url)
        puerto = u.port
    except ValueError:
        return None
    if u.scheme != 'https' or u.username is not None or u.password is not None or puerto not in (None, 443):
        return None
    host = (u.hostname or '').lower()
    if not host or '@' in u.netloc or not config.host_cdn_permitido(host):
        return None
    return host


def huella_url(url: str) -> str:
    """sha1(host + path) sin la query volátil (firma, x-expires): misma imagen aunque cambie la firma."""
    u = urllib.parse.urlsplit(url)
    return hashlib.sha1(((u.hostname or '').lower() + u.path).encode('utf-8')).hexdigest()


def es_firmada(url: str) -> bool:
    """URL firmada que caduca (avatar con x-expires): se descarga antes que todo lo demás."""
    try:
        nombres = {k.lower() for k, _ in urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query,
                                                                keep_blank_values=True)}
    except ValueError:
        return False
    return bool(nombres & {'x-expires', 'x-signature', 'expires'})


# ------------------------------------------------------------------ rutas en disco
def ruta_rel_og(tipo: str, ref_id: str, version: str, ext: str) -> str:
    if not ref_valido(tipo, ref_id) or not version_valida(version) or ext not in MIMES:
        raise ValueError('datos de ruta inválidos')
    return os.path.join(tipo, ref_id[:2], f'{ref_id}_{version}_og.{ext}')


def ruta_rel_variante(ruta_rel: str, t: str) -> str | None:
    """Ruta de la variante `t` a partir de la del original (`…_og.<ext>` -> `…_<t>.webp`)."""
    if t not in VARIANTES or not isinstance(ruta_rel, str):
        return None
    m = _RE_OG.match(ruta_rel)
    return f"{m.group('base')}_{t}.webp" if m else None


def rutas_rel_de(ruta_rel: str) -> list[str]:
    """El original y sus tres variantes."""
    rutas = [ruta_rel]
    rutas += [r for r in (ruta_rel_variante(ruta_rel, t) for t in VARIANTES) if r]
    return rutas


def ruta_segura(raiz: str, ruta_rel: object) -> str | None:
    """Ruta absoluta de `ruta_rel` (leída de la tabla) solo si su realpath queda dentro de la raíz de la caché."""
    if not isinstance(ruta_rel, str) or not ruta_rel or '\x00' in ruta_rel:
        return None
    if os.path.isabs(ruta_rel) or os.path.splitdrive(ruta_rel)[0] or ruta_rel[0] in '\\/':
        return None                                     # absoluta, con unidad o UNC: ni siquiera se resuelve
    base = os.path.realpath(raiz)
    real = os.path.realpath(os.path.join(base, ruta_rel))
    if not os.path.normcase(real).startswith(os.path.normcase(base) + os.sep):
        return None
    return real


def nombre_de_cache(nombre: str) -> bool:
    """True si `nombre` tiene la forma de un archivo que escribe este módulo (para limpiar huérfanos)."""
    return _RE_ARCHIVO.fullmatch(nombre) is not None


# ------------------------------------------------------------------ URL del hub (/img/<t>/<id>?v=…&t=…)
class UrlImg(NamedTuple):
    tipo: str
    ref_id: str
    v: str | None
    t: str | None

    @property
    def clave(self) -> str:
        return f'{self.tipo}:{self.ref_id}'


def parsear_url_img(url: object) -> UrlImg | None:
    """'/img/p/1731…?v=3f2a91c0&t=sm' -> UrlImg; None si no es una URL de imagen del hub válida."""
    if not isinstance(url, str) or len(url) > MAX_LARGO_URL:
        return None
    try:
        u = urllib.parse.urlsplit(url)
        q = urllib.parse.parse_qs(u.query, keep_blank_values=True)
    except ValueError:
        return None
    trozos = u.path.split('/')
    if u.scheme or u.netloc or len(trozos) != 4 or trozos[0] != '' or trozos[1] != 'img':
        return None
    tipo, ref_id = trozos[2], urllib.parse.unquote(trozos[3])
    if not ref_valido(tipo, ref_id):
        return None
    v = (q.get('v') or [None])[0]
    t = (q.get('t') or [None])[0]
    return UrlImg(tipo, ref_id, v, t)
