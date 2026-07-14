package com.giraffetechnology.qc.operator.cloud

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.security.MessageDigest
import java.util.UUID
import kotlin.math.max
import kotlin.math.roundToInt

class CloudCropEncoder(private val profile: CompressionProfile) {
    fun encode(imagePath: String, pointCode: String, roiJson: String?): EncodedCrop {
        val region = parseRegion(roiJson)
        val source = requireNotNull(BitmapFactory.decodeFile(imagePath)) { "capture_decode_failed" }
        val left = (source.width * region.x).roundToInt().coerceIn(0, source.width - 1)
        val top = (source.height * region.y).roundToInt().coerceIn(0, source.height - 1)
        val width = (source.width * region.w).roundToInt().coerceIn(1, source.width - left)
        val height = (source.height * region.h).roundToInt().coerceIn(1, source.height - top)
        var bitmap = Bitmap.createBitmap(source, left, top, width, height)
        if (bitmap !== source) source.recycle()

        val longest = max(bitmap.width, bitmap.height)
        if (longest > profile.maxLongestSidePx) {
            val scale = profile.maxLongestSidePx.toDouble() / longest
            val resized = Bitmap.createScaledBitmap(
                bitmap,
                (bitmap.width * scale).roundToInt().coerceAtLeast(1),
                (bitmap.height * scale).roundToInt().coerceAtLeast(1),
                true,
            )
            if (resized !== bitmap) bitmap.recycle()
            bitmap = resized
        }

        var quality = profile.jpegQuality
        var bytes = jpeg(bitmap, quality)
        while (bytes.size > profile.maxCropBytes && quality > 30) {
            quality -= 7
            bytes = jpeg(bitmap, quality)
        }
        while (bytes.size > profile.maxCropBytes && max(bitmap.width, bitmap.height) > 320) {
            val resized = Bitmap.createScaledBitmap(
                bitmap,
                (bitmap.width * 0.85).roundToInt().coerceAtLeast(1),
                (bitmap.height * 0.85).roundToInt().coerceAtLeast(1),
                true,
            )
            bitmap.recycle()
            bitmap = resized
            bytes = jpeg(bitmap, quality)
        }
        if (bytes.size > profile.maxCropBytes) {
            bitmap.recycle()
            error("crop_exceeds_200kb_hard_ceiling")
        }
        val result = EncodedCrop(
            cropId = "crop_${UUID.randomUUID()}",
            pointCode = pointCode,
            bytes = bytes,
            widthPx = bitmap.width,
            heightPx = bitmap.height,
            sha256 = bytes.sha256Hex(),
            region = region,
        )
        bitmap.recycle()
        return result
    }

    fun persist(jobDir: File, crop: EncodedCrop): File {
        jobDir.mkdirs()
        return File(jobDir, "${crop.cropId}.jpg").also { it.writeBytes(crop.bytes) }
    }

    private fun jpeg(bitmap: Bitmap, quality: Int): ByteArray = ByteArrayOutputStream().use { stream ->
        check(bitmap.compress(Bitmap.CompressFormat.JPEG, quality, stream)) { "jpeg_encode_failed" }
        stream.toByteArray()
    }

    companion object {
        internal fun parseRegion(raw: String?): NormalizedRegion {
            require(!raw.isNullOrBlank()) { "missing_detection_point_region" }
            val trimmed = raw.trim()
            val obj = if (trimmed.startsWith("[")) {
                val array = JSONArray(trimmed)
                require(array.length() == 1) { "exactly_one_capture_region_required" }
                array.getJSONObject(0)
            } else JSONObject(trimmed)
            return NormalizedRegion(
                x = obj.getDouble("x"), y = obj.getDouble("y"),
                w = obj.getDouble("w"), h = obj.getDouble("h"),
            )
        }
    }
}

internal fun ByteArray.sha256Hex(): String = MessageDigest.getInstance("SHA-256")
    .digest(this).joinToString("") { "%02x".format(it) }
