import { fetchCorte } from './servicio';

export interface SesionNativa {
  native_client: true;
  platform: 'windows' | 'android';
  authenticated: boolean;
  connected: boolean;
  offline: boolean;
  hay_copia: boolean;
  pending?: { user_code: string; verification_uri: string; expires_at: number };
  migration_pending?: boolean;
  migration_available?: boolean;
  migration_counts?: Record<string, number>;
  migration_warning?: string;
}

export async function leerSesionNativa(signal?: AbortSignal): Promise<SesionNativa | null> {
  const r = await fetch('/api/native/session', { cache: 'no-store', ...(signal ? { signal } : {}), headers: { Accept: 'application/json' } });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error('No pudimos comprobar el acceso de este dispositivo.');
  const s: unknown = await r.json();
  if (!s || typeof s !== 'object' || !('native_client' in s) || s.native_client !== true || !('authenticated' in s) || typeof s.authenticated !== 'boolean' || !('platform' in s) || !['windows', 'android'].includes(String(s.platform))) throw new Error('La aplicación no confirmó el acceso de este dispositivo.');
  return s as SesionNativa;
}

export async function accionNativa(accion: 'connect' | 'logout' | 'migrate', datos: unknown = {}): Promise<void> {
  const r = await fetchCorte(`/api/native/${accion}`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CH-Hub': '1' }, body: JSON.stringify(datos) });
  if (!r.ok) {
    const d: unknown = await r.json().catch(() => null);
    const mensaje = d && typeof d === 'object' && 'error' in d && d.error && typeof d.error === 'object' && 'mensaje' in d.error && typeof d.error.mensaje === 'string' ? d.error.mensaje : 'No pudimos completar el cambio. Vuelve a intentarlo.';
    throw new Error(mensaje);
  }
}
