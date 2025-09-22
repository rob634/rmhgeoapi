# ============================================================================
# CLAUDE CONTEXT - SCHEMA
# ============================================================================
# PURPOSE: Pydantic models for blob storage operations and metadata
# EXPORTS: BlobMetadata, ContainerInventory, ContainerSummary, FileFilter
# INTERFACES: None - pure data models
# PYDANTIC_MODELS: BlobMetadata, ContainerInventory, ContainerSummary, FileFilter, OrchestrationData
# DEPENDENCIES: pydantic, typing, datetime, enum
# SOURCE: Azure Blob Storage metadata and properties
# SCOPE: Blob storage operations, container analysis, file metadata
# VALIDATION: Pydantic v2 field validators for size limits and naming conventions
# PATTERNS: Data model pattern, Builder pattern for metadata extraction
# ENTRY_POINTS: from schema_blob import BlobMetadata, ContainerInventory
# INDEX: BlobMetadata:60, ContainerInventory:130, ContainerSummary:180, OrchestrationData:250
# ============================================================================

"""
Blob Storage Schemas - Data Models for Storage Operations

This module defines Pydantic models for blob storage operations,
including metadata extraction, container inventory, and orchestration data.

Key Models:
- BlobMetadata: Individual blob/file metadata
- ContainerInventory: Full container listing with statistics
- ContainerSummary: Aggregated container statistics
- OrchestrationData: Stage 1 analysis results for dynamic task generation

Design Principles:
- Strongly typed with Pydantic v2
- Validation for Azure naming conventions
- Support for both basic and extended metadata
- Efficient serialization for task results

Author: Robert and Geospatial Claude Legion
Date: 9 December 2025
"""

# ============================================================================
# IMPORTS - Top of file for fail-fast behavior
# ============================================================================

# Standard library imports
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, List

# Third-party imports - Will fail fast if Pydantic not installed
from pydantic import BaseModel, Field, field_validator, ConfigDict

# Application imports - Orchestration schemas
from schema_orchestration import (
    OrchestrationInstruction,
    OrchestrationAction,
    FileOrchestrationItem
)


# ============================================================================
# ENUMS
# ============================================================================

class FileSizeCategory(str, Enum):
    """Categorization of file sizes for analysis"""
    TINY = "tiny"           # < 1MB
    SMALL = "small"         # 1MB - 10MB
    MEDIUM = "medium"       # 10MB - 100MB
    LARGE = "large"         # 100MB - 1GB
    HUGE = "huge"           # > 1GB


class MetadataLevel(str, Enum):
    """Level of metadata extraction"""
    BASIC = "basic"         # Just size, name, modified date
    STANDARD = "standard"   # Basic + content type, etag
    FULL = "full"           # Standard + custom metadata, properties


# ============================================================================
# BLOB METADATA MODELS
# ============================================================================

class BlobMetadata(BaseModel):
    """
    Metadata for a single blob/file.
    
    This model captures all relevant metadata for a blob,
    used as the result data for extract_metadata tasks.
    """
    # Basic properties
    name: str = Field(..., description="Full blob path including folders")
    size: int = Field(..., ge=0, description="Size in bytes")
    last_modified: datetime = Field(..., description="Last modification timestamp")
    
    # Standard properties
    content_type: Optional[str] = Field(None, description="MIME type of the blob")
    etag: Optional[str] = Field(None, description="Entity tag for versioning")
    
    # Extended properties
    metadata: Dict[str, str] = Field(default_factory=dict, description="Custom metadata tags")
    
    # Computed properties
    size_category: Optional[FileSizeCategory] = Field(None, description="Size categorization")
    extension: Optional[str] = Field(None, description="File extension")
    folder_path: Optional[str] = Field(None, description="Parent folder path")
    
    @field_validator('name')
    @classmethod
    def validate_blob_name(cls, v: str) -> str:
        """Validate Azure blob naming conventions"""
        if not v or len(v) > 1024:
            raise ValueError(f"Blob name must be 1-1024 characters, got {len(v) if v else 0}")
        return v
    
    @field_validator('size_category', mode='before')
    @classmethod
    def compute_size_category(cls, v: Any, info) -> Optional[FileSizeCategory]:
        """Auto-compute size category from size"""
        if v is not None:
            return v
            
        size = info.data.get('size', 0)
        if size < 1024 * 1024:  # < 1MB
            return FileSizeCategory.TINY
        elif size < 10 * 1024 * 1024:  # < 10MB
            return FileSizeCategory.SMALL
        elif size < 100 * 1024 * 1024:  # < 100MB
            return FileSizeCategory.MEDIUM
        elif size < 1024 * 1024 * 1024:  # < 1GB
            return FileSizeCategory.LARGE
        else:
            return FileSizeCategory.HUGE
    
    def to_task_result(self) -> Dict[str, Any]:
        """Convert to format suitable for task.result_data"""
        return self.model_dump(mode='json', exclude_none=True)
    
    model_config = ConfigDict(validate_assignment=True)


# ============================================================================
# CONTAINER INVENTORY MODELS
# ============================================================================

class ContainerInventory(BaseModel):
    """
    Complete inventory of a container.
    
    Used for container listing operations and as input
    for orchestration decisions.
    """
    container_name: str = Field(..., description="Name of the container")
    blob_count: int = Field(..., ge=0, description="Total number of blobs")
    total_size: int = Field(..., ge=0, description="Total size in bytes")
    
    # File listings
    blobs: List[BlobMetadata] = Field(default_factory=list, description="List of blob metadata")
    
    # Filtering info
    prefix_filter: Optional[str] = Field(None, description="Prefix filter applied")
    max_files: Optional[int] = Field(None, description="Maximum files limit")
    truncated: bool = Field(False, description="Whether results were truncated")
    
    # Timestamp
    inventory_time: datetime = Field(default_factory=datetime.utcnow, description="When inventory was taken")
    
    def get_size_distribution(self) -> Dict[FileSizeCategory, int]:
        """Get distribution of file sizes"""
        distribution = {cat: 0 for cat in FileSizeCategory}
        for blob in self.blobs:
            if blob.size_category:
                distribution[blob.size_category] += 1
        return distribution
    
    def get_type_distribution(self) -> Dict[str, int]:
        """Get distribution of file types by extension"""
        distribution = {}
        for blob in self.blobs:
            ext = blob.extension or 'no_extension'
            distribution[ext] = distribution.get(ext, 0) + 1
        return distribution
    
    model_config = ConfigDict(validate_assignment=True)


# ============================================================================
# CONTAINER SUMMARY MODELS
# ============================================================================

class ContainerSummary(BaseModel):
    """
    Summary statistics for a container.
    
    Used as the result for summarize_container jobs.
    """
    container_name: str = Field(..., description="Name of the container")
    
    # Basic stats
    file_count: int = Field(..., ge=0, description="Total number of files")
    total_size: int = Field(..., ge=0, description="Total size in bytes")
    
    # Largest file info
    largest_file_name: Optional[str] = Field(None, description="Name of largest file")
    largest_file_size: Optional[int] = Field(None, ge=0, description="Size of largest file")
    
    # Distributions
    size_distribution: Dict[str, int] = Field(
        default_factory=dict,
        description="Distribution by size category"
    )
    type_distribution: Dict[str, int] = Field(
        default_factory=dict,
        description="Distribution by file type"
    )
    
    # Metadata
    scan_time: datetime = Field(default_factory=datetime.utcnow, description="When scan was performed")
    prefix_filter: Optional[str] = Field(None, description="Prefix filter applied")
    
    def to_human_readable(self) -> Dict[str, Any]:
        """Convert to human-readable format"""
        return {
            "container": self.container_name,
            "file_count": self.file_count,
            "total_size_mb": round(self.total_size / (1024 * 1024), 2),
            "largest_file": {
                "name": self.largest_file_name,
                "size_mb": round(self.largest_file_size / (1024 * 1024), 2) if self.largest_file_size else 0
            },
            "size_distribution": self.size_distribution,
            "type_distribution": self.type_distribution,
            "scan_time": self.scan_time.isoformat()
        }
    
    model_config = ConfigDict(validate_assignment=True)


# ============================================================================
# ORCHESTRATION MODELS
# ============================================================================

class OrchestrationData(BaseModel):
    """
    Data from Stage 1 orchestration analysis.

    Used to pass information from the analyze_and_orchestrate task
    to the controller for creating Stage 2 tasks.
    """
    # Analysis results
    total_files: int = Field(..., ge=0, description="Total files found")
    files_to_process: int = Field(..., ge=0, description="Files selected for processing")

    # File list for task creation - Now accepts FileOrchestrationItem objects
    files: List[Any] = Field(
        default_factory=list,
        description="List of FileOrchestrationItem objects for task creation"
    )
    
    # Orchestration decisions
    batch_size: Optional[int] = Field(None, description="Recommended batch size for tasks")
    estimated_duration_seconds: Optional[float] = Field(None, description="Estimated total processing time")
    
    # Filtering applied
    filter_applied: Optional[str] = Field(None, description="Filter term applied")
    prefix_applied: Optional[str] = Field(None, description="Prefix filter applied")
    
    # Overflow handling
    overflow_detected: bool = Field(False, description="Whether container exceeded limits")
    overflow_message: Optional[str] = Field(None, description="Message about overflow handling")

    # Processing parameters
    metadata_level: Optional[str] = Field(None, description="Metadata extraction level for Stage 2")
    
    def to_stage_result(self) -> Dict[str, Any]:
        """Convert to format for stage results"""

        # Ensure all files are FileOrchestrationItem objects
        orchestration_items = []
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Processing {len(self.files)} files for orchestration")

        for idx, file_item in enumerate(self.files):
            try:
                if isinstance(file_item, FileOrchestrationItem):
                    # Already a FileOrchestrationItem
                    orchestration_items.append(file_item)
                    logger.debug(f"Item {idx} is FileOrchestrationItem")
                elif hasattr(file_item, 'model_dump'):
                    # It's a Pydantic model, keep as-is
                    orchestration_items.append(file_item)
                    logger.debug(f"Item {idx} is Pydantic model")
                elif isinstance(file_item, dict):
                    # Try to convert dict to FileOrchestrationItem
                    if 'container' in file_item and 'path' in file_item:
                        orchestration_items.append(FileOrchestrationItem(**file_item))
                        logger.debug(f"Item {idx} converted from dict to FileOrchestrationItem")
                    else:
                        logger.warning(f"Item {idx} missing required fields for FileOrchestrationItem: {list(file_item.keys())}")
                        continue
                else:
                    # Try to keep as-is
                    orchestration_items.append(file_item)
                    logger.debug(f"Item {idx} kept as-is (type: {type(file_item)})")
            except Exception as e:
                logger.error(f"Failed to process item {idx}: {e}")
                logger.error(f"Item type: {type(file_item)}, Item: {file_item}")
                continue

        logger.info(f"Successfully processed {len(orchestration_items)} out of {len(self.files)} files")

        # Create proper OrchestrationInstruction with validated items
        if len(orchestration_items) > 0:
            action = OrchestrationAction.CREATE_TASKS
            reason = None
        else:
            action = OrchestrationAction.COMPLETE_JOB
            reason = "No items to process. Completing job early."

        orchestration_instruction = OrchestrationInstruction(
            action=action,
            items=orchestration_items,  # Now guaranteed to be proper OrchestrationItem objects
            total_items=self.total_files,
            items_filtered=0,
            items_included=self.files_to_process,
            batch_size=self.batch_size,
            reason=reason,
            stage_2_parameters={"metadata_level": str(self.metadata_level) if self.metadata_level else "standard"}
        )

        # Return the orchestration instruction in the expected format
        return {
            "orchestration": orchestration_instruction.model_dump(mode='json'),
            "ready_for_stage_2": len(orchestration_items) > 0
        }
    
    model_config = ConfigDict(validate_assignment=True)


# ============================================================================
# FILTER MODELS
# ============================================================================

class FileFilter(BaseModel):
    """
    Filter criteria for blob operations.
    
    Used to specify which files to include/exclude in operations.
    """
    # Basic filters
    prefix: Optional[str] = Field(None, description="Path prefix filter")
    extension: Optional[str] = Field(None, description="File extension filter (e.g., '.tif')")
    pattern: Optional[str] = Field(None, description="Glob pattern or regex")
    
    # Size filters
    min_size: Optional[int] = Field(None, ge=0, description="Minimum file size in bytes")
    max_size: Optional[int] = Field(None, ge=0, description="Maximum file size in bytes")
    
    # Date filters
    modified_after: Optional[datetime] = Field(None, description="Only files modified after this date")
    modified_before: Optional[datetime] = Field(None, description="Only files modified before this date")
    
    # Metadata filters
    metadata_match: Dict[str, str] = Field(
        default_factory=dict,
        description="Custom metadata key-value pairs to match"
    )
    
    def matches(self, blob: BlobMetadata) -> bool:
        """Check if a blob matches this filter"""
        # Prefix check
        if self.prefix and not blob.name.startswith(self.prefix):
            return False
        
        # Extension check
        if self.extension and not blob.name.endswith(self.extension):
            return False
        
        # Size checks
        if self.min_size and blob.size < self.min_size:
            return False
        if self.max_size and blob.size > self.max_size:
            return False
        
        # Date checks
        if self.modified_after and blob.last_modified < self.modified_after:
            return False
        if self.modified_before and blob.last_modified > self.modified_before:
            return False
        
        # Metadata checks
        for key, value in self.metadata_match.items():
            if blob.metadata.get(key) != value:
                return False
        
        return True
    
    model_config = ConfigDict(validate_assignment=True)


# ============================================================================
# CONTAINER OPERATION LIMITS
# ============================================================================

class ContainerSizeLimits(BaseModel):
    """
    Safe operating limits for container operations.
    
    These limits prevent timeout issues in Azure Functions.
    """
    # Conservative limits for different environments
    SAFE_FILE_COUNT: int = Field(1000, description="Safe for all plans (< 30 seconds)")
    STANDARD_FILE_COUNT: int = Field(2500, description="Standard limit (< 90 seconds)")
    MAX_FILE_COUNT: int = Field(5000, description="Maximum for single function (< 3 minutes)")
    
    # Development limits
    DEV_FILE_COUNT: int = Field(500, description="Quick testing limit")
    
    # Hard limit
    HARD_LIMIT: int = Field(5000, description="Absolute maximum - throw error beyond this")
    
    @classmethod
    def get_limit_for_environment(cls, is_production: bool = False) -> int:
        """Get appropriate limit based on environment"""
        limits = cls()
        return limits.STANDARD_FILE_COUNT if is_production else limits.DEV_FILE_COUNT
    
    model_config = ConfigDict(validate_assignment=True)


# Export the main models
__all__ = [
    'BlobMetadata',
    'ContainerInventory', 
    'ContainerSummary',
    'OrchestrationData',
    'FileFilter',
    'FileSizeCategory',
    'MetadataLevel',
    'ContainerSizeLimits'
]