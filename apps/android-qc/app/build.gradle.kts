import java.time.Instant
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Native MNN JNI build (src/main/cpp) is opt-in so CI's stub assemble — which
// uses empty --ci-stubs headers that cannot compile the bridge — keeps working.
// Hardware builds enable it after fetching the real AAR:
//   bash scripts/download_mnn_android_libs.sh   (sets real libMNN.so + headers)
//   ./gradlew :app:assemblePadLocalDebug -PwithMnnNative=true
val withMnnNative: Boolean =
    (project.findProperty("withMnnNative") as String?)?.toBoolean() ?: false

// ── Build provenance (P0-7) ──────────────────────────────────────────────────
// CI passes GIT_COMMIT_SHA / GIT_BRANCH / BUILD_TIMESTAMP explicitly; local
// builds fall back to `git` so every APK still carries real provenance.
fun gitOutput(vararg args: String): String? = try {
    val proc = ProcessBuilder("git", *args)
        .directory(rootProject.projectDir)
        .redirectErrorStream(true)
        .start()
    val out = proc.inputStream.bufferedReader().readText().trim()
    if (proc.waitFor() == 0 && out.isNotEmpty()) out else null
} catch (_: Exception) { null }

val gitCommitSha: String = System.getenv("GIT_COMMIT_SHA")
    ?: gitOutput("rev-parse", "HEAD") ?: "unknown"
val gitBranch: String = System.getenv("GIT_BRANCH")
    ?: gitOutput("rev-parse", "--abbrev-ref", "HEAD") ?: "unknown"
val buildTimestamp: String = System.getenv("BUILD_TIMESTAMP")
    ?: DateTimeFormatter.ISO_INSTANT.format(Instant.now().truncatedTo(ChronoUnit.SECONDS))

android {
    namespace = "com.giraffetechnology.qc"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.giraffetechnology.qc"
        minSdk = 26
        targetSdk = 34
        versionCode = 2
        versionName = "0.3.0-operator-cloud"

        buildConfigField("int",     "LEGACY_MNN_TIMEOUT_SECONDS",      "60")
        buildConfigField("String",  "SKU_API_BASE_URL",                "\"http://192.168.1.10:8080\"")
        // WS4: Jetson LAN inference is the default path. This must stay
        // false in defaultConfig -- flipping it true is the ONLY way the
        // retired on-device MNN path becomes active (PadRuntimeGraph reads
        // it via PadRuntimeConfig.legacyMnnRuntimeEnabled), and it must never
        // be true in a production-marked build by default.
        buildConfigField("boolean", "LEGACY_MNN_RUNTIME_ENABLED",      "false")
        // Architecture v2 Operator path. These are first-party, provider-neutral
        // service settings. Qwen is only the replaceable deployment default.
        buildConfigField("String",  "CLOUD_INFERENCE_BASE_URL",        "\"https://inference.invalid\"")
        buildConfigField("String",  "CLOUD_INFERENCE_DEVICE_TOKEN",    "\"\"")
        buildConfigField("String",  "CLOUD_INFERENCE_KEY_ID",          "\"\"")
        buildConfigField("String",  "CLOUD_DEFAULT_MODEL",             "\"qwen3-vl-30b-A3B\"")
        buildConfigField("int",     "CLOUD_MAX_CROP_BYTES",            "204800")
        buildConfigField("int",     "CLOUD_MAX_LONGEST_SIDE_PX",       "704")
        buildConfigField("int",     "CLOUD_JPEG_QUALITY",              "82")
        buildConfigField("int",     "CLOUD_JOB_DEADLINE_MS",           "10000")

        // Build provenance — ties any installed APK back to an exact commit.
        buildConfigField("String", "GIT_COMMIT_SHA",  "\"$gitCommitSha\"")
        buildConfigField("String", "GIT_BRANCH",      "\"$gitBranch\"")
        buildConfigField("String", "BUILD_TIMESTAMP", "\"$buildTimestamp\"")

        if (withMnnNative) {
            // Pad hardware is arm64-v8a only; MNN prebuilts ship for that ABI.
            ndk { abiFilters += "arm64-v8a" }
            externalNativeBuild {
                cmake { cppFlags += "-std=c++17" }
            }
        }
    }

    sourceSets["main"].assets.srcDir("../../../src/web/static")

    if (withMnnNative) {
        externalNativeBuild {
            cmake {
                path = file("src/main/cpp/CMakeLists.txt")
                version = "3.22.1"
            }
        }
    }

    flavorDimensions += "target"
    productFlavors {
        create("padLocal") {
            dimension = "target"
            versionNameSuffix = "-padLocal"
            // Historical flavor name retained for APK/update compatibility.
            // Operator inference is the provider-neutral first-party cloud API.
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

    // Embed the commit in every APK filename, e.g.
    // giraffe-qc-padLocal-debug-1a2b3c4d5e6f.apk
    applicationVariants.all {
        outputs.all {
            (this as? com.android.build.gradle.internal.api.BaseVariantOutputImpl)
                ?.outputFileName = "giraffe-qc-$name-${gitCommitSha.take(12)}.apk"
        }
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

tasks.register("auditNoDirectProviderSdk") {
    group = "verification"
    description = "Fails if the Pad directly embeds a third-party model-provider endpoint or SDK."
    doLast {
        val mainSrc = file("src/main")
        // Cloud inference providers and their hostnames/SDK ids. SKU-data LAN
        // HTTP is fine; these are inference/generation endpoints only.
        val forbidden = listOf(
            "dashscope", "aliyuncs", "generativelanguage", "api.openai.com",
            "openai", "anthropic", "bedrock", "vertexai", "generateContent",
            "qwen-vl-plus", "qwen-vl-max", "multimodal-generation",
        )
        val violations = mutableListOf<String>()
        if (mainSrc.exists()) {
            mainSrc.walkTopDown()
                .filter { it.isFile && (it.extension == "kt" || it.extension == "cpp" || it.extension == "java") }
                .forEach { f ->
                    val text = f.readText()
                    forbidden.forEach { needle ->
                        if (text.contains(needle, ignoreCase = true)) {
                            violations += "${f.relativeTo(mainSrc)}: references '$needle'"
                        }
                    }
                }
        }
        if (violations.isNotEmpty()) {
            error("Cloud inference reference in padLocal src/main:\n  ${violations.joinToString("\n  ")}")
        } else {
            println("auditNoDirectProviderSdk: only the first-party provider-neutral cloud contract is allowed.")
        }
    }
}

// Compatibility alias for the existing CI job name. Its v2 meaning is the
// direct-provider audit above; first-party cloud inference is intentional.
tasks.register("auditNoCloudInference") {
    group = "verification"
    description = "Compatibility alias for auditNoDirectProviderSdk."
    dependsOn("auditNoDirectProviderSdk")
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
    // Real org.json for JVM unit tests — android.jar stubs don't function for JSON ops
    testImplementation("org.json:json:20231013")
}
