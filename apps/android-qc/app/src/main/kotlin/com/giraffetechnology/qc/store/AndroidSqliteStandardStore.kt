package com.giraffetechnology.qc.store

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import com.giraffetechnology.qc.contracts.DetectionPoint
import com.giraffetechnology.qc.contracts.DetectionPointRegion
import com.giraffetechnology.qc.contracts.DetectionSeverity
import com.giraffetechnology.qc.contracts.IncidentalFindingPolicy
import com.giraffetechnology.qc.contracts.InstalledSku
import com.giraffetechnology.qc.contracts.InstalledStandardRevision
import com.giraffetechnology.qc.contracts.RequiredView
import com.giraffetechnology.qc.contracts.SqliteStandardStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

/**
 * SQLite-backed [SqliteStandardStore] + [StandardStoreWriter] (S5 §14).
 *
 * Strictly offline: every read hits the local DB only, never the network.
 * A miss returns null / empty — never throws — so callers fail closed. Bundle
 * install is a full atomic replace inside a single transaction (all-or-nothing),
 * matching the offline-sync importer contract.
 *
 * Detection points and photo-path lists are stored as JSON columns so an
 * installed revision is self-sufficient for on-device inspection with no server
 * round-trip.
 */
class AndroidSqliteStandardStore(
    context: Context,
    dbName: String = DEFAULT_DB_NAME,
) : SqliteStandardStore, StandardStoreWriter {

    private val helper = Helper(context.applicationContext, dbName)

    override suspend fun searchInstalledSku(query: String): List<InstalledSku> =
        withContext(Dispatchers.IO) {
            val like = "%${query.trim()}%"
            val out = mutableListOf<InstalledSku>()
            helper.readableDatabase.rawQuery(
                "SELECT sku_id, item_number, name, state, active_revision_id, bundle_id, bundle_version " +
                    "FROM installed_sku WHERE item_number LIKE ? OR name LIKE ? ORDER BY item_number",
                arrayOf(like, like),
            ).use { c ->
                while (c.moveToNext()) out += c.readInstalledSku()
            }
            out
        }

    override suspend fun getInstalledSku(skuId: String): InstalledSku? =
        withContext(Dispatchers.IO) {
            helper.readableDatabase.rawQuery(
                "SELECT sku_id, item_number, name, state, active_revision_id, bundle_id, bundle_version " +
                    "FROM installed_sku WHERE sku_id = ? LIMIT 1",
                arrayOf(skuId),
            ).use { c -> if (c.moveToNext()) c.readInstalledSku() else null }
        }

    override suspend fun getInstalledStandardRevision(skuId: String): InstalledStandardRevision? =
        withContext(Dispatchers.IO) {
            helper.readableDatabase.rawQuery(
                "SELECT revision_id, sku_id, revision_no, state, photo_paths_json, detection_points_json, " +
                    "bundle_id, bundle_version FROM installed_revision WHERE sku_id = ? LIMIT 1",
                arrayOf(skuId),
            ).use { c -> if (c.moveToNext()) c.readInstalledRevision() else null }
        }

    override suspend fun installedBundleVersion(): Long? = withContext(Dispatchers.IO) {
        helper.readableDatabase.rawQuery(
            "SELECT value FROM pad_meta WHERE key = ? LIMIT 1",
            arrayOf(META_BUNDLE_VERSION),
        ).use { c -> if (c.moveToNext()) c.getString(0)?.toLongOrNull() else null }
    }

    override suspend fun installBundle(
        bundleId: String,
        bundleVersion: Long,
        skus: List<InstalledSku>,
        revisions: List<InstalledStandardRevision>,
    ) = withContext(Dispatchers.IO) {
        val db = helper.writableDatabase
        db.beginTransaction()
        try {
            db.delete("installed_sku", null, null)
            db.delete("installed_revision", null, null)
            skus.forEach { db.insertOrThrow("installed_sku", null, it.toValues()) }
            revisions.forEach { db.insertOrThrow("installed_revision", null, it.toValues()) }
            val meta = ContentValues().apply {
                put("key", META_BUNDLE_VERSION)
                put("value", bundleVersion.toString())
            }
            db.insertWithOnConflict("pad_meta", null, meta, SQLiteDatabase.CONFLICT_REPLACE)
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    // ── row mapping ────────────────────────────────────────────────────────

    private fun android.database.Cursor.readInstalledSku() = InstalledSku(
        skuId = getString(0),
        itemNumber = getString(1),
        name = getString(2),
        state = getString(3),
        activeStandardRevisionId = getStringOrNull(4),
        bundleId = getStringOrNull(5),
        bundleVersion = getStringOrNull(6),
    )

    private fun android.database.Cursor.readInstalledRevision() = InstalledStandardRevision(
        standardRevisionId = getString(0),
        skuId = getString(1),
        revisionNo = getInt(2),
        state = getString(3),
        standardPhotoPaths = decodePaths(getStringOrNull(4)),
        detectionPoints = decodePoints(getStringOrNull(5)),
        bundleId = getString(6),
        bundleVersion = getString(7),
    )

    private fun android.database.Cursor.getStringOrNull(idx: Int): String? =
        if (isNull(idx)) null else getString(idx)

    private fun InstalledSku.toValues() = ContentValues().apply {
        put("sku_id", skuId)
        put("item_number", itemNumber)
        put("name", name)
        put("state", state)
        put("active_revision_id", activeStandardRevisionId)
        put("bundle_id", bundleId)
        put("bundle_version", bundleVersion)
    }

    private fun InstalledStandardRevision.toValues() = ContentValues().apply {
        put("revision_id", standardRevisionId)
        put("sku_id", skuId)
        put("revision_no", revisionNo)
        put("state", state)
        put("photo_paths_json", encodePaths(standardPhotoPaths))
        put("detection_points_json", encodePoints(detectionPoints))
        put("bundle_id", bundleId)
        put("bundle_version", bundleVersion)
    }

    private class Helper(context: Context, dbName: String) :
        SQLiteOpenHelper(context, dbName, null, DB_VERSION) {
        override fun onCreate(db: SQLiteDatabase) {
            db.execSQL(
                "CREATE TABLE installed_sku (" +
                    "sku_id TEXT PRIMARY KEY, item_number TEXT NOT NULL, name TEXT NOT NULL, " +
                    "state TEXT NOT NULL, active_revision_id TEXT, bundle_id TEXT, bundle_version TEXT)"
            )
            db.execSQL(
                "CREATE TABLE installed_revision (" +
                    "revision_id TEXT PRIMARY KEY, sku_id TEXT NOT NULL, revision_no INTEGER NOT NULL, " +
                    "state TEXT NOT NULL, photo_paths_json TEXT, detection_points_json TEXT, " +
                    "bundle_id TEXT NOT NULL, bundle_version TEXT NOT NULL)"
            )
            db.execSQL("CREATE INDEX idx_revision_sku ON installed_revision (sku_id)")
            db.execSQL("CREATE TABLE pad_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        }

        override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
            db.execSQL("DROP TABLE IF EXISTS installed_sku")
            db.execSQL("DROP TABLE IF EXISTS installed_revision")
            db.execSQL("DROP TABLE IF EXISTS pad_meta")
            onCreate(db)
        }
    }

    companion object {
        const val DEFAULT_DB_NAME = "giraffe_pad_standards.db"
        private const val DB_VERSION = 1
        private const val META_BUNDLE_VERSION = "installed_bundle_version"

        internal fun encodePaths(paths: List<String>): String =
            JSONArray().apply { paths.forEach { put(it) } }.toString()

        internal fun decodePaths(json: String?): List<String> {
            if (json.isNullOrBlank()) return emptyList()
            val arr = JSONArray(json)
            return (0 until arr.length()).map { arr.getString(it) }
        }

        internal fun encodePoints(points: List<DetectionPoint>): String {
            val arr = JSONArray()
            points.forEach { p ->
                arr.put(
                    JSONObject().apply {
                        put("point_code", p.pointCode)
                        put("label", p.label)
                        put("description", p.description)
                        put("method_hint", p.methodHint)
                        put("expected_value", p.expectedValue ?: JSONObject.NULL)
                        put("pass_criteria", p.passCriteria)
                        put("severity", p.severity.wire)
                        put("required_view", p.requiredView.wire)
                        put("evidence_required", p.evidenceRequired)
                        put("incidental_finding_policy", p.incidentalFindingPolicy.wire)
                        put("regions", JSONArray().apply {
                            p.regions.forEach { region ->
                                put(JSONObject().apply {
                                    put("image_id", region.imageId)
                                    put("x", region.x)
                                    put("y", region.y)
                                    put("w", region.w)
                                    put("h", region.h)
                                })
                            }
                        })
                    }
                )
            }
            return arr.toString()
        }

        internal fun decodePoints(json: String?): List<DetectionPoint> {
            if (json.isNullOrBlank()) return emptyList()
            val arr = JSONArray(json)
            return (0 until arr.length()).map { i ->
                val o = arr.getJSONObject(i)
                DetectionPoint(
                    pointCode = o.getString("point_code"),
                    label = o.getString("label"),
                    description = o.optString("description", ""),
                    methodHint = o.optString("method_hint", ""),
                    expectedValue = if (o.isNull("expected_value")) null else o.optString("expected_value"),
                    passCriteria = o.optString("pass_criteria", ""),
                    severity = DetectionSeverity.fromWire(o.optString("severity")) ?: DetectionSeverity.MAJOR,
                    requiredView = RequiredView.fromWire(o.optString("required_view")) ?: RequiredView.ANY,
                    evidenceRequired = o.optBoolean("evidence_required", false),
                    incidentalFindingPolicy = IncidentalFindingPolicy.fromWire(
                        o.optString("incidental_finding_policy")
                    ) ?: IncidentalFindingPolicy.FLAG_FOR_REVIEW,
                    regions = o.optJSONArray("regions")?.let { regions ->
                        (0 until regions.length()).map { index ->
                            val region = regions.getJSONObject(index)
                            DetectionPointRegion(
                                imageId = region.getString("image_id"),
                                x = region.getDouble("x"),
                                y = region.getDouble("y"),
                                w = region.getDouble("w"),
                                h = region.getDouble("h"),
                            )
                        }
                    } ?: emptyList(),
                )
            }
        }
    }
}
