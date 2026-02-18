# Pydantic V2 Serialization Review & Implementation Plan

**Created**: 18 FEB 2026
**Revised**: 18 FEB 2026 (v3 — Phase 1 implemented, enum compatibility verified)
**Status**: Phase 1 COMPLETE, Phase 2 ready
**SAFe Type**: Enabler (Technical Foundation)
**Epic**: Data Access Simplification / Code Quality

---

## Why JSONB Columns Exist (and their tradeoff)

PostgreSQL JSONB stores the **JSON type system**, not the Python type system. Primitives
(`str`, `int`, `float`, `bool`, `None`, `dict`, `list`) survive the round-trip perfectly.
Richer Python types (`datetime`, `Enum`, `UUID`) are flattened to strings on the way in
and come back as strings — the original type information is lost inside the JSONB blob.

**This is the tradeoff**: JSONB gives schema-free flexible storage with powerful query
operators (`@>`, `->`, `->>`, `?`) and GIN indexing, but at the cost of type fidelity
for non-JSON-native types.

**The design rule**: If you know the schema ahead of time and the values have meaningful
types (enums, dates, UUIDs), use **proper database columns** — PostgreSQL preserves their
types exactly, and psycopg3 round-trips them as native Python objects. JSONB is for
genuinely flexible data — varying keys, nested structures, platform-specific fields —
where a fixed schema would be impractical.

In this codebase, the JSONB columns (`platform_refs`, `parameters`, `metadata`,
`stage_results`, `source_config`, etc.) are all variable-shape data that differs by
job type, platform, or context. The structured attributes (`approval_state`,
`processing_status`, `created_at`, etc.) are proper typed columns.

---

## Problem Statement

All domain models are Pydantic V2 `BaseModel` subclasses, but **none of the repository
write paths use Pydantic serialization**. Instead, every repository manually calls
`json.dumps()` for JSONB columns and `.value` for enums — scattered across 40+ call sites
in 15 independent repositories. This caused a production bug on 18 FEB 2026 when a new
write path (`assign_version`) forgot `json.dumps()` on `platform_refs`.

### Root Cause

psycopg3 (unlike psycopg2) does **not** auto-adapt Python `dict` → PostgreSQL `jsonb`.
When a dict is passed to a `%s` SQL parameter, psycopg3 raises:
`cannot adapt type 'dict' using placeholder '%s'`

The codebase worked around this by calling `json.dumps()` in every repository write
method — 40+ manual call sites. This is error-prone and the wrong abstraction layer.

### The Right Fix

psycopg3 has a **type adapter registry** that can be configured once at the connection
level. Register `dict → Jsonb` adaptation and psycopg3 handles serialization
automatically. No application code changes needed — dicts pass straight through.

---

## Architecture: Before → After

```
BEFORE (broken):
  Pydantic Models → model_dump() → native Python dicts/enums
      ↓
  15 Repositories → each manually calls json.dumps() + .value (40+ sites)
      ↓
  psycopg3 → receives strings → PostgreSQL

AFTER (Phase 1 complete):
  Pydantic Models → model_dump() → native Python dicts/enums
      ↓
  15 Repositories → can pass raw dicts/enums (existing json.dumps/.value still harmless)
      ↓
  psycopg3 → type adapters auto-serialize dict→JSONB, Enum→.value → PostgreSQL
```

---

## Phase 1: Register psycopg3 Type Adapters ✅ COMPLETE

**Implemented**: 18 FEB 2026 (not yet committed/deployed)

### What was done

Registered three type adapters at connection creation time:

| Adapter | Type | Target | Effect |
|---------|------|--------|--------|
| `JsonbBinaryDumper` | `dict` | JSONB | Auto-serializes Python dicts |
| `JsonbBinaryDumper` | `list` | JSONB | Auto-serializes Python lists |
| `_EnumDumper` | `Enum` | TEXT | Extracts `.value` from any Enum subclass |

### Files modified

**`infrastructure/postgresql.py`** (lines 95-125):
- Added `_EnumDumper(Dumper)` class — converts `Enum.value` → `bytes`
- Added `_register_type_adapters(conn)` — registers all three adapters on a connection
- Called `_register_type_adapters(conn)` in `_get_single_use_connection()` (line 696)

**`infrastructure/connection_pool.py`** (lines 237-240):
- Called `_register_type_adapters(conn)` in `_configure_connection()`
- Imports from `infrastructure.postgresql` to share the same function

### Enum subclass inheritance — VERIFIED

psycopg3's `AdaptersMap` resolves Enum subclasses correctly when the dumper is
registered on the base `Enum` class:

```
Tested: register_dumper(Enum, _EnumDumper)
  → ApprovalState.APPROVED → b'approved'       ✅ (PyFormat.AUTO)
  → ApprovalState.APPROVED → b'approved'       ✅ (PyFormat.TEXT)
  → ApprovalState.APPROVED → ProgrammingError  ❌ (PyFormat.BINARY — not used)
```

All SQL in this codebase uses `%s` which maps to `PyFormat.AUTO` → subclass
resolution works. No per-enum registration needed.

### Backward compatibility — SAFE

Existing code manually calls `.value` before passing to SQL, producing a **string**.
The `_EnumDumper` only fires when psycopg3 receives an **Enum object**. So:

- `status.value` → string → psycopg3 uses StringDumper → **no change**
- `status` (raw Enum) → psycopg3 uses `_EnumDumper` → extracts `.value` → **new behavior, correct**

**Both paths produce identical SQL.** Existing `.value` calls are redundant but harmless.
This is the same backward-compatibility model as the `json.dumps()` / dict adapter.

---

## Phase 2: Revert Bandaid Fix — READY

**File**: `infrastructure/asset_repository.py`

The bandaid fix from commit `dafc46f` (18 FEB 2026) added isinstance dict/list
checking in `update()`. With adapters registered, this is now redundant.

### Changes to make

**Revert lines 591-608** (enum pre-conversion + isinstance dict/list check):

```python
# REMOVE (lines 591-597) — adapter handles enum conversion:
        if 'approval_state' in updates and isinstance(updates['approval_state'], ApprovalState):
            updates['approval_state'] = updates['approval_state'].value
        if 'clearance_state' in updates and isinstance(updates['clearance_state'], ClearanceState):
            updates['clearance_state'] = updates['clearance_state'].value
        if 'processing_status' in updates and isinstance(updates['processing_status'], ProcessingStatus):
            updates['processing_status'] = updates['processing_status'].value

# REVERT (lines 604-608) — adapter handles dict/list conversion:
        # FROM:
            if isinstance(value, dict) or isinstance(value, list):
                values.append(json.dumps(value))
            else:
                values.append(value)
        # TO:
            values.append(value)
```

**Acceptance criteria:**
- `update()` has zero type-checking logic for enums or dicts
- `assign_version` → update with `platform_refs` dict works
- `approve` → update with enum values works
- Test via existing approval + submit flows

---

## Phase 3: Remove Manual Serialization Across All Repositories

**Goal**: Remove all manual `json.dumps()` and `.value` calls. With adapters registered,
these are redundant — they convert to types psycopg3 can already handle natively.

**Approach**: One repo at a time, deploy and test after each.

### Enum `.value` Inventory (28 sites across 7 files)

**IMPORTANT**: Each `.value` removal must be verified individually. Some `.value` calls
are for **logging/display** (keep those), not SQL parameters. Only remove `.value` calls
that appear in SQL parameter tuples.

| File | Line | Pattern | Context | Action |
|------|------|---------|---------|--------|
| **asset_repository.py** | 213 | `asset.approval_state.value if isinstance(...)` | INSERT param | Remove — adapter handles |
| **asset_repository.py** | 215 | `asset.clearance_state.value if isinstance(...)` | INSERT param | Remove — adapter handles |
| **asset_repository.py** | 428 | `state.value` | WHERE param | Remove — adapter handles |
| **asset_repository.py** | 593 | `updates['approval_state'].value` | UPDATE pre-conv | Remove in Phase 2 |
| **asset_repository.py** | 595 | `updates['clearance_state'].value` | UPDATE pre-conv | Remove in Phase 2 |
| **asset_repository.py** | 597 | `updates['processing_status'].value` | UPDATE pre-conv | Remove in Phase 2 |
| **asset_repository.py** | 718 | `old_clearance.value`, `clearance_level.value` | **Logger string** | **KEEP** — display only |
| **asset_repository.py** | 720 | `clearance_level.value` | **Logger string** | **KEEP** — display only |
| **asset_repository.py** | 890 | `ProcessingStatus.PROCESSING.value` | WHERE param | Remove — adapter handles |
| **asset_repository.py** | 1047 | `status.value` | WHERE param | Remove — adapter handles |
| **asset_repository.py** | 1075 | `ProcessingStatus.PROCESSING.value` | WHERE param | Remove — adapter handles |
| **asset_repository.py** | 1708 | `approval_state.value` | UPDATE param | Remove — adapter handles |
| **asset_repository.py** | 1723 | `clearance_state.value` | UPDATE param | Remove — adapter handles |
| **asset_repository.py** | 1759 | `approval_state.value` | **Logger string** | **KEEP** — display only |
| **asset_repository.py** | 1801 | `ApprovalState.REVOKED.value` | WHERE param | Remove — adapter handles |
| **asset_repository.py** | 1806 | `ApprovalState.APPROVED.value` | WHERE param | Remove — adapter handles |
| **asset_repository.py** | 1870 | `state.value` | **Dict key** | **KEEP** — building result dict |
| **postgresql.py** | 1544 | `job.status.value` | INSERT param | Remove — adapter handles |
| **postgresql.py** | 1717 | `status_filter.value` | WHERE param | Remove — adapter handles |
| **postgresql.py** | 1848 | `task.status.value` | INSERT param | Remove — adapter handles |
| **postgresql.py** | 2056 | `s.value for s in TaskStatus` | **Error message** | **KEEP** — display only |
| **jobs_tasks.py** | 349 | `current_job.status.value` | **String comparison** | **KEEP** — comparing to 'failed' |
| **jobs_tasks.py** | 473 | `status.value` | WHERE param | Remove — adapter handles |
| **jobs_tasks.py** | 552 | `status.value` | WHERE param | Remove — adapter handles |
| **jobs_tasks.py** | 941 | `initial_status.value` | INSERT param | Remove — adapter handles |
| **job_event_repository.py** | 113 | `event.event_type.value if isinstance(...)` | INSERT param | Remove — adapter handles |
| **job_event_repository.py** | 114 | `event.event_status.value if isinstance(...)` | INSERT param | Remove — adapter handles |
| **job_event_repository.py** | 254 | `et.value if isinstance(...)` | WHERE param (IN list) | Remove — adapter handles |
| **job_event_repository.py** | 459 | `event.event_type.value` | **Dict building** | **KEEP** — building response dict |
| **job_event_repository.py** | 461 | `event.event_status.value` | **Dict building** | **KEEP** — building response dict |
| **job_event_repository.py** | 568 | `event_type.value` | Pre-conversion for query | Remove — adapter handles |
| **job_event_repository.py** | 575 | `event.event_type.value` | Pre-conversion for query | Remove — adapter handles |
| **revision_repository.py** | 101 | `revision.approval_state_at_supersession.value` | INSERT param | Remove — adapter handles |
| **revision_repository.py** | 102 | `revision.clearance_state_at_supersession.value` | INSERT param | Remove — adapter handles |
| **artifact_repository.py** | 118 | `artifact.status.value if isinstance(...)` | INSERT param | Remove — adapter handles |
| **artifact_repository.py** | 314 | `status.value if isinstance(...)` | WHERE param | Remove — adapter handles |
| **artifact_repository.py** | 326 | `status.value if isinstance(...)` | WHERE param | Remove — adapter handles |
| **external_service_repository.py** | 111 | `service.service_type.value` | INSERT param | Remove — adapter handles |
| **external_service_repository.py** | 116 | `service.status.value` | INSERT param | Remove — adapter handles |
| **external_service_repository.py** | 193 | `status.value` | WHERE param | Remove — adapter handles |
| **external_service_repository.py** | 197 | `service_type.value` | WHERE param | Remove — adapter handles |
| **external_service_repository.py** | 260 | `value.value` | UPDATE param | Remove — adapter handles |
| **external_service_repository.py** | 262 | `value.value` | UPDATE param | Remove — adapter handles |
| **promoted_repository.py** | 119 | `dataset.classification.value` | INSERT param | Remove — adapter handles |

**Summary**: ~35 SQL param sites to clean up, ~8 display/logging sites to KEEP.

### `json.dumps()` Inventory (existing from prior analysis)

| Priority | Repository | json.dumps sites | Notes |
|----------|-----------|-----------------|-------|
| 1 | GeospatialAssetRepository | 7 | Where bug occurred |
| 2 | PostgreSQLJobRepository (postgresql.py) | 4 | Core pipeline — `parameters`, `stage_results`, `metadata`, `result_data` |
| 3 | PostgreSQLTaskRepository (postgresql.py) | 2 | Core pipeline — `parameters`, `metadata` |
| 4 | jobs_tasks.py | 3 | `existing_metadata`, `task.parameters`, `task.metadata` |
| 5 | ArtifactRepository | 6 | |
| 6 | ExternalServiceRepository | 4 | |
| 7 | PlatformRegistryRepository | 3 | |
| 8 | H3Repository | 4 | |
| 9 | Remaining | ~5 total | JobEvent, Metrics, Promoted |

### Per-repo migration checklist

For each repository:
1. Identify all `json.dumps()` calls in SQL parameter positions → replace with raw value
2. Identify all `.value` calls in SQL parameter positions → replace with raw enum
3. Identify all `isinstance(x, SomeEnum)` ternaries → replace with raw value
4. **DO NOT** remove `.value` in logging, error messages, dict building, or string comparisons
5. Deploy and test write paths

### Recommended migration order

| Order | Repository | Why |
|-------|-----------|-----|
| 1 | `asset_repository.py` | Highest site count (7 json.dumps + 12 enum), where bug occurred |
| 2 | `postgresql.py` (Job + Task repos) | Core pipeline, 4 json.dumps + 2 enum |
| 3 | `jobs_tasks.py` | Core pipeline, 3 json.dumps + 2 enum |
| 4 | `job_event_repository.py` | 5 enum sites, 1 json.dumps |
| 5 | `artifact_repository.py` | 6 json.dumps + 3 enum |
| 6 | `external_service_repository.py` | 4 json.dumps + 6 enum |
| 7 | `revision_repository.py` | 2 enum sites only |
| 8 | `promoted_repository.py` | 1 enum + 2 Jsonb() calls |
| 9 | Remaining (h3, platform_registry, metrics) | Low-frequency write paths |

---

## Phase 4: Cleanup Models + Documentation

#### T4.1: Delete dead `to_dict()` methods

- `core/models/asset.py` — `GeospatialAsset.to_dict()`
- `core/models/asset.py` — `AssetRevision.to_dict()`
- Any other models with hand-written to_dict()

#### T4.2: Remove deprecated `json_encoders` from model_config

```python
# DELETE from core/models/asset.py:
json_encoders={datetime: lambda v: v.isoformat() if v else None}
```

#### T4.3: Verify `_parse_jsonb_column()` still needed for reads

psycopg3 with `row_factory=dict_row` auto-parses JSONB on read → dicts come
back as Python dicts. If so, `_parse_jsonb_column()` (postgresql.py line 128) is
dead code. Verify and remove if confirmed.

#### T4.4: Update DEV_BEST_PRACTICES.md

```markdown
## DB Write Serialization (18 FEB 2026)

psycopg3 type adapters are registered on every connection (both single-use
and pooled). dict/list auto-adapt to JSONB, Enum auto-adapts to .value.

**NEVER** call json.dumps() or .value manually in repository code for SQL params.
**NEVER** use psycopg.types.json.Jsonb() wrapper.

- INSERT: `model.model_dump()` → pass values directly to SQL
- UPDATE partial: pass raw Python values → psycopg3 handles serialization
- The adapters are registered in:
  - postgresql.py → _register_type_adapters() → called from _get_single_use_connection()
  - connection_pool.py → _configure_connection() → imports and calls same function
```

---

## Implementation Status

### Phase 1 — ✅ COMPLETE (local, not yet committed)

| File | Change | Status |
|------|--------|--------|
| `infrastructure/postgresql.py` | `_EnumDumper` class + `_register_type_adapters()` function + call in `_get_single_use_connection()` | ✅ Done |
| `infrastructure/connection_pool.py` | Call `_register_type_adapters()` in `_configure_connection()` | ✅ Done |

### Phase 2 — READY (blocked on Phase 1 deploy + verify)

| File | Change | Status |
|------|--------|--------|
| `infrastructure/asset_repository.py` | Revert bandaid (lines 591-608) | Pending |

### Phase 3 — NOT STARTED

~40 json.dumps + ~35 enum .value SQL param sites across 9 files.

### Phase 4 — NOT STARTED

Dead code cleanup + documentation.

### Previously committed (keep as-is)

| Commit | File | What was done | Status |
|--------|------|---------------|--------|
| `b428e1b` | `services/asset_service.py` | Fixed draft self-conflict: `is None` → `not version_id` | **Keep** — correct logic fix |
| `b428e1b` | `services/platform_validation.py` | Fixed `'unknown'` → `'draft'` in error message | **Keep** — correct display fix |

### Previously committed (revert after Phase 1 deploy)

| Commit | File | What was done | Status |
|--------|------|---------------|--------|
| `dafc46f` | `infrastructure/asset_repository.py` | Bandaid isinstance dict/list → json.dumps() in `update()` | **Revert** in Phase 2 |

### Previously attempted (discarded)

| Change | What was done | Status |
|--------|---------------|--------|
| `@field_serializer` on models | Added to asset.py, job.py, task.py, artifact.py | **Discarded** — wrong layer, causes double-encoding in API responses |
| `_prepare_value()` on PostgreSQLRepository | Added to postgresql.py | **Discarded** — adapter handles this at driver level |

---

## Decision Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| psycopg3 adapter vs `@field_serializer` | **Adapter** | Serialization belongs at driver layer, not model layer. `@field_serializer` would double-encode dicts in API responses. |
| Register on connection vs globally | **Per-connection** | Safer — no global state. Registered in `_get_single_use_connection()` and `_configure_connection()`. |
| Enum: base class registration vs per-enum | **Base class** | Verified: psycopg3 resolves subclasses (ApprovalState, JobStatus, etc.) when registered on `Enum`. Works for PyFormat.AUTO and TEXT. |
| Phase json.dumps removal | **Incremental** | Existing json.dumps calls are harmless (string → JSONB still works). Remove per-repo to limit blast radius. |
| Phase .value removal | **Incremental, careful** | Some `.value` calls are for logging/display (KEEP), some are SQL params (REMOVE). Must inspect each site individually. |
| `_prepare_value()` fallback | **Not needed** | Adapter handles all cases at driver level. No edge cases identified that bypass the adapter. |
| Keep models clean | **Yes** | No `@field_serializer` for DB concerns. `model_dump()` returns native Python types. Repos pass them through. |

---

## Repository Landscape

15 independent repos, all flat inheritors of PostgreSQLRepository:

| Repository | JSONB Cols | Enum .value (SQL) | Enum .value (display) | json.dumps Sites |
|------------|-----------|-------------------|----------------------|-----------------|
| **GeospatialAssetRepository** | `platform_refs`, `node_summary` | 10 | 3 | 7 |
| **PostgreSQLJobRepository** | `parameters`, `metadata`, `stage_results`, `error_details` | 2 | 0 | 4 |
| **PostgreSQLTaskRepository** | `parameters`, `result`, `error_context` | 1 | 1 | 2 |
| **jobs_tasks.py** | (shared) | 2 | 1 | 3 |
| **ArtifactRepository** | `client_refs`, `metadata` | 3 | 0 | 6 |
| **ExternalServiceRepository** | `tags`, `detected_capabilities`, `health_history`, `metadata` | 6 | 0 | 4 |
| **JobEventRepository** | `event_data` | 5 | 2 | 1 |
| **RevisionRepository** | none | 2 | 0 | 0 |
| **PromotedDatasetRepository** | `tags`, `viewer_config` | 1 | 0 | 2 (Jsonb()) |
| **PlatformRegistryRepository** | `required_refs`, `optional_refs` | 0 | 0 | 3 |
| **H3Repository** | `source_config` | 0 | 0 | 4 |
| **MetricsRepository** | `payload` | 0 | 0 | 1 |
| **ApiRequestRepository** | none | 0 | 0 | 0 |
| **H3BatchTracker** | none | 0 | 0 | 0 |
| **JanitorRepository** | read-only | 0 | 0 | 0 |

**Totals**: ~35 enum SQL param sites, ~7 enum display sites (KEEP), ~40 json.dumps sites.

---

## Next Steps (recommended order)

1. **Commit + deploy Phase 1** — adapter registration (postgresql.py + connection_pool.py)
2. **Test existing flows** — submit, approve, job creation should all still work
   (existing `.value` / `json.dumps()` produce strings, adapters don't interfere)
3. **Phase 2** — revert bandaid in asset_repository.py, test approval flow
4. **Phase 3** — incremental removal, one repo at a time, starting with asset_repository.py
5. **Phase 4** — dead code cleanup, documentation
