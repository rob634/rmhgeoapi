# ============================================================================
# CLAUDE CONTEXT - H3 BOOTSTRAP IMPLEMENTATION PLAN
# ============================================================================
# PRIORITY: 🔴 **HIGH** - Core platform functionality
# STATUS: 📋 **READY FOR IMPLEMENTATION** (14 NOV 2025)
# PURPOSE: Implement Phases 3-7 of H3 land-only grid pyramid bootstrap (resolutions 2-7)
# GOAL: Generate ~55.8M hexagonal cells globally using CoreMachine orchestration
# LAST_REVIEWED: 14 NOV 2025
# DEPENDENCIES:
#   - H3-design.md (architectural design)
#   - jobs/base.py (JobBase ABC for CoreMachine integration)
#   - infrastructure/h3_repository.py (PostgreSQLRepository pattern, safe SQL)
#   - services/handler_bootstrap_res2_spatial_filter.py (Phase 2 - COMPLETE)
# SCOPE: World Bank Agricultural Geography Platform - Multi-resolution geospatial analysis
# VALIDATION: CoreMachine orchestration, psycopg.sql composition, idempotency at all levels
# PATTERNS:
#   - JobBase ABC (6-method interface contract)
#   - PostgreSQLRepository (safe SQL via psycopg.sql.Identifier)
#   - Fan-out parallelism (stage-driven task generation)
#   - Atomic stage advancement ("last task turns out lights")
# ENTRY_POINTS:
#   - POST /api/jobs/submit/bootstrap_h3_land_grid_pyramid (job submission)
#   - GET /api/h3/debug?operation=grid_summary (progress monitoring)
# ESTIMATED_TIME: 7.5 hours development + 15-20 hours automated execution
# INDEX:
#   - Executive Summary: Line 42
#   - Current Status: Line 63
#   - Architecture Alignment: Line 95
#   - Phase 3 (Children Handler): Line 161
#   - Phase 4 (Bootstrap Job): Line 240
#   - Phase 5 (Finalization): Line 404
#   - Phase 6 (Registration): Line 456
#   - Phase 7 (Testing): Line 490
#   - Success Criteria: Line 560
# ============================================================================

# H3 Bootstrap Implementation Plan

**Priority**: 🔴 **HIGH** - Core platform functionality
**Status**: 📋 **READY FOR IMPLEMENTATION** (14 NOV 2025)
**Author**: Robert and Geospatial Claude Legion

---

## Executive Summary

Implement Phases 3-7 of H3 bootstrap to generate a hierarchical land-only hexagonal grid pyramid at resolutions 2-7 (~55.8 million cells globally). This bootstrap operation runs **once** after deployment and creates the foundation for all agricultural and climate data analysis at the World Bank.

**Key Constraints**:
- ✅ **CoreMachine Orchestration** - Use existing JobBase ABC, no custom queue logic
- ✅ **PostgreSQLRepository Pattern** - All SQL via `psycopg.sql` composition (injection prevention)
- ✅ **Idempotency** - Re-runnable at job, stage, and task levels
- ✅ **Config-Driven** - Uses `config.h3_spatial_filter_table` (set to `"system_admin0"`)

**Execution Pattern**: 7-stage job orchestrated by CoreMachine
- Stage 1: Generate resolution 2 + spatial filter (✅ **COMPLETE**, 15 min)
- Stages 2-6: Cascade children for resolutions 3-7 (fan-out parallelism, ~14 hours)
- Stage 7: Finalize pyramid (verify counts, VACUUM, 30 min)

---

## Current Status

### ✅ Completed (Phases 0-2)

**Phase 0**: H3 Schema Creation
- Database: `h3` schema created in PostgreSQL
- Tables: `h3.grids`, `h3.grid_metadata`, `h3.reference_filters` (all deployed, empty)
- Indexes: 24 indexes deployed across 3 tables

**Phase 1**: H3 Repository & Infrastructure
- File: [infrastructure/h3_repository.py](infrastructure/h3_repository.py) - 673 lines
- Pattern: Inherits from `PostgreSQLRepository` (safe SQL via `psycopg.sql.Identifier`)
- Methods: 10 methods including `insert_h3_cells()`, `get_parent_ids()`, `update_spatial_attributes()`

**Phase 2**: Resolution 2 Bootstrap Handler
- File: [services/handler_bootstrap_res2_spatial_filter.py](services/handler_bootstrap_res2_spatial_filter.py) - 370 lines
- Status: ✅ Implemented, registered in `services/__init__.py`
- Function: Generates 5,882 global res 2 cells, spatially filters to ~2,847 land cells
- Config: Uses `config.h3_spatial_filter_table` → `geo.system_admin0` (288 countries)

**Admin API**: Monitoring Endpoint
- Endpoint: `GET /api/h3/debug?operation={op}` (7 operations)
- Status: ✅ Working, deployed to production
- Operations: schema_status, grid_summary, grid_details, reference_filters, sample_cells, etc.

### ⏳ Remaining Work (Phases 3-7)

- ❌ Phase 3: Cascading children handler (res 3-7 generation) - **THIS PLAN**
- ❌ Phase 4: Bootstrap job definition (7-stage JobBase implementation) - **THIS PLAN**
- ❌ Phase 5: Finalization handler (verify, VACUUM) - **THIS PLAN**
- ❌ Phase 6: Job registration (`jobs/__init__.py`) - **THIS PLAN**
- ❌ Phase 7: Integration testing + overnight execution - **THIS PLAN**

---

## Architecture Alignment

### CoreMachine Integration (CRITICAL)

**1. JobBase ABC Contract**

Implement `BootstrapH3LandGridPyramidJob` class inheriting from [jobs/base.py:JobBase](jobs/base.py)

**Required Methods** (6 total):
```python
class BootstrapH3LandGridPyramidJob(JobBase):
    """7-stage job to generate H3 land grid pyramid (res 2-7)."""

    job_type = "bootstrap_h3_land_grid_pyramid"
    description = "Generate hierarchical H3 land grid (resolutions 2-7) via cascade"
    stages = [...]  # 7 stage definitions

    @staticmethod
    def validate_job_parameters(params: dict) -> dict:
        """Validate h3 schema exists, geo.system_admin0 exists."""

    @staticmethod
    def generate_job_id(params: dict) -> str:
        """Deterministic SHA256 hash (idempotency)."""

    @staticmethod
    def create_job_record(job_id: str, params: dict) -> JobRecord:
        """Create JobRecord in app.jobs table."""

    @staticmethod
    def queue_job(job_id: str, params: dict) -> dict:
        """Queue JobQueueMessage to Service Bus."""

    @staticmethod
    def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None) -> List[dict]:
        """
        Generate task parameter dicts for each stage.

        Stage 1: Return single task (res 2 bootstrap - already implemented)
        Stages 2-6: Query parent count, calculate batches, return N task params
        Stage 7: Return single finalization task
        """

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """Aggregate all stage results, verify cell counts."""
```

**CoreMachine Handles** (you don't implement):
- Service Bus queue management
- Task execution via task handlers
- Stage advancement detection ("last task turns out lights")
- Retry logic and error handling
- Task result aggregation in `app.tasks` table

**2. PostgreSQLRepository Pattern**

**✅ CORRECT - Use H3Repository methods**:
```python
from infrastructure.h3_repository import H3Repository

repo = H3Repository()

# Method internally uses psycopg.sql.Identifier for safe SQL:
parent_ids = repo.get_parent_ids('land_res2')
# Generates: SELECT h3_index, parent_res2 FROM "h3"."grids" WHERE grid_id = %s

cells = [{'h3_index': 123, 'resolution': 3, 'geom_wkt': 'POLYGON(...)'}]
repo.insert_h3_cells(cells, grid_id='land_res3')
# Uses: INSERT INTO "h3"."grids" (...) VALUES (%s, %s, ...) ON CONFLICT DO NOTHING
```

**❌ WRONG - Never use string formatting**:
```python
# ❌ SQL INJECTION RISK!
query = f"SELECT * FROM {schema}.{table} WHERE id = {user_input}"
cursor.execute(query)

# ❌ WRONG - Bypasses repository pattern
query = "INSERT INTO h3.grids ..."  # Should use H3Repository.insert_h3_cells()
```

**H3Repository Methods Available**:
- `insert_h3_cells(cells, grid_id)` - Bulk insert with ON CONFLICT DO NOTHING
- `get_parent_ids(grid_id)` - Load parent H3 indices for cascade
- `update_spatial_attributes(grid_id, spatial_filter_table)` - Spatial join (res 2 only)
- `get_cell_count(grid_id)` - Count cells for batch sizing
- `grid_exists(grid_id)` - Idempotency check
- `insert_reference_filter(filter_name, h3_indices, ...)` - Store parent ID arrays
- `get_reference_filter(filter_name)` - Retrieve parent ID arrays
- `update_grid_metadata(grid_id, status, cell_count, ...)` - Track progress

---

## Phase 3: Cascading Children Handler

**File**: `services/handler_generate_h3_children_batch.py`
**Estimated Time**: 2 hours
**Status**: ❌ **NOT IMPLEMENTED**

### Purpose

Generate child H3 hexagons from parent indices for resolutions 3-7. **NO spatial operations** - uses H3's deterministic parent-child relationships.

### Task Handler Interface

```python
def generate_h3_children_batch(task_params: dict) -> dict:
    """
    Generate children for a batch of parent H3 cells.

    Args:
        task_params: dict containing:
            - parent_grid_id: str (e.g., 'land_res2')
            - target_resolution: int (3-7)
            - grid_id: str (e.g., 'land_res3')
            - batch_start: int (parent batch start index)
            - batch_size: int (number of parents to process)
            - job_id: str (source job ID for tracking)

    Returns:
        dict containing:
            - success: bool
            - result: {
                "parents_processed": int,
                "children_generated": int,
                "grid_id": str,
                "resolution": int
              }
            - error: str (if success=False)
    """
```

### Implementation Logic

```python
import logging
from typing import Dict, Any, List, Tuple
import h3
from shapely.geometry import Polygon

from infrastructure.h3_repository import H3Repository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "GenerateH3Children")

def generate_h3_children_batch(task_params: dict) -> dict:
    """Generate children for batch of parent H3 cells."""

    # Extract parameters
    parent_grid_id = task_params.get('parent_grid_id')
    target_resolution = task_params.get('target_resolution')
    grid_id = task_params.get('grid_id')
    batch_start = task_params.get('batch_start', 0)
    batch_size = task_params.get('batch_size', 500)
    job_id = task_params.get('job_id', 'unknown')

    logger.info(f"🔄 Generating res {target_resolution} children from {parent_grid_id}")
    logger.info(f"   Batch: {batch_start} to {batch_start + batch_size}")

    # Initialize repository
    repo = H3Repository()

    # STEP 1: Load parent IDs for this batch
    # H3Repository.get_parent_ids uses safe SQL composition
    all_parent_ids = repo.get_parent_ids(parent_grid_id)
    batch_parent_ids = all_parent_ids[batch_start:batch_start + batch_size]

    logger.info(f"   Processing {len(batch_parent_ids)} parents")

    # STEP 2: Generate children using h3-py
    children_cells = []

    for h3_index, parent_res2 in batch_parent_ids:
        # Generate 7 children for this parent (H3 deterministic)
        child_indices = h3.cell_to_children(h3_index, target_resolution)

        for child_index in child_indices:
            # Convert to int if string
            if isinstance(child_index, str):
                child_index_int = int(child_index, 16)
            else:
                child_index_int = child_index

            # Get geometry as WKT
            boundary = h3.cell_to_boundary(child_index, geo_json=True)
            coords = [(lon, lat) for lat, lon in boundary]
            coords.append(coords[0])  # Close polygon
            polygon = Polygon(coords)
            geom_wkt = polygon.wkt

            # Create cell dict
            children_cells.append({
                'h3_index': child_index_int,
                'resolution': target_resolution,
                'geom_wkt': geom_wkt,
                'parent_h3_index': h3_index,
                'parent_res2': parent_res2  # Inherit from parent (no lookup!)
            })

    logger.info(f"   Generated {len(children_cells)} children")

    # STEP 3: Bulk insert using H3Repository (safe SQL, ON CONFLICT DO NOTHING)
    rows_inserted = repo.insert_h3_cells(
        cells=children_cells,
        grid_id=grid_id,
        grid_type='land',
        source_job_id=job_id
    )

    logger.info(f"✅ Inserted {rows_inserted} children to h3.grids (grid_id={grid_id})")

    return {
        "success": True,
        "result": {
            "parents_processed": len(batch_parent_ids),
            "children_generated": len(children_cells),
            "rows_inserted": rows_inserted,
            "grid_id": grid_id,
            "resolution": target_resolution,
            "batch_start": batch_start,
            "batch_size": batch_size
        }
    }
```

### Registration

Add to `services/__init__.py`:
```python
from .handler_generate_h3_children_batch import generate_h3_children_batch

ALL_HANDLERS = {
    # ... existing handlers ...
    "generate_h3_children_batch": generate_h3_children_batch,
}
```

---

## Phase 4: Bootstrap Job Definition

**File**: `jobs/bootstrap_h3_land_grid_pyramid.py`
**Estimated Time**: 2 hours
**Status**: ❌ **NOT IMPLEMENTED**

### Job Class Structure

```python
from typing import List, Dict, Any
import hashlib
import json

from jobs.base import JobBase
from infrastructure.h3_repository import H3Repository

class BootstrapH3LandGridPyramidJob(JobBase):
    """
    Bootstrap H3 Land Grid Pyramid (Resolutions 2-7).

    7-stage job orchestrated by CoreMachine:
    - Stage 1: Generate res 2 + spatial filter (~15 min, single task)
    - Stages 2-6: Cascade children for res 3-7 (fan-out, ~14 hours total)
    - Stage 7: Finalize pyramid (verify, VACUUM, ~30 min)

    Expected Results:
    - Res 2: ~2,847 cells (land-filtered)
    - Res 3: ~19,929 cells
    - Res 4: ~139,503 cells
    - Res 5: ~976,521 cells
    - Res 6: ~6,835,647 cells (primary working resolution, ~10km)
    - Res 7: ~47,849,529 cells (finest resolution)
    - Total: ~55,823,976 land cells globally
    """

    job_type = "bootstrap_h3_land_grid_pyramid"
    description = "Generate hierarchical H3 land grid pyramid (resolutions 2-7) via cascade"

    stages = [
        {
            "number": 1,
            "name": "bootstrap_res2",
            "task_type": "bootstrap_res2_with_spatial_filter",
            "parallelism": "single",
            "description": "Generate res 2 grid + spatial filter with geo.system_admin0 (~15 min)"
        },
        {
            "number": 2,
            "name": "generate_res3",
            "task_type": "generate_h3_children_batch",
            "parallelism": "fan_out",
            "description": "Generate res 3 children from res 2 parents (~2 min)"
        },
        {
            "number": 3,
            "name": "generate_res4",
            "task_type": "generate_h3_children_batch",
            "parallelism": "fan_out",
            "description": "Generate res 4 children from res 3 parents (~15 min)"
        },
        {
            "number": 4,
            "name": "generate_res5",
            "task_type": "generate_h3_children_batch",
            "parallelism": "fan_out",
            "description": "Generate res 5 children from res 4 parents (~2 hours)"
        },
        {
            "number": 5,
            "name": "generate_res6",
            "task_type": "generate_h3_children_batch",
            "parallelism": "fan_out",
            "description": "Generate res 6 children from res 5 parents (~6 hours)"
        },
        {
            "number": 6,
            "name": "generate_res7",
            "task_type": "generate_h3_children_batch",
            "parallelism": "fan_out",
            "description": "Generate res 7 children from res 6 parents (~7 hours)"
        },
        {
            "number": 7,
            "name": "finalize_pyramid",
            "task_type": "finalize_h3_pyramid",
            "parallelism": "single",
            "description": "Verify cell counts, create final indexes, VACUUM (~30 min)"
        }
    ]

    @staticmethod
    def validate_job_parameters(params: dict) -> dict:
        """
        Validate h3 schema exists and spatial filter table exists.

        Raises:
            ValueError: If h3 schema or geo.system_admin0 table missing
        """
        from config import get_config
        from infrastructure.postgresql import PostgreSQLRepository

        config = get_config()
        spatial_filter_table = f"geo.{config.h3_spatial_filter_table}"

        # Check h3 schema exists
        repo = PostgreSQLRepository(schema_name='h3')
        # ... schema validation logic ...

        # Check spatial filter table exists
        # ... table validation logic ...

        # No additional parameters needed (bootstrap is deterministic)
        return params or {}

    @staticmethod
    def generate_job_id(params: dict) -> str:
        """
        Generate deterministic job ID for idempotency.

        Bootstrap job has no parameters, so job ID is always the same.
        This ensures re-submissions return existing job.
        """
        job_type = "bootstrap_h3_land_grid_pyramid"
        params_hash = hashlib.sha256(json.dumps({}, sort_keys=True).encode()).hexdigest()[:16]
        return f"{job_type}-{params_hash}"

    @staticmethod
    def create_job_record(job_id: str, params: dict) -> 'JobRecord':
        """Create JobRecord in app.jobs table."""
        from infrastructure.job_repository import JobRepository

        repo = JobRepository()
        return repo.create_job_record(
            job_id=job_id,
            job_type="bootstrap_h3_land_grid_pyramid",
            parameters=params or {},
            stage=1  # Start at stage 1
        )

    @staticmethod
    def queue_job(job_id: str, params: dict) -> dict:
        """Queue JobQueueMessage to Service Bus."""
        from infrastructure.service_bus import ServiceBusAdapter

        adapter = ServiceBusAdapter()
        return adapter.queue_job(
            job_id=job_id,
            job_type="bootstrap_h3_land_grid_pyramid",
            parameters=params or {}
        )

    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        """
        Generate task parameter dicts for each stage.

        Stage 1: Single task for res 2 bootstrap
        Stages 2-6: Fan-out based on parent count (query DB)
        Stage 7: Single finalization task
        """
        repo = H3Repository()

        if stage == 1:
            # Stage 1: Bootstrap res 2 with spatial filtering
            return [{
                "task_id": f"{job_id[:8]}-s1-res2",
                "resolution": 2,
                "grid_id": "land_res2",
                "filter_name": "land_res2",
                # spatial_filter_table will use config default (geo.system_admin0)
                "job_id": job_id
            }]

        elif stage in [2, 3, 4, 5, 6]:
            # Stages 2-6: Generate children from previous resolution
            resolution_map = {2: 3, 3: 4, 4: 5, 5: 6, 6: 7}
            target_resolution = resolution_map[stage]
            parent_resolution = target_resolution - 1
            parent_grid_id = f"land_res{parent_resolution}"
            grid_id = f"land_res{target_resolution}"

            # Query parent count from database
            parent_count = repo.get_cell_count(parent_grid_id)

            # Calculate batch size (tune for performance vs parallelism)
            # Smaller batches = more parallelism, larger batches = less overhead
            if target_resolution == 3:
                batch_size = 500   # ~6 batches (2,847 / 500)
            elif target_resolution == 4:
                batch_size = 2000  # ~10 batches (19,929 / 2000)
            elif target_resolution == 5:
                batch_size = 5000  # ~28 batches (139,503 / 5000)
            elif target_resolution == 6:
                batch_size = 10000 # ~98 batches (976,521 / 10000)
            elif target_resolution == 7:
                batch_size = 50000 # ~137 batches (6,835,647 / 50000)

            num_batches = (parent_count + batch_size - 1) // batch_size

            # Create task parameters for each batch
            tasks = []
            for i in range(num_batches):
                tasks.append({
                    "task_id": f"{job_id[:8]}-s{stage}-batch{i:04d}",
                    "parent_grid_id": parent_grid_id,
                    "target_resolution": target_resolution,
                    "grid_id": grid_id,
                    "batch_start": i * batch_size,
                    "batch_size": batch_size,
                    "job_id": job_id
                })

            return tasks

        elif stage == 7:
            # Stage 7: Finalization
            return [{
                "task_id": f"{job_id[:8]}-s7-finalize",
                "job_id": job_id
            }]

        else:
            raise ValueError(f"Invalid stage number: {stage}")

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """
        Aggregate all stage results and verify cell counts.

        Returns final summary report with cell counts per resolution.
        """
        repo = H3Repository()

        # Query final cell counts from h3.grids
        result = {
            "pyramid_complete": True,
            "schema": "h3",
            "resolutions": {},
            "total_cells": 0
        }

        for resolution in [2, 3, 4, 5, 6, 7]:
            grid_id = f"land_res{resolution}"
            cell_count = repo.get_cell_count(grid_id)

            result["resolutions"][str(resolution)] = {
                "cell_count": cell_count,
                "grid_id": grid_id,
                "status": "completed"
            }
            result["total_cells"] += cell_count

        return result
```

---

## Phase 5: Finalization Handler

**File**: `services/handler_finalize_h3_pyramid.py`
**Estimated Time**: 1 hour
**Status**: ❌ **NOT IMPLEMENTED**

### Purpose

Verify cell counts match expected values, update metadata, VACUUM ANALYZE for performance.

### Implementation

```python
import logging
from typing import Dict, Any
from infrastructure.h3_repository import H3Repository

logger = logging.getLogger(__name__)

def finalize_h3_pyramid(task_params: dict) -> dict:
    """
    Finalize H3 pyramid bootstrap.

    - Verify cell counts match expected
    - Update h3.grid_metadata status to 'completed'
    - Run VACUUM ANALYZE on h3.grids for optimal query performance
    """

    job_id = task_params.get('job_id', 'unknown')
    logger.info(f"🏁 Finalizing H3 pyramid for job {job_id}")

    repo = H3Repository()

    # Expected cell counts (land-only, ~48.4% of global)
    expected_counts = {
        2: 2847,      # Actual from spatial filter
        3: 19929,     # 2847 × 7
        4: 139503,    # 19929 × 7
        5: 976521,    # 139503 × 7
        6: 6835647,   # 976521 × 7
        7: 47849529   # 6835647 × 7
    }

    # Verify counts and update metadata
    summary = {}
    for resolution in [2, 3, 4, 5, 6, 7]:
        grid_id = f"land_res{resolution}"
        actual_count = repo.get_cell_count(grid_id)
        expected_count = expected_counts[resolution]

        # Allow 10% variance (spatial filter variations)
        variance = abs(actual_count - expected_count) / expected_count
        status = "completed" if variance < 0.10 else "warning"

        summary[f"res{resolution}"] = {
            "grid_id": grid_id,
            "actual_count": actual_count,
            "expected_count": expected_count,
            "variance_pct": round(variance * 100, 2),
            "status": status
        }

        # Update grid_metadata
        repo.update_grid_metadata(
            grid_id=grid_id,
            status=status,
            cell_count=actual_count
        )

    # VACUUM ANALYZE for query performance
    logger.info("🔧 Running VACUUM ANALYZE on h3.grids...")
    # ... VACUUM ANALYZE logic via repository ...

    logger.info("✅ H3 pyramid finalization complete")

    return {
        "success": True,
        "result": {
            "total_cells": sum(s["actual_count"] for s in summary.values()),
            "resolutions": summary,
            "vacuum_completed": True
        }
    }
```

---

## Phase 6: Job Registration

**File**: `jobs/__init__.py`
**Estimated Time**: 30 minutes
**Status**: ❌ **NOT IMPLEMENTED**

### Implementation

Add import and register in ALL_JOBS:

```python
from .bootstrap_h3_land_grid_pyramid import BootstrapH3LandGridPyramidJob

ALL_JOBS = {
    # ... existing jobs ...
    "bootstrap_h3_land_grid_pyramid": BootstrapH3LandGridPyramidJob,
}
```

Verify registration:
```bash
# Health endpoint should show new job type
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health | \
  python3 -c "import sys, json; d=json.load(sys.stdin); print(d['components']['jobs']['details']['available_jobs'])"
```

---

## Phase 7: Integration Testing

**Estimated Time**: 2 hours development + 15-20 hours automated execution
**Status**: ❌ **NOT IMPLEMENTED**

### Testing Steps

**1. Deploy to Azure Functions**
```bash
# From dev branch (ensure all code committed)
func azure functionapp publish rmhazuregeoapi --python --build remote
```

**2. Submit Bootstrap Job**
```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/bootstrap_h3_land_grid_pyramid \
  -H "Content-Type: application/json" \
  -d '{}'
```

Expected response:
```json
{
  "job_id": "bootstrap_h3_land_grid_pyramid-<hash>",
  "status": "queued",
  "message": "Job queued successfully"
}
```

**3. Monitor Progress via H3 Admin API**
```bash
# Grid summary (shows cell counts per resolution)
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/h3/debug?operation=grid_summary" | python3 -m json.tool

# Schema status (shows table row counts)
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/h3/debug?operation=schema_status" | python3 -m json.tool
```

**4. Monitor CoreMachine Tables**
```bash
# Job status
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/jobs/{JOB_ID}" | python3 -m json.tool

# Task status (shows all tasks across all stages)
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/tasks/{JOB_ID}" | python3 -m json.tool
```

**5. Validation Queries**
```sql
-- Verify final cell counts
SELECT
    resolution,
    COUNT(*) as total_cells,
    COUNT(*) FILTER (WHERE is_land = TRUE) as land_cells,
    COUNT(DISTINCT parent_res2) as unique_res2_parents
FROM h3.grids
GROUP BY resolution
ORDER BY resolution;

-- Expected results:
-- Res 2: ~2,847 cells
-- Res 3: ~19,929 cells
-- Res 4: ~139,503 cells
-- Res 5: ~976,521 cells
-- Res 6: ~6,835,647 cells
-- Res 7: ~47,849,529 cells
-- Total: ~55,823,976 cells
```

### Success Criteria

✅ **Job Submission**: Job queued successfully via HTTP POST
✅ **Stage Progression**: All 7 stages complete sequentially
✅ **Cell Counts**: Final counts within 10% of expected values
✅ **Parent-Child Links**: All children have valid parent_h3_index
✅ **Res2 Propagation**: All cells inherit parent_res2 from original spatial filter
✅ **Metadata**: h3.grid_metadata shows 'completed' status for all grids
✅ **Idempotency**: Re-submitting job returns existing job_id
✅ **Performance**: Total execution time 15-20 hours

---

## Implementation Checklist

### Phase 3: Cascading Children Handler
- [ ] Create `services/handler_generate_h3_children_batch.py`
- [ ] Implement `generate_h3_children_batch(task_params)` function
- [ ] Use `H3Repository.get_parent_ids()` for safe parent loading
- [ ] Use `H3Repository.insert_h3_cells()` for safe bulk insert
- [ ] Register in `services/__init__.py` ALL_HANDLERS
- [ ] Test handler locally with sample parent IDs

### Phase 4: Bootstrap Job Definition
- [ ] Create `jobs/bootstrap_h3_land_grid_pyramid.py`
- [ ] Implement `BootstrapH3LandGridPyramidJob` class extending JobBase
- [ ] Define 7 stages with correct task_type and parallelism
- [ ] Implement `create_tasks_for_stage()` with dynamic batching
- [ ] Implement `validate_job_parameters()` (check h3 schema, geo.system_admin0)
- [ ] Implement remaining JobBase methods
- [ ] Verify all methods use H3Repository (no raw SQL)

### Phase 5: Finalization Handler
- [ ] Create `services/handler_finalize_h3_pyramid.py`
- [ ] Implement `finalize_h3_pyramid(task_params)` function
- [ ] Verify cell counts against expected values
- [ ] Update h3.grid_metadata with 'completed' status
- [ ] Run VACUUM ANALYZE via repository
- [ ] Register in `services/__init__.py` ALL_HANDLERS

### Phase 6: Job Registration
- [ ] Add import to `jobs/__init__.py`
- [ ] Register in ALL_JOBS dictionary
- [ ] Verify via health endpoint

### Phase 7: Integration Testing
- [ ] Commit all code to dev branch
- [ ] Deploy to Azure Functions
- [ ] Submit bootstrap job via HTTP POST
- [ ] Monitor via H3 admin API
- [ ] Monitor via CoreMachine debug endpoints
- [ ] Validate final cell counts
- [ ] Test idempotency (re-submit job)
- [ ] Document execution time

---

## Expected Execution Timeline

| Stage | Resolution | Task Type | Parallelism | Estimated Time |
|-------|-----------|-----------|-------------|----------------|
| 1 | Res 2 | bootstrap_res2_with_spatial_filter | single (1 task) | ~15 min |
| 2 | Res 3 | generate_h3_children_batch | fan_out (~6 tasks) | ~2 min |
| 3 | Res 4 | generate_h3_children_batch | fan_out (~10 tasks) | ~15 min |
| 4 | Res 5 | generate_h3_children_batch | fan_out (~28 tasks) | ~2 hours |
| 5 | Res 6 | generate_h3_children_batch | fan_out (~98 tasks) | ~6 hours |
| 6 | Res 7 | generate_h3_children_batch | fan_out (~137 tasks) | ~7 hours |
| 7 | Finalize | finalize_h3_pyramid | single (1 task) | ~30 min |

**Total**: ~15-16 hours (overnight execution)

---

## Success Metrics

| Metric | Target | Validation |
|--------|--------|------------|
| Total cells generated | ~55.8M | Query h3.grids: `SELECT COUNT(*) FROM h3.grids` |
| Res 2 land cells | ~2,847 | Based on geo.system_admin0 spatial filter |
| Res 7 cells | ~47.8M | Largest resolution, primary storage load |
| All children linked | 100% | `SELECT COUNT(*) FROM h3.grids WHERE parent_h3_index IS NULL AND resolution > 2` = 0 |
| parent_res2 propagated | 100% | All cells have parent_res2 value |
| Execution time | 15-20 hours | Monitor via Application Insights |
| Idempotency | Pass | Re-submit job returns same job_id |

---

## Key Takeaways

1. ✅ **CoreMachine Orchestration** - No custom queue logic, JobBase ABC enforces contract
2. ✅ **PostgreSQLRepository Pattern** - All SQL via H3Repository, psycopg.sql composition
3. ✅ **Fan-Out Parallelism** - Stages 2-6 query parent count, create batch tasks dynamically
4. ✅ **Atomic Stage Advancement** - CoreMachine handles "last task turns out lights"
5. ✅ **Idempotency** - Job/task level deduplication, ON CONFLICT DO NOTHING in SQL
6. ✅ **Config-Driven** - Spatial filter uses `config.h3_spatial_filter_table` (system_admin0)
7. ✅ **Monitoring** - H3 admin API + CoreMachine debug endpoints for progress tracking

---

**Document Status**: 📋 **READY FOR IMPLEMENTATION**
**Priority**: 🔴 **HIGH** - Core platform functionality
**Author**: Robert and Geospatial Claude Legion
**Last Updated**: 14 NOV 2025
