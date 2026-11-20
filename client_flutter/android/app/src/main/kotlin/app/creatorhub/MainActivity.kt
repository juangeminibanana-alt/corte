package app.creatorhub

import android.content.Intent
import android.os.Bundle
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private var nativeChannel: CorteNativeChannel? = null
    private var salesChannel: CorteSalesChannel? = null
    private var googleAuthChannel: CorteGoogleAuthChannel? = null
    private var startupChannel: MethodChannel? = null
    private var recoveryMode = false

    override fun onCreate(savedInstanceState: Bundle?) {
        recoveryMode = wantsRecovery(intent) ||
            savedInstanceState?.getBoolean(StartupDiagnostics.RECOVERY_STATE, false) == true
        runCatching { intent.removeExtra(StartupDiagnostics.RECOVERY_EXTRA) }
        val event = if (recoveryMode) "recovery_create" else "create"
        StartupDiagnostics.recordLifecycle(this, event)
        super.onCreate(savedInstanceState)
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        nativeChannel = CorteNativeChannel(this, flutterEngine.dartExecutor.binaryMessenger)
        salesChannel = CorteSalesChannel(this, flutterEngine.dartExecutor.binaryMessenger, nativeChannel!!)
        googleAuthChannel = CorteGoogleAuthChannel(this, flutterEngine.dartExecutor.binaryMessenger)
        startupChannel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, StartupDiagnostics.CHANNEL_NAME)
        startupChannel?.setMethodCallHandler { call, result ->
            when (call.method) {
                "mark" -> {
                    StartupDiagnostics.recordPhase(this, call.arguments as? String)
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
    }

    override fun getDartEntrypointFunctionName(): String =
        if (recoveryMode) "corteInicioLigero" else "main"

    override fun onResume() {
        super.onResume()
        StartupDiagnostics.recordLifecycle(this, "resume")
    }

    override fun onPause() {
        StartupDiagnostics.recordLifecycle(this, "pause", isFinishing, isChangingConfigurations)
        super.onPause()
    }

    override fun onStop() {
        StartupDiagnostics.recordLifecycle(this, "stop", isFinishing, isChangingConfigurations)
        super.onStop()
    }

    override fun onUserLeaveHint() {
        StartupDiagnostics.recordLifecycle(this, "leave_hint")
        super.onUserLeaveHint()
    }

    override fun onFlutterUiDisplayed() {
        super.onFlutterUiDisplayed()
        StartupDiagnostics.recordLifecycle(this, "flutter_frame")
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putBoolean(StartupDiagnostics.RECOVERY_STATE, recoveryMode)
    }

    override fun onDestroy() {
        StartupDiagnostics.recordLifecycle(this, "destroy", isFinishing, isChangingConfigurations)
        startupChannel?.setMethodCallHandler(null)
        startupChannel = null
        googleAuthChannel?.dispose()
        googleAuthChannel = null
        salesChannel?.dispose()
        salesChannel = null
        nativeChannel?.dispose()
        nativeChannel = null
        super.onDestroy()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (!recoveryMode && wantsRecovery(intent)) {
            // A launcher may deliver the intent to the existing singleTask
            // activity. Recreate it so a new Flutter engine reads this mode.
            recreate()
            return
        }
        runCatching { intent.removeExtra(StartupDiagnostics.RECOVERY_EXTRA) }
        if (salesChannel?.notificationOpened(intent) != true) nativeChannel?.notificationOpened()
    }

    private fun wantsRecovery(intent: Intent?) =
        runCatching { intent?.getBooleanExtra(StartupDiagnostics.RECOVERY_EXTRA, false) == true }
            .getOrDefault(false)

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        nativeChannel?.permissionResult(requestCode)
    }
}
