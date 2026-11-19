package app.creatorhub

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ComponentName
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

/** Runs in the diagnostics process without starting a Flutter engine. */
class DiagnosticActivity : Activity() {
    private val dark get() =
        (resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES
    private val surface get() = if (dark) 0xFF111216.toInt() else Color.WHITE
    private val panel get() = if (dark) 0xFF1B1C23.toInt() else 0xFFF6F6F8.toInt()
    private val line get() = if (dark) 0xFF3A3C48.toInt() else 0xFFE9E9EE.toInt()
    private val ink get() = if (dark) 0xFFF7F7FA.toInt() else 0xFF161823.toInt()
    private val muted get() = if (dark) 0xFFC8C9D2.toInt() else 0xFF62636F.toInt()
    private lateinit var details: TextView
    private lateinit var copy: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val scroll = ScrollView(this).apply {
            isFillViewport = true
            setBackgroundColor(surface)
        }
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(24), dp(24), dp(24))
        }
        scroll.addView(content)
        content.addView(TextView(this).apply {
            setText(R.string.diagnostics_title)
            setTextSize(30f)
            setTypeface(Typeface.DEFAULT, Typeface.BOLD)
            setTextColor(ink)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) isAccessibilityHeading = true
        }, row())
        content.addView(TextView(this).apply {
            setText(R.string.diagnostics_intro)
            setTextSize(16f)
            setTextColor(muted)
            setLineSpacing(dp(4).toFloat(), 1f)
        }, row(8))
        content.addView(Button(this).apply {
            setText(R.string.diagnostics_light_start)
            isAllCaps = false
            minHeight = dp(48)
            backgroundTintList = android.content.res.ColorStateList.valueOf(0xFFE31C48.toInt())
            setTextColor(Color.WHITE)
            setOnClickListener { openLightStart() }
        }, row(16))
        copy = Button(this).apply {
            setText(R.string.diagnostics_copy)
            isAllCaps = false
            minHeight = dp(48)
            isEnabled = false
            setTextColor(ink)
            backgroundTintList = android.content.res.ColorStateList.valueOf(
                if (dark) 0xFF2B2C34.toInt() else 0xFFEDEDF1.toInt(),
            )
            setOnClickListener {
                val clipboard = getSystemService(ClipboardManager::class.java) ?: return@setOnClickListener
                clipboard.setPrimaryClip(ClipData.newPlainText(getString(R.string.diagnostics_title), details.text))
                if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
                    Toast.makeText(this@DiagnosticActivity, R.string.diagnostics_copy_done, Toast.LENGTH_SHORT).show()
                }
            }
        }
        content.addView(copy, row(4))
        details = TextView(this).apply {
            setText(R.string.diagnostics_reading)
            setTextSize(14f)
            setTextColor(ink)
            setLineSpacing(dp(4).toFloat(), 1f)
            setTextIsSelectable(true)
            setPadding(dp(16), dp(16), dp(16), dp(16))
            background = GradientDrawable().apply {
                setColor(panel)
                cornerRadius = dp(8).toFloat()
                setStroke(dp(1), line)
            }
        }
        content.addView(details, row(16))
        setContentView(scroll)
        fitSystemBars(scroll)
    }

    override fun onResume() {
        super.onResume()
        StartupDiagnostics.loadReport(this) { text ->
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                details.text = text
                copy.isEnabled = true
            }
        }
    }

    private fun openLightStart() {
        val restart = Intent.makeRestartActivityTask(ComponentName(this, MainActivity::class.java))
            .putExtra(StartupDiagnostics.RECOVERY_EXTRA, true)
        try {
            startActivity(restart)
        } catch (_: RuntimeException) {
            Toast.makeText(this, R.string.diagnostics_open_failed, Toast.LENGTH_LONG).show()
        }
    }

    @Suppress("DEPRECATION")
    private fun fitSystemBars(content: View) {
        window.statusBarColor = surface
        window.navigationBarColor = surface
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.setDecorFitsSystemWindows(false)
            val bars = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or
                WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS
            window.insetsController?.setSystemBarsAppearance(if (dark) 0 else bars, bars)
            content.setOnApplyWindowInsetsListener { view, insets ->
                val safe = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                view.setPadding(safe.left, safe.top, safe.right, safe.bottom)
                insets
            }
            content.requestApplyInsets()
        } else if (!dark) {
            window.decorView.systemUiVisibility =
                View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
        }
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density + 0.5f).toInt()

    private fun row(spaceAbove: Int = 0) = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.MATCH_PARENT,
        LinearLayout.LayoutParams.WRAP_CONTENT,
    ).apply { topMargin = dp(spaceAbove) }
}
