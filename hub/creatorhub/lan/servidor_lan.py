"""Servidor HTTPS de la LAN (`/lan/v1/*`) para los celulares emparejados (03 §6.6, §7.4; 04 §C.3, §C.5, §C.7, §C.9).

Patrón probado en spec/pruebas/tls_hub_min/servidor_tls.py:
- El socket que escucha NO se envuelve. Cada conexión se envuelve en SU hilo con
  `wrap_socket(do_handshake_on_connect=False)` + `do_handshake()` con tope de 10 s: un cliente que abre TCP y no manda
  nada no bloquea `accept()` ni a los demás (slowloris).
- `verify_request()` corta sin TLS a toda IP fuera de 10/8, 172.16/12, 192.168/16 (loopback solo con
  `permitir_loopback`, que usan las pruebas). Máximo 32 conexiones a la vez y 8 por IP; el exceso se cierra de inmediato.
- `allow_reuse_address = False` + `SO_EXCLUSIVEADDRUSE`: ningún otro proceso puede robar el puerto.
- Lectura: 10 s por espera de red, 15 s en total para cabeceras + cuerpo, 8 KB de cabeceras, cuerpo ≤ 512 KB en el
  listener (03 §7.4, 04 §C.3) y ≤ 256 KB en `/lan/v1/api/*` (BUILD §5: la ruta REST tiene el mismo límite que desde la
  ventana); 413 ANTES de leerlo; `Transfer-Encoding` → 411; la conexión se cierra tras 100 peticiones o 60 s de
  inactividad.
- Cualquier petición con `Origin` → 403 (lo llama código nativo, nunca un navegador). Sin CORS.
- Tasas: 10 req/s (ráfaga 20) por celular en `/lan/v1/api/*`, 30/s (ráfaga 60) en `/lan/v1/img/*`; `pair/start` 12/min
  en total y 5/min por IP; > 10 firmas fallidas por IP en 1 min → 429 durante 60 s; 2 long-poll de `/api/cambios` a la
  vez por celular; `POST /api/sync` una vez cada 2 min por celular (03 §4.4).

Rutas: `GET /lan/v1/hello` · `POST /lan/v1/pair/start` · `GET /lan/v1/pair/{pair_id}?nonce_c=…` (long-poll) ·
`POST /lan/v1/rotar` (firmada) · `/lan/v1/api/*` e `/lan/v1/img/*` (firmadas) → `Despachador` con
`Contexto(origen='lan', plataforma='android', device_id, permisos)`; el permiso lo aplica hub-api.
Nunca se registran cabeceras (Authorization) ni cuerpos.
"""
from __future__ import annotations

import collections
import email.message
import http.client
import http.server
import json
import logging
import os
import re
import secrets
import socket
import socketserver
import ssl
import threading
import time
import urllib.parse
from typing import Any, Iterator, Mapping, Protocol

from ..errores import ErrorDominio
from ..interfaces import Json, RespuestaHttp
from .dispositivos import Verificado
from .red import ip_permitida

_log = logging.getLogger('creatorhub.lan.servidor')

MAX_CONEXIONES = 32
MAX_POR_IP = 8
TIMEOUT_HANDSHAKE_S = 10.0
TIMEOUT_LECTURA_S = 10.0
PLAZO_PETICION_S = 15.0
INACTIVIDAD_S = 60.0
MAX_PETICIONES_CONEXION = 100
MAX_CABECERAS = 8 * 1024
MAX_CUERPO = 512 * 1024              # listener LAN (03 §7.4, 04 §C.3)
MAX_CUERPO_API = 256 * 1024          # /lan/v1/api/* → Despachador: el límite de toda ruta REST (BUILD §5)
PREFIJO = '/lan/v1/'
PREFIJO_API = '/lan/v1/api/'
_RE_PAIR = re.compile(r'^/lan/v1/pair/([0-9a-f]{32})$')

MENSAJES = {
    'no_encontrado': 'No encontramos lo que buscas.',
    'prohibido': 'Esta conexión solo acepta peticiones de la app de Corte en tu celular.',
    'demasiadas_solicitudes': 'Demasiados intentos. Espera un minuto e inténtalo de nuevo.',
    'cuerpo_demasiado_grande': 'La petición es demasiado grande.',
    'parametros_invalidos': 'La petición no es válida.',
    'error_interno': 'Algo salió mal en tu PC. Inténtalo de nuevo.',
    'arrancando': 'Tu PC todavía está preparando la conexión. Inténtalo en unos segundos.',
}


def error_respuesta(codigo: str, mensaje: str | None = None, **extra: Any) -> bytes:
    e: dict[str, Any] = {'codigo': codigo, 'mensaje': mensaje or MENSAJES.get(codigo, MENSAJES['parametros_invalidos'])}
    e.update({k: v for k, v in extra.items() if v is not None})
    return json.dumps({'error': e}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


class NucleoLan(Protocol):
    """Lo que el servidor necesita del servicio (lo implementa servicio.ServicioLanHub)."""
    def hello(self) -> Json: ...
    def pair_start(self, req: Any) -> Json: ...
    def pair_poll(self, pair_id: str, nonce_c: str | None) -> Json: ...
    def verificar(self, cabecera: str | None, metodo: str, ruta_query: str, cuerpo: bytes, ip: str) -> Verificado: ...
    def rotar(self, device_id: str) -> Json: ...
    def despachar(self, metodo: str, ruta_lan: str, consulta: str, cabeceras: Mapping[str, str], cuerpo: bytes,
                  v: Verificado) -> RespuestaHttp: ...


# ====================================================================== límites
class Cubeta:
    """Cubeta de fichas: `tasa` por segundo con ráfaga `rafaga`."""

    def __init__(self, tasa: float, rafaga: float) -> None:
        self.tasa, self.rafaga = tasa, rafaga
        self.fichas, self.t = rafaga, time.monotonic()

    def tomar(self) -> bool:
        ahora = time.monotonic()
        self.fichas = min(self.rafaga, self.fichas + (ahora - self.t) * self.tasa)
        self.t = ahora
        if self.fichas >= 1:
            self.fichas -= 1
            return True
        return False


class VentanaEventos:
    """Cuenta eventos por clave en una ventana deslizante (minuto)."""

    def __init__(self, ventana_s: float) -> None:
        self.ventana_s = ventana_s
        self._d: dict[str, collections.deque[float]] = {}

    def contar(self, clave: str) -> int:
        ahora = time.monotonic()
        q = self._d.get(clave)
        if q is None:
            return 0
        while q and ahora - q[0] > self.ventana_s:
            q.popleft()
        if not q:
            del self._d[clave]
            return 0
        return len(q)

    def anotar(self, clave: str) -> None:
        self._d.setdefault(clave, collections.deque()).append(time.monotonic())


class Limites:
    """Tasas de 03 §7.4 y 04 §C.9 (seguras entre hilos)."""
    PAIR_GLOBAL_MIN = 12
    PAIR_IP_MIN = 5
    FALLOS_FIRMA_MIN = 10
    BLOQUEO_FIRMA_S = 60.0
    LONG_POLL_POR_CELULAR = 2
    SYNC_CADA_S = 120.0

    def __init__(self) -> None:
        self._c = threading.Lock()
        self._pair = VentanaEventos(60.0)
        self._fallos = VentanaEventos(60.0)
        self._bloqueadas: dict[str, float] = {}
        self._api: dict[str, Cubeta] = {}
        self._img: dict[str, Cubeta] = {}
        self._long_poll: collections.Counter[str] = collections.Counter()
        self._sync: dict[str, float] = {}

    def pair_start(self, ip: str) -> bool:
        with self._c:
            if self._pair.contar('*') >= self.PAIR_GLOBAL_MIN or self._pair.contar(ip) >= self.PAIR_IP_MIN:
                return False
            self._pair.anotar('*')
            self._pair.anotar(ip)
            return True

    def ip_bloqueada(self, ip: str) -> float:
        with self._c:
            hasta = self._bloqueadas.get(ip)
            if hasta is None:
                return 0.0
            resto = hasta - time.monotonic()
            if resto <= 0:
                del self._bloqueadas[ip]
                return 0.0
            return resto

    def fallo_firma(self, ip: str) -> None:
        with self._c:
            self._fallos.anotar(ip)
            if self._fallos.contar(ip) > self.FALLOS_FIRMA_MIN:
                self._bloqueadas[ip] = time.monotonic() + self.BLOQUEO_FIRMA_S

    def peticion(self, device_id: str, img: bool) -> bool:
        with self._c:
            tabla = self._img if img else self._api
            c = tabla.get(device_id)
            if c is None:
                c = tabla[device_id] = Cubeta(30, 60) if img else Cubeta(10, 20)
            return c.tomar()

    def entrar_long_poll(self, device_id: str) -> bool:
        with self._c:
            if self._long_poll[device_id] >= self.LONG_POLL_POR_CELULAR:
                return False
            self._long_poll[device_id] += 1
            return True

    def salir_long_poll(self, device_id: str) -> None:
        with self._c:
            self._long_poll[device_id] -= 1
            if self._long_poll[device_id] <= 0:
                del self._long_poll[device_id]

    def sync_espera(self, device_id: str) -> float:
        with self._c:
            t = self._sync.get(device_id)
            return 0.0 if t is None else max(0.0, self.SYNC_CADA_S - (time.monotonic() - t))

    def sync_hecho(self, device_id: str) -> None:
        with self._c:
            self._sync[device_id] = time.monotonic()


# ====================================================================== lectura con plazo
class _LectorConPlazo:
    """Envuelve el `rfile` de la conexión: cada lectura ajusta el timeout del socket al plazo total de la petición
    (15 s para cabeceras + cuerpo) y limita las cabeceras a 8 KB (http.client.LineTooLong → 431)."""

    def __init__(self, crudo: Any, sock: socket.socket) -> None:
        self._crudo, self._sock = crudo, sock
        self._limite: float | None = None
        self._presupuesto: int | None = None

    def iniciar(self, limite: float, presupuesto: int) -> None:
        self._limite, self._presupuesto = limite, presupuesto

    def fin_cabeceras(self) -> None:
        self._presupuesto = None

    def _ajustar(self) -> None:
        if self._limite is None:
            return
        resto = self._limite - time.monotonic()
        if resto <= 0:
            raise TimeoutError('plazo de la petición agotado')
        self._sock.settimeout(min(TIMEOUT_LECTURA_S, resto))

    def _linea(self, limite: int) -> bytes:
        """readline que revisa el plazo entre cada lectura de red (BufferedReader.readline no lo haría: un goteo de
        un byte cada pocos segundos la mantendría viva indefinidamente)."""
        partes: list[bytes] = []
        total = 0
        while limite < 0 or total < limite:
            self._ajustar()
            disponible = self._crudo.peek(1)             # a lo más UNA lectura de red si el búfer está vacío
            if not disponible:
                break
            i = disponible.find(b'\n')
            n = i + 1 if i >= 0 else len(disponible)
            if limite >= 0:
                n = min(n, limite - total)
            trozo = self._crudo.read(n)                  # ya está en el búfer: no bloquea
            partes.append(trozo)
            total += len(trozo)
            if trozo.endswith(b'\n'):
                break
        return b''.join(partes)

    def readline(self, limite: int | None = -1) -> bytes:
        limite = -1 if limite is None else limite
        if self._presupuesto is None:
            return self._linea(limite)
        if self._presupuesto <= 0:
            raise http.client.LineTooLong('cabeceras de más de 8 KB')
        tope = self._presupuesto + 1
        linea = self._linea(tope if limite < 0 else min(limite, tope))
        self._presupuesto -= len(linea)
        if self._presupuesto < 0:
            raise http.client.LineTooLong('cabeceras de más de 8 KB')
        return linea

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            raise ValueError('lectura sin tamaño')
        partes: list[bytes] = []
        while n > 0:
            self._ajustar()
            b = self._crudo.read1(n)
            if not b:
                break
            partes.append(b)
            n -= len(b)
        return b''.join(partes)

    def peek(self, n: int = 1) -> bytes:
        return self._crudo.peek(n)

    @property
    def closed(self) -> bool:
        return self._crudo.closed

    def close(self) -> None:
        self._crudo.close()


class _CabecerasCI(Mapping[str, str]):
    """Cabeceras para el Despachador: claves en minúsculas, búsqueda sin distinguir mayúsculas, SIN Authorization."""

    def __init__(self, mensaje: email.message.Message) -> None:
        self._d: dict[str, str] = {}
        for k, v in mensaje.items():
            kl = k.lower()
            if kl != 'authorization':
                self._d[kl] = v if kl not in self._d else self._d[kl] + ', ' + v

    def __getitem__(self, k: str) -> str:
        return self._d[k.lower()]

    def __iter__(self) -> Iterator[str]:
        return iter(self._d)

    def __len__(self) -> int:
        return len(self._d)

    def get(self, k: str, omision: Any = None) -> Any:  # type: ignore[override]
        return self._d.get(k.lower(), omision)


# ====================================================================== manejador
_CODIGO_HTTP = {400: 'parametros_invalidos', 404: 'no_encontrado', 405: 'no_encontrado', 408: 'parametros_invalidos',
                411: 'parametros_invalidos', 413: 'cuerpo_demasiado_grande', 414: 'parametros_invalidos',
                431: 'parametros_invalidos', 501: 'no_encontrado', 505: 'parametros_invalidos'}
_SIN_PASAR = frozenset({'content-length', 'connection', 'transfer-encoding', 'keep-alive', 'set-cookie', 'server',
                        'date'})


class Manejador(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'Corte'
    sys_version = ''
    server: 'ServidorLan'

    # -------------------------------------------------------------- ciclo de la conexión
    def setup(self) -> None:
        super().setup()
        self._crudo = self.rfile
        self.rfile = _LectorConPlazo(self._crudo, self.connection)  # type: ignore[assignment]
        self._peticiones = 0
        self._extra: list[tuple[str, str]] = []
        self._drenar = False

    def finish(self) -> None:
        # Se respondió un error sin leer el cuerpo (411/413/431…): cerrar con datos sin leer manda un RST que puede
        # borrar la respuesta en el cliente. Se descarta un poco de lo que llegue (tope 256 KB y 1 s) antes de cerrar.
        if self._drenar:
            try:
                self.connection.settimeout(0.3)
                fin, total = time.monotonic() + 1.0, 0
                while time.monotonic() < fin and total < 256 * 1024:
                    b = self._crudo.read1(64 * 1024)
                    if not b:
                        break
                    total += len(b)
            except (OSError, ssl.SSLError, ValueError):
                pass
        super().finish()

    def handle_one_request(self) -> None:
        self.connection.settimeout(TIMEOUT_LECTURA_S if self._peticiones == 0 else INACTIVIDAD_S)
        try:
            if not self._crudo.peek(1):                  # el cliente cerró
                self.close_connection = True
                return
        except (TimeoutError, OSError, ssl.SSLError):
            self.close_connection = True                 # inactiva: se cierra (60 s; 10 s antes de la primera)
            return
        self._peticiones += 1
        self._extra = []
        self.rfile.iniciar(time.monotonic() + PLAZO_PETICION_S, MAX_CABECERAS)  # type: ignore[attr-defined]
        try:
            super().handle_one_request()
        except http.client.HTTPException:
            self.requestline, self.request_version, self.command = '', 'HTTP/1.1', ''
            self.send_error(431)
        except (TimeoutError, ssl.SSLError, ConnectionError):
            self.close_connection = True
        if self._peticiones >= MAX_PETICIONES_CONEXION:
            self.close_connection = True

    def parse_request(self) -> bool:
        ok = super().parse_request()
        self.rfile.fin_cabeceras()                       # type: ignore[attr-defined]
        return ok

    def handle_expect_100(self) -> bool:
        largo, tope = self._largo_cuerpo(), self._tope_cuerpo()
        if largo is None or largo > tope or self.headers.get('Transfer-Encoding') is not None:
            self.send_error(413 if (largo or 0) > tope else 400)
            return False
        return super().handle_expect_100()

    # -------------------------------------------------------------- registro (sin cabeceras, cuerpos ni query)
    def log_request(self, code: Any = '-', size: Any = '-') -> None:
        ruta = (getattr(self, 'path', '') or '').split('?', 1)[0]      # la query puede traer nonce_c o búsquedas
        _log.debug('%s %s %s %s', self.client_address[0], getattr(self, 'command', '') or '-', ruta[:200],
                   getattr(code, 'value', code))

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - firma de la clase base
        _log.debug('%s %s', self.client_address[0], format % args)

    def log_error(self, format: str, *args: Any) -> None:    # noqa: A002
        _log.debug('%s %s', self.client_address[0], format % args)

    # -------------------------------------------------------------- respuestas
    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        self.close_connection = True
        self._drenar = True
        try:
            self._enviar(code, error_respuesta(_CODIGO_HTTP.get(code, 'parametros_invalidos')))
        except (OSError, ssl.SSLError):
            pass

    def _enviar(self, status: int, cuerpo: bytes = b'', cabeceras: list[tuple[str, str]] | None = None,
                archivo: str | None = None, tipo: str | None = 'application/json; charset=utf-8') -> None:
        cabeceras = list(cabeceras or [])
        nombres = {k.lower() for k, _ in cabeceras}
        self.send_response(status)
        if tipo and 'content-type' not in nombres and (cuerpo or archivo):
            self.send_header('Content-Type', tipo)
        if 'cache-control' not in nombres:
            self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        for k, v in cabeceras + self._extra:
            self.send_header(k, v)
        tam = os.path.getsize(archivo) if archivo else len(cuerpo)
        sin_cuerpo = status in (204, 304) or 100 <= status < 200
        if not sin_cuerpo:
            self.send_header('Content-Length', str(tam))
        if self.close_connection or self._peticiones >= MAX_PETICIONES_CONEXION or self.server.cerrando:
            self.close_connection = True
            self.send_header('Connection', 'close')
        self.end_headers()
        if sin_cuerpo:
            return
        if archivo:
            with open(archivo, 'rb') as f:
                while True:
                    bloque = f.read(64 * 1024)
                    if not bloque:
                        break
                    self.wfile.write(bloque)
        elif cuerpo:
            self.wfile.write(cuerpo)

    def _json(self, status: int, obj: Any) -> None:
        self._enviar(status, json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))

    def _error(self, e: ErrorDominio) -> None:
        extra: list[tuple[str, str]] = []
        if e.reintentar_en_s is not None:
            extra.append(('Retry-After', str(int(max(1, e.reintentar_en_s)))))
        cuerpo = json.dumps(e.a_respuesta(), ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self._enviar(e.http, cuerpo, extra)

    # -------------------------------------------------------------- métodos
    def do_GET(self) -> None:
        self._atender()

    def do_POST(self) -> None:
        self._atender()

    def do_PUT(self) -> None:
        self._atender()

    def do_PATCH(self) -> None:
        self._atender()

    def do_DELETE(self) -> None:
        self._atender()

    # -------------------------------------------------------------- cuerpo
    def _largo_cuerpo(self) -> int | None:
        v = self.headers.get('Content-Length')
        if v is None:
            return 0
        v = v.strip()
        if not (v.isascii() and v.isdigit()) or len(v) > 12:     # '²' es isdigit() pero int() lo rechaza
            return None
        return int(v)

    def _tope_cuerpo(self) -> int:
        return MAX_CUERPO_API if (getattr(self, 'path', '') or '').startswith(PREFIJO_API) else MAX_CUERPO

    def _leer_cuerpo(self) -> bytes:
        if self.headers.get('Transfer-Encoding') is not None:
            self.close_connection = self._drenar = True
            raise ErrorDominio('parametros_invalidos', 'Envía la petición con Content-Length.', http=411)
        largo = self._largo_cuerpo()
        if largo is None:
            self.close_connection = self._drenar = True
            raise ErrorDominio('parametros_invalidos', MENSAJES['parametros_invalidos'], http=400)
        if largo > self._tope_cuerpo():                  # 413 ANTES de leer
            self.close_connection = self._drenar = True
            raise ErrorDominio('cuerpo_demasiado_grande', MENSAJES['cuerpo_demasiado_grande'], http=413)
        if not largo:
            return b''
        cuerpo = self.rfile.read(largo)
        if len(cuerpo) != largo:
            self.close_connection = True
            raise TimeoutError('cuerpo incompleto')
        return cuerpo

    # -------------------------------------------------------------- enrutado
    def _atender(self) -> None:
        nucleo = self.server.nucleo
        ip = self.client_address[0]
        try:
            cuerpo = self._leer_cuerpo()                 # primero: así una respuesta de error no deja bytes sin leer
            if self.headers.get('Origin') is not None:
                raise ErrorDominio('prohibido', MENSAJES['prohibido'], http=403)
            ruta_query = self.path
            if not ruta_query.startswith(PREFIJO):
                raise ErrorDominio('no_encontrado', MENSAJES['no_encontrado'], http=404)
            ruta, _, consulta = ruta_query.partition('?')
            if any(urllib.parse.unquote(s) in ('.', '..') for s in ruta.split('/')):
                raise ErrorDominio('no_encontrado', MENSAJES['no_encontrado'], http=404)
            metodo = self.command
            m_pair = _RE_PAIR.match(ruta)
            if ruta == '/lan/v1/hello':
                self._solo(metodo, 'GET')
                return self._json(200, nucleo.hello())
            if ruta == '/lan/v1/pair/start':
                self._solo(metodo, 'POST')
                if not self.server.limites.pair_start(ip):
                    raise ErrorDominio('demasiadas_solicitudes', MENSAJES['demasiadas_solicitudes'], http=429,
                                       reintentar_en_s=60)
                try:
                    req = json.loads(cuerpo.decode('utf-8')) if cuerpo else None
                except (UnicodeDecodeError, ValueError):
                    raise ErrorDominio('parametros_invalidos', MENSAJES['parametros_invalidos'], http=400) from None
                return self._json(202, nucleo.pair_start(req))
            if m_pair:
                self._solo(metodo, 'GET')
                nonce_c = urllib.parse.parse_qs(consulta, keep_blank_values=True).get('nonce_c', [None])[0]
                return self._json(200, nucleo.pair_poll(m_pair.group(1), nonce_c))
            firmada = ruta == '/lan/v1/rotar' or ruta.startswith('/lan/v1/api/') or ruta.startswith('/lan/v1/img/')
            if not firmada:
                raise ErrorDominio('no_encontrado', MENSAJES['no_encontrado'], http=404)
            espera = self.server.limites.ip_bloqueada(ip)
            if espera:
                raise ErrorDominio('demasiadas_solicitudes', MENSAJES['demasiadas_solicitudes'], http=429,
                                   reintentar_en_s=int(espera) + 1)
            try:
                v = nucleo.verificar(self.headers.get('Authorization'), metodo, ruta_query, cuerpo, ip)
            except ErrorDominio as e:
                if e.codigo in ('firma_invalida', 'dispositivo_desconocido'):
                    self.server.limites.fallo_firma(ip)
                raise
            if v.rotar:
                self._extra.append(('X-CH-Rotar', '1'))
            if ruta == '/lan/v1/rotar':
                self._solo(metodo, 'POST')
                return self._json(200, nucleo.rotar(v.device_id))
            self._despachar(nucleo, metodo, ruta, consulta, cuerpo, v)
        except ErrorDominio as e:
            self._error(e)
        except (TimeoutError, ssl.SSLError, ConnectionError):
            self.close_connection = True
        except Exception:  # noqa: BLE001
            ref = secrets.token_hex(4)
            _log.exception('Error al atender una petición de la LAN (ref %s)', ref)
            self._enviar(500, error_respuesta('error_interno', detalle={'ref': ref}))

    @staticmethod
    def _solo(metodo: str, permitido: str) -> None:
        if metodo != permitido:
            raise ErrorDominio('no_encontrado', MENSAJES['no_encontrado'], http=405)

    def _despachar(self, nucleo: NucleoLan, metodo: str, ruta: str, consulta: str, cuerpo: bytes,
                   v: Verificado) -> None:
        limites = self.server.limites
        es_img = ruta.startswith('/lan/v1/img/')
        if not limites.peticion(v.device_id, es_img):
            raise ErrorDominio('demasiadas_solicitudes', MENSAJES['demasiadas_solicitudes'], http=429, reintentar_en_s=1)
        es_cambios = ruta == '/lan/v1/api/cambios'
        es_sync = metodo == 'POST' and ruta == '/lan/v1/api/sync'
        if es_sync:
            espera = limites.sync_espera(v.device_id)
            if espera:
                raise ErrorDominio('demasiadas_solicitudes', 'Tu PC acaba de actualizar tus datos. Inténtalo en un '
                                                             'momento.', http=429, reintentar_en_s=int(espera) + 1)
        if es_cambios and not limites.entrar_long_poll(v.device_id):
            raise ErrorDominio('demasiadas_solicitudes', MENSAJES['demasiadas_solicitudes'], http=429, reintentar_en_s=1)
        try:
            r = nucleo.despachar(metodo, ruta, consulta, _CabecerasCI(self.headers), cuerpo, v)
        finally:
            if es_cambios:
                limites.salir_long_poll(v.device_id)
        if es_sync and 200 <= r.status < 300:
            limites.sync_hecho(v.device_id)
        cabeceras = [(k, val) for k, val in r.cabeceras
                     if k.lower() not in _SIN_PASAR and not k.lower().startswith('access-control-')]
        self._enviar(r.status, r.cuerpo if r.archivo is None else b'', cabeceras, archivo=r.archivo, tipo=None)


# ====================================================================== servidor
class ServidorLan(socketserver.TCPServer):
    allow_reuse_address = False
    request_queue_size = 64

    def __init__(self, direccion: tuple[str, int], ctx: ssl.SSLContext, nucleo: NucleoLan,
                 permitir_loopback: bool = False, timeout_handshake_s: float = TIMEOUT_HANDSHAKE_S) -> None:
        self.ctx = ctx
        self.nucleo = nucleo
        self.permitir_loopback = permitir_loopback
        self.timeout_handshake_s = timeout_handshake_s
        self.limites = Limites()
        self.cerrando = False
        self.handshakes_fallidos = 0
        self.rechazadas = 0
        self._cupo = threading.Lock()
        self._total = 0
        self._por_ip: collections.Counter[str] = collections.Counter()
        self._activas: set[Any] = set()
        self._hilos: set[threading.Thread] = set()
        super().__init__(direccion, Manejador, bind_and_activate=False)
        try:
            self.server_bind()
            self.server_activate()
        except BaseException:
            self.server_close()
            raise

    def server_bind(self) -> None:
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    @property
    def puerto(self) -> int:
        return int(self.server_address[1])

    def servir_en_hilo(self) -> None:
        self._hilo_servir = threading.Thread(target=self.serve_forever, kwargs={'poll_interval': 0.2},
                                             name='lan-servidor', daemon=True)
        self._hilo_servir.start()

    def verify_request(self, request: Any, client_address: Any) -> bool:
        ok = ip_permitida(client_address[0], self.permitir_loopback)
        if not ok:
            self.rechazadas += 1
        return ok

    def process_request(self, request: Any, client_address: Any) -> None:
        ip = client_address[0]
        with self._cupo:
            if self.cerrando or self._total >= MAX_CONEXIONES or self._por_ip[ip] >= MAX_POR_IP:
                self.rechazadas += 1
                lleno = True
            else:
                self._total += 1
                self._por_ip[ip] += 1
                lleno = False
        if lleno:
            self.shutdown_request(request)
            return
        t = threading.Thread(target=self._conexion, args=(request, client_address), name='lan-conexion', daemon=True)
        with self._cupo:
            self._hilos.add(t)
        t.start()

    def _conexion(self, request: Any, client_address: Any) -> None:
        try:
            self.finish_request(request, client_address)
        except Exception:  # noqa: BLE001
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)
            ip = client_address[0]
            with self._cupo:
                self._total -= 1
                self._por_ip[ip] -= 1
                if self._por_ip[ip] <= 0:
                    del self._por_ip[ip]
                self._hilos.discard(threading.current_thread())

    def finish_request(self, request: Any, client_address: Any) -> None:
        request.settimeout(self.timeout_handshake_s)
        tls = self.ctx.wrap_socket(request, server_side=True, do_handshake_on_connect=False)
        with self._cupo:
            self._activas.add(tls)
        try:
            tls.do_handshake()                           # en el hilo de ESTA conexión
            tls.settimeout(TIMEOUT_LECTURA_S)
            self.RequestHandlerClass(tls, client_address, self)
        except (ssl.SSLError, OSError):
            self.handshakes_fallidos += 1                # p. ej. el celular rechazó la huella o no mandó nada
        finally:
            with self._cupo:
                self._activas.discard(tls)
            try:
                tls.close()
            except OSError:
                pass

    def handle_error(self, request: Any, client_address: Any) -> None:
        _log.exception('Error en una conexión de la LAN')

    def conexiones(self) -> int:
        with self._cupo:
            return self._total

    def cerrar(self, espera_s: float = 3.0) -> None:
        """Deja de aceptar, corta las conexiones abiertas y espera sus hilos."""
        self.cerrando = True
        hilo = getattr(self, '_hilo_servir', None)
        if hilo is not None:                             # shutdown() sin serve_forever esperaría para siempre
            self.shutdown()
            hilo.join(espera_s)
        self.server_close()
        with self._cupo:
            activas = list(self._activas)
            hilos = list(self._hilos)
        for s in activas:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        limite = time.monotonic() + espera_s
        for t in hilos:
            t.join(max(0.0, limite - time.monotonic()))
