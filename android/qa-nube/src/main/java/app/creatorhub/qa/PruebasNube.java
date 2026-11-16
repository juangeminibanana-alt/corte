package app.creatorhub.qa;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.content.ContextWrapper;
import android.os.Bundle;
import app.creatorhub.Nucleo;
import app.creatorhub.datos.ColaOps;
import app.creatorhub.datos.CopiaSinConexion;
import app.creatorhub.datos.AlmacenSeguro;
import app.creatorhub.datos.MigracionNube;
import app.creatorhub.red.CanalNube;
import app.creatorhub.red.SeguridadNube;
import app.creatorhub.red.PoliticaCacheImagenes;
import app.creatorhub.red.ControlPrecargaImagenes;
import app.creatorhub.red.ClienteHub;
import app.creatorhub.web.ProxyHub;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.UUID;
import java.util.zip.GZIPOutputStream;
import org.json.JSONArray;
import org.json.JSONObject;

/** Runner del framework Android sin JUnit, dependencias, interfaz ni red. Todo vive en la cache de su APK QA. */
public final class PruebasNube extends Instrumentation {
    @Override public void onCreate(Bundle argumentos) { super.onCreate(argumentos); start(); }

    @Override public void onStart() {
        Bundle resultado = new Bundle();
        try {
            probar();
            resultado.putString("native_checks", "PASS: Keystore, PKCE, rutas, fsync, deduplicacion, UTF8, archivo SHA256, defer, DTO limpio, ETag, fallback ProxyHub404/429/503, reintentos acotados y ficha/SKU/galeria/query/snapshot sin recortes");
            resultado.putBoolean("production_data_touched", false);
            finish(Activity.RESULT_OK, resultado);
        } catch (Throwable e) {
            resultado.putString("native_checks", "FAIL: " + e.getClass().getSimpleName() + (e instanceof AssertionError ? " / " + e.getMessage() : ""));
            finish(Activity.RESULT_CANCELED, resultado);
        }
    }

    private void probar() throws Exception {
        Context original = getTargetContext();
        comprobar("app.creatorhub.qa".equals(original.getPackageName()), "Paquete de QA separado");
        final File archivos = new File(original.getCacheDir(), "qa-nube-" + UUID.randomUUID());
        comprobar(archivos.mkdirs(), "Carpeta aislada");
        Context aislado = new ContextWrapper(original) {
            @Override public File getFilesDir() { return archivos; }
            @Override public Context getApplicationContext() { return this; }
        };
        comprobar(SeguridadNube.reto("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")
                .equals("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"), "PKCE nativo");
        try { SeguridadNube.rutaRemota("/api/native/%73ession"); throw new AssertionError("Ruta privada codificada"); }
        catch (IllegalArgumentException esperado) { }
        AlmacenSeguro seguro = new AlmacenSeguro(aislado);
        seguro.borrar("corte.nube.dispositivo.v1");
        seguro.borrar("corte.nube.autorizacion.v1");
        String verifier = SeguridadNube.nuevoVerificador();
        JSONObject pendiente = new JSONObject().put("request_id", "qa-pedido-sintetico").put("code_verifier", verifier)
                .put("user_code", "ABCD-EFGH").put("verification_uri", SeguridadNube.ORIGEN + "/conectar-dispositivo?codigo=ABCD-EFGH")
                .put("expires_at", System.currentTimeMillis() / 1000L + 600);
        seguro.guardar("corte.nube.autorizacion.v1", pendiente.toString());
        String cifrado = aislado.getSharedPreferences("creatorhub_seguro", Context.MODE_PRIVATE).getString("corte.nube.autorizacion.v1", "");
        comprobar(!cifrado.isEmpty() && !cifrado.contains(verifier), "Verifier cifrado en reposo");
        String publico = new CanalNube(new AlmacenSeguro(aislado), () -> { }).estado().toString();
        comprobar(publico.contains("ABCD-EFGH") && !publico.contains(verifier) && !publico.contains("code_verifier")
                && !publico.contains("request_id"), "Reapertura segura sin secreto en DTO");
        seguro.borrar("corte.nube.autorizacion.v1"); // El runner jamás inicia ni sondea una autorización real.
        CopiaSinConexion imagenes = new CopiaSinConexion(aislado);
        String imagen = "/img/v/123456789?v=aaaaaaaa&t=md";
        File archivoImagen = imagenes.archivoImagen(imagen);
        comprobar(archivoImagen.getParentFile().mkdirs(), "Directorio cache aislado");
        Files.write(archivoImagen.toPath(), "LEGACY-SIN-ETAG".getBytes(StandardCharsets.UTF_8));
        comprobar(imagenes.imagenEnCache(imagen) == null, "No confiar en cache vieja sin ETag");
        byte[] png = android.util.Base64.decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", android.util.Base64.DEFAULT);
        imagenes.guardarImagen(imagen, png, "\"bbbbbbbb-md\"");
        comprobar(imagenes.imagenEnCache(imagen) == null, "ETag distinto no se guarda bajo URL vieja");
        imagenes.guardarImagen(imagen, png, "\"aaaaaaaa-md\"");
        comprobar(imagenes.imagenEnCache(imagen) != null && "image/png".equals(CopiaSinConexion.mimeDe(archivoImagen)), "Cache privada con identidad fuerte");
        comprobar(imagenes.imagenEnCache("/img/v/123456789?v=bbbbbbbb&t=md") == null
                && imagenes.imagenEnCache("/img/v/987654321?v=aaaaaaaa&t=md") == null, "No cruzar ID/version");
        comprobar(!PoliticaCacheImagenes.almacenable(imagen, "\"aaaaaaaa-sm\"", "image/webp")
                && !PoliticaCacheImagenes.almacenable(imagen, "\"aaaaaaaa-md\"", "text/html"), "Variante y MIME correctos");
        ControlPrecargaImagenes presupuesto = new ControlPrecargaImagenes();
        comprobar(presupuesto.intentar("a", 0) && !presupuesto.intentar("a", 59999)
                && presupuesto.intentar("a", 60000) && presupuesto.intentar("a", 120000)
                && !presupuesto.intentar("a", 999999), "Tres intentos con pausa, sin bucle por304");
        JSONObject op = new JSONObject().put("op_id", "qa-pendiente-uno").put("tipo", "nota.crear")
                .put("datos", new JSONObject().put("texto", "Nota sintetica pendiente"));
        ColaOps cola = new ColaOps(aislado);
        comprobar(cola.agregar(new JSONArray().put(op).toString()) == 1, "Persistencia");
        File archivoCola = new File(archivos, "cola/ops.jsonl");
        byte[] hashCola = hash(archivoCola);
        ColaOps reabierta = new ColaOps(aislado);
        comprobar(reabierta.cantidad() == 1, "Reapertura tras cierre del proceso");
        comprobar(reabierta.agregar(new JSONArray().put(op).toString()) == 1 && reabierta.cantidad() == 1
                && java.util.Arrays.equals(hashCola, hash(archivoCola)), "Idempotencia de op_id");
        JSONObject grande = new JSONObject().put("op_id", "qa-demasiado-grande").put("tipo", "nota.crear")
                .put("datos", new JSONObject().put("texto", "á".repeat(40000)));
        comprobar(reabierta.agregar(new JSONArray().put(grande).toString()) == 0, "Tope por bytes UTF8");
        JSONObject local = new JSONObject().put("planes", new JSONArray()).put("avisos", new JSONArray())
                .put("notas", new JSONArray().put(new JSONObject().put("id", "confirmada-distinta").put("texto", "Nota sintetica confirmada")))
                .put("recordatorios", new JSONArray()).put("plantillas", new JSONArray()).put("preferencias", new JSONObject());
        File dirCopia = new File(archivos, "copia"); comprobar(dirCopia.mkdirs(), "Carpeta copia");
        File copia = new File(dirCopia, "snapshot.json.gz");
        try (FileOutputStream out = new FileOutputStream(copia); GZIPOutputStream gz = new GZIPOutputStream(out)) {
            gz.write(new JSONObject().put("version_esquema", 1).put("local", local).toString().getBytes(StandardCharsets.UTF_8));
            gz.finish(); out.getFD().sync();
        }
        Files.write(new File(dirCopia, "meta.json").toPath(), "{\"copia_at\":1}".getBytes(StandardCharsets.UTF_8));
        byte[] hashCopia = hash(copia);
        MigracionNube migracion = new MigracionNube(aislado);
        migracion.preparar(reabierta);
        comprobar(reabierta.cantidad() == 0, "Cola cloud separada");
        comprobar(java.util.Arrays.equals(hashCopia, hash(new File(archivos, "anterior_nube/snapshot.json.gz")))
                && java.util.Arrays.equals(hashCola, hash(new File(archivos, "anterior_nube/ops.jsonl")))
                && java.util.Arrays.equals(hashCopia, hash(copia)), "Archivo verificado y original conservado");
        JSONObject estado = migracion.estadoPublico();
        comprobar(estado.getBoolean("migration_pending") && estado.getJSONObject("migration_counts").getInt("notas") == 1
                && estado.getJSONObject("migration_counts").getInt("pendientes") == 1, "Snapshot raw separado de pendientes");
        migracion.decidir(false, null, reabierta);
        estado = migracion.estadoPublico();
        comprobar(!estado.getBoolean("migration_pending") && estado.getBoolean("migration_available")
                && new File(archivos, "anterior_nube/ops.jsonl").isFile(), "Defer conserva archivo y operaciones");
        File marca = new File(archivos, "anterior_nube/estado.json");
        JSONObject privada = new JSONObject(new String(Files.readAllBytes(marca.toPath()), StandardCharsets.UTF_8))
                .put("owner_uid", "qa-propietario-privado").put("tiktok_open_id", "qa-cuenta-privada");
        Files.write(marca.toPath(), privada.toString().getBytes(StandardCharsets.UTF_8));
        // El transporte HTTPS de pruebas NO abre sockets. El APK QA ni siquiera tiene permiso INTERNET.
        HttpsSintetica.cuerpo = png;
        java.net.URL.setURLStreamHandlerFactory(protocolo -> "https".equals(protocolo) ? new java.net.URLStreamHandler() {
            @Override protected java.net.URLConnection openConnection(java.net.URL u) { return new HttpsSintetica(u); }
        } : null);
        seguro.guardar("corte.nube.dispositivo.v1", new JSONObject().put("token", "corte_native_v1_" + "z".repeat(43))
                .put("expires_at", System.currentTimeMillis() / 1000L + 600).put("device_id", "qa-sintetico")
                .put("owner_uid", "qa-sintetico").toString());
        Nucleo nucleo = Nucleo.de(aislado);
        nucleo.cliente.pedir(new ClienteHub.Peticion("GET", "/img/v/333333333?v=aaaaaaaa&t=md"));
        java.lang.reflect.Method atender = ProxyHub.class.getDeclaredMethod("atender", String.class, android.net.Uri.class);
        atender.setAccessible(true);
        ProxyHub proxy = new ProxyHub(nucleo);
        String pedido = "/img/v/333333333?v=aaaaaaaa&t=md";
        HttpsSintetica.etag = "\"bbbbbbbb-md\"";
        android.webkit.WebResourceResponse respuesta = (android.webkit.WebResourceResponse) atender.invoke(proxy, "GET", android.net.Uri.parse("https://appassets.androidplatform.net" + pedido));
        comprobar(respuesta.getStatusCode() == 200 && nucleo.copia.imagenEnCache(pedido) == null
                && respuesta.getResponseHeaders().get("Cache-Control").contains("no-store"), "Proxy nativo rechaza persistir ETag distinto");
        HttpsSintetica.etag = "\"aaaaaaaa-md\"";
        atender.invoke(proxy, "GET", android.net.Uri.parse("https://appassets.androidplatform.net" + pedido));
        comprobar(nucleo.copia.imagenEnCache(pedido) != null, "Proxy nativo persiste sólo imagen verificada");
        String md = "/img/v/444444444?v=aaaaaaaa&t=md", sm = "/img/v/444444444?v=aaaaaaaa&t=sm";
        nucleo.copia.guardarImagen(sm, png, "\"aaaaaaaa-sm\"");
        for (int status : new int[] { 404, 429, 503 }) {
            HttpsSintetica.codigo = status;
            respuesta = (android.webkit.WebResourceResponse) atender.invoke(proxy, "GET", android.net.Uri.parse("https://appassets.androidplatform.net" + md));
            comprobar(respuesta.getStatusCode() == 200 && java.util.Arrays.equals(png, respuesta.getData().readAllBytes())
                    && respuesta.getResponseHeaders().get("Cache-Control").contains("no-store"), "Proxy nativo usa SM ante MD" + status);
        }
        respuesta = (android.webkit.WebResourceResponse) atender.invoke(proxy, "GET", android.net.Uri.parse("https://appassets.androidplatform.net/img/v/444444444?v=bbbbbbbb&t=md"));
        comprobar(respuesta.getStatusCode() == 503, "Proxy nativo no mezcla versiones");
        probarProductos(nucleo, proxy, atender, png);
        HttpsSintetica.codigo = 401;
        respuesta = (android.webkit.WebResourceResponse) atender.invoke(proxy, "GET", android.net.Uri.parse("https://appassets.androidplatform.net" + md));
        comprobar(respuesta.getStatusCode() == 401, "Proxy nativo no oculta sesión vencida con imagen cacheada");
        seguro.borrar("corte.nube.dispositivo.v1");
        String dto = nucleo.estadoNativo().toString();
        comprobar(!dto.contains("\"token\"") && !dto.contains("code_verifier") && !dto.contains("tiktok_open_id")
                && !dto.contains("owner_uid") && new JSONObject(dto).getBoolean("native_client"), "DTO limpio");
    }

    private static void probarProductos(Nucleo nucleo, ProxyHub proxy, java.lang.reflect.Method atender, byte[] png) throws Exception {
        String pid = "1729000000000000001";
        String galeria = "/img/g/" + pid + "-11?v=cccccccc&t=md";
        JSONObject sku = new JSONObject().put("sku_id", "1729000000000000101").put("variante", "Azul / M")
                .put("propiedades", new JSONArray().put(new JSONObject().put("nombre", "Color").put("valor", "Azul")));
        JSONObject extendido = new JSONObject().put("galeria", new JSONArray().put(galeria))
                .put("muestra", new JSONObject().put("skus", new JSONArray().put(sku)));
        byte[] ficha = new JSONObject().put("product_id", pid).put("extendido", extendido)
                .put("muestras", new JSONArray()).toString().getBytes(StandardCharsets.UTF_8);
        HttpsSintetica.codigo = 200;
        HttpsSintetica.tipo = "application/json; charset=utf-8";
        HttpsSintetica.cuerpo = ficha;
        String ruta = "/api/productos/" + pid + "?desde=2026-11-01&q=Azul%20%2F%20M";
        android.webkit.WebResourceResponse r = (android.webkit.WebResourceResponse) atender.invoke(proxy, "GET",
                android.net.Uri.parse("https://appassets.androidplatform.net" + ruta));
        comprobar(r.getStatusCode() == 200 && java.util.Arrays.equals(ficha, r.getData().readAllBytes()),
                "Ficha completa, propiedades de color y galeria llegan sin recorte nativo");
        comprobar((SeguridadNube.ORIGEN + ruta).equals(HttpsSintetica.ultimaUrl), "Query codificada llega intacta a HTTPS");
        HttpsSintetica.tipo = "image/png";
        HttpsSintetica.etag = "\"cccccccc-md\"";
        HttpsSintetica.cuerpo = png;
        r = (android.webkit.WebResourceResponse) atender.invoke(proxy, "GET",
                android.net.Uri.parse("https://appassets.androidplatform.net" + galeria));
        comprobar(r.getStatusCode() == 200 && java.util.Arrays.equals(png, r.getData().readAllBytes())
                && nucleo.copia.imagenEnCache(galeria) != null, "Foto12 de galeria permitida y guardada con su identidad");
        comprobar(nucleo.copia.imagenEnCache(galeria.replace("-11?", "-10?")) == null,
                "Fotos de galeria no comparten clave de cache");
        byte[] snapshot = new JSONObject().put("version_esquema", 1).put("data_version", 3).put("local_rev", 4)
                .put("img_rev", 7).put("generado_at", 123).put("local", new JSONObject())
                .put("productos", new JSONArray().put(new JSONObject().put("product_id", pid)))
                .put("muestras", new JSONArray().put(new JSONObject().put("application_id", "5770000000000000001")
                        .put("variante", "Azul / M").put("sku_id", sku.getString("sku_id"))))
                .put("imagenes", new JSONArray().put(galeria)).toString().getBytes(StandardCharsets.UTF_8);
        HttpsSintetica.tipo = "application/json";
        HttpsSintetica.etag = "W/\"dv3-lr4-ir7-f1\"";
        HttpsSintetica.cuerpo = snapshot;
        nucleo.copia.actualizar(nucleo.cliente);
        try (java.io.InputStream in = nucleo.copia.abrirDescomprimida()) {
            comprobar(java.util.Arrays.equals(snapshot, in.readAllBytes()), "Copia nativa conserva todo el JSON de servidor");
        }
        comprobar(nucleo.copia.meta().imagenes.contains(galeria), "Precarga admite fotos g de galeria del snapshot");
        comprobar(nucleo.copia.meta().imgRev == 7 && HttpsSintetica.etag.equals(nucleo.copia.meta().etag),
                "Snapshot f1 conserva img_rev del cuerpo y ETag literal");
        HttpsSintetica.codigo = 304;
        comprobar(nucleo.copia.actualizar(nucleo.cliente) == null
                && HttpsSintetica.etag.equals(HttpsSintetica.ultimoIfNoneMatch)
                && nucleo.copia.meta().imgRev == 7, "Snapshot f1 reenvia ETag y acepta304 sin perder copia");
        HttpsSintetica.codigo = 200;
        HttpsSintetica.tipo = "image/png";
        HttpsSintetica.etag = "\"aaaaaaaa-md\"";
        HttpsSintetica.cuerpo = png;
    }

    private static byte[] hash(File f) throws Exception { return MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(f.toPath())); }
    private static void comprobar(boolean valor, String mensaje) { if (!valor) throw new AssertionError(mensaje); }

    private static final class HttpsSintetica extends javax.net.ssl.HttpsURLConnection {
        static int codigo = 200;
        static String etag = "\"aaaaaaaa-md\"";
        static String tipo = "image/png", ultimaUrl, ultimoIfNoneMatch;
        static byte[] cuerpo;
        HttpsSintetica(java.net.URL u) { super(u); }
        @Override public int getResponseCode() throws java.io.IOException {
            ultimaUrl = url.toString();
            ultimoIfNoneMatch = getRequestProperty("If-None-Match");
            if (!"corte-e-book-21589.web.app".equals(url.getHost()) || !"1".equals(getRequestProperty("X-CH-Hub"))
                    || !"https://corte-e-book-21589.web.app".equals(getRequestProperty("Origin"))
                    || !getRequestProperty("Authorization").startsWith("Bearer corte_native_v1_")) throw new java.io.IOException("Transporte de prueba inesperado");
            return codigo;
        }
        @Override public String getContentType() { return tipo; }
        @Override public java.util.Map<String, java.util.List<String>> getHeaderFields() {
            return java.util.Map.of("Content-Type", java.util.List.of(tipo), "Cache-Control", java.util.List.of("private, no-store"), "ETag", java.util.List.of(etag));
        }
        @Override public java.io.InputStream getInputStream() { return new java.io.ByteArrayInputStream(cuerpo); }
        @Override public java.io.InputStream getErrorStream() { return new java.io.ByteArrayInputStream("{}".getBytes(StandardCharsets.UTF_8)); }
        @Override public void disconnect() { }
        @Override public boolean usingProxy() { return false; }
        @Override public void connect() { }
        @Override public String getCipherSuite() { return "QA-sin-red"; }
        @Override public java.security.cert.Certificate[] getLocalCertificates() { return new java.security.cert.Certificate[0]; }
        @Override public java.security.cert.Certificate[] getServerCertificates() { return new java.security.cert.Certificate[0]; }
    }
}
