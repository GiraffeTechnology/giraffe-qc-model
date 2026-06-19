package com.giraffetechnology.qc.qwen

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Loads Qwen3-VL-4B-Instruct-MNN via NativeMnnQwenBridge.
 *
 * [loadModel] verifies model files, verifies checksum, then calls
 * [NativeMnnQwenBridge.nativeLoadModel] and stores the returned non-zero
 * handle in [modelPtr]. [isLoaded] returns true only when modelPtr != 0.
 *
 * There is no scaffold success path. modelPtr > 0 if and only if
 * nativeLoadModel returned a non-zero handle.
 *
 * Failed load: modelPtr stays 0. Callers must return review_required.
 * No cloud fallback. No placeholder. No stub pass.
 */
class MnnRuntimeLoader(
    @Suppress("UnusedPrivateProperty") private val context: Context,
) {

    companion object {
        private const val TAG = "MnnRuntimeLoader"

        @Volatile private var nativeLibsAttempted = false
        @Volatile private var nativeLibsLoaded    = false

        /**
         * Triggers NativeMnnQwenBridge class initialisation (System.loadLibrary calls).
         * Returns false if any library is missing (UnsatisfiedLinkError wrapped in
         * ExceptionInInitializerError, or similar Throwable).
         */
        fun loadNativeLibs(): Boolean {
            if (nativeLibsAttempted) return nativeLibsLoaded
            nativeLibsAttempted = true
            return try {
                // Calling isAvailable() triggers the object init block:
                //   System.loadLibrary("MNN")
                //   System.loadLibrary("MNN_Express")
                //   System.loadLibrary("giraffe_mnn_qwen_bridge")
                NativeMnnQwenBridge.isAvailable()
                nativeLibsLoaded = true
                Log.i(TAG, "MNN native libs loaded")
                true
            } catch (t: Throwable) {
                Log.e(TAG, "MNN native libs not available: ${t.cause?.message ?: t.message}")
                nativeLibsLoaded = false
                false
            }
        }
    }

    internal var modelPtr: Long = 0L
        private set

    fun isLoaded(): Boolean = modelPtr > 0L

    suspend fun loadModel(modelDir: File): Boolean = withContext(Dispatchers.IO) {
        if (!loadNativeLibs()) {
            Log.e(TAG, "MNN native libs missing — result: review_required")
            return@withContext false
        }
        if (!ModelProvisioning.isModelReady(modelDir)) {
            Log.e(TAG, "Model incomplete — missing: ${ModelProvisioning.missingFiles(modelDir)} — result: review_required")
            return@withContext false
        }
        if (!ModelProvisioning.verifyModelChecksum(modelDir)) {
            Log.e(TAG, "Model checksum failed — result: review_required")
            return@withContext false
        }

        Log.i(TAG, "nativeLoadModel start: ${modelDir.absolutePath}")
        val ptr = NativeMnnQwenBridge.nativeLoadModel(modelDir.absolutePath)

        if (ptr <= 0L) {
            Log.e(TAG, "nativeLoadModel returned $ptr — result: review_required")
            modelPtr = 0L
            return@withContext false
        }

        modelPtr = ptr
        Log.i(TAG, "nativeLoadModel success: modelPtr=$modelPtr (non-zero)")
        true
    }

    fun unloadModel() {
        val ptr = modelPtr
        if (ptr != 0L) {
            Log.i(TAG, "nativeUnloadModel: ptr=$ptr")
            NativeMnnQwenBridge.nativeUnloadModel(ptr)
            modelPtr = 0L
        }
    }
}
