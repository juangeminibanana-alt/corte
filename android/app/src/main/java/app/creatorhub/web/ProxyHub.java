package app.creatorhub.web;

import android.net.Uri;
import android.webkit.WebResourceResponse;
import app.creatorhub.Nucleo;
import app.creatorhub.datos.CopiaSinConexion;
import app.creatorhub.red.ClienteHub;
import app.creatorhub.red.PoliticaCacheImagenes;
import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * `/api/*` (GET) e `/img/*` de la interfaz (04 §B.4; contrato.ts: "la capa nativa intercepta '/api/*' e '/img/*'"):
 * - con conexión: `https://<ip>:<puerto>/lan/v1/api/...` con TLS fijado y CH1, conexión 4 s y lectura 15 s →
 *   estado, tipo y cuerpo tal cual + `X-CH-Fuente: hub`;
 * - `/api/snapshot`: la copia local (`files/copia/snapshot.json.gz`), `X-CH-Fuente: copia` + `X-CH-Copia-At`;
 * - sin conexión, el resto: 503 con ErrorRespuesta y `X-CH-Fuente: sin_conexion` (la interfaz usa deCopia());
 * - imágenes versionadas (`?v=` distinto de 0): caché `files/img` inmutable; sin conexión se sirve otra variante
 *   guardada de la misma versión; `?v=0` nunca se guarda (C45). Claves aceptadas (CopiaSinConexion.normalizarImagen):
 *   `p` producto, `a` cuenta, desde la rev. 4 (15/11) `g` galería de la vitrina (`/img/g/<product_id>-<n>`) y `m`
 *   producto parecido del marketplace (`/img/m/<product_id>`), y desde la rev. 5 (15/11) `v` portada real del video de
 *   la Display API (`/img/v/<content_id>`, antes reservada).
 * Las escrituras no pasan por aquí (shouldInterceptRequest no da el cuerpo): van por el puente (ops / peticion).
 */
public final class ProxyHub {
    static final String FUENTE = "X-CH-Fuente";
    private final Nucleo n;

    public ProxyHub(Nucleo n) { this.n = n; }

    WebResourceResponse atender(String metodo, Uri u) {
        String ruta = u.getEncodedPath();
        String query = u.getEncodedQuery();
        if (ruta == null || ruta.length() > 1024 || (query != null && query.length() > 2048)) return error(400, "parametros_invalidos", "Petición inválida.", "hub");
        if (!"GET".equals(metodo)) {
            return error(405, "prohibido", "Este cambio se envía desde la app.", "hub");
        }
        String rutaQuery = query == null ? ruta : ruta + "?" + query;
        if (n.cliente.esNube() && u.getPath() != null && u.getPath().startsWith("/api/native/")) {
            if ("/api/native/session".equals(u.getPath()))
                return ServidorAssets.json(200, "OK", n.estadoNativo().toString(), new HashMap<>());
            return error(403, "prohibido", "Esta ruta de acceso se gestiona dentro de la aplicación.", "hub");
        }
        if (ruta.startsWith("/img/")) return imagen(rutaQuery);
        if ("/api/snapshot".equals(ruta)) return snapshot();
        if (!n.cliente.emparejado() || !n.cliente.conectado()) return sinConexion();
        try {
            ClienteHub.Respuesta r = n.cliente.pedir(new ClienteHub.Peticion("GET", "/lan/v1" + rutaQuery));
            if (r.codigo == 401) n.avisarConexion();
            return desdeHub(r, "no-store");
        } catch (IOException e) {
            n.cliente.marcarDesconectado();
            return sinConexion();
        }
    }

    // ------------------------------------------------------------------ copia
    private WebResourceResponse snapshot() {
        if (!n.copia.existe() && n.cliente.conectado()) n.refrescarCopia(false);
        if (!n.copia.existe()) return sinConexion();
        try {
            Map<String, String> h = new HashMap<>();
            h.put("Cache-Control", "no-store");
            h.put("X-Content-Type-Options", "nosniff");
            h.put(FUENTE, "copia");
            h.put("X-CH-Copia-At", String.valueOf(n.copia.meta().copiaAt));
            return new WebResourceResponse("application/json", "UTF-8", 200, "OK", h, n.copia.abrirDescomprimida());
        } catch (IOException e) {
            return sinConexion();
        }
    }

    // ------------------------------------------------------------------ imágenes
    private WebResourceResponse imagen(String rutaQuery) {
        // rev. 5: '/img/v/<content_id>' (portada real de la Display API) ya no está reservada; la valida normalizarImagen.
        String norm = CopiaSinConexion.normalizarImagen(rutaQuery);
        if (norm == null) return error(404, "no_encontrado", "No existe.", "hub");
        boolean versionada = PoliticaCacheImagenes.etagEsperada(norm) != null;
        if (versionada) {
            File f = n.copia.imagenEnCache(norm);
            if (f != null) return archivoImagen(f, "copia");
        }
        ClienteHub.Respuesta falloRemoto = null;
        if (n.cliente.conectado()) {
            try {
                ClienteHub.Respuesta r = n.cliente.pedir(new ClienteHub.Peticion("GET", "/lan/v1" + norm).limite(10L * 1024 * 1024));
                if (r.codigo == 200) {
                    if (PoliticaCacheImagenes.almacenable(norm, r.cabecera("ETag"), r.tipo))
                        n.copia.guardarImagen(norm, r.cuerpo, r.cabecera("ETag"));
                    return desdeHub(r, PoliticaCacheImagenes.CACHE_HTTP);
                }
                if (!PoliticaCacheImagenes.permiteRespaldo(r.codigo)) return desdeHub(r, PoliticaCacheImagenes.CACHE_HTTP);
                falloRemoto = r;
            } catch (IOException e) {
                n.cliente.marcarDesconectado();
            }
        }
        if (versionada) {
            for (String alt : CopiaSinConexion.alternativas(norm)) {
                File f = n.copia.imagenEnCache(alt);
                if (f != null) return archivoImagen(f, "copia");
            }
        }
        if (falloRemoto != null) return desdeHub(falloRemoto, PoliticaCacheImagenes.CACHE_HTTP);
        Map<String, String> h = new HashMap<>();
        h.put(FUENTE, "sin_conexion");
        h.put("Cache-Control", "no-store");
        return new WebResourceResponse("text/plain", "UTF-8", 404, "Not Found", h, new ByteArrayInputStream(new byte[0]));
    }

    private static WebResourceResponse archivoImagen(File f, String fuente) {
        try {
            InputStream in = new FileInputStream(f);
            Map<String, String> h = new HashMap<>();
            h.put("Cache-Control", PoliticaCacheImagenes.CACHE_HTTP);
            h.put("X-Content-Type-Options", "nosniff");
            h.put(FUENTE, fuente);
            return new WebResourceResponse(CopiaSinConexion.mimeDe(f), null, 200, "OK", h, in);
        } catch (IOException e) {
            return ServidorAssets.vacio(404, "Not Found");
        }
    }

    // ------------------------------------------------------------------ respuestas
    private static WebResourceResponse desdeHub(ClienteHub.Respuesta r, String cache) {
        String tipo = r.tipo, enc = null;
        int pc = tipo.indexOf(';');
        if (pc >= 0) {
            String resto = tipo.substring(pc + 1).trim();
            tipo = tipo.substring(0, pc).trim();
            if (resto.toLowerCase(java.util.Locale.ROOT).startsWith("charset=")) enc = resto.substring(8).trim();
        }
        if (enc == null && (tipo.contains("json") || tipo.startsWith("text/"))) enc = "UTF-8";
        Map<String, String> h = new HashMap<>();
        h.put("Cache-Control", cache);
        h.put("X-Content-Type-Options", "nosniff");
        h.put(FUENTE, "hub");
        String etag = r.cabecera("ETag");
        if (etag != null) h.put("ETag", etag);
        int codigo = r.codigo;
        if (codigo >= 300 && codigo < 400) codigo = 502;   // WebResourceResponse no admite 3xx
        return new WebResourceResponse(tipo, enc, codigo, razon(codigo), h, new ByteArrayInputStream(r.cuerpo));
    }

    /** 503 + ErrorRespuesta + X-CH-Fuente: sin_conexion → la interfaz arma la vista con deCopia() o «Necesita tu PC encendida». */
    static WebResourceResponse sinConexion() {
        return error(503, "sin_internet", "No hay conexión disponible. Tu copia guardada sigue en este dispositivo.", "sin_conexion");
    }

    static WebResourceResponse error(int codigo, String clave, String mensaje, String fuente) {
        String cuerpo;
        try {
            cuerpo = new JSONObject().put("error", new JSONObject().put("codigo", clave).put("mensaje", mensaje)).toString();
        } catch (JSONException e) {
            cuerpo = "{}";
        }
        Map<String, String> h = new HashMap<>();
        h.put(FUENTE, fuente);
        return ServidorAssets.json(codigo, razon(codigo), cuerpo, h);
    }

    static String razon(int codigo) {
        switch (codigo) {
            case 200: return "OK";
            case 201: return "Created";
            case 202: return "Accepted";
            case 204: return "No Content";
            case 400: return "Bad Request";
            case 401: return "Unauthorized";
            case 403: return "Forbidden";
            case 404: return "Not Found";
            case 405: return "Method Not Allowed";
            case 409: return "Conflict";
            case 413: return "Payload Too Large";
            case 429: return "Too Many Requests";
            case 500: return "Internal Server Error";
            case 502: return "Bad Gateway";
            case 503: return "Service Unavailable";
            default: return codigo < 400 ? "OK" : "Error";
        }
    }
}
