package app.creatorhub.web;

import android.content.res.AssetManager;
import android.net.Uri;
import android.webkit.MimeTypeMap;
import android.webkit.WebResourceResponse;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/**
 * shouldInterceptRequest de la WebView (04 §B.3; BUILD_SPEC §6.4):
 * - la interfaz se sirve desde assets/web bajo https://appassets.androidplatform.net (sin file://);
 * - `/` → index.html; ruta sin extensión (enrutador de la SPA) → index.html; rechaza `..`, `\0` y `\`; el resto 404;
 * - MIME propio; `/assets/*` inmutable un año; index.html no-store; siempre nosniff y Referrer-Policy no-referrer;
 * - la CSP de Android va como CABECERA HTTP de cada respuesta HTML (nunca en un meta);
 * - `/api/*` e `/img/*` los atiende ProxyHub (hub firmado o copia);
 * - TODO lo que no sea el origen local responde 403 nativo: nada sale a internet desde la WebView.
 */
public final class ServidorAssets {
    public static final String HOST = "appassets.androidplatform.net";
    public static final String ORIGEN = "https://" + HOST;
    /** CSP única (§6.4), variante Android: frame-src 'none' y media-src para la cámara del QR. */
    public static final String CSP = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            + "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; worker-src 'self' blob:; "
            + "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; "
            + "frame-src 'none'; media-src 'self' blob: mediastream:";

    private final AssetManager assets;
    private final ProxyHub proxy;

    public ServidorAssets(AssetManager assets, ProxyHub proxy) {
        this.assets = assets;
        this.proxy = proxy;
    }

    public static boolean esLocal(Uri u) {
        return u != null && "https".equalsIgnoreCase(u.getScheme()) && HOST.equalsIgnoreCase(u.getHost())
                && (u.getPort() == -1 || u.getPort() == 443);
    }

    /** Nunca devuelve null: todo lo que pide la WebView pasa por aquí. */
    public WebResourceResponse interceptar(String metodo, Uri u) {
        if (!esLocal(u)) return vacio(403, "Forbidden");                 // nada sale a internet desde la WebView
        String ruta = u.getPath();
        if (ruta == null || ruta.isEmpty() || "/".equals(ruta)) ruta = "/index.html";
        if (ruta.contains("..") || ruta.indexOf('\0') >= 0 || ruta.indexOf('\\') >= 0) return vacio(400, "Bad Request");
        if (ruta.startsWith("/api/") || ruta.startsWith("/img/")) return proxy.atender(metodo, u);
        if (!"GET".equals(metodo) && !"HEAD".equals(metodo)) return vacio(405, "Method Not Allowed");
        try {
            return respuesta(mime(ruta), assets.open("web" + ruta), ruta);
        } catch (IOException noExiste) {
            boolean sinExtension = ruta.lastIndexOf('.') <= ruta.lastIndexOf('/');
            if (sinExtension) {                                           // rutas del enrutador de la SPA
                try { return respuesta("text/html", assets.open("web/index.html"), "/index.html"); }
                catch (IOException ignorado) { /* sin interfaz empaquetada */ }
            }
            return vacio(404, "Not Found");
        }
    }

    static WebResourceResponse respuesta(String tipo, InputStream datos, String ruta) {
        Map<String, String> h = new HashMap<>();
        if (ruta.startsWith("/assets/")) h.put("Cache-Control", "public, max-age=31536000, immutable");
        else if (tipo.startsWith("text/html")) h.put("Cache-Control", "no-store");
        else h.put("Cache-Control", "no-cache");
        h.put("X-Content-Type-Options", "nosniff");
        h.put("Referrer-Policy", "no-referrer");
        if (tipo.startsWith("text/html")) h.put("Content-Security-Policy", CSP);
        boolean texto = tipo.startsWith("text/") || tipo.contains("json") || tipo.contains("javascript") || tipo.contains("svg");
        return new WebResourceResponse(tipo, texto ? "UTF-8" : null, 200, "OK", h, datos);
    }

    static WebResourceResponse vacio(int codigo, String razon) {
        Map<String, String> h = new HashMap<>();
        h.put("Cache-Control", "no-store");
        h.put("X-Content-Type-Options", "nosniff");
        return new WebResourceResponse("text/plain", "UTF-8", codigo, razon, h, new ByteArrayInputStream(new byte[0]));
    }

    static WebResourceResponse json(int codigo, String razon, String cuerpo, Map<String, String> extra) {
        Map<String, String> h = new HashMap<>();
        h.put("Cache-Control", "no-store");
        h.put("X-Content-Type-Options", "nosniff");
        if (extra != null) h.putAll(extra);
        return new WebResourceResponse("application/json", "UTF-8", codigo, razon, h,
                new ByteArrayInputStream(cuerpo.getBytes(StandardCharsets.UTF_8)));
    }

    public static String mime(String nombre) {
        String ext = nombre.substring(nombre.lastIndexOf('.') + 1).toLowerCase(Locale.ROOT);
        switch (ext) {
            case "html": return "text/html";
            case "js": case "mjs": return "text/javascript";
            case "css": return "text/css";
            case "json": case "webmanifest": return "application/json";
            case "svg": return "image/svg+xml";
            case "webp": return "image/webp";
            case "avif": return "image/avif";
            case "png": return "image/png";
            case "jpg": case "jpeg": return "image/jpeg";
            case "woff2": return "font/woff2";
            case "wasm": return "application/wasm";
            case "txt": return "text/plain";
            default:
                String m = MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext);
                return m != null ? m : "application/octet-stream";
        }
    }
}
