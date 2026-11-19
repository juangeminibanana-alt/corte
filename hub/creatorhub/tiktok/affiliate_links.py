"""Genera enlaces oficiales de TikTok Shop para productos de la cuenta Creator."""
from __future__ import annotations

import re
from typing import Any, Callable, Mapping
from urllib.parse import parse_qsl, urlsplit

from ..api.seguridad import validar_url_abrir
from ..errores import ErrorApi, ErrorDominio
from ..interfaces import Boveda, ClienteTikTok, ContextoSync, Json
from .conexion import scopes_de


RUTA_GENERAL = '/affiliate_creator/202505/affiliate_sharing_links/general_publishers/generate_batch'
RUTA_PUBLISHER = '/affiliate_creator/202504/affiliate_sharing_links/publisher/{publisher_id}/generate_batch'
SCOPE = 'creator.affiliate.share_link.read'
MAX_PRODUCTOS = 20
_CAMPOS = frozenset({'product_ids', 'campaign_id', 'publisher_id'})
_ID = re.compile(r'[1-9][0-9]{0,24}')
_PUBLISHER_ID = re.compile(r'[A-Za-z0-9_-]{1,128}')
_HOSTS = frozenset({'tiktok.com', 'www.tiktok.com', 'shop.tiktok.com', 'vt.tiktok.com', 'vm.tiktok.com'})
_HOSTS_CORTOS = frozenset({'vt.tiktok.com', 'vm.tiktok.com'})
_RUTA_PRODUCTO = re.compile(r'/view/product/[1-9][0-9]{0,24}/?')
_RUTA_CORTA = re.compile(r'/(?:t/|m/)[A-Za-z0-9_-]{1,128}/?')
_CODIGO_CORTO = re.compile(r'/[A-Za-z0-9_-]{1,128}/?')
_PARAMETROS_SECRETOS = frozenset({'access_token', 'refresh_token', 'x-tts-access-token', 'authorization', 'app_secret'})
_SIN_PERMISO = 'TikTok no autorizó la generación de enlaces de afiliado para esta cuenta.'
_SIN_CONEXION = 'Conecta tu cuenta de creador en TikTok Shop para generar enlaces de afiliado.'
_CAMBIO_CUENTA = 'La conexión con TikTok cambió. Vuelve a generar los enlaces.'


def _parametro_invalido(campo: str, mensaje: str) -> ErrorDominio:
    return ErrorDominio('parametros_invalidos', mensaje, http=400, detalle={'parametro': campo})


def _solicitud(cuerpo: Any) -> tuple[str, list[str], Json]:
    if not isinstance(cuerpo, dict) or set(cuerpo) - _CAMPOS:
        raise _parametro_invalido('cuerpo', 'Revisa los datos para generar enlaces.')
    ids = cuerpo.get('product_ids')
    if (not isinstance(ids, list) or not 1 <= len(ids) <= MAX_PRODUCTOS
            or not all(isinstance(i, str) and _ID.fullmatch(i) for i in ids)):
        raise _parametro_invalido('product_ids', f'Indica entre 1 y {MAX_PRODUCTOS} IDs de producto en texto.')
    ids = list(dict.fromkeys(ids))
    datos: Json = {'material': {'ids': ids, 'type': 'PRODUCT'}}
    if 'campaign_id' in cuerpo:
        campana = cuerpo['campaign_id']
        if not isinstance(campana, str) or not _ID.fullmatch(campana):
            raise _parametro_invalido('campaign_id', 'Revisa el ID de la campaña.')
        datos['campaign_id'] = campana
    ruta = RUTA_GENERAL
    if 'publisher_id' in cuerpo:
        editor = cuerpo['publisher_id']
        if not isinstance(editor, str) or not _PUBLISHER_ID.fullmatch(editor):
            raise _parametro_invalido('publisher_id', 'Revisa el ID del publisher. Usa letras, números, guiones o guiones bajos.')
        ruta = RUTA_PUBLISHER.format(publisher_id=editor)
    return ruta, ids, datos


def _material_id(valor: Any) -> str | None:
    # TikTok documenta material_id como entero para publisher y como texto en general.
    id_texto = str(valor) if type(valor) is int and 0 < valor < 10**25 else valor
    return id_texto if isinstance(id_texto, str) and _ID.fullmatch(id_texto) else None


def _enlace_tiktok(valor: Any) -> str | None:
    try:
        url = validar_url_abrir(valor, _HOSTS)
    except ErrorDominio:
        return None
    partes = urlsplit(url)
    ruta_corta = _CODIGO_CORTO if partes.hostname in _HOSTS_CORTOS else _RUTA_CORTA
    if not (_RUTA_PRODUCTO.fullmatch(partes.path) or ruta_corta.fullmatch(partes.path)):
        return None
    if any(k.lower() in _PARAMETROS_SECRETOS for k, _ in parse_qsl(partes.query, keep_blank_values=True)):
        return None
    return url


def _respuesta_por_id(items: Any, permitidos: set[str]) -> dict[str, Json]:
    encontrados: dict[str, Json] = {}
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                id_producto = _material_id(item.get('material_id'))
                if id_producto is not None and id_producto in permitidos:
                    encontrados.setdefault(id_producto, item)
    return encontrados


def _resultado(product_id: str, respuesta: Json | None, fallo: Json | None) -> Json:
    if fallo is not None:
        motivo = fallo.get('fail_reason')
        if isinstance(motivo, str) and motivo.strip().casefold() in {'product was sold out', 'the product was sold out'}:
            codigo, mensaje = 'producto_agotado', 'TikTok Shop informó que este producto está agotado.'
        else:
            codigo, mensaje = 'enlace_rechazado', 'TikTok Shop no pudo generar un enlace para este producto.'
        return {'product_id': product_id, 'enlace': None, 'codigo': codigo, 'mensaje': mensaje}
    if respuesta is None:
        return {'product_id': product_id, 'enlace': None, 'codigo': 'producto_sin_respuesta',
                'mensaje': 'TikTok Shop no devolvió un resultado para este producto.'}
    enlace = _enlace_tiktok(respuesta.get('sharing_link')) or _enlace_tiktok(respuesta.get('one_link'))
    return {'product_id': product_id, 'enlace': enlace, 'codigo': None if enlace else 'enlace_no_valido',
            'mensaje': None if enlace else 'TikTok Shop no devolvió un enlace web válido para este producto.'}


class AffiliateLinksCreator:
    def __init__(self, cliente: ClienteTikTok, boveda: Boveda, conexion: Callable[[], Json]) -> None:
        self._cliente = cliente
        self._boveda = boveda
        self._conexion = conexion

    def disponible(self, conexion: Mapping[str, Any]) -> bool:
        grant = self._boveda.leer()
        return (conexion.get('estado') == 'conectada' and grant.get('user_type') == 1
                and bool(grant.get('open_id')) and SCOPE in scopes_de(grant))

    def generar(self, cuerpo: Any) -> Json:
        ruta, ids, datos = _solicitud(cuerpo)
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
            data = self._cliente.llamar('POST', ruta, None, datos, ctx=contexto, reintentar=False)
        except ErrorApi as error:
            if error.codigo == 'credenciales_cambiaron':
                raise ErrorDominio('cuenta_cambio_sin_aplicar', _CAMBIO_CUENTA, http=409) from None
            if error.codigo in (105005, 16501011) or error.http == 403:
                raise ErrorDominio('sin_permiso_tiktok', _SIN_PERMISO, http=403) from None
            raise
        actual = self._boveda.leer()
        if (actual.get('open_id'), actual.get('epoca_credenciales')) != (
                grant.get('open_id'), grant.get('epoca_credenciales')):
            raise ErrorDominio('cuenta_cambio_sin_aplicar', _CAMBIO_CUENTA, http=409)

        permitidos = set(ids)
        # Un error transversal sin producto impide confirmar los enlaces del lote.
        exitos = {} if data.get('errors') else _respuesta_por_id(data.get('sharing_links'), permitidos)
        fallos = _respuesta_por_id(data.get('failed_materials'), permitidos)
        return {'resultados': [_resultado(i, exitos.get(i), fallos.get(i)) for i in ids]}
