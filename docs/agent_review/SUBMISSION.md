# Adversarial Analysis: Platform Submit Workflow

**Date**: 26 FEB 2026
**Pipeline**: Omega → Alpha + Beta (parallel) → Gamma → Delta
**Target**: `/api/platform/submit` endpoint and all supporting services
**Files Reviewed**: 12 files, ~6,700 LOC

---

## Scope

| # | File | LOC | Role |
|---|------|-----|------|
| 1 | `triggers/platform/submit.py` | 436 | HTTP endpoint entry point |
| 2 | `services/platform_job_submit.py` | 245 | Job creation + Service Bus submission |
| 3 | `services/platform_translation.py` | 568 | Anti-Corruption Layer (DDH → CoreMachine) |
| 4 | `services/platform_validation.py` | 312 | Version lineage validation |
| 5 | `services/asset_service.py` | 584 | Asset/Release lifecycle orchestration |
| 6 | `services/platform_response.py` | 248 | HTTP response builders |
| 7 | `infrastructure/asset_repository.py` | 447 | Asset persistence + advisory locks |
| 8 | `infrastructure/release_repository.py` | 1,408 | Release state machine persistence |
| 9 | `infrastructure/release_table_repository.py` | 277 | Release-to-table junction |
| 10 | `core/models/platform.py` | 634 | PlatformRequest DTO + validation |
| 11 | `core/models/asset.py` | 716 | Asset/Release domain models + enums |
| 12 | `core/models/release_table.py` | 82 | ReleaseTable model |

---

## Delta: Final Actionable Report

### EXECUTIVE SUMMARY

The platform submit workflow (`/api/platform/submit`) has one crash-level bug that blocks every submission (BUG-1: `config` NameError), making the endpoint non-functional in its current state on master. Beyond this showstopper, the overwrite path has two correctness bugs: it does not reset `approval_state` from REJECTED back to PENDING_REVIEW, and it does not clear the stale `job_id`, both of which will cause incorrect lifecycle behavior once the crash is fixed. The security posture has one medium-severity issue: raw exception strings (including DB connection details and internal paths) are returned to HTTP callers via the catch-all handler. The underlying architecture -- Asset/Release entity split, advisory locking on assets, deterministic IDs, orphan detection -- is sound and well-organized for a pre-production system.

---

### TOP FIXES

#### FIX 1: `config` NameError crashes every submit (CRITICAL)

**What**: Line 168 passes a bare `config` variable to `translate_to_coremachine()`, but `config` is never defined in this module. The import on line 46 is `from config import get_config, generate_platform_request_id` -- there is no `config` local variable.

**Why**: Every single platform submit request hits an unhandled `NameError` at line 168 and falls through to the catch-all on line 422-424, returning a 500 error. The endpoint is completely non-functional.

**Where**: `triggers/platform/submit.py`, function `platform_request_submit`, line 168.

**How**: Remove the argument entirely since `translate_to_coremachine` already has a `cfg=None` default that internally calls `get_config()`:

```python
# Line 168 - BEFORE:
job_type, job_params = translate_to_coremachine(platform_req, config)

# Line 168 - AFTER:
job_type, job_params = translate_to_coremachine(platform_req)
```

**Effort**: S (one-line change)
**Risk of fix**: None -- `translate_to_coremachine` already handles `cfg=None` by calling `get_config()` internally.
**Confidence**: CONFIRMED (both Alpha and Beta independently found this)

---

#### FIX 2: `update_overwrite` does not reset `approval_state` from REJECTED (HIGH)

**What**: When a REJECTED release is overwritten, `update_overwrite` resets `processing_status` to PENDING but leaves `approval_state` as `rejected`. The release remains in REJECTED state and will never appear in `list_pending_review()` or be eligible for approval after reprocessing completes.

**Why**: A rejected release that is resubmitted with `overwrite=true` must re-enter the approval queue. Without resetting to PENDING_REVIEW, the release is stuck in a terminal state.

**Where**: `infrastructure/release_repository.py`, method `update_overwrite`, lines 909-948.

**How**: Add `approval_state`, `rejection_reason`, `reviewer`, `reviewed_at` to the UPDATE SET clause:

```python
# AFTER:
SET revision = %s,
    processing_status = %s,
    approval_state = %s,
    rejection_reason = NULL,
    reviewer = NULL,
    reviewed_at = NULL,
    processing_started_at = NULL,
    processing_completed_at = NULL,
    last_error = NULL,
    updated_at = NOW()
WHERE release_id = %s
```

With parameters: `(revision, ProcessingStatus.PENDING, ApprovalState.PENDING_REVIEW, release_id)`

**Effort**: S (add 4 columns to existing UPDATE statement)
**Risk of fix**: Low -- purely additive columns in an existing UPDATE. The `can_overwrite()` guard already ensures we only reach this code from PENDING_REVIEW or REJECTED states.
**Confidence**: CONFIRMED

---

#### FIX 3: `update_overwrite` does not clear stale `job_id` (HIGH)

**What**: When a release is overwritten, `update_overwrite` resets processing fields but leaves the old `job_id` intact. Between the `update_overwrite` call (line 299 of `asset_service.py`) and `link_job_to_release` (line 388 of `submit.py`), the release points to the old job. If new job creation fails (line 385), the release is left permanently linked to a stale job -- an inconsistent state that the orphan detection on line 288 cannot catch (because `job_id` is not None).

**Why**: The old `job_id` creates a window where `get_release_by_job_id(old_job_id)` incorrectly returns this release.

**Where**: `infrastructure/release_repository.py`, method `update_overwrite`, lines 909-948.

**How**: Add `job_id = NULL` to the UPDATE SET clause (combine with FIX 2):

```python
            job_id = NULL,
```

**Effort**: S (one additional column in the same UPDATE from FIX 2)
**Risk of fix**: None -- `link_job_to_release` is called immediately after job creation and sets the correct `job_id`.
**Confidence**: CONFIRMED

---

#### FIX 4: Block overwrite while release is PROCESSING (HIGH)

**What**: `can_overwrite()` checks only `approval_state` (PENDING_REVIEW or REJECTED), not `processing_status`. A release with `approval_state=PENDING_REVIEW` and `processing_status=PROCESSING` passes the check. The old job continues running and writing physical side effects (blob writes, PostGIS table inserts) to shared output paths while the new job starts.

**Why**: Physical side effects from the old job (COG files, PostGIS rows) contaminate the new release's outputs.

**Where**: `core/models/asset.py`, method `can_overwrite`, line 643-645.

**How**: Add a `processing_status` check:

```python
# BEFORE:
def can_overwrite(self) -> bool:
    """Check if this release can be overwritten with new data."""
    return self.approval_state in (ApprovalState.PENDING_REVIEW, ApprovalState.REJECTED)

# AFTER:
def can_overwrite(self) -> bool:
    """Check if this release can be overwritten with new data."""
    if self.approval_state not in (ApprovalState.PENDING_REVIEW, ApprovalState.REJECTED):
        return False
    if self.processing_status == ProcessingStatus.PROCESSING:
        return False
    return True
```

Also update the error message in `services/asset_service.py` line 296:
```python
"pending_review or rejected (and not actively processing)"
```

**Effort**: S (3-line change in model method + error message update)
**Risk of fix**: Low -- callers already handle the `False` return via `ReleaseStateError`.
**Confidence**: CONFIRMED

---

#### FIX 5: Error response leaks internal exception details (MEDIUM)

**What**: The catch-all handler at lines 422-424 of `submit.py` passes `str(e)` directly into `error_response()`, which serializes it as JSON and returns it to the HTTP caller. Same pattern at line 379. Exception messages from psycopg, Azure SDK, and Python internals routinely contain database hostnames, connection strings, SQL queries, and internal paths.

**Why**: Information disclosure. An external caller can trigger errors that reveal internal infrastructure details.

**Where**: `triggers/platform/submit.py`, lines 379 and 422-424.

**How**: Replace raw exception messages with generic messages for 500-level errors:

```python
# Line 379 - AFTER:
return error_response(
    "Failed to create asset/release record. Check server logs for details.",
    "AssetCreationError",
    status_code=500
)

# Lines 422-424 - AFTER:
except Exception as e:
    logger.error(f"Platform request failed: {e}", exc_info=True)
    return error_response(
        "An internal error occurred. Check server logs for details.",
        "InternalError"
    )
```

**Effort**: S (two string changes)
**Risk of fix**: Low -- debugging info is still logged server-side.
**Confidence**: CONFIRMED

---

### ACCEPTED RISKS

| ID | Severity | Description | Rationale for Deferral |
|----|----------|-------------|------------------------|
| BUG-6 | MEDIUM | Deterministic job_id collides on overwrite with identical params | `release_id` is included in params which changes the hash. CoreMachine's idempotent check handles the edge case. Fix later when observed. |
| RISK-1 | MEDIUM | No advisory lock on release creation -- concurrent draft creation possible | Identical concurrent requests produce the same PK (caught by UniqueViolation). Different request_ids create two drafts, `get_draft` returns newest. Ugly but safe. Fix when formalizing state machine. |
| BLIND-3 | LOW-MED | `get_next_version_ordinal` excludes draft ordinals -- potential ordinal reuse | Race condition requires two concurrent "new version" submits. Practical impact is cosmetic. Fix by removing `version_id IS NOT NULL` filter. |
| BLIND-5 | LOW | `clearance_state` parsed at submit but never applied to release | Docstring says "Optional: specify clearance at submit for pre-approved data sources." Incomplete feature, not a bug. Approval endpoint handles clearance correctly. |
| BLIND-6 | LOW | `dry_run=true` creates asset as permanent side effect | Asset is a stable identity container with no lifecycle cost. Creating it early is harmless. |
| BLIND-4 | LOW | `release_tables` junction entries never cleaned for revoked releases | Revocation is rare admin operation; orphaned entries have no functional impact. |
| RISK-2 | LOW | Service Bus timeout ambiguity -- job may execute but be marked FAILED | Low probability. CoreMachine's state machine handles duplicate processing. |

---

### ARCHITECTURE WINS

1. **Asset/Release entity split**: Two-entity design with deterministic Asset IDs and lifecycle-carrying Releases is clean. Asset is truly a stable identity container (~12 fields); Release carries all versioning, approval, and processing state (~45 fields).

2. **Advisory locking on assets**: `find_or_create_asset()` uses PostgreSQL advisory locks for concurrent serialization. Correct pattern for preventing duplicate identity creation under concurrent load.

3. **Orphan detection**: Lines 286-298 of `submit.py` explicitly detect orphaned releases (prior attempt created Release but job creation failed) and return a clear 409 error with remediation instructions. Prevents silent failures.

4. **`can_overwrite()` as model method**: State guards live on the domain model rather than scattered across repository/service code. Correct DDD practice. FIX 4 extends this method rather than scattering checks elsewhere.

5. **`translate_to_coremachine` with fallback config**: Accepts optional `cfg` parameter with `None` default that self-resolves. Makes testing easy (inject mock config) while keeping production simple.

6. **Deterministic release_id with release_count disambiguator**: `SHA256(asset_id|uniquifier|release_count)` prevents PK collisions across approval cycles while maintaining idempotency within a cycle.

7. **Version ordinal reservation at draft creation**: Reserving the ordinal slot at draft time (not at approval) prevents the output-folder collision bug where two drafts would both write to `../draft/..`.

---

---

## Alpha: Architecture & Design Review

### STRENGTHS

#### 1. Well-defined Anti-Corruption Layer (ACL)
`services/platform_translation.py` (lines 158-401) cleanly separates the DDH external contract from CoreMachine internals. `translate_to_coremachine()` is the single choke-point where DDH semantics are mapped to internal job parameters. If DDH changes their API, the blast radius is confined to this one file.

#### 2. Clean Two-Entity Design (Asset / Release)
The V0.9 separation of Asset (stable identity, `core/models/asset.py` lines 92-288) from AssetRelease (versioned artifact, lines 294-717) is architecturally sound. The deterministic `asset_id = SHA256(platform_id|dataset_id|resource_id)[:32]` (line 258) ensures identity stability across releases.

#### 3. Repository Pattern with Clean Contracts
All three repositories extend `PostgreSQLRepository` and follow a consistent CRUD interface. The `_row_to_model()` private method provides a clean hydration boundary. Direct key access on NOT NULL columns means schema mismatches fail loudly.

#### 4. Advisory Locking for Concurrent Serialization
`AssetRepository.find_or_create()` (lines 192-292) uses `pg_advisory_xact_lock` with a deterministic key derived from the identity triple. Transaction-scoped lock is the correct pattern.

#### 5. Atomic Release Creation with Count Increment
`ReleaseRepository.create_and_count_atomic()` (lines 200-323) bundles INSERT + UPDATE in a single transaction. Explicit rollback on rowcount == 0 guards against orphans.

#### 6. Explicit Job Registry
`ALL_JOBS` in `jobs/__init__.py` uses explicit dictionary rather than decorator-based auto-discovery. Registry validation at import time enforces interface contracts before any job can be submitted.

#### 7. Response Builder Separation
`services/platform_response.py` isolates HTTP response construction from business logic. The trigger layer calls `submit_accepted()`, `idempotent_response()`, `validation_error()` without constructing JSON inline.

#### 8. State Machine Guards on Release
`AssetRelease` model has explicit guard methods (`can_approve()`, `can_reject()`, `can_revoke()`, `can_overwrite()` at lines 631-648 of `core/models/asset.py`).

### CONCERNS

| ID | Sev | File | Impact |
|----|-----|------|--------|
| HIGH-1 | HIGH | `triggers/platform/submit.py:170-371` | Trigger contains ~170 lines of domain logic (CSV preflight, GPKG warnings, STAC checks, ordinal finalization, title rewriting). Should be in service layer for reusability and testability. |
| HIGH-2 | HIGH | Multiple files | Inconsistent service instantiation -- `AssetService()`, `JobRepository()`, `PlatformRepository()` created ad-hoc per-request with no composition root or DI. Hidden coupling. |
| HIGH-3 | HIGH | `triggers/platform/submit.py:168` | `config` referenced as bare name -- undefined variable. See FIX 1. |
| MED-1 | MED | `services/platform_translation.py` | Dual responsibility: forward translation (DDH → CoreMachine) AND reverse translation (`get_unpublish_params_from_request` imports repositories). |
| MED-2 | MED | `core/models/platform.py:381-417` | PlatformRequest DTO encodes data type detection logic as a computed property. Routing decisions belong in translation service, not DTO. |
| MED-3 | MED | `services/platform_translation.py:404-568` | `translate_single_raster` and `translate_raster_collection` are dead code (deprecated endpoints return 410 Gone). |
| MED-4 | MED | `services/platform_validation.py` | Validation service is not wired into submit flow. Creates false sense of safety. |
| MED-5 | MED | `core/models/asset.py` | No formal state machine -- transitions scattered across model methods, service logic, and repository SQL. |
| LOW-1 | LOW | `services/platform_response.py:32-40` | Module-level mutable singleton `_config` never invalidated. |
| LOW-2 | LOW | `services/platform_job_submit.py:47-52` | `RASTER_JOB_FALLBACKS` flat dictionary doesn't scale for complex routing. |
| LOW-3 | LOW | `services/platform_validation.py:82-88` | Backward compatibility aliases (`lineage_id`, `lineage_exists`) contradicts project's "no backward compat" philosophy. |

### ASSUMPTIONS

| # | Assumption | Status | Notes |
|---|-----------|--------|-------|
| 1 | One Draft Per Asset invariant | FRAGILE | `get_draft()` returns `LIMIT 1 ORDER BY created_at DESC`. Advisory lock on Asset doesn't protect Release uniqueness. |
| 2 | Deterministic Job IDs prevent duplicates | SOLID | SHA256 of job_type + params with DB PK constraint. |
| 3 | Service Bus at-least-once delivery | SOLID | Code handles SB send failure by marking job FAILED. CoreMachine handles duplicate messages. |
| 4 | `release_count` is accurate | FRAGILE | Used for release_id generation. Can drift from actual count after manual DB edits or failed transactions. |
| 5 | File extension = reliable data type indicator | FRAGILE | Entire routing based on extension parsing. No content-type or magic byte validation. |
| 6 | DDH is the only platform | SOLID | `platform_id` hardcoded to "ddh". Architecture supports multiple platforms but trigger assumes DDH exclusively. |

### RECOMMENDATIONS

| ID | Priority | Recommendation |
|----|----------|----------------|
| R1 | HIGH | Extract domain logic from trigger into `PlatformSubmitService.submit()`. Trigger should be ~10 lines. |
| R2 | HIGH | Introduce composition root for dependency wiring (single factory per request). |
| R3 | MED | Remove dead `translate_single_raster` and `translate_raster_collection` functions. |
| R4 | MED | Move file-extension-to-DataType mapping from DTO property to translation service function. |
| R5 | MED | Wire `validate_version_lineage()` into submit flow or clearly deprecate the module. |
| R6 | MED | Formalize Release state machine as explicit transition table. |
| R7 | HIGH | Fix `config` undefined variable (see FIX 1). |
| R8 | LOW | Remove backward compatibility aliases in `VersionValidationResult`. |

---

## Beta: Correctness & Reliability Review

### VERIFIED SAFE

- **Advisory lock on asset creation**: `find_or_create_asset()` correctly uses `pg_advisory_xact_lock` scoped to the transaction. Lock key derived from identity triple via MD5 truncated to 15 hex chars (fits bigint). Verified: lines 218-231 of `asset_repository.py`.
- **Atomic release + count**: `create_and_count_atomic()` bundles INSERT and UPDATE in single transaction with explicit rollback. Verified: lines 200-323 of `release_repository.py`.
- **Orphan detection**: Lines 286-298 of `submit.py` catch the case where a release exists with `job_id=None` (prior job creation failed) and return a clear 409 error.
- **Deterministic ID generation**: Job IDs via SHA256 and asset IDs via SHA256 are collision-resistant and idempotent.

### BUGS

| ID | Sev | Description | Confidence |
|----|-----|-------------|------------|
| BUG-1 | CRITICAL | `config` NameError on `submit.py:168` -- every request crashes. See FIX 1. | CONFIRMED |
| BUG-2 | HIGH | Overwrite during PROCESSING allowed -- `can_overwrite()` checks only `approval_state`, not `processing_status`. Two jobs write to same physical outputs. See FIX 4. | CONFIRMED |
| BUG-3 | HIGH | `update_overwrite` doesn't clear old `job_id` -- stale job window. See FIX 3. | CONFIRMED |
| BUG-8 | HIGH | `update_overwrite` doesn't reset `approval_state` from REJECTED -- releases stuck forever. See FIX 2. | CONFIRMED |
| BUG-5 | MEDIUM | Non-atomic submit: release created before job. Orphaned on failure. Mitigated by orphan detection at lines 286-298. | CONFIRMED |
| BUG-6 | MEDIUM | Deterministic `job_id` collides on overwrite with identical params. SHA256 hash is same, `INSERT` hits `UniqueViolation`. | PROBABLE |
| BUG-7 | LOW | `_config` module-level global in `platform_response.py` with no thread safety (mitigated by CPython GIL and Azure Functions process model). | CONFIRMED |

### RISKS

| ID | Likelihood | Description | Blast Radius |
|----|-----------|-------------|--------------|
| RISK-1 | Medium | No advisory lock on release creation -- concurrent draft creation possible. Two requests could both see `get_draft()` return None, both create releases. | Orphaned draft, doubled `release_count`. |
| RISK-2 | Low-Med | Service Bus timeout ambiguity -- send hangs, catch block marks job FAILED, but message was actually delivered. Job executes but DB says FAILED. | Worker completion may not overwrite FAILED status. |
| RISK-3 | Low | `release_count` can drift from actual count after manual DB cleanup. Used for release_id generation. | Release ID collisions (low probability). |

### EDGE CASES

| ID | Trigger | Impact |
|----|---------|--------|
| EDGE-1 | Admin approves rejected draft between user's check and overwrite POST | Overwrite becomes new version instead of overwriting intended draft (TOCTOU) |
| EDGE-2 | `dry_run=true` for new dataset/resource | Creates permanent asset row as side effect |
| EDGE-3 | `clearance_state` in request body | Parsed but never applied -- dead code |
| EDGE-4 | Vector submission | `collection_id` not in job params; fallback to `dataset_id.lower()` for STAC collection ID |

---

## Gamma: Adversarial Contradiction Analysis

### CONTRADICTIONS

#### CONTRADICTION-1: `config` NameError -- Both Found, Agree on Existence

Both Alpha (HIGH-3) and Beta (BUG-1) independently found the `config` undefined variable at `submit.py:168`. Beta correctly classified it as CRITICAL (crashes every request). Alpha classified it as an architectural concern (inconsistent config access pattern). **Gamma verdict**: Beta's severity is correct. The `NameError` occurs at the call site before the function body executes, so `translate_to_coremachine`'s `cfg=None` fallback never fires.

#### CONTRADICTION-2: Advisory Lock Scope -- Talking Past Each Other

Alpha (Strength 4) praised advisory locking on assets. Beta (RISK-1) noted releases lack this protection. **Gamma verdict**: Both correct -- they're describing different things. Asset creation IS protected. Release creation IS NOT. The gap between the asset lock releasing and the release creation is unprotected.

#### CONTRADICTION-3: Overwrite During PROCESSING -- Severity Calibration

Beta (BUG-2) claims two jobs write to same release concurrently. **Gamma clarification**: The old job's `get_by_job_id(old_job_id)` returns `None` after `link_job` updates the release, preventing DB-level corruption. But physical side effects (blob writes, PostGIS writes) from the old job still happen. Severity is HIGH for physical outputs, not CRITICAL for DB state.

### AGREEMENT REINFORCEMENT (Highest Confidence)

| Finding | Alpha | Beta | Status |
|---------|-------|------|--------|
| `config` NameError | HIGH-3 | BUG-1 CRITICAL | **Both found independently. Highest confidence finding.** |
| `update_overwrite` incomplete | MEDIUM-5 (no formal FSM) | BUG-8 HIGH | Both identified from different angles. |

### BLIND SPOTS (Issues Neither Caught)

| ID | Sev | Description | Confidence |
|----|-----|-------------|------------|
| BLIND-1 | MEDIUM | `error_response` leaks raw exception messages (DB details, paths) to HTTP callers at `submit.py:422-424` and `submit.py:379` | CONFIRMED |
| BLIND-3 | LOW-MED | `get_next_version_ordinal` only counts approved releases (`WHERE version_id IS NOT NULL`), excluding draft ordinals -- potential reuse | PROBABLE |
| BLIND-4 | LOW | `release_tables` junction entries never cleaned for revoked releases -- unbounded growth | CONFIRMED |
| BLIND-5 | LOW | `clearance_state` parsed but never applied to release (confirms Beta EDGE-3 with full trace) | CONFIRMED |
| BLIND-6 | LOW | `dry_run=true` creates asset as permanent side effect (confirms Beta EDGE-2) | CONFIRMED |
| BLIND-7 | N/A | Validation service has a bug on line 274 (`current_latest.get()` when `current_latest` is `None`) but the service is dead code | CONFIRMED |

### SEVERITY RECALIBRATION

| Rank | ID | Severity | Description | Confidence |
|------|-----|----------|-------------|------------|
| 1 | BUG-1/HIGH-3 | **CRITICAL** | `config` NameError -- every submit crashes | CONFIRMED |
| 2 | BUG-8 | **HIGH** | `update_overwrite` doesn't reset `approval_state` | CONFIRMED |
| 3 | BUG-3 | **HIGH** | `update_overwrite` doesn't clear `job_id` | CONFIRMED |
| 4 | BUG-2 | **HIGH** | Overwrite during PROCESSING -- physical side effects | CONFIRMED |
| 5 | BLIND-1 | **MEDIUM** | Error response leaks internal details | CONFIRMED |
| 6 | BUG-5 | **MEDIUM** | Non-atomic submit (mitigated by orphan detection) | CONFIRMED |
| 7 | RISK-1 | **MEDIUM** | No advisory lock on release creation | CONFIRMED |
| 8 | BUG-6 | **MEDIUM** | Job ID collision on overwrite | PROBABLE |
| 9 | BLIND-3 | **LOW-MED** | `get_next_version_ordinal` excludes drafts | PROBABLE |
| 10 | BLIND-5 | **LOW** | `clearance_state` dead code | CONFIRMED |
| 11 | BLIND-6 | **LOW** | `dry_run` creates asset side effect | CONFIRMED |
| 12 | BLIND-4 | **LOW** | Junction entries never cleaned | CONFIRMED |
