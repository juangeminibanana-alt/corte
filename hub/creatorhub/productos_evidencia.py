"""Evidencia de producto capturada o importada por el dueño; no simula una API de TikTok.

Una captura se valida antes de tocar SQLite. Las fotografías sólo salen mediante el
proxy autenticado de Corte. El origen documenta quién aportó los datos; no acredita
por sí solo la veracidad de una reseña o una compra verificada.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import math
import re
import sqlite3
import threading
import urllib.parse
from typing import Any, Mapping

from .errores import ErrorDominio
from .imagenes import claves as imagen_claves
from .interfaces import Almacen, Bus, Contexto, Imagenes, Json, PedidoImagen, Reloj

_log = logging.getLogger('creatorhub.productos_evidencia')
MAX_DOCUMENTO_BYTES = 192 * 1024
MAX_RESENAS = 100
PAGINA_RESENAS = 20
MAX_COLUMNAS = 16
MAX_FILAS = 100
MAX_IMAGENES_TABLA = 6
MAX_IMAGENES_RESENA = 10
ESTADOS = frozenset({'disponible', 'no_disponible', 'no_aplica', 'error', 'pendiente'})
_PID = re.compile(r'[0-9]{1,25}')
_REVIEW_ID = re.compile(r'[A-Za-z0-9_-]{1,128}')
_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_TIKTOK_HOSTS = ('tiktok.com', 'tiktokshop.com')
_ERRORES_FUENTE = {
    'fuente_verificacion_requerida': 'TikTok pide una verificación antes de permitir la lectura de este producto.',
    'fuente_no_disponible': 'No pudimos leer la ficha pública de TikTok. Inténtalo de nuevo.',
    'fuente_sin_datos': 'La ficha pública no entregó una tabla de tallas ni reseñas consultables.',
    'fuente_respuesta_invalida': 'La ficha pública no entregó datos válidos para este producto.',
}


def _invalido(campo: str, mensaje: str = 'Los datos de la evidencia no son válidos.') -> ErrorDominio:
    return ErrorDominio('parametros_invalidos', mensaje, http=422, detalle={'campo': campo})


def producto_id(valor: Any) -> str:
    if not isinstance(valor, str) or _PID.fullmatch(valor) is None:
        raise _invalido('product_id')
    return valor


def _objeto(valor: Any, permitidas: set[str], campo: str) -> Json:
    if not isinstance(valor, dict) or set(valor) - permitidas:
        raise _invalido(campo)
    return valor


def _texto(valor: Any, campo: str, limite: int, vacio: bool = False) -> str:
    if (not isinstance(valor, str) or len(valor) > limite or _CONTROL.search(valor)
            or (not vacio and not valor.strip())):
        raise _invalido(campo)
    return valor.strip()


def _entero(valor: Any, campo: str, minimo: int, maximo: int) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int) or not minimo <= valor <= maximo:
        raise _invalido(campo)
    return valor


def _epoch(valor: Any, campo: str, ahora: int, opcional: bool = False) -> int | None:
    if valor is None and opcional:
        return None
    return _entero(valor, campo, 1, ahora + 300)


def _fuente(valor: Any, pid: str) -> Json:
    d = _objeto(valor, {'tipo', 'url', 'nombre'}, 'fuente')
    if d.get('tipo') not in ('captura_tiktok', 'vendedor'):
        raise _invalido('fuente.tipo')
    nombre = _texto(d.get('nombre'), 'fuente.nombre', 100)
    url = _texto(d.get('url'), 'fuente.url', 2048)
    try:
        u = urllib.parse.urlsplit(url)
        host = u.hostname or ''
        if (u.scheme != 'https' or u.username is not None or u.password is not None
                or u.port not in (None, 443) or not host or not url.isascii()
                or any(c in url for c in '\\ \t\r\n') or u.fragment or u.query):
            raise ValueError
        if d['tipo'] == 'captura_tiktok':
            if not any(host == suffix or host.endswith('.' + suffix) for suffix in _TIKTOK_HOSTS):
                raise ValueError
            # Asociar la captura al producto pedido, nunca aceptar la portada de otra ficha.
            if pid not in urllib.parse.unquote(u.path).split('/'):
                raise ValueError
        elif not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', host):
            raise ValueError
    except (ValueError, UnicodeError):
        raise _invalido('fuente.url', 'Indica un enlace público del producto sin parámetros de seguimiento.') from None
    return {'tipo': d['tipo'], 'url': url, 'nombre': nombre}


def _imagenes(valor: Any, campo: str, maximo: int) -> list[str]:
    if not isinstance(valor, list) or len(valor) > maximo:
        raise _invalido(campo)
    salida: list[str] = []
    for url in valor:
        if imagen_claves.url_permitida(url) is None:
            raise _invalido(campo, 'Las fotos deben proceder del CDN de TikTok permitido por Corte.')
        if url not in salida:
            salida.append(url)
    return salida


def _cabecera(d: Json, pid: str, ahora: int) -> Json:
    estado = d.get('estado')
    if not isinstance(estado, str) or estado not in ESTADOS:
        raise _invalido('estado')
    disponible = estado == 'disponible'
    fuente = d.get('fuente')
    if fuente is None and not disponible:
        origen = None
    else:
        origen = _fuente(fuente, pid)
    return {'estado': estado, 'fuente': origen,
            'consultado_at': _epoch(d.get('consultado_at'), 'consultado_at', ahora, opcional=not disponible)}


def _tabla(valor: Any, pid: str, ahora: int) -> Json:
    d = _objeto(valor, {'estado', 'fuente', 'consultado_at', 'tabla'}, 'tabla_tallas')
    salida = _cabecera(d, pid, ahora)
    if salida['estado'] != 'disponible':
        if d.get('tabla') is not None:
            raise _invalido('tabla_tallas.tabla', 'Una consulta pendiente o fallida no contiene una tabla disponible.')
        return dict(salida, tabla=None)
    t = _objeto(d.get('tabla'), {'columnas', 'filas', 'unidad', 'imagenes'}, 'tabla_tallas.tabla')
    columnas, filas = t.get('columnas', []), t.get('filas', [])
    if not isinstance(columnas, list) or len(columnas) > MAX_COLUMNAS:
        raise _invalido('tabla_tallas.columnas')
    columnas = [_texto(c, 'tabla_tallas.columnas', 80) for c in columnas]
    if not isinstance(filas, list) or len(filas) > MAX_FILAS:
        raise _invalido('tabla_tallas.filas')
    valores = []
    for fila in filas:
        if not isinstance(fila, list) or not columnas or len(fila) != len(columnas):
            raise _invalido('tabla_tallas.filas')
        valores.append([_texto(c, 'tabla_tallas.filas', 150, vacio=True) for c in fila])
    if bool(columnas) != bool(valores):
        raise _invalido('tabla_tallas.filas', 'La tabla necesita columnas y filas correspondientes.')
    imagenes = _imagenes(t.get('imagenes', []), 'tabla_tallas.imagenes', MAX_IMAGENES_TABLA)
    if not valores and not imagenes:
        raise _invalido('tabla_tallas.tabla', 'Incluye las medidas originales o una imagen de la tabla del producto.')
    unidad = t.get('unidad')
    if unidad is not None:
        unidad = _texto(unidad, 'tabla_tallas.unidad', 40)
    return dict(salida, tabla={'columnas': columnas, 'filas': valores, 'unidad': unidad, 'imagenes': imagenes})


def _resenas(valor: Any, pid: str, ahora: int) -> Json:
    d = _objeto(valor, {'estado', 'fuente', 'consultado_at', 'promedio', 'total', 'items'}, 'resenas')
    salida = _cabecera(d, pid, ahora)
    items = d.get('items', [])
    if not isinstance(items, list) or len(items) > MAX_RESENAS:
        raise _invalido('resenas.items')
    promedio, total = d.get('promedio'), d.get('total')
    if salida['estado'] != 'disponible':
        if items or promedio is not None or total is not None:
            raise _invalido('resenas', 'Una consulta pendiente o fallida no significa cero reseñas.')
        return dict(salida, promedio=None, total=None, items=[])
    if promedio is not None and (isinstance(promedio, bool) or not isinstance(promedio, (float, int))
                                 or not math.isfinite(promedio) or not 1 <= promedio <= 5):
        raise _invalido('resenas.promedio')
    if total is not None:
        total = _entero(total, 'resenas.total', len(items), 1_000_000_000)
        if total == 0 and promedio is not None:
            raise _invalido('resenas.promedio')
    salida_items: list[Json] = []
    ids: set[str] = set()
    for item in items:
        r = _objeto(item, {'id', 'texto', 'estrellas', 'fecha', 'variante', 'compra_verificada', 'imagenes'},
                    'resenas.items')
        rid = r.get('id')
        if not isinstance(rid, str) or _REVIEW_ID.fullmatch(rid) is None or rid in ids:
            raise _invalido('resenas.id')
        ids.add(rid)
        texto = _texto(r.get('texto', ''), 'resenas.texto', 5000, vacio=True)
        estrellas = r.get('estrellas')
        if estrellas is not None:
            estrellas = _entero(estrellas, 'resenas.estrellas', 1, 5)
        imagenes = _imagenes(r.get('imagenes', []), 'resenas.imagenes', MAX_IMAGENES_RESENA)
        if not texto and estrellas is None and not imagenes:
            raise _invalido('resenas.items')
        variante = r.get('variante')
        if variante is not None:
            variante = _texto(variante, 'resenas.variante', 200, vacio=True) or None
        verificada = r.get('compra_verificada')
        if verificada is not None and not isinstance(verificada, bool):
            raise _invalido('resenas.compra_verificada')
        salida_items.append({'id': rid, 'texto': texto, 'estrellas': estrellas,
                             'fecha': _epoch(r.get('fecha'), 'resenas.fecha', ahora, opcional=True),
                             'variante': variante, 'compra_verificada': verificada, 'imagenes': imagenes})
    return dict(salida, promedio=promedio, total=total, items=salida_items)


def _json(datos: Any) -> str:
    return json.dumps(datos, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _validar(datos: Any, pid: str, ahora: int) -> tuple[int, Json]:
    d = _objeto(datos, {'rev', 'tabla_tallas', 'resenas'}, 'evidencia')
    rev = _entero(d.get('rev'), 'rev', 0, 2**53 - 1)
    if not {'tabla_tallas', 'resenas'} & set(d):
        raise _invalido('evidencia', 'Incluye una tabla de tallas o las reseñas del producto.')
    bloques = {}
    for clave, validar in (('tabla_tallas', _tabla), ('resenas', _resenas)):
        if clave in d:
            bloques[clave] = validar(d[clave], pid, ahora)
    if len(_json(bloques).encode('utf-8')) > MAX_DOCUMENTO_BYTES:
        raise ErrorDominio('cuerpo_demasiado_grande', 'La evidencia supera el límite permitido.', http=413)
    return rev, bloques


def _producto_existe(conn: sqlite3.Connection, pid: str) -> None:
    fila = conn.execute('SELECT 1 FROM productos WHERE product_id=? UNION ALL SELECT 1 FROM vitrina '
                        'WHERE product_id=? UNION ALL SELECT 1 FROM muestras WHERE product_id=? UNION ALL '
                        'SELECT 1 FROM orden_lineas WHERE product_id=? UNION ALL SELECT 1 FROM solicitudes_recuperadas '
                        "WHERE product_id=? AND estado='ok' LIMIT 1", (pid,) * 5).fetchone()
    if fila is None:
        raise ErrorDominio('no_encontrado', 'No encontramos ese producto en tu catálogo.', http=404)


def referencia_imagen(pid: str, url: str, review_id: str = '') -> str:
    """La firma CDN puede renovarse sin cambiar la identidad de la foto o mezclar reseñas."""
    producto_id(pid)
    if imagen_claves.url_permitida(url) is None:
        raise _invalido('imagenes')
    parsed = urllib.parse.urlsplit(url)
    canon = (parsed.hostname or '').lower() + parsed.path
    huella = hashlib.sha256((review_id + '\0' + canon).encode('utf-8')).hexdigest()[:16]
    return f'{pid}-{huella}'


def _pedidos(pid: str, datos: Json) -> list[PedidoImagen]:
    pedidos: dict[str, PedidoImagen] = {}
    tabla = (datos.get('tabla_tallas') or {}).get('tabla') or {}
    for url in tabla.get('imagenes') or []:
        ref = referencia_imagen(pid, url, 'tabla')
        pedidos[ref] = PedidoImagen('e', ref, url, 1, 'evidencia')
    for resena in (datos.get('resenas') or {}).get('items') or []:
        for url in resena.get('imagenes') or []:
            ref = referencia_imagen(pid, url, resena['id'])
            pedidos[ref] = PedidoImagen('e', ref, url, 1, 'evidencia')
    return list(pedidos.values())


def leer_evidencia(conn: sqlite3.Connection, img: Any, pid: str, cursor: int = 0) -> Json:
    """Lectura en la transacción de Vista; nunca devuelve URLs de fotografías de origen."""
    fila = conn.execute('SELECT evidencia_json,rev,actualizado_at FROM producto_evidencia WHERE product_id=?',
                        (pid,)).fetchone()
    datos = json.loads(fila['evidencia_json']) if fila else {}
    pedidos = _pedidos(pid, datos)
    img.cargar([f'e:{p.ref_id}' for p in pedidos])

    def fotos(urls: list[str], rid: str) -> list[str]:
        return [proxy for url in urls
                if (proxy := img.url('e', referencia_imagen(pid, url, rid))) is not None]

    tabla = datos.get('tabla_tallas')
    if tabla is not None and tabla.get('tabla') is not None:
        t = tabla['tabla']
        tabla = dict(tabla, tabla=dict(t, imagenes=fotos(t['imagenes'], 'tabla')))
    resenas = datos.get('resenas')
    if resenas is not None:
        items = resenas['items']
        pagina = [dict(r, imagenes=fotos(r['imagenes'], r['id']))
                  for r in items[cursor:cursor + PAGINA_RESENAS]]
        resenas = dict(resenas, items=pagina, cargadas=len(items),
                       siguiente_cursor=str(cursor + PAGINA_RESENAS)
                       if cursor + PAGINA_RESENAS < len(items) else None)
    return {'product_id': pid, 'rev': fila['rev'] if fila else 0,
            'actualizado_at': fila['actualizado_at'] if fila else None,
            'tabla_tallas': tabla, 'resenas': resenas}


class ServicioEvidencia:
    """Evidencia con revisión optimista; sólo extraer() llama al lector de HTML público."""

    def __init__(self, almacen: Almacen, imagenes: Imagenes, bus: Bus, reloj: Reloj,
                 candado: threading.RLock | None = None) -> None:
        self.almacen, self.imagenes, self.bus, self.reloj = almacen, imagenes, bus, reloj
        self._candado = candado

    def leer(self, product_id: str) -> Json:
        from .analitica.imagenes import ResolutorImagenes
        pid = producto_id(product_id)
        with self.almacen.lector() as conn:
            _producto_existe(conn, pid)
            img = ResolutorImagenes(conn)
            respuesta = leer_evidencia(conn, img, pid)
            respuesta['meta_imagenes'] = img.meta_para(respuesta)
            return respuesta

    def resenas(self, product_id: str, query: Mapping[str, str]) -> Json:
        from .analitica.imagenes import ResolutorImagenes
        pid = producto_id(product_id)
        if set(query) - {'cursor'}:
            raise _invalido('cursor')
        raw = query.get('cursor', '0')
        if (not isinstance(raw, str) or re.fullmatch(r'[0-9]{1,3}', raw) is None
                or int(raw) > MAX_RESENAS or int(raw) % PAGINA_RESENAS):
            raise _invalido('cursor')
        with self.almacen.lector() as conn:
            _producto_existe(conn, pid)
            img = ResolutorImagenes(conn)
            evidencia = leer_evidencia(conn, img, pid, int(raw))
            respuesta = {k: evidencia[k] for k in ('product_id', 'rev', 'resenas')}
            respuesta['meta_imagenes'] = img.meta_para(respuesta)
            return respuesta

    def extraer(self, product_id: str, datos: Json, ctx: Contexto) -> Json:
        """Lee únicamente HTML público; la revisión se comprueba antes y después de la red."""
        if not ctx.puede_escribir:
            raise ErrorDominio('prohibido', 'Este dispositivo tiene permiso de lectura.', http=403)
        pid = producto_id(product_id)
        d = _objeto(datos, {'rev'}, 'extraccion')
        rev = _entero(d.get('rev'), 'rev', 0, 2**53 - 1)
        epoca = self.almacen.epoca()
        # El mismo candado de mutacion_segura mantiene ligada la captura al creador.
        # guardar() lo vuelve a adquirir: el candado del Hub es reentrante.
        with self._candado if self._candado is not None else contextlib.nullcontext():
            with self.almacen.lector() as conn:
                _producto_existe(conn, pid)
                if conn.execute("SELECT valor FROM meta WHERE clave='epoca_datos'").fetchone()[0] != str(epoca):
                    raise ErrorDominio('cuenta_cambio_sin_aplicar', 'La cuenta cambió. Actualiza la ficha.', http=409)
                fila = conn.execute('SELECT rev FROM producto_evidencia WHERE product_id=?', (pid,)).fetchone()
                if rev != (fila['rev'] if fila else 0):
                    from .analitica.imagenes import ResolutorImagenes
                    actual = leer_evidencia(conn, ResolutorImagenes(conn), pid)
                    raise ErrorDominio('conflicto', 'La información del producto cambió. Revisa la versión guardada.',
                                       http=409, vigente=actual)
            # No hay conexiones en transacción durante la petición externa. El adaptador
            # limita la lectura a 15 s, no usa cookies y rechaza verificaciones interactivas.
            from .productos_publicos import obtener_producto_publico
            try:
                bloques = obtener_producto_publico(pid, self.reloj.ahora())
            except ErrorDominio as exc:
                codigo = exc.codigo if exc.codigo in _ERRORES_FUENTE else 'fuente_no_disponible'
                raise ErrorDominio(codigo, _ERRORES_FUENTE[codigo], http=503) from None
            except Exception as exc:
                _log.warning('No se pudo consultar la evidencia pública (%s)', type(exc).__name__)
                raise ErrorDominio('fuente_no_disponible', _ERRORES_FUENTE['fuente_no_disponible'], http=503) from None
            try:
                bloques = _objeto(bloques, {'tabla_tallas', 'resenas'}, 'extraccion')
                # Que una sección ya no sea accesible en el HTML no demuestra
                # que su contenido anterior haya desaparecido. La captura sólo
                # reemplaza bloques efectivamente obtenidos; guardar conserva
                # los omitidos. Cero reseñas exige un bloque disponible total=0.
                bloques = {clave: bloque for clave, bloque in bloques.items()
                           if isinstance(bloque, dict) and bloque.get('estado') == 'disponible'}
                if not bloques:
                    raise ErrorDominio('fuente_sin_datos', _ERRORES_FUENTE['fuente_sin_datos'], http=503)
                documento = {'rev': rev, **bloques}
                _validar(documento, pid, self.reloj.ahora())
            except ErrorDominio as exc:
                if exc.codigo == 'fuente_sin_datos':
                    raise
                raise ErrorDominio('fuente_respuesta_invalida', _ERRORES_FUENTE['fuente_respuesta_invalida'],
                                   http=503) from None
            except (TypeError, ValueError):
                raise ErrorDominio('fuente_respuesta_invalida', _ERRORES_FUENTE['fuente_respuesta_invalida'],
                                   http=503) from None
            # Una edición concurrente posterior al preflight produce 409; nunca se
            # sobrescribe silenciosamente una tabla o una reseña anterior.
            return self.guardar(pid, documento, ctx)

    def guardar(self, product_id: str, datos: Json, ctx: Contexto) -> Json:
        if not ctx.puede_escribir:
            raise ErrorDominio('prohibido', 'Este dispositivo tiene permiso de lectura.', http=403)
        pid = producto_id(product_id)
        epoca = self.almacen.epoca()
        ahora = self.reloj.ahora()
        rev, cambios = _validar(datos, pid, ahora)
        versiones = None
        with self._candado if self._candado is not None else contextlib.nullcontext():
            with self.almacen.escritor(epoca) as conn:
                _producto_existe(conn, pid)
                fila = conn.execute('SELECT evidencia_json,rev FROM producto_evidencia WHERE product_id=?',
                                    (pid,)).fetchone()
                vigente = fila['rev'] if fila else 0
                if rev != vigente:
                    from .analitica.imagenes import ResolutorImagenes
                    actual = leer_evidencia(conn, ResolutorImagenes(conn), pid)
                    raise ErrorDominio('conflicto', 'La información del producto cambió. Revisa la versión guardada.',
                                       http=409, vigente=actual)
                completo = dict(json.loads(fila['evidencia_json']) if fila else {}, **cambios)
                encoded = _json(completo)
                if len(encoded.encode('utf-8')) > MAX_DOCUMENTO_BYTES:
                    raise ErrorDominio('cuerpo_demasiado_grande', 'La evidencia supera el límite permitido.', http=413)
                if fila is None or encoded != fila['evidencia_json']:
                    conn.execute('INSERT INTO producto_evidencia(product_id,evidencia_json,rev,actualizado_at) '
                                 'VALUES(?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET '
                                 'evidencia_json=excluded.evidencia_json,rev=excluded.rev,actualizado_at=excluded.actualizado_at',
                                 (pid, encoded, vigente + 1, ahora))
                    self.almacen.subir_local_rev(conn)
                    versiones = self.almacen.versiones(conn)
            # encolar abre su propia transacción: jamás dentro del escritor anterior.
            # El candado compartido con mutacion_segura impide insertar fotos de una cuenta recién desconectada.
            imagenes_pendientes = False
            try:
                self.imagenes.encolar(_pedidos(pid, completo))
            except Exception as exc:
                # La evidencia ya está confirmada. Un fallo de la cola no debe
                # comunicar que no se guardó ni obligar a sobrescribir otra revisión.
                imagenes_pendientes = True
                _log.warning('La evidencia se guardó; no se pudo preparar la cola de imágenes (%s)',
                             type(exc).__name__)
            respuesta = self.leer(pid)
            respuesta['imagenes_pendientes'] = imagenes_pendientes
            if imagenes_pendientes:
                respuesta['aviso'] = ('La información se guardó. Las imágenes están pendientes; '
                                      'puedes volver a intentar la importación con la revisión actual.')
        if versiones is not None:
            try:
                self.bus.notificar_cambio(versiones, ['productos', 'muestras'])
            except Exception:
                _log.exception('No se pudo notificar la evidencia guardada')
        return respuesta
