# Table Maintenance - VACUUM and Autovacuum Strategy

**Created**: 08 JAN 2026
**Status**: Implementation Guide

---

## Problem Statement

Azure Functions have a 30-minute timeout limit. Running `VACUUM ANALYZE` on large tables (e.g., h3.cells with 114M rows) synchronously blocks the function and causes timeout failures.

**Observed failure**: Rwanda H3 bootstrap Stage 3 timed out at 30 minutes due to `VACUUM ANALYZE h3.cells` call.

---

## Solution: pg_cron + Autovacuum Tuning

Two complementary approaches:

| Approach | Purpose | Use Case |
|----------|---------|----------|
| **pg_cron** | Scheduled/on-demand async VACUUM | Post-bulk-load maintenance |
| **Autovacuum tuning** | Aggressive per-table settings | Routine maintenance between bulk loads |

---

## Part 1: pg_cron Setup

### Step 1: Azure Portal Configuration

Navigate to **Azure Portal** > **PostgreSQL Flexible Server** > **Server Parameters**:

1. **Enable pg_cron extension**:
   - Find `azure.extensions`
   - Add `pg_cron` to the list

2. **Add to shared_preload_libraries**:
   - Find `shared_preload_libraries`
   - Add `pg_cron` (comma-separated if other extensions exist)

3. **Set cron database**:
   - Find `cron.database_name`
   - Set to `geopgflex` (your database name)

4. **Restart server** (required for shared_preload_libraries changes)

```bash
# Alternatively via CLI:
az postgres flexible-server parameter set \
    --resource-group rmhazure_rg \
    --server-name rmhpostgres \
    --name azure.extensions \
    --value "pg_cron,postgis,h3,pgstac"

az postgres flexible-server parameter set \
    --resource-group rmhazure_rg \
    --server-name rmhpostgres \
    --name shared_preload_libraries \
    --value "pg_cron"

az postgres flexible-server parameter set \
    --resource-group rmhazure_rg \
    --server-name rmhpostgres \
    --name cron.database_name \
    --value "geopgflex"

az postgres flexible-server restart \
    --resource-group rmhazure_rg \
    --server-name rmhpostgres
```

### Step 2: Create Extension in Database

```sql
-- Run as superuser/admin
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- Verify installation
SELECT * FROM pg_extension WHERE extname = 'pg_cron';
```

### Step 3: Grant Permissions

```sql
-- Grant cron job management to the app user
GRANT USAGE ON SCHEMA cron TO your_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON cron.job TO your_app_user;
```

### Step 4: Create Scheduled Vacuum Jobs

```sql
-- Nightly vacuum for H3 cells (2 AM UTC)
SELECT cron.schedule('vacuum-h3-cells', '0 2 * * *',
    'VACUUM ANALYZE h3.cells');

-- Nightly vacuum for geo tables (3 AM UTC)
SELECT cron.schedule('vacuum-geo-tables', '0 3 * * *',
    'VACUUM ANALYZE geo.flood_polygons; VACUUM ANALYZE geo.admin0; VACUUM ANALYZE geo.admin1;');

-- Nightly vacuum for STAC items (4 AM UTC)
SELECT cron.schedule('vacuum-pgstac', '0 4 * * *',
    'VACUUM ANALYZE pgstac.items; VACUUM ANALYZE pgstac.collections;');

-- Verify jobs
SELECT * FROM cron.job;
```

### Step 5: On-Demand Vacuum Pattern

For fire-and-forget vacuum calls from handlers:

```python
# In services/table_maintenance.py

def schedule_vacuum_async(table_name: str, conn) -> dict:
    """
    Schedule a one-time VACUUM via pg_cron.

    Returns immediately - vacuum runs asynchronously in database.
    """
    import time

    # Create unique job name
    job_name = f"vacuum-{table_name.replace('.', '-')}-{int(time.time())}"

    # Schedule for next minute
    conn.execute(f"""
        SELECT cron.schedule(
            '{job_name}',
            '* * * * *',
            'VACUUM ANALYZE {table_name}'
        );
    """)

    # Immediately unschedule (job is already queued for next minute)
    conn.execute(f"SELECT cron.unschedule('{job_name}');")

    return {
        "status": "vacuum_scheduled",
        "table": table_name,
        "job_name": job_name,
        "note": "Will execute within 1 minute"
    }
```

---

## Part 2: Autovacuum Tuning

### Per-Table Settings for Large Tables

Apply aggressive autovacuum to tables that receive bulk inserts:

```sql
-- H3 cells table (114M+ rows)
ALTER TABLE h3.cells SET (
    autovacuum_vacuum_scale_factor = 0.01,    -- 1% dead tuples (default: 20%)
    autovacuum_vacuum_threshold = 10000,       -- min 10K dead tuples
    autovacuum_analyze_scale_factor = 0.005,   -- analyze at 0.5%
    autovacuum_vacuum_cost_delay = 0,          -- no delay between batches
    autovacuum_vacuum_cost_limit = 1000        -- aggressive (default: 200)
);

-- H3 zonal stats (partitioned - apply to parent and partitions)
ALTER TABLE h3.zonal_stats SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 5000,
    autovacuum_vacuum_cost_delay = 0,
    autovacuum_vacuum_cost_limit = 500
);

-- Geo flood polygons
ALTER TABLE geo.flood_polygons SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 5000,
    autovacuum_vacuum_cost_delay = 0,
    autovacuum_vacuum_cost_limit = 500
);

-- PGSTAC items
ALTER TABLE pgstac.items SET (
    autovacuum_vacuum_scale_factor = 0.05,
    autovacuum_vacuum_threshold = 1000,
    autovacuum_vacuum_cost_delay = 2,
    autovacuum_vacuum_cost_limit = 400
);
```

### Server-Level Tuning (Optional)

For very heavy ETL workloads, increase server-level settings:

```bash
# Via Azure CLI
az postgres flexible-server parameter set \
    --resource-group rmhazure_rg \
    --server-name rmhpostgres \
    --name maintenance_work_mem \
    --value "1048576"  # 1GB (in KB)

az postgres flexible-server parameter set \
    --resource-group rmhazure_rg \
    --server-name rmhpostgres \
    --name autovacuum_max_workers \
    --value "4"  # More parallel workers
```

---

## Part 3: Handler Integration Pattern

### Updated H3 Finalize Handler

```python
# In handler_finalize_h3_pyramid.py

def finalize_h3_pyramid(params: Dict[str, Any], context: Dict[str, Any] = None):
    # ... existing verification logic ...

    # VACUUM handling - fire and forget via pg_cron
    run_vacuum = params.get('run_vacuum', False)  # Default OFF

    if run_vacuum:
        vacuum_result = _schedule_vacuum_async(h3_repo, 'h3.cells', logger)
        # vacuum_result = {"status": "vacuum_scheduled", ...}
    else:
        vacuum_result = {"status": "skipped", "note": "Run manually or via nightly cron"}

    return {
        "success": True,
        "result": {
            "verified_resolutions": resolutions,
            "total_cells": total_cells,
            "vacuum_status": vacuum_result,  # Changed from vacuum_completed bool
            ...
        }
    }


def _schedule_vacuum_async(h3_repo, table_name: str, logger) -> dict:
    """Schedule VACUUM via pg_cron (fire-and-forget)."""
    import time

    logger.info(f"Scheduling async VACUUM for {table_name}...")

    try:
        with h3_repo._get_connection() as conn:
            job_name = f"vacuum-{table_name.replace('.', '-')}-{int(time.time())}"

            with conn.cursor() as cur:
                # Schedule for next minute
                cur.execute(
                    "SELECT cron.schedule(%s, '* * * * *', %s)",
                    (job_name, f'VACUUM ANALYZE {table_name}')
                )
                # Immediately unschedule (job already queued)
                cur.execute("SELECT cron.unschedule(%s)", (job_name,))

            conn.commit()

        logger.info(f"VACUUM scheduled: {job_name} (executes within 1 minute)")
        return {
            "status": "scheduled",
            "table": table_name,
            "job_name": job_name
        }

    except Exception as e:
        logger.warning(f"Failed to schedule async VACUUM (non-critical): {e}")
        return {
            "status": "schedule_failed",
            "error": str(e),
            "note": "Run VACUUM manually: VACUUM ANALYZE " + table_name
        }
```

---

## Monitoring

### Check pg_cron Job History

```sql
-- Recent job runs
SELECT jobid, runid, job_pid, database, username, command, status,
       return_message, start_time, end_time
FROM cron.job_run_details
ORDER BY start_time DESC
LIMIT 20;

-- Running jobs
SELECT * FROM cron.job_run_details WHERE status = 'running';

-- Failed jobs (last 24 hours)
SELECT * FROM cron.job_run_details
WHERE status = 'failed'
AND start_time > NOW() - INTERVAL '24 hours';
```

### Check Autovacuum Status

```sql
-- Current autovacuum activity
SELECT schemaname, relname, last_vacuum, last_autovacuum,
       last_analyze, last_autoanalyze, n_dead_tup, n_live_tup
FROM pg_stat_user_tables
WHERE n_dead_tup > 1000
ORDER BY n_dead_tup DESC;

-- Bloat estimation
SELECT schemaname, tablename,
       pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) as size
FROM pg_tables
WHERE schemaname IN ('h3', 'geo', 'pgstac')
ORDER BY pg_total_relation_size(schemaname || '.' || tablename) DESC;
```

---

## Rollback Plan

If pg_cron causes issues:

```sql
-- Remove all scheduled jobs
SELECT cron.unschedule(jobid) FROM cron.job;

-- Drop extension (if needed)
DROP EXTENSION pg_cron;
```

Then revert handler to synchronous VACUUM (with increased function timeout if possible).

---

## Summary

| Component | Action | Priority |
|-----------|--------|----------|
| pg_cron extension | Enable in Azure Portal | High |
| Nightly vacuum jobs | Create 3 scheduled jobs | High |
| Autovacuum tuning | Apply to h3.cells, geo.*, pgstac.* | Medium |
| Handler update | Fire-and-forget vacuum via pg_cron | High |
| Monitoring | Add cron job status to health endpoint | Low |
