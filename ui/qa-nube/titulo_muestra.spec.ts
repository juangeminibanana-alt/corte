import { createElement } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { MuestraVista } from '../../spec/contrato';
import { TituloEditable } from '../src/pantallas/muestras/Detalle';

vi.mock('@/app', () => ({ EnlaceRuta: () => null }));
vi.mock('@/bloques', () => ({}));
vi.mock('@/datos', () => ({ useAcciones: () => ({}) }));
vi.mock('@/plataforma', () => ({}));
vi.mock('@/componentes', () => ({
  BotonIcono: (p: { etiqueta: string; alPulsar: () => void }) => createElement('button', { 'aria-label': p.etiqueta, onClick: p.alPulsar }),
  useToast: () => ({ mostrar: vi.fn() }),
}));
vi.mock('../src/pantallas/muestras/FichaProductoMuestra', () => ({ FichaProductoMuestra: () => null }));
afterEach(cleanup);

const titulo = 'Chaqueta con cuello para hombre';
const muestra = { application_id: 'solicitud-a', producto: { product_id: '100', titulo, titulo_corto: titulo } } as MuestraVista;
const props = { m: muestra, detalle: undefined, nivel: 'h1' as const, alConflicto: () => false };

test('el título compacto permite leer el original completo incluso si coincide con el nombre visible', () => {
  render(createElement(TituloEditable, { ...props, compacto: true }));
  const abrir = screen.getByRole('button', { name: 'Ver título completo' });
  expect(abrir.getAttribute('aria-expanded')).toBe('false');
  fireEvent.click(abrir);
  expect(screen.getAllByText(titulo)).toHaveLength(2);
  expect(screen.getByRole('button', { name: 'Ocultar título completo' }).getAttribute('aria-expanded')).toBe('true');
  fireEvent.click(screen.getByRole('button', { name: 'Ocultar título completo' }));
  expect(screen.getAllByText(titulo)).toHaveLength(1);
});

test('el título de panel sin recorte mantiene su presentación si coincide con el original', () => {
  render(createElement(TituloEditable, props));
  expect(screen.getByRole('heading', { name: titulo })).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Ver título completo' })).toBeNull();
});
