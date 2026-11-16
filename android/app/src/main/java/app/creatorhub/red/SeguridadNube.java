package app.creatorhub.red;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.Base64;

/** Límites y validación del canal nativo. Sin estado ni secretos persistidos. */
public final class SeguridadNube {
    public static final String ORIGEN = "https://corte-e-book-21589.web.app";
    public static final int LOTE_BYTES = 224 * 1024;
    private SeguridadNube() { }

    public static String nuevoVerificador() {
        byte[] bytes = new byte[32];
        new SecureRandom().nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    public static String reto(String verificador) {
        if (verificador == null || !verificador.matches("[A-Za-z0-9_-]{43,128}")) throw new IllegalArgumentException("PKCE inválido");
        try {
            return Base64.getUrlEncoder().withoutPadding().encodeToString(
                    MessageDigest.getInstance("SHA-256").digest(verificador.getBytes(StandardCharsets.US_ASCII)));
        } catch (NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }

    public static boolean tokenValido(String token) {
        return token != null && token.matches("corte_native_v1_[A-Za-z0-9_-]{43}");
    }

    public static boolean cabeEnLote(int bytes, int cantidad, String json) {
        return cantidad < 200 && (long) bytes + json.getBytes(StandardCharsets.UTF_8).length
                + (cantidad == 0 ? 0 : 1) <= LOTE_BYTES;
    }

    public static boolean verificacionPermitida(String url) {
        try {
            URI u = new URI(url);
            return "https".equals(u.getScheme()) && "corte-e-book-21589.web.app".equals(u.getHost())
                    && u.getPort() == -1 && u.getUserInfo() == null && u.getFragment() == null
                    && "/conectar-dispositivo".equals(u.getPath());
        } catch (Exception e) { return false; }
    }

    public static String rutaRemota(String ruta) {
        String r = ruta.startsWith("/lan/v1/") ? ruta.substring(7) : ruta;
        try {
            URI u = new URI(r);
            String p = u.getPath();
            if (r.length() > 4096 || u.isAbsolute() || u.getRawAuthority() != null || u.getFragment() != null
                    || u.getRawPath().contains("%")
                    || p == null || (!p.startsWith("/api/") && !p.startsWith("/img/"))
                    || p.contains("\\") || p.contains("//") || p.indexOf('\0') >= 0
                    || java.util.Arrays.asList(p.split("/")).contains("..") || java.util.Arrays.asList(p.split("/")).contains(".")
                    || p.chars().anyMatch(ch -> ch < 32 || ch == 127)
                    || !u.normalize().getPath().equals(p)) throw new IllegalArgumentException("Ruta no permitida");
            return r;
        } catch (java.net.URISyntaxException e) { throw new IllegalArgumentException("Ruta no permitida", e); }
    }
}
