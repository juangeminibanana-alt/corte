package app.creatorhub.datos;

import android.content.Context;
import app.creatorhub.red.ClienteHub;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * Cola de cambios hechos en el celular (04 §B.4; contrato OpLocal / OpsRequest / OpsResponse):
 * `files/cola/ops.jsonl` (una OpLocal por línea, persistida con fsync ANTES de responder a la interfaz), idempotente
 * por `op_id`, envío en lotes de ≤ 200 a POST /lan/v1/api/local/ops. Cada op con resultado (aplicada, duplicada,
 * conflicto o invalida) sale de la cola; las demás esperan al siguiente envío.
 */
public final class ColaOps {
    public static final int LOTE = 200;
    static final int TOPE = 5000;
    private static final Pattern OP_ID = Pattern.compile("[A-Za-z0-9_.:-]{1,80}");
    private static final Set<String> TIPOS = new HashSet<>(Arrays.asList(
            "plan.crear", "plan.editar", "plan.borrar", "nota.crear", "nota.editar", "nota.borrar",
            "recordatorio.crear", "recordatorio.editar", "recordatorio.borrar", "aviso.crear", "aviso.editar",
            "plantilla.editar", "preferencias.editar"));

    private final File dir, archivo;
    private final Object candadoEnvio = new Object();
    private final LinkedHashMap<String, String> ops = new LinkedHashMap<>();   // op_id → JSON de la OpLocal (con this)
    private boolean cargada;                                                    // con this

    /** No toca el disco (se construye en el hilo principal): ops.jsonl se lee en el primer uso, en otro hilo. */
    public ColaOps(Context ctx) {
        dir = new File(ctx.getFilesDir(), "cola");
        archivo = new File(dir, "ops.jsonl");
    }

    /** Lee ops.jsonl la primera vez. Se llama con `this` tomado. */
    private void cargar() {
        if (cargada) return;
        cargada = true;
        ops.clear();
        if (!archivo.isFile()) return;
        try (BufferedReader r = new BufferedReader(new InputStreamReader(new FileInputStream(archivo), StandardCharsets.UTF_8))) {
            for (String linea; (linea = r.readLine()) != null; ) {
                if (linea.trim().isEmpty()) continue;
                try {
                    JSONObject o = new JSONObject(linea);
                    String id = o.optString("op_id", "");
                    if (valida(o)) ops.put(id, o.toString());
                } catch (JSONException ignorada) {
                    // una línea cortada por un apagón: se descarta solo esa
                }
            }
        } catch (IOException e) {
            ops.clear();
        }
    }

    static boolean valida(JSONObject o) {
        return OP_ID.matcher(o.optString("op_id", "")).matches() && TIPOS.contains(o.optString("tipo", ""));
    }

    /**
     * Agrega las OpLocal de `json` (arreglo) a la cola y la persiste. Devuelve cuántas quedaron aceptadas (las
     * repetidas por op_id cuentan como aceptadas: la cola es idempotente). Lanza si el JSON no es un arreglo de ops.
     */
    public synchronized int agregar(String json) throws JSONException, IOException {
        cargar();
        JSONArray a = new JSONArray(json);
        if (a.length() > LOTE) throw new JSONException("demasiadas operaciones en una llamada");
        List<JSONObject> nuevas = new ArrayList<>();
        int aceptadas = 0;
        for (int i = 0; i < a.length(); i++) {
            JSONObject o = a.optJSONObject(i);
            if (o == null || !valida(o)) continue;
            if (o.toString().length() > 64 * 1024) continue;
            aceptadas++;
            if (!ops.containsKey(o.getString("op_id"))) nuevas.add(o);
        }
        if (ops.size() + nuevas.size() > TOPE) throw new IOException("La cola de cambios está llena");
        if (nuevas.isEmpty()) return aceptadas;
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("sin carpeta de cola");
        StringBuilder sb = new StringBuilder();
        if (terminaSinSalto(archivo)) sb.append('\n');       // una línea cortada por un apagón no se come la nueva
        for (JSONObject o : nuevas) sb.append(o.toString()).append('\n');
        try (FileOutputStream os = new FileOutputStream(archivo, true)) {
            os.write(sb.toString().getBytes(StandardCharsets.UTF_8));
            os.getFD().sync();
        }
        for (JSONObject o : nuevas) ops.put(o.getString("op_id"), o.toString());
        return aceptadas;
    }

    private static boolean terminaSinSalto(File f) {
        if (!f.isFile() || f.length() == 0) return false;
        try (java.io.RandomAccessFile r = new java.io.RandomAccessFile(f, "r")) {
            r.seek(f.length() - 1);
            return r.read() != '\n';
        } catch (IOException e) {
            return false;
        }
    }

    /** OpLocal[] aún no confirmadas por el hub. */
    public synchronized JSONArray pendientes() {
        cargar();
        JSONArray a = new JSONArray();
        for (String s : ops.values()) {
            try { a.put(new JSONObject(s)); } catch (JSONException ignorada) { /* ya validada al entrar */ }
        }
        return a;
    }

    public synchronized int cantidad() { cargar(); return ops.size(); }

    /**
     * Envía la cola en lotes de ≤ 200. Devuelve {resultados: OpsResultado[], pendientes: OpLocal[]} (detalle de
     * creatorhub-ops) o null si no había nada que enviar. Lanza IOException si se perdió la conexión.
     */
    public JSONObject enviar(ClienteHub cliente) throws IOException {
        synchronized (candadoEnvio) {          // un envío a la vez (bucle, ops() y actualizarAhora pueden coincidir)
            return enviarSinCompetencia(cliente);
        }
    }

    private JSONObject enviarSinCompetencia(ClienteHub cliente) throws IOException {
        JSONArray resultados = new JSONArray();
        boolean algo = false;
        while (true) {
            List<String> ids = new ArrayList<>();
            JSONArray lote = new JSONArray();
            synchronized (this) {
                cargar();
                for (Map.Entry<String, String> e : ops.entrySet()) {
                    if (ids.size() >= LOTE) break;
                    try { lote.put(new JSONObject(e.getValue())); ids.add(e.getKey()); }
                    catch (JSONException ignorada) { /* ya validada */ }
                }
            }
            if (ids.isEmpty()) break;
            algo = true;
            byte[] cuerpo;
            try { cuerpo = new JSONObject().put("ops", lote).toString().getBytes(StandardCharsets.UTF_8); }
            catch (JSONException e) { throw new IOException("lote", e); }
            ClienteHub.Respuesta r = cliente.pedir(new ClienteHub.Peticion("POST", "/lan/v1/api/local/ops").cuerpo(cuerpo).lectura(30_000));
            Set<String> resueltas = new HashSet<>();
            if (r.codigo == 200) {
                JSONObject o = r.json();
                JSONArray rs = o == null ? null : o.optJSONArray("resultados");
                if (rs != null) {
                    for (int i = 0; i < rs.length(); i++) {
                        JSONObject x = rs.optJSONObject(i);
                        if (x == null) continue;
                        resultados.put(x);
                        resueltas.add(x.optString("op_id"));
                    }
                }
            } else if (r.codigo == 403) {
                // permiso 'lectura': el hub nunca las va a aplicar; salen como inválidas para no trabar la cola
                for (String id : ids) {
                    try { resultados.put(new JSONObject().put("op_id", id).put("estado", "invalida").put("error", "prohibido")); }
                    catch (JSONException ignorada) { /* claves fijas */ }
                    resueltas.add(id);
                }
            } else {
                throw new IOException("ops " + r.codigo);
            }
            quitar(resueltas);
            if (resueltas.isEmpty()) break;      // el hub no resolvió nada: no insistir en un bucle
        }
        if (!algo) return null;
        try {
            return new JSONObject().put("resultados", resultados).put("pendientes", pendientes());
        } catch (JSONException e) {
            throw new IOException("ops", e);
        }
    }

    private synchronized void quitar(Set<String> ids) throws IOException {
        if (ids.isEmpty()) return;
        for (String id : ids) ops.remove(id);
        reescribir();
    }

    private void reescribir() throws IOException {
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("sin carpeta de cola");
        StringBuilder sb = new StringBuilder();
        for (String s : ops.values()) sb.append(s).append('\n');
        CopiaSinConexion.escribirAtomico(archivo, sb.toString().getBytes(StandardCharsets.UTF_8));
    }

    /** "Olvidar esta PC": la cola se borra (la interfaz ya avisó cuántos cambios se perderán). */
    public synchronized void borrarTodo() {
        cargada = true;                      // lo que hubiera en disco ya no cuenta
        ops.clear();
        if (archivo.exists() && !archivo.delete()) archivo.deleteOnExit();
    }
}
