"""Canal LAN PC ↔ celular (BUILD §3.1, §6.2; contrato.ts «Protocolo LAN 1 · NORMATIVO»; 03 §6.6, §7.4–§7.5; 04 §C).

Módulos: `protocolo_lan` (CH1, código, K_pair, prueba, SAS, K_enc, paquete, QR, UDP) · `identidad_tls` (CNG) ·
`servidor_lan` (HTTPS /lan/v1/*) · `emparejamiento` · `dispositivos` · `descubrimiento` (UDP 39231) · `red` · `qr`
(PyPNGImage, nunca PIL) · `firewall` (literal de 04 §C.10) · `firewall_diag` · `servicio` (ServicioLan).

Única fábrica (firma EXACTA de interfaces.FABRICAS): `crear_servicio_lan(dep)`. El import es perezoso: cargar
`creatorhub.lan` no abre sockets ni importa qrcode.
"""
from __future__ import annotations

from ..interfaces import Dependencias, ServicioLan

__all__ = ['crear_servicio_lan']


def crear_servicio_lan(dep: Dependencias) -> ServicioLan:
    """ServicioLan de producción. hub.py llama después `fijar_despachador(d)` y, en segundo plano,
    `iniciar_si_activo()` (BUILD §6.3.1 pasos 10 y 12)."""
    from .servicio import ServicioLanHub
    return ServicioLanHub(dep)
