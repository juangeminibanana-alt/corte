import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, expect, test, vi } from 'vitest';
import type * as C from '../../spec/contrato';
import { FilaMuestra } from '../src/pantallas/muestras/FilaMuestra';
import { FILTROS_VACIOS, contarFiltros, filtrar } from '../src/pantallas/muestras/logica';

const gesto = vi.hoisted(() => vi.fn(() => ({ dx: 0, manejadores: {}, arrastrando: false })));
vi.mock('@/componentes', () => ({
  Foto: (p: { url: string; alt: string }) => createElement('img', { src: p.url, alt: p.alt }),
  Icono: () => null,
  Menu: (p: { etiqueta: string }) => createElement('button', null, p.etiqueta),
}));
vi.mock('../src/bloques/muestras/TarjetaMuestra', () => ({
  anuncioMuestra: (m: C.MuestraVista) => `${m.producto.titulo}. ${m.variante}`,
  useDeslizar: gesto,
}));
vi.mock('../src/bloques/muestras/botones', () => ({
  useAccionPrincipal: () => 'planear',
  BotonAccionMuestra: () => createElement('button', null, 'Planear'),
}));
vi.mock('../src/bloques/muestras/menuMuestra', () => ({ useOpcionesMuestra: () => [] }));
vi.mock('../src/bloques/muestras/chips', () => ({
  textoAvance: () => 'Por planear', textoTikTok: (m: C.MuestraVista) => m.etiqueta,
}));

const muestra = {
  application_id: '100', grupo: 'vencida', etiqueta: 'Vencida', motivo: '', recibida: true,
  variante: 'Azul / M', prioridad: 'alta', posicion_cola: 3, razones: [],
  producto: { product_id: '200', titulo: 'Producto de prueba', titulo_corto: null,
    imagen: '/img/p/200?v=aaaaaaaa', categoria: null },
  tienda: { tienda_key: 'tienda-a', nombre: 'Tienda de prueba' },
  avance: { etapa: 'por_planear', fijada: false, fecha_planeada: null },
  avisos: { promesa: null, promesa_vencida: false, copiado_sin_confirmar: false },
  ventas_producto: { pedidos_validos: 0 },
} as C.MuestraVista;

beforeEach(() => gesto.mockClear());

test('la fila conserva foto, tienda, variante, urgencia y acciones de la muestra', () => {
  const html = renderToStaticMarkup(createElement(FilaMuestra, { muestra, alAbrir: vi.fn(), android: true, deslizable: true }));
  for (const texto of ['Producto de prueba', 'Tienda de prueba', 'Azul / M', 'Vencida', 'Planear', '/img/p/200?v=aaaaaaaa']) expect(html).toContain(texto);
  expect(gesto).toHaveBeenCalledWith(muestra, true);
});

test('una muestra que no se puede etiquetar conserva menú pero no ofrece Planear ni swipe', () => {
  const bloqueada = { ...muestra, prioridad: 'no_se_puede_etiquetar' as const };
  const html = renderToStaticMarkup(createElement(FilaMuestra, { muestra: bloqueada, alAbrir: vi.fn(), android: true, deslizable: true }));
  expect(html).toContain('No se puede etiquetar');
  expect(html).toContain('Más acciones');
  expect(html).not.toContain('>Planear<');
  expect(gesto).toHaveBeenCalledWith(bloqueada, false);
});

test('el modo de selección Android mantiene la casilla y suprime acción/gesto por fila', () => {
  const html = renderToStaticMarkup(createElement(FilaMuestra, { muestra, alAbrir: vi.fn(), android: true,
    marcable: true, marcada: true, deslizable: true, alMarcar: vi.fn() }));
  expect(html).toContain('aria-checked="true"');
  expect(html).toContain('type="checkbox"');
  expect(html).not.toContain('>Planear<');
  expect(gesto).toHaveBeenCalledWith(muestra, false);
});

test('tienda combina con los filtros existentes y las preferencias anteriores siguen válidas', () => {
  const otra = { ...muestra, application_id: '101', tienda: { ...muestra.tienda, tienda_key: 'tienda-b' } };
  expect(filtrar([muestra, otra], FILTROS_VACIOS)).toHaveLength(2);
  expect(filtrar([muestra, otra], { ...FILTROS_VACIOS, tienda: 'tienda-a', q: 'Azul', grupos: ['vencida'] })).toEqual([muestra]);
  expect(filtrar([muestra, otra], { ...FILTROS_VACIOS, tienda: 'tienda-a', q: 'Inexistente' })).toEqual([]);
  expect(contarFiltros({ ...FILTROS_VACIOS, tienda: 'tienda-a' })).toBe(1);
});
