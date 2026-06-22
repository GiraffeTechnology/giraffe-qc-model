package com.giraffetechnology.qc.sku

interface SkuRepository {
    suspend fun findByItemNumber(query: String): List<Sku>
    suspend fun getById(id: String): Sku?
}
