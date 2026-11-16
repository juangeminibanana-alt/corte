"""Globos programados de la bandeja (BUILD_SPEC §6.6, C32, C44).

La interfaz calcula los recordatorios UNA vez (`calcularNotificaciones` de `@/dominio`) y los entrega con
`js_api.programar_notificaciones(lista_json)`; cada llamada REEMPLAZA todo lo programado. El shell tiene su propio
temporizador (un hilo) y muestra cada globo con `ShowBalloonTip` a su hora, también con la ventana oculta. El clic en el
globo publica `ventana.mostrar_ruta` (lo hace la ventana). El hub nunca saca un globo por un recordatorio (C44).

Reglas:
- Una notificación se muestra una sola vez por (id, at): reprogramar la misma lista no repite globos.
- Las que ya pasaron hace más de `tolerancia_s` (2 min) se descartan al programar (la PC estaba apagada o dormida).
- El temporizador despierta como máximo cada `max_espera_s` (30 s) para tolerar saltos del reloj (suspensión).
- El reloj es inyectable (`ahora`): con `--ahora` el shell usa el reloj del hub, en pruebas un reloj virtual.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

_log = logging.getLogger('creatorhub.plataforma.notificaciones')

MAX_NOTIFICACIONES = 500
MAX_ID = 200
MAX_TITULO = 63                 # NOTIFYICONDATA.szInfoTitle
MAX_TEXTO = 255                 # NOTIFYICONDATA.szInfo
MAX_RUTA = 200
MAX_JSON = 512 * 1024


@dataclass(frozen=True)
class Notificacion:
    """NotificacionProgramada de spec/ui_firmas/plataforma.d.ts."""
    id: str
    titulo: str
    texto: str
    at: int
    ruta: str


def _texto_limpio(v: Any, maximo: int) -> str | None:
    if not isinstance(v, str):
        return None
    t = ''.join(c for c in v if c == ' ' or (ord(c) >= 32 and ord(c) != 127)).strip()
    return t[:maximo] if t else None


def ruta_valida(ruta: Any) -> bool:
    """Ruta hash de la interfaz: '#/…', sin caracteres de control ni espacios."""
    return (isinstance(ruta, str) and ruta.startswith('#/') and len(ruta) <= MAX_RUTA
            and all(32 < ord(c) < 127 or ord(c) > 159 for c in ruta))


def desde_dict(d: Any) -> Notificacion | None:
    if not isinstance(d, dict):
        return None
    ident = d.get('id')
    at = d.get('at')
    titulo = _texto_limpio(d.get('titulo'), MAX_TITULO)
    texto = _texto_limpio(d.get('texto'), MAX_TEXTO)
    ruta = d.get('ruta')
    if not isinstance(ident, str) or not ident or len(ident) > MAX_ID:
        return None
    if isinstance(at, bool) or not isinstance(at, (int, float)) or at <= 0 or at != at:
        return None
    if titulo is None or texto is None or not ruta_valida(ruta):
        return None
    return Notificacion(ident, titulo, texto, int(at), ruta)


def validar_lista(lista_json: Any) -> list[Notificacion]:
    """JSON de NotificacionProgramada[] → lista válida (las entradas inválidas se descartan). ValueError si el JSON no
    es una lista."""
    if not isinstance(lista_json, str) or len(lista_json) > MAX_JSON:
        raise ValueError('lista_json debe ser texto JSON')
    datos = json.loads(lista_json)
    if not isinstance(datos, list):
        raise ValueError('lista_json debe ser una lista')
    validas: list[Notificacion] = []
    for d in datos[:MAX_NOTIFICACIONES]:
        n = desde_dict(d)
        if n is not None:
            validas.append(n)
    descartadas = len(datos) - len(validas)
    if descartadas:
        _log.info('Se descartaron %d notificaciones inválidas o de más', descartadas)
    return validas


class Programador:
    """Temporizador propio de los globos. `mostrar(n)` se llama desde el hilo del temporizador (o desde `revisar()`)."""

    def __init__(self, mostrar: Callable[[Notificacion], None], ahora: Callable[[], float] = time.time,
                 tolerancia_s: float = 120.0, max_espera_s: float = 30.0) -> None:
        self._mostrar = mostrar
        self._ahora = ahora
        self.tolerancia_s = tolerancia_s
        self.max_espera_s = max_espera_s
        self._candado = threading.Lock()
        self._pendientes: dict[str, Notificacion] = {}
        self._mostradas: set[tuple[str, int]] = set()
        self._despertar = threading.Event()
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None

    # ------------------------------------------------------------------ estado
    @property
    def pendientes(self) -> list[Notificacion]:
        with self._candado:
            return sorted(self._pendientes.values(), key=lambda n: (n.at, n.id))

    def programar(self, lista: Iterable[Notificacion]) -> int:
        """Reemplaza TODO lo programado. Devuelve cuántas quedaron pendientes."""
        ahora = self._ahora()
        lista = list(lista)
        with self._candado:
            nuevas: dict[str, Notificacion] = {}
            for n in lista:
                if n.at < ahora - self.tolerancia_s or (n.id, n.at) in self._mostradas:
                    continue
                nuevas[n.id] = n
            self._pendientes = nuevas
            cuantas = len(nuevas)
        self._despertar.set()
        return cuantas

    def proxima_espera(self) -> float | None:
        """Segundos hasta la siguiente (0 si ya toca), o None si no hay nada programado."""
        with self._candado:
            if not self._pendientes:
                return None
            siguiente = min(n.at for n in self._pendientes.values())
        return max(0.0, siguiente - self._ahora())

    def revisar(self) -> list[Notificacion]:
        """Muestra las que ya tocan (una vez cada una) y las devuelve."""
        ahora = self._ahora()
        with self._candado:
            vencidas = sorted((n for n in self._pendientes.values() if n.at <= ahora), key=lambda n: (n.at, n.id))
            for n in vencidas:
                del self._pendientes[n.id]
                self._mostradas.add((n.id, n.at))
            if len(self._mostradas) > 4 * MAX_NOTIFICACIONES:
                self._mostradas = {m for m in self._mostradas if m[1] >= ahora - 86400}
        for n in vencidas:
            try:
                self._mostrar(n)
            except Exception:  # noqa: BLE001 - un globo que falla no detiene el temporizador
                _log.exception('No se pudo mostrar una notificación')
        return vencidas

    # ------------------------------------------------------------------ hilo
    def despertar(self) -> None:
        self._despertar.set()

    def _bucle(self) -> None:
        while not self._parar.is_set():
            espera = self.proxima_espera()
            espera = self.max_espera_s if espera is None else min(espera, self.max_espera_s)
            self._despertar.wait(espera)
            self._despertar.clear()
            if self._parar.is_set():
                return
            self.revisar()

    def iniciar(self) -> None:
        if self._hilo is not None:
            return
        self._hilo = threading.Thread(target=self._bucle, name='notificaciones', daemon=True)
        self._hilo.start()

    def detener(self, tope_s: float = 2.0) -> None:
        self._parar.set()
        self._despertar.set()
        if self._hilo is not None:
            self._hilo.join(tope_s)
