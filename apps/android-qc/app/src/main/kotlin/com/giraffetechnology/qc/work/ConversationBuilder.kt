package com.giraffetechnology.qc.work

import com.giraffetechnology.qc.contracts.GiraffeLanguageSkill
import com.giraffetechnology.qc.readiness.PadReadinessView
import com.giraffetechnology.qc.sku.PadInspectionResult
import com.giraffetechnology.qc.sku.QcTask

/**
 * Builds the QC Work page conversation/inspection log (S6 §8.2 right-middle).
 *
 * Every method resolves its text through the [GiraffeLanguageSkill] seam, so the
 * log is fully localized and never carries a hard-coded string. The content set
 * matches §8.2: selected SKU, standard revision/bundle version, system
 * instructions, missing image/angle prompts, inspection progress, detection-point
 * results, warnings/errors, and operator messages.
 *
 * Pure logic (no Android/Compose) so it is unit-tested on the JVM.
 */
object ConversationBuilder {

    /** Opening entries shown when a task is selected and the work page loads. */
    fun sessionOpening(
        task: QcTask,
        readiness: PadReadinessView,
        skill: GiraffeLanguageSkill,
    ): List<ConversationEntry> = buildList {
        add(
            ConversationEntry(
                ConversationRole.SYSTEM,
                skill.t(
                    "pad.work.selected_sku",
                    mapOf("item" to task.sku.itemNumber, "name" to task.sku.name),
                ),
            )
        )
        // Standard revision + bundle version (carried into every submission).
        add(
            ConversationEntry(
                ConversationRole.SYSTEM,
                skill.t(
                    "pad.review.standard_revision",
                    mapOf("rev" to (task.activeStandardRevisionId ?: skill.t("pad.work.no_standard_selected"))),
                ),
            )
        )
        task.bundleVersion?.let { ver ->
            add(
                ConversationEntry(
                    ConversationRole.SYSTEM,
                    skill.t("pad.review.bundle_version", mapOf("ver" to ver)),
                )
            )
        }
        // Runtime readiness — exact §8.3 lines, never overclaiming.
        addAll(readinessEntries(readiness, skill))
        // What will be inspected.
        addAll(checkpointList(task, skill))
        add(ConversationEntry(ConversationRole.INSTRUCTION, skill.t("pad.work.instruction")))
    }

    /** Readiness lines (§8.3) as SYSTEM entries, in resolver order. */
    fun readinessEntries(
        readiness: PadReadinessView,
        skill: GiraffeLanguageSkill,
    ): List<ConversationEntry> =
        readiness.messageKeys.map { ConversationEntry(ConversationRole.SYSTEM, skill.t(it)) }

    /** Enumerate the detection points that will be inspected. */
    fun checkpointList(task: QcTask, skill: GiraffeLanguageSkill): List<ConversationEntry> =
        task.qcPoints.map { p ->
            ConversationEntry(
                ConversationRole.SYSTEM,
                skill.t("pad.work.checkpoint", mapOf("code" to p.qcPointCode, "name" to p.name)),
            )
        }

    /** Prompts for any required views not yet captured. */
    fun missingViewPrompts(
        missingViews: List<String>,
        skill: GiraffeLanguageSkill,
    ): List<ConversationEntry> =
        missingViews.map { view ->
            ConversationEntry(
                ConversationRole.WARNING,
                skill.t("pad.work.missing_view", mapOf("view" to view)),
            )
        }

    fun progress(done: Int, total: Int, skill: GiraffeLanguageSkill): ConversationEntry =
        ConversationEntry(
            ConversationRole.PROGRESS,
            skill.t("pad.work.progress", mapOf("done" to done.toString(), "total" to total.toString())),
        )

    fun detectionResults(
        outcomes: List<DetectionOutcome>,
        skill: GiraffeLanguageSkill,
    ): List<ConversationEntry> =
        outcomes.map { o ->
            ConversationEntry(
                ConversationRole.DETECTION_RESULT,
                skill.t(
                    "pad.work.detection_result",
                    mapOf("code" to o.pointCode, "verdict" to skill.t(verdictKey(o.verdict)), "reason" to o.reason),
                ),
            )
        }

    /** Overall inspection summary. Non-terminal verdicts render as a warning. */
    fun resultSummary(result: PadInspectionResult, skill: GiraffeLanguageSkill): ConversationEntry {
        val verdictLabel = when (result.overallResult) {
            "ACCEPTED" -> skill.t("verdict.pass")
            "NOT_ACCEPTED" -> skill.t("verdict.fail")
            else -> skill.t("verdict.review_required")
        }
        val text = skill.t(
            "pad.work.result_overall",
            mapOf("verdict" to verdictLabel, "reason" to result.reason),
        )
        val role = if (result.overallResult == "ACCEPTED" || result.overallResult == "NOT_ACCEPTED") {
            ConversationRole.DETECTION_RESULT
        } else {
            ConversationRole.WARNING
        }
        return ConversationEntry(role, text)
    }

    fun operatorMessage(text: String): ConversationEntry =
        ConversationEntry(ConversationRole.OPERATOR, text)

    private fun verdictKey(verdict: String): String = when (verdict) {
        "pass" -> "verdict.pass"
        "fail" -> "verdict.fail"
        else -> "verdict.review_required"
    }
}
