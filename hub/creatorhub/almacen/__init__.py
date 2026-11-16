"""Almacén SQLite del hub (hub-sync). Exporta la fábrica `crear_almacen(ruta_db, reloj)` (BUILD_SPEC §6.2)."""
from __future__ import annotations

from .almacen import (MENSAJE_VERSION_NUEVA, PRAGMAS_APERTURA, SEMILLAS_META, TABLAS_LOCALES, TABLAS_SYNC, TABLAS_TIKTOK,
                      USER_VERSION, crear_almacen, leer_recurso_sql)

__all__ = ['crear_almacen', 'leer_recurso_sql', 'USER_VERSION', 'PRAGMAS_APERTURA', 'SEMILLAS_META', 'TABLAS_TIKTOK',
           'TABLAS_SYNC', 'TABLAS_LOCALES', 'MENSAJE_VERSION_NUEVA']
