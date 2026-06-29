package com.giraffetechnology.qc.sku

import com.giraffetechnology.qc.qwen.QcPointInput
import com.giraffetechnology.qc.qwen.StandardPhotoInput
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * Injectable transport interface — lets unit tests inject a fake without touching
 * real network. RealHttpTransport is the default in production.
 */
internal interface HttpTransport {
    fun get(urlString: String, connectTimeoutMs: Int, readTimeoutMs: Int): HttpResponse
}

internal data class HttpResponse(val code: Int, val body: String?)

private class RealHttpTransport : HttpTransport {
    override fun get(urlString: String, connectTimeoutMs: Int, readTimeoutMs: Int): HttpResponse {
        val conn = URL(urlString).openConnection() as HttpURLConnection
        conn.connectTimeout = connectTimeoutMs
        conn.readTimeout = readTimeoutMs
        return try {
            val code = conn.responseCode
            val body = if (code == 200) conn.inputStream.bufferedReader().readText() else null
            HttpResponse(code, body)
        } finally {
            conn.disconnect()
        }
    }
}

/**
 * SKU repository that fetches data from the factory LAN backend.
 * API contract: GET /api/v1/sku/search?q={query} and GET /api/v1/sku/{id}.
 * Returns empty list / null on any error; never crashes the UI.
 *
 * Constructor is internal so the internal HttpTransport parameter type is not
 * exposed in the public API surface. All callers within the module (graph,
 * tests) use internal visibility.
 */
class ApiSkuRepository internal constructor(
    private val baseUrl: String,
    private val transport: HttpTransport = RealHttpTransport(),
) : SkuRepository {

    private val _connectionState =
        MutableStateFlow<BackendConnectionState>(BackendConnectionState.Unknown)
    val connectionState: StateFlow<BackendConnectionState> = _connectionState.asStateFlow()

    override suspend fun findByItemNumber(query: String): List<Sku> =
        runCatching {
            val encoded = URLEncoder.encode(query.trim(), "UTF-8")
            val resp = transport.get(
                "$baseUrl/api/v1/sku/search?q=$encoded",
                connectTimeoutMs = 5_000,
                readTimeoutMs    = 10_000,
            )
            if (resp.code == 200 && resp.body != null) {
                _connectionState.value = BackendConnectionState.Connected
                parseSearchResponse(resp.body)
            } else {
                _connectionState.value = BackendConnectionState.Error("HTTP ${resp.code}")
                emptyList()
            }
        }.getOrElse { e ->
            _connectionState.value = BackendConnectionState.Offline
            emptyList()
        }

    override suspend fun getById(id: String): Sku? =
        runCatching {
            val encoded = URLEncoder.encode(id, "UTF-8")
            val resp = transport.get(
                "$baseUrl/api/v1/sku/$encoded",
                connectTimeoutMs = 5_000,
                readTimeoutMs    = 10_000,
            )
            if (resp.code == 200 && resp.body != null) parseSku(JSONObject(resp.body)) else null
        }.getOrElse { null }

    private fun parseSearchResponse(body: String): List<Sku> =
        runCatching {
            val items = JSONObject(body).getJSONArray("items")
            (0 until items.length()).map { parseSku(items.getJSONObject(it)) }
        }.getOrElse { emptyList() }

    private fun parseSku(obj: JSONObject) = Sku(
        id               = obj.getString("id"),
        itemNumber       = obj.getString("item_number"),
        name             = obj.getString("name"),
        referenceImageUrl = obj.optString("reference_image_url").takeIf { it.isNotEmpty() },
        standardPhotoPath = obj.optString("standard_photo_path").takeIf { it.isNotEmpty() },
        activeStandardRevisionId =
            obj.optString("active_standard_revision_id").takeIf { it.isNotEmpty() },
        standardPhotos   = parseStandardPhotos(obj.optJSONArray("photos")),
        detectionPoints  = parseDetectionPoints(obj.optJSONArray("detection_points")),
    )

    // SKU detail (GET /api/v1/sku/{id}) carries the inspection data contract.
    // A usable standard photo needs a path the Pad can read (local_path preferred,
    // image_url as fallback); entries without one are dropped so they cannot be
    // mistaken for a valid standard.
    private fun parseStandardPhotos(arr: JSONArray?): List<StandardPhotoInput> {
        if (arr == null) return emptyList()
        return (0 until arr.length()).mapNotNull { i ->
            val o = arr.optJSONObject(i) ?: return@mapNotNull null
            val path = o.optString("local_path").takeIf { it.isNotEmpty() }
                ?: o.optString("image_url").takeIf { it.isNotEmpty() }
                ?: return@mapNotNull null
            StandardPhotoInput(
                photoId   = o.optString("id"),
                localPath = path,
                angle     = o.optString("angle").takeIf { it.isNotEmpty() },
            )
        }
    }

    private fun parseDetectionPoints(arr: JSONArray?): List<QcPointInput> {
        if (arr == null) return emptyList()
        return (0 until arr.length()).mapNotNull { i ->
            val o = arr.optJSONObject(i) ?: return@mapNotNull null
            val code = o.optString("point_code").takeIf { it.isNotEmpty() }
                ?: return@mapNotNull null
            QcPointInput(
                qcPointId   = o.optString("id"),
                qcPointCode = code,
                name        = o.optString("label"),
                description = o.optString("description"),
                roiJson     = o.optJSONObject("roi_json")?.toString(),
                ruleType    = o.optString("severity").takeIf { it.isNotEmpty() },
            )
        }
    }
}
