package com.giraffetechnology.qc.admin

/**
 * Scripted [AdminTransport] for unit tests: responses are keyed by
 * "METHOD path" (query string ignored); every request is recorded for
 * assertions on URL, headers and body.
 */
internal class FakeAdminTransport : AdminTransport {

    data class Recorded(
        val method: String,
        val url: String,
        val headers: Map<String, String>,
        val body: ByteArray?,
        val contentType: String?,
    )

    val requests = mutableListOf<Recorded>()
    private val responses = mutableMapOf<String, AdminHttpResponse>()

    fun stub(method: String, path: String, response: AdminHttpResponse) {
        responses["$method $path"] = response
    }

    override fun request(
        method: String,
        urlString: String,
        headers: Map<String, String>,
        body: ByteArray?,
        contentType: String?,
        connectTimeoutMs: Int,
        readTimeoutMs: Int,
    ): AdminHttpResponse {
        requests += Recorded(method, urlString, headers, body, contentType)
        val path = urlString.substringAfter("://").substringAfter("/").substringBefore("?")
        return responses["$method /$path"]
            ?: AdminHttpResponse(404, """{"detail":"unstubbed $method /$path"}""")
    }
}

/** A logged-in client against the fake transport, for controller tests. */
internal fun loggedInClient(transport: FakeAdminTransport): AdminApiClient {
    transport.stub(
        "POST", "/admin/login",
        AdminHttpResponse(
            303, null,
            headers = mapOf("set-cookie" to listOf("session=abc123; Path=/; HttpOnly")),
        ),
    )
    val client = AdminApiClient("http://test", transport)
    val result = client.login("admin_en", "admin_en", "demo")
    check(result is AdminApiResult.Ok) { "test login must succeed" }
    return client
}
