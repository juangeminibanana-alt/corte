"""Descubrimiento UDP de la PC en la Wi-Fi (contrato.ts «Protocolo LAN 1»; 03 §6.6; 04 §B.8).

`UDP 0.0.0.0:39231` con `SO_EXCLUSIVEADDRUSE`. Pregunta ASCII `CREATORHUB_DESCUBRIR 1 <nonce 32 hex>` (≤ 160 B) →
respuesta unicast JSON (≤ 512 B) `{"app","v","host_id","nombre_equipo","puerto","huella","nonce"}`. `nombre_equipo`
es el ALIAS de LanEstado (C38: «PC 3F2A» por omisión), nunca el nombre de Windows. Solo responde a IPs privadas
(loopback solo con `permitir_loopback`, en pruebas), máx. 10 respuestas por segundo; lo malformado se ignora en silencio.
La huella de la respuesta no está autenticada: es solo una pista para el celular.
"""
from __future__ import annotations

import collections
import logging
import socket
import threading
import time
from typing import Callable

from . import protocolo_lan as pl
from .red import ip_permitida

_log = logging.getLogger('creatorhub.lan.descubrimiento')

MAX_RESPUESTAS_POR_S = 10


class RespondedorUdp:
    """Hilo que contesta las preguntas de descubrimiento. `identidad()` -> (host_id, alias, puerto_lan, huella_hex)."""

    def __init__(self, ip: str, puerto: int, identidad: Callable[[], tuple[str, str, int, str]],
                 permitir_loopback: bool = False) -> None:
        self.identidad = identidad
        self.permitir_loopback = permitir_loopback
        self.respuestas = 0
        self.ignorados = 0
        self._ultimas: collections.deque[float] = collections.deque()
        self._vivo = threading.Event()
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.s.bind((ip, puerto))
            self.s.settimeout(0.25)
        except OSError:
            self.s.close()
            raise
        self.puerto = self.s.getsockname()[1]
        self._hilo = threading.Thread(target=self._bucle, name='lan-descubrimiento', daemon=True)

    def iniciar(self) -> None:
        self._vivo.set()
        self._hilo.start()

    def _bucle(self) -> None:
        while self._vivo.is_set():
            try:
                datos, origen = self.s.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                # en Windows un ICMP «puerto inalcanzable» de un envío anterior se reporta aquí (WSAECONNRESET)
                if not self._vivo.is_set():
                    break
                continue
            try:
                self._atender(datos, origen)
            except Exception:  # noqa: BLE001 - un datagrama raro nunca tumba el respondedor
                _log.exception('Error al atender un datagrama de descubrimiento')

    def _atender(self, datos: bytes, origen: tuple[str, int]) -> None:
        ahora = time.monotonic()
        while self._ultimas and ahora - self._ultimas[0] > 1.0:
            self._ultimas.popleft()
        nonce = pl.leer_pregunta(datos)
        if nonce is None or not ip_permitida(origen[0], self.permitir_loopback) \
                or len(self._ultimas) >= MAX_RESPUESTAS_POR_S:
            self.ignorados += 1
            return
        host_id, alias, puerto_lan, huella = self.identidad()
        respuesta = pl.respuesta_descubrimiento(host_id, alias, puerto_lan, huella, nonce)
        if len(respuesta) > pl.MAX_RESPUESTA_UDP:
            _log.warning('Respuesta de descubrimiento de %d bytes: no se envía', len(respuesta))
            return
        self._ultimas.append(ahora)
        self.s.sendto(respuesta, origen)
        self.respuestas += 1

    def cerrar(self, espera_s: float = 2.0) -> None:
        self._vivo.clear()
        try:
            self.s.close()
        except OSError:
            pass
        if self._hilo.is_alive():
            self._hilo.join(espera_s)
