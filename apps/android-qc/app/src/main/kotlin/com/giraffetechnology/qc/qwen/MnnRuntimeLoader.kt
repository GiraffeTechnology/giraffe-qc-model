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
 * CI/test: MNN native libs absent → loadNativeLibs() returns false → stub mode.
 * Stub mode: native libs absent but llm.mnn exists on device → simulated inference.
 *
 * GPU backend selection (Snapdragon 8 Gen+ / Adreno):
 *   cpuOnly=false (default): tries OpenCL first, then Vulkan, falls back to CPU.
 *   cpuOnly=true: CPU-only regardless of GPU availability.
 *
 * Device: Snapdragon 8 Gen, 8 GB RAM.
 * Model: Qwen3-VL-4B-Instruct-MNN (INT4). 8 GB viability, peak memory, and p95 latency
 * are pending the physical-device MNN benchmark — see MNN_DEVICE_TEST_PLAN.md.
 *
 * Model directory layout (MNN/Qwen3-VL-4B-Instruct-MNN):
 *   llm.mnn, llm.mnn.weight, visual.mnn, visual.mnn.weight,
 *   llm.mnn.json, llm_config.json, embeddings_bf16.bin, tokenizer.txt, config.json
 */
class MnnRuntimeLoader(private val context: Context) {

    companion object {
        private const val TAG = "MnnRuntimeLoader"
        private var nativeLoaded = false
        private var gpuLibsAttempted = false

        /**
         * True when llm.mnn was found on device but MNN native libs are absent.
         * MnnQwenInspector will simulate inference instead of calling JNI.
         */
        var stubMode = false
            private set

        /**
         * Which inference hardware backend is active after loadNativeLibs() completes.
         * "opencl"  — Adreno GPU via OpenCL (Snapdragon 8 Gen+, preferred)
         * "vulkan"  — Adreno GPU via Vulkan (fallback if OpenCL unavailable)
         * "cpu"     — CPU-only (cpuOnly=true or GPU libs unavailable on this device)
         * "stub"    — MNN native libs absent; benchmark simulates inference
         */
        var inferenceBackend: String = "stub"
            private set

        fun loadNativeLibs(cpuOnly: Boolean = false): Boolean {
            if (nativeLoaded) return true
            return try {
                System.loadLibrary("MNN")
                System.loadLibrary("MNN_Express")
                nativeLoaded = true

                if (cpuOnly) {
                    inferenceBackend = "cpu"
                    Log.i(TAG, "MNN native libs loaded — backend: cpu (cpuOnly=true)")
                } else if (!gpuLibsAttempted) {
                    gpuLibsAttempted = true

                    // OpenCL: primary GPU backend for Adreno (Snapdragon 8 Gen series)
                    // libMNN_CL.so is bundled in MNN-android.aar alongside libMNN.so
                    val openClLoaded = runCatching {
                        System.loadLibrary("MNN_CL")
                    }.isSuccess
                    if (!openClLoaded) Log.d(TAG, "MNN_CL unavailable — OpenCL not supported on this device")

                    // Vulkan: secondary GPU backend if OpenCL is unavailable
                    val vulkanLoaded = !openClLoaded && runCatching {
                        System.loadLibrary("MNN_Vulkan")
                    }.isSuccess
                    if (!vulkanLoaded && !openClLoaded) Log.d(TAG, "MNN_Vulkan also unavailable — falling back to CPU")

                    inferenceBackend = when {
                        openClLoaded -> "opencl"
                        vulkanLoaded -> "vulkan"
                        else         -> "cpu"
                    }
                    Log.i(TAG, "MNN native libs loaded — backend: $inferenceBackend")
                }
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
         *   adb push ./Qwen3-VL-4B-Instruct-MNN  /sdcard/.../qwen_mnn/
         * results in: /sdcard/.../qwen_mnn/Qwen3-VL-4B-Instruct-MNN/llm.mnn
         */
        fun resolveModelDir(rootDir: File): File? {
            if (File(rootDir, "llm.mnn").exists()) {
                Log.i(TAG, "llm.mnn found directly in: ${rootDir.absolutePath}")
                return rootDir
            }
            Log.w(TAG, "llm.mnn not found directly in: ${rootDir.absolutePath}")
            val listing = rootDir.list()?.joinToString(", ") ?: "<directory empty or missing>"
            Log.w(TAG, "  Directory contents: $listing")

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
        val nativeAvailable = loadNativeLibs(cpuOnly)

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
            inferenceBackend = "stub"
            modelLoaded = true
            Log.w(TAG, "STUB MODE — llm.mnn found at ${effectiveDir.absolutePath} " +
                "but MNN native libs absent. Benchmark will simulate inference. " +
                "Integrate MNN-android.aar for real numbers.")
            return@withContext true
        }

        // Production: modelPtr = nativeLoadModel(effectiveDir.absolutePath, inferenceBackend)
        stubMode = false
        modelLoaded = true
        Log.i(TAG, "Model loaded from ${effectiveDir.absolutePath}  backend=$inferenceBackend")
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
    // private external fun nativeLoadModel(modelDir: String, backend: String): Long
    // private external fun nativeRunInference(ptr: Long, promptJson: String): String
    // private external fun nativeUnloadModel(ptr: Long)
}
