# ============================================================================
# JOB EVENTS HTTP TRIGGER
# ============================================================================
# STATUS: Trigger layer - GET /api/jobs/{job_id}/events
# PURPOSE: Job execution event timeline for debugging and monitoring
# CREATED: 23 JAN 2026
# LAST_REVIEWED: 23 JAN 2026
# EXPORTS: JobEventsTrigger, get_job_events_trigger
# DEPENDENCIES: azure.functions, triggers.http_base, infrastructure.JobEventRepository
# ============================================================================
"""
Job Events HTTP Trigger.

HTTP endpoint for GET /api/jobs/{job_id}/events requests.

Provides access to job execution events for:
    - Real-time progress tracking
    - Debugging "last successful checkpoint"
    - Failure context analysis
    - Timeline visualization

Endpoints:
    GET /api/jobs/{job_id}/events - List events for a job
    GET /api/jobs/{job_id}/events/latest - Get most recent event
    GET /api/jobs/{job_id}/events/summary - Get event summary statistics

Query Parameters (for /events):
    - limit: Max events to return (default 50, max 500)
    - event_type: Filter by event type (e.g., "task_completed")
    - since: ISO timestamp to get events after
    - include_task_events: Include task-level events (default true)

Exports:
    JobEventsTrigger: Job events trigger class
    get_job_events_trigger: Singleton trigger instance
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

import azure.functions as func
from .http_base import JobManagementTrigger
from infrastructure import JobEventRepository


class JobEventsTrigger(JobManagementTrigger):
    """Job events retrieval HTTP trigger implementation."""

    def __init__(self):
        super().__init__("get_job_events")
        self._event_repo = None

    @property
    def event_repo(self) -> JobEventRepository:
        """Lazy-load event repository."""
        if self._event_repo is None:
            self._event_repo = JobEventRepository()
        return self._event_repo

    def get_allowed_methods(self) -> List[str]:
        """Job events only supports GET."""
        return ["GET"]

    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Process job events retrieval request.

        Routes to appropriate handler based on path:
            - /api/jobs/{job_id}/events → list events
            - /api/jobs/{job_id}/events/latest → latest event
            - /api/jobs/{job_id}/events/summary → event summary

        Args:
            req: HTTP request with job_id in path

        Returns:
            Event data response

        Raises:
            FileNotFoundError: If job is not found
            ValueError: If job_id is invalid
        """
        # Extract job_id from path
        path_params = self.extract_path_params(req, ["job_id"])
        job_id = self.validate_job_id(path_params["job_id"])

        # Determine which endpoint was called based on path
        path = req.url.lower()

        if "/events/latest" in path:
            return self._get_latest_event(job_id)
        elif "/events/summary" in path:
            return self._get_event_summary(job_id)
        elif "/events/failure" in path:
            return self._get_failure_context(job_id)
        else:
            return self._get_events(req, job_id)

    def _get_events(self, req: func.HttpRequest, job_id: str) -> Dict[str, Any]:
        """
        Get events for a job with optional filtering.

        Query Parameters:
            limit: Max events (default 50, max 500)
            event_type: Filter by type
            since: ISO timestamp filter
            include_task_events: Include task events (default true)
        """
        # Parse query parameters
        limit = min(int(req.params.get('limit', '50')), 500)
        event_type = req.params.get('event_type')
        since_str = req.params.get('since')
        include_task_events = req.params.get('include_task_events', 'true').lower() == 'true'

        # Parse since timestamp if provided
        since = None
        if since_str:
            try:
                since = datetime.fromisoformat(since_str.replace('Z', '+00:00'))
            except ValueError:
                raise ValueError(f"Invalid timestamp format: {since_str}. Use ISO format.")

        # Parse event_type filter
        event_types = None
        if event_type:
            from core.models.job_event import JobEventType
            try:
                event_types = [JobEventType(event_type)]
            except ValueError:
                valid_types = [e.value for e in JobEventType]
                raise ValueError(f"Invalid event_type: {event_type}. Valid types: {valid_types}")

        self.logger.debug(f"🔍 Getting events for job {job_id[:16]}... (limit={limit})")

        # Get events from repository
        timeline = self.event_repo.get_events_timeline(job_id, limit=limit)

        # Apply additional filters if needed
        if event_types:
            type_values = [et.value for et in event_types]
            timeline = [e for e in timeline if e['event_type'] in type_values]

        if since:
            timeline = [e for e in timeline if e['timestamp'] and datetime.fromisoformat(e['timestamp']) > since]

        if not include_task_events:
            timeline = [e for e in timeline if e['task_id'] is None]

        return {
            'job_id': job_id,
            'event_count': len(timeline),
            'events': timeline
        }

    def _get_latest_event(self, job_id: str) -> Dict[str, Any]:
        """Get the most recent event for a job."""
        self.logger.debug(f"🔍 Getting latest event for job {job_id[:16]}...")

        event = self.event_repo.get_latest_event(job_id)

        if not event:
            return {
                'job_id': job_id,
                'has_events': False,
                'latest_event': None
            }

        return {
            'job_id': job_id,
            'has_events': True,
            'latest_event': {
                'event_id': event.event_id,
                'event_type': event.event_type.value if hasattr(event.event_type, 'value') else event.event_type,
                'event_status': event.event_status.value if hasattr(event.event_status, 'value') else event.event_status,
                'timestamp': event.created_at.isoformat() if event.created_at else None,
                'task_id': event.task_id,
                'stage': event.stage,
                'checkpoint_name': event.checkpoint_name,
                'duration_ms': event.duration_ms,
                'error_message': event.error_message
            }
        }

    def _get_event_summary(self, job_id: str) -> Dict[str, Any]:
        """Get event summary statistics for a job."""
        self.logger.debug(f"🔍 Getting event summary for job {job_id[:16]}...")

        summary = self.event_repo.get_event_summary(job_id)

        return {
            'job_id': job_id,
            **summary
        }

    def _get_failure_context(self, job_id: str) -> Dict[str, Any]:
        """Get failure event and preceding events for debugging."""
        self.logger.debug(f"🔍 Getting failure context for job {job_id[:16]}...")

        # Get preceding count from query params (default 10)
        preceding_count = 10

        context = self.event_repo.get_failure_context(job_id, preceding_count)

        if not context['has_failure']:
            return {
                'job_id': job_id,
                'has_failure': False,
                'failure_event': None,
                'preceding_events': []
            }

        # Format failure event
        failure = context['failure_event']
        failure_dict = {
            'event_id': failure.event_id,
            'event_type': failure.event_type.value if hasattr(failure.event_type, 'value') else failure.event_type,
            'timestamp': failure.created_at.isoformat() if failure.created_at else None,
            'task_id': failure.task_id,
            'stage': failure.stage,
            'error_message': failure.error_message,
            'event_data': failure.event_data
        }

        # Format preceding events
        preceding = []
        for event in context['preceding_events']:
            preceding.append({
                'event_id': event.event_id,
                'event_type': event.event_type.value if hasattr(event.event_type, 'value') else event.event_type,
                'event_status': event.event_status.value if hasattr(event.event_status, 'value') else event.event_status,
                'timestamp': event.created_at.isoformat() if event.created_at else None,
                'task_id': event.task_id,
                'stage': event.stage,
                'duration_ms': event.duration_ms
            })

        return {
            'job_id': job_id,
            'has_failure': True,
            'failure_event': failure_dict,
            'preceding_events': preceding
        }


# Singleton instance
get_job_events_trigger = JobEventsTrigger()
