# Pipeline UI Architecture

**Created**: 06 JAN 2026
**Status**: Proposal - Pending Implementation
**Authors**: Robert and Claude

---

## Overview

This document captures the design for a unified Pipeline Monitoring Dashboard that abstracts ETL pipeline monitoring across different job types (FATHOM, raster, vector, etc.).

---

## Problem Statement

### Current State
- `/api/interface/tasks?job_id=X` - Workflow Monitor for individual jobs
- Shows: stages, tasks, progress bars, processing rate, peak memory
- Data source: `app.jobs` + `app.tasks` tables
- Works for any job type but lacks pipeline-level aggregate stats

### FATHOM Requirements
Complex ETL pipelines like FATHOM need:
- **Cross-job visibility**: Multiple jobs contribute to the same pipeline
- **File-level tracking**: 12,000+ source files through multi-phase processing
- **Phase progress**: Phase 1 (Band Stack) vs Phase 2 (Spatial Merge)
- **Dimensional breakdown**: By region, flood type, defense scenario, year
- **Long-running monitoring**: Jobs run for hours to days

### Key Insight: Two Levels of Monitoring

```
┌─────────────────────────────────────────────────────────────────┐
│                    Two Levels of Monitoring                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  PIPELINE LEVEL (new)              JOB LEVEL (existing)         │
│  ┌─────────────────────┐           ┌─────────────────────┐      │
│  │ FATHOM Pipeline     │           │ Job: abc123         │      │
│  │                     │           │                     │      │
│  │ Total: 12,450 files │──────────▶│ Stage 2: Band Stack │      │
│  │ Phase 1: 66% done   │           │ Tasks: 45/128       │      │
│  │ Phase 2: 33% done   │           │ Rate: 42/hr         │      │
│  │                     │           │ Memory: 2.3 GB      │      │
│  │ Active Jobs: 3      │           │                     │      │
│  └─────────────────────┘           └─────────────────────┘      │
│                                                                  │
│  Data: etl_source_files            Data: jobs + tasks           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Design Decision: Abstract vs Specific

**Question**: Build a FATHOM-specific UI or abstract for all pipelines?

**Decision**: **Abstract approach** - One unified pipeline monitor that adapts based on pipeline type.

**Rationale**:
- Reusable for future ETL types (raster_v2, vector)
- Consistent UI patterns across all pipelines
- Graceful degradation for simple jobs
- Single codebase to maintain

---

## Proposed Architecture

### 1. Pipeline Registry

New configuration file that declares pipeline metadata:

```python
# config/pipelines.py
PIPELINE_REGISTRY = {
    "fathom": {
        "name": "FATHOM Flood Data",
        "description": "Global flood hazard data processing",
        "etl_type": "fathom",  # Links to etl_source_files.etl_type
        "job_types": [
            "process_fathom_stack",
            "process_fathom_merge",
            "inventory_fathom_container"
        ],
        "phases": [
            {
                "id": "phase1",
                "name": "Band Stack",
                "completed_field": "phase1_completed_at",
                "description": "Stack 8 return period TIFFs into multi-band COG"
            },
            {
                "id": "phase2",
                "name": "Spatial Merge",
                "completed_field": "phase2_completed_at",
                "description": "Merge N×N tiles into larger grid cells"
            }
        ],
        "groupings": [
            {"field": "region", "label": "Region", "from": "source_metadata"},
            {"field": "flood_type", "label": "Flood Type", "from": "source_metadata"},
            {"field": "defense", "label": "Defense", "from": "source_metadata"},
            {"field": "year", "label": "Year", "from": "source_metadata"}
        ],
        "submit_actions": [
            {"job_type": "inventory_fathom_container", "label": "Run Inventory", "icon": "📋"},
            {"job_type": "process_fathom_stack", "label": "Submit Phase 1", "icon": "📦"},
            {"job_type": "process_fathom_merge", "label": "Submit Phase 2", "icon": "🔗"}
        ]
    },
    "raster_v2": {
        "name": "Raster Processing",
        "description": "General raster to COG conversion",
        "etl_type": "raster_v2",  # Future
        "job_types": ["process_raster_v2", "process_large_raster_v2"],
        "phases": [
            {"id": "phase1", "name": "COG Convert", "completed_field": "phase1_completed_at"}
        ],
        "groupings": []
    }
    # Simple jobs with no ETL tracking = no pipeline entry
    # They still work in job-level monitor, just no aggregate stats
}
```

### 2. Generic ETL Stats API

New endpoint that returns stats from `etl_source_files` for any registered ETL type:

```
GET /api/etl/stats?etl_type=fathom&region=CI
```

**Response:**
```json
{
  "etl_type": "fathom",
  "pipeline": {
    "name": "FATHOM Flood Data",
    "description": "Global flood hazard data processing"
  },
  "summary": {
    "total_files": 12450,
    "total_size_bytes": 2400000000000,
    "total_size_formatted": "2.4 TB"
  },
  "phases": {
    "phase1": {
      "name": "Band Stack",
      "pending": 4216,
      "completed": 8234,
      "failed": 76,
      "percent_complete": 66.1
    },
    "phase2": {
      "name": "Spatial Merge",
      "eligible": 3100,
      "completed": 4100,
      "failed": 40,
      "percent_complete": 32.9
    }
  },
  "by_grouping": {
    "region": {
      "CI": {"total": 2560, "phase1_done": 2560, "phase2_done": 1024},
      "GH": {"total": 4096, "phase1_done": 3200, "phase2_done": 512}
    },
    "flood_type": {
      "fluvial": {"total": 5600, "phase1_done": 4200},
      "pluvial": {"total": 4350, "phase1_done": 2800},
      "coastal": {"total": 2500, "phase1_done": 1234}
    }
  },
  "active_jobs": [
    {
      "job_id": "abc123...",
      "job_type": "process_fathom_stack",
      "status": "processing",
      "stage": 2,
      "task_counts": {"completed": 45, "processing": 3, "pending": 80}
    }
  ],
  "processing_rate": {
    "phase1_per_hour": 80,
    "phase2_per_hour": 37,
    "eta_hours": 93
  },
  "timestamp": "2026-01-06T12:00:00Z"
}
```

**SQL Queries:**
```sql
-- Summary counts
SELECT
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE phase1_completed_at IS NULL) as phase1_pending,
    COUNT(*) FILTER (WHERE phase1_completed_at IS NOT NULL) as phase1_done,
    COUNT(*) FILTER (WHERE phase1_completed_at IS NOT NULL
                     AND phase2_completed_at IS NULL) as phase2_eligible,
    COUNT(*) FILTER (WHERE phase2_completed_at IS NOT NULL) as phase2_done,
    SUM(file_size_bytes) as total_bytes
FROM app.etl_source_files
WHERE etl_type = 'fathom';

-- By grouping (region example)
SELECT
    source_metadata->>'region' as region,
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE phase1_completed_at IS NOT NULL) as phase1_done,
    COUNT(*) FILTER (WHERE phase2_completed_at IS NOT NULL) as phase2_done
FROM app.etl_source_files
WHERE etl_type = 'fathom'
GROUP BY source_metadata->>'region';

-- Processing rate (last hour)
SELECT
    COUNT(*) FILTER (WHERE phase1_completed_at > NOW() - INTERVAL '1 hour') as phase1_last_hour,
    COUNT(*) FILTER (WHERE phase2_completed_at > NOW() - INTERVAL '1 hour') as phase2_last_hour
FROM app.etl_source_files
WHERE etl_type = 'fathom';
```

### 3. Unified Pipeline Monitor Interface

**Route:** `/api/interface/pipeline?type=fathom`

One interface that adapts based on pipeline type:

| Pipeline Type | What's Shown |
|--------------|--------------|
| `fathom` | Full dashboard: phases, regions, scenarios, file counts |
| `raster_v2` | Simpler: phase progress, file counts |
| (none/invalid) | Pipeline selector or "not found" message |

### 4. Enhanced Job Monitor Integration

The existing `/api/interface/tasks?job_id=X` should:
- Detect if job is part of a registered pipeline
- Show "View Pipeline Dashboard" link if applicable
- Continue showing job-specific stats (tasks, memory, etc.)

---

## UI Mockups

### Summary Banner

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ FATHOM Flood Data Pipeline                    [Refresh ▼] [Auto: 30s ▼]    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │  12,450  │  │   8,234  │  │   4,100  │  │     116  │  │   66.1%  │      │
│  │ TOTAL    │  │ PHASE 1  │  │ PHASE 2  │  │ FAILED   │  │ COMPLETE │      │
│  │ FILES    │  │ COMPLETE │  │ COMPLETE │  │          │  │          │      │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘      │
│                                                                              │
│  Processing: 45.2 files/hour │ ETA: ~93 hours │ 2.4 TB processed            │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Phase Progress Cards

```
┌─────────────────────────────────┐  ┌─────────────────────────────────┐
│ PHASE 1: Band Stack             │  │ PHASE 2: Spatial Merge          │
├─────────────────────────────────┤  ├─────────────────────────────────┤
│ ████████████████░░░░░  66.1%    │  │ ████████████░░░░░░░░░  32.9%    │
│                                 │  │                                 │
│ Pending:     4,216              │  │ Eligible:    3,100              │
│ Processing:     24              │  │ Processing:     12              │
│ Completed:   8,234              │  │ Completed:   4,100              │
│ Failed:         76              │  │ Failed:         40              │
│                                 │  │                                 │
│ Avg time: 45.2s │ Rate: 80/hr   │  │ Avg time: 96.8s │ Rate: 37/hr   │
│ [Submit Phase 1 Job]            │  │ [Submit Phase 2 Job]            │
└─────────────────────────────────┘  └─────────────────────────────────┘
```

### Region Breakdown Table

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Region Breakdown                                              [Filter ▼]    │
├──────────┬─────────┬──────────┬──────────┬──────────┬──────────┬───────────┤
│ Region   │ Total   │ Phase 1  │ Phase 1  │ Phase 2  │ Phase 2  │ Actions   │
│          │ Files   │ Done     │ Pending  │ Done     │ Pending  │           │
├──────────┼─────────┼──────────┼──────────┼──────────┼──────────┼───────────┤
│ CI       │   2,560 │    2,560 │        0 │    1,024 │      256 │ [View]    │
│ GH       │   4,096 │    3,200 │      896 │      512 │      128 │ [View]    │
│ NG       │   5,794 │    2,474 │    3,320 │    2,564 │      640 │ [View]    │
└──────────┴─────────┴──────────┴──────────┴──────────┴──────────┴───────────┘
```

### Active Jobs Panel

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Active Jobs                                                     [View All]  │
├──────────────┬──────────────┬────────┬─────────────┬───────────┬───────────┤
│ Job ID       │ Type         │ Region │ Progress    │ Rate      │ Action    │
├──────────────┼──────────────┼────────┼─────────────┼───────────┼───────────┤
│ abc123...    │ fathom_stack │ GH     │ 45/128 (35%)│ 42/hr     │ [Monitor] │
│ def456...    │ fathom_merge │ CI     │ 12/32  (38%)│ 18/hr     │ [Monitor] │
└──────────────┴──────────────┴────────┴─────────────┴───────────┴───────────┘
```

---

## Implementation Plan

### Phase A: Foundation
1. Create `config/pipelines.py` with registry
2. Create `/api/etl/stats` endpoint (generic SQL queries)
3. Register in `web_interfaces/__init__.py`

### Phase B: UI Implementation
1. Create `web_interfaces/pipeline_monitor/interface.py`
2. Implement abstract rendering based on pipeline config
3. Add configurable auto-refresh (30s, 1m, 5m, off)

### Phase C: FATHOM Integration
1. Register FATHOM in pipeline registry
2. Implement FATHOM-specific groupings
3. Add submit job buttons with parameter forms

### Phase D: Polish
1. Link job monitor → pipeline dashboard
2. Add "View Pipeline" button to job cards
3. Error handling and loading states

---

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `config/pipelines.py` | Pipeline registry (NEW) |
| `triggers/api/etl_stats.py` | ETL stats API endpoint (NEW) |
| `web_interfaces/pipeline_monitor/__init__.py` | Module init (NEW) |
| `web_interfaces/pipeline_monitor/interface.py` | Abstract dashboard UI (NEW) |
| `web_interfaces/__init__.py` | Register new interface (MODIFY) |
| `web_interfaces/tasks/interface.py` | Add pipeline link (MODIFY) |

---

## Configuration Options

### Auto-Refresh Settings
- Off (manual refresh only)
- 30 seconds (recommended for active monitoring)
- 1 minute
- 5 minutes
- 10 minutes

### Grouping Toggles
Users can show/hide dimensional breakdowns:
- By Region (default: on)
- By Scenario (default: collapsed)
- Active Jobs (default: on)

---

## Future Enhancements (Out of Scope)

1. **Historical tracking**: Time-series of processing rate over time
2. **Alerts/notifications**: Email or webhook on job completion/failure
3. **Cost estimation**: Estimate Azure costs based on processing time
4. **Retry automation**: Auto-retry failed tasks with smaller parameters

---

## Reference: FATHOM Pipeline Details

See `docs_claude/FATHOM_ETL.md` for complete FATHOM pipeline documentation.

### Data Flow
```
Bronze Container          Phase 1              Phase 2           STAC
┌─────────────────┐      ┌─────────────┐      ┌─────────────┐   ┌──────────┐
│ 8 TIFFs per     │─────▶│ Stack bands │─────▶│ Merge N×N   │──▶│ Register │
│ tile/scenario   │      │ into 1 COG  │      │ tiles       │   │ items    │
└─────────────────┘      └─────────────┘      └─────────────┘   └──────────┘
    bronze-fathom         silver-fathom/       silver-fathom/
                          fathom-stacked/      fathom/
```

### Tracking Table
`app.etl_source_files` with `etl_type='fathom'`

Key fields:
- `source_metadata`: JSONB with flood_type, defense, year, ssp, tile, grid_cell
- `phase1_completed_at`: NULL = pending, timestamp = done
- `phase2_completed_at`: NULL = pending, timestamp = done

---

## Questions Resolved

| Question | Decision |
|----------|----------|
| Build new or enhance existing? | Abstract approach - one unified monitor |
| Auto-refresh interval? | Configurable: off, 30s, 1m, 5m, 10m |
| Historical tracking? | Out of scope for initial implementation |
| Alerts/notifications? | Out of scope for initial implementation |
| Access control? | Same as app access - no special auth |
