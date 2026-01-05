# ============================================================================
# PROCESS VECTOR TASK HANDLERS
# ============================================================================
# STATUS: Service layer - Vector ETL workflow handlers
# PURPOSE: Idempotent vector processing with DELETE+INSERT pattern
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: process_vector_prepare, process_vector_upload
# DEPENDENCIES: geopandas, infrastructure.blob
# ============================================================================
"""
Process Vector Task Handlers.

Idempotent vector ETL workflow handlers using DELETE+INSERT pattern.

Stage 1 (process_vector_prepare):
    - Downloads source file from Bronze container
    - Validates and prepares GeoDataFrame
    - Creates target table with etl_batch_id column
    - Chunks and pickles data for Stage 2 fan-out

Stage 2 (process_vector_upload):
    - Loads pickled chunk
    - DELETEs existing rows with matching batch_id
    - INSERTs new rows with batch_id

Exports:
    process_vector_prepare: Stage 1 handler
    process_vector_upload: Stage 2 handler
"""

from typing import Dict, Any
import pickle
import logging
import traceback

from infrastructure.blob import BlobRepository
from config import get_config
from util_logger import LoggerFactory, ComponentType, log_memory_checkpoint

# Component-specific logger
logger = LoggerFactory.create_logger(
    ComponentType.SERVICE,
    "process_vector_tasks"
)


# ============================================================================
# GAP-009 FIX (16 DEC 2025): Memory Usage Logging Helper
# ============================================================================

def _log_memory_usage(gdf, label: str, job_id: str) -> float:
    """
    Log GeoDataFrame memory usage for debugging OOM issues.

    Args:
        gdf: GeoDataFrame to measure
        label: Description of measurement point (e.g., "after_load", "after_validation")
        job_id: Job ID for log correlation

    Returns:
        Memory usage in MB
    """
    mem_bytes = gdf.memory_usage(deep=True).sum()
    mem_mb = mem_bytes / (1024 * 1024)
    logger.info(f"[{job_id[:8]}] 📊 Memory usage ({label}): {mem_mb:.1f}MB ({len(gdf)} rows)")
    return mem_mb


# ============================================================================
# Column Mapping Helper (24 DEC 2025)
# ============================================================================

def _apply_column_mapping(gdf, mapping: Dict[str, str], job_id: str):
    """
    Apply column renames to GeoDataFrame with validation.

    Validates that all source columns exist before renaming. Provides detailed
    error message listing missing columns and available columns for debugging.

    Args:
        gdf: Source GeoDataFrame
        mapping: {source_column: target_column} rename mapping
        job_id: Job ID for log correlation

    Returns:
        GeoDataFrame with renamed columns

    Raises:
        ValueError: If any source columns in mapping are not found in GeoDataFrame
    """
    # Get available columns (exclude geometry column from list)
    available_cols = [c for c in gdf.columns if c != 'geometry']

    # Check for missing source columns
    missing = [col for col in mapping.keys() if col not in gdf.columns]

    if missing:
        raise ValueError(
            f"Column mapping failed. Source columns not found: {missing}. "
            f"Available columns in source file: {available_cols}"
        )

    # Apply renames
    gdf = gdf.rename(columns=mapping)

    # Log the mapping
    renamed_pairs = [f"'{src}' → '{tgt}'" for src, tgt in mapping.items()]
    logger.info(f"[{job_id[:8]}] 🔄 Applied column mapping: {', '.join(renamed_pairs)}")

    return gdf


def process_vector_prepare(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 1: Prepare vector data for chunked upload with idempotent table creation.

    IDEMPOTENCY:
    - Pickle uploads use overwrite=True (safe to re-run)
    - Table creation uses IF NOT EXISTS (safe to re-run)
    - etl_batch_id column added for Stage 2 idempotency

    Parameters:
        params: {
            'job_id': str,           # Required for batch_id generation and pickle paths
            'blob_name': str,        # Source file path in container
            'container_name': str,   # Bronze container (default: config.storage.bronze.rasters)
            'file_extension': str,   # csv, geojson, gpkg, kml, kmz, shp, zip
            'table_name': str,       # Target PostGIS table name
            'schema': str,           # Target schema (default: geo)
            'chunk_size': int,       # Rows per chunk (default: None = auto-calculate)
            'converter_params': dict,# File-specific params (CSV: lat/lon cols)
            'geometry_params': dict, # Geometry validation params
            'indexes': dict          # Index configuration
        }

    Returns:
        {
            'success': True,
            'result': {
                'chunk_paths': ['pickles/job123/chunk_0.pkl', ...],
                'total_features': 125000,
                'num_chunks': 7,
                'table_name': 'my_table',
                'schema': 'geo',
                'columns': ['col1', 'col2', ...],
                'geometry_type': 'MULTIPOLYGON',
                'srid': 4326
            }
        }
    """
    from .converters import (
        _convert_csv, _convert_geojson, _convert_geopackage,
        _convert_kml, _convert_kmz, _convert_shapefile
    )
    from .postgis_handler import VectorToPostGISHandler

    config = get_config()

    # Extract parameters
    job_id = parameters['job_id']
    blob_name = parameters['blob_name']
    # Use config for default container (bronze zone for input data)
    container_name = parameters.get('container_name', config.storage.bronze.rasters)
    file_extension = parameters['file_extension'].lower().lstrip('.')
    table_name = parameters['table_name']
    schema = parameters.get('schema', 'geo')
    chunk_size = parameters.get('chunk_size')
    converter_params = parameters.get('converter_params', {}) or {}

    # GAP-008a/008b (15 DEC 2025): Merge top-level CSV geometry params into converter_params
    # Top-level params take precedence over nested converter_params for discoverability
    if file_extension == 'csv':
        if parameters.get('lat_name'):
            converter_params['lat_name'] = parameters['lat_name']
        if parameters.get('lon_name'):
            converter_params['lon_name'] = parameters['lon_name']
        if parameters.get('wkt_column'):
            converter_params['wkt_column'] = parameters['wkt_column']

    geometry_params = parameters.get('geometry_params', {})
    indexes = parameters.get('indexes', {'spatial': True, 'attributes': [], 'temporal': []})

    # User-provided metadata fields (09 DEC 2025)
    title = parameters.get('title')
    description = parameters.get('description')
    attribution = parameters.get('attribution')
    license_id = parameters.get('license')  # 'license' is reserved word
    keywords = parameters.get('keywords')
    temporal_property = parameters.get('temporal_property')

    logger.info(f"[{job_id[:8]}] Stage 1: Preparing vector data from {blob_name}")

    # GAP-007 FIX (15 DEC 2025): Pre-flight file size check
    # Azure Functions have memory limits - large files cause OOM before useful error
    # GeoDataFrames typically expand 3-5x in memory vs source file size
    # B3 Basic: ~1.75GB available, Premium: up to 14GB
    # Raised to 2GB per user request (15 DEC 2025) - acled_export.csv (1.3GB) needs to work
    MAX_FILE_SIZE_MB = 2048  # 2GB limit
    blob_repo = BlobRepository.for_zone("bronze")

    try:
        blob_properties = blob_repo.get_blob_properties(container_name, blob_name)
        blob_size_bytes = blob_properties.get('size', 0)
        blob_size_mb = blob_size_bytes / (1024 * 1024)

        logger.info(
            f"[{job_id[:8]}] Source file size: {blob_size_mb:.1f}MB "
            f"(limit: {MAX_FILE_SIZE_MB}MB)"
        )

        if blob_size_mb > MAX_FILE_SIZE_MB:
            raise ValueError(
                f"Source file too large for in-memory processing: {blob_size_mb:.1f}MB. "
                f"Maximum supported: {MAX_FILE_SIZE_MB}MB. "
                f"GeoDataFrames expand 3-5x in memory vs source file size. "
                f"Consider splitting the file or using a streaming approach for files > {MAX_FILE_SIZE_MB}MB."
            )
    except ValueError:
        # Re-raise size errors
        raise
    except Exception as e:
        # Non-fatal: If we can't get properties, proceed with download and hope for the best
        logger.warning(f"[{job_id[:8]}] ⚠️ Could not get blob properties (non-fatal): {e}")

    # Step 1: Download source file from Bronze zone (08 DEC 2025)
    file_data = blob_repo.read_blob_to_stream(container_name, blob_name)

    # Memory checkpoint 1: After blob download
    log_memory_checkpoint(logger, "After blob download",
                          context_id=job_id,
                          blob_size_mb=round(blob_size_mb, 1),
                          file_extension=file_extension)

    # Step 2: Convert to GeoDataFrame
    converters = {
        'csv': _convert_csv,
        'geojson': _convert_geojson,
        'json': _convert_geojson,
        'gpkg': _convert_geopackage,
        'kml': _convert_kml,
        'kmz': _convert_kmz,
        'shp': _convert_shapefile,
        'zip': _convert_shapefile
    }

    if file_extension not in converters:
        raise ValueError(f"Unsupported file extension: '{file_extension}'")

    gdf = converters[file_extension](file_data, **converter_params)
    total_features = len(gdf)
    logger.info(f"[{job_id[:8]}] Loaded {total_features} features")

    # GAP-009 FIX (16 DEC 2025): Log memory usage after load
    gdf_mem_mb = _log_memory_usage(gdf, "after_load", job_id)

    # Memory checkpoint 2: After GeoDataFrame conversion (PEAK MEMORY - GDF expansion)
    log_memory_checkpoint(logger, "After GDF conversion",
                          context_id=job_id,
                          feature_count=total_features,
                          gdf_memory_mb=round(gdf_mem_mb, 1))

    # Step 2b: Apply column mapping if specified (24 DEC 2025)
    # Used for standardizing column names (e.g., ISO_A3 → iso3 for system tables)
    column_mapping = parameters.get('column_mapping')
    if column_mapping:
        gdf = _apply_column_mapping(gdf, column_mapping, job_id)

    # GAP-002 FIX (15 DEC 2025): Validate source file contains features
    # Empty source files would create empty tables and silently "succeed"
    if total_features == 0:
        raise ValueError(
            f"Source file '{blob_name}' contains 0 features. "
            f"File may be empty, corrupted, or in wrong format for extension '{file_extension}'. "
            f"Converter used: {converters[file_extension].__name__}."
        )

    # Capture original CRS before reprojection (06 DEC 2025)
    # This is stored in table_metadata for data lineage tracking
    original_crs = str(gdf.crs) if gdf.crs else "unknown"
    logger.info(f"[{job_id[:8]}] Original CRS: {original_crs}")

    # Step 3: Validate and prepare GeoDataFrame (reprojects to EPSG:4326)
    handler = VectorToPostGISHandler()
    validated_gdf = handler.prepare_gdf(gdf, geometry_params=geometry_params)

    # Capture any warnings from prepare_gdf (e.g., out-of-range datetime values)
    # These will be included in the job result for visibility (30 DEC 2025)
    data_warnings = handler.last_warnings.copy() if handler.last_warnings else []

    # GAP-009 FIX (16 DEC 2025): Log memory usage after validation
    validated_mem_mb = _log_memory_usage(validated_gdf, "after_validation", job_id)

    # Memory checkpoint 3: After geometry validation and reprojection
    log_memory_checkpoint(logger, "After GDF validation",
                          context_id=job_id,
                          validated_features=len(validated_gdf),
                          gdf_memory_mb=round(validated_mem_mb, 1))

    # GAP-002 FIX (15 DEC 2025): Validate features remain after geometry validation
    # prepare_gdf can filter out features with invalid/null geometries
    validated_count = len(validated_gdf)
    if validated_count == 0:
        raise ValueError(
            f"All {total_features} features filtered out during geometry validation. "
            f"geometry_params: {geometry_params}. "
            f"Common causes: all NULL geometries, invalid coordinates, CRS reprojection failures. "
            f"Check source data geometry validity."
        )

    if validated_count < total_features:
        filtered_count = total_features - validated_count
        logger.warning(
            f"[{job_id[:8]}] ⚠️ {filtered_count} features ({filtered_count/total_features*100:.1f}%) "
            f"filtered out during validation. {validated_count} features remaining."
        )

    # Get metadata
    geometry_type = validated_gdf.geometry.iloc[0].geom_type.upper()

    # Check for reserved column names (id, geom, etl_batch_id are created by our schema)
    reserved_cols = {'id', 'geom', 'geometry', 'etl_batch_id'}
    all_columns = [c for c in validated_gdf.columns if c != 'geometry']
    skipped_columns = [c for c in all_columns if c.lower() in reserved_cols]
    columns = [c for c in all_columns if c.lower() not in reserved_cols]

    if skipped_columns:
        logger.warning(
            f"[{job_id[:8]}] ⚠️ Source data contains reserved column names that will be skipped: {skipped_columns}. "
            f"These columns are created by our schema (id=PRIMARY KEY, geom=GEOMETRY, etl_batch_id=IDEMPOTENCY)."
        )

    # Step 3b: Auto-detect temporal extent if temporal_property specified (09 DEC 2025)
    temporal_start = None
    temporal_end = None
    if temporal_property and temporal_property in validated_gdf.columns:
        try:
            import pandas as pd
            temporal_col = pd.to_datetime(validated_gdf[temporal_property], errors='coerce')
            valid_dates = temporal_col.dropna()
            if len(valid_dates) > 0:
                temporal_start = valid_dates.min().isoformat() + "Z"
                temporal_end = valid_dates.max().isoformat() + "Z"
                logger.info(
                    f"[{job_id[:8]}] Temporal extent detected from '{temporal_property}': "
                    f"{temporal_start} to {temporal_end}"
                )
            else:
                logger.warning(
                    f"[{job_id[:8]}] ⚠️ temporal_property '{temporal_property}' found but no valid dates parsed"
                )
        except Exception as e:
            logger.warning(f"[{job_id[:8]}] ⚠️ Failed to parse temporal_property '{temporal_property}': {e}")
    elif temporal_property:
        logger.warning(
            f"[{job_id[:8]}] ⚠️ temporal_property '{temporal_property}' not found in columns: {list(validated_gdf.columns)}"
        )

    # Step 4: Create table with etl_batch_id column (IDEMPOTENT - IF NOT EXISTS)
    handler.create_table_with_batch_tracking(
        table_name=table_name,
        schema=schema,
        gdf=validated_gdf,
        indexes=indexes
    )
    logger.info(f"[{job_id[:8]}] Created table {schema}.{table_name} with etl_batch_id tracking")

    # Step 4b: Register table metadata in geo.table_metadata (06 DEC 2025, updated 09 DEC 2025)
    # This is the SOURCE OF TRUTH for vector metadata - STAC copies for convenience
    # Uses INSERT ON CONFLICT UPDATE for idempotency
    handler.register_table_metadata(
        table_name=table_name,
        schema=schema,
        etl_job_id=job_id,
        source_file=blob_name,
        source_format=file_extension,
        source_crs=original_crs,
        feature_count=total_features,
        geometry_type=geometry_type,
        bbox=tuple(validated_gdf.total_bounds),  # [minx, miny, maxx, maxy]
        # User-provided metadata (09 DEC 2025)
        title=title,
        description=description,
        attribution=attribution,
        license=license_id,
        keywords=keywords,
        temporal_start=temporal_start,
        temporal_end=temporal_end,
        temporal_property=temporal_property
    )

    # Step 5: Calculate optimal chunk size and split
    chunks = handler.chunk_gdf(validated_gdf, chunk_size)
    actual_chunk_size = len(chunks[0]) if chunks else 0

    # Step 6: Pickle each chunk to Silver zone blob storage (IDEMPOTENT - overwrite=True)
    # IMPORTANT: Pickles go to Silver zone (intermediate processed data), not Bronze (09 DEC 2025)
    # Bronze = raw input files, Silver = processed/intermediate data
    logger.info(f"[{job_id[:8]}] Step 6: Writing {len(chunks)} pickles to Silver zone container '{config.vector_pickle_container}'")
    silver_repo = BlobRepository.for_zone("silver")

    chunk_paths = []
    verified_pickles = []
    pickle_errors = []

    # Progress tracking setup (26 DEC 2025)
    # - Memory logging every 10 chunks (log only)
    # - Task progress update at 25%, 50%, 75% milestones (DB update)
    task_id = parameters.get('task_id')  # May be None if called outside task context
    total_chunks = len(chunks)
    progress_milestones = {int(total_chunks * p) for p in [0.25, 0.50, 0.75]} if total_chunks > 4 else set()
    last_memory_log = 0

    for i, chunk in enumerate(chunks):
        chunk_path = f"{config.vector_pickle_prefix}/{job_id}/chunk_{i}.pkl"

        try:
            # Pickle with protocol 5 (best compression)
            logger.debug(f"[{job_id[:8]}] Pickling chunk {i+1}/{len(chunks)} ({len(chunk)} rows)")
            pickled = pickle.dumps(chunk, protocol=5)
            pickle_size = len(pickled)
            logger.debug(f"[{job_id[:8]}] Chunk {i+1} pickled: {pickle_size:,} bytes")

            # Write to Silver zone blob storage with overwrite=True (IDEMPOTENT)
            write_result = silver_repo.write_blob(
                config.vector_pickle_container,
                chunk_path,
                pickled
            )

            # CRITICAL: Verify write was successful (09 DEC 2025)
            if write_result and write_result.get('size', 0) > 0:
                logger.info(
                    f"[{job_id[:8]}] ✅ Chunk {i+1}/{len(chunks)} written: "
                    f"{chunk_path} ({write_result['size']:,} bytes, etag={write_result.get('etag', 'N/A')[:16]}...)"
                )
                chunk_paths.append(chunk_path)
                verified_pickles.append({
                    'chunk_index': i,
                    'path': chunk_path,
                    'rows': len(chunk),
                    'pickle_bytes': pickle_size,
                    'blob_bytes': write_result['size'],
                    'etag': write_result.get('etag')
                })

                # Progress tracking (26 DEC 2025)
                chunks_done = i + 1
                percent_complete = (chunks_done / total_chunks) * 100

                # Memory logging every 10 chunks (log only, no DB overhead)
                if chunks_done - last_memory_log >= 10 or chunks_done == total_chunks:
                    log_memory_checkpoint(
                        logger, f"Pickle progress {chunks_done}/{total_chunks}",
                        context_id=job_id,
                        chunks_written=chunks_done,
                        percent_complete=round(percent_complete, 1)
                    )
                    last_memory_log = chunks_done

                # Task progress update at milestones (25%, 50%, 75%) - minimal DB overhead
                if task_id and chunks_done in progress_milestones:
                    try:
                        from infrastructure.jobs_tasks import JobsTasksRepository
                        repo = JobsTasksRepository()
                        repo.update_task_metadata(task_id, {
                            'pickle_progress': {
                                'chunks_written': chunks_done,
                                'total_chunks': total_chunks,
                                'percent_complete': round(percent_complete, 1),
                                'total_rows_written': sum(p['rows'] for p in verified_pickles)
                            }
                        }, merge=True)
                        logger.info(f"[{job_id[:8]}] 📊 Progress update: {percent_complete:.0f}% ({chunks_done}/{total_chunks} chunks)")
                    except Exception as progress_err:
                        # Non-fatal - don't fail task due to progress tracking error
                        logger.warning(f"[{job_id[:8]}] ⚠️ Failed to update progress: {progress_err}")

            else:
                # Write returned but with no size - suspicious!
                error_msg = f"Chunk {i} write returned invalid result: {write_result}"
                logger.error(f"[{job_id[:8]}] ❌ {error_msg}")
                pickle_errors.append({
                    'chunk_index': i,
                    'path': chunk_path,
                    'error': error_msg,
                    'error_type': 'InvalidWriteResult'
                })

        except Exception as e:
            # Capture and log pickle/write errors but continue to track all failures
            error_msg = f"Failed to pickle/write chunk {i}: {e}"
            logger.error(f"[{job_id[:8]}] ❌ {error_msg}\n{traceback.format_exc()}")
            pickle_errors.append({
                'chunk_index': i,
                'path': chunk_path,
                'error': str(e),
                'error_type': type(e).__name__,
                'traceback': traceback.format_exc()
            })

    # Step 7: CRITICAL VALIDATION - Ensure ALL pickles were created successfully (09 DEC 2025)
    if pickle_errors:
        error_summary = f"Failed to create {len(pickle_errors)}/{len(chunks)} pickles"
        logger.error(f"[{job_id[:8]}] ❌ STAGE 1 FAILED: {error_summary}")
        logger.error(f"[{job_id[:8]}] Pickle errors: {pickle_errors}")

        # Raise exception to PREVENT Stage 2 from starting
        raise RuntimeError(
            f"Stage 1 pickle creation failed: {error_summary}. "
            f"Failed chunks: {[e['chunk_index'] for e in pickle_errors]}. "
            f"First error: {pickle_errors[0]['error']}"
        )

    if len(chunk_paths) != len(chunks):
        error_msg = f"Pickle count mismatch: expected {len(chunks)}, got {len(chunk_paths)}"
        logger.error(f"[{job_id[:8]}] ❌ STAGE 1 FAILED: {error_msg}")
        raise RuntimeError(f"Stage 1 validation failed: {error_msg}")

    # Step 8: Final verification - check all pickles exist in blob storage
    logger.info(f"[{job_id[:8]}] Step 8: Verifying all {len(chunk_paths)} pickles exist in blob storage")
    missing_pickles = []
    for chunk_path in chunk_paths:
        if not silver_repo.blob_exists(config.vector_pickle_container, chunk_path):
            missing_pickles.append(chunk_path)
            logger.error(f"[{job_id[:8]}] ❌ Pickle missing after write: {chunk_path}")

    if missing_pickles:
        error_msg = f"Pickle verification failed: {len(missing_pickles)} pickles missing after write"
        logger.error(f"[{job_id[:8]}] ❌ STAGE 1 FAILED: {error_msg}")
        logger.error(f"[{job_id[:8]}] Missing pickles: {missing_pickles}")
        raise RuntimeError(f"Stage 1 verification failed: {error_msg}. Missing: {missing_pickles}")

    logger.info(
        f"[{job_id[:8]}] ✅ Stage 1 COMPLETE: {len(chunk_paths)} pickles created and verified, "
        f"{total_features} total features, ready for Stage 2 fan-out"
    )

    # Memory checkpoint 4: After chunking and pickle upload (cleanup phase)
    total_pickle_bytes = sum(p['pickle_bytes'] for p in verified_pickles)
    log_memory_checkpoint(logger, "After pickle upload (cleanup)",
                          context_id=job_id,
                          num_chunks=len(chunk_paths),
                          total_pickle_mb=round(total_pickle_bytes / (1024 * 1024), 1))

    result = {
        'chunk_paths': chunk_paths,
        'total_features': total_features,
        'num_chunks': len(chunks),
        'chunk_size_used': actual_chunk_size,
        'table_name': table_name,
        'schema': schema,
        'columns': columns,
        'geometry_type': geometry_type,
        'srid': 4326,
        'source_file': blob_name,
        'source_crs': original_crs,  # Original CRS before reprojection to 4326
        'pickle_verification': {
            'all_verified': True,
            'pickle_count': len(verified_pickles),
            'total_pickle_bytes': sum(p['pickle_bytes'] for p in verified_pickles),
            'total_blob_bytes': sum(p['blob_bytes'] for p in verified_pickles)
        }
    }

    # Include skipped columns in result if any were filtered
    if skipped_columns:
        result['skipped_reserved_columns'] = skipped_columns

    # Include data warnings in result (e.g., sanitized datetime values) (30 DEC 2025)
    if data_warnings:
        result['data_warnings'] = data_warnings

    return {
        "success": True,
        "result": result
    }


def process_vector_upload(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 2: Upload pickled chunk to PostGIS with DELETE+INSERT idempotency.

    IDEMPOTENCY MECHANISM:
    1. Compute deterministic batch_id from job_id + chunk_index
    2. DELETE any existing rows with that batch_id
    3. INSERT new rows with batch_id included

    This ensures re-running the same task:
    - Deletes the partial/complete previous attempt
    - Inserts fresh data
    - Results in exactly the same final state

    Parameters:
        params: {
            'job_id': str,           # Required - used in batch_id
            'chunk_index': int,      # Required - used in batch_id
            'chunk_path': str,       # Path to pickled GeoDataFrame
            'table_name': str,       # Target PostGIS table
            'schema': str            # Target schema (default: geo)
        }

    Returns:
        {
            'success': True,
            'result': {
                'rows_inserted': 20000,
                'rows_deleted': 0,      # 0 on first run, >0 on retry
                'batch_id': 'abc12345-chunk-3',
                'chunk_index': 3,
                'table': 'geo.my_table'
            }
        }
    """
    import psycopg
    import time
    from .postgis_handler import VectorToPostGISHandler

    config = get_config()

    # Extract parameters
    job_id = parameters['job_id']
    chunk_index = parameters['chunk_index']
    chunk_path = parameters['chunk_path']
    table_name = parameters['table_name']
    schema = parameters.get('schema', 'geo')

    # Deterministic batch_id for idempotency
    batch_id = f"{job_id[:8]}-chunk-{chunk_index}"

    logger.info(f"[{job_id[:8]}] Stage 2: Uploading chunk {chunk_index} (batch_id: {batch_id})")

    # GAP-008 FIX (16 DEC 2025): Track timing for performance analysis
    start_time = time.time()

    try:
        # Step 1: Load pickled chunk from blob storage (silver zone - intermediate data)
        blob_repo = BlobRepository.for_zone("silver")
        pickled_data = blob_repo.read_blob(config.vector_pickle_container, chunk_path)
        chunk = pickle.loads(pickled_data)

        # Memory checkpoint 1: After pickle load
        log_memory_checkpoint(logger, "After pickle load",
                              context_id=job_id,
                              chunk_index=chunk_index,
                              chunk_rows=len(chunk))

        # Step 2: DELETE + INSERT in single transaction (IDEMPOTENT)
        handler = VectorToPostGISHandler()
        result = handler.insert_chunk_idempotent(
            chunk=chunk,
            table_name=table_name,
            schema=schema,
            batch_id=batch_id
        )

        # GAP-008 FIX (16 DEC 2025): Calculate timing metrics
        elapsed = time.time() - start_time
        rows_per_second = result['rows_inserted'] / elapsed if elapsed > 0 else 0

        logger.info(
            f"[{job_id[:8]}] ⏱️ Chunk {chunk_index} complete: "
            f"deleted={result['rows_deleted']}, inserted={result['rows_inserted']} rows "
            f"in {elapsed:.2f}s ({rows_per_second:.0f} rows/sec)"
        )

        # Memory checkpoint 2: After DB insert (cleanup phase)
        log_memory_checkpoint(logger, "After DB insert (cleanup)",
                              context_id=job_id,
                              chunk_index=chunk_index,
                              rows_inserted=result['rows_inserted'],
                              elapsed_seconds=round(elapsed, 2))

        return {
            "success": True,
            "result": {
                'rows_inserted': result['rows_inserted'],
                'rows_deleted': result['rows_deleted'],
                'batch_id': batch_id,
                'chunk_index': chunk_index,
                'chunk_path': chunk_path,
                'table': f"{schema}.{table_name}",
                # GAP-008: Include timing in result for aggregation
                'elapsed_seconds': round(elapsed, 2),
                'rows_per_second': round(rows_per_second, 0)
            }
        }

    except psycopg.OperationalError as e:
        # Database connectivity or timeout issues
        error_msg = f"PostgreSQL connection error uploading chunk {chunk_index}: {e}"
        logger.error(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "error_type": "PostgreSQLConnectionError",
            "chunk_index": chunk_index,
            "chunk_path": chunk_path,
            "batch_id": batch_id,
            "table": f"{schema}.{table_name}",
            "retryable": True  # Connection issues are often transient
        }

    except psycopg.DataError as e:
        # Data validation errors (bad geometry, constraint violations)
        error_msg = f"Data validation error in chunk {chunk_index}: {e}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": error_msg,
            "error_type": "DataValidationError",
            "chunk_index": chunk_index,
            "chunk_path": chunk_path,
            "batch_id": batch_id,
            "table": f"{schema}.{table_name}",
            "retryable": False  # Data errors require investigation
        }

    except psycopg.IntegrityError as e:
        # Constraint violations (duplicate keys, foreign key issues)
        error_msg = f"Database constraint violation in chunk {chunk_index}: {e}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": error_msg,
            "error_type": "IntegrityError",
            "chunk_index": chunk_index,
            "chunk_path": chunk_path,
            "batch_id": batch_id,
            "table": f"{schema}.{table_name}",
            "retryable": False  # Constraint violations are permanent
        }

    except (MemoryError, OSError) as e:
        # GAP-005 FIX (15 DEC 2025): Memory/IO errors are often transient
        # OSError includes network issues, disk I/O errors, etc.
        error_msg = f"Resource error uploading chunk {chunk_index}: {e}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": error_msg,
            "error_type": type(e).__name__,
            "chunk_index": chunk_index,
            "chunk_path": chunk_path,
            "batch_id": batch_id,
            "table": f"{schema}.{table_name}",
            "retryable": True  # Resource errors often resolve on retry
        }

    except (TimeoutError, ConnectionError) as e:
        # GAP-005 FIX (15 DEC 2025): Network timeouts are transient
        error_msg = f"Network error uploading chunk {chunk_index}: {e}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": error_msg,
            "error_type": type(e).__name__,
            "chunk_index": chunk_index,
            "chunk_path": chunk_path,
            "batch_id": batch_id,
            "table": f"{schema}.{table_name}",
            "retryable": True  # Network issues are transient
        }

    except (ValueError, TypeError, KeyError) as e:
        # GAP-005 FIX (15 DEC 2025): Programming/data errors are permanent
        error_msg = f"Data/programming error in chunk {chunk_index}: {e}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": error_msg,
            "error_type": type(e).__name__,
            "chunk_index": chunk_index,
            "chunk_path": chunk_path,
            "batch_id": batch_id,
            "table": f"{schema}.{table_name}",
            "retryable": False  # Programming errors won't resolve on retry
        }

    except Exception as e:
        # GAP-005 FIX (15 DEC 2025): Unknown errors - default to retryable
        # Let Service Bus retry logic handle these - better to retry than fail permanently
        error_msg = f"Unexpected error uploading chunk {chunk_index}: {e}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": error_msg,
            "error_type": type(e).__name__,
            "chunk_index": chunk_index,
            "chunk_path": chunk_path,
            "batch_id": batch_id,
            "table": f"{schema}.{table_name}",
            "traceback": traceback.format_exc(),
            "retryable": True  # Unknown errors - retry cautiously via Service Bus
        }
