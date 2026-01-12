# Working Backlog

**Last Updated**: 12 JAN 2026
**Source of Truth**: [docs/epics/README.md](/docs/epics/README.md) — Epic/Feature/Story definitions
**Purpose**: Sprint-level task tracking and delegation

---

## 🔥 NEXT UP: RasterMetadata + STAC Self-Healing (F7.9 + F7.11)

**Epic**: E7 Pipeline Infrastructure → E2 Raster Data as API
**Goal**: Complete unified metadata architecture for rasters and wire up STAC self-healing
**Priority**: CRITICAL - Raster is primary STAC use case, self-healing depends on metadata
**Updated**: 12 JAN 2026

### Why Combined Priority

F7.9 (RasterMetadata) and F7.11 (STAC Self-Healing) are tightly coupled:
- F7.11 raster support **depends on** F7.9 being complete
- Both share the same service layer (`service_stac_metadata.py`, `stac_catalog.py`)
- Completing together ensures consistent metadata → STAC pipeline

### F7.9: RasterMetadata Implementation

**Status**: Phase 1 ✅ COMPLETE, Phase 2 📋 IN PROGRESS
**Dependency**: F7.8 ✅ (BaseMetadata, VectorMetadata pattern established)

#### Phase 1 (COMPLETE - 09 JAN 2026)

| Story | Description | Status |
|-------|-------------|--------|
| S7.9.1 | Create `RasterMetadata` class in `core/models/unified_metadata.py` | ✅ |
| S7.9.2 | Create `app.cog_metadata` table DDL with typed columns | ✅ |
| S7.9.3 | Create `RasterMetadataRepository` with CRUD operations | ✅ |
| S7.9.4 | Implement `RasterMetadata.from_db_row()` factory method | ✅ |
| S7.9.5 | Implement `RasterMetadata.to_stac_item()` conversion | ✅ |
| S7.9.6 | Implement `RasterMetadata.to_stac_collection()` conversion | ✅ |

#### Phase 2 (IN PROGRESS - 12 JAN 2026)

**Key Discovery**: Both `process_raster_v2` and `process_raster_docker` use the SAME handler for STAC creation: `services/stac_catalog.py:extract_stac_metadata()`. This is the single wiring point.

| Story | Description | Status |
|-------|-------------|--------|
| S7.9.8 | Wire `extract_stac_metadata` to populate `app.cog_metadata` | ✅ 12 JAN 2026 |
| S7.9.8a | Extract raster properties from STAC item for cog_metadata | ✅ |
| S7.9.8b | Call `RasterMetadataRepository.upsert()` after pgSTAC insert | ✅ |
| S7.9.8c | Handle graceful degradation if cog_metadata insert fails | ✅ |
| S7.11.5 | Enable raster rebuild in `rebuild_stac_handlers.py` | ✅ 12 JAN 2026 |
| S7.11.5a | Query `app.cog_metadata` for raster validation | ✅ |
| S7.11.5b | Use `RasterMetadata.to_stac_item()` for rebuild | ✅ |
| S7.9.TEST | Test: `process_raster_v2` populates cog_metadata + STAC | 📋 NEXT |

**Raster Job Architecture** (discovered 12 JAN 2026):
```
process_raster_v2 (Function App, <1GB)     process_raster_docker (Docker, large files)
        │                                           │
        │ Stage 3                                   │ Phase 3
        ▼                                           ▼
    ┌─────────────────────────────────────────────────┐
    │  services/stac_catalog.py:extract_stac_metadata │  ← SINGLE WIRING POINT
    │      Step 5: Insert STAC item to pgSTAC         │
    │      Step 5.5: Populate app.cog_metadata (NEW)  │
    └─────────────────────────────────────────────────┘
```

**Key Files**:
- `core/models/unified_metadata.py` - RasterMetadata domain model
- `core/models/raster_metadata.py` - CogMetadataRecord for DDL
- `core/schema/sql_generator.py` - Table/index generation
- `infrastructure/raster_metadata_repository.py` - CRUD operations

### F7.11: STAC Catalog Self-Healing

**Status**: 🚧 IN PROGRESS (vectors working, raster pending)
**Implemented**: 10 JAN 2026

| Story | Status | Description |
|-------|--------|-------------|
| S7.11.1 | ✅ | Create `jobs/rebuild_stac.py` - 2-stage job definition |
| S7.11.2 | ✅ | Create `services/rebuild_stac_handlers.py` - validate + rebuild handlers |
| S7.11.3 | ✅ | Register job and handlers in `__init__.py` files |
| S7.11.4 | ✅ | Add `force_recreate` mode (delete existing STAC before rebuild) |
| S7.11.5 | 📋 | **Add raster support** (rebuild from app.cog_metadata) ← Depends on F7.9 |
| S7.11.6 | 📋 | Timer auto-submit (F7.10 detects → auto-submit rebuild job) |

**Key Files**:
- `jobs/rebuild_stac.py` - RebuildStacJob class
- `services/rebuild_stac_handlers.py` - stac_rebuild_validate, stac_rebuild_item

---

## ✅ COMPLETED: Docker Worker Infrastructure (F7.12-13)

**Status**: ✅ COMPLETE - Moved to HISTORY.md (12 JAN 2026)
**Reference**: See HISTORY.md for full implementation details

### Summary

- F7.12: Docker Worker Infrastructure ✅ Deployed to `rmhheavyapi`
- F7.13: Docker Job Definitions ✅ Phase 1 complete (checkpoint/resume architecture)
- Tested: dctest.tif processed successfully via Docker worker

### Remaining Backlog (Low Priority)

| Story | Description | Status |
|-------|-------------|--------|
| S7.13.13 | Test checkpoint/resume: Docker crash → resume from checkpoint | 📋 |
| S7.13.14 | Add `process_vector_docker` job (same pattern) | 📋 |

---

## FY26 Priorities (ends 30 JUN 2026)

| Priority | Epic | Name | Status | Next Action |
|:--------:|------|------|--------|-------------|
| **1** | E7→E2 | **RasterMetadata + STAC Self-Healing** | 🔴 | F7.9 + F7.11: CRITICAL |
| **2** | E8 | **H3 Analytics (Rwanda)** | 🚧 | H3 bootstrap running (res 3-7) |
| 3 | E8 | Building Flood Exposure | 📋 | F8.7: MS Buildings → FATHOM → H3 |
| 4 | E9 | Pre-prepared Raster Ingest | 📋 | F9.8: COG copy + STAC |
| 5 | E2 | Raster Data as API | 🚧 | F2.7: Collection Processing |
| 6 | E3 | DDH Platform Integration | 🚧 | F3.1: Validate Swagger UI |
| — | E7 | Pipeline Builder | 📋 | F7.5: Future (after concrete implementations) |

**Focus**: Rwanda as test region for all analytics pipelines before scaling.

**Completed**:
- E9 FATHOM Rwanda Pipeline ✅
- E7 Unified Metadata Architecture ✅ (F7.8 VectorMetadata)
- E7 Docker Worker Infrastructure ✅ (F7.12-13)

---

## Current Sprint Focus

### 🟡 H3 Analytics on Rwanda

**Epic**: E8 GeoAnalytics Pipeline
**Goal**: H3 aggregation of FATHOM flood data for Rwanda
**Dependency**: F9.1 ✅ (FATHOM merged COGs exist in silver-fathom)
**Status**: H3 bootstrap running (08 JAN 2026)

#### F8.13: Rwanda H3 Aggregation

| Story | Description | Status |
|-------|-------------|--------|
| S8.13.1 | Seed Rwanda H3 cells (res 2-7, country-filtered) | 🔴 Stage 3 timeout |
| S8.13.1a | **Fix H3 finalize timeout** - pg_cron + autovacuum | ✅ Done (08 JAN) |
| S8.13.1b | Enable pg_cron extension in Azure Portal | 📋 |
| S8.13.1c | Run pg_cron_setup.sql on database | 📋 |
| S8.13.1d | Re-run H3 bootstrap (run_vacuum=False) | 📋 |
| S8.13.2 | Add FATHOM merged COGs to source_catalog | 📋 |
| S8.13.3 | Run H3 raster aggregation on Rwanda FATHOM | 📋 |
| S8.13.4 | Verify zonal_stats populated for flood themes | 📋 |
| S8.13.5 | Test H3 export endpoint with Rwanda data | 📋 |

See [TABLE_MAINTENANCE.md](./TABLE_MAINTENANCE.md) for pg_cron setup steps.

---

### 🟢 Building Flood Exposure Pipeline

**Epic**: E8 GeoAnalytics Pipeline
**Goal**: Calculate % of buildings in flood risk areas, aggregated to H3 level 7
**Dependency**: F8.13 (H3 cells for Rwanda), F9.1 ✅ (FATHOM COGs)
**Data Source**: Microsoft Building Footprints (direct download)
**Initial Scenario**: `fluvial-defended-2020` (baseline)

#### F8.7: Building Flood Exposure Job

| Story | Description | Status |
|-------|-------------|--------|
| S8.7.1 | Download MS Building Footprints for Rwanda | 📋 |
| S8.7.2 | Create `buildings` schema (footprints, flood_exposure tables) | 📋 |
| S8.7.3 | Create `BuildingFloodExposureJob` definition (4-stage) | 📋 |
| S8.7.4 | Stage 1 handler: `building_load_footprints` (GeoJSON → PostGIS) | 📋 |
| S8.7.5 | Stage 2 handler: `building_assign_h3` (centroid → H3 index) | 📋 |
| S8.7.6 | Stage 3 handler: `building_sample_fathom` (point → raster value) | 📋 |
| S8.7.7 | Stage 4 handler: `building_aggregate_h3` (SQL aggregation) | 📋 |
| S8.7.8 | End-to-end test: Rwanda + fluvial-defended-2020 | 📋 |
| S8.7.9 | Expand to all FATHOM scenarios (39 for Rwanda) | 📋 |

---

## Other Active Work

### ⚪ Future: Pipeline Builder (Low Priority)

**Epic**: E7 Pipeline Infrastructure
**Goal**: Generalize FATHOM pipeline to configuration-driven raster processing
**Timeline**: After FATHOM + H3 + Open Buildings working on Rwanda

#### F7.5: Pipeline Builder

| Story | Description | Status |
|-------|-------------|--------|
| S7.5.1 | Abstract FATHOM dimension parser to configuration | 📋 |
| S7.5.2 | Create `ComplexRasterPipeline` base class | 📋 |
| S7.5.3 | YAML/JSON pipeline definition schema | 📋 |
| S7.5.4 | Pipeline Builder UI (visual orchestration) | 📋 |

**Design Principle**: Build concrete implementations first (FATHOM, H3, Buildings), then extract patterns.

---

## E4: Classification Enforcement & ADF Integration

**Added**: 07 JAN 2026
**Epic**: E4 Security Zones / Externalization
**Goal**: Make `access_level` (OUO/Public/Restricted) mandatory and prepare for ADF integration
**Context**: Colleague configuring ADF; we need Python side ready with correct parameters

### Background

Data classification (`access_level`) controls where data can be exported:
- **PUBLIC**: Can be copied to external-facing storage (ADF will handle this)
- **OUO** (Official Use Only): Internal only, ADF should reject export requests
- **RESTRICTED**: Highest restriction, no external access

Currently `access_level` is inconsistently enforced across the codebase. This work makes it:
1. **Mandatory** at Platform API entry point
2. **Type-safe** using `AccessLevel` enum throughout
3. **Fail-fast** in pipeline tasks if somehow missing

### Current State Analysis (07 JAN 2026)

| Location | Type | Default | Required | Issue |
|----------|------|---------|----------|-------|
| `PlatformRequest` | `str` | `"OUO"` | ✅ | Not using enum |
| `AccessLevel` enum | `Enum` | N/A | N/A | Exists but unused |
| Job parameter schemas | `str` | `None` | ❌ | Loses value |
| `PlatformMetadata` dataclass | `Optional[str]` | `None` | ❌ | Loses value |
| `PlatformProperties` model | `Optional[AccessLevel]` | `None` | ❌ | Uses enum but optional |

**Key Files**:
- `core/models/stac.py:57-62` - `AccessLevel` enum definition
- `core/models/platform.py:147-151` - `PlatformRequest.access_level` field
- `triggers/trigger_platform.py` - Translation functions
- `jobs/process_raster_v2.py:92` - Job parameter schema
- `jobs/raster_mixin.py:93-98` - `PLATFORM_PASSTHROUGH_SCHEMA`
- `services/stac_metadata_helper.py:69` - `PlatformMetadata` dataclass
- `infrastructure/data_factory.py` - ADF repository (ready for testing)

### Phase 1: Enforce at Platform Level

**Goal**: Reject requests with invalid/missing classification at API entry point

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S4.CL.1 | Update `PlatformRequest.access_level` to use `AccessLevel` enum | 📋 | `core/models/platform.py` |
| S4.CL.2 | Add Pydantic validator to normalize case (accept "OUO" → store as "ouo") | 📋 | `core/models/platform.py` |
| S4.CL.3 | Make `access_level` required (remove default) OR keep secure default "ouo" | 📋 | `core/models/platform.py` |
| S4.CL.4 | Update `_translate_to_coremachine()` to pass enum value (lowercase string) | 📋 | `triggers/trigger_platform.py` |
| S4.CL.5 | Add validation tests for Platform API rejection of invalid values | 📋 | `tests/` |

**Implementation Notes for S4.CL.1-3**:
```python
# core/models/platform.py - Change from:
access_level: str = Field(default="OUO", max_length=50, ...)

# To:
from core.models.stac import AccessLevel

access_level: AccessLevel = Field(
    default=AccessLevel.OUO,
    description="Data classification: public, ouo, restricted"
)

@field_validator('access_level', mode='before')
@classmethod
def normalize_access_level(cls, v):
    """Accept case-insensitive input, normalize to enum."""
    if isinstance(v, str):
        try:
            return AccessLevel(v.lower())
        except ValueError:
            raise ValueError(f"Invalid access_level '{v}'. Must be: public, ouo, restricted")
    return v
```

**Decision Point**: Keep `default=AccessLevel.OUO` (secure by default) or make truly required (no default). Recommend keeping default since OUO is the safe choice.

### Phase 2: Fail-Fast in Pipeline Tasks

**Goal**: Defense-in-depth - tasks fail immediately if access_level missing (shouldn't happen if Phase 1 works)

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S4.CL.6 | Add `access_level` to job schemas with `required: True` | 📋 | `jobs/raster_mixin.py`, `jobs/process_raster_v2.py`, `jobs/process_vector.py` |
| S4.CL.7 | Add validation in STAC metadata creation (fail if missing) | 📋 | `services/stac_metadata_helper.py` |
| S4.CL.8 | Add validation in promote handlers (data export tasks) | 📋 | `services/promote_service.py` |
| S4.CL.9 | Update `PlatformMetadata` dataclass to require access_level | 📋 | `services/stac_metadata_helper.py` |
| S4.CL.10 | Add checkpoints logging for access_level at key stages | 📋 | Various handlers |

**Implementation Notes for S4.CL.6**:
```python
# jobs/raster_mixin.py - Update PLATFORM_PASSTHROUGH_SCHEMA:
PLATFORM_PASSTHROUGH_SCHEMA = {
    'dataset_id': {'type': 'str', 'default': None},
    'resource_id': {'type': 'str', 'default': None},
    'version_id': {'type': 'str', 'default': None},
    'access_level': {
        'type': 'str',
        'required': True,  # Now required!
        'allowed': ['public', 'ouo', 'restricted']
    },
}
```

**Implementation Notes for S4.CL.7**:
```python
# In job submission endpoint:
if file_size_mb > config.raster.raster_route_docker_mb:
    job_type = "process_raster_docker"  # Auto-route to Docker
else:
    job_type = "process_raster_v2"      # Standard Function App
```

**Alternative - TaskRoutingConfig**:
```bash
ROUTE_TO_DOCKER=create_cog,process_fathom_stack
```

**Current Decision**: Separate job definitions is simpler and sufficient for MVP.
Automatic routing can be added when:
1. Docker worker is proven stable
2. Real metrics show where the size threshold should be
3. Client convenience outweighs explicit job selection

### F7.15: HTTP-Triggered Docker Worker (Alternative Architecture)

**Status**: 📋 PLANNED - Alternative to Service Bus polling
**Added**: 11 JAN 2026
**Prerequisite**: Complete F7.13 Option A first, then implement as configuration option

**Concept**: Eliminate Docker→Service Bus connection entirely.
Function App task worker HTTP-triggers Docker, then exits. Docker tracks its own state.

```
┌─────────────────┐    ┌──────────────────────┐
│  Function App   │───▶│  Service Bus Queue   │
│  (SB Trigger)   │◀───│  long-running-tasks  │
└────────┬────────┘    └──────────────────────┘
         │
         │ 1. HTTP POST /task/start
         │    {task_id, params, callback_url}
         │
         │ 2. Docker returns 202 Accepted immediately
         ▼
┌─────────────────┐
│  Docker Worker  │──── 3. Process task in background
│  (HTTP only)    │     4. Update task status in PostgreSQL
└────────┬────────┘     5. Optionally call callback_url when done
         │
         │ (Function App is already gone - no timeout issues)
         ▼
   Task completion detected by:
   - Polling task status table
   - Or callback to Function App HTTP endpoint
```

**Why This Might Be Better**:
1. **Simpler Docker auth** - Only needs HTTP endpoint, no Service Bus SDK
2. **No queue credentials in Docker** - Function App owns all queue logic
3. **Function App exits immediately** - No timeout concerns
4. **State in PostgreSQL** - Already have task status table

**Key Insight**: Docker uses THE SAME CoreMachine as Function App.
It's Python + SQL - the only difference is the trigger mechanism.

**Implementation Stories**:

| Story | Description | Status |
|-------|-------------|--------|
| S7.15.1 | Create 2-stage job: `process_raster_docker_http` | 📋 |
| S7.15.2 | Stage 1 handler: `validate_and_trigger_docker` | 📋 |
| S7.15.3 | Docker endpoint: `POST /task/start` | 📋 |
| S7.15.4 | Docker background processing with CoreMachine | 📋 |
| S7.15.5 | Configuration switch: `DOCKER_ORCHESTRATION_MODE` | 📋 |
| S7.15.6 | Test both modes work | 📋 |

**Detailed Flow**:
```
STAGE 1 (Function App - raster-tasks queue):
┌─────────────────────────────────────────────────────────┐
│ handler_validate_and_trigger_docker(params):            │
│   1. validation = validate_raster(params)               │
│   2. response = http_post(docker_url + "/task/start",   │
│        {job_id, stage: 2, params: validated_params})    │
│   3. if response.status == 202:                         │
│        return {success: True}  # Stage 1 done           │
└─────────────────────────────────────────────────────────┘
                        │
                        ▼ HTTP POST
STAGE 2 (Docker - CoreMachine):
┌─────────────────────────────────────────────────────────┐
│ POST /task/start:                                       │
│   1. Create Stage 2 task record in DB                   │
│   2. Build TaskQueueMessage from HTTP payload           │
│   3. Spawn: CoreMachine.process_task_message(msg)       │
│   4. Return 202 Accepted immediately                    │
│                                                         │
│ Background thread:                                      │
│   - CoreMachine handles EVERYTHING:                     │
│     - Execute handler                                   │
│     - Update task status                                │
│     - Check stage completion (fan-in)                   │
│     - Advance job / complete job                        │
│   - Same code path as Service Bus trigger               │
└─────────────────────────────────────────────────────────┘
```

**Configuration**:
```bash
# Option A: Docker polls Service Bus (default)
DOCKER_ORCHESTRATION_MODE=service_bus

# Option B: Function App HTTP-triggers Docker
DOCKER_ORCHESTRATION_MODE=http_trigger
DOCKER_WORKER_URL=https://rmhheavyapi-xxx.azurewebsites.net
```

**Failure Handling**: Same as Function App - retries exhausted = job failed.
No special watchdog needed beyond existing job timeout logic.

**When to Implement**:
- After F7.13 Option A is working
- If Service Bus auth in Docker proves problematic
- As configuration option, not replacement

### Docker Execution Model Terminology (12 JAN 2026)

**Two Models - Clear Naming**:

| Model | Name | Trigger | Job Suffix | Use Case |
|-------|------|---------|------------|----------|
| **A** | **Queue-Polled** | Docker polls Service Bus | `*_docker` | Heavy ETL, hours-long |
| **B** | **Function-Triggered** | FA HTTP → Docker | `*_triggered` | FA as gatekeeper |

**Job Type Naming Convention**:
```
# QUEUE-POLLED (Docker polls queue, single stage)
process_raster_docker      # F7.13 - current implementation
process_vector_docker      # Future

# FUNCTION-TRIGGERED (FA triggers Docker, two stages)
process_raster_triggered   # F7.15 - FA validates → Docker ETL
process_vector_triggered   # F7.15 - FA validates → Docker ETL
```

**Common Abstraction for Function-Triggered Jobs**:
- `DockerTriggeredJobMixin` - standard 2-stage structure
- Stage 1 handler: `trigger_docker_task` (FA validates + POSTs to Docker)
- Stage 2: Docker creates task, runs CoreMachine in background
- Docker endpoint: `POST /task/start` returns 202 Accepted

**When to Use Which**:
| Scenario | Model |
|----------|-------|
| Tasks running hours (large rasters) | Queue-Polled |
| FA validation before Docker starts | Function-Triggered |
| Simpler Docker (no Service Bus) | Function-Triggered |
| High-volume parallel tasks | Queue-Polled |

---

## FY26 Priorities (ends 30 JUN 2026)

| Priority | Epic | Name | Status | Next Action |
|:--------:|------|------|--------|-------------|
| **1** | E9 | **FATHOM Rwanda Pipeline** | ✅ | Complete! Run fathom_stac_rebuild |
| **2** | E8 | **H3 Analytics (Rwanda)** | 🚧 | H3 bootstrap running (res 3-7) |
| **3** | E7 | **Unified Metadata Architecture** | ✅ | F7.8 complete (VectorMetadata) |
| **4** | E7→E2 | **RasterMetadata Architecture** | 🔴 | F7.9: CRITICAL - STAC depends on this |
| 5 | E8 | Building Flood Exposure | 📋 | F8.7: MS Buildings → FATHOM → H3 |
| 6 | E9 | Pre-prepared Raster Ingest | 📋 | F9.8: COG copy + STAC |
| 7 | E2 | Raster Data as API | 🚧 | F2.7: Collection Processing |
| 8 | E3 | DDH Platform Integration | 🚧 | F3.1: Validate Swagger UI |
| 9 | E1 | Vector Data as API | 🚧 | F1.8: ETL Style Integration |
| — | E7 | Pipeline Builder | 📋 | F7.5: Future (after concrete implementations) |

**Focus**: Rwanda as test region for all analytics pipelines before scaling.

---

## Current Sprint Focus

### 🟡 Priority 2: H3 Analytics on Rwanda

**Epic**: E8 GeoAnalytics Pipeline
**Goal**: H3 aggregation of FATHOM flood data for Rwanda
**Dependency**: F9.1 ✅ (FATHOM merged COGs exist in silver-fathom)
**Status**: H3 bootstrap running (08 JAN 2026)

#### F8.13: Rwanda H3 Aggregation

| Story | Description | Status |
|-------|-------------|--------|
| S8.13.1 | Seed Rwanda H3 cells (res 2-7, country-filtered) | 🔴 Stage 3 timeout |
| S8.13.1a | **Fix H3 finalize timeout** - pg_cron + autovacuum | ✅ Done (08 JAN) |
| S8.13.1b | Enable pg_cron extension in Azure Portal | 📋 |
| S8.13.1c | Run pg_cron_setup.sql on database | 📋 |
| S8.13.1d | Re-run H3 bootstrap (run_vacuum=False) | 📋 |
| S8.13.2 | Add FATHOM merged COGs to source_catalog | 📋 |
| S8.13.3 | Run H3 raster aggregation on Rwanda FATHOM | 📋 |
| S8.13.4 | Verify zonal_stats populated for flood themes | 📋 |
| S8.13.5 | Test H3 export endpoint with Rwanda data | 📋 |

**S8.13.1 Issue (08 JAN 2026)**: H3 bootstrap completed Stage 2 (114M cells inserted) but Stage 3 finalize timed out at 30 minutes. Root cause: `VACUUM ANALYZE h3.cells` on 114M rows exceeds Azure Functions timeout.

**S8.13.1a Fix (08 JAN 2026)**: Implemented pg_cron + autovacuum tuning solution:
- `services/table_maintenance.py` - Fire-and-forget VACUUM via pg_cron
- `sql/pg_cron_setup.sql` - pg_cron extension + autovacuum tuning SQL
- `handler_finalize_h3_pyramid.py` - Updated with `run_vacuum` param (default: False)
- `docs_claude/TABLE_MAINTENANCE.md` - Setup guide

See [TABLE_MAINTENANCE.md](./TABLE_MAINTENANCE.md) for pg_cron setup steps.

**H3 Theme Structure** (flood data):
```
themes:
  flood_risk:
    - fathom_fluvial_defended_2020_1in100
    - fathom_fluvial_defended_2050_ssp245_1in100
    - fathom_pluvial_defended_2020_1in100
    ...
```

**Key Files**:
- `services/h3_aggregation/` - Aggregation handlers
- `jobs/h3_raster_aggregation.py` - Main job
- `core/models/h3_sources.py` - source_catalog entries

---

### 🟢 Priority 3: Building Flood Exposure Pipeline

**Epic**: E8 GeoAnalytics Pipeline
**Goal**: Calculate % of buildings in flood risk areas, aggregated to H3 level 7
**Dependency**: F8.13 (H3 cells for Rwanda), F9.1 ✅ (FATHOM COGs)
**Data Source**: Microsoft Building Footprints (direct download)
**Initial Scenario**: `fluvial-defended-2020` (baseline)

#### Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ STAGE 1: Load MS Building Footprints                                │
│ Input: MS Buildings GeoJSON/Parquet for Rwanda                      │
│ Output: buildings.footprints (id, centroid, h3_index_7, iso3)      │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ STAGE 2: Sample FATHOM at Building Centroids                        │
│ Input: Building centroids + FATHOM COG (one scenario)              │
│ Output: buildings.flood_exposure (building_id, depth, is_flooded)  │
│ Binary: is_flooded = (flood_depth > 0)                             │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ STAGE 3: Aggregate to H3 Level 7                                    │
│ SQL: GROUP BY h3_index_7                                            │
│ Output: h3.building_flood_stats                                     │
│   - total_buildings, flooded_buildings, pct_flooded                │
└─────────────────────────────────────────────────────────────────────┘
```

#### F8.7: Building Flood Exposure Job

| Story | Description | Status |
|-------|-------------|--------|
| S8.7.1 | Download MS Building Footprints for Rwanda | 📋 |
| S8.7.2 | Create `buildings` schema (footprints, flood_exposure tables) | 📋 |
| S8.7.3 | Create `BuildingFloodExposureJob` definition (4-stage) | 📋 |
| S8.7.4 | Stage 1 handler: `building_load_footprints` (GeoJSON → PostGIS) | 📋 |
| S8.7.5 | Stage 2 handler: `building_assign_h3` (centroid → H3 index) | 📋 |
| S8.7.6 | Stage 3 handler: `building_sample_fathom` (point → raster value) | 📋 |
| S8.7.7 | Stage 4 handler: `building_aggregate_h3` (SQL aggregation) | 📋 |
| S8.7.8 | End-to-end test: Rwanda + fluvial-defended-2020 | 📋 |
| S8.7.9 | Expand to all FATHOM scenarios (39 for Rwanda) | 📋 |

**Data Source**: Microsoft Building Footprints
- Download: `https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv`
- Rwanda file: ~500K buildings expected
- Format: GeoJSON with polygon footprints

**Output Schema** (`h3.building_flood_stats`):
```sql
CREATE TABLE h3.building_flood_stats (
    h3_index BIGINT,
    scenario VARCHAR(100),        -- e.g., 'fluvial-defended-2020'
    total_buildings INT,
    flooded_buildings INT,
    pct_flooded DECIMAL(5,2),     -- 0.00 to 100.00
    PRIMARY KEY (h3_index, scenario)
);
```

**Key Files** (to create):
- `jobs/building_flood_exposure.py` - Job definition
- `services/building_exposure.py` - Handlers
- `infrastructure/buildings_schema.py` - Schema DDL
- `core/models/building.py` - Pydantic models

---

### ⚪ Future: Pipeline Builder (Low Priority)

**Epic**: E7 Pipeline Infrastructure
**Goal**: Generalize FATHOM pipeline to configuration-driven raster processing
**Timeline**: After FATHOM + H3 + Open Buildings working on Rwanda

#### F7.5: Pipeline Builder

| Story | Description | Status |
|-------|-------------|--------|
| S7.5.1 | Abstract FATHOM dimension parser to configuration | 📋 |
| S7.5.2 | Create `ComplexRasterPipeline` base class | 📋 |
| S7.5.3 | YAML/JSON pipeline definition schema | 📋 |
| S7.5.4 | Pipeline Builder UI (visual orchestration) | 📋 |

**Design Principle**: Build concrete implementations first (FATHOM, H3, Buildings), then extract patterns.

---

### 🟡 Priority 4: RasterMetadata Architecture (IN PROGRESS)

**Epic**: E7 Pipeline Infrastructure → E2 Raster Data as API
**Goal**: RasterMetadata model providing single source of truth for STAC-based raster catalogs
**Dependency**: F7.8 ✅ (BaseMetadata, VectorMetadata pattern established)
**Status**: Phase 1 Complete (09 JAN 2026) - Models, DDL, Repository
**Priority**: CRITICAL - Raster is primary STAC use case

#### F7.9: RasterMetadata Implementation

| Story | Description | Status |
|-------|-------------|--------|
| S7.9.1 | Create `RasterMetadata` class in `core/models/unified_metadata.py` | ✅ Done (09 JAN) |
| S7.9.2 | Create `app.cog_metadata` table DDL with typed columns | ✅ Done (09 JAN) |
| S7.9.3 | Create `RasterMetadataRepository` with CRUD operations | ✅ Done (09 JAN) |
| S7.9.4 | Implement `RasterMetadata.from_db_row()` factory method | ✅ Done (09 JAN) |
| S7.9.5 | Implement `RasterMetadata.to_stac_item()` conversion | ✅ Done (09 JAN) |
| S7.9.6 | Implement `RasterMetadata.to_stac_collection()` conversion | ✅ Done (09 JAN) |
| S7.9.7 | Refactor `service_stac_metadata.py` to use RasterMetadata | 📋 |
| S7.9.8 | Refactor `stac_catalog.py` to use RasterMetadata | 📋 |
| S7.9.9 | Wire raster ingest to populate app.cog_metadata | 📋 |
| S7.9.10 | Wire raster STAC handlers to upsert app.dataset_refs | 📋 |
| S7.9.11 | Update `fathom_stac_register` to use RasterMetadata | 📋 |
| S7.9.12 | Update `fathom_stac_rebuild` to use RasterMetadata | 📋 |

**Phase 1 Complete (09 JAN 2026)**:
- `RasterMetadata` class added to `core/models/unified_metadata.py`
- `CogMetadataRecord` model in `core/models/raster_metadata.py` for DDL
- DDL added to `sql_generator.py` (table + 5 indexes)
- `RasterMetadataRepository` in `infrastructure/raster_metadata_repository.py`
- Implements: from_db_row, to_stac_item, to_stac_collection

**Key Files**:
- `core/models/unified_metadata.py` - RasterMetadata domain model
- `core/models/raster_metadata.py` - CogMetadataRecord for DDL
- `core/schema/sql_generator.py` - Table/index generation
- `infrastructure/raster_metadata_repository.py` - CRUD operations

**RasterMetadata Fields** (beyond BaseMetadata):
```python
class RasterMetadata(BaseMetadata):
    # COG-specific fields
    cog_url: str                    # /vsiaz/ path or HTTPS URL
    container: str                  # Azure container name
    blob_path: str                  # Path within container

    # Raster properties
    width: int                      # Pixel width
    height: int                     # Pixel height
    band_count: int                 # Number of bands
    dtype: str                      # numpy dtype (uint8, int16, float32, etc.)
    nodata: Optional[float]         # NoData value
    crs: str                        # CRS as EPSG code or WKT
    transform: List[float]          # Affine transform (6 values)
    resolution: Tuple[float, float] # (x_res, y_res) in CRS units

    # Band metadata
    band_names: List[str]           # Band descriptions
    band_units: Optional[List[str]] # Units per band

    # Processing metadata
    is_cog: bool                    # Cloud-optimized GeoTIFF?
    overview_levels: List[int]      # COG overview levels
    compression: Optional[str]      # DEFLATE, LZW, etc.
    blocksize: Tuple[int, int]      # Internal tile size

    # Visualization defaults
    colormap: Optional[str]         # Default colormap name
    rescale_range: Optional[Tuple[float, float]]  # Default min/max

    # STAC extensions
    eo_bands: Optional[List[dict]]  # EO extension band metadata
    raster_bands: Optional[List[dict]]  # Raster extension metadata
```

**app.cog_metadata Table** (in existing app schema):
```sql
CREATE TABLE app.cog_metadata (
    -- Identity
    cog_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id TEXT NOT NULL,
    item_id TEXT NOT NULL UNIQUE,

    -- Location
    container TEXT NOT NULL,
    blob_path TEXT NOT NULL,
    cog_url TEXT NOT NULL,

    -- Spatial
    bbox DOUBLE PRECISION[4],
    geometry GEOMETRY(Polygon, 4326),
    crs TEXT NOT NULL DEFAULT 'EPSG:4326',

    -- Raster properties
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    band_count INTEGER NOT NULL,
    dtype TEXT NOT NULL,
    nodata DOUBLE PRECISION,
    resolution DOUBLE PRECISION[2],

    -- COG properties
    is_cog BOOLEAN DEFAULT true,
    compression TEXT,
    blocksize INTEGER[2],
    overview_levels INTEGER[],

    -- Metadata
    title TEXT,
    description TEXT,
    datetime TIMESTAMPTZ,
    start_datetime TIMESTAMPTZ,
    end_datetime TIMESTAMPTZ,

    -- Band metadata (JSONB for flexibility)
    band_names TEXT[],
    eo_bands JSONB,
    raster_bands JSONB,

    -- Visualization
    colormap TEXT,
    rescale_min DOUBLE PRECISION,
    rescale_max DOUBLE PRECISION,

    -- Extensibility
    providers JSONB,
    custom_properties JSONB,

    -- STAC linkage
    stac_item_id TEXT,
    stac_collection_id TEXT,

    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(container, blob_path)
);

-- Indexes
CREATE INDEX idx_cog_metadata_collection ON app.cog_metadata(collection_id);
CREATE INDEX idx_cog_metadata_bbox ON app.cog_metadata USING GIST(geometry);
CREATE INDEX idx_cog_metadata_datetime ON app.cog_metadata(datetime);
```

**Why Critical**:
1. STAC is primarily a raster catalog standard
2. Current raster STAC items built ad-hoc without metadata registry
3. FATHOM, DEM, satellite imagery all need consistent metadata
4. TiTiler integration requires predictable metadata structure
5. DDH linkage for rasters depends on this

**Current Gap**:
- VectorMetadata has `geo.table_metadata` as source of truth
- Raster has NO equivalent — STAC items built directly from COG headers
- No way to query "all rasters for DDH dataset X"
- No consistent visualization defaults stored

---

### 🚧 F7.11: STAC Catalog Self-Healing

**Epic**: E7 Pipeline Infrastructure
**Goal**: Job-based remediation for metadata consistency issues detected by F7.10
**Status**: 🚧 IN PROGRESS (vectors working, raster pending)
**Implemented**: 10 JAN 2026

#### Background

F7.10 Metadata Consistency timer runs every 6 hours and detects:
- Broken backlinks (table_metadata.stac_item_id → non-existent STAC item)
- Orphaned STAC items (no corresponding metadata record)
- Missing blob references

The timer *detects* issues but cannot *fix* them (would timeout on large repairs).
F7.11 provides a dedicated `rebuild_stac` job to remediate these issues.

#### Stories

| Story | Status | Description |
|-------|--------|-------------|
| S7.11.1 | ✅ Done | Create `jobs/rebuild_stac.py` - 2-stage job definition |
| S7.11.2 | ✅ Done | Create `services/rebuild_stac_handlers.py` - validate + rebuild handlers |
| S7.11.3 | ✅ Done | Register job and handlers in `__init__.py` files |
| S7.11.4 | ✅ Done | Add `force_recreate` mode (delete existing STAC before rebuild) |
| S7.11.5 | 📋 | Add raster support (rebuild from app.cog_metadata) |
| S7.11.6 | 📋 | Timer auto-submit (F7.10 detects → auto-submit rebuild job) |

#### Usage

```bash
# Rebuild STAC for specific vector tables
POST /api/jobs/submit/rebuild_stac
{
    "data_type": "vector",
    "items": ["curated_admin0", "system_ibat_kba"],
    "schema": "geo",
    "dry_run": false
}

# With force_recreate (deletes existing STAC item first)
POST /api/jobs/submit/rebuild_stac
{
    "data_type": "vector",
    "items": ["curated_admin0"],
    "schema": "geo",
    "dry_run": false,
    "force_recreate": true
}
```

#### Key Files

- `jobs/rebuild_stac.py` - RebuildStacJob class (227 lines)
- `services/rebuild_stac_handlers.py` - stac_rebuild_validate, stac_rebuild_item (367 lines)

#### Remaining Work

**S7.11.5 - Raster Support**:
- Currently returns "Raster rebuild not yet implemented"
- Needs to query `app.cog_metadata` for COG info
- Call existing `extract_stac_metadata` handler
- Depends on F7.9 (RasterMetadata) being complete

**S7.11.6 - Timer Auto-Submit**:
- Modify F7.10 timer to submit rebuild_stac job when issues detected
- Add threshold (only submit if >0 issues found)
- Add cooldown (don't re-submit if job already running)

---

## Other Active Work

### F7.16: Code Maintenance - db_maintenance.py Split

**Added**: 12 JAN 2026
**Completed**: 12 JAN 2026
**Status**: ✅ PHASE 1 COMPLETE
**Goal**: Split 2,673-line monolithic file into focused modules

| Story | Description | Status |
|-------|-------------|--------|
| S7.16.1 | Create `schema_operations.py` (~1,400 lines) | ⏳ Future |
| S7.16.2 | Create `data_cleanup.py` (~195 lines) | ✅ |
| S7.16.3 | Create `geo_table_operations.py` (~578 lines) | ✅ |
| S7.16.4 | Refactor `db_maintenance.py` to use delegates | ✅ |
| S7.16.5 | Update imports and verify no regressions | ✅ |

**Results**:
- `db_maintenance.py`: 2,673 → 1,922 lines (28% reduction)
- Extracted `data_cleanup.py`: 195 lines (cleanup + prerequisites)
- Extracted `geo_table_operations.py`: 578 lines (geo table management)
- Schema operations remain in db_maintenance.py (future extraction)

**Current Structure**:
```
triggers/admin/
├── db_maintenance.py          # Router + schema ops (1,922 lines)
├── data_cleanup.py            # Record cleanup (195 lines) NEW
└── geo_table_operations.py    # Geo table mgmt (578 lines) NEW
```

---

### F7.17: Additional Features (12 JAN 2026)

**Status**: ✅ COMPLETE
**Version**: 0.7.7.11

| Feature | Description | Status |
|---------|-------------|--------|
| Job Resubmit Endpoint | `POST /api/jobs/{job_id}/resubmit` - nuclear reset + resubmit | ✅ |
| Platform processing_mode | Route Platform raster to Docker via `processing_mode=docker` | ✅ |
| Env Validation Warnings | Separate errors from warnings (don't block Service Bus) | ✅ |
| PgStacRepository.delete_item | Delete STAC items for job resubmit cleanup | ✅ |
| JobRepository.delete_job | Delete job records for resubmit | ✅ |

**Job Resubmit Details** (`triggers/jobs/resubmit.py`):
- Dry run mode: preview cleanup without executing
- Cleanup: tasks, job record, PostGIS tables, STAC items
- Optionally delete blob artifacts (COGs)
- Force mode: resubmit even if job is processing

---

### E9: Large Data Hosting

| Feature | Description | Status |
|---------|-------------|--------|
| F9.1: FATHOM ETL | Band stacking + spatial merge | 🚧 Rwanda focus |
| F9.5: xarray Service | Time-series endpoints | ✅ Complete |
| F9.6: TiTiler Services | COG + Zarr tile serving | 🚧 TiTiler-xarray deployed 04 JAN |
| F9.8: Pre-prepared Ingest | COG copy + STAC from params | 📋 After Rwanda |

### E8: GeoAnalytics Pipeline

| Feature | Description | Status |
|---------|-------------|--------|
| F8.1-F8.3 | Grid infrastructure, bootstrap, raster aggregation | ✅ Complete |
| F8.8 | Source Catalog | ✅ Complete |
| F8.9 | H3 Export Pipeline | ✅ Complete |
| F8.13 | **Rwanda H3 Aggregation** | 📋 Priority 2 |
| F8.7 | **Building Exposure Pipeline** | 📋 Priority 3 |
| F8.4 | Vector→H3 Aggregation | 📋 After buildings |
| F8.5-F8.6 | GeoParquet, Analytics API | 📋 After Rwanda |

### E2: Raster Data as API

| Story | Description | Status |
|-------|-------------|--------|
| S2.2.5 | Fix TiTiler URLs for >3 band rasters | ✅ Complete (stac_metadata_helper.py bidx handling) |
| S2.2.6 | Auto-rescale DEM TiTiler URLs | ✅ Complete (04 JAN 2026, smart dtype defaults) |
| F2.9 | STAC-Integrated Raster Viewer | 📋 |

### E3: DDH Platform Integration

| Feature | Description | Status |
|---------|-------------|--------|
| F3.1 | API Docs (Swagger UI) | ✅ Deployed |
| F3.2 | Identity (DDH service principal) | 📋 |
| F3.3 | Environments (QA/UAT/Prod) | 📋 |

### E12: Interface Modernization

| Feature | Description | Status |
|---------|-------------|--------|
| F12.1-F12.3 | Cleanup, HTMX, Migration | ✅ Complete |
| F12.3.1 | DRY Consolidation (CSS/JS dedup) | ✅ Complete (09 JAN 2026) |
| SP12.9 | NiceGUI Evaluation Spike | ✅ Complete - **Not Pursuing** |
| F12.EN1 | Helper Enhancements | 📋 Planned |
| F12.4 | System Dashboard | 📋 Planned |
| F12.5 | Pipeline Workflow Hub | 📋 Planned |
| F12.6 | STAC & Raster Browser | 📋 Planned |
| F12.7 | OGC Features Browser | 📋 Planned |
| F12.8 | API Documentation Hub | 📋 Planned |

**SP12.9 Decision (09 JAN 2026)**: Evaluated NiceGUI and decided to stay with current HTMX + hardcoded JS/HTML/CSS approach. Rationale:
- NiceGUI requires persistent WebSocket connections → incompatible with Azure Functions
- Would require separate Docker deployment (Container Apps)
- Current approach is working well, simpler architecture, no additional infrastructure needed

---

## E4: Classification Enforcement & ADF Integration

**Added**: 07 JAN 2026
**Epic**: E4 Security Zones / Externalization
**Goal**: Make `access_level` (OUO/Public/Restricted) mandatory and prepare for ADF integration
**Context**: Colleague configuring ADF; we need Python side ready with correct parameters

### Background

Data classification (`access_level`) controls where data can be exported:
- **PUBLIC**: Can be copied to external-facing storage (ADF will handle this)
- **OUO** (Official Use Only): Internal only, ADF should reject export requests
- **RESTRICTED**: Highest restriction, no external access

Currently `access_level` is inconsistently enforced across the codebase. This work makes it:
1. **Mandatory** at Platform API entry point
2. **Type-safe** using `AccessLevel` enum throughout
3. **Fail-fast** in pipeline tasks if somehow missing

### Current State Analysis (07 JAN 2026)

| Location | Type | Default | Required | Issue |
|----------|------|---------|----------|-------|
| `PlatformRequest` | `str` | `"OUO"` | ✅ | Not using enum |
| `AccessLevel` enum | `Enum` | N/A | N/A | Exists but unused |
| Job parameter schemas | `str` | `None` | ❌ | Loses value |
| `PlatformMetadata` dataclass | `Optional[str]` | `None` | ❌ | Loses value |
| `PlatformProperties` model | `Optional[AccessLevel]` | `None` | ❌ | Uses enum but optional |

**Key Files**:
- `core/models/stac.py:57-62` - `AccessLevel` enum definition
- `core/models/platform.py:147-151` - `PlatformRequest.access_level` field
- `triggers/trigger_platform.py` - Translation functions
- `jobs/process_raster_v2.py:92` - Job parameter schema
- `jobs/raster_mixin.py:93-98` - `PLATFORM_PASSTHROUGH_SCHEMA`
- `services/stac_metadata_helper.py:69` - `PlatformMetadata` dataclass
- `infrastructure/data_factory.py` - ADF repository (ready for testing)

### Phase 1: Enforce at Platform Level

**Goal**: Reject requests with invalid/missing classification at API entry point

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S4.CL.1 | Update `PlatformRequest.access_level` to use `AccessLevel` enum | 📋 | `core/models/platform.py` |
| S4.CL.2 | Add Pydantic validator to normalize case (accept "OUO" → store as "ouo") | 📋 | `core/models/platform.py` |
| S4.CL.3 | Make `access_level` required (remove default) OR keep secure default "ouo" | 📋 | `core/models/platform.py` |
| S4.CL.4 | Update `_translate_to_coremachine()` to pass enum value (lowercase string) | 📋 | `triggers/trigger_platform.py` |
| S4.CL.5 | Add validation tests for Platform API rejection of invalid values | 📋 | `tests/` |

**Implementation Notes for S4.CL.1-3**:
```python
# core/models/platform.py - Change from:
access_level: str = Field(default="OUO", max_length=50, ...)

# To:
from core.models.stac import AccessLevel

access_level: AccessLevel = Field(
    default=AccessLevel.OUO,
    description="Data classification: public, ouo, restricted"
)

@field_validator('access_level', mode='before')
@classmethod
def normalize_access_level(cls, v):
    """Accept case-insensitive input, normalize to enum."""
    if isinstance(v, str):
        try:
            return AccessLevel(v.lower())
        except ValueError:
            raise ValueError(f"Invalid access_level '{v}'. Must be: public, ouo, restricted")
    return v
```

**Decision Point**: Keep `default=AccessLevel.OUO` (secure by default) or make truly required (no default). Recommend keeping default since OUO is the safe choice.

### Phase 2: Fail-Fast in Pipeline Tasks

**Goal**: Defense-in-depth - tasks fail immediately if access_level missing (shouldn't happen if Phase 1 works)

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S4.CL.6 | Add `access_level` to job schemas with `required: True` | 📋 | `jobs/raster_mixin.py`, `jobs/process_raster_v2.py`, `jobs/process_vector.py` |
| S4.CL.7 | Add validation in STAC metadata creation (fail if missing) | 📋 | `services/stac_metadata_helper.py` |
| S4.CL.8 | Add validation in promote handlers (data export tasks) | 📋 | `services/promote_service.py` |
| S4.CL.9 | Update `PlatformMetadata` dataclass to require access_level | 📋 | `services/stac_metadata_helper.py` |
| S4.CL.10 | Add checkpoints logging for access_level at key stages | 📋 | Various handlers |

**Implementation Notes for S4.CL.6**:
```python
# jobs/raster_mixin.py - Update PLATFORM_PASSTHROUGH_SCHEMA:
PLATFORM_PASSTHROUGH_SCHEMA = {
    'dataset_id': {'type': 'str', 'default': None},
    'resource_id': {'type': 'str', 'default': None},
    'version_id': {'type': 'str', 'default': None},
    'access_level': {
        'type': 'str',
        'required': True,  # Now required!
        'allowed': ['public', 'ouo', 'restricted']
    },
}
```

**Implementation Notes for S4.CL.7**:
```python
# services/stac_metadata_helper.py - Add validation in augment_item():
def augment_item(self, item_dict, ..., platform: Optional[PlatformMetadata] = None, ...):
    # Fail fast if platform metadata provided but access_level missing
    if platform and not platform.access_level:
        raise ValueError(
            "access_level is required for STAC item creation. "
            "This is a pipeline bug - access_level should be set at Platform API."
        )
```

### Phase 3: ADF Integration Testing

**Goal**: Verify Python can call ADF and pass classification parameter

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S4.ADF.1 | Create `/api/admin/adf/health` endpoint exposing health_check() | 📋 | `triggers/admin/` |
| S4.ADF.2 | Create `/api/admin/adf/pipelines` endpoint listing available pipelines | 📋 | `triggers/admin/` |
| S4.ADF.3 | Verify ADF env vars are set (`ADF_SUBSCRIPTION_ID`, `ADF_FACTORY_NAME`) | 📋 | Azure portal |
| S4.ADF.4 | Test trigger_pipeline() with simple test pipeline (colleague creates) | 📋 | Manual test |
| S4.ADF.5 | Add access_level to ADF pipeline parameters when triggering | 📋 | Future promote job |

**ADF Test Endpoint Implementation (S4.ADF.1-2)**:
```python
# triggers/admin/adf.py (new file)
from infrastructure.data_factory import get_data_factory_repository

def adf_health(req: func.HttpRequest) -> func.HttpResponse:
    """GET /api/admin/adf/health - Test ADF connectivity."""
    try:
        adf_repo = get_data_factory_repository()
        result = adf_repo.health_check()
        return func.HttpResponse(json.dumps(result), status_code=200, ...)
    except Exception as e:
        return func.HttpResponse(json.dumps({
            "status": "error",
            "error": str(e),
            "hint": "Check ADF_SUBSCRIPTION_ID, ADF_RESOURCE_GROUP, ADF_FACTORY_NAME env vars"
        }), status_code=500, ...)
```

### Testing Checklist

After implementation, verify:

- [ ] `POST /api/platform/submit` with `access_level: "INVALID"` returns 400
- [ ] `POST /api/platform/submit` with `access_level: "OUO"` (uppercase) succeeds
- [ ] `POST /api/platform/submit` with `access_level: "ouo"` (lowercase) succeeds
- [ ] `POST /api/platform/submit` without `access_level` uses default "ouo"
- [ ] STAC items have `platform:access_level` property populated
- [ ] Job parameters include `access_level` in task parameters
- [ ] `GET /api/admin/adf/health` returns ADF status (Phase 3)

### Acceptance Criteria

**Phase 1 Complete When**:
- Platform API validates and normalizes access_level on entry
- Invalid values rejected with clear error message
- Existing Platform API tests pass

**Phase 2 Complete When**:
- Pipeline tasks fail fast if access_level missing
- All STAC items have access_level in metadata
- Checkpoints logged at key stages

**Phase 3 Complete When**:
- ADF health endpoint working
- Can list pipelines from Python
- Ready to trigger actual export pipeline (pending ADF build)

---

## Reference Data Pipelines (Low Priority)

**Epic**: E7 Pipeline Infrastructure
**Goal**: Automated updates of reference datasets for spatial analysis
**Infrastructure**: Curated Datasets System (F7.1 ✅) - timer scheduler, 4-stage job, registry

### F7.2: IBAT Reference Data (Quarterly)

**Documentation**: [IBAT.md](/IBAT.md)
**Data Source**: IBAT Alliance API
**Auth**: `IBAT_AUTH_KEY` + `IBAT_AUTH_TOKEN`

| Story | Description | Status |
|-------|-------------|--------|
| S7.2.1 | IBAT base handler (shared auth) | ✅ Done |
| S7.2.2 | WDPA handler (protected areas, ~250K polygons) | ✅ Done |
| S7.2.3 | KBAs handler (Key Biodiversity Areas, ~16K polygons) | 📋 |
| S7.2.4 | Style integration (IUCN categories) | 📋 |
| S7.2.5 | Manual trigger endpoint | 📋 |

**Target Tables**: `geo.curated_wdpa_protected_areas`, `geo.curated_kbas`

### F7.6: ACLED Conflict Data (Twice Weekly)

**Documentation**: [ACLED.md](/ACLED.md)
**Data Source**: ACLED API
**Auth**: `ACLED_API_KEY` + `ACLED_EMAIL`
**Update Strategy**: `upsert` (incremental by event_id)

| Story | Description | Status |
|-------|-------------|--------|
| S7.6.1 | ACLED handler (API auth, pagination) | 📋 |
| S7.6.2 | Event data ETL (point geometry, conflict categories) | 📋 |
| S7.6.3 | Incremental updates (upsert vs full replace) | 📋 |
| S7.6.4 | Schedule config (Monday/Thursday timer) | 📋 |
| S7.6.5 | Style integration (conflict type symbology) | 📋 |

**Target Table**: `geo.curated_acled_events`

### F7.7: Static Reference Data (Manual)

| Story | Description | Status |
|-------|-------------|--------|
| S7.7.1 | Admin0 handler (Natural Earth countries) | 📋 |
| S7.7.2 | Admin1 handler (states/provinces) | 📋 |

**Target Tables**: `geo.curated_admin0`, `geo.curated_admin1`

---

## DevOps / Non-Geospatial Tasks

Tasks suitable for a colleague with Azure/Python/pipeline expertise but without geospatial domain knowledge.

### Ready Now (No Geospatial Knowledge Required)

| Task | Epic | Description | Skills Needed |
|------|------|-------------|---------------|
| S9.2.2 | E9 | Create DDH service principal | Azure AD, IAM |
| S9.2.3 | E9 | Grant blob read access | Azure RBAC |
| EN6.1 | EN6 | Docker image with GDAL/rasterio | Docker, Python |
| EN6.2 | EN6 | Container deployment | Azure, DevOps |
| F7.2.1 | E7 | Create ADF instance | Azure Data Factory |

---

## Recently Completed

| Date | Item | Epic |
|------|------|------|
| 12 JAN 2026 | **F7.17 Job Resubmit + Features** - `/api/jobs/{job_id}/resubmit` endpoint, env validation fix | E7 |
| 12 JAN 2026 | **F7.16 db_maintenance.py Split** - Phase 1 complete (28% reduction, 2 modules extracted) | E7 |
| 11 JAN 2026 | **F7.12 Docker OpenTelemetry** - Docker worker logs to App Insights (v0.7.8-otel) | E7 |
| 11 JAN 2026 | **F7.12 Docker Worker Infrastructure** - Deployed to rmhheavyapi | E7 |
| 10 JAN 2026 | **F7.12 Logging Architecture** - Flag consolidation, global log context | E7 |
| 09 JAN 2026 | **F7.8 Unified Metadata Architecture** - VectorMetadata pattern (→ HISTORY.md) | E7 |
| 09 JAN 2026 | **F12.5 DRY Consolidation** - CSS/JS deduplication (→ HISTORY.md) | E12 |
| 08 JAN 2026 | pg_cron + autovacuum for H3 VACUUM | E8 |
| 07 JAN 2026 | **F9.1 FATHOM Rwanda Pipeline COMPLETE** (→ HISTORY.md) | E9 |
| 06 JAN 2026 | **System Diagnostics & Drift Detection** (→ HISTORY.md) | — |
| 05 JAN 2026 | **Thread-safety fix for BlobRepository** (→ HISTORY.md) | — |

*For full details on items marked (→ HISTORY.md), see [HISTORY.md](./HISTORY.md)*

---

## Quick Links

| Document | Purpose |
|----------|---------|
| [FATHOM_ETL.md](./FATHOM_ETL.md) | FATHOM flood data pipeline |
| [H3_REVIEW.md](./H3_REVIEW.md) | H3 aggregation implementation |
| [TABLE_MAINTENANCE.md](./TABLE_MAINTENANCE.md) | pg_cron + autovacuum setup |
| [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) | Technical patterns |
| [docs/epics/README.md](/docs/epics/README.md) | Master Epic/Feature/Story definitions |

---

---

## F7.12: Logging Architecture Consolidation (10 JAN 2026)

**Epic**: E7 Pipeline Infrastructure
**Goal**: Eliminate duplicate debug flags, unify diagnostics, add global log context for multi-app filtering
**Priority**: HIGH - Duplicate flags are accumulating and causing confusion
**Status**: ✅ COMPLETE (Function App + Docker Worker both logging to App Insights)

### Background

Systematic review (10 JAN 2026) identified significant issues in logging/metrics infrastructure:

1. **Duplicate Debug Flags** - Multiple env vars controlling similar behavior
2. **No Global App/Instance ID** - Can't filter logs by app in multi-app deployment
3. **Duplicate Diagnostics Code** - `diagnostics.py` and `health.py` overlap
4. **Unclear Metrics Systems** - Three different metrics systems with unclear purposes

### Current State (Problems)

**Duplicate Debug Flags**:
| Env Var | Used By | Purpose |
|---------|---------|---------|
| `DEBUG_MODE` | util_logger.py | Memory/CPU checkpoints, runtime environment |
| `DEBUG_LOGGING` | util_logger.py | Log level DEBUG vs INFO |
| `METRICS_DEBUG_MODE` | service_latency.py, metrics_blob_logger.py | Service latency tracking + blob dumps |
| `METRICS_ENABLED` | metrics_config.py, metrics_repository.py | ETL job progress to PostgreSQL |

**Problem**: 4 different boolean flags for debug/metrics behavior. Very confusing!

**Missing App/Instance Context**:
- `util_logger.py` gathers `WEBSITE_INSTANCE_ID` but only logs it in debug checkpoints
- `service_latency.py` logs to App Insights WITHOUT instance/app identification
- In multi-app deployment (ETL + Reader + Docker workers), can't filter logs by source

**Duplicate Code**:
- `infrastructure/diagnostics.py` - DNS checks, connectivity checks, instance info
- `triggers/health.py` - Also does connectivity checks, instance info
- `util_logger.py:get_runtime_environment()` - Also gathers instance info

### F7.12.A: Global Log Context ✅ COMPLETE

**Goal**: Every log line includes app_name and instance_id for multi-app filtering

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S7.12.A.1 | Add `LOG_CONTEXT_APP_NAME` and `LOG_CONTEXT_INSTANCE_ID` to LoggerFactory | ✅ | `util_logger.py` |
| S7.12.A.2 | Modify `create_logger()` to inject app/instance into every log | ✅ | `util_logger.py` |
| S7.12.A.3 | Update `service_latency.py` to use LoggerFactory with context | ✅ | `infrastructure/service_latency.py` |
| S7.12.A.4 | Update `metrics_blob_logger.py` to include app_name in blob path | ✅ | `infrastructure/metrics_blob_logger.py` |
| S7.12.A.5 | Add `environment` (dev/qa/prod) to log context | ✅ | `util_logger.py` |
| S7.12.A.6 | Document log filtering patterns for multi-app deployment | ✅ | `docs/wiki/WIKI_ENVIRONMENT_VARIABLES.md` |

**Implementation for S7.12.A.1-2**:
```python
# util_logger.py - Module-level context (loaded once at import)
import os

# Global log context - every log gets these fields
_GLOBAL_LOG_CONTEXT = {
    "app_name": os.environ.get("APP_NAME", "unknown"),
    "app_instance": os.environ.get("WEBSITE_INSTANCE_ID", "local")[:16],
    "environment": os.environ.get("ENVIRONMENT", "dev"),
}

# In create_logger() wrapper:
def log_with_context(level, msg, args, exc_info=None, extra=None, ...):
    if extra is None:
        extra = {}

    custom_dims = {
        **_GLOBAL_LOG_CONTEXT,  # Always include app/instance
        'component_type': component_type.value,
        'component_name': name
    }
    # ... rest of existing code
```

**KQL Query (after implementation)**:
```kusto
// Filter logs by app in multi-app deployment
traces
| where customDimensions.app_name == "rmhazuregeoapi"
| where customDimensions.app_instance == "abc123"
| where timestamp >= ago(1h)
| order by timestamp desc
```

### F7.12.B: Unify Diagnostics Module ⏭️ SKIPPED

**Goal**: Single source of truth for connectivity/DNS/instance checks

**Decision (10 JAN 2026)**: Reviewed existing structure - determined current organization is clean enough. `infrastructure/diagnostics.py` already handles diagnostics, `triggers/health.py` delegates appropriately. No refactor needed at this time.

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S7.12.B.1-7 | Diagnostics module refactor | ⏭️ SKIPPED | Existing structure adequate |

**Target Structure**:
```
infrastructure/
  diagnostics/
    __init__.py           # Unified API: get_diagnostics(), check_connectivity(), etc.
    connectivity.py       # Database, storage, Service Bus connectivity checks
    dns.py                # DNS resolution timing
    instance.py           # Instance ID, cold start, Azure env vars
    pools.py              # Connection pool statistics
    network.py            # VNet, private IP, outbound IP

infrastructure/diagnostics.py  # DEPRECATED - thin wrapper over diagnostics/
triggers/health.py             # Delegates to infrastructure/diagnostics/
util_logger.py                 # Delegates to infrastructure/diagnostics/instance.py
```

### F7.12.C: Consolidate Debug Flags ✅ COMPLETE

**Goal**: Reduce 4 flags to 2 clear flags with distinct purposes

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S7.12.C.1 | Document current flag behavior and decide consolidation strategy | ✅ | This doc |
| S7.12.C.2 | Implement flag consolidation (see strategy below) | ✅ | `config/observability_config.py` |
| S7.12.C.3 | Update all usages to use new consolidated flags | ✅ | Multiple files |
| S7.12.C.4 | Add deprecation warnings for old flag names | ✅ | Backward compat in observability_config.py |
| S7.12.C.5 | Update WIKI_ENVIRONMENT_VARIABLES.md with new flag structure | ✅ | `docs/wiki/` |
| S7.12.C.6 | Update startup_state.py ENV_VARS_WITH_DEFAULTS | ✅ | `startup_state.py` |

**Consolidation Strategy**:

| Current Flag | Behavior | New Flag | New Behavior |
|--------------|----------|----------|--------------|
| `DEBUG_MODE` | Memory/CPU checkpoints | `OBSERVABILITY_MODE` | All debug diagnostics (memory, CPU, DB stats) |
| `DEBUG_LOGGING` | Log level DEBUG | `LOG_LEVEL=DEBUG` | Already exists! Remove DEBUG_LOGGING |
| `METRICS_DEBUG_MODE` | Service latency + blob dumps | `OBSERVABILITY_MODE` | Merge into single flag |
| `METRICS_ENABLED` | ETL job progress to PostgreSQL | `METRICS_ENABLED` | Keep - different purpose (dashboards) |

**Result: 2 flags instead of 4**:
- `OBSERVABILITY_MODE=true` → Memory checkpoints, service latency, blob dumps, database stats
- `METRICS_ENABLED=true` → ETL job progress to PostgreSQL (for dashboards)

**Implementation for S7.12.C.2**:
```python
# config/__init__.py - Add unified observability flag
class Config:
    @property
    def observability_mode(self) -> bool:
        """Master switch for debug diagnostics (memory, latency, blob dumps)."""
        # Check new name first, fall back to old names for backward compat
        if os.environ.get("OBSERVABILITY_MODE"):
            return os.environ.get("OBSERVABILITY_MODE", "false").lower() == "true"
        # Backward compat: any old flag enables observability
        return (
            os.environ.get("DEBUG_MODE", "false").lower() == "true" or
            os.environ.get("METRICS_DEBUG_MODE", "false").lower() == "true"
        )
```

### F7.12.D: Python App Insights Log Export ✅ COMPLETE

**Goal**: On-demand export of App Insights logs to blob storage via Python endpoint

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S7.12.D.1 | Create `infrastructure/appinsights_exporter.py` with REST API client | ✅ | `infrastructure/appinsights_exporter.py` |
| S7.12.D.2 | Implement `query_logs(query: str, hours: int)` method | ✅ | `appinsights_exporter.py` |
| S7.12.D.3 | Implement `export_to_blob(query, hours, container, blob_name)` method | ✅ | `appinsights_exporter.py` |
| S7.12.D.4 | Add `POST /api/appinsights/export` endpoint | ✅ | `triggers/probes.py` |
| S7.12.D.5 | Add `POST /api/appinsights/query` endpoint for quick queries | ✅ | `triggers/probes.py` |
| S7.12.D.6 | Document usage and KQL templates | ✅ | `docs/wiki/WIKI_API_HEALTH.md` |

**Note**: App Insights REST API query endpoints require Monitoring Reader RBAC role (optional - see WIKI for setup).

### F7.12.E: Docker Worker OpenTelemetry ✅ COMPLETE (11 JAN 2026)

**Goal**: Docker worker logs to same Application Insights as Function App

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S7.12.E.1 | Add `azure-monitor-opentelemetry>=1.6.0` to requirements-docker.txt | ✅ | `requirements-docker.txt` |
| S7.12.E.2 | Configure OpenTelemetry in `workers_entrance.py` BEFORE FastAPI import | ✅ | `workers_entrance.py` |
| S7.12.E.3 | Configure OpenTelemetry in `docker_main.py` for queue polling | ✅ | `docker_main.py` |
| S7.12.E.4 | Build and push to ACR (v0.7.8-otel) | ✅ | ACR |
| S7.12.E.5 | Deploy to rmhheavyapi and verify telemetry transmission | ✅ | Azure Web App |

**Result**: Docker worker and Function App both log to Application Insights with cross-app correlation via `cloud_RoleName`:
```kql
traces
| where cloud_RoleName in ("rmhazuregeoapi", "docker-worker-azure")
| project timestamp, cloud_RoleName, message
| order by timestamp desc
```

**Key Files**:
- `requirements-docker.txt` - Added `azure-monitor-opentelemetry>=1.6.0`
- `workers_entrance.py` - `configure_azure_monitor_telemetry()` called before FastAPI
- `docker_main.py` - `_configure_azure_monitor()` called early in startup

**Environment Variables for Docker**:
```bash
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=xxx;...
APP_NAME=docker-worker-azure
ENVIRONMENT=dev
```

**Implementation for S7.12.D.1-3** (`infrastructure/appinsights_export.py`):
```python
"""
App Insights Log Export.

Query Application Insights via REST API and export results to blob storage.
Uses same auth pattern as documented in APPLICATION_INSIGHTS.md.
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from azure.identity import DefaultAzureCredential
import requests


class AppInsightsExporter:
    """Export App Insights logs to blob storage."""

    def __init__(self):
        self.app_id = os.environ.get("APPINSIGHTS_APP_ID")  # From Azure portal
        self.api_endpoint = f"https://api.applicationinsights.io/v1/apps/{self.app_id}/query"
        self._credential = None

    def _get_token(self) -> str:
        """Get bearer token for App Insights API."""
        if self._credential is None:
            self._credential = DefaultAzureCredential()
        token = self._credential.get_token("https://api.applicationinsights.io/.default")
        return token.token

    def query_logs(
        self,
        query: str,
        timespan: str = "PT24H"  # ISO 8601 duration (24 hours default)
    ) -> List[Dict[str, Any]]:
        """
        Query App Insights and return results.

        Args:
            query: KQL query string
            timespan: ISO 8601 duration (PT1H, PT24H, P7D, etc.)

        Returns:
            List of result rows as dicts
        """
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json"
        }

        response = requests.post(
            self.api_endpoint,
            headers=headers,
            json={"query": query, "timespan": timespan}
        )
        response.raise_for_status()

        data = response.json()

        # Convert to list of dicts
        if "tables" not in data or not data["tables"]:
            return []

        table = data["tables"][0]
        columns = [col["name"] for col in table["columns"]]

        return [dict(zip(columns, row)) for row in table["rows"]]

    def export_to_blob(
        self,
        query: str,
        container: str = "applogs",
        blob_prefix: str = "exports",
        timespan: str = "PT24H"
    ) -> Dict[str, Any]:
        """
        Query App Insights and export results to blob storage.

        Args:
            query: KQL query string
            container: Blob container name
            blob_prefix: Prefix for blob path
            timespan: ISO 8601 duration

        Returns:
            Dict with export status, row count, blob path
        """
        from infrastructure.blob import BlobRepository

        # Query logs
        rows = self.query_logs(query, timespan)

        if not rows:
            return {"status": "empty", "row_count": 0, "blob_path": None}

        # Generate blob name
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        blob_name = f"{blob_prefix}/{timestamp}.jsonl"

        # Write as JSON Lines
        content = "\n".join(json.dumps(row, default=str) for row in rows)

        # Upload to blob
        blob_repo = BlobRepository()
        blob_repo.upload_blob(
            container_name=container,
            blob_name=blob_name,
            data=content.encode("utf-8"),
            overwrite=True
        )

        return {
            "status": "exported",
            "row_count": len(rows),
            "blob_path": f"{container}/{blob_name}",
            "timespan": timespan
        }
```

**API Endpoint (S7.12.D.4)**:
```python
# triggers/probes.py or new file

@bp.route(
    route="logs/export",
    methods=["POST"],
    auth_level=func.AuthLevel.ANONYMOUS
)
def logs_export(req: func.HttpRequest) -> func.HttpResponse:
    """
    Export App Insights logs to blob storage.

    POST /api/logs/export
    {
        "query": "traces | where timestamp >= ago(1h) | take 1000",
        "timespan": "PT1H",
        "container": "applogs",
        "blob_prefix": "exports/service-logs"
    }

    Returns:
        200: {"status": "exported", "row_count": 1000, "blob_path": "applogs/exports/..."}
    """
    try:
        body = req.get_json()
        query = body.get("query", "traces | where timestamp >= ago(1h) | take 1000")
        timespan = body.get("timespan", "PT1H")
        container = body.get("container", "applogs")
        blob_prefix = body.get("blob_prefix", "exports")

        from infrastructure.appinsights_export import AppInsightsExporter
        exporter = AppInsightsExporter()

        result = exporter.export_to_blob(
            query=query,
            container=container,
            blob_prefix=blob_prefix,
            timespan=timespan
        )

        return func.HttpResponse(
            json.dumps(result, indent=2),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        return func.HttpResponse(
            json.dumps({"status": "error", "error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )
```

**Required Env Var**:
```
APPINSIGHTS_APP_ID=d3af3d37-cfe3-411f-adef-bc540181cbca  # From Azure portal
```

### Implementation Order

1. **F7.12.C (Consolidate Flags)** - FIRST - Reduces confusion before other changes
2. **F7.12.A (Global Log Context)** - SECOND - Enables multi-app log filtering
3. **F7.12.B (Unify Diagnostics)** - THIRD - Clean up code duplication
4. **F7.12.D (App Insights Export)** - FOURTH - Nice-to-have for QA debugging

### Acceptance Criteria

**F7.12.C Complete When**:
- Only 2 debug flags: `OBSERVABILITY_MODE` and `METRICS_ENABLED`
- Old flags still work (backward compat) but log deprecation warning
- Documentation updated

**F7.12.A Complete When**:
- Every log line has `app_name`, `app_instance`, `environment`
- KQL queries can filter by app
- Documentation includes multi-app filtering examples

**F7.12.B Complete When**:
- Single `infrastructure/diagnostics/` module for all checks
- No duplicate DNS/connectivity/instance code
- health.py delegates to diagnostics module

**F7.12.D Complete When**:
- `POST /api/logs/export` endpoint works
- Exports to `applogs` container in silver storage
- Documentation includes usage examples

### Testing Checklist

- [ ] Set `OBSERVABILITY_MODE=true`, verify memory checkpoints + service latency work
- [ ] Set old `DEBUG_MODE=true`, verify backward compat + deprecation warning
- [ ] Verify logs include `app_name`, `app_instance` in customDimensions
- [ ] Run KQL query filtering by app_name
- [ ] Call `/api/logs/export`, verify blob created with log data
- [ ] Health endpoint still works after diagnostics refactor

---

### F7.12.F: JSONL Log Dump System (IMPLEMENTED)

**Added**: 11 JAN 2026
**Implemented**: 11 JAN 2026
**Goal**: Granular control over JSONL log exports with level-based filtering
**Status**: ✅ IMPLEMENTED

**Concept**: Separate JSONL exports based on observability mode and log level:

| Mode | What Gets Exported | Blob Path |
|------|-------------------|-----------|
| `OBSERVABILITY_MODE=true` | Janitor/timer logs + WARNING+ from everywhere | `applogs/logs/default/` |
| `OBSERVABILITY_MODE=true` + `VERBOSE_LOG_DUMP=true` | ALL logs including DEBUG | `applogs/logs/verbose/` |
| Log cleanup timer | Delete old logs based on retention | Daily at 3 AM UTC |

**Environment Variables**:
```bash
OBSERVABILITY_MODE=true           # Master switch for observability features
VERBOSE_LOG_DUMP=true             # When combined with OBSERVABILITY_MODE, dump ALL logs
JSONL_DEBUG_RETENTION_DAYS=7      # Days to keep verbose/debug logs
JSONL_WARNING_RETENTION_DAYS=30   # Days to keep warning+ logs
JSONL_METRICS_RETENTION_DAYS=14   # Days to keep metrics logs
JSONL_LOG_CONTAINER=applogs       # Blob container name (default: applogs)
JSONL_FLUSH_INTERVAL=60           # Seconds between flushes (default: 60)
JSONL_BUFFER_SIZE=100             # Max records before flush (default: 100)
```

**Stories**:

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S7.12.F.1 | Define unified observability schema (logger/metrics/diagnostics) | ✅ | Research complete |
| S7.12.F.2 | Create `JSONLBlobHandler` class extending logging.Handler | ✅ | `infrastructure/jsonl_log_handler.py` |
| S7.12.F.3 | Add level-based routing (WARNING+ vs ALL based on env vars) | ✅ | `infrastructure/jsonl_log_handler.py` |
| S7.12.F.4 | Integrate with LoggerFactory for automatic blob export | ✅ | `util_logger.py` |
| S7.12.F.5 | Implement log cleanup timer logic | ✅ | `triggers/admin/log_cleanup_timer.py` |
| S7.12.F.6 | Register log cleanup timer in function_app.py | ✅ | `function_app.py` |

**Blob Structure**:
```
applogs/
├── logs/
│   ├── default/          # WARNING+ always (OBSERVABILITY_MODE=true)
│   │   └── 2026-01-12/
│   │       └── instance123/
│   │           └── 1705012345.jsonl
│   └── verbose/          # ALL logs (VERBOSE_LOG_DUMP=true)
│       └── 2026-01-12/
│           └── instance123/
│               └── 1705012345.jsonl
└── service-metrics/      # Existing service latency metrics
    └── 2026-01-12/
        └── ...
```

**Manual Trigger**:
```bash
# Trigger log cleanup manually
curl -X POST "https://.../api/cleanup/run?type=log_cleanup"
```

**Schema Standardization Research** (11 JAN 2026):

Comparison of current observability tools identified these standardization needs:

| Issue | Current State | Recommendation |
|-------|--------------|----------------|
| Environment tag | Only in util_logger | Add to blob_logger, db_health |
| Correlation ID | LogContext only | Add to MetricRecord, diagnostics |
| Instance tracking | Inconsistent (16 vs 32 char) | Standardize on 16 char |
| Status vocabulary | 3 different enums | Unify: success/warning/error/critical |
| Metrics structure | Flat vs nested | Create standard `metrics` object |

**Key Files**:
- `infrastructure/jsonl_log_handler.py` - JSONL blob handler (created 11 JAN 2026)
- `triggers/admin/log_cleanup_timer.py` - Cleanup timer (implemented 11 JAN 2026)
- `config/observability_config.py` - Updated with retention settings
- `util_logger.py` - Integrated JSONLBlobHandler into LoggerFactory

---

**Workflow**:
1. ~~Complete Rwanda FATHOM pipeline (Priority 1)~~ ✅ DONE
2. Run H3 aggregation on FATHOM outputs (Priority 2) - 🚧 H3 bootstrap running
3. Building flood exposure pipeline: MS Buildings → FATHOM sample → H3 aggregation (Priority 3)
4. Generalize to Pipeline Builder (Future)
