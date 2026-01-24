# ============================================================================
# CLAUDE CONTEXT - PROCESS FATHOM DOCKER JOB
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Job Definition - FATHOM flood data processing via Docker workers
# PURPOSE: 3-stage hybrid job combining Functions (orchestration) + Docker (processing)
# LAST_REVIEWED: 24 JAN 2026
# EXPORTS: ProcessFathomDockerJob
# DEPENDENCIES: jobs.base, jobs.mixins
# ============================================================================
"""
FATHOM Flood Data Processing - Docker Worker Job.

This job implements a 3-stage hybrid architecture:
    Stage 1: fathom_chunk_inventory (Azure Functions)
        - Scan database for pending work
        - Create work chunks (by region or adaptive)
        - Pre-create STAC collections (eliminates race conditions)

    Stage 2: fathom_process_chunk (Docker workers - FAN-OUT)
        - Process tiles: band stack + spatial merge
        - VRT-based merge for memory efficiency
        - Upsert STAC items per chunk
        - Re-register mosaic search

    Stage 3: fathom_finalize (Azure Functions)
        - Validate expected vs actual item counts
        - Update collection extents
        - Aggregate job metrics

Parallelism:
    - Stage 2 fans out to N Docker workers via Service Bus
    - Each chunk processes independently
    - Global runs can complete in 1-2 days with 20 workers

Collection Strategy:
    - One STAC collection per region: fathom-flood-{region}
    - Supports single region, multi-region, or continent scope
    - Country-based collections are the default pattern

Usage:
    # Single region (development)
    POST /api/jobs/submit/process_fathom_docker
    {"region_code": "rwa", "grid_size": 5}

    # Multi-region (production)
    POST /api/jobs/submit/process_fathom_docker
    {"regions": ["rwa", "ken", "uga"], "grid_size": 5}

    # Continent (large scale)
    POST /api/jobs/submit/process_fathom_docker
    {"continent": "africa", "grid_size": 10, "chunk_strategy": "adaptive"}
"""

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class ProcessFathomDockerJob(JobBaseMixin, JobBase):
    """
    FATHOM flood data processing - 3-stage hybrid Docker job.

    Combines Phase 1 (band stacking) and Phase 2 (spatial merge) into
    a unified workflow with cross-region parallelism.
    """

    job_type = "process_fathom_docker"
    description = "Process FATHOM flood data (Docker - hybrid parallel pipeline)"

    # 3-stage hybrid architecture
    stages = [
        {
            "number": 1,
            "name": "chunk_inventory",
            "task_type": "fathom_chunk_inventory",
            "parallelism": "single",
            "description": "Create work chunks and pre-create STAC collections"
        },
        {
            "number": 2,
            "name": "process_chunks",
            "task_type": "fathom_process_chunk",
            "parallelism": "fan_out",
            "description": "Process chunks in parallel on Docker workers"
        },
        {
            "number": 3,
            "name": "finalize",
            "task_type": "fathom_finalize",
            "parallelism": "single",
            "description": "Validate results and update collection metadata"
        }
    ]

    parameters_schema = {
        # ═══════════════════════════════════════════════════════════════
        # SCOPE SELECTION (mutually exclusive - one required)
        # ═══════════════════════════════════════════════════════════════
        'continent': {
            'type': 'str',
            'required': False,
            'description': 'Process entire continent: africa, asia, europe, north_america, south_america, oceania, global'
        },
        'regions': {
            'type': 'list',
            'required': False,
            'description': 'List of region codes to process: ["rwa", "ken", "uga"]'
        },
        'region_code': {
            'type': 'str',
            'required': False,
            'description': 'Single region code (e.g., "rwa") - creates one country-based collection'
        },
        'bbox': {
            'type': 'list',
            'required': False,
            'description': 'Optional spatial filter [west, south, east, north]'
        },

        # ═══════════════════════════════════════════════════════════════
        # CHUNKING STRATEGY
        # ═══════════════════════════════════════════════════════════════
        'chunk_strategy': {
            'type': 'str',
            'default': 'region',
            'description': 'How to divide work: region (one chunk per country), grid_cell, or adaptive'
        },
        'max_tiles_per_chunk': {
            'type': 'int',
            'default': 500,
            'description': 'Split large regions if tile count exceeds this threshold'
        },

        # ═══════════════════════════════════════════════════════════════
        # PROCESSING OPTIONS
        # ═══════════════════════════════════════════════════════════════
        'grid_size': {
            'type': 'int',
            'default': 5,
            'description': 'Grid cell size in degrees for spatial merge (1-20)'
        },
        'skip_phase1': {
            'type': 'bool',
            'default': False,
            'description': 'Skip band stacking - use existing stacked COGs (resume Phase 2)'
        },
        'skip_phase2': {
            'type': 'bool',
            'default': False,
            'description': 'Skip spatial merge - Phase 1 only mode'
        },

        # ═══════════════════════════════════════════════════════════════
        # DATA FILTERS
        # ═══════════════════════════════════════════════════════════════
        'flood_types': {
            'type': 'list',
            'required': False,
            'description': 'Filter by flood type: ["fluvial", "pluvial", "coastal"]'
        },
        'years': {
            'type': 'list',
            'required': False,
            'description': 'Filter by year: [2020, 2030, 2050]'
        },
        'ssp_scenarios': {
            'type': 'list',
            'required': False,
            'description': 'Filter by SSP scenario: ["SSP2_4.5", "SSP5_8.5"]'
        },

        # ═══════════════════════════════════════════════════════════════
        # STAC / OUTPUT
        # ═══════════════════════════════════════════════════════════════
        'collection_id': {
            'type': 'str',
            'default': 'fathom-flood',
            'description': 'Base STAC collection ID (region suffix added automatically)'
        },

        # ═══════════════════════════════════════════════════════════════
        # BEHAVIOR
        # ═══════════════════════════════════════════════════════════════
        'force_reprocess': {
            'type': 'bool',
            'default': False,
            'description': 'Reprocess even if outputs already exist'
        },
        'dry_run': {
            'type': 'bool',
            'default': False,
            'description': 'Inventory only - do not process or create COGs'
        }
    }

    @staticmethod
    def validate_parameters(params: dict) -> dict:
        """
        Validate job parameters.

        Ensures at least one scope parameter is provided and validates
        grid_size range.
        """
        # Check that at least one scope is specified
        has_scope = any([
            params.get('continent'),
            params.get('regions'),
            params.get('region_code')
        ])

        if not has_scope:
            raise ValueError(
                "Must specify at least one scope: 'continent', 'regions', or 'region_code'"
            )

        # Validate grid_size
        grid_size = params.get('grid_size', 5)
        if not (1 <= grid_size <= 20):
            raise ValueError(f"grid_size must be between 1 and 20, got {grid_size}")

        # Validate continent if provided
        valid_continents = [
            'africa', 'asia', 'europe', 'north_america',
            'south_america', 'oceania', 'global'
        ]
        continent = params.get('continent')
        if continent and continent.lower() not in valid_continents:
            raise ValueError(
                f"Invalid continent '{continent}'. Must be one of: {valid_continents}"
            )

        # Validate chunk_strategy
        valid_strategies = ['region', 'grid_cell', 'adaptive']
        strategy = params.get('chunk_strategy', 'region')
        if strategy not in valid_strategies:
            raise ValueError(
                f"Invalid chunk_strategy '{strategy}'. Must be one of: {valid_strategies}"
            )

        return params

    @staticmethod
    def create_tasks_for_stage(stage: dict, job_params: dict, job_id: str,
                                previous_results: dict = None) -> list:
        """
        Create tasks for each stage.

        Stage 1: Single inventory task
        Stage 2: Fan-out tasks from Stage 1 chunks
        Stage 3: Single finalization task
        """
        stage_number = stage['number']
        task_type = stage['task_type']

        if stage_number == 1:
            # Stage 1: Single inventory task
            return [{
                "task_id": f"{job_id[:8]}-s1-inventory",
                "task_type": task_type,
                "parameters": {
                    "job_id": job_id,
                    "job_parameters": job_params
                }
            }]

        elif stage_number == 2:
            # Stage 2: Fan-out from Stage 1 chunks
            if not previous_results:
                raise ValueError("Stage 2 requires Stage 1 results with chunks")

            # Extract chunks from Stage 1 result
            stage1_result = previous_results.get('result', {})
            chunks = stage1_result.get('chunks', [])

            if not chunks:
                # No chunks to process (possibly dry_run or no pending work)
                return []

            tasks = []
            for idx, chunk in enumerate(chunks):
                tasks.append({
                    "task_id": f"{job_id[:8]}-s2-{chunk['chunk_id'][:12]}",
                    "task_type": task_type,
                    "parameters": {
                        "job_id": job_id,
                        "job_parameters": job_params,
                        "chunk": chunk,
                        "chunk_index": idx,
                        "total_chunks": len(chunks)
                    }
                })

            return tasks

        elif stage_number == 3:
            # Stage 3: Single finalization task
            return [{
                "task_id": f"{job_id[:8]}-s3-finalize",
                "task_type": task_type,
                "parameters": {
                    "job_id": job_id,
                    "job_parameters": job_params,
                    "stage1_result": previous_results.get('stage1_result', {}),
                    "chunk_results": previous_results.get('stage2_results', [])
                }
            }]

        else:
            raise ValueError(f"Unknown stage number: {stage_number}")


# Export the job class
__all__ = ['ProcessFathomDockerJob']
