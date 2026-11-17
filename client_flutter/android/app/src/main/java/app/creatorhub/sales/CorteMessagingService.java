package app.creatorhub.sales;

import app.creatorhub.CorteSalesChannel;
import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

/** Data-only messages are scope-checked before Android is allowed to display anything. */
public final class CorteMessagingService extends FirebaseMessagingService {
    @Override public void onMessageReceived(RemoteMessage message) {
        // A notification payload would bypass account checks in the background. Our sender uses DATA ONLY.
        if (message.getNotification() != null) return;
        SalesNotifications.show(getApplicationContext(), message.getData());
    }

    @Override public void onNewToken(String token) {
        SalesNotifications.rememberToken(getApplicationContext(), token);
        CorteSalesChannel.tokenChanged();
    }
}
