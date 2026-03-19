# Project Constitution

**Purpose**: Architectural rules that govern ALL Claude interactions with this codebase — implementation, review, design, and testing.

**Last Updated**: 19 MAR 2026

**Sources**: `CLAUDE.md`, `docs_claude/DEV_BEST_PRACTICES.md`, `docs_claude/ARCHITECTURE_REFERENCE.md`, `docs_claude/SCHEMA_EVOLUTION.md`

---

## Scope: Who Uses This Document

This Constitution applies to every Claude that touches this codebase, at every tier:

| Tier | Who | How They Use It |
|------|-----|-----------------|
| **Claude Prime** | Main interactive session | Check before writing code. Self-review against these rules before committing. |
| **Subagents** | Spawned by Claude Prime for focused tasks | Inherit these rules. Must not introduce violations even under narrow task scope. |
| **Pipeline Agents** | COMPETE, SIEGE, GREENFIELD, REFLEXION, TOURNAMENT, ADVOCATE | Enforce adversarially. Violations are findings with severity ratings. |

### How Claude Prime Uses This

Before writing or modifying code, verify against Sections 1-4 (zero-tolerance, config, errors, imports). These are the rules most likely to be violated during normal development. Sections 5-9 apply situationally.

**Deviation clause**: Claude Prime is advisory, not blocked. If Robert's request would deviate from a Constitution rule, Claude Prime must:
1. **Name the rule** — e.g. "This would deviate from Section 1.1 (no backward compatibility fallbacks)"
2. **Explain the risk** — what could go wrong, what the rule was designed to prevent
3. **Ask for the reasoning** — "What's driving this deviation?"
4. **Proceed if Robert confirms** — document the deviation with a code comment: `# DEVIATION: Section X.X — [reason]`

The goal is conscious deviation, not blind compliance. Robert is the architect. Some rules exist because of past incidents that may no longer apply, or because the general case differs from the specific situation. The Constitution makes deviation visible, not impossible.

**Pipeline agents do NOT get this clause.** COMPETE, SIEGE, and REFLEXION enforce the Constitution strictly — every violation is a finding. The deviation clause is exclusively for interactive sessions where Robert is present to make the judgment call.

**Do not silently fix violations you find in existing code** — flag them to Robert. The agent pipelines track these systematically; ad hoc fixes without context can break things.

### How Pipeline Agents Use This

**COMPETE** (Alpha/Beta/Gamma/Delta): Include relevant sections based on scope split:
- Alpha (architecture scope) -> Sections 1, 4, 5, 8, 9
- Beta (correctness scope) -> Sections 1, 2, 3, 6, 7
- Gamma (blind spot finder) -> All sections

**REFLEXION** (R/F/P/J):
- Agent F -> Sections 1, 2, 3, 6 (fault-relevant rules)
- Agent P -> Sections 1, 3 (patch constraints)

**GREENFIELD** (S/A/C/O/M/B/V):
- Agent C (Critic) -> All sections (finds spec gaps that would violate rules)
- Agent B (Builder) -> Sections 1, 2, 3, 4, 6 (must not introduce violations)
- Agent V (Validator) -> All sections (blind review against Constitution)

---

## Section 1: Zero-Tolerance Rules

These are CRITICAL violations. Any occurrence is a finding.

### 1.1 No Backward Compatibility Fallbacks

Fail explicitly. Never create fallbacks that mask breaking changes.

```python
# VIOLATION
job_type = entity.get('job_type') or 'default_value'
priority = data.get('key') or 'default'

# CORRECT
job_type = entity.get('job_type')
if not job_type:
    raise ValueError("job_type is required field")
```

### 1.2 SQL Must Use `sql.SQL` Composition -- Never F-Strings

All SQL must use `psycopg.sql.SQL()` and `sql.Identifier()`. F-strings in SQL are injection vulnerabilities.

```python
# VIOLATION -- SQL injection risk
cur.execute(f"SELECT * FROM {schema}.{table} WHERE id = '{id}'")

# CORRECT
cur.execute(
    sql.SQL("SELECT * FROM {}.{} WHERE id = %s").format(
        sql.Identifier(schema), sql.Identifier(table)
    ), (id,)
)
```

### 1.3 ContractViolationError Must Bubble Up

`ContractViolationError` = programming bug. Never catch it. Let it crash.

```python
# VIOLATION -- swallows a bug
except (ContractViolationError, BusinessLogicError):
    logger.error("Something went wrong")

# CORRECT -- let contract violations bubble
except ContractViolationError:
    raise  # Bug! Let it crash.
except BusinessLogicError as e:
    return handle_failure(e)  # Expected failure, handle gracefully.
```

### 1.4 Database Access Only Through Repository Pattern

Never create raw psycopg connections. Always use repository classes.

```python
# VIOLATION
import psycopg2
conn = psycopg2.connect(host=..., user=..., password=...)

# CORRECT
from infrastructure import PostgreSQLRepository
repo = PostgreSQLRepository(schema_name='app')
```

### 1.5 Auth Owned by BlobRepository

All blob access must derive credentials from `BlobRepository.for_zone()`. Never create independent `DefaultAzureCredential()`. Exception: health checks and diagnostics may use independent credentials when justified.

```python
# VIOLATION
from azure.identity import DefaultAzureCredential
cred = DefaultAzureCredential()
client = BlobServiceClient(account_url, credential=cred)

# CORRECT
from infrastructure import BlobRepository
repo = BlobRepository.for_zone("bronze")
```

---

## Section 2: Configuration Access

### 2.1 AppModeConfig Is Separate From AppConfig

`get_config()` returns `AppConfig`. `get_app_mode_config()` returns `AppModeConfig`. They are different singletons.

```python
# VIOLATION -- AttributeError
config = get_config()
mode = config.app_mode.mode

# CORRECT
config = get_config()
app_mode = get_app_mode_config()
mode = app_mode.mode
```

### 2.2 Never Access `os.environ` in Service Code

All env var access goes through the config layer.

```python
# VIOLATION
import os
host = os.environ['POSTGIS_HOST']

# CORRECT
from config import get_config
config = get_config()
host = config.database.host
```

### 2.3 Lazy Imports in Azure Functions Handlers

Azure Functions loads modules before env vars are ready. Infrastructure imports go inside handlers.

```python
# VIOLATION -- fails at module load time
from infrastructure import PostgreSQLRepository
repo = PostgreSQLRepository()

def my_handler(req):
    ...

# CORRECT -- import inside handler
def my_handler(req):
    from infrastructure import PostgreSQLRepository
    repo = PostgreSQLRepository()
```

---

## Section 3: Error Handling

### 3.1 Two Error Categories -- Never Mix

| Type | Meaning | Action |
|------|---------|--------|
| `ContractViolationError` | Programming bug (wrong type, missing field) | Let bubble up |
| `BusinessLogicError` | Expected failure (missing resource, validation) | Catch and handle |

### 3.2 Handler Return Contract

All task handlers MUST return `{"success": True/False, ...}`. CoreMachine and DAG orchestrator use this to determine COMPLETED vs FAILED.

```python
# VIOLATION -- missing success field
return {"result": data}

# CORRECT
return {"success": True, "result": data}
```

### 3.3 No Exception Swallowing

Never catch Exception without logging or re-raising. Silent failures are bugs.

```python
# VIOLATION
except Exception:
    pass

# CORRECT
except Exception as e:
    logger.error(f"Unexpected: {e}", exc_info=True)
    raise
```

---

## Section 4: Import & Layering Rules

### 4.1 Import Hierarchy (Higher Can Import Lower, Not Reverse)

```
triggers/          <- Top level, can import anything below
  |
services/          <- Business logic, can import infrastructure + core
  |
infrastructure/    <- Data access, can import core + config
  |
core/              <- Models, enums -- minimal dependencies
  |
config/            <- Configuration -- no internal dependencies
```

A `core/` file importing from `services/` is a CRITICAL violation.

### 4.2 Explicit Handler Registration

All handlers registered in `services/__init__.py` -> `ALL_HANDLERS` dict. No decorator magic.

### 4.3 TYPE_CHECKING Guard for Optional Imports

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from services.approval_service import ApprovalService
```

---

## Section 5: Platform & Task Dispatch Architecture

### 5.1 Platform Is Decoupled From Execution

Platform submits jobs and exits. Platform NEVER executes jobs or waits for results.

### 5.2 Platform Never Writes to Jobs/Tasks Tables

Platform CAN read `app.jobs` for status (read-only). Only CoreMachine/DAG orchestrator writes.

### 5.3 Task Dispatch Is DB-Polling (v0.10.3.0+)

Workers claim tasks via PostgreSQL `SELECT FOR UPDATE SKIP LOCKED`. Service Bus `container-tasks` queue is deprecated. `geospatial-jobs` queue remains for orchestrator job submission until v0.11.0.

### 5.4 Epoch 4 Freeze Policy

CoreMachine, Python job classes, and Service Bus are in maintenance mode. Bug fixes only. New features must be atomic handlers (work in both epochs) or YAML workflows (Epoch 5 DAG only). No new Python job classes, no CoreMachine refactoring, no SB changes.

---

## Section 6: Database Patterns

### 6.1 Cursor Rows Are Dicts, Not Tuples

Repository connections return `dict_row` cursors. Access by key.

```python
# VIOLATION
job_id = row[0]

# CORRECT
job_id = row['job_id']
```

### 6.2 Handle NULL/None Explicitly

Never assume columns are non-NULL.

```python
# VIOLATION
value = row['optional_col'].strip()

# CORRECT
value = row.get('optional_col')
if value:
    value = value.strip()
```

### 6.3 Type Adapters Registered at Connection Level

psycopg3 type adapters (UUID, enum, datetime) are registered via `register_type_adapters()` in `infrastructure/db_utils.py`. Never register adapters globally or per-cursor.

---

## Section 7: Schema Evolution

### 7.1 Default Action Is `ensure` (Safe, Preserves Data)

`action=rebuild` destroys all data. Only for fresh dev/test environments.

### 7.2 New Columns Must Have DEFAULT Values

Otherwise existing rows break.

### 7.3 Enum Changes Use Rebuild, Not ALTER

Enum values and DDL changes go into the model code and deploy via `action=rebuild`, not standalone ALTER statements.

### 7.4 Breaking Changes Require Written Migration Plans

Rename, type change, remove column/table -- never ad hoc.

---

## Section 8: Naming & Formatting

### 8.1 Military Date Format

All dates: `DD MMM YYYY` (e.g., `19 MAR 2026`). In code comments, docstrings, logs.

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

Defined in `config/__init__.py` -> `__version__`. Pre-production stays `0.x.y.z`.

---

## Section 9: Job & Task Patterns

### 9.1 Idempotent Job IDs

Job IDs are `SHA256(job_type + params)`. Same params = same job. Code must handle deduplication.

### 9.2 Mixin Inheritance Order

`JobBaseMixin` MUST come first:

```python
# VIOLATION
class MyJob(JobBase, JobBaseMixin):

# CORRECT
class MyJob(JobBaseMixin, JobBase):
```

### 9.3 Azure Functions Folders Require `__init__.py`

Every function folder must have `__init__.py`. Never use `*/` in `.funcignore`.

### 9.4 DAG Workflows Use YAML Definitions

New workflows are defined in YAML with 4 explicit node types: `task`, `conditional`, `fan_out`, `fan_in`. No new Python job classes (Epoch 4 freeze). See `docs/superpowers/specs/2026-03-16-workflow-loader-yaml-schema-design.md`.

---

## Quick Reference: Finding Severity

| Severity | When to Use |
|----------|-------------|
| **CRITICAL** | SQL injection, raw DB connections, caught ContractViolationError, circular import, core->services import |
| **HIGH** | Backward compat fallback, direct os.environ, exception swallowing, wrong config singleton, new Python job class |
| **MEDIUM** | Missing handler return contract, tuple row access, missing NULL check, standalone ALTER statement |
| **LOW** | Wrong date format, missing file header, naming inconsistency |
