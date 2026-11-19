import { useEffect, useState, type FormEvent, type ReactElement, type ReactNode } from 'react';
import { infoPlataforma } from '@/plataforma';
import { Logo } from '../raiz/Logo';
import { fijarClienteNativo, fijarModoNube } from './entorno';
import { leerSesionNativa, type SesionNativa } from './clienteNativo';
import { AccesoClienteNativo } from './AccesoClienteNativo';
import { clienteFirebase, errorGoogle, type ConfigFirebase } from './firebase';
import css from './AccesoNube.module.css';

type Acceso = 'comprobando' | 'local' | 'autorizado' | 'entrar' | 'error';
type ConfigAcceso = { auth_provider: 'firebase'; firebase: ConfigFirebase } | { auth_provider: 'password' };

function configAcceso(v: unknown): ConfigAcceso | null {
  if (v === null || typeof v !== 'object' || !('auth_provider' in v)) return null;
  if (v.auth_provider === 'password') return { auth_provider: 'password' };
  if (v.auth_provider !== 'firebase' || !('firebase' in v) || v.firebase === null || typeof v.firebase !== 'object') return null;
  const f = v.firebase;
  if (!('apiKey' in f) || typeof f.apiKey !== 'string' || !f.apiKey || !('authDomain' in f) || typeof f.authDomain !== 'string' || !f.authDomain || !('projectId' in f) || typeof f.projectId !== 'string' || !f.projectId || !('appId' in f) || typeof f.appId !== 'string' || !f.appId) return null;
  return { auth_provider: 'firebase', firebase: { apiKey: f.apiKey, authDomain: f.authDomain, projectId: f.projectId, appId: f.appId, ...('storageBucket' in f && typeof f.storageBucket === 'string' ? { storageBucket: f.storageBucket } : {}) } };
}

/** El acceso al servidor se verifica antes de solicitar cualquier dato de la cuenta. */
export function AccesoNube(p: { children: ReactNode }): ReactElement {
  const [acceso, setAcceso] = useState<Acceso>('comprobando');
  const [intento, setIntento] = useState(0);
  const [clave, setClave] = useState('');
  const [error, setError] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [config, setConfig] = useState<ConfigAcceso | null>(null);
  const [puedeRedirigir, setPuedeRedirigir] = useState(false);
  const [nativa, setNativa] = useState<SesionNativa | null>(null);

  useEffect(() => {
    if (import.meta.env.DEV && import.meta.env.VITE_DEMO === '1') {
      setAcceso('local');
      return undefined;
    }
    let vivo = true;
    const c = new AbortController();
    const tiempo = window.setTimeout(() => c.abort(), 15000);
    void (async () => {
      try {
        if (infoPlataforma().plataforma !== 'navegador') {
          const s = await leerSesionNativa(c.signal);
          if (s) {
            fijarClienteNativo(true); fijarModoNube(true);
            if (vivo) setNativa(s);
            return;
          }
          fijarModoNube(false);
          if (vivo) setAcceso('local');
          return;
        }
        const r = await fetch('/api/cloud/session', { credentials: 'same-origin', cache: 'no-store', signal: c.signal, headers: { Accept: 'application/json' } });
        const local = ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname);
        if (r.status === 404 && local) {
          fijarModoNube(false);
          if (vivo) setAcceso('local');
          return;
        }
        if (!r.ok) throw new Error('sesion');
        const datos: unknown = await r.json();
        if (datos === null || typeof datos !== 'object' || !('cloud' in datos) || datos.cloud !== true || !('authenticated' in datos) || typeof datos.authenticated !== 'boolean') throw new Error('sesion');
        fijarModoNube(true);
        if (datos.authenticated) { if (vivo) setAcceso('autorizado'); return; }
        const conf = await fetch('/api/cloud/config', { credentials: 'same-origin', cache: 'no-store', signal: c.signal });
        if (!conf.ok) throw new Error('config');
        const configuracion = configAcceso(await conf.json());
        if (!configuracion) throw new Error('config');
        if (vivo) { setConfig(configuracion); setAcceso('entrar'); }
        if (configuracion.auth_provider === 'firebase') {
          try {
            const { auth, sdk } = await clienteFirebase(configuracion.firebase);
            const regreso = await sdk.getRedirectResult(auth);
            if (regreso && vivo) {
              setEnviando(true);
              try { await verificarGoogle(await regreso.user.getIdToken(true)); if (vivo) setAcceso('autorizado'); }
              catch (e) { if (vivo) setError(e instanceof Error ? e.message : 'No pudimos verificar tu acceso.'); }
              finally { if (vivo) setEnviando(false); }
            }
          } catch (e) { if (vivo) setError(errorGoogle(e).mensaje); }
        }
      } catch (e) {
        if (vivo) {
          if (e instanceof Error && e.message === 'config') setError('Falta completar la configuración del acceso en el servidor.');
          else setError('El servidor no respondió. Revisa tu conexión y vuelve a intentarlo.');
          setAcceso('error');
        }
      } finally { window.clearTimeout(tiempo); }
    })();
    return () => { vivo = false; window.clearTimeout(tiempo); c.abort(); };
  }, [intento]);

  useEffect(() => {
    const cerrar = (): void => {
      // Descarta toda la memoria de la aplicación al expirar una sesión.
      window.location.reload();
    };
    window.addEventListener('corte:sesion-cerrada', cerrar);
    return () => window.removeEventListener('corte:sesion-cerrada', cerrar);
  }, []);

  const verificarGoogle = async (idToken: string): Promise<void> => {
    const r = await fetch('/api/cloud/login', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-CH-Hub': '1' },
      body: JSON.stringify({ id_token: idToken }),
    });
    if (!r.ok) throw new Error(r.status === 403 ? 'Esta cuenta de Google no tiene acceso a este espacio de CUTGC.' : r.status === 429 ? 'Demasiados intentos. Espera unos minutos e inténtalo de nuevo.' : 'No pudimos verificar tu acceso. Vuelve a entrar con Google.');
    const datos: unknown = await r.json();
    if (datos === null || typeof datos !== 'object' || !('authenticated' in datos) || datos.authenticated !== true) throw new Error('El servidor no confirmó el acceso. Inténtalo de nuevo.');
  };

  const entrarGoogle = async (redirigir = false): Promise<void> => {
    if (!config || config.auth_provider !== 'firebase' || enviando) return;
    setEnviando(true); setError(''); setPuedeRedirigir(false);
    try {
      const { auth, sdk } = await clienteFirebase(config.firebase);
      const provider = new sdk.GoogleAuthProvider();
      provider.setCustomParameters({ prompt: 'select_account' });
      if (redirigir) { await sdk.signInWithRedirect(auth, provider); return; }
      const resultado = await sdk.signInWithPopup(auth, provider);
      try { await verificarGoogle(await resultado.user.getIdToken(true)); setAcceso('autorizado'); }
      catch (e) { await sdk.signOut(auth); setError(e instanceof Error ? e.message : 'No pudimos verificar tu acceso.'); }
    } catch (e) { const detalle = errorGoogle(e); setError(detalle.mensaje); setPuedeRedirigir(detalle.redirigir); }
    finally { setEnviando(false); }
  };

  const entrar = async (e: FormEvent<HTMLFormElement>): Promise<void> => {
    e.preventDefault();
    if (enviando) return;
    if (!clave) { setError('Escribe tu contraseña para continuar.'); return; }
    setEnviando(true);
    setError('');
    try {
      const r = await fetch('/api/cloud/login', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-CH-Hub': '1' },
        body: JSON.stringify({ password: clave }),
      });
      if (!r.ok) {
        setError(r.status === 429 ? 'Demasiados intentos. Espera unos minutos antes de volver a entrar.' : r.status === 401 ? 'La contraseña no es correcta. Inténtalo de nuevo.' : 'No pudimos iniciar sesión. Inténtalo de nuevo.');
        return;
      }
      const datos: unknown = await r.json();
      if (datos === null || typeof datos !== 'object' || !('authenticated' in datos) || datos.authenticated !== true) throw new Error('sesion');
      setClave('');
      setAcceso('autorizado');
    } catch { setError('No pudimos conectar con CUTGC. Revisa tu conexión e inténtalo de nuevo.'); }
    finally { setEnviando(false); }
  };

  if (nativa) return <AccesoClienteNativo inicial={nativa}>{p.children}</AccesoClienteNativo>;
  if (acceso === 'local' || acceso === 'autorizado') return <>{p.children}</>;
  return (
    <main className={css.fondo}>
      <div className={css.marca} aria-label="CUTGC">
        <Logo tamano={32} />
        <span>CUTGC</span>
      </div>
      <section className={css.panel} aria-labelledby="acceso-titulo" aria-busy={acceso === 'comprobando' || enviando}>
        {acceso === 'comprobando' ? <><h1 id="acceso-titulo">Abriendo tu espacio</h1><p role="status">Comprobando el acceso a CUTGC…</p><span className={css.carga} aria-hidden="true" /></> : acceso === 'error' ? <><h1 id="acceso-titulo">No pudimos conectar</h1><p role="alert">{error || 'El servidor no respondió. Revisa tu conexión y vuelve a intentarlo.'}</p><button className={css.principal} onClick={() => { setError(''); setAcceso('comprobando'); setIntento((i) => i + 1); }}>Volver a intentar</button></> : <>
          <h1 id="acceso-titulo">Bienvenido a tu espacio</h1>
          <p>Entra para consultar tus resultados y organizar tus próximas publicaciones.</p>
          {config?.auth_provider === 'firebase' ? <div className={css.formulario}>
            <button className={css.google} type="button" onClick={() => void entrarGoogle()} disabled={enviando}>
              <svg width="20" height="20" viewBox="0 0 48 48" aria-hidden="true"><path fill="#4285F4" d="M43.6 24.5c0-1.5-.1-2.9-.4-4.3H24v8.2h11c-.5 2.6-1.9 4.7-4.1 6.2v5.1h6.6c3.9-3.6 6.1-8.9 6.1-15.2Z"/><path fill="#34A853" d="M24 44c5.5 0 10.1-1.8 13.5-4.9l-6.6-5.1c-1.8 1.2-4.1 1.9-6.9 1.9-5.3 0-9.8-3.6-11.4-8.4H5.8v5.3C9.2 39.5 16.1 44 24 44Z"/><path fill="#FBBC05" d="M12.6 27.5a12 12 0 0 1 0-7V15.2H5.8a20 20 0 0 0 0 17.6l6.8-5.3Z"/><path fill="#EA4335" d="M24 12.1c3 0 5.6 1 7.7 3l5.8-5.8A19.3 19.3 0 0 0 24 4C16.1 4 9.2 8.5 5.8 15.2l6.8 5.3c1.6-4.8 6.1-8.4 11.4-8.4Z"/></svg>
              {enviando ? 'Verificando acceso…' : 'Continuar con Google'}
            </button>
            <p className={css.notaGoogle}>Usa la cuenta de Google autorizada para este espacio.</p>
            {puedeRedirigir ? <button className={css.enlace} onClick={() => void entrarGoogle(true)} disabled={enviando}>Continuar en esta pestaña</button> : null}
            {error ? <p className={css.error} role="alert">{error}</p> : null}
          </div> : <form onSubmit={(e) => void entrar(e)} className={css.formulario}>
            <label htmlFor="clave-acceso">Contraseña de acceso</label>
            <input id="clave-acceso" name="password" type="password" autoComplete="current-password" value={clave} onChange={(e) => setClave(e.target.value)} autoFocus required aria-invalid={error ? true : undefined} aria-describedby={error ? 'error-acceso' : undefined} disabled={enviando} />
            {error ? <p id="error-acceso" className={css.error} role="alert">{error}</p> : null}
            <button className={css.principal} type="submit" disabled={enviando}>{enviando ? 'Entrando…' : 'Entrar a CUTGC'}<span aria-hidden="true">→</span></button>
          </form>}
        </>}
      </section>
      <p className={css.pie}>Tus resultados y próximos pasos, en un solo lugar.</p>
    </main>
  );
}
