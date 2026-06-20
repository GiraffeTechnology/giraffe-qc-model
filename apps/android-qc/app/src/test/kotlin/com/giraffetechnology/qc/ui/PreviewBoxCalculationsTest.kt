package com.giraffetechnology.qc.ui

import org.junit.Assert.assertEquals
import org.junit.Test

data class PreviewRect(val x: Float, val y: Float, val width: Float, val height: Float)

/**
 * Unit tests for the 4:3 preview fit formula used in QcCaptureScreen.
 *
 * Formula (per spec):
 *   previewWidth  = min(containerWidth, containerHeight * 4f / 3f)
 *   previewHeight = previewWidth * 3f / 4f
 *   x = (containerWidth  - previewWidth)  / 2f
 *   y = (containerHeight - previewHeight) / 2f
 */
class PreviewBoxCalculationsTest {

    private fun compute43PreviewRect(containerW: Float, containerH: Float): PreviewRect {
        val previewW = minOf(containerW, containerH * 4f / 3f)
        val previewH = previewW * 3f / 4f
        val x = (containerW - previewW) / 2f
        val y = (containerH - previewH) / 2f
        return PreviewRect(x, y, previewW, previewH)
    }

    private fun assertAspectRatio43(width: Float, height: Float, context: String = "") {
        val ratio = width / height
        assertEquals("4:3 aspect ratio not met$context: ratio=$ratio", 4f / 3f, ratio, 0.001f)
    }

    private fun assertFitsContainer(r: PreviewRect, containerW: Float, containerH: Float) {
        if (r.width  > containerW + 0.01f) throw AssertionError("previewWidth ${r.width} > containerW $containerW")
        if (r.height > containerH + 0.01f) throw AssertionError("previewHeight ${r.height} > containerH $containerH")
    }

    // 16:9 landscape container (left 3/4 of 1280×720 = 960×720, ratio=4:3 exactly)
    // Preview fills container completely — x and y offsets are both zero.
    @Test
    fun `16x9 container left-3-4 gives full-fit 4x3 preview`() {
        val r = compute43PreviewRect(960f, 720f)
        assertAspectRatio43(r.width, r.height, " [16:9 left-3/4]")
        assertFitsContainer(r, 960f, 720f)
        assertEquals(960f, r.width,  0.1f)
        assertEquals(720f, r.height, 0.1f)
        assertEquals(0f,   r.x,      0.1f)
        assertEquals(0f,   r.y,      0.1f)
    }

    // 16:10 landscape (left 3/4 of 1280×800 = 960×800 — taller than 4:3, letterbox top+bottom)
    // previewW=960, previewH=720, leaving 40dp margin top and bottom (y=40).
    @Test
    fun `16x10 container gives width-constrained 4x3 preview with top-bottom margin`() {
        val r = compute43PreviewRect(960f, 800f)
        assertAspectRatio43(r.width, r.height, " [16:10 left-3/4]")
        assertFitsContainer(r, 960f, 800f)
        assertEquals(960f, r.width,  0.1f)
        assertEquals(720f, r.height, 0.1f)
        assertEquals(0f,   r.x,      0.1f)
        assertEquals(40f,  r.y,      0.1f)
    }

    // Tall container (portrait-ish, height >> width)
    @Test
    fun `tall container is height-constrained resulting in correct 4x3 preview`() {
        val r = compute43PreviewRect(600f, 900f)
        assertAspectRatio43(r.width, r.height, " [tall container]")
        assertFitsContainer(r, 600f, 900f)
        // previewW = min(600, 900*4/3=1200) = 600; previewH = 450
        assertEquals(600f, r.width,  0.1f)
        assertEquals(450f, r.height, 0.1f)
    }

    // Very wide container (left 3/4 of 1920×400 = 1440×400)
    @Test
    fun `very wide container is height-constrained resulting in 4x3 preview with side margins`() {
        val r = compute43PreviewRect(1440f, 400f)
        assertAspectRatio43(r.width, r.height, " [very wide container]")
        assertFitsContainer(r, 1440f, 400f)
        // previewW = min(1440, 400*4/3=533.3) = 533.3; previewH = 400
        assertEquals(400f * 4f / 3f, r.width,  0.1f)
        assertEquals(400f,           r.height, 0.1f)
    }

    // Exact 4:3 container
    @Test
    fun `exact 4x3 container preview fills container exactly`() {
        val r = compute43PreviewRect(800f, 600f)
        assertAspectRatio43(r.width, r.height, " [exact 4:3]")
        assertEquals(800f, r.width,  0.1f)
        assertEquals(600f, r.height, 0.1f)
    }
}
