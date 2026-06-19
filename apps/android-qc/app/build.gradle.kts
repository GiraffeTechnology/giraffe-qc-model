@file:Suppress("HttpUrlsUsage")
import java.net.URL

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("kotlin-kapt")
}

// ─── MNN Android AAR — auto-download ─────────────────────────────────────────
// The MNN Android AAR (>100 MB) is not committed to the repo. Instead it is
// fetched from GitHub releases on first build. Update mnnVersion to the release
// tag you want; verify the asset name at https://github.com/alibaba/MNN/releases.
val mnnVersion = "2.9.6"
val mnnAarFile = File("${projectDir}/libs/MNN-android.aar")

tasks.register("downloadMnnAar") {
    description = "Download MNN Android AAR from GitHub releases if not already present."
    group       = "setup"
    outputs.file(mnnAarFile)
    onlyIf { !mnnAarFile.exists() }
    doLast {
        mnnAarFile.parentFile.mkdirs()
        val url = "https://github.com/alibaba/MNN/releases/download/$mnnVersion/MNN-android-$mnnVersion.aar"
        println("Downloading MNN $mnnVersion …\n  $url")
        runCatching {
            URL(url).openStream().use { input ->
                mnnAarFile.outputStream().use { output -> input.copyTo(output) }
            }
        }.onSuccess {
            println("MNN AAR saved: ${mnnAarFile.absolutePath}  (${mnnAarFile.length() / 1_048_576} MB)")
        }.onFailure { err: Throwable ->
            mnnAarFile.delete()
            // Non-blocking: warn but do not fail the build. Without the AAR, MnnRuntimeLoader
            // enters stub mode and MnnQwenInspector returns review_required (never pass).
            // To enable real inference, manually place the AAR at ${mnnAarFile.absolutePath}
            // or update mnnVersion to a real release asset at https://github.com/alibaba/MNN/releases
            println(
                "WARNING: MNN AAR download failed — building without it (stub mode).\n" +
                "  URL:   $url\n" +
                "  Cause: ${err.message}\n" +
                "  Stub mode: MnnQwenInspector returns review_required until AAR is present.\n" +
                "  Fix: manually place MNN-android.aar at ${mnnAarFile.absolutePath}"
            )
        }
    }
}

// Ensure the AAR is present before Android's preBuild (which triggers all compilation)
tasks.whenTaskAdded {
    if (name == "preBuild") dependsOn("downloadMnnAar")
}
// ─────────────────────────────────────────────────────────────────────────────

android {
    namespace = "com.giraffetechnology.qc"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.giraffetechnology.qc"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // On-device model config exposed via BuildConfig
        buildConfigField("String", "QWEN_MODEL_NAME", "\"Qwen3-VL-4B-Instruct-MNN\"")
        buildConfigField("String", "QWEN_PROVISIONING_MODE", "\"download_on_first_run\"")
        buildConfigField("int", "QWEN_TIMEOUT_SECONDS", "10")
        buildConfigField("boolean", "QWEN_CLOUD_ENABLED", "false")
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.8"
    }
    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    // CameraX
    implementation("androidx.camera:camera-camera2:1.3.1")
    implementation("androidx.camera:camera-lifecycle:1.3.1")
    implementation("androidx.camera:camera-view:1.3.1")
    // Room
    implementation("androidx.room:room-runtime:2.6.1")
    implementation("androidx.room:room-ktx:2.6.1")
    kapt("androidx.room:room-compiler:2.6.1")
    // WorkManager
    implementation("androidx.work:work-runtime-ktx:2.9.0")
    // Network
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    // Compose
    implementation(platform("androidx.compose:compose-bom:2024.02.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.activity:activity-compose:1.8.2")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.7.0")
    // Coroutines
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
    // MNN Android AAR — fetched automatically by :app:downloadMnnAar before preBuild.
    // Bundles libMNN.so, libMNN_Express.so, libMNN_CL.so (OpenCL), libMNN_Vulkan.so.
    // The AAR is git-ignored in app/libs/ (binary, >100 MB).
    implementation(fileTree("libs") { include("*.aar") })
    // Testing
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.7.3")
    androidTestImplementation("androidx.test.ext:junit:1.1.5")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.1")
}
