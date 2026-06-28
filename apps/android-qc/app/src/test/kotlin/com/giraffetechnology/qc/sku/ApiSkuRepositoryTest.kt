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

    // 9. SKU detail parsing carries the inspection data contract: standard photos
    //    and detection points are mapped into the Sku so the Pad task can fail
    //    closed (or run) on real inputs.
    @Test
    fun `getById parses standard photos and detection points`() = runTest {
        val detail = """
            {
              "id":"sku-1",
              "item_number":"ITEM-001",
              "name":"Widget A",
              "active_standard_revision_id":"rev-7",
              "photos":[
                {"id":"ph-1","local_path":"/factory/ph-1.jpg","angle":"front"},
                {"id":"ph-2","image_url":"http://server/ph-2.jpg"}
              ],
              "detection_points":[
                {"id":"dp-1","point_code":"COLOR","label":"Color","description":"Color must match","severity":"major"},
                {"id":"dp-2","point_code":"SHAPE","label":"Shape","severity":"critical","roi_json":{"x":1}}
              ]
            }
        """.trimIndent()
        val transport = FakeHttpTransport(mapOf("/api/v1/sku/sku-1" to HttpResponse(200, detail)))
        val sku = ApiSkuRepository("http://server", transport).getById("sku-1")

        assertNotNull(sku)
        assertEquals("rev-7", sku!!.activeStandardRevisionId)

        assertEquals(2, sku.standardPhotos.size)
        assertEquals("/factory/ph-1.jpg", sku.standardPhotos[0].localPath)
        assertEquals("front", sku.standardPhotos[0].angle)
        // image_url is used as the path when local_path is absent
        assertEquals("http://server/ph-2.jpg", sku.standardPhotos[1].localPath)

        assertEquals(2, sku.detectionPoints.size)
        assertEquals(setOf("COLOR", "SHAPE"), sku.detectionPoints.map { it.qcPointCode }.toSet())
        assertEquals("Color", sku.detectionPoints[0].name)
        assertEquals("major", sku.detectionPoints[0].ruleType)
        assertEquals("""{"x":1}""", sku.detectionPoints[1].roiJson)
    }

    // 10. Standard photos with no usable path are dropped so they cannot be
    //     mistaken for a valid standard.
    @Test
    fun `getById drops photos without a usable path`() = runTest {
        val detail = """
            {
              "id":"sku-1",
              "item_number":"ITEM-001",
              "name":"Widget A",
              "photos":[
                {"id":"ph-1","angle":"front"},
                {"id":"ph-2","local_path":"/factory/ph-2.jpg"}
              ],
              "detection_points":[]
            }
        """.trimIndent()
        val transport = FakeHttpTransport(mapOf("/api/v1/sku/sku-1" to HttpResponse(200, detail)))
        val sku = ApiSkuRepository("http://server", transport).getById("sku-1")

        assertNotNull(sku)
        assertEquals(1, sku!!.standardPhotos.size)
        assertEquals("/factory/ph-2.jpg", sku.standardPhotos[0].localPath)
        assertTrue(sku.detectionPoints.isEmpty())
    }

    // 11. Search response (no photos/detection_points arrays) leaves the lists
    //     empty — a Pad task built from search results must fail closed.
    @Test
    fun `search results leave inspection inputs empty`() = runTest {
        val transport = FakeHttpTransport(mapOf(
            "/api/v1/sku/search" to HttpResponse(200, searchJson(Triple("sku-1", "ITEM-001", "Widget A")))
        ))
        val result = ApiSkuRepository("http://server", transport).findByItemNumber("ITEM")
        assertEquals(1, result.size)
        assertTrue(result[0].standardPhotos.isEmpty())
        assertTrue(result[0].detectionPoints.isEmpty())
    }
}
