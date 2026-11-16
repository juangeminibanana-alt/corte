package app.creatorhub.red;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Map;

/**
 * Comprueba android/app/src/main/java/app/creatorhub/red/ProtocoloLan.java (el MISMO archivo que compila el APK)
 * contra los vectores que genera Python:
 *   spec/pruebas/protocolo_lan/vectores_emparejamiento.json  (spec/pruebas/protocolo_lan/protocolo_lan.py)
 *   spec/verificacion/vectores_ch1.json                      (spec 03, v04_cripto.py)
 * Sin Gradle ni internet: android/jdk/correr.ps1 (portado de spec/pruebas/android_min/jdk). Sale con 0 si todo coincide.
 * Único cambio respecto del original: la comprobación del alias UDP. El vector conserva el alias anterior a C38
 * ("Creator Hub · 3F2A"); el celular trata el alias como texto opaco (lo muestra y nada más), así que aquí se comprueba
 * su forma (1–40 caracteres imprimibles, sin saltos) y no la fórmula por omisión, que ahora es 'PC ' + host_id[0:4].
 */
public final class VectoresEmparejamiento {
    private static int ok;

    public static void main(String[] args) throws Exception {
        if (args.length < 2) throw new IllegalArgumentException("uso: VectoresEmparejamiento <vectores_emparejamiento.json> <vectores_ch1.json>");
        Map<String, Object> v = MiniJson.obj(MiniJson.leer(new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8)));
        Map<String, Object> c3 = MiniJson.obj(MiniJson.leer(new String(Files.readAllBytes(Paths.get(args[1])), StandardCharsets.UTF_8)));

        for (Object o : MiniJson.lista(v.get("aes_gcm"))) {
            Map<String, Object> g = MiniJson.obj(o);
            byte[] k = h(g, "k"), iv = h(g, "iv"), pt = h(g, "pt"), aad = h(g, "aad");
            igual("GCM cifrar", ProtocoloLan.hex(ProtocoloLan.gcmCifrar(k, iv, pt, aad)), s(g, "ct_tag"));
            igual("GCM descifrar", ProtocoloLan.hex(ProtocoloLan.gcmDescifrar(k, iv, h(g, "ct_tag"), aad)), s(g, "pt"));
        }
        Map<String, Object> hk = MiniJson.obj(v.get("hkdf"));
        igual("HKDF RFC 5869", ProtocoloLan.hex(ProtocoloLan.hkdf(h(hk, "ikm"), h(hk, "salt"), h(hk, "info"), ((Long) hk.get("n")).intValue())), s(hk, "okm"));

        for (Object o : MiniJson.lista(v.get("codigo"))) {
            Map<String, Object> c = MiniJson.obj(o);
            String obtenido;
            try { obtenido = ProtocoloLan.cNorm(s(c, "entrada")); } catch (IllegalArgumentException e) { obtenido = null; }
            igual("código '" + s(c, "entrada") + "'", obtenido, (String) c.get("norm"));
        }

        for (Object o : MiniJson.lista(v.get("emparejamiento"))) {
            Map<String, Object> e = MiniJson.obj(o);
            byte[] kp = ProtocoloLan.kPair(s(e, "codigo"), s(e, "host_id"));
            igual("K_pair", ProtocoloLan.hex(kp), s(e, "k_pair_hex"));
            igual("prueba", ProtocoloLan.prueba(kp, s(e, "nonce_c"), s(e, "huella_hex"), s(e, "nombre")), s(e, "prueba"));
            igual("SAS", ProtocoloLan.sas(kp, s(e, "nonce_c"), s(e, "nonce_s")), s(e, "sas"));
            byte[] ke = ProtocoloLan.kEnc(kp, s(e, "nonce_c"), s(e, "nonce_s"));
            igual("K_enc", ProtocoloLan.hex(ke), s(e, "k_enc_hex"));
            igual("paquete (sellar)", ProtocoloLan.sellar(ke, h(e, "iv_hex"), ProtocoloLan.utf8(s(e, "paquete_claro")), s(e, "pair_id")), s(e, "paquete"));
            igual("paquete (abrir)", new String(ProtocoloLan.abrir(ke, s(e, "paquete"), s(e, "pair_id")), StandardCharsets.UTF_8), s(e, "paquete_claro"));
            boolean rechazado = false;
            try { ProtocoloLan.abrir(ke, s(e, "paquete"), "otro-pair-id"); } catch (java.security.GeneralSecurityException x) { rechazado = true; }
            igual("paquete con AAD ajena se rechaza", String.valueOf(rechazado), "true");
            igual("intermediario: otra huella da otra prueba",
                    String.valueOf(ProtocoloLan.prueba(kp, s(e, "nonce_c"), "0000000000000000000000000000000000000000000000000000000000000000", s(e, "nombre")).equals(s(e, "prueba"))), "false");
        }

        Map<String, Object> hu = MiniJson.obj(v.get("huella"));
        igual("huella hex->b64url", ProtocoloLan.huellaAB64u(s(hu, "hex")), s(hu, "b64u"));
        igual("huella b64url->hex", ProtocoloLan.huellaAHex(s(hu, "b64u")), s(hu, "hex"));
        Map<String, Object> qr = MiniJson.obj(v.get("qr"));
        Map<String, Object> campos = MiniJson.obj(qr.get("campos"));
        String texto = s(qr, "texto");
        igual("QR: f -> huella", ProtocoloLan.huellaAHex(texto.substring(texto.indexOf("&f=") + 3)), s(campos, "huella_hex"));

        for (Object o : MiniJson.lista(v.get("ch1"))) {
            Map<String, Object> f = MiniJson.obj(o);
            byte[] dk = h(f, "device_key_hex"), cuerpo = ProtocoloLan.utf8(s(f, "cuerpo"));
            long ts = (Long) f.get("ts");
            igual("CH1 canónico " + s(f, "metodo"), ProtocoloLan.canonico(s(f, "metodo"), s(f, "ruta"), ts, s(f, "nonce"), cuerpo), s(f, "canonico"));
            igual("CH1 k_mac", ProtocoloLan.hex(ProtocoloLan.kMac(dk)), s(f, "k_mac_hex"));
            igual("CH1 Authorization " + s(f, "metodo"), ProtocoloLan.autorizacion(s(f, "device_id"), dk, s(f, "metodo"), s(f, "ruta"), cuerpo, ts, s(f, "nonce")), s(f, "autorizacion"));
        }
        for (Object o : MiniJson.lista(c3.get("canonicalizacion"))) {
            Map<String, Object> c = MiniJson.obj(o);
            igual("canon 03 '" + s(c, "entrada") + "'", ProtocoloLan.canonRutaQuery(s(c, "entrada")), s(c, "canonico"));
        }
        Map<String, Object> f3 = MiniJson.obj(c3.get("firma"));
        byte[] dk3 = h(f3, "device_key_hex");
        String aut3 = ProtocoloLan.autorizacion(s(f3, "device_id"), dk3, s(f3, "metodo"), s(f3, "ruta"), ProtocoloLan.utf8(s(f3, "cuerpo")), (Long) f3.get("ts"), s(f3, "nonce"));
        igual("firma 03 (sig)", aut3.substring(aut3.indexOf("sig=") + 4), s(f3, "sig"));

        Map<String, Object> d = MiniJson.obj(v.get("descubrimiento"));
        igual("pregunta UDP", new String(ProtocoloLan.preguntaDescubrimiento(s(d, "nonce")), StandardCharsets.US_ASCII), s(d, "pregunta"));
        Map<String, Object> resp = MiniJson.obj(MiniJson.leer(s(d, "respuesta")));
        igual("respuesta UDP app", s(resp, "app"), "creator-hub");
        igual("respuesta UDP nonce", s(resp, "nonce"), s(d, "nonce"));
        igual("respuesta UDP host_id/huella", String.valueOf(ProtocoloLan.esHostId(s(resp, "host_id")) && ProtocoloLan.esHuella(s(resp, "huella"))), "true");
        String alias = s(resp, "nombre_equipo");
        igual("respuesta UDP alias (texto opaco 1–40, C38)", String.valueOf(alias != null && !alias.isEmpty() && alias.length() <= 40
                && alias.codePoints().noneMatch(Character::isISOControl)), "true");

        System.out.println("[ok] Java " + System.getProperty("java.version") + ": " + ok + " comprobaciones idénticas a Python");
    }

    private static String s(Map<String, Object> m, String k) { return (String) m.get(k); }

    private static byte[] h(Map<String, Object> m, String k) { return ProtocoloLan.deHex(s(m, k)); }

    private static void igual(String que, String obtenido, String esperado) {
        boolean bien = obtenido == null ? esperado == null : obtenido.equals(esperado);
        if (!bien) {
            System.out.println("[FALLA] " + que + "\n  esperado: " + esperado + "\n  obtenido: " + obtenido);
            System.exit(1);
        }
        ok++;
    }
}
