# Resubmit Hardening — Implementation Plan

**Date**: 20 FEB 2026
**Story**: Fix 5 issues in `JobResubmitHandler` found during flow trace
**SAFe Type**: Enabler (bug fixes + hardening)
**File**: `triggers/jobs/resubmit.py`

---

## Issues (Severity Order)

| # | Severity | Issue | Lines |
|---|----------|-------|-------|
| C | CRITICAL | `PostgreSQLAdapter` doesn't exist — vector resubmit crashes with `ImportError` | 334-347 |
| D | Medium | New job missing `asset_id` FK — breaks job→asset linkage | 422-433 |
| B | Medium | `table_name` not found for vector cleanup — only checks `parameters`, not `result_data` | 228-231 |
| E | Low | Deterministic `job_id` collision — if old job delete fails, new insert silently does nothing | 416-419 |
| A | Cosmetic | STAC cleanup references stale in B2C architecture | 233-249 |

---

## Fix C: Replace `PostgreSQLAdapter` with Working Pattern

**Problem**: `_drop_table()` imports `PostgreSQLAdapter` which doesn't exist anywhere in the codebase. Vector resubmit crashes immediately with `ImportError`.

**Correct pattern** (from `services/unpublish_handlers.py:530-558`):
```python
from infrastructure.postgresql import PostgreSQLRepository
from psycopg import sql
repo = PostgreSQLRepository()
with repo._get_connection() as conn:
    with conn.cursor() as cur:
        drop_query = sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
            sql.Identifier(schema), sql.Identifier(table)
        )
        cur.execute(drop_query)
    conn.commit()
```

**Replace** `_drop_table()` (lines 334-347):

```python
def _drop_table(self, table_fqn: str) -> None:
    """Drop a PostGIS table using safe parameterized identifiers."""
    from infrastructure.postgresql import PostgreSQLRepository
    from psycopg import sql

    # Parse schema.table
    if '.' in table_fqn:
        schema, table = table_fqn.split('.', 1)
    else:
        schema, table = 'geo', table_fqn

    repo = PostgreSQLRepository()
    with repo._get_connection() as conn:
        with conn.cursor() as cur:
            drop_query = sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                sql.Identifier(schema),
                sql.Identifier(table)
            )
            cur.execute(drop_query)
        conn.commit()
```

---

## Fix D: Wire `asset_id` into New Job

**Problem**: `_resubmit_job()` creates `JobRecord` without `asset_id`. The original submit flow puts `asset_id` in `job_params` (submit.py:467), so `job.parameters['asset_id']` has it. But the new `JobRecord` constructor doesn't set the `asset_id` field.

**Change**: Accept `asset_id` parameter in `_resubmit_job()` and pass it to `JobRecord`.

### In `_resubmit_job()` signature (line 384):

```python
# BEFORE:
def _resubmit_job(self, job_type: str, parameters: Dict[str, Any]) -> str:

# AFTER:
def _resubmit_job(self, job_type: str, parameters: Dict[str, Any], asset_id: str = None) -> str:
```

### In `JobRecord` constructor (line 422):

```python
# BEFORE:
job_record = JobRecord(
    job_id=job_id,
    job_type=job_type,
    status=JobStatus.QUEUED,
    stage=1,
    total_stages=len(job_class.stages),
    parameters=validated_params,
    metadata={
        'resubmitted': True,
        'resubmit_timestamp': str(uuid.uuid4())[:8]
    }
)

# AFTER:
job_record = JobRecord(
    job_id=job_id,
    job_type=job_type,
    status=JobStatus.QUEUED,
    stage=1,
    total_stages=len(job_class.stages),
    parameters=validated_params,
    asset_id=asset_id,
    metadata={
        'resubmitted': True,
        'resubmit_timestamp': str(uuid.uuid4())[:8]
    }
)
```

### Update callers to pass `asset_id`:

**`triggers/jobs/resubmit.py` line 158** (JobResubmitHandler.handle):
```python
# BEFORE:
new_job_id = self._resubmit_job(job_type, parameters)

# AFTER:
new_job_id = self._resubmit_job(job_type, parameters, asset_id=job.asset_id)
```

**`triggers/platform/resubmit.py` line 179** (PlatformResubmitHandler.handle):
```python
# BEFORE:
new_job_id = resubmit_handler._resubmit_job(job_type, parameters)

# AFTER:
new_job_id = resubmit_handler._resubmit_job(job_type, parameters, asset_id=job.asset_id)
```

---

## Fix B: Look Up `table_name` from `result_data`

**Problem**: `_plan_cleanup()` only checks `parameters.get('table_name')` for vector jobs. But `table_name` is typically in `job.result_data['table_name']` (set by `vector_docker_etl.finalize_job()` line 453). The raster path already checks `result_data` for COG paths (line 253) — this is an asymmetry.

**Replace** lines 226-231:

```python
# BEFORE:
if 'vector' in job_type.lower():
    # Vector job - check for table_name
    table_name = parameters.get('table_name')
    schema = parameters.get('schema', 'geo')
    if table_name:
        plan["tables_to_drop"].append(f"{schema}.{table_name}")

# AFTER:
if 'vector' in job_type.lower():
    # Vector job - check parameters then result_data for table_name
    table_name = parameters.get('table_name')
    schema = parameters.get('schema', 'geo')
    if not table_name and job.result_data:
        table_name = job.result_data.get('table_name')
        schema = job.result_data.get('schema', schema)
    if table_name:
        plan["tables_to_drop"].append(f"{schema}.{table_name}")
```

---

## Fix E: Add Timestamp to Job ID Hash

**Problem**: `job_id = SHA256(job_type:params)` is deterministic. If old job delete fails (non-fatal error in `_execute_cleanup`), the INSERT does nothing because the old row with the same PK still exists.

**Fix**: Include a resubmit timestamp in the hash to guarantee uniqueness.

**Replace** lines 416-419:

```python
# BEFORE:
clean_params = {k: v for k, v in validated_params.items() if not k.startswith('_')}
canonical = f"{job_type}:{json.dumps(clean_params, sort_keys=True)}"
job_id = hashlib.sha256(canonical.encode()).hexdigest()

# AFTER:
import time
clean_params = {k: v for k, v in validated_params.items() if not k.startswith('_')}
resubmit_ts = str(time.time())
canonical = f"{job_type}:{json.dumps(clean_params, sort_keys=True)}:resubmit:{resubmit_ts}"
job_id = hashlib.sha256(canonical.encode()).hexdigest()
```

This guarantees each resubmit gets a unique `job_id` regardless of whether the old job was successfully deleted.

---

## Fix A: Update STAC Cleanup Comment (Cosmetic)

**Problem**: Lines 233-249 look for `stac_item_id` in parameters to plan STAC item deletion. In B2C architecture, pgSTAC items only exist for approved assets. The cleanup will always find nothing for unapproved assets, which is correct behavior — but the code is misleading.

**Add comment** before line 233:

```python
# NOTE (20 FEB 2026): In B2C architecture, pgSTAC items only exist for
# approved assets. For rejected/draft assets, this will find nothing to
# delete — which is correct. For revoked assets, the revocation flow
# already deleted the pgSTAC item via _delete_stac().
```

No logic change needed.

---

## Files Modified

| File | Changes |
|------|---------|
| `triggers/jobs/resubmit.py` | Fix C (drop_table), Fix D (asset_id param + caller), Fix B (result_data lookup), Fix E (unique hash), Fix A (comment) |
| `triggers/platform/resubmit.py` | Fix D (pass asset_id to _resubmit_job caller) |

---

## Verification

After deploying, test on the current rejected asset:

```bash
# 1. Dry run — should show correct cleanup plan with no errors
POST /api/platform/resubmit
{"request_id": "06d4184cb4c47ac89dc86833fd41065a", "dry_run": true}

# 2. Execute resubmit
POST /api/platform/resubmit
{"request_id": "06d4184cb4c47ac89dc86833fd41065a"}

# Expected: new_job_id returned, asset updated, processing restarts
# Verify: new job has asset_id set (check via /api/dbadmin/jobs/{new_job_id})
```
