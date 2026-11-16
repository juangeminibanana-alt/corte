package app.creatorhub.red;

import android.content.Context;
import android.net.Uri;
import android.os.Build;
import android.os.SystemClock;
import android.provider.Settings;
import java.io.IOException;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Pattern;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * Emparejamiento del celular con la PC (04 §C.4–C.6; 03 §7.5; textos de 01_ux §5.3):
 * QR `creatorhub://pair?v=1&h&a&p&s&f` (huella fijada desde el QR) o código de 12 Crockford + IP/descubrimiento
 * (huella observada en el TLS y atada a la prueba). pair/start → SAS de 4 dígitos → sondeo largo de pair/{id} →
 * paquete AES-256-GCM con la credencial, que se guarda en el Keystore → primera petición firmada (/api/session).
 * Los eventos siguen EventoEmparejamiento de plataforma.d.ts. Nunca registra el código, K_pair ni la llave.
 */
public final class Emparejador {
    private static final Pattern B64U43 = Pattern.compile("[A-Za-z0-9_-]{43}");
    private static final Pattern PAIR_ID = Pattern.compile("[A-Za-z0-9_-]{8,64}");
    private static final Pattern DEVICE_ID = Pattern.compile("[A-Za-z0-9_-]{8,64}");

    /** Recibe cada evento ya armado: {id, fase, ...}. */
    public interface Oyente { void evento(JSONObject detalle); }

    /** Error del flujo con su código de CodigoErrorEmparejamiento y el texto de 01_ux §5.3. */
    static final class Fallo extends Exception {
        final String codigo;
        Fallo(String codigo, String mensaje) { super(mensaje); this.codigo = codigo; }
    }

    /** Campos del QR (04 §C.4). */
    public static final class Qr {
        public final String hostId, codigo, huella;
        public final List<String> ips;
        public final int puerto;

        Qr(String hostId, List<String> ips, int puerto, String codigo, String huella) {
            this.hostId = hostId; this.ips = ips; this.puerto = puerto; this.codigo = codigo; this.huella = huella;
        }

        /** Valida TODO el texto; lanza IllegalArgumentException si algo no cuadra. */
        public static Qr leer(String texto) {
            if (texto == null || texto.length() > 512) throw new IllegalArgumentException("qr");
            Uri u = Uri.parse(texto.trim());
            if (!"creatorhub".equals(u.getScheme()) || !"pair".equals(u.getHost())) throw new IllegalArgumentException("qr");
            if (!"1".equals(u.getQueryParameter("v"))) throw new IllegalArgumentException("qr version");
            String h = u.getQueryParameter("h");
            if (!ProtocoloLan.esHostId(h)) throw new IllegalArgumentException("qr h");
            String a = u.getQueryParameter("a");
            List<String> ips = new ArrayList<>();
            if (a != null) {
                for (String ip : a.split(",")) {
                    if (DescubrimientoLan.ipPrivada(ip.trim()) != null && ips.size() < 3) ips.add(ip.trim());
                }
            }
            if (ips.isEmpty()) throw new IllegalArgumentException("qr a");
            int p;
            try { p = Integer.parseInt(u.getQueryParameter("p")); } catch (NumberFormatException e) { throw new IllegalArgumentException("qr p"); }
            if (p < 1024 || p > 65535) throw new IllegalArgumentException("qr p");
            String s = ProtocoloLan.cNorm(String.valueOf(u.getQueryParameter("s")));
            String f = u.getQueryParameter("f");
            if (f == null || !B64U43.matcher(f).matches()) throw new IllegalArgumentException("qr f");
            return new Qr(h, Collections.unmodifiableList(ips), p, s, ProtocoloLan.huellaAHex(f));
        }
    }

    private final Context ctx;
    private final ClienteHub cliente;
    private final Map<String, Boolean> cancelados = new ConcurrentHashMap<>();

    public Emparejador(Context ctx, ClienteHub cliente) {
        this.ctx = ctx.getApplicationContext();
        this.cliente = cliente;
    }

    public void cancelar(String idPedido) { cancelados.put(idPedido, Boolean.TRUE); }

    // ------------------------------------------------------------------ entradas (corren en un hilo de fondo)
    public void conQr(String texto, String idPedido, Oyente oyente) {
        cancelados.remove(idPedido);
        emitir(oyente, idPedido, "conectando", null);
        try {
            Qr qr;
            try { qr = Qr.leer(texto); }
            catch (IllegalArgumentException e) {
                throw new Fallo("qr_invalido", "Ese código no es de Corte. Escanea el código que aparece en tu PC, en Conexión y ajustes › Celular.");
            }
            TlsFijado.Canal canal = canalDe(qr.huella);
            String ipOk = null;
            int puertoOk = qr.puerto;
            for (String ip : qr.ips) {
                revisarCancelado(idPedido);
                try {
                    cliente.hola(canal, qr.hostId, ip, qr.puerto, 3000);
                    ipOk = ip;
                    break;
                } catch (IOException e) {
                    if (TlsFijado.esHuellaDistinta(e)) throw huellaDistinta();
                    if ("version".equals(e.getMessage())) throw versionIncompatible();
                }
            }
            if (ipOk == null) {        // la PC pudo cambiar de IP: descubrimiento filtrado por su host_id
                List<DescubrimientoLan.Pc> pcs = buscar(qr.ips, qr.hostId);
                for (DescubrimientoLan.Pc pc : pcs) {
                    try {
                        cliente.hola(canal, qr.hostId, pc.ip, pc.puerto, 3000);
                        ipOk = pc.ip;
                        puertoOk = pc.puerto;
                        break;
                    } catch (IOException e) {
                        if (TlsFijado.esHuellaDistinta(e)) throw huellaDistinta();
                    }
                }
            }
            if (ipOk == null) throw noSeAlcanza();
            emparejar(qr.hostId, ipOk, puertoOk, qr.codigo, qr.huella, canal, idPedido, oyente);
        } catch (Fallo f) {
            emitirError(oyente, idPedido, f);
        } finally {
            cancelados.remove(idPedido);
        }
    }

    public void conCodigo(String codigo, String ip, String idPedido, Oyente oyente) {
        cancelados.remove(idPedido);
        emitir(oyente, idPedido, "conectando", null);
        try {
            String norm;
            try { norm = ProtocoloLan.cNorm(codigo == null ? "" : codigo); }
            catch (IllegalArgumentException e) {
                throw new Fallo("codigo_invalido", "Revisa el código: son 12 letras y números, como K7QM-3XRA-9TPF.");
            }
            List<DescubrimientoLan.Pc> candidatos = new ArrayList<>();
            if (ip != null && !ip.trim().isEmpty()) {
                String i = ip.trim();
                if (DescubrimientoLan.ipPrivada(i) == null) {
                    throw new Fallo("pc_no_encontrada", "Esa dirección no es de tu red. Escribe la que aparece en tu PC, por ejemplo 192.168.1.20.");
                }
                candidatos.addAll(buscar(Collections.singletonList(i), null));   // trae el puerto real
                boolean esa = false;
                for (DescubrimientoLan.Pc pc : candidatos) esa |= pc.ip.equals(i);
                if (!esa) candidatos.add(0, new DescubrimientoLan.Pc(null, "", i, ProtocoloLan.PUERTO_LAN, null));
            } else {
                candidatos.addAll(buscar(Collections.emptyList(), null));
                if (candidatos.isEmpty()) {
                    throw new Fallo("pc_no_encontrada", "No encontramos tu PC en esta red. Revisa que Corte esté abierto en tu PC y que ambos estén en el mismo Wi‑Fi.");
                }
            }
            Fallo ultimo = null;
            for (DescubrimientoLan.Pc pc : candidatos) {
                revisarCancelado(idPedido);
                TlsFijado.Observador obs = new TlsFijado.Observador();
                JSONObject hello;
                try {
                    hello = holaObservando(obs, pc.ip, pc.puerto);
                } catch (IOException e) {
                    if ("version".equals(e.getMessage())) throw versionIncompatible();
                    ultimo = noSeAlcanza();
                    continue;
                }
                String hostId = hello.optString("host_id");
                String fObs = obs.huella();
                if (!ProtocoloLan.esHostId(hostId) || fObs == null) { ultimo = noSeAlcanza(); continue; }
                if (pc.hostId != null && !pc.hostId.equals(hostId)) { ultimo = noSeAlcanza(); continue; }
                try {
                    emparejar(hostId, pc.ip, pc.puerto, norm, fObs, canalDe(fObs), idPedido, oyente);
                    return;
                } catch (Fallo f) {
                    if (!"codigo_invalido".equals(f.codigo) || candidatos.size() == 1) throw f;
                    ultimo = f;      // con varias PC en la red, el código puede ser de otra
                }
            }
            throw ultimo != null ? ultimo : noSeAlcanza();
        } catch (Fallo f) {
            emitirError(oyente, idPedido, f);
        } finally {
            cancelados.remove(idPedido);
        }
    }

    // ------------------------------------------------------------------ núcleo del flujo
    private void emparejar(String hostId, String ip, int puerto, String codigo, String fObs, TlsFijado.Canal canal,
                           String idPedido, Oyente oyente) throws Fallo {
        byte[] kPair = null, kEnc = null;
        try {
            kPair = ProtocoloLan.kPair(codigo, hostId);
            String nonceC = ProtocoloLan.nuevoNonce();
            String nombre = nombreDispositivo();
            JSONObject inicio = new JSONObject()
                    .put("pair_id", JSONObject.NULL).put("nonce_c", nonceC).put("nombre", nombre)
                    .put("plataforma", "android").put("prueba", ProtocoloLan.prueba(kPair, nonceC, fObs, nombre));
            revisarCancelado(idPedido);
            ClienteHub.Respuesta r = sinFirma(canal, ip, puerto,
                    new ClienteHub.Peticion("POST", "/lan/v1/pair/start").cuerpo(inicio.toString().getBytes(StandardCharsets.UTF_8)), 8000);
            if (r.codigo != 200 && r.codigo != 202) throw falloDeInicio(r);
            JSONObject resp = r.json();
            String pairId = resp == null ? "" : resp.optString("pair_id", "");
            String nonceS = resp == null ? "" : resp.optString("nonce_s", "");
            if (!PAIR_ID.matcher(pairId).matches() || nonceS.isEmpty()) throw noSeAlcanza();
            String sas = ProtocoloLan.sas(kPair, nonceC, nonceS);
            emitir(oyente, idPedido, "verifica", new String[] {"codigo_verificacion", sas});

            long expira = resp.optLong("expira_at", 0);
            long ahora = ClienteHub.ahoraLocal();
            long topeMs = expira > ahora ? Math.min(150, expira - ahora + 15) * 1000L : 105_000L;
            long fin = SystemClock.elapsedRealtime() + topeMs;
            String ruta = "/lan/v1/pair/" + pairId + "?nonce_c=" + ProtocoloLan.pct(nonceC);
            JSONObject sondeo = null;
            while (SystemClock.elapsedRealtime() < fin) {
                revisarCancelado(idPedido);
                ClienteHub.Respuesta s;
                try {
                    s = sinFirma(canal, ip, puerto, new ClienteHub.Peticion("GET", ruta), 30_000);
                } catch (IOException e) {
                    if (TlsFijado.esHuellaDistinta(e)) throw huellaDistinta();
                    dormir(1000);              // la reentrega de 120 s cubre una respuesta perdida
                    continue;
                }
                JSONObject o = s.json();
                String estado = o == null ? "" : o.optString("estado", "");
                if (s.codigo == 200 && "pendiente_aprobacion".equals(estado)) continue;
                if (s.codigo == 200 && "aprobado".equals(estado)) { sondeo = o; break; }
                if ("rechazado".equals(estado) || "emparejamiento_rechazado".equals(s.codigoError())) {
                    throw new Fallo("rechazado", "Tu PC rechazó la conexión.");
                }
                if ("expirado".equals(estado) || "emparejamiento_vencido".equals(s.codigoError())) {
                    throw new Fallo("vencido", "No confirmaste en tu PC a tiempo. Vuelve a intentarlo.");
                }
                if (s.codigo == 429) dormir(2000);
                else if (s.codigo >= 400) throw falloDeInicio(s);
            }
            if (sondeo == null) throw new Fallo("vencido", "No confirmaste en tu PC a tiempo. Vuelve a intentarlo.");

            kEnc = ProtocoloLan.kEnc(kPair, nonceC, nonceS);
            JSONObject paquete;
            try {
                paquete = new JSONObject(new String(ProtocoloLan.abrir(kEnc, sondeo.optString("paquete", ""), pairId), StandardCharsets.UTF_8));
            } catch (GeneralSecurityException | IllegalArgumentException | JSONException e) {
                throw huellaDistinta();      // un paquete que no abre con K_enc no viene de la PC del código
            }
            validarPaquete(paquete, hostId, fObs);
            ClienteHub.Credencial cred = ClienteHub.Credencial.dePaquete(paquete, ip, ClienteHub.ahoraLocal());
            try {
                cliente.establecer(cred, ip);
            } catch (IOException e) {
                throw new Fallo("red", "No pudimos guardar la conexión en este celular. Inténtalo de nuevo.");
            }
            cliente.fijarDireccion(ip, cred.puerto == puerto ? puerto : cred.puerto);
            try {                              // primera petición firmada: el hub marca confirmado_at
                ClienteHub.Respuesta ses = cliente.pedir(new ClienteHub.Peticion("GET", "/lan/v1/api/session").lectura(8000));
                if (ses.codigo == 200) cliente.marcarConectado(ses.json());
            } catch (IOException e) {
                // emparejado: la reconexión automática lo vuelve a intentar
            }
            emitir(oyente, idPedido, "aprobado", new String[] {"nombre_equipo", cred.nombreEquipo});
        } catch (GeneralSecurityException | JSONException e) {
            throw new Fallo("red", "No pudimos completar el emparejamiento. Inténtalo de nuevo.");
        } catch (IOException e) {
            if (TlsFijado.esHuellaDistinta(e)) throw huellaDistinta();
            throw noSeAlcanza();
        } finally {
            if (kPair != null) Arrays.fill(kPair, (byte) 0);
            if (kEnc != null) Arrays.fill(kEnc, (byte) 0);
        }
    }

    /** LanPaquete: host_id == el de la PC, huella_tls == la observada (== f del QR), protocolo 1 y formatos. */
    static void validarPaquete(JSONObject p, String hostId, String fObs) throws Fallo {
        String dk = p.optString("device_key", "");
        boolean bien = hostId.equals(p.optString("host_id")) && fObs.equals(p.optString("huella_tls"))
                && p.optInt("protocolo", -1) == ProtocoloLan.PROTOCOLO
                && DEVICE_ID.matcher(p.optString("device_id", "")).matches()
                && B64U43.matcher(dk).matches()
                && ("lectura".equals(p.optString("permisos")) || "lectura_escritura".equals(p.optString("permisos")))
                && p.optInt("puerto", -1) >= 1024 && p.optInt("puerto", -1) <= 65535
                && !p.optString("nombre_equipo", "").isEmpty() && p.optString("nombre_equipo").length() <= 64;
        if (!bien) throw huellaDistinta();
    }

    // ------------------------------------------------------------------ apoyo
    private ClienteHub.Respuesta sinFirma(TlsFijado.Canal canal, String ip, int puerto, ClienteHub.Peticion p, int lecturaMs)
            throws IOException {
        HttpsURLConnection c = canal.abrir(cliente.red(), new URL("https", ip, puerto, p.ruta), ClienteHub.CONEXION_MS, lecturaMs);
        try {
            return ClienteHub.intercambiar(c, p.limite(64 * 1024));
        } catch (IOException e) {
            c.disconnect();
            throw e;
        }
    }

    private JSONObject holaObservando(TlsFijado.Observador obs, String ip, int puerto) throws IOException {
        HttpsURLConnection c;
        try {
            c = obs.abrir(cliente.red(), new URL("https", ip, puerto, "/lan/v1/hello"), 3000, 3000);
        } catch (GeneralSecurityException e) {
            throw new IOException("tls", e);
        }
        ClienteHub.Respuesta r;
        try {
            r = ClienteHub.intercambiar(c, new ClienteHub.Peticion("GET", "/lan/v1/hello").limite(16 * 1024));
        } finally {
            c.disconnect();            // conexión sin fijar: no se reutiliza
        }
        JSONObject h = r.json();
        if (r.codigo != 200 || h == null || !"creator-hub".equals(h.optString("app"))) throw new IOException("No es Corte");
        if (h.optInt("protocolo", -1) != ProtocoloLan.PROTOCOLO) throw new IOException("version");
        return h;
    }

    private List<DescubrimientoLan.Pc> buscar(List<String> unicast, String hostId) {
        try {
            return DescubrimientoLan.buscar(ctx, 1500, unicast, hostId);
        } catch (IOException e) {
            return Collections.emptyList();
        }
    }

    private static TlsFijado.Canal canalDe(String huella) throws Fallo {
        try {
            return new TlsFijado.Canal(huella);
        } catch (GeneralSecurityException | IllegalArgumentException e) {
            throw new Fallo("qr_invalido", "Ese código no es de Corte. Escanea el código que aparece en tu PC, en Conexión y ajustes › Celular.");
        }
    }

    private void revisarCancelado(String idPedido) throws Fallo {
        if (cancelados.containsKey(idPedido)) throw new Fallo("cancelado", "Cancelaste el emparejamiento.");
    }

    private static Fallo falloDeInicio(ClienteHub.Respuesta r) {
        String e = r.codigoError();
        if (r.codigo == 429 || "demasiadas_solicitudes".equals(e)) {
            return new Fallo("ocupado", "Demasiados intentos. Espera un minuto e inténtalo de nuevo.");
        }
        if ("emparejamiento_ocupado".equals(e)) {
            return new Fallo("ocupado", "Tu PC está emparejando otro celular. Espera un momento e inténtalo de nuevo.");
        }
        if ("emparejamiento_vencido".equals(e) || r.codigo == 410) {
            return new Fallo("vencido", "Ese código ya caducó. Escanea el código nuevo que aparece en tu PC.");
        }
        if ("emparejamiento_rechazado".equals(e)) return new Fallo("rechazado", "Tu PC rechazó la conexión.");
        if (r.codigo == 401 || r.codigo == 403 || "firma_invalida".equals(e) || "parametros_invalidos".equals(e)) {
            return new Fallo("codigo_invalido", "Ese código no coincide con el de tu PC. Revisa que sea el que aparece en Conexión y ajustes › Celular.");
        }
        return noSeAlcanza();
    }

    private static Fallo noSeAlcanza() {
        return new Fallo("red", "No pudimos llegar a tu PC. Revisa que ambos estén en el mismo Wi‑Fi y que Corte esté abierto en la PC.");
    }

    private static Fallo huellaDistinta() {
        return new Fallo("huella_distinta", "La PC respondió con una identidad distinta. Por seguridad no nos conectamos. Escanea el código otra vez desde tu PC.");
    }

    private static Fallo versionIncompatible() {
        return new Fallo("version_incompatible", "Corte de tu PC y el de este celular son de versiones distintas. Actualiza los dos.");
    }

    private static void dormir(long ms) {
        try { Thread.sleep(ms); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
    }

    /** Nombre que la PC muestra ("Galaxy S23 quiere conectarse…"): el del teléfono o el modelo, ≤ 40 caracteres. */
    String nombreDispositivo() {
        String n = null;
        try { n = Settings.Global.getString(ctx.getContentResolver(), Settings.Global.DEVICE_NAME); }
        catch (RuntimeException ignorado) { /* sin permiso o sin valor */ }
        if (n == null || n.trim().isEmpty()) n = Build.MODEL;
        if (n == null || n.trim().isEmpty()) n = "Android";
        n = n.replaceAll("[\\p{Cntrl}]", " ").trim();
        // ≤ 40 caracteres como los cuenta el hub (puntos de código, no unidades UTF-16: sin partir un emoji)
        return n.codePointCount(0, n.length()) > 40 ? n.substring(0, n.offsetByCodePoints(0, 40)).trim() : n;
    }

    private static void emitir(Oyente o, String id, String fase, String[] extra) {
        try {
            JSONObject d = new JSONObject().put("id", id).put("fase", fase);
            if (extra != null) d.put(extra[0], extra[1]);
            o.evento(d);
        } catch (JSONException ignorado) { /* claves fijas */ }
    }

    private static void emitirError(Oyente o, String id, Fallo f) {
        try {
            o.evento(new JSONObject().put("id", id).put("fase", "error").put("error", f.codigo).put("mensaje", f.getMessage()));
        } catch (JSONException ignorado) { /* claves fijas */ }
    }
}
