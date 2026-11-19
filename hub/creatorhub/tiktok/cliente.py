"""Cliente firmado de la Open API de TikTok Shop (03 §2.1, §2.6; BUILD_SPEC §6.2 `ClienteTikTok`).

`crear_cliente(boveda, transporte, reloj, almacen, bus)` → `ClienteTikTokReal`:

- **Firma** idéntica a `server_anterior.generate_sign` (`tiktok.firma`), con el `timestamp` del reloj corregido.
- **Cubeta de fichas** global de 5 llamadas/s, ráfaga 5. Todas las esperas usan `reloj.esperar(s, cancelar)`.
- **Política de errores** de 03 §2.1 (`tiktok.politica`, configurable) con backoff *full jitter* y `Retry-After`.
- **Refresh single-flight y clasificado**: proactivo (< 5 min; < 30 min en la primera llamada de una sync) y reactivo
  (105001/105002). La red va FUERA de `candado_auth`: `gen0 = boveda.generacion` antes de salir y
  `boveda.guardar_si(gen0, …)` al volver; si alguien escribió mientras tanto, los tokens se descartan
  (`credenciales_cambiaron`). Timeout de lectura → reintento inmediato con el MISMO refresh_token (2 veces); red/5xx →
  1, 4 y 16 s y luego transitorio (auth_estado intacto); dos rechazos seguidos (60 s entre ambos) → reautorizar;
  otra cuenta o user_type ≠ 1 → reautorizar; refresh vencido → reautorizar sin llamar a TikTok.
- **Disyuntor**: como máximo un refresh cada 10 min, salvo que el access_token haya cambiado.
- **Desfase de reloj** = mediana de las últimas 5 diferencias (cabecera `Date` − reloj local).
- **Época de credenciales**: con `ctx`, `llamar()` aborta con `credenciales_cambiaron` ANTES de enviar si cambiaron la
  época o el open_id capturados al iniciar la sync.
- **api_errores**: cada error se ENCOLA y se escribe al final de `llamar()`/`refrescar()` en una transacción propia del
  escritor (nunca dentro de una transacción ajena: por el invariante 1 de 03 §2.6 nadie llama a la red con una abierta).
- **auth_estado** y **`conexion.cambio`** por el bus cuando el refresh o la política cambian la conexión. C42: al pasar a
  reautorizar o token_rechazado < 72 h después de `meta.legado_importado_at`, el aviso es el texto exacto de C42
  (salvo que la conexión simplemente haya vencido: refresh_expira_at ≤ ahora, sin refresh que terminara mal).

Extras que no están en el Protocol (los usa `auth`): `canjear_codigo(code)` (token/get), `verificar_app_secret()` y
`desfase_s`. Nunca se registra la URL firmada, las cabeceras ni un cuerpo con secretos.
"""
from __future__ import annotations

import collections
import email.utils
import logging
import random
import statistics
import threading
import urllib.parse
from typing import Any, Callable, Literal, Mapping

from .. import config
from ..boveda import APP_KEY_PUBLICA
from ..comun import limpiar
from ..errores import ErrorApi, ErrorAuthTransitorio, ErrorRed, ErrorTimeoutLectura
from ..interfaces import Almacen, Boveda, Bus, ClienteTikTok, ContextoSync, Json, Reloj, Transporte
from . import conexion as cx
from .firma import generar_firma, serializar_cuerpo
from .politica import Politica, acotar_retry_after, espera_full_jitter

_log = logging.getLogger('creatorhub.tiktok.cliente')

API = 'https://open-api.tiktokglobalshop.com'
AUTH = 'https://auth.tiktok-shops.com'
P_PERFIL = '/affiliate_creator/202508/profiles'
P_REFRESH = '/api/v2/token/refresh'
P_TOKEN = '/api/v2/token/get'

UMBRAL_PROACTIVO_S = 300            # refresh proactivo si al access le quedan < 5 min
UMBRAL_INICIO_SYNC_S = 1800         # … o < 30 min en la primera llamada de una sync
MARGEN_TOKEN_VIGENTE_S = 30         # refresh transitorio: se sigue con el token vigente si le quedan > 30 s
DISYUNTOR_S = 600                   # máx. un refresh cada 10 min (salvo que el access_token haya cambiado)
ESPERA_RECHAZO_S = 60               # 2.º intento tras un rechazo del refresh
REINTENTOS_TIMEOUT_REFRESH = 2      # timeout de lectura: reintento inmediato con el MISMO refresh_token
ESPERAS_RED_REFRESH = (1, 4, 16)    # red / 429 / 5xx / no JSON al renovar
MUESTRAS_DESFASE = 5
MAX_API_ERRORES = 500
TASA_POR_S = 5.0
RAFAGA = 5

_SQL_ERROR = ('INSERT INTO api_errores(sync_id, at, endpoint, http_status, codigo, mensaje, request_id, intento, '
              'decision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)')
_DECISION_TABLA = {'reintentar_lento': 'reintentar'}


class Cubeta:
    """Cubeta de fichas global (tasa por segundo, ráfaga). Duerme con `reloj.esperar` DENTRO del candado para que el
    ritmo global se respete entre hilos. `tomar()` → True si se canceló mientras esperaba."""

    def __init__(self, reloj: Reloj, tasa: float = TASA_POR_S, rafaga: int = RAFAGA) -> None:
        self.reloj, self.tasa, self.capacidad = reloj, float(tasa), float(rafaga)
        self.fichas = float(rafaga)
        self.t = reloj.monotonico()
        self._candado = threading.Lock()

    def tomar(self, cancelar: threading.Event | None = None) -> bool:
        with self._candado:
            ahora = self.reloj.monotonico()
            self.fichas = min(self.capacidad, self.fichas + max(0.0, ahora - self.t) * self.tasa)
            self.t = ahora
            if self.fichas >= 1.0:
                self.fichas -= 1.0
                return False
            falta = (1.0 - self.fichas) / self.tasa
            if self.reloj.esperar(falta, cancelar):
                return True
            self.t = self.reloj.monotonico()
            self.fichas = 0.0
            return False


def _codigo_entero(codigo: Any) -> int | None:
    return codigo if isinstance(codigo, int) and not isinstance(codigo, bool) else None


class ClienteTikTokReal:
    """Implementa `ClienteTikTok` (más `canjear_codigo`, `verificar_app_secret` y `desfase_s`)."""

    def __init__(self, boveda: Boveda, transporte: Transporte, reloj: Reloj, almacen: Almacen, bus: Bus,
                 politica: Politica | None = None, azar: random.Random | None = None) -> None:
        self.boveda, self.transporte, self.reloj, self.almacen, self.bus = boveda, transporte, reloj, almacen, bus
        self.politica = politica or Politica()
        self.azar = azar or random.Random()
        self.cubeta = Cubeta(reloj)
        self.lock_refresh = threading.Lock()
        self._candado = threading.Lock()                      # contadores, desfase y cola de errores
        self._local = threading.local()
        self._muestras_desfase: collections.deque[float] = collections.deque(maxlen=MUESTRAS_DESFASE)
        self.desfase_s = 0.0
        self.ultimo_refresh_ok_at: int | None = None
        self.token_de_mi_refresh: str | None = None
        self.llamadas = 0
        self.reintentos = 0
        self.refrescos = 0
        self.dormido_s = 0.0
        self._errores: list[tuple[Any, ...]] = []
        self.user_agent = f'CreatorHub/{config.VERSION}'

    # ================================================================ reloj corregido
    def ahora(self) -> int:
        return int(self.reloj.ahora() + self.desfase_s)

    def _registrar_fecha(self) -> None:
        """Mediana de las últimas 5 diferencias entre la cabecera Date de TikTok y el reloj local (03 §2.1)."""
        f = getattr(self.transporte, 'cabeceras_respuesta', None)
        if not callable(f):
            return
        try:
            fecha = (f() or {}).get('date')
            if not fecha:
                return
            servidor = email.utils.parsedate_to_datetime(fecha).timestamp()
        except (TypeError, ValueError, IndexError, OverflowError):
            return
        with self._candado:
            self._muestras_desfase.append(servidor - self.reloj.ahora())
            self.desfase_s = float(round(statistics.median(self._muestras_desfase)))

    def _cabecera(self, nombre: str) -> str | None:
        f = getattr(self.transporte, 'cabeceras_respuesta', None)
        if not callable(f):
            return None
        try:
            return (f() or {}).get(nombre)
        except Exception:  # noqa: BLE001 - una cabecera ilegible no debe tumbar la llamada
            return None

    # ================================================================ esperas y contexto
    def _ctx(self) -> ContextoSync | None:
        return getattr(self._local, 'ctx', None)

    def _esperar(self, segundos: float, path: str | None = None) -> None:
        ctx = self._ctx()
        with self._candado:
            self.dormido_s += max(0.0, segundos)
        if self.reloj.esperar(max(0.0, segundos), ctx.cancelar if ctx is not None else None):
            raise ErrorApi('cancelada', 'La sincronización se canceló', 'abortar', path=path)

    def _tomar_ficha(self, path: str) -> None:
        ctx = self._ctx()
        if self.cubeta.tomar(ctx.cancelar if ctx is not None else None):
            raise ErrorApi('cancelada', 'La sincronización se canceló', 'abortar', path=path)

    @staticmethod
    def _verificar_contexto(b: Mapping[str, Any], ctx: ContextoSync | None, path: str) -> None:
        if ctx is None:
            return
        if ctx.cancelar.is_set():
            raise ErrorApi('cancelada', 'La sincronización se canceló', 'abortar', path=path)
        if b.get('epoca_credenciales') != ctx.epoca_credenciales or (ctx.open_id and b.get('open_id') != ctx.open_id):
            raise ErrorApi('credenciales_cambiaron', 'La cuenta o las credenciales cambiaron durante la sincronización',
                           'abortar', path=path)

    def _contar(self, reintento: bool = False) -> None:
        ctx = self._ctx()
        with self._candado:
            if reintento:
                self.reintentos += 1
            else:
                self.llamadas += 1
        if ctx is not None:
            if reintento:
                ctx.reintentos += 1
            else:
                ctx.llamadas += 1

    # ================================================================ api_errores (encolados)
    def _limpio(self, texto: Any) -> str:
        """Mensaje de TikTok limpio de secretos (patrones + valores vivos de la bóveda) ANTES de crear el ErrorApi."""
        try:
            vivos = self.boveda.secretos_vivos()
        except Exception:  # noqa: BLE001
            vivos = ()
        return limpiar(str(texto or ''), vivos)[:300]

    def _encolar_error(self, path: str, http: int | None, codigo: Any, mensaje: str, request_id: Any, intento: int,
                       decision: str) -> None:
        ctx = self._ctx()
        try:
            vivos = self.boveda.secretos_vivos()
        except Exception:  # noqa: BLE001
            vivos = ()
        fila = (ctx.sync_id if ctx is not None else None, int(self.reloj.ahora()), path, http, _codigo_entero(codigo),
                limpiar(str(mensaje or ''), vivos)[:300], None if request_id is None else str(request_id)[:120],
                int(intento), _DECISION_TABLA.get(decision, decision))
        with self._candado:
            self._errores.append(fila)

    def volcar_errores(self) -> None:
        """Escribe los errores encolados en SU transacción del escritor (y deja solo los últimos 500)."""
        with self._candado:
            filas, self._errores = self._errores, []
        if not filas:
            return
        try:
            with self.almacen.escritor() as c:
                c.executemany(_SQL_ERROR, filas)
                c.execute('DELETE FROM api_errores WHERE id <= (SELECT MAX(id) - ? FROM api_errores)', (MAX_API_ERRORES,))
        except Exception as e:  # noqa: BLE001 - registrar errores nunca debe tumbar una llamada
            _log.warning('No se pudieron guardar %d errores de TikTok (%s)', len(filas), type(e).__name__)

    # ================================================================ auth_estado + conexion.cambio
    def conexion_actual(self) -> Json:
        with self.almacen.lector() as c:
            fila = cx.leer_fila(c)
        return cx.construir_conexion(self.boveda.leer(), fila, self.ahora(), self.desfase_s)

    def _publicar(self, conexion: Json) -> None:
        try:
            self.bus.publicar({'tipo': 'conexion.cambio', 'conexion': conexion})
        except Exception as e:  # noqa: BLE001
            _log.warning('No se pudo publicar conexion.cambio (%s)', type(e).__name__)

    def _actualizar_estado(self, calcular: Callable[[dict[str, Any] | None], dict[str, Any]],
                           forzar_publicar: bool = False) -> None:
        """En una transacción propia: lee la fila, aplica `calcular(fila) -> campos` y publica conexion.cambio si la
        Conexion resultante cambió (o si `forzar_publicar`)."""
        ahora = self.ahora()
        datos = self.boveda.leer()
        try:
            with self.almacen.escritor() as c:
                antes = cx.leer_fila(c)
                campos = calcular(antes)
                if campos:
                    cx.actualizar_fila(c, ahora, datos.get('app_key'), **campos)
                despues = cx.leer_fila(c)
        except Exception as e:  # noqa: BLE001
            _log.warning('No se pudo actualizar el estado de la conexión (%s)', type(e).__name__)
            return
        c_antes = cx.construir_conexion(datos, antes, ahora, self.desfase_s)
        c_despues = cx.construir_conexion(datos, despues, ahora, self.desfase_s)
        if forzar_publicar or c_antes != c_despues:
            self._publicar(c_despues)

    def _legado_reciente(self) -> bool:
        """C42: ¿se importó el archivo del panel anterior hace menos de 72 h?"""
        try:
            with self.almacen.lector() as c:
                t = cx.meta_entero(c, 'legado_importado_at')
        except Exception:  # noqa: BLE001
            return False
        return t is not None and 0 <= self.reloj.ahora() - t < cx.VENTANA_C42_S

    def _marcar_reautorizar(self, e: ErrorApi, c42: bool = True) -> None:
        """`c42=False` cuando la conexión simplemente venció (refresh_expira_at ≤ ahora: no hubo refresh que terminara
        mal), para no culpar al panel anterior de un archivo que ya venía vencido (W2a'')."""
        aviso = 'panel_anterior' if c42 and self._legado_reciente() else None
        self._actualizar_estado(lambda f: {'estado': 'reautorizar', 'refresh_aviso': aviso,
                                           'ultimo_error_codigo': _codigo_entero(e.codigo),
                                           'ultimo_error_mensaje': e.mensaje})
        _log.warning('La conexión con TikTok necesita reautorización (código %s)', e.codigo)

    def _marcar_token_rechazado(self, e: ErrorApi) -> None:
        aviso = 'panel_anterior' if self._legado_reciente() else 'token_rechazado'
        self._actualizar_estado(lambda f: {'refresh_aviso': aviso, 'ultimo_error_codigo': _codigo_entero(e.codigo),
                                           'ultimo_error_mensaje': e.mensaje})
        _log.warning('TikTok rechazó una conexión recién renovada; no se insiste hasta la próxima sincronización')

    def _marcar_sin_region(self, e: ErrorApi) -> None:
        self._actualizar_estado(lambda f: {'estado': 'cuenta_sin_region', 'ultimo_error_codigo': _codigo_entero(e.codigo),
                                           'ultimo_error_mensaje': e.mensaje})

    def _marcar_transitorio(self) -> None:
        def calcular(f: dict[str, Any] | None) -> dict[str, Any]:
            if f is not None and f.get('refresh_aviso') in ('panel_anterior', 'token_rechazado', 'renovacion_pendiente'):
                return {}
            return {'refresh_aviso': 'renovacion_pendiente'}
        self._actualizar_estado(calcular)

    def _marcar_rechazos(self, n: int) -> None:
        self._actualizar_estado(lambda f: {'refresh_rechazos_seguidos': n})

    def _marcar_refresh_ok(self) -> None:
        datos = self.boveda.leer()
        ahora = self.ahora()

        def calcular(f: dict[str, Any] | None) -> dict[str, Any]:
            campos = cx.espejo(datos)
            campos.update(ultimo_refresh_at=ahora, refresh_rechazos_seguidos=0, refresh_aviso=None,
                          ultimo_error_codigo=None, ultimo_error_mensaje=None)
            previo = (f or {}).get('estado')
            campos['estado'] = 'cuenta_sin_region' if previo == 'cuenta_sin_region' else cx.estado_base(datos)
            return campos
        self._actualizar_estado(calcular, forzar_publicar=True)

    # ================================================================ refresh
    def refrescar(self, token_visto: str | None = None) -> bool:
        """Single-flight. True si renovó; False si otro hilo ya lo hizo (el access_token ya no es `token_visto`).
        Lanza ErrorAuthTransitorio (auth_estado intacto) o ErrorApi ('reautorizar' · 'token_rechazado' ·
        'credenciales_cambiaron' · 'sin_credenciales')."""
        try:
            return self._refrescar(token_visto)
        finally:
            self.volcar_errores()

    def _refrescar(self, token_visto: str | None) -> bool:
        with self.lock_refresh:
            b = self.boveda.leer()
            if token_visto and b.get('access_token') != token_visto:
                return False
            if not b.get('refresh_token') or not b.get('app_secret'):
                raise ErrorApi('sin_credenciales', 'No hay una conexión guardada con TikTok', 'abortar', path=P_REFRESH)
            r_exp = b.get('refresh_expira_at')
            if isinstance(r_exp, int) and r_exp <= self.ahora():
                e = ErrorApi(105001, 'La conexión con TikTok venció', 'reautorizar', path=P_REFRESH)
                self._marcar_reautorizar(e, c42=False)
                raise e
            if (self.ultimo_refresh_ok_at is not None and self.ahora() - self.ultimo_refresh_ok_at < DISYUNTOR_S
                    and b.get('access_token') == self.token_de_mi_refresh):
                raise ErrorApi('token_rechazado', 'TikTok rechazó una conexión recién renovada', 'abortar',
                               path=P_REFRESH)
            # La generación de la MISMA lectura que da el refresh_token: si alguien escribe después, guardar_si lo nota.
            gen0 = b.get('generacion', self.boveda.generacion)
            q = {'app_key': b.get('app_key') or APP_KEY_PUBLICA, 'app_secret': b['app_secret'],
                 'refresh_token': b['refresh_token'], 'grant_type': 'refresh_token'}
            url = f'{AUTH}{P_REFRESH}?{urllib.parse.urlencode(q)}'
            fallos = timeouts = rechazos = 0
            intento = 0
            while True:
                intento += 1
                try:
                    http, r = self.transporte.manejar('GET', url, {'User-Agent': self.user_agent}, None)
                except ErrorTimeoutLectura as e:
                    # TikTok pudo haber rotado ya el refresh_token: se reintenta YA con el MISMO (2 veces).
                    timeouts += 1
                    self._encolar_error(P_REFRESH, None, None, f'Sin respuesta al renovar ({type(e).__name__})', None,
                                        intento, 'reintentar')
                    if timeouts <= REINTENTOS_TIMEOUT_REFRESH:
                        continue
                    self._marcar_transitorio()
                    raise ErrorAuthTransitorio('Sin respuesta de TikTok al renovar la conexión') from None
                except ErrorRed as e:
                    fallos += 1
                    self._encolar_error(P_REFRESH, None, None, f'Sin red al renovar ({type(e).__name__})', None,
                                        intento, 'reintentar')
                    if fallos <= len(ESPERAS_RED_REFRESH):
                        self._esperar(ESPERAS_RED_REFRESH[fallos - 1], P_REFRESH)
                        continue
                    self._marcar_transitorio()
                    raise ErrorAuthTransitorio(f'Sin red al renovar la conexión ({type(e).__name__})') from None
                self._registrar_fecha()
                if r is None or http == 429 or (http or 0) >= 500:
                    fallos += 1
                    self._encolar_error(P_REFRESH, http, None, 'Respuesta inválida al renovar', None, intento,
                                        'reintentar')
                    if fallos <= len(ESPERAS_RED_REFRESH):
                        self._esperar(ESPERAS_RED_REFRESH[fallos - 1], P_REFRESH)
                        continue
                    self._marcar_transitorio()
                    raise ErrorAuthTransitorio(f'TikTok no respondió bien al renovar (HTTP {http})')
                d = r.get('data') if isinstance(r.get('data'), dict) else {}
                if r.get('code') != 0 or not d.get('access_token'):
                    rechazos += 1
                    mensaje = self._limpio(r.get('message'))
                    self._encolar_error(P_REFRESH, http, r.get('code'), mensaje, r.get('request_id'),
                                        intento, 'reautorizar' if rechazos >= 2 else 'reintentar')
                    self._marcar_rechazos(rechazos)
                    if rechazos < 2:
                        self._esperar(ESPERA_RECHAZO_S, P_REFRESH)
                        continue
                    e = ErrorApi(r.get('code'), mensaje, 'reautorizar', http=http,
                                 request_id=r.get('request_id'), path=P_REFRESH)
                    self._marcar_reautorizar(e)
                    raise e
                if d.get('user_type') != 1:
                    e = ErrorApi(-2, 'La cuenta renovada no es de creador (user_type distinto de 1)', 'reautorizar',
                                 path=P_REFRESH)
                    self._marcar_reautorizar(e)
                    raise e
                if b.get('open_id') and d.get('open_id') and d['open_id'] != b['open_id']:
                    e = ErrorApi(-3, 'La conexión renovada pertenece a otra cuenta', 'reautorizar', path=P_REFRESH)
                    self._marcar_reautorizar(e)
                    raise e
                a_exp, n_exp = d.get('access_token_expire_in'), d.get('refresh_token_expire_in')
                if (not isinstance(a_exp, int) or isinstance(a_exp, bool) or not isinstance(n_exp, int)
                        or isinstance(n_exp, bool) or not d.get('refresh_token')):
                    self._marcar_transitorio()
                    raise ErrorAuthTransitorio('TikTok respondió la renovación incompleta')
                cambios: dict[str, Any] = {
                    'access_token': d['access_token'], 'refresh_token': d['refresh_token'],
                    'access_expira_at': a_exp, 'refresh_expira_at': n_exp,          # SON epoch, no duraciones
                    'granted_scopes': [str(s) for s in d.get('granted_scopes') or []]}
                if d.get('open_id'):
                    cambios['open_id'] = d['open_id']
                if d.get('seller_name') is not None:
                    cambios['seller_name'] = d.get('seller_name')
                # Persistir ANTES de usar: solo si nadie escribió (desconectar, canje, importación) mientras tanto.
                if not self.boveda.guardar_si(gen0, cambios):
                    raise ErrorApi('credenciales_cambiaron', 'Las credenciales cambiaron mientras se renovaba la conexión',
                                   'abortar', path=P_REFRESH)
                self.ultimo_refresh_ok_at, self.token_de_mi_refresh = self.ahora(), d['access_token']
                with self._candado:
                    self.refrescos += 1
                self._marcar_refresh_ok()
                _log.info('Conexión con TikTok renovada')
                return True

    def _refrescar_desde_llamada(self, token: str | None, path: str) -> None:
        """Refresh disparado por `llamar()`: traduce el transitorio y marca token_rechazado."""
        try:
            self._refrescar(token)
        except ErrorAuthTransitorio as e:
            raise ErrorApi('renovacion_pendiente', e.mensaje, 'abortar', path=path, transitorio=True) from None
        except ErrorApi as e:
            if e.codigo == 'token_rechazado':
                self._marcar_token_rechazado(e)
            raise

    # ================================================================ llamada firmada
    def llamar(self, metodo: Literal['GET', 'POST', 'DELETE'], path: str, query: Mapping[str, str] | None = None,
               body: Json | None = None, *, ctx: ContextoSync | None = None, reintentar: bool = True) -> Json:
        """data{} de la respuesta o ErrorApi(codigo, mensaje_limpio, decision, http, request_id, path, transitorio)."""
        if metodo not in ('GET', 'POST', 'DELETE'):
            raise ValueError(f'método no permitido: {metodo!r}')
        if not isinstance(path, str) or not path.startswith('/') or '?' in path or '#' in path:
            raise ValueError('path debe ser una ruta absoluta sin query')
        previo = getattr(self._local, 'ctx', None)
        self._local.ctx = ctx
        try:
            return self._llamar(metodo, path, query, body, ctx, reintentar)
        finally:
            self._local.ctx = previo
            self.volcar_errores()

    def _proactivo(self, b: Mapping[str, Any], ctx: ContextoSync | None, path: str) -> None:
        a_exp = b.get('access_expira_at')
        if not isinstance(a_exp, int) or isinstance(a_exp, bool):
            return
        umbral = UMBRAL_INICIO_SYNC_S if (ctx is not None and ctx.llamadas == 0) else UMBRAL_PROACTIVO_S
        if a_exp - self.ahora() >= umbral:
            return
        try:
            self._refrescar(b.get('access_token'))
        except ErrorAuthTransitorio as e:
            if not a_exp > self.ahora() + MARGEN_TOKEN_VIGENTE_S:          # el token vigente ya no alcanza
                raise ErrorApi('renovacion_pendiente', e.mensaje, 'abortar', path=path, transitorio=True) from None
            _log.info('No se pudo renovar la conexión; se sigue con la vigente')
        except ErrorApi as e:
            if e.codigo == 'token_rechazado':
                self._marcar_token_rechazado(e)
            raise

    def _llamar(self, metodo: str, path: str, query: Mapping[str, Any] | None, body: Json | None,
                ctx: ContextoSync | None, reintentar: bool = True) -> Json:
        b = self.boveda.leer()
        self._verificar_contexto(b, ctx, path)
        if not b.get('app_secret') or not b.get('access_token'):
            raise ErrorApi('sin_credenciales', 'Falta conectar tu cuenta de TikTok', 'abortar', path=path)
        self._proactivo(b, ctx, path)
        intento = reintentos_politica = fallos_red = 0
        refrescado = False
        while True:
            intento += 1
            b = self.boveda.leer()
            self._verificar_contexto(b, ctx, path)
            if not b.get('app_secret') or not b.get('access_token'):
                raise ErrorApi('sin_credenciales', 'Falta conectar tu cuenta de TikTok', 'abortar', path=path)
            q: dict[str, Any] = {k: v for k, v in (query or {}).items() if v not in (None, '', [])}
            q['app_key'] = b.get('app_key') or APP_KEY_PUBLICA
            q['timestamp'] = str(self.ahora())
            cuerpo = serializar_cuerpo(body)
            q['sign'] = generar_firma(path, q, cuerpo, b['app_secret'])
            url = f'{API}{path}?{urllib.parse.urlencode(q)}'
            self._tomar_ficha(path)
            self._verificar_contexto(self.boveda.leer(), ctx, path)
            self._contar()
            try:
                http, r = self.transporte.manejar(metodo, url, {'content-type': 'application/json',
                                                                'x-tts-access-token': b['access_token'],
                                                                'User-Agent': self.user_agent}, cuerpo)
            except ErrorRed as e:
                fallos_red += 1
                regla_red = self.politica.regla_red
                agotado = not reintentar or fallos_red > regla_red.reintentos
                self._encolar_error(path, None, None, f'Sin conexión ({type(e).__name__})', None, intento,
                                    'abortar' if agotado else 'reintentar')
                if not agotado:
                    self._contar(reintento=True)
                    self._esperar(espera_full_jitter(self.azar, fallos_red, regla_red.base_s, regla_red.tope_s), path)
                    continue
                raise ErrorApi(-1, f'Sin conexión con TikTok ({type(e).__name__})', 'abortar', path=path,
                               transitorio=True) from None
            self._registrar_fecha()
            codigo = r.get('code') if isinstance(r, dict) else None
            if r is not None and codigo == 0 and (reintentar or 200 <= http < 300):
                data = r.get('data')
                return dict(data) if isinstance(data, dict) else {}
            regla = self.politica.decidir(http, codigo, sin_json=r is None)
            mensaje = self._limpio((r or {}).get('message')) or ('La respuesta de TikTok no se pudo leer' if r is None
                                                                 else f'TikTok respondió con el código {codigo}')
            request_id = (r or {}).get('request_id')
            self._encolar_error(path, http, codigo, mensaje, request_id, intento, regla.decision)
            if regla.decision == 'refrescar_token' and (reintentar or http < 500):
                if not refrescado:
                    refrescado = True
                    try:
                        self._refrescar_desde_llamada(b.get('access_token'), path)
                    except ErrorApi as error_refresh:
                        # A revoked credential remains unusable even when a
                        # recent successful refresh prevents another rotation.
                        if codigo == 36009005 and error_refresh.codigo == 'token_rechazado':
                            e = ErrorApi(codigo, mensaje, 'reautorizar', http, request_id, path)
                            self._marcar_reautorizar(e)
                            raise e from None
                        raise
                    continue
                if codigo == 105002:      # recién renovado y TikTok lo da por vencido: no insistir ni pedir reconectar
                    e = ErrorApi('token_rechazado', mensaje, 'abortar', http, request_id, path)
                    self._marcar_token_rechazado(e)
                    raise e
                e = ErrorApi(codigo, mensaje, 'reautorizar', http, request_id, path)
                self._marcar_reautorizar(e)
                raise e
            if regla.decision == 'reautorizar':
                e = ErrorApi(codigo, mensaje, 'reautorizar', http, request_id, path)
                self._marcar_reautorizar(e)
                raise e
            if regla.decision == 'abortar':
                e = ErrorApi(codigo, mensaje, 'abortar', http, request_id, path)
                if regla.efecto == 'cuenta_sin_region':
                    self._marcar_sin_region(e)
                raise e
            if (reintentar and regla.decision in ('reintentar', 'reintentar_lento')
                    and reintentos_politica < regla.reintentos):
                reintentos_politica += 1
                self._contar(reintento=True)
                espera = None
                if regla.respeta_retry_after:
                    espera = acotar_retry_after(self._cabecera('retry-after'))
                if espera is None:
                    espera = espera_full_jitter(self.azar, reintentos_politica, regla.base_s, regla.tope_s)
                self._esperar(espera, path)
                continue
            transitorio = regla.decision in ('reintentar', 'reintentar_lento')
            e = ErrorApi(codigo, mensaje, 'omitir_paso' if transitorio else regla.decision, http, request_id, path,
                         transitorio=transitorio)
            if regla.efecto == 'validacion':
                e.validacion = True        # type: ignore[attr-defined]  (el sincronizador lo anota en sync_cursores)
            raise e

    # ================================================================ extras para auth
    def canjear_codigo(self, code: str) -> Json:
        """GET /api/v2/token/get (grant_type=authorized_code, literal). `data` o ErrorApi:
        'sin_internet' (la petición no salió: el code sigue sirviendo) · 'sin_respuesta' (salió y no llegó respuesta:
        el code pudo gastarse) · 'tiktok_no_disponible' (429/5xx/no JSON) · <code de TikTok> (rechazado)."""
        try:
            return self._canjear(code)
        finally:
            self.volcar_errores()

    def _canjear(self, code: str) -> Json:
        b = self.boveda.leer()
        if not b.get('app_secret'):
            raise ErrorApi('sin_credenciales', 'Falta la clave de la app', 'abortar', path=P_TOKEN)
        q = {'app_key': b.get('app_key') or APP_KEY_PUBLICA, 'app_secret': b['app_secret'], 'auth_code': code,
             'grant_type': 'authorized_code'}
        url = f'{AUTH}{P_TOKEN}?{urllib.parse.urlencode(q)}'
        fallos = intento = 0
        while True:
            intento += 1
            try:
                http, r = self.transporte.manejar('GET', url, {'User-Agent': self.user_agent}, None)
            except ErrorTimeoutLectura as e:
                self._encolar_error(P_TOKEN, None, None, f'Sin respuesta al canjear ({type(e).__name__})', None,
                                    intento, 'abortar')
                raise ErrorApi('sin_respuesta', 'TikTok no respondió a tiempo', 'abortar', path=P_TOKEN,
                               transitorio=True) from None
            except ErrorRed as e:
                fallos += 1
                self._encolar_error(P_TOKEN, None, None, f'Sin red al canjear ({type(e).__name__})', None, intento,
                                    'reintentar' if fallos <= 2 else 'abortar')
                if fallos <= 2:
                    self._esperar(float(fallos), P_TOKEN)
                    continue
                raise ErrorApi('sin_internet', 'Sin conexión con TikTok', 'abortar', path=P_TOKEN,
                               transitorio=True) from None
            self._registrar_fecha()
            if r is None or http == 429 or (http or 0) >= 500:
                self._encolar_error(P_TOKEN, http, None, 'Respuesta inválida al canjear', None, intento, 'abortar')
                raise ErrorApi('tiktok_no_disponible', f'TikTok no respondió bien (HTTP {http})', 'abortar', http=http,
                               path=P_TOKEN, transitorio=True)
            if r.get('code') != 0:
                mensaje = self._limpio(r.get('message'))
                self._encolar_error(P_TOKEN, http, r.get('code'), mensaje, r.get('request_id'), intento, 'reautorizar')
                raise ErrorApi(r.get('code'), mensaje, 'reautorizar', http=http, request_id=r.get('request_id'),
                               path=P_TOKEN)
            data = r.get('data')
            return dict(data) if isinstance(data, dict) else {}

    def verificar_app_secret(self, candidato: str) -> str:
        """GET profiles firmado con `candidato` y la conexión actual (03 §7.7). 'ok' · 'rechazada' · 'sin_tokens'.
        105001/105002 cuentan como 'ok': TikTok aceptó la firma y el problema es la conexión (se renueva después).
        Sin red o con TikTok caído: ErrorApi transitorio."""
        b = self.boveda.leer()
        if not b.get('access_token'):
            return 'sin_tokens'
        q: dict[str, Any] = {'app_key': b.get('app_key') or APP_KEY_PUBLICA, 'timestamp': str(self.ahora())}
        q['sign'] = generar_firma(P_PERFIL, q, None, candidato)
        url = f'{API}{P_PERFIL}?{urllib.parse.urlencode(q)}'
        self._tomar_ficha(P_PERFIL)
        self._contar()
        try:
            http, r = self.transporte.manejar('GET', url, {'content-type': 'application/json',
                                                           'x-tts-access-token': b['access_token'],
                                                           'User-Agent': self.user_agent}, None)
        except ErrorRed as e:
            raise ErrorApi(-1, f'Sin conexión con TikTok ({type(e).__name__})', 'abortar', path=P_PERFIL,
                           transitorio=True) from None
        self._registrar_fecha()
        if r is None or http == 429 or (http or 0) >= 500:
            raise ErrorApi('tiktok_no_disponible', f'TikTok no respondió bien (HTTP {http})', 'abortar', http=http,
                           path=P_PERFIL, transitorio=True)
        codigo = r.get('code')
        if codigo in (0, 105001, 105002):
            return 'ok'
        return 'rechazada'


def crear_cliente(boveda: Boveda, transporte: Transporte, reloj: Reloj, almacen: Almacen, bus: Bus) -> ClienteTikTok:
    """Cliente firmado (BUILD §6.3.1 paso 5). En modo demo ancla las fechas falsas de la bóveda al reloj del hub."""
    anclar = getattr(boveda, 'anclar_demo', None)
    if callable(anclar):
        anclar(reloj.ahora())
    return ClienteTikTokReal(boveda, transporte, reloj, almacen, bus)
