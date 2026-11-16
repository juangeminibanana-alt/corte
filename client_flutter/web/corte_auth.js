// Entrada de bundle autocontenido: resolver Firebase 13.3.0 desde ui/node_modules.
// El resultado se sirve en este mismo origen. Nunca devuelve tokens a Dart/widgets.
import { getApps, initializeApp } from 'firebase/app';
import { browserSessionPersistence, getAuth, getRedirectResult, GoogleAuthProvider,
  setPersistence, signInWithPopup, signInWithRedirect, signOut } from 'firebase/auth';

let firebasePromise;
let generation = 0;
let activeLogin;

async function firebaseClient() {
  if (!firebasePromise) firebasePromise = (async () => {
    const response = await fetch('/api/cloud/config', { credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok) throw new Error('config');
    const config = await response.json();
    const f = config.firebase;
    if (config.auth_provider !== 'firebase' || !f || !['apiKey', 'authDomain', 'projectId', 'appId'].every(k => typeof f[k] === 'string' && f[k])) throw new Error('config');
    const app = getApps().find(a => a.name === 'corte-flutter-web') ?? initializeApp(f, 'corte-flutter-web');
    const auth = getAuth(app);
    auth.languageCode = 'es';
    await setPersistence(auth, browserSessionPersistence);
    return auth;
  })().catch(error => { firebasePromise = undefined; throw error; });
  return firebasePromise;
}

const messages = {
  'auth/popup-closed-by-user': 'Se canceló el acceso con Google. Puedes intentarlo de nuevo.',
  'auth/cancelled-popup-request': 'Se canceló el acceso con Google. Puedes intentarlo de nuevo.',
  'auth/popup-blocked': 'El navegador bloqueó la ventana de Google. Puedes continuar en esta pestaña.',
  'auth/unauthorized-domain': 'Este dominio aún no está autorizado para entrar con Google.',
  'auth/operation-not-allowed': 'El acceso con Google aún no está disponible en el servicio.',
  'auth/web-storage-unsupported': 'El navegador bloquea el almacenamiento necesario para entrar con Google.',
  'cuenta_no_autorizada': 'Esta cuenta de Google no tiene acceso a Corte.',
  'demasiados_intentos': 'Espera antes de volver a intentar el acceso.',
};
function failure(error) {
  const code = typeof error?.code === 'string' && Object.hasOwn(messages, error.code) ? error.code : 'error_google';
  return { ok: false, code, message: messages[code] ?? 'No pudimos conectar con Google. Revisa tu conexión e inténtalo de nuevo.' };
}
async function completeLogin(result, expectedGeneration) {
  if (!result) return { ok: true, authenticated: false };
  let idToken = await result.user.getIdToken(true);
  if (expectedGeneration !== generation) return { ok: false, code: 'cancelado', message: 'Se canceló el acceso.' };
  try {
    activeLogin = fetch('/api/cloud/login', { method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-CH-Hub': '1' }, body: JSON.stringify({ id_token: idToken }) });
    const response = await activeLogin;
    if (!response.ok) {
      const code = response.status === 429 ? 'demasiados_intentos' : 'cuenta_no_autorizada';
      return failure({ code });
    }
    return { ok: true, authenticated: true };
  } finally { idToken = null; activeLogin = undefined; }
}

window.corteAuth = Object.freeze({
  async signIn() {
    const current = ++generation;
    try {
      const auth = await firebaseClient();
      return await completeLogin(await signInWithPopup(auth, new GoogleAuthProvider()), current);
    } catch (error) { return failure(error); }
  },
  async finishRedirect() {
    const current = generation;
    try { return await completeLogin(await getRedirectResult(await firebaseClient()), current); }
    catch (error) { return failure(error); }
  },
  async redirectSignIn() {
    ++generation;
    try { await signInWithRedirect(await firebaseClient(), new GoogleAuthProvider()); return { ok: true, authenticated: false }; }
    catch (error) { return failure(error); }
  },
  async signOut() {
    ++generation;
    // El cierre del servidor queda después de cualquier canje ya enviado.
    if (activeLogin) { try { await activeLogin; } catch (_) { /* El logout se intenta igualmente. */ } }
    try {
      const response = await fetch('/api/cloud/logout', { method: 'POST', credentials: 'same-origin', cache: 'no-store', headers: { 'X-CH-Hub': '1' } });
      if (!response.ok && response.status !== 401) return { ok: false, code: 'cierre_no_confirmado', message: 'No pudimos confirmar el cierre de sesión. Inténtalo de nuevo.' };
      if (firebasePromise) await signOut(await firebasePromise);
      return { ok: true, authenticated: false };
    } catch (_) { return { ok: false, code: 'cierre_no_confirmado', message: 'No pudimos confirmar el cierre de sesión. Revisa tu conexión.' }; }
  },
});

// Copia/outbox privados de esta app, separados por el scope opaco del servidor.
// Una transacción completa es el ACK; nunca se almacenan tokens aquí.
let database;
function privateDatabase() {
  if (!database) database = new Promise((resolve, reject) => {
    const request = indexedDB.open('corte-private-v1', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('documents');
    request.onerror = () => reject(new Error('almacenamiento_no_disponible'));
    request.onblocked = () => reject(new Error('almacenamiento_bloqueado'));
    request.onsuccess = () => {
      const db = request.result;
      db.onversionchange = () => { db.close(); database = undefined; };
      resolve(db);
    };
  }).catch(error => { database = undefined; throw error; });
  return database;
}
async function documentTransaction(key, mode, value) {
  if (!/^corte\.data\.[a-f0-9]{64}\.(snapshot|outbox|images|image\.[a-f0-9]{64})$/.test(key)) throw new Error('clave_no_permitida');
  if (mode === 'write' && (typeof value !== 'string' || new TextEncoder().encode(value).length > 32 * 1024 * 1024)) throw new Error('copia_demasiado_grande');
  const db = await privateDatabase();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('documents', mode === 'read' ? 'readonly' : 'readwrite');
    const store = tx.objectStore('documents');
    const request = mode === 'read' ? store.get(key) : mode === 'write' ? store.put(value, key) : store.delete(key);
    let result;
    request.onsuccess = () => { result = request.result; };
    tx.oncomplete = () => resolve(mode === 'read' && typeof result === 'string' ? result : null);
    tx.onerror = tx.onabort = () => reject(new Error('copia_no_guardada'));
  });
}
window.corteData = Object.freeze({
  read: key => documentTransaction(key, 'read'),
  write: (key, value) => documentTransaction(key, 'write', value),
  remove: key => documentTransaction(key, 'remove'),
});
