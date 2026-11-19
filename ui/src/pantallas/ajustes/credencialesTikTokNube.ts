import { expirarSesionNube } from '../../nube/entorno';
import { fetchCorte } from '../../nube/servicio';

export interface IntegracionTikTokGuardada {
  app_key: string;
  app_secret_configurado: boolean;
  tokens_configurados: boolean;
}

export class ErrorIntegracionTikTok extends Error {
  constructor(readonly codigo: string, mensaje: string) { super(mensaje); }
}

export interface ImportacionAnteriorTikTok {
  verificacion: 'ok' | 'fallo';
  sync_iniciada: boolean;
}

const CAMPOS_CONEXION_ANTERIOR = [
  'app_key', 'app_secret', 'access_token', 'refresh_token', 'access_token_expire_in',
  'refresh_token_expire_in', 'open_id', 'user_type', 'seller_name', 'granted_scopes',
] as const;

/** Descarta preferencias y cualquier dato ajeno a la conexión anterior. */
export function sanearConexionAnteriorTikTok(valor: unknown): Record<string, unknown> {
  if (valor === null || typeof valor !== 'object' || Array.isArray(valor)) throw new ErrorIntegracionTikTok('archivo_invalido', 'Elige el archivo JSON de la conexión anterior de TikTok Shop.');
  const resultado: Record<string, unknown> = {};
  for (const campo of CAMPOS_CONEXION_ANTERIOR) if (Object.hasOwn(valor, campo)) resultado[campo] = (valor as Record<string, unknown>)[campo];
  if (!Object.keys(resultado).length) throw new ErrorIntegracionTikTok('archivo_invalido', 'El archivo no contiene una conexión de TikTok Shop.');
  return resultado;
}

/** Importa por HTTPS sin guardar el archivo ni mostrar sus credenciales. */
export async function importarConexionAnteriorTikTok(configuracion: Record<string, unknown>): Promise<ImportacionAnteriorTikTok> {
  const controlador = new AbortController();
  const limite = setTimeout(() => controlador.abort(), 30_000);
  try {
    const cuerpo = JSON.stringify(configuracion);
    if (new TextEncoder().encode(cuerpo).length > 64 * 1024) throw new ErrorIntegracionTikTok('archivo_invalido', 'El archivo contiene demasiados datos de conexión. Elige el archivo original de tu panel anterior.');
    const respuesta = await fetchCorte('/api/cloud/tiktok/import', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CH-Hub': '1' },
      body: cuerpo, signal: controlador.signal,
    });
    if (respuesta.status === 401) expirarSesionNube();
    const datos: unknown = await respuesta.json();
    if (!respuesta.ok) {
      const error = datos !== null && typeof datos === 'object' && 'error' in datos ? datos.error : null;
      const codigo = error !== null && typeof error === 'object' && 'codigo' in error && typeof error.codigo === 'string' ? error.codigo : '';
      const texto = respuesta.status === 401 ? 'Tu sesión terminó. Vuelve a entrar a CUTGC.'
        : respuesta.status === 409 ? 'CUTGC ya tiene una conexión o el archivo pertenece a otra cuenta. No se cambió tu conexión actual.'
        : respuesta.status === 413 ? 'El archivo supera el tamaño permitido para una conexión.'
        : 'No pudimos importar la conexión. Comprueba que sea el archivo original de tu panel anterior.';
      throw new ErrorIntegracionTikTok(codigo, texto);
    }
    if (datos === null || typeof datos !== 'object' || !('ok' in datos) || typeof datos.ok !== 'boolean'
      || !('verificacion' in datos) || (datos.verificacion !== 'ok' && datos.verificacion !== 'fallo')
      || !('sync_iniciada' in datos) || typeof datos.sync_iniciada !== 'boolean'
      || datos.ok !== (datos.verificacion === 'ok')) {
      throw new ErrorIntegracionTikTok('respuesta_invalida', 'El servidor no confirmó la importación. Actualiza para revisar la conexión.');
    }
    return { verificacion: datos.verificacion, sync_iniciada: datos.sync_iniciada };
  } catch (e) {
    if (e instanceof ErrorIntegracionTikTok) throw e;
    throw new ErrorIntegracionTikTok('red', 'No pudimos completar la importación. Revisa tu conexión y vuelve a intentarlo.');
  } finally {
    for (const campo of Object.keys(configuracion)) delete configuracion[campo];
    clearTimeout(limite);
  }
}

/** Envía la pareja de la misma app; nunca guarda el secreto en el navegador. */
export async function guardarIntegracionTikTok(credenciales: { app_key: string; app_secret: string }): Promise<IntegracionTikTokGuardada> {
  const controlador = new AbortController();
  const limite = setTimeout(() => controlador.abort(), 20_000);
  try {
    const respuesta = await fetchCorte('/api/cloud/tiktok/credentials', {
      method: 'PUT', credentials: 'same-origin', cache: 'no-store',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CH-Hub': '1' },
      body: JSON.stringify(credenciales), signal: controlador.signal,
    });
    if (respuesta.status === 401) expirarSesionNube();
    const datos: unknown = await respuesta.json();
    if (!respuesta.ok) {
      const error = datos !== null && typeof datos === 'object' && 'error' in datos ? datos.error : null;
      const codigo = error !== null && typeof error === 'object' && 'codigo' in error && typeof error.codigo === 'string' ? error.codigo : '';
      const mensajes: Record<string, string> = {
        app_key_invalida: 'La App key no tiene un formato válido. Cópiala de la misma app que el App secret.',
        app_secret_invalido: 'TikTok no aceptó el App secret. Comprueba que ambas claves pertenezcan a la misma app.',
        app_key_en_uso: 'Para cambiar la App key, primero desconecta la cuenta de TikTok Shop. Tus datos guardados se conservarán.',
        sin_internet: 'No pudimos verificar la integración con TikTok. Inténtalo de nuevo cuando se restablezca la conexión.',
      };
      const texto = respuesta.status === 401 ? 'Tu sesión terminó. Vuelve a entrar a CUTGC.'
        : respuesta.status === 403 ? 'No tienes permiso para cambiar esta integración.'
        : mensajes[codigo] ?? 'No pudimos guardar la integración. Revisa las dos claves e inténtalo de nuevo.';
      throw new ErrorIntegracionTikTok(codigo, texto);
    }
    if (datos === null || typeof datos !== 'object' || !('app_key' in datos) || datos.app_key !== credenciales.app_key
      || !('app_secret_configurado' in datos) || datos.app_secret_configurado !== true
      || !('tokens_configurados' in datos) || typeof datos.tokens_configurados !== 'boolean') {
      throw new ErrorIntegracionTikTok('respuesta_invalida', 'El servidor no confirmó la integración. Vuelve a intentarlo.');
    }
    return { app_key: datos.app_key, app_secret_configurado: true, tokens_configurados: datos.tokens_configurados };
  } catch (e) {
    if (e instanceof ErrorIntegracionTikTok) throw e;
    throw new ErrorIntegracionTikTok('red', 'No pudimos conectar con CUTGC. Vuelve a intentarlo; si el secreto ya se guardó, aparecerá como configurado al actualizar.');
  } finally {
    credenciales.app_secret = '';
    clearTimeout(limite);
  }
}
