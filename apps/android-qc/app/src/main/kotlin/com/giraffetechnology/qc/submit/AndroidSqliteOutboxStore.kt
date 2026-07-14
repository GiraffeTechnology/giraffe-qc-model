package com.giraffetechnology.qc.submit

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * SQLite-backed [OutboxStore] (S6 §9). Persists completed results across app
 * restarts so nothing is lost while the Pad waits for a sync window. Enqueue is
 * idempotent on `client_job_id` (INSERT OR IGNORE).
 */
class AndroidSqliteOutboxStore(
    context: Context,
    dbName: String = DEFAULT_DB_NAME,
) : OutboxStore {

    private val helper = Helper(context.applicationContext, dbName)

    override suspend fun enqueue(entry: OutboxEntry): Boolean = withContext(Dispatchers.IO) {
        val rowId = helper.writableDatabase.insertWithOnConflict(
            "outbox_entry", null, entry.toValues(), SQLiteDatabase.CONFLICT_IGNORE,
        )
        rowId != -1L
    }

    override suspend fun pending(): List<OutboxEntry> = query("uploaded = 0")

    override suspend fun all(): List<OutboxEntry> = query(null)

    override suspend fun markUploaded(clientJobId: String) = withContext(Dispatchers.IO) {
        val values = ContentValues().apply { put("uploaded", 1) }
        helper.writableDatabase.update("outbox_entry", values, "client_job_id = ?", arrayOf(clientJobId))
        Unit
    }

    private suspend fun query(where: String?): List<OutboxEntry> = withContext(Dispatchers.IO) {
        val out = mutableListOf<OutboxEntry>()
        val sql = "SELECT client_job_id, tenant_id, sku_id, item_number, standard_revision_id, " +
            "bundle_version, model_result, human_decision, human_decided_by, reason, model_name, captured_image_path, " +
            "created_at, cloud_job_id, point_results_json, timing_json, uploaded FROM outbox_entry" +
            (where?.let { " WHERE $it" } ?: "") + " ORDER BY created_at"
        helper.readableDatabase.rawQuery(sql, null).use { c ->
            while (c.moveToNext()) {
                val submission = ResultSubmission(
                    clientJobId = c.getString(0),
                    tenantId = c.getString(1),
                    skuId = c.getString(2),
                    itemNumber = c.getString(3),
                    standardRevisionId = if (c.isNull(4)) null else c.getString(4),
                    bundleVersion = if (c.isNull(5)) null else c.getString(5),
                    modelResult = c.getString(6),
                    humanDecision = HumanDecision.fromWire(c.getString(7)) ?: HumanDecision.REVIEW_REQUIRED,
                    humanDecidedBy = c.getString(8),
                    reason = c.getString(9),
                    modelName = c.getString(10),
                    capturedImagePath = if (c.isNull(11)) null else c.getString(11),
                    createdAtEpochMs = c.getLong(12),
                    cloudJobId = if (c.isNull(13)) null else c.getString(13),
                    pointResultsJson = if (c.isNull(14)) null else c.getString(14),
                    timingJson = if (c.isNull(15)) null else c.getString(15),
                )
                out += OutboxEntry(submission = submission, uploaded = c.getInt(16) != 0)
            }
        }
        out
    }

    private fun OutboxEntry.toValues() = ContentValues().apply {
        put("client_job_id", submission.clientJobId)
        put("tenant_id", submission.tenantId)
        put("sku_id", submission.skuId)
        put("item_number", submission.itemNumber)
        put("standard_revision_id", submission.standardRevisionId)
        put("bundle_version", submission.bundleVersion)
        put("model_result", submission.modelResult)
        put("human_decision", submission.humanDecision.wire)
        put("human_decided_by", submission.humanDecidedBy)
        put("reason", submission.reason)
        put("model_name", submission.modelName)
        put("captured_image_path", submission.capturedImagePath)
        put("created_at", submission.createdAtEpochMs)
        put("cloud_job_id", submission.cloudJobId)
        put("point_results_json", submission.pointResultsJson)
        put("timing_json", submission.timingJson)
        put("uploaded", if (uploaded) 1 else 0)
    }

    private class Helper(context: Context, dbName: String) :
        SQLiteOpenHelper(context, dbName, null, DB_VERSION) {
        override fun onCreate(db: SQLiteDatabase) {
            db.execSQL(
                "CREATE TABLE outbox_entry (" +
                    "client_job_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, sku_id TEXT NOT NULL, " +
                    "item_number TEXT NOT NULL, standard_revision_id TEXT, bundle_version TEXT, " +
                    "model_result TEXT NOT NULL, human_decision TEXT NOT NULL, human_decided_by TEXT NOT NULL, reason TEXT NOT NULL, " +
                    "model_name TEXT NOT NULL, captured_image_path TEXT, created_at INTEGER NOT NULL, " +
                    "cloud_job_id TEXT, point_results_json TEXT, timing_json TEXT, " +
                    "uploaded INTEGER NOT NULL DEFAULT 0)"
            )
        }

        override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
            if (oldVersion < 2) {
                db.execSQL("ALTER TABLE outbox_entry ADD COLUMN cloud_job_id TEXT")
                db.execSQL("ALTER TABLE outbox_entry ADD COLUMN point_results_json TEXT")
                db.execSQL("ALTER TABLE outbox_entry ADD COLUMN timing_json TEXT")
            }
            if (oldVersion < 3) {
                db.execSQL("ALTER TABLE outbox_entry ADD COLUMN human_decided_by TEXT NOT NULL DEFAULT ''")
            }
        }
    }

    companion object {
        const val DEFAULT_DB_NAME = "giraffe_pad_outbox.db"
        private const val DB_VERSION = 3
    }
}
