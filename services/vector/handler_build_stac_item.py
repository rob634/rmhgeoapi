# ============================================================================
# CLAUDE CONTEXT - VECTOR BUILD STAC ITEM HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.10 unified STAC lifecycle)
# STATUS: Atomic handler - Build STAC item JSON from PostGIS table metadata
# PURPOSE: Read bbox, row count, geometry type from table results and build
#          a STAC item with TiPG collection URL as the primary asset.
# CREATED: 03 APR 2026
# EXPORTS: vector_build_stac_item
# DEPENDENCIES: services.stac.stac_item_builder, infrastructure.release_repository
# ============================================================================
"""
Vector Build STAC Item — construct STAC JSON from PostGIS table metadata.

Reads tables_info (list of table results from create_and_load_tables),
extracts bbox / geometry_type / row_count from the primary table, and
builds a STAC item with TiPG OGC Features collection URL as the asset.

Optionally caches the built stac_item_json on the Release record so
that stac_materialize_item can read it without recomputation.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Default bbox when table metadata lacks spatial extent
_DEFAULT_BBOX = [-180.0, -90.0, 180.0, 90.0]


def vector_build_stac_item(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Build a STAC item for a vector dataset from PostGIS table metadata.

    Params:
        table_name (str, required): Primary table name.
        schema_name (str, default "geo"): PostGIS schema.
        collection_id (str, required): STAC collection to place the item in.
        stac_item_id (str, required): STAC item identifier.
        dataset_id (str, optional): DDH dataset ID.
        resource_id (str, optional): DDH resource ID.
        version_id (str, optional): DDH version ID.
        release_id (str, optional): If provided, cache stac_item_json on Release.
        title (str, optional): Human-readable title.
        tables_info (list): From create_and_load_tables result.
            Each entry: {table_name, geometry_type, row_count, bbox, srid}.
        _run_id (str): System-injected DAG run ID.

    Returns:
        {"success": True, "result": {"stac_item_id", "collection_id", "stac_item_json_cached"}}
    """
    table_name = params.get("table_name")
    schema_name = params.get("schema_name", "geo")
    collection_id = params.get("collection_id")
    stac_item_id = params.get("stac_item_id")
    tables_info = params.get("tables_info", [])
    release_id = params.get("release_id")
    _run_id = params.get("_run_id", "unknown")

    # ── Validate required params ──────────────────────────────────────────
    if not table_name:
        return {"success": False, "error": "table_name is required", "error_type": "ValidationError", "retryable": False}
    if not collection_id:
        return {"success": False, "error": "collection_id is required", "error_type": "ValidationError", "retryable": False}
    if not stac_item_id:
        return {"success": False, "error": "stac_item_id is required", "error_type": "ValidationError", "retryable": False}
    if not tables_info:
        return {"success": False, "error": "tables_info is required (list of table results)", "error_type": "ValidationError", "retryable": False}

    log_prefix = f"[{_run_id[:8]}]"

    try:
        from config import get_config
        from services.stac.stac_item_builder import build_stac_item

        config = get_config()

        # ── Find primary table entry ──────────────────────────────────────
        primary = None
        for entry in tables_info:
            if entry.get("table_name") == table_name:
                primary = entry
                break
        if primary is None:
            primary = tables_info[0]

        # ── Extract spatial metadata ──────────────────────────────────────
        bbox = primary.get("bbox") or _DEFAULT_BBOX
        if len(bbox) < 4:
            bbox = _DEFAULT_BBOX
        geometry_type = primary.get("geometry_type", "unknown")
        row_count = primary.get("row_count", 0)

        # ── Build TiPG asset URL ──────────────────────────────────────────
        tipg_collection = f"{schema_name}.{table_name}"
        asset_href = f"{config.tipg_base_url}/collections/{tipg_collection}"

        # ── Build STAC item ───────────────────────────────────────────────
        stac_item_json = build_stac_item(
            item_id=stac_item_id,
            collection_id=collection_id,
            bbox=bbox,
            asset_href=asset_href,
            asset_type="application/geo+json",
            asset_key="ogc-features",
            asset_roles=["data"],
            datetime=datetime.now(timezone.utc).isoformat(),
            crs="EPSG:4326",
            detected_type="vector",
            dataset_id=params.get("dataset_id"),
            resource_id=params.get("resource_id"),
            version_id=params.get("version_id"),
            title=params.get("title"),
            job_id=_run_id,
            epoch=5,
        )

        # ── Add vector-specific properties ────────────────────────────────
        stac_item_json["properties"]["vector:geometry_type"] = geometry_type
        stac_item_json["properties"]["vector:row_count"] = row_count
        stac_item_json["properties"]["vector:tipg_collection"] = tipg_collection

        # ── Cache on Release (optional) ───────────────────────────────────
        stac_item_json_cached = False
        if release_id:
            try:
                from infrastructure.release_repository import ReleaseRepository

                release_repo = ReleaseRepository()
                release_repo.update_stac_item_json(release_id, stac_item_json)
                stac_item_json_cached = True
                logger.info(
                    "%s Cached stac_item_json on release %s",
                    log_prefix, release_id[:16],
                )
            except Exception as cache_err:
                # Non-fatal: item is still built, just not cached
                logger.warning(
                    "%s Failed to cache stac_item_json on release %s: %s",
                    log_prefix, release_id[:16], cache_err,
                )

        logger.info(
            "%s vector_build_stac_item: built item %s for collection %s "
            "(bbox=%s, geometry=%s, rows=%d, cached=%s)",
            log_prefix, stac_item_id, collection_id,
            bbox, geometry_type, row_count, stac_item_json_cached,
        )

        return {
            "success": True,
            "result": {
                "stac_item_id": stac_item_id,
                "collection_id": collection_id,
                "stac_item_json_cached": stac_item_json_cached,
            },
        }

    except Exception as exc:
        logger.error(
            "%s vector_build_stac_item failed: %s", log_prefix, exc, exc_info=True,
        )
        return {
            "success": False,
            "error": f"Failed to build STAC item: {exc}",
            "error_type": type(exc).__name__,
            "retryable": False,
        }
