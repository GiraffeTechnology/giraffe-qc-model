package com.giraffetechnology.qc.benchmark

import android.app.Activity
import android.app.ActivityManager
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.util.Log
import com.giraffetechnology.qc.qwen.*
import kotlinx.coroutines.*
import org.json.JSONObject
import java.io.File
import java.time.Instant

/**
 * §4.3.0 On-device latency benchmark activity.
 *
 * Model storage strategy (Android 16 FUSE bypass):
 *   - Model lives in filesDir (internal private storage, regular ext4, always accessible).
 *   - On first run the activity auto-imports from the first source that has llm.mnn:
 *       1. Environment.getExternalStoragePublicDirectory(DIRECTORY_DOWNLOADS)/qwen_mnn/
 *          Push via ADB: adb push <model_dir>/ /sdcard/Download/qwen_mnn/
 *       2. getExternalFilesDir(null)/import/qwen_mnn/  (fallback, always accessible)
 *          Push via ADB: adb push <model_dir>/ \
 *            /sdcard/Android/data/com.giraffetechnology.qc/files/import/qwen_mnn/
 *   - Import is a one-time file copy (~4 GB, runs in IO coroutine). Subsequent runs skip it.
 *   - Results are written to getExternalFilesDir() (adb pull) AND logcat (fallback).
 *
 * ADB launch:
 *   adb shell am start -n com.giraffetechnology.qc/.benchmark.BenchmarkActivity \
 *     --ei iterations 10 \
 *     --es model_name "Qwen3-VL-4B-Instruct-MNN" \
 *     --ez cpu_only false
 *
 * Result JSON fields include:
 *   stub_mode        — true if MNN native libs are absent (simulated inference)
 *   inference_backend — "opencl" | "vulkan" | "cpu" | "stub"
 */
class BenchmarkActivity : Activity() {

    companion object {
        private const val TAG = "QCBenchmark"
        private const val RESULTS_FILENAME = "qc_benchmark_results.json"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val iterations = intent.getIntExtra("iterations", 10)
        val modelName  = intent.getStringExtra("model_name") ?: "Qwen3-VL-4B-Instruct-MNN"
        val cpuOnly    = intent.getBooleanExtra("cpu_only", false)

        // Results go to getExternalFilesDir() so adb pull works; logcat is always the fallback.
        val outputFile = File(getExternalFilesDir(null) ?: filesDir, RESULTS_FILENAME)

        Log.i(TAG, "Benchmark start: iterations=$iterations  modelName=$modelName  cpuOnly=$cpuOnly")
        Log.i(TAG, "Results file: ${outputFile.absolutePath}")

        CoroutineScope(Dispatchers.Main).launch {
            val results = runBenchmark(iterations, modelName, cpuOnly)
            writeResults(results, outputFile)
            Log.i(TAG, "Benchmark complete")
            finish()
        }
    }

    /**
     * Resolves the model directory in filesDir, importing files from external storage
     * if not already present. The import runs on Dispatchers.IO (never on main thread).
     *
     * filesDir = /data/data/<package>/files/ — plain ext4, no FUSE, no Android 16
     * scoped-storage symlink issues with Java File.exists() or FileInputStream.
     */
    private suspend fun resolveOrImportModel(): ImportResult = withContext(Dispatchers.IO) {
        val dest = File(filesDir, "models/qwen_mnn")

        if (File(dest, "llm.mnn").exists()) {
            Log.i(TAG, "Model already in filesDir: ${dest.absolutePath}")
            return@withContext ImportResult.Ready(dest)
        }

        // Source 1: public Downloads — canonical /storage/emulated/0/Download path
        // (avoids /sdcard/ FUSE symlink; accessible on Android ≤12 with READ_EXTERNAL_STORAGE)
        // Push: adb push <dir>/ /sdcard/Download/qwen_mnn/
        val downloadsSrc = File(
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
            "qwen_mnn"
        )

        // Source 2: app-scoped external staging — always accessible, no storage permission needed
        // Push: adb push <dir>/ /sdcard/Android/data/com.giraffetechnology.qc/files/import/qwen_mnn/
        val stagingSrc = File(getExternalFilesDir(null) ?: filesDir, "import/qwen_mnn")

        val checkedPaths = mutableListOf<String>()
        for (src in listOf(downloadsSrc, stagingSrc)) {
            checkedPaths.add(src.absolutePath)
            if (File(src, "llm.mnn").exists()) {
                Log.i(TAG, "Importing model: ${src.absolutePath} → ${dest.absolutePath}")
                return@withContext importModel(src, dest)
            }
            Log.w(TAG, "llm.mnn not found at: ${src.absolutePath}")
        }
        ImportResult.NotFound(checkedPaths)
    }

    private fun importModel(src: File, dest: File): ImportResult {
        return try {
            dest.mkdirs()
            val files = src.listFiles() ?: emptyArray()
            files.forEach { f ->
                f.copyTo(File(dest, f.name), overwrite = true)
                Log.d(TAG, "Imported: ${f.name}  (${f.length() / 1_048_576} MB)")
            }
            Log.i(TAG, "Import complete: ${files.size} files → ${dest.absolutePath}")
            ImportResult.Ready(dest)
        } catch (e: Exception) {
            Log.e(TAG, "Import failed: ${e.message}")
            ImportResult.ImportFailed(src.absolutePath, e.message ?: "unknown error")
        }
    }

    sealed class ImportResult {
        data class Ready(val dir: File) : ImportResult()
        data class NotFound(val checkedPaths: List<String>) : ImportResult()
        data class ImportFailed(val srcPath: String, val reason: String) : ImportResult()
    }

    private suspend fun runBenchmark(
        iterations: Int,
        modelName: String,
        cpuOnly: Boolean = false,
    ): Map<String, Any> = withContext(Dispatchers.Default) {
        val importResult = resolveOrImportModel()

        when (importResult) {
            is ImportResult.NotFound -> return@withContext mapOf(
                "error"         to "Model not found. Push llm.mnn to one of the checked paths.",
                "model_name"    to modelName,
                "device_model"  to Build.MODEL,
                "total_ram_mb"  to totalRamMb(),
                "checked_paths" to importResult.checkedPaths,
                "push_commands" to listOf(
                    "adb push <local_model_dir>/ /sdcard/Download/qwen_mnn/",
                    "adb push <local_model_dir>/ /sdcard/Android/data/com.giraffetechnology.qc/files/import/qwen_mnn/",
                ),
            )
            is ImportResult.ImportFailed -> return@withContext mapOf(
                "error"        to "Model import failed from ${importResult.srcPath}: ${importResult.reason}",
                "model_name"   to modelName,
                "device_model" to Build.MODEL,
                "total_ram_mb" to totalRamMb(),
            )
            is ImportResult.Ready -> Unit
        }

        val modelDir      = (importResult as ImportResult.Ready).dir
        val runtimeLoader = MnnRuntimeLoader(applicationContext)

        val loadStart  = System.currentTimeMillis()
        val loaded     = runtimeLoader.loadModel(modelDir, cpuOnly)
        val loadTimeMs = System.currentTimeMillis() - loadStart

        if (!loaded) {
            return@withContext mapOf(
                "error"        to "Model failed to load from ${modelDir.absolutePath}",
                "model_name"   to modelName,
                "device_model" to Build.MODEL,
                "total_ram_mb" to totalRamMb(),
                "dir_listing"  to (modelDir.list()?.joinToString(", ") ?: "<empty>"),
            )
        }

        val inspector = MnnQwenInspector(applicationContext, runtimeLoader, modelName)
        val qcPoints  = listOf(
            QcPointInput("QC-01", "color_check",  "Color",  "Surface color match"),
            QcPointInput("QC-02", "border_check", "Border", "Border integrity"),
            QcPointInput("QC-03", "defect_check", "Defect", "No surface defects"),
        )
        val ctx      = InspectionContext("bench", "SKU-BENCH", "STD-BENCH", "INS-BENCH")
        val stdPhoto = StandardPhotoInput("STD", syntheticImagePath("std_bench"), "front")
        val capPhoto = CapturePhotoInput("CAP", syntheticImagePath("cap_bench"))

        val latencies  = mutableListOf<Long>()
        val memPeak    = mutableListOf<Long>()
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
        val p50    = if (latencies.isNotEmpty()) latencies[latencies.size / 2] else -1L
        val p95    = if (latencies.isNotEmpty())
            latencies[(latencies.size * 0.95).toInt().coerceAtMost(latencies.size - 1)]
            else -1L
        val peakMb = memPeak.maxOrNull()?.div(1_048_576) ?: 0L

        mapOf(
            "model_name"         to modelName,
            "model_dir_used"     to modelDir.absolutePath,
            "device_model"       to Build.MODEL,
            "device_soc"         to Build.HARDWARE,
            "android_version"    to Build.VERSION.RELEASE,
            "total_ram_mb"       to totalRamMb(),
            "model_load_time_ms" to loadTimeMs,
            "cpu_only"           to cpuOnly,
            "stub_mode"          to MnnRuntimeLoader.stubMode,
            "inference_backend"  to MnnRuntimeLoader.inferenceBackend,
            "iterations"         to iterations,
            "error_count"        to errorCount,
            "p50_latency_ms"     to p50,
            "p95_latency_ms"     to p95,
            "peak_memory_mb"     to peakMb,
            "budget_met_10s"     to (p95 <= 10_000L),
            "latencies_ms"       to latencies,
            "timestamp_utc"      to Instant.now().toString(),
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
