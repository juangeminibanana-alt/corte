package app.creatorhub

import android.app.ActivityManager
import android.app.ApplicationExitInfo
import android.content.Context
import android.os.Build
import android.os.Process
import android.util.AtomicFile
import java.io.File
import java.io.FileOutputStream
import java.text.DateFormat
import java.util.ArrayDeque
import java.util.Date
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

internal object StartupDiagnostics {
    const val CHANNEL_NAME = "corte/startup"
    const val RECOVERY_EXTRA = "app.creatorhub.extra.INICIO_LIGERO"
    const val RECOVERY_STATE = "cutgc_recovery_mode"

    private const val MAX_EVENTS = 20
    private const val MAX_FILE_BYTES = 4096
    private const val FILE_NAME = "cutgc-startup-v1.txt"
    private val worker = Executors.newSingleThreadScheduledExecutor()
    private val pending = ArrayDeque<Event>()
    private var writeScheduled = false

    private val phases = mapOf(
        "dart_ready" to "Inicio de Flutter",
        "dart_recovery_ready" to "Flutter recibió Inicio ligero",
        "local_directory_open" to "Abriendo la carpeta local de CUTGC",
        "local_directory_ready" to "Carpeta local de CUTGC lista",
        "auth_restoring" to "Restaurando sesión",
        "auth_ready" to "Sesión lista",
        "home_open" to "Abriendo Inicio",
        "home_loading" to "Solicitando datos de Inicio",
        "home_session_loaded" to "Se recibió el estado de la sesión",
        "home_dashboard_loaded" to "Se recibieron los resultados",
        "home_samples_loaded" to "Se recibieron las muestras",
        "home_session_error" to "Error al consultar la sesión",
        "home_dashboard_error" to "Error al consultar resultados",
        "home_samples_error" to "Error al consultar muestras",
        "home_ready" to "Inicio listo",
        "dart_frame_error" to "Error al mostrar la pantalla",
        "dart_uncaught_error" to "Error de Flutter",
        "root_back" to "Flutter recibió Atrás, sin navegación previa",
        "recovery_home" to "Inicio ligero abierto",
    )
    private val lifecycle = mapOf(
        "create" to "Se abrió la actividad",
        "recovery_create" to "Arrancó la actividad en modo ligero",
        "resume" to "La actividad entró en primer plano",
        "pause" to "La actividad dejó de estar activa",
        "stop" to "La actividad dejó de ser visible",
        "destroy" to "Android destruyó la actividad",
        "leave_hint" to "Android avisó de una salida de la actividad",
        "flutter_frame" to "Se mostró un cuadro de Flutter",
    )

    fun recordPhase(context: Context, phase: String?) {
        if (phase != null && phase in phases) record(context, phase, -1)
    }

    fun recordLifecycle(
        context: Context,
        event: String,
        finishing: Boolean? = null,
        changingConfiguration: Boolean = false,
    ) {
        if (event !in lifecycle) return
        val flags = if (finishing == null) -1 else
            (if (finishing) 1 else 0) or (if (changingConfiguration) 2 else 0)
        record(context, event, flags)
    }

    fun loadReport(context: Context, result: (String) -> Unit) {
        val app = context.applicationContext
        worker.execute { result(report(app)) }
    }

    private fun record(context: Context, name: String, flags: Int) {
        val event = Event(System.currentTimeMillis(), Process.myPid(), name, flags)
        synchronized(pending) {
            if (pending.size == MAX_EVENTS) pending.removeFirst()
            pending.addLast(event)
            if (writeScheduled) return
            writeScheduled = true
        }
        val app = context.applicationContext
        worker.schedule({ flush(app) }, 20L, TimeUnit.MILLISECONDS)
    }

    private fun flush(context: Context) {
        val batch = synchronized(pending) {
            pending.toList().also {
                pending.clear()
                writeScheduled = false
            }
        }
        val file = AtomicFile(file(context))
        var stream: FileOutputStream? = null
        try {
            val events = (readEvents(context) + batch).takeLast(MAX_EVENTS)
            stream = file.startWrite()
            stream.write(events.joinToString("\n") { it.encode() }.toByteArray(Charsets.UTF_8))
            file.finishWrite(stream)
        } catch (_: Exception) {
            if (stream != null) runCatching { file.failWrite(stream) }
        }
    }

    private fun file(context: Context) = File(context.noBackupFilesDir, FILE_NAME)

    private fun readEvents(context: Context): List<Event> = try {
        val source = file(context)
        // Only MainActivity writes. The diagnostics process reads the last complete
        // base file so it never interferes with AtomicFile's in-progress write.
        if (source.length() in 1L..MAX_FILE_BYTES.toLong()) {
            source.useLines { lines -> lines.take(MAX_EVENTS).mapNotNull(::decodeEvent).toList() }
        } else emptyList()
    } catch (_: Exception) {
        emptyList()
    }

    private fun report(context: Context): String = buildString {
        val device = clean("${Build.MANUFACTURER} ${Build.MODEL}")
        val androidVersion = clean(Build.VERSION.RELEASE)
        val date = DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.MEDIUM)
        val app = runCatching { packageDetails(context) }.getOrNull()
        appendLine("CUTGC ${app?.version ?: "—"}")
        appendLine("$device · Android $androidVersion (API ${Build.VERSION.SDK_INT})")
        if (app != null) appendLine("Actualización instalada ${date.format(Date(app.updatedAt))}")
        appendLine()
        appendLine("Salidas del proceso registradas por Android")
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            appendLine("Este registro está disponible a partir de Android 11.")
        } else {
            val exits = runCatching { recordedExits(context) }.getOrNull()
            when {
                exits == null -> appendLine("No se pudo consultar el registro de Android.")
                exits.isEmpty() -> appendLine("Android no muestra una salida reciente de CUTGC.")
                else -> exits.forEach { exit ->
                    appendLine("${date.format(Date(exit.time))} · ${exit.reason} (motivo ${exit.code}, estado ${exit.status}, proceso ${exit.pid})")
                    for (frame in exit.nativeFrames) {
                        val index = frame.index.toString().padStart(2, '0')
                        val library = frame.library ?: "Módulo no identificado"
                        append("  #$index $library + 0x${frame.relativePc.toString(16)}")
                        if (frame.fileMapOffset != 0uL) {
                            append(" · offset de archivo 0x${frame.fileMapOffset.toString(16)}")
                        }
                        if (frame.buildId != null) append(" · ELF ${frame.buildId}")
                        appendLine()
                    }
                }
            }
        }
        appendLine()
        appendLine("Actividad reciente de CUTGC")
        val events = readEvents(context)
        if (events.isEmpty()) appendLine("Aún no hay eventos de apertura registrados.")
        for (event in events) {
            val label = lifecycle[event.name] ?: phases[event.name] ?: continue
            append("${date.format(Date(event.time))} · $label (proceso ${event.pid}")
            if (event.flags >= 0) {
                val finishing = if ((event.flags and 1) != 0) "sí" else "no"
                val configuration = if ((event.flags and 2) != 0) "sí" else "no"
                append(", finalizando: $finishing, cambio de configuración: $configuration")
            }
            appendLine(")")
        }
    }.trimEnd()

    @Suppress("DEPRECATION")
    private fun packageDetails(context: Context): AppDetails {
        val info = context.packageManager.getPackageInfo(context.packageName, 0)
        val build = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) info.longVersionCode else info.versionCode.toLong()
        return AppDetails("${clean(info.versionName ?: "—")} ($build)", info.lastUpdateTime)
    }

    private fun recordedExits(context: Context): List<Exit> {
        val manager = context.getSystemService(ActivityManager::class.java) ?: return emptyList()
        val packageName = context.packageName
        return manager.getHistoricalProcessExitReasons(packageName, 0, 32).asSequence()
            .filter { it.processName == packageName }
            .sortedByDescending { it.timestamp }
            .take(2)
            .map {
                Exit(it.timestamp, it.pid, it.reason, it.status, exitReason(it.reason), nativeFrames(it))
            }
            .toList()
    }

    private fun nativeFrames(exit: ApplicationExitInfo): List<NativeExitTrace.Frame> {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S ||
            exit.reason != ApplicationExitInfo.REASON_CRASH_NATIVE
        ) return emptyList()
        return runCatching {
            exit.traceInputStream?.use { NativeExitTrace.read(it, exit.pid) }
        }.getOrNull().orEmpty()
    }

    private fun exitReason(reason: Int): String = when (reason) {
        ApplicationExitInfo.REASON_UNKNOWN -> "Motivo desconocido"
        ApplicationExitInfo.REASON_EXIT_SELF -> "Salida del proceso"
        ApplicationExitInfo.REASON_SIGNALED -> "Señal del sistema"
        ApplicationExitInfo.REASON_LOW_MEMORY -> "Memoria insuficiente"
        ApplicationExitInfo.REASON_CRASH -> "Error interno"
        ApplicationExitInfo.REASON_CRASH_NATIVE -> "Error nativo"
        ApplicationExitInfo.REASON_ANR -> "La aplicación dejó de responder"
        ApplicationExitInfo.REASON_INITIALIZATION_FAILURE -> "Fallo al iniciar"
        ApplicationExitInfo.REASON_PERMISSION_CHANGE -> "Cambio de permiso"
        ApplicationExitInfo.REASON_EXCESSIVE_RESOURCE_USAGE -> "Límite de recursos"
        ApplicationExitInfo.REASON_USER_REQUESTED -> "Android informó una salida solicitada"
        ApplicationExitInfo.REASON_USER_STOPPED -> "Android informó una detención"
        ApplicationExitInfo.REASON_DEPENDENCY_DIED -> "Terminó un proceso dependiente"
        ApplicationExitInfo.REASON_FREEZER -> "Android congeló el proceso"
        ApplicationExitInfo.REASON_PACKAGE_STATE_CHANGE -> "Cambio del estado de la aplicación"
        ApplicationExitInfo.REASON_PACKAGE_UPDATED -> "Actualización de CUTGC"
        else -> "Otro motivo de Android"
    }

    private fun decodeEvent(line: String): Event? {
        val (time, pid, name, flags) = line.split('\t').takeIf { it.size == 4 } ?: return null
        if (name !in lifecycle && name !in phases) return null
        return Event(
            time.toLongOrNull()?.takeIf { it > 0L } ?: return null,
            pid.toIntOrNull()?.takeIf { it > 0 } ?: return null,
            name,
            flags.toIntOrNull()?.takeIf { it in -1..3 } ?: return null,
        )
    }

    private fun clean(value: String): String =
        value.filterNot { it.isISOControl() }.trim().take(80)

    private data class Event(val time: Long, val pid: Int, val name: String, val flags: Int) {
        fun encode() = "$time\t$pid\t$name\t$flags"
    }

    private data class Exit(
        val time: Long,
        val pid: Int,
        val code: Int,
        val status: Int,
        val reason: String,
        val nativeFrames: List<NativeExitTrace.Frame>,
    )
    private data class AppDetails(val version: String, val updatedAt: Long)
}
