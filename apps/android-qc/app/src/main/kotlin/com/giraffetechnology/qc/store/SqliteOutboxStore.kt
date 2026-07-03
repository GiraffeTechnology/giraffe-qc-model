package com.giraffetechnology.qc.store

import android.content.ContentValues
import com.giraffetechnology.qc.sync.OutboxCheckpoint
import com.giraffetechnology.qc.sync.OutboxCounts
import com.giraffetechnology.qc.sync.OutboxJob
import com.giraffetechnology.qc.sync.OutboxMedia
import com.giraffetechnology.qc.sync.OutboxStore

/**
 * SQLite-backed [OutboxStore] (Task 03). Enqueue is idempotent on job_uuid; a
 * re-enqueued completed job never creates a duplicate row.
 */
class SqliteOutboxStore(private val helper: PadSqliteHelper) : OutboxStore {

    override fun enqueue(job: OutboxJob) {
        val db = helper.writableDatabase
        db.beginTransaction()
        try {
            val exists = db.rawQuery(
                "SELECT 1 FROM outbox_job WHERE job_uuid=?", arrayOf(job.jobUuid),
            ).use { it.moveToFirst() }
            if (!exists) {
                db.insertOrThrow("outbox_job", null, ContentValues().apply {
                    put("job_uuid", job.jobUuid)
                    put("tenant_id", job.tenantId)
                    put("sku_id", job.skuId)
                    put("active_standard_revision_id", job.activeStandardRevisionId)
                    put("overall_result", job.overallResult)
                    put("created_by", job.createdBy)
                    put("job_ref", job.jobRef)
                    put("notes", job.notes)
                    put("started_at", job.startedAt)
                    put("completed_at", job.completedAt)
                    put("status", "pending")
                    put("attempts", 0)
                })
                for (cp in job.checkpoints) {
                    db.insertOrThrow("outbox_checkpoint", null, ContentValues().apply {
                        put("job_uuid", job.jobUuid)
                        put("detection_point_id", cp.detectionPointId)
                        put("result", cp.result)
                        put("observed_value", cp.observedValue)
                        put("confidence", cp.confidence)
                        put("notes", cp.notes)
                    })
                }
                for (m in job.media) {
                    db.insertOrThrow("outbox_media", null, ContentValues().apply {
                        put("job_uuid", job.jobUuid)
                        put("local_path", m.localPath)
                        put("sha256", m.sha256)
                        put("angle", m.angle)
                        put("view_type", m.viewType)
                    })
                }
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    override fun pending(limit: Int): List<OutboxJob> {
        val db = helper.readableDatabase
        val out = ArrayList<OutboxJob>()
        db.rawQuery(
            "SELECT job_uuid, tenant_id, sku_id, active_standard_revision_id, overall_result, " +
                "created_by, job_ref, notes, started_at, completed_at, attempts " +
                "FROM outbox_job WHERE status='pending' ORDER BY rowid LIMIT ?",
            arrayOf(limit.toString()),
        ).use { c ->
            while (c.moveToNext()) {
                val uuid = c.getString(0)
                out.add(OutboxJob(
                    jobUuid = uuid,
                    tenantId = c.getString(1),
                    skuId = c.getString(2),
                    activeStandardRevisionId = c.getString(3),
                    overallResult = c.getString(4),
                    createdBy = c.getString(5),
                    jobRef = c.getString(6),
                    notes = c.getString(7),
                    startedAt = c.getString(8),
                    completedAt = c.getString(9),
                    attempts = c.getInt(10),
                    checkpoints = loadCheckpoints(uuid),
                    media = loadMedia(uuid),
                    status = "pending",
                ))
            }
        }
        return out
    }

    override fun markUploaded(jobUuid: String) {
        helper.writableDatabase.execSQL(
            "UPDATE outbox_job SET status='uploaded' WHERE job_uuid=?", arrayOf(jobUuid),
        )
    }

    override fun markFailed(jobUuid: String, reason: String) {
        helper.writableDatabase.execSQL(
            "UPDATE outbox_job SET status='failed', attempts=attempts+1, last_error=? WHERE job_uuid=?",
            arrayOf(reason, jobUuid),
        )
    }

    override fun counts(): OutboxCounts {
        val db = helper.readableDatabase
        fun count(status: String) = db.rawQuery(
            "SELECT COUNT(*) FROM outbox_job WHERE status=?", arrayOf(status),
        ).use { if (it.moveToFirst()) it.getInt(0) else 0 }
        val last = db.rawQuery("SELECT value FROM sync_meta WHERE key='last_sync_at'", null)
            .use { if (it.moveToFirst()) it.getString(0).toLongOrNull() else null }
        return OutboxCounts(count("pending"), count("uploaded"), count("failed"), last)
    }

    override fun setLastSyncAt(tsMs: Long) {
        helper.writableDatabase.execSQL(
            "INSERT OR REPLACE INTO sync_meta(key, value) VALUES('last_sync_at', ?)",
            arrayOf(tsMs.toString()),
        )
    }

    private fun loadCheckpoints(uuid: String): List<OutboxCheckpoint> {
        val out = ArrayList<OutboxCheckpoint>()
        helper.readableDatabase.rawQuery(
            "SELECT detection_point_id, result, observed_value, confidence, notes FROM outbox_checkpoint WHERE job_uuid=?",
            arrayOf(uuid),
        ).use { c ->
            while (c.moveToNext()) {
                out.add(OutboxCheckpoint(c.getString(0), c.getString(1), c.getString(2), c.getFloat(3), c.getString(4)))
            }
        }
        return out
    }

    private fun loadMedia(uuid: String): List<OutboxMedia> {
        val out = ArrayList<OutboxMedia>()
        helper.readableDatabase.rawQuery(
            "SELECT local_path, sha256, angle, view_type FROM outbox_media WHERE job_uuid=?", arrayOf(uuid),
        ).use { c ->
            while (c.moveToNext()) {
                out.add(OutboxMedia(c.getString(0), c.getString(1), c.getString(2), c.getString(3)))
            }
        }
        return out
    }
}
