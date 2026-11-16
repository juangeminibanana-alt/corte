"""Cliente de la Display API de TikTok for Developers (rev. 5). Transporte INYECTADO (`interfaces.Transporte`).

`crear_cliente_display(boveda, transporte, reloj)` → `ClienteDisplay`:

- `url_autorizacion(...)`: https://www.tiktok.com/v2/auth/authorize/ con client_key, scope (separados por coma),
  response_type=code, redirect_uri, state, code_challenge (SHA-256 HEX del verifier) y code_challenge_method=S256.
- `canjear(code, verifier, redirect_uri)`: POST https://open.tiktokapis.com/v2/oauth/token/
  (application/x-www-form-urlencoded) con grant_type=authorization_code. Devuelve los tokens normalizados con sus
  vencimientos absolutos (expires_in ≈ 2 h, refresh_expires_in ≈ 180 días), open_id y scopes concedidos.
- `refrescar(token_visto)`: SINGLE-FLIGHT (`lock_refresh`). TikTok ROTA el refresh_token: el nuevo se guarda de
  INMEDIATO en la bóveda (DPAPI: `.nuevo` + fsync + `os.replace`), antes de devolver el access_token; reusar el viejo
  obligaría a volver a conectar. Si mientras tanto alguien desconectó o cambió las credenciales (`epoca_credenciales`
  distinta), los tokens nuevos se descartan. Un timeout de LECTURA se reintenta una sola vez con el mismo refresh_token
  (la petición salió y TikTok pudo haberlo rotado ya). Rechazo, refresh vencido u otra cuenta → `reautorizar` (queda
  marcado en la bóveda y se avisa con `al_cambiar`).
- `revocar()`: POST /v2/oauth/revoke/ (client_key, client_secret, token). True si TikTok lo aceptó.
- `usuario()`: GET /v2/user/info/?fields=… pidiendo SOLO los campos de los scopes concedidos (cada campo pide el suyo).
- `listar_videos(tope, cancelar)`: POST /v2/video/list/?fields=… con {max_count: 20, cursor?}, paginando por cursor
  mientras has_more (solo videos PÚBLICOS). `ListadoVideos.completo` dice si se llegó al final (no al tope).
- Errores: `data.error {code, message, log_id}` o un error HTTP → `ErrorDisplay`. access_token inválido o vencido →
  refresh + 1 reintento; scope_not_authorized → permiso_faltante.

Nunca se registra una URL con datos, una cabecera, un cuerpo, el `code`, el verifier ni un token: solo códigos cortos,
el estado HTTP y el `log_id` de TikTok.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.parse
from typing import Any, Callable, Iterator, Mapping, Sequence

from ..errores import ErrorRed, ErrorTimeoutLectura
from ..interfaces import Json, Reloj, Transporte
from .boveda import BovedaDisplay
from .errores import ErrorDisplay

_log = logging.getLogger('creatorhub.tiktok_dev.cliente')

URL_AUTORIZAR = 'https://www.tiktok.com/v2/auth/authorize/'
HOST_API = 'open.tiktokapis.com'
API = f'https://{HOST_API}'
P_TOKEN = '/v2/oauth/token/'
P_REVOCAR = '/v2/oauth/revoke/'
P_USUARIO = '/v2/user/info/'
P_VIDEOS = '/v2/video/list/'
SCOPES: tuple[str, ...] = ('user.info.basic', 'user.info.profile', 'user.info.stats', 'video.list')
CAMPOS_POR_SCOPE: dict[str, tuple[str, ...]] = {
    'user.info.basic': ('open_id', 'union_id', 'avatar_url', 'display_name'),
    'user.info.profile': ('bio_description', 'profile_deep_link', 'is_verified', 'username'),
    'user.info.stats': ('follower_count', 'following_count', 'likes_count', 'video_count'),
}
CAMPOS_USUARIO: tuple[str, ...] = tuple(c for cs in CAMPOS_POR_SCOPE.values() for c in cs)
CAMPOS_VIDEO: tuple[str, ...] = ('id', 'create_time', 'cover_image_url', 'share_url', 'video_description', 'duration',
                                 'title', 'embed_link', 'like_count', 'comment_count', 'share_count', 'view_count')
MAX_POR_PAGINA = 20
TOPE_VIDEOS = 1000
UMBRAL_PROACTIVO_S = 300                 # refresh si al access_token le quedan < 5 min
REINTENTOS_TIMEOUT_REFRESH = 1
CODIGOS_TOKEN = frozenset({'access_token_invalid', 'access_token_expired', 'token_expired', 'invalid_token',
                           'token_invalid', 'expired_token'})
CODIGOS_PERMISO = frozenset({'scope_not_authorized', 'scope_permission_missed', 'permission_denied'})
CODIGOS_CAIDA = frozenset({'internal_error', 'server_error', 'temporarily_unavailable', 'service_unavailable'})


def _entero(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _codigo_y_log(cuerpo: Mapping[str, Any]) -> tuple[str, str | None]:
    """(código de error en minúsculas o '', log_id) de las dos formas que usa TikTok: `error` objeto {code, log_id}
    (rutas de datos) o `error` texto + `log_id` aparte (rutas de OAuth)."""
    error = cuerpo.get('error')
    if isinstance(error, Mapping):
        codigo, log_id = error.get('code'), error.get('log_id')
    else:
        codigo, log_id = error, cuerpo.get('log_id')
    return (str(codigo).strip().lower() if codigo not in (None, '') else ''), (log_id if isinstance(log_id, str) else None)


class ListadoVideos:
    """Iterador de páginas de video/list (listas de dicts crudos). `completo` = TikTok dijo has_more=false."""

    def __init__(self, cliente: 'ClienteDisplay', tope: int, cancelar: threading.Event | None) -> None:
        self.cliente = cliente
        self.tope = max(1, int(tope))
        self.cancelar = cancelar
        self.completo = False
        self.paginas = 0

    def __iter__(self) -> Iterator[list[dict[str, Any]]]:
        cursor: int | None = None
        vistos = 0
        usados: set[int] = set()
        while vistos < self.tope:
            if self.cancelar is not None and self.cancelar.is_set():
                return
            cuerpo: dict[str, Any] = {'max_count': min(MAX_POR_PAGINA, self.tope - vistos)}
            if cursor is not None:
                cuerpo['cursor'] = cursor
            data = self.cliente._llamar('POST', P_VIDEOS, CAMPOS_VIDEO, cuerpo)
            self.paginas += 1
            crudos = data.get('videos')
            lista = [v for v in crudos if isinstance(v, dict)] if isinstance(crudos, list) else []
            vistos += len(lista)
            siguiente = _entero(data.get('cursor'))
            mas = data.get('has_more') is True
            yield lista
            if not mas:
                self.completo = True
                return
            if not lista or siguiente is None or siguiente in usados:    # nunca un bucle sin fin
                return
            usados.add(siguiente)
            cursor = siguiente


class ClienteDisplay:
    """Llamadas a la Display API con la bóveda de la Display API. Seguro entre hilos."""

    def __init__(self, boveda: BovedaDisplay, transporte: Transporte, reloj: Reloj) -> None:
        self.boveda, self.transporte, self.reloj = boveda, transporte, reloj
        self.lock_refresh = threading.Lock()
        self.al_cambiar: Callable[[], None] | None = None       # el servicio publica display.cambio
        self.llamadas = 0
        self.refrescos = 0

    # ================================================================ OAuth
    @staticmethod
    def url_autorizacion(client_key: str, redirect_uri: str, state: str, challenge: str,
                         scopes: Sequence[str] = SCOPES) -> str:
        return URL_AUTORIZAR + '?' + urllib.parse.urlencode({
            'client_key': client_key, 'scope': ','.join(scopes), 'response_type': 'code',
            'redirect_uri': redirect_uri, 'state': state, 'code_challenge': challenge,
            'code_challenge_method': 'S256'})

    def _post_form(self, ruta: str, campos: Mapping[str, str]) -> tuple[int, Json | None]:
        cuerpo = urllib.parse.urlencode(dict(campos)).encode('ascii')
        cab = {'Content-Type': 'application/x-www-form-urlencoded', 'Cache-Control': 'no-cache'}
        status, datos = self.transporte.manejar('POST', API + ruta, cab, cuerpo)
        self.llamadas += 1
        return int(status), datos

    @staticmethod
    def _error_token(status: int, codigo: str, log_id: str | None, al_refrescar: bool) -> ErrorDisplay:
        if status == 429 or codigo == 'rate_limit_exceeded':
            return ErrorDisplay('limite', http=status, log_id=log_id)
        if status >= 500 or codigo in CODIGOS_CAIDA:
            return ErrorDisplay('tiktok_no_disponible', http=status, log_id=log_id)
        if codigo in ('invalid_client', 'unauthorized_client'):
            return ErrorDisplay('credenciales_rechazadas', http=status, log_id=log_id, reautorizar=al_refrescar)
        if al_refrescar:
            return ErrorDisplay('reautorizar', http=status, log_id=log_id)
        if codigo == 'invalid_grant':
            return ErrorDisplay('codigo_vencido', http=status, log_id=log_id)
        if codigo in ('invalid_request', 'invalid_scope', 'access_denied'):
            return ErrorDisplay('solicitud_rechazada', http=status, log_id=log_id)
        return ErrorDisplay('respuesta_invalida', http=status, log_id=log_id)

    def _tokens(self, status: int, cuerpo: Json | None, al_refrescar: bool) -> dict[str, Any]:
        """Respuesta de /v2/oauth/token/ → {access_token, refresh_token, access_expira_at, refresh_expira_at, open_id,
        scopes}. Lanza ErrorDisplay clasificado."""
        if not isinstance(cuerpo, dict):
            raise self._error_token(status, '', None, al_refrescar) if status >= 400 else ErrorDisplay(
                'respuesta_invalida', http=status)
        codigo, log_id = _codigo_y_log(cuerpo)
        if status >= 400 or codigo not in ('', 'ok'):
            e = self._error_token(status, codigo, log_id, al_refrescar)
            _log.info('Display API: el canje o la renovación falló (%s, HTTP %d, log_id %s)', e.codigo, status, e.log_id)
            raise e
        access, refresh = cuerpo.get('access_token'), cuerpo.get('refresh_token')
        exp, rexp = _entero(cuerpo.get('expires_in')), _entero(cuerpo.get('refresh_expires_in'))
        open_id = cuerpo.get('open_id')
        if (not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh
                or exp is None or exp <= 0 or rexp is None or rexp <= 0 or not isinstance(open_id, str) or not open_id):
            raise ErrorDisplay('respuesta_invalida', http=status, log_id=log_id)
        scope = cuerpo.get('scope')
        scopes = [s.strip() for s in scope.split(',') if s.strip()] if isinstance(scope, str) else []
        ahora = int(self.reloj.ahora())
        return {'access_token': access, 'refresh_token': refresh, 'access_expira_at': ahora + exp,
                'refresh_expira_at': ahora + rexp, 'open_id': open_id, 'scopes': scopes}

    def canjear(self, code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
        d = self.boveda.leer()
        if not (d.get('client_key') and d.get('client_secret')):
            raise ErrorDisplay('sin_credenciales')
        campos = {'client_key': str(d['client_key']), 'client_secret': str(d['client_secret']), 'code': code,
                  'grant_type': 'authorization_code', 'redirect_uri': redirect_uri, 'code_verifier': verifier}
        try:
            status, cuerpo = self._post_form(P_TOKEN, campos)
        except ErrorTimeoutLectura:
            raise ErrorDisplay('tiktok_no_disponible') from None     # el code pudo consumirse: hay que reintentar
        except ErrorRed:
            raise ErrorDisplay('sin_internet') from None
        return self._tokens(status, cuerpo, al_refrescar=False)

    # ================================================================ refresh con rotación
    def _marcar_reautorizar(self, e: ErrorDisplay, epoca0: int) -> None:
        try:
            with self.boveda.candado:
                if int(self.boveda.leer().get('epoca_credenciales') or 0) != epoca0:
                    return                                       # ya cambiaron las credenciales: nada que marcar
                self.boveda.mutar(lambda d: d.update(reautorizar=True,
                                                     ultimo_error=e.como_dict(self.reloj.ahora())))
        except OSError as err:
            _log.warning('No se pudo marcar la conexión de la Display API como vencida (%s)', type(err).__name__)
        _log.info('La conexión de la Display API necesita volver a autorizarse (%s)', e.codigo)
        if self.al_cambiar is not None:
            try:
                self.al_cambiar()
            except Exception:  # noqa: BLE001 - avisar nunca tumba la llamada
                _log.warning('No se pudo avisar el cambio de la Display API', exc_info=True)

    def _guardar_tokens_si(self, epoca0: int, tokens: Mapping[str, Any]) -> bool:
        """Persiste los tokens rotados de inmediato (escritura atómica de la bóveda) salvo que alguien haya
        desconectado o cambiado las credenciales mientras el refresh estaba en la red."""
        with self.boveda.candado:
            actual = self.boveda.leer()
            if int(actual.get('epoca_credenciales') or 0) != epoca0 or not actual.get('refresh_token'):
                _log.info('La conexión de la Display API cambió mientras se renovaba: se descartan los tokens nuevos')
                return False
            try:
                self.boveda.mutar(lambda d: d.update(dict(tokens), reautorizar=False, ultimo_error=None))
            except OSError as e:
                _log.error('No se pudo guardar la conexión renovada de la Display API (%s)', type(e).__name__)
                raise ErrorDisplay('error_interno') from None
            return True

    def refrescar(self, token_visto: str | None = None) -> str:
        """Renueva el access_token (single-flight) y devuelve el vigente."""
        with self.lock_refresh:
            d = self.boveda.leer()
            if not (d.get('client_key') and d.get('client_secret')):
                raise ErrorDisplay('sin_credenciales')
            if not d.get('refresh_token'):
                raise ErrorDisplay('sin_conexion')
            ahora = int(self.reloj.ahora())
            exp = _entero(d.get('access_expira_at'))
            actual = d.get('access_token')
            if (token_visto is not None and actual and actual != token_visto and exp is not None
                    and exp - ahora >= UMBRAL_PROACTIVO_S):
                return str(actual)                               # otro hilo ya lo renovó mientras esperábamos
            epoca0 = int(d.get('epoca_credenciales') or 0)
            rexp = _entero(d.get('refresh_expira_at'))
            if rexp is not None and rexp <= ahora:
                e = ErrorDisplay('reautorizar')
                self._marcar_reautorizar(e, epoca0)
                raise e
            campos = {'client_key': str(d['client_key']), 'client_secret': str(d['client_secret']),
                      'grant_type': 'refresh_token', 'refresh_token': str(d['refresh_token'])}
            status, cuerpo = 0, None
            for intento in range(REINTENTOS_TIMEOUT_REFRESH + 1):
                try:
                    status, cuerpo = self._post_form(P_TOKEN, campos)
                    break
                except ErrorTimeoutLectura:
                    # La petición SALIÓ: TikTok pudo haber rotado ya el refresh_token. Un solo reintento con el mismo;
                    # si ya lo rotó, lo rechaza y toca volver a conectar (el nuevo nunca llegó).
                    if intento >= REINTENTOS_TIMEOUT_REFRESH:
                        raise ErrorDisplay('tiktok_no_disponible') from None
                except ErrorRed:
                    raise ErrorDisplay('sin_internet') from None
            try:
                tokens = self._tokens(status, cuerpo, al_refrescar=True)
            except ErrorDisplay as e:
                if e.reautorizar:
                    self._marcar_reautorizar(e, epoca0)
                raise
            previo = d.get('open_id')
            if previo and tokens['open_id'] != previo:
                e = ErrorDisplay('reautorizar')
                self._marcar_reautorizar(e, epoca0)
                raise e
            if not tokens['scopes']:
                tokens.pop('scopes')                             # la renovación no los trajo: se conservan
            if not self._guardar_tokens_si(epoca0, tokens):
                raise ErrorDisplay('sin_conexion')
            self.refrescos += 1
            _log.info('Conexión de la Display API renovada (refresh_token rotado y guardado)')
            return str(tokens['access_token'])

    def revocar(self) -> bool:
        d = self.boveda.leer()
        token = d.get('access_token')
        if not (d.get('client_key') and d.get('client_secret') and token):
            return False
        try:
            status, cuerpo = self._post_form(P_REVOCAR, {'client_key': str(d['client_key']),
                                                         'client_secret': str(d['client_secret']), 'token': str(token)})
        except ErrorRed:
            return False
        if status != 200:
            return False
        codigo = _codigo_y_log(cuerpo)[0] if isinstance(cuerpo, dict) else ''
        return codigo in ('', 'ok')

    # ================================================================ datos
    def _token_para_llamar(self) -> tuple[str, int]:
        d = self.boveda.leer()
        if not (d.get('client_key') and d.get('client_secret')):
            raise ErrorDisplay('sin_credenciales')
        if not (d.get('access_token') and d.get('refresh_token')):
            raise ErrorDisplay('sin_conexion')
        if d.get('reautorizar'):
            raise ErrorDisplay('reautorizar')
        epoca = int(d.get('epoca_credenciales') or 0)
        exp = _entero(d.get('access_expira_at'))
        if exp is None or exp - int(self.reloj.ahora()) < UMBRAL_PROACTIVO_S:
            return self.refrescar(token_visto=str(d['access_token'])), epoca
        return str(d['access_token']), epoca

    @staticmethod
    def _error_api(status: int, resp: Json | None) -> ErrorDisplay | None:
        codigo, log_id = _codigo_y_log(resp) if isinstance(resp, dict) else ('', None)
        if isinstance(resp, dict) and status == 200 and codigo in ('', 'ok'):
            return None
        if codigo in CODIGOS_TOKEN or status == 401:
            return ErrorDisplay('token_invalido', http=status, log_id=log_id)
        if codigo in CODIGOS_PERMISO or status == 403:
            return ErrorDisplay('permiso_faltante', http=status, log_id=log_id)
        if codigo == 'rate_limit_exceeded' or status == 429:
            return ErrorDisplay('limite', http=status, log_id=log_id)
        if codigo in CODIGOS_CAIDA or status >= 500:
            return ErrorDisplay('tiktok_no_disponible', http=status, log_id=log_id)
        return ErrorDisplay('respuesta_invalida', http=status, log_id=log_id)

    def _llamar(self, metodo: str, ruta: str, campos: Sequence[str], cuerpo: Json | None = None) -> dict[str, Any]:
        token, epoca = self._token_para_llamar()
        url = API + ruta + '?' + urllib.parse.urlencode({'fields': ','.join(campos)})
        datos = None if cuerpo is None else json.dumps(cuerpo, separators=(',', ':')).encode('utf-8')
        for intento in (0, 1):
            cab = {'Authorization': f'Bearer {token}'}
            if datos is not None:
                cab['Content-Type'] = 'application/json'
            try:
                status, resp = self.transporte.manejar(metodo, url, cab, datos)
            except ErrorTimeoutLectura:
                raise ErrorDisplay('tiktok_no_disponible') from None
            except ErrorRed:
                raise ErrorDisplay('sin_internet') from None
            self.llamadas += 1
            err = self._error_api(int(status), resp)
            if err is None:
                data = (resp or {}).get('data')
                return data if isinstance(data, dict) else {}
            if err.codigo == 'token_invalido':
                if intento == 0:
                    token = self.refrescar(token_visto=token)        # refresh + 1 reintento
                    continue
                err = ErrorDisplay('reautorizar', http=err.http, log_id=err.log_id)
                self._marcar_reautorizar(err, epoca)
            _log.info('Display API %s: %s (HTTP %s, log_id %s)', ruta, err.codigo, err.http, err.log_id)
            raise err
        raise ErrorDisplay('error_interno')                          # inalcanzable

    def usuario(self) -> dict[str, Any]:
        """`data.user` de user/info con los campos de los scopes concedidos (si no se conocen, todos)."""
        concedidos = set(self.boveda.leer().get('scopes') or [])
        campos = [c for s, cs in CAMPOS_POR_SCOPE.items() if not concedidos or s in concedidos for c in cs]
        data = self._llamar('GET', P_USUARIO, campos or CAMPOS_POR_SCOPE['user.info.basic'])
        user = data.get('user')
        if not isinstance(user, dict):
            raise ErrorDisplay('respuesta_invalida')
        return user

    def listar_videos(self, tope: int = TOPE_VIDEOS, cancelar: threading.Event | None = None) -> ListadoVideos:
        return ListadoVideos(self, tope, cancelar)


def crear_cliente_display(boveda: BovedaDisplay, transporte: Transporte, reloj: Reloj) -> ClienteDisplay:
    return ClienteDisplay(boveda, transporte, reloj)


def crear_transporte_display_real() -> Transporte:
    """urllib + TLS por defecto, conexión 10 s, lectura 30 s, sin redirecciones y SOLO open.tiktokapis.com."""
    from ..tiktok.transporte import TransporteHttps
    return TransporteHttps(hosts=frozenset({HOST_API}))


__all__ = ['ClienteDisplay', 'ListadoVideos', 'crear_cliente_display', 'crear_transporte_display_real', 'SCOPES',
           'CAMPOS_USUARIO', 'CAMPOS_VIDEO', 'CAMPOS_POR_SCOPE', 'URL_AUTORIZAR', 'API', 'HOST_API', 'P_TOKEN',
           'P_REVOCAR', 'P_USUARIO', 'P_VIDEOS', 'TOPE_VIDEOS', 'MAX_POR_PAGINA']
