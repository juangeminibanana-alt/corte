import { expect, test } from 'vitest';
import { resolverPortadaVideo } from '../src/dominio/imagenes';

const content_id = '7123456789012345678';
const producto = '/img/p/8234567890123456789?v=aaaaaaaa';
const real = `/img/v/${content_id}?v=bbbbbbbb`;

test('una portada real prevalece frente a la foto del producto en una respuesta anterior', () => {
  expect(resolverPortadaVideo({ content_id, portada: real, miniatura: producto, miniatura_origen: 'producto' }))
    .toEqual({ url: real, delProducto: false });
});

test('sin portada real conserva un espacio vacío en lugar de presentar un producto como video', () => {
  expect(resolverPortadaVideo({ content_id, miniatura: producto, miniatura_origen: 'producto' }))
    .toEqual({ url: null, delProducto: false });
  expect(resolverPortadaVideo({})).toEqual({ url: null, delProducto: false });
});

test('la miniatura canónica nueva y la copia nativa anterior aceptan la misma identidad de video', () => {
  expect(resolverPortadaVideo({ content_id, miniatura: real }).url).toBe(real);
  const legacy = `/lan/v1${real}`;
  expect(resolverPortadaVideo({ content_id, portada: legacy }).url).toBe(legacy);
});

test('rechaza la portada de otro video aunque el campo y el tipo de imagen sean correctos', () => {
  expect(resolverPortadaVideo({ content_id, portada: '/img/v/7999999999999999999?v=bbbbbbbb', miniatura: producto }).url)
    .toBeNull();
  expect(resolverPortadaVideo({ content_id, portada: '/img/v/7999999999999999999?v=bbbbbbbb', miniatura: real }).url)
    .toBe(real);
});

test('no convierte URLs de productos, externas o malformadas en portadas', () => {
  for (const portada of [producto, 'https://example.test' + real, '/img/v/../p/123?v=0', real + '#otro', real + '\n']) {
    expect(resolverPortadaVideo({ content_id, portada }).url).toBeNull();
  }
});
