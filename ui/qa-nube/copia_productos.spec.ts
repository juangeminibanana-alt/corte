import { expect, test } from 'vitest';
import type * as C from '../../spec/contrato';
import { aplicarOpsACopia, deCopia } from '../src/dominio/copia';

const hoy = '2026-11-16';
const galeria = '/img/g/100-0?v=aaaaaaaa';
const otraGaleria = '/img/g/200-0?v=bbbbbbbb';

function fila(product_id: string): C.FilaProducto {
  return {
    product_id, titulo: `Producto ${product_id}`, titulo_corto: null, imagen: null,
    tienda_key: null, tienda_nombre: null, pedidos: 2, pedidos_validos: 2, unidades: 2,
    ventas_centavos: 30000, comision_estimada_centavos: 3000, tasa_reembolso: 0,
    comision_bp: 1000, videos: 0, es_muestra: false, clase_muestra: null, con_ficha: true, en_vitrina: true,
  };
}

function extendido(imagen: string): C.ProductoExtendido {
  return {
    galeria: [imagen], vitrina: null,
    muestra: {
      puede_solicitar: true, estado: 'TO_APPLY', estado_texto: 'Puedes pedir muestra',
      application_id: null, limite_alcanzado: false, consultado_at: 1794801600,
      skus: [{
        sku_id: '123', propiedades: [{ nombre: 'Color', valor: 'Azul' }, { nombre: 'Talla', valor: 'M' }],
        variante: 'Azul / M', precio_centavos: 15000, disponible: true,
        motivo_no_disponible: null, motivo_texto: null,
      }],
    },
    solicitudes_recuperadas: [], planes_dirigidos: [], comision_real: null,
    parecidos: null, origen_ventas: null, origen_ventas_aviso: null,
  };
}

/** Datos sintéticos mínimos que usa el armador de producto; no accede a fixtures personales. */
function copiaBase(): C.SnapshotResponse {
  return {
    version_esquema: 1, data_version: 1, local_rev: 1, img_rev: 1, generado_at: 1794801600,
    productos: [fila('100'), fila('200')], muestras: [], videos: [], ordenes_recientes: [],
    local: {
      planes: [], avisos: [], recordatorios: [], plantillas: [], preferencias: {},
      notas: [{ id: 'confirmada', entidad: 'producto', entidad_id: '100', texto: 'Nota guardada', fijada: false,
        rev: 1, creado_at: 1794801500, actualizado_at: 1794801500, dispositivo_id: 'sintetico' }],
    },
    meta_imagenes: {
      [galeria]: { w: 800, h: 800, lqip: null, color: '#ffffff' },
      [otraGaleria]: { w: 800, h: 800, lqip: null, color: '#000000' },
    },
  } as C.SnapshotResponse;
}

test('una copia anterior sin extras conserva su ficha básica y no inventa variantes ni fotos', () => {
  const copia = copiaBase();
  const datos = deCopia('producto', { id: '100' }, copia, hoy);
  expect(datos?.fila).toEqual(copia.productos[0]);
  expect(datos?.notas.map((n) => n.id)).toEqual(['confirmada']);
  expect(datos).not.toHaveProperty('extendido');
});

test('galería y propiedades de Color/Talla sobreviven al armar una ficha sin conexión', () => {
  const copia = copiaBase();
  copia.extras = { muestras: {}, tiendas: {}, productos: { '100': extendido(galeria), '200': extendido(otraGaleria) } };
  const antes = structuredClone(copia);
  const datos = deCopia('producto', { id: '100' }, copia, hoy);
  expect(datos?.extendido).toEqual(copia.extras.productos?.['100']);
  expect(datos?.extendido?.muestra?.skus[0]?.propiedades).toEqual([
    { nombre: 'Color', valor: 'Azul' }, { nombre: 'Talla', valor: 'M' },
  ]);
  expect(Object.keys(datos?.meta_imagenes ?? {})).toEqual([galeria]);
  expect(copia).toEqual(antes);
});

test('el límite de fichas extendidas no elimina los demás productos de la copia', () => {
  const copia = copiaBase();
  copia.extras = { muestras: {}, tiendas: {}, productos: { '100': extendido(galeria) } };
  const otro = deCopia('producto', { id: '200' }, copia, hoy);
  expect(otro?.fila).toEqual(copia.productos[1]);
  expect(otro).not.toHaveProperty('extendido');
  expect(deCopia('producto', { id: '300' }, copia, hoy)).toBeNull();
});

test('las operaciones locales pendientes mantienen ficha extendida y notas confirmadas', () => {
  const copia = copiaBase();
  copia.extras = { muestras: {}, tiendas: {}, productos: { '100': extendido(galeria) } };
  const actualizada = aplicarOpsACopia(copia, [{
    op_id: 'op-nota-sintetica', tipo: 'nota.crear',
    datos: { id: 'pendiente', entidad: 'producto', entidad_id: '100', texto: 'Nota pendiente' },
  }], hoy);
  const datos = deCopia('producto', { id: '100' }, actualizada, hoy);
  expect(datos?.extendido?.galeria).toEqual([galeria]);
  expect(datos?.notas.map((n) => n.id)).toEqual(['confirmada', 'pendiente']);
  expect(copia.local.notas.map((n) => n.id)).toEqual(['confirmada']);
});
