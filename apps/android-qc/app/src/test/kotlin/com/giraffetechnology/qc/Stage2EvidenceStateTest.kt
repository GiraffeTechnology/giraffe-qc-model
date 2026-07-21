package com.giraffetechnology.qc

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class Stage2EvidenceStateTest {
    private val required = listOf(
        "simulator-ready",
        "simulated-capture",
        "cv-success",
        "cv-anomaly",
        "simulator-unavailable",
        "refresh-retry",
    )

    @Test fun `all six acceptance states are explicit and never production labeled`() {
        required.forEach { id -> assertEquals(id, stage2EvidenceState(id).id) }
        assertEquals("NON-PRODUCTION MOCK", STAGE2_MOCK_LABEL)
    }

    @Test fun `anomaly and unavailable states fail closed`() {
        assertTrue(stage2EvidenceState("cv-anomaly").failClosed)
        assertTrue(stage2EvidenceState("simulator-unavailable").failClosed)
        assertFalse(stage2EvidenceState("cv-success").failClosed)
    }

    @Test fun `recovery retains exactly one result`() {
        val recovered = stage2EvidenceState("refresh-retry")
        assertEquals(1, recovered.resultCount)
        assertTrue(recovered.detail.contains("no duplicate", ignoreCase = true))
    }
}
