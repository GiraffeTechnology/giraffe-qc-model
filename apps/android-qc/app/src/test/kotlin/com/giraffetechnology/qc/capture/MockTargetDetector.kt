package com.giraffetechnology.qc.capture

import com.giraffetechnology.qc.camera.CameraFrame

/**
 * Scriptable mock detector for unit tests. Accepts an ordered sequence of TargetDetection outputs
 * (one per detect() call) so tests can drive all state-machine transitions.
 * After the sequence is exhausted the last element is repeated indefinitely.
 */
class MockTargetDetector(
    private val sequence: List<TargetDetection>,
) : TargetDetector {

    private var index = 0

    override fun detect(frame: CameraFrame): TargetDetection {
        if (sequence.isEmpty()) return NO_CANDIDATE
        val result = sequence[index.coerceIn(0, sequence.lastIndex)]
        if (index < sequence.lastIndex) index++
        return result
    }

    fun reset() { index = 0 }

    companion object {
        private val NO_CANDIDATE = TargetDetection(
            hasCandidate = false, confidence = 0f,
            boundingBox = null, quality = FrameQuality.GOOD, reason = "no_candidate",
        )

        private fun noFrame() = NO_CANDIDATE
        private fun goodFrame(box: NormalizedBox = NormalizedBox.DEFAULT) =
            TargetDetection(true, 0.9f, box, FrameQuality.GOOD)
        private fun badQualityFrame(box: NormalizedBox = NormalizedBox.DEFAULT) =
            TargetDetection(true, 0.9f, box, FrameQuality.BAD)
        private fun movedBox(ref: NormalizedBox) = ref.copy(x = ref.x + 0.25f, y = ref.y + 0.25f)

        fun noCandidateForever(): MockTargetDetector =
            MockTargetDetector(List(1000) { noFrame() })

        fun singleFrameCandidate(box: NormalizedBox = NormalizedBox.DEFAULT): MockTargetDetector =
            MockTargetDetector(
                listOf(goodFrame(box)) + List(200) { noFrame() }
            )

        fun stableCandidate(count: Int, box: NormalizedBox = NormalizedBox.DEFAULT): MockTargetDetector =
            MockTargetDetector(List(count) { goodFrame(box) })

        fun candidateThenMove(stableCount: Int, box: NormalizedBox = NormalizedBox.DEFAULT): MockTargetDetector =
            MockTargetDetector(
                List(stableCount) { goodFrame(box) } +
                List(200) { goodFrame(movedBox(box)) }
            )

        fun stableWithOneBadQualityFrame(
            totalCount: Int,
            badAt: Int,
            box: NormalizedBox = NormalizedBox.DEFAULT,
        ): MockTargetDetector =
            MockTargetDetector(
                List(totalCount) { i ->
                    if (i == badAt) badQualityFrame(box) else goodFrame(box)
                }
            )

        fun persistentBadQuality(count: Int, box: NormalizedBox = NormalizedBox.DEFAULT): MockTargetDetector =
            MockTargetDetector(List(count) { badQualityFrame(box) })
    }
}
