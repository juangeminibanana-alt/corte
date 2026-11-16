"""Emparejamiento por QR o código (contrato.ts «Protocolo LAN 1»; 03 §7.5; 04 §C.4–§C.6, §C.9; 01 §5.3).

Un solo emparejamiento activo (que acepta código) a la vez:
- `crear()` (POST /api/lan/emparejar): pair_id (16 B en hex), código de 12 Crockford (60 bits) y K_pair (PBKDF2
  200 000). Vence a los 300 s; un solo uso. Si ya había uno ESPERANDO (ningún celular lo usó) se reemplaza; si hay un
  celular esperando la aprobación → 409 `emparejamiento_ocupado`.
- `iniciar()` (POST /lan/v1/pair/start): verifica la prueba con la huella PROPIA del hub (un intermediario que terminó el
  TLS no la puede reproducir). 5 pruebas fallidas queman el código. Si vale: nonce_s, 90 s para aprobar y el evento
  `emparejamiento.solicitud` (la decisión es del usuario, en la PC).
- `decidir()` (POST /api/lan/emparejar/{id}/decision): aprobar crea el dispositivo y sella el LanPaquete con K_enc
  (AES-256-GCM, aad = pair_id); rechazar lo cierra. Publica `emparejamiento.fin`.
- `sondear()` (GET /lan/v1/pair/{id}?nonce_c=…): long-poll de hasta 25 s; tras aprobar, el MISMO paquete se vuelve a
  entregar durante 120 s a sondeos con el nonce_c correcto.
Los secretos (código, K_pair, paquete) nunca se registran.
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ..errores import ErrorDominio
from ..interfaces import Json, Reloj
from . import protocolo_lan as pl

_log = logging.getLogger('creatorhub.lan.emparejamiento')

VIGENCIA_S = 300
APROBAR_S = 90
REENTREGA_S = 120
MAX_FALLOS = 5
CONSERVAR_S = 600                    # sesiones terminadas que aún responden a GET /api/lan/emparejar/{id}
ESPERA_LARGA_S = 25.0

MENSAJES = {
    'vencido': 'Ese código ya caducó. Escanea el código nuevo que aparece en tu PC.',
    'ocupado': 'Tu PC está terminando de emparejar otro celular. Inténtalo en un momento.',
    'prueba': 'El código no coincide. Revisa el código que aparece en tu PC.',
    'no_existe': 'Ese emparejamiento ya no existe.',
    'invalido': 'La solicitud de emparejamiento no es válida.',
    'sin_decision': 'Esa solicitud ya no espera tu respuesta.',
}


@dataclass
class Sesion:
    pair_id: str
    codigo: str                      # normalizado, sin guiones
    k_pair: bytes
    host_id: str
    creado_at: int
    expira_at: int                   # creado + 300 s (o la fecha límite para aprobar, ya con solicitud)
    estado: str = 'esperando'        # esperando | pendiente_aprobacion | aprobado | rechazado | expirado
    fallos: int = 0
    nonce_c: str | None = None
    nonce_s: str | None = None
    nombre: str | None = None
    sas: str | None = None
    paquete: str | None = None
    entregar_hasta: int | None = None
    terminado_at: int | None = None
    solicitud_publicada: bool = False

    def a_contrato(self) -> Json:
        """EmparejamientoEstado."""
        return {'pair_id': self.pair_id, 'estado': self.estado, 'dispositivo': self.nombre,
                'codigo_verificacion': self.sas, 'expira_at': self.expira_at}


class GestorEmparejamiento:
    def __init__(self, reloj: Reloj, publicar: Callable[[Json], None], espera_larga_s: float = ESPERA_LARGA_S) -> None:
        self.reloj = reloj
        self._publicar = publicar
        self.espera_larga_s = espera_larga_s
        self._cond = threading.Condition(threading.RLock())
        self._sesiones: dict[str, Sesion] = {}
        self._activa: str | None = None
        self._cerrado = False

    # -------------------------------------------------------------- utilidades
    def _publicar_seguro(self, evento: Json) -> None:
        try:
            self._publicar(evento)
        except Exception:  # noqa: BLE001 - un suscriptor roto no detiene el emparejamiento
            _log.exception('No se pudo publicar %s', evento.get('tipo'))

    def _terminar(self, s: Sesion, estado: str, ahora: int, publicar: bool) -> None:
        s.estado = estado
        s.terminado_at = ahora
        if self._activa == s.pair_id:
            self._activa = None
        if publicar:
            self._publicar_seguro({'tipo': 'emparejamiento.fin', 'pair_id': s.pair_id, 'resultado': estado})
        self._cond.notify_all()

    def revisar_vencidos(self) -> None:
        """Vence lo que caducó y olvida las sesiones viejas. Se llama en cada operación y desde el mantenimiento."""
        ahora = self.reloj.ahora()
        with self._cond:
            for s in list(self._sesiones.values()):
                if s.estado in ('esperando', 'pendiente_aprobacion') and ahora >= s.expira_at:
                    # una solicitud que nadie aprobó cierra el diálogo de la PC; un QR que nadie usó lo renueva la UI
                    self._terminar(s, 'expirado', ahora, publicar=s.solicitud_publicada)
                if s.terminado_at is not None and ahora - s.terminado_at > max(CONSERVAR_S, REENTREGA_S):
                    del self._sesiones[s.pair_id]

    def activa(self) -> Sesion | None:
        self.revisar_vencidos()
        with self._cond:
            return self._sesiones.get(self._activa) if self._activa else None

    # -------------------------------------------------------------- PC (UI local)
    def crear(self, host_id: str) -> Sesion:
        if not pl.es_host_id(host_id):
            raise ValueError('host_id inválido')
        self.revisar_vencidos()
        codigo = pl.generar_codigo()
        kp = pl.k_pair(codigo, host_id)              # ~0.2 s: una vez por código, fuera del candado
        with self._cond:
            previa = self._sesiones.get(self._activa) if self._activa else None
            if previa is not None and previa.estado == 'pendiente_aprobacion':
                raise ErrorDominio('emparejamiento_ocupado', MENSAJES['ocupado'], http=409)
            ahora = self.reloj.ahora()
            if previa is not None:                    # QR que nadie usó: el nuevo lo reemplaza (sin evento)
                self._terminar(previa, 'expirado', ahora, publicar=False)
            s = Sesion(pair_id=secrets.token_hex(16), codigo=codigo, k_pair=kp, host_id=host_id, creado_at=ahora,
                       expira_at=ahora + VIGENCIA_S)
            self._sesiones[s.pair_id] = s
            self._activa = s.pair_id
            return s

    def estado(self, pair_id: str) -> Json:
        self.revisar_vencidos()
        with self._cond:
            s = self._sesiones.get(pair_id) if isinstance(pair_id, str) else None
            if s is None:
                raise ErrorDominio('no_encontrado', MENSAJES['no_existe'], http=404)
            return s.a_contrato()

    def decidir(self, pair_id: str, decision: Mapping[str, Any],
                crear_paquete: Callable[[Sesion, str], str]) -> Json:
        """DecisionRequest {aprobar, permisos?}. `crear_paquete(sesion, permisos)` da de alta el dispositivo y devuelve
        el paquete sellado (b64url)."""
        if not isinstance(decision, Mapping) or not isinstance(decision.get('aprobar'), bool) \
                or set(decision) - {'aprobar', 'permisos'}:
            raise ErrorDominio('parametros_invalidos', 'La respuesta no es válida.', http=422)
        permisos = decision.get('permisos', 'lectura_escritura')
        if permisos not in ('lectura', 'lectura_escritura'):
            raise ErrorDominio('parametros_invalidos', 'El permiso no es válido.', http=422)
        self.revisar_vencidos()
        with self._cond:
            s = self._sesiones.get(pair_id) if isinstance(pair_id, str) else None
            if s is None:
                raise ErrorDominio('no_encontrado', MENSAJES['no_existe'], http=404)
            if s.estado == 'expirado':
                raise ErrorDominio('emparejamiento_vencido', 'La solicitud caducó. Pide al celular que lo intente de '
                                                             'nuevo.', http=410)
            if s.estado != 'pendiente_aprobacion':
                raise ErrorDominio('conflicto', MENSAJES['sin_decision'], http=409)
            ahora = self.reloj.ahora()
            if decision['aprobar']:
                s.paquete = crear_paquete(s, permisos)
                s.entregar_hasta = ahora + REENTREGA_S
                self._terminar(s, 'aprobado', ahora, publicar=True)
                _log.info('Emparejamiento aprobado en la PC')
            else:
                self._terminar(s, 'rechazado', ahora, publicar=True)
                _log.info('Emparejamiento rechazado en la PC')
            return s.a_contrato()

    def cancelar_todo(self) -> None:
        """Al apagar la LAN o desvincular todo: se cierran las sesiones abiertas y se despiertan los long-poll."""
        ahora = self.reloj.ahora()
        with self._cond:
            for s in self._sesiones.values():
                if s.estado in ('esperando', 'pendiente_aprobacion'):
                    self._terminar(s, 'expirado', ahora, publicar=s.solicitud_publicada)
            self._cond.notify_all()

    def cerrar(self) -> None:
        with self._cond:
            self._cerrado = True
            self._cond.notify_all()

    def abrir(self) -> None:
        with self._cond:
            self._cerrado = False

    # -------------------------------------------------------------- celular (LAN)
    def iniciar(self, req: Any, huella_hex: str) -> Json:
        """LanPairStartRequest -> LanPairStartResponse. ErrorDominio con el código del contrato si no procede."""
        if not isinstance(req, Mapping):
            raise ErrorDominio('parametros_invalidos', MENSAJES['invalido'], http=400)
        nonce_c, prueba, plataforma = req.get('nonce_c'), req.get('prueba'), req.get('plataforma')
        try:
            nombre = pl.validar_nombre_celular(req.get('nombre'))
        except ValueError:
            raise ErrorDominio('parametros_invalidos', MENSAJES['invalido'], http=400) from None
        if plataforma != 'android' or not pl.nonce_emparejamiento_valido(nonce_c) or not isinstance(prueba, str) \
                or len(prueba) > 64 or (req.get('pair_id') is not None and not isinstance(req.get('pair_id'), str)):
            raise ErrorDominio('parametros_invalidos', MENSAJES['invalido'], http=400)
        self.revisar_vencidos()
        with self._cond:
            s = self._sesiones.get(self._activa) if self._activa else None
            if s is None or (req.get('pair_id') is not None and req.get('pair_id') != s.pair_id):
                raise ErrorDominio('emparejamiento_vencido', MENSAJES['vencido'], http=410)
            ahora = self.reloj.ahora()
            if not pl.prueba_correcta(s.k_pair, nonce_c, huella_hex, nombre, prueba):
                s.fallos += 1
                if s.fallos >= MAX_FALLOS:            # 5 fallos queman el código: la PC muestra uno nuevo
                    _log.warning('Código de emparejamiento quemado tras %d pruebas fallidas', s.fallos)
                    self._terminar(s, 'expirado', ahora, publicar=True)
                raise ErrorDominio('firma_invalida', MENSAJES['prueba'], http=401)
            if s.estado == 'pendiente_aprobacion':
                if s.nonce_c == nonce_c and s.nombre == nombre:   # reintento del mismo celular (respuesta perdida)
                    return self._respuesta_inicio(s)
                raise ErrorDominio('emparejamiento_ocupado', MENSAJES['ocupado'], http=409)
            s.estado = 'pendiente_aprobacion'
            s.nonce_c, s.nonce_s, s.nombre = nonce_c, pl.nuevo_nonce(), nombre
            s.sas = pl.sas(s.k_pair, s.nonce_c, s.nonce_s)
            s.expira_at = ahora + APROBAR_S           # 90 s para que el usuario apruebe en la PC (04 §C.9)
            s.solicitud_publicada = True
            self._publicar_seguro({'tipo': 'emparejamiento.solicitud', 'pair_id': s.pair_id, 'dispositivo': nombre,
                                   'codigo_verificacion': s.sas, 'expira_at': s.expira_at})
            self._cond.notify_all()
            return self._respuesta_inicio(s)

    @staticmethod
    def _respuesta_inicio(s: Sesion) -> Json:
        return {'pair_id': s.pair_id, 'nonce_s': s.nonce_s, 'expira_at': s.expira_at, 'estado': 'pendiente_aprobacion'}

    def sondear(self, pair_id: str, nonce_c: str | None, espera_s: float | None = None) -> Json:
        """LanPairPollResponse. Espera hasta `espera_s` (25 s) mientras siga pendiente de aprobación."""
        espera = self.espera_larga_s if espera_s is None else espera_s
        limite = time.monotonic() + max(0.0, espera)
        while True:
            self.revisar_vencidos()
            with self._cond:
                s = self._sesiones.get(pair_id) if isinstance(pair_id, str) else None
                if s is None or not isinstance(nonce_c, str) or s.nonce_c is None \
                        or not secrets.compare_digest(s.nonce_c.encode('ascii'), nonce_c.encode('utf-8', 'replace')):
                    raise ErrorDominio('no_encontrado', MENSAJES['no_existe'], http=404)
                if s.estado == 'aprobado':
                    if s.entregar_hasta is not None and self.reloj.ahora() <= s.entregar_hasta:
                        return {'estado': 'aprobado', 'paquete': s.paquete}
                    return {'estado': 'expirado'}
                if s.estado != 'pendiente_aprobacion':
                    return {'estado': s.estado}
                restante = limite - time.monotonic()
                if restante <= 0 or self._cerrado:
                    return {'estado': 'pendiente_aprobacion'}
                # se despierta al decidir; cada segundo revisa el vencimiento (reloj del hub)
                self._cond.wait(min(restante, 1.0))
