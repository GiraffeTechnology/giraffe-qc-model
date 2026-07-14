package com.giraffetechnology.qc.i18n

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Pure fallback-priority tests: explicit selection > device language > English. */
class LanguageResolverTest {

    @Test fun `explicit selection wins over device language`() {
        assertEquals("ja", LanguageResolver.resolve("ja", listOf("zh-Hans-CN", "en-US")))
    }

    @Test fun `device language used when no explicit selection`() {
        assertEquals("zh-CN", LanguageResolver.resolve(null, listOf("zh-Hans-CN", "en-US")))
    }

    @Test fun `falls back to English when device language unsupported`() {
        assertEquals("en", LanguageResolver.resolve(null, listOf("fr-FR", "de-DE")))
    }

    @Test fun `falls back to English when nothing provided`() {
        assertEquals("en", LanguageResolver.resolve(null, emptyList()))
    }

    @Test fun `unsupported explicit selection falls through to device`() {
        assertEquals("ja", LanguageResolver.resolve("fr", listOf("ja-JP")))
    }

    @Test fun `normalize maps language subtag variants`() {
        assertEquals("zh-CN", LanguageResolver.normalize("zh"))
        assertEquals("zh-CN", LanguageResolver.normalize("zh-Hans-CN"))
        assertEquals("zh-CN", LanguageResolver.normalize("zh_CN"))
        assertEquals("ja", LanguageResolver.normalize("ja-JP"))
        assertEquals("en", LanguageResolver.normalize("en-GB"))
        assertNull(LanguageResolver.normalize("ko"))
        assertNull(LanguageResolver.normalize(null))
        assertNull(LanguageResolver.normalize(""))
    }

    @Test fun `supported locales are the three product locales`() {
        assertEquals(listOf("en", "zh-CN", "ja"), LanguageResolver.SUPPORTED_LOCALES)
        assertTrue(LanguageResolver.isSupported("zh-CN"))
        assertFalse(LanguageResolver.isSupported("ko"))
    }

    @Test fun `controller publishes normalized explicit choices for persistence`() {
        val persisted = mutableListOf<String>()
        val controller = LanguageController(
            deviceLanguageTags = listOf("en-US"),
            onSelectionChanged = persisted::add,
        )

        controller.select("zh-Hans-CN")

        assertEquals("zh-CN", controller.locale.value)
        assertEquals(listOf("zh-CN"), persisted)
    }

    @Test fun `controller restores a persisted choice before device language`() {
        val controller = LanguageController(
            deviceLanguageTags = listOf("zh-Hans-CN"),
            initialSelection = "ja-JP",
        )

        assertEquals("ja", controller.locale.value)
        assertEquals("ja", controller.skill.value.locale)
    }
}
