package app.creatorhub;
public final class Nucleo {
    public final app.creatorhub.red.ClienteHub cliente = new app.creatorhub.red.ClienteHub();
    public final app.creatorhub.datos.CopiaSinConexion copia = new app.creatorhub.datos.CopiaSinConexion();
    public void avisarConexion() { }
    public void refrescarCopia(boolean p) { }
    public org.json.JSONObject estadoNativo() { return new org.json.JSONObject(); }
}
