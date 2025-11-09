# ============================================================================
# CLAUDE CONTEXT - JOB DEFINITION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Job - Single-stage PostGIS vector STAC cataloging
# PURPOSE: Catalog PostGIS vector tables into STAC (PgSTAC)
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: StacCatalogVectorsWorkflow (JobBase implementation)
# INTERFACES: JobBase (implements 5-method contract)
# PYDANTIC_MODELS: None (uses dict-based validation)
# DEPENDENCIES: jobs.base.JobBase, hashlib, json
# SOURCE: HTTP job submission for PostGIS table STAC cataloging
# SCOPE: Single PostGIS table STAC metadata extraction
# VALIDATION: Schema name, table name, collection ID validation
# PATTERNS: Single-stage job, STAC Item generation from PostGIS
# ENTRY_POINTS: Registered in jobs/__init__.py ALL_JOBS as "stac_catalog_vectors"
# INDEX: StacCatalogVectorsWorkflow:16, stages:28, create_tasks_for_stage:48
# ============================================================================

"""
STAC Catalog Vectors Job Declaration - Single Stage for Vector Table Cataloging

This job catalogs PostGIS vector tables into STAC.
Single-stage job: Extract STAC metadata from PostGIS table and insert into PgSTAC.

Author: Robert and Geospatial Claude Legion
Date: 8 OCT 2025
Last Updated: 29 OCT 2025
"""

from typing import List, Dict, Any
import hashlib
import json

from jobs.base import JobBase


class StacCatalogVectorsWorkflow(JobBase):
    """
    Single-stage job for STAC cataloging of PostGIS vector tables.

    Stage 1: Extract STAC metadata from table and insert to PgSTAC

    Results: STAC Item stored in PgSTAC database + task.result_data
    """

    # Job metadata
    job_type: str = "stac_catalog_vectors"
    description: str = "STAC metadata extraction from PostGIS vector table"

    # Stage definitions
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "catalog_table",
            "task_type": "extract_vector_stac_metadata",
            "description": "Extract STAC metadata from PostGIS table and insert into PgSTAC",
            "parallelism": "single"
        }
    ]

    # Parameter schema
    parameters_schema: Dict[str, Any] = {
        "schema": {"type": "str", "required": True, "default": "geo"},
        "table_name": {"type": "str", "required": True},
        "collection_id": {"type": "str", "required": True, "default": "vectors"},
        "source_file": {"type": "str", "default": None}
    }

    @staticmethod
    def validate_job_parameters(params: dict) -> dict:
        """
        Validate job parameters.

        Required:
            schema: str - PostgreSQL schema name (default: "geo")
            table_name: str - Table name to catalog

        Optional:
            collection_id: str - STAC collection (default: "vectors")
            source_file: str - Original source file path

        Returns:
            Validated parameters dict

        Raises:
            ValueError: If parameters are invalid
        """
        validated = {}

        # Validate schema (required, with default)
        schema = params.get("schema", "geo")
        if not isinstance(schema, str) or not schema.strip():
            raise ValueError("schema must be a non-empty string")
        validated["schema"] = schema.strip()

        # Validate table_name (required)
        if "table_name" not in params:
            raise ValueError("table_name is required")

        table_name = params["table_name"]
        if not isinstance(table_name, str) or not table_name.strip():
            raise ValueError("table_name must be a non-empty string")
        validated["table_name"] = table_name.strip()

        # Validate collection_id (optional)
        collection_id = params.get("collection_id", "vectors")
        if not isinstance(collection_id, str) or not collection_id.strip():
            raise ValueError("collection_id must be a non-empty string")

        # Validate collection_id is valid
        valid_collections = ["dev", "cogs", "vectors", "geoparquet"]
        if collection_id not in valid_collections:
            raise ValueError(f"collection_id must be one of {valid_collections}, got '{collection_id}'")

        validated["collection_id"] = collection_id.strip()

        # Validate source_file (optional)
        source_file = params.get("source_file")
        if source_file is not None:
            if not isinstance(source_file, str):
                raise ValueError("source_file must be a string")
            validated["source_file"] = source_file.strip() if source_file.strip() else None
        else:
            validated["source_file"] = None

        return validated

    @staticmethod
    def generate_job_id(params: dict) -> str:
        """
        Generate deterministic job ID from parameters.

        Same parameters = same job ID (idempotency).
        """
        # Sort keys for consistent hashing
        param_str = json.dumps(params, sort_keys=True)
        job_hash = hashlib.sha256(param_str.encode()).hexdigest()
        return job_hash

    @staticmethod
    def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None) -> list[dict]:
        """
        Generate task parameters for a stage.

        Stage 1: Single task to catalog the PostGIS table

        Args:
            stage: Stage number (1)
            job_params: Job parameters
            job_id: Job ID for task ID generation
            previous_results: Not used (single stage)

        Returns:
            List of task parameter dicts
        """
        from core.task_id import generate_deterministic_task_id

        if stage == 1:
            # Stage 1: Single task to catalog vector table
            task_id = generate_deterministic_task_id(job_id, 1, f"catalog_{job_params['schema']}_{job_params['table_name']}")
            return [
                {
                    "task_id": task_id,
                    "task_type": "extract_vector_stac_metadata",
                    "parameters": {
                        "schema": job_params["schema"],
                        "table_name": job_params["table_name"],
                        "collection_id": job_params.get("collection_id", "vectors"),
                        "source_file": job_params.get("source_file")
                    }
                }
            ]
        else:
            return []

    @staticmethod
    def create_job_record(job_id: str, params: dict) -> dict:
        """
        Create job record for database storage.

        Args:
            job_id: Generated job ID
            params: Validated parameters

        Returns:
            Job record dict
        """
        from infrastructure import RepositoryFactory
        from core.models import JobRecord, JobStatus

        # Create job record object
        job_record = JobRecord(
            job_id=job_id,
            job_type="stac_catalog_vectors",
            parameters=params,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=1,
            stage_results={},
            metadata={
                "description": "STAC metadata extraction from PostGIS vector table",
                "created_by": "StacCatalogVectorsWorkflow",
                "schema": params.get("schema", "geo"),
                "table_name": params.get("table_name"),
                "collection_id": params.get("collection_id", "vectors")
            }
        )

        # Persist to database
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']
        job_repo.create_job(job_record)

        # Return as dict
        return job_record.model_dump()

    @staticmethod
    def queue_job(job_id: str, params: dict) -> dict:
        """
        Queue job for processing using Service Bus.

        Args:
            job_id: Job ID
            params: Validated parameters

        Returns:
            Queue result information
        """
        from infrastructure.service_bus import ServiceBusRepository
        from core.schema.queue import JobQueueMessage
        from config import get_config
        from util_logger import LoggerFactory, ComponentType
        import uuid

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "StacCatalogVectorsWorkflow.queue_job")

        logger.info(f"🚀 Starting queue_job for job_id={job_id}")

        # Get config for queue name
        config = get_config()
        queue_name = config.service_bus_jobs_queue

        # Create Service Bus repository
        service_bus_repo = ServiceBusRepository()

        # Create job queue message
        correlation_id = str(uuid.uuid4())[:8]
        job_message = JobQueueMessage(
            job_id=job_id,
            job_type="stac_catalog_vectors",
            stage=1,
            parameters=params,
            correlation_id=correlation_id
        )

        # Send to Service Bus jobs queue
        message_id = service_bus_repo.send_message(queue_name, job_message)
        logger.info(f"✅ Message sent successfully - message_id={message_id}")

        result = {
            "queued": True,
            "queue_type": "service_bus",
            "queue_name": queue_name,
            "message_id": message_id,
            "job_id": job_id
        }

        logger.info(f"🎉 Job queued successfully - {result}")
        return result

    @staticmethod
    def finalize_job(context) -> Dict[str, Any]:
        """
        Aggregate results from completed task into job summary.

        Args:
            context: JobExecutionContext with task results

        Returns:
            Aggregated job results dict
        """
        from core.models import TaskStatus

        task_results = context.task_results
        params = context.parameters

        # Should be exactly 1 task
        if not task_results:
            return {
                "job_type": "stac_catalog_vectors",
                "error": "No tasks executed"
            }

        task = task_results[0]
        task_data = task.result_data.get("result", {}) if task.result_data else {}

        # Build aggregated result
        return {
            "job_type": "stac_catalog_vectors",
            "schema": params.get("schema", "geo"),
            "table_name": params.get("table_name"),
            "collection_id": params.get("collection_id", "vectors"),
            "summary": {
                "item_id": task_data.get("item_id"),
                "row_count": task_data.get("row_count", 0),
                "geometry_types": task_data.get("geometry_types", []),
                "srid": task_data.get("srid", 0),
                "inserted_to_pgstac": task_data.get("inserted_to_pgstac", False),
                "item_skipped": task_data.get("item_skipped", False),
                "bbox": task_data.get("bbox", [])
            },
            "stages_completed": context.current_stage,
            "total_tasks_executed": len(task_results),
            "task_status": task.status.value if hasattr(task.status, 'value') else str(task.status)
        }
