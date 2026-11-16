"""Cliente Windows real: HTTPS privado, DPAPI, SQLite durable y copia local.

La interfaz y los archivos siguen en el equipo. La credencial del dispositivo
nunca cruza el puente JavaScript. La base histórica se conserva y respalda;
la réplica de trabajo usa otra base para no destruir su historial.
"""
from __future__ import annotations

import base64
import contextlib
import gzip
import hashlib
import http.client
import io
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3
import ssl
import threading
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from .boveda import BovedaDpapi
from .errores import ErrorDominio
from .interfaces import CTX_UI, RespuestaHttp

ORIGEN = 'https://corte-e-book-21589.web.app'
MAX_RESPUESTA = 20 * 1024 * 1024
MAX_LOTE = 224 * 1024
_log = logging.getLogger('creatorhub.cliente_nativo')


def codificar(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def respuesta(obj: Any, status: int = 200, extras: list | None = None) -> RespuestaHttp:
    return RespuestaHttp(status, [('Content-Type', 'application/json; charset=utf-8'),
                                 ('Cache-Control', 'no-store'), *(extras or [])], codificar(obj))


def error(codigo: str, texto: str, status: int) -> RespuestaHttp:
    return respuesta({'error': {'codigo': codigo, 'mensaje': texto}}, status)


def ruta_canonica(path: str) -> bool:
    """El puente acepta paths literales; las consultas conservan su codificación normal."""
    return (isinstance(path, str) and path.startswith(('/api/', '/img/'))
            and not any(c in path for c in ('%', '\\', '?', '#')) and '//' not in path
            and not any(ord(c) <= 32 or ord(c) == 127 for c in path)
            and not any(segmento in ('.', '..') for segmento in path.split('/')))


class BovedaDispositivo(BovedaDpapi):
    ENTROPIA = b'Corte/dispositivo-nube/v1'
    CAMPOS_SECRETOS = ('native_token',)


class SinRed(Exception):
    pass


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class HttpsCorte:
    """Un solo origen, CA/hostname normales, sin proxy ni redirecciones."""
    def __init__(self) -> None:
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _SinRedireccion(),
                                                  urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def pedir(self, metodo: str, ruta: str, cuerpo: bytes | None = None, token: str = '',
              expected_creator: str | None = None) -> RespuestaHttp:
        u = urllib.parse.urlsplit(ruta)
        if (metodo not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE') or u.scheme or u.netloc or u.fragment
                or not ruta_canonica(u.path) or any(ord(c) < 32 or ord(c) == 127 for c in ruta)):
            raise ValueError('Ruta no permitida')
        headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity',
                   'Origin': ORIGEN, 'X-CH-Hub': '1'}
        if cuerpo is not None:
            headers['Content-Type'] = 'application/json'
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if expected_creator is not None:
            if (not isinstance(expected_creator, str) or not 1 <= len(expected_creator) <= 256
                    or not expected_creator.isascii() or any(ord(c) <= 32 or ord(c) == 127 for c in expected_creator)):
                raise ValueError('Identidad no válida')
            headers['X-Corte-Expected-Creator'] = expected_creator
        req = urllib.request.Request(ORIGEN + ruta, data=cuerpo, headers=headers, method=metodo)
        try:
            try:
                remote = self.opener.open(req, timeout=12)
            except urllib.error.HTTPError as exc:
                remote = exc
            with remote:
                data = remote.read(MAX_RESPUESTA + 1)
                if len(data) > MAX_RESPUESTA:
                    raise ValueError('Respuesta demasiado grande')
                if remote.headers.get('Content-Encoding', '').lower() == 'gzip':
                    with gzip.GzipFile(fileobj=io.BytesIO(data)) as archive:
                        data = archive.read(MAX_RESPUESTA + 1)
                    if len(data) > MAX_RESPUESTA:
                        raise ValueError('Respuesta demasiado grande')
                allowed = {'content-type', 'etag', 'retry-after', 'cache-control'}
                return RespuestaHttp(remote.code, [(k, v) for k, v in remote.headers.items()
                                                   if k.lower() in allowed], data)
        except (OSError, urllib.error.URLError, TimeoutError, http.client.HTTPException) as exc:
            raise SinRed(type(exc).__name__) from None


class CacheNativa:
    def __init__(self, ruta: Path) -> None:
        self.ruta = ruta
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS cache(k TEXT PRIMARY KEY, status INTEGER, headers TEXT, body BLOB, at INTEGER);
              CREATE TABLE IF NOT EXISTS cola(id TEXT PRIMARY KEY, op TEXT NOT NULL, estado TEXT NOT NULL DEFAULT 'pendiente', resultado TEXT);
              CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
            ''')

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.ruta, timeout=15)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    def meta(self, key: str, value: str | None = None) -> str | None:
        with self.db() as db:
            if value is not None:
                db.execute('INSERT INTO meta VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v', (key, value))
            row = db.execute('SELECT v FROM meta WHERE k=?', (key,)).fetchone()
            return row[0] if row else None

    def guardar(self, ruta: str, r: RespuestaHttp) -> None:
        if r.status != 200 or not self._imagen_coincide(ruta, r.cabeceras):
            return
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?,?,?)',
                       (ruta, r.status, json.dumps(r.cabeceras), r.cuerpo, int(time.time())))
            db.execute('DELETE FROM cache WHERE k IN (SELECT k FROM cache WHERE k<>? ORDER BY at DESC LIMIT -1 OFFSET 350)',
                       ('/api/snapshot',))
            while db.execute('SELECT COALESCE(SUM(length(body)),0) FROM cache').fetchone()[0] > 128 * 1024 * 1024:
                db.execute('DELETE FROM cache WHERE k=(SELECT k FROM cache WHERE k<>? ORDER BY at LIMIT 1)',
                           ('/api/snapshot',))

    def leer(self, ruta: str) -> RespuestaHttp | None:
        with self.db() as db:
            row = db.execute('SELECT status,headers,body,at FROM cache WHERE k=?', (ruta,)).fetchone()
        if row is None:
            return None
        headers = json.loads(row[1])
        if not self._imagen_coincide(ruta, headers):
            # Repara entradas de versiones anteriores sin afectar las imágenes correctas.
            with self.db() as db:
                db.execute('DELETE FROM cache WHERE k=?', (ruta,))
            return None
        if not any(k.lower() == 'cache-control' for k, _ in headers):
            headers.append(('Cache-Control', 'private, no-store'))
        return RespuestaHttp(row[0], [*headers, ('X-CH-Fuente', 'copia'),
                                      ('X-CH-Copia-At', str(row[3]))], row[2])

    @staticmethod
    def _imagen_coincide(ruta: str, headers: list) -> bool:
        u = urllib.parse.urlsplit(ruta)
        if not u.path.startswith('/img/'):
            return True
        query = urllib.parse.parse_qs(u.query, keep_blank_values=True)
        versiones, variantes = query.get('v', []), query.get('t', [])
        if (len(versiones) != 1 or not re.fullmatch(r'[0-9a-f]{8}', versiones[0])
                or len(variantes) > 1 or (variantes and variantes[0] not in ('', 'xs', 'sm', 'md'))):
            return False
        variante = variantes[0] if variantes else ''
        etiqueta = '"' + versiones[0] + ('-' + variante if variante else '') + '"'
        cabeceras = {k.lower(): v for k, v in headers}
        # Es almacenamiento privado sin conexión, separado de la caché HTTP del WebView.
        # Un v=0 o una respuesta de otra versión nunca se vuelve una copia estable.
        return (cabeceras.get('etag') == etiqueta and cabeceras.get('content-type', '').split(';')[0]
                in ('image/jpeg', 'image/png', 'image/webp', 'image/gif'))

    def pendientes(self, todos: bool = False) -> list[dict]:
        with self.db() as db:
            rows = db.execute('SELECT op FROM cola' + ('' if todos else " WHERE estado='pendiente'") + ' ORDER BY rowid').fetchall()
        return [json.loads(r[0]) for r in rows]

    def encolar(self, ops: list[dict]) -> None:
        with self.db() as db:
            for op in ops:
                old = db.execute('SELECT op FROM cola WHERE id=?', (op['op_id'],)).fetchone()
                encoded = codificar(op).decode()
                if old and old[0] != encoded:
                    raise ValueError('La operación ya existe con otro contenido')
                db.execute('INSERT OR IGNORE INTO cola(id,op) VALUES (?,?)', (op['op_id'], encoded))

    def confirmar(self, resultados: list[dict], invalidar_copia: bool = False) -> None:
        with self.db() as db:
            hubo_resultado = False
            for r in resultados:
                if r.get('estado') in ('aplicada', 'duplicada'):
                    db.execute('DELETE FROM cola WHERE id=?', (r['op_id'],))
                    hubo_resultado = True
                elif r.get('estado') in ('conflicto', 'invalida'):
                    db.execute('UPDATE cola SET estado=?,resultado=? WHERE id=?',
                               (r['estado'], codificar(r).decode(), r['op_id']))
                    hubo_resultado = True
            if invalidar_copia and hubo_resultado:
                # Misma transacción que la confirmación: un cierre aquí no deja visible
                # un cambio rechazado con un marcador que impediría volver a leer Google.
                db.execute("INSERT INTO meta VALUES ('snapshot_revision','') ON CONFLICT(k) DO UPDATE SET v=''" )


class ClienteNativo:
    def __init__(self, hub: Any, transporte: Any = None, boveda: Any = None, abrir: Any = None) -> None:
        self.hub = hub
        self.http = transporte or HttpsCorte()
        self.vault = boveda or BovedaDispositivo(str(Path(hub.rutas.secretos, 'dispositivo_nube.dpapi')))
        self.cache = CacheNativa(Path(hub.rutas.raiz, 'datos', 'cliente_nube.sqlite'))
        self.lock = threading.RLock()
        self.io_ops = threading.Lock()
        self.work_lock = threading.RLock()
        self.migration_lock = threading.Lock()
        self.parar = threading.Event()
        self.despertar = threading.Event()
        self.pending: dict | None = None
        self.connected = False
        self.mensaje = ''
        self.abrir = abrir or hub.abrir_url
        self.original_local = hub.local
        self.export_original = hub.local.exportar()
        self.open_id_original = hub.boveda.leer().get('open_id')
        if not self.open_id_original:
            with contextlib.closing(sqlite3.connect(hub.rutas.db)) as db:
                row = db.execute('SELECT open_id FROM auth_estado WHERE id=1').fetchone()
                self.open_id_original = row[0] if row else None
        self.manual_original = (any(self.export_original.get(k) for k in ('planes', 'notas', 'avisos', 'recordatorios'))
                                or any(p.get('rev', 1) > 1 for p in self.export_original.get('plantillas', []))
                                or self.export_original.get('preferencias', {}).get('rev', 1) > 1)
        self._respaldar_historial()
        from .almacen import crear_almacen
        from .local import crear_estado_local
        self.replica = crear_almacen(str(Path(hub.rutas.raiz, 'datos', 'trabajo_nube.sqlite')), hub.reloj)
        self.local = crear_estado_local(self.replica, hub.bus, hub.reloj)
        self.local.sembrar()
        if self.cache.pendientes():
            self.local.aplicar_ops(self.cache.pendientes(), CTX_UI)
        hub.local = self.local
        self.thread = threading.Thread(target=self._bucle, name='cliente-google', daemon=True)

    def _respaldar_historial(self) -> None:
        backup = Path(self.hub.rutas.raiz, 'datos', 'antes_de_nube.sqlite')
        if not backup.exists() and Path(self.hub.rutas.db).exists():
            with contextlib.closing(sqlite3.connect(self.hub.rutas.db)) as src, \
                    contextlib.closing(sqlite3.connect(backup)) as dst:
                src.backup(dst)
        exported = Path(self.hub.rutas.raiz, 'datos', 'organizacion_antes_de_nube.json')
        if not exported.exists():
            with open(exported, 'xb') as f:
                f.write(codificar(self.export_original)); f.flush(); os.fsync(f.fileno())

    def iniciar(self) -> None:
        self.thread.start()

    def detener(self) -> None:
        self.parar.set(); self.despertar.set()
        self.thread.join(15) if self.thread.is_alive() else None
        if not self.thread.is_alive():
            self.replica.cerrar()

    def token(self) -> str:
        d = self.vault.leer()
        if d.get('expires_at', 0) <= time.time():
            return ''
        return d.get('native_token', '')

    def estado(self) -> dict:
        with self.lock:
            authenticated = bool(self.token())
            connected = self.connected and authenticated
            r = {'native_client': True, 'platform': 'windows', 'authenticated': authenticated,
                 'connected': connected, 'offline': not connected,
                 'hay_copia': self.cache.leer('/api/snapshot') is not None,
                 'operaciones_pendientes': len(self.cache.pendientes()), 'error': self.mensaje or None}
            if self.pending:
                r['pending'] = {k: self.pending[k] for k in ('user_code', 'verification_uri', 'expires_at')}
            if self.manual_original and self.cache.meta('organizacion_migrada') != '1':
                r['migration_pending'] = self.cache.meta('migration_deferred') != '1'
                r['migration_available'] = True
                r['migration_counts'] = {k: len(self.export_original.get(k, []))
                                         for k in ('planes', 'notas', 'avisos', 'recordatorios')}
                r['migration_warning'] = self.mensaje or 'La copia histórica y su respaldo se conservan en este equipo.'
            return r

    def _limpiar_credencial(self, token_visto: str | None = None) -> None:
        with self.lock:
            if token_visto is not None and self.vault.leer().get('native_token') != token_visto:
                return
            self.vault.mutar(lambda d: [d.pop(k, None) for k in ('native_token', 'expires_at', 'device_id')], True)
            self.connected = False

    def remoto(self, metodo: str, ruta: str, cuerpo: Any = None, autenticar: bool = True,
               expected_creator: str | None = None) -> RespuestaHttp:
        token = self.token() if autenticar else ''
        if autenticar and not token:
            return error('sesion_invalida', 'Inicia sesión con Google para conectar este equipo.', 401)
        try:
            r = self.http.pedir(metodo, ruta, codificar(cuerpo) if cuerpo is not None else None, token, expected_creator)
        except (SinRed, OSError):
            self.connected = False
            raise SinRed() from None
        if autenticar:
            if r.status == 401:
                self._limpiar_credencial(token)
            else:
                self.connected = r.status < 500
        return r

    def conectar(self) -> dict:
        verifier = secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        r = self.remoto('POST', '/api/native/auth/start',
                        {'platform': 'windows', 'name': 'Corte para Windows', 'code_challenge': challenge}, False)
        if r.status not in (200, 201):
            raise SinRed()
        data = json.loads(r.cuerpo)
        u = urllib.parse.urlsplit(data['verification_uri'])
        if (u.scheme + '://' + u.netloc != ORIGEN or u.path != '/conectar-dispositivo'
                or u.fragment or u.username or set(urllib.parse.parse_qs(u.query)) - {'codigo'}):
            raise ValueError('Dirección de autorización inesperada')
        with self.lock:
            self.pending = {'request_id': data['request_id'], 'code_verifier': verifier,
                            'user_code': data['user_code'], 'verification_uri': data['verification_uri'],
                            'expires_at': int(time.time()) + min(int(data['expires_in']), 600)}
            self.mensaje = ''
        self.abrir(data['verification_uri'])
        self.despertar.set()
        return self.estado()

    def salir(self) -> dict:
        try:
            if self.token():
                self.remoto('POST', '/api/native/devices/self/revoke', {})
        except (SinRed, OSError):
            pass
        with self.lock:
            self.pending = None
            self._limpiar_credencial()
        return self.estado()

    def _consultar_autorizacion(self) -> None:
        with self.lock:
            p = dict(self.pending or {})
        if not p:
            return
        if p['expires_at'] <= time.time():
            with self.lock:
                self.pending = None; self.mensaje = 'La autorización caducó. Vuelve a conectar con Google.'
            return
        r = self.remoto('POST', '/api/native/auth/poll',
                        {k: p[k] for k in ('request_id', 'code_verifier')}, False)
        if r.status in (202, 429) or r.status >= 500:
            return
        if r.status != 200:
            with self.lock:
                self.pending = None; self.mensaje = 'No se completó la autorización. Vuelve a conectar con Google.'
            return
        d = json.loads(r.cuerpo)
        import re
        if (d.get('estado') != 'autorizado' or not re.fullmatch(r'corte_native_v1_[A-Za-z0-9_-]{43}', d.get('token', ''))
                or not isinstance(d.get('expires_at'), int) or d['expires_at'] <= time.time()
                or not isinstance(d.get('owner'), dict) or not d['owner'].get('uid')):
            raise ValueError('Respuesta de autorización incompleta')
        previous = self.cache.meta('owner_uid')
        if previous and previous != d['owner']['uid']:
            with self.lock:
                self.pending = None; self.mensaje = 'Este equipo conserva una copia de otra cuenta. No mezclamos sus datos.'
            return
        self.cache.meta('owner_uid', d['owner']['uid'])
        with self.lock:
            if not self.pending or self.pending['request_id'] != p['request_id']:
                return
            self.vault.mutar(lambda b: b.update(native_token=d['token'], device_id=d['device_id'],
                                               expires_at=d['expires_at']), True)
            self.pending = None; self.connected = True; self.mensaje = ''

    def _migrar(self, session: dict) -> None:
        if (not self.manual_original or self.cache.meta('organizacion_migrada') == '1'
                or self.cache.meta('migration_deferred') == '1'):
            return
        if not self.open_id_original or session.get('tiktok_open_id') != self.open_id_original:
            self.mensaje = 'La organización anterior está respaldada. Confirma su cuenta antes de recuperarla.'
            return
        r = self.remoto('POST', '/api/cloud/import', self.export_original,
                        expected_creator=self.open_id_original)
        if r.status == 200:
            self.cache.meta('organizacion_migrada', '1')
            self.mensaje = ''
        else:
            self.mensaje = 'La organización anterior sigue respaldada. No pudimos recuperarla todavía.'

    def migrar(self, confirm: bool) -> RespuestaHttp:
        if not self.token():
            return error('sesion_invalida', 'Conecta este equipo con Google.', 401)
        if not confirm:
            self.cache.meta('migration_deferred', '1')
            return respuesta(self.estado())
        with self.migration_lock:
            session = self.remoto('GET', '/api/native/session')
            if session.status != 200:
                return session
            creator = json.loads(session.cuerpo).get('tiktok_open_id')
            if self.open_id_original and creator != self.open_id_original:
                return error('cuenta_distinta', 'La organización anterior pertenece a otra cuenta de TikTok. '
                             'Conservamos su respaldo y no mezclamos los datos.', 409)
            if not creator:
                return error('sin_credenciales', 'Conecta primero tu cuenta de TikTok en Corte.', 409)
            r = self.remoto('POST', '/api/cloud/import', self.export_original, expected_creator=creator)
            if r.status != 200:
                return r
            self.cache.meta('organizacion_migrada', '1')
            self.mensaje = ''
            self.despertar.set()
            return respuesta(self.estado())

    def _actualizar_copia(self) -> bool:
        r = self.remoto('GET', '/api/snapshot')
        if r.status != 200:
            return False
        data = json.loads(r.cuerpo)
        if (data.get('version_esquema') != 1 or not isinstance(data.get('muestras'), list)
                or not isinstance(data.get('local'), dict)
                or any(not isinstance(data['local'].get(k), list)
                       for k in ('planes', 'notas', 'recordatorios', 'avisos', 'plantillas'))):
            raise ValueError('Copia incompleta')
        self.cache.guardar('/api/snapshot', r)
        with self.work_lock:
            pendientes = self.cache.pendientes()
            # This is a separate local replica, never the historical database.
            self.replica.borrar('todo')
            self.local.importar({'formato': 'corte-local', 'version': 1, **data['local']})
            if pendientes:
                self.local.aplicar_ops(pendientes, CTX_UI)
        for ruta in data.get('imagenes', [])[:16]:
            if self.parar.is_set():
                break
            if isinstance(ruta, str) and ruta.startswith('/img/') and not self.cache.leer(ruta):
                self.cache.guardar(ruta, self.remoto('GET', ruta))
        return True

    def flush(self) -> None:
        if not self.io_ops.acquire(blocking=False):
            return
        try:
            pending = self.cache.pendientes()
            batch: list[dict] = []
            for op in pending:
                if batch and (len(batch) >= 200 or len(codificar({'ops': [*batch, op]})) > MAX_LOTE):
                    r = self.remoto('POST', '/api/local/ops', {'ops': batch})
                    if r.status != 200:
                        return
                    self.cache.confirmar(json.loads(r.cuerpo)['resultados'], invalidar_copia=True); batch = []
                if len(codificar({'ops': [op]})) > MAX_LOTE:
                    self.cache.confirmar([{'op_id': op['op_id'], 'estado': 'invalida', 'error': 'El cambio es demasiado grande.'}],
                                         invalidar_copia=True)
                    continue
                batch.append(op)
            if batch:
                r = self.remoto('POST', '/api/local/ops', {'ops': batch})
                if r.status == 200:
                    self.cache.confirmar(json.loads(r.cuerpo)['resultados'], invalidar_copia=True)
        finally:
            self.io_ops.release()

    def aplicar_ops(self, ops: list[dict]) -> dict:
        if not isinstance(ops, list) or not 1 <= len(ops) <= 200:
            raise ValueError('Lote inválido')
        if any(not isinstance(op, dict) or not isinstance(op.get('op_id'), str)
               or not 1 <= len(op['op_id']) <= 128 for op in ops):
            raise ValueError('Operación inválida')
        # Persist before local application. Replays use the same op_id.
        with self.work_lock:
            self.cache.encolar(ops)
            result = self.local.aplicar_ops(ops, CTX_UI)
        self.cache.confirmar([r for r in result['resultados'] if r['estado'] in ('conflicto', 'invalida')])
        result['en_cola'] = [r['op_id'] for r in result['resultados'] if r['estado'] in ('aplicada', 'duplicada')]
        self.despertar.set()
        return result

    def _bucle(self) -> None:
        while not self.parar.is_set():
            delay = 15
            try:
                if self.pending:
                    self._consultar_autorizacion(); delay = 3
                if self.token():
                    session = self.remoto('GET', '/api/native/session')
                    if session.status == 200:
                        self._migrar(json.loads(session.cuerpo))
                        self.flush()
                        rev = self.remoto('GET', '/api/cloud/revision')
                        if rev.status == 200:
                            data = json.loads(rev.cuerpo)
                            self.cache.guardar('/api/cloud/revision', rev)
                            if (self.cache.leer('/api/snapshot') is None
                                    or self.cache.meta('snapshot_revision') != data.get('revision')):
                                if self._actualizar_copia():
                                    self.cache.meta('snapshot_revision', data['revision'])
                            delay = 3 if data.get('sync', {}).get('en_curso') else 15
            except (SinRed, OSError):
                self.connected = False
            except Exception as exc:
                _log.warning('No se completó una actualización nativa (%s)', type(exc).__name__)
            self.despertar.wait(delay); self.despertar.clear()

    def archivo_imagen(self, ruta: str) -> str | None:
        r = self.cache.leer(ruta)
        if r is None:
            try:
                r = self.remoto('GET', ruta)
            except SinRed:
                return None
        if r.status != 200:
            return None
        mime = dict((k.lower(), v) for k, v in r.cabeceras).get('content-type', '').split(';')[0]
        ext = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp', 'image/gif': '.gif'}.get(mime)
        if not ext:
            return None
        file = Path(self.hub.rutas.cache_img, 'nativo', hashlib.sha256(ruta.encode()).hexdigest() + ext)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(r.cuerpo)
        return str(file)


class DespachadorNativo:
    def __init__(self, client: ClienteNativo, local: Any) -> None:
        self.client, self.local = client, local

    def despachar(self, metodo, ruta, consulta, cabeceras, cuerpo, ctx):
        c = self.client
        try:
            if not ruta_canonica(ruta):
                return error('parametros_invalidos', 'La ruta no es válida.', 422)
            if ruta == '/api/native/session' and metodo == 'GET':
                return respuesta(c.estado())
            if ruta == '/api/native/connect' and metodo == 'POST':
                return respuesta(c.conectar())
            if ruta == '/api/native/logout' and metodo == 'POST':
                return respuesta(c.salir())
            if ruta == '/api/native/migrate' and metodo == 'POST':
                data = json.loads(cuerpo)
                if not isinstance(data.get('confirm'), bool):
                    raise ValueError('Confirma la recuperación')
                return c.migrar(data['confirm'])
            if ruta == '/api/native/ops' and metodo == 'GET':
                if not c.token():
                    return error('sesion_invalida', 'Inicia sesión con Google.', 401)
                return respuesta({'ops': c.cache.pendientes()})
            if ruta == '/api/native/ops' and metodo == 'POST':
                if not c.token():
                    return error('sesion_invalida', 'Inicia sesión con Google.', 401)
                return respuesta(c.aplicar_ops(json.loads(cuerpo).get('ops')))
            if ruta == '/api/native' or ruta.startswith('/api/native/'):
                return error('no_encontrado', 'Esta acción del dispositivo no está disponible.', 404)
            if ruta.startswith('/api/lan'):
                return error('no_disponible', 'Los dispositivos se conectan con Google, sin emparejamiento Wi-Fi.', 410)
            locales = ('/api/ajustes/pc', '/api/datos/uso', '/api/sistema/abrir', '/api/health')
            trabajo = ('/api/plan', '/api/notas', '/api/recordatorios', '/api/avisos', '/api/plantillas', '/api/preferencias')
            if ruta in locales:
                return self.local.despachar(metodo, ruta, consulta, cabeceras, cuerpo, ctx)
            if not c.token():
                return error('sesion_invalida', 'Inicia sesión con Google para conectar este equipo.', 401)
            if ruta == '/api/local/importar' and metodo == 'POST':
                from .api.archivos import leer_json_usuario, MAX_PLAN_BYTES
                data = leer_json_usuario(json.loads(cuerpo).get('ruta'), MAX_PLAN_BYTES)
                if not isinstance(data, dict) or data.get('formato') != 'corte-local' or data.get('version') != 1:
                    return error('archivo_invalido', 'Elige una exportación de organización de Corte.', 422)
                campos = ('formato', 'version', 'exportado_at', 'planes', 'avisos', 'notas', 'recordatorios',
                          'plantillas', 'preferencias')
                session = c.remoto('GET', '/api/native/session')
                if session.status != 200:
                    return session
                creator = json.loads(session.cuerpo).get('tiktok_open_id')
                if not creator:
                    return error('sin_credenciales', 'Conecta primero tu cuenta de TikTok en Corte.', 409)
                r = c.remoto('POST', '/api/cloud/import', {k: data[k] for k in campos if k in data},
                             expected_creator=creator)
                c.despertar.set()
                return r
            if metodo == 'GET' and any(ruta == x or ruta.startswith(x + '/') for x in trabajo):
                limpias = {k: v for k, v in cabeceras.items() if k.lower() != 'if-none-match'}
                with c.work_lock:
                    r = self.local.despachar(metodo, ruta, consulta, limpias, cuerpo, ctx)
                r.cabeceras.extend([('X-CH-Fuente', 'copia'), ('X-CH-Copia-At', str(int(time.time())))])
                return r
            completa = ruta + ('?' + consulta if consulta else '')
            if metodo == 'GET' and not c.connected:
                cached = c.cache.leer(completa)
                c.despertar.set()
                return cached or error('sin_conexion', 'Esta vista todavía no está en la copia guardada.', 503)
            try:
                r = c.remoto(metodo, completa, json.loads(cuerpo) if cuerpo else None)
                if metodo == 'GET' and r.status == 200:
                    if ruta == '/api/session':
                        d = json.loads(r.cuerpo)
                        d['native_client'] = True
                        d['capacidades'].update(lan_admin=False, portapapeles=True)
                        d['plataforma'] = 'windows'
                        r = respuesta(d)
                    c.cache.guardar(completa, r)
                return r
            except SinRed:
                cached = c.cache.leer(completa) if metodo == 'GET' else None
                return cached or error('sin_conexion', 'Sin conexión. Puedes consultar la copia guardada.', 503)
        except ErrorDominio as exc:
            return respuesta(exc.a_respuesta(tuple(c.vault.secretos_vivos())), exc.http)
        except (ValueError, TypeError, KeyError):
            return error('parametros_invalidos', 'No pudimos completar esa solicitud.', 422)
        except (SinRed, OSError):
            return error('sin_conexion', 'No pudimos conectar con Corte. Inténtalo de nuevo.', 503)
