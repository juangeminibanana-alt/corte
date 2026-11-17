package app.creatorhub

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import android.content.Intent

class MainActivity : FlutterActivity() {
    private var nativeChannel: CorteNativeChannel? = null
    private var salesChannel: CorteSalesChannel? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        nativeChannel = CorteNativeChannel(this, flutterEngine.dartExecutor.binaryMessenger)
        salesChannel = CorteSalesChannel(this, flutterEngine.dartExecutor.binaryMessenger, nativeChannel!!)
    }

    override fun onDestroy() {
        salesChannel?.dispose()
        salesChannel = null
        nativeChannel?.dispose()
        nativeChannel = null
        super.onDestroy()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (salesChannel?.notificationOpened(intent) != true) nativeChannel?.notificationOpened()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        nativeChannel?.permissionResult(requestCode)
    }
}
