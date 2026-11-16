package app.creatorhub.datos;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * Almacén de secretos con Android Keystore puro (04 §B.6; base: spec/pruebas/android_min, probado en Android 14).
 * Clave AES-256-GCM no exportable dentro del Keystore; en SharedPreferences solo se guarda "b64(iv):b64(cifrado)".
 * El nombre del valor va como AAD para que un cifrado no pueda moverse a otra entrada. `allowBackup=false` +
 * `dataExtractionRules`: nada sale del teléfono. Si `leer()` devuelve null hay que emparejar de nuevo.
 */
public final class AlmacenSeguro {
    private static final String KEYSTORE = "AndroidKeyStore";
    private static final String ALIAS = "creatorhub.emparejamiento.v1";
    private static final String PREFS = "creatorhub_seguro";
    private final SharedPreferences prefs;

    public AlmacenSeguro(Context contexto) {
        prefs = contexto.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private SecretKey clave() throws GeneralSecurityException, IOException {
        KeyStore ks = KeyStore.getInstance(KEYSTORE);
        ks.load(null);
        KeyStore.Entry e = ks.getEntry(ALIAS, null);
        if (e instanceof KeyStore.SecretKeyEntry) return ((KeyStore.SecretKeyEntry) e).getSecretKey();
        KeyGenerator kg = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE);
        kg.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .setRandomizedEncryptionRequired(true)
                .build());
        return kg.generateKey();
    }

    public synchronized void guardar(String nombre, String valor) throws GeneralSecurityException, IOException {
        Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.ENCRYPT_MODE, clave());
        c.updateAAD(nombre.getBytes(StandardCharsets.UTF_8));
        byte[] cifrado = c.doFinal(valor.getBytes(StandardCharsets.UTF_8));
        String guardado = Base64.encodeToString(c.getIV(), Base64.NO_WRAP) + ":"
                + Base64.encodeToString(cifrado, Base64.NO_WRAP);
        if (!prefs.edit().putString(nombre, guardado).commit()) throw new IOException("No se pudo guardar");
    }

    /** Devuelve null si no existe o si ya no se puede descifrar (p. ej. tras restaurar el teléfono). */
    public synchronized String leer(String nombre) {
        String guardado = prefs.getString(nombre, null);
        if (guardado == null) return null;
        int sep = guardado.indexOf(':');
        if (sep <= 0) return null;
        try {
            byte[] iv = Base64.decode(guardado.substring(0, sep), Base64.NO_WRAP);
            byte[] cifrado = Base64.decode(guardado.substring(sep + 1), Base64.NO_WRAP);
            Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
            c.init(Cipher.DECRYPT_MODE, clave(), new GCMParameterSpec(128, iv));
            c.updateAAD(nombre.getBytes(StandardCharsets.UTF_8));
            return new String(c.doFinal(cifrado), StandardCharsets.UTF_8);
        } catch (GeneralSecurityException | IOException | IllegalArgumentException e) {
            return null;
        }
    }

    public synchronized void borrar(String nombre) {
        prefs.edit().remove(nombre).commit();
    }

    /** "Olvidar esta PC": borra todas las entradas (la clave del Keystore se conserva para el próximo emparejamiento). */
    public synchronized void borrarTodo() {
        prefs.edit().clear().commit();
    }
}
