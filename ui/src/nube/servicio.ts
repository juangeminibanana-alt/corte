import { infoPlataforma } from '@/plataforma';
import { obtenerTransporte } from '../datos/transporte';
import { ErrorHub } from '../datos/errores';

/** Android entrega el cuerpo JSON por su puente nativo, fuera del interceptor GET de WebView. */
export async function fetchCorte(ruta: string, init?: RequestInit): Promise<Response> {
  const metodo = (init?.method ?? 'GET').toUpperCase();
  if (infoPlataforma().plataforma !== 'android' || !['POST', 'PATCH', 'PUT', 'DELETE'].includes(metodo)) return fetch(ruta, init);
  if (!ruta.startsWith('/api/') || ruta.startsWith('//')) throw new Error('Ruta de CUTGC no válida.');
  const cuerpo: unknown = typeof init?.body === 'string' && init.body ? JSON.parse(init.body) : undefined;
  try {
    const transporte = await obtenerTransporte();
    const resultado = await transporte.pedir(metodo as 'POST' | 'PATCH' | 'PUT' | 'DELETE', ruta, cuerpo);
    return new Response(JSON.stringify(resultado ?? {}), { headers: { 'Content-Type': 'application/json' } });
  } catch (e) {
    if (!(e instanceof ErrorHub)) throw e;
    return new Response(JSON.stringify({ error: { codigo: e.codigo, mensaje: e.mensaje } }), { status: e.http >= 400 && e.http <= 599 ? e.http : 503, headers: { 'Content-Type': 'application/json' } });
  }
}
