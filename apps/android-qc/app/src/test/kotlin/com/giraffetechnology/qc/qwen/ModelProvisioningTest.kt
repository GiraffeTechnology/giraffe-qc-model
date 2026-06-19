package com.giraffetechnology.qc.qwen

import org.junit.Assert.*
import org.junit.Test
import java.io.File

class ModelProvisioningTest {

    // Note: These tests run on JVM (not Android), so Context is null.
    // ModelProvisioning.getModelDir() is tested indirectly; SHA256 and path logic
    // are unit-tested here via the companion utilities.

    @Test fun `default model name is 4B variant for 8GB device`() {
        assertEquals("Qwen3-VL-4B-Instruct-MNN", ModelProvisioning.DEFAULT_MODEL_NAME)
    }

    @Test fun `provisioning mode enum has expected values`() {
        val modes = ProvisioningMode.values().map { it.name }
        assertTrue("BUNDLED mode required", modes.contains("BUNDLED"))
        assertTrue("DOWNLOAD_ON_FIRST_RUN mode required", modes.contains("DOWNLOAD_ON_FIRST_RUN"))
    }

    @Test fun `sha256 of empty bytes is known constant`() {
        val emptyHash = ModelProvisioning.sha256(ByteArray(0))
        // SHA-256 of zero bytes is well-known
        assertEquals(
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            emptyHash,
        )
    }

    @Test fun `sha256 of single byte matches expected`() {
        // SHA-256 of [0x00] = 6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d
        val hash = ModelProvisioning.sha256(byteArrayOf(0x00.toByte()))
        assertEquals(
            "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
            hash,
        )
    }

    @Test fun `sha256 output is lowercase hex`() {
        val hash = ModelProvisioning.sha256("hello".toByteArray())
        assertTrue("Must be lowercase hex", hash.matches(Regex("[0-9a-f]+")))
        assertEquals("Must be 64 chars", 64, hash.length)
    }

    @Test fun `sha256 is deterministic`() {
        val data = "test_data_for_repeatability".toByteArray()
        val h1 = ModelProvisioning.sha256(data)
        val h2 = ModelProvisioning.sha256(data)
        assertEquals(h1, h2)
    }

    @Test fun `sha256 differs for different inputs`() {
        val h1 = ModelProvisioning.sha256("abc".toByteArray())
        val h2 = ModelProvisioning.sha256("abd".toByteArray())
        assertNotEquals(h1, h2)
    }

    @Test fun `isModelReady returns false when directory does not exist`() {
        val nonExistentDir = File("/tmp/nonexistent_model_dir_${System.nanoTime()}")
        assertFalse(ModelProvisioning.isModelReady(nonExistentDir))
    }

    @Test fun `isModelReady returns false for empty directory`() {
        val emptyDir = createTempDir()
        try {
            assertFalse(ModelProvisioning.isModelReady(emptyDir))
        } finally {
            emptyDir.deleteRecursively()
        }
    }

    @Test fun `isModelReady returns true when model file present`() {
        val dir = createTempDir()
        try {
            File(dir, "model.mnn").writeText("fake model content")
            assertTrue(ModelProvisioning.isModelReady(dir))
        } finally {
            dir.deleteRecursively()
        }
    }

    @Test fun `isModelReady requires model_mnn file specifically`() {
        val dir = createTempDir()
        try {
            // Only a config file, no model.mnn — should not be ready
            File(dir, "config.json").writeText("{}")
            assertFalse("config.json alone should not satisfy isModelReady",
                ModelProvisioning.isModelReady(dir))
        } finally {
            dir.deleteRecursively()
        }
    }
}
