package app.creatorhub.red;

import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** El archivo offline privado exige identidad fuerte. Las respuestas a WebView nunca usan cache HTTP. */
public final class PoliticaCacheImagenes {
    public static final String CACHE_HTTP = "private, no-store";
    private static final Pattern VERSION = Pattern.compile("^/img/[^?]+\\?v=([0-9a-f]{8})(?:&t=(xs|sm|md))?$");
    private PoliticaCacheImagenes() { }

    public static String etagEsperada(String normalizada) {
        if (normalizada == null) return null;
        Matcher m = VERSION.matcher(normalizada);
        return m.matches() ? "\"" + m.group(1) + (m.group(2) == null ? "" : "-" + m.group(2)) + "\"" : null;
    }

    public static boolean almacenable(String normalizada, String etag, String mime) {
        String esperada = etagEsperada(normalizada);
        return esperada != null && esperada.equals(etag) && mime != null
                && mime.split(";", 2)[0].trim().toLowerCase(Locale.ROOT).startsWith("image/");
    }

    public static boolean permiteRespaldo(int codigo) {
        return codigo == 404 || codigo == 429 || codigo == 500 || codigo == 502 || codigo == 503 || codigo == 504;
    }
}
