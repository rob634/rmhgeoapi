# ============================================================================
# CLAUDE CONTEXT - JOB REGISTRY
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Core component of new architecture
# PURPOSE: Job/Workflow registration system with decorator pattern
# EXPORTS: JOB_REGISTRY dict, register_job decorator, get_workflow function
# INTERFACES: Works with Workflow ABC
# PYDANTIC_MODELS: None directly, works with Workflow subclasses
# DEPENDENCIES: typing, jobs.workflow
# SOURCE: Framework pattern from epoch4_framework.md
# SCOPE: Application-wide job registration
# VALIDATION: Validates job_type uniqueness, Workflow subclass
# PATTERNS: Registry Pattern, Decorator Pattern
# ENTRY_POINTS: @register_job decorator, get_workflow()
# INDEX: JOB_REGISTRY:30, register_job:40, get_workflow:70
# ============================================================================

"""
Job Registry - Workflow Registration System

Provides decorator-based registration for workflow/job definitions.
Maps job_type strings to Workflow classes for dynamic instantiation.

Usage:
    @register_job
    class HelloWorldWorkflow(Workflow):
        ...

    # Later:
    workflow = get_workflow("hello_world")

Author: Robert and Geospatial Claude Legion
Date: 30 SEP 2025
"""

from typing import Dict, Type
from jobs.workflow import Workflow


# ============================================================================
# GLOBAL REGISTRY
# ============================================================================

JOB_REGISTRY: Dict[str, Type[Workflow]] = {}
"""
Global registry mapping job_type → Workflow class.

Example:
    {
        "hello_world": HelloWorldWorkflow,
        "raster_ingest": RasterIngestWorkflow,
    }
"""


# ============================================================================
# REGISTRATION DECORATOR
# ============================================================================

def register_job(workflow_class: Type[Workflow]) -> Type[Workflow]:
    """
    Decorator to register a workflow/job class in the global registry.

    Usage:
        @register_job
        class HelloWorldWorkflow(Workflow):
            def define_stages(self):
                return [...]

    Args:
        workflow_class: Workflow subclass to register

    Returns:
        The same class (unchanged, just registered)

    Raises:
        TypeError: If class is not a Workflow subclass
        ValueError: If job_type already registered
    """
    # Validate it's a Workflow subclass
    if not issubclass(workflow_class, Workflow):
        raise TypeError(
            f"{workflow_class.__name__} must inherit from Workflow"
        )

    # Get job_type from the class
    instance = workflow_class()
    job_type = instance.get_job_type()

    # Check for duplicates
    if job_type in JOB_REGISTRY:
        existing = JOB_REGISTRY[job_type]
        raise ValueError(
            f"Job type '{job_type}' already registered to {existing.__name__}. "
            f"Cannot register {workflow_class.__name__}."
        )

    # Register it
    JOB_REGISTRY[job_type] = workflow_class

    return workflow_class


# ============================================================================
# LOOKUP FUNCTIONS
# ============================================================================

def get_workflow(job_type: str) -> Workflow:
    """
    Get a workflow instance by job_type.

    Args:
        job_type: Job type identifier (e.g., "hello_world")

    Returns:
        Workflow instance

    Raises:
        ValueError: If job_type not found in registry

    Example:
        workflow = get_workflow("hello_world")
        stages = workflow.define_stages()
    """
    if job_type not in JOB_REGISTRY:
        available = ', '.join(sorted(JOB_REGISTRY.keys()))
        raise ValueError(
            f"Unknown job type: '{job_type}'. "
            f"Available: {available or '(none registered)'}"
        )

    workflow_class = JOB_REGISTRY[job_type]
    return workflow_class()


def list_registered_jobs() -> list[str]:
    """
    Get list of all registered job types.

    Returns:
        Sorted list of job_type strings

    Example:
        >>> list_registered_jobs()
        ['hello_world', 'raster_ingest', 'vector_ingest']
    """
    return sorted(JOB_REGISTRY.keys())


def is_registered(job_type: str) -> bool:
    """
    Check if a job type is registered.

    Args:
        job_type: Job type identifier

    Returns:
        True if registered, False otherwise
    """
    return job_type in JOB_REGISTRY
