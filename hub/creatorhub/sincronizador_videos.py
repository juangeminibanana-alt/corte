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
  borra en la misma transacción que guarda el perfil nuevo; si es del creador y la conexión es de otra cuenta, olvida
  esa autorización sin escribir nada. Cubre una conexión cuyo perfil no se pudo comprobar al conectar.
- El cursor guarda también `visto_tope` (el visto_at más reciente al escribirlo): `publicacion` del catálogo lo usa para
  reconocer los videos que vio una pasada posterior sin depender de que el reloj nunca se atrase.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .errores import ErrorApi
from .interfaces import PedidoImagen

_log = logging.getLogger('creatorhub.sincronizador')

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
        llamadas0 = getattr(s.cliente, 'llamadas', 0)
        self._escala[paso] = (desde, 1.0 - desde)
        self._avance(paso, 0.0, texto=TEXTO_VIDEOS_TIKTOK)
        try:
            conexion = s.boveda.leer()
            revision = (conexion.get('client_key'), conexion.get('epoca_credenciales', 0))
            perfil = D.normalizar_usuario(s.cliente.usuario())
            perfil['open_id'] = perfil.get('open_id') or conexion.get('open_id')   # la cuenta de esta conexión
            # De quién es lo guardado: puede preguntar a TikTok (video/query), así que nunca con una transacción abierta.
            decision = s.cuenta_de_lo_guardado(perfil)
            if decision == 'rechazar':
                raise s.olvidar_autorizacion_ajena(revision) or ErrorDisplay('solicitud_rechazada', D.MSG_OTRA_CUENTA)
            with self._tx() as db:
                if decision == 'otra':
                    # Una conexión cuyo perfil no se pudo comprobar al conectar: lo guardado era de otra cuenta.
                    _log.info('Los datos guardados de la Display API eran de otra cuenta: se borran (sync %s)',
                              getattr(self, 'sid', '?'))
                    D.borrar_todo(db)
                    self.alm.subir_img_rev(db)
                    self.alm.marcar_data_version(db)
                    self.secciones.update(('videos', 'cuenta'))
                if D.guardar_perfil(db, perfil, self.ahora):
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
                    with self._tx() as db:
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
                with self._tx() as db:
                    if listado.completo:
                        r['quitados'] = D.quitar_no_vistos(db, vistos)
                    podados = D.podar_historial(db, self.ahora)
                    if r['quitados'] or podados:
                        self.alm.marcar_data_version(db)
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
        cambios = r['nuevos'] + r['cambiados'] + r['quitados']
        if cambios:
            self.cambios += cambios
            self.secciones.add('videos')
        self.resumen['videos_tiktok'] = dict(r)
        ultima = {'at': self.ahora, 'estado': r['estado'], 'videos': r['videos'], 'nuevos': r['nuevos'],
                  'cambiados': r['cambiados'], 'quitados': r['quitados'], 'completa': r['completa'],
                  'error': None if error is None else {'codigo': error.codigo, 'mensaje': error.mensaje}}
        try:
            with self._tx() as db:
                # visto_tope: el visto_at más reciente al escribir el cursor, en su misma transacción. Un visto_at mayor
                # solo puede venir de una pasada POSTERIOR (en curso o interrumpida), aunque el reloj se haya atrasado.
                ultima['visto_tope'] = db.execute('SELECT MAX(visto_at) FROM videos_tiktok').fetchone()[0] or 0
                self._poner_cursor(db, D.CLAVE_ULTIMA_SYNC, json.dumps(ultima, ensure_ascii=False), self.ahora)
        except ErrorApi:                                 # cambió la cuenta o la época: igual que _poner_cursor_tx
            pass
        s.anotar_resultado(error)
        s.publicar()
        self._avance(paso, 1.0)


__all__ = ['PasoVideosTikTok', 'TEXTO_VIDEOS_TIKTOK', 'PASO_PUBLICO', 'TOPE_VIDEOS']
