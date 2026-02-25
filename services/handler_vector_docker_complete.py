# ============================================================================
# VECTOR DOCKER COMPLETE HANDLER
# ============================================================================
# STATUS: Service layer - V0.8 Docker-based consolidated vector ETL
# PURPOSE: Single-handler vector ETL with checkpoint progress tracking
# CREATED: 24 JAN 2026
# REFACTORED: 26 JAN 2026 - Use shared core.py, fix bugs
# UPDATED: 06 FEB 2026 - Phase 5 BUG_REFORM: Enhanced error responses
# LAST_REVIEWED: 06 FEB 2026
# EXPORTS: vector_docker_complete
# DEPENDENCIES: geopandas, services.vector.core, infrastructure.blob
# ============================================================================
"""
Vector Docker Complete Handler.

V0.8 consolidated vector ETL handler that replaces the 3-stage Function App
workflow with a single checkpoint-based handler. Eliminates pickle serialization
overhead and uses persistent connection pooling.

Refactored 26 JAN 2026 to use shared core.py module, eliminating DRY violations
with process_vector_tasks.py.

Checkpoint Phases:
    validated      - Source file validated, GeoDataFrame loaded
    table_created  - PostGIS table and metadata created
    style_created  - Default OGC style registered
    chunk_N        - Chunk N uploaded (N = 0, 1, 2...)
    complete       - Final result

Benefits:
    - No pickle serialization (direct memory -> DB)
    - Connection pool reuse across all chunks
    - No timeout (Docker long-running process)
    - Large file support via mounted storage
    - Fine-grained checkpoint progress
    - No file size limit (Docker has more memory + mount)

Exports:
    vector_docker_complete: Main handler function
"""

from typing import Dict, Any, Optional, List
import time
import logging
import traceback

from config import get_config
from util_logger import LoggerFactory, ComponentType, log_memory_checkpoint

# Component-specific logger
logger = LoggerFactory.create_logger(
    ComponentType.SERVICE,
    "vector_docker_complete"
)


def vector_docker_complete(parameters: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """
    Consolidated vector ETL with checkpoint-based progress tracking.

    Replaces the 3-stage Function App workflow:
        Stage 1 (prepare) + Stage 2 (upload) + Stage 3 (stac)
    with a single handler that:
        - Eliminates pickle serialization
        - Uses connection pool for all DB operations
        - Tracks progress via checkpoints (resumable)

    Args:
        parameters: Job parameters including:
            - job_id: Job identifier
            - blob_name: Source file path
            - container_name: Source container
            - file_extension: File format
            - table_name: Target PostGIS table
            - schema: Target schema (default: geo)
            - chunk_size: Rows per batch (default: 100000 for Docker)
            - ... (see job definition for full list)
        context: Optional task context with checkpoint support

    Returns:
        {
            'success': True/False,
            'result': {
                'table_name': str,
                'total_rows': int,
                'chunks_uploaded': int,
                'stac_item_id': str,
                ...
            }
        }
    """
    start_time = time.time()
    config = get_config()

    # Extract core parameters
    job_id = parameters.get('job_id', 'unknown')
    blob_name = parameters['blob_name']
    container_name = parameters.get('container_name') or config.storage.bronze.vectors
    file_extension = parameters['file_extension'].lower().lstrip('.')
    table_name = parameters['table_name']
    schema = parameters.get('schema', 'geo')
    # PERF FIX (26 JAN 2026): Increased from 20K to 100K for Docker
    # Docker has more memory than Function Apps, larger chunks = fewer round-trips
    chunk_size = parameters.get('chunk_size', 100000)
    overwrite = parameters.get('overwrite', False)

    logger.info(f"[{job_id[:8]}] Docker Vector ETL starting: {blob_name} -> {schema}.{table_name}")

    # V0.9: Mark Release as PROCESSING (handler entry)
    _release_id = parameters.get('release_id')
    if _release_id:
        try:
            from infrastructure import ReleaseRepository
            from core.models.asset import ProcessingStatus
            from datetime import datetime, timezone
            release_repo = ReleaseRepository()
            release_repo.update_processing_status(
                _release_id,
                status=ProcessingStatus.PROCESSING,
                started_at=datetime.now(timezone.utc)
            )
        except Exception as e:
            logger.warning(f"Failed to set PROCESSING on release (non-fatal): {e}")

    # =========================================================================
    # V0.8.16: Asset linking moved to CoreMachine factory (09 FEB 2026)
    # =========================================================================
    # Asset linking (current_job_id, content_hash) is now handled by the
    # CoreMachine factory on job completion using job.asset_id.
    # Tasks don't need asset awareness - they just execute work.
    # See: core/machine_factory.py lines 221-264
    # =========================================================================

    # Track checkpoints for resume capability
    checkpoints = []
    checkpoint_data = {}
    data_warnings = []
    validation_events = []  # Fine-grained validation events for swimlane

    def checkpoint(name: str, data: Dict[str, Any]):
        """Record a checkpoint for progress tracking."""
        checkpoints.append(name)
        checkpoint_data[name] = data
        logger.info(f"[{job_id[:8]}] Checkpoint: {name}")

    def emit_validation_event(event_name: str, details: Dict[str, Any]):
        """
        Record a fine-grained validation event for the swimlane UI.

        These events are collected and emitted to the job event system
        to show detailed progress in the events timeline.
        """
        validation_events.append({
            "event_name": event_name,
            "details": details,
            "timestamp": time.time()
        })
        logger.info(f"[{job_id[:8]}] Validation: {event_name} - {details}")

    try:
        # =====================================================================
        # PHASE 1: Load and Validate Source File
        # =====================================================================
        logger.info(f"[{job_id[:8]}] Phase 1: Loading and validating source file")

        gdf, load_info, validation_info, warnings = _load_and_validate_source(
            blob_name=blob_name,
            container_name=container_name,
            file_extension=file_extension,
            parameters=parameters,
            job_id=job_id,
            event_callback=emit_validation_event
        )
        data_warnings.extend(warnings)

        checkpoint("validated", {
            "features": len(gdf),
            "crs": load_info['original_crs'],
            "geometry_type": validation_info.get('geometry_type'),
            "columns": load_info['columns'],
            "file_size_mb": load_info['file_size_mb']
        })

        # Record validation events to job_events table for swimlane UI
        _record_validation_events(job_id, validation_events)

        # =====================================================================
        # PHASE 2: Create PostGIS Table and Metadata
        # =====================================================================
        logger.info(f"[{job_id[:8]}] Phase 2: Creating PostGIS table")

        table_result = _create_table_and_metadata(
            gdf=gdf,
            table_name=table_name,
            schema=schema,
            overwrite=overwrite,
            parameters=parameters,
            load_info=load_info,
            job_id=job_id
        )

        checkpoint("table_created", {
            "table": f"{schema}.{table_name}",
            "geometry_type": table_result['geometry_type'],
            "srid": table_result['srid']
        })

        # =====================================================================
        # PHASE 2.5: Create Default Style
        # =====================================================================
        logger.info(f"[{job_id[:8]}] Phase 2.5: Creating default style")

        style_result = _create_default_style(
            table_name=table_name,
            geometry_type=table_result['geometry_type'],
            style_params=parameters.get('style'),
            job_id=job_id
        )

        checkpoint("style_created", style_result)

        # =====================================================================
        # PHASE 3: Upload Chunks (with per-chunk checkpoints)
        # =====================================================================
        logger.info(f"[{job_id[:8]}] Phase 3: Uploading data in chunks")

        upload_result = _upload_chunks_with_checkpoints(
            gdf=gdf,
            table_name=table_name,
            schema=schema,
            chunk_size=chunk_size,
            job_id=job_id,
            checkpoint_fn=checkpoint
        )

        # =====================================================================
        # PHASE 3.5: Deferred Indexes + ANALYZE
        # =====================================================================
        # Build indexes after all data is loaded (faster than pre-insert).
        # Then run ANALYZE so the query planner has statistics immediately.
        # =====================================================================
        logger.info(f"[{job_id[:8]}] Phase 3.5: Creating deferred indexes")
        from services.vector.postgis_handler import VectorToPostGISHandler
        _post_handler = VectorToPostGISHandler()

        indexes = parameters.get('indexes', {'spatial': True, 'attributes': [], 'temporal': []})
        _post_handler.create_deferred_indexes(
            table_name=table_name,
            schema=schema,
            gdf=gdf,
            indexes=indexes
        )
        checkpoint("indexes_created", {"table": f"{schema}.{table_name}"})

        logger.info(f"[{job_id[:8]}] Phase 3.5: Running ANALYZE for query planner")
        _post_handler.analyze_table(table_name, schema)
        checkpoint("table_analyzed", {"table": f"{schema}.{table_name}"})

        # =====================================================================
        # PHASE 4: Refresh TiPG Collection Catalog (05 FEB 2026 - F1.6)
        # =====================================================================
        # Notify the Service Layer to re-scan PostGIS so TiPG immediately
        # discovers the new collection without waiting for cache TTL or restart.
        # Non-fatal: if the webhook fails, TiPG will eventually pick it up.
        # =====================================================================
        tipg_collection_id = f"{schema}.{table_name}"
        tipg_refresh_data = {
            "collection_id": tipg_collection_id,
            "status": "pending"
        }

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
                logger.info(
                    f"[{job_id[:8]}] TiPG catalog refreshed for {tipg_collection_id}: "
                    f"{refresh_result.collections_before} -> {refresh_result.collections_after} "
                    f"(new: {refresh_result.new_collections})"
                )
            else:
                tipg_refresh_data = {
                    "collection_id": tipg_collection_id,
                    "status": "error",
                    "error": refresh_result.error
                }
                logger.warning(
                    f"[{job_id[:8]}] TiPG refresh for {tipg_collection_id} returned error: {refresh_result.error}"
                )
        except Exception as e:
            tipg_refresh_data = {
                "collection_id": tipg_collection_id,
                "status": "failed",
                "error": str(e)
            }
            logger.warning(f"[{job_id[:8]}] TiPG catalog refresh for {tipg_collection_id} failed (non-fatal): {e}")

        # G3: Probe TiPG to verify collection is actually servable (non-fatal)
        try:
            probe = sl_client.probe_collection(tipg_collection_id)
            tipg_refresh_data['probe'] = probe

            if probe['number_matched'] == 0:
                logger.warning(
                    f"[{job_id[:8]}] TiPG probe: {tipg_collection_id} has 0 features "
                    f"(expected {upload_result.get('total_rows', '?')}). Data may not be servable."
                )
            else:
                logger.info(
                    f"[{job_id[:8]}] TiPG probe: {tipg_collection_id} confirmed "
                    f"{probe['number_matched']} features servable"
                )
        except Exception as probe_err:
            tipg_refresh_data['probe'] = {'status': 'failed', 'error': str(probe_err)}
            logger.warning(f"[{job_id[:8]}] TiPG probe failed (non-fatal): {probe_err}")

        checkpoint("tipg_refresh", tipg_refresh_data)

        # =====================================================================
        # POST-UPLOAD VALIDATION (24 FEB 2026 - False Success Prevention)
        # =====================================================================
        total_rows = upload_result.get('total_rows', 0)

        # G2: Hard gate — fail the job if 0 rows inserted
        if total_rows == 0:
            raise ValueError(
                f"Vector ETL completed all phases but inserted 0 rows into "
                f"{schema}.{table_name}. Table exists but is empty. "
                f"Source had {len(gdf)} features after validation — "
                f"data was lost during chunk upload."
            )

        # G1: Cross-check actual table row count against chunk sum
        try:
            from psycopg import sql as psql
            from services.vector.postgis_handler import VectorToPostGISHandler
            _handler = VectorToPostGISHandler()
            with _handler._pg_repo._get_connection() as conn:
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
                    f"[{job_id[:8]}] Row count discrepancy: "
                    f"chunk sum={total_rows}, table COUNT(*)={db_total}"
                )
                total_rows = db_total  # Use DB truth
        except Exception as count_err:
            logger.warning(f"[{job_id[:8]}] Could not verify table row count: {count_err}")

        # Update metadata feature_count with actual DB count (registered in Phase 2 with len(gdf))
        if total_rows != len(gdf):
            try:
                from services.vector.postgis_handler import VectorToPostGISHandler
                _meta_handler = VectorToPostGISHandler()
                with _meta_handler._pg_repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            psql.SQL(
                                "UPDATE {schema}.table_catalog SET feature_count = %s "
                                "WHERE table_name = %s AND schema_name = %s"
                            ).format(schema=psql.Identifier("geo")),
                            (total_rows, table_name, schema)
                        )
                        conn.commit()
                logger.info(f"[{job_id[:8]}] Updated metadata feature_count: {len(gdf)} -> {total_rows}")
            except Exception as meta_err:
                logger.warning(f"[{job_id[:8]}] Could not update metadata feature_count: {meta_err}")

        # =====================================================================
        # COMPLETE
        # =====================================================================
        elapsed = time.time() - start_time

        checkpoint("complete", {
            "total_rows": total_rows,
            "elapsed_seconds": round(elapsed, 2)
        })

        rows_per_sec = total_rows / elapsed if elapsed > 0 else 0
        logger.info(
            f"[{job_id[:8]}] Docker Vector ETL complete: "
            f"{total_rows:,} rows in {elapsed:.1f}s ({rows_per_sec:.0f} rows/sec)"
        )

        # V0.9: Update release processing status to COMPLETED
        if parameters.get('release_id'):
            try:
                from infrastructure import ReleaseRepository
                from core.models.asset import ProcessingStatus
                release_repo = ReleaseRepository()
                release_repo.update_processing_status(parameters['release_id'], status=ProcessingStatus.COMPLETED)
                logger.info(f"[{job_id[:8]}] Updated release {parameters['release_id'][:16]}... processing_status=completed")
            except Exception as release_err:
                logger.warning(f"[{job_id[:8]}] Failed to update release processing status: {release_err}")

        return {
            "success": True,
            "result": {
                "table_name": table_name,
                "schema": schema,
                "total_rows": total_rows,
                "geometry_type": table_result['geometry_type'],
                "srid": table_result.get('srid', 4326),
                "style_id": style_result.get('style_id', 'default'),
                "chunks_uploaded": upload_result.get('chunks_uploaded', 0),
                "checkpoint_count": len(checkpoints),
                "elapsed_seconds": round(elapsed, 2),
                "execution_mode": "docker",
                "connection_pooling": True,
                "data_warnings": data_warnings if data_warnings else None,
                "vector_tile_urls": table_result.get('vector_tile_urls')
            }
        }

    except Exception as e:
        elapsed = time.time() - start_time
        # Extract the raw diagnostic (the ValueError message itself)
        raw_detail = str(e)
        error_msg = f"Vector Docker ETL failed: {type(e).__name__}: {e}"
        logger.error(f"[{job_id[:8]}] {error_msg}\n{traceback.format_exc()}")

        # Phase 5 BUG_REFORM: Enhanced error response with ErrorResponse model
        from core.errors import ErrorCode, create_error_response_v2, get_error_category

        # Map exception type to appropriate ErrorCode
        error_code = _map_exception_to_error_code(e)

        # V0.9: Update Release to FAILED (defense-in-depth alongside callback)
        if parameters.get('release_id'):
            try:
                from infrastructure import ReleaseRepository
                from core.models.asset import ProcessingStatus
                release_repo = ReleaseRepository()
                release_repo.update_processing_status(
                    parameters['release_id'],
                    status=ProcessingStatus.FAILED,
                    error=str(e)[:500]
                )
            except Exception:
                pass  # Callback will handle

        # Create enhanced error response
        response, debug = create_error_response_v2(
            error_code=error_code,
            message=error_msg,
            remediation=_get_vector_remediation(error_code, e),
            exception=e,
            job_id=job_id,
            handler="vector_docker_complete",
            context={
                "blob_name": blob_name,
                "container_name": container_name,
                "table_name": table_name,
                "last_checkpoint": checkpoints[-1] if checkpoints else None,
            }
        )

        return {
            "success": False,
            "error": response.error_code,
            "error_code": response.error_code,
            "error_category": response.error_category,
            "error_scope": response.error_scope,
            "message": response.message,
            "detail": raw_detail,  # Raw diagnostic from ValueError
            "remediation": response.remediation,
            "user_fixable": response.user_fixable,
            "retryable": response.retryable,
            "http_status": response.http_status,
            "error_id": response.error_id,
            "error_type": type(e).__name__,
            "last_checkpoint": checkpoints[-1] if checkpoints else None,
            "checkpoint_data": checkpoint_data,
            "elapsed_seconds": round(elapsed, 2),
            "_debug": debug.model_dump(),  # Store for job record
        }


# =============================================================================
# PHASE IMPLEMENTATIONS
# =============================================================================

def _load_and_validate_source(
    blob_name: str,
    container_name: str,
    file_extension: str,
    parameters: Dict[str, Any],
    job_id: str,
    event_callback: Optional[callable] = None
) -> tuple:
    """
    Load source file and validate geometry using shared core module.

    Args:
        blob_name: Source file path in container
        container_name: Blob container name
        file_extension: File format
        parameters: Job parameters
        job_id: Job ID for logging
        event_callback: Optional callback for fine-grained validation events

    Returns:
        Tuple of (GeoDataFrame, load_info, validation_info, warnings)
    """
    from services.vector.core import (
        load_vector_source,
        build_csv_converter_params,
        validate_and_prepare,
        apply_column_mapping,
        extract_geometry_info,
        log_gdf_memory
    )

    # Helper to emit events
    def emit(event_name: str, details: Dict[str, Any]):
        if event_callback:
            event_callback(event_name, details)

    # Build converter params (handles CSV lat/lon/wkt merging)
    converter_params = parameters.get('converter_params', {}) or {}
    if file_extension == 'csv':
        converter_params = build_csv_converter_params(parameters, converter_params)
    # GPKG layer selection (24 FEB 2026)
    if file_extension == 'gpkg' and parameters.get('layer_name'):
        converter_params['layer_name'] = parameters['layer_name']

    # GPKG layer validation (24 FEB 2026)
    if file_extension == 'gpkg':
        import pyogrio
        from infrastructure.blob import BlobRepository
        blob_repo = BlobRepository.for_zone("bronze")
        blob_url = blob_repo.get_blob_url_with_sas(container_name, blob_name)
        available_layers = pyogrio.list_layers(blob_url)
        layer_names = [name for name, _ in available_layers]
        spatial_layers = [(name, gtype) for name, gtype in available_layers if gtype is not None]

        requested_layer = converter_params.get('layer_name')
        if requested_layer and requested_layer not in layer_names:
            raise ValueError(
                f"Layer '{requested_layer}' not found in GeoPackage '{blob_name}'. "
                f"Available layers: {layer_names}"
            )

        # Fix A: Reject non-spatial (attributes-only) layers (24 FEB 2026)
        # GeoPackage data_type='attributes' layers have no geometry column.
        # Examples: layer_styles, qgis_projects metadata tables.
        selected_layer = requested_layer or layer_names[0]
        layer_geom_types = {name: gtype for name, gtype in available_layers}
        if layer_geom_types.get(selected_layer) is None:
            spatial_names = [name for name, _ in spatial_layers]
            raise ValueError(
                f"Layer '{selected_layer}' is a non-spatial (attributes-only) table, "
                f"not a geospatial layer. Cannot upload to PostGIS. "
                f"Spatial layers in this file: {spatial_names}"
            )

    # Emit file download start event
    emit("file_download_start", {
        "blob_name": blob_name,
        "container": container_name,
        "format": file_extension
    })

    # Load file using shared core function
    gdf, load_info = load_vector_source(
        blob_name=blob_name,
        container_name=container_name,
        file_extension=file_extension,
        converter_params=converter_params,
        job_id=job_id
    )

    # Emit file loaded event
    emit("file_loaded", {
        "features": len(gdf),
        "file_size_mb": load_info['file_size_mb'],
        "original_crs": load_info['original_crs'],
        "columns": len(load_info['columns'])
    })

    # Fix B: Detect QGIS metadata layers (24 FEB 2026)
    # QGIS dashboard/chart layers have valid geometry but contain project
    # metadata (expressions, style defs), not real geospatial attribute data.
    # Detect by checking for signature QGIS column names.
    QGIS_SIGNATURE_COLUMNS = frozenset({
        'geometry_generator',   # Virtual geometry expression
        'label_expression',     # Label rendering expression
        'stylename',            # layer_styles table
        'styleqml',             # QML style definition
        'stylesld',             # SLD style definition
        'useasdefault',         # layer_styles boolean
        'f_table_catalog',      # layer_styles reference
        'f_geometry_column',    # layer_styles reference
    })
    if file_extension == 'gpkg':
        gdf_cols_lower = {c.lower() for c in gdf.columns if c != 'geometry'}
        qgis_overlap = gdf_cols_lower & QGIS_SIGNATURE_COLUMNS
        if len(qgis_overlap) >= 2:
            # Reuse spatial_layers from GPKG validation block above (line ~552)
            spatial_hint = ""
            try:
                spatial_names = [n for n, g in spatial_layers if g is not None
                                 and n.lower() not in ('dashboard', 'chart', 'layer_styles')]
                if spatial_names:
                    spatial_hint = f" Data layers in this file: {spatial_names}"
            except Exception:
                pass
            raise ValueError(
                f"Layer appears to be QGIS project metadata, not geospatial data. "
                f"Detected QGIS columns: {sorted(qgis_overlap)}. "
                f"Dashboard/chart/style layers contain rendering definitions, "
                f"not uploadable features.{spatial_hint}"
            )

    # Apply column mapping if provided
    column_mapping = parameters.get('column_mapping')
    if column_mapping:
        gdf = apply_column_mapping(gdf, column_mapping, job_id)
        emit("column_mapping_applied", {
            "mappings": len(column_mapping),
            "columns_renamed": list(column_mapping.keys())
        })

    # Validate and prepare using shared core function
    # Pass event_callback for fine-grained validation events
    geometry_params = parameters.get('geometry_params', {})
    validated_gdf, validation_info, warnings = validate_and_prepare(
        gdf=gdf,
        geometry_params=geometry_params,
        job_id=job_id,
        event_callback=event_callback
    )

    # Extract geometry info
    geom_info = extract_geometry_info(validated_gdf)
    validation_info['geometry_type'] = geom_info['geometry_type']

    log_gdf_memory(validated_gdf, "after_validation", job_id)

    # Emit validation complete event
    emit("validation_complete", {
        "original_features": validation_info['original_count'],
        "validated_features": validation_info['validated_count'],
        "filtered_features": validation_info['filtered_count'],
        "geometry_type": geom_info['geometry_type']
    })

    return validated_gdf, load_info, validation_info, warnings


def _create_table_and_metadata(
    gdf,
    table_name: str,
    schema: str,
    overwrite: bool,
    parameters: Dict[str, Any],
    load_info: Dict[str, Any],
    job_id: str
) -> Dict[str, Any]:
    """
    Create PostGIS table and register metadata.

    Returns:
        Dict with table creation result
    """
    from services.vector.postgis_handler import VectorToPostGISHandler
    from services.vector.core import (
        extract_geometry_info,
        detect_temporal_extent,
        filter_reserved_columns
    )

    config = get_config()
    handler = VectorToPostGISHandler()

    # Get geometry info
    geom_info = extract_geometry_info(gdf)
    geometry_type = geom_info['geometry_type']

    # Detect temporal extent
    temporal_property = parameters.get('temporal_property')
    temporal_start, temporal_end = detect_temporal_extent(gdf, temporal_property, job_id)

    # Filter reserved columns
    all_columns = [c for c in gdf.columns if c != 'geometry']
    columns, skipped_columns = filter_reserved_columns(all_columns, job_id)

    # Create table with batch tracking (idempotent)
    indexes = parameters.get('indexes', {'spatial': True, 'attributes': [], 'temporal': []})

    handler.create_table_with_batch_tracking(
        table_name=table_name,
        schema=schema,
        gdf=gdf,
        indexes=indexes,
        overwrite=overwrite
    )

    # Generate vector tile URLs
    vector_tile_urls = config.generate_vector_tile_urls(table_name, schema)

    # Register metadata
    custom_props = {
        "vector_tiles": {
            "tilejson_url": vector_tile_urls.get("tilejson"),
            "tiles_url": vector_tile_urls.get("tiles"),
            "viewer_url": vector_tile_urls.get("viewer"),
            "tipg_map_url": vector_tile_urls.get("tipg_map")
        },
        "tipg_collection_id": f"{schema}.{table_name}"
    }

    handler.register_table_metadata(
        table_name=table_name,
        schema=schema,
        etl_job_id=job_id,
        source_file=parameters.get('blob_name'),
        source_format=parameters.get('file_extension'),
        source_crs=load_info.get('original_crs'),
        feature_count=len(gdf),
        geometry_type=geometry_type,
        bbox=tuple(gdf.total_bounds),
        title=parameters.get('title'),
        description=parameters.get('description'),
        attribution=parameters.get('attribution'),
        license=parameters.get('license'),
        keywords=parameters.get('keywords'),
        temporal_start=temporal_start,
        temporal_end=temporal_end,
        temporal_property=temporal_property,
        custom_properties=custom_props
    )

    logger.info(f"[{job_id[:8]}] Created table {schema}.{table_name} ({geometry_type}, SRID=4326)")

    return {
        'table_name': table_name,
        'schema': schema,
        'geometry_type': geometry_type,
        'srid': 4326,
        'vector_tile_urls': vector_tile_urls
    }


def _create_default_style(
    table_name: str,
    geometry_type: str,
    style_params: Optional[Dict[str, Any]],
    job_id: str
) -> Dict[str, Any]:
    """
    Create default OGC style for the table.

    Returns:
        Dict with style creation result
    """
    try:
        from ogc_styles.repository import OGCStylesRepository

        styles_repo = OGCStylesRepository()

        if style_params:
            fill_color = style_params.get('fill_color', '#3388ff')
            stroke_color = style_params.get('stroke_color', '#2266cc')
            logger.info(f"[{job_id[:8]}] Creating style with custom params: fill={fill_color}, stroke={stroke_color}")
        else:
            fill_color = '#3388ff'
            stroke_color = '#2266cc'

        styles_repo.create_default_style_for_collection(
            collection_id=table_name,
            geometry_type=geometry_type,
            fill_color=fill_color,
            stroke_color=stroke_color
        )

        return {
            'style_id': 'default',
            'auto_generated': style_params is None,
            'fill_color': fill_color,
            'stroke_color': stroke_color
        }

    except Exception as e:
        # Style creation is non-fatal
        logger.warning(f"[{job_id[:8]}] Style creation failed (non-fatal): {e}")
        return {
            'style_id': None,
            'error': str(e),
            'auto_generated': False
        }


def _upload_chunks_with_checkpoints(
    gdf,
    table_name: str,
    schema: str,
    chunk_size: int,
    job_id: str,
    checkpoint_fn
) -> Dict[str, Any]:
    """
    Upload data in chunks with per-chunk checkpoints.

    Uses DELETE+INSERT idempotency pattern without pickle serialization.

    Returns:
        Dict with upload statistics
    """
    import time
    from services.vector.postgis_handler import VectorToPostGISHandler

    handler = VectorToPostGISHandler()

    total_features = len(gdf)
    num_chunks = (total_features + chunk_size - 1) // chunk_size

    logger.info(f"[{job_id[:8]}] Uploading {total_features:,} features in {num_chunks} chunks")

    total_rows_inserted = 0
    total_rows_deleted = 0
    chunk_times = []

    for i in range(num_chunks):
        chunk_start_idx = i * chunk_size
        chunk_end_idx = min((i + 1) * chunk_size, total_features)
        chunk = gdf.iloc[chunk_start_idx:chunk_end_idx].copy()

        # Deterministic batch_id for idempotency
        batch_id = f"{job_id[:8]}-chunk-{i}"

        chunk_start_time = time.time()

        # DELETE + INSERT in single transaction
        result = handler.insert_chunk_idempotent(
            chunk=chunk,
            table_name=table_name,
            schema=schema,
            batch_id=batch_id
        )

        chunk_elapsed = time.time() - chunk_start_time
        chunk_times.append(chunk_elapsed)

        rows_inserted = result.get('rows_inserted', len(chunk))
        rows_deleted = result.get('rows_deleted', 0)

        total_rows_inserted += rows_inserted
        total_rows_deleted += rows_deleted

        # Checkpoint for this chunk
        progress_pct = int((i + 1) / num_chunks * 100)
        checkpoint_fn(f"chunk_{i}", {
            "chunk": i,
            "rows": rows_inserted,
            "rows_deleted": rows_deleted,
            "total_rows": total_rows_inserted,
            "progress_pct": progress_pct,
            "elapsed_seconds": round(chunk_elapsed, 2)
        })

        # Log progress at milestones
        if progress_pct in [25, 50, 75, 100] or i == num_chunks - 1:
            total_time = sum(chunk_times)
            rows_per_sec = total_rows_inserted / total_time if total_time > 0 else 0
            logger.info(
                f"[{job_id[:8]}] Progress: {progress_pct}% "
                f"({total_rows_inserted:,} rows, {rows_per_sec:.0f} rows/sec)"
            )

    logger.info(
        f"[{job_id[:8]}] Upload complete: {total_rows_inserted:,} rows inserted, "
        f"{total_rows_deleted:,} rows deleted (idempotent reruns)"
    )

    return {
        'total_rows': total_rows_inserted,
        'total_deleted': total_rows_deleted,
        'chunks_uploaded': num_chunks,
        'avg_chunk_time': round(sum(chunk_times) / len(chunk_times), 2) if chunk_times else 0,
        'idempotent_reruns_detected': total_rows_deleted > 0
    }


def _record_validation_events(job_id: str, validation_events: List[Dict[str, Any]]):
    """
    Record fine-grained validation events to job_events table.

    These events populate the swimlane UI with detailed validation steps
    like null geometry removal, CRS reprojection, geometry fixing, etc.

    Args:
        job_id: Job ID to associate events with
        validation_events: List of event dicts from emit_validation_event callback
    """
    if not validation_events:
        return

    try:
        from infrastructure import JobEventRepository
        from core.models.job_event import JobEventType, JobEventStatus

        event_repo = JobEventRepository()

        for event in validation_events:
            event_name = event.get('event_name', 'unknown')
            details = event.get('details', {})

            # Map validation event names to user-friendly checkpoint names
            checkpoint_name = _get_checkpoint_label(event_name, details)

            # Store event_name in event_data for swimlane matching
            event_data_with_name = {**details, '_event_name': event_name}

            event_repo.record_job_event(
                job_id=job_id,
                event_type=JobEventType.CHECKPOINT,
                event_status=JobEventStatus.SUCCESS,
                stage=1,  # All validation happens in stage 1
                checkpoint_name=checkpoint_name,
                event_data=event_data_with_name
            )

        logger.info(f"[{job_id[:8]}] Recorded {len(validation_events)} validation events")

    except Exception as e:
        # Non-fatal - don't fail the job if event recording fails
        logger.warning(f"[{job_id[:8]}] Failed to record validation events: {e}")


def _get_checkpoint_label(event_name: str, details: Dict[str, Any]) -> str:
    """
    Generate user-friendly checkpoint label for swimlane UI.

    Args:
        event_name: Internal event name (e.g., 'null_geometry_removal')
        details: Event details dict

    Returns:
        Human-readable label for the checkpoint
    """
    # Map event names to descriptive labels with dynamic details
    label_map = {
        'file_download_start': lambda d: f"Download {d.get('blob_name', 'file').split('/')[-1]}",
        'file_loaded': lambda d: f"Loaded {d.get('features', 0):,} features ({d.get('file_size_mb', 0)}MB)",
        'column_mapping_applied': lambda d: f"Rename {d.get('mappings', 0)} columns",
        'null_geometry_removal': lambda d: f"Remove {d.get('removed', 0)} null geometries",
        'null_geometry_check': lambda d: "Check null geometries",
        'invalid_geometry_fix': lambda d: f"Fix {d.get('fixed', 0)} invalid geometries",
        'force_2d': lambda d: f"Force 2D ({', '.join(d.get('dimensions_removed', []))})",
        'antimeridian_fix': lambda d: f"Fix {d.get('fixed', 0)} antimeridian crossings",
        'geometry_normalization': lambda d: f"Normalize to Multi-types",
        'winding_order_fix': lambda d: "Fix polygon winding order",
        'postgis_type_validation': lambda d: f"Validate {', '.join(d.get('geometry_types', []))}",
        'datetime_validation': lambda d: f"Sanitize {d.get('warnings', 0)} datetime values",
        'crs_reprojection': lambda d: f"Reproject {d.get('from_crs', '?')} → 4326",
        'crs_assignment': lambda d: "Assign CRS EPSG:4326",
        'crs_verified': lambda d: "Verify CRS EPSG:4326",
        'geometry_simplification': lambda d: f"Simplify ({d.get('reduction_percent', 0)}% reduction)",
        'geometry_quantization': lambda d: f"Quantize (grid={d.get('grid_size', 0)})",
        'validation_complete': lambda d: f"Validated {d.get('validated_features', 0):,} features",
    }

    # Get the label generator function
    label_fn = label_map.get(event_name)
    if label_fn:
        try:
            return label_fn(details)
        except (KeyError, TypeError, ValueError) as e:
            logger.debug(f"Label formatting failed for event '{event_name}': {e}")

    # Fallback: Convert snake_case to Title Case
    return event_name.replace('_', ' ').title()


# =============================================================================
# ERROR MAPPING HELPERS (Phase 5 - BUG_REFORM - 06 FEB 2026)
# =============================================================================

def _map_exception_to_error_code(e: Exception) -> 'ErrorCode':
    """
    Map exception type to appropriate ErrorCode for vector operations.

    Uses the new VECTOR_* error codes from BUG_REFORM Phase 2.

    Args:
        e: The exception that occurred

    Returns:
        ErrorCode enum value
    """
    from core.errors import ErrorCode

    error_str = str(e).lower()
    error_type = type(e).__name__

    # Format mismatch (file content doesn't match declared type)
    if 'not valid json' in error_str or 'not valid geojson' in error_str:
        return ErrorCode.VECTOR_FORMAT_MISMATCH
    if 'not valid xml' in error_str or 'not a kml document' in error_str:
        return ErrorCode.VECTOR_FORMAT_MISMATCH
    if 'missing required component' in error_str:
        return ErrorCode.VECTOR_UNREADABLE

    # File/parsing errors
    if 'unable to open' in error_str or 'no such file' in error_str:
        return ErrorCode.FILE_NOT_FOUND
    if 'cannot read' in error_str or 'parse error' in error_str or 'malformed' in error_str:
        return ErrorCode.VECTOR_UNREADABLE
    if 'encoding' in error_str or 'codec' in error_str or 'utf' in error_str:
        return ErrorCode.VECTOR_ENCODING_ERROR

    # Mixed geometry types
    if 'mixed geometry types' in error_str:
        return ErrorCode.VECTOR_MIXED_GEOMETRY

    # Geometry errors
    if 'geometry' in error_str and 'invalid' in error_str:
        return ErrorCode.VECTOR_GEOMETRY_INVALID
    if 'geometry' in error_str and ('null' in error_str or 'empty' in error_str):
        return ErrorCode.VECTOR_GEOMETRY_EMPTY
    if 'no features' in error_str or ('empty' in error_str and 'geodataframe' in error_str) or 'contains 0 features' in error_str:
        return ErrorCode.VECTOR_NO_FEATURES

    # Coordinate/CRS errors
    if 'crs' in error_str and ('missing' in error_str or 'none' in error_str):
        return ErrorCode.CRS_MISSING
    if 'coordinate' in error_str or 'lat' in error_str or 'lon' in error_str:
        return ErrorCode.VECTOR_COORDINATE_ERROR

    # Database errors
    if 'database' in error_str or 'postgres' in error_str or 'connection' in error_str:
        return ErrorCode.DATABASE_ERROR
    if 'table' in error_str and 'already exists' in error_str:
        return ErrorCode.TABLE_EXISTS
    if 'table' in error_str and 'invalid' in error_str:
        return ErrorCode.VECTOR_TABLE_NAME_INVALID

    # Column/attribute errors
    if 'column' in error_str or 'attribute' in error_str or 'dtype' in error_str:
        return ErrorCode.VECTOR_ATTRIBUTE_ERROR

    # Storage errors
    if 'storage' in error_str or 'blob' in error_str or 'container' in error_str:
        return ErrorCode.STORAGE_ERROR
    if 'download' in error_str:
        return ErrorCode.DOWNLOAD_FAILED

    # Memory/resource errors
    if 'memory' in error_str or 'oom' in error_str:
        return ErrorCode.MEMORY_ERROR

    # Default to processing failed
    return ErrorCode.PROCESSING_FAILED


def _get_vector_remediation(error_code: 'ErrorCode', e: Exception) -> str:
    """
    Get user-friendly remediation guidance for vector error codes.

    Args:
        error_code: The ErrorCode for this error
        e: The original exception

    Returns:
        Remediation string with actionable guidance
    """
    from core.errors import ErrorCode

    remediation_map = {
        ErrorCode.FILE_NOT_FOUND: (
            "Verify the file path is correct and the file exists in the specified container. "
            "Ensure the upload completed successfully before submitting the job."
        ),
        ErrorCode.VECTOR_UNREADABLE: (
            "Your file could not be parsed. Ensure it is a valid GeoPackage, Shapefile, GeoJSON, "
            "or CSV file. If using Shapefile, include all required files (.shp, .dbf, .shx, .prj). "
            "Check for file corruption or truncation."
        ),
        ErrorCode.VECTOR_ENCODING_ERROR: (
            "Your file contains invalid characters. Re-export the file using UTF-8 encoding. "
            "Most GIS software has an option to specify encoding during export."
        ),
        ErrorCode.VECTOR_FORMAT_MISMATCH: (
            "The file content does not match the declared format. Verify the file "
            "extension matches the actual data. For example, ensure .geojson files "
            "contain valid GeoJSON (RFC 7946) and .kml files contain valid KML/XML. "
            "See the 'detail' field for the specific parsing error."
        ),
        ErrorCode.VECTOR_MIXED_GEOMETRY: (
            "Your file contains multiple geometry types (e.g., points and polygons) "
            "that cannot coexist in a single PostGIS table. Split your file by "
            "geometry type using QGIS (Vector > Geometry Tools > Explode) or ogr2ogr "
            "with a WHERE clause on geometry type, then submit each file separately. "
            "See the 'detail' field for the geometry type breakdown."
        ),
        ErrorCode.VECTOR_GEOMETRY_INVALID: (
            "Some geometries in your file are invalid (self-intersecting, unclosed rings, etc.). "
            "Use ST_MakeValid in PostGIS or Repair Geometry in ArcGIS/QGIS to fix them before upload."
        ),
        ErrorCode.VECTOR_GEOMETRY_EMPTY: (
            "Your file contains features with null or empty geometry. Ensure all features "
            "have valid geometry data. Remove empty features or populate geometry values."
        ),
        ErrorCode.VECTOR_NO_FEATURES: (
            "After removing invalid geometries, no features remain. Check your source data "
            "for valid geometry values. The file may be empty or all geometries may be null."
        ),
        ErrorCode.CRS_MISSING: (
            "Your file has no coordinate reference system defined. Either embed a CRS in your "
            "source file (e.g., .prj file for Shapefile) or provide the 'source_crs' parameter "
            "in your job submission (e.g., 'EPSG:4326')."
        ),
        ErrorCode.VECTOR_COORDINATE_ERROR: (
            "Could not parse coordinates from your file. If using CSV, ensure the lat/lon columns "
            "contain valid numeric values. Check for text values, nulls, or invalid coordinate formats."
        ),
        ErrorCode.VECTOR_TABLE_NAME_INVALID: (
            "The table name is invalid for PostGIS. Use lowercase letters, numbers, and underscores. "
            "Table names cannot start with a number and must not use reserved SQL keywords."
        ),
        ErrorCode.TABLE_EXISTS: (
            "A table with this name already exists from a previous attempt. "
            "Resubmit with processing_options.overwrite=true to replace it."
        ),
        ErrorCode.VECTOR_ATTRIBUTE_ERROR: (
            "Column data types could not be reconciled. Ensure each column has a consistent data type "
            "(all text or all numeric). Mixed types in a single column cannot be uploaded."
        ),
        ErrorCode.DATABASE_ERROR: (
            "A database error occurred. This may be a temporary issue. Please retry the job. "
            "If the error persists, contact support with the error_id."
        ),
        ErrorCode.STORAGE_ERROR: (
            "Could not access Azure storage. This may be a temporary issue. Please retry the job. "
            "If the error persists, contact support."
        ),
        ErrorCode.DOWNLOAD_FAILED: (
            "Failed to download the source file from storage. Verify the file exists and you have "
            "permission to access it. This may be a temporary network issue - please retry."
        ),
        ErrorCode.MEMORY_ERROR: (
            "The file is too large to process in memory. Consider splitting it into smaller files "
            "or contact support for large file processing options."
        ),
        ErrorCode.PROCESSING_FAILED: (
            "Vector processing failed unexpectedly. Please review the error details and contact "
            "support with the error_id if the issue is not clear from the message."
        ),
    }

    return remediation_map.get(error_code, (
        "An unexpected error occurred. Please review the error details and contact support "
        "with the error_id for assistance."
    ))
