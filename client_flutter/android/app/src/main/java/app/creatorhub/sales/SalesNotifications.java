package app.creatorhub.sales;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.service.notification.StatusBarNotification;
import app.creatorhub.MainActivity;
import app.creatorhub.R;
import app.creatorhub.sistema.Recordatorios;
import java.util.HashMap;
import java.util.Map;

/** Scope is persisted before enabling delivery, including when the Flutter engine is stopped. */
public final class SalesNotifications {
    private static final String PREFS = "corte_sales_push_v1";
    private static final String SEEN = "seen_";
    private static final String CHANNEL = "corte_sales";
    private static final String TAG = "corte.sale.";
    public static final String EXTRA_ROUTE = "app.creatorhub.SALES_ROUTE";
    public static final String EXTRA_SCOPE = "app.creatorhub.SALES_SCOPE";
    private static final Object DISPATCH_STATE = new Object();
    private static int pendingConfigurations;
    private static volatile boolean dispatchPaused;

    private SalesNotifications() { }

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    public static void beginConfiguration() {
        synchronized (DISPATCH_STATE) {
            pendingConfigurations++;
            dispatchPaused = true;
        }
    }

    public static void finishConfiguration(boolean succeeded) {
        synchronized (DISPATCH_STATE) {
            pendingConfigurations--;
            dispatchPaused = pendingConfigurations != 0 || !succeeded;
        }
    }

    public static boolean isDispatchPaused() {
        return dispatchPaused;
    }

    public static synchronized boolean configured(Context context) {
        SharedPreferences p = prefs(context);
        try {
            return !context.getPackageName().endsWith(".dev") && p.getBoolean("enabled", false)
                    && SalesMessagePolicy.validScope(p.getString("scope", null));
        } catch (ClassCastException malformedPreferences) {
            return false;
        }
    }

    public static boolean enabled(Context context) {
        return !isDispatchPaused() && configured(context) && !isDispatchPaused();
    }

    public static synchronized String scope(Context context) {
        return enabled(context) ? prefs(context).getString("scope", null) : null;
    }

    public static synchronized void configure(Context context, boolean enabled, String scope) {
        if (enabled && !SalesMessagePolicy.validScope(scope)) throw new IllegalArgumentException();
        SharedPreferences p = prefs(context);
        boolean changed = !enabled || !scope.equals(storedScope(p));
        SharedPreferences.Editor update = p.edit();
        if (changed) {
            update.remove("token");
            // Cold startup first clears the active context before Dart authenticates.
            // Retain only opaque replay hashes so an already shown FCM event is
            // acknowledged by the catch-up feed instead of notifying twice.
            writeLedger(p, update, ledger(p, System.currentTimeMillis()));
            cancelVisible(context);
        }
        update.putBoolean("enabled", enabled);
        if (enabled) update.putString("scope", scope); else update.remove("scope");
        if (!update.commit()) throw new IllegalStateException("Sales state unavailable");
        if (enabled) createChannel(context);
    }

    private static String storedScope(SharedPreferences preferences) {
        try {
            return preferences.getString("scope", null);
        } catch (ClassCastException malformedPreferences) {
            return null;
        }
    }

    public static synchronized String permission(Context context) {
        if (context.getPackageName().endsWith(".dev")) return "no_disponible";
        if (!"concedido".equals(Recordatorios.permiso(context))) return "denegado";
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        NotificationChannel channel = manager == null ? null : manager.getNotificationChannel(CHANNEL);
        return channel != null && channel.getImportance() == NotificationManager.IMPORTANCE_NONE
                ? "denegado" : "concedido";
    }

    public static synchronized void rememberToken(Context context, String token) {
        // A registration token never leaves native code while sales are disabled or permission is absent.
        if (!enabled(context) || !"concedido".equals(permission(context))) return;
        if (token == null || token.length() < 20 || token.length() > 4096) return;
        prefs(context).edit().putString("token", token).apply();
    }

    public static synchronized String storedToken(Context context) {
        return enabled(context) && "concedido".equals(permission(context))
                ? prefs(context).getString("token", null) : null;
    }

    public static synchronized boolean show(Context context, Map<String, ?> data) {
        if (!enabled(context) || !"concedido".equals(permission(context))) return false;
        String current = scope(context);
        SalesMessagePolicy.Message message = SalesMessagePolicy.parse(data, current);
        if (message == null) return false;
        SharedPreferences p = prefs(context);
        long now = System.currentTimeMillis();
        Map<String, Long> seen = ledger(p, now);
        if (seen.containsKey(message.key)) return true;
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null) return false;
        createChannel(context);
        Intent open = new Intent(context, MainActivity.class)
                .setAction("app.creatorhub.SALES." + message.key)
                .setData(Uri.parse("corte://ventas/" + message.key))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP)
                .putExtra(EXTRA_ROUTE, SalesMessagePolicy.ROUTE)
                .putExtra(EXTRA_SCOPE, current);
        PendingIntent tap = PendingIntent.getActivity(context, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification notification = new Notification.Builder(context, CHANNEL)
                .setSmallIcon(R.drawable.ic_notificacion)
                .setColor(context.getColor(R.color.acento))
                .setContentTitle(message.title).setContentText(message.text)
                .setStyle(new Notification.BigTextStyle().bigText(message.text))
                .setContentIntent(tap).setAutoCancel(true).setOnlyAlertOnce(true)
                .setCategory(Notification.CATEGORY_EVENT).setVisibility(Notification.VISIBILITY_PRIVATE)
                .setGroup("corte.sales").build();
        if (isDispatchPaused()) return false;
        try {
            manager.notify(TAG + message.key, 0, notification);
        } catch (SecurityException ignored) {
            return false;
        }
        seen.put(message.key, now);
        seen = SalesDeliveryLedger.prune(seen, now);
        SharedPreferences.Editor update = p.edit();
        writeLedger(p, update, seen);
        update.commit();
        return true;
    }

    private static Map<String, Long> ledger(SharedPreferences p, long now) {
        Map<String, Long> seen = new HashMap<>();
        for (Map.Entry<String, ?> entry : p.getAll().entrySet()) {
            if (entry.getKey().startsWith(SEEN) && entry.getValue() instanceof Long) {
                seen.put(entry.getKey().substring(SEEN.length()), (Long) entry.getValue());
            }
        }
        return SalesDeliveryLedger.prune(seen, now);
    }

    private static void writeLedger(SharedPreferences p, SharedPreferences.Editor update, Map<String, Long> seen) {
        for (String key : p.getAll().keySet()) if (key.startsWith(SEEN)) update.remove(key);
        for (Map.Entry<String, Long> entry : seen.entrySet()) update.putLong(SEEN + entry.getKey(), entry.getValue());
    }

    public static synchronized String consumeRoute(Context context, Intent intent) {
        if (intent == null || !intent.hasExtra(EXTRA_SCOPE)) return null;
        String requestedScope = intent.getStringExtra(EXTRA_SCOPE);
        String route = intent.getStringExtra(EXTRA_ROUTE);
        intent.removeExtra(EXTRA_SCOPE); intent.removeExtra(EXTRA_ROUTE);
        String scope = scope(context);
        return scope != null && scope.equals(requestedScope)
                && SalesMessagePolicy.ROUTE.equals(route) ? route : null;
    }

    public static synchronized boolean validTap(Context context, Intent intent) {
        String scope = scope(context);
        return intent != null && scope != null && scope.equals(intent.getStringExtra(EXTRA_SCOPE))
                && SalesMessagePolicy.ROUTE.equals(intent.getStringExtra(EXTRA_ROUTE));
    }

    private static void cancelVisible(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null) return;
        for (StatusBarNotification notification : manager.getActiveNotifications()) {
            if (notification.getTag() != null && notification.getTag().startsWith(TAG)) {
                manager.cancel(notification.getTag(), notification.getId());
            }
        }
    }

    private static void createChannel(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null || manager.getNotificationChannel(CHANNEL) != null) return;
        NotificationChannel channel = new NotificationChannel(CHANNEL, context.getString(R.string.canal_ventas),
                NotificationManager.IMPORTANCE_HIGH);
        channel.setDescription(context.getString(R.string.canal_ventas_desc));
        manager.createNotificationChannel(channel);
    }
}
