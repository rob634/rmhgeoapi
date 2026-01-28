# ============================================================================
# PLATFORM JOB SUBMISSION SERVICE
# ============================================================================
# STATUS: Service layer - Job creation and Service Bus submission
# PURPOSE: Create CoreMachine jobs and submit to processing queue
# CREATED: 27 JAN 2026 (extracted from trigger_platform.py)
# EXPORTS: create_and_submit_job, generate_unpublish_request_id, RASTER_JOB_FALLBACKS
# DEPENDENCIES: infrastructure.JobRepository, infrastructure.ServiceBusRepository
# ============================================================================
"""
Platform Job Submission Service.

Handles CoreMachine job creation and Service Bus queue submission.
Includes size-based fallback routing for raster jobs.

Exports:
    create_and_submit_job: Create job record and submit to queue
    generate_unpublish_request_id: Generate deterministic ID for unpublish operations
    RASTER_JOB_FALLBACKS: Mapping of job types to fallback alternatives
"""

import hashlib
import json
import logging
import uuid
from typing import Dict, Any, Optional

from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.SERVICE, "platform_job_submit")

# Import config
from config import get_config

# Import infrastructure
from infrastructure import JobRepository
from infrastructure.service_bus import ServiceBusRepository

# Import core models
from core.models.job import JobRecord
from core.models.enums import JobStatus
from core.schema.queue import JobQueueMessage


# Size-based job fallback routing (04 DEC 2025, updated 12 JAN 2026)
# When validator fails with size error, automatically try alternate job type
# process_raster_docker has no fallback - it handles all sizes
RASTER_JOB_FALLBACKS = {
    'process_raster_v2': 'process_large_raster_v2',
    'process_large_raster_v2': 'process_raster_v2',
    # Docker job handles all sizes - no automatic fallback needed
    # 'process_raster_docker': None,
}


def generate_unpublish_request_id(data_type: str, internal_id: str) -> str:
    """
    Generate deterministic request ID for unpublish operations.

    Uses different hash input than create operations to avoid collision.
    Same unpublish parameters will always generate same request ID (idempotent).

    Args:
        data_type: "vector" or "raster"
        internal_id: table_name (vector) or stac_item_id (raster)

    Returns:
        32-character hex string (SHA256 prefix)
    """
    # Include "unpublish" prefix to avoid collision with create request IDs
    combined = f"unpublish-{data_type}|{internal_id}"
    hash_hex = hashlib.sha256(combined.encode('utf-8')).hexdigest()
    return hash_hex[:32]


def create_and_submit_job(
    job_type: str,
    parameters: Dict[str, Any],
    platform_request_id: str
) -> Optional[str]:
    """
    Create CoreMachine job and submit to Service Bus queue.

    Uses the job class's validation method to:
    1. Validate parameters against schema
    2. Run pre-flight resource validators (e.g., blob_exists_with_size)
    3. Generate deterministic job ID
    4. Create job record and queue message

    Supports automatic fallback for size-based routing (04 DEC 2025):
    If validator fails with size-related error (too_large/too_small),
    automatically retries with fallback job type from RASTER_JOB_FALLBACKS.

    Args:
        job_type: CoreMachine job type (e.g., 'process_vector', 'process_raster_v2')
        parameters: Job parameters translated from DDH request
        platform_request_id: Platform request ID for tracking

    Returns:
        job_id if successful, None if failed

    Raises:
        ValueError: If pre-flight validation fails (e.g., blob doesn't exist)
    """
    from jobs import ALL_JOBS

    config = get_config()

    def _try_create_job(current_job_type: str, job_params: Dict[str, Any], allow_fallback: bool = True) -> str:
        """
        Attempt to create and submit job, with optional fallback on size validation failure.

        Args:
            current_job_type: Job type to attempt
            job_params: Parameters including platform tracking
            allow_fallback: Whether to try fallback job on size error (prevents infinite recursion)

        Returns:
            job_id if successful

        Raises:
            ValueError: If validation fails and no fallback available/applicable
        """
        job_class = ALL_JOBS.get(current_job_type)
        if not job_class:
            raise ValueError(f"Unknown job type: {current_job_type}")

        try:
            # Run validation (includes resource validators like blob_exists_with_size)
            # This will raise ValueError if validation fails
            validated_params = job_class.validate_job_parameters(job_params)
            logger.info(f"Pre-flight validation passed for {current_job_type}")

            # Generate deterministic job ID
            # Remove platform metadata for ID generation (so same CoreMachine params = same job)
            clean_params = {k: v for k, v in validated_params.items() if not k.startswith('_')}
            canonical = f"{current_job_type}:{json.dumps(clean_params, sort_keys=True)}"
            job_id = hashlib.sha256(canonical.encode()).hexdigest()

            # Create job record with correct total_stages from job class
            job_record = JobRecord(
                job_id=job_id,
                job_type=current_job_type,
                status=JobStatus.QUEUED,
                stage=1,
                total_stages=len(job_class.stages),  # FIX: Set from job class stages definition
                parameters=validated_params,
                metadata={
                    'platform_request': platform_request_id,
                    'created_by': 'platform_trigger'
                }
            )

            # Store in database
            job_repo = JobRepository()
            job_repo.create_job(job_record)

            # Record JOB_CREATED event (25 JAN 2026 - Job Monitor Interface)
            try:
                from infrastructure import JobEventRepository
                from core.models.job_event import JobEventType, JobEventStatus

                event_repo = JobEventRepository()
                event_repo.record_job_event(
                    job_id=job_id,
                    event_type=JobEventType.JOB_CREATED,
                    event_status=JobEventStatus.SUCCESS,
                    event_data={
                        'job_type': current_job_type,
                        'total_stages': len(job_class.stages),
                        'platform_request_id': platform_request_id
                    }
                )
            except Exception as event_err:
                logger.warning(f"Failed to record JOB_CREATED event: {event_err}")

            # Submit to Service Bus
            service_bus = ServiceBusRepository()
            queue_message = JobQueueMessage(
                job_id=job_id,
                job_type=current_job_type,
                parameters=validated_params,
                stage=1,
                correlation_id=str(uuid.uuid4())[:8]
            )

            message_id = service_bus.send_message(
                config.service_bus_jobs_queue,
                queue_message
            )

            logger.info(f"Submitted job {job_id[:16]} to queue (message_id: {message_id})")
            return job_id

        except ValueError as e:
            error_msg = str(e).lower()

            # Check if this is a size-related validation failure
            is_size_error = any(pattern in error_msg for pattern in [
                'too_large', 'too large', 'exceeds maximum size',
                'too_small', 'too small', '< 100mb'
            ])

            fallback_job = RASTER_JOB_FALLBACKS.get(current_job_type)

            if is_size_error and fallback_job and allow_fallback:
                logger.info(f"Size validation failed for {current_job_type}, trying fallback: {fallback_job}")
                # Retry with fallback job type (allow_fallback=False prevents infinite loop)
                return _try_create_job(fallback_job, job_params, allow_fallback=False)

            # Re-raise if not a size error, no fallback available, or already tried fallback
            raise

    try:
        # Add platform tracking to parameters
        job_params = {
            **parameters,
            '_platform_request_id': platform_request_id
        }

        return _try_create_job(job_type, job_params, allow_fallback=True)

    except ValueError as e:
        # Re-raise validation errors - caller will handle as 400 Bad Request
        logger.warning(f"Pre-flight validation failed: {e}")
        raise

    except Exception as e:
        logger.error(f"Failed to create/submit job: {e}", exc_info=True)
        return None
