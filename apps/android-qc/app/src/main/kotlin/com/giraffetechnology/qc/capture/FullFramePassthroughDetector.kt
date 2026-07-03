package com.giraffetechnology.qc.capture

import com.giraffetechnology.qc.camera.CameraFrame

/**
 * Full-frame pass-through detector (Work Item 3).
 *
 * When no real target/object detector is provisioned, this passes the ENTIRE
 * frame through to the inspector as the region of interest instead of localizing
 * a specific object. The bounding box is the whole frame (centre 0.5,0.5, size
 * 1.0×1.0) and quality is reported GOOD so the capture pipeline proceeds.
 *
 * This is a documented pass-through, NOT a fabricated detection: it makes no
 * claim about having found a specific target — it explicitly hands the full
 * frame to the on-device inspector, which performs the actual QC judgment. Swap
 * this for a real detector once one is available.
 *
 * Contrast with [PendingTargetDetector], which reports hasCandidate=false and
 * keeps the pipeline in Searching (used when we must NOT auto-capture at all).
 */
class FullFramePassthroughDetector : TargetDetector {
    override fun detect(frame: CameraFrame): TargetDetection =
        TargetDetection(
            hasCandidate = true,
            confidence = 1.0f,
            boundingBox = NormalizedBox(cx = 0.5f, cy = 0.5f, w = 1.0f, h = 1.0f),
            quality = FrameQuality.GOOD,
            reason = "full_frame_passthrough",
        )
}
