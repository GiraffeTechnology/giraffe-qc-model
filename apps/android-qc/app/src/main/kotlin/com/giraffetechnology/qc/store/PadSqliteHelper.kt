package com.giraffetechnology.qc.store

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

/**
 * SQLite schema for the Pad's offline standards + result outbox (Task 03).
 *
 * Kept as a hand-written SQLiteOpenHelper (no annotation processor) so it builds
 * without extra Gradle plugins. The store classes wrap it behind the
 * `StandardStore` / `OutboxStore` interfaces; unit tests use in-memory fakes so
 * the importer/uploader logic is verified without an Android runtime.
 */
class PadSqliteHelper(context: Context) :
    SQLiteOpenHelper(context, DB_NAME, null, DB_VERSION) {

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """CREATE TABLE installed_bundle(
                 tenant_id TEXT NOT NULL,
                 line_scope TEXT NOT NULL,
                 bundle_version INTEGER NOT NULL,
                 sku_count INTEGER NOT NULL,
                 imported_at INTEGER NOT NULL,
                 PRIMARY KEY(tenant_id, line_scope))""".trimIndent()
        )
        db.execSQL(
            """CREATE TABLE std_sku(
                 tenant_id TEXT NOT NULL,
                 line_scope TEXT NOT NULL,
                 sku_id TEXT NOT NULL,
                 item_number TEXT NOT NULL,
                 name TEXT NOT NULL,
                 category TEXT,
                 active_standard_revision_id TEXT NOT NULL,
                 revision_no INTEGER NOT NULL,
                 bundle_version INTEGER NOT NULL,
                 PRIMARY KEY(tenant_id, sku_id))""".trimIndent()
        )
        db.execSQL(
            """CREATE TABLE std_detection_point(
                 tenant_id TEXT NOT NULL,
                 sku_id TEXT NOT NULL,
                 point_id TEXT NOT NULL,
                 point_code TEXT NOT NULL,
                 label TEXT NOT NULL,
                 description TEXT,
                 roi_json TEXT,
                 method_hint TEXT,
                 sort_order INTEGER NOT NULL,
                 PRIMARY KEY(tenant_id, point_id))""".trimIndent()
        )
        db.execSQL(
            """CREATE TABLE std_photo(
                 tenant_id TEXT NOT NULL,
                 sku_id TEXT NOT NULL,
                 photo_id TEXT NOT NULL,
                 local_path TEXT NOT NULL,
                 angle TEXT,
                 is_primary INTEGER NOT NULL,
                 PRIMARY KEY(tenant_id, photo_id))""".trimIndent()
        )
        db.execSQL(
            """CREATE TABLE outbox_job(
                 job_uuid TEXT PRIMARY KEY,
                 tenant_id TEXT NOT NULL,
                 sku_id TEXT NOT NULL,
                 active_standard_revision_id TEXT NOT NULL,
                 overall_result TEXT NOT NULL,
                 created_by TEXT,
                 job_ref TEXT,
                 notes TEXT,
                 started_at TEXT,
                 completed_at TEXT,
                 status TEXT NOT NULL,
                 attempts INTEGER NOT NULL,
                 last_error TEXT)""".trimIndent()
        )
        db.execSQL(
            """CREATE TABLE outbox_checkpoint(
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 job_uuid TEXT NOT NULL,
                 detection_point_id TEXT NOT NULL,
                 result TEXT NOT NULL,
                 observed_value TEXT,
                 confidence REAL NOT NULL,
                 notes TEXT)""".trimIndent()
        )
        db.execSQL(
            """CREATE TABLE outbox_media(
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 job_uuid TEXT NOT NULL,
                 local_path TEXT,
                 sha256 TEXT,
                 angle TEXT,
                 view_type TEXT)""".trimIndent()
        )
        db.execSQL("""CREATE TABLE sync_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        // Standards are re-importable from bundles and the outbox is transient; a
        // destructive upgrade is safe and simplest for the Pad.
        for (t in listOf(
            "installed_bundle", "std_sku", "std_detection_point", "std_photo",
            "outbox_job", "outbox_checkpoint", "outbox_media", "sync_meta",
        )) db.execSQL("DROP TABLE IF EXISTS $t")
        onCreate(db)
    }

    companion object {
        const val DB_NAME = "giraffe_qc_pad.db"
        const val DB_VERSION = 1
    }
}
