# H3 Pipeline Architecture Review

**Created**: 27 DEC 2025
**Status**: Implementation Plan
**Author**: Claude + Robert

---

## Executive Summary

This document outlines the architecture for a **declarative H3 aggregation pipeline system** that leverages CoreMachine's existing job orchestration infrastructure. The key insight is that we're building a **domain-specific abstraction layer** on top of CoreMachine, not a new execution engine.

### Core Principles

1. **Declarative over Imperative** - Pipelines are data (metadata), not code
2. **CoreMachine is the Engine** - All execution uses existing Job/Stage/Task infrastructure
3. **Two-Phase Workflow** - Design (metadata) → Execute (start button)
4. **Composable Steps** - Pipeline steps can reference outputs of previous steps
5. **Metadata-Driven** - All parameters come from registered sources and pipeline definitions

---

## Table of Contents

1. [Current State](#current-state)
2. [Architecture Vision](#architecture-vision)
3. [Schema Design](#schema-design)
4. [CoreMachine Integration](#coremachine-integration)
5. [Execution Semantics](#execution-semantics)
6. [Implementation Plan](#implementation-plan)
7. [Example Pipelines](#example-pipelines)
8. [API Design](#api-design)
9. [Operational Queries](#operational-queries)
10. [Migration Path](#migration-path)

---

## Current State

### What Works Today

| Component | Status | Description |
|-----------|--------|-------------|
| `h3.cells` | ✅ Operational | 85,662 cells (Greece res6 + Rwanda res2-8) |
| `h3.cell_admin0` | ✅ Operational | Country attribution mappings |
| `h3.zonal_stats` | ✅ Operational | Partitioned stats table (68,260 elevation stats) |
| `h3.dataset_registry` | ✅ Operational | Basic dataset metadata (1 dataset) |
| `h3_raster_aggregation` job | ✅ Operational | 3-stage CoreMachine job |
| `seed_country_cells` | ✅ Operational | Test seeding endpoint |

### Current Limitations

| Issue | Impact |
|-------|--------|
| **Single STAC item_id required** | Can't aggregate tiled datasets (cop-dem-glo-30) across countries without manual tile specification |
| **No dynamic tile discovery** | Each Planetary Computer tile must be specified manually |
| **Limited source metadata** | `dataset_registry` lacks tile patterns, resolution hints, recommended stats |
| **No multi-step pipelines** | Can't chain operations (zonal stats → overlay → weighted aggregation) |
| **Hardcoded parameters** | Each job submission requires full parameter specification |

---

## Architecture Vision

### Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  LAYER 1: H3 METADATA (New)                                                 │
│                                                                             │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐       │
│  │ source_catalog  │     │ pipeline_def    │     │ pipeline_run    │       │
│  │                 │     │                 │     │                 │       │
│  │ • Data sources  │     │ • Step recipes  │     │ • Run instances │       │
│  │ • Tile patterns │     │ • Dependencies  │     │ • Progress      │       │
│  │ • STAC config   │     │ • Aggregations  │     │ • Outputs       │       │
│  └─────────────────┘     └─────────────────┘     └─────────────────┘       │
│                                                                             │
│  "What data exists"       "What to compute"       "What's running"          │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ PipelineFactory.build()
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  LAYER 2: COREMACHINE (Existing - Unchanged)                                │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │  Job                                                             │       │
│  │  ├── Stage 1: inventory_cells (single)                          │       │
│  │  ├── Stage 2: compute_stats (fan_out) ─┬─ Task 1                │       │
│  │  │                                      ├─ Task 2                │       │
│  │  │                                      ├─ Task 3                │       │
│  │  │                                      └─ Task N                │       │
│  │  └── Stage 3: finalize (single)                                 │       │
│  └─────────────────────────────────────────────────────────────────┘       │
│                                                                             │
│  ✓ Service Bus queuing        ✓ Idempotent job IDs                         │
│  ✓ Task tracking in DB        ✓ "Last Task Turns Out Lights"               │
│  ✓ Retry/resume               ✓ Parallel execution                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ Task Execution
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  LAYER 3: H3 HANDLERS (Existing + Enhanced)                                 │
│                                                                             │
│  Existing Handlers:              New Handlers:                              │
│  ┌─────────────────────┐        ┌─────────────────────┐                    │
│  │ h3_inventory_cells  │        │ h3_dynamic_tile_stats│ ← STAC search     │
│  │ h3_raster_zonal     │        │ h3_weighted_combine  │ ← Multi-source    │
│  │ h3_finalize         │        │ h3_spatial_join      │ ← Vector overlay  │
│  └─────────────────────┘        └─────────────────────┘                    │
│                                                                             │
│  Memory Pattern: Load batch → Process in memory → Single DB write          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Two-Phase Workflow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 1: PIPELINE DESIGN (Declarative)                                     │
│                                                                             │
│  1. Register data source → source_catalog                                   │
│     POST /api/h3/sources                                                    │
│     {                                                                       │
│       "id": "cop-dem-glo-30",                                              │
│       "source_type": "planetary_computer",                                  │
│       "collection": "cop-dem-glo-30",                                      │
│       "tile_size_degrees": 1.0,                                            │
│       "native_resolution_m": 30,                                           │
│       ...                                                                   │
│     }                                                                       │
│                                                                             │
│  2. Define pipeline → pipeline_definition                                   │
│     POST /api/h3/pipelines                                                  │
│     {                                                                       │
│       "id": "elevation_terrain",                                           │
│       "steps": [                                                           │
│         {"operation": "zonal_stats", "source": "cop-dem-glo-30", ...}      │
│       ],                                                                    │
│       "output": {"theme": "terrain", "stats": ["mean", "min", "max"]}      │
│     }                                                                       │
│                                                                             │
│  Result: All config stored in metadata tables. No code changes needed.     │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ Later...
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE 2: PIPELINE EXECUTION (Start Button)                                 │
│                                                                             │
│  POST /api/h3/pipelines/run                                                 │
│  {                                                                          │
│    "pipeline_id": "elevation_terrain",                                     │
│    "iso3": "RWA",                                                          │
│    "resolution": 6                                                          │
│  }                                                                          │
│                                                                             │
│  System automatically:                                                      │
│  1. Loads pipeline_definition                                               │
│  2. Resolves sources from source_catalog                                    │
│  3. PipelineFactory builds CoreMachine job                                  │
│  4. Submits job → CoreMachine executes                                      │
│  5. Returns run_id for tracking                                             │
│                                                                             │
│  All parameters come from metadata. User only specifies scope.              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Schema Design

### Table: `h3.source_catalog`

Comprehensive registry of data sources with all metadata needed for efficient aggregation.

```sql
CREATE TABLE h3.source_catalog (
    -- Identity
    id                      VARCHAR(100) PRIMARY KEY,
    display_name            VARCHAR(255) NOT NULL,
    description             TEXT,

    -- Source Connection
    source_type             VARCHAR(50) NOT NULL,  -- planetary_computer, azure_blob, url, postgis
    stac_api_url            VARCHAR(500),          -- For STAC sources
    collection_id           VARCHAR(100),          -- STAC collection
    asset_key               VARCHAR(50) DEFAULT 'data',

    -- Tile/Item Pattern (for tiled datasets)
    item_id_pattern         VARCHAR(255),          -- Regex for item IDs
    tile_size_degrees       REAL,                  -- Tile extent in degrees
    tile_count              INTEGER,               -- Approximate total tiles
    tile_naming_convention  VARCHAR(100),          -- lat_lon_grid, utm_zone, etc.

    -- Raster Properties
    native_resolution_m     REAL,                  -- Meters per pixel
    crs                     VARCHAR(50) DEFAULT 'EPSG:4326',
    data_type               VARCHAR(20),           -- float32, int16, etc.
    nodata_value            DOUBLE PRECISION,
    value_range             JSONB,                 -- {"min": -500, "max": 9000}
    band_count              SMALLINT DEFAULT 1,
    band_info               JSONB,                 -- [{"band": 1, "name": "elevation", "unit": "m"}]

    -- Aggregation Configuration
    theme                   VARCHAR(50) NOT NULL,  -- terrain, climate, demographics, etc.
    recommended_stats       VARCHAR[] DEFAULT ARRAY['mean'],
    recommended_h3_res_min  SMALLINT DEFAULT 4,
    recommended_h3_res_max  SMALLINT DEFAULT 8,
    aggregation_method      VARCHAR(50) DEFAULT 'zonal_stats',
    unit                    VARCHAR(50),

    -- Coverage
    spatial_extent          GEOMETRY(Polygon, 4326),
    coverage_type           VARCHAR(20) DEFAULT 'global',  -- global, regional, national
    land_only               BOOLEAN DEFAULT true,

    -- Temporal
    temporal_extent_start   TIMESTAMPTZ,
    temporal_extent_end     TIMESTAMPTZ,
    is_temporal_series      BOOLEAN DEFAULT false,
    update_frequency        VARCHAR(50),           -- static, daily, monthly, yearly

    -- Performance Hints
    avg_tile_size_mb        REAL,
    recommended_batch_size  INTEGER DEFAULT 500,
    requires_auth           BOOLEAN DEFAULT true,

    -- Provenance
    source_provider         VARCHAR(255),
    source_url              VARCHAR(500),
    source_license          VARCHAR(100),
    citation                TEXT,

    -- Metadata
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW(),
    is_active               BOOLEAN DEFAULT true,

    -- Constraints
    CONSTRAINT valid_source_type CHECK (source_type IN ('planetary_computer', 'azure_blob', 'url', 'postgis')),
    CONSTRAINT valid_theme CHECK (theme IN ('terrain', 'climate', 'demographics', 'vegetation', 'water', 'infrastructure', 'landcover', 'risk'))
);

-- Indexes
CREATE INDEX idx_source_catalog_theme ON h3.source_catalog(theme);
CREATE INDEX idx_source_catalog_source_type ON h3.source_catalog(source_type);
CREATE INDEX idx_source_catalog_active ON h3.source_catalog(is_active) WHERE is_active = true;
```

### Table: `h3.pipeline_definition`

Declarative pipeline recipes.

```sql
CREATE TABLE h3.pipeline_definition (
    -- Identity
    id                      VARCHAR(100) PRIMARY KEY,
    display_name            VARCHAR(255) NOT NULL,
    description             TEXT,
    version                 INTEGER DEFAULT 1,

    -- Pipeline Configuration
    steps                   JSONB NOT NULL,        -- Array of step definitions
    output_config           JSONB NOT NULL,        -- Final output settings
    default_parameters      JSONB,                 -- Default scope, resolution, etc.

    -- Validation
    required_sources        VARCHAR[],             -- Source IDs that must exist
    required_h3_tables      VARCHAR[],             -- Tables that must have data

    -- Metadata
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW(),
    created_by              VARCHAR(100),
    is_active               BOOLEAN DEFAULT true,
    is_system               BOOLEAN DEFAULT false  -- System pipelines can't be deleted
);

-- Indexes
CREATE INDEX idx_pipeline_def_active ON h3.pipeline_definition(is_active) WHERE is_active = true;
```

**Step Definition Schema (JSONB)**:

```json
{
  "steps": [
    {
      "id": "flood_risk",
      "operation": "zonal_stats",
      "source_id": "fathom-flood-100yr",
      "geometry_source": "building_footprints",
      "params": {
        "stats": ["max", "mean"],
        "all_touched": true
      },
      "output": {
        "type": "intermediate",
        "name": "building_flood_risk"
      }
    },
    {
      "id": "pop_overlay",
      "operation": "spatial_join",
      "source_id": "worldpop-2020",
      "geometry_source": "$flood_risk",
      "depends_on": ["flood_risk"],
      "params": {
        "stats": ["sum"]
      },
      "output": {
        "type": "intermediate",
        "name": "building_pop_risk"
      }
    },
    {
      "id": "h3_aggregate",
      "operation": "h3_weighted_aggregate",
      "geometry_source": "$pop_overlay",
      "depends_on": ["pop_overlay"],
      "params": {
        "aggregations": [
          {"field": "flood_max", "method": "weighted_mean", "weight": "pop_sum"},
          {"field": "pop_sum", "method": "sum"},
          {"field": "building_id", "method": "count"}
        ]
      },
      "output": {
        "type": "h3_stats",
        "theme": "risk"
      }
    }
  ],
  "output_config": {
    "theme": "risk",
    "dataset_id": "flood_pop_risk_weighted"
  }
}
```

### Table: `h3.pipeline_run`

Execution instances for tracking and resumability.

```sql
CREATE TABLE h3.pipeline_run (
    -- Identity
    run_id                  VARCHAR(64) PRIMARY KEY,
    pipeline_id             VARCHAR(100) NOT NULL REFERENCES h3.pipeline_definition(id),
    pipeline_version        INTEGER NOT NULL,

    -- Scope
    scope                   JSONB NOT NULL,        -- {iso3, bbox, resolution, etc.}

    -- Execution State
    status                  VARCHAR(20) NOT NULL DEFAULT 'pending',
    current_step_id         VARCHAR(50),
    progress                JSONB,                 -- Per-step progress

    -- Timing
    queued_at               TIMESTAMPTZ DEFAULT NOW(),
    started_at              TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ,

    -- CoreMachine Link
    job_id                  VARCHAR(64),           -- FK to app.jobs

    -- Results
    output_summary          JSONB,                 -- Stats, counts, etc.
    error                   TEXT,

    -- Constraints
    CONSTRAINT valid_status CHECK (status IN ('pending', 'queued', 'running', 'completed', 'failed', 'cancelled'))
);

-- Indexes
CREATE INDEX idx_pipeline_run_status ON h3.pipeline_run(status);
CREATE INDEX idx_pipeline_run_pipeline ON h3.pipeline_run(pipeline_id);
CREATE INDEX idx_pipeline_run_job ON h3.pipeline_run(job_id);
```

### Table: `h3.pipeline_step_run`

Per-step execution tracking.

```sql
CREATE TABLE h3.pipeline_step_run (
    -- Identity
    run_id                  VARCHAR(64) NOT NULL REFERENCES h3.pipeline_run(run_id),
    step_id                 VARCHAR(50) NOT NULL,

    -- State
    status                  VARCHAR(20) NOT NULL DEFAULT 'pending',

    -- Timing
    started_at              TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ,

    -- Results
    rows_input              INTEGER,
    rows_output             INTEGER,
    output_location         VARCHAR(255),          -- Table or temp location
    metrics                 JSONB,                 -- Timing, memory, etc.
    error                   TEXT,

    -- Primary Key
    PRIMARY KEY (run_id, step_id),

    -- Constraints
    CONSTRAINT valid_step_status CHECK (status IN ('pending', 'running', 'completed', 'failed', 'skipped'))
);
```

---

## CoreMachine Integration

### PipelineFactory: Translating Pipelines to Jobs

```python
class PipelineFactory:
    """
    Translates H3 pipeline definitions into CoreMachine jobs.

    This is the bridge between declarative pipelines and CoreMachine execution.
    """

    def build_job(
        self,
        pipeline_id: str,
        scope: Dict[str, Any],
        run_id: str
    ) -> Dict[str, Any]:
        """
        Build a CoreMachine job from a pipeline definition.

        Args:
            pipeline_id: ID of pipeline in h3.pipeline_definition
            scope: Execution scope {iso3, resolution, bbox, etc.}
            run_id: Unique run identifier

        Returns:
            CoreMachine job definition ready for submission
        """
        # 1. Load pipeline definition
        pipeline = self._load_pipeline(pipeline_id)

        # 2. Resolve all source references
        sources = self._resolve_sources(pipeline['steps'])

        # 3. Build stages from steps
        stages = self._build_stages(pipeline['steps'], sources)

        # 4. Add standard inventory and finalize stages
        stages = self._wrap_with_bookends(stages)

        # 5. Build job parameters
        job_params = {
            'pipeline_id': pipeline_id,
            'run_id': run_id,
            'scope': scope,
            'sources': sources,
            'output_config': pipeline['output_config']
        }

        return {
            'job_type': 'h3_pipeline',
            'stages': stages,
            'parameters': job_params
        }

    def _build_stages(self, steps, sources):
        """Convert pipeline steps to CoreMachine stages."""
        stages = []

        for i, step in enumerate(steps):
            operation = step['operation']

            # Map operation to handler
            handler_map = {
                'zonal_stats': 'h3_dynamic_tile_stats',
                'spatial_join': 'h3_spatial_join',
                'h3_weighted_aggregate': 'h3_weighted_aggregate',
                'filter': 'h3_filter',
                'transform': 'h3_transform'
            }

            task_type = handler_map.get(operation)
            if not task_type:
                raise ValueError(f"Unknown operation: {operation}")

            stages.append({
                'number': i + 2,  # +2 because inventory is stage 1
                'name': step['id'],
                'task_type': task_type,
                'parallelism': 'fan_out',
                'step_config': step
            })

        return stages
```

### Job Flow Example

```
User Request:
POST /api/h3/pipelines/run
{
    "pipeline_id": "elevation_terrain",
    "iso3": "RWA",
    "resolution": 6
}

        │
        ▼

PipelineFactory.build_job():
1. Load pipeline "elevation_terrain" from h3.pipeline_definition
2. Resolve source "cop-dem-glo-30" from h3.source_catalog
3. Build stages from steps
4. Return CoreMachine job definition

        │
        ▼

CoreMachine Job Created:
{
    "job_type": "h3_pipeline",
    "job_id": "sha256(h3_pipeline + params)",
    "stages": [
        {"number": 1, "task_type": "h3_pipeline_inventory", "parallelism": "single"},
        {"number": 2, "task_type": "h3_dynamic_tile_stats", "parallelism": "fan_out"},
        {"number": 3, "task_type": "h3_pipeline_finalize", "parallelism": "single"}
    ],
    "parameters": {
        "pipeline_id": "elevation_terrain",
        "run_id": "abc123",
        "scope": {"iso3": "RWA", "resolution": 6},
        "sources": {"cop-dem-glo-30": {full source config}},
        "output_config": {"theme": "terrain", "stats": ["mean", "min", "max"]}
    }
}

        │
        ▼

CoreMachine Executes:
Stage 1: h3_pipeline_inventory
    → Count cells, calculate batches, create pipeline_run record

Stage 2: h3_dynamic_tile_stats (N parallel tasks)
    → Task 1: cells 0-499, discover tiles, compute stats
    → Task 2: cells 500-999, discover tiles, compute stats
    → ...
    → Task N: remaining cells

Stage 3: h3_pipeline_finalize
    → Verify counts, update pipeline_run, update dataset_registry

        │
        ▼

Results in h3.zonal_stats_terrain:
+------------+----------------+-----------+-------+
| h3_index   | dataset_id     | stat_type | value |
+------------+----------------+-----------+-------+
| 5765...    | cop-dem-glo-30 | mean      | 1523.4|
| 5765...    | cop-dem-glo-30 | min       | 1201.0|
| 5765...    | cop-dem-glo-30 | max       | 1847.2|
+------------+----------------+-----------+-------+
```

---

## Execution Semantics

### Stage Barrier Constraint

**INVARIANT**: CoreMachine stages execute **sequentially**. Stage N+1 cannot begin until ALL tasks in Stage N have completed.

```python
# This is enforced by CoreMachine, not by pipeline logic.
# The "Last Task Turns Out the Lights" pattern detects stage completion:
#
# Stage 2 (fan_out, 100 tasks):
#   Task 1: completes → checks "am I last?" → no → done
#   Task 2: completes → checks "am I last?" → no → done
#   ...
#   Task 100: completes → checks "am I last?" → YES → triggers Stage 3
#
# This atomic check uses:
#   UPDATE tasks SET status='completed' WHERE task_id=X
#   RETURNING (SELECT COUNT(*) FROM tasks WHERE stage_id=Y AND status='pending') = 0
```

This means multi-step pipelines naturally respect dependencies:
- Step 1 (Stage 2) completes ALL batches → outputs written to intermediate storage
- Step 2 (Stage 3) begins → reads from intermediate storage
- No race conditions, no partial reads

### Parallelization Model: Steps are Global

For multi-step pipelines, **Option B** applies: Steps are global, batches are within-step only.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Pipeline: flood_risk_weighted                                              │
│  Scope: iso3=RWA, resolution=6                                              │
│  Total buildings: 50,000                                                    │
│  Batch size: 5,000 buildings                                                │
└─────────────────────────────────────────────────────────────────────────────┘

Stage 1: Inventory
    → Count buildings, calculate 10 batches
    → Output: batch_ranges = [{0-4999}, {5000-9999}, ...]

Stage 2: building_flood_risk (Step 1 - zonal_stats)
    ┌──────────────────────────────────────────────────────────┐
    │  10 PARALLEL TASKS                                       │
    │  Task 1: buildings 0-4999 → flood_stats → write to temp  │
    │  Task 2: buildings 5000-9999 → flood_stats → write to temp│
    │  ...                                                     │
    │  Task 10: buildings 45000-49999 → flood_stats → write    │
    └──────────────────────────────────────────────────────────┘
    → ALL tasks complete → intermediate table has 50,000 rows
    → BARRIER: Stage 3 cannot start until all 10 tasks done

Stage 3: building_population (Step 2 - spatial_join)
    ┌──────────────────────────────────────────────────────────┐
    │  10 PARALLEL TASKS (re-batched from intermediate)        │
    │  Task 1: read rows 0-4999 from intermediate → join pop   │
    │  Task 2: read rows 5000-9999 from intermediate → join    │
    │  ...                                                     │
    └──────────────────────────────────────────────────────────┘
    → ALL tasks complete → intermediate table 2 has 50,000 rows

Stage 4: h3_risk_aggregation (Step 3 - aggregate to H3)
    ┌──────────────────────────────────────────────────────────┐
    │  N PARALLEL TASKS (batched by H3 cells, not buildings)   │
    │  Task 1: H3 cells 0-499 → aggregate buildings in cell    │
    │  Task 2: H3 cells 500-999 → aggregate                    │
    │  ...                                                     │
    └──────────────────────────────────────────────────────────┘
    → ALL tasks complete → h3.zonal_stats_risk populated

Stage 5: Finalize
    → Verify counts, cleanup intermediates, update registry
```

**Why Option B (not end-to-end per batch)?**

| Aspect | Option A (E2E per batch) | Option B (Global steps) |
|--------|--------------------------|-------------------------|
| Complexity | High - each batch tracks own state | Low - stages are stages |
| CoreMachine fit | Poor - fights stage model | Perfect - uses stage model |
| Intermediate data | Per-batch temp tables | Single shared temp table |
| Re-batching | Impossible | Easy - Stage 3 can batch differently than Stage 2 |
| Debugging | Hard - 100 mini-pipelines | Easy - 5 stages to inspect |

### Intermediate Output Handling

Intermediate outputs between steps are stored in **PostgreSQL temp tables** with explicit cleanup:

```json
{
  "output": {
    "type": "intermediate",
    "storage": "temp_table",
    "schema": "h3_temp",
    "name": "building_flood_risk_{{run_id}}",
    "ttl_hours": 24,
    "cleanup": "on_success"
  }
}
```

**Storage Options**:

| Storage | Use Case | Pros | Cons |
|---------|----------|------|------|
| `temp_table` | Default for <10M rows | Fast, transactional, easy cleanup | Memory pressure if huge |
| `unlogged_table` | 10M-100M rows | Faster writes, survives session | No crash recovery |
| `blob_parquet` | >100M rows | Unlimited size, cheap storage | Slower access, needs cleanup job |

**Cleanup Policies**:

| Policy | Behavior |
|--------|----------|
| `on_success` | Delete intermediate after pipeline completes successfully |
| `on_completion` | Delete after pipeline completes (success or failure) |
| `ttl` | Keep for `ttl_hours`, background job cleans up |
| `manual` | Never auto-delete, user must clean up |

**Implementation**:

```sql
-- Intermediate tables use a dedicated schema
CREATE SCHEMA IF NOT EXISTS h3_temp;

-- Table naming includes run_id for isolation
CREATE UNLOGGED TABLE h3_temp.building_flood_risk_abc123 (
    building_id BIGINT,
    flood_max REAL,
    flood_mean REAL,
    geom GEOMETRY(Point, 4326),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Cleanup tracking
CREATE TABLE h3.intermediate_cleanup (
    table_name VARCHAR(255) PRIMARY KEY,
    run_id VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    cleanup_policy VARCHAR(20)
);

-- Background cleanup job (runs hourly)
DELETE FROM h3_temp.*
WHERE table_name IN (
    SELECT table_name FROM h3.intermediate_cleanup
    WHERE expires_at < NOW()
);
```

### Retry and Resume Semantics

**Task-level retries**: Handled by CoreMachine (configurable, default 3 attempts).

**Step-level recovery**: If a step fails after all task retries exhausted:

```sql
-- Add resume capability to pipeline_run
ALTER TABLE h3.pipeline_run ADD COLUMN
    resume_from_step VARCHAR(50),  -- NULL = start fresh, step_id = resume point
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3;
```

**Resume Workflow**:

```bash
# Original run fails at step 2
GET /api/h3/pipelines/runs/abc123
{
  "run_id": "abc123",
  "status": "failed",
  "current_step_id": "building_population",
  "error": "WorldPop tile server timeout",
  "steps": [
    {"step_id": "building_flood_risk", "status": "completed"},
    {"step_id": "building_population", "status": "failed"},
    {"step_id": "h3_risk_aggregation", "status": "pending"}
  ]
}

# Resume from failed step (intermediate from step 1 still exists)
POST /api/h3/pipelines/runs/abc123/resume
{
  "from_step": "building_population"  # Optional, defaults to failed step
}

# System:
# 1. Validates intermediate output from step 1 exists
# 2. Creates new job starting at Stage 3 (step 2)
# 3. Reuses existing intermediate table
```

**Idempotency Considerations**:

| Scenario | Behavior |
|----------|----------|
| Resume after step failure | Skip completed steps, rerun failed step |
| Resume after task failure | Step re-runs all tasks (intermediates may have partial data) |
| Rerun completed pipeline | Option: `force=true` to rerun, otherwise returns existing results |

---

## Operational Queries

### Pipeline Status Dashboard

```sql
-- Active pipeline runs with progress
SELECT
    pr.run_id,
    pr.pipeline_id,
    pd.display_name as pipeline_name,
    pr.status,
    pr.scope->>'iso3' as country,
    pr.scope->>'resolution' as resolution,
    pr.current_step_id,
    pr.started_at,
    EXTRACT(EPOCH FROM (NOW() - pr.started_at)) / 60 as minutes_running,
    (
        SELECT COUNT(*)
        FROM h3.pipeline_step_run psr
        WHERE psr.run_id = pr.run_id AND psr.status = 'completed'
    ) as steps_completed,
    (
        SELECT COUNT(*)
        FROM h3.pipeline_step_run psr
        WHERE psr.run_id = pr.run_id
    ) as steps_total
FROM h3.pipeline_run pr
JOIN h3.pipeline_definition pd ON pr.pipeline_id = pd.id
WHERE pr.status IN ('running', 'queued')
ORDER BY pr.started_at DESC;
```

### Task-Level Progress (via CoreMachine)

```sql
-- Detailed task progress for a pipeline run
SELECT
    pr.run_id,
    s.stage_number,
    s.name as stage_name,
    COUNT(t.task_id) as total_tasks,
    COUNT(t.task_id) FILTER (WHERE t.status = 'completed') as completed,
    COUNT(t.task_id) FILTER (WHERE t.status = 'processing') as running,
    COUNT(t.task_id) FILTER (WHERE t.status = 'failed') as failed,
    COUNT(t.task_id) FILTER (WHERE t.status = 'pending') as pending,
    ROUND(
        100.0 * COUNT(t.task_id) FILTER (WHERE t.status = 'completed') /
        NULLIF(COUNT(t.task_id), 0),
        1
    ) as pct_complete
FROM h3.pipeline_run pr
JOIN app.jobs j ON pr.job_id = j.job_id
JOIN app.stages s ON j.job_id = s.job_id
LEFT JOIN app.tasks t ON s.stage_id = t.stage_id
WHERE pr.run_id = 'abc123'
GROUP BY pr.run_id, s.stage_number, s.name
ORDER BY s.stage_number;
```

### Slow Tile Detection (Performance Debugging)

```sql
-- Which STAC tiles are slowest?
SELECT
    t.parameters->>'source_tile' as tile_id,
    t.parameters->>'collection' as collection,
    COUNT(*) as task_count,
    ROUND(AVG(EXTRACT(EPOCH FROM (t.completed_at - t.started_at)))::numeric, 2) as avg_seconds,
    ROUND(MAX(EXTRACT(EPOCH FROM (t.completed_at - t.started_at)))::numeric, 2) as max_seconds,
    ROUND(STDDEV(EXTRACT(EPOCH FROM (t.completed_at - t.started_at)))::numeric, 2) as stddev_seconds
FROM app.tasks t
JOIN app.stages s ON t.stage_id = s.stage_id
JOIN app.jobs j ON s.job_id = j.job_id
WHERE j.job_type = 'h3_pipeline'
  AND t.status = 'completed'
  AND t.parameters->>'source_tile' IS NOT NULL
GROUP BY t.parameters->>'source_tile', t.parameters->>'collection'
HAVING COUNT(*) > 5  -- Only tiles used multiple times
ORDER BY avg_seconds DESC
LIMIT 20;
```

### Source Catalog Usage

```sql
-- Which sources are most used?
SELECT
    sc.id as source_id,
    sc.display_name,
    sc.theme,
    COUNT(DISTINCT pr.run_id) as pipeline_runs,
    COUNT(DISTINCT pr.scope->>'iso3') as countries_processed,
    SUM((pr.output_summary->>'rows_output')::int) as total_rows_generated
FROM h3.source_catalog sc
LEFT JOIN h3.pipeline_definition pd ON pd.steps::text LIKE '%' || sc.id || '%'
LEFT JOIN h3.pipeline_run pr ON pr.pipeline_id = pd.id AND pr.status = 'completed'
GROUP BY sc.id, sc.display_name, sc.theme
ORDER BY pipeline_runs DESC;
```

### Intermediate Table Cleanup Status

```sql
-- Intermediate tables pending cleanup
SELECT
    ic.table_name,
    ic.run_id,
    pr.pipeline_id,
    pr.status as run_status,
    ic.created_at,
    ic.expires_at,
    ic.cleanup_policy,
    CASE
        WHEN ic.expires_at < NOW() THEN 'EXPIRED - pending cleanup'
        WHEN pr.status = 'completed' AND ic.cleanup_policy = 'on_success' THEN 'READY for cleanup'
        ELSE 'ACTIVE'
    END as cleanup_status,
    pg_size_pretty(pg_total_relation_size('h3_temp.' || ic.table_name)) as table_size
FROM h3.intermediate_cleanup ic
LEFT JOIN h3.pipeline_run pr ON ic.run_id = pr.run_id
ORDER BY ic.created_at DESC;
```

---

## Implementation Plan

### Phase 1: Foundation (Week 1)

| Task | Description | Effort |
|------|-------------|--------|
| 1.1 | Create `h3.source_catalog` table | S |
| 1.2 | Create source catalog repository methods | M |
| 1.3 | Create `/api/h3/sources` CRUD endpoints | M |
| 1.4 | Register cop-dem-glo-30 with full metadata | S |
| 1.5 | Enhance `h3_raster_zonal_stats` with dynamic tile discovery | L |
| 1.6 | Test end-to-end: Rwanda elevation with auto-discovery | M |

**Deliverable**: Can run elevation aggregation for any country without specifying item_id.

### Phase 2: Pipeline Framework (Week 2)

| Task | Description | Effort |
|------|-------------|--------|
| 2.1 | Create `h3.pipeline_definition` table | S |
| 2.2 | Create `h3.pipeline_run` and `h3.pipeline_step_run` tables | S |
| 2.3 | Implement `PipelineFactory` service | L |
| 2.4 | Create `h3_pipeline` job type (generic executor) | M |
| 2.5 | Create `/api/h3/pipelines` CRUD endpoints | M |
| 2.6 | Create `/api/h3/pipelines/run` execution endpoint | M |
| 2.7 | Migrate existing `h3_raster_aggregation` to use PipelineFactory | M |

**Deliverable**: Can define and execute simple single-step pipelines declaratively.

### Phase 3: Multi-Step Pipelines (Week 3)

| Task | Description | Effort |
|------|-------------|--------|
| 3.1 | Implement step dependency resolution | M |
| 3.2 | Create intermediate output handling (temp tables or materialized) | L |
| 3.3 | Implement `h3_weighted_aggregate` handler | L |
| 3.4 | Implement `h3_spatial_join` handler | L |
| 3.5 | Create example multi-step pipeline (flood + pop + risk) | M |
| 3.6 | Test full FATHOM → WorldPop → H3 Risk pipeline | L |

**Deliverable**: Can run complex multi-source weighted aggregation pipelines.

### Phase 4: Production Hardening (Week 4)

| Task | Description | Effort |
|------|-------------|--------|
| 4.1 | Add pipeline validation (source exists, schema compatible) | M |
| 4.2 | Add pipeline versioning and migration | M |
| 4.3 | Add monitoring dashboard for pipeline runs | M |
| 4.4 | Performance optimization (tile caching, batch tuning) | L |
| 4.5 | Documentation and examples | M |
| 4.6 | Register additional Planetary Computer sources | M |

**Deliverable**: Production-ready pipeline system with monitoring.

---

## Example Pipelines

### Simple: Elevation Stats

```json
{
  "id": "elevation_terrain",
  "display_name": "Elevation Statistics",
  "description": "Compute elevation stats (mean, min, max) from Copernicus DEM",
  "steps": [
    {
      "id": "elevation_stats",
      "operation": "zonal_stats",
      "source_id": "cop-dem-glo-30",
      "params": {
        "stats": ["mean", "min", "max", "std"]
      },
      "output": {
        "type": "h3_stats",
        "theme": "terrain"
      }
    }
  ],
  "output_config": {
    "theme": "terrain",
    "dataset_id": "elevation_copdem30"
  },
  "default_parameters": {
    "resolution": 6,
    "batch_size": 500
  }
}
```

### Complex: Flood-Population-Building Risk

```json
{
  "id": "flood_risk_weighted",
  "display_name": "Weighted Flood-Population-Building Risk",
  "description": "Multi-source risk aggregation: FATHOM flood × WorldPop population × Building footprints → H3",
  "steps": [
    {
      "id": "building_flood_risk",
      "operation": "zonal_stats",
      "source_id": "fathom-flood-100yr",
      "geometry_source": "building_footprints",
      "params": {
        "stats": ["max", "mean"],
        "all_touched": true
      },
      "output": {
        "type": "intermediate",
        "name": "building_flood_risk"
      }
    },
    {
      "id": "building_population",
      "operation": "spatial_join",
      "source_id": "worldpop-2020",
      "geometry_source": "$building_flood_risk",
      "depends_on": ["building_flood_risk"],
      "params": {
        "stats": ["sum"],
        "radius_m": 100
      },
      "output": {
        "type": "intermediate",
        "name": "building_pop_flood"
      }
    },
    {
      "id": "h3_risk_aggregation",
      "operation": "h3_weighted_aggregate",
      "geometry_source": "$building_population",
      "depends_on": ["building_population"],
      "params": {
        "aggregations": [
          {
            "field": "flood_risk_max",
            "method": "weighted_mean",
            "weight_field": "population_sum",
            "output_name": "pop_weighted_flood_risk"
          },
          {
            "field": "population_sum",
            "method": "sum",
            "output_name": "total_population"
          },
          {
            "field": "building_id",
            "method": "count",
            "output_name": "building_count"
          },
          {
            "field": "flood_risk_max",
            "method": "max",
            "output_name": "max_flood_risk"
          }
        ]
      },
      "output": {
        "type": "h3_stats",
        "theme": "risk"
      }
    }
  ],
  "output_config": {
    "theme": "risk",
    "dataset_id": "flood_pop_building_risk"
  },
  "required_sources": ["fathom-flood-100yr", "worldpop-2020"],
  "required_h3_tables": ["building_footprints"]
}
```

---

## API Design

### Source Catalog Endpoints

```bash
# List all sources
GET /api/h3/sources
GET /api/h3/sources?theme=terrain&is_active=true

# Get source details
GET /api/h3/sources/{source_id}

# Register new source
POST /api/h3/sources
{
  "id": "cop-dem-glo-30",
  "display_name": "Copernicus DEM 30m",
  "source_type": "planetary_computer",
  "collection_id": "cop-dem-glo-30",
  ...
}

# Update source
PATCH /api/h3/sources/{source_id}

# Deactivate source (soft delete)
DELETE /api/h3/sources/{source_id}
```

### Pipeline Definition Endpoints

```bash
# List pipelines
GET /api/h3/pipelines
GET /api/h3/pipelines?is_active=true

# Get pipeline details
GET /api/h3/pipelines/{pipeline_id}

# Create pipeline
POST /api/h3/pipelines
{
  "id": "elevation_terrain",
  "display_name": "Elevation Statistics",
  "steps": [...],
  ...
}

# Update pipeline (creates new version)
PUT /api/h3/pipelines/{pipeline_id}

# Validate pipeline (dry run)
POST /api/h3/pipelines/{pipeline_id}/validate
{
  "iso3": "RWA",
  "resolution": 6
}
```

### Pipeline Execution Endpoints

```bash
# Run a pipeline
POST /api/h3/pipelines/run
{
  "pipeline_id": "elevation_terrain",
  "iso3": "RWA",
  "resolution": 6
}

# Response:
{
  "run_id": "abc123",
  "job_id": "def456",
  "status": "queued",
  "steps": [
    {"step_id": "elevation_stats", "status": "pending"}
  ]
}

# Get run status
GET /api/h3/pipelines/runs/{run_id}

# List runs
GET /api/h3/pipelines/runs?pipeline_id=elevation_terrain&status=running

# Cancel run
POST /api/h3/pipelines/runs/{run_id}/cancel
```

---

## Migration Path

### From Current to New Architecture

| Current | New | Migration |
|---------|-----|-----------|
| `h3.dataset_registry` | `h3.source_catalog` | Expand schema, migrate data |
| `h3_raster_aggregation` job | `h3_pipeline` job | Wrap existing handlers |
| Hardcoded item_id | Dynamic tile discovery | Enhance handler |
| Manual job submission | `/api/h3/pipelines/run` | New endpoint, old still works |

### Backward Compatibility

The existing `h3_raster_aggregation` job will continue to work. The new pipeline system is additive:

1. Old way still works:
   ```bash
   POST /api/jobs/submit/h3_raster_aggregation
   {"source_type": "azure", "container": "...", ...}
   ```

2. New way via pipelines:
   ```bash
   POST /api/h3/pipelines/run
   {"pipeline_id": "elevation_terrain", "iso3": "RWA"}
   ```

---

## Summary

### What We're Building

1. **`h3.source_catalog`** - Rich metadata for data sources
2. **`h3.pipeline_definition`** - Declarative multi-step recipes
3. **`h3.pipeline_run`** - Execution tracking
4. **`PipelineFactory`** - Translates pipelines → CoreMachine jobs
5. **Dynamic tile discovery** - Auto-search STAC for tiles covering cells
6. **New handlers** - weighted_aggregate, spatial_join

### What We're NOT Building

- New execution engine (CoreMachine does this)
- New task queuing (Service Bus does this)
- New job tracking (existing tables do this)

### Key Insight

> We're building a **domain-specific abstraction layer** that translates H3 aggregation recipes into CoreMachine jobs. CoreMachine remains the execution engine.

---

## Detailed TODO List

**Instructions for Claude**: This section contains actionable tasks with full context. Each task can be picked up independently. Always mark tasks complete by changing `[ ]` to `[x]` and adding completion date.

---

### PHASE 1: Foundation - Source Catalog & Dynamic Tile Discovery

#### Task 1.1: Create `h3.source_catalog` Table
**Status**: `[x]` Completed 27 DEC 2025
**Effort**: Small
**Prerequisites**: None

**What to do**:
1. Add migration to create `h3.source_catalog` table in `infrastructure/h3_schema.py`
2. Use the schema defined in [Schema Design](#table-h3source_catalog) above
3. Added `_deploy_source_catalog_table()` method with full schema and indexes

**Files modified**:
- `infrastructure/h3_schema.py` - Added `_deploy_source_catalog_table()` method (lines 630-857)

**Acceptance criteria**:
- [ ] Table exists in h3 schema after deployment
- [ ] All columns match schema design
- [ ] Indexes created
- [ ] CHECK constraints work

**Testing**:
```bash
# After deployment, run full-rebuild and verify
curl -X POST "https://rmhazuregeoapi.../api/dbadmin/maintenance?action=full-rebuild&confirm=yes"
# Then check table exists via psql or dbadmin endpoint
```

---

#### Task 1.2: Create Source Catalog Repository
**Status**: `[x]` Completed 27 DEC 2025
**Effort**: Medium
**Prerequisites**: Task 1.1

**What was done**:
1. Created `infrastructure/h3_source_repository.py` with full CRUD implementation
2. Methods: `get_source()`, `list_sources()`, `register_source()`, `update_source()`, `deactivate_source()`
3. Follows existing patterns from `h3_repository.py`

**Files created**:
- `infrastructure/h3_source_repository.py` (~350 lines)

---

#### Task 1.3: Create `/api/h3/sources` Endpoints
**Status**: `[x]` Completed 27 DEC 2025
**Effort**: Medium
**Prerequisites**: Tasks 1.1, 1.2

**What was done**:
1. Created `web_interfaces/h3_sources/__init__.py` and `interface.py`
2. Registered blueprint in `function_app.py`
3. Implemented all 5 endpoints:
   - `GET /api/h3/sources` - List all sources with filters
   - `GET /api/h3/sources/{source_id}` - Get single source
   - `POST /api/h3/sources` - Register new source (201 Created)
   - `PATCH /api/h3/sources/{source_id}` - Update source
   - `DELETE /api/h3/sources/{source_id}` - Soft delete (deactivate)

**Files created**:
- `web_interfaces/h3_sources/__init__.py`
- `web_interfaces/h3_sources/interface.py` (~300 lines)

**Files modified**:
- `function_app.py` - Added blueprint registration (line 388, 392)

---

#### Task 1.4: Register cop-dem-glo-30 with Full Metadata
**Status**: `[x]` Completed 27 DEC 2025
**Effort**: Small
**Prerequisites**: Task 1.3

**What was done**:
1. Created `infrastructure/h3_source_seeds.py` with seed data definitions
2. Includes `COP_DEM_GLO_30`, `NASADEM`, and `ESA_WORLDCOVER_2021` definitions
3. Functions `seed_planetary_computer_sources()` and `seed_cop_dem_glo_30()` for seeding

**Files created**:
- `infrastructure/h3_source_seeds.py` (~250 lines)

**Usage after deployment**:
```python
from infrastructure.h3_source_seeds import seed_planetary_computer_sources
result = seed_planetary_computer_sources()  # Seeds all 3 sources
```

**cop-dem-glo-30 metadata includes**:
```json
{
  "id": "cop-dem-glo-30",
  "display_name": "Copernicus DEM GLO-30",
  "source_type": "planetary_computer",
  "collection_id": "cop-dem-glo-30",
  "theme": "terrain",
  "tile_count": 26000,
  "native_resolution_m": 30,
  "nodata_value": -32767.0,
  "recommended_stats": ["mean", "min", "max", "std"]
}
```

**Acceptance criteria**:
- [ ] Source registered successfully
- [ ] Can retrieve via GET /api/h3/sources/cop-dem-glo-30
- [ ] All fields populated correctly

---

#### Task 1.5: Implement Dynamic Tile Discovery in Handler
**Status**: `[x]` Completed 27 DEC 2025
**Effort**: Large
**Prerequisites**: Tasks 1.1-1.4

**What was done**:
1. Modified `services/h3_aggregation/handler_raster_zonal.py`
2. Added `source_id` parameter for referencing h3.source_catalog
3. Added `use_dynamic_tile_discovery` mode when source_id provided but item_id not
4. Created helper functions:
   - `_process_with_dynamic_tile_discovery()` - Main processing loop
   - `_calculate_cells_bbox()` - Calculate bbox from H3 cell geometries
   - `_filter_cells_to_tile_bbox()` - Filter cells within tile extent

**Files modified**:
- `services/h3_aggregation/handler_raster_zonal.py` (~200 lines added)

**Key features implemented**:
- Looks up source config from h3.source_catalog
- Calculates bounding box from cell batch
- Uses `pystac_client.search()` to discover tiles covering bbox
- Processes each tile, filtering cells to avoid duplicates
- Tracks processed h3_indices to prevent duplicate stats
- Inserts all stats in single batch at end

**New usage pattern**:
```python
# Dynamic discovery mode - no item_id needed
h3_raster_zonal_stats({
    "source_type": "planetary_computer",
    "source_id": "cop-dem-glo-30",  # References h3.source_catalog
    "dataset_id": "copdem_glo30",
    "resolution": 6,
    "iso3": "RWA",
    "batch_start": 0,
    "batch_size": 500,
    "stats": ["mean", "min", "max"]
})
```

---

#### Task 1.6: Test End-to-End Rwanda Elevation
**Status**: `[ ]` Not Started
**Effort**: Medium
**Prerequisites**: Tasks 1.1-1.5

**What to do**:
1. Deploy updated code
2. Run full-rebuild to create new tables
3. Submit job using source_id instead of item_id:
```bash
curl -X POST https://rmhazuregeoapi.../api/jobs/submit/h3_raster_aggregation \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "planetary_computer",
    "source_id": "cop-dem-glo-30",
    "iso3": "RWA",
    "resolution": 6,
    "stats": ["mean", "min", "max"]
  }'
```

**Acceptance criteria**:
- [ ] Job completes successfully
- [ ] Stats written to h3.zonal_stats_terrain
- [ ] All Rwanda cells at res 6 have elevation stats
- [ ] Multiple tiles automatically discovered and processed

**Phase 1 Complete When**:
- Can run elevation aggregation for ANY country without specifying item_id
- Source catalog has cop-dem-glo-30 registered
- All Phase 1 tasks marked complete

---

### PHASE 2: Pipeline Framework

#### Task 2.1: Create `h3.pipeline_definition` Table
**Status**: `[ ]` Not Started
**Effort**: Small
**Prerequisites**: Phase 1 complete

**What to do**:
1. Add table creation to `infrastructure/h3_bootstrap.py`
2. Use schema from [Schema Design](#table-h3pipeline_definition)

**Files to modify**:
- `infrastructure/h3_bootstrap.py`

---

#### Task 2.2: Create `h3.pipeline_run` and `h3.pipeline_step_run` Tables
**Status**: `[ ]` Not Started
**Effort**: Small
**Prerequisites**: Task 2.1

**What to do**:
1. Add both tables to `infrastructure/h3_bootstrap.py`
2. Use schemas from [Schema Design](#table-h3pipeline_run) and [Schema Design](#table-h3pipeline_step_run)
3. Add `h3_temp` schema creation for intermediate tables

**Files to modify**:
- `infrastructure/h3_bootstrap.py`

---

#### Task 2.3: Implement PipelineFactory Service
**Status**: `[ ]` Not Started
**Effort**: Large
**Prerequisites**: Tasks 2.1, 2.2

**What to do**:
1. Create `services/h3_pipeline/factory.py`
2. Implement `PipelineFactory` class as shown in [CoreMachine Integration](#pipelinefactory-translating-pipelines-to-jobs)
3. Key methods:
   - `build_job(pipeline_id, scope, run_id)` - Main entry point
   - `_load_pipeline(pipeline_id)` - Load from h3.pipeline_definition
   - `_resolve_sources(steps)` - Load all referenced sources
   - `_build_stages(steps, sources)` - Convert steps to CoreMachine stages
   - `_wrap_with_bookends(stages)` - Add inventory and finalize stages

**Files to create**:
- `services/h3_pipeline/__init__.py`
- `services/h3_pipeline/factory.py`

---

#### Task 2.4: Create `h3_pipeline` Job Type
**Status**: `[ ]` Not Started
**Effort**: Medium
**Prerequisites**: Task 2.3

**What to do**:
1. Create `jobs/h3_pipeline.py`
2. Follow JobBaseMixin pattern (see `docs_claude/JOB_CREATION_QUICKSTART.md`)
3. This job is a generic executor that runs any pipeline definition
4. Stages are dynamically generated by PipelineFactory

**Files to create**:
- `jobs/h3_pipeline.py`

**Files to modify**:
- `jobs/__init__.py` - Register job
- `services/__init__.py` - Register handlers

---

#### Task 2.5: Create `/api/h3/pipelines` CRUD Endpoints
**Status**: `[ ]` Not Started
**Effort**: Medium
**Prerequisites**: Tasks 2.1-2.4

**What to do**:
1. Create `web_interfaces/h3_pipelines/interface.py`
2. Implement endpoints per [API Design](#pipeline-definition-endpoints)
3. Include validation endpoint

**Files to create**:
- `web_interfaces/h3_pipelines/__init__.py`
- `web_interfaces/h3_pipelines/interface.py`

---

#### Task 2.6: Create `/api/h3/pipelines/run` Execution Endpoint
**Status**: `[ ]` Not Started
**Effort**: Medium
**Prerequisites**: Tasks 2.1-2.5

**What to do**:
1. Add to `web_interfaces/h3_pipelines/interface.py`
2. Endpoint calls PipelineFactory.build_job()
3. Submits generated job to CoreMachine
4. Creates pipeline_run record
5. Returns run_id for tracking

---

#### Task 2.7: Create Simple Pipeline Definition
**Status**: `[ ]` Not Started
**Effort**: Small
**Prerequisites**: Task 2.6

**What to do**:
1. Register "elevation_terrain" pipeline definition
2. Use the JSON from [Example Pipelines](#simple-elevation-stats)
3. Test end-to-end execution

**Phase 2 Complete When**:
- Can define pipelines declaratively via API
- Can execute pipelines with just `pipeline_id` and scope
- Pipeline runs tracked in h3.pipeline_run

---

### PHASE 3: Multi-Step Pipelines

#### Task 3.1: Implement Step Dependency Resolution
**Status**: `[ ]` Not Started
**Effort**: Medium
**Prerequisites**: Phase 2 complete

**What to do**:
1. Enhance PipelineFactory to handle `depends_on` in step definitions
2. Validate that referenced steps exist
3. Order stages based on dependencies (topological sort)

---

#### Task 3.2: Implement Intermediate Output Handling
**Status**: `[ ]` Not Started
**Effort**: Large
**Prerequisites**: Task 3.1

**What to do**:
1. Create `h3_temp` schema for intermediate tables
2. Create `h3.intermediate_cleanup` tracking table
3. Implement table creation/cleanup in handlers
4. Support storage options: temp_table, unlogged_table, blob_parquet
5. Implement cleanup policies

See [Intermediate Output Handling](#intermediate-output-handling) for schema.

---

#### Task 3.3: Implement `h3_weighted_aggregate` Handler
**Status**: `[ ]` Not Started
**Effort**: Large
**Prerequisites**: Task 3.2

**What to do**:
1. Create `services/h3_aggregation/handler_weighted_aggregate.py`
2. Supports weighted_mean, sum, count, max, min aggregations
3. Takes output from previous step as input
4. Writes to h3.zonal_stats_{theme}

---

#### Task 3.4: Implement `h3_spatial_join` Handler
**Status**: `[ ]` Not Started
**Effort**: Large
**Prerequisites**: Task 3.2

**What to do**:
1. Create `services/h3_aggregation/handler_spatial_join.py`
2. Joins point/polygon data with raster values
3. Supports radius-based spatial operations

---

#### Task 3.5: Create Multi-Step Pipeline Example
**Status**: `[ ]` Not Started
**Effort**: Medium
**Prerequisites**: Tasks 3.1-3.4

**What to do**:
1. Register "flood_risk_weighted" pipeline
2. Use JSON from [Example Pipelines](#complex-flood-population-building-risk)
3. Requires FATHOM and WorldPop sources to be registered

---

#### Task 3.6: Test Full Multi-Source Pipeline
**Status**: `[ ]` Not Started
**Effort**: Large
**Prerequisites**: Task 3.5

**What to do**:
1. Register FATHOM flood data source
2. Register WorldPop population source
3. Execute flood_risk_weighted pipeline
4. Verify results in h3.zonal_stats_risk

**Phase 3 Complete When**:
- Multi-step pipelines execute correctly
- Intermediate data handled properly
- Weighted aggregations work

---

### PHASE 4: Production Hardening

Tasks 4.1-4.6 are lower priority and can be tackled after Phases 1-3 are stable.

---

## Quick Start for Claude

**If you're picking up this project fresh**:

1. Read this document (H3_REVIEW.md) for architecture context
2. Read `WIKI_H3.md` for current implementation details
3. Check which tasks are marked complete above
4. Pick up the next incomplete task in sequence
5. Follow the file locations and acceptance criteria
6. Test locally if possible, or deploy and test
7. Mark task complete with date when done

**Key files to understand first**:
- `infrastructure/h3_bootstrap.py` - H3 schema setup
- `infrastructure/h3_repository.py` - H3 data access patterns
- `services/h3_aggregation/handler_raster_zonal.py` - Current zonal stats handler
- `jobs/h3_raster_aggregation.py` - Current aggregation job

**Critical deployment commands**:
```bash
# Deploy
func azure functionapp publish rmhazuregeoapi --python --build remote

# Rebuild schemas after deployment
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance?action=full-rebuild&confirm=yes"

# Health check
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health
```

---

## References

- **WIKI_H3.md** - Current H3 system documentation
- **ARCHITECTURE_REFERENCE.md** - CoreMachine job/stage/task patterns
- **JOB_CREATION_QUICKSTART.md** - How to create CoreMachine jobs
- **Planetary Computer STAC API** - https://planetarycomputer.microsoft.com/api/stac/v1
