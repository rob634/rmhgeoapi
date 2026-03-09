# ============================================================================
# CLAUDE CONTEXT - VECTOR MULTI-SOURCE DOCKER JOB
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Jobs - Multi-file and multi-layer GPKG vector ingestion
# PURPOSE: N sources in -> N PostGIS tables out, each with own TiPG endpoint
# CREATED: 08 MAR 2026
# EXPORTS: VectorMultiSourceDockerJob
# DEPENDENCIES: jobs.base, jobs.mixins
# ============================================================================
"""
VectorMultiSourceDockerJob -- Multi-source vector ETL.

Supports two modes (mutually exclusive):
    P1 (multi-file): blob_list = ["roads.gpkg", "bridges.gpkg"]
        -> one table per file
    P3 (multi-layer GPKG): blob_name + layer_names = ["transport", "buildings"]
        -> one table per GPKG layer

Each source goes through the same validation/upload pipeline as single-file
vector_docker_etl. Geometry-type splitting applies per source.

Table naming: {base_table_name}_{source_suffix}_ord{N}
    base = user's table_name or {dataset_id}_{resource_id}
    source_suffix = filename stem (P1) or layer name (P3)

Design doc: docs/plans/2026-03-08-multi-source-vector-design.md

Exports:
    VectorMultiSourceDockerJob
"""

import os
from typing import List, Dict, Any, Optional
from pathlib import PurePosixPath

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class VectorMultiSourceDockerJob(JobBaseMixin, JobBase):  # Mixin FIRST!
    """
    Multi-source vector ETL job.

    Single stage, single task -- the handler loops internally over sources.
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION
    # ========================================================================
    job_type = "vector_multi_source_docker"
    description = "Multi-source vector ETL: N files or N GPKG layers -> N PostGIS tables"

    # ETL linkage
    reversed_by = "unpublish_vector_multi_source"

    # Single consolidated stage
    stages = [
        {
            "number": 1,
            "name": "process_sources",
            "task_type": "vector_multi_source_complete",
            "parallelism": "single"
        }
    ]

    # Expected checkpoints per source (dynamic -- handler emits per source)
    validation_checkpoints: List[Dict[str, Any]] = [
        {"name": "sources_validated", "label": "Validate sources", "phase": "validate"},
        {"name": "processing_started", "label": "Begin processing", "phase": "load"},
        {"name": "all_sources_complete", "label": "All sources processed", "phase": "upload"},
    ]

    # ========================================================================
    # PARAMETER SCHEMA
    # ========================================================================
    parameters_schema = {
        # === Source (one of two modes) ===
        'blob_list': {
            'type': 'list',
            'default': None,
            'description': 'P1: List of source file paths in container'
        },
        'blob_name': {
            'type': 'str',
            'default': None,
            'description': 'P3: Single GPKG file path in container'
        },
        'layer_names': {
            'type': 'list',
            'default': None,
            'description': 'P3: GPKG layer names to extract as separate tables'
        },
        'file_extension': {
            'type': 'str',
            'required': True,
            'allowed': ['csv', 'geojson', 'json', 'gpkg', 'kml', 'kmz', 'shp', 'zip'],
            'description': 'Source file format (all files must share same format for P1)'
        },
        'container_name': {
            'type': 'str',
            'default': None,
            'description': 'Source blob container (default: bronze.vectors from config)'
        },

        # === Target ===
        'base_table_name': {
            'type': 'str',
            'required': True,
            'description': 'Base prefix for generated table names'
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

        # === Geometry (CSV only) ===
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

        # === DDH Platform Identifiers ===
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
        'release_id': {
            'type': 'str',
            'default': None,
            'description': 'Release ID for release_tables linkage'
        },
        'version_ordinal': {
            'type': 'int',
            'default': None,
            'description': 'Version ordinal for table naming (ord{N})'
        },
        'stac_item_id': {
            'type': 'str',
            'default': None,
            'description': 'Pre-generated STAC item ID'
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

        # === Processing ===
        'chunk_size': {
            'type': 'int',
            'default': 100000,
            'min': 100,
            'max': 500000,
            'description': 'Rows per chunk for batch upload'
        },
    }

    # ========================================================================
    # PRE-FLIGHT RESOURCE VALIDATORS
    # ========================================================================
    resource_validators = [
        {
            'type': 'multi_source_mode',
            'blob_list_param': 'blob_list',
            'blob_name_param': 'blob_name',
            'layer_names_param': 'layer_names',
            'file_extension_param': 'file_extension',
            'error': (
                "Invalid multi-source configuration. Choose ONE mode:\n"
                "  P1 (multi-file): provide 'blob_list' (list of file paths)\n"
                "  P3 (multi-layer GPKG): provide 'blob_name' (single .gpkg) + 'layer_names'\n"
                "Cannot combine blob_list with layer_names."
            )
        },
        {
            'type': 'source_count_limit',
            'blob_list_param': 'blob_list',
            'layer_names_param': 'layer_names',
            'error': 'Source count exceeds MAX_VECTOR_SOURCES limit.'
        },
    ]

    # ========================================================================
    # TASK CREATION
    # ========================================================================
    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: Dict[str, Any],
        job_id: str,
        previous_results: Optional[List[Dict]] = None
    ) -> List[Dict[str, Any]]:
        """Generate single task for the consolidated handler."""
        from core.task_id import generate_deterministic_task_id
        from config import get_config

        if stage != 1:
            return []

        config = get_config()
        container_name = job_params.get('container_name') or config.storage.bronze.vectors
        task_id = generate_deterministic_task_id(job_id, 1, "vector_multi_source")

        # Pass all relevant params through to handler
        task_params = {
            # Source
            'blob_list': job_params.get('blob_list'),
            'blob_name': job_params.get('blob_name'),
            'layer_names': job_params.get('layer_names'),
            'file_extension': job_params.get('file_extension'),
            'container_name': container_name,
            # Target
            'base_table_name': job_params.get('base_table_name'),
            'schema': job_params.get('schema', 'geo'),
            'overwrite': job_params.get('overwrite', False),
            # Geometry
            'lat_name': job_params.get('lat_name'),
            'lon_name': job_params.get('lon_name'),
            'wkt_column': job_params.get('wkt_column'),
            'converter_params': job_params.get('converter_params') or {},
            # DDH identifiers
            'dataset_id': job_params.get('dataset_id'),
            'resource_id': job_params.get('resource_id'),
            'version_id': job_params.get('version_id'),
            'release_id': job_params.get('release_id'),
            'version_ordinal': job_params.get('version_ordinal'),
            'stac_item_id': job_params.get('stac_item_id'),
            # Metadata
            'title': job_params.get('title'),
            'description': job_params.get('description'),
            'tags': job_params.get('tags'),
            'access_level': job_params.get('access_level'),
            # Processing
            'chunk_size': job_params.get('chunk_size', 100000),
            'job_id': job_id,
        }

        return [{
            'task_id': task_id,
            'task_type': 'vector_multi_source_complete',
            'parameters': task_params,
        }]

    # ========================================================================
    # FINALIZATION
    # ========================================================================
    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """Aggregate results from multi-source processing."""
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "VectorMultiSourceDockerJob.finalize_job"
        )

        if not context or not context.task_results:
            return {"job_type": "vector_multi_source_docker", "status": "completed"}

        task_result = context.task_results[0]
        result_data = getattr(task_result, 'result_data', {}) or {}

        tables_created = result_data.get('tables', [])
        table_names = [t.get('table_name') for t in tables_created]
        total_rows = sum(t.get('feature_count', 0) for t in tables_created)

        logger.info(
            f"Multi-source vector job {context.job_id[:16]}... completed -- "
            f"{len(tables_created)} tables, {total_rows} total rows"
        )

        return {
            "job_type": "vector_multi_source_docker",
            "status": "completed",
            "table_names": table_names,
            "tables_created": len(tables_created),
            "total_rows": total_rows,
            "tables": tables_created,
        }
