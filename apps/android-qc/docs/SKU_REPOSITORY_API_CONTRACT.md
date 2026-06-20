# SKU Repository API Contract

> Companion reference to
> `app/src/main/kotlin/com/giraffetechnology/qc/sku/SkuRepository.kt`
> and `ApiSkuRepository.kt`.

## Base URL

Configured at build time via `BuildConfig.SKU_API_BASE_URL`.  
Example (factory local network): `http://192.168.1.10:8080`

This endpoint is on the factory LAN. The Pad app has no INTERNET permission;
it only reaches the factory server over the local network.

---

## Endpoints

### Search SKUs by item number

```
GET /api/v1/sku/search?q={query}&page={page}&size={size}
```

| Parameter | Type   | Required | Default | Description                                 |
|-----------|--------|----------|---------|---------------------------------------------|
| `q`       | string | yes      | —       | Item-number or name substring (URL-encoded)  |
| `page`    | int    | no       | `0`     | Zero-based page index                       |
| `size`    | int    | no       | `50`    | Maximum items per page                      |

**Response 200:**
```json
{
  "items": [ SkuDto ],
  "total": 142
}
```

---

### List all SKUs (paginated)

```
GET /api/v1/sku?page={page}&size={size}
```

Same query parameters and response shape as search.

---

### Get SKU by ID

```
GET /api/v1/sku/{skuId}
```

| Parameter | Type   | Required | Description   |
|-----------|--------|----------|---------------|
| `skuId`   | string | yes      | Unique SKU ID |

**Response 200** — `SkuDto`  
**Response 404** — empty body or `{ "error": "not_found" }`

---

## SkuDto

```json
{
  "sku_id":                "string",
  "item_number":           "string",
  "name":                  "string",
  "reference_photo_paths": [ "string" ],
  "attributes":            { "key": "value" }
}
```

| Field                    | Type               | Nullable | Description                             |
|--------------------------|--------------------|----------|-----------------------------------------|
| `sku_id`                 | string             | no       | Unique identifier                       |
| `item_number`            | string             | no       | Human-readable product number (GH-1001) |
| `name`                   | string             | no       | Display name                            |
| `reference_photo_paths`  | array of string    | no       | Ordered reference image paths           |
| `attributes`             | map<string,string> | yes      | Optional key-value product attributes   |

---

## Kotlin model

```kotlin
data class Sku(
    val skuId               : String,
    val itemNumber          : String,
    val name                : String,
    val referencePhotoPaths : List<String>,
    val attributes          : Map<String, String> = emptyMap(),
)
```

---

## Error cases

| HTTP status  | Behaviour in `ApiSkuRepository`                                   |
|--------------|-------------------------------------------------------------------|
| 200          | Success — items parsed and returned                               |
| 404          | `getById` returns `null`; list endpoints return empty list        |
| 4xx / 5xx    | `runCatching` captures exception — returns empty list or null     |
| Network error| Same as above — operator falls back to manual item-number entry   |

`ApiSkuRepository` never propagates exceptions to callers.  
An empty result means "data unavailable"; the operator enters the item number manually.

---

## Pagination

- Pages are **zero-indexed** (`page=0` is the first page).
- `size` is the max items per page (default 50 for search, configurable for list).
- Continue iterating with `page=0,1,2,...` until the returned `items` array is shorter than `size`.

---

## Example response

```json
{
  "items": [
    {
      "sku_id": "sku-abc-123",
      "item_number": "GH-1001",
      "name": "Widget A",
      "reference_photo_paths": [
        "/storage/ref/gh1001_front.jpg",
        "/storage/ref/gh1001_back.jpg"
      ],
      "attributes": {
        "color": "blue",
        "material": "ABS"
      }
    }
  ],
  "total": 1
}
```
