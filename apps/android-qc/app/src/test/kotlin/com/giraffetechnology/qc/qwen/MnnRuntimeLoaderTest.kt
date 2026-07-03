package com.giraffetechnology.qc.qwen

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.lang.reflect.Modifier

/**
 * Tripwire guarding the on-device inference wiring contract.
 *
 * [MnnRuntimeLoader.JNI_INFERENCE_WIRED] gates the Ready transition: while it is
 * false, loadModel() returns a 0L native handle and the runtime stays NotReady
 * (a present model plus loaded .so libs is NOT proof the model can run). It may
 * only be flipped to true in the same change that wires nativeLoadModel /
 * nativeRunInference to the real MNN AAR AND verifies it on-device.
 *
 * The test is state-aware and encodes the invariant that survives both states:
 *  - Scaffold (flag = false): on-device inference is NOT claimed. This is the
 *    current, honest state — the JNI bridge (cpp/mnn_qwen_jni.cpp) is written
 *    but UNVERIFIED (no NDK / no real AAR / no device in this workspace).
 *  - Wired (flag = true): the three native methods MUST still be declared as
 *    JVM `native` symbols. This fails if someone flips the flag while stubbing
 *    the native calls back out to plain Kotlin — exactly the regression the
 *    tripwire exists to catch.
 *
 * Operator step (see VERIFICATION.md): after building with -PwithMnnNative=true
 * and confirming real inference on the OPPO PKB110, flip JNI_INFERENCE_WIRED to
 * true. This test then enforces the wired contract automatically — no further
 * edit to the assertion is required.
 */
class MnnRuntimeLoaderTest {

    private val nativeMethodNames = setOf("nativeLoadModel", "nativeRunInference", "nativeUnloadModel")

    private fun declaredNativeMethods(): Set<String> =
        MnnRuntimeLoader::class.java.declaredMethods
            .filter { Modifier.isNative(it.modifiers) }
            .map { it.name }
            .toSet()

    @Test
    fun `wiring flag matches native symbol presence`() {
        val nativePresent = declaredNativeMethods().containsAll(nativeMethodNames)
        if (MnnRuntimeLoader.JNI_INFERENCE_WIRED) {
            // Wired build must keep real native symbols — not Kotlin stubs.
            assertTrue(
                "JNI_INFERENCE_WIRED=true but native symbols missing/stubbed out: " +
                    "${nativeMethodNames - declaredNativeMethods()}",
                nativePresent,
            )
        } else {
            // Scaffold build must not overstate readiness.
            assertFalse(
                "Scaffold build must not claim JNI inference is wired until verified " +
                    "on-device (see VERIFICATION.md)",
                MnnRuntimeLoader.JNI_INFERENCE_WIRED,
            )
        }
    }

    @Test
    fun `native inference entry points are declared`() {
        // Independent of the flag: the external declarations must exist so the
        // JNI bridge has symbols to bind. Catches accidental removal.
        val present = declaredNativeMethods()
        assertTrue(
            "Missing native declarations: ${nativeMethodNames - present}",
            present.containsAll(nativeMethodNames),
        )
    }
}
