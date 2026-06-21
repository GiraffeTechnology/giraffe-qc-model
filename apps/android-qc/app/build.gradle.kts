plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("kotlin-kapt")
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
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // Android Pad local-only — locked at build time, cannot be overridden at runtime
        buildConfigField("String",  "QWEN_MODEL_NAME",                "\"Qwen3-VL-2B-Instruct-MNN\"")
        buildConfigField("String",  "QWEN_PROVISIONING_MODE",         "\"sideload_or_factory_preload\"")
        buildConfigField("int",     "QWEN_TIMEOUT_SECONDS",           "60")
        buildConfigField("boolean", "QWEN_CLOUD_ENABLED",             "false")
        buildConfigField("boolean", "PAD_LOCAL_ONLY",                 "true")
        buildConfigField("boolean", "ALLOW_SEND_IMAGES_TO_CLOUD_QWEN","false")
        buildConfigField("boolean", "ALLOW_STUB_PASS",                "false")
        // Factory LAN SKU API endpoint — intranet only, not cloud inference
        buildConfigField("String",  "SKU_API_BASE_URL",               "\"http://192.168.1.10:8080\"")

        externalNativeBuild {
            cmake {
                cppFlags += "-std=c++17"
            }
        }
        ndk {
            abiFilters += listOf("arm64-v8a")
        }
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
        }
    }

    flavorDimensions += "target"

    productFlavors {
        create("padLocal") {
            dimension = "target"
            versionNameSuffix = "-padLocal"
            // Factory LAN SKU API is allowed for SKU data.
            // Pad-side QC inference must remain local-only and must not call cloud inference services.
            buildConfigField("String",  "QWEN_MODEL_NAME",                "\"Qwen3-VL-2B-Instruct-MNN\"")
            buildConfigField("boolean", "PAD_LOCAL_ONLY",                 "true")
            buildConfigField("boolean", "QWEN_CLOUD_ENABLED",             "false")
            buildConfigField("boolean", "ALLOW_SEND_IMAGES_TO_CLOUD_QWEN","false")
            buildConfigField("boolean", "ALLOW_STUB_PASS",                "false")
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true   // required by AGP 8.x
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
}

// Verifies required MNN native artifacts are present before compile.
// Run: ./gradlew verifyMnnNativeDeps
tasks.register("verifyMnnNativeDeps") {
    doLast {
        val required = listOf(
            "src/main/jniLibs/arm64-v8a/libMNN.so",
            "src/main/jniLibs/arm64-v8a/libMNN_Express.so",
            "../mnn_android/include/llm/llm.hpp",
            "../mnn_android/include/MNN/Interpreter.hpp",
        )
        val missing = required.filter { !file(it).exists() }
        if (missing.isNotEmpty()) {
            error(
                "MNN native dependencies missing. Run scripts/download_mnn_android_libs.sh first.\n" +
                "Missing:\n" + missing.joinToString("\n") { "  $it" }
            )
        }
        println("verifyMnnNativeDeps: all required MNN artifacts present.")
    }
}

// Audits that no Mock/Fake test helpers are present in production source.
// Run: ./gradlew auditNoMocksInMainSrc
tasks.register("auditNoMocksInMainSrc") {
    doLast {
        val forbidden = listOf("MockTargetDetector", "MockCameraFrameSource", "FakeSkuRepository", "FakeInspectors")
        val mainSrc = fileTree("src/main") { include("**/*.kt") }
        val violations = mainSrc.filter { f ->
            val text = f.readText()
            forbidden.any { text.contains(it) }
        }
        if (violations.isNotEmpty()) {
            error(
                "Mock/Fake classes found in src/main (must live under src/test only):\n" +
                violations.joinToString("\n") { "  ${it.relativeTo(projectDir)}" }
            )
        }
        println("auditNoMocksInMainSrc: no mock/fake contamination in src/main.")
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
    // Compose
    implementation(platform("androidx.compose:compose-bom:2024.02.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.activity:activity-compose:1.8.2")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.7.0")
    // Coroutines
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
    // MNN Android native libs are packaged from src/main/jniLibs/arm64-v8a/
    // Run scripts/download_mnn_android_libs.sh to populate jniLibs/ and mnn_android/include/
    // Factory LAN SKU API uses HttpURLConnection (no external HTTP library needed).
    // Factory LAN SKU API is allowed for SKU data.
    // Pad-side QC inference must remain local-only and must not call cloud inference services.
    // Testing
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.7.3")
    androidTestImplementation("androidx.test.ext:junit:1.1.5")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.1")
}
