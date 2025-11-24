# ============================================================================
# CLAUDE CONTEXT - JOB CREATION QUICKSTART
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: QA/Deployment Documentation - Quick reference for creating new jobs
# PURPOSE: Step-by-step guide for creating new geospatial data processing jobs
# LAST_REVIEWED: 14 NOV 2025
# EXPORTS: Job creation patterns (JobBaseMixin recommended, manual fallback)
# INTERFACES: JobBase ABC, JobBaseMixin (boilerplate elimination)
# PYDANTIC_MODELS: JobRecord, TaskRecord, JobQueueMessage
# DEPENDENCIES: jobs.base.JobBase, jobs.mixins.JobBaseMixin
# SOURCE: Developer guide - referenced by team when creating new pipelines
# SCOPE: All new job creation - production and test workflows
# VALIDATION: Import-time registry validation (validate_job_registry)
# PATTERNS: Mixin pattern (recommended), Manual implementation (fallback)
# ENTRY_POINTS: New developers creating jobs, Migration of existing jobs
# INDEX:
#   - JobBaseMixin Quick Start (RECOMMENDED): Line 23
#   - Manual Implementation (Fallback): Line 180
#   - Registration Steps: Line 277
#   - Testing Commands: Line 316
#   - Reference Implementations: Line 342
# ============================================================================

# Job Creation Quickstart Guide

**Last Updated**: 14 NOV 2025

---

## START HERE: JobBaseMixin Pattern (Recommended)

**New jobs take 30 minutes instead of 2 hours using JobBaseMixin.**

### Why Use JobBaseMixin?

- 77% less code: 80 lines instead of 350 lines
- Declarative validation: Define schema, get validation automatically
- No boilerplate: 4 methods provided automatically
- Maintainable: Bug fixes apply to all jobs
- Production tested: Used in `hello_world_mixin` job (14 NOV 2025)

---

## Quick Start: Create a New Job in 5 Steps

### Step 1: Create Job File (5 minutes)

Create `jobs/my_new_job.py`:

```python
# ============================================================================
# CLAUDE CONTEXT - JOB DEFINITION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Job - [Brief description of what this job does]
# PURPOSE: [One sentence explanation]
# LAST_REVIEWED: [DD MMM YYYY]
# EXPORTS: MyNewJob (JobBase + JobBaseMixin implementation)
# INTERFACES: JobBase (2 methods), JobBaseMixin (provides 4 methods)
# PYDANTIC_MODELS: Uses declarative parameters_schema
# DEPENDENCIES: jobs.base.JobBase, jobs.mixins.JobBaseMixin
# SOURCE: HTTP job submission via POST /api/jobs/my_new_job
# SCOPE: [What this job processes - e.g., "Raster tiles", "Vector features"]
# VALIDATION: Declarative schema via JobBaseMixin
# PATTERNS: Mixin pattern (composition over inheritance)
# ENTRY_POINTS: Registered in jobs/__init__.py ALL_JOBS as "my_new_job"
# ============================================================================

"""
My New Job - Brief Description

[Detailed description of what this job does]

Multi-Stage Workflow:
1. Stage 1: [Description]
2. Stage 2: [Description]

Author: Robert and Geospatial Claude Legion
Date: [DD MMM YYYY]
"""

from typing import List, Dict, Any
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class MyNewJob(JobBaseMixin, JobBase):  # ← Mixin FIRST for correct MRO!
    """
    [Job description]

    Workflow: [Stage 1] → [Stage 2] → [Stage 3]
    """

    # ========================================================================
    # DECLARATIVE CONFIGURATION (No code!)
    # ========================================================================
    job_type = "my_new_job"
    description = "Brief description of job purpose"

    stages = [
        {
            "number": 1,
            "name": "stage_name",
            "task_type": "task_handler_name",
            "parallelism": "single"  # or "fan_out" for parallel tasks
        },
        {
            "number": 2,
            "name": "another_stage",
            "task_type": "another_handler",
            "parallelism": "fan_out"
        }
    ]

    # Declarative parameter validation (JobBaseMixin handles validation!)
    parameters_schema = {
        'required_param': {
            'type': 'str',
            'required': True
        },
        'optional_param': {
            'type': 'int',
            'default': 10,
            'min': 1,
            'max': 100
        },
        'format': {
            'type': 'str',
            'default': 'COG',
            'allowed': ['COG', 'GeoTIFF']  # Enum-like validation
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
        Generate tasks for this stage.

        This is the ONLY job-specific logic - everything else provided by mixin.
        """
        if stage == 1:
            # Stage 1: Single task
            return [{
                "task_id": f"{job_id[:8]}-s1-task",
                "task_type": "task_handler_name",
                "parameters": {
                    "param": job_params['required_param']
                }
            }]

        elif stage == 2:
            # Stage 2: Fan-out based on stage 1 results
            result_from_stage_1 = previous_results[0]['result']
            count = result_from_stage_1.get('file_count', 1)

            return [
                {
                    "task_id": f"{job_id[:8]}-s2-{i}",
                    "task_type": "another_handler",
                    "parameters": {
                        "index": i,
                        "format": job_params['format']
                    }
                }
                for i in range(count)
            ]

    # ========================================================================
    # JOB-SPECIFIC LOGIC ONLY: Finalization (~15 lines)
    # ========================================================================
    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """Create job summary."""
        if not context:
            return {"status": "completed", "job_type": "my_new_job"}

        return {
            "status": "completed",
            "job_type": "my_new_job",
            "tasks_completed": len(context.task_results)
        }
```

**That's it! Only ~80 lines vs 350 lines without mixin.**

---

### Step 2: Register Job (1 minute)

Edit `jobs/__init__.py`:

```python
# Add import at top
from .my_new_job import MyNewJob

# Add to ALL_JOBS dict
ALL_JOBS = {
    # ... existing jobs ...
    "my_new_job": MyNewJob,  # ← ADD THIS LINE
}
```

---

### Step 3: Create Task Handler (5-10 minutes)

Create `services/my_new_job.py`:

```python
"""Task handlers for my_new_job."""

def my_task_handler(params: dict) -> dict:
    """Execute the task logic."""
    # Your business logic here
    result = process_something(params)

    return {
        "success": True,
        "result": result
    }
```

---

### Step 4: Register Task Handler (1 minute)

Edit `services/__init__.py`:

```python
# Add import at top
from .my_new_job import my_task_handler

# Add to ALL_HANDLERS dict
ALL_HANDLERS = {
    # ... existing handlers ...
    "task_handler_name": my_task_handler,  # ← ADD THIS LINE
}
```

---

### Step 5: Deploy and Test (5 minutes)

```bash
# 1. Validate locally
python3 -c "from jobs import validate_job_registry; validate_job_registry()"

# 2. Deploy to Azure Functions
func azure functionapp publish rmhazuregeoapi --python --build remote

# 3. Redeploy database schema (if needed)
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes"

# 4. Submit test job
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/my_new_job \
  -H "Content-Type: application/json" \
  -d '{"required_param": "value"}'

# 5. Check job status (use job_id from response)
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
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
        'required': True,          # Must be provided
        'default': 'default_value', # Default if not provided
        'allowed': ['opt1', 'opt2'] # Enum-like validation
    },

    # Integer parameter
    'count': {
        'type': 'int',
        'default': 10,
        'min': 1,     # Minimum value
        'max': 100    # Maximum value
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

## 🔧 Advanced: Overriding Mixin Methods

**The default implementations work for 95% of jobs. Override only when needed.**

### Custom Job ID Logic

Exclude certain params from job ID hash (e.g., testing parameters):

```python
@classmethod
def generate_job_id(cls, params: dict) -> str:
    """Custom job ID - excludes 'failure_rate' from hash."""
    import hashlib
    import json

    # Exclude testing parameters
    hash_params = {k: v for k, v in params.items() if k != 'failure_rate'}

    canonical = json.dumps({
        'job_type': cls.job_type,
        **hash_params
    }, sort_keys=True)

    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
```

### Complex Parameter Validation

Add cross-field validation:

```python
@classmethod
def validate_job_parameters(cls, params: dict) -> dict:
    """Custom validation with cross-field checks."""
    # Call parent for basic validation
    validated = super().validate_job_parameters(params)

    # Add custom cross-field validation
    if validated['start_date'] > validated['end_date']:
        raise ValueError("start_date must be before end_date")

    return validated
```

### Custom Queue Routing

Route to different queues based on parameters:

```python
@classmethod
def queue_job(cls, job_id: str, params: dict) -> dict:
    """Custom queue routing for priority jobs."""
    from infrastructure.service_bus import ServiceBusRepository
    from config import get_config

    # Use priority queue for high-priority jobs
    if params.get('priority') == 'high':
        queue_name = 'geospatial-jobs-priority'
    else:
        config = get_config()
        queue_name = config.service_bus_jobs_queue

    # ... rest of implementation (copy from mixin source)
```

---

## 📚 Reference Implementations

### Simple (Single Stage)
- **File**: [jobs/create_h3_base.py](jobs/create_h3_base.py)
- **Lines**: ~150 lines
- **Pattern**: Single stage, minimal parameters

### Multi-Stage (JobBaseMixin)
- **File**: [jobs/hello_world_mixin.py](jobs/hello_world_mixin.py)
- **Lines**: ~208 lines (vs 347 without mixin)
- **Pattern**: Two stages, parameter defaults, custom job ID override

### Complex (Fan-Out/Fan-In)
- **File**: [jobs/process_large_raster.py](jobs/process_large_raster.py)
- **Lines**: Variable (hundreds of tasks)
- **Pattern**: Dynamic fan-out based on file size, stage result passing

---

## ⚠️ Common Mistakes

### ❌ Wrong Inheritance Order

```python
# WRONG - JobBase takes precedence over mixin
class MyJob(JobBase, JobBaseMixin):
    pass

# CORRECT - Mixin overrides JobBase methods
class MyJob(JobBaseMixin, JobBase):
    pass
```

### ❌ Missing parameters_schema

```python
# WRONG - No schema defined
class MyJob(JobBaseMixin, JobBase):
    job_type = "my_job"
    stages = [...]
    # Missing parameters_schema!

# CORRECT - Schema must be defined
class MyJob(JobBaseMixin, JobBase):
    job_type = "my_job"
    stages = [...]
    parameters_schema = {'param': {'type': 'str', 'required': True}}
```

### ❌ Missing Task Dict Keys

```python
# WRONG - Missing required keys
return [{
    "task_id": f"{job_id[:8]}-s1",
    # Missing "task_type" and "parameters"!
}]

# CORRECT - All required keys
return [{
    "task_id": f"{job_id[:8]}-s1",
    "task_type": "handler_name",
    "parameters": {"key": "value"}
}]
```

### ❌ Handler Not Registered

```python
# WRONG - Handler exists but not in ALL_HANDLERS
# services/my_job.py
def my_handler(params): ...

# CORRECT - Handler registered in services/__init__.py
# services/__init__.py
from .my_job import my_handler
ALL_HANDLERS = {"handler_name": my_handler}
```

---

## 🧪 Testing Checklist

Before deploying:

- [ ] Local import validation passes: `python3 -c "from jobs import validate_job_registry; validate_job_registry()"`
- [ ] All task handlers registered in `services/__init__.py`
- [ ] Job registered in `jobs/__init__.py`
- [ ] `parameters_schema` defined with all required params
- [ ] Inheritance order correct: `(JobBaseMixin, JobBase)`
- [ ] Task dicts have all required keys (`task_id`, `task_type`, `parameters`)
- [ ] Deployed to Azure Functions successfully
- [ ] Test job submits without errors
- [ ] Job completes with expected status
- [ ] Tasks execute correctly

---

## 📖 Additional Documentation

- **Full Architecture**: [docs_claude/ARCHITECTURE_REFERENCE.md](docs_claude/ARCHITECTURE_REFERENCE.md)
- **Mixin Implementation**: [jobs/mixins.py](jobs/mixins.py) (lines 1-670)
- **Service Bus Config**: [docs_claude/SERVICE_BUS_HARMONIZATION.md](docs_claude/SERVICE_BUS_HARMONIZATION.md)
- **Deployment Guide**: [docs_claude/DEPLOYMENT_GUIDE.md](docs_claude/DEPLOYMENT_GUIDE.md)

---

## 🔄 Migrating Existing Jobs (Optional)

**Do NOT migrate existing jobs unless necessary.** JobBaseMixin is for NEW jobs.

If you must migrate an existing job:

1. **Backup original file**: `cp jobs/my_job.py jobs/my_job_backup.py`
2. **Add mixin inheritance**: `class MyJob(JobBaseMixin, JobBase):`
3. **Add parameters_schema**: Extract validation logic to declarative schema
4. **Delete 4 boilerplate methods**:
   - `validate_job_parameters()`
   - `generate_job_id()`
   - `create_job_record()`
   - `queue_job()`
5. **Keep job-specific methods**:
   - `create_tasks_for_stage()`
   - `finalize_job()`
6. **Test thoroughly**: Ensure behavior is identical

**Only migrate if:**
- You're already making changes to the job
- The job is frequently copied for variations
- Clear maintenance benefit exists

**Leave working code alone** unless there's a clear benefit.

---

**Author**: Robert and Geospatial Claude Legion
**Date**: 14 NOV 2025
**Status**: Production-Ready QA/Deployment Documentation