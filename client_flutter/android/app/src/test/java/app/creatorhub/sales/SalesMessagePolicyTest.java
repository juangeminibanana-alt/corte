package app.creatorhub.sales;

import java.util.HashMap;
import java.util.Map;

/** Standalone JVM checks; no device, FCM traffic, SDK configuration or test credentials. */
public final class SalesMessagePolicyTest {
    private static final String SCOPE = "a".repeat(64);
    private static int checks;
    private static void require(boolean condition) {
        checks++;
        if (!condition) throw new AssertionError("Sales policy check " + checks);
    }

    private static Map<String, Object> message() {
        Map<String, Object> value = new HashMap<>();
        value.put("type", "sale"); value.put("event_id", "sale:synthetic-100");
        value.put("cache_scope", SCOPE); value.put("titulo", "Nueva venta");
        value.put("texto", "Comisión estimada: $12.34"); value.put("ruta", "#/ventas");
        return value;
    }

    public static void main(String[] args) {
        SalesMessagePolicy.Message valid = SalesMessagePolicy.parse(message(), SCOPE);
        require(valid != null && valid.title.equals("Nueva venta"));
        require(valid.key.matches("[0-9a-f]{64}"));
        require(SalesMessagePolicy.parse(message(), "b".repeat(64)) == null);
        require(SalesMessagePolicy.parse(message(), null) == null);
        require(!SalesMessagePolicy.validScope("A".repeat(64)));
        for (String key : new String[] {"type", "event_id", "cache_scope", "titulo", "texto", "ruta"}) {
            Map<String, Object> malformed = message(); malformed.remove(key);
            require(SalesMessagePolicy.parse(malformed, SCOPE) == null);
        }
        for (Map.Entry<String, Object> bad : Map.<String, Object>of(
                "type", "sample", "event_id", "../../100", "ruta", "https://example.test",
                "titulo", "x".repeat(121), "texto", "x".repeat(401), "cache_scope", "invalid").entrySet()) {
            Map<String, Object> malformed = message(); malformed.put(bad.getKey(), bad.getValue());
            require(SalesMessagePolicy.parse(malformed, SCOPE) == null);
        }
        Map<String, Object> control = message(); control.put("texto", "bad\u0000text");
        require(SalesMessagePolicy.parse(control, SCOPE) == null);
        Map<String, Object> unicode = message(); unicode.put("texto", "Venta de chamarra 🛍️");
        require(SalesMessagePolicy.parse(unicode, SCOPE) != null);
        require(SalesMessagePolicy.stableKey(SCOPE, "sale:100").equals(SalesMessagePolicy.stableKey(SCOPE, "sale:100")));
        require(!SalesMessagePolicy.stableKey(SCOPE, "sale:100").equals(SalesMessagePolicy.stableKey(SCOPE, "sale:101")));
        require(!SalesMessagePolicy.stableKey(SCOPE, "sale:100").equals(SalesMessagePolicy.stableKey("b".repeat(64), "sale:100")));
        long now = 2_000_000_000L;
        Map<String, Long> ledger = new HashMap<>();
        ledger.put(valid.key, now);
        ledger.put("invalid", now);
        ledger.put("b".repeat(64), now - SalesDeliveryLedger.RETENTION_MS - 1);
        ledger.put("c".repeat(64), now + 10 * 60 * 1000);
        require(SalesDeliveryLedger.prune(ledger, now).size() == 1);
        require(SalesDeliveryLedger.prune(ledger, now).containsKey(valid.key));
        for (int n = 0; n < SalesDeliveryLedger.MAX_EVENTS + 20; n++) {
            ledger.put(SalesMessagePolicy.stableKey(SCOPE, "event:" + n), now - n);
        }
        Map<String, Long> bounded = SalesDeliveryLedger.prune(ledger, now);
        require(bounded.size() == SalesDeliveryLedger.MAX_EVENTS);
        require(bounded.containsKey(valid.key));
        require(!bounded.containsKey(SalesMessagePolicy.stableKey(SCOPE, "event:" + (SalesDeliveryLedger.MAX_EVENTS + 19))));
        require(ledger.size() > bounded.size());
        System.out.println("PASS: " + checks + " sales payload, scope, stable identity and replay-retention checks");
    }
}
