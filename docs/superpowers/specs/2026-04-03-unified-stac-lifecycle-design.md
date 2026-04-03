# Unified STAC Lifecycle Design

**Date**: 03 APR 2026
**Status**: Draft
**Version**: v0.10.10 (prerequisite for v0.11 release)
**Author**: Claude + Robert

---

## Summary

Unify STAC materialization into a two-phase lifecycle (structural insert at processing time, B2C materialization at approval time) across all data types. Eliminates conditional branching between tiled/single/zarr paths, makes unpublish/revoke predictable, and adds optional STAC catalog registration for vector datasets.

## Motivation

The current STAC materialization has three problems:

1. **Inconsistent state machine**: Tiled rasters insert STAC items at processing time (for mosaic preview), but single COGs and zarr defer until approval. This branching complicates revoke and unpublish.

2. **Revoke/unpublish ordering bug (D6)**: Revoking an approved raster deletes the STAC item immediately. When unpublish runs later, its inventory step can't find the item. Fixed with fallback chains, but the root cause is that two operations compete to delete the same artifact.

3. **No vector STAC**: Clients want vector datasets discoverable via STAC search alongside rasters and zarrs. Currently vector uses only PostGIS/TiPG — no pgSTAC presence at all.

## Design Principles

1. **Every processed dataset gets a pgSTAC presence** (structural insert at processing time)
2. **Approval is an UPDATE, never an INSERT** (state 2 → state 3 transition)
3. **Only unpublish deletes from pgSTAC** (revoke marks state, doesn't delete artifacts)
4. **Vector STAC is opt-in** (default false, enabled via `create_stac` parameter)
5. **Two distinct methods, not one method with flags** (fundamentally different operations)

## STAC State Machine

```
STATE 1: Empty
  pgSTAC: nothing
  When: before processing, or after full unpublish

STATE 2: Structural
  pgSTAC: item exists with raw asset hrefs (abfs://, /vsiaz/)
          geoetl:* properties PRESERVED (internal traceability)
          ddh:status = 'processing'
          NO TiTiler/TiPG URL injection
          NO B2C sanitization
  pgSTAC search: registered (if collection, for mosaic tile serving)
  When: processing complete, awaiting approval

STATE 3: Materialized (B2C)
  pgSTAC: item with TiTiler/TiPG URLs injected
          geoetl:* properties STRIPPED (B2C sanitized)
          ddh:status = 'approved'
          ddh:approved_by, ddh:approved_at stamped
  When: after approval
```

### State Transitions

```
              process complete        approve           unpublish
State 1 ──────────────────────> State 2 ──────────> State 3 ──────────> State 1
                                   │                   │
                                   │ reject            │ revoke
                                   ▼                   ▼
                                State 1             State 1
                              (delete item)       (delete item)
```

**Key rule**: Only two operations delete from pgSTAC:
- **Reject** (awaiting_approval → delete structural item → state 1)
- **Unpublish** (any state → full teardown → state 1)

**Revoke** transitions from state 3 to state 1 by deleting the STAC item. This is acceptable because:
- The B2C-materialized item MUST be removed to stop TiTiler serving
- Unpublish (if run after revoke) uses Release.stac_item_json fallback (D6 fix, already implemented)
- Re-approval is not supported — revoked items must be resubmitted

### Per-Data-Type Behavior

| Data Type | State 2 Content | State 3 Additions | STAC Required? |
|-----------|----------------|-------------------|----------------|
| **Single COG** | Item with `/vsiaz/` asset href, band metadata | TiTiler `/cog/` URLs injected, `geoetl:*` stripped | Yes |
| **Tiled Raster** | N items + pgSTAC search (mosaic preview) | B2C sanitized, `ddh:approved_*` stamped | Yes |
| **Zarr** | Item with `abfs://` zarr-store asset | `/xarray/` URLs injected, `geoetl:*` stripped | Yes |
| **Vector** | Item with TiPG collection asset href | TiPG URLs injected, `geoetl:*` stripped | **Optional** (`create_stac=true`) |

---

## STACMaterializer Changes

### Current (One Method)

```python
def materialize_to_pgstac(self, stac_item_json, collection_id,
                          blob_path=None, zarr_prefix=None,
                          approved_by=None, ...):
    # Always: copy, sanitize, optionally stamp, optionally inject URLs, upsert
```

### Proposed (Two Methods)

```python
def materialize_structural(self, stac_item_json: dict, collection_id: str) -> dict:
    """
    State 1 → State 2: Insert raw item into pgSTAC for structural purposes.

    - Deep copy item (no mutation of cached source)
    - Stamp ddh:status = 'processing' (distinguishes from B2C items)
    - Preserve ALL properties (no sanitization — geoetl:* needed for traceability)
    - NO TiTiler/TiPG URL injection (not approved yet)
    - NO approval stamping
    - Ensure collection exists (auto-create if missing)
    - Upsert item to pgSTAC
    """

def materialize_approved(self, stac_item_json: dict, collection_id: str,
                         blob_path: str = None, zarr_prefix: str = None,
                         approved_by: str = None, approved_at: str = None,
                         access_level: str = None, version_id: str = None) -> dict:
    """
    State 2 → State 3: B2C materialization after approval.

    - Deep copy item
    - Sanitize (strip geoetl:*, processing:* — B2C consumers don't see internals)
    - Stamp ddh:status = 'approved', ddh:approved_by, ddh:approved_at, ddh:access_level
    - Inject TiTiler URLs (raster: /cog/, zarr: /xarray/) or TiPG URLs (vector)
    - Upsert item to pgSTAC (overwrites state 2 structural item)
    """
```

### Migration

The existing `materialize_to_pgstac()` method is retained as `materialize_approved()` (rename + add `ddh:status='approved'` stamp). `materialize_structural()` is new — simpler, no sanitization, no URL injection.

The Epoch 4 `materialize_item(release, reviewer, clearance_state)` method remains unchanged for backward compatibility until Epoch 4 is fully retired.

---

## DAG Handler Changes

### `stac_materialize_item` Handler

The existing handler (`services/stac/handler_materialize_item.py`) gains a `mode` parameter:

```python
def stac_materialize_item(params, context=None):
    mode = params.get("mode", "approved")  # "structural" or "approved"

    # ... existing item lookup from cog_metadata / zarr_metadata ...

    materializer = STACMaterializer()

    if mode == "structural":
        result = materializer.materialize_structural(
            stac_item_json=stac_item_json,
            collection_id=collection_id,
        )
    else:
        result = materializer.materialize_approved(
            stac_item_json=stac_item_json,
            collection_id=collection_id,
            blob_path=effective_blob_path,
            zarr_prefix=effective_zarr_prefix,
        )
```

### New Handler: `vector_build_stac_item`

Vector datasets don't produce `stac_item_json` during processing (no `cog_metadata` or `zarr_metadata`). A new handler builds the STAC item from `geo.table_catalog` metadata:

**File**: `services/vector/handler_build_stac_item.py`

```python
def vector_build_stac_item(params, context=None):
    """
    Build a STAC item for a vector dataset from PostGIS table metadata.

    Reads: geo.table_catalog (bbox, row count, geometry type, CRS)
    Produces: stac_item_json with TiPG collection URL as asset

    Called AFTER register_catalog (which populates table_catalog).
    Only runs when create_stac=true.
    """
    table_name = params.get("table_name")
    schema_name = params.get("schema_name", "geo")
    collection_id = params.get("collection_id")
    stac_item_id = params.get("stac_item_id")

    # Read table metadata from geo.table_catalog
    handler = VectorToPostGISHandler()
    metadata = handler.get_table_metadata(table_name, schema_name)

    bbox = [metadata.bbox_minx, metadata.bbox_miny,
            metadata.bbox_maxx, metadata.bbox_maxy]

    # TiPG collection URL as the vector asset
    config = get_config()
    tipg_base = config.titiler_base_url.rstrip('/')
    tipg_collection = f"{schema_name}.{table_name}"
    asset_href = f"{tipg_base}/collections/{tipg_collection}"

    stac_item_json = build_stac_item(
        item_id=stac_item_id,
        collection_id=collection_id,
        bbox=bbox,
        asset_href=asset_href,
        asset_type="application/geo+json",  # OGC Features
        asset_key="ogc-features",
        asset_roles=["data"],
        crs="EPSG:4326",
        detected_type="vector",
        dataset_id=params.get("dataset_id"),
        resource_id=params.get("resource_id"),
        version_id=params.get("version_id"),
        job_id=params.get("_run_id"),
        epoch=5,
    )

    # Cache on Release for downstream materialization
    if params.get("release_id"):
        release_repo = ReleaseRepository()
        release_repo.update_stac_item_json(params["release_id"], stac_item_json)

    return {"success": True, "result": {
        "stac_item_id": stac_item_id,
        "collection_id": collection_id,
        "stac_item_json_cached": True,
    }}
```

---

## Workflow YAML Changes

### process_raster.yaml (Single COG + Tiled)

```yaml
nodes:
  # ... download, validate, route_by_size ...
  # ... create_single_cog / tiling path ...
  # ... persist_single / persist_tiled ...

  # NEW: State 2 structural insert (before approval gate)
  materialize_structural:
    type: task
    handler: stac_materialize_item
    depends_on:
      - "persist_single?"
      - "persist_tiled?"
    params: [collection_id]
    receives:
      cog_id: "upload_single_cog.result.stac_item_id?"   # single COG path
      cog_ids: "persist_tiled.result.cog_ids?"            # tiled path
    mode: structural

  # State 2 collection (extent + pgSTAC search for mosaic preview)
  materialize_collection_structural:
    type: task
    handler: stac_materialize_collection
    depends_on: [materialize_structural]
    params: [collection_id]

  # APPROVAL GATE — reviewer can preview via pgSTAC search mosaic
  approval_gate:
    type: gate
    gate_type: approval
    depends_on: [materialize_collection_structural]

  # State 3 B2C materialization (after approval)
  materialize_approved:
    type: task
    handler: stac_materialize_item
    depends_on: [approval_gate]
    params: [collection_id]
    receives:
      cog_id: "upload_single_cog.result.stac_item_id?"
      cog_ids: "persist_tiled.result.cog_ids?"
      blob_path: "upload_single_cog.result.silver_blob_path?"
    mode: approved

  materialize_collection:
    type: task
    handler: stac_materialize_collection
    depends_on: [materialize_approved]
    params: [collection_id]
```

### ingest_zarr.yaml

Same pattern — `materialize_structural` before gate, `materialize_approved` after gate.

### vector_docker_etl.yaml

```yaml
parameters:
  create_stac: {type: bool, default: false}

nodes:
  # ... existing: load, validate, create_tables, split_views ...
  # ... refresh_tipg_preview, link_release_tables ...

  # APPROVAL GATE
  approval_gate:
    type: gate
    gate_type: approval
    depends_on: [link_release_tables]

  # ... register_catalog (after approval) ...

  # Optional STAC: build item from table_catalog metadata
  build_stac_item:
    type: task
    handler: vector_build_stac_item
    depends_on: [register_catalog]
    when: "params.create_stac"
    params: [collection_id, table_name, schema_name, stac_item_id,
             dataset_id, resource_id, version_id, release_id]
    receives:
      tables_info: "create_and_load_tables.result.tables_created"

  # Optional: State 2 structural insert
  materialize_structural:
    type: task
    handler: stac_materialize_item
    depends_on: [build_stac_item]
    when: "params.create_stac"
    params: [collection_id]
    receives:
      item_id: "build_stac_item.result.stac_item_id"
    mode: structural

  # Optional: State 3 B2C materialization
  materialize_approved:
    type: task
    handler: stac_materialize_item
    depends_on: [materialize_structural]
    when: "params.create_stac"
    params: [collection_id]
    receives:
      item_id: "build_stac_item.result.stac_item_id"
    mode: approved

  materialize_collection:
    type: task
    handler: stac_materialize_collection
    depends_on: [materialize_approved?]
    when: "params.create_stac"
    params: [collection_id]

  # ... refresh_tipg (always runs, not conditional on create_stac) ...
```

---

## Platform Integration

### VectorProcessingOptions

Add `create_stac` field:

```python
class VectorProcessingOptions(BaseProcessingOptions):
    create_stac: bool = Field(
        default=False,
        description="Create STAC catalog entry for vector dataset (optional)"
    )
```

### Platform Translation

Forward `create_stac` in `_reshape_vector_params`:

```python
for key in ('overwrite', 'split_column', 'converter_params', 'layer_name',
            'indexes', 'temporal_property', 'create_stac'):
```

### Platform Status

No changes needed. The services block is already gated on `approval_state == 'approved'`. For vector datasets with `create_stac=true`, the services block would include STAC collection/item URLs in addition to existing TiPG URLs.

---

## Revoke and Unpublish Changes

### Revoke

No change to revoke behavior. Revoke continues to delete STAC items immediately (state 3 → state 1 or state 2 → state 1). This is correct because:
- State 3 items have public-facing TiTiler URLs that must be cut off immediately
- State 2 items have raw internal URLs but should also be cleaned on reject/revoke
- The D6 fix (Release.stac_item_json fallback in unpublish inventory) handles the case where unpublish runs after revoke

### Unpublish

No change. Unpublish already handles missing pgSTAC items via the Release fallback (D6 fix). The structural insert (state 2) means unpublish will more often find items in pgSTAC, reducing reliance on the fallback.

### Reject

New: rejection of an `awaiting_approval` dataset should delete the state 2 structural item from pgSTAC. Currently rejection doesn't touch pgSTAC because items weren't inserted until approval. With state 2 structural inserts, rejection needs a cleanup step.

Add to the reject flow:
```python
# In reject handler — clean up structural STAC item
if release.stac_item_id and release.stac_collection_id:
    materializer = STACMaterializer()
    materializer.dematerialize_item(release.stac_collection_id, release.stac_item_id)
```

---

## Implementation Summary

### New Code

| File | What |
|------|------|
| `services/stac_materialization.py` | Add `materialize_structural()` method |
| `services/stac_materialization.py` | Rename `materialize_to_pgstac()` → `materialize_approved()` (keep alias for compat) |
| `services/stac/handler_materialize_item.py` | Add `mode` parameter (`structural` / `approved`) |
| `services/vector/handler_build_stac_item.py` | NEW: build STAC item from table_catalog metadata |
| `core/models/processing_options.py` | Add `create_stac` to `VectorProcessingOptions` |
| `services/platform_translation.py` | Forward `create_stac` in reshaper |

### Modified Workflows

| Workflow | Change |
|----------|--------|
| `workflows/process_raster.yaml` | Add `materialize_structural` before gate, rename existing to `materialize_approved` |
| `workflows/process_raster_collection.yaml` | Same pattern |
| `workflows/ingest_zarr.yaml` | Same pattern |
| `workflows/vector_docker_etl.yaml` | Add conditional STAC nodes (`when: "params.create_stac"`) |

### Modified Approval/Reject

| Flow | Change |
|------|--------|
| Reject | Add STAC cleanup for state 2 items |
| Revoke | No change (already deletes STAC) |
| Unpublish | No change (D6 fallback already in place) |

---

## Testing Plan

| Test | What | Expected |
|------|------|----------|
| Raster single COG submit | State 2 item appears in pgSTAC before approval | ddh:status='processing', no TiTiler URLs |
| Raster single COG approve | State 2 → State 3 | ddh:status='approved', TiTiler URLs injected |
| Raster tiled submit | State 2 items + pgSTAC search before approval | Mosaic preview works |
| Zarr submit | State 2 item in pgSTAC | Raw abfs:// URL, no xarray URLs |
| Vector submit (create_stac=false) | No pgSTAC presence | TiPG works, no STAC |
| Vector submit (create_stac=true) | State 2 item in pgSTAC | TiPG collection URL as asset |
| Reject awaiting_approval | State 2 item deleted | pgSTAC clean |
| Approve then revoke | State 3 item deleted | pgSTAC clean |
| Approve then unpublish | Full teardown | pgSTAC + blobs + metadata deleted |
| Revoke then unpublish | D6 path: inventory uses Release fallback | Blobs deleted, audit recorded |

---

## Dependencies

- D4 fix (zarr datetime "0") — must be deployed before zarr STAC testing
- D6 fix (revoke-unpublish fallback) — already implemented, safety net for revoke→unpublish
- `ddh:status` property — new STAC property, must be indexed in pgSTAC for filtering

## Deferred

- **TiTiler pgSTAC search filtering by `ddh:status`**: Would allow state 2 items to be completely invisible to public TiTiler searches. Not blocking — state 2 items have raw internal URLs that public clients can't use anyway.
- **Revoke as soft delete (state 3 → state 2)**: Architecturally cleaner but requires TiTiler filtering. Defer to post-v0.11.
- **Vector STAC temporal extent**: Auto-detect from `temporal_property` column in table_catalog. Defer — explicit datetime params work for now.
