import { useState, type ReactElement } from 'react';
import { Boton, CampoTexto, Chip, Modal, useToast } from '@/componentes';
import { ErrorHub, hub, useConsulta, useSesion, useSync } from '@/datos';
import { abrirAutorizacionNube } from '../../nube/entorno';
import { Aviso, CargandoGrupo, Dato, ErrorCarga, Fila, Grupo, Seccion } from './piezas';
import css from './ajustes.module.css';

const mensaje = (e: unknown): string => e instanceof ErrorHub ? e.mensaje : e instanceof Error ? e.message : 'No pudimos completar la operación. Inténtalo de nuevo.';

/** Conexión web: sin rutas del disco ni control del navegador del servidor. */
export function ConectarTikTokNube(p: { alConectada?: () => void }): ReactElement {
  const cred = useConsulta('credenciales', {});
  const sesion = useSesion();
  const [clave, setClave] = useState('');
  const [enlace, setEnlace] = useState('');
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState('');
  const [confirmarCuenta, setConfirmarCuenta] = useState(false);
  const [cambioCuenta, setCambioCuenta] = useState(false);
  const configurada = cred.datos?.app_secret_configurado ?? false;

  const abrir = async (): Promise<void> => {
    setGuardando(true); setError('');
    try {
      if (!configurada) {
        if (!clave.trim()) { setError('Escribe la clave secreta de tu app de Partner Center.'); return; }
        await hub.guardarAppSecret(clave.trim());
        setClave('');
      }
      const link = await hub.authLink(false);
      abrirAutorizacionNube(link.url);
    } catch (e) { setError(mensaje(e)); }
    finally { setGuardando(false); }
  };
  const canjear = async (confirmarCambio = false): Promise<void> => {
    if (!enlace.trim()) { setError('Pega la dirección completa de regreso de TikTok.'); return; }
    setGuardando(true); setError('');
    try {
      const r = await hub.authCanjear({ url_o_codigo: enlace.trim(), ...(confirmarCambio ? { confirmar_cambio_cuenta: true } : {}) });
      setCambioCuenta(false);
      setEnlace('');
      if (r.confirmar_cuenta) setConfirmarCuenta(true);
      else { await hub.sincronizar(); p.alConectada?.(); }
    } catch (e) {
      if (e instanceof ErrorHub && e.codigo === 'cuenta_distinta') setCambioCuenta(true);
      else setError(mensaje(e));
    } finally { setGuardando(false); }
  };
  const confirmar = async (): Promise<void> => {
    setGuardando(true); setError('');
    try { await hub.sincronizar('completa'); setConfirmarCuenta(false); p.alConectada?.(); }
    catch (e) { setError(mensaje(e)); }
    finally { setGuardando(false); }
  };

  if (cred.cargando && !cred.datos) return <CargandoGrupo filas={2} />;
  if (!cred.datos) return <ErrorCarga error={cred.error} alReintentar={() => void cred.refrescar()} />;
  return <div className={css.pila}>
    {confirmarCuenta ? <>
      <p className={css.parrafo}>Conectaste {sesion.datos?.cuenta ? `@${sesion.datos.cuenta.username}` : 'tu cuenta'}. Confirma para comenzar a sincronizar tus datos.</p>
      <Boton variante="primario" cargando={guardando} alPulsar={() => void confirmar()}>Confirmar cuenta y sincronizar</Boton>
    </> : <>
      <p className={css.parrafo}>Autoriza el acceso desde TikTok Shop. Al terminar, regresarás a Corte.</p>
      {!configurada ? <CampoTexto etiqueta="Clave secreta de la app (App secret)" tipo="password" valor={clave} alCambiar={setClave} ayuda="Cópiala de tu app de Partner Center. Se guarda cifrada en el servidor y nunca vuelve a mostrarse." alEnter={() => void abrir()} /> : null}
      <Boton variante="primario" iconoFinal="ArrowRight" cargando={guardando} alPulsar={() => void abrir()}>Continuar en TikTok Shop</Boton>
      <details className={css.tecnicos}>
        <summary className={css.tecnicosResumen}>Si TikTok no te devuelve a Corte</summary>
        <div className={css.tecnicosCuerpo}>
          <p className={css.parrafo}>Pega la dirección completa de la página de regreso. Corte verificará que corresponda a esta autorización.</p>
          <CampoTexto etiqueta="Dirección de regreso" valor={enlace} alCambiar={setEnlace} alEnter={() => void canjear()} />
          <Boton variante="secundario" cargando={guardando} alPulsar={() => void canjear()}>Completar conexión</Boton>
        </div>
      </details>
    </>}
    {error ? <Aviso tono="critico" vivo>{error}</Aviso> : null}
    <Modal abierto={cambioCuenta} titulo="¿Cambiar la cuenta de TikTok Shop?" alCerrar={() => setCambioCuenta(false)} pie={<><Boton variante="fantasma" alPulsar={() => setCambioCuenta(false)}>Cancelar</Boton><Boton variante="peligro" cargando={guardando} alPulsar={() => void canjear(true)}>Cambiar cuenta</Boton></>}>
      <p>La nueva autorización pertenece a otra cuenta. Al continuar se borrarán los datos de la cuenta anterior para evitar mezclarlos.</p>
    </Modal>
  </div>;
}

export function SeccionTikTokNube(): ReactElement {
  const sesion = useSesion();
  const sync = useSync();
  const toast = useToast();
  const [desconectar, setDesconectar] = useState(false);
  const [trabajando, setTrabajando] = useState(false);
  const conectada = sesion.datos?.conexion.estado === 'conectada';
  const borrar = async (): Promise<void> => {
    setTrabajando(true);
    try { await hub.authDesconectar({ borrar_datos: false }); setDesconectar(false); toast.mostrar({ texto: 'Desconectamos la cuenta. Tus datos guardados se conservan.', tono: 'ok' }); }
    catch (e) { toast.mostrar({ texto: mensaje(e), tono: 'error' }); }
    finally { setTrabajando(false); }
  };
  return <Seccion titulo="TikTok Shop" id="tiktok" descripcion="Conecta tu cuenta para traer tus muestras, ventas y comisiones.">
    {sesion.cargando && !sesion.datos ? <CargandoGrupo filas={2} /> : !sesion.datos ? <ErrorCarga error={sesion.error} alReintentar={() => void sesion.refrescar()} /> : <>
      <Grupo titulo="Tu cuenta">
        <Fila etiqueta={sesion.datos.cuenta ? `@${sesion.datos.cuenta.username}` : 'Cuenta de TikTok Shop'} descripcion={sesion.datos.conexion.aviso ?? (conectada ? 'La cuenta está autorizada para sincronizar.' : 'Autoriza tu cuenta para comenzar.')}><Chip tono={conectada ? 'ok' : 'neutro'}>{conectada ? 'Conectada' : 'Sin conectar'}</Chip></Fila>
        <Dato etiqueta="Región" valor={sesion.datos.cuenta?.region ?? 'México'} />
      </Grupo>
      {conectada ? <div className={css.acciones}><Boton variante="secundario" icono="RefreshCw" deshabilitado={!sync.puede || !!sync.estado?.en_curso} alPulsar={() => void sync.sincronizar()}>Sincronizar ahora</Boton><Boton variante="peligro" alPulsar={() => setDesconectar(true)}>Desconectar cuenta</Boton></div> : <ConectarTikTokNube />}
      <Modal abierto={desconectar} titulo="¿Desconectar tu cuenta?" alCerrar={() => setDesconectar(false)} pie={<><Boton variante="fantasma" alPulsar={() => setDesconectar(false)}>Cancelar</Boton><Boton variante="peligro" cargando={trabajando} alPulsar={() => void borrar()}>Desconectar</Boton></>}><p>La autorización se eliminará del servidor. Tus datos y tu plan se conservarán, pero dejarán de actualizarse hasta que vuelvas a conectar.</p></Modal>
    </>}
  </Seccion>;
}
