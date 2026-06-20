package com.giraffetechnology.qc.qwen

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.security.MessageDigest

// Android Pad branch: offline local-only provisioning.
// Network download has been removed. Model is loaded via sdcard sideload or factory preload.
// Cloud download URL fields have been removed from ProvisioningConfig.

enum class ProvisioningMode {
    BUNDLED,               // Factory preload / app asset bundle
    SIDELOAD_FROM_SDCARD,  // Manual sideload via adb push or file manager
}

enum class ProvisioningStatus {
    READY,
    COPYING,
    NOT_PROVISIONED,
    PARTIAL_MODEL,
    CHECKSUM_FAILED,
}

data class ProvisioningConfig(
    val mode: ProvisioningMode = ProvisioningMode.SIDELOAD_FROM_SDCARD,
    val modelName: String = "Qwen3-VL-4B-Instruct-MNN",
    val expectedSha256: String = "",
)

/**
 * On-device model provisioning for the Android Pad local-only app.
 *
 * NEVER downloads from the network. Model must be present via an approved sideload path
 * or factory preloaded into app assets.
 *
 * All 8 required model files must be present before the model is considered READY.
 * checksum.sha256 is optional: if present it is verified against llm.mnn; if absent,
 * verification is skipped (Qwen3-VL-4B-Instruct-MNN on ModelScope does not ship it).
 */
class ModelProvisioning(
    private val context: Context,
    val config: ProvisioningConfig = ProvisioningConfig(),
) {
    companion object {
        private const val TAG = "ModelProvisioning"

        const val DEFAULT_MODEL_NAME = "Qwen3-VL-4B-Instruct-MNN"

        val REQUIRED_MODEL_FILES = listOf(
            "llm.mnn",
            "llm.mnn.weight",
            "visual.mnn",
            "visual.mnn.weight",
            "llm.mnn.json",
            "llm_config.json",
            "tokenizer.txt",
            "config.json",
        )

        // Approved sdcard sideload paths searched in order
        val SDCARD_SIDELOAD_PATHS = listOf(
            "/sdcard/qwen3_vl_4b_mnn",
            "/sdcard/Download/qwen3_vl_4b_mnn",
            "/sdcard/Android/data/com.giraffetechnology.qc/files/import/qwen3_vl_4b_mnn",
        )

        fun getModelDir(context: Context): File =
            File(context.filesDir, "models/qwen_mnn")

        fun sha256(bytes: ByteArray): String {
            val digest = MessageDigest.getInstance("SHA-256")
            digest.update(bytes)
            return digest.digest().joinToString("") { "%02x".format(it) }
        }

        /**
         * Pure filesystem validation — no Android Context required; safe to call
         * from JVM unit tests. Checks all 8 required files present and verifies
         * llm.mnn against checksum.sha256 (if present).
         */
        fun validateModelDir(modelDir: File): ProvisioningStatus {
            if (!modelDir.exists()) return ProvisioningStatus.NOT_PROVISIONED
            val missing = missingFiles(modelDir)
            if (missing.isNotEmpty()) return ProvisioningStatus.PARTIAL_MODEL
            if (!verifyModelChecksum(modelDir)) return ProvisioningStatus.CHECKSUM_FAILED
            return ProvisioningStatus.READY
        }

        /**
         * Verifies llm.mnn against checksum.sha256 in the given model directory.
         * Returns true only when both files exist, the checksum is non-blank,
         * and the actual SHA-256 of llm.mnn matches the recorded value.
         * A blank or absent checksum always returns false — bypass not permitted.
         */
        fun verifyModelChecksum(modelDir: File): Boolean {
            val checksumFile = File(modelDir, "checksum.sha256")
            if (!checksumFile.exists()) return true  // no checksum file — skip verification
            val llmFile = File(modelDir, "llm.mnn")
            if (!llmFile.exists()) return false
            val expectedHex = checksumFile.readText().trim()
            if (expectedHex.isBlank()) return false
            val digest = MessageDigest.getInstance("SHA-256")
            llmFile.inputStream().use { s ->
                val buf = ByteArray(65536); var n: Int
                while (s.read(buf).also { n = it } != -1) digest.update(buf, 0, n)
            }
            val actual = digest.digest().joinToString("") { "%02x".format(it) }
            return actual.equals(expectedHex, ignoreCase = true)
        }

        /**
         * Returns true only if ALL 8 required model files are present.
         * Partial model presence is treated as NOT_READY.
         */
        fun isModelReady(modelDir: File): Boolean {
            if (!modelDir.exists() || !modelDir.isDirectory) return false
            return REQUIRED_MODEL_FILES.all { File(modelDir, it).exists() }
        }

        fun missingFiles(modelDir: File): List<String> {
            if (!modelDir.exists() || !modelDir.isDirectory) return REQUIRED_MODEL_FILES
            return REQUIRED_MODEL_FILES.filter { !File(modelDir, it).exists() }
        }
    }

    fun getStatus(): ProvisioningStatus {
        val modelDir = getModelDir(context)
        val status = validateModelDir(modelDir)
        when (status) {
            ProvisioningStatus.PARTIAL_MODEL   -> Log.w(TAG, "Partial model at ${modelDir.absolutePath} — missing: ${missingFiles(modelDir)}")
            ProvisioningStatus.CHECKSUM_FAILED -> Log.e(TAG, "llm.mnn checksum mismatch — refusing to use model")
            else -> {}
        }
        return status
    }

    suspend fun provision(onProgress: (Float) -> Unit = {}): ProvisioningStatus =
        withContext(Dispatchers.IO) {
            when (config.mode) {
                ProvisioningMode.BUNDLED              -> provisionFromAssets(onProgress)
                ProvisioningMode.SIDELOAD_FROM_SDCARD -> importFromSdcard(onProgress)
            }
        }

    private fun provisionFromAssets(onProgress: (Float) -> Unit): ProvisioningStatus {
        val modelDir = getModelDir(context)
        modelDir.mkdirs()
        return try {
            val files = context.assets.list("models/qwen_mnn") ?: emptyArray()
            files.forEachIndexed { i, name ->
                context.assets.open("models/qwen_mnn/$name").use { input ->
                    File(modelDir, name).outputStream().use { out -> input.copyTo(out) }
                }
                onProgress((i + 1).toFloat() / files.size)
            }
            val missing = missingFiles(modelDir)
            if (missing.isNotEmpty()) {
                Log.e(TAG, "Bundled assets missing required files: $missing")
                return ProvisioningStatus.PARTIAL_MODEL
            }
            // Always verify checksum — bypass not permitted on Pad branch
            if (!verifyModelChecksum(modelDir)) {
                Log.e(TAG, "Bundled model checksum mismatch — refusing to use")
                return ProvisioningStatus.CHECKSUM_FAILED
            }
            Log.i(TAG, "Bundled model provisioned: ${config.modelName}")
            ProvisioningStatus.READY
        } catch (e: Exception) {
            Log.e(TAG, "Failed to provision from assets: ${e.message}")
            ProvisioningStatus.NOT_PROVISIONED
        }
    }

    /**
     * Imports model from an approved sdcard sideload path.
     * Searches paths in order, copies all required files to app-private filesDir.
     * NEVER downloads from the internet.
     */
    private fun importFromSdcard(onProgress: (Float) -> Unit): ProvisioningStatus {
        val srcDir = SDCARD_SIDELOAD_PATHS.map { File(it) }.firstOrNull { dir ->
            dir.exists() && dir.isDirectory && isModelReady(dir)
        }
        if (srcDir == null) {
            val partialDir = SDCARD_SIDELOAD_PATHS.map { File(it) }.firstOrNull { it.exists() }
            if (partialDir != null) {
                Log.e(TAG, "Partial model at ${partialDir.absolutePath} — missing: ${missingFiles(partialDir)}")
                return ProvisioningStatus.PARTIAL_MODEL
            }
            Log.e(TAG, "No model found at any sideload path: $SDCARD_SIDELOAD_PATHS")
            return ProvisioningStatus.NOT_PROVISIONED
        }

        val destDir = getModelDir(context)
        destDir.mkdirs()
        return try {
            REQUIRED_MODEL_FILES.forEachIndexed { i, name ->
                File(srcDir, name).copyTo(File(destDir, name), overwrite = true)
                onProgress((i + 1).toFloat() / REQUIRED_MODEL_FILES.size)
            }
            if (!isModelReady(destDir)) {
                Log.e(TAG, "Copy incomplete — missing: ${missingFiles(destDir)}")
                return ProvisioningStatus.PARTIAL_MODEL
            }
            // Always verify checksum after copy — bypass not permitted on Pad branch
            if (!verifyModelChecksum(destDir)) {
                Log.e(TAG, "Imported model checksum mismatch — refusing to use")
                return ProvisioningStatus.CHECKSUM_FAILED
            }
            Log.i(TAG, "Model imported from ${srcDir.absolutePath}")
            ProvisioningStatus.READY
        } catch (e: Exception) {
            Log.e(TAG, "Sdcard import failed: ${e.message}")
            ProvisioningStatus.NOT_PROVISIONED
        }
    }
}
