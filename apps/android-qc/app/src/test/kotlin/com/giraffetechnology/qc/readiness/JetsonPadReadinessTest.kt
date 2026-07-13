package com.giraffetechnology.qc.readiness

import com.giraffetechnology.qc.sku.MnnRuntimeState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Jetson-flavored readiness resolver: same fail-closed shape as PadReadinessTest, Jetson wording. */
class JetsonPadReadinessTest {

    private fun inputs(
        reachable: Boolean = true,
        model: Boolean = true,
        verified: Boolean = true,
        standard: Boolean = true,
        sku: Boolean = true,
        online: Boolean = true,
    ) = PadReadinessInputs(reachable, model, verified, standard, sku, online)

    @Test fun `unreachable gives jetson-unreachable and cannot claim model ready`() {
        val v = JetsonPadReadiness.evaluate(inputs(reachable = false))
        assertEquals(JetsonPadReadiness.KEY_JETSON_UNREACHABLE, v.runtimeKey)
        assertFalse(v.canClaimModelReady)
    }

    @Test fun `verified model-loaded runtime reports Model ready`() {
        val v = JetsonPadReadiness.evaluate(inputs(verified = true, model = true))
        assertEquals(PadReadiness.KEY_MODEL_READY, v.runtimeKey)
        assertTrue(v.canClaimModelReady)
    }

    @Test fun `unverified inference never claims Model ready even with model loaded (PR30 fail-closed)`() {
        val v = JetsonPadReadiness.evaluate(inputs(model = true, verified = false))
        assertEquals(JetsonPadReadiness.KEY_JETSON_CONNECTING, v.runtimeKey)
        assertFalse(v.canClaimModelReady)
    }

    @Test fun `reachable but model not loaded is jetson connecting`() {
        val v = JetsonPadReadiness.evaluate(inputs(model = false, verified = true))
        assertEquals(JetsonPadReadiness.KEY_JETSON_CONNECTING, v.runtimeKey)
    }

    @Test fun `selection and standard gaps appear in message keys`() {
        val v = JetsonPadReadiness.evaluate(inputs(sku = false, standard = false))
        assertTrue(v.messageKeys.contains(PadReadiness.KEY_NO_SKU_SELECTED))
        assertTrue(v.messageKeys.contains(PadReadiness.KEY_NO_STANDARD_INSTALLED))
    }

    @Test fun `fromRuntimeState maps the three runtime states to jetson wording`() {
        assertEquals(
            JetsonPadReadiness.KEY_JETSON_UNREACHABLE,
            JetsonPadReadiness.fromRuntimeState(MnnRuntimeState.NotReady, true, true, true, true).runtimeKey,
        )
        assertEquals(
            JetsonPadReadiness.KEY_JETSON_CONNECTING,
            JetsonPadReadiness.fromRuntimeState(MnnRuntimeState.Loading, true, true, true, true).runtimeKey,
        )
        assertEquals(
            PadReadiness.KEY_MODEL_READY,
            JetsonPadReadiness.fromRuntimeState(MnnRuntimeState.Ready, true, true, true, true).runtimeKey,
        )
        // Ready but unverified stays pending (fail-closed) -- same PR30 rule as legacy MNN.
        assertEquals(
            JetsonPadReadiness.KEY_JETSON_CONNECTING,
            JetsonPadReadiness.fromRuntimeState(MnnRuntimeState.Ready, false, true, true, true).runtimeKey,
        )
    }
}
