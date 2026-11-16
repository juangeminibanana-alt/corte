package app.creatorhub.red;
public final class ClienteHub {
    public boolean conectado=true;
    public Respuesta respuesta;
    public boolean esNube() { return true; }
    public boolean emparejado() { return true; }
    public boolean conectado() { return conectado; }
    public void marcarDesconectado() { conectado=false; }
    public Respuesta pedir(Peticion p) throws java.io.IOException { return respuesta; }
    public static final class Peticion {
        public Peticion(String m,String r) { }
        public Peticion limite(long n) { return this; }
    }
    public static final class Respuesta {
        public final int codigo;
        public final String tipo;
        public final byte[] cuerpo;
        private final java.util.Map<String,String> headers;
        public Respuesta(int s,String m,byte[] b,java.util.Map<String,String> h) { codigo=s;tipo=m;cuerpo=b;headers=h; }
        public String cabecera(String n) { return headers.get(n); }
    }
}
