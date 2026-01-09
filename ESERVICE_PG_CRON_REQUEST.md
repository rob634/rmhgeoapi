# eService Request: Enable pg_cron Extension on PostgreSQL Flexible Server

**Date**: 08 JAN 2026
**Requestor**: Robert Harrison
**Environment**: QA / Production
**Priority**: Medium

---

## Server Details

| Field | Value |
|-------|-------|
| **Server Type** | Azure Database for PostgreSQL Flexible Server |
| **Server Name** | `{server-name}.postgres.database.azure.com` |
| **Database Name** | `{database-name}` |
| **PostgreSQL Version** | 15+ |
| **Current SKU** | Standard_D4s_v3 (or as configured) |

---

## Request Summary

Enable the **pg_cron** extension to allow scheduled database maintenance tasks (VACUUM, ANALYZE) to run asynchronously within PostgreSQL. This is required because Azure Functions have a 30-minute execution timeout, and maintenance operations on large tables (100M+ rows) exceed this limit.

---

## Server Parameter Changes Required

The following parameters must be configured in **Azure Portal** → **Server parameters**:

| Parameter | Current Value | New Value | Notes |
|-----------|---------------|-----------|-------|
| `azure.extensions` | `POSTGIS,H3` | `POSTGIS,H3,PG_CRON` | Add PG_CRON to allowlist |
| `shared_preload_libraries` | (empty or existing) | `pg_cron` | Add pg_cron; **requires restart** |
| `cron.database_name` | (empty) | `{database-name}` | Database where cron jobs run |

### Step-by-Step Portal Instructions

1. **Navigate to Server Parameters**
   - Azure Portal → Azure Database for PostgreSQL flexible servers
   - Select server → Settings → Server parameters

2. **Update `azure.extensions`**
   - Search for `azure.extensions`
   - Add `PG_CRON` to the comma-separated list
   - Example: `POSTGIS,H3,PG_CRON`

3. **Update `shared_preload_libraries`**
   - Search for `shared_preload_libraries`
   - Add `pg_cron` to the list
   - Example: `pg_cron` (or `pg_stat_statements,pg_cron` if others exist)

4. **Update `cron.database_name`**
   - Search for `cron.database_name`
   - Set value to: `{database-name}`

5. **Save Changes**
   - Click **Save** at the top of the page

6. **Restart Server** (REQUIRED)
   - Go to Overview → Click **Restart**
   - Confirm restart
   - Wait for server to come back online (~2-5 minutes)

---

## Post-Configuration SQL (Run After Restart)

After the server parameters are configured and the server is restarted, execute the following SQL:

```sql
-- ============================================================================
-- STEP 1: Create the pg_cron extension
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- Verify installation
SELECT extname, extversion FROM pg_extension WHERE extname = 'pg_cron';
-- Expected: pg_cron | 1.6 (or similar version)


-- ============================================================================
-- STEP 2: Grant permissions to application identity (if using Managed Identity)
-- ============================================================================
-- Replace {app-identity-name} with the actual managed identity name

GRANT USAGE ON SCHEMA cron TO "{app-identity-name}";
GRANT SELECT, INSERT, UPDATE, DELETE ON cron.job TO "{app-identity-name}";
GRANT SELECT ON cron.job_run_details TO "{app-identity-name}";


-- ============================================================================
-- STEP 3: Create scheduled maintenance jobs
-- ============================================================================

-- Nightly vacuum for large H3 table (2:00 AM UTC)
SELECT cron.schedule(
    'vacuum-h3-cells-nightly',
    '0 2 * * *',
    'VACUUM ANALYZE h3.cells'
);

-- Nightly vacuum for STAC items (3:00 AM UTC)
SELECT cron.schedule(
    'vacuum-pgstac-nightly',
    '0 3 * * *',
    'VACUUM ANALYZE pgstac.items; VACUUM ANALYZE pgstac.collections'
);

-- Nightly vacuum for application tables (4:00 AM UTC)
SELECT cron.schedule(
    'vacuum-app-schema-nightly',
    '0 4 * * *',
    'VACUUM ANALYZE app.jobs; VACUUM ANALYZE app.tasks'
);

-- Verify scheduled jobs
SELECT jobid, jobname, schedule, command, active FROM cron.job;


-- ============================================================================
-- STEP 4: Configure autovacuum for large tables (optional but recommended)
-- ============================================================================

-- H3 cells table (100M+ rows) - aggressive autovacuum settings
ALTER TABLE h3.cells SET (
    autovacuum_vacuum_scale_factor = 0.01,
    autovacuum_vacuum_threshold = 10000,
    autovacuum_analyze_scale_factor = 0.005,
    autovacuum_vacuum_cost_delay = 0,
    autovacuum_vacuum_cost_limit = 1000
);

-- STAC items table
ALTER TABLE pgstac.items SET (
    autovacuum_vacuum_scale_factor = 0.05,
    autovacuum_vacuum_threshold = 1000,
    autovacuum_vacuum_cost_delay = 2,
    autovacuum_vacuum_cost_limit = 400
);
```

---

## Business Justification

### Problem
Azure Functions have a maximum execution timeout of 30 minutes. Database maintenance operations (`VACUUM ANALYZE`) on large tables (100M+ rows) exceed this limit, causing function timeouts and incomplete maintenance.

### Solution
pg_cron allows scheduling maintenance jobs to run **inside PostgreSQL** rather than from external applications. Jobs execute asynchronously - the application can schedule a job and return immediately without waiting for completion.

### Benefits
1. **Avoids timeout failures** - Maintenance runs within PostgreSQL, not subject to function timeouts
2. **Scheduled maintenance** - Nightly vacuum jobs keep tables optimized
3. **On-demand scheduling** - Application can trigger async vacuum after bulk operations
4. **Built-in job management** - Queuing, history, and status tracking via `cron.job_run_details`

---

## Impact Assessment

| Aspect | Impact |
|--------|--------|
| **Downtime** | Brief restart required (~2-5 minutes) |
| **Schema Changes** | None to application tables; pg_cron uses separate `cron` schema |
| **Security** | Extension runs with database permissions; no elevated privileges |
| **Performance** | Scheduled jobs run during low-traffic hours (2-4 AM UTC) |
| **Storage** | Minimal (~1 MB for extension and job history) |
| **Compatibility** | pg_cron is GA on Azure Flexible Server and PostgreSQL 17 |

---

## Rollback Procedure

If issues occur, the extension can be disabled:

```sql
-- Remove all scheduled jobs
SELECT cron.unschedule(jobid) FROM cron.job;

-- Drop extension
DROP EXTENSION pg_cron;
```

Then revert server parameters:
- Remove `PG_CRON` from `azure.extensions`
- Remove `pg_cron` from `shared_preload_libraries`
- Clear `cron.database_name`
- Restart server

---

## Verification Checklist

After configuration, verify:

- [ ] Server parameters updated and saved
- [ ] Server restarted successfully
- [ ] `SELECT * FROM pg_extension WHERE extname = 'pg_cron'` returns a row
- [ ] Application identity has permissions on cron schema
- [ ] Scheduled jobs visible in `SELECT * FROM cron.job`
- [ ] Test job executes successfully (check `cron.job_run_details`)

---

## DEV Environment SQL (rmhpostgres - Ready to Run)

**Status**: Azure server parameters configured 09 JAN 2026. Run this SQL when you have network access.

```sql
-- ============================================================================
-- STEP 1: Create the pg_cron extension
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- Verify installation
SELECT extname, extversion FROM pg_extension WHERE extname = 'pg_cron';
-- Expected: pg_cron | 1.6 (or similar version)


-- ============================================================================
-- STEP 2: Schedule nightly vacuum jobs
-- ============================================================================

-- H3 cells (2:00 AM UTC) - the big table (114M+ rows)
SELECT cron.schedule('vacuum-h3-cells-nightly', '0 2 * * *', 'VACUUM ANALYZE h3.cells');

-- H3 zonal stats (2:30 AM UTC)
SELECT cron.schedule('vacuum-h3-zonal-stats-nightly', '30 2 * * *', 'VACUUM ANALYZE h3.zonal_stats');

-- STAC items and collections (3:00 AM UTC)
SELECT cron.schedule('vacuum-pgstac-nightly', '0 3 * * *', 'VACUUM ANALYZE pgstac.items; VACUUM ANALYZE pgstac.collections');

-- App schema jobs and tasks (4:00 AM UTC)
SELECT cron.schedule('vacuum-app-schema-nightly', '0 4 * * *', 'VACUUM ANALYZE app.jobs; VACUUM ANALYZE app.tasks');

-- Verify scheduled jobs
SELECT jobid, jobname, schedule, command, active FROM cron.job;


-- ============================================================================
-- STEP 3: Autovacuum tuning for large tables (recommended)
-- ============================================================================

-- H3 cells table (114M+ rows) - aggressive autovacuum settings
ALTER TABLE h3.cells SET (
    autovacuum_vacuum_scale_factor = 0.01,
    autovacuum_vacuum_threshold = 10000,
    autovacuum_analyze_scale_factor = 0.005,
    autovacuum_vacuum_cost_delay = 0,
    autovacuum_vacuum_cost_limit = 1000
);

-- H3 zonal stats
ALTER TABLE h3.zonal_stats SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 5000,
    autovacuum_vacuum_cost_delay = 0,
    autovacuum_vacuum_cost_limit = 500
);

-- STAC items table
ALTER TABLE pgstac.items SET (
    autovacuum_vacuum_scale_factor = 0.05,
    autovacuum_vacuum_threshold = 1000,
    autovacuum_vacuum_cost_delay = 2,
    autovacuum_vacuum_cost_limit = 400
);

-- App jobs table
ALTER TABLE app.jobs SET (
    autovacuum_vacuum_scale_factor = 0.1,
    autovacuum_vacuum_threshold = 500,
    autovacuum_vacuum_cost_delay = 2,
    autovacuum_vacuum_cost_limit = 300
);

-- App tasks table
ALTER TABLE app.tasks SET (
    autovacuum_vacuum_scale_factor = 0.05,
    autovacuum_vacuum_threshold = 1000,
    autovacuum_vacuum_cost_delay = 0,
    autovacuum_vacuum_cost_limit = 500
);


-- ============================================================================
-- STEP 4: Verify setup (run after a day or two)
-- ============================================================================

-- Check scheduled jobs
SELECT jobid, jobname, schedule, command, active FROM cron.job;

-- Check recent job runs (last 24 hours)
SELECT jobid, runid, command, status, return_message,
       start_time, end_time, end_time - start_time as duration
FROM cron.job_run_details
WHERE start_time > NOW() - INTERVAL '24 hours'
ORDER BY start_time DESC;

-- Check autovacuum status
SELECT schemaname, relname, last_vacuum, last_autovacuum,
       n_dead_tup, n_live_tup
FROM pg_stat_user_tables
WHERE schemaname IN ('h3', 'geo', 'pgstac', 'app')
ORDER BY n_dead_tup DESC;
```

---

## References

- [pg_cron GitHub Repository](https://github.com/citusdata/pg_cron)
- [Azure PostgreSQL Flexible Server Extensions](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/concepts-extensions)
- [pg_cron on Azure Documentation](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/how-to-use-pg-cron)

---

## Contact

| Role | Name |
|------|------|
| **Requestor** | Robert Harrison |
| **Application** | GeoAPI Platform |
| **Documentation** | `docs_claude/TABLE_MAINTENANCE.md` |
