package app.creatorhub.datos;

import android.content.Context;
import app.creatorhub.red.ClienteHub;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;
import java.util.zip.GZIPInputStream;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Archivo independiente de los datos históricos. Nunca compara identidades por nombre ni borra el original. */
public final class MigracionNube {
    private static final int MAX_EXPORT = 19 * 1024 * 1024;
    private static final String[] LISTAS = { "planes", "avisos", "notas", "recordatorios", "plantillas" };
    private final File base, dir, estadoFile, snapshot, operaciones;
    private JSONObject estado;

    public MigracionNube(Context ctx) {
        base = ctx.getFilesDir(); dir = new File(base, "anterior_nube");
        estadoFile = new File(dir, "estado.json"); snapshot = new File(dir, "snapshot.json.gz");
        operaciones = new File(dir, "ops.jsonl");
    }

    public synchronized void preparar(ColaOps cola) throws IOException {
        try {
            if (estado == null && estadoFile.isFile()) estado = new JSONObject(leer(estadoFile, 64 * 1024));
            if (estado == null) {
                if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("No pudimos preservar la copia anterior.");
                archivar(new File(base, "copia/snapshot.json.gz"), snapshot);
                archivar(new File(base, "copia/meta.json"), new File(dir, "meta.json"));
                archivar(new File(base, "cola/ops.jsonl"), operaciones);
                boolean hay = snapshot.isFile() || (operaciones.isFile() && operaciones.length() > 0);
                estado = new JSONObject().put("pending", hay).put("available", hay).put("queue_isolated", false);
                guardar();
            }
            if (!estado.optBoolean("queue_isolated")) {
                cola.aislarLegado();
                estado.put("queue_isolated", true); guardar();
            }
            if (!estado.has("counts")) {
                JSONObject counts = new JSONObject();
                try {
                    JSONObject local = localAnterior();
                    for (String campo : LISTAS) { JSONArray a = local.optJSONArray(campo); counts.put(campo, a == null ? 0 : a.length()); }
                    counts.put("pendientes", contarPendientes());
                } catch (IOException | JSONException e) {
                    estado.put("warning", "El archivo anterior está conservado. No pudimos leer todos sus registros para importarlos.");
                }
                estado.put("counts", counts); guardar();
            }
        } catch (JSONException e) { throw new IOException("La copia anterior sigue guardada, pero no pudimos prepararla.", e); }
    }

    public synchronized JSONObject estadoPublico() {
        JSONObject o = new JSONObject(), cuentas = new JSONObject();
        try {
            if (estado != null && estado.optJSONObject("counts") != null) cuentas = estado.getJSONObject("counts");
            o.put("migration_pending", estado != null && estado.optBoolean("pending"))
                    .put("migration_available", estado != null && estado.optBoolean("available"))
                    .put("migration_counts", cuentas);
            if (estado != null && estado.has("warning")) o.put("migration_warning", estado.optString("warning"));
        } catch (JSONException e) {
            try { o.put("migration_pending", true).put("migration_available", snapshot.isFile())
                    .put("migration_counts", cuentas).put("migration_warning", "La copia anterior está conservada. No pudimos leerla para importarla."); }
            catch (JSONException ignorada) { /* campos fijos */ }
        }
        return o;
    }

    public synchronized void decidir(boolean confirmar, ClienteHub cliente, ColaOps cola) throws IOException {
        if (estado == null || !estado.optBoolean("available")) return;
        try {
            if (!confirmar) { estado.put("pending", false); guardar(); return; }
            ClienteHub.Respuesta sesion = cliente.pedir(new ClienteHub.Peticion("GET", "/api/native/session"));
            JSONObject identidad = sesion.json(), owner = identidad == null ? null : identidad.optJSONObject("owner");
            String uid = owner == null ? "" : owner.optString("uid"), oid = identidad == null ? "" : identidad.optString("tiktok_open_id");
            if (sesion.codigo != 200 || uid.isEmpty() || !oid.matches("[!-~]{1,256}")) throw new IOException("Conecta primero tu cuenta de TikTok en Corte antes de importar tu organización anterior.");
            if (estado.has("owner_uid") && (!uid.equals(estado.optString("owner_uid")) || !oid.equals(estado.optString("tiktok_open_id"))))
                throw new IOException("Esta copia ya se vinculó a otra cuenta. El archivo anterior sigue conservado.");
            if (estado.has("attempt_owner_uid") && (!uid.equals(estado.optString("attempt_owner_uid")) || !oid.equals(estado.optString("attempt_tiktok_open_id"))))
                throw new IOException("La importación anterior comenzó en otra cuenta. El archivo original sigue conservado.");
            JSONObject local = localAnterior(), export = new JSONObject().put("formato", "corte-local").put("version", 1)
                    .put("exportado_at", System.currentTimeMillis() / 1000L);
            for (String campo : LISTAS) export.put(campo, local.optJSONArray(campo) == null ? new JSONArray() : local.getJSONArray(campo));
            export.put("preferencias", local.optJSONObject("preferencias") == null ? new JSONObject() : local.getJSONObject("preferencias"));
            byte[] payload = export.toString().getBytes(StandardCharsets.UTF_8);
            if (payload.length > MAX_EXPORT) throw new IOException("La organización anterior supera el límite de importación. Tu archivo sigue conservado.");
            // Vincular el intento ANTES de cualquier mutación; la confirmación se marca sólo tras el 200.
            estado.put("attempt_owner_uid", uid).put("attempt_tiktok_open_id", oid); guardar();
            ClienteHub.Respuesta r = cliente.pedir(new ClienteHub.Peticion("POST", "/api/cloud/import")
                    .cabecera("X-Corte-Expected-Creator", oid).cuerpo(payload).lectura(30000));
            if (r.codigo != 200) throw new IOException("No pudimos importar tu organización anterior. La copia y los cambios siguen conservados.");
            // Los pendientes se restauran como operaciones originales, separados del snapshot confirmado.
            if (operaciones.isFile()) {
                try (BufferedReader lector = new BufferedReader(new InputStreamReader(new FileInputStream(operaciones), StandardCharsets.UTF_8))) {
                    for (String linea; (linea = lector.readLine()) != null;) {
                        if (!linea.trim().isEmpty() && cola.agregar(new JSONArray().put(new JSONObject(linea)).toString()) != 1)
                            throw new IOException("Hay un cambio anterior que supera el límite admitido. El archivo original sigue conservado.");
                    }
                }
            }
            estado.put("owner_uid", uid).put("tiktok_open_id", oid).put("pending", false).put("available", false);
            estado.remove("warning"); guardar();
        } catch (JSONException e) { throw new IOException("No pudimos importar el archivo anterior. La copia sigue conservada.", e); }
    }

    private JSONObject localAnterior() throws IOException, JSONException {
        if (!snapshot.isFile()) return new JSONObject();
        try (InputStream in = new GZIPInputStream(new FileInputStream(snapshot))) {
            // Sólo se interpreta la copia archivada, nunca una superposición de la cola ni credenciales.
            android.util.JsonReader r = new android.util.JsonReader(new InputStreamReader(in, StandardCharsets.UTF_8));
            r.beginObject();
            JSONObject local = new JSONObject();
            while (r.hasNext()) { if ("local".equals(r.nextName())) local = objeto(r, new int[] { 0 }); else r.skipValue(); }
            r.endObject(); return local;
        }
    }

    private static JSONObject objeto(android.util.JsonReader r, int[] tamano) throws IOException, JSONException {
        JSONObject o = new JSONObject(); r.beginObject();
        while (r.hasNext()) { String key = r.nextName(); tamano[0] += key.length(); o.put(key, valor(r, tamano)); }
        r.endObject(); return o;
    }
    private static Object valor(android.util.JsonReader r, int[] tamano) throws IOException, JSONException {
        if (tamano[0] > MAX_EXPORT) throw new IOException("La copia anterior supera el límite de importación.");
        switch (r.peek()) {
            case BEGIN_OBJECT: return objeto(r, tamano);
            case BEGIN_ARRAY:
                JSONArray a = new JSONArray(); r.beginArray(); while (r.hasNext()) a.put(valor(r, tamano)); r.endArray(); return a;
            case STRING: String s = r.nextString(); tamano[0] += s.getBytes(StandardCharsets.UTF_8).length; return s;
            case NUMBER: return new java.math.BigDecimal(r.nextString());
            case BOOLEAN: return r.nextBoolean();
            case NULL: r.nextNull(); return JSONObject.NULL;
            default: throw new IOException("Copia anterior inválida.");
        }
    }

    private int contarPendientes() throws IOException {
        if (!operaciones.isFile()) return 0;
        int n = 0;
        try (BufferedReader r = new BufferedReader(new InputStreamReader(new FileInputStream(operaciones), StandardCharsets.UTF_8))) {
            for (String s; (s = r.readLine()) != null;) if (!s.trim().isEmpty()) n++;
        }
        return n;
    }
    private void guardar() throws IOException { CopiaSinConexion.escribirAtomico(estadoFile, estado.toString().getBytes(StandardCharsets.UTF_8)); }
    private static String leer(File f, int limite) throws IOException {
        try (InputStream in = new FileInputStream(f)) { return new String(CopiaSinConexion.leerTodo(in, limite), StandardCharsets.UTF_8); }
    }
    private static void archivar(File origen, File destino) throws IOException {
        if (!origen.isFile() || destino.isFile()) return;
        File temporal = new File(destino.getPath() + ".nuevo");
        try (InputStream in = new FileInputStream(origen); FileOutputStream out = new FileOutputStream(temporal)) {
            byte[] buf = new byte[65536]; for (int n; (n = in.read(buf)) != -1;) out.write(buf, 0, n); out.getFD().sync();
        }
        if (!Arrays.equals(hash(origen), hash(temporal))) throw new IOException("No pudimos verificar el respaldo anterior.");
        Files.move(temporal.toPath(), destino.toPath(), StandardCopyOption.ATOMIC_MOVE);
    }
    private static byte[] hash(File f) throws IOException {
        try (InputStream in = new FileInputStream(f)) {
            MessageDigest h = MessageDigest.getInstance("SHA-256"); byte[] buf = new byte[65536];
            for (int n; (n = in.read(buf)) != -1;) h.update(buf, 0, n); return h.digest();
        } catch (NoSuchAlgorithmException e) { throw new IOException(e); }
    }
}
