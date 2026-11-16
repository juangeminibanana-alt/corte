import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, test, vi } from 'vitest';
import type { FilaVideo } from '../../spec/contrato';
import { TarjetaVideo } from '../src/bloques/catalogo/TarjetaVideo';

vi.mock('@/componentes', () => ({
  Chip: () => null,
  TarjetaProducto: () => null,
  MiniaturaVideo: (p: { url: string | null; rotulo?: string }) => createElement('img', { src: p.url ?? undefined, 'aria-label': p.rotulo }),
}));
vi.mock('../src/bloques/util/comun', () => ({ cx: (...clases: unknown[]) => clases.filter(Boolean).join(' ') }));

const producto = '/img/p/8234567890123456789?v=aaaaaaaa';
const real = '/img/v/7123456789012345678?v=bbbbbbbb';
const video = {
  content_id: '7123456789012345678', titulo: 'Video de prueba', miniatura: producto, miniatura_origen: 'producto',
  portada: real, comision_estimada_centavos: 1000, unidades: 1, pedidos: 1, pedidos_validos: 1,
  tasa_reembolso: 0, tienda_principal: 'Tienda de prueba', primera_venta: '2026-01-01', ultima_venta: '2026-01-02',
} as FilaVideo;

test('la tarjeta usa la portada real incluso si una copia anterior incluye foto de producto', () => {
  const html = renderToStaticMarkup(createElement(TarjetaVideo, { video, anchoCss: 200 }));
  expect(html).toContain(real);
  expect(html).not.toContain(producto);
  expect(html).not.toContain('Foto del producto');
});

test('la tarjeta sin portada real no presenta una imagen de producto como vista previa', () => {
  const html = renderToStaticMarkup(createElement(TarjetaVideo, { video: { ...video, portada: null }, anchoCss: 200 }));
  expect(html).not.toContain(producto);
  expect(html).not.toContain('Foto del producto');
});
