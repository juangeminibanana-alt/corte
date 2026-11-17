package app.creatorhub.sales;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Map;
import java.util.regex.Pattern;

/** Pure validation shared by background FCM and the authenticated catch-up feed. */
public final class SalesMessagePolicy {
    private static final Pattern SCOPE = Pattern.compile("[0-9a-f]{64}");
    private static final Pattern ID = Pattern.compile("[A-Za-z0-9._:-]{1,160}");
    private static final Pattern CONTROL = Pattern.compile("[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f]");
    public static final String ROUTE = "#/ventas";

    private SalesMessagePolicy() { }

    public static boolean validScope(String scope) {
        return scope != null && SCOPE.matcher(scope).matches();
    }

    public static final class Message {
        public final String id, scope, title, text, key;
        private Message(String id, String scope, String title, String text) {
            this.id = id; this.scope = scope; this.title = title; this.text = text;
            key = stableKey(scope, id);
        }
    }

    public static Message parse(Map<String, ?> data, String currentScope) {
        if (data == null || !validScope(currentScope) || !"sale".equals(data.get("type"))) return null;
        Object scope = data.get("cache_scope"), id = data.get("event_id");
        Object title = data.get("titulo"), text = data.get("texto");
        if (!(scope instanceof String) || !currentScope.equals(scope)
                || !(id instanceof String) || !ID.matcher((String) id).matches()
                || !(title instanceof String) || !(text instanceof String)
                || !ROUTE.equals(data.get("ruta"))) return null;
        String cleanTitle = ((String) title).trim(), cleanText = ((String) text).trim();
        if (cleanTitle.isEmpty() || cleanTitle.length() > 120 || cleanText.length() > 400
                || CONTROL.matcher(cleanTitle).find() || CONTROL.matcher(cleanText).find()) return null;
        return new Message((String) id, currentScope, cleanTitle, cleanText);
    }

    public static String stableKey(String scope, String eventId) {
        try {
            byte[] bytes = MessageDigest.getInstance("SHA-256")
                    .digest((scope + "\u0000" + eventId).getBytes(StandardCharsets.UTF_8));
            StringBuilder result = new StringBuilder(64);
            for (byte value : bytes) result.append(String.format(java.util.Locale.ROOT, "%02x", value & 0xff));
            return result.toString();
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 unavailable");
        }
    }
}
