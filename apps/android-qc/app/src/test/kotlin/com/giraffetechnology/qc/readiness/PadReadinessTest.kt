package com.giraffetechnology.qc.readiness

import com.giraffetechnology.qc.sku.MnnRuntimeState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Runtime-readiness resolver: exact states + fail-closed (never overclaim). */
class PadReadinessTest {

    private fun inputs(
        native: Boolean = true,
        model: Boolean = true,
        verified: Boolean = true,
        standard: Boolean = true,
        sku: Boolean = true,
        online: Boolean = true,
    ) = PadReadinessInputs(native, model, verified, standard, sku, online)

    @Test fun `native not ready gives local-runtime-not-ready and cannot claim model ready`() {
        val v = PadReadiness.evaluate(inputs(native = false))
        assertEquals(PadReadiness.KEY_LOCAL_RUNTIME_NOT_READY, v.runtimeKey)
        assertFalse(v.canClaimModelReady)
    }

    @Test fun `verified model-loaded runtime reports Model ready`() {
        val v = PadReadiness.evaluate(inputs(verified = true, model = true))
        assertEquals(PadReadiness.KEY_MODEL_READY, v.runtimeKey)
        assertTrue(v.canClaimModelReady)
    }

    @Test fun `unverified inference never claims Model ready even with model loaded (PR30 fail-closed)`() {
        val v = PadReadiness.evaluate(inputs(model = true, verified = false))
        assertEquals(PadReadiness.KEY_MNN_NATIVE_READY_MODEL_PENDING, v.runtimeKey)
        assertFalse(v.canClaimModelReady)
    }

    @Test fun `native ready but model not loaded is model pending`() {
        val v = PadReadiness.evaluate(inputs(model = false, verified = true))
        assertEquals(PadReadiness.KEY_MNN_NATIVE_READY_MODEL_PENDING, v.runtimeKey)
    }

    @Test fun `connectivity maps to online and offline`() {
        assertEquals(PadReadiness.KEY_ONLINE, PadReadiness.evaluate(inputs(online = true)).connectivityKey)
        assertEquals(PadReadiness.KEY_OFFLINE, PadReadiness.evaluate(inputs(online = false)).connectivityKey)
    }

    @Test fun `selection and standard gaps appear in message keys`() {
        val v = PadReadiness.evaluate(inputs(sku = false, standard = false))
        assertTrue(v.messageKeys.contains(PadReadiness.KEY_NO_SKU_SELECTED))
        assertTrue(v.messageKeys.contains(PadReadiness.KEY_NO_STANDARD_INSTALLED))
    }

    @Test fun `no gaps means only runtime and connectivity lines`() {
        val v = PadReadiness.evaluate(inputs())
        assertEquals(listOf(PadReadiness.KEY_MODEL_READY, PadReadiness.KEY_ONLINE), v.messageKeys)
    }

    @Test fun `fromRuntimeState maps the three runtime states`() {
        assertEquals(
            PadReadiness.KEY_LOCAL_RUNTIME_NOT_READY,
            PadReadiness.fromRuntimeState(MnnRuntimeState.NotReady, true, true, true, true).runtimeKey,
        )
        assertEquals(
            PadReadiness.KEY_MNN_NATIVE_READY_MODEL_PENDING,
            PadReadiness.fromRuntimeState(MnnRuntimeState.Loading, true, true, true, true).runtimeKey,
        )
        assertEquals(
            PadReadiness.KEY_MODEL_READY,
            PadReadiness.fromRuntimeState(MnnRuntimeState.Ready, true, true, true, true).runtimeKey,
        )
        // Ready but unverified stays pending (fail-closed).
        assertEquals(
            PadReadiness.KEY_MNN_NATIVE_READY_MODEL_PENDING,
            PadReadiness.fromRuntimeState(MnnRuntimeState.Ready, false, true, true, true).runtimeKey,
        )
    }
}
