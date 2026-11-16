package app.creatorhub.red;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.security.cert.Certificate;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;
import javax.crypto.Cipher;
import javax.crypto.Mac;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.PBEKeySpec;
import javax.crypto.spec.SecretKeySpec;
import javax.net.ssl.HostnameVerifier;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLPeerUnverifiedException;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/**
 * Protocolo LAN 1 de Creator Hub, lado del teléfono. SOLO usa java.* y javax.* (nada de android.*), así el MISMO
 * archivo compila en el APK (API 26+) y en el JDK 17 local, donde se comprueba contra los vectores de Python:
 *   spec/pruebas/android_min/jdk/correr.ps1  ->  spec/pruebas/protocolo_lan/vectores_emparejamiento.json
 * Normativo: spec/contrato.ts («Protocolo LAN 1») y spec/04_plataformas.md §C. Referencia Python:
 * spec/pruebas/protocolo_lan/protocolo_lan.py.
 */
final class ProtocoloLan {
    static final int PROTOCOLO = 1;
    static final int PUERTO_LAN = 39230;
    static final int PUERTO_UDP = 39231;
    static final String ESQUEMA_AUTH = "CH1-HMAC-SHA256";
    private static final Pattern CODIGO = Pattern.compile("[0-9A-HJKMNP-TV-Z]{12}");
    private static final Pattern HEX32 = Pattern.compile("[0-9a-f]{32}");
    private static final Pattern HEX64 = Pattern.compile("[0-9a-f]{64}");
    private static final SecureRandom AZAR = new SecureRandom();

    private ProtocoloLan() { }

    // ------------------------------------------------------------------ utilidades
    static String b64u(byte[] b) { return Base64.getUrlEncoder().withoutPadding().encodeToString(b); }

    static byte[] b64uDec(String s) {
        if (s == null || !s.matches("[A-Za-z0-9_-]*") || s.length() % 4 == 1) throw new IllegalArgumentException("base64url inválido");
        return Base64.getUrlDecoder().decode(s);
    }

    static byte[] utf8(String s) { return s.getBytes(StandardCharsets.UTF_8); }

    static String hex(byte[] b) {
        StringBuilder sb = new StringBuilder(b.length * 2);
        for (byte x : b) sb.append(String.format(Locale.ROOT, "%02x", x & 0xff));
        return sb.toString();
    }

    static byte[] deHex(String s) {
        if (s == null || s.length() % 2 != 0 || !s.matches("[0-9a-fA-F]*")) throw new IllegalArgumentException("hex inválido");
        byte[] r = new byte[s.length() / 2];
        for (int i = 0; i < r.length; i++) r[i] = (byte) Integer.parseInt(s.substring(2 * i, 2 * i + 2), 16);
        return r;
    }

    static byte[] azar(int n) { byte[] b = new byte[n]; AZAR.nextBytes(b); return b; }

    static byte[] hmac(byte[] clave, byte[] datos) throws GeneralSecurityException {
        Mac m = Mac.getInstance("HmacSHA256");
        m.init(new SecretKeySpec(clave, "HmacSHA256"));
        return m.doFinal(datos);
    }

    static byte[] sha256(byte[] datos) throws GeneralSecurityException {
        return MessageDigest.getInstance("SHA-256").digest(datos);
    }

    /** HKDF-SHA256 (RFC 5869). salt vacío = 32 ceros (Mac no admite llave vacía). */
    static byte[] hkdf(byte[] ikm, byte[] salt, byte[] info, int n) throws GeneralSecurityException {
        byte[] prk = hmac(salt == null || salt.length == 0 ? new byte[32] : salt, ikm);
        ByteArrayOutputStream okm = new ByteArrayOutputStream();
        byte[] t = new byte[0];
        for (int i = 1; okm.size() < n; i++) {
            ByteArrayOutputStream e = new ByteArrayOutputStream();
            e.write(t, 0, t.length);
            e.write(info, 0, info.length);
            e.write(i);
            t = hmac(prk, e.toByteArray());
            okm.write(t, 0, t.length);
        }
        byte[] r = new byte[n];
        System.arraycopy(okm.toByteArray(), 0, r, 0, n);
        return r;
    }

    static String huellaAB64u(String huellaHex) {
        if (huellaHex == null || !HEX64.matcher(huellaHex).matches()) throw new IllegalArgumentException("huella inválida");
        return b64u(deHex(huellaHex));
    }

    static String huellaAHex(String f) {
        byte[] b = b64uDec(f);
        if (b.length != 32) throw new IllegalArgumentException("huella inválida");
        return hex(b);
    }

    // ------------------------------------------------------------------ AES-256-GCM (salida = cifrado || etiqueta)
    static byte[] gcmCifrar(byte[] clave, byte[] iv, byte[] claro, byte[] aad) throws GeneralSecurityException {
        Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(clave, "AES"), new GCMParameterSpec(128, iv));
        if (aad != null && aad.length > 0) c.updateAAD(aad);
        return c.doFinal(claro);
    }

    static byte[] gcmDescifrar(byte[] clave, byte[] iv, byte[] cifradoYEtiqueta, byte[] aad) throws GeneralSecurityException {
        Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.DECRYPT_MODE, new SecretKeySpec(clave, "AES"), new GCMParameterSpec(128, iv));
        if (aad != null && aad.length > 0) c.updateAAD(aad);
        return c.doFinal(cifradoYEtiqueta);
    }

    /** b64url( iv(12) || AES-256-GCM(clave, iv, claro, aad = UTF-8(aad)) ). */
    static String sellar(byte[] clave, byte[] iv, byte[] claro, String aad) throws GeneralSecurityException {
        if (iv.length != 12) throw new IllegalArgumentException("iv de 12 bytes");
        byte[] ct = gcmCifrar(clave, iv, claro, utf8(aad));
        byte[] r = new byte[12 + ct.length];
        System.arraycopy(iv, 0, r, 0, 12);
        System.arraycopy(ct, 0, r, 12, ct.length);
        return b64u(r);
    }

    static byte[] abrir(byte[] clave, String sellado, String aad) throws GeneralSecurityException {
        byte[] crudo = b64uDec(sellado);
        if (crudo.length < 12 + 16) throw new GeneralSecurityException("sellado demasiado corto");
        byte[] iv = new byte[12];
        byte[] ct = new byte[crudo.length - 12];
        System.arraycopy(crudo, 0, iv, 0, 12);
        System.arraycopy(crudo, 12, ct, 0, ct.length);
        return gcmDescifrar(clave, iv, ct, utf8(aad));
    }

    // ------------------------------------------------------------------ emparejamiento (§C.6)
    /** Mayúsculas, sin guiones ni espacios, O→0, I/L→1; exige 12 caracteres Crockford (sin I L O U). */
    static String cNorm(String codigo) {
        String s = codigo.toUpperCase(Locale.ROOT).replace("-", "").replace(" ", "")
                .replace('O', '0').replace('I', '1').replace('L', '1');
        if (!CODIGO.matcher(s).matches()) throw new IllegalArgumentException("código inválido");
        return s;
    }

    static byte[] kPair(String codigo, String hostId) throws GeneralSecurityException {
        if (hostId == null || !HEX32.matcher(hostId).matches()) throw new IllegalArgumentException("host_id inválido");
        PBEKeySpec spec = new PBEKeySpec(cNorm(codigo).toCharArray(), utf8("creatorhub-pair-v1|" + hostId), 200_000, 256);
        try {
            return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).getEncoded();
        } finally {
            spec.clearPassword();
        }
    }

    static String prueba(byte[] kPair, String nonceC, String huellaHex, String nombre) throws GeneralSecurityException {
        return b64u(hmac(kPair, utf8("CH1-PAIR|" + nonceC + "|" + huellaHex + "|" + nombre)));
    }

    static String sas(byte[] kPair, String nonceC, String nonceS) throws GeneralSecurityException {
        byte[] d = hmac(kPair, utf8("CH1-SAS|" + nonceC + "|" + nonceS));
        long n = ((d[0] & 0xffL) << 24) | ((d[1] & 0xffL) << 16) | ((d[2] & 0xffL) << 8) | (d[3] & 0xffL);
        return String.format(Locale.ROOT, "%04d", n % 10000);
    }

    static byte[] kEnc(byte[] kPair, String nonceC, String nonceS) throws GeneralSecurityException {
        byte[] a = b64uDec(nonceC), b = b64uDec(nonceS);
        byte[] salt = new byte[a.length + b.length];
        System.arraycopy(a, 0, salt, 0, a.length);
        System.arraycopy(b, 0, salt, a.length, b.length);
        return hkdf(kPair, salt, utf8("CH1-PAQUETE"), 32);
    }

    // ------------------------------------------------------------------ CH1 (firma de cada petición)
    private static final String NO_RESERVADOS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~";

    static String pct(String texto) {
        StringBuilder sb = new StringBuilder();
        for (byte b : utf8(texto)) {
            int c = b & 0xff;
            if (c < 0x80 && NO_RESERVADOS.indexOf(c) >= 0) sb.append((char) c);
            else sb.append('%').append(String.format(Locale.ROOT, "%02X", c));
        }
        return sb.toString();
    }

    /** Igual que urllib.parse.unquote: decodifica %XX dentro de los tramos ASCII (UTF-8); lo no ASCII pasa tal cual. */
    static String unquote(String s) {
        if (s.indexOf('%') < 0) return s;
        StringBuilder sb = new StringBuilder();
        int i = 0, n = s.length();
        while (i < n) {
            if (s.charAt(i) >= 0x80) { sb.append(s.charAt(i++)); continue; }
            ByteArrayOutputStream tramo = new ByteArrayOutputStream();
            while (i < n && s.charAt(i) < 0x80) {
                char ch = s.charAt(i);
                if (ch == '%' && i + 2 < n && esHex(s.charAt(i + 1)) && esHex(s.charAt(i + 2))) {
                    tramo.write(Integer.parseInt(s.substring(i + 1, i + 3), 16));
                    i += 3;
                } else {
                    tramo.write(ch);
                    i++;
                }
            }
            sb.append(new String(tramo.toByteArray(), StandardCharsets.UTF_8));
        }
        return sb.toString();
    }

    private static boolean esHex(char c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F'); }

    /** Forma canónica de ruta + query (= spec/verificacion/comun.canonico_ruta_query; vectores en vectores_ch1.json). */
    static String canonRutaQuery(String rutaQuery) {
        String s = rutaQuery;
        int h = s.indexOf('#');
        if (h >= 0) s = s.substring(0, h);
        int q = s.indexOf('?');
        String ruta = q >= 0 ? s.substring(0, q) : s;
        String query = q >= 0 ? s.substring(q + 1) : "";
        StringBuilder r = new StringBuilder();
        String[] segs = ruta.split("/", -1);
        for (int i = 0; i < segs.length; i++) {
            if (i > 0) r.append('/');
            r.append(pct(unquote(segs[i])));
        }
        List<String[]> pares = new ArrayList<>();
        for (String par : query.split("&", -1)) {
            if (par.isEmpty()) continue;
            int e = par.indexOf('=');
            String k = e >= 0 ? par.substring(0, e) : par;
            String v = e >= 0 ? par.substring(e + 1) : "";
            pares.add(new String[] {pct(unquote(k.replace('+', ' '))), pct(unquote(v.replace('+', ' ')))});
        }
        pares.sort((a, b) -> a[0].equals(b[0]) ? a[1].compareTo(b[1]) : a[0].compareTo(b[0]));
        StringBuilder qs = new StringBuilder();
        for (String[] p : pares) {
            if (qs.length() > 0) qs.append('&');
            qs.append(p[0]).append('=').append(p[1]);
        }
        return qs.length() > 0 ? r + "?" + qs : r.toString();
    }

    static String canonico(String metodo, String rutaQuery, long ts, String nonce, byte[] cuerpo) throws GeneralSecurityException {
        return "CH1\n" + metodo.toUpperCase(Locale.ROOT) + "\n" + canonRutaQuery(rutaQuery) + "\n" + ts + "\n" + nonce + "\n"
                + hex(sha256(cuerpo == null ? new byte[0] : cuerpo));
    }

    static byte[] kMac(byte[] deviceKey) throws GeneralSecurityException {
        return hkdf(deviceKey, utf8("creatorhub/lan/v1"), utf8("mac"), 32);
    }

    /** Valor de la cabecera Authorization. nonce = b64url de 16 bytes aleatorios (uno por petición). */
    static String autorizacion(String deviceId, byte[] deviceKey, String metodo, String rutaQuery, byte[] cuerpo,
                               long ts, String nonce) throws GeneralSecurityException {
        String sig = b64u(hmac(kMac(deviceKey), utf8(canonico(metodo, rutaQuery, ts, nonce, cuerpo))));
        return ESQUEMA_AUTH + " device=" + deviceId + ", ts=" + ts + ", nonce=" + nonce + ", sig=" + sig;
    }

    static String nuevoNonce() { return b64u(azar(16)); }

    // ------------------------------------------------------------------ descubrimiento
    static byte[] preguntaDescubrimiento(String nonceHex) {
        if (nonceHex == null || !HEX32.matcher(nonceHex).matches()) throw new IllegalArgumentException("nonce");
        return ("CREATORHUB_DESCUBRIR " + PROTOCOLO + " " + nonceHex).getBytes(StandardCharsets.US_ASCII);
    }

    static boolean esHostId(String s) { return s != null && HEX32.matcher(s).matches(); }

    static boolean esHuella(String s) { return s != null && HEX64.matcher(s).matches(); }

    // ------------------------------------------------------------------ TLS con huella fijada
    /** Fábrica TLS que acepta SOLO el certificado cuyo SHA-256 (DER) es la huella emparejada (más checkValidity). */
    static SSLSocketFactory fabricaFijada(final byte[] huella) throws GeneralSecurityException {
        X509TrustManager tm = new X509TrustManager() {
            @Override public void checkClientTrusted(X509Certificate[] cadena, String tipo) throws CertificateException {
                throw new CertificateException("No se aceptan clientes");
            }
            @Override public void checkServerTrusted(X509Certificate[] cadena, String tipo) throws CertificateException {
                if (cadena == null || cadena.length == 0 || !coincide(cadena[0], huella)) {
                    throw new CertificateException("La PC no es la que emparejaste");
                }
                cadena[0].checkValidity();
            }
            @Override public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
        };
        SSLContext ctx = SSLContext.getInstance("TLS");
        ctx.init(null, new TrustManager[] {tm}, AZAR);
        return ctx.getSocketFactory();
    }

    /** Se conecta por IP: el nombre no importa, se vuelve a comparar la huella del certificado de la sesión. */
    static HostnameVerifier verificadorFijado(final byte[] huella) {
        return (host, sesion) -> {
            try {
                Certificate[] cadena = sesion.getPeerCertificates();
                return cadena.length > 0 && coincide(cadena[0], huella);
            } catch (SSLPeerUnverifiedException e) {
                return false;
            }
        };
    }

    static boolean coincide(Certificate cert, byte[] huella) {
        try {
            return MessageDigest.isEqual(sha256(cert.getEncoded()), huella);
        } catch (Exception e) {
            return false;
        }
    }

    static byte[] huellaBytes(String huellaHex) {
        if (!esHuella(huellaHex)) throw new IllegalArgumentException("Huella inválida");
        return deHex(huellaHex);
    }
}
