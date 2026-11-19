import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactElement } from 'react';
import { Pantalla } from '@/app';
import { Boton, CampoTexto, Casilla, EncabezadoPantalla, EstadoVacio, Modal } from '@/componentes';
import { ErrorHub, invalidar } from '@/datos';
import { obtenerTransporte } from '../../datos/transporte';
import css from './marketplace.module.css';

type Producto = {
  product_id: string;
  titulo: string | null;
  tienda: string | null;
  precio_min: string | null;
  precio_max: string | null;
  moneda: string | null;
};
type Pagina = { productos: Producto[]; cursor_siguiente: string | null; total: number | null };
type Accion = 'agregar' | 'fijar' | 'quitar';
type Resultado = { product_id: string; ok: boolean; codigo: string | null; mensaje: string | null };
type Enlace = { product_id: string; enlace: string | null; codigo: string | null; mensaje: string | null };

const etiquetas: Record<Accion, string> = { agregar: 'Agregar', fijar: 'Fijar arriba', quitar: 'Quitar' };
const scopeValido = /^[a-f0-9]{64}$/;
const idValido = /^[0-9]{1,25}$/;
const destinosTikTok = new Set(['tiktok.com', 'www.tiktok.com', 'shop.tiktok.com', 'vt.tiktok.com', 'vm.tiktok.com']);

function esEnlaceTikTok(valor: string | null | undefined): valor is string {
  if (!valor) return false;
  try {
    const url = new URL(valor);
    return url.protocol === 'https:' && !url.username && !url.password && !url.port && destinosTikTok.has(url.hostname);
  } catch {
    return false;
  }
}

function precio(p: Producto): string {
  if (!p.moneda || !/^[A-Z]{3}$/.test(p.moneda)) return '';
  const formato = new Intl.NumberFormat('es-MX', { style: 'currency', currency: p.moneda, currencyDisplay: 'code' });
  return [...new Set([p.precio_min, p.precio_max])]
    .filter((v): v is string => !!v && /^\d+(\.\d+)?$/.test(v))
    .map(v => formato.format(Number(v))).join(' a ');
}

function mensaje(err: unknown, alternativo: string): string {
  return err instanceof ErrorHub ? err.mensaje : alternativo;
}

export function Vitrina(p: {
  puedeLeer: boolean; puedeEditar: boolean; puedeGenerar: boolean;
  cargandoAcceso?: boolean; idInicial?: string; alVolver: () => void;
}): ReactElement {
  const [productos, setProductos] = useState<Producto[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [scope, setScope] = useState<string | null>(null);
  const [cargando, setCargando] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [errorLectura, setErrorLectura] = useState('');
  const [errorAccion, setErrorAccion] = useState('');
  const [resultados, setResultados] = useState<Resultado[]>([]);
  const [seleccion, setSeleccion] = useState<string[]>([]);
  const [entrada, setEntrada] = useState(p.idInicial ?? '');
  const [confirmacion, confirmar] = useState<{ accion: Accion; ids: string[]; scope: string } | null>(null);
  const [generar, setGenerar] = useState<{ producto: Producto; scope: string } | null>(null);
  const lectura = useRef(0);
  const escribiendo = useRef(false);

  const cargar = useCallback(async (siguiente?: string, anterior?: string | null) => {
    const numero = ++lectura.current;
    setCargando(true);
    setErrorLectura('');
    try {
      const transporte = await obtenerTransporte();
      const sesion = await transporte.obtener('/api/cloud/session') as { cache_scope?: string } | null;
      const actual = sesion?.cache_scope && scopeValido.test(sesion.cache_scope) ? sesion.cache_scope : null;
      if (numero !== lectura.current) return;
      if (siguiente && anterior !== actual) {
        setSeleccion([]);
        setProductos([]);
        setCursor(null);
        setScope(null);
        setErrorLectura('Cambió tu cuenta de TikTok. Actualiza la vitrina.');
        return;
      }
      const params = new URLSearchParams({ limit: '20' });
      if (siguiente) params.set('cursor', siguiente);
      const pagina = await transporte.obtener('/api/catalogo/vitrina?' + params.toString()) as Pagina | null;
      if (numero !== lectura.current) return;
      if (!pagina || !Array.isArray(pagina.productos)) throw new Error('Vitrina');
      setProductos(previos => [...new Map(
        [...(siguiente ? previos : []), ...pagina.productos].map(x => [x.product_id, x]),
      ).values()]);
      setScope(actual);
      setCursor(pagina.cursor_siguiente === siguiente ? null : pagina.cursor_siguiente);
    } catch (err) {
      if (numero === lectura.current) {
        setScope(null);
        setErrorLectura(mensaje(err, 'No pudimos cargar tu vitrina.'));
      }
    } finally {
      if (numero === lectura.current) setCargando(false);
    }
  }, []);

  useEffect(() => {
    if (p.puedeLeer) void cargar();
    return () => { lectura.current++; };
  }, [cargar, p.puedeLeer]);

  const ocupado = cargando || guardando;
  const habilitado = p.puedeEditar && !!scope && !ocupado;

  function preparar(accion: Accion, ids: string[]): void {
    if (!habilitado || !scope || ids.length === 0) return;
    setErrorAccion('');
    confirmar({ accion, ids, scope });
  }

  async function guardar(): Promise<void> {
    if (!confirmacion || escribiendo.current) return;
    const { accion, ids, scope: esperado } = confirmacion;
    escribiendo.current = true;
    confirmar(null);
    setGuardando(true);
    setResultados([]);
    try {
      const respuesta = await (await obtenerTransporte()).pedir(
        'POST', '/api/catalogo/vitrina/' + accion, { product_ids: ids }, esperado,
      ) as { resultados?: Resultado[] } | null;
      if (!Array.isArray(respuesta?.resultados)) throw new Error('Vitrina');
      setResultados(respuesta.resultados);
      const exitosos = new Set(respuesta.resultados.filter(x => x.ok).map(x => x.product_id));
      setSeleccion(previos => previos.filter(id => !exitosos.has(id)));
      if (accion === 'agregar') setEntrada(ids.filter(id => !exitosos.has(id)).join(', '));
      if (exitosos.size) {
        invalidar('productos');
        await cargar();
      }
    } catch (err) {
      setErrorAccion(mensaje(err, 'No pudimos confirmar el cambio. Actualiza la vitrina antes de volver a intentarlo.'));
      setScope(null);
      setSeleccion([]);
    } finally {
      escribiendo.current = false;
      setGuardando(false);
    }
  }

  function agregar(evento: FormEvent): void {
    evento.preventDefault();
    const ids = [...new Set(entrada.trim().split(/[\s,]+/).filter(Boolean))];
    if (!ids.length || ids.length > 20 || ids.some(id => !idValido.test(id))) {
      setErrorAccion('Escribe de 1 a 20 IDs de producto, solo con dígitos.');
      return;
    }
    preparar('agregar', ids);
  }

  return (
    <Pantalla titulo="Vitrina de TikTok Shop" lista>
      <section className={css.pantalla}>
        <EncabezadoPantalla titulo="Vitrina de TikTok Shop"
          acciones={<Boton variante="secundario" alPulsar={p.alVolver}>Volver a Productos</Boton>} />
        {!p.puedeLeer ? (
          p.cargandoAcceso ? <p role="status">Comprobando acceso…</p>
            : <EstadoVacio icono="Store" titulo="Vitrina no disponible" texto="Revisa la conexión a TikTok Shop y el permiso para ver la vitrina." />
        ) : (
          <>
            <div className={css.acciones}>
              <Boton variante="secundario" deshabilitado={ocupado} alPulsar={() => { setSeleccion([]); void cargar(); }}>Actualizar vitrina</Boton>
            </div>
            {p.puedeEditar ? (
              <form className={css.formulario} onSubmit={agregar}>
                <CampoTexto etiqueta="IDs de producto" valor={entrada} alCambiar={setEntrada}
                  maximo={540} monoespaciado ayuda="Separa los IDs con comas o espacios. Máximo 20." />
                <div className={css.acciones}>
                  <Boton tipo="submit" deshabilitado={!habilitado || !entrada.trim()}>Agregar a vitrina</Boton>
                  {seleccion.length ? <>
                    <Boton variante="secundario" deshabilitado={!habilitado} alPulsar={() => preparar('fijar', seleccion)}>Fijar arriba ({seleccion.length})</Boton>
                    <Boton variante="secundario" deshabilitado={!habilitado} alPulsar={() => preparar('quitar', seleccion)}>Quitar ({seleccion.length})</Boton>
                  </> : null}
                </div>
              </form>
            ) : null}
            {errorLectura ? <p role="alert" className={css.aviso}>{errorLectura}</p> : null}
            {errorAccion ? <p role="alert" className={css.aviso}>{errorAccion}</p> : null}
            {resultados.length ? <ul aria-label="Resultado por producto" role="status">
              {resultados.map(x => <li key={x.product_id}>{x.product_id} · {x.ok ? 'Cambio aplicado' : x.mensaje ?? 'Cambio sin confirmar'}</li>)}
            </ul> : null}
            {ocupado ? <p role="status" className={css.aviso}>{guardando ? 'Aplicando cambio en TikTok Shop…' : 'Consultando tu vitrina…'}</p> : null}
            {productos.length ? <ul className={css.resultados} aria-label="Productos de tu vitrina">
              {productos.map(x => {
                const nombre = x.titulo ?? `Producto ${x.product_id}`;
                const marcada = seleccion.includes(x.product_id);
                return <li className={css.fila} key={x.product_id}>
                  <div className={css.cuerpo}>
                    <h2>{nombre}</h2>
                    <p>{[x.tienda, precio(x), x.product_id].filter(Boolean).join(' · ')}</p>
                    {p.puedeEditar ? <Casilla marcada={marcada} etiqueta={`Seleccionar ${nombre}`}
                      deshabilitado={!habilitado || (!marcada && seleccion.length === 20)}
                      alCambiar={marcar => setSeleccion(previos => marcar ? [...previos, x.product_id] : previos.filter(id => id !== x.product_id))} /> : null}
                  </div>
                  {p.puedeGenerar && scope ? <Boton variante="secundario" deshabilitado={ocupado}
                    alPulsar={() => setGenerar({ producto: x, scope })}>Generar enlace</Boton> : null}
                </li>;
              })}
            </ul> : !cargando && !errorLectura ? <EstadoVacio icono="Store" titulo="Tu vitrina está vacía" /> : null}
            {cursor ? <Boton variante="secundario" deshabilitado={ocupado} alPulsar={() => { void cargar(cursor, scope); }}>Cargar más productos</Boton> : null}
          </>
        )}
        {confirmacion ? <Modal abierto alCerrar={() => confirmar(null)}
          titulo={`${etiquetas[confirmacion.accion]} productos de vitrina`}
          descripcion={`Este cambio se aplicará a ${confirmacion.ids.length} producto(s) de tu vitrina en TikTok Shop.`}
          pie={<><Boton variante="fantasma" alPulsar={() => confirmar(null)}>Cancelar</Boton>
            <Boton variante={confirmacion.accion === 'quitar' ? 'peligro' : 'primario'} alPulsar={() => { void guardar(); }}>Confirmar cambio</Boton></>}>
          <p>{confirmacion.ids.join(', ')}</p>
        </Modal> : null}
        {generar ? <DialogoEnlace producto={generar.producto} scope={generar.scope} alCerrar={() => setGenerar(null)} /> : null}
      </section>
    </Pantalla>
  );
}

function DialogoEnlace(p: { producto: Producto; scope: string; alCerrar: () => void }): ReactElement {
  const [publisher, setPublisher] = useState('');
  const [campaña, setCampaña] = useState('');
  const [enlace, setEnlace] = useState('');
  const [aviso, setAviso] = useState('');
  const [error, setError] = useState('');
  const [cargando, setCargando] = useState(false);
  const enCurso = useRef(false);
  async function consultar(): Promise<void> {
    if (enCurso.current) return;
    enCurso.current = true;
    setCargando(true);
    setError('');
    setAviso('');
    setEnlace('');
    try {
      const respuesta = await (await obtenerTransporte()).pedir('POST', '/api/catalogo/enlaces-afiliado', {
        product_ids: [p.producto.product_id],
        ...(publisher.trim() ? { publisher_id: publisher.trim() } : {}),
        ...(campaña.trim() ? { campaign_id: campaña.trim() } : {}),
      }, p.scope) as { resultados?: Enlace[] } | null;
      const resultado = respuesta?.resultados?.find(x => x.product_id === p.producto.product_id);
      if (esEnlaceTikTok(resultado?.enlace)) setEnlace(resultado.enlace);
      else setError(resultado?.mensaje ?? 'TikTok Shop no devolvió un enlace para este producto.');
    } catch (err) {
      setError(mensaje(err, 'No pudimos generar el enlace.'));
    } finally {
      enCurso.current = false;
      setCargando(false);
    }
  }
  async function copiar(): Promise<void> {
    try {
      await navigator.clipboard.writeText(enlace);
      setAviso('Enlace copiado.');
    } catch {
      setAviso('Selecciona la dirección y cópiala manualmente.');
    }
  }
  return <Modal abierto alCerrar={p.alCerrar} titulo="Enlace de afiliado"
    descripcion={p.producto.titulo ?? `Producto ${p.producto.product_id}`}
    pie={<><Boton variante="fantasma" alPulsar={p.alCerrar}>Cerrar</Boton>
      <Boton deshabilitado={cargando} cargando={cargando} alPulsar={() => { void consultar(); }}>Generar enlace</Boton></>}>
    <div className={css.formulario}>
      <CampoTexto etiqueta="ID de publisher (opcional)" valor={publisher} alCambiar={setPublisher} maximo={128} />
      <CampoTexto etiqueta="ID de campaña (opcional)" valor={campaña} alCambiar={setCampaña} maximo={25} />
      {enlace ? <><a className={css.enlaceLargo} href={enlace} target="_blank" rel="noopener noreferrer">{enlace}</a>
        <div className={css.acciones}><Boton variante="secundario" alPulsar={() => { void copiar(); }}>Copiar enlace</Boton></div></> : null}
      {error ? <p role="alert">{error}</p> : null}
      {aviso ? <p role="status">{aviso}</p> : null}
    </div>
  </Modal>;
}
