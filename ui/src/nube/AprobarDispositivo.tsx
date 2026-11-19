import { useEffect, useState, type FormEvent, type ReactElement } from 'react';
import css from './AprobarDispositivo.module.css';

interface Solicitud {
  user_code: string;
  platform: 'windows' | 'android';
  name: string;
  expires_at: number;
  estado: string;
}

const CODIGO = /^[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$/;

async function respuesta(r: Response): Promise<unknown> {
  const datos: unknown = await r.json();
  if (!r.ok) {
    const mensaje = datos && typeof datos === 'object' && 'error' in datos && datos.error
      && typeof datos.error === 'object' && 'mensaje' in datos.error && typeof datos.error.mensaje === 'string'
      ? datos.error.mensaje : 'No pudimos comprobar la conexión. Inténtalo de nuevo.';
    throw new Error(mensaje);
  }
  return datos;
}

function solicitudValida(v: unknown): v is Solicitud {
  return v !== null && typeof v === 'object' && 'user_code' in v && typeof v.user_code === 'string'
    && 'platform' in v && (v.platform === 'windows' || v.platform === 'android')
    && 'name' in v && typeof v.name === 'string' && 'expires_at' in v && typeof v.expires_at === 'number'
    && 'estado' in v && typeof v.estado === 'string';
}

/** AccesoNube verifica Google antes de montar esta pantalla. Nunca recibe tokens nativos. */
export function AprobarDispositivo(): ReactElement {
  const [codigo, setCodigo] = useState(() => new URLSearchParams(window.location.search).get('codigo')?.toUpperCase() ?? '');
  const [consulta, setConsulta] = useState(() => CODIGO.test(codigo) ? codigo : '');
  const [intento, setIntento] = useState(0);
  const [solicitud, setSolicitud] = useState<Solicitud | null>(null);
  const [cargando, setCargando] = useState(Boolean(consulta));
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState('');
  const [terminado, setTerminado] = useState<'aprobado' | 'denegado' | null>(null);

  useEffect(() => {
    if (!consulta) return;
    const c = new AbortController();
    const tiempo = window.setTimeout(() => c.abort(), 15000);
    let vivo = true;
    setCargando(true); setSolicitud(null); setError(''); setTerminado(null);
    void fetch(`/api/native/auth/request?codigo=${encodeURIComponent(consulta)}`, {
      credentials: 'same-origin', cache: 'no-store', signal: c.signal,
    }).then(respuesta).then(datos => {
      if (!solicitudValida(datos)) throw new Error('El servidor no pudo comprobar este dispositivo.');
      if (vivo) setSolicitud(datos);
    }).catch((e: unknown) => {
      if (vivo) setError(e instanceof Error && e.name !== 'AbortError' ? e.message : 'La conexión tardó demasiado. Vuelve a intentarlo.');
    }).finally(() => {
      window.clearTimeout(tiempo);
      if (vivo) setCargando(false);
    });
    return () => { vivo = false; window.clearTimeout(tiempo); c.abort(); };
  }, [consulta, intento]);

  function buscar(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    if (!CODIGO.test(codigo)) { setError('Escribe el código de ocho caracteres que aparece en la app.'); return; }
    setConsulta(codigo);
    setIntento(v => v + 1);
  }

  async function decidir(aprobar: boolean): Promise<void> {
    if (!solicitud || enviando) return;
    setEnviando(true); setError('');
    const c = new AbortController();
    const tiempo = window.setTimeout(() => c.abort(), 15000);
    try {
      await respuesta(await fetch(`/api/native/auth/${aprobar ? 'approve' : 'deny'}`, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', signal: c.signal,
        headers: { 'Content-Type': 'application/json', 'X-CH-Hub': '1' },
        body: JSON.stringify({ user_code: solicitud.user_code }),
      }));
      setTerminado(aprobar ? 'aprobado' : 'denegado');
    } catch (e) {
      setError(e instanceof Error && e.name !== 'AbortError' ? e.message : 'La conexión tardó demasiado. Revisa el estado desde la app.');
    } finally { window.clearTimeout(tiempo); setEnviando(false); }
  }

  const resuelta = solicitud && solicitud.estado !== 'pendiente';
  return <main className={css.fondo}>
    <div className={css.marca}>CUTGC</div>
    <section className={css.panel} aria-labelledby="titulo-dispositivo" aria-busy={cargando || enviando}>
      <span className={css.etiqueta}>ACCESO A TU CUENTA</span>
      <h1 id="titulo-dispositivo">{terminado === 'aprobado' ? 'Tu app ya puede conectarse' : terminado === 'denegado' ? 'Conexión rechazada' : 'Conecta tu dispositivo'}</h1>
      {terminado ? <div role="status">
        <p>{terminado === 'aprobado' ? 'Vuelve a CUTGC en tu dispositivo. La conexión terminará allí automáticamente.' : 'Este dispositivo no tendrá acceso. Puedes cerrar esta página.'}</p>
      </div> : <>
        <p>Confirma el dispositivo que abriste para usar CUTGC con tus datos en la nube.</p>
        {!solicitud && !cargando && <form className={css.formulario} onSubmit={buscar}>
          <label htmlFor="codigo-dispositivo">Código de la app</label>
          <input id="codigo-dispositivo" value={codigo} maxLength={9} autoComplete="off" spellCheck={false}
            placeholder="ABCD-2345" aria-describedby="ayuda-codigo" onChange={e => {
              const limpio = e.currentTarget.value.toUpperCase().replace(/[^A-Z2-9]/g, '').slice(0, 8);
              setCodigo(limpio.length > 4 ? `${limpio.slice(0, 4)}-${limpio.slice(4)}` : limpio);
            }} />
          <span id="ayuda-codigo" className={css.ayuda}>Aparece al pulsar «Conectar mi cuenta» en CUTGC para Windows o Android.</span>
          <button type="submit" className={css.principal}>Revisar dispositivo</button>
        </form>}
        {cargando && <p role="status">Comprobando el dispositivo…</p>}
        {solicitud && <>
          <dl className={css.detalles}>
            <div><dt>Dispositivo</dt><dd>{solicitud.name}</dd></div>
            <div><dt>Sistema</dt><dd>{solicitud.platform === 'windows' ? 'Windows' : 'Android'}</dd></div>
            <div><dt>Código</dt><dd className={css.codigo}>{solicitud.user_code}</dd></div>
          </dl>
          {resuelta ? <p role="status">Esta solicitud ya fue resuelta. Vuelve a la app para comprobar su conexión.</p> : <>
            <p className={css.aviso}>Aprueba solo si acabas de abrir CUTGC en ese dispositivo y el código coincide. Tendrá acceso a tus datos y podrá guardar cambios.</p>
            <div className={css.acciones}>
              <button type="button" className={css.principal} disabled={enviando} onClick={() => { void decidir(true); }}>{enviando ? 'Guardando…' : 'Aprobar conexión'}</button>
              <button type="button" className={css.secundario} disabled={enviando} onClick={() => { void decidir(false); }}>Rechazar</button>
            </div>
          </>}
        </>}
      </>}
      {error && <p className={css.error} role="alert">{error}</p>}
    </section>
    <a className={css.volver} href="/">Ir a CUTGC</a>
  </main>;
}
