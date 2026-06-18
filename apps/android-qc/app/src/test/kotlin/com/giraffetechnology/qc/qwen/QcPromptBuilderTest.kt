package com.giraffetechnology.qc.qwen

import org.junit.Assert.*
import org.junit.Test

class QcPromptBuilderTest {

    private val stdPhotos = listOf(
        StandardPhotoInput("STD-1", "/fake/std_front.jpg", "front"),
        StandardPhotoInput("STD-2", "/fake/std_back.jpg",  "back"),
    )
    private val capPhoto  = CapturePhotoInput("CAP-1", "/fake/cap.jpg")
    private val qcPoints  = listOf(
        QcPointInput("QC-01", "color_check",  "Color",  "Surface color must match standard"),
        QcPointInput("QC-02", "border_check", "Border", "Border must be intact"),
        QcPointInput("QC-03", "defect_check", "Defect", "No surface defects allowed"),
    )
    private val schema = """{"overall_result":"pass|fail|review_required"}"""

    @Test fun `prompt contains version string`() {
        val p = QcPromptBuilder.build(stdPhotos, capPhoto, qcPoints, schema)
        assertTrue("Prompt must embed version string", p.contains("qwen-qc-v1"))
    }

    @Test fun `prompt contains all QC point IDs`() {
        val p = QcPromptBuilder.build(stdPhotos, capPhoto, qcPoints, schema)
        qcPoints.forEach { point ->
            assertTrue("Prompt must list ${point.qcPointId}", p.contains(point.qcPointId))
        }
    }

    @Test fun `prompt contains all QC point names`() {
        val p = QcPromptBuilder.build(stdPhotos, capPhoto, qcPoints, schema)
        qcPoints.forEach { point ->
            assertTrue("Prompt must include name: ${point.name}", p.contains(point.name))
        }
    }

    @Test fun `prompt contains all QC point descriptions`() {
        val p = QcPromptBuilder.build(stdPhotos, capPhoto, qcPoints, schema)
        qcPoints.forEach { point ->
            assertTrue("Prompt must include desc: ${point.description}", p.contains(point.description))
        }
    }

    @Test fun `prompt contains schema example`() {
        val p = QcPromptBuilder.build(stdPhotos, capPhoto, qcPoints, schema)
        assertTrue("Prompt must embed schema JSON", p.contains(schema))
    }

    @Test fun `prompt references captured photo path`() {
        val p = QcPromptBuilder.build(stdPhotos, capPhoto, qcPoints, schema)
        assertTrue("Prompt must reference capture path", p.contains(capPhoto.localPath))
    }

    @Test fun `prompt references all standard photo paths`() {
        val p = QcPromptBuilder.build(stdPhotos, capPhoto, qcPoints, schema)
        stdPhotos.forEach { std ->
            assertTrue("Prompt must reference std photo ${std.photoId}", p.contains(std.localPath))
        }
    }

    @Test fun `prompt instructs JSON-only output`() {
        val p = QcPromptBuilder.build(stdPhotos, capPhoto, qcPoints, schema)
        assertTrue("Prompt must ask for JSON output", p.contains("JSON") || p.contains("json"))
    }

    @Test fun `empty qc points still produces valid prompt`() {
        val p = QcPromptBuilder.build(stdPhotos, capPhoto, emptyList(), schema)
        assertTrue(p.isNotBlank())
        assertTrue(p.contains("qwen-qc-v1"))
    }

    @Test fun `single standard photo prompt is valid`() {
        val p = QcPromptBuilder.build(
            listOf(StandardPhotoInput("STD-1", "/fake/only.jpg", "front")),
            capPhoto, qcPoints, schema,
        )
        assertTrue(p.contains("qwen-qc-v1"))
        assertTrue(p.contains("QC-01"))
    }
}
