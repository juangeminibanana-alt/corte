/**
 * rev. 6 · Lógica de presentación del catálogo de videos («Todos»): videos PUBLICADOS en tu cuenta de TikTok (Display
 * API) y videos CON VENTAS (contrato VideoCatalogo). Funciones puras, sin React.
 * Regla del contrato que se respeta aquí: nunca se inventa una cifra. Un video sin pedidos lleva `ventas: null` y se
 * dice «Sin ventas» (con desde cuándo se puede afirmar), nunca «$0 · 0 pedidos».
 */
import type * as C from '@/contrato';
import type { ParamsCatalogoVideos } from '@/datos';
import { coincide, fechaLocalDe } from '@/dominio';
import { nombreVideo } from './logica';

export type SegmentoVideos = 'ventas' | 'todos';
export type OrdenCatalogo = 'publicado' | 'vistas' | 'comision';

/** El máximo del hub. Con más videos, el hub devuelve los primeros según el orden pedido (ver Catalogo.tsx). */
export const LIMITE_CATALOGO = 2000;
/** La petición de siempre: todo de una vez, lo publicado más reciente primero. La comparten «Todos», el detalle de un
 *  video sin ventas (su pedidos_desde) y PantallaVideos (un 404 guardado quita las pestañas): misma clave de caché. */
export const PARAMS_CATALOGO: ParamsCatalogoVideos = { orden: 'publicado', limite: LIMITE_CATALOGO };

export const ORDENES_CATALOGO: readonly OrdenCatalogo[] = ['publicado', 'vistas', 'comision'];

export function esOrdenCatalogo(v: string | null): v is OrdenCatalogo {
  return v !== null && (ORDENES_CATALOGO as readonly string[]).includes(v);
}

/** «Más vistas» solo si alguna vez se conectaron las métricas de TikTok (si no, nadie tiene vistas). */
export function ordenesCatalogoPara(conMetricas: boolean): OrdenCatalogo[] {
  return ORDENES_CATALOGO.filter((o) => conMetricas || o !== 'vistas');
}

/** Orden pedido en la URL, si se puede usar; si no, el de siempre: lo publicado más reciente primero. */
export function ordenCatalogoDe(param: string | null, conMetricas: boolean): OrdenCatalogo {
  return esOrdenCatalogo(param) && ordenesCatalogoPara(conMetricas).includes(param) ? param : 'publicado';
}

/**
 * Qué vista de #/videos se arma. «Todos» solo si el hub tiene el catálogo (capacidades.catalogo_videos) y no respondió
 * 404; mientras la sesión carga (las capacidades aún no se saben) se espera en vez de pintar «Con ventas» un momento.
 */
export function vistaVideos(p: { segmento: string | null; conCatalogo: boolean; sinCatalogo: boolean; sesionCargando: boolean }): 'catalogo' | 'espera' | 'ventas' {
  if (p.segmento !== 'todos' || p.sinCatalogo) return 'ventas';
  if (p.conCatalogo) return 'catalogo';
  return p.sesionCargando ? 'espera' : 'ventas';
}

const SIN_NOMBRES: ReadonlyMap<string, string> = new Map();

/** Nombre visible: la descripción real de TikTok sin hashtags (o «Video 7677…3012»), igual que en «Con ventas». */
export function nombreCatalogo(v: Pick<C.VideoCatalogo, 'content_id' | 'descripcion' | 'ventas'>): string {
  return nombreVideo(
    { content_id: v.content_id, miniatura: null, titulo: v.ventas?.titulo ?? null, descripcion: v.descripcion ?? v.ventas?.descripcion ?? null },
    SIN_NOMBRES,
  );
}

const cmpTexto = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

/** Última venta como número para ordenar (más reciente = mayor); los videos sin ventas, al final de su grupo. */
function ultimaVenta(v: C.VideoCatalogo): number {
  return v.ventas ? Date.parse(`${v.ventas.ultima_venta}T00:00:00Z`) || 0 : Number.NEGATIVE_INFINITY;
}

/** El mismo orden que el hub (vista._orden_catalogo): sin el dato, al final; empates por ID. */
export function ordenarCatalogo(items: readonly C.VideoCatalogo[], orden: OrdenCatalogo): C.VideoCatalogo[] {
  const copia = [...items];
  switch (orden) {
    case 'vistas':
      return copia.sort((a, b) =>
        Number(a.vistas === null) - Number(b.vistas === null) || (b.vistas ?? 0) - (a.vistas ?? 0) || cmpTexto(a.content_id, b.content_id));
    case 'comision':
      return copia.sort((a, b) =>
        Number(a.ventas === null) - Number(b.ventas === null)
        || (b.ventas?.comision_estimada_centavos ?? 0) - (a.ventas?.comision_estimada_centavos ?? 0)
        || cmpTexto(a.content_id, b.content_id));
    case 'publicado':
      // Lo más nuevo primero; sin fecha de publicación, por la última venta (los que nunca vendieron al final).
      return copia.sort((a, b) => {
        const sinFecha = Number(a.publicado_at === null) - Number(b.publicado_at === null);
        if (sinFecha) return sinFecha;
        const porFecha = (b.publicado_at ?? 0) - (a.publicado_at ?? 0);
        if (porFecha) return porFecha;
        const ua = ultimaVenta(a);
        const ub = ultimaVenta(b);
        if (ua !== ub) return ub > ua ? 1 : -1;
        return cmpTexto(a.content_id, b.content_id);
      });
  }
}

export interface FiltrosCatalogo {
  q: string;
  soloSinVentas: boolean;
}

/** Búsqueda por nombre (descripción de TikTok), ID del video o tienda de sus ventas; «Sin ventas» = `ventas: null`. */
export function filtrarCatalogo(items: readonly C.VideoCatalogo[], f: FiltrosCatalogo): C.VideoCatalogo[] {
  const q = f.q.trim();
  return items.filter((v) => {
    if (f.soloSinVentas && v.ventas !== null) return false;
    if (q && !coincide(q, nombreCatalogo(v), v.descripcion, v.content_id, v.ventas?.tienda_principal)) return false;
    return true;
  });
}

/**
 * Qué se puede afirmar de un video SIN pedidos (`ventas: null`). Los pedidos guardados empiezan en `pedidosDesde`:
 * - publicado ese día o después → «Sin ventas desde que se publicó».
 * - publicado antes (o sin fecha de publicación) → «Sin ventas desde el {pedidosDesde}»: de antes no se sabe.
 * - sin pedidos guardados (pedidosDesde null) → «Sin ventas registradas».
 * null si el video tiene ventas.
 */
export type SinVentas = { tipo: 'desde_publicado' } | { tipo: 'desde'; fecha: C.FechaLocal } | { tipo: 'registradas' };

export function sinVentasDe(v: Pick<C.VideoCatalogo, 'ventas' | 'publicado_at'>, pedidosDesde: C.FechaLocal | null): SinVentas | null {
  if (v.ventas !== null) return null;
  if (pedidosDesde === null) return { tipo: 'registradas' };
  if (v.publicado_at === null || fechaLocalDe(v.publicado_at) < pedidosDesde) return { tipo: 'desde', fecha: pedidosDesde };
  return { tipo: 'desde_publicado' };
}

/** Aviso de arriba de «Todos» cuando los videos sin ventas no se pueden listar (contrato: display y misma_cuenta). */
export type AvisoCatalogo = 'sin_metricas' | 'otra_cuenta' | 'sin_comprobar';

export function avisoCatalogo(display: C.CatalogoVideosResponse['display']): AvisoCatalogo | null {
  if (display === null) return 'sin_metricas';
  if (display.misma_cuenta === false) return 'otra_cuenta';
  if (display.misma_cuenta === null) return 'sin_comprobar';
  return null;
}

/** Estado de publicación que se rotula: el video sigue guardado pero no salió en la última lectura, o ya no es público. */
export function estadoRotulado(v: Pick<C.VideoCatalogo, 'publicacion'>): 'no_confirmado' | 'no_publico' | null {
  return v.publicacion === 'no_confirmado' || v.publicacion === 'no_publico' ? v.publicacion : null;
}

/** 45 s · 1:05 min · 1:02:03 h. */
export function textoDuracion(segundos: number): string {
  const s = Math.max(0, Math.round(segundos));
  if (s < 60) return `${s} s`;
  const dos = (x: number): string => String(x).padStart(2, '0');
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}:${dos(m)}:${dos(s % 60)} h` : `${m}:${dos(s % 60)} min`;
}
