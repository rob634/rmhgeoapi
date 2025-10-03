# ============================================================================
# CLAUDE CONTEXT - CORE SCHEMA
# ============================================================================
# CATEGORY: SCHEMAS - DATA VALIDATION & TRANSFORMATION
# PURPOSE: Pydantic models for validation, serialization, and data flow
# EPOCH: Shared by all epochs (not persisted to database)# PURPOSE: Formal schemas for dynamic orchestration pattern in Job→Stage→Task workflow (both pipelines)
# EXPORTS: OrchestrationInstruction, DynamicOrchestrationResult, OrchestrationItem, FileOrchestrationItem
# INTERFACES: None - pure data models
# PYDANTIC_MODELS: All classes in this file are Pydantic v2 models
# DEPENDENCIES: pydantic, typing, enum, datetime
# SOURCE: Stage 1 task results that need to orchestrate Stage 2+ tasks
# SCOPE: Used by both Storage Queue and Service Bus controllers for dynamic task generation
# VALIDATION: Pydantic automatic validation with custom validators
# PATTERNS: Data Transfer Objects for orchestration communication, Dynamic fan-out pattern
# ENTRY_POINTS: Import and use in controller aggregate_stage_results methods (both pipelines)
# LOCATION: core/schema/ - Core architecture schema (copied from root schema_orchestration.py)
# ============================================================================

"""
Universal Dynamic Orchestration Schemas - Dual Pipeline Support

Formal data models for the "Analyze & Orchestrate" pattern where Stage 1
analyzes content and dynamically determines what Stage 2+ tasks to create.
Used by BOTH Azure Storage Queue and Service Bus pipeline controllers.

This pattern is used when:
1. The number of tasks is not known until runtime
2. Task parameters depend on analyzed content
3. Stage 2 might be skipped based on Stage 1 findings
4. Dynamic fan-out is needed after content discovery

Supports both pipelines:
- Storage Queue: controller_container.py uses full orchestration
- Service Bus: controller_service_bus_container.py uses FileOrchestrationItem

Author: Robert and Geospatial Claude Legion
Date: 30 SEP 2025 (Copied to core/schema/)
"""

from typing import Dict, List, Any, Optional, Union, Literal
from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, ConfigDict


# ============================================================================
# ENUMS
# ============================================================================

class OrchestrationAction(str, Enum):
    """
    Actions that Stage 1 can instruct for subsequent processing.
    """
    CREATE_TASKS = "create_tasks"      # Normal: create Stage 2 tasks
    COMPLETE_JOB = "complete_job"      # Complete job early (no more stages needed)
    FAIL_JOB = "fail_job"              # Fail the job with reason
    RETRY_STAGE = "retry_stage"        # Retry Stage 1 (rare)


class ItemType(str, Enum):
    """
    Types of items that can be orchestrated.
    """
    FILE = "file"                      # Blob storage file
    RECORD = "record"                  # Database record
    TILE = "tile"                      # Spatial tile
    CHUNK = "chunk"                    # Data chunk
    GENERIC = "generic"                # Generic work item


# ============================================================================
# ORCHESTRATION ITEM MODEL
# ============================================================================

class OrchestrationItem(BaseModel):
    """
    A single item to be processed in Stage 2.

    This is the base unit of work that Stage 1 identifies for Stage 2 processing.
    Each item will typically become one task in Stage 2.

    Examples:
        - A file in blob storage
        - A database record to process
        - A spatial tile to analyze
        - A chunk of data to transform
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        use_enum_values=True,
        populate_by_name=True
    )

    # Required fields
    item_id: str = Field(
        ...,
        description="Unique identifier for this item (e.g., file path, record ID)"
    )

    item_type: ItemType = Field(
        default=ItemType.GENERIC,
        description="Type of item for routing to appropriate handler"
    )

    # Optional fields with common metadata
    name: Optional[str] = Field(
        default=None,
        description="Human-readable name"
    )

    size: Optional[int] = Field(
        default=None,
        description="Size in bytes if applicable",
        ge=0
    )

    location: Optional[str] = Field(
        default=None,
        description="Location (path, URL, coordinates)"
    )

    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Item-specific metadata"
    )

    # Processing hints
    priority: int = Field(
        default=0,
        description="Processing priority (higher = more important)",
        ge=0,
        le=100
    )

    estimated_duration_seconds: Optional[float] = Field(
        default=None,
        description="Estimated processing time",
        gt=0
    )

    @field_validator('item_id')
    @classmethod
    def validate_item_id(cls, v: str) -> str:
        """Ensure item_id is not empty."""
        if not v or not v.strip():
            raise ValueError("item_id cannot be empty")
        return v.strip()


# ============================================================================
# ORCHESTRATION INSTRUCTION MODEL
# ============================================================================

class OrchestrationInstruction(BaseModel):
    """
    Instructions from Stage 1 to the orchestrator about Stage 2.

    This is the contract between Stage 1 and the orchestration system.
    Stage 1 analyzes content and returns this instruction set.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        use_enum_values=True,
        arbitrary_types_allowed=True
    )

    # Required action
    action: OrchestrationAction = Field(
        ...,
        description="What action to take for Stage 2"
    )

    # Items to process (only required for CREATE_TASKS)
    # Using Union to preserve subclass fields during serialization
    items: List[Union['FileOrchestrationItem', OrchestrationItem]] = Field(
        default_factory=list,
        description="Items to create tasks for in Stage 2"
    )

    # Metadata about the orchestration
    total_items: int = Field(
        default=0,
        description="Total items found (might be > len(items) if limited)",
        ge=0
    )

    items_filtered: int = Field(
        default=0,
        description="Number of items filtered out",
        ge=0
    )

    items_included: int = Field(
        default=0,
        description="Number of items included for processing",
        ge=0
    )

    # Control parameters
    max_parallel_tasks: Optional[int] = Field(
        default=None,
        description="Override max parallel tasks for Stage 2",
        gt=0,
        le=1000
    )

    batch_size: Optional[int] = Field(
        default=None,
        description="Batch items into groups of this size",
        gt=0
    )

    # Reason/explanation (especially for non-CREATE_TASKS actions)
    reason: Optional[str] = Field(
        default=None,
        description="Explanation for the action (required for SKIP/FAIL)"
    )

    # Stage 2 configuration
    stage_2_parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional parameters to pass to all Stage 2 tasks"
    )

    # Orchestration metadata
    orchestration_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata about the orchestration process"
    )

    @field_validator('items')
    @classmethod
    def validate_items_for_action(cls, v: List[OrchestrationItem], info) -> List[OrchestrationItem]:
        """Validate items based on action."""
        action = info.data.get('action')
        if action == OrchestrationAction.CREATE_TASKS and not v:
            raise ValueError("items cannot be empty when action is CREATE_TASKS")
        return v

    @field_validator('reason')
    @classmethod
    def validate_reason_for_action(cls, v: Optional[str], info) -> Optional[str]:
        """Require reason for certain actions."""
        action = info.data.get('action')
        if action in [OrchestrationAction.COMPLETE_JOB, OrchestrationAction.FAIL_JOB] and not v:
            raise ValueError(f"reason is required when action is {action}")
        return v

    def should_create_tasks(self) -> bool:
        """Check if tasks should be created."""
        return self.action == OrchestrationAction.CREATE_TASKS and len(self.items) > 0

    def get_task_count(self) -> int:
        """Get the number of tasks that will be created."""
        if self.batch_size and self.batch_size > 1:
            # Items will be batched
            import math
            return math.ceil(len(self.items) / self.batch_size)
        return len(self.items)


# ============================================================================
# DYNAMIC ORCHESTRATION RESULT MODEL
# ============================================================================

class DynamicOrchestrationResult(BaseModel):
    """
    Complete Stage 1 result when using dynamic orchestration.

    This wraps both the orchestration instructions and Stage 1's own results,
    providing a complete picture of what Stage 1 discovered and what should happen next.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        use_enum_values=True
    )

    # Orchestration instructions (required)
    orchestration: OrchestrationInstruction = Field(
        ...,
        description="Instructions for Stage 2 task creation"
    )

    # Stage 1 analysis results
    analysis_summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="Summary of Stage 1 analysis"
    )

    # Statistics
    statistics: Dict[str, Union[int, float]] = Field(
        default_factory=dict,
        description="Numeric statistics from analysis"
    )

    # Discovered metadata
    discovered_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata discovered during analysis"
    )

    # Timing information
    analysis_duration_seconds: Optional[float] = Field(
        default=None,
        description="Time taken for Stage 1 analysis",
        gt=0
    )

    analysis_timestamp: datetime = Field(
        default_factory=lambda: datetime.utcnow(),
        description="When analysis was performed"
    )

    # Warnings or issues found
    warnings: List[str] = Field(
        default_factory=list,
        description="Non-fatal warnings from analysis"
    )

    def to_stage_result(self) -> Dict[str, Any]:
        """
        Convert to format expected by aggregate_stage_results.

        Returns:
            Dict suitable for storing in job.stage_results
        """
        return {
            "orchestration": self.orchestration.model_dump(),
            "analysis_summary": self.analysis_summary,
            "statistics": self.statistics,
            "discovered_metadata": self.discovered_metadata,
            "warnings": self.warnings,
            "analysis_timestamp": self.analysis_timestamp.isoformat()
        }


# ============================================================================
# HELPER MODELS FOR SPECIFIC PATTERNS
# ============================================================================

class FileOrchestrationItem(OrchestrationItem):
    """
    Specialized orchestration item for files in blob storage.
    """

    item_type: Literal[ItemType.FILE] = Field(
        default=ItemType.FILE
    )

    container: str = Field(
        ...,
        description="Blob storage container name"
    )

    path: str = Field(
        ...,
        description="File path within container"
    )

    content_type: Optional[str] = Field(
        default=None,
        description="MIME type"
    )

    last_modified: Optional[datetime] = Field(
        default=None,
        description="Last modification time"
    )

    etag: Optional[str] = Field(
        default=None,
        description="Entity tag for caching"
    )


class TileOrchestrationItem(OrchestrationItem):
    """
    Specialized orchestration item for spatial tiles.
    """

    item_type: Literal[ItemType.TILE] = Field(
        default=ItemType.TILE
    )

    x: int = Field(
        ...,
        description="Tile X coordinate"
    )

    y: int = Field(
        ...,
        description="Tile Y coordinate"
    )

    z: int = Field(
        ...,
        description="Zoom level"
    )

    bbox: Optional[List[float]] = Field(
        default=None,
        description="Bounding box [minx, miny, maxx, maxy]",
        min_length=4,
        max_length=4
    )


class ChunkOrchestrationItem(OrchestrationItem):
    """
    Specialized orchestration item for data chunks.
    """

    item_type: Literal[ItemType.CHUNK] = Field(
        default=ItemType.CHUNK
    )

    chunk_index: int = Field(
        ...,
        description="Zero-based chunk index",
        ge=0
    )

    start_offset: int = Field(
        ...,
        description="Starting byte/record offset",
        ge=0
    )

    end_offset: int = Field(
        ...,
        description="Ending byte/record offset",
        gt=0
    )

    total_chunks: Optional[int] = Field(
        default=None,
        description="Total number of chunks",
        gt=0
    )


# ============================================================================
# VALIDATION HELPERS
# ============================================================================

def create_item_id(container: str, path: str) -> str:
    """
    Create deterministic item ID from container and path.

    Uses SHA256 hash to create a unique, deterministic identifier
    that clearly separates identity from location.

    Args:
        container: Blob container name
        path: File path within container

    Returns:
        16-character hex hash identifier
    """
    import hashlib
    content = f"{container}:{path}".encode('utf-8')
    return hashlib.sha256(content).hexdigest()[:16]


def create_file_orchestration_items(
    files: List[Dict[str, Any]],
    container: str
) -> List[FileOrchestrationItem]:
    """
    Helper to create file orchestration items from blob listing.

    Args:
        files: List of file dictionaries from blob storage
        container: Container name

    Returns:
        List of FileOrchestrationItem objects
    """
    items = []
    for file_info in files:
        item = FileOrchestrationItem(
            item_id=create_item_id(container, file_info['path']),  # Deterministic hash
            container=container,
            path=file_info['path'],  # Actual file path
            name=file_info.get('name', file_info['path'].split('/')[-1]),
            size=file_info.get('size'),
            content_type=file_info.get('content_type'),
            last_modified=file_info.get('last_modified'),
            etag=file_info.get('etag'),
            metadata=file_info.get('metadata', {})
        )
        items.append(item)
    return items


def create_orchestration_instruction(
    items: List[Union[OrchestrationItem, Dict[str, Any]]],
    action: OrchestrationAction = OrchestrationAction.CREATE_TASKS,
    stage_2_parameters: Optional[Dict[str, Any]] = None,
    **kwargs
) -> OrchestrationInstruction:
    """
    Helper to create orchestration instruction with validation.

    Args:
        items: List of items (can be dicts or OrchestrationItem objects)
        action: What action to take
        stage_2_parameters: Parameters for Stage 2 tasks
        **kwargs: Additional fields for OrchestrationInstruction

    Returns:
        OrchestrationInstruction object
    """
    # Convert dict items to OrchestrationItem objects
    orchestration_items = []
    for item in items:
        if isinstance(item, dict):
            orchestration_items.append(OrchestrationItem(**item))
        else:
            orchestration_items.append(item)

    return OrchestrationInstruction(
        action=action,
        items=orchestration_items,
        total_items=kwargs.get('total_items', len(orchestration_items)),
        items_included=len(orchestration_items),
        stage_2_parameters=stage_2_parameters or {},
        **{k: v for k, v in kwargs.items() if k not in ['total_items']}
    )


# Export all public classes and functions
__all__ = [
    'OrchestrationAction',
    'ItemType',
    'OrchestrationItem',
    'OrchestrationInstruction',
    'DynamicOrchestrationResult',
    'FileOrchestrationItem',
    'TileOrchestrationItem',
    'ChunkOrchestrationItem',
    'create_item_id',
    'create_file_orchestration_items',
    'create_orchestration_instruction'
]