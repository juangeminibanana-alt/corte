package app.creatorhub.web;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.view.HapticFeedbackConstants;
import android.view.View;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import app.creatorhub.BuildConfig;
import app.creatorhub.Nucleo;
import app.creatorhub.R;
import app.creatorhub.datos.CopiaSinConexion;
import app.creatorhub.red.ClienteHub;
import app.creatorhub.red.DescubrimientoLan;
import app.creatorhub.sistema.ProveedorArchivos;
import app.creatorhub.sistema.Recordatorios;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * `window.CreatorHubAndroid`: EXACTAMENTE PuenteAndroid de spec/ui_firmas/plataforma.d.ts (rev. 3.1; 04 §B.5;
 * BUILD_SPEC §7.4). Reglas: ningún método devuelve secretos (el token del hub solo vive en Java); cada uno comprueba
 * que la página actual sea el origen local; entradas validadas; resultados largos como CustomEvent (EventosAndroid).
 * `peticion()` solo admite POST /api/sync y POST /api/plantillas/{id}/restaurar. No hay reautorización desde el
 * celular (C35). Estos métodos corren en el hilo del puente de la WebView: nada de UI aquí sin runOnUiThread.
 */
public final class PuenteJs {
    /** Lo que el puente necesita de la actividad. */
    public interface Anfitrion {
        Activity actividad();
        WebView vista();
        /** URL de la página actual (para validar el origen). */
        String urlActual();
        /** La interfaz pintó su primera vista con datos: retirar el splash. */
        void interfazLista();
        /** El creatorhub://pair?… recibido de fuera y aún no usado ('' si no hay). */
        String consumirEnlace();
        void pedirPermisoNotificaciones(String idPedido);
    }

    static final String PAQUETE_TIKTOK = "com.zhiliaoapp.musically";
    /** Hosts permitidos para abrir fuera de la app (BUILD_SPEC §6.4; 03 §7.7). Solo https. */
    static final Set<String> HOSTS_PERMITIDOS = new HashSet<>(Arrays.asList(
            "shop.tiktok.com", "www.tiktok.com", "affiliate.tiktok.com", "seller-mx.tiktok.com", "partner.tiktokshop.com"));
    private static final Pattern ID_PEDIDO = Pattern.compile("[A-Za-z0-9_-]{1,64}");
    private static final Pattern RESTAURAR = Pattern.compile("/api/plantillas/[A-Za-z0-9_-]{1,64}/restaurar");
    private static final int TOPE_TEXTO = 100_000;

    private final Anfitrion a;
    private final Nucleo n;

    public PuenteJs(Anfitrion anfitrion, Nucleo nucleo) {
        this.a = anfitrion;
        this.n = nucleo;
    }

    private boolean permitido() {
        String u = a.urlActual();
        return u != null && u.startsWith(ServidorAssets.ORIGEN + "/");
    }

    private static boolean idValido(String id) { return id != null && ID_PEDIDO.matcher(id).matches(); }

    // ================================================================== PuenteAndroid (26 métodos)
    @JavascriptInterface public String version() {
        if (!permitido()) return "";
        return BuildConfig.VERSION_NAME;
    }

    /** JSON {app, sdk, modelo, webview, idioma}. */
    @JavascriptInterface public String info() {
        if (!permitido()) return "{}";
        JSONObject o = new JSONObject();
        try {
            PackageInfo wv = WebView.getCurrentWebViewPackage();
            o.put("app", BuildConfig.VERSION_NAME).put("sdk", Build.VERSION.SDK_INT)
             .put("modelo", Build.MANUFACTURER + " " + Build.MODEL)
             .put("webview", wv == null ? "desconocido" : wv.packageName + " " + wv.versionName)
             .put("idioma", Locale.getDefault().toLanguageTag());
        } catch (JSONException ignorada) { /* claves fijas */ }
        return o.toString();
    }

    /** JSON EstadoConexionPc (con sync_en_curso). */
    @JavascriptInterface public String estadoConexion() {
        if (!permitido()) return "{}";
        return n.estado().toString();
    }

    @JavascriptInterface public void emparejarQr(String texto, String idPedido) {
        if (!permitido() || !idValido(idPedido) || texto == null || texto.length() > 512) return;
        n.io.execute(() -> n.emparejador.conQr(texto, idPedido, d -> {
            n.emitir("creatorhub-emparejamiento", d);
            if ("aprobado".equals(d.optString("fase"))) alEmparejar();
        }));
    }

    @JavascriptInterface public void emparejarCodigo(String codigo, String ip, String idPedido) {
        if (!permitido() || !idValido(idPedido) || codigo == null || codigo.length() > 40 || (ip != null && ip.length() > 64)) return;
        n.io.execute(() -> n.emparejador.conCodigo(codigo, ip, idPedido, d -> {
            n.emitir("creatorhub-emparejamiento", d);
            if ("aprobado".equals(d.optString("fase"))) alEmparejar();
        }));
    }

    private void alEmparejar() {
        n.avisarConexion();
        n.io.execute(() -> { n.refrescarCopia(true); n.despertar(); });
    }

    @JavascriptInterface public void cancelarEmparejamiento(String idPedido) {
        if (!permitido() || !idValido(idPedido)) return;
        n.emparejador.cancelar(idPedido);
    }

    /** Descubrimiento UDP 39231 (1.5 s) → creatorhub-descubrimiento {id, pcs: PcEncontrada[]}. */
    @JavascriptInterface public void buscarPcs(String idPedido) {
        if (!permitido() || !idValido(idPedido)) return;
        n.io.execute(() -> {
            JSONArray pcs = new JSONArray();
            try {
                List<DescubrimientoLan.Pc> l = DescubrimientoLan.buscar(n.ctx, 1500, n.cliente.direcciones(), null);
                for (DescubrimientoLan.Pc pc : l) pcs.put(pc.aJson());
            } catch (IOException | JSONException e) {
                // sin red: lista vacía
            }
            try { n.emitir("creatorhub-descubrimiento", new JSONObject().put("id", idPedido).put("pcs", pcs)); }
            catch (JSONException ignorada) { /* claves fijas */ }
        });
    }

    /** Borra credencial, copia, cola e imágenes del celular. */
    @JavascriptInterface public boolean olvidarPc() {
        if (!permitido()) return false;
        n.olvidar();
        return true;
    }

    /** Copia + cola ahora (y POST /api/sync si toca) → creatorhub-actualizar {id, ok}. */
    @JavascriptInterface public void actualizarAhora(String idPedido) {
        if (!permitido() || !idValido(idPedido)) return;
        n.io.execute(() -> {
            boolean ok = n.actualizarAhora();
            try { n.emitir("creatorhub-actualizar", new JSONObject().put("id", idPedido).put("ok", ok)); }
            catch (JSONException ignorada) { /* claves fijas */ }
        });
    }

    /** JSON OpLocal[] → JSON {aceptadas}. Persiste en la cola ANTES de responder; luego intenta enviar. */
    @JavascriptInterface public String ops(String json) {
        if (!permitido() || json == null || json.length() > 2_000_000) return "{\"aceptadas\":0}";
        int aceptadas;
        try {
            aceptadas = n.cola.agregar(json);
        } catch (JSONException | IOException e) {
            aceptadas = 0;
        }
        n.avisarConexion();
        if (aceptadas > 0) n.io.execute(n::enviarCola);
        return "{\"aceptadas\":" + aceptadas + "}";
    }

    /** JSON OpLocal[] aún no confirmadas por el hub. */
    @JavascriptInterface public String opsPendientes() {
        if (!permitido()) return "[]";
        return n.cola.pendientes().toString();
    }

    /** Solo POST /api/sync y POST /api/plantillas/{id}/restaurar → creatorhub-respuesta {id, status, cuerpo}. */
    @JavascriptInterface public void peticion(String metodo, String ruta, String cuerpo, String idPedido) {
        if (!permitido() || !idValido(idPedido)) return;
        final boolean admitida = "POST".equals(metodo) && ruta != null
                && ("/api/sync".equals(ruta) || RESTAURAR.matcher(ruta).matches())
                && (cuerpo == null || cuerpo.length() <= 64 * 1024);
        n.io.execute(() -> {
            int status;
            String texto;
            if (!admitida) {
                status = 403;      // como el hub con lo que no va por la LAN (BUILD_SPEC §5: 403 solo_local)
                texto = errorJson("solo_local", "Esto solo se puede hacer desde Corte en tu PC.");
            } else if (!n.cliente.emparejado() || !n.cliente.conectado()) {
                status = 503;
                texto = errorJson("sin_internet", "Necesita tu PC encendida y en el mismo Wi‑Fi.");
            } else {
                try {
                    byte[] b = (cuerpo == null || cuerpo.isEmpty() ? "{}" : cuerpo).getBytes(StandardCharsets.UTF_8);
                    ClienteHub.Respuesta r = n.cliente.pedir(new ClienteHub.Peticion("POST", "/lan/v1" + ruta).cuerpo(b));
                    status = r.codigo;
                    texto = new String(r.cuerpo, StandardCharsets.UTF_8);
                    if ("/api/sync".equals(ruta) && (r.codigo == 202 || r.codigo == 200)) n.io.execute(() -> n.refrescarCopia(false));
                } catch (IOException e) {
                    n.cliente.marcarDesconectado();
                    status = 503;
                    texto = errorJson("sin_internet", "Necesita tu PC encendida y en el mismo Wi‑Fi.");
                }
            }
            try { n.emitir("creatorhub-respuesta", new JSONObject().put("id", idPedido).put("status", status).put("cuerpo", texto)); }
            catch (JSONException ignorada) { /* claves fijas */ }
        });
    }

    private static String errorJson(String codigo, String mensaje) {
        try {
            return new JSONObject().put("error", new JSONObject().put("codigo", codigo).put("mensaje", mensaje)).toString();
        } catch (JSONException e) {
            return "{}";
        }
    }

    /** Solo https y hosts de la lista (§6.4): ACTION_VIEW + CATEGORY_BROWSABLE (la toma la app de TikTok si existe). */
    @JavascriptInterface public boolean abrirExterno(String url) {
        if (!permitido()) return false;
        return abrirUrl(a.actividad(), url);
    }

    /** Abre la app de TikTok; si no está instalada, `urlRespaldo` (misma lista blanca). */
    @JavascriptInterface public boolean abrirTikTok(String urlRespaldo) {
        if (!permitido()) return false;
        Activity act = a.actividad();
        PackageManager pm = act.getPackageManager();
        Intent i = pm.getLaunchIntentForPackage(PAQUETE_TIKTOK);
        if (i != null) {
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            act.runOnUiThread(() -> {
                try { act.startActivity(i); } catch (ActivityNotFoundException ignorada) { /* desinstalada justo ahora */ }
            });
            return true;
        }
        return urlRespaldo != null && !urlRespaldo.isEmpty() && abrirUrl(act, urlRespaldo);
    }

    public static boolean urlPermitida(String url) {
        if (url == null || url.length() > 2048) return false;
        Uri u = Uri.parse(url);
        return "https".equalsIgnoreCase(u.getScheme()) && u.getHost() != null
                && HOSTS_PERMITIDOS.contains(u.getHost().toLowerCase(Locale.ROOT)) && u.getUserInfo() == null
                && (u.getPort() == -1 || u.getPort() == 443);
    }

    public static boolean abrirUrl(Activity act, String url) {
        if (!urlPermitida(url)) return false;
        Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(url)).addCategory(Intent.CATEGORY_BROWSABLE);
        act.runOnUiThread(() -> {
            try { act.startActivity(i); } catch (ActivityNotFoundException ignorada) { /* sin navegador */ }
        });
        return true;
    }

    @JavascriptInterface public boolean copiar(String texto) {
        if (!permitido() || texto == null || texto.length() > TOPE_TEXTO) return false;
        Activity act = a.actividad();
        act.runOnUiThread(() -> {
            ClipboardManager cm = act.getSystemService(ClipboardManager.class);
            if (cm != null) cm.setPrimaryClip(ClipData.newPlainText(act.getString(R.string.app_name), texto));
        });
        return true;
    }

    @JavascriptInterface public boolean compartir(String texto) {
        if (!permitido() || texto == null || texto.isEmpty() || texto.length() > TOPE_TEXTO) return false;
        Intent i = new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, texto);
        lanzarSelector(i);
        return true;
    }

    /** Comparte la imagen de la caché (`/img/p/<id>?v=…`) por el ContentProvider propio (C21). */
    @JavascriptInterface public boolean compartirImagen(String rutaImg, String titulo) {
        if (!permitido()) return false;
        String norm = CopiaSinConexion.normalizarImagen(rutaImg);
        if (norm == null) return false;
        n.io.execute(() -> {
            try {
                byte[] datos = null;
                String original = norm.contains("&t=") ? norm.substring(0, norm.indexOf("&t=")) : norm;
                if (n.cliente.conectado()) {      // primero la original de la PC; si no, la variante guardada
                    ClienteHub.Respuesta r = n.cliente.pedir(new ClienteHub.Peticion("GET", "/lan/v1" + original).limite(10L * 1024 * 1024));
                    if (r.codigo == 200) datos = r.cuerpo;
                }
                File f = null;
                if (datos == null) {
                    for (String alt : CopiaSinConexion.alternativas(norm)) {
                        f = n.copia.imagenEnCache(alt);
                        if (f != null) break;
                    }
                    if (f == null) return;
                    try (InputStream in = new FileInputStream(f)) { datos = leer(in, 10L * 1024 * 1024); }
                }
                String ext = extension(f != null ? CopiaSinConexion.mimeDe(f) : mimeDeBytes(datos));
                Uri uri = ProveedorArchivos.publicar(n.ctx, ProveedorArchivos.nombreSeguro(titulo, ext), datos);
                Intent i = new Intent(Intent.ACTION_SEND).setType("image/" + (ext.equals("jpg") ? "jpeg" : ext))
                        .putExtra(Intent.EXTRA_STREAM, uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                i.setClipData(ClipData.newRawUri(titulo == null ? "" : titulo, uri));
                lanzarSelector(i);
            } catch (IOException e) {
                // sin imagen disponible: no se abre el selector
            }
        });
        return true;
    }

    /** Comparte un CSV o JSON generado por la interfaz (Exportar CSV en Android = compartir el archivo). */
    @JavascriptInterface public boolean compartirArchivo(String nombre, String mime, String contenido) {
        if (!permitido() || contenido == null || contenido.length() > 5_000_000) return false;
        final String ext;
        if ("text/csv".equals(mime)) ext = "csv";
        else if ("application/json".equals(mime)) ext = "json";
        else return false;
        n.io.execute(() -> {
            try {
                Uri uri = ProveedorArchivos.publicar(n.ctx, ProveedorArchivos.nombreSeguro(nombre, ext),
                        contenido.getBytes(StandardCharsets.UTF_8));
                Intent i = new Intent(Intent.ACTION_SEND).setType(mime).putExtra(Intent.EXTRA_STREAM, uri)
                        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                i.setClipData(ClipData.newRawUri(nombre == null ? "" : nombre, uri));
                lanzarSelector(i);
            } catch (IOException e) {
                // no se pudo escribir: no se abre el selector
            }
        });
        return true;
    }

    private void lanzarSelector(Intent i) {
        Activity act = a.actividad();
        Intent selector = Intent.createChooser(i, act.getString(R.string.compartir_titulo));
        act.runOnUiThread(() -> {
            try { act.startActivity(selector); } catch (ActivityNotFoundException ignorada) { /* nada que lo reciba */ }
        });
    }

    /** FLAG_KEEP_SCREEN_ON (Sesión de videos). */
    @JavascriptInterface public void mantenerPantalla(boolean encendida) {
        if (!permitido()) return;
        Activity act = a.actividad();
        act.runOnUiThread(() -> {
            if (encendida) act.getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            else act.getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        });
    }

    /** 'confirmar' (CONFIRM) · 'tecla' (KEYBOARD_TAP) · 'umbral' (CLOCK_TICK). */
    @JavascriptInterface public void vibrar(String tipo) {
        if (!permitido() || tipo == null) return;
        final int efecto;
        switch (tipo) {
            case "confirmar": efecto = Build.VERSION.SDK_INT >= 30 ? HapticFeedbackConstants.CONFIRM : HapticFeedbackConstants.VIRTUAL_KEY; break;
            case "tecla": efecto = HapticFeedbackConstants.KEYBOARD_TAP; break;
            case "umbral": efecto = HapticFeedbackConstants.CLOCK_TICK; break;
            default: return;
        }
        WebView v = a.vista();
        if (v != null) v.post(() -> v.performHapticFeedback(efecto));
    }

    /** Íconos de las barras del sistema: claros con tema oscuro, oscuros con tema claro. */
    @JavascriptInterface public void tema(String modo) {
        if (!permitido() || !("claro".equals(modo) || "oscuro".equals(modo))) return;
        final boolean claro = "claro".equals(modo);
        Activity act = a.actividad();
        act.runOnUiThread(() -> aplicarTema(act, claro));
    }

    @SuppressWarnings("deprecation")
    static void aplicarTema(Activity act, boolean claro) {
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController c = act.getWindow().getInsetsController();
            if (c == null) return;
            int banderas = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
            c.setSystemBarsAppearance(claro ? banderas : 0, banderas);
        } else {
            View d = act.getWindow().getDecorView();
            int f = d.getSystemUiVisibility();
            int luz = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
            d.setSystemUiVisibility(claro ? (f | luz) : (f & ~luz));
        }
    }

    /** JSON NotificacionProgramada[]: reemplaza todo lo programado (AlarmManager). */
    @JavascriptInterface public void programarRecordatorios(String json) {
        if (!permitido() || json == null || json.length() > 200_000) return;
        n.io.execute(() -> {
            try { Recordatorios.programar(n.ctx, json); } catch (JSONException ignorada) { /* lista inválida: se ignora */ }
        });
    }

    /** 'concedido' | 'denegado' | 'no_aplica'. */
    @JavascriptInterface public String permisoNotificaciones() {
        if (!permitido()) return "denegado";
        return Recordatorios.permiso(n.ctx);
    }

    /** POST_NOTIFICATIONS (API 33+) → creatorhub-permiso {id, resultado}. */
    @JavascriptInterface public void pedirPermisoNotificaciones(String idPedido) {
        if (!permitido() || !idValido(idPedido)) return;
        a.pedirPermisoNotificaciones(idPedido);
    }

    /** El creatorhub://pair?… pendiente o "". Nunca empareja solo. */
    @JavascriptInterface public String consumirEnlace() {
        if (!permitido()) return "";
        return a.consumirEnlace();
    }

    /** La interfaz pintó su primera vista: se retira el splash. */
    @JavascriptInterface public void lista() {
        if (!permitido()) return;
        a.interfazLista();
    }

    // ================================================================== apoyo (sin @JavascriptInterface)
    private static byte[] leer(InputStream in, long limite) throws IOException {
        java.io.ByteArrayOutputStream b = new java.io.ByteArrayOutputStream();
        byte[] buf = new byte[16384];
        for (int r; (r = in.read(buf)) != -1; ) {
            if (b.size() + r > limite) throw new IOException("demasiado grande");
            b.write(buf, 0, r);
        }
        return b.toByteArray();
    }

    private static String mimeDeBytes(byte[] b) {
        if (b.length >= 12 && b[0] == 'R' && b[1] == 'I' && b[2] == 'F' && b[3] == 'F' && b[8] == 'W' && b[9] == 'E') return "image/webp";
        if (b.length >= 3 && (b[0] & 0xff) == 0xFF && (b[1] & 0xff) == 0xD8) return "image/jpeg";
        if (b.length >= 4 && (b[0] & 0xff) == 0x89 && b[1] == 'P' && b[2] == 'N' && b[3] == 'G') return "image/png";
        return "image/jpeg";
    }

    private static String extension(String mime) {
        switch (mime) {
            case "image/webp": return "webp";
            case "image/png": return "png";
            case "image/gif": return "gif";
            case "image/avif": return "avif";
            default: return "jpg";
        }
    }
}
