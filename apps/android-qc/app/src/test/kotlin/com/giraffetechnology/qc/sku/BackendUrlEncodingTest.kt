package com.giraffetechnology.qc.sku

import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

/** Verifies that special characters in item-number queries are percent-encoded in the request URL. */
class BackendUrlEncodingTest {

    @Test fun `findByItemNumber encodes special characters in query`() = runTest {
        var capturedUrl = ""
        val transport = object : HttpTransport {
            override fun get(
                urlString: String,
                connectTimeoutMs: Int,
                readTimeoutMs: Int,
            ): HttpResponse {
                capturedUrl = urlString
                return HttpResponse(200, """{"items":[]}""".trimIndent())
            }
        }
        val repo = ApiSkuRepository("http://server", transport)
        repo.findByItemNumber("widget/type A")

        assertFalse("URL must not contain a raw space", capturedUrl.contains(" "))
        assertFalse(
            "URL must not contain a raw slash in the query value",
            capturedUrl.substringAfter("?").contains("/"),
        )
        assertTrue(
            "URL must contain the search endpoint",
            capturedUrl.contains("/api/v1/sku/search"),
        )
    }
}
