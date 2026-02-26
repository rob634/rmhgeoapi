# Geometry-Type Splitting — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Instead of rejecting mixed-geometry uploads, split them by geometry type into separate PostGIS tables (e.g., `_point`, `_line`, `_polygon`).

**Architecture:** Move the mixed-geometry detection in `prepare_gdf()` from a rejection to a `groupby` split at the end of the method. Change return type from `GeoDataFrame` to `dict[str, GeoDataFrame]`. Update the handler to loop over the dict, creating one table per geometry type. Single-type uploads still produce one table with no suffix.

**Tech Stack:** Python 3.12, GeoPandas, Pydantic v2, psycopg 3, PostgreSQL/PostGIS

**Depends on:** `docs/plans/2026-02-26-multi-table-release.md` (release_tables junction must exist first)

**Key files:**
- `services/vector/postgis_handler.py` — `prepare_gdf()` method (lines 83-719)
- `services/vector/core.py` — `validate_and_prepare()` wrapper (lines 246-325)
- `services/handler_vector_docker_complete.py` — handler phases 2-4 (lines 243-489)
- `services/curated/wdpa_handler.py` — secondary caller of `prepare_gdf()` (line 439)

**Future enhancement (deferred):** Explode `GeometryCollection` types into constituent geometries before the split. Currently these are still rejected at step 8 (PostGIS type validation).

---

## Task 1: Change `prepare_gdf()` Return Type

**Files:**
- Modify: `services/vector/postgis_handler.py:83-719`

**Step 1: Delete the mixed geometry rejection block**

Delete lines 456-481 (the `MIXED GEOMETRY TYPE DETECTION` block). This is the `raise ValueError("File contains mixed geometry types...")` block and its surrounding comments/emit.

**Step 2: Add geometry-type split at the end of the method**

Replace the final `return gdf` at line 719 with:

```python
        # ====================================================================
        # GEOMETRY TYPE SPLIT (26 FEB 2026)
        # ====================================================================
        # Split by geometry type. Always returns dict[str, GeoDataFrame].
        # Single-type files get one entry. Mixed-type files get 2-3 entries.
        # Suffixes only applied by caller when len(result) > 1.
        # ====================================================================
        GEOM_TYPE_SUFFIX = {
            'MultiPolygon': 'polygon',
            'MultiLineString': 'line',
            'MultiPoint': 'point',
        }

        groups = {}
        for geom_type, sub_gdf in gdf.groupby(gdf.geometry.geom_type):
            suffix = GEOM_TYPE_SUFFIX.get(geom_type, geom_type.lower())
            groups[suffix] = sub_gdf.copy()

        if len(groups) > 1:
            type_summary = {k: len(v) for k, v in groups.items()}
            logger.info(f"📊 Split into {len(groups)} geometry types: {type_summary}")
            emit("geometry_type_split", {
                "types": type_summary,
                "total_features": len(gdf)
            })
        else:
            key = list(groups.keys())[0]
            emit("geometry_type_uniform", {
                "geometry_type": key,
                "features": len(gdf)
            })

        return groups
```

**Step 3: Update the method signature and docstring**

Change the return type annotation and docstring at lines 83-114:

```python
    def prepare_gdf(
        self,
        gdf: gpd.GeoDataFrame,
        geometry_params: dict = None,
        event_callback: Optional[EventCallback] = None
    ) -> Dict[str, gpd.GeoDataFrame]:
        """
        Validate, reproject, clean, and split GeoDataFrame by geometry type.

        Runs all validation steps on the full GeoDataFrame (null removal,
        invalid fix, force 2D, antimeridian, normalize to Multi-types,
        winding order, PostGIS type validation, datetime validation,
        null column pruning, CRS reprojection, column sanitization,
        geometry processing). Then splits by geometry type at the end.

        Returns:
            Dict mapping geometry suffix to GeoDataFrame.
            Single-type files: {'polygon': gdf}
            Mixed-type files: {'polygon': gdf1, 'line': gdf2, 'point': gdf3}

        Raises:
            ValueError: If GeoDataFrame has no valid geometries or
                        contains unsupported geometry types
        """
```

Add `Dict` to the imports at the top of the file if not already present.

**Step 4: Verify the method parses**

Run:
```bash
cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "
from services.vector.postgis_handler import VectorToPostGISHandler
import inspect
sig = inspect.signature(VectorToPostGISHandler.prepare_gdf)
print(f'OK: prepare_gdf signature: {sig}')
print(f'Return annotation: {sig.return_annotation}')
"
```

**Step 5: Commit**

```bash
git add services/vector/postgis_handler.py
git commit -m "Change prepare_gdf to split by geometry type instead of rejecting mixed types"
```

---

## Task 2: Update `validate_and_prepare()` in core.py

**Files:**
- Modify: `services/vector/core.py:246-325`

The `validate_and_prepare()` function wraps `prepare_gdf()` and currently expects a single GeoDataFrame back. It needs to pass through the dict.

**Step 1: Update return type and logic**

Replace the function body at lines 246-325. The key changes:
- `validated_gdf` becomes `prepared_groups` (a dict)
- The empty-result check runs on the combined count across all groups
- The filtered-features warning uses the combined count
- Return type changes from `Tuple[GeoDataFrame, Dict, List]` to `Tuple[Dict[str, GeoDataFrame], Dict, List]`

```python
def validate_and_prepare(
    gdf: gpd.GeoDataFrame,
    geometry_params: Optional[Dict[str, Any]] = None,
    job_id: str = "unknown",
    event_callback: Optional[EventCallback] = None
) -> Tuple[Dict[str, gpd.GeoDataFrame], Dict[str, Any], List[str]]:
    """
    Validate geometries and prepare GeoDataFrame for PostGIS.

    Returns:
        Tuple of (prepared_groups, validation_info, warnings_list)
        prepared_groups: dict mapping geometry suffix to GeoDataFrame
    """
    from .postgis_handler import VectorToPostGISHandler

    original_count = len(gdf)

    handler = VectorToPostGISHandler()
    prepared_groups = handler.prepare_gdf(
        gdf,
        geometry_params=geometry_params or {},
        event_callback=event_callback
    )

    # Capture any warnings from prepare_gdf
    data_warnings = handler.last_warnings.copy() if hasattr(handler, 'last_warnings') and handler.last_warnings else []

    # Total validated count across all groups
    validated_count = sum(len(g) for g in prepared_groups.values())

    log_memory_checkpoint(
        logger, "After validation",
        context_id=job_id,
        validated_features=validated_count
    )

    if validated_count == 0:
        raise ValueError(
            f"All {original_count} features filtered out during geometry validation. "
            f"geometry_params: {geometry_params}. "
            f"Common causes: all NULL geometries, invalid coordinates, CRS reprojection failures."
        )

    if validated_count < original_count:
        filtered_count = original_count - validated_count
        pct_filtered = filtered_count / original_count * 100
        warning_msg = (
            f"{filtered_count} features ({pct_filtered:.1f}%) filtered out during validation. "
            f"{validated_count} features remaining."
        )
        logger.warning(f"[{job_id[:8]}] {warning_msg}")
        data_warnings.append(warning_msg)

    validation_info = {
        'original_count': original_count,
        'validated_count': validated_count,
        'filtered_count': original_count - validated_count,
        'geometry_groups': len(prepared_groups),
        'group_counts': {k: len(v) for k, v in prepared_groups.items()},
    }

    return prepared_groups, validation_info, data_warnings
```

**Step 2: Commit**

```bash
git add services/vector/core.py
git commit -m "Update validate_and_prepare to pass through geometry-split dict"
```

---

## Task 3: Update `_load_and_validate_source()` in Handler

**Files:**
- Modify: `services/handler_vector_docker_complete.py:590-767`

**Step 1: Update return type**

The function at line 599 currently returns `(GeoDataFrame, load_info, validation_info, warnings)`. Change it to return `(Dict[str, GeoDataFrame], load_info, validation_info, warnings)`.

At line 746-751, `validated_gdf` becomes `prepared_groups`:

```python
    prepared_groups, validation_info, warnings = validate_and_prepare(
        gdf=gdf,
        geometry_params=geometry_params,
        job_id=job_id,
        event_callback=event_callback
    )
```

At lines 753-755, `extract_geometry_info` was called on the single GDF. Replace with group-aware logic:

```python
    # Extract geometry info from all groups
    all_geom_types = list(prepared_groups.keys())
    validation_info['geometry_types'] = all_geom_types
    validation_info['geometry_type'] = all_geom_types[0] if len(all_geom_types) == 1 else 'mixed'
```

At line 757, `log_gdf_memory` was called on the single GDF. Update:

```python
    for suffix, sub_gdf in prepared_groups.items():
        log_gdf_memory(sub_gdf, f"after_validation_{suffix}", job_id)
```

At lines 760-765, update the emit to include group info:

```python
    total_validated = sum(len(g) for g in prepared_groups.values())
    emit("validation_complete", {
        "original_features": validation_info['original_count'],
        "validated_features": total_validated,
        "filtered_features": validation_info['filtered_count'],
        "geometry_types": all_geom_types,
        "geometry_groups": len(prepared_groups),
    })
```

At line 767, return `prepared_groups` instead of `validated_gdf`:

```python
    return prepared_groups, load_info, validation_info, warnings
```

**Step 2: Update the docstring** at lines 600-616 to reflect the new return type.

**Step 3: Commit**

```bash
git add services/handler_vector_docker_complete.py
git commit -m "Update _load_and_validate_source to return geometry-split dict"
```

---

## Task 4: Extract Per-Table Processing Into Helper Function

**Files:**
- Modify: `services/handler_vector_docker_complete.py`

Before adding the loop, extract Phases 2-4 + post-upload validation into a helper function. This avoids deep nesting inside the loop.

**Step 1: Create `_process_single_table()` helper**

Add this function after the existing `_create_table_and_metadata()` function (around line 870). It wraps Phases 2, 2.5, 3, 3.5, 4, and post-upload validation:

```python
def _process_single_table(
    gdf: 'gpd.GeoDataFrame',
    table_name: str,
    schema: str,
    overwrite: bool,
    parameters: Dict[str, Any],
    load_info: Dict[str, Any],
    job_id: str,
    chunk_size: int,
    checkpoint_fn: callable,
    table_group: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Process a single GeoDataFrame into a PostGIS table.

    Handles: table creation, metadata, style, chunk upload,
    deferred indexes, ANALYZE, TiPG refresh, post-upload validation.

    Args:
        gdf: Single-type GeoDataFrame to upload
        table_name: Target PostGIS table name (with suffix if split)
        schema: Target schema (default 'geo')
        overwrite: Whether to overwrite existing table
        parameters: Full job parameters
        load_info: File loading metadata
        job_id: Job ID for logging
        chunk_size: Rows per chunk
        checkpoint_fn: Checkpoint callback
        table_group: Optional group name for split tables

    Returns:
        Dict with table_name, geometry_type, total_rows, style_id, vector_tile_urls
    """
    from services.vector.postgis_handler import VectorToPostGISHandler
    from services.vector.core import extract_geometry_info

    logger.info(f"[{job_id[:8]}] Processing table: {schema}.{table_name} ({len(gdf)} features)")

    # Phase 2: Create table and metadata
    table_result = _create_table_and_metadata(
        gdf=gdf,
        table_name=table_name,
        schema=schema,
        overwrite=overwrite,
        parameters=parameters,
        load_info=load_info,
        job_id=job_id
    )

    # Set table_group in catalog if this is a geometry split
    if table_group:
        try:
            _handler = VectorToPostGISHandler()
            with _handler._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    from psycopg import sql as psql
                    cur.execute(
                        psql.SQL(
                            "UPDATE {schema}.table_catalog SET table_group = %s "
                            "WHERE table_name = %s"
                        ).format(schema=psql.Identifier("geo")),
                        (table_group, table_name)
                    )
                    conn.commit()
            logger.info(f"[{job_id[:8]}] Set table_group='{table_group}' for {table_name}")
        except Exception as e:
            logger.warning(f"[{job_id[:8]}] Failed to set table_group (non-fatal): {e}")

    checkpoint_fn(f"table_created_{table_name}", {
        "table": f"{schema}.{table_name}",
        "geometry_type": table_result['geometry_type'],
        "srid": table_result['srid']
    })

    # Phase 2.5: Create default style
    style_result = _create_default_style(
        table_name=table_name,
        geometry_type=table_result['geometry_type'],
        style_params=parameters.get('style'),
        job_id=job_id
    )

    # Phase 3: Upload chunks
    upload_result = _upload_chunks_with_checkpoints(
        gdf=gdf,
        table_name=table_name,
        schema=schema,
        chunk_size=chunk_size,
        job_id=job_id,
        checkpoint_fn=checkpoint_fn
    )

    # Phase 3.5: Deferred indexes + ANALYZE
    _post_handler = VectorToPostGISHandler()
    indexes = parameters.get('indexes', {'spatial': True, 'attributes': [], 'temporal': []})
    _post_handler.create_deferred_indexes(
        table_name=table_name,
        schema=schema,
        gdf=gdf,
        indexes=indexes
    )
    _post_handler.analyze_table(table_name, schema)

    # Phase 4: TiPG refresh
    tipg_collection_id = f"{schema}.{table_name}"
    tipg_refresh_data = _refresh_tipg(tipg_collection_id, job_id)
    checkpoint_fn(f"tipg_refresh_{table_name}", tipg_refresh_data)

    # Post-upload validation
    total_rows = upload_result.get('total_rows', 0)

    if total_rows == 0:
        raise ValueError(
            f"Vector ETL completed all phases but inserted 0 rows into "
            f"{schema}.{table_name}. Source had {len(gdf)} features."
        )

    # Cross-check row count
    try:
        from psycopg import sql as psql
        with _post_handler._pg_repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    psql.SQL("SELECT COUNT(*) FROM {schema}.{table}").format(
                        schema=psql.Identifier(schema),
                        table=psql.Identifier(table_name)
                    )
                )
                db_total = cur.fetchone()['count']
        if db_total != total_rows:
            logger.warning(
                f"[{job_id[:8]}] Row count discrepancy for {table_name}: "
                f"chunk sum={total_rows}, COUNT(*)={db_total}"
            )
            total_rows = db_total
    except Exception as count_err:
        logger.warning(f"[{job_id[:8]}] Could not verify row count for {table_name}: {count_err}")

    # Update metadata feature_count if needed
    if total_rows != len(gdf):
        try:
            from psycopg import sql as psql
            with _post_handler._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        psql.SQL(
                            "UPDATE {schema}.table_catalog SET feature_count = %s "
                            "WHERE table_name = %s AND schema_name = %s"
                        ).format(schema=psql.Identifier("geo")),
                        (total_rows, table_name, schema)
                    )
                    conn.commit()
        except Exception as meta_err:
            logger.warning(f"[{job_id[:8]}] Could not update feature_count for {table_name}: {meta_err}")

    return {
        "table_name": table_name,
        "geometry_type": table_result['geometry_type'],
        "total_rows": total_rows,
        "srid": table_result.get('srid', 4326),
        "style_id": style_result.get('style_id', 'default'),
        "chunks_uploaded": upload_result.get('chunks_uploaded', 0),
        "vector_tile_urls": table_result.get('vector_tile_urls'),
    }
```

**Step 2: Extract TiPG refresh into a small helper**

Extract the Phase 4 TiPG refresh logic (lines 322-386 in the current handler) into a `_refresh_tipg()` helper so `_process_single_table` can call it cleanly:

```python
def _refresh_tipg(tipg_collection_id: str, job_id: str) -> Dict[str, Any]:
    """Refresh TiPG catalog for a collection. Returns refresh data dict."""
    tipg_refresh_data = {"collection_id": tipg_collection_id, "status": "pending"}

    try:
        from infrastructure.service_layer_client import ServiceLayerClient
        sl_client = ServiceLayerClient()
        logger.info(f"[{job_id[:8]}] Refreshing TiPG catalog for {tipg_collection_id}")

        refresh_result = sl_client.refresh_tipg_collections()

        if refresh_result.status == "success":
            tipg_refresh_data = {
                "collection_id": tipg_collection_id,
                "status": "success",
                "collections_before": refresh_result.collections_before,
                "collections_after": refresh_result.collections_after,
                "new_collections": refresh_result.new_collections,
                "collection_discovered": tipg_collection_id in refresh_result.new_collections
            }
        else:
            tipg_refresh_data = {
                "collection_id": tipg_collection_id,
                "status": "error",
                "error": refresh_result.error
            }

        # Probe collection
        try:
            probe = sl_client.probe_collection(tipg_collection_id)
            tipg_refresh_data['probe'] = probe
        except Exception as probe_err:
            tipg_refresh_data['probe'] = {'status': 'failed', 'error': str(probe_err)}

    except Exception as e:
        tipg_refresh_data = {
            "collection_id": tipg_collection_id,
            "status": "failed",
            "error": str(e)
        }
        logger.warning(f"[{job_id[:8]}] TiPG refresh for {tipg_collection_id} failed (non-fatal): {e}")

    return tipg_refresh_data
```

**Step 3: Commit**

```bash
git add services/handler_vector_docker_complete.py
git commit -m "Extract _process_single_table and _refresh_tipg helpers"
```

---

## Task 5: Replace Inline Phases With Loop

**Files:**
- Modify: `services/handler_vector_docker_complete.py` — main handler function (lines 209-489)

**Step 1: Update Phase 1 to receive dict**

At lines 220-230, change:

```python
        gdf, load_info, validation_info, warnings = _load_and_validate_source(...)
```

to:

```python
        prepared_groups, load_info, validation_info, warnings = _load_and_validate_source(...)
```

Update the checkpoint at lines 232-238:

```python
        total_features = sum(len(g) for g in prepared_groups.values())
        checkpoint("validated", {
            "features": total_features,
            "geometry_groups": len(prepared_groups),
            "group_counts": {k: len(v) for k, v in prepared_groups.items()},
            "crs": load_info['original_crs'],
            "columns": load_info['columns'],
            "file_size_mb": load_info['file_size_mb']
        })
```

**Step 2: Replace Phases 2-4 and post-upload validation with loop**

Delete the inline Phases 2, 2.5, 3, 3.5, 4, and post-upload validation (lines 243-444). Replace with:

```python
        # =====================================================================
        # PHASES 2-4: Process each geometry type into its own table
        # =====================================================================
        is_split = len(prepared_groups) > 1
        table_results = []
        grand_total_rows = 0

        for suffix, sub_gdf in prepared_groups.items():
            # Suffix only when multiple geometry types
            current_table = f"{table_name}_{suffix}" if is_split else table_name

            logger.info(
                f"[{job_id[:8]}] {'Split' if is_split else 'Single'} table: "
                f"{schema}.{current_table} ({len(sub_gdf)} features, {suffix})"
            )

            table_result = _process_single_table(
                gdf=sub_gdf,
                table_name=current_table,
                schema=schema,
                overwrite=overwrite,
                parameters=parameters,
                load_info=load_info,
                job_id=job_id,
                chunk_size=chunk_size,
                checkpoint_fn=checkpoint,
                table_group=table_name if is_split else None,
            )

            table_results.append(table_result)
            grand_total_rows += table_result['total_rows']

            # Write to release_tables junction (if release exists)
            if parameters.get('release_id'):
                try:
                    from infrastructure import ReleaseTableRepository
                    release_table_repo = ReleaseTableRepository()
                    release_table_repo.create(
                        release_id=parameters['release_id'],
                        table_name=current_table,
                        geometry_type=table_result['geometry_type'],
                        feature_count=table_result['total_rows'],
                        table_role='geometry_split' if is_split else 'primary',
                        table_suffix=f"_{suffix}" if is_split else None,
                    )
                except Exception as rt_err:
                    logger.warning(f"[{job_id[:8]}] Failed to write release_tables (non-fatal): {rt_err}")
```

**Step 3: Update the COMPLETE block and return value**

Replace the existing COMPLETE block (lines 445-489) to aggregate across all tables:

```python
        # =====================================================================
        # COMPLETE
        # =====================================================================
        elapsed = time.time() - start_time

        checkpoint("complete", {
            "tables_created": len(table_results),
            "total_rows": grand_total_rows,
            "elapsed_seconds": round(elapsed, 2)
        })

        rows_per_sec = grand_total_rows / elapsed if elapsed > 0 else 0
        logger.info(
            f"[{job_id[:8]}] Docker Vector ETL complete: "
            f"{grand_total_rows:,} rows across {len(table_results)} table(s) "
            f"in {elapsed:.1f}s ({rows_per_sec:.0f} rows/sec)"
        )

        # V0.9: Update release processing status to COMPLETED
        if parameters.get('release_id'):
            try:
                from infrastructure import ReleaseRepository
                from core.models.asset import ProcessingStatus
                release_repo = ReleaseRepository()
                release_repo.update_processing_status(parameters['release_id'], status=ProcessingStatus.COMPLETED)
            except Exception as release_err:
                logger.warning(f"[{job_id[:8]}] Failed to update release processing status: {release_err}")

        # Build result — backward compatible for single table, enhanced for multi
        primary_result = table_results[0]

        result = {
            "table_name": table_name if not is_split else None,
            "table_names": [tr['table_name'] for tr in table_results],
            "schema": schema,
            "total_rows": grand_total_rows,
            "geometry_type": primary_result['geometry_type'] if not is_split else 'mixed',
            "geometry_split": is_split,
            "tables": table_results,
            "srid": primary_result.get('srid', 4326),
            "style_id": primary_result.get('style_id', 'default'),
            "chunks_uploaded": sum(tr.get('chunks_uploaded', 0) for tr in table_results),
            "checkpoint_count": len(checkpoints),
            "elapsed_seconds": round(elapsed, 2),
            "execution_mode": "docker",
            "connection_pooling": True,
            "data_warnings": data_warnings if data_warnings else None,
            "vector_tile_urls": primary_result.get('vector_tile_urls'),
        }

        return {"success": True, "result": result}
```

**Step 4: Update the error handler context**

In the `except` block (around line 529), the error context references `table_name`. Keep as-is — it's the base table name, which is fine for error reporting.

**Step 5: Commit**

```bash
git add services/handler_vector_docker_complete.py
git commit -m "Replace inline phases with geometry-split loop using _process_single_table"
```

---

## Task 6: Update WDPA Curated Handler

**Files:**
- Modify: `services/curated/wdpa_handler.py:439`

The WDPA handler calls `prepare_gdf()` directly. It's a curated dataset that is always single-type (polygons), so the dict will always have one entry. But the call site needs to handle the new return type.

**Step 1: Update the call site**

At line 439, replace:

```python
            gdf = handler.prepare_gdf(gdf)
```

with:

```python
            prepared_groups = handler.prepare_gdf(gdf)
            # WDPA is always single-type (polygons) — take the one entry
            if len(prepared_groups) != 1:
                raise ValueError(
                    f"WDPA data unexpectedly contains {len(prepared_groups)} geometry types: "
                    f"{list(prepared_groups.keys())}. Expected single type."
                )
            gdf = list(prepared_groups.values())[0]
```

**Step 2: Commit**

```bash
git add services/curated/wdpa_handler.py
git commit -m "Update WDPA handler for prepare_gdf dict return type"
```

---

## Task 7: Update `extract_geometry_info()` in core.py

**Files:**
- Modify: `services/vector/core.py:411-429`

This function is called from `_load_and_validate_source` (line 754) and `_create_table_and_metadata` (line 796). The handler call was updated in Task 3. The `_create_table_and_metadata` call receives a single-type GDF (from inside the loop), so it still works as-is. No changes needed to the function itself — just verify it's not called on the dict anywhere.

**Step 1: Search for any remaining callers that pass the dict**

Run:
```bash
cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo grep -rn "extract_geometry_info" services/ --include="*.py"
```

Verify all call sites pass a single GeoDataFrame, not the dict.

**Step 2: Commit (if any fixes needed)**

---

## Task 8: Final Verification

**Step 1: Run full import check**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "
from services.vector.postgis_handler import VectorToPostGISHandler
from services.vector.core import validate_and_prepare
from services.handler_vector_docker_complete import vector_docker_complete
from services.curated.wdpa_handler import WDPAHandler
print('All imports OK')
"
```

**Step 2: Verify prepare_gdf returns dict with test data**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "
import geopandas as gpd
from shapely.geometry import Point, Polygon
from services.vector.postgis_handler import VectorToPostGISHandler

# Single type
gdf_single = gpd.GeoDataFrame(
    {'name': ['a', 'b']},
    geometry=[Point(0, 0), Point(1, 1)],
    crs='EPSG:4326'
)
handler = VectorToPostGISHandler()
result = handler.prepare_gdf(gdf_single)
assert isinstance(result, dict), f'Expected dict, got {type(result)}'
assert len(result) == 1, f'Expected 1 group, got {len(result)}'
print(f'Single type OK: {list(result.keys())}')

# Mixed type
gdf_mixed = gpd.GeoDataFrame(
    {'name': ['a', 'b']},
    geometry=[Point(0, 0), Polygon([(0,0), (1,0), (1,1), (0,0)])],
    crs='EPSG:4326'
)
result2 = handler.prepare_gdf(gdf_mixed)
assert isinstance(result2, dict)
assert len(result2) == 2, f'Expected 2 groups, got {len(result2)}'
print(f'Mixed type OK: {list(result2.keys())}')
print('All tests passed')
"
```

Expected output:
```
Single type OK: ['point']
Mixed type OK: ['point', 'polygon']
All tests passed
```

**Step 3: Run existing test suite**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/ -v --tb=short 2>&1 | head -50
```

**Step 4: Commit any fixes**

```bash
git add -A
git commit -m "Fix any issues from geometry splitting verification"
```

---

## Deployment Notes

- This plan **depends on** the multi-table release schema change (`docs/plans/2026-02-26-multi-table-release.md`). Deploy that first so `app.release_tables` and `geo.table_catalog.table_group` exist.
- After deploying both, test with a mixed-geometry GeoJSON to verify end-to-end splitting.
- Single-type uploads are unaffected — the loop runs once with no suffix.

## Out of Scope (Deferred)

- **GeometryCollection explosion**: Currently still rejected at step 8. Future enhancement: explode into constituent geometries before the split.
- **Unpublish multi-table**: The unpublish job needs updating to drop all tables for a release. Design separately.
- **UI grouping**: Using `table_group` to visually group split tables in the web interface.
