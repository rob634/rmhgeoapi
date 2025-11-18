# Archaeological Code Review - Cleanup Report

**Date**: 18 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Comprehensive code review identifying unused files, confusing names, and DRY violations

---

## Executive Summary

Comprehensive analysis of the codebase revealed **significant archaeological artifacts** from rapid development:

- **30+ unused files** (~270 KB dead code)
- **21 naming inconsistencies** causing confusion
- **7 major DRY violations** (~700 lines duplicate code)
- **7 god objects** (>1,000 lines each)

**Immediate actions taken**:
- ✅ Deleted `postgis_handler_enhanced.py` (581 lines, experimental)
- ✅ Deleted `tasks_enhanced.py` (experimental, unused)

**Priority recommendations** for next cleanup phase below.

---

## 1. UNUSED FILES (30+ Files, ~270 KB)

### Immediate Deletions Recommended

#### Backup Files (Safe to Delete)
```bash
# Already committed in git, no need to keep backups
rm jobs/hello_world_original_backup.py      # 346 lines
rm jobs/hello_world_mixin.py                # 218 lines (test version - already migrated)
rm jobs/create_h3_base.py.bak
rm web_interfaces/jobs/interface.py.bak
```

**Impact**: -564 lines, cleaner codebase

#### Duplicate /vector/ Folder (Replaced by /services/vector/)
```bash
# Entire folder appears unused (11 files, ~50 KB)
# Replaced by /services/vector/ implementation
rm -rf vector/
```

**Files in /vector/**:
- converter_base.py (0 imports)
- converter_helpers.py (0 imports)
- converter_registry.py (0 imports)
- converters_init.py (0 imports)
- load_vector_task.py (0 imports)
- csv_converter.py (1 import - likely from __init__)
- geojson_converter.py (1 import)
- geopackage_converter.py (1 import)
- kml_converter.py (1 import)
- kmz_converter.py (1 import)
- shapefile_converter.py (1 import)

**Verification needed**: Confirm /services/vector/ has all functionality

#### Test File Organization
```bash
# Consolidate scattered test files
mkdir -p tests/unit tests/integration
mv test/*.py tests/unit/
mv test_*.py tests/  # Root-level test files
rmdir test/  # Old directory
```

### Investigate Before Deleting

#### Core Architecture Files (Large, Unused)
These may represent incomplete architectural transitions:

| File | Size | Status | Investigation Needed |
|------|------|--------|---------------------|
| core/core_controller.py | 13 KB | 0 imports | Was this the new architecture that never launched? |
| core/orchestration_manager.py | 15 KB | 0 imports | Part of CoreMachine refactor? |
| core/state_manager.py | 28 KB | 1 import | Why only 1 import if it's "essential"? |
| core/schema/orchestration.py | 16 KB | 6 imports | Duplicate of schema_orchestration.py? |

**Question**: Were these built for the Service Bus migration but never fully integrated?

#### Service Implementations (Zero Imports)

| File | Size | Purpose |
|------|------|---------|
| services/service_blob.py | 22 KB | Blob storage task handlers |
| services/service_stac_setup.py | 21 KB | STAC database setup tasks |
| services/titiler_search_service.py | 10 KB | TiTiler-PgSTAC integration |

**Question**: Are these replaced by newer handlers in services/handler_*.py files?

#### Trigger Files

| File | Size | Purpose |
|------|------|---------|
| triggers/stac_inspect.py | 8 KB | PgSTAC schema inspection endpoints |

**Potential value**: Might be useful debugging tool - check if endpoints are registered

---

## 2. NAMING ISSUES (21 Issues)

### CRITICAL: God Objects

**Files over 1,000 lines** that should be split:

| File | Lines | Recommendation |
|------|-------|----------------|
| function_app.py | 2,202 | Split into trigger modules by API domain |
| infrastructure/pgstac_bootstrap.py | 2,060 | Extract schema SQL to separate files |
| config.py | 1,747 | Split into app_config, storage_config, database_config |
| core/machine.py | 1,744 | Already improved from BaseController (2,290 lines) |
| infrastructure/postgresql.py | 1,656 | Consider splitting by repository type |
| services/h3_grid.py | 1,291 | Extract H3 utilities to separate module |
| services/raster_validation.py | 1,060 | Extract validation rules to config |

### CRITICAL: Inconsistent Handler/Service Naming

**Problem**: services/ directory has 3 naming patterns for same layer:

```
services/
├── handler_*.py (8 files)    - Task handlers
├── service_*.py (5 files)    - Task handlers
└── *.py (20+ files)          - Task handlers
```

**All three do the same thing!**

**Recommendation**: Standardize to simple pattern:
```
services/
├── hello_world.py       # No prefix needed (directory indicates layer)
├── h3_grid.py
├── raster_cog.py
└── container_analysis.py
```

Remove `handler_` and `service_` prefixes - directory already indicates architectural layer.

### CRITICAL: Multiple service.py Files

**Problem**: Generic filename without context:
```
/ogc_features/service.py     - OGC Features business logic
/stac_api/service.py         - STAC API business logic
/vector_viewer/service.py    - Vector viewer logic
```

**Recommendation**: Use descriptive names:
```
/ogc_features/ogc_service.py
/stac_api/stac_service.py
/vector_viewer/vector_viewer_service.py
```

### CRITICAL: Multiple config.py Files

**Problem**: Root + subdirectories = ambiguous imports:
```
/config.py (1,747 lines)         - Global config (GOD OBJECT!)
/ogc_features/config.py          - OGC Features config
/stac_api/config.py              - STAC API config
```

**Recommendation**:
```
/config/app_config.py           - Core application (500 lines max)
/config/storage_config.py       - Storage accounts
/config/database_config.py      - Database connections
/ogc_features/ogc_config.py     - Rename from config.py
/stac_api/stac_config.py        - Rename from config.py
```

### MODERATE: Root-Level Service Files

**Problem**: Service files in wrong location:
```
/service_stac.py (307 lines)        - STAC item creation (root)
/service_statistics.py (296 lines)  - Statistics service (root)
```

**Recommendation**: Move to proper location:
```
/services/stac_item_creation.py
/services/raster_statistics.py
```

### MINOR: Duplicate base.py Files

**Problem**: Generic name across directories:
```
/infrastructure/base.py
/jobs/base.py
/web_interfaces/base.py
```

**Recommendation**: Rename for clarity:
```
/infrastructure/repository_base.py
/jobs/job_base.py
/web_interfaces/interface_base.py
```

---

## 3. DRY VIOLATIONS (7 Major Categories, ~700 Lines)

### CRITICAL: PostgreSQL Connection Duplication

**Problem**: 20+ duplicate connection patterns across 9 files

**Current code** (duplicated 20+ times):
```python
conn = psycopg.connect(self.config.get_connection_string(), row_factory=dict_row)
```

**Files with duplication**:
- ogc_features/repository.py (6 instances)
- services/service_stac_setup.py (4 instances)
- infrastructure/database_utils.py
- triggers/health.py
- infrastructure/pgstac_bootstrap.py
- services/handler_h3_native_streaming.py
- services/handler_create_h3_stac.py
- services/service_stac_vector.py
- ... 12+ more locations

**Recommendation**: Create connection factory:

```python
# infrastructure/connection_factory.py (NEW FILE)
class PostgreSQLConnectionFactory:
    """Single source of truth for PostgreSQL connections."""

    @staticmethod
    def get_connection(row_factory=None):
        """Get PostgreSQL connection with managed identity support."""
        from infrastructure.postgresql import PostgreSQLRepository
        repo = PostgreSQLRepository()
        return repo._get_connection()
```

**Benefits**:
- Eliminates 20+ duplicate patterns
- Centralized managed identity logic
- Single place to add connection pooling
- **Impact**: -200 lines duplicate code

### HIGH: Duplicate Geometry Insertion SQL

**Problem**: ST_GeomFromText pattern repeated in 8 files

**Duplicate code**:
```python
# services/vector/postgis_handler.py
INSERT INTO {schema}.{table} (geom, {cols})
VALUES (ST_GeomFromText(%s, 4326), {placeholders})

# services/h3_grid.py
ST_GeomFromText(h3_cell_to_boundary_wkt(h3_index)) as geom

# infrastructure/database_utils.py
VALUES (ST_GeomFromText(%s, 4326), %s, %s)
```

**Files**:
- services/vector/postgis_handler.py (2 instances)
- services/h3_grid.py (4 instances)
- services/handler_h3_native_streaming.py
- infrastructure/h3_repository.py
- infrastructure/database_utils.py (2 instances)
- infrastructure/duckdb.py

**Recommendation**: Create PostGIS SQL utilities:

```python
# infrastructure/postgis_sql.py (NEW FILE)
from psycopg import sql

class PostGISSQLBuilder:
    """Centralized PostGIS SQL query construction."""

    @staticmethod
    def build_insert_geometry(schema: str, table: str, columns: list, srid: int = 4326):
        """Build INSERT statement with ST_GeomFromText."""
        cols_sql = sql.SQL(', ').join([sql.Identifier(col) for col in columns])
        placeholders = sql.SQL(', ').join([sql.Placeholder()] * len(columns))

        return sql.SQL("""
            INSERT INTO {schema}.{table} (geom, {cols})
            VALUES (ST_GeomFromText(%s, {srid}), {placeholders})
        """).format(
            schema=sql.Identifier(schema),
            table=sql.Identifier(table),
            cols=cols_sql,
            srid=sql.Literal(srid),
            placeholders=placeholders
        )
```

**Benefits**:
- Eliminates 8+ duplicate SQL patterns
- SQL injection protection in one place
- Easier to add SRID flexibility
- **Impact**: -100 lines duplicate code

### MEDIUM: Connection String Functions (3 Implementations)

**Problem**: Same function in 3 files:

```python
# config.py (line 1666) - Main implementation
def get_postgres_connection_string(config: Optional[AppConfig] = None) -> str:
    from infrastructure.postgresql import PostgreSQLRepository
    repo = PostgreSQLRepository()
    return repo.conn_string

# ogc_features/config.py (line 134) - Wrapper
def get_connection_string(self) -> str:
    from config import get_postgres_connection_string
    return get_postgres_connection_string()

# services/service_stac_setup.py (line 40) - Wrapper
def get_connection_string(as_admin: bool = False) -> str:
    from config import get_postgres_connection_string
    return get_postgres_connection_string()
```

**Recommendation**:
- Keep config.get_postgres_connection_string() only
- Delete wrappers
- Update 14 import statements

**Benefits**:
- Single source of truth
- **Impact**: -2 functions, clearer dependencies

### MEDIUM: Repository Pattern Proliferation

**Finding**: 39 repository class definitions

**Analysis**: Most serve distinct purposes (different data sources) - **NOT TRUE DUPLICATION**

**Concern**: Some are thin wrappers adding no value:

```python
# jobs_tasks.py - Thin wrappers
class JobRepository(PostgreSQLJobRepository):
    """Adds no functionality"""
    pass

class TaskRepository(PostgreSQLTaskRepository):
    """Adds no functionality"""
    pass

class StageCompletionRepository(PostgreSQLStageCompletionRepository):
    """Adds no functionality"""
    pass
```

**Recommendation**: Use base repositories directly:
```python
from infrastructure.postgresql import (
    PostgreSQLJobRepository,
    PostgreSQLTaskRepository,
    PostgreSQLStageCompletionRepository
)
```

**Benefits**:
- Removes 3 wrapper classes
- **Impact**: -50 lines

### LOW: Spatial Constants Duplication

**Problem**: SRID 4326 hardcoded in 8+ locations

**Recommendation**: Create constants module:

```python
# infrastructure/spatial_constants.py (NEW FILE)
"""Spatial reference system constants."""

# World Geodetic System 1984 (WGS84) - Standard for GPS, web maps
WGS84_SRID = 4326

# Default SRID for all PostGIS operations
DEFAULT_SRID = WGS84_SRID

# Supported coordinate reference systems
SUPPORTED_SRIDS = {
    4326: "WGS84 (GPS standard)",
    3857: "Web Mercator (Google Maps, OSM)",
    32633: "UTM Zone 33N (Europe)",
}
```

**Benefits**:
- Single source of truth
- Clear documentation
- **Impact**: Better maintainability

### LOW: Job Validation Duplication (Already Solved!)

**Finding**: 17 job files with validation methods

**Status**: ✅ JobBaseMixin already solves this (jobs/mixins.py)

**Migration status**:
- ✅ jobs/hello_world.py - Uses mixin (77% line reduction)
- ❌ 15 other jobs - Not using mixin yet

**Recommendation** (per CLAUDE.md):
> **DO NOT migrate existing jobs unless:**
> - You're already making changes to the job
> - The job is frequently copied for variations
> - Clear maintenance benefit exists
>
> **Leave working code alone** - JobBaseMixin is for NEW jobs!

**Action**: Use mixin for all NEW jobs only

### NOT DUPLICATION: Logger Initialization

**Finding**: 100+ LoggerFactory.create_logger() calls

**Analysis**: This is **CORRECT PATTERN** - not duplication

```python
# Each module needs its own logger (correct)
logger = LoggerFactory.create_logger(ComponentType.SERVICE, "service_name")
```

**Action**: No changes needed

---

## Priority Action Plan

### Phase 1: Immediate (Low Risk, High Value)

**Estimated time**: 30 minutes

1. ✅ **DELETE experimental PostGIS handlers** (DONE)
   - postgis_handler_enhanced.py
   - tasks_enhanced.py

2. **DELETE backup files**:
   ```bash
   git rm jobs/hello_world_original_backup.py
   git rm jobs/hello_world_mixin.py
   git rm jobs/create_h3_base.py.bak
   git rm web_interfaces/jobs/interface.py.bak
   ```
   **Impact**: -564 lines

3. **Consolidate connection string functions**:
   - Keep config.get_postgres_connection_string()
   - Delete wrappers in ogc_features/config.py, service_stac_setup.py
   - Update 14 import statements
   **Impact**: -2 functions

4. **Create spatial constants module**:
   - New file: infrastructure/spatial_constants.py
   - Extract SRID values
   - Update 8+ references
   **Impact**: Better maintainability

**Total Phase 1 Impact**: -566 lines, cleaner structure

### Phase 2: Medium-Term (Require Testing)

**Estimated time**: 6-8 hours

5. **Create PostgreSQL connection factory** (2 hours)
   - New: infrastructure/connection_factory.py
   - Migrate 20+ duplicate patterns
   - Comprehensive testing
   **Impact**: -200 lines

6. **Create PostGIS SQL utilities** (3 hours)
   - New: infrastructure/postgis_sql.py
   - Migrate 8 duplicate SQL patterns
   - Test spatial operations
   **Impact**: -100 lines, better SQL injection protection

7. **Remove thin wrapper repositories** (2 hours)
   - Delete JobRepository, TaskRepository wrappers
   - Update imports
   **Impact**: -50 lines

**Total Phase 2 Impact**: -350 lines, better maintainability

### Phase 3: Investigation Required

**Estimated time**: 4 hours investigation

8. **Investigate core/ architecture files**:
   - core_controller.py (13 KB, 0 imports)
   - orchestration_manager.py (15 KB, 0 imports)
   - state_manager.py (28 KB, 1 import)
   - Question: Were these part of incomplete Service Bus migration?

9. **Investigate /vector/ folder**:
   - 11 files, ~50 KB
   - Appears replaced by /services/vector/
   - Verify functionality before deletion

10. **Investigate unused service files**:
    - services/service_blob.py (22 KB, 0 imports)
    - services/service_stac_setup.py (21 KB, 0 imports)
    - services/titiler_search_service.py (10 KB, 0 imports)

**Potential Phase 3 Impact**: -100+ KB if truly unused

### Phase 4: Long-Term (Only When Needed)

11. **Split god objects** (per CLAUDE.md: "No backward compatibility"):
    - function_app.py (2,202 → ~200 lines)
    - config.py (1,747 → multiple ~500 line files)
    - infrastructure/pgstac_bootstrap.py (2,060 lines)
    - Only split when making other changes to these files

12. **Standardize services/ naming**:
    - Remove handler_/service_ prefixes
    - Only when touching those files

13. **Migrate jobs to JobBaseMixin**:
    - Only for NEW jobs
    - Only when making changes to existing jobs
    - 77% line reduction per job

---

## Summary Statistics

**Files Analyzed**: 200+
**Archaeological Artifacts Found**:
- Unused files: 30+ files (~270 KB)
- Naming issues: 21 issues (7 god objects)
- DRY violations: 7 categories (~700 lines duplicate)

**Cleanup Potential**:
- Phase 1 (immediate): -566 lines
- Phase 2 (medium-term): -350 lines
- Phase 3 (investigation): -100+ KB potentially
- **Total**: ~900+ lines minimum, potentially 1,000+ lines

**Risk Assessment**:
- ✅ Low risk: Delete backups, constants (Phase 1)
- ⚠️ Medium risk: Connection factory, SQL utilities (Phase 2)
- ⚠️ Higher risk: God object refactoring (Phase 4 - only when needed)

---

## Notes

- **Development philosophy**: "No backward compatibility" means clean breaks are acceptable
- **Test coverage**: Limited - changes require careful manual testing
- **Production verification**: All changes must be tested with 2.5M row ETL job
- **JobBaseMixin success**: Already proven 77% line reduction - use for new jobs
- **Keep working code**: Don't refactor just to refactor - only when making other changes

---

**Last Updated**: 18 NOV 2025
**Status**: Phase 1 partially complete (experimental handlers deleted)
**Next Action**: Execute remaining Phase 1 tasks (delete backups, consolidate functions)