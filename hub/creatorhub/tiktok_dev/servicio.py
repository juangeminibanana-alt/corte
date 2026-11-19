"""Servicio de la Display API (rev. 5): lo que usan las rutas locales, el callback /oauth/tiktok y la sincronización.

`crear_servicio_display(boveda, transporte, almacen, bus, reloj, coordinador, modo)` → `ServicioDisplay`:

- `estado()` → EstadoDisplay (contrato rev. 5): configurada / conectada / estado / usuario / scopes / última sync /
  último error / conexión pendiente. Nunca trae el client_key, el client_secret ni un token.
- `guardar_credenciales(client_key, client_secret)`: escritura local (formato validado), cifrada con DPAPI. Si cambia
  el client_key, los tokens de la app anterior se borran (pertenecen a esa app).
- `iniciar_conexion(abrir_navegador)`: verifier y state NUEVOS (en memoria, 10 min, un solo uso; máx. 5 intentos
  vivos) y la URL de autorización con redirect_uri = http://127.0.0.1:<puerto real del hub>/oauth/tiktok. La interfaz la
  abre con el navegador del sistema (POST /api/sistema/abrir) o pide `abrir_navegador`.
- `callback(consulta)` → (status, página HTML mínima en español): valida el state (comparación en tiempo constante),
  canjea el code con el verifier de ESE intento, guarda los tokens, lee el perfil y pide una sincronización. Recargar
  la página de un intento que ya terminó repite el mismo resultado sin volver a canjear. La página nunca lleva el code,
  el state ni un token, y nada de eso se registra.
- Rev. 6 (18/11/2026), `cuenta_de_lo_guardado`: antes de guardar nada de una cuenta, decide de quién es lo ya
  guardado (perfiles y, si no bastan, video/query). Se borra solo si se comprueba que es de otra cuenta y la cuenta
  autorizada es la de la tienda; si lo guardado es del creador, o la autorizada tampoco es la de la tienda, esa
  autorización se rechaza (409) y no se toca nada; sin pruebas no se decide nada. Lo usan también el paso de la sync y
  la importación de la nube.
- `desconectar(borrar_datos, olvidar_app)`: revoca en TikTok (si se puede) y borra los tokens; con `borrar_datos`
  también lo descargado de la Display API (cancela antes la sync en curso); con `olvidar_app`, el client_key/secret.
- `listo()`: hay credenciales y conexión sin marca de reautorizar (si no, el paso «videos_tiktok» se salta en silencio).
- Cambios → `bus.publicar({'tipo': 'display.cambio', 'display': EstadoDisplay})` (SSE de la ventana local).

En demo y autoprueba lo que cambia la conexión responde 403 `prohibido` (la demo nunca toca credenciales reales).
"""
from __future__ import annotations

import hmac
import html
import json
import logging
import os
import re
import threading
import urllib.parse
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .. import config
from ..errores import ErrorApi, ErrorDominio
from ..interfaces import Almacen, Bus, Coordinador, Json, ModoHub, Reloj, Transporte
from . import datos as D
from . import pkce
from .boveda import CAMPOS_TOKENS, BovedaDisplay
from .cliente import SCOPES, ClienteDisplay, validar_ids_video
from .errores import ErrorDisplay

_log = logging.getLogger('creatorhub.tiktok_dev')

VIGENCIA_INTENTO_S = 600                # 10 min, un solo uso (como los states de TikTok Shop, C37)
MAX_INTENTOS_VIVOS = 5
RUTA_CALLBACK = '/oauth/tiktok'
_RE_CLIENT_KEY = re.compile(r'[A-Za-z0-9]{8,64}')
_RE_CLIENT_SECRET = re.compile(r'[A-Za-z0-9_\-]{16,128}')
MAX_CAMPOS_CALLBACK = 16
MAX_CODE = 2048

NOMBRE_SCOPE: dict[str, str] = {'user.info.basic': 'tu nombre y foto', 'user.info.profile': 'los datos de tu perfil',
                                'user.info.stats': 'tus seguidores y likes', 'video.list': 'la lista de tus videos'}

# Textos visibles (español de México, sin «token» ni «scope»).
MSG_DEMO = 'En el modo de demostración no puedes cambiar la conexión para ver las vistas de tus videos.'
MSG_CLAVE_FORMATO = 'El Client key debe tener de 8 a 64 letras y números, sin espacios.'
MSG_SECRETO_FORMATO = 'El Client secret debe tener de 16 a 128 letras, números, guiones o guiones bajos, sin espacios.'
MSG_FALTAN_CREDENCIALES = 'Primero escribe el Client key y el Client secret de tu app de TikTok for Developers.'
MSG_NAVEGADOR = 'No pudimos abrir tu navegador. Copia el enlace y ábrelo tú.'
PAG_LISTO = 'Listo, ya puedes volver a Corte.'
PAG_LISTO_FALTAN = 'Listo, ya puedes volver a Corte. Faltó un permiso: {faltan}. Algunas cifras no se van a actualizar.'
PAG_NO_CORRESPONDE = ('Este enlace no corresponde a un intento de conexión de Corte, o ya caducó. Vuelve a Corte e '
                      'inténtalo de nuevo.')
PAG_CANCELADA = 'Cancelaste la autorización en TikTok. Puedes volver a Corte e intentarlo cuando quieras.'
PAG_ERROR_TIKTOK = 'TikTok no completó la autorización. Vuelve a Corte e inténtalo de nuevo.'
PAG_INVALIDA = 'Este enlace no es válido. Vuelve a Corte e inténtalo de nuevo.'


def pagina_html(mensaje: str, ok: bool) -> bytes:
    """Página mínima (sin scripts ni recursos externos; la CSP del servidor solo permite estilos en línea)."""
    color = '#1f7a4d' if ok else '#9b2c2c'
    return ('<!doctype html><html lang="es-MX"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1"><title>Corte</title>'
            '<style>body{font-family:Segoe UI,system-ui,sans-serif;margin:0;display:flex;min-height:100vh;'
            'align-items:center;justify-content:center;background:#f6f6f4;color:#1c1c1a}'
            'main{max-width:28rem;padding:2rem;text-align:center}h1{font-size:1.4rem;margin:0 0 .75rem}'
            f'p{{font-size:1.05rem;line-height:1.5;margin:0;color:{color}}}</style></head>'
            f'<body><main><h1>Corte</h1><p>{html.escape(mensaje)}</p></main></body></html>').encode('utf-8')


def _abrir_url_sistema(url: str) -> None:
    os.startfile(url)          # type: ignore[attr-defined]   (solo Windows; el hub es solo Windows)


@dataclass
class _Intento:
    verifier: str
    redirect_uri: str
    expira: int


class ServicioDisplay:
    """Los colaboradores del sistema (navegador, puerto, sincronizar) son atributos sustituibles en pruebas."""

    def __init__(self, boveda: BovedaDisplay, cliente: ClienteDisplay, almacen: Almacen, bus: Bus, reloj: Reloj,
                 coordinador: Coordinador | None, modo: ModoHub) -> None:
        if modo not in ('real', 'demo', 'autoprueba'):
            raise ValueError(f'modo desconocido: {modo!r}')
        self.boveda, self.cliente, self.almacen, self.bus, self.reloj = boveda, cliente, almacen, bus, reloj
        self.coordinador, self.modo = coordinador, modo
        self.puerto: Callable[[], int] = lambda: config.PUERTO_UI        # hub.py: el puerto REAL de la interfaz
        self.redirect_uri: str | None = None
        self.abrir_url: Callable[[str], None] = _abrir_url_sistema
        self.al_conectar: Callable[[], None] | None = None              # hub.py: sincronizar_ahora
        self._candado = threading.Lock()
        self._intentos: dict[str, _Intento] = {}
        self._terminados: dict[str, tuple[int, int, bytes]] = {}       # state -> (expira, status, página)
        cliente.al_cambiar = self.publicar

    # ================================================================ lectura
    def secretos_vivos(self) -> tuple[str, ...]:
        return self.boveda.secretos_vivos()

    def listo(self) -> bool:
        d = self.boveda.leer()
        return bool(d.get('client_key') and d.get('client_secret') and d.get('access_token') and d.get('refresh_token')
                    and not d.get('reautorizar'))

    def _estado_conexion(self, d: Mapping[str, Any]) -> str:
        if not (d.get('client_key') and d.get('client_secret')):
            return 'sin_credenciales'
        if not (d.get('access_token') and d.get('refresh_token')):
            return 'sin_conectar'
        rexp = d.get('refresh_expira_at')
        if d.get('reautorizar') or (isinstance(rexp, int) and rexp <= self.reloj.ahora()):
            return 'reautorizar'
        return 'conectada'

    def _leer_bd(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        try:
            with self.almacen.lector() as c:
                perfil = D.leer_perfil(c)
                r = c.execute('SELECT valor FROM sync_cursores WHERE clave = ?', (D.CLAVE_ULTIMA_SYNC,)).fetchone()
        except Exception as e:  # noqa: BLE001 - base sin la migración o cerrada: el estado sale sin esos datos
            _log.debug('No se pudo leer el perfil de la Display API (%s)', type(e).__name__)
            return None, None
        ultima = None
        if r is not None:
            try:
                ultima = json.loads(r[0])
            except ValueError:
                ultima = None
        return perfil, ultima if isinstance(ultima, dict) else None

    def estado(self) -> Json:
        d = self.boveda.leer()
        estado = self._estado_conexion(d)
        conectada = estado in ('conectada', 'reautorizar')
        scopes = [str(s) for s in (d.get('scopes') or [])] if conectada else []
        perfil, ultima = self._leer_bd()
        usuario = None
        if conectada and perfil is not None:
            usuario = {k: perfil[k] for k in ('username', 'nombre', 'verificada', 'enlace_perfil', 'seguidores',
                                              'siguiendo', 'likes_total', 'videos_total')}
            usuario['actualizado_at'] = perfil['actualizado_at']
        ahora = self.reloj.ahora()
        with self._candado:
            vivos = [i.expira for i in self._intentos.values() if i.expira > ahora]
        error = d.get('ultimo_error')
        return {
            'configurada': estado != 'sin_credenciales', 'conectada': conectada, 'estado': estado,
            'usuario': usuario, 'scopes': scopes,
            'scopes_faltantes': [s for s in SCOPES if s not in scopes] if conectada else [],
            'access_expira_at': d.get('access_expira_at') if conectada else None,
            'refresh_expira_at': d.get('refresh_expira_at') if conectada else None,
            'conectada_at': d.get('conectada_at') if conectada else None,
            'ultima_sync': _ultima_sync(ultima),
            'ultimo_error': ({'codigo': str(error.get('codigo')), 'mensaje': str(error.get('mensaje') or ''),
                              'at': int(error.get('at') or 0)} if isinstance(error, Mapping) else None),
            'conexion_pendiente': {'expira_at': max(vivos)} if vivos else None,
        }

    def publicar(self) -> None:
        try:
            self.bus.publicar({'tipo': 'display.cambio', 'display': self.estado()})
        except Exception as e:  # noqa: BLE001
            _log.warning('No se pudo publicar display.cambio (%s)', type(e).__name__)

    @staticmethod
    def _cuenta_video_verificada(conexion: Mapping[str, Any], perfil: Mapping[str, Any] | None,
                                  usuario_shop: str) -> bool:
        usuario = D.usuario_normalizado(usuario_shop)
        return bool(usuario and perfil and conexion.get('open_id')
                    and perfil.get('open_id') == conexion['open_id']
                    and D.usuario_normalizado(perfil.get('username')) == usuario)

    def puede_actualizar_video(self, usuario_shop: str) -> bool:
        conexion = self.boveda.leer()
        if self._estado_conexion(conexion) != 'conectada' or 'video.list' not in (conexion.get('scopes') or ()):
            return False
        perfil, _ = self._leer_bd()
        return self._cuenta_video_verificada(conexion, perfil, usuario_shop)

    def actualizar_video(self, content_id: str, candado: AbstractContextManager[Any],
                         identidad_shop: Callable[[], tuple[tuple[Any, ...], str]]) -> Json:
        """Consulta un video propio fuera de los candados y aplica sus métricas solo si todo sigue vigente."""
        try:
            validar_ids_video([content_id])
        except ValueError:
            raise ErrorDominio('parametros_invalidos', 'El identificador del video no es válido.', http=422) from None

        no_disponible = 'TikTok no devolvió métricas para este video de la cuenta conectada.'
        cambio = 'La cuenta o las métricas cambiaron durante la consulta. Abre de nuevo la ficha del video.'
        with candado, self.boveda.candado:
            shop = identidad_shop()
            conexion = self.boveda.leer()
            if self._estado_conexion(conexion) != 'conectada':
                raise ErrorDominio('display_no_conectada', 'Conecta TikTok en Ajustes para actualizar tus videos.', http=409)
            if 'video.list' not in (conexion.get('scopes') or ()):
                raise ErrorDominio('permiso_faltante', 'La cuenta de TikTok no autorizó la lectura de tus videos.', http=403)
            epoca = self.almacen.epoca()
            with self.almacen.lector() as db:
                if not self._cuenta_video_verificada(conexion, D.leer_perfil(db), shop[1]):
                    raise ErrorDominio('cuenta_distinta', 'Verifica la conexión de TikTok en Ajustes antes de actualizar.', http=409)
                previo = D.leer_metricas_video(db, content_id)
                if previo is None:
                    raise ErrorDominio('video_no_disponible', no_disponible, http=404)

        try:
            videos = self.cliente.consultar_videos([content_id])
        except ErrorDisplay as exc:
            http = {
                'permiso_faltante': 403, 'limite': 429, 'sin_conexion': 409, 'sin_credenciales': 409,
                'reautorizar': 409, 'credenciales_rechazadas': 409, 'token_invalido': 409,
            }.get(exc.codigo, 503 if exc.transitorio else 502)
            raise ErrorDominio(exc.codigo, exc.mensaje, http=http) from None
        video = D.normalizar_video(videos[0]) if videos else None
        if video is None or video['video_id'] != content_id:
            raise ErrorDominio('video_no_disponible', no_disponible, http=404)
        if not D.tiene_metricas_video(video):
            raise ErrorDominio('respuesta_invalida', 'TikTok no devolvió cifras válidas para este video.', http=502)

        with candado, self.boveda.candado:
            actual = self.boveda.leer()
            revision = ('client_key', 'open_id', 'epoca_credenciales')
            if (identidad_shop() != shop or any(actual.get(k) != conexion.get(k) for k in revision)
                    or self._estado_conexion(actual) != 'conectada' or 'video.list' not in (actual.get('scopes') or ())):
                raise ErrorDominio('credenciales_cambiaron', cambio, http=409)
            try:
                with self.almacen.escritor(epoca) as db:
                    if (not self._cuenta_video_verificada(actual, D.leer_perfil(db), shop[1])
                            or D.leer_metricas_video(db, content_id) != previo):
                        raise ErrorDominio('credenciales_cambiaron', cambio, http=409)
                    D.actualizar_metricas_video(db, video, previo, int(self.reloj.ahora()))
                    self.almacen.marcar_data_version(db)
            except ErrorApi as exc:
                if exc.codigo != 'credenciales_cambiaron':
                    raise
                raise ErrorDominio('credenciales_cambiaron', cambio, http=409) from None
            self.almacen.confirmar_data_version()
            try:
                self.bus.notificar_cambio(self.almacen.versiones(), ['videos'])
            except Exception:  # noqa: BLE001 - los clientes también consultan la versión de la base
                _log.warning('No se pudo publicar la actualización de métricas de video')
        return {'actualizado': True}

    # ================================================================ errores de la sync
    def anotar_resultado(self, error: ErrorDisplay | None, revision: tuple[Any, Any] | None = None) -> None:
        """La sync terminó su paso: guarda (o limpia) el último error. Solo escribe si cambia algo y, con `revision`
        ((client_key, epoca_credenciales) de la conexión del paso), solo si la conexión sigue siendo esa."""
        ahora = self.reloj.ahora()
        try:
            with self.boveda.candado:
                actual = self.boveda.leer()
                if revision is not None and (actual.get('client_key'), actual.get('epoca_credenciales', 0)) != revision:
                    return                               # el error era de una conexión anterior
                previo = actual.get('ultimo_error')
                if error is None and previo is None:
                    return
                self.boveda.mutar(lambda d: d.update(ultimo_error=None if error is None else error.como_dict(ahora)))
        except OSError as e:
            _log.warning('No se pudo guardar el resultado de la Display API (%s)', type(e).__name__)

    # ================================================================ escritura (solo la ventana local)
    def _exigir_real(self) -> None:
        if self.modo != 'real':
            raise ErrorDominio('prohibido', MSG_DEMO, http=403)

    def guardar_credenciales(self, client_key: Any, client_secret: Any) -> Json:
        self._exigir_real()
        if not isinstance(client_key, str) or not _RE_CLIENT_KEY.fullmatch(client_key):
            raise ErrorDominio('parametros_invalidos', MSG_CLAVE_FORMATO, http=422, detalle={'campo': 'client_key'})
        if not isinstance(client_secret, str) or not _RE_CLIENT_SECRET.fullmatch(client_secret):
            raise ErrorDominio('parametros_invalidos', MSG_SECRETO_FORMATO, http=422, detalle={'campo': 'client_secret'})

        def poner(d: dict[str, Any]) -> None:
            if d.get('client_key') and d.get('client_key') != client_key:
                for k in CAMPOS_TOKENS:                          # los tokens eran de la app anterior
                    d.pop(k, None)
            d['client_key'], d['client_secret'] = client_key, client_secret
            d['ultimo_error'] = None
        self.boveda.mutar(poner, cambia_credenciales=True)
        with self._candado:
            self._intentos.clear()
        _log.info('Credenciales de la Display API guardadas (cifradas con DPAPI)')
        self.publicar()
        return self.estado()

    def purgar(self) -> None:
        """Tic del planificador: intentos y páginas vencidas fuera; reintento del `.nuevo` pendiente de la bóveda."""
        ahora = self.reloj.ahora()
        with self._candado:
            for s in [s for s, i in self._intentos.items() if i.expira <= ahora]:
                del self._intentos[s]
            for s in [s for s, t in self._terminados.items() if t[0] <= ahora]:
                del self._terminados[s]
        try:
            self.boveda.reintentar_pendiente()
        except Exception:  # noqa: BLE001
            pass

    def iniciar_conexion(self, abrir_navegador: bool = False) -> Json:
        if self.redirect_uri is not None:
            abrir_navegador = False
        self._exigir_real()
        d = self.boveda.leer()
        if not (d.get('client_key') and d.get('client_secret')):
            raise ErrorDominio('sin_credenciales', MSG_FALTAN_CREDENCIALES, http=409)
        verifier, state = pkce.nuevo_verifier(), pkce.nuevo_state()
        redirect_uri = self.redirect_uri or f'http://{config.HOST_UI}:{int(self.puerto())}{RUTA_CALLBACK}'
        ahora = self.reloj.ahora()
        expira = ahora + VIGENCIA_INTENTO_S
        with self._candado:
            for s in [s for s, i in self._intentos.items() if i.expira <= ahora]:
                del self._intentos[s]
            while len(self._intentos) >= MAX_INTENTOS_VIVOS:     # el más viejo deja de servir
                del self._intentos[min(self._intentos, key=lambda s: self._intentos[s].expira)]
            self._intentos[state] = _Intento(verifier, redirect_uri, expira)
        url = self.cliente.url_autorizacion(str(d['client_key']), redirect_uri, state, pkce.challenge_hex(verifier))
        abierto = False
        if abrir_navegador:
            try:
                self.abrir_url(url)
                abierto = True
            except OSError as e:
                _log.warning('No se pudo abrir el navegador (%s)', type(e).__name__)
        _log.info('Enlace de autorización de la Display API creado (vigente 10 min)')
        self.publicar()
        return {'url': url, 'expira_at': expira, 'abierto': abierto}

    # ================================================================ callback GET /oauth/tiktok
    def _tomar_intento(self, state: str) -> tuple[_Intento | None, tuple[int, bytes] | None]:
        """(intento vivo consumido, None) · (None, resultado ya terminado) · (None, None) si no corresponde."""
        ahora = self.reloj.ahora()
        s = state.encode('utf-8')
        with self._candado:
            for k, t in list(self._terminados.items()):
                if hmac.compare_digest(k.encode('utf-8'), s):
                    return (None, (t[1], t[2])) if t[0] > ahora else (None, None)
            for k in list(self._intentos):
                if hmac.compare_digest(k.encode('utf-8'), s):
                    intento = self._intentos.pop(k)
                    return (intento, None) if intento.expira > ahora else (None, None)
        return None, None

    def _recordar(self, state: str, status: int, pagina: bytes) -> tuple[int, bytes]:
        with self._candado:
            self._terminados[state] = (self.reloj.ahora() + VIGENCIA_INTENTO_S, status, pagina)
        return status, pagina

    def _anotar_error(self, e: ErrorDisplay) -> None:
        try:
            self.boveda.mutar(lambda d: d.update(ultimo_error=e.como_dict(self.reloj.ahora())))
        except OSError:
            pass

    def callback(self, consulta: str) -> tuple[int, bytes]:
        try:
            q = urllib.parse.parse_qs(consulta or '', keep_blank_values=True, strict_parsing=False, errors='strict',
                                      max_num_fields=MAX_CAMPOS_CALLBACK)
        except (ValueError, UnicodeDecodeError):
            return 400, pagina_html(PAG_INVALIDA, False)
        uno = lambda k: (q.get(k) or [''])[0]  # noqa: E731
        state = uno('state')
        if not state or len(state) > 256:
            return 400, pagina_html(PAG_NO_CORRESPONDE, False)
        intento, previo = self._tomar_intento(state)
        if previo is not None:
            return previo                                        # recarga de la página de un intento ya terminado
        if intento is None:
            _log.info('Regreso de autorización de la Display API con un state desconocido, usado o vencido')
            return 400, pagina_html(PAG_NO_CORRESPONDE, False)
        if uno('error'):
            cancelada = uno('error') in ('access_denied', 'user_denied', 'cancel')
            _log.info('La autorización de la Display API no se completó (%s)', 'cancelada' if cancelada else 'error')
            self._anotar_error(ErrorDisplay('solicitud_rechazada', PAG_CANCELADA if cancelada else PAG_ERROR_TIKTOK))
            self.publicar()
            return self._recordar(state, 400, pagina_html(PAG_CANCELADA if cancelada else PAG_ERROR_TIKTOK, False))
        code = uno('code')
        if not code or len(code) > MAX_CODE:
            return self._recordar(state, 400, pagina_html(PAG_INVALIDA, False))
        initial = self.boveda.leer()
        revision = (initial.get('client_key'), initial.get('epoca_credenciales', 0))
        try:
            tokens = self.cliente.canjear(code, intento.verifier, intento.redirect_uri)
        except ErrorDisplay as e:
            with self.boveda.candado:
                current = self.boveda.leer()
                if (current.get('client_key'), current.get('epoca_credenciales', 0)) != revision:
                    return self._recordar(state, 409, pagina_html('La conexión cambió. Vuelve a Corte para revisar su estado.', False))
                self._anotar_error(e)
            self.publicar()
            return self._recordar(state, 502 if e.transitorio else 400, pagina_html(e.mensaje, False))
        try:
            return self._recordar(state, 200, self._conectar(tokens, revision))
        except ErrorDominio as e:
            return self._recordar(state, e.http, pagina_html(e.mensaje, False))

    def _conectar(self, tokens: Mapping[str, Any], revision: tuple[Any, Any]) -> bytes:
        ahora = self.reloj.ahora()
        cambio = 'La conexión cambió. Vuelve a Corte para revisar su estado.'
        actual = self.boveda.leer()
        if (actual.get('client_key'), actual.get('epoca_credenciales', 0)) != revision:
            raise ErrorDominio('credenciales_cambiaron', cambio, http=409)
        # Antes de guardar nada: con un cliente aparte (bóveda en memoria) se lee la cuenta autorizada y se decide de
        # quién es lo ya guardado. Así una sincronización en curso nunca usa una autorización que luego se rechaza.
        provisional = BovedaDisplay(None, datos={**actual, **dict(tokens)})
        cliente = ClienteDisplay(provisional, self.cliente.transporte, self.reloj)
        perfil: dict[str, Any] | None = None
        try:
            perfil = D.normalizar_usuario(cliente.usuario())
            perfil['open_id'] = perfil.get('open_id') or tokens.get('open_id')     # el canje siempre lo trae
        except ErrorDisplay as e:
            _log.info('Autorizada, pero no se pudo leer el perfil de la Display API (%s)', e.codigo)
        except Exception as e:  # noqa: BLE001 - el perfil llega en la siguiente sync
            _log.warning('No se pudo leer el perfil de la Display API (%s)', type(e).__name__)
        identidad = perfil or {'open_id': tokens.get('open_id')}
        decision: str | None = None
        try:
            decision = self.cuenta_de_lo_guardado(identidad, actual.get('open_id'), cliente=cliente)
        except ErrorDisplay as e:                    # sin pruebas, sin permiso de videos o TikTok no respondió
            _log.info('Autorizada, sin poder comprobar de quién son los datos guardados (%s)', e.codigo)
        except Exception as e:  # noqa: BLE001 - sin decidir no se borra ni se guarda nada
            _log.warning('No se pudo comprobar de quién son los datos guardados (%s)', type(e).__name__)
        if decision == 'rechazar':
            raise self._rechazar_autorizacion(cliente, revision, tokens.get('open_id'))
        if decision != 'misma' and self.coordinador is not None:
            # 'otra' o sin decidir: ninguna pasada en curso debe seguir escribiendo ni usar esta autorización.
            self.coordinador.mutacion_segura(None, 'nada')
        vigentes = provisional.leer()                    # por si el cliente provisional tuvo que renovarlos

        def save(d: dict[str, Any]) -> None:
            if (d.get('client_key'), d.get('epoca_credenciales', 0)) != revision:
                raise ErrorDominio('credenciales_cambiaron', cambio, http=409)
            d.update({k: vigentes.get(k, v) for k, v in tokens.items()}, conectada_at=ahora, reautorizar=False,
                     ultimo_error=None, origen='oauth')
        borrado = False
        with self.boveda.candado:                        # el borrado y la autorización nueva se guardan juntos o nada
            if decision == 'otra':
                with self.almacen.escritor() as db:      # si la autorización ya no es vigente (409), se deshace el borrado
                    # Lo guardado pudo cambiar mientras se le preguntaba a TikTok: se vuelve a mirar, sin red.
                    if not D.hay_datos(db) or self._decision_local(db, identidad, actual.get('open_id')) == 'misma':
                        decision = 'misma'
                    elif D.datos_del_creador(db):
                        decision = 'rechazar'
                    else:
                        D.borrar_todo(db)
                        self.almacen.marcar_data_version(db)
                        self.almacen.subir_img_rev(db)
                        borrado = True
                    if decision != 'rechazar':
                        self.boveda.mutar(save, cambia_credenciales=True)
            else:
                self.boveda.mutar(save, cambia_credenciales=True)
        if decision == 'rechazar':
            raise self._rechazar_autorizacion(cliente, revision, tokens.get('open_id'))
        if borrado:
            _log.info('Los datos guardados de la Display API eran de otra cuenta: se borraron al guardar la nueva')
            self.almacen.confirmar_data_version()
            try:
                self.bus.notificar_cambio(self.almacen.versiones(), ['videos', 'cuenta'])
            except Exception:  # noqa: BLE001
                _log.warning('No se pudo publicar datos.cambiaron tras borrar la Display API')
        saved_revision = (revision[0], revision[1] + 1)
        if perfil is not None and decision is not None:      # sin decidir, guardar el perfil mezclaría cuentas
            try:
                with self.boveda.candado:
                    current = self.boveda.leer()
                    if (current.get('client_key'), current.get('epoca_credenciales', 0)) != saved_revision:
                        raise ErrorDominio('credenciales_cambiaron', 'La conexión cambió al verificar el perfil. Revisa su estado.', http=409)
                    with self.almacen.escritor() as db:
                        if D.guardar_perfil(db, perfil, ahora, conservar_identidad=decision == 'misma'):
                            self.almacen.marcar_data_version(db)
                if self.almacen.confirmar_data_version() is not None:
                    self.bus.notificar_cambio(self.almacen.versiones(), ['cuenta'])
            except ErrorDominio:
                raise
            except Exception as e:  # noqa: BLE001 - el perfil llega en la siguiente sync
                _log.warning('No se pudo guardar el perfil de la Display API (%s)', type(e).__name__)
        _log.info('Cuenta conectada a la Display API')
        self.publicar()
        if self.al_conectar is not None:
            try:
                self.al_conectar()
            except Exception:  # noqa: BLE001
                _log.warning('No se pudo pedir la sincronización tras conectar la Display API', exc_info=True)
        faltan = [s for s in SCOPES if s not in (tokens.get('scopes') or [])]
        if faltan:
            return pagina_html(PAG_LISTO_FALTAN.format(faltan=', '.join(NOMBRE_SCOPE.get(s, s) for s in faltan)), True)
        return pagina_html(PAG_LISTO, True)

    # ================================================================ de quién es lo guardado (rev. 6)
    def cuenta_de_lo_guardado(self, perfil: Mapping[str, Any], open_id_anterior: str | None = None,
                              cliente: ClienteDisplay | None = None) -> str:
        """Lo guardado de la Display API frente a la cuenta autorizada (`perfil`, con su open_id):

        - 'misma': se conserva (los perfiles lo prueban, o TikTok devuelve como suyos videos guardados);
        - 'otra': se comprobó que es de otra cuenta que no es la del creador, y la cuenta autorizada sí es la de la
          tienda: se borra antes de guardar la nueva;
        - 'rechazar': se comprobó que es de otra cuenta, pero lo guardado es del creador o la cuenta autorizada tampoco
          es la de la tienda: no se toca nada ni se guarda nada de ella.

        `open_id_anterior`: el de la conexión anterior de la MISMA app (la bóveda); si lo guardado es de ella y el open_id
        cambió, es otra cuenta sin preguntar. Si los perfiles no bastan, pregunta a TikTok con video/query (con `cliente`,
        o el del servicio) por los videos guardados; un «no son míos» solo prueba otra cuenta si alguno de ellos seguía
        público (TikTok no devuelve los privados ni a su dueño). Sin pruebas, o si la consulta falla, lanza ErrorDisplay:
        no se decide nada (ni se borra, ni se rechaza, ni se guarda el perfil)."""
        with self.almacen.lector() as c:
            if not D.hay_datos(c):
                return 'misma'
            decision = self._decision_local(c, perfil, open_id_anterior)
            if decision == 'misma':
                return 'misma'                           # el caso de cada sincronización: nada más que leer
            ids = D.videos_para_comprobar(c) if decision is None else []
            concluyente = D.alguno_publico(c, ids)
        if decision is None:
            if ids and (cliente or self.cliente).consultar_videos(ids):
                return 'misma'
            if not concluyente:                          # nada que TikTok pudiera devolver: sin pruebas
                raise ErrorDisplay('solicitud_rechazada', D.MSG_SIN_COMPROBAR)
        with self.almacen.lector() as c:                 # se lee después de preguntar a TikTok
            return self._destino_de_otra(c, perfil)

    @staticmethod
    def _decision_local(c: Any, perfil: Mapping[str, Any], open_id_anterior: str | None) -> str | None:
        """La parte sin red: 'misma' (los perfiles lo prueban), 'otra' (la misma app con otro open_id) o None."""
        nuevo = perfil.get('open_id')
        guardado = c.execute('SELECT open_id FROM perfil_tiktok WHERE id = 1').fetchone()
        if (open_id_anterior and nuevo and nuevo != open_id_anterior and guardado is not None
                and guardado[0] == open_id_anterior):
            return 'otra'
        return D.comparar_cuenta(c, perfil)

    @staticmethod
    def _destino_de_otra(c: Any, perfil: Mapping[str, Any]) -> str:
        """Comprobado que lo guardado es de otra cuenta. Solo se borra para dejar entrar al creador de la tienda: si lo
        guardado es del creador, o la cuenta autorizada tampoco es la de la tienda, borrar no protege nada y se rechaza.
        Una cuenta autorizada sin nombre no se puede comprobar: ErrorDisplay (sin decidir)."""
        if D.datos_del_creador(c):
            return 'rechazar'
        tienda, nuevo = D.usuario_de_la_tienda(c), D.usuario_normalizado(perfil.get('username'))
        if tienda and nuevo == tienda:
            return 'otra'
        if nuevo:
            return 'rechazar'
        raise ErrorDisplay('solicitud_rechazada', D.MSG_SIN_COMPROBAR)

    def _rechazar_autorizacion(self, cliente: ClienteDisplay, revision: tuple[Any, Any],
                               open_id_rechazado: str | None = None) -> ErrorDominio:
        """Callback: la cuenta recién autorizada es otra y no se puede dejar entrar. Nada de ella se guardó: se revoca
        (si se puede) y se anota el motivo. La conexión anterior sigue igual, salvo que sea una autorización anterior
        (sin decidir) de esa MISMA cuenta en la misma app: también se olvida. -> el 409 de la página del callback."""
        try:
            cliente.revocar()
        except Exception as e:  # noqa: BLE001 - sin internet o TikTok caído: igual no se guarda
            _log.info('No se pudo revocar en TikTok la autorización rechazada (%s)', type(e).__name__)
        error = ErrorDisplay('solicitud_rechazada', D.MSG_OTRA_CUENTA)
        olvidada: dict[str, Any] | None = None

        def quitar(d: dict[str, Any]) -> None:
            for k in CAMPOS_TOKENS:
                d.pop(k, None)
            d['ultimo_error'] = error.como_dict(self.reloj.ahora())
        with self.boveda.candado:
            actual = self.boveda.leer()
            if (actual.get('client_key'), actual.get('epoca_credenciales', 0)) != revision:
                return ErrorDominio('credenciales_cambiaron', 'La conexión cambió. Vuelve a Corte para revisar su estado.',
                                    http=409)
            if open_id_rechazado and actual.get('open_id') == open_id_rechazado and actual.get('access_token'):
                olvidada = dict(actual)
                self.boveda.mutar(quitar, cambia_credenciales=True)
            else:
                self.boveda.mutar(lambda d: d.update(ultimo_error=error.como_dict(self.reloj.ahora())))
        if olvidada is not None:                         # se revoca exactamente esa autorización, no otra guardada después
            try:
                ClienteDisplay(BovedaDisplay(None, datos=olvidada), self.cliente.transporte, self.reloj).revocar()
            except Exception as e:  # noqa: BLE001
                _log.info('No se pudo revocar en TikTok la autorización anterior rechazada (%s)', type(e).__name__)
        _log.info('Se autorizó otra cuenta de TikTok que no puede entrar: no se guardó nada de ella')
        self.publicar()
        return ErrorDominio('cuenta_distinta', error.mensaje, http=409)

    def olvidar_autorizacion_ajena(self, revision: tuple[Any, Any]) -> ErrorDisplay | None:
        """Paso de la sync: la conexión guardada (sin decidir al conectar) no es la de los datos guardados, que son del
        creador: se revoca (si se puede) y se olvida esa autorización sin tocar los datos. -> el error para el usuario,
        o None si la conexión ya cambió (`revision` = (client_key, epoca_credenciales) de esa autorización)."""
        error = ErrorDisplay('solicitud_rechazada', D.MSG_OTRA_CUENTA)

        def quitar(d: dict[str, Any]) -> None:
            for k in CAMPOS_TOKENS:
                d.pop(k, None)
            d['ultimo_error'] = error.como_dict(self.reloj.ahora())
        with self.boveda.candado:
            actual = self.boveda.leer()
            if (actual.get('client_key'), actual.get('epoca_credenciales', 0)) != revision:
                return None
            olvidada = dict(actual)
            self.boveda.mutar(quitar, cambia_credenciales=True)
        try:                                             # se revoca exactamente esa autorización, no una guardada después
            ClienteDisplay(BovedaDisplay(None, datos=olvidada), self.cliente.transporte, self.reloj).revocar()
        except Exception as e:  # noqa: BLE001 - sin internet o TikTok caído: ya se olvidó
            _log.info('No se pudo revocar en TikTok la autorización rechazada (%s)', type(e).__name__)
        _log.info('Se autorizó otra cuenta de TikTok y los datos guardados son del creador: no se cambió nada')
        self.publicar()
        return error

    # ================================================================ desconectar / borrar
    def _borrar_datos(self) -> None:
        if self.coordinador is not None:
            self.coordinador.mutacion_segura(None, 'nada')       # cancela la sync en curso (no reescribirá lo borrado)
        with self.almacen.escritor() as db:
            D.borrar_todo(db)
            self.almacen.marcar_data_version(db)
            self.almacen.subir_img_rev(db)
        self.almacen.confirmar_data_version()
        try:
            self.bus.notificar_cambio(self.almacen.versiones(), ['videos', 'cuenta'])
        except Exception:  # noqa: BLE001
            _log.warning('No se pudo publicar datos.cambiaron tras borrar la Display API')

    def desconectar(self, borrar_datos: bool = False, olvidar_app: bool = False) -> Json:
        self._exigir_real()
        revocado = False
        if self.boveda.leer().get('access_token'):
            try:
                revocado = self.cliente.revocar()
            except Exception as e:  # noqa: BLE001 - sin internet o TikTok caído: se borra igual
                _log.info('No se pudo revocar en TikTok (%s); se borra la conexión en esta PC', type(e).__name__)

        def quitar(d: dict[str, Any]) -> None:
            for k in (*CAMPOS_TOKENS, 'ultimo_error'):
                d.pop(k, None)
            if olvidar_app:
                d.pop('client_key', None)
                d.pop('client_secret', None)
        self.boveda.mutar(quitar, cambia_credenciales=True)
        with self._candado:
            self._intentos.clear()
            self._terminados.clear()
        if borrar_datos:
            self._borrar_datos()
        _log.info('Display API desconectada%s%s', ' (revocada en TikTok)' if revocado else '',
                  ' y datos borrados' if borrar_datos else '')
        self.publicar()
        return {'display': self.estado(), 'revocado': revocado}

    def olvidar_todo(self) -> None:
        """«Borrar todo» (alcance 'todo'): borra el archivo de la bóveda; las tablas ya las vació el almacén."""
        eliminar = getattr(self.boveda, 'eliminar', None)
        if callable(eliminar):
            eliminar()
        with self._candado:
            self._intentos.clear()
            self._terminados.clear()


def _ultima_sync(u: Mapping[str, Any] | None) -> Json | None:
    if not u:
        return None
    err = u.get('error')
    return {'at': int(u.get('at') or 0), 'estado': str(u.get('estado') or 'ok'), 'videos': int(u.get('videos') or 0),
            'nuevos': int(u.get('nuevos') or 0), 'cambiados': int(u.get('cambiados') or 0),
            'quitados': int(u.get('quitados') or 0), 'completa': bool(u.get('completa')),
            'error': ({'codigo': str(err.get('codigo')), 'mensaje': str(err.get('mensaje') or '')}
                      if isinstance(err, Mapping) else None)}


def crear_transporte_display(modo: ModoHub, reloj: Reloj) -> Transporte:
    """real → urllib solo hacia open.tiktokapis.com · demo y autoprueba → transporte falso (nunca red)."""
    if modo == 'real':
        from .cliente import crear_transporte_display_real
        return crear_transporte_display_real()
    from .demo import TransporteDisplayDemo
    return TransporteDisplayDemo(reloj)


def crear_servicio_display(boveda: BovedaDisplay, transporte: Transporte, almacen: Almacen, bus: Bus, reloj: Reloj,
                           coordinador: Coordinador | None, modo: ModoHub) -> ServicioDisplay:
    boveda.anclar_demo(reloj.ahora())
    return ServicioDisplay(boveda, ClienteDisplay(boveda, transporte, reloj), almacen, bus, reloj, coordinador, modo)


__all__ = ['ServicioDisplay', 'crear_servicio_display', 'crear_transporte_display', 'pagina_html', 'RUTA_CALLBACK',
           'VIGENCIA_INTENTO_S', 'NOMBRE_SCOPE']
