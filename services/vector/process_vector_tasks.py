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
from util_logger import LoggerFactory, ComponentType

# Component-specific logger
logger = LoggerFactory.create_logger(
    ComponentType.SERVICE,
    "process_vector_tasks"
)


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
    converter_params = parameters.get('converter_params', {})
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

    # Step 1: Download source file from Bronze zone (08 DEC 2025)
    blob_repo = BlobRepository.for_zone("bronze")
    file_data = blob_repo.read_blob_to_stream(container_name, blob_name)

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

    # Capture original CRS before reprojection (06 DEC 2025)
    # This is stored in table_metadata for data lineage tracking
    original_crs = str(gdf.crs) if gdf.crs else "unknown"
    logger.info(f"[{job_id[:8]}] Original CRS: {original_crs}")

    # Step 3: Validate and prepare GeoDataFrame (reprojects to EPSG:4326)
    handler = VectorToPostGISHandler()
    validated_gdf = handler.prepare_gdf(gdf, geometry_params=geometry_params)

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

    try:
        # Step 1: Load pickled chunk from blob storage (silver zone - intermediate data)
        blob_repo = BlobRepository.for_zone("silver")
        pickled_data = blob_repo.read_blob(config.vector_pickle_container, chunk_path)
        chunk = pickle.loads(pickled_data)

        # Step 2: DELETE + INSERT in single transaction (IDEMPOTENT)
        handler = VectorToPostGISHandler()
        result = handler.insert_chunk_idempotent(
            chunk=chunk,
            table_name=table_name,
            schema=schema,
            batch_id=batch_id
        )

        logger.info(
            f"[{job_id[:8]}] Chunk {chunk_index} complete: "
            f"deleted={result['rows_deleted']}, inserted={result['rows_inserted']}"
        )

        return {
            "success": True,
            "result": {
                'rows_inserted': result['rows_inserted'],
                'rows_deleted': result['rows_deleted'],
                'batch_id': batch_id,
                'chunk_index': chunk_index,
                'chunk_path': chunk_path,
                'table': f"{schema}.{table_name}"
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

    except Exception as e:
        # Unexpected errors
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
            "retryable": False  # Unknown errors require investigation
        }
