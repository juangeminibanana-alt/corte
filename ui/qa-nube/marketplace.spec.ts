import { createElement } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

const obtener = vi.hoisted(() => vi.fn());
vi.mock('../src/datos/transporte', () => ({ obtenerTransporte: async () => ({ obtener }) }));
vi.mock('@/app', () => ({ Pantalla: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('@/datos', () => ({ ErrorHub: class extends Error {} }));

import { Marketplace } from '../src/pantallas/productos/Marketplace';

afterEach(() => {
  cleanup();
  obtener.mockReset();
});

function producto(id: string, titulo: string, categorias: { id: string; nombre: string }[] = []) {
  return { product_id: id, titulo, tienda: null, precio_min: '150', precio_max: '170', moneda: 'MXN',
    comision_porcentaje: 12.5, unidades_vendidas: null, categorias, enlace: null };
}

test('la consulta conserva los filtros al paginar y permite seleccionar una categoría del resultado', async () => {
  obtener.mockResolvedValueOnce({ productos: [producto('123', 'Termo claro', [{ id: '101', nombre: 'Hogar' }])], cursor_siguiente: 'b2=' });
  obtener.mockResolvedValueOnce({ productos: [producto('456', 'Termo oscuro')], cursor_siguiente: null });
  obtener.mockResolvedValueOnce({ productos: [], cursor_siguiente: null });
  render(createElement(Marketplace, { puedeBuscar: true, alVolver: vi.fn() }));
  fireEvent.change(screen.getByLabelText('Producto'), { target: { value: 'termo' } });
  fireEvent.change(screen.getByLabelText('Comisión mínima (%)'), { target: { value: '12,50' } });
  fireEvent.change(screen.getByLabelText('Orden'), { target: { value: 'units_sold:DESC' } });
  fireEvent.click(screen.getByRole('button', { name: 'Buscar' }));
  expect(await screen.findByRole('heading', { name: 'Termo claro' })).toBeTruthy();
  expect(obtener).toHaveBeenCalledWith('/api/catalogo/marketplace?limit=20&q=termo&min_commission=12.50&sort=units_sold&direction=DESC');
  fireEvent.click(screen.getByRole('button', { name: 'Cargar más productos' }));
  expect(await screen.findByRole('heading', { name: 'Termo oscuro' })).toBeTruthy();
  expect(obtener.mock.calls[1]?.[0]).toContain('cursor=b2%3D');
  fireEvent.click(screen.getByRole('button', { name: 'Seleccionar categoría Hogar' }));
  fireEvent.click(screen.getByRole('button', { name: 'Buscar' }));
  expect(await screen.findByText('No encontramos productos')).toBeTruthy();
  expect(obtener.mock.calls[2]?.[0]).toContain('category_id=101');
  expect(obtener.mock.calls[2]?.[0]).not.toContain('cursor=');
});

test('sin el permiso de Creator la pantalla informa del bloqueo sin enviar consultas', () => {
  render(createElement(Marketplace, { puedeBuscar: false, alVolver: vi.fn() }));
  expect(screen.getByText('Búsqueda de TikTok Shop no disponible')).toBeTruthy();
  expect(obtener).not.toHaveBeenCalled();
});
