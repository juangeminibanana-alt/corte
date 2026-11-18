/** Pruebas sintéticas: nunca leen archivos de conexión ni credenciales del equipo. */
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { randomBytes } from 'node:crypto';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import ts from 'typescript';
import { Window } from 'happy-dom';

const require = createRequire(import.meta.url);
const ui = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const window = new Window({ url: 'https://corte-e-book-21589.web.app/' });
for (const [name, value] of Object.entries({ window, document: window.document, navigator: window.navigator,
  HTMLElement: window.HTMLElement, HTMLInputElement: window.HTMLInputElement, Node: window.Node,
  Event: window.Event, MouseEvent: window.MouseEvent, getComputedStyle: window.getComputedStyle.bind(window),
  IS_REACT_ACT_ENVIRONMENT: true })) Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });

const React = require('react');
const { render, screen, fireEvent, waitFor, cleanup } = require('@testing-library/react');
const styles = { __esModule: true, default: new Proxy({}, { get: (_target, key) => String(key) }) };
const requests = [], invalidations = [], links = [], toasts = [];
let fetcher, expired = 0, credentialReads = 0, sessionReads = 0;
let credentials = { app_key: '', app_secret_configurado: false, tokens_configurados: false };
const consulta = { get datos() { return credentials; }, cargando: false, error: null, refrescar: async () => { credentialReads++; } };
let session = { datos: { conexion: { estado: 'sin_autorizar', aviso: null }, cuenta: null }, cargando: false, error: null, refrescar: async () => { sessionReads++; } };
// origenNube: en la web (no nativa) es window.location.origin, como en nube/entorno.ts.
const env = { abrirAutorizacionNube: (url) => links.push(url), expirarSesionNube: () => expired++, origenNube: () => window.location.origin };
const hub = { authLink: async (open) => { links.push(open); return { url: 'https://shop.tiktok.com/alliance/creator/auth?state=qa' }; },
  authCanjear: async () => {}, authRefrescar: async () => ({ conexion: { estado: 'conectada', aviso: null, scopes_faltantes: [] } }), sincronizar: async () => {}, authDesconectar: async () => {} };
class ErrorHub extends Error {}

function load(file, mock) {
  const source = readFileSync(resolve(ui, file), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText;
  const context = { exports: {}, require: mock, window, document: window.document, Error, TextEncoder,
    AbortController, setTimeout, clearTimeout, fetch: (url, options) => { requests.push({ url, options }); return fetcher(url, options); } };
  vm.runInNewContext(code, context, { filename: file });
  return context.exports;
}

// fetchCorte real en el navegador: así las aserciones de peticiones siguen viendo lo que recibe fetch.
const servicio = load('src/nube/servicio.ts', (id) => {
  if (id === '@/plataforma') return { infoPlataforma: () => ({ plataforma: 'navegador' }) };
  if (id === '../datos/transporte') return { obtenerTransporte: async () => assert.fail('El navegador no usa el transporte nativo.') };
  if (id === '../datos/errores') return { ErrorHub };
  throw new Error('Dependencia de prueba inesperada.');
});
const helper = load('src/pantallas/ajustes/credencialesTikTokNube.ts', (id) => {
  if (id === '../../nube/entorno') return env;
  if (id === '../../nube/servicio') return servicio;
  throw new Error('Dependencia de prueba inesperada.');
});
const CampoTexto = load('src/componentes/CampoTexto.tsx', (id) => id === 'react' ? React
  : id === 'react/jsx-runtime' ? require('react/jsx-runtime') : id === './Icono' ? { Icono: () => React.createElement('span') }
    : id === './util/clases' ? { cx: (...values) => values.filter(Boolean).join(' ') } : styles).CampoTexto;
const children = (p) => React.createElement('div', null, p.children);
const componentes = { CampoTexto, Boton: (p) => React.createElement('button', { type: 'button', onClick: p.alPulsar,
  disabled: !!p.cargando || !!p.deshabilitado }, p.children), Chip: children,
  Modal: (p) => p.abierto ? React.createElement('section', null, React.createElement('h2', null, p.titulo), p.children, p.pie) : null,
  useToast: () => ({ mostrar: (value) => toasts.push(value) }) };
const piezas = { Aviso: (p) => React.createElement('div', { role: p.tono === 'critico' ? 'alert' : 'status' }, p.children),
  CargandoGrupo: () => React.createElement('div', null, 'Cargando'), Dato: (p) => React.createElement('div', null, p.etiqueta, p.valor),
  ErrorCarga: () => React.createElement('div', null, 'Error'), Fila: (p) => React.createElement('div', null, p.etiqueta, p.descripcion, p.children), Grupo: children, Seccion: children };
const componentesNube = load('src/pantallas/ajustes/ConexionNube.tsx', (id) => id === 'react' ? React
  : id === 'react/jsx-runtime' ? require('react/jsx-runtime') : id === '@/componentes' ? componentes
    : id === '@/datos' ? { ErrorHub, hub, invalidar: (...keys) => invalidations.push(keys), useConsulta: () => consulta,
      useSesion: () => session, useSync: () => ({ puede: true, estado: null, sincronizar: async () => {} }) }
      : id === '../../nube/entorno' ? env : id === './piezas' ? piezas : id === './credencialesTikTokNube' ? helper : styles);

const appKey = 'qa-' + randomBytes(6).toString('hex');
const secretoSintetico = randomBytes(24).toString('hex');
const conexionSintetica = () => ({ app_key: appKey, app_secret: secretoSintetico,
  access_token: randomBytes(24).toString('hex'), refresh_token: randomBytes(24).toString('hex'),
  access_token_expire_in: 2000000000, refresh_token_expire_in: 2100000000, user_type: 1,
  granted_scopes: ['creator.affiliate.info'], preferencias_ajenas: { no_importar: true } });
const response = (json, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => json });
const change = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const selectFile = (file) => fireEvent.change(screen.getByLabelText('Archivo de conexión anterior de TikTok Shop'), { target: { files: [file] } });

try {
  let complete;
  fetcher = (_url, options) => new Promise((resolveResponse) => {
    complete = () => resolveResponse(response({ ok: true, app_key: JSON.parse(options.body).app_key,
      app_secret_configurado: true, tokens_configurados: false }));
  });
  render(React.createElement(componentesNube.ConectarTikTokNube));
  assert.ok(screen.getByLabelText('App key').value === '', 'App key nueva sin prellenado');
  assert.ok(!screen.queryByRole('button', { name: 'Continuar en TikTok Shop' }), 'OAuth exige configuración previa');
  fireEvent.click(screen.getByRole('button', { name: 'Guardar integración' }));
  assert.ok(requests.length === 0, 'No enviar campos vacíos');
  change('App key', appKey); change('App secret', secretoSintetico);
  fireEvent.click(screen.getByRole('button', { name: 'Guardar integración' }));
  assert.ok(requests.length === 1, 'Enviar una sola vez');
  const request = requests[0], sent = JSON.parse(request.options.body);
  assert.ok(request.url === '/api/cloud/tiktok/credentials' && request.options.method === 'PUT', 'Guardar la pareja en la API correcta');
  assert.ok(request.options.credentials === 'same-origin' && request.options.headers['X-CH-Hub'] === '1', 'Sesión y CSRF');
  assert.ok(sent.app_key === appKey && sent.app_secret === secretoSintetico, 'Enviar claves de la misma app juntas');
  assert.ok(screen.getByLabelText('App secret').value === '', 'Vaciar secreto antes de recibir respuesta');
  complete();
  await waitFor(() => assert.ok(screen.queryByRole('button', { name: 'Continuar en TikTok Shop' })));
  assert.ok(invalidations.length === 1, 'Actualizar consultas después del guardado');
  assert.ok(!screen.getByText('Cambiar integración').closest('details').open, 'Edición plegada');
  assert.ok(!window.document.body.innerHTML.includes(secretoSintetico), 'No serializar el secreto');
  fireEvent.click(screen.getByRole('button', { name: 'Continuar en TikTok Shop' }));
  await waitFor(() => assert.ok(links.includes(false), 'OAuth se abre en el navegador del creador'));
  cleanup();

  fetcher = async () => response({ error: { codigo: 'app_secret_invalido' } }, 422);
  render(React.createElement(componentesNube.FormularioIntegracionTikTokNube, { alGuardada: () => assert.fail('No debe confirmar un rechazo') }));
  change('App key', appKey); change('App secret', secretoSintetico);
  fireEvent.click(screen.getByRole('button', { name: 'Guardar integración' }));
  await waitFor(() => assert.ok(screen.getByLabelText('App secret').getAttribute('aria-invalid') === 'true'));
  assert.ok(screen.getByLabelText('App secret').value === '', 'Secreto vacío también al fallar');
  assert.ok(screen.getByLabelText('App key').value === appKey, 'Conservar la clave pública al fallar');
  cleanup();

  fetcher = async () => response({ error: { codigo: 'app_key_en_uso' } }, 409);
  const conflict = { app_key: appKey, app_secret: secretoSintetico };
  let rejected = false;
  try { await helper.guardarIntegracionTikTok(conflict); } catch (e) { rejected = e.codigo === 'app_key_en_uso' && e.message.includes('desconecta'); }
  assert.ok(rejected && conflict.app_secret === '', 'Respetar integración activa y limpiar secreto');
  fetcher = async () => response({ error: { codigo: 'sesion_requerida' } }, 401);
  try { await helper.guardarIntegracionTikTok({ app_key: appKey, app_secret: secretoSintetico }); } catch { /* rechazo esperado */ }
  assert.ok(expired === 1, 'Expiración de sesión');

  const imported = [], toastCount = toasts.length;
  fetcher = async () => response({ ok: true, verificacion: 'ok', sync_iniciada: true });
  render(React.createElement(componentesNube.ImportarConexionAnteriorTikTok, { alImportada: (value) => imported.push(value) }));
  const previous = conexionSintetica();
  selectFile(new window.File([JSON.stringify(previous)], 'conexion-sintetica.json', { type: 'application/json' }));
  await waitFor(() => assert.ok(imported.length === 1));
  const importRequest = requests.at(-1), importBody = JSON.parse(importRequest.options.body);
  assert.ok(importRequest.url === '/api/cloud/tiktok/import' && importRequest.options.method === 'POST', 'Importación directa por la API privada');
  assert.ok(!Object.hasOwn(importBody, 'preferencias_ajenas'), 'Descartar datos ajenos');
  assert.ok(importBody.app_secret === secretoSintetico && importBody.access_token === previous.access_token, 'Importar sin transformar las credenciales');
  assert.ok(screen.getByLabelText('Archivo de conexión anterior de TikTok Shop').value === '', 'Limpiar selector');
  assert.ok(toasts.length === toastCount + 1 && toasts.at(-1).tono === 'ok', 'Éxito sólo después de verificación');
  assert.ok(!window.document.body.innerHTML.includes(secretoSintetico), 'No mostrar credenciales importadas');
  cleanup();

  const beforeTooLarge = requests.length;
  render(React.createElement(componentesNube.ImportarConexionAnteriorTikTok, { alImportada: () => assert.fail('Archivo excesivo') }));
  selectFile(new window.File([' '.repeat(1024 * 1024 + 1)], 'grande.json', { type: 'application/json' }));
  await waitFor(() => assert.ok(screen.getByRole('alert').textContent.includes('1 MB')));
  assert.ok(requests.length === beforeTooLarge, 'No enviar archivo excesivo');
  cleanup();

  const beforeUnverified = toasts.length;
  fetcher = async () => {
    credentials = { app_key: appKey, app_secret_configurado: true, tokens_configurados: true };
    return response({ ok: false, verificacion: 'fallo', sync_iniciada: false });
  };
  render(React.createElement(componentesNube.ConectarTikTokNube));
  selectFile(new window.File([JSON.stringify(conexionSintetica())], 'conexion-sintetica.json', { type: 'application/json' }));
  await waitFor(() => assert.ok(screen.getByRole('status').textContent.includes('TikTok no pudo confirmar')));
  assert.ok(toasts.length === beforeUnverified, 'No anunciar éxito si TikTok no confirma');
  cleanup();

  credentials = { app_key: appKey, app_secret_configurado: true, tokens_configurados: true };
  session = { ...session, datos: { ...session.datos, conexion: { estado: 'reautorizar', aviso: null } } };
  render(React.createElement(componentesNube.SeccionTikTokNube));
  assert.ok(screen.getByRole('button', { name: 'Desconectar cuenta' }), 'Autorización vencida permite desconexión explícita');
  assert.ok(!screen.getByText('Cambiar integración').closest('details').open, 'Conexión reutilizada no pide secretos');
  cleanup();

  session = { ...session, datos: { ...session.datos, conexion: { estado: 'conectada', aviso: null } } };
  let refreshCalls = 0, finishRefresh;
  hub.authRefrescar = () => { refreshCalls++; return new Promise((resolveRefresh) => { finishRefresh = resolveRefresh; }); };
  render(React.createElement(componentesNube.SeccionTikTokNube));
  const previousReads = credentialReads + sessionReads;
  fireEvent.click(screen.getByRole('button', { name: 'Renovar conexión' }));
  fireEvent.click(screen.getByRole('button', { name: 'Renovar conexión' }));
  assert.ok(refreshCalls === 1, 'Evitar renovaciones duplicadas');
  finishRefresh({ conexion: { estado: 'conectada', aviso: null, scopes_faltantes: [] } });
  await waitFor(() => assert.ok(toasts.at(-1).texto === 'Se actualizó la conexión.'));
  await waitFor(() => assert.ok(credentialReads + sessionReads === previousReads + 2));
  assert.ok(screen.getByRole('status').textContent.includes('comprobar el perfil'), 'No afirmar verificación del perfil después de renovar');

  hub.authRefrescar = async () => ({ conexion: { estado: 'reautorizar', aviso: 'Autorización requerida.', scopes_faltantes: [] } });
  const beforeReauth = toasts.length;
  fireEvent.click(screen.getByRole('button', { name: 'Renovar conexión' }));
  await waitFor(() => assert.ok(screen.queryByRole('button', { name: 'Continuar en TikTok Shop' })));
  assert.ok(toasts.slice(beforeReauth).every((toast) => toast.tono !== 'ok'), 'HTTP 200 con reautorizar no es éxito');
  assert.ok(!screen.getByText('Cambiar integración').closest('details').open, 'Reautorizar conserva las claves guardadas');

  hub.authRefrescar = async () => ({ conexion: { estado: 'conectada', aviso: 'La renovación está pendiente por un problema temporal.', scopes_faltantes: [] } });
  const beforeTransient = toasts.length;
  fireEvent.click(screen.getByRole('button', { name: 'Renovar conexión' }));
  await waitFor(() => assert.ok(screen.getByRole('status').textContent.includes('problema temporal')));
  assert.ok(toasts.slice(beforeTransient).every((toast) => toast.tono !== 'ok'), 'Aviso transitorio no produce falso éxito');
  cleanup();

  credentials = { app_key: '', app_secret_configurado: false, tokens_configurados: false };
  session = { ...session, datos: { ...session.datos, conexion: { estado: 'sin_credenciales', aviso: null } } };
  fetcher = async () => {
    credentials = { app_key: appKey, app_secret_configurado: true, tokens_configurados: true };
    session = { ...session, datos: { ...session.datos, conexion: { estado: 'conectada', aviso: null } } };
    return response({ ok: false, verificacion: 'fallo', sync_iniciada: false });
  };
  const beforeParentImport = toasts.length;
  render(React.createElement(componentesNube.SeccionTikTokNube));
  selectFile(new window.File([JSON.stringify(conexionSintetica())], 'conexion-sintetica.json', { type: 'application/json' }));
  await waitFor(() => assert.ok(screen.getByText('Pendiente de verificar')));
  assert.ok(!screen.queryByText('Conectada'), 'No etiquetar como conectada la importación no verificada');
  assert.ok(screen.getByRole('status').textContent.includes('TikTok no pudo confirmar'), 'Aviso de importación sobrevive al cambio de sección');
  assert.ok(screen.getByRole('button', { name: 'Renovar conexión' }), 'Permitir renovación después de importar');
  assert.ok(toasts.slice(beforeParentImport).every((toast) => toast.tono !== 'ok'), 'Sin éxito falso al cambiar el estado del padre');
  hub.authRefrescar = async () => ({ conexion: { estado: 'conectada', aviso: null, scopes_faltantes: [] } });
  fireEvent.click(screen.getByRole('button', { name: 'Renovar conexión' }));
  await waitFor(() => assert.ok(screen.getByText('Conectada')));
  assert.ok(!screen.queryByText('Pendiente de verificar'), 'Renovación confirmada limpia la verificación pendiente de importación');
  assert.ok(screen.getByRole('status').textContent.includes('comprobar el perfil'), 'El perfil sigue requiriendo sincronización');
  cleanup();
  console.log('PASS: pareja/importación segura, renovación sin duplicados, refresco de consultas, reautorización 200, aviso transitorio y estado padre sin falsa conexión.');
} catch (error) {
  // Lo que lanza el código cargado con vm es de otro realm (no es `instanceof Error` aquí) y act() de React puede
  // agruparlo en un AggregateError: se imprime el stack de cada error igualmente.
  for (const e of [error, ...(Array.isArray(error?.errors) ? error.errors : [])]) console.error(e?.stack ?? e?.message ?? `Falló la prueba de conexión nube: ${String(e)}`);
  process.exitCode = 1;
} finally {
  cleanup();
  await window.happyDOM.close();
}
