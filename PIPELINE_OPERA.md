# PIPELINE_OPERA.md - Pipeline Operations & Resilience Architecture

**Created**: 05 JAN 2026
**Status**: ACTIVE DEVELOPMENT
**Full Technical Spec**: `docs_claude/PIPELINE_OPERATIONS.md`

---

## Context for Future Claude Sessions

This document captures the architectural decisions and implementation progress for making long-running ETL pipelines resilient. The work was triggered by the FATHOM ETL scaling from Rwanda (234 COGs) to Côte d'Ivoire (1924 COGs).

---

## The Problem We Discovered

### Timeline: 05 JAN 2026

1. **Rwanda processing worked fine**: 234 stacked COGs → 78 merged COGs
2. **CIV processing failed silently**: 1924 stacked COGs created, but STAC registration task stuck in `pending` forever
3. **Root cause**: Service Bus has 256KB message limit. The fan-in task for Stage 3 had 1.09MB of results embedded in parameters

### The Architectural Issue

```
CoreMachine._create_fan_in_task() at core/machine.py:2230

task = {
    "parameters": {
        "previous_results": previous_results,  # ← ALL 1924 results here = 1.09MB
    }
}
```

When CoreMachine creates a fan-in task, it embeds ALL previous stage results directly in the task parameters. For small result sets this works. For 1924 results, it exceeds the 256KB Service Bus limit.

---

## Solutions Implemented (Partial)

### Fix 1: ETL Tracking on Skip (COMPLETE)

**Problem**: When Phase 1 tasks skip (COGs already exist), they weren't updating `phase1_completed_at` in the ETL tracking table. Phase 2 couldn't find any "Phase 1 complete" records.

**Fix**: Call `_update_phase1_processed()` and `_update_phase2_processed()` even when tasks skip.

**Files**: `services/fathom_etl.py` lines 481-483, 973-975

### Fix 2: Database Reference Pattern for FATHOM Jobs (COMPLETE)

**Problem**: FATHOM STAC registration task params contained all COG results.

**Fix**: Pass `job_id` + `stage` instead of results. Handler queries database directly.

**Files**:
- `jobs/process_fathom_stack.py` - Pass reference instead of cog_results
- `jobs/process_fathom_merge.py` - Same
- `services/fathom_etl.py` - Handler queries DB when `job_id` in params

### Fix 3: Universal Fan-In Reference Pattern (NOT YET IMPLEMENTED)

**Decision**: Make database reference the DEFAULT for ALL fan-in stages in CoreMachine, not just FATHOM.

**Rationale**: Robert asked "is there a reason not to make this how we do all fan-in?" Answer: No. The downsides (extra DB query, ~5-20ms) are negligible compared to the benefits.

---

## CoreMachine Fan-In Architecture

### Current Implementation (core/machine.py)

```python
# Line 2162-2245
def _create_fan_in_task(self, job_id, stage, previous_results, stage_definition, job_parameters):
    """Current: Embeds ALL previous_results in task params."""

    task = {
        "task_id": task_id,
        "task_type": task_type,
        "parameters": {
            "previous_results": previous_results,  # ← PROBLEM: Can be huge
            "job_parameters": job_parameters,
        }
    }
    return [task]
```

### Proposed Implementation (TO BE DONE)

```python
def _create_fan_in_task(self, job_id, stage, previous_results, stage_definition, job_parameters):
    """
    Create fan-in task using database reference pattern.

    PATTERN (05 JAN 2026): Fan-in tasks NEVER embed previous_results.
    Instead, they receive a reference to query the database directly.
    This avoids Service Bus 256KB message limit for any result count.
    """

    task = {
        "task_id": task_id,
        "task_type": task_type,
        "parameters": {
            "fan_in_source": {
                "job_id": job_id,
                "source_stage": stage - 1,
                "expected_count": len(previous_results)
            },
            "job_parameters": job_parameters,
            "aggregation_metadata": {
                "stage": stage,
                "pattern": "fan_in_reference"
            }
        }
    }
    return [task]
```

### Handler Pattern (Universal)

All fan-in handlers should use this pattern:

```python
from repositories.job_repository import JobRepository

def load_fan_in_results(params: dict) -> list[dict]:
    """Universal helper to load fan-in results from DB reference."""
    source = params["fan_in_source"]
    job_repo = JobRepository()
    tasks = job_repo.get_tasks_for_job(source["job_id"])

    results = [
        t.result_data.get("result", t.result_data)
        for t in tasks
        if t.stage == source["source_stage"]
        and t.status.value == "completed"
        and t.result_data
    ]

    return results

# Usage in any fan-in handler:
def my_aggregation_handler(params, context):
    results = load_fan_in_results(params)
    # ... process results
```

---

## Data Flow Comparison

### Before (Embedding Pattern)

```
Stage 2 completes (1924 tasks)
    ↓
CoreMachine fetches all 1924 results from DB
    ↓
CoreMachine creates task with params = {previous_results: [1924 items]} (1.09MB)
    ↓
Service Bus REJECTS (>256KB)
    ↓
Task stuck in pending forever
```

### After (Reference Pattern)

```
Stage 2 completes (1924 tasks)
    ↓
CoreMachine counts results (1924)
    ↓
CoreMachine creates task with params = {fan_in_source: {job_id, stage}} (~200 bytes)
    ↓
Service Bus ACCEPTS
    ↓
Handler executes, queries DB directly for 1924 results
    ↓
SUCCESS
```

---

## Current State of CIV Job

**Job ID**: `038ffc2d537986c903ce8d4c5cec106b26a515d4e0398c9b22b1438c0e78e594`

**Status**: Stuck at Stage 3 (STAC registration)

**Problem**: The Stage 3 task was created with OLD params format (embedded results) before we deployed the fix.

**Recovery Options**:

### Option A: Update task params directly (SQL)
```sql
UPDATE app.tasks
SET parameters = jsonb_build_object(
    'job_id', '038ffc2d537986c903ce8d4c5cec106b26a515d4e0398c9b22b1438c0e78e594',
    'stage', 2,
    'cog_count', 1924,
    'region_code', 'CIV',
    'collection_id', 'fathom-flood-stacked',
    'output_container', 'silver-fathom'
),
status = 'pending',
error_details = NULL
WHERE task_id = '8d471f99635793f6';
```

### Option B: Delete task and reset job stage
```sql
-- Delete stuck task
DELETE FROM app.tasks WHERE task_id = '8d471f99635793f6';

-- Reset job to end of Stage 2 so CoreMachine recreates Stage 3 task
UPDATE app.jobs
SET stage = 2, status = 'processing'
WHERE job_id = '038ffc2d537986c903ce8d4c5cec106b26a515d4e0398c9b22b1438c0e78e594';

-- CoreMachine will detect Stage 2 complete and create new Stage 3 task with new code
```

---

## Implementation TODO

### Immediate (Before CIV Can Complete)

- [ ] Implement universal fan-in reference pattern in `core/machine.py`
- [ ] Add `load_fan_in_results()` helper function
- [ ] Update existing fan-in handlers to use helper
- [ ] Recover CIV job using Option B

### Short-term

- [ ] Add size check to janitor to detect oversized pending tasks
- [ ] Add retry budget to tasks (max_retries column)
- [ ] Add job timeout (timeout_minutes column)

### Medium-term

- [ ] Implement resumable jobs (Pattern 4)
- [ ] Implement graceful degradation (Pattern 5)

---

## Files Reference

| File | Purpose |
|------|---------|
| `core/machine.py` | CoreMachine orchestration - `_create_fan_in_task()` at line 2162 |
| `services/fathom_etl.py` | FATHOM handlers - already has DB reference pattern |
| `jobs/process_fathom_stack.py` | Phase 1 job - already uses DB reference |
| `jobs/process_fathom_merge.py` | Phase 2 job - already uses DB reference |
| `docs_claude/PIPELINE_OPERATIONS.md` | Full technical spec with 5 resilience patterns |

---

## Key Insight from This Session

**Question** (Robert): "This sounds like it should be the pattern for all fan-in stages?? is there a reason not to make this how we do all fan-in?"

**Answer**: No reason not to. The "downsides" of always using DB reference are trivial:
- Extra DB query: ~5-20ms (negligible)
- Handler complexity: Actually SIMPLER (one pattern, not two)

**Decision**: Universal database reference pattern for ALL fan-in stages. No conditional logic, no size thresholds, no edge cases.

---

## Commit History

```
9be5df9 FATHOM ETL: Fix 256KB Service Bus limit + ETL tracking on skip
```

This commit includes:
- ETL tracking fix for skipped tasks
- Database reference pattern for FATHOM jobs (job-level, not CoreMachine-level)
- PIPELINE_OPERATIONS.md documentation

Next commit will be:
- Universal fan-in reference pattern in CoreMachine
- Helper function for loading fan-in results
- CIV job recovery
