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
        buildConfigField("String",  "QWEN_MODEL_NAME",                "\"Qwen3-VL-4B-Instruct-MNN\"")
        buildConfigField("String",  "QWEN_PROVISIONING_MODE",         "\"sideload_or_factory_preload\"")
        buildConfigField("int",     "QWEN_TIMEOUT_SECONDS",           "60")
        buildConfigField("boolean", "QWEN_CLOUD_ENABLED",             "false")
        buildConfigField("boolean", "PAD_LOCAL_ONLY",                 "true")
        buildConfigField("boolean", "ALLOW_SEND_IMAGES_TO_CLOUD_QWEN","false")
        buildConfigField("boolean", "ALLOW_STUB_PASS",                "false")
        // Factory backend SKU API base URL — override per deployment network (no cloud endpoint)
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
            // Restated explicitly so no other flavor can accidentally enable cloud
            buildConfigField("String",  "QWEN_MODEL_NAME",                "\"Qwen3-VL-4B-Instruct-MNN\"")
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
    // OkHttp is NOT included: Pad local-only app must not make network calls
    // Testing
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.7.3")
    androidTestImplementation("androidx.test.ext:junit:1.1.5")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.1")
}

// ── Preflight: verify MNN native binaries before any build ──────────────────
tasks.register("verifyMnnNativeDeps") {
    group = "verification"
    description = "Fails fast when MNN .so / header files are missing from the checkout"
    doLast {
        val missingFiles = listOf(
            "src/main/jniLibs/arm64-v8a/libMNN.so",
            "src/main/jniLibs/arm64-v8a/libMNN_Express.so",
            "../../mnn_android/include/llm/llm.hpp",
            "../../mnn_android/include/MNN/Interpreter.hpp",
        ).filterNot { project.file(it).exists() }
        if (missingFiles.isNotEmpty()) {
            error("""
                MNN native dependency check FAILED. Missing:
                ${missingFiles.joinToString("\n") { "  $it" }}
                
                Run:  bash scripts/download_mnn_android_libs.sh
                Then: cd apps/android-qc && ./gradlew :app:assemblePadLocalDebug
            """.trimIndent())
        }
    }
}

// ── Audit guard: no mock/fake class names in src/main ─────────────────────────
tasks.register("auditNoMocksInMainSrc") {
    group = "verification"
    description = "Fails if test-only mock/fake class names appear in src/main"
    doLast {
        val forbidden = listOf(
            "MockTargetDetector", "MockCameraFrameSource",
            "FakeSkuRepository", "FakeInspectors",
        )
        val violations = project.file("src/main").walkTopDown()
            .filter { it.isFile && it.name.endsWith(".kt") }
            .flatMap { file ->
                val text = file.readText()
                forbidden.filter { name -> name in text }
                    .map { name -> "${file.relativeTo(project.projectDir)}: '$name'" }
            }
            .toList()
        if (violations.isNotEmpty()) {
            error("Production source-set contamination:\n${violations.joinToString("\n")}")
        }
    }
}

afterEvaluate {
    tasks.matching { it.name == "preBuild" }.configureEach { dependsOn("verifyMnnNativeDeps") }
    tasks.matching { it.name.endsWith("UnitTest") }.configureEach { dependsOn("auditNoMocksInMainSrc") }
}
