# Active Tasks - process_raster_collection Implementation

**Last Updated**: 25 NOV 2025 (15:30 UTC)
**Author**: Robert and Geospatial Claude Legion

---

## ✅ RESOLVED: SQL Generator Invalid Index Bug (24 NOV 2025)

**Status**: ✅ **FIXED** on 24 NOV 2025
**Fix Location**: `core/schema/sql_generator.py:478-491`

### What Was Fixed

The `generate_indexes_composed()` method was creating an invalid `idx_api_requests_status` index for the `api_requests` table, which does NOT have a `status` column.

**Fix Applied** (sql_generator.py:479-481):
```python
elif table_name == "api_requests":
    # Platform Layer indexes (added 16 NOV 2025, FIXED 24 NOV 2025)
    # NOTE: api_requests does NOT have a status column (removed 22 NOV 2025)
    # Status is delegated to CoreMachine job_id lookup
```

Now only valid indexes are generated:
- `idx_api_requests_dataset_id`
- `idx_api_requests_created_at`

---

## 🚨 CRITICAL: JPEG COG Compression Failing in Azure Functions (21 NOV 2025)

**Status**: ❌ **BROKEN** - JPEG compression fails, DEFLATE works fine
**Priority**: **CRITICAL** - Blocks visualization tier COG creation
**Impact**: Cannot create web-optimized COGs for TiTiler streaming

### Problem Description

The `process_raster` job fails at Stage 2 (create_cog) when using `output_tier: "visualization"` (JPEG compression), but succeeds with `output_tier: "analysis"` (DEFLATE compression).

**Error**: `COG_TRANSLATE_FAILED` after ~6 seconds of processing
**Error Classification**: The error occurs in `cog_translate()` call (rio-cogeo library)

### Evidence

| Test | Output Tier | Compression | Result | Duration |
|------|-------------|-------------|--------|----------|
| dctest_v3 | visualization | JPEG | ❌ COG_TRANSLATE_FAILED | ~6 sec |
| dctest_deflate | analysis | DEFLATE | ✅ SUCCESS (127.58 MB) | 9.8 sec |

**Same input file**: dctest.tif (27 MB RGB GeoTIFF, 7777x5030 pixels, uint8)
**Same infrastructure**: Azure Functions B3 tier, same runtime, same deployment

### Root Cause Analysis (Suspected)

1. **GDAL JPEG Driver Issue**: The Azure Functions Python runtime may have a broken or missing libjpeg library linkage with GDAL/rasterio
2. **Memory Allocation Pattern**: JPEG compression may have different memory allocation patterns that fail in the constrained Azure Functions environment
3. **rio-cogeo JPEG Profile Bug**: The JPEG COG profile configuration may be incompatible with rasterio version in Azure

### Technical Context

**Code Location**: `services/raster_cog.py` lines 388-401
```python
# This call fails for JPEG, succeeds for DEFLATE
cog_translate(
    src,                        # Input rasterio dataset
    output_memfile.name,        # Output to MemoryFile
    cog_profile,                # JPEG vs DEFLATE profile
    config=config,
    overview_level=None,
    overview_resampling=overview_resampling_name,
    in_memory=in_memory,
    quiet=False,
)
```

**COG Profile Source**: `rio_cogeo.profiles.cog_profiles` dictionary
- DEFLATE profile: Works ✅
- JPEG profile: Fails ❌

### Workaround (Active)

Use `output_tier: "analysis"` (DEFLATE) instead of `output_tier: "visualization"` (JPEG):
```bash
curl -X POST ".../api/jobs/submit/process_raster" \
  -d '{"blob_name": "image.tif", "container_name": "rmhazuregeobronze", "output_tier": "analysis"}'
```

**Trade-offs**:
- ✅ DEFLATE produces larger files (127 MB vs ~5-10 MB with JPEG for RGB imagery)
- ✅ DEFLATE is lossless (better for analysis)
- ❌ DEFLATE is slower to stream via TiTiler (more bytes to transfer)
- ❌ JPEG compression ratio (97% reduction) unavailable

### Investigation Steps Required

- [ ] **Test JPEG locally**: Run rio-cogeo with JPEG profile on local machine to verify it works outside Azure
- [ ] **Check GDAL drivers**: Add diagnostic to log available GDAL drivers in Azure Functions runtime
  ```python
  from osgeo import gdal
  logger.info(f"GDAL drivers: {[gdal.GetDriver(i).ShortName for i in range(gdal.GetDriverCount())]}")
  ```
- [ ] **Check libjpeg linkage**: Verify JPEG driver is properly linked
  ```python
  import rasterio
  logger.info(f"Rasterio GDAL version: {rasterio.gdal_version()}")
  driver = rasterio.drivers.env.get('JPEG')
  ```
- [ ] **Test explicit JPEG driver**: Try creating JPEG COG with explicit driver specification
- [ ] **Check Azure Functions base image**: Determine if Python 3.12 runtime image has JPEG support
- [ ] **Review rio-cogeo GitHub issues**: Search for known JPEG issues in cloud environments
- [ ] **Add detailed error logging**: Capture the actual exception message from cog_translate()

### Fix Options (Once Root Cause Identified)

1. **If missing driver**: Add GDAL JPEG driver to requirements or use custom Docker image
2. **If memory issue**: Reduce JPEG quality or process smaller tiles
3. **If rio-cogeo bug**: Pin to specific version or patch the library
4. **If unfixable**: Document limitation and recommend DEFLATE for all tiers

### Related Config Issue Fixed (Same Session)

**Root Cause Found**: Missing `raster_cog_in_memory` legacy property in `config/app_config.py`

**Fix Applied**: Added three missing legacy properties:
```python
@property
def raster_cog_in_memory(self) -> bool:
    return self.raster.cog_in_memory

@property
def raster_target_crs(self) -> str:
    return self.raster.target_crs

@property
def raster_mosaicjson_maxzoom(self) -> int:
    return self.raster.mosaicjson_maxzoom
```

This fix was required after the config.py → config/ package migration (20 NOV 2025).

---

## ✅ STAC API Fixed & Validated (19 NOV 2025)

**Status**: **RESOLVED** - STAC API fully operational with live data
**Achievement**: Complete end-to-end validation from raster upload to browser visualization
**Completion**: 20 NOV 2025 00:40 UTC

### What Was Fixed

**Root Cause**: Tuple/dict confusion in pgSTAC query functions
- `infrastructure/pgstac_bootstrap.py:1191` - `get_collection_items()` using `result[0]` instead of `result['jsonb_build_object']`
- `infrastructure/pgstac_bootstrap.py:1291` - `search_items()` using same incorrect pattern

**Fix Applied**: Changed from tuple indexing to dictionary key access with RealDictCursor

**Validation Results**:
- ✅ Deployed to Azure Functions (20 NOV 2025 00:08:28 UTC)
- ✅ Schema redeployment: app + pgSTAC 0.9.8
- ✅ Live test: process_raster job with dctest.tif (27 MB → 127.6 MB COG)
- ✅ STAC API endpoints working: `/api/stac/collections` and `/api/stac/collections/{id}/items`
- ✅ TiTiler URLs present in STAC items using `/vsiaz/silver-cogs/` pattern
- ✅ **USER CONFIRMED**: TiTiler interactive map working in browser

### Database State

**pgSTAC** (pgstac schema):
- Version: 0.9.8 with 22 tables
- Collections: 1 (`dctest_validation_19nov2025`)
- Items: 1 (`dctest_validation_19nov2025-dctest_cog_analysis-tif`)
- Search hash functions: `search_tohash`, `search_hash`, `search_fromhash` all present
- GENERATED hash column: Working correctly

**CoreMachine** (app schema):
- Jobs: process_raster job completed in 25 seconds
- Tasks: All 3 stages completed successfully

---

## 🔧 HIGH PRIORITY - Refactor config.py God Object (18 NOV 2025)

**Status**: Planned - Incremental migration with parallel operation
**Purpose**: Split 1,747-line config.py into domain-specific modules
**Priority**: HIGH (maintainability + testing + merge conflicts)
**Strategy**: Create new modules alongside old code, migrate incrementally, delete old code last
**Effort**: 6-8 hours over 2-3 sessions
**Documentation**: See [GOD_OBJECTS_EXPLAINED.md](GOD_OBJECTS_EXPLAINED.md) for detailed analysis

### The Problem

**Current State**: config.py is 1,747 lines with 6 different configuration domains:
- Lines 496-1586: AppConfig class (1,090 lines!)
  - 63+ fields covering Storage + Database + Raster + Vector + Queues + STAC + H3 + Application settings
  - 10+ computed properties
  - 5+ validation methods
  - 200+ lines of documentation strings

**Pain Points**:
1. ❌ **Hard to find settings**: "What's the COG compression default?" = search 1,747 lines
2. ❌ **Unclear dependencies**: Does raster code need database config? (AppConfig has both - can't tell!)
3. ❌ **Testing complexity**: Test COG creation = mock 63+ fields (only need 15 raster fields!)
4. ❌ **Merge conflicts**: Two developers changing different configs = editing same AppConfig class

**Analysis**: See [GOD_OBJECTS_EXPLAINED.md](GOD_OBJECTS_EXPLAINED.md) section "2. config.py - The Configuration Monster"

---

### Incremental Migration Strategy (Safe, Testable)

**Core Principle**: Create new structure alongside old code, migrate piece by piece, delete old code last

#### Phase 1: Create New Config Modules (2 hours)

**Step 1.1: Create config/ folder structure**
```bash
mkdir -p config
touch config/__init__.py
touch config/app_config.py        # Core application settings
touch config/storage_config.py    # COG tiers, multi-account storage
touch config/database_config.py   # PostgreSQL/PostGIS
touch config/raster_config.py     # Raster pipeline settings
touch config/vector_config.py     # Vector pipeline settings
touch config/queue_config.py      # Service Bus queues
```

**Step 1.2: Implement new config modules**

Create each module with clean, focused configuration classes:

**config/storage_config.py** (400 lines):
```python
"""Azure Storage configuration - COG tiers, multi-account trust zones."""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

# Copy from config.py lines 59-254 (COG tier enums/profiles)
class CogTier(str, Enum):
    VISUALIZATION = "visualization"
    ANALYSIS = "analysis"
    ARCHIVE = "archive"

class CogTierProfile(BaseModel):
    # ... copy from config.py

# Copy from config.py lines 255-299 (utility function)
def determine_applicable_tiers(band_count: int, data_type: str) -> List[CogTier]:
    # ... copy from config.py

# Copy from config.py lines 300-364
class StorageAccountConfig(BaseModel):
    # ... copy from config.py

# Copy from config.py lines 365-495
class MultiAccountStorageConfig(BaseModel):
    # ... copy from config.py

# NEW: Clean wrapper
class StorageConfig(BaseModel):
    """Azure Storage configuration."""
    storage: MultiAccountStorageConfig

    @classmethod
    def from_environment(cls):
        """Load from environment variables."""
        return cls(storage=MultiAccountStorageConfig.from_environment())
```

**config/database_config.py** (300 lines):
```python
"""PostgreSQL/PostGIS database configuration."""

from typing import Optional
from pydantic import BaseModel, Field

class DatabaseConfig(BaseModel):
    """PostgreSQL/PostGIS configuration."""

    # Extract from AppConfig lines ~620-710
    host: str = Field(...)
    port: int = Field(default=5432)
    user: str = Field(...)
    password: Optional[str] = Field(default=None, repr=False)
    database: str = Field(...)
    postgis_schema: str = Field(default="geo")
    app_schema: str = Field(default="app")
    platform_schema: str = Field(default="platform")

    # Extract managed identity fields
    use_managed_identity: bool = Field(default=True)
    managed_identity_name: Optional[str] = Field(default=None)

    # Connection pooling (extract from AppConfig if present)
    min_connections: int = Field(default=1)
    max_connections: int = Field(default=20)
    connection_timeout_seconds: int = Field(default=30)

    @property
    def connection_string(self) -> str:
        """Build PostgreSQL connection string."""
        if self.use_managed_identity:
            return f"host={self.host} port={self.port} dbname={self.database} user={self.user}"
        else:
            return f"host={self.host} port={self.port} dbname={self.database} user={self.user} password={self.password}"

    def debug_dict(self) -> dict:
        """Debug output with masked password."""
        return {
            "host": self.host,
            "database": self.database,
            "password": "***MASKED***" if self.password else None,
            "managed_identity": self.use_managed_identity
        }

    @classmethod
    def from_environment(cls):
        """Load from environment variables."""
        import os
        return cls(
            host=os.environ["POSTGIS_HOST"],
            port=int(os.environ.get("POSTGIS_PORT", "5432")),
            user=os.environ["POSTGIS_USER"],
            password=os.environ.get("POSTGIS_PASSWORD"),
            database=os.environ["POSTGIS_DATABASE"],
            # ... all fields from env
        )

def get_postgres_connection_string(config: Optional[DatabaseConfig] = None) -> str:
    """Legacy compatibility function."""
    if config is None:
        from infrastructure.postgresql import PostgreSQLRepository
        repo = PostgreSQLRepository()
        return repo.conn_string
    return config.connection_string
```

**config/raster_config.py** (250 lines):
```python
"""Raster processing pipeline configuration."""

from typing import Optional
from pydantic import BaseModel, Field

class RasterConfig(BaseModel):
    """Raster processing configuration."""

    # Extract from AppConfig lines ~560-642
    size_threshold_mb: int = Field(default=1000)
    cog_compression: str = Field(default="deflate")
    cog_jpeg_quality: int = Field(default=85)
    cog_tile_size: int = Field(default=512)
    cog_in_memory: bool = Field(default=True)
    overview_resampling: str = Field(default="average")
    target_crs: str = Field(default="EPSG:4326")
    reproject_resampling: str = Field(default="bilinear")
    strict_validation: bool = Field(default=True)
    mosaicjson_maxzoom: int = Field(default=24)
    intermediate_tiles_container: Optional[str] = Field(default=None)
    intermediate_prefix: str = Field(default="temp/raster_etl")

    @classmethod
    def from_environment(cls):
        """Load from environment variables."""
        import os
        return cls(
            cog_compression=os.environ.get("RASTER_COG_COMPRESSION", "deflate"),
            cog_jpeg_quality=int(os.environ.get("RASTER_COG_JPEG_QUALITY", "85")),
            # ... all fields
        )
```

**config/vector_config.py** (150 lines):
```python
"""Vector processing pipeline configuration."""

from pydantic import BaseModel, Field

class VectorConfig(BaseModel):
    """Vector processing configuration."""

    # Extract from AppConfig lines ~545-558
    pickle_container: str = Field(default="rmhazuregeotemp")
    pickle_prefix: str = Field(default="temp/vector_etl")
    default_chunk_size: int = Field(default=1000)
    auto_chunk_sizing: bool = Field(default=True)
    target_schema: str = Field(default="geo")
    create_spatial_indexes: bool = Field(default=True)

    @classmethod
    def from_environment(cls):
        """Load from environment variables."""
        import os
        return cls(
            pickle_container=os.environ.get("VECTOR_PICKLE_CONTAINER", "rmhazuregeotemp"),
            # ... all fields
        )
```

**config/queue_config.py** (200 lines):
```python
"""Azure Service Bus queue configuration."""

from pydantic import BaseModel, Field

class QueueNames:
    """Queue name constants (copied from config.py lines 1622-1626)."""
    JOBS = "geospatial-jobs"
    TASKS = "geospatial-tasks"

class QueueConfig(BaseModel):
    """Service Bus queue configuration."""

    # Extract from AppConfig if present
    connection_string: str = Field(..., repr=False)
    jobs_queue: str = Field(default=QueueNames.JOBS)
    tasks_queue: str = Field(default=QueueNames.TASKS)
    batch_size: int = Field(default=100)
    batch_threshold: int = Field(default=50)

    @classmethod
    def from_environment(cls):
        """Load from environment variables."""
        import os
        return cls(
            connection_string=os.environ["ServiceBusConnection"],
            # ... all fields
        )
```

**config/app_config.py** (150 lines):
```python
"""Main application configuration - composes domain configs."""

from pydantic import BaseModel, Field
from .storage_config import StorageConfig
from .database_config import DatabaseConfig
from .raster_config import RasterConfig
from .vector_config import VectorConfig
from .queue_config import QueueConfig

class AppConfig(BaseModel):
    """
    Application configuration - composition of domain configs.

    NEW PATTERN: Instead of 63+ fields in one class, compose smaller configs.
    Each domain config manages its own validation and defaults.
    """

    # Core application settings (extract from old AppConfig)
    debug_mode: bool = Field(default=False)
    environment: str = Field(default="dev")
    timeout_seconds: int = Field(default=300)
    max_retries: int = Field(default=3)
    log_level: str = Field(default="INFO")

    # Domain configurations (composition, not inheritance)
    storage: StorageConfig
    database: DatabaseConfig
    raster: RasterConfig
    vector: VectorConfig
    queues: QueueConfig

    # Legacy fields for backward compatibility during migration
    # These delegate to domain configs
    @property
    def postgis_host(self) -> str:
        """Legacy compatibility - use database.host instead."""
        return self.database.host

    @property
    def raster_cog_compression(self) -> str:
        """Legacy compatibility - use raster.cog_compression instead."""
        return self.raster.cog_compression

    # ... add more legacy properties as needed during migration

    @classmethod
    def from_environment(cls):
        """Load all configs from environment."""
        return cls(
            storage=StorageConfig.from_environment(),
            database=DatabaseConfig.from_environment(),
            raster=RasterConfig.from_environment(),
            vector=VectorConfig.from_environment(),
            queues=QueueConfig.from_environment()
        )
```

**config/__init__.py** (100 lines):
```python
"""Configuration management - exports for backward compatibility."""

# Export domain configs
from .storage_config import (
    CogTier,
    CogTierProfile,
    StorageConfig,
    determine_applicable_tiers
)
from .database_config import DatabaseConfig, get_postgres_connection_string
from .raster_config import RasterConfig
from .vector_config import VectorConfig
from .queue_config import QueueConfig, QueueNames
from .app_config import AppConfig

# Singleton pattern
_config_instance: Optional[AppConfig] = None

def get_config() -> AppConfig:
    """Get global configuration - backward compatible."""
    global _config_instance
    if _config_instance is None:
        _config_instance = AppConfig.from_environment()
    return _config_instance

def debug_config() -> dict:
    """Debug output with masked passwords."""
    config = get_config()
    return {
        "storage": config.storage.dict(),
        "database": config.database.debug_dict(),
        "raster": config.raster.dict(),
        "vector": config.vector.dict(),
        "queues": {"connection": "***MASKED***"}
    }

__all__ = [
    'AppConfig', 'get_config', 'debug_config',
    'CogTier', 'CogTierProfile', 'StorageConfig', 'determine_applicable_tiers',
    'DatabaseConfig', 'get_postgres_connection_string',
    'RasterConfig', 'VectorConfig',
    'QueueConfig', 'QueueNames'
]
```

**Step 1.3: Test new config modules**
```python
# test_new_config.py
from config import get_config, CogTier, QueueNames

config = get_config()

# Test composition
assert config.database.host is not None
assert config.raster.cog_compression == "deflate"
assert config.storage.storage is not None

# Test backward compatibility properties
assert config.postgis_host == config.database.host
assert config.raster_cog_compression == config.raster.cog_compression

print("✅ New config modules working!")
```

---

#### Phase 2: Parallel Operation & Testing (2 hours)

**Step 2.1: Both configs operational**

At this point, BOTH import patterns work:
```python
# OLD PATTERN (still works via backward compatibility)
from config import get_config
config = get_config()
host = config.postgis_host  # Legacy property

# NEW PATTERN (preferred)
from config import get_config
config = get_config()
host = config.database.host  # Direct domain access
```

**Step 2.2: Test with existing code**

Run full test suite to ensure nothing breaks:
```bash
# Deploy to Azure
func azure functionapp publish rmhazuregeoapi --python --build remote

# Test health endpoint
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health

# Test job submission (uses config extensively)
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "test"}'

# Verify: Check logs for config access patterns
```

---

#### Phase 3: Migrate Code to New Pattern (2-3 hours)

**Step 3.1: Prioritize files by domain**

**Raster pipeline files** (migrate to `config.raster`):
- services/raster_cog.py
- services/raster_validation.py
- services/handler_create_cog.py
- jobs/process_raster.py

**Vector pipeline files** (migrate to `config.vector`):
- services/vector/postgis_handler.py
- jobs/ingest_vector.py

**Database files** (migrate to `config.database`):
- infrastructure/postgresql.py
- triggers/db_query.py

**Step 3.2: Migrate one domain at a time**

Example: Migrate raster pipeline first
```python
# BEFORE (services/raster_cog.py)
from config import get_config
config = get_config()
compression = config.raster_cog_compression  # Legacy property

# AFTER
from config import get_config
config = get_config()
compression = config.raster.cog_compression  # Direct domain access
```

**Step 3.3: Test after each domain migration**
- Migrate raster files → test raster job → commit
- Migrate vector files → test vector job → commit
- Migrate database files → test schema operations → commit

---

#### Phase 4: Remove Legacy Code (1 hour)

**Step 4.1: Remove backward compatibility properties**

Once all code migrated, remove from config/app_config.py:
```python
# DELETE these legacy properties
@property
def postgis_host(self) -> str:
    return self.database.host

@property
def raster_cog_compression(self) -> str:
    return self.raster.cog_compression
```

**Step 4.2: Delete old config.py**

```bash
# Backup first (just in case)
cp config.py config.py.old

# Delete old monolithic config
git rm config.py

# config/ folder is now the only config source
```

**Step 4.3: Update imports across codebase**

```bash
# Find any remaining old-style imports
grep -r "from config import" --include="*.py" .

# Should only find:
# - from config import get_config
# - from config import CogTier, QueueNames, etc.

# All using new config/ package
```

**Step 4.4: Final deployment & testing**

```bash
func azure functionapp publish rmhazuregeoapi --python --build remote

# Run full test suite
curl .../api/health
curl .../api/jobs/submit/hello_world
curl .../api/jobs/submit/ingest_vector
curl .../api/jobs/submit/process_raster
```

---

### Task Checklist

#### Phase 1: Create New Config Modules
- [ ] Create config/ folder structure (7 files)
- [ ] Implement config/storage_config.py (copy COG tiers, storage classes)
- [ ] Implement config/database_config.py (extract database fields)
- [ ] Implement config/raster_config.py (extract raster fields)
- [ ] Implement config/vector_config.py (extract vector fields)
- [ ] Implement config/queue_config.py (extract queue fields)
- [ ] Implement config/app_config.py (composition with legacy properties)
- [ ] Implement config/__init__.py (exports for backward compatibility)
- [ ] Write test_new_config.py (verify new modules work)
- [ ] Test: Both old and new import patterns work
- [ ] Commit: "Add new config/ package (parallel to old config.py)"

#### Phase 2: Parallel Operation & Testing
- [ ] Deploy to Azure with both configs active
- [ ] Test health endpoint (uses config extensively)
- [ ] Test hello_world job (validates config access)
- [ ] Test process_raster job (validates raster config)
- [ ] Test ingest_vector job (validates vector config)
- [ ] Verify Application Insights logs (no config errors)
- [ ] Commit: "Verify parallel config operation in production"

#### Phase 3: Migrate Code to New Pattern
- [ ] Migrate raster pipeline files (5-7 files)
  - [ ] services/raster_cog.py
  - [ ] services/raster_validation.py
  - [ ] jobs/process_raster.py
  - [ ] Test: process_raster job still works
  - [ ] Commit: "Migrate raster pipeline to config.raster"
- [ ] Migrate vector pipeline files (3-5 files)
  - [ ] services/vector/postgis_handler.py
  - [ ] jobs/ingest_vector.py
  - [ ] Test: ingest_vector job still works
  - [ ] Commit: "Migrate vector pipeline to config.vector"
- [ ] Migrate database files (3-4 files)
  - [ ] infrastructure/postgresql.py
  - [ ] triggers/db_query.py
  - [ ] Test: Schema redeploy still works
  - [ ] Commit: "Migrate database code to config.database"
- [ ] Migrate remaining files (grep for legacy properties)
- [ ] Commit: "Complete migration to new config/ package"

#### Phase 4: Remove Legacy Code
- [ ] Remove legacy @property methods from config/app_config.py
- [ ] Test: Ensure no code still uses legacy properties
- [ ] Delete old config.py (backup first!)
- [ ] Update all remaining imports (should be minimal)
- [ ] Final deployment to Azure
- [ ] Full regression testing (all jobs, all endpoints)
- [ ] Update documentation (FILE_CATALOG.md, ARCHITECTURE_REFERENCE.md)
- [ ] Commit: "Remove old config.py - migration complete"

---

### Expected Benefits

| Metric | Before | After |
|--------|--------|-------|
| **AppConfig size** | 1,090 lines (63+ fields) | 150 lines (5 composed configs) |
| **Find raster setting** | Search 1,747 lines | Look in config/raster_config.py (250 lines) |
| **Test raster code** | Mock all 63+ fields | Only mock RasterConfig (15 fields) |
| **Merge conflicts** | High (everyone edits AppConfig) | Low (different files per domain) |
| **Clear dependencies** | Unclear (everything in one class) | Obvious (import only what you need) |

### Risk Mitigation

**Low Risk Strategy**:
1. ✅ New code runs alongside old code (both operational)
2. ✅ Backward compatibility via legacy properties (nothing breaks)
3. ✅ Incremental migration (one domain at a time, tested)
4. ✅ Old config.py deleted LAST (after everything migrated)

**Rollback Plan**:
- If issues discovered: Keep using legacy properties while debugging
- If critical failure: Revert to old config.py (single file)
- Git history preserves all migration steps for analysis

---

## 🎯 CURRENT PRIORITY - process_raster_collection Job

**Status**: Ready to implement
**Purpose**: Multi-raster collection processing with TiTiler search URLs

### Analysis (18 NOV 2025 03:50 UTC)

**The Sequence**:
1. `stac_collection.py:326` → `PgStacRepository().insert_collection()` ✅ Succeeds
2. `stac_collection.py:335` → `PgStacInfrastructure().collection_exists()` ❌ Returns False
3. Code raises: "Collection not found in PgSTAC after insertion"

**The Problem**:
- `PgStacRepository` and `PgStacInfrastructure` both create **separate** `PostgreSQLRepository` instances
- Each instance = separate connection context
- INSERT commits on Connection A, SELECT queries on Connection B
- Possible transaction isolation or connection pooling visibility issue

### Immediate Fix Required

**Quick Fix** (services/stac_collection.py lines 325-341):
```python
# BEFORE (current broken pattern):
pgstac_id = _insert_into_pgstac_collections(collection_dict)  # Creates PgStacRepository
stac_service = StacMetadataService()  # Creates PgStacInfrastructure
if not stac_service.stac.collection_exists(collection_id):  # Different connection!
    raise RuntimeError("Collection not found...")

# AFTER (single repository instance):
repo = PgStacRepository()  # Create ONCE
collection = Collection.from_dict(collection_dict)
pgstac_id = repo.insert_collection(collection)  # Use it for insert
if not repo.collection_exists(collection_id):  # Use SAME instance for verification
    raise RuntimeError("Collection not found...")
```

### Long-Term Architectural Fix - Consolidate PgSTAC Classes

**Current Duplication** (18 NOV 2025 analysis):

| Class | Lines | Purpose | Issues |
|-------|-------|---------|--------|
| **PgStacRepository** | 390 | Collections/Items CRUD | ✅ Clean, focused, newer (12 NOV) |
| **PgStacInfrastructure** | 2,060 | Setup + Operations + Queries | ❌ Bloated, duplicates PgStacRepository methods |

**Duplicate Methods Found**:
- `collection_exists()` - **THREE copies** (PgStacRepository:214, PgStacInfrastructure:802, PgStacInfrastructure:943)
- `insert_item()` - **TWO copies** (PgStacRepository:247, PgStacInfrastructure:880)

**Root Cause**: PgStacInfrastructure was created first (4 OCT), PgStacRepository added later (12 NOV) but old methods never removed

### Refactoring Plan - Rename & Consolidate

**Step 1: Rename PgStacInfrastructure → PgStacBootstrap**
- Clarifies purpose: schema setup, installation, verification
- Filename: `infrastructure/stac.py` → `infrastructure/pgstac_bootstrap.py`
- Class: `PgStacInfrastructure` → `PgStacBootstrap`

**Step 2: Move ALL Data Operations to PgStacRepository**

**PgStacBootstrap** (setup/installation ONLY):
- ✅ Keep: `check_installation()`, `install_pgstac()`, `verify_installation()`, `_drop_pgstac_schema()`, `_run_pypgstac_migrate()`
- ✅ Keep: Standalone query functions for admin/diagnostics (`get_collection()`, `get_collection_items()`, `search_items()`, etc.)
- ❌ Remove: `collection_exists()` (duplicate)
- ❌ Remove: `item_exists()` (duplicate)
- ❌ Remove: `insert_item()` (duplicate)
- ❌ Remove: `create_collection()` (data operation, not setup)

**PgStacRepository** (ALL data operations):
- ✅ Keep: All existing methods (`insert_collection()`, `update_collection_metadata()`, `collection_exists()`, `insert_item()`, `get_collection()`, `list_collections()`)
- ➕ Add: `bulk_insert_items()` (move from PgStacBootstrap)
- ➕ Add: `item_exists()` (if not already present)

**Step 3: Update All Imports**
- Search codebase for `from infrastructure.stac import PgStacInfrastructure`
- Replace with `from infrastructure.pgstac_repository import PgStacRepository` where data operations are used
- Replace with `from infrastructure.pgstac_bootstrap import PgStacBootstrap` where setup/admin functions are used

**Step 4: Fix StacMetadataService**
- Change `self.stac = PgStacInfrastructure()` to `self.stac = PgStacRepository()`
- This ensures single repository pattern throughout

### Task Breakdown

- [ ] **CRITICAL**: Implement quick fix in stac_collection.py (single repository instance)
- [ ] Test quick fix with new job submission
- [ ] Rename infrastructure/stac.py → infrastructure/pgstac_bootstrap.py
- [ ] Rename class PgStacInfrastructure → PgStacBootstrap
- [ ] Remove duplicate methods from PgStacBootstrap (collection_exists, insert_item, item_exists, create_collection)
- [ ] Add bulk_insert_items to PgStacRepository (if needed)
- [ ] Update all imports (search for PgStacInfrastructure, replace appropriately)
- [ ] Fix StacMetadataService to use PgStacRepository
- [ ] Test end-to-end STAC collection creation
- [ ] Update documentation (FILE_CATALOG.md, ARCHITECTURE_REFERENCE.md)
- [ ] Commit: "Consolidate PgSTAC: Rename to Bootstrap, eliminate duplication"

### Expected Benefits

1. ✅ **Fixes "Collection not found" error** - single repository instance eliminates READ AFTER WRITE issue
2. ✅ **Eliminates duplication** - removes 3 duplicate method implementations
3. ✅ **Clearer architecture** - PgStacBootstrap = setup, PgStacRepository = data operations
4. ✅ **Easier maintenance** - no more confusion about which class to use
5. ✅ **Better testability** - single repository pattern easier to mock

---

## 🚨 CRITICAL NEXT WORK - Repository Pattern Enforcement (16 NOV 2025)

**Purpose**: Eliminate all direct database connections, enforce repository pattern
**Status**: 🟡 **IN PROGRESS** - Managed identity operational, service files remain
**Priority**: **HIGH** - Complete repository pattern migration for maintainability
**Root Cause**: 5+ service files bypass PostgreSQLRepository, directly manage connections

**✅ Managed Identity Status**: Operational in production (15 NOV 2025)
**📘 Documentation**: See [QA_DEPLOYMENT.md](../QA_DEPLOYMENT.md) lines 361-438 for setup guide

### Architecture Violation

**Current Broken Pattern**:
```python
# ❌ VIOLATES REPOSITORY PATTERN
from config import get_postgres_connection_string
conn_str = get_postgres_connection_string()  # Creates repo, throws it away
with psycopg.connect(conn_str) as conn:      # Manages connection directly
    cur.execute("SELECT ...")                 # Bypasses repository
```

**Problems**:
1. PostgreSQLRepository created just to extract connection string
2. Connection management scattered across 10+ files
3. Can't centralize: pooling, retry logic, monitoring, token refresh
4. Violates single responsibility - repository should manage connections
5. Makes testing harder - can't mock repository

**Correct Pattern**:
```python
# ✅ REPOSITORY PATTERN - ONLY ALLOWED PATTERN
from infrastructure.postgresql import PostgreSQLRepository

# Option 1: Use repository methods (PREFERRED)
repo = PostgreSQLRepository()
job = repo.get_job(job_id)  # Repository manages connection internally

# Option 2: Raw SQL via repository connection manager (ALLOWED)
repo = PostgreSQLRepository()
with repo._get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT ...")
```

---

## CRITICAL ETL FILES - IMMEDIATE REFACTORING REQUIRED

### Priority 1: Schema Management (BLOCKING SCHEMA REDEPLOY)

**1. triggers/schema_pydantic_deploy.py** (lines 283-287)
- **Current**: `get_postgres_connection_string()` + `psycopg.connect()`
- **Fix**: Use `PostgreSQLRepository._get_connection()` context manager
- **Impact**: Schema deployment failing (36 statements fail due to "already exists")
- **Blocking**: YES - prevents nuke operation

**2. triggers/db_query.py** (lines 139-141, 1017-1019)
- **Current**: `DatabaseQueryTrigger._get_database_connection()` builds connection directly
- **Fix**: Make `_get_database_connection()` use `PostgreSQLRepository._get_connection()`
- **Impact**: All database query endpoints + nuke operation broken
- **Blocking**: YES - nuke returns 0 objects dropped

**3. core/schema/deployer.py** (lines 102-103)
- **Current**: `SchemaManager._build_connection_string()` returns connection string
- **Fix**: Replace with `PostgreSQLRepository._get_connection()` context manager
- **Impact**: Schema management utilities broken
- **Blocking**: YES - used by nuke operation

**4. infrastructure/postgis.py** (lines 57-71)
- **Current**: `check_table_exists()` uses `get_postgres_connection_string()`
- **Fix**: Create `PostgreSQLRepository`, use `_get_connection()`
- **Impact**: Table existence checks (used in validation)
- **Blocking**: NO - but needed for production readiness

---

### Priority 2: STAC Metadata Pipeline (CORE ETL)

**5. infrastructure/stac.py** (10+ direct connections)
- **Lines**: 1082-1083, 1140-1141, 1193-1194, 1283-1284, 1498-1499, 1620-1621, 1746-1747, 1816-1817, 1898-1899, 2000-2001
- **Current**: Every function creates connection via `get_postgres_connection_string()`
- **Fix**: Create `PgSTACRepository` class that wraps pgstac operations
- **Impact**: ALL STAC operations (collections, items, search)
- **Blocking**: YES - STAC is core metadata layer

**6. services/stac_collection.py** (line 617-620)
- **Current**: Uses `get_postgres_connection_string()` for pgstac operations
- **Fix**: Use `PgSTACRepository` (after creating it from #5)
- **Impact**: STAC collection creation
- **Blocking**: YES - needed for dataset ingestion

**7. services/service_stac_vector.py** (lines 181-183)
- **Current**: Direct connection for vector → STAC ingestion
- **Fix**: Use `PgSTACRepository`
- **Impact**: Vector data STAC indexing
- **Blocking**: YES - core ETL pipeline

**8. services/service_stac_setup.py** (lines 56-57)
- **Current**: `get_connection_string()` wrapper around `get_postgres_connection_string()`
- **Fix**: Delete function, use `PgSTACRepository`
- **Impact**: pgstac installation
- **Blocking**: NO - setup only

---

### Priority 3: Vector Ingestion Handlers

**9. services/vector/postgis_handler.py** (lines 55-59)
- **Current**: Stores `self.conn_string` in constructor, creates connections in methods
- **Fix**: Store `self.repo = PostgreSQLRepository()`, use `repo._get_connection()`
- **Impact**: Vector data ingestion to PostGIS
- **Blocking**: YES - primary ingestion path

**10. services/vector/postgis_handler_enhanced.py** (lines 88-92)
- **Current**: Same pattern as postgis_handler.py
- **Fix**: Same fix - use repository
- **Impact**: Enhanced vector ingestion
- **Blocking**: YES - used for complex vector datasets

---

## IMPLEMENTATION STEPS

### Step 1: Fix PostgreSQLRepository (✅ COMPLETED - 16 NOV 2025)
- [x] Remove fallback logic (no password fallback) - DONE
- [x] Use environment variable `MANAGED_IDENTITY_NAME` with fallback to `WEBSITE_SITE_NAME`
- [x] Environment variable set in Azure: `MANAGED_IDENTITY_NAME=rmhazuregeoapi`
- [x] NO fallbacks - fails immediately if token acquisition fails
- [x] **PostgreSQL user `rmhazuregeoapi` created** - Operational in production (15 NOV 2025)

### Step 2: Create PgSTACRepository Class (NEW)
**File**: `infrastructure/pgstac_repository.py` (refactor existing)
```python
class PgSTACRepository:
    """Repository for pgstac operations - wraps all STAC database operations."""

    def __init__(self):
        self.repo = PostgreSQLRepository()  # Delegate to PostgreSQL repo

    def list_collections(self) -> List[Dict]:
        with self.repo._get_connection() as conn:
            # pgstac collection listing logic

    def get_collection(self, collection_id: str) -> Dict:
        with self.repo._get_connection() as conn:
            # pgstac collection retrieval logic

    # ... all other pgstac operations
```

### Step 3: Fix Schema Management Files (COMPLETED - 16 NOV 2025)
1. ✅ **triggers/schema_pydantic_deploy.py**:
   ```python
   # OLD
   from config import get_postgres_connection_string
   conn_string = get_postgres_connection_string()
   conn = psycopg.connect(conn_string)

   # NEW
   from infrastructure.postgresql import PostgreSQLRepository
   repo = PostgreSQLRepository()
   with repo._get_connection() as conn:
       # Execute schema statements
   ```

2. ✅ **triggers/db_query.py**:
   ```python
   # OLD
   def _get_database_connection(self):
       from config import get_postgres_connection_string
       conn_str = get_postgres_connection_string()
       return psycopg.connect(conn_str)

   # NEW
   def _get_database_connection(self):
       from infrastructure.postgresql import PostgreSQLRepository
       repo = PostgreSQLRepository()
       return repo._get_connection()  # Returns context manager
   ```

3. ✅ **core/schema/deployer.py**:
   ```python
   # OLD
   def _build_connection_string(self) -> str:
       from config import get_postgres_connection_string
       return get_postgres_connection_string()

   # NEW
   def _get_connection(self):
       from infrastructure.postgresql import PostgreSQLRepository
       repo = PostgreSQLRepository()
       return repo._get_connection()
   ```

### Step 4: Migrate STAC Files to PgSTACRepository
- Update `infrastructure/stac.py` to use `PgSTACRepository` methods
- Update `services/stac_collection.py`
- Update `services/service_stac_vector.py`

### Step 5: Fix Vector Handlers
- Update `services/vector/postgis_handler.py`
- Update `services/vector/postgis_handler_enhanced.py`

### Step 6: Delete get_postgres_connection_string() Helper
**File**: `config.py` (line 1666-1747)
- **After all files migrated**, delete the helper function
- This enforces repository pattern at compile time

### Step 7: Deploy and Test
```bash
# Deploy
func azure functionapp publish rmhazuregeoapi --python --build remote

# Test schema redeploy (should work 100%)
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes"

# Test STAC
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/collections"

# Test OGC Features
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections"
```

---

## NOT TOUCHING (Lower Priority)

### H3 Grid System (not core ETL)
- `services/handler_h3_native_streaming.py` - Can refactor later
- `services/handler_create_h3_stac.py` - Can refactor later

### OGC Features API (separate module)
- `ogc_features/config.py` - Already standalone, can refactor later

---

## ✅ MANAGED IDENTITY - USER-ASSIGNED PATTERN (22 NOV 2025)

**Status**: ✅ Configured with automatic credential detection
**Architecture**: User-assigned identity `rmhpgflexadmin` for read/write/admin database access
**Documentation**: See [QA_DEPLOYMENT.md](../QA_DEPLOYMENT.md) lines 361-438 for complete setup guide

### Authentication Priority Chain (NEW - 22 NOV 2025)

The system automatically detects and uses credentials in this order:

1. **User-Assigned Managed Identity** - If `MANAGED_IDENTITY_CLIENT_ID` is set
2. **System-Assigned Managed Identity** - If running in Azure (detected via `WEBSITE_SITE_NAME`)
3. **Password Authentication** - If `POSTGIS_PASSWORD` is set
4. **FAIL** - Clear error message with instructions

This allows the same codebase to work in:
- Azure Functions with user-assigned identity (production - recommended)
- Azure Functions with system-assigned identity (simpler setup)
- Local development with password (developer machines)

### Identity Strategy

**User-Assigned (RECOMMENDED)** - Single identity shared across multiple apps:
- `rmhpgflexadmin` - Read/write/admin access (Function App, etc.)
- `rmhpgflexreader` (future) - Read-only access (TiTiler, OGC/STAC apps)

**Benefits**:
- Single identity for multiple apps (easier to manage)
- Identity persists even if app is deleted
- Can grant permissions before app deployment
- Cleaner separation of concerns

### Environment Variables

```bash
# For User-Assigned Identity (production)
MANAGED_IDENTITY_CLIENT_ID=<client-id>        # From Azure Portal → Managed Identities
MANAGED_IDENTITY_NAME=rmhpgflexadmin          # PostgreSQL user name

# For System-Assigned Identity (auto-detected in Azure)
# No env vars needed - WEBSITE_SITE_NAME is set automatically

# For Local Development
POSTGIS_PASSWORD=<password>                   # Password auth fallback
```

### Azure Setup Required

**1. Create PostgreSQL user for managed identity**:
```sql
-- As Entra admin
SELECT * FROM pgaadauth_create_principal('rmhpgflexadmin', false, false);
GRANT ALL PRIVILEGES ON SCHEMA geo TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON SCHEMA app TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON SCHEMA platform TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON SCHEMA pgstac TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON SCHEMA h3 TO rmhpgflexadmin;

-- Grant on existing tables
GRANT ALL ON ALL TABLES IN SCHEMA geo TO rmhpgflexadmin;
GRANT ALL ON ALL TABLES IN SCHEMA app TO rmhpgflexadmin;
GRANT ALL ON ALL TABLES IN SCHEMA platform TO rmhpgflexadmin;
GRANT ALL ON ALL TABLES IN SCHEMA pgstac TO rmhpgflexadmin;
GRANT ALL ON ALL TABLES IN SCHEMA h3 TO rmhpgflexadmin;

-- Default for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT ALL ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL ON TABLES TO rmhpgflexadmin;
-- etc.
```

**2. Assign identity to Function App** (Azure Portal or CLI):
```bash
# Assign existing user-assigned identity
az functionapp identity assign \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --identities /subscriptions/{sub}/resourcegroups/rmhazure_rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/rmhpgflexadmin
```

**3. Configure environment variables**:
```bash
az functionapp config appsettings set \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --settings \
    USE_MANAGED_IDENTITY=true \
    MANAGED_IDENTITY_NAME=rmhpgflexadmin \
    MANAGED_IDENTITY_CLIENT_ID=<client-id-from-portal>
```

### Files Updated (22 NOV 2025)
- `config/database_config.py` - Added `managed_identity_client_id` field
- `infrastructure/postgresql.py` - Updated to use user-assigned identity by default

### Previous Production Setup (15 NOV 2025)
- ✅ PostgreSQL user `rmhazuregeoapi` created with pgaadauth
- ✅ All schema permissions granted (app, geo, pgstac, h3)
- ✅ Function App managed identity enabled
- ✅ Environment variable `USE_MANAGED_IDENTITY=true` configured
- ✅ PostgreSQLRepository using ManagedIdentityCredential
- ✅ Token refresh working (automatic hourly rotation)

**For New Environments** (QA/Production):

See [QA_DEPLOYMENT.md](../QA_DEPLOYMENT.md) section "Managed Identity for Database Connections" for complete setup instructions including:
- Azure CLI commands to enable managed identity
- PostgreSQL user creation script
- Environment variable configuration
- Verification steps

**Quick Setup** (for reference):
```bash
# 1. Enable managed identity on Function App
az functionapp identity assign --name <app-name> --resource-group <rg>

# 2. Create PostgreSQL user (as Entra admin)
psql "host=<server>.postgres.database.azure.com dbname=<db> sslmode=require"
SELECT pgaadauth_create_principal('<app-name>', false, false);
# ... grant permissions (see QA_DEPLOYMENT.md)

# 3. Configure Function App
az functionapp config appsettings set --name <app-name> \
  --settings USE_MANAGED_IDENTITY=true
```

---

## Current Status (16 NOV 2025 - 22:25 UTC)

### ✅ COMPLETED - Phase 1: Schema Management (Critical Path)
- ✅ Fixed PostgreSQLRepository:
  - Changed from `DefaultAzureCredential` → `ManagedIdentityCredential` (explicit control)
  - Removed ALL fallback logic (no password fallback)
  - Uses `MANAGED_IDENTITY_NAME` env var (value: `rmhazuregeoapi`)
  - Supports user-assigned identities via `MANAGED_IDENTITY_CLIENT_ID`
  - Fails immediately if token acquisition fails
- ✅ Fixed PostgreSQL ownership (all app schema objects owned by `rmhazuregeoapi`)
- ✅ Refactored 4 critical schema management files:
  - triggers/schema_pydantic_deploy.py
  - triggers/db_query.py
  - core/schema/deployer.py
  - infrastructure/postgis.py
- ✅ Deployed to Azure (16 NOV 2025 20:49 UTC)
- ✅ **VERIFIED WORKING**:
  - Schema redeploy: 100% success (38/38 statements)
  - Nuke operation: Works perfectly
  - Hello world job: Completed successfully
  - Managed identity authentication: Operational

### ✅ COMPLETED - Phase 2A: STAC Infrastructure (16 NOV 2025 23:20 UTC)
- ✅ **infrastructure/stac.py**: Refactored all 9 standalone functions (10 occurrences):
  - get_collection() - Added optional repo parameter
  - get_collection_items() - Added optional repo parameter
  - search_items() - Added optional repo parameter
  - get_schema_info() - Added optional repo parameter
  - get_collection_stats() - Added optional repo parameter
  - get_item_by_id() - Added optional repo parameter
  - get_health_metrics() - Added optional repo parameter
  - get_collections_summary() - Added optional repo parameter
  - get_all_collections() - Added optional repo parameter (removed duplicate, kept better implementation)
- ✅ All functions use repository pattern with dependency injection
- ✅ Backward compatible (repo parameter optional)
- ✅ Compiled successfully (python3 -m py_compile)
- ✅ ZERO remaining `get_postgres_connection_string()` calls in infrastructure/stac.py

### 🔴 REMAINING - Phase 2B: STAC Service Files (NEXT)
- ⏳ services/stac_collection.py
- ⏳ services/service_stac_vector.py
- ⏳ services/service_stac_setup.py
- ⏳ services/vector/postgis_handler.py
- ⏳ services/vector/postgis_handler_enhanced.py

### 📋 NEXT STEPS - STAC Infrastructure Refactoring

**Phase 2A: Fix infrastructure/stac.py (10 direct connections - BLOCKING STAC JOBS)**

The file has TWO usage patterns that need different fixes:

**Pattern 1: Class Methods (lines 140-166, already correct)**
- `PgStacInfrastructure.__init__()` already creates `self._pg_repo = PostgreSQLRepository()`
- `check_installation()`, `verify_installation()`, etc. already use `self._pg_repo._get_connection()`
- ✅ NO CHANGES NEEDED - already using repository pattern correctly

**Pattern 2: Standalone Functions (10 violations)**
These are module-level functions that bypass the repository pattern:

1. **get_all_collections()** (lines 1082-1083, 2000-2001) - 2 occurrences
   - Fix: Accept optional `repo` parameter, default to creating new PostgreSQLRepository

2. **get_collection()** (lines 1140-1141)
   - Fix: Same pattern - accept optional `repo` parameter

3. **get_collection_items()** (lines 1193-1194)
   - Fix: Same pattern - accept optional `repo` parameter

4. **search_items()** (lines 1283-1284)
   - Fix: Same pattern - accept optional `repo` parameter

5. **get_schema_info()** (lines 1498-1499)
   - Fix: Same pattern - accept optional `repo` parameter

6. **get_collection_stats()** (lines 1620-1621)
   - Fix: Same pattern - accept optional `repo` parameter

7. **get_item_by_id()** (lines 1746-1747)
   - Fix: Same pattern - accept optional `repo` parameter

8. **get_health_metrics()** (lines 1816-1817)
   - Fix: Same pattern - accept optional `repo` parameter

9. **get_collections_summary()** (lines 1898-1899)
   - Fix: Same pattern - accept optional `repo` parameter

**Refactoring Pattern**:
```python
# OLD
def get_all_collections() -> Dict[str, Any]:
    from config import get_postgres_connection_string
    connection_string = get_postgres_connection_string()
    with psycopg.connect(connection_string) as conn:
        # ... query logic

# NEW
def get_all_collections(repo: Optional[PostgreSQLRepository] = None) -> Dict[str, Any]:
    if repo is None:
        from infrastructure.postgresql import PostgreSQLRepository
        repo = PostgreSQLRepository()

    with repo._get_connection() as conn:
        # ... query logic (unchanged)
```

**Why This Pattern**:
- Allows dependency injection for testing
- Backward compatible (callers can omit repo parameter)
- Repository creates managed identity connection automatically
- No need for PgSTACRepository wrapper - these are already pgstac-schema-aware functions

**Phase 2B: Update STAC service files**
- services/stac_collection.py
- services/service_stac_vector.py
- services/service_stac_setup.py

**Phase 2C: Update vector handlers**
- services/vector/postgis_handler.py
- services/vector/postgis_handler_enhanced.py

**Phase 2D: Final cleanup**
- Delete `get_postgres_connection_string()` helper (after all migrations complete)

---

## 🌍 MEDIUM PRIORITY - ISO3 Country Attribution in STAC Items (21 NOV 2025)

**Status**: Planned - Ready for implementation
**Purpose**: Add ISO3 country codes to STAC item metadata during creation
**Priority**: MEDIUM (enriches metadata, enables country-based filtering)
**Effort**: 2-3 hours
**Requested By**: Robert (21 NOV 2025)

### Problem Statement

**Current State**: STAC items are created WITHOUT country/ISO3 attribution:
- Raster items ([services/service_stac_metadata.py](../services/service_stac_metadata.py)) extract bbox, geometry, projection
- Vector items ([services/service_stac_vector.py](../services/service_stac_vector.py)) extract extent, row count, geometry types
- **Neither includes which country the data is located in**

**Desired State**: STAC items should include:
```json
{
  "properties": {
    "geo:iso3": ["USA"],
    "geo:primary_iso3": "USA",
    "geo:countries": ["United States of America"]
  }
}
```

### Existing Infrastructure

**The `geo.system_admin0_boundaries` table is already configured** in [config/h3_config.py:145-152](../config/h3_config.py):
```python
system_admin0_table: str = Field(
    default="geo.system_admin0_boundaries",
    description="PostGIS table containing admin0 (country) boundaries..."
)
```

**Expected schema** (from H3 code patterns in [infrastructure/h3_repository.py:352](../infrastructure/h3_repository.py)):
- `iso3` VARCHAR(3) - ISO 3166-1 alpha-3 country code
- `geom` GEOMETRY - Country boundary polygons (WGS84)
- Optional: `name` - Country name

**H3 already uses this for spatial joins**:
```sql
UPDATE h3.grids h
SET country_code = c.iso3
FROM geo.system_admin0 c
WHERE ST_Intersects(h.geom, c.geom)
```

### Implementation Plan

#### Step 1: Add Spatial Config (Optional - Use H3 Config)

**Option A**: Reuse existing H3 config (RECOMMENDED - less code)
```python
# In service methods, access via:
from config import get_config
config = get_config()
admin0_table = config.h3.system_admin0_table  # "geo.system_admin0_boundaries"
```

**Option B**: Create dedicated spatial config (if needed for separation)
```python
# config/spatial_config.py
class SpatialConfig(BaseModel):
    admin0_table: str = Field(default="geo.system_admin0_boundaries")
    iso3_column: str = Field(default="iso3")
    name_column: str = Field(default="name")
    enable_country_attribution: bool = Field(default=True)
```

#### Step 2: Add Helper Method to StacMetadataService

**File**: [services/service_stac_metadata.py](../services/service_stac_metadata.py) (after line 591)

```python
def _get_countries_for_bbox(self, bbox: List[float]) -> Dict[str, Any]:
    """
    Get ISO3 codes for countries intersecting the given bounding box.

    Uses ST_Intersects with the bbox envelope to find all countries
    that overlap with the STAC item's spatial extent.

    For items spanning multiple countries (e.g., border regions),
    returns all intersecting countries with the primary determined
    by centroid point-in-polygon.

    Args:
        bbox: [minx, miny, maxx, maxy] in EPSG:4326

    Returns:
        {
            "iso3_list": ["USA", "CAN"],  # All intersecting countries
            "primary_iso3": "USA",         # Country containing centroid
            "country_names": ["United States", "Canada"]
        }
    """
    from config import get_config
    from infrastructure.postgresql import PostgreSQLRepository
    from psycopg import sql

    config = get_config()
    admin0_table = config.h3.system_admin0_table  # "geo.system_admin0_boundaries"

    # Parse schema.table
    if '.' in admin0_table:
        schema, table = admin0_table.split('.', 1)
    else:
        schema, table = 'geo', admin0_table

    minx, miny, maxx, maxy = bbox
    centroid_x = (minx + maxx) / 2
    centroid_y = (miny + maxy) / 2

    repo = PostgreSQLRepository()

    try:
        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Query 1: All countries intersecting bbox
                query_intersects = sql.SQL("""
                    SELECT iso3, name
                    FROM {schema}.{table}
                    WHERE ST_Intersects(
                        geom,
                        ST_MakeEnvelope(%s, %s, %s, %s, 4326)
                    )
                    ORDER BY iso3
                """).format(
                    schema=sql.Identifier(schema),
                    table=sql.Identifier(table)
                )
                cur.execute(query_intersects, [minx, miny, maxx, maxy])
                rows = cur.fetchall()

                iso3_list = [r['iso3'] for r in rows if r.get('iso3')]
                country_names = [r['name'] for r in rows if r.get('name')]

                # Query 2: Primary country (centroid point-in-polygon)
                primary_iso3 = None
                if iso3_list:
                    query_centroid = sql.SQL("""
                        SELECT iso3
                        FROM {schema}.{table}
                        WHERE ST_Contains(geom, ST_Point(%s, %s, 4326))
                        LIMIT 1
                    """).format(
                        schema=sql.Identifier(schema),
                        table=sql.Identifier(table)
                    )
                    cur.execute(query_centroid, [centroid_x, centroid_y])
                    result = cur.fetchone()
                    primary_iso3 = result['iso3'] if result else iso3_list[0]

                return {
                    "iso3_list": iso3_list,
                    "primary_iso3": primary_iso3,
                    "country_names": country_names
                }

    except Exception as e:
        logger.warning(f"Country attribution failed (non-critical): {e}")
        return {
            "iso3_list": [],
            "primary_iso3": None,
            "country_names": []
        }
```

#### Step 3: Integrate into extract_item_from_blob()

**File**: [services/service_stac_metadata.py](../services/service_stac_metadata.py)

**Location**: After STEP G.1 (required STAC fields), before STEP G.5 (asset URL conversion)

Add new **STEP G.2: Country Attribution**:

```python
# STEP G.2: Add country attribution (ISO3 codes)
try:
    logger.debug("   Step G.2: Adding country attribution...")
    bbox = item_dict.get('bbox')
    if bbox and len(bbox) == 4:
        country_info = self._get_countries_for_bbox(bbox)

        if country_info['iso3_list']:
            item_dict['properties']['geo:iso3'] = country_info['iso3_list']
            item_dict['properties']['geo:primary_iso3'] = country_info['primary_iso3']
            if country_info['country_names']:
                item_dict['properties']['geo:countries'] = country_info['country_names']

            logger.debug(f"   ✅ Step G.2: Country attribution added - {country_info['primary_iso3']} ({len(country_info['iso3_list'])} countries)")
        else:
            logger.debug("   ⚠️ Step G.2: No countries found for bbox (may be ocean/international waters)")
    else:
        logger.warning("   ⚠️ Step G.2: No valid bbox available for country attribution")
except Exception as e:
    # Non-critical - don't fail item creation if country lookup fails
    logger.warning(f"⚠️ Step G.2: Country attribution failed (non-critical): {e}")
```

#### Step 4: Add Same Logic to StacVectorService

**File**: [services/service_stac_vector.py](../services/service_stac_vector.py)

**Location**: In `extract_item_from_table()`, after building properties dict (around line 128)

```python
# Add country attribution
try:
    from services.service_stac_metadata import StacMetadataService
    stac_service = StacMetadataService()
    country_info = stac_service._get_countries_for_bbox(bbox)

    if country_info['iso3_list']:
        properties['geo:iso3'] = country_info['iso3_list']
        properties['geo:primary_iso3'] = country_info['primary_iso3']
        if country_info['country_names']:
            properties['geo:countries'] = country_info['country_names']

        logger.debug(f"Country attribution: {country_info['primary_iso3']}")
except Exception as e:
    logger.warning(f"Country attribution failed (non-critical): {e}")
```

**Alternative**: Extract the method to a shared utility to avoid circular imports.

#### Step 5: Ensure admin0 Table Exists

**PREREQUISITE**: The `geo.system_admin0_boundaries` table must exist with:
- `iso3` column (VARCHAR 3)
- `geom` column (GEOMETRY Polygon/MultiPolygon EPSG:4326)
- Optional: `name` column (VARCHAR)

**If table doesn't exist**, create it:
```sql
CREATE TABLE IF NOT EXISTS geo.system_admin0_boundaries (
    id SERIAL PRIMARY KEY,
    iso3 VARCHAR(3) NOT NULL,
    name VARCHAR(255),
    geom GEOMETRY(MultiPolygon, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_admin0_geom ON geo.system_admin0_boundaries USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_admin0_iso3 ON geo.system_admin0_boundaries(iso3);

-- Populate from Natural Earth, GADM, or other admin boundary source
```

### Testing

```bash
# 1. Submit raster processing job
curl -X POST ".../api/jobs/submit/process_raster" \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "test.tif", "container_name": "rmhazuregeobronze"}'

# 2. After job completes, check STAC item
curl ".../api/stac/collections/dev/items/{item_id}" | jq '.properties | {iso3: .["geo:iso3"], primary: .["geo:primary_iso3"]}'

# Expected output:
# {
#   "iso3": ["USA"],
#   "primary": "USA"
# }

# 3. Test border case (item spanning multiple countries)
# Upload a raster that crosses US-Canada border, verify both ISO3 codes returned
```

### Task Checklist

- [ ] **Prerequisite**: Verify `geo.system_admin0_boundaries` table exists with iso3 and geom columns
- [ ] **Step 1**: Decide on config approach (reuse H3Config or create SpatialConfig)
- [ ] **Step 2**: Add `_get_countries_for_bbox()` helper to StacMetadataService
- [ ] **Step 3**: Add STEP G.2 (country attribution) to `extract_item_from_blob()`
- [ ] **Step 4**: Add country attribution to `StacVectorService.extract_item_from_table()`
- [ ] **Step 5**: Test with raster job submission
- [ ] **Step 6**: Test with vector STAC cataloging
- [ ] **Step 7**: Test border case (multi-country item)
- [ ] **Step 8**: Update documentation (note new STAC properties)
- [ ] **Commit**: "Add ISO3 country attribution to STAC items during metadata extraction"

### Properties Added to STAC Items

| Property | Type | Description | Example |
|----------|------|-------------|---------|
| `geo:iso3` | List[str] | ISO 3166-1 alpha-3 codes for all intersecting countries | `["USA", "CAN"]` |
| `geo:primary_iso3` | str | Primary country (centroid-based) | `"USA"` |
| `geo:countries` | List[str] | Country names (if available in admin0 table) | `["United States", "Canada"]` |

### Performance Considerations

- **Single PostGIS query** per STAC item (~10-50ms overhead)
- **Index-backed**: Spatial queries use GIST index on geom column
- **Non-blocking**: Failures don't prevent STAC item creation
- **Cached connection**: Uses PostgreSQLRepository connection pooling

### Future Enhancements

1. **H3 Cell Lookup** (Alternative approach): Use H3 grid with precomputed country_code instead of real-time spatial join
2. **Admin1 Attribution**: Add state/province codes for more granular attribution
3. **Configurable Columns**: Allow configuration of which spatial attributes to extract
4. **Batch Processing**: Optimize for bulk STAC item creation (single query for multiple bboxes)

---

## 🎨 MEDIUM-LOW PRIORITY - Multispectral Band Combination URLs in STAC (21 NOV 2025)

**Status**: Planned - Enhancement for satellite imagery visualization
**Purpose**: Auto-generate TiTiler viewer URLs with common band combinations for Landsat/Sentinel-2 imagery
**Priority**: MEDIUM-LOW (nice-to-have for multispectral data users)
**Effort**: 2-3 hours
**Requested By**: Robert (21 NOV 2025)

### Problem Statement

**Current State**: When `process_raster` detects multispectral imagery (11+ bands like Sentinel-2), it creates standard TiTiler URLs that don't specify band combinations. The default TiTiler viewer can't display 11-band data without explicit band selection.

**User Experience Today**:
1. User processes Sentinel-2 GeoTIFF
2. TiTiler preview URL opens blank/error page
3. User must manually craft URL with `&bidx=4&bidx=3&bidx=2&rescale=0,3000` parameters
4. No guidance provided for common visualization patterns

**Desired State**: STAC items for multispectral imagery should include multiple ready-to-use visualization URLs:
```json
{
  "assets": {
    "data": { "href": "..." },
    "visual_truecolor": {
      "href": "https://titiler.../preview?url=...&bidx=4&bidx=3&bidx=2&rescale=0,3000",
      "title": "True Color (RGB)",
      "type": "text/html",
      "roles": ["visual"]
    },
    "visual_falsecolor": {
      "href": "https://titiler.../preview?url=...&bidx=8&bidx=4&bidx=3&rescale=0,3000",
      "title": "False Color (NIR)",
      "type": "text/html",
      "roles": ["visual"]
    },
    "visual_swir": {
      "href": "https://titiler.../preview?url=...&bidx=11&bidx=8&bidx=4&rescale=0,3000",
      "title": "SWIR Composite",
      "type": "text/html",
      "roles": ["visual"]
    }
  }
}
```

### Detection Logic

**When to generate band combination URLs**:
```python
# Criteria for "multispectral satellite imagery"
should_add_band_urls = (
    band_count >= 4 and
    (dtype == 'uint16' or dtype == 'int16') and
    (
        # Sentinel-2 pattern (11-13 bands)
        band_count in [10, 11, 12, 13] or
        # Landsat 8/9 pattern (7-11 bands)
        band_count in [7, 8, 9, 10, 11] or
        # Generic multispectral with band descriptions
        has_band_descriptions_matching(['blue', 'green', 'red', 'nir'])
    )
)
```

### Standard Band Combinations

**Sentinel-2 (10m/20m bands)**:
| Combination | Bands | TiTiler Parameters | Use Case |
|-------------|-------|-------------------|----------|
| True Color RGB | B4, B3, B2 | `bidx=4&bidx=3&bidx=2&rescale=0,3000` | Natural appearance |
| False Color NIR | B8, B4, B3 | `bidx=8&bidx=4&bidx=3&rescale=0,3000` | Vegetation health |
| SWIR | B11, B8, B4 | `bidx=11&bidx=8&bidx=4&rescale=0,3000` | Moisture/geology |
| Agriculture | B11, B8, B2 | `bidx=11&bidx=8&bidx=2&rescale=0,3000` | Crop analysis |

**Landsat 8/9**:
| Combination | Bands | TiTiler Parameters | Use Case |
|-------------|-------|-------------------|----------|
| True Color RGB | B4, B3, B2 | `bidx=4&bidx=3&bidx=2&rescale=0,10000` | Natural appearance |
| False Color NIR | B5, B4, B3 | `bidx=5&bidx=4&bidx=3&rescale=0,10000` | Vegetation health |
| SWIR | B7, B5, B4 | `bidx=7&bidx=5&bidx=4&rescale=0,10000` | Moisture/geology |

### Implementation Location

**File**: [services/service_stac_metadata.py](../services/service_stac_metadata.py)

**Location**: In `_generate_titiler_urls()` method, after standard URL generation (around line 455)

```python
# After generating standard URLs...

# Check if multispectral imagery
if raster_type == 'multispectral' and band_count >= 10:
    # Determine rescale based on dtype
    rescale = "0,3000" if dtype == 'uint16' else "0,255"

    # Sentinel-2 band combinations (11-13 bands)
    if band_count >= 10:
        band_combinations = {
            'truecolor': {
                'bands': [4, 3, 2],
                'title': 'True Color (RGB)',
                'description': 'Natural color composite (Red, Green, Blue)'
            },
            'falsecolor_nir': {
                'bands': [8, 4, 3],
                'title': 'False Color (NIR)',
                'description': 'Near-infrared composite for vegetation analysis'
            },
            'swir': {
                'bands': [11, 8, 4] if band_count >= 11 else [8, 4, 3],
                'title': 'SWIR Composite',
                'description': 'Short-wave infrared for moisture and geology'
            }
        }

        for combo_name, combo_info in band_combinations.items():
            bidx_params = '&'.join([f'bidx={b}' for b in combo_info['bands']])
            urls[f'preview_{combo_name}'] = f"{titiler_base}/cog/preview?url={encoded_url}&{bidx_params}&rescale={rescale}"

        logger.info(f"Added {len(band_combinations)} band combination URLs for multispectral imagery")
```

### Task Checklist

- [ ] **Step 1**: Add band combination detection logic to `_validate_raster()` or `_detect_raster_type()`
- [ ] **Step 2**: Create band combination profiles (Sentinel-2, Landsat 8/9, generic)
- [ ] **Step 3**: Extend `_generate_titiler_urls()` to add band-specific preview URLs
- [ ] **Step 4**: Update STAC item assets structure to include visual role URLs
- [ ] **Step 5**: Test with Sentinel-2 imagery (bia_glo30dem.tif is actually Sentinel-2)
- [ ] **Step 6**: Test with Landsat imagery (if available)
- [ ] **Step 7**: Document new STAC asset types in API documentation
- [ ] **Commit**: "Add band combination URLs for multispectral STAC items"

### Expected STAC Item Structure

```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "sentinel2-scene-001",
  "properties": {
    "datetime": "2025-11-21T00:00:00Z",
    "geo:raster_type": "multispectral",
    "eo:bands": [
      {"name": "B1", "description": "Coastal aerosol"},
      {"name": "B2", "description": "Blue"},
      {"name": "B3", "description": "Green"},
      {"name": "B4", "description": "Red"},
      {"name": "B5", "description": "Vegetation Red Edge"},
      {"name": "B6", "description": "Vegetation Red Edge"},
      {"name": "B7", "description": "Vegetation Red Edge"},
      {"name": "B8", "description": "NIR"},
      {"name": "B8A", "description": "Vegetation Red Edge"},
      {"name": "B11", "description": "SWIR"},
      {"name": "B12", "description": "SWIR"}
    ]
  },
  "assets": {
    "data": {
      "href": "https://rmhazuregeo.blob.core.windows.net/silver-cogs/...",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data"]
    },
    "thumbnail": {
      "href": "https://titiler.../cog/preview?url=...&bidx=4&bidx=3&bidx=2&rescale=0,3000&width=256&height=256",
      "type": "image/png",
      "roles": ["thumbnail"]
    },
    "visual_truecolor": {
      "href": "https://titiler.../cog/viewer?url=...&bidx=4&bidx=3&bidx=2&rescale=0,3000",
      "title": "True Color (RGB) Viewer",
      "type": "text/html",
      "roles": ["visual"]
    },
    "visual_falsecolor": {
      "href": "https://titiler.../cog/viewer?url=...&bidx=8&bidx=4&bidx=3&rescale=0,3000",
      "title": "False Color (NIR) Viewer",
      "type": "text/html",
      "roles": ["visual"]
    },
    "visual_swir": {
      "href": "https://titiler.../cog/viewer?url=...&bidx=11&bidx=8&bidx=4&rescale=0,3000",
      "title": "SWIR Composite Viewer",
      "type": "text/html",
      "roles": ["visual"]
    }
  }
}
```

### Notes

- **Rescale values**: Sentinel-2 L2A reflectance is typically 0-10000 but clipped at 3000 for visualization
- **Band indexing**: TiTiler uses 1-based indexing (band 1 = first band)
- **uint16 handling**: Most satellite imagery is uint16, requires rescale parameter
- **Graceful degradation**: If band combination bands don't exist, skip that combination
