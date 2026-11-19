"""Búsqueda del marketplace Creator. Una lectura de TikTok Shop por página solicitada."""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Callable, Mapping

from ..api.seguridad import validar_url_abrir
from ..errores import ErrorApi, ErrorDominio
from ..imagenes.claves import url_permitida
from ..interfaces import Boveda, ClienteTikTok, ContextoSync, Json
from .conexion import scopes_de


RUTA = '/affiliate_creator/202405/open_collaborations/products/search'
SCOPE = 'creator.affiliate_collaboration.read'
_FILTROS = frozenset({'q', 'category_id', 'min_price', 'max_price', 'min_commission', 'max_commission',
                      'sort', 'direction', 'limit', 'cursor'})
_ORDENES = frozenset({'commission_rate', 'product_sales_price', 'commission', 'units_sold'})
_ID = re.compile(r'[0-9]{1,25}')
_DECIMAL = re.compile(r'[0-9]{1,12}(?:\.[0-9]{1,2})?')
_PRECIO_RESPUESTA = re.compile(r'[0-9]{1,12}(?:\.[0-9]{1,6})?')
_MONEDA = re.compile(r'[A-Z]{3}')
_SIN_PERMISO = 'TikTok no autorizó la búsqueda de colaboraciones para esta cuenta.'
_SIN_CONEXION = 'Conecta tu cuenta de creador en TikTok Shop para buscar productos.'
_CAMBIO_CUENTA = 'La conexión con TikTok cambió. Vuelve a buscar.'


def _invalido(campo: str) -> ErrorDominio:
    return ErrorDominio('parametros_invalidos', 'Revisa los filtros de búsqueda.', http=400,
                        detalle={'parametro': campo})


def _cursor(valor: Any) -> str | None:
    if isinstance(valor, str) and 0 < len(valor) <= 2048 and all(33 <= ord(c) <= 126 for c in valor):
        return valor
    return None


def _decimal(q: Mapping[str, str], campo: str) -> Decimal | None:
    valor = q.get(campo, '').strip()
    if not valor:
        return None
    if not _DECIMAL.fullmatch(valor):
        raise _invalido(campo)
    return Decimal(valor)


def _filtros(q: Mapping[str, str]) -> tuple[dict[str, str], Json]:
    if set(q) - _FILTROS:
        raise _invalido('filtros')
    size = q.get('limit', '20')
    if not re.fullmatch(r'[0-9]{1,2}', size) or not 1 <= int(size) <= 20:
        raise _invalido('limit')
    query = {'page_size': str(int(size))}
    if q.get('cursor'):
        token = _cursor(q['cursor'])
        if token is None:
            raise _invalido('cursor')
        query['page_token'] = token
    sort, direction = q.get('sort', ''), q.get('direction', '')
    if sort:
        if sort not in _ORDENES:
            raise _invalido('sort')
        query['sort_field'] = sort
    if direction:
        if not sort or direction not in ('ASC', 'DESC'):
            raise _invalido('direction')
        query['sort_order'] = direction

    body: Json = {}
    texto = q.get('q', '').strip()
    palabras = texto.split()
    if len(texto) > 255 or len(palabras) > 20 or not all(palabra.isprintable() for palabra in palabras):
        raise _invalido('q')
    if palabras:
        body['title_keywords'] = palabras
    categoria = q.get('category_id', '').strip()
    if categoria:
        if not _ID.fullmatch(categoria):
            raise _invalido('category_id')
        body['category'] = {'id': categoria}

    precio_min, precio_max = _decimal(q, 'min_price'), _decimal(q, 'max_price')
    if precio_min is not None and precio_min <= 0:
        raise _invalido('min_price')
    if precio_max is not None and (precio_max <= 0 or (precio_min is not None and precio_max <= precio_min)):
        raise _invalido('max_price')
    precios = {k: format(v, 'f') for k, v in (('amount_ge', precio_min), ('amount_lt', precio_max)) if v is not None}
    if precios:
        body['sales_price_range'] = precios

    com_min, com_max = _decimal(q, 'min_commission'), _decimal(q, 'max_commission')
    if com_min is not None and not 1 <= com_min <= 80:
        raise _invalido('min_commission')
    if com_max is not None and (not 10 <= com_max <= 100 or (com_min is not None and com_max <= com_min)):
        raise _invalido('max_commission')
    comisiones = {k: int(v * 100) for k, v in (('rate_ge', com_min), ('rate_lt', com_max)) if v is not None}
    if comisiones:
        body['commission_rate_range'] = comisiones
    return query, body


def _id(valor: Any) -> str | None:
    return valor if isinstance(valor, str) and _ID.fullmatch(valor) else None


def _objeto(valor: Any) -> Json:
    return valor if isinstance(valor, dict) else {}


def _texto(valor: Any, maximo: int) -> str | None:
    if not isinstance(valor, str):
        return None
    return ' '.join(valor.split())[:maximo] or None


def _precio(valor: Any) -> str | None:
    return valor if isinstance(valor, str) and _PRECIO_RESPUESTA.fullmatch(valor) else None


def _rango_precio(producto: Json) -> tuple[str | None, str | None, str | None]:
    for campo in ('sales_price', 'original_price'):
        precio = _objeto(producto.get(campo))
        moneda = _texto(precio.get('currency'), 8)
        if moneda is None or not _MONEDA.fullmatch(moneda):
            continue
        minimo = _precio(precio.get('minimum_amount'))
        maximo = _precio(precio.get('maximum_amount'))
        if minimo is not None or maximo is not None:
            return minimo, maximo, moneda
    return None, None, None


def _entero_no_negativo(valor: Any) -> int | None:
    return valor if type(valor) is int and 0 <= valor <= 2**53 - 1 else None


def _producto(p: Json) -> Json | None:
    producto_id = _id(p.get('id'))
    if producto_id is None:
        return None
    minimo, maximo, moneda = _rango_precio(p)
    comision = _entero_no_negativo(_objeto(p.get('commission')).get('rate'))
    enlace: str | None = None
    try:
        enlace = validar_url_abrir(p.get('detail_link'), frozenset({'shop.tiktok.com', 'www.tiktok.com'}))
    except ErrorDominio:
        pass
    imagen = p.get('main_image_url')
    categorias = []
    ramas = p.get('category_chains')
    for raw in ramas[:3] if isinstance(ramas, list) else []:
        categoria = _objeto(raw)
        cid = _id(categoria.get('id'))
        nombre = _texto(categoria.get('local_name'), 160)
        # La API filtra exclusivamente por categorías de primer nivel.
        if cid and nombre and categoria.get('parent_id') in (None, '', '0', 0):
            categorias.append({'id': cid, 'nombre': nombre})
            break
    return {
        'product_id': producto_id,
        'titulo': _texto(p.get('title'), 255),
        'tienda': _texto(_objeto(p.get('shop')).get('name'), 160),
        'region': _texto(p.get('sale_region'), 8),
        'precio_min': minimo,
        'precio_max': maximo,
        'moneda': moneda,
        'comision_porcentaje': comision / 100 if comision is not None and 100 <= comision <= 8000 else None,
        'unidades_vendidas': _entero_no_negativo(p.get('units_sold')),
        'inventario': p.get('has_inventory') if type(p.get('has_inventory')) is bool else None,
        'categorias': categorias,
        'enlace': enlace,
        'imagen_url': imagen if url_permitida(imagen) else None,
    }


class MarketplaceCreator:
    def __init__(self, cliente: ClienteTikTok, boveda: Boveda, conexion: Callable[[], Json]) -> None:
        self._cliente = cliente
        self._boveda = boveda
        self._conexion = conexion

    def disponible(self, conexion: Mapping[str, Any]) -> bool:
        grant = self._boveda.leer()
        return (conexion.get('estado') == 'conectada' and grant.get('user_type') == 1
                and bool(grant.get('open_id')) and SCOPE in scopes_de(grant))

    def buscar(self, filtros: Mapping[str, str]) -> Json:
        query, body = _filtros(filtros)
        grant = self._boveda.leer()
        estado = self._conexion().get('estado')
        if estado == 'reautorizar':
            raise ErrorDominio('reautorizar', 'Vuelve a autorizar tu cuenta de TikTok Shop.', http=409)
        if estado != 'conectada' or not grant.get('open_id'):
            raise ErrorDominio('sin_credenciales', _SIN_CONEXION, http=409)
        if grant.get('user_type') != 1 or SCOPE not in scopes_de(grant):
            raise ErrorDominio('sin_permiso_tiktok', _SIN_PERMISO, http=403)

        contexto = ContextoSync(sync_id=None, open_id=grant['open_id'],
                               epoca_credenciales=int(grant.get('epoca_credenciales') or 0), epoca_datos=0)
        try:
            data = self._cliente.llamar('POST', RUTA, query, body, ctx=contexto)
        except ErrorApi as error:
            if error.codigo in (105005, 16501011) or error.http == 403:
                raise ErrorDominio('sin_permiso_tiktok', _SIN_PERMISO, http=403) from None
            if error.codigo == 'credenciales_cambiaron':
                raise ErrorDominio('cuenta_cambio_sin_aplicar', _CAMBIO_CUENTA, http=409) from None
            raise
        actual = self._boveda.leer()
        if (actual.get('open_id'), actual.get('epoca_credenciales')) != (
                grant.get('open_id'), grant.get('epoca_credenciales')):
            raise ErrorDominio('cuenta_cambio_sin_aplicar', _CAMBIO_CUENTA, http=409)

        productos: list[Json] = []
        vistos: set[str] = set()
        items = data.get('products')
        for item in items[:int(query['page_size'])] if isinstance(items, list) else []:
            producto = _producto(_objeto(item))
            if producto is not None and producto['product_id'] not in vistos:
                vistos.add(producto['product_id'])
                productos.append(producto)
        cursor = _cursor(data.get('next_page_token'))
        return {'productos': productos, 'cursor_siguiente': cursor if cursor != query.get('page_token') else None,
                'total': _entero_no_negativo(data.get('total_count'))}
