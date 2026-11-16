package app.creatorhub.red;

import android.net.Network;
import java.io.IOException;
import java.net.URL;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;
import javax.net.ssl.HostnameVerifier;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/**
 * HTTPS hacia el hub con certificado autofirmado FIJADO (04 §B.7, §C.2): se acepta únicamente el certificado cuyo
 * SHA-256 (DER) coincide con la huella del QR o del paquete de emparejamiento. Se conecta por IP; la identidad la
 * garantiza la huella, no el nombre. La lógica del fijado vive en ProtocoloLan (Java puro, probado en el JDK).
 *
 * Un {@link Canal} conserva la fábrica TLS y el verificador de una huella: así HttpsURLConnection reutiliza las
 * conexiones (keep-alive) en lugar de repetir el handshake en cada imagen.
 */
public final class TlsFijado {
    /** Texto del rechazo del fijado (ProtocoloLan.fabricaFijada). */
    public static final String RECHAZO = "La PC no es la que emparejaste";
    private static final SecureRandom AZAR = new SecureRandom();

    private TlsFijado() { }

    /** Literal de spec/pruebas/android_min: una conexión fijada a `huellaHex`. */
    public static HttpsURLConnection abrir(Network red, URL url, String huellaHex) throws IOException, GeneralSecurityException {
        final byte[] huella = ProtocoloLan.huellaBytes(huellaHex);
        HttpsURLConnection c = (HttpsURLConnection) (red != null ? red.openConnection(url) : url.openConnection());
        c.setSSLSocketFactory(ProtocoloLan.fabricaFijada(huella));
        c.setHostnameVerifier(ProtocoloLan.verificadorFijado(huella));
        c.setConnectTimeout(4000);
        c.setReadTimeout(15000);
        c.setUseCaches(false);
        return c;
    }

    /** Fábrica + verificador de UNA huella, reutilizables entre peticiones. */
    public static final class Canal {
        public final String huella;
        final SSLSocketFactory fabrica;
        final HostnameVerifier verificador;

        public Canal(String huellaHex) throws GeneralSecurityException {
            byte[] h = ProtocoloLan.huellaBytes(huellaHex);
            huella = huellaHex;
            fabrica = ProtocoloLan.fabricaFijada(h);
            verificador = ProtocoloLan.verificadorFijado(h);
        }

        public HttpsURLConnection abrir(Network red, URL url, int conexionMs, int lecturaMs) throws IOException {
            HttpsURLConnection c = (HttpsURLConnection) (red != null ? red.openConnection(url) : url.openConnection());
            c.setSSLSocketFactory(fabrica);
            c.setHostnameVerifier(verificador);
            c.setConnectTimeout(conexionMs);
            c.setReadTimeout(lecturaMs);
            c.setUseCaches(false);
            c.setInstanceFollowRedirects(false);
            return c;
        }
    }

    /**
     * Emparejamiento por código sin QR (04 §C.5): todavía no hay huella que fijar. Este administrador acepta el
     * certificado vigente que presente el hub y ANOTA su huella (f_obs). La prueba del código se calcula con f_obs:
     * si un intermediario terminó el TLS, el hub la rechaza. Después del hello se fija f_obs para todo lo demás.
     */
    public static final class Observador implements X509TrustManager {
        private volatile String huella;

        public String huella() { return huella; }

        @Override public void checkClientTrusted(X509Certificate[] cadena, String tipo) throws CertificateException {
            throw new CertificateException("No se aceptan clientes");
        }

        @Override public void checkServerTrusted(X509Certificate[] cadena, String tipo) throws CertificateException {
            if (cadena == null || cadena.length == 0) throw new CertificateException("La PC no presentó certificado");
            try {
                huella = ProtocoloLan.hex(ProtocoloLan.sha256(cadena[0].getEncoded()));
            } catch (GeneralSecurityException e) {
                throw new CertificateException("Certificado ilegible", e);
            }
            cadena[0].checkValidity();
        }

        @Override public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }

        /** Abre una conexión que anota la huella; el verificador de nombre exige que la sesión sea la anotada. */
        public HttpsURLConnection abrir(Network red, URL url, int conexionMs, int lecturaMs)
                throws IOException, GeneralSecurityException {
            SSLContext ctx = SSLContext.getInstance("TLS");
            ctx.init(null, new TrustManager[] {this}, AZAR);
            HttpsURLConnection c = (HttpsURLConnection) (red != null ? red.openConnection(url) : url.openConnection());
            c.setSSLSocketFactory(ctx.getSocketFactory());
            c.setHostnameVerifier((host, sesion) -> {
                String h = huella;
                if (h == null) return false;
                try {
                    return ProtocoloLan.coincide(sesion.getPeerCertificates()[0], ProtocoloLan.deHex(h));
                } catch (Exception e) {
                    return false;
                }
            });
            c.setConnectTimeout(conexionMs);
            c.setReadTimeout(lecturaMs);
            c.setUseCaches(false);
            c.setInstanceFollowRedirects(false);
            return c;
        }
    }

    /** true si la excepción (o una de sus causas) es el rechazo del fijado: la PC presentó otra identidad. */
    public static boolean esHuellaDistinta(Throwable e) {
        for (Throwable t = e; t != null; t = t.getCause()) {
            String m = t.getMessage();
            if (m != null && m.contains(RECHAZO)) return true;
            if (t.getCause() == t) break;
        }
        return false;
    }
}
