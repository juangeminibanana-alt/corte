package app.creatorhub.datos;

import android.content.Context;
import android.net.Uri;
import android.util.JsonReader;
import android.util.JsonToken;
import app.creatorhub.red.ClienteHub;
import java.io.BufferedInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.GZIPInputStream;
import java.util.zip.GZIPOutputStream;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * Copia sin conexión del celular (04 §B.4; C27; C45; C11):
 * - `files/copia/snapshot.json.gz`: GET /lan/v1/api/snapshot con If-None-Match (ETag "dv<N>-lr<M>-ir<K>"); 200 →
 *   escritura ATÓMICA (archivo temporal + fsync + move atómico) y metadatos en `meta.json`; 304 → sin cambios;
 * - imágenes en `files/img/<sha1(ruta normalizada)>`, precarga de `imagenes[]` con 4 descargas a la vez y caché LRU de
 *   150 MB (C11: 150, no 200).
 * El snapshot se lee en flujo (JsonReader sobre GZIP) para no cargar varios MB en memoria.
 */
public final class CopiaSinConexion {
    public static final long TOPE_IMAGENES = 150L * 1024 * 1024;
    static final long TOPE_SNAPSHOT = 64L * 1024 * 1024;
    static final long TOPE_IMAGEN = 10L * 1024 * 1024;
    private static final Pattern ETAG = Pattern.compile("^(?:W/)?\"dv(\\d+)-lr(\\d+)-ir(\\d+)\"$");
    /** p = producto · a = cuenta · rev. 4 (15/11): g = foto n de la galería de tu vitrina ('<product_id>-<n>', n 0–11)
     *  y m = foto de un producto parecido del marketplace ('<product_id>') · rev. 5 (15/11): v = portada real del video
     *  de la Display API ('<content_id>', solo dígitos, como el hub). */
    private static final Pattern RUTA_IMG = Pattern.compile("^/img/(?:[pam]/[A-Za-z0-9_-]{1,64}|g/[0-9]{1,25}-(?:[0-9]|1[01])|v/[0-9]{1,25})$");
    private static final List<String> VARIANTES = Arrays.asList("xs", "sm", "md");

    /** Datos públicos de la copia (van en creatorhub-copia y en EstadoConexionPc). */
    public static final class Meta {
        public String etag = "";
        public long dataVersion, localRev, imgRev, copiaAt, generadoAt;
        public List<String> imagenes = Collections.emptyList();

        JSONObject aJson() throws JSONException {
            return new JSONObject().put("etag", etag).put("data_version", dataVersion).put("local_rev", localRev)
                    .put("img_rev", imgRev).put("copia_at", copiaAt).put("generado_at", generadoAt)
                    .put("imagenes", new org.json.JSONArray(imagenes));
        }

        static Meta deJson(JSONObject o) {
            Meta m = new Meta();
            m.etag = o.optString("etag", "");
            m.dataVersion = o.optLong("data_version", 0);
            m.localRev = o.optLong("local_rev", 0);
            m.imgRev = o.optLong("img_rev", 0);
            m.copiaAt = o.optLong("copia_at", 0);
            m.generadoAt = o.optLong("generado_at", 0);
            org.json.JSONArray a = o.optJSONArray("imagenes");
            if (a != null) {
                List<String> l = new ArrayList<>();
                for (int i = 0; i < a.length(); i++) l.add(a.optString(i));
                m.imagenes = l;
            }
            return m;
        }
    }

    /** Progreso de la precarga: creatorhub-imagenes {hechas, total}. */
    public interface Progreso { void avance(int hechas, int total); }

    private final File dirCopia, dirImg, archivo, archivoMeta;
    private final Object candadoDescarga = new Object();
    private Meta meta;                       // con this; null = todavía no se lee meta.json

    /** No toca el disco (se construye en el hilo principal): meta.json se lee en el primer uso, en otro hilo. */
    public CopiaSinConexion(Context ctx) {
        File base = ctx.getFilesDir();
        dirCopia = new File(base, "copia");
        dirImg = new File(base, "img");
        archivo = new File(dirCopia, "snapshot.json.gz");
        archivoMeta = new File(dirCopia, "meta.json");
    }

    /** La meta en memoria (la lee de disco la primera vez). Se llama con `this` tomado. */
    private Meta m() {
        if (meta == null) meta = leerMeta();
        return meta;
    }

    private Meta leerMeta() {
        if (!archivoMeta.isFile() || !archivo.isFile()) return new Meta();
        try (InputStream in = new FileInputStream(archivoMeta)) {
            return Meta.deJson(new JSONObject(new String(leerTodo(in, 4L * 1024 * 1024), StandardCharsets.UTF_8)));
        } catch (IOException | JSONException e) {
            return new Meta();
        }
    }

    public synchronized Meta meta() { return m(); }
    /** Hay una copia válida guardada (data_version puede ser 0 si la PC aún no sincroniza: igual es una copia). */
    public synchronized boolean existe() { return archivo.isFile() && m().copiaAt > 0; }

    /** El snapshot descomprimido (el proxy lo sirve como /api/snapshot sin conexión). */
    public synchronized InputStream abrirDescomprimida() throws IOException {
        return new GZIPInputStream(new BufferedInputStream(new FileInputStream(archivo), 65536), 65536);
    }

    /**
     * GET /lan/v1/api/snapshot con If-None-Match. Devuelve la meta nueva si cambió, o null si el hub respondió 304.
     * Lanza IOException si no hubo respuesta usable (la copia anterior queda intacta).
     */
    public Meta actualizar(ClienteHub cliente) throws IOException {
        synchronized (candadoDescarga) {        // una descarga a la vez: el archivo temporal es uno solo
            return actualizarSinCompetencia(cliente);
        }
    }

    private Meta actualizarSinCompetencia(ClienteHub cliente) throws IOException {
        if (!dirCopia.isDirectory() && !dirCopia.mkdirs()) throw new IOException("sin carpeta de copia");
        String etag;
        synchronized (this) { etag = existe() ? m().etag : ""; }
        File tmp = new File(dirCopia, "snapshot.json.gz.nuevo");
        ClienteHub.Peticion p = new ClienteHub.Peticion("GET", "/lan/v1/api/snapshot")
                .gzipCrudo().aArchivo(tmp).limite(TOPE_SNAPSHOT).lectura(60_000);
        if (!etag.isEmpty()) p.cabecera("If-None-Match", etag);
        ClienteHub.Respuesta r;
        try {
            r = cliente.pedir(p);
        } catch (IOException e) {
            borrar(tmp);
            throw e;
        }
        if (r.codigo == 304) { borrar(tmp); return null; }
        if (r.codigo != 200 || !tmp.isFile()) { borrar(tmp); throw new IOException("snapshot " + r.codigo); }
        try {
            if (!esGzip(tmp)) comprimirEnSuLugar(tmp);   // si llegó sin Content-Encoding, se guarda comprimido igual
            Meta nueva;
            try (InputStream in = new GZIPInputStream(new BufferedInputStream(new FileInputStream(tmp), 65536), 65536)) {
                nueva = leerCabecera(in);
            }
            String e = r.cabecera("ETag");
            nueva.etag = e == null ? "" : e.trim();
            Matcher m = ETAG.matcher(nueva.etag);
            if (m.matches()) {           // la ETag manda si el cuerpo no trae img_rev (opcional en el tipo)
                if (nueva.imgRev == 0) nueva.imgRev = Long.parseLong(m.group(3));
            }
            nueva.copiaAt = System.currentTimeMillis() / 1000L;
            synchronized (this) {
                Files.move(tmp.toPath(), archivo.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
                escribirAtomico(archivoMeta, nueva.aJson().toString().getBytes(StandardCharsets.UTF_8));
                meta = nueva;
            }
            return nueva;
        } catch (JSONException | IOException | IllegalStateException e) {
            borrar(tmp);
            throw new IOException("snapshot ilegible", e);
        }
    }

    /** Lee solo lo necesario del SnapshotResponse: versiones, generado_at e imagenes[] (salta lo demás). */
    static Meta leerCabecera(InputStream in) throws IOException {
        Meta m = new Meta();
        List<String> imgs = new ArrayList<>();
        boolean esquema = false;
        try (JsonReader r = new JsonReader(new InputStreamReader(in, StandardCharsets.UTF_8))) {
            r.beginObject();
            while (r.hasNext()) {
                String k = r.nextName();
                if (r.peek() == JsonToken.NULL) { r.skipValue(); continue; }
                switch (k) {
                    case "version_esquema": esquema = r.nextInt() == 1; break;
                    case "data_version": m.dataVersion = r.nextLong(); break;
                    case "local_rev": m.localRev = r.nextLong(); break;
                    case "img_rev": m.imgRev = r.nextLong(); break;
                    case "generado_at": m.generadoAt = r.nextLong(); break;
                    case "imagenes":
                        r.beginArray();
                        while (r.hasNext()) {
                            if (r.peek() == JsonToken.STRING) {
                                String u = r.nextString();
                                if (imgs.size() < 5000 && normalizarImagen(u) != null) imgs.add(u);
                            } else r.skipValue();
                        }
                        r.endArray();
                        break;
                    default: r.skipValue();
                }
            }
            r.endObject();
        }
        if (!esquema) throw new IOException("snapshot sin version_esquema 1");
        if (m.dataVersion < 0 || m.localRev < 0 || m.imgRev < 0) throw new IOException("snapshot con versiones negativas");
        m.imagenes = imgs;
        return m;
    }

    // ------------------------------------------------------------------ imágenes
    /**
     * Forma normalizada '/img/<p|a|m>/<id>?v=<v>[&t=<xs|sm|md>]', '/img/g/<product_id>-<n>?v=…' (rev. 4: galería de
     * la vitrina, n 0–11) o '/img/v/<content_id>?v=…' (rev. 5: portada de la Display API; antes reservada) (clave de la
     * caché) o null si no es una imagen válida.
     */
    public static String normalizarImagen(String rutaQuery) {
        if (rutaQuery == null || rutaQuery.length() > 512) return null;
        Uri u = Uri.parse("https://x" + rutaQuery);
        String ruta = u.getEncodedPath();
        if (ruta == null || !RUTA_IMG.matcher(ruta).matches()) return null;
        String v = u.getQueryParameter("v");
        if (v == null || !v.matches("[0-9A-Za-z]{1,32}")) return null;
        String t = u.getQueryParameter("t");
        if (t != null && !VARIANTES.contains(t)) return null;
        return ruta + "?v=" + v + (t == null ? "" : "&t=" + t);
    }

    /** Variantes alternativas de la misma imagen y versión para servir sin conexión (pedida → sm → md → xs → original). */
    public static List<String> alternativas(String normalizada) {
        List<String> l = new ArrayList<>();
        l.add(normalizada);
        int i = normalizada.indexOf("&t=");
        String base = i >= 0 ? normalizada.substring(0, i) : normalizada;
        for (String t : new String[] {"sm", "md", "xs"}) {
            String a = base + "&t=" + t;
            if (!l.contains(a)) l.add(a);
        }
        if (!l.contains(base)) l.add(base);
        return l;
    }

    public File archivoImagen(String normalizada) { return new File(dirImg, sha1(normalizada)); }

    /** La imagen en caché (y la marca como usada para el LRU) o null. */
    public File imagenEnCache(String normalizada) {
        File f = archivoImagen(normalizada);
        if (!f.isFile() || f.length() == 0) return null;
        //noinspection ResultOfMethodCallIgnored
        f.setLastModified(System.currentTimeMillis());
        return f;
    }

    public void guardarImagen(String normalizada, byte[] datos) {
        if (datos.length == 0 || datos.length > TOPE_IMAGEN) return;
        if (!dirImg.isDirectory() && !dirImg.mkdirs()) return;
        try { escribirAtomico(archivoImagen(normalizada), datos); } catch (IOException ignorado) { /* caché opcional */ }
    }

    /** Precarga las imágenes de la copia: 4 a la vez, solo las que faltan; luego recorta la caché a 150 MB. */
    public void precargar(ClienteHub cliente, Progreso progreso) {
        List<String> lista;
        synchronized (this) { lista = new ArrayList<>(m().imagenes); }
        final List<String> faltan = new ArrayList<>();
        for (String u : lista) {
            String n = normalizarImagen(u);
            if (n != null && !archivoImagen(n).isFile()) faltan.add(n);
        }
        final int total = faltan.size();
        if (total == 0) { recortarCache(); return; }
        final AtomicInteger hechas = new AtomicInteger();
        ExecutorService ex = Executors.newFixedThreadPool(4);
        try {
            for (final String n : faltan) {
                ex.execute(() -> {
                    try {
                        if (cliente.conectado()) {
                            ClienteHub.Respuesta r = cliente.pedir(new ClienteHub.Peticion("GET", "/lan/v1" + n).limite(TOPE_IMAGEN));
                            if (r.codigo == 200) guardarImagen(n, r.cuerpo);
                        }
                    } catch (IOException ignorado) {
                        // sin conexión a mitad de la precarga: se completa en la siguiente copia
                    }
                    int h = hechas.incrementAndGet();
                    if (progreso != null && (h == total || h % 10 == 0)) progreso.avance(h, total);
                });
            }
            ex.shutdown();
            ex.awaitTermination(10, TimeUnit.MINUTES);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } finally {
            ex.shutdownNow();
        }
        recortarCache();
    }

    /** LRU: borra las menos usadas (lastModified) hasta quedar en 150 MB. */
    public void recortarCache() {
        File[] fs = dirImg.listFiles();
        if (fs == null) return;
        long total = 0;
        for (File f : fs) total += f.length();
        if (total <= TOPE_IMAGENES) return;
        Arrays.sort(fs, (a, b) -> Long.compare(a.lastModified(), b.lastModified()));
        for (File f : fs) {
            if (total <= TOPE_IMAGENES) break;
            long n = f.length();
            if (f.delete()) total -= n;
        }
    }

    public long bytesImagenes() {
        File[] fs = dirImg.listFiles();
        long t = 0;
        if (fs != null) for (File f : fs) t += f.length();
        return t;
    }

    /** "Olvidar esta PC": copia e imágenes fuera. */
    public synchronized void borrarTodo() {
        borrarCarpeta(dirCopia);
        borrarCarpeta(dirImg);
        meta = new Meta();
    }

    /** Tipo MIME por los primeros bytes (la caché no guarda cabeceras). */
    public static String mimeDe(File f) {
        byte[] b = new byte[16];
        int n;
        try (InputStream in = new FileInputStream(f)) { n = in.read(b); } catch (IOException e) { return "application/octet-stream"; }
        if (n >= 12 && b[0] == 'R' && b[1] == 'I' && b[2] == 'F' && b[3] == 'F' && b[8] == 'W' && b[9] == 'E' && b[10] == 'B' && b[11] == 'P') return "image/webp";
        if (n >= 3 && (b[0] & 0xff) == 0xFF && (b[1] & 0xff) == 0xD8 && (b[2] & 0xff) == 0xFF) return "image/jpeg";
        if (n >= 8 && (b[0] & 0xff) == 0x89 && b[1] == 'P' && b[2] == 'N' && b[3] == 'G') return "image/png";
        if (n >= 6 && b[0] == 'G' && b[1] == 'I' && b[2] == 'F') return "image/gif";
        if (n >= 12 && b[4] == 'f' && b[5] == 't' && b[6] == 'y' && b[7] == 'p' && b[8] == 'a' && b[9] == 'v' && b[10] == 'i') return "image/avif";
        return "application/octet-stream";
    }

    // ------------------------------------------------------------------ utilidades de archivo
    static void escribirAtomico(File destino, byte[] datos) throws IOException {
        File tmp = new File(destino.getPath() + ".nuevo");
        try (FileOutputStream os = new FileOutputStream(tmp)) {
            os.write(datos);
            os.getFD().sync();
        }
        Files.move(tmp.toPath(), destino.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
    }

    private static boolean esGzip(File f) {
        try (InputStream in = new FileInputStream(f)) {
            return in.read() == 0x1f && in.read() == 0x8b;
        } catch (IOException e) {
            return false;
        }
    }

    private static void comprimirEnSuLugar(File f) throws IOException {
        File gz = new File(f.getPath() + ".gz");
        try (InputStream in = new FileInputStream(f); FileOutputStream fo = new FileOutputStream(gz)) {
            try (OutputStream os = new GZIPOutputStream(fo, 65536)) {
                byte[] buf = new byte[65536];
                for (int n; (n = in.read(buf)) != -1; ) os.write(buf, 0, n);
            }
        }
        Files.move(gz.toPath(), f.toPath(), StandardCopyOption.REPLACE_EXISTING);
    }

    private static void borrar(File f) {
        if (f.exists() && !f.delete()) f.deleteOnExit();
    }

    private static void borrarCarpeta(File d) {
        File[] fs = d.listFiles();
        if (fs != null) for (File f : fs) { if (f.isDirectory()) borrarCarpeta(f); else borrar(f); }
        borrar(d);
    }

    static String sha1(String s) {
        try {
            byte[] h = MessageDigest.getInstance("SHA-1").digest(s.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(40);
            for (byte x : h) sb.append(String.format(Locale.ROOT, "%02x", x & 0xff));
            return sb.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    /** Lectura acotada sin depender de readAllBytes (API 33+). */
    static byte[] leerTodo(InputStream in, long limite) throws IOException {
        java.io.ByteArrayOutputStream b = new java.io.ByteArrayOutputStream();
        byte[] buf = new byte[16384];
        for (int n; (n = in.read(buf)) != -1; ) {
            if (b.size() + n > limite) throw new IOException("demasiado grande");
            b.write(buf, 0, n);
        }
        return b.toByteArray();
    }
}
