package com.giraffetechnology.qc.sync

import android.util.Log
import java.io.File

/**
 * USB-sideload intake (Task 03, fallback channel).
 *
 * Scans a designated inbox directory (default `/sdcard/giraffe_qc/inbox/`) for
 * new bundle archives, funnels each through the SAME [BundleImporter] as the
 * sync-window pull, then moves the file to `processed/` or `failed/` with the
 * outcome recorded. Fail-closed: a bad bundle never disturbs the live standards.
 *
 * No network is involved — this is the offline delivery path.
 */
class InboxScanner(
    private val inboxDir: File,
    private val importer: BundleImporter,
) {
    private val processedDir = File(inboxDir, "processed")
    private val failedDir = File(inboxDir, "failed")

    data class ScanOutcome(val file: String, val result: ImportResult)

    /** Scan once; import every new *.tar.gz and move it to processed/ or failed/. */
    fun scanOnce(): List<ScanOutcome> {
        if (!inboxDir.isDirectory) return emptyList()
        processedDir.mkdirs()
        failedDir.mkdirs()
        val outcomes = ArrayList<ScanOutcome>()
        val candidates = inboxDir.listFiles { f ->
            f.isFile && (f.name.endsWith(".tar.gz") || f.name.endsWith(".tgz"))
        } ?: return emptyList()

        for (file in candidates.sortedBy { it.name }) {
            val result = try {
                importer.import(file.readBytes(), source = "inbox")
            } catch (e: Exception) {
                ImportResult.Rejected("read_failed: ${e.message}")
            }
            val ok = result is ImportResult.Imported || result is ImportResult.AlreadyInstalled
            val dest = File(if (ok) processedDir else failedDir, file.name)
            if (!file.renameTo(dest)) {
                runCatching { file.copyTo(dest, overwrite = true); file.delete() }
            }
            Log.i(TAG, "Inbox bundle ${file.name}: $result")
            outcomes.add(ScanOutcome(file.name, result))
        }
        return outcomes
    }

    companion object {
        private const val TAG = "InboxScanner"
        const val DEFAULT_INBOX_PATH = "/sdcard/giraffe_qc/inbox"
    }
}
