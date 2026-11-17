package app.creatorhub.sales;

import java.util.Comparator;
import java.util.HashMap;
import java.util.Map;

/** Bounded persistent identifiers; no order text, token or customer data is retained. */
public final class SalesDeliveryLedger {
    public static final int MAX_EVENTS = 2048;
    public static final long RETENTION_MS = 48L * 60 * 60 * 1000;
    private SalesDeliveryLedger() { }

    public static Map<String, Long> prune(Map<String, Long> existing, long now) {
        Map<String, Long> result = new HashMap<>();
        for (Map.Entry<String, Long> entry : existing.entrySet()) {
            Long time = entry.getValue();
            if (entry.getKey().matches("[0-9a-f]{64}") && time != null
                    && time >= now - RETENTION_MS && time <= now + 5 * 60 * 1000) {
                result.put(entry.getKey(), time);
            }
        }
        if (result.size() > MAX_EVENTS) {
            String[] oldest = result.entrySet().stream().sorted(Comparator.comparingLong(Map.Entry::getValue))
                    .limit(result.size() - MAX_EVENTS).map(Map.Entry::getKey).toArray(String[]::new);
            for (String key : oldest) result.remove(key);
        }
        return result;
    }
}
