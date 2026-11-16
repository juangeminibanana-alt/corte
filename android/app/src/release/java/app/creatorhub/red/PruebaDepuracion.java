package app.creatorhub.red;

import android.app.Activity;
import android.content.Intent;
import app.creatorhub.Nucleo;

/**
 * Variante release: las pruebas de depuración (`ch_prueba_tls`, `ch_prueba_web`) NO existen. Métodos vacíos que R8
 * elimina; la implementación real vive solo en src/debug (app.creatorhub.dev).
 */
public final class PruebaDepuracion {
    private PruebaDepuracion() { }

    /** Siempre false: la app carga su interfaz normal. */
    public static boolean alCrear(Activity act, Nucleo n, Intent i) { return false; }

    public static void paginaLista(Activity act, Intent i) { }
}
