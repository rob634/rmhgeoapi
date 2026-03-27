# Orchestrator Lease Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken advisory lock in DAGOrchestrator with a database lease, enabling safe multi-instance behavior and automatic recovery of partially completed workflows.

**Architecture:** A single row in `app.orchestrator_lease` acts as a distributed mutex. The holder renews the lease every poll cycle (5s). If the holder crashes, the lease expires after 60s and any new Brain instance acquires it and resumes orchestration. The DAG's stateless design (all state in workflow_tasks table) means the new holder picks up exactly where the crashed instance left off. CAS guards on individual task mutations remain as defense-in-depth.

**Tech Stack:** PostgreSQL (psycopg3 sql composition), existing WorkflowRunRepository pattern, Pydantic model with `__sql_*` DDL hints

---

## Background

### The Problem
`DAGOrchestrator._try_acquire_xact_lock()` uses `pg_try_advisory_xact_lock` (transaction-level). The lock releases when `conn.commit()` is called at line 244, before the poll loop even starts. Two Brain instances can both "acquire" the lock and run simultaneously.

### The Solution
Replace the advisory lock with a **database lease** — a row in `app.orchestrator_lease` with an `expires_at` timestamp. The holder renews every cycle. If the holder crashes, the lease expires and another instance takes over. The new instance resumes the in-progress workflow by reading task states from the database.

### Why This Works
The DAG orchestrator is stateless. It reads `workflow_tasks`, evaluates what needs to happen, and acts. It doesn't carry in-memory state between cycles. Any instance that holds the lease can drive any run to completion.

---

## File Structure

**New files:**
- `core/models/orchestrator_lease.py` — Pydantic model with DDL hints (follows WorkflowRun pattern)
- `infrastructure/lease_repository.py` — Acquire, renew, release, read lease

**Modified files:**
- `core/dag_orchestrator.py` — Replace `_try_acquire_xact_lock` with lease acquire/renew
- `docker_service.py` — DAGBrainPrimaryLoop acquires lease before scanning, renews each cycle
- `docker_health/dag_brain.py` — Health check verifies lease is being renewed

---

## Task 1: Create Lease Model

**Files:**
- Create: `core/models/orchestrator_lease.py`

- [ ] **Step 1: Create the Pydantic model with DDL hints**

```python
# core/models/orchestrator_lease.py
"""
Orchestrator lease model — distributed mutex for DAG Brain instances.

A single row acts as a lease. The holder renews it every poll cycle.
If the holder crashes, the lease expires and another instance takes over.
"""
from datetime import datetime
from typing import Any, ClassVar, Dict, List, Optional

from pydantic import BaseModel


class OrchestratorLease(BaseModel):
    """Single-row lease for orchestrator exclusion."""

    lease_key: str = "singleton"
    holder_id: str
    acquired_at: datetime
    expires_at: datetime
    renewed_at: datetime

    # DDL generation hints (same pattern as WorkflowRun)
    __sql_table_name: ClassVar[str] = "orchestrator_lease"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["lease_key"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {}
    __sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = []
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = []
```

- [ ] **Step 2: Commit**

```bash
git add core/models/orchestrator_lease.py
git commit -m "feat: OrchestratorLease model with DDL hints"
```

---

## Task 2: Create Lease Repository

**Files:**
- Create: `infrastructure/lease_repository.py`

The repository handles all lease operations using the same `PostgreSQLRepository` base class and `psycopg.sql` composition as `WorkflowRunRepository`.

- [ ] **Step 1: Create the repository**

```python
# infrastructure/lease_repository.py
"""
Lease repository — atomic acquire/renew/release for orchestrator mutex.

All SQL uses psycopg.sql composition (Standard 1.2). Inherits connection
management from PostgreSQLRepository.
"""
import logging
import os
import socket
from datetime import datetime, timezone
from typing import Optional

from psycopg import sql
from psycopg.rows import dict_row

from exceptions import DatabaseError
from .postgresql import PostgreSQLRepository

logger = logging.getLogger(__name__)

_SCHEMA = "app"
_TABLE = "orchestrator_lease"
_LEASE_TTL_SECONDS = 60


def _generate_holder_id() -> str:
    """Generate a unique holder ID for this process (hostname + pid)."""
    return f"{socket.gethostname()}:{os.getpid()}"


class LeaseRepository(PostgreSQLRepository):
    """
    Atomic lease operations for orchestrator exclusion.

    The lease is a single row in app.orchestrator_lease. Only one holder
    can hold the lease at a time. The holder must renew before expires_at
    or lose the lease to the next caller.
    """

    def ensure_table(self) -> None:
        """Create the lease table if it doesn't exist."""
        ddl = sql.SQL(
            "CREATE TABLE IF NOT EXISTS {schema}.{table} ("
            "  lease_key TEXT PRIMARY KEY DEFAULT 'singleton',"
            "  holder_id TEXT NOT NULL,"
            "  acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
            "  expires_at TIMESTAMPTZ NOT NULL,"
            "  renewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            ")"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
        )
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(ddl)
                conn.commit()
        except Exception as exc:
            logger.error("Failed to ensure orchestrator_lease table: %s", exc)
            raise DatabaseError(f"Failed to ensure lease table: {exc}") from exc

    def try_acquire(
        self, holder_id: Optional[str] = None, ttl_seconds: int = _LEASE_TTL_SECONDS
    ) -> bool:
        """
        Attempt to acquire the lease.

        Succeeds if:
        - No lease row exists (first time — inserts one)
        - Lease row exists and is expired (takes over)
        - Lease row exists and holder_id matches (re-acquire by same instance)

        Returns True if lease acquired, False if held by another instance.
        """
        holder_id = holder_id or _generate_holder_id()

        # Upsert: insert if missing, update if expired or same holder
        upsert = sql.SQL(
            "INSERT INTO {schema}.{table} (lease_key, holder_id, acquired_at, expires_at, renewed_at) "
            "VALUES ('singleton', %(holder_id)s, NOW(), NOW() + %(ttl)s * interval '1 second', NOW()) "
            "ON CONFLICT (lease_key) DO UPDATE "
            "SET holder_id = %(holder_id)s, "
            "    acquired_at = NOW(), "
            "    expires_at = NOW() + %(ttl)s * interval '1 second', "
            "    renewed_at = NOW() "
            "WHERE {schema}.{table}.expires_at < NOW() "
            "   OR {schema}.{table}.holder_id = %(holder_id)s"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
        )

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(upsert, {"holder_id": holder_id, "ttl": ttl_seconds})
                    acquired = cur.rowcount > 0
                conn.commit()

            if acquired:
                logger.info("Lease acquired: holder=%s ttl=%ds", holder_id, ttl_seconds)
            else:
                logger.debug("Lease held by another instance (holder=%s)", holder_id)

            return acquired
        except Exception as exc:
            logger.error("Failed to acquire lease: %s", exc)
            raise DatabaseError(f"Failed to acquire lease: {exc}") from exc

    def renew(
        self, holder_id: Optional[str] = None, ttl_seconds: int = _LEASE_TTL_SECONDS
    ) -> bool:
        """
        Renew the lease. Only succeeds if caller is the current holder.

        Returns True if renewed, False if lease was lost (another instance
        took over, or lease expired). Caller should stop orchestrating
        if renew returns False.
        """
        holder_id = holder_id or _generate_holder_id()

        query = sql.SQL(
            "UPDATE {schema}.{table} "
            "SET expires_at = NOW() + %(ttl)s * interval '1 second', "
            "    renewed_at = NOW() "
            "WHERE lease_key = 'singleton' AND holder_id = %(holder_id)s"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
        )

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, {"holder_id": holder_id, "ttl": ttl_seconds})
                    renewed = cur.rowcount > 0
                conn.commit()

            if not renewed:
                logger.warning("Lease renewal failed — lease lost (holder=%s)", holder_id)

            return renewed
        except Exception as exc:
            logger.error("Failed to renew lease: %s", exc)
            return False  # Treat DB errors as lease-lost — stop orchestrating

    def release(self, holder_id: Optional[str] = None) -> None:
        """
        Release the lease. Only the current holder can release.

        Called during graceful shutdown. If not called (crash), the lease
        expires naturally after TTL.
        """
        holder_id = holder_id or _generate_holder_id()

        query = sql.SQL(
            "DELETE FROM {schema}.{table} "
            "WHERE lease_key = 'singleton' AND holder_id = %(holder_id)s"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
        )

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, {"holder_id": holder_id})
                conn.commit()
            logger.info("Lease released: holder=%s", holder_id)
        except Exception as exc:
            logger.warning("Failed to release lease (non-fatal): %s", exc)

    def get_current(self) -> Optional[dict]:
        """
        Read the current lease state. For diagnostics and health checks.

        Returns dict with lease_key, holder_id, acquired_at, expires_at,
        renewed_at, and computed is_expired field. Returns None if no
        lease row exists.
        """
        query = sql.SQL(
            "SELECT *, (expires_at < NOW()) as is_expired "
            "FROM {schema}.{table} WHERE lease_key = 'singleton'"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
        )

        try:
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query)
                    return cur.fetchone()
        except Exception as exc:
            logger.error("Failed to read lease: %s", exc)
            return None
```

- [ ] **Step 2: Commit**

```bash
git add infrastructure/lease_repository.py
git commit -m "feat: LeaseRepository — atomic acquire/renew/release for orchestrator mutex"
```

---

## Task 3: Wire Lease into DAGOrchestrator

**Files:**
- Modify: `core/dag_orchestrator.py`

Replace `_try_acquire_xact_lock` and the advisory lock call in `run()` with lease acquire. The lease is acquired **per poll cycle** in the primary loop (Task 4), not per `run()` call. The orchestrator's `run()` method just needs to know it's authorized — the primary loop handles the lease lifecycle.

- [ ] **Step 1: Remove advisory lock methods and imports**

Remove:
- `_advisory_lock_id()` helper function (the `hashlib` import for it can be removed too if unused elsewhere)
- `_try_acquire_xact_lock()` method
- The lock acquisition block in `run()` (Step 1: lines 311-323)
- Update the module docstring to reference lease instead of advisory lock

- [ ] **Step 2: Add lease-lost check parameter to run()**

The primary loop will pass a callable that `run()` can check mid-cycle:

```python
def run(
    self,
    run_id: str,
    max_cycles: int = 1000,
    cycle_interval: float = 5.0,
    shutdown_event: Optional[threading.Event] = None,
    lease_check: Optional[callable] = None,
) -> OrchestratorResult:
```

In the poll loop, before each cycle, check if the lease is still held:

```python
# At the start of each cycle (inside the existing poll loop):
if lease_check and not lease_check():
    result.error = "lease_lost"
    logger.warning("DAGOrchestrator.run: lease lost for run_id=%s — stopping", run_id)
    break
```

This replaces the old `lock_held` error path. The orchestrator doesn't manage the lease itself — it just respects a callback that says "you still have permission to run."

- [ ] **Step 3: Update module docstring**

Update the file header and `run()` docstring to reference lease instead of advisory lock.

- [ ] **Step 4: Commit**

```bash
git add core/dag_orchestrator.py
git commit -m "refactor: replace advisory lock with lease_check callback in DAGOrchestrator"
```

---

## Task 4: Wire Lease into DAG Brain Primary Loop

**Files:**
- Modify: `docker_service.py` (the `DAGBrainPrimaryLoop` class, ~lines 1022-1115)

This is the main integration point. The primary loop acquires the lease on startup, renews it every scan cycle, and stops if the lease is lost.

- [ ] **Step 1: Add lease lifecycle to `__init__` and `_loop`**

In `__init__`, create a `LeaseRepository` and generate a `holder_id`:

```python
from infrastructure.lease_repository import LeaseRepository, _generate_holder_id

self._lease_repo = LeaseRepository()
self._holder_id = _generate_holder_id()
```

In `_loop`, restructure to:

1. Ensure lease table exists (idempotent)
2. Acquire lease (retry with backoff if held by another instance)
3. In the scan loop, renew lease every cycle
4. If renewal fails, stop scanning (lease lost)
5. Release lease in finally block (graceful shutdown)

```python
def _loop(self):
    from core.dag_orchestrator import DAGOrchestrator

    # Ensure lease table exists (idempotent, first-boot only)
    try:
        self._lease_repo.ensure_table()
    except Exception as exc:
        logger.error("DAG Brain: failed to ensure lease table: %s", exc)

    logger.info("DAG Brain primary loop started (scan_interval=%.1fs)", self._scan_interval)

    while not self._stop_event.is_set():
        # Acquire lease (blocks with backoff until acquired or shutdown)
        if not self._lease_repo.try_acquire(self._holder_id):
            logger.info("DAG Brain: lease held by another instance, waiting...")
            self._stop_event.wait(timeout=self._scan_interval)
            continue

        logger.info("DAG Brain: lease acquired (holder=%s)", self._holder_id)

        try:
            # Inner scan loop — runs while we hold the lease
            while not self._stop_event.is_set():
                made_progress = False
                try:
                    # Renew lease at the start of each scan
                    if not self._lease_repo.renew(self._holder_id):
                        logger.warning("DAG Brain: lease lost — stopping scan loop")
                        break

                    active_run_ids = self._repo.list_active_runs()
                    self._total_scans += 1
                    self._last_scan_at = datetime.now(timezone.utc)

                    if active_run_ids:
                        logger.info(
                            "DAG Brain scan %d: %d active run(s)",
                            self._total_scans, len(active_run_ids),
                        )

                    for run_id in active_run_ids:
                        if self._stop_event.is_set():
                            break

                        try:
                            orchestrator = DAGOrchestrator(self._repo)
                            result = orchestrator.run(
                                run_id,
                                max_cycles=1,
                                cycle_interval=0.0,
                                shutdown_event=self._stop_event,
                            )
                            self._total_cycles += 1

                            if result.tasks_promoted > 0 or result.tasks_skipped > 0 or result.tasks_failed > 0:
                                made_progress = True

                            if result.error:
                                logger.warning(
                                    "DAG Brain: run_id=%s cycle result: status=%s error=%s",
                                    run_id[:16], result.final_status.value, result.error,
                                )
                        except Exception as run_exc:
                            logger.error(
                                "DAG Brain: run_id=%s orchestration error: %s",
                                run_id[:16], run_exc, exc_info=True,
                            )

                except Exception as exc:
                    logger.error("DAG Brain primary loop scan error: %s", exc, exc_info=True)

                if made_progress:
                    continue

                self._stop_event.wait(timeout=self._scan_interval)

        finally:
            # Release lease on exit (graceful shutdown or lease-lost)
            self._lease_repo.release(self._holder_id)
            logger.info("DAG Brain: lease released (holder=%s)", self._holder_id)

    logger.info(
        "DAG Brain primary loop stopped (scans=%d cycles=%d)",
        self._total_scans, self._total_cycles,
    )
```

Note: The `lease_check` callback on `orchestrator.run()` is optional and not wired here because `max_cycles=1` means the orchestrator does one cycle and returns. The lease renewal happens in the outer loop between cycles. For long-running orchestrator calls (max_cycles > 1, used in tests), the callback can be wired later.

- [ ] **Step 2: Commit**

```bash
git add docker_service.py
git commit -m "feat: DAG Brain primary loop uses lease for orchestrator exclusion"
```

---

## Task 5: Wire Lease into Health Check

**Files:**
- Modify: `docker_health/dag_brain.py`

- [ ] **Step 1: Add lease check to health subsystem**

Add a `_check_lease` method and include it in the health components:

```python
def _check_lease(self) -> Dict[str, Any]:
    """Check orchestrator lease status."""
    try:
        from infrastructure.lease_repository import LeaseRepository
        repo = LeaseRepository()
        lease = repo.get_current()

        if not lease:
            return self.build_component(
                status="unhealthy",
                description="Orchestrator lease",
                source="dag_brain",
                details={"note": "No lease row — table may not be initialized"},
            )

        return self.build_component(
            status="healthy" if not lease["is_expired"] else "unhealthy",
            description="Orchestrator lease",
            source="dag_brain",
            details={
                "holder_id": lease["holder_id"],
                "expires_at": str(lease["expires_at"]),
                "renewed_at": str(lease["renewed_at"]),
                "is_expired": lease["is_expired"],
            },
        )
    except Exception as e:
        return self.build_component(
            status="unhealthy",
            description="Orchestrator lease",
            source="dag_brain",
            details={"error": str(e)},
        )
```

Find where the existing health components are collected (look for a list or dict of `_check_*` calls) and add `_check_lease` to it.

- [ ] **Step 2: Commit**

```bash
git add docker_health/dag_brain.py
git commit -m "feat: health check includes orchestrator lease status"
```

---

## Task 6: Cleanup and Verification

- [ ] **Step 1: Remove dead advisory lock code**

Verify that `_advisory_lock_id` and any `hashlib` import used only for it are removed from `dag_orchestrator.py`. Verify no other file references `_try_acquire_xact_lock` or `advisory_lock`.

- [ ] **Step 2: Verify the `lock_held` error path is removed**

The old code returned `result.error = "lock_held"` when the advisory lock was not acquired. The primary loop checked for this at line 1092: `if result.error and result.error != "lock_held"`. With the lease, the orchestrator's `run()` no longer returns `lock_held` — the primary loop handles exclusion before calling `run()`. Remove the `lock_held` check from the primary loop.

- [ ] **Step 3: Syntax verification**

```bash
conda activate azgeo
python -c "from infrastructure.lease_repository import LeaseRepository; print('OK')"
python -c "from core.dag_orchestrator import DAGOrchestrator; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add core/dag_orchestrator.py docker_service.py
git commit -m "chore: remove advisory lock remnants, clean up lock_held error path"
```

---

## Notes

### Lease TTL
60 seconds. Renewed every scan cycle (default 5s). This gives 12 renewal opportunities before expiry. Even with a few missed renewals (transient DB errors), the lease won't expire prematurely.

### Recovery Scenario
```
Brain A: acquires lease → polls → completes 15/24 tiles → CRASH
         (lease expires 60s later)
Brain B: starts → tries acquire → lease expired → acquires
         → list_active_runs() → finds RUNNING run
         → evaluates tasks → 15 COMPLETED, 9 READY → dispatches 9
         → completes workflow
```

### What Doesn't Change
- CAS guards on every mutation — defense-in-depth stays
- `DAGOrchestrator.run()` API — still takes run_id, returns OrchestratorResult
- Worker task claiming — SKIP LOCKED is unchanged
- Fast rescan on progress — unchanged

### Table Creation
`ensure_table()` is called once on primary loop startup. It's `CREATE TABLE IF NOT EXISTS` — idempotent. No migration needed for existing deployments.
