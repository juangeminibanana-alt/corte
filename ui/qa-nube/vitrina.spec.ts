import { createElement } from 'react';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

const obtener = vi.hoisted(() => vi.fn());
const pedir = vi.hoisted(() => vi.fn());
vi.mock('../src/datos/transporte', () => ({ obtenerTransporte: async () => ({ obtener, pedir }) }));
vi.mock('@/app', () => ({ Pantalla: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('@/datos', () => ({ ErrorHub: class extends Error {}, invalidar: vi.fn() }));

import { Vitrina } from '../src/pantallas/productos/Vitrina';

const scope = 'a'.repeat(64);
const producto = { product_id: '123', titulo: 'Termo claro', moneda: 'MXN', precio_min: '200', precio_max: '200', tienda: null };
const props = { puedeLeer: true, puedeEditar: true, puedeGenerar: true, alVolver: vi.fn() };

afterEach(() => {
  cleanup();
  obtener.mockReset();
  pedir.mockReset();
});

function prepararLectura(): void {
  obtener.mockImplementation(async (ruta: string) => {
    return ruta === '/api/cloud/session' ? { cache_scope: scope }
      : { productos: [producto], cursor_siguiente: null, total: 1 };
  });
}

test('pide confirmación, pasa el scope de lectura y presenta los fallos parciales', async () => {
  prepararLectura();
  pedir.mockResolvedValueOnce({ resultados: [
    { product_id: '345', ok: true, codigo: null, mensaje: null },
    { product_id: '678', ok: false, codigo: 'no_elegible', mensaje: 'TikTok no permite agregar este producto.' },
  ] });
  render(createElement(Vitrina, props));
  await screen.findByRole('heading', { name: 'Termo claro' });
  fireEvent.change(screen.getByLabelText('IDs de producto'), { target: { value: '345, 678' } });
  fireEvent.click(screen.getByRole('button', { name: 'Agregar a vitrina' }));
  const modal = await screen.findByRole('dialog');
  expect(pedir).not.toHaveBeenCalled();
  fireEvent.click(within(modal).getByRole('button', { name: 'Confirmar cambio' }));
  expect(await screen.findByText(/no permite agregar este producto/)).toBeTruthy();
  expect(pedir).toHaveBeenCalledWith('POST', '/api/catalogo/vitrina/agregar', { product_ids: ['345', '678'] }, scope);
  expect((screen.getByLabelText('IDs de producto') as HTMLInputElement).value).toBe('678');
});

test('genera un enlace con el publisher y la campaña solicitados expresamente', async () => {
  prepararLectura();
  pedir.mockResolvedValueOnce({ resultados: [
    { product_id: '123', enlace: 'https://vt.tiktok.com/ejemplo/', codigo: null, mensaje: null },
  ] });
  render(createElement(Vitrina, props));
  fireEvent.click(await screen.findByRole('button', { name: 'Generar enlace' }));
  const modal = await screen.findByRole('dialog');
  fireEvent.change(within(modal).getByLabelText('ID de publisher (opcional)'), { target: { value: 'creador-123' } });
  fireEvent.change(within(modal).getByLabelText('ID de campaña (opcional)'), { target: { value: '456' } });
  fireEvent.click(within(modal).getByRole('button', { name: 'Generar enlace' }));
  expect(await within(modal).findByRole('link', { name: 'https://vt.tiktok.com/ejemplo/' })).toBeTruthy();
  expect(pedir).toHaveBeenCalledWith('POST', '/api/catalogo/enlaces-afiliado',
    { product_ids: ['123'], publisher_id: 'creador-123', campaign_id: '456' }, scope);
});

test('sin permiso de lectura no consulta ni ofrece modificar la vitrina', () => {
  render(createElement(Vitrina, { ...props, puedeLeer: false, puedeEditar: false }));
  expect(screen.getByText('Vitrina no disponible')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Agregar a vitrina' })).toBeNull();
  expect(obtener).not.toHaveBeenCalled();
});
