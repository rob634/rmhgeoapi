# PostgreSQL Function Usage Comparison: BaseController vs Service Bus
**Date**: 28 SEP 2025
**Analysis**: Comparing how BaseController and Service Bus controllers use PostgreSQL functions

## Key Finding: BOTH Use Same Repository Pattern ✅

### BaseController Flow

**File**: `controller_base.py`

1. **Repository Creation** (Line 1772):
```python
repos = RepositoryFactory.create_repositories()
stage_completion_repo = repos['stage_completion_repo']
```

2. **Direct Repository Call** (Lines 1897-1903):
```python
stage_completion = stage_completion_repo.complete_task_and_check_stage(
    task_id=task_message.task_id,
    job_id=task_message.parent_job_id,
    stage=task_message.stage,
    result_data=task_result.result_data if task_result.result_data else {},
    error_details=None
)
```

### Service Bus Controller Flow

**File**: `controller_service_bus_hello.py`

1. **StateManager Creation** (Line 96):
```python
self.state_manager = StateManager()
```

2. **StateManager Method Call** (Lines 708-713):
```python
completion = self.state_manager.complete_task_with_sql(
    task_message.task_id,
    task_message.parent_job_id,
    task_message.stage,
    result  # TaskResult object
)
```

3. **StateManager Internal Implementation** (`state_manager.py`):
   - **Repository Creation** (Line 507):
   ```python
   repos = RepositoryFactory.create_repositories()
   stage_completion_repo = repos['stage_completion_repo']
   ```

   - **Same Repository Call** (Lines 525-531):
   ```python
   stage_completion = stage_completion_repo.complete_task_and_check_stage(
       task_id=task_id,
       job_id=job_id,
       stage=stage,
       result_data=task_result.result_data or {},
       error_details=None
   )
   ```

## Architecture Comparison

### BaseController
```
BaseController
    ↓ (direct)
RepositoryFactory.create_repositories()
    ↓
stage_completion_repo.complete_task_and_check_stage()
    ↓
PostgreSQL Function
```

### Service Bus Controller
```
ServiceBusHelloWorldController
    ↓ (via StateManager)
StateManager.complete_task_with_sql()
    ↓
RepositoryFactory.create_repositories()
    ↓
stage_completion_repo.complete_task_and_check_stage()
    ↓
PostgreSQL Function
```

## Key Differences

### 1. Abstraction Layer
- **BaseController**: Direct repository access (God Class pattern)
- **Service Bus**: StateManager abstraction (Clean Architecture)

### 2. Error Handling
- **BaseController**: Handles errors directly in controller
- **Service Bus**: StateManager adds validation layer (checks task status)

### 3. Logging
- **BaseController**: Extensive DEBUG logging throughout
- **Service Bus/StateManager**: Additional logging in StateManager layer

## Critical Validation in StateManager

**Lines 512-520 in state_manager.py**:
```python
# Verify task is in PROCESSING state
task = task_repo.get_task(task_id)
if not task:
    raise ValueError(f"Task not found: {task_id}")

if task.status != TaskStatus.PROCESSING:
    raise RuntimeError(
        f"Task {task_id} has unexpected status: {task.status} "
        f"(expected: PROCESSING)"
    )
```

This validation ensures tasks are in the correct state before completion.

## Same PostgreSQL Repository Implementation ✅

Both ultimately call the **exact same repository method**:
- Repository: `stage_completion_repo`
- Method: `complete_task_and_check_stage()`
- Implementation: `repositories/postgresql.py` (Line 1532)

The repository executes the same SQL:
```sql
SELECT * FROM app.complete_task_and_check_stage(
    %s::VARCHAR,  -- task_id
    %s::VARCHAR,  -- job_id
    %s::INTEGER,  -- stage
    %s::JSONB,    -- result_data
    %s::TEXT      -- error_details
);
```

## Return Values

Both receive the same `StageAdvancementResult` with:
- `task_updated`: Boolean indicating if task was updated
- `stage_complete`: Boolean indicating if all tasks in stage are complete
- `remaining_tasks`: Count of tasks still pending in stage
- `job_complete`: Boolean indicating if entire job is complete

## Conclusion

✅ **BOTH controllers use the SAME PostgreSQL repository and function**
- The Service Bus controller just adds an abstraction layer (StateManager)
- StateManager provides additional validation and logging
- The underlying PostgreSQL function call is identical
- The race condition prevention (advisory locks) works the same for both

The issue with Service Bus tasks getting stuck is NOT due to different PostgreSQL usage - they use the exact same repository pattern and database function.