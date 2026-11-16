import { createElement } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { GaleriaProducto, type GaleriaProductoProps } from '../src/pantallas/productos/FichaCompleta';

vi.mock('@/app', () => ({ navegar: vi.fn() }));
vi.mock('@/bloques', () => ({ BotonGuardarImagen: () => null }));
vi.mock('@/plataforma', () => ({ abrirExterno: vi.fn() }));
vi.mock('@/componentes', () => ({
  Foto: (p: { url: string | null; alt: string }) => createElement('img', { src: p.url ?? undefined, alt: p.alt }),
  Icono: () => null,
}));
afterEach(cleanup);

const principal = '/img/p/100?v=aaaaaaaa';
const galeria = '/img/g/100-0?v=bbbbbbbb';
const props: GaleriaProductoProps = {
  productoId: '100', principal, fotos: [galeria], nombre: 'Producto uno', compacta: true,
  tienda: null, categoria: null, resumen: null,
};

test('una única foto de galería se muestra aunque no exista la foto principal', () => {
  render(createElement(GaleriaProducto, { ...props, principal: null }));
  expect(screen.getByRole('img', { name: /Producto uno/ }).getAttribute('src')).toBe(galeria);
});

test('la galería es la colección canónica y no suma la principal servida por otra ruta', () => {
  const segunda = '/img/g/100-1?v=cccccccc';
  render(createElement(GaleriaProducto, { ...props, fotos: [galeria, segunda, segunda] }));
  expect(screen.getAllByRole('button')).toHaveLength(2);
  expect(screen.getByRole('img', { name: /Producto uno/ }).getAttribute('src')).toBe(galeria);
  expect(screen.queryByRole('img', { name: /foto 3/i })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Ver la foto 2 de 2' }));
  expect(screen.getByRole('img', { name: /Producto uno/ }).getAttribute('src')).toBe(segunda);
  fireEvent.click(screen.getByRole('button', { name: 'Ver la foto 1 de 2' }));
  expect(screen.getByRole('img', { name: /Producto uno/ }).getAttribute('src')).toBe(galeria);
});

test('la principal sigue disponible cuando la galería está vacía', () => {
  render(createElement(GaleriaProducto, { ...props, fotos: [] }));
  expect(screen.getByRole('img', { name: /Producto uno/ }).getAttribute('src')).toBe(principal);
  expect(screen.queryByRole('button')).toBeNull();
});

test('nueve fotos de galería no se cuentan como diez al existir una principal', () => {
  render(createElement(GaleriaProducto, { ...props, fotos: Array.from({ length: 9 }, (_, i) => `/img/g/100-${i}?v=bbbbbbbb`) }));
  expect(screen.getAllByRole('button')).toHaveLength(9);
  expect(screen.getByText('1 / 9')).toBeTruthy();
  expect(screen.queryByText('1 / 10')).toBeNull();
});

test('al cambiar de producto descarta la selección anterior incluso si el componente no se desmonta', () => {
  const vista = render(createElement(GaleriaProducto, { ...props, fotos: [galeria, '/img/g/100-1?v=cccccccc'] }));
  fireEvent.click(screen.getByRole('button', { name: 'Ver la foto 2 de 2' }));
  vista.rerender(createElement(GaleriaProducto, { ...props, productoId: '200', nombre: 'Producto dos',
    principal: '/img/p/200?v=cccccccc', fotos: ['/img/g/200-0?v=dddddddd'] }));
  expect(screen.getByRole('img', { name: /Producto dos/ }).getAttribute('src')).toBe('/img/g/200-0?v=dddddddd');
  expect(screen.queryByRole('img', { name: /Producto uno/ })).toBeNull();
});
