import type { ReactElement } from 'react';
import type * as C from '@/contrato';
import { Icono } from '@/componentes';
import { formato } from '@/dominio';
import { precioVisible } from '../../bloques/muestras/FichaPrecio';
import { T } from './textos';
import css from './Detalle.module.css';

/** Datos de la solicitud real; explorar otra foto/SKU nunca modifica este resumen. */
export function ResumenMuestra(p: { muestra: C.MuestraVista }): ReactElement {
  const m = p.muestra;
  const precio = precioVisible(m.producto);
  const tasa = m.producto.comision_bp === null ? null : formato.tasaBp(m.producto.comision_bp);
  return (
    <section className={css.resumenMuestra} aria-label={T.tuMuestra}>
      <h2>{m.recibida ? T.tuMuestraRecibida : T.tuMuestra}</h2>
      <div className={css.resumenMuestraDatos}>
        <div className={css.resumenVariante}><Icono nombre="Shirt" tamano={24} /><span>{m.variante || T.varianteNoInformada}</span></div>
        <div className={css.resumenPrecio}><strong>{precio?.texto ?? '—'}</strong>{precio?.fuente === 'lista' ? <small>{precio.rotulo}</small> : null}</div>
        <span className={css.resumenComision}>{tasa ? T.tasaMuestra(tasa) : T.comisionNoInformada}</span>
      </div>
    </section>
  );
}
