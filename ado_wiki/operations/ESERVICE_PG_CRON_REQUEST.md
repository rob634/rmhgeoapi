# User Story: Database Maintenance Scheduling (pg_cron)

**ADO Work Item Type**: User Story
**Parent Feature**: E7 Pipeline Infrastructure (ADO: "ETL Pipeline Infrastructure")
**Story Points**: 3
**Tags**: geo-platform, v0.8, infra, enabler, database

---

## User Story

**AS A** platform operator
**I WANT** scheduled database maintenance (VACUUM ANALYZE) running inside PostgreSQL
**SO THAT** large tables (100M+ rows) stay optimized without hitting Azure Function timeouts

---

## Acceptance Criteria

- [ ] pg_cron extension enabled on all environments
- [ ] Nightly VACUUM ANALYZE scheduled for: h3.cells, pgstac.items, app.jobs, app.tasks
- [ ] Autovacuum tuned for large tables (h3.cells 114M+ rows)
- [ ] Job history queryable via `cron.job_run_details`

---

## Tasks

| Task | Environment | Status | Notes |
|------|-------------|--------|-------|
| Configure Azure server parameters | DEV | ✅ Done 09 JAN 2026 | `azure.extensions`, `shared_preload_libraries`, `cron.database_name` |
| Run SQL setup (CREATE EXTENSION, schedules) | DEV | 📋 Ready | SQL below - run when on network |
| Submit eService request | QA | 📋 Pending | Use template below |
| Submit eService request | UAT | 📋 Pending | Use template below |
| Submit eService request | PROD | 📋 Pending | Use template below |

---

## Implementation Notes

### Business Justification
Azure Functions have 30-minute timeout. VACUUM on h3.cells (114M+ rows) exceeds this. pg_cron runs maintenance **inside PostgreSQL** asynchronously.

### Server Parameter Changes (eService Request)

| Parameter | Value | Notes |
|-----------|-------|-------|
| `azure.extensions` | Add `PG_CRON` | Allowlist the extension |
| `shared_preload_libraries` | Add `pg_cron` | **Requires restart** |
| `cron.database_name` | `{database-name}` | Target database |

### Post-Configuration SQL

```sql
-- ============================================================================
-- STEP 1: Create extension
-- ============================================================================
-- NOTE: Run this AFTER enabling pg_cron in Azure Portal and restarting server
CREATE EXTENSION IF NOT EXISTS pg_cron;
SELECT extname, extversion FROM pg_extension WHERE extname = 'pg_cron';

-- ============================================================================
-- STEP 2: Schedule nightly vacuum jobs
-- ============================================================================

-- H3 cells (2:00 AM UTC) - Primary large table
SELECT cron.schedule('vacuum-h3-cells-nightly', '0 2 * * *', 'VACUUM ANALYZE h3.cells');

-- H3 zonal stats (2:30 AM UTC)
SELECT cron.schedule('vacuum-h3-zonal-stats-nightly', '30 2 * * *', 'VACUUM ANALYZE h3.zonal_stats');

-- Geo schema tables (3:00 AM UTC) - Dynamic vacuum for all user vector tables
SELECT cron.schedule(
    'vacuum-geo-tables-nightly',
    '0 3 * * *',
    $$
    DO $$
    DECLARE
        tbl RECORD;
    BEGIN
        FOR tbl IN
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = 'geo'
            AND table_type = 'BASE TABLE'
            AND table_name != 'table_metadata'
        LOOP
            EXECUTE format('VACUUM ANALYZE %I.%I', tbl.table_schema, tbl.table_name);
        END LOOP;
    END $$;
    $$
);

-- STAC items (4:00 AM UTC)
SELECT cron.schedule('vacuum-pgstac-nightly', '0 4 * * *', 'VACUUM ANALYZE pgstac.items; VACUUM ANALYZE pgstac.collections');

-- App schema (4:30 AM UTC)
SELECT cron.schedule('vacuum-app-schema-nightly', '30 4 * * *', 'VACUUM ANALYZE app.jobs; VACUUM ANALYZE app.tasks');

-- Verify scheduled jobs
SELECT jobid, jobname, schedule, command, database, username, active FROM cron.job ORDER BY jobname;

-- ============================================================================
-- STEP 3: Autovacuum tuning for large tables
-- ============================================================================
-- These settings make autovacuum more aggressive for bulk-loaded tables.

-- H3 cells table (100M+ rows expected)
ALTER TABLE h3.cells SET (
    autovacuum_vacuum_scale_factor = 0.01,      -- 1% dead tuples (default: 20%)
    autovacuum_vacuum_threshold = 10000,         -- minimum 10K dead tuples
    autovacuum_analyze_scale_factor = 0.005,     -- analyze at 0.5%
    autovacuum_analyze_threshold = 5000,         -- minimum 5K for analyze
    autovacuum_vacuum_cost_delay = 0,            -- no delay between batches
    autovacuum_vacuum_cost_limit = 1000          -- aggressive (default: 200)
);

-- H3 zonal stats
ALTER TABLE h3.zonal_stats SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 5000,
    autovacuum_analyze_scale_factor = 0.01,
    autovacuum_vacuum_cost_delay = 0,
    autovacuum_vacuum_cost_limit = 500
);

-- STAC items
ALTER TABLE pgstac.items SET (
    autovacuum_vacuum_scale_factor = 0.05,
    autovacuum_vacuum_threshold = 1000,
    autovacuum_analyze_scale_factor = 0.02,
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
```

### Monitoring Queries

```sql
-- View scheduled cron jobs
SELECT * FROM cron.job;

-- View recent job runs (last 24 hours)
SELECT jobid, runid, job_pid, command, status, return_message,
       start_time, end_time, end_time - start_time as duration
FROM cron.job_run_details
WHERE start_time > NOW() - INTERVAL '24 hours'
ORDER BY start_time DESC;

-- View autovacuum status for our tables
SELECT schemaname, relname, last_vacuum, last_autovacuum,
       last_analyze, last_autoanalyze, n_dead_tup, n_live_tup,
       ROUND(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2) as dead_pct
FROM pg_stat_user_tables
WHERE schemaname IN ('h3', 'geo', 'pgstac', 'app')
ORDER BY n_dead_tup DESC;

-- View current autovacuum settings for a table
SELECT relname, reloptions
FROM pg_class
WHERE relname = 'cells' AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'h3');
```

### Rollback (if needed)

```sql
-- Disable all scheduled jobs
SELECT cron.unschedule(jobid) FROM cron.job;

-- Remove pg_cron extension
DROP EXTENSION pg_cron;

-- Reset autovacuum to defaults (example for h3.cells)
ALTER TABLE h3.cells RESET (
    autovacuum_vacuum_scale_factor,
    autovacuum_vacuum_threshold,
    autovacuum_analyze_scale_factor,
    autovacuum_analyze_threshold,
    autovacuum_vacuum_cost_delay,
    autovacuum_vacuum_cost_limit
);
```

---

## eService Request Template

**Subject**: Enable pg_cron Extension on PostgreSQL Flexible Server

**Request**:
Enable pg_cron extension for scheduled database maintenance.

**Server**: `{server-name}.postgres.database.azure.com`
**Database**: `{database-name}`

**Parameter Changes**:
1. Add `PG_CRON` to `azure.extensions`
2. Add `pg_cron` to `shared_preload_libraries`
3. Set `cron.database_name` to `{database-name}`
4. **Restart server** (required for shared_preload_libraries)

**Justification**: Application timeout limits prevent long-running maintenance on large tables. pg_cron runs maintenance inside PostgreSQL.

**Impact**: Brief restart (~2-5 min). No schema changes. Extension uses separate `cron` schema.

**Rollback**: Remove extension and parameters, restart.

---

## References

- [pg_cron on Azure](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/how-to-use-pg-cron)
- [pg_cron GitHub](https://github.com/citusdata/pg_cron)

---

*Last Updated*: 02 FEB 2026
