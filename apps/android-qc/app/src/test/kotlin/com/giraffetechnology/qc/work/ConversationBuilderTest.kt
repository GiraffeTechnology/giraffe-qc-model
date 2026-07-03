package com.giraffetechnology.qc.work

import com.giraffetechnology.qc.i18n.PadLanguageCatalog
import com.giraffetechnology.qc.qwen.QcPointInput
import com.giraffetechnology.qc.qwen.StandardPhotoInput
import com.giraffetechnology.qc.readiness.PadReadiness
import com.giraffetechnology.qc.readiness.PadReadinessInputs
import com.giraffetechnology.qc.sku.PadInspectionResult
import com.giraffetechnology.qc.sku.QcTask
import com.giraffetechnology.qc.sku.Sku
import com.giraffetechnology.qc.sku.SkuResolutionMethod
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The conversation/inspection log content set (§8.2) is built and localized. */
class ConversationBuilderTest {

    private val skill = PadLanguageCatalog.skillFor("en")

    private val task = QcTask(
        sku = Sku(
            id = "sku-1",
            itemNumber = "ITEM-FLOWER-001",
            name = "Artificial Flower A",
            activeStandardRevisionId = "rev-7",
            standardPhotos = listOf(StandardPhotoInput("0", "/sdcard/std/front.jpg", "front")),
            detectionPoints = listOf(
                QcPointInput("center_alignment", "center_alignment", "Center alignment", "aligned"),
            ),
        ),
        confirmedByUser = true,
        resolvedBy = SkuResolutionMethod.MANUAL_ITEM_NUMBER,
        activeStandardRevisionId = "rev-7",
        bundleVersion = "12",
    )

    private val readiness = PadReadiness.evaluate(
        PadReadinessInputs(
            mnnNativeReady = false, modelLoaded = false, inferenceVerified = false,
            standardInstalled = true, skuSelected = true, online = false,
        )
    )

    @Test fun `session opening carries SKU, standard revision, bundle version and readiness`() {
        val entries = ConversationBuilder.sessionOpening(task, readiness, skill)
        val text = entries.joinToString("\n") { it.text }
        assertTrue(text.contains("ITEM-FLOWER-001"))
        assertTrue(text.contains("Artificial Flower A"))
        assertTrue(text.contains("rev-7"))
        assertTrue(text.contains("12"))
        // Readiness lines are the exact §8.3 strings (fail-closed states here).
        assertTrue(text.contains("Local runtime not ready"))
        assertTrue(text.contains("Offline"))
        // Checkpoints are enumerated.
        assertTrue(text.contains("center_alignment"))
    }

    @Test fun `accepted result renders as a detection-result line with Pass`() {
        val entry = ConversationBuilder.resultSummary(
            PadInspectionResult("ACCEPTED", "looks good", "Qwen3-VL-2B-Instruct-MNN", true, false, "/x.jpg"),
            skill,
        )
        assertEquals(ConversationRole.DETECTION_RESULT, entry.role)
        assertTrue(entry.text.contains("Pass"))
    }

    @Test fun `review-required result renders as a warning`() {
        val entry = ConversationBuilder.resultSummary(
            PadInspectionResult("MNN_PENDING", "runtime not ready", "Qwen3-VL-2B-Instruct-MNN", true, false, null),
            skill,
        )
        assertEquals(ConversationRole.WARNING, entry.role)
    }

    @Test fun `operator message is right-aligned OPERATOR role`() {
        assertEquals(ConversationRole.OPERATOR, ConversationBuilder.operatorMessage("hello").role)
    }

    @Test fun `missing-view prompts are warnings naming the view`() {
        val entries = ConversationBuilder.missingViewPrompts(listOf("back"), skill)
        assertEquals(ConversationRole.WARNING, entries.single().role)
        assertTrue(entries.single().text.contains("back"))
    }

    @Test fun `detection results render code and localized verdict`() {
        val entries = ConversationBuilder.detectionResults(
            listOf(DetectionOutcome("center_alignment", "Center", "fail", "off by 3mm")),
            skill,
        )
        assertEquals(ConversationRole.DETECTION_RESULT, entries.single().role)
        assertTrue(entries.single().text.contains("center_alignment"))
        assertTrue(entries.single().text.contains("Fail"))
    }
}
