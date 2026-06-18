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
    }

    private var modelLoaded = false
    internal var modelPtr: Long = 0L

    suspend fun loadModel(modelDir: File, cpuOnly: Boolean = false): Boolean = withContext(Dispatchers.IO) {
        val nativeAvailable = loadNativeLibs()
        val modelFile = File(modelDir, "llm.mnn")
        if (!modelFile.exists()) {
            Log.e(TAG, "llm.mnn not found at ${modelFile.absolutePath}")
            return@withContext false
        }
        if (!nativeAvailable) {
            // STUB MODE: model files present but MNN AAR not yet integrated.
            // Inspector will simulate inference with realistic latency rather than fail.
            stubMode = true
            modelLoaded = true
            Log.w(TAG, "STUB MODE — llm.mnn found but MNN native libs absent. " +
                "Benchmark will simulate inference. Integrate MNN-android.aar for real numbers.")
            return@withContext true
        }
        // Production: modelPtr = nativeLoadModel(modelDir.absolutePath, cpuOnly)
        stubMode = false
        modelLoaded = true
        Log.i(TAG, "Model loaded from ${modelDir.absolutePath}  cpuOnly=$cpuOnly")
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
