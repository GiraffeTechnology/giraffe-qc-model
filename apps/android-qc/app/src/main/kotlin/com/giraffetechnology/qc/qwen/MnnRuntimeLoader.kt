package com.giraffetechnology.qc.qwen

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/**
 * MNN runtime loader for Qwen3-VL-4B-Instruct-MNN on Android Pad.
 *
 * Target: Snapdragon Android Pad, 8+ GB RAM.
 * Model: Qwen3-VL-4B-Instruct-MNN (INT4) — requires llm.mnn + visual.mnn + 8 supporting files.
 *
 * When MNN AAR is absent (CI/tests): loadNativeLibs() returns false → scaffold mode.
 * When model directory is incomplete: loadModel() returns false → review_required.
 *
 * IMPORTANT: A failed load NEVER triggers cloud fallback. Missing MNN = review_required.
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
            Log.e(TAG, "MNN native libs missing — local inference unavailable, result: review_required")
            return@withContext false
        }
        if (!ModelProvisioning.isModelReady(modelDir)) {
            val missing = ModelProvisioning.missingFiles(modelDir)
            Log.e(TAG, "Model directory incomplete — missing $missing, result: review_required")
            return@withContext false
        }
        // Production: modelPtr = nativeLoadModel(modelDir.absolutePath)
        // Scaffold: mark loaded when full file set is present (real JNI requires MNN AAR)
        modelLoaded = true
        Log.i(TAG, "Qwen3-VL-4B scaffold-loaded from ${modelDir.absolutePath}")
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
