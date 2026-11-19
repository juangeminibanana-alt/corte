import { useRef, useState, type ReactElement } from 'react';
import { Boton, useToast } from '@/componentes';
import { invalidar } from '@/datos';
import { fetchCorte } from '../../nube/servicio';
import { Fila, Grupo } from './piezas';

const CAMPOS = ['client_key', 'client_secret', 'access_token', 'refresh_token', 'access_expira_at', 'refresh_expira_at', 'open_id', 'scopes', 'conectada_at', 'origen'] as const;

/** Recupera la conexión existente sin almacenar ni volver a mostrar sus secretos. */
export function ImportarVideosNube(): ReactElement {
  const archivo = useRef<HTMLInputElement>(null);
  const [ocupado, setOcupado] = useState(false);
  const toast = useToast();
  async function importar(file: File | undefined): Promise<void> {
    if (!file || ocupado) return;
    setOcupado(true);
    const cuerpo: Record<string, unknown> = {};
    try {
      if (file.size > 64 * 1024) throw new Error('El archivo de conexión supera el límite de 64 KB.');
      const contenido: unknown = JSON.parse(await file.text());
      if (!contenido || typeof contenido !== 'object' || Array.isArray(contenido)) throw new Error('Elige la conexión exportada de tu aplicación anterior.');
      for (const k of CAMPOS) if (Object.hasOwn(contenido, k)) cuerpo[k] = (contenido as Record<string, unknown>)[k];
      const r = await fetchCorte('/api/cloud/display/import', { method:'POST', credentials:'same-origin', cache:'no-store', headers:{ 'Content-Type':'application/json', 'X-CH-Hub':'1' }, body:JSON.stringify(cuerpo) });
      const d: unknown = await r.json();
      if (!r.ok || !d || typeof d !== 'object' || !('ok' in d) || d.ok !== true) {
        const mensaje = d && typeof d === 'object' && 'error' in d && d.error && typeof d.error === 'object' && 'mensaje' in d.error && typeof d.error.mensaje === 'string' ? d.error.mensaje : 'No pudimos verificar la conexión de videos. Tu conexión actual se conservó.';
        throw new Error(mensaje);
      }
      invalidar();
      toast.mostrar({ texto:'Recuperamos tu conexión de videos. Las portadas y métricas se actualizarán al sincronizar.', tono:'ok' });
    } catch (e) { toast.mostrar({ texto:e instanceof SyntaxError ? 'El archivo no contiene una conexión JSON válida.' : e instanceof Error ? e.message : 'No pudimos recuperar la conexión.', tono:'error' }); }
    finally { for (const k of Object.keys(cuerpo)) delete cuerpo[k]; setOcupado(false); if (archivo.current) archivo.current.value=''; }
  }
  return <Grupo titulo="Recuperar la conexión anterior">
    <input type="file" accept=".json,application/json" hidden ref={archivo} onChange={e => void importar(e.target.files?.[0])} />
    <Fila etiqueta="Conexión de videos de tu aplicación anterior" descripcion="CUTGC comprueba que pertenezca a tu cuenta antes de recuperar las portadas y las métricas.">
      <Boton variante="secundario" cargando={ocupado} alPulsar={() => archivo.current?.click()}>Recuperar conexión de videos</Boton>
    </Fila>
  </Grupo>;
}
