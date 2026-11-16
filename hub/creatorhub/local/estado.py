"""EstadoLocal (BUILD_SPEC §6.2; 03 §3, §6.2; 01 §7): plan, avisos, plantillas, preferencias, notas, recordatorios,
ops del celular, exportar/importar y tareas del hub, sobre las tablas locales del almacén.

Reglas:
- Cada mutación corre en UNA transacción del escritor (`almacen.escritor()`), sube `meta.local_rev` en esa misma
  transacción y, ya confirmada, publica `datos.cambiaron` por el bus con las versiones leídas en ella.
- PATCH/DELETE/PUT llevan `rev`: si no coincide -> ErrorDominio('conflicto', …, http=409, vigente=<objeto vigente>) (C26).
- Los ids los genera el cliente: una creación repetida devuelve el objeto que ya existe (idempotente por id).
- Un solo PlanVideo vivo por application_id; `plan_crear` copia `muestras.en_cohorte_desde_at` (BUILD §4.3).
- `aplicar_ops` (≤ 200) aplica cada op en su propia transacción e idempotente por op_id (`ops_aplicadas`, 03 §6.2).
- `sembrar()` es lo ÚNICO que siembra: las 11 plantillas de plantillas.json y las preferencias por omisión.
"""
from __future__ import annotations

import functools
import importlib.resources
import json
import logging
import sqlite3
import urllib.parse
from typing import Any, Callable, Mapping, Sequence

from .. import comun
from ..errores import ErrorDominio
from ..interfaces import Almacen, Bus, Contexto, Json, Reloj, Versiones
from . import serial as S
from . import validacion as V

_log = logging.getLogger('creatorhub.local')

MAX_OPS = 200
HOSTS_ENLACE_CORTO = ('vm.tiktok.com', 'vt.tiktok.com', 'www.tiktok.com')   # BUILD §6.3.4

# Secciones que se invalidan en la interfaz con cada tipo de cambio (Seccion de contrato.ts).
SEC_PLAN = ('local', 'muestras', 'tiendas', 'videos', 'productos')
SEC_AVISO = ('local', 'muestras', 'tiendas')
SEC_NOTA = ('local', 'muestras', 'tiendas', 'videos', 'productos')
SEC_RECORDATORIO = ('local', 'muestras')
SEC_PLANTILLA = ('local',)
SEC_PREFERENCIAS = ('local',)

MSG_CONFLICTO_MUESTRA = ('Esta muestra también se cambió en tu PC mientras estabas sin conexión. '
                         'Conservamos el cambio de tu PC.')
MSG_CONFLICTO = 'Esto también se cambió en tu PC mientras estabas sin conexión. Conservamos el cambio de tu PC.'
MSG_PLAN_VIVO = 'Esta muestra ya tiene su avance guardado en tu PC. Conservamos el de tu PC.'
MSG_SOLO_LECTURA = 'Este celular solo puede ver tus datos. Pide permiso de edición desde Corte en tu PC.'


@functools.lru_cache(maxsize=1)
def plantillas_por_omision() -> tuple[tuple[str, str, str], ...]:
    """(id, nombre, cuerpo) de las 11 plantillas de 01 §4.8, en orden, desde plantillas.json (importlib.resources)."""
    datos = json.loads(importlib.resources.files('creatorhub.local').joinpath('plantillas.json').read_text('utf-8'))
    return tuple((p['id'], p['nombre'], p['cuerpo']) for p in datos['plantillas'])


def _conflicto(vigente: Json, mensaje: str = MSG_CONFLICTO) -> ErrorDominio:
    return ErrorDominio('conflicto', mensaje, http=409, vigente=vigente)


def _no_encontrado(mensaje: str) -> ErrorDominio:
    return ErrorDominio('no_encontrado', mensaje, http=404)


class _Mutacion:
    """Resultado interno de una mutación: objeto a devolver, si cambió algo y qué secciones invalida."""
    __slots__ = ('objeto', 'cambio', 'secciones')

    def __init__(self, objeto: Json | None, cambio: bool, secciones: tuple[str, ...]) -> None:
        self.objeto, self.cambio, self.secciones = objeto, cambio, secciones


class EstadoLocalSqlite:
    """Implementa interfaces.EstadoLocal."""

    def __init__(self, almacen: Almacen, bus: Bus, reloj: Reloj) -> None:
        self.almacen = almacen
        self.bus = bus
        self.reloj = reloj

    # ================================================================== utilidades
    @staticmethod
    def _escribible(ctx: Contexto) -> None:
        if not ctx.puede_escribir:
            raise ErrorDominio('prohibido', MSG_SOLO_LECTURA, http=403)

    @staticmethod
    def _dispositivo(ctx: Contexto | None) -> str:
        return (ctx.device_id if ctx is not None and ctx.device_id else 'pc')[:64]

    def _hoy(self) -> str:
        return comun.fecha_local(self.reloj.ahora())

    def _ejecutar(self, ctx: Contexto | None, fn: Callable[[sqlite3.Connection], _Mutacion]) -> Json | None:
        """Una mutación = una transacción del escritor + local_rev en ella + aviso por el bus al confirmar."""
        if ctx is not None:
            self._escribible(ctx)
        versiones: Versiones | None = None
        with self.almacen.escritor() as conn:
            r = fn(conn)
            if r.cambio:
                self.almacen.subir_local_rev(conn)
                versiones = self.almacen.versiones(conn)
        if versiones is not None:
            self._notificar(versiones, r.secciones)
        return r.objeto

    def _notificar(self, versiones: Versiones, secciones: Sequence[str]) -> None:
        try:
            self.bus.notificar_cambio(versiones, list(dict.fromkeys(secciones)))
        except Exception:                                   # el cambio ya está guardado: el aviso no debe romperlo
            _log.exception('No se pudo publicar datos.cambiaron')

    def _leer(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        with self.almacen.lector() as conn:
            return fn(conn)

    # ------------------------------------------------------------------ lecturas de una fila
    @staticmethod
    def _plan_fila(conn: sqlite3.Connection, plan_id: str, incluso_borrado: bool = False) -> Json | None:
        sql = ('SELECT pl.*, COALESCE(pl.en_cohorte_desde_at, m.en_cohorte_desde_at) AS cohorte FROM plan_videos pl '
               'LEFT JOIN muestras m ON m.application_id = pl.application_id WHERE pl.id = ?')
        f = S.fila(conn, sql + ('' if incluso_borrado else ' AND pl.eliminado = 0'), (plan_id,))
        return f

    @staticmethod
    def _plan_vivo_de(conn: sqlite3.Connection, application_id: str) -> Json | None:
        return S.fila(conn, 'SELECT pl.*, COALESCE(pl.en_cohorte_desde_at, m.en_cohorte_desde_at) AS cohorte '
                            'FROM plan_videos pl LEFT JOIN muestras m ON m.application_id = pl.application_id '
                            'WHERE pl.application_id = ? AND pl.eliminado = 0', (application_id,))

    # ================================================================== siembra
    def sembrar(self) -> None:
        """Inserta lo que falte de las 11 plantillas predeterminadas y la fila de preferencias (idempotente)."""
        t = self.reloj.ahora()

        def fn(conn: sqlite3.Connection) -> _Mutacion:
            n = 0
            for pid, nombre, cuerpo in plantillas_por_omision():
                n += conn.execute('INSERT OR IGNORE INTO plantillas(id, nombre, cuerpo, predeterminada, creado_at, '
                                  'actualizado_at, rev, dispositivo_id) VALUES (?, ?, ?, 1, ?, ?, 1, ?)',
                                  (pid, nombre, cuerpo, t, t, 'pc')).rowcount
            n += conn.execute('INSERT OR IGNORE INTO preferencias_sinc(id, valor_json, actualizado_at, rev, dispositivo_id) '
                              'VALUES (1, ?, ?, 1, ?)', (_json(S.PREFERENCIAS_POR_OMISION), t, 'pc')).rowcount
            return _Mutacion(None, n > 0, SEC_PLANTILLA)
        self._ejecutar(None, fn)

    # ================================================================== plan
    def plan_listar(self, filtros: Mapping[str, str]) -> Json:
        f = V.filtros(filtros, ('desde', 'hasta'))
        desde, hasta = V.filtro_fecha(f, 'desde'), V.filtro_fecha(f, 'hasta')
        if desde and hasta and desde > hasta:
            raise V.invalido('desde', '«desde» no puede ser posterior a «hasta».', http=400)

        def leer(conn: sqlite3.Connection) -> Json:
            planes = S.leer_planes(conn)
            if desde or hasta:
                planes = [p for p in planes if _plan_en_rango(p, desde, hasta)]
            return {'items': planes, 'local_rev': S.local_rev(conn)}
        return self._leer(leer)

    def _plan_crear(self, conn: sqlite3.Connection, d: Json, ctx: Contexto) -> _Mutacion:
        previo = self._plan_fila(conn, d['id'], incluso_borrado=True)
        if previo is not None:
            if previo['eliminado']:
                raise _no_encontrado('Ese plan ya se borró.')
            return _Mutacion(S.plan(previo), False, SEC_PLAN)          # creación repetida: idempotente por id
        p: Json = {'application_id': None, 'product_id': None, 'tienda_key': None, 'fecha_plan': None,
                   'estado': 'por_planear', 'fecha_video_listo': None, 'programada_para_at': None, 'fecha_publicada': None,
                   'content_id': None, 'enlace_video': None, 'vinculo_origen': None, 'sugerencias_descartadas': [],
                   'motivo_no_se_puede': None, 'motivo_texto': None, 'fijada': False, 'nombre_corto': None, 'notas': None,
                   'orden': 0, 'en_cohorte_desde_at': None}
        p.update(d)
        if p['application_id']:
            vivo = self._plan_vivo_de(conn, p['application_id'])
            if vivo is not None:
                raise _conflicto(S.plan(vivo), MSG_PLAN_VIVO)
            self._completar_desde_muestra(conn, p)
        self._autocompletar(p)
        V.coherencia_plan(p)
        t = self.reloj.ahora()
        conn.execute(
            'INSERT INTO plan_videos(id, application_id, product_id, tienda_key, titulo, fecha_plan, estado, fecha_video_listo, '
            'programada_para_at, fecha_publicada, content_id, enlace_video, vinculo_origen, sugerencias_descartadas_json, '
            'motivo_no_se_puede, motivo_texto, fijada, nombre_corto, notas, orden, en_cohorte_desde_at, creado_at, '
            'actualizado_at, rev, eliminado, dispositivo_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,0,?)',
            (p['id'], p['application_id'], p['product_id'], p['tienda_key'], p['titulo'], p['fecha_plan'], p['estado'],
             p['fecha_video_listo'], p['programada_para_at'], p['fecha_publicada'], p['content_id'], p['enlace_video'],
             p['vinculo_origen'], _json(p['sugerencias_descartadas']), p['motivo_no_se_puede'], p['motivo_texto'],
             int(p['fijada']), p['nombre_corto'], p['notas'], p['orden'], p['en_cohorte_desde_at'], t, t,
             self._dispositivo(ctx)))
        return _Mutacion(S.plan(self._plan_fila(conn, p['id'])), True, SEC_PLAN)  # type: ignore[arg-type]

    @staticmethod
    def _completar_desde_muestra(conn: sqlite3.Connection, p: Json) -> None:
        """Copia la cohorte de la muestra (BUILD §4.3) y completa producto y tienda si el cliente no los mandó."""
        m = S.fila(conn, 'SELECT product_id, en_cohorte_desde_at FROM muestras WHERE application_id = ?', (p['application_id'],))
        if m is None:
            p['en_cohorte_desde_at'] = None
            return
        p['en_cohorte_desde_at'] = m['en_cohorte_desde_at']
        if not p.get('product_id'):
            p['product_id'] = m['product_id']
        if not p.get('tienda_key'):
            t = S.fila(conn, 'SELECT tienda_key FROM v_muestras WHERE application_id = ?', (p['application_id'],))
            p['tienda_key'] = t['tienda_key'] if t else None

    def _autocompletar(self, p: Json) -> None:
        """Fechas automáticas de 01 §7.2 (video listo y publicada) y content_id del enlace completo."""
        if p['estado'] == 'video_listo' and not p.get('fecha_video_listo'):
            p['fecha_video_listo'] = self._hoy()
        if p['estado'] == 'publicada' and not p.get('fecha_publicada'):
            p['fecha_publicada'] = self._hoy()
        if p.get('enlace_video') and not p.get('content_id'):
            p['content_id'] = V.content_id_de_enlace(p['enlace_video'])

    def plan_crear(self, datos: Json, ctx: Contexto) -> Json:
        d = V.plan_crear(datos)
        return self._ejecutar(ctx, lambda conn: self._plan_crear(conn, d, ctx))  # type: ignore[return-value]

    def _plan_editar(self, conn: sqlite3.Connection, plan_id: str, rev: int, campos: Json, ctx: Contexto) -> _Mutacion:
        actual = self._plan_fila(conn, plan_id)
        if actual is None:
            raise _no_encontrado('No encontramos ese plan.')
        if actual['rev'] != rev:
            raise _conflicto(S.plan(actual), MSG_CONFLICTO_MUESTRA if actual['application_id'] else MSG_CONFLICTO)
        p = S.plan(actual)
        p['en_cohorte_desde_at'] = actual['en_cohorte_desde_at']
        p.update(campos)
        if 'application_id' in campos and campos['application_id'] != actual['application_id']:
            for clave in ('product_id', 'tienda_key'):           # siguen a la muestra nueva salvo que vengan en el cambio
                if clave not in campos:
                    p[clave] = None
            if campos['application_id']:
                vivo = self._plan_vivo_de(conn, campos['application_id'])
                if vivo is not None and vivo['id'] != plan_id:
                    raise _conflicto(S.plan(vivo), MSG_PLAN_VIVO)
                self._completar_desde_muestra(conn, p)
            else:
                p['en_cohorte_desde_at'] = None
        if 'enlace_video' in campos and 'content_id' not in campos and campos['enlace_video'] != actual['enlace_video']:
            p['content_id'] = None                         # enlace nuevo: el content_id viejo ya no aplica
        self._autocompletar(p)
        V.coherencia_plan(p)
        conn.execute(
            'UPDATE plan_videos SET application_id=?, product_id=?, tienda_key=?, titulo=?, fecha_plan=?, estado=?, '
            'fecha_video_listo=?, programada_para_at=?, fecha_publicada=?, content_id=?, enlace_video=?, vinculo_origen=?, '
            'sugerencias_descartadas_json=?, motivo_no_se_puede=?, motivo_texto=?, fijada=?, nombre_corto=?, notas=?, orden=?, '
            'en_cohorte_desde_at=?, actualizado_at=?, rev=rev+1, dispositivo_id=? WHERE id=? AND eliminado=0',
            (p['application_id'], p['product_id'], p['tienda_key'], p['titulo'], p['fecha_plan'], p['estado'],
             p['fecha_video_listo'], p['programada_para_at'], p['fecha_publicada'], p['content_id'], p['enlace_video'],
             p['vinculo_origen'], _json(p['sugerencias_descartadas']), p['motivo_no_se_puede'], p['motivo_texto'],
             int(p['fijada']), p['nombre_corto'], p['notas'], p['orden'], p['en_cohorte_desde_at'], self.reloj.ahora(),
             self._dispositivo(ctx), plan_id))
        return _Mutacion(S.plan(self._plan_fila(conn, plan_id)), True, SEC_PLAN)  # type: ignore[arg-type]

    def plan_editar(self, plan_id: str, cambios: Json, ctx: Contexto) -> Json:
        pid = V.ident(plan_id)
        rev, campos = V.plan_cambios(cambios)
        return self._ejecutar(ctx, lambda conn: self._plan_editar(conn, pid, rev, campos, ctx))  # type: ignore[return-value]

    def _plan_borrar(self, conn: sqlite3.Connection, plan_id: str, rev: int, ctx: Contexto) -> _Mutacion:
        actual = self._plan_fila(conn, plan_id)
        if actual is None:
            raise _no_encontrado('No encontramos ese plan.')
        if actual['rev'] != rev:
            raise _conflicto(S.plan(actual), MSG_CONFLICTO_MUESTRA if actual['application_id'] else MSG_CONFLICTO)
        conn.execute('UPDATE plan_videos SET eliminado=1, rev=rev+1, actualizado_at=?, dispositivo_id=? WHERE id=?',
                     (self.reloj.ahora(), self._dispositivo(ctx), plan_id))
        return _Mutacion(None, True, SEC_PLAN)

    def plan_borrar(self, plan_id: str, rev: int, ctx: Contexto) -> None:
        pid = V.ident(plan_id)
        r = V.rev({'rev': rev})
        self._ejecutar(ctx, lambda conn: self._plan_borrar(conn, pid, r, ctx))

    # ================================================================== avisos
    def avisos_listar(self, filtros: Mapping[str, str]) -> Json:
        f = V.filtros(filtros, ('tienda', 'solicitud'))

        def leer(conn: sqlite3.Connection) -> Json:
            items = [a for a in S.leer_avisos(conn)
                     if ('tienda' not in f or a['tienda_key'] == f['tienda'])
                     and ('solicitud' not in f or f['solicitud'] in a['solicitud_ids'] or f['solicitud'] in a['compromisos'])]
            return {'items': items, 'local_rev': S.local_rev(conn)}
        return self._leer(leer)

    @staticmethod
    def _aviso_fila(conn: sqlite3.Connection, aviso_id: str) -> Json | None:
        return S.fila(conn, 'SELECT * FROM avisos_tienda WHERE id = ?', (aviso_id,))

    def _aviso_crear(self, conn: sqlite3.Connection, d: Json, ctx: Contexto) -> _Mutacion:
        previo = self._aviso_fila(conn, d['id'])
        if previo is not None:
            return _Mutacion(S.aviso(previo), False, SEC_AVISO)
        t = self.reloj.ahora()
        conn.execute('INSERT INTO avisos_tienda(id, tienda_key, solicitud_ids_json, plantilla_id, texto, compromisos_json, '
                     'fecha_anterior, origen, copiado_at, marcado_enviado_at, quitado_at, creado_at, actualizado_at, rev, '
                     'dispositivo_id) VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?,?,1,?)',
                     (d['id'], d['tienda_key'], _json(d['solicitud_ids']), d['plantilla_id'], d['texto'],
                      _json(d['compromisos']), d.get('fecha_anterior'), d['origen'], d.get('copiado_at'),
                      d.get('marcado_enviado_at'), t, t, self._dispositivo(ctx)))
        return _Mutacion(S.aviso(self._aviso_fila(conn, d['id'])), True, SEC_AVISO)  # type: ignore[arg-type]

    def aviso_crear(self, datos: Json, ctx: Contexto) -> Json:
        d = V.aviso_crear(datos)
        return self._ejecutar(ctx, lambda conn: self._aviso_crear(conn, d, ctx))  # type: ignore[return-value]

    def _aviso_editar(self, conn: sqlite3.Connection, aviso_id: str, rev: int, campos: Json, ctx: Contexto) -> _Mutacion:
        actual = self._aviso_fila(conn, aviso_id)
        if actual is None:
            raise _no_encontrado('No encontramos ese aviso.')
        if actual['rev'] != rev:
            raise _conflicto(S.aviso(actual))
        a = S.aviso(actual)
        a.update(campos)
        conn.execute('UPDATE avisos_tienda SET texto=?, compromisos_json=?, marcado_enviado_at=?, quitado_at=?, '
                     'actualizado_at=?, rev=rev+1, dispositivo_id=? WHERE id=?',
                     (a['texto'], _json(a['compromisos']), a['marcado_enviado_at'], a['quitado_at'], self.reloj.ahora(),
                      self._dispositivo(ctx), aviso_id))
        return _Mutacion(S.aviso(self._aviso_fila(conn, aviso_id)), True, SEC_AVISO)  # type: ignore[arg-type]

    def aviso_editar(self, aviso_id: str, cambios: Json, ctx: Contexto) -> Json:
        aid = V.ident(aviso_id)
        rev, campos = V.aviso_cambios(cambios)
        return self._ejecutar(ctx, lambda conn: self._aviso_editar(conn, aid, rev, campos, ctx))  # type: ignore[return-value]

    # ================================================================== plantillas
    def plantillas_listar(self) -> Json:
        return self._leer(lambda conn: {'items': S.leer_plantillas(conn), 'local_rev': S.local_rev(conn)})

    @staticmethod
    def _plantilla_fila(conn: sqlite3.Connection, plantilla_id: str) -> Json | None:
        return S.fila(conn, 'SELECT * FROM plantillas WHERE id = ?', (plantilla_id,))

    def _plantilla_editar(self, conn: sqlite3.Connection, plantilla_id: str, rev: int, campos: Json,
                          ctx: Contexto) -> _Mutacion:
        actual = self._plantilla_fila(conn, plantilla_id)
        t = self.reloj.ahora()
        if actual is None:
            # PUT de una plantilla que no existe con rev 0, nombre y cuerpo = plantilla propia del usuario.
            if rev != 0 or 'nombre' not in campos or 'cuerpo' not in campos:
                raise _no_encontrado('No encontramos esa plantilla.')
            conn.execute('INSERT INTO plantillas(id, nombre, cuerpo, predeterminada, creado_at, actualizado_at, rev, '
                         'dispositivo_id) VALUES (?, ?, ?, 0, ?, ?, 1, ?)',
                         (plantilla_id, campos['nombre'], campos['cuerpo'], t, t, self._dispositivo(ctx)))
        else:
            if actual['rev'] != rev:
                raise _conflicto(S.plantilla(actual))
            conn.execute('UPDATE plantillas SET nombre=?, cuerpo=?, actualizado_at=?, rev=rev+1, dispositivo_id=? WHERE id=?',
                         (campos.get('nombre', actual['nombre']), campos.get('cuerpo', actual['cuerpo']), t,
                          self._dispositivo(ctx), plantilla_id))
        return _Mutacion(S.plantilla(self._plantilla_fila(conn, plantilla_id)), True, SEC_PLANTILLA)  # type: ignore[arg-type]

    def plantilla_editar(self, plantilla_id: str, cambios: Json, ctx: Contexto) -> Json:
        pid = V.ident(plantilla_id)
        rev, campos = V.plantilla_cambios(cambios)
        return self._ejecutar(ctx, lambda conn: self._plantilla_editar(conn, pid, rev, campos, ctx))  # type: ignore[return-value]

    def plantilla_restaurar(self, plantilla_id: str, ctx: Contexto) -> Json:
        original = {pid: (n, c) for pid, n, c in plantillas_por_omision()}.get(str(plantilla_id))
        if original is None:
            raise _no_encontrado('Esa plantilla no es de las predeterminadas.')

        def fn(conn: sqlite3.Connection) -> _Mutacion:
            t = self.reloj.ahora()
            if self._plantilla_fila(conn, plantilla_id) is None:
                conn.execute('INSERT INTO plantillas(id, nombre, cuerpo, predeterminada, creado_at, actualizado_at, rev, '
                             'dispositivo_id) VALUES (?, ?, ?, 1, ?, ?, 1, ?)',
                             (plantilla_id, original[0], original[1], t, t, self._dispositivo(ctx)))
            else:
                conn.execute('UPDATE plantillas SET nombre=?, cuerpo=?, predeterminada=1, actualizado_at=?, rev=rev+1, '
                             'dispositivo_id=? WHERE id=?', (original[0], original[1], t, self._dispositivo(ctx), plantilla_id))
            return _Mutacion(S.plantilla(self._plantilla_fila(conn, plantilla_id)), True, SEC_PLANTILLA)  # type: ignore[arg-type]
        return self._ejecutar(ctx, fn)  # type: ignore[return-value]

    # ================================================================== preferencias
    def preferencias_leer(self) -> Json:
        return self._leer(S.leer_preferencias)

    def _preferencias_editar(self, conn: sqlite3.Connection, rev: int, campos: Json, ctx: Contexto) -> _Mutacion:
        f = S.fila(conn, 'SELECT valor_json, rev FROM preferencias_sinc WHERE id = 1')
        actual = S.preferencias(f)
        if actual['rev'] != rev:
            raise _conflicto(actual, 'Tus preferencias también se cambiaron en tu PC. Conservamos el cambio de tu PC.')
        nuevo = {k: v for k, v in actual.items() if k != 'rev'}
        nuevo.update(campos)
        t = self.reloj.ahora()
        if f is None:
            conn.execute('INSERT INTO preferencias_sinc(id, valor_json, actualizado_at, rev, dispositivo_id) '
                         'VALUES (1, ?, ?, 1, ?)', (_json(nuevo), t, self._dispositivo(ctx)))
        else:
            conn.execute('UPDATE preferencias_sinc SET valor_json=?, actualizado_at=?, rev=rev+1, dispositivo_id=? WHERE id=1',
                         (_json(nuevo), t, self._dispositivo(ctx)))
        return _Mutacion(S.leer_preferencias(conn), True, SEC_PREFERENCIAS)

    def preferencias_editar(self, cambios: Json, ctx: Contexto) -> Json:
        rev, campos = V.preferencias_cambios(cambios)
        return self._ejecutar(ctx, lambda conn: self._preferencias_editar(conn, rev, campos, ctx))  # type: ignore[return-value]

    # ================================================================== notas
    def notas_listar(self, filtros: Mapping[str, str]) -> Json:
        f = V.filtros(filtros, ('entidad', 'entidad_id'))
        entidad = V.filtro_opcion(f, 'entidad', V.ENTIDADES_NOTA)

        def leer(conn: sqlite3.Connection) -> Json:
            items = [n for n in S.leer_notas(conn) if (entidad is None or n['entidad'] == entidad)
                     and ('entidad_id' not in f or n['entidad_id'] == f['entidad_id'])]
            return {'items': items, 'local_rev': S.local_rev(conn)}
        return self._leer(leer)

    @staticmethod
    def _nota_fila(conn: sqlite3.Connection, nota_id: str, incluso_borrada: bool = False) -> Json | None:
        return S.fila(conn, 'SELECT * FROM notas WHERE id = ?' + ('' if incluso_borrada else ' AND eliminado = 0'), (nota_id,))

    def _nota_crear(self, conn: sqlite3.Connection, d: Json, ctx: Contexto) -> _Mutacion:
        previo = self._nota_fila(conn, d['id'], incluso_borrada=True)
        if previo is not None:
            if previo['eliminado']:
                raise _no_encontrado('Esa nota ya se borró.')
            return _Mutacion(S.nota(previo), False, SEC_NOTA)
        t = self.reloj.ahora()
        conn.execute('INSERT INTO notas(id, entidad, entidad_id, texto, fijada, creado_at, actualizado_at, rev, eliminado, '
                     'dispositivo_id) VALUES (?,?,?,?,?,?,?,1,0,?)',
                     (d['id'], d['entidad'], d['entidad_id'], d['texto'], int(d.get('fijada', False)), t, t,
                      self._dispositivo(ctx)))
        return _Mutacion(S.nota(self._nota_fila(conn, d['id'])), True, SEC_NOTA)  # type: ignore[arg-type]

    def nota_crear(self, datos: Json, ctx: Contexto) -> Json:
        d = V.nota_crear(datos)
        return self._ejecutar(ctx, lambda conn: self._nota_crear(conn, d, ctx))  # type: ignore[return-value]

    def _nota_editar(self, conn: sqlite3.Connection, nota_id: str, rev: int, campos: Json, ctx: Contexto,
                     borrar: bool = False) -> _Mutacion:
        actual = self._nota_fila(conn, nota_id)
        if actual is None:
            raise _no_encontrado('No encontramos esa nota.')
        if actual['rev'] != rev:
            raise _conflicto(S.nota(actual))
        conn.execute('UPDATE notas SET texto=?, fijada=?, eliminado=?, actualizado_at=?, rev=rev+1, dispositivo_id=? WHERE id=?',
                     (campos.get('texto', actual['texto']), int(campos.get('fijada', bool(actual['fijada']))), int(borrar),
                      self.reloj.ahora(), self._dispositivo(ctx), nota_id))
        return _Mutacion(None if borrar else S.nota(self._nota_fila(conn, nota_id)), True, SEC_NOTA)  # type: ignore[arg-type]

    def nota_editar(self, nota_id: str, cambios: Json, ctx: Contexto) -> Json:
        nid = V.ident(nota_id)
        rev, campos = V.nota_cambios(cambios)
        return self._ejecutar(ctx, lambda conn: self._nota_editar(conn, nid, rev, campos, ctx))  # type: ignore[return-value]

    def nota_borrar(self, nota_id: str, rev: int, ctx: Contexto) -> None:
        nid = V.ident(nota_id)
        r = V.rev({'rev': rev})
        self._ejecutar(ctx, lambda conn: self._nota_editar(conn, nid, r, {}, ctx, borrar=True))

    # ================================================================== recordatorios
    def recordatorios_listar(self, filtros: Mapping[str, str]) -> Json:
        f = V.filtros(filtros, ('estado',))
        estado = V.filtro_opcion(f, 'estado', V.ESTADOS_RECORDATORIO)

        def leer(conn: sqlite3.Connection) -> Json:
            items = [r for r in S.leer_recordatorios(conn) if estado is None or r['estado'] == estado]
            return {'items': items, 'local_rev': S.local_rev(conn)}
        return self._leer(leer)

    @staticmethod
    def _rec_fila(conn: sqlite3.Connection, rec_id: str, incluso_borrado: bool = False) -> Json | None:
        return S.fila(conn, 'SELECT * FROM recordatorios WHERE id = ?' + ('' if incluso_borrado else ' AND eliminado = 0'),
                      (rec_id,))

    def _recordatorio_crear(self, conn: sqlite3.Connection, d: Json, ctx: Contexto) -> _Mutacion:
        previo = self._rec_fila(conn, d['id'], incluso_borrado=True)
        if previo is not None:
            if previo['eliminado']:
                raise _no_encontrado('Ese recordatorio ya se borró.')
            return _Mutacion(S.recordatorio(previo), False, SEC_RECORDATORIO)
        t = self.reloj.ahora()
        conn.execute('INSERT INTO recordatorios(id, entidad, entidad_id, titulo, vence_at, repetir, estado, pospuesto_hasta, '
                     'notificado_at, creado_at, actualizado_at, rev, eliminado, dispositivo_id) '
                     "VALUES (?,?,?,?,?,?,'activo',NULL,NULL,?,?,1,0,?)",
                     (d['id'], d.get('entidad', 'general'), d.get('entidad_id'), d['titulo'], d['vence_at'],
                      d.get('repetir', 'no'), t, t, self._dispositivo(ctx)))
        return _Mutacion(S.recordatorio(self._rec_fila(conn, d['id'])), True, SEC_RECORDATORIO)  # type: ignore[arg-type]

    def recordatorio_crear(self, datos: Json, ctx: Contexto) -> Json:
        d = V.recordatorio_crear(datos)
        return self._ejecutar(ctx, lambda conn: self._recordatorio_crear(conn, d, ctx))  # type: ignore[return-value]

    def _recordatorio_editar(self, conn: sqlite3.Connection, rec_id: str, rev: int, campos: Json, ctx: Contexto,
                             borrar: bool = False) -> _Mutacion:
        actual = self._rec_fila(conn, rec_id)
        if actual is None:
            raise _no_encontrado('No encontramos ese recordatorio.')
        if actual['rev'] != rev:
            raise _conflicto(S.recordatorio(actual))
        r = dict(actual)
        r.update(campos)
        # Otra fecha (o volver a activarlo) lo rearma: el hub podrá avisar de nuevo (C44).
        if any(k in campos and campos[k] != actual[k] for k in ('vence_at', 'pospuesto_hasta', 'repetir')) or (
                campos.get('estado') == 'activo' and actual['estado'] != 'activo'):
            r['notificado_at'] = None
        conn.execute('UPDATE recordatorios SET titulo=?, vence_at=?, repetir=?, estado=?, pospuesto_hasta=?, notificado_at=?, '
                     'eliminado=?, actualizado_at=?, rev=rev+1, dispositivo_id=? WHERE id=?',
                     (r['titulo'], r['vence_at'], r['repetir'], r['estado'], r['pospuesto_hasta'], r['notificado_at'],
                      int(borrar), self.reloj.ahora(), self._dispositivo(ctx), rec_id))
        return _Mutacion(None if borrar else S.recordatorio(self._rec_fila(conn, rec_id)),  # type: ignore[arg-type]
                         True, SEC_RECORDATORIO)

    def recordatorio_editar(self, rec_id: str, cambios: Json, ctx: Contexto) -> Json:
        rid = V.ident(rec_id)
        rev, campos = V.recordatorio_cambios(cambios)
        return self._ejecutar(ctx, lambda conn: self._recordatorio_editar(conn, rid, rev, campos, ctx))  # type: ignore[return-value]

    def recordatorio_borrar(self, rec_id: str, rev: int, ctx: Contexto) -> None:
        rid = V.ident(rec_id)
        r = V.rev({'rev': rev})
        self._ejecutar(ctx, lambda conn: self._recordatorio_editar(conn, rid, r, {}, ctx, borrar=True))

    # ================================================================== ops del celular (03 §6.2)
    def _aplicar_op(self, conn: sqlite3.Connection, op: Mapping[str, Any], ctx: Contexto) -> _Mutacion:
        tipo = op.get('tipo')
        if tipo == 'plan.crear':
            return self._plan_crear(conn, V.plan_crear(op.get('datos')), ctx)
        if tipo == 'plan.editar':
            rev, campos = V.plan_cambios(op.get('cambios'))
            return self._plan_editar(conn, V.ident(op.get('id')), rev, campos, ctx)
        if tipo == 'plan.borrar':
            return self._plan_borrar(conn, V.ident(op.get('id')), V.rev(op), ctx)
        if tipo == 'nota.crear':
            return self._nota_crear(conn, V.nota_crear(op.get('datos')), ctx)
        if tipo == 'nota.editar':
            rev, campos = V.nota_cambios(op.get('cambios'))
            return self._nota_editar(conn, V.ident(op.get('id')), rev, campos, ctx)
        if tipo == 'nota.borrar':
            return self._nota_editar(conn, V.ident(op.get('id')), V.rev(op), {}, ctx, borrar=True)
        if tipo == 'recordatorio.crear':
            return self._recordatorio_crear(conn, V.recordatorio_crear(op.get('datos')), ctx)
        if tipo == 'recordatorio.editar':
            rev, campos = V.recordatorio_cambios(op.get('cambios'))
            return self._recordatorio_editar(conn, V.ident(op.get('id')), rev, campos, ctx)
        if tipo == 'recordatorio.borrar':
            return self._recordatorio_editar(conn, V.ident(op.get('id')), V.rev(op), {}, ctx, borrar=True)
        if tipo == 'aviso.crear':
            return self._aviso_crear(conn, V.aviso_crear(op.get('datos')), ctx)
        if tipo == 'aviso.editar':
            rev, campos = V.aviso_cambios(op.get('cambios'))
            return self._aviso_editar(conn, V.ident(op.get('id')), rev, campos, ctx)
        if tipo == 'plantilla.editar':
            rev, campos = V.plantilla_cambios(op.get('cambios'))
            return self._plantilla_editar(conn, V.ident(op.get('id')), rev, campos, ctx)
        if tipo == 'preferencias.editar':
            rev, campos = V.preferencias_cambios(op.get('cambios'))
            return self._preferencias_editar(conn, rev, campos, ctx)
        raise V.invalido('tipo', 'Tipo de cambio desconocido.')

    def aplicar_ops(self, ops: Sequence[Json], ctx: Contexto) -> Json:
        if not isinstance(ops, (list, tuple)):
            raise V.invalido('ops', 'El cuerpo debe traer la lista de cambios.', http=400)
        if len(ops) > MAX_OPS:
            raise ErrorDominio('parametros_invalidos', f'Manda como máximo {MAX_OPS} cambios por lote.', http=400)
        self._escribible(ctx)
        resultados: list[Json] = []
        secciones: list[str] = []
        versiones: Versiones | None = None
        for op in ops:
            op_id = op.get('op_id') if isinstance(op, Mapping) else None
            if not isinstance(op_id, str) or not op_id or len(op_id) > 64:
                resultados.append({'op_id': op_id if isinstance(op_id, str) else '', 'estado': 'invalida',
                                   'error': 'Al cambio le falta su identificador.'})
                continue
            try:
                with self.almacen.escritor() as conn:
                    previo = S.fila(conn, 'SELECT resultado_json FROM ops_aplicadas WHERE op_id = ?', (op_id,))
                    if previo is not None:
                        guardado = json.loads(previo['resultado_json'])
                        r: Json = {'op_id': op_id, 'estado': 'duplicada'}
                        if guardado.get('objeto') is not None:
                            r['objeto'] = guardado['objeto']
                    else:
                        m = self._aplicar_op(conn, op, ctx)
                        r = {'op_id': op_id, 'estado': 'aplicada'}
                        if m.objeto is not None:
                            r['objeto'] = m.objeto
                        conn.execute('INSERT INTO ops_aplicadas(op_id, dispositivo_id, recibida_at, resultado_json) '
                                     'VALUES (?, ?, ?, ?)', (op_id, self._dispositivo(ctx), self.reloj.ahora(), _json(r)))
                        self.almacen.subir_local_rev(conn)
                        versiones = self.almacen.versiones(conn)
                        secciones.extend(m.secciones)
            except ErrorDominio as e:
                if e.codigo == 'conflicto':
                    r = {'op_id': op_id, 'estado': 'conflicto'}
                    if e.vigente is not None:
                        r['objeto'] = e.vigente
                else:
                    r = {'op_id': op_id, 'estado': 'invalida', 'error': e.mensaje}
            except sqlite3.IntegrityError:
                r = {'op_id': op_id, 'estado': 'invalida', 'error': 'No se pudo guardar este cambio.'}
            resultados.append(r)
        if versiones is not None:
            self._notificar(versiones, secciones)       # un solo aviso por lote (no 200 eventos)
            lr = versiones[1]
        else:
            lr = self._leer(S.local_rev)
        return {'resultados': resultados, 'local_rev': lr}

    # ================================================================== exportar / importar (C19)
    def exportar(self) -> Json:
        def leer(conn: sqlite3.Connection) -> Json:
            return {'formato': 'corte-local', 'version': 1, 'exportado_at': self.reloj.ahora(),
                    'planes': S.leer_planes(conn), 'avisos': S.leer_avisos(conn), 'notas': S.leer_notas(conn),
                    'recordatorios': S.leer_recordatorios(conn), 'plantillas': S.leer_plantillas(conn),
                    'preferencias': S.leer_preferencias(conn)}
        return self._leer(leer)

    def importar(self, datos: Json) -> Json:
        if not isinstance(datos, Mapping) or datos.get('formato') != 'corte-local' or datos.get('version') != 1:
            raise ErrorDominio('archivo_invalido', 'El archivo no es una exportación de Corte.', http=422)
        colecciones = ('planes', 'avisos', 'notas', 'recordatorios', 'plantillas')
        for c in colecciones:
            if datos.get(c) is not None and not isinstance(datos.get(c), list):
                raise ErrorDominio('archivo_invalido', 'El archivo no es una exportación de Corte.', http=422)
        importados = {c: 0 for c in colecciones}
        omitidos = 0
        versiones: Versiones | None = None
        with self.almacen.escritor() as conn:
            for c in colecciones:
                for obj in datos.get(c) or []:
                    try:
                        hecho = isinstance(obj, Mapping) and _IMPORTADORES[c](conn, obj)
                    except (ErrorDominio, KeyError, TypeError, ValueError, AttributeError, sqlite3.IntegrityError):
                        hecho = False
                    if hecho:
                        importados[c] += 1
                    else:
                        omitidos += 1
            pref_hecho = False
            if isinstance(datos.get('preferencias'), Mapping):
                try:
                    pref_hecho = _importar_preferencias(conn, datos['preferencias'], self.reloj.ahora())
                except (ErrorDominio, KeyError, TypeError, ValueError):
                    pref_hecho = False
            if sum(importados.values()) or pref_hecho:
                self.almacen.subir_local_rev(conn)
                versiones = self.almacen.versiones(conn)
            lr = S.local_rev(conn)
        if versiones is not None:
            self._notificar(versiones, SEC_PLAN + SEC_AVISO + SEC_NOTA)
        return {'importados': importados, 'omitidos': omitidos, 'local_rev': lr}

    # ================================================================== tareas del hub
    def recordatorios_vencidos(self, ahora: int) -> list[Json]:
        """Recordatorios activos cuyo momento ya llegó y de los que el hub aún no avisó: marca notificado_at (C44).
        Momento = la última repetición ≤ ahora de vence_at (diario/semanal; si no repite, vence_at), o pospuesto_hasta
        si lo pospusiste a más tarde.
        No cambia vence_at ni la rev (es contabilidad del hub); sí sube local_rev para refrescar las copias."""
        ahora = int(ahora)
        vencidos: list[Json] = []

        def fn(conn: sqlite3.Connection) -> _Mutacion:
            for r in S.filas(conn, "SELECT * FROM recordatorios WHERE eliminado = 0 AND estado = 'activo'"):
                momento = max(r['pospuesto_hasta'] or 0, _ultima_ocurrencia(r['vence_at'], r['repetir'], ahora))
                if momento > ahora or (r['notificado_at'] is not None and r['notificado_at'] >= momento):
                    continue
                conn.execute('UPDATE recordatorios SET notificado_at = ? WHERE id = ?', (ahora, r['id']))
                r['notificado_at'] = ahora
                vencidos.append(S.recordatorio(r))
            return _Mutacion(None, bool(vencidos), SEC_RECORDATORIO)
        self._ejecutar(None, fn)
        return vencidos

    def enlaces_por_resolver(self) -> list[tuple[str, str]]:
        """(plan_id, enlace) de planes vivos con enlace de TikTok y sin content_id (enlaces cortos, C30)."""
        def leer(conn: sqlite3.Connection) -> list[tuple[str, str]]:
            out = []
            for f in S.filas(conn, "SELECT id, enlace_video FROM plan_videos WHERE eliminado = 0 AND content_id IS NULL "
                                   "AND enlace_video IS NOT NULL AND enlace_video <> '' ORDER BY actualizado_at, id"):
                u = urllib.parse.urlsplit(f['enlace_video'])
                if u.scheme == 'https' and (u.hostname or '').lower() in HOSTS_ENLACE_CORTO:
                    out.append((f['id'], f['enlace_video']))
            return out
        return self._leer(leer)

    def guardar_content_id(self, plan_id: str, content_id: str) -> None:
        pid = V.ident(plan_id)
        cid = V.digitos(content_id, 'content_id', nulo=False)

        def fn(conn: sqlite3.Connection) -> _Mutacion:
            n = conn.execute('UPDATE plan_videos SET content_id = ?, actualizado_at = ? '
                             'WHERE id = ? AND eliminado = 0 AND content_id IS NULL', (cid, self.reloj.ahora(), pid)).rowcount
            return _Mutacion(None, n > 0, SEC_PLAN)
        self._ejecutar(None, fn)


# ---------------------------------------------------------------------- funciones auxiliares
def _json(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(',', ':'))


def _plan_en_rango(p: Mapping[str, Any], desde: str | None, hasta: str | None) -> bool:
    """Un plan entra en [desde, hasta] si alguna de sus fechas (planeada, video listo, programada, publicada) cae ahí."""
    fechas = [p.get('fecha_plan'), p.get('fecha_video_listo'), p.get('fecha_publicada')]
    if p.get('programada_para_at'):
        fechas.append(comun.fecha_local(p['programada_para_at']))
    return any(f and (desde is None or f >= desde) and (hasta is None or f <= hasta) for f in fechas)


def _ultima_ocurrencia(vence_at: int, repetir: str, ahora: int) -> int:
    paso = {'diario': 86400, 'semanal': 7 * 86400}.get(repetir)
    if not paso or vence_at >= ahora:
        return vence_at
    return vence_at + ((ahora - vence_at) // paso) * paso


def _versionado(obj: Mapping[str, Any]) -> tuple[int, int, int, str]:
    """(rev, creado_at, actualizado_at, dispositivo_id) de un objeto importado, validados."""
    rev = obj.get('rev')
    if isinstance(rev, bool) or not isinstance(rev, int) or rev < 1:
        raise V.invalido('rev')
    creado = V.epoch(obj.get('creado_at'), 'creado_at', nulo=False)
    actualizado = V.epoch(obj.get('actualizado_at'), 'actualizado_at', nulo=False)
    disp = obj.get('dispositivo_id') or 'pc'
    if not isinstance(disp, str) or len(disp) > 64:
        raise V.invalido('dispositivo_id')
    return rev, creado, actualizado, disp  # type: ignore[return-value]


def _sin_versionado(obj: Mapping[str, Any], extra: tuple[str, ...] = ()) -> dict[str, Any]:
    return {k: v for k, v in obj.items() if k not in ('rev', 'creado_at', 'actualizado_at', 'dispositivo_id') + extra}


def _rev_guardada(conn: sqlite3.Connection, tabla: str, ident: str) -> int | None:
    f = S.fila(conn, f'SELECT rev FROM {tabla} WHERE id = ?', (ident,))   # `tabla` viene de una tupla fija
    return f['rev'] if f else None


def _importar_plan(conn: sqlite3.Connection, obj: Mapping[str, Any]) -> bool:
    rev, creado, actualizado, disp = _versionado(obj)
    d = V.plan_crear(_sin_versionado(obj))
    previo = _rev_guardada(conn, 'plan_videos', d['id'])
    if previo is not None and previo >= rev:
        return False
    p: Json = {'application_id': None, 'product_id': None, 'tienda_key': None, 'fecha_plan': None, 'estado': 'por_planear',
               'fecha_video_listo': None, 'programada_para_at': None, 'fecha_publicada': None, 'content_id': None,
               'enlace_video': None, 'vinculo_origen': None, 'sugerencias_descartadas': [], 'motivo_no_se_puede': None,
               'motivo_texto': None, 'fijada': False, 'nombre_corto': None, 'notas': None, 'orden': 0}
    p.update(d)
    V.coherencia_plan(p)
    if p['application_id']:
        vivo = S.fila(conn, 'SELECT id FROM plan_videos WHERE application_id = ? AND eliminado = 0', (p['application_id'],))
        if vivo is not None and vivo['id'] != p['id']:
            return False                                  # un solo plan vivo por muestra: gana el de esta PC
    cohorte = V.epoch(obj.get('en_cohorte_desde_at'), 'en_cohorte_desde_at')
    conn.execute(
        'INSERT INTO plan_videos(id, application_id, product_id, tienda_key, titulo, fecha_plan, estado, fecha_video_listo, '
        'programada_para_at, fecha_publicada, content_id, enlace_video, vinculo_origen, sugerencias_descartadas_json, '
        'motivo_no_se_puede, motivo_texto, fijada, nombre_corto, notas, orden, en_cohorte_desde_at, creado_at, actualizado_at, '
        'rev, eliminado, dispositivo_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?) '
        'ON CONFLICT(id) DO UPDATE SET application_id=excluded.application_id, product_id=excluded.product_id, '
        'tienda_key=excluded.tienda_key, titulo=excluded.titulo, fecha_plan=excluded.fecha_plan, estado=excluded.estado, '
        'fecha_video_listo=excluded.fecha_video_listo, programada_para_at=excluded.programada_para_at, '
        'fecha_publicada=excluded.fecha_publicada, content_id=excluded.content_id, enlace_video=excluded.enlace_video, '
        'vinculo_origen=excluded.vinculo_origen, sugerencias_descartadas_json=excluded.sugerencias_descartadas_json, '
        'motivo_no_se_puede=excluded.motivo_no_se_puede, motivo_texto=excluded.motivo_texto, fijada=excluded.fijada, '
        'nombre_corto=excluded.nombre_corto, notas=excluded.notas, orden=excluded.orden, '
        'en_cohorte_desde_at=excluded.en_cohorte_desde_at, creado_at=excluded.creado_at, '
        'actualizado_at=excluded.actualizado_at, rev=excluded.rev, eliminado=0, dispositivo_id=excluded.dispositivo_id',
        (p['id'], p['application_id'], p['product_id'], p['tienda_key'], p['titulo'], p['fecha_plan'], p['estado'],
         p['fecha_video_listo'], p['programada_para_at'], p['fecha_publicada'], p['content_id'], p['enlace_video'],
         p['vinculo_origen'], _json(p['sugerencias_descartadas']), p['motivo_no_se_puede'], p['motivo_texto'],
         int(p['fijada']), p['nombre_corto'], p['notas'], p['orden'], cohorte, creado, actualizado, rev, disp))
    return True


def _importar_aviso(conn: sqlite3.Connection, obj: Mapping[str, Any]) -> bool:
    rev, creado, actualizado, disp = _versionado(obj)
    d = V.aviso_crear(_sin_versionado(obj, ('quitado_at',)))
    quitado = V.epoch(obj.get('quitado_at'), 'quitado_at')
    previo = _rev_guardada(conn, 'avisos_tienda', d['id'])
    if previo is not None and previo >= rev:
        return False
    conn.execute(
        'INSERT INTO avisos_tienda(id, tienda_key, solicitud_ids_json, plantilla_id, texto, compromisos_json, fecha_anterior, '
        'origen, copiado_at, marcado_enviado_at, quitado_at, creado_at, actualizado_at, rev, dispositivo_id) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET tienda_key=excluded.tienda_key, '
        'solicitud_ids_json=excluded.solicitud_ids_json, plantilla_id=excluded.plantilla_id, texto=excluded.texto, '
        'compromisos_json=excluded.compromisos_json, fecha_anterior=excluded.fecha_anterior, origen=excluded.origen, '
        'copiado_at=excluded.copiado_at, marcado_enviado_at=excluded.marcado_enviado_at, quitado_at=excluded.quitado_at, '
        'creado_at=excluded.creado_at, actualizado_at=excluded.actualizado_at, rev=excluded.rev, '
        'dispositivo_id=excluded.dispositivo_id',
        (d['id'], d['tienda_key'], _json(d['solicitud_ids']), d['plantilla_id'], d['texto'], _json(d['compromisos']),
         d.get('fecha_anterior'), d['origen'], d.get('copiado_at'), d.get('marcado_enviado_at'), quitado, creado,
         actualizado, rev, disp))
    return True


def _importar_nota(conn: sqlite3.Connection, obj: Mapping[str, Any]) -> bool:
    rev, creado, actualizado, disp = _versionado(obj)
    d = V.nota_crear(_sin_versionado(obj))
    previo = _rev_guardada(conn, 'notas', d['id'])
    if previo is not None and previo >= rev:
        return False
    conn.execute(
        'INSERT INTO notas(id, entidad, entidad_id, texto, fijada, creado_at, actualizado_at, rev, eliminado, dispositivo_id) '
        'VALUES (?,?,?,?,?,?,?,?,0,?) ON CONFLICT(id) DO UPDATE SET entidad=excluded.entidad, entidad_id=excluded.entidad_id, '
        'texto=excluded.texto, fijada=excluded.fijada, creado_at=excluded.creado_at, actualizado_at=excluded.actualizado_at, '
        'rev=excluded.rev, eliminado=0, dispositivo_id=excluded.dispositivo_id',
        (d['id'], d['entidad'], d['entidad_id'], d['texto'], int(d.get('fijada', False)), creado, actualizado, rev, disp))
    return True


def _importar_recordatorio(conn: sqlite3.Connection, obj: Mapping[str, Any]) -> bool:
    rev, creado, actualizado, disp = _versionado(obj)
    base = _sin_versionado(obj, ('estado', 'pospuesto_hasta', 'notificado_at'))
    d = V.recordatorio_crear(base)
    estado = V.opcion(obj.get('estado', 'activo'), 'estado', V.ESTADOS_RECORDATORIO)
    pospuesto = V.epoch(obj.get('pospuesto_hasta'), 'pospuesto_hasta')
    notificado = V.epoch(obj.get('notificado_at'), 'notificado_at')
    previo = _rev_guardada(conn, 'recordatorios', d['id'])
    if previo is not None and previo >= rev:
        return False
    conn.execute(
        'INSERT INTO recordatorios(id, entidad, entidad_id, titulo, vence_at, repetir, estado, pospuesto_hasta, notificado_at, '
        'creado_at, actualizado_at, rev, eliminado, dispositivo_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,?) '
        'ON CONFLICT(id) DO UPDATE SET entidad=excluded.entidad, entidad_id=excluded.entidad_id, titulo=excluded.titulo, '
        'vence_at=excluded.vence_at, repetir=excluded.repetir, estado=excluded.estado, '
        'pospuesto_hasta=excluded.pospuesto_hasta, notificado_at=excluded.notificado_at, creado_at=excluded.creado_at, '
        'actualizado_at=excluded.actualizado_at, rev=excluded.rev, eliminado=0, dispositivo_id=excluded.dispositivo_id',
        (d['id'], d.get('entidad', 'general'), d.get('entidad_id'), d['titulo'], d['vence_at'], d.get('repetir', 'no'),
         estado, pospuesto, notificado, creado, actualizado, rev, disp))
    return True


def _importar_plantilla(conn: sqlite3.Connection, obj: Mapping[str, Any]) -> bool:
    rev, creado, actualizado, disp = _versionado(obj)
    ident = V.ident(obj.get('id'))
    nombre = V.texto(obj.get('nombre'), 'nombre', 1, 60)
    cuerpo = V.texto(obj.get('cuerpo'), 'cuerpo', 1, 5000)
    predeterminada = V.booleano(obj.get('predeterminada', False), 'predeterminada')
    previo = _rev_guardada(conn, 'plantillas', ident)
    if previo is not None and previo >= rev:
        return False
    conn.execute(
        'INSERT INTO plantillas(id, nombre, cuerpo, predeterminada, creado_at, actualizado_at, rev, dispositivo_id) '
        'VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET nombre=excluded.nombre, cuerpo=excluded.cuerpo, '
        'predeterminada=excluded.predeterminada, creado_at=excluded.creado_at, actualizado_at=excluded.actualizado_at, '
        'rev=excluded.rev, dispositivo_id=excluded.dispositivo_id',
        (ident, nombre, cuerpo, int(predeterminada), creado, actualizado, rev, disp))
    return True


def _importar_preferencias(conn: sqlite3.Connection, obj: Mapping[str, Any], ahora: int) -> bool:
    rev = obj.get('rev')
    if isinstance(rev, bool) or not isinstance(rev, int) or rev < 1:
        return False
    _r, campos = V.preferencias_cambios({k: v for k, v in obj.items() if k in S.PREFERENCIAS_POR_OMISION} | {'rev': rev})
    f = S.fila(conn, 'SELECT valor_json, rev FROM preferencias_sinc WHERE id = 1')
    actual = S.preferencias(f)
    if f is not None and actual['rev'] >= rev:
        return False
    nuevo = {k: v for k, v in actual.items() if k != 'rev'}
    nuevo.update(campos)
    conn.execute('INSERT INTO preferencias_sinc(id, valor_json, actualizado_at, rev, dispositivo_id) VALUES (1, ?, ?, ?, ?) '
                 'ON CONFLICT(id) DO UPDATE SET valor_json=excluded.valor_json, actualizado_at=excluded.actualizado_at, '
                 'rev=excluded.rev, dispositivo_id=excluded.dispositivo_id',
                 (_json(nuevo), ahora, rev, 'pc'))
    return True


_IMPORTADORES: dict[str, Callable[[sqlite3.Connection, Mapping[str, Any]], bool]] = {
    'planes': _importar_plan, 'avisos': _importar_aviso, 'notas': _importar_nota, 'recordatorios': _importar_recordatorio,
    'plantillas': _importar_plantilla,
}
