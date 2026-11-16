import { createElement } from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { MuestraVista, ProductoResumen } from '../../spec/contrato';
import { ResumenMuestra } from '../src/pantallas/muestras/ResumenMuestra';

vi.mock('@/componentes', () => ({ Icono: () => null }));
vi.mock('@/app', () => ({ usePlataforma: () => 'android' }));
afterEach(cleanup);

const producto = {
  precio_fuente: 'variante', precio_venta_min_centavos: 37200, precio_venta_max_centavos: 37200,
  precio_min_centavos: 40000, precio_max_centavos: 40000, comision_bp: 800,
} as ProductoResumen;
const muestra = { producto, variante: 'Café Marrón / L', recibida: true } as MuestraVista;

test('la banda muestra la variante recibida y sus cifras reales sin tomar la selección de galería', () => {
  render(createElement(ResumenMuestra, { muestra }));
  expect(screen.getByRole('heading', { name: 'Tu muestra recibida' })).toBeTruthy();
  expect(screen.getByText('Café Marrón / L')).toBeTruthy();
  expect(screen.getByText(/372/)).toBeTruthy();
  expect(screen.getByText(/8.*de comisión/)).toBeTruthy();
});

test('sin datos no inventa recepción, color, precio ni comisión', () => {
  render(createElement(ResumenMuestra, { muestra: { ...muestra, recibida: false, variante: null,
    producto: { ...producto, precio_fuente: null, precio_venta_min_centavos: null, precio_venta_max_centavos: null,
      precio_min_centavos: null, precio_max_centavos: null, comision_bp: null } } }));
  expect(screen.getByRole('heading', { name: 'Tu muestra' })).toBeTruthy();
  expect(screen.queryByText('Tu muestra recibida')).toBeNull();
  expect(screen.getByText('Variante no informada')).toBeTruthy();
  expect(screen.getByText('Comisión no informada')).toBeTruthy();
  expect(screen.getByText('—')).toBeTruthy();
});

test('conserva el indicador de precio calculado y el aviso de precio de lista', () => {
  const vista = render(createElement(ResumenMuestra, { muestra: { ...muestra, producto: { ...producto, precio_fuente: 'comision' } } }));
  expect(screen.getByText(/≈/)).toBeTruthy();
  vista.rerender(createElement(ResumenMuestra, { muestra: { ...muestra, producto: { ...producto, precio_fuente: 'lista' } } }));
  expect(screen.getByText('precio de lista')).toBeTruthy();
});
