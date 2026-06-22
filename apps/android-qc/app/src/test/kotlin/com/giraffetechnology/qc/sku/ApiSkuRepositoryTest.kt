package com.giraffetechnology.qc.sku

import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

/** Fake transport for unit tests — never touches the network. */
private class FakeHttpTransport(
    private val responses: Map<String, HttpResponse>,
    private val throwOn: String? = null,
) : HttpTransport {
    override fun get(urlString: String, connectTimeoutMs: Int, readTimeoutMs: Int): HttpResponse {
        if (throwOn != null && urlString.contains(throwOn))
            throw java.net.SocketTimeoutException("Fake timeout")
        return responses.entries
            .firstOrNull { urlString.contains(it.key) }
            ?.value
            ?: HttpResponse(404, null)
    }
}

private fun searchJson(vararg skus: Triple<String, String, String>) =
    """{
        "items": [${skus.joinToString(",") { (id, num, name) ->
            """{
                "id":"$id",
                "item_number":"$num",
                "name":"$name",
                "reference_image_url":"http://server/ref/$id.jpg",
                "standard_photo_path":"/factory/ref/$id.jpg"
            }""".trimIndent()
        }}]
    }"""

private fun skuJson(id: String, num: String, name: String) =
    """{"id":"$id","item_number":"$num","name":"$name"}"""

class ApiSkuRepositoryTest {

    // 1. Successful search returns List<Sku>
    @Test
    fun `findByItemNumber returns parsed SKU list on HTTP 200`() = runTest {
        val transport = FakeHttpTransport(mapOf(
            "/api/v1/sku/search" to HttpResponse(200, searchJson(Triple("sku-1", "ITEM-001", "Widget A")))
        ))
        val repo = ApiSkuRepository("http://server", transport)
        val result = repo.findByItemNumber("ITEM")
        assertEquals(1, result.size)
        assertEquals("sku-1", result[0].id)
        assertEquals("ITEM-001", result[0].itemNumber)
        assertEquals("Widget A", result[0].name)
        assertEquals("http://server/ref/sku-1.jpg", result[0].referenceImageUrl)
    }

    // 2. Empty search returns empty list
    @Test
    fun `findByItemNumber returns empty list when items array is empty`() = runTest {
        val transport = FakeHttpTransport(mapOf(
            "/api/v1/sku/search" to HttpResponse(200, """{"items":[]}"""),
        ))
        val repo = ApiSkuRepository("http://server", transport)
        val result = repo.findByItemNumber("ITEM")
        assertTrue(result.isEmpty())
    }

    // 3. Malformed JSON returns empty list and does not crash
    @Test
    fun `findByItemNumber returns empty list on malformed JSON`() = runTest {
        val transport = FakeHttpTransport(mapOf(
            "/api/v1/sku/search" to HttpResponse(200, "not-json!!!"),
        ))
        val repo = ApiSkuRepository("http://server", transport)
        val result = repo.findByItemNumber("ITEM")
        assertTrue(result.isEmpty())
    }

    // 4. HTTP 500 returns empty list
    @Test
    fun `findByItemNumber returns empty list on HTTP 500`() = runTest {
        val transport = FakeHttpTransport(mapOf(
            "/api/v1/sku/search" to HttpResponse(500, null),
        ))
        val repo = ApiSkuRepository("http://server", transport)
        val result = repo.findByItemNumber("ITEM")
        assertTrue(result.isEmpty())
        assertTrue(repo.connectionState.value is BackendConnectionState.Error)
    }

    // 5. Timeout / network error returns empty list
    @Test
    fun `findByItemNumber returns empty list on network error`() = runTest {
        val transport = FakeHttpTransport(emptyMap(), throwOn = "/api/v1/sku/search")
        val repo = ApiSkuRepository("http://server", transport)
        val result = repo.findByItemNumber("ITEM")
        assertTrue(result.isEmpty())
        assertEquals(BackendConnectionState.Offline, repo.connectionState.value)
    }

    // 6. getById 200 returns Sku
    @Test
    fun `getById returns Sku on HTTP 200`() = runTest {
        val transport = FakeHttpTransport(mapOf(
            "/api/v1/sku/sku-1" to HttpResponse(200, skuJson("sku-1", "ITEM-001", "Widget A")),
        ))
        val repo = ApiSkuRepository("http://server", transport)
        val sku = repo.getById("sku-1")
        assertNotNull(sku)
        assertEquals("sku-1", sku!!.id)
    }

    // 7. getById 404 returns null
    @Test
    fun `getById returns null on HTTP 404`() = runTest {
        val transport = FakeHttpTransport(mapOf(
            "/api/v1/sku/sku-missing" to HttpResponse(404, null),
        ))
        val repo = ApiSkuRepository("http://server", transport)
        assertNull(repo.getById("sku-missing"))
    }

    // 8. getById malformed JSON returns null
    @Test
    fun `getById returns null on malformed JSON`() = runTest {
        val transport = FakeHttpTransport(mapOf(
            "/api/v1/sku/sku-1" to HttpResponse(200, "{broken"),
        ))
        val repo = ApiSkuRepository("http://server", transport)
        assertNull(repo.getById("sku-1"))
    }
}
