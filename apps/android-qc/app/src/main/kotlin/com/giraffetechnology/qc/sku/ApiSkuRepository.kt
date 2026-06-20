package com.giraffetechnology.qc.sku

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL

/**
 * Production SkuRepository backed by the factory backend API.
 * Uses plain HttpURLConnection (no external HTTP library needed; no cloud path).
 *
 * [baseUrl] example: "http://192.168.1.10:8080"
 */
class ApiSkuRepository(
    private val baseUrl: String,
    private val timeoutMs: Int = 5_000,
) : SkuRepository {

    companion object { private const val TAG = "ApiSkuRepository" }

    override suspend fun searchByItemNumber(query: String): List<Sku> =
        get("/api/v1/sku/search?q=${query.encodeUrl()}&page=0&size=50")

    override suspend fun listAll(page: Int, pageSize: Int): List<Sku> =
        get("/api/v1/sku?page=$page&size=$pageSize")

    override suspend fun getById(skuId: String): Sku? =
        runCatching { getOne("/api/v1/sku/${skuId.encodeUrl()}") }.getOrNull()

    // ── HTTP helpers ──────────────────────────────────────────────────────

    private suspend fun get(path: String): List<Sku> = withContext(Dispatchers.IO) {
        val body = fetch(path)
        val json = JSONObject(body)
        val arr  = json.getJSONArray("items")
        List(arr.length()) { parseSku(arr.getJSONObject(it)) }
    }

    private suspend fun getOne(path: String): Sku = withContext(Dispatchers.IO) {
        parseSku(JSONObject(fetch(path)))
    }

    private fun fetch(path: String): String {
        val url = URL("$baseUrl$path")
        val conn = (url.openConnection() as HttpURLConnection).apply {
            connectTimeout = timeoutMs
            readTimeout    = timeoutMs
            requestMethod  = "GET"
            setRequestProperty("Accept", "application/json")
        }
        return try {
            val code = conn.responseCode
            if (code != 200) error("HTTP $code from $path")
            BufferedReader(InputStreamReader(conn.inputStream)).use { it.readText() }
        } finally {
            conn.disconnect()
        }
    }

    private fun parseSku(o: JSONObject): Sku {
        val photosArr = o.getJSONArray("reference_photo_paths")
        val photos    = List(photosArr.length()) { photosArr.getString(it) }
        val attrObj   = o.optJSONObject("attributes")
        val attrs     = mutableMapOf<String, String>()
        attrObj?.keys()?.forEach { k -> attrs[k] = attrObj.getString(k) }
        return Sku(
            skuId                = o.getString("sku_id"),
            itemNumber           = o.getString("item_number"),
            name                 = o.getString("name"),
            referencePhotoPaths  = photos,
            attributes           = attrs,
        )
    }

    private fun String.encodeUrl() = java.net.URLEncoder.encode(this, "UTF-8")
}
