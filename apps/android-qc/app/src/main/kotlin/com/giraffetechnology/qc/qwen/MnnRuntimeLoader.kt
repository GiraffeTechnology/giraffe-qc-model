package com.giraffetechnology.qc.qwen

import android.content.Context
import android.util.Log
import com.giraffetechnology.qc.sku.MnnRuntime
import com.giraffetechnology.qc.sku.MnnRuntimeState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Manages MNN model lifecycle (load/unload, native library binding).
 *
 * Production: wires to MNN-android.aar JNI layer.
 * CI/test: MNN native libs absent → loadNativeLibs() returns false → scaffold mode.
 *
 * Device: Snapdragon 8 Gen, 8 GB RAM.
 * Model: Qwen3-VL-2B-Instruct-MNN (INT4) — ~2 GB weights, ~3–4 GB at runtime
 * including vision encoder and KV cache. Within the 8 GB budget.
 *
 * Ready gate: the runtime only reports Ready once a real native model load
 * returns a non-zero model pointer. While JNI inference is still scaffolded
 * ([JNI_INFERENCE_WIRED] = false), a present model.mnn plus loaded native libs
 * is NOT enough — the runtime stays NotReady so the Pad fails closed instead of
 * accepting inspections that never actually ran on-device.
 */
class MnnRuntimeLoader(private val context: Context) : MnnRuntime {

    private val _runtimeState = MutableStateFlow<MnnRuntimeState>(MnnRuntimeState.NotReady)
    override val runtimeState: StateFlow<MnnRuntimeState> = _runtimeState.asStateFlow()

    companion object {
        private const val TAG = "MnnRuntimeLoader"

        // Flip to true only when nativeLoadModel/nativeRunInference are wired to the
        // MNN AAR. Until then real on-device inference is unavailable and the runtime
        // must never claim Ready.
        const val JNI_INFERENCE_WIRED = false

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

    internal var modelPtr: Long = 0L
    private var modelLoaded = false

    suspend fun loadModel(modelDir: File): Boolean = withContext(Dispatchers.IO) {
        _runtimeState.value = MnnRuntimeState.Loading
        if (!loadNativeLibs()) {
            Log.e(TAG, "MNN native libs not loaded — on-device inference unavailable")
            _runtimeState.value = MnnRuntimeState.NotReady
            return@withContext false
        }
        val modelFile = File(modelDir, "model.mnn")
        if (!modelFile.exists()) {
            Log.e(TAG, "model.mnn not found at ${modelFile.absolutePath}")
            _runtimeState.value = MnnRuntimeState.NotReady
            return@withContext false
        }

        // A real load must produce a non-zero native model pointer. While JNI is
        // scaffolded this returns 0L, so we refuse to report Ready: a file on disk
        // and loaded .so libs do not prove the model can actually run inference.
        val ptr = nativeLoadModelOrScaffold(modelDir)
        if (ptr == 0L) {
            Log.w(
                TAG,
                "MNN model not loaded into native runtime (JNI scaffolded) — " +
                    "runtime stays NotReady; on-device inference unavailable",
            )
            modelPtr = 0L
            modelLoaded = false
            _runtimeState.value = MnnRuntimeState.NotReady
            return@withContext false
        }

        modelPtr = ptr
        modelLoaded = true
        _runtimeState.value = MnnRuntimeState.Ready
        Log.i(TAG, "Model loaded from ${modelDir.absolutePath}")
        true
    }

    /**
     * Returns a real native model pointer once JNI is wired, otherwise 0L.
     * 0L means "not actually loaded" and the caller must not report Ready.
     */
    private fun nativeLoadModelOrScaffold(modelDir: File): Long =
        if (JNI_INFERENCE_WIRED) nativeLoadModel(modelDir.absolutePath) else 0L

    fun isLoaded(): Boolean = modelLoaded

    fun unloadModel() {
        if (modelLoaded && modelPtr != 0L) {
            if (JNI_INFERENCE_WIRED) nativeUnloadModel(modelPtr)
            modelPtr = 0L
        }
        modelLoaded = false
        _runtimeState.value = MnnRuntimeState.NotReady
    }

    // JNI declarations — implemented in MNN-android.aar. Calls are guarded by
    // JNI_INFERENCE_WIRED so the scaffold build links without the native symbols.
    private external fun nativeLoadModel(modelDir: String): Long
    private external fun nativeRunInference(ptr: Long, promptJson: String): String
    private external fun nativeUnloadModel(ptr: Long)
}
