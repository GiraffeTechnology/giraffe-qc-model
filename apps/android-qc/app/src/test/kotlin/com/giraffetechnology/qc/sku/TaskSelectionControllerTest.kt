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
        status             = MatchStatus.MNN_PENDING,
        candidates         = emptyList(),
        capturedImagePath  = "/tmp/capture.jpg",
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

    @Before
    fun setUp() {
        repo    = FakeSkuRepository(listOf(testSku))
        matcher = FakeMatcher(MnnRuntimeState.NotReady)
        ctrl    = TaskSelectionController(repo, matcher)
    }

    @Test
    fun `starts in Idle`() {
        assertEquals(TaskSelectionState.Idle, ctrl.state.value)
    }

    @Test
    fun `searchByItemNumber emits ManualResults`() = runTest {
        ctrl.searchByItemNumber("ITEM")
        val s = ctrl.state.value
        assertTrue("expected ManualResults but was $s", s is TaskSelectionState.ManualResults)
        val results = (s as TaskSelectionState.ManualResults).results
        assertTrue(results.any { it.itemNumber == "ITEM-001" })
    }

    @Test
    fun `runMatch with MNN not ready emits MnnPending`() = runTest {
        ctrl.runMatch("/tmp/photo.jpg")
        assertEquals(TaskSelectionState.MnnPending, ctrl.state.value)
    }

    @Test
    fun `runMatch with MNN ready emits MatchCandidates`() = runTest {
        val expected = SkuMatchResult(
            status            = MatchStatus.OK,
            candidates        = listOf(SkuCandidate(testSku, 0.9f, "/tmp/std.jpg")),
            capturedImagePath = "/tmp/capture.jpg",
        )
        val readyMatcher = object : SkuMatcher {
            override val runtimeState: StateFlow<MnnRuntimeState> =
                MutableStateFlow(MnnRuntimeState.Ready)
            override suspend fun match(capturedImagePath: String) = expected
        }
        val ctrl2 = TaskSelectionController(repo, readyMatcher)
        ctrl2.runMatch("/tmp/capture.jpg")
        val s = ctrl2.state.value
        assertTrue("expected MatchCandidates but was $s", s is TaskSelectionState.MatchCandidates)
        assertEquals(expected, (s as TaskSelectionState.MatchCandidates).result)
    }

    @Test
    fun `confirmCandidate emits TaskConfirmed with MNN_PHOTO_MATCH`() {
        val candidate = SkuCandidate(testSku, 0.9f, "/tmp/std.jpg")
        ctrl.confirmCandidate(candidate)
        val s = ctrl.state.value
        assertTrue("expected TaskConfirmed but was $s", s is TaskSelectionState.TaskConfirmed)
        val task = (s as TaskSelectionState.TaskConfirmed).task
        assertEquals(SkuResolutionMethod.MNN_PHOTO_MATCH, task.resolvedBy)
        assertEquals(testSku, task.sku)
        assertTrue(task.confirmedByUser)
    }

    @Test
    fun `reset returns to Idle`() = runTest {
        ctrl.searchByItemNumber("ITEM")
        ctrl.reset()
        assertEquals(TaskSelectionState.Idle, ctrl.state.value)
    }
}
