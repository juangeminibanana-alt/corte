"""Planificador del hub (BUILD_SPEC §6.2 `Planificador`, §6.3.1 punto 9; 03 §2.5 y §4.4 con C36).

- Un hilo con tic de 30 s (`reloj.esperar(30, parar)`) corre las tareas registradas con `registrar_tarea(nombre, cada_s,
  fn)`: cada una a su ritmo (la primera vez en el primer tic). Una tarea que falla se registra y no detiene a las demás.
- La tarea `auto_sync` es especial: no corre «cada cada_s», sino cuando toca la sincronización automática:
  * `configurar(sync_auto, intervalo_min)`: 30 min por omisión (C36; opciones 15/30/60; `sync_auto=False` = apagada);
  * próxima = fin de la última sync + intervalo; si la última falló por `sin_internet` (o por una renovación
    pendiente), reintento a los 5, 10, 20, 40 y 60 min (y después cada 60);
  * suspendida mientras la conexión esté en `reautorizar` o `cuenta_sin_region` (se entera por `conexion.cambio`, por
    el código de error de `sync.fin` y, al arrancar, por el ErrorDominio con que el sincronizador rechaza una automática
    en ese estado); nunca mientras haya una sync en curso (`sync.progreso`).
  Un ErrorDominio de una tarea es un rechazo esperado: se registra sin traza.
  El planificador se entera de todo por el bus (`suscribir`), sin depender del sincronizador: hub.py registra
  `auto_sync` con una función que llama a `sincronizador.iniciar('incremental', 'auto')` (el sincronizador la vuelve
  completa si el barrido completo tiene más de 7 días).
- `calcular_proxima_auto()` es la MISMA regla que usa el sincronizador para `SyncEstado.proxima_auto_at`.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable

from .errores import ErrorDominio
from .interfaces import Bus, Json, Planificador, Reloj

_log = logging.getLogger('creatorhub.planificador')

TIC_S = 30
SYNC_AUTO_OMISION = True
INTERVALO_OMISION_MIN = 30                       # C36 (01 §5.6 manda sobre los 60 de 03 §4.4)
INTERVALOS_MIN: tuple[int, ...] = (15, 30, 60)
REINTENTOS_MIN: tuple[int, ...] = (5, 10, 20, 40, 60)
CODIGOS_REINTENTO: frozenset[str] = frozenset({'sin_internet', 'renovacion_pendiente'})
ESTADOS_SUSPENDIDOS: frozenset[str] = frozenset({'reautorizar', 'cuenta_sin_region'})
# ErrorDominio con que el sincronizador rechaza una automática -> estado de la conexión que suspende las siguientes
SUSPENDE_POR_CODIGO: dict[str, str] = {'reautorizar': 'reautorizar', 'sin_permiso_tiktok': 'cuenta_sin_region'}
TAREA_AUTO_SYNC = 'auto_sync'
# Una sync publica sync.progreso al menos en cada paso; tanto silencio = se perdió su sync.fin (no bloquear las automáticas)
SIN_NOTICIAS_DE_SYNC_S = 2 * 3600


def calcular_proxima_auto(*, sync_auto: bool, intervalo_min: int, ultimo_fin_at: int | None, ultimo_codigo: str | None,
                          fallos_seguidos: int, auth_estado: str | None,
                          referencia_at: int | None = None) -> int | None:
    """Epoch de la próxima sincronización automática o None (apagada, suspendida o sin referencia).

    ultimo_fin_at  : fin de la última sync (cualquier origen); si no hay, `referencia_at` (p. ej. el arranque).
    ultimo_codigo  : código de error de la última sync si terminó en error (None si terminó bien).
    fallos_seguidos: syncs seguidas que terminaron en error con un código de CODIGOS_REINTENTO.
    auth_estado    : estado de la conexión (auth_estado.estado). Si es desconocido (None), un último código
                     'reautorizar'/'cuenta_sin_region' también suspende.
    """
    if not sync_auto:
        return None
    if auth_estado in ESTADOS_SUSPENDIDOS or (auth_estado is None and ultimo_codigo in ESTADOS_SUSPENDIDOS):
        return None
    base = ultimo_fin_at if ultimo_fin_at is not None else referencia_at
    if base is None:
        return None
    if ultimo_codigo in CODIGOS_REINTENTO and fallos_seguidos > 0:
        return base + REINTENTOS_MIN[min(fallos_seguidos, len(REINTENTOS_MIN)) - 1] * 60
    intervalo = intervalo_min if intervalo_min in INTERVALOS_MIN else INTERVALO_OMISION_MIN
    return base + intervalo * 60


@dataclass
class _Tarea:
    nombre: str
    cada_s: int
    fn: Callable[[], None]
    proxima_at: int | None = None
    ejecuciones: int = 0
    fallos: int = 0


class _Planificador:
    """Implementa `Planificador`. `tic()` y `procesar_evento()` son públicos para probar sin hilos con un reloj virtual."""

    def __init__(self, reloj: Reloj, bus: Bus) -> None:
        self._reloj = reloj
        self._bus = bus
        self._candado = threading.RLock()
        self._tareas: dict[str, _Tarea] = {}
        self._sync_auto = SYNC_AUTO_OMISION
        self._intervalo_min = INTERVALO_OMISION_MIN
        self._auth_estado: str | None = None
        self._ultimo_fin_at: int | None = None
        self._ultimo_codigo: str | None = None
        self._fallos_seguidos = 0
        self._referencia_at: int | None = None
        self._sync_en_curso = False
        self._progreso_visto_at = 0
        self._parar = threading.Event()
        self._hilos: list[threading.Thread] = []
        self._suscripcion: Any = None
        self._activo = False

    # ------------------------------------------------------------------ Protocol
    def iniciar(self) -> None:
        with self._candado:
            if self._activo:
                return
            self._activo = True
            self._parar.clear()
            if self._referencia_at is None:
                self._referencia_at = self._reloj.ahora()
            self._suscripcion = self._bus.suscribir(max_cola=1000)
            self._hilos = [threading.Thread(target=self._bucle_tic, name='planificador-tic', daemon=True),
                           threading.Thread(target=self._bucle_eventos, name='planificador-eventos', daemon=True)]
        for h in self._hilos:
            h.start()

    def detener(self) -> None:
        with self._candado:
            if not self._activo:
                return
            self._activo = False
            self._parar.set()
            sus, hilos = self._suscripcion, list(self._hilos)
            self._suscripcion, self._hilos = None, []
        if sus is not None:
            sus.cerrar()
        for h in hilos:
            if h is not threading.current_thread():
                h.join(5)

    def configurar(self, sync_auto: bool, intervalo_min: int) -> None:
        """C36: 15/30/60 min. Un valor fuera de la lista (p. ej. un config.json viejo con 180) no tumba el arranque:
        se registra y se usa el de omisión (30)."""
        if intervalo_min not in INTERVALOS_MIN:
            _log.warning('Intervalo de sincronización %r no válido (se admite 15, 30 o 60): se usa %d',
                         intervalo_min, INTERVALO_OMISION_MIN)
            intervalo_min = INTERVALO_OMISION_MIN
        with self._candado:
            self._sync_auto = bool(sync_auto)
            self._intervalo_min = int(intervalo_min)

    def registrar_tarea(self, nombre: str, cada_s: int, fn: Callable[[], None]) -> None:
        if not nombre or cada_s <= 0 or not callable(fn):
            raise ValueError('tarea inválida: hace falta nombre, cada_s > 0 y una función')
        with self._candado:
            self._tareas[nombre] = _Tarea(nombre=nombre, cada_s=int(cada_s), fn=fn)

    # ------------------------------------------------------------------ consultas (no son del Protocol)
    def proxima_auto_at(self) -> int | None:
        with self._candado:
            return calcular_proxima_auto(sync_auto=self._sync_auto, intervalo_min=self._intervalo_min,
                                         ultimo_fin_at=self._ultimo_fin_at, ultimo_codigo=self._ultimo_codigo,
                                         fallos_seguidos=self._fallos_seguidos, auth_estado=self._auth_estado,
                                         referencia_at=self._referencia_at)

    def configuracion(self) -> tuple[bool, int]:
        with self._candado:
            return self._sync_auto, self._intervalo_min

    def suspendido(self) -> bool:
        with self._candado:
            return self._auth_estado in ESTADOS_SUSPENDIDOS or (
                self._auth_estado is None and self._ultimo_codigo in ESTADOS_SUSPENDIDOS)

    # ------------------------------------------------------------------ eventos del bus
    def procesar_evento(self, evento: Json) -> None:
        tipo = evento.get('tipo')
        with self._candado:
            if tipo == 'sync.progreso':
                self._sync_en_curso = True
                self._progreso_visto_at = self._reloj.ahora()
            elif tipo == 'sync.fin':
                estado = evento.get('estado') or {}
                self._sync_en_curso = False
                err = estado.get('ultimo_error') if estado.get('ultima_estado') == 'error' else None
                codigo = (err or {}).get('codigo')
                self._ultimo_fin_at = int((err or {}).get('at') or self._reloj.ahora())
                self._ultimo_codigo = codigo
                if codigo in CODIGOS_REINTENTO:
                    self._fallos_seguidos += 1
                else:
                    self._fallos_seguidos = 0
                if codigo in ESTADOS_SUSPENDIDOS:
                    self._auth_estado = codigo
                elif estado.get('ultima_estado') in ('ok', 'parcial') and self._auth_estado in ESTADOS_SUSPENDIDOS:
                    self._auth_estado = 'conectada'
            elif tipo == 'conexion.cambio':
                self._auth_estado = (evento.get('conexion') or {}).get('estado')

    def _bucle_eventos(self) -> None:
        while not self._parar.is_set():
            sus = self._suscripcion
            if sus is None:
                return
            try:
                ev = sus.siguiente(1.0)
            except Exception:
                _log.exception('Error leyendo el bus en el planificador')
                continue
            if ev is not None:
                self.procesar_evento(ev)
            elif getattr(sus, 'cortada', False) and not self._parar.is_set():
                _log.info('Suscripción del planificador cortada: se vuelve a suscribir')
                with self._candado:
                    if self._activo:
                        self._suscripcion = self._bus.suscribir(max_cola=1000)
                        # pudo perderse un sync.fin: no quedarse «con una sync en curso» para siempre (si de verdad
                        # hay una, iniciar() responde ya_en_curso y el siguiente sync.progreso lo vuelve a marcar)
                        self._sync_en_curso = False

    # ------------------------------------------------------------------ tic
    def _bucle_tic(self) -> None:
        while not self._reloj.esperar(TIC_S, self._parar):
            try:
                self.tic()
            except Exception:
                _log.exception('Error en el tic del planificador')

    def tic(self) -> list[str]:
        """Corre lo que toque AHORA. Devuelve los nombres de las tareas ejecutadas (para pruebas y registro)."""
        ahora = self._reloj.ahora()
        corridas: list[str] = []
        with self._candado:
            if self._referencia_at is None:
                self._referencia_at = ahora
            pendientes = []
            for t in self._tareas.values():
                if t.nombre == TAREA_AUTO_SYNC:
                    continue
                if t.proxima_at is None or ahora >= t.proxima_at:
                    t.proxima_at = ahora + t.cada_s
                    pendientes.append(t)
            auto = self._tareas.get(TAREA_AUTO_SYNC)
            disparar_auto = False
            if self._sync_en_curso and ahora - self._progreso_visto_at > SIN_NOTICIAS_DE_SYNC_S:
                _log.info('Sin noticias de la sincronización en curso desde hace más de %d s', SIN_NOTICIAS_DE_SYNC_S)
                self._sync_en_curso = False
            if auto is not None and not self._sync_en_curso:
                proxima = self.proxima_auto_at()
                if proxima is not None and ahora >= proxima:
                    disparar_auto = True
                    # Provisional hasta que llegue su sync.fin: evita dispararla en cada tic si no arranca.
                    self._ultimo_fin_at = ahora
                    self._ultimo_codigo = None if self._ultimo_codigo not in CODIGOS_REINTENTO else self._ultimo_codigo
        for t in pendientes:
            if self._ejecutar(t):
                corridas.append(t.nombre)
        if disparar_auto and auto is not None and self._ejecutar(auto):
            corridas.append(auto.nombre)
        return corridas

    def _ejecutar(self, t: _Tarea) -> bool:
        try:
            t.fn()
            t.ejecuciones += 1
            return True
        except ErrorDominio as e:
            # Rechazo esperado (p. ej. la sincronización automática con la conexión vencida, 03 §4.4): sin traza.
            t.fallos += 1
            _log.info('La tarea %s no corrió (%s)', t.nombre, e.codigo)
            if t.nombre == TAREA_AUTO_SYNC and e.codigo in SUSPENDE_POR_CODIGO:
                with self._candado:
                    self._auth_estado = SUSPENDE_POR_CODIGO[e.codigo]
            return False
        except Exception:
            t.fallos += 1
            _log.exception('La tarea %s falló', t.nombre)
            return False


def crear_planificador(reloj: Reloj, bus: Bus) -> Planificador:
    return _Planificador(reloj, bus)
