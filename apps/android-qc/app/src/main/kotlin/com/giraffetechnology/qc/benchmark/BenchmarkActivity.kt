package com.giraffetechnology.qc.benchmark

import android.app.Activity
import android.app.ActivityManager
import android.os.Build
import android.os.Bundle
import android.util.Log
import com.giraffetechnology.qc.qwen.*
import kotlinx.coroutines.*
import org.json.JSONObject
import java.io.File
import java.time.Instant

/**
 * §4.3.0 On-device latency benchmark activity.
 *
 * Uses getExternalFilesDir() for both model loading and results — no
 * MANAGE_EXTERNAL_STORAGE permission needed on Android 10+ / Android 16
 * scoped storage. ADB can push to this path without root.
 *
 * Default model path: <external_files_dir>/models/qwen_mnn/
 * Push via ADB:
 *   adb push <local_model_dir>/ \
 *     /sdcard/Android/data/com.giraffetechnology.qc/files/models/qwen_mnn/
 *
 * Launch via ADB:
 *   adb shell am start -n com.giraffetechnology.qc/.benchmark.BenchmarkActivity \
 *     --ei iterations 10 \
 *     --es model_name "Qwen2-VL-2B-Instruct-MNN" \
 *     --ez cpu_only true
 *
 * Results written to <external_files_dir>/qc_benchmark_results.json
 * and logcat tag QCBenchmark.
 */
class BenchmarkActivity : Activity() {

    companion object {
        private const val TAG = "QCBenchmark"
        private const val RESULTS_FILENAME = "qc_benchmark_results.json"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Use app-scoped external storage — readable/writable without any
        // storage permission on Android 10+ (API 29+) incl. Android 16.
        val extDir = getExternalFilesDir(null) ?: filesDir
        val defaultModelPath = File(extDir, "models/qwen_mnn").absolutePath
        val outputFile = File(extDir, RESULTS_FILENAME)

        val modelPath  = intent.getStringExtra("model_path") ?: defaultModelPath
        val iterations = intent.getIntExtra("iterations", 10)
        val modelName  = intent.getStringExtra("model_name") ?: "Qwen2-VL-2B-Instruct-MNN"
        val cpuOnly    = intent.getBooleanExtra("cpu_only", false)

        Log.i(TAG, "Benchmark start: model=$modelPath  iterations=$iterations  modelName=$modelName  cpuOnly=$cpuOnly")
        Log.i(TAG, "Results file: ${outputFile.absolutePath}")

        CoroutineScope(Dispatchers.Main).launch {
            val results = runBenchmark(modelPath, iterations, modelName, cpuOnly)
            writeResults(results, outputFile)
            Log.i(TAG, "Benchmark complete")
            finish()
        }
    }

    private suspend fun runBenchmark(
        modelPath: String,
        iterations: Int,
        modelName: String,
        cpuOnly: Boolean = false,
    ): Map<String, Any> = withContext(Dispatchers.Default) {
        val runtimeLoader = MnnRuntimeLoader(applicationContext)

        // Cold start
        val loadStart  = System.currentTimeMillis()
        val loaded     = runtimeLoader.loadModel(File(modelPath), cpuOnly)
        val loadTimeMs = System.currentTimeMillis() - loadStart

        if (!loaded) {
            val checkedDir = File(modelPath)
            val dirListing = checkedDir.list()?.joinToString(", ") ?: "<directory missing>"
            val subdirListings = checkedDir.listFiles { f -> f.isDirectory }
                ?.joinToString("; ") { sub ->
                    "${sub.name}/[${sub.list()?.joinToString(", ") ?: "empty"}]"
                } ?: ""
            return@withContext mapOf(
                "error"              to "Model failed to load from $modelPath",
                "model_name"         to modelName,
                "device_model"       to Build.MODEL,
                "total_ram_mb"       to totalRamMb(),
                "checked_path"       to "$modelPath/llm.mnn",
                "dir_listing"        to dirListing,
                "subdir_listings"    to subdirListings,
                "note"               to "Expected llm.mnn directly in $modelPath " +
                    "or in one subdirectory. Push model with trailing slash: " +
                    "adb push <local_dir>/ $modelPath/ — see docs/DEPLOYMENT_LOCAL_QWEN.md",
            )
        }

        val inspector = MnnQwenInspector(applicationContext, runtimeLoader, modelName)
        val qcPoints = listOf(
            QcPointInput("QC-01", "color_check",  "Color",  "Surface color match"),
            QcPointInput("QC-02", "border_check", "Border", "Border integrity"),
            QcPointInput("QC-03", "defect_check", "Defect", "No surface defects"),
        )
        val ctx = InspectionContext("bench", "SKU-BENCH", "STD-BENCH", "INS-BENCH")
        val stdPhoto = StandardPhotoInput("STD", syntheticImagePath("std_bench"), "front")
        val capPhoto = CapturePhotoInput("CAP", syntheticImagePath("cap_bench"))

        val latencies = mutableListOf<Long>()
        val memPeak   = mutableListOf<Long>()
        var errorCount = 0

        repeat(iterations) { i ->
            val memBefore = usedMemBytes()
            val t0        = System.currentTimeMillis()
            try {
                inspector.inspect(listOf(stdPhoto), capPhoto, qcPoints, ctx)
            } catch (e: Exception) {
                errorCount++
                Log.w(TAG, "Iteration $i error: ${e.message}")
            }
            val elapsed  = System.currentTimeMillis() - t0
            val memAfter = usedMemBytes()
            latencies.add(elapsed)
            memPeak.add(maxOf(memBefore, memAfter))
            Log.d(TAG, "Iter $i: ${elapsed}ms  mem=${memAfter / 1_048_576}MB")
        }

        latencies.sort()
        val p50 = if (latencies.isNotEmpty()) latencies[latencies.size / 2] else -1L
        val p95 = if (latencies.isNotEmpty())
            latencies[(latencies.size * 0.95).toInt().coerceAtMost(latencies.size - 1)]
        else -1L
        val peakMb = memPeak.maxOrNull()?.div(1_048_576) ?: 0L

        mapOf(
            "model_name"          to modelName,
            "model_dir_used"      to (runtimeLoader.resolvedModelDir?.absolutePath ?: modelPath),
            "device_model"        to Build.MODEL,
            "device_soc"          to Build.HARDWARE,
            "android_version"     to Build.VERSION.RELEASE,
            "total_ram_mb"        to totalRamMb(),
            "model_load_time_ms"  to loadTimeMs,
            "cpu_only"            to cpuOnly,
            "stub_mode"           to MnnRuntimeLoader.stubMode,
            "iterations"          to iterations,
            "error_count"         to errorCount,
            "p50_latency_ms"      to p50,
            "p95_latency_ms"      to p95,
            "peak_memory_mb"      to peakMb,
            "budget_met_10s"      to (p95 <= 10_000L),
            "latencies_ms"        to latencies,
            "timestamp_utc"       to Instant.now().toString(),
        )
    }

    private fun writeResults(results: Map<String, Any>, outputFile: File) {
        val json = JSONObject(results).toString(2)
        try {
            outputFile.parentFile?.mkdirs()
            outputFile.writeText(json)
            Log.i(TAG, "Results written → ${outputFile.absolutePath}")
        } catch (e: Exception) {
            Log.w(TAG, "Write failed: ${e.message}")
        }
        // Always emit to logcat as fallback for adb pull failures
        Log.i(TAG, "BENCHMARK_RESULTS_JSON_START")
        Log.i(TAG, json)
        Log.i(TAG, "BENCHMARK_RESULTS_JSON_END")
    }

    private fun totalRamMb(): Long {
        val mi = ActivityManager.MemoryInfo()
        (getSystemService(ACTIVITY_SERVICE) as ActivityManager).getMemoryInfo(mi)
        return mi.totalMem / 1_048_576
    }

    private fun usedMemBytes(): Long =
        Runtime.getRuntime().let { it.totalMemory() - it.freeMemory() }

    private fun syntheticImagePath(name: String): String {
        val f = File(cacheDir, "$name.jpg")
        if (!f.exists()) f.writeBytes(ByteArray(1024) { (it % 256).toByte() })
        return f.absolutePath
    }
}
