"""Despachador de la API del hub (BUILD_SPEC §5, §6.2 `Despachador`; 03 §6.1–§6.2).

`crear_despachador(hub)` → `DespachadorHub`, que atiende TODAS las rutas de §5 para dos orígenes:
- la ventana local (`Contexto(origen='ui')`): el servidor de interfaz (api/servidor.py) ya comprobó Host, Origin,
  cookie, `X-CH-Hub` y tasa;
- los celulares emparejados (`Contexto(origen='lan', permisos=…)`): servidor_lan ya verificó TLS + CH1. Aquí se aplica
  la columna «LAN» de §5: ✓ = cualquier celular; ✓* = solo `lectura_escritura` (si no, `403 prohibido`); — = `403
  solo_local`. En las filas mixtas los GET son ✓ y las mutaciones ✓*.

Convenciones: éxito sin envoltorio; errores `ErrorRespuesta` (ErrorDominio.a_respuesta pasa por limpiar() y solo lleva
`vigente` con `codigo='conflicto'`); un 500 nunca trae texto de la excepción, solo `detalle.ref`. JSON UTF-8, gzip si
`Accept-Encoding: gzip` y el cuerpo pasa de 1 KB, `Cache-Control: no-store` salvo las lecturas compuestas, que llevan
`ETag: W/"dv<N>-lr<M>-ir<K>-<hash>"` (el hash cubre la ruta, la query ordenada, la fecha local de hoy, porque hay
campos como `dias_restantes` que cambian con el día, y `REV_LECTURAS`) y responden `304` a `If-None-Match`. En las
rutas `api/catalogo/*` el hash cubre además el instante de la última pasada de la Display API, una huella del visto_at
de los videos guardados (cambia también con las páginas de una pasada interrumpida) y las pasadas aún sin registrar,
leídos en la misma transacción que las versiones: de ellos dependen `publicacion`, `metricas_at` y
`display.ultima_sync_at`. La forma visible no cambia.
`GET /api/snapshot` lleva la forma `W/"dv<N>-lr<M>-ir<K>-f5-YYYY-MM-DD"`, con las versiones y fecha MX del propio cuerpo.
La ruta llega SIN decodificar: se parte en segmentos y cada segmento se decodifica por separado (nunca se normaliza la
ruta completa). Ya no existe `POST /local/activar` (C40).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import secrets
import urllib.parse
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Iterable, Literal, Mapping

from .. import comun, config
from ..errores import ErrorApi, ErrorDominio, ErrorRed
from ..interfaces import Contexto, Despachador, Json, RespuestaHttp
from . import archivos, seguridad

if TYPE_CHECKING:
    from ..tiktok.agenda_publicaciones import AgendaPublicaciones
    from ..tiktok.publicaciones import PublicacionesShop

_log = logging.getLogger('creatorhub.api.rutas')

TIPO_JSON = 'application/json; charset=utf-8'
GZIP_DESDE = 1024
MAX_CUERPO = config.MAX_CUERPO_BYTES
MAX_CAMPOS_QUERY = 64
REV_SNAPSHOT = 'f5'               # f3: actualidad de ventas/pagos · f4: origen de ventas histórico, sin aviso de permiso
#                                   · f5: origen_ventas_actual (trace_info de orders/search 202410).
REV_LECTURAS = 'r7'               # Entra en la ETag de cada lectura compuesta: subirlo renueva las copias de los clientes.
#                                   r7: la ficha de producto agrega origen_ventas_actual.
PREFIJO_CATALOGO = 'api/catalogo/'  # rev. 6: su ETag también cubre la última pasada de la Display API.
ModoLan = Literal['lectura', 'escritura', 'local']
TipoEtag = Literal['lectura', 'snapshot'] | None

MSG_NO_ENCONTRADO = 'No encontramos lo que buscas.'
MSG_METODO = 'Esa acción no existe para esta dirección.'
MSG_SOLO_LOCAL = 'Esto solo se puede hacer desde Corte en tu PC.'
MSG_SOLO_LECTURA = 'Este celular solo puede ver tus datos. Para hacer cambios, dale permiso desde Corte en tu PC.'
MSG_GRANDE = 'La petición es demasiado grande.'
MSG_JSON = 'La petición no es válida.'
MSG_CAMPOS = 'Los datos de la petición no son válidos.'
MSG_INTERNO = 'Algo salió mal en Corte. Inténtalo de nuevo.'
MSG_SIN_INTERNET = 'No pudimos hablar con TikTok. Revisa tu internet e inténtalo de nuevo.'
MSG_TIKTOK = 'TikTok no respondió. Inténtalo de nuevo en unos minutos.'
MSG_REAUTORIZAR = 'Tu conexión con TikTok venció. Vuelve a conectar desde Corte en tu PC.'
MSG_CONFIRMAR_BORRAR = 'Para borrar, escribe BORRAR.'
MSG_CONFIRMAR_LEGADO = 'Confirma que quieres mandar el archivo anterior a la Papelera.'


# ====================================================================== petición y ruta
@dataclass
class Peticion:
    metodo: str
    ruta: str                                   # cruda, sin query
    params: dict[str, str]
    query: dict[str, str]
    cabeceras: Mapping[str, str]
    cuerpo: bytes
    ctx: Contexto
    _json: Any = field(default=None, repr=False)
    _leido: bool = field(default=False, repr=False)

    def cabecera(self, nombre: str) -> str | None:
        v = self.cabeceras.get(nombre)
        if v is None:
            v = self.cabeceras.get(nombre.lower())
        if v is None:
            for k, val in self.cabeceras.items():
                if k.lower() == nombre.lower():
                    return val
        return v

    def json(self) -> Any:
        if not self._leido:
            self._leido = True
            if self.cuerpo.strip():
                try:
                    self._json = json.loads(self.cuerpo.decode('utf-8'))
                except (UnicodeDecodeError, ValueError):
                    raise ErrorDominio('parametros_invalidos', MSG_JSON, http=400) from None
        return self._json

    def objeto(self, permitidas: Iterable[str] | None = None) -> dict[str, Any]:
        """El cuerpo como objeto JSON ({} si viene vacío). Con `permitidas`, una clave de más → 422."""
        v = self.json()
        if v is None:
            v = {}
        if not isinstance(v, dict):
            raise ErrorDominio('parametros_invalidos', MSG_JSON, http=400)
        if permitidas is not None:
            de_mas = sorted(set(v) - set(permitidas))
            if de_mas:
                raise ErrorDominio('parametros_invalidos', MSG_CAMPOS, http=422, detalle={'campo': de_mas[0]})
        return v


@dataclass(frozen=True)
class Ruta:
    metodo: str
    plantilla: str                              # 'api/plan/{id}' (sin la barra inicial)
    fn: Callable[[Peticion], Any]
    lan: ModoLan
    etag: TipoEtag = None
    status: int = 200

    @property
    def partes(self) -> tuple[str, ...]:
        return tuple(self.plantilla.split('/'))


def entero(q: Mapping[str, str], clave: str, omision: int | None = None, minimo: int | None = None,
           maximo: int | None = None) -> int:
    """Entero de la query (400 parametros_invalidos si falta sin omisión, no es entero o se sale del rango)."""
    v = q.get(clave)
    if v is None or v == '':
        if omision is None:
            raise ErrorDominio('parametros_invalidos', MSG_CAMPOS, http=400, detalle={'parametro': clave})
        return omision
    if not (v.isascii() and (v.isdigit() or (v[:1] == '-' and v[1:].isdigit()))) or len(v) > 18:
        raise ErrorDominio('parametros_invalidos', MSG_CAMPOS, http=400, detalle={'parametro': clave})
    n = int(v)
    if (minimo is not None and n < minimo) or (maximo is not None and n > maximo):
        raise ErrorDominio('parametros_invalidos', MSG_CAMPOS, http=400, detalle={'parametro': clave})
    return n


def _segmentos(ruta: str) -> list[str] | None:
    """'/api/tiendas/value%20chic' → ['api', 'tiendas', 'value chic']; None si la ruta no sirve."""
    if not ruta.startswith('/') or '?' in ruta or '#' in ruta:
        return None
    crudos = ruta[1:].split('/')
    if not crudos or any(s == '' for s in crudos):
        return None
    out = []
    for s in crudos:
        try:
            d = urllib.parse.unquote(s, errors='strict')
        except UnicodeDecodeError:
            return None
        if not d or any(ord(c) < 32 or ord(c) == 127 for c in d):
            return None
        out.append(d)
    return out


def _consulta(consulta: str) -> dict[str, str]:
    if not consulta:
        return {}
    try:
        pares = urllib.parse.parse_qsl(consulta, keep_blank_values=True, strict_parsing=False, errors='strict',
                                       max_num_fields=MAX_CAMPOS_QUERY)
    except (ValueError, UnicodeDecodeError):
        raise ErrorDominio('parametros_invalidos', MSG_CAMPOS, http=400) from None
    q: dict[str, str] = {}
    for k, v in pares:
        if k in q:                               # sin parámetros repetidos: las listas van con comas
            raise ErrorDominio('parametros_invalidos', MSG_CAMPOS, http=400, detalle={'parametro': k})
        q[k] = v
    return q


def acepta_gzip(valor: str | None) -> bool:
    for parte in (valor or '').split(','):
        nombre, _, params = parte.strip().partition(';')
        if nombre.strip().lower() in ('gzip', '*'):
            q = params.strip().lower()
            return not (q.startswith('q=') and q[2:].strip() in ('0', '0.0', '0.00', '0.000'))
    return False


def _sin_debil(etiqueta: str) -> str:
    e = etiqueta.strip()
    return e[2:] if e.startswith('W/') else e


def coincide_etag(if_none_match: str | None, etiqueta: str) -> bool:
    if not if_none_match:
        return False
    objetivo = _sin_debil(etiqueta)
    return any(p.strip() == '*' or _sin_debil(p) == objetivo for p in if_none_match.split(','))


# ====================================================================== despachador
class DespachadorHub:
    """Implementa `Despachador`. `hub` es el objeto de hub.py (servicios + ajustes + coordinador)."""

    def __init__(self, hub: Any) -> None:
        self.hub = hub
        self.rutas: list[Ruta] = self._tabla()

    # -------------------------------------------------------------- Protocol
    def despachar(self, metodo: str, ruta: str, consulta: str, cabeceras: Mapping[str, str], cuerpo: bytes,
                  ctx: Contexto) -> RespuestaHttp:
        metodo = (metodo or '').upper()
        aceptar_gzip = False
        try:
            aceptar_gzip = acepta_gzip(_cabecera(cabeceras, 'accept-encoding'))
            segs = _segmentos(ruta)
            if segs is None or segs[0] not in ('api', 'img'):
                raise ErrorDominio('no_encontrado', MSG_NO_ENCONTRADO, http=404)
            definicion, params = self._buscar(metodo, segs)
            self._permiso(definicion, ctx)
            if len(cuerpo) > MAX_CUERPO:
                raise ErrorDominio('cuerpo_demasiado_grande', MSG_GRANDE, http=413)
            p = Peticion(metodo=metodo, ruta=ruta, params=params, query=_consulta(consulta), cabeceras=cabeceras,
                         cuerpo=cuerpo, ctx=ctx)
            if definicion.etag is not None:
                return self._lectura_compuesta(definicion, p, aceptar_gzip)
            return self._convertir(definicion.fn(p), definicion.status, aceptar_gzip)
        except ErrorDominio as e:
            return self._error(e)
        except ErrorApi as e:
            return self._error(self._de_error_api(e))
        except ErrorRed:
            return self._error(ErrorDominio('sin_internet', MSG_SIN_INTERNET, http=503, reintentar_en_s=30))
        except Exception:  # noqa: BLE001 - nunca texto de la excepción hacia afuera
            ref = secrets.token_hex(4)
            _log.exception('Error interno al atender %s %s (ref %s)', metodo, ruta.split('?', 1)[0][:200], ref)
            return self._error(ErrorDominio('error_interno', MSG_INTERNO, http=500, detalle={'ref': ref}))

    # -------------------------------------------------------------- enrutado
    def _buscar(self, metodo: str, segs: list[str]) -> tuple[Ruta, dict[str, str]]:
        metodos_de_la_ruta = False
        for r in self.rutas:
            partes = r.partes
            if len(partes) != len(segs):
                continue
            params: dict[str, str] = {}
            for patron, s in zip(partes, segs):
                if patron.startswith('{'):
                    params[patron[1:-1]] = s
                elif patron != s:
                    break
            else:
                if r.metodo == metodo:
                    return r, params
                metodos_de_la_ruta = True
        if metodos_de_la_ruta:
            raise ErrorDominio('no_encontrado', MSG_METODO, http=405)
        raise ErrorDominio('no_encontrado', MSG_NO_ENCONTRADO, http=404)

    @staticmethod
    def _permiso(r: Ruta, ctx: Contexto) -> None:
        if ctx.origen != 'lan':
            return
        if r.lan == 'local':
            raise ErrorDominio('solo_local', MSG_SOLO_LOCAL, http=403)
        if r.lan == 'escritura' and not ctx.puede_escribir:
            raise ErrorDominio('prohibido', MSG_SOLO_LECTURA, http=403)

    def rutas_definidas(self) -> list[tuple[str, str, str]]:
        """(método, '/plantilla', modo LAN) de cada ruta: para pruebas y documentación."""
        return [(r.metodo, '/' + r.plantilla, r.lan) for r in self.rutas]

    # -------------------------------------------------------------- respuestas
    def _vivos(self) -> tuple[str, ...]:
        try:
            todos = getattr(self.hub, 'secretos_vivos', None)        # rev. 5: + los de la Display API (hub.py)
            return tuple(todos() if callable(todos) else self.hub.boveda.secretos_vivos())
        except Exception:  # noqa: BLE001
            return ()

    @staticmethod
    def _cuerpo_json(obj: Any) -> bytes:
        return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')

    def _json(self, status: int, obj: Any, gz: bool, extra: Iterable[tuple[str, str]] = ()) -> RespuestaHttp:
        cuerpo = self._cuerpo_json(obj)
        extra = list(extra)
        cab = [('Content-Type', TIPO_JSON)]
        if not any(k.lower() == 'cache-control' for k, _ in extra):
            cab.append(('Cache-Control', 'no-store'))
        cab.extend(extra)
        if gz and len(cuerpo) > GZIP_DESDE:
            cuerpo = gzip.compress(cuerpo, compresslevel=6, mtime=0)
            cab += [('Content-Encoding', 'gzip'), ('Vary', 'Accept-Encoding')]
        return RespuestaHttp(status, cab, cuerpo)

    def _convertir(self, resultado: Any, status: int, gz: bool) -> RespuestaHttp:
        if isinstance(resultado, RespuestaHttp):
            return resultado
        if resultado is None:
            return RespuestaHttp(204, [('Cache-Control', 'no-store')])
        if isinstance(resultado, tuple) and len(resultado) == 2 and isinstance(resultado[0], int):
            status, resultado = resultado
        return self._json(status, resultado, gz)

    def _error(self, e: ErrorDominio) -> RespuestaHttp:
        cab = [('Content-Type', TIPO_JSON), ('Cache-Control', 'no-store')]
        if e.reintentar_en_s is not None:
            cab.append(('Retry-After', str(max(1, int(e.reintentar_en_s)))))
        return RespuestaHttp(int(e.http), cab, self._cuerpo_json(e.a_respuesta(self._vivos())))

    @staticmethod
    def _de_error_api(e: ErrorApi) -> ErrorDominio:
        if e.decision == 'reautorizar':
            return ErrorDominio('reautorizar', MSG_REAUTORIZAR, http=409)
        if e.codigo in (-1, 'sin_internet'):
            return ErrorDominio('sin_internet', MSG_SIN_INTERNET, http=503, reintentar_en_s=30)
        return ErrorDominio('tiktok_no_disponible', MSG_TIKTOK, http=503, reintentar_en_s=60)

    # -------------------------------------------------------------- lecturas compuestas: ETag y 304
    def _versiones_etag(self, r: Ruta | None = None) -> str | None:
        try:
            if r is not None and r.plantilla.startswith(PREFIJO_CATALOGO):
                v = self.hub.analitica.etag(con_display=True)
            else:
                v = self.hub.analitica.etag()
            return v if isinstance(v, str) and v else None
        except Exception:  # noqa: BLE001 - sin ETag, nunca sin respuesta
            _log.warning('No se pudo leer la versión para la ETag', exc_info=True)
            return None

    def _etiqueta(self, versiones: str, p: Peticion, tipo: TipoEtag, generado_at: int | None = None) -> str:
        versiones, _, marca = versiones.partition('|')   # marca: última pasada de la Display API (solo el catálogo)
        if tipo == 'snapshot':
            # Hoy/semana/próximo miércoles cambian aunque no haya ventas nuevas.
            # La etiqueta del cuerpo usa su propio instante al cruzar medianoche.
            dia = comun.fecha_local(self.hub.reloj.ahora() if generado_at is None else generado_at)
            return f'W/"{versiones}-{REV_SNAPSHOT}-{dia}"'
        canon = '&'.join(f'{k}={v}' for k, v in sorted(p.query.items()))
        hoy = comun.fecha_local(self.hub.reloj.ahora())
        base = f'{p.ruta}?{canon}|{hoy}|{REV_LECTURAS}' + (f'|{marca}' if marca else '')
        h = hashlib.sha256(base.encode('utf-8')).hexdigest()[:12]
        return f'W/"{versiones}-{h}"'

    def _lectura_compuesta(self, r: Ruta, p: Peticion, gz: bool) -> RespuestaHttp:
        antes = self._versiones_etag(r)
        etiqueta = self._etiqueta(antes, p, r.etag) if antes is not None else None
        if etiqueta is not None and coincide_etag(p.cabecera('if-none-match'), etiqueta):
            return RespuestaHttp(304, [('ETag', etiqueta), ('Cache-Control', 'private, no-cache')])
        datos = r.fn(p)
        extra: list[tuple[str, str]] = []
        if r.etag == 'snapshot' and isinstance(datos, dict) and all(
                isinstance(datos.get(k), int) for k in ('data_version', 'local_rev', 'img_rev')):
            propia = f"dv{datos['data_version']}-lr{datos['local_rev']}-ir{datos['img_rev']}"
            momento = datos.get('generado_at')
            extra = [('ETag', self._etiqueta(propia, p, 'snapshot', momento if isinstance(momento, int) else None)),
                     ('Cache-Control', 'private, no-cache')]
        elif (antes is not None and etiqueta is not None and self._versiones_etag(r) == antes
              and self._etiqueta(antes, p, r.etag) == etiqueta):
            # La etiqueta solo vale si ni las versiones ni el día cambiaron durante la lectura.
            extra = [('ETag', etiqueta), ('Cache-Control', 'private, no-cache')]
        return self._json(r.status, datos, gz, extra)

    # ================================================================== tabla de rutas (BUILD §5)
    def _tabla(self) -> list[Ruta]:
        L, E, X = 'lectura', 'escritura', 'local'
        h = self.hub
        a = lambda: h.analitica          # noqa: E731 - perezoso: los servicios se enlazan después (LAN)
        lo = lambda: h.local             # noqa: E731
        R = Ruta
        return [
            # ---------------------------------------------------------- salud, sesión, eventos, cambios
            R('GET', 'api/health', self._salud, L),
            R('GET', 'api/session', self._sesion, L),
            R('GET', 'api/events', self._eventos, X),
            R('GET', 'api/cambios', self._cambios, L),
            # ---------------------------------------------------------- sincronización
            R('POST', 'api/sync', self._sync_iniciar, E, status=202),
            R('GET', 'api/sync/estado', lambda p: h.sincronizador.estado(), L),
            R('GET', 'api/sync/historial', self._sync_historial, L),
            R('POST', 'api/sync/cancelar', self._sync_cancelar, X),
            R('GET', 'api/sync/cobertura', lambda p: h.sincronizador.cobertura(), L),
            # ---------------------------------------------------------- TikTok y credenciales (— por LAN, C35)
            R('POST', 'api/auth/link', self._auth_link, X),
            R('GET', 'api/auth/portapapeles', lambda p: h.auth.portapapeles(), X),
            R('POST', 'api/auth/canjear', self._auth_canjear, X),
            R('POST', 'api/auth/refrescar', lambda p: h.auth.refrescar(), X),
            R('POST', 'api/auth/desconectar', self._auth_desconectar, X),
            R('GET', 'api/credenciales/estado', lambda p: h.auth.credenciales_estado(), X),
            R('POST', 'api/credenciales/importar', self._credenciales_importar, X),
            R('PUT', 'api/credenciales/app-secret', self._app_secret, X),
            R('POST', 'api/credenciales/legado/borrar', self._legado_borrar, X),
            # ---------------------------------------------------------- analítica (lecturas compuestas)
            R('GET', 'api/dashboard', self._dashboard, L, 'lectura'),
            R('GET', 'api/muestras', lambda p: a().muestras(p.query), L, 'lectura'),
            R('GET', 'api/muestras/{application_id}', lambda p: a().muestra_detalle(p.params['application_id']),
              L, 'lectura'),
            R('GET', 'api/tiendas', lambda p: a().tiendas(p.query), L, 'lectura'),
            R('GET', 'api/tiendas/{tienda_key}', lambda p: a().tienda_detalle(p.params['tienda_key'], p.query),
              L, 'lectura'),
            R('GET', 'api/analitica/serie', lambda p: a().serie(p.query), L, 'lectura'),
            R('GET', 'api/analitica/videos', lambda p: a().videos(p.query), L, 'lectura'),
            R('GET', 'api/analitica/productos', lambda p: a().productos(p.query), L, 'lectura'),
            R('GET', 'api/videos/{content_id}', lambda p: a().video_detalle(p.params['content_id']), L, 'lectura'),
            # rev. 6: catálogo de videos publicados y con ventas (rutas nuevas: las de ventas no cambian)
            R('GET', 'api/catalogo/videos', lambda p: a().catalogo_videos(p.query), L, 'lectura'),
            R('GET', 'api/catalogo/videos/{content_id}', lambda p: a().video_catalogo(p.params['content_id']),
              L, 'lectura'),
            R('GET', 'api/catalogo/marketplace', self._marketplace_creator, X),
            R('GET', 'api/catalogo/vitrina', self._vitrina_creator, X),
            R('POST', 'api/catalogo/vitrina/agregar', lambda p: self._vitrina_creator(p, 'agregar'), X),
            R('POST', 'api/catalogo/vitrina/quitar', lambda p: self._vitrina_creator(p, 'quitar'), X),
            R('POST', 'api/catalogo/vitrina/fijar', lambda p: self._vitrina_creator(p, 'fijar'), X),
            R('POST', 'api/catalogo/enlaces-afiliado', self._enlaces_afiliado_creator, X),
            R('GET', 'api/publicaciones/shop/capacidades', lambda p: self._publicaciones_shop(p).capacidades(), X),
            R('POST', 'api/publicaciones/shop/preparar', lambda p: self._publicaciones_shop(p).preparar(p.objeto()), X),
            R('POST', 'api/publicaciones/shop/publicar', lambda p: self._publicaciones_shop(p).publicar(p.objeto()), X),
            R('GET', 'api/publicaciones/shop/agenda', lambda p: self._agenda_shop(p).listar(), X),
            R('POST', 'api/publicaciones/shop/agenda', lambda p: self._agenda_shop(p).programar(p.objeto()), X),
            R('POST', 'api/publicaciones/shop/agenda/{id}/cancelar',
              lambda p: self._agenda_shop(p).cancelar(p.params['id'], p.objeto()), X),
            R('GET', 'api/publicaciones/shop/{video_id}/estado',
              lambda p: self._publicaciones_shop(p).estado(p.params['video_id']), X),
            R('GET', 'api/productos/{product_id}', lambda p: a().producto_detalle(p.params['product_id']),
              L, 'lectura'),
            R('GET', 'api/productos/{product_id}/evidencia',
              lambda p: h.evidencia.leer(p.params['product_id']), L, 'lectura'),
            R('PUT', 'api/productos/{product_id}/evidencia',
              lambda p: h.evidencia.guardar(p.params['product_id'], p.objeto(), p.ctx), E),
            R('POST', 'api/productos/{product_id}/extraer',
              lambda p: h.evidencia.extraer(p.params['product_id'], p.objeto(), p.ctx), E),
            R('GET', 'api/productos/{product_id}/resenas',
              lambda p: h.evidencia.resenas(p.params['product_id'], p.query), L, 'lectura'),
            R('GET', 'api/ordenes', lambda p: a().ordenes(p.query), L, 'lectura'),
            R('GET', 'api/snapshot', self._snapshot, L, 'snapshot'),
            # ---------------------------------------------------------- estado local (✓ GET · ✓* mutaciones)
            R('GET', 'api/plan', lambda p: lo().plan_listar(p.query), L, 'lectura'),
            R('POST', 'api/plan', lambda p: lo().plan_crear(p.objeto(), p.ctx), E),
            R('PATCH', 'api/plan/{id}', lambda p: lo().plan_editar(p.params['id'], p.objeto(), p.ctx), E),
            R('DELETE', 'api/plan/{id}', lambda p: lo().plan_borrar(p.params['id'], entero(p.query, 'rev', minimo=0),
                                                                    p.ctx), E),
            R('GET', 'api/avisos', lambda p: lo().avisos_listar(p.query), L, 'lectura'),
            R('POST', 'api/avisos', lambda p: lo().aviso_crear(p.objeto(), p.ctx), E),
            R('PATCH', 'api/avisos/{id}', lambda p: lo().aviso_editar(p.params['id'], p.objeto(), p.ctx), E),
            R('GET', 'api/plantillas', lambda p: lo().plantillas_listar(), L, 'lectura'),
            R('PUT', 'api/plantillas/{id}', lambda p: lo().plantilla_editar(p.params['id'], p.objeto(), p.ctx), E),
            R('POST', 'api/plantillas/{id}/restaurar', lambda p: lo().plantilla_restaurar(p.params['id'], p.ctx), E),
            R('GET', 'api/preferencias', lambda p: lo().preferencias_leer(), L, 'lectura'),
            R('PATCH', 'api/preferencias', lambda p: lo().preferencias_editar(p.objeto(), p.ctx), E),
            R('GET', 'api/notas', lambda p: lo().notas_listar(p.query), L, 'lectura'),
            R('POST', 'api/notas', lambda p: lo().nota_crear(p.objeto(), p.ctx), E),
            R('PATCH', 'api/notas/{id}', lambda p: lo().nota_editar(p.params['id'], p.objeto(), p.ctx), E),
            R('DELETE', 'api/notas/{id}', lambda p: lo().nota_borrar(p.params['id'], entero(p.query, 'rev', minimo=0),
                                                                     p.ctx), E),
            R('GET', 'api/recordatorios', lambda p: lo().recordatorios_listar(p.query), L, 'lectura'),
            R('POST', 'api/recordatorios', lambda p: lo().recordatorio_crear(p.objeto(), p.ctx), E),
            R('PATCH', 'api/recordatorios/{id}', lambda p: lo().recordatorio_editar(p.params['id'], p.objeto(), p.ctx),
              E),
            R('DELETE', 'api/recordatorios/{id}',
              lambda p: lo().recordatorio_borrar(p.params['id'], entero(p.query, 'rev', minimo=0), p.ctx), E),
            R('POST', 'api/local/ops', self._ops, E),
            R('GET', 'api/local/exportar', lambda p: lo().exportar(), X),
            R('POST', 'api/local/importar', self._importar_local, X),
            # ---------------------------------------------------------- imágenes
            R('GET', 'img/{tipo}/{ref_id}', self._imagen, L),
            # ---------------------------------------------------------- sistema, datos y ajustes de la PC (— por LAN)
            R('POST', 'api/sistema/abrir', self._abrir, X),
            R('POST', 'api/datos/borrar', self._borrar_datos, X),
            R('GET', 'api/datos/uso', lambda p: h.uso_datos(), X),
            R('GET', 'api/ajustes/pc', lambda p: h.ajustes_pc(), X),
            R('PATCH', 'api/ajustes/pc', lambda p: h.cambiar_ajustes_pc(p.objeto()), X),
            # ---------------------------------------------------------- celulares (— por LAN)
            R('GET', 'api/lan/estado', lambda p: h.lan.estado(), X),
            R('PATCH', 'api/lan/estado', lambda p: h.lan.cambiar(p.objeto()), X),
            R('POST', 'api/lan/activar', self._lan_activar, X),
            R('POST', 'api/lan/emparejar', lambda p: h.lan.emparejar(), X),
            R('GET', 'api/lan/emparejar/{pair_id}', lambda p: h.lan.estado_emparejamiento(p.params['pair_id']), X),
            R('POST', 'api/lan/emparejar/{pair_id}/decision',
              lambda p: h.lan.decidir(p.params['pair_id'], p.objeto()), X),
            R('PATCH', 'api/lan/dispositivos/{device_id}',
              lambda p: h.lan.cambiar_dispositivo(p.params['device_id'], p.objeto()), X),
            R('DELETE', 'api/lan/dispositivos/{device_id}', lambda p: h.lan.revocar(p.params['device_id']), X),
            R('GET', 'api/lan/firewall', lambda p: h.lan.firewall_diagnostico(), X),
            R('POST', 'api/lan/firewall', lambda p: h.lan.firewall_configurar(p.objeto({'opcion'})), X),
        ]

    # ================================================================== manejadores
    def _salud(self, p: Peticion) -> Json:
        return self.hub.salud()

    def _sesion(self, p: Peticion) -> Json:
        return self.hub.sesion(p.ctx)

    @staticmethod
    def _eventos(p: Peticion) -> Json:
        # La ventana local la atiende el servidor (flujo SSE); aquí solo llegaría una petición que no es de la ventana.
        raise ErrorDominio('no_encontrado', MSG_NO_ENCONTRADO, http=404)

    def _cambios(self, p: Peticion) -> Any:
        q = p.query
        dv = entero(q, 'data_version', minimo=0)
        lr = entero(q, 'local_rev', minimo=0)
        ir = entero(q, 'img_rev', omision=-1, minimo=0)      # sin img_rev en la query: no se compara (C45)
        espera = min(entero(q, 'espera_s', omision=config.ESPERA_CAMBIOS_MAX_S, minimo=0), config.ESPERA_CAMBIOS_MAX_S)
        r = self.hub.bus.esperar_cambio((dv, lr, ir), float(espera))
        if r is None:
            return RespuestaHttp(204, [('Cache-Control', 'no-store')])
        en_curso = bool((self.hub.sincronizador.estado() or {}).get('en_curso'))
        return {'data_version': int(r['data_version']), 'local_rev': int(r['local_rev']),
                'img_rev': int(r.get('img_rev', 0)), 'secciones': list(r.get('secciones') or []),
                'sync_en_curso': en_curso}

    # -------------------------------------------------------------- sincronización
    def _sync_iniciar(self, p: Peticion) -> Json:
        b = p.objeto({'tipo'})
        tipo = b.get('tipo', 'incremental')
        if tipo not in ('incremental', 'completa'):
            raise ErrorDominio('parametros_invalidos', MSG_CAMPOS, http=422, detalle={'campo': 'tipo'})
        origen = 'telefono' if p.ctx.origen == 'lan' else 'usuario'
        return self.hub.sincronizador.iniciar(tipo, origen)

    def _sync_historial(self, p: Peticion) -> Json:
        return self.hub.sincronizador.historial(entero(p.query, 'limite', omision=20, minimo=1, maximo=200))

    def _sync_cancelar(self, p: Peticion) -> Json:
        self.hub.sincronizador.cancelar(10.0)
        return self.hub.sincronizador.estado()

    # -------------------------------------------------------------- TikTok y credenciales
    def _auth_link(self, p: Peticion) -> Json:
        b = p.objeto({'abrir_navegador'})
        abrir = b.get('abrir_navegador', False)
        if not isinstance(abrir, bool):
            raise ErrorDominio('parametros_invalidos', MSG_CAMPOS, http=422, detalle={'campo': 'abrir_navegador'})
        return self.hub.auth.link(abrir)

    def _auth_canjear(self, p: Peticion) -> Json:
        b = p.objeto({'url_o_codigo', 'desde_portapapeles', 'confirmar_cambio_cuenta'})
        r = self.hub.auth.canjear(b)
        self.hub.encolar_avatar()               # «¿Eres tú?»: la foto llega sin esperar a la sync (aviso de hub-nucleo)
        return r

    def _auth_desconectar(self, p: Peticion) -> Json:
        b = p.objeto({'borrar_datos'})
        borrar = b.get('borrar_datos', False)
        if not isinstance(borrar, bool):
            raise ErrorDominio('parametros_invalidos', MSG_CAMPOS, http=422, detalle={'campo': 'borrar_datos'})
        return self.hub.auth.desconectar(borrar)

    def _credenciales_importar(self, p: Peticion) -> Json:
        b = p.objeto({'ruta', 'verificar'})
        r = self.hub.auth.importar(b)
        if isinstance(r, dict) and r.get('verificacion') == 'ok':
            self.hub.sincronizar_tras_conectar()    # 03 §4.4/§8 paso 6: importación verificada → completa inmediata
        return r

    def _app_secret(self, p: Peticion) -> Json:
        b = p.objeto({'app_secret'})
        valor = b.get('app_secret')
        if not isinstance(valor, str):
            raise ErrorDominio('parametros_invalidos', MSG_CAMPOS, http=422, detalle={'campo': 'app_secret'})
        return self.hub.auth.guardar_app_secret(valor)

    def _legado_borrar(self, p: Peticion) -> Json:
        b = p.objeto({'confirmar'})
        if b.get('confirmar') is not True:
            raise ErrorDominio('parametros_invalidos', MSG_CONFIRMAR_LEGADO, http=422, detalle={'campo': 'confirmar'})
        return self.hub.auth.borrar_legado()

    # -------------------------------------------------------------- analítica
    def _dashboard(self, p: Peticion) -> Json:
        de_mas = sorted(set(p.query) - {'periodo'})
        if de_mas:
            raise ErrorDominio('parametros_invalidos', MSG_CAMPOS, http=400, detalle={'parametro': de_mas[0]})
        return self.hub.analitica.dashboard(p.query.get('periodo') or '30d')

    def _marketplace_creator(self, p: Peticion) -> Json:
        marketplace = getattr(self.hub, 'marketplace', None)
        if marketplace is None:
            raise ErrorDominio('no_encontrado', MSG_NO_ENCONTRADO, http=404)
        return marketplace.buscar(p.query)

    def _vitrina_creator(self, p: Peticion, accion: str | None = None) -> Json:
        vitrina = getattr(self.hub, 'showcase', None)
        if vitrina is None:
            raise ErrorDominio('no_encontrado', 'La vitrina Creator está disponible en Corte Nube.', http=404)
        if accion is None:
            return vitrina.listar(p.query)
        return vitrina.cambiar(accion, p.objeto({'product_ids'}))

    def _enlaces_afiliado_creator(self, p: Peticion) -> Json:
        enlaces = getattr(self.hub, 'affiliate_links', None)
        if enlaces is None:
            raise ErrorDominio('no_encontrado', 'Los enlaces de afiliado están disponibles en Corte Nube.', http=404)
        return enlaces.generar(p.objeto())

    def _publicaciones_shop(self, p: Peticion) -> PublicacionesShop:
        servicio = getattr(self.hub, 'publicaciones_shop', None)
        if servicio is None:
            raise ErrorDominio('no_encontrado', MSG_NO_ENCONTRADO, http=404)
        if p.query or (p.metodo == 'GET' and p.cuerpo):
            raise ErrorDominio('parametros_invalidos', MSG_CAMPOS, http=400)
        return servicio

    def _agenda_shop(self, p: Peticion) -> AgendaPublicaciones:
        servicio = getattr(self.hub, 'agenda_shop', None)
        if servicio is None:
            raise ErrorDominio('no_encontrado', MSG_NO_ENCONTRADO, http=404)
        if p.query or (p.metodo == 'GET' and p.cuerpo):
            raise ErrorDominio('parametros_invalidos', MSG_CAMPOS, http=400)
        return servicio

    def _snapshot(self, p: Peticion) -> Json:
        h = self.hub
        return h.analitica.snapshot(h.auth.cuenta(), h.auth.conexion(), h.sincronizador.estado())

    # -------------------------------------------------------------- estado local
    def _ops(self, p: Peticion) -> Json:
        b = p.objeto({'ops'})
        ops = b.get('ops')
        if not isinstance(ops, list):
            raise ErrorDominio('parametros_invalidos', MSG_CAMPOS, http=400, detalle={'campo': 'ops'})
        return self.hub.local.aplicar_ops(ops, p.ctx)

    def _importar_local(self, p: Peticion) -> Json:
        b = p.objeto({'ruta'})
        datos = archivos.leer_json_usuario(b.get('ruta'), archivos.MAX_PLAN_BYTES)
        return self.hub.local.importar(datos)

    # -------------------------------------------------------------- imágenes
    def _imagen(self, p: Peticion) -> RespuestaHttp:
        v, t = p.query.get('v'), p.query.get('t')
        r = self.hub.imagenes.servir(p.params['tipo'], p.params['ref_id'], v, t)
        cab = seguridad.sin_cors(r.cabeceras or [])
        if not any(k.lower() == 'cache-control' for k, _ in cab):
            cab.append(('Cache-Control', 'no-store'))
        if r.status == 200 and r.archivo:
            return RespuestaHttp(200, cab, b'', archivo=r.archivo)
        if r.status == 200:                     # 200 sin archivo: no se sirve nada a medias
            return RespuestaHttp(404, [('Cache-Control', 'no-store')])
        return RespuestaHttp(int(r.status), cab)

    # -------------------------------------------------------------- sistema, datos, ajustes, celulares
    def _abrir(self, p: Peticion) -> None:
        b = p.objeto({'url'})
        self.hub.abrir_enlace(seguridad.validar_url_abrir(b.get('url')))
        return None

    def _borrar_datos(self, p: Peticion) -> None:
        b = p.objeto({'alcance', 'confirmacion'})
        alcance = b.get('alcance')
        if alcance not in ('tiktok', 'todo', 'imagenes'):
            raise ErrorDominio('parametros_invalidos', MSG_CAMPOS, http=422, detalle={'campo': 'alcance'})
        if b.get('confirmacion') != 'BORRAR':
            raise ErrorDominio('parametros_invalidos', MSG_CONFIRMAR_BORRAR, http=422, detalle={'campo': 'confirmacion'})
        self.hub.borrar_datos(alcance)
        return None

    def _lan_activar(self, p: Peticion) -> Json:
        b = p.objeto({'activo'})
        activo = b.get('activo')
        if not isinstance(activo, bool):
            raise ErrorDominio('parametros_invalidos', MSG_CAMPOS, http=422, detalle={'campo': 'activo'})
        return self.hub.lan.activar(activo)


def _cabecera(cabeceras: Mapping[str, str], nombre: str) -> str | None:
    v = cabeceras.get(nombre)
    if v is not None:
        return v
    for k, val in cabeceras.items():
        if k.lower() == nombre:
            return val
    return None


def crear_despachador(hub: Any) -> Despachador:
    return DespachadorHub(hub)
