package com.giraffetechnology.qc.i18n

/**
 * Pure locale-resolution logic for the Pad, shared with the Web `giraffe-language-skill`
 * adapter seam (S0 §11). Fallback priority is identical on both platforms:
 *
 *   explicit selection  >  device language  >  English
 *
 * Extracted from any Android framework type so it can be unit-tested on the JVM.
 */
object LanguageResolver {

    const val DEFAULT_LOCALE = "en"

    /** The three locales the product ships (PRD §11): English, Simplified Chinese, Japanese. */
    val SUPPORTED_LOCALES: List<String> = listOf("en", "zh-CN", "ja")

    /**
     * Resolve the active locale tag.
     *
     * @param explicitSelection an operator-chosen locale tag, or null if none.
     * @param deviceLanguageTags device locale tags in preference order (e.g.
     *   `["zh-Hans-CN", "en-US"]`), as reported by the platform.
     *
     * A selection or device tag is honoured only if it maps to a supported
     * locale; otherwise resolution falls through to the next source and finally
     * to [DEFAULT_LOCALE]. Never returns an unsupported tag.
     */
    fun resolve(explicitSelection: String?, deviceLanguageTags: List<String>): String {
        normalize(explicitSelection)?.let { return it }
        for (tag in deviceLanguageTags) {
            normalize(tag)?.let { return it }
        }
        return DEFAULT_LOCALE
    }

    /**
     * Map an arbitrary BCP-47-ish tag onto one of [SUPPORTED_LOCALES], or null if
     * unsupported. Matches on the primary language subtag so device variants such
     * as `zh-Hans-CN`, `zh-CN`, or `zh` all resolve to `zh-CN`.
     */
    fun normalize(tag: String?): String? {
        if (tag.isNullOrBlank()) return null
        val lower = tag.trim().lowercase().replace('_', '-')
        // Exact supported match first (case-insensitive).
        SUPPORTED_LOCALES.firstOrNull { it.lowercase() == lower }?.let { return it }
        return when (lower.substringBefore('-')) {
            "en" -> "en"
            "zh" -> "zh-CN"
            "ja" -> "ja"
            else -> null
        }
    }

    fun isSupported(tag: String?): Boolean = normalize(tag) != null
}
