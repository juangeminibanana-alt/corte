"""Comportamiento durable del envío de un video. Sólo bases SQLite temporales."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'hub'))

from creatorhub.almacen import USER_VERSION, crear_almacen
from creatorhub.errores import ErrorApi, ErrorDominio
from creatorhub.interfaces import ContextoSync
from creatorhub.tiktok.registro_publicacion import RegistroPublicacion


class RegistroPublicacionTests(unittest.TestCase):
    def setUp(self):
        temporal = tempfile.TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        self.ruta = str(Path(temporal.name) / 'hub.sqlite')
        self.reloj = SimpleNamespace(ahora=lambda: 123456)
        self.db = crear_almacen(self.ruta, self.reloj)
        self.addCleanup(lambda: self.db.cerrar())
        self.registro = RegistroPublicacion(self.db, self.reloj.ahora)
        self.ctx = ContextoSync(None, 'creador-de-prueba', 1, self.db.epoca())
        self.datos = {'file_id': 'archivo', 'titulo': 'Abrigo'}

    def test_reserva_atomica_sobrevive_reinicio_y_recupera_aceptacion(self):
        barrera = threading.Barrier(2)

        def reservar():
            barrera.wait(timeout=5)
            try:
                return self.registro.iniciar(self.ctx, 'archivo', self.datos)
            except ErrorDominio as error:
                return error.http

        with ThreadPoolExecutor(2) as pool:
            resultados = list(pool.map(lambda _: reservar(), range(2)))
        self.assertCountEqual(resultados, [None, 409])
        self.db.cerrar()
        self.db = crear_almacen(self.ruta, self.reloj)
        registro = RegistroPublicacion(self.db, self.reloj.ahora)
        with self.assertRaises(ErrorDominio):
            registro.iniciar(self.ctx, 'archivo', self.datos)
        confirmado = {'video_id': '123', 'estado': 'aceptada'}
        registro.confirmar(self.ctx, 'archivo', confirmado)
        self.assertEqual(registro.iniciar(self.ctx, 'archivo', dict(reversed(self.datos.items()))), confirmado)
        with self.assertRaises(ErrorDominio):
            registro.iniciar(self.ctx, 'archivo', {**self.datos, 'titulo': 'Otro'})
        otra = ContextoSync(None, 'otra-cuenta', 1, self.db.epoca())
        self.assertIsNone(registro.iniciar(otra, 'archivo', self.datos))

    def test_liberacion_previa_al_envio_solo_para_la_misma_solicitud_pendiente(self):
        self.registro.iniciar(self.ctx, 'archivo', self.datos)
        self.registro.liberar_sin_envio(self.ctx, 'archivo', {**self.datos, 'titulo': 'Otra prenda'})
        with self.assertRaises(ErrorDominio):
            self.registro.iniciar(self.ctx, 'archivo', self.datos)
        self.registro.liberar_sin_envio(self.ctx, 'archivo', self.datos)
        self.assertIsNone(self.registro.iniciar(self.ctx, 'archivo', self.datos))
        confirmado = {'video_id': '123', 'estado': 'aceptada'}
        self.registro.confirmar(self.ctx, 'archivo', confirmado)
        self.registro.liberar_sin_envio(self.ctx, 'archivo', self.datos)
        self.assertEqual(self.registro.iniciar(self.ctx, 'archivo', self.datos), confirmado)

    def test_migracion_v7_y_borrado_de_datos_tiktok(self):
        self.db.cerrar()
        with sqlite3.connect(self.ruta) as conexion:
            conexion.execute('DROP TABLE publicaciones_shop')
            conexion.execute('PRAGMA user_version=7')
        conexion.close()
        self.db = crear_almacen(self.ruta, self.reloj)
        registro = RegistroPublicacion(self.db, self.reloj.ahora)
        self.assertTrue(Path(self.ruta + '.bak-v7').is_file())
        self.assertIsNone(registro.iniciar(self.ctx, 'archivo', self.datos))
        with self.db.lector() as conexion:
            self.assertEqual(conexion.execute('PRAGMA user_version').fetchone()[0], USER_VERSION)
        self.db.borrar('tiktok')
        with self.assertRaises(ErrorApi):
            registro.confirmar(self.ctx, 'archivo', {'video_id': '1'})
        with self.db.lector() as conexion:
            self.assertEqual(conexion.execute('SELECT count(*) FROM publicaciones_shop').fetchone()[0], 0)
