# Production DDL Management

**STATUS:** Policy Document
**CREATED:** 29 JAN 2026
**APPLIES TO:** UAT, Production environments

---

## Overview

This document defines the separation between DDL (Data Definition Language) and DML (Data Manipulation Language) operations, and establishes the migration pattern for production database changes.

**Core Principle:** Application service accounts should never have DDL permissions in production. Schema changes require human review and controlled execution.

---

## Permission Model

### Application Service Account (DML Only)

The service account used by Function Apps, Docker Orchestrator, and Workers:

```sql
-- GRANTED (runtime operations)
SELECT, INSERT, UPDATE, DELETE ON schema.tables
EXECUTE ON schema.functions
USAGE ON schema

-- NOT GRANTED (infrastructure operations)
CREATE, ALTER, DROP
GRANT, REVOKE
TRUNCATE
REFERENCES
```

### Infrastructure Account (DDL)

Used only by DBA/Platform team for controlled migrations:

```sql
-- Full schema ownership for migrations
ALL PRIVILEGES ON SCHEMA dagapp, geoapi, pgstac
```

---

## Environment Patterns

### DEV / QA: Rebuild Schema (Red Button)

In development and QA, rapid iteration requires the ability to tear down and rebuild:

```
┌─────────────────────────────────────────────────────────────┐
│  DEV / QA PATTERN                                           │
│                                                             │
│  • "Rebuild Schema" button available                        │
│  • Drops and recreates all tables                           │
│  • Reseeds reference data                                   │
│  • Data loss is acceptable                                  │
│  • Developer can trigger directly                           │
│  • Used liberally during development                        │
└─────────────────────────────────────────────────────────────┘
```

**Acceptable because:**
- No real user data
- Fast iteration needed
- Mistakes are cheap
- Environment can be rebuilt in minutes

### UAT / Production: Migration Scripts

In UAT and Production, changes must be incremental and reversible:

```
┌─────────────────────────────────────────────────────────────┐
│  UAT / PRODUCTION PATTERN                                   │
│                                                             │
│  • No rebuild capability                                    │
│  • Incremental migrations only                              │
│  • All changes via versioned scripts                        │
│  • DBA/Platform team executes                               │
│  • Change ticket required                                   │
│  • Rollback script mandatory                                │
└─────────────────────────────────────────────────────────────┘
```

**Required because:**
- Real user data exists
- Downtime costs money
- Mistakes are expensive
- Audit trail mandatory
- Compliance requirements

---

## Migration Script Requirements

Every migration script MUST include the following sections:

### 1. Header Block

```sql
-- ============================================================================
-- MIGRATION: [NUMBER]_[DESCRIPTION].sql
-- ============================================================================
-- VERSION:     [Semantic version, e.g., 1.2.0]
-- TICKET:      [Change ticket number, e.g., CHG-2026-0142]
-- AUTHOR:      [Your name]
-- CREATED:     [Date]
-- REVIEWED BY: [DBA/Reviewer name]
-- REVIEWED ON: [Date]
-- ============================================================================
-- DESCRIPTION:
--   [What this migration does and why]
--
-- DEPENDENCIES:
--   - Requires migration [XXX] to be applied first
--   - Requires PgSTAC 0.9.x schema
--
-- IMPACT:
--   - Tables affected: [list]
--   - Estimated duration: [X minutes]
--   - Downtime required: [Yes/No]
--   - Lock escalation risk: [Low/Medium/High]
--
-- ROLLBACK:
--   - Rollback script: [NUMBER]_[DESCRIPTION]_rollback.sql
--   - Rollback tested: [Yes/No]
--   - Data recovery: [Automatic/Manual/Not possible]
-- ============================================================================
```

### 2. Pre-Flight Checks

```sql
-- ============================================================================
-- PRE-FLIGHT CHECKS
-- ============================================================================
-- These checks MUST pass before migration proceeds.
-- If any check fails, STOP and investigate.

-- Check 1: Verify current schema version
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM schema_migrations
        WHERE version = '[PREVIOUS_VERSION]'
        AND applied = true
    ) THEN
        RAISE EXCEPTION 'Pre-requisite migration [PREVIOUS_VERSION] not applied';
    END IF;
END $$;

-- Check 2: Verify no active locks on affected tables
DO $$
DECLARE
    lock_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO lock_count
    FROM pg_locks l
    JOIN pg_class c ON l.relation = c.oid
    WHERE c.relname IN ('affected_table_1', 'affected_table_2')
    AND l.mode IN ('AccessExclusiveLock', 'ExclusiveLock');

    IF lock_count > 0 THEN
        RAISE EXCEPTION 'Active locks detected on target tables. Aborting.';
    END IF;
END $$;

-- Check 3: Verify sufficient disk space (if adding large columns/indexes)
-- [Custom check based on migration needs]

-- Check 4: Record migration start
INSERT INTO schema_migrations (version, description, started_at, applied)
VALUES ('[VERSION]', '[DESCRIPTION]', NOW(), false);
```

### 3. Migration Body

```sql
-- ============================================================================
-- MIGRATION
-- ============================================================================
-- Execute within transaction for atomicity (where possible)

BEGIN;

-- Step 1: [Description]
ALTER TABLE dagapp.jobs ADD COLUMN IF NOT EXISTS new_column TEXT;

-- Step 2: [Description]
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_jobs_new_column
ON dagapp.jobs(new_column);
-- Note: CREATE INDEX CONCURRENTLY cannot run in transaction

-- Step 3: [Description]
-- [Additional DDL operations]

COMMIT;
```

### 4. Post-Flight Validation

```sql
-- ============================================================================
-- POST-FLIGHT VALIDATION
-- ============================================================================
-- These checks verify the migration was successful.

-- Validation 1: New column exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'dagapp'
        AND table_name = 'jobs'
        AND column_name = 'new_column'
    ) THEN
        RAISE EXCEPTION 'Validation failed: new_column not found';
    END IF;
END $$;

-- Validation 2: Index exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname = 'dagapp'
        AND indexname = 'idx_jobs_new_column'
    ) THEN
        RAISE EXCEPTION 'Validation failed: index not created';
    END IF;
END $$;

-- Validation 3: Record migration complete
UPDATE schema_migrations
SET applied = true, completed_at = NOW()
WHERE version = '[VERSION]';

-- Output success
DO $$ BEGIN RAISE NOTICE 'Migration [VERSION] completed successfully'; END $$;
```

### 5. Rollback Script (Separate File)

```sql
-- ============================================================================
-- ROLLBACK: [NUMBER]_[DESCRIPTION]_rollback.sql
-- ============================================================================
-- TICKET:      [Same ticket number]
-- ROLLS BACK:  [VERSION]
-- ============================================================================
-- WARNING: Review data implications before executing rollback.
-- Some operations may not be fully reversible.
-- ============================================================================

BEGIN;

-- Step 1: Remove index
DROP INDEX IF EXISTS dagapp.idx_jobs_new_column;

-- Step 2: Remove column
ALTER TABLE dagapp.jobs DROP COLUMN IF EXISTS new_column;

-- Step 3: Update migration record
UPDATE schema_migrations
SET applied = false, rolled_back_at = NOW()
WHERE version = '[VERSION]';

COMMIT;

DO $$ BEGIN RAISE NOTICE 'Rollback of [VERSION] completed'; END $$;
```

---

## Migration Tracking Table

Create this table in each environment to track applied migrations:

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    id SERIAL PRIMARY KEY,
    version VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    applied BOOLEAN DEFAULT false,
    rolled_back_at TIMESTAMP WITH TIME ZONE,
    executed_by VARCHAR(100),
    ticket_number VARCHAR(50)
);

CREATE INDEX idx_migrations_version ON schema_migrations(version);
CREATE INDEX idx_migrations_applied ON schema_migrations(applied);
```

---

## Change Management Process

### Step 1: Development

```
Developer writes migration script
    ↓
Test in DEV environment
    ↓
Commit to repository: migrations/[VERSION]_[description].sql
    ↓
Create pull request with:
    - Migration script
    - Rollback script
    - Test evidence from DEV
```

### Step 2: Review

```
DBA reviews migration script for:
    ↓
    ├── Syntax correctness
    ├── Lock escalation risks
    ├── Index strategy
    ├── Rollback completeness
    ├── Performance implications
    ↓
Approved → Merge to main branch
```

### Step 3: QA Execution

```
Platform team runs migration in QA
    ↓
QA team validates application behavior
    ↓
Sign-off for UAT
```

### Step 4: UAT Execution

```
Create change ticket (CHG-XXXX-XXXX)
    ↓
Change Advisory Board approval (if required)
    ↓
Schedule maintenance window (if downtime needed)
    ↓
Platform team executes migration
    ↓
Application team validates
    ↓
Sign-off for Production
```

### Step 5: Production Execution

```
Change ticket approved for Production
    ↓
Platform team executes during maintenance window
    ↓
Post-deployment validation
    ↓
Close change ticket
```

---

## High-Risk Operations

The following operations require additional scrutiny:

| Operation | Risk | Mitigation |
|-----------|------|------------|
| `DROP TABLE` | Data loss | Backup verification, delayed drop |
| `DROP COLUMN` | Data loss | Archive data first, rollback window |
| `ALTER TYPE` | Lock escalation | Off-hours, table rewrite |
| `ADD NOT NULL` | Lock + backfill | Add nullable, backfill, then constrain |
| `CREATE INDEX` | Table lock | Use `CONCURRENTLY` |
| `TRUNCATE` | Data loss | Almost never in production |

### Safe Pattern: Adding NOT NULL Column

```sql
-- WRONG: Locks table while setting default for all rows
ALTER TABLE jobs ADD COLUMN status TEXT NOT NULL DEFAULT 'pending';

-- RIGHT: Three-step process
-- Step 1: Add nullable column
ALTER TABLE jobs ADD COLUMN status TEXT;

-- Step 2: Backfill in batches (application or script)
UPDATE jobs SET status = 'pending' WHERE status IS NULL LIMIT 10000;
-- Repeat until complete

-- Step 3: Add constraint
ALTER TABLE jobs ALTER COLUMN status SET NOT NULL;
ALTER TABLE jobs ALTER COLUMN status SET DEFAULT 'pending';
```

---

## File Organization

```
rmhgeoapi/
├── migrations/
│   ├── README.md                           # This document (link)
│   ├── 001_initial_schema.sql
│   ├── 001_initial_schema_rollback.sql
│   ├── 002_add_dag_tables.sql
│   ├── 002_add_dag_tables_rollback.sql
│   ├── 003_geospatial_asset_v08.sql
│   ├── 003_geospatial_asset_v08_rollback.sql
│   └── ...
└── PRODUCTION_DDL.md                       # This document
```

---

## Emergency Procedures

### Rollback During Deployment

If migration fails mid-execution:

1. **DO NOT** attempt manual fixes
2. Execute the rollback script
3. Verify application functionality
4. Investigate root cause
5. Fix script and re-test in lower environment
6. Reschedule production deployment

### Production Incident

If migration causes production issues after completion:

1. Assess: Is rollback safe? (data written since migration?)
2. If safe: Execute rollback script
3. If unsafe: Implement forward-fix
4. Document incident for post-mortem

---

## Checklist: Before Production Deployment

```
[ ] Migration script committed and reviewed
[ ] Rollback script committed and reviewed
[ ] Tested in DEV
[ ] Tested in QA
[ ] Tested in UAT
[ ] Change ticket created and approved
[ ] Maintenance window scheduled (if needed)
[ ] DBA/Platform team briefed
[ ] Application team on standby for validation
[ ] Rollback plan documented
[ ] Communication sent to stakeholders
```

---

## Contact

| Role | Responsibility |
|------|----------------|
| Application Team | Write migrations, validate behavior |
| DBA / Platform Team | Review and execute migrations |
| Change Management | Approve change tickets |
