package com.giraffetechnology.qc.contracts

/**
 * i18n adapter seam for `giraffe-language-skill` (PRD §11).
 *
 * S0 deliverable. Both Web and Android bind their UI text to THIS interface;
 * neither hard-codes a user-facing string. The English source strings are the
 * canonical key set in `contracts/i18n/en.json`; other locales provide the same
 * keys. Missing-key behaviour is fail-soft: return the key itself so a missing
 * translation is visible in QA but never crashes the Pad.
 *
 * The Web side binds the identical shape (see `contracts/CONTRACTS.md` §5 for
 * the Python `LanguageSkill` protocol). Keep method names and the placeholder
 * convention (`{name}`) identical across both bindings.
 */
interface GiraffeLanguageSkill {

    /** Active locale tag, e.g. "en", "zh-CN". */
    val locale: String

    /**
     * Resolve [key] for the active locale, substituting `{placeholder}` tokens
     * from [params]. Returns [key] verbatim if the key is unknown (fail-soft).
     */
    fun t(key: String, params: Map<String, String> = emptyMap()): String

    /** True if [key] exists for the active locale. */
    fun has(key: String): Boolean
}
