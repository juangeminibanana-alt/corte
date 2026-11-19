import { useRef, useState, type FormEvent, type ReactElement } from 'react';
import { Pantalla } from '@/app';
import { Boton, CampoTexto, EncabezadoPantalla, EstadoVacio } from '@/componentes';
import { ErrorHub } from '@/datos';
import { obtenerTransporte } from '../../datos/transporte';
import css from './marketplace.module.css';

interface ProductoMarketplace {
  product_id: string;
  titulo: string | null;
  tienda: string | null;
  precio_min: string | null;
  precio_max: string | null;
  moneda: string | null;
  comision_porcentaje: number | null;
  unidades_vendidas: number | null;
  categorias: { id: string; nombre: string }[];
  enlace: string | null;
}

interface PaginaMarketplace {
  productos: ProductoMarketplace[];
  cursor_siguiente: string | null;
}

const moneda = (importe: string | null, codigo: string | null): string => {
  if (importe === null || !codigo || !/^[A-Z]{3}$/.test(codigo)) return '';
  const valor = Number(importe);
  return Number.isFinite(valor) ? new Intl.NumberFormat('es-MX', { style: 'currency', currency: codigo, currencyDisplay: 'code' }).format(valor) : '';
};

function precio(producto: ProductoMarketplace): string {
  const desde = moneda(producto.precio_min, producto.moneda);
  const hasta = moneda(producto.precio_max, producto.moneda);
  return desde && hasta && desde !== hasta ? `${desde} a ${hasta}` : desde || hasta;
}

const porcentaje = new Intl.NumberFormat('es-MX', { maximumFractionDigits: 2 });
const campos = [
  ['min_price', 'Precio mínimo'], ['max_price', 'Precio máximo'],
  ['min_commission', 'Comisión mínima (%)'], ['max_commission', 'Comisión máxima (%)'],
] as const;
const ordenes = [
  ['', 'Relevancia'], ['units_sold:DESC', 'Más vendidos'], ['commission_rate:DESC', 'Mayor comisión'],
  ['commission:DESC', 'Mayor importe de comisión'], ['product_sales_price:ASC', 'Precio de menor a mayor'],
  ['product_sales_price:DESC', 'Precio de mayor a menor'],
] as const;

export function Marketplace(p: { puedeBuscar: boolean; alVolver: () => void }): ReactElement {
  const [q, setQ] = useState('');
  const [filtros, setFiltros] = useState<Partial<Record<(typeof campos)[number][0], string>>>({});
  const [categoria, setCategoria] = useState<{ id: string; nombre: string } | null>(null);
  const [orden, setOrden] = useState('');
  const [productos, setProductos] = useState<ProductoMarketplace[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [consultada, setConsultada] = useState(false);
  const [error, setError] = useState('');
  const [cargando, setCargando] = useState(false);
  const consulta = useRef<URLSearchParams | null>(null);
  const enCurso = useRef(false);

  async function cargar(parametros: URLSearchParams, siguiente: string | null = null): Promise<void> {
    if (enCurso.current || !p.puedeBuscar) return;
    enCurso.current = true;
    setCargando(true);
    setError('');
    const pagina = new URLSearchParams(parametros);
    if (siguiente) pagina.set('cursor', siguiente);
    else {
      setConsultada(false);
      setProductos([]);
      setCursor(null);
      consulta.current = parametros;
    }
    try {
      const datos = await (await obtenerTransporte()).obtener(`/api/catalogo/marketplace?${pagina.toString()}`) as PaginaMarketplace | null;
      if (!datos || !Array.isArray(datos.productos)) throw new Error('Respuesta inesperada');
      setProductos((actuales) => {
        const items = new Map((siguiente ? actuales : []).map((x) => [x.product_id, x]));
        for (const producto of datos.productos) items.set(producto.product_id, producto);
        return [...items.values()];
      });
      setConsultada(true);
      setCursor(datos.cursor_siguiente !== siguiente ? datos.cursor_siguiente : null);
    } catch (err) {
      setError(err instanceof ErrorHub ? err.mensaje : 'No pudimos consultar TikTok Shop. Inténtalo de nuevo.');
    } finally {
      enCurso.current = false;
      setCargando(false);
    }
  }

  function buscar(evento: FormEvent<HTMLFormElement>): void {
    evento.preventDefault();
    const params = new URLSearchParams({ limit: '20' });
    if (q.trim()) params.set('q', q.trim());
    if (categoria) params.set('category_id', categoria.id);
    for (const [campo] of campos) {
      const valor = filtros[campo]?.trim().replace(',', '.');
      if (valor) params.set(campo, valor);
    }
    if (orden) {
      const [campo, direccion] = orden.split(':') as [string, string];
      params.set('sort', campo);
      params.set('direction', direccion);
    }
    void cargar(params);
  }

  return (
    <Pantalla titulo="Explorar TikTok Shop" lista>
      <section className={css.pantalla}>
        <EncabezadoPantalla titulo="Explorar TikTok Shop" contexto="Busca productos de colaboración abierta."
          acciones={<Boton variante="secundario" alPulsar={p.alVolver}>Volver a Productos</Boton>} />
        {p.puedeBuscar ? (
          <>
            <form onSubmit={buscar} className={css.formulario}>
              <CampoTexto etiqueta="Producto" tipo="search" valor={q} alCambiar={setQ} maximo={255} placeholder="Busca por nombre" />
              <div className={css.filtros}>
                {campos.map(([campo, etiqueta]) => (
                  <CampoTexto key={campo} etiqueta={etiqueta} valor={filtros[campo] ?? ''} maximo={16}
                    alCambiar={(valor) => setFiltros((previos) => ({ ...previos, [campo]: valor }))} />
                ))}
                <label className={css.campoOrden}>Orden
                  <select value={orden} onChange={(evento) => setOrden(evento.target.value)}>
                    {ordenes.map(([valor, nombre]) => <option key={valor} value={valor}>{nombre}</option>)}
                  </select>
                </label>
              </div>
              <div className={css.acciones}>
                <Boton tipo="submit" cargando={cargando} deshabilitado={cargando}>Buscar</Boton>
                {categoria ? <Boton variante="secundario" alPulsar={() => setCategoria(null)}>Quitar categoría: {categoria.nombre}</Boton> : null}
              </div>
            </form>
            {error ? <p className={css.aviso} role="alert">{error}</p> : null}
            {cargando ? <p className={css.aviso} role="status">Consultando TikTok Shop…</p> : null}
            {consultada && !cargando && productos.length === 0 ? <EstadoVacio icono="Search" titulo="No encontramos productos" texto="Prueba con otro nombre o ajusta los filtros." /> : null}
            {productos.length ? (
              <ul className={css.resultados} aria-label="Resultados de TikTok Shop">
                {productos.map((x) => (
                  <li key={x.product_id} className={css.fila}>
                    <div className={css.cuerpo}>
                      <h2>{x.titulo ?? `Producto ${x.product_id}`}</h2>
                      {x.tienda ? <p>{x.tienda}</p> : null}
                      <p>{[precio(x), x.comision_porcentaje == null ? '' : `${porcentaje.format(x.comision_porcentaje)} % de comisión`,
                        x.unidades_vendidas == null ? '' : `${porcentaje.format(x.unidades_vendidas)} vendidos`].filter(Boolean).join(' · ')}</p>
                      {x.categorias.length ? <div className={css.acciones}>
                        {x.categorias.filter((c) => c.id !== categoria?.id).map((c) => (
                          <Boton key={c.id} variante="secundario" tamano="sm" alPulsar={() => setCategoria(c)} aria-label={`Seleccionar categoría ${c.nombre}`}>{c.nombre}</Boton>
                        ))}
                      </div> : null}
                    </div>
                    {x.enlace ? <a href={x.enlace} target="_blank" rel="noopener noreferrer">Ver en TikTok</a> : null}
                  </li>
                ))}
              </ul>
            ) : null}
            {cursor ? <Boton variante="secundario" deshabilitado={cargando} alPulsar={() => {
              if (consulta.current) void cargar(consulta.current, cursor);
            }}>Cargar más productos</Boton> : null}
          </>
        ) : <EstadoVacio icono="Store" titulo="Búsqueda de TikTok Shop no disponible" texto="Revisa la conexión y el permiso de colaboraciones de creador en Ajustes." />}
      </section>
    </Pantalla>
  );
}
