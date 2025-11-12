# Platform Schema Migration to App Schema

**Date**: 29 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Change Type**: Schema consolidation - Platform tables moved to `app` schema

---

## 🎯 Summary

Platform layer tables have been migrated from a separate `platform` schema to the existing `app` schema to consolidate all application data in one place, matching CoreMachine's architecture.

---

## 📊 Changes Made

### Schema Migration

**BEFORE** (Separate schema):
```
platform (schema)
  ├── platform.requests
  └── platform.request_jobs
```

**AFTER** (Consolidated in app schema):
```
app (schema)
  ├── app.jobs                      # CoreMachine (existing)
  ├── app.tasks                     # CoreMachine (existing)
  ├── app.stage_completions         # CoreMachine (existing)
  ├── app.platform_requests         # Platform (NEW)
  └── app.platform_request_jobs     # Platform (NEW)
```

### Table Definitions

**app.platform_requests**:
```sql
CREATE TABLE app.platform_requests (
    request_id VARCHAR(32) PRIMARY KEY,          -- SHA256 hash (32 chars, truncated)
    dataset_id VARCHAR(255) NOT NULL,            -- DDH dataset ID
    resource_id VARCHAR(255) NOT NULL,           -- DDH resource ID
    version_id VARCHAR(50) NOT NULL,             -- DDH version ID
    data_type VARCHAR(50) NOT NULL,              -- "raster", "vector", etc.
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    job_ids JSONB NOT NULL DEFAULT '[]'::jsonb,  -- Array of CoreMachine job IDs
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_platform_requests_status ON app.platform_requests(status);
CREATE INDEX idx_platform_requests_dataset ON app.platform_requests(dataset_id);
CREATE INDEX idx_platform_requests_created ON app.platform_requests(created_at DESC);
```

**app.platform_request_jobs** (Mapping table):
```sql
CREATE TABLE app.platform_request_jobs (
    request_id VARCHAR(32) NOT NULL,             -- Platform request ID
    job_id VARCHAR(64) NOT NULL,                 -- CoreMachine job ID (FULL 64-char SHA256)
    job_type VARCHAR(100) NOT NULL,              -- CoreMachine job type
    sequence INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (request_id, job_id)
);
```

### Key Field Size Changes

| Field | Table | Old Size | New Size | Reason |
|-------|-------|----------|----------|--------|
| `job_id` | `platform_request_jobs` | VARCHAR(32) | **VARCHAR(64)** | CoreMachine uses FULL SHA256 hash (64 chars) |
| `request_id` | `platform_requests` | VARCHAR(32) | VARCHAR(32) | No change (truncated SHA256) |

---

## 🔧 Code Changes

### Files Modified

1. **triggers/trigger_platform.py**
   - Changed schema references: `platform.requests` → `app.platform_requests`
   - Changed table references: `platform.request_jobs` → `app.platform_request_jobs`
   - Updated `_ensure_schema()` to create tables in `app` schema
   - Fixed `job_id` size to VARCHAR(64) for CoreMachine compatibility

2. **triggers/trigger_platform_status.py**
   - Updated all SQL queries to use `app.platform_requests`
   - Updated JOIN queries to use `app.platform_request_jobs`
   - Fixed row access to use dict keys instead of integer indices

### SQL Query Updates

**Example UPDATE query**:
```sql
-- BEFORE
INSERT INTO platform.requests (...) VALUES (...)

-- AFTER
INSERT INTO app.platform_requests (...) VALUES (...)
```

**Example JOIN query**:
```sql
-- BEFORE
FROM platform.requests r
LEFT JOIN platform.request_jobs pj ON pj.request_id = r.request_id

-- AFTER
FROM app.platform_requests r
LEFT JOIN app.platform_request_jobs pj ON pj.request_id = r.request_id
```

---

## 🐛 Bug Fixes Applied

### Bug #1: Job ID Size Mismatch
**Problem**: Platform mapping table used VARCHAR(32) for `job_id`, but CoreMachine jobs use 64-char SHA256 hashes.

**Error**: `value too long for type character varying(32)`

**Fix**: Changed `job_id` column to VARCHAR(64) in `app.platform_request_jobs`

### Bug #2: Row Access Method
**Problem**: Status endpoint tried to access rows by integer index (`row[0]`) but psycopg uses `dict_row` factory.

**Error**: `KeyError: 0`

**Fix**: Changed all row access to use column names (`row['request_id']`)

### Bug #3: Job Repository Return Type
**Problem**: Platform orchestrator expected `create_job()` to return `JobRecord`, but it returns `bool`.

**Error**: `'bool' object has no attribute 'job_id'`

**Fix**: Use `job_record` object directly instead of `stored_job` return value:
```python
# BEFORE
stored_job = self.job_repo.create_job(job_record)
await self._submit_to_queue(stored_job)  # ❌ stored_job is bool

# AFTER
created = self.job_repo.create_job(job_record)
await self._submit_to_queue(job_record)  # ✅ Use original job_record
```

---

## 📋 Migration Steps (For Future Reference)

If you need to manually recreate Platform tables:

### 1. Drop Old Platform Schema (If Exists)
```sql
DROP SCHEMA IF EXISTS platform CASCADE;
```

### 2. Redeploy App Schema
```bash
curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes"
```

This will:
- Drop and recreate `app` schema
- Create `app.jobs`, `app.tasks`, `app.stage_completions` (CoreMachine)
- Create `app.platform_requests`, `app.platform_request_jobs` (Platform)

### 3. Verify Tables Created
```sql
-- Check Platform tables exist
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'app'
  AND table_name LIKE 'platform%';

-- Should return:
-- platform_requests
-- platform_request_jobs
```

---

## ✅ Benefits of App Schema Consolidation

1. **Single Source of Truth**: All application data in one schema
2. **Simpler Queries**: JOIN between Platform requests and CoreMachine jobs without cross-schema references
3. **Unified Permissions**: One schema to manage access control
4. **Easier Backups**: Single schema to backup/restore
5. **Consistent with CoreMachine**: Follows established architecture pattern
6. **No Schema Namespace Conflicts**: Avoids potential naming collisions

---

## 🧪 Testing Checklist

After deployment, verify:

- [ ] Platform submission works: `POST /api/platform/submit`
- [ ] Platform status works: `GET /api/platform/status/{request_id}`
- [ ] Platform list works: `GET /api/platform/status`
- [ ] Jobs are created in CoreMachine: Check `app.jobs` table
- [ ] Mapping table populated: Check `app.platform_request_jobs` table
- [ ] No errors in Application Insights logs

---

## 📚 Related Documentation

- **OpenAPI Spec**: `/openapi/platform-api-v1.yaml`
- **Architecture**: `docs_claude/COREMACHINE_PLATFORM_ARCHITECTURE.md`
- **Research Findings**: `PLATFORM_OPENAPI_RESEARCH_FINDINGS.md`
- **Original Issues**: `PLATFORM_LAYER_FIXES_TODO.md`

---

**Migration Status**: ✅ COMPLETE
**Deployment Required**: Yes (deploy to Azure Functions)
**Breaking Change**: Yes (old `platform` schema no longer used)
**Backward Compatible**: No (requires schema recreation)