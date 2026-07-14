package com.giraffetechnology.qc.i18n

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AndroidBrandAssetTest {
    @Test fun `welcome uses shared brand asset instead of emoji`() {
        val repoRoot = generateSequence(File(".").canonicalFile) { it.parentFile }
            .first { File(it, "src/web/static/giraffe-qc-model-icon.png").isFile }
        val welcome = File(
            repoRoot,
            "apps/android-qc/app/src/main/kotlin/com/giraffetechnology/qc/ui/WelcomeScreen.kt",
        ).readText()
        val sharedIcon = File(repoRoot, "src/web/static/giraffe-qc-model-icon.png")

        assertFalse(welcome.contains("🦒"))
        assertTrue(welcome.contains("giraffe-qc-model-icon.png"))
        assertTrue(sharedIcon.isFile)
    }
}
