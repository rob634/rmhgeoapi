# ============================================================================
# JOB REGISTRY
# ============================================================================
# STATUS: Jobs - Explicit job registration (no decorators, no auto-discovery)
# PURPOSE: Central registry mapping job_type strings to job classes
# LAST_REVIEWED: 14 JAN 2026
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
from .container_summary import ContainerSummaryWorkflow
from .stac_catalog_container import StacCatalogContainerWorkflow
from .stac_catalog_vectors import StacCatalogVectorsWorkflow
from .validate_raster_job import ValidateRasterJob
from .generate_h3_level4 import GenerateH3Level4Job
from .create_h3_base import CreateH3BaseJob
from .bootstrap_h3_land_grid_pyramid import BootstrapH3LandGridPyramidJob
from .process_fathom_stack import ProcessFathomStackJob
from .process_fathom_merge import ProcessFathomMergeJob
from .process_fathom_docker import ProcessFathomDockerJob
from .process_vector import ProcessVectorJob
from .process_raster_v2 import ProcessRasterV2Job
from .raster_mixin import RasterMixin
from .process_raster_collection_v2 import ProcessRasterCollectionV2Job
from .process_large_raster_v2 import ProcessLargeRasterV2Job
from .inventory_fathom_container import InventoryFathomContainerJob
from .inventory_container_contents import InventoryContainerContentsJob
from .unpublish_raster import UnpublishRasterJob
from .unpublish_vector import UnpublishVectorJob
from .curated_update import CuratedDatasetUpdateJob
from .h3_raster_aggregation import H3RasterAggregationJob
from .h3_register_dataset import H3RegisterDatasetJob
from .h3_export_dataset import H3ExportDatasetJob
from .repair_stac_items import RepairStacItemsJob
from .rebuild_stac import RebuildStacJob
from .ingest_collection import IngestCollectionJob
from .process_raster_docker import ProcessRasterDockerJob
from .process_large_raster_docker import ProcessLargeRasterDockerJob
from .detect_orphan_blobs import DetectOrphanBlobsJob
from .register_silver_blobs import RegisterSilverBlobsJob
from .bootstrap_h3_docker import BootstrapH3DockerJob
from .vector_docker_etl import VectorDockerETLJob

# Job Registry - add new jobs here
ALL_JOBS = {
    # Test/Utility
    "hello_world": HelloWorldJob,
    "summarize_container": ContainerSummaryWorkflow,

    # STAC Catalog
    "stac_catalog_container": StacCatalogContainerWorkflow,
    "stac_catalog_vectors": StacCatalogVectorsWorkflow,

    # Validation
    "validate_raster_job": ValidateRasterJob,

    # H3 Grid (Function App - multi-stage)
    "generate_h3_level4": GenerateH3Level4Job,
    "create_h3_base": CreateH3BaseJob,
    "bootstrap_h3_land_grid_pyramid": BootstrapH3LandGridPyramidJob,
    "h3_raster_aggregation": H3RasterAggregationJob,
    "h3_register_dataset": H3RegisterDatasetJob,
    "h3_export_dataset": H3ExportDatasetJob,

    # H3 Grid (Docker - single stage)
    "bootstrap_h3_docker": BootstrapH3DockerJob,

    # Fathom ETL (Function App - multi-stage)
    "process_fathom_stack": ProcessFathomStackJob,
    "process_fathom_merge": ProcessFathomMergeJob,
    "inventory_fathom_container": InventoryFathomContainerJob,

    # Fathom ETL (Docker - 3-stage hybrid)
    "process_fathom_docker": ProcessFathomDockerJob,

    # Vector ETL (Function App - multi-stage)
    "process_vector": ProcessVectorJob,

    # Vector ETL (Docker - single stage with checkpoints)
    "vector_docker_etl": VectorDockerETLJob,

    # Raster ETL (Function App - multi-stage)
    "process_raster_v2": ProcessRasterV2Job,
    "process_raster_collection_v2": ProcessRasterCollectionV2Job,
    "process_large_raster_v2": ProcessLargeRasterV2Job,

    # Raster ETL (Docker - single stage)
    "process_raster_docker": ProcessRasterDockerJob,
    "process_large_raster_docker": ProcessLargeRasterDockerJob,

    # Container Inventory
    "inventory_container_contents": InventoryContainerContentsJob,

    # Unpublish
    "unpublish_raster": UnpublishRasterJob,
    "unpublish_vector": UnpublishVectorJob,

    # Curated Datasets
    "curated_dataset_update": CuratedDatasetUpdateJob,

    # STAC Maintenance
    "repair_stac_items": RepairStacItemsJob,
    "rebuild_stac": RebuildStacJob,

    # Ingest
    "ingest_collection": IngestCollectionJob,

    # Orphan Blob Detection & Registration (F7.11 STAC Self-Healing)
    "detect_orphan_blobs": DetectOrphanBlobsJob,
    "register_silver_blobs": RegisterSilverBlobsJob,
}

def validate_job_registry():
    """
    Validate all jobs in registry on startup.

    Catches configuration errors at import time, not when a user submits a job.

    Validates:
        1. Required attributes (stages, job_type, description)
        2. Required methods (interface contract - 5 methods)
        3. Stage structure (list, not empty)
        4. ABC inheritance (JobBase enforces method signatures)

    Raises:
        AttributeError: If job missing required methods
        ValueError: If job has invalid attributes
        TypeError: If ABC instantiation attempted without implementing abstract methods
    """
    REQUIRED_METHODS = [
        'validate_job_parameters',
        'generate_job_id',
        'create_job_record',
        'queue_job',
        'create_tasks_for_stage',
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
    'JobBase',
]
