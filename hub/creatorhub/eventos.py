"""Bus de eventos en memoria (BUILD_SPEC §6.2 `Bus`; 03 §2.5): SSE (`/api/events`) y long-poll (`/api/cambios`).

- `publicar(evento)` reparte un EventoHub completo a cada suscripción. Cada suscripción tiene una cola de `max_cola`
  (100 por omisión); si se llena, ESA suscripción se corta (se vacía y `siguiente()` devuelve None con `cortada=True`):
  el cliente vuelve a conectarse y relee lo que necesite.
- `notificar_cambio(versiones, secciones)` publica {'tipo': 'datos.cambiaron', data_version, local_rev, img_rev,
  secciones} y despierta a `esperar_cambio`.
- `esperar_cambio(vistas, timeout_s)` responde en cuanto las versiones difieren de `vistas` (o de inmediato si ya
  difieren); img_rev < 0 en `vistas` = no comparar img_rev (cliente sin img_rev en la query). None al agotar la espera.
"""
from __future__ import annotations

import collections
import logging
import threading
import time
from typing import Any, Sequence

from .interfaces import Bus, Json, Versiones

_log = logging.getLogger('creatorhub.eventos')

SECCIONES: tuple[str, ...] = ('muestras', 'ordenes', 'productos', 'tiendas', 'videos', 'cuenta', 'local')
_HISTORIAL = 256


def _validar_versiones(v: Any) -> Versiones:
    if not isinstance(v, (tuple, list)) or len(v) != 3 or not all(isinstance(x, int) and not isinstance(x, bool)
                                                                  for x in v):
        raise ValueError('versiones debe ser (data_version, local_rev, img_rev) con enteros')
    return (v[0], v[1], v[2])


def _difiere(actual: Versiones, vistas: Versiones) -> bool:
    return actual[0] != vistas[0] or actual[1] != vistas[1] or (vistas[2] >= 0 and actual[2] != vistas[2])


class _Suscripcion:
    """Implementa Suscripcion. `cerrada` = ya no entregará nada; `cortada` = se cerró porque se llenó su cola."""

    def __init__(self, bus: '_Bus', max_cola: int) -> None:
        self._bus = bus
        self._max = max_cola
        self._cola: collections.deque[Json] = collections.deque()
        self._cond = threading.Condition()
        self.cerrada = False
        self.cortada = False

    def _entregar(self, evento: Json) -> bool:
        with self._cond:
            if self.cerrada:
                return True
            if len(self._cola) >= self._max:
                return False
            self._cola.append(evento)
            self._cond.notify()
            return True

    def _cortar(self) -> None:
        with self._cond:
            self.cortada = True
            self.cerrada = True
            self._cola.clear()
            self._cond.notify_all()

    def siguiente(self, timeout_s: float) -> Json | None:
        limite = time.monotonic() + max(0.0, timeout_s)
        with self._cond:
            while not self._cola and not self.cerrada:
                restante = limite - time.monotonic()
                if restante <= 0:
                    return None
                self._cond.wait(restante)
            if self._cola:
                return self._cola.popleft()
            return None

    def cerrar(self) -> None:
        with self._cond:
            self.cerrada = True
            self._cola.clear()
            self._cond.notify_all()
        self._bus._quitar(self)


class _Bus:
    """Implementa Bus. Seguro entre hilos; no hace E/S."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._versiones: Versiones = (0, 0, 0)
        self._historial: collections.deque[tuple[Versiones, tuple[str, ...]]] = collections.deque(maxlen=_HISTORIAL)
        self._base: Versiones = (0, 0, 0)          # el historial está completo para quien ya vio al menos esto
        self._candado_subs = threading.Lock()
        self._subs: set[_Suscripcion] = set()

    # -------------------------------------------------------------- versiones
    def iniciar_versiones(self, versiones: Versiones) -> None:
        v = _validar_versiones(versiones)
        with self._cond:
            self._versiones = v
            self._historial.clear()
            self._base = v                          # un cliente con versiones anteriores relee todo
            self._cond.notify_all()

    def versiones_actuales(self) -> Versiones:
        with self._cond:
            return self._versiones

    def _registrar_cambio(self, versiones: Versiones, secciones: tuple[str, ...]) -> None:
        with self._cond:
            # contadores monótonos: si dos hilos notifican fuera de orden, no se retrocede
            self._versiones = tuple(max(a, b) for a, b in zip(self._versiones, versiones))  # type: ignore[assignment]
            if len(self._historial) == self._historial.maxlen:
                expulsada = self._historial[0][0]
                self._base = tuple(max(a, b) for a, b in zip(self._base, expulsada))  # type: ignore[assignment]
            self._historial.append((versiones, secciones))
            self._cond.notify_all()

    # -------------------------------------------------------------- reparto
    def suscribir(self, max_cola: int = 100) -> _Suscripcion:
        if max_cola < 1:
            raise ValueError('max_cola debe ser ≥ 1')
        s = _Suscripcion(self, max_cola)
        with self._candado_subs:
            self._subs.add(s)
        return s

    def _quitar(self, s: _Suscripcion) -> None:
        with self._candado_subs:
            self._subs.discard(s)

    def _repartir(self, evento: Json) -> None:
        with self._candado_subs:
            subs = list(self._subs)
        for s in subs:
            if not s._entregar(evento):
                s._cortar()
                self._quitar(s)
                _log.info('Suscripción cortada: su cola de %d eventos se llenó', s._max)

    def publicar(self, evento: Json) -> None:
        if not isinstance(evento, dict) or not isinstance(evento.get('tipo'), str):
            raise ValueError("evento debe ser un EventoHub con 'tipo'")
        if evento['tipo'] == 'datos.cambiaron':
            v = _validar_versiones((evento.get('data_version'), evento.get('local_rev'), evento.get('img_rev', 0)))
            self._registrar_cambio(v, tuple(evento.get('secciones') or ()))
        self._repartir(evento)

    def notificar_cambio(self, versiones: Versiones, secciones: Sequence[str]) -> None:
        v = _validar_versiones(versiones)
        secs = tuple(secciones)
        desconocidas = [s for s in secs if s not in SECCIONES]
        if desconocidas:
            raise ValueError(f'secciones desconocidas: {desconocidas}')
        self._registrar_cambio(v, secs)
        self._repartir({'tipo': 'datos.cambiaron', 'data_version': v[0], 'local_rev': v[1], 'img_rev': v[2],
                        'secciones': list(secs)})

    # -------------------------------------------------------------- long-poll
    def _secciones_desde(self, vistas: Versiones) -> list[str]:
        """Unión de las secciones de los cambios posteriores a `vistas`; todas si no se puede saber con certeza."""
        b = self._base
        if vistas[0] < b[0] or vistas[1] < b[1] or (vistas[2] >= 0 and vistas[2] < b[2]):
            return list(SECCIONES)                  # sus versiones son anteriores a lo que el historial recuerda
        nuevas = [secs for (v, secs) in self._historial
                  if v[0] > vistas[0] or v[1] > vistas[1] or (vistas[2] >= 0 and v[2] > vistas[2])]
        if not nuevas:
            return list(SECCIONES)
        union = set().union(*nuevas)
        return [s for s in SECCIONES if s in union]

    def esperar_cambio(self, vistas: Versiones, timeout_s: float) -> Json | None:
        vistas = _validar_versiones(vistas)
        limite = time.monotonic() + max(0.0, timeout_s)
        with self._cond:
            while not _difiere(self._versiones, vistas):
                restante = limite - time.monotonic()
                if restante <= 0:
                    return None
                self._cond.wait(restante)
            dv, lr, ir = self._versiones
            return {'data_version': dv, 'local_rev': lr, 'img_rev': ir, 'secciones': self._secciones_desde(vistas)}


def crear_bus() -> Bus:
    return _Bus()
