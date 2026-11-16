"""Servidor de interfaz de la ventana local (BUILD_SPEC §5, §6.4, C8; 03 §6.1, §7.2–§7.3; 04 §A.3).

`ThreadingHTTPServer` (HTTP/1.1, un hilo por conexión, hilos daemon) en 127.0.0.1, nunca 0.0.0.0, con
`SO_EXCLUSIVEADDRUSE` y sin `SO_REUSEADDR`. `enlazar()` hace el bind de forma SÍNCRONA: 39229 y, si está ocupado,
39228…39220 (C8); `puerto_ui=0` = puerto libre al azar (autoprueba, pruebas); otro número = solo ese.

Orden de cada petición: límites (cabeceras ≤ 8 KB → 431, lectura con tope de 15 s, cuerpo ≤ 256 KB → 413 ANTES de
leerlo, `Transfer-Encoding` → 411) · `Host` (421) · `Origin` (403) · rutas:
- `/boot?t=` (token de un uso) → 302 a `/` con la cookie `ch_s`; `/boot/dev` solo con --dev.
- `/api/health` sin sesión; el resto de `/api/*` e `/img/*` exige la cookie (401), su cubeta (429: 50/s en /api, 400/s
  aparte para /img y estáticos) y, en mutaciones, `X-CH-Hub: 1` (403). `/api/events` es el flujo SSE; lo demás va al
  Despachador con `CTX_UI`.
- Lo demás: estáticos de la interfaz (solo GET/HEAD; cualquier otra cosa → 404: no hay más rutas, tampoco
  `/local/activar`, C40).
Rev. 5 (15/11/2026, Display API), solo si hub.py los pasa:
- `/api/display/*` pasa por TODO lo anterior (cookie, cubeta y `X-CH-Hub` en mutaciones) y va al despachador LOCAL
  (api/rutas_display.py), no al principal: el servidor LAN nunca las ve.
- `GET /oauth/tiktok?code&state` (o `error`): el regreso del navegador del SISTEMA tras autorizar en TikTok. Pasa por
  Host (421) y Origin (403) pero no lleva la cookie de la ventana (es otro navegador): lo protegen el state de un solo
  uso de 10 min y PKCE. Cubeta propia de 2/s; solo GET; responde la página HTML mínima del servicio con la CSP de las
  páginas propias, `no-store` y `Referrer-Policy: no-referrer` (el code nunca sale en un Referer).
Nunca hay cabeceras `Access-Control-*`. `log_message` no registra la línea de petición (la de /boot trae el token, la
de /oauth/tiktok el code y el state).
Si se responde sin usar el cuerpo (421/403/401/429/404 de una mutación), el cuerpo se lee y se tira cuando cabe en
256 KB; si no cabe (413), es `chunked` (411) o sobraron cabeceras (431), la conexión se cierra «con espera» (SHUT_WR +
lectura acotada): cerrar un socket con datos sin leer manda RST y el cliente perdería la respuesta de error.
"""
from __future__ import annotations

import http.server
import json
import logging
import os
import socket
import socketserver
import sys
import threading
import time
import urllib.parse
from typing import Any, Callable, Iterable

from .. import config
from ..interfaces import CTX_UI, Despachador, RespuestaHttp
from . import seguridad
from .estaticos import Estaticos
from .sesion import GestorSesiones
from .sse import CanalEventos

_log = logging.getLogger('creatorhub.api.servidor')

METODOS = frozenset({'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE'})
_SIN_PASAR = frozenset({'content-length', 'connection', 'transfer-encoding', 'keep-alive', 'date', 'server'})
_CABECERAS_PRIVADAS = frozenset({'cookie', 'authorization'})
TIPO_JSON = 'application/json; charset=utf-8'
BLOQUE = 64 * 1024
ESPERA_CIERRE_S = 2.0                     # cierre con espera tras rechazar un cuerpo sin leerlo
MAX_DESCARTE_CIERRE = 4 * 1024 * 1024

MSG_PETICION = 'La petición no es válida.'
MSG_METODO = 'Esa acción no existe para esta dirección.'
MSG_NO_ENCONTRADO = 'No encontramos lo que buscas.'
MSG_GRANDE = 'La petición es demasiado grande.'
MSG_CABECERAS = 'Las cabeceras de la petición son demasiado grandes.'
MSG_LARGO = 'Envía la petición con Content-Length.'
MSG_BOOT = 'Este enlace de inicio ya no sirve. Cierra Corte y vuelve a abrirlo.'
MSG_OAUTH = 'Algo salió mal al volver de TikTok. Regresa a Corte e inténtalo de nuevo.'
RUTA_OAUTH = '/oauth/tiktok'
TASA_OAUTH = 2.0                          # regresos de autorización por segundo (ráfaga 5)

_CODIGO_DE_STATUS = {400: 'parametros_invalidos', 404: 'no_encontrado', 405: 'no_encontrado', 408: 'parametros_invalidos',
                     411: 'parametros_invalidos', 413: 'cuerpo_demasiado_grande', 414: 'parametros_invalidos',
                     431: 'parametros_invalidos', 501: 'no_encontrado', 505: 'parametros_invalidos'}


class CabecerasDemasiadoGrandes(Exception):
    pass


class _LectorLimitado:
    """Envuelve `rfile`: mientras se leen la línea de petición y las cabeceras cuenta los bytes (tope 8 KB)."""

    def __init__(self, crudo: Any, tope: int) -> None:
        self._f = crudo
        self.tope = tope
        self.contando = True
        self.leidos = 0

    def reiniciar(self) -> None:
        self.contando, self.leidos = True, 0

    def fin_cabeceras(self) -> None:
        self.contando = False

    def readline(self, limite: int = -1) -> bytes:
        if not self.contando:
            return self._f.readline(limite)
        restante = self.tope - self.leidos + 1
        lim = restante if limite is None or limite < 0 else min(limite, restante)
        linea = self._f.readline(lim)
        self.leidos += len(linea)
        if self.leidos > self.tope:
            raise CabecerasDemasiadoGrandes()
        return linea

    def read(self, n: int = -1) -> bytes:
        return self._f.read(n)

    def __getattr__(self, nombre: str) -> Any:
        return getattr(self._f, nombre)


def _cabeceras_ci(mensaje: Any) -> dict[str, str]:
    """Cabeceras para el Despachador: nombres en minúsculas, sin Cookie ni Authorization."""
    out: dict[str, str] = {}
    for k, v in mensaje.items():
        kl = k.lower()
        if kl in _CABECERAS_PRIVADAS:
            continue
        out[kl] = v if kl not in out else out[kl] + ', ' + v
    return out


def _cerrar_con_espera(sock: Any, tope_s: float = ESPERA_CIERRE_S, max_bytes: int = MAX_DESCARTE_CIERRE) -> None:
    """Medio cierre (SHUT_WR) y lectura de lo que el cliente todavía manda, con tope de tiempo y de bytes, antes de que
    el servidor cierre el socket: así la respuesta de error ya enviada no se pierde por un RST."""
    try:
        sock.shutdown(socket.SHUT_WR)
        limite = time.monotonic() + tope_s
        leidos = 0
        while leidos < max_bytes:
            restante = limite - time.monotonic()
            if restante <= 0:
                break
            sock.settimeout(min(0.5, restante))
            try:
                datos = sock.recv(BLOQUE)
            except (TimeoutError, socket.timeout):
                continue
            if not datos:
                break
            leidos += len(datos)
    except OSError:
        pass


def _pagina(mensaje: str) -> bytes:
    return ('<!doctype html><html lang="es-MX"><head><meta charset="utf-8"><title>Corte</title></head><body>'
            f'<main><h1>Corte</h1><p>{mensaje}</p></main></body></html>').encode('utf-8')


class Manejador(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'Corte'
    sys_version = ''
    timeout = config.TIMEOUT_LECTURA_S                    # tope de lectura por operación del socket (03 §7.3)
    server: 'ServidorUI'

    # -------------------------------------------------------------- ciclo de cada petición
    def setup(self) -> None:
        super().setup()
        self.rfile = _LectorLimitado(self.rfile, config.MAX_CABECERAS_BYTES)  # type: ignore[assignment]
        self._cuerpo_pendiente = False
        self._drenar_al_cerrar = False

    def finish(self) -> None:
        """Cierre «con espera» si quedaron bytes sin leer (cuerpo rechazado con 413/411/403…, cabeceras de más): cerrar
        un socket con datos sin leer manda RST y el cliente podría perder la respuesta de error antes de leerla."""
        try:
            super().finish()
        finally:
            if self._drenar_al_cerrar:
                _cerrar_con_espera(self.request)

    def handle_one_request(self) -> None:
        self._cuerpo_pendiente = False
        try:
            self.rfile.reiniciar()                                         # type: ignore[attr-defined]
            self.raw_requestline = self.rfile.readline(65537)
            if not self.raw_requestline:
                self.close_connection = True
                return
            if len(self.raw_requestline) > 65536:
                self.requestline, self.request_version, self.command = '', '', ''
                self.close_connection = True
                self.send_error(414)
                return
            if not self.parse_request():
                return
            self.rfile.fin_cabeceras()                                     # type: ignore[attr-defined]
            self._atender()
            self.wfile.flush()
        except CabecerasDemasiadoGrandes:
            self.close_connection = True
            self._drenar_al_cerrar = True
            if not getattr(self, 'request_version', ''):
                self.request_version = 'HTTP/1.1'
            self._error_json(431, 'parametros_invalidos', MSG_CABECERAS)
        except (TimeoutError, ConnectionError, OSError):
            self.close_connection = True

    def version_string(self) -> str:
        return self.server_version

    # -------------------------------------------------------------- registro sin secretos
    def log_message(self, formato: str, *args: Any) -> None:    # nunca la línea de petición (trae el token de /boot)
        return

    def log_request(self, code: int | str = '-', size: int | str = '-') -> None:
        if _log.isEnabledFor(logging.DEBUG):
            ruta = urllib.parse.urlsplit(getattr(self, 'path', '') or '').path
            _log.debug('%s %s → %s', getattr(self, 'command', '?'), ruta[:200], code)

    def log_error(self, formato: str, *args: Any) -> None:
        return

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """Errores de http.server (línea de petición mala, versión, …) como ErrorRespuesta JSON."""
        self.close_connection = True
        self._error_json(code, _CODIGO_DE_STATUS.get(code, 'parametros_invalidos'),
                         MSG_NO_ENCONTRADO if code in (404, 501) else MSG_PETICION)

    # -------------------------------------------------------------- envío
    def _enviar(self, status: int, cabeceras: Iterable[tuple[str, str]] = (), cuerpo: bytes = b'',
                archivo: str | None = None, cabeza: bool = False) -> None:
        if self._cuerpo_pendiente:
            self._descartar_cuerpo()                # respuesta sin usar el cuerpo (403, 401, 404…): se lee y se tira
        f = None
        if archivo is not None:
            try:
                f = open(archivo, 'rb')
                tam = os.fstat(f.fileno()).st_size
            except OSError:
                if f is not None:
                    f.close()
                self._error_json(404, 'no_encontrado', MSG_NO_ENCONTRADO)
                return
        else:
            tam = len(cuerpo)
        try:
            cab = [(k, v) for k, v in seguridad.sin_cors(cabeceras) if k.lower() not in _SIN_PASAR]
            nombres = {k.lower() for k, _ in cab}
            self.send_response(status)
            for k, v in seguridad.CABECERAS_BASE:
                if k.lower() not in nombres:
                    self.send_header(k, v)
            for k, v in cab:
                self.send_header(k, v)
            sin_cuerpo = status in (204, 304) or 100 <= status < 200
            if not sin_cuerpo:
                self.send_header('Content-Length', str(tam))
            if self._cuerpo_pendiente or self.close_connection or self.server.cerrando:
                self.close_connection = True
                self._drenar_al_cerrar = self._drenar_al_cerrar or self._cuerpo_pendiente
                self.send_header('Connection', 'close')
            self.end_headers()
            if cabeza or sin_cuerpo:
                return
            if f is not None:
                while True:
                    bloque = f.read(BLOQUE)
                    if not bloque:
                        break
                    self.wfile.write(bloque)
            elif cuerpo:
                self.wfile.write(cuerpo)
        finally:
            if f is not None:
                f.close()

    def _enviar_respuesta(self, r: RespuestaHttp, cabeza: bool = False) -> None:
        self._enviar(int(r.status), r.cabeceras or [], r.cuerpo if r.archivo is None else b'', r.archivo, cabeza)

    def _error_json(self, status: int, codigo: str, mensaje: str, reintentar_en_s: int | None = None) -> None:
        error: dict[str, Any] = {'codigo': codigo, 'mensaje': mensaje}
        cab = [('Content-Type', TIPO_JSON), ('Cache-Control', 'no-store')]
        if reintentar_en_s is not None:
            error['reintentar_en_s'] = reintentar_en_s
            cab.append(('Retry-After', str(reintentar_en_s)))
        cuerpo = json.dumps({'error': error}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        try:
            self._enviar(status, cab, cuerpo, cabeza=getattr(self, 'command', '') == 'HEAD')
        except OSError:
            self.close_connection = True

    # -------------------------------------------------------------- cuerpo
    def _hay_cuerpo(self) -> bool:
        if self.headers.get('Transfer-Encoding') is not None:
            return True
        cl = (self.headers.get('Content-Length') or '').strip()
        return bool(cl) and cl != '0'

    def _descartar_cuerpo(self) -> None:
        """Lee y tira un cuerpo que no se va a usar si cabe en el límite (≤ 256 KB, con el tope de lectura de 15 s).
        Uno más grande, `chunked` o con Content-Length inválido NO se lee: la conexión se cierra con espera."""
        if self.headers.get('Transfer-Encoding') is not None:
            return
        cl = (self.headers.get('Content-Length') or '').strip()
        if not (cl.isascii() and cl.isdigit()) or len(cl) > 12 or int(cl) > config.MAX_CUERPO_BYTES:
            return
        restante = int(cl)
        try:
            while restante > 0:
                bloque = self.rfile.read(min(restante, BLOQUE))
                if not bloque:
                    break
                restante -= len(bloque)
        except OSError:
            self.close_connection = True
            return
        if restante == 0:
            self._cuerpo_pendiente = False

    def _leer_cuerpo(self) -> bytes | None:
        """El cuerpo (≤ 256 KB). None si ya se respondió un error (413 antes de leer, 411, 400)."""
        if self.headers.get('Transfer-Encoding') is not None:
            self.close_connection = True
            self._error_json(411, 'parametros_invalidos', MSG_LARGO)
            return None
        cl = self.headers.get('Content-Length')
        if cl is None:
            return b''
        cl = cl.strip()
        if not (cl.isascii() and cl.isdigit()) or len(cl) > 12:
            self.close_connection = True
            self._error_json(400, 'parametros_invalidos', MSG_PETICION)
            return None
        largo = int(cl)
        if largo > config.MAX_CUERPO_BYTES:                  # 413 ANTES de leer
            self.close_connection = True
            self._error_json(413, 'cuerpo_demasiado_grande', MSG_GRANDE)
            return None
        datos = self.rfile.read(largo) if largo else b''
        if len(datos) != largo:
            self.close_connection = True
            return None
        self._cuerpo_pendiente = False
        return datos

    # -------------------------------------------------------------- enrutado
    def _atender(self) -> None:
        srv = self.server
        metodo = (self.command or '').upper()
        self._cuerpo_pendiente = self._hay_cuerpo()
        ruta, _, consulta = self.path.partition('?')
        ruta = ruta.split('#', 1)[0]
        if not ruta.startswith('/'):
            self._error_json(400, 'parametros_invalidos', MSG_PETICION)
            return
        if not seguridad.host_valido(self.headers.get('Host'), srv.puerto):
            self._error_json(421, 'prohibido', seguridad.MSG_HOST)
            return
        if not seguridad.origen_valido(self.headers.get('Origin'), srv.puerto, srv.dev):
            self._error_json(403, 'prohibido', seguridad.MSG_ORIGEN)
            return
        if metodo not in METODOS:
            self._error_json(405, 'no_encontrado', MSG_METODO)
            return
        if ruta == '/boot':
            self._boot(metodo, consulta)
        elif ruta == '/boot/dev':
            self._boot_dev(metodo)
        elif ruta == RUTA_OAUTH and srv.oauth is not None:
            self._oauth(metodo, consulta)
        elif ruta == '/api' or ruta.startswith('/api/') or ruta.startswith('/img/'):
            self._api(metodo, ruta, consulta)
        else:
            self._estatico(metodo, ruta)

    def _boot(self, metodo: str, consulta: str) -> None:
        if metodo not in ('GET', 'HEAD'):
            self._error_json(405, 'no_encontrado', MSG_METODO)
            return
        token = urllib.parse.parse_qs(consulta, keep_blank_values=True).get('t', [''])[-1]
        if not self.server.sesiones.consumir_token(token):
            self._enviar(403, [('Content-Type', 'text/html; charset=utf-8'), ('Cache-Control', 'no-store'),
                               ('Content-Security-Policy', seguridad.CSP_PAGINA_HUB)], _pagina(MSG_BOOT),
                         cabeza=metodo == 'HEAD')
            return
        self._entregar_sesion(metodo)

    def _boot_dev(self, metodo: str) -> None:
        if not self.server.dev:
            self._error_json(404, 'no_encontrado', MSG_NO_ENCONTRADO)
            return
        if metodo not in ('GET', 'HEAD'):
            self._error_json(405, 'no_encontrado', MSG_METODO)
            return
        self._entregar_sesion(metodo)

    def _oauth(self, metodo: str, consulta: str) -> None:
        """Regreso de la autorización de la Display API (rev. 5). Nunca registra la consulta (trae el code)."""
        srv = self.server
        if metodo != 'GET':                       # un HEAD o un POST nunca consumen el state
            self.close_connection = self.close_connection or self._cuerpo_pendiente
            self._error_json(405, 'no_encontrado', MSG_METODO)
            return
        if not srv.cubeta_oauth.tomar():
            self._error_json(429, 'demasiadas_solicitudes', seguridad.MSG_TASA, reintentar_en_s=1)
            return
        try:
            status, pagina = srv.oauth(consulta)
        except Exception as e:  # noqa: BLE001 - nunca texto de la excepción hacia afuera
            _log.warning('Falló el regreso de la autorización de TikTok (%s)', type(e).__name__)
            status, pagina = 500, _pagina(MSG_OAUTH)
        self._enviar(int(status), [('Content-Type', 'text/html; charset=utf-8'), ('Cache-Control', 'no-store'),
                                   ('Content-Security-Policy', seguridad.CSP_PAGINA_HUB)], pagina)

    def _entregar_sesion(self, metodo: str) -> None:
        sesion = self.server.sesiones.nueva_sesion()
        self._enviar(302, [('Location', '/'), ('Cache-Control', 'no-store'),
                           ('Set-Cookie', GestorSesiones.cookie(sesion))], b'', cabeza=metodo == 'HEAD')

    def _api(self, metodo: str, ruta: str, consulta: str) -> None:
        srv = self.server
        es_img = ruta.startswith('/img/')
        if ruta == '/api/health' and metodo == 'GET':      # única ruta sin sesión (la usa el shell al arrancar)
            self._enviar_respuesta(srv.despachador.despachar('GET', ruta, consulta, _cabeceras_ci(self.headers), b'',
                                                             CTX_UI))
            return
        sesion = srv.sesiones.sesion(self.headers.get('Cookie'))
        if sesion is None:
            self._error_json(401, 'sesion_invalida', seguridad.MSG_SESION)
            return
        if not srv.sesiones.permitir(sesion, 'img' if es_img else 'api'):
            self._error_json(429, 'demasiadas_solicitudes', seguridad.MSG_TASA, reintentar_en_s=1)
            return
        if seguridad.es_mutacion(metodo) and (self.headers.get('X-CH-Hub') or '').strip() != '1':
            self._error_json(403, 'prohibido', seguridad.MSG_CABECERA_HUB)
            return
        if ruta == '/api/events':
            if metodo != 'GET':
                self._error_json(405, 'no_encontrado', MSG_METODO)
                return
            self._eventos()
            return
        cuerpo = self._leer_cuerpo()
        if cuerpo is None:
            return
        despachador = srv.despachador
        if srv.despachador_local is not None and (ruta == '/api/display' or ruta.startswith('/api/display/')):
            despachador = srv.despachador_local              # rev. 5: rutas solo de la ventana local (nunca LAN)
        r = despachador.despachar(metodo, ruta, consulta, _cabeceras_ci(self.headers), cuerpo, CTX_UI)
        self._enviar_respuesta(r, cabeza=metodo == 'HEAD')

    def _eventos(self) -> None:
        self.close_connection = True
        self.send_response(200)
        for k, v in seguridad.CABECERAS_BASE:
            self.send_header(k, v)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Accel-Buffering', 'no')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.server.canal.transmitir(self.wfile)

    def _estatico(self, metodo: str, ruta: str) -> None:
        srv = self.server
        if metodo not in ('GET', 'HEAD'):
            self.close_connection = self.close_connection or self._cuerpo_pendiente
            self._error_json(404, 'no_encontrado', MSG_NO_ENCONTRADO)
            return
        sesion = srv.sesiones.sesion(self.headers.get('Cookie'))
        if not srv.sesiones.permitir(sesion, 'img'):
            self._error_json(429, 'demasiadas_solicitudes', seguridad.MSG_TASA, reintentar_en_s=1)
            return
        e = srv.estaticos.resolver(ruta)
        self._enviar(e.status, e.cabeceras, e.cuerpo, e.archivo, cabeza=metodo == 'HEAD')


class ServidorUI(http.server.ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, direccion: tuple[str, int], despachador: Despachador, sesiones: GestorSesiones,
                 estaticos: Estaticos, canal: CanalEventos, dev: bool = False,
                 despachador_local: Despachador | None = None,
                 oauth: Callable[[str], tuple[int, bytes]] | None = None) -> None:
        self.despachador = despachador
        self.sesiones = sesiones
        self.estaticos = estaticos
        self.canal = canal
        self.dev = dev
        self.despachador_local = despachador_local          # rev. 5: /api/display/* (solo la ventana local)
        self.oauth = oauth                                   # rev. 5: GET /oauth/tiktok → (status, página HTML)
        self.cubeta_oauth = seguridad.Cubeta(TASA_OAUTH, 5)
        self.cerrando = False
        self.puerto = 0
        super().__init__(direccion, Manejador)
        self.puerto = int(self.server_address[1])

    def server_bind(self) -> None:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)               # sin getfqdn() (lento y sin uso aquí)
        host, puerto = self.server_address[:2]
        self.server_name, self.server_port = str(host), int(puerto)

    def handle_error(self, request: Any, client_address: Any) -> None:   # nunca a stderr ni con datos de la petición
        tipo = sys.exc_info()[0]
        _log.warning('Error al atender una conexión de la interfaz (%s)', tipo.__name__ if tipo else '?')


def puertos_candidatos(puerto_ui: int | None) -> tuple[list[int], bool]:
    """(puertos a probar en orden, si hay respaldo). None = 39229 + 39228…39220 · 0 = al azar · n = solo n."""
    if puerto_ui is None:
        return [config.PUERTO_UI, *config.PUERTOS_UI_RESPALDO], True
    if isinstance(puerto_ui, bool) or not isinstance(puerto_ui, int) or not 0 <= puerto_ui <= 65535:
        raise ValueError(f'puerto_ui inválido: {puerto_ui!r}')
    return [puerto_ui], False


def enlazar(puerto_ui: int | None, fabrica: Callable[[tuple[str, int]], ServidorUI]) -> tuple[ServidorUI, bool]:
    """Bind SÍNCRONO (C8). Devuelve (servidor, puerto_respaldo). Lanza OSError si ningún puerto sirve."""
    puertos, con_respaldo = puertos_candidatos(puerto_ui)
    ultimo: OSError | None = None
    for i, p in enumerate(puertos):
        try:
            srv = fabrica((config.HOST_UI, p))
        except OSError as e:
            ultimo = e
            continue
        respaldo = con_respaldo and i > 0
        if respaldo:
            _log.warning('Puerto %d ocupado; interfaz en %d', config.PUERTO_UI, srv.puerto)
        return srv, respaldo
    raise OSError(f'No hay puerto libre para la interfaz ({puertos[0]}…{puertos[-1]})') from ultimo


class ServidorLocal:
    """Dueño del ServidorUI y de su hilo `servidor-local`."""

    def __init__(self, despachador: Despachador, sesiones: GestorSesiones, estaticos: Estaticos, canal: CanalEventos,
                 puerto_ui: int | None, dev: bool = False, despachador_local: Despachador | None = None,
                 oauth: Callable[[str], tuple[int, bytes]] | None = None) -> None:
        self.canal = canal
        self.servidor, self.respaldo = enlazar(
            puerto_ui, lambda d: ServidorUI(d, despachador, sesiones, estaticos, canal, dev, despachador_local, oauth))
        self.puerto = self.servidor.puerto
        self._hilo: threading.Thread | None = None

    def iniciar(self) -> None:
        self._hilo = threading.Thread(target=self.servidor.serve_forever, kwargs={'poll_interval': 0.1},
                                      name='servidor-local', daemon=True)
        self._hilo.start()

    def detener(self, tope_s: float = 2.0) -> None:
        self.servidor.cerrando = True
        self.canal.cerrar_todas()
        if self._hilo is not None and self._hilo.is_alive():
            hecho = threading.Event()

            def apagar() -> None:
                try:
                    self.servidor.shutdown()
                finally:
                    hecho.set()

            threading.Thread(target=apagar, name='servidor-local-apagar', daemon=True).start()
            hecho.wait(max(0.1, tope_s))
        try:
            self.servidor.server_close()
        except OSError:
            pass
        if self._hilo is not None:
            self._hilo.join(max(0.0, min(1.0, tope_s)))
