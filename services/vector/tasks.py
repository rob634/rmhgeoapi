# ============================================================================
# CLAUDE CONTEXT - VECTOR ETL TASK HANDLERS
# ============================================================================
# PURPOSE: Task handlers for vector ETL workflow (load, validate, upload)
# EXPORTS: load_vector_file, validate_vector, upload_vector_chunk
# INTERFACES: TaskRegistry (decorator registration pattern)
# PYDANTIC_MODELS: Uses Dict[str, Any] for parameters and returns
# DEPENDENCIES: geopandas, infrastructure.blob.BlobRepository, services.vector.converters
# SOURCE: Called by CoreMachine during task execution
# SCOPE: Service layer - task execution logic
# VALIDATION: Format validation, GeoDataFrame validation
# PATTERNS: TaskRegistry decorator pattern (when registry exists)
# ENTRY_POINTS: Registered with @TaskRegistry.register() decorator
# INDEX:
#   - load_vector_file (line 35): Load file from blob storage and convert to GDF
#   - validate_vector (line 90): Validate and prepare GeoDataFrame
#   - upload_vector_chunk (line 110): Upload GDF chunk to PostGIS
# ============================================================================

"""
Vector ETL task handlers using TaskRegistry.

These task handlers are registered with TaskRegistry and executed by CoreMachine.
They implement the three stages of vector ETL:
1. load_vector_file: Load from blob storage and convert to GeoDataFrame
2. validate_vector: Validate and prepare GeoDataFrame for PostGIS
3. upload_vector_chunk: Upload chunk to PostGIS geo schema
"""

from typing import Dict, Any
import geopandas as gpd
from infrastructure.blob import BlobRepository
from .converters import (
    _convert_csv, _convert_geojson, _convert_geopackage,
    _convert_kml, _convert_kmz, _convert_shapefile
)

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

    # Get file from blob storage using BlobRepository singleton
    blob_repo = BlobRepository.instance()
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
        container_name: str - Source container (default: 'rmhazuregeobronze')
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
    from io import BytesIO
    from config import get_config

    config = get_config()

    job_id = parameters["job_id"]
    blob_name = parameters["blob_name"]
    # TODO: Parameterize via env var instead of hardcoded default
    container_name = parameters.get("container_name", "rmhazuregeobronze")
    file_extension = parameters["file_extension"]
    table_name = parameters["table_name"]
    schema = parameters.get("schema", "geo")
    chunk_size = parameters.get("chunk_size")
    converter_params = parameters.get("converter_params", {})
    geometry_params = parameters.get("geometry_params", {})  # NEW: Phase 2 (9 NOV 2025)

    # 1. Load vector file from blob storage
    blob_repo = BlobRepository.instance()
    file_data = blob_repo.read_blob_to_stream(container_name, blob_name)

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

    # 3. Validate, prepare, and optionally process geometries
    from .postgis_handler import VectorToPostGISHandler
    handler = VectorToPostGISHandler()
    validated_gdf = handler.prepare_gdf(gdf, geometry_params=geometry_params)

    # 4. Calculate optimal chunk size and split
    chunks = handler.chunk_gdf(validated_gdf, chunk_size)
    actual_chunk_size = len(chunks[0]) if chunks else 0

    # 5. Attach index configuration as chunk metadata (31 OCT 2025)
    # This allows upload_pickled_chunk to create indexes with proper config
    index_config = parameters.get("indexes", {
        "spatial": True,
        "attributes": [],
        "temporal": []
    })

    # 6. Pickle each chunk to temp blob storage
    chunk_paths = []
    for i, chunk in enumerate(chunks):
        chunk_path = f"{config.vector_pickle_prefix}/{job_id}/chunk_{i}.pkl"

        # Attach index config as chunk metadata (persists through pickle)
        chunk._index_config = index_config

        # Pickle with protocol 5 (best compression)
        pickled = pickle.dumps(chunk, protocol=5)

        # Write to blob storage (configured container for intermediate data)
        blob_repo.write_blob(config.vector_pickle_container, chunk_path, pickled)

        chunk_paths.append(chunk_path)

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
            'geometry_types': validated_gdf.geometry.type.unique().tolist()
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

    # 1. Load pickled chunk from blob storage
    blob_repo = BlobRepository.instance()
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
