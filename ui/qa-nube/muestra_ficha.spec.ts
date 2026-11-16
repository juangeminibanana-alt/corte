import { createElement } from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import type { MuestraVista } from '../../spec/contrato';
import { FichaProductoMuestra } from '../src/pantallas/muestras/FichaProductoMuestra';

const consulta = vi.hoisted(() => ({ valor: {} as Record<string, unknown>, pedir: vi.fn() }));
vi.mock('@/datos', () => ({ useConsulta: (...args: unknown[]) => { consulta.pedir(...args); return consulta.valor; } }));
vi.mock('@/app', () => ({ EnlaceRuta: (p: { a: string; children: unknown }) => createElement('a', { href: p.a }, p.children as string) }));
vi.mock('@/componentes', () => ({ Boton: () => null }));
vi.mock('../src/pantallas/productos/FichaCompleta', () => ({
  GaleriaProducto: (p: { productoId: string; fotos: string[]; principal: string | null }) => createElement('div', { 'data-testid': 'galeria', 'data-producto': p.productoId, 'data-principal': p.principal },
    ...p.fotos.map((src) => createElement('img', { key: src, src, alt: 'Foto ampliada' }))),
  ListaSkus: (p: { skus: Array<{ variante: string }> }) => createElement('p', null, p.skus.map((s) => s.variante).join(', ')),
}));
beforeEach(() => { consulta.pedir.mockClear(); consulta.valor = { datos: null, cargando: false, error: null, fuente: 'hub' }; });
afterEach(cleanup);

const muestra = (id: string, pid: string): MuestraVista => ({
  application_id: id, producto: { product_id: pid, imagen: `/img/p/${pid}?v=aaaaaaaa`, titulo: 'Producto de prueba',
    titulo_corto: null, categoria: null }, tienda: { nombre: 'Tienda de prueba' }, variante: 'Azul / M',
} as MuestraVista);
const ficha = (pid: string) => ({ product_id: pid, ficha: null, extendido: {
  galeria: [`/img/g/${pid}-0?v=bbbbbbbb`], muestra: { skus: [{ variante: 'Color: Rojo / Talla: L' }] },
} });

test('la muestra ofrece ficha completa y fotos ampliadas, con variantes de solo consulta', () => {
  const original = muestra('solicitud-a', '100');
  consulta.valor.datos = ficha('100');
  render(createElement(FichaProductoMuestra, { muestra: original, compacta: true }));
  expect(screen.getByRole('link', { name: 'Ver ficha completa' }).getAttribute('href')).toBe('/productos/100');
  expect(screen.getByRole('img', { name: 'Foto ampliada' }).getAttribute('src')).toBe('/img/g/100-0?v=bbbbbbbb');
  expect(screen.getByText(/Tu variante solicitada sigue siendo Azul \/ M/)).toBeTruthy();
  expect(original.variante).toBe('Azul / M');
});

test('el espacio de galería de cabecera conserva la foto real de la muestra al faltar datos ampliados', () => {
  consulta.valor.datos = ficha('100');
  const actual = muestra('solicitud-b', '200');
  render(createElement(FichaProductoMuestra, { muestra: actual, compacta: true, modo: 'fotos' }));
  const galeria = screen.getByTestId('galeria');
  expect(galeria.getAttribute('data-producto')).toBe('200');
  expect(galeria.getAttribute('data-principal')).toBe('/img/p/200?v=aaaaaaaa');
  expect(screen.queryByRole('img')).toBeNull();
});

test('no pinta galería ni variantes del producto anterior durante el cambio de muestra', () => {
  consulta.valor.datos = ficha('100');
  const vista = render(createElement(FichaProductoMuestra, { muestra: muestra('solicitud-a', '100'), compacta: true }));
  vista.rerender(createElement(FichaProductoMuestra, { muestra: muestra('solicitud-b', '200'), compacta: true }));
  expect(screen.queryByTestId('galeria')).toBeNull();
  expect(screen.queryByText('Color: Rojo / Talla: L')).toBeNull();
  expect(screen.getByRole('link', { name: 'Ver ficha completa' }).getAttribute('href')).toBe('/productos/200');
  expect(consulta.pedir).toHaveBeenLastCalledWith('producto', { id: '200' }, { activa: true });
  consulta.valor.datos = ficha('200');
  vista.rerender(createElement(FichaProductoMuestra, { muestra: muestra('solicitud-b', '200'), compacta: true }));
  expect(screen.getByRole('img', { name: 'Foto ampliada' }).getAttribute('src')).toBe('/img/g/200-0?v=bbbbbbbb');
});
