import { useEffect, useState, type ReactElement, type ReactNode } from 'react';
import { accionNativa, leerSesionNativa, type SesionNativa } from './clienteNativo';
import css from './AccesoNube.module.css';
import nativo from './AccesoClienteNativo.module.css';

export function AccesoClienteNativo(p: { inicial: SesionNativa; children: ReactNode }): ReactElement {
  const [sesion, setSesion] = useState(p.inicial);
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let vivo = true;
    let activo = false;
    const actualizar = async (): Promise<void> => {
      if (activo) return;
      activo = true;
      try { const s = await leerSesionNativa(); if (vivo && s) { setSesion(s); setError(''); } }
      catch { /* Un fallo temporal conserva el estado local y el código pendiente. */ }
      finally { activo = false; }
    };
    void actualizar();
    const alVolver = (): void => { if (!document.hidden) void actualizar(); };
    const t = window.setInterval(() => void actualizar(), sesion.authenticated && !sesion.migration_pending ? 30_000 : 2500);
    document.addEventListener('visibilitychange', alVolver);
    window.addEventListener('focus', alVolver);
    window.addEventListener('creatorhub-conexion', alVolver);
    return () => { vivo = false; window.clearInterval(t); document.removeEventListener('visibilitychange', alVolver); window.removeEventListener('focus', alVolver); window.removeEventListener('creatorhub-conexion', alVolver); };
  }, [sesion.authenticated, sesion.migration_pending, revision]);

  const actuar = async (accion: 'connect' | 'migrate', datos?: unknown): Promise<void> => {
    setOcupado(true); setError('');
    try {
      await accionNativa(accion, datos);
      const s = await leerSesionNativa();
      if (s) setSesion(s);
      setRevision(v => v + 1);
    } catch (e) { setError(e instanceof Error ? e.message : 'No pudimos completar la conexión.'); }
    finally { setOcupado(false); }
  };
  if (sesion.authenticated && !sesion.migration_pending) return <>{p.children}</>;
  const migrar = sesion.authenticated && sesion.migration_pending;
  return <main className={css.fondo}>
    <div className={css.marca}>Corte <span className={nativo.plataforma}>{sesion.platform === 'windows' ? 'Windows' : 'Android'}</span></div>
    <section className={css.panel} aria-labelledby="acceso-nativo" aria-busy={ocupado}>
      <h1 id="acceso-nativo">{migrar ? 'Recupera tu organización' : 'Tu espacio, conectado'}</h1>
      {migrar ? <>
        <p>Hay información guardada de tu aplicación anterior. Puedes incorporar tus planes, notas y recordatorios a este espacio.</p>
        {sesion.migration_counts ? <dl className={nativo.conteos}>{Object.entries(sesion.migration_counts).filter(([, n]) => n > 0).map(([k, n]) => <div key={k}><dt>{k.replaceAll('_', ' ')}</dt><dd>{n}</dd></div>)}</dl> : null}
        {sesion.migration_warning ? <p className={nativo.aviso}>{sesion.migration_warning}</p> : null}
        <button className={css.principal} disabled={ocupado} onClick={() => void actuar('migrate', { confirm: true })}>{ocupado ? 'Guardando…' : 'Recuperar organización anterior'}</button>
        <button className={css.enlace} disabled={ocupado} onClick={() => void actuar('migrate', { confirm: false })}>Conservarla para después</button>
      </> : <>
        <p>Conecta esta aplicación con tu cuenta de Google para consultar tus datos desde cualquier lugar.</p>
        {sesion.pending ? <div className={nativo.pendiente}>
          <p>En el navegador, comprueba este código y aprueba el acceso. Después vuelve a Corte.</p>
          <strong className={nativo.codigo}>{sesion.pending.user_code}</strong>
          <p role="status">Esperando tu autorización…</p>
        </div> : null}
        <button className={css.principal} disabled={ocupado} onClick={() => void actuar('connect')}>{ocupado ? 'Abriendo navegador…' : sesion.pending ? 'Volver a abrir la conexión' : 'Continuar con Google'}</button>
        <p className={css.notaGoogle}>El acceso se realiza en tu navegador habitual.</p>
      </>}
      {error || sesion.error ? <p role="alert" className={css.error}>{error || sesion.error}</p> : null}
    </section>
    <p className={css.pie}>Tus resultados y próximos pasos, en un solo lugar.</p>
  </main>;
}
