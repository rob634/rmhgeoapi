"""
Job Registry - Explicit Registration (No Decorators!)

All jobs are registered here explicitly. No decorators, no auto-discovery, no import magic.
If you don't see it in ALL_JOBS, it's not registered.

CRITICAL: We avoid decorator-based registration because:
1. Decorators only execute when module is imported
2. If service module never imported, decorators never run
3. This caused silent registration failures in previous implementation (10 SEP 2025)
4. Explicit registration is clear, visible, and predictable

Registration Process:
1. Create your job class in jobs/your_job.py
2. Import it at the top of this file: `from .your_job import YourJob`
3. Add entry to ALL_JOBS dict: `"your_job": YourJob`
4. Done! No decorators, no magic, just a simple dict

Example:
    # In jobs/container_list.py:
    class ContainerListJob:
        job_type = "container_list"
        stages = [...]
    
    # In jobs/__init__.py (this file):
    from .container_list import ContainerListJob
    
    ALL_JOBS = {
        "hello_world": HelloWorldJob,
        "container_list": ContainerListJob,  # <- Added here!
    }

Author: Robert and Geospatial Claude Legion
Date: 1 OCT 2025
"""

from .hello_world import HelloWorldJob
from .container_summary import ContainerSummaryWorkflow
from .container_list import ListContainerContentsWorkflow

# ============================================================================
# EXPLICIT JOB REGISTRY
# ============================================================================
# To add a new job:
# 1. Create jobs/your_job.py with YourJobClass
# 2. Import it above
# 3. Add entry to ALL_JOBS dict below
# ============================================================================

ALL_JOBS = {
    "hello_world": HelloWorldJob,
    "summarize_container": ContainerSummaryWorkflow,
    "list_container_contents": ListContainerContentsWorkflow,
    # Add new jobs here explicitly
    # "process_raster": ProcessRasterJob,
}

# ============================================================================
# VALIDATION
# ============================================================================

def validate_job_registry():
    """
    Validate all jobs in registry on startup.

    This catches configuration errors immediately at import time,
    not when a user tries to submit a job.
    """
    for job_type, job_class in ALL_JOBS.items():
        # Verify required attributes exist
        if not hasattr(job_class, 'stages'):
            raise ValueError(
                f"Job {job_type} missing required 'stages' attribute. "
                f"Job classes must define stages for orchestration."
            )

        # Verify stages is a list
        if not isinstance(job_class.stages, list):
            raise ValueError(
                f"Job {job_type} 'stages' must be a list, got {type(job_class.stages).__name__}"
            )

        # Verify stages not empty
        if not job_class.stages:
            raise ValueError(
                f"Job {job_type} has empty 'stages' list. Jobs must have at least one stage."
            )

    return True


def get_job_class(job_type: str):
    """
    Get job class by type.

    Args:
        job_type: Job type string (e.g., "hello_world")

    Returns:
        Job class

    Raises:
        ValueError: If job_type not in registry
    """
    if job_type not in ALL_JOBS:
        available = list(ALL_JOBS.keys())
        raise ValueError(
            f"Unknown job type: '{job_type}'. "
            f"Available jobs: {available}"
        )

    return ALL_JOBS[job_type]


# Validate on import - fail fast if something's wrong!
validate_job_registry()

__all__ = [
    'ALL_JOBS',
    'get_job_class',
    'validate_job_registry',
]
