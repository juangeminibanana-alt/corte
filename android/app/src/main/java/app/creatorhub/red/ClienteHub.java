package app.creatorhub.red;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.Network;
import android.os.SystemClock;
import app.creatorhub.datos.AlmacenSeguro;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CompletionService;
import java.util.concurrent.ExecutorCompletionService;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * Canal del celular con el hub de la PC (Protocolo LAN 1; 04 §C.7–C.8; 03 §6.6):
 * - TLS fijado a la huella emparejada (un {@link TlsFijado.Canal} por credencial: keep-alive entre peticiones);
 * - firma CH1 de cada petición (ProtocoloLan.autorizacion) con ts corregido por el desfase con la PC;
 * - 401 `reloj_desfasado`: guarda el desfase (detalle.hora_servidor − hora local) y reintenta UNA vez;
 * - rotación de la clave en dos fases: la nueva se guarda ANTES de usarla; se firma con ella y la primera respuesta
 *   válida la confirma; ante `firma_invalida` con la nueva se vuelve a la anterior (que el hub acepta sin plazo);
 * - reconexión: últimas IP en paralelo (hello fijado, 2 s), luego descubrimiento UDP filtrado por host_id, tope 5 s.
 * Nunca registra cuerpos, claves ni firmas.
 */
public final class ClienteHub {
    static final String ENTRADA = "credencial";
    static final long ROTAR_CADA_S = 30L * 24 * 3600;
    public static final int CONEXION_MS = 4000;
    public static final int LECTURA_MS = 15000;

    /** Avisa a la capa de arriba (Nucleo) de cualquier cambio de conectado / revocado / incompatible. */
    public interface Oyente { void cambioDeEstado(); }

    /** Lo que guarda el Keystore (04 §B.6): identidad de la PC, credencial del dispositivo y estado de la rotación. */
    public static final class Credencial {
        public String hostId, deviceId, huella, nombreEquipo, permisos;
        public int puerto, protocolo = 1;
        public List<String> direcciones = new ArrayList<>();
        byte[] deviceKey, clavePendiente;
        public long claveRotadaAt, desfaseS;

        String aJson() throws JSONException {
            JSONObject o = new JSONObject()
                    .put("host_id", hostId).put("device_id", deviceId).put("device_key", ProtocoloLan.b64u(deviceKey))
                    .put("huella_tls", huella).put("nombre_equipo", nombreEquipo).put("puerto", puerto)
                    .put("direcciones", new JSONArray(direcciones)).put("permisos", permisos).put("protocolo", protocolo)
                    .put("clave_rotada_at", claveRotadaAt).put("desfase_s", desfaseS);
            if (clavePendiente != null) o.put("clave_pendiente", ProtocoloLan.b64u(clavePendiente));
            return o.toString();
        }

        static Credencial deJson(String texto) throws JSONException {
            JSONObject o = new JSONObject(texto);
            Credencial c = new Credencial();
            c.hostId = o.getString("host_id");
            c.deviceId = o.getString("device_id");
            c.deviceKey = ProtocoloLan.b64uDec(o.getString("device_key"));
            c.huella = o.getString("huella_tls");
            c.nombreEquipo = o.optString("nombre_equipo", "PC");
            c.puerto = o.optInt("puerto", ProtocoloLan.PUERTO_LAN);
            c.permisos = o.optString("permisos", "lectura");
            c.protocolo = o.optInt("protocolo", 1);
            JSONArray d = o.optJSONArray("direcciones");
            if (d != null) for (int i = 0; i < d.length() && i < 3; i++) c.direcciones.add(d.getString(i));
            c.claveRotadaAt = o.optLong("clave_rotada_at", 0);
            c.desfaseS = o.optLong("desfase_s", 0);
            String p = o.optString("clave_pendiente", "");
            c.clavePendiente = p.isEmpty() ? null : ProtocoloLan.b64uDec(p);
            if (!ProtocoloLan.esHostId(c.hostId) || !ProtocoloLan.esHuella(c.huella) || c.deviceKey.length != 32) {
                throw new JSONException("credencial inválida");
            }
            return c;
        }

        /** Construye la credencial a partir del LanPaquete descifrado (validado por el Emparejador). */
        static Credencial dePaquete(JSONObject paquete, String ip, long ahora) throws JSONException {
            Credencial c = new Credencial();
            c.hostId = paquete.getString("host_id");
            c.deviceId = paquete.getString("device_id");
            c.deviceKey = ProtocoloLan.b64uDec(paquete.getString("device_key"));
            c.huella = paquete.getString("huella_tls");
            c.nombreEquipo = paquete.getString("nombre_equipo");
            c.puerto = paquete.getInt("puerto");
            c.permisos = paquete.getString("permisos");
            c.protocolo = paquete.getInt("protocolo");
            c.direcciones.add(ip);
            c.claveRotadaAt = ahora;
            return c;
        }
    }

    /** Una petición firmada hacia `ruta` (= ruta COMPLETA en el cable, p. ej. '/lan/v1/api/session?x=1'). */
    public static final class Peticion {
        final String metodo, ruta;
        byte[] cuerpo;
        String tipo = "application/json; charset=utf-8";
        int lecturaMs = LECTURA_MS;
        long limite = 8L * 1024 * 1024;
        boolean gzipCrudo;
        File archivo;
        java.util.concurrent.atomic.AtomicReference<HttpsURLConnection> enCurso;
        final Map<String, String> cabeceras = new LinkedHashMap<>();

        public Peticion(String metodo, String ruta) { this.metodo = metodo.toUpperCase(Locale.ROOT); this.ruta = ruta; }
        public Peticion cuerpo(byte[] c) { cuerpo = c; return this; }
        public Peticion lectura(int ms) { lecturaMs = ms; return this; }
        public Peticion limite(long bytes) { limite = bytes; return this; }
        /** Pide gzip y NO lo descomprime (la copia se guarda tal cual llega). */
        public Peticion gzipCrudo() { gzipCrudo = true; return this; }
        /** Escribe el cuerpo de una respuesta 200 en este archivo en lugar de memoria. */
        public Peticion aArchivo(File f) { archivo = f; return this; }
        public Peticion cabecera(String k, String v) { cabeceras.put(k, v); return this; }
        /** Deja la conexión en `ref` para poder cortarla desde otro hilo (long-poll al pasar a segundo plano). */
        public Peticion cancelable(java.util.concurrent.atomic.AtomicReference<HttpsURLConnection> ref) { enCurso = ref; return this; }
    }

    /** Respuesta del hub. El cuerpo nunca se registra. */
    public static final class Respuesta {
        public final int codigo;
        public final String tipo;
        public final byte[] cuerpo;
        final Map<String, String> cabeceras;

        Respuesta(int codigo, String tipo, byte[] cuerpo, Map<String, String> cabeceras) {
            this.codigo = codigo; this.tipo = tipo == null ? "application/octet-stream" : tipo;
            this.cuerpo = cuerpo == null ? new byte[0] : cuerpo; this.cabeceras = cabeceras;
        }

        public String cabecera(String nombre) {
            for (Map.Entry<String, String> e : cabeceras.entrySet()) {
                if (e.getKey().equalsIgnoreCase(nombre)) return e.getValue();
            }
            return null;
        }

        public JSONObject json() {
            try { return new JSONObject(new String(cuerpo, StandardCharsets.UTF_8)); }
            catch (JSONException e) { return null; }
        }

        /** ErrorRespuesta.error.codigo o null. */
        public String codigoError() {
            JSONObject o = json();
            JSONObject e = o == null ? null : o.optJSONObject("error");
            return e == null ? null : e.optString("codigo", null);
        }

        long horaServidor() {
            JSONObject o = json();
            JSONObject e = o == null ? null : o.optJSONObject("error");
            JSONObject d = e == null ? null : e.optJSONObject("detalle");
            return d == null ? -1 : d.optLong("hora_servidor", -1);
        }
    }

    /** No hay PC emparejada o alcanzable (el proxy responde con la copia o 503 sin_conexion). */
    public static final class SinConexion extends IOException {
        public SinConexion(String m) { super(m); }
    }

    private final Context ctx;
    private final AlmacenSeguro almacen;
    private final Object candado = new Object();
    private Credencial cred;                 // con candado
    private TlsFijado.Canal canal;           // con candado
    private boolean cargada;                 // con candado: la credencial ya se leyó del Keystore
    private volatile String ip;
    private volatile int puerto;
    private volatile boolean conectado, revocado, rotacionPedida;
    private volatile String incompatible;
    private volatile JSONObject ultimaSesion;
    private volatile Oyente oyente;
    private volatile Network redActual;

    /** No toca el disco (se construye en el hilo principal): la credencial se lee en el primer uso, siempre en otro hilo. */
    public ClienteHub(Context ctx, AlmacenSeguro almacen) {
        this.ctx = ctx.getApplicationContext();
        this.almacen = almacen;
    }

    /** Lee la credencial del Keystore la primera vez que se necesita. Se llama con `candado` tomado. */
    private void cargar() {
        if (cargada) return;
        cargada = true;
        String guardada = almacen.leer(ENTRADA);
        if (guardada == null) return;
        try {
            Credencial c = Credencial.deJson(guardada);
            cred = c;
            canal = new TlsFijado.Canal(c.huella);
            if (puerto == 0) puerto = c.puerto;
        } catch (JSONException | GeneralSecurityException | IllegalArgumentException e) {
            cred = null;   // ilegible: la interfaz pide emparejar de nuevo
        }
    }

    public void fijarOyente(Oyente o) { oyente = o; }

    private void avisar() {
        Oyente o = oyente;
        if (o != null) o.cambioDeEstado();
    }

    // ------------------------------------------------------------------ estado (sin secretos)
    public boolean emparejado() { synchronized (candado) { cargar(); return cred != null; } }
    public boolean conectado() { return conectado && emparejado(); }
    public boolean revocado() { return revocado; }
    public String incompatible() { return incompatible; }
    public String ip() { return conectado ? ip : null; }
    public int puerto() { return puerto; }
    public JSONObject ultimaSesion() { return ultimaSesion; }

    public String hostId() { synchronized (candado) { cargar(); return cred == null ? null : cred.hostId; } }
    public String nombreEquipo() { synchronized (candado) { cargar(); return cred == null ? null : cred.nombreEquipo; } }
    public String permisos() { synchronized (candado) { cargar(); return cred == null ? null : cred.permisos; } }
    public List<String> direcciones() {
        synchronized (candado) { cargar(); return cred == null ? Collections.emptyList() : new ArrayList<>(cred.direcciones); }
    }
    /** Solo para pruebas de depuración: desfase actual en segundos (no es secreto). */
    public long desfase() { synchronized (candado) { cargar(); return cred == null ? 0 : cred.desfaseS; } }
    public boolean hayClavePendiente() { synchronized (candado) { cargar(); return cred != null && cred.clavePendiente != null; } }

    public void marcarDesconectado() {
        if (conectado) { conectado = false; avisar(); }
    }

    // ------------------------------------------------------------------ alta / baja
    /** Guarda la credencial recién emparejada (Emparejador) y fija su huella. */
    void establecer(Credencial c, String ipActual) throws IOException {
        try {
            TlsFijado.Canal k = new TlsFijado.Canal(c.huella);
            almacen.guardar(ENTRADA, c.aJson());
            synchronized (candado) { cargar(); cred = c; canal = k; }
        } catch (GeneralSecurityException | JSONException e) {
            throw new IOException("No se pudo guardar la credencial", e);
        }
        ip = ipActual;
        puerto = c.puerto;
        revocado = false;
        incompatible = null;
        conectado = false;
        avisar();
    }

    /** "Olvidar esta PC": borra la credencial del Keystore. */
    public void olvidar() {
        synchronized (candado) { cargar();
            if (cred != null) {
                Arrays.fill(cred.deviceKey, (byte) 0);
                if (cred.clavePendiente != null) Arrays.fill(cred.clavePendiente, (byte) 0);
            }
            cred = null;
            canal = null;
        }
        almacen.borrar(ENTRADA);
        ip = null;
        conectado = false;
        revocado = false;
        incompatible = null;
        ultimaSesion = null;
        avisar();
    }

    private void persistir() {
        try {
            String j;
            synchronized (candado) { cargar(); if (cred == null) return; j = cred.aJson(); }
            almacen.guardar(ENTRADA, j);
        } catch (GeneralSecurityException | IOException | JSONException e) {
            // se reintenta en el siguiente cambio; la credencial en memoria sigue siendo válida
        }
    }

    // ------------------------------------------------------------------ peticiones firmadas
    static long ahoraLocal() { return System.currentTimeMillis() / 1000L; }

    /**
     * La red Wi-Fi/Ethernet. Se devuelve SIEMPRE la misma instancia mientras sea la misma red: cada objeto Network
     * de Android tiene su propio pool de conexiones, y getAllNetworks() entrega objetos nuevos en cada llamada; sin
     * esto no habría keep-alive (un handshake TLS por petición y conexiones ociosas acumuladas).
     */
    Network red() {
        Network actual = DescubrimientoLan.redLocal(ctx.getSystemService(ConnectivityManager.class));
        Network previa = redActual;
        if (actual == null) { redActual = null; return null; }
        if (actual.equals(previa)) return previa;      // equals = mismo netId
        redActual = actual;
        return actual;
    }

    /**
     * Petición firmada CH1 a la PC conectada. Reintenta una vez por `reloj_desfasado` (con el desfase corregido) y una
     * vez por `firma_invalida` si estaba probando la clave nueva de una rotación.
     */
    public Respuesta pedir(Peticion p) throws IOException {
        TlsFijado.Canal k;
        String deviceId;
        synchronized (candado) { cargar();
            if (cred == null) throw new SinConexion("sin emparejar");
            k = canal;
            deviceId = cred.deviceId;
        }
        String ipU = ip;
        int pu = puerto;
        if (ipU == null) throw new SinConexion("sin dirección de la PC");
        boolean reintentoReloj = false, reintentoClave = false;
        while (true) {
            byte[] clave;
            long ts;
            boolean conPendiente;
            synchronized (candado) { cargar();
                if (cred == null) throw new SinConexion("sin emparejar");
                conPendiente = cred.clavePendiente != null;
                clave = (conPendiente ? cred.clavePendiente : cred.deviceKey).clone();
                ts = ahoraLocal() + cred.desfaseS;
            }
            Respuesta r;
            try {
                r = enviar(k, ipU, pu, p, deviceId, clave, ts);
            } finally {
                Arrays.fill(clave, (byte) 0);
            }
            if (r.codigo == 401) {
                String e = r.codigoError();
                if ("reloj_desfasado".equals(e) && !reintentoReloj) {
                    long hs = r.horaServidor();
                    if (hs > 0) {
                        synchronized (candado) { cargar(); if (cred != null) cred.desfaseS = hs - ahoraLocal(); }
                        persistir();
                    }
                    reintentoReloj = true;
                    continue;
                }
                if ("firma_invalida".equals(e) && conPendiente && !reintentoClave) {
                    synchronized (candado) { cargar();
                        if (cred != null && cred.clavePendiente != null) {
                            Arrays.fill(cred.clavePendiente, (byte) 0);
                            cred.clavePendiente = null;
                        }
                    }
                    persistir();
                    reintentoClave = true;
                    continue;
                }
                if ("dispositivo_revocado".equals(e) || "dispositivo_desconocido".equals(e)) {
                    revocado = true;
                    conectado = false;
                    avisar();
                }
                return r;
            }
            if (((r.codigo >= 200 && r.codigo < 300) || r.codigo == 304) && conPendiente) {   // 304 también pasó CH1
                synchronized (candado) { cargar();   // fase 2: el hub ya descartó la anterior; la nueva queda como vigente
                    if (cred != null && cred.clavePendiente != null) {
                        Arrays.fill(cred.deviceKey, (byte) 0);
                        cred.deviceKey = cred.clavePendiente;
                        cred.clavePendiente = null;
                        cred.claveRotadaAt = ahoraLocal();
                    }
                }
                persistir();
            }
            if ("1".equals(r.cabecera("X-CH-Rotar"))) rotacionPedida = true;
            return r;
        }
    }

    private Respuesta enviar(TlsFijado.Canal k, String ipU, int pu, Peticion p, String deviceId, byte[] clave, long ts)
            throws IOException {
        URL url = new URL("https", ipU, pu, p.ruta);
        HttpsURLConnection c = k.abrir(red(), url, CONEXION_MS, p.lecturaMs);
        if (p.enCurso != null) p.enCurso.set(c);
        try {
            String aut = ProtocoloLan.autorizacion(deviceId, clave, p.metodo, p.ruta, p.cuerpo, ts, ProtocoloLan.nuevoNonce());
            c.setRequestProperty("Authorization", aut);
            return intercambiar(c, p);
        } catch (GeneralSecurityException e) {
            c.disconnect();
            throw new IOException("No se pudo firmar la petición", e);
        } catch (IOException e) {
            c.disconnect();
            throw e;
        } finally {
            if (p.enCurso != null) p.enCurso.compareAndSet(c, null);
        }
    }

    /** Envía y lee sin firmar (hello, pair/*) o ya firmada. No llama disconnect() en el camino feliz (keep-alive). */
    static Respuesta intercambiar(HttpsURLConnection c, Peticion p) throws IOException {
        c.setRequestMethod(p.metodo);
        c.setRequestProperty("Accept", "application/json");
        if (p.gzipCrudo) c.setRequestProperty("Accept-Encoding", "gzip");
        for (Map.Entry<String, String> e : p.cabeceras.entrySet()) c.setRequestProperty(e.getKey(), e.getValue());
        boolean conCuerpo = "POST".equals(p.metodo) || "PUT".equals(p.metodo) || "PATCH".equals(p.metodo);
        if (conCuerpo) {
            byte[] b = p.cuerpo == null ? new byte[0] : p.cuerpo;
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", p.tipo);
            // Sin setFixedLengthStreamingMode: el cuerpo (pequeño) queda en memoria y la pila HTTP puede reenviarlo
            // sola si la conexión reutilizada del pool ya estaba cerrada por la PC (keep-alive vencido).
            try (OutputStream os = c.getOutputStream()) { os.write(b); }
        }
        int codigo = c.getResponseCode();
        Map<String, String> cab = new LinkedHashMap<>();
        for (Map.Entry<String, List<String>> e : c.getHeaderFields().entrySet()) {
            if (e.getKey() != null && e.getValue() != null && !e.getValue().isEmpty()) cab.put(e.getKey(), e.getValue().get(0));
        }
        InputStream in = codigo >= 400 ? c.getErrorStream() : (codigo == 204 || codigo == 304 ? null : c.getInputStream());
        byte[] cuerpo = new byte[0];
        if (in != null) {
            try (InputStream x = in) {
                if (p.archivo != null && codigo == 200) {
                    copiarAArchivo(x, p.archivo, p.limite);
                } else {
                    cuerpo = leerTodo(x, codigo >= 400 ? 64 * 1024 : p.limite);
                }
            }
        }
        return new Respuesta(codigo, c.getContentType(), cuerpo, cab);
    }

    static byte[] leerTodo(InputStream in, long limite) throws IOException {
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        byte[] buf = new byte[16384];
        for (int n; (n = in.read(buf)) != -1; ) {
            if (b.size() + n > limite) throw new IOException("Respuesta demasiado grande");
            b.write(buf, 0, n);
        }
        return b.toByteArray();
    }

    private static void copiarAArchivo(InputStream in, File destino, long limite) throws IOException {
        long total = 0;
        try (FileOutputStream os = new FileOutputStream(destino)) {
            byte[] buf = new byte[65536];
            for (int n; (n = in.read(buf)) != -1; ) {
                total += n;
                if (total > limite) throw new IOException("Respuesta demasiado grande");
                os.write(buf, 0, n);
            }
            os.getFD().sync();
        }
    }

    // ------------------------------------------------------------------ hello y reconexión (§C.8)
    /** GET /lan/v1/hello fijado: exige app, protocolo compatible y el host_id emparejado. */
    JSONObject hola(TlsFijado.Canal k, String hostId, String ipU, int pu, int ms) throws IOException {
        HttpsURLConnection c = k.abrir(red(), new URL("https", ipU, pu, "/lan/v1/hello"), ms, ms);
        Respuesta r;
        try {
            r = intercambiar(c, new Peticion("GET", "/lan/v1/hello").limite(16 * 1024));
        } catch (IOException e) {
            c.disconnect();
            throw e;
        }
        JSONObject h = r.json();
        if (r.codigo != 200 || h == null || !"creator-hub".equals(h.optString("app"))) throw new IOException("No es Corte");
        int prot = h.optInt("protocolo", -1);
        if (prot != ProtocoloLan.PROTOCOLO) {
            incompatible = prot > ProtocoloLan.PROTOCOLO ? "actualiza_app" : "actualiza_pc";
            avisar();
            throw new IOException("version");
        }
        if (hostId != null && !hostId.equals(h.optString("host_id"))) throw new IOException("Es otra PC");
        return h;
    }

    /**
     * Encuentra la PC y abre sesión (04 §C.8): últimas IP:puerto en paralelo (2 s), si no, descubrimiento UDP
     * filtrado por host_id (1.5 s), y GET /lan/v1/api/session firmado. Tope total `topeMs` (5 s en la app).
     */
    public boolean conectar(int topeMs) {
        final TlsFijado.Canal k;
        final String hostId;
        final int puertoGuardado;
        final List<String> ips = new ArrayList<>();
        synchronized (candado) { cargar();
            if (cred == null) return false;
            k = canal;
            hostId = cred.hostId;
            puertoGuardado = cred.puerto;
            Set<String> s = new LinkedHashSet<>();
            if (ip != null) s.add(ip);
            s.addAll(cred.direcciones);
            ips.addAll(s);
        }
        long fin = SystemClock.elapsedRealtime() + topeMs;
        String[] hallado = probarEnParalelo(k, hostId, ips, puerto > 0 ? puerto : puertoGuardado,
                (int) Math.min(2000, Math.max(500, topeMs - 500)));
        long resta = fin - SystemClock.elapsedRealtime();
        if (hallado == null && resta > 600) {
            try {
                List<DescubrimientoLan.Pc> pcs = DescubrimientoLan.buscar(ctx, (int) Math.min(1500, resta - 400), ips, hostId);
                if (!pcs.isEmpty()) {
                    DescubrimientoLan.Pc pc = pcs.get(0);
                    resta = fin - SystemClock.elapsedRealtime();
                    hola(k, hostId, pc.ip, pc.puerto, (int) Math.max(500, Math.min(2000, resta)));
                    hallado = new String[] {pc.ip, String.valueOf(pc.puerto)};
                }
            } catch (IOException e) {
                hallado = null;
            }
        }
        if (hallado == null) {
            marcarDesconectado();
            return false;
        }
        ip = hallado[0];
        puerto = Integer.parseInt(hallado[1]);
        boolean cambio = false;
        synchronized (candado) { cargar();
            if (cred == null) return false;
            if (cred.puerto != puerto) { cred.puerto = puerto; cambio = true; }
            if (cred.direcciones.isEmpty() || !cred.direcciones.get(0).equals(ip)) {
                cred.direcciones.remove(ip);
                cred.direcciones.add(0, ip);
                while (cred.direcciones.size() > 3) cred.direcciones.remove(cred.direcciones.size() - 1);
                cambio = true;
            }
        }
        if (cambio) persistir();
        try {
            Respuesta r = pedir(new Peticion("GET", "/lan/v1/api/session").lectura(8000));
            if (r.codigo == 200) {
                ultimaSesion = r.json();
                incompatible = null;
                boolean antes = conectado;
                conectado = true;
                if (!antes) avisar();
                return true;
            }
        } catch (IOException e) {
            // cae a desconectado
        }
        marcarDesconectado();
        return false;
    }

    private String[] probarEnParalelo(TlsFijado.Canal k, String hostId, List<String> ips, int pu, int ms) {
        if (ips.isEmpty()) return null;
        ExecutorService ex = Executors.newFixedThreadPool(Math.min(4, ips.size()));
        try {
            CompletionService<String[]> cs = new ExecutorCompletionService<>(ex);
            List<Future<String[]>> futuros = new ArrayList<>();
            for (String i : ips) {
                if (DescubrimientoLan.ipPrivada(i) == null) continue;
                futuros.add(cs.submit(() -> { hola(k, hostId, i, pu, ms); return new String[] {i, String.valueOf(pu)}; }));
            }
            long fin = SystemClock.elapsedRealtime() + ms + 300;
            for (int n = 0; n < futuros.size(); n++) {
                long resta = fin - SystemClock.elapsedRealtime();
                if (resta <= 0) break;
                Future<String[]> f = cs.poll(resta, TimeUnit.MILLISECONDS);
                if (f == null) break;
                try { return f.get(); } catch (Exception fallo) { /* esa IP no respondió: la siguiente */ }
            }
            return null;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return null;
        } finally {
            ex.shutdownNow();
        }
    }

    // ------------------------------------------------------------------ rotación (dos fases)
    /** POST /lan/v1/rotar si el hub lo pidió (X-CH-Rotar: 1) o pasaron 30 días. La nueva se guarda antes de usarla. */
    public boolean rotarSiToca(boolean forzar) throws IOException {
        long rotada;
        synchronized (candado) { cargar();
            if (cred == null || cred.clavePendiente != null) return false;
            rotada = cred.claveRotadaAt;
        }
        if (!forzar && !rotacionPedida && ahoraLocal() - rotada < ROTAR_CADA_S) return false;
        if (!conectado()) return false;
        Respuesta r = pedir(new Peticion("POST", "/lan/v1/rotar").cuerpo(new byte[0]));
        if (r.codigo != 200) return false;
        JSONObject o = r.json();
        byte[] nueva;
        try {
            nueva = ProtocoloLan.b64uDec(o == null ? "" : o.optString("device_key", ""));
        } catch (IllegalArgumentException e) {
            return false;
        }
        if (nueva.length != 32) return false;
        synchronized (candado) { cargar();
            if (cred == null) return false;
            cred.clavePendiente = nueva;
        }
        persistir();                  // ANTES de firmar con ella (perder la respuesta no deja fuera al teléfono)
        rotacionPedida = false;
        return true;
    }

    /** Hora de la última sincronización OK de la PC según la última SessionResponse (0 si no hay). */
    public long ultimaSyncOkAt() {
        JSONObject s = ultimaSesion;
        if (s == null) return 0;
        JSONObject sync = s.optJSONObject("sync");
        long a = sync == null ? 0 : sync.optLong("ultima_ok_at", 0);
        if (a > 0) return a;
        JSONObject datos = s.optJSONObject("datos");
        return datos == null ? 0 : datos.optLong("ultima_sync_ok_at", 0);
    }

    public boolean syncEnCursoSegunSesion() {
        JSONObject s = ultimaSesion;
        JSONObject sync = s == null ? null : s.optJSONObject("sync");
        return sync != null && sync.optBoolean("en_curso", false);
    }

    /** Vuelve a pedir /api/session (para decidir si actualizarAhora dispara una sync). */
    public JSONObject refrescarSesion() throws IOException {
        Respuesta r = pedir(new Peticion("GET", "/lan/v1/api/session").lectura(8000));
        if (r.codigo != 200) throw new IOException("session " + r.codigo);
        ultimaSesion = r.json();
        return ultimaSesion;
    }

    /** Solo la prueba de depuración (src/debug): simula un reloj atrasado para ejercitar el reintento. */
    void forzarDesfase(long s) {
        synchronized (candado) { cargar(); if (cred != null) cred.desfaseS = s; }
    }

    /** Fija la dirección actual sin hello (solo lo usa el emparejamiento tras validar la PC). */
    void fijarDireccion(String ipU, int pu) { ip = ipU; puerto = pu; }

    void marcarConectado(JSONObject sesion) {
        ultimaSesion = sesion;
        boolean antes = conectado;
        conectado = true;
        if (!antes) avisar();
    }
}
