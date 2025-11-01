# ============================================================================
# CLAUDE CONTEXT - PLATFORM API REQUEST HTTP TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: HTTP Trigger - Platform Service Layer orchestration endpoint
# PURPOSE: Handle external application requests (DDH) and orchestrate CoreMachine jobs
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: platform_request_submit (HTTP trigger function)
# INTERFACES: None
# PYDANTIC_MODELS: PlatformRequest, ApiRequest (renamed from PlatformRecord)
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
    from infrastructure import PlatformRepository, JobRepository
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
    # Import Platform models from core (Infrastructure-as-Code pattern - 29 OCT 2025)
    from core.models import (
        ApiRequest,
        PlatformRequestStatus,
        DataType,
        PlatformRequest
    )
    logger.info("✅ Platform trigger: core modules loaded successfully")
except ImportError as e:
    logger.error(f"❌ CRITICAL: Failed to import core modules")
    logger.error(f"   ImportError: {e}")
    logger.error(f"   Traceback: {traceback.format_exc()}")
    logger.error(f"   NOTE: JobRecord should be imported from core.models.job, not core.models")
    raise

# ============================================================================
# PLATFORM MODELS MOVED TO core/models/platform.py (29 OCT 2025)
# ============================================================================
# Platform models now use Infrastructure-as-Code pattern.
# Models imported above from core.models:
#   - ApiRequest (database schema definition, renamed from PlatformRecord)
#   - PlatformRequestStatus (enum)
#   - DataType (enum)
#   - PlatformRequest (DTO for HTTP requests)
#
# Tables renamed (29 OCT 2025):
#   - platform_requests → api_requests (client-facing layer)
#   - platform_request_jobs → orchestration_jobs (execution layer)
#
# These models are the SINGLE SOURCE OF TRUTH for database schema.
# PostgreSQL DDL is auto-generated from Pydantic field definitions.
#
# Benefits:
#   - Zero drift between Python models and database schema
#   - Consistent with JobRecord/TaskRecord pattern
#   - Update model → schema updates automatically
#
# Reference: PLATFORM_SCHEMA_COMPARISON.md
# ============================================================================

# ============================================================================
# REPOSITORY MOVED TO infrastructure/platform.py (29 OCT 2025)
# ============================================================================
# PlatformRepository class has been moved to infrastructure/platform.py
# Now uses SQL composition pattern for injection safety.
# Imported above via: from infrastructure import PlatformRepository
# ============================================================================

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
        platform_record = ApiRequest(
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

        # CRITICAL FIX (30 OCT 2025): Monkey-patch global callback function
        # The global CoreMachine instance in function_app.py processes all jobs via Service Bus.
        # We need to inject our handler into that global callback function.
        # See: function_app.py:269 _global_platform_callback
        import function_app

        # Store original callback (if any)
        original_callback = function_app._global_platform_callback

        # Replace with our handler (chain if original exists)
        def combined_callback(job_id: str, job_type: str, status: str, result: dict):
            logger.info(f"🔗 CALLBACK CHAIN: Entry point for job {job_id[:16]}, type={job_type}, status={status}")
            try:
                # Call our handler first
                self._handle_job_completion(job_id, job_type, status, result)
                logger.info(f"🔗 CALLBACK CHAIN: Platform handler completed successfully")
            except Exception as e:
                logger.error(f"🔗 CALLBACK CHAIN: Platform handler failed: {e}", exc_info=True)
                # Don't re-raise - callback failures should not break job completion

            # Call original handler if it wasn't just a pass statement
            if original_callback and original_callback.__code__.co_code != (lambda: None).__code__.co_code:
                logger.debug(f"🔗 CALLBACK CHAIN: Calling original callback (if any)")
                try:
                    original_callback(job_id, job_type, status, result)
                except Exception as e:
                    logger.warning(f"🔗 CALLBACK CHAIN: Original callback failed: {e}")

        function_app._global_platform_callback = combined_callback

        # Update the global CoreMachine's callback reference
        function_app.core_machine.on_job_complete = combined_callback

        logger.info(f"✅ PlatformOrchestrator initialized - callback injected into global CoreMachine")
        logger.info(f"   🔗 All jobs processed via Service Bus will now trigger Platform callbacks")
        logger.info(f"   🔍 Callback verification: {function_app.core_machine.on_job_complete.__name__}")

    async def process_platform_request(self, request: ApiRequest) -> List[str]:
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

    def _determine_jobs(self, request: ApiRequest) -> List[Dict[str, Any]]:
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
            # Check for hello_world_only testing flag (31 OCT 2025)
            if request.parameters.get('hello_world_only'):
                # Testing mode: ONLY hello_world job (no ingest_vector)
                jobs.append({
                    'job_type': 'hello_world',
                    'parameters': {
                        'message': f"Platform request {request.request_id}",
                        'n': request.parameters.get('n', 2)
                    }
                })
            else:
                # Normal vector processing pipeline
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

        return jobs

    async def _create_coremachine_job(
        self,
        request: ApiRequest,
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

            # Store in database (returns bool: True if created, False if exists)
            created = self.job_repo.create_job(job_record)

            # Submit to Service Bus jobs queue (use job_record, not the bool return)
            await self._submit_to_queue(job_record)

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

    def _handle_job_completion(self, job_id: str, job_type: str, status: str, result: Dict[str, Any]):
        """
        Handle job completion callback from CoreMachine.

        This method is called by CoreMachine when ANY job completes or fails.
        Platform uses this to:
        1. Chain jobs (e.g., ingest_vector → stac_catalog_vectors)
        2. Update Platform request status when all jobs complete
        3. Populate data_access URLs in Platform response

        Args:
            job_id: Job identifier
            job_type: Type of job that completed
            status: 'completed' or 'failed'
            result: Job result data (aggregated task results)

        Added: 30 OCT 2025 - Platform job orchestration
        """
        try:
            logger.info(f"🔔 Platform received job completion: {job_type} ({job_id[:16]}) - {status}")

            # Check if this job belongs to a Platform request
            job_record = self.job_repo.get_job(job_id)
            if not job_record:
                logger.warning(f"Job {job_id[:16]} not found - ignoring completion callback")
                return

            platform_request_id = job_record.parameters.get('_platform_request_id')
            if not platform_request_id:
                logger.debug(f"Job {job_id[:16]} not associated with Platform request - ignoring")
                return

            logger.info(f"   Platform request: {platform_request_id}")
            logger.info(f"   Job type: {job_type}")
            logger.info(f"   Status: {status}")

            # Handle based on job type and status
            if status == 'completed':
                logger.info(f"   ✅ Job completed successfully")

                # Job chaining logic - submit dependent jobs
                if job_type == 'ingest_vector':
                    # Vector ingestion complete → Submit STAC cataloging job
                    logger.info(f"   🔗 Chaining: ingest_vector → stac_catalog_vectors")

                    # Extract table name from job result
                    table_name = result.get('table_name') or job_record.parameters.get('table_name')
                    dataset_id = job_record.parameters.get('_platform_dataset') or job_record.parameters.get('dataset_id')

                    if table_name:
                        # Submit STAC catalog job
                        import asyncio
                        platform_request = self.platform_repo.get_request(platform_request_id)

                        stac_job_id = asyncio.run(self._create_coremachine_job(
                            platform_request,
                            'stac_catalog_vectors',
                            {
                                'schema': 'geo',
                                'table_name': table_name,
                                'collection_id': dataset_id or 'vectors',
                                'source_file': job_record.parameters.get('source_path')
                            }
                        ))

                        if stac_job_id:
                            logger.info(f"   ✅ Submitted stac_catalog_vectors job: {stac_job_id[:16]}")
                            self.platform_repo.add_job_to_request(
                                platform_request_id,
                                stac_job_id,
                                'stac_catalog_vectors'
                            )
                        else:
                            logger.error(f"   ❌ Failed to submit STAC catalog job")
                    else:
                        logger.warning(f"   ⚠️ No table_name in result - cannot chain to STAC job")

            elif status == 'failed':
                # Mark Platform request as failed
                logger.warning(f"   ❌ Job failed - marking Platform request as failed")
                self.platform_repo.update_request_status(
                    platform_request_id,
                    PlatformRequestStatus.FAILED
                )

            # Check if all jobs for Platform request are complete
            self._check_and_finalize_request(platform_request_id)

        except Exception as e:
            logger.error(f"Error in job completion handler: {e}", exc_info=True)
            # Don't raise - callback failures should not affect job completion

    def _check_and_finalize_request(self, platform_request_id: str):
        """
        Check if all jobs for Platform request are complete and finalize if so.

        Finalization includes:
        1. Mark Platform request as COMPLETED
        2. Populate data_access URLs (OGC Features, STAC, web map)
        3. Aggregate results from all jobs

        Args:
            platform_request_id: Platform request identifier

        Added: 30 OCT 2025 - Platform request finalization
        """
        try:
            # Get all jobs for this Platform request
            platform_request = self.platform_repo.get_request(platform_request_id)
            if not platform_request:
                logger.warning(f"Platform request {platform_request_id} not found")
                return

            # Get jobs from the JSONB jobs field
            jobs_dict = platform_request.jobs or {}
            if not jobs_dict:
                logger.warning(f"No jobs found for Platform request {platform_request_id}")
                return

            # Check if all jobs are complete (completed or failed)
            all_complete = True
            any_failed = False
            job_results = {}

            for job_key, job_info in jobs_dict.items():
                job_id = job_info.get('job_id')
                if job_id:
                    job_record = self.job_repo.get_job(job_id)
                    if job_record:
                        job_status = job_record.status.value if hasattr(job_record.status, 'value') else job_record.status

                        if job_status not in ['completed', 'failed']:
                            all_complete = False
                            break

                        if job_status == 'failed':
                            any_failed = True

                        # Collect results
                        job_results[job_record.job_type] = {
                            'status': job_status,
                            'result': job_record.result_data
                        }

            if not all_complete:
                logger.debug(f"Platform request {platform_request_id} - not all jobs complete yet")
                return

            logger.info(f"🏁 All jobs complete for Platform request {platform_request_id}")

            # Determine final status
            if any_failed:
                final_status = PlatformRequestStatus.FAILED
                logger.warning(f"   ❌ At least one job failed - marking request as FAILED")
            else:
                final_status = PlatformRequestStatus.COMPLETED
                logger.info(f"   ✅ All jobs succeeded - marking request as COMPLETED")

                # Populate data_access URLs (only for successful completions)
                data_access_urls = self._generate_data_access_urls(platform_request, job_results)
                logger.info(f"   📍 Generated data access URLs: {list(data_access_urls.keys())}")

                # TODO: Store data_access_urls in Platform request metadata
                # self.platform_repo.update_data_access_urls(platform_request_id, data_access_urls)

            # Update Platform request status
            self.platform_repo.update_request_status(platform_request_id, final_status)
            logger.info(f"   ✅ Platform request {platform_request_id} finalized: {final_status.value}")

        except Exception as e:
            logger.error(f"Error finalizing Platform request: {e}", exc_info=True)

    def _generate_data_access_urls(self, platform_request: ApiRequest, job_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate data access URLs for completed Platform request.

        Args:
            platform_request: Platform request record
            job_results: Dictionary of job_type → {status, result}

        Returns:
            Dictionary with OGC Features, STAC, and web map URLs

        Added: 30 OCT 2025 - Data access URL generation
        """
        base_url = config.function_app_url or "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net"
        web_map_url = "https://rmhazuregeo.z13.web.core.windows.net"

        # Extract data from job results
        ingest_result = job_results.get('ingest_vector', {}).get('result', {})
        stac_result = job_results.get('stac_catalog_vectors', {}).get('result', {})

        table_name = ingest_result.get('table_name')
        collection_id = stac_result.get('collection_id') or platform_request.dataset_id

        urls = {}

        # PostGIS info
        if table_name:
            urls['postgis'] = {
                'schema': 'geo',
                'table': table_name
            }

            # OGC Features API URLs
            urls['ogc_features'] = {
                'collection_url': f"{base_url}/api/features/collections/{table_name}",
                'items_url': f"{base_url}/api/features/collections/{table_name}/items",
                'web_map_url': f"{web_map_url}/?collection={table_name}"
            }

        # STAC API URLs
        if collection_id:
            urls['stac'] = {
                'collection_id': collection_id,
                'collection_url': f"{base_url}/api/collections/{collection_id}",
                'items_url': f"{base_url}/api/collections/{collection_id}/items",
                'search_url': f"{base_url}/api/search"
            }

        return urls

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