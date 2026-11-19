import { useMemo, useState, type ReactElement } from 'react';
import type { MuestraVista } from '@/contrato';
import { EnlaceRuta, Pantalla, navegar } from '@/app';
import { Boton, Foto, Icono } from '@/componentes';
import { useConsulta, useSesion, useSync } from '@/datos';
import { ahoraS, esPendiente, formato } from '@/dominio';
import { nombreProducto } from './logica';
import css from './Resumen.module.css';

const ACCESOS = [
  { titulo: 'Organizar muestras', texto: 'Planea tus próximas publicaciones', ruta: '/muestras', icono: 'Package' },
  { titulo: 'Revisar ventas', texto: 'Consulta ingresos y comisiones', ruta: '/ventas', icono: 'ChartColumn' },
  { titulo: 'Ver tus tiendas', texto: 'Da seguimiento a cada colaboración', ruta: '/tiendas', icono: 'Store' },
] as const;

/** Fechas reales y orden estable: primero compromisos vencidos, después el plazo más próximo. */
function ordenarPrioridades(items: readonly MuestraVista[]): MuestraVista[] {
  return items.filter(esPendiente).sort((a, b) =>
    Number(b.grupo === 'vencida') - Number(a.grupo === 'vencida') ||
    (a.fecha_limite_at ?? Number.MAX_SAFE_INTEGER) - (b.fecha_limite_at ?? Number.MAX_SAFE_INTEGER) ||
    (a.posicion_cola ?? Number.MAX_SAFE_INTEGER) - (b.posicion_cola ?? Number.MAX_SAFE_INTEGER) ||
    a.application_id.localeCompare(b.application_id),
  ).slice(0, 5);
}

function Plazo(p: { muestra: MuestraVista }): ReactElement {
  const m = p.muestra;
  if (m.grupo === 'vencida') return <span className={css.plazo} data-urgente="">Plazo vencido</span>;
  if (m.fecha_limite_at !== null) {
    const urgente = m.fecha_limite_at - ahoraS() < 48 * 3600;
    return <span className={css.plazo} data-urgente={urgente ? '' : undefined}>Vence {formato.fechaConDia(m.fecha_limite_at)}</span>;
  }
  if (m.grupo === 'pausada') return <span className={css.plazo}>Muestra pausada</span>;
  return <span className={css.plazo}>Por organizar</span>;
}

function FilaPrioridad(p: { muestra: MuestraVista }): ReactElement {
  const m = p.muestra;
  return (
    <li>
      <EnlaceRuta a={`/muestras/m/${encodeURIComponent(m.application_id)}`} className={css.prioridad}>
        <Foto url={m.producto.imagen} alt="" anchoCss={48} proporcion="1:1" radio="sm" tienda={m.tienda.nombre} categoria={m.producto.categoria} />
        <span className={css.prioridadTexto}>
          <strong>{nombreProducto(m)}</strong>
          <span>{m.tienda.nombre}</span>
          <Plazo muestra={m} />
        </span>
        <Icono nombre="ChevronRight" tamano={18} />
      </EnlaceRuta>
    </li>
  );
}

/** Resumen breve. El trabajo y los análisis completos viven en sus propias vistas. */
export function PantallaInicio(): ReactElement {
  const sesion = useSesion();
  const sync = useSync();
  const muestras = useConsulta('muestras', {});
  const dashboard = useConsulta('dashboard', { periodo: '30d' });
  const [actualizando, setActualizando] = useState(false);
  const [aviso, setAviso] = useState('');
  const prioridades = useMemo(() => ordenarPrioridades(muestras.datos?.items ?? []), [muestras.datos]);
  const conectada = sesion.datos?.conexion.estado === 'conectada';
  const hayDatos = sesion.datos?.datos.hay_datos === true || sesion.datos?.datos.ultima_sync_ok_at != null;
  const kpis = hayDatos ? dashboard.datos?.kpis : undefined;
  const ocupado = actualizando || sync.estado?.en_curso === true;
  const lista = !sesion.cargando && !muestras.cargando && !dashboard.cargando;
  const sinMuestras = (muestras.datos?.items.length ?? 0) === 0;

  const actualizar = async (): Promise<void> => {
    if (ocupado) return;
    setActualizando(true);
    setAviso('');
    try {
      if (conectada && sync.puede) await sync.sincronizar();
      await Promise.all([sesion.refrescar(), muestras.refrescar(), dashboard.refrescar()]);
      setAviso(conectada ? 'Actualización solicitada. Tus datos aparecerán al terminar la sincronización.' : 'Actualización solicitada. Conecta tu cuenta para traer tus resultados.');
    } catch {
      setAviso('No pudimos actualizar. Revisa tu conexión e inténtalo de nuevo.');
    } finally {
      setActualizando(false);
    }
  };

  const metricas = [
    { etiqueta: 'Ventas generadas', valor: kpis ? formato.dinero(kpis.ventas_centavos) : '—', ruta: '/ventas?periodo=30d', nota: 'Ventas atribuidas a tu contenido' },
    { etiqueta: 'Comisión estimada', valor: kpis ? formato.dinero(kpis.comision_estimada_centavos) : '—', ruta: '/ventas?periodo=30d', nota: 'Estimación de TikTok Shop' },
    { etiqueta: 'Pedidos', valor: kpis ? formato.numero(kpis.pedidos) : '—', ruta: '/ventas?periodo=30d', nota: 'Pedidos de los últimos 30 días' },
  ];

  return (
    <Pantalla titulo="Inicio" lista={lista} className={css.pantalla}>
      <div className={css.resumen}>
        <header className={css.encabezado}>
          <div>
            <h1>Tu negocio, en orden</h1>
            <p>Tus resultados y próximos pasos, en un solo lugar.</p>
          </div>
          <Boton variante="secundario" tamano="lg" cargando={ocupado} alPulsar={() => void actualizar()}>{ocupado ? 'Actualizando…' : 'Actualizar'}</Boton>
        </header>

        <p className={css.aviso} role="status" aria-live="polite">{aviso}</p>

        {!sesion.cargando && !sesion.error && !conectada ? (
          <section className={css.conectar} aria-labelledby="inicio-conectar">
            <span className={css.iconoConexion}><Icono nombre="Store" tamano={24} /></span>
            <div className={css.conexionTexto}>
              <h2 id="inicio-conectar">Conecta tu cuenta de TikTok Shop</h2>
              <p>Consulta tus comisiones y organiza tus muestras.<br />Tus datos aparecerán después de la primera sincronización.</p>
            </div>
            <Boton variante="primario" tamano="lg" iconoFinal="ArrowRight" alPulsar={() => navegar('/ajustes/tiktok')}>Conectar cuenta</Boton>
          </section>
        ) : null}

        {sesion.error ? (
          <div className={css.error} role="alert">
            <Icono nombre="CircleAlert" tamano={20} />
            <p>No pudimos cargar tu cuenta. {sesion.error.mensaje}</p>
            <Boton tamano="sm" alPulsar={() => void actualizar()}>Reintentar</Boton>
          </div>
        ) : null}

        <section className={css.resultados} aria-labelledby="inicio-resultados">
          <header className={css.tituloSeccion}>
            <h2 id="inicio-resultados">Resultados</h2>
            <span>Últimos 30 días</span>
          </header>
          <div className={css.metricas} aria-busy={dashboard.cargando}>
            {metricas.map((metrica) => (
              <EnlaceRuta a={metrica.ruta} key={metrica.etiqueta} className={css.metrica}>
                <h3>{metrica.etiqueta}</h3>
                <strong className={css.valor}>{metrica.valor}</strong>
                <span>{kpis ? metrica.nota : dashboard.cargando ? 'Cargando resultados…' : dashboard.error ? 'No disponible' : 'Sin datos todavía'}</span>
              </EnlaceRuta>
            ))}
          </div>
          {dashboard.error ? <p className={css.errorSeccion} role="alert">No pudimos cargar tus resultados. Usa Actualizar para volver a intentarlo.</p> : null}
        </section>

        <div className={css.columnas}>
          <section className={css.panel} aria-labelledby="inicio-prioridades">
            <header className={css.cabeceraPanel}>
              <h2 id="inicio-prioridades">Tus prioridades</h2>
              <EnlaceRuta a="/muestras" className={css.enlace}>Ver muestras</EnlaceRuta>
            </header>
            {muestras.cargando ? (
              <div className={css.vacio} role="status"><Icono nombre="Package" tamano={24} /><p>Cargando tus muestras…</p></div>
            ) : muestras.error && !muestras.datos ? (
              <div className={css.vacio} role="alert"><Icono nombre="CircleAlert" tamano={24} /><h3>No pudimos cargar tus muestras</h3><p>{muestras.error.mensaje}</p><Boton alPulsar={() => void muestras.refrescar()}>Reintentar</Boton></div>
            ) : prioridades.length > 0 ? (
              <ul className={css.prioridades}>{prioridades.map((muestra) => <FilaPrioridad key={muestra.application_id} muestra={muestra} />)}</ul>
            ) : (
              <div className={css.vacio}>
                <span className={css.iconoVacio}><Icono nombre={sinMuestras ? 'Package' : 'CircleCheckBig'} tamano={24} /><i aria-hidden="true" /><i aria-hidden="true" /></span>
                <h3>{sinMuestras ? 'Todo empieza con tus muestras' : 'Tus muestras están al día'}</h3>
                <p>{sinMuestras ? 'Aquí verás qué productos necesitas grabar y cuándo publicarlos.' : 'No tienes muestras pendientes de publicar. Puedes revisar todas en Muestras.'}</p>
                <Boton variante="secundario" alPulsar={() => navegar('/muestras')}>Ir a muestras</Boton>
              </div>
            )}
          </section>

          <section className={css.panel} aria-labelledby="inicio-accesos">
            <header className={css.cabeceraPanel}><h2 id="inicio-accesos">Accesos rápidos</h2></header>
            <nav className={css.accesos} aria-label="Accesos rápidos">
              {ACCESOS.map((acceso) => (
                <EnlaceRuta a={acceso.ruta} key={acceso.ruta} className={css.acceso}>
                  <Icono nombre={acceso.icono} tamano={24} />
                  <span><strong>{acceso.titulo}</strong><span>{acceso.texto}</span></span>
                  <Icono nombre="ChevronRight" tamano={18} />
                </EnlaceRuta>
              ))}
            </nav>
          </section>
        </div>
        <footer className={css.pie}>CUTGC · Tu espacio para crear y crecer</footer>
      </div>
    </Pantalla>
  );
}
