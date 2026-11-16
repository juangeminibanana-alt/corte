"""API del hub (hub-api; BUILD_SPEC §5, §6.4): servidor de interfaz, Despachador de rutas, sesión, seguridad, SSE,
estáticos y archivos del usuario. `rutas.crear_despachador(hub)` lo usa hub.py y, por la LAN, servidor_lan."""
from __future__ import annotations

from .rutas import crear_despachador

__all__ = ['crear_despachador']
