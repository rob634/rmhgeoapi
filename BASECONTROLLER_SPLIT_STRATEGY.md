# BaseController Split Strategy - Minimal Refactor

**Date**: 26 SEP 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: PROPOSED - Split BaseController into Core + Queue Components

## 🎯 The Strategy

Split BaseController into TWO classes:
1. **CoreController** - The REAL abstract base (5 methods + contracts)
2. **QueueStorageController** - Queue Storage specific God Class (inherits from CoreController)

This allows Service Bus to inherit ONLY CoreController without the Queue Storage baggage!

## 🏗️ Architecture

```
                    CoreController (ABC)
                    - 5 abstract methods
                    - Contract enforcement
                    - Pydantic models
                         /        \
                        /          \
        QueueStorageController    ServiceBusController
        - 33 queue methods         - Clean implementation
        - process_job_queue        - Own process methods
        - process_task_queue       - Batch optimizations
```

## 📦 Implementation Plan

### Step 1: Create CoreController (Abstract Base)

```python
# controller_core.py
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from schema_base import (
    JobExecutionContext, StageResultContract,
    TaskResult, TaskDefinition
)
from utils.contract_validator import enforce_contract

class CoreController(ABC):
    """
    Core controller contract - the TRUE abstraction.

    Contains ONLY the essential abstract methods and
    contract enforcement that ALL controllers need.
    """

    def __init__(self):
        """Initialize core controller components."""
        from util_logger import LoggerFactory, ComponentType
        self.logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            self.__class__.__name__
        )
        self._job_type = None  # Set by concrete controller

    # ========================================================================
    # CORE ABSTRACT METHODS - The Essential Contract
    # ========================================================================

    @abstractmethod
    def get_job_type(self) -> str:
        """Return the job type identifier."""
        pass

    @abstractmethod
    def validate_job_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and normalize job parameters.

        Args:
            parameters: Raw job parameters

        Returns:
            Validated and normalized parameters
        """
        pass

    @abstractmethod
    def create_stage_tasks(
        self,
        stage_number: int,
        job_id: str,
        job_parameters: Dict[str, Any],
        previous_stage_results: Optional[List[Dict[str, Any]]] = None
    ) -> List[TaskDefinition]:
        """
        Create task definitions for a stage.

        Args:
            stage_number: Current stage number
            job_id: Job identifier
            job_parameters: Validated job parameters
            previous_stage_results: Results from previous stage

        Returns:
            List of TaskDefinition objects
        """
        pass

    @abstractmethod
    def should_advance_stage(
        self,
        job_id: str,
        current_stage: int,
        stage_results: Dict[str, Any]
    ) -> bool:
        """
        Determine if job should advance to next stage.

        Args:
            job_id: Job identifier
            current_stage: Current stage number
            stage_results: Results from current stage

        Returns:
            True if should advance, False if job complete
        """
        pass

    @enforce_contract(
        params={
            'job_id': str,
            'stage_number': int,
            'task_results': list
        },
        returns=Dict[str, Any]
    )
    def aggregate_stage_results(
        self,
        job_id: str,
        stage_number: int,
        task_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Aggregate task results for a stage.

        Default implementation uses StageResultContract for consistency.
        Override if custom aggregation needed.

        Args:
            job_id: Job identifier
            stage_number: Stage number
            task_results: List of task results

        Returns:
            Aggregated stage results following StageResultContract
        """
        # Convert to TaskResult objects
        task_result_objects = []
        for task_data in task_results:
            if isinstance(task_data, TaskResult):
                task_result_objects.append(task_data)
            else:
                # Convert dict to TaskResult
                try:
                    task_result = TaskResult(**task_data)
                    task_result_objects.append(task_result)
                except Exception as e:
                    self.logger.warning(f"Could not convert: {e}")

        # Use StageResultContract for consistent structure
        stage_result = StageResultContract.from_task_results(
            stage_number=stage_number,
            task_results=task_result_objects,
            metadata={"job_id": job_id}
        )

        return stage_result.model_dump(mode='json')

    @abstractmethod
    def aggregate_job_results(
        self,
        context: JobExecutionContext
    ) -> Dict[str, Any]:
        """
        Aggregate all stage results into final job result.

        Args:
            context: Job execution context with all stage results

        Returns:
            Final aggregated job results
        """
        pass

    # ========================================================================
    # SHARED UTILITIES - Common to all controllers
    # ========================================================================

    def generate_job_id(self, parameters: Dict[str, Any]) -> str:
        """Generate deterministic job ID using SHA256."""
        import hashlib
        import json

        canonical_params = {
            "job_type": self.get_job_type(),
            "parameters": parameters
        }
        canonical_json = json.dumps(canonical_params, sort_keys=True)
        return hashlib.sha256(canonical_json.encode()).hexdigest()

    def generate_task_id(
        self,
        job_id: str,
        stage: int,
        semantic_index: str
    ) -> str:
        """Generate semantic task ID."""
        return f"{job_id}-s{stage}-{semantic_index}"
```

### Step 2: Rename BaseController to QueueStorageController

```python
# controller_queue_storage.py
from controller_core import CoreController
from typing import Dict, Any
from schema_queue import JobQueueMessage, TaskQueueMessage

class QueueStorageController(CoreController):
    """
    Queue Storage specific controller.

    Contains all the Queue Storage specific logic that was in BaseController.
    This is the "God Class" with 33+ methods for Queue Storage operations.
    """

    def __init__(self):
        """Initialize queue storage controller."""
        super().__init__()
        self.processing_path = 'queue_storage'

    # All 33+ Queue Storage specific methods from BaseController
    def process_job_queue_message(
        self,
        job_message: JobQueueMessage
    ) -> Dict[str, Any]:
        """250+ lines of Queue Storage specific processing."""
        # ... existing implementation
        pass

    def process_task_queue_message(
        self,
        task_message: TaskQueueMessage
    ) -> Dict[str, Any]:
        """240+ lines of Queue Storage specific processing."""
        # ... existing implementation
        pass

    # ... all other Queue Storage methods
```

### Step 3: Update ServiceBusBaseController

```python
# controller_service_bus.py
from controller_core import CoreController  # NOT BaseController!
from typing import Dict, Any, List, Optional
from schema_base import TaskDefinition
from repositories.factory import RepositoryFactory

class ServiceBusBaseController(CoreController):
    """
    Service Bus controller - CLEAN implementation.

    Inherits ONLY CoreController, not the Queue Storage God Class.
    """

    BATCH_SIZE = 100
    BATCH_THRESHOLD = 50

    def __init__(self):
        """Initialize Service Bus controller."""
        super().__init__()
        self.processing_path = 'service_bus'
        self.batch_metrics = []

    def process_service_bus_job(
        self,
        job_message: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        CLEAN Service Bus job processing - 50 lines not 250!

        No Queue Storage baggage, just clean Service Bus logic.
        """
        job_id = job_message['job_id']
        stage = job_message['stage']
        params = job_message['parameters']

        # 1. Validate parameters
        validated = self.validate_job_parameters(params)

        # 2. Create tasks for stage
        tasks = self.create_stage_tasks(stage, job_id, validated)

        # 3. Queue tasks (with batching if needed)
        if len(tasks) >= self.BATCH_THRESHOLD:
            result = self._batch_queue_tasks(tasks)
        else:
            result = self._queue_tasks_individually(tasks)

        return result

    def process_service_bus_task(
        self,
        task_message: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        CLEAN Service Bus task processing - 50 lines not 240!
        """
        # Clean implementation without Queue Storage cruft
        pass

    def _batch_queue_tasks(
        self,
        tasks: List[TaskDefinition]
    ) -> Dict[str, Any]:
        """Service Bus batch processing."""
        # Existing batch implementation
        pass
```

### Step 4: Update Existing Controllers

```python
# For Queue Storage controllers
from controller_queue_storage import QueueStorageController

class HelloWorldController(QueueStorageController):
    """Existing controller keeps working unchanged."""
    # No changes needed!
    pass

# For Service Bus controllers
from controller_service_bus import ServiceBusBaseController

class ServiceBusHelloWorldController(ServiceBusBaseController):
    """Clean Service Bus implementation."""
    # Already clean!
    pass
```

## 🎯 Benefits

### Immediate Benefits:
1. **Service Bus gets clean architecture** - No Queue Storage baggage
2. **Zero breaking changes** - Existing controllers keep working
3. **Clear separation** - Queue Storage vs Service Bus logic separated
4. **Easier testing** - Can test CoreController contract independently

### Migration Path:
1. **Phase 1**: Create CoreController with 5 abstract methods
2. **Phase 2**: Copy BaseController → QueueStorageController (inherits CoreController)
3. **Phase 3**: Update ServiceBusBaseController to inherit CoreController
4. **Phase 4**: Update imports for existing controllers
5. **Phase 5**: Gradually refactor QueueStorageController to be cleaner

## 📊 Result

### Before:
```
BaseController (2,290 lines, 38 methods)
    ↓
ServiceBusBaseController (inherits ALL 38 methods)
```

### After:
```
CoreController (200 lines, 5 abstract + utilities)
    ↓                           ↓
QueueStorageController      ServiceBusBaseController
(2,090 lines, 33 methods)   (400 lines, clean)
```

## 🚀 Implementation Steps

1. **Create `controller_core.py`** (1 hour)
   - Extract 5 abstract methods
   - Keep contract enforcement
   - Add shared utilities (ID generation)

2. **Copy `controller_base.py` → `controller_queue_storage.py`** (30 min)
   - Change class name to QueueStorageController
   - Inherit from CoreController
   - Remove duplicate abstract methods

3. **Update `controller_service_bus.py`** (30 min)
   - Change inheritance to CoreController
   - Remove any BaseController references
   - Test Service Bus still works

4. **Update existing controllers** (1 hour)
   - Change imports from BaseController to QueueStorageController
   - Test all existing functionality

5. **Mark BaseController as deprecated** (10 min)
   - Add deprecation warning
   - Plan removal after migration

## 🏆 End Result

- **CoreController**: Clean 200-line abstraction with contracts
- **ServiceBusBaseController**: Clean 400-line implementation
- **QueueStorageController**: Contains the God Class (for now)
- **Clear path forward**: Can refactor QueueStorageController gradually

This approach:
- ✅ Preserves all contract enforcement (ABC + Pydantic + @enforce_contract)
- ✅ Service Bus gets clean architecture immediately
- ✅ Zero breaking changes for existing code
- ✅ Sets up for gradual QueueStorageController refactoring