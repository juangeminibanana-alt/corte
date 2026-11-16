package android.net;
public final class Uri {
    private final java.net.URI uri;
    private Uri(String s) { uri = java.net.URI.create(s); }
    public static Uri parse(String s) { return new Uri(s); }
    public String getEncodedPath() { return uri.getRawPath(); }
    public String getPath() { return uri.getPath(); }
    public String getEncodedQuery() { return uri.getRawQuery(); }
}
