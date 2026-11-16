"""Autorización del creador con TikTok (solo la UI local de Windows; 03 §2.2, §7.8, §8; BUILD_SPEC C35, C37, C42, C46).

`crear_auth(boveda, cliente, almacen, bus, reloj, coordinador, modo)` → `ServicioAuthReal`:

- `link()`: `state = secrets.token_urlsafe(24)` en `oauth_states`, vigente **10 min** y de **un solo uso** (C37);
  `https://shop.tiktok.com/alliance/creator/auth?app_key=…&state=…`; con `abrir_navegador` se abre con `os.startfile`.
- `portapapeles()`: solo lee con un `state` vivo y en modo real (04 §A.8). Nunca devuelve el `code`.
- `canjear(req)`: URL pegada, `code` suelto (solo con exactamente un `state` activo) o el del portapapeles. `state`
  desconocido, usado o vencido → 400 `state_invalido`. `GET /api/v2/token/get` (literal `authorized_code`). Valida
  `user_type == 1` (422 `no_es_creador`), permisos indispensables (422 `sin_permiso_tiktok`; los demás van en
  `scopes_faltantes`) y la cuenta: otra → 409 `cuenta_distinta`, salvo `confirmar_cambio_cuenta`, que pasa por
  `coordinador.mutacion_segura(…, 'tiktok')` con los tokens que se guardaron EN MEMORIA al responder el 409 (TikTok
  no deja canjear dos veces el mismo `code`). `confirmar_cuenta` en la primera conexión. El canje no sincroniza. Tras
  el canje se vacía el portapapeles si todavía tiene la URL.
- `desconectar(borrar_datos)`: borra solo la autorización (la clave de la app se conserva); con `borrar_datos` el
  coordinador borra lo descargado de TikTok ('tiktok').
- `refrescar()`, `credenciales_estado()`, `importar(req)` (importador_legado, C46), `guardar_app_secret()`
  (16–128 alfanuméricos, verificada con GET profiles firmado si ya hay conexión), `borrar_legado()` (a la Papelera
  con SHFileOperationW: 'papelera' | 'no_existe') y `purgar_states()`.
- Toda mutación de credenciales pasa por `coordinador.mutacion_segura` (03 §2.6) y sube `epoca_credenciales`.
- En **demo** y **autoprueba** el portapapeles no se lee y las acciones que cambian la conexión o tocan el archivo
  anterior responden 403 `prohibido` (la demo nunca toca credenciales reales).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import threading
import urllib.parse
from typing import Any, Callable, Mapping

from . import importador_legado
from .boveda import APP_KEY_PUBLICA
from .errores import ErrorApi, ErrorAuthTransitorio, ErrorDominio, ErrorRed
from .interfaces import Almacen, Boveda, Bus, ClienteTikTok, Coordinador, Json, ModoHub, Reloj, ServicioAuth
from .portapapeles import HOST_RETORNO, analizar_url_retorno, crear_portapapeles, vista_previa
from .tiktok import conexion as cx

_log = logging.getLogger('creatorhub.auth')

URL_AUTORIZAR = 'https://shop.tiktok.com/alliance/creator/auth'
P_PERFIL = '/affiliate_creator/202508/profiles'
VIGENCIA_STATE_S = 600                  # C37: 10 min, un solo uso
_RE_CODE_SUELTO = frozenset('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~*')
_RE_SECRETO = importador_legado._RE_SECRETO

# Textos visibles (01 §5.4, §4.14; vocabulario de 01 §1.5: «conexión», «permiso», nunca «token» ni «scope»).
MSG_DEMO = 'En el modo de demostración no puedes cambiar la conexión con TikTok.'
MSG_FALTA_CLAVE = 'Para conectar, Corte necesita la clave de tu app de Partner Center (una sola vez).'
MSG_SIN_CONEXION = 'Todavía no conectas tu cuenta de TikTok.'
# Comillas rectas en "code=" y "state=": con las tipográficas, limpiar() taparía el texto como si fuera un valor.
MSG_NO_ES_URL = ('Eso no parece el enlace de regreso. Debe contener "code=". Copia la dirección completa de la página '
                 'a la que llegaste.')
MSG_CANCELADA = 'Cancelaste la autorización en TikTok. Puedes intentarlo cuando quieras.'
MSG_STATE_AJENO = 'Este enlace no corresponde a este intento de conexión. Usa el de la autorización que acabas de hacer.'
MSG_STATE_VENCIDO = 'El enlace ya caducó o ya se usó. Vuelve a autorizar (tarda menos de un minuto).'
MSG_VARIOS_STATES = ('Pega el enlace completo de la página a la que llegaste (contiene "code=" y "state="), no solo el '
                     'código.')
MSG_SIN_PORTAPAPELES = 'No encontramos el enlace de autorización en lo que copiaste. Pégalo aquí.'
MSG_CODIGO_VENCIDO = 'El enlace ya caducó o ya se usó. Vuelve a autorizar (tarda menos de un minuto).'
MSG_NO_CREADOR = ('La cuenta que autorizaste no es de creador de TikTok Shop. Cierra sesión en TikTok Shop y vuelve a '
                  'intentarlo con tu cuenta de creador.')
MSG_SIN_INTERNET = ('No pudimos hablar con TikTok. Revisa tu internet e inténtalo de nuevo. Tu enlace caduca en unos '
                    'minutos.')
MSG_SIN_RESPUESTA = 'TikTok no respondió a tiempo. Vuelve a autorizar (tarda menos de un minuto).'
MSG_INCOMPLETA = 'TikTok respondió de forma incompleta. Vuelve a autorizar (tarda menos de un minuto).'
MSG_CUENTA_DISTINTA = ('Este enlace es de otra cuenta de TikTok. Si continúas, borraremos de esta PC los datos de la '
                       'cuenta anterior; tu plan, tus avisos y tus notas se conservan.')
MSG_CLAVE_FORMATO = 'La clave de la app debe tener de 16 a 128 letras y números, sin espacios.'
MSG_CLAVE_RECHAZADA = 'TikTok no reconoció la clave de la app. Revisa que sea la de Partner Center de esta app.'
MSG_PAPELERA = 'No pudimos mover el archivo a la Papelera. Bórralo desde el Explorador de archivos.'


def _faltan_permisos(faltan: list[str]) -> str:
    return ', '.join(cx.NOMBRE_PERMISO.get(s, s) for s in faltan)


def _abrir_url_sistema(url: str) -> None:
    os.startfile(url)          # type: ignore[attr-defined]   (solo Windows; el hub es solo Windows)


class ServicioAuthReal:
    """Implementa `ServicioAuth`. Los colaboradores del sistema (portapapeles, navegador, papelera, tipo de unidad,
    rutas del archivo anterior) son atributos sustituibles en pruebas."""

    def __init__(self, boveda: Boveda, cliente: ClienteTikTok, almacen: Almacen, bus: Bus, reloj: Reloj,
                 coordinador: Coordinador, modo: ModoHub) -> None:
        if modo not in ('real', 'demo', 'autoprueba'):
            raise ValueError(f'modo desconocido: {modo!r}')
        self.boveda, self.cliente, self.almacen, self.bus = boveda, cliente, almacen, bus
        self.reloj, self.coordinador, self.modo = reloj, coordinador, modo
        self.portapapeles_sistema: Any = crear_portapapeles() if modo == 'real' else None
        self.abrir_url: Callable[[str], None] = _abrir_url_sistema
        self.papelera: Callable[[str], None] = importador_legado.mover_a_papelera
        self.tipo_unidad: Callable[[str], int] = importador_legado._tipo_unidad
        self.rutas_legado: list[str] | None = None          # None = importador_legado.rutas_conocidas() al usarse
        self._candado = threading.RLock()
        self._pp_cache: tuple[int, Json] | None = None       # (número de secuencia, respuesta)
        self._pp_pendiente: dict[str, Any] | None = None     # {'seq', 'code', 'state'}: solo en memoria
        self._cambio_pendiente: dict[str, Any] | None = None  # tokens de otra cuenta a la espera de confirmación
        self.host_retorno = HOST_RETORNO
        self.ruta_retorno: str | None = None
        self.esquema_retorno = 'https'
        self.puerto_retorno: int | None = 443
        self.nube = False

    # ================================================================ utilidades
    def _ahora_tokens(self) -> int:
        """Reloj corregido por el desfase con TikTok (decisiones de expiración)."""
        try:
            return int(self.cliente.ahora())
        except Exception:  # noqa: BLE001
            return int(self.reloj.ahora())

    def _desfase(self) -> float:
        v = getattr(self.cliente, 'desfase_s', 0.0)
        return float(v) if isinstance(v, (int, float)) else 0.0

    def _exigir_real(self) -> None:
        if self.modo != 'real':
            raise ErrorDominio('prohibido', MSG_DEMO, http=403)

    def _candidatos(self) -> list[str]:
        return list(self.rutas_legado) if self.rutas_legado else importador_legado.rutas_conocidas()

    def _leer_fila(self) -> dict[str, Any] | None:
        with self.almacen.lector() as c:
            return cx.leer_fila(c)

    def _publicar(self) -> None:
        try:
            self.bus.publicar({'tipo': 'conexion.cambio', 'conexion': self.conexion()})
        except Exception as e:  # noqa: BLE001
            _log.warning('No se pudo publicar conexion.cambio (%s)', type(e).__name__)

    def _espejar(self, **extra: Any) -> None:
        """auth_estado = espejo de la bóveda (+ `extra`), en una transacción propia."""
        datos = self.boveda.leer()
        with self.almacen.escritor() as c:
            previo = cx.leer_fila(c)
            campos = cx.espejo(datos)
            estado = cx.estado_base(datos)
            if estado == 'conectada' and (previo or {}).get('estado') in ('reautorizar', 'cuenta_sin_region'):
                estado = previo['estado']               # una bandera solo se limpia con conexión nueva
            campos['estado'] = estado
            campos.update(extra)
            cx.actualizar_fila(c, self.reloj.ahora(), datos.get('app_key'), **campos)

    def _guardar_perfil(self, perfil: Mapping[str, Any]) -> None:
        try:
            with self.almacen.escritor() as c:
                cx.guardar_cuenta(c, perfil, self.reloj.ahora())
        except Exception as e:  # noqa: BLE001
            _log.warning('No se pudo guardar el perfil de la cuenta (%s)', type(e).__name__)

    def _traer_perfil(self) -> Mapping[str, Any] | None:
        try:
            return self.cliente.llamar('GET', P_PERFIL)
        except (ErrorApi, ErrorRed) as e:
            _log.info('No se pudo leer el perfil de la cuenta (%s)', getattr(e, 'codigo', type(e).__name__))
            return None

    # ================================================================ lectura
    def conexion(self) -> Json:
        return cx.construir_conexion(self.boveda.leer(), self._leer_fila(), self._ahora_tokens(), self._desfase())

    def cuenta(self) -> Json | None:
        with self.almacen.lector() as c:
            return cx.construir_cuenta(c)

    def credenciales_estado(self) -> Json:
        d = self.boveda.leer()
        with self.almacen.lector() as c:
            fila = cx.leer_fila(c)
            importado_at = cx.meta_entero(c, 'legado_importado_at')
        origen = d.get('origen') or (fila or {}).get('origen')
        if self.modo == 'real' and not self.nube:
            ruta = importador_legado.ruta_por_omision(self._candidatos())
            disponible = os.path.isfile(ruta)
        else:
            ruta, disponible = '', False                      # la demo nunca mira el archivo real
        return {'app_key': d.get('app_key') or APP_KEY_PUBLICA,
                'app_secret_configurado': bool(d.get('app_secret')),
                'tokens_configurados': bool(d.get('access_token') and d.get('refresh_token')),
                'origen': origen if origen in cx.ORIGENES else None,
                'legado': {'disponible': disponible, 'ruta': ruta, 'ya_importado_at': importado_at}}

    # ================================================================ states (C37)
    def _states_vivos(self, c: Any, ahora: int) -> list[tuple[str, int]]:
        return [(str(r[0]), int(r[1])) for r in
                c.execute('SELECT state, expira_at FROM oauth_states WHERE usado_at IS NULL AND expira_at > ?',
                          (ahora,)).fetchall()]

    def _hay_state_vivo(self) -> bool:
        with self.almacen.lector() as c:
            return bool(self._states_vivos(c, self.reloj.ahora()))

    def _coincide_vivo(self, state: str) -> bool:
        with self.almacen.lector() as c:
            vivos = self._states_vivos(c, self.reloj.ahora())
        s = state.encode('utf-8')
        return any(hmac.compare_digest(v.encode('utf-8'), s) for v, _ in vivos)

    def _consumir_state(self, state: str) -> str:
        """'ok' (consumido) · 'desconocido' · 'usado' · 'vencido'. Atómico: dos canjes con el mismo state → uno gana."""
        ahora = self.reloj.ahora()
        s = state.encode('utf-8')
        with self.almacen.escritor() as c:
            filas = c.execute('SELECT state, expira_at, usado_at FROM oauth_states').fetchall()
            fila = next((f for f in filas if hmac.compare_digest(str(f[0]).encode('utf-8'), s)), None)
            if fila is None:
                return 'desconocido'
            if fila[2] is not None:
                return 'usado'
            if int(fila[1]) <= ahora:
                return 'vencido'
            c.execute('UPDATE oauth_states SET usado_at = ? WHERE state = ? AND usado_at IS NULL', (ahora, fila[0]))
            return 'ok'

    def _consumir_unico(self) -> str:
        """`code` suelto: solo con exactamente UN state activo, que se consume. Devuelve ese state."""
        ahora = self.reloj.ahora()
        with self.almacen.escritor() as c:
            vivos = self._states_vivos(c, ahora)
            if not vivos:
                raise ErrorDominio('state_invalido', MSG_STATE_VENCIDO, http=400)
            if len(vivos) > 1:
                raise ErrorDominio('parametros_invalidos', MSG_VARIOS_STATES, http=400)
            c.execute('UPDATE oauth_states SET usado_at = ? WHERE state = ? AND usado_at IS NULL', (ahora, vivos[0][0]))
            return vivos[0][0]

    def _devolver_state(self, state: str) -> None:
        """La petición a TikTok no salió: el mismo enlace puede reintentarse."""
        try:
            with self.almacen.escritor() as c:
                c.execute('UPDATE oauth_states SET usado_at = NULL WHERE state = ? AND expira_at > ?',
                          (state, self.reloj.ahora()))
        except Exception as e:  # noqa: BLE001
            _log.warning('No se pudo reactivar el enlace de autorización (%s)', type(e).__name__)

    def link(self, abrir_navegador: bool) -> Json:
        self._exigir_real()
        if self.nube:
            abrir_navegador = False
        d = self.boveda.leer()
        if not d.get('app_secret'):
            raise ErrorDominio('sin_credenciales', MSG_FALTA_CLAVE, http=409)
        state = secrets.token_urlsafe(24)
        ahora = self.reloj.ahora()
        expira = ahora + VIGENCIA_STATE_S
        with self.almacen.escritor() as c:
            c.execute('DELETE FROM oauth_states WHERE expira_at <= ?', (ahora,))
            c.execute('INSERT INTO oauth_states(state, creado_at, expira_at, usado_at) VALUES (?, ?, ?, NULL)',
                      (state, ahora, expira))
        url = URL_AUTORIZAR + '?' + urllib.parse.urlencode({'app_key': d.get('app_key') or APP_KEY_PUBLICA,
                                                             'state': state})
        abierto = False
        if abrir_navegador:
            try:
                self.abrir_url(url)
                abierto = True
            except OSError as e:
                _log.warning('No se pudo abrir el navegador (%s)', type(e).__name__)
        with self._candado:
            self._pp_cache = None
        _log.info('Enlace de autorización creado (vigente 10 min)')
        return {'url': url, 'state': state, 'expira_at': expira, 'abierto': abierto}

    def purgar_states(self) -> None:
        ahora = self.reloj.ahora()
        try:
            with self.almacen.escritor() as c:
                c.execute('DELETE FROM oauth_states WHERE expira_at <= ?', (ahora,))
        except Exception as e:  # noqa: BLE001
            _log.warning('No se pudieron purgar los enlaces vencidos (%s)', type(e).__name__)
        vivo = False
        try:
            vivo = self._hay_state_vivo()
        except Exception:  # noqa: BLE001
            pass
        with self._candado:
            if not vivo:
                self._pp_pendiente = None
                self._pp_cache = None
            if self._cambio_pendiente is not None and self._cambio_pendiente['expira'] <= ahora:
                self._cambio_pendiente = None

    # ================================================================ portapapeles (04 §A.8)
    def portapapeles(self) -> Json:
        nada: Json = {'detectado': False, 'vista_previa': None, 'state_coincide': None}
        if self.modo != 'real' or self.portapapeles_sistema is None:
            return nada
        with self._candado:
            if not self._hay_state_vivo():                 # sin state vivo NO se lee
                self._pp_pendiente = None
                self._pp_cache = None
                return dict(nada)
            pp = self.portapapeles_sistema
            seq = pp.numero_secuencia()
            if self._pp_cache is not None and self._pp_cache[0] == seq:
                return dict(self._pp_cache[1])
            respuesta: Json = dict(nada)
            self._pp_pendiente = None
            if pp.hay_texto():
                par = analizar_url_retorno(pp.leer_texto())
                if par is not None:
                    code, state = par
                    coincide = self._coincide_vivo(state)
                    self._pp_pendiente = {'seq': seq, 'code': code, 'state': state}
                    respuesta = {'detectado': True, 'vista_previa': vista_previa(coincide), 'state_coincide': coincide}
            self._pp_cache = (seq, respuesta)
            return dict(respuesta)

    def _del_portapapeles(self) -> tuple[str, str, int]:
        """(code, state, seq) desde lo detectado (si no cambió el portapapeles) o leyendo una vez con state vivo."""
        pp = self.portapapeles_sistema
        if self.modo != 'real' or pp is None:
            raise ErrorDominio('parametros_invalidos', MSG_SIN_PORTAPAPELES, http=400)
        with self._candado:
            seq = pp.numero_secuencia()
            p = self._pp_pendiente
            if p is not None and p['seq'] == seq:
                return p['code'], p['state'], seq
            if not self._hay_state_vivo():
                raise ErrorDominio('state_invalido', MSG_STATE_VENCIDO, http=400)
            par = analizar_url_retorno(pp.leer_texto()) if pp.hay_texto() else None
            if par is None:
                raise ErrorDominio('parametros_invalidos', MSG_SIN_PORTAPAPELES, http=400)
            self._pp_pendiente = {'seq': seq, 'code': par[0], 'state': par[1]}
            return par[0], par[1], seq

    def _seq_con_url(self, code: str) -> int | None:
        """Antes de consumir el state (todavía vivo): ¿el portapapeles tiene ESTA URL? → su número de secuencia."""
        pp = self.portapapeles_sistema
        if self.modo != 'real' or pp is None:
            return None
        try:
            with self._candado:
                seq = pp.numero_secuencia()
                p = self._pp_pendiente
                if p is not None and p['seq'] == seq:
                    return seq if hmac.compare_digest(p['code'].encode(), code.encode()) else None
                if not self._hay_state_vivo() or not pp.hay_texto():
                    return None
                par = analizar_url_retorno(pp.leer_texto())
                return seq if par is not None and hmac.compare_digest(par[0].encode(), code.encode()) else None
        except Exception:  # noqa: BLE001 - el portapapeles nunca debe tumbar el canje
            return None

    def _vaciar_si_sigue(self, seq: int | None) -> None:
        pp = self.portapapeles_sistema
        if seq is None or pp is None:
            return
        try:
            if pp.numero_secuencia() == seq:              # nadie copió otra cosa: sigue la URL de retorno
                pp.vaciar()
        except Exception as e:  # noqa: BLE001
            _log.info('No se pudo vaciar el portapapeles (%s)', type(e).__name__)

    # ================================================================ canje
    def _analizar_entrada(self, texto: str) -> tuple[str, str | None]:
        """(code, state | None) de la URL pegada o del code suelto. Lanza ErrorDominio con el texto de 01 §5.4."""
        t = texto.strip()
        if not t or len(t) > 4096:
            raise ErrorDominio('parametros_invalidos', MSG_NO_ES_URL, http=400)
        parece_url = '://' in t or t.lower().startswith(self.host_retorno) or '?' in t or '=' in t
        if not parece_url:
            if len(t) < 6 or any(ch not in _RE_CODE_SUELTO for ch in t):
                raise ErrorDominio('parametros_invalidos', MSG_NO_ES_URL, http=400)
            return t, None
        if t.lower().startswith(self.host_retorno):
            t = 'https://' + t
        try:
            u = urllib.parse.urlsplit(t)
            puerto = u.port
        except ValueError:
            raise ErrorDominio('parametros_invalidos', MSG_NO_ES_URL, http=400) from None
        if (u.scheme.lower() != self.esquema_retorno or (u.hostname or '').lower() != self.host_retorno
                or u.username or u.password or puerto not in (None, self.puerto_retorno)
                or (self.ruta_retorno is not None and u.path != self.ruta_retorno)):
            raise ErrorDominio('parametros_invalidos', MSG_NO_ES_URL, http=400)
        q = urllib.parse.parse_qs(u.query)
        if q.get('error'):
            denegada = (q.get('error') or [''])[0] == 'auth_denied'
            raise ErrorDominio('parametros_invalidos', MSG_CANCELADA if denegada else MSG_NO_ES_URL, http=400,
                               detalle={'motivo': 'autorizacion_cancelada' if denegada else 'error_de_tiktok'})
        code = (q.get('code') or [''])[0]
        if not code:
            raise ErrorDominio('parametros_invalidos', MSG_NO_ES_URL, http=400)
        state = (q.get('state') or [''])[0] or None
        return code, state

    def _canjear_en_tiktok(self, code: str, state: str) -> Json:
        f = getattr(self.cliente, 'canjear_codigo', None)
        if not callable(f):
            self._devolver_state(state)
            raise ErrorDominio('error_interno', 'No se pudo completar la conexión.', http=500)
        try:
            return f(code)
        except ErrorApi as e:
            if e.codigo in ('sin_internet', 'tiktok_no_disponible'):
                self._devolver_state(state)
                raise ErrorDominio('sin_internet' if e.codigo == 'sin_internet' else 'tiktok_no_disponible',
                                   MSG_SIN_INTERNET, http=503) from None
            if e.codigo == 'sin_respuesta':
                raise ErrorDominio('tiktok_no_disponible', MSG_SIN_RESPUESTA, http=503) from None
            if e.codigo == 'sin_credenciales':
                raise ErrorDominio('sin_credenciales', MSG_FALTA_CLAVE, http=409) from None
            raise ErrorDominio('codigo_vencido', MSG_CODIGO_VENCIDO, http=400,
                               detalle={'codigo_tiktok': e.codigo if isinstance(e.codigo, int) else None}) from None

    @staticmethod
    def _validar_tokens(datos: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """(cambios para la bóveda, permisos opcionales que faltan). Lanza no_es_creador / sin_permiso_tiktok."""
        if datos.get('user_type') != 1:
            raise ErrorDominio('no_es_creador', MSG_NO_CREADOR, http=422)
        a_exp, r_exp = datos.get('access_token_expire_in'), datos.get('refresh_token_expire_in')
        if (not isinstance(datos.get('access_token'), str) or not datos.get('access_token')
                or not isinstance(datos.get('refresh_token'), str) or not datos.get('refresh_token')
                or not isinstance(a_exp, int) or isinstance(a_exp, bool) or not isinstance(r_exp, int)
                or isinstance(r_exp, bool) or not datos.get('open_id')):
            raise ErrorDominio('tiktok_no_disponible', MSG_INCOMPLETA, http=502)
        scopes = [str(s) for s in datos.get('granted_scopes') or []]
        faltan_min = [s for s in cx.SCOPES_MINIMOS if s not in scopes]
        if faltan_min:
            raise ErrorDominio('sin_permiso_tiktok',
                               f'Faltan permisos indispensables: {_faltan_permisos(faltan_min)}. Vuelve a autorizar y '
                               'deja activados todos los permisos.', http=422,
                               detalle={'faltan': _faltan_permisos(faltan_min)})
        faltan = [s for s in cx.SCOPES_USADOS if s not in scopes]
        cambios = {'access_token': datos['access_token'], 'refresh_token': datos['refresh_token'],
                   'access_expira_at': a_exp, 'refresh_expira_at': r_exp, 'open_id': str(datos['open_id']),
                   'user_type': 1, 'granted_scopes': scopes, 'seller_name': str(datos.get('seller_name') or ''),
                   'origen': 'oauth'}
        return cambios, faltan

    def canjear(self, req: Json) -> Json:
        self._exigir_real()
        if not isinstance(req, Mapping):
            raise ErrorDominio('parametros_invalidos', MSG_NO_ES_URL, http=400)
        texto = req.get('url_o_codigo')
        desde_pp = req.get('desde_portapapeles') is True
        confirmar = req.get('confirmar_cambio_cuenta') is True
        if texto is not None and not isinstance(texto, str):
            raise ErrorDominio('parametros_invalidos', MSG_NO_ES_URL, http=400)
        if not self.boveda.tiene_app_secret():
            raise ErrorDominio('sin_credenciales', MSG_FALTA_CLAVE, http=409)
        solo_pp = desde_pp and not texto
        ahora = self.reloj.ahora()
        with self._candado:
            pendiente = self._cambio_pendiente
            if pendiente is not None and pendiente['expira'] <= ahora:
                pendiente = self._cambio_pendiente = None
        seq_url: int | None = None
        if confirmar and solo_pp and pendiente is not None and pendiente.get('desde_pp'):
            # Confirmación del 409 de un canje «desde el portapapeles»: el state ya se consumió (el portapapeles NO se
            # vuelve a leer sin state vivo) y TikTok ya canjeó el code: se usan los tokens guardados en memoria.
            huella, datos, seq_url = pendiente['huella'], pendiente['datos'], pendiente.get('seq')
        else:
            if solo_pp:
                code, state_url, seq_url = self._del_portapapeles()
            else:
                code, state_url = self._analizar_entrada(texto or '')
            huella = hashlib.sha256(code.encode('utf-8')).hexdigest()
            if confirmar and pendiente is not None and hmac.compare_digest(pendiente['huella'], huella):
                datos = pendiente['datos']                     # el code ya se canjeó al responder el 409
                if seq_url is None:
                    seq_url = pendiente.get('seq')             # para vaciar el portapapeles si sigue la misma URL
            else:
                if seq_url is None:
                    seq_url = self._seq_con_url(code)
                if state_url is not None:
                    r = self._consumir_state(state_url)
                    if r == 'desconocido':
                        raise ErrorDominio('state_invalido', MSG_STATE_AJENO, http=400)
                    if r in ('usado', 'vencido'):
                        raise ErrorDominio('state_invalido', MSG_STATE_VENCIDO, http=400)
                    state = state_url
                else:
                    state = self._consumir_unico()
                datos = self._canjear_en_tiktok(code, state)
        try:
            cambios, faltan = self._validar_tokens(datos)
        finally:
            with self._candado:
                self._pp_pendiente = None
                self._pp_cache = None
        actual = self.boveda.leer()
        guardado = actual.get('open_id') or (self._leer_fila() or {}).get('open_id')
        distinta = bool(guardado) and cambios['open_id'] != guardado
        if distinta and not confirmar:
            with self._candado:
                self._cambio_pendiente = {'huella': huella, 'datos': dict(datos), 'expira': ahora + VIGENCIA_STATE_S,
                                          'seq': seq_url, 'desde_pp': solo_pp}
            raise ErrorDominio('cuenta_distinta', MSG_CUENTA_DISTINTA, http=409)
        primera = not guardado
        self.coordinador.mutacion_segura(
            lambda: self.boveda.mutar(lambda d: d.update(cambios), cambia_credenciales=True),
            'tiktok' if distinta else 'nada')
        with self._candado:
            self._cambio_pendiente = None
        self._espejar(estado='conectada', ultimo_refresh_at=None, refresh_rechazos_seguidos=0, refresh_aviso=None,
                      ultimo_error_codigo=None, ultimo_error_mensaje=None)
        perfil = self._traer_perfil()
        if perfil:
            self._guardar_perfil(perfil)
        self._vaciar_si_sigue(seq_url)
        self._publicar()
        avisos = []
        if faltan:
            avisos.append(f'Conectado, pero faltan permisos: {_faltan_permisos(faltan)}. Algunas secciones no se '
                          'actualizarán.')
        cuenta = self.cuenta() or (cx.cuenta_de_perfil(perfil) if perfil else None)
        _log.info('Cuenta de TikTok conectada%s', ' (cambio de cuenta)' if distinta else '')
        return {'ok': True, 'conexion': self.conexion(), 'cuenta': cuenta, 'cuenta_cambio': distinta,
                'confirmar_cuenta': primera, 'avisos': avisos}

    # ================================================================ refrescar / desconectar
    def refrescar(self) -> Json:
        if not self.boveda.tiene_tokens():
            raise ErrorDominio('sin_credenciales', MSG_SIN_CONEXION, http=409)
        try:
            self.cliente.refrescar()
        except ErrorAuthTransitorio:
            pass                       # el cliente dejó el aviso 'renovacion_pendiente'
        except ErrorApi as e:
            # reautorizar ya quedó en auth_estado; token_rechazado aquí = disyuntor (renovada hace < 10 min).
            _log.info('Renovación manual sin efecto (%s)', e.codigo)
        return {'conexion': self.conexion()}

    def desconectar(self, borrar_datos: bool) -> Json:
        self._exigir_real()
        borrar = bool(borrar_datos)

        def quitar(d: dict[str, Any]) -> None:
            for k in ('access_token', 'refresh_token', 'access_expira_at', 'refresh_expira_at', 'granted_scopes'):
                d.pop(k, None)
            if borrar:
                for k in ('open_id', 'seller_name', 'user_type'):
                    d.pop(k, None)
        self.coordinador.mutacion_segura(lambda: self.boveda.mutar(quitar, cambia_credenciales=True),
                                         'tiktok' if borrar else 'nada')
        with self._candado:
            self._cambio_pendiente = None
            self._pp_pendiente = None
            self._pp_cache = None
        self._espejar(estado=cx.estado_base(self.boveda.leer()), ultimo_refresh_at=None, refresh_rechazos_seguidos=0,
                      refresh_aviso=None, ultimo_error_codigo=None, ultimo_error_mensaje=None)
        self._publicar()
        _log.info('Cuenta de TikTok desconectada%s', ' y datos descargados borrados' if borrar else '')
        return {'conexion': self.conexion()}

    # ================================================================ credenciales
    def importar(self, req: Json) -> Json:
        self._exigir_real()
        if not isinstance(req, Mapping):
            raise ErrorDominio('parametros_invalidos', 'Petición inválida.', http=400)
        ruta = req.get('ruta')
        verificar = req.get('verificar', True)
        if ruta is not None and not isinstance(ruta, str):
            raise ErrorDominio('archivo_invalido', importador_legado.MSG_RUTA_INVALIDA, http=400)
        if not isinstance(verificar, bool):
            raise ErrorDominio('parametros_invalidos', 'Petición inválida.', http=400)
        r = importador_legado.importar(ruta or None, self._candidatos(), self.boveda, self.almacen, self.coordinador,
                                       self.reloj.ahora(), self.tipo_unidad)
        verificacion = 'omitida'
        if verificar and r.tokens_en_boveda:
            perfil = self._traer_perfil()
            if perfil is not None:
                self._guardar_perfil(perfil)
                verificacion = 'ok'
            else:
                verificacion = 'fallo'
        if r.cambio:
            self._publicar()
        return {'importado': dict(r.importado), 'conexion': self.conexion(), 'verificacion': verificacion,
                'aviso_archivo_original': r.aviso_archivo_original}

    def guardar_app_secret(self, app_secret: str) -> Json:
        self._exigir_real()
        if not isinstance(app_secret, str) or not _RE_SECRETO.match(app_secret):
            raise ErrorDominio('app_secret_invalido', MSG_CLAVE_FORMATO, http=422)
        if self.boveda.tiene_tokens():
            verificar = getattr(self.cliente, 'verificar_app_secret', None)
            if callable(verificar):
                try:
                    resultado = verificar(app_secret)
                except ErrorApi:
                    raise ErrorDominio('sin_internet', 'No pudimos hablar con TikTok para revisar la clave. Revisa tu '
                                       'internet e inténtalo de nuevo.', http=503) from None
                if resultado == 'rechazada':
                    raise ErrorDominio('app_secret_invalido', MSG_CLAVE_RECHAZADA, http=422)

        def poner(d: dict[str, Any]) -> None:
            d['app_secret'] = app_secret
            d.setdefault('app_key', APP_KEY_PUBLICA)
            if not (d.get('access_token') and d.get('refresh_token')):
                d['origen'] = 'manual'
        self.coordinador.mutacion_segura(lambda: self.boveda.mutar(poner, cambia_credenciales=True), 'nada')
        self._espejar()
        self._publicar()
        _log.info('Clave de la app guardada (cifrada con DPAPI)')
        return self.credenciales_estado()

    def borrar_legado(self) -> Json:
        self._exigir_real()
        ruta = importador_legado.ruta_por_omision(self._candidatos())
        try:
            st = os.lstat(ruta)
        except FileNotFoundError:
            return {'resultado': 'no_existe'}
        except OSError:
            raise ErrorDominio('error_interno', MSG_PAPELERA, http=500) from None
        import stat as _stat
        if not _stat.S_ISREG(st.st_mode):
            return {'resultado': 'no_existe'}
        try:
            self.papelera(ruta)
        except OSError as e:
            _log.warning('No se pudo mover el archivo anterior a la Papelera (%s)', type(e).__name__)
            raise ErrorDominio('error_interno', MSG_PAPELERA, http=500) from None
        if os.path.lexists(ruta):
            raise ErrorDominio('error_interno', MSG_PAPELERA, http=500)
        _log.info('Archivo del panel anterior enviado a la Papelera')
        return {'resultado': 'papelera'}


def crear_auth(boveda: Boveda, cliente: ClienteTikTok, almacen: Almacen, bus: Bus, reloj: Reloj,
               coordinador: Coordinador, modo: ModoHub) -> ServicioAuth:
    """ServicioAuth (BUILD §6.3.1 paso 8). Reconcilia auth_estado con la bóveda al crearse (base recreada, bóveda
    ilegible, modo demo); si la base es de solo lectura, sigue sin escribir."""
    servicio = ServicioAuthReal(boveda, cliente, almacen, bus, reloj, coordinador, modo)
    try:
        datos = boveda.leer()
        with almacen.escritor() as c:
            previo = cx.leer_fila(c)
            campos = cx.espejo(datos)
            estado = cx.estado_base(datos)
            if estado == 'conectada' and (previo or {}).get('estado') in ('reautorizar', 'cuenta_sin_region'):
                estado = previo['estado']
            campos['estado'] = estado
            if previo is None or any(previo.get(k) != v for k, v in campos.items()):
                cx.actualizar_fila(c, reloj.ahora(), datos.get('app_key'), **campos)
    except Exception as e:  # noqa: BLE001
        _log.warning('No se pudo reconciliar el estado de la conexión (%s)', type(e).__name__)
    if getattr(boveda, 'ilegible_at', None):
        _log.warning('La conexión quedó sin credenciales: el archivo cifrado anterior no se pudo leer')
    return servicio
