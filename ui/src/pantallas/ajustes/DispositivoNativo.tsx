import { useEffect, useState, type ReactElement } from 'react';
import { Boton, useToast } from '@/componentes';
import { accionNativa, leerSesionNativa, type SesionNativa } from '../../nube/clienteNativo';
import { cerrarSesionNube } from '../../nube/entorno';
import { Fila, Grupo } from './piezas';

export function DispositivoNativo(): ReactElement {
  const [sesion, setSesion] = useState<SesionNativa | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [confirmar, setConfirmar] = useState(false);
  const toast = useToast();
  useEffect(() => { let vivo = true; void leerSesionNativa().then(s => { if (vivo) setSesion(s); }).catch(() => {}); return () => { vivo = false; }; }, []);
  const recuperar = async (): Promise<void> => {
    setOcupado(true);
    try { await accionNativa('migrate', { confirm: true }); setSesion(await leerSesionNativa()); setConfirmar(false); toast.mostrar({ texto: 'Recuperamos tu organización anterior.', tono: 'ok' }); }
    catch (e) { toast.mostrar({ texto: e instanceof Error ? e.message : 'No pudimos recuperar los datos.', tono: 'error' }); }
    finally { setOcupado(false); }
  };
  return <Grupo titulo="Este dispositivo">
    <Fila etiqueta="Conexión con Google Cloud" descripcion={sesion?.offline ? 'Sin internet. Puedes consultar la información guardada en este dispositivo.' : 'Tus datos se actualizan por internet, sin depender de una PC encendida.'} />
    {sesion?.migration_available ? <Fila etiqueta="Organización de la aplicación anterior" descripcion={confirmar ? 'Incorpora los planes, notas y recordatorios guardados a la cuenta conectada actualmente.' : 'Conservamos una copia de tu información anterior.'}>
      <Boton variante="secundario" cargando={ocupado} alPulsar={() => confirmar ? void recuperar() : setConfirmar(true)}>{confirmar ? 'Confirmar recuperación' : 'Recuperar organización'}</Boton>
    </Fila> : null}
    <Fila etiqueta="Acceso a CUTGC" descripcion="Cierra el acceso únicamente en este dispositivo.">
      <Boton variante="secundario" alPulsar={() => void cerrarSesionNube().catch(e => toast.mostrar({ texto: e instanceof Error ? e.message : 'No pudimos cerrar la sesión.', tono: 'error' }))}>Cerrar sesión</Boton>
    </Fila>
  </Grupo>;
}
