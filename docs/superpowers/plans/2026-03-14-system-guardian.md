# SystemGuardian Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 3-trigger janitor system with a single ordered-phase sweep pipeline that explicitly covers Risk G (orphaned tasks) and Risk H (stuck stage advancement).

**Architecture:** Single `SystemGuardian` class with 4 ordered phases (task recovery → stage recovery → job recovery → consistency). Single 5-minute timer trigger replaces 3 independent triggers. `GuardianRepository` provides all DB queries. Two-phase audit trail (INSERT at start, UPDATE at end).

**Tech Stack:** Python 3.12, psycopg3, Azure Functions timer triggers, Azure Service Bus, Pydantic models

**Spec:** `docs/superpowers/specs/2026-03-14-system-guardian-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `services/system_guardian.py` | **Create** | Sweep orchestration, phase methods, config, result models |
| `infrastructure/guardian_repository.py` | **Create** | All DB queries for detection + fix operations, audit logging |
| `core/models/janitor.py` | **Modify** | Add `SWEEP` run type, `phases` field to `JanitorRun` |
| `triggers/janitor/__init__.py` | **Modify** | Replace old exports with `system_guardian_handler` |
| `triggers/janitor/system_guardian.py` | **Create** | Single timer trigger handler |
| `triggers/timers/timer_bp.py` | **Modify** | Replace 3 janitor triggers with 1 sweep trigger |
| `triggers/admin/admin_janitor.py` | **Modify** | Update HTTP endpoints to use SystemGuardian |
| `triggers/janitor/http_triggers.py` | **Modify** | Update run handler to use SystemGuardian |
| `core/schema/sql_generator.py` | **Modify** | Add `phases` JSONB column to janitor_runs table |
| `triggers/janitor/task_watchdog.py` | **Delete** | Replaced by Phase 1 |
| `triggers/janitor/job_health.py` | **Delete** | Replaced by Phase 3 |
| `triggers/janitor/orphan_detector.py` | **Delete** | Replaced by Phases 2-4 |
| `services/janitor_service.py` | **Delete** | Replaced by SystemGuardian |
| `infrastructure/janitor_repository.py` | **Delete** | Replaced by GuardianRepository |
| `tests/test_system_guardian.py` | **Create** | Unit tests for SystemGuardian |
| `tests/test_guardian_repository.py` | **Create** | Unit tests for GuardianRepository |

---

## Chunk 1: Foundation — Models, Config, Repository

### Task 1: Update Audit Models

**Files:**
- Modify: `core/models/janitor.py`

- [ ] **Step 1: Add SWEEP to JanitorRunType and phases field to JanitorRun**

```python
# In JanitorRunType enum, add:
SWEEP = "sweep"

# In JanitorRun model, add after error_details field:
phases: Optional[Dict[str, Any]] = Field(
    default=None,
    description="Per-phase breakdown for sweep runs"
)
```

The full updated `core/models/janitor.py`:

```python
# ============================================================================
# GUARDIAN AUDIT MODELS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Core - Maintenance operation audit trail
# PURPOSE: Track SystemGuardian sweeps and legacy janitor runs
# LAST_REVIEWED: 14 MAR 2026
# EXPORTS: JanitorRun, JanitorRunType, JanitorRunStatus
# DEPENDENCIES: pydantic
# ============================================================================
"""
Guardian/Janitor Audit Models.

Pydantic models for janitor_runs audit table. Logs all SystemGuardian
sweep operations and legacy maintenance runs for audit and monitoring.

Exports:
    JanitorRun: Audit record for maintenance operations
    JanitorRunType: Types of maintenance runs
    JanitorRunStatus: Run status enumeration
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, field_serializer
import uuid


class JanitorRunType(str, Enum):
    """Types of maintenance runs."""
    SWEEP = "sweep"
    TASK_WATCHDOG = "task_watchdog"       # Legacy
    JOB_HEALTH = "job_health"             # Legacy
    ORPHAN_DETECTOR = "orphan_detector"   # Legacy


class JanitorRunStatus(str, Enum):
    """Status of a maintenance run."""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JanitorRun(BaseModel):
    """
    Database representation of a maintenance run.

    Records all SystemGuardian sweep operations for audit trail and monitoring.
    Each sweep() call creates one JanitorRun record.

    Fields:
    - run_id: Unique identifier (UUID)
    - run_type: Type of operation (sweep for SystemGuardian)
    - started_at: When the run started
    - completed_at: When the run completed (optional until done)
    - status: Current status (running/completed/failed)
    - items_scanned: Number of records examined
    - items_fixed: Number of records updated/fixed
    - actions_taken: Flat list of all actions performed
    - phases: Per-phase breakdown (sweep runs only)
    - error_details: Error message if run failed
    - duration_ms: Run duration in milliseconds
    """

    model_config = ConfigDict()

    @field_serializer('started_at', 'completed_at')
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

    run_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique run identifier (UUID)"
    )
    run_type: str = Field(
        ...,
        description="Type of run (sweep, task_watchdog, job_health, orphan_detector)"
    )
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the run started"
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="When the run completed"
    )
    duration_ms: Optional[int] = Field(
        default=None,
        description="Run duration in milliseconds"
    )
    status: str = Field(
        default="running",
        description="Run status (running, completed, failed)"
    )
    items_scanned: int = Field(
        default=0,
        ge=0,
        description="Number of records scanned"
    )
    items_fixed: int = Field(
        default=0,
        ge=0,
        description="Number of records fixed"
    )
    actions_taken: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of actions taken during the run"
    )
    phases: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Per-phase breakdown for sweep runs"
    )
    error_details: Optional[str] = Field(
        default=None,
        description="Error message if the run failed"
    )


__all__ = [
    'JanitorRun',
    'JanitorRunType',
    'JanitorRunStatus'
]
```

- [ ] **Step 2: Commit**

```bash
git add core/models/janitor.py
git commit -m "feat(guardian): add SWEEP run type and phases field to audit model"
```

---

### Task 2: Add phases column to schema DDL

**Files:**
- Modify: `core/schema/sql_generator.py`

- [ ] **Step 1: Find the janitor_runs table generation**

The `JanitorRun` Pydantic model is used by `generate_table_composed()` to auto-generate DDL. Adding the `phases` field to the model (Task 1) should automatically include it in the generated DDL. Verify by checking how `Optional[Dict[str, Any]]` maps to SQL types.

Search for `generate_table_composed` to understand the type mapping. The Pydantic-to-SQL mapper should map `Optional[Dict[str, Any]]` to `JSONB` (same as `actions_taken`).

- [ ] **Step 2: Verify the type mapping handles the new field**

Run:
```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
conda activate azgeo
python -c "
from core.schema.sql_generator import SchemaDeployer
deployer = SchemaDeployer('app')
# Check if JanitorRun model includes phases field
from core.models.janitor import JanitorRun
fields = JanitorRun.model_fields
print('phases' in fields, fields.get('phases'))
"
```

Expected: `True` and field info showing `Optional[Dict[str, Any]]`

- [ ] **Step 3: Commit**

```bash
git add core/schema/sql_generator.py
git commit -m "feat(guardian): add phases JSONB column to janitor_runs DDL"
```

Note: If the auto-generation doesn't pick up the new field, manually add the column in the `janitor_runs` table generation section of `sql_generator.py`.

---

### Task 3: Create GuardianRepository

**Files:**
- Create: `infrastructure/guardian_repository.py`
- Create: `tests/test_guardian_repository.py`

- [ ] **Step 1: Write unit tests for GuardianRepository query methods**

Create `tests/test_guardian_repository.py`:

```python
"""
Tests for GuardianRepository.

Tests query construction and parameter handling. Does NOT test against
a real database — these verify SQL is built correctly and results are
transformed properly.
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone


class TestGuardianRepositorySchemaReady:
    """Test schema readiness check."""

    def test_schema_ready_returns_true_when_table_exists(self):
        from infrastructure.guardian_repository import GuardianRepository
        repo = GuardianRepository.__new__(GuardianRepository)
        repo.schema_name = "app"
        repo._execute_query = MagicMock(return_value={"1": 1})
        assert repo.schema_ready() is True

    def test_schema_ready_returns_false_when_table_missing(self):
        from infrastructure.guardian_repository import GuardianRepository
        repo = GuardianRepository.__new__(GuardianRepository)
        repo.schema_name = "app"
        repo._execute_query = MagicMock(return_value=None)
        assert repo.schema_ready() is False

    def test_schema_ready_returns_false_on_exception(self):
        from infrastructure.guardian_repository import GuardianRepository
        repo = GuardianRepository.__new__(GuardianRepository)
        repo.schema_name = "app"
        repo._execute_query = MagicMock(side_effect=Exception("DB down"))
        assert repo.schema_ready() is False


class TestGuardianRepositoryMarkOperations:
    """Test fix operations."""

    def test_mark_tasks_failed_returns_zero_for_empty_list(self):
        from infrastructure.guardian_repository import GuardianRepository
        repo = GuardianRepository.__new__(GuardianRepository)
        repo.schema_name = "app"
        assert repo.mark_tasks_failed([], "test error") == 0

    def test_mark_tasks_failed_calls_execute_query(self):
        from infrastructure.guardian_repository import GuardianRepository
        repo = GuardianRepository.__new__(GuardianRepository)
        repo.schema_name = "app"
        repo._execute_query = MagicMock(return_value=[{"task_id": "t1"}, {"task_id": "t2"}])
        repo._error_context = MagicMock(return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock(return_value=False)))
        count = repo.mark_tasks_failed(["t1", "t2"], "timeout")
        assert count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
conda activate azgeo
python -m pytest tests/test_guardian_repository.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'infrastructure.guardian_repository'`

- [ ] **Step 3: Create GuardianRepository**

Create `infrastructure/guardian_repository.py`:

```python
# ============================================================================
# GUARDIAN REPOSITORY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - SystemGuardian DB operations
# PURPOSE: Detection queries and fix operations for distributed systems recovery
# LAST_REVIEWED: 14 MAR 2026
# EXPORTS: GuardianRepository
# DEPENDENCIES: postgresql, psycopg
# ============================================================================
"""
GuardianRepository — DB operations for SystemGuardian.

All detection queries and fix operations organized by sweep phase.
Extends PostgreSQLRepository for connection management and query execution.

Phase 1: Task Recovery — orphaned PENDING/QUEUED, stale PROCESSING
Phase 2: Stage Recovery — zombie stages (all tasks terminal, stage stuck)
Phase 3: Job Recovery — failed task propagation, stuck QUEUED, ancient stale
Phase 4: Consistency — orphaned tasks (parent job missing)
Audit: Two-phase sweep logging (INSERT at start, UPDATE at end)
"""

import json
import uuid
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from contextlib import contextmanager

from psycopg import sql

from infrastructure.postgresql import PostgreSQLRepository

logger = logging.getLogger(__name__)


class GuardianRepository(PostgreSQLRepository):
    """DB operations for SystemGuardian anomaly detection and recovery."""

    # ================================================================
    # SCHEMA READINESS
    # ================================================================

    def schema_ready(self) -> bool:
        """
        Check if app schema exists before running queries.

        Prevents errors during schema rebuilds. Returns True if
        app.jobs table exists, False otherwise.
        """
        try:
            result = self._execute_query(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = %s AND table_name = %s",
                (self.schema_name, "jobs"),
                fetch='one'
            )
            return result is not None
        except Exception:
            return False

    # ================================================================
    # PHASE 1: TASK RECOVERY
    # ================================================================

    def get_orphaned_pending_tasks(self, timeout_minutes: int) -> List[Dict[str, Any]]:
        """Tasks stuck in PENDING > timeout (Risk G: message never delivered)."""
        query = sql.SQL("""
            SELECT
                t.task_id, t.parent_job_id, t.job_type, t.task_type,
                t.stage, t.task_index, t.status, t.last_pulse,
                t.parameters, t.updated_at, t.created_at, t.retry_count,
                EXTRACT(EPOCH FROM (NOW() - t.created_at)) / 60 AS minutes_stuck
            FROM {schema}.tasks t
            WHERE t.status = 'pending'
              AND t.created_at < NOW() - make_interval(mins => %s)
            ORDER BY t.created_at ASC
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get orphaned pending tasks"):
            result = self._execute_query(query, (timeout_minutes,), fetch='all')
            count = len(result) if result else 0
            if count > 0:
                logger.info(f"[GUARDIAN] Phase 1a: {count} orphaned PENDING tasks (>{timeout_minutes}min)")
            return result or []

    def get_orphaned_queued_tasks(self, timeout_minutes: int) -> List[Dict[str, Any]]:
        """Tasks stuck in QUEUED > timeout (Risk G: worker never picked up)."""
        query = sql.SQL("""
            SELECT
                t.task_id, t.parent_job_id, t.job_type, t.task_type,
                t.stage, t.task_index, t.status, t.last_pulse,
                t.parameters, t.updated_at, t.created_at, t.retry_count,
                EXTRACT(EPOCH FROM (NOW() - t.created_at)) / 60 AS minutes_stuck
            FROM {schema}.tasks t
            WHERE t.status = 'queued'
              AND t.created_at < NOW() - make_interval(mins => %s)
            ORDER BY t.created_at ASC
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get orphaned queued tasks"):
            result = self._execute_query(query, (timeout_minutes,), fetch='all')
            count = len(result) if result else 0
            if count > 0:
                logger.info(f"[GUARDIAN] Phase 1b: {count} orphaned QUEUED tasks (>{timeout_minutes}min)")
            return result or []

    def get_stale_processing_tasks(
        self, timeout_minutes: int, exclude_types: List[str]
    ) -> List[Dict[str, Any]]:
        """Function App tasks stuck in PROCESSING > timeout."""
        query = sql.SQL("""
            SELECT
                t.task_id, t.parent_job_id, t.job_type, t.task_type,
                t.stage, t.task_index, t.status, t.last_pulse,
                t.parameters, t.updated_at, t.created_at, t.retry_count,
                EXTRACT(EPOCH FROM (NOW() - t.updated_at)) / 60 AS minutes_stuck
            FROM {schema}.tasks t
            WHERE t.status = 'processing'
              AND t.updated_at < NOW() - make_interval(mins => %s)
              AND NOT (t.task_type = ANY(%s))
            ORDER BY t.updated_at ASC
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get stale processing tasks"):
            result = self._execute_query(
                query, (timeout_minutes, list(exclude_types)), fetch='all'
            )
            count = len(result) if result else 0
            if count > 0:
                logger.info(f"[GUARDIAN] Phase 1c: {count} stale FA PROCESSING tasks (>{timeout_minutes}min)")
            return result or []

    def get_stale_docker_tasks(
        self, timeout_minutes: int, docker_types: List[str]
    ) -> List[Dict[str, Any]]:
        """Docker tasks stuck in PROCESSING > timeout."""
        query = sql.SQL("""
            SELECT
                t.task_id, t.parent_job_id, t.job_type, t.task_type,
                t.stage, t.task_index, t.status, t.last_pulse,
                t.parameters, t.updated_at, t.created_at, t.retry_count,
                EXTRACT(EPOCH FROM (NOW() - t.updated_at)) / 60 AS minutes_stuck
            FROM {schema}.tasks t
            WHERE t.status = 'processing'
              AND t.task_type = ANY(%s)
              AND t.updated_at < NOW() - make_interval(mins => %s)
            ORDER BY t.updated_at ASC
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get stale docker tasks"):
            result = self._execute_query(
                query, (list(docker_types), timeout_minutes), fetch='all'
            )
            count = len(result) if result else 0
            if count > 0:
                logger.info(f"[GUARDIAN] Phase 1d: {count} stale Docker PROCESSING tasks (>{timeout_minutes}min)")
            return result or []

    # ================================================================
    # PHASE 2: STAGE RECOVERY
    # ================================================================

    def get_zombie_stages(self) -> List[Dict[str, Any]]:
        """
        Jobs where all tasks for current stage are terminal but stage
        has not advanced. This is Risk H's observable symptom.

        Uses JOIN (not LEFT JOIN) — jobs with zero tasks are caught
        by Phase 3b (stuck QUEUED jobs).
        """
        query = sql.SQL("""
            SELECT
                j.job_id, j.job_type, j.stage, j.total_stages, j.parameters,
                j.status, j.created_at, j.updated_at,
                COUNT(*) FILTER (WHERE t.status = 'completed') AS completed_tasks,
                COUNT(*) FILTER (WHERE t.status = 'failed') AS failed_tasks,
                COUNT(*) AS total_tasks
            FROM {schema}.jobs j
            JOIN {schema}.tasks t ON t.parent_job_id = j.job_id
                AND t.stage = j.stage
            WHERE j.status = 'processing'
            GROUP BY j.job_id
            HAVING COUNT(*) FILTER (WHERE t.status NOT IN ('completed', 'failed')) = 0
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get zombie stages"):
            result = self._execute_query(query, fetch='all')
            count = len(result) if result else 0
            if count > 0:
                logger.info(f"[GUARDIAN] Phase 2: {count} zombie stages detected")
            return result or []

    # ================================================================
    # PHASE 3: JOB RECOVERY
    # ================================================================

    def get_jobs_with_failed_tasks(self) -> List[Dict[str, Any]]:
        """PROCESSING jobs that have at least one failed task."""
        query = sql.SQL("""
            SELECT
                j.job_id, j.job_type, j.stage, j.total_stages,
                j.status, j.parameters, j.stage_results,
                j.created_at, j.updated_at,
                COUNT(t.*) FILTER (WHERE t.status = 'failed') AS failed_count,
                COUNT(t.*) FILTER (WHERE t.status = 'completed') AS completed_count,
                COUNT(t.*) AS total_tasks,
                ARRAY_AGG(t.task_id) FILTER (WHERE t.status = 'failed') AS failed_task_ids,
                ARRAY_AGG(t.error_details) FILTER (WHERE t.status = 'failed') AS failed_task_errors
            FROM {schema}.jobs j
            JOIN {schema}.tasks t ON t.parent_job_id = j.job_id
            WHERE j.status = 'processing'
            GROUP BY j.job_id
            HAVING COUNT(t.*) FILTER (WHERE t.status = 'failed') > 0
            ORDER BY j.updated_at ASC
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get jobs with failed tasks"):
            result = self._execute_query(query, fetch='all')
            count = len(result) if result else 0
            if count > 0:
                logger.info(f"[GUARDIAN] Phase 3a: {count} jobs with failed tasks")
            return result or []

    def get_stuck_queued_jobs(self, timeout_minutes: int) -> List[Dict[str, Any]]:
        """Jobs stuck in QUEUED with no tasks created (Risk H)."""
        query = sql.SQL("""
            SELECT
                j.job_id, j.job_type, j.stage, j.status,
                j.created_at, j.updated_at,
                EXTRACT(EPOCH FROM (NOW() - j.updated_at)) / 60 AS minutes_stuck
            FROM {schema}.jobs j
            WHERE j.status = 'queued'
              AND j.updated_at < NOW() - make_interval(mins => %s)
              AND NOT EXISTS (
                  SELECT 1 FROM {schema}.tasks t
                  WHERE t.parent_job_id = j.job_id
              )
            ORDER BY j.updated_at ASC
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get stuck queued jobs"):
            result = self._execute_query(query, (timeout_minutes,), fetch='all')
            count = len(result) if result else 0
            if count > 0:
                logger.info(f"[GUARDIAN] Phase 3b: {count} stuck QUEUED jobs (>{timeout_minutes}min)")
            return result or []

    def get_ancient_stale_jobs(self, timeout_minutes: int) -> List[Dict[str, Any]]:
        """PROCESSING jobs older than hard backstop threshold."""
        query = sql.SQL("""
            SELECT
                j.job_id, j.job_type, j.stage, j.total_stages,
                j.status, j.created_at, j.updated_at,
                EXTRACT(EPOCH FROM (NOW() - j.updated_at)) / 60 AS minutes_stuck
            FROM {schema}.jobs j
            WHERE j.status = 'processing'
              AND j.updated_at < NOW() - make_interval(mins => %s)
            ORDER BY j.updated_at ASC
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get ancient stale jobs"):
            result = self._execute_query(query, (timeout_minutes,), fetch='all')
            count = len(result) if result else 0
            if count > 0:
                logger.info(f"[GUARDIAN] Phase 3c: {count} ancient stale jobs (>{timeout_minutes}min)")
            return result or []

    def get_completed_task_results(self, job_id: str) -> List[Dict[str, Any]]:
        """Get results from completed tasks for partial result capture."""
        query = sql.SQL("""
            SELECT task_id, task_type, stage, result_data
            FROM {schema}.tasks
            WHERE parent_job_id = %s AND status = 'completed'
            ORDER BY stage, task_index
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get completed task results"):
            result = self._execute_query(query, (job_id,), fetch='all')
            return result or []

    # ================================================================
    # PHASE 4: CONSISTENCY
    # ================================================================

    def get_orphaned_tasks(self) -> List[Dict[str, Any]]:
        """Tasks whose parent job no longer exists."""
        query = sql.SQL("""
            SELECT t.task_id, t.parent_job_id, t.job_type, t.task_type,
                   t.stage, t.status, t.created_at
            FROM {schema}.tasks t
            LEFT JOIN {schema}.jobs j ON t.parent_job_id = j.job_id
            WHERE j.job_id IS NULL
            LIMIT 100
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get orphaned tasks"):
            result = self._execute_query(query, fetch='all')
            count = len(result) if result else 0
            if count > 0:
                logger.info(f"[GUARDIAN] Phase 4: {count} orphaned tasks (parent job missing)")
            return result or []

    # ================================================================
    # FIX OPERATIONS (shared across phases)
    # ================================================================

    def mark_tasks_failed(self, task_ids: List[str], error: str) -> int:
        """Batch mark tasks as FAILED. Returns count of updated rows."""
        if not task_ids:
            return 0

        query = sql.SQL("""
            UPDATE {schema}.tasks
            SET status = 'failed', error_details = %s, updated_at = NOW()
            WHERE task_id = ANY(%s)
            RETURNING task_id
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("mark tasks failed"):
            result = self._execute_query(query, (error, task_ids), fetch='all')
            count = len(result) if result else 0
            logger.info(f"[GUARDIAN] Marked {count} tasks FAILED")
            return count

    def mark_job_failed(
        self, job_id: str, error: str, partial_results: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Mark a job as FAILED with optional partial results."""
        if partial_results:
            query = sql.SQL("""
                UPDATE {schema}.jobs
                SET status = 'failed', error_details = %s,
                    result_data = %s::jsonb, updated_at = NOW()
                WHERE job_id = %s
                RETURNING job_id
            """).format(schema=sql.Identifier(self.schema_name))
            params = (error, json.dumps(partial_results), job_id)
        else:
            query = sql.SQL("""
                UPDATE {schema}.jobs
                SET status = 'failed', error_details = %s, updated_at = NOW()
                WHERE job_id = %s
                RETURNING job_id
            """).format(schema=sql.Identifier(self.schema_name))
            params = (error, job_id)

        with self._error_context("mark job failed"):
            result = self._execute_query(query, params, fetch='one')
            success = result is not None
            if success:
                logger.info(f"[GUARDIAN] Marked job {job_id[:16]}... FAILED")
            return success

    def increment_task_retry(self, task_id: str) -> int:
        """Increment retry_count and return new value."""
        query = sql.SQL("""
            UPDATE {schema}.tasks
            SET retry_count = retry_count + 1, updated_at = NOW()
            WHERE task_id = %s
            RETURNING retry_count
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("increment task retry"):
            result = self._execute_query(query, (task_id,), fetch='one')
            return result['retry_count'] if result else 0

    # ================================================================
    # AUDIT LOGGING (two-phase: insert at start, update at end)
    # ================================================================

    def log_sweep_start(self, sweep_id: str, started_at: datetime) -> Optional[str]:
        """
        Phase 1 of two-phase audit: INSERT running record at sweep start.

        Non-fatal — audit failure does not block the sweep.
        """
        query = sql.SQL("""
            INSERT INTO {schema}.janitor_runs (
                run_id, run_type, started_at, status,
                items_scanned, items_fixed, actions_taken
            ) VALUES (%s, 'sweep', %s, 'running', 0, 0, '[]'::jsonb)
            RETURNING run_id
        """).format(schema=sql.Identifier(self.schema_name))

        try:
            with self._error_context("log sweep start"):
                result = self._execute_query(
                    query, (sweep_id, started_at), fetch='one'
                )
                if result:
                    logger.debug(f"[GUARDIAN] Audit record created: {sweep_id}")
                    return str(result['run_id'])
                return None
        except Exception as e:
            logger.warning(f"[GUARDIAN] Failed to create audit record (non-fatal): {e}")
            return None

    def log_sweep_end(
        self,
        sweep_id: str,
        completed_at: datetime,
        items_scanned: int,
        items_fixed: int,
        actions_taken: List[Dict[str, Any]],
        phases: Dict[str, Any],
        status: str,
        error_details: Optional[str] = None
    ) -> bool:
        """
        Phase 2 of two-phase audit: UPDATE record with final results.

        Non-fatal — audit failure does not block the sweep.
        """
        query = sql.SQL("""
            UPDATE {schema}.janitor_runs
            SET completed_at = %s,
                items_scanned = %s,
                items_fixed = %s,
                actions_taken = %s::jsonb,
                phases = %s::jsonb,
                status = %s,
                error_details = %s,
                duration_ms = EXTRACT(EPOCH FROM (%s - started_at)) * 1000
            WHERE run_id = %s
            RETURNING run_id
        """).format(schema=sql.Identifier(self.schema_name))

        try:
            with self._error_context("log sweep end"):
                result = self._execute_query(
                    query,
                    (
                        completed_at, items_scanned, items_fixed,
                        json.dumps(actions_taken), json.dumps(phases),
                        status, error_details, completed_at, sweep_id
                    ),
                    fetch='one'
                )
                if result:
                    logger.debug(f"[GUARDIAN] Audit record updated: {sweep_id}")
                    return True
                return False
        except Exception as e:
            logger.warning(f"[GUARDIAN] Failed to update audit record (non-fatal): {e}")
            return False

    def get_recent_sweeps(
        self, hours: int = 24, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get recent sweep records for monitoring."""
        query = sql.SQL("""
            SELECT * FROM {schema}.janitor_runs
            WHERE started_at > NOW() - make_interval(hours => %s)
            ORDER BY started_at DESC
            LIMIT %s
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get recent sweeps"):
            result = self._execute_query(query, (hours, limit), fetch='all')
            return result or []


__all__ = ['GuardianRepository']
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_guardian_repository.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add infrastructure/guardian_repository.py tests/test_guardian_repository.py
git commit -m "feat(guardian): create GuardianRepository with phase-organized queries"
```

---

## Chunk 2: SystemGuardian Service

### Task 4: Create SystemGuardian

**Files:**
- Create: `services/system_guardian.py`
- Create: `tests/test_system_guardian.py`

- [ ] **Step 1: Write unit tests for SystemGuardian**

Create `tests/test_system_guardian.py`:

```python
"""
Tests for SystemGuardian sweep orchestration.

Uses mocked repository and queue client. Tests phase ordering,
fail-open behavior, audit trail, and config.
"""
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone


class TestGuardianConfig:
    """Test configuration and environment overrides."""

    def test_defaults(self):
        from services.system_guardian import GuardianConfig
        config = GuardianConfig()
        assert config.pending_task_timeout_minutes == 2
        assert config.queued_task_timeout_minutes == 5
        assert config.processing_task_timeout_minutes == 30
        assert config.docker_task_timeout_minutes == 180
        assert config.stuck_queued_job_timeout_minutes == 10
        assert config.ancient_job_timeout_minutes == 360
        assert config.max_task_retries == 3
        assert config.enabled is True

    def test_from_environment(self):
        from services.system_guardian import GuardianConfig
        with patch.dict('os.environ', {
            'GUARDIAN_DOCKER_TIMEOUT_MINUTES': '240',
            'GUARDIAN_ENABLED': 'false',
        }):
            config = GuardianConfig.from_environment()
            assert config.docker_task_timeout_minutes == 240
            assert config.enabled is False

    def test_frozen(self):
        from services.system_guardian import GuardianConfig
        config = GuardianConfig()
        with pytest.raises(AttributeError):
            config.enabled = False


class TestSweepOrchestration:
    """Test sweep phase ordering and fail-open behavior."""

    def _make_guardian(self):
        from services.system_guardian import SystemGuardian, GuardianConfig
        repo = MagicMock()
        repo.schema_ready.return_value = True
        repo.log_sweep_start.return_value = "test-sweep-id"
        repo.log_sweep_end.return_value = True
        # All detection queries return empty (no anomalies)
        repo.get_orphaned_pending_tasks.return_value = []
        repo.get_orphaned_queued_tasks.return_value = []
        repo.get_stale_processing_tasks.return_value = []
        repo.get_stale_docker_tasks.return_value = []
        repo.get_zombie_stages.return_value = []
        repo.get_jobs_with_failed_tasks.return_value = []
        repo.get_stuck_queued_jobs.return_value = []
        repo.get_ancient_stale_jobs.return_value = []
        repo.get_orphaned_tasks.return_value = []

        queue = MagicMock()
        config = GuardianConfig()
        guardian = SystemGuardian(repo, queue, config)
        return guardian, repo, queue

    def test_clean_sweep_no_anomalies(self):
        guardian, repo, _ = self._make_guardian()
        result = guardian.sweep()
        assert result.success is True
        assert result.total_scanned == 0
        assert result.total_fixed == 0
        assert len(result.phases) == 4

    def test_schema_not_ready_returns_early(self):
        guardian, repo, _ = self._make_guardian()
        repo.schema_ready.return_value = False
        result = guardian.sweep()
        assert result.success is True
        assert result.total_scanned == 0
        # No phase queries should be called
        repo.get_orphaned_pending_tasks.assert_not_called()

    def test_all_four_phases_run(self):
        guardian, repo, _ = self._make_guardian()
        result = guardian.sweep()
        # Verify all phase queries were called
        repo.get_orphaned_pending_tasks.assert_called_once()
        repo.get_orphaned_queued_tasks.assert_called_once()
        repo.get_stale_processing_tasks.assert_called_once()
        repo.get_stale_docker_tasks.assert_called_once()
        repo.get_zombie_stages.assert_called_once()
        repo.get_jobs_with_failed_tasks.assert_called_once()
        repo.get_stuck_queued_jobs.assert_called_once()
        repo.get_ancient_stale_jobs.assert_called_once()
        repo.get_orphaned_tasks.assert_called_once()

    def test_phase1_error_does_not_block_phase2(self):
        """Fail-open: phase errors don't abort the sweep."""
        guardian, repo, _ = self._make_guardian()
        repo.get_orphaned_pending_tasks.side_effect = Exception("DB transient error")
        result = guardian.sweep()
        # Phase 2+ should still run
        repo.get_zombie_stages.assert_called_once()
        repo.get_jobs_with_failed_tasks.assert_called_once()
        repo.get_orphaned_tasks.assert_called_once()
        # Phase 1 should have error
        assert result.phases["task_recovery"].error is not None
        # Overall sweep still succeeds (fail-open)
        assert result.success is True

    def test_disabled_config_skips_sweep(self):
        from services.system_guardian import SystemGuardian, GuardianConfig
        repo = MagicMock()
        queue = MagicMock()
        config = GuardianConfig(enabled=False)
        guardian = SystemGuardian(repo, queue, config)
        result = guardian.sweep()
        assert result.success is True
        repo.schema_ready.assert_not_called()

    def test_audit_trail_two_phase(self):
        guardian, repo, _ = self._make_guardian()
        result = guardian.sweep()
        repo.log_sweep_start.assert_called_once()
        repo.log_sweep_end.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_system_guardian.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'services.system_guardian'`

- [ ] **Step 3: Create SystemGuardian**

Create `services/system_guardian.py`:

```python
# ============================================================================
# SYSTEM GUARDIAN
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service - Distributed systems recovery engine
# PURPOSE: Ordered-phase sweep pipeline for task/stage/job recovery
# LAST_REVIEWED: 14 MAR 2026
# EXPORTS: SystemGuardian, GuardianConfig, SweepResult, PhaseResult
# DEPENDENCIES: guardian_repository, service_bus, core.models
# ============================================================================
"""
SystemGuardian — Distributed Systems Recovery Engine.

Replaces the 3-trigger janitor system with a single ordered-phase sweep.
Runs every 5 minutes from the orchestrator Function App.

Phase ordering is deliberate and load-bearing:
    Phase 1: Task Recovery   — fix tasks first (may unblock stages naturally)
    Phase 2: Stage Recovery  — fix stages next (may unblock jobs naturally)
    Phase 3: Job Recovery    — fail jobs that couldn't be rescued
    Phase 4: Consistency     — structural cleanup (orphaned records)

Fail-open: each phase runs regardless of previous phase errors.
"""

import os
import uuid
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass(frozen=True)
class GuardianConfig:
    """Immutable sweep configuration. All timeouts in minutes."""
    sweep_interval_minutes: int = 5
    pending_task_timeout_minutes: int = 2
    queued_task_timeout_minutes: int = 5
    processing_task_timeout_minutes: int = 30       # Function App tasks
    docker_task_timeout_minutes: int = 180           # 3 hours
    stuck_queued_job_timeout_minutes: int = 10       # Risk H detection
    ancient_job_timeout_minutes: int = 360           # 6 hours
    max_task_retries: int = 3
    enabled: bool = True

    @classmethod
    def from_environment(cls) -> 'GuardianConfig':
        """Override defaults from GUARDIAN_* env vars."""
        return cls(
            pending_task_timeout_minutes=int(os.getenv('GUARDIAN_PENDING_TIMEOUT_MINUTES', 2)),
            queued_task_timeout_minutes=int(os.getenv('GUARDIAN_QUEUED_TIMEOUT_MINUTES', 5)),
            processing_task_timeout_minutes=int(os.getenv('GUARDIAN_PROCESSING_TIMEOUT_MINUTES', 30)),
            docker_task_timeout_minutes=int(os.getenv('GUARDIAN_DOCKER_TIMEOUT_MINUTES', 180)),
            stuck_queued_job_timeout_minutes=int(os.getenv('GUARDIAN_STUCK_JOB_TIMEOUT_MINUTES', 10)),
            ancient_job_timeout_minutes=int(os.getenv('GUARDIAN_ANCIENT_JOB_TIMEOUT_MINUTES', 360)),
            max_task_retries=int(os.getenv('GUARDIAN_MAX_TASK_RETRIES', 3)),
            enabled=os.getenv('GUARDIAN_ENABLED', 'true').lower() == 'true',
        )


# ============================================================================
# RESULT MODELS
# ============================================================================

@dataclass
class PhaseResult:
    """Result of one phase within a sweep."""
    phase: str
    scanned: int = 0
    fixed: int = 0
    actions: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scanned": self.scanned,
            "fixed": self.fixed,
            "actions": self.actions,
            "error": self.error,
        }


@dataclass
class SweepResult:
    """Result of a single sweep() call."""
    sweep_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    phases: Dict[str, PhaseResult] = field(default_factory=dict)
    total_scanned: int = 0
    total_fixed: int = 0
    success: bool = True
    error: Optional[str] = None

    def _aggregate(self):
        """Sum scanned/fixed across all phases."""
        self.total_scanned = sum(p.scanned for p in self.phases.values())
        self.total_fixed = sum(p.fixed for p in self.phases.values())

    def complete(self):
        """Finalize the sweep result."""
        self.completed_at = datetime.now(timezone.utc)
        self._aggregate()

    @property
    def all_actions(self) -> List[Dict[str, Any]]:
        """Flat list of all actions across all phases."""
        actions = []
        for phase in self.phases.values():
            actions.extend(phase.actions)
        return actions

    @property
    def phases_dict(self) -> Dict[str, Any]:
        """Phases as plain dict for JSONB storage."""
        return {name: p.to_dict() for name, p in self.phases.items()}


# ============================================================================
# SYSTEM GUARDIAN
# ============================================================================

class SystemGuardian:
    """
    Distributed systems recovery engine.

    Runs 4 ordered phases to detect and fix anomalies in the
    job/task pipeline. Phase ordering eliminates false positives.
    """

    def __init__(self, repo, queue_client, config: Optional[GuardianConfig] = None):
        """
        Args:
            repo: GuardianRepository instance
            queue_client: ServiceBusRepository for re-queuing tasks
            config: Sweep configuration (defaults if None)
        """
        self._repo = repo
        self._queue = queue_client
        self._config = config or GuardianConfig()

    def sweep(self) -> SweepResult:
        """
        Run all phases in order. Fail-open: each phase runs regardless
        of previous phase errors.
        """
        result = SweepResult()

        if not self._config.enabled:
            logger.info("[GUARDIAN] Sweep disabled via config")
            result.complete()
            return result

        # Schema readiness check
        if not self._repo.schema_ready():
            logger.info("[GUARDIAN] Schema not ready (rebuild in progress?), skipping sweep")
            result.complete()
            return result

        # Two-phase audit: INSERT at start
        self._repo.log_sweep_start(result.sweep_id, result.started_at)

        # Execute phases in order
        phase_methods = [
            ("task_recovery", self._phase_task_recovery),
            ("stage_recovery", self._phase_stage_recovery),
            ("job_recovery", self._phase_job_recovery),
            ("consistency", self._phase_consistency),
        ]

        for phase_name, phase_fn in phase_methods:
            try:
                phase_result = phase_fn()
                result.phases[phase_name] = phase_result
            except Exception as e:
                logger.error(f"[GUARDIAN] Phase {phase_name} failed: {e}")
                result.phases[phase_name] = PhaseResult(
                    phase=phase_name, error=str(e)
                )

        # Finalize
        result.complete()

        # Two-phase audit: UPDATE at end
        self._repo.log_sweep_end(
            sweep_id=result.sweep_id,
            completed_at=result.completed_at,
            items_scanned=result.total_scanned,
            items_fixed=result.total_fixed,
            actions_taken=result.all_actions,
            phases=result.phases_dict,
            status="completed" if result.success else "failed",
            error_details=result.error,
        )

        logger.info(
            f"[GUARDIAN] Sweep {result.sweep_id[:8]}: "
            f"scanned={result.total_scanned} fixed={result.total_fixed}"
        )

        return result

    # ================================================================
    # PHASE 1: TASK RECOVERY
    # ================================================================

    def _phase_task_recovery(self) -> PhaseResult:
        """Fix orphaned and stale tasks."""
        phase = PhaseResult(phase="task_recovery")
        cfg = self._config

        # 1a. Orphaned PENDING tasks
        pending = self._repo.get_orphaned_pending_tasks(cfg.pending_task_timeout_minutes)
        phase.scanned += len(pending)
        for task in pending:
            self._recover_orphaned_task(task, phase, "pending_timeout")

        # 1b. Orphaned QUEUED tasks (with queue peek)
        queued = self._repo.get_orphaned_queued_tasks(cfg.queued_task_timeout_minutes)
        phase.scanned += len(queued)
        for task in queued:
            self._recover_queued_task(task, phase)

        # 1c. Stale PROCESSING tasks — Function App
        from config.defaults import TaskRoutingDefaults
        docker_types = list(TaskRoutingDefaults.DOCKER_TASKS)

        stale_fa = self._repo.get_stale_processing_tasks(
            cfg.processing_task_timeout_minutes, docker_types
        )
        phase.scanned += len(stale_fa)
        for task in stale_fa:
            self._recover_stale_processing_task(task, phase)

        # 1d. Stale PROCESSING tasks — Docker
        stale_docker = self._repo.get_stale_docker_tasks(
            cfg.docker_task_timeout_minutes, docker_types
        )
        phase.scanned += len(stale_docker)
        for task in stale_docker:
            self._repo.mark_tasks_failed(
                [task['task_id']], "docker_task_timeout"
            )
            phase.fixed += 1
            phase.actions.append({
                "action": "mark_docker_task_failed",
                "task_id": task['task_id'],
                "parent_job_id": task['parent_job_id'],
                "task_type": task['task_type'],
                "minutes_stuck": task.get('minutes_stuck'),
                "reason": "docker_task_timeout",
            })

        return phase

    def _recover_orphaned_task(
        self, task: Dict, phase: PhaseResult, reason: str
    ):
        """Re-send message for orphaned PENDING task, or fail if max retries."""
        task_id = task['task_id']
        retry_count = task.get('retry_count', 0)

        if retry_count >= self._config.max_task_retries:
            self._repo.mark_tasks_failed([task_id], f"max_retries_exceeded_{reason}")
            phase.fixed += 1
            phase.actions.append({
                "action": f"mark_{reason}_failed",
                "task_id": task_id,
                "parent_job_id": task['parent_job_id'],
                "reason": "max_retries_exceeded",
                "retry_count": retry_count,
            })
            return

        # Re-send message
        try:
            self._send_task_message(task)
            self._repo.increment_task_retry(task_id)
            phase.fixed += 1
            phase.actions.append({
                "action": f"resend_{reason}",
                "task_id": task_id,
                "parent_job_id": task['parent_job_id'],
                "task_type": task['task_type'],
                "retry_count": retry_count + 1,
            })
        except Exception as e:
            logger.error(f"[GUARDIAN] Failed to resend task {task_id[:16]}...: {e}")
            self._repo.mark_tasks_failed([task_id], f"resend_failed: {str(e)[:200]}")
            phase.fixed += 1
            phase.actions.append({
                "action": f"mark_{reason}_failed",
                "task_id": task_id,
                "reason": f"resend_failed: {str(e)[:100]}",
            })

    def _recover_queued_task(self, task: Dict, phase: PhaseResult):
        """Recover orphaned QUEUED task with queue peek verification."""
        task_id = task['task_id']
        queue_name = self._get_queue_for_task(task['task_type'])

        # Peek queue — if message exists, task is not orphaned
        try:
            message_exists = self._queue.message_exists_for_task(queue_name, task_id)
            if message_exists:
                phase.actions.append({
                    "action": "skip_queued_task",
                    "task_id": task_id,
                    "reason": "message_exists_in_queue",
                })
                return
        except Exception as e:
            logger.warning(f"[GUARDIAN] Queue peek failed for {task_id[:16]}...: {e}")
            # Peek failed — treat as orphaned (conservative)

        self._recover_orphaned_task(task, phase, "queued_timeout")

    def _recover_stale_processing_task(self, task: Dict, phase: PhaseResult):
        """Recover stale PROCESSING Function App task."""
        task_id = task['task_id']
        last_pulse = task.get('last_pulse')
        retry_count = task.get('retry_count', 0)

        # Task never started (no pulse) and retries left → re-queue
        if last_pulse is None and retry_count < self._config.max_task_retries:
            try:
                self._send_task_message(task)
                self._repo.increment_task_retry(task_id)
                phase.fixed += 1
                phase.actions.append({
                    "action": "requeue_stale_processing_task",
                    "task_id": task_id,
                    "parent_job_id": task['parent_job_id'],
                    "reason": "processing_timeout_no_pulse",
                    "retry_count": retry_count + 1,
                })
                return
            except Exception as e:
                logger.error(f"[GUARDIAN] Re-queue failed for {task_id[:16]}...: {e}")

        # Task ran (has pulse) or max retries → fail
        self._repo.mark_tasks_failed([task_id], "processing_timeout")
        phase.fixed += 1
        phase.actions.append({
            "action": "mark_processing_task_failed",
            "task_id": task_id,
            "parent_job_id": task['parent_job_id'],
            "minutes_stuck": task.get('minutes_stuck'),
            "reason": "processing_timeout" if last_pulse else "processing_timeout_no_pulse_max_retries",
            "retry_count": retry_count,
        })

    # ================================================================
    # PHASE 2: STAGE RECOVERY
    # ================================================================

    def _phase_stage_recovery(self) -> PhaseResult:
        """Fix zombie stages (Risk H recovery)."""
        phase = PhaseResult(phase="stage_recovery")

        zombies = self._repo.get_zombie_stages()
        phase.scanned = len(zombies)

        for job in zombies:
            job_id = job['job_id']
            failed_tasks = job.get('failed_tasks', 0)

            if failed_tasks > 0:
                # Stage has failures → mark job failed with partial results
                partial = self._build_partial_results(job_id, job)
                self._repo.mark_job_failed(
                    job_id,
                    f"stage_{job['stage']}_has_{failed_tasks}_failed_tasks",
                    partial_results=partial,
                )
                phase.fixed += 1
                phase.actions.append({
                    "action": "mark_zombie_job_failed",
                    "job_id": job_id,
                    "job_type": job['job_type'],
                    "stage": job['stage'],
                    "reason": "zombie_with_failures",
                    "failed_tasks": failed_tasks,
                })
            else:
                # All tasks completed → re-attempt stage advancement
                try:
                    self._send_stage_complete_message(job)
                    phase.fixed += 1
                    phase.actions.append({
                        "action": "resend_stage_complete",
                        "job_id": job_id,
                        "job_type": job['job_type'],
                        "stage": job['stage'],
                        "reason": "zombie_stage_advancement_retry",
                    })
                except Exception as e:
                    logger.error(
                        f"[GUARDIAN] Stage advancement retry failed for "
                        f"{job_id[:16]}...: {e}"
                    )
                    phase.actions.append({
                        "action": "stage_recovery_failed",
                        "job_id": job_id,
                        "reason": str(e)[:200],
                    })

        return phase

    # ================================================================
    # PHASE 3: JOB RECOVERY
    # ================================================================

    def _phase_job_recovery(self) -> PhaseResult:
        """Propagate failures and clean up stuck jobs."""
        phase = PhaseResult(phase="job_recovery")
        cfg = self._config

        # 3a. PROCESSING jobs with failed tasks
        failed_jobs = self._repo.get_jobs_with_failed_tasks()
        phase.scanned += len(failed_jobs)
        for job in failed_jobs:
            job_id = job['job_id']
            partial = self._build_partial_results(job_id, job)
            self._repo.mark_job_failed(
                job_id,
                f"tasks_failed: {job.get('failed_count', 0)} of {job.get('total_tasks', 0)}",
                partial_results=partial,
            )
            phase.fixed += 1
            phase.actions.append({
                "action": "mark_job_failed_propagated",
                "job_id": job_id,
                "job_type": job['job_type'],
                "stage": job['stage'],
                "failed_count": job.get('failed_count', 0),
                "reason": "failed_task_propagation",
            })

        # 3b. Stuck QUEUED jobs, no tasks (Risk H)
        stuck = self._repo.get_stuck_queued_jobs(cfg.stuck_queued_job_timeout_minutes)
        phase.scanned += len(stuck)
        for job in stuck:
            self._repo.mark_job_failed(
                job['job_id'],
                f"stuck_queued_no_tasks_{job.get('minutes_stuck', 0):.0f}min",
            )
            phase.fixed += 1
            phase.actions.append({
                "action": "mark_stuck_queued_failed",
                "job_id": job['job_id'],
                "job_type": job['job_type'],
                "minutes_stuck": job.get('minutes_stuck'),
                "reason": "stuck_queued_no_tasks",
            })

        # 3c. Ancient stale jobs
        ancient = self._repo.get_ancient_stale_jobs(cfg.ancient_job_timeout_minutes)
        phase.scanned += len(ancient)
        for job in ancient:
            job_id = job['job_id']
            partial = self._build_partial_results(job_id, job)
            self._repo.mark_job_failed(
                job_id,
                f"ancient_stale_{job.get('minutes_stuck', 0):.0f}min",
                partial_results=partial,
            )
            phase.fixed += 1
            phase.actions.append({
                "action": "mark_ancient_job_failed",
                "job_id": job_id,
                "job_type": job['job_type'],
                "minutes_stuck": job.get('minutes_stuck'),
                "reason": "exceeded_max_duration",
            })

        return phase

    # ================================================================
    # PHASE 4: CONSISTENCY
    # ================================================================

    def _phase_consistency(self) -> PhaseResult:
        """Detect and fix structural inconsistencies."""
        phase = PhaseResult(phase="consistency")

        orphans = self._repo.get_orphaned_tasks()
        phase.scanned = len(orphans)

        if orphans:
            task_ids = [t['task_id'] for t in orphans]
            self._repo.mark_tasks_failed(task_ids, "parent_job_missing")
            phase.fixed = len(task_ids)
            for task in orphans:
                phase.actions.append({
                    "action": "mark_orphaned_task_failed",
                    "task_id": task['task_id'],
                    "parent_job_id": task['parent_job_id'],
                    "reason": "parent_job_missing",
                })

        return phase

    # ================================================================
    # HELPERS
    # ================================================================

    def _get_queue_for_task(self, task_type: str) -> str:
        """Route task type to correct Service Bus queue."""
        from config.defaults import TaskRoutingDefaults, QueueDefaults
        if task_type in TaskRoutingDefaults.DOCKER_TASKS:
            return QueueDefaults.CONTAINER_TASKS_QUEUE
        return QueueDefaults.JOBS_QUEUE

    def _send_task_message(self, task: Dict):
        """Build and send a task queue message."""
        from core.schema.queue import TaskQueueMessage
        queue_name = self._get_queue_for_task(task['task_type'])

        msg = TaskQueueMessage(
            task_id=task['task_id'],
            parent_job_id=task['parent_job_id'],
            job_type=task['job_type'],
            task_type=task['task_type'],
            stage=task['stage'],
            task_index=task.get('task_index', 0),
            parameters=task.get('parameters', {}),
            retry_count=task.get('retry_count', 0) + 1,
        )
        # ServiceBusRepository.send_message expects BaseModel, serializes internally
        self._queue.send_message(queue_name, msg)

    def _send_stage_complete_message(self, job: Dict):
        """Send StageCompleteMessage to retry stage advancement (Risk H recovery)."""
        from core.schema.queue import StageCompleteMessage
        from config.defaults import QueueDefaults

        msg = StageCompleteMessage(
            job_id=job['job_id'],
            job_type=job['job_type'],
            completed_stage=job['stage'],
            completed_at=datetime.now(timezone.utc).isoformat(),
            completed_by_app="system_guardian",
            correlation_id=str(uuid.uuid4())[:8],
        )
        # Routes through _handle_stage_completion(), not new job dispatch
        self._queue.send_message(QueueDefaults.JOBS_QUEUE, msg)

    def _build_partial_results(
        self, job_id: str, job_info: Dict
    ) -> Dict[str, Any]:
        """Capture completed task results before marking job failed."""
        try:
            completed = self._repo.get_completed_task_results(job_id)
            return {
                "status": "partial_failure",
                "completed_tasks_count": len(completed),
                "failed_tasks_count": job_info.get('failed_count', job_info.get('failed_tasks', 0)),
                "total_tasks_count": job_info.get('total_tasks', 0),
                "failed_at_stage": job_info.get('stage'),
                "partial_results": [
                    {
                        "task_id": t['task_id'],
                        "task_type": t.get('task_type'),
                        "stage": t.get('stage'),
                        "result_data": t.get('result_data'),
                    }
                    for t in completed[:10]
                ],
                "guardian_cleanup_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.warning(f"[GUARDIAN] Failed to build partial results for {job_id[:16]}...: {e}")
            return {
                "status": "partial_failure",
                "error": f"Failed to capture partial results: {e}",
            }


__all__ = ['SystemGuardian', 'GuardianConfig', 'SweepResult', 'PhaseResult']
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_system_guardian.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/system_guardian.py tests/test_system_guardian.py
git commit -m "feat(guardian): create SystemGuardian with 4-phase ordered sweep"
```

---

## Chunk 3: Trigger Wiring + Cleanup

### Task 5: Create new timer trigger and update trigger wiring

**Files:**
- Create: `triggers/janitor/system_guardian.py`
- Modify: `triggers/janitor/__init__.py`
- Modify: `triggers/timers/timer_bp.py`

- [ ] **Step 1: Create the timer trigger handler**

Create `triggers/janitor/system_guardian.py`:

```python
# ============================================================================
# SYSTEM GUARDIAN TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Trigger - SystemGuardian timer handler
# PURPOSE: Single 5-minute timer trigger for distributed systems recovery
# LAST_REVIEWED: 14 MAR 2026
# EXPORTS: system_guardian_handler
# DEPENDENCIES: system_guardian, guardian_repository, service_bus
# ============================================================================
"""
SystemGuardian Timer Trigger.

Single trigger replaces task_watchdog, job_health, and orphan_detector.
Runs sweep() which executes 4 ordered phases.
"""

import logging
from datetime import datetime, timezone

import azure.functions as func

logger = logging.getLogger(__name__)


def _build_guardian():
    """Construct SystemGuardian with repository and queue client."""
    from services.system_guardian import SystemGuardian, GuardianConfig
    from infrastructure.guardian_repository import GuardianRepository
    from infrastructure.service_bus import ServiceBusRepository

    repo = GuardianRepository()
    queue = ServiceBusRepository()
    config = GuardianConfig.from_environment()
    return SystemGuardian(repo, queue, config)


def system_guardian_handler(timer: func.TimerRequest) -> None:
    """Timer trigger handler for SystemGuardian sweep."""
    trigger_time = datetime.now(timezone.utc)

    if timer.past_due:
        logger.warning("[GUARDIAN] Timer is past due — running immediately")

    logger.info(f"[GUARDIAN] Sweep triggered at {trigger_time.isoformat()}")

    try:
        guardian = _build_guardian()
        result = guardian.sweep()

        if result.total_fixed > 0:
            logger.warning(
                f"[GUARDIAN] Sweep {result.sweep_id[:8]}: "
                f"scanned={result.total_scanned} fixed={result.total_fixed}"
            )
        else:
            logger.info(
                f"[GUARDIAN] Sweep {result.sweep_id[:8]}: clean (no anomalies)"
            )

    except Exception as e:
        logger.error(f"[GUARDIAN] Sweep unhandled exception: {e}")
        import traceback
        logger.error(traceback.format_exc())
```

- [ ] **Step 2: Update `triggers/janitor/__init__.py`**

Replace the entire file:

```python
# ============================================================================
# JANITOR TRIGGERS PACKAGE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Trigger layer - Package init for system maintenance triggers
# PURPOSE: Export SystemGuardian trigger and HTTP handlers
# LAST_REVIEWED: 14 MAR 2026
# EXPORTS: system_guardian_handler, janitor_*_handler
# ============================================================================
"""
Janitor Triggers Package.

SystemGuardian timer trigger and HTTP triggers for maintenance operations.

Exports:
    system_guardian_handler: Timer trigger for 4-phase sweep (replaces
        task_watchdog, job_health, orphan_detector)
    janitor_run_handler: HTTP trigger for manual sweep/maintenance
    janitor_status_handler: HTTP trigger for status
    janitor_history_handler: HTTP trigger for history
"""

from .system_guardian import system_guardian_handler

# HTTP trigger handlers
from .http_triggers import (
    janitor_run_handler,
    janitor_status_handler,
    janitor_history_handler
)

__all__ = [
    'system_guardian_handler',
    'janitor_run_handler',
    'janitor_status_handler',
    'janitor_history_handler'
]
```

- [ ] **Step 3: Update `triggers/timers/timer_bp.py`**

Replace the three janitor timer triggers (`janitor_task_watchdog`, `janitor_job_health`, `janitor_orphan_detector`) with a single trigger:

```python
# Replace the three janitor triggers with:

@bp.timer_trigger(
    schedule="0 */5 * * * *",
    arg_name="timer",
    run_on_startup=False
)
def system_guardian_sweep(timer: func.TimerRequest) -> None:
    """
    SystemGuardian — distributed systems recovery sweep.

    Runs 4 ordered phases: task recovery → stage recovery → job recovery → consistency.
    Replaces task_watchdog + job_health + orphan_detector.

    Schedule: Every 5 minutes
    """
    from triggers.janitor import system_guardian_handler
    system_guardian_handler(timer)
```

Update the module docstring's "Timer Schedule Overview" to replace the three janitor lines with the single `system_guardian_sweep` entry.

- [ ] **Step 4: Commit**

```bash
git add triggers/janitor/system_guardian.py triggers/janitor/__init__.py triggers/timers/timer_bp.py
git commit -m "feat(guardian): wire single timer trigger, replace 3 janitor triggers"
```

---

### Task 6: Update HTTP endpoints

**Files:**
- Modify: `triggers/janitor/http_triggers.py`

- [ ] **Step 1: Update janitor_run_handler to use SystemGuardian**

Update the `janitor_run_handler` function to support `type=sweep` (and phase aliases). The `type=all` should now run a sweep. Legacy types (`task_watchdog`, `job_health`, `orphan_detector`) should map to individual phases for transition.

For non-sweep utilities (`metadata_consistency`, `log_cleanup`, `queue_depth_snapshot`), retain existing behavior — these call standalone functions, not SystemGuardian.

Key changes:
- `type=sweep` or `type=all` → `guardian.sweep()`
- `type=task_watchdog` → alias for sweep (or just Phase 1 for debugging)
- Retain `metadata_consistency`, `log_cleanup`, `queue_depth_snapshot` as-is

- [ ] **Step 2: Test via manual HTTP call**

After deployment, test:
```bash
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/cleanup/run?type=sweep"
```

- [ ] **Step 3: Commit**

```bash
git add triggers/janitor/http_triggers.py
git commit -m "feat(guardian): update HTTP endpoints to use SystemGuardian"
```

---

### Task 7: Delete old files

**Files:**
- Delete: `triggers/janitor/task_watchdog.py`
- Delete: `triggers/janitor/job_health.py`
- Delete: `triggers/janitor/orphan_detector.py`
- Delete: `services/janitor_service.py`
- Delete: `infrastructure/janitor_repository.py`

- [ ] **Step 1: Verify no remaining imports of old modules**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
grep -r "from services.janitor_service" --include="*.py" | grep -v __pycache__ | grep -v ".pyc"
grep -r "from infrastructure.janitor_repository" --include="*.py" | grep -v __pycache__ | grep -v ".pyc"
grep -r "from triggers.janitor.task_watchdog" --include="*.py" | grep -v __pycache__ | grep -v ".pyc"
grep -r "from triggers.janitor.job_health" --include="*.py" | grep -v __pycache__ | grep -v ".pyc"
grep -r "from triggers.janitor.orphan_detector" --include="*.py" | grep -v __pycache__ | grep -v ".pyc"
```

Expected: No matches (all imports should have been updated in prior tasks). If matches found, fix them first.

- [ ] **Step 2: Delete old files**

```bash
git rm triggers/janitor/task_watchdog.py
git rm triggers/janitor/job_health.py
git rm triggers/janitor/orphan_detector.py
git rm services/janitor_service.py
git rm infrastructure/janitor_repository.py
```

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: All tests pass. If imports break, fix them.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(guardian): delete old janitor files — replaced by SystemGuardian"
```

---

### Task 8: Final verification

- [ ] **Step 1: Verify clean import chain**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
conda activate azgeo
python -c "
from services.system_guardian import SystemGuardian, GuardianConfig, SweepResult, PhaseResult
from infrastructure.guardian_repository import GuardianRepository
from triggers.janitor import system_guardian_handler
print('All imports OK')
"
```

Expected: `All imports OK`

- [ ] **Step 2: Run all tests**

```bash
python -m pytest tests/test_system_guardian.py tests/test_guardian_repository.py -v
```

Expected: All PASS

- [ ] **Step 3: Final commit — atomic with all changes**

If any fixes were needed, commit them:

```bash
git add -A
git commit -m "feat(guardian): SystemGuardian complete — 4-phase ordered sweep replaces 3-trigger janitor

Addresses V10_DECISIONS Risk G (orphaned tasks) and Risk H (stuck stage advancement).
Single 5-min timer trigger. Deterministic phase ordering eliminates false positives.
Thresholds: Docker 3h, stuck QUEUED 10min, ancient 6h."
```
