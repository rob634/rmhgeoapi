"""
Process Vector Job.

Idempotent vector ETL workflow using DELETE+INSERT pattern.

Three-stage workflow:
    - Stage 1: Load, validate, chunk, create table
    - Stage 2: Fan-out DELETE+INSERT for each chunk
    - Stage 3: Create STAC record

Exports:
    ProcessVectorJob: Job class for vector ETL processing
"""

from typing import Dict, Any, List, Optional
import logging

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin
from config.defaults import STACDefaults
from config import get_config
from util_logger import LoggerFactory, ComponentType

# Component-specific logger
logger = LoggerFactory.create_logger(
    ComponentType.CONTROLLER,
    "process_vector_job"
)


class ProcessVectorJob(JobBaseMixin, JobBase):  # Mixin FIRST for correct MRO!
    """
    Idempotent vector ETL workflow.

    Replaces ingest_vector with built-in idempotency at every stage:
    - Stage 1: Pickle uploads with overwrite=True, table IF NOT EXISTS
    - Stage 2: DELETE+INSERT pattern with etl_batch_id
    - Stage 3: STAC item_exists check before insert

    No retry flags, no optional idempotency - it's always idempotent.
    """

    # Job metadata
    job_type: str = "process_vector"
    description: str = "Idempotent vector ETL: Bronze -> PostGIS + STAC"

    # Declarative validation schema (JobBaseMixin handles validation)
    parameters_schema = {
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
        'table_name': {
            'type': 'str',
            'required': True,
            'description': 'Target PostGIS table name'
        },
        'container_name': {
            'type': 'str',
            'default': None,  # Resolved at runtime via config.storage.bronze.vectors
            'description': 'Source blob container (default: bronze-vectors from config)'
        },
        'schema': {
            'type': 'str',
            'default': 'geo',
            'description': 'Target PostGIS schema'
        },
        'chunk_size': {
            'type': 'int',
            'default': None,
            'min': 100,
            'max': 500000,
            'description': 'Rows per chunk for parallel upload (None = auto-calculate)'
        },
        'converter_params': {
            'type': 'dict',
            'default': {},
            'description': 'File-specific params (alternative to top-level lat_name/lon_name)'
        },
        # CSV-specific geometry column parameters (GAP-008a - 15 DEC 2025)
        # Required for CSV files - must provide (lat_name AND lon_name) OR wkt_column
        'lat_name': {
            'type': 'str',
            'default': None,
            'description': 'CSV latitude column name (required with lon_name for point geometry)'
        },
        'lon_name': {
            'type': 'str',
            'default': None,
            'description': 'CSV longitude column name (required with lat_name for point geometry)'
        },
        'wkt_column': {
            'type': 'str',
            'default': None,
            'description': 'CSV WKT geometry column name (alternative to lat_name/lon_name)'
        },
        'geometry_params': {
            'type': 'dict',
            'default': {},
            'description': 'Geometry validation and processing parameters'
        },
        'indexes': {
            'type': 'dict',
            'default': {'spatial': True, 'attributes': [], 'temporal': []},
            'description': 'Database index configuration'
        },
        'overwrite': {
            'type': 'bool',
            'default': False,
            'description': 'If true, allows overwriting existing tables (DELETE+INSERT for existing data)'
        },
        # User-provided metadata fields (09 DEC 2025)
        # These populate geo.table_metadata which is the source of truth for OGC/STAC
        'title': {
            'type': 'str',
            'default': None,
            'description': 'User-friendly display name for the dataset'
        },
        'description': {
            'type': 'str',
            'default': None,
            'description': 'Full dataset description'
        },
        'attribution': {
            'type': 'str',
            'default': None,
            'description': 'Data source attribution (e.g., "Natural Earth - naturalearthdata.com")'
        },
        'license': {
            'type': 'str',
            'default': None,
            'description': 'SPDX license identifier (e.g., CC-BY-4.0, MIT, CC0-1.0)'
        },
        'keywords': {
            'type': 'str',
            'default': None,
            'description': 'Comma-separated tags for discoverability (e.g., "boundaries,admin,political")'
        },
        'temporal_property': {
            'type': 'str',
            'default': None,
            'description': 'Column name containing date data for temporal extent auto-detection'
        }
    }

    # Pre-flight resource validation (28 NOV 2025, updated 09 DEC 2025)
    # Validates resources BEFORE job creation - fail fast at HTTP 400!
    # Prevents wasted job records and queue messages for non-existent files or table conflicts.
    resource_validators = [
        {
            'type': 'blob_exists',
            'container_param': 'container_name',
            'blob_param': 'blob_name',
            'zone': 'bronze',  # Source files are in Bronze tier
            'default_container': 'bronze.vectors',  # Resolves to config.storage.bronze.vectors if not provided
            'error': 'Source file does not exist in Bronze storage. Check blob_name and container_name.'
        },
        {
            # Prevent overwriting existing tables (09 DEC 2025)
            # If table exists, job submission fails with 400 Bad Request
            # To re-ingest to same table, submit with overwrite=true
            'type': 'table_not_exists',
            'table_param': 'table_name',
            'schema_param': 'schema',
            'default_schema': 'geo',
            'allow_overwrite_param': 'overwrite',
            'error': "Table already exists in geo schema. Use 'overwrite': true to replace existing data, or choose a different table_name."
        },
        {
            # GAP-008a FIX (15 DEC 2025): Validate CSV geometry params at submission
            # CSV files MUST provide lat/lon OR wkt column names - fail fast!
            'type': 'csv_geometry_params',
            'file_extension_param': 'file_extension',
            'lat_param': 'lat_name',
            'lon_param': 'lon_name',
            'wkt_param': 'wkt_column',
            'converter_params_field': 'converter_params',
            'error': (
                "CSV files require geometry column parameters. Provide either:\n"
                "  • 'lat_name' AND 'lon_name' for point geometry (e.g., lat_name='latitude', lon_name='longitude')\n"
                "  • OR 'wkt_column' for WKT geometry strings (e.g., wkt_column='geom_wkt')"
            )
        }
    ]

    # 3-stage pipeline
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "prepare_chunks",
            "task_type": "process_vector_prepare",
            "parallelism": "single",
            "description": "Download, validate, chunk, create table with etl_batch_id"
        },
        {
            "number": 2,
            "name": "upload_chunks",
            "task_type": "process_vector_upload",
            "parallelism": "fan_out",
            "description": "Parallel chunk upload with DELETE+INSERT idempotency"
        },
        {
            "number": 3,
            "name": "create_stac",
            "task_type": "create_vector_stac",  # REUSE existing handler (already idempotent)
            "parallelism": "single",
            "description": "Create STAC catalog entry"
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
        Generate task parameters for each stage.

        Stage 1: Single task with all job params
        Stage 2: N tasks, one per chunk from Stage 1 results
        Stage 3: Single task with table metadata

        Args:
            stage: Stage number (1, 2, or 3)
            job_params: Validated job parameters
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage(s)

        Returns:
            List of task parameter dicts
        """
        from core.task_id import generate_deterministic_task_id

        if stage == 1:
            # Stage 1: Single prepare task
            task_id = generate_deterministic_task_id(job_id, 1, "prepare")

            # Resolve container name from config if not provided
            config = get_config()
            container_name = job_params.get('container_name') or config.storage.bronze.vectors

            return [{
                'task_id': task_id,
                'task_type': 'process_vector_prepare',
                'parameters': {
                    'job_id': job_id,
                    'blob_name': job_params['blob_name'],
                    'container_name': container_name,
                    'file_extension': job_params['file_extension'],
                    'table_name': job_params['table_name'],
                    'schema': job_params.get('schema', 'geo'),
                    'chunk_size': job_params.get('chunk_size'),
                    'converter_params': job_params.get('converter_params', {}),
                    'geometry_params': job_params.get('geometry_params', {}),
                    'indexes': job_params.get('indexes', {'spatial': True, 'attributes': [], 'temporal': []}),
                    # CSV geometry column params (GAP-008 - 15 DEC 2025)
                    'lat_name': job_params.get('lat_name'),
                    'lon_name': job_params.get('lon_name'),
                    'wkt_column': job_params.get('wkt_column'),
                    # User-provided metadata (09 DEC 2025)
                    'title': job_params.get('title'),
                    'description': job_params.get('description'),
                    'attribution': job_params.get('attribution'),
                    'license': job_params.get('license'),
                    'keywords': job_params.get('keywords'),
                    'temporal_property': job_params.get('temporal_property')
                }
            }]

        elif stage == 2:
            # Stage 2: Fan-out - one task per chunk
            if not previous_results:
                raise ValueError("Stage 2 requires Stage 1 results for fan-out")

            # GAP-006 FIX (15 DEC 2025): Validate Stage 1 result structure with Pydantic
            # This catches malformed results early with clear error messages
            from pydantic import ValidationError
            from core.models.results import ProcessVectorStage1Result

            raw_result = previous_results[0]

            try:
                # Validate full structure - Pydantic will raise if fields missing/invalid
                validated_result = ProcessVectorStage1Result(**raw_result)
            except ValidationError as e:
                # Convert Pydantic errors to actionable message
                error_details = "; ".join(
                    f"{err['loc']}: {err['msg']}" for err in e.errors()
                )
                raise ValueError(
                    f"Stage 1 result validation failed (GAP-006): {error_details}. "
                    f"Raw result keys: {list(raw_result.keys()) if isinstance(raw_result, dict) else 'NOT_A_DICT'}. "
                    f"This indicates Stage 1 returned malformed data."
                )

            # Check for explicit failure
            if not validated_result.success:
                raise ValueError(f"Stage 1 failed: {validated_result.error or 'unknown error'}")

            # Extract validated data - guaranteed to exist and be non-empty by Pydantic
            stage_1_data = validated_result.result
            chunk_paths = stage_1_data.chunk_paths  # Guaranteed min_length=1
            table_name = stage_1_data.table_name    # Guaranteed min_length=1
            schema = stage_1_data.schema

            logger.info(
                f"[{job_id[:8]}] Stage 2 fan-out: {len(chunk_paths)} chunks to upload "
                f"to {schema}.{table_name} (validated via GAP-006 Pydantic model)"
            )

            # Create one task per chunk with deterministic ID
            tasks = []
            for i, chunk_path in enumerate(chunk_paths):
                task_id = generate_deterministic_task_id(job_id, 2, f"chunk_{i}")
                tasks.append({
                    'task_id': task_id,
                    'task_type': 'process_vector_upload',
                    'parameters': {
                        'job_id': job_id,
                        'chunk_index': i,
                        'chunk_path': chunk_path,
                        'table_name': table_name,
                        'schema': schema
                    }
                })
            return tasks

        elif stage == 3:
            # Stage 3: Single STAC task - reuse existing create_vector_stac handler
            if not previous_results:
                raise ValueError("Stage 3 requires previous results")

            # Find Stage 1 result for table metadata
            stage_1_result = None
            for result in previous_results:
                result_data = result.get('result', {})
                if 'chunk_paths' in result_data:
                    stage_1_result = result_data
                    break

            if not stage_1_result:
                # Fallback: get table info from any Stage 2 result
                for result in previous_results:
                    result_data = result.get('result', {})
                    if 'table' in result_data:
                        table_full = result_data['table']
                        schema, table_name = table_full.split('.')
                        stage_1_result = {'table_name': table_name, 'schema': schema}
                        break

            if not stage_1_result:
                raise ValueError("Could not find table info in previous results")

            task_id = generate_deterministic_task_id(job_id, 3, "stac")
            return [{
                'task_id': task_id,
                'task_type': 'create_vector_stac',  # Reuse existing idempotent handler
                'parameters': {
                    'schema': stage_1_result.get('schema', 'geo'),
                    'table_name': stage_1_result.get('table_name'),
                    'collection_id': STACDefaults.VECTOR_COLLECTION,
                    'source_file': job_params.get('blob_name'),
                    'source_format': job_params.get('file_extension'),
                    'job_id': job_id,
                    'geometry_params': job_params.get('geometry_params', {})
                }
            }]

        else:
            return []

    @staticmethod
    def finalize_job(context) -> Dict[str, Any]:
        """
        Aggregate results from all completed tasks into job summary.

        Includes idempotency metrics (rows_deleted) to show if reruns occurred.

        Args:
            context: JobExecutionContext with task results

        Returns:
            Aggregated job results dict including OGC Features API URLs
        """
        from core.models import TaskStatus

        task_results = context.task_results
        params = context.parameters

        # Separate tasks by stage
        stage_1_tasks = [t for t in task_results if t.task_type == "process_vector_prepare"]
        stage_2_tasks = [t for t in task_results if t.task_type == "process_vector_upload"]
        stage_3_tasks = [t for t in task_results if t.task_type == "create_vector_stac"]

        # Extract metadata from Stage 1
        chunk_metadata = {}
        if stage_1_tasks and stage_1_tasks[0].result_data:
            stage_1_result = stage_1_tasks[0].result_data.get("result", {})
            chunk_metadata = {
                "chunk_count": stage_1_result.get("num_chunks", 0),
                "total_features": stage_1_result.get("total_features", 0),
                "chunk_size_used": stage_1_result.get("chunk_size_used", 0)
            }

        # Aggregate Stage 2 upload results (including idempotency metrics)
        successful_chunks = sum(1 for t in stage_2_tasks if t.status == TaskStatus.COMPLETED)
        failed_chunks = len(stage_2_tasks) - successful_chunks

        total_rows_inserted = 0
        total_rows_deleted = 0  # Idempotency indicator

        for task in stage_2_tasks:
            if task.result_data:
                result = task.result_data.get("result", {})
                total_rows_inserted += result.get("rows_inserted", 0)
                total_rows_deleted += result.get("rows_deleted", 0)

        # Extract STAC results from Stage 3 (with degraded mode detection - 6 DEC 2025)
        stac_summary = {}
        degraded_mode = False
        degraded_warnings = []

        if stage_3_tasks and stage_3_tasks[0].result_data:
            stac_data = stage_3_tasks[0].result_data

            # Check for degraded mode (pgSTAC unavailable)
            if stac_data.get("degraded"):
                degraded_mode = True
                degraded_warnings.append(stac_data.get("warning", "STAC cataloging skipped"))
                stac_result = stac_data.get("result", {})
                stac_summary = {
                    "degraded": True,
                    "stac_item_created": False,
                    "ogc_features_available": stac_result.get("ogc_features_available", True),
                    "degraded_reason": stac_result.get("degraded_reason")
                }
            else:
                stac_result = stac_data.get("result", {})
                stac_summary = {
                    "collection_id": stac_result.get("collection_id", "system-vectors"),
                    "stac_id": stac_result.get("stac_id"),
                    "pgstac_id": stac_result.get("pgstac_id"),
                    "inserted_to_pgstac": stac_result.get("inserted_to_pgstac", True),
                    "feature_count": stac_result.get("feature_count"),
                    "bbox": stac_result.get("bbox")
                }

        # Generate OGC Features URL and Vector Viewer URL
        from config import get_config
        config = get_config()
        table_name = params.get("table_name")
        ogc_features_url = config.generate_ogc_features_url(table_name)
        viewer_url = config.generate_vector_viewer_url(table_name)

        # Log completion with degraded mode indicator
        stac_status = "(STAC skipped - degraded mode)" if degraded_mode else "STAC cataloged"
        logger.info(
            f"[{context.job_id[:8]}] process_vector completed: "
            f"{total_rows_inserted} rows inserted, {total_rows_deleted} rows deleted (reruns), "
            f"{stac_status}"
        )

        result = {
            "job_type": "process_vector",
            "blob_name": params.get("blob_name"),
            "file_extension": params.get("file_extension"),
            "table_name": table_name,
            "schema": params.get("schema"),
            "container_name": params.get("container_name"),
            "summary": {
                "total_chunks": chunk_metadata.get("chunk_count", 0),
                "chunks_uploaded": successful_chunks,
                "chunks_failed": failed_chunks,
                "total_rows_inserted": total_rows_inserted,
                "total_rows_deleted": total_rows_deleted,  # >0 indicates idempotent reruns occurred
                "idempotent_reruns_detected": total_rows_deleted > 0,
                "success_rate": f"{(successful_chunks / len(stage_2_tasks) * 100):.1f}%" if stage_2_tasks else "0%",
                "stage_1_metadata": chunk_metadata,
                "data_complete": failed_chunks == 0
            },
            "stac": stac_summary,
            "ogc_features_url": ogc_features_url,
            "viewer_url": viewer_url,
            "stages_completed": context.current_stage,
            "total_tasks_executed": len(task_results),
            "tasks_by_status": {
                "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
                "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED),
                "queued": sum(1 for t in task_results if t.status == TaskStatus.QUEUED)
            }
        }

        # Add degraded mode info if applicable (6 DEC 2025)
        if degraded_mode:
            result["degraded_mode"] = True
            result["warnings"] = degraded_warnings
            result["available_capabilities"] = ["OGC Features API", "Vector Viewer"]
            result["unavailable_capabilities"] = ["STAC API discovery"]

        return result
