# Architecture Review - Interface Contracts & Enforcement Gaps

**Date**: 15 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Comprehensive analysis of architectural vision vs reality for future refactoring
**Status**: Active - Use this for planning enforcement and documentation improvements

---

## Executive Summary

### Current State Assessment

**Architectural Goal:** Strong types, fail-fast/loud, strict requirements to make expanding functionality easier with clear rules.

**Reality:**
- ✅ Composition patterns work well (CoreMachine, repositories, handlers)
- ✅ Duck typing enables flexible dependency injection
- ❌ **No interface enforcement** - job classes have implicit contracts discovered at runtime
- ❌ **Scattered requirements** - what methods a job needs is spread across 3+ files
- ❌ **Misleading documentation** - describes unused ABC pattern, not actual Pattern B

**Impact:** Creating new job types requires trial-and-error deployment cycles to discover missing methods (opposite of fail-fast).

### Key Findings

1. **Unused ABC exists** - `jobs/workflow.py` defines Workflow ABC but zero jobs use it
2. **Implicit job interface** - 5 required methods, no enforcement, discovered via AttributeError
3. **Documentation mismatch** - Docs say use Pydantic Stage objects, reality uses plain dicts
4. **No fail-fast** - Missing methods discovered one at a time during HTTP requests, not at startup
5. **Composition works** - Dependency injection and composition patterns are correctly implemented

### Priority Recommendations

**P0 - Critical (Before Next Job Type):**
1. Document required job methods in ARCHITECTURE_REFERENCE.md with checklist
2. Add inline comments to `submit_job.py` explaining contract expectations

**P1 - High (Next Sprint):**
1. Create minimal `JobBase` ABC enforcing interface contract
2. Update all 10 jobs to inherit from ABC
3. Test that missing methods cause import-time errors

**P2 - Medium (Next Month):**
1. Remove or fix unused `jobs/workflow.py` ABC
2. Create job template generator script
3. Add automated compliance tests

---

## Architectural Vision vs Reality

### EPOCH 4 Intended Design (From Documentation)

**Source:** `docs/architecture/core_machine.md`, `docs/epoch/EPOCH4_IMPLEMENTATION.md`

**Vision:**
- Job-specific code as pure declarative instructions
- All orchestration machinery in CoreMachine
- Pydantic models throughout for type safety
- Abstract Base Classes defining clear contracts
- Fail-fast error detection

**Example from docs:**
```python
class HelloWorldWorkflow(Workflow):  # Inherits from ABC
    def define_stages(self) -> List[Stage]:  # Returns Pydantic Stage objects
        return [Stage(stage_num=1, stage_name="greeting", ...)]
```

### Actual Implementation (Pattern B - What 10 Jobs Use)

**Reality:**
- ✅ Jobs ARE declarative (stages + task creation logic)
- ✅ CoreMachine handles orchestration
- ✅ Pydantic used at boundaries (TaskDefinition, TaskResult, JobRecord)
- ❌ NO ABC inheritance (all jobs inherit from `object`)
- ❌ Plain dicts for stages (NOT Pydantic Stage objects)
- ❌ Duck-typed interface (no enforcement)

**Actual pattern:**
```python
class HelloWorldJob:  # No inheritance!
    job_type: str = "hello_world"
    stages: List[Dict[str, Any]] = [{"number": 1, ...}]  # Plain dicts

    @staticmethod
    def create_tasks_for_stage(...): ...  # Required but not enforced
```

### Specific Contradictions

| Documentation Says | Reality Is | Impact |
|-------------------|-----------|--------|
| Inherit from Workflow ABC | No inheritance (`object` base) | No compile-time checking |
| Use `List[Stage]` Pydantic models | Use `List[Dict[str, Any]]` | Documentation misleading |
| ABC enforces interface | Duck typing, runtime errors | Fail-late, not fail-fast |
| Defined in `jobs/workflow.py` | Defined by `submit_job.py` calls | Contract scattered |

---

## Interface Contract Analysis

### Job Classes (Pattern B)

#### Expected Interface (What Jobs Must Have)

**Class Attributes:**
- `job_type: str` - Unique identifier for job type
- `description: str` - Human-readable description
- `stages: List[Dict[str, Any]]` - Stage definitions as plain dicts
- `parameters_schema: Dict[str, Any]` - (Optional) Parameter validation schema

**Required Methods (Called by `triggers/submit_job.py`):**
1. `validate_job_parameters(params: dict) -> dict` - Line 171
2. `generate_job_id(params: dict) -> str` - Line 175
3. `create_job_record(job_id: str, params: dict) -> dict` - Line 220
4. `queue_job(job_id: str, params: dict) -> dict` - Line 226

**Required Methods (Called by `core/machine.py`):**
5. `create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list) -> List[dict]` - Line 248

**Optional Methods:**
- `get_batch_threshold() -> int` - Line 647, default: 50
- `aggregate_job_results(context) -> dict` - Line 906, default: simple aggregation

#### Actual Interface Discovery

**Where Requirements Come From:**

1. **triggers/submit_job.py** (Job submission flow):
   ```python
   # Line 171: Expects validate_job_parameters()
   validated_params = controller.validate_job_parameters(job_params)

   # Line 175: Expects generate_job_id()
   job_id = controller.generate_job_id(validated_params)

   # Line 220: Expects create_job_record()
   job_record = controller.create_job_record(job_id, validated_params)

   # Line 226: Expects queue_job()
   queue_result = controller.queue_job(job_id, validated_params)
   ```

2. **core/machine.py** (Task execution flow):
   ```python
   # Line 248: Expects create_tasks_for_stage()
   tasks = job_class.create_tasks_for_stage(
       job_message.stage,
       job_record.parameters,
       job_message.job_id,
       previous_results=previous_results
   )

   # Line 647: Optional get_batch_threshold()
   batch_threshold = workflow.get_batch_threshold()

   # Line 814: Expects stages attribute
   stages = workflow.stages if hasattr(workflow, 'stages') else []

   # Line 906: Optional aggregate_job_results()
   if hasattr(workflow, 'aggregate_job_results'):
       final_result = workflow.aggregate_job_results(context)
   ```

3. **Implicit from examples** (Not documented anywhere):
   - Must be a class (not instance)
   - Methods must be static (no `self`)
   - Must be registered in `jobs/__init__.py` ALL_JOBS dict

#### Current Enforcement: NONE

**Enforcement mechanism:** Duck typing
**Failure mode:** `AttributeError: type object 'JobClass' has no attribute 'method_name'`
**Detection timing:** Runtime, when HTTP request triggers method call
**Discovery pattern:** One method at a time per deploy cycle

**Example from CreateH3BaseJob development:**
1. Created job with `create_tasks_for_stage()` only
2. Deploy → Submit job → Error: Missing `validate_job_parameters`
3. Add method, deploy → Submit job → Error: Missing `generate_job_id`
4. Add method, deploy → Submit job → Error: Missing `create_job_record`
5. Add method, deploy → Submit job → Error: Missing `queue_job`

**Result:** 4+ deploy cycles, 20+ minutes, frustrating experience

#### Proposed Enforcement Approach

**Option A: Minimal ABC (Recommended)**

Create `jobs/base.py`:
```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any

class JobBase(ABC):
    """
    Minimal ABC enforcing job interface contract.
    NO business logic - just method signatures.
    All work done via composition.
    """

    # Class attributes (subclass must define)
    job_type: str
    description: str
    stages: List[Dict[str, Any]]

    @abstractmethod
    @staticmethod
    def validate_job_parameters(params: dict) -> dict:
        """Validate parameters. Called by submit_job.py line 171."""
        pass

    @abstractmethod
    @staticmethod
    def generate_job_id(params: dict) -> str:
        """Generate deterministic job ID. Called by submit_job.py line 175."""
        pass

    @abstractmethod
    @staticmethod
    def create_job_record(job_id: str, params: dict) -> dict:
        """Create database record. Called by submit_job.py line 220."""
        pass

    @abstractmethod
    @staticmethod
    def queue_job(job_id: str, params: dict) -> dict:
        """Queue to Service Bus. Called by submit_job.py line 226."""
        pass

    @abstractmethod
    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        """Generate tasks for stage. Called by CoreMachine line 248."""
        pass
```

**Benefits:**
- ✅ Fail-fast at import time (can't instantiate without all methods)
- ✅ IDE autocomplete works
- ✅ No business logic in ABC (just signatures)
- ✅ Composition patterns unchanged
- ✅ Built-in Python feature (no external tools)

**Migration:**
- Update all 10 jobs: `class HelloWorldJob(JobBase):`
- Estimated effort: 30 minutes
- Risk: Low (only adds enforcement, no behavior change)

---

### Handlers

#### Expected Interface

**Signature:**
```python
def handler_name(task_params: dict) -> dict:
    """
    Execute task logic.

    Args:
        task_params: Task parameters from CoreMachine

    Returns:
        Dict with success status and results
    """
```

**Contract:**
- Must accept single `dict` parameter
- Must return `dict` (CoreMachine converts to TaskResult)
- Should use composition (repositories, services)
- Should log using LoggerFactory

#### Current Enforcement

**Enforcement mechanism:** CoreMachine type checking
**Location:** `core/machine.py` line 397-422
**Detection:** Runtime, when task executes
**Validation:**
```python
raw_result = handler(task_message.parameters)

if isinstance(raw_result, dict):
    result = TaskResult(...)  # Convert to Pydantic
elif isinstance(raw_result, TaskResult):
    result = raw_result
else:
    raise ContractViolationError(
        f"Handler returned {type(raw_result).__name__} instead of dict or TaskResult"
    )
```

**Status:** ✅ Good enforcement - fails fast with clear error

---

### Repositories

#### Expected Interface

**Pattern:** Composition via RepositoryFactory

**Usage:**
```python
from infrastructure.factory import RepositoryFactory

repos = RepositoryFactory.create_repositories()
job_repo = repos['job_repo']
blob_repo = repos['blob_repo']
```

#### Current Enforcement

**Enforcement mechanism:** Factory pattern + dependency injection
**Status:** ✅ Well-implemented
**Pattern to keep:** This is the reference implementation for composition

---

### CoreMachine Orchestration

#### Interface

**CoreMachine expects jobs to provide:**
- `stages` attribute (plain dicts)
- `create_tasks_for_stage()` method
- Optional: `get_batch_threshold()`, `aggregate_job_results()`

**CoreMachine provides:**
- Task queuing (batch or individual)
- Stage completion detection
- Job advancement logic
- Error handling

#### Current Enforcement

**Enforcement mechanism:** Duck typing + `hasattr()` checks
**Location:** `core/machine.py` lines 647, 814, 906
**Detection:** Runtime
**Status:** ⚠️ Partial - uses `hasattr()` for optional methods, but no validation for required methods

**Example:**
```python
# Line 814: Safe check for stages attribute
stages = workflow.stages if hasattr(workflow, 'stages') else []

# Line 906: Safe check for optional method
if hasattr(workflow, 'aggregate_job_results'):
    final_result = workflow.aggregate_job_results(context)
```

---

## Documentation Gaps

### Critical: Missing Docs That Cause Development Errors

#### 1. Job Creation Checklist

**Gap:** No step-by-step guide for creating new job type
**Impact:** Developers guess, make mistakes, waste time in deploy cycles
**Location:** Should be in `docs_claude/ARCHITECTURE_REFERENCE.md`

**What's needed:**
```markdown
### Creating a New Job Type - Checklist

**Prerequisites:**
- [ ] Understand job→stage→task pattern
- [ ] Have handler implementations ready
- [ ] Know which containers/queues to use

**Step-by-step:**
1. [ ] Create `jobs/your_job.py` with class `YourJobClass`
2. [ ] Define class attributes: `job_type`, `description`, `stages`
3. [ ] Implement required methods:
   - [ ] `validate_job_parameters(params)` → dict
   - [ ] `generate_job_id(params)` → str
   - [ ] `create_job_record(job_id, params)` → dict
   - [ ] `queue_job(job_id, params)` → dict
   - [ ] `create_tasks_for_stage(stage, job_params, job_id, previous_results)` → List[dict]
4. [ ] Register in `jobs/__init__.py`:
   - [ ] Import: `from .your_job import YourJobClass`
   - [ ] Add to dict: `"your_job": YourJobClass`
5. [ ] Register handlers in `services/__init__.py`
6. [ ] Test locally: `python3 -m py_compile jobs/your_job.py`
7. [ ] Deploy and test health endpoint
8. [ ] Submit test job and verify execution

**Reference implementations:**
- Simple single-stage: `jobs/create_h3_base.py`
- Multi-stage: `jobs/hello_world.py`
- Complex pipeline: `jobs/process_raster.py`
```

#### 2. Required Job Methods

**Gap:** No documentation of required methods beyond examples
**Impact:** Must read trigger code to discover requirements
**Location:** Should be in `docs_claude/ARCHITECTURE_REFERENCE.md`

**What's needed:** Full method signatures, purposes, who calls them, error handling

#### 3. Stage Dict Structure

**Gap:** No specification of required keys in stage dicts
**Impact:** Unknown what fields CoreMachine expects

**What's needed:**
```markdown
### Stage Dictionary Structure

Required fields:
- `number: int` - Stage number (1-based, sequential)
- `name: str` - Human-readable stage name
- `task_type: str` - Handler function name from services registry

Optional fields:
- `parallelism: str` - "fixed", "dynamic", or "match_previous" (default: "fixed")
- `count: int` - Number of tasks if parallelism="fixed"
- `description: str` - Documentation

Example:
```python
stages = [
    {
        "number": 1,
        "name": "validate",
        "task_type": "validate_raster",
        "parallelism": "fixed",
        "count": 1
    }
]
```

---

### Important: Misleading Docs Point to Wrong Patterns

#### 1. jobs/workflow.py - Unused ABC

**Current state:** File exists, marked as "REFERENCE ONLY (NOT IMPLEMENTED)" in header
**Problem:** Still confusing - why does it exist if unused?
**Impact:** New developers might think they should use it

**Options:**
- **A) Remove entirely** - Cleanest, prevents confusion
- **B) Implement properly** - Make all jobs inherit from it
- **C) Rename to `workflow_reference.py.example`** - Clear it's just documentation

**Recommendation:** Option B (implement) or Option A (remove)

#### 2. docs_claude/ARCHITECTURE_REFERENCE.md - Says Use Pydantic Stage

**Current state:** Shows example with `Stage(...)` Pydantic objects
**Reality:** All 10 jobs use plain dicts
**Impact:** Misleading, developers waste time trying to use Pydantic Stage

**Fix:** Update examples to show plain dicts, explain why

#### 3. Pattern B Not Clearly Defined

**Current state:** "Pattern B" mentioned but not fully documented
**Impact:** Unclear what the official pattern is

**Fix:** Comprehensive Pattern B documentation in ARCHITECTURE_REFERENCE.md

---

### Nice-to-have: Undocumented Optional Behaviors

#### 1. get_batch_threshold()

**Used by:** `core/machine.py` line 647
**Default:** 50 (if method doesn't exist)
**Documented:** No

**Add to docs:** Jobs can override batch threshold for high-volume scenarios

#### 2. aggregate_job_results()

**Used by:** `core/machine.py` line 906
**Default:** Simple aggregation from task results
**Documented:** No

**Add to docs:** Jobs can customize final result aggregation

#### 3. parameters_schema

**Used by:** Examples show it, but nothing enforces it
**Purpose:** Self-documenting parameter structure
**Documented:** Partially

**Add to docs:** Recommended but not required, format specification

---

## Enforcement Gaps

### Job Interface Contract

**Current enforcement:** None (duck typing)
**Failure mode:** `AttributeError` at runtime
**Detection timing:** When HTTP request triggers missing method
**Discovery pattern:** One error at a time

**Proposed enforcement:**
```python
# Option A: Minimal ABC (jobs/base.py)
class JobBase(ABC):
    @abstractmethod
    @staticmethod
    def validate_job_parameters(params): pass
    # ... etc

# Usage:
class YourJob(JobBase):  # Inherit
    # Must implement all abstract methods or Python raises TypeError
```

**Benefits:**
- Fail-fast at import time
- Clear error message listing ALL missing methods
- IDE support
- No runtime surprises

**Implementation:**
1. Create `jobs/base.py` with `JobBase(ABC)`
2. Update 10 jobs to inherit: `class HelloWorldJob(JobBase):`
3. Test by removing method - should fail at import
4. Update docs to reference ABC as contract

**Estimated effort:** 1 hour
**Risk:** Low (adds enforcement, no behavior change)

---

### Handler Return Type

**Current enforcement:** ✅ Good
**Location:** `core/machine.py` line 397-422
**Method:** Type checking + ContractViolationError

**Keep as-is** - this is working correctly

---

### Stage Dict Structure

**Current enforcement:** None (implicit from usage)
**Failure mode:** KeyError or unexpected behavior
**Detection timing:** Runtime when CoreMachine reads stage

**Proposed enforcement:**

**Option 1: Pydantic validation at import**
```python
# jobs/__init__.py
from pydantic import BaseModel, Field

class StageSchema(BaseModel):
    number: int = Field(ge=1)
    name: str
    task_type: str
    parallelism: str = "fixed"
    count: int = Field(default=1, ge=1)

# Validate all job stages at import
for job_type, job_class in ALL_JOBS.items():
    for stage in job_class.stages:
        try:
            StageSchema(**stage)  # Validates structure
        except Exception as e:
            raise ValueError(f"Job {job_type} has invalid stage: {e}")
```

**Option 2: Document and trust**
- Document required structure
- Let runtime errors catch issues
- Simpler, less overhead

**Recommendation:** Option 2 for now, Option 1 if problems arise

---

### Registry Validation

**Current enforcement:** Basic dict lookup
**Failure mode:** `KeyError` if job not registered
**Detection timing:** When job submitted

**Proposed enhancement:**
```python
# jobs/__init__.py
from jobs.base import JobBase  # If we create ABC

# Validate at import time
for job_type, job_class in ALL_JOBS.items():
    # Check it's actually a class
    if not isinstance(job_class, type):
        raise TypeError(f"ALL_JOBS['{job_type}'] must be a class, got {type(job_class)}")

    # Check it has required attributes
    if not hasattr(job_class, 'job_type'):
        raise AttributeError(f"Job class {job_class.__name__} missing 'job_type' attribute")

    # Check job_type matches key
    if job_class.job_type != job_type:
        raise ValueError(f"Job {job_class.__name__}.job_type = '{job_class.job_type}' "
                        f"doesn't match registry key '{job_type}'")
```

**Benefits:**
- Catches registration mistakes at import
- Clear error messages
- No runtime surprises

**Estimated effort:** 15 minutes
**Risk:** None

---

## Concrete Action Items

### P0 - Critical (Before Next Job Type)

#### Task 1: Document Required Job Methods
**What:** Add complete job creation section to `docs_claude/ARCHITECTURE_REFERENCE.md`
**Why:** Prevent CreateH3BaseJob experience from repeating
**Effort:** 30 minutes
**Success criteria:**
- Checklist covers all 5 required methods
- Includes method signatures
- Links to reference implementations
- Explains what calls each method and when

**Dependencies:** None

#### Task 2: Add Inline Contract Comments
**What:** Add comments to `triggers/submit_job.py` explaining contract
**Why:** Make expectations clear when reading trigger code
**Effort:** 15 minutes
**Success criteria:**
```python
# INTERFACE CONTRACT: All jobs must implement validate_job_parameters()
# This is called to validate parameters before job creation
# Must return dict with validated/normalized parameters
validated_params = controller.validate_job_parameters(job_params)
```

**Dependencies:** None

---

### P1 - High (Next Sprint)

#### Task 3: Create Minimal JobBase ABC
**What:** Create `jobs/base.py` with `JobBase(ABC)` defining required methods
**Why:** Enforce interface contract, enable fail-fast
**Effort:** 30 minutes
**File:** New file `jobs/base.py`
**Success criteria:**
- ABC defines all 5 required methods as abstract
- No business logic in ABC
- Clear docstrings explaining each method
- Reference to callers (submit_job.py, machine.py)

**Dependencies:** None

**Testing:**
1. Create test job without all methods
2. Should get `TypeError: Can't instantiate abstract class` at import
3. Lists ALL missing methods in error

#### Task 4: Migrate 10 Jobs to ABC
**What:** Update all jobs to inherit from `JobBase`
**Why:** Apply enforcement consistently
**Effort:** 30 minutes (10 jobs × 3 minutes each)
**Changes per job:**
1. Add import: `from jobs.base import JobBase`
2. Change: `class JobName:` → `class JobName(JobBase):`
3. Verify all methods present (ABC will enforce)

**Jobs to update:**
1. `jobs/hello_world.py`
2. `jobs/create_h3_base.py`
3. `jobs/generate_h3_level4.py`
4. `jobs/container_summary.py`
5. `jobs/container_list.py`
6. `jobs/stac_catalog_container.py`
7. `jobs/stac_catalog_vectors.py`
8. `jobs/ingest_vector.py`
9. `jobs/validate_raster_job.py`
10. `jobs/process_raster.py`

**Success criteria:**
- All jobs still work (no behavior change)
- Removing a method causes import error
- Error message lists missing methods

**Dependencies:** Task 3 (JobBase created)

#### Task 5: Update Documentation to Reference ABC
**What:** Update all job-related docs to mention ABC contract
**Why:** Documentation matches reality
**Effort:** 20 minutes
**Files to update:**
- `docs_claude/ARCHITECTURE_REFERENCE.md` - Add ABC section
- `docs_claude/CLAUDE_CONTEXT.md` - Update Pattern B description
- `CLAUDE.md` - Update job creation guidance

**Success criteria:**
- Docs say "inherit from JobBase"
- Examples show inheritance
- Checklist includes inheritance step

**Dependencies:** Task 3, 4 (ABC exists and jobs use it)

#### Task 6: Test Fail-Fast Behavior
**What:** Create test that verifies missing methods cause import errors
**Why:** Validate enforcement works
**Effort:** 15 minutes
**Test approach:**
```python
# test_job_enforcement.py
def test_missing_method_fails_at_import():
    # Create job class missing a method
    code = """
from jobs.base import JobBase

class TestJob(JobBase):
    job_type = "test"
    stages = []

    # Missing validate_job_parameters, etc.
"""

    # Should raise TypeError at class definition
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        exec(code)
```

**Success criteria:**
- Test catches missing methods
- Error lists ALL missing methods
- Test runs in CI

**Dependencies:** Task 3, 4

---

### P2 - Medium (Next Month)

#### Task 7: Handle Unused workflow.py
**What:** Either remove, implement, or rename `jobs/workflow.py`
**Why:** Eliminate confusion about which pattern to use
**Effort:** 30 minutes
**Options:**
- **A) Remove file** - Since all jobs now use JobBase
- **B) Rename to `workflow_reference.py.example`** - Keep as documentation
- **C) Leave as-is** - Already marked as unused in comments

**Recommendation:** Option A (remove) after Task 4 complete

**Dependencies:** Task 4 (all jobs migrated to JobBase)

#### Task 8: Create Job Template Generator
**What:** Script to scaffold new job with all required methods
**Why:** Make job creation trivial
**Effort:** 1 hour
**Usage:**
```bash
python scripts/create_job.py my_new_job "My job description"

# Creates:
# - jobs/my_new_job.py (with all methods stubbed)
# - services/handler_my_new_job.py (handler stub)
# - Adds to jobs/__init__.py and services/__init__.py automatically
```

**Dependencies:** Task 3, 4 (ABC established as pattern)

#### Task 9: Registry Validation
**What:** Add validation to `jobs/__init__.py` to check registry consistency
**Why:** Catch registration mistakes at import time
**Effort:** 15 minutes
**Implementation:** See "Registry Validation" in Enforcement Gaps section

**Dependencies:** None

#### Task 10: Audit Pattern B References
**What:** Search all docs for "Pattern B" and ensure accuracy
**Why:** Terminology should be clear and consistent
**Effort:** 30 minutes

**Dependencies:** Task 5 (docs updated)

---

### P3 - Long-term (Future)

#### Task 11: Consider Full Pydantic Stage Models
**What:** Evaluate switching from `List[Dict]` to `List[Stage]`
**Why:** Original EPOCH 4 vision, stronger type safety
**Effort:** 2-4 hours (analysis + implementation if decided)
**Trade-offs:**
- ✅ Stronger typing
- ✅ Pydantic validation
- ❌ More verbose
- ❌ Migration effort for 10 jobs
- ❌ Might be over-engineering

**Decision criteria:**
- Has plain dict approach caused problems?
- Would Pydantic Stage catch real bugs?
- Is added complexity worth it?

**Dependencies:** Task 4 (jobs on ABC first)

#### Task 12: Automated Compliance Tests
**What:** CI tests that verify all jobs comply with contract
**Why:** Continuous validation
**Effort:** 1 hour
**Tests:**
- All jobs inherit from JobBase
- All jobs registered in ALL_JOBS
- job_type matches registry key
- No duplicate job_types
- All handlers registered

**Dependencies:** Task 3, 4, 9

#### Task 13: Performance Evaluation
**What:** Benchmark ABC vs plain classes
**Why:** Ensure enforcement doesn't impact performance
**Effort:** 1 hour
**Metrics:**
- Import time
- Job submission time
- Memory usage

**Dependencies:** Task 4

---

## Reference Examples

### Good Examples to Follow

#### 1. HelloWorldJob - Complete Job Implementation
**Location:** `jobs/hello_world.py`
**Why reference:** Shows all 5 required methods implemented correctly
**Use for:** Template when creating new jobs

#### 2. CoreMachine - Composition Pattern
**Location:** `core/machine.py`
**Why reference:** Excellent use of dependency injection and composition
**Pattern:**
```python
class CoreMachine:
    def __init__(self, all_jobs, all_handlers, state_manager, config):
        self.jobs_registry = all_jobs  # Composed
        self.handlers_registry = all_handlers  # Composed
        self.state_manager = state_manager  # Composed
        self.config = config  # Composed
```
**Use for:** How to compose dependencies without inheritance

#### 3. RepositoryFactory - Dependency Injection
**Location:** `infrastructure/factory.py`
**Why reference:** Clean factory pattern for creating dependencies
**Use for:** Creating new factories or understanding DI pattern

#### 4. Handler Pattern - Composition in Practice
**Location:** Any `services/handler_*.py`
**Example:** `services/handler_h3_base.py`
**Pattern:**
```python
def handler(task_params: dict) -> dict:
    # Compose Pydantic model for validation
    request = H3BaseGridRequest(**task_params)

    # Compose repositories
    repos = RepositoryFactory.create_repositories()

    # Compose service
    service = H3GridService(repos['duckdb_repo'], repos['blob_repo'])

    # Do work via composed objects
    result = service.generate_grid(...)
```
**Use for:** How to write handlers that compose dependencies

---

### Bad Examples to Avoid

#### 1. Unused Workflow ABC
**Location:** `jobs/workflow.py`
**Problem:** Exists but isn't used, causes confusion
**Lesson:** Remove unused abstractions or implement them

#### 2. Scattered Interface Requirements
**Location:** Requirements split between `submit_job.py`, `machine.py`, examples
**Problem:** No single source of truth
**Lesson:** Centralize interface definitions

#### 3. Duck-Typed Job Interface (Current)
**Problem:** No enforcement, discover missing methods at runtime
**Lesson:** Use ABC or Protocol for contracts, not duck typing

---

### Anti-patterns Identified

#### 1. Silent Interface Requirements
**Pattern:** Code calls methods without documenting or enforcing they exist
**Example:** `controller.validate_job_parameters()` with no ABC requiring it
**Fix:** Create ABC enforcing required methods

#### 2. Documentation Divergence
**Pattern:** Docs describe one pattern, code uses another
**Example:** Docs say use Pydantic Stage, code uses plain dicts
**Fix:** Update docs to match reality or change code to match docs

#### 3. Runtime Discovery of Interface
**Pattern:** Learn what methods are needed by triggering AttributeError
**Example:** CreateH3BaseJob took 4 deploy cycles to find all methods
**Fix:** Fail-fast at import time with ABC

---

## Migration Patterns

### Pattern: Adding ABC to Existing Job

**Before:**
```python
class HelloWorldJob:
    job_type = "hello_world"
    stages = [...]
```

**After:**
```python
from jobs.base import JobBase

class HelloWorldJob(JobBase):
    job_type = "hello_world"
    stages = [...]
```

**Steps:**
1. Add import: `from jobs.base import JobBase`
2. Add inheritance: `(JobBase)` to class definition
3. Verify all methods present
4. No other changes needed

**Testing:**
1. Import job module: `from jobs.hello_world import HelloWorldJob`
2. Should succeed without errors
3. Remove a method temporarily, should get `TypeError`
4. Restore method

---

### Pattern: Creating New Job with ABC

**Template:**
```python
"""
Your Job Description

Author: Name
Date: DATE
"""

from typing import List, Dict, Any
from jobs.base import JobBase


class YourJob(JobBase):
    """Your job description."""

    # Required attributes
    job_type: str = "your_job"
    description: str = "What this job does"
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "stage_name",
            "task_type": "handler_name",
            "parallelism": "fixed",
            "count": 1
        }
    ]

    @staticmethod
    def validate_job_parameters(params: dict) -> dict:
        """Validate parameters."""
        # Validation logic
        return params

    @staticmethod
    def generate_job_id(params: dict) -> str:
        """Generate deterministic job ID."""
        import hashlib, json
        id_str = f"{JobBase.job_type}:{json.dumps(params, sort_keys=True)}"
        return hashlib.sha256(id_str.encode()).hexdigest()

    @staticmethod
    def create_job_record(job_id: str, params: dict) -> dict:
        """Create database record."""
        from infrastructure import RepositoryFactory
        from core.models import JobRecord, JobStatus

        job_record = JobRecord(
            job_id=job_id,
            job_type="your_job",
            parameters=params,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=len(YourJob.stages),
            stage_results={},
            metadata={"description": YourJob.description}
        )

        repos = RepositoryFactory.create_repositories()
        repos['job_repo'].create_job(job_record)
        return {"job_id": job_id, "status": "queued"}

    @staticmethod
    def queue_job(job_id: str, params: dict) -> dict:
        """Queue to Service Bus."""
        from infrastructure.service_bus import ServiceBusRepository
        from core.schema.queue import JobQueueMessage
        from config import get_config
        import uuid

        message = JobQueueMessage(
            job_id=job_id,
            job_type="your_job",
            stage=1,
            parameters=params,
            message_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4())
        )

        config = get_config()
        service_bus = ServiceBusRepository(
            connection_string=config.get_service_bus_connection(),
            queue_name=config.jobs_queue_name
        )
        service_bus.send_message(message.model_dump_json())

        return {"queued": True, "queue_type": "service_bus"}

    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        """Generate tasks for stage."""
        if stage != 1:
            raise ValueError(f"Invalid stage {stage}")

        return [
            {
                "task_id": f"{job_id[:8]}-task-{i}",
                "task_type": "handler_name",
                "parameters": {}
            }
            for i in range(1)  # Adjust count
        ]
```

**Registration:**
```python
# jobs/__init__.py
from .your_job import YourJob

ALL_JOBS = {
    # ... existing jobs ...
    "your_job": YourJob,
}
```

---

## Future Claude Instructions

### How to Use This Document

**When starting architectural work:**
1. Read Executive Summary for current state
2. Identify which P0/P1/P2 tasks remain
3. Check dependencies before starting
4. Follow testing strategy for validation

**When creating enforcement:**
1. Review "Enforcement Gaps" section
2. Check "Proposed Enforcement Approach" for each area
3. Use migration patterns for existing code
4. Test fail-fast behavior before deployment

**When updating documentation:**
1. Check "Documentation Gaps" section
2. Address Critical gaps first
3. Use reference examples as templates
4. Verify docs match actual code behavior

**When refactoring:**
1. Check "Anti-patterns Identified"
2. Use "Good Examples to Follow"
3. Avoid "Bad Examples"
4. Update this document when patterns change

---

### Order of Operations for Refactoring

**Phase 1: Documentation (Low Risk, High Value)**
1. Document required job methods (P0 Task 1)
2. Add inline contract comments (P0 Task 2)
3. Update existing docs (P1 Task 5)

**Phase 2: Enforcement (Medium Risk, High Value)**
1. Create JobBase ABC (P1 Task 3)
2. Migrate all jobs to ABC (P1 Task 4)
3. Test fail-fast behavior (P1 Task 6)
4. Add registry validation (P2 Task 9)

**Phase 3: Tooling (Low Risk, Medium Value)**
1. Create job template generator (P2 Task 8)
2. Add automated compliance tests (P3 Task 12)

**Phase 4: Cleanup (Low Risk, Low Value)**
1. Handle unused workflow.py (P2 Task 7)
2. Audit Pattern B references (P2 Task 10)

**Phase 5: Optimization (Optional)**
1. Evaluate Pydantic Stage models (P3 Task 11)
2. Performance evaluation (P3 Task 13)

---

### Testing Strategy

#### Unit Tests
```python
# test_job_base_enforcement.py
def test_job_without_required_method_fails():
    """Verify ABC enforcement works"""
    with pytest.raises(TypeError):
        class BadJob(JobBase):
            job_type = "bad"
            stages = []
            # Missing required methods

def test_job_with_all_methods_succeeds():
    """Verify complete job can be instantiated"""
    class GoodJob(JobBase):
        job_type = "good"
        stages = []

        @staticmethod
        def validate_job_parameters(params): return params
        # ... all other methods

    # Should not raise
    assert GoodJob.job_type == "good"
```

#### Integration Tests
```python
def test_job_submission_end_to_end():
    """Test job can be submitted and executed"""
    # Submit job via HTTP
    # Verify job created in database
    # Verify tasks queued
    # Verify execution completes
```

#### Smoke Tests After Deployment
```bash
# Verify health endpoint
curl https://rmhgeoapibeta.../api/health

# Submit test job
curl -X POST https://rmhgeoapibeta.../api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"n": 2}'

# Check job status
curl https://rmhgeoapibeta.../api/jobs/status/{JOB_ID}
```

---

### Rollback Plan

**If ABC enforcement causes issues:**

1. **Immediate rollback:**
   ```python
   # jobs/base.py
   # Comment out @abstractmethod decorators
   # Jobs will still inherit but won't be enforced
   ```

2. **Restore duck typing:**
   ```python
   # jobs/__init__.py
   # Remove JobBase imports
   # Remove inheritance from all jobs
   # Deploy - back to original pattern
   ```

3. **Document issue:**
   - Add to this document under "Issues Encountered"
   - Note what broke and why
   - Propose alternative approach

---

### Success Metrics

#### Before Refactor (Current State)

| Metric | Value | Status |
|--------|-------|--------|
| Time to create new job | Unknown (trial and error) | ❌ Poor |
| Deploy cycles for interface issues | 3-5 cycles | ❌ Poor |
| Documentation accuracy | ~60% (major gaps) | ❌ Poor |
| Fail-fast score | 2/10 (most errors at runtime) | ❌ Poor |
| Developer confidence | Low (guessing required methods) | ❌ Poor |

#### After Refactor (Target State)

| Metric | Value | Status |
|--------|-------|--------|
| Time to create new job | <2 hours with checklist | ✅ Good |
| Deploy cycles for interface issues | 0 (caught at import) | ✅ Good |
| Documentation accuracy | >95% (matches reality) | ✅ Good |
| Fail-fast score | 9/10 (only business logic errors at runtime) | ✅ Good |
| Developer confidence | High (clear contract, IDE support) | ✅ Good |

#### Measurement Approach

**Before metrics (baseline):**
- Time next developer to create job from scratch
- Count deploy cycles needed to get interface right
- Survey: "On a scale 1-10, how confident are you about job requirements?"

**After metrics (validation):**
- Repeat measurements with same criteria
- Should see significant improvement
- If not, analyze why and adjust approach

---

## Document Maintenance

**Update this document when:**
- New architectural patterns emerge
- Major refactors complete (especially P1 tasks)
- New enforcement mechanisms added
- Documentation gaps filled
- Job interface changes
- Anti-patterns discovered

**Review frequency:**
- After each P0/P1 task completion
- After each EPOCH
- When onboarding new developers
- When job creation patterns change

**Owner:** Architecture team / Tech lead
**Last updated:** 15 OCT 2025
**Next review:** After P1 tasks complete

**Deprecated when:**
- All enforcement complete
- Documentation 100% accurate
- Patterns stable and well-understood
- No new gaps identified for 3+ months

---

## Appendix: CreateH3BaseJob Case Study

### The Problem (Documented for Posterity)

**Goal:** Create new job type for H3 grid generation
**Date:** 15 OCT 2025
**Developer experience:** Multiple deploy cycles discovering interface requirements

### Discovery Timeline

**Attempt 1:**
- Created job with `create_tasks_for_stage()` only
- Deploy successful
- Submit job → `AttributeError: 'CreateH3BaseJob' has no attribute 'validate_job_parameters'`
- **Time wasted:** 10 minutes (code + deploy + test)

**Attempt 2:**
- Added `validate_job_parameters()`
- Deploy successful
- Submit job → `AttributeError: 'CreateH3BaseJob' has no attribute 'generate_job_id'`
- **Time wasted:** 10 minutes

**Attempt 3:**
- Added `generate_job_id()`
- Deploy successful
- Submit job → `AttributeError: 'CreateH3BaseJob' has no attribute 'create_job_record'`
- **Time wasted:** 10 minutes

**Attempt 4:**
- Added `create_job_record()` and `queue_job()` (looked at HelloWorldJob example)
- Deploy successful
- Would have worked (if not for unrelated import error)
- **Time wasted:** 10 minutes

**Total time:** 40+ minutes discovering interface requirements
**Root cause:** No documentation, no enforcement, duck typing
**Expected with ABC:** 0 minutes - would know all methods at start, error at import if missing

### What Should Have Happened

**With ABC enforcement:**
```python
from jobs.base import JobBase

class CreateH3BaseJob(JobBase):  # Inherit
    # IDE immediately shows: "Class must implement abstract methods:
    # - validate_job_parameters
    # - generate_job_id
    # - create_job_record
    # - queue_job
    # - create_tasks_for_stage"
```

**Developer experience:**
1. See list of required methods in IDE
2. Implement all 5 methods before first deploy
3. Deploy once
4. Works ✅

**Time saved:** 30+ minutes
**Frustration avoided:** High
**Developer confidence:** High (clear requirements)

### Lessons Learned

1. **Duck typing has costs** - Flexibility comes at the price of clarity
2. **Implicit contracts fail** - Requirements should be explicit
3. **Fail-fast matters** - Every deploy cycle is expensive in cloud environments
4. **Good docs aren't enough** - Need enforcement, not just documentation
5. **Examples are insufficient** - Developers shouldn't have to reverse-engineer interface from examples

### Prevention

**Immediate (P0):**
- Document all required methods with checklist
- Would reduce to 1-2 deploy cycles

**Short-term (P1):**
- Implement ABC enforcement
- Would reduce to 0 deploy cycles for interface issues

**Long-term (P2):**
- Job template generator
- Would eliminate even needing to know the methods (auto-generated)

---

**End of ARCHITECTURE_REVIEW.md**
