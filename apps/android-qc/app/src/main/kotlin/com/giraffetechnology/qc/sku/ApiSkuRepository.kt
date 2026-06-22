package com.giraffetechnology.qc.sku

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
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
    )
}
