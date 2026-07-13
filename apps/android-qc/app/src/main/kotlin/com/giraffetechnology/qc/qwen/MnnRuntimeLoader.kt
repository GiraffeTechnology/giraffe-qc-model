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
import java.security.MessageDigest

/**
 * Manages MNN model lifecycle (load/unload, native library binding) and owns
 * the on-device inference entry point.
 *
 * Device target: OPPO PKB110 (arm64-v8a), on-device Qwen3-VL-2B-Instruct-MNN.
 * Model: ~1.3 GB weights (llm.mnn.weight + visual.mnn.weight) at a configurable
 * root, default `/sdcard/qwen_2b_mnn`.
 *
 * ## Ready gate (fail-closed)
 * The runtime reports [MnnRuntimeState.Ready] ONLY when a real native model load
 * returns a non-zero handle for BOTH the LLM and the visual encoder. Before that
 * the loader enforces, in order:
 *   1. the model directory exists,
 *   2. every required weight file + the tokenizer are present,
 *   3. the checksum manifest is present and (optionally) every listed file's
 *      SHA-256 matches — a corrupt/partial model fails closed to NotReady,
 *   4. the MNN native libraries load,
 *   5. `nativeLoadModel` returns a non-zero handle.
 * Any failure leaves the runtime NotReady so the Pad defers to manual review
 * instead of accepting an inspection that never actually ran on-device.
 *
 * ## Tripwire — [JNI_INFERENCE_WIRED]
 * This flag is `false` until `nativeLoadModel`/`nativeRunInference` are BOTH
 * wired to a real MNN AAR AND that wiring has been verified on-device. While it
 * is false, [nativeLoadModelOrScaffold] returns 0L, so the Ready transition can
 * never fire and inference throws — the Pad stays fail-closed. Flipping it
 * without verified native wiring is caught by [MnnRuntimeLoaderTest].
 */
class MnnRuntimeLoader(
    private val context: Context,
    private val config: MnnRuntimeConfig = MnnRuntimeConfig(),
) : MnnRuntime {

    private val _runtimeState = MutableStateFlow<MnnRuntimeState>(MnnRuntimeState.NotReady)
    override val runtimeState: StateFlow<MnnRuntimeState> = _runtimeState.asStateFlow()
    override val inferenceVerified: Boolean get() = JNI_INFERENCE_WIRED

    companion object {
        private const val TAG = "MnnRuntimeLoader"

        /**
         * Flip to true ONLY in the same change that wires nativeLoadModel /
         * nativeRunInference to the real MNN AAR AND verifies it on-device.
         * Until then real on-device inference is unavailable and the runtime
         * must never claim Ready. Guarded by [MnnRuntimeLoaderTest].
         */
        const val JNI_INFERENCE_WIRED = false

        private var nativeLoaded = false

        fun loadNativeLibs(): Boolean {
            if (nativeLoaded) return true
            return try {
                System.loadLibrary("MNN")
                System.loadLibrary("MNN_Express")
                // The JNI bridge (libmnn_qwen_jni.so) hosts nativeLoadModel /
                // nativeRunInference / nativeUnloadModel and links against MNN.
                System.loadLibrary("mnn_qwen_jni")
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

    /** Loads the default configured model root ([MnnRuntimeConfig.modelRoot]). */
    suspend fun loadModel(): Boolean = loadModel(File(config.modelRoot))

    /**
     * Loads and validates the model at [modelDir]. Returns true only when the
     * runtime reaches Ready (native handle non-zero). Any validation or native
     * failure sets NotReady and returns false — never throws to the caller.
     */
    suspend fun loadModel(modelDir: File): Boolean = withContext(Dispatchers.IO) {
        _runtimeState.value = MnnRuntimeState.Loading

        if (!modelDir.exists() || !modelDir.isDirectory) {
            failClosed("model directory not found: ${modelDir.absolutePath}")
            return@withContext false
        }

        // (2) Required weight files + tokenizer must all be present.
        val requiredFiles = config.requiredWeightFiles + config.tokenizerFile
        val missing = requiredFiles.filterNot { File(modelDir, it).exists() }
        if (missing.isNotEmpty()) {
            failClosed("missing required model files: $missing at ${modelDir.absolutePath}")
            return@withContext false
        }

        // (3) Checksum manifest must be present; verify listed files fail-closed.
        val checksumFile = File(modelDir, config.checksumFile)
        if (!checksumFile.exists()) {
            failClosed("checksum manifest ${config.checksumFile} missing — refusing to load")
            return@withContext false
        }
        if (config.verifyChecksumOnLoad) {
            val checksumError = verifyChecksums(modelDir, checksumFile)
            if (checksumError != null) {
                failClosed("checksum verification failed: $checksumError")
                return@withContext false
            }
            Log.i(TAG, "Checksum verification passed for ${checksumFile.name}")
        }

        // (4) Native libraries.
        if (!loadNativeLibs()) {
            failClosed("MNN native libs not loaded — on-device inference unavailable")
            return@withContext false
        }

        // (5) Real native load must produce a non-zero handle. While JNI is not
        // wired (or verified) this returns 0L and we refuse to report Ready.
        val ptr = nativeLoadModelOrScaffold(modelDir)
        if (ptr == 0L) {
            Log.w(
                TAG,
                "MNN model not loaded into native runtime " +
                    "(JNI_INFERENCE_WIRED=$JNI_INFERENCE_WIRED) — runtime stays " +
                    "NotReady; on-device inference unavailable",
            )
            modelPtr = 0L
            modelLoaded = false
            _runtimeState.value = MnnRuntimeState.NotReady
            return@withContext false
        }

        modelPtr = ptr
        modelLoaded = true
        _runtimeState.value = MnnRuntimeState.Ready
        Log.i(TAG, "Model loaded (handle=$ptr) from ${modelDir.absolutePath}")
        true
    }

    private fun failClosed(reason: String) {
        Log.e(TAG, reason)
        modelPtr = 0L
        modelLoaded = false
        _runtimeState.value = MnnRuntimeState.NotReady
    }

    /**
     * Verifies each `<hex>␠␠<filename>` entry in [checksumFile] against the file
     * on disk. Returns null on success, or a human-readable reason on the first
     * failure (missing listed file, or hash mismatch). The manifest may list the
     * checksum file itself or entries outside the model dir; those are skipped.
     */
    private fun verifyChecksums(modelDir: File, checksumFile: File): String? {
        val lines = checksumFile.readLines().map { it.trim() }.filter { it.isNotEmpty() }
        if (lines.isEmpty()) return "checksum manifest is empty"
        var verified = 0
        for (line in lines) {
            // sha256sum format: "<64 hex>  <name>" (two spaces) or "<hex> *<name>".
            val parts = line.split(Regex("\\s+"), limit = 2)
            if (parts.size != 2) continue
            val expectedHex = parts[0].lowercase()
            if (expectedHex.length != 64) continue
            val name = parts[1].removePrefix("*").trim()
            if (name == config.checksumFile) continue
            val target = File(modelDir, name)
            if (!target.exists()) return "listed file missing: $name"
            val actual = sha256Of(target)
            if (!actual.equals(expectedHex, ignoreCase = true)) {
                return "hash mismatch for $name (expected $expectedHex, got $actual)"
            }
            verified++
        }
        if (verified == 0) return "no verifiable entries in checksum manifest"
        return null
    }

    private fun sha256Of(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { s ->
            val buf = ByteArray(1 shl 16)
            var n: Int
            while (s.read(buf).also { n = it } != -1) digest.update(buf, 0, n)
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    /**
     * Returns a real native model handle once JNI is wired and verified,
     * otherwise 0L. 0L means "not actually loaded" and the caller must not
     * report Ready.
     */
    private fun nativeLoadModelOrScaffold(modelDir: File): Long =
        if (JNI_INFERENCE_WIRED) nativeLoadModel(modelDir.absolutePath) else 0L

    fun isLoaded(): Boolean = modelLoaded

    /**
     * Runs one native inference pass. [requestJson] is the fully-assembled
     * request (image references + prompt) built by [MnnQwenInspector]; the
     * return value is the model's raw text output for [QcResultParser].
     *
     * Throws if the runtime is not loaded or JNI is not wired — callers treat a
     * throw as an inference error and fail closed to review_required.
     */
    fun runInference(requestJson: String): String {
        check(modelLoaded && modelPtr != 0L) { "model not loaded" }
        check(JNI_INFERENCE_WIRED) { "JNI inference not wired" }
        return nativeRunInference(modelPtr, requestJson)
    }

    fun unloadModel() {
        if (modelLoaded && modelPtr != 0L) {
            if (JNI_INFERENCE_WIRED) nativeUnloadModel(modelPtr)
            modelPtr = 0L
        }
        modelLoaded = false
        _runtimeState.value = MnnRuntimeState.NotReady
    }

    // JNI declarations — implemented in cpp/mnn_qwen_jni.cpp against the MNN AAR.
    // Calls are guarded by JNI_INFERENCE_WIRED so the scaffold build links and
    // runs (fail-closed) without the native symbols present.
    private external fun nativeLoadModel(modelDir: String): Long
    private external fun nativeRunInference(ptr: Long, requestJson: String): String
    private external fun nativeUnloadModel(ptr: Long)
}
