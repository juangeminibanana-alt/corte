"""Descargador del modo demo (BUILD_SPEC §6.3.1 punto 6; 03 §9.2): `url -> bytes` que NUNCA usa la red.

- 'fixtures_reales' (solo desarrollo): si existe ui/fixtures/img (lo genera fixtures-ui), devuelve el ORIGINAL de esa
  carpeta: el producto se reconoce por la huella sha1(host + path) de su main_image_url en research/datos-reales y el
  avatar de demostración por su URL. Si no hay archivo, cae al marcador.
- 'sinteticos' (o sin archivo): marcador PNG dibujado con Pillow (import perezoso, C3): color de la tienda + iniciales
  del producto, como pide 03 §9.2. Siempre es una imagen válida de 720 × 720.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import threading
import urllib.parse
from typing import Callable

from ..interfaces import Descargador, FuenteDemo
from . import sinteticos
from .transporte import DIR_DATOS_REALES, RAIZ_PROYECTO, URL_AVATAR_DEMO

DIR_FIXTURES_IMG = os.path.join(RAIZ_PROYECTO, 'ui', 'fixtures', 'img')
LADO_MARCADOR = 720


def huella_url(url: str) -> str:
    u = urllib.parse.urlsplit(url)
    return hashlib.sha1(((u.hostname or '') + u.path).encode('utf-8')).hexdigest()


def _aclarar(color: str, f: float) -> str:
    """'#rrggbb' mezclado con blanco en proporción f (0..1)."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return '#{:02x}{:02x}{:02x}'.format(*(round(c + (255 - c) * f) for c in (r, g, b)))


def _iniciales(texto: str) -> str:
    palabras = [p for p in ''.join(c if c.isalnum() or c.isspace() else ' ' for c in texto).split() if p]
    return (''.join(p[0] for p in palabras[:2]) or '?').upper()


def marcador_png(texto: str, color: str, lado: int = LADO_MARCADOR) -> bytes:
    """PNG cuadrado de un color con las iniciales de `texto` al centro (Pillow, import perezoso)."""
    from PIL import Image, ImageDraw, ImageFont                       # C3: Pillow solo aquí y en imagenes/

    img = Image.new('RGB', (lado, lado), color)
    dibujo = ImageDraw.Draw(img)
    letras = _iniciales(texto)
    try:
        fuente = ImageFont.load_default(size=lado // 3)
    except (TypeError, OSError):                                       # Pillow sin FreeType: fuente de mapa de bits
        fuente = ImageFont.load_default()
    caja = dibujo.textbbox((0, 0), letras, font=fuente)
    x = (lado - (caja[2] - caja[0])) / 2 - caja[0]
    y = (lado - (caja[3] - caja[1])) / 2 - caja[1]
    dibujo.text((x, y), letras, fill='#ffffff', font=fuente)
    salida = io.BytesIO()
    img.save(salida, format='PNG', optimize=True)
    return salida.getvalue()


class _DescargadorDemo:
    def __init__(self, fuente: FuenteDemo) -> None:
        self.fuente = fuente
        self._candado = threading.Lock()
        self._catalogo: sinteticos.Catalogo | None = None
        self._indice_real: dict[str, str] | None = None

    # ------------------------------------------------------------------ búsqueda
    def _producto_sintetico(self, url: str) -> tuple[str, str] | None:
        with self._candado:
            if self._catalogo is None:
                self._catalogo = sinteticos.catalogo()
            cat = self._catalogo
        nombre = os.path.splitext(os.path.basename(urllib.parse.urlsplit(url).path))[0]
        pid, _, n = nombre.partition('-')               # rev. 4: foto n de la galería de vitrina ('<id>-<n>')
        p = cat.por_id.get(pid)
        if p is None:
            return None
        color = cat.tiendas[p.tienda].color
        if n.isdigit():                                 # cada foto de la galería, un tono distinto del color de la tienda
            color = _aclarar(color, min(0.6, 0.12 * int(n)))
        return p.titulo, color

    def _indice_fixtures(self) -> dict[str, str]:
        """huella(main_image_url) -> product_id, desde research/datos-reales/productos.json (solo desarrollo)."""
        with self._candado:
            if self._indice_real is not None:
                return self._indice_real
            indice: dict[str, str] = {}
            ruta = os.path.join(DIR_DATOS_REALES, 'productos.json')
            try:
                with open(ruta, encoding='utf-8-sig') as f:
                    productos = json.load(f)
                for pid, p in productos.items():
                    if isinstance(p, dict) and p.get('main_image_url'):
                        indice[huella_url(p['main_image_url'])] = str(pid)
            except (OSError, ValueError):
                pass
            self._indice_real = indice
            return indice

    @staticmethod
    def _original(tipo: str, ref_id: str) -> bytes | None:
        carpeta = os.path.join(DIR_FIXTURES_IMG, tipo, ref_id)
        if not os.path.isdir(carpeta):
            return None
        for nombre in sorted(os.listdir(carpeta)):
            if nombre.startswith('og.'):
                with open(os.path.join(carpeta, nombre), 'rb') as f:
                    return f.read()
        return None

    # ------------------------------------------------------------------ Descargador
    def __call__(self, url: str) -> bytes:
        if self.fuente == 'fixtures_reales':
            if huella_url(url) == huella_url(URL_AVATAR_DEMO):
                datos = self._original('a', 'cuenta')
                if datos:
                    return datos
            else:
                pid = self._indice_fixtures().get(huella_url(url))
                if pid:
                    datos = self._original('p', pid)
                    if datos:
                        return datos
        if huella_url(url) == huella_url(URL_AVATAR_DEMO):
            return marcador_png('creador demo', '#8a5cf6')
        ruta = urllib.parse.urlsplit(url).path
        if ruta.startswith('/obj/corte-demo/portada/'):      # rev. 5: portada de un video de la Display API de demo
            vid = os.path.splitext(os.path.basename(ruta))[0]
            return marcador_png(f'Video {vid[-4:]}', sinteticos.color_de(vid))
        sint = self._producto_sintetico(url)
        if sint is not None:
            return marcador_png(sint[0], sint[1])
        return marcador_png(os.path.basename(urllib.parse.urlsplit(url).path) or 'Producto',
                            sinteticos.color_de(huella_url(url)))


def crear_descargador(fuente: FuenteDemo) -> Callable[[str], bytes]:
    return _DescargadorDemo(fuente)


__all__ = ['crear_descargador', 'marcador_png', 'huella_url', 'DIR_FIXTURES_IMG', 'Descargador']
