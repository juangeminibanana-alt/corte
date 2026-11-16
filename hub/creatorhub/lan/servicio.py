"""ServicioLan del hub (BUILD §6.2 `ServicioLan`, §6.3.1; contrato.ts LanResumen/LanEstado/EmparejarResponse/…).

Compone las piezas de `lan/`: identidad TLS (CNG), servidor HTTPS (`servidor_lan`), descubrimiento UDP, emparejamiento,
celulares (`dispositivos`), QR, direcciones y firewall. hub.py lo crea con `lan.crear_servicio_lan(dep)`, le fija el
Despachador (`fijar_despachador`, enlace tardío) y después llama `iniciar_si_activo()` en segundo plano.

- El listener solo existe con «Permitir que mis celulares se conecten» encendido (`config.json` → `lan.activo`) y solo
  en modo `real` (demo y autoprueba van sin LAN).
- Alias de la PC (`lan.nombre_equipo` en config.json; por omisión 'PC ' + host_id[0:4] en mayúsculas): el MISMO en
  hello, UDP, LanPaquete y LanEstado (C38).
- Puertos: 39230 o el siguiente libre de 39232–39239 (TCP) · 39231 (UDP) · SO_EXCLUSIVEADDRUSE en los dos (C8).
- `host_id` vive en `meta` (lo siembra el almacén; si falta, se crea aquí). «Desvincular todos» lo regenera.
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
from typing import Any, Callable, Mapping

from .. import config
from ..errores import ErrorDominio
from ..interfaces import Contexto, Dependencias, Despachador, Json, RespuestaHttp
from . import identidad_tls, protocolo_lan as pl, qr, red
from .descubrimiento import RespondedorUdp
from .dispositivos import RegistroDispositivos, Verificado
from .emparejamiento import ESPERA_LARGA_S, GestorEmparejamiento, Sesion
from .firewall_diag import Diagnostico, diagnosticar, evaluar, perfiles_para
from .servidor_lan import TIMEOUT_HANDSHAKE_S, ServidorLan

_log = logging.getLogger('creatorhub.lan')

DIAG_VIGENTE_S = 120.0
VOLCADO_CADA_S = 60.0
MANTENIMIENTO_REGISTRO_S = 30.0


def _configurar_firewall_real(perfiles: tuple[str, ...], indice: int | None, red_privada: bool) -> int:
    from . import firewall
    return firewall.configurar(perfiles=perfiles, indice=indice, red_privada=red_privada)


class ServicioLanHub:
    """Implementa `interfaces.ServicioLan` y `servidor_lan.NucleoLan`.

    Los argumentos con nombre existen para las pruebas (loopback, puertos efímeros, firewall simulado); la fábrica
    `crear_servicio_lan(dep)` usa los valores de producción."""

    def __init__(self, dep: Dependencias, *, permitir_loopback: bool = False, ip_escucha: str = '0.0.0.0',
                 puertos: tuple[int, ...] | None = None, puerto_udp: int | None = None,
                 direcciones: Callable[[], list[str]] | None = None, diagnostico: Callable[[], Diagnostico] | None = None,
                 configurar_firewall: Callable[[tuple[str, ...], int | None, bool], int] | None = None,
                 espera_larga_s: float = ESPERA_LARGA_S, timeout_handshake_s: float = TIMEOUT_HANDSHAKE_S,
                 mantenimiento_s: float = 5.0) -> None:
        self.dep = dep
        self.reloj = dep.reloj
        self.almacen = dep.almacen
        self.config = dep.config
        self.bus = dep.bus
        self.rutas = dep.rutas
        self._permitir_loopback = permitir_loopback
        self._ip = ip_escucha
        self._puertos = tuple(puertos) if puertos is not None else (config.PUERTO_LAN,) + config.PUERTOS_LAN_RESPALDO
        self._puerto_udp = config.PUERTO_UDP if puerto_udp is None else puerto_udp
        self._fuente_direcciones = direcciones or red.direcciones_privadas
        self._fuente_diagnostico = diagnostico or diagnosticar
        self._configurar_fw = configurar_firewall or _configurar_firewall_real
        self._timeout_hs = timeout_handshake_s
        self._mant_s = mantenimiento_s
        self.registro = RegistroDispositivos(self.almacen, self.reloj)
        self.gestor = GestorEmparejamiento(self.reloj, self._publicar, espera_larga_s)
        self._candado = threading.RLock()
        self._despachador: Despachador | None = None
        self.servidor: ServidorLan | None = None
        self.udp: RespondedorUdp | None = None
        self._huella: str | None = None
        self._host_id: str | None = None
        self._diag: Diagnostico | None = None
        self._diag_at = 0.0
        self._hilo_diag: threading.Thread | None = None
        self._fin_mant = threading.Event()
        self._hilo_mant: threading.Thread | None = None
        self._ultimo_volcado = time.monotonic()

    # ================================================================== datos básicos
    def _publicar(self, evento: Json) -> None:
        self.bus.publicar(evento)

    def _cfg_lan(self) -> dict[str, Any]:
        v = self.config.leer('lan', {})
        return dict(v) if isinstance(v, Mapping) else {}

    def _activo(self) -> bool:
        return self.dep.modo == 'real' and bool(self._cfg_lan().get('activo'))

    def host_id(self) -> str:
        with self._candado:
            if self._host_id is None:
                self._host_id = self._leer_o_crear_host_id()
            return self._host_id

    def _leer_o_crear_host_id(self) -> str:
        with self.almacen.lector() as c:
            r = c.execute("SELECT valor FROM meta WHERE clave='host_id'").fetchone()
        if r is not None and pl.es_host_id(r[0]):
            return str(r[0])
        nuevo = pl.nuevo_host_id()
        self._guardar_host_id(nuevo)
        return nuevo

    def _guardar_host_id(self, host_id: str) -> None:
        with self.almacen.escritor() as c:
            c.execute("INSERT INTO meta(clave, valor) VALUES ('host_id', ?) "
                      "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor", (host_id,))

    def alias(self) -> str:
        n = self._cfg_lan().get('nombre_equipo')
        try:
            return pl.validar_alias(n) if n is not None else pl.alias_por_omision(self.host_id())
        except ValueError:
            return pl.alias_por_omision(self.host_id())

    def puerto(self) -> int | None:
        s = self.servidor
        return s.puerto if s is not None else None

    def huella(self) -> str:
        return self._huella or identidad_tls.huella_guardada(self.rutas) or ''

    def _direcciones(self) -> list[str]:
        try:
            return [ip for ip in self._fuente_direcciones() if red.ip_privada(ip)]
        except Exception:  # noqa: BLE001 - sin direcciones no se cae la pantalla
            _log.exception('No se pudieron leer las direcciones de red')
            return []

    # ================================================================== ServicioLan
    def fijar_despachador(self, d: Despachador) -> None:
        self._despachador = d

    def iniciar_si_activo(self) -> None:
        if not self._activo():
            return
        try:
            self._arrancar()
            self._diagnosticar_en_fondo()
        except Exception:  # noqa: BLE001 - la LAN nunca tumba al hub
            _log.exception('No se pudo iniciar la conexión con el celular')

    def detener(self) -> None:
        self._parar()

    def resumen(self) -> Json:
        return {'activo': self._activo(), 'dispositivos_activos': self.registro.activos(), 'puerto': self.puerto()}

    def estado(self) -> Json:
        activo = self._activo()
        diag = self._diag
        return {'activo': activo, 'puerto': self.puerto(), 'direcciones': self._direcciones(),
                'host_id': self.host_id(), 'nombre_equipo': self.alias(), 'huella_tls': self.huella(),
                'dispositivos': self.registro.listar(),
                'aviso_firewall': diag.mensaje if (activo and diag is not None) else None}

    def activar(self, activo: bool) -> Json:
        if not isinstance(activo, bool):
            raise ErrorDominio('parametros_invalidos', 'El valor de «activo» no es válido.', http=422)
        if activo:
            if self.dep.modo != 'real':
                raise ErrorDominio('prohibido', 'En el modo de demostración no se pueden conectar celulares.', http=403)
            self._arrancar()
            self.config.escribir({'lan': {'activo': True}})
            self._diagnosticar_en_fondo()
        else:
            self.config.escribir({'lan': {'activo': False}})
            self._parar()
        return self.estado()

    def cambiar(self, cambios: Json) -> Json:
        if not isinstance(cambios, Mapping) or set(cambios) - {'nombre_equipo'}:
            raise ErrorDominio('parametros_invalidos', 'Solo se puede cambiar el nombre de la PC.', http=422)
        if 'nombre_equipo' in cambios:
            try:
                nombre = pl.validar_alias(cambios['nombre_equipo'])
            except ValueError:
                raise ErrorDominio('parametros_invalidos', 'El nombre de la PC debe tener de 1 a 40 caracteres, sin '
                                                           'saltos de línea.', http=422) from None
            self.config.escribir({'lan': {'nombre_equipo': nombre}})
        return self.estado()

    def emparejar(self) -> Json:
        puerto, huella = self.puerto(), self._huella
        if puerto is None or not huella:
            raise ErrorDominio('prohibido', 'Activa «Permitir que mis celulares se conecten» para emparejar tu '
                                            'celular.', http=409)
        host_id = self.host_id()
        s = self.gestor.crear(host_id)
        direcciones = self._direcciones()
        texto = pl.qr_texto(host_id, direcciones, puerto, s.codigo, huella)
        return {'pair_id': s.pair_id, 'qr_texto': texto, 'qr_png': qr.data_uri(texto),
                'codigo_manual': pl.formatear_codigo(s.codigo), 'expira_at': s.expira_at, 'direcciones': direcciones}

    def estado_emparejamiento(self, pair_id: str) -> Json:
        return self.gestor.estado(pair_id)

    def decidir(self, pair_id: str, decision: Json) -> Json:
        return self.gestor.decidir(pair_id, decision, self._crear_paquete)

    def _crear_paquete(self, s: Sesion, permisos: str) -> str:
        if s.nonce_c is None or s.nonce_s is None or not self._huella:
            raise ErrorDominio('conflicto', 'Esa solicitud ya no espera tu respuesta.', http=409)
        device_id, device_key = self.registro.crear(s.nombre or 'Celular', permisos)
        claro = pl.paquete_claro(device_id, device_key, s.host_id, self.alias(), self.puerto() or 0, permisos,
                                 self._huella)
        return pl.sellar(pl.k_enc(s.k_pair, s.nonce_c, s.nonce_s), secrets.token_bytes(12), claro, s.pair_id)

    def cambiar_dispositivo(self, device_id: str, cambios: Json) -> Json:
        return self.registro.cambiar(device_id, cambios)

    def revocar(self, device_id: str) -> None:
        self.registro.revocar(device_id)

    def revocar_todos(self) -> None:
        """«Desvincular todos»: revoca todos los celulares, cierra emparejamientos y regenera host_id (03 §7.4)."""
        self.gestor.cancelar_todo()
        self.registro.revocar_todos()
        nuevo = pl.nuevo_host_id()
        self._guardar_host_id(nuevo)
        with self._candado:
            self._host_id = nuevo

    def firewall_diagnostico(self) -> Json:
        return self._diagnosticar().contrato()

    def firewall_configurar(self, req: Json) -> Json:
        opcion = req.get('opcion') if isinstance(req, Mapping) else None
        if opcion not in ('privada', 'publica_subred', 'arreglar'):
            raise ErrorDominio('parametros_invalidos', 'Elige una opción.', http=422)
        diag = self._diag if (self._diag is not None and time.monotonic() - self._diag_at < DIAG_VIGENTE_S) \
            else self._diagnosticar()
        perfiles, red_privada = perfiles_para(opcion, diag)
        if red_privada and diag.indice is None:
            _log.warning('No se conoce el índice de la red: no se puede marcar como privada')
            codigo = -1
        else:
            try:
                codigo = self._configurar_fw(perfiles, diag.indice if red_privada else None, red_privada)
            except (OSError, ValueError) as e:
                _log.warning('No se pudo configurar el firewall (%s)', type(e).__name__)
                codigo = -1
        nuevo = self._diagnosticar()                 # 04 §C.10 paso 4: «Listo» solo si la regla cubre la red actual
        if codigo == 1223:
            resultado = 'cancelado'
        elif codigo == 0 and nuevo.estado == 'bien':
            resultado = 'listo'
        else:
            resultado = 'fallo'
        return {'resultado': resultado, 'diagnostico': nuevo.contrato()}

    def volcar_accesos(self) -> None:
        self._ultimo_volcado = time.monotonic()
        self.registro.volcar_accesos()

    # ================================================================== NucleoLan (lo llama servidor_lan)
    def hello(self) -> Json:
        return {'app': pl.APP, 'protocolo': pl.PROTOCOLO, 'host_id': self.host_id(), 'nombre_equipo': self.alias(),
                'version': config.VERSION, 'auth': pl.ESQUEMA_AUTH, 'hora_servidor': self.reloj.ahora(),
                'huella_tls': self.huella()}

    def pair_start(self, req: Any) -> Json:
        return self.gestor.iniciar(req, self.huella())

    def pair_poll(self, pair_id: str, nonce_c: str | None) -> Json:
        return self.gestor.sondear(pair_id, nonce_c)

    def verificar(self, cabecera: str | None, metodo: str, ruta_query: str, cuerpo: bytes, ip: str) -> Verificado:
        return self.registro.verificar(cabecera, metodo, ruta_query, cuerpo, ip)

    def rotar(self, device_id: str) -> Json:
        return self.registro.rotar(device_id)

    def despachar(self, metodo: str, ruta_lan: str, consulta: str, cabeceras: Mapping[str, str], cuerpo: bytes,
                  v: Verificado) -> RespuestaHttp:
        d = self._despachador
        if d is None:
            raise ErrorDominio('error_interno', 'Tu PC todavía está arrancando. Inténtalo en unos segundos.', http=503,
                               reintentar_en_s=5)
        ruta = ruta_lan[len('/lan/v1'):]             # '/api/…' o '/img/…', tal como llegó (sin decodificar)
        ctx = Contexto(origen='lan', plataforma='android', device_id=v.device_id, permisos=v.permisos)  # type: ignore[arg-type]
        return d.despachar(metodo, ruta, consulta, cabeceras, cuerpo, ctx)

    # ================================================================== arranque y parada
    def _identidad_udp(self) -> tuple[str, str, int, str]:
        return self.host_id(), self.alias(), self.puerto() or 0, self.huella()

    def _arrancar(self) -> None:
        with self._candado:
            if self.servidor is not None:
                return
            ctx, huella = identidad_tls.contexto(self.rutas)
            servidor: ServidorLan | None = None
            for p in self._puertos:
                try:
                    servidor = ServidorLan((self._ip, p), ctx, self, self._permitir_loopback, self._timeout_hs)
                    break
                except OSError as e:                  # 10048/10013 con SO_EXCLUSIVEADDRUSE: el siguiente
                    _log.info('Puerto %d ocupado (%s)', p, type(e).__name__)
            if servidor is None:
                raise ErrorDominio('error_interno', 'No pudimos abrir la conexión para tu celular: los puertos 39230 a '
                                                    '39239 están ocupados. Cierra el programa que los usa e inténtalo '
                                                    'de nuevo.', http=503)
            self._huella = huella
            self.host_id()
            self.gestor.abrir()
            servidor.servir_en_hilo()
            self.servidor = servidor
            try:
                udp = RespondedorUdp(self._ip, self._puerto_udp, self._identidad_udp, self._permitir_loopback)
                udp.iniciar()
                self.udp = udp
            except OSError as e:
                _log.warning('Sin descubrimiento UDP (puerto %d: %s); el QR sigue funcionando', self._puerto_udp,
                             type(e).__name__)
                self.udp = None
            self._fin_mant.clear()
            self._hilo_mant = threading.Thread(target=self._mantener, name='lan-mantenimiento', daemon=True)
            self._hilo_mant.start()
            _log.info('Conexión con el celular activa en el puerto %d', servidor.puerto)

    def _parar(self) -> None:
        with self._candado:
            servidor, udp, hilo = self.servidor, self.udp, self._hilo_mant
            self.servidor = self.udp = self._hilo_mant = None
            self._fin_mant.set()
        self.gestor.cancelar_todo()
        self.gestor.cerrar()
        if servidor is not None:
            servidor.cerrar()
        if udp is not None:
            udp.cerrar()
        if hilo is not None:
            hilo.join(3.0)
        diag = self._hilo_diag
        if diag is not None and diag.is_alive():
            diag.join(0.5)
        try:
            self.volcar_accesos()
        except Exception:  # noqa: BLE001
            _log.exception('No se pudieron volcar los accesos de los celulares')
        if servidor is not None:
            _log.info('Conexión con el celular detenida')

    def _mantener(self) -> None:
        ultimo_registro = 0.0
        while not self._fin_mant.wait(self._mant_s):
            try:
                self.gestor.revisar_vencidos()
                ahora = time.monotonic()
                if ahora - ultimo_registro >= MANTENIMIENTO_REGISTRO_S:
                    self.registro.mantenimiento()
                    ultimo_registro = ahora
                if ahora - self._ultimo_volcado >= VOLCADO_CADA_S:
                    self.volcar_accesos()
            except Exception:  # noqa: BLE001
                _log.exception('Error en el mantenimiento de la LAN')

    # ================================================================== firewall
    def _diagnosticar(self) -> Diagnostico:
        try:
            d = self._fuente_diagnostico()
        except Exception:  # noqa: BLE001
            _log.exception('El diagnóstico del firewall falló')
            d = evaluar([], [], None)
        self._diag, self._diag_at = d, time.monotonic()
        return d

    def _diagnosticar_en_fondo(self) -> None:
        if self._hilo_diag is not None and self._hilo_diag.is_alive():
            return
        self._hilo_diag = threading.Thread(target=self._diagnosticar, name='lan-firewall', daemon=True)
        self._hilo_diag.start()
