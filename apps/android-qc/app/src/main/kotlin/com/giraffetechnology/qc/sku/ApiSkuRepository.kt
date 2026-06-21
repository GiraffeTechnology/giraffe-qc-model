package com.giraffetechnology.qc.sku

import java.net.HttpURLConnection
import java.net.URL

/**
 * SKU repository that fetches data from the factory LAN backend.
 * Uses HttpURLConnection — no OkHttp dependency required.
 * Returns an empty list on network failure; callers must handle gracefully.
 */
class ApiSkuRepository(private val baseUrl: String) : SkuRepository {
    override suspend fun findByItemNumber(query: String): List<Sku> =
        runCatching {
            val url = URL("$baseUrl/api/skus?item_number=${query.trim()}")
            val conn = url.openConnection() as HttpURLConnection
            conn.connectTimeout = 5_000
            conn.readTimeout = 10_000
            try {
                if (conn.responseCode == 200) {
                    // TODO: parse JSON response body into List<Sku>
                    emptyList<Sku>()
                } else emptyList<Sku>()
            } finally {
                conn.disconnect()
            }
        }.getOrElse { emptyList() }

    override suspend fun getById(id: String): Sku? = null
}
