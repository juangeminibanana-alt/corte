package app.creatorhub.datos;
public final class CopiaSinConexion {
    public final java.util.Map<String,java.io.File> cache = new java.util.HashMap<>();
    public static String normalizarImagen(String ruta) { return ruta; }
    public static java.util.List<String> alternativas(String ruta) {
        String base=ruta.split("&t=")[0];
        return java.util.List.of(ruta,base+"&t=sm",base+"&t=md",base+"&t=xs",base);
    }
    public java.io.File imagenEnCache(String ruta) { return cache.get(ruta); }
    public void guardarImagen(String ruta,byte[] body) {
        try { java.io.File f=java.io.File.createTempFile("corte-imagen-qa-",".bin");java.nio.file.Files.write(f.toPath(),body);cache.put(ruta,f); }
        catch(java.io.IOException e) { throw new RuntimeException(e); }
    }
    public void guardarImagen(String ruta,byte[] body,String etag) { guardarImagen(ruta,body); }
    public static String mimeDe(java.io.File f) { return "image/webp"; }
    public boolean existe() { return false; }
    public Meta meta() { return new Meta(); }
    public java.io.InputStream abrirDescomprimida() throws java.io.IOException { return null; }
    public static final class Meta { public long copiaAt=1; }
}
