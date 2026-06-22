package com.giraffetechnology.qc.sku

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

private class FakeMatcher(
    initialState: MnnRuntimeState = MnnRuntimeState.NotReady,
    private val matchResult: SkuMatchResult = SkuMatchResult(
        status            = MatchStatus.MNN_PENDING,
        candidates        = emptyList(),
        capturedImagePath = "/tmp/capture.jpg",
    ),
) : SkuMatcher {
    private val _runtimeState = MutableStateFlow(initialState)
    override val runtimeState: StateFlow<MnnRuntimeState> = _runtimeState
    fun setState(state: MnnRuntimeState) { _runtimeState.value = state }
    override suspend fun match(capturedImagePath: String): SkuMatchResult = matchResult
}

class TaskSelectionControllerTest {

    private val testSku = Sku(id = "sku-1", itemNumber = "ITEM-001", name = "Test Widget")
    private lateinit var repo: FakeSkuRepository
    private lateinit var matcher: FakeMatcher
    private lateinit var ctrl: TaskSelectionController

    @Before fun setUp() {
        repo    = FakeSkuRepository(listOf(testSku))
        matcher = FakeMatcher(MnnRuntimeState.NotReady)
        ctrl    = TaskSelectionController(repo, matcher)
    }

    // 1. starts in Idle
    @Test fun `starts in Idle`() = runTest {
        assertEquals(TaskSelectionState.Idle, ctrl.state.value)
    }

    // 2. manual search success — emits SearchingBackend then ManualResults
    @Test fun `searchByItemNumber emits SearchingBackend then ManualResults`() = runTest {
        ctrl.searchByItemNumber("ITEM")
        val s = ctrl.state.value
        assertTrue("expected ManualResults but was $s", s is TaskSelectionState.ManualResults)
        assertTrue((s as TaskSelectionState.ManualResults).results.any { it.itemNumber == "ITEM-001" })
    }

    // 3. manual search empty
    @Test fun `searchByItemNumber returns empty ManualResults when no match`() = runTest {
        ctrl.searchByItemNumber("ZZZNOMATCH")
        val s = ctrl.state.value
        assertTrue(s is TaskSelectionState.ManualResults)
        assertTrue((s as TaskSelectionState.ManualResults).results.isEmpty())
    }

    // 4. backend error — repo throws
    @Test fun `searchByItemNumber emits BackendError on repo throw`() = runTest {
        val failRepo = object : SkuRepository {
            override suspend fun findByItemNumber(query: String): List<Sku> =
                throw RuntimeException("Network error")
            override suspend fun getById(id: String): Sku? = null
        }
        val ctrl2 = TaskSelectionController(failRepo, matcher)
        ctrl2.searchByItemNumber("X")
        val s = ctrl2.state.value
        assertTrue("expected BackendError but was $s", s is TaskSelectionState.BackendError)
    }

    // 5. MNN not ready emits MnnPending
    @Test fun `runMatch with MNN not ready emits MnnPending`() = runTest {
        ctrl.runMatch("/tmp/photo.jpg")
        assertEquals(TaskSelectionState.MnnPending, ctrl.state.value)
    }

    // 6. MNN ready clear candidate emits MatchCandidates, no auto-confirm
    @Test fun `runMatch with MNN ready and OK status emits MatchCandidates`() = runTest {
        val expected = SkuMatchResult(
            status            = MatchStatus.OK,
            candidates        = listOf(SkuCandidate(testSku, 0.9f, "/tmp/std.jpg")),
            capturedImagePath = "/tmp/capture.jpg",
        )
        val readyMatcher = FakeMatcher(MnnRuntimeState.Ready, expected)
        val ctrl2 = TaskSelectionController(repo, readyMatcher)
        ctrl2.runMatch("/tmp/capture.jpg")
        val s = ctrl2.state.value
        assertTrue("expected MatchCandidates but was $s", s is TaskSelectionState.MatchCandidates)
        assertFalse("must not auto-confirm", s is TaskSelectionState.TaskConfirmed)
    }

    // 7. operator confirms candidate — emits TaskConfirmed
    @Test fun `confirmCandidate emits TaskConfirmed with MNN_PHOTO_MATCH`() {
        val candidate = SkuCandidate(testSku, 0.9f, "/tmp/std.jpg")
        ctrl.confirmCandidate(candidate)
        val s = ctrl.state.value
        assertTrue(s is TaskSelectionState.TaskConfirmed)
        val task = (s as TaskSelectionState.TaskConfirmed).task
        assertEquals(SkuResolutionMethod.MNN_PHOTO_MATCH, task.resolvedBy)
        assertTrue(task.confirmedByUser)
    }

    // 8. ambiguous match emits ReviewRequired
    @Test fun `runMatch with REVIEW_REQUIRED status emits ReviewRequired`() = runTest {
        val reviewResult = SkuMatchResult(
            status            = MatchStatus.REVIEW_REQUIRED,
            candidates        = emptyList(),
            capturedImagePath = "/tmp/capture.jpg",
        )
        val readyMatcher = FakeMatcher(MnnRuntimeState.Ready, reviewResult)
        val ctrl2 = TaskSelectionController(repo, readyMatcher)
        ctrl2.runMatch("/tmp/capture.jpg")
        assertTrue(ctrl2.state.value is TaskSelectionState.ReviewRequired)
    }

    // 9. no match emits NoMatch
    @Test fun `runMatch with NO_MATCH status emits NoMatch`() = runTest {
        val noMatchResult = SkuMatchResult(
            status            = MatchStatus.NO_MATCH,
            candidates        = emptyList(),
            capturedImagePath = "/tmp/capture.jpg",
        )
        val readyMatcher = FakeMatcher(MnnRuntimeState.Ready, noMatchResult)
        val ctrl2 = TaskSelectionController(repo, readyMatcher)
        ctrl2.runMatch("/tmp/capture.jpg")
        assertEquals(TaskSelectionState.NoMatch, ctrl2.state.value)
    }

    // 10. manual confirmation sets confirmedByUser = true
    @Test fun `confirmManual sets confirmedByUser true`() {
        ctrl.confirmManual(testSku, SkuResolutionMethod.MANUAL_ITEM_NUMBER)
        val s = ctrl.state.value
        assertTrue(s is TaskSelectionState.TaskConfirmed)
        val task = (s as TaskSelectionState.TaskConfirmed).task
        assertTrue(task.confirmedByUser)
        assertEquals(SkuResolutionMethod.MANUAL_ITEM_NUMBER, task.resolvedBy)
    }

    @Test fun `reset returns to Idle`() = runTest {
        ctrl.searchByItemNumber("ITEM")
        ctrl.reset()
        assertEquals(TaskSelectionState.Idle, ctrl.state.value)
    }
}
