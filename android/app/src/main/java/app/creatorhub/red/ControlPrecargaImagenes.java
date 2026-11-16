package app.creatorhub.red;

/** Hasta tres intentos por conjunto de imágenes y sesión en primer plano, separados por un minuto. */
public final class ControlPrecargaImagenes {
    private String clave;
    private int intentos;
    private long siguiente;
    public synchronized void reiniciar() { clave = null; intentos = 0; siguiente = 0; }
    public synchronized boolean intentar(String nuevaClave, long ahoraMs) {
        if (!nuevaClave.equals(clave)) { clave = nuevaClave; intentos = 0; siguiente = 0; }
        if (intentos >= 3 || ahoraMs < siguiente) return false;
        intentos++;
        siguiente = ahoraMs + 60_000;
        return true;
    }
}
