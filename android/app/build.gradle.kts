import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

// SEC-15 : signature avec la clé de Mathieu, lue depuis keystore.properties (hors dépôt)
val proprietesCle = Properties().apply {
    val f = rootProject.file("keystore.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "fr.mathieu.jarvis"
    compileSdk = 36

    defaultConfig {
        applicationId = "fr.mathieu.jarvis"
        minSdk = 29 // Android 10 : encodeur Opus de MediaRecorder
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
    }

    signingConfigs {
        if (proprietesCle.isNotEmpty()) {
            create("mathieu") {
                storeFile = file(proprietesCle.getProperty("fichier"))
                storePassword = proprietesCle.getProperty("motDePasse")
                keyAlias = proprietesCle.getProperty("alias")
                keyPassword = proprietesCle.getProperty("motDePasseCle")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (proprietesCle.isNotEmpty()) signingConfig = signingConfigs.getByName("mathieu")
        }
    }

    buildFeatures { compose = true }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2026.09.00")
    implementation(composeBom)
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.core:core-ktx:1.19.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.11.0")
    implementation("androidx.biometric:biometric:1.1.0")
    implementation("com.squareup.okhttp3:okhttp:5.5.0")
    // Mot de réveil sur le téléphone (TEL-02) : modèles openWakeWord exécutés localement
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.31.0")
}
