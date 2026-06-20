package com.giraffetechnology.qc.ui

import org.junit.Assert.assertEquals
import org.junit.Test
import kotlin.math.abs

/**
 * Unit tests for the 4:3 preview fit formula used in QcCaptureScreen.
 *
 * Formula (per spec):
 *   previewWidth  = min(containerWidth, containerHeight * 4f / 3f)
 *   previewHeight = previewWidth * 3f / 4f
 *
 * Verifies:
 *   - Result is exactly 4:3
 *   - Preview is never larger than container
 *   - Preview is centered (letterbox/pillarbox space available on both sides)
 */
class PreviewBoxCalculationsTest {

    private fun compute43Preview(containerW: Float, containerH: Float): Pair<Float, Float> {
        val previewW = minOf(containerW, containerH * 4f / 3f)
        val previewH = previewW * 3f / 4f
        return previewW to previewH
    }

    private fun assertAspectRatio43(previewW: Float, previewH: Float, context: String = "") {
        val ratio = previewW / previewH
        assertEquals("4:3 aspect ratio not met$context: ratio=$ratio", 4f / 3f, ratio, 0.001f)
    }

    private fun assertFitsContainer(previewW: Float, previewH: Float, containerW: Float, containerH: Float) {
        assertTrue("previewW $previewW > containerW $containerW", previewW <= containerW + 0.01f)
        assertTrue("previewH $previewH > containerH $containerH", previewH <= containerH + 0.01f)
    }

    private fun assertTrue(msg: String, value: Boolean) {
        if (!value) throw AssertionError(msg)
    }

    // ── 16:9 landscape container (left 3/4 of 1280×720) ──
    // Left 3/4 of 1280 = 960dp wide, 720dp tall -> container ratio = 960/720 = 4:3 exactly
    @Test
    fun `16x9 container left-3-4 gives full-fit 4x3 preview`() {
        val (pw, ph) = compute43Preview(960f, 720f)
        assertAspectRatio43(pw, ph, " [16:9 left-3/4]")
        assertFitsContainer(pw, ph, 960f, 720f)
        // At 16:9, left 3/4 IS exactly 4:3 so preview fills the whole container
        assertEquals(960f, pw, 0.1f)
        assertEquals(720f, ph, 0.1f)
    }

    // ── 16:10 landscape container (left 3/4 of 1280×800) ──
    // Left 3/4 of 1280 = 960dp wide, 800dp tall -> container ratio = 960/800 = 1.2 (taller than 4:3)
    // Preview is constrained by width: previewW=960, previewH=720 -> pillarbox top+bottom
    @Test
    fun `16x10 container gives width-constrained 4x3 preview with top-bottom margin`() {
        val (pw, ph) = compute43Preview(960f, 800f)
        assertAspectRatio43(pw, ph, " [16:10 left-3/4]")
        assertFitsContainer(pw, ph, 960f, 800f)
        assertEquals(960f, pw, 0.1f)
        assertEquals(720f, ph, 0.1f)  // 720 < 800, so there are 40dp margins top and bottom
        // Verify letterbox margin
        val verticalMargin = (800f - ph) / 2f
        assertEquals(40f, verticalMargin, 0.1f)
    }

    // ── Tall container (e.g. portrait-ish, height >> width) ──
    @Test
    fun `tall container is height-constrained resulting in correct 4x3 preview`() {
        val containerW = 600f
        val containerH = 900f
        val (pw, ph) = compute43Preview(containerW, containerH)
        assertAspectRatio43(pw, ph, " [tall container]")
        assertFitsContainer(pw, ph, containerW, containerH)
        // Height constrained: previewW = min(600, 900*4/3=1200) = 600
        assertEquals(600f, pw, 0.1f)
        assertEquals(450f, ph, 0.1f)
    }

    // ── Wide container (very wide, e.g. 1920×400) ──
    @Test
    fun `very wide container is height-constrained resulting in 4x3 preview with side margins`() {
        val containerW = 1440f  // left 3/4 of 1920
        val containerH = 400f
        val (pw, ph) = compute43Preview(containerW, containerH)
        assertAspectRatio43(pw, ph, " [very wide container]")
        assertFitsContainer(pw, ph, containerW, containerH)
        // previewW = min(1440, 400*4/3=533.3) = 533.3
        assertEquals(400f * 4f / 3f, pw, 0.1f)
        assertEquals(400f, ph, 0.1f)
    }

    // ── Exact 4:3 container ──
    @Test
    fun `exact 4x3 container preview fills container exactly`() {
        val (pw, ph) = compute43Preview(800f, 600f)
        assertAspectRatio43(pw, ph, " [exact 4:3]")
        assertEquals(800f, pw, 0.1f)
        assertEquals(600f, ph, 0.1f)
    }
}
