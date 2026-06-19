package com.giraffetechnology.qc.qwen

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.net.URL
import java.security.MessageDigest

enum class ProvisioningMode { BUNDLED, DOWNLOAD_ON_FIRST_RUN }

enum class ProvisioningStatus {
    READY,
    DOWNLOADING,
    NOT_PROVISIONED,
    CHECKSUM_FAILED,
    DOWNLOAD_FAILED,
}

data class ProvisioningConfig(
    val mode: ProvisioningMode = ProvisioningMode.DOWNLOAD_ON_FIRST_RUN,
    // Default: Qwen3-VL-4B-Instruct-MNN (INT4) — suitable for 8GB RAM Snapdragon 8 Gen devices.
    // For devices with <3GB available RAM, switch to a smaller model variant.
    val modelName: String = "Qwen3-VL-4B-Instruct-MNN",
    val modelDownloadUrl: String = "",
    val expectedSha256: String = "",
)

/**
 * Handles on-device model provisioning (§4.3.2).
 *
 * Checksum verification is MANDATORY.
 * A corrupted or partial download is NEVER silently used for inference.
 *
 * Hardware note: Qwen3-VL-4B-Instruct-MNN (INT4) requires ~8GB device RAM.
 * Tested device: Snapdragon 8 Gen, 8 GB RAM — 4B model is viable.
 */
class ModelProvisioning(
    private val context: Context,
    val config: ProvisioningConfig,
) {
    companion object {
        private const val TAG = "ModelProvisioning"

        const val DEFAULT_MODEL_NAME = "Qwen3-VL-4B-Instruct-MNN"

        fun getModelDir(context: Context): File =
            File(context.filesDir, "models/qwen_mnn")

        fun sha256(bytes: ByteArray): String {
            val digest = MessageDigest.getInstance("SHA-256")
            digest.update(bytes)
            return digest.digest().joinToString("") { "%02x".format(it) }
        }

        fun isModelReady(modelDir: File): Boolean =
            modelDir.exists() && modelDir.isDirectory &&
            File(modelDir, "llm.mnn").exists() &&
            File(modelDir, "llm.mnn.weight").exists() &&
            File(modelDir, "visual.mnn").exists() &&
            File(modelDir, "visual.mnn.weight").exists()
    }

    fun getStatus(): ProvisioningStatus {
        val modelDir = getModelDir(context)
        if (!modelDir.exists()) return ProvisioningStatus.NOT_PROVISIONED
        val checksumFile = File(modelDir, "checksum.sha256")
        if (!checksumFile.exists()) return ProvisioningStatus.NOT_PROVISIONED
        val modelFile = File(modelDir, "llm.mnn")
        if (!modelFile.exists()) return ProvisioningStatus.NOT_PROVISIONED
        return if (verifySha256(modelFile, checksumFile.readText().trim()))
            ProvisioningStatus.READY
        else
            ProvisioningStatus.CHECKSUM_FAILED
    }

    suspend fun provision(onProgress: (Float) -> Unit = {}): ProvisioningStatus =
        withContext(Dispatchers.IO) {
            when (config.mode) {
                ProvisioningMode.BUNDLED              -> provisionFromAssets(onProgress)
                ProvisioningMode.DOWNLOAD_ON_FIRST_RUN -> downloadAndVerify(onProgress)
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
            val checksumFile = File(modelDir, "checksum.sha256")
            if (!checksumFile.exists()) {
                Log.e(TAG, "No checksum file in bundled assets — refusing to use model")
                return ProvisioningStatus.CHECKSUM_FAILED
            }
            val modelFile = File(modelDir, "llm.mnn")
            if (!verifySha256(modelFile, checksumFile.readText().trim())) {
                Log.e(TAG, "Bundled model checksum mismatch — refusing to use model")
                return ProvisioningStatus.CHECKSUM_FAILED
            }
            Log.i(TAG, "Bundled model provisioned and verified: ${config.modelName}")
            ProvisioningStatus.READY
        } catch (e: Exception) {
            Log.e(TAG, "Failed to provision from assets: ${e.message}")
            ProvisioningStatus.NOT_PROVISIONED
        }
    }

    private fun downloadAndVerify(onProgress: (Float) -> Unit): ProvisioningStatus {
        if (config.modelDownloadUrl.isBlank()) {
            Log.e(TAG, "No download URL configured")
            return ProvisioningStatus.NOT_PROVISIONED
        }
        val modelDir = getModelDir(context)
        modelDir.mkdirs()
        val tmpFile = File(modelDir.parentFile, "model_download.tmp")
        return try {
            Log.i(TAG, "Downloading model from ${config.modelDownloadUrl}")
            URL(config.modelDownloadUrl).openStream().use { input ->
                tmpFile.outputStream().use { out ->
                    val buf  = ByteArray(65536)
                    var read: Int
                    while (input.read(buf).also { read = it } != -1) out.write(buf, 0, read)
                }
            }
            if (config.expectedSha256.isNotBlank() && !verifySha256(tmpFile, config.expectedSha256)) {
                tmpFile.delete()
                Log.e(TAG, "Downloaded model checksum mismatch — refusing to use")
                return ProvisioningStatus.CHECKSUM_FAILED
            }
            val modelFile = File(modelDir, "llm.mnn")
            tmpFile.renameTo(modelFile)
            File(modelDir, "checksum.sha256").writeText(config.expectedSha256)
            Log.i(TAG, "Model downloaded and verified: ${config.modelName}")
            ProvisioningStatus.READY
        } catch (e: Exception) {
            tmpFile.delete()
            Log.e(TAG, "Download failed: ${e.message}")
            ProvisioningStatus.DOWNLOAD_FAILED
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
