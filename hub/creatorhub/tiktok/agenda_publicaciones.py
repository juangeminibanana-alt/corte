"""Agenda de videos comprables. El tic del hub sólo envía planes confirmados del creador activo."""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Callable

from ..errores import ErrorDominio
from ..interfaces import Almacen, Json
from .publicaciones import PublicacionesShop
from .registro_publicacion import huella

# Si el proceso terminó entre la reserva y su desenlace, el siguiente trabajador consulta la
# misma operación idempotente. Un resultado remoto desconocido siempre conserva la reserva.
RECUPERAR_TRAS_S = 5 * 60
REVISAR = 'Comprueba en la cuenta de TikTok Shop si el video se publicó.'


def _vista(fila: sqlite3.Row) -> Json:
    datos = json.loads(fila['datos_json'])
    res = {k: fila[k] for k in ('id', 'estado', 'programada_at')}
    res.update({k: datos[k] for k in ('titulo', 'titulo_ancla', 'product_id')})
    for campo in ('video_id', 'mensaje'):
        if fila[campo]:
            res[campo] = fila[campo]
    return res


class AgendaPublicaciones:
    def __init__(self, servicio: PublicacionesShop, almacen: Almacen, ahora: Callable[[], int]) -> None:
        self.servicio = servicio
        self.almacen = almacen
        self.ahora = ahora

    def listar(self) -> Json:
        ctx = self.servicio.contexto(requerir_permiso=False)
        with self.almacen.lector() as db:
            filas = db.execute("SELECT * FROM agenda_publicaciones_shop WHERE cuenta_sha256=? "
                               "ORDER BY estado NOT IN ('programada','enviando'), "
                               "CASE WHEN estado IN ('programada','enviando') THEN programada_at ELSE -programada_at END, id",
                               (huella(ctx.open_id),))
            return {'items': [_vista(fila) for fila in filas]}

    def programar(self, body: Json) -> Json:
        if body.get('confirmar') is not True:
            raise ErrorDominio('parametros_invalidos', 'Confirma que quieres publicar este video a la hora indicada.', http=400)
        fecha = body.get('programada_at')
        if type(fecha) is not int or not 0 < fecha <= 253402300799:
            raise ErrorDominio('parametros_invalidos', 'Selecciona una fecha y una hora válidas.', http=400)
        ctx = self.servicio.contexto()
        entrada = {k: v for k, v in body.items() if k not in ('confirmar', 'programada_at')}
        payload = self.servicio.preparar(entrada)['payload']
        # Guardar la etiqueta normalizada que revisó el usuario y retirar el identificador al terminar.
        archivo = entrada.pop('file_id')
        entrada['titulo_ancla'] = payload['product_link_info']['title']
        datos = json.dumps(entrada, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        claves = (huella(ctx.open_id), huella(archivo))
        ahora = self.ahora()
        with self.almacen.escritor(ctx.epoca_datos) as db:
            anterior = db.execute('SELECT * FROM agenda_publicaciones_shop WHERE cuenta_sha256=? AND archivo_sha256=? '
                                  'ORDER BY rowid DESC LIMIT 1', claves).fetchone()
            if anterior and anterior['programada_at'] == fecha and anterior['datos_json'] == datos:
                return _vista(anterior)
            if anterior and anterior['estado'] not in ('cancelada', 'fallida'):
                raise ErrorDominio('conflicto', 'Este archivo ya tiene un envío. Revisa tu agenda.', http=409)
            if db.execute('SELECT 1 FROM publicaciones_shop WHERE cuenta_sha256=? AND archivo_sha256=?', claves).fetchone():
                raise ErrorDominio('conflicto', 'Este archivo ya se envió. Revisa tus videos en TikTok Shop.', http=409)
            if fecha <= ahora:
                raise ErrorDominio('parametros_invalidos', 'Selecciona una hora futura para publicar.', http=400)
            identificador = uuid.uuid4().hex
            fila = db.execute("INSERT INTO agenda_publicaciones_shop "
                              "(id,cuenta_sha256,archivo_sha256,file_id,datos_json,programada_at,consentida_at,estado) "
                              "VALUES (?,?,?,?,?,?,?,'programada') RETURNING *",
                              (identificador, *claves, archivo, datos, fecha, ahora)).fetchone()
            return _vista(fila)

    def cancelar(self, identificador: str, body: Json) -> Json:
        if body:
            raise ErrorDominio('parametros_invalidos', 'La cancelación se envía sin parámetros.', http=400)
        ctx = self.servicio.contexto(requerir_permiso=False)
        claves = (identificador, huella(ctx.open_id))
        with self.almacen.escritor(ctx.epoca_datos) as db:
            fila = db.execute('SELECT * FROM agenda_publicaciones_shop WHERE id=? AND cuenta_sha256=?', claves).fetchone()
            if fila is None:
                raise ErrorDominio('no_encontrado', 'No se encontró ese video en la agenda.', http=404)
            if fila['estado'] == 'cancelada':
                return _vista(fila)
            if fila['estado'] != 'programada':
                raise ErrorDominio('conflicto', 'El envío ya empezó o terminó. Revisa su estado en la agenda.', http=409)
            fila = db.execute("UPDATE agenda_publicaciones_shop SET estado='cancelada', file_id=NULL "
                              "WHERE id=? AND cuenta_sha256=? RETURNING *", claves).fetchone()
            return _vista(fila)

    def ejecutar_siguiente(self) -> None:
        """Procesa el primer video vencido. El planificador llama bajo el candado de cambio de cuenta."""
        try:
            ctx = self.servicio.contexto(requerir_permiso=False)
        except ErrorDominio as error:
            if error.codigo in ('sin_credenciales', 'sin_permiso_tiktok'):
                return
            raise
        cuenta = huella(ctx.open_id)
        ahora = self.ahora()
        turno = uuid.uuid4().hex
        with self.almacen.escritor(ctx.epoca_datos) as db:
            fila = db.execute("UPDATE agenda_publicaciones_shop SET estado='enviando', intento=?, intento_at=? "
                              "WHERE id=(SELECT id FROM agenda_publicaciones_shop WHERE cuenta_sha256=? AND "
                              "((estado='programada' AND programada_at<=?) OR (estado='enviando' AND intento_at<=?)) "
                              "ORDER BY programada_at, id LIMIT 1) RETURNING *",
                              (turno, ahora, cuenta, ahora, ahora - RECUPERAR_TRAS_S)).fetchone()
        if fila is None:
            return
        solicitud = {**json.loads(fila['datos_json']), 'file_id': fila['file_id']}
        video_id = None
        mensaje = None
        try:
            resultado = self.servicio.recuperar_envio(ctx, solicitud)
            if resultado is None:
                resultado = self.servicio.publicar({**solicitud, 'confirmar': True}, contexto_esperado=ctx)
            estado, video_id = 'aceptada', resultado['video_id']
        except ErrorDominio as error:
            if error.codigo in ('conflicto', 'publicacion_sin_confirmar'):
                estado, mensaje = 'por_verificar', REVISAR
            else:
                estado, mensaje = 'fallida', error.mensaje
        with self.almacen.escritor(ctx.epoca_datos) as db:
            db.execute("UPDATE agenda_publicaciones_shop SET estado=?, video_id=?, mensaje=?, file_id=NULL, intento=NULL "
                       "WHERE id=? AND cuenta_sha256=? AND (intento=? OR (estado='por_verificar' AND ?='aceptada'))",
                       (estado, video_id, mensaje, fila['id'], cuenta, turno, estado))
