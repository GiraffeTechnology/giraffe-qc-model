package com.giraffetechnology.qc.admin

import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.UUID

/**
 * Injectable transport for the Administrator backend — mirrors the
 * [com.giraffetechnology.qc.sku.ApiSkuRepository] pattern so unit tests can
 * exercise the full client against a fake without any network.
 */
internal interface AdminTransport {
    fun request(
        method: String,
        urlString: String,
        headers: Map<String, String> = emptyMap(),
        body: ByteArray? = null,
        contentType: String? = null,
        connectTimeoutMs: Int = 5_000,
        readTimeoutMs: Int = 15_000,
    ): AdminHttpResponse
}

internal data class AdminHttpResponse(
    val code: Int,
    val body: String?,
    /** Response headers, lower-cased keys, first value wins. */
    val headers: Map<String, List<String>> = emptyMap(),
)

private class RealAdminTransport : AdminTransport {
    override fun request(
        method: String,
        urlString: String,
        headers: Map<String, String>,
        body: ByteArray?,
        contentType: String?,
        connectTimeoutMs: Int,
        readTimeoutMs: Int,
    ): AdminHttpResponse {
        val conn = URL(urlString).openConnection() as HttpURLConnection
        conn.requestMethod = method
        conn.connectTimeout = connectTimeoutMs
        conn.readTimeout = readTimeoutMs
        // The login flow answers with a 303 redirect on success — the client
        // inspects the status itself, so redirects must not be auto-followed.
        conn.instanceFollowRedirects = false
        headers.forEach { (k, v) -> conn.setRequestProperty(k, v) }
        if (contentType != null) conn.setRequestProperty("Content-Type", contentType)
        if (body != null) {
            conn.doOutput = true
            conn.outputStream.use { it.write(body) }
        }
        return try {
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader()?.readText()
            val responseHeaders = conn.headerFields
                .filterKeys { it != null }
                .mapKeys { it.key.lowercase() }
            AdminHttpResponse(code, text, responseHeaders)
        } finally {
            conn.disconnect()
        }
    }
}

/** Authenticated administrator identity — attached to every admin action. */
data class AdminIdentity(
    val username: String,
    val tenantId: String,
    /** Opaque backend session cookie (`session=...`). */
    internal val sessionCookie: String,
)

sealed class AdminApiResult<out T> {
    data class Ok<T>(val value: T) : AdminApiResult<T>()
    data class Error(val message: String, val httpCode: Int? = null) : AdminApiResult<Nothing>()
}

// ── View models parsed from the backend JSON ────────────────────────────────

data class AdminSkuSummary(
    val id: String,
    val itemNumber: String,
    val name: String,
    val status: String,
    val standardStatus: String,
    val activeRevisionId: String?,
    val detectionPointCount: Int,
    val photos: List<AdminPhoto> = emptyList(),
    val detectionPoints: List<AdminDetectionPoint> = emptyList(),
)

data class AdminPhoto(
    val id: String,
    val url: String,
    val viewType: String?,
    val isPrimary: Boolean,
)

data class AdminDetectionPoint(
    val id: String,
    val pointCode: String,
    val label: String,
    val description: String?,
    val methodHint: String?,
    val expectedValue: String?,
    val severity: String,
    val regions: List<Region> = emptyList(),
)

data class AdminCheckpointCategory(
    val category: String,
    val defaultAiRole: String,
    val aiCanBePrimaryJudge: Boolean,
)

data class AdminDetectionPointCategory(
    val detectionPointId: String,
    val proposedCategory: String,
    val confirmedCategory: String?,
    val confirmedBy: String?,
    val aiRole: String,
    val aiCanBePrimaryJudge: Boolean,
)

data class AdminBundle(
    val id: String,
    val bundleVersion: String,
    val status: String,
    val skuCount: Int,
    val createdBy: String?,
    val createdAt: String?,
    val manifestSha256: String,
    val signed: Boolean,
)

data class AdminWorkstation(
    val id: String,
    val workstationId: String,
    val displayName: String,
    val siteOrLine: String?,
    val pairedStatus: String,
    val assignedBundleVersion: String?,
    val installedBundleVersion: String?,
    val lastSeenAt: String?,
    val inSync: Boolean,
)

data class AdminVerdict(
    val submissionId: String,
    val serverOverallResult: String,
    val padOverallResult: String,
    val agrees: Boolean,
    val reviewRequired: Boolean,
    val standardRevisionId: String,
    val bundleVersion: String?,
    val failingCheckpoints: List<String>,
    val humanFinalDecision: String?,
    val recomputedAt: String?,
)

data class AdminSuspension(
    val id: String,
    val trainingPackId: String?,
    val status: String,
    val reason: String?,
)

data class AdminProbationGate(
    val jobsRecorded: Int,
    val agreements: Int,
    val agreementRate: Double,
    val minSampleSize: Int,
    val agreementThreshold: Double,
    val recheckInterval: Int,
    val minSampleMet: Boolean,
    val thresholdMet: Boolean,
    val checkDue: Boolean,
    val qualified: Boolean,
)

data class AdminProbationView(
    val probationId: String,
    val skuId: String,
    val standardRevisionId: String,
    val status: String,
    val gate: AdminProbationGate,
)

data class AdminDisagreementPoint(
    val pointCode: String,
    val disagreementCount: Int,
)

data class AdminDisagreementJob(
    val jobRef: String,
    val sequenceNo: Int,
    val aiVerdict: String,
    val humanFinalVerdict: String,
)

data class AdminDisagreementReport(
    val probationId: String,
    val status: String,
    val disagreements: Int,
    val detectionPoints: List<AdminDisagreementPoint>,
    val jobs: List<AdminDisagreementJob>,
)

/**
 * HTTP client for the Pad Administrator module.
 *
 * Authenticates against the server's admin session login (`POST /admin/login`)
 * and carries the session cookie on every subsequent call, so the backend's
 * fail-closed auth + tenant-isolation middleware sees a real admin principal
 * and every action is attributable to the logged-in administrator.
 */
class AdminApiClient internal constructor(
    private val baseUrl: String,
    private val transport: AdminTransport = RealAdminTransport(),
) {
    constructor(baseUrl: String) : this(baseUrl, RealAdminTransport())

    @Volatile
    var identity: AdminIdentity? = null
        private set

    private fun cookieHeaders(): Map<String, String> =
        identity?.let { mapOf("Cookie" to it.sessionCookie) } ?: emptyMap()

    private fun enc(v: String): String = URLEncoder.encode(v, "UTF-8")
    private fun pathEnc(v: String): String = enc(v).replace("+", "%20")

    // ── 1. Admin login / identity binding ───────────────────────────────────

    fun login(username: String, password: String, tenantId: String): AdminApiResult<AdminIdentity> {
        val form = "username=${enc(username)}&password=${enc(password)}" +
            "&tenant_id=${enc(tenantId)}&next=${enc("/admin")}"
        val resp = runCatching {
            transport.request(
                "POST", "$baseUrl/admin/login",
                body = form.toByteArray(),
                contentType = "application/x-www-form-urlencoded",
            )
        }.getOrElse { e -> return AdminApiResult.Error(e.message ?: "network error") }

        // Success is a 303 redirect to /admin with the session cookie set.
        if (resp.code != 303) {
            return AdminApiResult.Error("login rejected", resp.code)
        }
        val setCookie = resp.headers["set-cookie"]?.firstOrNull { it.startsWith("session=") }
            ?: return AdminApiResult.Error("login succeeded but no session cookie was set")
        val cookie = setCookie.substringBefore(';')
        val id = AdminIdentity(username = username, tenantId = tenantId, sessionCookie = cookie)
        identity = id
        return AdminApiResult.Ok(id)
    }

    fun logout() {
        identity = null
    }

    // ── 2. SKU list / create / select ───────────────────────────────────────

    fun listSkus(query: String = "", status: String = ""): AdminApiResult<List<AdminSkuSummary>> {
        val tenant = identity?.tenantId ?: "default"
        val url = "$baseUrl/admin/studio/skus?tenant_id=${enc(tenant)}&q=${enc(query)}&status=${enc(status)}"
        return getJson(url) { json ->
            val items = json.getJSONArray("items")
            (0 until items.length()).map { parseSkuSummary(items.getJSONObject(it)) }
        }
    }

    fun fetchSkuLifecycleStates(): AdminApiResult<List<String>> =
        getJson("$baseUrl/admin/studio/config") { json ->
            val states = json.getJSONArray("sku_lifecycle_states")
            (0 until states.length()).map { states.getString(it) }
        }

    fun getSku(skuId: String): AdminApiResult<AdminSkuSummary> {
        val tenant = identity?.tenantId ?: "default"
        return getJson("$baseUrl/admin/studio/skus/${enc(skuId)}?tenant_id=${enc(tenant)}") {
            parseSkuSummary(it)
        }
    }

    fun createSku(
        itemNumber: String,
        name: String,
        category: String?,
        description: String?,
    ): AdminApiResult<String> {
        val body = JSONObject()
            .put("tenant_id", identity?.tenantId ?: "default")
            .put("item_number", itemNumber)
            .put("name", name)
            .putOpt("category", category)
            .putOpt("description", description)
        return postJson("$baseUrl/admin/studio/skus", body) { it.getString("id") }
    }

    // ── 3. Standard photo / process-card upload ─────────────────────────────

    fun uploadStandardPhoto(
        skuId: String,
        fileName: String,
        mimeType: String,
        bytes: ByteArray,
        viewType: String? = null,
    ): AdminApiResult<String> {
        if (identity == null) return AdminApiResult.Error("administrator authentication required", 401)
        val tenant = identity?.tenantId ?: "default"
        val boundary = "----GiraffeQcPad${UUID.randomUUID().toString().replace("-", "")}"
        val out = ByteArrayOutputStream()
        fun field(name: String, value: String) {
            out.write("--$boundary\r\nContent-Disposition: form-data; name=\"$name\"\r\n\r\n$value\r\n".toByteArray())
        }
        field("sku_id", skuId)
        field("tenant_id", tenant)
        if (viewType != null) field("view_type", viewType)
        out.write(
            ("--$boundary\r\nContent-Disposition: form-data; name=\"image\"; " +
                "filename=\"$fileName\"\r\nContent-Type: $mimeType\r\n\r\n").toByteArray()
        )
        out.write(bytes)
        out.write("\r\n--$boundary--\r\n".toByteArray())

        val resp = runCatching {
            transport.request(
                "POST", "$baseUrl/admin/studio/upload",
                headers = cookieHeaders(),
                body = out.toByteArray(),
                contentType = "multipart/form-data; boundary=$boundary",
                readTimeoutMs = 60_000,
            )
        }.getOrElse { e -> return AdminApiResult.Error(e.message ?: "network error") }
        return parseResponse(resp) { it.getString("photo_id") }
    }

    /**
     * Upload a process-card source through the same real Source Workbench route
     * used by Studio. The backend stores/classifies every accepted document and
     * only extracts formats for which it has a real parser; this client does not
     * duplicate or guess extraction behavior.
     */
    fun uploadProcessCard(
        trainingPackId: String,
        fileName: String,
        mimeType: String,
        bytes: ByteArray,
    ): AdminApiResult<String> {
        if (identity == null) return AdminApiResult.Error("administrator authentication required", 401)
        val tenant = identity?.tenantId ?: "default"
        val boundary = "----GiraffeQcPad${UUID.randomUUID().toString().replace("-", "")}"
        val safeFileName = fileName.replace(Regex("[\\r\\n\\\"]"), "_")
        val out = ByteArrayOutputStream()
        fun field(name: String, value: String) {
            out.write("--$boundary\r\nContent-Disposition: form-data; name=\"$name\"\r\n\r\n$value\r\n".toByteArray())
        }
        field("tenant_id", tenant)
        field("title", safeFileName)
        out.write(
            ("--$boundary\r\nContent-Disposition: form-data; name=\"file\"; " +
                "filename=\"$safeFileName\"\r\nContent-Type: $mimeType\r\n\r\n").toByteArray()
        )
        out.write(bytes)
        out.write("\r\n--$boundary--\r\n".toByteArray())

        val resp = runCatching {
            transport.request(
                "POST",
                "$baseUrl/admin/qc-model/training-packs/${pathEnc(trainingPackId)}/sources/upload",
                headers = cookieHeaders(),
                body = out.toByteArray(),
                contentType = "multipart/form-data; boundary=$boundary",
                readTimeoutMs = 60_000,
            )
        }.getOrElse { e -> return AdminApiResult.Error(e.message ?: "network error") }

        // The Source Workbench returns a 303 to its source list after the file
        // has been stored and the source document committed.
        if (resp.code == 303) {
            val location = resp.headers["location"]?.firstOrNull().orEmpty()
            return AdminApiResult.Ok(location.ifBlank { trainingPackId })
        }
        return AdminApiResult.Error(errorMessage(resp), resp.code)
    }

    // ── 4. Detection point input / edit / confirm ───────────────────────────

    fun addDetectionPoint(
        skuId: String,
        pointCode: String,
        label: String,
        description: String?,
        methodHint: String?,
        expectedValue: String?,
        severity: String,
    ): AdminApiResult<String> {
        val body = JSONObject()
            .put("tenant_id", identity?.tenantId ?: "default")
            .put("point_code", pointCode)
            .put("label", label)
            .putOpt("description", description)
            .putOpt("method_hint", methodHint)
            .putOpt("expected_value", expectedValue)
            .put("severity", severity)
        return postJson("$baseUrl/api/v1/sku/${enc(skuId)}/detection-points", body) {
            it.getString("id")
        }
    }

    fun updateDetectionPoint(
        detectionPointId: String,
        pointCode: String,
        label: String,
        description: String?,
        methodHint: String?,
        expectedValue: String?,
        severity: String,
    ): AdminApiResult<String> {
        val body = JSONObject()
            .put("tenant_id", identity?.tenantId ?: "default")
            .put("point_code", pointCode)
            .put("label", label)
            .putOpt("description", description)
            .putOpt("method_hint", methodHint)
            .putOpt("expected_value", expectedValue)
            .put("severity", severity)
        return requestJson(
            "PATCH", "$baseUrl/admin/studio/detection-points/${enc(detectionPointId)}", body,
        ) { it.getString("id") }
    }

    fun fetchCheckpointCategories(): AdminApiResult<List<AdminCheckpointCategory>> =
        getJson("$baseUrl/api/qc-model/checkpoint-categories") { json ->
            val items = json.getJSONArray("categories")
            (0 until items.length()).map { i ->
                val item = items.getJSONObject(i)
                AdminCheckpointCategory(
                    category = item.getString("category"),
                    defaultAiRole = item.getString("default_ai_role"),
                    aiCanBePrimaryJudge = item.getBoolean("ai_can_be_primary_judge"),
                )
            }
        }

    fun fetchDetectionPointCategories(skuId: String): AdminApiResult<List<AdminDetectionPointCategory>> {
        val tenant = identity?.tenantId ?: "default"
        return getJson(
            "$baseUrl/api/qc/skus/${enc(skuId)}/detection-points?tenant_id=${enc(tenant)}"
        ) { json ->
            val items = json.getJSONArray("detection_points")
            (0 until items.length()).map { i -> parseDetectionPointCategory(items.getJSONObject(i)) }
        }
    }

    fun confirmDetectionPointCategory(
        detectionPointId: String,
        category: String,
        rationale: String = "",
    ): AdminApiResult<AdminDetectionPointCategory> {
        val admin = identity ?: return AdminApiResult.Error("administrator authentication required", 401)
        val form = "confirmed_category=${enc(category)}&confirmed_by=${enc(admin.username)}" +
            "&rationale=${enc(rationale)}"
        val resp = runCatching {
            transport.request(
                "POST",
                "$baseUrl/api/qc/detection-points/${enc(detectionPointId)}/confirm-category",
                headers = cookieHeaders(),
                body = form.toByteArray(),
                contentType = "application/x-www-form-urlencoded",
            )
        }.getOrElse { e -> return AdminApiResult.Error(e.message ?: "network error") }
        return parseResponse(resp) { parseDetectionPointCategory(it) }
    }

    /** Confirm a standard-intake's candidate checkpoints (category confirmation). */
    fun confirmIntake(
        intakeId: String,
        checkpoints: List<JSONObject>,
        confirmedBy: String,
    ): AdminApiResult<String> {
        val body = JSONObject()
            .put("tenant_id", identity?.tenantId ?: "default")
            .put("intake_id", intakeId)
            .put("confirmed_by", confirmedBy)
            .put("checkpoints", JSONArray(checkpoints))
        return postJson("$baseUrl/admin/studio/confirm", body) { it.getString("revision_id") }
    }

    // ── 5. Region drawing persistence ────────────────────────────────────────

    fun saveDetectionPointRegions(
        detectionPointId: String,
        regions: List<Region>,
    ): AdminApiResult<Unit> {
        val serialized = JSONArray()
        regions.forEach { region ->
            serialized.put(
                JSONObject()
                    .put("image_id", region.imageId)
                    .put("x", region.x)
                    .put("y", region.y)
                    .put("w", region.w)
                    .put("h", region.h)
            )
        }
        val body = JSONObject()
            .put("tenant_id", identity?.tenantId ?: "default")
            .put("regions", serialized)
        return postJson(
            "$baseUrl/admin/studio/detection-points/${enc(detectionPointId)}/regions", body,
        ) { Unit }
    }

    // ── 6. Bundle publish / download status ─────────────────────────────────

    fun publishBundle(skuId: String): AdminApiResult<String> {
        val body = JSONObject()
            .put("tenant_id", identity?.tenantId ?: "default")
            .put("sku_id", skuId)
            .put("published_by", identity?.username ?: "unknown-admin")
        return postJson("$baseUrl/admin/studio/publish", body) {
            it.getJSONObject("bundle").optString("id")
        }
    }

    fun listBundles(): AdminApiResult<List<AdminBundle>> {
        val tenant = identity?.tenantId ?: "default"
        return getJsonArray("$baseUrl/api/qc/bundles?tenant_id=${enc(tenant)}") { arr ->
            (0 until arr.length()).map { parseBundle(arr.getJSONObject(it)) }
        }
    }

    /** Fetch + verify a signed bundle; Ok means the server verified signatures. */
    fun downloadBundle(bundlePk: String): AdminApiResult<String> {
        val tenant = identity?.tenantId ?: "default"
        return getJson("$baseUrl/api/qc/bundles/${enc(bundlePk)}/download?tenant_id=${enc(tenant)}") {
            it.getString("manifest_sha256")
        }
    }

    // ── 7. Workstation registration / assignment ────────────────────────────

    fun registerWorkstation(
        workstationId: String,
        displayName: String,
        siteOrLine: String?,
    ): AdminApiResult<AdminWorkstation> {
        val body = JSONObject()
            .put("tenant_id", identity?.tenantId ?: "default")
            .put("workstation_id", workstationId)
            .put("display_name", displayName)
            .putOpt("site_or_line", siteOrLine)
        return postJson("$baseUrl/api/qc/workstations", body) { parseWorkstation(it) }
    }

    fun listWorkstations(): AdminApiResult<List<AdminWorkstation>> {
        val tenant = identity?.tenantId ?: "default"
        return getJsonArray("$baseUrl/api/qc/workstations?tenant_id=${enc(tenant)}") { arr ->
            (0 until arr.length()).map { parseWorkstation(arr.getJSONObject(it)) }
        }
    }

    fun assignBundle(workstationPk: String, bundlePk: String): AdminApiResult<AdminWorkstation> {
        val body = JSONObject()
            .put("tenant_id", identity?.tenantId ?: "default")
            .put("bundle_pk", bundlePk)
            .put("assigned_by", identity?.username ?: "unknown-admin")
        return postJson("$baseUrl/api/qc/workstations/${enc(workstationPk)}/assign", body) {
            parseWorkstation(it)
        }
    }

    // ── 9. Probation / qualification (probation-api.md v2) ─────────────────

    fun fetchProbation(revisionId: String): AdminApiResult<AdminProbationView> {
        if (revisionId.isBlank()) return AdminApiResult.Error("standard revision id is required")
        val tenant = identity?.tenantId ?: "default"
        return getJson(
            "$baseUrl/api/qc/probation/by-revision/${enc(revisionId)}?tenant_id=${enc(tenant)}"
        ) { parseProbation(it) }
    }

    fun pauseProbation(probationId: String): AdminApiResult<AdminProbationView> {
        val tenant = identity?.tenantId ?: "default"
        return postJson(
            "$baseUrl/api/qc/probation/${enc(probationId)}/pause?tenant_id=${enc(tenant)}",
            JSONObject(),
        ) { parseProbation(it) }
    }

    fun resumeProbation(probationId: String): AdminApiResult<AdminProbationView> {
        val tenant = identity?.tenantId ?: "default"
        return postJson(
            "$baseUrl/api/qc/probation/${enc(probationId)}/resume?tenant_id=${enc(tenant)}",
            JSONObject(),
        ) { parseProbation(it) }
    }

    fun fetchDisagreementReport(probationId: String): AdminApiResult<AdminDisagreementReport> {
        val tenant = identity?.tenantId ?: "default"
        return getJson(
            "$baseUrl/api/qc/probation/${enc(probationId)}/disagreement-report" +
                "?tenant_id=${enc(tenant)}"
        ) { parseDisagreementReport(it) }
    }

    fun listSuspensions(): AdminApiResult<List<AdminSuspension>> {
        val tenant = identity?.tenantId ?: "default"
        return getJson("$baseUrl/api/qc/suspensions?tenant_id=${enc(tenant)}&active_only=true") { json ->
            val arr = json.getJSONArray("suspensions")
            (0 until arr.length()).map { i ->
                val o = arr.getJSONObject(i)
                AdminSuspension(
                    id = o.optString("id"),
                    trainingPackId = o.optString("training_pack_id").takeIf { it.isNotEmpty() },
                    status = o.optString("status"),
                    reason = o.optString("reason").takeIf { it.isNotEmpty() },
                )
            }
        }
    }

    // ── 10. Server verdicts / incident viewing ──────────────────────────────

    fun listResults(): AdminApiResult<List<AdminVerdict>> {
        val tenant = identity?.tenantId ?: "default"
        return getJsonArray("$baseUrl/api/qc/results?tenant_id=${enc(tenant)}") { arr ->
            (0 until arr.length()).map { parseVerdict(arr.getJSONObject(it)) }
        }
    }

    fun recordFinalDecision(
        submissionId: String,
        decision: String,
        comment: String,
    ): AdminApiResult<AdminVerdict> {
        val body = JSONObject()
            .put("tenant_id", identity?.tenantId ?: "default")
            .put("decision", decision)
            .put("decided_by", identity?.username ?: "unknown-admin")
            .put("comment", comment)
        return postJson("$baseUrl/api/qc/results/${enc(submissionId)}/final-decision", body) {
            parseVerdict(it)
        }
    }

    // ── plumbing ─────────────────────────────────────────────────────────────

    private fun <T> getJson(url: String, parse: (JSONObject) -> T): AdminApiResult<T> {
        if (identity == null) return AdminApiResult.Error("administrator authentication required", 401)
        val resp = runCatching {
            transport.request("GET", url, headers = cookieHeaders())
        }.getOrElse { e -> return AdminApiResult.Error(e.message ?: "network error") }
        return parseResponse(resp, parse)
    }

    private fun <T> getJsonArray(url: String, parse: (JSONArray) -> T): AdminApiResult<T> {
        if (identity == null) return AdminApiResult.Error("administrator authentication required", 401)
        val resp = runCatching {
            transport.request("GET", url, headers = cookieHeaders())
        }.getOrElse { e -> return AdminApiResult.Error(e.message ?: "network error") }
        if (resp.code !in 200..299 || resp.body == null) {
            return AdminApiResult.Error(errorMessage(resp), resp.code)
        }
        return runCatching { AdminApiResult.Ok(parse(JSONArray(resp.body))) }
            .getOrElse { e -> AdminApiResult.Error("malformed response: ${e.message}") }
    }

    private fun <T> postJson(url: String, body: JSONObject, parse: (JSONObject) -> T): AdminApiResult<T> {
        return requestJson("POST", url, body, parse)
    }

    private fun <T> requestJson(
        method: String,
        url: String,
        body: JSONObject,
        parse: (JSONObject) -> T,
    ): AdminApiResult<T> {
        if (identity == null) return AdminApiResult.Error("administrator authentication required", 401)
        val resp = runCatching {
            transport.request(
                method, url,
                headers = cookieHeaders(),
                body = body.toString().toByteArray(),
                contentType = "application/json",
            )
        }.getOrElse { e -> return AdminApiResult.Error(e.message ?: "network error") }
        return parseResponse(resp, parse)
    }

    private fun <T> parseResponse(resp: AdminHttpResponse, parse: (JSONObject) -> T): AdminApiResult<T> {
        if (resp.code !in 200..299 || resp.body == null) {
            return AdminApiResult.Error(errorMessage(resp), resp.code)
        }
        return runCatching { AdminApiResult.Ok(parse(JSONObject(resp.body))) }
            .getOrElse { e -> AdminApiResult.Error("malformed response: ${e.message}") }
    }

    private fun errorMessage(resp: AdminHttpResponse): String {
        val fromBody = resp.body?.let { text ->
            runCatching {
                val o = JSONObject(text)
                o.optString("error").takeIf { it.isNotEmpty() }
                    ?: o.optString("detail").takeIf { it.isNotEmpty() }
            }.getOrNull()
        }
        return fromBody ?: "HTTP ${resp.code}"
    }

    private fun parseSkuSummary(o: JSONObject): AdminSkuSummary {
        val photos = o.optJSONArray("photos")?.let { arr ->
            (0 until arr.length()).map { i ->
                val p = arr.getJSONObject(i)
                AdminPhoto(
                    id = p.getString("id"),
                    url = p.optString("url"),
                    viewType = p.optString("view_type").takeIf { it.isNotEmpty() },
                    isPrimary = p.optBoolean("is_primary"),
                )
            }
        } ?: emptyList()
        val dps = o.optJSONArray("detection_points")?.let { arr ->
            (0 until arr.length()).map { i -> parseDetectionPoint(arr.getJSONObject(i)) }
        } ?: emptyList()
        return AdminSkuSummary(
            id = o.getString("id"),
            itemNumber = o.getString("item_number"),
            name = o.getString("name"),
            status = o.optString("status"),
            standardStatus = o.optString("standard_status"),
            activeRevisionId = o.optString("active_revision_id").takeIf { it.isNotEmpty() },
            detectionPointCount = o.optInt("detection_point_count", dps.size),
            photos = photos,
            detectionPoints = dps,
        )
    }

    private fun parseDetectionPoint(o: JSONObject): AdminDetectionPoint {
        val regions = o.optJSONArray("regions")?.let { arr ->
            (0 until arr.length()).mapNotNull { i ->
                val r = arr.optJSONObject(i) ?: return@mapNotNull null
                Region(
                    imageId = r.optString("image_id"),
                    x = r.optDouble("x", 0.0).toFloat(),
                    y = r.optDouble("y", 0.0).toFloat(),
                    w = r.optDouble("w", 0.0).toFloat(),
                    h = r.optDouble("h", 0.0).toFloat(),
                )
            }
        } ?: emptyList()
        return AdminDetectionPoint(
            id = o.getString("id"),
            pointCode = o.getString("point_code"),
            label = o.getString("label"),
            description = o.optString("description").takeIf { it.isNotEmpty() },
            methodHint = o.optString("method_hint").takeIf { it.isNotEmpty() },
            expectedValue = o.optString("expected_value").takeIf { it.isNotEmpty() },
            severity = o.optString("severity", "major"),
            regions = regions,
        )
    }

    private fun parseDetectionPointCategory(o: JSONObject) = AdminDetectionPointCategory(
        detectionPointId = o.getString("detection_point_id"),
        proposedCategory = o.optString("proposed_checkpoint_category"),
        confirmedCategory = o.optString("confirmed_checkpoint_category").takeIf { it.isNotEmpty() },
        confirmedBy = o.optString("category_confirmed_by").takeIf { it.isNotEmpty() },
        aiRole = o.optString("ai_role"),
        aiCanBePrimaryJudge = o.optBoolean("ai_can_be_primary_judge"),
    )

    private fun parseBundle(o: JSONObject) = AdminBundle(
        id = o.getString("id"),
        bundleVersion = o.optString("bundle_version"),
        status = o.optString("status"),
        skuCount = o.optInt("sku_count"),
        createdBy = o.optString("created_by").takeIf { it.isNotEmpty() },
        createdAt = o.optString("created_at").takeIf { it.isNotEmpty() },
        manifestSha256 = o.optString("manifest_sha256"),
        signed = o.optBoolean("signed"),
    )

    private fun parseWorkstation(o: JSONObject) = AdminWorkstation(
        id = o.getString("id"),
        workstationId = o.optString("workstation_id"),
        displayName = o.optString("display_name"),
        siteOrLine = o.optString("site_or_line").takeIf { it.isNotEmpty() },
        pairedStatus = o.optString("paired_status"),
        assignedBundleVersion = o.optString("assigned_bundle_version").takeIf { it.isNotEmpty() },
        installedBundleVersion = o.optString("installed_bundle_version").takeIf { it.isNotEmpty() },
        lastSeenAt = o.optString("last_seen_at").takeIf { it.isNotEmpty() },
        inSync = o.optBoolean("in_sync"),
    )

    private fun parseVerdict(o: JSONObject) = AdminVerdict(
        submissionId = o.getString("submission_id"),
        serverOverallResult = o.optString("server_overall_result"),
        padOverallResult = o.optString("pad_overall_result"),
        agrees = o.optBoolean("agrees"),
        reviewRequired = o.optBoolean("review_required"),
        standardRevisionId = o.optString("standard_revision_id"),
        bundleVersion = o.optString("bundle_version").takeIf { it.isNotEmpty() },
        failingCheckpoints = o.optJSONArray("failing_checkpoints")?.let { arr ->
            (0 until arr.length()).map { arr.optString(it) }
        } ?: emptyList(),
        humanFinalDecision = o.optString("human_final_decision").takeIf { it.isNotEmpty() },
        recomputedAt = o.optString("recomputed_at").takeIf { it.isNotEmpty() },
    )

    private fun parseProbation(o: JSONObject): AdminProbationView {
        val gate = o.getJSONObject("gate")
        return AdminProbationView(
            probationId = o.getString("probation_id"),
            skuId = o.getString("sku_id"),
            standardRevisionId = o.getString("standard_revision_id"),
            status = o.getString("status"),
            gate = AdminProbationGate(
                jobsRecorded = gate.getInt("jobs_recorded"),
                agreements = gate.getInt("agreements"),
                agreementRate = gate.getDouble("agreement_rate"),
                minSampleSize = gate.getInt("min_sample_size"),
                agreementThreshold = gate.getDouble("agreement_threshold"),
                recheckInterval = gate.getInt("recheck_interval"),
                minSampleMet = gate.getBoolean("min_sample_met"),
                thresholdMet = gate.getBoolean("threshold_met"),
                checkDue = gate.getBoolean("is_check_due"),
                qualified = gate.getBoolean("qualified"),
            ),
        )
    }

    private fun parseDisagreementReport(o: JSONObject): AdminDisagreementReport {
        val points = o.getJSONArray("detection_points")
        val jobs = o.getJSONArray("jobs")
        return AdminDisagreementReport(
            probationId = o.getString("probation_id"),
            status = o.getString("status"),
            disagreements = o.getInt("disagreements"),
            detectionPoints = (0 until points.length()).map { i ->
                val point = points.getJSONObject(i)
                AdminDisagreementPoint(
                    pointCode = point.getString("point_code"),
                    disagreementCount = point.getInt("disagreement_count"),
                )
            },
            jobs = (0 until jobs.length()).map { i ->
                val job = jobs.getJSONObject(i)
                AdminDisagreementJob(
                    jobRef = job.getString("job_ref"),
                    sequenceNo = job.getInt("sequence_no"),
                    aiVerdict = job.getString("ai_verdict"),
                    humanFinalVerdict = job.getString("human_final_verdict"),
                )
            },
        )
    }
}
