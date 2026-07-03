package com.giraffetechnology.qc.i18n

import com.giraffetechnology.qc.contracts.GiraffeLanguageSkill

/**
 * Map-backed [GiraffeLanguageSkill]. Holds the string table for a single active
 * [locale] plus the English table as the fail-soft fallback source.
 *
 * Resolution order for a key:
 *   1. active-locale table
 *   2. English table (so a not-yet-translated key still shows readable English)
 *   3. the key itself, verbatim (fail-soft — never crashes, visible in QA)
 *
 * Placeholders use the `{name}` convention, identical to the Web binding.
 */
class InMemoryLanguageSkill(
    override val locale: String,
    private val table: Map<String, String>,
    private val fallbackTable: Map<String, String>,
) : GiraffeLanguageSkill {

    override fun t(key: String, params: Map<String, String>): String {
        val template = table[key] ?: fallbackTable[key] ?: key
        return substitute(template, params)
    }

    override fun has(key: String): Boolean = table.containsKey(key)

    private fun substitute(template: String, params: Map<String, String>): String {
        if (params.isEmpty() || !template.contains('{')) return template
        var out = template
        for ((name, value) in params) {
            out = out.replace("{$name}", value)
        }
        return out
    }
}
