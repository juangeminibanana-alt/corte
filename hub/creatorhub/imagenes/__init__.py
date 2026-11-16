"""Caché de imágenes del hub (paquete hub-imagenes; BUILD_SPEC §6.2, §6.3.3, C3, C11, C39, C45; 03 §2.3 y §6.5).

Fábrica: `crear_imagenes(almacen, bus, reloj, raiz_cache, descargar=None)` (firma de FABRICAS). Importar este paquete
NO importa PIL: Pillow se carga de forma perezosa en `proceso.py`, cuando un trabajador procesa la primera imagen.

Módulos: `claves` (validaciones, rutas, URL), `cola` (prioridad y límite por host), `descarga` (HTTPS real con lista
blanca), `proceso` (Pillow: bombas, formato, variantes, lqip, color) y `servicio` (implementación de `Imagenes`).
Sin archivos de datos de ejecución.
"""
from __future__ import annotations

from .servicio import crear_imagenes

__all__ = ['crear_imagenes']
