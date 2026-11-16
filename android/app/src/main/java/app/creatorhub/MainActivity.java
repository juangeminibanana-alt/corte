package app.creatorhub;

import android.Manifest;
import android.animation.ValueAnimator;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.ActivityManager;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.res.Configuration;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.Insets;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.view.View;
import android.view.ViewTreeObserver;
import android.view.WindowInsets;
import android.webkit.PermissionRequest;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.ValueCallback;
import android.window.OnBackInvokedCallback;
import android.window.OnBackInvokedDispatcher;
import app.creatorhub.red.PruebaDepuracion;
import app.creatorhub.sistema.Recordatorios;
import app.creatorhub.web.ProxyHub;
import app.creatorhub.web.PuenteJs;
import app.creatorhub.web.ServidorAssets;
import java.util.Locale;
import java.io.InputStream;
import java.io.IOException;
import java.util.regex.Pattern;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * Corte en Android (BUILD_SPEC §7.2; 04 §B.3–B.10; 02 §11.2): WebView de borde a borde con la interfaz servida desde
 * https://appassets.androidplatform.net, entorno nativo inyectado como variables CSS y atributos de &lt;html&gt;, splash
 * retenido hasta que la interfaz está lista (tope 3 s), Atrás → window.creatorHubBack(), onResume →
 * creatorhub-reanudar. El puente es PuenteJs; los datos pasan por ServidorAssets → ProxyHub.
 */
public final class MainActivity extends Activity implements Nucleo.Emisor, PuenteJs.Anfitrion {
    private static final int PEDIR_CAMARA = 41;
    private static final int PEDIR_NOTIFICACIONES = 42;
    private static final int ELEGIR_JSON = 43;
    private static final long TOPE_JSON = 20L * 1024 * 1024;
    private static final int WEBVIEW_MINIMA = 111;      // target de Vite (04 §B.10)
    private static final Pattern RUTA_HASH = Pattern.compile("#/[A-Za-z0-9/_.~?=&%-]{0,200}");

    private WebView web;
    private View raiz;
    private Nucleo nucleo;
    private ServidorAssets servidor;
    private volatile boolean interfazLista;
    private volatile String urlActual = "";
    private volatile String enlacePendiente;
    private volatile String idPermisoPendiente;
    private String rutaPendiente;
    private PermissionRequest permisoPendiente;
    private WindowInsets ultimosInsets;
    private Object callbackAtras;    // OnBackInvokedCallback (API 33+), guardado como Object para API 26
    private ValueCallback<Uri[]> archivoPendiente;

    @SuppressLint("SetJavaScriptEnabled")
    @Override protected void onCreate(Bundle estado) {
        super.onCreate(estado);
        nucleo = Nucleo.de(this);
        servidor = new ServidorAssets(getAssets(), new ProxyHub(nucleo));
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);

        // De borde a borde (obligatorio con targetSdk 35): la interfaz dibuja detrás de las barras.
        if (Build.VERSION.SDK_INT >= 30) getWindow().setDecorFitsSystemWindows(false);
        else marcarBordeABordeAntiguo();

        web = new WebView(this);
        web.setBackgroundColor(getColor(R.color.fondo));
        setContentView(web);

        // Splash: el primer cuadro se retiene hasta que la interfaz está lista (tope 3 s, 04 §B.10).
        raiz = findViewById(android.R.id.content);
        raiz.getViewTreeObserver().addOnPreDrawListener(new ViewTreeObserver.OnPreDrawListener() {
            @Override public boolean onPreDraw() {
                if (!interfazLista) return false;
                raiz.getViewTreeObserver().removeOnPreDrawListener(this);
                return true;
            }
        });
        raiz.postDelayed(this::marcarLista, 3000);

        web.setOnApplyWindowInsetsListener((v, insets) -> {
            ultimosInsets = insets;
            inyectarEntorno();
            return insets;
        });

        WebSettings w = web.getSettings();
        w.setJavaScriptEnabled(true);
        w.setDomStorageEnabled(true);
        w.setAllowFileAccess(false);
        w.setAllowContentAccess(false);
        w.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        w.setMediaPlaybackRequiresUserGesture(true);
        w.setSupportMultipleWindows(false);
        w.setJavaScriptCanOpenWindowsAutomatically(false);
        w.setGeolocationEnabled(false);
        w.setTextZoom(100);                       // la escala del sistema la aplica la interfaz con --fs
        w.setUserAgentString(w.getUserAgentString() + " CreatorHubAndroid/" + BuildConfig.VERSION_NAME);
        web.addJavascriptInterface(new PuenteJs(this, nucleo), "CreatorHubAndroid");

        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest pedido) {
                Uri u = pedido.getUrl();
                if (ServidorAssets.esLocal(u)) return false;
                if (pedido.isForMainFrame()) PuenteJs.abrirUrl(MainActivity.this, u.toString());   // solo hosts de §6.4
                return true;
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView v, WebResourceRequest pedido) {
                return servidor.interceptar(pedido.getMethod(), pedido.getUrl());
            }
            @Override public void onPageStarted(WebView v, String url, Bitmap icono) {
                urlActual = url == null ? "" : url;
            }
            @Override public void onPageCommitVisible(WebView v, String url) {
                inyectarEntorno();
            }
            @Override public void onPageFinished(WebView v, String url) {
                urlActual = url == null ? "" : url;
                inyectarEntorno();
                marcarLista();
                navegarPendiente();
                PruebaDepuracion.paginaLista(MainActivity.this, getIntent());
            }
            @Override public boolean onRenderProcessGone(WebView v, RenderProcessGoneDetail detalle) {
                if (web == v) { web = null; recreate(); }     // nunca dejar la actividad con una WebView muerta
                return true;
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView vista, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (archivoPendiente != null) devolverArchivo(archivoPendiente, null);
                archivoPendiente = callback;
                if (!ServidorAssets.esLocal(Uri.parse(urlActual)) || params.getMode() != FileChooserParams.MODE_OPEN) {
                    devolverArchivo(callback, null); return true;
                }
                Intent selector = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                        .setType("*/*").putExtra(Intent.EXTRA_MIME_TYPES,
                                new String[] { "application/json", "text/json", "text/plain", "application/octet-stream" })
                        .putExtra(Intent.EXTRA_ALLOW_MULTIPLE, false).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                try { startActivityForResult(selector, ELEGIR_JSON); }
                catch (ActivityNotFoundException e) { devolverArchivo(callback, null); }
                return true;
            }
            @Override public void onPermissionRequest(PermissionRequest pedido) {
                runOnUiThread(() -> decidirPermiso(pedido));
            }
            @Override public void onPermissionRequestCanceled(PermissionRequest pedido) {
                if (pedido == permisoPendiente) permisoPendiente = null;
            }
        });

        if (Build.VERSION.SDK_INT >= 33) {
            OnBackInvokedCallback cb = this::manejarAtras;
            callbackAtras = cb;
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT, cb);
        }

        nucleo.fijarEmisor(this);
        capturarEnlace(getIntent());
        capturarRuta(getIntent());
        if (PruebaDepuracion.alCrear(this, nucleo, getIntent())) return;   // solo app.creatorhub.dev con ch_prueba_tls
        avisarSiWebViewVieja();
        web.loadUrl(ServidorAssets.ORIGEN + "/index.html");
    }

    @SuppressWarnings("deprecation")
    private void marcarBordeABordeAntiguo() {
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
    }

    private void marcarLista() {
        if (interfazLista) return;
        interfazLista = true;
        if (raiz != null) raiz.invalidate();
    }

    // ------------------------------------------------------------------ entorno (02 §11.2 con C48)
    /**
     * Escribe en &lt;html&gt;: --native-inset-top/right/bottom/left y --native-ime (px CSS), --fs (escala de texto,
     * tope 2.0), data-platform="android", data-glass="on" solo si el equipo es capaz (sin pisar un "off" que haya
     * puesto el vigilante de cuadros) y SOLO el dato del sistema data-system-reduced-motion. La decisión de reducir el
     * movimiento (y el atributo que la refleja) es de la interfaz (BUILD_SPEC §8.4, C48).
     */
    @SuppressWarnings("deprecation")
    void inyectarEntorno() {
        if (web == null) return;
        float d = getResources().getDisplayMetrics().density;
        int t = 0, b = 0, l = 0, r = 0, ime = 0;
        WindowInsets in = ultimosInsets;
        if (in != null) {
            if (Build.VERSION.SDK_INT >= 30) {
                Insets s = in.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                ime = in.getInsets(WindowInsets.Type.ime()).bottom;
                t = s.top; b = s.bottom; l = s.left; r = s.right;
            } else {
                t = in.getSystemWindowInsetTop(); b = in.getSystemWindowInsetBottom();
                l = in.getSystemWindowInsetLeft(); r = in.getSystemWindowInsetRight();
            }
        }
        float fs = Math.min(getResources().getConfiguration().fontScale, 2.0f);
        boolean vidrio = equipoCapaz();
        boolean sinAnimaciones = !ValueAnimator.areAnimatorsEnabled();
        web.evaluateJavascript(String.format(Locale.US,
                "(function(e){if(!e)return;var s=e.style;"
                + "s.setProperty('--native-inset-top','%.1fpx');s.setProperty('--native-inset-right','%.1fpx');"
                + "s.setProperty('--native-inset-bottom','%.1fpx');s.setProperty('--native-inset-left','%.1fpx');"
                + "s.setProperty('--native-ime','%.1fpx');s.setProperty('--fs','%.2f');"
                + "e.setAttribute('data-platform','android');"
                + "if(%b&&e.getAttribute('data-glass')!=='off')e.setAttribute('data-glass','on');"
                + "e.toggleAttribute('data-system-reduced-motion',%b);"
                + "})(document.documentElement)",
                t / d, r / d, b / d, l / d, ime / d, fs, vidrio, sinAnimaciones), null);
    }

    /** 02 §11.2: Media Performance Class ≥ S, o ≥ 6 GB de RAM sin ser equipo de poca memoria. */
    private boolean equipoCapaz() {
        ActivityManager am = getSystemService(ActivityManager.class);
        if (am == null) return false;
        ActivityManager.MemoryInfo mi = new ActivityManager.MemoryInfo();
        am.getMemoryInfo(mi);
        return (Build.VERSION.SDK_INT >= 31 && Build.VERSION.MEDIA_PERFORMANCE_CLASS >= Build.VERSION_CODES.S)
                || (mi.totalMem >= 6L * 1024 * 1024 * 1024 && !am.isLowRamDevice());
    }

    @Override public void onConfigurationChanged(Configuration nueva) {
        super.onConfigurationChanged(nueva);
        inyectarEntorno();
    }

    // ------------------------------------------------------------------ ciclo de vida
    @Override protected void onResume() {
        super.onResume();
        nucleo.fijarEmisor(this);
        nucleo.alFrente(true);
        emitir("creatorhub-reanudar", new JSONObject());
        inyectarEntorno();          // la escala de texto o las animaciones pudieron cambiar en Ajustes
    }

    @Override protected void onPause() {
        nucleo.alFrente(false);
        super.onPause();
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if (capturarEnlace(intent)) {
            try { emitir("creatorhub-enlace", new JSONObject().put("url", enlacePendiente)); }
            catch (JSONException ignorada) { /* clave fija */ }
        }
        capturarRuta(intent);
        if (interfazLista) navegarPendiente();
    }

    @Override protected void onDestroy() {
        if (archivoPendiente != null) devolverArchivo(archivoPendiente, null);
        if (Build.VERSION.SDK_INT >= 33 && callbackAtras != null) {
            getOnBackInvokedDispatcher().unregisterOnBackInvokedCallback((OnBackInvokedCallback) callbackAtras);
        }
        nucleo.quitarEmisor(this);
        if (web != null) { web.destroy(); web = null; }
        super.onDestroy();
    }

    @SuppressWarnings("deprecation")
    @Override protected void onActivityResult(int codigo, int resultado, Intent datos) {
        super.onActivityResult(codigo, resultado, datos);
        if (codigo != ELEGIR_JSON || archivoPendiente == null) return;
        final ValueCallback<Uri[]> callback = archivoPendiente;
        final Uri uri = resultado == RESULT_OK && datos != null ? datos.getData() : null;
        if (uri == null) { devolverArchivo(callback, null); return; }
        nucleo.io.execute(() -> {
            boolean valido = false;
            try { valido = jsonPermitido(uri); } catch (IOException | RuntimeException e) { /* no se registra el archivo */ }
            final boolean aceptado = valido;
            runOnUiThread(() -> {
                devolverArchivo(callback, aceptado && !isFinishing() ? new Uri[] { uri } : null);
                if (!aceptado && !isFinishing()) android.widget.Toast.makeText(this,
                        "Elige un archivo JSON de hasta 20 MB.", android.widget.Toast.LENGTH_LONG).show();
            });
        });
    }

    private void devolverArchivo(ValueCallback<Uri[]> callback, Uri[] archivos) {
        if (archivoPendiente != callback) return;
        archivoPendiente = null;
        callback.onReceiveValue(archivos);
    }

    private boolean jsonPermitido(Uri uri) throws IOException {
        if (!"content".equals(uri.getScheme())) return false;
        String nombre = null;
        try (Cursor c = getContentResolver().query(uri, new String[] { OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE }, null, null, null)) {
            if (c != null && c.moveToFirst()) {
                int n = c.getColumnIndex(OpenableColumns.DISPLAY_NAME), tam = c.getColumnIndex(OpenableColumns.SIZE);
                if (n >= 0) nombre = c.getString(n);
                if (tam >= 0 && !c.isNull(tam) && c.getLong(tam) > TOPE_JSON) return false;
            }
        }
        if (nombre == null || !nombre.toLowerCase(Locale.ROOT).endsWith(".json")) return false;
        // El proveedor puede omitir o falsear SIZE: comprobar el límite leyendo en bloques, sin guardar su contenido.
        try (InputStream in = getContentResolver().openInputStream(uri)) {
            if (in == null) return false;
            byte[] buffer = new byte[8192]; long total = 0;
            for (int n; (n = in.read(buffer)) != -1;) { total += n; if (total > TOPE_JSON) return false; }
        }
        return true;
    }

    // ------------------------------------------------------------------ eventos hacia la interfaz
    /** window.dispatchEvent(new CustomEvent(evento, {detail})) solo si la página es la del origen local. */
    @Override public void emitir(String evento, JSONObject detalle) {
        final String js = "window.dispatchEvent(new CustomEvent(" + JSONObject.quote(evento) + ",{detail:" + detalle + "}))";
        runOnUiThread(() -> {
            if (web != null && !isFinishing() && urlActual.startsWith(ServidorAssets.ORIGEN + "/")) {
                web.evaluateJavascript(js, null);
            }
        });
    }

    // ------------------------------------------------------------------ PuenteJs.Anfitrion
    @Override public Activity actividad() { return this; }
    @Override public WebView vista() { return web; }
    @Override public String urlActual() { return urlActual; }
    @Override public void interfazLista() { runOnUiThread(this::marcarLista); }

    @Override public String consumirEnlace() {
        String e = enlacePendiente;
        enlacePendiente = null;
        return e == null ? "" : e;
    }

    @Override public void pedirPermisoNotificaciones(String idPedido) {
        runOnUiThread(() -> {
            if (Build.VERSION.SDK_INT < 33
                    || checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) {
                responderPermiso(idPedido, Recordatorios.permiso(this));
                return;
            }
            idPermisoPendiente = idPedido;
            requestPermissions(new String[] {Manifest.permission.POST_NOTIFICATIONS}, PEDIR_NOTIFICACIONES);
        });
    }

    private void responderPermiso(String id, String resultado) {
        try { emitir("creatorhub-permiso", new JSONObject().put("id", id).put("resultado", resultado)); }
        catch (JSONException ignorada) { /* claves fijas */ }
    }

    // ------------------------------------------------------------------ enlaces y rutas
    /** creatorhub://pair?… (≤ 512 caracteres). Devuelve true si quedó pendiente. Nunca empareja solo. */
    private boolean capturarEnlace(Intent intent) {
        Uri u = intent == null ? null : intent.getData();
        if (u != null && "creatorhub".equals(u.getScheme()) && "pair".equals(u.getHost()) && u.toString().length() <= 512) {
            enlacePendiente = u.toString();
            return true;
        }
        return false;
    }

    /** Toque en una notificación: la ruta hash que se abre ('#/muestras/sesion'). */
    private void capturarRuta(Intent intent) {
        String r = intent == null ? null : intent.getStringExtra(Recordatorios.EXTRA_RUTA);
        if (r != null && RUTA_HASH.matcher(r).matches()) rutaPendiente = r;
    }

    private void navegarPendiente() {
        String r = rutaPendiente;
        rutaPendiente = null;
        if (r != null && web != null) web.evaluateJavascript("location.hash=" + JSONObject.quote(r), null);
    }

    // ------------------------------------------------------------------ Atrás
    private void manejarAtras() {
        if (web == null) { moveTaskToBack(true); return; }
        web.evaluateJavascript("Boolean(window.creatorHubBack && window.creatorHubBack())", v -> {
            if (!"true".equals(v)) moveTaskToBack(true);
        });
    }

    @SuppressWarnings("deprecation")
    @Override public void onBackPressed() { manejarAtras(); } // Android 8–12

    // ------------------------------------------------------------------ permisos
    private void decidirPermiso(PermissionRequest pedido) {
        boolean soloCamara = pedido.getResources().length > 0;
        for (String r : pedido.getResources()) {
            if (!PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(r)) soloCamara = false;
        }
        Uri o = pedido.getOrigin();
        if (!soloCamara || o == null || !ServidorAssets.esLocal(o)) { pedido.deny(); return; }
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            pedido.grant(new String[] {PermissionRequest.RESOURCE_VIDEO_CAPTURE});
            return;
        }
        if (permisoPendiente != null) permisoPendiente.deny();
        permisoPendiente = pedido;
        requestPermissions(new String[] {Manifest.permission.CAMERA}, PEDIR_CAMARA);
    }

    @Override public void onRequestPermissionsResult(int codigo, String[] permisos, int[] resultados) {
        super.onRequestPermissionsResult(codigo, permisos, resultados);
        boolean concedido = resultados.length > 0 && resultados[0] == PackageManager.PERMISSION_GRANTED;
        if (codigo == PEDIR_CAMARA && permisoPendiente != null) {
            if (concedido) permisoPendiente.grant(new String[] {PermissionRequest.RESOURCE_VIDEO_CAPTURE});
            else permisoPendiente.deny();
            permisoPendiente = null;
        } else if (codigo == PEDIR_NOTIFICACIONES && idPermisoPendiente != null) {
            responderPermiso(idPermisoPendiente, concedido ? "concedido" : "denegado");
            idPermisoPendiente = null;
        }
    }

    // ------------------------------------------------------------------ WebView mínima
    private void avisarSiWebViewVieja() {
        PackageInfo wv = WebView.getCurrentWebViewPackage();
        if (wv == null || wv.versionName == null) return;
        int mayor;
        try { mayor = Integer.parseInt(wv.versionName.split("\\.")[0]); } catch (NumberFormatException e) { return; }
        if (mayor >= WEBVIEW_MINIMA) return;
        final String paquete = wv.packageName;
        new AlertDialog.Builder(this)
                .setTitle(R.string.webview_vieja_titulo)
                .setMessage(R.string.webview_vieja_texto)
                .setPositiveButton(R.string.webview_vieja_si, (dlg, i) -> {
                    try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=" + paquete))); }
                    catch (ActivityNotFoundException e) {
                        try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse("https://play.google.com/store/apps/details?id=" + paquete))); }
                        catch (ActivityNotFoundException ignorada) { /* sin tienda ni navegador */ }
                    }
                })
                .setNegativeButton(R.string.webview_vieja_no, null)
                .show();
    }
}
