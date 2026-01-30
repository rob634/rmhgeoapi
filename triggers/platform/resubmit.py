# ============================================================================
# PLATFORM RESUBMIT TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Trigger layer - POST /api/platform/resubmit
# PURPOSE: Resubmit failed jobs via platform identifiers (DDH)
# CREATED: 30 JAN 2026
# EXPORTS: platform_resubmit
# DEPENDENCIES: triggers.jobs.resubmit.JobResubmitHandler, infrastructure.platform
# ============================================================================
"""
Platform Resubmit Trigger.

Exposes job resubmit functionality through the platform API layer.
Allows external applications (DDH) to retry failed jobs using their
native identifiers (dataset_id, resource_id, version_id) rather than
internal job IDs.

Lookup Resolution:
    1. DDH Identifiers → platform_requests table → job_id
    2. Request ID → platform_requests table → job_id
    3. Job ID → direct lookup

Uses JobResubmitHandler for the actual cleanup and resubmit logic.
"""

import json
import logging
import traceback
from typing import Dict, Any, Optional, Tuple

import azure.functions as func

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "platform_resubmit")


class PlatformResubmitHandler:
    """
    Handler for platform resubmit operations.

    Translates platform identifiers to job IDs and delegates to
    JobResubmitHandler for the actual resubmit logic.
    """

    def __init__(self):
        """Initialize with repository access."""
        from infrastructure import RepositoryFactory
        from infrastructure.platform import PlatformRequestRepository

        self.repos = RepositoryFactory.create_repositories()
        self.job_repo = self.repos['job_repo']
        self.platform_repo = PlatformRequestRepository()

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle platform resubmit request.

        Args:
            req: HTTP request with identifier options

        Returns:
            HTTP response with resubmit result
        """
        try:
            # Parse request body
            body = self._parse_body(req)
            if not body:
                return self._error_response(
                    "Request body is required",
                    "ValidationError",
                    400
                )

            # Extract options
            dry_run = body.get('dry_run', False)
            delete_blobs = body.get('delete_blobs', False)
            force = body.get('force', False)

            # Resolve job_id from various identifier types
            job_id, platform_refs, error = self._resolve_job_id(body)

            if error:
                return error

            if not job_id:
                return self._error_response(
                    "Could not resolve job_id from provided identifiers",
                    "NotFound",
                    404
                )

            logger.info(f"Platform resubmit requested: job={job_id[:16]}...")
            if platform_refs:
                logger.info(f"  Platform refs: {platform_refs}")

            # Delegate to JobResubmitHandler
            from triggers.jobs.resubmit import JobResubmitHandler

            resubmit_handler = JobResubmitHandler()

            # Get existing job
            job = resubmit_handler.job_repo.get_job(job_id)
            if not job:
                return self._error_response(
                    f"Job not found: {job_id}",
                    "NotFound",
                    404
                )

            # Check if job is currently processing (unless force=True)
            if job.status.value == 'processing' and not force:
                return func.HttpResponse(
                    json.dumps({
                        "success": False,
                        "error": "Job is currently processing. Use force=true to resubmit anyway.",
                        "job_status": job.status.value,
                        "job_id": job_id,
                        "platform_refs": platform_refs,
                        "error_type": "JobInProgress"
                    }),
                    status_code=409,
                    mimetype="application/json"
                )

            # Extract job info for resubmission
            job_type = job.job_type
            parameters = job.parameters.copy() if job.parameters else {}

            # Remove internal parameters
            internal_keys = [k for k in parameters.keys() if k.startswith('_')]
            for key in internal_keys:
                del parameters[key]

            logger.info(f"  Job type: {job_type}")
            logger.info(f"  Current status: {job.status.value}")

            # Plan cleanup
            cleanup_plan = resubmit_handler._plan_cleanup(job, parameters)

            if dry_run:
                return func.HttpResponse(
                    json.dumps({
                        "success": True,
                        "dry_run": True,
                        "job_id": job_id,
                        "job_type": job_type,
                        "job_status": job.status.value,
                        "platform_refs": platform_refs,
                        "cleanup_plan": cleanup_plan,
                        "parameters": parameters,
                        "message": "Dry run - no changes made. Set dry_run=false to execute."
                    }, default=str),
                    status_code=200,
                    mimetype="application/json"
                )

            # Execute cleanup
            cleanup_result = resubmit_handler._execute_cleanup(job, cleanup_plan, delete_blobs)

            # Resubmit job
            new_job_id = resubmit_handler._resubmit_job(job_type, parameters)

            # TODO: Update platform request record with new job_id when
            # PlatformRequestRepository.update_request() is implemented.
            # For now, the new job can be tracked via the response.

            logger.info(f"✅ Platform resubmit complete: {job_id[:16]}... → {new_job_id[:16]}...")

            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "original_job_id": job_id,
                    "new_job_id": new_job_id,
                    "job_type": job_type,
                    "platform_refs": platform_refs,
                    "cleanup_summary": cleanup_result,
                    "message": "Job resubmitted successfully",
                    "monitor_url": f"/api/platform/status/{new_job_id}"
                }, default=str),
                status_code=202,
                mimetype="application/json"
            )

        except Exception as e:
            logger.error(f"Platform resubmit failed: {e}")
            logger.error(traceback.format_exc())
            return self._error_response(str(e), type(e).__name__, 500)

    def _parse_body(self, req: func.HttpRequest) -> Optional[Dict[str, Any]]:
        """Parse request body."""
        try:
            return req.get_json()
        except ValueError:
            return None

    def _resolve_job_id(
        self,
        body: Dict[str, Any]
    ) -> Tuple[Optional[str], Optional[Dict[str, str]], Optional[func.HttpResponse]]:
        """
        Resolve job_id from various identifier types.

        Priority:
            1. Direct job_id
            2. Request ID → lookup platform_requests
            3. DDH Identifiers → lookup platform_requests

        Returns:
            Tuple of (job_id, platform_refs dict, error response if any)
        """
        platform_refs = {}

        # Option 1: Direct job_id
        if 'job_id' in body:
            job_id = body['job_id']
            # Try to find associated platform request
            try:
                request = self.platform_repo.get_request_by_job(job_id)
                if request:
                    platform_refs = {
                        'request_id': request.get('request_id'),
                        'dataset_id': request.get('dataset_id'),
                        'resource_id': request.get('resource_id'),
                        'version_id': request.get('version_id'),
                    }
            except Exception:
                pass
            return job_id, platform_refs or None, None

        # Option 2: Request ID
        if 'request_id' in body:
            request_id = body['request_id']
            try:
                request = self.platform_repo.get_request(request_id)
                if not request:
                    return None, None, self._error_response(
                        f"Platform request not found: {request_id}",
                        "NotFound",
                        404
                    )

                platform_refs = {
                    'request_id': request_id,
                    'dataset_id': request.get('dataset_id'),
                    'resource_id': request.get('resource_id'),
                    'version_id': request.get('version_id'),
                }

                # Get job_id from request
                job_id = request.get('job_id')
                if not job_id:
                    # Check jobs_created array
                    jobs_created = request.get('jobs_created', [])
                    if jobs_created:
                        # Use first job (or could allow specifying which one)
                        job_id = jobs_created[0]

                if not job_id:
                    return None, platform_refs, self._error_response(
                        f"No job associated with platform request: {request_id}",
                        "NotFound",
                        404
                    )

                return job_id, platform_refs, None

            except Exception as e:
                return None, None, self._error_response(
                    f"Error looking up platform request: {e}",
                    "LookupError",
                    500
                )

        # Option 3: DDH Identifiers
        dataset_id = body.get('dataset_id')
        resource_id = body.get('resource_id')
        version_id = body.get('version_id')

        if dataset_id and resource_id and version_id:
            try:
                request = self.platform_repo.get_request_by_ddh_ids(
                    dataset_id=dataset_id,
                    resource_id=resource_id,
                    version_id=version_id
                )

                if not request:
                    return None, None, self._error_response(
                        f"No platform request found for dataset_id={dataset_id}, "
                        f"resource_id={resource_id}, version_id={version_id}",
                        "NotFound",
                        404
                    )

                platform_refs = {
                    'request_id': request.get('request_id'),
                    'dataset_id': dataset_id,
                    'resource_id': resource_id,
                    'version_id': version_id,
                }

                job_id = request.get('job_id')
                if not job_id:
                    jobs_created = request.get('jobs_created', [])
                    if jobs_created:
                        job_id = jobs_created[0]

                if not job_id:
                    return None, platform_refs, self._error_response(
                        f"No job associated with platform request for these identifiers",
                        "NotFound",
                        404
                    )

                return job_id, platform_refs, None

            except Exception as e:
                return None, None, self._error_response(
                    f"Error looking up by DDH identifiers: {e}",
                    "LookupError",
                    500
                )

        # No valid identifier provided
        return None, None, self._error_response(
            "Must provide one of: job_id, request_id, or (dataset_id + resource_id + version_id)",
            "ValidationError",
            400
        )

    def _error_response(
        self,
        message: str,
        error_type: str,
        status_code: int
    ) -> func.HttpResponse:
        """Create standardized error response."""
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": message,
                "error_type": error_type
            }),
            status_code=status_code,
            mimetype="application/json"
        )


# Singleton handler
_handler = None


def get_handler() -> PlatformResubmitHandler:
    """Get or create handler instance."""
    global _handler
    if _handler is None:
        _handler = PlatformResubmitHandler()
    return _handler


def platform_resubmit(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger for platform resubmit.

    POST /api/platform/resubmit

    Request Body Options:

        Option 1 - By DDH Identifiers (Preferred):
        {
            "dataset_id": "aerial-imagery-2024",
            "resource_id": "site-alpha",
            "version_id": "v1.0",
            "dry_run": true,
            "delete_blobs": false,
            "force": false
        }

        Option 2 - By Request ID:
        {
            "request_id": "a3f2c1b8e9d7f6a5...",
            "dry_run": true
        }

        Option 3 - By Job ID:
        {
            "job_id": "abc123...",
            "dry_run": true
        }

    Options:
        dry_run: Preview cleanup without executing (default: false)
        delete_blobs: Also delete COG files from storage (default: false)
        force: Resubmit even if job is currently processing (default: false)

    Response:
        {
            "success": true,
            "original_job_id": "abc123...",
            "new_job_id": "def456...",
            "job_type": "process_raster_v2",
            "platform_refs": {
                "request_id": "...",
                "dataset_id": "...",
                "resource_id": "...",
                "version_id": "..."
            },
            "cleanup_summary": {
                "tasks_deleted": 5,
                "job_deleted": true,
                "tables_dropped": [],
                "stac_items_deleted": ["item-123"],
                "blobs_deleted": []
            },
            "message": "Job resubmitted successfully",
            "monitor_url": "/api/platform/status/def456..."
        }
    """
    handler = get_handler()
    return handler.handle(req)
