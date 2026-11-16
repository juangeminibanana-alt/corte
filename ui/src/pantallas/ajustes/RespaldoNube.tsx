import { useCallback, useEffect, useState, type ReactElement } from 'react';
import { Boton, Modal, useToast } from '@/componentes';
import { invalidar } from '@/datos';
import { expirarSesionNube } from '../../nube/entorno';
import { fetchCorte } from '../../nube/servicio';
import { Aviso, Fila, Grupo } from './piezas';
import { tamano } from './logica';
import css from './ajustes.module.css';

interface Respaldo { id: string; created_at: string | number; size_bytes: number }

async function peticion(ruta: string, cuerpo?: unknown): Promise<unknown> {
  const r = await fetchCorte(`/api/cloud/storage${ruta}`, { credentials: 'same-origin', cache: 'no-store', method: cuerpo === undefined ? 'GET' : 'POST', headers: { Accept: 'application/json', ...(cuerpo === undefined ? {} : { 'Content-Type': 'application/json', 'X-CH-Hub': '1' }) }, ...(cuerpo === undefined ? {} : { body: JSON.stringify(cuerpo) }) });
  if (r.status === 401) expirarSesionNube();
  if (!r.ok) throw new Error('No pudimos completar la operación con el almacenamiento. Inténtalo de nuevo.');
  return r.json();
}

function fecha(respaldo: Respaldo): string {
  const d = new Date(typeof respaldo.created_at === 'number' ? respaldo.created_at * 1000 : respaldo.created_at);
  return Number.isNaN(d.getTime()) ? 'Fecha no disponible' : d.toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: 'short' });
}

/** Respaldos privados, creados solo al pulsar el botón. Nunca se publican URLs del bucket. */
export function RespaldoNube(): ReactElement {
  const [habilitado, setHabilitado] = useState<boolean | null>(null);
  const [items, setItems] = useState<Respaldo[]>([]);
  const [error, setError] = useState('');
  const [trabajando, setTrabajando] = useState(false);
  const [restaurar, setRestaurar] = useState<Respaldo | null>(null);
  const toast = useToast();
  const cargar = useCallback(async (): Promise<void> => {
    setError('');
    try {
      const datos = await peticion('');
      if (datos === null || typeof datos !== 'object' || !('enabled' in datos) || typeof datos.enabled !== 'boolean' || !('backups' in datos) || !Array.isArray(datos.backups)) throw new Error('El servidor no confirmó el almacenamiento.');
      setHabilitado(datos.enabled);
      setItems(datos.backups.filter((x: unknown): x is Respaldo => x !== null && typeof x === 'object' && 'id' in x && typeof x.id === 'string' && 'created_at' in x && (typeof x.created_at === 'string' || typeof x.created_at === 'number') && 'size_bytes' in x && typeof x.size_bytes === 'number'));
    } catch (e) { setError(e instanceof Error ? e.message : 'No pudimos consultar los respaldos.'); }
  }, []);
  useEffect(() => { void cargar(); }, [cargar]);
  const guardar = async (): Promise<void> => {
    setTrabajando(true); setError('');
    try { await peticion('/backup', {}); toast.mostrar({ texto: 'Guardamos el respaldo en Firebase Storage.', tono: 'ok' }); await cargar(); }
    catch (e) { setError(e instanceof Error ? e.message : 'No pudimos guardar el respaldo.'); }
    finally { setTrabajando(false); }
  };
  const recuperar = async (): Promise<void> => {
    if (!restaurar) return;
    setTrabajando(true); setError('');
    try { await peticion('/restore', { id: restaurar.id }); invalidar(); setRestaurar(null); toast.mostrar({ texto: 'Restauramos los datos del respaldo.', tono: 'ok' }); }
    catch (e) { setError(e instanceof Error ? e.message : 'No pudimos restaurar el respaldo.'); }
    finally { setTrabajando(false); }
  };
  return <Grupo titulo="Respaldos en Firebase Storage">
    <Fila etiqueta="Guarda una copia de tu trabajo" descripcion="Incluye tu plan, notas, avisos, recordatorios, plantillas y preferencias. Las credenciales de TikTok no se incluyen.">
      <Boton variante="secundario" icono="Download" deshabilitado={habilitado !== true || trabajando} cargando={trabajando && restaurar === null} alPulsar={() => void guardar()}>Crear respaldo</Boton>
    </Fila>
    {error ? <div className={css.filaLibre}><Aviso tono="critico" vivo acciones={<Boton variante="secundario" tamano="sm" alPulsar={() => void cargar()}>Reintentar</Boton>}>{error}</Aviso></div> : habilitado === null ? <p className={css.vacioGrupo} role="status">Consultando respaldos…</p> : habilitado === false ? <p className={css.vacioGrupo}>El almacenamiento de Firebase aún no está configurado en el servicio.</p> : items.length === 0 ? <p className={css.vacioGrupo}>Todavía no has creado ningún respaldo.</p> : items.map((item) => <Fila key={item.id} etiqueta={fecha(item)} descripcion={tamano(item.size_bytes)}><Boton variante="secundario" tamano="sm" deshabilitado={trabajando} alPulsar={() => setRestaurar(item)}>Restaurar</Boton></Fila>)}
    <Modal abierto={restaurar !== null} titulo="¿Restaurar este respaldo?" alCerrar={() => setRestaurar(null)} pie={<><Boton variante="fantasma" alPulsar={() => setRestaurar(null)}>Cancelar</Boton><Boton variante="primario" cargando={trabajando} alPulsar={() => void recuperar()}>Restaurar respaldo</Boton></>}><p>Se importarán el plan, las notas y las preferencias guardadas {restaurar ? `el ${fecha(restaurar)}` : ''}. Los registros que ya existen no se duplicarán.</p></Modal>
  </Grupo>;
}
