"""Analítica del hub (paquete hub-analitica, BUILD_SPEC §6.2): lecturas del contrato REST sobre SQLite.

Fábrica con firma EXACTA de interfaces.FABRICAS: `crear_analitica(almacen, reloj) -> Analitica`.
"""
from __future__ import annotations

from ..interfaces import Almacen, Analitica, Reloj
from .servicio import AnaliticaSqlite


def crear_analitica(almacen: Almacen, reloj: Reloj) -> Analitica:
    """Analitica de solo lectura: una transacción de lectura por respuesta, imágenes con la regla C45."""
    return AnaliticaSqlite(almacen, reloj)


__all__ = ['crear_analitica', 'AnaliticaSqlite']
