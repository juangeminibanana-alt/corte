"""Canal de eventos de la ventana local: `GET /api/events` (03 §6.4; BUILD_SPEC §5).

Formato: `retry: 3000` al abrir y luego un mensaje por EventoHub: `event: <tipo>\\ndata: <json>\\n\\n` (el JSON trae
también `tipo`). `ping` cada 15 s (`{"tipo":"ping","t":<epoch>}`). La suscripción al bus tiene cola de 100: si se
llena, el bus la corta y aquí se cierra la conexión (EventSource se reconecta y la interfaz relee). Al detener el hub
se cierran todas las conexiones abiertas. Solo para la ventana local: por la LAN la ruta es `403 solo_local`.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, BinaryIO

from ..interfaces import Bus, Json, Reloj

_log = logging.getLogger('creatorhub.api.sse')

PING_S = 15.0
REINTENTO_MS = 3000
MAX_COLA = 100


def formatear(evento: Json) -> bytes:
    tipo = str(evento.get('tipo') or 'message').replace('\n', ' ').replace('\r', ' ')
    datos = json.dumps(evento, ensure_ascii=False, separators=(',', ':'))
    return f'event: {tipo}\ndata: {datos}\n\n'.encode('utf-8')


class CanalEventos:
    """Lleva la cuenta de las suscripciones abiertas para cerrarlas todas al detener el hub."""

    def __init__(self, bus: Bus, reloj: Reloj, ping_s: float = PING_S) -> None:
        self.bus = bus
        self.reloj = reloj
        self.ping_s = float(ping_s)
        self.parar = threading.Event()
        self._candado = threading.Lock()
        self._abiertas: set[Any] = set()

    def abiertas(self) -> int:
        with self._candado:
            return len(self._abiertas)

    def cerrar_todas(self) -> None:
        self.parar.set()
        with self._candado:
            subs, self._abiertas = list(self._abiertas), set()
        for s in subs:
            try:
                s.cerrar()
            except Exception:  # noqa: BLE001
                pass

    def transmitir(self, salida: BinaryIO) -> None:
        """Escribe eventos en `salida` hasta que el cliente se vaya, el bus corte la suscripción o el hub se detenga.
        Las cabeceras HTTP ya las mandó el servidor."""
        if self.parar.is_set():
            return
        sub = self.bus.suscribir(MAX_COLA)
        with self._candado:
            self._abiertas.add(sub)
        try:
            salida.write(f'retry: {REINTENTO_MS}\n\n'.encode('ascii'))
            salida.flush()
            proximo_ping = time.monotonic() + self.ping_s
            while not self.parar.is_set():
                espera = max(0.0, min(1.0, proximo_ping - time.monotonic()))
                ev = sub.siguiente(espera)
                if ev is not None:
                    salida.write(formatear(ev))
                    salida.flush()
                elif getattr(sub, 'cerrada', False):
                    break                                  # cortada por cola llena o cerrada al detener
                if time.monotonic() >= proximo_ping:
                    salida.write(formatear({'tipo': 'ping', 't': self.reloj.ahora()}))
                    salida.flush()
                    proximo_ping = time.monotonic() + self.ping_s
        except (OSError, ValueError):
            pass                                           # el cliente cerró la conexión
        finally:
            with self._candado:
                self._abiertas.discard(sub)
            try:
                sub.cerrar()
            except Exception:  # noqa: BLE001
                pass
