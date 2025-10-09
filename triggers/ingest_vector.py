# ============================================================================
# CLAUDE CONTEXT - HTTP TRIGGER
# ============================================================================
# PURPOSE: Vector ingest HTTP trigger for POST /api/jobs/ingest_vector
# EXPORTS: IngestVectorTrigger, ingest_vector_trigger (singleton instance)
# INTERFACES: JobManagementTrigger (inherited from http_base)
# PYDANTIC_MODELS: None directly - uses IngestVectorJob validation
# DEPENDENCIES: http_base.JobManagementTrigger, azure.functions, typing
# SOURCE: HTTP POST requests with JSON body containing vector file parameters
# SCOPE: HTTP endpoint for vector ETL job submission
# VALIDATION: File extension, table name, blob path validation via IngestVectorJob
# PATTERNS: Template Method (base class), Explicit Registration (jobs registry)
# ENTRY_POINTS: trigger = IngestVectorTrigger(); response = trigger.handle_request(req)
# INDEX: IngestVectorTrigger:45, process_request:62, get_allowed_methods:57
# ============================================================================

"""
Vector Ingest HTTP Trigger - Azure Geospatial ETL Pipeline

HTTP endpoint for submitting vector file ETL jobs to PostGIS.

Supports 6 file formats:
- CSV (lat/lon or WKT)
- GeoJSON
- GeoPackage
- KML
- KMZ (zipped KML)
- Shapefile (zipped)

Job Flow:
1. Validate request parameters (blob_name, file_extension, table_name)
2. Route to IngestVectorJob via CoreMachine
3. Create job record in PostgreSQL
4. Queue job message to Service Bus
5. Two-stage fan-out execution:
   - Stage 1: Load, validate, chunk, pickle GeoDataFrame
   - Stage 2: N parallel tasks upload chunks to PostGIS

API Endpoint:
    POST /api/jobs/ingest_vector

Request Body:
    {
        "blob_name": "data/parcels.gpkg",       # Required
        "file_extension": "gpkg",               # Required (csv, geojson, gpkg, kml, kmz, shp, zip)
        "table_name": "parcels_2025",           # Required (PostgreSQL identifier)
        "container_name": "bronze",             # Optional (default: bronze)
        "schema": "geo",                        # Optional (default: geo)
        "chunk_size": 1000,                     # Optional (None = auto-calculate)
        "converter_params": {                   # Optional (format-specific)
            "layer_name": "parcels"             # For GPKG
            // OR
            "lat_name": "latitude",             # For CSV
            "lon_name": "longitude"             # For CSV
            // OR
            "wkt_column": "geometry"            # For CSV with WKT
        }
    }

Response:
    {
        "job_id": "sha256_hash",
        "status": "created",
        "job_type": "ingest_vector",
        "message": "Vector ETL job created and queued",
        "parameters": {...validated_params},
        "queue_info": {...queue_details}
    }

Error Responses:
- 400: Invalid parameters (unsupported format, invalid table name, etc.)
- 404: Blob not found
- 500: Internal server error

Author: Azure Geospatial ETL Team
Date: 7 OCT 2025
"""

from typing import Dict, Any, List
import azure.functions as func
from .http_base import JobManagementTrigger


class IngestVectorTrigger(JobManagementTrigger):
    """Vector ingest HTTP trigger implementation."""

    def __init__(self):
        super().__init__("ingest_vector")

    def get_allowed_methods(self) -> List[str]:
        """Vector ingest only supports POST."""
        return ["POST"]

    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Process vector ingest request.

        Args:
            req: HTTP request with vector file parameters in body

        Returns:
            Job creation response data

        Raises:
            ValueError: For invalid parameters or unsupported formats
        """
        # Extract and validate request body
        req_body = self.extract_json_body(req, required=True)

        # Validate required fields
        self.validate_required_fields(req_body, ["blob_name", "file_extension", "table_name"])

        # Extract parameters
        blob_name = req_body["blob_name"]
        file_extension = req_body["file_extension"]
        table_name = req_body["table_name"]
        container_name = req_body.get("container_name", "bronze")
        schema = req_body.get("schema", "geo")
        chunk_size = req_body.get("chunk_size")  # None = auto-calculate
        converter_params = req_body.get("converter_params", {})

        self.logger.info(
            f"📦 Vector ingest request: blob={blob_name}, format={file_extension}, "
            f"table={schema}.{table_name}, container={container_name}"
        )

        # Get job class from registry (explicit registration, no magic)
        from jobs import ALL_JOBS

        if "ingest_vector" not in ALL_JOBS:
            raise ValueError(
                "Vector ingest job not registered. Available jobs: "
                f"{', '.join(ALL_JOBS.keys())}"
            )

        job_class = ALL_JOBS["ingest_vector"]
        self.logger.debug(f"✅ Job class loaded: {job_class.__name__}")

        # Build job parameters
        job_params = {
            "blob_name": blob_name,
            "file_extension": file_extension,
            "table_name": table_name,
            "container_name": container_name,
            "schema": schema,
            "chunk_size": chunk_size,
            "converter_params": converter_params
        }

        # Validate parameters using job's validation
        self.logger.debug("🔍 Validating job parameters")
        validated_params = job_class.validate_job_parameters(job_params)
        self.logger.debug("✅ Parameters validated")

        # Generate deterministic job ID
        job_id = job_class.generate_job_id(validated_params)
        self.logger.info(f"📋 Job ID: {job_id[:16]}...")

        # Check for existing job (idempotency)
        from infrastructure.factory import RepositoryFactory
        repos = RepositoryFactory.create_repositories()
        existing_job = repos['job_repo'].get_job(job_id)

        if existing_job:
            self.logger.info(f"🔄 Job {job_id[:16]}... already exists: {existing_job.status}")

            if existing_job.status.value == 'completed':
                return {
                    "job_id": job_id,
                    "status": "already_completed",
                    "job_type": "ingest_vector",
                    "message": "Vector ETL job already completed (idempotency)",
                    "parameters": validated_params,
                    "result_data": existing_job.result_data,
                    "created_at": existing_job.created_at.isoformat() if existing_job.created_at else None,
                    "completed_at": existing_job.updated_at.isoformat() if existing_job.updated_at else None,
                    "idempotent": True
                }
            else:
                return {
                    "job_id": job_id,
                    "status": existing_job.status.value,
                    "job_type": "ingest_vector",
                    "message": f"Vector ETL job in progress: {existing_job.status.value} (idempotency)",
                    "parameters": validated_params,
                    "current_stage": existing_job.stage,
                    "total_stages": existing_job.total_stages,
                    "idempotent": True
                }

        # Create new job via CoreMachine
        self.logger.info(f"✨ Creating new vector ETL job")

        # CoreMachine handles job creation and queuing
        job_record = job_class.create_job_record(job_id, validated_params)
        queue_result = job_class.queue_job(job_id, validated_params)

        self.logger.info(f"✅ Vector ETL job created and queued")

        return {
            "job_id": job_id,
            "status": "created",
            "job_type": "ingest_vector",
            "message": "Vector ETL job created and queued for processing",
            "parameters": validated_params,
            "queue_info": queue_result,
            "idempotent": False
        }


# Create singleton instance for use in function_app.py
ingest_vector_trigger = IngestVectorTrigger()
