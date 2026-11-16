/**
 * Detalle de muestra a pantalla completa (01 §4.3 «Celular», 02 §7.12, lienzo MovilMuestra.png): Android, ventanas de
 * menos de 1280 y «Abrir en página completa» (⤢). En el celular: foto protagonista a sangre con flecha atrás y el chip
 * «TikTok:» encima, el título sobre el degradado y la barra de acciones fija abajo [Acción principal] [Avisar] [⋯]. En
 * Windows: encabezado con «‹ Muestras», foto 4:5 con halo a la izquierda y el contenido a la derecha.
 * Sin conexión (Android) se arma con la copia y sus extras («Datos de tu última copia · {fecha}»); lo que la copia no
 * trae → «Necesita tu PC encendida».
 */
import type { ReactElement } from 'react';
import type * as C from '@/contrato';
import { atras, EnlaceRuta, navegar, Pantalla, useClaseAncho, usePlataforma } from '@/app';
import { BotonAccionMuestra, useControlMuestra } from '@/bloques';
import { Boton, BotonIcono, EncabezadoPantalla, EstadoVacio, Esqueleto, EsqueletoVista, Icono, Menu } from '@/componentes';
import { useConsulta } from '@/datos';
import { formato } from '@/dominio';
import { AvisoConflicto, CuerpoDetalle, LineaTienda, Rotulo, TituloEditable, nombreVisible, useAtajosDetalle, useConflicto, useMenuMuestra } from './Detalle';
import { NecesitaPc } from './Estados';
import { FichaProductoMuestra } from './FichaProductoMuestra';
import { ResumenMuestra } from './ResumenMuestra';
import { PARAMS_PENDIENTES } from './useCola';
import { RUTA_PENDIENTES } from './rutas';
import { T } from './textos';
import { cx } from './util';
import css from './Detalle.module.css';

function volver(): void {
  if (typeof window !== 'undefined' && window.history.length > 1) atras();
  else navegar(RUTA_PENDIENTES, { reemplazar: true });
}

function irANotas(): void {
  const el = typeof document === 'undefined' ? null : document.getElementById('notas-muestra');
  el?.scrollIntoView?.({ block: 'start', behavior: 'smooth' });
}

function Contenido(p: { m: C.MuestraVista; detalle: C.MuestraDetalleResponse | undefined; movil: boolean; fuente: string; copiaAt: C.EpochS | null }): ReactElement {
  const { m, detalle } = p;
  const control = useControlMuestra();
  const conflicto = useConflicto();
  const nombre = nombreVisible(m, detalle);
  const menu = useMenuMuestra(m, irANotas);
  const pendientes = useConsulta('muestras', PARAMS_PENDIENTES);
  const cola = pendientes.datos?.items ?? [];
  useAtajosDetalle(m, nombre, irANotas, !p.movil);

  const copia = p.fuente === 'copia' && p.copiaAt !== null ? <p className={cx(css.copia)}>{T.datosCopia(`${formato.fechaCorta(p.copiaAt)}, ${formato.hora(p.copiaAt)}`)}</p> : null;
  const principal = (
    <div className={css.accionesProducto}>
      <BotonAccionMuestra muestra={m} tamano="lg" anchoCompleto className={cx(css.detallePrincipal)} />
      <EnlaceRuta a={`/productos/${encodeURIComponent(m.producto.product_id)}`} className={cx(css.fichaCompleta)}>
        {T.verFichaProducto}<Icono nombre="ChevronRight" tamano={20} />
      </EnlaceRuta>
    </div>
  );
  const secundarias = (
    <div className={css.accionesSecundarias}>
      <Boton variante="secundario" icono="MessageCircle" alPulsar={() => control.abrirMensaje({ solicitud: m.application_id })}>
        {T.avisarTienda}
      </Boton>
      <Menu etiqueta={T.masAcciones} opciones={menu} />
    </div>
  );

  if (p.movil) {
    return (
      <div className={cx(css.completoMovil)} data-detalle-muestra={m.application_id}>
        <button type="button" className={css.volverMuestras} aria-label={T.volverMuestras} onClick={volver}>
          <Icono nombre="ChevronLeft" tamano={20} /><span>{T.titulo}</span>
        </button>
        <div className={cx(css.encabezadoTexto)}>
          <TituloEditable m={m} detalle={detalle} nivel="h1" compacto alConflicto={conflicto.anotar} />
          <LineaTienda m={m} conVariante={false} />
          {copia}
        </div>
        <FichaProductoMuestra muestra={m} compacta modo="fotos" />
        <ResumenMuestra muestra={m} />
        {principal}
        {conflicto.vigente ? <AvisoConflicto vigente={conflicto.vigente} alCerrar={conflicto.limpiar} /> : null}
        <div className={css.detalleContinuacion}>
          {secundarias}
          <CuerpoDetalle m={m} detalle={detalle} modo="completo" cola={cola} galeriaEnCabecera alConflicto={conflicto.anotar} />
        </div>
      </div>
    );
  }

  return (
    <div className={cx(css.completoAncho)} data-detalle-muestra={m.application_id}>
      <div className={cx(css.columnaFoto)}>
        <FichaProductoMuestra muestra={m} compacta={false} modo="fotos" />
      </div>
      <div className={cx(css.columnaDatos)}>
        {conflicto.vigente ? <AvisoConflicto vigente={conflicto.vigente} alCerrar={conflicto.limpiar} /> : null}
        {/* La luz ambiente ya va detrás de la foto (columna izquierda); repetirla tras el título dejaba una mancha. */}
        <div className={cx(css.encabezadoTexto)}>
          <Rotulo m={m} conTienda />
          <TituloEditable m={m} detalle={detalle} nivel="h2" alConflicto={conflicto.anotar} />
          <LineaTienda m={m} conVariante={false} />
          {copia}
        </div>
        <ResumenMuestra muestra={m} />
        {principal}
        {secundarias}
        <CuerpoDetalle m={m} detalle={detalle} modo="completo" cola={cola} galeriaEnCabecera alConflicto={conflicto.anotar} />
      </div>
    </div>
  );
}

export function DetalleCompleto(p: { id: string }): ReactElement {
  const plataforma = usePlataforma();
  const clase = useClaseAncho();
  const movil = plataforma === 'android' || clase === 'compacta';
  const consulta = useConsulta('muestra', { id: p.id });
  const detalle = consulta.datos?.muestra.application_id === p.id ? consulta.datos : undefined;
  const m = detalle?.muestra;
  const titulo = m ? nombreVisible(m, detalle) : T.tituloDetalle;

  let cuerpo: ReactElement;
  if (m) {
    cuerpo = <Contenido m={m} detalle={detalle} movil={movil} fuente={consulta.fuente} copiaAt={consulta.copia_at} />;
  } else if (consulta.error?.codigo === 'necesita_pc') {
    cuerpo = <NecesitaPc alReintentar={() => void consulta.refrescar()} />;
  } else if (consulta.error) {
    cuerpo = (
      <div className={cx(css.estadoCompleto)}>
        <EstadoVacio icono="CircleHelp" titulo={T.noEncontradaTitulo} texto={T.noEncontradaTexto} accion={{ etiqueta: T.volverALaCola, alPulsar: () => navegar(RUTA_PENDIENTES) }} />
      </div>
    );
  } else {
    cuerpo = (
      <EsqueletoVista textoLento={T.cargandoLento} className={cx(movil ? css.esqueletoMovil : css.esqueletoAncho)}>
        <Esqueleto forma="foto" ancho={movil ? '100%' : 320} alto={movil ? 340 : 400} />
        <div className={cx(css.esqueletoTextos)}>
          <Esqueleto forma="texto" ancho="30%" />
          <Esqueleto forma="titulo" ancho="80%" />
          <Esqueleto forma="texto" ancho="50%" />
          <Esqueleto forma="bloque" alto={88} />
          <Esqueleto forma="bloque" alto={120} />
        </div>
      </EsqueletoVista>
    );
  }

  const mostrarEncabezado = !movil || !m;
  return (
    <Pantalla titulo={titulo} lista={m !== undefined || consulta.error !== null} className={cx(movil ? css.pantallaMovil : css.pantallaAncha)}>
      {mostrarEncabezado ? (
        <EncabezadoPantalla
          titulo={T.detalleEtiqueta}
          volver={{ a: RUTA_PENDIENTES, etiqueta: T.volverMuestras }}
          {...(!movil && m ? { acciones: <BotonIcono icono="X" etiqueta={T.cerrar} alPulsar={volver} /> } : {})}
        />
      ) : null}
      {cuerpo}
    </Pantalla>
  );
}
