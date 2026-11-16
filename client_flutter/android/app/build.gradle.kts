import java.security.KeyStore
import java.security.MessageDigest

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

val historicalStore = file(providers.environmentVariable("CORTE_KEYSTORE_PATH")
    .getOrElse("${System.getProperty("user.home")}/.android/debug.keystore"))
val historicalPassword = providers.environmentVariable("CORTE_KEYSTORE_PASSWORD").getOrElse("android")
val historicalAlias = providers.environmentVariable("CORTE_KEY_ALIAS").getOrElse("androiddebugkey")
val historicalKeyPassword = providers.environmentVariable("CORTE_KEY_PASSWORD").getOrElse("android")

android {
    namespace = "app.creatorhub"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "app.creatorhub"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = 26
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        create("historical") {
            storeFile = historicalStore
            storePassword = historicalPassword
            keyAlias = historicalAlias
            keyPassword = historicalKeyPassword
        }
    }
    buildTypes {
        debug {
            applicationIdSuffix = ".dev"
            versionNameSuffix = "-dev"
        }
        release {
            signingConfig = signingConfigs.getByName("historical")
        }
    }
}

// An update must keep the installed certificate. CI builds only the isolated .dev variant.
gradle.taskGraph.whenReady {
    if (allTasks.any { it.name.contains("Release", ignoreCase = true) }) {
        check(historicalStore.isFile) { "Restore the historical Corte keystore before building an update." }
        val expected = rootProject.projectDir.resolve("../../android/firma_esperada.txt")
        check(expected.isFile) { "Missing reviewed historical certificate fingerprint." }
        val store = KeyStore.getInstance(historicalStore, historicalPassword.toCharArray())
        val certificate = store.getCertificate(historicalAlias)
        check(certificate != null) { "Missing historical signing alias." }
        val fingerprint = MessageDigest.getInstance("SHA-256").digest(certificate.encoded)
            .joinToString("") { "%02x".format(it.toInt() and 0xff) }
        check(fingerprint.equals(expected.readText().trim(), ignoreCase = true)) {
            "Signing certificate differs from the installed Corte app. No replacement APK will be built."
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}

tasks.withType<JavaCompile>().configureEach {
    options.encoding = "UTF-8"
}
