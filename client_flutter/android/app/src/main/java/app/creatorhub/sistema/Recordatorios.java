package app.creatorhub.sistema;

import android.Manifest;
import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import app.creatorhub.MainActivity;
import app.creatorhub.R;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * Notificaciones locales (04 §B.11; C32/C44): la interfaz calcula la lista (`calcularNotificaciones` de @/dominio) y
 * la entrega con `programarRecordatorios(json)`; aquí se REEMPLAZA todo lo programado con
 * `AlarmManager.setAndAllowWhileIdle` (inexacto: no pide SCHEDULE_EXACT_ALARM) en el canal «Recordatorios».
 * La lista vive en SharedPreferences para reprogramarla al encender el teléfono (ReceptorArranque).
 */
public final class Recordatorios {
    static final String CANAL = "recordatorios";
    static final String PREFS = "creatorhub_recordatorios";
    static final String CLAVE = "lista";
    public static final String EXTRA_RUTA = "app.creatorhub.RUTA";
    static final int TOPE = 64;
    private static final Pattern ID = Pattern.compile("[A-Za-z0-9._:-]{1,80}");
    private static final Pattern RUTA = Pattern.compile("#/[A-Za-z0-9/_.~?=&%-]{0,200}");

    private Recordatorios() { }

    /** Valida y normaliza NotificacionProgramada[]; descarta lo inválido o ya pasado. */
    static JSONArray validar(String json, long ahoraS) throws JSONException {
        JSONArray entrada = new JSONArray(json);
        JSONArray salida = new JSONArray();
        for (int i = 0; i < entrada.length() && salida.length() < TOPE; i++) {
            JSONObject n = entrada.optJSONObject(i);
            if (n == null) continue;
            String id = n.optString("id", ""), titulo = n.optString("titulo", ""), texto = n.optString("texto", "");
            String ruta = n.optString("ruta", "#/inicio");
            long at = n.optLong("at", 0);
            if (!ID.matcher(id).matches() || titulo.isEmpty() || at <= ahoraS) continue;
            if (!RUTA.matcher(ruta).matches()) ruta = "#/inicio";
            salida.put(new JSONObject().put("id", id).put("titulo", recortar(titulo, 120)).put("texto", recortar(texto, 400))
                    .put("at", at).put("ruta", ruta));
        }
        return salida;
    }

    private static String recortar(String s, int n) { return s.length() > n ? s.substring(0, n) : s; }

    private static String listaGuardada(SharedPreferences preferencias) {
        Object valor = preferencias.getAll().get(CLAVE);
        return valor instanceof String ? (String) valor : "[]";
    }

    /** Reemplaza TODO lo programado por `json` (NotificacionProgramada[]). */
    public static synchronized void programar(Context ctx, String json) throws JSONException {
        JSONArray nueva = validar(json, System.currentTimeMillis() / 1000L);
        SharedPreferences p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        cancelarTodo(ctx, listaGuardada(p));
        p.edit().putString(CLAVE, nueva.toString()).apply();
        crearCanal(ctx);
        agendar(ctx, nueva);
    }

    /** Al encender el teléfono o actualizar la app: vuelve a agendar lo que siga en el futuro. */
    static synchronized void reprogramar(Context ctx) {
        SharedPreferences p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        try {
            JSONArray vigente = validar(listaGuardada(p), System.currentTimeMillis() / 1000L);
            p.edit().putString(CLAVE, vigente.toString()).apply();
            crearCanal(ctx);
            agendar(ctx, vigente);
        } catch (JSONException e) {
            p.edit().remove(CLAVE).apply();
        }
    }

    private static void agendar(Context ctx, JSONArray lista) {
        AlarmManager am = ctx.getSystemService(AlarmManager.class);
        if (am == null) return;
        for (int i = 0; i < lista.length(); i++) {
            JSONObject n = lista.optJSONObject(i);
            if (n == null) continue;
            am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, n.optLong("at") * 1000L, intencion(ctx, n));
        }
    }

    private static void cancelarTodo(Context ctx, String anterior) {
        AlarmManager am = ctx.getSystemService(AlarmManager.class);
        if (am == null) return;
        try {
            JSONArray a = new JSONArray(anterior);
            for (int i = 0; i < a.length(); i++) {
                JSONObject n = a.optJSONObject(i);
                if (n != null) am.cancel(intencion(ctx, n));
            }
        } catch (JSONException ignorada) { /* nada que cancelar */ }
    }

    private static PendingIntent intencion(Context ctx, JSONObject n) {
        Intent i = new Intent(ctx, Alarma.class)
                .setAction("app.creatorhub.RECORDATORIO." + n.optString("id"))
                .putExtra("id", n.optString("id"))
                .putExtra("titulo", n.optString("titulo"))
                .putExtra("texto", n.optString("texto"))
                .putExtra("ruta", n.optString("ruta"));
        return PendingIntent.getBroadcast(ctx, n.optString("id").hashCode(), i,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    static void crearCanal(Context ctx) {
        NotificationManager nm = ctx.getSystemService(NotificationManager.class);
        if (nm == null || nm.getNotificationChannel(CANAL) != null) return;
        NotificationChannel c = new NotificationChannel(CANAL, ctx.getString(R.string.canal_recordatorios),
                NotificationManager.IMPORTANCE_DEFAULT);
        c.setDescription(ctx.getString(R.string.canal_recordatorios_desc));
        nm.createNotificationChannel(c);
    }

    /** 'concedido' | 'denegado' (POST_NOTIFICATIONS en API 33+; antes, si el usuario no las apagó). */
    public static String permiso(Context ctx) {
        if (Build.VERSION.SDK_INT >= 33
                && ctx.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            return "denegado";
        }
        NotificationManager nm = ctx.getSystemService(NotificationManager.class);
        return nm != null && nm.areNotificationsEnabled() ? "concedido" : "denegado";
    }

    static void mostrar(Context ctx, Intent datos) {
        if (!"concedido".equals(permiso(ctx))) return;
        crearCanal(ctx);
        String id = datos.getStringExtra("id");
        String ruta = datos.getStringExtra("ruta");
        Intent abrir = new Intent(ctx, MainActivity.class)
                .setAction("app.creatorhub.ABRIR." + id)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP)
                .putExtra(EXTRA_RUTA, ruta == null ? "#/inicio" : ruta);
        PendingIntent pi = PendingIntent.getActivity(ctx, id == null ? 0 : id.hashCode(), abrir,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        String texto = datos.getStringExtra("texto");
        Notification n = new Notification.Builder(ctx, CANAL)
                .setSmallIcon(R.drawable.ic_notificacion)
                .setContentTitle(datos.getStringExtra("titulo"))
                .setContentText(texto)
                .setStyle(new Notification.BigTextStyle().bigText(texto))
                .setColor(ctx.getColor(R.color.acento))
                .setAutoCancel(true)
                .setContentIntent(pi)
                .build();
        NotificationManager nm = ctx.getSystemService(NotificationManager.class);
        if (nm != null) nm.notify(id == null ? 0 : id.hashCode(), n);
        quitarDeLista(ctx, id);
    }

    private static synchronized void quitarDeLista(Context ctx, String id) {
        SharedPreferences p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        try {
            JSONArray a = new JSONArray(listaGuardada(p));
            JSONArray resto = new JSONArray();
            for (int i = 0; i < a.length(); i++) {
                JSONObject n = a.optJSONObject(i);
                if (n != null && !n.optString("id").equals(id)) resto.put(n);
            }
            p.edit().putString(CLAVE, resto.toString()).apply();
        } catch (JSONException e) {
            p.edit().remove(CLAVE).apply();
        }
    }

    /** "Olvidar esta PC" no borra recordatorios: son de la interfaz. Esto solo se usa al borrar todo. */
    public static synchronized void borrarTodo(Context ctx) {
        SharedPreferences p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        cancelarTodo(ctx, listaGuardada(p));
        p.edit().remove(CLAVE).apply();
    }

    /** La alarma de un recordatorio: muestra la notificación (fuera del hilo principal: toca SharedPreferences). */
    public static final class Alarma extends BroadcastReceiver {
        @Override public void onReceive(Context ctx, Intent intent) {
            if (intent == null || intent.getAction() == null || !intent.getAction().startsWith("app.creatorhub.RECORDATORIO.")) return;
            final PendingResult pendiente = goAsync();
            final Context app = ctx.getApplicationContext();
            new Thread(() -> {
                try { mostrar(app, intent); } finally { pendiente.finish(); }
            }, "corte-recordatorio").start();
        }
    }
}
