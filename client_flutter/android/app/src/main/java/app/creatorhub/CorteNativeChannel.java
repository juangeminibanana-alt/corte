package app.creatorhub;

import android.content.Context;
import android.app.Activity;
import android.app.ActivityManager;
import android.app.ApplicationExitInfo;
import android.Manifest;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import app.creatorhub.datos.AlmacenSeguro;
import app.creatorhub.sistema.Recordatorios;
import io.flutter.plugin.common.BinaryMessenger;
import io.flutter.plugin.common.MethodChannel;
import java.io.File;
import java.io.FileInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/** Native-only storage. No WebView/JavaScript bridge and no credential logging. */
public final class CorteNativeChannel {
    private static final Set<String> KEYS = new HashSet<>(Arrays.asList(
        "corte.nube.dispositivo.v1", "corte.nube.autorizacion.v1", "corte.nube.propietario.v1"));
    private static final int MAX_LEGACY = 20 * 1024 * 1024;
    private final Context context;
    private final Activity activity;
    private final AlmacenSeguro secure;
    private final MethodChannel channel;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Handler main = new Handler(Looper.getMainLooper());
    private MethodChannel.Result pendingPermission;
    private static final int NOTIFICATION_PERMISSION = 2217;

    CorteNativeChannel(Activity context, BinaryMessenger messenger) {
        activity = context;
        this.context = context.getApplicationContext();
        secure = new AlmacenSeguro(this.context);
        channel = new MethodChannel(messenger, "corte/native");
        channel.setMethodCallHandler((call, result) -> {
            if ("requestNotificationPermission".equals(call.method)) {
                main.post(() -> requestPermission(result)); return;
            }
            if ("notificationLaunchRoute".equals(call.method)) {
                String route = activity.getIntent().getStringExtra(Recordatorios.EXTRA_RUTA);
                activity.getIntent().removeExtra(Recordatorios.EXTRA_RUTA);
                result.success(route != null && route.matches("#/[A-Za-z0-9/_.~?=&%-]{0,200}") ? route : null);
                return;
            }
            if ("filesDirectory".equals(call.method)) {
                try {
                    result.success(this.context.getFilesDir().getAbsolutePath());
                } catch (RuntimeException ignored) {
                    storageUnavailable(result);
                }
                return;
            }
            worker.execute(() -> {
                try {
                    Object value;
                    switch (call.method) {
                        case "secureRead": value = secure.leer(key(call.argument("key"))); break;
                        case "secureWrite": {
                            String key = key(call.argument("key"));
                            Object raw = call.argument("value");
                            if (!(raw instanceof String) || ((String) raw).getBytes(StandardCharsets.UTF_8).length > 65536)
                                throw new IllegalArgumentException();
                            secure.guardar(key, (String) raw); value = null; break;
                        }
                        case "secureDelete": secure.borrar(key(call.argument("key"))); value = null; break;
                        case "legacyInfo": value = info(); break;
                        case "dataRoot": value = dataRoot().getAbsolutePath(); break;
                        case "legacyRead": value = readLegacy(call.argument("name")); break;
                        case "lastAndroidExit": value = lastAndroidExit(); break;
                        case "notificationPermission": value = Recordatorios.permiso(this.context); break;
                        case "scheduleNotifications": {
                            Object raw = call.argument("notifications");
                            if (!(raw instanceof String) || ((String) raw).getBytes(StandardCharsets.UTF_8).length > 65536)
                                throw new IllegalArgumentException();
                            org.json.JSONArray notifications = new org.json.JSONArray((String) raw);
                            if (notifications.length() > 64) throw new IllegalArgumentException();
                            Recordatorios.programar(this.context, notifications.toString()); value = null; break;
                        }
                        default: main.post(result::notImplemented); return;
                    }
                    main.post(() -> result.success(value));
                } catch (Exception ignored) {
                    main.post(() -> storageUnavailable(result));
                }
            });
        });
    }

    private static void storageUnavailable(MethodChannel.Result result) {
        result.error("native_storage_unavailable",
            "No pudimos acceder al almacenamiento privado. Los datos anteriores se conservan.", null);
    }

    private void requestPermission(MethodChannel.Result result) {
        if (Build.VERSION.SDK_INT < 33 || activity.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) {
            result.success(Recordatorios.permiso(context)); return;
        }
        if (pendingPermission != null) { result.error("permission_request_pending", "Ya hay una solicitud de permiso abierta.", null); return; }
        if (activity.isFinishing() || activity.isDestroyed()) { result.error("activity_closed", "La pantalla ya se cerró.", null); return; }
        pendingPermission = result;
        try {
            activity.requestPermissions(new String[] {Manifest.permission.POST_NOTIFICATIONS}, NOTIFICATION_PERMISSION);
        } catch (RuntimeException ignored) {
            pendingPermission = null;
            result.error("permission_unavailable", "No pudimos abrir la solicitud de permiso.", null);
        }
    }

    /** Shares the existing permission request with sales; reminder behavior and request IDs stay unchanged. */
    public void requestNotificationPermission(MethodChannel.Result result) {
        main.post(() -> requestPermission(result));
    }

    public void permissionResult(int requestCode) {
        if (requestCode != NOTIFICATION_PERMISSION || pendingPermission == null) return;
        MethodChannel.Result result = pendingPermission; pendingPermission = null;
        result.success(Recordatorios.permiso(context));
    }

    public void notificationOpened() { channel.invokeMethod("notificationOpened", null); }

    private Map<String, Object> lastAndroidExit() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return null;
        ActivityManager manager = context.getSystemService(ActivityManager.class);
        if (manager == null) return null;
        String ownProcess = context.getPackageName();
        long recent = System.currentTimeMillis() - TimeUnit.DAYS.toMillis(7);
        for (ApplicationExitInfo exit : manager.getHistoricalProcessExitReasons(ownProcess, 0, 10)) {
            if (!ownProcess.equals(exit.getProcessName()) || exit.getTimestamp() < recent) continue;
            String reason;
            switch (exit.getReason()) {
                case ApplicationExitInfo.REASON_CRASH: reason = "crash"; break;
                case ApplicationExitInfo.REASON_CRASH_NATIVE: reason = "native_crash"; break;
                case ApplicationExitInfo.REASON_ANR: reason = "unresponsive"; break;
                case ApplicationExitInfo.REASON_LOW_MEMORY: reason = "low_memory"; break;
                case ApplicationExitInfo.REASON_INITIALIZATION_FAILURE: reason = "startup_failure"; break;
                case ApplicationExitInfo.REASON_EXCESSIVE_RESOURCE_USAGE: reason = "resource_limit"; break;
                default: continue;
            }
            Map<String, Object> report = new HashMap<>();
            report.put("reason", reason);
            report.put("status", exit.getStatus());
            report.put("sdk", Build.VERSION.SDK_INT);
            report.put("time", exit.getTimestamp() / 1000);
            return report;
        }
        return null;
    }

    private static String key(Object key) {
        if (!(key instanceof String) || !KEYS.contains(key)) throw new IllegalArgumentException();
        return (String) key;
    }

    private File dataRoot() throws java.io.IOException {
        File root = new File(context.getFilesDir(), "flutter_client");
        if (!root.isDirectory() && !root.mkdirs()) throw new java.io.IOException();
        return root;
    }

    private File legacyFile(Object name) {
        if (!(name instanceof String)) throw new IllegalArgumentException();
        String relative;
        switch ((String) name) {
            case "snapshot": relative = "copia/snapshot.json.gz"; break;
            case "meta": relative = "copia/meta.json"; break;
            case "outbox": relative = "cola/ops.jsonl"; break;
            case "archive_snapshot": relative = "anterior_nube/snapshot.json.gz"; break;
            case "archive_outbox": relative = "anterior_nube/ops.jsonl"; break;
            default: throw new IllegalArgumentException();
        }
        return new File(context.getFilesDir(), relative);
    }

    private Map<String, Object> info() throws java.io.IOException {
        Map<String, Object> info = new HashMap<>();
        info.put("platform", "android");
        info.put("dataRoot", dataRoot().getAbsolutePath());
        info.put("legacyRoot", context.getFilesDir().getAbsolutePath());
        for (String[] item : new String[][] {{"hasSnapshot","snapshot"},{"hasMeta","meta"},{"hasOutbox","outbox"},
                {"hasArchiveSnapshot","archive_snapshot"},{"hasArchiveOutbox","archive_outbox"}})
            info.put(item[0], legacyFile(item[1]).isFile());
        return info;
    }

    private byte[] readLegacy(Object name) throws java.io.IOException {
        File file = legacyFile(name);
        if (!file.isFile()) return null;
        if (file.length() > MAX_LEGACY) throw new java.io.IOException();
        try (FileInputStream input = new FileInputStream(file); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[16384]; int n;
            while ((n = input.read(buffer)) != -1) {
                if (output.size() + n > MAX_LEGACY) throw new java.io.IOException();
                output.write(buffer, 0, n);
            }
            return output.toByteArray();
        }
    }

    public void dispose() {
        channel.setMethodCallHandler(null); worker.shutdown();
        if (pendingPermission != null) {
            pendingPermission.error("activity_closed", "La pantalla se cerró durante la solicitud.", null);
            pendingPermission = null;
        }
    }
}
