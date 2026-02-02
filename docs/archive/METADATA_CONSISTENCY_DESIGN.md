# Metadata Consistency Checker Design

**Created**: 09 JAN 2026
**Status**: Working Document
**Epic**: E7 Pipeline Infrastructure → F7.10 Metadata Consistency Enforcement

---

## Quick Answers to Robert's Questions

### Q1: Blob storage checks - what's expensive?

**Blob Storage Operations Cost Matrix:**

| Operation | Cost | Frequency Appropriate |
|-----------|------|----------------------|
| **List blobs** (enumerate container) | 💰 CHEAP | Can run hourly |
| **Get blob properties** (metadata only) | 💰 CHEAP | Can run hourly |
| **HEAD request** (exists check) | 💰 CHEAP | Can run per-record |
| **Read blob content** | 💰💰 MODERATE | Daily or on-demand |
| **Open as rasterio/GDAL** | 💰💰💰 EXPENSIVE | Weekly or CoreMachine job |
| **Full COG validation** (read all overviews) | 💰💰💰💰 VERY EXPENSIVE | Only via CoreMachine job |

**Recommendation**:
- Timer trigger → List/HEAD operations only (DB + blob existence)
- CoreMachine job → Full COG validation (read file, verify overviews, check checksums)

### Q2: Frequent DB checks vs infrequent blob validation via CoreMachine?

**YES - Absolutely possible and recommended!**

```
┌─────────────────────────────────────────────────────────────────┐
│                    TWO-TIER VALIDATION                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  TIER 1: Timer Trigger (Every 6 hours)                         │
│  ─────────────────────────────────────                         │
│  • Database cross-reference checks                              │
│  • Blob existence checks (HEAD only)                            │
│  • STAC ↔ Metadata linkage validation                           │
│  • Fast, lightweight, frequent                                  │
│                                                                 │
│  TIER 2: CoreMachine Job (Weekly or on-demand)                  │
│  ─────────────────────────────────────────────                  │
│  • Full COG validation (open file, read headers)                │
│  • Verify overviews exist and are valid                         │
│  • Check compression, blocksize, CRS                            │
│  • Validate against app.cog_metadata values                     │
│  • Expensive but thorough                                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Q3: Same pattern for other checks?

**YES - Apply two-tier pattern consistently:**

| Check Domain | Tier 1 (Timer - Frequent) | Tier 2 (CoreMachine - Infrequent) |
|--------------|---------------------------|-----------------------------------|
| **Raster** | DB refs exist, blob HEAD | Full COG validation |
| **Vector** | table_metadata ↔ table exists | Row count validation, geometry check |
| **STAC** | Item exists in pgstac | Full STAC spec compliance |
| **DDH Refs** | FK integrity to metadata | Validate DDH API still has dataset |

---

## Current Timer Trigger Inventory

| Timer | Schedule | Purpose |
|-------|----------|---------|
| `janitor_task_watchdog` | Every 5 min | Stale task detection |
| `janitor_job_health` | Every 30 min | Failed task propagation |
| `janitor_orphan_detector` | Every hour | Orphaned records |
| `geo_orphan_check_timer` | Every 6 hours | Geo schema consistency |
| `curated_dataset_scheduler` | Daily 2 AM | Curated update checks |
| `system_snapshot_timer` | Every hour | Config snapshots |

**NEW (Proposed):**
| `metadata_consistency_timer` | Every 6 hours | Unified metadata validation |

---

## DRY Refactoring Opportunities

### Problem: Duplicated Patterns

**Current State - 3 patterns for timer handlers:**

```python
# Pattern A: Handler function (janitor triggers)
def janitor_task_watchdog(timer: func.TimerRequest) -> None:
    task_watchdog_handler(timer)  # Delegates to module

# Pattern B: Class method (curated trigger)
def curated_dataset_scheduler(timer: func.TimerRequest) -> None:
    curated_scheduler_trigger.handle_timer(timer)

# Pattern C: Inline logic (geo_orphan, snapshot)
def geo_orphan_check_timer(timer: func.TimerRequest) -> None:
    # 20+ lines of inline code duplicating logging patterns
```

**Duplicated Code in Each Handler:**
```python
# This pattern repeats in EVERY handler:
trigger_time = datetime.now(timezone.utc)
if timer.past_due:
    logger.warning("Timer is past due")
logger.info(f"Timer triggered at {trigger_time.isoformat()}")
try:
    result = service.do_thing()
    if result.success:
        logger.info(f"Completed: {result.items_fixed} fixed")
    else:
        logger.error(f"Failed: {result.error}")
except Exception as e:
    logger.error(f"Unhandled: {e}")
    logger.error(traceback.format_exc())
```

### Solution: Extract TimerHandlerBase

```python
# triggers/timer_base.py (NEW FILE)

class TimerHandlerBase:
    """
    Base class for timer trigger handlers.

    Provides:
    - Consistent past_due handling
    - Standard logging structure
    - Result interpretation
    - Exception wrapping
    """

    name: str  # Override in subclass

    def __init__(self):
        self.logger = LoggerFactory.create_logger(
            ComponentType.TRIGGER,
            self.name
        )

    def handle(self, timer: func.TimerRequest) -> Dict[str, Any]:
        """Standard timer handling with logging."""
        trigger_time = datetime.now(timezone.utc)

        # Past due check
        if timer.past_due:
            self.logger.warning(f"⏰ {self.name}: Timer is past due")

        self.logger.info(f"⏰ {self.name}: Triggered at {trigger_time.isoformat()}")

        try:
            result = self.execute()  # Subclass implements
            self._log_result(result)
            return result

        except Exception as e:
            self.logger.error(f"❌ {self.name}: Unhandled exception: {e}")
            self.logger.error(traceback.format_exc())
            return {"success": False, "error": str(e)}

    def execute(self) -> Dict[str, Any]:
        """Override in subclass to implement actual logic."""
        raise NotImplementedError

    def _log_result(self, result: Dict[str, Any]):
        """Standard result logging."""
        if result.get("success"):
            health = result.get("health_status", "UNKNOWN")
            if health == "HEALTHY":
                self.logger.info(f"✅ {self.name}: {health}")
            else:
                self.logger.warning(f"⚠️ {self.name}: {health}")
        else:
            self.logger.error(f"❌ {self.name}: {result.get('error')}")
```

### Refactored Handlers

```python
# triggers/admin/geo_orphan_timer.py (EXTRACTED from function_app.py)

class GeoOrphanTimerHandler(TimerHandlerBase):
    name = "GeoOrphanCheck"

    def execute(self) -> Dict[str, Any]:
        from services.janitor_service import geo_orphan_detector
        return geo_orphan_detector.run()

geo_orphan_handler = GeoOrphanTimerHandler()

# triggers/admin/metadata_consistency_timer.py (NEW)

class MetadataConsistencyHandler(TimerHandlerBase):
    name = "MetadataConsistency"

    def execute(self) -> Dict[str, Any]:
        checker = MetadataConsistencyChecker()
        return checker.run()

metadata_consistency_handler = MetadataConsistencyHandler()
```

---

## MetadataConsistencyChecker Design

### Class Structure

```python
# services/metadata_consistency.py (NEW FILE)

class MetadataConsistencyChecker:
    """
    Unified metadata consistency enforcement.

    Tier 1 checks (database + blob HEAD):
    - STAC ↔ Metadata cross-reference
    - Dataset refs integrity
    - Blob existence (HEAD only)

    Reports findings, does NOT auto-delete.
    """

    def run(self) -> Dict[str, Any]:
        """Execute all Tier 1 consistency checks."""
        result = {
            "success": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": {},
            "issues": [],
            "summary": {},
            "health_status": "HEALTHY"
        }

        # Run each check
        result["checks"]["stac_vector_orphans"] = self._check_stac_vector_orphans()
        result["checks"]["stac_raster_orphans"] = self._check_stac_raster_orphans()
        result["checks"]["vector_backlinks"] = self._check_vector_backlinks()
        result["checks"]["raster_backlinks"] = self._check_raster_backlinks()
        result["checks"]["dataset_refs_vector"] = self._check_dataset_refs_vector()
        result["checks"]["dataset_refs_raster"] = self._check_dataset_refs_raster()
        result["checks"]["raster_blob_exists"] = self._check_raster_blobs_exist()

        # Aggregate issues
        for check_name, check_result in result["checks"].items():
            if check_result.get("issues"):
                result["issues"].extend(check_result["issues"])

        # Determine health status
        result["health_status"] = "HEALTHY" if not result["issues"] else "ISSUES_DETECTED"
        result["success"] = True

        return result
```

### Check Implementations

```python
def _check_stac_vector_orphans(self) -> Dict[str, Any]:
    """
    Find STAC items for vector collections without geo.table_metadata.

    Query: pgstac.items LEFT JOIN geo.table_metadata
           WHERE collection LIKE 'vector-%' AND metadata IS NULL
    """
    check = {"name": "stac_vector_orphans", "issues": [], "scanned": 0}

    try:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT i.id as stac_item_id, i.collection
                    FROM pgstac.items i
                    LEFT JOIN geo.table_metadata m
                        ON i.id = m.stac_item_id
                    WHERE i.collection LIKE 'vector-%'
                    AND m.table_name IS NULL
                    LIMIT 100
                """)
                orphans = cur.fetchall()
                check["scanned"] = len(orphans)

                for orphan in orphans:
                    check["issues"].append({
                        "type": "stac_vector_orphan",
                        "stac_item_id": orphan["stac_item_id"],
                        "collection": orphan["collection"],
                        "message": "STAC item exists but no geo.table_metadata record"
                    })

    except Exception as e:
        check["error"] = str(e)

    return check


def _check_raster_blobs_exist(self) -> Dict[str, Any]:
    """
    Verify COGs in app.cog_metadata actually exist in blob storage.

    Uses HEAD request only (cheap).
    """
    check = {"name": "raster_blob_exists", "issues": [], "scanned": 0}

    try:
        # Get all COG records
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT cog_id, container, blob_path
                    FROM app.cog_metadata
                    ORDER BY created_at DESC
                    LIMIT 500
                """)
                cogs = cur.fetchall()

        check["scanned"] = len(cogs)

        # Check each blob exists (HEAD only)
        from azure.storage.blob import BlobServiceClient

        for cog in cogs:
            exists = self._blob_exists(cog["container"], cog["blob_path"])
            if not exists:
                check["issues"].append({
                    "type": "raster_blob_missing",
                    "cog_id": cog["cog_id"],
                    "container": cog["container"],
                    "blob_path": cog["blob_path"],
                    "message": "COG metadata exists but blob not found"
                })

    except Exception as e:
        check["error"] = str(e)

    return check


def _blob_exists(self, container: str, blob_path: str) -> bool:
    """HEAD request to check blob exists (cheap operation)."""
    try:
        from infrastructure.blob_storage import BlobStorageRepository
        repo = BlobStorageRepository(container)
        return repo.blob_exists(blob_path)  # HEAD request only
    except Exception:
        return False  # Assume missing on error
```

---

## Timer Registration

### New Timer in function_app.py

```python
# ============================================================================
# METADATA CONSISTENCY TIMER (F7.10)
# ============================================================================
# Schedule: Every 6 hours (offset from geo_orphan by 3 hours)
# Purpose: Unified metadata validation across vector, raster, STAC, DDH refs
# ============================================================================

@app.timer_trigger(
    schedule="0 0 3,9,15,21 * * *",  # Every 6 hours at 03:00, 09:00, 15:00, 21:00
    arg_name="timer",
    run_on_startup=False
)
def metadata_consistency_timer(timer: func.TimerRequest) -> None:
    """
    Unified metadata consistency check (Tier 1 - DB + blob HEAD).

    Runs every 6 hours, offset from geo_orphan_check_timer.

    Checks:
    - STAC ↔ Metadata cross-reference (vector and raster)
    - Dataset refs FK integrity
    - Raster blob existence (HEAD only)

    Full validation (Tier 2) runs via CoreMachine job weekly.
    """
    from triggers.admin.metadata_consistency_timer import metadata_consistency_handler
    metadata_consistency_handler.handle(timer)
```

---

## File Structure (New Files)

```
rmhgeoapi/
├── triggers/
│   ├── timer_base.py                    # NEW: TimerHandlerBase
│   └── admin/
│       ├── geo_orphan_timer.py          # EXTRACTED from function_app.py
│       └── metadata_consistency_timer.py # NEW: Handler class
│
├── services/
│   └── metadata_consistency.py          # NEW: MetadataConsistencyChecker
│
└── jobs/
    └── validate_metadata.py             # FUTURE: Tier 2 CoreMachine job
```

---

## TODO List

### Phase 1: Foundation (DRY Refactoring) ✅ COMPLETE

| Task | Description | Status | Notes |
|------|-------------|--------|-------|
| T1.1 | Create `triggers/timer_base.py` with `TimerHandlerBase` class | ✅ | 175 lines, ABC pattern |
| T1.2 | Extract `geo_orphan_check_timer` to `triggers/admin/geo_orphan_timer.py` | ✅ | Wraps GeoOrphanDetector |
| T1.3 | Extract `system_snapshot_timer` to `triggers/admin/system_snapshot_timer.py` | ✅ | Preserves drift detection |
| T1.4 | Update function_app.py to use extracted handlers | ✅ | Reduced ~50 lines inline |
| T1.5 | Syntax verification | ✅ | All files pass py_compile |

### Phase 2: Metadata Consistency Checker (Core Service) ✅ COMPLETE

| Task | Description | Status | Notes |
|------|-------------|--------|-------|
| T2.1 | Create `services/metadata_consistency.py` with `MetadataConsistencyChecker` | ✅ | 580 lines |
| T2.2 | Implement `_check_stac_vector_orphans()` | ✅ | pgstac.items LEFT JOIN geo.table_metadata |
| T2.3 | Implement `_check_stac_raster_orphans()` | ✅ | pgstac.items LEFT JOIN app.cog_metadata |
| T2.4 | Implement `_check_vector_backlinks()` | ✅ | table_metadata.stac_item_id → pgstac |
| T2.5 | Implement `_check_raster_backlinks()` | ✅ | cog_metadata.stac_item_id → pgstac |
| T2.6 | Implement `_check_dataset_refs_vector()` | ✅ | dataset_refs → table_metadata FK |
| T2.7 | Implement `_check_dataset_refs_raster()` | ✅ | dataset_refs → cog_metadata FK |
| T2.8 | Implement `_check_raster_blobs_exist()` | ✅ | HEAD request, last 100 COGs |
| T2.9 | Add `get_metadata_consistency_checker()` singleton factory | ✅ | Standard pattern |

### Phase 3: Timer Integration ✅ COMPLETE

| Task | Description | Status | Notes |
|------|-------------|--------|-------|
| T3.1 | Create `triggers/admin/metadata_consistency_timer.py` | ✅ | Uses TimerHandlerBase |
| T3.2 | Register `metadata_consistency_timer` in function_app.py | ✅ | Schedule: 03:00,09:00,15:00,21:00 UTC |
| T3.3 | Add HTTP endpoint `GET /api/cleanup/metadata-health` | ✅ | Dedicated health endpoint |
| T3.4 | Add `metadata_consistency` to `/api/cleanup/run` | ✅ | Works with type=all too |
| T3.5 | Syntax verification | ✅ | All files pass py_compile |

### Phase 4: Tier 2 Validation (Future - CoreMachine) - DEFERRED

| Task | Description | Status | Notes |
|------|-------------|--------|-------|
| T4.1 | Design `validate_metadata` job type | 🔮 | Weekly deep validation |
| T4.2 | Implement full COG validation stage | 🔮 | Open file, verify overviews |
| T4.3 | Implement full vector validation stage | 🔮 | Row counts, geometry checks |
| T4.4 | Add weekly scheduled submission | 🔮 | Via curated scheduler pattern |

### Phase 5: Remediation Actions (Future) - DEFERRED

| Task | Description | Status | Notes |
|------|-------------|--------|-------|
| T5.1 | Design safe deletion workflow | 🔮 | Requires approval flow |
| T5.2 | Implement orphan cleanup endpoint | 🔮 | With confirmation |
| T5.3 | Audit logging for deletions | 🔮 | Track who deleted what |

---

## Implementation Log

### Phase 1 Progress ✅ COMPLETE

_Started: 09 JAN 2026_
_Completed: 09 JAN 2026_

**T1.1 - TimerHandlerBase**:
- Status: ✅ Complete
- File: `triggers/timer_base.py` (175 lines)
- Features: ABC pattern, lazy logger loading, past_due handling, health_status interpretation

**T1.2 - Extract geo_orphan_timer**:
- Status: ✅ Complete
- File: `triggers/admin/geo_orphan_timer.py`
- Notes: Simple wrapper around existing GeoOrphanDetector

**T1.3 - Extract system_snapshot_timer**:
- Status: ✅ Complete
- File: `triggers/admin/system_snapshot_timer.py`
- Notes: Added health_status mapping for DRIFT_DETECTED

**T1.4 - Update function_app.py**:
- Status: ✅ Complete
- Notes: Reduced ~50 lines of inline code, now 2-line handler calls

**T1.5 - Syntax verification**:
- Status: ✅ Complete
- All 3 new files pass py_compile

### Phase 2 Progress ✅ COMPLETE

_Started: 09 JAN 2026_
_Completed: 09 JAN 2026_

**T2.1-T2.9 - MetadataConsistencyChecker**:
- Status: ✅ Complete
- File: `services/metadata_consistency.py` (580 lines)
- 7 check methods implemented
- Graceful handling of missing tables (skipped with reason)
- Singleton factory pattern matches other services

**Design Decisions**:
- Checks are independent - one failure doesn't block others
- Each check has "skipped" state for missing dependencies
- Blob check limited to 100 most recent COGs (balance thoroughness vs speed)
- All queries have LIMIT 100 to prevent runaway on large datasets

### Phase 3 Progress ✅ COMPLETE

_Started: 09 JAN 2026_
_Completed: 09 JAN 2026_

**T3.1 - Timer Handler**:
- Status: ✅ Complete
- File: `triggers/admin/metadata_consistency_timer.py`
- Added detailed issue logging (first 10 issues logged individually)

**T3.2 - Timer Registration**:
- Status: ✅ Complete
- Schedule: `0 0 3,9,15,21 * * *` (every 6 hours, offset from geo_orphan)
- Placed after geo_orphan_check_timer, before curated_dataset_scheduler

**T3.3-T3.4 - HTTP Endpoints**:
- Status: ✅ Complete
- `GET /api/cleanup/metadata-health` - Dedicated health endpoint
- `POST /api/cleanup/run?type=metadata_consistency` - Integrated with janitor

**T3.5 - Syntax verification**:
- Status: ✅ Complete
- All files pass py_compile

---

## Notable Findings & Unexpected Issues

_Document any surprises, edge cases, or design decisions made during implementation._

1. **TimerHandlerBase Logging Levels**: Decided to use WARNING for ISSUES_DETECTED and DRIFT_DETECTED health statuses, INFO for HEALTHY. This ensures issues show up in default Application Insights queries.

2. **Blob Check Scope**: Limited `_check_raster_blobs_exist()` to most recent 100 COGs. This balances thoroughness with performance. Tier 2 (CoreMachine) will do full validation.

3. **STAC Item ID Matching**: The check assumes `stac_item_id` in metadata matches `id` in pgstac.items exactly. If there are case sensitivity issues, this may need adjustment.

4. **Missing Table Handling**: All checks gracefully skip if required tables don't exist (e.g., app.cog_metadata before first deployment). This is intentional - new tables won't be created until schema rebuild.

5. **Janitor HTTP Integration**: Extended existing `janitor_run_handler` rather than creating separate HTTP trigger class. This keeps all cleanup operations discoverable under `/api/cleanup/`.

6. **DRY Success**: Extracted ~100 lines of inline timer code into reusable TimerHandlerBase. Future timers can be created with ~30 lines instead of ~50+.

---

---

## Health Status Output Example

```json
{
  "success": true,
  "timestamp": "2026-01-09T15:00:00Z",
  "duration_seconds": 12.5,
  "checks": {
    "stac_vector_orphans": {
      "scanned": 45,
      "issues": []
    },
    "stac_raster_orphans": {
      "scanned": 128,
      "issues": [
        {
          "type": "stac_raster_orphan",
          "stac_item_id": "fathom-flood-2020-tile-001",
          "collection": "fathom-flood-data",
          "message": "STAC item exists but no app.cog_metadata record"
        }
      ]
    },
    "raster_blob_exists": {
      "scanned": 200,
      "issues": []
    }
  },
  "summary": {
    "total_checks": 7,
    "total_scanned": 573,
    "total_issues": 1
  },
  "health_status": "ISSUES_DETECTED"
}
```

---

## Schedule Summary

| Timer | Schedule | Offset | Purpose |
|-------|----------|--------|---------|
| `geo_orphan_check_timer` | `0 0 */6 * * *` | :00 | Geo table consistency |
| `metadata_consistency_timer` | `0 0 3,9,15,21 * * *` | :00 +3h | Unified metadata validation |

Offset by 3 hours to spread load and avoid simultaneous heavy queries.

---

## Open Questions

1. **Should metadata_consistency_timer also check geo orphans?**
   - Option A: Keep separate (current design) - clear separation
   - Option B: Consolidate into single timer - simpler but coupled

2. **Blob existence check scope?**
   - Option A: Check all COGs (thorough but slow)
   - Option B: Check recent COGs only (fast, catches recent issues)
   - Option C: Sample-based (random 10%, statistical confidence)

3. **Alert integration?**
   - Should ISSUES_DETECTED trigger alerts (Application Insights, email)?
   - Or just verbose logging for now?

---

## References

- `services/janitor_service.py` - GeoOrphanDetector pattern
- `triggers/janitor/*.py` - Timer handler patterns
- `core/models/unified_metadata.py` - RasterMetadata, VectorMetadata
- `infrastructure/raster_metadata_repository.py` - COG metadata CRUD
