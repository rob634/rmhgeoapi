# ============================================================================
# JOB LOGS HTTP TRIGGER
# ============================================================================
# STATUS: Trigger layer - GET /api/jobs/{job_id}/logs
# PURPOSE: Fetch Application Insights logs filtered by job_id
# LAST_REVIEWED: 12 JAN 2026
# EXPORTS: JobLogsTrigger, get_job_logs_trigger
# DEPENDENCIES: azure.functions, infrastructure.appinsights_exporter
# ============================================================================
"""
Job Logs HTTP Trigger.

HTTP endpoint for GET /api/jobs/{job_id}/logs requests.

Fetches logs from Application Insights filtered by job_id for display
in the workflow monitor interface.

Query Parameters:
    - level: Minimum log level (DEBUG, INFO, WARNING, ERROR) - default: INFO
    - limit: Maximum number of logs to return (default: 100, max: 500)
    - timespan: How far back to search (default: PT24H = 24 hours)
    - component: Filter by component type (optional)

Example:
    GET /api/jobs/abc123/logs?level=WARNING&limit=50

Response:
    {
        "success": true,
        "job_id": "abc123...",
        "logs": [
            {
                "timestamp": "2026-01-12T10:30:00Z",
                "level": "WARNING",
                "levelNum": 2,
                "component": "service.stac_vector",
                "message": "Chunk size exceeds threshold",
                "job_id": "abc123...",
                "task_id": "abc123-s1-0",
                "stage": 1
            }
        ],
        "query_duration_ms": 1234,
        "row_count": 50
    }
"""

from typing import Dict, Any, List

import azure.functions as func
from .http_base import JobManagementTrigger


class JobLogsTrigger(JobManagementTrigger):
    """Job logs retrieval HTTP trigger implementation."""

    # Severity level mapping
    SEVERITY_LEVELS = {
        "DEBUG": 0,
        "INFO": 1,
        "WARNING": 2,
        "ERROR": 3,
        "CRITICAL": 4
    }

    def __init__(self):
        super().__init__("get_job_logs")

    def get_allowed_methods(self) -> List[str]:
        """Job logs only supports GET."""
        return ["GET"]

    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Process job logs retrieval request.

        Args:
            req: HTTP request with job_id in path
            Query params:
                - level: Minimum severity (DEBUG/INFO/WARNING/ERROR)
                - limit: Max rows (default 100, max 500)
                - timespan: How far back (default PT24H)
                - component: Filter by component type

        Returns:
            Job logs response data

        Raises:
            FileNotFoundError: If job is not found
            ValueError: If job_id is invalid
        """
        # Extract and validate job ID from path
        path_params = self.extract_path_params(req, ["job_id"])
        job_id = self.validate_job_id(path_params["job_id"])

        # Parse query parameters
        level = req.params.get('level', 'INFO').upper()
        limit = min(int(req.params.get('limit', '100')), 500)
        timespan = req.params.get('timespan', 'PT24H')
        component = req.params.get('component', '')

        # Validate level
        if level not in self.SEVERITY_LEVELS:
            level = 'INFO'
        severity_num = self.SEVERITY_LEVELS[level]

        self.logger.debug(f"Fetching logs for job: {job_id[:16]}... level>={level} limit={limit}")

        # Verify job exists (optional but good for user feedback)
        job_record = self.job_repository.get_job(job_id)
        if not job_record:
            raise FileNotFoundError(f"Job not found: {job_id}")

        # Query Application Insights
        logs = self._query_logs(job_id, severity_num, limit, timespan, component)

        return {
            "success": True,
            "job_id": job_id,
            "logs": logs["records"],
            "query_duration_ms": logs["query_duration_ms"],
            "row_count": logs["row_count"],
            "level_filter": level,
            "timespan": timespan
        }

    def _query_logs(
        self,
        job_id: str,
        severity_num: int,
        limit: int,
        timespan: str,
        component: str = ""
    ) -> Dict[str, Any]:
        """
        Query Application Insights for job logs.

        Args:
            job_id: Job identifier to filter by
            severity_num: Minimum severity level (0-4)
            limit: Maximum rows to return
            timespan: ISO 8601 duration (e.g., PT24H)
            component: Optional component filter

        Returns:
            Dictionary with records, query_duration_ms, row_count
        """
        try:
            from infrastructure.appinsights_exporter import query_logs

            # Build KQL query
            # customDimensions contains job_id as string
            query_parts = [
                "traces",
                f"| where customDimensions.job_id == '{job_id}'",
                f"| where severityLevel >= {severity_num}",
            ]

            if component:
                query_parts.append(f"| where customDimensions.component_name contains '{component}'")

            query_parts.extend([
                "| project timestamp, severityLevel, message, customDimensions",
                "| order by timestamp desc",
                f"| take {limit}"
            ])

            query = "\n".join(query_parts)

            self.logger.debug(f"Executing KQL query: {query[:100]}...")

            result = query_logs(query=query, timespan=timespan, timeout=30.0)

            if not result.success:
                self.logger.warning(f"App Insights query failed: {result.error}")
                return {
                    "records": [],
                    "query_duration_ms": result.query_duration_ms,
                    "row_count": 0,
                    "error": result.error
                }

            # Transform records to cleaner format
            records = []
            for record in result.to_records():
                custom_dims = record.get("customDimensions", {})
                # customDimensions comes as JSON string, parse it
                if isinstance(custom_dims, str):
                    import json
                    try:
                        custom_dims = json.loads(custom_dims)
                    except Exception:
                        custom_dims = {}

                records.append({
                    "timestamp": record.get("timestamp"),
                    "level": self._severity_to_level(record.get("severityLevel", 1)),
                    "levelNum": record.get("severityLevel", 1),
                    "message": record.get("message", ""),
                    "component": custom_dims.get("component_name", ""),
                    "component_type": custom_dims.get("component_type", ""),
                    "job_id": custom_dims.get("job_id", ""),
                    "task_id": custom_dims.get("task_id", ""),
                    "stage": custom_dims.get("stage"),
                })

            return {
                "records": records,
                "query_duration_ms": result.query_duration_ms,
                "row_count": result.row_count
            }

        except ImportError:
            self.logger.warning("appinsights_exporter not available")
            return {
                "records": [],
                "query_duration_ms": 0,
                "row_count": 0,
                "error": "Application Insights exporter not configured"
            }
        except Exception as e:
            self.logger.error(f"Error querying logs: {e}")
            return {
                "records": [],
                "query_duration_ms": 0,
                "row_count": 0,
                "error": str(e)
            }

    def _severity_to_level(self, severity: int) -> str:
        """Convert severity number to level name."""
        levels = {0: "DEBUG", 1: "INFO", 2: "WARNING", 3: "ERROR", 4: "CRITICAL"}
        return levels.get(severity, "INFO")


# Create singleton instance for use in function_app.py
get_job_logs_trigger = JobLogsTrigger()
