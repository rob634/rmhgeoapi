# Unified STAC Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two-phase STAC materialization (structural pre-approval, B2C post-approval) across all data types, with optional STAC for vector datasets.

**Architecture:** Add `materialize_structural()` method to STACMaterializer (raw insert, no sanitization), add `mode` parameter to `stac_materialize_item` handler, rewire all workflow YAMLs to insert STAC before approval gate, add `vector_build_stac_item` handler for vector STAC opt-in.

**Tech Stack:** Python, YAML workflow definitions, pgSTAC, psycopg

**Spec:** `docs/superpowers/specs/2026-04-03-unified-stac-lifecycle-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `services/stac_materialization.py` | Add `materialize_structural()`, rename existing to `materialize_approved()` |
| Modify | `services/stac/handler_materialize_item.py` | Add `mode` parameter routing |
| Create | `services/vector/handler_build_stac_item.py` | Build STAC JSON from table_catalog for vector |
| Modify | `services/__init__.py` | Register new handler |
| Modify | `config/defaults.py` | Add to DOCKER_TASKS |
| Modify | `core/models/processing_options.py` | Add `create_stac` to VectorProcessingOptions |
| Modify | `services/platform_translation.py` | Forward `create_stac` in reshaper |
| Modify | `workflows/process_raster.yaml` | Add structural insert before gate |
| Modify | `workflows/process_raster_collection.yaml` | Same pattern |
| Modify | `workflows/ingest_zarr.yaml` | Same pattern |
| Modify | `workflows/vector_docker_etl.yaml` | Add conditional STAC nodes |

---

## Important Context for Implementer

### Current `materialize_to_pgstac()` Signature (line 137 of stac_materialization.py)

```python
def materialize_to_pgstac(self, stac_item_json, collection_id,
                          blob_path=None, zarr_prefix=None,
                          approved_by=None, approved_at=None,
                          access_level=None, version_id=None):
```

This method ALWAYS sanitizes (strips geoetl:*) and optionally injects URLs. It becomes `materialize_approved()`.

### Current `stac_materialize_item` Handler (handler_materialize_item.py)

Looks up item from `cog_metadata` or `zarr_metadata`, then calls `materialize_to_pgstac()`. The handler needs a `mode` param to choose between structural and approved paths.

### Workflow YAML `when:` Conditional

Existing pattern in `vector_docker_etl.yaml:61`:
```yaml
create_split_views:
    when: "params.processing_options.split_column"
```

This is how we gate optional STAC nodes on `params.create_stac`.

### `build_stac_item()` Signature (stac_item_builder.py:27)

Accepts: item_id, collection_id, bbox, asset_href, asset_type, asset_key, asset_roles, datetime, crs, detected_type, dataset_id, resource_id, version_id, title, job_id, epoch.

### Handler Contract

All handlers: `def handler(params, context=None) -> {"success": bool, "result": {...}}` or `{"success": False, "error": "...", "retryable": bool}`.

---

## Task 1: Add `materialize_structural()` to STACMaterializer

**Files:**
- Modify: `services/stac_materialization.py`

- [ ] **Step 1: Add `materialize_structural()` method**

Add this method BEFORE the existing `materialize_to_pgstac()` (after the `sanitize_item_properties` method, around line 135):

```python
    def materialize_structural(
        self,
        stac_item_json: dict,
        collection_id: str,
    ) -> Dict[str, Any]:
        """
        State 1 → State 2: Insert raw item into pgSTAC for structural purposes.

        NO sanitization (geoetl:* preserved for traceability).
        NO TiTiler/TiPG URL injection (not approved yet).
        NO approval stamping.
        Stamps ddh:status='processing' to distinguish from B2C items.
        Ensures collection exists. Upserts item.
        """
        try:
            item = copy.deepcopy(stac_item_json)
            item["collection"] = collection_id

            # Stamp structural status — distinguishes from B2C materialized items
            props = item.setdefault("properties", {})
            props["ddh:status"] = "processing"

            # Ensure collection exists (auto-create if missing)
            existing = self.pgstac.get_collection(collection_id)
            if not existing:
                from services.stac.stac_collection_builder import build_stac_collection
                bbox = item.get("bbox", [-180, -90, 180, 90])
                coll_dict = build_stac_collection(
                    collection_id=collection_id,
                    bbox=bbox,
                    temporal_start=props.get("datetime") or props.get("start_datetime"),
                )
                self.pgstac.insert_collection(coll_dict)
                logger.info("materialize_structural: auto-created collection %s", collection_id)

            # Upsert raw item (no sanitization, no URL injection)
            pgstac_id = self.pgstac.insert_item(item, collection_id)

            logger.info(
                "materialize_structural: %s -> collection %s (state 2)",
                item.get("id"), collection_id,
            )

            return {"success": True, "pgstac_id": pgstac_id}

        except Exception as exc:
            logger.error("materialize_structural failed: %s", exc, exc_info=True)
            return {"success": False, "error": str(exc)}
```

- [ ] **Step 2: Rename `materialize_to_pgstac` → `materialize_approved` with alias**

Rename the existing method and add an alias for backward compatibility:

After the existing `materialize_to_pgstac` method (around line 211), add:

```python
    # Alias for backward compatibility — callers using the old name still work
    materialize_to_pgstac = materialize_approved
```

And rename the method definition from `def materialize_to_pgstac(` to `def materialize_approved(`. Update its docstring to say "State 2 → State 3: B2C materialization after approval."

Also add `ddh:status = 'approved'` stamp in the approval properties block (around line 168):

```python
            # Step 3: Stamp approval properties
            props = item.setdefault("properties", {})
            props["ddh:status"] = "approved"
            if approved_by:
                props["ddh:approved_by"] = approved_by
```

- [ ] **Step 3: Verify import works**

Run: `python -c "from services.stac_materialization import STACMaterializer; m = STACMaterializer(); assert hasattr(m, 'materialize_structural'); assert hasattr(m, 'materialize_approved'); assert hasattr(m, 'materialize_to_pgstac'); print('OK')"`

- [ ] **Step 4: Commit**

```bash
git add services/stac_materialization.py
git commit -m "feat: add materialize_structural() for state 2 STAC inserts"
```

---

## Task 2: Add `mode` Parameter to `stac_materialize_item` Handler

**Files:**
- Modify: `services/stac/handler_materialize_item.py`

- [ ] **Step 1: Add mode parameter routing**

In the handler function, after the item lookup logic (around line 120, after `effective_zarr_prefix` is resolved), replace the materializer call block:

Find the block starting with `# Materialize to pgSTAC via single write path` (around line 122-128) and replace with:

```python
        # Materialize to pgSTAC — mode determines structural (state 2) vs approved (state 3)
        mode = params.get("mode", "approved")
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

- [ ] **Step 2: Handle `cog_ids` list for tiled structural inserts**

For tiled rasters, the handler receives `cog_ids` (a list). In structural mode, it needs to materialize each item. Find the existing `cog_ids` handling (if it exists) or add after the mode routing:

After the single-item materialize block, add handling for bulk structural inserts:

```python
        # Bulk mode: materialize multiple items (tiled raster collections)
        cog_ids = params.get("cog_ids")
        if cog_ids and isinstance(cog_ids, list) and mode == "structural":
            bulk_results = []
            for cid in cog_ids:
                try:
                    from infrastructure.raster_metadata_repository import RasterMetadataRepository
                    cog_repo = RasterMetadataRepository.instance()
                    cog_meta = cog_repo.get_by_id(cid)
                    if cog_meta and cog_meta.get("stac_item_json"):
                        item_json = copy.deepcopy(cog_meta["stac_item_json"])
                        item_json["id"] = cid
                        r = materializer.materialize_structural(item_json, collection_id)
                        if r.get("success"):
                            bulk_results.append(cid)
                except Exception as bulk_err:
                    logger.warning("Structural materialize failed for %s: %s", cid, bulk_err)

            return {
                "success": len(bulk_results) > 0,
                "result": {
                    "mode": "structural",
                    "items_materialized": len(bulk_results),
                    "collection_id": collection_id,
                },
            }
```

- [ ] **Step 3: Verify handler imports**

Run: `python -c "from services.stac.handler_materialize_item import stac_materialize_item; print('OK')"`

- [ ] **Step 4: Commit**

```bash
git add services/stac/handler_materialize_item.py
git commit -m "feat: add mode param to stac_materialize_item (structural/approved)"
```

---

## Task 3: Create `vector_build_stac_item` Handler

**Files:**
- Create: `services/vector/handler_build_stac_item.py`
- Modify: `services/__init__.py`
- Modify: `config/defaults.py`

- [ ] **Step 1: Create the handler file**

```python
# ============================================================================
# CLAUDE CONTEXT - VECTOR BUILD STAC ITEM HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.10 unified STAC lifecycle)
# STATUS: Atomic handler - Build STAC item JSON from PostGIS table metadata
# PURPOSE: Read bbox, row count, geometry type from geo.table_catalog and
#          build a STAC item with TiPG collection URL as the primary asset.
#          Only runs when create_stac=true. Caches result on Release.
# CREATED: 03 APR 2026
# EXPORTS: vector_build_stac_item
# DEPENDENCIES: services.stac.stac_item_builder, infrastructure.release_repository
# ============================================================================
"""
Vector Build STAC Item — DAG handler for optional vector STAC registration.

Reads metadata from geo.table_catalog (populated by register_catalog handler)
and builds a STAC item with the TiPG OGC Features collection URL as the
primary asset. The item is cached on the Release for downstream
materialize_structural and materialize_approved handlers.

This handler only runs when create_stac=true in processing_options.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def vector_build_stac_item(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Build a STAC item for a vector dataset from PostGIS table metadata.

    Params:
        table_name (str, required): PostGIS table name
        schema_name (str): PostGIS schema (default: geo)
        collection_id (str, required): STAC collection ID
        stac_item_id (str, required): STAC item ID
        dataset_id (str): Platform dataset ID
        resource_id (str): Platform resource ID
        version_id (str): Platform version ID
        release_id (str): Release to cache stac_item_json on
        tables_info (list): Table creation results from create_and_load_tables
        _run_id (str): System-injected

    Returns:
        {"success": True, "result": {"stac_item_id", "collection_id", "stac_item_json_cached"}}
    """
    table_name = params.get("table_name")
    schema_name = params.get("schema_name", "geo")
    collection_id = params.get("collection_id")
    stac_item_id = params.get("stac_item_id")
    release_id = params.get("release_id")
    tables_info = params.get("tables_info", [])
    run_id = params.get("_run_id", "unknown")

    missing = []
    if not table_name:
        missing.append("table_name")
    if not collection_id:
        missing.append("collection_id")
    if not stac_item_id:
        missing.append("stac_item_id")
    if missing:
        return {
            "success": False,
            "error": f"Missing required parameters: {', '.join(missing)}",
            "error_type": "ValidationError",
            "retryable": False,
        }

    try:
        from config import get_config
        from services.stac.stac_item_builder import build_stac_item

        config = get_config()

        # Extract bbox and metadata from tables_info (created by create_and_load_tables)
        # Use the first (or primary) table's metadata
        primary_table = None
        for ti in tables_info:
            if ti.get("table_name") == table_name or not primary_table:
                primary_table = ti

        if not primary_table:
            # Fallback: use table_name directly, with global bbox
            primary_table = {"table_name": table_name, "bbox": [-180, -90, 180, 90]}
            logger.warning(
                "vector_build_stac_item: no tables_info match for %s, using global bbox",
                table_name,
            )

        bbox = primary_table.get("bbox", [-180, -90, 180, 90])
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            bbox = list(bbox)
        else:
            bbox = [-180, -90, 180, 90]

        geometry_type = primary_table.get("geometry_type", "unknown")
        row_count = primary_table.get("row_count", 0)

        # TiPG collection URL as the vector asset
        tipg_base = config.titiler_base_url.rstrip("/")
        tipg_collection = f"{schema_name}.{table_name}"
        asset_href = f"{tipg_base}/collections/{tipg_collection}"

        now_iso = datetime.now(timezone.utc).isoformat()

        stac_item_json = build_stac_item(
            item_id=stac_item_id,
            collection_id=collection_id,
            bbox=bbox,
            asset_href=asset_href,
            asset_type="application/geo+json",
            asset_key="ogc-features",
            asset_roles=["data"],
            datetime=now_iso,
            crs="EPSG:4326",
            detected_type="vector",
            dataset_id=params.get("dataset_id"),
            resource_id=params.get("resource_id"),
            version_id=params.get("version_id"),
            title=params.get("title"),
            job_id=run_id,
            epoch=5,
        )

        # Add vector-specific properties
        stac_item_json["properties"]["vector:geometry_type"] = geometry_type
        stac_item_json["properties"]["vector:row_count"] = row_count
        stac_item_json["properties"]["vector:tipg_collection"] = tipg_collection

        # Cache on Release for downstream materialization
        if release_id:
            try:
                from infrastructure.release_repository import ReleaseRepository
                release_repo = ReleaseRepository()
                release_repo.update_stac_item_json(release_id, stac_item_json)
                logger.info(
                    "vector_build_stac_item: cached stac_item_json on release %s",
                    release_id[:16],
                )
            except Exception as cache_err:
                logger.warning(
                    "vector_build_stac_item: failed to cache on release %s: %s",
                    release_id[:16] if release_id else "?", cache_err,
                )

        logger.info(
            "vector_build_stac_item: built STAC item %s for %s.%s (%s, %d rows)",
            stac_item_id, schema_name, table_name, geometry_type, row_count,
        )

        return {
            "success": True,
            "result": {
                "stac_item_id": stac_item_id,
                "collection_id": collection_id,
                "stac_item_json_cached": True,
                "geometry_type": geometry_type,
                "row_count": row_count,
            },
        }

    except Exception as exc:
        import traceback
        logger.error(
            "vector_build_stac_item failed: %s\n%s", exc, traceback.format_exc()
        )
        return {
            "success": False,
            "error": f"Failed to build vector STAC item: {exc}",
            "error_type": "HandlerError",
            "retryable": False,
        }
```

- [ ] **Step 2: Register handler in `services/__init__.py`**

After the `release_link_tables` import (around line 131), add:

```python
from .vector.handler_build_stac_item import vector_build_stac_item
```

In ALL_HANDLERS dict (after `release_link_tables` entry), add:

```python
    "vector_build_stac_item": vector_build_stac_item,
```

- [ ] **Step 3: Add to DOCKER_TASKS in `config/defaults.py`**

After the `release_link_tables` entry (around line 504), add:

```python
        "vector_build_stac_item",         # V0.10.10: Optional vector STAC item builder
```

- [ ] **Step 4: Verify import**

Run: `python -c "from services import ALL_HANDLERS; assert 'vector_build_stac_item' in ALL_HANDLERS; print('OK')"`

- [ ] **Step 5: Commit**

```bash
git add services/vector/handler_build_stac_item.py services/__init__.py config/defaults.py
git commit -m "feat: add vector_build_stac_item handler for optional STAC registration"
```

---

## Task 4: Add `create_stac` to VectorProcessingOptions and Translation

**Files:**
- Modify: `core/models/processing_options.py`
- Modify: `services/platform_translation.py`

- [ ] **Step 1: Add `create_stac` field to VectorProcessingOptions**

In `core/models/processing_options.py`, after the `temporal_property` field (around line 228), add:

```python
    # Optional STAC catalog registration (03 APR 2026)
    create_stac: bool = Field(
        default=False,
        description=(
            "Create STAC catalog entry for vector dataset. When true, "
            "the workflow builds a STAC item from PostGIS table metadata "
            "and registers it in pgSTAC for catalog discovery."
        )
    )
```

- [ ] **Step 2: Forward `create_stac` in `_reshape_vector_params`**

In `services/platform_translation.py`, update the forwarding loop in `_reshape_vector_params` (around line 630):

```python
    for key in ('overwrite', 'split_column', 'converter_params', 'layer_name',
                'indexes', 'temporal_property', 'create_stac'):
```

Also forward from the Epoch 4 translation path. In `translate_to_coremachine` vector section (after the `'temporal_property': opts.temporal_property,` line around line 363), add:

```python
            'create_stac': opts.create_stac,
```

- [ ] **Step 3: Verify Pydantic accepts the field**

Run: `python -c "from core.models.processing_options import VectorProcessingOptions; o = VectorProcessingOptions(create_stac=True); print(f'create_stac={o.create_stac}'); o2 = VectorProcessingOptions(); print(f'default={o2.create_stac}')"`
Expected: `create_stac=True` then `default=False`

- [ ] **Step 4: Commit**

```bash
git add core/models/processing_options.py services/platform_translation.py
git commit -m "feat: add create_stac to VectorProcessingOptions and translation"
```

---

## Task 5: Rewire Raster Workflow YAMLs

**Files:**
- Modify: `workflows/process_raster.yaml`
- Modify: `workflows/process_raster_collection.yaml`

- [ ] **Step 1: Update `process_raster.yaml`**

Replace the STAC materialization section (everything from `approval_gate:` to `materialize_collection:`) with:

```yaml
  # -- STRUCTURAL STAC INSERT (state 2 — before approval) --
  # Insert raw items into pgSTAC so tiled collections have mosaic preview.
  # Single COGs also get structural insert for consistent state machine.
  materialize_structural_single:
    type: task
    handler: stac_materialize_item
    depends_on:
      - "persist_single?"
    when: "upload_single_cog.result.stac_item_id"
    params: [collection_id]
    receives:
      cog_id: "upload_single_cog.result.stac_item_id"
    mode: structural

  materialize_structural_tiled:
    type: task
    handler: stac_materialize_item
    depends_on:
      - "persist_tiled?"
    when: "persist_tiled.result.cog_ids"
    params: [collection_id]
    receives:
      cog_ids: "persist_tiled.result.cog_ids"
    mode: structural

  materialize_collection_structural:
    type: task
    handler: stac_materialize_collection
    depends_on:
      - "materialize_structural_single?"
      - "materialize_structural_tiled?"
    params: [collection_id]

  # -- APPROVAL GATE (reviewer can preview via pgSTAC) --
  approval_gate:
    type: gate
    gate_type: approval
    depends_on:
      - "materialize_collection_structural"

  # -- B2C MATERIALIZATION (state 3 — after approval) --
  materialize_single_item:
    type: task
    handler: stac_materialize_item
    depends_on: [approval_gate]
    when: "upload_single_cog.result.stac_item_id"
    params: [collection_id]
    receives:
      cog_id: "upload_single_cog.result.stac_item_id"
      blob_path: "upload_single_cog.result.silver_blob_path"
    mode: approved

  materialize_tiled_items:
    type: task
    handler: stac_materialize_item
    depends_on:
      - "approval_gate"
      - "persist_tiled?"
    when: "persist_tiled.result.cog_ids"
    params: [collection_id]
    receives:
      cog_ids: "persist_tiled.result.cog_ids"
    mode: approved

  materialize_collection:
    type: task
    handler: stac_materialize_collection
    depends_on:
      - "materialize_single_item?"
      - "materialize_tiled_items?"
    params: [collection_id]
```

- [ ] **Step 2: Update `process_raster_collection.yaml`**

Same pattern: add structural materialization nodes before the approval gate, keep approved materialization after. The persist_collection node outputs `cog_ids`. Add before `approval_gate`:

```yaml
  # State 2: structural insert
  materialize_structural:
    type: task
    handler: stac_materialize_item
    depends_on: [persist_collection]
    params: [collection_id]
    receives:
      cog_ids: "persist_collection.result.cog_ids"
    mode: structural

  materialize_collection_structural:
    type: task
    handler: stac_materialize_collection
    depends_on: [materialize_structural]
    params: [collection_id]

  approval_gate:
    type: gate
    gate_type: approval
    depends_on: [materialize_collection_structural]
```

And update the existing post-approval materialization nodes to include `mode: approved`.

- [ ] **Step 3: Validate both YAMLs**

Run: `python -c "import yaml; yaml.safe_load(open('workflows/process_raster.yaml')); yaml.safe_load(open('workflows/process_raster_collection.yaml')); print('Both YAML valid')"`

- [ ] **Step 4: Commit**

```bash
git add workflows/process_raster.yaml workflows/process_raster_collection.yaml
git commit -m "feat: add structural STAC insert before approval gate in raster workflows"
```

---

## Task 6: Rewire Zarr and Vector Workflow YAMLs

**Files:**
- Modify: `workflows/ingest_zarr.yaml`
- Modify: `workflows/vector_docker_etl.yaml`

- [ ] **Step 1: Update `ingest_zarr.yaml`**

Add structural materialization before the approval gate (which doesn't exist yet in this workflow — add one). Currently zarr has no approval gate. Add:

After `register` node and before `materialize_item`, insert:

```yaml
  # State 2: structural insert (pre-approval)
  materialize_structural:
    type: task
    handler: stac_materialize_item
    depends_on: [register]
    params: [collection_id, dry_run]
    receives:
      cog_id: "register.result.zarr_id"
    mode: structural

  materialize_collection_structural:
    type: task
    handler: stac_materialize_collection
    depends_on: [materialize_structural]
    params: [collection_id, dry_run]

  # APPROVAL GATE
  approval_gate:
    type: gate
    gate_type: approval
    depends_on: [materialize_collection_structural]

  # State 3: B2C materialization (post-approval)
  materialize_item:
    type: task
    handler: stac_materialize_item
    depends_on: [approval_gate]
    params: [collection_id, dry_run]
    receives:
      cog_id: "register.result.zarr_id"
    mode: approved

  materialize_collection:
    type: task
    handler: stac_materialize_collection
    depends_on: [materialize_item]
    params: [collection_id, dry_run]
```

- [ ] **Step 2: Update `vector_docker_etl.yaml`**

Add `create_stac` parameter and conditional STAC nodes. Add to parameters section:

```yaml
  create_stac: {type: bool, default: false}
```

After `register_catalog` node and before `refresh_tipg`, add:

```yaml
  # -- Optional STAC: build item from table_catalog metadata --
  build_stac_item:
    type: task
    handler: vector_build_stac_item
    depends_on: [register_catalog]
    when: "params.create_stac"
    params: [table_name, schema_name, collection_id, stac_item_id,
             dataset_id, resource_id, version_id, release_id, title]
    receives:
      tables_info: "create_and_load_tables.result.tables_created"

  # Optional: State 2 structural STAC insert
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

  # Optional: Collection materialization
  materialize_collection:
    type: task
    handler: stac_materialize_collection
    depends_on: ["materialize_approved?"]
    when: "params.create_stac"
    params: [collection_id]
```

Note: For vector, both structural and approved materialize run AFTER the approval gate (because `build_stac_item` depends on `register_catalog` which is post-gate). This is correct — vector STAC is catalog metadata, not a preview mechanism.

- [ ] **Step 3: Validate both YAMLs**

Run: `python -c "import yaml; yaml.safe_load(open('workflows/ingest_zarr.yaml')); yaml.safe_load(open('workflows/vector_docker_etl.yaml')); print('Both YAML valid')"`

- [ ] **Step 4: Commit**

```bash
git add workflows/ingest_zarr.yaml workflows/vector_docker_etl.yaml
git commit -m "feat: add STAC lifecycle to zarr (with approval gate) and vector (optional) workflows"
```

---

## Task 7: Add Reject STAC Cleanup

**Files:**
- Modify: `services/asset_approval_service.py` (or wherever reject is handled)

- [ ] **Step 1: Find the reject handler**

Search for the reject/rejection flow:
```bash
grep -rn "def.*reject\|approval_state.*rejected" services/asset_approval_service.py triggers/trigger_approvals.py | head -10
```

- [ ] **Step 2: Add STAC cleanup on rejection**

In the reject handler, after marking `approval_state='rejected'`, add:

```python
        # Clean up structural STAC item (state 2) on rejection
        # With unified lifecycle, processing inserts a structural item into pgSTAC.
        # Rejection means this item should be removed.
        if release.stac_item_id and release.stac_collection_id:
            try:
                from services.stac_materialization import STACMaterializer
                materializer = STACMaterializer()
                result = materializer.dematerialize_item(
                    release.stac_collection_id, release.stac_item_id
                )
                if result.get("deleted"):
                    logger.info(
                        "Cleaned up structural STAC item on rejection: %s/%s",
                        release.stac_collection_id, release.stac_item_id,
                    )
            except Exception as stac_err:
                logger.warning(
                    "Failed to clean up structural STAC item on rejection: %s (non-fatal)",
                    stac_err,
                )
```

- [ ] **Step 3: Commit**

```bash
git add services/asset_approval_service.py
git commit -m "feat: clean up structural STAC item on rejection"
```

---

## Summary

| Task | What | New Files | Commits |
|------|------|-----------|---------|
| 1 | `materialize_structural()` + rename to `materialize_approved()` | — | 1 |
| 2 | Handler `mode` parameter (structural/approved) | — | 1 |
| 3 | `vector_build_stac_item` handler + registration | 1 | 1 |
| 4 | `create_stac` Pydantic field + translation | — | 1 |
| 5 | Raster workflow YAMLs (structural before gate) | — | 1 |
| 6 | Zarr workflow (add approval gate) + Vector YAML (optional STAC) | — | 1 |
| 7 | Reject STAC cleanup | — | 1 |

**Total: 1 new file, ~10 modified files, 7 commits**
