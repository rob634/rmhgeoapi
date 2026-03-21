# Scheduler & API-Driven Workflows Design Spec

**Created**: 20 MAR 2026
**Version**: v0.10.4.1 (DAG Foundation incremental)
**Status**: APPROVED (design)
**Authors**: Robert Harrison, Claude Prime

---

## Overview

Two new capabilities for the DAG-based workflow system:

1. **Scheduler** — a DAG Brain thread that submits workflow runs on cron schedules
2. **API-driven workflows** — workflows that fetch data from external APIs, save to Bronze, and append to Silver

These extend the existing DAG foundation (v0.10.4) without modifying any existing handler or workflow code. ACLED weekly sync is the reference implementation.

---

## Architectural Principles Applied

| Principle | How Applied |
|-----------|-------------|
| P1 (Explicit Failure) | Auth failure, API failure, empty response — all explicit errors, no silent accommodation |
| P2 (Deterministic Materialized Views) | Raw API responses saved to Bronze before Silver write. Rebuild path: Bronze snapshots -> Silver, even if API is down |
| P3 (Unidirectional Data Flow) | API -> Bronze -> Silver. No reverse writes |
| P5 (Paired Lifecycles) | Schedule deletion removes the schedule. Accumulated workflow_runs cleaned by existing DAG janitor/maintenance. No orphan risk |
| P8 (Database Is Coordination Layer) | Schedules stored in `app.schedules` table, polled by scheduler thread. No external scheduler service |
| P11 (Traceable State Changes) | Every API request logged. Every scheduled submission creates a standard `workflow_run` |

---

## Handler Return Contract (Canonical)

All handlers in this spec follow the canonical return structure:

```python
# Success
{"success": True, "result": {"key": "value", ...}}

# Failure
{"success": False, "error": "message", "error_type": "category"}
```

Result fields are **always nested under `result`**. The `receives` paths in YAML reflect this: `"node_name.result.field_name"`.

This is the standard going forward. The `hello_world` handlers' top-level fields are legacy and will be normalized when those handlers are next touched.

---

## Workstream 1: API Repository Foundation

### Base Class — `infrastructure/api_repository.py`

```python
class APIRepository:
    """
    Base class for external API access.

    Owns auth lifecycle, session management, retry, and request logging.
    Subclasses implement their specific auth flow (OAuth password grant,
    client_id/secret, API key, etc.).

    Same pattern as BlobRepository.for_zone() and PostgreSQLRepository —
    handlers never manage credentials directly.
    """

    # --- Abstract (subclass must implement) ---
    def authenticate(self) -> None: ...
    def refresh_token(self) -> None: ...
    def get_auth_headers(self) -> dict: ...

    # --- Provided by base ---
    def request(self, method, url, params=None, **kwargs) -> requests.Response:
        """
        Authenticated HTTP request with:
        - Automatic token refresh on 401
        - Retry with backoff on transient errors (429, 503, 502)
        - Request/response logging (P11)
        - Timeout enforcement
        """

    def get(self, url, params=None, **kwargs) -> requests.Response: ...
    def post(self, url, data=None, **kwargs) -> requests.Response: ...
```

**Key behaviors:**

- `requests.Session` for connection pooling and keepalive
- Retry: 3 attempts with exponential backoff for transient HTTP errors
- Auto-refresh: on 401 response, call `refresh_token()` and retry once
- Logging: every request logged with method, URL, status code, duration
- Credentials: read from config layer (`get_config()`), never from parameters

### ACLED Implementation — `infrastructure/acled_repository.py`

```python
class ACLEDRepository(APIRepository):
    """
    ACLED API access — OAuth 2.0 password grant.

    Handles:
    - OAuth token acquisition and refresh
    - Paginated data fetching
    - Deduplication against existing PostGIS table
    """

    BASE_URL = "https://acleddata.com"
    TOKEN_URL = f"{BASE_URL}/oauth/token"
    API_URL = f"{BASE_URL}/api/acled"

    def authenticate(self) -> None:
        """OAuth 2.0 password grant. Credentials from config."""

    def refresh_token(self) -> None:
        """Refresh using stored refresh_token, fall back to re-auth."""

    def get_auth_headers(self) -> dict:
        """Return Authorization: Bearer <token> header."""

    def fetch_page(self, page: int, limit: int = 5000) -> Optional[pd.DataFrame]:
        """Fetch single page of ACLED data."""

    def fetch_pages(self, max_pages: int = 0, limit: int = 5000) -> Generator[pd.DataFrame, None, None]:
        """
        Generator yielding DataFrames per page.

        Args:
            max_pages: Stop after N pages. 0 = unlimited (until empty page).
            limit: Records per page (API max: 5000).
        """

    def fetch_and_diff(
        self,
        max_pages: int,
        batch_size: int,
        target_schema: str,
        target_table: str,
    ) -> dict:
        """
        Fetch new events from API, diff against existing DB rows.

        Loads existing event_id_cnty set into memory for O(1) dedup.
        ~2.8M string IDs = ~200MB in memory — acceptable for weekly sync.

        NOTE: Coupling of API fetch + DB read in one method is a known
        trade-off. Splitting the DB query into its own DAG node would
        require passing millions of IDs through the receives mechanism.
        Revisit if the ID set grows beyond memory or if the receives
        mechanism gains streaming support.

        Returns:
            {
                "new_events": [...],       # list of dicts (new records)
                "raw_responses": [...],    # raw API responses for Bronze
                "metadata": {
                    "pages_processed": int,
                    "total_fetched": int,
                    "duplicates_skipped": int,
                    "new_count": int,
                    "db_max_timestamp": int,
                }
            }
        """
```

### Repository Hierarchy (Complete)

```
infrastructure/
    api_repository.py           # NEW — base APIRepository
    acled_repository.py         # NEW — ACLEDRepository(APIRepository)
    schedule_repository.py      # NEW — ScheduleRepository (S1.4 compliance)
    blob_repository.py          # existing — BlobRepository
    db_auth.py                  # existing — DB authentication
    db_connections.py           # existing — connection management
    db_utils.py                 # existing — type adapters
    postgresql_repository.py    # existing — base DB repo
    postgis_repository.py       # existing — spatial DB repo
    workflow_run_repository.py  # existing — DAG run/task repo
    release_repository.py       # existing — release state machine
    pgstac_repository.py        # existing — STAC catalog
```

### Handlers (Workstream 1)

One handler to validate the repository pattern. Handler file convention follows existing flat pattern in `services/`:

```python
# services/handler_acled_fetch_and_diff.py
def acled_fetch_and_diff(params, context=None):
    """
    Fetch new ACLED events and diff against existing Silver table.

    Params:
        max_pages (int): Pages to process. 0 = unlimited.
        batch_size (int): Records per API page.
        target_schema (str): PostGIS schema containing ACLED table.
        target_table (str): Table name to diff against.

    Returns:
        {"success": True, "result": {
            "new_events": [...],
            "raw_responses": [...],
            "metadata": {...}
        }}
    """
    repo = ACLEDRepository()
    result = repo.fetch_and_diff(
        max_pages=params['max_pages'],
        batch_size=params['batch_size'],
        target_schema=params['target_schema'],
        target_table=params['target_table'],
    )
    return {"success": True, "result": result}
```

Register in `services/__init__.py` -> `ALL_HANDLERS`.

---

## Workstream 2: Scheduler Infrastructure

### Database Schema

Schema changes go through the model/DDL system (Standard 7.3). The SQL below is the target DDL — implementation uses Pydantic models with `__sql_table_name__` and deploys via `action=ensure`.

#### Schedule Pydantic Model — `core/models/schedule.py`

```python
class Schedule(BaseModel):
    """
    Scheduled workflow execution.

    Maps to app.schedules. Created via admin API, polled by DAGScheduler.
    """
    __sql_table_name__ = "schedules"

    schedule_id: str                    # SHA256(workflow_name + sorted(parameters))
    workflow_name: str
    parameters: dict = {}
    description: Optional[str] = None
    cron_expression: str                # 5-field cron, evaluated in UTC
    status: ScheduleStatus = ScheduleStatus.ACTIVE
    last_run_at: Optional[datetime] = None
    last_run_id: Optional[str] = None
    max_concurrent: int = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
```

#### ScheduleStatus Enum — `core/models/workflow_enums.py`

```python
class ScheduleStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"
```

Added to `workflow_enums.py` alongside existing `WorkflowRunStatus` and `WorkflowTaskStatus`.

#### Target DDL

```sql
CREATE TYPE app.schedule_status AS ENUM ('active', 'paused', 'disabled');

CREATE TABLE app.schedules (
    schedule_id TEXT PRIMARY KEY,
    workflow_name TEXT NOT NULL,
    parameters JSONB NOT NULL DEFAULT '{}',
    description TEXT,
    cron_expression TEXT NOT NULL,
    status app.schedule_status NOT NULL DEFAULT 'active',
    last_run_at TIMESTAMPTZ,
    last_run_id TEXT,
    max_concurrent INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_schedules_active ON app.schedules(status)
    WHERE status = 'active';
```

#### Addition to `WorkflowRun` model

```python
# In core/models/workflow_run.py — add field:
schedule_id: Optional[str] = None
```

Column added to `app.workflow_runs` DDL. Nullable. NULL = platform-submitted or manual. Non-NULL = submitted by scheduler.

**Design decisions:**

- **`schedule_id`**: Deterministic — `SHA256(workflow_name + sorted(parameters))`. Prevents duplicate schedules for same workflow+params.
- **No `next_run_at` column**: Per DDIA doctrine, derived state is a liability. Due time computed from `croniter(cron_expression, last_run_at or created_at)` at query time. One fewer thing that can drift.
- **`max_concurrent`**: Default 1. If active run count >= max_concurrent, skip. No stacking.
- **All times UTC**: No timezone column. Cron expressions evaluated in UTC. Period.
- **All changes via model/DDL system**: Deployed via `action=ensure` (Standard 7.3). No standalone ALTER statements.

### Schedule Repository — `infrastructure/schedule_repository.py`

Per Standard 1.4, all database access through repository classes:

```python
class ScheduleRepository:
    """
    Database access for app.schedules.

    Used by admin endpoints (CRUD) and DAGScheduler thread (read + update).
    """

    def create(self, schedule: Schedule) -> Schedule: ...
    def get_by_id(self, schedule_id: str) -> Optional[Schedule]: ...
    def list_all(self, status: Optional[ScheduleStatus] = None) -> list[Schedule]: ...
    def list_active(self) -> list[Schedule]: ...
    def update(self, schedule_id: str, **fields) -> Schedule: ...
    def delete(self, schedule_id: str) -> bool: ...
    def record_run(self, schedule_id: str, run_id: str) -> None:
        """Atomically update last_run_at and last_run_id after firing."""
    def get_active_run_count(self, schedule_id: str) -> int:
        """Count workflow_runs for this schedule in pending/running status."""
```

### Scheduler Thread — `core/dag_scheduler.py`

```python
class DAGScheduler(threading.Thread):
    """
    Polls app.schedules for due items and submits workflow runs.

    Lifecycle: same pattern as DAGJanitor.
    - Poll interval: 30 seconds
    - Graceful shutdown via shutdown_event
    - Registered with DAGBrainSubsystem for health monitoring
    - Invalid cron expressions: log error, mark schedule DISABLED, continue

    On each tick:
      1. SELECT all active schedules (via ScheduleRepository)
      2. For each schedule, compute next_due via croniter
      3. If next_due <= NOW():
         a. Concurrency check — count active runs for this schedule
            If active_count >= max_concurrent: skip, log warning
         b. Validate workflow exists in registry
         c. Create workflow_run (same path as submit endpoint)
         d. Record run (last_run_at, last_run_id) via ScheduleRepository
      4. Sleep 30s
    """
```

**Concurrency guard (corrected):**

```
for each due schedule:
    active_count = repo.get_active_run_count(schedule_id)
    if active_count >= schedule.max_concurrent:
        log "skipping {schedule_id}, {active_count} runs still active"
        continue
    else:
        submit new run
```

**Atomicity:** Check + submit + record_run in one transaction per schedule. Prevents duplicate submissions on crash-restart.

**Graceful shutdown:** Respects `shutdown_event` from worker lifecycle. Finishes current tick, exits cleanly. Same pattern as janitor.

**Error resilience:** If `croniter` raises on a malformed cron expression, catch the error, log it, mark the schedule `DISABLED`, and continue processing remaining schedules. The scheduler thread must never crash.

### DAG Brain Integration

```
DAG Brain (Docker, APP_MODE=orchestrator)
    +-- Orchestrator poll loop (existing)
    +-- Janitor thread (existing)
    +-- Scheduler thread (NEW)
```

**Topology note:** Schedule admin endpoints live in the Function App (`triggers/dag/dag_bp.py`). The scheduler thread runs in Docker (`APP_MODE=orchestrator`). This is the same split as workflow submission (Function App) vs workflow execution (Docker). The database is the coordination layer (Principle 8) — both apps read/write `app.schedules` in the same PostgreSQL instance.

`DAGBrainSubsystem` health check extended:

```python
components["scheduler"] = self._check_scheduler()
metrics["scheduler_polls"] = self._scheduler._total_polls
metrics["schedules_fired"] = self._scheduler._total_fired
metrics["last_poll_at"] = self._scheduler._last_poll_at
```

### Admin API Endpoints

All under `/api/dag/schedules` in `triggers/dag/dag_bp.py`:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/dag/schedules` | Create schedule |
| `GET` | `/api/dag/schedules` | List all schedules |
| `GET` | `/api/dag/schedules/{schedule_id}` | Get schedule + recent runs |
| `PUT` | `/api/dag/schedules/{schedule_id}` | Update (cron, params, status) |
| `DELETE` | `/api/dag/schedules/{schedule_id}` | Remove schedule |
| `POST` | `/api/dag/schedules/{schedule_id}/trigger` | Fire immediately (bypass cron) |

**Create request:**

```json
{
    "workflow_name": "acled_sync",
    "description": "ACLED Africa weekly update",
    "parameters": {"max_pages": 20, "batch_size": 5000},
    "cron_expression": "0 6 * * 1"
}
```

**Behaviors:**

- Create validates workflow exists in registry — 400 if not found (Principle 1)
- Deterministic `schedule_id` — 409 Conflict if duplicate workflow+params
- Update allows changing cron, parameters, description, status
- Changing parameters = different `schedule_id` (it's a different schedule)
- Delete does not affect running workflow runs — they're independent
- Trigger submits immediately, does not advance the cron schedule
- GET returns computed `next_run_at` (via croniter) in the response — display only, not stored

### Dependencies

- `croniter` added to `requirements.txt`

---

## Workstream 3: ACLED Workflow

### Workflow YAML — `workflows/acled_sync.yaml`

```yaml
workflow: acled_sync
description: "ACLED conflict data sync — fetch new events and append to Silver"
version: 1

parameters:
  max_pages: {type: int, default: 20}
  batch_size: {type: int, default: 5000}
  target_schema: {type: str, default: "ops"}
  target_table: {type: str, default: "acled_new"}

nodes:
  fetch_and_diff:
    type: task
    handler: acled_fetch_and_diff
    params: [max_pages, batch_size, target_schema, target_table]

  save_to_bronze:
    type: task
    handler: acled_save_to_bronze
    depends_on: [fetch_and_diff]
    receives:
      raw_responses: "fetch_and_diff.result.raw_responses"
      fetch_metadata: "fetch_and_diff.result.metadata"

  append_to_silver:
    type: task
    handler: acled_append_to_silver
    depends_on: [save_to_bronze]
    params: [target_schema, target_table]
    receives:
      new_events: "fetch_and_diff.result.new_events"
      event_count: "fetch_and_diff.result.metadata.new_count"
```

**Three nodes, linear.** Auth handled internally by `ACLEDRepository`. No secrets in YAML.

### Remaining Handlers

```python
# services/handler_acled_save_to_bronze.py
def acled_save_to_bronze(params, context=None):
    """
    Save raw API responses to Bronze blob storage.

    Writes JSON blob: bronze/{container}/acled/sync_{timestamp}.json
    Contains raw API responses for audit trail and rebuild capability (P2).

    Returns:
        {"success": True, "result": {
            "bronze_path": str,
            "response_count": int,
            "bytes_written": int
        }}
    """

# services/handler_acled_append_to_silver.py
def acled_append_to_silver(params, context=None):
    """
    Bulk INSERT new ACLED events into existing PostGIS table.

    Uses PostgreSQL COPY protocol for performance.
    Append-only — no updates to existing rows.
    If corrections needed, full rebuild from scratch.

    Returns:
        {"success": True, "result": {
            "rows_inserted": int,
            "target_table": str
        }}
    """
```

Register all handlers in `services/__init__.py` -> `ALL_HANDLERS`.

### Schedule Setup (Post-Deployment)

```bash
curl -X POST https://.../api/dag/schedules \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_name": "acled_sync",
    "description": "ACLED weekly sync — 20 pages",
    "parameters": {"max_pages": 20, "batch_size": 5000},
    "cron_expression": "0 6 * * 1"
  }'
```

Manual full sync (unlimited pages):

```bash
curl -X POST https://.../api/dag/submit/acled_sync \
  -H "Content-Type: application/json" \
  -d '{"max_pages": 0}'
```

---

## Data Flow Diagram

```
                        SCHEDULER (DAG Brain thread)
                               |
                    polls app.schedules (30s)
                    computes due via croniter
                               |
                    +--------------------------+
                    |   app.workflow_runs       |  <-- same table as platform-submitted
                    |   schedule_id = X        |
                    +--------------------------+
                               |
              DAG Orchestrator picks up run
                               |
           +-------------------+-------------------+
           v                   v                   v
    fetch_and_diff      save_to_bronze      append_to_silver
    (ACLEDRepository)   (BlobRepository)    (PostgreSQLRepository)
           |                   |                   |
           v                   v                   v
      ACLED API           Bronze blob          ops.acled_new
    (OAuth, paginate,     (raw JSON,           (COPY protocol,
     diff vs existing)     audit trail)         append-only)
```

**Topology:**

```
Function App (gateway)                  Docker (DAG Brain)
+-- POST /api/dag/schedules (CRUD)     +-- Orchestrator poll loop
+-- POST /api/dag/submit/* (manual)    +-- Janitor thread
+-- GET /api/dag/runs/* (status)       +-- Scheduler thread (NEW)
         |                                      |
         +------------- app.schedules ----------+
         +------------- app.workflow_runs ------+
         +------------- app.workflow_tasks -----+
                         (PostgreSQL)
```

---

## Workstream Dependencies

```
Workstream 1: API Repository         Workstream 2: Scheduler
(independent)                        (independent)
  |                                    |
  |  api_repository.py                 |  Schedule model + enum
  |  acled_repository.py               |  schedule_repository.py
  |  handler_acled_fetch_and_diff.py   |  dag_scheduler.py
  |                                    |  dag_bp.py (endpoints)
  |                                    |  dag_brain.py (health)
  |                                    |  croniter dependency
  +----------------+-------------------+
                   |
                   v
          Workstream 3: ACLED Workflow
          (depends on W1 + W2)
            |
            |  workflows/acled_sync.yaml
            |  handler_acled_save_to_bronze.py
            |  handler_acled_append_to_silver.py
            |  E2E validation
```

W1 and W2 are independent and can be built in parallel. W3 depends on both.

---

## ScheduledDataset Entity (Design — Not Yet Built)

**Decision (21 MAR 2026):** Scheduled/API-sourced datasets need their own entity model, separate from the static ETL release lifecycle. These are fundamentally different asset types.

### Why a New Entity

| Aspect | Static Asset (Release) | ScheduledDataset |
|--------|----------------------|------------------|
| Source | File -> Bronze blob | API -> Bronze audit copy |
| Mutability | Immutable once created | Appended continuously |
| Versioning | Ordinal (ord1, ord2) | None — one table, forever growing |
| Approval | draft -> completed -> approved -> published | None — fully automated |
| Corrections | New version (ordN+1) | Truncate + full rebuild from API/Bronze |
| Unpublish | Drop table + remove STAC | Pause schedule + optionally drop |
| "Status" | Release status | Last sync time, row count, health |

### Key Decisions

- **Schema**: `geo` (same as static ETL tables — one PostGIS schema for all data)
- **Entity name**: `ScheduledDataset` (not "live" — that implies real-time)
- **Model**: Separate from release/asset model — no forced overlap with approval lifecycle
- **ACLED migration**: `ops.acled_new` moves to `geo` schema under ScheduledDataset management

### Minimum Model (TBD — needs brainstorm session)

```python
class ScheduledDataset(BaseModel):
    dataset_id: str                    # PK
    table_name: str                    # PostGIS table in geo schema
    schedule_id: Optional[str]         # FK to app.schedules (nullable for manually-managed)
    description: Optional[str]
    source_type: str                   # "api", "feed", etc.
    column_schema: dict                # expected columns and types (JSONB)
    row_count: int = 0                 # updated after each sync
    last_sync_at: Optional[datetime]
    last_sync_run_id: Optional[str]
    rebuild_strategy: str              # "append" | "truncate_reload"
    created_at: datetime
    updated_at: datetime
```

### Open Questions

- How does ScheduledDataset integrate with catalog/discovery layer?
- Do scheduled datasets appear in OGC Features API automatically?
- Does TiPG need refresh after appends?
- Does the first sync create the table, or is it pre-created from `column_schema`?
- What monitoring/alerting exists for sync failures (missed schedule, row count anomalies)?

### Two Rebuild Strategies — ACLED vs WDPA/KBA

| Strategy | Example | Workflow Shape | How It Works |
|----------|---------|---------------|-------------|
| `append` | ACLED | fetch_and_diff -> save_to_bronze -> append_to_silver | Diff against existing rows, INSERT only new ones. Table grows over time. |
| `truncate_reload` | WDPA, KBA | check_for_update -> download_to_bronze -> truncate_and_load_silver | Check if source has a newer version. If yes, TRUNCATE table + full reload. One version, always current. |

**ACLED** (append): ~2.8M rows, weekly sync adds ~100-5,000 new events. Corrections = full rebuild from API/Bronze.

**WDPA** (truncate_reload): ~295K protected areas, monthly bulk GeoPackage from IBAT API. Always the complete current dataset. If someone wants historical WDPA, they submit the old file through static ETL and get a versioned release with ordinal naming.

**KBA** (truncate_reload): ~50-80K Key Biodiversity Areas, biannual from IBAT API. Same pattern as WDPA.

Both strategies are `ScheduledDataset` entities — the `rebuild_strategy` field drives which handler the workflow uses at the Silver write node.

### Existing IBAT/WDPA Code (Epoch 4 — Port to DAG)

An Epoch 4 `WDPAHandler` exists at `services/curated/wdpa_handler.py` with a `curated_update` Python job class. This is frozen under Standard 5.4 (Epoch 4 freeze). The port to DAG follows the same pattern as ACLED:

1. **`IBATRepository(APIRepository)`** — inherits from the base class, handles IBAT v2 auth (`auth_key` + `auth_token`), bulk download endpoint
2. **`wdpa_sync.yaml`** / **`kba_sync.yaml`** — 3-node DAG workflows (check_for_update -> download_to_bronze -> truncate_and_load_silver)
3. **`ScheduledDataset`** entity tracking each PostGIS table
4. **`app.schedules`** row with monthly/biannual cron

The IBAT API reference is at `docs/pipelines/IBAT.md`. Catalog specs at `geopipeline_local/catalog/specs/ibat_wdpa.yaml` and `ibat_kba.yaml`.

### Workstream 4: ScheduledDataset Entity (DONE — 21 MAR 2026)

`ScheduledDataset` model and repository are built:
- `core/models/scheduled_dataset.py` — Pydantic model with DDL hints
- `infrastructure/scheduled_dataset_repository.py` — CRUD + `record_sync()` + `get_by_table()`

### Workstream 5: ScheduledDataset Integration (Future)

Wire ScheduledDataset into the workflow system:
1. ACLED handlers reference `dataset_id` instead of raw `target_schema`/`target_table`
2. `append_to_silver` handler calls `repo.record_sync()` after successful COPY
3. `truncate_and_load_silver` handler (new) — for WDPA/KBA `truncate_reload` strategy
4. Admin endpoint to register a ScheduledDataset and link to a schedule
5. TiPG refresh after sync (if dataset is vector and discoverable via OGC Features)

---

## Not In Scope (This Spec)

- Key Vault integration (env vars for credentials)
- Vantor/Maxar or other API sources (pattern established, implementation later)
- Schedule UI (admin API only)
- Timezone support (UTC only)
- `next_run_at` stored column (computed at query time)
- Splitting fetch_and_diff DB read into separate node (revisit if ID set outgrows memory)
- ScheduledDataset implementation (design above, build in future session)

---

## ACLED Reference

Existing pipeline documentation and code: `docs/pipelines/ACLED.md`

Key facts from existing implementation:
- OAuth 2.0 password grant (`client_id: "acled"`)
- API max 5000 records per page
- `timestamp` field = when record added to ACLED DB (not event date) — used for incremental sync
- `event_id_cnty` = primary key for deduplication
- PostgreSQL COPY protocol for bulk insert
- ~2.8M records, ~2 GB in database
- `inter1`, `inter2`, `interaction` changed from INTEGER to VARCHAR (Dec 2025)
- Table: `ops.acled_new` with 31 columns
