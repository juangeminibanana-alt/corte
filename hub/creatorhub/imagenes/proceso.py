"""Verificación y variantes con Pillow (03 §2.3; 02 §8.2–8.3). PIL se importa AQUÍ y solo dentro de las funciones:
importar este módulo no carga PIL (C3); lo carga el primer trabajador que procesa una imagen.

- `Image.open(..., formats=JPEG/PNG/WEBP/GIF)`: ningún otro decodificador se intenta.
- `DecompressionBombWarning` como error (filtro reafirmado en cada llamada, así queda primero aunque otro código
  cambie los filtros) y `Image.MAX_IMAGE_PIXELS` nunca por encima de 40 M. Además, rechazo explícito si
  ancho × alto > 40 M leyendo solo el encabezado, ANTES de `load()`.
- Extensión por formato detectado (`claves.EXTENSIONES`), nunca por la cabecera HTTP. `version = sha256(og)[:8]`.
- Variantes WebP por ancho: xs 96 (q78), sm 240 (q80), md 720 (q82); el alto sale de la proporción y nunca se amplía.
  JPEG grandes se decodifican con `draft()` a la escala mínima que conserva ≥ 720 px por lado.
- `lqip`: WebP de 16 px de ancho como data URI ≤ 600 B (calidad 50, baja de 10 en 10; si ni con 0 cabe, None).
- `color`: '#rrggbb', promedio de la imagen reducida a 8×8.
- Orientación EXIF aplicada (ancho y alto son los que ve el usuario); transparencia aplanada sobre blanco.
"""
from __future__ import annotations

import base64
import hashlib
import io
import threading
import warnings
from dataclasses import dataclass, field
from typing import Any

from .. import config
from .claves import EXTENSIONES, MIMES, VARIANTES, ErrorImagen

FORMATOS_PERMITIDOS: tuple[str, ...] = ('JPEG', 'PNG', 'WEBP', 'GIF')
LQIP_ANCHO = 16
LQIP_MAX_BYTES = 600
LQIP_CALIDADES: tuple[int, ...] = (50, 40, 30, 20, 10, 0)
PREFIJO_LQIP = 'data:image/webp;base64,'
_ORIENTACION_EXIF = 0x0112
_candado_pil = threading.Lock()
_pil_configurado = False


@dataclass(frozen=True)
class Variante:
    nombre: str
    datos: bytes
    ancho: int
    alto: int


@dataclass(frozen=True)
class Procesada:
    version: str
    ext: str
    mime: str
    ancho: int                     # del original, ya orientado (ImagenMeta.w)
    alto: int                      # ImagenMeta.h
    variantes: dict[str, Variante] = field(default_factory=dict)
    lqip: str | None = None
    color: str | None = None


def _pil() -> Any:
    """Importa PIL (perezoso) y deja la defensa contra bombas activa."""
    global _pil_configurado
    from PIL import Image

    with _candado_pil:
        if not _pil_configurado:
            if Image.MAX_IMAGE_PIXELS is None or Image.MAX_IMAGE_PIXELS > config.IMAGEN_MAX_PIXELES:
                Image.MAX_IMAGE_PIXELS = config.IMAGEN_MAX_PIXELES
            _pil_configurado = True
        # filterwarnings quita el filtro idéntico y lo vuelve a insertar al frente: no crece y siempre manda.
        warnings.filterwarnings('error', category=Image.DecompressionBombWarning)
    return Image


def _abrir(og: bytes) -> tuple[Any, str, int, int]:
    """Abre y valida SIN decodificar los píxeles. -> (imagen, formato, ancho, alto del encabezado)."""
    Image = _pil()
    try:
        im = Image.open(io.BytesIO(og), formats=FORMATOS_PERMITIDOS)
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ErrorImagen('bomba', permanente=True) from None
    except Image.UnidentifiedImageError:
        raise ErrorImagen('formato_no_permitido', permanente=True) from None
    except (OSError, SyntaxError, ValueError, EOFError, MemoryError):
        raise ErrorImagen('imagen_invalida') from None
    formato = im.format or ''
    ancho, alto = im.size
    if formato not in EXTENSIONES:
        im.close()
        raise ErrorImagen('formato_no_permitido', permanente=True)
    if ancho <= 0 or alto <= 0 or ancho * alto > config.IMAGEN_MAX_PIXELES:
        im.close()
        raise ErrorImagen('bomba', permanente=True)               # rechazo ANTES de load()
    return im, formato, ancho, alto


def _orientacion(im: Any) -> int:
    try:
        return int(im.getexif().get(_ORIENTACION_EXIF, 1) or 1)
    except Exception:  # noqa: BLE001 - EXIF dañado: se ignora la orientación
        return 1


def _a_rgb(im: Any) -> Any:
    Image = _pil()
    if im.mode in ('RGBA', 'LA', 'PA') or (im.mode == 'P' and 'transparency' in im.info):
        rgba = im.convert('RGBA')
        fondo = Image.new('RGB', rgba.size, (255, 255, 255))
        fondo.paste(rgba, mask=rgba.getchannel('A'))
        return fondo
    return im if im.mode == 'RGB' else im.convert('RGB')


def _decodificar(og: bytes) -> tuple[Any, str, int, int]:
    """-> (imagen RGB orientada, formato, ancho y alto ORIGINALES orientados)."""
    Image = _pil()
    from PIL import ImageOps

    im, formato, ancho, alto = _abrir(og)
    try:
        orientacion = _orientacion(im)
        if orientacion in (5, 6, 7, 8):
            ancho, alto = alto, ancho
        if formato in ('JPEG', 'MPO'):
            maximo = max(v[0] for v in VARIANTES.values())
            im.draft('RGB', (maximo, maximo))                     # escala ≥ 720 px por lado: variantes exactas
        try:
            im.load()
        except (Image.DecompressionBombWarning, Image.DecompressionBombError):
            raise ErrorImagen('bomba', permanente=True) from None
        except (OSError, SyntaxError, ValueError, EOFError, MemoryError):
            raise ErrorImagen('imagen_invalida') from None
        try:
            orientada = ImageOps.exif_transpose(im) if orientacion != 1 else im
        except Exception:  # noqa: BLE001 - si EXIF no se puede aplicar, se usa tal cual
            orientada = im
        try:
            rgb = _a_rgb(orientada)
        except (OSError, ValueError, MemoryError):
            raise ErrorImagen('imagen_invalida') from None
        if rgb is im:
            rgb = im.copy()
        return rgb, formato, ancho, alto
    finally:
        im.close()


def _webp(im: Any, ancho_max: int, calidad: int) -> tuple[bytes, int, int]:
    Image = _pil()
    w, h = im.size
    tw = min(ancho_max, w)
    th = max(1, round(h * tw / w))
    chica = im if (tw, th) == (w, h) else im.resize((tw, th), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    chica.save(buf, format='WEBP', quality=calidad, method=4)
    return buf.getvalue(), tw, th


def lqip_de(im: Any) -> str | None:
    Image = _pil()
    w, h = im.size
    th = max(1, round(h * LQIP_ANCHO / w))
    mini = im.resize((LQIP_ANCHO, th), Image.Resampling.LANCZOS)
    for calidad in LQIP_CALIDADES:
        buf = io.BytesIO()
        mini.save(buf, format='WEBP', quality=calidad, method=6)
        uri = PREFIJO_LQIP + base64.b64encode(buf.getvalue()).decode('ascii')
        if len(uri.encode('ascii')) <= LQIP_MAX_BYTES:
            return uri
    return None


def color_de(im: Any) -> str:
    Image = _pil()
    datos = im.resize((8, 8), Image.Resampling.BOX).tobytes()          # 64 píxeles RGB
    n = len(datos) // 3
    canales = [round(sum(datos[i::3]) / n) for i in range(3)]
    return '#%02x%02x%02x' % tuple(max(0, min(255, c)) for c in canales)


def procesar(og: bytes) -> Procesada:
    """Bytes originales -> versión, formato, medidas, variantes WebP, lqip y color. Lanza ErrorImagen."""
    if not og:
        raise ErrorImagen('respuesta_vacia')
    if len(og) > config.IMAGEN_MAX_BYTES:
        raise ErrorImagen('demasiado_grande', permanente=True)
    rgb, formato, ancho, alto = _decodificar(og)
    try:
        variantes = {}
        for nombre, (ancho_v, calidad) in VARIANTES.items():
            datos, w, h = _webp(rgb, ancho_v, calidad)
            variantes[nombre] = Variante(nombre, datos, w, h)
        lqip = lqip_de(rgb)
        color = color_de(rgb)
    except (OSError, ValueError, MemoryError):
        raise ErrorImagen('imagen_invalida') from None
    finally:
        rgb.close()
    ext = EXTENSIONES[formato]
    return Procesada(version=hashlib.sha256(og).hexdigest()[:8], ext=ext, mime=MIMES[ext], ancho=ancho, alto=alto,
                     variantes=variantes, lqip=lqip, color=color)
