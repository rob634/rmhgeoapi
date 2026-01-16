# Schema Evolution Guide

**Last Updated**: 16 JAN 2026
**Purpose**: Patterns for evolving the database schema safely

---

## Core Principle

> **Prefer non-breaking (additive) changes. Breaking changes require migration plans.**

The app schema should evolve incrementally. New features should add new tables/columns rather than modify existing ones. This allows:

- Safe deployments with `action=ensure`
- No data loss during updates
- Rollback capability (old code can ignore new columns)
- Zero-downtime deployments

---

## Schema Change Categories

### 1. Non-Breaking Changes (Safe)

These changes are **additive** and can be deployed using `action=ensure`:

| Change | SQL Pattern | Notes |
|--------|-------------|-------|
| New table | `CREATE TABLE IF NOT EXISTS` | Always safe |
| New column with default | `ALTER TABLE ADD COLUMN ... DEFAULT` | Safe if default provided |
| New index | `CREATE INDEX IF NOT EXISTS` | Safe, may take time on large tables |
| New enum type | `CREATE TYPE IF NOT EXISTS` | Safe |
| New function | `CREATE OR REPLACE FUNCTION` | Safe |

**Deployment**:
```bash
# Deploy code with new models
func azure functionapp publish rmhazuregeoapi --python --build remote

# Create missing objects (safe - no data loss)
curl -X POST ".../api/dbadmin/maintenance?action=ensure&confirm=yes"
```

### 2. Breaking Changes (Require Migration)

These changes **modify existing structures** and require a migration plan:

| Change | Risk | Migration Required |
|--------|------|-------------------|
| Rename column | Code references break | Yes - copy data, update code |
| Rename table | All queries break | Yes - copy data, update code |
| Change column type | Data conversion issues | Yes - add new column, migrate, drop old |
| Remove column | Old code may reference | Yes - verify no references first |
| Remove table | Data loss | Yes - backup, verify no references |
| Add NOT NULL to existing column | Existing NULLs fail | Yes - fill NULLs first |
| Add enum value | PostgreSQL limitation | Yes - see enum section |

---

## Detailed Patterns

### Pattern 1: Adding a New Table

**Scenario**: Adding `dataset_approvals` table for new approval workflow.

**Steps**:
1. Create Pydantic model in `core/models/`
2. Export from `core/models/__init__.py`
3. Register in `core/schema/sql_generator.py`
4. Deploy and run `action=ensure`

**Example** (16 JAN 2026 - Dataset Approvals):
```python
# core/models/approval.py
class DatasetApproval(BaseModel):
    approval_id: str = Field(..., max_length=64)
    job_id: str = Field(..., max_length=64)
    status: ApprovalStatus = Field(default=ApprovalStatus.PENDING)
    # ... etc

# core/schema/sql_generator.py - add to generate_composed_statements()
composed.append(self.generate_table_composed(DatasetApproval, "dataset_approvals"))
composed.extend(self.generate_indexes_composed("dataset_approvals", DatasetApproval))
```

**Deployment**:
```bash
curl -X POST ".../api/dbadmin/maintenance?action=ensure&confirm=yes"
# Response shows: tables_created: 1, indexes_created: 6
```

### Pattern 2: Adding a Column to Existing Table

**Scenario**: Adding `priority` column to `jobs` table.

**Safe Approach** (with DEFAULT):
```python
# In Pydantic model
priority: int = Field(default=0, description="Job priority (0=normal)")
```

The SQL generator will produce:
```sql
ALTER TABLE app.jobs ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 0;
```

**Unsafe Approach** (NOT NULL without DEFAULT):
```python
# DON'T DO THIS - will fail on existing rows
priority: int = Field(..., description="Required priority")  # No default!
```

### Pattern 3: Adding an Index

**Scenario**: Adding index for faster approval queries.

```python
# In sql_generator.py generate_indexes_composed()
elif table_name == "dataset_approvals":
    indexes.append(IndexBuilder.btree(s, "dataset_approvals", "status"))
    indexes.append(IndexBuilder.btree(s, "dataset_approvals", "created_at", descending=True))
```

**Note**: Large table indexes may lock the table briefly. For production tables with millions of rows, consider `CREATE INDEX CONCURRENTLY` (requires manual migration).

### Pattern 4: Adding Enum Values (Careful!)

**Problem**: PostgreSQL enums are immutable by default. You cannot add values with `IF NOT EXISTS`.

**Current Approach**: Our `sql_generator.py` uses:
```sql
DROP TYPE IF EXISTS app.status_enum CASCADE;
CREATE TYPE app.status_enum AS ENUM ('pending', 'approved', 'rejected');
```

This works for `action=rebuild` but **fails for `action=ensure`** because:
- `DROP TYPE CASCADE` drops dependent columns
- We can't safely drop types in additive mode

**Safe Approach for Adding Enum Values**:

1. **Write a migration script**:
```sql
-- migrations/001_add_enum_value.sql
ALTER TYPE app.approval_status ADD VALUE IF NOT EXISTS 'expired';
```

2. **Run manually or via dbadmin/query endpoint**:
```bash
curl -X POST ".../api/dbadmin/query" \
  -H "Content-Type: application/json" \
  -d '{"sql": "ALTER TYPE app.approval_status ADD VALUE IF NOT EXISTS '\''expired'\'';"}'
```

3. **Update the Pydantic enum** (for new deployments):
```python
class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"  # New value
```

---

## Migration Plan Template

For breaking changes, create a migration plan document:

```markdown
# Migration: [Brief Description]

**Date**: DD MMM YYYY
**Author**: [Name]
**Risk Level**: Low / Medium / High

## Summary
[What is changing and why]

## Pre-Migration Checklist
- [ ] Backup taken
- [ ] Tested on dev environment
- [ ] Rollback plan documented
- [ ] Downtime window scheduled (if needed)

## Migration Steps

### Step 1: [Description]
```sql
-- SQL to execute
```

### Step 2: [Description]
```sql
-- SQL to execute
```

## Verification
```sql
-- Queries to verify migration success
SELECT COUNT(*) FROM app.table_name WHERE new_column IS NOT NULL;
```

## Rollback Plan
```sql
-- SQL to undo changes if needed
```

## Post-Migration
- [ ] Verify application health
- [ ] Monitor error rates
- [ ] Update documentation
```

---

## Migration Examples

### Example 1: Rename Column

**Scenario**: Rename `job_params` to `parameters` in jobs table.

```sql
-- Step 1: Add new column
ALTER TABLE app.jobs ADD COLUMN parameters JSONB;

-- Step 2: Copy data
UPDATE app.jobs SET parameters = job_params;

-- Step 3: Deploy new code (reads from 'parameters')

-- Step 4: Verify no code uses old column
-- Search codebase for 'job_params'

-- Step 5: Drop old column (only after verification)
ALTER TABLE app.jobs DROP COLUMN job_params;
```

### Example 2: Change Column Type

**Scenario**: Change `status` from VARCHAR to ENUM.

```sql
-- Step 1: Create enum type
CREATE TYPE app.job_status_enum AS ENUM ('pending', 'processing', 'completed', 'failed');

-- Step 2: Add new column
ALTER TABLE app.jobs ADD COLUMN status_new app.job_status_enum;

-- Step 3: Migrate data
UPDATE app.jobs SET status_new = status::app.job_status_enum;

-- Step 4: Deploy code using new column

-- Step 5: Swap columns
ALTER TABLE app.jobs DROP COLUMN status;
ALTER TABLE app.jobs RENAME COLUMN status_new TO status;
```

### Example 3: Split Table

**Scenario**: Extract `job_metadata` from `jobs` table.

```sql
-- Step 1: Create new table
CREATE TABLE app.job_metadata (
    job_id VARCHAR(64) PRIMARY KEY REFERENCES app.jobs(job_id),
    source_file VARCHAR(500),
    file_size BIGINT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Step 2: Migrate data
INSERT INTO app.job_metadata (job_id, source_file, file_size, created_at)
SELECT job_id, source_file, file_size, created_at FROM app.jobs;

-- Step 3: Deploy code using new table

-- Step 4: Drop old columns from jobs
ALTER TABLE app.jobs DROP COLUMN source_file;
ALTER TABLE app.jobs DROP COLUMN file_size;
```

---

## Schema Versioning (Future)

For production deployments, consider implementing schema versioning:

```sql
-- Track schema version
CREATE TABLE IF NOT EXISTS app.schema_version (
    version INTEGER PRIMARY KEY,
    description TEXT,
    applied_at TIMESTAMP DEFAULT NOW()
);

-- Check current version
SELECT MAX(version) FROM app.schema_version;
```

This allows:
- Tracking which migrations have been applied
- Preventing duplicate migrations
- Auditing schema changes

---

## Quick Reference

### Safe Operations (use `action=ensure`)
```bash
curl -X POST ".../api/dbadmin/maintenance?action=ensure&confirm=yes"
```
- New tables
- New columns with defaults
- New indexes
- New enum types

### Destructive Operations (use `action=rebuild`)
```bash
curl -X POST ".../api/dbadmin/maintenance?action=rebuild&confirm=yes"
```
- Fresh start (dev/test only)
- After major schema redesign
- When data can be regenerated

### Manual Migrations
```bash
# Via psql
psql -h $POSTGIS_HOST -U $POSTGIS_USER -d $POSTGIS_DATABASE -f migration.sql

# Via API (if query endpoint exists)
curl -X POST ".../api/dbadmin/query" -d '{"sql": "..."}'
```

---

## Related Documentation

- `CLAUDE.md` - Quick reference and decision tree
- `docs_claude/ARCHITECTURE_REFERENCE.md` - Full architecture details
- `core/schema/sql_generator.py` - DDL generation implementation
- `triggers/admin/db_maintenance.py` - Schema management endpoints
