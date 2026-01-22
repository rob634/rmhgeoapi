# Schema Rebuild SQL Reference

> **Navigation**: [Quick Start](WIKI_QUICK_START.md) | [Platform API](WIKI_PLATFORM_API.md) | [Errors](WIKI_API_ERRORS.md) | [Glossary](WIKI_API_GLOSSARY.md)

**Date**: 22 JAN 2026
**Status**: Reference Documentation
**Wiki**: Azure DevOps Wiki - Database schema rebuild instructions
**Purpose**: Manual SQL instructions for rebuilding `app` and `pgstac` schemas
**Audience**: Database administrators with PostgreSQL access
**Last Updated**: 22 JAN 2026 - Updated geo schema to IaC pattern (table_catalog, feature_collection_styles)

---

## Overview

This document provides the SQL commands needed to manually rebuild the `app` and `pgstac` schemas from scratch. These schemas meet **Infrastructure-as-Code (IaC)** standards - they can be completely wiped and recreated from code with no manual intervention.

**Automated Alternative**: If the Function App is running, use the API endpoint instead:
```bash
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance/full-rebuild?confirm=yes"
```

### 9-Step Rebuild Process (07 DEC 2025)

| Step | Action | Fatal? | Notes |
|------|--------|--------|-------|
| 1 | Drop app schema | **FATAL** | System cannot function without app schema |
| 2 | Drop pgstac schema | NON-FATAL | Continue if fails; STAC features disabled |
| 3 | Deploy app schema | **FATAL** | Jobs/Tasks tables required |
| 4 | Ensure geo schema | NON-FATAL | **Critical for vector workflows** - must exist before any vector jobs |
| 5 | Deploy pgstac (pypgstac migrate) | NON-FATAL | Continue if fails; STAC features disabled |
| 6 | Grant pgstac_read role | NON-FATAL | Skip if step 5 failed |
| 7 | Create system STAC collections | NON-FATAL | Skip if step 5 failed |
| 8 | Verify app schema | NON-FATAL | Always attempt |
| 9 | Verify pgstac schema | NON-FATAL | Skip if step 5 failed |

**Architecture Principle**: App schema is FATAL (system non-functional without it). pgstac is NON-FATAL (STAC features disabled but core system works). geo schema is NEVER dropped (contains user business data).

---

## Prerequisites

### Connection Details

| Property | Value |
|----------|-------|
| **Server** | `rmhpgflex.postgres.database.azure.com` |
| **Database** | `geopgflex` |
| **Admin User** | {db_superuser} (or Entra ID admin) |
| **SSL Mode** | `require` |

### Required Extensions (MUST be created first!)

**⚠️ CRITICAL**: These extensions must be created by an `azure_pg_admin` member BEFORE running schema rebuild. The managed identity admin user cannot create extensions.

| Extension | Required For | Error if Missing |
|-----------|--------------|------------------|
| **postgis** | All geospatial operations | `type "geometry" does not exist` |
| **btree_gist** | pypgstac exclusion constraints | `operator class "gist_timestamptz_ops" does not exist` |
| **unaccent** | pypgstac text search | `function unaccent() does not exist` |

**Verify extensions exist**:
```sql
SELECT extname, extversion FROM pg_extension
WHERE extname IN ('postgis', 'btree_gist', 'unaccent');
```

**If missing, have `azure_pg_admin` run**:
```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS unaccent;
```

### Required Permissions

The executing user (managed identity) needs:
- `CREATE ON DATABASE` - to create schemas
- Schema ownership (automatic when identity creates the schema)
- `WITH ADMIN OPTION` on pgstac roles - for pypgstac migrate

**Note**: `azure_pg_admin` is NOT required for the managed identity. Extensions and pgstac roles must be pre-created by DBA. See [DATABASE_IDENTITY_RUNBOOK.md](DATABASE_IDENTITY_RUNBOOK.md) for complete setup.

---

## Schema Classification

| Schema | Rebuild | Method | Notes |
|--------|---------|--------|-------|
| `app` | **YES** | SQL below | CoreMachine jobs/tasks |
| `pgstac` | **YES** | pypgstac CLI | STAC metadata catalog |
| `geo` | **NEVER** | - | User business data |
| `h3` | Manual only | Bootstrap SQL | Static H3 grid data |

---

## Step 1: Drop App Schema (FATAL)

**WARNING**: This deletes ALL data in the app schema. The `geo` schema (user data) is NEVER touched.

```sql
-- ============================================================================
-- STEP 1: DROP APP SCHEMA (FATAL if fails)
-- CASCADE ensures dependent objects are removed.
-- ============================================================================

-- Drop app schema (CoreMachine jobs/tasks)
DROP SCHEMA IF EXISTS app CASCADE;
```

---

## Step 2: Drop pgstac Schema (NON-FATAL)

**Note**: If this step fails, the rebuild continues. STAC features will be unavailable until pgstac is fixed.

```sql
-- ============================================================================
-- STEP 2: DROP PGSTAC SCHEMA (NON-FATAL)
-- This also drops pgstac roles (pgstac_admin, pgstac_ingest, pgstac_read)
-- ============================================================================

-- Drop pgstac schema (STAC metadata)
DROP SCHEMA IF EXISTS pgstac CASCADE;
```

---

## Step 3: Deploy App Schema (FATAL)

Execute these statements **in order**. The SQL is generated from Pydantic models and represents the single source of truth.

```sql
-- ============================================================================
-- STEP 3: DEPLOY APP SCHEMA (FATAL if fails)
-- Generated from Pydantic models (PydanticToSQL)
-- Date: 25 NOV 2025
-- ============================================================================

-- 2.1: Create schema
CREATE SCHEMA IF NOT EXISTS "app";
SET search_path TO "app", public;

-- 2.2: Create ENUM types
DROP TYPE IF EXISTS "app"."job_status" CASCADE;
CREATE TYPE "app"."job_status" AS ENUM ('queued', 'processing', 'completed', 'failed', 'completed_with_errors');

DROP TYPE IF EXISTS "app"."task_status" CASCADE;
CREATE TYPE "app"."task_status" AS ENUM ('queued', 'processing', 'completed', 'failed', 'retrying', 'pending_retry', 'cancelled');

DROP TYPE IF EXISTS "app"."platform_request_status" CASCADE;
CREATE TYPE "app"."platform_request_status" AS ENUM ('pending', 'processing', 'completed', 'failed');

DROP TYPE IF EXISTS "app"."data_type" CASCADE;
CREATE TYPE "app"."data_type" AS ENUM ('raster', 'vector', 'pointcloud', 'mesh_3d', 'tabular');

DROP TYPE IF EXISTS "app"."janitor_run_type" CASCADE;
CREATE TYPE "app"."janitor_run_type" AS ENUM ('task_watchdog', 'job_health', 'orphan_detector');

DROP TYPE IF EXISTS "app"."janitor_run_status" CASCADE;
CREATE TYPE "app"."janitor_run_status" AS ENUM ('running', 'completed', 'failed');

-- 2.3: Create tables
CREATE TABLE IF NOT EXISTS "app"."jobs" (
    "job_id" VARCHAR(64) NOT NULL,
    "job_type" VARCHAR(100) NOT NULL,
    "parameters" JSONB NOT NULL DEFAULT '{}',
    "status" "app"."job_status" NOT NULL DEFAULT 'queued'::job_status,
    "stage" INTEGER NOT NULL DEFAULT 1,
    "total_stages" INTEGER NOT NULL DEFAULT 1,
    "stage_results" JSONB NOT NULL DEFAULT '{}',
    "metadata" JSONB NOT NULL DEFAULT '{}',
    "result_data" JSONB,
    "error_details" VARCHAR,
    "created_at" TIMESTAMP NOT NULL DEFAULT NOW(),
    "updated_at" TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY ("job_id")
);

CREATE TABLE IF NOT EXISTS "app"."tasks" (
    "task_id" VARCHAR(100) NOT NULL,
    "parent_job_id" VARCHAR(64) NOT NULL,
    "job_type" VARCHAR(100) NOT NULL,
    "task_type" VARCHAR(100) NOT NULL,
    "stage" INTEGER NOT NULL,
    "task_index" VARCHAR(50) NOT NULL DEFAULT '0',
    "parameters" JSONB NOT NULL DEFAULT '{}',
    "status" "app"."task_status" NOT NULL DEFAULT 'queued'::task_status,
    "result_data" JSONB,
    "metadata" JSONB NOT NULL DEFAULT '{}',
    "error_details" VARCHAR,
    "retry_count" INTEGER NOT NULL DEFAULT 0,
    "heartbeat" TIMESTAMP,
    "next_stage_params" JSONB,
    "created_at" TIMESTAMP NOT NULL DEFAULT NOW(),
    "updated_at" TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY ("task_id"),
    FOREIGN KEY ("parent_job_id") REFERENCES "app"."jobs" ("job_id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS "app"."api_requests" (
    "request_id" VARCHAR(32) NOT NULL,
    "dataset_id" VARCHAR(255) NOT NULL,
    "resource_id" VARCHAR(255) NOT NULL,
    "version_id" VARCHAR(50) NOT NULL,
    "job_id" VARCHAR(64) NOT NULL,
    "data_type" VARCHAR(50) NOT NULL,
    "created_at" TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY ("request_id")
);

CREATE TABLE IF NOT EXISTS "app"."janitor_runs" (
    "run_id" VARCHAR NOT NULL,
    "run_type" VARCHAR NOT NULL,
    "started_at" TIMESTAMP NOT NULL,
    "completed_at" TIMESTAMP,
    "duration_ms" INTEGER,
    "status" VARCHAR NOT NULL DEFAULT 'running',
    "items_scanned" INTEGER NOT NULL DEFAULT 0,
    "items_fixed" INTEGER NOT NULL DEFAULT 0,
    "actions_taken" JSONB NOT NULL,
    "error_details" VARCHAR,
    PRIMARY KEY ("run_id")
);

-- 2.4: Create indexes
CREATE INDEX IF NOT EXISTS "idx_jobs_status" ON "app"."jobs" ("status");
CREATE INDEX IF NOT EXISTS "idx_jobs_job_type" ON "app"."jobs" ("job_type");
CREATE INDEX IF NOT EXISTS "idx_jobs_created_at" ON "app"."jobs" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_jobs_updated_at" ON "app"."jobs" ("updated_at");
CREATE INDEX IF NOT EXISTS "idx_tasks_parent_job_id" ON "app"."tasks" ("parent_job_id");
CREATE INDEX IF NOT EXISTS "idx_tasks_status" ON "app"."tasks" ("status");
CREATE INDEX IF NOT EXISTS "idx_tasks_job_stage" ON "app"."tasks" ("parent_job_id", "stage");
CREATE INDEX IF NOT EXISTS "idx_tasks_job_stage_status" ON "app"."tasks" ("parent_job_id", "stage", "status");
CREATE INDEX IF NOT EXISTS "idx_tasks_heartbeat" ON "app"."tasks" ("heartbeat") WHERE "heartbeat" IS NOT NULL;
CREATE INDEX IF NOT EXISTS "idx_tasks_retry_count" ON "app"."tasks" ("retry_count") WHERE "retry_count" > 0;
CREATE INDEX IF NOT EXISTS "idx_api_requests_dataset_id" ON "app"."api_requests" ("dataset_id");
CREATE INDEX IF NOT EXISTS "idx_api_requests_created_at" ON "app"."api_requests" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_janitor_runs_started_at" ON "app"."janitor_runs" ("started_at" DESC);
CREATE INDEX IF NOT EXISTS "idx_janitor_runs_type" ON "app"."janitor_runs" ("run_type");

-- 2.5: Create functions
CREATE OR REPLACE FUNCTION "app"."complete_task_and_check_stage"(
    p_task_id VARCHAR(100),
    p_job_id VARCHAR(64),
    p_stage INTEGER,
    p_result_data JSONB DEFAULT NULL,
    p_error_details TEXT DEFAULT NULL
)
RETURNS TABLE (
    task_updated BOOLEAN,
    is_last_task_in_stage BOOLEAN,
    job_id VARCHAR(64),
    stage_number INTEGER,
    remaining_tasks INTEGER
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_job_id VARCHAR(64);
    v_stage INTEGER;
    v_remaining INTEGER;
    v_task_status app.task_status;
BEGIN
    UPDATE app.tasks
    SET
        status = CASE
            WHEN p_error_details IS NOT NULL THEN 'failed'::app.task_status
            ELSE 'completed'::app.task_status
        END,
        result_data = p_result_data,
        error_details = p_error_details,
        updated_at = NOW()
    WHERE
        task_id = p_task_id
        AND parent_job_id = p_job_id
        AND stage = p_stage
        AND status = 'processing'
    RETURNING parent_job_id, stage, status
    INTO v_job_id, v_stage, v_task_status;

    IF v_job_id IS NULL THEN
        RETURN QUERY SELECT FALSE, FALSE, NULL::VARCHAR(64), NULL::INTEGER, 0::INTEGER;
        RETURN;
    END IF;

    PERFORM pg_advisory_xact_lock(hashtext(v_job_id || ':stage:' || v_stage::text));

    SELECT COUNT(*)::INTEGER INTO v_remaining
    FROM app.tasks
    WHERE parent_job_id = v_job_id
      AND stage = v_stage
      AND status NOT IN ('completed', 'failed');

    RETURN QUERY SELECT
        TRUE,
        v_remaining = 0,
        v_job_id,
        v_stage,
        v_remaining;
END;
$$;

CREATE OR REPLACE FUNCTION "app"."advance_job_stage"(
    p_job_id VARCHAR(64),
    p_current_stage INTEGER,
    p_stage_results JSONB DEFAULT NULL
)
RETURNS TABLE (
    job_updated BOOLEAN,
    new_stage INTEGER,
    is_final_stage BOOLEAN
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_total_stages INTEGER;
    v_new_stage INTEGER;
BEGIN
    UPDATE app.jobs
    SET
        stage = stage + 1,
        stage_results = CASE
            WHEN p_stage_results IS NOT NULL THEN
                stage_results || jsonb_build_object(p_current_stage::text, p_stage_results)
            ELSE stage_results
        END,
        status = CASE
            WHEN stage + 1 > total_stages THEN 'completed'::app.job_status
            ELSE 'processing'::app.job_status
        END,
        updated_at = NOW()
    WHERE
        job_id = p_job_id
        AND stage = p_current_stage
    RETURNING stage, total_stages
    INTO v_new_stage, v_total_stages;

    IF v_new_stage IS NULL THEN
        RETURN QUERY SELECT FALSE, NULL::INTEGER, NULL::BOOLEAN;
        RETURN;
    END IF;

    RETURN QUERY SELECT
        TRUE,
        v_new_stage,
        v_new_stage > v_total_stages;
END;
$$;

CREATE OR REPLACE FUNCTION "app"."check_job_completion"(
    p_job_id VARCHAR(64)
)
RETURNS TABLE (
    job_complete BOOLEAN,
    final_stage INTEGER,
    total_tasks BIGINT,
    completed_tasks BIGINT,
    task_results JSONB
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_job_record RECORD;
    v_task_counts RECORD;
BEGIN
    SELECT job_id, job_type, status, stage, total_stages, stage_results
    INTO v_job_record
    FROM app.jobs
    WHERE job_id = p_job_id
    FOR UPDATE;

    IF v_job_record.job_id IS NULL THEN
        RETURN QUERY SELECT
            FALSE,
            0::INTEGER,
            0::BIGINT,
            0::BIGINT,
            '[]'::jsonb;
        RETURN;
    END IF;

    SELECT
        COUNT(*)::BIGINT as total_tasks,
        COUNT(CASE WHEN status = 'completed' THEN 1 END)::BIGINT as completed_tasks,
        COUNT(CASE WHEN status = 'failed' THEN 1 END)::BIGINT as failed_tasks,
        COALESCE(
            jsonb_agg(
                jsonb_build_object(
                    'task_id', task_id,
                    'task_type', task_type,
                    'stage', stage,
                    'task_index', task_index,
                    'status', status::text,
                    'result_data', result_data,
                    'error_details', error_details
                )
            ) FILTER (WHERE result_data IS NOT NULL OR error_details IS NOT NULL),
            '[]'::jsonb
        ) as task_results
    INTO v_task_counts
    FROM app.tasks
    WHERE parent_job_id = p_job_id;

    RETURN QUERY SELECT
        (
            v_task_counts.total_tasks > 0 AND
            (v_task_counts.completed_tasks + v_task_counts.failed_tasks) = v_task_counts.total_tasks AND
            v_job_record.stage >= v_job_record.total_stages
        ) as job_complete,
        v_job_record.stage as final_stage,
        v_task_counts.total_tasks,
        v_task_counts.completed_tasks,
        v_task_counts.task_results;
END;
$$;

CREATE OR REPLACE FUNCTION "app"."increment_task_retry_count"(
    p_task_id VARCHAR(100)
)
RETURNS TABLE (
    new_retry_count INTEGER
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_new_retry_count INTEGER;
BEGIN
    UPDATE app.tasks
    SET
        retry_count = retry_count + 1,
        status = 'queued'::app.task_status,
        updated_at = NOW()
    WHERE task_id = p_task_id
    RETURNING retry_count INTO v_new_retry_count;

    RETURN QUERY SELECT v_new_retry_count;
END;
$$;

CREATE OR REPLACE FUNCTION "app"."update_updated_at_column"()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

-- 2.6: Create triggers
DROP TRIGGER IF EXISTS "update_jobs_updated_at" ON "app"."jobs";
CREATE TRIGGER "update_jobs_updated_at"
    BEFORE UPDATE ON "app"."jobs"
    FOR EACH ROW
    EXECUTE FUNCTION "app"."update_updated_at_column"();

DROP TRIGGER IF EXISTS "update_tasks_updated_at" ON "app"."tasks";
CREATE TRIGGER "update_tasks_updated_at"
    BEFORE UPDATE ON "app"."tasks"
    FOR EACH ROW
    EXECUTE FUNCTION "app"."update_updated_at_column"();
```

---

## Step 4: Ensure geo Schema Exists (NON-FATAL)

**CRITICAL for vector workflows**: The `geo` schema must exist before any vector processing jobs can run. This step uses `IF NOT EXISTS` so it never deletes existing data.

**Architecture Principle (22 JAN 2026)**: The geo schema stores:
- **Service layer metadata** (`table_catalog`, `feature_collection_styles`) - suitable for replication to external DBs
- **User vector data** (`{table_name}`) - PostGIS tables created by `process_vector` jobs

Unlike app/pgstac (rebuilt from code), geo contains **USER DATA** and is **NEVER dropped**.

**IaC Pattern (22 JAN 2026)**: DDL is generated from Pydantic models via `PydanticToSQL.generate_geo_schema_ddl()`. Source of truth: `core/models/geo.py` (`GeoTableCatalog`, `FeatureCollectionStyles`).

```sql
-- ============================================================================
-- STEP 4: ENSURE GEO SCHEMA EXISTS (NON-FATAL)
-- Uses IF NOT EXISTS - safe to run on existing schema
-- Never deletes existing tables or data
-- DDL generated from Pydantic models (22 JAN 2026)
-- ============================================================================

-- Create geo schema if it doesn't exist
CREATE SCHEMA IF NOT EXISTS geo;

-- geo.table_catalog: Service layer metadata for vector tables
-- Replaces old geo.table_metadata (21 JAN 2026)
CREATE TABLE IF NOT EXISTS geo.table_catalog (
    table_name VARCHAR(255) PRIMARY KEY,
    schema_name VARCHAR(100) NOT NULL DEFAULT 'geo',
    title VARCHAR(500),
    description TEXT,
    attribution VARCHAR(500),
    license VARCHAR(100),
    keywords VARCHAR(500),
    providers JSONB DEFAULT '[]',
    feature_count INTEGER,
    geometry_type VARCHAR(50),
    srid INTEGER DEFAULT 4326,
    bbox JSONB,
    stac_item_id VARCHAR(255),
    stac_collection_id VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for table_catalog
CREATE INDEX IF NOT EXISTS idx_table_catalog_schema ON geo.table_catalog(schema_name);
CREATE INDEX IF NOT EXISTS idx_table_catalog_geometry_type ON geo.table_catalog(geometry_type);
CREATE INDEX IF NOT EXISTS idx_table_catalog_type ON geo.table_catalog(stac_collection_id);
CREATE INDEX IF NOT EXISTS idx_table_catalog_stac ON geo.table_catalog(stac_item_id) WHERE stac_item_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_table_catalog_created ON geo.table_catalog(created_at DESC);

-- geo.feature_collection_styles: OGC API Styles (CartoSym-JSON)
CREATE TABLE IF NOT EXISTS geo.feature_collection_styles (
    id SERIAL PRIMARY KEY,
    collection_id VARCHAR(255) NOT NULL,
    style_id VARCHAR(100) NOT NULL,
    title VARCHAR(500),
    description TEXT,
    style_spec JSONB NOT NULL,
    is_default BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_styles_collection_style UNIQUE (collection_id, style_id)
);

-- Indexes for feature_collection_styles
CREATE INDEX IF NOT EXISTS idx_styles_collection ON geo.feature_collection_styles(collection_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_styles_default ON geo.feature_collection_styles(collection_id) WHERE is_default = true;

-- Grant permissions to reader identity (for OGC Features API)
-- Replace 'rmhpgflexreader' with your reader managed identity name
GRANT USAGE ON SCHEMA geo TO rmhpgflexreader;
GRANT SELECT ON ALL TABLES IN SCHEMA geo TO rmhpgflexreader;
ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT SELECT ON TABLES TO rmhpgflexreader;
```

**Verification**:
```sql
-- Verify geo schema exists
SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'geo';

-- Verify geo tables exist
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'geo' AND table_name IN ('table_catalog', 'feature_collection_styles');
```

---

## Step 5: Deploy pgstac Schema (NON-FATAL)

The `pgstac` schema is managed by the **pypgstac** library (v0.9.8). It cannot be deployed via raw SQL - you must use the CLI tool.

### Option A: From Machine with pypgstac Installed

```bash
# Set PostgreSQL environment variables
export PGHOST=rmhpgflex.postgres.database.azure.com
export PGPORT=5432
export PGDATABASE=geopgflex
export PGUSER={db_superuser}
export PGPASSWORD='<your_password>'

# Run pypgstac migrate
pypgstac migrate
```

### Option B: Via Python (if pypgstac is installed)

```python
import subprocess
import os

env = os.environ.copy()
env.update({
    'PGHOST': 'rmhpgflex.postgres.database.azure.com',
    'PGPORT': '5432',
    'PGDATABASE': 'geopgflex',
    'PGUSER': '{db_superuser}',
    'PGPASSWORD': '<your_password>'
})

result = subprocess.run(
    ['pypgstac', 'migrate'],
    env=env,
    capture_output=True,
    text=True
)
print(result.stdout)
print(result.stderr)
```

### What pypgstac Creates

After `pypgstac migrate` completes, the following objects exist:

**Tables** (22 total):
- `pgstac.collections` - STAC collection metadata
- `pgstac.items` - STAC item metadata with spatial index
- `pgstac.searches` - Registered search configurations
- `pgstac.partitions` - Item partitioning metadata
- Plus internal tables for search optimization

**Roles** (3):
- `pgstac_admin` - Full control over pgstac schema
- `pgstac_ingest` - Insert/update items and collections
- `pgstac_read` - Read-only access for queries

**Functions** (many):
- `pgstac.search()` - Main STAC search function
- `pgstac.create_collection()` - Create STAC collections
- `pgstac.create_item()` - Create STAC items
- `pgstac.get_version()` - Returns "0.9.8"

---

## Step 6: Grant pgstac_read Role (NON-FATAL)

After pgstac is deployed, grant the `pgstac_read` role to the read-only identity. **Skip this step if Step 5 failed.**

```sql
-- ============================================================================
-- STEP 6: GRANT PGSTAC ROLES (NON-FATAL)
-- Required for read-only API access (OGC/STAC API function app)
-- Skip if pypgstac migrate failed (pgstac_read role won't exist)
-- ============================================================================

-- Grant pgstac_read to the read-only managed identity
-- This allows rmhpgflexreader to query STAC collections and items
GRANT pgstac_read TO rmhpgflexreader;

-- Verify the grant
SELECT
    r.rolname as role,
    m.rolname as member
FROM pg_auth_members am
JOIN pg_roles r ON am.roleid = r.oid
JOIN pg_roles m ON am.member = m.oid
WHERE r.rolname = 'pgstac_read';
```

---

## Step 7: Create System STAC Collections (NON-FATAL)

After pgstac is deployed, create the system collections. **Skip this step if Step 5 failed.**

```sql
-- ============================================================================
-- STEP 7: CREATE SYSTEM STAC COLLECTIONS (NON-FATAL)
-- These collections track ETL operational data
-- Skip if pypgstac migrate failed (pgstac.create_collection won't exist)
-- ============================================================================

-- Create system-vectors collection (tracks PostGIS tables created by ETL)
SELECT pgstac.create_collection('{
    "id": "system-vectors",
    "type": "Collection",
    "stac_version": "1.0.0",
    "title": "System STAC - Vector Tables",
    "description": "Operational tracking of PostGIS vector tables created by ETL",
    "license": "proprietary",
    "extent": {
        "spatial": {"bbox": [[-180, -90, 180, 90]]},
        "temporal": {"interval": [[null, null]]}
    },
    "summaries": {
        "asset_type": ["vector"],
        "media_type": ["application/geo+json"]
    }
}'::jsonb);

-- Create system-rasters collection (tracks COG files created by ETL)
SELECT pgstac.create_collection('{
    "id": "system-rasters",
    "type": "Collection",
    "stac_version": "1.0.0",
    "title": "System STAC - Raster Files",
    "description": "Operational tracking of COG files created by ETL",
    "license": "proprietary",
    "extent": {
        "spatial": {"bbox": [[-180, -90, 180, 90]]},
        "temporal": {"interval": [[null, null]]}
    },
    "summaries": {
        "asset_type": ["raster"],
        "media_type": ["image/tiff; application=geotiff; profile=cloud-optimized"]
    }
}'::jsonb);

-- Verify collections were created
SELECT id, content->>'title' as title
FROM pgstac.collections
WHERE id IN ('system-vectors', 'system-rasters');
```

---

## Step 8: Verify App Schema (NON-FATAL)

Run these queries to verify app schema deployment was successful:

```sql
-- ============================================================================
-- STEP 8: VERIFY APP SCHEMA (NON-FATAL)
-- Always attempt this verification
-- ============================================================================

-- 8.1: Verify app schema
SELECT
    'app schema' as check,
    (SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'app') as tables,
    (SELECT COUNT(*) FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid WHERE n.nspname = 'app') as functions,
    (SELECT COUNT(*) FROM pg_type t JOIN pg_namespace n ON t.typnamespace = n.oid WHERE n.nspname = 'app' AND t.typtype = 'e') as enums;

-- Expected: tables=4, functions=5, enums=6

-- 8.2: Test app functions
SELECT * FROM app.check_job_completion('test-job-id');

-- Expected: Returns (false, 0, 0, 0, '[]')
```

---

## Step 9: Verify pgstac Schema (NON-FATAL)

Run these queries to verify pgstac schema deployment was successful. **Skip this step if Step 5 failed.**

```sql
-- ============================================================================
-- STEP 9: VERIFY PGSTAC SCHEMA (NON-FATAL)
-- Skip if pypgstac migrate failed
-- ============================================================================

-- 9.1: Verify pgstac schema
SELECT
    'pgstac schema' as check,
    (SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'pgstac') as tables,
    (SELECT pgstac.get_version()) as version;

-- Expected: tables=22, version='0.9.8'

-- 9.2: Verify pgstac roles
SELECT rolname FROM pg_roles WHERE rolname LIKE 'pgstac%';

-- Expected: pgstac_admin, pgstac_ingest, pgstac_read

-- 9.3: Verify system collections
SELECT id, content->>'title' as title FROM pgstac.collections;

-- Expected: system-vectors, system-rasters
```

---

## Troubleshooting

### Error: "permission denied for schema pgstac"

**Cause**: User doesn't have pgstac role membership.

**Solution**:
```sql
GRANT pgstac_admin TO <your_user>;
```

### Error: "relation pgstac.search_hash does not exist"

**Cause**: pypgstac migration didn't complete successfully.

**Solution**: Re-run `pypgstac migrate` - it's idempotent.

### Error: "type job_status already exists"

**Cause**: Running app schema SQL on existing schema.

**Solution**: Run `DROP SCHEMA app CASCADE;` first, or use `DROP TYPE IF EXISTS ... CASCADE` statements.

---

## Related Documentation

- **[WIKI_API_DATABASE.md](WIKI_API_DATABASE.md)** - Database setup and configuration
- **[DB_ADMIN_SQL.md](DB_ADMIN_SQL.md)** - Managed identity setup
- **[docs_claude/SCHEMA_ARCHITECTURE.md](docs_claude/SCHEMA_ARCHITECTURE.md)** - Schema architecture details

---

**Last Updated**: 22 JAN 2026 - Updated geo schema to IaC pattern (GeoTableCatalog, FeatureCollectionStyles Pydantic models)
