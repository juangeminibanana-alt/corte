"""Transporte real hacia TikTok (03 §2.1 pasos 4–6; BUILD_SPEC §6.2 `Transporte`).

- `urllib.request` de la librería estándar con un `OpenerDirector` armado a mano: SOLO el manejador HTTPS propio (sin
  redirecciones, sin proxy del entorno, sin `HTTPErrorProcessor`: un 4xx/5xx se devuelve como respuesta, no como
  excepción). Una URL firmada nunca se reenvía a otro host.
- TLS con la verificación por defecto de `ssl.create_default_context()` (certificado y nombre de host obligatorios).
- Timeouts separados: **conexión 10 s** (TCP + TLS, en `_Conexion*.connect`) y **lectura 30 s** (el `timeout` que urllib
  pasa a la conexión y que queda en el socket ya conectado).
- Clasificación: si la falla ocurre ANTES de enviar la petición completa (DNS, conexión, TLS, envío: urllib la envuelve
  en `URLError`) → `ErrorRed`; si ocurre DESPUÉS (timeout o corte al leer la respuesta) → `ErrorTimeoutLectura`,
  porque TikTok pudo haberla procesado (p. ej. rotar el refresh_token).
- Solo `https` y solo los hosts de TikTok (`HOSTS_TIKTOK`): cualquier otro destino → `ErrorRed` sin abrir socket.
- Devuelve `(status, dict | None)`: None = el cuerpo no era un objeto JSON.
- Las excepciones solo llevan el NOMBRE del tipo de error: nunca la URL (la del refresh trae app_secret y
  refresh_token en la query) ni las cabeceras.
- `cabeceras_respuesta()` (extra, por hilo): cabeceras de la última respuesta recibida en ESTE hilo, en minúsculas; el
  cliente lee `date` (desfase de reloj) y `retry-after`. El Protocol `Transporte` no las expone (faltante anotado en la
  entrega de hub-nucleo); un transporte sin este método simplemente no aporta desfase ni Retry-After.
"""
from __future__ import annotations

import functools
import http.client
import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from ..errores import ErrorRed, ErrorTimeoutLectura
from ..interfaces import Json, Transporte

_log = logging.getLogger('creatorhub.tiktok.transporte')

HOSTS_TIKTOK: frozenset[str] = frozenset({'open-api.tiktokglobalshop.com', 'auth.tiktok-shops.com'})
TIMEOUT_CONEXION_S = 10.0
TIMEOUT_LECTURA_S = 30.0
MAX_RESPUESTA_BYTES = 32 * 1024 * 1024
METODOS = frozenset({'GET', 'POST', 'PUT', 'DELETE'})


# ------------------------------------------------------------------ conexiones con tope de conexión propio
class _ConexionHttp(http.client.HTTPConnection):
    """`timeout` (el que pasa urllib) es el de LECTURA; `connect()` usa `timeout_conexion` y luego deja el de lectura
    en el socket. Solo para pruebas contra 127.0.0.1 (nunca desde `crear_transporte_real`)."""

    def __init__(self, *args: Any, timeout_conexion: float, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.timeout_conexion = timeout_conexion

    def connect(self) -> None:
        lectura = self.timeout
        self.timeout = self.timeout_conexion
        try:
            super().connect()
        finally:
            self.timeout = lectura
        if self.sock is not None:
            self.sock.settimeout(lectura)


class _ConexionHttps(http.client.HTTPSConnection):
    """Ídem con TLS: el apretón de manos TLS también cuenta dentro del tope de conexión."""

    def __init__(self, *args: Any, timeout_conexion: float, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.timeout_conexion = timeout_conexion

    def connect(self) -> None:
        lectura = self.timeout
        self.timeout = self.timeout_conexion
        try:
            super().connect()                      # TCP + wrap_socket (handshake) con el tope de conexión
        finally:
            self.timeout = lectura
        if self.sock is not None:
            self.sock.settimeout(lectura)


class _ManejadorHttps(urllib.request.HTTPSHandler):
    def __init__(self, contexto: Any, timeout_conexion: float) -> None:
        super().__init__(context=contexto)
        self._timeout_conexion = timeout_conexion

    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(functools.partial(_ConexionHttps, timeout_conexion=self._timeout_conexion), req,
                            context=self._context)


class _ManejadorHttp(urllib.request.HTTPHandler):
    def __init__(self, timeout_conexion: float) -> None:
        super().__init__()
        self._timeout_conexion = timeout_conexion

    def http_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(functools.partial(_ConexionHttp, timeout_conexion=self._timeout_conexion), req)


def _nombre_causa(e: urllib.error.URLError) -> str:
    causa = getattr(e, 'reason', None)
    return type(causa).__name__ if isinstance(causa, BaseException) else type(e).__name__


# ------------------------------------------------------------------ transporte
class TransporteHttps:
    """Implementa `Transporte` con `urllib.request`. Seguro entre hilos (una conexión por petición)."""

    def __init__(self, timeout_conexion: float = TIMEOUT_CONEXION_S, timeout_lectura: float = TIMEOUT_LECTURA_S,
                 hosts: frozenset[str] = HOSTS_TIKTOK, solo_https: bool = True) -> None:
        self.timeout_conexion = float(timeout_conexion)
        self.timeout_lectura = float(timeout_lectura)
        self.hosts = frozenset(h.lower() for h in hosts)
        self.solo_https = solo_https          # False solo en pruebas contra 127.0.0.1 (nunca desde crear_transporte_real)
        self._ctx: Any = None
        self._opener: urllib.request.OpenerDirector | None = None
        self._candado = threading.Lock()
        self._local = threading.local()

    # -------------------------------------------------------------- TLS y opener (perezosos: no pesan en el arranque)
    def contexto_tls(self) -> Any:
        with self._candado:
            if self._ctx is None:
                import ssl
                self._ctx = ssl.create_default_context()
            return self._ctx

    def opener(self) -> urllib.request.OpenerDirector:
        """OpenerDirector SOLO con los manejadores propios: sin redirecciones, sin proxy y sin HTTPErrorProcessor."""
        ctx = self.contexto_tls()
        with self._candado:
            if self._opener is None:
                op = urllib.request.OpenerDirector()
                op.addheaders = []                                   # sin 'Python-urllib/…'
                op.add_handler(_ManejadorHttps(ctx, self.timeout_conexion))
                if not self.solo_https:
                    op.add_handler(_ManejadorHttp(self.timeout_conexion))
                self._opener = op
            return self._opener

    def cabeceras_respuesta(self) -> dict[str, str]:
        """Cabeceras (en minúsculas) de la última respuesta recibida en este hilo; {} si no hubo."""
        return dict(getattr(self._local, 'cabeceras', None) or {})

    # -------------------------------------------------------------- petición
    def _validar_destino(self, url: str) -> None:
        try:
            u = urllib.parse.urlsplit(url)
            esquema = u.scheme.lower()
            host = (u.hostname or '').lower()
            u.port                                                    # puerto inválido → ValueError
        except ValueError:
            raise ErrorRed('UrlInvalida') from None
        if u.username or u.password or not host:
            raise ErrorRed('DestinoNoPermitido')
        if esquema == 'https' and host in self.hosts:
            return
        if not self.solo_https and esquema == 'http' and host == '127.0.0.1':
            return
        raise ErrorRed('DestinoNoPermitido')

    def manejar(self, metodo: str, url: str, cabeceras: Mapping[str, str], cuerpo: bytes | None) -> tuple[int, Json | None]:
        self._local.cabeceras = {}
        metodo = str(metodo).upper()
        if metodo not in METODOS:
            raise ValueError(f'método no permitido: {metodo!r}')
        self._validar_destino(url)
        enviar = {str(k): str(v) for k, v in cabeceras.items()}
        if not any(k.lower() == 'accept' for k in enviar):
            enviar['Accept'] = 'application/json'
        if not any(k.lower() == 'accept-encoding' for k in enviar):
            enviar['Accept-Encoding'] = 'identity'
        req = urllib.request.Request(url, data=cuerpo, headers=enviar, method=metodo)
        op = self.opener()
        # 1) Conexión, TLS y envío (urllib los envuelve en URLError): la petición todavía no salió completa.
        # 2) getresponse(): la petición ya salió; una falla aquí pudo haber sido procesada por TikTok.
        try:
            resp = op.open(req, timeout=self.timeout_lectura)
        except urllib.error.URLError as e:
            raise ErrorRed(_nombre_causa(e)) from None
        except (OSError, http.client.HTTPException) as e:
            raise ErrorTimeoutLectura(type(e).__name__) from None
        if resp is None:                                              # sin manejador para el esquema (no debería)
            raise ErrorRed('DestinoNoPermitido')
        try:
            status = int(resp.status)
            self._local.cabeceras = {k.lower(): v for k, v in resp.getheaders()}
            # 3) Cuerpo: también después de enviar.
            try:
                datos = resp.read(MAX_RESPUESTA_BYTES + 1)
            except (OSError, http.client.HTTPException) as e:
                raise ErrorTimeoutLectura(type(e).__name__) from None
        finally:
            try:
                resp.close()
            except OSError:
                pass
        if len(datos) > MAX_RESPUESTA_BYTES:
            _log.warning('Respuesta de TikTok demasiado grande (%d bytes): se descarta', len(datos))
            return status, None
        try:
            obj = json.loads(datos.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            return status, None
        return status, obj if isinstance(obj, dict) else None


def crear_transporte_real() -> Transporte:
    """Transporte de producción: urllib, https, solo hosts de TikTok, conexión 10 s, lectura 30 s, TLS por defecto."""
    return TransporteHttps()


# Sinónimo con el nombre de la spec (03 §2.1: «transporte urllib»).
TransporteUrllib = TransporteHttps
