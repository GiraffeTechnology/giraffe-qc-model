package com.giraffetechnology.qc.qwen

import org.junit.Assert.*
import org.junit.Test
import java.io.File

class ModelProvisioningTest {

    // Note: runs on JVM (not Android), so Context is null.
    // getModelDir(), sideload provisioning, and sha256/path logic are unit-tested here.

    @Test fun `default model name is Qwen3-VL-4B-Instruct-MNN`() {
        assertEquals("Qwen3-VL-4B-Instruct-MNN", ModelProvisioning.DEFAULT_MODEL_NAME)
    }

    @Test fun `provisioning mode enum has BUNDLED and SIDELOAD_FROM_SDCARD`() {
        val modes = ProvisioningMode.values().map { it.name }
        assertTrue("BUNDLED mode required", modes.contains("BUNDLED"))
        assertTrue("SIDELOAD_FROM_SDCARD mode required", modes.contains("SIDELOAD_FROM_SDCARD"))
        assertFalse("DOWNLOAD_ON_FIRST_RUN must not exist on Pad branch",
            modes.contains("DOWNLOAD_ON_FIRST_RUN"))
    }

    @Test fun `required model files list has all 10 mandatory files`() {
        val req = ModelProvisioning.REQUIRED_MODEL_FILES
        assertTrue(req.contains("llm.mnn"))
        assertTrue(req.contains("llm.mnn.weight"))
        assertTrue(req.contains("visual.mnn"))
        assertTrue(req.contains("visual.mnn.weight"))
        assertTrue(req.contains("llm.mnn.json"))
        assertTrue(req.contains("llm_config.json"))
        assertTrue(req.contains("embeddings_bf16.bin"))
        assertTrue(req.contains("tokenizer.txt"))
        assertTrue(req.contains("config.json"))
        assertTrue(req.contains("checksum.sha256"))
        assertEquals("exactly 10 required files", 10, req.size)
    }

    @Test fun `sha256 of empty bytes is known constant`() {
        val emptyHash = ModelProvisioning.sha256(ByteArray(0))
        assertEquals(
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            emptyHash,
        )
    }

    @Test fun `sha256 of single byte matches expected`() {
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
        assertEquals(ModelProvisioning.sha256(data), ModelProvisioning.sha256(data))
    }

    @Test fun `sha256 differs for different inputs`() {
        assertNotEquals(
            ModelProvisioning.sha256("abc".toByteArray()),
            ModelProvisioning.sha256("abd".toByteArray()),
        )
    }

    @Test fun `isModelReady returns false when directory does not exist`() {
        val nonExistentDir = File("/tmp/nonexistent_model_dir_${System.nanoTime()}")
        assertFalse(ModelProvisioning.isModelReady(nonExistentDir))
    }

    @Test fun `isModelReady returns false for empty directory`() {
        val dir = createTempDir()
        try {
            assertFalse(ModelProvisioning.isModelReady(dir))
        } finally {
            dir.deleteRecursively()
        }
    }

    @Test fun `isModelReady returns false with only llm_mnn present`() {
        val dir = createTempDir()
        try {
            File(dir, "llm.mnn").writeText("fake")
            assertFalse("llm.mnn alone is insufficient — all 10 files required",
                ModelProvisioning.isModelReady(dir))
        } finally {
            dir.deleteRecursively()
        }
    }

    @Test fun `isModelReady returns false when only config json present`() {
        val dir = createTempDir()
        try {
            File(dir, "config.json").writeText("{}")
            assertFalse("config.json alone must not satisfy isModelReady",
                ModelProvisioning.isModelReady(dir))
        } finally {
            dir.deleteRecursively()
        }
    }

    @Test fun `isModelReady returns true when all 10 required files present`() {
        val dir = createTempDir()
        try {
            ModelProvisioning.REQUIRED_MODEL_FILES.forEach { name ->
                File(dir, name).writeText("fake_$name")
            }
            assertTrue("All required files present — isModelReady should be true",
                ModelProvisioning.isModelReady(dir))
        } finally {
            dir.deleteRecursively()
        }
    }

    @Test fun `missingFiles returns all when directory is empty`() {
        val dir = createTempDir()
        try {
            val missing = ModelProvisioning.missingFiles(dir)
            assertEquals(ModelProvisioning.REQUIRED_MODEL_FILES.size, missing.size)
        } finally {
            dir.deleteRecursively()
        }
    }

    @Test fun `missingFiles returns only the absent files`() {
        val dir = createTempDir()
        try {
            ModelProvisioning.REQUIRED_MODEL_FILES
                .filter { it != "visual.mnn" }
                .forEach { File(dir, it).writeText("fake") }
            val missing = ModelProvisioning.missingFiles(dir)
            assertEquals(listOf("visual.mnn"), missing)
        } finally {
            dir.deleteRecursively()
        }
    }

    @Test fun `missingFiles returns empty list when all files present`() {
        val dir = createTempDir()
        try {
            ModelProvisioning.REQUIRED_MODEL_FILES.forEach { File(dir, it).writeText("fake") }
            assertTrue(ModelProvisioning.missingFiles(dir).isEmpty())
        } finally {
            dir.deleteRecursively()
        }
    }

    // --- verifyModelChecksum tests ---

    @Test fun `verifyModelChecksum returns false when checksum file is absent`() {
        val dir = createTempDir()
        try {
            File(dir, "llm.mnn").writeText("model_data")
            // checksum.sha256 intentionally not created
            assertFalse("Missing checksum.sha256 must return false",
                ModelProvisioning.verifyModelChecksum(dir))
        } finally {
            dir.deleteRecursively()
        }
    }

    @Test fun `verifyModelChecksum returns false when llm_mnn is absent`() {
        val dir = createTempDir()
        try {
            val data = "fake_model_bytes"
            val hash = ModelProvisioning.sha256(data.toByteArray())
            File(dir, "checksum.sha256").writeText(hash)
            // llm.mnn intentionally not created
            assertFalse("Missing llm.mnn must return false",
                ModelProvisioning.verifyModelChecksum(dir))
        } finally {
            dir.deleteRecursively()
        }
    }

    @Test fun `verifyModelChecksum returns false when checksum file is blank`() {
        val dir = createTempDir()
        try {
            File(dir, "llm.mnn").writeText("model_data")
            File(dir, "checksum.sha256").writeText("   ") // blank — bypass not permitted
            assertFalse("Blank checksum.sha256 must return false — bypass not permitted on Pad branch",
                ModelProvisioning.verifyModelChecksum(dir))
        } finally {
            dir.deleteRecursively()
        }
    }

    @Test fun `verifyModelChecksum returns false when hash mismatches`() {
        val dir = createTempDir()
        try {
            File(dir, "llm.mnn").writeText("model_data")
            File(dir, "checksum.sha256").writeText(
                "0000000000000000000000000000000000000000000000000000000000000000"
            )
            assertFalse("Mismatched hash must return false — model rejected",
                ModelProvisioning.verifyModelChecksum(dir))
        } finally {
            dir.deleteRecursively()
        }
    }

    @Test fun `verifyModelChecksum returns true when hash matches`() {
        val dir = createTempDir()
        try {
            val content = "valid_model_bytes_for_checksum_test"
            File(dir, "llm.mnn").writeBytes(content.toByteArray())
            val correctHash = ModelProvisioning.sha256(content.toByteArray())
            File(dir, "checksum.sha256").writeText(correctHash)
            assertTrue("Correct hash must return true — model accepted",
                ModelProvisioning.verifyModelChecksum(dir))
        } finally {
            dir.deleteRecursively()
        }
    }
}
