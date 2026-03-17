# COMPETE Run 46 Fixes — DAG Data Layer

> **For agentic workers:** Use superpowers:executing-plans to implement this plan.

**Goal:** Fix the 5 findings from COMPETE Run 46 (DAG Data Layer adversarial review).

**Architecture:** All fixes are small (<1 hour each), isolated to single files, no new dependencies.

---

### Task 1: Replace `default=str` with canonical serializer in `_generate_run_id`

**Files:**
- Modify: `core/dag_initializer.py`

- [ ] **Step 1: Add `_canonical_default` function**

After the existing imports, before `_generate_run_id`:

```python
def _canonical_default(obj):
    """
    Deterministic JSON serializer for run_id generation.

    Spec: COMPETE Run 46 Fix 1 — default=str is non-deterministic across
    Python versions for datetime, UUID, Decimal. Whitelist known types.
    """
    from datetime import datetime, date
    from decimal import Decimal
    from enum import Enum
    from uuid import UUID

    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return obj.hex
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    raise ContractViolationError(
        f"_generate_run_id: parameter value of type {type(obj).__name__} is not "
        "JSON-serializable. Add explicit handling in _canonical_default()."
    )
```

- [ ] **Step 2: Update `_generate_run_id` to use it**

Replace `default=str` with `default=_canonical_default`:

```python
payload = json.dumps(
    {"workflow": workflow_name, "parameters": parameters},
    sort_keys=True,
    default=_canonical_default,
)
```

- [ ] **Step 3: Verify determinism**

Run: `conda run -n azgeo python -c "from core.dag_initializer import _generate_run_id; from datetime import datetime, timezone; id1 = _generate_run_id('test', {'ts': datetime(2026,1,1,tzinfo=timezone.utc)}); id2 = _generate_run_id('test', {'ts': datetime(2026,1,1,tzinfo=timezone.utc)}); assert id1 == id2; print('OK')"`

---

### Task 2: Wire workflow exceptions into exception hierarchy

**Files:**
- Modify: `core/errors/workflow_errors.py`

- [ ] **Step 1: Read current file**

Read `core/errors/workflow_errors.py` to see current inheritance.

- [ ] **Step 2: Change base classes**

```python
from exceptions import BusinessLogicError

class WorkflowValidationError(BusinessLogicError):
    """Raised when a workflow YAML definition is invalid."""
    def __init__(self, workflow_name: str, errors: list[str]):
        self.workflow_name = workflow_name
        self.errors = errors
        super().__init__(
            f"Workflow '{workflow_name}' invalid: {'; '.join(errors)}"
        )


class WorkflowNotFoundError(BusinessLogicError):
    """Raised when a workflow name is not in the registry."""
    def __init__(self, workflow_name: str):
        self.workflow_name = workflow_name
        super().__init__(f"Workflow not found: '{workflow_name}'")
```

- [ ] **Step 3: Verify imports still work**

Run: `conda run -n azgeo python -c "from core.errors.workflow_errors import WorkflowValidationError, WorkflowNotFoundError; from exceptions import BusinessLogicError; assert issubclass(WorkflowValidationError, BusinessLogicError); assert issubclass(WorkflowNotFoundError, BusinessLogicError); print('OK')"`

---

### Task 3: Strict unknown-ID guard in `_build_adjacency_from_tasks`

**Files:**
- Modify: `core/dag_fan_engine.py`

- [ ] **Step 1: Find and replace the silent guard**

Find `_build_adjacency_from_tasks` — replace the `if task_name and dep_name:` guard with an explicit error:

```python
task_name = id_to_name.get(task_iid)
dep_name = id_to_name.get(dep_iid)
if task_name is None or dep_name is None:
    raise ContractViolationError(
        f"_build_adjacency_from_tasks: dep edge references unknown task_instance_id. "
        f"task_iid={task_iid!r} (known={task_name is not None}), "
        f"dep_iid={dep_iid!r} (known={dep_name is not None}). "
        "This indicates a data integrity violation in workflow_task_deps."
    )
```

- [ ] **Step 2: Verify import of ContractViolationError exists**

Check that `from exceptions import ContractViolationError` is already in the imports of `dag_fan_engine.py`.

---

### Task 4: Add cross-field validation to `RetryPolicy`

**Files:**
- Modify: `core/models/workflow_definition.py`

- [ ] **Step 1: Add model_validator to RetryPolicy**

```python
from pydantic import model_validator

class RetryPolicy(BaseModel):
    max_attempts: int = Field(default=3, ge=1, le=10)
    backoff: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    initial_delay_seconds: int = Field(default=5, ge=1)
    max_delay_seconds: int = Field(default=300, ge=1)

    @model_validator(mode='after')
    def validate_delay_bounds(self):
        if self.initial_delay_seconds > self.max_delay_seconds:
            raise ValueError(
                f"initial_delay_seconds ({self.initial_delay_seconds}) must not exceed "
                f"max_delay_seconds ({self.max_delay_seconds})"
            )
        return self
```

- [ ] **Step 2: Verify validation fires**

Run: `conda run -n azgeo python -c "from core.models.workflow_definition import RetryPolicy; from pydantic import ValidationError; try: RetryPolicy(initial_delay_seconds=500, max_delay_seconds=100); print('FAIL'); except ValidationError: print('OK — validation caught')"`

---

### Task 5: Fix stale fields in `claim_ready_workflow_task` return

**Files:**
- Modify: `infrastructure/workflow_run_repository.py`

- [ ] **Step 1: Patch the returned WorkflowTask with post-UPDATE values**

In `claim_ready_workflow_task`, after building the task from the row, patch the fields that were set by the UPDATE:

```python
task = _workflow_task_from_row(row)
task.status = WorkflowTaskStatus.RUNNING
task.claimed_by = worker_id
# started_at and last_pulse were set to NOW() by the UPDATE —
# use Python's current time as a close approximation
from datetime import datetime, timezone
task.started_at = datetime.now(timezone.utc)
task.last_pulse = datetime.now(timezone.utc)
```

---

### Task 6: Run full test suite and commit

- [ ] **Step 1: Run all existing tests**

Run: `conda run -n azgeo python -m pytest tests/unit/test_workflow_dag_models.py tests/unit/test_workflow_loader.py -v --timeout=30`
Expected: 73/73 pass

- [ ] **Step 2: Commit**

```bash
git add core/dag_initializer.py core/errors/workflow_errors.py core/dag_fan_engine.py \
  core/models/workflow_definition.py infrastructure/workflow_run_repository.py \
  V10_DECISIONS.md
git commit -m "fix(COMPETE-46): 5 fixes from DAG data layer adversarial review"
```
