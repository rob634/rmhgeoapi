# ============================================================================
# PURE ENUMERATION TYPES
# ============================================================================
# STATUS: Core - Type definitions without business logic
# PURPOSE: Job, Task, and Stage status enums plus RasterType/ColorRamp classification
# LAST_REVIEWED: 12 FEB 2026
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
    ColorRamp: Curated TiTiler colormaps for raster visualization
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

    Used to automatically select optimal COG compression, resampling,
    and default colormap based on the type of raster data being processed.

    Physical Types (auto-detectable from file characteristics):
    - RGB: 3 bands, uint8/uint16 (drone imagery, aerial photos)
    - RGBA: 4 bands, uint8/uint16 with alpha channel (drone imagery with transparency)
    - DEM: Single-band float32/int16 with smooth gradients (elevation data)
    - CATEGORICAL: Single-band with <256 discrete integer values (land cover classification)
    - MULTISPECTRAL: 5+ bands (Landsat, Sentinel-2, Planet satellite imagery)
    - NIR: 4 bands without alpha (RGB + Near-Infrared)
    - CONTINUOUS: Single-band numeric, non-smooth (generic continuous data)
    - VEGETATION_INDEX: Single-band float in [-1, 1] range (NDVI, EVI, etc.)

    Domain Types (user-specified, refine physical detection):
    - FLOOD_DEPTH: Flood depth/extent models (compatible with dem/continuous)
    - FLOOD_PROBABILITY: Flood probability surfaces (compatible with dem/continuous)
    - HYDROLOGY: Flow accumulation, drainage, watershed (compatible with dem/continuous)
    - TEMPORAL: Each pixel = time period, e.g. deforestation year (compatible with dem/continuous/categorical)
    - POPULATION: Population density, count grids (compatible with dem/continuous)

    Fallback:
    - UNKNOWN: Cannot determine type automatically

    12 FEB 2026: Expanded from 7 to 15 types. Domain types use hierarchical
    compatibility validation (see COMPATIBLE_OVERRIDES in raster_validation.py).
    """

    # Physical types (auto-detectable)
    RGB = "rgb"
    RGBA = "rgba"
    DEM = "dem"
    CATEGORICAL = "categorical"
    MULTISPECTRAL = "multispectral"
    NIR = "nir"
    CONTINUOUS = "continuous"
    VEGETATION_INDEX = "vegetation_index"

    # Domain types (user-specified, refine physical detection)
    FLOOD_DEPTH = "flood_depth"
    FLOOD_PROBABILITY = "flood_probability"
    HYDROLOGY = "hydrology"
    TEMPORAL = "temporal"
    POPULATION = "population"

    # Fallback
    UNKNOWN = "unknown"


class ColorRamp(str, Enum):
    """
    Curated TiTiler colormaps for raster visualization.

    All values are valid colormap_name parameters for TiTiler tile endpoints.
    Users can submit a ColorRamp value as the 'default_ramp' job parameter
    to override the type-based default colormap.

    Organized by use case:
    - Sequential: General-purpose perceptual colormaps
    - Terrain: Elevation and topographic data
    - Water: Hydrology, flood, precipitation
    - Heat: Temperature, intensity, density
    - Vegetation: Diverging colormaps for vegetation indices
    - Classification: Discrete/categorical data
    - Specialized: Domain-specific applications

    12 FEB 2026: Created for default_ramp job parameter validation.
    """

    # Perceptual sequential (general purpose)
    VIRIDIS = "viridis"
    PLASMA = "plasma"
    INFERNO = "inferno"
    MAGMA = "magma"
    CIVIDIS = "cividis"

    # Terrain / elevation
    TERRAIN = "terrain"
    GIST_EARTH = "gist_earth"

    # Water / hydrology
    BLUES = "blues"
    PUBU = "pubu"
    YLGNBU = "ylgnbu"

    # Temperature / heat
    COOLWARM = "coolwarm"
    RDYLBU = "rdylbu"
    REDS = "reds"
    ORANGES = "oranges"
    YLORRD = "ylorrd"

    # Vegetation / diverging
    RDYLGN = "rdylgn"
    PIYG = "piyg"
    BRBG = "brbg"
    PRGN = "prgn"

    # Classification / discrete
    SPECTRAL = "spectral"
    GREYS = "greys"
    GREENS = "greens"
    PURPLES = "purples"

    # Specialized
    SEISMIC = "seismic"
    BWR = "bwr"
    GNBU = "gnbu"
    ORRD = "orrd"
    YLORBR = "ylorbr"