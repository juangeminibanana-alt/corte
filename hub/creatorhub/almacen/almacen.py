"""Almacén SQLite del hub (BUILD_SPEC §4.3, §6.2 `Almacen`; 03 §2.6, §3.2–§3.4).

- Abre la base con los PRAGMA de siempre (WAL, foreign_keys, synchronous=NORMAL, busy_timeout) y mira `user_version`:
  0 → `schema.sql` (rev. 7, user_version 7) + semillas de `meta`; 1…6 → `migraciones/00{n+1}.sql` … `007.sql` en UNA
  transacción con copia previa `hub.sqlite.bak-v{n}` (3 = las bases de Corte 1.0.0: 004.sql reconstruye `imagenes`
  copiando todas sus filas y agrega lo de la ficha completa de producto; 4 = rev. 4: 005.sql solo crea las tablas de la
  Display API); 5 → 006.sql conserva imágenes y añade evidencia de producto; 6 → 007.sql solo agrega
  `orden_lineas_traza` (trace_info de orders/search 202410); 7 → nada; > 7 → solo lectura (`base_de_version_nueva`).
  Los .sql se leen con importlib.resources (también dentro del exe). La línea «Base migrada…» también va a stderr: en la
  nube, el registro del hub vive en el disco de la VM y solo la salida del contenedor llega a Cloud Logging.
- NO siembra plantillas ni preferencias: eso lo hace solo `EstadoLocal.sembrar()` (BUILD §4.3).
- Un escritor: candado + `BEGIN IMMEDIATE` + comprobación de `meta.epoca_datos` (si cambió: ROLLBACK y
  ErrorApi('credenciales_cambiaron', decision='abortar')). Cuatro lectores `query_only` en una cola fija; cada `lector()`
  es una transacción de lectura (`BEGIN … COMMIT`), así las versiones y la respuesta salen del mismo instante.
- `data_version` sube por transacción CONFIRMADA con cambios: quien escribe marca `dv_pendiente` en su transacción y
  `confirmar_data_version()` (transacción propia) lo publica (03 §3.2). `local_rev` e `img_rev` suben dentro de la
  transacción de quien los cambia.
- `borrar(alcance)`: secuencia de 03 §3.4 (secure_delete, época += 1 y DELETE en un BEGIN IMMEDIATE, checkpoint, VACUUM,
  checkpoint, copias .bak fuera).
- `reparar_al_abrir`: syncs y pasos que quedaron 'en_curso' pasan a 'error/interrumpida' (sin tocar cursor_json: son
  reanudables) y se publica un dv_pendiente que haya quedado.
- `cerrar()`: espera la transacción en curso, `wal_checkpoint(TRUNCATE)` y cierra.
Nunca guarda secretos. Ninguna llamada de red ocurre aquí.
"""
from __future__ import annotations

import contextlib
import glob
import logging
import os
import queue
import re
import secrets
import sqlite3
import sys
import threading
import time
from importlib import resources
from typing import Iterator

from ..errores import ErrorApi, ErrorDominio
from ..interfaces import Alcance, Almacen, Reloj, Versiones

_log = logging.getLogger('creatorhub.almacen')

USER_VERSION = 7
PRAGMAS_APERTURA: tuple[str, ...] = ('journal_mode=WAL', 'foreign_keys=ON', 'synchronous=NORMAL', 'busy_timeout=5000')
TZ_OFFSET_S = -21600
SEMILLAS_META: tuple[tuple[str, str], ...] = (
    ('data_version', '0'), ('local_rev', '0'), ('img_rev', '0'), ('dv_pendiente', '0'), ('epoca_datos', '0'),
    ('tz_offset_s', str(TZ_OFFSET_S)))
LECTORES = 4
RETENCION_COPIAS_S = 7 * 86400

# Alcances de borrar() (03 §3.4). Orden: hijas antes que padres (claves foráneas).
TABLAS_TIKTOK: tuple[str, ...] = ('producto_evidencia', 'orden_lineas_traza', 'orden_lineas', 'ordenes', 'cumplimientos', 'muestras_historial', 'muestras', 'vitrina',
                                  'productos', 'videos', 'imagenes', 'tienda_alias', 'tiendas', 'cuenta', 'sync_cursores',
                                  # rev. 4 (ficha completa de producto): también vienen de TikTok y se borran igual
                                  'muestra_etiquetas', 'solicitudes_recuperadas', 'colaboraciones_dirigidas',
                                  'dirigidas_tiendas', 'productos_parecidos', 'parecidos_consultas', 'orden_trazas',
                                  # rev. 5 (métricas de tus videos con la Display API): también vienen de TikTok
                                  'videos_tiktok_dias', 'videos_tiktok', 'perfil_tiktok_dias', 'perfil_tiktok')
TABLAS_SYNC: tuple[str, ...] = ('api_errores', 'sync_pasos', 'sync_ejecuciones', 'oauth_states')
TABLAS_LOCALES: tuple[str, ...] = ('plan_videos', 'avisos_tienda', 'notas', 'recordatorios', 'ops_aplicadas', 'plantillas',
                                   'preferencias_sinc', 'preferencias', 'dispositivos', 'auth_estado')
CLAVES_META_BASE: frozenset[str] = frozenset({'host_id'} | {k for k, _ in SEMILLAS_META})

_RE_ADD_COLUMN = re.compile(r'^\s*ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)', re.IGNORECASE)
MENSAJE_VERSION_NUEVA = 'Esta base es de una versión más nueva de Corte. Actualiza Corte para seguir usándola.'


def leer_recurso_sql(nombre: str) -> str:
    """Texto de un .sql empaquetado en creatorhub.almacen ('schema.sql' o 'migraciones/002.sql')."""
    recurso = resources.files('creatorhub.almacen')
    for parte in nombre.split('/'):
        recurso = recurso / parte
    return recurso.read_text(encoding='utf-8')


def _sentencias(sql: str) -> list[str]:
    """Parte un guion SQL en sentencias completas (sin comentarios de línea sueltos)."""
    out, actual = [], ''
    for linea in sql.splitlines(keepends=True):
        if not actual and linea.strip().startswith('--'):
            continue
        actual += linea
        if sqlite3.complete_statement(actual):
            if actual.strip():
                out.append(actual.strip())
            actual = ''
    if actual.strip():
        raise ValueError('guion SQL incompleto')
    return out


def _conectar(ruta: str) -> sqlite3.Connection:
    c = sqlite3.connect(ruta, isolation_level=None, check_same_thread=False, timeout=5)
    c.row_factory = sqlite3.Row
    for pragma in PRAGMAS_APERTURA:
        c.execute(f'PRAGMA {pragma}')
    return c


def _meta_int(c: sqlite3.Connection, clave: str, omision: int = 0) -> int:
    r = c.execute('SELECT valor FROM meta WHERE clave=?', (clave,)).fetchone()
    return int(r[0]) if r is not None else omision


def _columnas(c: sqlite3.Connection, tabla: str) -> set[str]:
    return {r[1] for r in c.execute(f'PRAGMA table_info({tabla})')}       # tabla: de una regex \w+ sobre NUESTRO .sql


class _Almacen:
    """Implementa `Almacen` (interfaces.py)."""

    def __init__(self, ruta_db: str, reloj: Reloj, lectores: int = LECTORES) -> None:
        self.ruta = os.path.abspath(ruta_db)
        self._reloj = reloj
        os.makedirs(os.path.dirname(self.ruta), exist_ok=True)
        self._candado_w = threading.Lock()
        self._w = _conectar(self.ruta)
        self._todas: list[sqlite3.Connection] = [self._w]
        self._pool: queue.Queue[sqlite3.Connection] = queue.Queue()
        self._cerrado = False
        try:
            self.version_archivo = self._abrir_o_migrar()
            self._solo_lectura = self.version_archivo > USER_VERSION
            if self._solo_lectura:
                self._w.execute('PRAGMA query_only=ON')
                _log.warning('La base tiene user_version %d (> %d): se abre en solo lectura',
                             self.version_archivo, USER_VERSION)
            else:
                self.reparar_al_abrir()
                self._purgar_copias_viejas()
            for _ in range(max(1, lectores)):
                c = _conectar(self.ruta)
                c.execute('PRAGMA query_only=ON')
                self._todas.append(c)
                self._pool.put(c)
        except BaseException:
            for c in self._todas:
                with contextlib.suppress(sqlite3.Error):
                    c.close()
            raise

    # ------------------------------------------------------------------ apertura y migraciones
    def _abrir_o_migrar(self) -> int:
        w = self._w
        uv = w.execute('PRAGMA user_version').fetchone()[0]
        if uv == 0:
            self._crear(w)
            return USER_VERSION
        if uv < USER_VERSION:
            self._migrar(w, uv)
            return USER_VERSION
        return uv

    def _crear(self, w: sqlite3.Connection) -> None:
        sql = leer_recurso_sql('schema.sql')
        w.execute('BEGIN IMMEDIATE')
        try:
            for s in _sentencias(sql):
                w.execute(s)
            self._sembrar_meta(w)
            if w.execute('PRAGMA user_version').fetchone()[0] != USER_VERSION:
                raise RuntimeError(f'schema.sql no dejó user_version = {USER_VERSION}')
        except BaseException:
            w.execute('ROLLBACK')
            raise
        w.execute('COMMIT')
        _log.info('Base nueva creada (user_version %d)', USER_VERSION)

    @staticmethod
    def _sembrar_meta(w: sqlite3.Connection) -> None:
        w.execute('INSERT OR IGNORE INTO meta(clave, valor) VALUES (?, ?)', ('host_id', secrets.token_hex(16)))
        w.executemany('INSERT OR IGNORE INTO meta(clave, valor) VALUES (?, ?)', SEMILLAS_META)

    def _migrar(self, w: sqlite3.Connection, desde: int) -> None:
        copia = f'{self.ruta}.bak-v{desde}'
        with contextlib.suppress(FileNotFoundError):
            os.remove(copia)
        destino = sqlite3.connect(copia)
        try:
            w.backup(destino)
        finally:
            destino.close()
        w.execute('BEGIN IMMEDIATE')
        try:
            for n in range(desde + 1, USER_VERSION + 1):
                for s in _sentencias(leer_recurso_sql(f'migraciones/{n:03d}.sql')):
                    m = _RE_ADD_COLUMN.match(s)
                    if m and m.group(2) in _columnas(w, m.group(1)):
                        continue                        # base intermedia que ya la tenía
                    w.execute(s)
            self._sembrar_meta(w)
            if w.execute('PRAGMA user_version').fetchone()[0] != USER_VERSION:
                raise RuntimeError(f'las migraciones no dejaron user_version = {USER_VERSION}')
        except BaseException:
            w.execute('ROLLBACK')
            raise
        w.execute('COMMIT')
        _log.info('Base migrada de user_version %d a %d (copia previa: %s)', desde, USER_VERSION,
                  os.path.basename(copia))
        # También a stderr: en la nube es lo único que llega a Cloud Logging (el registro del hub vive en el disco).
        print(f'Corte: base migrada de user_version {desde} a {USER_VERSION} (copia previa: {os.path.basename(copia)})',
              file=sys.stderr, flush=True)

    def _purgar_copias_viejas(self) -> None:
        for p in glob.glob(glob.escape(self.ruta) + '.bak-v*'):
            with contextlib.suppress(OSError):
                if time.time() - os.path.getmtime(p) > RETENCION_COPIAS_S:
                    os.remove(p)

    def reparar_al_abrir(self) -> int | None:
        """Syncs/pasos 'en_curso' (se cerró la app o se apagó la PC) → 'error/interrumpida' (reanudables) y publica un
        dv_pendiente que haya quedado. Devuelve el data_version nuevo o None."""
        ahora = self._reloj.ahora()
        with self.escritor() as c:
            c.execute("UPDATE sync_ejecuciones SET estado='error', error_codigo='interrumpida', terminada_at=? "
                      "WHERE estado='en_curso'", (ahora,))
            c.execute("UPDATE sync_pasos SET estado='error', error_codigo='interrumpida', terminado_at=? "
                      "WHERE estado='en_curso'", (ahora,))
        return self.confirmar_data_version()

    # ------------------------------------------------------------------ transacciones
    @contextlib.contextmanager
    def lector(self) -> Iterator[sqlite3.Connection]:
        if self._cerrado:
            raise RuntimeError('el almacén está cerrado')
        c = self._pool.get(timeout=30)
        try:
            c.execute('BEGIN')
            ok = False
            try:
                yield c
                ok = True
            finally:
                c.execute('COMMIT' if ok else 'ROLLBACK')
        finally:
            self._pool.put(c)

    @contextlib.contextmanager
    def escritor(self, epoca: int | None = None) -> Iterator[sqlite3.Connection]:
        if self._solo_lectura_actual():
            raise ErrorDominio('base_de_version_nueva', MENSAJE_VERSION_NUEVA, http=409)
        with self._candado_w:
            if self._cerrado:
                raise RuntimeError('el almacén está cerrado')
            c = self._w
            c.execute('BEGIN IMMEDIATE')
            try:
                if epoca is not None and _meta_int(c, 'epoca_datos') != epoca:
                    raise ErrorApi('credenciales_cambiaron',
                                   'Los datos se borraron o cambió la cuenta durante la sincronización', 'abortar')
                yield c
            except BaseException:
                c.execute('ROLLBACK')
                raise
            else:
                c.execute('COMMIT')

    def _solo_lectura_actual(self) -> bool:
        return getattr(self, '_solo_lectura', False)

    # ------------------------------------------------------------------ versiones
    def epoca(self) -> int:
        with self.lector() as c:
            return _meta_int(c, 'epoca_datos')

    def versiones(self, conn: sqlite3.Connection | None = None) -> Versiones:
        if conn is not None:
            return (_meta_int(conn, 'data_version'), _meta_int(conn, 'local_rev'), _meta_int(conn, 'img_rev'))
        with self.lector() as c:
            return self.versiones(c)

    def marcar_data_version(self, conn: sqlite3.Connection) -> None:
        conn.execute("UPDATE meta SET valor='1' WHERE clave='dv_pendiente'")

    def confirmar_data_version(self) -> int | None:
        with self.escritor() as c:
            if _meta_int(c, 'dv_pendiente') != 1:
                return None
            dv = _meta_int(c, 'data_version') + 1
            c.execute("UPDATE meta SET valor=? WHERE clave='data_version'", (str(dv),))
            c.execute("UPDATE meta SET valor='0' WHERE clave='dv_pendiente'")
            return dv

    @staticmethod
    def _subir(conn: sqlite3.Connection, clave: str) -> int:
        conn.execute("INSERT OR IGNORE INTO meta(clave, valor) VALUES (?, '0')", (clave,))
        conn.execute('UPDATE meta SET valor = CAST(CAST(valor AS INTEGER) + 1 AS TEXT) WHERE clave=?', (clave,))
        return _meta_int(conn, clave)

    def subir_local_rev(self, conn: sqlite3.Connection) -> int:
        return self._subir(conn, 'local_rev')

    def subir_img_rev(self, conn: sqlite3.Connection) -> int:
        return self._subir(conn, 'img_rev')

    # ------------------------------------------------------------------ borrar (03 §3.4)
    def borrar(self, alcance: Alcance) -> None:
        """'tiktok': lo descargado de TikTok + historial de syncs y errores + oauth_states (conserva plan, avisos,
        notas, plantillas, preferencias, celulares y auth_estado). 'todo': además todo el estado local, celulares,
        auth_estado y las claves de meta que no son contadores. 'imagenes': deja las filas de `imagenes` sin archivo
        (estado 'pendiente', sin versión ni LQIP; conserva url_origen para volver a descargarlas) y sube img_rev.
        Siempre: época += 1 en la misma transacción (un escritor que empezó antes se revierte), secure_delete,
        checkpoint + VACUUM + checkpoint y fuera las copias .bak (el archivo no conserva restos)."""
        if alcance not in ('tiktok', 'todo', 'imagenes'):
            raise ValueError(f'alcance desconocido: {alcance!r}')
        with self._candado_w:
            self._w.execute('PRAGMA secure_delete=ON')
        with self.escritor() as c:
            self._subir(c, 'epoca_datos')
            if alcance == 'imagenes':
                c.execute("UPDATE imagenes SET estado='pendiente', version=NULL, ruta_rel=NULL, mime=NULL, ancho=NULL, "
                          "alto=NULL, bytes=NULL, lqip=NULL, color=NULL, intentos=0, ultimo_error=NULL, "
                          "descargada_at=NULL, ultimo_acceso_at=NULL, actualizado_at=?", (self._reloj.ahora(),))
                self._subir(c, 'img_rev')
            else:
                for t in TABLAS_SYNC + TABLAS_TIKTOK:
                    c.execute(f'DELETE FROM {t}')       # nombres de tuplas fijas, nunca de la entrada
                if alcance == 'todo':
                    for t in TABLAS_LOCALES:
                        c.execute(f'DELETE FROM {t}')
                    marcadores = ','.join('?' * len(CLAVES_META_BASE))
                    c.execute(f'DELETE FROM meta WHERE clave NOT IN ({marcadores})', tuple(sorted(CLAVES_META_BASE)))
                    self._subir(c, 'local_rev')
                self.marcar_data_version(c)
        if alcance != 'imagenes':
            self.confirmar_data_version()
        self._compactar()
        for p in glob.glob(glob.escape(self.ruta) + '.bak-v*'):
            with contextlib.suppress(OSError):
                os.remove(p)

    def _compactar(self) -> None:
        with self._candado_w:
            w = self._w
            w.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            w.execute('VACUUM')
            w.execute('PRAGMA wal_checkpoint(TRUNCATE)')

    # ------------------------------------------------------------------ estado y cierre
    def solo_lectura(self) -> bool:
        return self._solo_lectura_actual()

    def tamano_bytes(self) -> int:
        """Bytes de hub.sqlite + -wal + -shm (para «Espacio usado»)."""
        total = 0
        for sufijo in ('', '-wal', '-shm'):
            with contextlib.suppress(OSError):
                total += os.path.getsize(self.ruta + sufijo)
        return total

    def cerrar(self) -> None:
        if self._cerrado:
            return
        adquirido = self._candado_w.acquire(timeout=10)
        try:
            self._cerrado = True
            if not self._solo_lectura_actual():
                with contextlib.suppress(sqlite3.Error):
                    self._w.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        finally:
            if adquirido:
                self._candado_w.release()
        limite = time.monotonic() + 5
        devueltos = 0
        while devueltos < len(self._todas) - 1 and time.monotonic() < limite:
            try:
                self._pool.get(timeout=max(0.0, limite - time.monotonic()))
                devueltos += 1
            except queue.Empty:
                break
        for c in self._todas:
            with contextlib.suppress(sqlite3.Error):
                c.close()


def crear_almacen(ruta_db: str, reloj: Reloj) -> Almacen:
    return _Almacen(ruta_db, reloj)
