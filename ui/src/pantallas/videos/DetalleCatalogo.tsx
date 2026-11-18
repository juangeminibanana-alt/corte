/**
 * rev. 6 · Detalle de un video SIN ventas del catálogo (GET /api/catalogo/videos/{id}): lo arma PantallaVideo cuando
 * /api/videos/{id} responde 404 y el hub tiene el catálogo. Misma composición que el detalle con ventas (portada a la
 * izquierda, texto, bloque principal e ID), sin nada de lo que solo existe con pedidos:
 * - «Ventas» dice «Sin ventas» y desde cuándo se puede afirmar (los pedidos guardados empiezan en pedidos_desde de
 *   /api/sync/cobertura), nunca «$0 · 0 pedidos».
 * - «En TikTok»: vistas, likes, comentarios, compartidos y vistas nuevas por día, sin conversión (no hay pedidos).
 * - Muestras vinculadas (por el video planeado), notas del video e ID con [Copiar], como siempre.
 */
import type { ReactElement } from 'react';
import type * as C from '@/contrato';
import { Chip, Icono, Tarjeta } from '@/componentes';
import { formato } from '@/dominio';
import { ListaNotas } from '@/bloques';
import { BotonAbrirVideo, PortadaCatalogo } from './MarcoVideo';
import { KpisTikTok, SinCifrasTikTok, VistasPorDia } from './MetricasVideo';
import { IdVideo, Seccion, SeccionMuestras } from './Piezas';
import { estadoRotulado, sinVentasDe, textoDuracion, type SinVentas } from './logicaCatalogo';
import { T } from './textos';
import { cx } from './util';
import css from './videos.module.css';

/** Texto de «Ventas» de un video sin pedidos (uno con ventas usa el detalle de siempre, nunca este). */
export function textoVentasDetalle(s: SinVentas): string {
  if (s.tipo === 'desde_publicado') return T.sinVentasDetalle;
  if (s.tipo === 'desde') return T.sinVentasDetalleDesde(formato.fechaCorta(s.fecha));
  return T.sinVentasDetalleRegistradas;
}

function MetricasCatalogo(p: { video: C.VideoCatalogo; tendencia: C.PuntoTendenciaVideo[] | null; compacta: boolean }): ReactElement {
  const v = p.video;
  if (v.vistas === null) return <SinCifrasTikTok texto={T.sinCifrasCatalogo} />;
  return (
    <div className={cx(css.tiktok)} data-en-tiktok="">
      <KpisTikTok vistas={v.vistas} video={v} tendencia={p.tendencia ?? []} />
      <Tarjeta padding="amplio" className={cx(css.seccion)}>
        <VistasPorDia tendencia={p.tendencia ?? []} compacta={p.compacta} />
      </Tarjeta>
    </div>
  );
}

export function ContenidoCatalogo(p: {
  detalle: C.VideoCatalogoDetalleResponse;
  nombre: string;
  compacta: boolean;
  android: boolean;
  /** Desde cuándo hay pedidos guardados (null = ninguno); undefined = aún no se sabe (cargando o sin respuesta). */
  pedidosDesde: C.FechaLocal | null | undefined;
}): ReactElement {
  const v = p.detalle.video;
  const sinVentas = p.pedidosDesde === undefined ? null : sinVentasDe(v, p.pedidosDesde) ?? { tipo: 'registradas' as const };
  const estado = estadoRotulado(v);

  const fechas = (
    <div className={cx(css.fechas)}>
      {v.publicado_at !== null ? (
        <span className={cx(css.fecha)}>
          <Icono nombre="Clapperboard" tamano={16} />
          <span>{T.publicadoEl(formato.fechaCorta(v.publicado_at))}</span>
        </span>
      ) : null}
      {typeof v.duracion_s === 'number' && v.duracion_s > 0 ? (
        <span className={cx(css.fecha)}>
          <Icono nombre="Clock" tamano={16} />
          <span>{T.duracion(textoDuracion(v.duracion_s))}</span>
        </span>
      ) : null}
      {estado ? (
        <Chip tono={estado === 'no_publico' ? 'atencion' : 'neutro'} icono={estado === 'no_publico' ? 'EyeOff' : 'CircleDashed'} titulo={T.publicacionAyuda[estado]}>
          {T.publicacion[estado]}
        </Chip>
      ) : null}
    </div>
  );

  // En la ventana va en el lugar de los KPI de ventas (al lado de la portada); en el celular, debajo del botón.
  const ventas = (
    <Seccion titulo={T.ventasTitulo} className={cx(css.kpis)}>
      <p className={cx(css.vacioCorto)} data-sin-ventas={sinVentas?.tipo ?? 'sin_cobertura'}>
        {sinVentas ? textoVentasDetalle(sinVentas) : T.sinVentasDetalleSinCobertura}
      </p>
    </Seccion>
  );

  return (
    <div className={cx(css.detalle)} data-compacta={p.compacta ? '' : undefined} data-catalogo="">
      <div className={cx(css.heroe)}>
        <PortadaCatalogo video={v} nombre={p.nombre} anchoCss={p.compacta ? 150 : 300} className={cx(css.heroePortada)} />
        <div className={cx(css.heroeTexto)}>
          <p className={cx(css.overline)}>{T.overlineCatalogo[v.publicacion]}</p>
          {fechas}
          {p.android && !p.compacta ? <BotonAbrirVideo enlace={v.enlace} variante="primario" tamano="lg" anchoCompleto /> : null}
          {!p.android && !p.compacta ? <BotonAbrirVideo enlace={v.enlace} variante="secundario" className={cx(css.soloVentanaAngosta)} /> : null}
        </div>
        {!p.compacta ? ventas : null}
        {!p.compacta ? <IdVideo id={v.content_id} /> : null}
      </div>
      {p.compacta ? <BotonAbrirVideo enlace={v.enlace} variante="primario" tamano="lg" anchoCompleto /> : null}
      {p.compacta ? ventas : null}
      <MetricasCatalogo video={v} tendencia={p.detalle.tendencia} compacta={p.compacta} />

      <div className={cx(css.columnas)}>
        <div className={cx(css.columnaAncha)}>
          <SeccionMuestras ids={v.muestras_vinculadas} />
        </div>
        <div className={cx(css.columnaLateral)}>
          {/* ListaNotas ya es una tarjeta con su título: va sola, con el padding y la sombra de las demás. */}
          <div className={cx(css.notasPagina)}>
            <ListaNotas entidad="video" entidadId={v.content_id} titulo={T.notas} className={cx(css.notasTarjeta)} />
          </div>
          {p.compacta ? <IdVideo id={v.content_id} /> : null}
        </div>
      </div>
    </div>
  );
}
