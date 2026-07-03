package com.giraffetechnology.qc.submit

/** Pure JVM [OutboxStore] for unit tests; mirrors the SQLite store's semantics. */
class InMemoryOutboxStore : OutboxStore {
    private val entries = LinkedHashMap<String, OutboxEntry>()

    override suspend fun enqueue(entry: OutboxEntry): Boolean {
        val id = entry.submission.clientJobId
        if (entries.containsKey(id)) return false
        entries[id] = entry
        return true
    }

    override suspend fun pending(): List<OutboxEntry> = entries.values.filter { !it.uploaded }

    override suspend fun all(): List<OutboxEntry> = entries.values.toList()

    override suspend fun markUploaded(clientJobId: String) {
        entries[clientJobId]?.let { entries[clientJobId] = it.copy(uploaded = true) }
    }
}
