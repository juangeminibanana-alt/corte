import app.creatorhub.red.SeguridadNube;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Set;

/** Datos sintéticos; no abre dispositivos, archivos de usuario ni conexiones. */
public final class PruebaSeguridadNube {
    static void comprobar(boolean ok, String mensaje) { if (!ok) throw new AssertionError(mensaje); }
    static void rechazar(String ruta) {
        try { SeguridadNube.rutaRemota(ruta); throw new AssertionError("Se aceptó una ruta ajena"); }
        catch (IllegalArgumentException esperado) { }
    }
    public static void main(String[] args) {
        comprobar(SeguridadNube.reto("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk").equals("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"), "Vector PKCE S256 RFC7636");
        Set<String> generados = new HashSet<>();
        for (int i = 0; i < 500; i++) { String v = SeguridadNube.nuevoVerificador(); comprobar(v.matches("[A-Za-z0-9_-]{43}"), "Verifier nativo"); comprobar(generados.add(v), "Aleatoriedad"); }
        comprobar(SeguridadNube.rutaRemota("/lan/v1/api/snapshot").equals("/api/snapshot"), "Ruta del snapshot original");
        comprobar(SeguridadNube.rutaRemota("/lan/v1/img/p/123?v=4&t=sm").equals("/img/p/123?v=4&t=sm"), "Imagen original");
        comprobar(SeguridadNube.rutaRemota("/api/muestras?q=caf%C3%A9%20azul&next=%2Fapi%2Fnative%2Fsession")
                .equals("/api/muestras?q=caf%C3%A9%20azul&next=%2Fapi%2Fnative%2Fsession"), "Query codificado legitimo");
        for (String r : new String[] { "https://otro.example/api/a", "//otro.example/api/a", "/api/../fuera", "/api/../api/native/session",
                "/api/./native/session", "/api//native/session", "/api/\\native/session", "/api/\nnative/session", "/api/\tnative/session",
                "/api/%2e%2e/fuera", "/api/%2fotra", "/api/%0d%0aX", "/api/native/%73ession", "/api/native/%2573ession", "/api/a#fragment", "/oauth/shop" }) rechazar(r);
        comprobar(SeguridadNube.verificacionPermitida(SeguridadNube.ORIGEN + "/conectar-dispositivo?codigo=ABCD-EFGH"), "Browser propio");
        for (String u : new String[] { "http://corte-e-book-21589.web.app/conectar-dispositivo", "https://corte-e-book-21589.web.app.otro.example/conectar-dispositivo", "https://usuario@corte-e-book-21589.web.app/conectar-dispositivo", SeguridadNube.ORIGEN + "/otra", SeguridadNube.ORIGEN + ":444/conectar-dispositivo" }) comprobar(!SeguridadNube.verificacionPermitida(u), "Browser ajeno rechazado");
        comprobar(SeguridadNube.tokenValido("corte_native_v1_" + "a".repeat(43)), "Formato bearer propio");
        comprobar(!SeguridadNube.tokenValido("eyJ-token-google"), "No usar token Google como bearer nativo");
        String op = "{\"texto\":\"" + "á".repeat(30000) + "\"}";
        int bytes = "{\"ops\":[]}".getBytes(StandardCharsets.UTF_8).length, cantidad = 0;
        while (SeguridadNube.cabeEnLote(bytes, cantidad, op)) { bytes += op.getBytes(StandardCharsets.UTF_8).length + (cantidad == 0 ? 0 : 1); cantidad++; }
        comprobar(cantidad == 3 && bytes <= 224 * 1024, "Lote Unicode por bytes, bajo límite cloud");
        comprobar(!SeguridadNube.cabeEnLote(10, 200, "{}"), "Tope 200 operaciones");
        System.out.println("PASS: PKCE conocido, aleatoriedad, origen/rutas cerradas y lotes UTF-8 bajo límite real.");
    }
}
