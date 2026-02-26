# ============================================================================
# CLAUDE CONTEXT - RELEASE TABLE JUNCTION
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Data Model - Junction table linking releases to PostGIS tables
# PURPOSE: Single source of truth for Release → table(s) relationship
# LAST_REVIEWED: 26 FEB 2026
# EXPORTS: ReleaseTable
# DEPENDENCIES: pydantic
# ============================================================================

from datetime import datetime, timezone
from typing import ClassVar, Dict, List, Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class ReleaseTable(BaseModel):
    """
    Junction table linking an AssetRelease to its PostGIS output table(s).

    This is the SINGLE SOURCE OF TRUTH for which tables a Release owns.
    Single-table uploads have one row. Geometry-split uploads have 2-3 rows.

    Primary Key: (release_id, table_name)
    Foreign Key: release_id → app.asset_releases(release_id)

    DDL Annotations:
        The __sql_* class attributes guide DDL generation via PydanticToSQL.
    """
    model_config = ConfigDict(
        use_enum_values=True,
        extra='ignore',
        str_strip_whitespace=True
    )

    # DDL generation hints
    __sql_table_name: ClassVar[str] = "release_tables"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["release_id", "table_name"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {
        "release_id": "app.asset_releases(release_id)"
    }
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["release_id"], "name": "idx_release_tables_release"},
        {"columns": ["table_name"], "name": "idx_release_tables_table"},
        {"columns": ["table_role"], "name": "idx_release_tables_role"},
    ]

    # Fields
    release_id: str = Field(
        ...,
        max_length=64,
        description="FK to app.asset_releases"
    )
    table_name: str = Field(
        ...,
        max_length=63,
        description="PostGIS table name (matches geo.table_catalog PK)"
    )
    geometry_type: str = Field(
        ...,
        max_length=30,
        description="PostGIS geometry type: MULTIPOLYGON, MULTILINESTRING, MULTIPOINT"
    )
    feature_count: int = Field(
        default=0,
        description="Number of features in this table"
    )
    table_role: str = Field(
        default="primary",
        max_length=20,
        description="Role: 'primary' (single table), 'geometry_split', 'view'"
    )
    table_suffix: Optional[str] = Field(
        default=None,
        max_length=20,
        description="Suffix applied: '_point', '_line', '_polygon', or None"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this record was created"
    )
