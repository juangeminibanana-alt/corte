"""Estado local del usuario (paquete hub-analitica, BUILD_SPEC §6.2): plan, avisos, plantillas, preferencias, notas,
recordatorios, ops del celular y exportar/importar. Dato de ejecución: plantillas.json (importlib.resources).

Fábrica con firma EXACTA de interfaces.FABRICAS: `crear_estado_local(almacen, bus, reloj) -> EstadoLocal`.
"""
from __future__ import annotations

from ..interfaces import Almacen, Bus, EstadoLocal, Reloj
from .estado import EstadoLocalSqlite


def crear_estado_local(almacen: Almacen, bus: Bus, reloj: Reloj) -> EstadoLocal:
    """EstadoLocal sobre las tablas locales del almacén; `sembrar()` es lo único que siembra plantillas y preferencias."""
    return EstadoLocalSqlite(almacen, bus, reloj)


__all__ = ['crear_estado_local', 'EstadoLocalSqlite']
