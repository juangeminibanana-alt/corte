package app.creatorhub.sales;

import android.util.Log;
import app.creatorhub.CorteSalesChannel;
import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

/** Data-only messages are scope-checked before Android is allowed to display anything. */
public final class CorteMessagingService extends FirebaseMessagingService {
    @Override public void onMessageReceived(RemoteMessage message) {
        // A notification payload would bypass account checks in the background. Our sender uses DATA ONLY.
        try {
            if (message.getNotification() != null || SalesNotifications.isDispatchPaused()) return;
            SalesNotifications.show(getApplicationContext(), message.getData());
        } catch (RuntimeException error) {
            Log.w("CorteVentas", "No pudimos mostrar el aviso: " + error.getClass().getSimpleName());
        }
    }

    @Override public void onNewToken(String token) {
        try {
            if (SalesNotifications.isDispatchPaused()) return;
            SalesNotifications.rememberToken(getApplicationContext(), token);
            CorteSalesChannel.tokenChanged();
        } catch (RuntimeException error) {
            Log.w("CorteVentas", "No pudimos registrar los avisos: " + error.getClass().getSimpleName());
        }
    }
}
