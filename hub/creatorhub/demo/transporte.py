"""Transportes del modo demo (BUILD_SPEC §6.3.1 punto 5, §6.3.4; 03 §9.2). Nunca salen a la red.

- `TransporteApiFalsa`: responde como la API de creador de TikTok Shop a partir de un `DatosApi` en memoria (lo usan los
  datos sintéticos, que son lo único que viaja dentro del exe). Reproduce el contrato que el sincronizador necesita:
  `application_statuses`/`fulfillment_statuses` obligatorios, filtros comodín que devuelven todo, paginación con
  `page_token` que «da la vuelta», `expiration_time` = hora de la consulta en cumplimientos cerrados, `single_query` que
  falla si `application_type` no corresponde, máx. 20 `product_ids`, pedidos paginados por LÍNEA (un pedido puede
  partirse entre páginas) con `total_count` = líneas y montos como texto «$1,234.50», y renovación de la conexión.
  No verifica firmas: en demo las credenciales son ficticias.
  Rev. 4 (ficha completa de producto), con el MISMO formato que la API real: samples/labels (`label` con
  sample_sku_list), target_collaborations/search (exige `shop_id`, paginado), open_collaborations/products/search
  (`title_keywords` como lista o texto) y orders/trace/search (ms; con `trazas_sin_permiso` responde 105005 como hoy la
  cuenta real). single_query trae además `sample_product` y `status`.
- `TransporteFixtures` (solo desarrollo): envuelve `spec/verificacion/fixtures_api.FakeTikTok` sobre
  research/datos-reales. Vuelve a firmar cada petición con el secreto de prueba del falso y le pone su access token,
  así cualquier bóveda de demo funciona; el perfil sale con la identidad de demostración (`creador_demo`), nunca la real.
"""
from __future__ import annotations

import collections
import json
import os
import sys
import threading
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..comun import norm_estado
from ..errores import ErrorRed, ErrorTimeoutLectura
from ..interfaces import Json, Reloj

HOST_API = 'open-api.tiktokglobalshop.com'
HOST_AUTH = 'auth.tiktok-shops.com'
P_PERFIL = '/affiliate_creator/202508/profiles'
P_MUESTRAS = '/affiliate_creator/202412/sample_applications/search'
P_DETALLE = '/affiliate_creator/202412/sample_applications/single_query'
P_CUMPL = '/affiliate_creator/202409/sample_applications/fulfillments/search'
P_PRODUCTOS = '/affiliate_creator/202509/open_collaborations/products'
P_ORDENES = '/affiliate_creator/202410/orders/search'
P_VITRINA = '/affiliate_creator/202405/showcases/products'
P_ETIQUETAS = '/affiliate_creator/202412/samples/labels'
P_DIRIGIDAS = '/affiliate_creator/202405/target_collaborations/search'
P_MARKETPLACE = '/affiliate_creator/202405/open_collaborations/products/search'
P_TRAZAS = '/affiliate_creator/202505/orders/trace/search'
P_REFRESH = '/api/v2/token/refresh'
CON_FECHA_LIMITE = ('PENDING', 'ONGOING')
CODIGO_SIN_PERMISO = 105005

USUARIO_DEMO = 'creador_demo'
OPEN_ID_DEMO = 'OPEN_ID_DEMO'
# Imagen del avatar de demostración: host con sufijo de la lista blanca del CDN, pero NUNCA se descarga de la red (el
# modo demo usa crear_descargador_demo, que la dibuja o la lee de ui/fixtures/img/a/cuenta).
URL_AVATAR_DEMO = 'https://p16-corte-demo.ibyteimg.com/obj/corte-demo/a/cuenta.png'
SCOPES_DEMO = ['creator.affiliate.info', 'creator.affiliate_collaboration.read', 'creator.showcase.read']

RAIZ_PROYECTO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
DIR_VERIFICACION = os.path.join(RAIZ_PROYECTO, 'spec', 'verificacion')
DIR_DATOS_REALES = os.path.join(RAIZ_PROYECTO, 'research', 'datos-reales')


def perfil_demo(perfil: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """`data` del GET de perfil con la identidad de demostración (conserva regiones, tipo y permisos si vienen)."""
    base = dict(perfil or {'selection_region': 'MX', 'register_region': 'MX', 'user_type': 1, 'seller_type': 'UNKNOWN',
                           'permissions': ['ADD_AFFILIATE_PERMISSION', 'LIVE_STREAM_PERMISSION']})
    base.update(username=USUARIO_DEMO, creator_user_open_id=OPEN_ID_DEMO, avatar={'url': URL_AVATAR_DEMO})
    return base


def _ok(data: Json) -> tuple[int, Json]:
    return 200, {'code': 0, 'message': 'Success', 'request_id': 'DEMO', 'data': data}


def _err(code: int, mensaje: str, http: int = 200) -> tuple[int, Json]:
    return http, {'code': code, 'message': mensaje, 'request_id': 'DEMO'}


def _consulta(url: str) -> tuple[urllib.parse.SplitResult, dict[str, str]]:
    u = urllib.parse.urlsplit(url)
    return u, {k: v[0] for k, v in urllib.parse.parse_qs(u.query, keep_blank_values=True).items()}


@dataclass
class DatosApi:
    """Respuestas crudas con la forma de la API. `busqueda[filtro]` = filas de sample_applications/search; un filtro de
    `comodines` devuelve TODAS las solicitudes (como en la cuenta real)."""
    perfil: dict[str, Any]
    solicitudes: list[dict[str, Any]]
    filtros: dict[str, list[str]]                       # application_id -> filtros específicos donde aparece
    comodines: frozenset[str]
    envios: list[dict[str, Any]]
    detalle: dict[str, dict[str, Any]]                  # application_id -> {create_time, type, main_order_id}
    productos: dict[str, dict[str, Any]]                # open_collaborations/products por id
    ordenes: list[dict[str, Any]]
    vitrina: list[dict[str, Any]]
    ahora: int = 0
    llamadas: collections.Counter = field(default_factory=collections.Counter)
    # rev. 4 (ficha completa de producto)
    etiquetas: dict[str, dict[str, Any]] = field(default_factory=dict)        # product_id -> label de samples/labels
    dirigidas: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # shop_id -> target_collaborations
    trazas: dict[str, list[str | None]] = field(default_factory=dict)         # order_id -> trace.type por SKU
    trazas_sin_permiso: bool = False                                          # True: orders/trace/search -> 105005


class TransporteApiFalsa:
    """Implementa `Transporte` sobre un DatosApi (sin red, sin firmas)."""

    def __init__(self, datos: DatosApi, reloj: Reloj | None = None) -> None:
        self.datos = datos
        self.reloj = reloj
        self.access_token = 'demo-access'
        self.refresh_token = 'demo-refresh'
        self.refrescos = 0
        self._candado = threading.Lock()
        self._por_filtro: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
        for s in datos.solicitudes:
            for f in datos.filtros.get(s['id'], []):
                self._por_filtro[f].append(s)
        self._envio_por_app = {e['application_id']: e for e in datos.envios}

    def _ahora(self) -> int:
        return self.reloj.ahora() if self.reloj is not None else self.datos.ahora

    def manejar(self, metodo: str, url: str, cabeceras: Mapping[str, str], cuerpo: bytes | None) -> tuple[int, Json | None]:
        u, q = _consulta(url)
        with self._candado:
            self.datos.llamadas[u.path] += 1
        if u.hostname == HOST_AUTH:
            return self._refrescar(u.path, q)
        if u.hostname != HOST_API:
            return _err(-10404, 'host desconocido (demo)', http=404)
        try:
            body = json.loads(cuerpo.decode('utf-8')) if cuerpo else {}
        except ValueError:
            return _err(-10001, 'cuerpo inválido (demo)', http=400)
        rutas = {P_PERFIL: lambda: _ok(dict(self.datos.perfil)), P_MUESTRAS: lambda: self._muestras(q, body),
                 P_CUMPL: lambda: self._cumplimientos(body), P_DETALLE: lambda: self._detalle(body),
                 P_PRODUCTOS: lambda: self._productos(q), P_ORDENES: lambda: self._ordenes(q, body),
                 P_VITRINA: lambda: self._vitrina(q), P_ETIQUETAS: lambda: self._etiquetas(q),
                 P_DIRIGIDAS: lambda: self._dirigidas(q, body), P_MARKETPLACE: lambda: self._marketplace(q, body),
                 P_TRAZAS: lambda: self._trazas(q, body)}
        manejador = rutas.get(u.path)
        if manejador is None:
            return _err(-10404, 'ruta desconocida (demo)', http=404)
        return manejador()

    # ------------------------------------------------------------------ auth
    def _refrescar(self, path: str, q: Mapping[str, str]) -> tuple[int, Json]:
        if path != P_REFRESH or q.get('grant_type') != 'refresh_token' or not q.get('refresh_token'):
            return _err(105001, 'refresh token invalid (demo)')
        with self._candado:
            self.refrescos += 1
            self.access_token = f'demo-access-{self.refrescos}'
        ahora = self._ahora()
        return _ok({'access_token': self.access_token, 'access_token_expire_in': ahora + 7 * 86400,
                    'refresh_token': self.refresh_token, 'refresh_token_expire_in': ahora + 300 * 86400,
                    'open_id': OPEN_ID_DEMO, 'seller_name': '', 'user_type': 1, 'granted_scopes': list(SCOPES_DEMO)})

    # ------------------------------------------------------------------ endpoints
    def _muestras(self, q: Mapping[str, str], body: Json) -> tuple[int, Json]:
        sts = body.get('application_statuses')
        if not sts:
            return _err(-10001, 'application_statuses es obligatorio (demo)')
        size = int(q.get('page_size') or 20)
        if not 0 < size <= 50:
            return _err(-10003, 'page_size inválido (demo)')
        filas: list[dict[str, Any]] = []
        for s in sts:
            s = norm_estado(s) or ''
            filas += self.datos.solicitudes if s in self.datos.comodines else self._por_filtro.get(s, [])
        unicos = list(collections.OrderedDict((f['id'], f) for f in filas).values())
        ini = int(q.get('page_token') or 0)
        pagina = unicos[ini:ini + size]
        sig = str(ini + size) if ini + size < len(unicos) else ('0' if unicos else '')   # «da la vuelta» al final
        return _ok({'sample_applications': [dict(f) for f in pagina], 'next_page_token': sig})

    def _cumplimientos(self, body: Json) -> tuple[int, Json]:
        sts = body.get('fulfillment_statuses')
        if not sts:
            return _err(-10001, 'fulfillment_statuses es obligatorio (demo)')
        ahora = self._ahora()
        out = []
        for e in self.datos.envios:
            if e['status'] in sts:
                g = dict(e)
                if g['status'] not in CON_FECHA_LIMITE:
                    g['expiration_time'] = ahora        # como la API real: en cerrados es la hora de la consulta
                out.append(g)
        return _ok({'fulfillments': out})

    def _detalle(self, body: Json) -> tuple[int, Json]:
        aid, tipo = body.get('application_id'), body.get('application_type')
        if not body.get('product_id') or not tipo:
            return _err(-10001, 'product_id y application_type son obligatorios (demo)')
        d = self.datos.detalle.get(aid)
        if d is None:
            return _err(-10404, 'solicitud desconocida (demo)')
        real = d.get('type', 'FREE_SAMPLE')
        if tipo != real or (tipo != 'FREE_SAMPLE' and not body.get('main_order_id')):
            return _err(36009003, 'Internal error. Please try again.')
        sa = {'id': aid, 'create_time': d.get('create_time') or 0, 'type': real, 'main_order_id': d.get('main_order_id')}
        if d.get('sample_product'):                         # como la API real: SKU y variante de la solicitud
            sa['sample_product'] = dict(d['sample_product'])
        if d.get('status'):
            sa['status'] = d['status']
        e = self._envio_por_app.get(aid)
        if e is not None:
            sa['creator_fulfillment'] = {
                'id': e['id'], 'status': e['status'], 'total_suspend_duration': e.get('total_suspend_duration', 0),
                'expiration_time': e['expiration_time'] if e['status'] in CON_FECHA_LIMITE else self._ahora()}
        return _ok({'sample_application': sa})

    def _productos(self, q: Mapping[str, str]) -> tuple[int, Json]:
        ids = [x for x in (q.get('product_ids') or '').split(',') if x]
        if not ids or len(ids) > 20:
            return _err(-10004, 'product_ids debe traer 1..20 ids (demo)')
        return _ok({'products': [dict(self.datos.productos[i]) for i in ids if i in self.datos.productos]})

    def _ordenes(self, q: Mapping[str, str], body: Json) -> tuple[int, Json]:
        size = int(q.get('page_size') or 20)
        if not 1 <= size <= 100:
            return _err(-10003, 'page_size inválido (demo)')
        ahora = self._ahora()
        ge, lt = body.get('create_time_ge'), body.get('create_time_lt')
        if ge is None and lt is None:
            ge, lt = ahora - 30 * 86400, ahora + 1          # sin ventana la API real solo trae ~30 días
        ge = ge if ge is not None else 0
        lt = lt if lt is not None else ahora + 1
        sel = sorted((o for o in self.datos.ordenes if ge <= o['create_time'] < lt),
                     key=lambda o: (-o['create_time'], o['id']))
        lineas = [(o, s) for o in sel for s in o['skus']]
        ini = int(q.get('page_token') or 0)
        trozo = lineas[ini:ini + size]
        agrupado: dict[str, dict[str, Any]] = collections.OrderedDict()
        for o, s in trozo:
            agrupado.setdefault(o['id'], {k: v for k, v in o.items() if k != 'skus'} | {'skus': []})['skus'].append(dict(s))
        sig = str(ini + size) if ini + size < len(lineas) else ''
        return _ok({'orders': list(agrupado.values()), 'next_page_token': sig, 'total_count': len(lineas)})

    def _vitrina(self, q: Mapping[str, str]) -> tuple[int, Json]:
        size = max(1, min(20, int(q.get('page_size') or 20)))
        ini = int(q.get('page_token') or 0)
        pagina = self.datos.vitrina[ini:ini + size]
        sig = str(ini + size) if ini + size < len(self.datos.vitrina) else ''
        return _ok({'products': [dict(p) for p in pagina], 'next_page_token': sig,
                    'total_count': len(self.datos.vitrina)})

    # ------------------------------------------------------------------ rev. 4: ficha completa de producto
    def _etiquetas(self, q: Mapping[str, str]) -> tuple[int, Json]:
        pid = q.get('product_id') or ''
        if not pid.isdigit():
            return _err(-10001, 'product_id es obligatorio (demo)')
        label = self.datos.etiquetas.get(pid) or {'can_apply': False, 'status': 'UNKNOWN'}
        return _ok({'label': json.loads(json.dumps(label))})

    def _dirigidas(self, q: Mapping[str, str], body: Json) -> tuple[int, Json]:
        sid = str(body.get('shop_id') or '')
        if not sid:
            return _err(-10001, 'shop_id es obligatorio (demo)')
        size = int(q.get('page_size') or 0)
        if not 0 < size <= 100:
            return _err(-10003, 'page_size inválido (demo)')
        todas = self.datos.dirigidas.get(sid, [])
        ini = int(q.get('page_token') or 0)
        sig = str(ini + size) if ini + size < len(todas) else ''
        return _ok({'target_collaborations': json.loads(json.dumps(todas[ini:ini + size])), 'next_page_token': sig,
                    'total_count': len(todas)})

    def _marketplace(self, q: Mapping[str, str], body: Json) -> tuple[int, Json]:
        palabras = body.get('title_keywords')
        if isinstance(palabras, str):
            palabras = palabras.split()
        if not palabras or not isinstance(palabras, list):
            return _err(-10001, 'title_keywords es obligatorio (demo)')
        size = int(q.get('page_size') or 20)
        if not 0 < size <= 100:
            return _err(-10003, 'page_size inválido (demo)')
        claves = [str(w).lower() for w in palabras if str(w).strip()]
        puntaje = []
        for p in self.datos.productos.values():
            titulo = str(p.get('title') or '').lower()
            n = sum(1 for w in claves if w in titulo)
            if n:
                puntaje.append((-n, -(p.get('units_sold') or 0), p['id'], p))
        puntaje.sort(key=lambda x: x[:3])
        return _ok({'products': [json.loads(json.dumps(x[3])) for x in puntaje[:size]], 'next_page_token': '',
                    'total_count': len(puntaje)})

    def _trazas(self, q: Mapping[str, str], body: Json) -> tuple[int, Json]:
        if self.datos.trazas_sin_permiso:
            return _err(CODIGO_SIN_PERMISO, 'Access denied: this API requires a scope your app was not granted (demo)')
        ge, lt = body.get('time_ge'), body.get('time_lt')
        if not isinstance(ge, int) or not isinstance(lt, int):
            return _err(-10001, 'time_ge y time_lt (ms) son obligatorios (demo)')
        size = int(q.get('page_size') or 0)
        if not 1 <= size <= 100:
            return _err(-10003, 'page_size inválido (demo)')
        sel = sorted((o for o in self.datos.ordenes if ge <= o['create_time'] * 1000 < lt),
                     key=lambda o: (-o['create_time'], o['id']))
        ini = int(q.get('page_token') or 0)
        out = []
        for o in sel[ini:ini + size]:
            tipos = self.datos.trazas.get(o['id']) or []
            skus = []
            for k, s in enumerate(o['skus']):
                x = {'id': s['id'], 'product_id': s['product_id'], 'price': s['price'], 'quantity': s['quantity'],
                     'commission_rate': s['commission_rate'], 'content_type': s['content_type'],
                     'content_id': s.get('content_id') or ''}
                t = tipos[k] if k < len(tipos) else None
                if t:
                    x['trace'] = {'id': f'{o["id"][-6:]}{k}', 'type': t}
                skus.append(x)
            out.append({'id': int(o['id']), 'status': o['status'], 'create_time': o['create_time'], 'skus': skus})
        sig = str(ini + size) if ini + size < len(sel) else ''
        return _ok({'orders': out, 'next_page_token': sig, 'total_count': len(sel)})


# ====================================================================== fixtures reales (solo desarrollo)
def modulo_fixtures_api() -> Any:
    """Importa spec/verificacion/fixtures_api.py (prototipo de 03 §9.1). La carpeta va al FINAL de sys.path."""
    import importlib
    if not os.path.isdir(DIR_VERIFICACION):
        raise FileNotFoundError('No está spec/verificacion (los datos reales solo existen en desarrollo)')
    if DIR_VERIFICACION not in sys.path:
        sys.path.append(DIR_VERIFICACION)
    previo = sys.dont_write_bytecode
    sys.dont_write_bytecode = True                       # spec/ es de solo lectura: sin .pyc nuevos
    try:
        return importlib.import_module('fixtures_api')
    finally:
        sys.dont_write_bytecode = previo


class TransporteFixtures:
    """Implementa `Transporte` envolviendo FakeTikTok (research/datos-reales). Ver el docstring del módulo."""

    def __init__(self, reloj: Reloj | None = None, **kw_fake: Any) -> None:
        self._fa = modulo_fixtures_api()
        if reloj is not None:
            kw_fake.setdefault('ahora', reloj.ahora())
        self.fake = self._fa.FakeTikTok(**kw_fake)
        self.fake.perfil = perfil_demo(self.fake.perfil)      # privacidad: nunca el usuario ni el avatar reales
        self._candado = threading.Lock()

    def manejar(self, metodo: str, url: str, cabeceras: Mapping[str, str], cuerpo: bytes | None) -> tuple[int, Json | None]:
        u, q = _consulta(url)
        cab = dict(cabeceras)
        if u.hostname == HOST_AUTH:
            if q.get('refresh_token'):
                q['refresh_token'] = self.fake.refresh_token
        else:
            q.pop('sign', None)
            q['sign'] = self._fa.generar_firma(u.path, q, cuerpo, self._fa.APP_SECRET_DEMO)
            cab['x-tts-access-token'] = self.fake.access_token
        url2 = urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, urllib.parse.urlencode(q), ''))
        try:
            with self._candado:
                return self.fake.manejar(metodo, url2, cab, cuerpo)
        except self._fa.ErrorTimeoutLectura as e:
            raise ErrorTimeoutLectura(type(e).__name__) from None
        except self._fa.ErrorRed as e:
            raise ErrorRed(type(e).__name__) from None
