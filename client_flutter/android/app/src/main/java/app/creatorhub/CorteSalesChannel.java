package app.creatorhub;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.os.Handler;
import android.os.Looper;
import app.creatorhub.sales.SalesNotifications;
import com.google.firebase.FirebaseApp;
import com.google.firebase.messaging.FirebaseMessaging;
import io.flutter.plugin.common.BinaryMessenger;
import io.flutter.plugin.common.MethodChannel;
import java.lang.ref.WeakReference;
import java.util.HashMap;
import java.util.Map;

/** Native FCM bridge. Registration is performed by authenticated Dart code, never by this service. */
public final class CorteSalesChannel {
    private static WeakReference<CorteSalesChannel> active = new WeakReference<>(null);
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
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
                        boolean requested = (Boolean) value;
                        boolean ready = firebaseReady();
                        boolean enabled = requested && ready;
                        SalesNotifications.configure(context, enabled, enabled ? (String) rawScope : null);
                        if (ready) FirebaseMessaging.getInstance().setAutoInitEnabled(
                                enabled && "concedido".equals(SalesNotifications.permission(context)));
                        if (!enabled || !SalesNotifications.validTap(context, activity.getIntent())) {
                            clearSalesExtras(activity.getIntent());
                        }
                        Map<String, Object> state = new HashMap<>();
                        state.put("enabled", SalesNotifications.enabled(context));
                        state.put("permission", ready ? SalesNotifications.permission(context) : "no_disponible");
                        result.success(state);
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
                        result.success(SalesNotifications.consumeRoute(context, activity.getIntent()));
                        break;
                    case "showSaleNotification": {
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
                result.error("sales_unavailable", "No pudimos configurar las notificaciones de ventas.", null);
            }
        });
    }

    private boolean firebaseReady() {
        if (context.getPackageName().endsWith(".dev")) return false;
        try {
            try { FirebaseApp.getInstance(); }
            catch (IllegalStateException missing) {
                if (FirebaseApp.initializeApp(context) == null) return false;
            }
            return true;
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    private void token(MethodChannel.Result result) {
        if (!firebaseReady() || !SalesNotifications.enabled(context)
                || !"concedido".equals(SalesNotifications.permission(context))) {
            result.success(null); return;
        }
        final String expectedScope = SalesNotifications.scope(context);
        FirebaseMessaging.getInstance().setAutoInitEnabled(true);
        FirebaseMessaging.getInstance().getToken().addOnCompleteListener(task -> {
            if (disposed) return;
            if (!task.isSuccessful() || !SalesNotifications.enabled(context)
                    || !expectedScope.equals(SalesNotifications.scope(context))
                    || !"concedido".equals(SalesNotifications.permission(context))) {
                result.success(null); return;
            }
            String token = task.getResult();
            SalesNotifications.rememberToken(context, token);
            result.success(SalesNotifications.storedToken(context));
        });
    }

    /** Called by Firebase without forwarding token values through callbacks or logs. */
    public static void tokenChanged() {
        MAIN.post(() -> {
            CorteSalesChannel bridge = active.get();
            if (bridge != null && !bridge.disposed && SalesNotifications.enabled(bridge.context)
                    && "concedido".equals(SalesNotifications.permission(bridge.context))) {
                bridge.channel.invokeMethod("pushTokenChanged", null);
            }
        });
    }

    /** Sales intents are isolated from reminder intents and checked again against the current creator. */
    public boolean notificationOpened(Intent intent) {
        if (intent == null || !intent.hasExtra(SalesNotifications.EXTRA_SCOPE)) return false;
        if (SalesNotifications.validTap(context, intent)) channel.invokeMethod("saleNotificationOpened", null);
        else clearSalesExtras(intent);
        return true;
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
