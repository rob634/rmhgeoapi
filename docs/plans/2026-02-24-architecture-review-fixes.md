# Architecture Review Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Resolve all 71 findings from the 24 FEB 2026 Architecture Review (73 total minus 2 excluded dev-grade security items: C8.6 CSP, C8.7 CSRF).

**Architecture:** Fix-in-place across 10 phases, ordered by risk. P1 critical items first with tests, then P2/P3 items grouped by subsystem. Large refactors (base.py split, process_task_message decomposition) are in later phases.

**Tech Stack:** Python 3.12, psycopg3 (`psycopg.sql`), Pydantic V2, Azure Functions, FastAPI, DuckDB

**Excluded (dev-grade, per CLAUDE.md policy):** C8.6 (CSP frame-ancestors), C8.7 (CSRF tokens)

**Reference:** `docs_claude/ARCHITECTURE_REVIEW_24FEB2026.md`

---

## Phase 1: Critical Security Fixes

### Task 1.1: Fix SQL Injection in batch_update_status (C3.1)

**Files:**
- Modify: `infrastructure/jobs_tasks.py:1050-1067`
- Test: `tests/test_sql_injection_fixes.py` (create)

**Step 1: Add psycopg.sql import if missing**

Check top of `infrastructure/jobs_tasks.py` for `from psycopg import sql`. Add if absent.

**Step 2: Rewrite batch_update_status to use sql.SQL composition**

Replace lines 1050-1067:
```python
# OLD (vulnerable):
if additional_updates:
    for key, value in additional_updates.items():
        set_clauses.append(f"{key} = %s")
        params.append(value)
query = f"""
    UPDATE {self.schema_name}.tasks
    SET {', '.join(set_clauses)}
    WHERE task_id = ANY(%s)
"""
cursor.execute(query, params)
```

With:
```python
# NEW (safe):
if additional_updates:
    for key, value in additional_updates.items():
        set_clauses.append(
            sql.SQL("{} = %s").format(sql.Identifier(key))
        )
        params.append(value)

params.append(tuple(task_ids))

query = sql.SQL("UPDATE {}.{} SET {} WHERE task_id = ANY(%s)").format(
    sql.Identifier(self.schema_name),
    sql.Identifier('tasks'),
    sql.SQL(', ').join(set_clauses)
)
cursor.execute(query, params)
```

Note: `set_clauses` initialization (line 1050) also needs updating from `[f"status = %s", f"updated_at = %s"]` to use `sql.SQL`:
```python
set_clauses = [
    sql.SQL("{} = %s").format(sql.Identifier('status')),
    sql.SQL("{} = %s").format(sql.Identifier('updated_at'))
]
```

**Step 3: Commit**
```
fix(security): Use sql.Identifier for column names in batch_update_status [C3.1]
```

---

### Task 1.2: Fix SQL Injection in batch_create_tasks (C3.2)

**Files:**
- Modify: `infrastructure/jobs_tasks.py:991-1001`

**Step 1: Rewrite INSERT to use sql.SQL composition**

Replace the f-string INSERT:
```python
# OLD:
cursor.executemany(
    f"""
    INSERT INTO {self.schema_name}.tasks (...)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """,
    data
)
```

With:
```python
# NEW:
query = sql.SQL("""
    INSERT INTO {}.{} (
        task_id, parent_job_id, task_type, status,
        stage_number, parameters, batch_id, retry_count,
        metadata, created_at, updated_at
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
""").format(
    sql.Identifier(self.schema_name),
    sql.Identifier('tasks')
)
cursor.executemany(query, data)
```

**Step 2: Commit**
```
fix(security): Use sql.Identifier for schema in batch_create_tasks [C3.2]
```

---

### Task 1.3: Fix SQL Injection in SET search_path (C3.3)

**Files:**
- Modify: `infrastructure/connection_pool.py:242-259`

**Step 1: Add psycopg.sql import**

Add `from psycopg import sql` at top of file if not present.

**Step 2: Replace f-string SET search_path**

Replace line 259:
```python
# OLD:
search_path = ', '.join(schemas)
conn.execute(f"SET search_path TO {search_path}")
```

With:
```python
# NEW:
schema_identifiers = [sql.Identifier(s) for s in schemas]
conn.execute(
    sql.SQL("SET search_path TO {}").format(
        sql.SQL(', ').join(schema_identifiers)
    )
)
```

**Step 3: Commit**
```
fix(security): Use sql.Identifier for SET search_path [C3.3]
```

---

### Task 1.4: Fix XSS in Web Interface Error Page (C8.1)

**Files:**
- Modify: `web_interfaces/__init__.py:228-268`

**Step 1: Add html import**

Add `import html` to the imports at top of file.

**Step 2: Escape user-controlled values in error HTML**

In the error_html f-string (around lines 261-263), escape both values:
```python
# OLD:
<p><strong>Interface:</strong> {interface_name}</p>
...
<pre>{str(e)}</pre>
```

```python
# NEW:
<p><strong>Interface:</strong> {html.escape(str(interface_name))}</p>
...
<pre>{html.escape(str(e))}</pre>
```

Also escape in the `<title>` tag:
```python
<title>Error - {html.escape(str(interface_name))}</title>
```

**Step 3: Commit**
```
fix(security): HTML-escape interface_name and exception in error page [C8.1]
```

---

### Task 1.5: Fix Credential Exposure in Logger (C7.1)

**Files:**
- Modify: `util_logger.py:820-858`

**Step 1: Use keyword arguments for psycopg.connect instead of connection string**

Replace the connection string approach with keyword arguments so credentials don't appear in exception messages:

```python
# OLD:
conn_str = (
    f"host={config.database.host} "
    f"password={token.token} "
    ...
)
conn = psycopg.connect(conn_str, ...)

# NEW (keyword args - credentials not in exception messages):
conn = psycopg.connect(
    host=config.database.host,
    port=config.database.port,
    dbname=config.database.database,
    user=config.database.managed_identity_admin_name if config.database.use_managed_identity else config.database.user,
    password=token.token if config.database.use_managed_identity else config.database.password,
    sslmode='require',
    connect_timeout=timeout_seconds,
    autocommit=True,
    options=f"-c statement_timeout={timeout_seconds * 1000}"
)
```

**Step 2: Sanitize the exception message in the except block**

Replace line 858:
```python
# OLD:
_logger.warning(f"Database stats connection failed: {e}")

# NEW:
_logger.warning(f"Database stats connection failed: {type(e).__name__}")
```

**Step 3: Commit**
```
fix(security): Use keyword args for DB connect, sanitize error messages [C7.1]
```

---

### Task 1.6: Move AppInsights Query to Admin Guard (C5.1)

**Files:**
- Modify: `triggers/probes.py:470-554`

**Step 1: Add app mode guard to the endpoint**

The endpoint already exists at anonymous auth level. Since we're skipping full auth (dev-grade), add an app mode guard so it only runs on the orchestrator (not gateway/worker) and add basic query validation:

```python
@bp.route(route="appinsights/query", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def appinsights_query(req: func.HttpRequest) -> func.HttpResponse:
    # Guard: Only available in standalone/orchestrator mode
    from config import get_app_mode_config
    mode_config = get_app_mode_config()
    if mode_config.app_mode.value not in ('standalone', 'orchestrator'):
        return func.HttpResponse(
            json.dumps({"status": "error", "error": "Endpoint not available in this app mode"}),
            status_code=403,
            mimetype="application/json"
        )

    # ... existing logic ...

    # Add query length limit
    query = body.get("query")
    if not query:
        # ... existing validation ...
    if len(query) > 2000:
        return func.HttpResponse(
            json.dumps({"status": "error", "error": "Query too long (max 2000 chars)"}),
            status_code=400,
            mimetype="application/json"
        )
```

**Step 2: Commit**
```
fix(security): Add mode guard and query length limit to appinsights endpoint [C5.1]
```

---

### Task 1.7: Write P1 Security Tests

**Files:**
- Create: `tests/test_sql_injection_fixes.py`

**Step 1: Write tests for SQL composition**

```python
"""Tests for P1 security fixes from Architecture Review 24 FEB 2026."""
import pytest
from psycopg import sql


class TestSQLComposition:
    """Verify SQL injection fixes use sql.Identifier, not f-strings."""

    def test_sql_identifier_rejects_injection_in_column_name(self):
        """C3.1: Column names must use sql.Identifier."""
        malicious_key = "status = 'admin'--"
        # sql.Identifier wraps in quotes, neutralizing injection
        ident = sql.Identifier(malicious_key)
        rendered = sql.SQL("{} = %s").format(ident).as_string(None)
        assert '"' in rendered  # Quoted identifier
        assert "--" in rendered  # Still present but inside quotes (safe)

    def test_sql_identifier_rejects_injection_in_schema_name(self):
        """C3.2/C3.3: Schema names must use sql.Identifier."""
        malicious_schema = "app; DROP TABLE jobs;--"
        ident = sql.Identifier(malicious_schema)
        rendered = sql.SQL("SELECT * FROM {}.tasks").format(ident).as_string(None)
        assert '"' in rendered  # Quoted identifier


class TestXSSPrevention:
    """Verify XSS fixes use html.escape."""

    def test_html_escape_strips_script_tags(self):
        """C8.1: Error messages must be HTML-escaped."""
        import html
        malicious = '<script>alert("xss")</script>'
        escaped = html.escape(malicious)
        assert '<script>' not in escaped
        assert '&lt;script&gt;' in escaped


class TestCredentialSanitization:
    """Verify credential exposure fixes."""

    def test_exception_message_excludes_password(self):
        """C7.1: DB connection errors must not leak credentials."""
        # Simulate a connection failure with keyword args
        import psycopg
        try:
            psycopg.connect(
                host="nonexistent-host-12345.example.com",
                password="SECRET_TOKEN_VALUE",
                connect_timeout=1
            )
        except Exception as e:
            error_msg = str(e)
            # psycopg with keyword args should NOT include the password in the error
            assert "SECRET_TOKEN_VALUE" not in error_msg
```

**Step 2: Run tests**

```bash
conda activate azgeo && python -m pytest tests/test_sql_injection_fixes.py -v
```

**Step 3: Commit**
```
test: Add P1 security fix tests (SQL injection, XSS, credential exposure)
```

---

## Phase 2: Critical Bug Fixes

### Task 2.1: Add StageResultContract.from_task_results() (C1.1)

**Files:**
- Modify: `core/models/results.py:55-82`

**Step 1: Add the missing classmethod**

Add after line 82 (after `validate_status`):
```python
@classmethod
def from_task_results(
    cls,
    stage_number: int,
    task_results: List['TaskResult'],
    metadata: Optional[Dict[str, Any]] = None
) -> 'StageResultContract':
    """
    Aggregate individual task results into a stage result contract.

    Args:
        stage_number: The stage number
        task_results: List of TaskResult objects from the stage
        metadata: Optional additional metadata

    Returns:
        StageResultContract with aggregated results
    """
    from core.logic.calculations import get_error_summary

    successful = sum(1 for r in task_results if r.success)
    failed = len(task_results) - successful

    if failed == 0:
        status = 'completed'
    elif successful == 0:
        status = 'failed'
    else:
        status = 'completed_with_errors'

    return cls(
        stage=stage_number,
        status=status,
        task_count=len(task_results),
        successful_count=successful,
        failed_count=failed,
        task_results=[r.model_dump() for r in task_results],
        aggregated_data=metadata,
        error_summary=get_error_summary(task_results),
        completion_time=datetime.now(timezone.utc)
    )
```

Also add `timezone` to the datetime import at line 22:
```python
from datetime import datetime, timezone
```

**Step 2: Commit**
```
fix: Add StageResultContract.from_task_results() classmethod [C1.1]
```

---

### Task 2.2: Fix error_message → error_details (C1.2)

**Files:**
- Modify: `core/logic/calculations.py:183-186`

**Step 1: Replace attribute name**

```python
# OLD:
for result in task_results:
    if result.error_message and result.error_message not in seen:
        errors.append(result.error_message)
        seen.add(result.error_message)

# NEW:
for result in task_results:
    if result.error_details and result.error_details not in seen:
        errors.append(result.error_details)
        seen.add(result.error_details)
```

**Step 2: Commit**
```
fix: Use error_details (not error_message) matching TaskResult model [C1.2]
```

---

### Task 2.3: Reconcile State Transition Rules (C1.3)

**Files:**
- Modify: `core/logic/transitions.py:48-58`

**Step 1: Add PROCESSING → QUEUED transition to transitions.py**

The `JobRecord.can_transition_to()` in `core/models/job.py:149` correctly allows PROCESSING → QUEUED for stage advancement re-queuing. The `transitions.py` module is missing this. Add it:

```python
# OLD:
JobStatus.PROCESSING: [
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.COMPLETED_WITH_ERRORS
],

# NEW:
JobStatus.PROCESSING: [
    JobStatus.QUEUED,  # Stage advancement re-queuing
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.COMPLETED_WITH_ERRORS
],
```

Also add terminal → any recovery transitions to match `job.py:164`:
```python
# OLD:
JobStatus.FAILED: [],  # Terminal state
JobStatus.COMPLETED: [],  # Terminal state
JobStatus.COMPLETED_WITH_ERRORS: []  # Terminal state

# NEW:
# Terminal states allow recovery transitions (error recovery/retry)
JobStatus.FAILED: [JobStatus.QUEUED],
JobStatus.COMPLETED: [JobStatus.QUEUED],
JobStatus.COMPLETED_WITH_ERRORS: [JobStatus.QUEUED]
```

Add a comment linking the two implementations:
```python
# NOTE: Must stay in sync with JobRecord.can_transition_to() in core/models/job.py
```

**Step 2: Commit**
```
fix: Reconcile transitions.py with JobRecord.can_transition_to() [C1.3]
```

---

### Task 2.4: Fix _resolve_release() Draft-for-Revoke Bug (C6.1)

**Files:**
- Modify: `triggers/trigger_approvals.py:47-127`

**Step 1: Add operation parameter to _resolve_release()**

```python
def _resolve_release(
    release_id: str = None,
    asset_id: str = None,
    job_id: str = None,
    request_id: str = None,
    dataset_id: str = None,
    resource_id: str = None,
    operation: str = "approve"  # NEW: "approve", "reject", or "revoke"
):
```

**Step 2: Update asset_id resolution logic (lines 116-127)**

```python
# OLD:
if asset_id:
    release = release_repo.get_draft(asset_id)
    if not release:
        release = release_repo.get_latest(asset_id)

# NEW:
if asset_id:
    if operation == "revoke":
        # Revoke targets approved releases, not drafts
        release = release_repo.get_latest(asset_id)
    else:
        # Approve/reject targets drafts first, then falls back to latest
        release = release_repo.get_draft(asset_id)
        if not release:
            release = release_repo.get_latest(asset_id)
```

Apply same fix for the dataset_id+resource_id path (lines 130-136):
```python
if asset:
    if operation == "revoke":
        release = release_repo.get_latest(asset.asset_id)
    else:
        release = release_repo.get_draft(asset.asset_id)
        if not release:
            release = release_repo.get_latest(asset.asset_id)
```

**Step 3: Update callers to pass operation parameter**

In `platform_revoke()` (line 588):
```python
release, error = _resolve_release(
    release_id=release_id_param,
    asset_id=asset_id_param,
    job_id=job_id,
    request_id=request_id,
    dataset_id=dataset_id,
    resource_id=resource_id,
    operation="revoke"  # NEW
)
```

Similarly update `platform_approve()` and `platform_reject()` with `operation="approve"` and `operation="reject"`.

**Step 4: Commit**
```
fix: _resolve_release() uses operation param for correct draft/approved resolution [C6.1]
```

---

### Task 2.5: Add job_type to SHA256 Hash (C4.1)

**Files:**
- Modify: `jobs/validate_raster_job.py:197-206`
- Modify: `jobs/stac_catalog_container.py:154-163`

**Step 1: Fix both generate_job_id methods**

In both files, change:
```python
# OLD:
param_str = json.dumps(params, sort_keys=True)
job_hash = hashlib.sha256(param_str.encode()).hexdigest()

# NEW:
hash_input = {"job_type": "validate_raster_job", **params}  # Include job_type
param_str = json.dumps(hash_input, sort_keys=True)
job_hash = hashlib.sha256(param_str.encode()).hexdigest()
```

For `stac_catalog_container.py`, use `"stac_catalog_container"` as the job_type value.

**Step 2: Commit**
```
fix: Include job_type in SHA256 hash for validate_raster and stac_catalog jobs [C4.1]
```

---

### Task 2.6: Fix Jobs Bypassing Mixin (C4.2)

**Files:**
- Modify: `jobs/validate_raster_job.py`
- Modify: `jobs/stac_catalog_container.py`

**Step 1: Verify both jobs use JobBaseMixin**

Check if both classes inherit from `JobBaseMixin`. If not, add it:
```python
# Ensure: class ValidateRasterJob(JobBaseMixin, JobBase):
# Ensure: class StacCatalogContainerWorkflow(JobBaseMixin, JobBase):
```

The mixin provides `etl_version` tracking and `system_params` validation. If the jobs have custom `__init__` or `generate_job_id` that bypass mixin logic, ensure the mixin's `system_params` are included.

**Step 2: Commit**
```
fix: Ensure validate_raster and stac_catalog jobs use JobBaseMixin [C4.2]
```

---

### Task 2.7: Fix Raw SQL in unpublish_handlers.py (C4.3)

**Files:**
- Modify: `services/unpublish_handlers.py:97-106, 234-266`

**Step 1: Replace raw SQL with repository method calls**

The raw SQL queries `geo.table_catalog` and `app.vector_etl_tracking`. These should go through proper repository methods. If no repository method exists, create a helper method on the relevant repository class, or at minimum use `sql.SQL` composition instead of raw strings.

For lines 234-266 (geo.table_catalog query):
```python
# Use sql.SQL composition at minimum:
from psycopg import sql as psql

cur.execute(
    psql.SQL("""
        SELECT table_name, schema_name, stac_item_id, stac_collection_id,
               feature_count, geometry_type, created_at, updated_at,
               bbox_minx, bbox_miny, bbox_maxx, bbox_maxy
        FROM {}.{}
        WHERE table_name = %s
    """).format(
        psql.Identifier('geo'),
        psql.Identifier('table_catalog')
    ),
    (table_name,)
)
```

Apply same pattern to `app.vector_etl_tracking` query.

**Step 2: Commit**
```
fix: Use sql.SQL composition in unpublish_handlers.py [C4.3]
```

---

### Task 2.8: Fix Error Context Lost in App Insights (C7.2)

**Files:**
- Modify: `core/error_handler.py:123-126` and `core/error_handler.py:219`

**Step 1: Fix both logging calls**

Location 1 (line 125):
```python
# OLD:
extra=error_context

# NEW:
extra={'custom_dimensions': error_context}
```

Location 2 (line 219):
```python
# OLD:
extra=error_context

# NEW:
extra={'custom_dimensions': error_context}
```

**Step 2: Commit**
```
fix: Use extra={'custom_dimensions': ...} for App Insights error context [C7.2]
```

---

### Task 2.9: Write P1 Bug Fix Tests

**Files:**
- Create: `tests/test_p1_bugfixes.py`

```python
"""Tests for P1 bug fixes from Architecture Review 24 FEB 2026."""
import pytest
from datetime import datetime, timezone


class TestStageResultContract:
    """C1.1: StageResultContract.from_task_results() must exist."""

    def test_from_task_results_exists(self):
        from core.models.results import StageResultContract
        assert hasattr(StageResultContract, 'from_task_results')
        assert callable(StageResultContract.from_task_results)

    def test_from_task_results_aggregates_correctly(self):
        from core.models.results import StageResultContract, TaskResult
        from core.models.enums import TaskStatus

        results = [
            TaskResult(
                task_id="t1", task_type="test", status=TaskStatus.COMPLETED,
                timestamp=datetime.now(timezone.utc)
            ),
            TaskResult(
                task_id="t2", task_type="test", status=TaskStatus.FAILED,
                error_details="Something broke",
                timestamp=datetime.now(timezone.utc)
            ),
        ]
        stage = StageResultContract.from_task_results(1, results)
        assert stage.task_count == 2
        assert stage.successful_count == 1
        assert stage.failed_count == 1
        assert stage.status == 'completed_with_errors'
        assert stage.error_summary == ["Something broke"]


class TestErrorDetailsAttribute:
    """C1.2: calculations.py must use error_details, not error_message."""

    def test_get_error_summary_uses_error_details(self):
        from core.logic.calculations import get_error_summary
        from core.models.results import TaskResult
        from core.models.enums import TaskStatus

        results = [
            TaskResult(
                task_id="t1", task_type="test", status=TaskStatus.FAILED,
                error_details="Error A",
                timestamp=datetime.now(timezone.utc)
            ),
        ]
        errors = get_error_summary(results)
        assert errors == ["Error A"]


class TestStateTransitions:
    """C1.3: transitions.py must agree with JobRecord.can_transition_to()."""

    def test_processing_to_queued_allowed(self):
        from core.logic.transitions import can_job_transition
        from core.models.enums import JobStatus
        assert can_job_transition(JobStatus.PROCESSING, JobStatus.QUEUED)

    def test_failed_to_queued_recovery_allowed(self):
        from core.logic.transitions import can_job_transition
        from core.models.enums import JobStatus
        assert can_job_transition(JobStatus.FAILED, JobStatus.QUEUED)
```

**Run:**
```bash
conda activate azgeo && python -m pytest tests/test_p1_bugfixes.py -v
```

**Commit:**
```
test: Add P1 bug fix tests (StageResultContract, error_details, transitions)
```

---

## Phase 3: Configuration Alignment

### Task 3.1: Fix Default Value Mismatches (C2.1, C2.2, C2.3)

**Files:**
- Modify: `config/env_validation.py:427` (COG_COMPRESSION default)
- Modify: `config/env_validation.py:491-497` (DEFAULT_ACCESS_LEVEL pattern + default)
- Modify: `config/env_validation.py:351` (DOCKER_WORKER_ENABLED default)
- Modify: `config/defaults.py:389` (DOCKER_WORKER_ENABLED)

**Step 1: Align COG_COMPRESSION (C2.1)**

`defaults.py` says `"deflate"`. Change `env_validation.py` to match:
```python
# env_validation.py line 427:
default_value="DEFLATE",  # Was "LZW", aligned with defaults.py
```

**Step 2: Align DOCKER_WORKER_ENABLED (C2.2)**

Runtime uses `False` (from `app_mode_config.py`). Align `defaults.py`:
```python
# defaults.py:
class AppModeDefaults:
    DOCKER_WORKER_ENABLED = False  # Was True, aligned with app_mode_config.py
```

**Step 3: Align DEFAULT_ACCESS_LEVEL (C2.3)**

`defaults.py` says `"OUO"` but validation rejects it. Add `"OUO"` to the validation regex and align default:
```python
# env_validation.py line 490-497:
"PLATFORM_DEFAULT_ACCESS_LEVEL": EnvVarRule(
    pattern=re.compile(r"^(public|internal|restricted|confidential|OUO)$", re.IGNORECASE),
    pattern_description="Default data classification (public, internal, restricted, confidential, OUO)",
    required=False,
    fix_suggestion="Set default access level for datasets",
    example="OUO",
    default_value="OUO",  # Aligned with defaults.py
),
```

**Step 4: Commit**
```
fix: Align COG_COMPRESSION, DOCKER_WORKER_ENABLED, DEFAULT_ACCESS_LEVEL defaults [C2.1-C2.3]
```

---

### Task 3.2: Fix AnalyticsConfig Ignoring AnalyticsDefaults (C2.4)

**Files:**
- Modify: `config/analytics_config.py:141-179`
- Modify: `config/defaults.py` (verify AnalyticsDefaults exists)

**Step 1: Check if AnalyticsDefaults class exists in defaults.py**

If it exists, replace hardcoded values in `AnalyticsConfig.from_environment()` with references:
```python
return cls(
    connection_type=DuckDBConnectionType(
        os.environ.get("DUCKDB_CONNECTION_TYPE", AnalyticsDefaults.CONNECTION_TYPE)
    ),
    # ... etc for all fields
)
```

If `AnalyticsDefaults` doesn't exist, create it in `defaults.py`:
```python
class AnalyticsDefaults:
    CONNECTION_TYPE = "memory"
    ENABLE_SPATIAL = True
    ENABLE_AZURE = True
    ENABLE_HTTPFS = True
    MEMORY_LIMIT = "4GB"
    THREADS = 4
```

**Step 2: Commit**
```
fix: AnalyticsConfig.from_environment() uses AnalyticsDefaults [C2.4]
```

---

### Task 3.3: Add MetricsConfig to AppConfig.from_environment() (C2.5)

**Files:**
- Modify: `config/app_config.py`

**Step 1: Verify MetricsConfig is composed in from_environment()**

Check `AppConfig.from_environment()`. If `metrics=MetricsConfig.from_environment()` is missing, add it alongside the other domain configs.

**Step 2: Commit**
```
fix: Include MetricsConfig in AppConfig.from_environment() [C2.5]
```

---

### Task 3.4: Standardize Boolean Parsing (C2.6)

**Files:**
- Modify: `config/analytics_config.py` (local `parse_bool`)
- Reference: Identify the canonical `parse_bool` and use it everywhere

**Step 1: Add canonical parse_bool to defaults.py if not present**

```python
# In defaults.py or a config utility:
def parse_bool(value: str) -> bool:
    """Canonical boolean parser for environment variables."""
    return value.lower() in ("true", "1", "yes")
```

**Step 2: Replace all inline boolean parsing in config files with the canonical version**

- `analytics_config.py`: Remove local `parse_bool`, import from defaults
- Any other config files with inline `.lower() == "true"` patterns

**Step 3: Commit**
```
fix: Standardize boolean parsing across config files [C2.6]
```

---

### Task 3.5: Remove Legacy Properties (C2.8)

**Files:**
- Modify: `config/app_config.py`

**Step 1: Identify and remove legacy @property aliases**

Search for `# Legacy` or `@property` in `app_config.py`. Per the "no backward compatibility" policy, remove properties that are just aliases for the new composition pattern (e.g., `config.postgis_host` → `config.database.host`).

Grep for callers first to ensure nothing still uses the legacy properties. Fix any callers to use the new pattern.

**Step 2: Commit**
```
cleanup: Remove 30+ legacy property aliases from AppConfig [C2.8]
```

---

### Task 3.6: Singleton Thread Safety (C2.9)

**Files:**
- Modify: `config/__init__.py:109-127`

**Step 1: Add threading.Lock to get_config()**

```python
import threading

_config_instance: Optional[AppConfig] = None
_config_lock = threading.Lock()

def get_config() -> AppConfig:
    global _config_instance
    if _config_instance is None:
        with _config_lock:
            if _config_instance is None:  # Double-checked locking
                _config_instance = AppConfig.from_environment()
    return _config_instance
```

**Step 2: Commit**
```
fix: Thread-safe config singleton with double-checked locking [C2.9]
```

---

## Phase 4: Observability Improvements

### Task 4.1: Thread-Safe _checkpoint_times (C7.3)

**Files:**
- Modify: `util_logger.py:176`

**Step 1: Add a threading.Lock for _checkpoint_times**

```python
_checkpoint_times: Dict[str, float] = {}
_checkpoint_lock = threading.Lock()
```

**Step 2: Wrap all accesses to _checkpoint_times in the lock**

In `log_memory_checkpoint()`, `clear_checkpoint_context()`, and `_cleanup_stale_checkpoints()`, wrap dict access with `with _checkpoint_lock:`.

**Step 3: Commit**
```
fix: Thread-safe _checkpoint_times with threading.Lock [C7.3]
```

---

### Task 4.2: Remove Legacy ErrorResponse Fields (C7.5)

**Files:**
- Modify: `core/errors.py:331-332, 667`

**Step 1: Remove legacy fields from ErrorResponse**

```python
# Remove these two fields:
error: Optional[str] = Field(None, description="Legacy: same as error_code")
error_type: Optional[str] = Field(None, description="Legacy: exception class name")
```

**Step 2: Remove legacy defaults from factory function (line 667)**

Remove `error_type=error_type or "ValidationError"` and any other legacy field population.

**Step 3: Search for callers that reference .error or .error_type and update**

**Step 4: Commit**
```
cleanup: Remove legacy error/error_type fields from ErrorResponse [C7.5]
```

---

### Task 4.3: Docker Health Use Connection Pool (C7.6)

**Files:**
- Modify: `docker_health/shared.py:168-211`

**Step 1: Replace fresh connection with connection pool**

Replace the raw `psycopg.connect()` call with the existing `ConnectionPoolManager`:
```python
from infrastructure.connection_pool import ConnectionPoolManager

pool = ConnectionPoolManager.get_pool()
with pool.connection() as conn:
    conn.execute("SELECT 1")
    # ... health check logic
```

**Step 2: Commit**
```
fix: Docker health uses ConnectionPoolManager instead of raw connections [C7.6]
```

---

### Task 4.4: Repository Logger Respects LOG_LEVEL (C7.7)

**Files:**
- Modify: `util_logger.py:1668-1671`

**Step 1: Change repository default to follow LOG_LEVEL**

```python
# OLD:
ComponentType.REPOSITORY: ComponentConfig(
    component_type=ComponentType.REPOSITORY,
    log_level=LogLevel.DEBUG,  # Always debug
    enable_debug_context=True
),

# NEW:
ComponentType.REPOSITORY: ComponentConfig(
    component_type=ComponentType.REPOSITORY,
    log_level=None,  # Inherits from LOG_LEVEL env var
    enable_debug_context=True
),
```

Ensure the `None` log_level falls through to the global LOG_LEVEL. If the LoggerFactory doesn't support `None`, use the pattern used by other component types.

**Step 2: Commit**
```
fix: Repository logger respects LOG_LEVEL instead of hardcoded DEBUG [C7.7]
```

---

### Task 4.5: MetricsBlobLogger Log Flush Errors (C7.8)

**Files:**
- Modify: `infrastructure/metrics_blob_logger.py:304-308`

**Step 1: Add warning log on flush failure**

```python
except Exception as e:
    self.flush_errors += 1
    logging.getLogger("metrics_blob_logger").warning(
        f"Metrics blob flush failed ({self.flush_errors} total): {type(e).__name__}"
    )
    # Re-add records to buffer on failure (best effort)
    for record in records[:self.buffer_size]:
        self.buffer.appendleft(record)
```

**Step 2: Commit**
```
fix: MetricsBlobLogger logs flush errors instead of silently swallowing [C7.8]
```

---

### Task 4.6: Docker Health Non-Blocking cpu_percent (C7.9)

**Files:**
- Modify: `docker_health/runtime.py:146`

**Step 1: Change to non-blocking measurement**

```python
# OLD:
"cpu_percent": round(psutil.cpu_percent(interval=0.1), 1),

# NEW:
"cpu_percent": round(psutil.cpu_percent(interval=None), 1),
```

**Step 2: Commit**
```
fix: Docker health uses non-blocking psutil.cpu_percent [C7.9]
```

---

## Phase 5: Data Access Cleanup

### Task 5.1: DuckDB Singleton Thread Safety (C3.4)

**Files:**
- Modify: `infrastructure/duckdb.py:171-186`

**Step 1: Add threading.Lock for singleton**

```python
import threading

class DuckDBRepository:
    _instance = None
    _initialized = False
    _instance_lock = threading.Lock()

    @classmethod
    def instance(cls, **kwargs) -> 'DuckDBRepository':
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls(**kwargs)
                    cls._initialized = True
                    logger.info("DuckDBRepository singleton created")
        return cls._instance
```

**Step 2: Commit**
```
fix: Thread-safe DuckDB singleton with double-checked locking [C3.4]
```

---

### Task 5.2: Remove Manual json.dumps() for JSONB (C3.5)

**Files:**
- Modify: `infrastructure/platform.py` (PlatformRegistryRepository.create)
- Modify: `infrastructure/raster_metadata_repository.py` (upsert)
- Modify: `infrastructure/h3_repository.py` (register_dataset)

**Step 1: Remove json.dumps() calls for JSONB columns**

Replace `json.dumps(value)` with just `value` (dict) since psycopg type adapters handle dict→JSONB automatically via `_register_type_adapters()`.

Example:
```python
# OLD:
json.dumps(platform.required_refs),

# NEW:
platform.required_refs,
```

**Step 2: Commit**
```
fix: Remove manual json.dumps() for JSONB columns, trust type adapters [C3.5]
```

---

### Task 5.3: Replace Hardcoded 'pending_review' with Enum (C3.6)

**Files:**
- Modify: `infrastructure/release_repository.py:1196, 1227`

**Step 1: Use enum value**

```python
# OLD:
AND approval_state = 'pending_review'

# NEW:
AND approval_state = %s
# ... with ApprovalState.PENDING_REVIEW.value in params
```

Or if using sql.SQL:
```python
AND approval_state = {approval_state}
# with sql.Literal(ApprovalState.PENDING_REVIEW.value)
```

**Step 2: Commit**
```
fix: Use ApprovalState enum instead of hardcoded 'pending_review' [C3.6]
```

---

### Task 5.4: Fix Factory Eager Imports (C3.7)

**Files:**
- Modify: `infrastructure/factory.py:33`

**Step 1: Move imports inside factory methods**

Replace module-level imports with deferred imports inside the methods that create repositories:
```python
# OLD (at module level):
from infrastructure.jobs_tasks import JobRepository, TaskRepository

# NEW (inside factory method):
def create_job_repository(self) -> 'JobRepository':
    from infrastructure.jobs_tasks import JobRepository
    return JobRepository()
```

**Step 2: Commit**
```
fix: Defer factory imports to match lazy loading pattern [C3.7]
```

---

### Task 5.5: Remove Duplicate IDuckDBRepository (C3.8)

**Files:**
- Modify: `infrastructure/duckdb.py:64-110`

**Step 1: Remove local IDuckDBRepository definition**

Have `DuckDBRepository` inherit from the canonical `IDuckDBRepository` in `infrastructure/interface_repository.py` instead of the local duplicate.

```python
# OLD:
class IDuckDBRepository(ABC):
    # ... local duplicate definition

class DuckDBRepository(IDuckDBRepository):

# NEW:
from infrastructure.interface_repository import IDuckDBRepository

class DuckDBRepository(IDuckDBRepository):
```

**Step 2: Commit**
```
cleanup: Remove duplicate IDuckDBRepository, use canonical interface [C3.8]
```

---

### Task 5.6: Standardize RasterMetadata Singleton (C3.9)

**Files:**
- Modify: `infrastructure/raster_metadata_repository.py:632-640`

**Step 1: Replace module-level singleton with class-method pattern**

```python
# OLD (module-level):
_instance = None
def get_raster_metadata_repository():
    global _instance
    if _instance is None:
        _instance = RasterMetadataRepository()
    return _instance

# NEW (class-method with lock):
class RasterMetadataRepository:
    _instance = None
    _instance_lock = threading.Lock()

    @classmethod
    def instance(cls) -> 'RasterMetadataRepository':
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
```

Update callers from `get_raster_metadata_repository()` to `RasterMetadataRepository.instance()`.

**Step 2: Commit**
```
fix: Standardize RasterMetadataRepository to class-method singleton [C3.9]
```

---

## Phase 6: Jobs, Services & Dead Code

### Task 6.1: Fix Direct DB Access in PromoteService (C4.4)

**Files:**
- Modify: `services/promote_service.py`

**Step 1: Replace `_get_item_for_validation()` direct DB query with repository call**

Identify the direct DB access in `PromoteService._get_item_for_validation()` and route through the appropriate repository method.

**Step 2: Commit**
```
fix: Route PromoteService._get_item_for_validation through repository [C4.4]
```

---

### Task 6.2: Document Parallelism Values (C4.5)

**Files:**
- Modify: `jobs/hello_world_job.py`

**Step 1: Add docstring explaining "dynamic" and "match_previous" parallelism**

Add documentation to the stages definition explaining what these values mean and when to use them.

**Step 2: Commit**
```
docs: Document parallelism values 'dynamic' and 'match_previous' [C4.5]
```

---

### Task 6.3: Decompose PromoteService.promote() (C4.6)

**Files:**
- Modify: `services/promote_service.py`

**Step 1: Extract logical sections into helper methods**

Break the 200+ line `promote()` method into focused helpers:
- `_validate_promotion_request()`
- `_prepare_promotion_data()`
- `_execute_promotion()`
- `_finalize_promotion()`

Each should be 30-60 lines. The main `promote()` becomes a coordinator calling these in sequence.

**Step 2: Commit**
```
refactor: Decompose PromoteService.promote() into focused helpers [C4.6]
```

---

### Task 6.4: Delete Dead Code docker_main.py (C8.2)

**Files:**
- Delete: `docker_main.py`

**Step 1: Verify Dockerfile uses docker_service.py**

Confirm `Dockerfile` CMD references `docker_service:app`, not `docker_main`.

**Step 2: Delete docker_main.py**

```bash
git rm docker_main.py
```

**Step 3: Commit**
```
cleanup: Delete dead docker_main.py (Dockerfile uses docker_service.py) [C8.2]
```

---

### Task 6.5: Replace Deprecated cgi Module (C5.2)

**Files:**
- Modify: `triggers/storage_upload.py:34, 85-94`

**Step 1: Replace cgi.FieldStorage with python-multipart or manual parsing**

```python
# OLD:
import cgi
fs = cgi.FieldStorage(fp=fp, environ=environ, keep_blank_values=True)

# NEW: Use multipart library or manual boundary parsing
from multipart.multipart import parse_options_header
from multipart import multipart

# Or use email.parser for simpler cases
```

If `python-multipart` is already in requirements (check `requirements.txt`), use it. Otherwise, use `email.parser` from stdlib.

**Step 2: Commit**
```
fix: Replace deprecated cgi module with modern multipart parsing [C5.2]
```

---

## Phase 7: API & Triggers

### Task 7.1: Fix STAC Nuke HTTP Status (C5.3)

**Files:**
- Modify: `triggers/` (find STAC nuke endpoint)

**Step 1: Return proper HTTP status codes for error conditions**

If the endpoint returns HTTP 200 with `status_code` in the body, change to return the actual HTTP status:
```python
# OLD:
return func.HttpResponse(json.dumps({"status": "error", ...}), status_code=200)

# NEW:
return func.HttpResponse(json.dumps({"status": "error", ...}), status_code=500)
```

**Step 2: Commit**
```
fix: STAC nuke returns proper HTTP status codes for errors [C5.3]
```

---

### Task 7.2: Gate Timer Triggers on App Mode (C5.4)

**Files:**
- Modify: Timer trigger registration in `function_app.py` or relevant blueprint

**Step 1: Add mode guard to timer triggers**

```python
from config import get_app_mode_config
mode_config = get_app_mode_config()

# Only register timer triggers for appropriate modes
if mode_config.app_mode.value in ('standalone', 'orchestrator'):
    # Register timer triggers
    ...
```

**Step 2: Commit**
```
fix: Timer triggers only registered in appropriate app modes [C5.4]
```

---

### Task 7.3: Standardize Approval Field Names (C5.5)

**Files:**
- Grep for `clearance_state` and `clearance_level` across triggers/

**Step 1: Pick one name and use it consistently**

Based on the V0.9 model (`ClearanceState` enum), standardize on `clearance_state`. Replace any `clearance_level` references.

**Step 2: Commit**
```
fix: Standardize approval field name to clearance_state [C5.5]
```

---

### Task 7.4: Standardize Error Response Format (C5.6)

**Files:**
- Modify: Various trigger files

**Step 1: Identify the 3 inconsistent formats**

Search for error response patterns. Standardize on:
```python
{
    "success": False,
    "error": "Human-readable message",
    "error_type": "ErrorCategory"
}
```

**Step 2: Commit**
```
fix: Standardize error response format across trigger endpoints [C5.6]
```

---

### Task 7.5: Replace datetime.utcnow() in Triggers (C5.7, C1.7)

**Files:**
- Modify: All files with `datetime.utcnow()` (30 occurrences across 11 files)

Full list:
- `core/schema/orchestration.py:301`
- `core/models/etl_tracking.py:308,347,359,375,386,403`
- `infrastructure/h3_schema.py:100,1063`
- `infrastructure/platform.py:107`
- `infrastructure/schema_analyzer.py:525,709,901`
- `triggers/admin/admin_system.py:109`
- `services/stac_catalog.py:65,85,240,254,299,303,420,511`
- `services/container_analysis.py:160,685`
- `services/delivery_discovery.py:389`
- `services/external_db_initializer.py:264,358`
- `triggers/admin/admin_data_migration.py:123,124,249`
- `core/models/results.py:100` (StageAdvancementResult default_factory)

**Step 1: Global replace**

```python
# OLD:
datetime.utcnow()

# NEW:
datetime.now(timezone.utc)
```

Ensure `timezone` is imported: `from datetime import datetime, timezone`

**Step 2: Commit**
```
fix: Replace deprecated datetime.utcnow() with datetime.now(timezone.utc) [C1.7, C5.7]
```

---

### Task 7.6: Fix Stale V0.8 Reference (C5.8)

**Files:**
- Grep for "V0.8" or "v0.8" in log messages in triggers/

**Step 1: Update to V0.9 reference**

**Step 2: Commit**
```
fix: Update stale V0.8 reference in log message [C5.8]
```

---

### Task 7.7: Remove Commented-Out Code in function_app.py (C5.9)

**Files:**
- Modify: `function_app.py`

**Step 1: Remove 300+ lines of commented-out code**

Delete any large blocks of `# commented out code` that are no longer needed. Git history preserves the old code.

**Step 2: Commit**
```
cleanup: Remove 300+ lines of commented-out code from function_app.py [C5.9]
```

---

## Phase 8: V0.9 Model Fixes

### Task 8.1: Fix flip_is_latest() Missing Rollback (C6.2)

**Files:**
- Modify: `infrastructure/release_repository.py` (find `flip_is_latest`)

**Step 1: Add rollback when target release not found**

```python
# After the UPDATE that clears old is_latest:
if cursor.rowcount == 0:
    conn.rollback()
    raise BusinessLogicError(f"Target release not found for flip_is_latest")
```

**Step 2: Commit**
```
fix: flip_is_latest() rolls back when target release not found [C6.2]
```

---

### Task 8.2: Deduplicate Approval Resolution Logic (C6.3)

**Files:**
- Modify: `triggers/trigger_approvals.py` (already has `_resolve_release()`)
- Modify: Any other trigger files that duplicate this logic

**Step 1: Identify other files with duplicated resolution logic**

Grep for `get_draft` + `get_latest` patterns in other trigger files.

**Step 2: Have other files import and use `_resolve_release()` from trigger_approvals**

Or extract to a shared helper module like `triggers/approval_helpers.py`.

**Step 3: Commit**
```
refactor: Deduplicate approval resolution logic into shared helper [C6.3]
```

---

### Task 8.3: Delete Dead Code AssetService.assign_version() (C6.4)

**Files:**
- Modify: `services/asset_service.py`

**Step 1: Verify assign_version() is not called anywhere**

```bash
grep -r "assign_version" --include="*.py"
```

**Step 2: Remove the method**

**Step 3: Commit**
```
cleanup: Remove dead AssetService.assign_version() method [C6.4]
```

---

### Task 8.4: Fix version_ordinal Type (C6.5)

**Files:**
- Modify: V0.9 model files (find `version_ordinal` definition)

**Step 1: Change Optional[int] to int with a default**

If spec says "never null", the type should be `int` with a default value (e.g., 0 or 1), not `Optional[int]`.

**Step 2: Commit**
```
fix: version_ordinal type int (not Optional[int]) per spec [C6.5]
```

---

### Task 8.5: Handle STAC insert_item Duplicates (C6.6)

**Files:**
- Modify: `infrastructure/pgstac_repository.py`

**Step 1: Add ON CONFLICT handling to insert_item**

```python
# Use INSERT ... ON CONFLICT (id, collection) DO UPDATE
# or check-then-insert pattern
```

**Step 2: Commit**
```
fix: STAC insert_item handles duplicates with ON CONFLICT [C6.6]
```

---

### Task 8.6: Address Pydantic V2 json_encoders Deprecation (C6.7)

**Files:**
- Modify: All model files using `json_encoders` in `ConfigDict`

**Step 1: Replace with custom serializers**

```python
# OLD (Pydantic V1 pattern):
model_config = ConfigDict(
    json_encoders={datetime: lambda v: v.isoformat()}
)

# NEW (Pydantic V2 pattern):
from pydantic import field_serializer

@field_serializer('timestamp', 'completion_time', 'created_at', 'updated_at')
@classmethod
def serialize_datetime(cls, v: datetime) -> str:
    return v.isoformat() if v else None
```

Note: This can be done incrementally. For now, the V1 pattern still works in Pydantic V2 with a deprecation warning. Track as low-priority.

**Step 2: Commit**
```
fix: Replace Pydantic V1 json_encoders with V2 field_serializer [C6.7]
```

---

## Phase 9: Core Orchestration Improvements

### Task 9.1: Persist Error Details in _mark_job_failed (C1.4)

**Files:**
- Modify: `core/machine.py:2144-2193`

**Step 1: Add error_message persistence to jobs table**

After `update_job_status()`, add a call to persist the error:
```python
self.state_manager.update_job_status(job_id, JobStatus.FAILED)

# Persist error details to jobs table
try:
    self.state_manager.update_job_error(
        job_id, error_message=error_message[:2000]
    )
except Exception as err:
    self.logger.warning(f"Failed to persist error details: {err}")
```

If `update_job_error()` doesn't exist on StateManager, check for an `update_job_metadata()` or add one that sets an `error_message` column.

**Step 2: Commit**
```
fix: _mark_job_failed persists error details to jobs table [C1.4]
```

---

### Task 9.2: Consolidate Repository Bundles (C1.5)

**Files:**
- Modify: `core/machine.py` and `core/state_manager.py`

**Step 1: Identify duplicate repository instantiations**

If both CoreMachine and StateManager create their own `JobRepository`, `TaskRepository`, etc., consolidate so CoreMachine's repositories are shared via StateManager (or vice versa).

**Step 2: Commit**
```
refactor: Share repository instances between CoreMachine and StateManager [C1.5]
```

---

### Task 9.3: Address Race Window in _advance_stage (C1.6)

**Files:**
- Modify: `core/machine.py` (find `_advance_stage`)

**Step 1: Document or fix the race between status update and message send**

If the status update commits but the message send fails, the job is in an inconsistent state. Options:
- Wrap both in a single transaction (if Service Bus supports transactional outbox)
- Add retry logic for the message send
- At minimum, document the window with a TODO

**Step 2: Commit**
```
fix: Document race window in _advance_stage between status update and message send [C1.6]
```

---

### Task 9.4: Fix Documentation Claim (C1.9)

**Files:**
- Modify: `docs_claude/ARCHITECTURE_REFERENCE.md` or relevant doc

**Step 1: Correct claim that CoreMachine composes OrchestrationManager**

Update to reflect actual composition (CoreMachine composes StateManager).

**Step 2: Commit**
```
docs: Correct CoreMachine composition claim in architecture docs [C1.9]
```

---

### Task 9.5: Decompose process_task_message (C1.8) [LARGE REFACTOR]

**Files:**
- Modify: `core/machine.py` (find `process_task_message`)

**Step 1: Identify logical sections in the ~400-line method**

Read the method and identify natural breakpoints:
- Message parsing/validation
- Task lookup and state validation
- Result processing
- Stage completion check
- Stage advancement
- Job completion

**Step 2: Extract each section into a named private method**

```python
def process_task_message(self, message):
    task, job = self._parse_and_validate_message(message)
    result = self._process_task_result(task, message)
    stage_complete = self._check_stage_completion(job, task.stage_number)
    if stage_complete:
        self._handle_stage_completion(job, task.stage_number, result)
```

Each extracted method should be 40-80 lines.

**Step 3: Commit**
```
refactor: Decompose process_task_message into focused helpers [C1.8]
```

---

## Phase 10: Web & Docker Polish

### Task 10.1: Audit innerHTML for Escaping (C8.3)

**Files:**
- Modify: Multiple web interface files

**Step 1: Identify high-risk innerHTML assignments**

Search for `innerHTML` assignments that interpolate:
- Collection names/descriptions (user-originated)
- Error messages
- Dataset names

**Step 2: Add escapeHtml() calls**

The `escapeHtml()` function already exists in `base.py`. Wrap user-originated data:
```javascript
// OLD:
el.innerHTML = `<span>${data.collection_name}</span>`;

// NEW:
el.innerHTML = `<span>${escapeHtml(data.collection_name)}</span>`;
```

Focus on the highest-risk paths first (data that originates from user input).

**Step 3: Commit**
```
fix: Add escapeHtml() to innerHTML assignments with user-originated data [C8.3]
```

---

### Task 10.2: Split base.py Monolith (C8.4) [LARGE REFACTOR]

**Files:**
- Modify: `web_interfaces/base.py` (3,100 lines)
- Create: `web_interfaces/design_system.py`
- Create: `web_interfaces/common_js.py`
- Create: `web_interfaces/navbar.py`

**Step 1: Extract CSS constants**

Move `COMMON_CSS` (~1,100 lines) to `web_interfaces/design_system.py`:
```python
# web_interfaces/design_system.py
COMMON_CSS = """
... (moved from base.py)
"""
HTMX_CSS = """
... (moved from base.py)
"""
```

**Step 2: Extract JavaScript constants**

Move `COMMON_JS` and `HTMX_JS` (~900 lines) to `web_interfaces/common_js.py`.

**Step 3: Extract navigation rendering**

Move navbar-related methods to `web_interfaces/navbar.py`.

**Step 4: Update base.py to import from new modules**

```python
from web_interfaces.design_system import COMMON_CSS, HTMX_CSS
from web_interfaces.common_js import COMMON_JS, HTMX_JS
from web_interfaces.navbar import render_navbar
```

**Step 5: Commit**
```
refactor: Split base.py into design_system, common_js, navbar modules [C8.4]
```

---

### Task 10.3: Replace Boilerplate Auto-Import (C8.5)

**Files:**
- Modify: `web_interfaces/__init__.py:279-485`

**Step 1: Replace 33 try/except blocks with auto-discovery**

```python
import importlib
import pkgutil

# Auto-discover and import all interface modules
for _, module_name, is_pkg in pkgutil.iter_modules(__path__):
    if is_pkg and module_name not in ('__pycache__', 'swagger'):
        try:
            importlib.import_module(f'.{module_name}.interface', package=__name__)
        except ImportError as e:
            logger.warning(f"Failed to import interface {module_name}: {e}")
```

**Step 2: Commit**
```
refactor: Auto-discover web interfaces instead of 33 manual imports [C8.5]
```

---

### Task 10.4: Docker HEALTHCHECK Use /livez (C8.8)

**Files:**
- Modify: `Dockerfile:69-70`

**Step 1: Change endpoint**

```dockerfile
# OLD:
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD curl -f http://localhost/health || exit 1

# NEW:
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD curl -f http://localhost/livez || exit 1
```

**Step 2: Commit**
```
fix: Docker HEALTHCHECK uses /livez instead of /health [C8.8]
```

---

### Task 10.5: Add HTMX SRI Hash (C8.9)

**Files:**
- Modify: `web_interfaces/base.py` (find HTMX script tag)

**Step 1: Add integrity attribute**

Generate SRI hash for HTMX 1.9.10 and add to script tag:
```python
htmx_script = (
    f'<script src="https://unpkg.com/htmx.org@{self.HTMX_VERSION}" '
    f'integrity="sha384-XXXX" crossorigin="anonymous"></script>'
)
```

Calculate the hash:
```bash
curl -s https://unpkg.com/htmx.org@1.9.10 | openssl dgst -sha384 -binary | openssl base64 -A
```

**Step 2: Commit**
```
fix: Add SRI integrity hash to HTMX CDN script [C8.9]
```

---

### Task 10.6: Exclude web_interfaces from Docker Image (C8.10)

**Files:**
- Modify: `.dockerignore`

**Step 1: Add web_interfaces/ to .dockerignore**

```
web_interfaces/
```

The Docker worker does not serve web interfaces (confirmed by archived comment in docker_service.py:1156).

**Step 2: Commit**
```
fix: Exclude web_interfaces/ from Docker image [C8.10]
```

---

## Coverage Summary

| Phase | Items | Severity | Estimated Effort |
|-------|-------|----------|------------------|
| 1. Critical Security | C3.1-C3.3, C8.1, C7.1, C5.1 + tests | P1 | Medium |
| 2. Critical Bugs | C1.1-C1.3, C6.1, C4.1-C4.3, C7.2 + tests | P1 | Medium |
| 3. Config Alignment | C2.1-C2.6, C2.8, C2.9 | P1/P2 | Small |
| 4. Observability | C7.3, C7.5-C7.9 | P2/P3 | Small |
| 5. Data Access | C3.4-C3.9 | P2/P3 | Small |
| 6. Jobs/Services/Dead Code | C4.4-C4.6, C8.2, C5.2 | P2/P3 | Small-Medium |
| 7. API/Triggers | C5.3-C5.9, C1.7 | P2/P3 | Small |
| 8. V0.9 Model | C6.2-C6.7 | P2/P3 | Small-Medium |
| 9. Core Orchestration | C1.4-C1.6, C1.8, C1.9 | P2/P3 | Medium-Large |
| 10. Web/Docker Polish | C8.3-C8.5, C8.8-C8.10 | P2/P3 | Medium-Large |

**Excluded:** C8.6 (CSP), C8.7 (CSRF) -- dev-grade security per policy
**Tests:** P1 security fixes (Task 1.7) and P1 bug fixes (Task 2.9)

---

## Execution Notes

- **Phases 1-2 are critical path** -- do these first, in order
- **Phases 3-8 are independent** -- can be parallelized across agents
- **Phases 9-10 contain large refactors** -- do last, one at a time
- **Each task should be committed separately** for easy rollback
- **Run `conda activate azgeo`** before any Python execution
- **Test after each phase:** `python -m pytest tests/ -v`
