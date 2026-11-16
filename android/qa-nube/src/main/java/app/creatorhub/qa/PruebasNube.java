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
            resultado.putString("native_checks", "PASS: Keystore, PKCE, rutas, fsync, deduplicacion, UTF8, archivo SHA256, defer, DTO limpio, cache ETag y reintentos acotados");
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
        String dto = Nucleo.de(aislado).estadoNativo().toString();
        comprobar(!dto.contains("\"token\"") && !dto.contains("code_verifier") && !dto.contains("tiktok_open_id")
                && !dto.contains("owner_uid") && new JSONObject(dto).getBoolean("native_client"), "DTO limpio");
    }

    private static byte[] hash(File f) throws Exception { return MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(f.toPath())); }
    private static void comprobar(boolean valor, String mensaje) { if (!valor) throw new AssertionError(mensaje); }
}
