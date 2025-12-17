"""
Platform Repository - Thin Tracking Pattern.

Provides thin tracking for Platform → CoreMachine mapping. Platform creates
one CoreMachine job per request and stores the 1:1 mapping.

Architecture:
    - Single table (app.api_requests)
    - 1:1 mapping: request_id → job_id
    - Status delegated to CoreMachine

Methods:
    create_request(request) - Store request → job mapping
    get_request(request_id) - Lookup by Platform request ID
    get_request_by_job(job_id) - Reverse lookup by CoreMachine job ID
    get_all_requests(limit, dataset_id) - List requests with filtering

Exports:
    ApiRequestRepository: Platform request tracking repository
    PlatformRepository: Alias for ApiRequestRepository
"""

import json
from datetime import datetime
from typing import Dict, Any, Optional, List
from psycopg import sql

from infrastructure.postgresql import PostgreSQLRepository

# Import Platform models from core
from core.models import ApiRequest

# Logger setup
from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "platform")


# ============================================================================
# API REQUEST REPOSITORY - Thin Tracking (22 NOV 2025)
# ============================================================================

class ApiRequestRepository(PostgreSQLRepository):
    """
    Repository for Platform API requests - THIN TRACKING ONLY.

    Simplified to single table with 1:1 request → job mapping.
    Status is delegated to CoreMachine - Platform just stores the mapping.

    Table: app.api_requests
        request_id VARCHAR(32) PRIMARY KEY  -- SHA256(dataset|resource|version)[:32]
        dataset_id VARCHAR(255) NOT NULL
        resource_id VARCHAR(255) NOT NULL
        version_id VARCHAR(50) NOT NULL
        job_id VARCHAR(64) NOT NULL         -- CoreMachine job ID
        data_type VARCHAR(50) NOT NULL
        created_at TIMESTAMPTZ DEFAULT NOW()

    Usage:
        repo = ApiRequestRepository()

        # Create mapping
        request = ApiRequest(
            request_id=generate_platform_request_id(dataset, resource, version),
            dataset_id=dataset,
            resource_id=resource,
            version_id=version,
            job_id=coremachine_job_id,
            data_type="vector"
        )
        repo.create_request(request)

        # Lookup for DDH status poll
        request = repo.get_request(request_id)
        job_status = job_repo.get_job(request.job_id)  # Delegate to CoreMachine
    """

    def __init__(self):
        super().__init__()
        # Schema deployed centrally via POST /api/db/schema/redeploy?confirm=yes
        # No _ensure_schema() call - fail fast if schema missing

    def create_request(self, request: ApiRequest) -> ApiRequest:
        """
        Create a new Platform request record (thin tracking).

        Uses ON CONFLICT to handle idempotent submissions:
        - Same DDH identifiers = same request_id (SHA256 hash)
        - If already exists, returns existing record

        Args:
            request: ApiRequest with request_id, DDH IDs, job_id

        Returns:
            ApiRequest (newly created or existing)
        """
        with self._error_context("platform request creation", request.request_id):
            query = sql.SQL("""
                INSERT INTO {}.{}
                (request_id, dataset_id, resource_id, version_id, job_id, data_type, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (request_id) DO NOTHING
                RETURNING *
            """).format(
                sql.Identifier(self.schema_name),
                sql.Identifier("api_requests")
            )

            params = (
                request.request_id,
                request.dataset_id,
                request.resource_id,
                request.version_id,
                request.job_id,
                request.data_type,
                request.created_at or datetime.utcnow()
            )

            row = self._execute_query(query, params, fetch='one')

            if row:
                logger.info(f"Created platform request: {request.request_id} → job {request.job_id}")
                return self._row_to_record(row)
            else:
                # Request already exists (idempotent), fetch it
                existing = self.get_request(request.request_id)
                if existing:
                    logger.info(f"Platform request already exists: {request.request_id}")
                    return existing
                raise RuntimeError(f"Failed to create or fetch request {request.request_id}")

    def get_request(self, request_id: str) -> Optional[ApiRequest]:
        """
        Get Platform request by request_id.

        Args:
            request_id: SHA256(dataset|resource|version)[:32]

        Returns:
            ApiRequest or None if not found
        """
        with self._error_context("platform request retrieval", request_id):
            query = sql.SQL("""
                SELECT * FROM {}.{} WHERE request_id = %s
            """).format(
                sql.Identifier(self.schema_name),
                sql.Identifier("api_requests")
            )

            row = self._execute_query(query, (request_id,), fetch='one')
            return self._row_to_record(row) if row else None

    def get_request_by_job(self, job_id: str) -> Optional[ApiRequest]:
        """
        Reverse lookup: Get Platform request by CoreMachine job_id.

        Useful for:
        - CoreMachine callbacks (if ever needed)
        - Debugging which Platform request created a job

        Args:
            job_id: CoreMachine job ID

        Returns:
            ApiRequest or None if not found
        """
        with self._error_context("platform request lookup by job", job_id):
            query = sql.SQL("""
                SELECT * FROM {}.{} WHERE job_id = %s
            """).format(
                sql.Identifier(self.schema_name),
                sql.Identifier("api_requests")
            )

            row = self._execute_query(query, (job_id,), fetch='one')
            return self._row_to_record(row) if row else None

    def get_request_by_ddh_ids(
        self,
        dataset_id: str,
        resource_id: str,
        version_id: str
    ) -> Optional[ApiRequest]:
        """
        Lookup Platform request by DDH identifiers.

        Generates the request_id from DDH identifiers and performs lookup.
        Useful for Platform unpublish endpoints that receive DDH IDs.

        Args:
            dataset_id: DDH dataset identifier
            resource_id: DDH resource identifier
            version_id: DDH version identifier

        Returns:
            ApiRequest or None if not found
        """
        from config import generate_platform_request_id

        request_id = generate_platform_request_id(dataset_id, resource_id, version_id)
        return self.get_request(request_id)

    def get_all_requests(
        self,
        limit: int = 100,
        dataset_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List Platform requests with optional filtering.

        Args:
            limit: Maximum number of results (default 100)
            dataset_id: Filter by DDH dataset ID (optional)

        Returns:
            List of request dictionaries (for API responses)
        """
        with self._error_context("list platform requests", f"limit={limit}"):
            if dataset_id:
                query = sql.SQL("""
                    SELECT * FROM {}.{}
                    WHERE dataset_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """).format(
                    sql.Identifier(self.schema_name),
                    sql.Identifier("api_requests")
                )
                params = (dataset_id, limit)
            else:
                query = sql.SQL("""
                    SELECT * FROM {}.{}
                    ORDER BY created_at DESC
                    LIMIT %s
                """).format(
                    sql.Identifier(self.schema_name),
                    sql.Identifier("api_requests")
                )
                params = (limit,)

            rows = self._execute_query(query, params, fetch='all')

            return [
                {
                    'request_id': row['request_id'],
                    'dataset_id': row['dataset_id'],
                    'resource_id': row['resource_id'],
                    'version_id': row['version_id'],
                    'job_id': row['job_id'],
                    'data_type': row['data_type'],
                    'created_at': row['created_at'].isoformat() if row['created_at'] else None
                }
                for row in rows
            ]

    def _row_to_record(self, row) -> ApiRequest:
        """
        Convert database row to ApiRequest model.

        Args:
            row: Database row (dict-like from psycopg dict_row factory)

        Returns:
            ApiRequest Pydantic model
        """
        return ApiRequest(
            request_id=row['request_id'],
            dataset_id=row['dataset_id'],
            resource_id=row['resource_id'],
            version_id=row['version_id'],
            job_id=row['job_id'],
            data_type=row['data_type'],
            created_at=row.get('created_at')
        )


# ============================================================================
# BACKWARD COMPATIBILITY ALIASES (22 NOV 2025)
# ============================================================================

# Alias for code still referencing PlatformRepository
PlatformRepository = ApiRequestRepository

# PlatformStatusRepository is REMOVED
# Old code importing PlatformStatusRepository will get ImportError
# This is intentional - forces migration to simplified pattern
#
# Migration path:
#   OLD: repo = PlatformStatusRepository()
#        repo.check_and_update_completion(request_id)
#
#   NEW: Status is delegated to CoreMachine
#        request = repo.get_request(request_id)
#        job = job_repo.get_job(request.job_id)
#        status = job.status  # Get status from CoreMachine
