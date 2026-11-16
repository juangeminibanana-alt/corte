package app.creatorhub.red;

import app.creatorhub.datos.AlmacenSeguro;
import java.io.IOException;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONException;
import org.json.JSONObject;

/** HTTPS de sistema y sesión propia del dispositivo. Ninguna credencial cruza el puente JavaScript. */
public final class CanalNube {
    private static final String ENTRADA = "corte.nube.dispositivo.v1";
    private static final String PENDIENTE = "corte.nube.autorizacion.v1";
    private static final String PROPIETARIO = "corte.nube.propietario.v1";
    private final AlmacenSeguro almacen;
    private final Runnable avisar;
    private JSONObject credencial, pendiente;
    private boolean cargada;
    private volatile boolean conectado;
    private volatile String error;
    private volatile long esperaSondeoMs = 3000;

    public CanalNube(AlmacenSeguro almacen, Runnable avisar) { this.almacen = almacen; this.avisar = avisar; }

    private synchronized void cargar() {
        if (cargada) return;
        cargada = true;
        try {
            String c = almacen.leer(ENTRADA), p = almacen.leer(PENDIENTE);
            if (c != null) {
                JSONObject o = new JSONObject(c);
                if (SeguridadNube.tokenValido(o.optString("token"))) credencial = o;
            }
            if (p != null && (credencial == null || credencial.optLong("expires_at", 0) <= ahora())) pendiente = new JSONObject(p);
        } catch (JSONException e) { credencial = null; pendiente = null; }
    }

    public synchronized boolean autenticado() {
        cargar();
        return credencial != null && credencial.optLong("expires_at", 0) > ahora();
    }
    public boolean conectado() { return conectado && autenticado(); }
    public long esperaSondeoMs() { return esperaSondeoMs; }
    public void desconectado() { conectado = false; }
    public synchronized boolean hayPendiente() {
        cargar();
        return pendiente != null && pendiente.optLong("expires_at", 0) > ahora();
    }
    public synchronized JSONObject estado() {
        cargar();
        if (pendiente != null && pendiente.optLong("expires_at", 0) <= ahora()) {
            cancelarPendiente(); error = "El código venció. Vuelve a conectar tu cuenta.";
        }
        if (credencial != null && !autenticado() && error == null) error = "Tu sesión venció. Vuelve a entrar con Google.";
        JSONObject o = new JSONObject();
        try {
            o.put("authenticated", autenticado()).put("connected", conectado()).put("offline", !conectado());
            if (hayPendiente()) o.put("pending", new JSONObject()
                    .put("user_code", pendiente.getString("user_code"))
                    .put("verification_uri", pendiente.getString("verification_uri"))
                    .put("expires_at", pendiente.getLong("expires_at")));
            if (error != null) o.put("error", error);
        } catch (JSONException e) { /* campos fijos */ }
        return o;
    }

    public synchronized String iniciar(String nombre) throws IOException {
        cargar();
        if (hayPendiente()) return pendiente.optString("verification_uri");
        String verifier = SeguridadNube.nuevoVerificador();
        try {
            JSONObject cuerpo = new JSONObject().put("platform", "android").put("name", nombre)
                    .put("code_challenge", SeguridadNube.reto(verifier));
            ClienteHub.Respuesta r = enviar(new ClienteHub.Peticion("POST", "/api/native/auth/start")
                    .cuerpo(cuerpo.toString().getBytes(StandardCharsets.UTF_8)).limite(32 * 1024), null);
            JSONObject o = r.json();
            if (r.codigo != 200 || o == null) throw new IOException("No pudimos iniciar el acceso. Inténtalo de nuevo.");
            String uri = o.optString("verification_uri"), id = o.optString("request_id"), codigo = o.optString("user_code");
            int duracion = o.optInt("expires_in", 0);
            if (!SeguridadNube.verificacionPermitida(uri) || !id.matches("[A-Za-z0-9_-]{16,128}")
                    || codigo.isEmpty() || codigo.length() > 32 || duracion < 1 || duracion > 600)
                throw new IOException("El servidor no confirmó una autorización válida.");
            JSONObject nueva = new JSONObject().put("request_id", id).put("code_verifier", verifier)
                    .put("verification_uri", uri).put("user_code", codigo).put("expires_at", ahora() + duracion);
            almacen.guardar(PENDIENTE, nueva.toString());
            pendiente = nueva;
            error = null;
            return uri;
        } catch (IOException e) { error = e.getMessage(); throw e; }
        catch (JSONException | GeneralSecurityException e) { error = "No pudimos guardar el acceso seguro."; throw new IOException(error, e); }
    }

    /** Una consulta corta; true cuando hay que seguir sondeando. La autorización se persiste antes de anunciarla. */
    public boolean sondear() {
        final JSONObject actual;
        synchronized (this) { cargar(); if (!hayPendiente()) { cancelarPendiente(); return false; } actual = pendiente; }
        try {
            JSONObject cuerpo = new JSONObject().put("request_id", actual.getString("request_id"))
                    .put("code_verifier", actual.getString("code_verifier"));
            ClienteHub.Respuesta r = enviar(new ClienteHub.Peticion("POST", "/api/native/auth/poll")
                    .cuerpo(cuerpo.toString().getBytes(StandardCharsets.UTF_8)).limite(32 * 1024), null);
            if (r.codigo == 429) {
                try { esperaSondeoMs = Math.max(3000, Math.min(60000, Long.parseLong(r.cabecera("Retry-After")) * 1000)); }
                catch (NumberFormatException e) { esperaSondeoMs = 3000; }
                return true;
            }
            esperaSondeoMs = 3000;
            if (r.codigo == 202 || r.codigo >= 500) return true;
            JSONObject o = r.json();
            synchronized (this) {
                if (pendiente != actual) return false; // se cerró la sesión durante la petición
                JSONObject owner = o == null ? null : o.optJSONObject("owner");
                String token = o == null ? "" : o.optString("token"), uid = owner == null ? "" : owner.optString("uid");
                String deviceId = o == null ? "" : o.optString("device_id");
                long expires = o == null ? 0 : o.optLong("expires_at", 0);
                if (r.codigo == 200 && o != null && "autorizado".equals(o.optString("estado")) && SeguridadNube.tokenValido(token)
                        && !uid.isEmpty() && uid.length() <= 128 && deviceId.matches("[A-Za-z0-9_-]{1,128}") && expires > ahora()) {
                    String previo = almacen.leer(PROPIETARIO);
                    if (previo != null && !previo.equals(uid)) {
                        error = "Esta copia y sus cambios pertenecen a otra cuenta. Usa la cuenta original.";
                        cancelarPendiente(); return false;
                    }
                    JSONObject nueva = new JSONObject().put("token", token).put("device_id", deviceId)
                            .put("expires_at", expires).put("owner_uid", uid);
                    almacen.guardar(PROPIETARIO, uid);
                    almacen.guardar(ENTRADA, nueva.toString());
                    credencial = nueva;
                    conectado = true;
                    error = null;
                    cancelarPendiente();
                } else {
                    error = r.codigo == 403 ? "No se autorizó este dispositivo. Vuelve a entrar con tu cuenta de Google."
                            : r.codigo == 410 ? "El código venció. Vuelve a conectar tu cuenta."
                            : "No se pudo completar el acceso. Vuelve a conectar tu cuenta.";
                    cancelarPendiente();
                }
            }
            avisar.run();
            return false;
        } catch (IOException e) { return true; }
        catch (JSONException | GeneralSecurityException e) {
            synchronized (this) { error = "No pudimos guardar el acceso seguro. Vuelve a conectar tu cuenta."; cancelarPendiente(); }
            avisar.run(); return false;
        }
    }

    private synchronized void cancelarPendiente() { pendiente = null; almacen.borrar(PENDIENTE); }
    public void cerrar() {
        synchronized (this) { cancelarPendiente(); }
        try { if (autenticado()) pedir(new ClienteHub.Peticion("POST", "/api/native/devices/self/revoke")
                .cuerpo("{}".getBytes(StandardCharsets.UTF_8)).lectura(8000)); }
        catch (IOException e) { /* La salida local siempre ocurre; el token tiene caducidad en el servidor. */ }
        synchronized (this) { credencial = null; conectado = false; error = null; almacen.borrar(ENTRADA); }
        avisar.run();
    }

    public ClienteHub.Respuesta pedir(ClienteHub.Peticion p) throws IOException {
        final String ruta;
        try { ruta = SeguridadNube.rutaRemota(p.ruta); }
        catch (IllegalArgumentException e) { throw new IOException("Ruta no permitida.", e); }
        if ("POST".equals(p.metodo) && "/api/cloud/import".equals(ruta)
                && !p.cabeceras.containsKey("X-Corte-Expected-Creator")) {
            ClienteHub.Respuesta sesion = pedir(new ClienteHub.Peticion("GET", "/api/native/session"));
            if (sesion.codigo != 200) return sesion;
            JSONObject identidad = sesion.json();
            String oid = identidad == null ? "" : identidad.optString("tiktok_open_id");
            if (!oid.matches("[!-~]{1,256}")) {
                return new ClienteHub.Respuesta(409, "application/json", ("{\"error\":{\"codigo\":\"cuenta_cambio_sin_importar\","
                        + "\"mensaje\":\"Conecta primero tu cuenta de TikTok antes de importar la organización.\"}}")
                        .getBytes(StandardCharsets.UTF_8), new java.util.LinkedHashMap<>());
            }
            p.cabecera("X-Corte-Expected-Creator", oid);
        }
        final String token;
        synchronized (this) { if (!autenticado()) throw new ClienteHub.SinConexion("Vuelve a conectar tu cuenta de Google."); token = credencial.optString("token"); }
        try {
            ClienteHub.Respuesta r = enviar(p, token);
            if (r.codigo == 401) {
                boolean invalidada = false;
                synchronized (this) {
                    if (credencial != null && token.equals(credencial.optString("token"))) {
                        credencial = null; conectado = false; error = "Tu sesión venció. Vuelve a entrar con Google.";
                        almacen.borrar(ENTRADA); invalidada = true;
                    }
                }
                if (invalidada) avisar.run();
            } else if (r.codigo < 500 && (r.codigo < 300 || r.codigo >= 400)) conectado = true;
            return r;
        } catch (IOException e) { conectado = false; throw e; }
    }

    private ClienteHub.Respuesta enviar(ClienteHub.Peticion p, String token) throws IOException {
        String ruta;
        try { ruta = SeguridadNube.rutaRemota(p.ruta); } catch (IllegalArgumentException e) { throw new IOException("Ruta no permitida.", e); }
        HttpsURLConnection c = (HttpsURLConnection) new URL(SeguridadNube.ORIGEN + ruta).openConnection();
        c.setInstanceFollowRedirects(false);
        c.setUseCaches(false);
        c.setConnectTimeout(ClienteHub.CONEXION_MS);
        c.setReadTimeout(p.lecturaMs);
        c.setRequestProperty("Origin", SeguridadNube.ORIGEN);
        c.setRequestProperty("X-CH-Hub", "1");
        if (token != null) c.setRequestProperty("Authorization", "Bearer " + token);
        if (p.enCurso != null) p.enCurso.set(c);
        try { return ClienteHub.intercambiar(c, p); }
        catch (IOException e) { c.disconnect(); throw e; }
        finally { if (p.enCurso != null) p.enCurso.compareAndSet(c, null); }
    }

    private static long ahora() { return System.currentTimeMillis() / 1000L; }
}
