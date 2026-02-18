# ============================================================================
# REGISTER SILVER BLOBS JOB
# ============================================================================
# STATUS: Jobs - 2-stage STAC registration from existing silver blobs
# PURPOSE: Create cog_metadata + STAC items for orphaned silver blobs
# CREATED: 14 JAN 2026
# EPIC: E7 Pipeline Infrastructure -> F7.11 STAC Catalog Self-Healing
# ============================================================================
"""
Register Silver Blobs Job.

Creates both app.cog_metadata entries and STAC items for COGs that exist
in silver storage but have no metadata registration. Supports custom
schema profiles for domain-specific metadata (e.g., FATHOM flood data).

Use detect_orphan_blobs job first to identify orphaned blobs, then use
this job to register them.

Stages:
    1. validate - Verify blobs exist, check not already registered
    2. register - Extract COG metadata, create cog_metadata + STAC (fan-out)

Parameters:
    blobs: List of blob references to register (required)
           Each item: {"container": str, "blob_path": str} or just blob_path string
    container: Default container if blobs are just paths (optional)
    zone: Storage zone - "silver" or "silverext" (default: "silver")
    collection_id: Target STAC collection (default: "system-rasters")
    schema_profile: Custom schema - "default", "fathom", or dict (default: "default")
    dry_run: Validate only without registering (default: true)
    force_recreate: Delete existing STAC item if exists (default: false)

Schema Profiles:
    - "default": Standard STAC with azure:* and proj:* extensions
    - "fathom": FATHOM flood data schema with fathom:* properties
    - dict: Custom properties to add (e.g., {"my:property": "value"})

Usage:
    # From detect_orphan_blobs output:
    POST /api/jobs/submit/register_silver_blobs
    {
        "blobs": [
            {"container": "silver-cogs", "blob_path": "path/to/file.tif"},
            {"container": "silver-cogs", "blob_path": "other/file.tif"}
        ],
        "collection_id": "my-collection",
        "dry_run": false
    }

    # Simple list with default container:
    POST /api/jobs/submit/register_silver_blobs
    {
        "container": "silver-cogs",
        "blobs": ["path/to/file.tif", "other/file.tif"],
        "dry_run": false
    }

    # With FATHOM schema profile:
    POST /api/jobs/submit/register_silver_blobs
    {
        "blobs": [...],
        "schema_profile": "fathom",
        "collection_id": "fathom-flood-data"
    }

Exports:
    RegisterSilverBlobsJob: Job class for STAC registration
"""

from typing import List, Dict, Any

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class RegisterSilverBlobsJob(JobBaseMixin, JobBase):
    """
    Register silver blobs with metadata and STAC.

    Two-stage pipeline:
        1. validate - Check blobs exist, verify not already registered
        2. register - Extract COG metadata, create cog_metadata + STAC (fan-out)

    Schema Profile Extensibility:
        Custom schema profiles allow domain-specific STAC properties.
        Built-in profiles: "default", "fathom"
        Custom: Pass a dict with properties to add to STAC items.
    """

    job_type = "register_silver_blobs"
    description = "Create STAC entries for orphaned silver blobs"

    stages = [
        {
            "number": 1,
            "name": "validate",
            "task_type": "silver_blob_validate",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "register",
            "task_type": "silver_blob_register",
            "parallelism": "fan_out"
        }
    ]

    parameters_schema = {
        'blobs': {
            'type': 'list',
            'required': True,
            'min_length': 1,
            'max_length': 500,
            'description': 'List of blobs to register (dicts or paths)'
        },
        'container': {
            'type': 'str',
            'required': False,
            'default': None,
            'description': 'Default container when blobs are just paths'
        },
        'zone': {
            'type': 'str',
            'required': False,
            'default': 'silver',
            'enum': ['silver', 'silverext'],
            'description': 'Storage zone for multi-account setup'
        },
        'collection_id': {
            'type': 'str',
            'required': False,
            'default': None,
            'description': 'Target STAC collection (default: auto-detect or system-rasters)'
        },
        'schema_profile': {
            'type': 'any',  # str or dict
            'required': False,
            'default': 'default',
            'description': 'Schema profile: "default", "fathom", or custom dict'
        },
        'dry_run': {
            'type': 'bool',
            'required': False,
            'default': True,
            'description': 'Validate only without registering'
        },
        'force_recreate': {
            'type': 'bool',
            'required': False,
            'default': False,
            'description': 'Delete existing STAC item before creating'
        }
    }

    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[Dict[str, Any]]:
        """
        Generate tasks for each stage.

        Stage 1: Single validate task to check all blobs
        Stage 2: One register task per valid blob (fan-out)
        """
        if stage == 1:
            # Normalize blobs to consistent format
            blobs = job_params.get('blobs', [])
            default_container = job_params.get('container')

            normalized_blobs = []
            for blob in blobs:
                if isinstance(blob, dict):
                    normalized_blobs.append({
                        "container": blob.get("container", default_container),
                        "blob_path": blob.get("blob_path") or blob.get("name")
                    })
                elif isinstance(blob, str):
                    normalized_blobs.append({
                        "container": default_container,
                        "blob_path": blob
                    })

            return [{
                "task_id": f"{job_id[:8]}-validate",
                "task_type": "silver_blob_validate",
                "parameters": {
                    "blobs": normalized_blobs,
                    "zone": job_params.get('zone', 'silver'),
                    "collection_id": job_params.get('collection_id'),
                    "force_recreate": job_params.get('force_recreate', False),
                    "job_id": job_id
                }
            }]

        elif stage == 2:
            # Stage 2: Register - one task per valid blob
            if not previous_results:
                return []

            validate_result = previous_results[0].get('result', {})
            valid_blobs = validate_result.get('valid_blobs', [])

            # If dry run, skip register stage
            if job_params.get('dry_run', True):
                return []

            # Create register task for each valid blob
            register_tasks = []
            schema_profile = job_params.get('schema_profile', 'default')
            collection_id = validate_result.get('collection_id') or job_params.get('collection_id')

            for idx, blob_info in enumerate(valid_blobs):
                register_tasks.append({
                    "task_id": f"{job_id[:8]}-register-{idx:04d}",
                    "task_type": "silver_blob_register",
                    "parameters": {
                        "container": blob_info.get('container'),
                        "blob_path": blob_info.get('blob_path'),
                        "zone": job_params.get('zone', 'silver'),
                        "collection_id": collection_id,
                        "schema_profile": schema_profile,
                        "force_recreate": job_params.get('force_recreate', False),
                        "job_id": job_id
                    }
                })

            return register_tasks

        return []

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """Create final job summary."""
        if not context:
            return {
                "status": "completed",
                "job_type": "register_silver_blobs"
            }

        # Aggregate results
        total_requested = 0
        valid_count = 0
        invalid_count = 0
        registered_count = 0
        failed_count = 0
        dry_run = True
        collection_id = None

        for task_result in context.task_results:
            result_data = task_result.result_data or {}
            result = result_data.get('result', {})

            if task_result.task_type == 'silver_blob_validate':
                total_requested = result.get('total_requested', 0)
                valid_count = len(result.get('valid_blobs', []))
                invalid_count = len(result.get('invalid_blobs', []))
                dry_run = result.get('dry_run', True)
                collection_id = result.get('collection_id')

            elif task_result.task_type == 'silver_blob_register':
                if result.get('registered', False):
                    registered_count += 1
                elif not task_result.success:
                    failed_count += 1

        summary = {
            "total_requested": total_requested,
            "valid_blobs": valid_count,
            "invalid_blobs": invalid_count,
            "registered": registered_count,
            "failed": failed_count,
            "dry_run": dry_run
        }

        if collection_id:
            summary["collection_id"] = collection_id

        return {
            "status": "completed",
            "job_type": "register_silver_blobs",
            "summary": summary
        }


# Module exports
__all__ = ['RegisterSilverBlobsJob']
