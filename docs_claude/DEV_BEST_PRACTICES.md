# Development Best Practices

**Last Updated**: 16 JAN 2026
**Purpose**: Accumulated lessons learned and patterns for developers and future Claude instances

---

## How to Use This Document

1. **Read before coding** - Review relevant sections before implementing new features
2. **Add lessons learned** - When you discover a gotcha or pattern, add it here
3. **Link from code** - Reference this doc in code comments when relevant

---

## Table of Contents

1. [Database Access Patterns](#database-access-patterns)
2. [Configuration Access](#configuration-access)
3. [Error Handling](#error-handling)
4. [Import Patterns](#import-patterns)
5. [Job/Task Patterns](#jobtask-patterns)
6. [STAC Patterns](#stac-patterns)
7. [Testing Patterns](#testing-patterns)
8. [Common Mistakes](#common-mistakes)

---

## Database Access Patterns

### Use PostgreSQLRepository for All DB Access

**Pattern**: Always use `PostgreSQLRepository` - never raw psycopg connections.

```python
# CORRECT
from infrastructure import PostgreSQLRepository

repo = PostgreSQLRepository(schema_name='app')
with repo._get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT * FROM {}.jobs").format(
            sql.Identifier('app')
        ))
        rows = cur.fetchall()
```

**Why**: Repository handles connection pooling, managed identity auth, and consistent error handling.

### Dict Indexing vs Tuple Indexing

**CRITICAL**: Our cursors return **dict rows** by default, NOT tuples.

```python
# WRONG - Will fail with KeyError or TypeError
row = cur.fetchone()
job_id = row[0]  # Tuple indexing - WRONG!

# CORRECT - Dict indexing
row = cur.fetchone()
job_id = row['job_id']  # Dict key access - CORRECT!
```

**Why**: `PostgreSQLRepository._get_connection()` configures cursor with `row_factory=dict_row`.

### Always Use sql.SQL Composition

**Pattern**: Never use f-strings or string formatting for SQL.

```python
# WRONG - SQL injection risk
cur.execute(f"SELECT * FROM {schema}.{table} WHERE id = '{id}'")

# CORRECT - Parameterized query with sql composition
cur.execute(
    sql.SQL("SELECT * FROM {}.{} WHERE id = %s").format(
        sql.Identifier(schema),
        sql.Identifier(table)
    ),
    (id,)
)
```

### Handle NULL/None Explicitly

```python
# WRONG - Will error if column is NULL
value = row['optional_column'].strip()

# CORRECT - Check for None first
value = row.get('optional_column')
if value:
    value = value.strip()
```

---

## Configuration Access

### AppConfig Composition Pattern

`AppConfig` uses composition with these sub-configs:

| Attribute | Config Class | Common Properties |
|-----------|--------------|-------------------|
| `config.storage` | StorageConfig | `bronze`, `silver`, `gold`, `account_name` |
| `config.database` | DatabaseConfig | `host`, `database`, `geo_schema` |
| `config.queues` | QueueConfig | `connection_string`, `raster_tasks_queue` |
| `config.raster` | RasterConfig | `default_resolution`, `cog_settings` |
| `config.vector` | VectorConfig | `max_features`, `simplify_tolerance` |
| `config.analytics` | AnalyticsConfig | `instrumentation_key` |
| `config.h3` | H3Config | `resolutions`, `base_resolution` |
| `config.platform` | PlatformConfig | `api_version` |
| `config.metrics` | MetricsConfig | `enabled`, `sample_rate` |

### AppModeConfig is SEPARATE

**CRITICAL**: `app_mode` is NOT part of AppConfig!

```python
# WRONG - Will raise AttributeError
from config import get_config
config = get_config()
mode = config.app_mode.mode  # AttributeError!

# CORRECT - Use separate function
from config import get_config, get_app_mode_config
config = get_config()
app_mode = get_app_mode_config()
mode = app_mode.mode
docker_enabled = app_mode.docker_worker_enabled
```

### Environment Variable Access

**Pattern**: Never access `os.environ` directly in service code.

```python
# WRONG - Direct env access
import os
host = os.environ['POSTGIS_HOST']

# CORRECT - Use config
from config import get_config
config = get_config()
host = config.database.host
```

**Why**: Config validates required vars at startup, provides defaults, and centralizes access.

---

## Error Handling

### Contract Violation vs Business Error

| Error Type | When | How to Handle |
|------------|------|---------------|
| `ContractViolationError` | Programming bug, should never happen | Let bubble up, fix the code |
| `BusinessLogicError` | Expected failure (invalid input, etc.) | Handle gracefully, return error |

```python
from core.errors import ContractViolationError, BusinessLogicError

def process_job(job_id: str):
    if not job_id:
        # This is a programming bug - caller should validate
        raise ContractViolationError("job_id is required")

    job = repo.get_by_id(job_id)
    if not job:
        # This is expected - job might not exist
        raise BusinessLogicError(f"Job not found: {job_id}")
```

### No Backward Compatibility Fallbacks

**CRITICAL**: This is a development environment - fail explicitly!

```python
# WRONG - Hides problems
job_type = entity.get('job_type') or 'default_value'

# CORRECT - Explicit error
job_type = entity.get('job_type')
if not job_type:
    raise ValueError("job_type is required field - data corruption?")
```

### Logging Best Practices

```python
from util_logger import LoggerFactory, ComponentType

# Create logger with component type
logger = LoggerFactory.create_logger(ComponentType.SERVICE, "MyService")

# Use appropriate levels
logger.debug("Detailed info for debugging")
logger.info("Normal operation info")
logger.warning("Something unexpected but recoverable")
logger.error("Error that needs attention", exc_info=True)  # Include traceback
```

---

## Import Patterns

### Lazy Imports for Azure Functions

**Problem**: Azure Functions loads modules before env vars are ready.

```python
# WRONG - Top-level import executes immediately
from infrastructure import PostgreSQLRepository  # May fail!

# CORRECT - Lazy import inside function
def my_handler(req):
    from infrastructure import PostgreSQLRepository
    repo = PostgreSQLRepository()
    ...
```

### TYPE_CHECKING Guard

Use for type hints without runtime import:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.approval_service import ApprovalService

def process(service: "ApprovalService"):  # Quoted type hint
    ...
```

### Avoid Circular Imports

Import hierarchy (higher can import lower, not reverse):
```
triggers/          # Top level - can import anything
  ↓
services/          # Business logic - can import infrastructure, core
  ↓
infrastructure/    # Data access - can import core, config
  ↓
core/              # Models, enums - minimal dependencies
  ↓
config/            # Configuration - no internal dependencies
```

---

## Job/Task Patterns

### Handler Return Contract

All task handlers MUST return a dict with `success` field:

```python
def my_handler(params: Dict[str, Any], context: Optional[Dict] = None) -> Dict[str, Any]:
    try:
        result = do_work(params)
        return {
            "success": True,
            "result": result
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }
```

**Why**: CoreMachine uses `success` field to determine task status (COMPLETED vs FAILED).

### Register Handlers Explicitly

All handlers must be registered in `services/__init__.py`:

```python
# services/__init__.py
ALL_HANDLERS = {
    "my_new_handler": my_handler_function,
    ...
}
```

**Why**: No decorator magic - explicit registration is visible and predictable.

### Idempotent Job IDs

Job IDs are SHA256 hashes of (job_type + params):

```python
# Same params = same job ID = deduplication
job_id_1 = submit_job("process_vector", {"file": "a.gpkg"})
job_id_2 = submit_job("process_vector", {"file": "a.gpkg"})
assert job_id_1 == job_id_2  # Same job, not duplicated
```

---

## STAC Patterns

### STAC Item Properties

Custom properties use `app:` prefix:

```python
properties = {
    "datetime": datetime.now(timezone.utc).isoformat(),
    "app:published": True,
    "app:classification": "ouo",
    "app:job_id": job_id,
    "app:etl_version": "1.0"
}
```

### Collection Naming

| Tier | Collection Pattern | Example |
|------|-------------------|---------|
| Bronze | `bronze-{container}` | `bronze-uploads` |
| Silver | Domain-specific | `admin-boundaries`, `flood-risk` |
| Gold | Export format | `geoparquet-exports` |

### PgSTAC Repository

```python
from infrastructure.pgstac_repository import PgStacRepository

pgstac = PgStacRepository()

# Create/update item
pgstac.upsert_item(collection_id, item_dict)

# Update properties only
pgstac.update_item_properties(item_id, collection_id, {"app:published": True})

# Query items
items = pgstac.search_items(collection_id, bbox=[-180, -90, 180, 90])
```

---

## Testing Patterns

### Local Testing with func start

```bash
# Activate correct environment
conda activate azgeo

# Start local Functions runtime
func start

# Test endpoint
curl http://localhost:7071/api/health
```

### Test Approvals (Dev Endpoint)

```bash
# Create test approval
curl -X POST "http://localhost:7071/api/approvals/test" \
  -H "Content-Type: application/json" \
  -d '{"job_id": "test-123", "classification": "ouo"}'
```

### Schema Testing

```bash
# Safe additive test (no data loss)
curl -X POST "http://localhost:7071/api/dbadmin/maintenance?action=ensure&confirm=yes"

# Destructive reset (wipes data)
curl -X POST "http://localhost:7071/api/dbadmin/maintenance?action=rebuild&confirm=yes"
```

---

## Common Mistakes

### Mistake 1: Tuple Indexing Database Results

```python
# WRONG
row = cur.fetchone()
value = row[0]

# RIGHT
value = row['column_name']
```

### Mistake 2: Accessing app_mode from AppConfig

```python
# WRONG
config.app_mode.docker_worker_enabled

# RIGHT
from config import get_app_mode_config
app_mode = get_app_mode_config()
app_mode.docker_worker_enabled
```

### Mistake 3: String Formatting in SQL

```python
# WRONG - SQL injection
f"SELECT * FROM {table}"

# RIGHT - sql.Identifier
sql.SQL("SELECT * FROM {}").format(sql.Identifier(table))
```

### Mistake 4: Backward Compatibility Fallbacks

```python
# WRONG - Masks data issues
value = data.get('key') or 'default'

# RIGHT - Explicit validation
value = data.get('key')
if value is None:
    raise ValueError("'key' is required")
```

### Mistake 5: Top-Level Imports in Triggers

```python
# WRONG - Fails before env vars ready
from infrastructure import PostgreSQLRepository
repo = PostgreSQLRepository()  # Fails at module load!

# RIGHT - Lazy import
def handler(req):
    from infrastructure import PostgreSQLRepository
    repo = PostgreSQLRepository()
```

### Mistake 6: Missing Handler Registration

```python
# Created handler in services/my_handlers.py but forgot to register

# MUST add to services/__init__.py:
ALL_HANDLERS = {
    "my_new_task": my_handler_function,  # Don't forget!
}
```

### Mistake 7: Forgetting confirm=yes

```bash
# WRONG - Returns 400 error
curl -X POST ".../api/dbadmin/maintenance?action=ensure"

# RIGHT - Include confirmation
curl -X POST ".../api/dbadmin/maintenance?action=ensure&confirm=yes"
```

---

## Adding to This Document

When you discover a new pattern or gotcha:

1. **Identify the category** - Does it fit existing sections?
2. **Document the mistake** - Show wrong code first
3. **Show the fix** - Provide correct code
4. **Explain why** - Help future developers understand
5. **Add to Common Mistakes** - If it's a frequent issue

Example format:
```markdown
### Mistake N: Brief Description

```python
# WRONG - Explain why
bad_code()

# RIGHT - Explain the fix
good_code()
```

**Why**: Explanation of the underlying reason.
```

---

## Related Documentation

- `CLAUDE.md` - Quick reference for all common operations
- `ERRORS_AND_FIXES.md` - Specific error messages and resolutions
- `SCHEMA_EVOLUTION.md` - Database schema change patterns
- `ARCHITECTURE_REFERENCE.md` - Deep technical architecture
- `JOB_CREATION_QUICKSTART.md` - Adding new job types
