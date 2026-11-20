"""Reserva durable del file_id de Shop antes de enviar la petición a TikTok."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Callable

from ..errores import ErrorDominio
from ..interfaces import Almacen, ContextoSync, Json


def huella(texto: str) -> str:
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()


def _huella_solicitud(payload: Json) -> str:
    return huella(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')))


def _claves(ctx: ContextoSync, file_id: str) -> tuple[str, str]:
    if not ctx.open_id:
        raise ErrorDominio('sin_credenciales', 'Conecta tu cuenta de TikTok Shop.', http=409)
    return huella(ctx.open_id), huella(file_id)


class RegistroPublicacion:
    def __init__(self, almacen: Almacen, ahora: Callable[[], int]) -> None:
        self._almacen = almacen
        self._ahora = ahora

    @staticmethod
    def _resultado(fila: sqlite3.Row, solicitud: str) -> Json:
        if fila[0] != solicitud:
            raise ErrorDominio('conflicto', 'Ya se solicitó publicar ese archivo con otros datos.', http=409)
        if fila[1] is None:
            raise ErrorDominio('conflicto', 'Ya hay un envío de ese archivo. Comprueba el resultado en TikTok Shop.',
                               http=409)
        return json.loads(fila[1])

    def recuperar(self, ctx: ContextoSync, file_id: str, payload: Json) -> Json | None:
        with self._almacen.lector() as db:
            fila = db.execute('SELECT solicitud_sha256, resultado_json FROM publicaciones_shop '
                              'WHERE cuenta_sha256=? AND archivo_sha256=?', _claves(ctx, file_id)).fetchone()
            return self._resultado(fila, _huella_solicitud(payload)) if fila is not None else None

    def iniciar(self, ctx: ContextoSync, file_id: str, payload: Json) -> Json | None:
        claves = _claves(ctx, file_id)
        huella = _huella_solicitud(payload)
        # BEGIN IMMEDIATE serializa también dos procesos que comparten la base.
        with self._almacen.escritor(ctx.epoca_datos) as db:
            fila = db.execute('SELECT solicitud_sha256, resultado_json FROM publicaciones_shop '
                              'WHERE cuenta_sha256=? AND archivo_sha256=?', claves).fetchone()
            if fila is None:
                db.execute('INSERT INTO publicaciones_shop '
                           '(cuenta_sha256, archivo_sha256, solicitud_sha256, iniciado_at) VALUES (?, ?, ?, ?)',
                           (*claves, huella, self._ahora()))
                return None
            return self._resultado(fila, huella)

    def liberar_sin_envio(self, ctx: ContextoSync, file_id: str, payload: Json) -> None:
        """La operación sólo se libera si el cliente acredita que no inició el envío HTTP."""
        claves = _claves(ctx, file_id)
        with self._almacen.escritor(ctx.epoca_datos) as db:
            db.execute('DELETE FROM publicaciones_shop WHERE cuenta_sha256=? AND archivo_sha256=? '
                       'AND solicitud_sha256=? AND resultado_json IS NULL', (*claves, _huella_solicitud(payload)))

    def confirmar(self, ctx: ContextoSync, file_id: str, resultado: Json) -> None:
        claves = _claves(ctx, file_id)
        with self._almacen.escritor(ctx.epoca_datos) as db:
            actualizadas = db.execute('UPDATE publicaciones_shop SET resultado_json=? '
                                      'WHERE cuenta_sha256=? AND archivo_sha256=? AND resultado_json IS NULL',
                                      (json.dumps(resultado, ensure_ascii=False), *claves)).rowcount
            if actualizadas != 1:
                raise ErrorDominio('conflicto', 'Cambió el registro del envío. Comprueba el video en TikTok Shop.',
                                   http=409)
