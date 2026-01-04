# ============================================================================
# PURE ENUMERATION TYPES
# ============================================================================
# STATUS: Core - Type definitions without business logic
# PURPOSE: Job, Task, and Stage status enums plus RasterType classification
# LAST_REVIEWED: 03 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Pure Enumeration Types for Core Framework.

Defines valid states for jobs, tasks, and stages.
No business logic - pure type definitions only.

Exports:
    JobStatus: Job state enumeration
    TaskStatus: Task state enumeration
    StageStatus: Stage state enumeration
    RasterType: Raster type classification
"""

from enum import Enum


class JobStatus(Enum):
    """
    Valid status values for jobs.

    State transitions:
    - QUEUED -> PROCESSING -> COMPLETED (normal flow)
    - QUEUED -> PROCESSING -> FAILED (processing failure)
    - QUEUED -> FAILED (early failure before processing starts - 11 NOV 2025)
    - QUEUED -> PROCESSING -> COMPLETED_WITH_ERRORS
    """

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"


class TaskStatus(Enum):
    """
    Valid status values for tasks.

    State transitions (16 DEC 2025 - PENDING status added):
    - PENDING -> QUEUED (trigger confirms message received)
    - QUEUED -> PROCESSING -> COMPLETED
    - QUEUED -> PROCESSING -> FAILED
    - QUEUED -> PROCESSING -> FAILED -> RETRYING -> PROCESSING

    PENDING vs QUEUED:
    - PENDING: Task record created in DB, message sent to Service Bus, awaiting trigger confirmation
    - QUEUED: Trigger received message, confirmed delivery, task ready for processing
    """

    PENDING = "pending"  # Task created, message sent but not yet confirmed by trigger
    QUEUED = "queued"  # Trigger confirmed message receipt
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    PENDING_RETRY = "pending_retry"  # Waiting for retry
    CANCELLED = "cancelled"  # Task was cancelled


class StageStatus(Enum):
    """
    Valid status values for stages within a job.

    These are derived from task statuses but tracked separately
    for stage-level orchestration.
    """

    PENDING = "pending"  # Stage not yet started
    PROCESSING = "processing"  # Stage has active tasks
    COMPLETED = "completed"  # All tasks in stage completed
    FAILED = "failed"  # Stage failed (unrecoverable)
    COMPLETED_WITH_ERRORS = "completed_with_errors"  # Some tasks failed but stage continues


class RasterType(str, Enum):
    """
    Raster data types for automatic detection and optimization.

    Used to automatically select optimal COG compression and resampling
    settings based on the type of raster data being processed.

    Type Detection Criteria:
    - RGB: 3 bands, uint8/uint16 (drone imagery, aerial photos)
    - RGBA: 4 bands, uint8/uint16 with alpha channel (drone imagery with transparency)
    - DEM: Single-band float32/int16 with smooth gradients (elevation data)
    - CATEGORICAL: Single-band with <256 discrete integer values (land cover classification)
    - MULTISPECTRAL: 5+ bands (Landsat, Sentinel-2, Planet satellite imagery)
    - NIR: 4 bands without alpha (RGB + Near-Infrared)
    - UNKNOWN: Cannot determine type automatically
    """

    RGB = "rgb"
    RGBA = "rgba"
    DEM = "dem"
    CATEGORICAL = "categorical"
    MULTISPECTRAL = "multispectral"
    NIR = "nir"
    UNKNOWN = "unknown"