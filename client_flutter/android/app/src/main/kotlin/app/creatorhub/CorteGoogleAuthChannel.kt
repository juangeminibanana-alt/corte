package app.creatorhub

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
import com.google.android.gms.common.ConnectionResult
import com.google.android.gms.common.GoogleApiAvailabilityLight
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
    private var deadline: Runnable? = null

    init {
        channel.setMethodCallHandler { call, result ->
            if (call.method == "signInWithGoogle") signIn(result)
            else result.notImplemented()
        }
    }

    private fun signIn(result: MethodChannel.Result) {
        if (request != null || exchangingFirebaseToken) {
            result.error("google_sign_in_busy", "Ya hay un inicio de sesión en curso.", null)
            return
        }
        val activity = context.baseContext as? Activity
        if (activity == null || activity.isFinishing || activity.isDestroyed) {
            result.error("google_unavailable", "Acceder con Google no está disponible en esta instalación.", null)
            return
        }
        request = result
        try {
            val availability = GoogleApiAvailabilityLight.getInstance().isGooglePlayServicesAvailable(
                activity.applicationContext,
                MIN_GOOGLE_SIGN_IN_SERVICES_VERSION,
            )
            if (availability != ConnectionResult.SUCCESS) {
                fail("google_services_unavailable", "El acceso con Google no está disponible en este dispositivo.")
                return
            }
            val clientId = activity.getString(R.string.default_web_client_id)
            if (clientId.isBlank()) {
                fail("google_unavailable", "Acceder con Google no está disponible en esta instalación.")
                return
            }
            val signal = CancellationSignal()
            selection = signal
            val timeout = Runnable {
                if (request !== result) return@Runnable
                fail("google_sign_in_timeout", "Google tardó en responder. Vuelve a intentarlo.")
            }
            deadline = timeout
            main.postDelayed(timeout, SIGN_IN_TIMEOUT_MS)
            val option = GetSignInWithGoogleOption.Builder(clientId).build()
            val credentialRequest = GetCredentialRequest.Builder().addCredentialOption(option).build()
            CredentialManager.create(activity.applicationContext).getCredentialAsync(
                context, credentialRequest, signal, callbacks,
                object : CredentialManagerCallback<GetCredentialResponse, GetCredentialException> {
                    override fun onResult(response: GetCredentialResponse) {
                        if (selection !== signal) return
                        selection = null
                        try {
                            exchange(response)
                        } catch (_: RuntimeException) {
                            // The provider response is read on the callback, after signIn's try block.
                            fail()
                        }
                    }

                    override fun onError(error: GetCredentialException) {
                        if (selection !== signal) return
                        selection = null
                        when (error) {
                            is GetCredentialCancellationException -> complete()
                            is NoCredentialException ->
                                fail("google_no_account", "No hay una cuenta de Google disponible en este dispositivo.")
                            is GetCredentialUnsupportedException, is GetCredentialProviderConfigurationException ->
                                fail("google_unavailable", "Acceder con Google no está disponible en esta instalación.")
                            else -> fail()
                        }
                    }
                },
            )
        } catch (_: RuntimeException) {
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
            auth.signInWithCredential(GoogleAuthProvider.getCredential(googleIdToken, null))
                .addOnCompleteListener(callbacks) { login ->
                    if (!login.isSuccessful) {
                        exchangingFirebaseToken = false
                        fail()
                        return@addOnCompleteListener
                    }
                    try {
                        val user = login.result?.user
                        if (request == null || user == null) {
                            finishExchange(auth, null)
                        } else {
                            user.getIdToken(false).addOnCompleteListener(callbacks) { token ->
                                val idToken = try {
                                    if (token.isSuccessful) token.result?.token else null
                                } catch (_: RuntimeException) {
                                    null
                                }
                                finishExchange(auth, idToken)
                            }
                        }
                    } catch (_: RuntimeException) {
                        finishExchange(auth, null)
                    }
                }
        } catch (_: RuntimeException) {
            exchangingFirebaseToken = false
            fail()
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

    private fun takeRequest(): MethodChannel.Result? {
        val result = request
        request = null
        deadline?.let(main::removeCallbacks)
        deadline = null
        val signal = selection
        selection = null
        try {
            signal?.cancel()
        } catch (_: RuntimeException) {
            // The request is already detached, even if the provider cannot cancel.
        }
        return result
    }

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
        context.baseContext = context.applicationContext
        complete()
    }

    private companion object {
        // Minimum checked by the AndroidX Play Services provider in credentials 1.6.0.
        const val MIN_GOOGLE_SIGN_IN_SERVICES_VERSION = 230815045
        const val SIGN_IN_TIMEOUT_MS = 90_000L

        // All callbacks and Activity transitions run on the main thread.
        var exchangingFirebaseToken = false
    }
}
