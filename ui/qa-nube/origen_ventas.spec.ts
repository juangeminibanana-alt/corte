import { createElement, type ReactNode } from 'react';
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type * as C from '../../spec/contrato';
import { SeccionOrigen } from '../src/pantallas/productos/FichaCompleta';
import { slotsDeEnlace, vistaOrigen } from '../src/pantallas/productos/logicaFicha';

vi.mock('@/app', () => ({ navegar: vi.fn() }));
vi.mock('@/bloques', () => ({ BotonGuardarImagen: () => null }));
vi.mock('@/plataforma', () => ({ abrirExterno: vi.fn() }));
vi.mock('@/componentes', () => ({
  Tarjeta: (p: { children: ReactNode }) => createElement('div', null, p.children),
  // Como la barra real (BarraApilada.tsx): figura con su título en un <h3>; aquí basta con lo que dice cada parte, su
  // color (slot) y la tabla gemela, sin medir el ancho.
  BarraApilada: (p: { titulo: string; partes: Array<{ etiqueta: string; texto: string; estilo: string; slot?: number }>; tablaGemela: { filas: string[][] } }) =>
    createElement('figure', { 'aria-label': p.titulo },
      createElement('h3', null, p.titulo),
      ...p.partes.map((x) => createElement('span', { key: x.etiqueta, 'data-estilo': x.estilo, 'data-slot': x.slot ?? '' }, `${x.etiqueta}: ${x.texto}`)),
      createElement('table', null, createElement('tbody', null,
        ...p.tablaGemela.filas.map((f) => createElement('tr', { key: f[0] }, ...f.map((c, i) => createElement('td', { key: i }, c))))))),
}));
afterEach(cleanup);

// Mediodía en México; las fechas se comprueban sin el año (fechaCorta lo agrega fuera del año en curso).
const DIA = 86_400;
const HASTA_HISTORICO = 1_786_730_400;           // 2026-08-14 12:00 CST
const DESDE_ACTUAL = HASTA_HISTORICO + 30 * DIA;  // 2026-09-13
const HASTA_ACTUAL = HASTA_HISTORICO + 95 * DIA;  // 2026-11-17

const historico = (cambios: Partial<C.OrigenVentas> = {}): C.OrigenVentas => ({
  lineas: 40,
  por_tipo_contenido: [{ tipo: 'VIDEO', texto: 'Video', lineas: 30 }, { tipo: null, texto: 'Sin dato', lineas: 10 }],
  por_tipo_enlace: [
    { tipo: 'SPECIFIC', texto: 'Enlace para un publicador', lineas: 26 },
    { tipo: null, texto: 'Sin enlace reportado', lineas: 10 },
    { tipo: 'GENERAL', texto: 'Enlace general', lineas: 4 },
  ],
  fuente: 'orders_trace_search_202505_retirada', pedidos: 38, desde_at: HASTA_HISTORICO - 90 * DIA, hasta_at: HASTA_HISTORICO,
  ...cambios,
});

const actual = (cambios: Partial<C.OrigenVentasActual> = {}): C.OrigenVentasActual => ({
  lineas: 20, con_enlace: 5,
  por_tipo_enlace: [
    { tipo: null, texto: 'Sin enlace reportado', lineas: 15 },
    { tipo: 'GENERAL', texto: 'Enlace general', lineas: 4 },
    { tipo: 'RARO', texto: 'RARO', lineas: 1 },
  ],
  lineas_sin_dato: 3, pedidos: 19, fuente: 'orders_search_202410', desde_at: DESDE_ACTUAL, hasta_at: HASTA_ACTUAL,
  capturada_at: HASTA_ACTUAL + 3_600,
  ...cambios,
});

function detalle(origen: C.OrigenVentas | null, origenActual?: C.OrigenVentasActual | null): C.ProductoDetalleResponse {
  const extendido = {
    galeria: [], vitrina: null, muestra: null, solicitudes_recuperadas: [], planes_dirigidos: [], comision_real: null,
    parecidos: null, origen_ventas: origen, origen_ventas_aviso: null,
    ...(origenActual !== undefined ? { origen_ventas_actual: origenActual } : {}),
  } satisfies C.ProductoExtendido;
  return { product_id: '100', extendido } as unknown as C.ProductoDetalleResponse;
}

const bloque = (cual: 'actual' | 'historico'): HTMLElement | null => document.querySelector(`[data-origen="${cual}"]`);
const filas = (el: HTMLElement): string[][] => Array.from(el.querySelectorAll('tr')).map((tr) => Array.from(tr.children).map((td) => td.textContent ?? ''));

test('solo el histórico: un grupo con su periodo, sus dos barras y partes sobre sus propias líneas', () => {
  render(createElement(SeccionOrigen, { d: detalle(historico()) }));
  expect(screen.getByRole('heading', { level: 2, name: 'De dónde vienen tus ventas' })).toBeTruthy();
  expect(screen.getByText(/«Sin enlace reportado» no dice de dónde vino la venta/)).toBeTruthy();
  expect(bloque('actual')).toBeNull();
  const grupo = screen.getByRole('group', { name: /^Histórico hasta el 14 ago/ });
  expect(grupo).toBe(bloque('historico'));
  const vista = within(grupo);
  expect(vista.getByText('40 pedidos con su origen registrado')).toBeTruthy();
  // Un solo bloque: las gráficas conservan su título corto; el rótulo del periodo no es un encabezado.
  expect(vista.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual(['Tipo de contenido', 'Tipo de enlace']);
  expect(vista.getByText('Sin enlace reportado: 10').getAttribute('data-estilo')).toBe('neutro');
  expect(vista.getByText('Enlace para un publicador: 26').getAttribute('data-estilo')).toBe('solido');
  expect(filas(grupo).find((f) => f[0] === 'Enlace para un publicador')?.[2]).toMatch(/^65\s?%$/);
});

test('un hub anterior a la rev. 6 (sin periodo ni bloque actual) deja la sección como antes', () => {
  const { desde_at: _d, hasta_at: _h, fuente: _f, pedidos: _p, ...viejo } = historico();
  render(createElement(SeccionOrigen, { d: detalle(viejo) }));
  expect(screen.getByText('40 pedidos con su origen registrado')).toBeTruthy();
  expect(screen.queryByText(/^Histórico/)).toBeNull();
  expect(screen.queryByRole('group')).toBeNull();
  expect(screen.queryByText(/no dice de dónde vino la venta/)).toBeNull();
  expect(screen.getAllByRole('figure').map((f) => f.getAttribute('aria-label'))).toEqual(['Tipo de contenido', 'Tipo de enlace']);
});

test('con enlaces reportados: el bloque reciente va primero, aparte y con nombres que no se repiten', () => {
  render(createElement(SeccionOrigen, { d: detalle(historico(), actual()) }));
  const a = screen.getByRole('group', { name: /^Pedidos del 13 sep.* al 17 nov/ });
  const h = screen.getByRole('group', { name: /^Histórico hasta el 14 ago/ });
  expect(a.compareDocumentPosition(h) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  // Cada gráfica nombra su bloque: ninguna figura ni botón comparte nombre.
  const nombres = screen.getAllByRole('figure').map((f) => f.getAttribute('aria-label'));
  expect(nombres).toEqual(['Tipo de enlace en estos pedidos', 'Tipo de contenido en el histórico', 'Tipo de enlace en el histórico']);
  const va = within(a);
  expect(va.getByText('20 pedidos')).toBeTruthy();
  expect(va.getByText('3 pedidos más todavía sin este dato')).toBeTruthy();
  expect(va.getByText('Sin enlace reportado: 15').getAttribute('data-estilo')).toBe('neutro');
  expect(va.getByText('RARO: 1')).toBeTruthy();                         // un valor nuevo se muestra tal cual
  // Porcentajes sobre las líneas de cada bloque, nunca sobre la suma de los dos.
  expect(filas(a).find((f) => f[0] === 'Enlace general')?.[2]).toMatch(/^20\s?%$/);
  expect(filas(h).find((f) => f[0] === 'Enlace general')?.[2]).toMatch(/^10\s?%$/);
  expect(within(h).getByText('40 pedidos con su origen registrado')).toBeTruthy();
  // El mismo tipo de enlace tiene el mismo color en las dos barras, aunque su lugar en cada una sea distinto.
  const slot = (el: HTMLElement, etiqueta: string) => within(el).getByText(new RegExp(`^${etiqueta}:`)).getAttribute('data-slot');
  expect(slot(a, 'Enlace general')).toBe('2');
  expect(slot(h, 'Enlace general')).toBe('2');
  expect(slot(h, 'Enlace para un publicador')).toBe('1');
  expect(slot(a, 'RARO')).toBe('3');
});

test('sin datos pendientes no se agrega la nota de «sin este dato»', () => {
  render(createElement(SeccionOrigen, { d: detalle(null, actual({ lineas_sin_dato: 0 })) }));
  const a = bloque('actual') as HTMLElement;
  expect(within(a).getByText('20 pedidos')).toBeTruthy();
  expect(within(a).queryByText(/sin este dato/)).toBeNull();
  expect(within(a).getByRole('figure').getAttribute('aria-label')).toBe('Tipo de enlace');   // único bloque: título corto
  expect(bloque('historico')).toBeNull();
});

test('si TikTok no reportó ningún enlace el bloque reciente no aparece', () => {
  const sinEnlaces = actual({ con_enlace: 0, por_tipo_enlace: [{ tipo: null, texto: 'Sin enlace reportado', lineas: 20 }] });
  const { container } = render(createElement(SeccionOrigen, { d: detalle(null, sinEnlaces) }));
  expect(container.innerHTML).toBe('');
  cleanup();
  render(createElement(SeccionOrigen, { d: detalle(historico(), sinEnlaces) }));
  expect(bloque('actual')).toBeNull();
  expect(bloque('historico')).not.toBeNull();
});

test('vistaOrigen: qué bloques muestra cada combinación', () => {
  expect(vistaOrigen(detalle(null))).toBeNull();
  expect(vistaOrigen(detalle(null, null))).toBeNull();
  expect(vistaOrigen(detalle(historico({ lineas: 0 }), actual({ lineas: 0, con_enlace: 0, por_tipo_enlace: [] })))).toBeNull();
  expect(vistaOrigen(detalle(historico()))?.actual).toBeNull();
  expect(vistaOrigen(detalle(null, actual()))).toEqual({ actual: actual(), historico: null });
  expect(vistaOrigen({ product_id: '1' } as unknown as C.ProductoDetalleResponse)).toBeNull();
});

test('slotsDeEnlace: color fijo por tipo, los desconocidos en orden alfabético', () => {
  const slot = slotsDeEnlace([actual().por_tipo_enlace, [{ tipo: 'ZETA', texto: 'ZETA', lineas: 1 }, { tipo: 'ALFA', texto: 'ALFA', lineas: 1 }]]);
  expect(['SPECIFIC', 'GENERAL', 'ALFA', 'RARO', 'ZETA'].map(slot)).toEqual([1, 2, 3, 4, 5]);
});
