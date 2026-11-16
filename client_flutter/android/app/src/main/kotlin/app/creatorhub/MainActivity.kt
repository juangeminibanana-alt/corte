package app.creatorhub

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import android.content.Intent

class MainActivity : FlutterActivity() {
    private var nativeChannel: CorteNativeChannel? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        nativeChannel = CorteNativeChannel(this, flutterEngine.dartExecutor.binaryMessenger)
    }

    override fun onDestroy() {
        nativeChannel?.dispose()
        nativeChannel = null
        super.onDestroy()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        nativeChannel?.notificationOpened()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        nativeChannel?.permissionResult(requestCode)
    }
}
