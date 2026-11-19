import { createElement } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

const { obtener, pedir, invalidar } = vi.hoisted(() => ({
  obtener: vi.fn(), pedir: vi.fn(), invalidar: vi.fn(),
}));
vi.mock('../src/datos/transporte', () => ({ obtenerTransporte: async () => ({ obtener, pedir }) }));
vi.mock('@/datos', async () => ({
  ErrorHub: (await import('../src/datos/errores')).ErrorHub, invalidar,
}));

import { ActualizarMetricas } from '../src/pantallas/videos/ActualizarMetricas';

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

test('actualiza el video en la cuenta activa y recarga su ficha', async () => {
  const scope = 'a'.repeat(64);
  obtener.mockResolvedValue({ cache_scope: scope });
  pedir.mockResolvedValue({ actualizado: true });
  const refrescar = vi.fn(async () => {});
  render(createElement(ActualizarMetricas, { id: '7723400055', refrescar }));
  fireEvent.click(screen.getByRole('button', { name: 'Actualizar métricas' }));
  expect(await screen.findByText('TikTok confirmó la actualización.')).toBeTruthy();
  expect(pedir).toHaveBeenCalledWith('POST', '/api/catalogo/videos/7723400055/actualizar', {}, scope);
  expect(refrescar).toHaveBeenCalledOnce();
});

test('sin la cuenta activa conserva los datos y no consulta por ID', async () => {
  obtener.mockResolvedValue({});
  const refrescar = vi.fn(async () => {});
  render(createElement(ActualizarMetricas, { id: '7723400055', refrescar }));
  fireEvent.click(screen.getByRole('button', { name: 'Actualizar métricas' }));
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Vuelve a conectar Corte para actualizar este video.');
  expect(pedir).not.toHaveBeenCalled();
  expect(refrescar).not.toHaveBeenCalled();
});
