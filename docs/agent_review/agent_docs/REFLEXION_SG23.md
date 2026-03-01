# REFLEXION Pipeline: SG2-3 — Catalog API Strips STAC 1.0.0 Fields

**Date**: 01 MAR 2026
**Bug ID**: SG2-3
**Severity**: HIGH
**Pipeline**: R -> F -> P -> J (Reverse Engineer, Fault Injector, Patch Author, Judge)

---

## Agent R: Reverse Engineer

### Objective
Audit all pgSTAC read methods in `PgStacRepository` for STAC 1.0.0 compliance — specifically whether returned dicts include the required top-level fields.

### Methods Analyzed: 3

#### Method 1: `get_item()` (lines 351-400)
- **Contract**: `(item_id, collection_id) -> Optional[Dict]`
- **Pre-patch SQL**: `SELECT content FROM pgstac.items WHERE id = %s AND collection = %s`
- **Pre-patch return**: `result['content']` — missing `id`, `type`, `geometry`, `collection`, `stac_version`
- **Consumers**: `platform_catalog_item` trigger (direct HTTP response), materialization re-upsert, unpublish inventory, approval service

#### Method 2: `search_by_platform_ids()` (lines 578-647)
- **Contract**: `(dataset_id, resource_id, version_id) -> Optional[Dict]`
- **Pre-patch SQL**: `SELECT content, collection, id FROM pgstac.items WHERE content->'properties' @> %s::jsonb`
- **Pre-patch return**: `result['content']` — discarded the `collection` and `id` columns it fetched
- **Consumers**: `PlatformCatalogService.lookup_direct()` for B2B lookups

#### Method 3: `get_items_by_platform_dataset()` (lines 649-699)
- **Contract**: `(dataset_id, limit) -> List[Dict]`
- **Pre-patch SQL**: `SELECT id, collection, content FROM pgstac.items WHERE ...`
- **Pre-patch return**: Python-side merge of `id` and `collection` into content — still missing `type`, `geometry`, `stac_version`
- **Consumers**: `PlatformCatalogService.list_items_for_dataset()`

### Root Cause
pgSTAC stores STAC items in denormalized form. The `content` JSONB column does NOT include `id`, `collection`, or `geometry` — these are extracted into separate table columns for indexing. The `type` (`"Feature"`) and `stac_version` (`"1.0.0"`) are also stripped during insert.

A correct reconstitution pattern already existed in `pgstac_bootstrap.py` (lines 2093-2100, written 13 NOV 2025) but was never propagated to `PgStacRepository`.

---

## Agent F: Fault Injector

### Fault Scenarios

#### F1: Catalog item endpoint returns invalid STAC (HIGH)
- **Trigger**: `GET /api/platform/catalog/item/{collection}/{item}`
- **Code path**: `platform_catalog_item()` -> `PgStacRepository.get_item()` -> `json.dumps(item)`
- **Effect**: HTTP 200 response with dict missing `id`, `type`, `geometry`, `collection`, `stac_version`
- **Impact**: B2B consumers (DDH) receive a "Feature" with no geometry, no id, no type. Clients parsing `item['geometry']` get `KeyError`. Violates STAC 1.0.0 specification.

#### F2: Materialization re-upsert corrupts items (CRITICAL)
- **Trigger**: `stac_materialization.py:278` calls `get_item()`, patches properties, then calls `insert_item()` with the incomplete dict
- **Code path**: `STACMaterializer._materialize_tiled_items()` -> `get_item()` -> patch -> `insert_item()`
- **Effect**: pgSTAC's `upsert_item()` receives an incomplete STAC item. Could silently corrupt the stored item (geometry lost).

#### F3: search_by_platform_ids discards fetched columns (MEDIUM)
- **Trigger**: `PlatformCatalogService.lookup_direct()` returns incomplete item
- **Code path**: SQL fetches `content, collection, id` but only returns `content`
- **Effect**: Wasteful query + incomplete return value

#### F4: get_items_by_platform_dataset partial fix (LOW)
- **Trigger**: Items returned with `id` and `collection` but missing `type`, `geometry`, `stac_version`
- **Effect**: Items technically violate STAC spec but functional consumers only access `properties` and `bbox`

### Downstream Consumer Impact

| Consumer | Accesses | Broken Pre-Patch? | Severity |
|----------|----------|-------------------|----------|
| `platform_catalog_item` trigger | Full STAC item as HTTP response | YES | HIGH |
| `stac_materialization.py` re-upsert | Full item for `insert_item()` | YES (corruption risk) | CRITICAL |
| `unpublish_handlers.py` inventory | `properties.geoetl:job_id` only | No (field in content) | LOW |
| `asset_approval_service.py` filter | `properties.ddh:release_id` only | No (field in content) | LOW |
| `platform_catalog_service.py` lookup | `bbox`, `properties.datetime` | No (fields in content) | LOW |

---

## Agent P: Patch Author

All 3 patches use the same SQL reconstitution pattern from `pgstac_bootstrap.py`:

```sql
SELECT content ||
    jsonb_build_object(
        'id', id,
        'collection', collection,
        'geometry', ST_AsGeoJSON(geometry)::jsonb,
        'type', 'Feature',
        'stac_version', COALESCE(content->>'stac_version', '1.0.0')
    ) AS stac_item
FROM pgstac.items
WHERE ...
```

### Patch 1: `get_item()` (lines 374-393)

**File**: `infrastructure/pgstac_repository.py`
**Change**: Replaced `SELECT content` with `content || jsonb_build_object(...)`. Changed `result['content']` to `result['stac_item']`.

```diff
-SELECT content
-FROM pgstac.items
-WHERE id = %s AND collection = %s
+SELECT content ||
+    jsonb_build_object(
+        'id', id,
+        'collection', collection,
+        'geometry', ST_AsGeoJSON(geometry)::jsonb,
+        'type', 'Feature',
+        'stac_version', COALESCE(content->>'stac_version', '1.0.0')
+    ) AS stac_item
+FROM pgstac.items
+WHERE id = %s AND collection = %s
```
Result extraction: `result['content']` -> `result['stac_item']`

### Patch 2: `search_by_platform_ids()` (lines 612-640)

**File**: `infrastructure/pgstac_repository.py`
**Change**: Replaced `SELECT content, collection, id` with `content || jsonb_build_object(...)`. Changed `result['content']` to `result['stac_item']`. Updated debug logging to use `stac_item.get('id')`.

```diff
-SELECT content, collection, id
-FROM pgstac.items
-WHERE content->'properties' @> %s::jsonb
-LIMIT 1
+SELECT content ||
+    jsonb_build_object(
+        'id', id,
+        'collection', collection,
+        'geometry', ST_AsGeoJSON(geometry)::jsonb,
+        'type', 'Feature',
+        'stac_version', COALESCE(content->>'stac_version', '1.0.0')
+    ) AS stac_item
+FROM pgstac.items
+WHERE content->'properties' @> %s::jsonb
+LIMIT 1
```

### Patch 3: `get_items_by_platform_dataset()` (lines 672-692)

**File**: `infrastructure/pgstac_repository.py`
**Change**: Replaced `SELECT id, collection, content` with `content || jsonb_build_object(...)`. Replaced Python-side merge loop with `items = [row['stac_item'] for row in results]`.

```diff
-SELECT id, collection, content
+SELECT content ||
+    jsonb_build_object(
+        'id', id,
+        'collection', collection,
+        'geometry', ST_AsGeoJSON(geometry)::jsonb,
+        'type', 'Feature',
+        'stac_version', COALESCE(content->>'stac_version', '1.0.0')
+    ) AS stac_item
 FROM pgstac.items
 WHERE content->'properties'->>'ddh:dataset_id' = %s
```

```diff
-items = []
-for row in results:
-    item = row['content']
-    item['id'] = row['id']
-    item['collection'] = row['collection']
-    items.append(item)
+items = [row['stac_item'] for row in results]
```

---

## Agent J: Judge

### Patch 1 Verdict: ACCEPT

| Criterion | Assessment |
|-----------|------------|
| **Correctness** | PASS. The `||` operator merges `content` with reconstituted fields. Right operand wins on key collision, so authoritative column values take precedence. |
| **Safety** | PASS. `ST_AsGeoJSON(geometry)::jsonb` handles all PostGIS geometry types. `COALESCE` provides `'1.0.0'` default. Return type unchanged. |
| **Scope** | PASS. SQL query and result key changed. No signature, error handling, or behavioral changes. |
| **Performance** | NEGLIGIBLE. `jsonb_build_object` + `ST_AsGeoJSON` are microsecond operations. No additional queries. |

### Patch 2 Verdict: ACCEPT

| Criterion | Assessment |
|-----------|------------|
| **Correctness** | PASS. Eliminates the wasteful pattern of fetching `id, collection` columns and discarding them. Now all reconstitution happens in SQL. |
| **Safety** | PASS. GIN index on `content` still used for `@>` containment. WHERE clause unchanged. |
| **Scope** | PASS. Also fixes debug logging to use `stac_item.get()` instead of `result['id']`. |

### Patch 3 Verdict: ACCEPT

| Criterion | Assessment |
|-----------|------------|
| **Correctness** | PASS. Replaces incomplete Python-side merge (missing `type`, `geometry`, `stac_version`) with complete SQL-side reconstitution. Eliminates mutable-dict side effect. |
| **Safety** | PASS. List comprehension `[row['stac_item'] for row in results]` is cleaner and doesn't mutate row dicts. |
| **Scope** | PASS. ORDER BY and LIMIT unchanged. |

### Overall Verdict: **ACCEPT ALL THREE PATCHES**

### Residual Risks

1. **`get_collection()` returns `result['content']`**: Collections in pgSTAC are stored whole (not decomposed), so this is likely correct — but should be verified.
2. **`update_item_properties()` uses `content` directly**: This is a write operation targeting `content` specifically — correct by design.
3. **NULL geometry edge case**: If an item has NULL geometry, `ST_AsGeoJSON(NULL)` returns NULL, producing `"geometry": null` in the output. Better than absent, but unusual.

### Key Insight

This bug is a classic impedance mismatch between storage model and API contract. pgSTAC's decomposition of STAC items into separate columns is an optimization for indexing. The correct reconstitution pattern existed in `pgstac_bootstrap.py` since 13 NOV 2025 but was never propagated to the repository class written later. The fix was already known — it just was not applied consistently.
