"""Carga de videos de Shop. Los archivos grandes atraviesan CUTGC una parte a la vez."""
from __future__ import annotations

import hashlib
import math
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from ..errores import ErrorApi, ErrorDominio
from ..interfaces import ClienteTikTok, ContextoSync, Json
from .cliente import P_ARCHIVO_VIDEO
from .publicaciones import POST_VIDEO, PublicacionesShop, file_id_valido

MIB = 1024 * 1024
PARTE_MAX = 10 * MIB
VIDEO_MAX = 500 * MIB
INICIAR = '/open/202512/file/init'
FORMATOS = {
    'mp4': 'video/mp4', 'mov': 'video/quicktime', 'mkv': 'video/x-matroska', 'wmv': 'video/x-ms-wmv',
    'webm': 'video/webm', 'avi': 'video/x-msvideo', '3gp': 'video/3gpp', 'flv': 'video/x-flv',
    'mpg': 'video/mpeg', 'mpeg': 'video/mpeg',
}
FORMATOS_GRANDES = {'mp4', 'mov', 'webm'}


def _archivo_invalido(mensaje: str) -> ErrorDominio:
    return ErrorDominio('archivo_invalido', mensaje, http=422)


def _extension(nombre: object, *, grande: bool) -> str:
    if not isinstance(nombre, str) or not nombre.isprintable() or len(nombre) > 255:
        raise _archivo_invalido('Selecciona un archivo de video.')
    ext = nombre.rpartition('.')[2].lower() if '.' in nombre else ''
    if ext not in FORMATOS:
        raise _archivo_invalido('Selecciona un formato de video compatible con TikTok Shop.')
    if grande and ext not in FORMATOS_GRANDES:
        raise _archivo_invalido('Para videos de 10 MB o más elige un archivo MP4, MOV o WebM.')
    return ext


def _comprobar_formato(ext: str, datos: bytes) -> None:
    if ext in ('mp4', 'mov', '3gp'):
        compatible = (datos[4:8] == b'ftyp' and datos[8:12] not in {
            b'heic', b'heix', b'hevc', b'mif1', b'msf1', b'avif', b'avis', b'M4A ', b'M4B ',
        }) or (ext == 'mov' and datos[4:8] in (b'wide', b'moov', b'mdat', b'free'))
    elif ext in ('mkv', 'webm'):
        compatible = datos.startswith(bytes.fromhex('1a45dfa3')) and (
            (b'webm' if ext == 'webm' else b'matroska') in datos[:1024])
    elif ext == 'avi':
        compatible = datos[:4] == b'RIFF' and datos[8:12] == b'AVI '
    elif ext == 'wmv':
        compatible = datos.startswith(bytes.fromhex('3026b2758e66cf11a6d900aa0062ce6c'))
    elif ext == 'flv':
        compatible = datos.startswith(b'FLV') and len(datos) >= 9 and datos[4] & 1
    else:
        compatible = datos.startswith((bytes.fromhex('000001ba'), bytes.fromhex('000001b3')))
    if len(datos) < 16 or not compatible:
        raise _archivo_invalido('El contenido del archivo no corresponde al formato de video elegido.')


def _id(resultado: object) -> str:
    # TikTok entrega un identificador opaco; admite los mismos valores que el contrato de publicación.
    if not file_id_valido(resultado):
        raise ErrorDominio('tiktok_no_disponible', 'TikTok no devolvió un identificador de archivo válido.', http=502)
    return resultado


@dataclass
class SesionCarga:
    contexto: ContextoSync
    extension: str
    tamano: int
    partes: int
    url: str
    token: str = field(repr=False)
    ultimo_uso: float = 0
    recibidas: int = 0
    ultima_huella: bytes = b''
    resultado: Json = field(default_factory=dict)
    fallida: bool = False
    candado: threading.Lock = field(default_factory=threading.Lock)


class CargaVideosShop:
    def __init__(self, cliente: ClienteTikTok, publicaciones: PublicacionesShop,
                 reloj: Callable[[], float] = time.monotonic) -> None:
        self.cliente = cliente
        self.publicaciones = publicaciones
        self.reloj = reloj
        self._sesiones: dict[str, SesionCarga] = {}
        self._candado = threading.Lock()

    def _llamar(self, ctx: ContextoSync, fn: Callable[[], Json]) -> Json:
        self.publicaciones._vigente(ctx)
        try:
            resultado = fn()
        except ErrorApi as error:
            self.publicaciones._vigente(ctx)
            raise self.publicaciones._error_proveedor(error, envio=False) from None
        self.publicaciones._vigente(ctx)
        return resultado

    def directa(self, nombre: str, datos: bytes) -> Json:
        ctx = self.publicaciones.contexto()
        if not 0 < len(datos) < PARTE_MAX:
            raise _archivo_invalido('Usa la carga por partes desde 10 MB. El archivo debe contener video.')
        ext = _extension(nombre, grande=False)
        _comprobar_formato(ext, datos)
        borde = 'cutgc' + secrets.token_hex(24)
        cabecera = (f'--{borde}\r\nContent-Disposition: form-data; name="data"; filename="video.{ext}"\r\n'
                    f'Content-Type: {FORMATOS[ext]}\r\n\r\n').encode('ascii')
        multipart = (f'multipart/form-data; boundary={borde}', b''.join((cabecera, datos, f'\r\n--{borde}--\r\n'.encode())))
        respuesta = self._llamar(ctx, lambda: self.cliente.llamar(
            'POST', P_ARCHIVO_VIDEO, ctx=ctx, archivo_multipart=multipart, reintentar=False,
            reemitir_tras_refresh=False, antes_de_enviar=lambda: self.publicaciones._vigente(ctx)))
        video = respuesta.get('video_file')
        if not isinstance(video, dict):
            raise ErrorDominio('tiktok_no_disponible', 'TikTok no confirmó la carga del archivo.', http=502)
        md5 = video.get('md5')
        if md5 is not None and (not isinstance(md5, str) or md5.lower() != hashlib.md5(datos, usedforsecurity=False).hexdigest()):
            raise ErrorDominio('tiktok_no_disponible', 'TikTok recibió un archivo distinto. Vuelve a cargar el video.', http=502)
        return {'file_id': _id(video.get('id'))}

    def iniciar(self, body: Json) -> Json:
        ctx = self.publicaciones.contexto()
        if not isinstance(body, dict) or set(body) != {'bytes', 'nombre'}:
            raise _archivo_invalido('Indica el nombre y el tamaño del archivo.')
        ext = _extension(body['nombre'], grande=True)
        tamano = body['bytes']
        if type(tamano) is not int or not PARTE_MAX <= tamano <= VIDEO_MAX:
            raise _archivo_invalido('La carga por partes admite videos de 10 a 500 MB.')
        partes = math.ceil(tamano / PARTE_MAX)
        payload = {'file_size': tamano, 'file_name': f'video.{ext}', 'file_type': 'video', 'total_chunk_count': partes,
                   'target_path': '[POST]' + POST_VIDEO}
        with self._candado:
            self._purgar()
            if len(self._sesiones) >= 64:
                completa = next((k for k, s in self._sesiones.items() if s.recibidas == s.partes), None)
                if completa is None:
                    raise ErrorDominio('demasiadas_solicitudes', 'Espera a que finalice otra carga de video.', http=429)
                self._sesiones.pop(completa)
            data = self._llamar(ctx, lambda: self.cliente.llamar(
                'POST', INICIAR, None, payload, ctx=ctx, reintentar=False, reemitir_tras_refresh=False,
                antes_de_enviar=lambda: self.publicaciones._vigente(ctx)))
            url, token = data.get('upload_url'), data.get('upload_token')
            if not isinstance(url, str) or not 0 < len(url) <= 8192 or not isinstance(token, str) or not 0 < len(token) <= 8192:
                raise ErrorDominio('tiktok_no_disponible', 'TikTok no confirmó el inicio de la carga.', http=502)
            ident = secrets.token_hex(20)
            self._sesiones[ident] = SesionCarga(ctx, ext, tamano, partes, url, token, self.reloj())
        return {'carga_id': ident, 'partes': partes}

    def _purgar(self) -> None:
        limite = self.reloj() - 3600
        vencidas = [key for key, s in self._sesiones.items() if s.ultimo_uso < limite and not s.candado.locked()]
        for key in vencidas:
            self._sesiones.pop(key)

    def parte(self, ident: str, numero: int, datos: bytes) -> Json:
        with self._candado:
            self._purgar()
            s = self._sesiones.get(ident)
        if s is None:
            raise ErrorDominio('no_encontrado', 'La carga terminó o venció. Selecciona el video de nuevo.', http=404)
        with s.candado:
            self.publicaciones._vigente(s.contexto)
            if s.fallida:
                raise ErrorDominio('conflicto', 'Selecciona el video otra vez para iniciar una nueva carga.', http=409)
            if not 1 <= numero <= s.partes:
                raise _archivo_invalido('Número de parte fuera del archivo.')
            esperados = (numero * s.tamano // s.partes) - ((numero - 1) * s.tamano // s.partes)
            if len(datos) != esperados:
                raise _archivo_invalido('La parte del video llegó incompleta.')
            huella = hashlib.sha256(datos).digest()
            if numero == s.recibidas and huella == s.ultima_huella:
                return s.resultado.copy()
            if numero != s.recibidas + 1:
                raise ErrorDominio('conflicto', 'Envía las partes del video en orden.', http=409)
            if numero == 1:
                _comprobar_formato(s.extension, datos)
            try:
                data = self._llamar(s.contexto, lambda: self.cliente.subir_parte_video(
                    s.url, s.token, numero, FORMATOS[s.extension], datos, ctx=s.contexto,
                    antes_de_enviar=lambda: self.publicaciones._vigente(s.contexto)))
                if numero == s.partes:
                    resultado = {'file_id': _id(data.get('resource_id'))}
                    s.token = s.url = ''
                else:
                    if not data.get('part_id'):
                        raise ErrorDominio('tiktok_no_disponible', 'TikTok no confirmó esta parte del video.', http=502)
                    resultado = {'recibida': numero}
            except Exception:
                # Una pérdida de respuesta puede haber avanzado el contador remoto. Empezar otra carga es seguro.
                s.fallida = True
                with self._candado:
                    self._sesiones.pop(ident, None)
                raise
            s.recibidas, s.ultima_huella, s.resultado, s.ultimo_uso = numero, huella, resultado, self.reloj()
            return resultado.copy()
