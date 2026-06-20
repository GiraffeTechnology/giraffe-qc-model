package com.giraffetechnology.qc.sku

/**
 * SKU data source. Real impl calls the factory backend API (DB-backed).
 * Fake impl (FakeSkuRepository) is used in unit tests only.
 *
 * API contract (backend REST endpoints):
 *
 *   GET  /api/v1/sku/search?q={itemNumber}&page={p}&size={n}
 *        -> 200 { "items": [ SkuDto, ... ], "total": int }
 *
 *   GET  /api/v1/sku?page={p}&size={n}
 *        -> 200 { "items": [ SkuDto, ... ], "total": int }
 *
 *   GET  /api/v1/sku/{skuId}
 *        -> 200 SkuDto | 404
 *
 *   SkuDto {
 *     "sku_id":                String,
 *     "item_number":           String,
 *     "name":                  String,
 *     "reference_photo_paths": [ String ],
 *     "attributes":            { String: String }   // optional
 *   }
 */
interface SkuRepository {
    suspend fun searchByItemNumber(query: String): List<Sku>
    suspend fun listAll(page: Int, pageSize: Int): List<Sku>
    suspend fun getById(skuId: String): Sku?
}
