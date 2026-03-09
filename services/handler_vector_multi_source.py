# ============================================================================
# CLAUDE CONTEXT - MULTI-SOURCE VECTOR ETL HANDLER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service layer - Multi-source vector collection ETL
# PURPOSE: Process N files or 1 GPKG with N layers into N PostGIS tables
# CREATED: 09 MAR 2026
# LAST_REVIEWED: 09 MAR 2026
# EXPORTS: vector_multi_source_complete
# DEPENDENCIES: geopandas, pyogrio, services.vector, infrastructure
# ============================================================================
"""
Multi-Source Vector ETL Handler.

Processes multi-source vector collections into PostGIS:
    P1 (multi-file): N files -> N PostGIS tables
    P3 (multi-layer): 1 GPKG with N layers -> N PostGIS tables

Each source produces one table named:
    {base_table_name}_{slugified_source_suffix}_ord{version_ordinal}

Reuses existing infrastructure:
    - PostGISHandler for upload (services/vector/postgis_handler.py)
    - Converters for file reading (services/vector/converters.py)
    - Core module for validation (services/vector/core.py)
    - ReleaseTableRepository for junction tracking
    - _refresh_tipg / _process_single_table from handler_vector_docker_complete

Exports:
    vector_multi_source_complete: Main handler function
"""

import os
import re
import time
import traceback
from pathlib import Path
from typing import Dict, Any, List, Optional

from config import get_config
from config.defaults import VectorDefaults
from util_logger import LoggerFactory, ComponentType

# Component-specific logger
logger = LoggerFactory.create_logger(
    ComponentType.SERVICE,
    "vector_multi_source"
)

# Docker mount base path for input files
DOCKER_INPUT_MOUNT = "/mnt/worker/input/"


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _slugify_for_postgres(name: str) -> str:
    """
    Sanitize a string for use as part of a PostgreSQL identifier.

    - Lowercase
    - Replace non-alphanumeric characters with underscore
    - Collapse multiple underscores
    - Strip leading/trailing underscores
    - Truncate to 40 chars max

    Args:
        name: Raw string (filename stem, layer name, etc.)

    Returns:
        Sanitized string safe for PostgreSQL identifier composition
    """
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9]', '_', slug)
    slug = re.sub(r'_+', '_', slug)
    slug = slug.strip('_')
    return slug[:40]


def _derive_source_suffix(source_identifier: str) -> str:
    """
    Derive table suffix from source file name or layer name.

    Strips file extension (if any) then slugifies.

    Args:
        source_identifier: Filename (e.g. "roads.gpkg") or layer name (e.g. "admin_boundaries")

    Returns:
        Slugified suffix suitable for table name composition
    """
    stem = Path(source_identifier).stem
    return _slugify_for_postgres(stem)


def _compute_table_name(base_prefix: str, source_suffix: str, version_ordinal: int) -> str:
    """
    Build full table name: {base}_{suffix}_ord{N}.

    Total length must be <= 63 chars (PostgreSQL identifier limit).
    If the combined name would exceed 63 chars, the base_prefix is truncated.

    Args:
        base_prefix: Base table name prefix (e.g. "dataset123_resource456")
        source_suffix: Slugified source suffix (e.g. "roads")
        version_ordinal: Version ordinal number

    Returns:
        Full table name (max 63 chars)
    """
    ordinal_part = f"_ord{version_ordinal}"
    # Reserve space for: _ + suffix + _ordN
    suffix_part = f"_{source_suffix}{ordinal_part}"
    max_base = 63 - len(suffix_part)

    if max_base < 1:
        raise ValueError(
            f"Source suffix '{source_suffix}' is too long to form a valid "
            f"PostgreSQL table name (suffix_part={len(suffix_part)} chars, limit 63)"
        )

    truncated_base = base_prefix[:max_base]
    return f"{truncated_base}{suffix_part}"


def _build_source_list(parameters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Determine mode and build the list of sources to process.

    Mode detection:
        - blob_list present and non-empty -> P1 multi-file mode
        - blob_name + layer_names -> P3 multi-layer GPKG mode
        - Otherwise -> error

    Args:
        parameters: Job parameters

    Returns:
        List of source dicts, each with:
            - source_identifier: display name (filename stem or layer name)
            - source_path: mount path to the file
            - layer_name: layer name for GPKG (None for non-GPKG)
            - file_extension: format extension for converter lookup
    """
    blob_list = parameters.get('blob_list')
    blob_name = parameters.get('blob_name')
    layer_names = parameters.get('layer_names')

    if blob_list:
        # P1: Multi-file mode — each blob is a separate source
        sources = []
        for blob_path in blob_list:
            p = Path(blob_path)
            mount_path = os.path.join(DOCKER_INPUT_MOUNT, blob_path)
            sources.append({
                'source_identifier': p.stem,
                'source_path': mount_path,
                'layer_name': None,
                'file_extension': p.suffix.lstrip('.').lower(),
            })
        return sources

    elif blob_name and layer_names:
        # P3: Multi-layer GPKG mode — one file, multiple layers
        mount_path = os.path.join(DOCKER_INPUT_MOUNT, blob_name)
        sources = []
        for layer in layer_names:
            sources.append({
                'source_identifier': layer,
                'source_path': mount_path,
                'layer_name': layer,
                'file_extension': 'gpkg',
            })
        return sources

    else:
        raise ValueError(
            "Multi-source handler requires either 'blob_list' (P1 multi-file) "
            "or 'blob_name' + 'layer_names' (P3 multi-layer GPKG). "
            "Neither was provided."
        )


# =============================================================================
# MAIN HANDLER
# =============================================================================

def vector_multi_source_complete(
    parameters: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Multi-source vector ETL handler.

    Processes N files or 1 GPKG with N layers into N PostGIS tables,
    each registered in release_tables with table_role='multi_source'.

    Args:
        parameters: Job parameters including:
            - job_id: Job identifier
            - table_name: Base table name prefix
            - version_ordinal: Ordinal version number
            - blob_list: (P1) List of blob paths for multi-file mode
            - blob_name: (P3) Single GPKG blob path
            - layer_names: (P3) List of layer names to extract
            - schema: Target schema (default: geo)
            - overwrite: Whether to overwrite existing tables
            - release_id: Release ID for junction table registration
            - chunk_size: Rows per batch (default: 100000)
        context: Optional task context

    Returns:
        Handler contract dict: {"success": True/False, ...}
    """
    start_time = time.time()
    config = get_config()

    # =========================================================================
    # Extract core parameters
    # =========================================================================
    job_id = parameters.get('job_id', 'unknown')
    base_table_name = parameters.get('base_table_name') or parameters.get('table_name')
    if not base_table_name:
        raise ValueError("base_table_name (or table_name) is required")
    version_ordinal = parameters.get('version_ordinal', 1)
    schema = parameters.get('schema', 'geo')
    overwrite = parameters.get('overwrite', False)
    chunk_size = parameters.get('chunk_size', 100000)
    release_id = parameters.get('release_id')

    logger.info(
        f"[{job_id[:8]}] Multi-source vector ETL starting: "
        f"base={base_table_name}, ord={version_ordinal}"
    )

    # Mark Release as PROCESSING
    if release_id:
        try:
            from infrastructure import ReleaseRepository
            from core.models.asset import ProcessingStatus
            from datetime import datetime, timezone
            release_repo = ReleaseRepository()
            release_repo.update_processing_status(
                release_id,
                status=ProcessingStatus.PROCESSING,
                started_at=datetime.now(timezone.utc)
            )
        except Exception as e:
            logger.warning(f"[{job_id[:8]}] Failed to set PROCESSING on release (non-fatal): {e}")

    # Checkpoints for progress tracking
    checkpoints = []
    checkpoint_data = {}

    def checkpoint(name: str, data: Dict[str, Any]):
        """Record a checkpoint."""
        checkpoints.append(name)
        checkpoint_data[name] = data
        logger.info(f"[{job_id[:8]}] Checkpoint: {name}")

    try:
        # =================================================================
        # PHASE 1: Build and validate source list
        # =================================================================
        sources = _build_source_list(parameters)
        source_count = len(sources)

        # Validate source count against limit
        max_sources = VectorDefaults.MAX_VECTOR_SOURCES
        if source_count > max_sources:
            raise ValueError(
                f"Source count ({source_count}) exceeds maximum "
                f"({max_sources}). Reduce the number of files or layers."
            )

        if source_count == 0:
            raise ValueError("No sources to process. blob_list or layer_names is empty.")

        mode = "multi_file" if parameters.get('blob_list') else "multi_layer_gpkg"
        logger.info(
            f"[{job_id[:8]}] Mode: {mode}, sources: {source_count}, "
            f"max: {max_sources}"
        )

        checkpoint("sources_resolved", {
            "mode": mode,
            "source_count": source_count,
            "sources": [s['source_identifier'] for s in sources],
        })

        # For GPKG multi-layer: validate layers exist in the file
        if mode == "multi_layer_gpkg":
            _validate_gpkg_layers(
                sources[0]['source_path'],
                [s['layer_name'] for s in sources],
                job_id
            )

        # =================================================================
        # PHASE 2: Process each source
        # =================================================================
        from services.vector.core import (
            load_vector_source,
            validate_and_prepare,
        )
        from services.vector.postgis_handler import VectorToPostGISHandler
        from services.handler_vector_docker_complete import (
            _process_single_table,
            _refresh_tipg,
        )

        table_results = []
        total_features = 0
        failed_sources = []

        for idx, source in enumerate(sources):
            source_id = source['source_identifier']
            source_suffix = _derive_source_suffix(source_id)
            current_table = _compute_table_name(
                base_table_name, source_suffix, version_ordinal
            )

            logger.info(
                f"[{job_id[:8]}] Processing source {idx + 1}/{source_count}: "
                f"{source_id} -> {schema}.{current_table}"
            )

            try:
                # ---------------------------------------------------------
                # Step A: Load source file/layer
                # ---------------------------------------------------------
                converter_params = {}
                if source['layer_name']:
                    converter_params['layer_name'] = source['layer_name']

                gdf, load_info = load_vector_source(
                    blob_name=parameters.get('blob_name', source_id),
                    container_name=parameters.get('container_name', config.storage.bronze.vectors),
                    file_extension=source['file_extension'],
                    converter_params=converter_params,
                    job_id=job_id,
                    mount_source_path=source['source_path'],
                )

                logger.info(
                    f"[{job_id[:8]}] Loaded {len(gdf):,} features from {source_id} "
                    f"(CRS: {load_info.get('original_crs', 'unknown')})"
                )

                # ---------------------------------------------------------
                # Step B: Validate and prepare geometry
                # ---------------------------------------------------------
                geometry_params = parameters.get('geometry_params', {})
                prepared_groups, validation_info, warnings = validate_and_prepare(
                    gdf=gdf,
                    geometry_params=geometry_params,
                    job_id=job_id,
                )

                # For multi-source, each source produces one table.
                # If geometry split occurs within a source, use primary group.
                if len(prepared_groups) > 1:
                    logger.warning(
                        f"[{job_id[:8]}] Source '{source_id}' has mixed geometry types "
                        f"({list(prepared_groups.keys())}). Using largest group."
                    )
                    # Pick the group with the most features
                    primary_suffix = max(prepared_groups, key=lambda k: len(prepared_groups[k]))
                    prepared_gdf = prepared_groups[primary_suffix]
                else:
                    primary_suffix = list(prepared_groups.keys())[0]
                    prepared_gdf = prepared_groups[primary_suffix]

                # ---------------------------------------------------------
                # Step C: Process into PostGIS table
                # ---------------------------------------------------------
                table_result = _process_single_table(
                    gdf=prepared_gdf,
                    table_name=current_table,
                    schema=schema,
                    overwrite=overwrite,
                    parameters=parameters,
                    load_info=load_info,
                    job_id=job_id,
                    chunk_size=chunk_size,
                    checkpoint_fn=checkpoint,
                )

                feature_count = table_result['total_rows']
                geometry_type = table_result['geometry_type']

                # ---------------------------------------------------------
                # Step D: Register in release_tables junction
                # ---------------------------------------------------------
                if release_id:
                    try:
                        from infrastructure import ReleaseTableRepository
                        release_table_repo = ReleaseTableRepository()
                        release_table_repo.create(
                            release_id=release_id,
                            table_name=current_table,
                            geometry_type=geometry_type,
                            feature_count=feature_count,
                            table_role='multi_source',
                            table_suffix=source_suffix,
                        )
                        logger.info(
                            f"[{job_id[:8]}] Registered {current_table} in release_tables "
                            f"(role=multi_source, suffix={source_suffix})"
                        )
                    except Exception as rt_err:
                        logger.warning(
                            f"[{job_id[:8]}] Failed to write release_tables for "
                            f"{current_table} (non-fatal): {rt_err}"
                        )

                # Track result
                crs_str = load_info.get('original_crs', 'EPSG:4326')
                table_results.append({
                    "table_name": current_table,
                    "source": source_id,
                    "feature_count": feature_count,
                    "geometry_type": geometry_type,
                    "crs": crs_str,
                })
                total_features += feature_count

                checkpoint(f"source_complete_{idx}", {
                    "source": source_id,
                    "table_name": current_table,
                    "feature_count": feature_count,
                    "geometry_type": geometry_type,
                })

            except Exception as source_err:
                logger.error(
                    f"[{job_id[:8]}] Failed to process source '{source_id}': "
                    f"{type(source_err).__name__}: {source_err}\n"
                    f"{traceback.format_exc()}"
                )
                failed_sources.append({
                    "source": source_id,
                    "error": str(source_err),
                    "error_type": type(source_err).__name__,
                })

        # =================================================================
        # PHASE 3: TiPG refresh (ONCE for all tables)
        # =================================================================
        if table_results:
            # Refresh TiPG once — it discovers all new collections
            first_table = table_results[0]['table_name']
            tipg_collection_id = f"{schema}.{first_table}"
            tipg_data = _refresh_tipg(tipg_collection_id, job_id)
            checkpoint("tipg_refresh", tipg_data)
        else:
            logger.warning(f"[{job_id[:8]}] No tables created, skipping TiPG refresh")

        # =================================================================
        # PHASE 4: Assemble result
        # =================================================================
        elapsed = time.time() - start_time

        # If ALL sources failed, return failure
        if not table_results:
            error_summary = "; ".join(
                f"{f['source']}: {f['error']}" for f in failed_sources
            )
            return {
                "success": False,
                "error": "ALL_SOURCES_FAILED",
                "error_type": "ValueError",
                "message": f"All {source_count} sources failed to process.",
                "detail": error_summary,
                "failed_sources": failed_sources,
                "elapsed_seconds": round(elapsed, 2),
            }

        checkpoint("complete", {
            "tables_created": len(table_results),
            "total_features": total_features,
            "failed_sources": len(failed_sources),
            "elapsed_seconds": round(elapsed, 2),
        })

        rows_per_sec = total_features / elapsed if elapsed > 0 else 0
        logger.info(
            f"[{job_id[:8]}] Multi-source vector ETL complete: "
            f"{total_features:,} features across {len(table_results)} table(s) "
            f"in {elapsed:.1f}s ({rows_per_sec:.0f} rows/sec)"
        )

        result = {
            "tables": table_results,
            "total_sources": source_count,
            "total_features": total_features,
            "tables_created": len(table_results),
            "failed_sources": failed_sources if failed_sources else None,
            "mode": mode,
            "schema": schema,
            "base_table_name": base_table_name,
            "version_ordinal": version_ordinal,
            "elapsed_seconds": round(elapsed, 2),
            "checkpoint_count": len(checkpoints),
        }

        return {"success": True, "result": result}

    except Exception as e:
        elapsed = time.time() - start_time
        raw_detail = str(e)
        error_msg = f"Multi-source vector ETL failed: {type(e).__name__}: {e}"
        logger.error(f"[{job_id[:8]}] {error_msg}\n{traceback.format_exc()}")

        return {
            "success": False,
            "error": "MULTI_SOURCE_ETL_FAILED",
            "error_type": type(e).__name__,
            "message": error_msg,
            "detail": raw_detail,
            "last_checkpoint": checkpoints[-1] if checkpoints else None,
            "checkpoint_data": checkpoint_data,
            "elapsed_seconds": round(elapsed, 2),
        }


# =============================================================================
# GPKG LAYER VALIDATION
# =============================================================================

def _validate_gpkg_layers(
    gpkg_path: str, requested_layers: List[str], job_id: str
) -> None:
    """
    Validate that all requested layers exist in the GPKG file and are spatial.

    Args:
        gpkg_path: Path to the GeoPackage file on mount
        requested_layers: List of layer names the user wants to extract
        job_id: Job ID for logging

    Raises:
        FileNotFoundError: If the GPKG file does not exist on the mount
        ValueError: If any requested layer does not exist or is non-spatial
    """
    import pyogrio

    if not os.path.exists(gpkg_path):
        raise FileNotFoundError(
            f"GeoPackage file not found at mount path: {gpkg_path}. "
            f"Ensure the file is available in the Docker input mount."
        )

    available = pyogrio.list_layers(gpkg_path)
    available_names = [name for name, _ in available]
    spatial_map = {name: gtype for name, gtype in available}

    logger.info(
        f"[{job_id[:8]}] GPKG layers available: {available_names} "
        f"(requested: {requested_layers})"
    )

    for layer in requested_layers:
        if layer not in available_names:
            raise ValueError(
                f"Layer '{layer}' not found in GeoPackage. "
                f"Available layers: {available_names}"
            )
        if spatial_map.get(layer) is None:
            spatial_only = [n for n, g in available if g is not None]
            raise ValueError(
                f"Layer '{layer}' is non-spatial (attributes-only table). "
                f"Cannot upload to PostGIS. Spatial layers: {spatial_only}"
            )
