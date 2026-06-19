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
 * §4.3.0 On-device latency benchmark activity — Android Pad local-only build.
 *
 * Target model: Qwen3-VL-4B-Instruct-MNN (INT4), via MNN local runtime.
 * Target device: Snapdragon 8 Gen, 8 GB RAM.
 * No cloud inference path. All results are local-only.
 * If native MNN is not wired, inspector returns review_required — never pass.
 *
 * Launch via ADB:
 *   adb shell am start -n com.giraffetechnology.qc/.benchmark.BenchmarkActivity \
 *     --es model_path /sdcard/qwen3_vl_4b_mnn \
 *     --ei iterations 10 \
 *     --es model_name "Qwen3-VL-4B-Instruct-MNN"
 *
 * Results written to /sdcard/qc_benchmark_results.json and logcat tag QCBenchmark.
 * See docs/PAD_LOCAL_MNN_DEPLOYMENT.md for model provisioning instructions.
 */
class BenchmarkActivity : Activity() {

    companion object {
        private const val TAG = "QCBenchmark"
        private const val OUTPUT_FILE = "/sdcard/qc_benchmark_results.json"
        private const val MODE = "android_pad_local_only"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val modelPath  = intent.getStringExtra("model_path") ?: "/sdcard/qwen3_vl_4b_mnn"
        val iterations = intent.getIntExtra("iterations", 10)
        val modelName  = intent.getStringExtra("model_name") ?: "Qwen3-VL-4B-Instruct-MNN"

        Log.i(TAG, "Benchmark start: model=$modelPath, iterations=$iterations")
        Log.i(TAG, "Mode: $MODE — local inference only, no external services")

        CoroutineScope(Dispatchers.Main).launch {
            val results = runBenchmark(modelPath, iterations, modelName)
            writeResults(results)
            Log.i(TAG, "Benchmark complete")
            finish()
        }
    }

    private suspend fun runBenchmark(
        modelPath: String,
        iterations: Int,
        modelName: String,
    ): Map<String, Any> = withContext(Dispatchers.Default) {
        val runtimeLoader = MnnRuntimeLoader(applicationContext)

        // Cold start
        val loadStart  = System.currentTimeMillis()
        val loaded     = runtimeLoader.loadModel(File(modelPath))
        val loadTimeMs = System.currentTimeMillis() - loadStart

        if (!loaded) {
            Log.w(TAG, "MNN runtime not wired or model missing at $modelPath — result: review_required")
            return@withContext mapOf(
                "model_name"                 to modelName,
                "mode"                       to MODE,
                "cloud_fallback"             to false,
                "qwen_api_used"              to false,
                "dashscope_used"             to false,
                "native_inference_not_wired" to true,
                "inspection_result"          to "review_required",
                "error"                      to "Model failed to load from $modelPath",
                "device_model"               to Build.MODEL,
                "total_ram_mb"               to totalRamMb(),
                "note"                       to "Ensure model is provisioned per docs/PAD_LOCAL_MNN_DEPLOYMENT.md",
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
            "mode"                to MODE,
            "cloud_fallback"      to false,
            "qwen_api_used"       to false,
            "dashscope_used"      to false,
            "device_model"        to Build.MODEL,
            "device_soc"          to Build.HARDWARE,
            "android_version"     to Build.VERSION.RELEASE,
            "total_ram_mb"        to totalRamMb(),
            "model_load_time_ms"  to loadTimeMs,
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

    private fun writeResults(results: Map<String, Any>) {
        val json = JSONObject(results).toString(2)
        try {
            File(OUTPUT_FILE).writeText(json)
            Log.i(TAG, "Results → $OUTPUT_FILE")
        } catch (e: Exception) {
            Log.w(TAG, "Write failed: ${e.message}")
        }
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
