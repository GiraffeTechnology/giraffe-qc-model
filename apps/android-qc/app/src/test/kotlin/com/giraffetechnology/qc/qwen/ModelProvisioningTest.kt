package com.giraffetechnology.qc.qwen

import org.junit.Assert.*
import org.junit.Test
import java.io.File

class ModelProvisioningTest {

    @Test fun `default model name is Qwen3 2B variant`() {
        assertEquals("Qwen3-VL-2B-Instruct-MNN", ModelProvisioning.DEFAULT_MODEL_NAME)
    }

    @Test fun `provisioning mode enum has expected values`() {
        val modes = ProvisioningMode.values().map { it.name }
        assertTrue("BUNDLED mode required", modes.contains("BUNDLED"))
        assertTrue("SIDELOAD_OR_FACTORY_PRELOAD mode required",
            modes.contains("SIDELOAD_OR_FACTORY_PRELOAD"))
        assertFalse("DOWNLOAD_ON_FIRST_RUN must not be present",
            modes.contains("DOWNLOAD_ON_FIRST_RUN"))
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
            File(dir, "config.json").writeText("{}")
            assertFalse(
                "config.json alone should not satisfy isModelReady",
                ModelProvisioning.isModelReady(dir),
            )
        } finally {
            dir.deleteRecursively()
        }
    }
}
