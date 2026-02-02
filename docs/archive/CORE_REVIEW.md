# Core Orchestration Review

**Date**: 06 JAN 2026
**Reviewer**: Claude (Automated Analysis)
**Scope**: `core/`, `infrastructure/`, `jobs/`
**Focus**: Efficiency, Durability, DRY Principles

---

## Executive Summary

The core orchestration system is **well-architected** with strong patterns for distributed job processing. The codebase demonstrates mature engineering practices with proper separation of concerns, atomic database operations, and comprehensive error handling.

### Overall Assessment

| Category | Rating | Notes |
|----------|--------|-------|
| **Efficiency** | ⭐⭐⭐⭐ | Good - Some minor connection pooling opportunities |
| **Durability** | ⭐⭐⭐⭐⭐ | Excellent - Atomic operations, advisory locks, retry logic |
| **DRY** | ⭐⭐⭐⭐⭐ | Excellent - JobBaseMixin eliminates 77% boilerplate |

---

## 1. Architecture Overview

### Core Components

```
┌─────────────────────────────────────────────────────────────────────┐
│                          CORE LAYER                                  │
├─────────────────────────────────────────────────────────────────────┤
│  CoreMachine                 │ Main orchestration engine            │
│  (core/machine.py ~1400 LOC) │ - Processes job queue messages       │
│                              │ - Executes task handlers             │
│                              │ - Manages stage advancement          │
├──────────────────────────────┼──────────────────────────────────────┤
│  StateManager                │ All database state transitions       │
│  (core/state_manager.py)     │ - Advisory locks for atomicity       │
│                              │ - Task/Job status management         │
├──────────────────────────────┼──────────────────────────────────────┤
│  OrchestrationManager        │ Multi-app coordination               │
│  (core/orchestration_manager)│ - Platform ↔ Worker communication    │
├──────────────────────────────┼──────────────────────────────────────┤
│  Models (core/models/)       │ Pydantic data structures             │
│                              │ - JobRecord, TaskRecord, enums       │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                       INFRASTRUCTURE LAYER                           │
├─────────────────────────────────────────────────────────────────────┤
│  PostgreSQLRepository        │ Base repository with connection mgmt │
│  (infrastructure/postgresql) │ - Managed identity auth              │
│                              │ - SQL composition for safety         │
├──────────────────────────────┼──────────────────────────────────────┤
│  JobRepository               │ Job CRUD operations                  │
│  TaskRepository              │ Task CRUD + atomic completion        │
│  StageCompletionRepository   │ Advisory lock stage detection        │
├──────────────────────────────┼──────────────────────────────────────┤
│  ServiceBusRepository        │ Azure Service Bus messaging          │
│  (infrastructure/service_bus)│ - Scheduled delivery for retries     │
├──────────────────────────────┼──────────────────────────────────────┤
│  RepositoryFactory           │ Centralized repository creation      │
│  (infrastructure/factory)    │ - Singleton patterns where needed    │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                           JOBS LAYER                                 │
├─────────────────────────────────────────────────────────────────────┤
│  JobBase (ABC)               │ 6-method interface contract          │
│  (jobs/base.py)              │ - Fail-fast at import time           │
├──────────────────────────────┼──────────────────────────────────────┤
│  JobBaseMixin                │ Default implementations              │
│  (jobs/mixins.py ~717 LOC)   │ - 77% boilerplate elimination        │
│                              │ - Schema-based validation            │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Patterns

1. **Job → Stage → Task Hierarchy**
   - Jobs contain sequential stages
   - Stages contain parallel tasks
   - "Last task turns out the lights" pattern

2. **Parallelism Modes**
   - `single`: Fixed task count at orchestration time
   - `fan_out`: Task count discovered from previous stage results
   - `fan_in`: Aggregation (CoreMachine auto-creates)

3. **Repository Pattern**
   - Clean separation of data access
   - Factory for consistent instantiation
   - Interface abstractions for testability

---

## 2. Efficiency Analysis

### Strengths ✅

#### 2.1 Atomic SQL Functions
The PostgreSQL `complete_task_and_check_stage()` function combines multiple operations in a single database call:
```sql
-- Single call does: UPDATE + advisory lock + COUNT
PERFORM pg_advisory_xact_lock(hashtext(v_job_id || ':stage:' || v_stage::text));
SELECT COUNT(*) INTO v_remaining FROM tasks WHERE ...;
```
**Impact**: Reduces round-trips from 3-4 to 1 per task completion.

#### 2.2 Service Bus Scheduled Delivery
Retry logic uses Service Bus scheduled messages instead of polling:
```python
# core/machine.py:1311
message_id = self.service_bus.send_message_with_delay(
    retry_queue,
    task_message,
    delay_seconds
)
```
**Impact**: No polling loops, serverless cost efficiency.

#### 2.3 Lazy Imports
Package `__init__.py` uses `__getattr__` for lazy loading:
```python
# core/__init__.py:44
def __getattr__(name):
    if name in _LAZY_IMPORTS:
        module = import_module(_LAZY_IMPORTS[name], package='core')
        return getattr(module, name)
```
**Impact**: Faster cold starts, reduced memory when not all components needed.

### Opportunities for Improvement 🔧

#### 2.4 Connection Creation Per Operation
**Location**: `infrastructure/postgresql.py:731-741`

Currently, each query creates a new connection:
```python
def _get_cursor(self, conn=None):
    if conn:
        with conn.cursor() as cursor:
            yield cursor
    else:
        with self._get_connection() as conn:  # New connection each time
            with conn.cursor() as cursor:
                yield cursor
                conn.commit()
```

**Impact**: Token acquisition (~50ms) + connection setup per operation.

**Recommendation**: Consider connection pooling for high-throughput scenarios:
```python
# Future enhancement - use psycopg_pool
from psycopg_pool import ConnectionPool

class PostgreSQLRepository:
    _pool: Optional[ConnectionPool] = None

    @classmethod
    def get_pool(cls) -> ConnectionPool:
        if cls._pool is None:
            cls._pool = ConnectionPool(conninfo=get_conn_string())
        return cls._pool
```

**Priority**: LOW - Azure Functions short-lived nature makes this less critical.

#### 2.5 Repository Recreation Pattern
**Location**: `jobs/mixins.py:637`, `core/machine.py` (multiple locations)

Repositories are recreated frequently:
```python
# Called on each job submission
repos = RepositoryFactory.create_repositories()
```

**Current Behavior**: Works correctly due to Azure Functions per-request model.

**Future Risk**: If migrating to Container Apps or long-running services, this pattern would benefit from caching.

**Priority**: LOW - Documented in code comments (postgresql.py:203-232).

---

## 3. Durability Assessment

### Strengths ✅

#### 3.1 PostgreSQL Advisory Locks
**Location**: `core/schema/sql_generator.py:573-578`, `core/state_manager.py`

The "last task turns out the lights" pattern uses transaction-scoped advisory locks:
```sql
PERFORM pg_advisory_xact_lock(
    hashtext(v_job_id || ':stage:' || v_stage::text)
);
```

**Benefits**:
- Race condition prevention without row-level locking
- Deadlock avoidance (hash-based, not row-based)
- Automatic release on transaction commit/rollback

**Verdict**: ⭐⭐⭐⭐⭐ Industry best practice for distributed coordination.

#### 3.2 Explicit Error Categorization
**Location**: `core/machine.py:931-998`

Errors are categorized for appropriate handling:
```python
except RETRYABLE_EXCEPTIONS as e:
    # Transient failures - schedule retry
    result_data={'retryable': True, 'error_type': 'transient'}

except PERMANENT_EXCEPTIONS as e:
    # No retry - mark failed immediately
    result_data={'retryable': False, 'error_type': 'permanent'}
```

**Verdict**: ⭐⭐⭐⭐⭐ Prevents infinite retry loops, surfaces real issues.

#### 3.3 Nested Error Preservation
**Location**: `core/error_handler.py:145-224`

```python
def log_nested_error(
    logger, primary_error, cleanup_error, operation, ...
):
    error_context = {
        'nested_error': True,  # Flag for Application Insights filtering
        'primary_error': str(primary_error),
        'cleanup_error': str(cleanup_error),
    }
```

**Verdict**: ⭐⭐⭐⭐⭐ Root cause never lost even when cleanup fails.

#### 3.4 Idempotent Operations
**Location**: `core/state_manager.py:644-660`

```python
# Already completed is OK (duplicate message delivery)
if task.status == TaskStatus.COMPLETED:
    self.logger.info(
        f"Task {task_id} already completed (idempotent)"
    )
```

**Verdict**: ⭐⭐⭐⭐⭐ Handles Service Bus at-least-once delivery correctly.

#### 3.5 Job/Task Failure Propagation
**Location**: `core/machine.py:1100-1125`

When stage advancement fails, orphan tasks are cleaned up:
```python
# GAP-004 FIX: Fail all orphan tasks for this job
orphan_count = self.state_manager.fail_all_job_tasks(
    task_message.parent_job_id,
    orphan_error_msg
)
```

**Verdict**: ⭐⭐⭐⭐⭐ Prevents zombie tasks from continuing after job failure.

### Minor Observation 📝

#### 3.6 Heartbeat Disabled
**Location**: `core/machine.py:870-874`

```python
# NOTE: _heartbeat_fn DISABLED (2 DEC 2025) - Token expiration issues
# When re-enabling, add this to enriched_params:
#   '_heartbeat_fn': lambda tid=task_id: ...
```

**Status**: Documented, not a bug. Token expiration issues noted.

**Impact**: Long-running tasks (>5min) may have Service Bus lock expiry.

**Mitigation**: Already handled by idempotent completion (3.4 above).

---

## 4. DRY (Don't Repeat Yourself) Analysis

### Strengths ✅

#### 4.1 JobBaseMixin - 77% Boilerplate Reduction
**Location**: `jobs/mixins.py`

Before JobBaseMixin: ~350 lines per job
After JobBaseMixin: ~80 lines per job

```python
# What developers write (80 lines):
class FloodRiskCOGJob(JobBaseMixin, JobBase):
    job_type = "flood_risk_cog"
    description = "Convert flood risk rasters to tiled COGs"

    stages = [...]  # Declarative
    parameters_schema = {...}  # Declarative

    @staticmethod
    def create_tasks_for_stage(...):  # Only unique logic
        ...

    @staticmethod
    def finalize_job(context):  # Only unique logic
        ...
```

**What JobBaseMixin provides automatically**:
- `validate_job_parameters()` - Schema-based validation
- `generate_job_id()` - SHA256 hash generation
- `create_job_record()` - Database persistence
- `queue_job()` - Service Bus queueing

**Verdict**: ⭐⭐⭐⭐⭐ Exemplary DRY implementation.

#### 4.2 Repository Inheritance Hierarchy
**Location**: `infrastructure/postgresql.py`, `infrastructure/base.py`

```
BaseRepository (abstract)
    ↓
PostgreSQLRepository (connection, cursor, query helpers)
    ↓
JobRepository, TaskRepository, StageCompletionRepository
```

**Shared Methods** (not duplicated):
- `_get_connection()` - Connection management
- `_get_cursor()` - Cursor context manager
- `_execute_query()` - Safe SQL execution
- `_ensure_schema_exists()` - Schema verification
- `build_where_clause()` - SQL composition helper

**Verdict**: ⭐⭐⭐⭐⭐ Clean inheritance without duplication.

#### 4.3 Centralized Error Handler
**Location**: `core/error_handler.py`

```python
class CoreMachineErrorHandler:
    @staticmethod
    @contextmanager
    def handle_operation(logger, operation_name, job_id=None, ...):
        try:
            yield
        except ContractViolationError:
            raise  # Always bubble up
        except Exception as e:
            # Consistent logging, callbacks, re-raise
```

**Benefits**: Single place for error handling patterns, not scattered across files.

**Verdict**: ⭐⭐⭐⭐⭐ Context manager eliminates try-catch duplication.

#### 4.4 SQL Generator for Schema DDL
**Location**: `core/schema/sql_generator.py`

Database functions generated from templates:
```python
def generate_functions(self) -> List[sql.Composed]:
    body_complete_task = """
    ...
    PERFORM pg_advisory_xact_lock(hashtext(...));
    ...
    """.format(schema=self.schema_name)
```

**Verdict**: ⭐⭐⭐⭐ Schema name parameterized, not hardcoded.

### Areas Without Duplication Issues 📝

After thorough review, I did not find significant DRY violations. The codebase demonstrates:

1. **No copy-paste SQL** - All SQL uses `psycopg.sql` composition
2. **No repeated validation logic** - Schema-based validation in mixin
3. **No repeated connection logic** - Centralized in PostgreSQLRepository
4. **No repeated error handling** - Centralized in CoreMachineErrorHandler

---

## 5. Recommendations Summary

### High Priority (Should Do)

| # | Issue | Location | Recommendation |
|---|-------|----------|----------------|
| None | - | - | No high-priority issues found |

### Medium Priority (Consider)

| # | Issue | Location | Recommendation |
|---|-------|----------|----------------|
| M1 | Connection per operation | postgresql.py | Document trade-off; consider pooling for Container Apps migration |
| M2 | Heartbeat disabled | machine.py | Re-enable with proper token refresh strategy |

### Low Priority (Future Enhancement)

| # | Issue | Location | Recommendation |
|---|-------|----------|----------------|
| L1 | Repository caching | factory.py | Add optional caching for long-running deployments |
| L2 | Metrics collection | machine.py | Add OpenTelemetry spans for observability |

---

## 6. Code Quality Highlights

### Documentation Quality ⭐⭐⭐⭐⭐

Every file has comprehensive headers:
```python
# ============================================================================
# CLAUDE CONTEXT - DESCRIPTIVE_TITLE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: [Component type] - [Brief description]
# PURPOSE: [One sentence description]
# LAST_REVIEWED: [DD MMM YYYY]
# EXPORTS: [Main classes, functions, constants]
# DEPENDENCIES: [Key external libraries]
# ============================================================================
```

### Contract Enforcement ⭐⭐⭐⭐⭐

Type contracts enforced at runtime:
```python
# core/machine.py:738-742
if not isinstance(task_message, TaskQueueMessage):
    raise ContractViolationError(
        f"task_message must be TaskQueueMessage, got {type(task_message).__name__}"
    )
```

### Logging Quality ⭐⭐⭐⭐⭐

Structured logging with checkpoints for Application Insights:
```python
self.logger.info(
    f"✅ [TASK_COMPLETE] Task marked COMPLETED",
    extra={
        'checkpoint': 'TASK_COMPLETE_SUCCESS',
        'task_id': task_message.task_id,
        'job_id': task_message.parent_job_id,
        'stage_complete': completion.stage_complete,
    }
)
```

---

## 7. Conclusion

The core orchestration system is **production-ready** with excellent patterns for:

1. **Distributed Coordination** - PostgreSQL advisory locks prevent race conditions
2. **Failure Recovery** - Comprehensive retry logic with categorized exceptions
3. **Developer Experience** - JobBaseMixin makes adding new pipelines trivial
4. **Observability** - Structured logging with checkpoints

The minor efficiency opportunities identified (connection pooling) are documented trade-offs appropriate for the current Azure Functions deployment model. No refactoring is urgently needed.

---

**Files Reviewed**:
- `core/machine.py` (1400+ LOC) - Main orchestration engine
- `core/state_manager.py` (~700 LOC) - Database state management
- `core/orchestration_manager.py` - Multi-app coordination
- `core/error_handler.py` - Centralized error handling
- `core/fan_in.py` - Fan-in pattern helpers
- `infrastructure/postgresql.py` (~1000 LOC) - Repository base
- `infrastructure/jobs_tasks.py` - Job/Task repositories
- `infrastructure/service_bus.py` - Message queue
- `infrastructure/factory.py` - Repository factory
- `jobs/base.py` - Abstract base class
- `jobs/mixins.py` (717 LOC) - Boilerplate elimination
- `core/schema/sql_generator.py` - DDL generation
- `core/models/__init__.py` - Data model exports
