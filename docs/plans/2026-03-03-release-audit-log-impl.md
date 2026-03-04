# Release Audit Log & In-Place Ordinal Revision — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable in-place revision of revoked ordinals with an append-only audit log that preserves release state transitions before destructive mutations.

**Architecture:** New `ReleaseAuditEvent` model + `ReleaseAuditRepository` following the `JobEvent`/`job_events` pattern (SERIAL PK, ClassVar metadata, `generate_table_from_model`). Three surgical changes to existing code: `can_overwrite()`, `update_overwrite()`, stale ordinal guard.

**Tech Stack:** Pydantic model, psycopg SQL composition, PostgreSQL append-only table, existing PydanticToSQL schema generator.

**Spec:** `docs/plans/2026-03-03-release-audit-log.md`

---

### Task 1: Create the `ReleaseAuditEvent` model

**Files:**
- Create: `core/models/release_audit.py`

**Context:** Follow the `JobEvent` pattern in `core/models/job_event.py`. Use `ClassVar` metadata (`__sql_table_name`, `__sql_schema`, `__sql_primary_key`, `__sql_serial_columns`, `__sql_indexes`). The enum `ReleaseAuditEventType` is a `str, Enum`. The model uses `BIGSERIAL` via `__sql_serial_columns`.

**Step 1: Create the model file**

```python
# core/models/release_audit.py
# ============================================================================
# CLAUDE CONTEXT - RELEASE AUDIT LOG MODELS
# ============================================================================
# STATUS: Core - Append-only release lifecycle event tracking
# PURPOSE: Preserve release state transitions before destructive mutations
# CREATED: 03 MAR 2026
# LAST_REVIEWED: 03 MAR 2026
# ============================================================================
"""
Release Audit Log Models.

Append-only event journal that captures release state at each lifecycle
transition. Exists to preserve audit trail when update_overwrite() resets
the release row for resubmission.

This is NOT a restore mechanism. It records what happened.
It does NOT store blob data or enable rollback.

Exports:
    ReleaseAuditEventType: Event type enum
    ReleaseAuditEvent: Database model for audit records

Dependencies:
    pydantic: Data validation
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, ClassVar
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, field_serializer


# ============================================================================
# ENUMS
# ============================================================================

class ReleaseAuditEventType(str, Enum):
    """
    Release lifecycle events that produce audit records.

    Every state-changing operation on a release row emits one of these.
    OVERWRITTEN is the critical event — it fires before update_overwrite()
    destroys approval/revocation fields.
    """
    CREATED = "created"
    PROCESSING_STARTED = "processing_started"
    PROCESSING_COMPLETED = "processing_completed"
    PROCESSING_FAILED = "processing_failed"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"
    OVERWRITTEN = "overwritten"


# ============================================================================
# DATABASE MODEL
# ============================================================================

class ReleaseAuditEvent(BaseModel):
    """
    Release audit event — append-only lifecycle record.

    Auto-generates:
        CREATE TABLE app.release_audit (
            audit_id BIGSERIAL PRIMARY KEY,
            release_id VARCHAR(64) NOT NULL,
            asset_id VARCHAR(64) NOT NULL,
            version_ordinal INTEGER NOT NULL,
            revision INTEGER NOT NULL,
            event_type app.release_audit_event_type NOT NULL,
            actor VARCHAR(200),
            reason TEXT,
            snapshot JSONB NOT NULL DEFAULT '{}',
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """

    model_config = ConfigDict()

    @field_serializer('created_at')
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

    # ========================================================================
    # SQL DDL METADATA
    # ========================================================================
    __sql_table_name: ClassVar[str] = "release_audit"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["audit_id"]
    __sql_serial_columns: ClassVar[List[str]] = ["audit_id"]
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"name": "idx_release_audit_release_id", "columns": ["release_id"]},
        {"name": "idx_release_audit_asset_ord", "columns": ["asset_id", "version_ordinal"]},
        {"name": "idx_release_audit_event_type", "columns": ["event_type"]},
        {"name": "idx_release_audit_created_at", "columns": ["created_at"], "descending": True},
    ]

    # ========================================================================
    # PRIMARY KEY (Auto-increment)
    # ========================================================================
    audit_id: Optional[int] = Field(
        None,
        description="Auto-increment audit ID (BIGSERIAL)"
    )

    # ========================================================================
    # RELEASE IDENTITY (denormalized for query efficiency)
    # ========================================================================
    release_id: str = Field(
        ...,
        max_length=64,
        description="Release this event belongs to"
    )
    asset_id: str = Field(
        ...,
        max_length=64,
        description="Asset ID (denormalized — avoids join for ordinal queries)"
    )
    version_ordinal: int = Field(
        ...,
        ge=0,
        description="Ordinal at event time"
    )
    revision: int = Field(
        ...,
        ge=1,
        description="Revision cycle this event belongs to"
    )

    # ========================================================================
    # EVENT DATA
    # ========================================================================
    event_type: ReleaseAuditEventType = Field(
        ...,
        description="Lifecycle event type"
    )
    actor: Optional[str] = Field(
        None,
        max_length=200,
        description="Who triggered the event (user email or 'system')"
    )
    reason: Optional[str] = Field(
        None,
        description="Human-readable reason (revocation reason, rejection reason, etc.)"
    )

    # ========================================================================
    # STATE SNAPSHOT
    # ========================================================================
    snapshot: Dict[str, Any] = Field(
        default_factory=dict,
        description="Frozen release.to_dict() at event time — the 'before' state"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible event-specific data"
    )

    # ========================================================================
    # TIMESTAMP
    # ========================================================================
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this event was recorded"
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            'audit_id': self.audit_id,
            'release_id': self.release_id,
            'asset_id': self.asset_id,
            'version_ordinal': self.version_ordinal,
            'revision': self.revision,
            'event_type': self.event_type.value if isinstance(self.event_type, ReleaseAuditEventType) else self.event_type,
            'actor': self.actor,
            'reason': self.reason,
            'snapshot': self.snapshot,
            'metadata': self.metadata,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'ReleaseAuditEventType',
    'ReleaseAuditEvent',
]
```

**Step 2: Verify syntax**

Run: `python -m py_compile core/models/release_audit.py`
Expected: No output (clean compile)

**Step 3: Commit**

```bash
git add core/models/release_audit.py
git commit -m "feat: add ReleaseAuditEvent model and enum"
```

---

### Task 2: Create the `ReleaseAuditRepository`

**Files:**
- Create: `infrastructure/release_audit_repository.py`

**Context:** Follow `infrastructure/artifact_repository.py` pattern. Append-only — only `record_event()` and read methods. No update or delete. Non-fatal emission pattern: callers wrap in try/except.

**Step 1: Create the repository file**

```python
# infrastructure/release_audit_repository.py
# ============================================================================
# CLAUDE CONTEXT - RELEASE AUDIT REPOSITORY
# ============================================================================
# STATUS: Infrastructure - Append-only audit event CRUD
# PURPOSE: Database operations for app.release_audit table
# CREATED: 03 MAR 2026
# LAST_REVIEWED: 03 MAR 2026
# ============================================================================
"""
Release Audit Repository - Append-Only Event Log.

Provides write and read operations for the release_audit table.
This is append-only: no update or delete methods.

Methods:
    record_event(...) - Insert audit event (non-fatal on failure)
    get_events_for_release(release_id) - All events for a release
    get_events_for_ordinal(asset_id, version_ordinal) - Events across revisions
    get_events_by_type(event_type, limit) - Filter by event type
    get_recent_events(hours, limit) - Recent events

Exports:
    ReleaseAuditRepository: Append-only audit CRUD
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from psycopg import sql

from infrastructure.postgresql import PostgreSQLRepository
from core.models.release_audit import ReleaseAuditEvent, ReleaseAuditEventType

from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "ReleaseAudit")


class ReleaseAuditRepository(PostgreSQLRepository):
    """
    Repository for release audit event operations.

    Append-only: record_event() inserts, read methods query.
    No update or delete — audit log is immutable.
    """

    def __init__(self):
        super().__init__()
        self.table = "release_audit"
        self.schema = "app"

    def record_event(
        self,
        release_id: str,
        asset_id: str,
        version_ordinal: int,
        revision: int,
        event_type: ReleaseAuditEventType,
        actor: Optional[str] = None,
        reason: Optional[str] = None,
        snapshot: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:
        """
        Record a release audit event. Returns audit_id or None on failure.

        This method is designed to be called inside a try/except by the caller.
        Audit emission must NEVER block the pipeline.
        """
        logger.info(
            f"Audit: {event_type.value} for release {release_id[:16]}... "
            f"(ord={version_ordinal}, rev={revision})"
        )

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        INSERT INTO {}.{}
                            (release_id, asset_id, version_ordinal, revision,
                             event_type, actor, reason, snapshot, metadata, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, NOW())
                        RETURNING audit_id
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (
                        release_id,
                        asset_id,
                        version_ordinal,
                        revision,
                        event_type.value,
                        actor,
                        reason,
                        json.dumps(snapshot or {}),
                        json.dumps(metadata or {}),
                    )
                )
                conn.commit()
                row = cur.fetchone()
                audit_id = row[0] if row else None
                if audit_id:
                    logger.info(f"Audit event {audit_id} recorded")
                return audit_id

    def get_events_for_release(self, release_id: str) -> List[ReleaseAuditEvent]:
        """All events for a release, ordered chronologically."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE release_id = %s
                        ORDER BY created_at ASC
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (release_id,)
                )
                rows = cur.fetchall()
                columns = [desc.name for desc in cur.description]
                return [self._row_to_event(dict(zip(columns, row))) for row in rows]

    def get_events_for_ordinal(
        self, asset_id: str, version_ordinal: int
    ) -> List[ReleaseAuditEvent]:
        """All events for an ordinal across all revisions."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE asset_id = %s AND version_ordinal = %s
                        ORDER BY created_at ASC
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (asset_id, version_ordinal)
                )
                rows = cur.fetchall()
                columns = [desc.name for desc in cur.description]
                return [self._row_to_event(dict(zip(columns, row))) for row in rows]

    def get_events_by_type(
        self, event_type: ReleaseAuditEventType, limit: int = 50
    ) -> List[ReleaseAuditEvent]:
        """Recent events of a specific type."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE event_type = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (event_type.value, limit)
                )
                rows = cur.fetchall()
                columns = [desc.name for desc in cur.description]
                return [self._row_to_event(dict(zip(columns, row))) for row in rows]

    def get_recent_events(
        self, hours: int = 24, limit: int = 100
    ) -> List[ReleaseAuditEvent]:
        """Recent audit events across all releases."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT * FROM {}.{}
                        WHERE created_at >= NOW() - INTERVAL '%s hours'
                        ORDER BY created_at DESC
                        LIMIT %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (hours, limit)
                )
                rows = cur.fetchall()
                columns = [desc.name for desc in cur.description]
                return [self._row_to_event(dict(zip(columns, row))) for row in rows]

    def _row_to_event(self, row: Dict[str, Any]) -> ReleaseAuditEvent:
        """Convert database row dict to ReleaseAuditEvent model."""
        snapshot = row.get('snapshot', {})
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        meta = row.get('metadata', {})
        if isinstance(meta, str):
            meta = json.loads(meta)

        return ReleaseAuditEvent(
            audit_id=row.get('audit_id'),
            release_id=row['release_id'],
            asset_id=row['asset_id'],
            version_ordinal=row['version_ordinal'],
            revision=row['revision'],
            event_type=ReleaseAuditEventType(row['event_type']),
            actor=row.get('actor'),
            reason=row.get('reason'),
            snapshot=snapshot,
            metadata=meta,
            created_at=row['created_at'],
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'ReleaseAuditRepository',
]
```

**Step 2: Verify syntax**

Run: `python -m py_compile infrastructure/release_audit_repository.py`
Expected: No output (clean compile)

**Step 3: Commit**

```bash
git add infrastructure/release_audit_repository.py
git commit -m "feat: add ReleaseAuditRepository (append-only)"
```

---

### Task 3: Register model in schema generator

**Files:**
- Modify: `core/schema/sql_generator.py:59-85` (imports), `core/schema/sql_generator.py:1697-1698` (enum), `core/schema/sql_generator.py:1722-1723` (table), `core/schema/sql_generator.py:1743-1744` (indexes)

**Context:** Three insertion points in `generate_composed_statements()`. Follow the `JobEvent` registration pattern exactly.

**Step 1: Add import** at `core/schema/sql_generator.py:85` (after the `job_event` import line):

```python
from ..models.release_audit import ReleaseAuditEvent, ReleaseAuditEventType  # Release audit log (03 MAR 2026)
```

**Step 2: Add enum generation** after line 1697 (after the `processing_status` enum):

```python
composed.extend(self.generate_enum("release_audit_event_type", ReleaseAuditEventType))  # Release audit log (03 MAR 2026)
```

**Step 3: Add table generation** after line 1723 (after the `ReleaseTable` line):

```python
composed.append(self.generate_table_from_model(ReleaseAuditEvent))  # Release audit log (03 MAR 2026)
```

**Step 4: Add index generation** after line 1744 (after the `ReleaseTable` indexes):

```python
composed.extend(self.generate_indexes_from_model(ReleaseAuditEvent))  # Release audit log (03 MAR 2026)
```

**Step 5: Verify syntax**

Run: `python -m py_compile core/schema/sql_generator.py`
Expected: No output (clean compile)

**Step 6: Verify import chain**

Run: `python -c "from core.models.release_audit import ReleaseAuditEvent, ReleaseAuditEventType; print('Model OK'); from infrastructure.release_audit_repository import ReleaseAuditRepository; print('Repo OK')"`
Expected: `Model OK` / `Repo OK`

**Step 7: Commit**

```bash
git add core/schema/sql_generator.py
git commit -m "feat: register ReleaseAuditEvent in schema generator"
```

---

### Task 4: Wire audit emission into `update_overwrite()`

**Files:**
- Modify: `infrastructure/release_repository.py:970-1014`

**Context:** This is the CRITICAL integration point. Before `update_overwrite()` resets the release row, snapshot its current state into the audit log. Also clear revocation fields (`revoked_at`, `revoked_by`, `revocation_reason`) and set `is_served = FALSE` during the reset.

**Step 1: Add audit emission and clear revocation fields**

At `infrastructure/release_repository.py:970`, replace the entire `update_overwrite` method:

```python
    def update_overwrite(self, release_id: str, revision: int) -> bool:
        """
        Reset processing lifecycle for re-submission (overwrite).

        Emits OVERWRITTEN audit event BEFORE resetting fields.
        Clears all processing, approval, AND revocation fields.

        Args:
            release_id: Release to reset
            revision: New revision number

        Returns:
            True if updated, False if release not found
        """
        logger.info(f"Resetting release {release_id[:16]}... for overwrite (revision={revision})")

        # Snapshot BEFORE reset (non-fatal)
        try:
            release = self.get_by_id(release_id)
            if release:
                from infrastructure.release_audit_repository import ReleaseAuditRepository
                from core.models.release_audit import ReleaseAuditEventType
                audit_repo = ReleaseAuditRepository()
                audit_repo.record_event(
                    release_id=release_id,
                    asset_id=release.asset_id,
                    version_ordinal=release.version_ordinal,
                    revision=release.revision,
                    event_type=ReleaseAuditEventType.OVERWRITTEN,
                    actor="system",
                    reason="Release overwritten for resubmission",
                    snapshot=release.to_dict(),
                )
        except Exception as audit_err:
            logger.warning(f"Audit emission failed (non-fatal): {audit_err}")

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        UPDATE {}.{}
                        SET revision = %s,
                            processing_status = %s,
                            approval_state = %s,
                            rejection_reason = NULL,
                            reviewer = NULL,
                            reviewed_at = NULL,
                            revoked_at = NULL,
                            revoked_by = NULL,
                            revocation_reason = NULL,
                            is_served = FALSE,
                            job_id = NULL,
                            processing_started_at = NULL,
                            processing_completed_at = NULL,
                            last_error = NULL,
                            updated_at = NOW()
                        WHERE release_id = %s
                    """).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.table)
                    ),
                    (revision, ProcessingStatus.PENDING, ApprovalState.PENDING_REVIEW, release_id)
                )
                conn.commit()

                updated = cur.rowcount > 0
                if updated:
                    logger.info(f"Reset release {release_id[:16]}... for overwrite at revision {revision}")
                return updated
```

**Step 2: Verify syntax**

Run: `python -m py_compile infrastructure/release_repository.py`
Expected: No output (clean compile)

**Step 3: Commit**

```bash
git add infrastructure/release_repository.py
git commit -m "feat: emit OVERWRITTEN audit event + clear revocation fields in update_overwrite"
```

---

### Task 5: Wire audit emission into `update_revocation()`

**Files:**
- Modify: `infrastructure/release_repository.py:787-830`

**Context:** Same non-fatal pattern. Snapshot the APPROVED state before it becomes REVOKED.

**Step 1: Add audit emission before the UPDATE**

Read `infrastructure/release_repository.py:787-830` for current code. Insert the audit block after the logger.info and before the `with self._get_connection()` block:

```python
        # Snapshot BEFORE revocation (non-fatal)
        try:
            release = self.get_by_id(release_id)
            if release:
                from infrastructure.release_audit_repository import ReleaseAuditRepository
                from core.models.release_audit import ReleaseAuditEventType
                audit_repo = ReleaseAuditRepository()
                audit_repo.record_event(
                    release_id=release_id,
                    asset_id=release.asset_id,
                    version_ordinal=release.version_ordinal,
                    revision=release.revision,
                    event_type=ReleaseAuditEventType.REVOKED,
                    actor=revoked_by,
                    reason=revocation_reason,
                    snapshot=release.to_dict(),
                )
        except Exception as audit_err:
            logger.warning(f"Audit emission failed (non-fatal): {audit_err}")
```

**Step 2: Verify syntax**

Run: `python -m py_compile infrastructure/release_repository.py`
Expected: No output (clean compile)

**Step 3: Commit**

```bash
git add infrastructure/release_repository.py
git commit -m "feat: emit REVOKED audit event before update_revocation"
```

---

### Task 6: Wire audit emission into `approve_release_atomic()`

**Files:**
- Modify: `infrastructure/release_repository.py` — find `approve_release_atomic` method

**Context:** Snapshot the PENDING_REVIEW state before it becomes APPROVED. The `reviewer` parameter is available as the actor.

**Step 1: Read the method to find exact insertion point**

Run: `grep -n "def approve_release_atomic" infrastructure/release_repository.py`

**Step 2: Add audit emission before the atomic UPDATE**

Same pattern — insert after the method's initial validation and before the SQL execution:

```python
        # Snapshot BEFORE approval (non-fatal)
        try:
            release = self.get_by_id(release_id)
            if release:
                from infrastructure.release_audit_repository import ReleaseAuditRepository
                from core.models.release_audit import ReleaseAuditEventType
                audit_repo = ReleaseAuditRepository()
                audit_repo.record_event(
                    release_id=release_id,
                    asset_id=release.asset_id,
                    version_ordinal=release.version_ordinal,
                    revision=release.revision,
                    event_type=ReleaseAuditEventType.APPROVED,
                    actor=reviewer,
                    snapshot=release.to_dict(),
                )
        except Exception as audit_err:
            logger.warning(f"Audit emission failed (non-fatal): {audit_err}")
```

**Step 3: Verify syntax**

Run: `python -m py_compile infrastructure/release_repository.py`
Expected: No output (clean compile)

**Step 4: Commit**

```bash
git add infrastructure/release_repository.py
git commit -m "feat: emit APPROVED audit event before approve_release_atomic"
```

---

### Task 7: Extend `can_overwrite()` to accept REVOKED

**Files:**
- Modify: `core/models/asset.py:656-662`

**Context:** One-line change. Add `ApprovalState.REVOKED` to the allowed tuple.

**Step 1: Edit the method**

At `core/models/asset.py:658`, change the tuple:

```python
# Before:
        if self.approval_state not in (ApprovalState.PENDING_REVIEW, ApprovalState.REJECTED):

# After:
        if self.approval_state not in (ApprovalState.PENDING_REVIEW, ApprovalState.REJECTED, ApprovalState.REVOKED):
```

**Step 2: Verify syntax**

Run: `python -m py_compile core/models/asset.py`
Expected: No output (clean compile)

**Step 3: Commit**

```bash
git add core/models/asset.py
git commit -m "feat: can_overwrite() accepts REVOKED for in-place ordinal revision"
```

---

### Task 8: Stale ordinal guard exemption for revision > 1

**Files:**
- Modify: `services/asset_approval_service.py:166-186`

**Context:** The stale ordinal guard blocks approval of ordinal N when ordinal N+1 exists. For in-place revision (revision > 1), this guard must be skipped — the ordinal was previously approved and is being re-approved after revocation + overwrite.

**Step 1: Add revision check**

At `services/asset_approval_service.py:167`, change:

```python
# Before:
        if release.version_ordinal:

# After:
        # Skip guard for in-place revisions (revision > 1 means previously approved,
        # revoked, then overwritten for resubmission)
        if release.version_ordinal and release.revision == 1:
```

**Step 2: Verify syntax**

Run: `python -m py_compile services/asset_approval_service.py`
Expected: No output (clean compile)

**Step 3: Commit**

```bash
git add services/asset_approval_service.py
git commit -m "feat: stale ordinal guard exemption for in-place revision (revision > 1)"
```

---

### Task 9: Full integration verification

**Files:** None modified — verification only.

**Step 1: Syntax check all modified files**

Run:
```bash
python -m py_compile core/models/release_audit.py && \
python -m py_compile infrastructure/release_audit_repository.py && \
python -m py_compile core/schema/sql_generator.py && \
python -m py_compile infrastructure/release_repository.py && \
python -m py_compile core/models/asset.py && \
python -m py_compile services/asset_approval_service.py && \
echo "ALL PASS"
```
Expected: `ALL PASS`

**Step 2: Verify import chain**

Run:
```bash
python -c "
from core.models.release_audit import ReleaseAuditEvent, ReleaseAuditEventType
print(f'Enum values: {[e.value for e in ReleaseAuditEventType]}')
from infrastructure.release_audit_repository import ReleaseAuditRepository
print('Repository import OK')
from services import ALL_HANDLERS
print(f'Handlers: {len(ALL_HANDLERS)}')
from jobs import ALL_JOBS
print(f'Jobs: {len(ALL_JOBS)}')
"
```
Expected: 8 enum values, 32 handlers, 12 jobs

**Step 3: Verify can_overwrite accepts REVOKED**

Run:
```bash
python -c "
from core.models.asset import AssetRelease, ApprovalState, ProcessingStatus
r = AssetRelease(
    release_id='test', asset_id='test',
    approval_state=ApprovalState.REVOKED,
    processing_status=ProcessingStatus.COMPLETED,
)
assert r.can_overwrite() == True, 'REVOKED should be overwritable'
print('can_overwrite(REVOKED) = True  PASS')
r2 = AssetRelease(
    release_id='test', asset_id='test',
    approval_state=ApprovalState.APPROVED,
    processing_status=ProcessingStatus.COMPLETED,
)
assert r2.can_overwrite() == False, 'APPROVED should NOT be overwritable'
print('can_overwrite(APPROVED) = False  PASS')
"
```
Expected: Both assertions pass

**Step 4: Commit (if any fixups needed)**

No commit if all pass. If fixups were needed, commit the fixes.

---

## Dependency Graph

```
Task 1 (model) ──┬── Task 2 (repository)
                  │
                  └── Task 3 (schema generator)

Task 1 + 2 ───────── Task 4 (update_overwrite audit)
                  │
                  ├── Task 5 (update_revocation audit)
                  │
                  └── Task 6 (approve_release_atomic audit)

Task 7 (can_overwrite) ── independent
Task 8 (stale guard)   ── independent

Task 9 (verification)  ── depends on ALL above
```

Tasks 7 and 8 can run in parallel with Tasks 4-6.

---

## Post-Implementation

After Task 9 passes, the feature is ready for:
1. **COMPETE adversarial review** — stress-test the revision > 1 guard exemption, overwrite targeting for multiple revoked ordinals, version_id conflict guard
2. **Deploy + `action=ensure`** — creates the `release_audit` table and `release_audit_event_type` enum
3. **Manual test** — revoke an ordinal, resubmit with overwrite=true, verify audit trail
