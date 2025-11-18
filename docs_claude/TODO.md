# Active Tasks - CRITICAL ETL Repository Pattern Migration

**Last Updated**: 18 NOV 2025 (03:50 UTC)
**Author**: Robert and Geospatial Claude Legion

---

## 🚨 CRITICAL BLOCKING ISSUE - PgSTAC Collection Insertion Failure (18 NOV 2025)

**Problem**: Collections insert successfully but verification fails immediately after
**Error**: "Collection 'X' was not found in PgSTAC after insertion"
**Root Cause**: READ AFTER WRITE consistency issue - two separate repository instances
**Impact**: Phase 2B deployed but STAC collection creation still fails at Stage 4

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

## ✅ MANAGED IDENTITY - OPERATIONAL (15 NOV 2025)

**Status**: ✅ Managed identity authentication working in production
**Documentation**: See [QA_DEPLOYMENT.md](../QA_DEPLOYMENT.md) lines 361-438 for complete setup guide

**Production Setup Completed**:
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
