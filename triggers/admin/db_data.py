# ============================================================================
# DATABASE DATA ADMIN TRIGGER
# ============================================================================
# STATUS: Trigger layer - GET /api/dbadmin/jobs, /api/dbadmin/tasks
# PURPOSE: Read-only access to CoreMachine and Platform layer data
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: AdminDbDataTrigger, admin_db_data_trigger
# ============================================================================
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
            limit: Number of results (default: 25, max: 1000)
            status: Filter by status (queued, processing, completed, failed)
            hours: Only show jobs from last N hours (default: 168/7 days, max: 720/30 days, 0=all)
            job_type: Filter by job type

        Returns:
            {
                "jobs": [...],
                "query_info": {...}
            }

        V0.8.16 (09 FEB 2026): Refactored to use JobRepository.list_jobs_with_task_counts()
        """
        logger.info("📊 Querying jobs with filters")

        try:
            # Parse query parameters
            limit = self._validate_limit(req.params.get('limit'), default=25)
            hours_param = req.params.get('hours')
            # Support hours=0 or hours=all to disable time filter
            if hours_param in ('0', 'all', 'none'):
                hours = None
            else:
                hours = self._validate_hours(hours_param, default=168, max_hours=720)
            status_filter = req.params.get('status')
            job_type_filter = req.params.get('job_type')

            app_schema = self.config.app_schema
            logger.info(f"📊 Querying via repository: hours={hours}, limit={limit}")

            # V0.8.16: Use centralized repository method instead of hardcoded SQL
            from infrastructure import JobRepository
            from core.models import JobStatus

            job_repo = JobRepository()

            # Convert status string to JobStatus enum if provided
            status_enum = None
            if status_filter:
                try:
                    status_enum = JobStatus(status_filter)
                except ValueError:
                    pass  # Invalid status, will be ignored

            jobs = job_repo.list_jobs_with_task_counts(
                status=status_enum,
                job_type=job_type_filter,
                hours=hours,
                limit=limit
            )

            result = {
                'jobs': jobs,
                'query_info': {
                    'schema': app_schema,
                    'limit': limit,
                    'hours_back': hours if hours else 'all',
                    'status_filter': status_filter,
                    'job_type_filter': job_type_filter,
                    'total_found': len(jobs)
                },
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"✅ Found {len(jobs)} jobs via repository")

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

        V0.8.16 (09 FEB 2026): Refactored to use JobRepository.get_job()
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

            # V0.8.16: Use centralized repository method instead of hardcoded SQL
            from infrastructure import JobRepository

            job_repo = JobRepository()
            job_record = job_repo.get_job(job_id)

            if not job_record:
                return func.HttpResponse(
                    body=json.dumps({
                        'error': 'Job not found',
                        'job_id': job_id
                    }),
                    status_code=404,
                    mimetype='application/json'
                )

            # Convert JobRecord to dict for JSON response
            job = {
                'job_id': job_record.job_id,
                'job_type': job_record.job_type,
                'status': job_record.status.value if hasattr(job_record.status, 'value') else job_record.status,
                'stage': job_record.stage,
                'total_stages': job_record.total_stages,
                'parameters': job_record.parameters,
                'result_data': job_record.result_data,
                'error_details': job_record.error_details,
                'asset_id': job_record.asset_id,
                'platform_id': job_record.platform_id,
                'request_id': job_record.request_id,
                'etl_version': getattr(job_record, 'etl_version', None),
                'created_at': job_record.created_at.isoformat() if job_record.created_at else None,
                'updated_at': job_record.updated_at.isoformat() if job_record.updated_at else None
            }

            result = {
                'job': job,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"✅ Found job via repository: {job_id[:16]}...")

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

        V0.8.16 (09 FEB 2026): Refactored to use TaskRepository.list_tasks_with_filters()
        """
        logger.info("📊 Querying tasks with filters")

        try:
            # Parse query parameters
            limit = self._validate_limit(req.params.get('limit'), default=50)
            hours = self._validate_hours(req.params.get('hours'))
            status_filter = req.params.get('status')
            stage_filter = req.params.get('stage')

            # Convert stage to int if provided
            stage_num = None
            if stage_filter:
                try:
                    stage_num = int(stage_filter)
                except ValueError:
                    pass  # Ignore invalid stage filter

            # V0.8.16: Use centralized repository method instead of hardcoded SQL
            from infrastructure import TaskRepository

            task_repo = TaskRepository()
            tasks = task_repo.list_tasks_with_filters(
                status=status_filter,
                stage=stage_num,
                limit=limit
            )

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

            logger.info(f"✅ Found {len(tasks)} tasks via repository")

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

            # F7.19: Include checkpoint fields for Docker progress display (19 JAN 2026)
            query = f"""
                SELECT task_id, parent_job_id, task_type, status::text, stage, task_index,
                       parameters, result_data, metadata, error_details, last_pulse, retry_count,
                       execution_started_at, created_at, updated_at,
                       checkpoint_phase, checkpoint_data, checkpoint_updated_at
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
                        # Calculate execution time if task is completed and has start time
                        execution_time_ms = None
                        if row['execution_started_at'] and row['updated_at'] and row['status'] == 'completed':
                            delta = row['updated_at'] - row['execution_started_at']
                            execution_time_ms = int(delta.total_seconds() * 1000)

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
                            'last_pulse': row['last_pulse'].isoformat() if row['last_pulse'] else None,
                            'retry_count': row['retry_count'],
                            'execution_started_at': row['execution_started_at'].isoformat() if row['execution_started_at'] else None,
                            'execution_time_ms': execution_time_ms,
                            'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                            'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None,
                            # F7.19: Checkpoint fields for Docker progress (19 JAN 2026)
                            'checkpoint_phase': row['checkpoint_phase'],
                            'checkpoint_data': row['checkpoint_data'],
                            'checkpoint_updated_at': row['checkpoint_updated_at'].isoformat() if row['checkpoint_updated_at'] else None,
                        })

            # Calculate aggregate metrics per stage
            stage_metrics = {}
            for task in tasks:
                stage = task['stage']
                if stage not in stage_metrics:
                    stage_metrics[stage] = {
                        'total': 0,
                        'completed': 0,
                        'failed': 0,
                        'processing': 0,
                        'pending': 0,
                        'queued': 0,
                        'execution_times_ms': []
                    }
                stage_metrics[stage]['total'] += 1
                stage_metrics[stage][task['status']] = stage_metrics[stage].get(task['status'], 0) + 1
                if task['execution_time_ms']:
                    stage_metrics[stage]['execution_times_ms'].append(task['execution_time_ms'])

            # Compute averages and rates
            metrics_summary = {}
            for stage, metrics in stage_metrics.items():
                times = metrics['execution_times_ms']
                completed = metrics['completed']
                avg_time_ms = sum(times) / len(times) if times else None
                min_time_ms = min(times) if times else None
                max_time_ms = max(times) if times else None

                metrics_summary[stage] = {
                    'total_tasks': metrics['total'],
                    'completed': completed,
                    'failed': metrics['failed'],
                    'processing': metrics['processing'],
                    'pending': metrics['pending'] + metrics.get('queued', 0),
                    'avg_execution_time_ms': round(avg_time_ms) if avg_time_ms else None,
                    'min_execution_time_ms': min_time_ms,
                    'max_execution_time_ms': max_time_ms,
                    'avg_execution_time_formatted': f"{avg_time_ms/1000:.1f}s" if avg_time_ms else None,
                    'tasks_per_minute': round(60000 / avg_time_ms, 1) if avg_time_ms and avg_time_ms > 0 else None
                }

            result = {
                'job_id': job_id,
                'tasks': tasks,
                'metrics': metrics_summary,
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

        Query Parameters:
            limit: Number of results (default: 10, max: 1000)
            hours: Only show requests from last N hours (default: 24, max: 168)
            dataset_id: Filter by DDH dataset ID

        Returns:
            {
                "api_requests": [...],
                "query_info": {...}
            }

        V0.8.16 (09 FEB 2026): Refactored to use ApiRequestRepository.get_all_requests()
        """
        logger.info("📊 Querying Platform API requests via repository")

        try:
            # Parse query parameters
            limit = self._validate_limit(req.params.get('limit'))
            hours = self._validate_hours(req.params.get('hours'))
            dataset_filter = req.params.get('dataset_id')

            # V0.8.16: Use centralized repository method instead of hardcoded SQL
            from infrastructure.platform import ApiRequestRepository

            api_repo = ApiRequestRepository()
            api_requests = api_repo.get_all_requests(
                limit=limit,
                dataset_id=dataset_filter
            )

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

            logger.info(f"✅ Found {len(api_requests)} API requests via repository")

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

        Args:
            request_id: Request ID (32-char hex SHA256 hash)

        Returns:
            {
                "api_request": {...}
            }

        V0.8.16 (09 FEB 2026): Refactored to use ApiRequestRepository.get_request()
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

            # V0.8.16: Use centralized repository method instead of hardcoded SQL
            from infrastructure.platform import ApiRequestRepository

            api_repo = ApiRequestRepository()
            api_request_record = api_repo.get_request(request_id)

            if not api_request_record:
                return func.HttpResponse(
                    body=json.dumps({
                        'error': 'API request not found',
                        'request_id': request_id
                    }),
                    status_code=404,
                    mimetype='application/json'
                )

            # Convert ApiRequest model to dict for JSON response
            api_request = {
                'request_id': api_request_record.request_id,
                'dataset_id': api_request_record.dataset_id,
                'resource_id': api_request_record.resource_id,
                'version_id': api_request_record.version_id,
                'job_id': api_request_record.job_id,
                'data_type': api_request_record.data_type,
                'asset_id': api_request_record.asset_id,
                'platform_id': api_request_record.platform_id,
                'created_at': api_request_record.created_at.isoformat() if api_request_record.created_at else None,
                'note': 'Thin tracking - status via job_id lookup to CoreMachine'
            }

            result = {
                'api_request': api_request,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"✅ Found API request via repository: {request_id}")

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
