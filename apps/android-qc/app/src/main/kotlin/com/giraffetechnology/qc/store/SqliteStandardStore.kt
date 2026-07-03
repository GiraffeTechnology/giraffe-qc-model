package com.giraffetechnology.qc.store

import android.content.ContentValues
import com.giraffetechnology.qc.qwen.QcPointInput
import com.giraffetechnology.qc.qwen.StandardPhotoInput
import com.giraffetechnology.qc.sku.Sku
import com.giraffetechnology.qc.sync.BundleManifest
import com.giraffetechnology.qc.sync.StandardStore
import com.giraffetechnology.qc.sync.StandardsVersionInfo

/**
 * SQLite-backed [StandardStore] for on-device offline standards (Task 03).
 *
 * [installBundle] runs inside a single transaction: it clears the scope's prior
 * standards and writes the new bundle atomically, so a failure mid-import leaves
 * the previous standards intact (fail-closed).
 */
class SqliteStandardStore(private val helper: PadSqliteHelper) : StandardStore {

    override fun installedBundleVersion(tenantId: String, lineScope: String): Int? {
        helper.readableDatabase.rawQuery(
            "SELECT bundle_version FROM installed_bundle WHERE tenant_id=? AND line_scope=?",
            arrayOf(tenantId, lineScope),
        ).use { c -> return if (c.moveToFirst()) c.getInt(0) else null }
    }

    override fun installBundle(manifest: BundleManifest, photoLocalPaths: Map<String, String>) {
        val db = helper.writableDatabase
        db.beginTransaction()
        try {
            val tenant = manifest.tenantId
            val line = manifest.lineScope
            // Clear prior standards for this scope.
            db.delete("std_photo", "tenant_id=? AND sku_id IN (SELECT sku_id FROM std_sku WHERE tenant_id=? AND line_scope=?)", arrayOf(tenant, tenant, line))
            db.delete("std_detection_point", "tenant_id=? AND sku_id IN (SELECT sku_id FROM std_sku WHERE tenant_id=? AND line_scope=?)", arrayOf(tenant, tenant, line))
            db.delete("std_sku", "tenant_id=? AND line_scope=?", arrayOf(tenant, line))

            for (sku in manifest.skus) {
                db.insertOrThrow("std_sku", null, ContentValues().apply {
                    put("tenant_id", tenant)
                    put("line_scope", line)
                    put("sku_id", sku.skuId)
                    put("item_number", sku.itemNumber)
                    put("name", sku.name)
                    put("category", sku.category)
                    put("active_standard_revision_id", sku.activeStandardRevisionId)
                    put("revision_no", sku.revisionNo)
                    put("bundle_version", manifest.bundleVersion)
                })
                for (dp in sku.detectionPoints) {
                    db.insertOrThrow("std_detection_point", null, ContentValues().apply {
                        put("tenant_id", tenant)
                        put("sku_id", sku.skuId)
                        put("point_id", dp.id)
                        put("point_code", dp.pointCode)
                        put("label", dp.label)
                        put("description", dp.description)
                        put("roi_json", dp.roiJson)
                        put("method_hint", dp.methodHint)
                        put("sort_order", dp.sortOrder)
                    })
                }
                for (photo in sku.photos) {
                    val path = photoLocalPaths[photo.id]
                        ?: throw IllegalStateException("no extracted path for photo ${photo.id}")
                    db.insertOrThrow("std_photo", null, ContentValues().apply {
                        put("tenant_id", tenant)
                        put("sku_id", sku.skuId)
                        put("photo_id", photo.id)
                        put("local_path", path)
                        put("angle", photo.angle)
                        put("is_primary", if (photo.isPrimary) 1 else 0)
                    })
                }
            }

            db.delete("installed_bundle", "tenant_id=? AND line_scope=?", arrayOf(tenant, line))
            db.insertOrThrow("installed_bundle", null, ContentValues().apply {
                put("tenant_id", tenant)
                put("line_scope", line)
                put("bundle_version", manifest.bundleVersion)
                put("sku_count", manifest.skus.size)
                put("imported_at", System.currentTimeMillis())
            })
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    override fun listSkus(tenantId: String): List<Sku> {
        val out = ArrayList<Sku>()
        helper.readableDatabase.rawQuery(
            "SELECT sku_id FROM std_sku WHERE tenant_id=? ORDER BY item_number", arrayOf(tenantId),
        ).use { c -> while (c.moveToNext()) getSku(tenantId, c.getString(0))?.let(out::add) }
        return out
    }

    override fun getSku(tenantId: String, skuId: String): Sku? {
        val db = helper.readableDatabase
        db.rawQuery(
            "SELECT item_number, name, active_standard_revision_id FROM std_sku WHERE tenant_id=? AND sku_id=?",
            arrayOf(tenantId, skuId),
        ).use { c ->
            if (!c.moveToFirst()) return null
            val itemNumber = c.getString(0)
            val name = c.getString(1)
            val revId = c.getString(2)
            return Sku(
                id = skuId,
                itemNumber = itemNumber,
                name = name,
                activeStandardRevisionId = revId,
                standardPhotos = loadPhotos(tenantId, skuId),
                detectionPoints = loadPoints(tenantId, skuId),
            )
        }
    }

    override fun findByItemNumber(tenantId: String, query: String): List<Sku> {
        val out = ArrayList<Sku>()
        helper.readableDatabase.rawQuery(
            "SELECT sku_id FROM std_sku WHERE tenant_id=? AND item_number LIKE ? ORDER BY item_number",
            arrayOf(tenantId, "%$query%"),
        ).use { c -> while (c.moveToNext()) getSku(tenantId, c.getString(0))?.let(out::add) }
        return out
    }

    fun versionInfo(tenantId: String, lineScope: String): StandardsVersionInfo {
        helper.readableDatabase.rawQuery(
            "SELECT bundle_version, sku_count, imported_at FROM installed_bundle WHERE tenant_id=? AND line_scope=?",
            arrayOf(tenantId, lineScope),
        ).use { c ->
            return if (c.moveToFirst())
                StandardsVersionInfo(tenantId, lineScope, c.getInt(0), c.getInt(1), c.getLong(2))
            else StandardsVersionInfo(tenantId, lineScope, null, 0, null)
        }
    }

    private fun loadPhotos(tenantId: String, skuId: String): List<StandardPhotoInput> {
        val out = ArrayList<StandardPhotoInput>()
        helper.readableDatabase.rawQuery(
            "SELECT photo_id, local_path, angle FROM std_photo WHERE tenant_id=? AND sku_id=? ORDER BY is_primary DESC, photo_id",
            arrayOf(tenantId, skuId),
        ).use { c ->
            while (c.moveToNext()) {
                out.add(StandardPhotoInput(photoId = c.getString(0), localPath = c.getString(1), angle = c.getString(2)))
            }
        }
        return out
    }

    private fun loadPoints(tenantId: String, skuId: String): List<QcPointInput> {
        val out = ArrayList<QcPointInput>()
        helper.readableDatabase.rawQuery(
            "SELECT point_id, point_code, label, description, roi_json, method_hint FROM std_detection_point WHERE tenant_id=? AND sku_id=? ORDER BY sort_order, point_code",
            arrayOf(tenantId, skuId),
        ).use { c ->
            while (c.moveToNext()) {
                out.add(QcPointInput(
                    qcPointId = c.getString(0),
                    qcPointCode = c.getString(1),
                    name = c.getString(2),
                    description = c.getString(3) ?: "",
                    roiJson = c.getString(4),
                    ruleType = c.getString(5),
                ))
            }
        }
        return out
    }
}
