# H3 Agricultural Geography Platform - Design Document

## Executive Summary

Building a cloud-native, multi-resolution geospatial data platform for agricultural and climate analysis at the World Bank. The platform aggregates global datasets (MapSPAM crop production, climate variables, topography) into an H3 hexagonal grid at resolutions 2-7, stored in PostGIS + GeoParquet, and exposed via REST API.

**Goal**: Replace ad-hoc geospatial analysis requests with a queryable, self-service platform that DEC can own and maintain.

**Key Innovation**: Using H3's hierarchical structure for efficient multi-scale analysis, combining PostGIS for spatial queries with GeoParquet for massive time-series data.

---

## 🚀 IMPLEMENTATION TODO - H3 Grid Bootstrap (Res 2→7 Cascade)

**Status**: ⏳ **PLANNED** (10 NOV 2025)
**Goal**: Generate hierarchical land-only H3 grid pyramid (resolutions 2-7) using spatial filtering at top level, then cascading children via H3 parent-child relationships
**Context**: Bootstrap operation runs once after deployment, creates ~34M land cells globally across 6 resolution levels in dedicated `h3` schema (separate from user data in `geo` schema)
**Last Updated**: 10 NOV 2025
**Estimated Development Time**: 11-12 hours
**Estimated Execution Time**: 15-20 hours (automated, overnight)

---

### Architecture Summary

**Key Design Decisions**:
- ✅ **Dedicated `h3` schema** (separate from `geo` schema for user-uploaded data)
- ✅ Spatial filtering ONLY at resolution 2 (top level, ~5,882 global cells)
- ✅ Level-by-level cascade: Res 2 → Res 3 → Res 4 → Res 5 → Res 6 → Res 7
- ✅ Each child inherits `parent_res2` for GeoParquet partition routing
- ✅ H3 index sorting provides inherent spatial structure for exports
- ✅ ~30% of global cells at each level (land only, avoids open ocean)
- ✅ Idempotent design (re-running safe, uses ON CONFLICT DO NOTHING)

**Schema Organization**:
- **`h3` schema**: System-generated H3 grids (bootstrap data, read-only for users)
  - Tables: `h3.grids`, `h3.reference_filters`, `h3.grid_metadata`
- **`geo` schema**: User-uploaded vector data (ingest_vector jobs)
  - Tables: `geo.countries` (used for res 2 spatial filtering)
  - User tables created by ingest_vector workflow
- **Clean separation**: System H3 data vs. user geospatial data

**Expected Cell Counts** (Global Land Coverage):
- Res 2: ~2,847 cells (reference grid with spatial attribution)
- Res 3: ~19,929 cells (2,847 × 7 children/parent)
- Res 4: ~139,503 cells
- Res 5: ~976,521 cells
- Res 6: ~6,835,647 cells (primary working resolution, matches 10km MapSPAM)
- Res 7: ~47,849,529 cells (finest resolution)

**Job Structure**: Single 7-stage job (`bootstrap_h3_land_grid_pyramid`)
- Stage 1: Generate res 2 + spatial filter (15 min, single task)
- Stages 2-6: Generate children for previous resolution (fan-out, parallel)
- Stage 7: Finalize pyramid (30 min, metadata + indexes)

---

### Phase 0: H3 Schema Creation (CRITICAL - Always First)

**Goal**: Create dedicated `h3` schema for system-generated H3 grids
**Time**: 10 minutes
**Priority**: **CRITICAL** - Must run before any other H3 operations

#### Why Separate Schema?

**`h3` schema (System-Generated)**:
- Bootstrap H3 grids (resolutions 2-7)
- Reference filters (land_res2, etc.)
- Grid metadata and status tracking
- **Read-only for users** (no user modifications allowed)
- Managed by system bootstrap jobs

**`geo` schema (User Data)**:
- User-uploaded vector data (ingest_vector jobs)
- Country boundaries (for spatial filtering)
- User-created PostGIS tables
- **Read-write for users** (user-managed data)

**Benefits**:
- ✅ Clear separation of concerns
- ✅ Access control: Users can't accidentally modify H3 grids
- ✅ Backup strategy: Can backup `h3` schema separately (rarely changes)
- ✅ Permissions: Grant SELECT-only to users on `h3.*`, full control on `geo.*`
- ✅ Namespace clarity: `h3.grids` vs `geo.user_table`

#### Tasks

- [x] **Create `sql/init/00_create_h3_schema.sql`** ✅ COMPLETED (10 NOV 2025)
  ```sql
  -- ============================================================================
  -- H3 SCHEMA - System-generated H3 grids (Bootstrap Data)
  -- ============================================================================
  -- PURPOSE: Dedicated schema for H3 hexagonal grids (resolutions 2-7)
  -- SEPARATION: h3 schema = system data, geo schema = user data
  -- CREATED: 10 NOV 2025
  -- AUTHOR: Robert and Geospatial Claude Legion
  -- ============================================================================

  -- Create h3 schema if not exists (idempotent)
  CREATE SCHEMA IF NOT EXISTS h3;

  -- Grant permissions
  -- System user (rob634) has full control
  GRANT ALL PRIVILEGES ON SCHEMA h3 TO rob634;
  GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA h3 TO rob634;
  GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA h3 TO rob634;

  -- Future: Grant SELECT-only to read-only users
  -- GRANT USAGE ON SCHEMA h3 TO readonly_user;
  -- GRANT SELECT ON ALL TABLES IN SCHEMA h3 TO readonly_user;

  -- Schema comments
  COMMENT ON SCHEMA h3 IS 'System-generated H3 hexagonal grids (resolutions 2-7) for World Bank Agricultural Geography Platform. Read-only for users.';

  -- Verification
  SELECT schema_name
  FROM information_schema.schemata
  WHERE schema_name = 'h3';

  -- Success message
  DO $$
  BEGIN
      RAISE NOTICE 'H3 schema created successfully';
  END $$;
  ```

- [ ] **Update all H3 SQL files to use `h3` schema instead of `geo`**
  - `sql/init/02_create_h3_grids_table.sql` → Change `geo.h3_grids` to `h3.grids`
  - `sql/init/04_create_h3_reference_filters_table.sql` → Change `geo.h3_reference_filters` to `h3.reference_filters`
  - New file: `sql/init/06_create_h3_grid_metadata_table.sql` → Use `h3.grid_metadata`

- [ ] **Deploy schema to PostgreSQL (FIRST STEP)**
  ```bash
  # Run BEFORE any other H3 operations
  psql -h rmhpgflex.postgres.database.azure.com -U rob634 -d geopgflex \
    < sql/init/00_create_h3_schema.sql
  ```

- [ ] **Verify schema creation**
  ```sql
  -- Check schema exists
  SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'h3';

  -- Check permissions
  SELECT schema_name, schema_owner FROM information_schema.schemata WHERE schema_name = 'h3';
  ```

---

### Phase 1: Database Schema Updates & H3 Repository

**Goal**: Create database tables in `h3` schema and H3-specific repository using safe SQL composition
**Time**: 1.5 hours (30 min schemas + 1 hour repository)

#### Architecture Decision: Use PostgreSQLRepository Pattern

**Why Repository Pattern?**
- ✅ **Safe SQL Composition**: Use `psycopg.sql.SQL()` and `sql.Identifier()` for injection prevention
- ✅ **Reuse Connection Management**: Leverage existing `PostgreSQLRepository` base class
- ✅ **Transaction Support**: Atomic operations with built-in rollback
- ✅ **Consistent Error Handling**: Logging and retry logic already implemented
- ✅ **Schema-Aware**: Works seamlessly with `h3` schema
- ✅ **Testable**: Can mock repository in unit tests

**Pattern from Existing Code** (`infrastructure/postgresql.py`):
```python
from psycopg import sql

# ✅ SAFE: sql.Identifier prevents SQL injection on schema/table/column names
query = sql.SQL("""
    INSERT INTO {schema}.{table} (h3_index, resolution, geom)
    VALUES (%s, %s, ST_GeomFromText(%s, 4326))
""").format(
    schema=sql.Identifier('h3'),      # Quoted identifier (safe)
    table=sql.Identifier('grids')     # Quoted identifier (safe)
)

# Execute with parameterized values (%s - psycopg handles escaping)
cursor.execute(query, (h3_index, resolution, geom_wkt))
```

**New Repository**: `infrastructure/h3_repository.py`
- Inherits: `PostgreSQLRepository` (connection mgmt, safe SQL, transactions)
- Schema: `'h3'` (dedicated H3 schema)
- Methods:
  - `insert_h3_cells()` - Bulk insert with `executemany()` and safe SQL
  - `get_parent_ids()` - Query parent H3 indices
  - `update_spatial_attributes()` - Update country_code, is_land via spatial join
  - `get_cell_count()` - Count cells by grid_id
  - `grid_exists()` - Check if grid_id exists (idempotency)

**Benefits for H3 Operations**:
- All handlers use `H3Repository()` instead of raw psycopg connections
- Consistent SQL composition across all H3 operations
- Single source of truth for H3 database access
- Easy to add caching, connection pooling, or other cross-cutting concerns

#### Tasks

- [x] **Create `infrastructure/h3_repository.py`** ✅ COMPLETED (10 NOV 2025) - 673 lines, 10 methods, safe SQL composition
  - **Class**: `H3Repository(PostgreSQLRepository)`
  - **Purpose**: Safe SQL operations for h3 schema using psycopg.sql composition
  - **Inheritance**: Extends `PostgreSQLRepository` (connection mgmt, transactions, error handling)
  - **Schema**: `'h3'` (passed to parent constructor)
  - **Methods to implement**:
    ```python
    class H3Repository(PostgreSQLRepository):
        """
        H3-specific repository for h3.grids operations.

        Inherits connection management and safe SQL composition from
        PostgreSQLRepository. All queries use sql.Identifier() for
        injection prevention.
        """

        def __init__(self):
            # Initialize with h3 schema
            super().__init__(schema_name='h3')

        def insert_h3_cells(
            self,
            cells: List[Dict[str, Any]],
            grid_id: str,
            grid_type: str = 'land'
        ) -> int:
            """
            Bulk insert H3 cells using safe SQL composition.

            Uses executemany() for batch insertion and sql.Identifier()
            for schema/table names to prevent SQL injection.
            """
            pass

        def get_parent_ids(self, grid_id: str) -> List[Tuple[int, Optional[int]]]:
            """
            Load parent H3 indices for a grid.

            Returns: List of (h3_index, parent_res2) tuples
            """
            pass

        def update_spatial_attributes(
            self,
            grid_id: str,
            spatial_filter_table: str = 'geo.countries'
        ) -> int:
            """
            Update country_code and is_land via spatial join.

            Uses ST_Intersects to find which cells intersect countries.
            """
            pass

        def get_cell_count(self, grid_id: str) -> int:
            """Count cells for a grid_id."""
            pass

        def grid_exists(self, grid_id: str) -> bool:
            """Check if grid_id exists (for idempotency)."""
            pass

        def insert_reference_filter(
            self,
            filter_name: str,
            resolution: int,
            h3_indices: List[int]
        ) -> bool:
            """
            Insert to h3.reference_filters table.

            Stores parent H3 indices as BIGINT[] array.
            """
            pass

        def get_reference_filter(self, filter_name: str) -> Optional[List[int]]:
            """
            Load h3_indices_array from h3.reference_filters.

            Returns: List of parent H3 indices
            """
            pass

        def update_grid_metadata(
            self,
            grid_id: str,
            cell_count: int,
            status: str,
            job_id: str
        ) -> None:
            """Update h3.grid_metadata for bootstrap tracking."""
            pass
    ```
  - **Key Implementation Details**:
    - All SQL uses `sql.SQL()` and `sql.Identifier()` for safety
    - Use `self._get_connection()` context manager from parent
    - Use `self._execute_query()` helper from parent (if available)
    - All methods log operations using inherited logger
    - Handle PostgreSQL-specific types (BIGINT[], GEOMETRY)

  - **Example Safe SQL Pattern**:
    ```python
    # SAFE: sql.Identifier() prevents injection
    query = sql.SQL("""
        INSERT INTO {schema}.{table}
            (h3_index, resolution, geom, grid_id, grid_type,
             parent_res2, parent_h3_index, source_job_id)
        VALUES
            (%s, %s, ST_GeomFromText(%s, 4326), %s, %s, %s, %s, %s)
        ON CONFLICT (h3_index, grid_id) DO NOTHING
    """).format(
        schema=sql.Identifier('h3'),
        table=sql.Identifier('grids')
    )

    # UNSAFE (DO NOT DO THIS):
    # query = f"INSERT INTO {schema}.{table} ..."  # ❌ SQL injection risk!
    ```

- [x] **Update `sql/init/02_create_h3_grids_table.sql`** ✅ COMPLETED (10 NOV 2025) - Migrated to h3.grids with parent tracking
  ```sql
  -- Change ALL instances of geo.h3_grids to h3.grids
  -- Original: CREATE TABLE geo.h3_grids
  -- New:      CREATE TABLE h3.grids

  CREATE TABLE IF NOT EXISTS h3.grids (
      id SERIAL PRIMARY KEY,

      -- H3 Identification
      h3_index BIGINT NOT NULL,
      resolution INTEGER NOT NULL,

      -- Geometry
      geom GEOMETRY(Polygon, 4326) NOT NULL,

      -- Grid Metadata
      grid_id VARCHAR(255) NOT NULL,
      grid_type VARCHAR(50) NOT NULL,

      -- Parent Tracking (NEW - for hierarchical queries & partition routing)
      parent_res2 BIGINT,           -- Top-level parent (for GeoParquet partitioning)
      parent_h3_index BIGINT,       -- Immediate parent (for hierarchical traversal)

      -- Source Information
      source_job_id VARCHAR(255),
      source_blob_path TEXT,

      -- Classification (for land grids)
      is_land BOOLEAN DEFAULT NULL,
      land_percentage DECIMAL(5,2) DEFAULT NULL,

      -- Administrative Attributes (from spatial filtering)
      country_code VARCHAR(3),
      admin_level_1 VARCHAR(255),

      -- Timestamps
      created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
      updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

      -- Constraints
      CONSTRAINT h3_grids_unique_cell UNIQUE (h3_index, grid_id),
      CONSTRAINT h3_grids_resolution_check CHECK (resolution >= 0 AND resolution <= 15),
      CONSTRAINT h3_grids_land_pct_check CHECK (land_percentage IS NULL OR (land_percentage >= 0 AND land_percentage <= 100))
  );

  -- Spatial index (GIST) for fast spatial queries
  CREATE INDEX IF NOT EXISTS idx_h3_grids_geom ON h3.grids USING GIST(geom);

  -- B-tree index for H3 index lookups
  CREATE INDEX IF NOT EXISTS idx_h3_grids_h3_index ON h3.grids (h3_index);

  -- Index for resolution filtering
  CREATE INDEX IF NOT EXISTS idx_h3_grids_resolution ON h3.grids (resolution);

  -- Index for grid filtering
  CREATE INDEX IF NOT EXISTS idx_h3_grids_grid_id ON h3.grids (grid_id);

  -- NEW: Parent tracking indexes
  CREATE INDEX IF NOT EXISTS idx_h3_grids_parent_res2 ON h3.grids (parent_res2);
  CREATE INDEX IF NOT EXISTS idx_h3_grids_parent_index ON h3.grids (parent_h3_index);

  -- NEW: Composite index for GeoParquet export (partition routing + sorting)
  CREATE INDEX IF NOT EXISTS idx_h3_grids_parent_res2_h3_index ON h3.grids (parent_res2, h3_index);

  -- Partial indexes (unchanged)
  CREATE INDEX IF NOT EXISTS idx_h3_grids_is_land ON h3.grids (is_land) WHERE is_land IS NOT NULL;
  CREATE INDEX IF NOT EXISTS idx_h3_grids_country ON h3.grids (country_code) WHERE country_code IS NOT NULL;
  CREATE INDEX IF NOT EXISTS idx_h3_grids_grid_resolution ON h3.grids (grid_id, resolution);

  -- Table and column comments (update table name)
  COMMENT ON TABLE h3.grids IS 'H3 hexagonal grid cells (resolutions 2-7) for World Bank Agricultural Geography Platform. System-generated, read-only.';
  COMMENT ON COLUMN h3.grids.parent_res2 IS 'Top-level resolution 2 parent (for GeoParquet partition routing)';
  COMMENT ON COLUMN h3.grids.parent_h3_index IS 'Immediate parent H3 index (for hierarchical traversal)';

  -- Grant permissions
  GRANT SELECT, INSERT, UPDATE, DELETE ON h3.grids TO rob634;
  GRANT USAGE, SELECT ON SEQUENCE h3.grids_id_seq TO rob634;
  ```

- [x] **Create `sql/init/04_create_h3_reference_filters_table.sql`** ✅ COMPLETED (10 NOV 2025) - Stores parent ID arrays for cascade
  ```sql
  -- ============================================================================
  -- H3 REFERENCE FILTERS - Parent ID sets for child generation
  -- ============================================================================
  -- PURPOSE: Store filtered H3 parent indices (e.g., land_res2) for cascading children
  -- SCHEMA: h3 (system data)
  -- CREATED: 10 NOV 2025
  -- ============================================================================

  CREATE TABLE IF NOT EXISTS h3.reference_filters (
      id SERIAL PRIMARY KEY,
      filter_name VARCHAR(100) UNIQUE NOT NULL,  -- e.g., 'land_res2'
      resolution INTEGER NOT NULL CHECK (resolution BETWEEN 0 AND 4),
      h3_indices_array BIGINT[] NOT NULL,        -- Array of parent H3 indices
      cell_count INTEGER NOT NULL,
      spatial_filter_sql TEXT,                   -- SQL used to generate filter
      created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
      updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
  );

  -- Index for fast filter lookups
  CREATE INDEX IF NOT EXISTS idx_h3_ref_filters_name ON h3.reference_filters(filter_name);

  -- GIN index for array operations (if needed for complex queries)
  CREATE INDEX IF NOT EXISTS idx_h3_ref_indices_gin ON h3.reference_filters USING GIN(h3_indices_array);

  -- Table comment
  COMMENT ON TABLE h3.reference_filters IS 'Reference H3 parent indices for cascading child generation (e.g., land_res2 parents for generating res 3-7)';

  -- Column comments
  COMMENT ON COLUMN h3.reference_filters.filter_name IS 'Unique filter identifier (e.g., land_res2, usa_res3)';
  COMMENT ON COLUMN h3.reference_filters.h3_indices_array IS 'PostgreSQL array of H3 parent indices (BIGINT[])';
  COMMENT ON COLUMN h3.reference_filters.spatial_filter_sql IS 'SQL query used to generate filter (for reproducibility)';

  -- Grant permissions
  GRANT SELECT, INSERT, UPDATE, DELETE ON h3.reference_filters TO rob634;
  GRANT USAGE, SELECT ON SEQUENCE h3.reference_filters_id_seq TO rob634;
  ```

- [x] **Create `sql/init/06_create_h3_grid_metadata_table.sql`** ✅ COMPLETED (10 NOV 2025) - Bootstrap status and statistics tracking
  ```sql
  -- ============================================================================
  -- H3 GRID METADATA - Track pyramid bootstrap progress and status
  -- ============================================================================
  -- PURPOSE: Monitor H3 grid generation status, cell counts, and completion
  -- SCHEMA: h3 (system data)
  -- CREATED: 10 NOV 2025
  -- ============================================================================

  CREATE TABLE IF NOT EXISTS h3.grid_metadata (
      id SERIAL PRIMARY KEY,
      grid_id VARCHAR(100) UNIQUE NOT NULL,      -- e.g., 'land_res2', 'land_res6'
      resolution INTEGER NOT NULL CHECK (resolution BETWEEN 2 AND 7),
      parent_grid_id VARCHAR(100),               -- e.g., 'land_res5' for 'land_res6'
      cell_count BIGINT,
      bbox GEOMETRY(Polygon, 4326),
      generation_status VARCHAR(50),             -- 'complete', 'in_progress', 'failed'
      generation_job_id VARCHAR(255),            -- CoreMachine job ID
      created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
      updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
  );

  -- Index for fast status lookups
  CREATE INDEX IF NOT EXISTS idx_h3_grid_metadata_grid_id ON h3.grid_metadata(grid_id);
  CREATE INDEX IF NOT EXISTS idx_h3_grid_metadata_status ON h3.grid_metadata(generation_status);

  -- Table comment
  COMMENT ON TABLE h3.grid_metadata IS 'Metadata and status tracking for H3 grid pyramid bootstrap process';

  -- Column comments
  COMMENT ON COLUMN h3.grid_metadata.grid_id IS 'Unique grid identifier (e.g., land_res2, land_res6)';
  COMMENT ON COLUMN h3.grid_metadata.parent_grid_id IS 'Parent grid ID for hierarchical relationship tracking';
  COMMENT ON COLUMN h3.grid_metadata.generation_status IS 'Bootstrap status: complete, in_progress, failed';

  -- Grant permissions
  GRANT SELECT, INSERT, UPDATE, DELETE ON h3.grid_metadata TO rob634;
  GRANT USAGE, SELECT ON SEQUENCE h3.grid_metadata_id_seq TO rob634;
  ```

- [ ] **Deploy schema updates to PostgreSQL** (NEXT STEP - run after all schemas created)
  ```bash
  # CRITICAL: Run 00_create_h3_schema.sql FIRST
  psql < sql/init/00_create_h3_schema.sql

  # Then create tables in h3 schema
  psql < sql/init/02_create_h3_grids_table.sql
  psql < sql/init/04_create_h3_reference_filters_table.sql
  psql < sql/init/06_create_h3_grid_metadata_table.sql
  ```

- [ ] **Verify schema deployment**
  ```sql
  -- Check all tables exist in h3 schema
  SELECT table_name
  FROM information_schema.tables
  WHERE table_schema = 'h3'
  ORDER BY table_name;

  -- Expected result:
  -- grids
  -- grid_metadata
  -- reference_filters

  -- Check columns on h3.grids
  SELECT column_name, data_type
  FROM information_schema.columns
  WHERE table_schema='h3' AND table_name='grids'
  AND column_name IN ('parent_res2', 'parent_h3_index');

  -- Should return both columns with type 'bigint'
  ```

---

### Phase 2: Resolution 2 Bootstrap Handler

**Goal**: Generate global res 2 grid and apply spatial filtering (one-time spatial ops)
**Time**: 2 hours

#### Tasks

- [ ] **Create `services/handler_bootstrap_res2_spatial_filter.py`**
  - **Function**: `bootstrap_res2_with_spatial_filter(task_params: dict) -> dict`
  - **Inputs**:
    - `resolution`: 2 (fixed)
    - `grid_id`: 'land_res2'
    - `filter_name`: 'land_res2'
    - `spatial_filter_table`: 'geo.countries' (NOTE: countries stay in geo schema)
  - **Logic**:
    1. Generate global res 2 grid (5,882 cells) using h3-py
    2. Stream to **`h3.grids`** with `grid_id='land_res2'`
    3. Query `geo.countries` for all country geometries (spatial filter source)
    4. For each H3 cell: `ST_Intersects(h3_cell.geom, country.geom)`
    5. Update `country_code`, `is_land=TRUE` for intersecting cells
    6. Extract land cell IDs: `SELECT h3_index FROM h3.grids WHERE is_land=TRUE`
    7. Insert to **`h3.reference_filters`**:
       - `filter_name='land_res2'`
       - `h3_indices_array=ARRAY[land_cell_ids]`
       - `cell_count=COUNT(*)`
    8. Update **`h3.grid_metadata`** with cell count and status
  - **Key SQL Updates** (change `geo.h3_*` to `h3.*`):
    ```python
    # INSERT statement
    stmt = """
        INSERT INTO h3.grids (h3_index, resolution, geom, grid_id, grid_type, source_job_id)
        VALUES (%s, %s, ST_GeomFromText(%s, 4326), %s, %s, %s)
        ON CONFLICT (h3_index, grid_id) DO NOTHING
    """

    # UPDATE for spatial attribution
    update_stmt = """
        UPDATE h3.grids h
        SET country_code = c.iso3, is_land = TRUE
        FROM geo.countries c
        WHERE h.grid_id = 'land_res2'
          AND ST_Intersects(h.geom, c.geom)
    """

    # INSERT to reference_filters
    insert_filter = """
        INSERT INTO h3.reference_filters (filter_name, resolution, h3_indices_array, cell_count)
        SELECT
            %s,
            %s,
            array_agg(h3_index),
            count(*)
        FROM h3.grids
        WHERE grid_id = 'land_res2' AND is_land = TRUE
    """
    ```
  - **Output**:
    ```json
    {
      "success": true,
      "result": {
        "grid_id": "land_res2",
        "schema": "h3",
        "table": "h3.grids",
        "total_cells": 5882,
        "land_cells": 2847,
        "ocean_cells": 3035,
        "filter_name": "land_res2",
        "processing_time_seconds": 900
      }
    }
    ```
  - **Performance**: ~15 minutes (one-time spatial ops acceptable)
  - **Idempotency**: Check if `land_res2` already exists in `h3.grid_metadata`, skip if complete

- [ ] **Register handler in `services/__init__.py`**
  ```python
  from .handler_bootstrap_res2_spatial_filter import bootstrap_res2_with_spatial_filter

  ALL_HANDLERS = {
      # ...existing handlers...
      "bootstrap_res2_with_spatial_filter": bootstrap_res2_with_spatial_filter,
  }
  ```

- [ ] **Add comprehensive logging**
  - Log start of each substep (generate, spatial filter, extract)
  - Log progress every 1,000 cells during spatial intersection
  - Log final cell counts (total, land, ocean)
  - Log filter insertion to `h3.reference_filters`
  - Log schema name in all messages: "Inserting to h3.grids..."

- [ ] **Add error handling**
  - Handle missing `h3` schema (fail early: "h3 schema does not exist - run 00_create_h3_schema.sql first")
  - Handle missing `geo.countries` table (fail early with clear message)
  - Handle PostgreSQL connection failures (retry logic)
  - Handle h3-py import errors (dependency check)
  - Rollback on failure (delete partial inserts from `h3.grids`)

---

### Phase 3: Cascading Children Handler

**Goal**: Generate children for any parent resolution (res 3-7), no spatial ops
**Time**: 2 hours

#### Tasks

- [ ] **Create `services/handler_generate_h3_children_batch.py`**
  - **Function**: `generate_h3_children_batch(task_params: dict) -> dict`
  - **Inputs**:
    - `parent_batch`: List[int] - Parent H3 indices for this batch
    - `parent_resolution`: int (2-6)
    - `target_resolution`: int (3-7)
    - `grid_id`: str (e.g., 'land_res3')
    - `parent_grid_id`: str (e.g., 'land_res2')
  - **Logic**:
    1. Query parent metadata from **`h3.grids`** WHERE `grid_id=parent_grid_id`
       - Get `parent_res2` for each parent (to propagate to children)
    2. For each parent H3 index in batch:
       - `children = h3.cell_to_children(parent, target_resolution)`
       - Generate geometry for each child (7 children per parent)
       - Build row: `(h3_index, resolution, geom, grid_id, parent_res2, parent_h3_index)`
    3. Batch insert to **`h3.grids`** using `infrastructure.database_utils.batched_executemany()`
       - Batch size: 1000 rows (dynamic based on geometry complexity)
       - `ON CONFLICT (h3_index, grid_id) DO NOTHING` for idempotency
  - **Key SQL Updates** (change `geo.h3_grids` to `h3.grids`):
    ```python
    # Query parents for metadata
    query_parents = """
        SELECT h3_index, parent_res2
        FROM h3.grids
        WHERE grid_id = %s
          AND h3_index = ANY(%s)
    """

    # INSERT children
    insert_stmt = """
        INSERT INTO h3.grids
            (h3_index, resolution, geom, grid_id, grid_type,
             parent_res2, parent_h3_index, source_job_id)
        VALUES
            (%s, %s, ST_GeomFromText(%s, 4326), %s, %s, %s, %s, %s)
        ON CONFLICT (h3_index, grid_id) DO NOTHING
    """
    ```
  - **Output**:
    ```json
    {
      "success": true,
      "result": {
        "grid_id": "land_res3",
        "schema": "h3",
        "table": "h3.grids",
        "parent_count": 100,
        "children_generated": 700,
        "rows_inserted": 700,
        "processing_time_seconds": 480
      }
    }
    ```
  - **Performance**: ~6-8 minutes per batch (well under 10 min timeout)
  - **Key Feature**: NO spatial operations (pure H3 math + geometry generation)

- [ ] **Implement parent_res2 propagation logic**
  - Query parent rows to get their `parent_res2` values
  - Build mapping: `Dict[parent_h3_index, parent_res2]`
  - Pass `parent_res2` from parent to all children
  - For res 3 children: `parent_res2 = parent's h3_index` (parent IS res 2)
  - For res 4+ children: `parent_res2 = parent's parent_res2` (inherited)

- [ ] **Add batch size calculation helper**
  ```python
  def calculate_optimal_batch_size(target_resolution: int) -> int:
      """
      Calculate parents per batch to keep task time <10 min.

      Target: 2M cells per batch, adjusted by resolution.
      Higher resolutions = slower geometry generation.
      """
      children_per_parent = 7
      target_cells_per_batch = 2_000_000
      parents_per_batch = target_cells_per_batch // children_per_parent

      scaling_factors = {3: 1.0, 4: 0.9, 5: 0.8, 6: 0.7, 7: 0.6}
      factor = scaling_factors.get(target_resolution, 0.7)

      return max(100, int(parents_per_batch * factor))
  ```

- [ ] **Register handler in `services/__init__.py`**
  ```python
  from .handler_generate_h3_children_batch import generate_h3_children_batch

  ALL_HANDLERS = {
      # ...existing handlers...
      "generate_h3_children_batch": generate_h3_children_batch,
  }
  ```

- [ ] **Add comprehensive logging**
  - Log batch start (parent count, target resolution, schema: h3)
  - Log progress every 10,000 children generated
  - Log insertion metrics (rows inserted, conflicts, time)
  - Log parent_res2 propagation for verification

---

### Phase 4: Bootstrap Job Definition

**Goal**: Orchestrate 7-stage cascade job (res 2→7)
**Time**: 2 hours

#### Tasks

- [ ] **Create `jobs/bootstrap_h3_land_grid_pyramid.py`**
  - **Job metadata**:
    - `job_type = "bootstrap_h3_land_grid_pyramid"`
    - `description = "Generate hierarchical land-only H3 grid (res 2-7) in h3 schema"`
    - `total_stages = 7`
  - **Parameters schema**:
    ```python
    {
        "resolutions": {
            "type": "list",
            "default": [2, 3, 4, 5, 6, 7],
            "description": "Resolutions to generate (must be sequential)"
        },
        "spatial_filter_table": {
            "type": "str",
            "default": "geo.countries",
            "description": "Table for res 2 spatial filtering (in geo schema)"
        },
        "target_schema": {
            "type": "str",
            "default": "h3",
            "description": "Target schema for H3 grids (always 'h3')"
        }
    }
    ```

- [ ] **Implement stage definitions**
  ```python
  stages = [
      {
          "number": 1,
          "name": "bootstrap_res2",
          "task_type": "bootstrap_res2_with_spatial_filter",
          "parallelism": "single",
          "description": "Generate res 2 + spatial filter in h3.grids (~15 min)"
      },
      {
          "number": 2,
          "name": "generate_res3",
          "task_type": "generate_h3_children_batch",
          "parallelism": "fan_out",
          "description": "Generate res 3 from res 2 parents in h3.grids (~20 min)"
      },
      # ... stages 3-6 similar (res 4-7)
      {
          "number": 7,
          "name": "finalize_pyramid",
          "task_type": "finalize_h3_pyramid",
          "parallelism": "single",
          "description": "Create indexes, STAC metadata, verify counts in h3 schema"
      }
  ]
  ```

- [ ] **Implement `create_tasks_for_stage()` method**
  - **Stage 1**: Single task for res 2 generation + spatial filter
  - **Stages 2-6**: Fan-out tasks
    1. Query parent IDs from previous resolution in **`h3.grids`**
    2. Calculate batch size for target resolution
    3. Chunk parent IDs into batches
    4. Create one task per batch
  - **Stage 7**: Single finalization task
  - **Key logic**: Dynamic batch sizing based on target resolution
  - **SQL Update**: Change `FROM geo.h3_grids` to `FROM h3.grids`

- [ ] **Implement helper function: `load_parent_ids_from_db()`**
  ```python
  def load_parent_ids_from_db(parent_grid_id: str) -> List[Tuple[int, int]]:
      """
      Load all H3 indices for a given grid_id from h3.grids.

      Used by stages 2-6 to get parent IDs for child generation.
      """
      from infrastructure.postgis import get_postgis_connection

      with get_postgis_connection() as conn:
          with conn.cursor() as cur:
              cur.execute("""
                  SELECT h3_index, parent_res2
                  FROM h3.grids
                  WHERE grid_id = %s
                  ORDER BY h3_index
              """, (parent_grid_id,))

              rows = cur.fetchall()
              return [(row[0], row[1]) for row in rows]
  ```

- [ ] **Implement `validate_job_parameters()` method**
  - Verify **`h3` schema exists** (CRITICAL - fail early if missing)
  - Verify `geo.countries` table exists
  - Verify resolutions are sequential (2, 3, 4, 5, 6, 7)
  - Check if pyramid already exists (fail if `land_res2` complete in `h3.grid_metadata`)

- [ ] **Implement `finalize_job()` method**
  - Extract cell counts from each stage
  - Verify against expected counts (2,847 × 7^(n-2))
  - Build comprehensive result summary:
    ```json
    {
      "pyramid_complete": true,
      "schema": "h3",
      "resolutions": {
        "2": {"cell_count": 2847, "status": "complete"},
        "3": {"cell_count": 19929, "status": "complete"},
        "4": {"cell_count": 139503, "status": "complete"},
        "5": {"cell_count": 976521, "status": "complete"},
        "6": {"cell_count": 6835647, "status": "complete"},
        "7": {"cell_count": 47849529, "status": "complete"}
      },
      "total_cells": 55824976,
      "execution_time_hours": 18.5
    }
    ```

- [ ] **Register job in `jobs/__init__.py`**
  ```python
  from .bootstrap_h3_land_grid_pyramid import BootstrapH3LandGridPyramidJob

  ALL_JOBS = {
      # ...existing jobs...
      "bootstrap_h3_land_grid_pyramid": BootstrapH3LandGridPyramidJob,
  }
  ```

---

### Phase 5: Finalization Handler

**Goal**: Create indexes, STAC metadata, verify pyramid in h3 schema
**Time**: 1 hour

#### Tasks

- [ ] **Create `services/handler_finalize_h3_pyramid.py`**
  - **Function**: `finalize_h3_pyramid(task_params: dict) -> dict`
  - **Logic**:
    1. Create materialized view for fast parent lookups (optional)
    2. Verify cell counts match expectations at each resolution
    3. Calculate bbox for each resolution grid from **`h3.grids`**
    4. Update **`h3.grid_metadata`** with final status
    5. Create STAC collection for H3 pyramid (optional)
    6. Run VACUUM ANALYZE on **`h3.grids`** table
  - **SQL Updates**: Change all `geo.h3_*` to `h3.*`
  - **Performance**: ~30 minutes

- [ ] **Register handler in `services/__init__.py`**

---

### Phase 6: Bootstrap Status Endpoint

**Goal**: Query bootstrap progress via REST API
**Time**: 1 hour

#### Tasks

- [ ] **Create `triggers/trigger_h3_bootstrap_status.py`**
  - **Endpoint**: `GET /api/h3/bootstrap/status`
  - **Logic**:
    1. Query **`h3.grid_metadata`** for all resolutions
    2. Check if **`h3.reference_filters.land_res2`** exists
    3. Count cells in each `land_res{N}` grid from **`h3.grids`**
    4. Calculate completion percentage
  - **SQL Updates**: Change all `geo.h3_*` to `h3.*`
  - **Response**:
    ```json
    {
      "bootstrap_complete": false,
      "progress_percent": 57,
      "schema": "h3",
      "reference_grids": {
        "land_res2": {
          "status": "complete",
          "total_cells": 5882,
          "land_cells": 2847,
          "ocean_cells": 3035,
          "table": "h3.grids"
        }
      },
      "reference_filters": {
        "land_res2": {
          "status": "complete",
          "parent_count": 2847,
          "table": "h3.reference_filters"
        }
      },
      "production_grids": {
        "land_res3": {"status": "complete", "cell_count": 19929},
        "land_res4": {"status": "complete", "cell_count": 139503},
        "land_res5": {"status": "in_progress", "cell_count": 450000},
        "land_res6": {"status": "not_started", "cell_count": null},
        "land_res7": {"status": "not_started", "cell_count": null}
      },
      "current_job_id": "abc123...",
      "estimated_time_remaining_hours": 12
    }
    ```

- [ ] **Register endpoint in `function_app.py`**

---

### Phase 7: Testing & Deployment

**Goal**: Deploy and execute bootstrap, verify results in h3 schema
**Time**: 2 hours setup + 15-20 hours execution

#### Pre-Deployment Tasks

- [ ] **CRITICAL: Verify h3 schema exists**
  ```sql
  SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'h3';
  -- If not exists, run: psql < sql/init/00_create_h3_schema.sql
  ```

- [ ] **Verify prerequisite: `geo.countries` table exists**
  - If not, run ingest_vector job to load Natural Earth countries
  - Verify spatial index: `idx_countries_geom` exists on `geo.countries`
  - Verify data: `SELECT COUNT(*) FROM geo.countries` (~250 countries)

- [ ] **Deploy SQL schemas to PostgreSQL**
  ```bash
  # CRITICAL: Run in order
  psql < sql/init/00_create_h3_schema.sql              # Create h3 schema FIRST
  psql < sql/init/02_create_h3_grids_table.sql         # Create h3.grids
  psql < sql/init/04_create_h3_reference_filters_table.sql  # Create h3.reference_filters
  psql < sql/init/06_create_h3_grid_metadata_table.sql      # Create h3.grid_metadata
  ```

- [ ] **Deploy to Azure Functions**
  ```bash
  func azure functionapp publish rmhgeoapibeta --python --build remote
  ```

- [ ] **Verify health endpoint**
  ```bash
  curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health
  ```

#### Bootstrap Execution Tasks

- [ ] **Submit bootstrap job**
  ```bash
  curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/bootstrap_h3_land_grid_pyramid \
    -H "Content-Type: application/json" \
    -d '{
      "resolutions": [2, 3, 4, 5, 6, 7],
      "spatial_filter_table": "geo.countries",
      "target_schema": "h3"
    }'
  ```

- [ ] **Monitor job progress**
  ```bash
  # Get job status
  curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}

  # Get bootstrap status
  curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/h3/bootstrap/status
  ```

- [ ] **Monitor Azure Function logs**
  ```bash
  # Use Application Insights query script
  /tmp/query_ai.sh

  # Filter for bootstrap job
  traces | where timestamp >= ago(1h)
         | where message contains "bootstrap" or message contains "h3.grids"
         | order by timestamp desc
  ```

#### Verification Tasks

- [ ] **Verify cell counts at each resolution in h3.grids**
  ```sql
  SELECT
      grid_id,
      resolution,
      COUNT(*) as cell_count
  FROM h3.grids
  WHERE grid_id LIKE 'land_res%'
  GROUP BY grid_id, resolution
  ORDER BY resolution;

  -- Expected results:
  -- land_res2 | 2 | 2847
  -- land_res3 | 3 | 19929
  -- land_res4 | 4 | 139503
  -- land_res5 | 5 | 976521
  -- land_res6 | 6 | 6835647
  -- land_res7 | 7 | 47849529
  ```

- [ ] **Verify parent_res2 propagation**
  ```sql
  -- All cells should have parent_res2 populated
  SELECT
      resolution,
      COUNT(*) as total_cells,
      COUNT(parent_res2) as cells_with_parent,
      COUNT(*) - COUNT(parent_res2) as missing_parent
  FROM h3.grids
  WHERE grid_id LIKE 'land_res%'
  GROUP BY resolution
  ORDER BY resolution;

  -- missing_parent should be 0 for all resolutions (except res 2 where parent_res2 = h3_index)
  ```

- [ ] **Verify parent-child relationships**
  ```sql
  -- Pick random res 6 cell, verify it has valid res 5 parent
  WITH sample AS (
      SELECT h3_index, parent_h3_index, parent_res2
      FROM h3.grids
      WHERE grid_id = 'land_res6'
      LIMIT 1
  )
  SELECT
      s.h3_index as child_res6,
      s.parent_h3_index as parent_res5,
      p.h3_index as parent_exists_in_db,
      s.parent_res2,
      p.parent_res2 as parent_res2_matches
  FROM sample s
  LEFT JOIN h3.grids p
      ON p.h3_index = s.parent_h3_index
      AND p.grid_id = 'land_res5';

  -- parent_exists_in_db should equal parent_res5
  -- parent_res2_matches should equal parent_res2
  ```

- [ ] **Test spatial query performance**
  ```sql
  -- Query: Get all res 6 cells intersecting Tanzania
  EXPLAIN ANALYZE
  SELECT COUNT(*)
  FROM h3.grids h
  JOIN geo.countries c ON c.iso3 = 'TZA'
  WHERE h.grid_id = 'land_res6'
    AND ST_Intersects(h.geom, c.geom);

  -- Should use spatial index (idx_h3_grids_geom)
  -- Execution time should be <5 seconds
  ```

- [ ] **Verify H3 index spatial sorting**
  ```sql
  -- Sample 100 cells from res 6, verify h3_index sorting
  SELECT
      h3_index,
      ST_X(ST_Centroid(geom)) as lon,
      ST_Y(ST_Centroid(geom)) as lat
  FROM h3.grids
  WHERE grid_id = 'land_res6'
  ORDER BY h3_index
  LIMIT 100;

  -- Visually inspect: adjacent h3_index values should have similar lon/lat
  -- (Confirms H3 spatial locality property)
  ```

- [ ] **Verify schema separation (h3 vs geo)**
  ```sql
  -- Check tables in h3 schema
  SELECT table_name FROM information_schema.tables WHERE table_schema = 'h3';
  -- Expected: grids, grid_metadata, reference_filters

  -- Check tables in geo schema
  SELECT table_name FROM information_schema.tables WHERE table_schema = 'geo' AND table_name = 'countries';
  -- Expected: countries (and user tables)

  -- Verify NO h3_* tables in geo schema
  SELECT table_name FROM information_schema.tables WHERE table_schema = 'geo' AND table_name LIKE 'h3_%';
  -- Expected: 0 rows (all H3 tables should be in h3 schema)
  ```

---

### Phase 8: GeoParquet Export (Post-Bootstrap)

**Goal**: Export grid to spatially-sorted Parquet files (separate job, run after bootstrap)
**Time**: TBD (future implementation)
**Status**: ⏳ **PLANNED** (not part of initial bootstrap)

#### Tasks (Future)

- [ ] Create separate job: `export_h3_grid_to_parquet`
- [ ] Query by `parent_res2` for partitioning from **`h3.grids`**
- [ ] Export one Parquet file per parent_res2
- [ ] Sort by `h3_index` for spatial locality
- [ ] Compress with zstd
- [ ] Upload to Azure Blob Storage
- [ ] Create STAC catalog entries for Parquet files

---

## Bootstrap Execution Timeline

**Total Time Estimate**: 15-20 hours (automated, can run overnight)

| Stage | Resolution | Cell Count | Batches | Time/Batch | Total Time | Can Parallelize? |
|-------|-----------|-----------|---------|------------|------------|------------------|
| 1 | 2 (reference) | 2,847 | 1 | 15 min | **15 min** | No (single task) |
| 2 | 3 | 19,929 | 1 | 20 min | **20 min** | No (1 batch) |
| 3 | 4 | 139,503 | 1 | 30 min | **30 min** | No (1 batch) |
| 4 | 5 | 976,521 | 5 | 20 min | **1.5 hours** | Yes (5 tasks) |
| 5 | 6 | 6,835,647 | 35 | 10 min | **3.5 hours** | Yes (35 tasks) |
| 6 | 7 | 47,849,529 | 280 | 8 min | **12 hours** | Yes (280 tasks) |
| 7 | Finalize | - | 1 | 30 min | **30 min** | No (single task) |

**TOTAL**: ~18 hours (can parallelize stages 4-6 if resources available)

**Critical Path**:
- Stages 1-3 must run sequentially (each needs previous stage's output)
- Stages 4-6 can parallelize within themselves (fan-out tasks)
- Stage 7 must wait for Stage 6 completion

**Optimization Notes**:
- If `maxConcurrentCalls > 1`, stages 4-6 can run multiple tasks simultaneously
- Current setting: `maxConcurrentCalls = 1` (must change for faster bootstrap)
- Recommendation: Set to 10-20 during bootstrap, revert to 1 after completion

---

## Success Criteria

- ✅ **h3 schema created** and isolated from geo schema (system data vs user data)
- ✅ Complete land grid pyramid res 2-7 in **`h3.grids`** (~55.8M cells total)
- ✅ ~30% of global cells at each level (land only, avoids open ocean)
- ✅ `parent_res2` populated for all cells (enables partition routing for GeoParquet)
- ✅ `parent_h3_index` tracks immediate parent (enables hierarchical queries)
- ✅ Spatially sorted by `h3_index` (ready for Parquet export with spatial locality)
- ✅ Idempotent design (re-running safe, uses ON CONFLICT DO NOTHING)
- ✅ Fast spatial queries: "Get all res 6 cells for Tanzania" completes in <5 seconds
- ✅ Bootstrap status endpoint shows progress in real-time
- ✅ Cell counts match expectations at each resolution level
- ✅ Parent-child relationships verified (sample queries confirm linkage)
- ✅ Schema separation verified: `h3.*` tables exist, no `h3_*` tables in `geo` schema

---

## Rollback Plan (If Bootstrap Fails)

**Partial failure recovery**:
```sql
-- Check which resolutions completed
SELECT grid_id, generation_status, cell_count
FROM h3.grid_metadata
WHERE grid_id LIKE 'land_res%';

-- Delete incomplete resolution
DELETE FROM h3.grids WHERE grid_id = 'land_res6';
DELETE FROM h3.grid_metadata WHERE grid_id = 'land_res6';

-- Restart job from failed stage
-- Job will skip completed stages (idempotent design)
```

**Full rollback** (nuclear option):
```sql
-- Delete all bootstrap data (keeps h3 schema structure)
DELETE FROM h3.grids WHERE grid_id LIKE 'land_res%';
DELETE FROM h3.reference_filters WHERE filter_name = 'land_res2';
DELETE FROM h3.grid_metadata WHERE grid_id LIKE 'land_res%';

-- Restart bootstrap job from scratch
```

**Nuclear option** (complete schema reset):
```sql
-- Drop entire h3 schema and recreate
DROP SCHEMA h3 CASCADE;

-- Re-run schema creation scripts
-- psql < sql/init/00_create_h3_schema.sql
-- psql < sql/init/02_create_h3_grids_table.sql
-- ... etc
```

---

## Post-Bootstrap Next Steps

**After bootstrap completes successfully**:

1. **Revert `maxConcurrentCalls` to 1** (critical for raster memory safety)
   ```json
   // host.json
   "maxConcurrentCalls": 1  // Revert from temporary higher value
   ```

2. **Export to GeoParquet** (separate job, future implementation)
   - One Parquet file per parent_res2
   - Sorted by h3_index for spatial locality
   - Compressed with zstd
   - Uploaded to Azure Blob Storage
   - Query from **`h3.grids`** for export

3. **Integrate with MapSPAM aggregation** (Phase 2 of H3-design.md)
   - Raster → H3 aggregation pipeline
   - Store crop data in time-series Parquet files
   - Partition by parent_res2 for efficient queries
   - Reference **`h3.grids`** for spatial joins

4. **Integrate with climate data** (Phase 3 of H3-design.md)
   - TerraClimate/ERA5 → H3 aggregation
   - Monthly time-series in Parquet
   - Partition by parent_res2 + time range
   - Reference **`h3.grids`** for spatial attribution

5. **Create API endpoints for H3 queries** (Phase 4 of H3-design.md)
   - Spatial queries via PostGIS (`FROM h3.grids`)
   - Attribute/temporal queries via DuckDB + Parquet
   - Two-stage query pattern implementation
   - Users query **`h3.grids`** (read-only access)

---

**END OF TODO SECTION**

---

## H3 Resolution Strategy

### Resolution Levels and Use Cases

| Resolution | Area per hex | Edge length | Width* | Use Case |
|------------|--------------|-------------|---------|----------|
| **2** | ~86,745 km² | ~158 km | ~274 km | Top-level filter, multiple metro areas per hex |
| **3** | ~12,393 km² | ~60 km | ~104 km | Continental modeling, metro area scale |
| **4** | ~1,770 km² | ~23 km | ~39 km | Regional patterns, city-scale aggregations |
| **5** | **~252 km²** | **~8.5 km** | **~15 km** | **Regional climate zones, major watersheds** |
| **6** | **~36 km²** | **~3.2 km** | **~5.6 km** | **Primary working resolution, matches 10km MapSPAM** |
| **7** | **~5.2 km²** | **~1.2 km** | **~2.1 km** | **Local variation, detailed habitat mapping** |
| 8 | ~0.74 km² | ~461 m | ~798 m | (Too fine for source data resolution) |

\* Width = distance between parallel edges = √3 × edge length

### Hierarchical Generation Strategy

1. **Level 2 as Top-Level Filter**
   - Polyfill all admin0 (country) boundaries at resolution 2
   - Accept ~30% false positives in littoral/EEZ waters to capture all islands and coastal zones
   - These res 2 IDs become the **parent set** (~2,000 hexes globally)

2. **Generate Children Only for Res 2 Parents**
   - Each res 2 hex → 7 res 3 hexes → 49 res 4 → 343 res 5 → 2,401 res 6 → 16,807 res 7
   - ~2,000 res 2 hexes × 16,807 = **~34 million res 7 hexes** (manageable)
   - Avoid generating hexes for open ocean

3. **Parent-Child Relationships**
   - H3 provides native hierarchical functions
   - Store parent_res2 ID in all child records for partition routing
   - Enable hierarchical aggregation (res 7 → res 6 → res 5)

---

## Data Sources and Features

### Core Datasets

**MapSPAM (IFPRI Spatial Production Allocation Model)**
- Resolution: 10km × 10km (5 arc-minutes)
- Temporal: 2010, 2017-SSA, 2020 (latest)
- Coverage: Global
- Crops: 46 individual crops
- Variables: Physical area (ha), harvested area (ha), production (mt), yield (kg/ha)
- Production systems: Irrigated, rainfed (high input, low input, subsistence in older versions)
- Source: https://mapspam.info, Harvard Dataverse
- **Key Value**: Answers 10 years of agriculture specialist questions about crop patterns, yields, intensification potential

**Topography (Copernicus DEM 30m or similar)**
- Mean elevation per hex
- Elevation range (max - min) for local relief
- Mean slope
- Slope standard deviation (terrain complexity indicator)
- Aspect diversity (optional, as northness/eastness components)

**Climate Data (TerraClimate or Planetary Computer)**
- Temporal: Monthly, 1958-present (TerraClimate at 4km)
- Variables:
  - Temperature: min, max, mean (monthly)
  - Precipitation: total (monthly)
  - Vapor Pressure Deficit (VPD)
  - Soil moisture
  - Potential evapotranspiration (PET)
- Derived bioclimatic variables:
  - Annual temperature range
  - Temperature seasonality
  - Precipitation seasonality
  - Warmest/coldest quarter temps
  - Wettest/driest quarter precipitation

**Vegetation/Land Cover**
- ESA WorldCover 10m or MODIS Land Cover
- Dominant class + diversity/fragmentation metrics per hex
- MODIS NDVI: seasonal means, annual max/min, growing season length

**Additional Layers (Optional)**
- Soil properties (SoilGrids if available)
- Distance to water (HydroSHEDS derived)
- Human modification index
- Solar radiation/insolation

### Aggregated Features per H3 Cell

**For MapSPAM (res 6-7 primarily)**
- Total cropland area
- Crop diversity index (Shannon or species richness)
- Dominant crop type + percentage of area
- Irrigated fraction
- Average yield by crop category
- Production intensity (tons/ha)

**For Climate (all resolutions, time-series)**
- Monthly aggregates: mean, min, max per hex
- Seasonal summaries
- Annual statistics
- Bioclimatic variable derivations

**For Topography (static, all resolutions)**
- Elevation: mean, min, max, std dev
- Slope: mean, max, std dev
- Terrain ruggedness or complexity metrics

---

## Architecture

### Storage Strategy: PostGIS + GeoParquet Two-Stage Pattern

**Why Two Systems?**
- **PostGIS**: Excels at spatial indexing, polygon intersections, bbox queries
- **GeoParquet**: Excels at columnar filtering, temporal ranges, massive time-series datasets
- **Use each for its strength**

### PostGIS: Spatial Index

**H3 Grid Tables** (one per resolution)
```sql
CREATE TABLE h3_grid_res6 (
    h3_id TEXT PRIMARY KEY,
    resolution INT,
    parent_res2 TEXT,
    geom GEOMETRY(POLYGON, 4326),
    centroid GEOMETRY(POINT, 4326)
);

CREATE INDEX idx_h3_geom ON h3_grid_res6 USING GIST(geom);
CREATE INDEX idx_h3_parent ON h3_grid_res6(parent_res2);
```

- Relatively small tables (millions of rows: IDs + geometries only)
- Fast spatial queries: bbox, polygon intersection, admin boundary overlaps
- Returns list of H3 IDs matching spatial criteria

**Static Attributes** (optional, can also go in Parquet)
```sql
CREATE TABLE h3_static_res6 (
    h3_id TEXT PRIMARY KEY REFERENCES h3_grid_res6(h3_id),
    elevation_mean FLOAT,
    elevation_range FLOAT,
    slope_mean FLOAT,
    slope_stddev FLOAT,
    dominant_landcover TEXT,
    -- MapSPAM aggregates (static for a given year)
    total_cropland_ha FLOAT,
    crop_diversity_index FLOAT,
    dominant_crop TEXT,
    irrigated_fraction FLOAT
);
```

### GeoParquet: Time-Series Data Lake

**Partitioning Strategy: By Res 2 Parent + Time**
```
/data/
  /res2_8a1234567ffffff/          # Parent res 2 hex ID
    climate_2000_2005.parquet     # All res 5-7 children, sorted by h3_id
    climate_2006_2010.parquet
    climate_2011_2015.parquet
    climate_2016_2020.parquet
    mapspam_2010.parquet
    mapspam_2020.parquet
  /res2_8a1234abcffffff/
    climate_2000_2005.parquet
    ...
```

**Parquet File Schema** (example: monthly climate)
```
h3_id: string (sorted)
resolution: int8
parent_res2: string
year: int16
month: int8
temperature_mean: float32
temperature_min: float32
temperature_max: float32
precipitation_total: float32
vpd: float32
pet: float32
...
```

**Key Properties**
- **Partition pruning**: Query for Brazil → only scan relevant res2 parent directories
- **Row sorting by h3_id**: Adjacent hexes cluster in same row groups (H3's spatial locality property)
- **Columnar efficiency**: Only read requested columns (e.g., just temperature, not all 12 variables)
- **Bloom filters**: Parquet can skip entire row groups based on h3_id filters

**H3 Spatial Locality Magic**
- H3 IDs that are lexicographically similar are spatially proximate
- Sorting by h3_id string provides approximate spatial clustering
- No need for explicit spatial indexing in Parquet when combined with PostGIS filtering

### Two-Stage Query Pattern

**Stage 1: Spatial Filter (PostGIS)**
```sql
-- Fast spatial index lookup
SELECT h3_id 
FROM h3_grid_res6 
WHERE ST_Intersects(geom, ST_GeomFromText('POLYGON(...)'))
  AND parent_res2 IN (SELECT h3_id FROM h3_grid_res2 WHERE ...);
```
Returns: List of 100-10,000 H3 IDs

**Stage 2: Attribute/Temporal Filter (GeoParquet via DuckDB)**
```python
import duckdb

# IDs from PostGIS
id_list = ['861f9c9ffffffff', '861f9ca7fffffff', ...]

# Query Parquet with partition pruning
result = duckdb.query(f"""
    SELECT h3_id, year, month, temperature_mean, precipitation_total
    FROM read_parquet('data/res2_*/climate_*.parquet')
    WHERE h3_id IN {tuple(id_list)}
      AND year BETWEEN 2010 AND 2020
      AND month IN (6, 7, 8)  -- Summer months
""").to_df()
```

**Alternative: Direct H3 ID Query** (skip PostGIS if user knows IDs)
```python
# User already has specific H3 cells
result = duckdb.query("""
    SELECT * FROM read_parquet('data/res2_8a1234567ffffff/climate_*.parquet')
    WHERE h3_id = '861f9c9ffffffff'
      AND year BETWEEN 2010 AND 2020
""").to_df()
```

### Performance Hypothesis

**Testing PostGIS + Parquet vs. Parquet-Only Spatial Queries**
- At current scale (34M hexes, 20 years monthly = ~8B records): Difference may be minimal
- At 100M-1B+ hex scale: PostGIS spatial filtering becomes critical for query performance
- Parquet alone: Must scan all files to check spatial predicates
- PostGIS + Parquet: Spatial filter reduces scan to 0.1-10% of data

**Benchmark Plan**
1. Generate sample dataset at target scale
2. Query pattern: "Give me temperature for hexes intersecting polygon X for 2010-2020"
3. Compare:
   - PostGIS → Parquet (expected: fast)
   - Parquet-only with spatial filter (expected: slower at scale)
4. Measure at 10M, 100M, 1B hex scales

---

## Processing Pipeline

### Azure Functions Architecture

**Function 1: H3 Grid Generation**
- Input: Admin0 polygons (World Bank boundaries or Natural Earth)
- Process:
  1. Polyfill each country at res 2
  2. Generate res 2 set (deduplicated, ~2,000 globally)
  3. For each res 2, generate children res 3-7
  4. Create H3 polygon geometries
  5. Insert into PostGIS h3_grid_res* tables
- Output: PostGIS tables populated with grid + parent relationships
- Trigger: Manual/scheduled (rare, only when grid definition changes)

**Function 2: Raster → H3 Aggregation (Static Layers)**
- Input: COGs from Planetary Computer or Blob Storage (DEM, land cover, MapSPAM)
- Process:
  1. Read COG with rasterio/xarray
  2. For each H3 cell geometry, compute zonal statistics
  3. Store results in PostGIS static tables or GeoParquet
- Libraries: rasterio, xarray, h3-py, rasterstats
- Output: h3_static_res* tables or static Parquet files
- Trigger: Per dataset update (e.g., new MapSPAM release)

**Function 3: Time-Series → H3 Aggregation (Climate)**
- Input: Climate COGs/zarr from Planetary Computer (TerraClimate, ERA5, etc.)
- Process:
  1. Chunk by time and spatial tile
  2. For each chunk, aggregate to H3 cells
  3. Sort by h3_id and partition by parent_res2
  4. Write GeoParquet files (partitioned by res2 + time range)
- Output: Partitioned GeoParquet in Blob Storage
- Trigger: Scheduled (monthly/quarterly for new climate data)
- Optimization: Use Dask/xarray for parallel processing

**Function 4: API Query Handler**
- Input: REST API request (bbox, polygon, h3_ids, time range, variables)
- Process:
  1. If spatial query: Query PostGIS for h3_id list
  2. Query GeoParquet via DuckDB with h3_id filter + temporal/attribute filters
  3. Format response (JSON, GeoJSON, or Parquet download)
- Output: Filtered dataset
- Trigger: API request

### Data Lineage and Metadata

**Metadata Tracking** (PostGIS table or JSON)
```sql
CREATE TABLE processing_metadata (
    dataset_name TEXT,
    source_url TEXT,
    source_version TEXT,
    processing_date TIMESTAMP,
    h3_resolutions INT[],
    variable_names TEXT[],
    time_range_start DATE,
    time_range_end DATE,
    notes TEXT
);
```

- Track which MapSPAM version, climate dataset version, processing date
- Enable reproducibility and update management
- DEC can see what's in the system and when it was last updated

---

## API Design

### REST API Endpoints (FastAPI)

**Base URL**: `https://api.worldbank.org/geo/h3/` (or internal endpoint)

**Endpoint 1: Spatial Query**
```
GET /timeseries
Query Parameters:
  - bbox: minx,miny,maxx,maxy (WGS84)
  - polygon: GeoJSON or WKT
  - admin0: ISO country code (e.g., BRA, KEN)
  - resolution: 5, 6, or 7 (default: 6)
  - years: 2000-2020 or 2010,2015,2020
  - months: 1-12 (optional, default: all)
  - variables: temp,precip,ndvi (comma-separated)
  - format: json, geojson, parquet

Response:
  - GeoJSON FeatureCollection or Parquet download
  - Each feature: h3_id, geometry, time-series data
```

**Endpoint 2: Direct H3 Query**
```
GET /timeseries/h3
Query Parameters:
  - h3_ids: comma-separated list or array
  - years: 2000-2020
  - variables: temp,precip
  - format: json, parquet

Response:
  - Time-series data for specified hexes
```

**Endpoint 3: Aggregated Statistics**
```
GET /stats
Query Parameters:
  - bbox or polygon or admin0
  - resolution: 5, 6, 7
  - years: 2000-2020
  - variables: temp,precip
  - aggregation: mean, min, max, sum (spatial aggregation across hexes)

Response:
  - Aggregated statistics (e.g., mean temperature for all hexes in bbox)
```

**Endpoint 4: Grid Metadata**
```
GET /grid/{resolution}
Query Parameters:
  - bbox or polygon or admin0

Response:
  - H3 cell IDs and geometries (no attributes, just the grid)
```

**Endpoint 5: Catalog/Discovery**
```
GET /catalog

Response:
  - List of available datasets, variables, time ranges, resolutions
  - Metadata about data sources and processing dates
```

### Authentication and Rate Limiting
- Internal World Bank SSO or API key
- Rate limiting per user/key (e.g., 1000 requests/hour)
- Large queries → async job queue with callback URL

---

## DEC Handoff Strategy

### What You're Building
1. **H3 grid infrastructure** in PostGIS (res 2-7)
2. **Aggregation pipeline** (Azure Functions)
3. **GeoParquet data lake** (Blob Storage)
4. **REST API** (FastAPI on App Service or Container Apps)
5. **Documentation** (API docs, data dictionary, update procedures)

### What DEC Gets
- **A data product they own**: "World Bank Agricultural Geography API"
- **Operational control**: They decide when to update MapSPAM versions, add new variables
- **Self-service for users**: Agriculture specialists query the API instead of filing IT tickets
- **Clear data governance**: DEC manages agricultural data, ITS manages infrastructure

### Handoff Requirements

**For DEC to Successfully Maintain This:**
1. **Automated pipeline** that runs on schedule (monthly/quarterly)
2. **Clear documentation**:
   - How to trigger updates when new MapSPAM data is released
   - How to add new climate variables
   - How to monitor API health and usage
3. **Simple update mechanism**:
   - Drop new MapSPAM GeoTIFFs in Blob Storage → trigger Function
   - System auto-aggregates and updates Parquet files
4. **Monitoring and alerts**:
   - Azure Monitor for Function failures
   - API usage dashboards
   - Data freshness checks (alert if no update in X months)

**DEC Technical Capacity Assessment:**
- Do they have data engineers who can manage Azure Functions?
- Can they write SQL and basic Python?
- Or do you need to make it "set and forget" with minimal human intervention?

**Your Positioning in Handoff Discussion:**
> "I've built the geospatial infrastructure and data integration pipeline. This creates a globally consistent, multi-resolution agricultural geography dataset—MapSPAM crops, climate, terrain—all queryable via API or direct PostGIS/Parquet access. 
>
> DEC, this is your data product to manage and evolve. You own the agricultural content. ITS owns the infrastructure. When agriculture specialists need data, they use your API. When MapSPAM 2025 is released, you trigger the update pipeline.
>
> The World Bank now has an authoritative ag-geo base layer that answers a decade of recurring questions in a self-service way."

### Success Metrics
- **For You (promotion credit)**:
  - Designed and implemented cloud-native geospatial architecture
  - Modernized World Bank's ag-geo data access (serverless, API-first)
  - Enabled self-service analytics for agriculture specialists
- **For DEC (ownership)**:
  - Published and maintained ag-geo data product
  - Reduced turnaround time for data requests from days/weeks to seconds
  - Platform for climate-ag analysis and development policy insights

---

## Implementation Timeline (Estimated)

**Phase 1: Foundation (2-3 weeks)**
- H3 grid generation (res 2-7) in PostGIS
- Admin0 filtering logic
- Parent-child relationships
- Basic metadata tables

**Phase 2: Static Aggregation (3-4 weeks)**
- MapSPAM → H3 aggregation pipeline
- Topography (DEM) → H3 aggregation
- Land cover → H3 aggregation
- Store in PostGIS static tables

**Phase 3: Time-Series Pipeline (4-6 weeks)**
- Climate data (TerraClimate/Planetary Computer) → H3
- Monthly time-series aggregation
- GeoParquet output with partitioning
- Test at scale (20 years × 12 months × millions of hexes)

**Phase 4: API and Access Layer (2-3 weeks)**
- FastAPI implementation
- PostGIS + DuckDB query integration
- API documentation (Swagger/OpenAPI)
- Simple web map demo

**Phase 5: Documentation and Handoff (1-2 weeks)**
- Technical documentation for DEC
- Update procedures
- Monitoring setup
- Demo and training session

**Total: ~3-4 months for production-ready system**

**Quick POC (for door-opening conversation): ~4-6 weeks**
- Res 6 only
- Single country or region
- One MapSPAM year + basic climate
- Basic API endpoint
- "Here's what it looks like—want to see the full build?"

---

## Technical Stack Summary

**Compute**: Azure Functions (Python)
**Storage**: 
  - PostGIS (RDS or Azure Database for PostgreSQL)
  - Azure Blob Storage (GeoParquet files)
**Query**: DuckDB (in-process for Parquet queries)
**API**: FastAPI (Azure App Service or Container Apps)
**Geospatial Libraries**:
  - h3-py (H3 hexagon operations)
  - rasterio (raster I/O)
  - xarray (multi-dimensional arrays, climate data)
  - geopandas (vector operations)
  - shapely (geometry manipulation)
  - rasterstats (zonal statistics)
**Data Formats**:
  - Input: COG (Cloud Optimized GeoTIFF), Zarr (for climate)
  - Output: GeoParquet (time-series), PostGIS (spatial index)
**Monitoring**: Azure Monitor, Application Insights

---

## Open Questions and Next Steps

1. **PostGIS vs. Parquet-only performance testing**
   - Hypothesis: At 100M+ hexes, PostGIS spatial filtering is essential
   - Test at 10M, 100M, 1B scales

2. **DEC technical capacity assessment**
   - Can they manage Azure Functions and SQL?
   - How much automation is needed?

3. **Dev Seed deliverables**
   - What exactly did they provide?
   - Can their work be integrated or is this a parallel build?

4. **Data update frequency**
   - MapSPAM: Every 5-10 years
   - Climate: Monthly or quarterly
   - Automation level needed?

5. **Access control and usage tracking**
   - Internal only or public API?
   - Usage quotas and rate limiting

6. **Additional datasets to integrate**
   - Soil properties?
   - Water availability?
   - Population/poverty layers?

---

## References and Resources

**MapSPAM**
- Website: https://mapspam.info
- Data: https://dataverse.harvard.edu/dataverse/mapspam
- SPAM 2020 (latest): https://doi.org/10.7910/DVN/SWPENT

**H3**
- Documentation: https://h3geo.org
- h3-py: https://github.com/uber/h3-py

**Climate Data**
- TerraClimate: https://www.climatologylab.org/terraclimate.html
- Planetary Computer: https://planetarycomputer.microsoft.com

**GeoParquet**
- Spec: https://geoparquet.org
- DuckDB Spatial: https://duckdb.org/docs/extensions/spatial

**Dev Seed**
- Known for cloud-native geospatial, STAC, H3 aggregations
- Likely used AWS (Lambda, S3, Athena)
- Your Azure translation = productionizing their R&D

---

## The Flex

Walk into the DEC meeting with:
1. **Working H3 grid** in PostGIS (all resolutions, all countries)
2. **Sample aggregations** (MapSPAM for one region, climate time-series)
3. **API endpoint** that responds in <2 seconds for complex queries
4. **Web map demo** showing it in action
5. **GeoParquet files** proving you can handle 20 years of monthly data

Then ask: *"So, what did Dev Seed deliver when you paid them?"*

Either they have something useful to integrate, or you've just demonstrated that their contractor spend is now redundant. You've translated external R&D into operational World Bank infrastructure.

**You get credit for**: Cloud-native architecture, serverless geospatial pipeline, modern data access patterns
**DEC gets**: A flagship data product they own and maintain
**Agriculture specialists get**: Self-service access to a decade's worth of answers

Everyone wins. You get promoted.

---

*Document created: 2025-11-10*
*Author: Robert (World Bank ITS Geospatial Cloud Architect)*
*Purpose: Design specification for H3 agricultural geography platform POC and production handoff to DEC*