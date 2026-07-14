package com.giraffetechnology.qc.i18n

import com.giraffetechnology.qc.contracts.GiraffeLanguageSkill
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Holds the Pad's active language and exposes a live [GiraffeLanguageSkill] that
 * every screen binds to. The initial locale is resolved once from the device
 * language ([deviceLanguageTags]) with English fallback; an explicit operator
 * selection via [select] takes precedence from then on (S5 §3.3).
 *
 * Framework-free so it is unit-testable: MainActivity supplies the real device
 * tags from `Resources.configuration.locales`.
 */
class LanguageController(
    deviceLanguageTags: List<String>,
    initialSelection: String? = null,
    private val onSelectionChanged: (String) -> Unit = {},
) {
    private val _locale = MutableStateFlow(
        LanguageResolver.resolve(initialSelection, deviceLanguageTags)
    )
    val locale: StateFlow<String> = _locale.asStateFlow()

    private val _skill = MutableStateFlow(PadLanguageCatalog.skillFor(_locale.value))
    /** Active language skill — recomposition source for all localized screens. */
    val skill: StateFlow<GiraffeLanguageSkill> = _skill.asStateFlow()

    /** The locales the operator can pick from, in display order. */
    val supportedLocales: List<String> get() = LanguageResolver.SUPPORTED_LOCALES

    /**
     * Explicit operator selection. Ignored if [tag] is not a supported locale so
     * the UI can never land on an unrenderable language.
     */
    fun select(tag: String) {
        val normalized = LanguageResolver.normalize(tag) ?: return
        _locale.value = normalized
        _skill.value = PadLanguageCatalog.skillFor(normalized)
        onSelectionChanged(normalized)
    }
}
