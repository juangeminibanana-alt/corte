/**
 * @/datos · transporte de Windows (y del navegador con el proxy de `vite` hacia el hub `--dev`, C31). BUILD_SPEC §5,
 * §6.4, 03 §6.1 y §6.4:
 * - GET con la cookie de sesión (`credentials: 'same-origin'`); ETag/If-None-Match propio: un 304 devuelve el cuerpo
 *   guardado de esa URL.
 * - Mutaciones con `X-CH-Hub: 1`. Errores con ErrorRespuesta → ErrorHub (409 trae `vigente`).
 * - Eventos: SSE /api/events (`event: <tipo>` + `data: <json>`). Al reconectarse tras un corte se invalida todo.
 * - Estado local: cada op va a su ruta REST (POST/PATCH/PUT/DELETE); los lotes, a POST /api/local/ops.
 */
import type * as C from '@/contrato';
import type { ClaveConsulta, ParamsDe } from '@firmas/datos';
import { ErrorHub, TEXTO_CONFLICTO, comoErrorHub, errorDeRed, errorDesdeRespuesta, esObjetoLocal } from './errores';
import { rutaDeConsulta, urlDe } from './rutas';
import { esNube, expirarSesionNube } from '../nube/entorno';
import { dom, registrarMetaDe } from './dominio';
import type { Lectura, MetodoMutacion, ResultadoOpTransporte, SumideroEventos, Transporte } from './transporte';

const MAX_ETAGS = 200;
/** Tope de OpsRequest (contrato: «máx. 200 por lote»). */
export const MAX_OPS_POR_LOTE = 200;
const esWindowsNativo = (): boolean => typeof window !== 'undefined' && 'pywebview' in window;

interface Guardado {
  etag: string;
  cuerpo: unknown;
}

async function leerCuerpo(resp: Response): Promise<unknown> {
  if (resp.status === 204) return null;
  const texto = await resp.text();
  if (texto === '') return null;
  try {
    const v: unknown = JSON.parse(texto);
    return v;
  } catch {
    throw new ErrorHub('error_interno', 'Corte respondió algo que no esperábamos. Inténtalo de nuevo.', resp.status);
  }
}

export const TIPOS_EVENTO: readonly C.EventoHub['tipo'][] = [
  'sync.progreso', 'sync.fin', 'datos.cambiaron', 'conexion.cambio', 'emparejamiento.solicitud', 'emparejamiento.fin',
  'recordatorio.vencido', 'ventana.preguntar_cierre', 'ventana.mostrar_ruta', 'ping',
  // rev. 5 · Display API: cambió la conexión (trae el EstadoDisplay completo).
  'display.cambio',
];
const CONJUNTO_TIPOS: ReadonlySet<string> = new Set(TIPOS_EVENTO);
const EVENTOS_SHELL_WINDOWS = ['recordatorio.vencido', 'ventana.preguntar_cierre', 'ventana.mostrar_ruta', 'datos.cambiaron'] as const;
const CONJUNTO_SHELL: ReadonlySet<string> = new Set(EVENTOS_SHELL_WINDOWS);

/** rev. 5 · Forma mínima de EstadoDisplay (lo que la interfaz lee para decidir el estado de Ajustes). */
export function esEstadoDisplay(v: unknown): v is C.EstadoDisplay {
  if (v === null || typeof v !== 'object' || Array.isArray(v)) return false;
  const o = v as Record<string, unknown>;
  return typeof o['configurada'] === 'boolean' && typeof o['conectada'] === 'boolean' && typeof o['estado'] === 'string'
    && Array.isArray(o['scopes']) && Array.isArray(o['scopes_faltantes']);
}

/** Convierte un mensaje SSE (nombre del evento + data JSON) en EventoHub; null si no se reconoce. */
export function leerEventoSse(nombre: string, data: string): C.EventoHub | null {
  let v: unknown;
  try {
    v = data === '' ? {} : JSON.parse(data);
  } catch {
    return null;
  }
  if (v === null || typeof v !== 'object' || Array.isArray(v)) return null;
  const tipo = 'tipo' in v && typeof v.tipo === 'string' ? v.tipo : nombre;
  if (!CONJUNTO_TIPOS.has(tipo)) return null;
  const evento: Record<string, unknown> = { ...v, tipo };
  if (tipo === 'datos.cambiaron' && !Array.isArray(evento['secciones'])) return null;
  if ((tipo === 'sync.progreso' || tipo === 'sync.fin') && (evento['estado'] === null || typeof evento['estado'] !== 'object')) return null;
  if (tipo === 'display.cambio' && !esEstadoDisplay(evento['display'])) return null;
  return evento as C.EventoHub;
}

/** Solo loopback: conserva el puente de la ventana, los recordatorios y la actualización de su copia local. */
export function conectarEventosShellWindows(sumidero: SumideroEventos): () => void {
  if (typeof EventSource === 'undefined') return () => undefined;
  const fuente = new EventSource('/api/events');
  let activo = true;
  const recibir = (nombre: string) => (ev: Event): void => {
    if (!activo) return;
    const data = ev instanceof MessageEvent && typeof ev.data === 'string' ? ev.data : '';
    const evento = leerEventoSse(nombre, data);
    if (evento && CONJUNTO_SHELL.has(evento.tipo)
      && (evento.tipo !== 'datos.cambiaron' || evento.secciones.includes('local'))) sumidero.evento(evento);
  };
  const oyentes = [...EVENTOS_SHELL_WINDOWS, 'message'].map((tipo) => [tipo, recibir(tipo)] as const);
  for (const [tipo, fn] of oyentes) fuente.addEventListener(tipo, fn);
  return () => {
    activo = false;
    for (const [tipo, fn] of oyentes) fuente.removeEventListener(tipo, fn);
    fuente.close();
  };
}

function rutaDeOp(op: C.OpLocal): { metodo: MetodoMutacion; ruta: string; cuerpo?: unknown } {
  const e = (s: string): string => encodeURIComponent(s);
  switch (op.tipo) {
    case 'plan.crear': return { metodo: 'POST', ruta: '/api/plan', cuerpo: op.datos };
    case 'plan.editar': return { metodo: 'PATCH', ruta: `/api/plan/${e(op.id)}`, cuerpo: op.cambios };
    case 'plan.borrar': return { metodo: 'DELETE', ruta: `/api/plan/${e(op.id)}?rev=${op.rev}` };
    case 'nota.crear': return { metodo: 'POST', ruta: '/api/notas', cuerpo: op.datos };
    case 'nota.editar': return { metodo: 'PATCH', ruta: `/api/notas/${e(op.id)}`, cuerpo: op.cambios };
    case 'nota.borrar': return { metodo: 'DELETE', ruta: `/api/notas/${e(op.id)}?rev=${op.rev}` };
    case 'recordatorio.crear': return { metodo: 'POST', ruta: '/api/recordatorios', cuerpo: op.datos };
    case 'recordatorio.editar': return { metodo: 'PATCH', ruta: `/api/recordatorios/${e(op.id)}`, cuerpo: op.cambios };
    case 'recordatorio.borrar': return { metodo: 'DELETE', ruta: `/api/recordatorios/${e(op.id)}?rev=${op.rev}` };
    case 'aviso.crear': return { metodo: 'POST', ruta: '/api/avisos', cuerpo: op.datos };
    case 'aviso.editar': return { metodo: 'PATCH', ruta: `/api/avisos/${e(op.id)}`, cuerpo: op.cambios };
    case 'plantilla.editar': return { metodo: 'PUT', ruta: `/api/plantillas/${e(op.id)}`, cuerpo: op.cambios };
    case 'preferencias.editar': return { metodo: 'PATCH', ruta: '/api/preferencias', cuerpo: op.cambios };
  }
}

/** Resultado de /api/local/ops → resultado del transporte. */
export function desdeOpsResultado(r: C.OpsResultado): ResultadoOpTransporte {
  const objeto = r.objeto ?? null;
  switch (r.estado) {
    case 'aplicada':
    case 'duplicada':
      return { op_id: r.op_id, estado: 'aplicada', estado_hub: r.estado, objeto, error: null };
    case 'conflicto':
      return {
        op_id: r.op_id, estado: 'conflicto', estado_hub: r.estado, objeto,
        error: new ErrorHub('conflicto', TEXTO_CONFLICTO, 409, undefined, undefined, objeto ?? undefined),
      };
    case 'invalida':
      return {
        op_id: r.op_id, estado: 'error', estado_hub: r.estado, objeto: null,
        error: new ErrorHub('parametros_invalidos', r.error && r.error.trim() !== '' ? r.error : 'No pudimos guardar ese cambio. Revisa los datos.', 422),
      };
  }
}

function esOpsResponse(v: unknown): v is C.OpsResponse {
  return v !== null && typeof v === 'object' && 'resultados' in v && Array.isArray(v.resultados);
}

export function crearTransporteWindows(): Transporte {
  const etags = new Map<string, Guardado>();
  const fuentes = new Map<string, { copia: boolean; at: number | null }>();
  let revisarNube: (() => void) | null = null;

  async function getJson(url: string): Promise<unknown> {
    const previo = etags.get(url);
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (previo) headers['If-None-Match'] = previo.etag;
    let resp: Response;
    try {
      resp = await fetch(url, { method: 'GET', credentials: 'same-origin', cache: 'no-store', headers });
    } catch {
      throw errorDeRed();
    }
    if (resp.status === 304 && previo) return previo.cuerpo;
    if (resp.status === 401 && esNube()) expirarSesionNube();
    if (!resp.ok) throw await errorDesdeRespuesta(resp);
    fuentes.set(url, { copia: resp.headers.get('X-CH-Fuente') === 'copia',
      at: Number(resp.headers.get('X-CH-Copia-At')) || null });
    const cuerpo = await leerCuerpo(resp);
    const etag = resp.headers.get('ETag');
    if (etag) {
      etags.delete(url);
      etags.set(url, { etag, cuerpo });
      if (etags.size > MAX_ETAGS) {
        const primera = etags.keys().next();
        if (!primera.done) etags.delete(primera.value);
      }
    } else {
      etags.delete(url);
    }
    return cuerpo;
  }

  async function mutar(metodo: MetodoMutacion, ruta: string, cuerpo?: unknown, cacheScope?: string): Promise<unknown> {
    const headers: Record<string, string> = { Accept: 'application/json', 'X-CH-Hub': '1' };
    if (cacheScope) headers['X-Corte-Cache-Scope'] = cacheScope;
    const init: RequestInit = { method: metodo, credentials: 'same-origin', cache: 'no-store', headers };
    if (cuerpo !== undefined) {
      headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(cuerpo);
    }
    let resp: Response;
    try {
      resp = await fetch(ruta, init);
    } catch {
      throw errorDeRed();
    }
    if (resp.status === 401 && esNube()) expirarSesionNube();
    if (!resp.ok) throw await errorDesdeRespuesta(resp);
    return leerCuerpo(resp);
  }

  async function aplicarUna(op: C.OpLocal): Promise<ResultadoOpTransporte> {
    const { metodo, ruta, cuerpo } = rutaDeOp(op);
    try {
      const r = await mutar(metodo, ruta, cuerpo);
      return { op_id: op.op_id, estado: 'aplicada', estado_hub: 'aplicada', objeto: esObjetoLocal(r) ? r : null, error: null };
    } catch (e) {
      const error = comoErrorHub(e);
      if (error.codigo === 'conflicto') {
        return { op_id: op.op_id, estado: 'conflicto', estado_hub: 'conflicto', objeto: error.vigente ?? null, error };
      }
      return { op_id: op.op_id, estado: 'error', estado_hub: null, objeto: null, error };
    }
  }

  return {
    tipo: 'windows',

    async leer<K extends ClaveConsulta>(clave: K, params: ParamsDe<K>): Promise<Lectura> {
      const url = urlDe(rutaDeConsulta(clave, params));
      try {
        const datos = await getJson(url);
        const fuente = fuentes.get(url);
        return { datos, fuente: fuente?.copia ? 'copia' : 'hub', copia_at: fuente?.at ?? null,
          con_cambios_pendientes: false };
      } catch (e) {
        if (!esWindowsNativo() || (e instanceof ErrorHub && e.http === 401)) throw e;
        // The same bounded offline contract as Android, backed by native SQLite.
        const copia = await getJson('/api/snapshot') as C.SnapshotResponse;
        if (copia?.version_esquema !== 1) throw e;
        const cola = await getJson('/api/native/ops') as { ops: C.OpLocal[] };
        const ops = Array.isArray(cola.ops) ? cola.ops : [];
        const hoy = dom.hoyLocal();
        const datos = dom.deCopia(clave, params, dom.aplicarOpsACopia(copia, ops, hoy), hoy);
        if (datos === null) throw e;
        registrarMetaDe(copia);
        return { datos, fuente: 'copia', copia_at: copia.generado_at, con_cambios_pendientes: ops.length > 0 };
      }
    },

    obtener(ruta: string): Promise<unknown> {
      return getJson(ruta);
    },

    pedir(metodo: MetodoMutacion, ruta: string, cuerpo?: unknown, cacheScope?: string): Promise<unknown> {
      return mutar(metodo, ruta, cuerpo, cacheScope);
    },

    async aplicarOps(ops: C.OpLocal[], modo: 'individual' | 'lote'): Promise<ResultadoOpTransporte[]> {
      if (esWindowsNativo()) {
        const salida: ResultadoOpTransporte[] = [];
        let tramo: C.OpLocal[] = [];
        const enviar = async (): Promise<void> => {
          const r = await mutar('POST', '/api/native/ops', { ops: tramo }) as C.OpsResponse & { en_cola: string[] };
          const cola = new Set(r.en_cola ?? []);
          for (const x of r.resultados) {
            const resultado = desdeOpsResultado(x);
            salida.push(cola.has(x.op_id) ? { ...resultado, estado: 'en_cola', estado_hub: null } : resultado);
          }
          tramo = [];
        };
        for (const op of ops) {
          if (tramo.length && (tramo.length >= 200
            || new TextEncoder().encode(JSON.stringify({ ops: [...tramo, op] })).length > 224 * 1024)) await enviar();
          tramo.push(op);
        }
        if (tramo.length) await enviar();
        revisarNube?.();
        return salida;
      }
      if (modo === 'individual') {
        const salida: ResultadoOpTransporte[] = [];
        for (const op of ops) salida.push(await aplicarUna(op));
        return salida;
      }
      // OpsRequest admite hasta 200 ops por lote (03 §6.2): uno tras otro, en orden; si uno falla, los siguientes no van.
      const salida: ResultadoOpTransporte[] = [];
      for (let i = 0; i < ops.length; i += MAX_OPS_POR_LOTE) {
        const tramo = ops.slice(i, i + MAX_OPS_POR_LOTE);
        try {
          const r = await mutar('POST', '/api/local/ops', { ops: tramo } satisfies C.OpsRequest);
          if (!esOpsResponse(r)) throw new ErrorHub('error_interno', 'Corte respondió algo que no esperábamos. Inténtalo de nuevo.', 200);
          const porId = new Map(r.resultados.map((x) => [x.op_id, x] as const));
          for (const op of tramo) {
            const x = porId.get(op.op_id);
            salida.push(
              x
                ? desdeOpsResultado(x)
                : { op_id: op.op_id, estado: 'error', estado_hub: null, objeto: null, error: new ErrorHub('error_interno', 'Corte no confirmó este cambio. Inténtalo de nuevo.', 200) },
            );
          }
        } catch (e) {
          const error = comoErrorHub(e);
          for (const op of ops.slice(i)) salida.push({ op_id: op.op_id, estado: 'error', estado_hub: null, objeto: null, error });
          break;
        }
      }
      return salida;
    },

    conectarEventos(sumidero: SumideroEventos): () => void {
      if (esNube() || esWindowsNativo()) {
        // Las peticiones cortas dejan al gateway escalar a cero entre lecturas.
        // Windows añade únicamente los eventos Shell de su servidor loopback; nunca abre SSE en Google.
        const cerrarShell = esWindowsNativo() ? conectarEventosShellWindows(sumidero) : () => undefined;
        let activo = true;
        let temporizador: ReturnType<typeof setTimeout> | null = null;
        let solicitud: AbortController | null = null;
        let volverAhora = false;
        let espera = 15_000;
        let revision: string | null = null;
        let firmaSync: string | null = null;
        let ultimoSync: C.SyncEstado | null = null;

        const limpiarTemporizador = (): void => {
          if (temporizador !== null) clearTimeout(temporizador);
          temporizador = null;
        };
        const programar = (demora: number): void => {
          limpiarTemporizador();
          if (!activo || document.hidden) return;
          temporizador = setTimeout(() => {
            temporizador = null;
            void consultarRevision();
          }, demora);
        };
        const consultarRevision = async (): Promise<void> => {
          if (!activo || document.hidden) return;
          if (solicitud !== null) { volverAhora = true; return; }
          const controlador = new AbortController();
          solicitud = controlador;
          const limite = setTimeout(() => controlador.abort(), 10_000);
          try {
            const resp = await fetch('/api/cloud/revision', {
              method: 'GET', credentials: 'same-origin', cache: 'no-store',
              headers: { Accept: 'application/json' }, signal: controlador.signal,
            });
            if (!activo || document.hidden || controlador.signal.aborted) return;
            if (resp.status === 401) {
              activo = false;
              expirarSesionNube();
              return;
            }
            if (!resp.ok) throw new Error('revision_no_disponible');
            const datos: unknown = await resp.json();
            if (!activo || document.hidden || controlador.signal.aborted) return;
            if (datos === null || typeof datos !== 'object' || Array.isArray(datos)
              || !('revision' in datos) || typeof datos.revision !== 'string' || !datos.revision
              || !('sync' in datos) || datos.sync === null || typeof datos.sync !== 'object'
              || !('en_curso' in datos.sync) || typeof datos.sync.en_curso !== 'boolean'
              || !('progreso' in datos.sync) || typeof datos.sync.progreso !== 'number' || !Number.isFinite(datos.sync.progreso)
              || !('texto' in datos.sync) || typeof datos.sync.texto !== 'string'
              || !('pasos' in datos.sync) || !Array.isArray(datos.sync.pasos)) throw new Error('revision_invalida');
            const estado = datos.sync as C.SyncEstado;
            espera = estado.en_curso ? 3_000 : 15_000;
            if (revision !== null && revision !== datos.revision) sumidero.invalidar([]);
            revision = datos.revision;
            const firma = JSON.stringify(estado);
            if (firmaSync !== firma) {
              const termino = ultimoSync !== null && !estado.en_curso
                && (ultimoSync.en_curso || (estado.sync_id !== null && estado.sync_id !== ultimoSync.sync_id));
              sumidero.evento({ tipo: termino ? 'sync.fin' : 'sync.progreso', estado });
              firmaSync = firma;
              ultimoSync = estado;
            }
          } catch {
            // Red o servidor temporalmente indisponible: conserva la copia visible y reintenta sin errores sin manejar.
            espera = 15_000;
          } finally {
            clearTimeout(limite);
            if (solicitud === controlador) solicitud = null;
            const demora = volverAhora ? 0 : espera;
            volverAhora = false;
            programar(demora);
          }
        };
        const despertar = (): void => {
          espera = 3_000;
          if (solicitud !== null) volverAhora = true;
          else programar(0);
        };
        const alVisibilidad = (): void => {
          if (document.hidden) {
            limpiarTemporizador();
            solicitud?.abort();
          } else {
            sumidero.invalidar([]);
            despertar();
          }
        };
        revisarNube = despertar;
        document.addEventListener('visibilitychange', alVisibilidad);
        programar(0);
        return () => {
          activo = false;
          cerrarShell();
          limpiarTemporizador();
          solicitud?.abort();
          document.removeEventListener('visibilitychange', alVisibilidad);
          if (revisarNube === despertar) revisarNube = null;
        };
      }
      if (typeof EventSource === 'undefined') return () => undefined;
      const fuente = new EventSource('/api/events');
      let huboCorte = false;
      const recibir = (nombre: string) => (ev: Event): void => {
        const data = ev instanceof MessageEvent && typeof ev.data === 'string' ? ev.data : '';
        const e = leerEventoSse(nombre, data);
        if (e) sumidero.evento(e);
      };
      const oyentes = TIPOS_EVENTO.map((t) => [t, recibir(t)] as const);
      for (const [t, fn] of oyentes) fuente.addEventListener(t, fn);
      const sinNombre = recibir('message');
      fuente.addEventListener('message', sinNombre);
      const alError = (): void => {
        huboCorte = true;
      };
      const alAbrir = (): void => {
        if (!huboCorte) return;
        huboCorte = false;
        sumidero.invalidar([]); // pudo perderse un datos.cambiaron mientras estuvo cortado
      };
      fuente.addEventListener('error', alError);
      fuente.addEventListener('open', alAbrir);
      return () => {
        for (const [t, fn] of oyentes) fuente.removeEventListener(t, fn);
        fuente.removeEventListener('message', sinNombre);
        fuente.removeEventListener('error', alError);
        fuente.removeEventListener('open', alAbrir);
        fuente.close();
      };
    },

    vigilarSync(): void {
      if (esNube() || esWindowsNativo()) revisarNube?.();
      /* Windows recibe sync.progreso / sync.fin por SSE. */
    },
  };
}
