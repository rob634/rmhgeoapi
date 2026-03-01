# ============================================================================
# JOB REGISTRY
# ============================================================================
# STATUS: Jobs - Explicit job registration (no decorators, no auto-discovery)
# PURPOSE: Central registry mapping job_type strings to job classes
# LAST_REVIEWED: 13 FEB 2026
# ============================================================================
"""
Job Registry - Explicit job registration.

All jobs are registered here explicitly. No decorators, no auto-discovery.
If it's not in ALL_JOBS, it's not registered.

We use explicit registration because:
    1. Decorators only execute when module is imported
    2. If module never imported, decorators never run
    3. Explicit registration is clear, visible, and predictable

Registration Process:
    1. Create your job class in jobs/your_job.py
    2. Import it at the top of this file
    3. Add entry to ALL_JOBS dict
    4. Done - no decorators, no magic

Exports:
    ALL_JOBS: Dict mapping job_type to job class
    JobBase: Abstract base class for jobs

Historical context archived in: docs/archive/INIT_PY_HISTORY.md
"""

from .base import JobBase
from .hello_world import HelloWorldJob
from .stac_catalog_container import StacCatalogContainerWorkflow
from .validate_raster_job import ValidateRasterJob
from .raster_mixin import RasterMixin
from .unpublish_raster import UnpublishRasterJob
from .unpublish_vector import UnpublishVectorJob
from .process_raster_docker import ProcessRasterDockerJob
from .process_raster_collection_docker import ProcessRasterCollectionDockerJob
from .vector_docker_etl import VectorDockerETLJob
from .virtualzarr import VirtualZarrJob
from .unpublish_zarr import UnpublishZarrJob

# Job Registry - add new jobs here
# ARCHIVED (13 FEB 2026): H3 (7), Fathom (4), legacy Function App ETL (4) → docs/archive/v08_archive_feb2026/
# ARCHIVED (18 FEB 2026): V0.9 Docker migration — curated (1), ingest (1), inventory (2),
#   STAC catalog vectors (1), STAC repair (1), STAC rebuild (1), orphan blobs (2) → docs/archive/v09_archive_feb2026/
ALL_JOBS = {
    # Test/Utility
    "hello_world": HelloWorldJob,

    # STAC Catalog
    "stac_catalog_container": StacCatalogContainerWorkflow,

    # Validation
    "validate_raster_job": ValidateRasterJob,

    # Vector ETL (Docker - single stage with checkpoints)
    "vector_docker_etl": VectorDockerETLJob,

    # Raster ETL (Docker - single stage)
    "process_raster_docker": ProcessRasterDockerJob,
    "process_raster_collection_docker": ProcessRasterCollectionDockerJob,

    # Unpublish
    "unpublish_raster": UnpublishRasterJob,
    "unpublish_vector": UnpublishVectorJob,
    "unpublish_zarr": UnpublishZarrJob,

    # VirtualiZarr (NetCDF virtual reference pipeline)
    "virtualzarr": VirtualZarrJob,
}

def validate_job_registry():
    """
    Validate all jobs in registry on startup.

    Catches configuration errors at import time, not when a user submits a job.

    Validates:
        1. Required attributes (stages, job_type, description)
        2. Required methods (interface contract - 6 methods)
        3. Stage structure (list, not empty)
        4. ABC inheritance (JobBase enforces method signatures)
        5. ETL linkage: reversed_by → valid unpublish job, reverses → valid ETL jobs

    Raises:
        AttributeError: If job missing required methods
        ValueError: If job has invalid attributes or broken ETL linkage
        TypeError: If ABC instantiation attempted without implementing abstract methods
    """
    REQUIRED_METHODS = [
        'validate_job_parameters',
        'generate_job_id',
        'create_job_record',
        'queue_job',
        'create_tasks_for_stage',
        'finalize_job',
    ]

    registered_job_types = set(ALL_JOBS.keys())

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

        # Verify required methods exist (interface contract enforcement)
        missing_methods = []
        for method_name in REQUIRED_METHODS:
            if not hasattr(job_class, method_name):
                missing_methods.append(method_name)

        if missing_methods:
            raise AttributeError(
                f"\n{'='*80}\n"
                f"JOB INTERFACE CONTRACT VIOLATION: {job_type}\n"
                f"{'='*80}\n"
                f"Job class: {job_class.__name__}\n"
                f"Missing required methods: {', '.join(missing_methods)}\n"
                f"\n"
                f"All jobs must implement these 6 methods:\n"
                f"  1. validate_job_parameters(params: dict) -> dict\n"
                f"  2. generate_job_id(params: dict) -> str\n"
                f"  3. create_job_record(job_id: str, params: dict) -> dict\n"
                f"  4. queue_job(job_id: str, params: dict) -> dict\n"
                f"  5. create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list) -> List[dict]\n"
                f"  6. finalize_job(context) -> Dict[str, Any]\n"
                f"\n"
                f"JobBaseMixin provides 1-4. You must implement 5 and 6.\n"
                f"\n"
                f"Reference implementations:\n"
                f"  - Simple single-stage: jobs/process_raster_docker.py\n"
                f"  - Multi-stage: jobs/hello_world.py\n"
                f"  - Docker ETL: jobs/vector_docker_etl.py\n"
                f"{'='*80}\n"
            )

        # Validate ETL linkage: reversed_by must point to a registered job
        reversed_by = getattr(job_class, 'reversed_by', None)
        if reversed_by and reversed_by not in registered_job_types:
            raise ValueError(
                f"Job '{job_type}' has reversed_by='{reversed_by}' "
                f"but '{reversed_by}' is not a registered job. "
                f"Update reversed_by or register the unpublish job."
            )

        # Validate ETL linkage: reverses entries must all point to registered jobs
        reverses = getattr(job_class, 'reverses', None)
        if reverses:
            invalid = [r for r in reverses if r not in registered_job_types]
            if invalid:
                raise ValueError(
                    f"Job '{job_type}' has reverses={reverses} "
                    f"but these are not registered jobs: {invalid}. "
                    f"Update reverses list or register the missing jobs."
                )

    # Cross-validate: every reversed_by target should have a reverses list that includes the source
    for job_type, job_class in ALL_JOBS.items():
        reversed_by = getattr(job_class, 'reversed_by', None)
        if reversed_by:
            unpublish_class = ALL_JOBS[reversed_by]
            reverses = getattr(unpublish_class, 'reverses', None) or []
            if job_type not in reverses:
                raise ValueError(
                    f"ETL linkage mismatch: '{job_type}' declares reversed_by='{reversed_by}', "
                    f"but '{reversed_by}' does not list '{job_type}' in its reverses={reverses}. "
                    f"Add '{job_type}' to {unpublish_class.__name__}.reverses."
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


# Validate on import - fail fast if something's wrong.
validate_job_registry()

__all__ = [
    'ALL_JOBS',
    'get_job_class',
    'validate_job_registry',
    'JobBase',
]
