package com.giraffetechnology.qc.work

/**
 * Author/kind of a conversation entry (S6 §3.4). Drives the bubble
 * alignment/color rules, shared with the Web spec: OPERATOR bubbles are
 * right-aligned; every system-side kind is left-aligned, with WARNING/ERROR
 * given distinct emphasis.
 */
enum class ConversationRole {
    /** System status: selected SKU, standard revision/bundle, readiness. */
    SYSTEM,
    /** A system instruction to the operator (e.g. how/what to capture). */
    INSTRUCTION,
    /** Inspection progress updates. */
    PROGRESS,
    /** A per-detection-point result line. */
    DETECTION_RESULT,
    /** A non-blocking warning (missing view/angle, review_required, MNN pending). */
    WARNING,
    /** A blocking error. */
    ERROR,
    /** A message typed/spoken by the operator. */
    OPERATOR,
}

/**
 * One entry in the QC Work page conversation/inspection log. [text] is already
 * localized (the builder resolves it through the language skill) so the log is a
 * flat, render-ready list.
 */
data class ConversationEntry(
    val role: ConversationRole,
    val text: String,
)

/** A resolved per-detection-point outcome, for the conversation log. */
data class DetectionOutcome(
    val pointCode: String,
    val name: String,
    /** Verdict wire value: "pass" | "fail" | "review_required". */
    val verdict: String,
    val reason: String,
)
