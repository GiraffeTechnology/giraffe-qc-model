package com.giraffetechnology.qc.sku

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class TaskSelectionControllerTest {

    // ── Test fakes ──────────────────────────────────────────────────────

    private val testSkus = listOf(
        Sku("sku-1", "GH-1001", "Widget A", listOf("/ref/a1.jpg", "/ref/a2.jpg")),
        Sku("sku-2", "GH-1002", "Widget B", listOf("/ref/b1.jpg")),
        Sku("sku-3", "GH-2000", "Gadget X", listOf("/ref/x1.jpg")),
    )

    private val config = SkuMatchConfig(confirmThreshold = 0.75f, ambiguityGap = 0.05f, maxCandidates = 3)

    private inner class FakeMatcher(
        private val result: SkuMatchResult,
        private val ready: Boolean = true,
    ) : SkuMatcher {
        private val _state = MutableStateFlow<MnnRuntimeState>(
            if (ready) MnnRuntimeState.Ready else MnnRuntimeState.NotReady
        )
        override val runtimeState: StateFlow<MnnRuntimeState> = _state.asStateFlow()
        override suspend fun match(capturedImagePath: String): SkuMatchResult = result
    }

    private fun okMatcher(top1: Float, top2: Float? = null): FakeMatcher {
        val candidates = mutableListOf(
            SkuCandidate(testSkus[0], top1, "/ref/a1.jpg"),
        )
        if (top2 != null) candidates.add(SkuCandidate(testSkus[1], top2, "/ref/b1.jpg"))

        val gap = top1 - (top2 ?: 0f)
        val status = when {
            top1 < config.confirmThreshold -> MatchStatus.REVIEW_REQUIRED
            gap < config.ambiguityGap      -> MatchStatus.REVIEW_REQUIRED
            else                           -> MatchStatus.OK
        }
        return FakeMatcher(SkuMatchResult(status, candidates, "/captured.jpg"))
    }

    private fun pendingMatcher() = FakeMatcher(
        SkuMatchResult(MatchStatus.MNN_PENDING, emptyList(), "/captured.jpg"),
        ready = false,
    )

    private fun noMatchMatcher() = FakeMatcher(
        SkuMatchResult(MatchStatus.NO_MATCH, emptyList(), "/captured.jpg")
    )

    private fun makeController(matcher: SkuMatcher = pendingMatcher()): TaskSelectionController =
        TaskSelectionController(FakeSkuRepository(testSkus), matcher)

    // 1. Manual item-number search returns SKUs
    @Test
    fun `manual search by item number returns matching SKUs`() = runTest {
        val ctrl = makeController()
        ctrl.searchByItemNumber("GH-1")
        val state = ctrl.state.value
        assertTrue("Expected ManualResults, got $state", state is TaskSelectionState.ManualResults)
        val results = (state as TaskSelectionState.ManualResults).results
        assertTrue(results.any { it.itemNumber == "GH-1001" })
        assertTrue(results.any { it.itemNumber == "GH-1002" })
        assertFalse(results.any { it.itemNumber == "GH-2000" })
    }

    // 2. MNN Ready + clear Top1 -> MatchCandidates (NOT auto-confirm)
    @Test
    fun `MNN Ready clear Top1 enters MatchCandidates not auto-confirmed`() = runTest {
        val ctrl = makeController(okMatcher(top1 = 0.92f, top2 = 0.50f))
        ctrl.runMatch("/captured.jpg")
        val state = ctrl.state.value
        assertTrue("Expected MatchCandidates, got $state", state is TaskSelectionState.MatchCandidates)
        assertFalse(
            "Must NOT auto-confirm even at high similarity",
            state is TaskSelectionState.TaskConfirmed,
        )
        val result = (state as TaskSelectionState.MatchCandidates).result
        assertEquals(MatchStatus.OK, result.status)
    }

    // 3. Operator taps confirm -> TaskConfirmed with confirmedByUser=true, MNN_PHOTO_MATCH
    @Test
    fun `operator confirm candidate produces TaskConfirmed with correct fields`() = runTest {
        val ctrl = makeController(okMatcher(top1 = 0.92f, top2 = 0.50f))
        ctrl.runMatch("/captured.jpg")
        assertTrue(ctrl.state.value is TaskSelectionState.MatchCandidates)

        val candidate = (ctrl.state.value as TaskSelectionState.MatchCandidates).result.candidates.first()
        ctrl.confirmCandidate(candidate)

        val state = ctrl.state.value
        assertTrue("Expected TaskConfirmed, got $state", state is TaskSelectionState.TaskConfirmed)
        val task = (state as TaskSelectionState.TaskConfirmed).task
        assertTrue(task.confirmedByUser)
        assertEquals(SkuResolutionMethod.MNN_PHOTO_MATCH, task.resolvedBy)
        assertEquals(candidate.sku.skuId, task.sku.skuId)
    }

    // 4. MNN not ready -> MnnPending, manual path still works
    @Test
    fun `MNN not ready gives MnnPending and manual path still works`() = runTest {
        val ctrl = makeController(pendingMatcher())
        ctrl.runMatch("/captured.jpg")
        assertEquals(TaskSelectionState.MnnPending, ctrl.state.value)

        // Manual path must still be usable after MNN_PENDING
        ctrl.searchByItemNumber("Widget")
        assertTrue(ctrl.state.value is TaskSelectionState.ManualResults)
    }

    // 5. Top1 approx Top2 (within ambiguityGap) -> REVIEW_REQUIRED, no auto-confirm
    @Test
    fun `ambiguous top1 top2 gives REVIEW_REQUIRED not auto-confirm`() = runTest {
        val gap = config.ambiguityGap / 2  // inside ambiguity gap
        val top1 = 0.85f
        val top2 = top1 - gap
        val ctrl = makeController(okMatcher(top1 = top1, top2 = top2))
        ctrl.runMatch("/captured.jpg")

        val state = ctrl.state.value
        assertTrue("Expected MatchCandidates, got $state", state is TaskSelectionState.MatchCandidates)
        val result = (state as TaskSelectionState.MatchCandidates).result
        assertEquals(MatchStatus.REVIEW_REQUIRED, result.status)
        assertFalse(state is TaskSelectionState.TaskConfirmed)
    }

    // 6. No match over threshold -> NO_MATCH, guides operator to manual
    @Test
    fun `no match returns MatchCandidates with NO_MATCH status`() = runTest {
        val ctrl = makeController(noMatchMatcher())
        ctrl.runMatch("/captured.jpg")
        val state = ctrl.state.value
        assertTrue("Expected MatchCandidates, got $state", state is TaskSelectionState.MatchCandidates)
        assertEquals(MatchStatus.NO_MATCH, (state as TaskSelectionState.MatchCandidates).result.status)
    }
}
