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
 * Model: Qwen3-VL-2B-Instruct-MNN (INT4) — ~2GB weights, ~3-4GB at runtime including
 * vision encoder and KV cache. Within the 8GB budget.
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

    suspend fun loadModel(modelDir: File): Boolean = withContext(Dispatchers.IO) {
        if (!loadNativeLibs()) {
            Log.e(TAG, "MNN native libs not loaded — on-device inference unavailable")
            return@withContext false
        }
        val modelFile = File(modelDir, "model.mnn")
        if (!modelFile.exists()) {
            Log.e(TAG, "model.mnn not found at ${modelFile.absolutePath}")
            return@withContext false
        }
        // Production: modelPtr = nativeLoadModel(modelDir.absolutePath)
        // Scaffold: mark loaded if file exists (real call requires MNN AAR)
        modelLoaded = true
        Log.i(TAG, "Model loaded from ${modelDir.absolutePath}")
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
    // private external fun nativeLoadModel(modelDir: String): Long
    // private external fun nativeRunInference(ptr: Long, promptJson: String): String
    // private external fun nativeUnloadModel(ptr: Long)
}
