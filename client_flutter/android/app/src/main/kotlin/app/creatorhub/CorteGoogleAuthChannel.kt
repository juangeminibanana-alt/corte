package app.creatorhub

import android.annotation.SuppressLint
import android.app.Activity
import android.content.MutableContextWrapper
import android.os.CancellationSignal
import android.os.Handler
import android.os.Looper
import androidx.credentials.CredentialManager
import androidx.credentials.CredentialManagerCallback
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import androidx.credentials.GetCredentialResponse
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.credentials.exceptions.GetCredentialException
import androidx.credentials.exceptions.GetCredentialProviderConfigurationException
import androidx.credentials.exceptions.GetCredentialUnsupportedException
import androidx.credentials.exceptions.NoCredentialException
import com.google.android.libraries.identity.googleid.GetSignInWithGoogleOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import com.google.android.libraries.identity.googleid.GoogleIdTokenParsingException
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.auth.GoogleAuthProvider
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel
import java.util.concurrent.Executor

internal class CorteGoogleAuthChannel(activity: Activity, messenger: BinaryMessenger) {
    private val channel = MethodChannel(messenger, "corte/google_auth")
    private val context = MutableContextWrapper(activity)
    private val main = Handler(Looper.getMainLooper())
    private val callbacks = Executor { main.post(it) }
    private var request: MethodChannel.Result? = null
    private var selection: CancellationSignal? = null

    init {
        channel.setMethodCallHandler { call, result ->
            if (call.method == "signInWithGoogle") signIn(result)
            else result.notImplemented()
        }
    }

    // The Google Services plugin generates this resource only for provisioned builds.
    @SuppressLint("DiscouragedApi")
    private fun webClientId(): String? {
        val id = context.resources.getIdentifier("default_web_client_id", "string", context.packageName)
        return if (id == 0) null else context.getString(id).takeIf { it.isNotBlank() }
    }

    private fun signIn(result: MethodChannel.Result) {
        if (request != null || exchangingFirebaseToken) {
            result.error("google_sign_in_busy", "Ya hay un inicio de sesión en curso.", null)
            return
        }
        val activity = context.baseContext as? Activity
        val clientId = webClientId()
        if (activity == null || activity.isFinishing || activity.isDestroyed || clientId == null) {
            result.error("google_unavailable", "Acceder con Google no está disponible en esta instalación.", null)
            return
        }
        val signal = CancellationSignal()
        selection = signal
        request = result
        try {
            val option = GetSignInWithGoogleOption.Builder(clientId).build()
            val credentialRequest = GetCredentialRequest.Builder().addCredentialOption(option).build()
            CredentialManager.create(activity.applicationContext).getCredentialAsync(
                context, credentialRequest, signal, callbacks,
                object : CredentialManagerCallback<GetCredentialResponse, GetCredentialException> {
                    override fun onResult(response: GetCredentialResponse) {
                        if (selection !== signal) return
                        selection = null
                        exchange(response)
                    }

                    override fun onError(error: GetCredentialException) {
                        if (selection !== signal) return
                        selection = null
                        when (error) {
                            is GetCredentialCancellationException -> complete()
                            is NoCredentialException ->
                                fail("google_no_account", "No hay una cuenta de Google disponible en este dispositivo.")
                            is GetCredentialUnsupportedException, is GetCredentialProviderConfigurationException ->
                                fail("google_unavailable", "Actualiza los Servicios de Google Play para entrar a Corte.")
                            else -> fail()
                        }
                    }
                },
            )
        } catch (_: RuntimeException) {
            selection = null
            fail()
        }
    }

    private fun exchange(response: GetCredentialResponse) {
        val credential = response.credential
        if (credential !is CustomCredential ||
            credential.type != GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL
        ) {
            fail()
            return
        }
        val googleIdToken = try {
            GoogleIdTokenCredential.createFrom(credential.data).idToken
        } catch (_: GoogleIdTokenParsingException) {
            fail()
            return
        }
        val auth = try {
            FirebaseAuth.getInstance()
        } catch (_: IllegalStateException) {
            fail("google_unavailable", "Acceder con Google no está disponible en esta instalación.")
            return
        }
        exchangingFirebaseToken = true
        try {
            auth.signOut()
            auth.signInWithCredential(GoogleAuthProvider.getCredential(googleIdToken, null))
                .addOnCompleteListener(callbacks) { login ->
                    val user = if (login.isSuccessful && request != null) login.result?.user else null
                    if (user == null) {
                        finishExchange(auth, null)
                    } else {
                        try {
                            user.getIdToken(false).addOnCompleteListener(callbacks) { token ->
                                finishExchange(auth, if (token.isSuccessful) token.result?.token else null)
                            }
                        } catch (_: RuntimeException) {
                            finishExchange(auth, null)
                        }
                    }
                }
        } catch (_: RuntimeException) {
            finishExchange(auth, null)
        }
    }

    private fun finishExchange(auth: FirebaseAuth, idToken: String?) {
        // Firebase only supplies proof of identity. Corte persists its own device session.
        val token = try {
            auth.signOut()
            idToken
        } catch (_: RuntimeException) {
            null
        } finally {
            exchangingFirebaseToken = false
        }
        if (token.isNullOrBlank()) fail() else complete(token)
    }

    private fun takeRequest(): MethodChannel.Result? = request.also { request = null }

    private fun complete(idToken: String? = null) {
        takeRequest()?.success(idToken)
    }

    private fun fail(
        code: String = "google_sign_in_failed",
        message: String = "No se pudo verificar tu cuenta de Google. Vuelve a intentarlo.",
    ) {
        takeRequest()?.error(code, message, null)
    }

    fun dispose() {
        channel.setMethodCallHandler(null)
        val signal = selection
        selection = null
        signal?.cancel()
        context.baseContext = context.applicationContext
        complete()
    }

    private companion object {
        // All callbacks and Activity transitions run on the main thread.
        var exchangingFirebaseToken = false
    }
}
