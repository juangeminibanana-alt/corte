"""Cola con prioridad y límite de descargas por host (03 §2.3: 4 trabajadores, máx. 4 por host). Solo stdlib.

- `ColaPrioridad`: menor número = antes (-1 firmadas, 0 muestras/avatar, 1 ventas/vitrina, 2 resto). Una clave vive
  una sola vez: si se vuelve a poner con mejor prioridad, sube; con peor o igual, se ignora. FIFO dentro de la misma
  prioridad. `sacar(timeout)` espera en tiempo real (nunca en el reloj del hub, que en las pruebas es virtual).
- `LimiteHosts`: un semáforo por host; `ranura(host, timeout)` es un gestor de contexto que entrega True si obtuvo
  lugar (False si se agotó la espera).
"""
from __future__ import annotations

import contextlib
import heapq
import itertools
import threading
from typing import Iterator


class ColaPrioridad:
    def __init__(self) -> None:
        self._monton: list[tuple[int, int, str]] = []
        self._mejor: dict[str, int] = {}
        self._turno = itertools.count()
        self._cond = threading.Condition()

    def poner(self, clave: str, prioridad: int) -> bool:
        with self._cond:
            actual = self._mejor.get(clave)
            if actual is not None and actual <= prioridad:
                return False
            self._mejor[clave] = prioridad
            heapq.heappush(self._monton, (prioridad, next(self._turno), clave))
            self._cond.notify()
            return True

    def _sacar_sin_esperar(self) -> str | None:
        while self._monton:
            prioridad, _, clave = heapq.heappop(self._monton)
            if self._mejor.get(clave) == prioridad:          # las entradas viejas (prioridad mejorada) se descartan
                del self._mejor[clave]
                return clave
        return None

    def sacar(self, timeout: float) -> str | None:
        with self._cond:
            clave = self._sacar_sin_esperar()
            if clave is None and timeout > 0:
                self._cond.wait(timeout)
                clave = self._sacar_sin_esperar()
            return clave

    def vaciar(self) -> int:
        with self._cond:
            n = len(self._mejor)
            self._monton.clear()
            self._mejor.clear()
            self._cond.notify_all()
            return n

    def despertar(self) -> None:
        with self._cond:
            self._cond.notify_all()

    def prioridad_de(self, clave: str) -> int | None:
        with self._cond:
            return self._mejor.get(clave)

    def claves(self) -> list[str]:
        """Claves pendientes en el orden en que saldrían (para pruebas y diagnóstico)."""
        with self._cond:
            vigentes = sorted(e for e in self._monton if self._mejor.get(e[2]) == e[0])
            return list(dict.fromkeys(c for _, _, c in vigentes))

    def __len__(self) -> int:
        with self._cond:
            return len(self._mejor)


class LimiteHosts:
    def __init__(self, max_por_host: int) -> None:
        if max_por_host < 1:
            raise ValueError('max_por_host debe ser ≥ 1')
        self.max_por_host = max_por_host
        self._candado = threading.Lock()
        self._sem: dict[str, threading.BoundedSemaphore] = {}
        self._activos: dict[str, int] = {}
        self.max_visto: dict[str, int] = {}               # máximo simultáneo observado por host (diagnóstico)

    def _semaforo(self, host: str) -> threading.BoundedSemaphore:
        with self._candado:
            s = self._sem.get(host)
            if s is None:
                s = self._sem[host] = threading.BoundedSemaphore(self.max_por_host)
            return s

    @contextlib.contextmanager
    def ranura(self, host: str, timeout: float | None = None) -> Iterator[bool]:
        s = self._semaforo(host)
        obtuvo = s.acquire(timeout=timeout) if timeout is not None else s.acquire()
        if not obtuvo:
            yield False
            return
        with self._candado:
            n = self._activos[host] = self._activos.get(host, 0) + 1
            self.max_visto[host] = max(self.max_visto.get(host, 0), n)
        try:
            yield True
        finally:
            with self._candado:
                self._activos[host] -= 1
            s.release()

    def activos(self, host: str) -> int:
        with self._candado:
            return self._activos.get(host, 0)
