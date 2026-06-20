package com.giraffetechnology.qc.sku

/**
 * SKU data source. Production impl: [ApiSkuRepository]. Test-only impl: FakeSkuRepository (src/test).
 *
 * Full API contract: [docs/SKU_REPOSITORY_API_CONTRACT.md](../../../../../../../../docs/SKU_REPOSITORY_API_CONTRACT.md)
 */
interface SkuRepository {
    suspend fun searchByItemNumber(query: String): List<Sku>
    suspend fun listAll(page: Int, pageSize: Int): List<Sku>
    suspend fun getById(skuId: String): Sku?
}
