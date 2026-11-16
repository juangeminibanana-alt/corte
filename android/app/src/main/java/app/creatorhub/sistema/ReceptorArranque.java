package app.creatorhub.sistema;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * RECEIVE_BOOT_COMPLETED (04 §B.11): las alarmas se pierden al apagar; aquí se vuelven a agendar. La lista vive en
 * SharedPreferences: se lee fuera del hilo principal (goAsync + hilo propio, BUILD_SPEC §9).
 */
public final class ReceptorArranque extends BroadcastReceiver {
    @Override public void onReceive(Context ctx, Intent intent) {
        String a = intent == null ? null : intent.getAction();
        if (!Intent.ACTION_BOOT_COMPLETED.equals(a) && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(a)) return;
        final PendingResult pendiente = goAsync();
        final Context app = ctx.getApplicationContext();
        new Thread(() -> {
            try { Recordatorios.reprogramar(app); } finally { pendiente.finish(); }
        }, "corte-arranque").start();
    }
}
