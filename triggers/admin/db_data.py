"""
Database Data Admin Trigger.

Read-only access to CoreMachine and Platform layer data.

Exports:
    AdminDbDataTrigger: HTTP trigger class for data queries
    admin_db_data_trigger: Singleton instance of AdminDbDataTrigger
"""

import azure.functions as func
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import traceback

from infrastructure import RepositoryFactory, PostgreSQLRepository
from util_logger import LoggerFactory, ComponentType
from config import get_config

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "AdminDbData")


class AdminDbDataTrigger:
    """
    Admin trigger for CoreMachine and Platform data queries.

    Singleton pattern for consistent configuration across requests.
    """

    _instance: Optional['AdminDbDataTrigger'] = None

    def __new__(cls):
        """Singleton pattern - reuse instance across requests."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize trigger (only once due to singleton)."""
        if self._initialized:
            return

        logger.info("🔧 Initializing AdminDbDataTrigger")
        self.config = get_config()
        self._initialized = True
        logger.info("✅ AdminDbDataTrigger initialized")

    @classmethod
    def instance(cls) -> 'AdminDbDataTrigger':
        """Get singleton instance."""
        return cls()

    @property
    def db_repo(self) -> PostgreSQLRepository:
        """Lazy initialization of database repository."""
        if not hasattr(self, '_db_repo'):
            logger.debug("🔧 Lazy loading database repository")
            repos = RepositoryFactory.create_repositories()
            self._db_repo = repos['job_repo']
        return self._db_repo

    def handle_request(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Route admin database data requests.

        Routes:
            GET /api/dbadmin/jobs
            GET /api/dbadmin/jobs/{job_id}
            GET /api/dbadmin/tasks
            GET /api/dbadmin/tasks/{job_id}
            GET /api/dbadmin/platform/requests
            GET /api/dbadmin/platform/requests/{request_id}
            GET /api/dbadmin/platform/orchestration
            GET /api/dbadmin/platform/orchestration/{request_id}

        Args:
            req: Azure Function HTTP request

        Returns:
            JSON response with query results
        """
        try:
            # Parse route to determine operation
            # Azure Functions provides URL without /api/ prefix in route
            # URL format: dbadmin/jobs or dbadmin/platform/requests
            url = req.url

            # Extract path after dbadmin/
            if '/dbadmin/' in url:
                path = url.split('/dbadmin/')[-1].strip('/')
            elif 'dbadmin/' in url:
                path = url.split('dbadmin/')[-1].strip('/')
            else:
                path = ''

            # Strip query string if present
            if '?' in path:
                path = path.split('?')[0].strip('/')

            path_parts = path.split('/') if path else []

            logger.info(f"📥 Admin DB Data request: url={url}, path={path}, parts={path_parts}, method={req.method}")

            # Route to appropriate handler
            if path_parts[0] == 'jobs':
                if len(path_parts) == 1:
                    return self._get_jobs(req)
                else:
                    job_id = path_parts[1]
                    return self._get_job(req, job_id)

            elif path_parts[0] == 'tasks':
                if len(path_parts) == 1:
                    return self._get_tasks(req)
                else:
                    job_id = path_parts[1]
                    return self._get_tasks_for_job(req, job_id)

            elif path_parts[0] == 'platform':
                if len(path_parts) < 2:
                    return func.HttpResponse(
                        body=json.dumps({'error': 'Invalid platform path'}),
                        status_code=400,
                        mimetype='application/json'
                    )

                resource_type = path_parts[1]

                if resource_type == 'requests':
                    if len(path_parts) == 2:
                        return self._get_api_requests(req)
                    else:
                        request_id = path_parts[2]
                        return self._get_api_request(req, request_id)

                elif resource_type == 'orchestration':
                    if len(path_parts) == 2:
                        return self._get_orchestration_jobs(req)
                    else:
                        request_id = path_parts[2]
                        return self._get_orchestration_jobs_for_request(req, request_id)
                else:
                    return func.HttpResponse(
                        body=json.dumps({'error': f'Unknown platform resource: {resource_type}'}),
                        status_code=404,
                        mimetype='application/json'
                    )
            else:
                return func.HttpResponse(
                    body=json.dumps({'error': f'Unknown operation: {path_parts[0]}'}),
                    status_code=404,
                    mimetype='application/json'
                )

        except Exception as e:
            logger.error(f"❌ Error in AdminDbDataTrigger: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _validate_limit(self, limit_str: Optional[str], default: int = 10, max_limit: int = 1000) -> int:
        """Validate and sanitize limit parameter."""
        if not limit_str:
            return default

        try:
            limit = int(limit_str)
            if limit < 1:
                return 1
            if limit > max_limit:
                return max_limit
            return limit
        except ValueError:
            return default

    def _validate_hours(self, hours_str: Optional[str], default: int = 24, max_hours: int = 168) -> int:
        """Validate and sanitize hours parameter."""
        if not hours_str:
            return default

        try:
            hours = int(hours_str)
            if hours < 1:
                return 1
            if hours > max_hours:
                return max_hours
            return hours
        except ValueError:
            return default

    def _validate_job_id(self, job_id: str) -> bool:
        """Validate job ID format (SHA256 hash - 64 hex chars)."""
        if not job_id or len(job_id) != 64:
            return False
        try:
            int(job_id, 16)
            return True
        except ValueError:
            return False

    def _validate_request_id(self, request_id: str) -> bool:
        """Validate request ID format (MD5 hash - 32 hex chars)."""
        if not request_id or len(request_id) != 32:
            return False
        try:
            int(request_id, 16)
            return True
        except ValueError:
            return False

    def _get_jobs(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Query jobs with optional filtering.

        GET /api/dbadmin/jobs?limit=100&status=processing&hours=24&job_type=process_raster

        Query Parameters:
            limit: Number of results (default: 10, max: 1000)
            status: Filter by status (queued, processing, completed, failed)
            hours: Only show jobs from last N hours (default: 24, max: 168)
            job_type: Filter by job type

        Returns:
            {
                "jobs": [...],
                "query_info": {...}
            }
        """
        logger.info("📊 Querying jobs with filters")

        try:
            # Parse query parameters
            limit = self._validate_limit(req.params.get('limit'))
            hours = self._validate_hours(req.params.get('hours'))
            status_filter = req.params.get('status')
            job_type_filter = req.params.get('job_type')

            # Build query
            query_parts = [
                f"SELECT job_id, job_type, status::text, stage, total_stages,",
                f"       parameters, result_data, error_details, created_at, updated_at",
                f"FROM {self.config.app_schema}.jobs",
                f"WHERE created_at >= NOW() - INTERVAL '{hours} hours'"
            ]

            params = []

            if status_filter:
                query_parts.append("AND status::text = %s")
                params.append(status_filter)

            if job_type_filter:
                query_parts.append("AND job_type = %s")
                params.append(job_type_filter)

            query_parts.extend([
                "ORDER BY created_at DESC",
                f"LIMIT %s"
            ])
            params.append(limit)

            query = " ".join(query_parts)

            # Execute query
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, tuple(params))
                    rows = cursor.fetchall()

                    jobs = []
                    for row in rows:
                        jobs.append({
                            'job_id': row['job_id'],
                            'job_type': row['job_type'],
                            'status': row['status'],
                            'stage': row['stage'],
                            'total_stages': row['total_stages'],
                            'parameters': row['parameters'],
                            'result_data': row['result_data'],
                            'error_details': row['error_details'],
                            'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                            'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None
                        })

            result = {
                'jobs': jobs,
                'query_info': {
                    'limit': limit,
                    'hours_back': hours,
                    'status_filter': status_filter,
                    'job_type_filter': job_type_filter,
                    'total_found': len(jobs)
                },
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"✅ Found {len(jobs)} jobs")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error querying jobs: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_job(self, req: func.HttpRequest, job_id: str) -> func.HttpResponse:
        """
        Get specific job by ID.

        GET /api/dbadmin/jobs/{job_id}

        Args:
            job_id: Job ID (64-char hex SHA256 hash)

        Returns:
            {
                "job": {...}
            }
        """
        logger.info(f"📊 Getting job: {job_id}")

        try:
            if not self._validate_job_id(job_id):
                return func.HttpResponse(
                    body=json.dumps({
                        'error': 'Invalid job ID format',
                        'message': 'Job ID must be a 64-character hexadecimal string'
                    }),
                    status_code=400,
                    mimetype='application/json'
                )

            query = f"""
                SELECT job_id, job_type, status::text, stage, total_stages,
                       parameters, result_data, error_details, created_at, updated_at
                FROM {self.config.app_schema}.jobs
                WHERE job_id = %s
            """

            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (job_id,))
                    row = cursor.fetchone()

                    if not row:
                        return func.HttpResponse(
                            body=json.dumps({
                                'error': 'Job not found',
                                'job_id': job_id
                            }),
                            status_code=404,
                            mimetype='application/json'
                        )

                    job = {
                        'job_id': row['job_id'],
                        'job_type': row['job_type'],
                        'status': row['status'],
                        'stage': row['stage'],
                        'total_stages': row['total_stages'],
                        'parameters': row['parameters'],
                        'result_data': row['result_data'],
                        'error_details': row['error_details'],
                        'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                        'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None
                    }

            result = {
                'job': job,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"✅ Found job: {job_id}")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error getting job: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_tasks(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Query tasks with optional filtering.

        GET /api/dbadmin/tasks?limit=50&status=failed&stage=2

        Query Parameters:
            limit: Number of results (default: 50, max: 1000)
            status: Filter by status
            stage: Filter by stage number
            hours: Only show tasks from last N hours (default: 24, max: 168)

        Returns:
            {
                "tasks": [...],
                "query_info": {...}
            }
        """
        logger.info("📊 Querying tasks with filters")

        try:
            # Parse query parameters
            limit = self._validate_limit(req.params.get('limit'), default=50)
            hours = self._validate_hours(req.params.get('hours'))
            status_filter = req.params.get('status')
            stage_filter = req.params.get('stage')

            # Build query
            query_parts = [
                f"SELECT task_id, parent_job_id, task_type, status::text, stage, task_index,",
                f"       parameters, result_data, error_details, heartbeat, retry_count,",
                f"       created_at, updated_at",
                f"FROM {self.config.app_schema}.tasks",
                f"WHERE created_at >= NOW() - INTERVAL '{hours} hours'"
            ]

            params = []

            if status_filter:
                query_parts.append("AND status::text = %s")
                params.append(status_filter)

            if stage_filter:
                try:
                    stage_num = int(stage_filter)
                    query_parts.append("AND stage = %s")
                    params.append(stage_num)
                except ValueError:
                    pass  # Ignore invalid stage filter

            query_parts.extend([
                "ORDER BY created_at DESC",
                f"LIMIT %s"
            ])
            params.append(limit)

            query = " ".join(query_parts)

            # Execute query
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, tuple(params))
                    rows = cursor.fetchall()

                    tasks = []
                    for row in rows:
                        tasks.append({
                            'task_id': row['task_id'],
                            'parent_job_id': row['parent_job_id'],
                            'task_type': row['task_type'],
                            'status': row['status'],
                            'stage': row['stage'],
                            'task_index': row['task_index'],
                            'parameters': row['parameters'],
                            'result_data': row['result_data'],
                            'error_details': row['error_details'],
                            'heartbeat': row['heartbeat'].isoformat() if row['heartbeat'] else None,
                            'retry_count': row['retry_count'],
                            'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                            'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None
                        })

            result = {
                'tasks': tasks,
                'query_info': {
                    'limit': limit,
                    'hours_back': hours,
                    'status_filter': status_filter,
                    'stage_filter': stage_filter,
                    'total_found': len(tasks)
                },
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"✅ Found {len(tasks)} tasks")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error querying tasks: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_tasks_for_job(self, req: func.HttpRequest, job_id: str) -> func.HttpResponse:
        """
        Get all tasks for a specific job.

        GET /api/dbadmin/tasks/{job_id}

        Args:
            job_id: Job ID (64-char hex SHA256 hash)

        Returns:
            {
                "job_id": "...",
                "tasks": [...],
                "query_info": {...}
            }
        """
        logger.info(f"📊 Getting tasks for job: {job_id}")

        try:
            if not self._validate_job_id(job_id):
                return func.HttpResponse(
                    body=json.dumps({
                        'error': 'Invalid job ID format',
                        'message': 'Job ID must be a 64-character hexadecimal string'
                    }),
                    status_code=400,
                    mimetype='application/json'
                )

            query = f"""
                SELECT task_id, parent_job_id, task_type, status::text, stage, task_index,
                       parameters, result_data, metadata, error_details, heartbeat, retry_count,
                       created_at, updated_at
                FROM {self.config.app_schema}.tasks
                WHERE parent_job_id = %s
                ORDER BY stage ASC, task_index ASC
            """

            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (job_id,))
                    rows = cursor.fetchall()

                    tasks = []
                    for row in rows:
                        tasks.append({
                            'task_id': row['task_id'],
                            'parent_job_id': row['parent_job_id'],
                            'task_type': row['task_type'],
                            'status': row['status'],
                            'stage': row['stage'],
                            'task_index': row['task_index'],
                            'parameters': row['parameters'],
                            'result_data': row['result_data'],
                            'metadata': row['metadata'],
                            'error_details': row['error_details'],
                            'heartbeat': row['heartbeat'].isoformat() if row['heartbeat'] else None,
                            'retry_count': row['retry_count'],
                            'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                            'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None
                        })

            result = {
                'job_id': job_id,
                'tasks': tasks,
                'query_info': {
                    'total_tasks': len(tasks)
                },
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"✅ Found {len(tasks)} tasks for job {job_id}")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error getting tasks for job: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_api_requests(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Query Platform API requests with filtering.

        GET /api/dbadmin/platform/requests?limit=100&dataset_id=xyz

        UPDATED 26 NOV 2025: Simplified to match thin tracking pattern.
        - api_requests now in app schema (not platform schema)
        - status column REMOVED (delegate to CoreMachine job status)
        - Columns: request_id, dataset_id, resource_id, version_id, job_id, data_type, created_at

        Query Parameters:
            limit: Number of results (default: 10, max: 1000)
            hours: Only show requests from last N hours (default: 24, max: 168)
            dataset_id: Filter by DDH dataset ID

        Returns:
            {
                "api_requests": [...],
                "query_info": {...}
            }
        """
        logger.info("📊 Querying Platform API requests (thin tracking)")

        try:
            # Parse query parameters
            limit = self._validate_limit(req.params.get('limit'))
            hours = self._validate_hours(req.params.get('hours'))
            dataset_filter = req.params.get('dataset_id')

            # Build query - UPDATED for simplified schema (26 NOV 2025)
            # Platform tables now in app schema, not platform schema
            query_parts = [
                f"SELECT request_id, dataset_id, resource_id, version_id,",
                f"       job_id, data_type, created_at",
                f"FROM {self.config.app_schema}.api_requests",
                f"WHERE created_at >= NOW() - INTERVAL '{hours} hours'"
            ]

            params = []

            if dataset_filter:
                query_parts.append("AND dataset_id = %s")
                params.append(dataset_filter)

            query_parts.extend([
                "ORDER BY created_at DESC",
                f"LIMIT %s"
            ])
            params.append(limit)

            query = " ".join(query_parts)

            # Execute query
            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, tuple(params))
                    rows = cursor.fetchall()

                    api_requests = []
                    for row in rows:
                        api_requests.append({
                            'request_id': row['request_id'],
                            'dataset_id': row['dataset_id'],
                            'resource_id': row['resource_id'],
                            'version_id': row['version_id'],
                            'job_id': row['job_id'],
                            'data_type': row['data_type'],
                            'created_at': row['created_at'].isoformat() if row['created_at'] else None
                        })

            result = {
                'api_requests': api_requests,
                'query_info': {
                    'limit': limit,
                    'hours_back': hours,
                    'dataset_filter': dataset_filter,
                    'total_found': len(api_requests),
                    'note': 'Thin tracking - status via job_id lookup to CoreMachine'
                },
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"✅ Found {len(api_requests)} API requests")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error querying API requests: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_api_request(self, req: func.HttpRequest, request_id: str) -> func.HttpResponse:
        """
        Get specific Platform API request by ID.

        GET /api/dbadmin/platform/requests/{request_id}

        UPDATED 26 NOV 2025: Simplified to match thin tracking pattern.
        - api_requests now in app schema (not platform schema)
        - Columns: request_id, dataset_id, resource_id, version_id, job_id, data_type, created_at

        Args:
            request_id: Request ID (32-char hex SHA256 hash)

        Returns:
            {
                "api_request": {...}
            }
        """
        logger.info(f"📊 Getting API request: {request_id}")

        try:
            if not self._validate_request_id(request_id):
                return func.HttpResponse(
                    body=json.dumps({
                        'error': 'Invalid request ID format',
                        'message': 'Request ID must be a 32-character hexadecimal string'
                    }),
                    status_code=400,
                    mimetype='application/json'
                )

            # UPDATED for simplified schema (26 NOV 2025)
            # Platform tables now in app schema, not platform schema
            query = f"""
                SELECT request_id, dataset_id, resource_id, version_id,
                       job_id, data_type, created_at
                FROM {self.config.app_schema}.api_requests
                WHERE request_id = %s
            """

            if not isinstance(self.db_repo, PostgreSQLRepository):
                raise ValueError("Database repository is not PostgreSQL")

            with self.db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (request_id,))
                    row = cursor.fetchone()

                    if not row:
                        return func.HttpResponse(
                            body=json.dumps({
                                'error': 'API request not found',
                                'request_id': request_id
                            }),
                            status_code=404,
                            mimetype='application/json'
                        )

                    api_request = {
                        'request_id': row['request_id'],
                        'dataset_id': row['dataset_id'],
                        'resource_id': row['resource_id'],
                        'version_id': row['version_id'],
                        'job_id': row['job_id'],
                        'data_type': row['data_type'],
                        'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                        'note': 'Thin tracking - status via job_id lookup to CoreMachine'
                    }

            result = {
                'api_request': api_request,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"✅ Found API request: {request_id}")

            return func.HttpResponse(
                body=json.dumps(result, indent=2),
                status_code=200,
                mimetype='application/json'
            )

        except Exception as e:
            logger.error(f"❌ Error getting API request: {e}")
            logger.error(traceback.format_exc())
            return func.HttpResponse(
                body=json.dumps({
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }),
                status_code=500,
                mimetype='application/json'
            )

    def _get_orchestration_jobs(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        DEPRECATED (26 NOV 2025): orchestration_jobs table was REMOVED (22 NOV 2025).

        Platform now uses thin tracking pattern:
        - 1:1 mapping: api_requests.job_id → CoreMachine job
        - No separate orchestration table needed
        - Use /api/dbadmin/platform/requests instead

        Returns deprecation notice.
        """
        logger.warning("⚠️ Deprecated endpoint: orchestration_jobs table removed (22 NOV 2025)")

        return func.HttpResponse(
            body=json.dumps({
                'error': 'Endpoint deprecated',
                'message': 'orchestration_jobs table was removed on 22 NOV 2025',
                'reason': 'Platform now uses thin tracking pattern (1:1 api_request → job mapping)',
                'alternative': 'Use GET /api/dbadmin/platform/requests - includes job_id for CoreMachine lookup',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }),
            status_code=410,  # 410 Gone - resource no longer available
            mimetype='application/json'
        )

    def _get_orchestration_jobs_for_request(self, req: func.HttpRequest, request_id: str) -> func.HttpResponse:
        """
        DEPRECATED (26 NOV 2025): orchestration_jobs table was REMOVED (22 NOV 2025).

        Platform now uses thin tracking pattern:
        - 1:1 mapping: api_requests.job_id → CoreMachine job
        - No separate orchestration table needed
        - Use /api/dbadmin/platform/requests/{request_id} instead

        Returns deprecation notice.
        """
        logger.warning(f"⚠️ Deprecated endpoint: orchestration_jobs table removed (22 NOV 2025)")

        return func.HttpResponse(
            body=json.dumps({
                'error': 'Endpoint deprecated',
                'message': 'orchestration_jobs table was removed on 22 NOV 2025',
                'reason': 'Platform now uses thin tracking pattern (1:1 api_request → job mapping)',
                'alternative': f'Use GET /api/dbadmin/platform/requests/{request_id} - includes job_id for CoreMachine lookup',
                'request_id': request_id,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }),
            status_code=410,  # 410 Gone - resource no longer available
            mimetype='application/json'
        )



# Create singleton instance
admin_db_data_trigger = AdminDbDataTrigger.instance()
