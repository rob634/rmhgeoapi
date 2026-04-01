# ============================================================================
# CLAUDE CONTEXT - UI ADAPTERS
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Core - Public API for record-to-DTO conversion
# PURPOSE: Re-export converters that map DB records to stable UI DTOs
# LAST_REVIEWED: 01 APR 2026
# EXPORTS: job_to_dto, task_to_dto, asset_to_dto, jobs_to_dto, tasks_to_dto,
#          stage_to_node_dto, job_event_to_dto
# DEPENDENCIES: ui.adapters.converters
# ============================================================================
"""
UI Adapters.

Public API for converting infrastructure DB records (JobRecord, TaskRecord,
Asset) to stable UI DTOs used by templates and routes.

Usage:
    from ui.adapters import job_to_dto, task_to_dto, asset_to_dto

    job_dto = job_to_dto(job_record)
    task_dto = task_to_dto(task_record)
    asset_dto = asset_to_dto(asset)
"""

from .converters import (
    job_to_dto,
    task_to_dto,
    asset_to_dto,
    jobs_to_dto,
    tasks_to_dto,
    stage_to_node_dto,
    job_event_to_dto,
)

__all__ = [
    "job_to_dto",
    "task_to_dto",
    "asset_to_dto",
    "jobs_to_dto",
    "tasks_to_dto",
    "stage_to_node_dto",
    "job_event_to_dto",
]
