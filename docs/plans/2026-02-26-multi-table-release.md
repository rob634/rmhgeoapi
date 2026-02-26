# Multi-Table Release Schema Change — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace `AssetRelease.table_name` (single string) with `app.release_tables` junction table so one Release can own multiple PostGIS tables.

**Architecture:** New `ReleaseTable` Pydantic model + `ReleaseTableRepository` for CRUD. Drop `table_name` from `AssetRelease`. Add `table_group` to `geo.table_catalog`. Update all 10+ consumer files to read from junction table instead of `release.table_name`.

**Tech Stack:** Python 3.12, Pydantic v2, psycopg 3, PostgreSQL/PostGIS

**Key docs:**
- Design: `docs/plans/2026-02-26-multi-table-release-design.md`
- Existing models: `core/models/asset.py` (AssetRelease), `core/models/geo.py` (GeoTableCatalog)
- DDL generation: `core/schema/sql_generator.py`
- Dev philosophy: No backward compatibility — fail explicitly, never create fallbacks

---

## Task 1: Create `ReleaseTable` Pydantic Model

**Files:**
- Create: `core/models/release_table.py`
- Modify: `core/models/__init__.py` (add export)

**Step 1: Create the model file**

Create `core/models/release_table.py`. Follow the exact pattern used by `VectorEtlTracking` in `core/models/etl_tracking.py:84-122` (same composite PK, same ClassVar DDL hints pattern):

```python
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
```

**Step 2: Add export to `core/models/__init__.py`**

Find the imports section in `core/models/__init__.py` and add:

```python
from core.models.release_table import ReleaseTable
```

And add `ReleaseTable` to the `__all__` list if one exists.

**Step 3: Verify model instantiation**

Run:
```bash
cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "
from core.models.release_table import ReleaseTable
rt = ReleaseTable(release_id='test123', table_name='my_table', geometry_type='MULTIPOLYGON')
print(f'OK: {rt.release_id}, {rt.table_name}, {rt.geometry_type}, role={rt.table_role}')
"
```
Expected: `OK: test123, my_table, MULTIPOLYGON, role=primary`

**Step 4: Commit**

```bash
git add core/models/release_table.py core/models/__init__.py
git commit -m "Add ReleaseTable model for multi-table release support"
```

---

## Task 2: Add `table_group` to `GeoTableCatalog` Model

**Files:**
- Modify: `core/models/geo.py:78-114` (GeoTableCatalog class)

**Step 1: Add the field**

In `core/models/geo.py`, find the `custom_properties` field (near end of GeoTableCatalog class) and add `table_group` BEFORE it, in the metadata section:

```python
    table_group: Optional[str] = Field(
        default=None,
        max_length=63,
        description="Groups related tables (geometry splits share same group). NULL for single-table uploads."
    )
```

Also add an index for `table_group` to the `__sql_indexes` ClassVar list at line 108-114:

```python
        {"columns": ["table_group"], "name": "idx_table_catalog_group", "partial_where": "table_group IS NOT NULL"},
```

**Step 2: Verify model**

Run:
```bash
cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "
from core.models.geo import GeoTableCatalog
print([f for f in GeoTableCatalog.model_fields if 'group' in f])
"
```
Expected: `['table_group']`

**Step 3: Commit**

```bash
git add core/models/geo.py
git commit -m "Add table_group field to GeoTableCatalog for multi-table grouping"
```

---

## Task 3: Register `ReleaseTable` in DDL Generation

**Files:**
- Modify: `core/schema/sql_generator.py:1572-1679` (generate_composed_statements method)

**Step 1: Add import**

At the top of `sql_generator.py`, find the existing model imports (look for `from core.models.asset import Asset, AssetRelease`) and add:

```python
from core.models.release_table import ReleaseTable
```

**Step 2: Add table generation**

In `generate_composed_statements()` method, after line 1646 (`AssetRelease` generation), add:

```python
        composed.append(self.generate_table_from_model(ReleaseTable))  # Release→tables junction (26 FEB 2026)
```

**Step 3: Add index generation**

After line 1666 (`AssetRelease` indexes), add:

```python
        composed.extend(self.generate_indexes_from_model(ReleaseTable))  # Release→tables junction (26 FEB 2026)
```

**Step 4: Verify DDL generation**

Run:
```bash
cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "
from core.schema.sql_generator import PydanticToSQL
from core.models.release_table import ReleaseTable
gen = PydanticToSQL(schema_name='app')
ddl = gen.generate_table_from_model(ReleaseTable)
print(str(ddl.as_string(None)) if hasattr(ddl, 'as_string') else str(ddl))
"
```
Expected: SQL containing `CREATE TABLE IF NOT EXISTS app.release_tables` with the correct columns and PK.

**Step 5: Commit**

```bash
git add core/schema/sql_generator.py
git commit -m "Register ReleaseTable in DDL generation for ensure flow"
```

---

## Task 4: Create `ReleaseTableRepository`

**Files:**
- Create: `infrastructure/release_table_repository.py`
- Modify: `infrastructure/__init__.py` (add export)

**Step 1: Create the repository**

Create `infrastructure/release_table_repository.py`. Follow the patterns in `infrastructure/release_repository.py` for connection management (`self._get_connection()`, `psycopg.sql` composition, `RealDictCursor`).

Look at how `ReleaseRepository.__init__()` works (it inherits from a base or uses `self.schema = 'app'`, `self.table = 'asset_releases'`). The new repo should follow the same pattern.

```python
# ============================================================================
# CLAUDE CONTEXT - RELEASE TABLE REPOSITORY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Repository - CRUD for app.release_tables junction table
# PURPOSE: Single source of truth for Release → PostGIS table relationships
# LAST_REVIEWED: 26 FEB 2026
# EXPORTS: ReleaseTableRepository
# DEPENDENCIES: psycopg, core.models.release_table
# ============================================================================

import logging
from typing import List, Optional
from datetime import datetime, timezone

from psycopg import sql
from psycopg.rows import dict_row

from core.models.release_table import ReleaseTable

logger = logging.getLogger(__name__)


class ReleaseTableRepository:
    """
    Repository for app.release_tables — the junction table linking
    releases to their PostGIS output tables.

    This is the SINGLE SOURCE OF TRUTH for which tables a release owns.
    """

    def __init__(self, conn_provider=None):
        """
        Args:
            conn_provider: Callable that returns a psycopg connection.
                           If None, uses default from infrastructure.
        """
        self.schema = "app"
        self.table = "release_tables"
        self._conn_provider = conn_provider

    def _get_connection(self):
        """Get database connection using same pattern as ReleaseRepository."""
        if self._conn_provider:
            return self._conn_provider()
        from infrastructure.database import get_connection
        return get_connection()

    def create(
        self,
        release_id: str,
        table_name: str,
        geometry_type: str,
        table_role: str = "primary",
        table_suffix: Optional[str] = None,
        feature_count: int = 0
    ) -> ReleaseTable:
        """Insert a single release_tables row."""
        now = datetime.now(timezone.utc)

        with self._get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL("""
                        INSERT INTO {}.{} (
                            release_id, table_name, geometry_type,
                            feature_count, table_role, table_suffix,
                            created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING *
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (release_id, table_name, geometry_type,
                     feature_count, table_role, table_suffix, now)
                )
                row = cur.fetchone()
                conn.commit()
                logger.info(f"Created release_table: {release_id[:12]}... -> {table_name}")
                return self._row_to_model(row)

    def create_batch(self, entries: List[ReleaseTable]) -> List[ReleaseTable]:
        """Insert multiple release_tables rows in one transaction."""
        if not entries:
            return []

        now = datetime.now(timezone.utc)
        results = []

        with self._get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                for entry in entries:
                    cur.execute(
                        sql.SQL("""
                            INSERT INTO {}.{} (
                                release_id, table_name, geometry_type,
                                feature_count, table_role, table_suffix,
                                created_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                            RETURNING *
                        """).format(
                            sql.Identifier(self.schema),
                            sql.Identifier(self.table)
                        ),
                        (entry.release_id, entry.table_name, entry.geometry_type,
                         entry.feature_count, entry.table_role, entry.table_suffix, now)
                    )
                    row = cur.fetchone()
                    results.append(self._row_to_model(row))

                conn.commit()
                logger.info(f"Created {len(results)} release_table entries for {entries[0].release_id[:12]}...")
                return results

    def get_tables(self, release_id: str) -> List[ReleaseTable]:
        """Get ALL tables owned by a release."""
        with self._get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE release_id = %s
                        ORDER BY table_role, table_name
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (release_id,)
                )
                rows = cur.fetchall()
                return [self._row_to_model(r) for r in rows]

    def get_primary_table(self, release_id: str) -> Optional[ReleaseTable]:
        """Get the primary table for a release (or first table if geometry_split)."""
        tables = self.get_tables(release_id)
        if not tables:
            return None
        # Prefer 'primary' role, fall back to first entry
        for t in tables:
            if t.table_role == 'primary':
                return t
        return tables[0]

    def get_by_table_name(self, table_name: str) -> Optional[ReleaseTable]:
        """Find which release owns a given table."""
        with self._get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE table_name = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (table_name,)
                )
                row = cur.fetchone()
                return self._row_to_model(row) if row else None

    def get_table_names(self, release_id: str) -> List[str]:
        """Get just the table names for a release (convenience method)."""
        tables = self.get_tables(release_id)
        return [t.table_name for t in tables]

    def update_feature_count(self, release_id: str, table_name: str, count: int) -> bool:
        """Update feature_count for a specific release+table entry."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET feature_count = %s
                        WHERE release_id = %s AND table_name = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (count, release_id, table_name)
                )
                conn.commit()
                return cur.rowcount > 0

    def delete_for_release(self, release_id: str) -> int:
        """Delete ALL table entries for a release. Returns count deleted."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        DELETE FROM {}.{}
                        WHERE release_id = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (release_id,)
                )
                conn.commit()
                count = cur.rowcount
                if count:
                    logger.info(f"Deleted {count} release_table entries for {release_id[:12]}...")
                return count

    def _row_to_model(self, row: dict) -> ReleaseTable:
        """Convert a database row to a ReleaseTable model."""
        return ReleaseTable(
            release_id=row['release_id'],
            table_name=row['table_name'],
            geometry_type=row.get('geometry_type', 'UNKNOWN'),
            feature_count=row.get('feature_count', 0),
            table_role=row.get('table_role', 'primary'),
            table_suffix=row.get('table_suffix'),
            created_at=row.get('created_at', datetime.now(timezone.utc)),
        )
```

**Step 2: Add export to `infrastructure/__init__.py`**

Find the imports in `infrastructure/__init__.py` and add:

```python
from infrastructure.release_table_repository import ReleaseTableRepository
```

Add `ReleaseTableRepository` to the `__all__` list if one exists.

**Step 3: Verify import**

Run:
```bash
cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "
from infrastructure.release_table_repository import ReleaseTableRepository
repo = ReleaseTableRepository.__new__(ReleaseTableRepository)
print(f'OK: schema={repo.__class__.__name__}')
"
```
Expected: `OK: schema=ReleaseTableRepository`

**Step 4: Commit**

```bash
git add infrastructure/release_table_repository.py infrastructure/__init__.py
git commit -m "Add ReleaseTableRepository for release_tables CRUD"
```

---

## Task 5: Remove `table_name` from `AssetRelease` Model

**Files:**
- Modify: `core/models/asset.py:453-457` (remove field), `core/models/asset.py:680` (remove from to_dict)
- Modify: `infrastructure/release_repository.py` (remove from INSERT/UPDATE/SELECT at lines 126, 167, 236, 273, 988, 1024, 1363)
- Modify: `services/asset_service.py:546,572` (remove from update_physical_outputs wrapper)

**Step 1: Remove field from AssetRelease model**

In `core/models/asset.py`, delete lines 453-457 (the `table_name` field definition):

```python
    # DELETE THIS:
    table_name: Optional[str] = Field(
        default=None,
        max_length=63,
        description="PostGIS table name for vector outputs"
    )
```

**Step 2: Remove from `to_dict()`**

In `core/models/asset.py` at line 680, remove:

```python
            'table_name': self.table_name,
```

**Step 3: Remove from `ReleaseRepository.create()` (first INSERT)**

In `infrastructure/release_repository.py`, the INSERT at lines 120-193:
- Remove `table_name` from the column list (line 126)
- Remove the corresponding `%s` placeholder from VALUES
- Remove `release.table_name` from the values tuple (line 167)

The physical outputs line should change from:
```
blob_path, table_name, stac_item_id, stac_collection_id,
```
to:
```
blob_path, stac_item_id, stac_collection_id,
```

And the values tuple from:
```
release.blob_path, release.table_name,
release.stac_item_id, release.stac_collection_id,
```
to:
```
release.blob_path,
release.stac_item_id, release.stac_collection_id,
```

Also remove one `%s` from the VALUES placeholder (the line that had `%s, %s, %s, %s,` for physical outputs becomes `%s, %s, %s,`).

**Step 4: Remove from `ReleaseRepository.create_and_count_atomic()` (second INSERT)**

Same changes as Step 3, but in the second INSERT block at lines 230-293. Same column list, VALUES, and tuple changes.

**Step 5: Remove from `update_physical_outputs()`**

In `infrastructure/release_repository.py` at line 988, remove the `table_name: str = None` parameter.
At line 1024, remove `'table_name': table_name` from the `field_map` dict.

In `services/asset_service.py` at line 546, remove the `table_name: Optional[str] = None` parameter.
At line 572, remove `table_name=table_name` from the call to `release_repo.update_physical_outputs()`.

**Step 6: Remove from `_row_to_model()`**

In `infrastructure/release_repository.py` at line 1363, remove:

```python
            table_name=row.get('table_name'),
```

**Step 7: Verify model loads**

Run:
```bash
cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "
from core.models.asset import AssetRelease
fields = AssetRelease.model_fields
assert 'table_name' not in fields, 'table_name should be removed!'
print(f'OK: AssetRelease has {len(fields)} fields, table_name removed')
"
```
Expected: `OK: AssetRelease has N fields, table_name removed`

**Step 8: Commit**

```bash
git add core/models/asset.py infrastructure/release_repository.py services/asset_service.py
git commit -m "Remove table_name from AssetRelease — release_tables is now source of truth"
```

---

## Task 6: Update Submit Trigger

**Files:**
- Modify: `triggers/platform/submit.py:338-343`

**Step 1: Replace update_physical_outputs(table_name=) with release_tables insert**

At the top of the function (near other repository imports), add:

```python
from infrastructure import ReleaseTableRepository
```

At lines 338-343, replace:

```python
                    job_params['table_name'] = final_table
                    job_params['stac_item_id'] = final_stac

                    asset_service.update_physical_outputs(
                        release.release_id, table_name=final_table, stac_item_id=final_stac
                    )
```

with:

```python
                    job_params['table_name'] = final_table
                    job_params['stac_item_id'] = final_stac

                    # Write table name to junction table (single source of truth)
                    release_table_repo = ReleaseTableRepository()
                    release_table_repo.create(
                        release_id=release.release_id,
                        table_name=final_table,
                        geometry_type='UNKNOWN',  # Set by ETL handler after processing
                        table_role='primary',
                    )

                    # Still update stac_item_id on release (not a table field)
                    asset_service.update_physical_outputs(
                        release.release_id, stac_item_id=final_stac
                    )
```

**NOTE:** `job_params['table_name']` stays — the ETL handler still needs the base table name as a job parameter. Only the Release record changes.

**Step 2: Commit**

```bash
git add triggers/platform/submit.py
git commit -m "Update submit trigger to write table_name to release_tables"
```

---

## Task 7: Update Machine Factory

**Files:**
- Modify: `core/machine_factory.py:240-274`

**Step 1: Replace outputs['table_name'] extraction**

At lines 243-246, the current code extracts `table_name` from job result and passes it to `update_physical_outputs()`. Change this to write to `release_tables` instead.

Replace lines 243-246:

```python
                # Vector: table_name from result
                table_name = result.get('table_name')
                if table_name:
                    outputs['table_name'] = table_name
```

with:

```python
                # Vector: table_name from result → write to release_tables
                table_name = result.get('table_name')
                if table_name:
                    from infrastructure import ReleaseTableRepository
                    release_table_repo = ReleaseTableRepository()
                    # Check if already exists (submit trigger may have created a placeholder)
                    existing = release_table_repo.get_tables(release.release_id)
                    if existing:
                        # Update feature count from result
                        total_rows = result.get('total_rows', 0)
                        if total_rows:
                            release_table_repo.update_feature_count(
                                release.release_id, existing[0].table_name, total_rows
                            )
                    else:
                        # Create entry (fallback if submit didn't create one)
                        geom_type = result.get('geometry_type', 'UNKNOWN')
                        release_table_repo.create(
                            release_id=release.release_id,
                            table_name=table_name,
                            geometry_type=geom_type,
                            feature_count=result.get('total_rows', 0),
                            table_role='primary',
                        )
```

**Step 2: Commit**

```bash
git add core/machine_factory.py
git commit -m "Update machine_factory to write vector table_name to release_tables"
```

---

## Task 8: Update Platform Status Trigger

**Files:**
- Modify: `triggers/trigger_platform_status.py` (lines 773, 822-824, 864-868, 923-925)

This file has 4 places reading `release.table_name`. Each needs to query `release_tables` instead.

**Step 1: Add helper function at module level**

Near the top of `triggers/trigger_platform_status.py` (after existing imports), add:

```python
def _get_release_table_names(release_id: str) -> list[str]:
    """Get table names for a release from the junction table."""
    from infrastructure import ReleaseTableRepository
    repo = ReleaseTableRepository()
    return repo.get_table_names(release_id)
```

**Step 2: Update release summary (line 773)**

Replace:
```python
            "table_name": getattr(release, 'table_name', None),
```
with:
```python
            "table_names": _get_release_table_names(release.release_id),
```

**Step 3: Update _build_outputs_block (lines 822-824)**

Replace:
```python
    if release.table_name:
        outputs["table_name"] = release.table_name
        outputs["schema"] = "geo"
```
with:
```python
    table_names = _get_release_table_names(release.release_id)
    if table_names:
        outputs["table_names"] = table_names
        outputs["table_name"] = table_names[0]  # Primary for backward-compat in API response
        outputs["schema"] = "geo"
```

**Step 4: Update _build_services_block (lines 864-868)**

Replace:
```python
    elif data_type == "vector" and release.table_name:
        tipg_base = config.tipg_base_url
        qualified = f"geo.{release.table_name}" if '.' not in release.table_name else release.table_name
        services["collection"] = f"{tipg_base}/collections/{qualified}"
        services["items"] = f"{tipg_base}/collections/{qualified}/items"
```
with:
```python
    elif data_type == "vector":
        table_names = _get_release_table_names(release.release_id)
        if table_names:
            tipg_base = config.tipg_base_url
            # Return URLs for ALL tables (multi-table releases)
            if len(table_names) == 1:
                qualified = f"geo.{table_names[0]}"
                services["collection"] = f"{tipg_base}/collections/{qualified}"
                services["items"] = f"{tipg_base}/collections/{qualified}/items"
            else:
                services["collections"] = []
                for tn in table_names:
                    qualified = f"geo.{tn}"
                    services["collections"].append({
                        "table_name": tn,
                        "collection": f"{tipg_base}/collections/{qualified}",
                        "items": f"{tipg_base}/collections/{qualified}/items",
                    })
```

**Step 5: Update _build_approval_block (lines 923-925)**

Replace:
```python
    elif data_type == "vector" and release.table_name:
        approval["viewer_url"] = f"{platform_base}/api/interface/vector-viewer?collection={release.table_name}&asset_id={asset_id}"
        approval["embed_url"] = f"{platform_base}/api/interface/vector-viewer?collection={release.table_name}&asset_id={asset_id}&embed=true"
```
with:
```python
    elif data_type == "vector":
        table_names = _get_release_table_names(release.release_id)
        if table_names:
            # Use first/primary table for viewer URLs
            primary_table = table_names[0]
            approval["viewer_url"] = f"{platform_base}/api/interface/vector-viewer?collection={primary_table}&asset_id={asset_id}"
            approval["embed_url"] = f"{platform_base}/api/interface/vector-viewer?collection={primary_table}&asset_id={asset_id}&embed=true"
            if len(table_names) > 1:
                approval["all_tables"] = table_names
```

**Step 6: Commit**

```bash
git add triggers/trigger_platform_status.py
git commit -m "Update platform status trigger to read from release_tables"
```

---

## Task 9: Update Platform Translation (Unpublish)

**Files:**
- Modify: `services/platform_translation.py:132-147`

**Step 1: Replace release.table_name lookup**

Replace lines 132-147:

```python
    if data_type == "vector":
        # Read stored table_name from Release (authoritative source)
        table_name = None
        if request.job_id:
            from infrastructure import ReleaseRepository
            release_repo = ReleaseRepository()
            release = release_repo.get_by_job_id(request.job_id)
            if release and release.table_name:
                table_name = release.table_name

        if not table_name:
            # Fallback: reconstruct (pre-ordinal data only)
            table_name = generate_table_name(request.dataset_id, request.resource_id, request.version_id)
            logger.warning(f"Reconstructed table_name (no release): {table_name}")

        return {'table_name': table_name}
```

with:

```python
    if data_type == "vector":
        # Read table names from release_tables junction (authoritative source)
        table_names = []
        if request.job_id:
            from infrastructure import ReleaseRepository, ReleaseTableRepository
            release_repo = ReleaseRepository()
            release = release_repo.get_by_job_id(request.job_id)
            if release:
                release_table_repo = ReleaseTableRepository()
                table_names = release_table_repo.get_table_names(release.release_id)

        if not table_names:
            # Fallback: reconstruct (pre-ordinal data only)
            table_name = generate_table_name(request.dataset_id, request.resource_id, request.version_id)
            logger.warning(f"Reconstructed table_name (no release_tables entry): {table_name}")
            table_names = [table_name]

        # Return all table names — unpublish handler must drop all of them
        return {'table_names': table_names, 'table_name': table_names[0]}
```

**IMPORTANT:** This changes the unpublish params contract. The `unpublish_vector` job and its handlers will need a follow-up update to handle `table_names` (list) in addition to `table_name` (single). For now, we keep `table_name` as the first entry for backward compat with the existing unpublish job. The unpublish multi-table support is a separate task to be designed with the geometry splitting feature.

**Step 2: Commit**

```bash
git add services/platform_translation.py
git commit -m "Update unpublish params to read from release_tables"
```

---

## Task 10: Update Platform Catalog Service

**Files:**
- Modify: `services/platform_catalog_service.py:594-625`

**Step 1: Replace release.get('table_name')**

The `_build_vector_response()` method at line 594 reads `table_name = release.get('table_name')`. The `release` here is a dict from `to_dict()`, so `table_name` won't be there after removal.

Replace lines 594-627 area. Find where `table_name = release.get('table_name')` is and replace with a junction table lookup:

```python
        # Get table names from junction table
        from infrastructure import ReleaseTableRepository
        release_table_repo = ReleaseTableRepository()
        release_id = release.get('release_id')
        table_names = release_table_repo.get_table_names(release_id) if release_id else []
        table_name = table_names[0] if table_names else None
```

The rest of the method that uses `table_name` for URL generation stays the same — it already guards with `if table_name`.

**Step 2: Commit**

```bash
git add services/platform_catalog_service.py
git commit -m "Update catalog service to read table_name from release_tables"
```

---

## Task 11: Update Approval Service (ADF Params)

**Files:**
- Modify: `services/asset_approval_service.py:819`

**Step 1: Replace release.table_name in ADF pipeline params**

At line 819, the ADF pipeline parameters include `'table_name': release.table_name`. Replace with junction table lookup.

Find the ADF trigger block (around line 811-822) and replace:

```python
                    'table_name': release.table_name,
```

with:

```python
                    'table_names': ReleaseTableRepository().get_table_names(release.release_id),
```

Add the import near the top of the method or file:

```python
from infrastructure import ReleaseTableRepository
```

**Step 2: Commit**

```bash
git add services/asset_approval_service.py
git commit -m "Update approval service ADF params to use release_tables"
```

---

## Task 12: Write Migration Backfill Script

**Files:**
- Create: `scripts/migrate_release_tables.py`

**Step 1: Create migration script**

This script backfills existing `AssetRelease` records that have a `table_name` column value (the column still exists in the DB even though we removed it from the model) into `app.release_tables`.

```python
"""
Migration: Backfill app.release_tables from existing app.asset_releases.table_name

Run AFTER deploying the new code with `action=ensure` (to create the table),
but BEFORE dropping the table_name column.

Usage:
    conda run -n azgeo python scripts/migrate_release_tables.py
"""
import logging
from infrastructure.database import get_connection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate():
    """Backfill release_tables from asset_releases.table_name."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Count existing entries
            cur.execute("SELECT COUNT(*) FROM app.release_tables")
            existing = cur.fetchone()[0]
            if existing > 0:
                logger.warning(f"app.release_tables already has {existing} rows. Skipping duplicates.")

            # Backfill: INSERT rows that don't already exist
            cur.execute("""
                INSERT INTO app.release_tables (
                    release_id, table_name, geometry_type,
                    feature_count, table_role, table_suffix, created_at
                )
                SELECT
                    ar.release_id,
                    ar.table_name,
                    COALESCE(tc.geometry_type, 'UNKNOWN'),
                    COALESCE(tc.feature_count, 0),
                    'primary',
                    NULL,
                    ar.created_at
                FROM app.asset_releases ar
                LEFT JOIN geo.table_catalog tc ON tc.table_name = ar.table_name
                WHERE ar.table_name IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM app.release_tables rt
                      WHERE rt.release_id = ar.release_id
                        AND rt.table_name = ar.table_name
                  )
            """)
            migrated = cur.rowcount
            conn.commit()

            logger.info(f"Migrated {migrated} rows to app.release_tables")

            # Verify
            cur.execute("SELECT COUNT(*) FROM app.release_tables")
            total = cur.fetchone()[0]
            logger.info(f"Total rows in app.release_tables: {total}")


if __name__ == '__main__':
    migrate()
```

**Step 2: Commit**

```bash
git add scripts/migrate_release_tables.py
git commit -m "Add migration script to backfill release_tables from existing data"
```

---

## Task 13: Final Verification

**Step 1: Run full import check**

Verify no import errors across all modified files:

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "
from core.models.release_table import ReleaseTable
from core.models.asset import AssetRelease
from core.models.geo import GeoTableCatalog
from infrastructure.release_table_repository import ReleaseTableRepository

# Verify table_name removed from AssetRelease
assert 'table_name' not in AssetRelease.model_fields, 'table_name should be removed!'

# Verify table_group added to GeoTableCatalog
assert 'table_group' in GeoTableCatalog.model_fields, 'table_group should exist!'

# Verify ReleaseTable model
rt = ReleaseTable(release_id='test', table_name='t', geometry_type='MULTIPOLYGON')
assert rt.table_role == 'primary'

print('All verifications passed')
"
```
Expected: `All verifications passed`

**Step 2: Run existing tests**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest tests/ -v --tb=short 2>&1 | head -50
```

Fix any failures before proceeding.

**Step 3: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "Fix any issues from verification pass"
```

---

## Deployment Order

After all code is merged:

1. `action=ensure` — creates `app.release_tables` table + `table_group` column (safe, additive)
2. Deploy code — all reads now use junction table
3. Run migration: `conda run -n azgeo python scripts/migrate_release_tables.py`
4. Verify: `SELECT COUNT(*) FROM app.release_tables` should match `SELECT COUNT(*) FROM app.asset_releases WHERE table_name IS NOT NULL`
5. (Later, manual) Drop orphaned column: `ALTER TABLE app.asset_releases DROP COLUMN table_name`

---

## Out of Scope (Deferred to Geometry Splitting Feature)

- Updating `unpublish_vector` job to handle multiple table names
- Updating the vector ETL handler to write multiple tables
- The `prepare_gdf()` split logic
- `postgis_handler.py` changes for creating multiple tables
- Multi-table STAC materialization at approval time
