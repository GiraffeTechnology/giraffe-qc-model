package com.giraffetechnology.qc.sync

import org.json.JSONObject

/**
 * Parsed `manifest.json` from a standard bundle (Task 03).
 *
 * Mirrors the server's `src/sync/bundle_service.py` manifest schema. Only parsed
 * AFTER signature + checksum verification succeed (see [BundleVerification]).
 */
data class BundleManifest(
    val bundleFormatVersion: Int,
    val bundleVersion: Int,
    val generatedAt: String,
    val tenantId: String,
    val lineScope: String,
    val signingKeyFingerprint: String,
    val skus: List<BundleSku>,
)

data class BundleSku(
    val skuId: String,
    val itemNumber: String,
    val name: String,
    val category: String?,
    val activeStandardRevisionId: String,
    val revisionNo: Int,
    val detectionPoints: List<BundleDetectionPoint>,
    val requirements: List<BundleRequirement>,
    val photos: List<BundlePhoto>,
)

data class BundleDetectionPoint(
    val id: String,
    val pointCode: String,
    val label: String,
    val description: String?,
    val roiJson: String?,
    val expectedValue: String?,
    val methodHint: String?,
    val severity: String,
    val sortOrder: Int,
)

data class BundleRequirement(
    val id: String,
    val code: String,
    val title: String,
    val requirementText: String,
    val severity: String,
    val passCriteria: String?,
    val sortOrder: Int,
)

data class BundlePhoto(
    val id: String,
    val filename: String,
    val path: String,        // archive-relative, e.g. photos/<sku>/<file>
    val angle: String?,
    val viewType: String?,
    val isPrimary: Boolean,
    val sha256: String?,
    val mimeType: String?,
)

object BundleManifestParser {

    /** Parse the canonical manifest JSON. Throws on structural problems. */
    fun parse(json: String): BundleManifest {
        val root = JSONObject(json)
        val skusArr = root.getJSONArray("skus")
        val skus = ArrayList<BundleSku>(skusArr.length())
        for (i in 0 until skusArr.length()) {
            val s = skusArr.getJSONObject(i)
            skus.add(
                BundleSku(
                    skuId = s.getString("sku_id"),
                    itemNumber = s.getString("item_number"),
                    name = s.getString("name"),
                    category = s.optStringOrNull("category"),
                    activeStandardRevisionId = s.getString("active_standard_revision_id"),
                    revisionNo = s.optInt("revision_no", 1),
                    detectionPoints = s.getJSONArray("detection_points").map { dp ->
                        BundleDetectionPoint(
                            id = dp.getString("id"),
                            pointCode = dp.getString("point_code"),
                            label = dp.getString("label"),
                            description = dp.optStringOrNull("description"),
                            roiJson = dp.optJsonStringOrNull("roi_json"),
                            expectedValue = dp.optStringOrNull("expected_value"),
                            methodHint = dp.optStringOrNull("method_hint"),
                            severity = dp.optString("severity", "major"),
                            sortOrder = dp.optInt("sort_order", 0),
                        )
                    },
                    requirements = s.getJSONArray("inspection_requirements").map { r ->
                        BundleRequirement(
                            id = r.getString("id"),
                            code = r.getString("code"),
                            title = r.getString("title"),
                            requirementText = r.optString("requirement_text", ""),
                            severity = r.optString("severity", "major"),
                            passCriteria = r.optStringOrNull("pass_criteria"),
                            sortOrder = r.optInt("sort_order", 0),
                        )
                    },
                    photos = s.getJSONArray("photos").map { p ->
                        BundlePhoto(
                            id = p.getString("id"),
                            filename = p.getString("filename"),
                            path = p.getString("path"),
                            angle = p.optStringOrNull("angle"),
                            viewType = p.optStringOrNull("view_type"),
                            isPrimary = p.optBoolean("is_primary", false),
                            sha256 = p.optStringOrNull("sha256"),
                            mimeType = p.optStringOrNull("mime_type"),
                        )
                    },
                )
            )
        }
        return BundleManifest(
            bundleFormatVersion = root.optInt("bundle_format_version", 1),
            bundleVersion = root.getInt("bundle_version"),
            generatedAt = root.optString("generated_at", ""),
            tenantId = root.getString("tenant_id"),
            lineScope = root.optString("line_scope", ""),
            signingKeyFingerprint = root.optString("signing_key_fingerprint", ""),
            skus = skus,
        )
    }
}

// ── small JSON helpers ────────────────────────────────────────────────────────

private fun JSONObject.optStringOrNull(key: String): String? =
    if (isNull(key) || !has(key)) null else optString(key).ifEmpty { null }

/** roi_json / tolerance_json come through as nested objects; keep them as raw JSON strings. */
private fun JSONObject.optJsonStringOrNull(key: String): String? {
    if (!has(key) || isNull(key)) return null
    val v = get(key)
    return v.toString()
}

private inline fun <T> org.json.JSONArray.map(transform: (JSONObject) -> T): List<T> {
    val out = ArrayList<T>(length())
    for (i in 0 until length()) out.add(transform(getJSONObject(i)))
    return out
}
