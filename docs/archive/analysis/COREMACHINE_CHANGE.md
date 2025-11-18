# CoreMachine JobBaseMixin Implementation Plan

**Date**: 14 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: Planning Complete - Ready for Implementation
**Risk Level**: LOW (Additive, backward compatible)

---

## 🎯 Executive Summary

**Problem**: Creating a new job type requires ~350 lines of code, but only ~70 lines are job-specific. The remaining 185 lines (53%) are boilerplate that's nearly identical across all jobs.

**Solution**: Implement `JobBaseMixin` to provide default implementations of 4 boilerplate methods, reducing new job creation from **350 lines → 80 lines (77% reduction)**.

**Impact**:
- **Developer Efficiency**: 2 hours → 30 minutes per new job
- **Code Reduction**: 185 lines of boilerplate eliminated per job
- **Maintainability**: Bug fixes to boilerplate apply to all jobs automatically
- **Backward Compatible**: Existing jobs continue working without changes

---

## 📚 Key Concepts Explained

### What is "Boilerplate"?

**Boilerplate** = Repetitive code that must be written over and over with only tiny variations.

In our jobs, these 4 methods are nearly identical across all 5 job types:

1. **validate_job_parameters()** - 30-40 lines per job
   - Same validation pattern (type checking, min/max, defaults)
   - Only parameter names change

2. **generate_job_id()** - 15-20 lines per job
   - **Identical SHA256 hash logic** in every job
   - Only `job_type` string changes

3. **create_job_record()** - 40-50 lines per job
   - **Identical JobRecord creation** in every job
   - Only `job_type`, `total_stages`, and `description` change

4. **queue_job()** - 60-80 lines per job
   - **Identical Service Bus sending** in every job
   - Only `job_type` string changes

**The Problem**: You copy-paste these 185 lines into every new job file, changing only 3-4 values.

### How JobBaseMixin Eliminates Boilerplate

**JobBaseMixin** is a Python class that provides **default implementations** of these 4 methods. When you inherit from it:

```python
class MyJob(JobBase, JobBaseMixin):  # ← Inherit from mixin
    job_type = "my_job"
    stages = [...]
    parameters_schema = {...}  # ← Declarative validation

    # ONLY implement job-specific methods:
    @staticmethod
    def create_tasks_for_stage(...):
        # Your unique logic here

    @staticmethod
    def finalize_job(context):
        # Your unique summary here
```

The mixin **automatically generates** the 4 boilerplate methods using your `job_type`, `stages`, and `parameters_schema` attributes.

---

## 🏗️ Architecture Analysis: Three Options Considered

### Option 1: JobBaseMixin (RECOMMENDED) ✅

**What**: Add mixin class with default implementations

```python
# jobs/mixins.py (NEW - 120 lines, written once)
class JobBaseMixin(ABC):
    # Default implementations of 4 boilerplate methods
    # Uses job's class attributes (job_type, stages, parameters_schema)
```

**Pros**:
- ✅ **Minimal change** - Add 1 file, jobs opt-in via inheritance
- ✅ **Backward compatible** - Existing jobs keep working unchanged
- ✅ **Gradual migration** - Migrate jobs one at a time (test with 1 job first)
- ✅ **Clear abstraction** - Mixin exists ONLY for boilerplate elimination
- ✅ **Easy rollback** - If it doesn't work, just don't use it
- ✅ **No CoreMachine changes** - CoreMachine structure stays clean

**Cons**:
- ❌ **Another abstraction layer** - Now have JobBase + JobBaseMixin
- ❌ **Jobs still contain boilerplate until migrated** - Not automatic

**Impact**:
- New jobs: 350 lines → 80 lines (77% reduction)
- Existing jobs: No change until migrated
- CoreMachine: No changes needed

---

### Option 2: Move Boilerplate to submit_job.py Trigger

**What**: submit_job.py provides default implementations, jobs override only what's unique

**Pros**:
- ✅ No new abstractions - Logic moves to existing trigger file
- ✅ Jobs become simpler - Only implement what's unique

**Cons**:
- ❌ **Trigger becomes bloated** - submit_job.py grows from 400 → 600+ lines
- ❌ **Logic spread across 2 places** - Job methods vs trigger defaults
- ❌ **Harder to test** - Defaults coupled to HTTP trigger
- ❌ **Less discoverable** - Developers must know trigger has defaults

**Rejected**: Relocates the problem instead of solving it cleanly.

---

### Option 3: CoreMachine Structural Change

**What**: CoreMachine only calls `create_tasks_for_stage()` and `finalize_job()`, submit_job.py handles everything else inline

**Pros**:
- ✅ Fewest abstractions - Jobs are pure data + 2 methods
- ✅ Cleanest job files - 350 lines → 50 lines

**Cons**:
- ❌ **Biggest change** - Requires modifying trigger + JobBase contract
- ❌ **All jobs must migrate at once** - Breaking change (no gradual migration)
- ❌ **Trigger grows significantly** - submit_job.py becomes ~600 lines
- ❌ **Less flexible** - Jobs can't override boilerplate methods if needed

**Rejected**: High risk, no gradual migration path.

---

## 🎯 Decision: Option 1 (JobBaseMixin)

### Why JobBaseMixin Is Best

1. **CoreMachine is already clean** - It only calls 2 job methods (`create_tasks_for_stage` + `finalize_job`)
2. **The problem is in jobs, not CoreMachine** - Jobs have too much boilerplate
3. **Mixin doesn't add complexity to CoreMachine** - It simplifies jobs
4. **Jobs are composing correctly** - They just have redundant code

### The Decisive Factor

The "structural change" options would move boilerplate to `submit_job.py`, but that just **relocates the problem** instead of **solving it cleanly**.

JobBaseMixin is **good abstraction** because:
- ✅ Eliminates 800+ lines of duplication across 5 jobs
- ✅ Doesn't couple jobs to CoreMachine (jobs stay independent)
- ✅ Optional (jobs can still implement methods manually if needed)
- ✅ Has ONE clear purpose (eliminate boilerplate)

---

## 📋 Detailed Implementation Plan

### 🚨 CRITICAL: Git Commit Strategy

**Changes to CoreMachine and job architecture are sensitive. Frequent, detailed commits are REQUIRED for debugging and rollback capability.**

**Commit Pattern**:
```bash
# After EACH task completion:
git add -A
git commit -m "Brief description

🔧 Technical details (what was changed)
✅ Status updates (what works now)
⚠️ Known issues (what's still broken or needs testing)

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"

# Work on dev branch, merge to master when stable
git checkout dev  # ← Work here
# ... make changes, commit frequently ...
git checkout master
git merge dev  # ← Only when fully tested
```

**Why This Matters**:
- Detailed git history shows exactly what broke and when
- Easy rollback to last working state if something fails
- Clear debugging trail for future issues

---

### Phase 1: Create JobBaseMixin (2-3 hours)

**Goal**: Implement mixin with default implementations of 4 boilerplate methods

**File**: `jobs/mixins.py` (NEW - ~150 lines)

**Tasks**:

#### Task 1.1: Create mixins.py skeleton (30 min)
```python
# jobs/mixins.py
"""
JobBaseMixin - Default Implementations for Job Boilerplate

Provides default implementations of 4 repetitive methods:
1. validate_job_parameters() - Schema-based validation
2. generate_job_id() - SHA256 hash generation
3. create_job_record() - JobRecord creation + DB persistence
4. queue_job() - Service Bus message sending

Jobs inherit this mixin and only implement:
- create_tasks_for_stage() - Job-specific task generation
- finalize_job() - Job-specific summary

Author: Robert and Geospatial Claude Legion
Date: 14 NOV 2025
"""

from abc import ABC
from typing import Dict, Any
import hashlib
import json
import uuid

class JobBaseMixin(ABC):
    """
    Mixin providing default implementations of JobBase methods.

    Jobs only override what's unique (create_tasks_for_stage, finalize_job).

    Required class attributes:
        job_type: str - Unique job identifier
        description: str - Human-readable description
        stages: List[Dict] - Stage definitions
        parameters_schema: Dict - Parameter validation schema

    Usage:
        class MyJob(JobBase, JobBaseMixin):
            job_type = "my_job"
            stages = [...]
            parameters_schema = {...}

            @staticmethod
            def create_tasks_for_stage(...):
                # Your unique logic here
    """

    # Subclasses MUST set these attributes
    job_type: str
    description: str
    stages: list
    parameters_schema: dict
```

**Commit after this task**:
```bash
git add jobs/mixins.py
git commit -m "Add JobBaseMixin skeleton with docstrings

🔧 Created jobs/mixins.py with class structure
✅ Documented required class attributes
⏳ Method implementations pending

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

#### Task 1.2: Implement validate_job_parameters() (45 min)

**Schema-based validation using `parameters_schema` attribute**

```python
@classmethod
def validate_job_parameters(cls, params: dict) -> dict:
    """
    Default parameter validation using parameters_schema.

    Override for complex validation logic.

    Schema format:
        {
            'param_name': {
                'type': 'int'|'str'|'float'|'bool',
                'required': True|False,
                'default': <value>,
                'min': <number>,  # For int/float
                'max': <number>,  # For int/float
                'allowed': [...]  # For str (enum-like)
            }
        }

    Example:
        parameters_schema = {
            'dataset_id': {'type': 'str', 'required': True},
            'resolution': {'type': 'int', 'default': 10, 'min': 1, 'max': 100},
            'format': {'type': 'str', 'default': 'COG', 'allowed': ['COG', 'GeoTIFF']}
        }

    Returns:
        Validated parameters with defaults applied

    Raises:
        ValueError: If validation fails
    """
    from util_logger import LoggerFactory, ComponentType

    logger = LoggerFactory.create_logger(
        ComponentType.CONTROLLER,
        f"{cls.__name__}.validate_job_parameters"
    )

    validated = {}

    for param_name, schema in cls.parameters_schema.items():
        # Get value from params or use default
        value = params.get(param_name, schema.get('default'))

        # Check required
        if value is None and schema.get('required', False):
            raise ValueError(f"Parameter '{param_name}' is required")

        # Skip validation if value is None and not required
        if value is None:
            continue

        # Type validation
        param_type = schema.get('type', 'str')
        if param_type == 'int':
            value = cls._validate_int(param_name, value, schema)
        elif param_type == 'float':
            value = cls._validate_float(param_name, value, schema)
        elif param_type == 'str':
            value = cls._validate_str(param_name, value, schema)
        elif param_type == 'bool':
            value = cls._validate_bool(param_name, value)
        else:
            raise ValueError(f"Unknown type '{param_type}' for parameter '{param_name}'")

        validated[param_name] = value

    logger.debug(f"✅ Parameters validated: {list(validated.keys())}")
    return validated

@staticmethod
def _validate_int(param_name: str, value: Any, schema: dict) -> int:
    """Validate integer parameter."""
    if not isinstance(value, int):
        raise ValueError(
            f"Parameter '{param_name}' must be an integer, got {type(value).__name__}"
        )

    if 'min' in schema and value < schema['min']:
        raise ValueError(
            f"Parameter '{param_name}' must be >= {schema['min']}, got {value}"
        )

    if 'max' in schema and value > schema['max']:
        raise ValueError(
            f"Parameter '{param_name}' must be <= {schema['max']}, got {value}"
        )

    return value

@staticmethod
def _validate_float(param_name: str, value: Any, schema: dict) -> float:
    """Validate float parameter."""
    if not isinstance(value, (int, float)):
        raise ValueError(
            f"Parameter '{param_name}' must be a number, got {type(value).__name__}"
        )

    value = float(value)

    if 'min' in schema and value < schema['min']:
        raise ValueError(
            f"Parameter '{param_name}' must be >= {schema['min']}, got {value}"
        )

    if 'max' in schema and value > schema['max']:
        raise ValueError(
            f"Parameter '{param_name}' must be <= {schema['max']}, got {value}"
        )

    return value

@staticmethod
def _validate_str(param_name: str, value: Any, schema: dict) -> str:
    """Validate string parameter."""
    if not isinstance(value, str):
        raise ValueError(
            f"Parameter '{param_name}' must be a string, got {type(value).__name__}"
        )

    if 'allowed' in schema and value not in schema['allowed']:
        raise ValueError(
            f"Parameter '{param_name}' must be one of {schema['allowed']}, got '{value}'"
        )

    return value

@staticmethod
def _validate_bool(param_name: str, value: Any) -> bool:
    """Validate boolean parameter."""
    if not isinstance(value, bool):
        raise ValueError(
            f"Parameter '{param_name}' must be a boolean, got {type(value).__name__}"
        )
    return value
```

**Testing**:
```python
# Test in Python REPL:
from jobs.mixins import JobBaseMixin
from jobs.base import JobBase

class TestJob(JobBase, JobBaseMixin):
    job_type = "test"
    description = "Test"
    stages = []
    parameters_schema = {
        'n': {'type': 'int', 'min': 1, 'max': 100, 'default': 10},
        'name': {'type': 'str', 'required': True}
    }

    @staticmethod
    def create_tasks_for_stage(*args): return []
    @staticmethod
    def finalize_job(*args): return {}

# Should work:
result = TestJob.validate_job_parameters({'name': 'test', 'n': 50})
print(result)  # {'name': 'test', 'n': 50}

# Should apply default:
result = TestJob.validate_job_parameters({'name': 'test'})
print(result)  # {'name': 'test', 'n': 10}

# Should fail (missing required):
try:
    TestJob.validate_job_parameters({'n': 50})
except ValueError as e:
    print(f"Expected error: {e}")
```

**Commit after this task**:
```bash
git add jobs/mixins.py
git commit -m "Implement validate_job_parameters() in JobBaseMixin

🔧 Added schema-based parameter validation
🔧 Support for int, float, str, bool types
🔧 Support for required, default, min, max, allowed constraints
✅ Tested with sample schema (manual testing)
⏳ Other mixin methods pending

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

#### Task 1.3: Implement generate_job_id() (15 min)

**Generic SHA256 hash using job_type + params**

```python
@staticmethod
def generate_job_id(params: dict) -> str:
    """
    Default job ID generation (SHA256 of job_type + params).

    Override if you need custom ID logic (e.g., exclude certain params).

    Args:
        params: Validated job parameters

    Returns:
        SHA256 hash as hex string (64 characters)
    """
    # Create canonical representation
    # Note: cls.job_type is available in @classmethod, but @staticmethod
    # requires passing it via params or making this @classmethod
    # For consistency with JobBase, keeping as @staticmethod and
    # requiring jobs to pass job_type if they override this

    canonical = json.dumps(params, sort_keys=True)
    hash_obj = hashlib.sha256(canonical.encode('utf-8'))
    return hash_obj.hexdigest()
```

**Wait - this won't work as @staticmethod! Need to make it @classmethod:**

```python
@classmethod
def generate_job_id(cls, params: dict) -> str:
    """
    Default job ID generation (SHA256 of job_type + params).

    Override if you need custom ID logic (e.g., exclude certain params).

    Args:
        params: Validated job parameters

    Returns:
        SHA256 hash as hex string (64 characters)

    Example:
        # Default behavior:
        job_id = MyJob.generate_job_id({'dataset_id': 'abc', 'n': 10})

        # Custom override (exclude 'failure_rate' from hash):
        @classmethod
        def generate_job_id(cls, params: dict) -> str:
            hash_params = {k: v for k, v in params.items() if k != 'failure_rate'}
            canonical = json.dumps({
                'job_type': cls.job_type,
                **hash_params
            }, sort_keys=True)
            return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    """
    # Create canonical representation
    canonical = json.dumps({
        'job_type': cls.job_type,  # ← Include job_type in hash
        **params
    }, sort_keys=True)

    # Generate SHA256 hash
    hash_obj = hashlib.sha256(canonical.encode('utf-8'))
    return hash_obj.hexdigest()
```

**⚠️ BREAKING CHANGE ALERT**: This changes method signature from `@staticmethod` to `@classmethod`!

**Solution**: Keep JobBase as `@staticmethod`, but mixin uses `@classmethod`. Python allows this override.

**Testing**:
```python
# Test in Python REPL:
from jobs.mixins import JobBaseMixin
from jobs.base import JobBase

class TestJob(JobBase, JobBaseMixin):
    job_type = "test_job"
    description = "Test"
    stages = []
    parameters_schema = {'n': {'type': 'int', 'default': 10}}

    @staticmethod
    def create_tasks_for_stage(*args): return []
    @staticmethod
    def finalize_job(*args): return {}

# Should be deterministic:
id1 = TestJob.generate_job_id({'n': 10, 'name': 'test'})
id2 = TestJob.generate_job_id({'n': 10, 'name': 'test'})
assert id1 == id2, "Job IDs should be deterministic"

# Should change if params change:
id3 = TestJob.generate_job_id({'n': 20, 'name': 'test'})
assert id1 != id3, "Different params should produce different IDs"

print("✅ generate_job_id() tests passed")
```

**Commit after this task**:
```bash
git add jobs/mixins.py
git commit -m "Implement generate_job_id() in JobBaseMixin

🔧 Added SHA256 hash generation from job_type + params
🔧 Changed to @classmethod to access cls.job_type
✅ Deterministic job ID generation
✅ Tested with sample parameters
⏳ Other mixin methods pending

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

#### Task 1.4: Implement create_job_record() (30 min)

**Generic JobRecord creation + DB persistence**

```python
@classmethod
def create_job_record(cls, job_id: str, params: dict) -> dict:
    """
    Default job record creation.

    Override if you need custom metadata or initialization.

    Args:
        job_id: Generated job ID from generate_job_id()
        params: Validated parameters from validate_job_parameters()

    Returns:
        Job record dict (from JobRecord.model_dump())

    Example override:
        @classmethod
        def create_job_record(cls, job_id: str, params: dict) -> dict:
            # Call parent to get default record
            record_dict = super().create_job_record(job_id, params)

            # Add custom metadata
            record_dict['metadata']['custom_field'] = 'custom_value'

            return record_dict
    """
    from infrastructure import RepositoryFactory
    from core.models import JobRecord, JobStatus
    from util_logger import LoggerFactory, ComponentType

    logger = LoggerFactory.create_logger(
        ComponentType.CONTROLLER,
        f"{cls.__name__}.create_job_record"
    )

    # Create job record object
    job_record = JobRecord(
        job_id=job_id,
        job_type=cls.job_type,
        parameters=params,
        status=JobStatus.QUEUED,
        stage=1,
        total_stages=len(cls.stages),
        stage_results={},
        metadata={
            'description': cls.description,
            'created_by': cls.__name__
        }
    )

    logger.debug(f"💾 Creating job record: {job_id[:16]}...")

    # Persist to database
    repos = RepositoryFactory.create_repositories()
    job_repo = repos['job_repo']
    created = job_repo.create_job(job_record)

    if created:
        logger.info(f"✅ Job record created: {job_id[:16]}... (type={cls.job_type})")
    else:
        logger.info(f"📋 Job record already exists: {job_id[:16]}... (idempotent)")

    # Return as dict
    return job_record.model_dump()
```

**Testing**:
```python
# Test requires database connection - test after deployment
# For now, verify imports work:
from jobs.mixins import JobBaseMixin
print("✅ create_job_record() imports successful")
```

**Commit after this task**:
```bash
git add jobs/mixins.py
git commit -m "Implement create_job_record() in JobBaseMixin

🔧 Added JobRecord creation from class attributes
🔧 Uses job_type, stages (for total_stages), description
🔧 Persists to database via RepositoryFactory
✅ Idempotency handled by PostgreSQL ON CONFLICT
⏳ Requires deployment to test with database
⏳ queue_job() method pending

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

#### Task 1.5: Implement queue_job() (30 min)

**Generic Service Bus message sending**

```python
@classmethod
def queue_job(cls, job_id: str, params: dict) -> dict:
    """
    Default job queueing to Service Bus.

    Override if you need custom queue routing or message properties.

    Args:
        job_id: Job ID
        params: Validated parameters

    Returns:
        Queue result information dict

    Example override:
        @classmethod
        def queue_job(cls, job_id: str, params: dict) -> dict:
            # Use custom queue for priority jobs
            if params.get('priority') == 'high':
                queue_name = 'geospatial-jobs-priority'
            else:
                queue_name = config.service_bus_jobs_queue

            # ... rest of implementation
    """
    from infrastructure.service_bus import ServiceBusRepository
    from core.schema.queue import JobQueueMessage
    from config import get_config
    from util_logger import LoggerFactory, ComponentType

    logger = LoggerFactory.create_logger(
        ComponentType.CONTROLLER,
        f"{cls.__name__}.queue_job"
    )

    logger.info(f"🚀 Queueing {cls.job_type} job: {job_id[:16]}...")

    # Get config for queue name
    config = get_config()
    queue_name = config.service_bus_jobs_queue

    # Create Service Bus repository
    service_bus_repo = ServiceBusRepository()

    # Create job queue message
    job_message = JobQueueMessage(
        job_id=job_id,
        job_type=cls.job_type,
        stage=1,
        parameters=params,
        correlation_id=str(uuid.uuid4())[:8]
    )

    # Send to Service Bus jobs queue
    message_id = service_bus_repo.send_message(queue_name, job_message)

    logger.info(f"✅ Job queued: {job_id[:16]}... (message_id: {message_id})")

    return {
        "queued": True,
        "queue_type": "service_bus",
        "queue_name": queue_name,
        "message_id": message_id,
        "job_id": job_id
    }
```

**Testing**:
```python
# Test requires Service Bus connection - test after deployment
# For now, verify imports work:
from jobs.mixins import JobBaseMixin
print("✅ queue_job() imports successful")
```

**Commit after this task**:
```bash
git add jobs/mixins.py
git commit -m "Implement queue_job() in JobBaseMixin

🔧 Added Service Bus message creation and sending
🔧 Uses job_type from class attribute
🔧 Creates JobQueueMessage with correlation_id
✅ Generic implementation works for all job types
⏳ Requires deployment to test with Service Bus
✅ JobBaseMixin implementation COMPLETE - all 4 methods done!

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Phase 2: Migrate HelloWorld to Use Mixin (1-2 hours)

**Goal**: Prove the pattern works by migrating hello_world.py

**File**: `jobs/hello_world.py` (MODIFY - reduce from 346 lines → ~80 lines)

#### Task 2.1: Create hello_world_mixin.py (backup approach) (30 min)

**Why**: Test mixin pattern without breaking existing hello_world.py

```python
# jobs/hello_world_mixin.py (NEW - for testing)
"""
HelloWorld Job - Mixin Pattern Test

This is a TEST VERSION of hello_world.py using JobBaseMixin.
If successful, this will replace jobs/hello_world.py.

Author: Robert and Geospatial Claude Legion
Date: 14 NOV 2025
"""

from typing import List, Dict, Any
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class HelloWorldMixinJob(JobBase, JobBaseMixin):
    """
    HelloWorld job using JobBaseMixin pattern.

    Demonstrates 77% line reduction:
    - Before: 346 lines
    - After: ~80 lines
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION (No code!)
    # ========================================================================
    job_type = "hello_world_mixin"  # ← Use different job_type for testing
    description = "Simple two-stage greeting workflow for testing (mixin version)"

    stages = [
        {
            "number": 1,
            "name": "greeting",
            "task_type": "hello_world_greeting",
            "parallelism": "dynamic",
            "count_param": "n"
        },
        {
            "number": 2,
            "name": "reply",
            "task_type": "hello_world_reply",
            "parallelism": "match_previous",
            "depends_on": 1,
            "uses_lineage": True
        }
    ]

    # Declarative parameter validation (no code!)
    parameters_schema = {
        "n": {
            "type": "int",
            "min": 1,
            "max": 1000,
            "default": 3
        },
        "message": {
            "type": "str",
            "default": "Hello World"
        },
        "failure_rate": {
            "type": "float",
            "min": 0.0,
            "max": 1.0,
            "default": 0.0
        }
    }

    # ========================================================================
    # JOB-SPECIFIC LOGIC ONLY: Task Creation (~30 lines)
    # ========================================================================
    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        """
        Generate task parameters for a stage.

        This is the ONLY job-specific logic - everything else provided by mixin.
        """
        n = job_params.get('n', 3)
        message = job_params.get('message', 'Hello World')

        if stage == 1:
            # Stage 1: Create N greeting tasks
            return [
                {
                    "task_id": f"{job_id[:8]}-s1-{i}",
                    "task_type": "hello_world_greeting",
                    "parameters": {
                        "message": message,
                        "index": i,
                        "failure_rate": job_params.get('failure_rate', 0.0)
                    }
                }
                for i in range(n)
            ]

        elif stage == 2:
            # Stage 2: Create N reply tasks (matches stage 1)
            return [
                {
                    "task_id": f"{job_id[:8]}-s2-{i}",
                    "task_type": "hello_world_reply",
                    "parameters": {
                        "greeting": previous_results[i]['result']['greeting'] if previous_results else f"Hello {i}",
                        "index": i
                    }
                }
                for i in range(n)
            ]

    # ========================================================================
    # JOB-SPECIFIC LOGIC ONLY: Finalization (~15 lines)
    # ========================================================================
    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """Create final job summary."""
        if not context:
            return {"status": "completed", "job_type": "hello_world_mixin"}

        # Count completed tasks
        completed = sum(1 for r in context.task_results if r.status.value == 'completed')

        return {
            "status": "completed",
            "job_type": "hello_world_mixin",
            "tasks_completed": completed,
            "tasks_total": len(context.task_results)
        }
```

**Register in jobs/__init__.py**:
```python
# jobs/__init__.py (ADD)
from jobs.hello_world_mixin import HelloWorldMixinJob

ALL_JOBS = {
    "hello_world": HelloWorldJob,  # ← Existing
    "hello_world_mixin": HelloWorldMixinJob,  # ← NEW for testing
    # ... other jobs
}
```

**Testing Plan**:
1. Deploy to Azure Functions
2. Test `hello_world_mixin` job: `POST /api/jobs/submit/hello_world_mixin`
3. Verify it works identically to `hello_world`
4. If successful, replace `hello_world.py` with mixin version

**Commit after this task**:
```bash
git add jobs/hello_world_mixin.py jobs/__init__.py
git commit -m "Add hello_world_mixin.py for testing JobBaseMixin pattern

🔧 Created test version of hello_world using mixin
🔧 Reduced from 346 lines → 80 lines (77% reduction)
🔧 Registered as 'hello_world_mixin' job type
✅ Ready for deployment and testing
⏳ If successful, will replace hello_world.py

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

#### Task 2.2: Deploy and Test hello_world_mixin (30 min)

**Deployment**:
```bash
# 1. Deploy to Azure Functions
func azure functionapp publish rmhazuregeoapi --python --build remote

# 2. Redeploy schema
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes"

# 3. Test hello_world_mixin job
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/hello_world_mixin \
  -H "Content-Type: application/json" \
  -d '{"message": "Testing JobBaseMixin", "n": 3}'

# 4. Wait and check status
sleep 10
curl -s "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}"
```

**Success Criteria**:
- ✅ Job submits without errors
- ✅ Job completes with status "completed"
- ✅ Tasks execute correctly (N greeting tasks + N reply tasks)
- ✅ Finalization returns expected summary

**If successful, commit**:
```bash
git add .
git commit -m "Verify hello_world_mixin works correctly

✅ Deployed hello_world_mixin to Azure Functions
✅ Job submitted and completed successfully
✅ All tasks executed correctly
✅ JobBaseMixin pattern VERIFIED
⏳ Ready to replace hello_world.py with mixin version

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

**If failed, debug and commit each fix**:
```bash
# Example debugging commits:
git commit -m "Fix: Add missing import in JobBaseMixin

❌ Error: NameError: name 'Any' is not defined
🔧 Added 'from typing import Any' to jobs/mixins.py
⏳ Retesting deployment

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

#### Task 2.3: Replace hello_world.py with mixin version (15 min)

**Only do this if Task 2.2 passed all tests!**

```bash
# 1. Backup original hello_world.py
cp jobs/hello_world.py jobs/hello_world_original_backup.py

# 2. Replace hello_world.py with mixin version
# Change class name: HelloWorldMixinJob → HelloWorldJob
# Change job_type: "hello_world_mixin" → "hello_world"

# 3. Remove hello_world_mixin.py (no longer needed)
rm jobs/hello_world_mixin.py

# 4. Update jobs/__init__.py
# Remove HelloWorldMixinJob import
# Keep only HelloWorldJob
```

**Edit jobs/hello_world.py**:
```python
# Change line 43:
class HelloWorldJob(JobBase, JobBaseMixin):  # ← Added JobBaseMixin

# Change line 52:
job_type = "hello_world"  # ← Back to original job_type

# Delete lines 120-318 (all boilerplate methods):
# - validate_job_parameters() - DELETE
# - generate_job_id() - DELETE
# - create_job_record() - DELETE
# - queue_job() - DELETE

# Keep only:
# - create_tasks_for_stage() (lines 82-117)
# - finalize_job() (lines 319-340)
```

**Commit after this task**:
```bash
git add jobs/hello_world.py jobs/__init__.py
git commit -m "Migrate hello_world.py to use JobBaseMixin

🔧 Changed HelloWorldJob to inherit from JobBaseMixin
🔧 Removed 4 boilerplate methods (validate, generate_id, create_record, queue)
🔧 Kept only job-specific logic (create_tasks_for_stage, finalize_job)
✅ Reduced from 346 lines → 80 lines (77% reduction)
✅ Added declarative parameters_schema
⏳ Requires deployment and testing to verify

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

#### Task 2.4: Deploy and Verify hello_world Works (15 min)

**Deployment**:
```bash
# 1. Deploy
func azure functionapp publish rmhazuregeoapi --python --build remote

# 2. Redeploy schema
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes"

# 3. Test original hello_world job (should work identically)
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "Testing migrated hello_world", "n": 3}'

# 4. Wait and check status
sleep 10
curl -s "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}"
```

**Success Criteria**:
- ✅ Job submits without errors
- ✅ Job completes with status "completed"
- ✅ Behavior is identical to pre-migration version

**Commit after verification**:
```bash
git add .
git commit -m "Verify migrated hello_world works correctly

✅ Deployed migrated hello_world to Azure Functions
✅ Job behavior identical to pre-migration version
✅ All tests passed
✅ hello_world.py migration COMPLETE!
✅ JobBaseMixin pattern PROVEN successful

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Phase 3: Documentation & Migration Guide (1 hour)

**Goal**: Enable team to use JobBaseMixin for future jobs

#### Task 3.1: Create JOB_CREATION_QUICKSTART.md (30 min)

**File**: `JOB_CREATION_QUICKSTART.md` (UPDATE - add mixin section)

```markdown
# Job Creation Quickstart - JobBaseMixin Pattern

**Date**: 14 NOV 2025
**Status**: Recommended Pattern for All New Jobs

## 🎯 Quick Start: Create a New Job in 5 Steps

### Step 1: Create Job File (3 minutes)

```python
# jobs/my_new_job.py
from typing import List, Dict, Any
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin

class MyNewJob(JobBase, JobBaseMixin):
    """What this job does."""

    # Declarative configuration (no code!)
    job_type = "my_new_job"
    description = "Brief description of job purpose"

    stages = [
        {
            "number": 1,
            "name": "stage_name",
            "task_type": "task_handler_name",
            "parallelism": "single"  # or "fan_out"
        }
    ]

    parameters_schema = {
        'required_param': {'type': 'str', 'required': True},
        'optional_param': {'type': 'int', 'default': 10, 'min': 1, 'max': 100}
    }

    @staticmethod
    def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None) -> List[dict]:
        """Generate tasks for this stage."""
        if stage == 1:
            return [{
                "task_id": f"{job_id[:8]}-s1-task",
                "task_type": "task_handler_name",
                "parameters": {"param": job_params['required_param']}
            }]

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """Create job summary."""
        return {"status": "completed", "job_type": "my_new_job"}
```

**That's it! Only ~50 lines vs 350 lines without mixin.**

### Step 2: Register Job (1 minute)

```python
# jobs/__init__.py
from jobs.my_new_job import MyNewJob

ALL_JOBS = {
    # ... existing jobs
    "my_new_job": MyNewJob,  # ← ADD THIS LINE
}
```

### Step 3: Create Task Handler (5-10 minutes)

```python
# services/my_new_job.py
def my_task_handler(params: dict) -> dict:
    """Execute the task logic."""
    # Your business logic here
    return {"success": True, "result": {"data": "processed"}}
```

### Step 4: Register Task Handler (1 minute)

```python
# services/__init__.py
from services.my_new_job import my_task_handler

ALL_HANDLERS = {
    # ... existing handlers
    "task_handler_name": my_task_handler,  # ← ADD THIS LINE
}
```

### Step 5: Deploy and Test (5 minutes)

```bash
# Deploy
func azure functionapp publish rmhazuregeoapi --python --build remote

# Test
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/my_new_job \
  -H "Content-Type: application/json" \
  -d '{"required_param": "value"}'
```

**Total Time**: ~15 minutes (vs 2 hours without mixin)

---

## 📋 Parameters Schema Reference

### Supported Types

```python
parameters_schema = {
    # String parameter
    'name': {
        'type': 'str',
        'required': True,  # Must be provided
        'default': 'default_value',  # Default if not provided
        'allowed': ['option1', 'option2']  # Enum-like validation
    },

    # Integer parameter
    'count': {
        'type': 'int',
        'default': 10,
        'min': 1,  # Minimum value
        'max': 100  # Maximum value
    },

    # Float parameter
    'threshold': {
        'type': 'float',
        'default': 0.5,
        'min': 0.0,
        'max': 1.0
    },

    # Boolean parameter
    'enabled': {
        'type': 'bool',
        'default': True
    }
}
```

### Schema Validation Rules

- **required**: If True, parameter must be provided (no default needed)
- **default**: Value used if parameter not provided
- **min/max**: For int/float types, enforces range
- **allowed**: For str type, enforces enum-like values

---

## 🔄 Migrating Existing Jobs

**Do NOT migrate existing jobs unless necessary.** JobBaseMixin is for NEW jobs.

If you must migrate an existing job:

1. **Backup original file**: `cp jobs/my_job.py jobs/my_job_backup.py`
2. **Add mixin inheritance**: `class MyJob(JobBase, JobBaseMixin):`
3. **Add parameters_schema**: Extract validation logic to declarative schema
4. **Delete 4 boilerplate methods**: validate, generate_id, create_record, queue
5. **Keep job-specific methods**: create_tasks_for_stage, finalize_job
6. **Test thoroughly**: Ensure behavior is identical

---

## ❓ FAQ

**Q: Can I override mixin methods if needed?**
A: Yes! Just implement the method in your job class - it will override the mixin default.

**Q: What if I need custom job ID logic?**
A: Override `generate_job_id()`:
```python
@classmethod
def generate_job_id(cls, params: dict) -> str:
    # Exclude 'failure_rate' from job ID hash
    hash_params = {k: v for k, v in params.items() if k != 'failure_rate'}
    canonical = json.dumps({'job_type': cls.job_type, **hash_params}, sort_keys=True)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
```

**Q: What if I need complex validation logic?**
A: Override `validate_job_parameters()`:
```python
@staticmethod
def validate_job_parameters(params: dict) -> dict:
    # Call parent for basic validation
    validated = super().validate_job_parameters(params)

    # Add custom validation
    if validated['start_date'] > validated['end_date']:
        raise ValueError("start_date must be before end_date")

    return validated
```

**Q: Should I migrate all existing jobs?**
A: No. Only migrate if:
- You're already making changes to the job
- The job is frequently copied for new variations
- You need to reduce maintenance burden

Leave working jobs alone unless there's a clear benefit.
```

**Commit after this task**:
```bash
git add JOB_CREATION_QUICKSTART.md
git commit -m "Add JobBaseMixin quick start guide to documentation

📚 Created comprehensive quick start guide
📚 5-step process with code examples
📚 Parameters schema reference
📚 Migration guide for existing jobs
📚 FAQ section
✅ Ready for team to create new jobs with mixin

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

#### Task 3.2: Update COREMACHINE_IMPLEMENTATION_PLAN.md (15 min)

**File**: `COREMACHINE_IMPLEMENTATION_PLAN.md` (UPDATE)

Add new section:

```markdown
### Phase 3: JobBaseMixin (COMPLETED)

- [x] Task 3.1: Create jobs/mixins.py with JobBaseMixin (3 hours)
  - Implemented validate_job_parameters() with schema-based validation
  - Implemented generate_job_id() with SHA256 hash
  - Implemented create_job_record() with JobRecord creation
  - Implemented queue_job() with Service Bus sending
  - **Lines added: 150** (written once, used by all jobs)

- [x] Task 3.2: Migrate hello_world.py to use mixin (2 hours)
  - Created hello_world_mixin.py for testing
  - Deployed and verified functionality
  - Replaced hello_world.py with mixin version
  - **Lines saved: 266** (346 → 80 lines, 77% reduction)

- [x] Task 3.3: Documentation (1 hour)
  - Updated JOB_CREATION_QUICKSTART.md with mixin pattern
  - Added parameters schema reference
  - Added migration guide
  - Added FAQ section

**Overall Progress**: Parts 1 & 2 Complete (100%), Part 3 Complete (100%)
**Total Lines Saved**: 120 (Part 1) + 266 (hello_world migration) = **386 lines**
**New Job Creation Time**: 2 hours → 30 minutes (75% reduction)
```

**Commit after this task**:
```bash
git add COREMACHINE_IMPLEMENTATION_PLAN.md
git commit -m "Update implementation plan with Phase 3 completion

✅ Marked all Phase 3 tasks as complete
✅ Documented lines saved (386 total)
✅ Documented time savings (75% reduction)
✅ All planned CoreMachine improvements COMPLETE

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

#### Task 3.3: Update docs_claude/TODO.md (15 min)

**File**: `docs_claude/TODO.md` (UPDATE)

Add to HISTORY section:

```markdown
## 14 NOV 2025 - CoreMachine JobBaseMixin Implementation ✅

**Implemented by**: Robert and Geospatial Claude Legion

### Changes Made

1. **Created JobBaseMixin Pattern** (jobs/mixins.py - 150 lines)
   - Eliminates 185 lines of boilerplate per job (77% reduction)
   - Provides default implementations of 4 repetitive methods
   - Schema-based parameter validation
   - Generic SHA256 job ID generation
   - Generic JobRecord creation
   - Generic Service Bus queueing

2. **Migrated hello_world.py** (346 lines → 80 lines)
   - First job to use JobBaseMixin pattern
   - Proves pattern works in production
   - Behavior identical to pre-migration version

3. **Updated Documentation**
   - JOB_CREATION_QUICKSTART.md - 5-step job creation guide
   - COREMACHINE_IMPLEMENTATION_PLAN.md - Phase 3 completion
   - COREMACHINE_CHANGE.md - Complete implementation plan

### Impact

- **New job creation time**: 2 hours → 30 minutes (75% reduction)
- **Code reduction**: 266 lines saved in hello_world.py alone
- **Maintainability**: Bug fixes to boilerplate apply to all jobs
- **Consistency**: All jobs use same validation, ID generation, queueing patterns

### Files Changed

- `jobs/mixins.py` - NEW (150 lines)
- `jobs/hello_world.py` - MODIFIED (346 → 80 lines)
- `JOB_CREATION_QUICKSTART.md` - UPDATED
- `COREMACHINE_IMPLEMENTATION_PLAN.md` - UPDATED
- `COREMACHINE_CHANGE.md` - NEW (this file)

### Commits

- 8 commits total (frequent commits for sensitive CoreMachine changes)
- All commits follow git workflow pattern from CLAUDE.md
- Clear commit messages with technical details and status
```

**Commit after this task**:
```bash
git add docs_claude/TODO.md
git commit -m "Update TODO.md with JobBaseMixin implementation history

📚 Added 14 NOV 2025 entry to HISTORY section
📚 Documented all changes, impact, and files
✅ JobBaseMixin implementation fully documented

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 📊 Success Metrics

### Before JobBaseMixin

- **New job creation**: ~350 lines, 2 hours
- **Boilerplate per job**: 185 lines (53% of code)
- **Duplication across 5 jobs**: ~925 lines of repeated code
- **Maintenance burden**: Bug fixes require updating 5+ files

### After JobBaseMixin

- **New job creation**: ~80 lines, 30 minutes (77% reduction)
- **Boilerplate per job**: 0 lines (provided by mixin)
- **Duplication**: 150 lines (written once in mixin)
- **Maintenance burden**: Bug fixes update 1 file, apply to all jobs

### Quantitative Results

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Lines per new job | 350 | 80 | **77% reduction** |
| Time per new job | 2 hours | 30 min | **75% faster** |
| Duplicated code | 925 lines | 150 lines | **84% reduction** |
| Maintenance files | 5+ | 1 | **80% reduction** |

---

## 🚨 Critical Success Factors

### 1. Frequent Git Commits

**Why**: Changes to CoreMachine architecture are sensitive. Detailed git history enables:
- Fast rollback if something breaks
- Clear debugging trail ("what changed between working and broken?")
- Team understanding of evolution

**Pattern**: Commit after EACH task (not at end of phase)

### 2. Test in Production

**Why**: Cannot fully test locally (no Service Bus, no database connections)

**Pattern**:
1. Make change
2. Commit to git (dev branch)
3. Deploy to Azure Functions
4. Test with real job submission
5. If successful, commit "Verified XYZ works"
6. If failed, debug, commit fix, redeploy

### 3. Backward Compatibility

**Why**: Existing jobs must keep working while we migrate

**Pattern**:
- JobBaseMixin is ADDITIVE (doesn't break existing jobs)
- Jobs opt-in via inheritance (can migrate one at a time)
- Original hello_world.py backed up before migration

### 4. Documentation First

**Why**: Pattern is new - team needs clear examples

**Pattern**:
- Update JOB_CREATION_QUICKSTART.md first
- Provide code examples for every feature
- Document edge cases and FAQs

---

## 🎯 Next Steps (After JobBaseMixin Complete)

### Optional: Migrate Other Jobs

**Candidates** (only if there's a clear benefit):
1. `ingest_vector.py` (762 lines → ~200 lines)
2. `generate_h3_level4.py` (405 lines → ~150 lines)
3. `create_h3_base.py` (430 lines → ~180 lines)
4. `validate_raster_job.py` (356 lines → ~100 lines)

**Total potential savings**: ~1,100 lines across 4 jobs

**Recommendation**: Only migrate if:
- Making other changes to the job
- Job is frequently copied for variations
- Clear maintenance benefit

Otherwise, **leave working code alone**.

### Future Enhancements (Low Priority)

1. **Auto-discovering handler registry** (COREMACHINE_REVIEW.md Part 3.2)
   - Reduces handler registration errors
   - ~40 lines of code

2. **StageResultExtractor utility** (COREMACHINE_REVIEW.md Part 2.4)
   - Safe fan-out result extraction
   - Clearer error messages for malformed results
   - ~50 lines of code

3. **Pydantic parameter validation** (COREMACHINE_REVIEW.md Part 3.3)
   - Optional upgrade for jobs needing complex validation
   - Type-safe parameters with IDE autocomplete

---

## 📝 Notes for Robert

### Why This Works

The key insight is: **CoreMachine structure is already clean**. It only calls 2 job methods:
- `create_tasks_for_stage()` - Job-specific logic
- `finalize_job()` - Job-specific summary

The problem is NOT in CoreMachine - it's in the **jobs having too much boilerplate**.

JobBaseMixin solves this by:
1. Not changing CoreMachine at all
2. Not changing the JobBase interface
3. Just providing default implementations that jobs can inherit

### Flood Model Data Pipeline

When the flood risk raster data arrives, creating the processing job will be:

```python
# jobs/flood_risk_cog.py (~80 lines total)
class FloodRiskCOGJob(JobBase, JobBaseMixin):
    job_type = "flood_risk_cog"
    stages = [
        {"number": 1, "name": "validate", "task_type": "validate_raster_file"},
        {"number": 2, "name": "create_tiles", "task_type": "create_cog_tile", "parallelism": "fan_out"},
        {"number": 3, "name": "update_catalog", "task_type": "update_stac_catalog"}
    ]

    parameters_schema = {
        'dataset_id': {'type': 'str', 'required': True},
        'tile_size': {'type': 'int', 'default': 256, 'allowed': [128, 256, 512]}
    }

    @staticmethod
    def create_tasks_for_stage(stage, job_params, job_id, previous_results=None):
        if stage == 1:
            return [{"task_id": f"{job_id[:8]}-s1", "task_type": "validate_raster_file", ...}]
        elif stage == 2:
            # Fan-out based on file size from stage 1
            file_size = previous_results[0]['result']['size_mb']
            zoom_levels = [10, 11, 12] if file_size < 100 else [10, 11, 12, 13, 14]
            return [{"task_id": f"{job_id[:8]}-s2-z{z}", "task_type": "create_cog_tile", ...} for z in zoom_levels]
        elif stage == 3:
            return [{"task_id": f"{job_id[:8]}-s3", "task_type": "update_stac_catalog", ...}]

    @staticmethod
    def finalize_job(context):
        return {"status": "completed", "tiles_created": len(context.task_results)}
```

**30 minutes** instead of **2 hours**. 🎉

---

## 🏁 Final Checklist

Before marking this implementation complete:

- [ ] Phase 1: JobBaseMixin created and tested
  - [ ] Task 1.1: Skeleton with docstrings ✅
  - [ ] Task 1.2: validate_job_parameters() ✅
  - [ ] Task 1.3: generate_job_id() ✅
  - [ ] Task 1.4: create_job_record() ✅
  - [ ] Task 1.5: queue_job() ✅

- [ ] Phase 2: HelloWorld migrated
  - [ ] Task 2.1: hello_world_mixin.py created ✅
  - [ ] Task 2.2: Deployed and tested ✅
  - [ ] Task 2.3: Replaced hello_world.py ✅
  - [ ] Task 2.4: Verified behavior unchanged ✅

- [ ] Phase 3: Documentation complete
  - [ ] Task 3.1: JOB_CREATION_QUICKSTART.md ✅
  - [ ] Task 3.2: COREMACHINE_IMPLEMENTATION_PLAN.md ✅
  - [ ] Task 3.3: docs_claude/TODO.md ✅

- [ ] All commits made with detailed messages ✅
- [ ] All tests passed in production ✅
- [ ] Team can create new jobs using quickstart guide ✅

---

**Date Completed**: _____________
**Verified By**: _____________
**Status**: READY FOR IMPLEMENTATION ✅
