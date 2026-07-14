package com.giraffetechnology.qc.admin

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AdminLoginControllerTest {

    @Test
    fun `blank credentials never hit the network`() {
        val transport = FakeAdminTransport()
        val controller = AdminLoginController(AdminApiClient("http://test", transport))
        controller.login("", "", "demo")
        val state = controller.state.value
        assertTrue(state is AdminLoginState.Error)
        assertEquals("admin.login.error.missing_fields", (state as AdminLoginState.Error).messageKey)
        assertEquals(0, transport.requests.size)
    }

    @Test
    fun `successful login reaches LoggedIn with identity`() {
        val transport = FakeAdminTransport()
        transport.stub(
            "POST", "/admin/login",
            AdminHttpResponse(303, null, mapOf("set-cookie" to listOf("session=s1; Path=/"))),
        )
        val controller = AdminLoginController(AdminApiClient("http://test", transport))
        controller.login("admin_en", "admin_en", "demo")
        val state = controller.state.value
        assertTrue(state is AdminLoginState.LoggedIn)
        assertEquals("admin_en", (state as AdminLoginState.LoggedIn).identity.username)
    }

    @Test
    fun `401 maps to the invalid-credentials key`() {
        val transport = FakeAdminTransport()
        transport.stub("POST", "/admin/login", AdminHttpResponse(401, "no"))
        val controller = AdminLoginController(AdminApiClient("http://test", transport))
        controller.login("x", "wrong", "demo")
        val state = controller.state.value as AdminLoginState.Error
        assertEquals("admin.login.error.invalid", state.messageKey)
    }

    @Test
    fun `logout clears identity`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        val controller = AdminLoginController(client)
        controller.logout()
        assertTrue(controller.state.value is AdminLoginState.Idle)
        assertEquals(null, client.identity)
    }
}

class AdminSkuControllerTest {

    @Test
    fun `refresh loads sku list`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "GET", "/admin/studio/config",
            AdminHttpResponse(200, """{"sku_lifecycle_states":["draft","needs_information","ready_for_review","confirmed","published","installed","needs_requalification"]}"""),
        )
        transport.stub(
            "GET", "/admin/studio/skus",
            AdminHttpResponse(200, """{"items":[{"id":"s1","item_number":"A","name":"N","status":"draft","standard_status":"no_standard"}]}"""),
        )
        val controller = AdminSkuController(client)
        controller.refresh()
        val state = controller.listState.value as AdminSkuListState.Loaded
        assertEquals("A", state.skus.single().itemNumber)
    }

    @Test
    fun `create requires item number and name`() {
        val transport = FakeAdminTransport()
        val controller = AdminSkuController(loggedInClient(transport))
        controller.create("", "name", null, null)
        assertTrue(controller.createState.value is AdminSkuCreateState.Error)
        assertEquals(1, transport.requests.size) // login only — no create call
    }

    @Test
    fun `create success refreshes list and selects the new sku`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub("POST", "/admin/studio/skus", AdminHttpResponse(201, """{"id":"s2"}"""))
        transport.stub(
            "GET", "/admin/studio/config",
            AdminHttpResponse(200, """{"sku_lifecycle_states":["draft","needs_information","ready_for_review","confirmed","published","installed","needs_requalification"]}"""),
        )
        transport.stub("GET", "/admin/studio/skus", AdminHttpResponse(200, """{"items":[]}"""))
        transport.stub(
            "GET", "/admin/studio/skus/s2",
            AdminHttpResponse(200, """{"id":"s2","item_number":"B","name":"N2","status":"draft","standard_status":"no_standard"}"""),
        )
        val controller = AdminSkuController(client)
        controller.create("B", "N2", null, null)
        assertTrue(controller.createState.value is AdminSkuCreateState.Created)
        assertEquals("s2", controller.selected.value?.id)
    }

    @Test
    fun `lifecycle states load from the shared backend config`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "GET", "/admin/studio/config",
            AdminHttpResponse(200, """{"sku_lifecycle_states":["draft","needs_information","ready_for_review","confirmed","published","installed","needs_requalification"]}"""),
        )
        transport.stub("GET", "/admin/studio/skus", AdminHttpResponse(200, """{"items":[]}"""))
        val controller = AdminSkuController(client)
        controller.refresh()
        assertEquals(
            listOf(
                "draft", "needs_information", "ready_for_review", "confirmed",
                "published", "installed", "needs_requalification",
            ),
            (controller.configState.value as AdminSkuConfigState.Loaded).lifecycleStates,
        )
    }
}

class AdminStandardControllerTest {

    @Test
    fun `process card requires a training pack before opening the real flow`() {
        val transport = FakeAdminTransport()
        val controller = AdminStandardController(loggedInClient(transport))
        controller.uploadProcessCard("", "card.txt", "text/plain", "step one".toByteArray())
        val state = controller.processCardUploadState.value
        assertTrue(state is AdminProcessCardUploadState.Error)
        assertEquals(1, transport.requests.size) // login only
    }

    @Test
    fun `process card upload reaches Source Workbench and reports stored`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "POST", "/admin/qc-model/training-packs/tp1/sources/upload",
            AdminHttpResponse(303, null, mapOf("location" to listOf("/sources"))),
        )
        val controller = AdminStandardController(client)
        controller.uploadProcessCard(
            "tp1", "card.txt", "text/plain", "step one".toByteArray(),
        )
        val state = controller.processCardUploadState.value
        assertTrue(state is AdminProcessCardUploadState.Uploaded)
        assertEquals("tp1", (state as AdminProcessCardUploadState.Uploaded).trainingPackId)
    }

    @Test
    fun `counting point without expected count is rejected before the network`() {
        val transport = FakeAdminTransport()
        val controller = AdminStandardController(loggedInClient(transport))
        controller.addDetectionPoint("s1", "DP-1", "Stones", null, "counting", null, "major")
        val state = controller.pointState.value as AdminPointEditState.Error
        assertTrue(state.message.contains("expected count"))
        assertEquals(1, transport.requests.size) // login only
    }

    @Test
    fun `valid point posts and reports saved`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "POST", "/api/v1/sku/s1/detection-points",
            AdminHttpResponse(201, """{"id":"dp1","sku_id":"s1","point_code":"DP-1"}"""),
        )
        val controller = AdminStandardController(client)
        controller.addDetectionPoint("s1", "DP-1", "Stones", null, "counting", "12", "major")
        assertEquals("dp1", (controller.pointState.value as AdminPointEditState.Saved).pointId)
    }

    @Test
    fun `invalid regions fail closed without queueing`() {
        val transport = FakeAdminTransport()
        val store = PendingRegionStore()
        val controller = AdminStandardController(loggedInClient(transport), store)
        controller.saveRegions(
            "dp1",
            listOf(Region("unknown-photo", 0.1f, 0.1f, 0.2f, 0.2f)),
            validImageIds = setOf("p1"),
        )
        assertTrue(controller.regionState.value is AdminRegionSaveState.Invalid)
        assertEquals(emptyList<Region>(), store.get("dp1"))
    }

    @Test
    fun `valid regions persist through the real studio route`() {
        val transport = FakeAdminTransport()
        val store = PendingRegionStore()
        val client = loggedInClient(transport)
        transport.stub(
            "POST", "/admin/studio/detection-points/dp1/regions",
            AdminHttpResponse(200, """{"status":"regions_saved","detection_point_id":"dp1","regions":[]}"""),
        )
        val controller = AdminStandardController(client, store)
        val regions = listOf(Region("p1", 0.1f, 0.1f, 0.2f, 0.2f))
        controller.saveRegions("dp1", regions, validImageIds = setOf("p1"))
        val state = controller.regionState.value
        assertTrue(state is AdminRegionSaveState.SavedToServer)
        assertEquals(emptyList<Region>(), store.get("dp1"))
    }
}

class AdminResultsControllerTest {

    @Test
    fun `refresh loads verdicts and suspensions together`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "GET", "/api/qc/results",
            AdminHttpResponse(200, """[{"submission_id":"s1","server_overall_result":"pass","pad_overall_result":"pass","agrees":true,"review_required":false,"standard_revision_id":"r1"}]"""),
        )
        transport.stub(
            "GET", "/api/qc/suspensions",
            AdminHttpResponse(200, """{"suspensions":[{"id":"su1","training_pack_id":"tp1","status":"active","reason":"false_pass"}]}"""),
        )
        val controller = AdminResultsController(client)
        controller.refresh()
        val state = controller.state.value as AdminResultsState.Loaded
        assertEquals(1, state.verdicts.size)
        assertEquals("false_pass", state.suspensions.single().reason)
    }

    @Test
    fun `decision saved refreshes and exposes the verdict`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "POST", "/api/qc/results/s1/final-decision",
            AdminHttpResponse(201, """{"submission_id":"s1","server_overall_result":"fail","pad_overall_result":"pass","agrees":false,"review_required":true,"standard_revision_id":"r1","human_final_decision":"fail"}"""),
        )
        transport.stub("GET", "/api/qc/results", AdminHttpResponse(200, "[]"))
        transport.stub("GET", "/api/qc/suspensions", AdminHttpResponse(200, """{"suspensions":[]}"""))
        val controller = AdminResultsController(client)
        controller.recordDecision("s1", "fail", "defect confirmed")
        val decision = controller.decision.value as AdminDecisionState.Saved
        assertEquals("fail", decision.verdict.humanFinalDecision)
    }
}

class AdminHealthControllerTest {
    private class FakeSource(initial: PadHealthState) : PadHealthStateSource {
        private val mutable = MutableStateFlow(initial)
        override val state: StateFlow<PadHealthState> = mutable
        var refreshes = 0
        override suspend fun refresh() { refreshes += 1 }
    }

    @Test
    fun `controller consumes one v2 health source without collapsing subsystems`() = runBlocking {
        val snapshot = PadHealthState(
            observedAt = "2026-07-14T00:00:00Z",
            operatorPipelineReadiness = "ready",
            canStartJob = true,
            nanoCv = NanoCvHealth(status = "ready", lastCvDurationMs = 120),
            cloudLink = CloudLinkHealth(
                state = "healthy", cloudService = "reachable", acceptingJobs = true,
                currentNetwork = "wifi", effectiveUplinkMbps = 8.0,
            ),
            offlineQueue = OfflineQueueHealth(pendingUploadJobs = 0),
            xavierAdmin = XavierAdminHealth(
                status = "ready", runtimeEngine = "mnn", modelName = "configured-vlm",
                modelLoaded = true,
            ),
        )
        val source = FakeSource(snapshot)
        val controller = AdminHealthController(source)
        controller.refresh()
        assertEquals(1, source.refreshes)
        assertEquals("ready", controller.state.value.snapshot.nanoCv.status)
        assertEquals("wifi", controller.state.value.snapshot.cloudLink.currentNetwork)
        assertEquals("configured-vlm", controller.state.value.snapshot.xavierAdmin.modelName)
    }

    @Test
    fun `backend pending source fails closed with null measurements`() = runBlocking {
        val controller = AdminHealthController(BackendPendingPadHealthStateSource())
        controller.refresh()
        val state = controller.state.value.snapshot
        assertEquals("unknown", state.operatorPipelineReadiness)
        assertTrue(!state.canStartJob)
        assertEquals(null, state.nanoCv.lastCvDurationMs)
        assertEquals(null, state.cloudLink.effectiveUplinkMbps)
        assertEquals("not_configured", state.xavierAdmin.status)
        assertTrue(state.limitations.all { it.startsWith("TODO(backend-pending)") })
    }
}

class AdminProbationControllerTest {

    @Test
    fun `suspensions and live probation gate load together`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "GET", "/api/qc/suspensions",
            AdminHttpResponse(200, """{"suspensions":[{"id":"su1","training_pack_id":"tp1","status":"active","reason":"false_pass"}]}"""),
        )
        transport.stub(
            "GET", "/api/qc/probation/by-revision/r1",
            AdminHttpResponse(200, probationJson(status = "active")),
        )
        val controller = AdminProbationController(client)
        controller.refresh("r1")
        val state = controller.state.value as AdminProbationState.Loaded
        val probation = requireNotNull(state.probation)
        assertEquals(1, state.suspensions.size)
        assertEquals(24, probation.gate.jobsRecorded)
        assertEquals("active", probation.status)
    }

    @Test
    fun `pause uses server transition and refreshes without optimistic state`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub("GET", "/api/qc/suspensions", AdminHttpResponse(200, """{"suspensions":[]}"""))
        transport.stub("GET", "/api/qc/probation/by-revision/r1", AdminHttpResponse(200, probationJson("active")))
        transport.stub("POST", "/api/qc/probation/p1/pause", AdminHttpResponse(200, probationJson("paused")))
        val controller = AdminProbationController(client)
        controller.refresh("r1")
        controller.pause()
        assertTrue(transport.requests.any { it.method == "POST" && it.url.contains("/p1/pause") })
        assertTrue(controller.mutation.value is AdminProbationMutationState.Idle)
    }

    @Test
    fun `disagreement report is loaded from server`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub("GET", "/api/qc/suspensions", AdminHttpResponse(200, """{"suspensions":[]}"""))
        transport.stub("GET", "/api/qc/probation/by-revision/r1", AdminHttpResponse(200, probationJson("active")))
        transport.stub(
            "GET", "/api/qc/probation/p1/disagreement-report",
            AdminHttpResponse(
                200,
                """{"probation_id":"p1","standard_revision_id":"r1","status":"active",
                    "gate":{},"disagreements":1,
                    "detection_points":[{"point_code":"DP-1","disagreement_count":1,"examples":[]}],
                    "jobs":[{"job_ref":"j1","sequence_no":1,"ai_verdict":"pass",
                    "human_final_verdict":"fail","agreed":false,"points":[]}]}""",
            ),
        )
        val controller = AdminProbationController(client)
        controller.refresh("r1")
        controller.loadDisagreementReport()
        val loaded = controller.state.value as AdminProbationState.Loaded
        val report = requireNotNull(loaded.report)
        assertEquals(1, report.disagreements)
        assertEquals("DP-1", report.detectionPoints.single().pointCode)
    }

    private fun probationJson(status: String) =
        """{"probation_id":"p1","tenant_id":"demo","sku_id":"s1",
            "standard_revision_id":"r1","status":"$status","gate":{
            "jobs_recorded":24,"agreements":22,"agreement_rate":0.916666,
            "min_sample_size":30,"agreement_threshold":0.9,"recheck_interval":10,
            "min_sample_met":false,"threshold_met":true,"is_check_due":false,
            "qualified":false}}"""
}

class AdminBundleControllerTest {

    @Test
    fun `publish then refresh lists the new bundle`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "POST", "/admin/studio/publish",
            AdminHttpResponse(200, """{"status":"published","bundle":{"id":"b1"}}"""),
        )
        transport.stub(
            "GET", "/api/qc/bundles",
            AdminHttpResponse(200, """[{"id":"b1","bundle_version":"v1","status":"published","sku_count":1,"created_by":"admin_en","manifest_sha256":"deadbeef","signed":true}]"""),
        )
        val controller = AdminBundleController(client)
        controller.publish("sku1")
        assertEquals("b1", (controller.publish.value as AdminPublishState.Published).bundleId)
        val bundles = (controller.bundles.value as AdminBundleState.Loaded).bundles
        assertTrue(bundles.single().signed)
    }

    @Test
    fun `verifyDownload records the verified manifest hash`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "GET", "/api/qc/bundles/b1/download",
            AdminHttpResponse(200, """{"manifest":{},"signature":"sig","signature_algo":"hmac","manifest_sha256":"cafe1234"}"""),
        )
        val controller = AdminBundleController(client)
        controller.verifyDownload("b1")
        assertEquals("cafe1234", controller.downloadChecks.value["b1"])
    }

    @Test
    fun `tampered bundle download surfaces the verification error`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        transport.stub(
            "GET", "/api/qc/bundles/b1/download",
            AdminHttpResponse(409, """{"detail":{"reason":"signature_mismatch"}}"""),
        )
        val controller = AdminBundleController(client)
        controller.verifyDownload("b1")
        assertTrue(controller.downloadChecks.value["b1"]!!.startsWith("error:"))
    }
}

class AdminWorkstationControllerTest {

    @Test
    fun `register validates required fields locally`() {
        val transport = FakeAdminTransport()
        val controller = AdminWorkstationController(loggedInClient(transport))
        controller.register("", "", null)
        assertTrue(controller.opState.value is AdminWorkstationOpState.Error)
        assertEquals(1, transport.requests.size) // login only
    }

    @Test
    fun `register then assign round-trips through the api`() {
        val transport = FakeAdminTransport()
        val client = loggedInClient(transport)
        val wsJson = """{"id":"w1","workstation_id":"WS-01","display_name":"Line 1","paired_status":"registered","in_sync":false}"""
        transport.stub("POST", "/api/qc/workstations", AdminHttpResponse(201, wsJson))
        transport.stub("GET", "/api/qc/workstations", AdminHttpResponse(200, "[$wsJson]"))
        transport.stub("POST", "/api/qc/workstations/w1/assign", AdminHttpResponse(201, wsJson))
        val controller = AdminWorkstationController(client)
        controller.register("WS-01", "Line 1", "A-line")
        assertTrue(controller.opState.value is AdminWorkstationOpState.Done)
        controller.assign("w1", "b1")
        assertTrue(controller.opState.value is AdminWorkstationOpState.Done)
        val list = (controller.workstations.value as AdminWorkstationState.Loaded).workstations
        assertEquals("WS-01", list.single().workstationId)
    }
}
