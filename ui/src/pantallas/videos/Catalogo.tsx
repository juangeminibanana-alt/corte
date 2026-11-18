/**
 * #/videos?segmento=todos · «Todos» (rev. 6): una sola cuadrícula con los videos PUBLICADOS en tu cuenta de TikTok
 * (Display API) y los videos CON VENTAS, unidos por ID exacto (GET /api/catalogo/videos). Solo existe si el hub anuncia
 * capacidades.catalogo_videos; si aun así responde 404, PantallaVideos vuelve a «Con ventas» sin pestañas.
 * - Un video sin pedidos dice «Sin ventas» y desde cuándo se puede afirmar (pedidos_desde), nunca «$0 · 0 pedidos».
 * - «Ya no es público» / «Sin confirmar» rotulan los videos que TikTok ya no devolvió en su última lectura.
 * - Sin métricas de TikTok, o con la cuenta de otra persona (o sin poder comprobarlo), el hub solo lista los videos con
 *   ventas: un aviso lo explica y lleva a Ajustes › Métricas de TikTok.
 * Se pide UNA vez con todo (hasta 2,000, lo más nuevo primero): el orden y los filtros se aplican aquí, sin esperas.
 * Si hay más de 2,000, el hub ordena (Más vistas / Más comisión piden su propia lista) y un texto dice que la búsqueda
 * y el filtro solo cubren los que llegaron.
 */
import { useEffect, useMemo, useState, type ReactElement } from 'react';
import type * as C from '@/contrato';
import { useConsulta } from '@/datos';
import { navegar, useParametro } from '@/app';
import { Boton, CampoTexto, Chip, ChipFiltro, EstadoVacio, Foto, Icono, Menu } from '@/componentes';
import { formato } from '@/dominio';
import { RUTA_SEGMENTO } from './Cabecera';
import { CargaRejilla, ErrorVista } from './Estados';
import { cifraCompacta } from './logica';
import {
  LIMITE_CATALOGO, PARAMS_CATALOGO, avisoCatalogo, estadoRotulado, filtrarCatalogo, nombreCatalogo, ordenCatalogoDe, ordenarCatalogo,
  ordenesCatalogoPara, sinVentasDe, type AvisoCatalogo as TipoAviso, type SinVentas,
} from './logicaCatalogo';
import { T } from './textos';
import { cx, rutaVideo } from './util';
import css from './videos.module.css';

const RUTA_METRICAS = '/ajustes/metricas';

const TEXTO_AVISO: Readonly<Record<TipoAviso, string>> = {
  sin_metricas: T.avisoSinMetricas,
  otra_cuenta: T.avisoOtraCuenta,
  sin_comprobar: T.avisoSinComprobar,
};

function AvisoCatalogo(p: { aviso: TipoAviso }): ReactElement {
  return (
    <div className={cx(css.catalogoAviso)} role="note" data-aviso={p.aviso}>
      <Icono nombre="Info" tamano={20} className={cx(css.catalogoAvisoIcono)} />
      <p className={cx(css.catalogoAvisoTexto)}>{TEXTO_AVISO[p.aviso]}</p>
      <Boton variante="secundario" tamano="sm" iconoFinal="ChevronRight" alPulsar={() => navegar(RUTA_METRICAS)}>{T.avisoAccion}</Boton>
    </div>
  );
}

/** Segundo renglón de «Sin ventas»: desde que se publicó · desde el 3 mar · registradas. */
export function detalleSinVentas(s: SinVentas): string {
  if (s.tipo === 'desde_publicado') return T.sinVentasDesdePublicado;
  if (s.tipo === 'desde') return T.sinVentasDesde(formato.fechaCorta(s.fecha));
  return T.sinVentasRegistradas;
}

export function TarjetaCatalogo(p: { video: C.VideoCatalogo; pedidosDesde: C.FechaLocal | null; conMetricas: boolean }): ReactElement {
  const v = p.video;
  const nombre = nombreCatalogo(v);
  const sinVentas = sinVentasDe(v, p.pedidosDesde);
  const estado = estadoRotulado(v);
  // Un video «Sin confirmar» o «Ya no es público» trae cifras de antes de la última lectura: van con su propia fecha.
  const vistas = typeof v.vistas !== 'number' ? null
    : estado && typeof v.metricas_at === 'number' ? T.vistasAl(cifraCompacta(v.vistas), formato.fechaCorta(v.metricas_at))
      : T.vistas(cifraCompacta(v.vistas));
  const publicado = v.publicado_at !== null ? T.publicadoEl(formato.fechaCorta(v.publicado_at)) : null;
  const ventas = v.ventas;
  const dinero = ventas ? formato.dinero(ventas.comision_estimada_centavos) : '';
  const ventasTexto = ventas
    ? T.ventasTarjeta(dinero, ventas.pedidos_validos)
    : sinVentas ? `${T.sinVentas} ${detalleSinVentas(sinVentas)}` : null;
  // El porqué del estado va también en el nombre accesible (el title del chip solo se ve al pasar el puntero).
  const etiqueta = T.etiquetaCatalogo([
    T.verVideo(nombre), estado ? `${T.publicacion[estado]}: ${T.publicacionAyuda[estado]}` : null, ventasTexto, vistas, publicado,
  ]);
  return (
    <li className={cx(css.videoCard)} data-sin-ventas={ventas ? undefined : ''} data-publicacion={v.publicacion}>
      <button type="button" className={css.videoAbrir} onClick={() => navegar(rutaVideo(v.content_id, 'todos'))} aria-label={etiqueta}>
        <span className={css.videoPortada}>
          {v.portada ? (
            <Foto url={v.portada} alt="" anchoCss={280} proporcion="9:16" radio="xs" className={cx(css.videoFoto)} />
          ) : (
            <span className={css.videoSinPortada}><Icono nombre="SquarePlay" tamano={24} /><span>{T.portadaNoDisponible}</span></span>
          )}
          {v.portada ? <span className={css.videoPlay} aria-hidden="true"><Icono nombre="Play" tamano={22} /></span> : null}
          {estado ? (
            <span className={cx(css.catalogoEstado)}>
              <span className={cx(css.catalogoEstadoFondo)}>
                <Chip tono={estado === 'no_publico' ? 'atencion' : 'neutro'} icono={estado === 'no_publico' ? 'EyeOff' : 'CircleDashed'} titulo={T.publicacionAyuda[estado]}>
                  {T.publicacion[estado]}
                </Chip>
              </span>
            </span>
          ) : null}
        </span>
        <span className={css.videoContenido}>
          <span className={css.videoNombre} title={nombre}>{nombre}</span>
          {ventas ? (
            <span className={css.videoNumeros}>
              <span><strong>{dinero}</strong><span>{T.kpiComision}</span></span>
              <span><strong>{formato.numero(ventas.pedidos_validos)}</strong><span>{T.kpiPedidos}</span></span>
            </span>
          ) : sinVentas ? (
            <span
              className={cx(css.videoNumeros, css.catalogoSinVentas)}
              data-sin-ventas={sinVentas.tipo}
              {...(sinVentas.tipo === 'desde' ? { title: T.sinVentasDesdeAyuda(formato.fechaCorta(sinVentas.fecha)) } : {})}
            >
              <span><strong>{T.sinVentas}</strong><span>{detalleSinVentas(sinVentas)}</span></span>
            </span>
          ) : null}
          {vistas || publicado || p.conMetricas ? (
            <span className={cx(css.videoVistas, css.catalogoPie)}>
              {vistas ? (
                <span className={cx(css.sinCorte, css.catalogoVistas)}><Icono nombre="Eye" tamano={14} />{vistas}</span>
              ) : p.conMetricas ? (
                <span className={cx(css.pieSinCifras)} title={T.sinCifrasAyuda}>{T.sinCifras}</span>
              ) : null}
              {publicado ? <span className={cx(css.sinCorte)}>{publicado}</span> : null}
            </span>
          ) : null}
        </span>
      </button>
    </li>
  );
}

export function VistaCatalogo(p: { alListo: (lista: boolean) => void }): ReactElement {
  const { alListo } = p;
  const [ordenParam, setOrden] = useParametro('orden');
  const [q, setQ] = useState('');
  const [soloSinVentas, setSoloSinVentas] = useState(false);
  const base = useConsulta('catalogo_videos', PARAMS_CATALOGO);
  const conMetricas = !!base.datos && base.datos.display !== null;
  const orden = ordenCatalogoDe(ordenParam, conMetricas);
  // Más de 2,000 videos: «Más vistas» y «Más comisión» los ordena el hub (si no, faltarían los primeros de esa lista).
  const recortada = !!base.datos && base.datos.items.length < base.datos.total;
  const pideOrden = recortada && orden !== 'publicado';
  const ordenada = useConsulta('catalogo_videos', { orden, limite: LIMITE_CATALOGO }, { activa: pideOrden });
  const catalogo = pideOrden && ordenada.datos ? ordenada : base;
  const d = catalogo.datos;
  const items = d?.items;

  // Un hub que anuncia el catálogo pero responde 404: PantallaVideos lo lee de la misma consulta y vuelve a «Con ventas».
  const noExiste = !base.datos && base.error?.codigo === 'no_encontrado';
  const lista = !!d || (!!catalogo.error && !noExiste);
  useEffect(() => {
    alListo(lista);
  }, [lista, alListo]);

  const aviso = d ? avisoCatalogo(d.display) : null;
  const visibles = useMemo(() => ordenarCatalogo(filtrarCatalogo(items ?? [], { q, soloSinVentas }), orden), [items, q, soloSinVentas, orden]);
  const nSinVentas = useMemo(() => (items ?? []).filter((v) => v.ventas === null).length, [items]);
  const hayFiltros = q.trim() !== '' || soloSinVentas;
  const metricasAt = d?.display?.misma_cuenta === true ? d.display.ultima_sync_at : null;

  let cuerpo: ReactElement;
  if (!d && catalogo.error && !noExiste) {
    cuerpo = (
      <ErrorVista
        error={catalogo.error}
        titulo={T.errorTitulo}
        alReintentar={() => void catalogo.refrescar()}
        textoNecesitaPc={T.catalogoNecesitaPc}
        accionNecesitaPc={{ etiqueta: T.verConVentas, alPulsar: () => navegar(RUTA_SEGMENTO.ventas, { reemplazar: true }) }}
      />
    );
  } else if (!d) {
    cuerpo = <CargaRejilla />;
  } else if (d.items.length === 0) {
    cuerpo = (
      <EstadoVacio
        icono="SquarePlay"
        titulo={T.catalogoVacioTitulo}
        texto={aviso === 'sin_metricas' ? T.catalogoVacioSinMetricas : aviso ? T.catalogoVacioSoloVentas : T.catalogoVacioTexto}
        className={cx(css.estado)}
      />
    );
  } else if (visibles.length === 0) {
    cuerpo = (
      <EstadoVacio
        icono="Search"
        titulo={T.sinResultados}
        texto={T.sinResultadosTexto}
        accion={{ etiqueta: T.quitarFiltros, alPulsar: () => { setQ(''); setSoloSinVentas(false); } }}
        className={cx(css.estado)}
      />
    );
  } else {
    cuerpo = (
      <ul className={cx(css.rejilla)} aria-label={T.catalogoEtiqueta}>
        {visibles.map((v) => <TarjetaCatalogo key={v.content_id} video={v} pedidosDesde={d.pedidos_desde} conMetricas={conMetricas} />)}
      </ul>
    );
  }

  // Va dentro del <Pantalla> de PantallaVideos, debajo del encabezado y de las pestañas (no se vuelve a montar al cambiar).
  return (
    <>
      {aviso ? <AvisoCatalogo aviso={aviso} /> : null}
      <div className={css.videoHerramientas}>
        <CampoTexto etiqueta={T.buscarCatalogo} etiquetaOculta tipo="search" placeholder={T.buscarCatalogo} valor={q} alCambiar={setQ} className={cx(css.videoBuscar)} />
        <Menu
          etiqueta={T.ordenCatalogo[orden]}
          icono="ArrowDownUp"
          disparador="boton"
          opciones={ordenesCatalogoPara(conMetricas).map((o) => ({
            id: o,
            etiqueta: T.ordenCatalogo[o],
            ...(o === orden ? { icono: 'Check' as const } : {}),
            alPulsar: () => setOrden(o === 'publicado' ? null : o, { reemplazar: true }),
          }))}
        />
      </div>
      {d && nSinVentas > 0 ? (
        <div className={css.chips} role="group" aria-label={T.filtros}>
          <ChipFiltro activo={soloSinVentas} conteo={nSinVentas} alCambiar={setSoloSinVentas}>{T.filtroSinVentas}</ChipFiltro>
        </div>
      ) : null}
      {d ? (
        <p className={css.videoConteo} aria-live="polite">
          {hayFiltros ? T.catalogoConteoFiltrado(visibles.length, d.total) : T.catalogoConteo(d.total)}
          <span>{aviso ? T.catalogoAlcanceSoloVentas : T.catalogoAlcance}</span>
          {typeof metricasAt === 'number' ? <span>{T.catalogoMetricasAl(formato.fechaCorta(metricasAt))}</span> : null}
        </p>
      ) : null}
      {d && d.items.length < d.total ? <p className={cx(css.mostrando)}>{T.catalogoRecorte(d.items.length, d.total)}</p> : null}
      <div className={cx((catalogo.refrescando || (pideOrden && !ordenada.datos)) && css.refrescando)}>{cuerpo}</div>
    </>
  );
}
