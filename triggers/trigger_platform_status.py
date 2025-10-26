# ============================================================================
# CLAUDE CONTEXT - PLATFORM REQUEST STATUS TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: HTTP Trigger - Platform request status monitoring endpoint
# PURPOSE: Query status of platform requests and their associated CoreMachine jobs
# LAST_REVIEWED: 25 OCT 2025
# EXPORTS: platform_request_status (HTTP trigger function)
# INTERFACES: None
# PYDANTIC_MODELS: None
# DEPENDENCIES: azure-functions, psycopg
# SOURCE: Database queries
# SCOPE: Platform request monitoring
# VALIDATION: None
# PATTERNS: Repository
# ENTRY_POINTS: GET /api/platform/status/{request_id}
# INDEX:
#   - Imports: Line 20
#   - Repository Extension: Line 40
#   - HTTP Handler: Line 150
# ============================================================================

"""
Platform Request Status HTTP Trigger

Provides monitoring endpoints for platform requests.
Shows the status of the request and all associated CoreMachine jobs.
"""

import json
import logging
from typing import Dict, Any, Optional, List

import azure.functions as func

from triggers.trigger_platform import PlatformRepository, PlatformRequestStatus

# Configure logging
logger = logging.getLogger(__name__)

# ============================================================================
# EXTENDED PLATFORM REPOSITORY
# ============================================================================

class PlatformStatusRepository(PlatformRepository):
    """Extended repository with status query methods"""

    def get_request_with_jobs(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Get platform request with all associated job details"""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Get request details
                cur.execute("""
                    SELECT
                        r.*,
                        COALESCE(
                            json_agg(
                                json_build_object(
                                    'job_id', j.job_id,
                                    'job_type', j.job_type,
                                    'status', j.status,
                                    'stage', j.stage,
                                    'created_at', j.created_at,
                                    'updated_at', j.updated_at
                                ) ORDER BY j.created_at
                            ) FILTER (WHERE j.job_id IS NOT NULL),
                            '[]'::json
                        ) as jobs
                    FROM platform.requests r
                    LEFT JOIN LATERAL (
                        SELECT
                            pj.job_id,
                            pj.job_type,
                            j.status,
                            j.stage,
                            j.created_at,
                            j.updated_at
                        FROM platform.request_jobs pj
                        JOIN app.jobs j ON j.job_id = pj.job_id
                        WHERE pj.request_id = r.request_id
                    ) j ON true
                    WHERE r.request_id = %s
                    GROUP BY r.request_id, r.dataset_id, r.resource_id, r.version_id,
                             r.data_type, r.status, r.job_ids, r.parameters,
                             r.metadata, r.result_data, r.created_at, r.updated_at
                """, (request_id,))

                row = cur.fetchone()
                if not row:
                    return None

                # Build response
                return {
                    'request_id': row[0],
                    'dataset_id': row[1],
                    'resource_id': row[2],
                    'version_id': row[3],
                    'data_type': row[4],
                    'status': row[5],
                    'job_ids': row[6] if row[6] else [],
                    'parameters': row[7] if row[7] else {},
                    'metadata': row[8] if row[8] else {},
                    'result_data': row[9] if row[9] else None,
                    'created_at': row[10].isoformat() if row[10] else None,
                    'updated_at': row[11].isoformat() if row[11] else None,
                    'jobs': row[12] if len(row) > 12 else []
                }

    def get_all_requests(self, limit: int = 100, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all platform requests with optional filtering"""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                query = """
                    SELECT
                        request_id,
                        dataset_id,
                        resource_id,
                        version_id,
                        data_type,
                        status,
                        array_length(job_ids::text[], 1) as job_count,
                        created_at,
                        updated_at
                    FROM platform.requests
                """

                params = []
                if status:
                    query += " WHERE status = %s"
                    params.append(status)

                query += " ORDER BY created_at DESC LIMIT %s"
                params.append(limit)

                cur.execute(query, params)
                rows = cur.fetchall()

                return [
                    {
                        'request_id': row[0],
                        'dataset_id': row[1],
                        'resource_id': row[2],
                        'version_id': row[3],
                        'data_type': row[4],
                        'status': row[5],
                        'job_count': row[6] if row[6] else 0,
                        'created_at': row[7].isoformat() if row[7] else None,
                        'updated_at': row[8].isoformat() if row[8] else None
                    }
                    for row in rows
                ]

    def check_and_update_completion(self, request_id: str) -> bool:
        """
        Check if all jobs are complete and update platform request status.
        Implements "last job turns out the lights" pattern.
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Check job statuses
                cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE j.status = 'completed') as completed,
                        COUNT(*) FILTER (WHERE j.status = 'failed') as failed,
                        COUNT(*) FILTER (WHERE j.status IN ('pending', 'processing')) as in_progress
                    FROM platform.request_jobs pj
                    JOIN app.jobs j ON j.job_id = pj.job_id
                    WHERE pj.request_id = %s
                """, (request_id,))

                row = cur.fetchone()
                if not row or row[0] == 0:  # No jobs
                    return False

                total, completed, failed, in_progress = row

                # Determine platform request status
                if in_progress > 0:
                    # Still processing
                    new_status = PlatformRequestStatus.PROCESSING
                elif failed > 0:
                    # Any failures = request failed
                    new_status = PlatformRequestStatus.FAILED
                elif completed == total:
                    # All completed successfully
                    new_status = PlatformRequestStatus.COMPLETED
                else:
                    # Shouldn't happen
                    logger.warning(f"Unexpected status combination for {request_id}")
                    return False

                # Update platform request status
                cur.execute("""
                    UPDATE platform.requests
                    SET status = %s, updated_at = NOW()
                    WHERE request_id = %s AND status != %s
                """, (new_status.value, request_id, new_status.value))

                if cur.rowcount > 0:
                    conn.commit()
                    logger.info(f"Updated platform request {request_id} to {new_status.value}")
                    return True

                return False

# ============================================================================
# HTTP HANDLERS
# ============================================================================

async def platform_request_status(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get status of a platform request.

    GET /api/platform/status/{request_id}
    GET /api/platform/status  (lists all requests)
    """
    logger.info("Platform status endpoint called")

    try:
        repo = PlatformStatusRepository()

        # Check if specific request_id provided
        request_id = req.route_params.get('request_id')

        if request_id:
            # Get specific request with job details
            result = repo.get_request_with_jobs(request_id)

            if not result:
                return func.HttpResponse(
                    json.dumps({
                        "success": False,
                        "error": f"Platform request {request_id} not found"
                    }),
                    status_code=404,
                    headers={"Content-Type": "application/json"}
                )

            # Check and update completion status
            repo.check_and_update_completion(request_id)

            # Calculate summary statistics
            jobs = result.get('jobs', [])
            job_stats = {
                'total': len(jobs),
                'completed': sum(1 for j in jobs if j.get('status') == 'completed'),
                'failed': sum(1 for j in jobs if j.get('status') == 'failed'),
                'processing': sum(1 for j in jobs if j.get('status') == 'processing'),
                'pending': sum(1 for j in jobs if j.get('status') == 'pending')
            }

            # Add statistics to result
            result['job_statistics'] = job_stats

            # Add helpful URLs
            result['urls'] = {
                'jobs': [f"/api/jobs/status/{j['job_id']}" for j in jobs]
            }

            return func.HttpResponse(
                json.dumps(result, indent=2),
                status_code=200,
                headers={"Content-Type": "application/json"}
            )

        else:
            # List all requests
            limit = int(req.params.get('limit', 100))
            status_filter = req.params.get('status')

            requests = repo.get_all_requests(limit, status_filter)

            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "count": len(requests),
                    "requests": requests
                }, indent=2),
                status_code=200,
                headers={"Content-Type": "application/json"}
            )

    except Exception as e:
        logger.error(f"Platform status query failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e)
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )