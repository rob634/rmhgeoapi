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
            'container_name': str,   # Bronze container (default: rmhazuregeobronze)
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
    container_name = parameters.get('container_name', 'rmhazuregeobronze')
    file_extension = parameters['file_extension'].lower().lstrip('.')
    table_name = parameters['table_name']
    schema = parameters.get('schema', 'geo')
    chunk_size = parameters.get('chunk_size')
    converter_params = parameters.get('converter_params', {})
    geometry_params = parameters.get('geometry_params', {})
    indexes = parameters.get('indexes', {'spatial': True, 'attributes': [], 'temporal': []})

    logger.info(f"[{job_id[:8]}] Stage 1: Preparing vector data from {blob_name}")

    # Step 1: Download source file
    blob_repo = BlobRepository.instance()
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

    # Step 3: Validate and prepare GeoDataFrame
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

    # Step 4: Create table with etl_batch_id column (IDEMPOTENT - IF NOT EXISTS)
    handler.create_table_with_batch_tracking(
        table_name=table_name,
        schema=schema,
        gdf=validated_gdf,
        indexes=indexes
    )
    logger.info(f"[{job_id[:8]}] Created table {schema}.{table_name} with etl_batch_id tracking")

    # Step 5: Calculate optimal chunk size and split
    chunks = handler.chunk_gdf(validated_gdf, chunk_size)
    actual_chunk_size = len(chunks[0]) if chunks else 0

    # Step 6: Pickle each chunk to blob storage (IDEMPOTENT - overwrite=True)
    chunk_paths = []
    for i, chunk in enumerate(chunks):
        chunk_path = f"{config.vector_pickle_prefix}/{job_id}/chunk_{i}.pkl"

        # Pickle with protocol 5 (best compression)
        pickled = pickle.dumps(chunk, protocol=5)

        # Write to blob storage with overwrite=True (IDEMPOTENT)
        blob_repo.write_blob(config.vector_pickle_container, chunk_path, pickled)

        chunk_paths.append(chunk_path)
        logger.info(f"[{job_id[:8]}] Pickled chunk {i+1}/{len(chunks)}: {len(chunk)} rows")

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
        'source_file': blob_name
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
        # Step 1: Load pickled chunk from blob storage
        blob_repo = BlobRepository.instance()
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
