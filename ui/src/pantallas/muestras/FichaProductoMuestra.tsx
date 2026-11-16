/** Ficha ampliada de solo lectura; nunca cambia la variante de la solicitud. */
import type { ReactElement } from 'react';
import type * as C from '@/contrato';
import { EnlaceRuta } from '@/app';
import { useConsulta } from '@/datos';
import { Boton } from '@/componentes';
import { GaleriaProducto, ListaSkus } from '../productos/FichaCompleta';
import { T } from './textos';
import { cx } from './util';
import css from './Detalle.module.css';

export function FichaProductoMuestra(p: { muestra: C.MuestraVista; compacta: boolean; modo?: 'completo' | 'fotos' | 'opciones' }): ReactElement | null {
  const producto = p.muestra.producto;
  const consulta = useConsulta('producto', { id: producto.product_id }, { activa: !!producto.product_id });
  const detalle = consulta.datos?.product_id === producto.product_id ? consulta.datos : undefined;
  const fotos = detalle?.extendido?.galeria ?? [];
  const skus = detalle?.extendido?.muestra?.skus ?? [];
  const nombre = producto.titulo_corto || producto.titulo || T.fichaProducto;
  const galeria = <GaleriaProducto key={`${p.muestra.application_id}:${producto.product_id}`} productoId={producto.product_id}
    principal={detalle?.ficha?.imagen ?? producto.imagen} fotos={fotos} nombre={nombre}
    compacta={p.compacta} tienda={p.muestra.tienda.nombre} categoria={producto.categoria}
    resumen={detalle?.ficha ?? producto} guardar={p.modo !== 'fotos'} />;
  if (p.modo === 'fotos') return <div className={css.fotosDetalle}>{galeria}</div>;
  if (p.modo === 'opciones' && skus.length === 0) return null;
  return (
    <section className={css.bloque} aria-label={T.fichaProducto} data-ficha-producto-muestra={p.muestra.application_id}>
      <div className={css.bloqueCabeza}>
        <h2 className={css.bloqueTitulo}>{T.fichaProducto}</h2>
        <EnlaceRuta a={`/productos/${encodeURIComponent(producto.product_id)}`} className={cx(css.enlaceAccion)}>
          {T.verFichaProducto}
        </EnlaceRuta>
      </div>
      {p.modo === 'opciones' ? null : fotos.length > 0 ? galeria
        : consulta.cargando ? <p className={css.texto} role="status">{T.cargandoFichaProducto}</p>
        : consulta.error ? <p className={css.texto}>{T.errorFichaProducto}</p>
          : <p className={css.texto}>{consulta.fuente === 'copia' && !detalle?.extendido ? T.fichaProductoEnCopia : T.sinGaleriaProducto}</p>}
      {skus.length > 0 ? (
        <>
          <p className={css.texto}>{T.variantesSoloConsulta(p.muestra.variante)}</p>
          <ListaSkus key={producto.product_id} skus={skus} />
        </>
      ) : null}
      {consulta.error ? <Boton variante="secundario" tamano="sm" alPulsar={() => void consulta.refrescar()}>{T.reintentarFichaProducto}</Boton> : null}
    </section>
  );
}
