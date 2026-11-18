"""Imagen de vuelta atrás de la rev. 7 (rama claude/corte-vuelta-atras-rev6, docs/ORDER_TRACE_RETIREMENT.md etapa 2).

La rev. 7 solo agrega `orden_lineas_traza` y sube user_version a 7. Este código (la rev. 6 que está en producción más un
paso) debe arrancar con esa base: copiarla a .bak-v7, quitar la tabla y regresar a 6 sin tocar nada más. Si la base trae
cualquier otra diferencia, no se toca y se abre en solo lectura como siempre. Datos sintéticos; sin red.
"""
from __future__ import annotations

import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'hub'))

from creatorhub.almacen import crear_almacen
from creatorhub.hub import iniciar_hub
from creatorhub.imagenes.claves import ErrorImagen
from creatorhub.interfaces import OpcionesHub

# = hub/creatorhub/almacen/migraciones/007.sql de la rev. 7 (sin sus comentarios).
DDL_REV7 = """CREATE TABLE IF NOT EXISTS orden_lineas_traza (
  order_id     TEXT NOT NULL,
  linea_n      INTEGER NOT NULL,
  traza_tipo   TEXT,
  capturada_at INTEGER NOT NULL,
  PRIMARY KEY (order_id, linea_n),
  FOREIGN KEY (order_id, linea_n) REFERENCES orden_lineas(order_id, linea_n) ON DELETE CASCADE
) STRICT"""
RELOJ = SimpleNamespace(ahora=lambda: 1_800_000_000)
LOCALES = frozenset({None, '', 'localhost', '127.0.0.1', '::1', '0.0.0.0'})


def base_rev7(ruta: Path, extra: str | None = None, sin: str | None = None) -> None:
    """Una base rev. 6 real (con sus semillas de meta) llevada a la rev. 7 como lo hace migraciones/007.sql."""
    crear_almacen(str(ruta), RELOJ).cerrar()
    db = sqlite3.connect(ruta)
    db.execute(DDL_REV7)
    if extra:
        db.execute(extra)
    if sin:
        db.execute(f'DROP TABLE {sin}')
    db.execute("INSERT INTO ordenes(order_id, creada_at, estado, huella, actualizado_at) "
               "VALUES ('O1', 1800000000, 'SETTLED', 'h', 1800000000)")
    db.executemany('INSERT INTO orden_lineas(order_id, linea_n, product_id, cantidad) VALUES (?,?,?,?)',
                   [('O1', 0, 'P1', 1), ('O1', 1, 'P1', 2)])
    db.executemany('INSERT INTO orden_lineas_traza VALUES (?,?,?,?)', [('O1', 0, 'GENERAL', 1), ('O1', 1, None, 1)])
    db.execute("INSERT INTO notas(id,entidad,entidad_id,texto,creado_at,actualizado_at) "
               "VALUES('n1','producto','P1','Nota sintética',1800000000,1800000000)")
    db.execute('PRAGMA user_version = 7')
    db.commit()
    db.close()


def tablas(ruta: str) -> set[str]:
    db = sqlite3.connect(ruta)
    try:
        return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        db.close()


def esquema(ruta: Path) -> list[tuple]:
    db = sqlite3.connect(ruta)
    try:
        return sorted(db.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
    finally:
        db.close()


class VueltaAtrasTests(unittest.TestCase):
    def test_regresa_a_la_rev_6_sin_perder_nada_mas(self) -> None:
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / 'hub.sqlite'
            base_rev7(ruta)
            almacen = crear_almacen(str(ruta), RELOJ)
            try:
                self.assertFalse(almacen.solo_lectura())
                with almacen.lector() as db:
                    self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 6)
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM orden_lineas').fetchone()[0], 2)
                    self.assertEqual(db.execute('SELECT texto FROM notas').fetchone()[0], 'Nota sintética')
                    self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='orden_lineas_traza'").fetchone())
                    self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
                with almacen.escritor() as db:                      # se puede escribir: no quedó en solo lectura
                    db.execute("UPDATE notas SET texto='Editada' WHERE id='n1'")
            finally:
                almacen.cerrar()
            copia = str(ruta) + '.bak-v7'
            self.assertTrue(os.path.isfile(copia))
            self.assertIn('orden_lineas_traza', tablas(copia))     # la copia previa conserva la base tal cual
            nueva = Path(carpeta) / 'nueva.sqlite'                  # y el esquema queda idéntico al de una rev. 6 nueva
            crear_almacen(str(nueva), RELOJ).cerrar()
            self.assertEqual(esquema(ruta), esquema(nueva))
            # Abrirla otra vez no hace nada más (ya es la rev. 6).
            os.remove(copia)
            crear_almacen(str(ruta), RELOJ).cerrar()
            self.assertFalse(os.path.exists(copia))

    def test_con_otra_diferencia_no_toca_la_base(self) -> None:
        casos = {'tabla de más': {'extra': 'CREATE TABLE otra_rev7 (x INTEGER)'},
                 'tabla de menos': {'sin': 'parecidos_consultas'}}
        for nombre, cambio in casos.items():
            with self.subTest(caso=nombre), tempfile.TemporaryDirectory() as carpeta:
                ruta = Path(carpeta) / 'hub.sqlite'
                base_rev7(ruta, **cambio)
                almacen = crear_almacen(str(ruta), RELOJ)
                try:
                    self.assertTrue(almacen.solo_lectura())
                finally:
                    almacen.cerrar()
                self.assertIn('orden_lineas_traza', tablas(str(ruta)))
                self.assertFalse(os.path.exists(str(ruta) + '.bak-v7'))
                db = sqlite3.connect(ruta)
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 7)
                db.close()

    def test_el_hub_arranca_con_una_base_de_la_rev_7(self) -> None:
        intentos: list[str] = []
        real = socket.getaddrinfo

        def resolver(host, *args, **kwargs):
            if host not in LOCALES:
                intentos.append(str(host))
                raise OSError('Red bloqueada en las pruebas')
            return real(host, *args, **kwargs)

        def sin_red(url: str) -> bytes:
            raise ErrorImagen('sin_red_en_pruebas', permanente=True)
        with tempfile.TemporaryDirectory() as carpeta, patch('socket.getaddrinfo', resolver), \
                patch.dict(os.environ, {'CORTE_PUBLIC_URL': 'https://corte.example',
                                        'CORTE_ENCRYPTION_KEY': 'synthetic-master-' * 4}), \
                patch('creatorhub.imagenes.servicio.DescargadorHttps', return_value=sin_red):
            datos = Path(carpeta) / 'datos'
            datos.mkdir()
            base_rev7(datos / 'hub.sqlite')
            hub = iniciar_hub(OpcionesHub(modo='real', nube=True, sin_lan=True, raiz_datos=carpeta,
                                          sync_al_iniciar=False))
            try:
                self.assertFalse(hub.almacen.solo_lectura())
                with hub.almacen.lector() as db:
                    self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 6)
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM orden_lineas').fetchone()[0], 2)
            finally:
                hub.detener(10)
        self.assertEqual(intentos, [])


if __name__ == '__main__':
    unittest.main()
