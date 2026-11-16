"""Servicio de imágenes del hub: implementa `interfaces.Imagenes` (BUILD_SPEC §6.2, §6.3.3, C3, C11, C39, C45; 03 §2.3).

Resumen de reglas (cada una tiene su prueba en hub/pruebas/test_imagenes_*.py):
- `encolar(pedidos)`: valida tipo/ref_id/URL y, en UNA transacción propia del escritor, registra `url_origen` y
  `url_huella` (estado 'pendiente' si es nueva o si cambió la huella). Funciona aunque los trabajadores no hayan
  arrancado: la analítica ya puede emitir '?v=0'. Nunca se llama con el escritor tomado (lo toma ella).
- `iniciar()` (hub.py, 2 s después de «listo»): 4 trabajadores con prioridad (-1 firmadas, 0 muestras/avatar,
  1 ventas/vitrina, 2 resto), máx. 4 descargas por host, y un hilo de control (lotes, reintentos). PIL solo se carga
  dentro de un trabajador (o del hilo de una descarga síncrona), al procesar la primera imagen.
- Descarga: el `Descargador` inyectado o `DescargadorHttps` (lista blanca, ≤ 3 redirecciones, ≤ 10 MB, image/*).
  La URL se valida contra la lista blanca SIEMPRE, también con un descargador inyectado (modo demo).
- `servir()`: v vigente -> `immutable`; v=0 u otra -> `no-cache`; si no está en caché, descarga síncrona con tope de
  5 s; si falla, 404 `no-store`. La ruta sale de `ruta_rel` y su realpath debe quedar dentro de la caché. Una fila en
  'error' que falló hace menos de 30 s responde 404 sin volver a descargar (no se insiste en cada petición).
- Invalidación (C45): cuando termina un lote (2 s sin descargas nuevas y la cola vacía; con cola larga, como máximo
  cada 10 s) -> `almacen.subir_img_rev(conn)` en una transacción y luego
  `bus.notificar_cambio(almacen.versiones(), ['productos','videos','tiendas','muestras'])` (+ 'cuenta' si el lote
  trae el avatar). Un lote = un solo `datos.cambiaron`.
- LRU de `max_mb` por `ultimo_acceso_at` (que se acumula en memoria y se vuelca con `volcar_accesos()`); nunca expulsa
  las imágenes de muestras pendientes ni el avatar. También expulsa lo que lleva 90 días sin uso y borra huérfanos.
  Una expulsada queda 'pendiente' con `descargada_at` (solo se vuelve a bajar si alguien la pide). Al cerrar cada lote,
  si la caché pasa del último tope (400 MB por omisión), se purga sola.
- Errores: 3 reintentos (15 s, 60 s, 5 min) y luego cada 24 h. Las fallas permanentes (host fuera de la lista,
  > 10 MB, bomba, formato no permitido) dejan la fila 'bloqueada' hasta que cambie la URL.
- Nunca se registra una URL (las del avatar llevan firma): solo la clave de la imagen y un código corto.
- Rev. 4 (15/11): tipos DIFERIDOS 'g' (galería de vitrina, '<product_id>-<n>') y 'm' (producto parecido). `encolar`
  solo registra su URL (nunca entran a la cola de fondo, ni al arrancar ni por reintentos); se bajan cuando alguien
  las pide con `servir()` (descarga síncrona con el mismo tope de 5 s y, si no hay lugar, la termina un trabajador).
"""
from __future__ import annotations

import heapq
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .. import config
from ..errores import ErrorApi
from ..interfaces import Almacen, Bus, Descargador, Imagenes, Json, PedidoImagen, Reloj, RespuestaImagen
from . import claves as k
from . import proceso
from .cola import ColaPrioridad, LimiteHosts
from .descarga import DescargadorHttps

_log = logging.getLogger('creatorhub.imagenes')

TRABAJADORES = 4
MAX_POR_HOST = 4
TOPE_SINCRONO_S = 5.0
ANTIRREBOTE_S = 2.0
LOTE_MAX_S = 10.0
TIC_S = 0.05                                   # tiempo REAL entre revisiones del hilo de control
ESPERA_COLA_S = 0.2                            # tiempo REAL que un trabajador espera trabajo antes de revisar la parada
REINTENTOS_S: tuple[float, ...] = (15.0, 60.0, 300.0)
REINTENTO_LARGO_S = 86400
REVISION_ERRORES_S = 600.0                     # cada cuánto (reloj del hub) se buscan errores con 24 h cumplidas
PAUSA_SINCRONA_TRAS_ERROR_S = 30.0             # no repetir una descarga síncrona fallida en cada petición
DIAS_SIN_USO = 90
TOPE_DETENER_S = 3.0
SECCIONES_LOTE: tuple[str, ...] = ('productos', 'videos', 'tiendas', 'muestras')
GRUPOS_PENDIENTES: tuple[str, ...] = ('por_vencer', 'vencida', 'pausada')
CACHE_INMUTABLE = 'private, max-age=31536000, immutable'
CACHE_REVALIDAR = 'no-cache'
CACHE_NUNCA = 'no-store'
_RANGO_FUENTE = {'ficha': 0, 'perfil': 0, 'vitrina': 1}       # cascada C39: ficha -> vitrina

_SQL_FILA = ('SELECT img_key, tipo, ref_id, url_origen, url_huella, version, ruta_rel, mime, ancho, alto, bytes, lqip, '
             'color, estado, intentos, ultimo_error, descargada_at, ultimo_acceso_at, actualizado_at '
             'FROM imagenes WHERE img_key = ?')
_SQL_PENDIENTES = """
SELECT i.img_key, i.url_origen,
       CASE WHEN i.tipo IN ('a', 'v') THEN 0
            WHEN EXISTS (SELECT 1 FROM muestras m WHERE m.product_id = i.ref_id) THEN 0
            WHEN EXISTS (SELECT 1 FROM vitrina v WHERE v.product_id = i.ref_id)
              OR EXISTS (SELECT 1 FROM orden_lineas l WHERE l.product_id = i.ref_id) THEN 1
            ELSE 2 END AS prioridad
FROM imagenes i
WHERE i.url_origen IS NOT NULL AND i.tipo IN ('p', 'a', 'v')
  AND ((i.estado = 'pendiente' AND i.descargada_at IS NULL)
       OR (i.estado = 'error' AND (i.intentos <= ? OR i.actualizado_at <= ?)))
"""
_SQL_PROTEGIDAS = f"""
SELECT DISTINCT product_id FROM v_muestras
WHERE pendiente OR grupo IN {GRUPOS_PENDIENTES!r}
"""


def _respuesta_404() -> RespuestaImagen:
    return RespuestaImagen(404, [('Cache-Control', CACHE_NUNCA)])


class _Descartar(Exception):
    """La fila cambió o se borró mientras se descargaba: el resultado ya no sirve."""


@dataclass
class _Pedido:
    tipo: str
    ref_id: str
    url: str
    huella: str
    prioridad: int
    rango: int
    fuente: str


class _Imagenes:
    """Implementa interfaces.Imagenes."""

    def __init__(self, almacen: Almacen, bus: Bus, reloj: Reloj, raiz_cache: str,
                 descargar: Descargador | None) -> None:
        self._almacen = almacen
        self._bus = bus
        self._reloj = reloj
        self.raiz = os.path.abspath(raiz_cache)
        os.makedirs(self.raiz, exist_ok=True)
        self._descargar: Descargador = descargar if descargar is not None else DescargadorHttps()
        self.n_trabajadores = TRABAJADORES
        self._cola = ColaPrioridad()
        self.hosts = LimiteHosts(MAX_POR_HOST)
        self._candado = threading.Lock()                # estado en memoria (nunca se toma otro candado dentro)
        self._candado_archivos = threading.Lock()       # escribir/borrar archivos + su fila (orden: este -> escritor)
        self._en_vuelo: dict[str, threading.Event] = {}
        self._repetir: set[str] = set()
        self._accesos: dict[str, int] = {}
        self._reintentos: list[tuple[float, str]] = []
        self._generacion = 0
        self._lote_n = 0
        self._lote_primero = 0.0
        self._lote_ultimo = 0.0
        self._lote_avatar = False
        self._proxima_revision = 0.0
        self._max_mb = config.IMAGENES_MAX_MB_PC
        self._parar = threading.Event()
        self._hilos: list[threading.Thread] = []
        self._activo = False

    # ================================================================== ciclo de vida
    def iniciar(self) -> None:
        with self._candado:
            if self._activo:
                return
            self._activo = True
            # Un evento de parada NUEVO por arranque: un hilo de la vuelta anterior que no alcanzó a salir dentro del
            # tope de detener() conserva su evento ya puesto y termina; nunca queda como trabajador de más.
            parar = self._parar = threading.Event()
        self._cargar_pendientes()
        hilos = [threading.Thread(target=self._bucle_trabajador, args=(parar,), name=f'imagenes-trabajador-{i + 1}',
                                  daemon=True) for i in range(self.n_trabajadores)]
        hilos.append(threading.Thread(target=self._bucle_control, args=(parar,), name='imagenes-control', daemon=True))
        with self._candado:
            self._hilos = hilos
        for h in hilos:
            h.start()
        _log.info('Imágenes: %d trabajadores en marcha (%d en cola)', self.n_trabajadores, len(self._cola))

    def detener(self) -> None:
        with self._candado:
            hilos, self._hilos = self._hilos, []
            self._activo = False
            parar = self._parar
        parar.set()
        self._cola.despertar()
        limite = time.monotonic() + TOPE_DETENER_S            # tope en tiempo real, aunque el reloj del hub sea virtual
        for h in hilos:
            h.join(max(0.0, limite - time.monotonic()))
        self._cerrar_lote_si_toca(forzar=True)
        self.volcar_accesos()

    # ================================================================== encolar
    def _validar(self, p: Any) -> tuple[str, _Pedido | None] | None:
        tipo, ref_id = getattr(p, 'tipo', None), getattr(p, 'ref_id', None)
        if tipo not in k.TIPOS or not k.ref_valido(tipo, ref_id):
            _log.warning('Pedido de imagen ignorado: tipo o id inválido')
            return None
        clave = k.clave(tipo, ref_id)
        url = getattr(p, 'url', None)
        if k.url_permitida(url) is None:
            _log.warning('Imagen %s: URL fuera de la lista blanca o sin https; no se descarga', clave)
            return clave, None
        try:
            prioridad = max(0, min(2, int(getattr(p, 'prioridad', 2))))
        except (TypeError, ValueError):
            prioridad = 2
        if k.es_firmada(url):
            prioridad = -1                                  # URL que caduca (avatar): primero que todo
        fuente = str(getattr(p, 'fuente', '') or '')
        return clave, _Pedido(tipo, ref_id, url, k.huella_url(url), prioridad, _RANGO_FUENTE.get(fuente, 1), fuente)

    def encolar(self, pedidos: Sequence[PedidoImagen]) -> None:
        validos: dict[str, _Pedido] = {}
        bloqueados: set[str] = set()
        for p in pedidos:
            r = self._validar(p)
            if r is None:
                continue
            clave, pedido = r
            if pedido is None:
                bloqueados.add(clave)
                continue
            previo = validos.get(clave)
            if previo is not None:
                pedido.prioridad = min(pedido.prioridad, previo.prioridad)
                if previo.rango < pedido.rango:            # en el mismo lote, la ficha gana a la vitrina (C39)
                    previo.prioridad = pedido.prioridad
                    continue
            validos[clave] = pedido
            bloqueados.discard(clave)
        bloqueados -= set(validos)
        if not validos and not bloqueados:
            return
        ahora = self._reloj.ahora()
        a_encolar: list[tuple[str, int]] = []
        with self._almacen.escritor() as conn:
            for clave, pd in validos.items():
                if self._registrar_pedido(conn, clave, pd, ahora):
                    a_encolar.append((clave, pd.prioridad))
            for clave in bloqueados:
                tipo, ref_id = k.partes(clave)
                conn.execute("INSERT OR IGNORE INTO imagenes(img_key, tipo, ref_id, estado, intentos, ultimo_error, "
                             "actualizado_at) VALUES (?, ?, ?, 'bloqueada', 0, 'host_no_permitido', ?)",
                             (clave, tipo, ref_id, ahora))
        for clave, prioridad in a_encolar:
            self._cola.poner(clave, prioridad)

    def _registrar_pedido(self, conn: sqlite3.Connection, clave: str, pd: _Pedido, ahora: int) -> bool:
        """Escribe url_origen/url_huella. -> True si hay que descargar (nunca para los tipos diferidos 'g' y 'm')."""
        quiere = self._registrar_url(conn, clave, pd, ahora)
        return quiere and not k.es_diferida(pd.tipo)

    def _registrar_url(self, conn: sqlite3.Connection, clave: str, pd: _Pedido, ahora: int) -> bool:
        fila = conn.execute('SELECT url_origen, url_huella, estado, descargada_at FROM imagenes WHERE img_key = ?',
                            (clave,)).fetchone()
        if fila is None:
            conn.execute("INSERT INTO imagenes(img_key, tipo, ref_id, url_origen, url_huella, estado, intentos, "
                         "actualizado_at) VALUES (?, ?, ?, ?, ?, 'pendiente', 0, ?)",
                         (clave, pd.tipo, pd.ref_id, pd.url, pd.huella, ahora))
            return True
        url_actual, huella_actual, estado, descargada_at = fila[0], fila[1], fila[2], fila[3]
        if pd.fuente == 'vitrina' and pd.tipo == 'p' and url_actual and huella_actual != pd.huella:
            ficha = conn.execute('SELECT imagen_url FROM productos WHERE product_id = ?', (pd.ref_id,)).fetchone()
            if (ficha is not None and k.url_permitida(ficha[0]) is not None
                    and k.huella_url(ficha[0]) == huella_actual):
                return False                                # la foto vigente es la de la ficha: manda (C39)
        if huella_actual != pd.huella:
            conn.execute("UPDATE imagenes SET url_origen = ?, url_huella = ?, estado = 'pendiente', intentos = 0, "
                         "ultimo_error = NULL, descargada_at = NULL, actualizado_at = ? WHERE img_key = ?",
                         (pd.url, pd.huella, ahora, clave))
            return True
        if url_actual != pd.url:                            # misma imagen, firma nueva
            if estado == 'error':
                conn.execute('UPDATE imagenes SET url_origen = ?, intentos = 0, ultimo_error = NULL, actualizado_at = ? '
                             'WHERE img_key = ?', (pd.url, ahora, clave))
                return True
            conn.execute('UPDATE imagenes SET url_origen = ?, actualizado_at = ? WHERE img_key = ?',
                         (pd.url, ahora, clave))
        return estado == 'pendiente' and descargada_at is None

    def _cargar_pendientes(self) -> None:
        ahora = self._reloj.ahora()
        try:
            with self._almacen.lector() as conn:
                filas = conn.execute(_SQL_PENDIENTES, (len(REINTENTOS_S), ahora - REINTENTO_LARGO_S)).fetchall()
        except sqlite3.Error as e:
            _log.warning('Imágenes: no se pudieron leer las pendientes (%s)', type(e).__name__)
            filas = []
        for clave, url, prioridad in filas:
            self._cola.poner(clave, -1 if k.es_firmada(url or '') else int(prioridad))
        self._proxima_revision = self._reloj.monotonico() + REVISION_ERRORES_S

    # ================================================================== trabajadores
    def _bucle_trabajador(self, parar: threading.Event) -> None:
        while not parar.is_set():
            clave = self._cola.sacar(ESPERA_COLA_S)
            if clave is None:
                continue
            if parar.is_set():
                self._cola.poner(clave, 2)                  # se sacó justo al detener: que no se pierda (al volver a
                break                                       # iniciar, _cargar_pendientes le devuelve su prioridad)
            ev = self._tomar(clave)
            if ev is None:
                continue                                    # otra descarga de la misma clave ya está en curso
            try:
                self._trabajar(clave, sincrona=False)
            except Exception as e:  # noqa: BLE001 - un trabajador nunca muere por una imagen
                _log.error('Imagen %s: falla inesperada (%s)', clave, type(e).__name__)
            finally:
                self._soltar(clave, ev)

    def _tomar(self, clave: str) -> threading.Event | None:
        """Reserva la clave. Si ya hay una descarga en curso, la clave se vuelve a encolar cuando esa termine (puede
        haber cambiado la URL mientras tanto); por eso `_tomar` y `_soltar` comparten el mismo candado."""
        with self._candado:
            if clave in self._en_vuelo:
                self._repetir.add(clave)
                return None
            ev = self._en_vuelo[clave] = threading.Event()
            return ev

    def _soltar(self, clave: str, ev: threading.Event) -> None:
        with self._candado:
            if self._en_vuelo.get(clave) is ev:
                del self._en_vuelo[clave]
            repetir = clave in self._repetir
            self._repetir.discard(clave)
        if repetir:
            self._cola.poner(clave, 0)
        ev.set()

    def _fila(self, clave: str) -> sqlite3.Row | None:
        with self._almacen.lector() as conn:
            return conn.execute(_SQL_FILA, (clave,)).fetchone()

    def _trabajar(self, clave: str, sincrona: bool) -> str:
        """Descarga, verifica, genera variantes y guarda. Nunca toca la red dentro de una transacción.
        -> 'ok' | 'fallo' | 'nada' (no había nada que hacer o el resultado se descartó) | 'sin_lugar'."""
        generacion = self._generacion
        epoca = self._almacen.epoca()
        fila = self._fila(clave)
        if fila is None or not fila['url_origen'] or fila['estado'] in ('ok', 'bloqueada'):
            return 'nada'
        url, huella = fila['url_origen'], fila['url_huella']
        host = k.url_permitida(url)
        if host is None:
            self._registrar_fallo(clave, huella, epoca, k.ErrorImagen('host_no_permitido', permanente=True))
            return 'fallo'
        with self.hosts.ranura(host, TOPE_SINCRONO_S if sincrona else None) as hay_lugar:
            if not hay_lugar:
                return 'sin_lugar'                          # la petición síncrona ya se rindió; no cuenta como falla
            try:
                og = self._descargar(url)
            except k.ErrorImagen as e:
                self._registrar_fallo(clave, huella, epoca, e)
                return 'fallo'
            except Exception as e:  # noqa: BLE001 - descargador inyectado (demo): cualquier falla es transitoria
                _log.info('Imagen %s: el descargador falló (%s)', clave, type(e).__name__)
                self._registrar_fallo(clave, huella, epoca, k.ErrorImagen('descarga_fallida'))
                return 'fallo'
        try:
            if not isinstance(og, (bytes, bytearray, memoryview)):
                raise k.ErrorImagen('respuesta_invalida')
            res = proceso.procesar(bytes(og))
        except k.ErrorImagen as e:
            self._registrar_fallo(clave, huella, epoca, e)
            return 'fallo'
        except Exception as e:  # noqa: BLE001 - Pillow puede lanzar otras cosas con archivos raros
            _log.info('Imagen %s: no se pudo procesar (%s)', clave, type(e).__name__)
            self._registrar_fallo(clave, huella, epoca, k.ErrorImagen('imagen_invalida'))
            return 'fallo'
        if generacion != self._generacion:
            return 'nada'                                   # vaciar_cola() mientras tanto (cambio de cuenta, borrar)
        return 'ok' if self._guardar(clave, huella, epoca, bytes(og), res) else 'nada'

    def _escribir(self, ruta: str, datos: bytes) -> None:
        nuevo = f'{ruta}.nuevo-{threading.get_ident()}'
        try:
            with open(nuevo, 'wb') as f:
                f.write(datos)
            for intento in range(10):
                try:
                    os.replace(nuevo, ruta)
                    return
                except PermissionError:
                    if intento == 9:
                        raise
                    time.sleep(0.02 * (intento + 1))       # antivirus o indexador con el archivo abierto un instante
        except BaseException:
            try:
                os.remove(nuevo)
            except OSError:
                pass
            raise

    def _borrar_archivos(self, ruta_rel: str | None, reintentos: int = 0) -> None:
        """Borra el original y sus variantes. En Windows un archivo recién escrito puede seguir abierto un instante
        (antivirus, indexador) o lo está enviando el servidor: se reintenta un poco y, si no, lo limpia purgar()."""
        if not ruta_rel:
            return
        for rel in k.rutas_rel_de(ruta_rel):
            ruta = k.ruta_segura(self.raiz, rel)
            if ruta is None:
                continue
            for intento in range(reintentos + 1):
                try:
                    os.remove(ruta)
                    break
                except FileNotFoundError:
                    break
                except OSError:
                    if intento < reintentos:
                        time.sleep(0.05 * (intento + 1))

    def _guardar(self, clave: str, huella: str, epoca: int, og: bytes, res: proceso.Procesada) -> bool:
        tipo, ref_id = k.partes(clave)
        ruta_og = k.ruta_rel_og(tipo, ref_id, res.version, res.ext)
        archivos = {ruta_og: og}
        archivos.update({k.ruta_rel_variante(ruta_og, n): v.datos for n, v in res.variantes.items()})
        total = sum(len(d) for d in archivos.values())
        ahora = self._reloj.ahora()
        escritos: list[str] = []
        vieja: str | None = None
        with self._candado_archivos:
            try:
                for rel, datos in archivos.items():
                    ruta = k.ruta_segura(self.raiz, rel)
                    if ruta is None:
                        raise _Descartar()
                    os.makedirs(os.path.dirname(ruta), exist_ok=True)
                    if os.path.isfile(ruta) and os.path.getsize(ruta) == len(datos):
                        continue                             # misma versión ya en disco (la versión va en el nombre)
                    self._escribir(ruta, datos)
                    escritos.append(ruta)
                with self._almacen.escritor(epoca) as conn:
                    previa = conn.execute('SELECT url_huella, ruta_rel FROM imagenes WHERE img_key = ?',
                                          (clave,)).fetchone()
                    if previa is None or previa[0] != huella:
                        raise _Descartar()
                    vieja = previa[1]
                    conn.execute("UPDATE imagenes SET version = ?, ruta_rel = ?, mime = ?, ancho = ?, alto = ?, "
                                 "bytes = ?, lqip = ?, color = ?, estado = 'ok', intentos = 0, ultimo_error = NULL, "
                                 "descargada_at = ?, actualizado_at = ? WHERE img_key = ?",
                                 (res.version, ruta_og, res.mime, res.ancho, res.alto, total, res.lqip, res.color,
                                  ahora, ahora, clave))
            except (_Descartar, ErrorApi):
                for ruta in escritos:
                    try:
                        os.remove(ruta)
                    except OSError:
                        pass
                return False
            except OSError as e:
                for ruta in escritos:
                    try:
                        os.remove(ruta)
                    except OSError:
                        pass
                _log.warning('Imagen %s: no se pudo guardar en la caché (%s)', clave, type(e).__name__)
                self._registrar_fallo(clave, huella, epoca, k.ErrorImagen('sin_espacio'))
                return False
        if vieja and vieja != ruta_og:
            self._borrar_archivos(vieja, reintentos=4)         # ya nadie la referencia: fuera del candado
        self._anotar_exito(clave)
        return True

    def _registrar_fallo(self, clave: str, huella: str | None, epoca: int, e: k.ErrorImagen) -> None:
        ahora = self._reloj.ahora()
        intentos = 0
        try:
            with self._almacen.escritor(epoca) as conn:
                fila = conn.execute('SELECT intentos, url_huella, estado FROM imagenes WHERE img_key = ?',
                                    (clave,)).fetchone()
                if fila is None or fila[1] != huella or fila[2] == 'ok':
                    return
                intentos = int(fila[0] or 0) + 1
                conn.execute('UPDATE imagenes SET estado = ?, intentos = ?, ultimo_error = ?, actualizado_at = ? '
                             'WHERE img_key = ?', ('bloqueada' if e.permanente else 'error', intentos, e.codigo, ahora,
                                                   clave))
        except ErrorApi:
            return                                           # los datos se borraron mientras tanto
        _log.info('Imagen %s: %s (intento %d)', clave, e.codigo, intentos)
        mono = self._reloj.monotonico()
        with self._candado:
            if not e.permanente and 1 <= intentos <= len(REINTENTOS_S) and not k.es_diferida(clave.partition(':')[0]):
                heapq.heappush(self._reintentos, (mono + REINTENTOS_S[intentos - 1], clave))

    # ================================================================== hilo de control: lotes y reintentos
    def _bucle_control(self, parar: threading.Event) -> None:
        while not parar.wait(TIC_S):
            try:
                self._cerrar_lote_si_toca()
                self._mover_reintentos()
                self._revisar_errores_largos()
            except Exception as e:  # noqa: BLE001 - el control sigue aunque una vuelta falle
                _log.error('Imágenes: falla en el hilo de control (%s)', type(e).__name__)

    def _anotar_exito(self, clave: str) -> None:
        ahora = self._reloj.monotonico()
        with self._candado:
            if self._lote_n == 0:
                self._lote_primero = ahora
            self._lote_n += 1
            self._lote_ultimo = ahora
            self._lote_avatar = self._lote_avatar or clave.startswith('a:')

    def _cola_ocupada(self) -> bool:
        with self._candado:
            en_vuelo = bool(self._en_vuelo)
        return en_vuelo or len(self._cola) > 0

    def _cerrar_lote_si_toca(self, forzar: bool = False) -> bool:
        ocupada = self._cola_ocupada()
        ahora = self._reloj.monotonico()
        with self._candado:
            if self._lote_n == 0:
                return False
            quieto = ahora - self._lote_ultimo >= ANTIRREBOTE_S
            largo = ahora - self._lote_primero >= LOTE_MAX_S
            if not (forzar or largo or (quieto and not ocupada)):
                return False
            n, avatar = self._lote_n, self._lote_avatar
            self._lote_n, self._lote_avatar = 0, False
        try:
            with self._almacen.escritor() as conn:
                self._almacen.subir_img_rev(conn)
            versiones = self._almacen.versiones()
            secciones = list(SECCIONES_LOTE) + (['cuenta'] if avatar else [])
            self._bus.notificar_cambio(versiones, secciones)
        except Exception as e:  # noqa: BLE001 - se reintenta en la siguiente vuelta
            _log.warning('Imágenes: no se pudo publicar el lote (%s)', type(e).__name__)
            with self._candado:
                if self._lote_n == 0:
                    self._lote_primero = ahora
                self._lote_n += n
                self._lote_avatar = self._lote_avatar or avatar
            return False
        _log.info('Imágenes: lote de %d listo (img_rev %d)', n, versiones[2])
        self._purgar_si_excede()
        return True

    def _purgar_si_excede(self) -> None:
        """La LRU se cumple sola: al cerrar un lote, si la caché pasa del último tope (400 MB por omisión, o el que
        hub.py pasó a purgar()), se purga en ese momento sin esperar a la tarea diaria."""
        try:
            with self._almacen.lector() as conn:
                total = conn.execute("SELECT COALESCE(SUM(bytes), 0) FROM imagenes WHERE estado = 'ok'").fetchone()[0]
        except sqlite3.Error:
            return
        if int(total) > self._max_mb * 1024 * 1024:
            self.purgar(self._max_mb)

    def _mover_reintentos(self) -> None:
        ahora = self._reloj.monotonico()
        vencidos = []
        with self._candado:
            while self._reintentos and self._reintentos[0][0] <= ahora:
                vencidos.append(heapq.heappop(self._reintentos)[1])
        for clave in vencidos:
            self._cola.poner(clave, 2)

    def _revisar_errores_largos(self) -> None:
        if self._reloj.monotonico() < self._proxima_revision:
            return
        self._proxima_revision = self._reloj.monotonico() + REVISION_ERRORES_S
        ahora = self._reloj.ahora()
        with self._almacen.lector() as conn:
            filas = conn.execute("SELECT img_key FROM imagenes WHERE estado = 'error' AND url_origen IS NOT NULL "
                                 "AND tipo IN ('p', 'a', 'v') AND intentos > ? AND actualizado_at <= ?",
                                 (len(REINTENTOS_S), ahora - REINTENTO_LARGO_S)).fetchall()
        for (clave,) in filas:
            self._cola.poner(clave, 2)

    # ================================================================== servir
    def _archivo_si_ok(self, fila: sqlite3.Row | None, t: str | None) -> tuple[str, str] | str | None:
        """(ruta, mime) si la fila está 'ok' y el archivo pedido (original o variante `t`) existe; 'fuera' si ruta_rel
        escapa de la caché; None si no. Si falta la variante pedida NO se sirve el original en su lugar (quedaría
        guardado como `immutable` bajo la URL de la variante): se trata como faltante y se vuelve a generar."""
        if fila is None or fila['estado'] != 'ok' or not k.version_valida(fila['version']) or not fila['ruta_rel']:
            return None
        og = k.ruta_segura(self.raiz, fila['ruta_rel'])
        if og is None:
            return 'fuera'
        if not os.path.isfile(og):
            return None
        if not t:
            return og, fila['mime'] or k.MIMES.get(os.path.splitext(og)[1].lstrip('.'), 'application/octet-stream')
        rel = k.ruta_rel_variante(fila['ruta_rel'], t)
        ruta = k.ruta_segura(self.raiz, rel) if rel else None
        if ruta is None or not os.path.isfile(ruta):
            return None
        return ruta, 'image/webp'

    def _respuesta(self, clave: str, fila: sqlite3.Row, archivo: tuple[str, str], v: str | None, t: str | None,
                   forzar_revalidar: bool = False) -> RespuestaImagen:
        ruta, mime = archivo
        version = fila['version']
        cache = CACHE_INMUTABLE if (v == version and not forzar_revalidar) else CACHE_REVALIDAR
        etiqueta = f'"{version}-{t}"' if t else f'"{version}"'
        with self._candado:
            self._accesos[clave] = self._reloj.ahora()
        return RespuestaImagen(200, [('Content-Type', mime), ('Cache-Control', cache), ('ETag', etiqueta)], ruta)

    def servir(self, tipo: str, ref_id: str, v: str | None, t: str | None) -> RespuestaImagen:
        if tipo not in k.TIPOS or not k.ref_valido(tipo, ref_id):
            return _respuesta_404()                         # tipos desconocidos y '..\\..\\secretos.dat'
        if t not in (None, '') and t not in k.VARIANTES:
            return _respuesta_404()
        t = t or None
        clave = k.clave(tipo, ref_id)
        fila = self._fila(clave)
        archivo = self._archivo_si_ok(fila, t)
        if archivo == 'fuera':
            _log.warning('Imagen %s: ruta_rel fuera de la caché; no se sirve', clave)
            return _respuesta_404()
        if isinstance(archivo, tuple):
            return self._respuesta(clave, fila, archivo, v, t)
        if fila is None or not fila['url_origen'] or fila['estado'] == 'bloqueada':
            return _respuesta_404()
        if (fila['estado'] == 'error'
                and self._reloj.ahora() - int(fila['actualizado_at'] or 0) < PAUSA_SINCRONA_TRAS_ERROR_S):
            return _respuesta_404()                         # acaba de fallar (trabajador o síncrona): no insistir
        if fila['estado'] == 'ok':                          # 'ok' sin el archivo pedido: se borró fuera del hub
            self._marcar_faltante(clave, fila['ruta_rel'])
        self._lanzar_sincrona(clave).wait(TOPE_SINCRONO_S)
        fila = self._fila(clave)
        archivo = self._archivo_si_ok(fila, t)
        if isinstance(archivo, tuple):
            return self._respuesta(clave, fila, archivo, v, t, forzar_revalidar=True)
        return _respuesta_404()

    def _lanzar_sincrona(self, clave: str) -> threading.Event:
        """Descarga en un hilo propio (el tope de 5 s lo pone quien espera). Si ya hay una en curso, se espera esa."""
        with self._candado:
            ev = self._en_vuelo.get(clave)
            if ev is not None:
                return ev
            ev = self._en_vuelo[clave] = threading.Event()

        def correr() -> None:
            try:
                if self._trabajar(clave, sincrona=True) == 'sin_lugar':
                    with self._candado:
                        self._repetir.add(clave)            # que la descargue un trabajador en cuanto haya lugar
            except Exception as e:  # noqa: BLE001
                _log.error('Imagen %s: falla inesperada en la descarga síncrona (%s)', clave, type(e).__name__)
            finally:
                self._soltar(clave, ev)

        threading.Thread(target=correr, name='imagenes-sincrona', daemon=True).start()
        return ev

    def _marcar_faltante(self, clave: str, ruta_rel: str | None) -> None:
        with self._almacen.escritor() as conn:
            conn.execute("UPDATE imagenes SET estado = 'pendiente', version = NULL, ruta_rel = NULL, bytes = NULL, "
                         'actualizado_at = ? WHERE img_key = ? AND ruta_rel IS ?', (self._reloj.ahora(), clave, ruta_rel))

    def ruta_original(self, tipo: str, ref_id: str) -> str | None:
        if tipo not in k.TIPOS or not k.ref_valido(tipo, ref_id):
            return None
        archivo = self._archivo_si_ok(self._fila(k.clave(tipo, ref_id)), None)
        return archivo[0] if isinstance(archivo, tuple) else None

    def meta_de(self, urls: Iterable[str]) -> Json:
        pedidas: dict[str, k.UrlImg] = {}
        for url in urls:
            u = k.parsear_url_img(url)
            if u is not None and k.version_valida(u.v):
                pedidas[url] = u
        if not pedidas:
            return {}
        claves = sorted({u.clave for u in pedidas.values()})
        filas: dict[str, sqlite3.Row] = {}
        with self._almacen.lector() as conn:
            for i in range(0, len(claves), 500):
                trozo = claves[i:i + 500]
                marcas = ','.join('?' * len(trozo))
                for f in conn.execute(f"SELECT img_key, version, ancho, alto, lqip, color FROM imagenes "
                                      f"WHERE estado = 'ok' AND img_key IN ({marcas})", trozo):
                    filas[f['img_key']] = f
        meta: Json = {}
        for url, u in pedidas.items():
            f = filas.get(u.clave)
            if f is not None and f['version'] == u.v and f['ancho'] and f['alto']:
                meta[url] = {'w': f['ancho'], 'h': f['alto'], 'lqip': f['lqip'], 'color': f['color']}
        return meta

    # ================================================================== cola, accesos, LRU
    def vaciar_cola(self) -> None:
        n = self._cola.vaciar()
        with self._candado:
            self._reintentos.clear()
            self._repetir.clear()
            self._generacion += 1
        _log.info('Imágenes: cola vaciada (%d pendientes)', n)

    def volcar_accesos(self) -> None:
        with self._candado:
            pendientes, self._accesos = self._accesos, {}
        if not pendientes:
            return
        try:
            with self._almacen.escritor() as conn:
                conn.executemany('UPDATE imagenes SET ultimo_acceso_at = MAX(COALESCE(ultimo_acceso_at, 0), ?) '
                                 'WHERE img_key = ?', [(t, c) for c, t in pendientes.items()])
        except Exception as e:  # noqa: BLE001 - se conservan para el siguiente volcado
            _log.warning('Imágenes: no se pudieron volcar los accesos (%s)', type(e).__name__)
            with self._candado:
                for c, t in pendientes.items():
                    self._accesos[c] = max(t, self._accesos.get(c, 0))

    def _protegidas(self) -> set[str]:
        with self._almacen.lector() as conn:
            productos = {r[0] for r in conn.execute(_SQL_PROTEGIDAS)}
        return {f'p:{p}' for p in productos if k.ref_valido('p', p)} | {f'a:{k.REF_CUENTA}'}

    def purgar(self, max_mb: int) -> None:
        self.volcar_accesos()
        try:
            self._max_mb = max(0, int(max_mb))
        except (TypeError, ValueError):
            return
        limite = self._max_mb * 1024 * 1024
        try:
            protegidas = self._protegidas()
        except sqlite3.Error as e:
            _log.warning('Imágenes: no se purga, no se pudieron leer las muestras pendientes (%s)', type(e).__name__)
            return
        ahora = self._reloj.ahora()
        viejo = ahora - DIAS_SIN_USO * 86400
        expulsadas: list[tuple[str, str]] = []
        with self._candado_archivos:
            with self._almacen.lector() as conn:
                filas = conn.execute("SELECT img_key, ruta_rel, COALESCE(bytes, 0), "
                                     "COALESCE(ultimo_acceso_at, descargada_at, actualizado_at, 0) AS uso "
                                     "FROM imagenes WHERE estado = 'ok' AND ruta_rel IS NOT NULL "
                                     "ORDER BY uso ASC, img_key ASC").fetchall()
            total = sum(int(f[2]) for f in filas)
            for clave, ruta_rel, tam, uso in filas:
                if clave in protegidas:
                    continue
                if total > limite or uso < viejo:
                    expulsadas.append((clave, ruta_rel))
                    total -= int(tam)
            if expulsadas:
                with self._almacen.escritor() as conn:
                    conn.executemany("UPDATE imagenes SET estado = 'pendiente', version = NULL, ruta_rel = NULL, "
                                     "mime = NULL, ancho = NULL, alto = NULL, bytes = NULL, lqip = NULL, color = NULL, "
                                     "actualizado_at = ? WHERE img_key = ? AND ruta_rel = ?",
                                     [(ahora, c, r) for c, r in expulsadas])
                for _, ruta_rel in expulsadas:
                    self._borrar_archivos(ruta_rel)
            huerfanos = self._borrar_huerfanos()
        if expulsadas or huerfanos:
            _log.info('Imágenes: purga de %d imágenes y %d archivos huérfanos (tope %d MB)', len(expulsadas),
                      huerfanos, max_mb)

    def _borrar_huerfanos(self) -> int:
        """Archivos de la caché que ninguna fila referencia (versiones viejas, restos de .nuevo, datos borrados)."""
        with self._almacen.lector() as conn:
            rutas = [r[0] for r in conn.execute('SELECT ruta_rel FROM imagenes WHERE ruta_rel IS NOT NULL')]
        vivos = {os.path.normcase(p) for rel in rutas for r in k.rutas_rel_de(rel)
                 if (p := k.ruta_segura(self.raiz, r)) is not None}
        borrados = 0
        for tipo in k.TIPOS:
            carpeta = os.path.join(self.raiz, tipo)
            if not os.path.isdir(carpeta) or os.path.islink(carpeta):
                continue
            for sub in os.scandir(carpeta):
                if not sub.is_dir(follow_symlinks=False):
                    continue
                for a in os.scandir(sub.path):
                    if not a.is_file(follow_symlinks=False):
                        continue
                    resto = '.nuevo-' in a.name and k.nombre_de_cache(a.name.split('.nuevo-', 1)[0])
                    if not (k.nombre_de_cache(a.name) or resto) or os.path.normcase(a.path) in vivos:
                        continue
                    try:
                        os.remove(a.path)
                        borrados += 1
                    except OSError:
                        pass
                try:
                    os.rmdir(sub.path)                       # solo si quedó vacía
                except OSError:
                    pass
        return borrados

    def uso_bytes(self) -> int:
        total = 0
        pila = [self.raiz]
        while pila:
            try:
                entradas = list(os.scandir(pila.pop()))
            except OSError:
                continue
            for e in entradas:
                try:
                    if e.is_dir(follow_symlinks=False):
                        pila.append(e.path)
                    elif e.is_file(follow_symlinks=False):
                        total += e.stat(follow_symlinks=False).st_size
                except OSError:
                    pass
        return total


def crear_imagenes(almacen: Almacen, bus: Bus, reloj: Reloj, raiz_cache: str,
                   descargar: Descargador | None = None) -> Imagenes:
    """Fábrica (FABRICAS de interfaces.py). Sin iniciar: hub.py llama `iniciar()` 2 s después de «listo» (C3).
    `descargar=None` -> descarga real HTTPS (`DescargadorHttps`); en demo, el descargador sin red de `demo/`."""
    return _Imagenes(almacen, bus, reloj, raiz_cache, descargar)
