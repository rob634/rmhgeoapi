# ============================================================================
# VECTOR DOCKER ETL JOB
# ============================================================================
# STATUS: Jobs - V0.8 Docker-based vector ETL
# PURPOSE: Single-handler vector ETL with checkpoint progress tracking
# CREATED: 24 JAN 2026
# LAST_REVIEWED: 24 JAN 2026
# ============================================================================
"""
Vector Docker ETL Job.

V0.8 Docker-based vector ETL pipeline with checkpoint progress tracking.
Replaces the 3-stage Function App workflow with a single consolidated handler
that eliminates pickle serialization overhead and uses persistent connection pooling.

Benefits over Function App workflow:
    - No timeout (long-running Docker process)
    - No pickle serialization (direct memory → DB)
    - Connection pool reuse (persistent)
    - Large file support (streaming from mount)
    - Fine-grained checkpoint progress

Exports:
    VectorDockerETLJob: Job class for Docker vector ETL
"""

from typing import Dict, Any, List, Optional
import logging

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin
from config.defaults import STACDefaults
from util_logger import LoggerFactory, ComponentType

# Component-specific logger
logger = LoggerFactory.create_logger(
    ComponentType.CONTROLLER,
    "vector_docker_etl_job"
)


class VectorDockerETLJob(JobBaseMixin, JobBase):
    """
    Docker-based vector ETL with checkpoint progress tracking.

    Single consolidated handler replaces 3-stage Function App workflow.
    Uses connection pooling and eliminates pickle serialization.

    Checkpoint Phases:
        validated      - Source validated, GeoDataFrame loaded
        table_created  - PostGIS table + metadata created
        style_created  - Default style registered
        chunk_N        - Chunk N uploaded (N = 0, 1, 2...)
        stac_created   - STAC item registered
        complete       - Final result

    Resume Behavior:
        On restart, reads last checkpoint and resumes from that point.
        Chunk uploads are idempotent (DELETE batch_id before INSERT).
    """

    # Job metadata
    job_type: str = "vector_docker_etl"
    description: str = "Docker vector ETL with connection pooling and checkpoints"

    # Single stage - all work in one handler with checkpoints
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "process_complete",
            "task_type": "vector_docker_complete",
            "parallelism": "single",
            "description": "Consolidated vector ETL with checkpoint progress"
        }
    ]

    # Declarative validation schema
    parameters_schema = {
        # === Source ===
        'blob_name': {
            'type': 'str',
            'required': True,
            'description': 'Source file path in container'
        },
        'file_extension': {
            'type': 'str',
            'required': True,
            'allowed': ['csv', 'geojson', 'json', 'gpkg', 'kml', 'kmz', 'shp', 'zip'],
            'description': 'Source file format'
        },
        'container_name': {
            'type': 'str',
            'default': None,
            'description': 'Source blob container (default: bronze-vectors from config)'
        },

        # === Target ===
        'table_name': {
            'type': 'str',
            'required': True,
            'description': 'Target PostGIS table name'
        },
        'schema': {
            'type': 'str',
            'default': 'geo',
            'description': 'Target PostGIS schema'
        },
        'overwrite': {
            'type': 'bool',
            'default': False,
            'description': 'If true, allows overwriting existing tables'
        },

        # === Geometry ===
        'lat_name': {
            'type': 'str',
            'default': None,
            'description': 'CSV latitude column name'
        },
        'lon_name': {
            'type': 'str',
            'default': None,
            'description': 'CSV longitude column name'
        },
        'wkt_column': {
            'type': 'str',
            'default': None,
            'description': 'CSV WKT geometry column name'
        },
        'converter_params': {
            'type': 'dict',
            'default': {},
            'description': 'File-specific conversion parameters'
        },
        'geometry_params': {
            'type': 'dict',
            'default': {},
            'description': 'Geometry validation and processing parameters'
        },

        # === Column Mapping ===
        'column_mapping': {
            'type': 'dict',
            'default': None,
            'description': 'Column rename mapping {source_name: target_name}'
        },
        'temporal_property': {
            'type': 'str',
            'default': None,
            'description': 'Column name for temporal extent auto-detection'
        },

        # === Metadata ===
        'title': {
            'type': 'str',
            'default': None,
            'description': 'User-friendly display name'
        },
        'description': {
            'type': 'str',
            'default': None,
            'description': 'Full dataset description'
        },
        'attribution': {
            'type': 'str',
            'default': None,
            'description': 'Data source attribution'
        },
        'license': {
            'type': 'str',
            'default': None,
            'description': 'SPDX license identifier'
        },
        'keywords': {
            'type': 'str',
            'default': None,
            'description': 'Comma-separated tags'
        },

        # === DDH Platform Identifiers (passthrough) ===
        'dataset_id': {
            'type': 'str',
            'default': None,
            'description': 'DDH dataset identifier'
        },
        'resource_id': {
            'type': 'str',
            'default': None,
            'description': 'DDH resource identifier'
        },
        'version_id': {
            'type': 'str',
            'default': None,
            'description': 'DDH version identifier'
        },
        'stac_item_id': {
            'type': 'str',
            'default': None,
            'description': 'Pre-generated STAC item ID'
        },
        'service_name': {
            'type': 'str',
            'default': None,
            'description': 'DDH service name'
        },
        'tags': {
            'type': 'list',
            'default': None,
            'description': 'DDH tags'
        },
        'access_level': {
            'type': 'str',
            'default': None,
            'description': 'DDH access level'
        },

        # === Style Parameters (V0.8+ - Future) ===
        'style': {
            'type': 'dict',
            'default': None,
            'description': 'Style parameters for OGC Styles (fill_color, stroke_color, etc.)'
        },

        # === Processing ===
        'chunk_size': {
            'type': 'int',
            'default': 20000,
            'min': 100,
            'max': 500000,
            'description': 'Rows per chunk for batch upload'
        },
        'indexes': {
            'type': 'dict',
            'default': {'spatial': True, 'attributes': [], 'temporal': []},
            'description': 'Database index configuration'
        },
        'create_tile_view': {
            'type': 'bool',
            'default': False,
            'description': 'Create tile-optimized materialized view'
        },
        'max_tile_vertices': {
            'type': 'int',
            'default': 256,
            'min': 64,
            'max': 2048,
            'description': 'Max vertices per polygon in tile view'
        },

        # === Internal (set by platform) ===
        '_platform_job_id': {
            'type': 'str',
            'default': None,
            'description': 'Platform request ID for artifact tracking'
        },
    }

    # Pre-flight resource validation
    resource_validators = [
        {
            'type': 'blob_exists',
            'container_param': 'container_name',
            'blob_param': 'blob_name',
            'zone': 'bronze',
            'default_container': 'bronze.vectors',
            'error': 'Source file does not exist in Bronze storage.'
        },
        {
            'type': 'table_not_exists',
            'table_param': 'table_name',
            'schema_param': 'schema',
            'default_schema': 'geo',
            'allow_overwrite_param': 'overwrite',
            'error': "Table already exists. Use 'overwrite': true to replace."
        },
        {
            'type': 'csv_geometry_params',
            'file_extension_param': 'file_extension',
            'lat_param': 'lat_name',
            'lon_param': 'lon_name',
            'wkt_param': 'wkt_column',
            'converter_params_field': 'converter_params',
            'error': (
                "CSV files require geometry column parameters. Provide either:\n"
                "  • 'lat_name' AND 'lon_name' for point geometry\n"
                "  • OR 'wkt_column' for WKT geometry strings"
            )
        }
    ]

    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: Dict[str, Any],
        job_id: str,
        previous_results: Optional[List[Dict]] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate task parameters for the single consolidated stage.

        Args:
            stage: Stage number (always 1 for this job)
            job_params: Validated job parameters
            job_id: Job ID for task ID generation
            previous_results: Not used (single stage)

        Returns:
            List with single task dict
        """
        from core.task_id import generate_deterministic_task_id
        from config import get_config

        if stage != 1:
            return []

        config = get_config()

        # Resolve container name from config if not provided
        container_name = job_params.get('container_name') or config.storage.bronze.vectors

        task_id = generate_deterministic_task_id(job_id, 1, "vector_docker")

        return [{
            'task_id': task_id,
            'task_type': 'vector_docker_complete',
            'parameters': {
                # Job context
                'job_id': job_id,

                # Source
                'blob_name': job_params['blob_name'],
                'container_name': container_name,
                'file_extension': job_params['file_extension'],

                # Target
                'table_name': job_params['table_name'],
                'schema': job_params.get('schema', 'geo'),
                'overwrite': job_params.get('overwrite', False),

                # Geometry
                'lat_name': job_params.get('lat_name'),
                'lon_name': job_params.get('lon_name'),
                'wkt_column': job_params.get('wkt_column'),
                'converter_params': job_params.get('converter_params', {}),
                'geometry_params': job_params.get('geometry_params', {}),

                # Column mapping
                'column_mapping': job_params.get('column_mapping'),
                'temporal_property': job_params.get('temporal_property'),

                # Metadata
                'title': job_params.get('title'),
                'description': job_params.get('description'),
                'attribution': job_params.get('attribution'),
                'license': job_params.get('license'),
                'keywords': job_params.get('keywords'),

                # DDH identifiers
                'dataset_id': job_params.get('dataset_id'),
                'resource_id': job_params.get('resource_id'),
                'version_id': job_params.get('version_id'),
                'stac_item_id': job_params.get('stac_item_id'),
                'service_name': job_params.get('service_name'),
                'tags': job_params.get('tags'),
                'access_level': job_params.get('access_level'),

                # Style
                'style': job_params.get('style'),

                # Processing
                'chunk_size': job_params.get('chunk_size', 20000),
                'indexes': job_params.get('indexes', {'spatial': True, 'attributes': [], 'temporal': []}),
                'create_tile_view': job_params.get('create_tile_view', False),
                'max_tile_vertices': job_params.get('max_tile_vertices', 256),

                # Platform tracking
                '_platform_job_id': job_params.get('_platform_job_id'),
            }
        }]

    @staticmethod
    def finalize_job(context) -> Dict[str, Any]:
        """
        Extract final results from the single completed task.

        The handler returns comprehensive results including checkpoint history,
        so finalize just extracts and formats them.

        Args:
            context: JobExecutionContext with task results

        Returns:
            Job result dict with OGC Features API URLs
        """
        from core.models import TaskStatus
        from config import get_config

        task_results = context.task_results
        params = context.parameters
        config = get_config()

        # Single task - extract its result
        if not task_results:
            return {
                "job_type": "vector_docker_etl",
                "success": False,
                "error": "No task results found"
            }

        task = task_results[0]
        task_result = task.result_data or {}

        # Check if task completed successfully
        if task.status != TaskStatus.COMPLETED:
            return {
                "job_type": "vector_docker_etl",
                "success": False,
                "error": task_result.get("error", "Task did not complete"),
                "last_checkpoint": task_result.get("last_checkpoint")
            }

        # Extract result from handler
        result_data = task_result.get("result", task_result)

        # Get table info for URL generation
        table_name = result_data.get("table_name") or params.get("table_name")
        schema = result_data.get("schema") or params.get("schema", "geo")

        # Generate URLs
        ogc_features_url = config.generate_ogc_features_url(table_name)
        viewer_url = config.generate_vector_viewer_url(table_name)
        vector_tile_urls = config.generate_vector_tile_urls(table_name, schema)

        return {
            "job_type": "vector_docker_etl",
            "success": True,

            # Table info
            "table_name": table_name,
            "schema": schema,
            "total_rows": result_data.get("total_rows", 0),
            "geometry_type": result_data.get("geometry_type"),
            "srid": result_data.get("srid"),

            # STAC info
            "stac_item_id": result_data.get("stac_item_id"),
            "collection_id": result_data.get("collection_id", STACDefaults.VECTOR_COLLECTION),

            # Style info
            "style_id": result_data.get("style_id", "default"),

            # Processing stats
            "chunks_uploaded": result_data.get("chunks_uploaded", 0),
            "checkpoint_count": result_data.get("checkpoint_count", 0),

            # URLs
            "ogc_features_url": ogc_features_url,
            "viewer_url": viewer_url,
            "vector_tiles": {
                "tilejson_url": vector_tile_urls.get("tilejson"),
                "tiles_url": vector_tile_urls.get("tiles"),
                "viewer_url": vector_tile_urls.get("viewer"),
            },

            # Source info
            "blob_name": params.get("blob_name"),
            "file_extension": params.get("file_extension"),
            "container_name": params.get("container_name"),

            # Execution mode
            "execution_mode": "docker",
            "connection_pooling": True,
        }
