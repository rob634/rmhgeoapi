# Service Bus Clean Architecture Plan

**Date**: 26 SEP 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: PROPOSED - Build Service Bus Right, Then Retrofit

## 🎯 The Strategy

Build Service Bus controllers with a **minimal, clean architecture** FIRST, then retrofit Storage Queue to match. This avoids inheriting 38 methods of cruft and lets us identify the TRUE controller abstractions.

## 📊 What Service Bus Controllers ACTUALLY Need

After analyzing `ServiceBusBaseController`, here's what it TRULY uses from BaseController:

### Core Abstract Methods (5 total - that's it!)
1. `validate_job_parameters()` - Validate inputs
2. `create_stage_tasks()` - Create tasks for a stage
3. `should_advance_stage()` - Decide on stage progression
4. `aggregate_stage_results()` - Aggregate task results per stage
5. `aggregate_job_results()` - Final job aggregation

### That's literally ALL the abstract methods needed!

## 🏗️ Proposed Clean Architecture

```
IJobController (Pure Interface - 5 methods)
    ↓
ServiceBusController (Clean Implementation)
    ├── IJobIdentity (job/task ID generation)
    ├── IQueueStrategy (Service Bus specific)
    ├── IStageOrchestrator (stage progression)
    └── IResultAggregator (result handling)
```

## 📦 Component Design

### 1. IJobController Interface (The TRUE Abstraction)
```python
# interfaces/job_controller.py
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

class IJobController(ABC):
    """The ACTUAL controller contract - just 5 methods!"""

    @abstractmethod
    def get_job_type(self) -> str:
        """Identify the job type this controller handles."""
        pass

    @abstractmethod
    def validate_job_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize job parameters."""
        pass

    @abstractmethod
    def create_stage_tasks(
        self,
        stage_number: int,
        job_id: str,
        job_parameters: Dict[str, Any],
        previous_stage_results: Optional[List[Dict[str, Any]]] = None
    ) -> List['TaskDefinition']:
        """Create tasks for a specific stage."""
        pass

    @abstractmethod
    def should_advance_stage(
        self,
        job_id: str,
        current_stage: int,
        stage_results: Dict[str, Any]
    ) -> bool:
        """Determine if job should advance to next stage."""
        pass

    @abstractmethod
    def aggregate_stage_results(
        self,
        job_id: str,
        stage_number: int,
        task_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Aggregate results from all tasks in a stage."""
        pass
```

### 2. ServiceBusController (Clean Base Implementation)
```python
# orchestration/service_bus_controller.py
from interfaces.job_controller import IJobController
from orchestration.components import (
    JobIdentityManager,
    ServiceBusQueueStrategy,
    StageOrchestrator,
    ResultAggregator
)

class ServiceBusController(IJobController):
    """Clean Service Bus controller with composed components."""

    def __init__(self, job_type: str):
        self.job_type = job_type

        # Compose clean components
        self.identity = JobIdentityManager()
        self.queue_strategy = ServiceBusQueueStrategy()
        self.stage_orchestrator = StageOrchestrator(job_type)
        self.result_aggregator = ResultAggregator()

    def get_job_type(self) -> str:
        return self.job_type

    def execute_job(self, job_id: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Main orchestration method - clean and simple."""
        # 1. Validate parameters
        validated_params = self.validate_job_parameters(parameters)

        # 2. Check for duplicate (idempotency)
        if existing := self.identity.check_duplicate(job_id):
            return existing

        # 3. Queue the job
        queue_result = self.queue_strategy.queue_job(job_id, validated_params)

        return {
            "job_id": job_id,
            "status": "queued",
            "queue_result": queue_result
        }

    def process_stage(self, job_id: str, stage: int, params: Dict) -> Dict[str, Any]:
        """Process a single stage - called by queue trigger."""
        # 1. Get previous results if needed
        prev_results = None
        if stage > 1:
            prev_results = self.stage_orchestrator.get_previous_results(job_id, stage - 1)

        # 2. Create tasks for this stage
        tasks = self.create_stage_tasks(stage, job_id, params, prev_results)

        # 3. Queue tasks (with batching if needed)
        if len(tasks) >= 50:
            result = self.queue_strategy.batch_queue_tasks(tasks)
        else:
            result = self.queue_strategy.queue_tasks(tasks)

        # 4. Update stage status
        self.stage_orchestrator.mark_stage_queued(job_id, stage, len(tasks))

        return result

    def handle_stage_completion(self, job_id: str, stage: int) -> Dict[str, Any]:
        """Handle when all tasks in a stage complete."""
        # 1. Get stage results
        task_results = self.stage_orchestrator.get_stage_task_results(job_id, stage)

        # 2. Aggregate them
        stage_result = self.aggregate_stage_results(job_id, stage, task_results)

        # 3. Decide on next action
        if self.should_advance_stage(job_id, stage, stage_result):
            next_stage = stage + 1
            self.queue_strategy.queue_job_stage(job_id, next_stage)
            return {"action": "advanced", "next_stage": next_stage}
        else:
            # Job complete
            return self.complete_job(job_id)

    def complete_job(self, job_id: str) -> Dict[str, Any]:
        """Complete the job with final aggregation."""
        all_results = self.stage_orchestrator.get_all_stage_results(job_id)
        final_result = self.aggregate_job_results(job_id, all_results)
        self.stage_orchestrator.mark_job_complete(job_id, final_result)
        return {"status": "completed", "result": final_result}

    # Abstract methods remain abstract - implemented by concrete controllers
```

### 3. Component Implementations

#### JobIdentityManager
```python
# orchestration/components/job_identity.py
import hashlib
import json
from typing import Dict, Any, Optional

class JobIdentityManager:
    """Handles job identity and idempotency."""

    def generate_job_id(self, job_type: str, parameters: Dict[str, Any]) -> str:
        """Generate deterministic job ID."""
        canonical = json.dumps({"type": job_type, "params": parameters}, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def generate_task_id(self, job_id: str, stage: int, index: int) -> str:
        """Generate semantic task ID."""
        return f"{job_id}-s{stage}-t{index}"

    def check_duplicate(self, job_id: str) -> Optional[Dict]:
        """Check if job already exists."""
        from repositories.factory import RepositoryFactory
        repo = RepositoryFactory.create_job_repository()
        existing = repo.get_job(job_id)
        return existing.dict() if existing else None
```

#### ServiceBusQueueStrategy
```python
# orchestration/components/queue_strategies.py
from typing import List, Dict, Any
from repositories.service_bus import ServiceBusRepository

class ServiceBusQueueStrategy:
    """Service Bus specific queue operations."""

    BATCH_SIZE = 100
    BATCH_THRESHOLD = 50

    def __init__(self):
        self.sb_repo = ServiceBusRepository.instance()

    def queue_job(self, job_id: str, params: Dict) -> Dict:
        """Queue a job to Service Bus."""
        message = {
            "job_id": job_id,
            "parameters": params,
            "stage": 1
        }
        result = self.sb_repo.send_message("jobs", message)
        return {"queued": True, "message_id": result}

    def queue_tasks(self, tasks: List['TaskDefinition']) -> Dict:
        """Queue tasks individually."""
        results = []
        for task in tasks:
            msg_id = self.sb_repo.send_message("tasks", task.dict())
            results.append(msg_id)
        return {"queued": len(results), "message_ids": results}

    def batch_queue_tasks(self, tasks: List['TaskDefinition']) -> Dict:
        """Queue tasks in batches."""
        results = []
        for i in range(0, len(tasks), self.BATCH_SIZE):
            batch = tasks[i:i + self.BATCH_SIZE]
            batch_result = self.sb_repo.batch_send_messages("tasks",
                [t.dict() for t in batch])
            results.append(batch_result)

        return {
            "batches": len(results),
            "total_queued": sum(r.success_count for r in results),
            "batch_results": results
        }

    def queue_job_stage(self, job_id: str, stage: int) -> Dict:
        """Queue next stage of job."""
        message = {
            "job_id": job_id,
            "stage": stage,
            "trigger": "stage_advancement"
        }
        result = self.sb_repo.send_message("jobs", message)
        return {"queued": True, "stage": stage, "message_id": result}
```

#### StageOrchestrator
```python
# orchestration/components/stage_orchestrator.py
from typing import Dict, Any, List, Optional

class StageOrchestrator:
    """Manages stage progression and results."""

    def __init__(self, job_type: str):
        self.job_type = job_type
        self.workflow = self._load_workflow(job_type)

    def _load_workflow(self, job_type: str) -> Dict:
        """Load workflow definition."""
        # Could come from config, database, or be hardcoded
        workflows = {
            "hello_world": {"stages": 2, "final_stage": 2},
            "process_raster": {"stages": 5, "final_stage": 5}
        }
        return workflows.get(job_type, {"stages": 1, "final_stage": 1})

    def get_previous_results(self, job_id: str, stage: int) -> Optional[List[Dict]]:
        """Get results from previous stage."""
        from repositories.factory import RepositoryFactory
        repo = RepositoryFactory.create_task_repository()
        tasks = repo.get_stage_tasks(job_id, stage)
        return [t.result_data for t in tasks if t.status == "completed"]

    def get_stage_task_results(self, job_id: str, stage: int) -> List[Dict]:
        """Get all task results for a stage."""
        from repositories.factory import RepositoryFactory
        repo = RepositoryFactory.create_task_repository()
        tasks = repo.get_stage_tasks(job_id, stage)
        return [t.result_data for t in tasks]

    def mark_stage_queued(self, job_id: str, stage: int, task_count: int):
        """Mark stage as queued with task count."""
        from repositories.factory import RepositoryFactory
        repo = RepositoryFactory.create_job_repository()
        repo.update_job_metadata(job_id, {
            f"stage_{stage}_status": "queued",
            f"stage_{stage}_tasks": task_count
        })

    def mark_job_complete(self, job_id: str, result: Dict):
        """Mark job as completed."""
        from repositories.factory import RepositoryFactory
        repo = RepositoryFactory.create_job_repository()
        repo.update_job_status(job_id, "completed", result)

    def is_final_stage(self, stage: int) -> bool:
        """Check if this is the final stage."""
        return stage >= self.workflow["final_stage"]
```

## 🚀 Implementation Plan

### Phase 1: Build Clean Service Bus Architecture (Day 1-2)
1. Create `interfaces/job_controller.py` with minimal interface
2. Create `orchestration/components/` with clean components:
   - `job_identity.py`
   - `queue_strategies.py`
   - `stage_orchestrator.py`
   - `result_aggregator.py`
3. Create `orchestration/service_bus_controller.py` as clean base
4. Update `ServiceBusHelloWorldController` to use new base

### Phase 2: Test and Validate (Day 2-3)
1. Test HelloWorld with new architecture
2. Create ServiceBusContainerController with clean pattern
3. Validate batching and performance
4. Ensure no dependency on BaseController cruft

### Phase 3: Create Storage Queue Version (Day 3-4)
1. Create `StorageQueueStrategy` component
2. Create `orchestration/storage_queue_controller.py`
3. Update existing controllers one by one
4. Run both patterns in parallel

### Phase 4: Remove BaseController Cruft (Day 4-5)
1. Identify all unused methods in BaseController
2. Mark as deprecated
3. Remove after all controllers migrated
4. BaseController becomes thin abstract class or interface

## 📊 Success Metrics

### Before (BaseController)
- **Lines**: 2,290
- **Methods**: 38
- **Responsibilities**: 11+
- **God Class**: YES

### After (Clean Architecture)
- **IJobController**: ~50 lines (just interface)
- **ServiceBusController**: ~200 lines (clean orchestration)
- **Components**: ~100-150 lines each (single responsibility)
- **God Class**: NO

## 🎯 Key Benefits

1. **Service Bus gets clean architecture from the start**
2. **Identify TRUE abstractions by building fresh**
3. **Storage Queue migrated to match clean pattern**
4. **BaseController shrinks from 2,290 to ~200 lines**
5. **Each component is testable, reusable, focused**

## 💡 Example: Clean HelloWorld Controller

```python
from orchestration.service_bus_controller import ServiceBusController

class ServiceBusHelloWorldController(ServiceBusController):
    """Clean, focused HelloWorld controller."""

    def __init__(self):
        super().__init__(job_type="sb_hello_world")

    def validate_job_parameters(self, params: Dict) -> Dict:
        return {
            "n": min(1000, max(1, params.get("n", 3))),
            "message": params.get("message", "Hello Service Bus")
        }

    def create_stage_tasks(self, stage: int, job_id: str, params: Dict,
                          prev_results: Optional[List] = None) -> List[TaskDefinition]:
        tasks = []
        n = params["n"]

        if stage == 1:
            for i in range(n):
                tasks.append(TaskDefinition(
                    task_id=f"{job_id}-s1-t{i}",
                    task_type="greeting",
                    parameters={"index": i, "message": params["message"]}
                ))
        elif stage == 2:
            for i in range(n):
                tasks.append(TaskDefinition(
                    task_id=f"{job_id}-s2-t{i}",
                    task_type="reply",
                    parameters={"index": i}
                ))

        return tasks

    def should_advance_stage(self, job_id: str, current: int, results: Dict) -> bool:
        return current < 2

    def aggregate_stage_results(self, job_id: str, stage: int,
                               task_results: List[Dict]) -> Dict:
        return {
            "stage": stage,
            "completed_tasks": len(task_results),
            "success": all(t.get("success") for t in task_results)
        }
```

That's it! Clean, simple, focused. No 38-method God Class inheritance.

## 🏁 Next Steps

1. **Approve approach** - Confirm this clean architecture strategy
2. **Start with IJobController** - Define the minimal interface
3. **Build Service Bus clean** - No BaseController dependency
4. **Test and iterate** - Prove the pattern works
5. **Retrofit Storage Queue** - Match the clean pattern
6. **Delete the cruft** - Remove 2,000+ lines from BaseController

This approach ensures Service Bus is built RIGHT from the start, and we can then clean up the legacy code to match.