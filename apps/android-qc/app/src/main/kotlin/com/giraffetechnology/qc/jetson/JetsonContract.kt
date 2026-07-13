package com.giraffetechnology.qc.jetson

import org.json.JSONArray
import org.json.JSONObject

/**
 * Pad-side mirror of the §4 Pad<->Jetson inference contract
 * (`src/qc_model/jetson/contract.py` / `docs/api-contracts/jetson-runner-api.md`).
 * Field names/shape must stay in lockstep with that Python module -- this is
 * not an independent schema.
 */
data class JetsonDetectionPointSpec(
    val pointCode: String,
    val label: String = "",
    val description: String = "",
    val methodHint: String = "",
    val expectedValue: String = "",
    val passCriteria: String = "",
    val severity: String = "major",
) {
    fun toJson(): JSONObject = JSONObject()
        .put("point_code", pointCode)
        .put("label", label)
        .put("description", description)
        .put("method_hint", methodHint)
        .put("expected_value", expectedValue)
        .put("pass_criteria", passCriteria)
        .put("severity", severity)
        // Region annotation (WS6) is not wired into the per-point request
        // yet -- always empty rather than fabricated. See JetsonQwenInspector.
        .put("regions", JSONArray())
}

data class JetsonInferenceRequest(
    val jobId: String,
    val standardRevisionId: String,
    val bundleVersion: String = "",
    /**
     * Per docs/api-contracts/jetson-runner-api.md §2, a "reference/URI or
     * inline-encoded frame". This client always sends an inline
     * `data:<mime>;base64,<...>` data URI so the Jetson never needs a shared
     * filesystem mount with the Pad -- and a llama.cpp-backed real adapter
     * can pass this string straight through as a chat-completions-style
     * `image_url.url` value unmodified (see jetson_runner's
     * LlamaCppInferenceAdapter). This is LAN-local inference on the Jetson,
     * never a cloud endpoint.
     */
    val image: String,
    val detectionPoints: List<JetsonDetectionPointSpec>,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("job_id", jobId)
        .put("standard_revision_id", standardRevisionId)
        .put("bundle_version", bundleVersion)
        .put("image", image)
        .put("detection_points", JSONArray(detectionPoints.map { it.toJson() }))
}

data class JetsonPerPointResult(
    val pointCode: String,
    /** "pass" | "fail" | "uncertain" -- raw wire value, not yet mapped to the Pad's verdict vocabulary. */
    val result: String,
    val confidence: Float,
    val evidence: String,
)

data class JetsonInferenceResponse(
    val jobId: String,
    val perPointResults: List<JetsonPerPointResult>,
) {
    companion object {
        fun fromJson(json: JSONObject): JetsonInferenceResponse {
            val results = json.optJSONArray("per_point_results") ?: JSONArray()
            return JetsonInferenceResponse(
                jobId = json.optString("job_id", ""),
                perPointResults = (0 until results.length()).map { i ->
                    val r = results.getJSONObject(i)
                    JetsonPerPointResult(
                        pointCode = r.optString("point_code", ""),
                        result = r.optString("result", "uncertain"),
                        confidence = r.optDouble("confidence", 0.0).toFloat(),
                        evidence = r.optString("evidence", ""),
                    )
                },
            )
        }
    }
}
