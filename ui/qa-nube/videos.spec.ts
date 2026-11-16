import { createElement, type ReactNode } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { FilaVideo } from '../../spec/contrato';
import { filtrarVideos, nombreVideo } from '../src/pantallas/videos/logica';
import { esErrorDeModulo, LimiteError } from '../src/app/LimiteError';

vi.mock('@/componentes', () => ({
  Boton: (p: { children: ReactNode; alPulsar: () => void }) => createElement('button', { onClick: p.alPulsar }, p.children),
  Icono: () => null,
}));
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const cid = '7123456789012345678';
const pid = '8234567890123456789';
const producto = `/img/p/${pid}?v=aaaaaaaa`;
const portada = `/img/v/${cid}?v=bbbbbbbb`;
const nombres = new Map([[pid, 'Camisa de lino natural']]);

test('el nombre del video usa su descripción real sin hashtags y no el título de su producto', () => {
  expect(nombreVideo({ content_id: cid, miniatura: producto, titulo: null,
    descripcion: '  Así se ve después de usarlo  #TikTokShop #Reseña  ' }, nombres))
    .toBe('Así se ve después de usarlo');
});

test('sin texto real, un producto asociado no se convierte en el nombre del video', () => {
  const nombre = nombreVideo({ content_id: cid, miniatura: producto, titulo: null, descripcion: null }, nombres);
  expect(nombre).toMatch(/^Video /);
  expect(nombre).not.toContain('Camisa');
});

test.each([null, portada])('la búsqueda por producto usa producto_principal_id sin foto de producto: %s', (miniatura) => {
  const buscado = { content_id: cid, titulo: null, descripcion: 'Mi reseña del día', miniatura,
    producto_principal_id: pid, tienda_principal: 'Tienda de prueba', pedidos_validos: 1, tasa_reembolso: 0 } as FilaVideo;
  const otro = { ...buscado, content_id: '7999999999999999999', producto_principal_id: '8999999999999999999' };
  const resultado = filtrarVideos([buscado, otro],
    { soloConVentas: false, vendiendoAhora: false, reembolsoAlto: false, q: 'camisa lino' }, null, nombres);
  expect(resultado).toEqual([buscado]);
});

test.each([
  'Failed to fetch dynamically imported module: https://corte.example/assets/videos-anterior.js',
  'Importing a module script failed.', 'Loading chunk 42 failed.', 'Loading CSS chunk 42 failed.',
])('reconoce una importación de módulo fallida: %s', (mensaje) => {
  expect(esErrorDeModulo(new TypeError(mensaje))).toBe(true);
});

test('un error normal conserva el reintento de sección', () => {
  expect(esErrorDeModulo(new TypeError('Cannot read properties of undefined'))).toBe(false);
  expect(esErrorDeModulo('Failed to fetch dynamically imported module')).toBe(false);
});

test('un módulo perdido ofrece recarga y ejecuta reload en lugar de reintentar el import cacheado', () => {
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
  const reload = vi.spyOn(window.location, 'reload').mockImplementation(() => undefined);
  const PantallaPerdida = (): never => { throw new TypeError('Failed to fetch dynamically imported module: https://corte.example/assets/videos-anterior.js'); };
  render(createElement(LimiteError, { seccion: 'Videos', children: createElement(PantallaPerdida) }));
  expect(screen.queryByRole('button', { name: 'Reintentar' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Recargar Corte' }));
  expect(reload).toHaveBeenCalledOnce();
});
