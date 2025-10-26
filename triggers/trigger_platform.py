# ============================================================================
# CLAUDE CONTEXT - PLATFORM REQUEST HTTP TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: HTTP Trigger - Platform Service Layer orchestration endpoint
# PURPOSE: Handle external application requests (DDH) and orchestrate CoreMachine jobs
# LAST_REVIEWED: 25 OCT 2025
# EXPORTS: platform_request_submit (HTTP trigger function)
# INTERFACES: None
# PYDANTIC_MODELS: PlatformRequest, PlatformRecord
# DEPENDENCIES: azure-functions, psycopg, azure-servicebus
# SOURCE: HTTP requests from external applications (DDH)
# SCOPE: Platform-level orchestration above CoreMachine
# VALIDATION: Pydantic models for request validation
# PATTERNS: Repository, parallel to job submission trigger
# ENTRY_POINTS: POST /api/platform/submit
# INDEX:
#   - Imports: Line 20
#   - Models: Line 40
#   - Repository: Line 100
#   - HTTP Handler: Line 250
#   - Platform Orchestrator: Line 350
# ============================================================================

"""
Platform Request HTTP Trigger

Provides application-level orchestration above CoreMachine.
Accepts requests from external applications (DDH) and creates
appropriate CoreMachine jobs to fulfill them.

This is the "turtle above CoreMachine" in our fractal pattern.
"""

import json
import logging
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum

import azure.functions as func
from pydantic import BaseModel, Field, field_validator
from azure.servicebus import ServiceBusClient, ServiceBusMessage

from config import get_settings
from infrastructure.postgresql import PostgreSQLRepository
from infrastructure.jobs_tasks import JobRepository
from core.machine import CoreMachine
from core.models import JobRecord

# Configure logging
logger = logging.getLogger(__name__)
settings = get_settings()

# ============================================================================
# PLATFORM REQUEST MODELS
# ============================================================================

class PlatformRequestStatus(str, Enum):
    """Platform request status - mirrors JobStatus pattern"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class DataType(str, Enum):
    """Supported data types for processing"""
    RASTER = "raster"
    VECTOR = "vector"
    POINTCLOUD = "pointcloud"
    MESH_3D = "mesh_3d"
    TABULAR = "tabular"

class PlatformRequest(BaseModel):
    """
    Platform request from external application (DDH).
    This is what DDH sends us.
    """
    dataset_id: str = Field(..., description="DDH dataset identifier")
    resource_id: str = Field(..., description="DDH resource identifier")
    version_id: str = Field(..., description="DDH version identifier")
    data_type: DataType = Field(..., description="Type of data to process")
    source_location: str = Field(..., description="Azure blob URL or path")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Processing parameters")
    client_id: str = Field(..., description="Client application identifier (e.g., 'ddh')")

    @field_validator('source_location')
    @classmethod
    def validate_source(cls, v: str) -> str:
        """Ensure source is Azure blob storage"""
        if not (v.startswith('https://') or v.startswith('wasbs://') or v.startswith('/')):
            raise ValueError("Source must be Azure blob URL or absolute path")
        return v

class PlatformRecord(BaseModel):
    """
    Platform request database record.
    Follows same pattern as JobRecord.
    """
    request_id: str = Field(..., description="SHA256 hash of identifiers")
    dataset_id: str
    resource_id: str
    version_id: str
    data_type: str
    status: PlatformRequestStatus = Field(default=PlatformRequestStatus.PENDING)
    job_ids: List[str] = Field(default_factory=list, description="CoreMachine job IDs")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    result_data: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage"""
        return {
            'request_id': self.request_id,
            'dataset_id': self.dataset_id,
            'resource_id': self.resource_id,
            'version_id': self.version_id,
            'data_type': self.data_type,
            'status': self.status.value if isinstance(self.status, Enum) else self.status,
            'job_ids': self.job_ids,
            'parameters': self.parameters,
            'metadata': self.metadata,
            'result_data': self.result_data,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

# ============================================================================
# PLATFORM REPOSITORY
# ============================================================================

class PlatformRepository(PostgreSQLRepository):
    """
    Repository for platform requests.
    Follows same pattern as JobRepository.
    """

    def __init__(self):
        super().__init__()
        self._ensure_schema()

    def _ensure_schema(self):
        """Create platform schema and tables if they don't exist"""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Create schema
                cur.execute("CREATE SCHEMA IF NOT EXISTS platform")

                # Create platform requests table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS platform.requests (
                        request_id VARCHAR(32) PRIMARY KEY,
                        dataset_id VARCHAR(255) NOT NULL,
                        resource_id VARCHAR(255) NOT NULL,
                        version_id VARCHAR(50) NOT NULL,
                        data_type VARCHAR(50) NOT NULL,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        job_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                        parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        result_data JSONB,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)

                # Create indexes
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_platform_status
                    ON platform.requests(status)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_platform_dataset
                    ON platform.requests(dataset_id)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_platform_created
                    ON platform.requests(created_at DESC)
                """)

                # Create platform-job mapping table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS platform.request_jobs (
                        request_id VARCHAR(32) NOT NULL,
                        job_id VARCHAR(32) NOT NULL,
                        job_type VARCHAR(100) NOT NULL,
                        sequence INTEGER NOT NULL DEFAULT 1,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        PRIMARY KEY (request_id, job_id)
                    )
                """)

                conn.commit()

    def create_request(self, request: PlatformRecord) -> PlatformRecord:
        """Create a new platform request"""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO platform.requests
                    (request_id, dataset_id, resource_id, version_id, data_type,
                     status, parameters, metadata, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (request_id) DO NOTHING
                    RETURNING *
                """, (
                    request.request_id,
                    request.dataset_id,
                    request.resource_id,
                    request.version_id,
                    request.data_type,
                    request.status.value if isinstance(request.status, Enum) else request.status,
                    json.dumps(request.parameters),
                    json.dumps(request.metadata),
                    request.created_at,
                    request.updated_at
                ))

                row = cur.fetchone()
                conn.commit()

                if row:
                    logger.info(f"Created platform request: {request.request_id}")
                else:
                    # Request already exists, fetch it
                    cur.execute("""
                        SELECT * FROM platform.requests WHERE request_id = %s
                    """, (request.request_id,))
                    row = cur.fetchone()
                    logger.info(f"Platform request already exists: {request.request_id}")

                return self._row_to_record(row)

    def get_request(self, request_id: str) -> Optional[PlatformRecord]:
        """Get a platform request by ID"""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM platform.requests WHERE request_id = %s
                """, (request_id,))

                row = cur.fetchone()
                return self._row_to_record(row) if row else None

    def update_request_status(self, request_id: str, status: PlatformRequestStatus) -> bool:
        """Update platform request status"""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE platform.requests
                    SET status = %s, updated_at = NOW()
                    WHERE request_id = %s
                """, (status.value, request_id))

                conn.commit()
                return cur.rowcount > 0

    def add_job_to_request(self, request_id: str, job_id: str, job_type: str) -> bool:
        """Add a CoreMachine job to a platform request"""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Add to job_ids array
                cur.execute("""
                    UPDATE platform.requests
                    SET job_ids = job_ids || %s::jsonb,
                        updated_at = NOW()
                    WHERE request_id = %s
                """, (json.dumps([job_id]), request_id))

                # Add to mapping table
                cur.execute("""
                    INSERT INTO platform.request_jobs (request_id, job_id, job_type)
                    VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, (request_id, job_id, job_type))

                conn.commit()
                return cur.rowcount > 0

    def _row_to_record(self, row) -> PlatformRecord:
        """Convert database row to PlatformRecord"""
        return PlatformRecord(
            request_id=row[0],
            dataset_id=row[1],
            resource_id=row[2],
            version_id=row[3],
            data_type=row[4],
            status=row[5],
            job_ids=row[6] if row[6] else [],
            parameters=row[7] if row[7] else {},
            metadata=row[8] if row[8] else {},
            result_data=row[9] if len(row) > 9 else None,
            created_at=row[10] if len(row) > 10 else None,
            updated_at=row[11] if len(row) > 11 else None
        )

# ============================================================================
# HTTP HANDLER
# ============================================================================

async def platform_request_submit(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger for platform request submission.

    POST /api/platform/submit

    Body:
    {
        "dataset_id": "landsat-8",
        "resource_id": "LC08_L1TP_044034_20210622",
        "version_id": "v1.0",
        "data_type": "raster",
        "source_location": "https://rmhazuregeo.blob.core.windows.net/bronze/...",
        "parameters": {...},
        "client_id": "ddh"
    }
    """
    logger.info("Platform request submission endpoint called")

    try:
        # Parse request body
        req_body = req.get_json()

        # Validate with Pydantic
        platform_req = PlatformRequest(**req_body)

        # Generate deterministic request ID
        request_id = generate_request_id(
            platform_req.dataset_id,
            platform_req.resource_id,
            platform_req.version_id
        )

        # Create platform record
        platform_record = PlatformRecord(
            request_id=request_id,
            dataset_id=platform_req.dataset_id,
            resource_id=platform_req.resource_id,
            version_id=platform_req.version_id,
            data_type=platform_req.data_type.value,
            status=PlatformRequestStatus.PENDING,
            parameters=platform_req.parameters,
            metadata={
                'client_id': platform_req.client_id,
                'source_location': platform_req.source_location,
                'submission_time': datetime.utcnow().isoformat()
            }
        )

        # Store in database
        repo = PlatformRepository()
        stored_record = repo.create_request(platform_record)

        # Create platform orchestrator
        orchestrator = PlatformOrchestrator()

        # Process the request (creates CoreMachine jobs)
        jobs_created = await orchestrator.process_platform_request(stored_record)

        # Return response
        return func.HttpResponse(
            json.dumps({
                "success": True,
                "request_id": request_id,
                "status": stored_record.status.value if isinstance(stored_record.status, Enum) else stored_record.status,
                "jobs_created": jobs_created,
                "message": f"Platform request submitted. {len(jobs_created)} jobs created.",
                "monitor_url": f"/api/platform/status/{request_id}"
            }),
            status_code=200 if stored_record.status == PlatformRequestStatus.PENDING else 202,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform request submission failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=400,
            headers={"Content-Type": "application/json"}
        )

# ============================================================================
# PLATFORM ORCHESTRATOR
# ============================================================================

class PlatformOrchestrator:
    """
    Orchestrates platform requests by creating appropriate CoreMachine jobs.
    This is the "turtle above CoreMachine" - it doesn't execute work itself,
    but creates jobs for CoreMachine to handle.
    """

    def __init__(self):
        self.platform_repo = PlatformRepository()
        self.job_repo = JobRepository()
        self.core_machine = CoreMachine()

    async def process_platform_request(self, request: PlatformRecord) -> List[str]:
        """
        Process a platform request by creating CoreMachine jobs.

        Returns list of job IDs created.
        """
        logger.info(f"Processing platform request: {request.request_id}")

        try:
            # Update status to processing
            self.platform_repo.update_request_status(
                request.request_id,
                PlatformRequestStatus.PROCESSING
            )

            # Determine what jobs to create based on data type
            jobs_to_create = self._determine_jobs(request)

            # Create each job
            job_ids = []
            for job_config in jobs_to_create:
                job_id = await self._create_coremachine_job(
                    request,
                    job_config['job_type'],
                    job_config['parameters']
                )

                if job_id:
                    job_ids.append(job_id)
                    # Add job to platform request
                    self.platform_repo.add_job_to_request(
                        request.request_id,
                        job_id,
                        job_config['job_type']
                    )

            logger.info(f"Created {len(job_ids)} jobs for platform request {request.request_id}")

            # If no jobs could be created, mark as failed
            if not job_ids:
                self.platform_repo.update_request_status(
                    request.request_id,
                    PlatformRequestStatus.FAILED
                )

            return job_ids

        except Exception as e:
            logger.error(f"Failed to process platform request: {e}", exc_info=True)
            self.platform_repo.update_request_status(
                request.request_id,
                PlatformRequestStatus.FAILED
            )
            raise

    def _determine_jobs(self, request: PlatformRecord) -> List[Dict[str, Any]]:
        """
        Determine what CoreMachine jobs to create based on data type.

        This is where we implement the business logic of "what work needs
        to be done for this type of data".
        """
        jobs = []

        if request.data_type == DataType.RASTER.value:
            # Raster processing pipeline
            source = request.metadata.get('source_location', '')

            jobs.extend([
                {
                    'job_type': 'validate_raster',
                    'parameters': {
                        'source_path': source,
                        'dataset_id': request.dataset_id,
                        'resource_id': request.resource_id
                    }
                },
                {
                    'job_type': 'create_cog',
                    'parameters': {
                        'source_path': source,
                        'output_container': 'silver',
                        'dataset_id': request.dataset_id
                    }
                },
                {
                    'job_type': 'create_stac_item',
                    'parameters': {
                        'dataset_id': request.dataset_id,
                        'resource_id': request.resource_id,
                        'asset_path': f"silver/{request.dataset_id}/{request.resource_id}.tif"
                    }
                }
            ])

        elif request.data_type == DataType.VECTOR.value:
            # Vector processing pipeline
            source = request.metadata.get('source_location', '')

            jobs.extend([
                {
                    'job_type': 'validate_vector',
                    'parameters': {
                        'source_path': source,
                        'dataset_id': request.dataset_id
                    }
                },
                {
                    'job_type': 'import_to_postgis',
                    'parameters': {
                        'source_path': source,
                        'table_name': f"{request.dataset_id}_{request.resource_id}",
                        'schema': 'geo'
                    }
                }
            ])

        elif request.data_type == DataType.POINTCLOUD.value:
            # Point cloud processing
            jobs.append({
                'job_type': 'process_pointcloud',
                'parameters': {
                    'source_path': request.metadata.get('source_location', ''),
                    'dataset_id': request.dataset_id
                }
            })

        # Add hello_world job for testing
        if request.parameters.get('test_mode'):
            jobs.insert(0, {
                'job_type': 'hello_world',
                'parameters': {
                    'message': f"Testing platform request {request.request_id}"
                }
            })

        return jobs

    async def _create_coremachine_job(
        self,
        request: PlatformRecord,
        job_type: str,
        parameters: Dict[str, Any]
    ) -> Optional[str]:
        """
        Create a CoreMachine job and submit it to the jobs queue.
        """
        try:
            # Add platform metadata to job parameters
            job_params = {
                **parameters,
                '_platform_request_id': request.request_id,
                '_platform_dataset': request.dataset_id
            }

            # Generate job ID
            job_id = self._generate_job_id(job_type, job_params)

            # Create job record
            job_record = JobRecord(
                job_id=job_id,
                job_type=job_type,
                status='pending',
                parameters=job_params,
                metadata={
                    'platform_request': request.request_id,
                    'created_by': 'platform_orchestrator'
                }
            )

            # Store in database
            stored_job = self.job_repo.create_job(job_record)

            # Submit to Service Bus jobs queue
            await self._submit_to_queue(stored_job)

            logger.info(f"Created CoreMachine job {job_id} for platform request {request.request_id}")
            return job_id

        except Exception as e:
            logger.error(f"Failed to create CoreMachine job: {e}", exc_info=True)
            return None

    async def _submit_to_queue(self, job: JobRecord):
        """Submit job to Service Bus jobs queue"""
        try:
            client = ServiceBusClient.from_connection_string(
                settings.SERVICE_BUS_CONNECTION_STRING
            )

            with client:
                sender = client.get_queue_sender(queue_name="jobs")

                message = ServiceBusMessage(
                    json.dumps({
                        'job_id': job.job_id,
                        'job_type': job.job_type
                    })
                )

                sender.send_messages(message)
                logger.info(f"Submitted job {job.job_id} to jobs queue")

        except Exception as e:
            logger.error(f"Failed to submit job to queue: {e}", exc_info=True)
            raise

    def _generate_job_id(self, job_type: str, parameters: Dict[str, Any]) -> str:
        """Generate deterministic job ID"""
        # Remove platform metadata for ID generation
        clean_params = {
            k: v for k, v in parameters.items()
            if not k.startswith('_platform_')
        }

        canonical = f"{job_type}:{json.dumps(clean_params, sort_keys=True)}"
        return hashlib.sha256(canonical.encode()).hexdigest()[:32]

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def generate_request_id(dataset_id: str, resource_id: str, version_id: str) -> str:
    """
    Generate deterministic request ID from DDH identifiers.
    Includes timestamp to allow reprocessing of same dataset.
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    canonical = f"{dataset_id}:{resource_id}:{version_id}:{timestamp}"
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]