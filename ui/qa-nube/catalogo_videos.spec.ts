import { createElement, type ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import type { CatalogoVideosResponse, FilaVideo, VideoCatalogo, VideoCatalogoDetalleResponse } from '../../spec/contrato';
import { epochDeFecha, formato } from '../src/dominio';

// ------------------------------------------------------------------------------------------------ dobles de módulos
// vi.mock sube al principio del archivo: sus fábricas no pueden usar constantes del módulo (solo vi.hoisted o imports
// dinámicos), así que cada una arma sus piezas.
type Props = Record<string, unknown> & { children?: ReactNode };

vi.mock('@/componentes', async () => {
  const { createElement: h } = await import('react');
  const caja = (nombre: string) => (p: Props) =>
    h('div', { 'data-c': nombre }, p.children ?? null, typeof p['titulo'] === 'string' ? p['titulo'] : null, typeof p['texto'] === 'string' ? p['texto'] : null);
  const nada = () => null;
  return {
    AvatarTienda: nada, BandaKpi: caja('BandaKpi'), Boton: caja('Boton'), BotonIcono: nada, CampoTexto: nada,
    Chip: (p: Props) => h('span', { 'data-chip': '' }, p.children ?? null),
    ChipFiltro: (p: Props) => h('button', { 'data-chip-filtro': String(p['conteo'] ?? '') }, p.children ?? null),
    EncabezadoPantalla: (p: Props) => h('header', { 'data-volver': (p['volver'] as { a: string } | undefined)?.a ?? '' }, String(p['titulo'] ?? '')),
    EstadoVacio: caja('EstadoVacio'), Esqueleto: nada, EsqueletoVista: caja('EsqueletoVista'),
    Foto: (p: Props) => h('img', { src: (p['url'] as string | null) ?? undefined, 'data-foto': '' }),
    GraficaColumnas: caja('GraficaColumnas'), Icono: nada,
    Kpi: (p: Props) => h('span', { 'data-kpi': String(p['etiqueta']) }, String(p['valor'])),
    Menu: nada, MiniaturaVideo: nada, PuntoVivo: nada, ReproductorTikTok: nada, Tabla: nada, Tarjeta: caja('Tarjeta'), TarjetaProducto: nada,
    useToast: () => ({ mostrar: () => undefined, cerrar: () => undefined }),
  };
});
const app = vi.hoisted(() => ({ consulta: new URLSearchParams() }));
vi.mock('@/app', async () => {
  const { createElement: h } = await import('react');
  return {
    EnlaceRuta: (p: Props) => h('a', { href: `#${String(p['a'])}` }, p.children ?? null),
    Pantalla: (p: Props) => h('section', null, p.children ?? null),
    navegar: () => undefined,
    useClaseAncho: () => 'expandida',
    usePlataforma: () => 'windows',
    useParametro: () => [null, () => undefined],
    useRuta: () => ({ ruta: '/videos/:id', params: { id: '7400000000000000001' }, consulta: app.consulta }),
  };
});
vi.mock('@/bloques', () => ({ ListaNotas: () => null, TarjetaMuestra: () => null, columnasVideos: () => [] }));
vi.mock('@/plataforma', () => ({ abrirExterno: async () => true, copiarTexto: async () => true, esWindows: () => false }));
/** Estado de cada consulta; `soloActiva`: la consulta solo trae datos si la pantalla la activó (p. ej. el catálogo).
 *  `sesion`: la sesión del hub (undefined = todavía cargando). */
const datos = vi.hoisted(() => ({
  estados: {} as Record<string, { datos?: unknown; error?: unknown; soloActiva?: boolean }>,
  sesion: { capacidades: { catalogo_videos: true } } as unknown,
}));
vi.mock('@/datos', () => {
  const estado = (d: unknown, error: unknown, activa: boolean) => ({
    datos: d, error, cargando: activa && d === undefined && error === null, refrescando: false, fuente: 'hub', copia_at: null,
    con_cambios_pendientes: false, refrescar: async () => undefined,
  });
  return {
    useConsulta: (clave: string, _params: unknown, opciones?: { activa?: boolean }) => {
      const activa = opciones?.activa ?? true;
      const e = datos.estados[clave] ?? {};
      const visible = activa || !e.soloActiva;
      return estado(visible ? e.datos : undefined, visible ? e.error ?? null : null, activa);
    },
    useSesion: () => estado(datos.sesion ?? undefined, null, true),
    useSync: () => ({ estado: null, puede: true, sincronizar: async () => undefined, cancelar: async () => undefined }),
  };
});

import { PestanasVideos } from '../src/pantallas/videos/Cabecera';
import { TarjetaCatalogo, VistaCatalogo } from '../src/pantallas/videos/Catalogo';
import { PantallaVideo } from '../src/pantallas/videos/PantallaVideo';
import { PantallaVideos } from '../src/pantallas/videos/PantallaVideos';
import {
  avisoCatalogo, filtrarCatalogo, nombreCatalogo, ordenCatalogoDe, ordenarCatalogo, sinVentasDe, textoDuracion, vistaVideos,
} from '../src/pantallas/videos/logicaCatalogo';
import { rutaVideo } from '../src/pantallas/videos/util';

// ------------------------------------------------------------------------------------------------ datos sintéticos
const fila = (cid: string, comision: number, ultima: string): FilaVideo => ({
  content_id: cid, titulo: null, miniatura: null, enlace: `https://www.tiktok.com/@creadora/video/${cid}`, pedidos: 3, pedidos_validos: 2,
  unidades: 3, ventas_centavos: comision * 10, comision_estimada_centavos: comision, tasa_reembolso: 0, participacion: 0.1,
  primera_venta: '2026-01-10', ultima_venta: ultima, productos: 1, tienda_principal: 'Tienda Sintética', muestras_vinculadas: [],
});
const video = (cid: string, extra: Partial<VideoCatalogo> = {}): VideoCatalogo => ({
  content_id: cid, origen: 'display', publicacion: 'publico', descripcion: `Video ${cid} #moda`, portada: `/img/v/${cid}?v=abcdef12`,
  enlace: `https://www.tiktok.com/@creadora/video/${cid}`, publicado_at: null, duracion_s: 30, vistas: 1200, likes: 80, comentarios: 4,
  compartidos: 2, metricas_at: epochDeFecha('2026-11-17', 9), ventas: null, muestras_vinculadas: [], ...extra,
});

describe('orden del catálogo (igual que el hub)', () => {
  const items = [
    video('7400000000000000005'),
    video('7400000000000000004'),
    video('7400000000000000003', { origen: 'ventas', ventas: fila('7400000000000000003', 500, '2026-02-01'), vistas: null }),
    video('7400000000000000002', { origen: 'ventas', ventas: fila('7400000000000000002', 900, '2026-03-01'), vistas: 50 }),
    video('7400000000000000001', { publicado_at: epochDeFecha('2026-04-01', 12), vistas: 9000 }),
    video('7400000000000000006', { publicado_at: epochDeFecha('2026-05-01', 12), vistas: 10 }),
  ];
  const ids = (xs: VideoCatalogo[]) => xs.map((v) => v.content_id.slice(-1));

  test('publicado: lo más nuevo primero; sin fecha, por última venta y al final los que nunca vendieron', () => {
    expect(ids(ordenarCatalogo(items, 'publicado'))).toEqual(['6', '1', '2', '3', '4', '5']);
  });
  test('vistas: sin cifra al final', () => {
    expect(ids(ordenarCatalogo(items, 'vistas'))).toEqual(['1', '4', '5', '2', '6', '3']);
  });
  test('comisión: los que no vendieron al final, por ID', () => {
    expect(ids(ordenarCatalogo(items, 'comision'))).toEqual(['2', '3', '1', '4', '5', '6']);
  });
  test('«Más vistas» solo con métricas; un orden desconocido vuelve al de siempre', () => {
    expect(ordenCatalogoDe('vistas', false)).toBe('publicado');
    expect(ordenCatalogoDe('vistas', true)).toBe('vistas');
    expect(ordenCatalogoDe('comision', false)).toBe('comision');
    expect(ordenCatalogoDe('pedidos', true)).toBe('publicado');
    expect(ordenCatalogoDe(null, true)).toBe('publicado');
  });
});

describe('nunca se inventa una cifra', () => {
  const desde = '2026-03-01';
  test('publicado desde que hay pedidos guardados: «Sin ventas desde que se publicó»', () => {
    expect(sinVentasDe(video('1', { publicado_at: epochDeFecha('2026-03-01', 8) }), desde)).toEqual({ tipo: 'desde_publicado' });
  });
  test('publicado antes de los pedidos guardados o sin fecha: solo se afirma desde ese día', () => {
    expect(sinVentasDe(video('1', { publicado_at: epochDeFecha('2026-02-28', 23) }), desde)).toEqual({ tipo: 'desde', fecha: desde });
    expect(sinVentasDe(video('1', { publicado_at: null }), desde)).toEqual({ tipo: 'desde', fecha: desde });
  });
  test('sin pedidos guardados: «Sin ventas registradas»; con ventas no aplica', () => {
    expect(sinVentasDe(video('1'), null)).toEqual({ tipo: 'registradas' });
    expect(sinVentasDe(video('1', { ventas: fila('1', 100, '2026-03-02') }), desde)).toBeNull();
  });
  test('la tarjeta sin ventas dice «Sin ventas» y no pinta comisión ni pedidos', () => {
    const html = renderToStaticMarkup(createElement(TarjetaCatalogo, {
      video: video('7400000000000000009', { publicado_at: epochDeFecha('2026-06-01', 12) }), pedidosDesde: desde, conMetricas: true,
    }));
    expect(html).toContain('Sin ventas');
    expect(html).toContain('desde que se publicó');
    expect(html).not.toContain('Comisión');
    expect(html).not.toContain('$0');
    expect(html).toContain('/img/v/7400000000000000009');
  });
  test('la tarjeta con ventas muestra la comisión y los pedidos válidos de toda la vida', () => {
    const v = video('7400000000000000008', { origen: 'display_y_ventas', ventas: fila('7400000000000000008', 123456, '2026-11-01') });
    const html = renderToStaticMarkup(createElement(TarjetaCatalogo, { video: v, pedidosDesde: desde, conMetricas: true }));
    expect(html).toContain(formato.dinero(123456));
    expect(html).toContain('Comisión');
    expect(html).not.toContain('Sin ventas');
  });
  test('«Ya no es público» se rotula y entra en el nombre accesible', () => {
    const html = renderToStaticMarkup(createElement(TarjetaCatalogo, {
      video: video('7400000000000000007', { publicacion: 'no_publico', descripcion: 'Reseña de bolso #tiktokshop' }), pedidosDesde: null, conMetricas: true,
    }));
    expect(html).toContain('Ya no es público');
    expect(html).toContain('aria-label="Ver Reseña de bolso. Ya no es público: Ya no está entre tus videos públicos de TikTok. Se muestran sus últimas cifras guardadas. Sin ventas registradas. 1,200 vistas al ');
  });
  test('una tarjeta rotulada lleva la fecha de sus propias cifras', () => {
    const html = renderToStaticMarkup(createElement(TarjetaCatalogo, {
      video: video('7400000000000000005', { publicacion: 'no_confirmado', metricas_at: epochDeFecha('2026-10-03', 9) }), pedidosDesde: null, conMetricas: true,
    }));
    expect(html).toContain(`1,200 vistas al ${formato.fechaCorta(epochDeFecha('2026-10-03', 9)).replace(/ /g, '\u00a0')}`);
  });
  test('sin cifras de TikTok con las métricas conectadas, lo dice', () => {
    const html = renderToStaticMarkup(createElement(TarjetaCatalogo, {
      video: video('7400000000000000006', { vistas: null, origen: 'ventas', ventas: fila('7400000000000000006', 10, '2026-11-01') }), pedidosDesde: null, conMetricas: true,
    }));
    expect(html).toContain('Sin cifras de TikTok');
  });
});

describe('nombre, búsqueda y utilidades', () => {
  test('el nombre es la descripción de TikTok sin hashtags; sin ella, la de sus ventas o el ID corto', () => {
    expect(nombreCatalogo(video('7400000000000000001', { descripcion: '  Look de otoño #moda #ootd ' }))).toBe('Look de otoño');
    expect(nombreCatalogo({ content_id: '7400000000000000001', descripcion: null, ventas: { ...fila('7400000000000000001', 1, '2026-01-01'), descripcion: 'Desde ventas' } }))
      .toBe('Desde ventas');
    expect(nombreCatalogo({ content_id: '7400000000000000001', descripcion: null, ventas: null })).toMatch(/^Video /);
  });
  test('busca por nombre, ID o tienda y filtra los que no tienen ventas', () => {
    const a = video('7400000000000000011', { descripcion: 'Bolso de piel' });
    const b = video('7400000000000000012', { descripcion: 'Tenis blancos', ventas: fila('7400000000000000012', 10, '2026-11-01') });
    expect(filtrarCatalogo([a, b], { q: 'bolso', soloSinVentas: false })).toEqual([a]);
    expect(filtrarCatalogo([a, b], { q: '7400000000000000012', soloSinVentas: false })).toEqual([b]);
    expect(filtrarCatalogo([a, b], { q: 'sintética', soloSinVentas: false })).toEqual([b]);
    expect(filtrarCatalogo([a, b], { q: '', soloSinVentas: true })).toEqual([a]);
  });
  test('duración legible', () => {
    expect(textoDuracion(45)).toBe('45 s');
    expect(textoDuracion(65)).toBe('1:05 min');
    expect(textoDuracion(3723)).toBe('1:02:03 h');
  });
  test('el detalle abierto desde «Todos» lo recuerda en la ruta', () => {
    expect(rutaVideo('7400000000000000001')).toBe('/videos/7400000000000000001');
    expect(rutaVideo('7400000000000000001', 'todos')).toBe('/videos/7400000000000000001?desde=todos');
  });
});

describe('qué vista se arma', () => {
  test('abre en «Con ventas»; «Todos» solo con el catálogo del hub', () => {
    expect(vistaVideos({ segmento: null, conCatalogo: true, sinCatalogo: false, sesionCargando: false })).toBe('ventas');
    expect(vistaVideos({ segmento: 'todos', conCatalogo: true, sinCatalogo: false, sesionCargando: false })).toBe('catalogo');
    expect(vistaVideos({ segmento: 'todos', conCatalogo: false, sinCatalogo: false, sesionCargando: false })).toBe('ventas');
    expect(vistaVideos({ segmento: 'todos', conCatalogo: false, sinCatalogo: false, sesionCargando: true })).toBe('espera');
    expect(vistaVideos({ segmento: 'todos', conCatalogo: true, sinCatalogo: true, sesionCargando: false })).toBe('ventas');
  });
  test('las pestañas marcan la activa y llevan a cada vista', () => {
    const html = renderToStaticMarkup(createElement(PestanasVideos, { activa: 'todos' }));
    expect(html).toContain('href="#/videos"');
    expect(html).toContain('href="#/videos?segmento=todos" aria-current="page"');
    expect(html.match(/aria-current/g)?.length).toBe(1);
  });
  test('aviso: sin métricas, otra cuenta o sin poder comprobarlo', () => {
    expect(avisoCatalogo(null)).toBe('sin_metricas');
    expect(avisoCatalogo({ ultima_sync_at: 1, misma_cuenta: false })).toBe('otra_cuenta');
    expect(avisoCatalogo({ ultima_sync_at: 1, misma_cuenta: null })).toBe('sin_comprobar');
    expect(avisoCatalogo({ ultima_sync_at: 1, misma_cuenta: true })).toBeNull();
  });
});

describe('vista «Todos»', () => {
  const respuesta = (extra: Partial<CatalogoVideosResponse>): CatalogoVideosResponse => ({
    items: [video('7400000000000000021'), video('7400000000000000022', { origen: 'display_y_ventas', ventas: fila('7400000000000000022', 700, '2026-11-02') })],
    total: 2, data_version: 7, display: { ultima_sync_at: epochDeFecha('2026-11-17', 9), misma_cuenta: true }, pedidos_desde: '2026-01-01', ...extra,
  });
  const pintar = () => renderToStaticMarkup(createElement(VistaCatalogo, { alListo: vi.fn() }));
  beforeEach(() => { datos.estados = {}; });

  test('con la cuenta del creador lista también los que no venden y ofrece filtrarlos', () => {
    datos.estados['catalogo_videos'] = { datos: respuesta({}) };
    const html = pintar();
    expect(html).toContain('data-chip-filtro="1"');
    expect(html).toContain('2 videos');
    expect(html).toContain('Publicados y con ventas');
    expect(html).not.toContain('Conecta las métricas');
  });
  test('sin métricas de TikTok lo explica y no promete videos sin ventas', () => {
    datos.estados['catalogo_videos'] = { datos: respuesta({ display: null, items: [respuesta({}).items[1] as VideoCatalogo], total: 1 }) };
    const html = pintar();
    expect(html).toContain('Conecta las métricas de TikTok');
    expect(html).toContain('Solo los que tienen ventas');
    expect(html).not.toContain('data-chip-filtro');
  });
  test('si la lista llegó recortada lo dice', () => {
    datos.estados['catalogo_videos'] = { datos: respuesta({ total: 2500 }) };
    expect(pintar()).toContain('Se muestran los primeros 2 de 2,500 videos según el orden elegido; la búsqueda y el filtro solo cubren esos.');
  });
  test('con la cuenta de otra persona (o sin comprobarla) el vacío no promete videos sin ventas', () => {
    for (const misma of [false, null]) {
      datos.estados['catalogo_videos'] = { datos: respuesta({ items: [], total: 0, display: { ultima_sync_at: 1, misma_cuenta: misma } }) };
      const html = pintar();
      expect(html).toContain('Cuando un video venda, aparecerá aquí.');
      expect(html).not.toContain('Cuando publiques');
    }
  });
});

describe('detalle de un video sin ventas', () => {
  const noEncontrado = { codigo: 'no_encontrado', mensaje: 'No encontramos ese video.', http: 404 };
  const detalle: VideoCatalogoDetalleResponse = {
    video: video('7400000000000000001', { descripcion: 'Probador de vestidos #moda', publicado_at: epochDeFecha('2026-10-01', 10) }),
    ventas: null, tendencia: [],
  };
  beforeEach(() => {
    datos.sesion = { capacidades: { catalogo_videos: true } };
    app.consulta = new URLSearchParams();
    datos.estados = {
      video: { error: noEncontrado },
      catalogo_video: { datos: detalle, soloActiva: true },
      catalogo_videos: { datos: { items: [], total: 0, data_version: 1, display: null, pedidos_desde: '2026-01-01' }, soloActiva: true },
    };
  });

  test('con el catálogo, el 404 de ventas se convierte en el detalle con sus cifras de TikTok', () => {
    const html = renderToStaticMarkup(createElement(PantallaVideo));
    expect(html).toContain('Probador de vestidos');
    expect(html).toContain('Este video aún no tiene ventas desde que se publicó.');
    expect(html).toContain('data-kpi="Vistas"');
    expect(html).not.toContain('No encontramos este video');
    expect(html).not.toContain('data-kpi="Comisión"');
  });
  test('mientras no se sabe desde cuándo hay pedidos guardados, solo dice lo seguro', () => {
    datos.estados['catalogo_videos'] = {};
    const html = renderToStaticMarkup(createElement(PantallaVideo));
    expect(html).toContain('Este video no tiene ventas registradas en Corte.');
    expect(html).not.toContain('Corte todavía no tiene pedidos guardados');
  });
  test('si un refresco de ventas falla por otra causa, el detalle que ya se veía se queda', () => {
    datos.estados['video'] = { error: { codigo: 'red', mensaje: 'Sin conexión.', http: 0 } };
    datos.estados['catalogo_video'] = { datos: detalle };
    const html = renderToStaticMarkup(createElement(PantallaVideo));
    expect(html).toContain('Probador de vestidos');
    expect(html).not.toContain('Sin conexión.');
  });
  test('mientras la sesión carga, un 404 de ventas no dice «No encontramos este video»', () => {
    datos.sesion = undefined;
    const html = renderToStaticMarkup(createElement(PantallaVideo));
    expect(html).not.toContain('No encontramos este video');
    expect(html).toContain('data-c="EsqueletoVista"');
  });
  test('sin el catálogo sigue el «No encontramos este video» de siempre', () => {
    datos.sesion = { capacidades: { catalogo_videos: false } };
    const html = renderToStaticMarkup(createElement(PantallaVideo));
    expect(html).toContain('No encontramos este video');
    expect(html).not.toContain('Probador de vestidos');
  });
  test('abierto desde «Todos», «‹ Videos» vuelve a esa pestaña', () => {
    app.consulta = new URLSearchParams('desde=todos');
    expect(renderToStaticMarkup(createElement(PantallaVideo))).toContain('data-volver="/videos?segmento=todos"');
    app.consulta = new URLSearchParams();
    expect(renderToStaticMarkup(createElement(PantallaVideo))).toContain('data-volver="/videos"');
  });
});

describe('pantalla de videos: pestañas', () => {
  beforeEach(() => {
    datos.sesion = { capacidades: { catalogo_videos: true } };
    datos.estados = {};
  });
  const pintar = () => renderToStaticMarkup(createElement(PantallaVideos));

  test('con el catálogo abre en «Con ventas» y ofrece «Todos»', () => {
    const html = pintar();
    expect(html).toContain('href="#/videos" aria-current="page"');
    expect(html).toContain('href="#/videos?segmento=todos"');
  });
  test('sin el catálogo no hay pestañas', () => {
    datos.sesion = { capacidades: { catalogo_videos: false } };
    expect(pintar()).not.toContain('segmento=todos');
  });
  test('si el catálogo ya respondió 404, las pestañas no vuelven al regresar a la pantalla', () => {
    datos.estados['catalogo_videos'] = { error: { codigo: 'no_encontrado', mensaje: 'No existe.', http: 404 } };
    expect(pintar()).not.toContain('segmento=todos');
  });
});
