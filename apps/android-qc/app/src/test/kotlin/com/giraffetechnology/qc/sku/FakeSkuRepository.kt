package com.giraffetechnology.qc.sku

/**
 * In-memory SkuRepository for unit tests only.
 * NOT used in production code; production uses ApiSkuRepository.
 */
class FakeSkuRepository(
    private val skus: List<Sku> = emptyList(),
) : SkuRepository {

    override suspend fun searchByItemNumber(query: String): List<Sku> =
        skus.filter { it.itemNumber.contains(query, ignoreCase = true) ||
                      it.name.contains(query, ignoreCase = true) }

    override suspend fun listAll(page: Int, pageSize: Int): List<Sku> =
        skus.drop(page * pageSize).take(pageSize)

    override suspend fun getById(skuId: String): Sku? =
        skus.firstOrNull { it.skuId == skuId }
}
