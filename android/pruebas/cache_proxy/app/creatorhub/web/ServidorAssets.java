package app.creatorhub.web;
public final class ServidorAssets {
    public static android.webkit.WebResourceResponse json(int c,String r,String b,java.util.Map<String,String> h) {
        return new android.webkit.WebResourceResponse("application/json","UTF-8",c,r,h,new java.io.ByteArrayInputStream(b.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
    }
    public static android.webkit.WebResourceResponse vacio(int c,String r) { return json(c,r,"",java.util.Map.of()); }
}
