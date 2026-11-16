import type { ReactElement } from 'react';
import { navegar } from '@/app';
import { Boton, Menu, type OpcionMenu } from '@/componentes';
import { formato } from '@/dominio';
import { accionPrincipalMuestras, useEstadoAccionesMuestras } from '../../bloques/muestras/PestanasMuestras';
import { cx } from './util';
import css from './ListadoMuestras.module.css';

/** Conserva Pendientes/Agenda/Todas: representan vistas reales, no tres estados equivalentes. */
export function CabeceraListado(p: { activa: 'pendientes' | 'todas'; contexto: string }): ReactElement {
  const e = useEstadoAccionesMuestras();
  const principal = accionPrincipalMuestras(e);
  const acciones = {
    plan: { etiqueta: e.conPlan ? 'Rehacer mi plan' : 'Armar mi plan', ruta: '/muestras/plan', icono: 'CalendarDays' as const },
    avisar: { etiqueta: 'Avisar a mis tiendas', ruta: '/muestras/avisos', icono: 'MessageCircle' as const },
    sesion: { etiqueta: 'Empezar sesión de videos', ruta: '/muestras/sesion', icono: 'Clapperboard' as const },
  };
  const otras: OpcionMenu[] = (['plan', 'avisar', 'sesion'] as const).filter((a) => a !== principal)
    .map((a) => ({ id: a, etiqueta: acciones[a].etiqueta, icono: acciones[a].icono, alPulsar: () => navegar(acciones[a].ruta) }));
  return (
    <div className={css.cabecera}>
      <header className={css.encabezado} data-sin-accion={principal ? undefined : ''}>
        <div><h1>Muestras</h1><p>{p.contexto}</p></div>
        <div className={css.accionCabecera}>
          {principal ? <Boton variante="primario" icono={acciones[principal].icono} className={cx(css.principal)} alPulsar={() => navegar(acciones[principal].ruta)}>{acciones[principal].etiqueta}</Boton> : null}
          <Menu etiqueta="Más acciones de muestras" opciones={otras} />
        </div>
      </header>
      <nav className={css.pestanas} aria-label="Vistas de muestras">
        {[
          { id: 'pendientes', etiqueta: 'Pendientes', ruta: '/muestras', n: e.pendientes },
          { id: 'agenda', etiqueta: 'Agenda', ruta: '/muestras/agenda', n: null },
          { id: 'todas', etiqueta: 'Todas', ruta: '/muestras/todas', n: e.total },
        ].map((t) => <a key={t.id} href={`#${t.ruta}`} aria-current={p.activa === t.id ? 'page' : undefined}
          onClick={(ev) => { ev.preventDefault(); navegar(t.ruta); }}>
          {t.etiqueta}{t.n !== null ? <span>{formato.numero(t.n)}</span> : null}
        </a>)}
      </nav>
    </div>
  );
}
