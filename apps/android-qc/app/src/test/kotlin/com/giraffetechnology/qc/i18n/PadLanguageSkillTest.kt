package com.giraffetechnology.qc.i18n

import com.giraffetechnology.qc.operator.OperatorTaskSelectionController
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** i18n skill fail-soft behaviour + exact spec-string coverage. */
class PadLanguageSkillTest {

    @Test fun `unknown key returns the key verbatim (fail-soft)`() {
        val skill = PadLanguageCatalog.skillFor("en")
        assertEquals("no.such.key", skill.t("no.such.key"))
        assertFalse(skill.has("no.such.key"))
    }

    @Test fun `placeholder substitution uses brace convention`() {
        val skill = PadLanguageCatalog.skillFor("en")
        assertEquals("3 result(s) pending upload", skill.t("pad.sync.pending", mapOf("count" to "3")))
    }

    @Test fun `missing translation falls back to English before the key`() {
        // A zh-CN table that omits a key still yields readable English, not the raw key.
        val skill = InMemoryLanguageSkill(
            locale = "zh-CN",
            table = emptyMap(),
            fallbackTable = PadLanguageCatalog.EN,
        )
        assertEquals("Model ready", skill.t("readiness.model_ready"))
    }

    @Test fun `skillFor normalizes device-style tags`() {
        assertEquals("zh-CN", PadLanguageCatalog.skillFor("zh-Hans-CN").locale)
        assertEquals("en", PadLanguageCatalog.skillFor("unsupported").locale)
    }

    // ── exact spec strings (S5 §8.1, S6 §8.3) — must not drift ──────────────

    @Test fun `S5 task-selection messages are exact`() {
        val en = PadLanguageCatalog.EN
        assertEquals(
            "No standards installed. Please ask Administrator to publish or sync a standard bundle.",
            en[OperatorTaskSelectionController.KEY_NO_STANDARDS],
        )
        assertEquals(
            "SKU not found in installed standards. Please sync with Administrator.",
            en[OperatorTaskSelectionController.KEY_SKU_NOT_FOUND],
        )
    }

    @Test fun `S6 runtime-readiness messages are exact`() {
        val en = PadLanguageCatalog.EN
        assertEquals("MNN native ready; model pending", en["readiness.mnn_native_ready_model_pending"])
        assertEquals("Model ready", en["readiness.model_ready"])
        assertEquals("Local runtime not ready", en["readiness.local_runtime_not_ready"])
        assertEquals("No standard installed", en["readiness.no_standard_installed"])
        assertEquals("No SKU selected", en["readiness.no_sku_selected"])
        assertEquals("Offline", en["readiness.offline"])
        assertEquals("Online", en["readiness.online"])
    }

    @Test fun `all three locales define the two exact-message keys`() {
        listOf(PadLanguageCatalog.EN, PadLanguageCatalog.ZH_CN, PadLanguageCatalog.JA).forEach { table ->
            assertTrue(table.containsKey(OperatorTaskSelectionController.KEY_NO_STANDARDS))
            assertTrue(table.containsKey(OperatorTaskSelectionController.KEY_SKU_NOT_FOUND))
        }
    }

    @Test fun `all product locales define the complete English key set`() {
        assertEquals(PadLanguageCatalog.EN.keys, PadLanguageCatalog.ZH_CN.keys)
        assertEquals(PadLanguageCatalog.EN.keys, PadLanguageCatalog.JA.keys)
    }
}
