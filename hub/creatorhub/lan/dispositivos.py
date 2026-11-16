"""Celulares emparejados y verificación CH1 (contrato.ts «Protocolo LAN 1»; 03 §6.6, §7.1, §7.4; 04 §C.7–§C.9).

Tabla `dispositivos` de la base (esquema de spec/verificacion/schema.sql). Reglas:
- `device_key` (32 B) solo se guarda cifrada con DPAPI (entropía `CreatorHub/dispositivo/v1|<device_id>`); en memoria
  solo se cachean los bytes de `k_mac` por blob y se purgan al revocar. Ninguna llave va a los registros.
- Verificación de cada petición firmada, en este orden (04 §C.7): formato exacto de la cabecera → dispositivo
  desconocido / revocado → |ts − ahora| ≤ 300 s (si no, `reloj_desfasado` con `detalle.hora_servidor`) → firma con
  `hmac.compare_digest` (llave vigente y, en rotación, la pendiente) → nonce único por dispositivo durante 600 s
  (deque + set con candado, tope 4,096). La fila se lee en cada petición: una revocación o un «Borrar todo» hecho por
  otra vía se respetan al instante.
- Rotación en DOS FASES: `/rotar` guarda la nueva en `clave_pendiente_dpapi`; la vieja sigue valiendo SIN plazo hasta la
  primera petición válida firmada con la nueva (entonces se descarta la vieja). Si la nueva no se usa en 7 días se
  descarta la NUEVA, nunca la vieja. Toca rotar (cabecera `X-CH-Rotar: 1`) cada 30 días.
- La primera petición firmada marca `confirmado_at`; si no llega en 10 min tras aprobar, el dispositivo se borra.
- Accesos (`ultimo_uso_at`, `ultima_ip`) en memoria, volcados cada 60 s (`volcar_accesos`) o al cambiar la IP.
"""
from __future__ import annotations

import collections
import hashlib
import hmac
import logging
import re
import secrets
import threading
from dataclasses import dataclass
from typing import Any, Mapping

from ..cripto import dpapi
from ..errores import ErrorDominio
from ..interfaces import Almacen, Json, Reloj
from . import protocolo_lan as pl

_log = logging.getLogger('creatorhub.lan.dispositivos')

ENTROPIA_DISPOSITIVO = b'CreatorHub/dispositivo/v1|'
VENTANA_S = 300                     # ±300 s (contrato.ts)
RETENCION_NONCES_S = 600            # ≥ 2 × ventana
TOPE_NONCES = 4096
GRACIA_S = 7 * 86400                # LanRotarResponse.gracia_s
ROTAR_CADA_S = 30 * 86400
CONFIRMAR_ANTES_S = 600             # 03 §7.5 paso 6
MAX_ACTIVOS = 16                    # 04 §C.9
MAX_NOMBRE = 48                     # CHECK de la tabla
PERMISOS = ('lectura', 'lectura_escritura')
_RE_DEVICE = re.compile(r'^[0-9a-f]{32}$')
_COLUMNAS = ('device_id, nombre, plataforma, permisos, creado_at, confirmado_at, clave_rotada_at, ultimo_uso_at, '
             'ultima_ip, revocado_at, clave_dpapi, clave_pendiente_dpapi, clave_pendiente_at')

MENSAJES = {
    'firma_invalida': 'La firma de la petición no es válida.',
    'reloj_desfasado': 'La hora del celular y la de la PC no coinciden.',
    'repetida': 'Esta petición ya se había recibido.',
    'dispositivo_desconocido': 'Tu PC no reconoce este celular. Vuelve a emparejarlo.',
    'dispositivo_revocado': 'Tu PC ya no reconoce este celular. Vuelve a emparejarlo para actualizarte.',   # 01 §4.16
}


def error_auth(codigo: str, **detalle: Any) -> ErrorDominio:
    return ErrorDominio(codigo, MENSAJES[codigo], http=401, detalle=detalle or None)


@dataclass(frozen=True)
class Verificado:
    device_id: str
    permisos: str
    rotar: bool                     # agregar X-CH-Rotar: 1 a la respuesta


@dataclass
class _Fila:
    device_id: str
    nombre: str
    plataforma: str
    permisos: str
    creado_at: int
    confirmado_at: int | None
    clave_rotada_at: int
    ultimo_uso_at: int | None
    ultima_ip: str | None
    revocado_at: int | None
    clave: bytes
    pendiente: bytes | None
    pendiente_at: int | None


def _entropia(device_id: str) -> bytes:
    return ENTROPIA_DISPOSITIVO + device_id.encode('ascii')


class RegistroDispositivos:
    """Celulares emparejados sobre la tabla `dispositivos` (un escritor: `almacen.escritor()`)."""

    def __init__(self, almacen: Almacen, reloj: Reloj) -> None:
        self.almacen = almacen
        self.reloj = reloj
        self._candado = threading.RLock()
        self._kmac: dict[tuple[str, bytes], bytes] = {}                     # (device_id, sha256(blob)) -> k_mac
        self._nonces: dict[str, tuple[collections.deque, set]] = {}
        self._accesos: dict[str, tuple[int, str]] = {}                      # device_id -> (ultimo_uso_at, ip)
        self._ip_conocida: dict[str, str | None] = {}

    # -------------------------------------------------------------- lectura
    def _leer(self, device_id: str) -> _Fila | None:
        with self.almacen.lector() as c:
            r = c.execute(f'SELECT {_COLUMNAS} FROM dispositivos WHERE device_id=?', (device_id,)).fetchone()
        return _Fila(*tuple(r)) if r is not None else None

    def _todas(self) -> list[_Fila]:
        with self.almacen.lector() as c:
            filas = c.execute(f'SELECT {_COLUMNAS} FROM dispositivos ORDER BY creado_at, device_id').fetchall()
        return [_Fila(*tuple(r)) for r in filas]

    def _a_contrato(self, f: _Fila) -> Json:
        uso, ip = f.ultimo_uso_at, f.ultima_ip
        with self._candado:
            pendiente = self._accesos.get(f.device_id)
        if pendiente is not None and (uso is None or pendiente[0] >= uso):
            uso, ip = pendiente
        return {'device_id': f.device_id, 'nombre': f.nombre, 'plataforma': 'android', 'permisos': f.permisos,
                'creado_at': f.creado_at, 'ultimo_uso_at': uso, 'ultima_ip': ip, 'clave_rotada_at': f.clave_rotada_at,
                'revocado_at': f.revocado_at}

    def listar(self) -> list[Json]:
        """Dispositivo[] (incluye los revocados con su `revocado_at`; la interfaz decide qué mostrar)."""
        return [self._a_contrato(f) for f in self._todas()]

    def obtener(self, device_id: str) -> Json | None:
        f = self._leer(device_id) if isinstance(device_id, str) and _RE_DEVICE.match(device_id) else None
        return self._a_contrato(f) if f else None

    def activos(self) -> int:
        with self.almacen.lector() as c:
            return int(c.execute('SELECT COUNT(*) FROM dispositivos WHERE revocado_at IS NULL').fetchone()[0])

    # -------------------------------------------------------------- alta, cambios y revocación
    def crear(self, nombre: str, permisos: str) -> tuple[str, bytes]:
        """Alta al aprobar un emparejamiento -> (device_id, device_key). La llave en claro no se guarda."""
        if permisos not in PERMISOS:
            raise ErrorDominio('parametros_invalidos', 'El permiso no es válido.', http=422)
        nombre = (nombre or 'Celular').strip()[:MAX_NOMBRE] or 'Celular'
        if self.activos() >= MAX_ACTIVOS:
            raise ErrorDominio('prohibido', f'Ya tienes {MAX_ACTIVOS} celulares emparejados. Olvida alguno en esta PC '
                                            'para agregar otro.', http=409)
        device_id = secrets.token_hex(16)
        device_key = secrets.token_bytes(32)
        blob = dpapi.proteger(device_key, _entropia(device_id))
        ahora = self.reloj.ahora()
        with self.almacen.escritor() as c:
            c.execute('INSERT INTO dispositivos(device_id, nombre, plataforma, clave_dpapi, permisos, creado_at, '
                      'clave_rotada_at) VALUES (?,?,?,?,?,?,?)',
                      (device_id, nombre, 'android', blob, permisos, ahora, ahora))
        return device_id, device_key

    def cambiar(self, device_id: str, cambios: Mapping[str, Any]) -> Json:
        """DispositivoCambios {nombre?, permisos?} -> Dispositivo."""
        if not isinstance(cambios, Mapping) or set(cambios) - {'nombre', 'permisos'}:
            raise ErrorDominio('parametros_invalidos', 'Solo se puede cambiar el nombre o el permiso.', http=422)
        f = self._leer(device_id) if isinstance(device_id, str) and _RE_DEVICE.match(device_id) else None
        if f is None or f.revocado_at is not None:
            raise ErrorDominio('no_encontrado', 'Ese celular ya no está emparejado.', http=404)
        sets: list[str] = []
        valores: list[Any] = []
        if 'nombre' in cambios:
            n = cambios['nombre']
            if not isinstance(n, str) or not n.isprintable() or not 1 <= len(n.strip()) <= MAX_NOMBRE:
                raise ErrorDominio('parametros_invalidos', 'El nombre debe tener de 1 a 48 caracteres.', http=422)
            sets.append('nombre=?')
            valores.append(n.strip())
        if 'permisos' in cambios:
            if cambios['permisos'] not in PERMISOS:
                raise ErrorDominio('parametros_invalidos', 'El permiso no es válido.', http=422)
            sets.append('permisos=?')
            valores.append(cambios['permisos'])
        if sets:
            with self.almacen.escritor() as c:
                c.execute(f'UPDATE dispositivos SET {", ".join(sets)} WHERE device_id=?', (*valores, device_id))
        return self.obtener(device_id) or {}

    def _purgar_memoria(self, device_id: str) -> None:
        with self._candado:
            for k in [k for k in self._kmac if k[0] == device_id]:
                del self._kmac[k]
            self._nonces.pop(device_id, None)
            self._ip_conocida.pop(device_id, None)

    def revocar(self, device_id: str) -> None:
        """Revocación inmediata: la siguiente petición recibe 401 dispositivo_revocado."""
        f = self._leer(device_id) if isinstance(device_id, str) and _RE_DEVICE.match(device_id) else None
        if f is None:
            raise ErrorDominio('no_encontrado', 'Ese celular ya no está emparejado.', http=404)
        self.volcar_accesos()
        if f.revocado_at is None:
            with self.almacen.escritor() as c:
                c.execute('UPDATE dispositivos SET revocado_at=?, clave_pendiente_dpapi=NULL, clave_pendiente_at=NULL '
                          'WHERE device_id=? AND revocado_at IS NULL', (self.reloj.ahora(), device_id))
        self._purgar_memoria(device_id)

    def revocar_todos(self) -> None:
        self.volcar_accesos()
        with self.almacen.escritor() as c:
            c.execute('UPDATE dispositivos SET revocado_at=?, clave_pendiente_dpapi=NULL, clave_pendiente_at=NULL '
                      'WHERE revocado_at IS NULL', (self.reloj.ahora(),))
        with self._candado:
            self._kmac.clear()
            self._nonces.clear()
            self._ip_conocida.clear()

    # -------------------------------------------------------------- llaves
    def _k_mac(self, device_id: str, blob: bytes) -> bytes:
        clave = (device_id, hashlib.sha256(blob).digest())
        with self._candado:
            k = self._kmac.get(clave)
        if k is None:
            k = pl.k_mac(dpapi.desproteger(blob, _entropia(device_id)))
            with self._candado:
                self._kmac[clave] = k
        return k

    def _firma_ok(self, device_id: str, blob: bytes | None, canon: bytes, sig: str) -> bool:
        if not blob:
            return False
        try:
            k = self._k_mac(device_id, blob)
        except (dpapi.ErrorDpapi, ValueError):
            _log.warning('La llave guardada de un celular no se pudo descifrar')
            return False
        return hmac.compare_digest(pl.firma(k, canon).encode('ascii'), sig.encode('ascii'))

    # -------------------------------------------------------------- verificación CH1
    def verificar(self, cabecera: str | None, metodo: str, ruta_query: str, cuerpo: bytes, ip: str) -> Verificado:
        """Verifica la petición firmada. ErrorDominio 401 con el código de 04 §C.7 si no vale."""
        try:
            c = pl.leer_autorizacion(cabecera or '')
        except ValueError:
            raise error_auth('firma_invalida') from None
        device_id = c['device']
        if not _RE_DEVICE.match(device_id):
            raise error_auth('firma_invalida')
        f = self._leer(device_id)
        if f is None:
            raise error_auth('dispositivo_desconocido')
        if f.revocado_at is not None:
            raise error_auth('dispositivo_revocado')
        ahora = self.reloj.ahora()
        if abs(ahora - c['ts']) > VENTANA_S:
            raise error_auth('reloj_desfasado', hora_servidor=ahora)
        canon = pl.canonico(metodo, ruta_query, c['ts'], c['nonce'], cuerpo)
        pendiente_vigente = f.pendiente is not None and f.pendiente_at is not None and ahora - f.pendiente_at <= GRACIA_S
        if self._firma_ok(device_id, f.clave, canon, c['sig']):
            usada = 'vigente'
        elif pendiente_vigente and self._firma_ok(device_id, f.pendiente, canon, c['sig']):
            usada = 'pendiente'
        else:
            raise error_auth('firma_invalida')
        with self._candado:
            cola, vistos = self._nonces.setdefault(device_id, (collections.deque(), set()))
            while cola and (ahora - cola[0][0] > RETENCION_NONCES_S or len(cola) >= TOPE_NONCES):
                vistos.discard(cola.popleft()[1])
            if c['nonce'] in vistos:
                raise error_auth('repetida')
            cola.append((ahora, c['nonce']))
            vistos.add(c['nonce'])
        if usada == 'pendiente' or f.confirmado_at is None:
            with self.almacen.escritor() as conn:
                if usada == 'pendiente':            # primera petición con la nueva: ahora sí se descarta la vieja
                    conn.execute('UPDATE dispositivos SET clave_dpapi=clave_pendiente_dpapi, clave_pendiente_dpapi=NULL, '
                                 'clave_pendiente_at=NULL, clave_rotada_at=? WHERE device_id=? AND clave_pendiente_dpapi=?',
                                 (ahora, device_id, f.pendiente))
                if f.confirmado_at is None:
                    conn.execute('UPDATE dispositivos SET confirmado_at=? WHERE device_id=? AND confirmado_at IS NULL',
                                 (ahora, device_id))
            if usada == 'pendiente':
                with self._candado:
                    self._kmac.pop((device_id, hashlib.sha256(f.clave).digest()), None)
                _log.info('Rotación de llave completada para un celular')
        self._anotar_acceso(device_id, ahora, ip, f.ultima_ip)
        rotada_at = ahora if usada == 'pendiente' else f.clave_rotada_at
        rotar = usada == 'vigente' and not pendiente_vigente and ahora - rotada_at >= ROTAR_CADA_S
        return Verificado(device_id, f.permisos, rotar)

    def rotar(self, device_id: str) -> Json:
        """POST /lan/v1/rotar (ya verificado) -> LanRotarResponse. La nueva queda pendiente; la vieja sigue valiendo."""
        f = self._leer(device_id)
        if f is None or f.revocado_at is not None:
            raise error_auth('dispositivo_revocado' if f else 'dispositivo_desconocido')
        nueva = secrets.token_bytes(32)
        blob = dpapi.proteger(nueva, _entropia(device_id))
        ahora = self.reloj.ahora()
        with self.almacen.escritor() as c:
            c.execute('UPDATE dispositivos SET clave_pendiente_dpapi=?, clave_pendiente_at=? WHERE device_id=? '
                      'AND revocado_at IS NULL', (blob, ahora, device_id))
        if f.pendiente:
            with self._candado:
                self._kmac.pop((device_id, hashlib.sha256(f.pendiente).digest()), None)
        return {'device_key': pl.b64u(nueva), 'vigente_desde': ahora, 'gracia_s': GRACIA_S}

    # -------------------------------------------------------------- accesos y mantenimiento
    def _anotar_acceso(self, device_id: str, ahora: int, ip: str, ip_guardada: str | None) -> None:
        with self._candado:
            previa = self._ip_conocida.get(device_id, ip_guardada)
            self._accesos[device_id] = (ahora, ip)
            self._ip_conocida[device_id] = ip
            cambio = previa != ip
        if cambio:
            self.volcar_accesos()

    def volcar_accesos(self) -> None:
        """Escribe en la base los accesos acumulados (cada 60 s desde hub.py y al cambiar la IP)."""
        with self._candado:
            if not self._accesos:
                return
            lote, self._accesos = self._accesos, {}
        try:
            with self.almacen.escritor() as c:
                c.executemany('UPDATE dispositivos SET ultimo_uso_at=MAX(COALESCE(ultimo_uso_at, 0), ?), ultima_ip=? '
                              'WHERE device_id=?', [(t, ip, d) for d, (t, ip) in lote.items()])
        except Exception:
            with self._candado:                       # se reintenta en el siguiente volcado
                for d, v in lote.items():
                    if d not in self._accesos:
                        self._accesos[d] = v
            raise

    def mantenimiento(self) -> int:
        """Borra los dispositivos sin confirmar tras 10 min y las llaves nuevas sin usar tras 7 días. -> borrados."""
        ahora = self.reloj.ahora()
        with self.almacen.escritor() as c:
            borrados = c.execute('DELETE FROM dispositivos WHERE confirmado_at IS NULL AND revocado_at IS NULL '
                                 'AND creado_at < ?', (ahora - CONFIRMAR_ANTES_S,)).rowcount
            c.execute('UPDATE dispositivos SET clave_pendiente_dpapi=NULL, clave_pendiente_at=NULL '
                      'WHERE clave_pendiente_at IS NOT NULL AND clave_pendiente_at < ?', (ahora - GRACIA_S,))
        if borrados:
            _log.info('Se quitaron %d celulares que nunca confirmaron el emparejamiento', borrados)
            vivos = {f.device_id for f in self._todas()}
            with self._candado:
                for k in [k for k in self._kmac if k[0] not in vivos]:
                    del self._kmac[k]
        return borrados
