import { useRef, useState, type ReactElement } from 'react';
import { Boton, CampoTexto, Chip, Modal, useToast } from '@/componentes';
import { ErrorHub, hub, invalidar, useConsulta, useSesion, useSync } from '@/datos';
import { abrirAutorizacionNube, origenNube } from '../../nube/entorno';
import { Aviso, CargandoGrupo, Dato, ErrorCarga, Fila, Grupo, Seccion } from './piezas';
import css from './ajustes.module.css';
import {
  ErrorIntegracionTikTok, guardarIntegracionTikTok, importarConexionAnteriorTikTok, sanearConexionAnteriorTikTok,
  type ImportacionAnteriorTikTok, type IntegracionTikTokGuardada,
} from './credencialesTikTokNube';

const mensaje = (e: unknown): string => e instanceof ErrorHub ? e.mensaje : e instanceof Error ? e.message : 'No pudimos completar la operación. Inténtalo de nuevo.';

export function ImportarConexionAnteriorTikTok(p: { alImportada: (resultado: ImportacionAnteriorTikTok) => void }): ReactElement {
  const archivo = useRef<HTMLInputElement>(null);
  const ocupado = useRef(false);
  const [importando, setImportando] = useState(false);
  const [error, setError] = useState('');
  const toast = useToast();
  const importar = async (elegido: File | undefined): Promise<void> => {
    if (!elegido || ocupado.current) return;
    setError('');
    if (elegido.size > 1024 * 1024) { setError('El archivo debe ser un JSON de conexión de hasta 1 MB.'); if (archivo.current) archivo.current.value = ''; return; }
    ocupado.current = true;
    setImportando(true);
    let datos: Record<string, unknown> | null = null;
    try {
      let contenido = await elegido.text();
      let original: unknown = JSON.parse(contenido.replace(/^\uFEFF/, ''));
      contenido = '';
      datos = sanearConexionAnteriorTikTok(original);
      original = null;
      if (archivo.current) archivo.current.value = '';
      const resultado = await importarConexionAnteriorTikTok(datos);
      invalidar();
      if (resultado.verificacion === 'ok') toast.mostrar({ texto: resultado.sync_iniciada ? 'Recuperamos tu conexión y empezamos a sincronizar.' : 'Recuperamos tu conexión anterior.', tono: 'ok' });
      p.alImportada(resultado);
    } catch (e) { setError(e instanceof SyntaxError ? 'El archivo no contiene un JSON válido.' : mensaje(e)); }
    finally {
      if (datos) for (const campo of Object.keys(datos)) delete datos[campo];
      if (archivo.current) archivo.current.value = '';
      ocupado.current = false;
      setImportando(false);
    }
  };
  return <div className={css.pila}>
    <input ref={archivo} type="file" accept=".json,application/json" aria-label="Archivo de conexión anterior de TikTok Shop" hidden onChange={(e) => void importar(e.target.files?.[0])} />
    <div className={css.acciones}><Boton variante="secundario" icono="Download" cargando={importando} alPulsar={() => archivo.current?.click()}>Importar conexión anterior</Boton></div>
    <p className={css.filaDesc}>Elige el archivo JSON de tu panel anterior. Solo se importará la conexión con TikTok Shop; el archivo original se conserva.</p>
    {error ? <Aviso tono="critico" vivo>{error}</Aviso> : null}
  </div>;
}

/** Configuración de la app, una sola vez. Las dos claves empiezan vacías. */
export function FormularioIntegracionTikTokNube(p: { alGuardada: (datos: IntegracionTikTokGuardada) => void }): ReactElement {
  const [appKey, setAppKey] = useState('');
  const secreto = useRef('');
  const [vueltaSecreto, setVueltaSecreto] = useState(0);
  const [guardando, setGuardando] = useState(false);
  const [errorKey, setErrorKey] = useState('');
  const [errorSecret, setErrorSecret] = useState('');
  const [error, setError] = useState('');
  const enviando = useRef(false);
  const callback = `${origenNube()}/oauth/shop`;

  const guardar = async (): Promise<void> => {
    if (enviando.current) return;
    const key = appKey.trim();
    setErrorKey(!key ? 'Pega la App key de tu app de Partner Center.' : '');
    setErrorSecret(!secreto.current.trim() ? 'Pega el App secret de esa misma app.' : '');
    setError('');
    if (!key || !secreto.current.trim()) return;
    const credenciales = { app_key: key, app_secret: secreto.current.trim() };
    secreto.current = '';
    setVueltaSecreto((n) => n + 1);
    enviando.current = true;
    setGuardando(true);
    try {
      const datos = await guardarIntegracionTikTok(credenciales);
      invalidar('credenciales', 'sesion');
      p.alGuardada(datos);
    } catch (e) {
      if (e instanceof ErrorIntegracionTikTok && e.codigo === 'app_key_invalida') setErrorKey(e.message);
      else if (e instanceof ErrorIntegracionTikTok && e.codigo === 'app_secret_invalido') setErrorSecret(e.message);
      else setError(mensaje(e));
    } finally {
      credenciales.app_secret = '';
      secreto.current = '';
      setVueltaSecreto((n) => n + 1);
      enviando.current = false;
      setGuardando(false);
    }
  };

  return <form className={css.pila} aria-label="Integración de la app de TikTok Shop" onSubmit={(e) => { e.preventDefault(); void guardar(); }}>
    <p className={css.parrafo}>Configura tu app una sola vez. Copia las dos claves de la misma app en Partner Center → App &amp; Service → App credentials.</p>
    <CampoTexto etiqueta="App key" valor={appKey} alCambiar={setAppKey} ayuda="Identifica tu app de TikTok Shop." error={errorKey || null} monoespaciado maximo={64} alEnter={() => void guardar()} />
    <CampoTexto key={vueltaSecreto} etiqueta="App secret" tipo="password" valor="" alCambiar={(v) => { secreto.current = v; }} ayuda="Se guarda cifrado en Corte y nunca vuelve a mostrarse. No es tu contraseña de TikTok." error={errorSecret || null} alEnter={() => void guardar()} />
    <p className={css.filaDesc}>En esa app, registra esta URL de regreso (Redirect URL):<br /><code className={css.mono}>{callback}</code></p>
    {error ? <Aviso tono="critico" vivo>{error}</Aviso> : null}
    <div className={css.acciones}><Boton variante="primario" cargando={guardando} alPulsar={() => void guardar()}>Guardar integración</Boton></div>
  </form>;
}

/** Conexión web: sin rutas del disco ni control del navegador del servidor. */
export function ConectarTikTokNube(p: {
  alConectada?: () => void;
  alImportacion?: (resultado: ImportacionAnteriorTikTok) => void;
  soloIntegracion?: boolean;
}): ReactElement {
  const cred = useConsulta('credenciales', {});
  const sesion = useSesion();
  const [integracionGuardada, setIntegracionGuardada] = useState<IntegracionTikTokGuardada | null>(null);
  const [importacionPendiente, setImportacionPendiente] = useState(false);
  const edicion = useRef<HTMLDetailsElement>(null);
  const [enlace, setEnlace] = useState('');
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState('');
  const [confirmarCuenta, setConfirmarCuenta] = useState(false);
  const [cambioCuenta, setCambioCuenta] = useState(false);
  const appKeyActual = integracionGuardada?.app_key ?? cred.datos?.app_key ?? '';
  const configurada = (integracionGuardada?.app_secret_configurado ?? cred.datos?.app_secret_configurado ?? false) && appKeyActual !== '';

  const abrir = async (): Promise<void> => {
    setGuardando(true); setError(''); setImportacionPendiente(false);
    try {
      if (!configurada) return;
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
  const alGuardada = (datos: IntegracionTikTokGuardada): void => {
    setIntegracionGuardada(datos);
    setImportacionPendiente(false);
    setError('');
    if (edicion.current) edicion.current.open = false;
  };
  const alImportada = (resultado: ImportacionAnteriorTikTok): void => {
    setIntegracionGuardada(null);
    setImportacionPendiente(resultado.verificacion === 'fallo');
    p.alImportacion?.(resultado);
    void cred.refrescar();
    if (resultado.verificacion === 'ok') p.alConectada?.();
  };
  return <div className={css.pila}>
    {importacionPendiente && !p.alImportacion ? <Aviso tono="atencion" vivo>La configuración se importó, pero TikTok no pudo confirmar la conexión. Usa Continuar en TikTok Shop para volver a autorizarla.</Aviso> : null}
    {confirmarCuenta ? <>
      <p className={css.parrafo}>Conectaste {sesion.datos?.cuenta ? `@${sesion.datos.cuenta.username}` : 'tu cuenta'}. Confirma para comenzar a sincronizar tus datos.</p>
      <Boton variante="primario" cargando={guardando} alPulsar={() => void confirmar()}>Confirmar cuenta y sincronizar</Boton>
    </> : <>
      {configurada ? <>
        <Dato etiqueta="App key configurada" valor={appKeyActual} mono />
        {!p.soloIntegracion ? <><p className={css.parrafo}>Tu app está configurada. Continúa para autorizar tu cuenta en TikTok Shop y regresar a Corte.</p><div className={css.acciones}><Boton variante="primario" iconoFinal="ArrowRight" cargando={guardando} alPulsar={() => void abrir()}>Continuar en TikTok Shop</Boton></div></> : null}
        <details ref={edicion} className={css.tecnicos}>
          <summary className={css.tecnicosResumen}>Cambiar integración</summary>
          <div className={css.tecnicosCuerpo}><FormularioIntegracionTikTokNube alGuardada={alGuardada} /><ImportarConexionAnteriorTikTok alImportada={alImportada} /></div>
        </details>
      </> : <><ImportarConexionAnteriorTikTok alImportada={alImportada} /><FormularioIntegracionTikTokNube alGuardada={alGuardada} /></>}
      {!p.soloIntegracion && configurada ? <details className={css.tecnicos}>
        <summary className={css.tecnicosResumen}>Si TikTok no te devuelve a Corte</summary>
        <div className={css.tecnicosCuerpo}>
          <p className={css.parrafo}>Pega la dirección completa de la página de regreso. Corte verificará que corresponda a esta autorización.</p>
          <CampoTexto etiqueta="Dirección de regreso" valor={enlace} alCambiar={setEnlace} alEnter={() => void canjear()} />
          <Boton variante="secundario" cargando={guardando} alPulsar={() => void canjear()}>Completar conexión</Boton>
        </div>
      </details> : null}
    </>}
    {error ? <Aviso tono="critico" vivo>{error}</Aviso> : null}
    <Modal abierto={cambioCuenta} titulo="¿Cambiar la cuenta de TikTok Shop?" alCerrar={() => setCambioCuenta(false)} pie={<><Boton variante="fantasma" alPulsar={() => setCambioCuenta(false)}>Cancelar</Boton><Boton variante="peligro" cargando={guardando} alPulsar={() => void canjear(true)}>Cambiar cuenta</Boton></>}>
      <p>La nueva autorización pertenece a otra cuenta. Al continuar se borrarán los datos de la cuenta anterior para evitar mezclarlos.</p>
    </Modal>
  </div>;
}

export function SeccionTikTokNube(): ReactElement {
  const sesion = useSesion();
  const cred = useConsulta('credenciales', {});
  const sync = useSync();
  const toast = useToast();
  const [desconectar, setDesconectar] = useState(false);
  const [trabajando, setTrabajando] = useState(false);
  const [renovando, setRenovando] = useState(false);
  const renovacionEnCurso = useRef(false);
  const [importacionPendiente, setImportacionPendiente] = useState(false);
  const [requiereAutorizacion, setRequiereAutorizacion] = useState(false);
  const [avisoRenovacion, setAvisoRenovacion] = useState<{ texto: string; tono: 'atencion' | 'critico' | 'info' } | null>(null);
  const autorizada = sesion.datos?.conexion.estado === 'conectada';
  const conectada = autorizada && !importacionPendiente && !requiereAutorizacion;
  const hayTokens = !!cred.datos?.tokens_configurados;
  const alImportacion = (resultado: ImportacionAnteriorTikTok): void => {
    setImportacionPendiente(resultado.verificacion === 'fallo');
    setAvisoRenovacion(null);
    if (resultado.verificacion === 'fallo') toast.mostrar({ texto: 'TikTok no pudo confirmar la conexión importada. Revisa la conexión antes de continuar.', tono: 'info' });
  };
  const renovar = async (): Promise<void> => {
    if (renovacionEnCurso.current) return;
    renovacionEnCurso.current = true;
    setRenovando(true);
    setAvisoRenovacion(null);
    try {
      const resultado = await hub.authRefrescar();
      const conexion = resultado.conexion;
      const reautorizar = conexion.estado === 'reautorizar' || conexion.estado === 'sin_autorizar' || conexion.scopes_faltantes.length > 0;
      setRequiereAutorizacion(reautorizar);
      if (reautorizar) {
        const texto = 'TikTok solicita que vuelvas a autorizar la cuenta. Usa Continuar en TikTok Shop; las claves guardadas se conservan.';
        setAvisoRenovacion({ texto, tono: 'atencion' });
        toast.mostrar({ texto: 'TikTok solicita una nueva autorización.', tono: 'info' });
      } else if (conexion.estado !== 'conectada' || conexion.aviso) {
        const texto = conexion.aviso ?? 'No pudimos renovar la conexión. Revisa su estado e inténtalo de nuevo.';
        setAvisoRenovacion({ texto, tono: 'atencion' });
        toast.mostrar({ texto: 'La renovación requiere atención. Revisa el aviso de la conexión.', tono: 'info' });
      } else {
        setImportacionPendiente(false);
        setAvisoRenovacion({ texto: 'Sincroniza ahora para comprobar el perfil y actualizar tus datos.', tono: 'info' });
        toast.mostrar({ texto: 'Se actualizó la conexión.', tono: 'ok' });
      }
      await Promise.all([sesion.refrescar(), cred.refrescar()]);
    } catch (e) {
      const texto = mensaje(e);
      if (e instanceof ErrorHub && e.codigo === 'reautorizar') setRequiereAutorizacion(true);
      setAvisoRenovacion({ texto, tono: 'critico' });
      toast.mostrar({ texto, tono: 'error' });
    } finally {
      renovacionEnCurso.current = false;
      setRenovando(false);
    }
  };
  const borrar = async (): Promise<void> => {
    setTrabajando(true);
    try { await hub.authDesconectar({ borrar_datos: false }); setDesconectar(false); toast.mostrar({ texto: 'Desconectamos la cuenta. Tus datos guardados se conservan.', tono: 'ok' }); }
    catch (e) { toast.mostrar({ texto: mensaje(e), tono: 'error' }); }
    finally { setTrabajando(false); }
  };
  return <Seccion titulo="TikTok Shop" id="tiktok" descripcion="Conecta tu cuenta para traer tus muestras, ventas y comisiones.">
    {sesion.cargando && !sesion.datos ? <CargandoGrupo filas={2} /> : !sesion.datos ? <ErrorCarga error={sesion.error} alReintentar={() => void sesion.refrescar()} /> : <>
      <Grupo titulo="Tu cuenta">
        <Fila etiqueta={sesion.datos.cuenta ? `@${sesion.datos.cuenta.username}` : 'Cuenta de TikTok Shop'} descripcion={importacionPendiente ? 'La conexión se importó, pero TikTok aún no confirmó el acceso.' : sesion.datos.conexion.aviso ?? (conectada ? 'La cuenta está autorizada para sincronizar.' : 'Autoriza tu cuenta para comenzar.')}><Chip tono={conectada ? 'ok' : 'neutro'}>{importacionPendiente ? 'Pendiente de verificar' : requiereAutorizacion ? 'Vuelve a autorizar' : conectada ? 'Conectada' : 'Sin conectar'}</Chip></Fila>
        <Dato etiqueta="Región" valor={sesion.datos.cuenta?.region ?? 'México'} />
      </Grupo>
      {importacionPendiente ? <Aviso tono="atencion" vivo>TikTok no pudo confirmar la conexión importada. Prueba Renovar conexión o continúa en TikTok Shop para volver a autorizarla.</Aviso> : null}
      {avisoRenovacion ? <Aviso tono={avisoRenovacion.tono} vivo>{avisoRenovacion.texto}</Aviso> : null}
      <div className={css.acciones}>
        {autorizada && !requiereAutorizacion ? <Boton variante="secundario" icono="RefreshCw" deshabilitado={!sync.puede || !!sync.estado?.en_curso || renovando} alPulsar={() => void sync.sincronizar()}>Sincronizar ahora</Boton> : null}
        {hayTokens ? <Boton variante="secundario" icono="RotateCcw" cargando={renovando} alPulsar={() => void renovar()}>Renovar conexión</Boton> : null}
      </div>
      <ConectarTikTokNube soloIntegracion={conectada} alImportacion={alImportacion} alConectada={() => { setImportacionPendiente(false); setRequiereAutorizacion(false); setAvisoRenovacion(null); }} />
      {autorizada || hayTokens ? <div className={css.acciones}><Boton variante="peligro" alPulsar={() => setDesconectar(true)}>Desconectar cuenta</Boton></div> : null}
      <Modal abierto={desconectar} titulo="¿Desconectar tu cuenta?" alCerrar={() => setDesconectar(false)} pie={<><Boton variante="fantasma" alPulsar={() => setDesconectar(false)}>Cancelar</Boton><Boton variante="peligro" cargando={trabajando} alPulsar={() => void borrar()}>Desconectar</Boton></>}><p>La autorización se eliminará del servidor. Tus datos y tu plan se conservarán, pero dejarán de actualizarse hasta que vuelvas a conectar.</p></Modal>
    </>}
  </Seccion>;
}
