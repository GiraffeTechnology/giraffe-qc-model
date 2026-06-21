package com.giraffetechnology.qc.sku

class FakeSkuRepository(
    private val skus: List<Sku> = emptyList(),
) : SkuRepository {
    override suspend fun findByItemNumber(query: String): List<Sku> =
        skus.filter { it.itemNumber.contains(query, ignoreCase = true) }

    override suspend fun getById(id: String): Sku? =
        skus.firstOrNull { it.id == id }
}
