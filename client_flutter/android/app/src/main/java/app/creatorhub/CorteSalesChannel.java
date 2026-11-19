package app.creatorhub;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import app.creatorhub.sales.SalesNotifications;
import com.google.firebase.FirebaseApp;
import com.google.firebase.messaging.FirebaseMessaging;
import io.flutter.plugin.common.BinaryMessenger;
import io.flutter.plugin.common.MethodChannel;
import java.lang.ref.WeakReference;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Native FCM bridge. Registration is performed by authenticated Dart code, never by this service. */
public final class CorteSalesChannel {
    private static WeakReference<CorteSalesChannel> active = new WeakReference<>(null);
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final ExecutorService CONFIGURATION = Executors.newSingleThreadExecutor(
            work -> new Thread(work, "corte-ventas-configuracion"));
    private final Activity activity;
    private final Context context;
    private final CorteNativeChannel notifications;
    private final MethodChannel channel;
    private boolean disposed;

    public CorteSalesChannel(Activity activity, BinaryMessenger messenger, CorteNativeChannel notifications) {
        this.activity = activity;
        this.context = activity.getApplicationContext();
        this.notifications = notifications;
        this.channel = new MethodChannel(messenger, "corte/sales");
        active = new WeakReference<>(this);
        channel.setMethodCallHandler((call, result) -> {
            try {
                switch (call.method) {
                    case "configureSales": {
                        Object value = call.argument("enabled");
                        Object rawScope = call.argument("cache_scope");
                        if (!(value instanceof Boolean) || rawScope != null && !(rawScope instanceof String)) {
                            throw new IllegalArgumentException();
                        }
                        configure((Boolean) value, (String) rawScope, result);
                        break;
                    }
                    case "notificationPermission":
                        result.success(firebaseReady() ? SalesNotifications.permission(context) : "no_disponible");
                        break;
                    case "requestNotificationPermission":
                        if (!firebaseReady()) { result.success("no_disponible"); break; }
                        notifications.requestNotificationPermission(new MethodChannel.Result() {
                            @Override public void success(Object ignored) { result.success(SalesNotifications.permission(context)); }
                            @Override public void error(String code, String message, Object details) {
                                result.error(code, message, details);
                            }
                            @Override public void notImplemented() { result.notImplemented(); }
                        });
                        break;
                    case "pushToken":
                        token(result);
                        break;
                    case "notificationLaunchRoute":
                        result.success(SalesNotifications.isDispatchPaused()
                                ? null : SalesNotifications.consumeRoute(context, activity.getIntent()));
                        break;
                    case "showSaleNotification": {
                        if (SalesNotifications.isDispatchPaused()) { result.success(false); break; }
                        Map<String, Object> payload = new HashMap<>();
                        payload.put("type", "sale"); payload.put("event_id", call.argument("id"));
                        for (String key : new String[] {"titulo", "texto", "ruta", "cache_scope"}) {
                            payload.put(key, call.argument(key));
                        }
                        result.success(SalesNotifications.show(context, payload));
                        break;
                    }
                    default:
                        result.notImplemented();
                }
            } catch (Exception ignored) {
                unavailable(result);
            }
        });
    }

    private void configure(boolean requested, String scope, MethodChannel.Result result) {
        // Suspend local dispatch immediately. The same queue orders writes across activity restarts.
        SalesNotifications.beginConfiguration();
        try {
            if (!requested) clearSalesExtras(activity.getIntent());
            CONFIGURATION.execute(() -> {
                Map<String, Object> state = null;
                try {
                    boolean wasEnabled = !requested && SalesNotifications.configured(context);
                    boolean enabled = requested && firebaseReady(true);
                    SalesNotifications.configure(context, enabled, enabled ? scope : null);
                    boolean ready = enabled || wasEnabled && firebaseReady(false);
                    String permission = ready ? SalesNotifications.permission(context) : "no_disponible";
                    if (ready) FirebaseMessaging.getInstance().setAutoInitEnabled(
                            enabled && "concedido".equals(permission));
                    state = new HashMap<>();
                    state.put("enabled", enabled);
                    state.put("permission", permission);
                } catch (RuntimeException error) {
                    logFailure(error);
                } finally {
                    SalesNotifications.finishConfiguration(state != null);
                }
                final Map<String, Object> configured = state;
                MAIN.post(() -> {
                    if (disposed) return;
                    if (configured == null) unavailable(result);
                    else result.success(configured);
                });
            });
        } catch (RuntimeException error) {
            SalesNotifications.finishConfiguration(false);
            throw error;
        }
    }

    private boolean firebaseReady() { return firebaseReady(true); }

    private boolean firebaseReady(boolean initialize) {
        if (context.getPackageName().endsWith(".dev")) return false;
        try {
            try { FirebaseApp.getInstance(); }
            catch (IllegalStateException missing) {
                if (!initialize || FirebaseApp.initializeApp(context) == null) return false;
            }
            return true;
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    private void token(MethodChannel.Result result) {
        if (SalesNotifications.isDispatchPaused()) { result.success(null); return; }
        final String expectedScope = SalesNotifications.scope(context);
        if (expectedScope == null || !firebaseReady()
                || !"concedido".equals(SalesNotifications.permission(context))) {
            result.success(null); return;
        }
        FirebaseMessaging.getInstance().setAutoInitEnabled(true);
        FirebaseMessaging.getInstance().getToken().addOnCompleteListener(task -> {
            if (disposed) return;
            String stored = null;
            try {
                if (!SalesNotifications.isDispatchPaused() && task.isSuccessful()
                        && expectedScope.equals(SalesNotifications.scope(context))
                        && "concedido".equals(SalesNotifications.permission(context))) {
                    SalesNotifications.rememberToken(context, task.getResult());
                    stored = SalesNotifications.storedToken(context);
                }
            } catch (RuntimeException error) {
                logFailure(error);
            }
            result.success(stored);
        });
    }

    /** Called by Firebase without forwarding token values through callbacks or logs. */
    public static void tokenChanged() {
        MAIN.post(() -> {
            CorteSalesChannel bridge = active.get();
            try {
                if (bridge != null && !bridge.disposed && SalesNotifications.enabled(bridge.context)
                        && "concedido".equals(SalesNotifications.permission(bridge.context))) {
                    bridge.channel.invokeMethod("pushTokenChanged", null);
                }
            } catch (RuntimeException error) {
                logFailure(error);
            }
        });
    }

    /** Sales intents are isolated from reminder intents and checked again against the current creator. */
    public boolean notificationOpened(Intent intent) {
        try {
            if (intent == null || !intent.hasExtra(SalesNotifications.EXTRA_SCOPE)) return false;
            if (!SalesNotifications.isDispatchPaused() && SalesNotifications.validTap(context, intent)) {
                channel.invokeMethod("saleNotificationOpened", null);
            } else clearSalesExtras(intent);
        } catch (RuntimeException error) {
            logFailure(error);
        }
        return true;
    }

    private static void unavailable(MethodChannel.Result result) {
        result.error("sales_unavailable", "No pudimos configurar las notificaciones de ventas.", null);
    }

    private static void logFailure(RuntimeException error) {
        Log.w("CorteVentas", "No pudimos configurar los avisos: " + error.getClass().getSimpleName());
    }

    private static void clearSalesExtras(Intent intent) {
        if (intent == null) return;
        intent.removeExtra(SalesNotifications.EXTRA_SCOPE);
        intent.removeExtra(SalesNotifications.EXTRA_ROUTE);
    }

    public void dispose() {
        disposed = true;
        channel.setMethodCallHandler(null);
        if (active.get() == this) active.clear();
    }
}
