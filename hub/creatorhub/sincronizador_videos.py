"""Paso «videos_tiktok» de la sincronización (rev. 5, 15/11/2026): métricas de TUS videos con la Display API.

Corre DENTRO del paso público `videos` (segunda mitad de su avance, después de las portadas C4), igual que las fases de
la ficha completa corren dentro de `productos_ventas`: `PasoSync` del contrato NO cambia (la interfaz tiene
`Record<PasoSync, …>` exhaustivos). Sus cifras van a `sync_ejecuciones.resumen_json['videos_tiktok']` = {estado,
videos, nuevos, cambiados, quitados, llamadas, completa, codigo} y a `sync_cursores['display.ultima_sync']` (lo lee
EstadoDisplay.ultima_sync).

- Se SALTA EN SILENCIO (sin tocar el avance, sin error y sin escribir nada) si no hay servicio, credenciales o
  conexión, o si la conexión está marcada para volver a autorizar.
- Trae el perfil (user/info) y TODOS los videos públicos con video/list (máx. 1,000, de 20 en 20 por cursor). Cada
  página se guarda en su propia transacción del escritor con época (nunca hay red con una transacción abierta) y sus
  portadas se encolan DESPUÉS de confirmarla ('v:<video_id>', firmadas: van primero en la cola porque caducan en ~6 h).
- Si el listado llegó al final (has_more = false), los videos que ya no salen (privados o borrados) dejan de estar en
  videos_tiktok: sus campos en la analítica vuelven a null.
- Sus errores NUNCA vuelven parcial ni fallida la sync de TikTok Shop ni tocan auth_estado: quedan en EstadoDisplay
  (ultimo_error) y en el resumen. Solo se propagan los de control de la sync (cancelar, cambio de cuenta/época).
- Rev. 6 (18/11/2026): antes de guardar el perfil decide de quién es lo guardado (`ServicioDisplay.cuenta_de_lo_guardado`,
  que puede preguntar a TikTok con video/query, fuera de toda transacción). Si se comprueba que es de otra cuenta, lo
  borra en la misma transacción que guarda el perfil nuevo; si no se puede dejar entrar a esa cuenta, olvida su
  autorización sin tocar los datos (la pasada queda registrada como error). Sin pruebas, no guarda ni borra nada.
- Antes de cada escritura comprueba que la conexión sigue siendo la misma con la que decidió; si cambió (otra
  autorización, desconectar), termina sin escribir más ni anotar error ni cursor: lo hará la pasada de la nueva.
- El cursor guarda también `visto_tope` (el visto_at más reciente al escribirlo) y, mientras una pasada no se registra,
  'display.pasadas_sin_registrar' lleva su instante: `publicacion` del catálogo reconoce así los videos que vio una
  pasada posterior (en curso o interrumpida) sin depender de que el reloj nunca se atrase.
"""
from __future__ import annotations

import contextlib
import json
import logging
from typing import Any, Iterator

from .errores import ErrorApi
from .interfaces import PedidoImagen

_log = logging.getLogger('creatorhub.sincronizador')


class _ConexionCambio(Exception):
    """La conexión de la Display API cambió durante el paso: lo traído ya no es de la conexión vigente."""


PASO_PUBLICO = 'videos'
TEXTO_VIDEOS_TIKTOK = 'Trayendo las vistas de tus videos…'
TOPE_VIDEOS = 1000


class PasoVideosTikTok:
    """Lo usa `_Sincronizador`, que aporta _tx, _encolar, _avance, _poner_cursor, _comprobar_cancelacion,
    _error_de_control, alm, ahora, sid, resumen, cambios, secciones, _escala y _c."""

    display: Any = None

    def fijar_display(self, servicio: Any) -> None:
        """hub.py lo enlaza después de crear el sincronizador (la fábrica conserva su firma de interfaces.FABRICAS)."""
        self.display = servicio

    def _videos_tiktok_activo(self) -> bool:
        s = getattr(self, 'display', None)
        if s is None:
            return False
        try:
            return bool(s.listo())
        except Exception:  # noqa: BLE001 - un servicio roto nunca detiene la sync
            _log.warning('No se pudo revisar la conexión de la Display API', exc_info=True)
            return False

    def _correr_videos_tiktok(self, paso: str, desde: float) -> None:
        from .tiktok_dev import datos as D
        from .tiktok_dev.errores import ErrorDisplay

        s = self.display
        r: dict[str, Any] = {'estado': 'ok', 'videos': 0, 'nuevos': 0, 'cambiados': 0, 'quitados': 0, 'llamadas': 0,
                             'completa': False, 'codigo': None}
        error: ErrorDisplay | None = None
        cambio_de_conexion = False
        llamadas0 = getattr(s.cliente, 'llamadas', 0)
        conexion = s.boveda.leer()
        revision = (conexion.get('client_key'), conexion.get('epoca_credenciales', 0))

        @contextlib.contextmanager
        def tx_vigente() -> Iterator[Any]:
            """Cada escritura del paso, solo si la conexión sigue siendo con la que se decidió, comprobado con la bóveda
            tomada (el mismo orden que el callback y la importación: bóveda → escritor). Otra autorización, desconectar
            o un cambio de credenciales suben la época; renovar el token no."""
            with s.boveda.candado:
                actual = s.boveda.leer()
                if (actual.get('client_key'), actual.get('epoca_credenciales', 0)) != revision:
                    raise _ConexionCambio()
                with self._tx() as db:
                    yield db
        self._escala[paso] = (desde, 1.0 - desde)
        self._avance(paso, 0.0, texto=TEXTO_VIDEOS_TIKTOK)
        try:
            perfil = D.normalizar_usuario(s.cliente.usuario())
            perfil['open_id'] = perfil.get('open_id') or conexion.get('open_id')   # la cuenta de esta conexión
            # De quién es lo guardado: puede preguntar a TikTok (video/query), así que nunca con una transacción abierta.
            decision = s.cuenta_de_lo_guardado(perfil)
            if decision == 'rechazar':
                rechazo = s.olvidar_autorizacion_ajena(revision)
                if rechazo is None:
                    raise _ConexionCambio()
                raise rechazo
            with tx_vigente() as db:
                if decision == 'otra':
                    # Una conexión cuyo perfil no se pudo comprobar al conectar: lo guardado era de otra cuenta.
                    _log.info('Los datos guardados de la Display API eran de otra cuenta: se borran (sync %s)',
                              getattr(self, 'sid', '?'))
                    D.borrar_todo(db)
                    self.alm.subir_img_rev(db)
                    self.alm.marcar_data_version(db)
                    self.secciones.update(('videos', 'cuenta'))
                previas = [x for x in D.pasadas_sin_registrar(db) if x != self.ahora]
                self._poner_cursor(db, D.CLAVE_SIN_REGISTRAR,
                                   json.dumps([*previas, self.ahora][-D.MAX_SIN_REGISTRAR:]), self.ahora)
                if D.guardar_perfil(db, perfil, self.ahora, conservar_identidad=decision == 'misma'):
                    self.alm.marcar_data_version(db)
                    self.secciones.add('cuenta')
            self._comprobar_cancelacion()
            total = perfil.get('videos_total') or 0
            scopes = set((s.boveda.leer().get('scopes') or []))
            if scopes and 'video.list' not in scopes:
                r['estado'], r['codigo'] = 'sin_permiso', 'permiso_faltante'
                error = ErrorDisplay('permiso_faltante')
            else:
                vistos: set[str] = set()
                listado = s.cliente.listar_videos(TOPE_VIDEOS, self._c.ctx.cancelar)
                for crudos in listado:
                    self._comprobar_cancelacion()
                    pagina = [v for v in (D.normalizar_video(x) for x in crudos)
                              if v is not None and v['video_id'] not in vistos]
                    vistos.update(v['video_id'] for v in pagina)
                    with tx_vigente() as db:
                        n, c = D.guardar_videos(db, pagina, self.ahora)
                        if n + c:
                            self.alm.marcar_data_version(db)
                    r['nuevos'] += n
                    r['cambiados'] += c
                    self._encolar([PedidoImagen('v', v['video_id'], v['portada_url'], 1, 'portada')
                                   for v in pagina if v['portada_url']])
                    hechos = len(vistos)
                    self._avance(paso, min(0.98, hechos / total) if total else min(0.9, hechos / TOPE_VIDEOS))
                self._comprobar_cancelacion()
                r['videos'] = len(vistos)
                r['completa'] = bool(listado.completo)
                with tx_vigente() as db:
                    if listado.completo:
                        r['quitados'] = D.quitar_no_vistos(db, vistos)
                    podados = D.podar_historial(db, self.ahora)
                    if r['quitados'] or podados:
                        self.alm.marcar_data_version(db)
        except _ConexionCambio:
            cambio_de_conexion = True
        except ErrorDisplay as e:
            error = e
            r['estado'] = 'parcial' if (r['nuevos'] or r['cambiados']) else 'error'
            r['codigo'] = e.codigo
            _log.info('Videos de TikTok (Display API): %s (sync %s)', e.codigo, getattr(self, 'sid', '?'))
        except Exception as e:  # noqa: BLE001 - una falla de la Display API nunca tumba la sync (salvo las de control)
            if self._error_de_control(e):
                raise
            _log.exception('Falla interna en el paso videos_tiktok (sync %s)', getattr(self, 'sid', '?'))
            r['estado'], r['codigo'] = 'error', 'error_interno'
            error = ErrorDisplay('error_interno')
        finally:
            self._escala.pop(paso, None)
        r['llamadas'] = getattr(s.cliente, 'llamadas', 0) - llamadas0
        if cambio_de_conexion:
            # La pasada ya no es de la conexión vigente: no se anota error ni cursor (los de la conexión nueva valen).
            _log.info('La conexión de la Display API cambió durante el paso videos_tiktok (sync %s)',
                      getattr(self, 'sid', '?'))
            r['estado'], r['codigo'] = 'error', 'sin_conexion'
            if r['nuevos'] + r['cambiados']:
                self.cambios += r['nuevos'] + r['cambiados']
                self.secciones.add('videos')
            self.resumen['videos_tiktok'] = dict(r)
            self._avance(paso, 1.0)
            return
        cambios = r['nuevos'] + r['cambiados'] + r['quitados']
        if cambios:
            self.cambios += cambios
            self.secciones.add('videos')
        self.resumen['videos_tiktok'] = dict(r)
        ultima = {'at': self.ahora, 'estado': r['estado'], 'videos': r['videos'], 'nuevos': r['nuevos'],
                  'cambiados': r['cambiados'], 'quitados': r['quitados'], 'completa': r['completa'],
                  'error': None if error is None else {'codigo': error.codigo, 'mensaje': error.mensaje}}
        registrar = True
        try:
            with tx_vigente() as db:
                # visto_tope: el visto_at más reciente al escribir el cursor, en su misma transacción. Un visto_at mayor
                # solo puede venir de una pasada POSTERIOR (en curso o interrumpida), aunque el reloj se haya atrasado.
                ultima['visto_tope'] = db.execute('SELECT MAX(visto_at) FROM videos_tiktok').fetchone()[0] or 0
                self._poner_cursor(db, D.CLAVE_ULTIMA_SYNC, json.dumps(ultima, ensure_ascii=False), self.ahora)
                db.execute('DELETE FROM sync_cursores WHERE clave = ?', (D.CLAVE_SIN_REGISTRAR,))   # ya registrada
        except ErrorApi:                                 # cambió la cuenta o la época: igual que _poner_cursor_tx
            pass
        except _ConexionCambio:                          # la conexión cambió al terminar: lo anota la pasada de la nueva
            registrar = False
        if registrar:
            s.anotar_resultado(error, revision)
        s.publicar()
        self._avance(paso, 1.0)


__all__ = ['PasoVideosTikTok', 'TEXTO_VIDEOS_TIKTOK', 'PASO_PUBLICO', 'TOPE_VIDEOS']
