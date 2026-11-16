"""Reloj del hub (BUILD_SPEC §6.2 `Reloj`).

`crear_reloj(None)` = reloj del sistema. `crear_reloj(ahora_fijo)` = reloj que ARRANCA en `ahora_fijo` (epoch UTC, s) y
avanza al ritmo real (bandera `--ahora`, solo demo y autoprueba). `esperar()` duerme con un `threading.Event`, así una
cancelación o un cierre no esperan el plazo completo; devuelve True si se canceló.
"""
from __future__ import annotations

import threading
import time

from .interfaces import Reloj


def _esperar(segundos: float, cancelar: threading.Event | None) -> bool:
    if cancelar is None:
        if segundos > 0:
            threading.Event().wait(segundos)
        return False
    if segundos <= 0:
        return cancelar.is_set()
    return cancelar.wait(segundos)


class _RelojSistema:
    def ahora(self) -> int:
        return int(time.time())

    def monotonico(self) -> float:
        return time.monotonic()

    def esperar(self, segundos: float, cancelar: threading.Event | None = None) -> bool:
        return _esperar(segundos, cancelar)


class _RelojDesde:
    """Arranca en `inicio` y avanza con el reloj monotónico (inmune a cambios de hora del equipo)."""

    def __init__(self, inicio: int) -> None:
        self.inicio = inicio
        self._t0 = time.monotonic()

    def ahora(self) -> int:
        return self.inicio + int(time.monotonic() - self._t0)

    def monotonico(self) -> float:
        return time.monotonic()

    def esperar(self, segundos: float, cancelar: threading.Event | None = None) -> bool:
        return _esperar(segundos, cancelar)


def crear_reloj(ahora_fijo: int | None = None) -> Reloj:
    if ahora_fijo is None:
        return _RelojSistema()
    if isinstance(ahora_fijo, bool) or not isinstance(ahora_fijo, int) or ahora_fijo <= 0:
        raise ValueError('ahora_fijo debe ser un epoch UTC en segundos (entero positivo)')
    return _RelojDesde(ahora_fijo)
