package app.creatorhub;

import android.content.Context;
import android.os.SystemClock;
import app.creatorhub.datos.AlmacenSeguro;
import app.creatorhub.datos.ColaOps;
import app.creatorhub.datos.CopiaSinConexion;
import app.creatorhub.datos.MigracionNube;
import app.creatorhub.red.ClienteHub;
import app.creatorhub.red.Emparejador;
import app.creatorhub.red.ControlPrecargaImagenes;
import java.io.IOException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * Estado nativo de la app (uno por proceso): credencial y canal con la PC (ClienteHub), copia sin conexión, cola de
 * cambios y el bucle de cambios (C27): con la app al frente hace el long-poll GET /lan/v1/api/cambios?…&img_rev=…
 * (espera_s=25, lectura 30 s), refresca la copia y emite creatorhub-copia con img_rev y sync_en_curso. Al pasar a
 * segundo plano el bucle se detiene. Los eventos salen por el Emisor (MainActivity → CustomEvent en window).
 */
public final class Nucleo implements ClienteHub.Oyente {
    /** Lo implementa MainActivity: window.dispatchEvent(new CustomEvent(evento, {detail})). */
    public interface Emisor { void emitir(String evento, JSONObject detalle); }

    static final int TOPE_RECONEXION_MS = 5000;
    static final long MIN_ENTRE_COPIAS_POR_IMAGENES_MS = 30_000;
    static final long REVISAR_COPIA_MS = 15L * 60 * 1000;       // 04 §B.4: "al volver al frente y cada 15 min"
    private static Nucleo unico;

    public final Context ctx;
    public final AlmacenSeguro almacen;
    public final ClienteHub cliente;
    public final CopiaSinConexion copia;
    public final ColaOps cola;
    public final Emparejador emparejador;
    public final MigracionNube migracion;
    /** Tareas del puente (emparejar, buscar, actualizar, peticion, compartir). */
    public final ExecutorService io = Executors.newFixedThreadPool(4);
    private final ExecutorService fondo = Executors.newSingleThreadExecutor();
    private final AtomicBoolean precargando = new AtomicBoolean();
    private final ControlPrecargaImagenes controlPrecarga = new ControlPrecargaImagenes();
    private final AtomicBoolean sondeandoAcceso = new AtomicBoolean();
    private final AtomicReference<HttpsURLConnection> largoEnCurso = new AtomicReference<>();
    private final Object senal = new Object();

    private volatile Emisor emisor;
    private volatile boolean alFrente, pausado;
    private volatile boolean syncEnCurso;
    private volatile Thread bucle;
    private volatile long ultimaCopiaPorImagenes, ultimaRevisionCopia;
    private volatile boolean ultimaCopiaValida;
    private String ultimoEstado = "";
    private String ultimaRevisionNube;

    private Nucleo(Context c) {
        ctx = c.getApplicationContext();
        almacen = new AlmacenSeguro(ctx);
        cliente = new ClienteHub(ctx, almacen);
        copia = new CopiaSinConexion(ctx);
        cola = new ColaOps(ctx);
        emparejador = new Emparejador(ctx, cliente);
        migracion = new MigracionNube(ctx);
        cliente.fijarOyente(this);
    }

    public static synchronized Nucleo de(Context c) {
        if (unico == null) unico = new Nucleo(c);
        return unico;
    }

    public void fijarEmisor(Emisor e) { emisor = e; }

    public void quitarEmisor(Emisor e) { if (emisor == e) emisor = null; }

    public void emitir(String evento, JSONObject detalle) {
        Emisor e = emisor;
        if (e != null) e.emitir(evento, detalle);
    }

    // ------------------------------------------------------------------ EstadoConexionPc
    /** EstadoConexionPc de plataforma.d.ts (rev. 3.1, con sync_en_curso). Sin secretos. */
    public JSONObject estado() {
        JSONObject o = new JSONObject();
        try {
            boolean emp = cliente.emparejado();
            CopiaSinConexion.Meta m = copia.meta();
            o.put("emparejado", emp)
             .put("host_id", emp ? cliente.hostId() : JSONObject.NULL)
             .put("nombre_equipo", emp ? cliente.nombreEquipo() : JSONObject.NULL)
             .put("conectado", emp && cliente.conectado())
             .put("ip", emp && cliente.ip() != null ? cliente.ip() : JSONObject.NULL)
             .put("ultima_copia_at", copia.existe() ? (Object) m.copiaAt : JSONObject.NULL)
             .put("cambios_pendientes", cola.cantidad())
             .put("permisos", emp && cliente.permisos() != null ? cliente.permisos() : JSONObject.NULL)
             .put("revocado", emp && cliente.revocado())
             .put("incompatible", cliente.incompatible() != null ? cliente.incompatible() : JSONObject.NULL)
             .put("sync_en_curso", emp && syncEnCurso);
        } catch (JSONException ignorada) { /* claves fijas */ }
        return o;
    }

    /** Emite creatorhub-conexion solo si algo cambió. */
    public void avisarConexion() {
        JSONObject e = estado();
        String s = e.toString();
        synchronized (this) {
            if (s.equals(ultimoEstado)) return;
            ultimoEstado = s;
        }
        emitir("creatorhub-conexion", e);
    }

    @Override public void cambioDeEstado() {
        avisarConexion();
        synchronized (senal) { senal.notifyAll(); }
    }

    /** Estado local sin tokens: el gate puede consultarlo antes de cualquier sesión remota. */
    public JSONObject estadoNativo() {
        JSONObject o = cliente.esNube() ? cliente.nube.estado() : new JSONObject();
        try {
            if (cliente.esNube()) migracion.preparar(cola);
            o.put("native_client", true).put("platform", "android").put("hay_copia", copia.existe());
            if (cliente.esNube()) {
                JSONObject anterior = migracion.estadoPublico();
                java.util.Iterator<String> keys = anterior.keys();
                while (keys.hasNext()) { String key = keys.next(); o.put(key, anterior.get(key)); }
            }
        } catch (IOException | JSONException e) {
            try { o.put("native_client", true).put("platform", "android").put("migration_pending", true)
                    .put("migration_warning", "La copia anterior está conservada. No pudimos prepararla para la nube."); }
            catch (JSONException ignorada) { /* campos fijos */ }
        }
        reanudarAccesoNube();
        return o;
    }

    public String iniciarAccesoNube() throws IOException {
        if (!cliente.esNube()) throw new IOException("Este paquete no está configurado para la nube.");
        String url = cliente.nube.iniciar("Corte para Android");
        reanudarAccesoNube();
        return url;
    }

    public JSONObject migrarAccesoNube(boolean confirmar) throws IOException {
        if (!cliente.esNube() || !cliente.emparejado()) throw new IOException("Entra con Google antes de importar tu organización anterior.");
        migracion.preparar(cola);
        migracion.decidir(confirmar, cliente, cola);
        ultimaRevisionNube = null;
        despertar();
        JSONObject o = estadoNativo();
        try { o.put("ok", true); } catch (JSONException e) { /* campo fijo */ }
        return o;
    }

    public void reanudarAccesoNube() {
        if (!cliente.esNube() || !cliente.nube.hayPendiente() || !sondeandoAcceso.compareAndSet(false, true)) return;
        io.execute(() -> {
            try {
                while (cliente.nube.hayPendiente() && cliente.nube.sondear()) {
                    try { Thread.sleep(cliente.nube.esperaSondeoMs()); } catch (InterruptedException e) { Thread.currentThread().interrupt(); break; }
                }
            } finally {
                sondeandoAcceso.set(false);
                avisarConexion();
                despertar();
            }
        });
    }

    /** Salir no descarta los cambios pendientes; la identidad se comprueba antes de volver a enviarlos. */
    public void cerrarAccesoNube() {
        if (!cliente.esNube()) return;
        cliente.nube.cerrar();
        syncEnCurso = false;
        ultimaRevisionNube = null;
        avisarConexion();
        despertar();
    }

    // ------------------------------------------------------------------ ciclo de vida
    public void alFrente(boolean si) {
        if (si && !alFrente) controlPrecarga.reiniciar();
        alFrente = si;
        if (si) reanudarAccesoNube();
        if (si) arrancarBucle();
        else detenerBucle();                   // el long-poll solo se hace con la app al frente (C27)
        synchronized (senal) { senal.notifyAll(); }
    }

    /** Tras emparejar: si la app está al frente, el bucle de cambios sigue (o vuelve a arrancar) sin esperar. */
    public void despertar() {
        if (alFrente) arrancarBucle();
        synchronized (senal) { senal.notifyAll(); }
    }

    /** Solo para las pruebas de depuración: detiene el bucle para que no hable con el servidor de prueba. */
    public void pausar(boolean si) {
        pausado = si;
        if (si) detenerBucle();
        else if (alFrente) arrancarBucle();
    }

    private void detenerBucle() {
        Thread t = bucle;
        if (t != null) t.interrupt();
        final HttpsURLConnection c = largoEnCurso.getAndSet(null);
        if (c != null) io.execute(c::disconnect);   // corta la lectura bloqueada del long-poll
    }

    private synchronized void arrancarBucle() {
        if (pausado || (bucle != null && bucle.isAlive() && !bucle.isInterrupted())) return;
        Thread t = new Thread(this::bucleDeCambios, "corte-cambios");
        t.setDaemon(true);
        bucle = t;
        t.start();
    }

    private void bucleDeCambios() {
        long espera = 0;
        boolean recienAlFrente = true;          // 04 §B.4: la copia se revisa al volver al frente…
        while (alFrente && !pausado && !Thread.currentThread().isInterrupted()) {
            if (cliente.esNube()) {
                revisarNube(recienAlFrente);
                recienAlFrente = false;
                esperar(syncEnCurso ? 3000 : 15000);
                continue;
            }
            if (!cliente.emparejado() || cliente.revocado()) {
                syncEnCurso = false;
                avisarConexion();
                esperar(60_000);              // se despierta con cambioDeEstado (emparejar / olvidar)
                continue;
            }
            if (!cliente.conectado()) {
                boolean ok = cliente.conectar(TOPE_RECONEXION_MS);
                if (ok) {
                    syncEnCurso = cliente.syncEnCursoSegunSesion();
                    avisarConexion();
                    refrescarCopia(true);
                    enviarCola();
                    rotarSiToca();
                    espera = 0;
                    recienAlFrente = false;
                } else {
                    avisarConexion();
                    espera = espera == 0 ? 5000 : Math.min(30_000, espera * 2);
                    esperar(espera);
                }
                continue;
            }
            // …y cada 15 min aunque el long-poll no haya avisado (If-None-Match: casi siempre 304, sin costo).
            if (recienAlFrente || SystemClock.elapsedRealtime() - ultimaRevisionCopia > REVISAR_COPIA_MS) {
                recienAlFrente = false;
                refrescarCopia(true);
                enviarCola();
            }
            CopiaSinConexion.Meta m = copia.meta();
            String ruta = "/lan/v1/api/cambios?data_version=" + m.dataVersion + "&local_rev=" + m.localRev
                    + "&img_rev=" + m.imgRev + "&espera_s=25";
            try {
                long t0 = SystemClock.elapsedRealtime();
                ClienteHub.Respuesta r = cliente.pedir(new ClienteHub.Peticion("GET", ruta).lectura(30_000).cancelable(largoEnCurso));
                if (!alFrente || pausado) break;
                if (r.codigo == 200) {
                    JSONObject c = r.json();
                    if (c != null) procesarCambios(c, m);
                    if (SystemClock.elapsedRealtime() - t0 < 1000) esperar(1000);   // nunca un bucle apretado
                } else if (r.codigo == 204) {
                    rotarSiToca();
                } else if (r.codigo == 401 || r.codigo == 403) {
                    avisarConexion();
                    esperar(10_000);
                } else {
                    esperar(5000);
                }
            } catch (IOException e) {
                if (Thread.currentThread().isInterrupted() || !alFrente || pausado) break;
                cliente.marcarDesconectado();
            }
        }
        synchronized (this) { if (bucle == Thread.currentThread()) bucle = null; }
    }

    /** Peticiones cortas sobre internet; se pausa con el ciclo de vida y mantiene la copia/cola originales. */
    private void revisarNube(boolean alVolver) {
        if (!cliente.emparejado()) { syncEnCurso = false; avisarConexion(); return; }
        if (!cliente.conectado() && !cliente.conectar(TOPE_RECONEXION_MS)) return;
        try {
            ClienteHub.Respuesta r = cliente.pedir(new ClienteHub.Peticion("GET", "/api/cloud/revision")
                    .lectura(10000).cancelable(largoEnCurso));
            if (r.codigo != 200) { avisarConexion(); return; }
            JSONObject o = r.json(), sync = o == null ? null : o.optJSONObject("sync");
            String revision = o == null ? "" : o.optString("revision");
            if (revision.isEmpty()) return;
            boolean antes = syncEnCurso;
            syncEnCurso = sync != null && sync.optBoolean("en_curso", false);
            if (alVolver || !revision.equals(ultimaRevisionNube) || !copia.existe()) {
                refrescarCopia(true);
                if (ultimaCopiaValida) ultimaRevisionNube = revision;
            } else precargarImagenes(); // Reintenta faltantes de la misma copia con presupuesto acotado.
            enviarCola();
            if (antes != syncEnCurso) emitirCopia(copia.meta());
            avisarConexion();
        } catch (IOException e) { cliente.marcarDesconectado(); }
    }

    /**
     * CambiosResponse: sync_en_curso al estado; si cambió data_version/local_rev → copia ya; si solo img_rev → máx. 1
     * copia cada 30 s (mientras tanto el long-poll respondería al instante: se espera lo que falta de la ventana).
     */
    private void procesarCambios(JSONObject c, CopiaSinConexion.Meta m) {
        boolean sync = c.optBoolean("sync_en_curso", false);
        boolean cambioSync = sync != syncEnCurso;
        syncEnCurso = sync;
        boolean datos = c.optLong("data_version", m.dataVersion) != m.dataVersion || c.optLong("local_rev", m.localRev) != m.localRev;
        boolean imgs = c.has("img_rev") && c.optLong("img_rev", m.imgRev) != m.imgRev;
        boolean refresco = false;
        long diferir = 0;
        if (datos) refresco = refrescarCopia(true);
        else if (imgs) {
            long desde = SystemClock.elapsedRealtime() - ultimaCopiaPorImagenes;
            if (desde > MIN_ENTRE_COPIAS_POR_IMAGENES_MS) {
                ultimaCopiaPorImagenes = SystemClock.elapsedRealtime();
                refresco = refrescarCopia(true);
            } else {
                diferir = MIN_ENTRE_COPIAS_POR_IMAGENES_MS - desde;
            }
        }
        if (cambioSync && !refresco) emitirCopia(copia.meta());   // la interfaz muestra/oculta "Tu PC está sincronizando…"
        if (cambioSync) avisarConexion();
        if (diferir > 0) esperar(diferir);
    }

    /** GET snapshot con If-None-Match; 200 → creatorhub-copia y precarga de imágenes. Devuelve true si cambió. */
    public boolean refrescarCopia(boolean precargar) {
        ultimaCopiaValida = false;
        try {
            if (cliente.esNube()) migracion.preparar(cola);
            CopiaSinConexion.Meta nueva = copia.actualizar(cliente);
            ultimaRevisionCopia = SystemClock.elapsedRealtime();
            ultimaCopiaValida = true;
            if (nueva == null) { if (precargar) precargarImagenes(); return false; }
            emitirCopia(nueva);
            avisarConexion();
            if (precargar) precargarImagenes();
            return true;
        } catch (ClienteHub.SinConexion e) {
            return false;
        } catch (IOException e) {
            return false;
        }
    }

    /** creatorhub-copia: {data_version, local_rev, img_rev, copia_at, sync_en_curso} (EventosAndroid rev. 3.1). */
    public void emitirCopia(CopiaSinConexion.Meta m) {
        try {
            emitir("creatorhub-copia", new JSONObject()
                    .put("data_version", m.dataVersion).put("local_rev", m.localRev).put("img_rev", m.imgRev)
                    .put("copia_at", m.copiaAt).put("sync_en_curso", syncEnCurso));
        } catch (JSONException ignorada) { /* claves fijas */ }
    }

    private void precargarImagenes() {
        if (!precargando.compareAndSet(false, true)) return;
        CopiaSinConexion.Meta metaImagenes = copia.meta();
        String claveImagenes = metaImagenes.imgRev + ":" + metaImagenes.imagenes.hashCode();
        if (!controlPrecarga.intentar(claveImagenes, SystemClock.elapsedRealtime())) { precargando.set(false); return; }
        fondo.execute(() -> {
            try {
                copia.precargar(cliente, (hechas, total) -> {
                    try { emitir("creatorhub-imagenes", new JSONObject().put("hechas", hechas).put("total", total)); }
                    catch (JSONException ignorada) { /* claves fijas */ }
                });
            } finally {
                precargando.set(false);
            }
        });
    }

    /** Envía la cola y emite creatorhub-ops {resultados, pendientes}. */
    public void enviarCola() {
        if (cola.cantidad() == 0 || !cliente.conectado()) return;
        try {
            JSONObject r = cola.enviar(cliente);
            if (r != null) {
                emitir("creatorhub-ops", r);
                avisarConexion();
            }
        } catch (IOException e) {
            // se reintenta con la siguiente conexión
        }
    }

    private void rotarSiToca() {
        try { cliente.rotarSiToca(false); } catch (IOException e) { /* se reintenta en la siguiente vuelta */ }
    }

    /**
     * actualizarAhora (01 §5.6; BUILD_SPEC §7.2): reconecta si hace falta; si la última sync OK de la PC tiene más de
     * 30 min y el permiso es lectura_escritura, primero POST /lan/v1/api/sync (la copia llega con los cambios del
     * long-poll); luego copia + cola. Devuelve true si se habló con la PC.
     */
    public boolean actualizarAhora() {
        if (!cliente.emparejado() || cliente.revocado()) return false;
        if (!cliente.conectado() && !cliente.conectar(TOPE_RECONEXION_MS)) { avisarConexion(); return false; }
        try {
            JSONObject ses = cliente.refrescarSesion();
            JSONObject sync = ses == null ? null : ses.optJSONObject("sync");
            boolean enCurso = sync != null && sync.optBoolean("en_curso", false);
            long ultima = cliente.ultimaSyncOkAt();
            long ahora = System.currentTimeMillis() / 1000L;
            if ("lectura_escritura".equals(cliente.permisos()) && !enCurso && (ultima == 0 || ahora - ultima > 30 * 60)) {
                ClienteHub.Respuesta r = cliente.pedir(new ClienteHub.Peticion("POST", "/lan/v1/api/sync")
                        .cuerpo("{}".getBytes(java.nio.charset.StandardCharsets.UTF_8)));
                if (r.codigo == 202 || r.codigo == 200) enCurso = true;
            }
            if (enCurso != syncEnCurso) { syncEnCurso = enCurso; avisarConexion(); }
            refrescarCopia(true);
            enviarCola();
            synchronized (senal) { senal.notifyAll(); }
            return true;
        } catch (IOException e) {
            cliente.marcarDesconectado();
            return false;
        }
    }

    /** "Olvidar esta PC": credencial, copia, cola e imágenes (04 §B.5). */
    public void olvidar() {
        cliente.olvidar();
        copia.borrarTodo();
        cola.borrarTodo();
        syncEnCurso = false;
        avisarConexion();
    }

    private void esperar(long ms) {
        synchronized (senal) {
            try { senal.wait(ms); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
        }
    }
}
