package com.giraffetechnology.qc.qwen

import org.junit.Assert.assertFalse
import org.junit.Test

/**
 * MnnRuntimeLoader is gated so it never overstates readiness while JNI inference
 * is still scaffolded. Constructing the loader requires an Android Context, so
 * this guards the contract that actually controls the Ready transition: until
 * [MnnRuntimeLoader.JNI_INFERENCE_WIRED] is true, loadModel() returns a 0L
 * native pointer and the runtime stays NotReady (a present model.mnn plus loaded
 * .so libs is NOT proof the model can run).
 *
 * If someone flips this flag without wiring nativeLoadModel/nativeRunInference,
 * this test fails — a deliberate tripwire before physical Pad deployment.
 */
class MnnRuntimeLoaderTest {

    @Test
    fun `JNI inference is not wired so runtime cannot report Ready`() {
        assertFalse(
            "Scaffold build must not claim JNI inference is wired",
            MnnRuntimeLoader.JNI_INFERENCE_WIRED,
        )
    }
}
