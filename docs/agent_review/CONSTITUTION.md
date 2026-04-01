# Project Constitution

**Purpose**: Architectural principles and implementation standards that govern ALL Claude interactions with this codebase.

**Last Updated**: 31 MAR 2026

**Sources**: `CLAUDE.md`, `PPT.md`, `docs_claude/DEV_BEST_PRACTICES.md`, `docs_claude/ARCHITECTURE_REFERENCE.md`, `docs_claude/SCHEMA_EVOLUTION.md`

---

# Part I: Constitutional Principles

These principles survive a platform change, a language change, a complete rewrite. They govern *how to think about this system*, not how to write Python. When evaluating a deviation, name the principle — if the principle doesn't apply, the implementation standard may not either.

---

## Preamble: The Nature of This Environment

This is a first-principles design environment. The architect (Robert) is iterating toward correct design, not maintaining a production system that must never break. Bad design gets wrecked and replaced, not accommodated.

Claude's default instinct is to preserve existing behavior, add fallbacks, and avoid breaking changes. **This instinct is wrong here.** Every backward-compatibility shim is a layer of scar tissue protecting a decision that may no longer hold. When something is wrong, the correct action is to fix it and let the breakage surface. The breakage *is the signal* — it shows what depended on the bad design so those things can be fixed too.

Every other principle flows from this. If the system is designed correctly, breaking a bad abstraction improves it. If the system can't tolerate a broken abstraction, the system has a design problem, not a compatibility problem.

---

## Principle 1: Explicit Failure Over Silent Accommodation

When something breaks, fail loudly. Never default missing values. Never try both old and new patterns. Never add a fallback that masks a problem. The breakage is information — silent accommodation destroys that information.

This applies to code, configuration, data contracts, and API responses. If a field is required and missing, that's an error, not a reason to guess.

## Principle 2: Deterministic Materialized Views

Same inputs + same parameters = identical outputs. Every downstream layer is deterministically derived from the layer above it. Bronze is the recovery point. Silver is derived. Gold is derived. STAC is a materialized projection of internal metadata.

This means:
- **Rebuild is always safe** — losing Silver is a re-run, not a disaster
- **No hidden state** — if a result depends on something, that something is an explicit input
- **The source of truth is always upstream** — pgSTAC is not authoritative, internal metadata is

## Principle 3: Unidirectional Data Flow, Mechanically Enforced

Data flows in one direction: Bronze → Silver → Gold. No component writes upstream. This is enforced by mechanism (RBAC, identity permissions), not by convention or human discipline.

- **Bronze** (landing zone): Clients write, ETL reads. Source data preserved.
- **Silver** (derived): ETL writes, Service Layer reads. Re-derivable from Bronze.
- **Gold** (analytics): Feature engineering writes, analytics consumers read.
- **Service Layer**: Reads from Silver. Writes nowhere.

The constitutional requirement is that enforcement is structural. The specific mechanism (RBAC on managed identities, IAM policies, type systems) is an implementation detail.

## Principle 4: Separation of Readiness and Publication

ETL produces ready data. Humans approve visibility. Revocation removes visibility. The pipeline's job ends at readiness, not at publication.

This is a governance boundary between automation and human judgment. The system automates everything up to the decision point, then stops and waits.

## Principle 5: Paired Lifecycles

Every forward path has a reverse path. Build ingest, build unpublish, in the same iteration. Nothing gets created without a known path to remove it.

Implementation Standards SHALL specify how paired lifecycles are verified at code review and by pipeline agents.

## Principle 6: Composable Atomic Units

Handlers are independently testable, independently invocable, and compose into workflows via explicit inputs and outputs. No shared mutable state between handlers. The handler library is a menu; workflows are recipes.

Every unit of work has a uniform interface and communicates through explicit contracts, not side effects.

## Principle 7: Bugs and Business Errors Are Different Things

Programming errors (contract violations, type mismatches, missing fields) crash immediately and loudly. Expected failures (missing resources, validation failures, user errors) are handled gracefully. These two categories are never mixed, never caught in the same handler, never treated with the same severity.

The specific exception class names are implementation details. The principle is that bug errors are always fatal.

## Principle 8: The Database Is the Coordination Layer

Prefer queryable, transactional state over opaque infrastructure. "Show me all running tasks" should be a query, not an API call to a message broker. Coordination state lives where you can SELECT it, inspect it, and debug it with standard tools.

The specific technology (PostgreSQL SKIP LOCKED) is an implementation detail. The principle is that coordination state is transparent and queryable.

## Principle 9: Correctness Under Concurrency by Construction

Concurrent operations must be correct by construction, not by hope. Isolation guarantees are explicit. No handler assumes it is the only writer. Locking strategies, transaction boundaries, and ordering guarantees are declared, not implied.

## Principle 10: Explicit Data Contracts

Inter-handler data flows have explicit, typed contracts. Handlers must not depend on undocumented fields in their inputs and must not produce undocumented fields in their outputs. If it's not in the contract, it doesn't exist.

## Principle 11: Traceable State Changes

Every state change is traceable. Every handler invocation is auditable. If it happened, you can find evidence that it happened. The specific logging format is an implementation detail. The principle is that the system never does something important silently.

## Principle 12: AI-Native Development

This codebase is developed collaboratively with AI agents. Architectural intent must be legible in code and documentation, not carried in human memory alone. Rules must be enforceable by automated review, not just by human judgment.

This Constitution exists because agents need explicit rules to operate autonomously. The principles are written for agents to reason against — not as aspirational values, but as enforceable constraints.

---

# Part II: Governance Framework

## Enforcement Tiers

| Tier | Who | Enforcement |
|------|-----|-------------|
| **Claude Prime** | Main interactive session | Advisory. Warns on deviation, asks for reasoning, proceeds if Robert confirms. |
| **Subagents** | Spawned by Claude Prime | Same as Claude Prime — Robert is present to make judgment calls. |
| **Pipeline Agents** | COMPETE, SIEGE, GREENFIELD, REFLEXION, TOURNAMENT, ADVOCATE | Strict. Every violation is a finding with a severity rating. No deviation clause. |

## Deviation Protocol (Claude Prime and Subagents Only)

When Robert's request would deviate from a principle or standard, Claude Prime must:

1. **Name the principle or standard** — e.g. "This would deviate from Principle 1 (explicit failure over silent accommodation)"
2. **Explain the risk** — what could go wrong, what the rule was designed to prevent
3. **Ask for the reasoning** — "What's driving this deviation?"
4. **Proceed if Robert confirms** — document with a code comment: `# DEVIATION: Principle N / Standard X.X — [reason]`

The goal is conscious deviation, not blind compliance. Robert is the architect. The Constitution makes deviation visible, not impossible.

## Major Questions Doctrine (All Tiers)

*Paraphrasing the Supreme Court: if Robert wanted agents to make fundamental architecture changes, he would explicitly say so.*

When an agent encounters a bug, finding, or improvement opportunity, the decision tree is:

1. **Straightforward fix that respects existing principles and architecture** → Proceed.
2. **Fix that would violate a principle or challenge an architectural decision** → **Stop.** Document the issue, explain why a straightforward fix isn't available, and defer the decision to Robert.

Agents do not have implied authority to make high-level design changes. The absence of a prohibition is not authorization. If a fix requires changing how the system *thinks* — data flow direction, coordination strategy, contract boundaries, governance rules — that decision belongs to the architect, not the agent.

**Applies to all tiers equally.** Pipeline agents (COMPETE, SIEGE, etc.) flag it as a finding with severity and rationale. Claude Prime and subagents raise it in conversation and wait for direction.

**Examples:**

| Scenario | Action |
|----------|--------|
| Handler missing NULL check | Fix it — Standard 6.2 is clear |
| SQL uses f-string | Fix it — Standard 1.2 is clear |
| Fix requires adding a new data flow direction | **Stop** — Principle 3 decision, defer to Robert |
| Bug can only be resolved by changing the handler contract | **Stop** — Principle 10 decision, defer to Robert |
| COMPETE finding suggests replacing DB polling with event-driven | **Stop** — Principle 8 decision, defer to Robert |
| Workaround needs a backward-compat shim | **Stop** — Principle 1 decision, defer to Robert |

## Pipeline Agent Mappings

**COMPETE** (Alpha/Beta/Gamma/Delta):
- Alpha (architecture scope) -> Principles 2-6, Standards 4, 5, 8, 9
- Beta (correctness scope) -> Principles 1, 7-11, Standards 1, 2, 3, 6, 7
- Gamma (blind spot finder) -> All principles and standards

**REFLEXION** (R/F/P/J):
- Agent F -> Principles 1, 7, 9, Standards 1, 2, 3, 6
- Agent P -> Principles 1, 6, 7, Standards 1, 3

**GREENFIELD** (S/A/C/O/M/B/V):
- Agent C (Critic) -> All principles (finds spec gaps)
- Agent B (Builder) -> Principles 1, 6, 7, 10, Standards 1, 2, 3, 4, 6
- Agent V (Validator) -> All principles and standards (blind review)

---

# Part III: Implementation Standards

These are the statutory rules for the current DDHGeo implementation. They implement the constitutional principles using specific technologies, patterns, and class names. They change as the implementation evolves.

Each standard references the principle(s) it implements.

---

## Standard 1: Zero-Tolerance Rules (Principles 1, 7)

These are CRITICAL violations. Any occurrence is a finding.

### 1.1 No Backward Compatibility Fallbacks

Fail explicitly. Never create fallbacks that mask breaking changes. *Implements Principle 1.*

```python
# VIOLATION
job_type = entity.get('job_type') or 'default_value'

# CORRECT
job_type = entity.get('job_type')
if not job_type:
    raise ValueError("job_type is required field")
```

### 1.2 SQL Must Use `sql.SQL` Composition -- Never F-Strings

All SQL must use `psycopg.sql.SQL()` and `sql.Identifier()`. F-strings in SQL are injection vulnerabilities.

```python
# VIOLATION
cur.execute(f"SELECT * FROM {schema}.{table} WHERE id = '{id}'")

# CORRECT
cur.execute(
    sql.SQL("SELECT * FROM {}.{} WHERE id = %s").format(
        sql.Identifier(schema), sql.Identifier(table)
    ), (id,)
)
```

### 1.3 ContractViolationError Must Bubble Up

`ContractViolationError` = programming bug. Never catch it. *Implements Principle 7.*

```python
# VIOLATION
except (ContractViolationError, BusinessLogicError):
    logger.error("Something went wrong")

# CORRECT
except ContractViolationError:
    raise  # Bug! Let it crash.
except BusinessLogicError as e:
    return handle_failure(e)
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

All blob access must derive credentials from `BlobRepository.for_zone()`. Exception: health checks and diagnostics may use independent credentials when justified.

---

## Standard 2: Configuration Access (Principle 1)

### 2.1 AppModeConfig Is Separate From AppConfig

`get_config()` returns `AppConfig`. `get_app_mode_config()` returns `AppModeConfig`. Different singletons.

### 2.2 Never Access `os.environ` in Service Code

All env var access goes through the config layer.

### 2.3 Lazy Imports in Azure Functions Handlers

Azure Functions loads modules before env vars are ready. Infrastructure imports go inside handlers.

---

## Standard 3: Error Handling (Principles 1, 7, 11)

### 3.1 Two Error Categories -- Never Mix

| Type | Meaning | Action |
|------|---------|--------|
| `ContractViolationError` | Programming bug | Let bubble up |
| `BusinessLogicError` | Expected failure | Catch and handle |

### 3.2 Handler Return Contract

All task handlers MUST return `{"success": True/False, ...}`. *Implements Principle 6 (uniform interface) and Principle 10 (explicit contracts).*

### 3.3 No Exception Swallowing

Never catch Exception without logging or re-raising. *Implements Principle 11 (traceable state changes).*

---

## Standard 4: Import & Layering Rules (Principle 3)

### 4.1 Import Hierarchy

```
triggers/          <- Top level
services/          <- Business logic
infrastructure/    <- Data access
core/              <- Models, enums
config/            <- Configuration
```

Higher can import lower, not reverse. A `core/` file importing from `services/` is CRITICAL. *Implements Principle 3 (unidirectional flow, applied to code structure).*

### 4.2 Explicit Handler Registration

All handlers in `services/__init__.py` -> `ALL_HANDLERS` dict. No decorator magic.

### 4.3 TYPE_CHECKING Guard for Optional Imports

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from services.approval_service import ApprovalService
```

---

## Standard 5: Platform & Task Dispatch (Principles 4, 8)

### 5.1 Platform Is Decoupled From Execution

Platform submits jobs and exits. Platform NEVER executes jobs or waits for results. *Implements Principle 4 (readiness vs publication boundary).*

### 5.2 Platform Never Writes to Jobs/Tasks Tables

Read-only access to `app.jobs` for status. Only CoreMachine/DAG orchestrator writes.

### 5.3 Task Dispatch Is DB-Polling (v0.10.3.0+)

Workers claim tasks via `SELECT FOR UPDATE SKIP LOCKED`. *Implements Principle 8 (queryable coordination).*

### 5.4 Epoch 4 Freeze Policy

CoreMachine, Python job classes, and Service Bus are in maintenance mode. Bug fixes only. New features must be atomic handlers or YAML workflows. No new Python job classes. **Sunset**: This standard expires when v0.11.0 removes the legacy systems entirely.

---

## Standard 6: Database Patterns (Principles 9, 10)

### 6.1 Cursor Rows Are Dicts, Not Tuples

Access by key, not position. *Implements Principle 10 (explicit contracts).*

### 6.2 Handle NULL/None Explicitly

Never assume columns are non-NULL.

### 6.3 Type Adapters Registered at Connection Level

psycopg3 type adapters registered via `register_type_adapters()` in `infrastructure/db_utils.py`. Never globally or per-cursor.

### 6.4 No Derived Flags — Calculate On The Fly

Never store a boolean that can be derived from existing data. A stored flag is a stale cache that *will* diverge from truth. Compute derived state at query time. *Implements Principle 2 (deterministic materialized views).*

```sql
-- VIOLATION: stored flag that must be maintained on every insert/update/delete
ALTER TABLE releases ADD COLUMN is_latest_version BOOLEAN DEFAULT FALSE;
-- Now every write must flip old rows OFF and new row ON — and concurrent writes corrupt it

-- CORRECT: derive from the data that already exists
SELECT * FROM releases
WHERE version_ordinal = (SELECT MAX(version_ordinal) FROM releases WHERE dataset_id = %s)
```

If you find yourself adding a boolean column whose value is determined by other rows in the same table, you are creating a synchronization problem. Let the query answer the question.

---

## Standard 7: Schema Evolution (Principle 2)

### 7.1 Default Action Is `ensure` (Safe, Preserves Data)

`action=rebuild` destroys all data. Only for fresh dev/test environments.

### 7.2 New Columns Must Have DEFAULT Values

### 7.3 Enum Changes Use Rebuild, Not ALTER

Enum values and DDL changes go into the model code and deploy via `action=rebuild`.

### 7.4 Breaking Changes Require Written Migration Plans

Rename, type change, remove column/table -- never ad hoc.

---

## Standard 8: Naming & Formatting

### 8.1 Military Date Format

All dates: `DD MMM YYYY` (e.g., `19 MAR 2026`).

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

## Standard 9: Job & Task Patterns (Principles 2, 5, 6)

### 9.1 Idempotent Job IDs

`SHA256(job_type + params)`. Same params = same job. *Implements Principle 2 (determinism).*

### 9.2 Mixin Inheritance Order

`JobBaseMixin` MUST come first: `class MyJob(JobBaseMixin, JobBase):`

### 9.3 Azure Functions Folders Require `__init__.py`

Every function folder must have `__init__.py`. Never use `*/` in `.funcignore`.

### 9.4 DAG Workflows Use YAML Definitions

4 node types: `task`, `conditional`, `fan_out`, `fan_in`. No new Python job classes (Standard 5.4). *Implements Principles 5 (paired lifecycles) and 6 (composable units).*

---

## Quick Reference: Finding Severity

| Severity | When to Use |
|----------|-------------|
| **CRITICAL** | SQL injection, raw DB connections, caught ContractViolationError, circular import, core->services import |
| **HIGH** | Backward compat fallback, direct os.environ, exception swallowing, wrong config singleton, new Python job class |
| **MEDIUM** | Missing handler return contract, tuple row access, missing NULL check, standalone ALTER statement |
| **LOW** | Wrong date format, missing file header, naming inconsistency |
