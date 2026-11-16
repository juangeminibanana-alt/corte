import type { ReactElement } from 'react';
import type * as C from '@/contrato';
import { Foto, Icono, Menu } from '@/componentes';
import { ETIQUETA_ACCION, formato } from '@/dominio';
import { anuncioMuestra, useDeslizar } from '../../bloques/muestras/TarjetaMuestra';
import { BotonAccionMuestra, useAccionPrincipal } from '../../bloques/muestras/botones';
import { textoAvance, textoTikTok } from '../../bloques/muestras/chips';
import { useOpcionesMuestra } from '../../bloques/muestras/menuMuestra';
import { nombreDe } from './logica';
import { cx, vars } from './util';
import css from './ListadoMuestras.module.css';

/** La presentación de la lista conserva el menú, las acciones y los gestos originales. */
export function FilaMuestra(p: {
  muestra: C.MuestraVista; seleccionada?: boolean; marcable?: boolean; marcada?: boolean;
  android?: boolean; esNueva?: boolean; conAccion?: boolean; deslizable?: boolean;
  alMarcar?: (si: boolean) => void; alAbrir: () => void;
}): ReactElement {
  const m = p.muestra;
  const nombre = nombreDe(m);
  const opciones = useOpcionesMuestra(m);
  const original = useAccionPrincipal(m);
  const accion = original === 'planear' && m.prioridad === 'no_se_puede_etiquetar' ? null : original;
  const seleccionTactil = p.android && p.marcable;
  const gesto = useDeslizar(m, p.deslizable === true && accion !== null && !seleccionTactil);
  const urgente = m.grupo === 'por_vencer' || m.grupo === 'vencida' || m.avisos.promesa_vencida;
  const bloqueada = m.prioridad === 'no_se_puede_etiquetar';
  const estado = bloqueada ? 'No se puede etiquetar' : m.avisos.promesa_vencida ? 'Promesa vencida'
    : urgente ? textoTikTok(m) : textoAvance(m.avance);
  const fecha = m.avisos.promesa_vencida && m.avisos.promesa ? formato.fechaConDia(m.avisos.promesa)
    : m.grupo === 'por_vencer' && m.fecha_limite_at ? `${formato.fechaConDia(m.fecha_limite_at)}, ${formato.hora(m.fecha_limite_at)}`
      : urgente ? m.avance.etapa === 'por_planear' ? null : textoAvance(m.avance) : m.variante ? null : textoTikTok(m);
  const seleccionar = (): void => { if (seleccionTactil) p.alMarcar?.(!p.marcada); else p.alAbrir(); };
  return (
    <div className={css.carril}>
      {gesto.dx !== 0 ? <div className={css.gesto} aria-hidden="true">
        {gesto.dx > 0 && accion ? ETIQUETA_ACCION[accion] : m.avance.fecha_planeada ? 'Mover a otro día' : 'No puedo hacer este video'}
      </div> : null}
      <article className={cx(css.fila, p.seleccionada && css.seleccionada, p.marcada && css.marcada)}
        data-solicitud={m.application_id} aria-current={p.seleccionada ? 'true' : undefined}
        data-con-accion={p.conAccion !== false && accion && !seleccionTactil ? '' : undefined}
        style={gesto.dx !== 0 ? vars({ '--desplazamiento': `${Math.max(-140, Math.min(140, gesto.dx))}px` }) : undefined}
        {...gesto.manejadores}>
        <div className={css.imagen}>
          <Foto url={m.producto.imagen} alt={nombre} anchoCss={100} proporcion="1:1" radio="md"
            tienda={m.tienda.nombre} categoria={m.producto.categoria} className={cx(css.foto)} />
          {p.marcable ? <label className={css.casilla}>
            <input type="checkbox" checked={p.marcada ?? false} onChange={(e) => p.alMarcar?.(e.currentTarget.checked)}
              aria-label={`Seleccionar ${nombre}`} />
          </label> : m.posicion_cola !== null ? <span className={css.posicion} title="Posición en tu cola">
            {m.avance.fijada ? <Icono nombre="Pin" tamano={14} /> : formato.numero(m.posicion_cola)}
          </span> : null}
        </div>
        <div className={css.identidad}>
          <button type="button" className={css.nombre} data-abrir="" onClick={seleccionar}
            {...(seleccionTactil ? { role: 'checkbox', 'aria-checked': p.marcada ?? false } : {})}
            aria-label={seleccionTactil ? `Seleccionar ${nombre}` : anuncioMuestra(m)}>
            {p.esNueva ? <span className={css.nueva} aria-label="Nueva" /> : null}{nombre}
          </button>
          <span className={css.tienda}><Icono nombre="Store" tamano={16} /><span>{m.tienda.nombre}</span></span>
        </div>
        <div className={css.variante}>
          <span className={css.recibida}>{m.recibida ? 'Recibida' : textoTikTok(m)}</span>
          {m.variante ? <span>{m.variante}</span> : null}
        </div>
        <div className={css.estado} data-urgente={urgente || bloqueada ? '' : undefined} data-planeada={m.avance.etapa !== 'por_planear' ? '' : undefined}>
          <strong><span className={css.punto} aria-hidden="true" />{estado}</strong>
          {fecha ? <span className={css.fecha}>{fecha}</span> : null}
          {m.avisos.copiado_sin_confirmar ? <span className={css.fecha}>Mensaje copiado · sin confirmar</span> : null}
        </div>
        <div className={css.acciones}>
          {p.conAccion !== false && accion && !seleccionTactil ? <BotonAccionMuestra muestra={m} tamano="sm" className={cx(css.accion)} /> : null}
          <Menu etiqueta={`Más acciones de ${nombre}`} opciones={opciones} className={cx(css.menu)} />
        </div>
      </article>
    </div>
  );
}
