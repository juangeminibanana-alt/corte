import { createElement, type ReactNode } from 'react';
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type * as C from '../../spec/contrato';
import { SeccionOrigen } from '../src/pantallas/productos/FichaCompleta';
import { vistaOrigen } from '../src/pantallas/productos/logicaFicha';

vi.mock('@/app', () => ({ navegar: vi.fn() }));
vi.mock('@/bloques', () => ({ BotonGuardarImagen: () => null }));
vi.mock('@/plataforma', () => ({ abrirExterno: vi.fn() }));
vi.mock('@/componentes', () => ({
  Tarjeta: (p: { children: ReactNode }) => createElement('div', null, p.children),
  // La barra real mide el ancho; aquí basta con lo que dice cada parte y la tabla gemela.
  BarraApilada: (p: { titulo: string; partes: Array<{ etiqueta: string; texto: string; estilo: string }>; tablaGemela: { filas: string[][] } }) =>
    createElement('figure', { 'aria-label': p.titulo },
      createElement('h4', null, p.titulo),
      ...p.partes.map((x) => createElement('span', { key: x.etiqueta, 'data-estilo': x.estilo }, `${x.etiqueta}: ${x.texto}`)),
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
  por_tipo_enlace: [{ tipo: 'SPECIFIC', texto: 'Enlace para un publicador', lineas: 25 }, { tipo: null, texto: 'Sin enlace reportado', lineas: 15 }],
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

test('solo el histórico: sus dos barras, rotulado con la fecha hasta la que llega', () => {
  render(createElement(SeccionOrigen, { d: detalle(historico()) }));
  expect(screen.getByRole('heading', { level: 2, name: 'De dónde vienen tus ventas' })).toBeTruthy();
  expect(screen.getByText(/«Sin enlace reportado» no dice de dónde vino la venta/)).toBeTruthy();
  expect(bloque('actual')).toBeNull();
  const h = bloque('historico');
  expect(h).not.toBeNull();
  const vista = within(h as HTMLElement);
  expect(vista.getByRole('heading', { level: 3 }).textContent).toMatch(/^Histórico hasta el 14 ago/);
  expect(vista.getByText('40 pedidos con su origen registrado')).toBeTruthy();
  expect(vista.getByRole('figure', { name: 'Tipo de contenido' })).toBeTruthy();
  expect(vista.getByRole('figure', { name: 'Tipo de enlace' })).toBeTruthy();
  // El balde nulo va en neutro y la parte se calcula sobre las líneas del propio histórico.
  expect(vista.getByText('Sin enlace reportado: 15').getAttribute('data-estilo')).toBe('neutro');
  expect(vista.getByText('Enlace para un publicador: 25').getAttribute('data-estilo')).toBe('solido');
});

test('un hub anterior a la rev. 6 (sin periodo ni bloque actual) deja la sección como antes', () => {
  const { desde_at: _d, hasta_at: _h, fuente: _f, pedidos: _p, ...viejo } = historico();
  render(createElement(SeccionOrigen, { d: detalle(viejo) }));
  expect(screen.getByText('40 pedidos con su origen registrado')).toBeTruthy();
  expect(screen.queryByRole('heading', { level: 3 })).toBeNull();
  expect(screen.queryByText(/no dice de dónde vino la venta/)).toBeNull();
  expect(screen.getAllByRole('figure')).toHaveLength(2);
});

test('con enlaces reportados: el bloque reciente va primero y aparte del histórico, sin sumarlos', () => {
  render(createElement(SeccionOrigen, { d: detalle(historico(), actual()) }));
  const a = bloque('actual') as HTMLElement;
  const h = bloque('historico') as HTMLElement;
  expect(a.compareDocumentPosition(h) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  const va = within(a);
  expect(va.getByRole('heading', { level: 3 }).textContent).toMatch(/^Pedidos del 13 sep.* al 17 nov/);
  expect(va.getByText('20 pedidos · 3 más sin dato todavía')).toBeTruthy();
  expect(va.getAllByRole('figure')).toHaveLength(1);
  expect(va.getByText('Sin enlace reportado: 15').getAttribute('data-estilo')).toBe('neutro');
  expect(va.getByText('Enlace general: 4').getAttribute('data-estilo')).toBe('solido');
  expect(va.getByText('RARO: 1')).toBeTruthy();                         // un valor nuevo se muestra tal cual
  // Porcentajes sobre las 20 líneas del bloque, no sobre 20 + 40.
  const filas = Array.from(a.querySelectorAll('tr')).map((tr) => Array.from(tr.children).map((td) => td.textContent));
  expect(filas.find((f) => f[0] === 'Enlace general')?.[2]).toMatch(/^20\s?%$/);
  expect(within(h).getByText('40 pedidos con su origen registrado')).toBeTruthy();
});

test('sin datos pendientes no se agrega la cuenta de «sin dato»', () => {
  render(createElement(SeccionOrigen, { d: detalle(null, actual({ lineas_sin_dato: 0 })) }));
  expect(within(bloque('actual') as HTMLElement).getByText('20 pedidos')).toBeTruthy();
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
