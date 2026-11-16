/** Búsqueda y estados a la vista; el resto se muestra cuando hace falta. */
import { useCallback, useEffect, useId, useMemo, useState, type ReactElement, type ReactNode } from 'react';
import type * as C from '@/contrato';
import { Boton, CampoTexto, Chip, ChipFiltro, Icono, Menu, Modal, type OpcionMenu } from '@/componentes';
import { registrarAtras } from '@/plataforma';
import { AGRUPACIONES, ORDENES, FILTROS_VACIOS, GRUPOS_FILTRO, contarFiltros, contarPorGrupo, type FiltrosCola } from './logica';
import type { PreferenciasCola } from './recuerdo';
import { T } from './textos';
import { cx } from './util';
import css from './Muestras.module.css';

/** Conservado para consumidores de la interfaz anterior; la barra ya no depende del ancho. */
export const ANCHO_CHIPS_AGRUPAR = 1080;

type Interruptor = 'yaLoVendo' | 'etiquetable' | 'conPromesa' | 'fijadas';
const INTERRUPTORES: ReadonlyArray<[Interruptor, string]> = [
  ['yaLoVendo', T.filtroYaLoVendo],
  ['etiquetable', T.filtroEtiquetable],
  ['conPromesa', T.filtroConPromesa],
  ['fijadas', T.filtroFijadas],
];

function Estados(p: { filtros: FiltrosCola; conteos: Partial<Record<C.GrupoMuestra, number>>; alCambiar: (f: FiltrosCola) => void }): ReactElement {
  const f = p.filtros;
  const presentes = GRUPOS_FILTRO.filter((g) => (p.conteos[g] ?? 0) > 0);
  const grupos = GRUPOS_FILTRO.filter((g) => f.grupos.includes(g) || (presentes.length > 1 && presentes.includes(g)));
  return <>{grupos.map((g) => (
    <ChipFiltro key={g} activo={f.grupos.includes(g)} conteo={p.conteos[g] ?? 0}
      alCambiar={(si) => p.alCambiar({ ...f, grupos: si ? [...f.grupos, g] : f.grupos.filter((x) => x !== g) })}>
      {T.filtroGrupo[g] ?? g}
    </ChipFiltro>
  ))}</>;
}

export function BarraHerramientas(p: {
  prefs: PreferenciasCola;
  alCambiar: (c: Partial<PreferenciasCola>) => void;
  items: readonly C.MuestraVista[];
  movil: boolean;
  ordenProvisional: boolean;
  selectorVista?: ReactNode;
  avance?: ReactNode;
  mostrarAvance?: boolean;
}): ReactElement {
  const [porQue, setPorQue] = useState(false);
  const [avanzados, setAvanzados] = useState(false);
  const panelId = useId();
  useEffect(() => { if (p.mostrarAvance) setAvanzados(true); }, [p.mostrarAvance]);
  useEffect(() => {
    if (!p.movil || !avanzados) return undefined;
    return registrarAtras(() => { setAvanzados(false); return true; });
  }, [p.movil, avanzados]);
  const f = p.prefs.filtros;
  const conteos = useMemo(() => contarPorGrupo(p.items), [p.items]);
  const nFiltros = contarFiltros(f);
  const { alCambiar } = p;
  const cambiarFiltros = useCallback((filtros: FiltrosCola): void => alCambiar({ filtros }), [alCambiar]);
  const activos = INTERRUPTORES.filter(([clave]) => f[clave]);
  const opcionesOrden: OpcionMenu[] = ORDENES.map((o) => ({ id: o, etiqueta: T.ordenar[o], ...(o === p.prefs.orden ? { icono: 'Check' as const } : {}), alPulsar: () => p.alCambiar({ orden: o }) }));
  const opcionesAgrupar: OpcionMenu[] = AGRUPACIONES.map((a) => ({ id: a, etiqueta: T.agrupar[a], ...(a === p.prefs.agrupar ? { icono: 'Check' as const } : {}), alPulsar: () => p.alCambiar({ agrupar: a }) }));
  const tiendas = useMemo(() => [...new Map(p.items.map((m) => [m.tienda.tienda_key, m.tienda.nombre])).entries()]
    .sort((a, b) => a[1].localeCompare(b[1], 'es')), [p.items]);
  const estados: OpcionMenu[] = [
    { id: 'todos', etiqueta: 'Todos los estados', alPulsar: () => cambiarFiltros({ ...f, grupos: [] }) },
    ...GRUPOS_FILTRO.filter((g) => (conteos[g] ?? 0) > 0 || f.grupos.includes(g)).map((g) => ({
      id: g, etiqueta: `${T.filtroGrupo[g] ?? g} (${conteos[g] ?? 0})`,
      ...(f.grupos.includes(g) ? { icono: 'Check' as const } : {}),
      alPulsar: () => cambiarFiltros({ ...f, grupos: f.grupos.includes(g) ? f.grupos.filter((x) => x !== g) : [...f.grupos, g] }),
    })),
  ];

  return (
    <div className={cx(css.herramientas, css.herramientasSencillas)} data-movil={p.movil ? '' : undefined}>
      <div className={cx(css.filaPrincipalSimple)}>
        <label className={css.selectorTienda}>
          <span className={css.soloLectores}>Filtrar por tienda</span>
          <select value={f.tienda ?? ''} onChange={(e) => cambiarFiltros({ ...f, tienda: e.currentTarget.value })}>
            <option value="">{p.movil ? 'Tiendas' : 'Todas las tiendas'}</option>
            {tiendas.map(([key, nombre]) => <option key={key} value={key}>{nombre}</option>)}
          </select>
          <Icono nombre="ChevronDown" tamano={16} />
        </label>
        <div className={css.selectorEstados}>
          <Menu etiqueta={f.grupos.length === 0 ? 'Todos los estados' : f.grupos.length === 1 ? T.filtroGrupo[f.grupos[0]!] ?? f.grupos[0]! : `${f.grupos.length} estados`} opciones={estados} disparador="boton" />
        </div>
        <div className={css.selectorOrden}>
          <Menu etiqueta={T.ordenar[p.prefs.orden]} opciones={opcionesOrden} disparador="boton" />
        </div>
        <CampoTexto etiqueta={T.buscarEtiqueta} etiquetaOculta tipo="search" valor={f.q}
          placeholder="Buscar muestra o tienda" alCambiar={(q) => cambiarFiltros({ ...f, q })} className={cx(css.busquedaSimple)} />
        <button type="button" className={cx(css.botonOpciones)} aria-label={p.movil ? 'Filtros, vista y avance' : 'Más filtros y vista'} aria-expanded={avanzados} aria-controls={panelId} onClick={() => setAvanzados(!avanzados)}>
          <Icono nombre="ArrowDownUp" tamano={18} />
          <span>Más filtros y vista</span>
        </button>
      </div>

      <div className={cx(css.filtrosVisibles)} role="group" aria-label={T.filtrosEtiqueta}>
        {f.grupos.length > 0 ? <Estados filtros={f} conteos={conteos} alCambiar={cambiarFiltros} /> : null}
        {!avanzados ? activos.map(([clave, texto]) => (
          <ChipFiltro key={clave} activo alCambiar={() => cambiarFiltros({ ...f, [clave]: false })}>{texto}</ChipFiltro>
        )) : null}
        {nFiltros > 0 ? <span className={cx(css.filtrosActivos)}>
          {T.filtrosActivos(nFiltros)}
          <Boton variante="fantasma" tamano="sm" alPulsar={() => cambiarFiltros(FILTROS_VACIOS)}>{T.limpiar}</Boton>
        </span> : null}
        {p.ordenProvisional ? <Chip tono="info" icono="Hourglass">{T.ordenProvisional}</Chip> : null}
      </div>

      <div id={panelId} className={cx(css.panelOpciones)} hidden={!avanzados}>
        {p.avance ? <div className={css.avanceOpciones}>{p.avance}</div> : null}
        <div className={cx(css.grupoOpciones)}>
          <span className={cx(css.rotuloOpciones)}>Filtrar muestras</span>
          <div className={cx(css.chipsFiltro)} role="group" aria-label="Más filtros de muestras">
            <Estados filtros={f} conteos={conteos} alCambiar={cambiarFiltros} />
            {INTERRUPTORES.map(([clave, texto]) => (
              <ChipFiltro key={clave} activo={f[clave]} alCambiar={(si) => cambiarFiltros({ ...f, [clave]: si })}>{texto}</ChipFiltro>
            ))}
          </div>
        </div>
        <div className={cx(css.grupoOpciones)}>
          <span className={cx(css.rotuloOpciones)}>Organizar la lista</span>
          <div className={cx(css.chipsFiltro)}>
            <Menu etiqueta={T.agruparActual(T.agrupar[p.prefs.agrupar])} opciones={opcionesAgrupar} disparador="boton" icono="LayoutList" />
            <Menu etiqueta={T.ordenActual(T.ordenar[p.prefs.orden])} opciones={opcionesOrden} disparador="boton" icono="ArrowDownUp" />
          </div>
        </div>
        {p.selectorVista ? <div className={cx(css.grupoOpciones)}>
          <span className={cx(css.rotuloOpciones)}>Vista</span>
          <div className={cx(css.selectorSimple)}>{p.selectorVista}</div>
        </div> : null}
        <Boton variante="fantasma" tamano="sm" icono="CircleHelp" alPulsar={() => setPorQue(true)}>{T.porQueOrden}</Boton>
      </div>

      <Modal abierto={porQue} titulo={T.porQueOrden} alCerrar={() => setPorQue(false)} pie={<Boton variante="primario" alPulsar={() => setPorQue(false)}>{T.entendido}</Boton>}>
        <p className={cx(css.parrafo)}>{T.porQueTexto}</p>
      </Modal>
    </div>
  );
}
