"""Hub de Corte (nombre técnico CreatorHub): servidor local, sincronización con TikTok Shop y canal LAN.

El paquete no importa nada al cargarse para no pesar en el arranque (`t_hub_listo_ms`, BUILD_SPEC C3). La versión vive
en `creatorhub.config.VERSION` (leída de `version.json`) y las interfaces entre paquetes en `creatorhub.interfaces`.
"""
from __future__ import annotations
