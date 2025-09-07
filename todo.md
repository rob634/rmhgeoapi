# PostgreSQL Repository Refactoring TODO

**Date Created**: 2025-09-06  
**Context**: Remove unnecessary adapter abstraction layer since application is PostgreSQL-only  
**Priority**: HIGH - Current architecture has bugs due to parameter mismatches and duplicate implementations
**Requirement**: No SQL files - Use psycopg.sql composed statements for all SQL generation in Python code EXCEPT for database functions which use f string for the time being

## ✅ COMPLETED: CRITICAL FIRST STEPS

### ✅ Step 0.1: Verify ABC Classes in schema_core.py
**Status**: COMPLETED
- ✅ JobRecord and TaskRecord Pydantic models are complete with all fields
- ✅ No ABC definitions in schema_core.py (they're correctly in repository_abc.py)
- ✅ Enum definitions (JobStatus, TaskStatus) include state transition validation
- ✅ Field validators enforce SHA256 job IDs, snake_case naming, etc.
- ✅ All required fields present with proper defaults

### ✅ Step 0.2: Check SQL Schema Generation in schema_sql_generator.py
**Status**: COMPLETED
- ✅ Reads from schema_core.py models (imports JobRecord, TaskRecord)
- ✅ Generates CREATE TABLE statements using psycopg.sql composition
- ✅ Properly handles enum types with DROP IF EXISTS + CREATE
- ✅ Generates PostgreSQL functions (f-strings allowed as temporary exception)
- ✅ NO DO blocks found - uses clean DROP/CREATE pattern
- ✅ Uses psycopg.sql composition for tables, indexes, triggers
- ✅ Fixed bug: undefined `load_static_functions()` → `generate_static_functions()`

### ✅ Step 0.3: ASSESSMENT COMPLETE
**Conclusions**:
- ✅ Pydantic models in schema_core.py ARE the single source of truth
- ✅ SQL is correctly generated from these models
- ✅ Functions exist in both files but signatures match
- ✅ Refactoring WILL preserve Pydantic → SQL generation pattern

---

## ✅ COMPLETED: NEW ARCHITECTURE IMPLEMENTATION

### ✅ Step 1: Created Pure Base Repository
**Status**: COMPLETED
- ✅ Created `repository_base.py` with NO storage dependencies
- ✅ Pure abstract class with validation logic only
- ✅ Added comprehensive documentation with docstrings
- ✅ Includes placeholders for future Container, Cosmos, Redis repositories

### ✅ Step 2: Created PostgreSQL Repository Base
**Status**: COMPLETED
- ✅ Created `repository_postgresql.py` inheriting from BaseRepository
- ✅ Integrated with `config.py` for configuration management
- ✅ Connection management using psycopg3
- ✅ SQL composition for injection safety
- ✅ Comprehensive documentation added
- ✅ Includes placeholders for future PostGIS repositories

### ✅ Step 3: Created Domain Repositories
**Status**: COMPLETED
- ✅ JobRepository(PostgreSQLRepository) with direct PostgreSQL operations
- ✅ TaskRepository(PostgreSQLRepository) with direct PostgreSQL operations
- ✅ CompletionDetector(PostgreSQLRepository) with atomic operations
- ✅ Fixed 3-parameter signature for advance_job_stage()

### ✅ Step 4: Created Consolidated Repository
**Status**: COMPLETED
- ✅ Created `repository_consolidated.py` with business logic layer
- ✅ Extended repositories with business-specific methods
- ✅ New RepositoryFactory without storage_backend_type parameter

---

## 🚀 NEXT STEPS: INTEGRATION AND CLEANUP

### ✅ Step 5: Update All Callers to Use New Repository
**Status**: COMPLETED

**Files updated** (changed imports and removed 'postgres' parameter):
- ✅ `trigger_http_base.py`: Import from repository_consolidated, removed 'postgres' param
- ✅ `controller_base.py`: Updated all 4 occurrences to use new repository
- ✅ `function_app.py`: Updated both occurrences, marked test function for refactoring
- ✅ `trigger_database_query.py`: Updated to use repository_postgresql (needs further refactoring)

### ✅ Step 6: Update Imports Across Codebase
**Status**: COMPLETED

**Imports updated**:
- ✅ All active code now imports from `repository_consolidated.py` or `repository_postgresql.py`
- ✅ Removed all references to `StorageAdapterFactory` and `StorageBackend` from active code
- ✅ Only remaining references are in `repository_data.py` (to be deleted) and `adapter_storage.py` (to be deleted)

### Step 7: Delete Unused Adapter Code
**Purpose**: Remove ~1000+ lines of unused multi-backend code

**Files/sections to remove**:
- [ ] Delete entire `adapter_storage.py` file (after confirming no dependencies)
- [ ] Remove old repository_data.py if fully replaced by repository_consolidated.py
- [ ] Clean up any remaining adapter references

### Step 8: Testing and Validation
**Purpose**: Ensure the refactoring works end-to-end

**Test checklist**:
- [ ] Deploy schema using schema deployment endpoint
- [ ] Submit hello_world job via HTTP endpoint
- [ ] Verify job creates and queues properly
- [ ] Verify tasks complete without "stage_result" error
- [ ] Verify stage advancement works (3 parameters)
- [ ] Verify job completion detection works
- [ ] Check database health endpoint still works
- [ ] Run integration tests if available

---

## Problem Summary

The codebase has an unnecessary adapter pattern from when multiple storage backends were planned (Azure Tables, PostgreSQL, CosmosDB). Now that the application is PostgreSQL-only, this creates:
- Duplicate implementations of atomic operations in both adapter_storage.py and repository_data.py
- Parameter mismatches (advance_job_stage takes 4 params in Python but SQL needs only 3)
- ~1000+ lines of unused code
- Confusing double-wrapping of PostgreSQL operations

## Current Architecture (TO BE REMOVED)

```
function_app.py
    ↓ calls
RepositoryFactory.create_repositories('postgres')  # Always 'postgres', never anything else
    ↓ creates
StorageAdapterFactory.create_adapter('postgres')
    ↓ creates
PostgresAdapter (adapter_storage.py)
    ↓ wrapped by
PostgreSQLCompletionDetector (repository_data.py)
    ↓ calls
PostgreSQL Database
```

## Target Architecture (TO BE IMPLEMENTED)

```
function_app.py
    ↓ calls
RepositoryFactory.create_repositories()  # No parameter needed
    ↓ creates
PostgreSQLRepository (direct database operations)
    ↓ creates
JobRepository, TaskRepository, CompletionDetector
    ↓ calls
PostgreSQL Database
```

## Implementation Steps

### Step 1: Create New PostgreSQL-Only Repository File

**Create**: `repository_postgresql.py`

**Include from adapter_storage.py (lines to copy)**:
- PostgreSQL connection logic (lines 725-744: `_get_connection()` method)
- Table creation logic (lines 745-920: `_ensure_tables_exist()` method)
- Basic CRUD operations for jobs (lines 921-1095)
- Basic CRUD operations for tasks (lines 1096-1368)

**Include from repository_data.py**:
- BaseRepository class (lines 54-103)
- JobRepository class logic (lines 104-322)
- TaskRepository class logic (lines 323-573)

**Fix the atomic operations**:
- Move `complete_task_and_check_stage()` from adapter_storage.py lines 1369-1422
- Move `advance_job_stage()` from adapter_storage.py lines 1423-1478
  - **CRITICAL FIX**: Remove the `next_stage` parameter (currently line 1423)
  - Change signature from `(job_id, current_stage, next_stage, stage_results)` 
  - To: `(job_id, current_stage, stage_results)` to match SQL function
- Move `check_job_completion()` from adapter_storage.py lines 1487-1523

### Step 2: Update CompletionDetector in repository_data.py

**Fix PostgreSQLCompletionDetector.advance_job_stage()** (lines 737-770):
- Remove the line calculating `next_stage = current_stage + 1` (line 753)
- Change the call from 4 parameters to 3 parameters
- From:
  ```python
  result = self.postgres_adapter.advance_job_stage(
      job_id, current_stage, next_stage, stage_results
  )
  ```
- To:
  ```python
  result = self.postgres_adapter.advance_job_stage(
      job_id, current_stage, stage_results
  )
  ```

### Step 3: Simplify RepositoryFactory

**In repository_data.py, update RepositoryFactory** (lines 818-882):
- Remove `storage_backend_type` parameter from `create_repositories()`
- Remove all conditional logic for different backends
- Always create PostgreSQL repositories
- Remove references to StorageAdapterFactory

### Step 4: Update All Callers

**Files to update** (remove 'postgres' parameter):
- `trigger_http_base.py` line 76: Change `RepositoryFactory.create_repositories('postgres')` to `RepositoryFactory.create_repositories()`
- `debug_queue_processing.py` line 159: Same change
- `controller_base.py` lines 180, 859, 932, 967: Same change (4 occurrences)
- `function_app.py` lines 414, 598: Same change (2 occurrences)

### Step 5: Clean Up Imports

**Update imports in these files**:
- Remove imports of `StorageAdapterFactory`, `StorageBackend` 
- Update to import from new `repository_postgresql.py` instead of `adapter_storage.py`

### Step 6: Delete Unused Code

**Files/sections to remove**:
- **adapter_storage.py**: 
  - Lines 131-174: `StorageBackend` Protocol
  - Lines 180-638: `AzureTableStorageAdapter` class (458 lines!)
  - Lines 1538-1551: `CosmosDbAdapter` class
  - Lines 1560-1590: `StorageAdapterFactory` class
  - Keep only PostgreSQL-specific utilities if needed

**Consider full deletion of adapter_storage.py** if all needed code is moved to repository_postgresql.py

### Step 7: Fix Test Code in function_app.py

**Fix lines 291-301 in function_app.py**:
- Currently has commented out incorrect import
- Either remove this test code entirely OR
- Fix to use proper imports from repository_data.py

### Step 8: Testing Checklist

After implementation, verify:
- [ ] Hello world job can be submitted successfully
- [ ] Tasks complete and advance stages properly
- [ ] No "unexpected keyword argument" errors
- [ ] All 3 PostgreSQL functions work: `complete_task_and_check_stage`, `advance_job_stage`, `check_job_completion`
- [ ] Database health endpoint still works
- [ ] Schema deployment still works

## Key Issues Being Fixed

1. **Parameter Mismatch**: `advance_job_stage()` currently takes 4 params but SQL function only needs 3
2. **Duplicate Implementation**: Same atomic operations exist in both adapter and repository layers
3. **Incorrect Import**: function_app.py line 292 imports from wrong module
4. **Unused Code**: ~1000+ lines for Azure Tables and CosmosDB adapters never used

## SQL Function Signatures (DO NOT CHANGE)

These are correct and should match the Python implementations:

```sql
-- functions_only.sql line 66
CREATE OR REPLACE FUNCTION advance_job_stage(
    p_job_id VARCHAR(64),
    p_current_stage INTEGER,
    p_stage_results JSONB DEFAULT NULL  -- Note: only 3 parameters!
)

-- functions_only.sql line 6
CREATE OR REPLACE FUNCTION complete_task_and_check_stage(
    p_task_id VARCHAR(100),
    p_result_data JSONB DEFAULT NULL,
    p_error_details TEXT DEFAULT NULL
)

-- functions_only.sql line 117
CREATE OR REPLACE FUNCTION check_job_completion(
    p_job_id VARCHAR(64)
)
```

## Success Criteria

- Code is simpler with single repository layer
- No adapter abstraction for PostgreSQL-only operations
- Parameter signatures match between Python and SQL
- Hello world jobs complete successfully
- ~1000+ lines of unused code removed

## Notes for Implementation

- This is a PostgreSQL-only application now, no need for backend flexibility
- The atomic operations are PostgreSQL stored procedures that could never work with other backends anyway
- Keep the repository pattern for business logic separation, just remove the adapter layer
- Test thoroughly after changes - the current bugs are preventing job completion

## Current Bug Manifestation

Error when running hello_world job:
```
"error_details": "Stage advancement failed: PostgreSQLCompletionDetector.advance_job_stage() got an unexpected keyword argument 'stage_result'"
```

This will be fixed by aligning all method signatures to match the SQL function (3 parameters, not 4).