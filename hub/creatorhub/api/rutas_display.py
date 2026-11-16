"""Rutas LOCALES de la Display API (rev. 5, 15/11/2026): mismo patrón que api/rutas.py (Ruta, Peticion, ErrorRespuesta
con limpiar(), JSON UTF-8, gzip, Cache-Control no-store), pero en un despachador APARTE.

Por qué aparte: el Despachador principal es el que también atiende a los celulares (servidor_lan → `/lan/v1/api/*`) y
su tabla es exactamente la de BUILD_SPEC §5. Estas rutas solo existen en el servidor de interfaz de 127.0.0.1
(api/servidor.py las encamina aquí DESPUÉS de comprobar Host, Origin, la cookie de sesión, la cubeta y, en mutaciones,
`X-CH-Hub: 1`); el servidor LAN ni siquiera las conoce (por la LAN responden 404). Por si alguien las despachara con un
contexto de celular, todas son 'local' (403 solo_local).

  GET  /api/display/estado        → EstadoDisplay
  PUT  /api/display/credenciales  {client_key, client_secret} → EstadoDisplay
  POST /api/display/conectar      {abrir_navegador?} → ConectarDisplayResponse {url, expira_at, abierto}
  POST /api/display/desconectar   {borrar_datos?, olvidar_app?} → DesconectarDisplayResponse {display, revocado}

El callback `GET /oauth/tiktok` NO pasa por aquí: lo atiende el servidor de interfaz (lo abre el navegador del
sistema, sin la cookie de la ventana; lo protege el state de un solo uso + PKCE).
"""
from __future__ import annotations

from typing import Any

from ..errores import ErrorDominio
from ..interfaces import Despachador, Json
from .rutas import MSG_CAMPOS, MSG_NO_ENCONTRADO, DespachadorHub, Peticion, Ruta

PREFIJO = '/api/display/'


def es_ruta_display(ruta: str) -> bool:
    return ruta == '/api/display' or ruta.startswith(PREFIJO)


class DespachadorDisplay(DespachadorHub):
    """`hub.display` es el ServicioDisplay (None en hubs de prueba sin Display API → 404)."""

    def _tabla(self) -> list[Ruta]:
        X = 'local'
        return [
            Ruta('GET', 'api/display/estado', lambda p: self._servicio().estado(), X),
            Ruta('PUT', 'api/display/credenciales', self._credenciales, X),
            Ruta('POST', 'api/display/conectar', self._conectar, X),
            Ruta('POST', 'api/display/desconectar', self._desconectar, X),
        ]

    def _servicio(self) -> Any:
        s = getattr(self.hub, 'display', None)
        if s is None:
            raise ErrorDominio('no_encontrado', MSG_NO_ENCONTRADO, http=404)
        return s

    def _vivos(self) -> tuple[str, ...]:
        vivos = super()._vivos()
        try:
            s = getattr(self.hub, 'display', None)
            return tuple(dict.fromkeys(vivos + (tuple(s.secretos_vivos()) if s is not None else ())))
        except Exception:  # noqa: BLE001
            return vivos

    @staticmethod
    def _booleano(b: dict[str, Any], campo: str) -> bool:
        v = b.get(campo, False)
        if not isinstance(v, bool):
            raise ErrorDominio('parametros_invalidos', MSG_CAMPOS, http=422, detalle={'campo': campo})
        return v

    def _credenciales(self, p: Peticion) -> Json:
        b = p.objeto({'client_key', 'client_secret'})
        for campo in ('client_key', 'client_secret'):
            if not isinstance(b.get(campo), str):
                raise ErrorDominio('parametros_invalidos', MSG_CAMPOS, http=422, detalle={'campo': campo})
        return self._servicio().guardar_credenciales(b['client_key'], b['client_secret'])

    def _conectar(self, p: Peticion) -> Json:
        b = p.objeto({'abrir_navegador'})
        return self._servicio().iniciar_conexion(self._booleano(b, 'abrir_navegador'))

    def _desconectar(self, p: Peticion) -> Json:
        b = p.objeto({'borrar_datos', 'olvidar_app'})
        return self._servicio().desconectar(self._booleano(b, 'borrar_datos'), self._booleano(b, 'olvidar_app'))


def crear_despachador_display(hub: Any) -> Despachador:
    return DespachadorDisplay(hub)


__all__ = ['DespachadorDisplay', 'crear_despachador_display', 'es_ruta_display', 'PREFIJO']
