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

    @Test
    fun `admin action without bound identity fails before network`() {
        val transport = FakeAdminTransport()
        val client = AdminApiClient("http://test", transport)
        val result = client.createSku("A", "B", null, null)
        assertTrue(result is AdminApiResult.Error)
        assertEquals(401, (result as AdminApiResult.Error).httpCode)
        assertEquals(0, transport.requests.size)
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
        transport.stub("POST", "/admin/studio/skus", AdminHttpResponse(201, """{"id":"sku9","tenant_id":"demo","item_number":"A","name":"B","status":"draft"}"""))

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
            "POST", "/admin/studio/skus",
            AdminHttpResponse(409, """{"detail":"item_number 'A' already exists for tenant 'demo'"}"""),
        )
        val result = client.createSku("A", "B", null, null)
        assertTrue(result is AdminApiResult.Error)
        assertTrue((result as AdminApiResult.Error).message.contains("already exists"))
    }

    @Test
    fun `sku lifecycle states are read from shared Studio config`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "GET", "/admin/studio/config",
            AdminHttpResponse(200, """{"sku_lifecycle_states":["draft","needs_information","ready_for_review","confirmed","published","installed","needs_requalification"]}"""),
        )
        val result = client.fetchSkuLifecycleStates() as AdminApiResult.Ok
        assertEquals("draft", result.value.first())
        assertEquals(7, result.value.size)
    }

    @Test
    fun `detection point edit uses authenticated patch`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "PATCH", "/admin/studio/detection-points/dp1",
            AdminHttpResponse(200, """{"id":"dp1"}"""),
        )
        val result = client.updateDetectionPoint(
            "dp1", "DP-1", "Count", null, "counting", "12", "critical",
        )
        assertEquals("dp1", (result as AdminApiResult.Ok).value)
        assertEquals("PATCH", transport.requests.last().method)
        assertEquals("session=abc123", transport.requests.last().headers["Cookie"])
    }

    @Test
    fun `checkpoint category confirmation carries administrator identity`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "POST", "/api/qc/detection-points/dp1/confirm-category",
            AdminHttpResponse(
                200,
                """{"detection_point_id":"dp1","proposed_checkpoint_category":"visual_defect","confirmed_checkpoint_category":"visual_defect","category_confirmed_by":"admin_en","ai_role":"primary_visual_judge","ai_can_be_primary_judge":true}""",
            ),
        )
        val result = client.confirmDetectionPointCategory("dp1", "visual_defect")
            as AdminApiResult.Ok
        assertTrue(result.value.aiCanBePrimaryJudge)
        assertTrue(String(transport.requests.last().body!!).contains("confirmed_by=admin_en"))
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

    // ── probation API ───────────────────────────────────────────────────────

    @Test
    fun `probation state parses gate and carries authenticated tenant`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "GET", "/api/qc/probation/by-revision/rev1",
            AdminHttpResponse(
                200,
                """{"probation_id":"p1","tenant_id":"demo","sku_id":"s1",
                    "standard_revision_id":"rev1","status":"active","gate":{
                    "jobs_recorded":30,"agreements":28,"agreement_rate":0.9333,
                    "min_sample_size":30,"agreement_threshold":0.9,"recheck_interval":10,
                    "min_sample_met":true,"threshold_met":true,"is_check_due":true,
                    "qualified":false}}""",
            ),
        )
        val result = client.fetchProbation("rev1") as AdminApiResult.Ok
        val probation = result.value
        assertEquals(30, probation.gate.jobsRecorded)
        assertEquals("active", probation.status)
        val request = transport.requests.last()
        assertTrue(request.url.contains("tenant_id=demo"))
        assertEquals("session=abc123", request.headers["Cookie"])
    }

    @Test
    fun `probation pause uses authenticated real endpoint`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "POST", "/api/qc/probation/p1/pause",
            AdminHttpResponse(
                200,
                """{"probation_id":"p1","tenant_id":"demo","sku_id":"s1",
                    "standard_revision_id":"rev1","status":"paused","gate":{
                    "jobs_recorded":0,"agreements":0,"agreement_rate":0.0,
                    "min_sample_size":30,"agreement_threshold":0.9,"recheck_interval":10,
                    "min_sample_met":false,"threshold_met":false,"is_check_due":false,
                    "qualified":false}}""",
            ),
        )
        val result = client.pauseProbation("p1") as AdminApiResult.Ok
        assertEquals("paused", result.value.status)
        assertEquals("session=abc123", transport.requests.last().headers["Cookie"])
    }

    // ── standard authoring APIs ─────────────────────────────────────────────

    @Test
    fun `region persistence posts the normalized model to the real route`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "POST", "/admin/studio/detection-points/dp1/regions",
            AdminHttpResponse(200, """{"status":"regions_saved","detection_point_id":"dp1"}"""),
        )

        val result = client.saveDetectionPointRegions(
            "dp1", listOf(Region("photo1", 0.1f, 0.2f, 0.3f, 0.4f)),
        )
        assertTrue(result is AdminApiResult.Ok)
        val request = transport.requests.last()
        assertTrue(String(request.body!!).contains("\"image_id\":\"photo1\""))
        assertEquals("session=abc123", request.headers["Cookie"])
    }
}
