import { useRef, useState, type ReactElement } from 'react';
import { Boton } from '@/componentes';
import { ErrorHub, invalidar } from '@/datos';
import { obtenerTransporte } from '../../datos/transporte';
import css from './videos.module.css';

const scopeValido = /^[a-f0-9]{64}$/;

export function ActualizarMetricas(p: { id: string; refrescar: () => Promise<void> }): ReactElement {
  const enCurso = useRef(false);
  const [cargando, setCargando] = useState(false);
  const [mensaje, setMensaje] = useState('');
  const [error, setError] = useState('');

  async function actualizar(): Promise<void> {
    if (enCurso.current) return;
    enCurso.current = true;
    setCargando(true);
    setMensaje('');
    setError('');
    try {
      const transporte = await obtenerTransporte();
      const sesion = await transporte.obtener('/api/cloud/session') as { cache_scope?: string } | null;
      const scope = sesion?.cache_scope;
      if (!scope || !scopeValido.test(scope)) {
        setError('Vuelve a conectar CUTGC para actualizar este video.');
        return;
      }
      const respuesta = await transporte.pedir(
        'POST', '/api/catalogo/videos/' + encodeURIComponent(p.id) + '/actualizar', {}, scope,
      ) as { actualizado?: boolean } | null;
      if (respuesta?.actualizado !== true) throw new Error('Respuesta incompleta');
      invalidar('videos', 'catalogo_videos', 'dashboard');
      await p.refrescar();
      setMensaje('TikTok confirmó la actualización.');
    } catch (err) {
      setError(err instanceof ErrorHub ? err.mensaje : 'No pudimos actualizar las métricas del video.');
    } finally {
      enCurso.current = false;
      setCargando(false);
    }
  }

  return <div className={css.actualizarMetricas}>
    <Boton variante="secundario" cargando={cargando} deshabilitado={cargando}
      alPulsar={() => { void actualizar(); }}>Actualizar métricas</Boton>
    {mensaje ? <span role="status" className={css.vacioCorto}>{mensaje}</span> : null}
    {error ? <span role="alert" className={css.vacioCorto}>{error}</span> : null}
  </div>;
}
