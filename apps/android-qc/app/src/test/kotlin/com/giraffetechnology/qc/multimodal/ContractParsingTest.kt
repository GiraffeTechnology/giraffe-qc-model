package com.giraffetechnology.qc.multimodal

import org.junit.Assert.*
import org.junit.Test

class ContractParsingTest {

    @Test
    fun `contract version matches expected value`() {
        assertEquals("multimodal-qc-v1", SharedQcContract.QC_CONTRACT_VERSION)
    }

    @Test
    fun `normalizeResult returns pass unchanged`() {
        assertEquals("pass", SharedQcContract.normalizeResult("pass"))
    }

    @Test
    fun `normalizeResult returns fail unchanged`() {
        assertEquals("fail", SharedQcContract.normalizeResult("fail"))
    }

    @Test
    fun `normalizeResult returns review_required unchanged`() {
        assertEquals("review_required", SharedQcContract.normalizeResult("review_required"))
    }

    @Test
    fun `normalizeResult maps unknown values to review_required`() {
        // Forbidden values must never pass through normalisation
        for (forbidden in listOf("ok", "ng", "unknown", "needs_fix", "good", "bad", "", "PASS")) {
            assertEquals(
                "Expected review_required for forbidden value: $forbidden",
                "review_required",
                SharedQcContract.normalizeResult(forbidden),
            )
        }
    }

    @Test
    fun `normalizeResult maps null to review_required`() {
        assertEquals("review_required", SharedQcContract.normalizeResult(null))
    }

    @Test
    fun `isValidResult accepts canonical values`() {
        assertTrue(SharedQcContract.isValidResult("pass"))
        assertTrue(SharedQcContract.isValidResult("fail"))
        assertTrue(SharedQcContract.isValidResult("review_required"))
    }

    @Test
    fun `isValidResult rejects forbidden values`() {
        for (forbidden in listOf("ok", "ng", "unknown", "needs_fix", "good", "bad", "")) {
            assertFalse(
                "Expected isValidResult=false for: $forbidden",
                SharedQcContract.isValidResult(forbidden),
            )
        }
    }

    @Test
    fun `VALID_RESULTS contains exactly the three canonical values`() {
        assertEquals(
            setOf("pass", "fail", "review_required"),
            SharedQcContract.VALID_RESULTS,
        )
    }
}
