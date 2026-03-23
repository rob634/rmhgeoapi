# ============================================================================
# CLAUDE CONTEXT - SCHEDULED DATASET MODEL
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Pydantic model for schedule-managed PostGIS tables
# PURPOSE: Tracks API-sourced datasets that are appended/rebuilt by scheduled
#          workflows. Separate lifecycle from static ETL release model.
# LAST_REVIEWED: 21 MAR 2026
# EXPORTS: ScheduledDataset
# DEPENDENCIES: pydantic, datetime
# ============================================================================
"""
ScheduledDataset — tracks a PostGIS table managed by a scheduled workflow.

Unlike static ETL assets (immutable, versioned, release lifecycle), scheduled
datasets are mutable (append/truncate), unversioned, and fully automated.

Table: app.scheduled_datasets
Primary Key: dataset_id
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, ClassVar
from pydantic import BaseModel, Field, ConfigDict, field_serializer


class ScheduledDataset(BaseModel):
    """
    A PostGIS table managed by a scheduled workflow.

    Lifecycle: schedule fires → workflow appends/rebuilds → entity updated.
    No approval gate, no versioning, no release model.
    """
    model_config = ConfigDict(extra='ignore', str_strip_whitespace=True)

    @field_serializer('created_at', 'updated_at', 'last_sync_at')
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

    # =========================================================================
    # DDL GENERATION HINTS (ClassVar = not a model field)
    # =========================================================================
    __sql_table_name: ClassVar[str] = "scheduled_datasets"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["dataset_id"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {}
    __sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["table_schema", "table_name"], "name": "uq_scheduled_datasets_table"},
    ]
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["schedule_id"], "name": "idx_scheduled_datasets_schedule",
         "partial_where": "schedule_id IS NOT NULL"},
    ]

    # =========================================================================
    # IDENTITY
    # =========================================================================
    dataset_id: str = Field(
        ...,
        max_length=64,
        description="Unique dataset identifier",
    )
    table_name: str = Field(
        ...,
        max_length=100,
        description="PostGIS table name managed by this dataset",
    )
    table_schema: str = Field(
        default="geo",
        max_length=50,
        description="PostgreSQL schema containing the table",
    )

    # =========================================================================
    # SCHEDULE LINK
    # =========================================================================
    schedule_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="FK to app.schedules (nullable for manually-managed datasets)",
    )

    # =========================================================================
    # METADATA
    # =========================================================================
    description: Optional[str] = Field(
        default=None,
        description="Human-readable description of the dataset",
    )
    source_type: str = Field(
        default="api",
        max_length=50,
        description="Data source type: api, feed, etc.",
    )
    column_schema: Dict[str, Any] = Field(
        default_factory=dict,
        description="Expected columns and types (JSONB) for table creation and validation",
    )
    rebuild_strategy: str = Field(
        default="append",
        max_length=20,
        description="How sync updates the table: append | truncate_reload",
    )
    credential_key: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Key Vault credential group name (e.g. 'acled'). "
                    "Resolves to secrets via KeyVaultRepository.resolve_credentials().",
    )

    # =========================================================================
    # SYNC STATE
    # =========================================================================
    row_count: int = Field(
        default=0,
        ge=0,
        description="Current row count (updated after each sync)",
    )
    last_sync_at: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp of most recent successful sync",
    )
    last_sync_run_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="run_id of the most recent sync workflow run",
    )

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the dataset was registered",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of most recent update",
    )
