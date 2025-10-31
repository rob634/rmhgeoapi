# ============================================================================
# CLAUDE CONTEXT - API REQUEST REPOSITORIES (PLATFORM LAYER)
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Infrastructure - API request repositories with SQL composition
# PURPOSE: PostgreSQL repositories for Platform layer API requests and orchestration tracking
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: ApiRequestRepository (renamed from PlatformRepository), PlatformStatusRepository
# INTERFACES: PostgreSQLRepository (from infrastructure.postgresql)
# PYDANTIC_MODELS: ApiRequest, PlatformRequestStatus
# DEPENDENCIES: psycopg, psycopg.sql, infrastructure.postgresql
# SOURCE: PostgreSQL database (app schema: api_requests, orchestration_jobs)
# SCOPE: Platform layer request orchestration and status monitoring
# VALIDATION: SQL injection prevention via psycopg.sql composition
# PATTERNS: Repository pattern, SQL composition, inheritance from PostgreSQLRepository
# ENTRY_POINTS: repo = ApiRequestRepository(); request = repo.create_request(record)
# INDEX:
#   - Imports: Line 34
#   - ApiRequestRepository: Line 49
#   - PlatformStatusRepository: Line 179
# ============================================================================

"""
Platform Repository Implementation - SQL Composition Pattern

This module provides PostgreSQL repository implementations for the Platform layer,
following CoreMachine's SQL composition patterns for injection safety.

Architecture:
    PostgreSQLRepository (base)
        ↓
    PlatformRepository (platform requests)
        ↓
    PlatformStatusRepository (extended status queries)

Key Features:
- SQL composition using psycopg.sql for injection safety
- Inherits connection management from PostgreSQLRepository
- Uses _execute_query() for automatic commits and error handling
- Schema-agnostic via sql.Identifier(self.schema_name)
"""

import json
import warnings
from datetime import datetime
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from enum import Enum
from psycopg import sql

from infrastructure.postgresql import PostgreSQLRepository

# Import Platform models from core (Infrastructure-as-Code pattern - 29 OCT 2025)
from core.models import ApiRequest, PlatformRequestStatus

# Logger setup - using LoggerFactory from util_logger
from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "platform")


# ============================================================================
# API REQUEST REPOSITORY - Core API request operations (Platform layer)
# ============================================================================

class ApiRequestRepository(PostgreSQLRepository):
    """
    Repository for API requests (Platform layer).

    Tables: app.api_requests, app.orchestration_jobs
    Renamed from PlatformRepository (29 OCT 2025) for API clarity.

    Follows CoreMachine SQL composition patterns:
    - Uses sql.SQL().format(sql.Identifier()) for table/schema names
    - Uses _execute_query() instead of manual commits
    - Uses _error_context() for detailed error logging

    Schema deployed centrally via triggers/schema_pydantic_deploy.py
    POST /api/db/schema/redeploy?confirm=yes
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
        warnings.warn(
            "PlatformRepository._ensure_schema() is deprecated. "
            "Use centralized schema deployment via /api/db/schema/redeploy",
            DeprecationWarning,
            stacklevel=2
        )
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Use app schema (same as jobs/tasks tables)
                # No separate platform schema needed

                # Create API requests table in app schema
                # NOTE: This manual DDL is DEPRECATED - use Infrastructure-as-Code pattern instead
                # Schema is now auto-generated from core/models/platform.py (29 OCT 2025)
                # Tables renamed: platform_requests → api_requests, platform_request_jobs → orchestration_jobs
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS app.api_requests (
                        request_id VARCHAR(32) PRIMARY KEY,
                        dataset_id VARCHAR(255) NOT NULL,
                        resource_id VARCHAR(255) NOT NULL,
                        version_id VARCHAR(50) NOT NULL,
                        data_type VARCHAR(50) NOT NULL,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        jobs JSONB NOT NULL DEFAULT '{}'::jsonb,
                        parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        result_data JSONB,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)

                # Create indexes
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_api_requests_status
                    ON app.api_requests(status)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_api_requests_dataset
                    ON app.api_requests(dataset_id)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_api_requests_created
                    ON app.api_requests(created_at DESC)
                """)

                # Create orchestration jobs mapping table in app schema
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS app.orchestration_jobs (
                        request_id VARCHAR(32) NOT NULL,
                        job_id VARCHAR(64) NOT NULL,
                        job_type VARCHAR(100) NOT NULL,
                        sequence INTEGER NOT NULL DEFAULT 1,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        PRIMARY KEY (request_id, job_id)
                    )
                """)

                conn.commit()

    def create_request(self, request: ApiRequest) -> ApiRequest:
        """
        Create a new platform request using SQL composition.

        Follows CoreMachine pattern (infrastructure/postgresql.py:624-665):
        - Uses sql.SQL().format(sql.Identifier()) for table names
        - Uses _execute_query() for automatic commit
        - Uses _error_context() for detailed error logging
        """
        with self._error_context("platform request creation", request.request_id):
            # INSERT with ON CONFLICT DO NOTHING
            query = sql.SQL("""
                INSERT INTO {}.{}
                (request_id, dataset_id, resource_id, version_id, data_type,
                 status, parameters, metadata, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                request.data_type,
                request.status.value if isinstance(request.status, Enum) else request.status,
                json.dumps(request.parameters),
                json.dumps(request.metadata),
                request.created_at,
                request.updated_at
            )

            row = self._execute_query(query, params, fetch='one')

            if row:
                logger.info(f"Created platform request: {request.request_id}")
                return self._row_to_record(row)
            else:
                # Request already exists, fetch it
                select_query = sql.SQL("""
                    SELECT * FROM {}.{} WHERE request_id = %s
                """).format(
                    sql.Identifier(self.schema_name),
                    sql.Identifier("api_requests")
                )
                row = self._execute_query(select_query, (request.request_id,), fetch='one')
                logger.info(f"Platform request already exists: {request.request_id}")
                return self._row_to_record(row)

    def get_request(self, request_id: str) -> Optional[ApiRequest]:
        """Get a platform request by ID using SQL composition"""
        with self._error_context("platform request retrieval", request_id):
            query = sql.SQL("""
                SELECT * FROM {}.{} WHERE request_id = %s
            """).format(
                sql.Identifier(self.schema_name),
                sql.Identifier("api_requests")
            )

            row = self._execute_query(query, (request_id,), fetch='one')
            return self._row_to_record(row) if row else None

    def update_request_status(self, request_id: str, status: PlatformRequestStatus) -> bool:
        """Update platform request status using SQL composition"""
        with self._error_context("platform request status update", request_id):
            query = sql.SQL("""
                UPDATE {}.{}
                SET status = %s, updated_at = NOW()
                WHERE request_id = %s
            """).format(
                sql.Identifier(self.schema_name),
                sql.Identifier("api_requests")
            )

            rowcount = self._execute_query(query, (status.value, request_id), fetch=None)
            return rowcount > 0

    def add_job_to_request(self, request_id: str, job_id: str, job_type: str) -> bool:
        """
        Add a CoreMachine job to a platform request using SQL composition.

        Updates structured jobs JSONB object and mapping table.

        Args:
            request_id: Platform request ID
            job_id: CoreMachine job ID
            job_type: Type of job (e.g., 'validate_raster', 'create_cog')
            step_name: Optional logical step name (defaults to job_type)
        """
        step_name = job_type  # Use job_type as logical step name by default

        with self._error_context("add job to platform request", f"{request_id}:{job_id}"):
            # Build job metadata structure
            job_metadata = {
                "job_id": job_id,
                "job_type": job_type,
                "status": "pending",
                "created_at": datetime.utcnow().isoformat()
            }

            # Update structured jobs JSONB object using jsonb_set
            update_query = sql.SQL("""
                UPDATE {}.{}
                SET jobs = jsonb_set(
                        COALESCE(jobs, '{{}}'::jsonb),
                        ARRAY[%s],
                        %s::jsonb,
                        true
                    ),
                    updated_at = NOW()
                WHERE request_id = %s
            """).format(
                sql.Identifier(self.schema_name),
                sql.Identifier("api_requests")
            )
            self._execute_query(
                update_query,
                (step_name, json.dumps(job_metadata), request_id),
                fetch=None
            )

            # Add to mapping table
            insert_query = sql.SQL("""
                INSERT INTO {}.{} (request_id, job_id, job_type)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
            """).format(
                sql.Identifier(self.schema_name),
                sql.Identifier("orchestration_jobs")
            )
            rowcount = self._execute_query(insert_query, (request_id, job_id, job_type), fetch=None)
            return rowcount > 0

    def _row_to_record(self, row) -> ApiRequest:
        """
        Convert database row to ApiRequest.

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
            'jobs': row['jobs'] if row['jobs'] else {},
            'parameters': row['parameters'] if isinstance(row['parameters'], dict) else json.loads(row['parameters']) if row['parameters'] else {},
            'metadata': row['metadata'] if isinstance(row['metadata'], dict) else json.loads(row['metadata']) if row['metadata'] else {},
            'result_data': row.get('result_data'),  # Optional field
            'created_at': row.get('created_at'),    # Optional field
            'updated_at': row.get('updated_at')     # Optional field
        }

        # Use Pydantic unpacking for validation
        return ApiRequest(**record_data)


# ============================================================================
# PLATFORM STATUS REPOSITORY - Extended status query methods
# ============================================================================

class PlatformStatusRepository(ApiRequestRepository):
    """
    Extended repository with status query methods.

    Provides comprehensive status monitoring and job tracking for platform requests.
    All SQL queries use composition for injection safety.
    """

    def get_request_with_jobs(self, request_id: str) -> Optional[Dict[str, Any]]:
        """
        Get platform request with all associated job details using SQL composition.

        Complex query with LEFT JOIN LATERAL and json aggregation.
        """
        with self._error_context("get request with jobs", request_id):
            # Note: This complex query uses app schema explicitly in joins
            # Schema identifier composition doesn't work well with LATERAL joins
            # We accept hardcoded "app" here since it's in the FROM/JOIN clauses
            query = sql.SQL("""
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
                FROM {}.{} r
                LEFT JOIN LATERAL (
                    SELECT
                        pj.job_id,
                        pj.job_type,
                        j.status,
                        j.stage,
                        j.created_at,
                        j.updated_at
                    FROM {}.{} pj
                    JOIN {}.{} j ON j.job_id = pj.job_id
                    WHERE pj.request_id = r.request_id
                ) j ON true
                WHERE r.request_id = %s
                GROUP BY r.request_id, r.dataset_id, r.resource_id, r.version_id,
                         r.data_type, r.status, r.jobs, r.parameters,
                         r.metadata, r.result_data, r.created_at, r.updated_at
            """).format(
                sql.Identifier(self.schema_name),  # platform_requests
                sql.Identifier("api_requests"),
                sql.Identifier(self.schema_name),  # platform_request_jobs
                sql.Identifier("orchestration_jobs"),
                sql.Identifier(self.schema_name),  # jobs
                sql.Identifier("jobs")
            )

            row = self._execute_query(query, (request_id,), fetch='one')
            if not row:
                return None

            # Build response using dict row (psycopg dict_row factory)
            return {
                'request_id': row['request_id'],
                'dataset_id': row['dataset_id'],
                'resource_id': row['resource_id'],
                'version_id': row['version_id'],
                'data_type': row['data_type'],
                'status': row['status'],
                'jobs': row.get('jobs') or {},  # Structured JSONB object, not array
                'parameters': row.get('parameters') or {},
                'metadata': row.get('metadata') or {},
                'result_data': row.get('result_data'),
                'created_at': row['created_at'].isoformat() if row.get('created_at') else None,
                'updated_at': row['updated_at'].isoformat() if row.get('updated_at') else None,
                'coremachine_jobs': row.get('jobs') or []  # Aggregated job list from mapping table
            }

    def get_all_requests(self, limit: int = 100, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all platform requests with optional filtering using SQL composition"""
        with self._error_context("get all requests", f"limit={limit}, status={status}"):
            # Build dynamic query with optional WHERE clause
            if status:
                query = sql.SQL("""
                    SELECT
                        request_id,
                        dataset_id,
                        resource_id,
                        version_id,
                        data_type,
                        status,
                        (SELECT COUNT(*) FROM jsonb_object_keys(jobs)) as job_count,
                        created_at,
                        updated_at
                    FROM {}.{}
                    WHERE status = %s
                    ORDER BY created_at DESC LIMIT %s
                """).format(
                    sql.Identifier(self.schema_name),
                    sql.Identifier("api_requests")
                )
                params = (status, limit)
            else:
                query = sql.SQL("""
                    SELECT
                        request_id,
                        dataset_id,
                        resource_id,
                        version_id,
                        data_type,
                        status,
                        (SELECT COUNT(*) FROM jsonb_object_keys(jobs)) as job_count,
                        created_at,
                        updated_at
                    FROM {}.{}
                    ORDER BY created_at DESC LIMIT %s
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
                    'data_type': row['data_type'],
                    'status': row['status'],
                    'job_count': row['job_count'] if row['job_count'] else 0,
                    'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                    'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None
                }
                for row in rows
            ]

    def check_and_update_completion(self, request_id: str) -> bool:
        """
        Check if all jobs are complete and update platform request status.

        Implements "last job turns out the lights" pattern.
        Uses SQL composition for injection safety.
        """
        with self._error_context("check and update completion", request_id):
            # Check job statuses from app schema
            check_query = sql.SQL("""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE j.status = 'completed') as completed,
                    COUNT(*) FILTER (WHERE j.status = 'failed') as failed,
                    COUNT(*) FILTER (WHERE j.status IN ('pending', 'processing')) as in_progress
                FROM {}.{} pj
                JOIN {}.{} j ON j.job_id = pj.job_id
                WHERE pj.request_id = %s
            """).format(
                sql.Identifier(self.schema_name),  # platform_request_jobs
                sql.Identifier("orchestration_jobs"),
                sql.Identifier(self.schema_name),  # jobs
                sql.Identifier("jobs")
            )

            row = self._execute_query(check_query, (request_id,), fetch='one')
            if not row or row['total'] == 0:  # No jobs
                return False

            total = row['total']
            completed = row['completed']
            failed = row['failed']
            in_progress = row['in_progress']

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

            # Update platform request status in app schema
            update_query = sql.SQL("""
                UPDATE {}.{}
                SET status = %s, updated_at = NOW()
                WHERE request_id = %s AND status != %s
            """).format(
                sql.Identifier(self.schema_name),
                sql.Identifier("api_requests")
            )

            rowcount = self._execute_query(update_query, (new_status.value, request_id, new_status.value), fetch=None)

            if rowcount > 0:
                logger.info(f"Updated platform request {request_id} to {new_status.value}")
                return True

            return False


# ============================================================================
# BACKWARD COMPATIBILITY ALIAS (29 OCT 2025)
# ============================================================================
# Temporary alias for code still referencing PlatformRepository
# TODO: Remove after all references updated to ApiRequestRepository
PlatformRepository = ApiRequestRepository
