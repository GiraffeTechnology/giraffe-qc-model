package com.giraffetechnology.qc.contracts

/**
 * Shared standard-lifecycle state model (PRD §10).
 *
 * Kotlin mirror of `contracts/state_model.py`. This is the single source of
 * truth for lifecycle state on the Android Pad. The [wire] value is the
 * canonical serialized form that appears in every API payload, bundle manifest,
 * and SQLite row — it MUST stay byte-for-byte identical to the Python enum
 * `value`. Display labels are localized through the i18n seam
 * (`GiraffeLanguageSkill`), never hard-coded; [i18nKey] gives the lookup key.
 *
 * S0 deliverable — do not edit downstream without coordinating both sides.
 */
enum class StandardState(val wire: String) {
    DRAFT("draft"),
    NEEDS_INFORMATION("needs_information"),
    READY_FOR_REVIEW("ready_for_review"),
    CONFIRMED("confirmed"),
    PUBLISHED("published"),
    INSTALLED_ON_PAD("installed_on_pad"),
    ACTIVE_INSPECTION("active_inspection"),
    NEEDS_REQUALIFICATION("needs_requalification");

    /** i18n key for the display label; see `contracts/i18n/en.json`. */
    val i18nKey: String get() = "state.$wire"

    companion object {
        private val byWire = entries.associateBy(StandardState::wire)

        /** Parse a wire value fail-closed: unknown strings return null. */
        fun fromWire(value: String): StandardState? = byWire[value]

        /**
         * Allowed forward transitions (PRD §10). Any pair not present is
         * rejected. Kept identical to `ALLOWED_TRANSITIONS` in state_model.py.
         */
        val allowedTransitions: Map<StandardState, Set<StandardState>> = mapOf(
            DRAFT to setOf(NEEDS_INFORMATION, READY_FOR_REVIEW),
            NEEDS_INFORMATION to setOf(DRAFT, READY_FOR_REVIEW),
            READY_FOR_REVIEW to setOf(CONFIRMED, NEEDS_INFORMATION),
            CONFIRMED to setOf(PUBLISHED, NEEDS_INFORMATION),
            PUBLISHED to setOf(INSTALLED_ON_PAD, NEEDS_REQUALIFICATION),
            INSTALLED_ON_PAD to setOf(ACTIVE_INSPECTION, NEEDS_REQUALIFICATION),
            ACTIVE_INSPECTION to setOf(NEEDS_REQUALIFICATION),
            NEEDS_REQUALIFICATION to setOf(DRAFT, READY_FOR_REVIEW),
        )

        fun canTransition(src: StandardState, dst: StandardState): Boolean =
            allowedTransitions[src]?.contains(dst) == true
    }
}
