package com.giraffetechnology.qc.qwen

import android.content.Context
import android.util.Log
import java.io.File
import java.security.MessageDigest

// Only sideload_or_factory_preload is permitted on the Pad QC device.
// Network model download is not allowed — the model must be pre-installed
// via factory sideload or OTA mechanism before the app is started.
enum class ProvisioningMode { BUNDLED, SIDELOAD_OR_FACTORY_PRELOAD }

enum class ProvisioningStatus {
    READY,
    NOT_PROVISIONED,
    CHECKSUM_FAILED,
}

data class ProvisioningConfig(
    val mode: ProvisioningMode = ProvisioningMode.SIDELOAD_OR_FACTORY_PRELOAD,
    // Qwen3-VL-2B-Instruct-MNN (INT4) — suitable for 8 GB RAM Snapdragon 8 Gen devices.
    val modelName: String = "Qwen3-VL-2B-Instruct-MNN",
    val expectedSha256: String = "",
)

/**
 * Handles on-device model provisioning.
 *
 * Checksum verification is MANDATORY when an expectedSha256 is provided.
 * A corrupted or partial model is NEVER silently used for inference.
 *
 * Network download has been intentionally removed. The model must arrive
 * via factory sideload, OTA push, or asset bundling — never via a runtime
 * HTTP fetch from the pad app.
 */
class ModelProvisioning(
    private val context: Context,
    val config: ProvisioningConfig,
) {
    companion object {
        private const val TAG = "ModelProvisioning"

        const val DEFAULT_MODEL_NAME = "Qwen3-VL-2B-Instruct-MNN"

        fun getModelDir(context: Context): File =
            File(context.filesDir, "models/qwen_mnn")

        fun isModelReady(modelDir: File): Boolean =
            modelDir.exists() && modelDir.isDirectory && File(modelDir, "model.mnn").exists()
    }

    fun getStatus(): ProvisioningStatus {
        val modelDir = getModelDir(context)
        if (!modelDir.exists()) return ProvisioningStatus.NOT_PROVISIONED
        val modelFile = File(modelDir, "model.mnn")
        if (!modelFile.exists()) return ProvisioningStatus.NOT_PROVISIONED
        if (config.expectedSha256.isNotBlank()) {
            val checksumFile = File(modelDir, "checksum.sha256")
            if (!checksumFile.exists()) return ProvisioningStatus.NOT_PROVISIONED
            if (!verifySha256(modelFile, checksumFile.readText().trim())) {
                return ProvisioningStatus.CHECKSUM_FAILED
            }
        }
        return ProvisioningStatus.READY
    }

    fun provision(onProgress: (Float) -> Unit = {}): ProvisioningStatus {
        return when (config.mode) {
            ProvisioningMode.BUNDLED -> provisionFromAssets(onProgress)
            ProvisioningMode.SIDELOAD_OR_FACTORY_PRELOAD -> getStatus()
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
            if (config.expectedSha256.isNotBlank()) {
                val modelFile = File(modelDir, "model.mnn")
                if (!verifySha256(modelFile, config.expectedSha256)) {
                    Log.e(TAG, "Bundled model checksum mismatch — refusing to use")
                    return ProvisioningStatus.CHECKSUM_FAILED
                }
            }
            Log.i(TAG, "Bundled model provisioned: ${config.modelName}")
            ProvisioningStatus.READY
        } catch (e: Exception) {
            Log.e(TAG, "Failed to provision from assets: ${e.message}")
            ProvisioningStatus.NOT_PROVISIONED
        }
    }

    private fun verifySha256(file: File, expectedHex: String): Boolean {
        if (expectedHex.isBlank() || !file.exists()) return false
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { s ->
            val buf = ByteArray(65536); var n: Int
            while (s.read(buf).also { n = it } != -1) digest.update(buf, 0, n)
        }
        val actual = digest.digest().joinToString("") { "%02x".format(it) }
        return actual.equals(expectedHex, ignoreCase = true)
    }
}
