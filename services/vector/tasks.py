"""
Vector ETL Task Handlers.

Task handlers for the three stages of vector ETL workflow:
    1. load_vector_file: Load from blob storage and convert to GeoDataFrame
    2. validate_vector: Validate and prepare GeoDataFrame for PostGIS
    3. upload_vector_chunk: Upload chunk to PostGIS geo schema

Exports:
    load_vector_file: Load file from blob storage task
    validate_vector: Validate and prepare GeoDataFrame task
    upload_vector_chunk: Upload chunk to PostGIS task
"""

from typing import Dict, Any, List
import geopandas as gpd
from infrastructure.blob import BlobRepository
from util_logger import LoggerFactory, ComponentType
from .converters import (
    _convert_csv, _convert_geojson, _convert_geopackage,
    _convert_kml, _convert_kmz, _convert_shapefile
)

# Component-specific logger (09 DEC 2025)
logger = LoggerFactory.create_logger(ComponentType.SERVICE, "vector_tasks")

# Note: TaskRegistry will be imported when it exists
# from services.registry import TaskRegistry


# @TaskRegistry.register("load_vector_file")
def load_vector_file(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Task: Load vector file from blob storage to GeoDataFrame.

    Parameters:
        blob_name: str - Blob path in storage
        container_name: str - Container name (default: 'bronze')
        file_extension: str - File extension (determines converter)
        **converter_params: Format-specific parameters
            CSV: lat_name, lon_name OR wkt_column
            GPKG: layer_name
            KMZ/Shapefile: optional file name in archive

    Returns:
        gdf: str - Serialized GeoDataFrame (JSON)
        row_count: int - Number of rows
        geometry_types: List[str] - Geometry types in GDF
        bounds: List[float] - Bounding box [minx, miny, maxx, maxy]
        crs: str - Coordinate reference system
        blob_name: str - Source blob name
        container_name: str - Source container
    """
    blob_name = parameters["blob_name"]
    container_name = parameters.get("container_name", "bronze")
    file_extension = parameters["file_extension"].lower().lstrip('.')

    # Get file from blob storage using Bronze zone for input vectors (08 DEC 2025)
    blob_repo = BlobRepository.for_zone("bronze")
    file_data = blob_repo.read_blob_to_stream(container_name, blob_name)

    # Extract converter-specific parameters
    converter_params = {
        k: v for k, v in parameters.items()
        if k not in ['blob_name', 'container_name', 'file_extension']
    }

    # Dispatch to appropriate converter
    converters = {
        'csv': _convert_csv,
        'geojson': _convert_geojson,
        'json': _convert_geojson,
        'gpkg': _convert_geopackage,
        'kml': _convert_kml,
        'kmz': _convert_kmz,
        'shp': _convert_shapefile,
        'zip': _convert_shapefile  # Assume shapefile if .zip
    }

    if file_extension not in converters:
        raise ValueError(
            f"Unsupported file extension: '{file_extension}'. "
            f"Supported: {', '.join(converters.keys())}"
        )

    # Convert to GeoDataFrame
    gdf = converters[file_extension](file_data, **converter_params)

    # Return serialized result
    return {
        "gdf": gdf.to_json(),
        "row_count": len(gdf),
        "geometry_types": gdf.geometry.type.unique().tolist(),
        "bounds": gdf.total_bounds.tolist(),
        "crs": str(gdf.crs) if gdf.crs else None,
        "blob_name": blob_name,
        "container_name": container_name
    }


# @TaskRegistry.register("validate_vector")
def validate_vector(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Task: Validate and prepare GeoDataFrame for PostGIS.

    Parameters:
        gdf_serialized: str - JSON serialized GeoDataFrame

    Returns:
        validated_gdf: str - Serialized validated GeoDataFrame
        geometry_types: List[str] - Geometry types after validation
        row_count: int - Number of rows after validation
    """
    # Import here to avoid circular dependency
    from .postgis_handler import VectorToPostGISHandler

    gdf = gpd.read_file(parameters["gdf_serialized"])

    handler = VectorToPostGISHandler()
    validated_gdf = handler.prepare_gdf(gdf)

    return {
        "validated_gdf": validated_gdf.to_json(),
        "geometry_types": validated_gdf.geometry.type.unique().tolist(),
        "row_count": len(validated_gdf)
    }


# @TaskRegistry.register("upload_vector_chunk")
def upload_vector_chunk(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Task: Upload GeoDataFrame chunk to PostGIS.

    Parameters:
        chunk_data: str - JSON serialized GeoDataFrame chunk
        table_name: str - Target table name
        schema: str - Target schema (default: 'geo')

    Returns:
        rows_uploaded: int - Number of rows uploaded
        table: str - Full table name (schema.table)
    """
    # Import here to avoid circular dependency
    from .postgis_handler import VectorToPostGISHandler

    chunk = gpd.read_file(parameters["chunk_data"])
    table_name = parameters["table_name"]
    schema = parameters.get("schema", "geo")

    handler = VectorToPostGISHandler()
    handler.upload_chunk(chunk, table_name, schema)

    return {
        "rows_uploaded": len(chunk),
        "table": f"{schema}.{table_name}"
    }


# ============================================================================
# NEW TASKS: Two-Stage Fan-Out with Pickle Intermediate Storage
# ============================================================================

# @TaskRegistry.register("prepare_vector_chunks")
def prepare_vector_chunks(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 1 Task: Load, validate, chunk, and pickle GeoDataFrame.

    This task:
    1. Loads vector file from blob storage
    2. Validates and prepares GeoDataFrame
    3. Auto-calculates optimal chunk size (or uses provided)
    4. Splits into N chunks
    5. Pickles each chunk to temp blob storage
    6. Returns list of chunk paths for Stage 2 fan-out

    Parameters:
        job_id: str - Job ID for temp path naming
        blob_name: str - Source file path in blob storage
        container_name: str - Source container (default: config.storage.bronze.rasters)
        file_extension: str - File extension (csv, gpkg, etc.)
        table_name: str - Target PostGIS table name
        schema: str - Target schema (default: 'geo')
        chunk_size: int - Rows per chunk (None = auto-calculate)
        converter_params: dict - Format-specific converter parameters
        indexes: dict - Database index configuration (default: spatial only)
            spatial: bool - Create GIST index on geometry
            attributes: list - Column names for B-tree indexes
            temporal: list - Column names for DESC B-tree indexes

    Returns:
        chunk_paths: List[str] - Paths to pickled chunks in blob storage
        table_name: str - Target table name
        schema: str - Target schema
        total_rows: int - Total rows in source file
        chunk_count: int - Number of chunks created
        chunk_size_used: int - Actual chunk size used
    """
    import pickle
    import traceback
    from io import BytesIO
    from config import get_config

    config = get_config()

    job_id = parameters["job_id"]
    blob_name = parameters["blob_name"]
    # Use config for default container (bronze zone for input data)
    container_name = parameters.get("container_name", config.storage.bronze.rasters)
    file_extension = parameters["file_extension"]
    table_name = parameters["table_name"]
    schema = parameters.get("schema", "geo")
    chunk_size = parameters.get("chunk_size")
    converter_params = parameters.get("converter_params", {})
    geometry_params = parameters.get("geometry_params", {})  # NEW: Phase 2 (9 NOV 2025)

    logger.info(f"[{job_id[:8]}] Stage 1: prepare_vector_chunks starting for {blob_name}")

    # 1. Load vector file from blob storage using Bronze zone (08 DEC 2025)
    logger.info(f"[{job_id[:8]}] Step 1: Loading from Bronze zone {container_name}/{blob_name}")
    blob_repo = BlobRepository.for_zone("bronze")
    file_data = blob_repo.read_blob_to_stream(container_name, blob_name)
    logger.info(f"[{job_id[:8]}] Step 1 complete: File loaded from blob storage")

    # 2. Convert to GeoDataFrame
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
    logger.info(f"[{job_id[:8]}] Step 2 complete: Converted to GeoDataFrame with {len(gdf)} features")

    # 3. Validate, prepare, and optionally process geometries
    from .postgis_handler import VectorToPostGISHandler
    handler = VectorToPostGISHandler()
    validated_gdf = handler.prepare_gdf(gdf, geometry_params=geometry_params)
    logger.info(f"[{job_id[:8]}] Step 3 complete: Validated GeoDataFrame with {len(validated_gdf)} features")

    # 4. Calculate optimal chunk size and split
    chunks = handler.chunk_gdf(validated_gdf, chunk_size)
    actual_chunk_size = len(chunks[0]) if chunks else 0
    logger.info(f"[{job_id[:8]}] Step 4 complete: Split into {len(chunks)} chunks of ~{actual_chunk_size} rows each")

    # 5. Attach index configuration as chunk metadata (31 OCT 2025)
    # This allows upload_pickled_chunk to create indexes with proper config
    index_config = parameters.get("indexes", {
        "spatial": True,
        "attributes": [],
        "temporal": []
    })

    # 6. Pickle each chunk to Silver zone temp blob storage (09 DEC 2025)
    # IMPORTANT: Pickles go to Silver zone (intermediate processed data), not Bronze
    # Bronze = raw input files, Silver = processed/intermediate data
    logger.info(f"[{job_id[:8]}] Step 6: Writing {len(chunks)} pickles to Silver zone container '{config.vector_pickle_container}'")
    silver_repo = BlobRepository.for_zone("silver")

    chunk_paths: List[str] = []
    verified_pickles: List[Dict[str, Any]] = []
    pickle_errors: List[Dict[str, Any]] = []

    for i, chunk in enumerate(chunks):
        chunk_path = f"{config.vector_pickle_prefix}/{job_id}/chunk_{i}.pkl"

        # Attach index config as chunk metadata (persists through pickle)
        chunk._index_config = index_config

        try:
            # Pickle with protocol 5 (best compression)
            logger.debug(f"[{job_id[:8]}] Pickling chunk {i+1}/{len(chunks)} ({len(chunk)} rows)")
            pickled = pickle.dumps(chunk, protocol=5)
            pickle_size = len(pickled)
            logger.debug(f"[{job_id[:8]}] Chunk {i+1} pickled: {pickle_size:,} bytes")

            # Write to Silver zone blob storage (intermediate data)
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

    # 7. CRITICAL VALIDATION: Ensure ALL pickles were created successfully (09 DEC 2025)
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

    # 8. Final verification - check all pickles exist in blob storage
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
        f"{len(validated_gdf)} total rows, ready for Stage 2 fan-out"
    )

    return {
        "success": True,
        "result": {
            'chunk_paths': chunk_paths,
            'table_name': table_name,
            'schema': schema,
            'total_rows': len(validated_gdf),
            'chunk_count': len(chunks),
            'chunk_size_used': actual_chunk_size,
            'source_file': blob_name,
            'geometry_types': validated_gdf.geometry.type.unique().tolist(),
            'pickle_verification': {
                'all_verified': True,
                'pickle_count': len(verified_pickles),
                'total_pickle_bytes': sum(p['pickle_bytes'] for p in verified_pickles),
                'total_blob_bytes': sum(p['blob_bytes'] for p in verified_pickles)
            }
        }
    }


# @TaskRegistry.register("upload_pickled_chunk")
def upload_pickled_chunk(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 2 Task: Load pickled chunk and upload to PostGIS.

    This task:
    1. Loads pickled GeoDataFrame chunk from blob storage
    2. Uploads chunk to PostGIS
    3. Deletes temp pickle file

    Designed to stay under Azure Functions timeout (each chunk ~30-60 seconds).

    Parameters:
        chunk_path: str - Path to pickled chunk in blob storage
        table_name: str - Target PostGIS table name
        schema: str - Target schema
        chunk_index: int - Chunk number (for logging)

    Returns:
        rows_uploaded: int - Number of rows uploaded
        chunk_path: str - Chunk path (for tracking)
        chunk_index: int - Chunk number
    """
    import pickle
    from config import get_config

    config = get_config()

    chunk_path = parameters["chunk_path"]
    table_name = parameters["table_name"]
    schema = parameters.get("schema", "geo")
    chunk_index = parameters.get("chunk_index", 0)

    # 1. Load pickled chunk from blob storage (silver zone - intermediate data)
    blob_repo = BlobRepository.for_zone("silver")
    pickled_data = blob_repo.read_blob(config.vector_pickle_container, chunk_path)
    chunk = pickle.loads(pickled_data)

    # 2. Insert data into PostGIS (table already created in Stage 1)
    # DEADLOCK FIX (17 OCT 2025): Use insert_features_only() to skip table creation
    # Table was created once in jobs/ingest_vector.py before Stage 2 task creation
    # QA HARDENING (12 NOV 2025): Add exception handling for PostgreSQL errors
    from .postgis_handler import VectorToPostGISHandler
    import psycopg
    import traceback
    from util_logger import LoggerFactory, ComponentType

    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "upload_pickled_chunk")
    handler = VectorToPostGISHandler()

    try:
        handler.insert_features_only(chunk, table_name, schema)

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
            "table": f"{schema}.{table_name}",
            "traceback": traceback.format_exc(),
            "retryable": False  # Unknown errors require investigation
        }

    # 3. Note: Pickle cleanup handled by timer function
    # Pickles persist in {container}/{prefix}/{job_id}/ for audit/retry
    # Timer job will clean up old pickles (>24 hours)

    # SUCCESS PATH (only reached if no exception)
    return {
        "success": True,
        "result": {
            'rows_uploaded': len(chunk),
            'chunk_path': chunk_path,
            'chunk_index': chunk_index,
            'table': f"{schema}.{table_name}",
            'pickle_retained': True  # For timer cleanup tracking
        }
    }
