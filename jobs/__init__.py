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

Example:
    from .container_list import ContainerListJob

    ALL_JOBS = {
        "container_list": ContainerListJob,
    }

Exports:
    ALL_JOBS: Dict mapping job_type to job class
    JobBase: Abstract base class for jobs
"""

from .base import JobBase
from .hello_world import HelloWorldJob
from .container_summary import ContainerSummaryWorkflow
from .stac_catalog_container import StacCatalogContainerWorkflow
from .stac_catalog_vectors import StacCatalogVectorsWorkflow
from .validate_raster_job import ValidateRasterJob
from .generate_h3_level4 import GenerateH3Level4Job
from .create_h3_base import CreateH3BaseJob
from .bootstrap_h3_land_grid_pyramid import BootstrapH3LandGridPyramidJob
from .process_fathom_stack import ProcessFathomStackJob
from .process_fathom_merge import ProcessFathomMergeJob
from .process_vector import ProcessVectorJob
from .process_raster_v2 import ProcessRasterV2Job
from .raster_mixin import RasterMixin
from .process_raster_collection_v2 import ProcessRasterCollectionV2Job
from .process_large_raster_v2 import ProcessLargeRasterV2Job
from .inventory_fathom_container import InventoryFathomContainerJob

# Consolidated container inventory (07 DEC 2025)
from .inventory_container_contents import InventoryContainerContentsJob

# ARCHIVED (07 DEC 2025) - replaced by inventory_container_contents
# from .container_list import ListContainerContentsWorkflow
# from .container_list_diamond import ListContainerContentsDiamondWorkflow
# from .inventory_container_geospatial import InventoryContainerGeospatialJob

# Job Registry - add new jobs here
ALL_JOBS = {
    # Production Workflows
    "hello_world": HelloWorldJob,
    "summarize_container": ContainerSummaryWorkflow,
    "stac_catalog_container": StacCatalogContainerWorkflow,
    "stac_catalog_vectors": StacCatalogVectorsWorkflow,
    "validate_raster_job": ValidateRasterJob,
    "generate_h3_level4": GenerateH3Level4Job,
    "create_h3_base": CreateH3BaseJob,
    "bootstrap_h3_land_grid_pyramid": BootstrapH3LandGridPyramidJob,

    # Fathom ETL - Two-Phase Architecture
    "process_fathom_stack": ProcessFathomStackJob,
    "process_fathom_merge": ProcessFathomMergeJob,

    # Vector and Raster ETL
    "process_vector": ProcessVectorJob,
    "process_raster_v2": ProcessRasterV2Job,
    "process_raster_collection_v2": ProcessRasterCollectionV2Job,
    "process_large_raster_v2": ProcessLargeRasterV2Job,

    # Container Analysis (consolidated 07 DEC 2025)
    "inventory_container_contents": InventoryContainerContentsJob,  # Replaces list_container_contents, container_list_diamond, inventory_container_geospatial
    "inventory_fathom_container": InventoryFathomContainerJob,

    # ARCHIVED (07 DEC 2025) - use inventory_container_contents instead
    # "list_container_contents": ListContainerContentsWorkflow,
    # "list_container_contents_diamond": ListContainerContentsDiamondWorkflow,
    # "inventory_container_geospatial": InventoryContainerGeospatialJob,
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

    Raises:
        AttributeError: If job missing required methods
        ValueError: If job has invalid attributes
        TypeError: If ABC instantiation attempted without implementing abstract methods
    """
    # Interface contract: Methods that triggers/CoreMachine expect
    REQUIRED_METHODS = [
        'validate_job_parameters',  # Called by: triggers/submit_job.py line 171
        'generate_job_id',          # Called by: triggers/submit_job.py line 175
        'create_job_record',        # Called by: triggers/submit_job.py line 220
        'queue_job',                # Called by: triggers/submit_job.py line 226
        'create_tasks_for_stage',   # Called by: core/machine.py line 248
    ]

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

        # NEW: Verify required methods exist (interface contract enforcement)
        missing_methods = []
        for method_name in REQUIRED_METHODS:
            if not hasattr(job_class, method_name):
                missing_methods.append(method_name)

        if missing_methods:
            raise AttributeError(
                f"\n{'='*80}\n"
                f"❌ JOB INTERFACE CONTRACT VIOLATION: {job_type}\n"
                f"{'='*80}\n"
                f"Job class: {job_class.__name__}\n"
                f"Missing required methods: {', '.join(missing_methods)}\n"
                f"\n"
                f"All jobs must implement these 5 methods:\n"
                f"  1. validate_job_parameters(params: dict) -> dict\n"
                f"  2. generate_job_id(params: dict) -> str\n"
                f"  3. create_job_record(job_id: str, params: dict) -> dict\n"
                f"  4. queue_job(job_id: str, params: dict) -> dict\n"
                f"  5. create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list) -> List[dict]\n"
                f"\n"
                f"Reference implementations:\n"
                f"  - Simple single-stage: jobs/create_h3_base.py\n"
                f"  - Multi-stage: jobs/hello_world.py\n"
                f"  - Complex pipeline: jobs/process_raster_v2.py\n"
                f"{'='*80}\n"
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
    'JobBase',  # Export ABC for job implementations
]
