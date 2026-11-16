package app.creatorhub.red;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.LinkAddress;
import android.net.LinkProperties;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.SystemClock;
import java.io.IOException;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.SocketTimeoutException;
import java.net.UnknownHostException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * Busca el hub de la PC en la Wi-Fi (Protocolo LAN 1, 04 §B.8): 'CREATORHUB_DESCUBRIR 1 <nonce 32 hex>' por UDP 39231
 * al broadcast general, al dirigido de la subred y, además, por unicast a las IP ya conocidas (si la PC cambió de
 * puerto, la respuesta trae el nuevo). Se reenvía cada 500 ms durante la espera. La respuesta solo trae identidad
 * pública, alias, puerto y huella (pista no autenticada): nunca secretos.
 */
public final class DescubrimientoLan {
    public static final int PUERTO = ProtocoloLan.PUERTO_UDP;

    /** Una PC que respondió. `huella` es solo una pista (la autenticación la dan el QR o la prueba del código). */
    public static final class Pc {
        public final String hostId, nombreEquipo, ip, huella;
        public final int puerto;

        Pc(String hostId, String nombreEquipo, String ip, int puerto, String huella) {
            this.hostId = hostId; this.nombreEquipo = nombreEquipo; this.ip = ip; this.puerto = puerto; this.huella = huella;
        }

        /** PcEncontrada de plataforma.d.ts: {host_id, nombre_equipo, ip, puerto}. */
        public JSONObject aJson() throws JSONException {
            return new JSONObject().put("host_id", hostId).put("nombre_equipo", nombreEquipo).put("ip", ip).put("puerto", puerto);
        }
    }

    private DescubrimientoLan() { }

    /** Todas las PC que respondan en `esperaMs` (1.5 s en la app). `hostId` != null: solo esa PC y termina al encontrarla. */
    public static List<Pc> buscar(Context ctx, int esperaMs, Collection<String> unicast, String hostId) throws IOException {
        String nonce = ProtocoloLan.hex(ProtocoloLan.azar(16));
        byte[] pregunta = ProtocoloLan.preguntaDescubrimiento(nonce);

        ConnectivityManager cm = ctx.getSystemService(ConnectivityManager.class);
        Network wifi = redLocal(cm);
        Set<InetAddress> destinos = new LinkedHashSet<>();
        if (unicast != null) {
            for (String ip : unicast) {
                InetAddress a = ipPrivada(ip);
                if (a != null) destinos.add(a);
            }
        }
        if (wifi != null) agregarBroadcasts(cm.getLinkProperties(wifi), destinos);
        destinos.add(InetAddress.getByName("255.255.255.255"));

        List<Pc> pcs = new ArrayList<>();
        Set<String> vistos = new HashSet<>();
        try (DatagramSocket s = new DatagramSocket()) {
            if (wifi != null) {
                try { wifi.bindSocket(s); } catch (IOException ignorado) { /* sin Wi-Fi utilizable: red por omisión */ }
            }
            s.setBroadcast(true);
            s.setSoTimeout(250);
            byte[] buf = new byte[1024];
            long fin = SystemClock.elapsedRealtime() + esperaMs;
            long proximoEnvio = 0;
            while (SystemClock.elapsedRealtime() < fin) {
                if (SystemClock.elapsedRealtime() >= proximoEnvio) {
                    for (InetAddress d : destinos) {
                        try { s.send(new DatagramPacket(pregunta, pregunta.length, d, PUERTO)); }
                        catch (IOException ignorado) { /* sin ruta hacia ese destino */ }
                    }
                    proximoEnvio = SystemClock.elapsedRealtime() + 500;
                }
                DatagramPacket p = new DatagramPacket(buf, buf.length);
                try { s.receive(p); } catch (SocketTimeoutException t) { continue; }
                if (!esPrivada(p.getAddress()) || p.getLength() > 512) continue;
                JSONObject r;
                try { r = new JSONObject(new String(p.getData(), 0, p.getLength(), StandardCharsets.UTF_8)); }
                catch (JSONException e) { continue; }
                if (!"creator-hub".equals(r.optString("app")) || r.optInt("v") != ProtocoloLan.PROTOCOLO
                        || !nonce.equals(r.optString("nonce"))) continue;
                String id = r.optString("host_id");
                String huella = r.optString("huella");
                int puerto = r.optInt("puerto", -1);
                String alias = r.optString("nombre_equipo", "");
                if (!ProtocoloLan.esHostId(id) || !ProtocoloLan.esHuella(huella) || puerto < 1 || puerto > 65535) continue;
                if (alias.isEmpty() || alias.length() > 64) alias = "PC " + id.substring(0, 4).toUpperCase(java.util.Locale.ROOT);
                if (hostId != null && !hostId.equals(id)) continue;
                if (!vistos.add(id)) continue;
                pcs.add(new Pc(id, alias, p.getAddress().getHostAddress(), puerto, huella));
                if (hostId != null) break;
            }
        }
        return pcs;
    }

    /** La red Wi-Fi/Ethernet (aunque los datos móviles sean la red por omisión), o null. */
    @SuppressWarnings("deprecation") // getAllNetworks sigue siendo la vía sin callbacks para API 26+
    public static Network redLocal(ConnectivityManager cm) {
        if (cm == null) return null;
        for (Network red : cm.getAllNetworks()) {
            NetworkCapabilities nc = cm.getNetworkCapabilities(red);
            if (nc != null && (nc.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
                    || nc.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET))) return red;
        }
        return null;
    }

    private static void agregarBroadcasts(LinkProperties lp, Set<InetAddress> destino) {
        if (lp == null) return;
        for (LinkAddress la : lp.getLinkAddresses()) {
            InetAddress a = la.getAddress();
            if (!(a instanceof Inet4Address) || !esPrivada(a)) continue;
            byte[] b = a.getAddress();
            int ip = ((b[0] & 0xff) << 24) | ((b[1] & 0xff) << 16) | ((b[2] & 0xff) << 8) | (b[3] & 0xff);
            int prefijo = la.getPrefixLength();
            int mascara = prefijo == 0 ? 0 : -1 << (32 - prefijo);
            int bc = ip | ~mascara;
            try {
                destino.add(InetAddress.getByAddress(new byte[] {
                        (byte) (bc >>> 24), (byte) (bc >>> 16), (byte) (bc >>> 8), (byte) bc}));
            } catch (UnknownHostException ignorado) { /* no ocurre con 4 bytes */ }
        }
    }

    /** Solo 10/8, 172.16/12 y 192.168/16 (contrato.ts, Protocolo LAN 1). */
    public static boolean esPrivada(InetAddress a) {
        if (!(a instanceof Inet4Address)) return false;
        byte[] b = a.getAddress();
        int x = b[0] & 0xff, y = b[1] & 0xff;
        return x == 10 || (x == 172 && y >= 16 && y <= 31) || (x == 192 && y == 168);
    }

    /** IPv4 literal privada (sin DNS) o null. */
    public static InetAddress ipPrivada(String texto) {
        if (texto == null || !texto.matches("\\d{1,3}(\\.\\d{1,3}){3}")) return null;
        String[] p = texto.split("\\.");
        byte[] b = new byte[4];
        for (int i = 0; i < 4; i++) {
            int v = Integer.parseInt(p[i]);
            if (v > 255) return null;
            b[i] = (byte) v;
        }
        try {
            InetAddress a = InetAddress.getByAddress(b);
            return esPrivada(a) ? a : null;
        } catch (UnknownHostException e) {
            return null;
        }
    }
}
