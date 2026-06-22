package com.giraffetechnology.qc.ui

import org.junit.Assert.*
import org.junit.Test

// Self-contained 4:3 camera preview layout calculations — no production class imports.
// Tests cover the Compose/canvas formula that positions the camera preview within
// an arbitrary container while maintaining 4:3 aspect ratio (no crop, no stretch).
class PreviewBoxCalculationsTest {

    private data class PreviewBox(
        val width: Float,
        val height: Float,
        val offsetX: Float,
        val offsetY: Float,
    )

    /**
     * Fit a 4:3 camera frame into [containerW] x [containerH] without cropping or stretching.
     * Returns the preview box size and its top-left offset (bars have positive offset).
     *
     * Decision rule:
     *   scaleW = containerW / frameAspect   (height needed if we fit-to-width)
     *   If scaleW < containerH → letterbox (fit to width, bars top+bottom)
     *   Else                  → pillarbox (fit to height, bars left+right)
     */
    private fun fitPreviewBox(
        containerW: Float,
        containerH: Float,
        frameAspect: Float = 4f / 3f,
    ): PreviewBox {
        val scaleW = containerW / frameAspect
        return if (scaleW < containerH) {
            // Letterbox: fit to width
            val previewW = containerW
            val previewH = containerW / frameAspect
            PreviewBox(previewW, previewH, 0f, (containerH - previewH) / 2f)
        } else {
            // Pillarbox: fit to height
            val previewH = containerH
            val previewW = containerH * frameAspect
            PreviewBox(previewW, previewH, (containerW - previewW) / 2f, 0f)
        }
    }

    @Test
    fun `square container letterboxes a 4-3 frame`() {
        // 600x600: scaleW = 600/(4/3) = 450 < 600 → letterbox
        val box = fitPreviewBox(600f, 600f)
        assertEquals(600f,  box.width,   0.01f)
        assertEquals(450f,  box.height,  0.01f)
        assertEquals(0f,    box.offsetX, 0.01f)
        assertEquals(75f,   box.offsetY, 0.01f)  // (600−450)/2
    }

    @Test
    fun `tall container letterboxes a 4-3 frame`() {
        // 600x900: scaleW = 450 < 900 → letterbox
        val box = fitPreviewBox(600f, 900f)
        assertEquals(600f,  box.width,   0.01f)
        assertEquals(450f,  box.height,  0.01f)
        assertEquals(0f,    box.offsetX, 0.01f)
        assertEquals(225f,  box.offsetY, 0.01f)  // (900−450)/2
    }

    @Test
    fun `exact 4-3 container fills with no bars`() {
        // 800x600: scaleW = 800/(4/3) = 600 == containerH → pillarbox branch (no bars)
        val box = fitPreviewBox(800f, 600f)
        assertEquals(800f,  box.width,   0.01f)
        assertEquals(600f,  box.height,  0.01f)
        assertEquals(0f,    box.offsetX, 0.01f)
        assertEquals(0f,    box.offsetY, 0.01f)
    }

    @Test
    fun `widescreen 16-9 container pillarboxes a 4-3 frame`() {
        // 1920x1080: scaleW = 1920/(4/3) = 1440 > 1080 → pillarbox
        val box = fitPreviewBox(1920f, 1080f)
        assertEquals(1440f, box.width,   0.01f)
        assertEquals(1080f, box.height,  0.01f)
        assertEquals(240f,  box.offsetX, 0.01f)  // (1920−1440)/2
        assertEquals(0f,    box.offsetY, 0.01f)
    }

    @Test
    fun `portrait 9-16 container letterboxes a 4-3 frame`() {
        // 1080x1920: scaleW = 1080/(4/3) = 810 < 1920 → letterbox
        val box = fitPreviewBox(1080f, 1920f)
        assertEquals(1080f, box.width,   0.01f)
        assertEquals(810f,  box.height,  0.01f)
        assertEquals(0f,    box.offsetX, 0.01f)
        assertEquals(555f,  box.offsetY, 0.01f)  // (1920−810)/2
    }
}
