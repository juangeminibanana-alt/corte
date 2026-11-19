"""Catálogo de vitrina y LIVE, y operaciones de vitrina de la cuenta Creator."""
from __future__ import annotations

import re
from typing import Any, Callable, Literal, Mapping

from ..errores import ErrorApi, ErrorDominio
from ..imagenes.claves import ref_valido
from ..interfaces import Almacen, Boveda, ClienteTikTok, ContextoSync, Json
from ..sincronizador import P_VITRINA, VITRINA_MUTACIONES, urls_galeria
from .conexion import scopes_de


AGREGAR = '/affiliate_creator/202405/showcases/products/add'
QUITAR = '/affiliate_creator/202409/showcases/products'
FIJAR = '/affiliate_creator/202409/showcases/products/top'
SCOPE_LEER = frozenset({'creator.showcase.read', 'creator.video.write'})
SCOPE_ESCRIBIR = 'creator.showcase.write'
_OPERACIONES: dict[str, tuple[Literal['POST', 'DELETE'], str]] = {
    'agregar': ('POST', AGREGAR), 'quitar': ('DELETE', QUITAR), 'fijar': ('POST', FIJAR),
}
_PRECIO = re.compile(r'[0-9]{1,12}(?:\.[0-9]{1,6})?')
_MONEDA = re.compile(r'[A-Z]{3}')
_SIN_PERMISO = 'TikTok no autorizó esta operación de vitrina para la cuenta conectada.'
_CAMBIO_CUENTA = 'La cuenta de TikTok cambió. Actualiza la vitrina para continuar.'
_SIN_CONFIRMAR = 'TikTok no confirmó el cambio. Revisa la vitrina antes de volver a intentarlo.'


def _invalido(campo: str) -> ErrorDominio:
    return ErrorDominio('parametros_invalidos', 'Revisa la selección de la vitrina.', http=400,
                        detalle={'parametro': campo})


def _cursor(valor: Any) -> str | None:
    if isinstance(valor, str) and 0 < len(valor) <= 2048 and all(33 <= ord(c) <= 126 for c in valor):
        return valor
    return None


def _objeto(valor: Any) -> Json:
    return valor if isinstance(valor, dict) else {}


def _texto(valor: Any, limite: int) -> str | None:
    return (' '.join(valor.split())[:limite] or None) if isinstance(valor, str) else None


def _importe(valor: Any) -> str | None:
    return valor if isinstance(valor, str) and _PRECIO.fullmatch(valor) else None


def _precios(producto: Json) -> tuple[str | None, str | None, str | None]:
    precios = _objeto(producto.get('price'))
    for campo in ('platform_discount_price', 'seller_discount_price', 'original_price'):
        precio = _objeto(precios.get(campo))
        moneda = _texto(precio.get('currency'), 8)
        minimo = _importe(precio.get('minimum_amount'))
        maximo = _importe(precio.get('maximum_amount'))
        if moneda and _MONEDA.fullmatch(moneda) and (minimo is not None or maximo is not None):
            return minimo, maximo, moneda
    return None, None, None


def _producto(p: Json, *, origen_live: bool = False) -> Json:
    precio_min, precio_max, moneda = _precios(p)
    status = _objeto(p.get('status'))
    revision = _texto(status.get('review_status'), 45)
    inventario = _texto(status.get('inventory_status'), 45)
    estado = 'HIDDEN' if status.get('is_hidden') is True else (
        inventario if inventario == 'SOLD_OUT' else revision or inventario
    )
    galeria = urls_galeria(p.get('main_images'), _objeto(p.get('addition')).get('customized_main_images'))
    producto = {'product_id': p['id'], 'titulo': _texto(p.get('title'), 255),
                'tienda': _texto(_objeto(p.get('shop')).get('name'), 160),
                'precio_min': precio_min, 'precio_max': precio_max, 'moneda': moneda,
                'imagen_url': galeria[0] if galeria else None, 'estado': estado}
    if origen_live:
        # El ejemplo oficial lo anida en status, aunque la tabla lo pone en la raíz.
        estados = ('ADDED', 'NOT_ADDED', 'REJECTED')
        agregado = status.get('added_status')
        if agregado not in estados:
            agregado = p.get('added_status')
        producto['estado_agregado'] = agregado if agregado in estados else None
    return producto


def _resultados(ids: list[str], data: Json, agregar: bool) -> list[Json]:
    codigo = data.get('code')
    if type(codigo) is int and codigo != 0:
        return [{'product_id': pid, 'ok': False, 'codigo': codigo,
                 'mensaje': 'TikTok rechazó la selección de productos.'} for pid in ids]
    if not agregar:
        if type(codigo) is not int:
            raise ErrorDominio('tiktok_no_disponible', _SIN_CONFIRMAR, http=502)
        return [{'product_id': pid, 'ok': True, 'codigo': None, 'mensaje': None} for pid in ids]

    errores = data.get('errors', [])
    if not isinstance(errores, list):
        raise ErrorDominio('tiktok_no_disponible', _SIN_CONFIRMAR, http=502)
    por_id: dict[str, int | None] = {}
    sin_id = False
    for error in errores:
        registro = _objeto(error)
        pid = _objeto(registro.get('detail')).get('product_id')
        if not isinstance(pid, str) or pid not in ids:
            sin_id = True
            continue
        codigo_error = registro.get('code')
        por_id[pid] = codigo_error if type(codigo_error) is int else None
    return [
        {'product_id': pid, 'ok': pid not in por_id and not sin_id, 'codigo': por_id.get(pid),
         'mensaje': ('TikTok no agregó este producto.' if pid in por_id else _SIN_CONFIRMAR if sin_id else None)}
        for pid in ids
    ]


class ShowcaseCreator:
    def __init__(self, cliente: ClienteTikTok, boveda: Boveda, conexion: Callable[[], Json],
                 almacen: Almacen, ahora: Callable[[], int]) -> None:
        self._cliente = cliente
        self._boveda = boveda
        self._conexion = conexion
        self._almacen = almacen
        self._ahora = ahora

    def capacidades(self, conexion: Mapping[str, Any]) -> tuple[bool, bool]:
        grant = self._boveda.leer()
        scopes = set(scopes_de(grant))
        lee = bool(conexion.get('estado') == 'conectada' and grant.get('user_type') == 1
                   and grant.get('open_id') and scopes & SCOPE_LEER)
        return lee, lee and SCOPE_ESCRIBIR in scopes

    def _contexto(self, escribir: bool) -> ContextoSync:
        estado = self._conexion().get('estado')
        grant = self._boveda.leer()
        cuenta = grant.get('open_id')
        if estado == 'reautorizar':
            raise ErrorDominio('reautorizar', 'Vuelve a autorizar tu cuenta de TikTok Shop.', http=409)
        if estado != 'conectada' or not isinstance(cuenta, str) or not cuenta:
            raise ErrorDominio('sin_credenciales', 'Conecta tu cuenta de creador de TikTok Shop.', http=409)
        scopes = set(scopes_de(grant))
        if grant.get('user_type') != 1 or not scopes & SCOPE_LEER or (escribir and SCOPE_ESCRIBIR not in scopes):
            raise ErrorDominio('sin_permiso_tiktok', _SIN_PERMISO, http=403)
        return ContextoSync(sync_id=None, open_id=cuenta, epoca_credenciales=int(grant.get('epoca_credenciales') or 0),
                            epoca_datos=self._almacen.epoca())

    def _vigente(self, ctx: ContextoSync) -> None:
        grant = self._boveda.leer()
        if (grant.get('open_id') != ctx.open_id or int(grant.get('epoca_credenciales') or 0) != ctx.epoca_credenciales
                or self._almacen.epoca() != ctx.epoca_datos):
            raise ErrorDominio('cuenta_cambio_sin_aplicar', _CAMBIO_CUENTA, http=409)

    def _llamar(self, metodo: Literal['GET', 'POST', 'DELETE'], ruta: str, ctx: ContextoSync,
                query: Mapping[str, str] | None = None, body: Json | None = None) -> Json:
        self._vigente(ctx)
        try:
            dato = self._cliente.llamar(metodo, ruta, query, body, ctx=ctx, reintentar=metodo == 'GET')
        except ErrorApi as error:
            if error.codigo == 'credenciales_cambiaron':
                raise ErrorDominio('cuenta_cambio_sin_aplicar', _CAMBIO_CUENTA, http=409) from None
            if error.codigo in (105005, 16501011) or error.http == 403:
                raise ErrorDominio('sin_permiso_tiktok', _SIN_PERMISO, http=403) from None
            if metodo != 'GET' and error.transitorio:
                raise ErrorDominio('tiktok_no_disponible', _SIN_CONFIRMAR, http=503) from None
            raise
        self._vigente(ctx)
        return dato

    def listar(self, filtros: Mapping[str, str]) -> Json:
        if set(filtros) - {'limit', 'cursor', 'origin'}:
            raise _invalido('filtros')
        origen = filtros.get('origin', 'SHOWCASE')
        if origen not in ('SHOWCASE', 'LIVE'):
            raise _invalido('origin')
        limite = filtros.get('limit', '20')
        if not re.fullmatch(r'[0-9]{1,2}', limite) or not 1 <= int(limite) <= 20:
            raise _invalido('limit')
        limite_num = int(limite)
        query = {'page_size': str(limite_num), 'origin': origen}
        if 'cursor' in filtros:
            token = _cursor(filtros['cursor'])
            if token is None:
                raise _invalido('cursor')
            query['page_token'] = token
        dato = self._llamar('GET', P_VITRINA, self._contexto(False), query=query)
        productos = {}
        lista = dato.get('products')
        if isinstance(lista, list):
            for item in lista[:limite_num]:
                p = _objeto(item)
                if ref_valido('p', p.get('id')) and p['id'] not in productos:
                    productos[p['id']] = _producto(p, origen_live=origen == 'LIVE')
        elif dato.get('total_count') != 0:
            raise ErrorDominio('tiktok_no_disponible', 'TikTok no devolvió una lista válida de productos.', http=502)
        total = dato.get('total_count')
        token = _cursor(dato.get('next_page_token'))
        return {'productos': list(productos.values()), 'total': total if type(total) is int and 0 <= total <= 2000 else None,
                'cursor_siguiente': token if token != query.get('page_token') else None}

    def _invalidar(self, ctx: ContextoSync) -> None:
        with self._almacen.escritor(ctx.epoca_datos) as db:
            db.execute("DELETE FROM sync_cursores WHERE clave = 'vitrina.at'")
            db.execute("""INSERT INTO sync_cursores(clave, valor, actualizado_at) VALUES (?,'1',?)
                          ON CONFLICT(clave) DO UPDATE SET valor=CAST(sync_cursores.valor AS INTEGER)+1,
                          actualizado_at=excluded.actualizado_at""", (VITRINA_MUTACIONES, self._ahora()))

    def cambiar(self, accion: str, body: Json) -> Json:
        if accion not in _OPERACIONES:
            raise ErrorDominio('no_encontrado', 'No existe esa operación de vitrina.', http=404)
        ids = body.get('product_ids')
        if (set(body) != {'product_ids'} or not isinstance(ids, list) or not 1 <= len(ids) <= 20
                or not all(ref_valido('p', pid) for pid in ids) or len(set(ids)) != len(ids)):
            raise _invalido('product_ids')
        ctx = self._contexto(True)
        metodo, ruta = _OPERACIONES[accion]
        datos = {'product_ids': ids}
        if accion == 'agregar':
            datos['add_type'] = 'PRODUCT_ID'
        self._invalidar(ctx)
        try:
            resultado = self._llamar(metodo, ruta, ctx, body=datos)
        except ErrorApi as error:
            if error.codigo != 16015001:
                raise
            resultado = {'code': error.codigo}
        finally:
            self._vigente(ctx)
            self._invalidar(ctx)
        return {'resultados': _resultados(ids, resultado, accion == 'agregar')}
