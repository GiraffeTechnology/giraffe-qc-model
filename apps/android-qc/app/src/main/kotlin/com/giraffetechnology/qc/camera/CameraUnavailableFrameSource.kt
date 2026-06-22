package com.giraffetechnology.qc.camera

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow

/**
 * Production-safe placeholder used when no real camera source is available.
 * start() and stop() are no-ops; frames never emits.
 */
class CameraUnavailableFrameSource : CameraFrameSource {
    override val frames: Flow<CameraFrame> = emptyFlow()
    override fun start() = Unit
    override fun stop() = Unit
}
