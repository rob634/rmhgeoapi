# Multi-Table Release Model — Design Document

**Created**: 26 FEB 2026
**Status**: APPROVED
**Branch**: TBD (new feature branch)
**Relates to**: V0.9_VIEWS.md (Split Views), geometry-type splitting

---

## Problem

Today, `AssetRelease.table_name` is a single `str` field — one Release maps to exactly one PostGIS table. Two upcoming features break this assumption:

1. **Geometry-type splitting**: A mixed-geometry upload (points + lines + polygons) should produce separate PostGIS tables instead of being rejected.
2. **Split Views** (V0.9_VIEWS.md): A single table can spawn per-value PostgreSQL views, each registered as a separate OGC Feature Collection.

Both require one Release to own multiple tables/views. Rather than bolt on workarounds, this design introduces a proper junction table as the **single source of truth** for Release-to-table relationships.

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Source of truth | `app.release_tables` junction table only | Fewer decision trees — one code path whether 1 or N tables |
| `AssetRelease.table_name` | **Drop entirely** | No dual paths, no sync bugs, clean break |
| Service layer grouping | `geo.table_catalog.table_group` field | Groups related tables without leaking internal IDs into replicated schema |
| Geometry split default | Auto-split on, configurable off | Most users want it to "just work" |
| Naming convention | `_point` / `_line` / `_polygon` suffix | Matches common GIS conventions |
| Composability | Geometry split + Split Views are orthogonal | Split tables can independently have views applied later |

---

## New Schema: `app.release_tables`

```sql
CREATE TABLE IF NOT EXISTS app.release_tables (
    release_id    TEXT NOT NULL REFERENCES app.asset_releases(release_id),
    table_name    TEXT NOT NULL,
    geometry_type TEXT NOT NULL,       -- MULTIPOLYGON, MULTILINESTRING, MULTIPOINT
    feature_count INT DEFAULT 0,
    table_role    TEXT NOT NULL DEFAULT 'primary',  -- 'primary', 'geometry_split', 'view'
    table_suffix  TEXT,                -- '_point', '_line', '_polygon', or NULL
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (release_id, table_name)
);
CREATE INDEX idx_release_tables_release ON app.release_tables(release_id);
```

**`table_role` values:**
- `primary` — single-table upload (today's behavior), always exactly one per single-type Release
- `geometry_split` — created by auto-splitting mixed geometry types
- `view` — future: Split Views feature

---

## Modified Schema: `geo.table_catalog`

```sql
ALTER TABLE geo.table_catalog ADD COLUMN table_group TEXT;
```

- Single-table upload: `table_group = NULL`
- Geometry splits: all split tables share `table_group = '<base_table_name>'`
- Split Views (future): views share `table_group` with their base table
- Replication-safe — no internal IDs exposed

---

## Removed Field: `AssetRelease.table_name`

The `table_name` column is dropped from `app.asset_releases`. All code that currently reads/writes `release.table_name` will instead use `ReleaseTableRepository` methods.

---

## New Repository: `ReleaseTableRepository`

```python
class ReleaseTableRepository:
    def create(self, release_id, table_name, geometry_type, table_role='primary',
               table_suffix=None, feature_count=0) -> ReleaseTable

    def create_batch(self, entries: list[ReleaseTable]) -> list[ReleaseTable]

    def get_tables(self, release_id: str) -> list[ReleaseTable]

    def get_primary_table(self, release_id: str) -> Optional[ReleaseTable]

    def get_by_table_name(self, table_name: str) -> Optional[ReleaseTable]

    def update_feature_count(self, release_id, table_name, count) -> None

    def delete_for_release(self, release_id: str) -> int
```

---

## Data Flow: Single-Type Upload (Common Case)

```
Submit → job_params includes table_name
ETL handler → creates 1 PostGIS table → inserts 1 row into app.release_tables
                                          (table_role='primary', table_suffix=NULL)
Unpublish → queries release_tables → gets 1 row → drops 1 table
```

No behavioral change from the user's perspective.

## Data Flow: Mixed-Geometry Upload (New)

```
Submit → job_params includes base table_name "osm_city"
ETL handler → prepare_gdf() detects 3 geometry types
           → returns dict: {point: gdf, line: gdf, polygon: gdf}
           → creates 3 PostGIS tables: osm_city_point, osm_city_line, osm_city_polygon
           → inserts 3 rows into app.release_tables
              (table_role='geometry_split', table_suffix='_point'/'_line'/'_polygon')
           → registers 3 rows in geo.table_catalog (table_group='osm_city')
Unpublish → queries release_tables → gets 3 rows → drops 3 tables
```

---

## Affected Files (10 files)

| # | File | Change |
|---|------|--------|
| 1 | `core/models/asset.py` | Remove `table_name` field, update `to_dict()` |
| 2 | `core/models/release_table.py` | **NEW** — `ReleaseTable` Pydantic model |
| 3 | `core/models/geo.py` | Add `table_group` field to `GeoTableCatalog` |
| 4 | `infrastructure/release_repository.py` | Remove `table_name` from INSERT/UPDATE/SELECT mapping |
| 5 | `infrastructure/release_table_repository.py` | **NEW** — `ReleaseTableRepository` CRUD |
| 6 | `services/asset_service.py` | Remove `table_name` from `update_physical_outputs()`, add `ReleaseTableRepository` methods |
| 7 | `triggers/platform/submit.py` | Write to `release_tables` instead of `update_physical_outputs(table_name=)` |
| 8 | `triggers/trigger_platform_status.py` | Replace `release.table_name` reads with `release_table_repo.get_tables()` |
| 9 | `services/platform_translation.py` | Replace `release.table_name` with `release_table_repo` lookup for unpublish |
| 10 | `services/platform_catalog_service.py` | Replace `release.get('table_name')` with junction table lookup |
| 11 | `services/asset_approval_service.py` | Replace `release.table_name` in ADF params with junction table lookup |
| 12 | `core/machine_factory.py` | Remove `outputs['table_name']` extraction, write to `release_tables` instead |
| 13 | `core/schema/sql_generator.py` | Add `release_tables` DDL to ensure flow |

---

## Migration Strategy

1. **Create `app.release_tables`** via `action=ensure` (additive — safe)
2. **Add `table_group` to `geo.table_catalog`** via `action=ensure` (additive — safe)
3. **Backfill**: `INSERT INTO app.release_tables (release_id, table_name, geometry_type, table_role) SELECT release_id, table_name, 'UNKNOWN', 'primary' FROM app.asset_releases WHERE table_name IS NOT NULL`
4. **Deploy code** that reads from junction table instead of `release.table_name`
5. **Drop column**: `ALTER TABLE app.asset_releases DROP COLUMN table_name` (manual migration, not via ensure)

Steps 1-2 are safe and idempotent. Step 3 is a one-time backfill. Step 4 is the code deployment. Step 5 is cleanup after verification.
