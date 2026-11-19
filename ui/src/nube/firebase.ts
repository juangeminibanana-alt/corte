/** Solo configuración pública; las credenciales de administración viven en el servidor. */
export interface ConfigFirebase {
  apiKey: string;
  authDomain: string;
  projectId: string;
  storageBucket?: string;
  appId: string;
}

let cliente: Promise<{ auth: import('firebase/auth').Auth; sdk: typeof import('firebase/auth') }> | null = null;

export function clienteFirebase(config: ConfigFirebase) {
  if (!cliente) cliente = Promise.all([import('firebase/app'), import('firebase/auth')]).then(([appSdk, sdk]) => {
    const app = appSdk.getApps().find((a) => a.name === 'corte-web') ?? appSdk.initializeApp(config, 'corte-web');
    const auth = sdk.getAuth(app);
    auth.languageCode = 'es';
    return { auth, sdk };
  }).catch((e: unknown) => { cliente = null; throw e; });
  return cliente;
}

export async function salirFirebase(): Promise<void> {
  if (cliente) {
    const { auth, sdk } = await cliente;
    await sdk.signOut(auth);
  }
}

export function errorGoogle(e: unknown): { mensaje: string; redirigir: boolean } {
  const codigo = e !== null && typeof e === 'object' && 'code' in e && typeof e.code === 'string' ? e.code : '';
  if (codigo === 'auth/popup-closed-by-user' || codigo === 'auth/cancelled-popup-request') return { mensaje: 'Se canceló el acceso con Google. Puedes intentarlo de nuevo.', redirigir: false };
  if (codigo === 'auth/popup-blocked') return { mensaje: 'El navegador bloqueó la ventana de Google. Permite las ventanas emergentes o continúa en esta pestaña.', redirigir: true };
  if (codigo === 'auth/unauthorized-domain') return { mensaje: 'El dominio de CUTGC aún no está autorizado en Firebase. Falta completar la configuración del acceso.', redirigir: false };
  if (codigo === 'auth/operation-not-allowed' || codigo === 'auth/invalid-api-key') return { mensaje: 'El acceso con Google aún no está configurado. Revisa la configuración de Firebase del servicio.', redirigir: false };
  if (codigo === 'auth/web-storage-unsupported') return { mensaje: 'El navegador bloquea el almacenamiento necesario para entrar. Permítelo para este sitio e inténtalo de nuevo.', redirigir: false };
  return { mensaje: 'No pudimos conectar con Google. Revisa tu conexión e inténtalo de nuevo.', redirigir: false };
}
