"""Publicación de videos comprables con un archivo ya cargado en TikTok Shop."""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from contextlib import suppress
from typing import TYPE_CHECKING, Callable, TypeGuard

from ..errores import ErrorApi, ErrorDominio
from ..imagenes.claves import ref_valido
from ..interfaces import Almacen, Boveda, ClienteTikTok, ContextoSync, Json
from .conexion import scopes_de

if TYPE_CHECKING:
    from .registro_publicacion import RegistroPublicacion


POST_VIDEO = '/affiliate_creator/202607/videos'
STATUS_VIDEO = '/affiliate_creator/202509/videos/{video_id}/status'
SCOPE = 'creator.video.write'
_ESTADOS = {'PROCESSING': 'procesando', 'SUCCESS': 'publicada', 'FAIL': 'fallida'}
_SIN_PERMISO = 'TikTok Shop no concedió el permiso de publicación de videos a esta cuenta de creador.'
_CUENTA_CAMBIO = 'Cambió la cuenta de TikTok Shop. Revisa la cuenta conectada antes de continuar.'
_INCIERTO = ('CUTGC no pudo confirmar el resultado. Revisa los videos de la cuenta de TikTok Shop desde la que '
             'iniciaste el envío antes de volver a publicar.')


def _invalido(campo: str) -> ErrorDominio:
    return ErrorDominio('parametros_invalidos', 'Revisa los datos del video y el enlace al producto.',
                        http=400, detalle={'parametro': campo})


def _incierto() -> ErrorDominio:
    return ErrorDominio('publicacion_sin_confirmar', _INCIERTO, http=503)


def file_id_valido(archivo: object) -> TypeGuard[str]:
    return (isinstance(archivo, str) and bool(archivo) and archivo.isprintable()
            and not any(c.isspace() for c in archivo) and '://' not in archivo
            and '\\' not in archivo and not archivo.startswith('/'))


def _payload(body: Json) -> Json:
    if not isinstance(body, dict) or set(body) - {'file_id', 'titulo', 'product_id', 'titulo_ancla', 'is_ai_generated'}:
        raise _invalido('campos')
    archivo = body.get('file_id')
    if not file_id_valido(archivo):
        raise _invalido('file_id')
    titulo = body.get('titulo')
    if not isinstance(titulo, str):
        raise _invalido('titulo')
    try:
        unidades = len(titulo.encode('utf-16-le')) // 2
    except UnicodeEncodeError:
        raise _invalido('titulo') from None
    if unidades > 4000:
        raise _invalido('titulo')
    if not ref_valido('p', body.get('product_id')):
        raise _invalido('product_id')
    titulo_ancla = body.get('titulo_ancla')
    if not isinstance(titulo_ancla, str):
        raise _invalido('titulo_ancla')
    ancla = unicodedata.normalize('NFC', titulo_ancla).strip()
    # TikTok pide menos de 30 caracteres y rechaza puntuación y emoji en esta etiqueta.
    if not 1 <= len(ancla) < 30 or not all(c.isalnum() or c == ' ' for c in ancla):
        raise _invalido('titulo_ancla')
    video: Json = {'file_id': archivo, 'title': titulo}
    if 'is_ai_generated' in body:
        if type(body['is_ai_generated']) is not bool:
            raise _invalido('is_ai_generated')
        video['is_ai_generated'] = body['is_ai_generated']
    return {'video_info': video, 'product_link_info': {'product_id': body['product_id'], 'title': ancla}}


class PublicacionesShop:
    def __init__(self, cliente: ClienteTikTok, boveda: Boveda, conexion: Callable[[], Json],
                 almacen: Almacen, registro: RegistroPublicacion) -> None:
        self._cliente = cliente
        self._boveda = boveda
        self._conexion = conexion
        self._almacen = almacen
        self._registro = registro

    def capacidades(self) -> Json:
        estado = self._conexion().get('estado')
        grant = self._boveda.leer()
        es_creator = type(grant.get('user_type')) is int and grant['user_type'] == 1
        cuenta = grant.get('open_id')
        conectada = bool(estado == 'conectada' and es_creator and isinstance(cuenta, str) and cuenta)
        return {'scope_requerido': SCOPE, 'scope_concedido': conectada and SCOPE in scopes_de(grant),
                'cuenta_creator_conectada': conectada}

    def preparar(self, body: Json) -> Json:
        return {'payload': _payload(body), 'autorizacion': self.capacidades()}

    def recuperar_envio(self, ctx: ContextoSync, body: Json) -> Json | None:
        """Recupera el resultado guardado del creador de la agenda incluso si debe renovar permisos."""
        payload = _payload(body)
        return self._registro.recuperar(ctx, payload['video_info']['file_id'], payload)

    def contexto(self, *, requerir_permiso: bool = True) -> ContextoSync:
        estado = self._conexion().get('estado')
        grant = self._boveda.leer()
        if requerir_permiso and estado == 'reautorizar':
            raise ErrorDominio('reautorizar', 'Vuelve a autorizar TikTok Shop para continuar.', http=409)
        if ((requerir_permiso and estado != 'conectada')
                or not isinstance(grant.get('open_id'), str) or not grant['open_id']):
            raise ErrorDominio('sin_credenciales', 'Conecta tu cuenta de creador de TikTok Shop.', http=409)
        if (type(grant.get('user_type')) is not int or grant['user_type'] != 1
                or (requerir_permiso and SCOPE not in scopes_de(grant))):
            raise ErrorDominio('sin_permiso_tiktok', _SIN_PERMISO, http=403)
        return ContextoSync(None, grant['open_id'], int(grant.get('epoca_credenciales') or 0), self._almacen.epoca())

    def _vigente(self, ctx: ContextoSync) -> None:
        actual = self.contexto()
        if (actual.open_id != ctx.open_id or actual.epoca_credenciales != ctx.epoca_credenciales
                or actual.epoca_datos != ctx.epoca_datos):
            raise ErrorDominio('cuenta_cambio_sin_aplicar', _CUENTA_CAMBIO, http=409)

    def _vigente_tras_envio(self, ctx: ContextoSync) -> None:
        try:
            self._vigente(ctx)
        except (ErrorDominio, ErrorApi, sqlite3.Error, RuntimeError):
            raise _incierto() from None

    @staticmethod
    def _error_proveedor(error: ErrorApi, *, envio: bool) -> ErrorDominio:
        if error.codigo == 'credenciales_cambiaron':
            return ErrorDominio('cuenta_cambio_sin_aplicar', _CUENTA_CAMBIO, http=409)
        if error.codigo == 'sin_credenciales':
            return ErrorDominio('sin_credenciales', 'Conecta tu cuenta de creador de TikTok Shop.', http=409)
        if error.decision == 'reautorizar' or error.codigo in (105001, 105002, 36009005):
            return ErrorDominio('reautorizar', 'Revisa la conexión de TikTok Shop para continuar.', http=409)
        if error.codigo in (105005, 16501011) or error.http == 403:
            return ErrorDominio('sin_permiso_tiktok', _SIN_PERMISO, http=403)
        if envio and (error.transitorio or error.http is None or error.http >= 500):
            return _incierto()
        detalle = {'codigo_tiktok': error.codigo} if type(error.codigo) is int else None
        return ErrorDominio('tiktok_no_disponible', 'TikTok Shop no pudo completar la operación.',
                            http=502, detalle=detalle)

    def publicar(self, body: Json, *, contexto_esperado: ContextoSync | None = None) -> Json:
        if not isinstance(body, dict) or body.get('confirmar') is not True:
            raise _invalido('confirmar')
        payload = _payload({k: v for k, v in body.items() if k != 'confirmar'})
        ctx = contexto_esperado or self.contexto()
        if contexto_esperado is not None:
            self._vigente(ctx)
        archivo = payload['video_info']['file_id']
        try:
            anterior = self._registro.iniciar(ctx, archivo, payload)
        except ErrorApi as error:
            raise self._error_proveedor(error, envio=False) from None
        if anterior is not None:
            self._vigente(ctx)
            return anterior

        intento_http = False

        def antes_de_enviar() -> None:
            nonlocal intento_http
            self._vigente(ctx)
            intento_http = True

        try:
            self._vigente(ctx)
            data = self._cliente.llamar('POST', POST_VIDEO, None, payload, ctx=ctx, reintentar=False,
                                        reemitir_tras_refresh=False, antes_de_enviar=antes_de_enviar)
        except (ErrorDominio, ErrorApi, sqlite3.Error, RuntimeError) as error:
            if not intento_http:
                # Una época ya sustituida nunca debe liberar registros de la cuenta nueva.
                with suppress(ErrorApi, ErrorDominio, sqlite3.Error, RuntimeError):
                    self._registro.liberar_sin_envio(ctx, archivo, payload)
                if isinstance(error, ErrorApi):
                    raise self._error_proveedor(error, envio=False) from None
                raise
            self._vigente_tras_envio(ctx)
            if isinstance(error, ErrorApi) and error.codigo != 'credenciales_cambiaron':
                raise self._error_proveedor(error, envio=True) from None
            raise _incierto() from None
        self._vigente_tras_envio(ctx)
        video = data.get('video') if isinstance(data, dict) else None
        if not isinstance(video, dict) or not ref_valido('v', video.get('id')):
            raise _incierto()
        resultado = {'video_id': video['id'], 'estado': 'aceptada'}
        cuota = data.get('quota', video.get('quota'))
        if isinstance(cuota, str) and re.fullmatch(r'[0-9]{1,12}/(day|week|month)', cuota):
            resultado['cuota'] = cuota
        try:
            self._registro.confirmar(ctx, archivo, resultado)
        except (ErrorApi, ErrorDominio, sqlite3.Error, RuntimeError):
            raise _incierto() from None
        self._vigente_tras_envio(ctx)
        return resultado

    def estado(self, video_id: str) -> Json:
        if not ref_valido('v', video_id):
            raise _invalido('video_id')
        ctx = self.contexto()
        try:
            data = self._cliente.llamar('GET', STATUS_VIDEO.format(video_id=video_id), ctx=ctx,
                                        antes_de_enviar=lambda: self._vigente(ctx))
        except ErrorApi as error:
            self._vigente(ctx)
            raise self._error_proveedor(error, envio=False) from None
        self._vigente(ctx)
        video = data.get('video') if isinstance(data, dict) else None
        if (not isinstance(video, dict) or video.get('id') != video_id or not isinstance(video.get('post_status'), str)
                or video['post_status'] not in _ESTADOS):
            raise ErrorDominio('tiktok_no_disponible', 'TikTok Shop no devolvió un estado válido del video.', http=502)
        resultado = {'video_id': video_id, 'estado': _ESTADOS[video['post_status']]}
        if video['post_status'] == 'SUCCESS' and type(video.get('post_time')) is int and video['post_time'] > 0:
            resultado['publicado_en'] = video['post_time']
        return resultado
