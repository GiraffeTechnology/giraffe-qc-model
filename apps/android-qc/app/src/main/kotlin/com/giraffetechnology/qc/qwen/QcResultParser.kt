package com.giraffetechnology.qc.qwen

import org.json.JSONArray
import org.json.JSONObject

// Mirrors Python src/qwen/parser.py — same rules as §4.3.5
object QcResultParser {

    private val VALID_RESULTS = setOf("pass", "fail", "review_required")

    fun parse(
        raw: String,
        expectedQcPointIds: List<String>,
        engine: String,
    ): QwenInspectionOutput {
        if (raw.isBlank()) return failClosed(engine, "empty_response")
        // Strip Qwen3 <think>…</think> blocks before JSON extraction.
        // Guards against thinking-mode output even if enable_thinking=false is ignored by MNN.
        val stripped = stripThinkingBlocks(raw)
        val jsonStr = extractJson(stripped) ?: return failClosed(engine, "json_parse_failed")
        return try {
            parseJson(jsonStr, expectedQcPointIds, engine)
        } catch (_: Exception) {
            failClosed(engine, "json_parse_failed")
        }
    }

    // Removes every <think>…</think> span (including multiline) produced by Qwen3 thinking mode.
    fun stripThinkingBlocks(raw: String): String =
        raw.replace(Regex("<think>.*?</think>", RegexOption.DOT_MATCHES_ALL), "").trim()

    private fun extractJson(raw: String): String? {
        // Try markdown code block
        val mdMatch = Regex("```(?:json)?\\s*\\n?([\\s\\S]+?)\\n?```").find(raw)
        if (mdMatch != null) return mdMatch.groupValues[1].trim()
        // Try bare JSON object
        val start = raw.indexOf('{')
        val end   = raw.lastIndexOf('}')
        if (start >= 0 && end > start) return raw.substring(start, end + 1)
        return null
    }

    private fun parseJson(
        jsonStr: String,
        expectedIds: List<String>,
        engine: String,
    ): QwenInspectionOutput {
        val obj = JSONObject(jsonStr)

        val overallResult = obj.optString("overall_result", "review_required")
            .let { if (it in VALID_RESULTS) it else "review_required" }

        val confidence = obj.optDouble("confidence", 0.0).coerceIn(0.0, 1.0).toFloat()
        val modelName  = obj.optString("model_name", "unknown")
        val summary    = obj.optString("summary", "")

        val expectedSet = expectedIds.toSet()
        val parsedItems = mutableMapOf<String, InspectionItemResult>()

        val itemsArr: JSONArray? = obj.optJSONArray("items")
        if (itemsArr != null) {
            for (i in 0 until itemsArr.length()) {
                val item = itemsArr.getJSONObject(i)
                val id   = item.optString("qc_point_id", "")
                if (id.isBlank() || id !in expectedSet) continue  // reject hallucinated IDs
                val itemResult = item.optString("result", "review_required")
                    .let { if (it in VALID_RESULTS) it else "review_required" }
                parsedItems[id] = InspectionItemResult(
                    qcPointId   = id,
                    qcPointCode = item.optString("qc_point_code", id),
                    name        = item.optString("name", id),
                    result      = itemResult,
                    confidence  = item.optDouble("confidence", 0.0).coerceIn(0.0, 1.0).toFloat(),
                    reason      = item.optString("reason", ""),
                    evidence    = emptyMap(),
                )
            }
        }

        // Fill missing QC points as review_required
        val allItems = expectedIds.map { id ->
            parsedItems[id] ?: InspectionItemResult(
                qcPointId   = id,
                qcPointCode = id,
                name        = id,
                result      = "review_required",
                confidence  = 0.0f,
                reason      = "not_returned_by_model",
            )
        }

        val fbObj = obj.optJSONObject("fallback")
        val fallback = FallbackInfo(
            used   = fbObj?.optBoolean("used", false) ?: false,
            reason = if (fbObj != null && !fbObj.isNull("reason")) fbObj.optString("reason") else null,
        )

        return QwenInspectionOutput(
            overallResult = overallResult,
            engine        = engine,
            modelName     = modelName,
            confidence    = confidence,
            items         = allItems,
            fallback      = fallback,
            summary       = summary,
        )
    }

    fun failClosed(engine: String, reason: String): QwenInspectionOutput =
        QwenInspectionOutput(
            overallResult = "review_required",
            engine        = engine,
            modelName     = "none",
            confidence    = 0.0f,
            items         = emptyList(),
            fallback      = FallbackInfo(used = false, reason = reason),
            summary       = "Parse failed: $reason",
        )
}
