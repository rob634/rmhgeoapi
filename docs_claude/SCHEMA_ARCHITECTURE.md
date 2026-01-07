# PostgreSQL Schema Architecture

**Date**: 24 NOV 2025

## Overview

This document explains the **intentional design** behind the PostgreSQL schema architecture. The DDL code is spread across multiple files and approaches - this is **by design**, not technical debt.

Each of the 5 database schemas uses a different management approach appropriate to its purpose and lifecycle.

---

## The Five-Schema Design

| Schema | Purpose | Management Approach | Key Files |
|--------|---------|---------------------|-----------|
| `app` | CoreMachine jobs/tasks | Pydantic → `PydanticToSQL` | `core/schema/sql_generator.py` |
| `pgstac` | STAC metadata catalog | `pypgstac migrate` (external library) | `infrastructure/pgstac_bootstrap.py` |
| `geo` | User vector/raster data | Dynamic creation at runtime | `services/vector/postgis_handler.py` |
| `h3` | H3 hexagonal grids | Static SQL files | `sql/init/*.sql` |
| `platform` | API request tracking | Pydantic → `PydanticToSQL` | `core/schema/sql_generator.py` |

---

## Schema Details

### 1. `app` Schema - CoreMachine (Pydantic-Generated)

**Tables**: `jobs`, `tasks`, `api_requests`, `janitor_runs`

**Management**: Pydantic models → `PydanticToSQL` generator → PostgreSQL DDL

**How It Works**:
1. Pydantic models define table structure (`core/models/job.py`, `core/models/task.py`)
2. `PydanticToSQL` class generates DDL from model fields
3. DDL includes: CREATE TABLE, ENUM types, indexes, functions, triggers
4. Deployment via `/api/dbadmin/maintenance/redeploy?confirm=yes`

**Key Files**:
- `core/schema/sql_generator.py` - DDL generation (1,127 lines)
- `core/schema/deployer.py` - Deployment orchestration (505 lines)
- `triggers/schema_pydantic_deploy.py` - HTTP endpoint

**PostgreSQL Functions** (generated automatically):
| Function | Purpose |
|----------|---------|
| `complete_task_and_check_stage()` | Atomic task completion with advisory locks |
| `advance_job_stage()` | Stage advancement logic |
| `check_job_completion()` | Job completion detection |
| `increment_task_retry_count()` | Retry counter management |
| `update_updated_at_column()` | Trigger for timestamp updates |

**Why This Approach**:
- Single source of truth (Pydantic models)
- Type safety from Python to database
- Automatic DDL generation reduces manual errors
- SQL injection prevention via `psycopg.sql` composition

---

### 2. `pgstac` Schema - STAC Catalog (External Library)

**Tables**: `collections`, `items`, `searches`, `queryables`, partitions, etc. (22 tables total)

**Management**: `pypgstac migrate` command (library controls schema)

**How It Works**:
1. pypgstac library owns the schema structure
2. Schema name is hardcoded as `pgstac` (cannot change)
3. Migrations run via subprocess: `python -m pypgstac.pypgstac migrate`
4. Application code only reads/writes data, never modifies schema

**Key Files**:
- `infrastructure/pgstac_bootstrap.py` - Schema setup and verification (2,090 lines)
- `infrastructure/pgstac_repository.py` - Data CRUD operations (401 lines)

**Critical Functions** (provided by pypgstac):
| Function | Purpose | Status |
|----------|---------|--------|
| `get_version()` | Return pgstac version | ✅ Working |
| `search()` | STAC search endpoint | ✅ Working |
| `create_collection()` | Insert new collection | ✅ Working |
| `upsert_collection()` | Insert or update collection | ✅ Working |
| `create_item()` | Insert STAC item | ✅ Working |
| `search_tohash()` | Hash search query (GENERATED column) | ✅ Present |
| `search_hash()` | Compute search hash | ✅ Present |
| `get_collection()` | Get single collection | ❌ **Does NOT exist in 0.9.8** |

**Version Info** (24 NOV 2025):
- Database schema: **0.9.8**
- pypgstac library: **0.9.8** (requirements.txt)
- Status: ✅ Synchronized

**Why This Approach**:
- pgstac is a mature, tested library
- Schema designed for STAC specification compliance
- Partitioning strategy for millions of items
- We don't control the schema - library does

**CRITICAL: `get_collection()` Function**

The function `pgstac.get_collection()` does **NOT exist** in pgstac 0.9.8. Code was updated (13 NOV 2025) to use direct table query:

```python
# OLD (BROKEN) - Never existed in 0.9.8
cur.execute("SELECT * FROM pgstac.get_collection(%s)", [collection_id])

# NEW (CORRECT) - Direct table query
cur.execute("SELECT content FROM pgstac.collections WHERE id = %s", [collection_id])
```

---

### 3. `geo` Schema - User Data (Dynamic Runtime Creation)

**Tables**: Created dynamically based on uploaded data (e.g., `countries`, `buildings`, `roads`)

**Management**:
- **Legacy**: `VectorToPostGISHandler._create_table_if_not_exists()` - minimal columns
- **New (24 NOV 2025)**: `GeoTableBuilder` - standard metadata + ArcGIS compatibility

**How It Works**:
1. User uploads vector file (Shapefile, GeoPackage, GeoJSON, etc.)
2. ETL job reads file and detects schema from data
3. `GeoTableBuilder.create_complete_ddl()` generates DDL with standard metadata columns
4. Table created with geometry column + standard metadata + dynamic attributes

**Key Files**:
- `core/schema/geo_table_builder.py` - Standardized geo table DDL generation (NEW)
- `services/vector/postgis_handler.py` - Table creation and data insertion

**Why This Approach**:
- **Tables vary by input file** - attribute schema unknown until runtime
- **Standard metadata always present** - traceability, STAC linkage, timestamps
- Geometry type detected from data (MultiPolygon, MultiLineString, etc.)
- **ArcGIS Enterprise compatible** - configurable geometry column name

---

## GeoTableBuilder - Standardized Geo Tables (NEW 24 NOV 2025)

### Purpose

`GeoTableBuilder` provides standardized table creation for the `geo` schema with:
1. **Standard metadata columns** (always present for traceability)
2. **Dynamic attribute columns** (detected from GeoDataFrame at runtime)
3. **ArcGIS Enterprise compatibility** (configurable `shape` vs `geom` column)
4. **Automatic indexes and triggers**

### Standard Metadata Columns

Every geo table created with `GeoTableBuilder` includes:

| Column | Type | Purpose |
|--------|------|---------|
| `objectid` | SERIAL PRIMARY KEY | ArcGIS-compatible primary key |
| `created_at` | TIMESTAMP WITH TIME ZONE | Record creation time |
| `updated_at` | TIMESTAMP WITH TIME ZONE | Auto-updated on modification |
| `source_file` | VARCHAR(500) | Original filename for lineage |
| `source_format` | VARCHAR(50) | File format (shp, gpkg, geojson) |
| `source_crs` | VARCHAR(50) | Original CRS before reprojection |
| `stac_item_id` | VARCHAR(100) | Link to STAC catalog item |
| `stac_collection_id` | VARCHAR(100) | Link to STAC collection |
| `etl_job_id` | VARCHAR(64) | Link to CoreMachine job |
| `etl_batch_id` | VARCHAR(100) | Chunk/batch identifier |

### Geometry Column Configuration

```python
from core.schema.geo_table_builder import GeoTableBuilder, GeometryColumnConfig

# Standard PostGIS (default)
builder = GeoTableBuilder(geometry_column=GeometryColumnConfig.POSTGIS)
# Creates: geom GEOMETRY(MULTIPOLYGON, 4326)

# ArcGIS Enterprise Geodatabase
builder = GeoTableBuilder(geometry_column=GeometryColumnConfig.ARCGIS)
# Creates: shape GEOMETRY(MULTIPOLYGON, 4326)
```

### Usage Examples

**Create table with metadata (recommended)**:
```python
from services.vector.postgis_handler import VectorToPostGISHandler

handler = VectorToPostGISHandler()
result = handler.create_table_with_metadata(
    gdf=my_geodataframe,
    table_name='countries',
    schema='geo',
    source_file='countries.shp',
    source_format='shp',
    stac_item_id='countries-2024',
    arcgis_mode=False  # or True for ArcGIS
)
```

**Complete upload with metadata**:
```python
result = handler.upload_chunk_with_metadata(
    chunk=my_geodataframe,
    table_name='countries',
    schema='geo',
    source_file='countries.shp',
    source_format='shp',
    stac_item_id='countries-2024',
    etl_job_id='abc123',
    arcgis_mode=True  # Use 'shape' column for ArcGIS
)
```

**Legacy upload (no metadata)**:
```python
# Still available for backward compatibility
handler.upload_chunk(chunk, 'countries', 'geo')
```

### ArcGIS Enterprise Integration

For ArcGIS Enterprise Geodatabase compatibility:

1. Set `arcgis_mode=True` in method calls
2. Uses `shape` column name instead of `geom`
3. Uses `objectid` for primary key (ArcGIS convention)
4. Future: Add SDE metadata table registration

**Example**:
```
User uploads: countries.shp
ArcGIS mode: True

Table created: geo.countries
├── objectid SERIAL PRIMARY KEY (ArcGIS convention)
├── shape GEOMETRY(MULTIPOLYGON, 4326) (ArcGIS convention)
├── created_at TIMESTAMP WITH TIME ZONE
├── updated_at TIMESTAMP WITH TIME ZONE
├── source_file VARCHAR(500) → 'countries.shp'
├── stac_item_id VARCHAR(100) → 'countries-2024'
├── etl_job_id VARCHAR(64) → 'abc123'
├── name TEXT (dynamic from data)
├── population INTEGER (dynamic from data)
└── gdp DOUBLE PRECISION (dynamic from data)

Indexes created:
├── idx_countries_shape (GIST spatial)
├── idx_countries_stac_item_id (B-tree)
├── idx_countries_stac_collection_id (B-tree)
├── idx_countries_etl_job_id (B-tree)
└── idx_countries_created_at (B-tree)

Trigger created:
└── trg_countries_updated_at (auto-update updated_at on modification)
```

---

### 4. `h3` Schema - H3 Grids (Static SQL)

**Tables**: `grids`, `reference_filters`, `grid_metadata`

**Management**: Static SQL files executed manually or at deployment

**How It Works**:
1. SQL files in `sql/init/` define schema structure
2. Executed during initial setup or bootstrap
3. Rarely changes after initial creation
4. Contains system reference data (H3 hexagonal grids)

**Key Files**:
- `sql/init/00_create_h3_schema.sql` - Schema creation
- `sql/init/01_init_extensions.sql` - PostGIS extensions
- `sql/init/02_create_h3_grids_table.sql` - Grids table
- `sql/init/04_create_h3_reference_filters_table.sql` - Filters
- `sql/init/06_create_h3_grid_metadata_table.sql` - Metadata

**Why This Approach**:
- Bootstrap data that rarely changes
- Different lifecycle than application code
- Simple, readable SQL files
- No need for dynamic generation

---

### 5. `platform` Schema - API Tracking (Pydantic-Generated)

**Tables**: Part of `app` schema (`api_requests`, `janitor_runs`)

**Management**: Same as `app` schema - Pydantic → `PydanticToSQL`

**Note**: Platform tables are logically separate but physically in `app` schema for simplicity.

---

## Infrastructure-as-Code (IaC) Guarantees

**Date Added**: 25 NOV 2025

### Core Principle

The `app` and `pgstac` schemas meet **infrastructure-as-code** standards:

> **IaC Standard**: Both schemas can be completely wiped and recreated perfectly from code, with no manual intervention required.

### Schema Classification

| Schema | IaC Status | Rebuild Method | Can Be Wiped |
|--------|------------|----------------|--------------|
| `app` | ✅ **100% IaC** | Pydantic → `PydanticToSQL` DDL | **YES** |
| `pgstac` | ✅ **100% IaC** | `pypgstac migrate` CLI | **YES** |
| `geo` | ❌ Business Data | Dynamic at runtime | **NEVER** |
| `h3` | ⚠️ Bootstrap | Static SQL files | Manual only |

### Why app + pgstac Must Be Wiped Together

**Architectural Decision (25 NOV 2025)**:

```
Job IDs in app.jobs ←→ STAC items in pgstac.items
```

Every job ID corresponds to a STAC item. Wiping one without the other creates orphaned references:
- Wiping `app` only → STAC items with no job context
- Wiping `pgstac` only → Jobs referencing non-existent STAC items

**Solution**: The `full-rebuild` endpoint enforces atomic rebuild of both schemas.

### What NEVER Gets Touched

- **`geo` schema**: User-uploaded vector/raster data (business data)
- **`h3` schema**: Static H3 grid bootstrap data
- **`public` schema**: PostgreSQL/PostGIS extensions

---

## Deployment Commands

### ⚡ Full Infrastructure Rebuild (RECOMMENDED)

Atomically wipe and redeploy BOTH `app` and `pgstac` schemas together:

```bash
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance/full-rebuild?confirm=yes"
```

**Steps Performed**:
1. Drop `app` schema (CASCADE)
2. Drop `pgstac` schema (CASCADE)
3. Deploy `app` schema from Pydantic models
4. Deploy `pgstac` schema via `pypgstac migrate`
5. Create system STAC collections
6. Verify `app` schema (tables, functions, enums)
7. Verify `pgstac` schema (version, hash functions)

**Use Cases**:
- Fresh development environment
- Schema corruption recovery
- Major architecture changes
- Resetting demo/test environments

### Redeploy App Schema Only
```bash
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance/redeploy?confirm=yes"
```

### Redeploy pgstac Schema Only
```bash
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance/pgstac/redeploy?confirm=yes"
```

### Clear STAC Data (dev/test only)
```bash
# Clear all (collections CASCADE to items)
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/stac/nuke?confirm=yes&mode=all"

# Clear items only
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/stac/nuke?confirm=yes&mode=items"
```

### H3 Schema (manual)
```bash
PGPASSWORD='...' psql -h rmhpostgres.postgres.database.azure.com -U {db_superuser} -d geopgflex \
  < sql/init/00_create_h3_schema.sql
```

---

## Schema Verification

### Check All Schemas Exist
```sql
SELECT schema_name FROM information_schema.schemata
WHERE schema_name IN ('app', 'pgstac', 'geo', 'h3', 'platform')
ORDER BY schema_name;
```

### Check pgstac Functions
```sql
SELECT routine_name FROM information_schema.routines
WHERE routine_schema = 'pgstac'
ORDER BY routine_name;
```

### Check pgstac Version
```sql
SELECT pgstac.get_version();
```

### Check Search Hash Functions (Critical for TiTiler)
```sql
SELECT COUNT(*) FROM pg_proc p
JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'pgstac'
AND p.proname IN ('search_tohash', 'search_hash');
-- Should return: 2
```

---

## Connection Patterns

### Managed Identity Authentication (24 NOV 2025)

**Identity**: `rmhpgflexadmin` (user-assigned managed identity)

All database connections use the same authentication priority chain:

| Priority | Method | Detection | Environment Variables |
|----------|--------|-----------|----------------------|
| 1 | User-Assigned Managed Identity | `DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID` is set | `DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID`, `DB_ADMIN_MANAGED_IDENTITY_NAME` |
| 2 | System-Assigned Managed Identity | `WEBSITE_SITE_NAME` is set (Azure) | `DB_ADMIN_MANAGED_IDENTITY_NAME` (optional) |
| 3 | Password Authentication | `POSTGIS_PASSWORD` is set | `POSTGIS_USER`, `POSTGIS_PASSWORD` |
| 4 | **FAIL** | None of the above | - |

**Environment Variables**:
```bash
# User-Assigned Managed Identity (PRODUCTION - RECOMMENDED)
DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID=12345678-1234-1234-1234-123456789abc  # Client ID from Azure Portal
DB_ADMIN_MANAGED_IDENTITY_NAME=rmhpgflexadmin                              # PostgreSQL user name (default)

# Password Authentication (LOCAL DEVELOPMENT ONLY)
POSTGIS_USER={db_superuser}
POSTGIS_PASSWORD=your_password_here
```

### Main Pattern (PostgreSQLRepository)
Used by: `PostgreSQLRepository`, `PgStacBootstrap`, `VectorToPostGISHandler`

```python
from infrastructure.postgresql import PostgreSQLRepository
repo = PostgreSQLRepository()
with repo._get_connection() as conn:
    # ... database operations
```

**Implementation**: `infrastructure/postgresql.py` lines 223-300
- `_get_connection_string()` - Authentication priority chain
- `_build_managed_identity_connection_string()` - Token acquisition

### OGC Features Pattern (Standalone)
Used by: `OGCFeaturesRepository`

```python
from ogc_features.repository import OGCFeaturesRepository
repo = OGCFeaturesRepository()
with repo._get_connection() as conn:
    # ... OGC Features queries
```

**Implementation**: `ogc_features/config.py` lines 132-267
- Uses same authentication priority chain as PostgreSQLRepository
- ✅ **Fixed 24 NOV 2025**: Now properly supports managed identity authentication

### PostgreSQL User Setup

The managed identity user must be created in PostgreSQL:

```sql
-- Create user from managed identity (Azure PostgreSQL Flexible Server)
SELECT * FROM pgaadauth_create_principal('rmhpgflexadmin', false, false);

-- Grant permissions on all schemas
GRANT ALL PRIVILEGES ON SCHEMA app TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON SCHEMA geo TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON SCHEMA pgstac TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON SCHEMA h3 TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA app TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA geo TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA pgstac TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA h3 TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA app TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA geo TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA pgstac TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA h3 TO rmhpgflexadmin;

-- Grant default privileges for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT ALL ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT ALL ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA h3 GRANT ALL ON TABLES TO rmhpgflexadmin;
```

### Token Lifecycle

**Azure Functions (Current Architecture)**:
- Function instances are short-lived (typically <10 minutes)
- Repository instances recreated per-request
- Fresh tokens acquired automatically on each invocation
- Token expiration (~1 hour) is NOT a problem

**Future Long-Running Services**:
If migrating to Container Apps or always-on services, implement one of:
1. Fetch token per connection (simple, ~50ms overhead)
2. Connection pool with token refresh (complex, efficient)
3. Periodic repository recreation

---

## Why Different Approaches?

| Approach | Used For | Reason |
|----------|----------|--------|
| Pydantic → SQL | `app` schema | Known schema, type safety, single source of truth |
| External library | `pgstac` schema | Industry-standard STAC implementation |
| Dynamic runtime | `geo` schema | Schema varies per user upload |
| Static SQL | `h3` schema | Bootstrap data, rarely changes |

**Key Insight**: The "scattered" DDL code is **intentional domain separation**, not technical debt. Each schema has different requirements and lifecycles.

---

## pgstac Function Reference

### Functions That EXIST in pgstac 0.9.8
| Function | Parameters | Returns | Purpose |
|----------|------------|---------|---------|
| `get_version()` | none | text | Schema version |
| `search(jsonb)` | search params | jsonb | STAC search |
| `create_collection(jsonb)` | collection JSON | void | Insert collection |
| `upsert_collection(jsonb)` | collection JSON | void | Insert/update collection |
| `create_item(jsonb)` | item JSON | void | Insert item |
| `search_tohash(jsonb)` | search params | text | Hash for GENERATED column |
| `search_hash(jsonb)` | search params | text | Compute search hash |
| `all_collections()` | none | jsonb | List all collections |

### Functions That DO NOT EXIST
| Function | Why Referenced | Correct Approach |
|----------|---------------|------------------|
| `get_collection(text)` | Old code assumed it existed | Direct query: `SELECT content FROM pgstac.collections WHERE id = %s` |

---

## Troubleshooting

### "function pgstac.get_collection(text) does not exist"
**Cause**: Code calling non-existent function
**Fix**: Use direct table query instead of function call

### "no partition of relation 'items' found for row"
**Cause**: Trying to insert item into non-existent collection
**Fix**: Create collection BEFORE inserting items (pgstac uses partitioning)

### "column hash has no default"
**Cause**: Missing `search_tohash` or `search_hash` functions
**Fix**: Run `/api/dbadmin/maintenance/pgstac/redeploy?confirm=yes`

### Schema out of sync with Pydantic models
**Fix**: Run `/api/dbadmin/maintenance/redeploy?confirm=yes`

---

## Related Documentation

- `docs_claude/CLAUDE_CONTEXT.md` - Primary context
- `docs_claude/ARCHITECTURE_REFERENCE.md` - Deep technical specs
- `docs_claude/PGSTAC_VERSION_ANALYSIS.md` - pgstac version details
- `docs_claude/SERVICE_BUS_HARMONIZATION.md` - Queue configuration
