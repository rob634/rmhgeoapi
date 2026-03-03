# Agent Review Constitution

**Purpose**: Project-specific architectural rules that ALL code review agents (COMPETE, REFLEXION) must enforce. These rules are non-negotiable — violations are findings.

**Last Updated**: 02 MAR 2026

**Sources**: `CLAUDE.md`, `docs_claude/DEV_BEST_PRACTICES.md`, `docs_claude/ARCHITECTURE_REFERENCE.md`, `docs_claude/SCHEMA_EVOLUTION.md`

---

## How Agents Use This Document

**COMPETE** (Alpha/Beta/Gamma/Delta): Include relevant sections in the agent prompts based on the scope split:
- Alpha (architecture scope) → Sections 1, 4, 5, 8, 9
- Beta (correctness scope) → Sections 1, 2, 3, 6, 7
- Gamma (blind spot finder) → All sections (Gamma checks what Alpha and Beta missed)

**REFLEXION** (R/F/P/J): Include in Agent F's Developer Context:
- Agent F → Sections 1, 2, 3, 6 (fault-relevant rules)
- Agent P → Sections 1, 3 (patch constraints — don't introduce violations)

---

## Section 1: Zero-Tolerance Rules

These are CRITICAL violations. Any occurrence is a finding.

### 1.1 No Backward Compatibility Fallbacks

Fail explicitly. Never create fallbacks that mask breaking changes.

```python
# ❌ VIOLATION
job_type = entity.get('job_type') or 'default_value'
priority = data.get('key') or 'default'

# ✅ CORRECT
job_type = entity.get('job_type')
if not job_type:
    raise ValueError("job_type is required field")
```

### 1.2 SQL Must Use `sql.SQL` Composition — Never F-Strings

All SQL must use `psycopg.sql.SQL()` and `sql.Identifier()`. F-strings in SQL are injection vulnerabilities.

```python
# ❌ VIOLATION — SQL injection risk
cur.execute(f"SELECT * FROM {schema}.{table} WHERE id = '{id}'")

# ✅ CORRECT
cur.execute(
    sql.SQL("SELECT * FROM {}.{} WHERE id = %s").format(
        sql.Identifier(schema), sql.Identifier(table)
    ), (id,)
)
```

### 1.3 ContractViolationError Must Bubble Up

`ContractViolationError` = programming bug. Never catch it. Let it crash.

```python
# ❌ VIOLATION — swallows a bug
except (ContractViolationError, BusinessLogicError):
    logger.error("Something went wrong")

# ✅ CORRECT — let contract violations bubble
except ContractViolationError:
    raise  # Bug! Let it crash.
except BusinessLogicError as e:
    return handle_failure(e)  # Expected failure, handle gracefully.
```

### 1.4 Database Access Only Through Repository Pattern

Never create raw psycopg connections. Always use `PostgreSQLRepository`.

```python
# ❌ VIOLATION
import psycopg2
conn = psycopg2.connect(host=..., user=..., password=...)

# ✅ CORRECT
from infrastructure import PostgreSQLRepository
repo = PostgreSQLRepository(schema_name='app')
```

### 1.5 Auth Owned by BlobRepository

All blob access must derive credentials from `BlobRepository.for_zone()`. Never create independent `DefaultAzureCredential()`.

```python
# ❌ VIOLATION
from azure.identity import DefaultAzureCredential
cred = DefaultAzureCredential()
client = BlobServiceClient(account_url, credential=cred)

# ✅ CORRECT
from infrastructure import BlobRepository
repo = BlobRepository.for_zone("bronze")
```

---

## Section 2: Configuration Access

### 2.1 AppModeConfig Is Separate From AppConfig

`get_config()` returns `AppConfig`. `get_app_mode_config()` returns `AppModeConfig`. They are different singletons.

```python
# ❌ VIOLATION — AttributeError
config = get_config()
mode = config.app_mode.mode

# ✅ CORRECT
config = get_config()
app_mode = get_app_mode_config()
mode = app_mode.mode
```

### 2.2 Never Access `os.environ` in Service Code

All env var access goes through the config layer.

```python
# ❌ VIOLATION
import os
host = os.environ['POSTGIS_HOST']

# ✅ CORRECT
from config import get_config
config = get_config()
host = config.database.host
```

### 2.3 Lazy Imports in Azure Functions Handlers

Azure Functions loads modules before env vars are ready. Infrastructure imports go inside handlers.

```python
# ❌ VIOLATION — fails at module load time
from infrastructure import PostgreSQLRepository
repo = PostgreSQLRepository()

def my_handler(req):
    ...

# ✅ CORRECT — import inside handler
def my_handler(req):
    from infrastructure import PostgreSQLRepository
    repo = PostgreSQLRepository()
```

---

## Section 3: Error Handling

### 3.1 Two Error Categories — Never Mix

| Type | Meaning | Action |
|------|---------|--------|
| `ContractViolationError` | Programming bug (wrong type, missing field) | Let bubble up |
| `BusinessLogicError` | Expected failure (missing resource, validation) | Catch and handle |

### 3.2 Handler Return Contract

All task handlers MUST return `{"success": True/False, ...}`. CoreMachine uses this to determine COMPLETED vs FAILED.

```python
# ❌ VIOLATION — missing success field
return {"result": data}

# ✅ CORRECT
return {"success": True, "result": data}
```

### 3.3 No Exception Swallowing

Never catch Exception without logging or re-raising. Silent failures are bugs.

```python
# ❌ VIOLATION
except Exception:
    pass

# ✅ CORRECT
except Exception as e:
    logger.error(f"Unexpected: {e}", exc_info=True)
    raise
```

---

## Section 4: Import & Layering Rules

### 4.1 Import Hierarchy (Higher Can Import Lower, Not Reverse)

```
triggers/          ← Top level, can import anything below
  ↓
services/          ← Business logic, can import infrastructure + core
  ↓
infrastructure/    ← Data access, can import core + config
  ↓
core/              ← Models, enums — minimal dependencies
  ↓
config/            ← Configuration — no internal dependencies
```

A `core/` file importing from `services/` is a CRITICAL violation.

### 4.2 Explicit Handler Registration

All handlers registered in `services/__init__.py` → `ALL_HANDLERS` dict. No decorator magic.

### 4.3 TYPE_CHECKING Guard for Optional Imports

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from services.approval_service import ApprovalService
```

---

## Section 5: Platform Layer Architecture

### 5.1 Service Bus Queue Is the Only Interface

Platform enqueues jobs and exits. Platform NEVER executes jobs or waits for results.

### 5.2 Platform Never Writes to Jobs/Tasks Tables

Platform CAN read `app.jobs` for status (read-only). Only CoreMachine writes.

---

## Section 6: Database Patterns

### 6.1 Cursor Rows Are Dicts, Not Tuples

`PostgreSQLRepository._get_connection()` returns `dict_row` cursors. Access by key.

```python
# ❌ VIOLATION
job_id = row[0]

# ✅ CORRECT
job_id = row['job_id']
```

### 6.2 Handle NULL/None Explicitly

Never assume columns are non-NULL.

```python
# ❌ VIOLATION
value = row['optional_col'].strip()

# ✅ CORRECT
value = row.get('optional_col')
if value:
    value = value.strip()
```

---

## Section 7: Schema Evolution

### 7.1 Default Action Is `ensure` (Safe, Preserves Data)

`action=rebuild` destroys all data. Only for fresh dev/test environments.

### 7.2 New Columns Must Have DEFAULT Values

Otherwise existing rows break.

### 7.3 Enum Changes Require Migration Scripts

PostgreSQL enums are immutable. `ALTER TYPE ... ADD VALUE IF NOT EXISTS` in a migration script.

### 7.4 Breaking Changes Require Written Migration Plans

Rename, type change, remove column/table — never ad hoc.

---

## Section 8: Naming & Formatting

### 8.1 Military Date Format

All dates: `DD MMM YYYY` (e.g., `02 MAR 2026`). In code comments, docstrings, logs.

### 8.2 Python File Header Template

```python
# ============================================================================
# CLAUDE CONTEXT - [DESCRIPTIVE_TITLE]
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: [Component type]
# PURPOSE: [One sentence]
# LAST_REVIEWED: [DD MMM YYYY]
# EXPORTS: [Main classes, functions]
# DEPENDENCIES: [Key external libraries]
# ============================================================================
```

### 8.3 Version Format `0.v.i.d`

Defined in `config/__init__.py` → `__version__`. Pre-production stays `0.x.y.z`.

---

## Section 9: Job & Task Patterns

### 9.1 Idempotent Job IDs

Job IDs are `SHA256(job_type + params)`. Same params = same job. Code must handle deduplication.

### 9.2 Mixin Inheritance Order

`JobBaseMixin` MUST come first:

```python
# ❌ VIOLATION
class MyJob(JobBase, JobBaseMixin):

# ✅ CORRECT
class MyJob(JobBaseMixin, JobBase):
```

### 9.3 Azure Functions Folders Require `__init__.py`

Every function folder must have `__init__.py`. Never use `*/` in `.funcignore`.

---

## Quick Reference: Finding Severity

| Severity | When to Use |
|----------|-------------|
| **CRITICAL** | SQL injection, raw DB connections, caught ContractViolationError, circular import |
| **HIGH** | Backward compat fallback, direct os.environ, exception swallowing, wrong config singleton |
| **MEDIUM** | Missing handler return contract, tuple row access, missing NULL check |
| **LOW** | Wrong date format, missing file header, naming inconsistency |
