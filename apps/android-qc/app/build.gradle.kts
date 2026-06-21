plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.giraffetechnology.qc"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.giraffetechnology.qc"
        minSdk = 26
        targetSdk = 34
        versionCode = 2
        versionName = "0.2.0-pad-local"

        buildConfigField("String",  "QWEN_MODEL_NAME",                 "\"Qwen3-VL-2B-Instruct-MNN\"")
        buildConfigField("String",  "QWEN_PROVISIONING_MODE",          "\"sideload_or_factory_preload\"")
        buildConfigField("int",     "QWEN_TIMEOUT_SECONDS",            "60")
        buildConfigField("boolean", "QWEN_CLOUD_ENABLED",              "false")
        buildConfigField("boolean", "PAD_LOCAL_ONLY",                  "true")
        buildConfigField("boolean", "ALLOW_SEND_IMAGES_TO_CLOUD_QWEN", "false")
        buildConfigField("boolean", "ALLOW_STUB_PASS",                 "false")
        buildConfigField("String",  "SKU_API_BASE_URL",                "\"http://192.168.1.10:8080\"")
    }

    flavorDimensions += "target"
    productFlavors {
        create("padLocal") {
            dimension = "target"
            versionNameSuffix = "-padLocal"
            // Factory LAN SKU API is allowed for SKU data.
            // Pad-side QC inference must remain local-only — no cloud inference.
            buildConfigField("String",  "QWEN_MODEL_NAME",                 "\"Qwen3-VL-2B-Instruct-MNN\"")
            buildConfigField("boolean", "PAD_LOCAL_ONLY",                  "true")
            buildConfigField("boolean", "QWEN_CLOUD_ENABLED",              "false")
            buildConfigField("boolean", "ALLOW_SEND_IMAGES_TO_CLOUD_QWEN", "false")
            buildConfigField("boolean", "ALLOW_STUB_PASS",                 "false")
        }
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
    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

tasks.register("verifyMnnNativeDeps") {
    group = "verification"
    description = "Checks that required MNN native libraries (.so) and headers (.hpp) are present."
    doLast {
        val jniLibsDir = file("src/main/jniLibs/arm64-v8a")
        val includeDir = file("src/main/cpp/include")
        val requiredSos = listOf("libMNN.so", "libMNN_Express.so")
        val requiredHeaders = listOf("llm/llm.hpp", "MNN/Interpreter.hpp")
        val missing = mutableListOf<String>()
        requiredSos.forEach { so ->
            if (!file("$jniLibsDir/$so").exists()) missing += "jniLibs/arm64-v8a/$so"
        }
        requiredHeaders.forEach { h ->
            if (!file("$includeDir/$h").exists()) missing += "cpp/include/$h"
        }
        if (missing.isNotEmpty()) {
            error("MNN native deps missing:\n  ${missing.joinToString("\n  ")}\n" +
                  "Run: bash scripts/download_mnn_android_libs.sh  (or --ci-stubs for CI)")
        } else {
            println("verifyMnnNativeDeps: all required MNN native artifacts present.")
        }
    }
}

tasks.register("auditNoMocksInMainSrc") {
    group = "verification"
    description = "Fails if any mock/fake class is found under src/main."
    doLast {
        val mainSrc = file("src/main/kotlin")
        val forbidden = listOf("FakeInspectors", "MockTargetDetector", "FakeMatcher", "FakeSkuRepository")
        val violations = mutableListOf<String>()
        if (mainSrc.exists()) {
            mainSrc.walkTopDown().filter { it.extension == "kt" }.forEach { f ->
                val text = f.readText()
                forbidden.forEach { name ->
                    if (text.contains(name)) violations += "${f.relativeTo(mainSrc)}: contains '$name'"
                }
            }
        }
        if (violations.isNotEmpty()) {
            error("Mock/fake contamination in src/main:\n  ${violations.joinToString("\n  ")}")
        } else {
            println("auditNoMocksInMainSrc: src/main is clean.")
        }
    }
}

dependencies {
    // No OkHttp — factory LAN SKU API uses HttpURLConnection
    // No AppCompat — uses platform Material theme (Theme.Material.Light.NoActionBar)
    implementation("androidx.activity:activity-compose:1.8.2")
    implementation(platform("androidx.compose:compose-bom:2024.02.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")

    implementation("androidx.camera:camera-core:1.3.1")
    implementation("androidx.camera:camera-camera2:1.3.1")
    implementation("androidx.camera:camera-lifecycle:1.3.1")
    implementation("androidx.camera:camera-view:1.3.1")

    implementation("androidx.room:room-runtime:2.6.1")
    implementation("androidx.room:room-ktx:2.6.1")

    implementation("androidx.work:work-runtime-ktx:2.9.0")

    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.7.3")
}
