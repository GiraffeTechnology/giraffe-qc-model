package com.giraffetechnology.qc.admin

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AdminApiClientTest {

    // ── login / identity binding ─────────────────────────────────────────────

    @Test
    fun `login captures session cookie and binds identity`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)

        val identity = client.identity
        assertNotNull(identity)
        assertEquals("admin_en", identity!!.username)
        assertEquals("demo", identity.tenantId)

        val login = transport.requests.first()
        assertEquals("POST", login.method)
        assertEquals("application/x-www-form-urlencoded", login.contentType)
        val form = String(login.body!!)
        assertTrue(form.contains("username=admin_en"))
        assertTrue(form.contains("tenant_id=demo"))
    }

    @Test
    fun `login rejects non-303 as error with http code`() {
        val transport = FakeAdminTransport()
        transport.stub("POST", "/admin/login", AdminHttpResponse(401, "unauthorized"))
        val client = AdminApiClient("http://test", transport)
        val result = client.login("x", "y", "demo")
        assertTrue(result is AdminApiResult.Error)
        assertEquals(401, (result as AdminApiResult.Error).httpCode)
        assertNull(client.identity)
    }

    @Test
    fun `session cookie is sent on subsequent calls`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub("GET", "/admin/studio/skus", AdminHttpResponse(200, """{"items":[]}"""))

        client.listSkus()

        val listReq = transport.requests.last()
        assertEquals("session=abc123", listReq.headers["Cookie"])
    }

    // ── SKU list / create ────────────────────────────────────────────────────

    @Test
    fun `listSkus parses sku summaries with detection points and regions`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "GET", "/admin/studio/skus",
            AdminHttpResponse(
                200,
                """{"items":[{"id":"sku1","item_number":"FLW-001","name":"Brooch",
                    "status":"draft","standard_status":"standard_active",
                    "active_revision_id":"rev1","detection_point_count":1,
                    "photos":[{"id":"p1","url":"/admin/studio/photos/p1","view_type":"front","is_primary":true}],
                    "detection_points":[{"id":"dp1","point_code":"DP-1","label":"Stones",
                        "method_hint":"counting","expected_value":"12","severity":"major",
                        "regions":[{"image_id":"p1","x":0.1,"y":0.2,"w":0.3,"h":0.4}]}]}]}""",
            ),
        )

        val result = client.listSkus(query = "FLW", status = "draft")
        assertTrue(result is AdminApiResult.Ok)
        val sku = (result as AdminApiResult.Ok).value.single()
        assertEquals("FLW-001", sku.itemNumber)
        assertEquals("draft", sku.status)
        assertEquals(1, sku.photos.size)
        val dp = sku.detectionPoints.single()
        assertEquals("counting", dp.methodHint)
        assertEquals(Region("p1", 0.1f, 0.2f, 0.3f, 0.4f), dp.regions.single())

        // Query params carried through.
        assertTrue(transport.requests.last().url.contains("q=FLW"))
        assertTrue(transport.requests.last().url.contains("status=draft"))
    }

    @Test
    fun `createSku posts tenant-scoped body and returns id`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub("POST", "/api/v1/sku", AdminHttpResponse(201, """{"id":"sku9","tenant_id":"demo","item_number":"A","name":"B","category":null,"description":null,"status":"active","created_at":"2026-01-01T00:00:00"}"""))

        val result = client.createSku("A", "B", null, null)
        assertEquals("sku9", (result as AdminApiResult.Ok).value)
        val body = String(transport.requests.last().body!!)
        assertTrue(body.contains("\"tenant_id\":\"demo\""))
        assertTrue(body.contains("\"item_number\":\"A\""))
    }

    @Test
    fun `backend error detail is surfaced`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "POST", "/api/v1/sku",
            AdminHttpResponse(409, """{"detail":"item_number 'A' already exists for tenant 'demo'"}"""),
        )
        val result = client.createSku("A", "B", null, null)
        assertTrue(result is AdminApiResult.Error)
        assertTrue((result as AdminApiResult.Error).message.contains("already exists"))
    }

    // ── upload ───────────────────────────────────────────────────────────────

    @Test
    fun `uploadStandardPhoto sends multipart body with sku and file`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "POST", "/admin/studio/upload",
            AdminHttpResponse(200, """{"status":"uploaded","photo_id":"p7"}"""),
        )

        val result = client.uploadStandardPhoto("sku1", "ref.jpg", "image/jpeg", byteArrayOf(1, 2, 3))
        assertEquals("p7", (result as AdminApiResult.Ok).value)

        val req = transport.requests.last()
        assertTrue(req.contentType!!.startsWith("multipart/form-data; boundary="))
        val body = String(req.body!!, Charsets.ISO_8859_1)
        assertTrue(body.contains("name=\"sku_id\""))
        assertTrue(body.contains("sku1"))
        assertTrue(body.contains("filename=\"ref.jpg\""))
        assertTrue(body.contains("Content-Type: image/jpeg"))
    }

    // ── bundles / workstations ───────────────────────────────────────────────

    @Test
    fun `publishBundle attributes the acting admin`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "POST", "/admin/studio/publish",
            AdminHttpResponse(200, """{"status":"published","bundle":{"id":"b1"}}"""),
        )
        val result = client.publishBundle("sku1")
        assertEquals("b1", (result as AdminApiResult.Ok).value)
        assertTrue(String(transport.requests.last().body!!).contains("\"published_by\":\"admin_en\""))
    }

    @Test
    fun `listWorkstations parses sync state`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "GET", "/api/qc/workstations",
            AdminHttpResponse(
                200,
                """[{"id":"w1","workstation_id":"WS-01","display_name":"Line 1","site_or_line":"A",
                    "paired_status":"paired","assigned_bundle_version":"v2",
                    "installed_bundle_version":"v2","last_seen_at":"2026-07-13T00:00:00","in_sync":true}]""",
            ),
        )
        val result = client.listWorkstations()
        val ws = (result as AdminApiResult.Ok).value.single()
        assertTrue(ws.inSync)
        assertEquals("v2", ws.installedBundleVersion)
    }

    @Test
    fun `assignBundle posts assigned_by identity`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "POST", "/api/qc/workstations/w1/assign",
            AdminHttpResponse(201, """{"id":"w1","workstation_id":"WS-01","display_name":"Line 1","paired_status":"paired","in_sync":false}"""),
        )
        client.assignBundle("w1", "b1")
        val body = String(transport.requests.last().body!!)
        assertTrue(body.contains("\"assigned_by\":\"admin_en\""))
        assertTrue(body.contains("\"bundle_pk\":\"b1\""))
    }

    // ── results ──────────────────────────────────────────────────────────────

    @Test
    fun `listResults parses verdicts`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "GET", "/api/qc/results",
            AdminHttpResponse(
                200,
                """[{"submission_id":"s1","server_overall_result":"fail",
                    "pad_overall_result":"pass","agrees":false,"review_required":true,
                    "standard_revision_id":"rev1","bundle_version":"v1",
                    "failing_checkpoints":["DP-2"],"human_final_decision":null,
                    "recomputed_at":"2026-07-13T00:00:00"}]""",
            ),
        )
        val v = (client.listResults() as AdminApiResult.Ok).value.single()
        assertFalse(v.agrees)
        assertTrue(v.reviewRequired)
        assertEquals(listOf("DP-2"), v.failingCheckpoints)
    }

    @Test
    fun `recordFinalDecision posts decided_by identity`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "POST", "/api/qc/results/s1/final-decision",
            AdminHttpResponse(
                201,
                """{"submission_id":"s1","server_overall_result":"fail","pad_overall_result":"pass",
                    "agrees":false,"review_required":true,"standard_revision_id":"rev1",
                    "human_final_decision":"fail"}""",
            ),
        )
        client.recordFinalDecision("s1", "fail", "confirmed defect")
        val body = String(transport.requests.last().body!!)
        assertTrue(body.contains("\"decided_by\":\"admin_en\""))
        assertTrue(body.contains("\"decision\":\"fail\""))
    }

    // ── labeled backend-pending stubs ────────────────────────────────────────

    @Test
    fun `region persistence and jetson health and probation are labeled backend-pending`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)

        listOf(
            client.saveDetectionPointRegions("dp1", emptyList()),
            client.fetchJetsonHealth(),
            client.fetchProbation("rev1"),
        ).forEach { result ->
            assertTrue(result is AdminApiResult.Error)
            val message = (result as AdminApiResult.Error).message
            assertTrue(message, message.startsWith("backend-pending"))
            assertTrue(message, message.contains("docs/api-contracts/"))
        }
        // And crucially: no network request was fabricated for them.
        assertEquals(1, transport.requests.size) // only the login
    }
}
