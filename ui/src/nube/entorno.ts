/** El modo web se establece antes de montar la aplicación y sus consultas. */
import { abrirExterno } from '@/plataforma';
import { accionNativa } from './clienteNativo';
let nube = false;
let nativo = false;
export const ORIGEN_CORTE = 'https://corte-e-book-21589.web.app';
export function esClienteNativo(): boolean { return nativo; }
export function fijarClienteNativo(valor: boolean): void { nativo = valor; }
export function origenNube(): string { return nativo ? ORIGEN_CORTE : window.location.origin; }

export function esNube(): boolean { return nube; }
export function fijarModoNube(valor: boolean): void { nube = valor; }

/** OAuth abre la página oficial en la misma pestaña para evitar bloqueos de ventanas emergentes. */
export function abrirAutorizacionNube(enlace: string): void {
  const url = new URL(enlace);
  const permitida = ['tiktok.com', 'tiktokshop.com'].some((host) => url.hostname === host || url.hostname.endsWith(`.${host}`));
  if (url.protocol !== 'https:' || !permitida || url.username || url.password) throw new Error('TikTok devolvió una dirección de autorización no válida.');
  if (nativo) { void abrirExterno(url.href); return; }
  window.location.assign(url.href);
}

export function expirarSesionNube(): void {
  if (nube) window.dispatchEvent(new Event('corte:sesion-cerrada'));
}

export async function cerrarSesionNube(): Promise<void> {
  if (nativo) { await accionNativa('logout'); window.location.reload(); return; }
  const respuesta = await fetch('/api/cloud/logout', {
    method: 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: { 'X-CH-Hub': '1', Accept: 'application/json' },
  });
  if (!respuesta.ok && respuesta.status !== 401) throw new Error('No pudimos cerrar la sesión. Inténtalo de nuevo.');
  try { const { salirFirebase } = await import('./firebase'); await salirFirebase(); } catch { /* El cierre de sesión del servidor ya se completó. */ }
  // La recarga elimina también la caché privada que conserva la app en memoria.
  window.location.reload();
}
