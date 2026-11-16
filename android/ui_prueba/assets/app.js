/* Interfaz de prueba de android-shell (solo -PchUiDist=../ui_prueba). Dos cosas:
 *  1) botones mínimos para probar a mano el puente con un hub real (emparejar, actualizar, buscar, olvidar);
 *  2) una autoprueba al cargar que deja su resultado en window.__corteResultado (la lee la variante de depuración con
 *     el extra ch_prueba_web y la escribe en logcat con la etiqueta CorteWeb).
 * Nunca escribe data-reduced-motion: eso lo decide la interfaz real; aquí solo se comprueba que Java no lo ponga. */
'use strict';

var METODOS = ['version', 'info', 'estadoConexion', 'emparejarQr', 'emparejarCodigo', 'cancelarEmparejamiento',
  'buscarPcs', 'olvidarPc', 'actualizarAhora', 'ops', 'opsPendientes', 'peticion', 'abrirExterno', 'abrirTikTok',
  'copiar', 'compartir', 'compartirImagen', 'compartirArchivo', 'mantenerPantalla', 'vibrar', 'tema',
  'programarRecordatorios', 'permisoNotificaciones', 'pedirPermisoNotificaciones', 'consumirEnlace', 'lista'];
var CLAVES_ESTADO = ['emparejado', 'host_id', 'nombre_equipo', 'conectado', 'ip', 'ultima_copia_at',
  'cambios_pendientes', 'permisos', 'revocado', 'incompatible', 'sync_en_curso'];
var CSP_ANDROID = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; " +
  "font-src 'self'; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'none'; " +
  "frame-ancestors 'none'; frame-src 'none'; media-src 'self' blob: mediastream:";

var P = window.CreatorHubAndroid;
var $ = function (id) { return document.getElementById(id); };
var contador = 0;
function nuevoId(prefijo) { contador += 1; return prefijo + '-' + Date.now().toString(36) + '-' + contador; }

/** Espera el CustomEvent nativo `nombre` cuyo detail.id coincide (o el primero si id es null). */
function esperarEvento(nombre, id, ms) {
  return new Promise(function (listo) {
    var t = setTimeout(function () { window.removeEventListener(nombre, f); listo(null); }, ms);
    function f(e) {
      if (id !== null && (!e.detail || e.detail.id !== id)) return;
      clearTimeout(t); window.removeEventListener(nombre, f); listo(e.detail);
    }
    window.addEventListener(nombre, f);
  });
}

function pintarEstado() {
  if (!P) { $('estado').textContent = 'Sin puente nativo (no es la app de Android).'; return; }
  try { $('estado').textContent = JSON.stringify(JSON.parse(P.estadoConexion()), null, 2); }
  catch (e) { $('estado').textContent = 'Error: ' + e; }
}

function enlazarBotones() {
  if (!P) return;
  window.addEventListener('creatorhub-conexion', pintarEstado);
  window.addEventListener('creatorhub-copia', pintarEstado);
  window.addEventListener('creatorhub-emparejamiento', function (e) { $('emparejamiento').textContent = JSON.stringify(e.detail, null, 2); pintarEstado(); });
  $('actualizar').onclick = function () { P.actualizarAhora(nuevoId('act')); };
  $('buscar').onclick = function () {
    var id = nuevoId('buscar');
    esperarEvento('creatorhub-descubrimiento', id, 4000).then(function (d) { $('emparejamiento').textContent = JSON.stringify(d, null, 2); });
    P.buscarPcs(id);
  };
  $('olvidar').onclick = function () { P.olvidarPc(); pintarEstado(); };
  $('emparejar-qr').onclick = function () { P.emparejarQr($('qr').value, nuevoId('qr')); };
  $('emparejar-codigo').onclick = function () { P.emparejarCodigo($('codigo').value, $('ip').value, nuevoId('codigo')); };
  window.creatorHubBack = function () { return false; };
}

async function autoprueba() {
  var r = { fallas: [] };
  function revisar(nombre, bien, valor) { r[nombre] = valor === undefined ? bien : valor; if (!bien) r.fallas.push(nombre); }
  var html = document.documentElement;

  // --- puente: exactamente los 26 métodos de PuenteAndroid
  revisar('puente_presente', !!P);
  if (P) {
    var faltan = METODOS.filter(function (m) { return typeof P[m] !== 'function'; });
    revisar('puente_metodos', faltan.length === 0, faltan.length === 0 ? METODOS.length : 'faltan ' + faltan.join(','));
    var enumerables = [];
    for (var k in P) { enumerables.push(k); }
    var extra = enumerables.filter(function (m) { return METODOS.indexOf(m) < 0; });
    // Si la WebView enumera el objeto del puente, el conjunto debe ser EXACTO; si no enumera nada, se informa.
    revisar('puente_enumerado', enumerables.length === 0 || (extra.length === 0 && enumerables.length === METODOS.length),
      enumerables.length === 0 ? 'no enumerable' : (extra.length ? 'sobran ' + extra.join(',') : enumerables.length + ' exactos'));
    revisar('puente_no_hay_extra', typeof P.probarAlmacen === 'undefined' && typeof P.probarHub === 'undefined' && typeof P.descubrir === 'undefined');

    var est = JSON.parse(P.estadoConexion());
    var claves = Object.keys(est).sort();
    revisar('estado_conexion', JSON.stringify(claves) === JSON.stringify(CLAVES_ESTADO.slice().sort()), claves.join(','));
    revisar('estado_sync_en_curso_bool', typeof est.sync_en_curso === 'boolean');
    var info = JSON.parse(P.info());
    revisar('info', ['app', 'sdk', 'modelo', 'webview', 'idioma'].every(function (c) { return c in info; }), info.webview);
    revisar('version', /^\d+\.\d+\.\d+/.test(P.version()), P.version());
    revisar('permiso_notificaciones', ['concedido', 'denegado', 'no_aplica'].indexOf(P.permisoNotificaciones()) >= 0, P.permisoNotificaciones());
    var enlace = P.consumirEnlace();
    revisar('enlace_pendiente', enlace.indexOf('creatorhub://pair?') === 0, enlace);
    revisar('enlace_consumido', P.consumirEnlace() === '');

    // cola: ops → {aceptadas}, opsPendientes, olvidarPc la borra
    var acep = JSON.parse(P.ops(JSON.stringify([{ op_id: 'ui-1', tipo: 'nota.crear', datos: { id: 'n-ui', texto: 'prueba' } },
      { op_id: 'ui-x', tipo: 'no.existe' }])));
    revisar('ops_aceptadas', acep.aceptadas === 1, acep.aceptadas);
    revisar('ops_pendientes', JSON.parse(P.opsPendientes()).length === 1);
    revisar('olvidar', P.olvidarPc() === true && JSON.parse(P.opsPendientes()).length === 0);

    // peticion: solo POST /api/sync y restaurar plantilla; lo demás 403; sin PC 503
    var id1 = nuevoId('pet'), id2 = nuevoId('pet'), id3 = nuevoId('pet');
    var e1 = esperarEvento('creatorhub-respuesta', id1, 5000), e2 = esperarEvento('creatorhub-respuesta', id2, 5000),
      e3 = esperarEvento('creatorhub-respuesta', id3, 5000);
    P.peticion('POST', '/api/datos/borrar', '{"alcance":"todo","confirmacion":"BORRAR"}', id1);
    P.peticion('POST', '/api/sync', '{}', id2);
    P.peticion('POST', '/api/plantillas/disculpa_y_fecha/restaurar', '', id3);
    var d1 = await e1, d2 = await e2, d3 = await e3;
    var c1 = null;
    try { c1 = d1 ? JSON.parse(d1.cuerpo).error.codigo : null; } catch (e) { c1 = 'ilegible'; }
    revisar('peticion_prohibida', !!d1 && d1.status === 403 && c1 === 'solo_local', d1 && (d1.status + ' ' + c1));
    revisar('peticion_sync_sin_pc', !!d2 && d2.status === 503, d2 && d2.status);
    revisar('peticion_restaurar_sin_pc', !!d3 && d3.status === 503, d3 && d3.status);

    // eventos con idPedido
    var idb = nuevoId('buscar');
    var eb = esperarEvento('creatorhub-descubrimiento', idb, 5000);
    P.buscarPcs(idb);
    var db = await eb;
    revisar('buscar_pcs_evento', !!db && Array.isArray(db.pcs), db ? db.pcs.length + ' pc' : 'sin evento');
    var ida = nuevoId('act');
    var ea = esperarEvento('creatorhub-actualizar', ida, 8000);
    P.actualizarAhora(ida);
    var da = await ea;
    revisar('actualizar_evento', !!da && da.ok === false, da && da.ok);
    var ide = nuevoId('emp');
    var ee = esperarEvento('creatorhub-emparejamiento', ide, 5000);
    // QR inválido → fase error qr_invalido (el primer evento es 'conectando')
    var errQr = new Promise(function (listo) {
      var t = setTimeout(function () { listo(null); }, 6000);
      window.addEventListener('creatorhub-emparejamiento', function f(e) {
        if (e.detail && e.detail.id === ide && e.detail.fase === 'error') { clearTimeout(t); window.removeEventListener('creatorhub-emparejamiento', f); listo(e.detail); }
      });
    });
    P.emparejarQr('creatorhub://pair?v=1&h=zz', ide);
    var primero = await ee, error = await errQr;
    revisar('emparejar_qr_invalido', !!primero && primero.fase === 'conectando' && !!error && error.error === 'qr_invalido' && !!error.mensaje,
      error && (error.error + ': ' + error.mensaje));
    P.programarRecordatorios(JSON.stringify([{ id: 'prueba-1', titulo: 'Graba tu video', texto: 'Hoy toca un video.',
      at: Math.floor(Date.now() / 1000) + 3600, ruta: '#/muestras' }]));
    revisar('abrir_externo_no_permitido', P.abrirExterno('https://example.com/') === false);
    revisar('abrir_externo_http', P.abrirExterno('http://www.tiktok.com/') === false);
  }

  // --- entorno de <html> (02 §11.2 con C48)
  var estilo = html.style;
  revisar('data_platform', html.getAttribute('data-platform') === 'android', html.getAttribute('data-platform'));
  revisar('native_inset_top', /px$/.test(estilo.getPropertyValue('--native-inset-top')), estilo.getPropertyValue('--native-inset-top'));
  revisar('native_ime', /px$/.test(estilo.getPropertyValue('--native-ime')), estilo.getPropertyValue('--native-ime'));
  revisar('fs', /^\d+\.\d\d$/.test(estilo.getPropertyValue('--fs').trim()), estilo.getPropertyValue('--fs'));
  r.data_glass = html.getAttribute('data-glass');
  r.data_system_reduced_motion = html.hasAttribute('data-system-reduced-motion');
  revisar('sin_data_reduced_motion', !html.hasAttribute('data-reduced-motion'));
  revisar('sin_data_motion', !html.hasAttribute('data-motion'));

  // --- servidor: CSP como cabecera, nada externo, proxy sin conexión
  try {
    var ri = await fetch('/index.html', { cache: 'no-store' });
    revisar('csp_cabecera', ri.headers.get('content-security-policy') === CSP_ANDROID, ri.headers.get('content-security-policy'));
    revisar('csp_no_meta', !document.querySelector('meta[http-equiv="Content-Security-Policy" i]'));
  } catch (e) { revisar('csp_cabecera', false, String(e)); }
  try { await fetch('https://example.com/'); revisar('externo_bloqueado', false, 'pasó'); }
  catch (e) { revisar('externo_bloqueado', true, 'bloqueado'); }
  try {
    var ra = await fetch('/api/session');
    var cuerpo = await ra.json();
    revisar('api_sin_conexion', ra.status === 503 && ra.headers.get('x-ch-fuente') === 'sin_conexion' && !!cuerpo.error,
      ra.status + ' ' + ra.headers.get('x-ch-fuente') + ' ' + (cuerpo.error && cuerpo.error.codigo));
    var rs = await fetch('/api/snapshot');
    revisar('snapshot_sin_copia', rs.status === 503, rs.status);
  } catch (e) { revisar('api_sin_conexion', false, String(e)); }

  r.resultado = r.fallas.length === 0 ? 'ok' : 'FALLA';
  return r;
}

document.addEventListener('DOMContentLoaded', function () {
  pintarEstado();
  enlazarBotones();
  if (P) P.lista();
  autoprueba().then(function (r) {
    window.__corteResultado = r;
    $('autoprueba').textContent = JSON.stringify(r, null, 2);
  }, function (e) {
    window.__corteResultado = { resultado: 'FALLA', excepcion: String(e && e.stack || e) };
    $('autoprueba').textContent = String(e);
  });
});
