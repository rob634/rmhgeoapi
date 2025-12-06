"""
Triggers Package.

Azure Functions HTTP and Timer trigger implementations.

HTTP Endpoints:
    /api/health: System health check
    /api/jobs/submit/{job_type}: Job submission
    /api/jobs/status/{job_id}: Job status query
    /api/db/*: Database query and management

Exports:
    All trigger classes for HTTP endpoints and timer functions
"""

# Only import base classes to avoid initialization at import time
# Trigger instances should be imported directly from their modules
from .http_base import BaseHttpTrigger, SystemMonitoringTrigger, JobManagementTrigger

__all__ = [
    # Base classes for type hints and inheritance
    'BaseHttpTrigger',
    'SystemMonitoringTrigger',
    'JobManagementTrigger',
]