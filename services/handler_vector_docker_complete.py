# ============================================================================
# VECTOR DOCKER COMPLETE HANDLER
# ============================================================================
# STATUS: Service layer - V0.8 Docker-based consolidated vector ETL
# PURPOSE: Single-handler vector ETL with checkpoint progress tracking
# CREATED: 24 JAN 2026
# LAST_REVIEWED: 24 JAN 2026
# EXPORTS: vector_docker_complete
# DEPENDENCIES: geopandas, infrastructure.blob, psycopg
# ============================================================================
"""
Vector Docker Complete Handler.

V0.8 consolidated vector ETL handler that replaces the 3-stage Function App
workflow with a single checkpoint-based handler. Eliminates pickle serialization
overhead and uses persistent connection pooling.

Checkpoint Phases:
    validated      - Source file validated, GeoDataFrame loaded
    table_created  - PostGIS table and metadata created
    style_created  - Default OGC style registered
    chunk_N        - Chunk N uploaded (N = 0, 1, 2...)
    stac_created   - STAC item registered
    complete       - Final result

Benefits:
    - No pickle serialization (direct memory → DB)
    - Connection pool reuse across all chunks
    - No timeout (Docker long-running process)
    - Large file support via mounted storage
    - Fine-grained checkpoint progress

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
            - chunk_size: Rows per batch (default: 20000)
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
    chunk_size = parameters.get('chunk_size', 20000)
    overwrite = parameters.get('overwrite', False)

    logger.info(f"[{job_id[:8]}] 🐳 Docker Vector ETL starting: {blob_name} → {schema}.{table_name}")

    # Track checkpoints for resume capability
    checkpoints = []
    checkpoint_data = {}

    def checkpoint(name: str, data: Dict[str, Any]):
        """Record a checkpoint for progress tracking."""
        checkpoints.append(name)
        checkpoint_data[name] = data
        logger.info(f"[{job_id[:8]}] ✓ Checkpoint: {name}")

    try:
        # =====================================================================
        # PHASE 1: Load and Validate Source File
        # =====================================================================
        logger.info(f"[{job_id[:8]}] 📥 Phase 1: Loading and validating source file")

        gdf, validation_result = _load_and_validate_source(
            blob_name=blob_name,
            container_name=container_name,
            file_extension=file_extension,
            parameters=parameters,
            job_id=job_id
        )

        checkpoint("validated", {
            "features": len(gdf),
            "crs": str(gdf.crs),
            "geometry_type": validation_result.get('geometry_type'),
            "columns": list(gdf.columns),
            "source_crs": validation_result.get('source_crs')
        })

        # =====================================================================
        # PHASE 2: Create PostGIS Table and Metadata
        # =====================================================================
        logger.info(f"[{job_id[:8]}] 🗄️ Phase 2: Creating PostGIS table")

        table_result = _create_table_and_metadata(
            gdf=gdf,
            table_name=table_name,
            schema=schema,
            overwrite=overwrite,
            parameters=parameters,
            validation_result=validation_result,
            job_id=job_id
        )

        checkpoint("table_created", {
            "table": f"{schema}.{table_name}",
            "geometry_type": table_result.get('geometry_type'),
            "srid": table_result.get('srid')
        })

        # =====================================================================
        # PHASE 2.5: Create Default Style
        # =====================================================================
        logger.info(f"[{job_id[:8]}] 🎨 Phase 2.5: Creating default style")

        style_result = _create_default_style(
            table_name=table_name,
            geometry_type=table_result.get('geometry_type'),
            style_params=parameters.get('style'),
            job_id=job_id
        )

        checkpoint("style_created", style_result)

        # =====================================================================
        # PHASE 3: Upload Chunks (with per-chunk checkpoints)
        # =====================================================================
        logger.info(f"[{job_id[:8]}] 📤 Phase 3: Uploading data in chunks")

        upload_result = _upload_chunks_with_checkpoints(
            gdf=gdf,
            table_name=table_name,
            schema=schema,
            chunk_size=chunk_size,
            job_id=job_id,
            checkpoint_fn=checkpoint
        )

        # =====================================================================
        # PHASE 4: Create STAC Item
        # =====================================================================
        logger.info(f"[{job_id[:8]}] 📋 Phase 4: Creating STAC item")

        stac_result = _create_stac_item(
            table_name=table_name,
            schema=schema,
            parameters=parameters,
            job_id=job_id
        )

        checkpoint("stac_created", stac_result)

        # =====================================================================
        # COMPLETE
        # =====================================================================
        elapsed = time.time() - start_time
        total_rows = upload_result.get('total_rows', 0)

        checkpoint("complete", {
            "total_rows": total_rows,
            "elapsed_seconds": round(elapsed, 2)
        })

        logger.info(
            f"[{job_id[:8]}] ✅ Docker Vector ETL complete: "
            f"{total_rows:,} rows in {elapsed:.1f}s "
            f"({total_rows/elapsed:.0f} rows/sec)" if elapsed > 0 else ""
        )

        return {
            "success": True,
            "result": {
                "table_name": table_name,
                "schema": schema,
                "total_rows": total_rows,
                "geometry_type": table_result.get('geometry_type'),
                "srid": table_result.get('srid', 4326),
                "stac_item_id": stac_result.get('item_id'),
                "collection_id": stac_result.get('collection_id'),
                "style_id": style_result.get('style_id', 'default'),
                "chunks_uploaded": upload_result.get('chunks_uploaded', 0),
                "checkpoint_count": len(checkpoints),
                "elapsed_seconds": round(elapsed, 2),
                "execution_mode": "docker",
                "connection_pooling": True
            }
        }

    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = f"Vector Docker ETL failed: {type(e).__name__}: {e}"
        logger.error(f"[{job_id[:8]}] ❌ {error_msg}\n{traceback.format_exc()}")

        return {
            "success": False,
            "error": error_msg,
            "error_type": type(e).__name__,
            "last_checkpoint": checkpoints[-1] if checkpoints else None,
            "checkpoint_data": checkpoint_data,
            "elapsed_seconds": round(elapsed, 2),
            "traceback": traceback.format_exc()
        }


# =============================================================================
# PHASE IMPLEMENTATIONS
# =============================================================================

def _load_and_validate_source(
    blob_name: str,
    container_name: str,
    file_extension: str,
    parameters: Dict[str, Any],
    job_id: str
) -> tuple:
    """
    Load source file and validate geometry.

    Returns:
        Tuple of (GeoDataFrame, validation_result dict)
    """
    from infrastructure.blob import BlobRepository
    from services.vector.converters import (
        _convert_csv, _convert_geojson, _convert_geopackage,
        _convert_kml, _convert_kmz, _convert_shapefile
    )
    from services.vector.postgis_handler import VectorToPostGISHandler

    config = get_config()

    # Build converter params
    converter_params = parameters.get('converter_params', {}) or {}
    if file_extension == 'csv':
        if parameters.get('lat_name'):
            converter_params['lat_name'] = parameters['lat_name']
        if parameters.get('lon_name'):
            converter_params['lon_name'] = parameters['lon_name']
        if parameters.get('wkt_column'):
            converter_params['wkt_column'] = parameters['wkt_column']

    # Download source file
    logger.info(f"[{job_id[:8]}] Downloading {blob_name} from {container_name}")
    blob_repo = BlobRepository.for_zone("bronze")
    file_bytes = blob_repo.read_blob(container_name, blob_name)

    log_memory_checkpoint(logger, "After file download", context_id=job_id,
                          file_size_mb=round(len(file_bytes) / (1024 * 1024), 1))

    # Convert to GeoDataFrame based on format
    converter_map = {
        'csv': _convert_csv,
        'geojson': _convert_geojson,
        'json': _convert_geojson,
        'gpkg': _convert_geopackage,
        'kml': _convert_kml,
        'kmz': _convert_kmz,
        'shp': _convert_shapefile,
        'zip': _convert_shapefile
    }

    converter = converter_map.get(file_extension)
    if not converter:
        raise ValueError(f"Unsupported file format: {file_extension}")

    gdf = converter(file_bytes, converter_params)
    original_crs = str(gdf.crs) if gdf.crs else 'unknown'

    log_memory_checkpoint(logger, "After format conversion", context_id=job_id,
                          rows=len(gdf), crs=original_crs)

    # Apply column mapping if provided
    column_mapping = parameters.get('column_mapping')
    if column_mapping:
        from services.vector.process_vector_tasks import _apply_column_mapping
        gdf = _apply_column_mapping(gdf, column_mapping, job_id)

    # Validate and reproject to EPSG:4326
    handler = VectorToPostGISHandler()
    geometry_params = parameters.get('geometry_params', {})
    validated_gdf = handler.validate_and_prepare_gdf(gdf, geometry_params)

    if len(validated_gdf) == 0:
        raise ValueError("No valid features after geometry validation")

    # Get geometry type
    geom_types = validated_gdf.geometry.geom_type.unique()
    geometry_type = geom_types[0] if len(geom_types) == 1 else 'GEOMETRY'

    log_memory_checkpoint(logger, "After validation", context_id=job_id,
                          rows=len(validated_gdf), geometry_type=geometry_type)

    return validated_gdf, {
        'geometry_type': geometry_type,
        'source_crs': original_crs,
        'columns': list(validated_gdf.columns)
    }


def _create_table_and_metadata(
    gdf,
    table_name: str,
    schema: str,
    overwrite: bool,
    parameters: Dict[str, Any],
    validation_result: Dict[str, Any],
    job_id: str
) -> Dict[str, Any]:
    """
    Create PostGIS table and register metadata.

    Returns:
        Dict with table creation result
    """
    from services.vector.postgis_handler import VectorToPostGISHandler

    handler = VectorToPostGISHandler()

    # Get geometry type
    geom_types = gdf.geometry.geom_type.unique()
    geometry_type = geom_types[0].upper() if len(geom_types) == 1 else 'GEOMETRY'

    # Detect temporal extent if temporal_property specified
    temporal_start = None
    temporal_end = None
    temporal_property = parameters.get('temporal_property')

    if temporal_property and temporal_property in gdf.columns:
        try:
            temporal_col = gdf[temporal_property].dropna()
            if len(temporal_col) > 0:
                temporal_start = str(temporal_col.min())
                temporal_end = str(temporal_col.max())
                logger.info(f"[{job_id[:8]}] Detected temporal extent: {temporal_start} to {temporal_end}")
        except Exception as e:
            logger.warning(f"[{job_id[:8]}] Failed to detect temporal extent: {e}")

    # Create table with IF NOT EXISTS
    indexes = parameters.get('indexes', {'spatial': True, 'attributes': [], 'temporal': []})

    handler.create_table_if_not_exists(
        table_name=table_name,
        gdf=gdf,
        schema=schema,
        geometry_type=geometry_type,
        srid=4326,
        indexes=indexes
    )

    # Register metadata
    handler.register_table_metadata(
        table_name=table_name,
        schema=schema,
        geometry_type=geometry_type,
        srid=4326,
        feature_count=len(gdf),
        columns=[c for c in gdf.columns if c != 'geometry'],
        title=parameters.get('title'),
        description=parameters.get('description'),
        attribution=parameters.get('attribution'),
        license=parameters.get('license'),
        keywords=parameters.get('keywords'),
        temporal_start=temporal_start,
        temporal_end=temporal_end,
        temporal_property=temporal_property
    )

    logger.info(f"[{job_id[:8]}] Created table {schema}.{table_name} ({geometry_type}, SRID=4326)")

    return {
        'table_name': table_name,
        'schema': schema,
        'geometry_type': geometry_type,
        'srid': 4326
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
            # Use custom style params
            fill_color = style_params.get('fill_color', '#3388ff')
            stroke_color = style_params.get('stroke_color', '#2266cc')
            logger.info(f"[{job_id[:8]}] Creating style with custom params: fill={fill_color}, stroke={stroke_color}")
        else:
            # Use defaults
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
        logger.warning(f"[{job_id[:8]}] ⚠️ Style creation failed (non-fatal): {e}")
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
    from services.vector.postgis_handler import VectorToPostGISHandler

    handler = VectorToPostGISHandler()

    total_features = len(gdf)
    num_chunks = (total_features + chunk_size - 1) // chunk_size

    logger.info(f"[{job_id[:8]}] Uploading {total_features:,} features in {num_chunks} chunks")

    total_rows_inserted = 0
    total_rows_deleted = 0
    chunk_times = []

    for i in range(num_chunks):
        chunk_start = i * chunk_size
        chunk_end = min((i + 1) * chunk_size, total_features)
        chunk = gdf.iloc[chunk_start:chunk_end].copy()

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
            avg_time = sum(chunk_times) / len(chunk_times)
            rows_per_sec = total_rows_inserted / sum(chunk_times) if chunk_times else 0
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


def _create_stac_item(
    table_name: str,
    schema: str,
    parameters: Dict[str, Any],
    job_id: str
) -> Dict[str, Any]:
    """
    Create STAC item for the vector table.

    Returns:
        Dict with STAC creation result
    """
    try:
        from services.stac_vector_catalog import create_vector_stac
        from config.defaults import STACDefaults

        # Call existing STAC handler
        stac_params = {
            'schema': schema,
            'table_name': table_name,
            'collection_id': STACDefaults.VECTOR_COLLECTION,
            'source_file': parameters.get('blob_name'),
            'source_format': parameters.get('file_extension'),
            'job_id': job_id,
            'geometry_params': parameters.get('geometry_params', {}),
            # DDH identifiers for artifact tracking
            'dataset_id': parameters.get('dataset_id'),
            'resource_id': parameters.get('resource_id'),
            'version_id': parameters.get('version_id'),
            'stac_item_id': parameters.get('stac_item_id'),
            '_platform_job_id': parameters.get('_platform_job_id')
        }

        result = create_vector_stac(stac_params)

        if result.get('success'):
            stac_data = result.get('result', {})
            return {
                'item_id': stac_data.get('stac_id') or stac_data.get('item_id'),
                'collection_id': stac_data.get('collection_id', STACDefaults.VECTOR_COLLECTION),
                'inserted_to_pgstac': stac_data.get('inserted_to_pgstac', True),
                'degraded': stac_data.get('degraded', False)
            }
        elif result.get('degraded'):
            # Graceful degradation - STAC unavailable but data is in PostGIS
            logger.warning(f"[{job_id[:8]}] STAC registration degraded: {result.get('warning')}")
            return {
                'item_id': None,
                'collection_id': STACDefaults.VECTOR_COLLECTION,
                'inserted_to_pgstac': False,
                'degraded': True,
                'degraded_reason': result.get('warning')
            }
        else:
            raise Exception(result.get('error', 'Unknown STAC error'))

    except Exception as e:
        # STAC creation failure is non-fatal - data is already in PostGIS
        logger.warning(f"[{job_id[:8]}] ⚠️ STAC creation failed (non-fatal): {e}")
        return {
            'item_id': None,
            'collection_id': None,
            'inserted_to_pgstac': False,
            'degraded': True,
            'error': str(e)
        }
