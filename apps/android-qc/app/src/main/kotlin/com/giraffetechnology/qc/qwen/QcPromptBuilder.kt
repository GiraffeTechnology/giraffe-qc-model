package com.giraffetechnology.qc.qwen

import org.json.JSONArray
import org.json.JSONObject

// Mirrors Python src/qwen/prompt_builder.py — same PROMPT_VERSION, same template structure
object QcPromptBuilder {

    const val PROMPT_VERSION = "qwen-qc-v1"

    fun build(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        schemaJson: String,
    ): String {
        val qcPointsJson = JSONArray().apply {
            qcPoints.forEach { p ->
                put(JSONObject().apply {
                    put("qc_point_id", p.qcPointId)
                    put("qc_point_code", p.qcPointCode)
                    put("name", p.name)
                    put("description", p.description)
                    p.ruleType?.let { put("rule_type", it) }
                    p.roiJson?.let { put("roi", JSONObject(it)) }
                })
            }
        }.toString(2)

        val stdDesc = if (standardPhotos.isEmpty()) "(none)" else
            standardPhotos.joinToString("\n") { p ->
                "  - ID: ${p.photoId}${p.angle?.let { ", angle: $it" } ?: ""}, path: ${p.localPath}"
            }

        return """
You are a professional product quality control (QC) inspector. (Prompt version: $PROMPT_VERSION)
Your task is to inspect a production product photo against reference standard photos and QC points.

## Standard (Reference) Photos
$stdDesc

## Captured Production Photo
  - ID: ${capturedPhoto.photoId}, path: ${capturedPhoto.localPath}

## QC Inspection Points
$qcPointsJson

## Instructions
1. Carefully compare the captured production photo against the standard reference photos.
2. For each QC point, determine: pass, fail, or review_required.
3. If uncertain, blurry, occluded, or angle-mismatched, use "review_required" or "fail". NEVER "pass" for uncertain cases.
4. Provide a confidence score between 0.0 and 1.0 for each item.
5. Only include the listed QC point IDs in "items". Do not hallucinate new IDs.
6. overall_result = "pass" only if ALL items pass; "fail" if any fail; "review_required" if uncertain.

## Output Format
Respond ONLY with a valid JSON object. No markdown. No text outside the JSON.
Required schema:
$schemaJson
        """.trimIndent()
    }
}
