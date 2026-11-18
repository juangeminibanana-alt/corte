/**
 * Ficha completa de producto (contrato rev. 4, 15/11: ProductoDetalleResponse.extendido, solo endpoints de LECTURA de
 * la API oficial de afiliados). Secciones de #/productos/:id, cada una se oculta entera si no hay datos:
 *  - GaleriaProducto: foto grande + tira de las fotos de tu vitrina ('/img/g/…'); Guardar imagen guarda la que ves;
 *  - SeccionComision: la tasa que de verdad pagaron tus pedidos (la más común destacada), plan abierto y planes
 *    dirigidos, y las tasas por pedido;
 *  - SeccionPrecio: lista, venta en tu vitrina, con descuento de TikTok Shop y lo que pagaron tus compradores;
 *  - BloqueMuestraExtendida: si puedes pedir muestra, solicitudes anteriores con su variante y las variantes (SKU);
 *  - SeccionOrigen: de dónde vienen tus ventas, en dos bloques que nunca se suman: pedidos recientes con el enlace que
 *    reporta orders/search 202410 (rev. 7; solo si TikTok reportó alguno) y el histórico cerrado de orders/trace/search
 *    (retirada el 15/08/2026; ya no hay nota de permiso: la ruta dejó de existir);
 *  - SeccionParecidos: parecidos del marketplace por palabras del título, por mejor comisión o más vendidos.
 * Solo componentes de @/componentes y @/bloques; textos en ./textos y cifras con `formato`.
 */
import { useId, useMemo, useState, type CSSProperties, type ReactElement, type ReactNode } from 'react';
import type * as C from '@/contrato';
import { navegar, type ClaseAncho } from '@/app';
import {
  BarraApilada, BarrasHorizontales, Boton, Chip, Foto, Icono, Segmentado, Tarjeta, TarjetaProducto, useToast, type BarraApiladaProps,
} from '@/componentes';
import { BotonGuardarImagen } from '@/bloques';
import { formato } from '@/dominio';
import { abrirExterno } from '@/plataforma';
import {
  type CriterioParecidos, MAX_SKUS, estiloCumplimiento, estiloElegibilidad, estiloSku, extendidoDe, ordenarParecidos,
  puedePedirOtra, puntosDe, resumenSkus, slotsDeEnlace, vistaComision, vistaOrigen, vistaPrecio,
} from './logicaFicha';
import { nombreVisible } from './logica';
import { T } from './textos';
import { cx, rutaProducto } from './util';
import css from './productos.module.css';

// ---------------------------------------------------------------------------------------------- estructura

export function Seccion(p: { titulo: string; nota?: ReactNode; children: ReactNode; id?: string; acciones?: ReactNode; className?: string }): ReactElement {
  return (
    <Tarjeta padding="amplio" className={cx(css.seccion, p.className)}>
      <section aria-label={p.titulo} className={cx(css.seccionInterior)} {...(p.id ? { id: p.id } : {})}>
        <header className={cx(css.seccionCabeza, p.acciones ? css.seccionCabezaConAcciones : null)}>
          <div className={cx(css.seccionTitulos)}>
            <h2 className={cx(css.seccionTitulo)}>{p.titulo}</h2>
            {p.nota ? <p className={cx(css.seccionNota)}>{p.nota}</p> : null}
          </div>
          {p.acciones ? <div className={cx(css.seccionAcciones)}>{p.acciones}</div> : null}
        </header>
        {p.children}
      </section>
    </Tarjeta>
  );
}

/** Renglón etiqueta / cifra de las secciones de comisión y precio. */
function Renglon(p: { etiqueta: ReactNode; detalle?: ReactNode; cifra: ReactNode; chip?: ReactNode; tachada?: boolean; dato?: string }): ReactElement {
  return (
    <div className={cx(css.renglon)} {...(p.dato ? { 'data-renglon': p.dato } : {})}>
      <dt className={cx(css.renglonTexto)}>
        <span className={cx(css.renglonEtiqueta)}>{p.etiqueta}</span>
        {p.detalle ? <span className={cx(css.renglonDetalle)}>{p.detalle}</span> : null}
      </dt>
      <dd className={cx(css.renglonValor)}>
        {p.chip}
        <span className={cx(css.renglonCifra, p.tachada && css.tachada)}>{p.cifra}</span>
      </dd>
    </div>
  );
}

const dineroDe = (r: readonly [C.Centavos, C.Centavos]): string => formato.rangoDinero(r[0], r[1]);

// ---------------------------------------------------------------------------------------------- galería

export interface GaleriaProductoProps {
  productoId: string;
  principal: C.UrlImagen | null;
  fotos: readonly C.UrlImagen[];
  nombre: string;
  compacta: boolean;
  tienda: string | null;
  categoria: string | null;
  resumen: C.ProductoResumen | null;
  guardar?: boolean;
}

/** La galería de la vitrina es la colección; la foto principal sirve de respaldo si no hay galería. */
export function GaleriaProducto(p: GaleriaProductoProps): ReactElement {
  const [seleccion, setSeleccion] = useState<{ productoId: string; url: C.UrlImagen }>({ productoId: p.productoId, url: '' });
  const galeria = [...new Set(p.fotos.filter((url): url is C.UrlImagen => !!url))];
  const fotos = galeria.length ? galeria : p.principal ? [p.principal] : [];
  const total = fotos.length;
  const elegida = seleccion.productoId === p.productoId && fotos.includes(seleccion.url) ? seleccion.url : null;
  const actual = elegida ?? fotos[0] ?? null;
  const indice = actual ? fotos.indexOf(actual) : -1;
  const alt = indice >= 0 ? T.fotoDe(indice + 1, total, p.nombre) : p.nombre;
  const nombreArchivo = indice >= 0 ? `${p.nombre} ${indice + 1}.jpg` : `${p.nombre}.jpg`;
  return (
    <div className={cx(css.heroeFoto)} data-galeria-producto="" data-compacta={p.compacta ? '' : undefined}>
      <div className={css.marcoFotoPrincipal}>
        <Foto
        url={actual}
        alt={alt}
        anchoCss={p.compacta ? 360 : 340}
        proporcion="1:1"
        radio="xl"
        prioridad="alta"
        tienda={p.tienda}
        categoria={p.categoria}
        arrastrable={{ nombreArchivo }}
        className={cx(css.fotoPrincipal)}
        />
        {total > 1 ? <span className={css.contadorFoto} aria-hidden="true">{indice + 1} / {total}</span> : null}
      </div>
      {total > 1 ? (
        <div className={cx(css.galeria)} data-galeria="">
          <ul className={cx(css.tira)} role="list" aria-label={T.galeria}>
            {fotos.map((u, i) => (
              <li key={`${p.productoId}-${i}`} className={cx(css.tiraElemento)}>
                <button
                  type="button"
                  className={cx(css.miniFoto)}
                  aria-pressed={indice === i}
                  aria-label={T.verFoto(i + 1, total)}
                  onClick={() => setSeleccion({ productoId: p.productoId, url: u })}
                >
                  <Foto url={u} alt="" anchoCss={p.compacta ? 64 : 56} radio="md" tienda={p.tienda} categoria={p.categoria} className={cx(css.miniFotoImagen)} />
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {p.guardar !== false && p.resumen && actual ? <BotonGuardarImagen producto={{ ...p.resumen, imagen: actual }} className={cx(css.guardar)} /> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------- chips de vitrina

/** «Agotado en tu vitrina» · «Oculto en tu vitrina» (el «En tu vitrina» lo pone el héroe). null si no aplica. */
export function ChipsVitrina(p: { vitrina: C.VitrinaProducto | null }): ReactElement | null {
  const v = p.vitrina;
  if (!v || (v.con_existencias !== false && !v.oculto)) return null;
  return (
    <>
      {v.con_existencias === false ? <Chip tono="atencion" icono="CircleAlert">{T.agotadoVitrina}</Chip> : null}
      {v.oculto ? <Chip tono="neutro" icono="EyeOff">{T.ocultoVitrina}</Chip> : null}
    </>
  );
}

// ---------------------------------------------------------------------------------------------- comisión

export function SeccionComision(p: { d: C.ProductoDetalleResponse }): ReactElement | null {
  const v = vistaComision(p.d);
  if (!v) return null;
  const real = v.real;
  const principal = v.principal;
  const varias = !!real && real.por_tasa.length > 1;
  const dif = v.diferenciaBp;
  const tasaPlan = v.abierto ? formato.tasaBp(v.abierto.bp) : '';
  const tasaReal = real ? formato.tasaBp(real.tasa_principal_bp) : '';
  return (
    <Seccion titulo={T.comision} nota={T.comisionNota} id="ficha-comision" className={cx(css.seccionDato)}>
      {real && principal ? (
        <div className={cx(css.destacado)} data-destacado="">
          <div className={cx(css.destacadoTexto)}>
            <span className={cx(css.destacadoEtiqueta)}>
              {T.enTusPedidos}
              {varias ? <Chip tono="marca" icono="Star">{T.laMasComun}</Chip> : null}
            </span>
            <span className={cx(css.destacadoNota)}>
              {varias ? T.enTusPedidosNota(formato.porcentaje(principal.participacion), real.lineas) : T.enTusPedidosUnica(real.lineas)}
            </span>
          </div>
          <span className={cx(css.cifraGrande)}>{tasaReal}</span>
        </div>
      ) : null}
      {v.abierto || v.dirigidos.length > 0 ? (
        <dl className={cx(css.renglones)}>
          {v.abierto ? (
            <Renglon
              dato="abierto"
              etiqueta={T.planAbierto}
              detalle={v.abierto.porVentaMin !== null ? T.porVentaAprox(formato.rangoDinero(v.abierto.porVentaMin, v.abierto.porVentaMax)) : T.planAbiertoNota}
              cifra={tasaPlan}
            />
          ) : null}
          {v.dirigidos.map((pl) => (
            <Renglon
              key={pl.collab_id}
              dato="dirigido"
              etiqueta={pl.nombre ? `${T.planDirigido} · ${pl.nombre}` : T.planDirigido}
              detalle={[pl.tienda_nombre, pl.comision_monto_centavos !== null ? T.porVentaAprox(formato.dinero(pl.comision_monto_centavos)) : null].filter(Boolean).join(' · ') || undefined}
              chip={<Chip tono={pl.activo ? 'ok' : 'neutro'} icono={pl.activo ? 'Check' : 'History'}>{pl.estado_texto}</Chip>}
              cifra={pl.comision_bp !== null ? formato.tasaBp(pl.comision_bp) : T.sinTasa}
              tachada={!pl.activo}
            />
          ))}
        </dl>
      ) : null}
      {v.dirigidosOcultos > 0 ? <p className={cx(css.notaChica)}>{T.masPlanes(v.dirigidosOcultos)}</p> : null}
      {real && dif !== null ? (
        <p className={cx(css.diferencia)} data-sentido={dif > 0 ? 'mas' : dif < 0 ? 'menos' : 'igual'}>
          <Icono nombre={dif > 0 ? 'TrendingUp' : dif < 0 ? 'Info' : 'Check'} tamano={16} />
          <span>{dif > 0 ? T.diferenciaMas(tasaReal, puntosDe(dif), tasaPlan) : dif < 0 ? T.diferenciaMenos(tasaReal, puntosDe(dif), tasaPlan) : T.diferenciaIgual(tasaPlan)}</span>
        </p>
      ) : null}
      {real && varias ? (
        <BarrasHorizontales
          titulo={T.tasasTitulo}
          className={cx(css.barras)}
          filas={real.por_tasa.map((t) => ({
            id: String(t.comision_bp),
            etiqueta: formato.tasaBp(t.comision_bp),
            valor: t.lineas,
            texto: T.tasaPedidos(t.lineas),
            secundario: formato.porcentaje(t.participacion),
          }))}
          tablaGemela={{
            columnas: [T.colTasa, T.colPedidos, T.colParte],
            filas: real.por_tasa.map((t) => [formato.tasaBp(t.comision_bp), formato.numero(t.lineas), formato.porcentaje(t.participacion)]),
          }}
        />
      ) : null}
      {real && v.conCampana > 0 ? <p className={cx(css.notaChica)}>{T.conCampana(v.conCampana, Math.max(1, real.campanas))}</p> : null}
    </Seccion>
  );
}

// ---------------------------------------------------------------------------------------------- precio

export function SeccionPrecio(p: { d: C.ProductoDetalleResponse }): ReactElement | null {
  const v = vistaPrecio(p.d);
  if (!v) return null;
  return (
    <Seccion titulo={T.precio} nota={v.deVitrina ? T.precioNotaVitrina : T.precioNotaFicha} id="ficha-precio" className={cx(css.seccionDato)}>
      <dl className={cx(css.renglones)}>
        {v.lista ? <Renglon dato="lista" etiqueta={T.precioLista} cifra={dineroDe(v.lista)} tachada={!!(v.venta || v.plataforma)} /> : null}
        {v.venta ? (
          <Renglon
            dato="venta"
            etiqueta={v.deVitrina ? T.precioVenta : T.precioVentaAprox}
            cifra={v.deVitrina ? dineroDe(v.venta) : formato.rangoDinero(v.venta[0], v.venta[1], { aprox: true })}
          />
        ) : null}
        {v.plataforma ? <Renglon dato="plataforma" etiqueta={T.precioPlataforma} cifra={dineroDe(v.plataforma)} /> : null}
        {v.promedio !== null ? (
          <Renglon dato="promedio" etiqueta={T.precioPromedio} detalle={T.precioPromedioNota(v.unidades)} cifra={formato.dineroAprox(v.promedio)} />
        ) : null}
      </dl>
      {v.descuento !== null ? (
        <p className={cx(css.diferencia)} data-sentido="mas">
          <Icono nombre="Tag" tamano={16} />
          <span>{T.descuento(formato.porcentaje(v.descuento))}</span>
        </p>
      ) : null}
    </Seccion>
  );
}

// ---------------------------------------------------------------------------------------------- muestra

export function ListaSkus(p: { skus: readonly C.SkuMuestra[] }): ReactElement {
  const [todas, setTodas] = useState(false);
  const visibles = todas ? p.skus : p.skus.slice(0, MAX_SKUS);
  const { disponibles, total } = resumenSkus(p.skus);
  return (
    <div className={cx(css.subbloque)} data-skus="">
      <div className={cx(css.subcabeza)}>
        <h3 className={cx(css.subtitulo)}>{T.skusTitulo}</h3>
        <span className={cx(css.subnota)}>{T.skusResumen(disponibles, total)}</span>
      </div>
      <ul className={cx(css.listaSkus)} role="list" aria-label={T.listaSkus}>
        {visibles.map((s) => {
          const estilo = estiloSku(s);
          return (
            <li key={s.sku_id} className={cx(css.sku)} data-disponible={s.disponible === false ? 'no' : 'si'}>
              <span className={cx(css.skuVariante)}>{s.propiedades.map((p) => `${p.nombre}: ${p.valor}`).join(' · ') || s.variante || T.unica}</span>
              {s.precio_centavos !== null ? <span className={cx(css.skuPrecio)}>{formato.dinero(s.precio_centavos)}</span> : null}
              <span className={cx(css.skuEstado)}>
                {estilo ? (
                  <Chip tono={estilo.tono} icono={estilo.icono}>{s.motivo_texto ?? T.disponible}</Chip>
                ) : (
                  <span className={cx(css.skuDisponible)}>
                    <Icono nombre="Check" tamano={14} />
                    {T.disponible}
                  </span>
                )}
              </span>
            </li>
          );
        })}
      </ul>
      {p.skus.length > MAX_SKUS ? (
        <Boton variante="fantasma" tamano="sm" iconoFinal={todas ? 'ChevronLeft' : 'ChevronDown'} alPulsar={() => setTodas((x) => !x)} className={cx(css.verMas)}>
          {todas ? T.verMenos : T.verTodas(p.skus.length)}
        </Boton>
      ) : null}
    </div>
  );
}

/** Elegibilidad (samples/labels), solicitudes anteriores recuperadas y variantes. `antes` = las solicitudes que sí
 *  salen en la búsqueda (TarjetaMuestra), que van entre el estado y las anteriores. */
export function BloqueMuestraExtendida(p: { d: C.ProductoDetalleResponse; antes?: ReactNode }): ReactElement | null {
  const x = extendidoDe(p.d);
  const m = x?.muestra ?? null;
  const recuperadas = x?.solicitudes_recuperadas ?? [];
  if (!m && recuperadas.length === 0) return null;
  const estilo = m ? estiloElegibilidad(m) : null;
  return (
    <div className={cx(css.bloqueMuestra)} data-muestra-extendida="">
      {m && estilo ? (
        <div className={cx(css.estadoMuestra)}>
          <div className={cx(css.chipsFicha)}>
            <Chip tono={estilo.tono} icono={estilo.icono} tamano="lg">{m.estado_texto}</Chip>
            {puedePedirOtra(m) ? <Chip tono="ok" icono="Plus" tamano="lg">{T.puedesPedirOtra}</Chip> : null}
          </div>
          <span className={cx(css.subnota)}>{T.revisado(formato.relativa(m.consultado_at))}</span>
        </div>
      ) : null}
      {p.antes}
      {recuperadas.length > 0 ? (
        <div className={cx(css.subbloque)} data-recuperadas="">
          <div className={cx(css.subcabeza)}>
            <h3 className={cx(css.subtitulo)}>{T.anteriores}</h3>
            <span className={cx(css.subnota)}>{T.anterioresNota}</span>
          </div>
          <ul className={cx(css.listaRecuperadas)} role="list" aria-label={T.anteriores}>
            {recuperadas.map((s) => {
              const ec = estiloCumplimiento(s.cumplimiento);
              const partes = [s.tipo_texto, s.solicitada_at !== null ? T.pedidaEl(formato.fechaCorta(s.solicitada_at)) : null].filter(Boolean);
              return (
                <li key={s.application_id} className={cx(css.recuperada)}>
                  <div className={cx(css.recuperadaTexto)}>
                    <span className={cx(css.recuperadaVariante)}>{s.variante ?? T.sinVariante}</span>
                    {partes.length > 0 ? <span className={cx(css.subnota)}>{partes.join(' · ')}</span> : null}
                  </div>
                  {s.cumplimiento_texto ? <Chip tono={ec.tono} icono={ec.icono}>{s.cumplimiento_texto}</Chip> : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      {m && m.skus.length > 0 ? <ListaSkus skus={m.skus} /> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------- origen

/** Partes de una barra de origen. Sin `slotDe`, el color sigue el orden (gráfica única); con él, cada tipo tiene un color
 *  fijo (las dos barras de enlace). «Sin enlace» / «Sin dato» siempre en neutro. */
function partesOrigen(cuentas: readonly C.CuentaOrigen[], slotDe?: (tipo: string) => number): BarraApiladaProps['partes'] {
  let orden = 0;
  return cuentas.map((c, i) => {
    const neutro = c.tipo === null;
    if (!neutro) orden = Math.min(8, orden + 1);
    const slot = c.tipo === null ? null : Math.min(8, slotDe ? slotDe(c.tipo) : orden);
    return {
      id: `${c.tipo ?? 'sin'}-${i}`,
      etiqueta: c.texto,
      valor: c.lineas,
      texto: formato.numero(c.lineas),
      estilo: neutro ? ('neutro' as const) : ('solido' as const),
      ...(slot === null ? {} : { slot: slot as 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 }),
    };
  });
}

function BarraOrigen(p: { titulo: string; cuentas: readonly C.CuentaOrigen[]; total: number; slotDe?: (tipo: string) => number }): ReactElement | null {
  if (p.cuentas.length === 0) return null;
  return (
    <BarraApilada
      titulo={p.titulo}
      etiquetasDirectas
      partes={partesOrigen(p.cuentas, p.slotDe)}
      tablaGemela={{
        columnas: [T.colOrigen, T.colPedidos, T.colParte],
        filas: p.cuentas.map((c) => [c.texto, formato.numero(c.lineas), formato.porcentaje(p.total > 0 ? c.lineas / p.total : 0)]),
      }}
    />
  );
}

/** Dos bloques que nunca se suman: los pedidos recientes con el enlace que reporta TikTok (rev. 7) y el histórico cerrado.
 *  Cada bloque es un grupo nombrado por su periodo (el rótulo no es un encabezado: los títulos de las gráficas sí lo son)
 *  y, con los dos a la vista, cada gráfica nombra su bloque. Un tipo de enlace tiene el mismo color en las dos barras.
 *  Un hub anterior a la rev. 6 no manda el periodo del histórico: entonces la sección queda como antes, sin rótulos. */
export function SeccionOrigen(p: { d: C.ProductoDetalleResponse }): ReactElement | null {
  const idActual = useId();
  const idHistorico = useId();
  const v = vistaOrigen(p.d);
  if (!v) return null;
  const { actual: a, historico: h } = v;
  const legado = !a && !!h && h.hasta_at === undefined;
  const ambos = !!a && !!h;
  const slotDe = slotsDeEnlace([a?.por_tipo_enlace ?? [], h?.por_tipo_enlace ?? []]);
  return (
    <Seccion titulo={T.origen} nota={legado && h ? T.origenPedidos(h.lineas) : T.origenNota} id="ficha-origen">
      <div className={cx(css.origenBloques)}>
        {a ? (
          <div className={cx(css.subbloque)} data-origen="actual" role="group" aria-labelledby={idActual}>
            <div className={cx(css.subcabeza)}>
              <p className={cx(css.subtitulo)} id={idActual}>{T.origenActual(formato.fechaCorta(a.desde_at), formato.fechaCorta(a.hasta_at))}</p>
              <span className={cx(css.subnota)}>{T.origenPedidosActual(a.lineas)}</span>
            </div>
            <BarraOrigen titulo={ambos ? T.origenEnlaceActual : T.origenEnlace} cuentas={a.por_tipo_enlace} total={a.lineas} slotDe={slotDe} />
            {a.lineas_sin_dato > 0 ? <p className={cx(css.subnota)}>{T.origenSinDato(a.lineas_sin_dato)}</p> : null}
          </div>
        ) : null}
        {h ? (
          <div className={cx(css.subbloque)} data-origen="historico" {...(legado ? {} : { role: 'group', 'aria-labelledby': idHistorico })}>
            {legado ? null : (
              <div className={cx(css.subcabeza)}>
                <p className={cx(css.subtitulo)} id={idHistorico}>{T.origenHistorico(h.hasta_at !== undefined ? formato.fechaCorta(h.hasta_at) : null)}</p>
                <span className={cx(css.subnota)}>{T.origenPedidos(h.lineas)}</span>
              </div>
            )}
            <div className={cx(css.origenBarras)}>
              <BarraOrigen titulo={ambos ? T.origenContenidoHistorico : T.origenContenido} cuentas={h.por_tipo_contenido} total={h.lineas} />
              <BarraOrigen titulo={ambos ? T.origenEnlaceHistorico : T.origenEnlace} cuentas={h.por_tipo_enlace} total={h.lineas} slotDe={slotDe} />
            </div>
          </div>
        ) : null}
      </div>
    </Seccion>
  );
}

// ---------------------------------------------------------------------------------------------- parecidos

/** Columnas de la rejilla de parecidos por clase de ancho; a la vista van dos filas completas (tres en el celular). */
const COLUMNAS_PARECIDOS: Readonly<Record<ClaseAncho, number>> = { compacta: 2, media: 3, expandida: 4, amplia: 5 };

export function SeccionParecidos(p: { d: C.ProductoDetalleResponse; ancho: ClaseAncho }): ReactElement | null {
  const par = extendidoDe(p.d)?.parecidos ?? null;
  const toast = useToast();
  const [criterio, setCriterio] = useState<CriterioParecidos>('comision');
  const [todos, setTodos] = useState(false);
  const ordenados = useMemo(() => (par ? ordenarParecidos(par.items, criterio) : []), [par, criterio]);
  if (!par || par.items.length === 0) return null;
  const compacta = p.ancho === 'compacta';
  const columnas = COLUMNAS_PARECIDOS[p.ancho];
  const tope = columnas * (compacta ? 3 : 2);
  const visibles = todos ? ordenados : ordenados.slice(0, tope);
  const ficha = p.d.ficha;
  const propia = ficha?.comision_bp ?? null;
  const contexto = [
    ...(propia !== null ? [T.esteProductoComision(formato.tasaBp(propia))] : []),
    ...(ficha?.unidades_vendidas_global != null ? [T.vendidosCorto(ficha.unidades_vendidas_global)] : []),
  ];
  return (
    <Seccion
      titulo={T.parecidos}
      nota={T.parecidosNota(par.palabras)}
      id="ficha-parecidos"
      acciones={
        <Segmentado<CriterioParecidos>
          etiqueta={T.ordenParecidos}
          valor={criterio}
          alCambiar={setCriterio}
          opciones={[{ valor: 'comision', etiqueta: T.porComision }, { valor: 'vendidos', etiqueta: T.porVendidos }]}
          {...(compacta ? { anchoCompleto: true } : {})}
        />
      }
    >
      {contexto.length > 0 ? <p className={cx(css.esteProducto)}>{T.esteProducto(contexto)}</p> : null}
      <ul className={cx(css.rejillaParecidos)} role="list" aria-label={T.rejillaParecidos} style={{ '--columnas': columnas } as CSSProperties}>
        {visibles.map((x) => {
          const nombre = nombreVisible(x.titulo_corto, x.titulo);
          const enlace = x.enlace;
          const alPulsar = x.tiene_ficha
            ? () => navegar(rutaProducto(x.product_id))
            : enlace
              ? () => void abrirExterno(enlace).then((ok) => !ok && toast.mostrar({ texto: T.abrirFallo, tono: 'error' }))
              : undefined;
          const porVenta = x.comision_por_venta_centavos !== null ? T.porVentaAprox(formato.rangoDinero(x.comision_por_venta_centavos, x.comision_por_venta_max_centavos)) : undefined;
          return (
            <li key={x.product_id} className={cx(css.celda)}>
              <TarjetaProducto
                imagen={x.imagen}
                nombre={nombre}
                tienda={x.tienda_nombre}
                cifraPrincipal={x.comision_bp !== null ? formato.tasaBp(x.comision_bp) : T.sinTasa}
                {...(porVenta ? { cifraSecundaria: porVenta } : {})}
                chips={
                  <>
                    {x.unidades_vendidas_global !== null ? <Chip tono="neutro">{T.vendidosCorto(x.unidades_vendidas_global)}</Chip> : null}
                    {x.tiene_ficha ? <Chip tono="info" icono="Package">{T.enCorte}</Chip> : null}
                  </>
                }
                {...(alPulsar ? { alPulsar } : {})}
                className={cx(css.tarjeta)}
              />
            </li>
          );
        })}
      </ul>
      <div className={cx(css.parecidosPie)}>
        <span className={cx(css.subnota)}>{T.consultadoEl(formato.fechaCorta(par.consultado_at))}</span>
        {ordenados.length > tope ? (
          <Boton variante="fantasma" tamano="sm" iconoFinal={todos ? 'ChevronLeft' : 'ChevronDown'} alPulsar={() => setTodos((v) => !v)}>
            {todos ? T.verMenosParecidos : T.verTodosParecidos(ordenados.length)}
          </Boton>
        ) : null}
      </div>
    </Seccion>
  );
}
