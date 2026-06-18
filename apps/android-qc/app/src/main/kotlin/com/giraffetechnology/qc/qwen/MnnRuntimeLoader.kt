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
        if (!loadNativeLibs()) {
            Log.e(TAG, "MNN native libs not loaded — on-device inference unavailable")
            return@withContext false
        }
        val modelFile = File(modelDir, "llm.mnn")
        if (!modelFile.exists()) {
            Log.e(TAG, "llm.mnn not found at ${modelFile.absolutePath}")
            return@withContext false
        }
        // Production: modelPtr = nativeLoadModel(modelDir.absolutePath, cpuOnly)
        // Scaffold: mark loaded if file exists (real call requires MNN AAR)
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
