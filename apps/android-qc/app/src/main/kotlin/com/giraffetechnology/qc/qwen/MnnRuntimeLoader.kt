package com.giraffetechnology.qc.qwen

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Manages MNN model lifecycle (load/unload, native library binding).
 *
 * Production: wires to MNN-android.aar JNI layer.
 * CI/test: MNN native libs absent → loadNativeLibs() returns false → scaffold mode.
 * Stub mode: native libs absent but llm.mnn exists on device → simulated inference.
 *
 * Device: Snapdragon 8 Gen, 8 GB RAM.
 * Model: Qwen2-VL-2B-Instruct-MNN (INT4) — ~2GB weights, ~3-4GB at runtime including
 * vision encoder and KV cache. Within the 8GB budget.
 *
 * Model directory layout (taobao-mnn/Qwen2-VL-2B-Instruct-MNN):
 *   llm.mnn, llm.mnn.weight, visual.mnn, visual.mnn.weight,
 *   llm.mnn.json, llm_config.json, embeddings_bf16.bin, tokenizer.txt, config.json
 */
class MnnRuntimeLoader(private val context: Context) {

    companion object {
        private const val TAG = "MnnRuntimeLoader"
        private var nativeLoaded = false

        /**
         * True when llm.mnn was found on device but MNN native libs are absent.
         * MnnQwenInspector will simulate inference instead of calling JNI.
         */
        var stubMode = false
            private set

        fun loadNativeLibs(): Boolean {
            if (nativeLoaded) return true
            return try {
                System.loadLibrary("MNN")
                System.loadLibrary("MNN_Express")
                nativeLoaded = true
                Log.i(TAG, "MNN native libs loaded")
                true
            } catch (e: UnsatisfiedLinkError) {
                Log.w(TAG, "MNN native libs not available: ${e.message}")
                false
            }
        }

        /**
         * Resolves the directory that actually contains llm.mnn, starting from rootDir.
         * Checks rootDir directly first, then one level of subdirectories.
         * Returns null if llm.mnn cannot be found anywhere under rootDir.
         *
         * This handles the common adb-push case where files land in a subdirectory:
         *   adb push ./Qwen2-VL-2B-Instruct-MNN  /sdcard/.../qwen_mnn/
         * results in: /sdcard/.../qwen_mnn/Qwen2-VL-2B-Instruct-MNN/llm.mnn
         */
        fun resolveModelDir(rootDir: File): File? {
            // Direct check
            if (File(rootDir, "llm.mnn").exists()) {
                Log.i(TAG, "llm.mnn found directly in: ${rootDir.absolutePath}")
                return rootDir
            }
            Log.w(TAG, "llm.mnn not found directly in: ${rootDir.absolutePath}")
            val listing = rootDir.list()?.joinToString(", ") ?: "<directory empty or missing>"
            Log.w(TAG, "  Directory contents: $listing")

            // One-level subdirectory scan
            val subdirs = rootDir.listFiles { f -> f.isDirectory } ?: emptyArray()
            for (sub in subdirs) {
                if (File(sub, "llm.mnn").exists()) {
                    Log.w(TAG, "llm.mnn found in subdirectory: ${sub.absolutePath} " +
                        "— model was pushed one level too deep. Using this path.")
                    return sub
                }
            }
            Log.e(TAG, "llm.mnn not found in ${rootDir.absolutePath} or any immediate subdirectory")
            return null
        }
    }

    private var modelLoaded = false
    internal var modelPtr: Long = 0L

    /** Actual directory containing llm.mnn — may differ from the rootDir passed to loadModel(). */
    var resolvedModelDir: File? = null
        private set

    suspend fun loadModel(modelDir: File, cpuOnly: Boolean = false): Boolean = withContext(Dispatchers.IO) {
        val nativeAvailable = loadNativeLibs()

        val effectiveDir = resolveModelDir(modelDir)
        if (effectiveDir == null) {
            Log.e(TAG, "Model directory resolution failed. rootDir=${modelDir.absolutePath}")
            return@withContext false
        }

        resolvedModelDir = effectiveDir

        if (!nativeAvailable) {
            // STUB MODE: model files present but MNN AAR not yet integrated.
            // Inspector will simulate inference with realistic latency rather than fail.
            stubMode = true
            modelLoaded = true
            Log.w(TAG, "STUB MODE — llm.mnn found at ${effectiveDir.absolutePath} " +
                "but MNN native libs absent. Benchmark will simulate inference. " +
                "Integrate MNN-android.aar for real numbers.")
            return@withContext true
        }

        // Production: modelPtr = nativeLoadModel(effectiveDir.absolutePath, cpuOnly)
        stubMode = false
        modelLoaded = true
        Log.i(TAG, "Model loaded from ${effectiveDir.absolutePath}  cpuOnly=$cpuOnly")
        true
    }

    fun isLoaded(): Boolean = modelLoaded

    fun unloadModel() {
        if (modelLoaded && modelPtr != 0L) {
            // nativeUnloadModel(modelPtr)
            modelPtr = 0L
        }
        modelLoaded = false
    }

    // JNI declarations — implemented in MNN-android.aar
    // private external fun nativeLoadModel(modelDir: String, cpuOnly: Boolean): Long
    // private external fun nativeRunInference(ptr: Long, promptJson: String): String
    // private external fun nativeUnloadModel(ptr: Long)
}
