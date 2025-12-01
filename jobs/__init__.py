# ============================================================================
# CLAUDE CONTEXT - JOB REGISTRY
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Core Architecture - Explicit job registration (no decorators)
# PURPOSE: Central registry of all available jobs for Job→Stage→Task architecture
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: ALL_JOBS (dict mapping job_type to job class), JobBase
# INTERFACES: None (pure Python dict registry)
# PYDANTIC_MODELS: None (individual jobs define their own models)
# DEPENDENCIES: All job classes (hello_world, ingest_vector, process_large_raster, etc.)
# SOURCE: Explicit imports and dictionary definition (no auto-discovery)
# SCOPE: Job type to job class mapping for entire application
# VALIDATION: Import-time validation (missing jobs cause immediate import errors)
# PATTERNS: Registry pattern, Explicit registration (anti-decorator), Single source of truth
# ENTRY_POINTS: from jobs import ALL_JOBS; job_class = ALL_JOBS["hello_world"]
# INDEX: ALL_JOBS:61, Job imports:37-50
# ============================================================================

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

Last Updated: 29 OCT 2025
"""

from .base import JobBase
from .hello_world import HelloWorldJob  # ← Now uses JobBaseMixin pattern (14 NOV 2025)
from .container_summary import ContainerSummaryWorkflow
from .container_list import ListContainerContentsWorkflow
from .container_list_diamond import ListContainerContentsDiamondWorkflow
from .stac_catalog_container import StacCatalogContainerWorkflow
from .stac_catalog_vectors import StacCatalogVectorsWorkflow
# ingest_vector REMOVED (27 NOV 2025) - Replaced by process_vector (idempotent DELETE+INSERT)
from .validate_raster_job import ValidateRasterJob
from .process_raster import ProcessRasterWorkflow
from .generate_h3_level4 import GenerateH3Level4Job
from .create_h3_base import CreateH3BaseJob
from .bootstrap_h3_land_grid_pyramid import BootstrapH3LandGridPyramidJob
from .process_raster_collection import ProcessRasterCollectionWorkflow
from .process_large_raster import ProcessLargeRasterWorkflow
from .process_fathom import ProcessFathomWorkflow
from .process_vector import ProcessVectorJob  # Idempotent vector ETL (26 NOV 2025)
from .process_raster_v2 import ProcessRasterV2Job  # Mixin pattern raster ETL (28 NOV 2025)
from .raster_mixin import RasterMixin  # Shared raster infrastructure (30 NOV 2025)
from .process_raster_collection_v2 import ProcessRasterCollectionV2Job  # Mixin pattern collection ETL (30 NOV 2025)
from .process_large_raster_v2 import ProcessLargeRasterV2Job  # Mixin pattern large raster ETL (30 NOV 2025)

# ============================================================================
# EXPLICIT JOB REGISTRY
# ============================================================================
# To add a new job:
# 1. Create jobs/your_job.py with YourJobClass
# 2. Import it above
# 3. Add entry to ALL_JOBS dict below
# ============================================================================

ALL_JOBS = {
    # Production Workflows
    "hello_world": HelloWorldJob,
    "summarize_container": ContainerSummaryWorkflow,
    "list_container_contents": ListContainerContentsWorkflow,
    "stac_catalog_container": StacCatalogContainerWorkflow,
    "stac_catalog_vectors": StacCatalogVectorsWorkflow,
    # "ingest_vector" REMOVED (27 NOV 2025) - Platform now routes to process_vector
    "validate_raster_job": ValidateRasterJob,
    "process_raster": ProcessRasterWorkflow,
    "process_raster_collection": ProcessRasterCollectionWorkflow,  # Multi-tile COG + MosaicJSON (20 OCT 2025)
    "process_large_raster": ProcessLargeRasterWorkflow,  # Large raster tiling (1-30 GB) → COG mosaic (24 OCT 2025)
    "generate_h3_level4": GenerateH3Level4Job,
    "create_h3_base": CreateH3BaseJob,
    "bootstrap_h3_land_grid_pyramid": BootstrapH3LandGridPyramidJob,  # H3 land pyramid bootstrap (res 2-7) - 14 NOV 2025
    "process_fathom": ProcessFathomWorkflow,  # Fathom flood hazard consolidation (26 NOV 2025)
    "process_vector": ProcessVectorJob,  # Idempotent vector ETL with DELETE+INSERT pattern (26 NOV 2025)
    "process_raster_v2": ProcessRasterV2Job,  # Mixin pattern raster ETL - clean slate (28 NOV 2025)
    "process_raster_collection_v2": ProcessRasterCollectionV2Job,  # Mixin pattern collection ETL (30 NOV 2025)
    "process_large_raster_v2": ProcessLargeRasterV2Job,  # Mixin pattern large raster tiling (30 NOV 2025)

    # Test/Diagnostic Workflows
    "list_container_contents_diamond": ListContainerContentsDiamondWorkflow,  # TEST ONLY - Fan-in demo (16 OCT 2025)

    # Add new jobs here explicitly
}

# ============================================================================
# VALIDATION
# ============================================================================

def validate_job_registry():
    """
    Validate all jobs in registry on startup.

    This catches configuration errors immediately at import time,
    not when a user tries to submit a job.

    Validates:
    1. Required attributes (stages, job_type, description)
    2. Required methods (interface contract - 5 methods)
    3. Stage structure (list, not empty)
    4. ABC inheritance (JobBase enforces method signatures at class definition)

    Note: As of Phase 2 (15 OCT 2025), jobs should inherit from JobBase ABC.
    ABC enforcement happens automatically at class definition time, providing:
    - Fail-fast at import (not at HTTP request)
    - IDE autocomplete and type hints
    - Clear method signature documentation

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
                f"  - Complex pipeline: jobs/process_raster.py\n"
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
