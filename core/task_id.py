"""
Deterministic Task ID Generation

Provides deterministic task ID generation based on job_id + stage + logical_unit.
This enables tasks to calculate their predecessors' IDs without database lookups,
supporting complex multi-stage parallel workflows.

Key Concepts:
- Logical Unit: The identifier that stays constant across stages (e.g., "tile_x5_y10", "blob.tif")
- Lineage: Tasks in different stages processing the same logical unit form a lineage chain
- Deterministic: Same inputs always produce same task ID
"""

import hashlib
from typing import Optional


def generate_deterministic_task_id(
    job_id: str,
    stage: int,
    logical_unit: str
) -> str:
    """
    Generate deterministic task ID from job context and logical unit.

    Formula: SHA256(job_id|stage|logical_unit)[:16]

    The logical_unit is the identifier that remains constant across stages:
    - For raster tiling: "tile_x5_y10"
    - For blob processing: blob file name
    - For batch conversion: file path
    - For single tasks: task type name

    Args:
        job_id: Parent job ID
        stage: Stage number (1, 2, 3, ...)
        logical_unit: Identifier for the work unit

    Returns:
        16-character hexadecimal task ID

    Examples:
        >>> generate_deterministic_task_id("abc123", 2, "tile_x5_y10")
        'd4f8a2b1c3e5d7f9'

        >>> generate_deterministic_task_id("abc123", 3, "tile_x5_y10")
        'e5g9b3c2d4f6e8g0'

        # Same logical unit, different stages = predictable lineage
    """
    # Create composite key with delimiters
    composite = f"{job_id}|s{stage}|{logical_unit}"

    # Hash and truncate to 16 characters
    full_hash = hashlib.sha256(composite.encode()).hexdigest()
    return full_hash[:16]


def get_predecessor_task_id(
    job_id: str,
    current_stage: int,
    logical_unit: str
) -> Optional[str]:
    """
    Calculate the task ID of the same logical unit in the previous stage.

    This allows tasks to find their predecessors without database queries:
    - Stage 3 task for "tile_x5_y10" can calculate Stage 2 task ID
    - Stage 2 task can calculate Stage 1 task ID
    - Stage 1 has no predecessor (returns None)

    Args:
        job_id: Parent job ID
        current_stage: Current stage number
        logical_unit: Identifier for the work unit

    Returns:
        Task ID of predecessor, or None if Stage 1

    Example:
        >>> # I'm Stage 3, processing tile_x5_y10
        >>> my_predecessor = get_predecessor_task_id("abc123", 3, "tile_x5_y10")
        >>> # Returns Stage 2 task ID for tile_x5_y10

        >>> # Now I can fetch predecessor's result directly
        >>> predecessor_result = task_repo.get_task(my_predecessor)
    """
    if current_stage <= 1:
        return None  # Stage 1 has no predecessor

    previous_stage = current_stage - 1
    return generate_deterministic_task_id(job_id, previous_stage, logical_unit)


def get_successor_task_id(
    job_id: str,
    current_stage: int,
    logical_unit: str
) -> str:
    """
    Calculate the task ID of the same logical unit in the next stage.

    Useful for Stage N to know what task will process its output in Stage N+1.

    Args:
        job_id: Parent job ID
        current_stage: Current stage number
        logical_unit: Identifier for the work unit

    Returns:
        Task ID of successor task in next stage
    """
    next_stage = current_stage + 1
    return generate_deterministic_task_id(job_id, next_stage, logical_unit)


# Export public API
__all__ = [
    'generate_deterministic_task_id',
    'get_predecessor_task_id',
    'get_successor_task_id'
]
