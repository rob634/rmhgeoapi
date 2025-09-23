# ============================================================================
# CLAUDE CONTEXT - TRIGGERS PACKAGE INITIALIZATION
# ============================================================================
# PURPOSE: Initialize the triggers package for Azure Functions HTTP/Timer triggers
# EXPORTS: All trigger classes for HTTP endpoints and timer functions
# INTERFACES: Azure Functions trigger interfaces
# PYDANTIC_MODELS: Various request/response models per trigger
# DEPENDENCIES: azure.functions, trigger base classes
# SOURCE: Package initialization
# SCOPE: Package-level
# VALIDATION: Request validation via Pydantic models
# PATTERNS: Package initialization, Strategy pattern for triggers
# ENTRY_POINTS: from triggers import *
# INDEX: N/A
# ============================================================================

"""
Triggers package for rmhgeoapi Azure Functions.

This package contains all Azure Functions trigger implementations:
- HTTP triggers for job submission, status checking, database operations
- Timer triggers for poison queue monitoring
- Base classes for trigger implementation patterns

HTTP Endpoints:
- /api/health - System health check
- /api/jobs/submit/{job_type} - Job submission
- /api/jobs/status/{job_id} - Job status query
- /api/db/* - Database query and management
- /api/schema/* - Schema deployment and management

Timer Functions:
- Poison queue monitor - Every 5 minutes
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