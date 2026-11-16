package android.webkit;
public final class WebResourceResponse {
    public final String mime;
    public final int status;
    public final java.util.Map<String,String> headers;
    public final java.io.InputStream body;
    public WebResourceResponse(String m, String e, int s, String r, java.util.Map<String,String> h, java.io.InputStream b) {
        mime=m; status=s; headers=h; body=b;
    }
}
