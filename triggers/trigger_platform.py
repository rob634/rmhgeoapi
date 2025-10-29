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
import traceback
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum

import azure.functions as func
from pydantic import BaseModel, Field, field_validator
from azure.servicebus import ServiceBusClient, ServiceBusMessage

# Configure logging using LoggerFactory (Application Insights integration)
from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "trigger_platform")

# Import config with error handling
try:
    from config import get_config
    config = get_config()
    logger.info("✅ Platform trigger: config loaded successfully")
except ImportError as e:
    logger.error(f"❌ CRITICAL: Failed to import get_config from config module")
    logger.error(f"   ImportError: {e}")
    logger.error(f"   Traceback: {traceback.format_exc()}")
    raise
except Exception as e:
    logger.error(f"❌ CRITICAL: Failed to initialize config")
    logger.error(f"   Error: {e}")
    logger.error(f"   Traceback: {traceback.format_exc()}")
    raise

# Import infrastructure with error handling
try:
    from infrastructure.postgresql import PostgreSQLRepository
    from infrastructure.jobs_tasks import JobRepository
    logger.info("✅ Platform trigger: infrastructure modules loaded successfully")
except ImportError as e:
    logger.error(f"❌ CRITICAL: Failed to import infrastructure modules")
    logger.error(f"   ImportError: {e}")
    logger.error(f"   Traceback: {traceback.format_exc()}")
    raise

# Import core with error handling
try:
    from core.machine import CoreMachine
    from core.models.job import JobRecord
    from core.models.enums import JobStatus
    logger.info("✅ Platform trigger: core modules loaded successfully")
except ImportError as e:
    logger.error(f"❌ CRITICAL: Failed to import core modules")
    logger.error(f"   ImportError: {e}")
    logger.error(f"   Traceback: {traceback.format_exc()}")
    logger.error(f"   NOTE: JobRecord should be imported from core.models.job, not core.models")
    raise

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

        # ISSUE #3 - RESOLVED (26 OCT 2025): Schema Initialization Moved to Centralized System
        # ================================================================
        # PREVIOUS BEHAVIOR: _ensure_schema() ran on EVERY HTTP request (50+ DDL statements)
        # IMPACT: 50-100ms overhead per request, unnecessary database locks
        #
        # SOLUTION IMPLEMENTED:
        #   ✅ Platform schema now deployed via triggers/schema_pydantic_deploy.py
        #   ✅ Repository assumes schema exists (fail fast if missing)
        #   ✅ No DDL in constructors or request handlers (CoreMachine pattern)
        #   ✅ Schema deployed ONCE via POST /api/db/schema/redeploy?confirm=yes
        #
        # PERFORMANCE IMPROVEMENT: ~50-100ms per Platform request eliminated
        #
        # NOTE: _ensure_schema() method kept below as emergency fallback but NOT called
        # REFERENCE: PLATFORM_LAYER_FIXES_TODO.md Issue #3 (lines 174-282)
        # STATUS: FIXED - 26 OCT 2025
        # ================================================================
        # self._ensure_schema()  # ✅ REMOVED - Schema now deployed centrally

    def _ensure_schema(self):
        """
        DEPRECATED (26 OCT 2025) - Emergency fallback only, not called in normal operation.

        Create platform schema and tables if they don't exist.

        ⚠️ DEPRECATED: This method is NO LONGER CALLED automatically.
        Platform schema is now deployed via triggers/schema_pydantic_deploy.py

        This method is kept as an emergency fallback in case schema deployment fails.
        Schema should be deployed via: POST /api/db/schema/redeploy?confirm=yes

        PERFORMANCE IMPACT if re-enabled: 50-100ms per request, unnecessary database locks
        DO NOT call this from __init__() or request handlers!
        """
        import warnings
        warnings.warn(
            "PlatformRepository._ensure_schema() is deprecated. "
            "Use centralized schema deployment via /api/db/schema/redeploy",
            DeprecationWarning,
            stacklevel=2
        )
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
        """
        Convert database row to PlatformRecord.

        Uses CoreMachine pattern (infrastructure/postgresql.py:694-709):
        - Build intermediate dictionary with explicit column name mapping
        - Use Pydantic model unpacking for validation
        - Rows are dict-like (psycopg dict_row factory) NOT tuples
        """
        # Build intermediate dictionary with explicit column mapping
        record_data = {
            'request_id': row['request_id'],
            'dataset_id': row['dataset_id'],
            'resource_id': row['resource_id'],
            'version_id': row['version_id'],
            'data_type': row['data_type'],
            'status': row['status'],
            'job_ids': row['job_ids'] if row['job_ids'] else [],
            'parameters': row['parameters'] if isinstance(row['parameters'], dict) else json.loads(row['parameters']) if row['parameters'] else {},
            'metadata': row['metadata'] if isinstance(row['metadata'], dict) else json.loads(row['metadata']) if row['metadata'] else {},
            'result_data': row.get('result_data'),  # Optional field
            'created_at': row.get('created_at'),    # Optional field
            'updated_at': row.get('updated_at')     # Optional field
        }

        # Use Pydantic unpacking for validation
        return PlatformRecord(**record_data)

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
        # Import registries explicitly (CoreMachine requires them since 10 SEP 2025)
        from jobs import ALL_JOBS
        from services import ALL_HANDLERS

        self.platform_repo = PlatformRepository()
        self.job_repo = JobRepository()

        # CoreMachine requires explicit registries (no decorator magic!)
        # See: core/machine.py:116-149 for constructor signature
        self.core_machine = CoreMachine(
            all_jobs=ALL_JOBS,
            all_handlers=ALL_HANDLERS
        )

        logger.info(f"✅ PlatformOrchestrator initialized with CoreMachine ({len(ALL_JOBS)} jobs, {len(ALL_HANDLERS)} handlers)")

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

            # Use actual CoreMachine job types from jobs/__init__.py:ALL_JOBS
            jobs.extend([
                {
                    'job_type': 'validate_raster_job',  # Actual job: jobs/validate_raster_job.py
                    'parameters': {
                        'source_path': source,
                        'dataset_id': request.dataset_id,
                        'resource_id': request.resource_id
                    }
                },
                {
                    'job_type': 'process_raster',  # Actual job: jobs/process_raster.py (handles COG creation)
                    'parameters': {
                        'source_path': source,
                        'output_container': 'silver',
                        'dataset_id': request.dataset_id,
                        'resource_id': request.resource_id
                    }
                }
            ])

        elif request.data_type == DataType.VECTOR.value:
            # Vector processing pipeline
            source = request.metadata.get('source_location', '')

            # Use actual CoreMachine job types from jobs/__init__.py:ALL_JOBS
            jobs.extend([
                {
                    'job_type': 'ingest_vector',  # Actual job: jobs/ingest_vector.py (handles validation + PostGIS import)
                    'parameters': {
                        'source_path': source,
                        'dataset_id': request.dataset_id,
                        'table_name': f"{request.dataset_id}_{request.resource_id}",
                        'schema': 'geo'
                    }
                }
            ])

        elif request.data_type == DataType.POINTCLOUD.value:
            # Point cloud processing
            # TODO: No point cloud job exists yet in jobs/__init__.py:ALL_JOBS
            # When implemented, uncomment:
            # jobs.append({
            #     'job_type': 'process_pointcloud',
            #     'parameters': {
            #         'source_path': request.metadata.get('source_location', ''),
            #         'dataset_id': request.dataset_id
            #     }
            # })
            logger.warning(f"Point cloud processing requested but no job exists yet for request {request.request_id}")

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

        NOTE - ISSUE #4 (INTENTIONAL): Duplicate Job Submission Logic
        ================================================================
        This method duplicates job submission logic from triggers/trigger_job_submit.py:
        - Job ID generation (SHA256 hash)
        - JobRecord creation
        - Database persistence via repository
        - Service Bus queue submission

        WHY INTENTIONAL (per Robert 26 OCT 2025):
        "duplicate job submission logic is intentional so we can test both systems
        - it will be reconciled in the near future"

        Platform submission and standard job submission can coexist during testing.
        When Platform is proven stable, consolidate to shared service.

        FUTURE REFACTORING OPTIONS:
        - Option A: Create shared JobSubmissionService (services/job_submission.py)
        - Option B: Platform makes HTTP call to standard /api/jobs/submit endpoint

        REFERENCE: PLATFORM_LAYER_FIXES_TODO.md Issue #4 (lines 286-363)
        STATUS: DEFERRED - Intentional duplication for testing
        ================================================================
        """
        try:
            # Add platform metadata to job parameters
            job_params = {
                **parameters,
                '_platform_request_id': request.request_id,
                '_platform_dataset': request.dataset_id
            }

            # Generate job ID (duplicates trigger_job_submit.py pattern)
            job_id = self._generate_job_id(job_type, job_params)

            # Create job record
            # CRITICAL: Use JobStatus enum (not string) - mirrors CoreMachine pattern
            job_record = JobRecord(
                job_id=job_id,
                job_type=job_type,
                status=JobStatus.QUEUED,  # Enum value - consistent with CoreMachine
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
        """Submit job to Service Bus jobs queue via repository pattern"""
        try:
            import uuid
            from infrastructure.service_bus import ServiceBusRepository
            from core.schema.queue import JobQueueMessage

            # Use repository pattern (handles connection pooling, retries, etc.)
            service_bus_repo = ServiceBusRepository()

            # Use Pydantic message model (automatic serialization + validation)
            # Platform always creates Stage 1 jobs
            queue_message = JobQueueMessage(
                job_id=job.job_id,
                job_type=job.job_type,
                parameters=job.parameters,
                stage=1,  # Platform creates Stage 1 jobs
                correlation_id=str(uuid.uuid4())[:8]
            )

            # Send via repository (uses config.service_bus_jobs_queue)
            message_id = service_bus_repo.send_message(
                config.service_bus_jobs_queue,
                queue_message
            )

            logger.info(f"✅ Submitted job {job.job_id} to jobs queue (message_id: {message_id}, queue: {config.service_bus_jobs_queue})")

        except Exception as e:
            logger.error(f"❌ Failed to submit job to queue: {e}")
            logger.error(f"   Job ID: {job.job_id}")
            logger.error(f"   Job Type: {job.job_type}")
            logger.error(f"   Traceback: {traceback.format_exc()}")
            raise

    def _generate_job_id(self, job_type: str, parameters: Dict[str, Any]) -> str:
        """
        Generate deterministic job ID (SHA256 full 64-char hash).

        CRITICAL: JobRecord requires minLength=64 for job_id validation.
        Must return FULL SHA256 hash (64 chars), not truncated.
        """
        # Remove platform metadata for ID generation
        clean_params = {
            k: v for k, v in parameters.items()
            if not k.startswith('_platform_')
        }

        canonical = f"{job_type}:{json.dumps(clean_params, sort_keys=True)}"
        return hashlib.sha256(canonical.encode()).hexdigest()  # FULL 64-char hash

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