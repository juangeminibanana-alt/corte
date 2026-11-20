package app.creatorhub

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ComponentName
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

/** Runs in the diagnostics process without starting a Flutter engine. */
class DiagnosticActivity : Activity() {
    private val dark get() =
        (resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES
    private val surface get() = getColor(R.color.cutgc_canvas)
    private val ink get() = getColor(R.color.cutgc_ink)
    private val muted get() = getColor(R.color.cutgc_muted)
    private val uiFont by lazy {
        runCatching { Typeface.createFromAsset(assets, "flutter_assets/assets/fonts/CUTGCWebSans.ttf") }
            .getOrDefault(Typeface.DEFAULT)
    }
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
        content.addView(ImageView(this).apply {
            setImageResource(R.drawable.cutgc_firma)
            contentDescription = getString(R.string.app_name)
            scaleType = ImageView.ScaleType.FIT_START
        }, LinearLayout.LayoutParams(dp(130), dp(24)))
        content.addView(TextView(this).apply {
            setText(R.string.diagnostics_title)
            setTextSize(32f)
            setTypeface(uiFont, Typeface.BOLD)
            setTextColor(ink)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) isAccessibilityHeading = true
        }, row(24))
        content.addView(TextView(this).apply {
            setText(R.string.diagnostics_intro)
            typeface = uiFont
            setTextSize(16f)
            setTextColor(muted)
            setLineSpacing(dp(4).toFloat(), 1f)
        }, row(8))
        content.addView(Button(this).apply {
            setText(R.string.diagnostics_light_start)
            setTypeface(uiFont, Typeface.BOLD)
            isAllCaps = false
            minHeight = dp(48)
            backgroundTintList = android.content.res.ColorStateList.valueOf(getColor(R.color.cutgc_action))
            setTextColor(getColor(R.color.cutgc_on_action))
            setOnClickListener { openLightStart() }
        }, row(16))
        copy = Button(this).apply {
            setText(R.string.diagnostics_copy)
            setTypeface(uiFont, Typeface.BOLD)
            isAllCaps = false
            minHeight = dp(48)
            isEnabled = false
            setTextColor(ink)
            backgroundTintList = null
            background = android.graphics.drawable.RippleDrawable(
                android.content.res.ColorStateList.valueOf(getColor(R.color.cutgc_line)),
                GradientDrawable().apply {
                    setColor(getColor(R.color.cutgc_surface))
                    setStroke(dp(1), getColor(R.color.cutgc_input_border))
                    cornerRadius = dp(8).toFloat()
                }, null,
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
            typeface = uiFont
            setTextSize(14f)
            setTextColor(ink)
            setLineSpacing(dp(4).toFloat(), 1f)
            setTextIsSelectable(true)
            setPadding(dp(16), dp(16), dp(16), dp(16))
            background = GradientDrawable().apply {
                setColor(getColor(R.color.cutgc_surface))
                cornerRadius = dp(12).toFloat()
                setStroke(dp(1), getColor(R.color.cutgc_line))
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
