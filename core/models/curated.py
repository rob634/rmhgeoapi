# ============================================================================
# CURATED DATASET MODELS
# ============================================================================
# STATUS: Core - System-managed geospatial data models
# PURPOSE: Registry and audit models for auto-updating curated datasets
# LAST_REVIEWED: 03 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Curated Dataset Models.

Pydantic models for curated dataset management. Curated datasets are
system-managed geospatial data that updates automatically from external
sources (unlike user-submitted data).

Tables:
    app.curated_datasets - Registry of curated datasets
    app.curated_update_log - History of update operations

Exports:
    CuratedDataset: Registry record for a curated dataset
    CuratedUpdateLog: Audit record for update operations
    CuratedSourceType: Types of data sources (api_bulk_download, manual, etc.)
    CuratedUpdateStrategy: Update strategies (full_replace, upsert)
    CuratedUpdateType: Types of update triggers (scheduled, manual, triggered)
    CuratedUpdateStatus: Status of an update operation
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, field_validator


class CuratedSourceType(str, Enum):
    """Types of curated data sources."""
    API_BULK_DOWNLOAD = "api_bulk_download"  # Download full file from API
    API_PAGINATED = "api_paginated"          # Page through API results
    MANUAL = "manual"                         # Manually triggered only


class CuratedUpdateStrategy(str, Enum):
    """Strategies for updating curated data."""
    FULL_REPLACE = "full_replace"  # TRUNCATE + INSERT (WDPA, admin0)
    UPSERT = "upsert"              # INSERT ON CONFLICT UPDATE


class CuratedUpdateType(str, Enum):
    """Types of update triggers."""
    SCHEDULED = "scheduled"   # Triggered by daily scheduler
    MANUAL = "manual"         # Triggered by HTTP endpoint
    TRIGGERED = "triggered"   # Triggered by external webhook


class CuratedUpdateStatus(str, Enum):
    """Status of an update operation."""
    STARTED = "started"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"  # No update needed (source unchanged)


class CuratedDataset(BaseModel):
    """
    Registry record for a curated dataset.

    Curated datasets are system-managed geospatial data that:
    - Cannot be deleted/modified via normal API
    - Update on a schedule (or manually triggered)
    - Use 'curated_' table prefix for protection
    - Track update history and source versions

    Table: app.curated_datasets
    Primary Key: dataset_id

    Examples:
        # WDPA - World Database on Protected Areas
        CuratedDataset(
            dataset_id="wdpa",
            name="World Database on Protected Areas",
            source_type=CuratedSourceType.API_BULK_DOWNLOAD,
            source_url="https://api.ibat-alliance.org/v1/data-downloads",
            job_type="curated_wdpa_update",
            update_strategy=CuratedUpdateStrategy.FULL_REPLACE,
            update_schedule="0 0 1 * *",  # Monthly
            target_table_name="curated_wdpa_protected_areas"
        )

        # Admin0 - Country boundaries (manual update)
        CuratedDataset(
            dataset_id="admin0",
            name="Admin0 Country Boundaries",
            source_type=CuratedSourceType.MANUAL,
            source_url="https://www.naturalearthdata.com/",
            job_type="curated_admin0_update",
            update_strategy=CuratedUpdateStrategy.FULL_REPLACE,
            update_schedule=None,  # Manual only
            target_table_name="curated_admin0"
        )
    """

    model_config = ConfigDict(
        json_encoders={datetime: lambda v: v.isoformat()}
    )

    # Identity
    dataset_id: str = Field(
        ...,
        max_length=64,
        description="Unique identifier (slug format, e.g., 'wdpa', 'admin0')"
    )
    name: str = Field(
        ...,
        max_length=100,
        description="Display name (e.g., 'World Database on Protected Areas')"
    )
    description: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Detailed description of the dataset"
    )

    # Source Configuration
    source_type: CuratedSourceType = Field(
        ...,
        description="How data is fetched (api_bulk_download, api_paginated, manual)"
    )
    source_url: str = Field(
        ...,
        max_length=500,
        description="Base API URL or download endpoint"
    )
    source_config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Source-specific config (auth params, pagination, format)"
    )

    # Pipeline Configuration
    job_type: str = Field(
        ...,
        max_length=50,
        description="Job type to submit (e.g., 'curated_wdpa_update')"
    )
    update_strategy: CuratedUpdateStrategy = Field(
        ...,
        description="How to update data (full_replace or upsert)"
    )
    update_schedule: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Cron expression (e.g., '0 0 1 * *' for monthly). None = manual only."
    )

    # Credentials (environment variable name or Key Vault reference)
    credential_key: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Environment variable or Key Vault secret name for credentials"
    )

    # Target Configuration
    target_table_name: str = Field(
        ...,
        max_length=255,
        description="PostGIS table name (MUST start with 'curated_')"
    )
    target_schema: str = Field(
        default="geo",
        max_length=50,
        description="PostgreSQL schema for the target table"
    )

    # Status Tracking
    enabled: bool = Field(
        default=True,
        description="Whether scheduled updates are enabled"
    )
    last_checked_at: Optional[datetime] = Field(
        default=None,
        description="When source was last checked for updates"
    )
    last_updated_at: Optional[datetime] = Field(
        default=None,
        description="When data was last successfully updated"
    )
    last_job_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Job ID of last update attempt"
    )
    source_version: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Version/hash from source API (for change detection)"
    )

    # Audit
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this registry entry was created"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this registry entry was last modified"
    )

    @field_validator('target_table_name')
    @classmethod
    def validate_curated_prefix(cls, v: str) -> str:
        """Ensure target table has curated_ prefix."""
        if not v.startswith('curated_'):
            raise ValueError(
                f"target_table_name must start with 'curated_', got: {v}"
            )
        return v


class CuratedUpdateLog(BaseModel):
    """
    Audit record for a curated dataset update operation.

    Records each update attempt with timing, record counts, and status.
    Used for monitoring, debugging, and auditing curated dataset updates.

    Table: app.curated_update_log
    Primary Key: log_id (auto-generated)

    Example:
        CuratedUpdateLog(
            dataset_id="wdpa",
            job_id="abc123...",
            update_type=CuratedUpdateType.SCHEDULED,
            source_version="2024-12",
            records_total=250000,
            status=CuratedUpdateStatus.COMPLETED,
            duration_seconds=1234.5
        )
    """

    model_config = ConfigDict(
        json_encoders={datetime: lambda v: v.isoformat()}
    )

    # Primary key (auto-generated by database)
    log_id: Optional[int] = Field(
        default=None,
        description="Auto-generated log entry ID"
    )

    # Foreign keys
    dataset_id: str = Field(
        ...,
        max_length=64,
        description="Reference to curated_datasets.dataset_id"
    )
    job_id: str = Field(
        ...,
        max_length=64,
        description="CoreMachine job ID that performed the update"
    )

    # Update Details
    update_type: CuratedUpdateType = Field(
        ...,
        description="What triggered the update (scheduled, manual, triggered)"
    )
    source_version: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Version from source API"
    )

    # Record Counts
    records_added: int = Field(
        default=0,
        ge=0,
        description="Number of new records inserted"
    )
    records_updated: int = Field(
        default=0,
        ge=0,
        description="Number of existing records updated"
    )
    records_deleted: int = Field(
        default=0,
        ge=0,
        description="Number of records removed"
    )
    records_total: int = Field(
        default=0,
        ge=0,
        description="Total records in table after update"
    )

    # Status
    status: CuratedUpdateStatus = Field(
        default=CuratedUpdateStatus.STARTED,
        description="Current status of the update operation"
    )
    error_message: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Error message if update failed"
    )

    # Timing
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the update started"
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="When the update completed (success or failure)"
    )
    duration_seconds: Optional[float] = Field(
        default=None,
        ge=0,
        description="Total duration in seconds"
    )


# Module exports
__all__ = [
    'CuratedDataset',
    'CuratedUpdateLog',
    'CuratedSourceType',
    'CuratedUpdateStrategy',
    'CuratedUpdateType',
    'CuratedUpdateStatus'
]
