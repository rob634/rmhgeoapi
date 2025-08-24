# Job vs Task Architecture Guidelines

## Executive Summary

Based on the review of your Controller→Service→Repository pattern, I recommend establishing a **strict separation between Jobs and Tasks** where:

- **Jobs** = Controller-level orchestration (user-facing, application state)
- **Tasks** = Service-level processing units (geospatial operations)

This creates consistency: **1 raster = 1 job + 1 task**, **N rasters = 1 job + N tasks**

## Core Architectural Rules

### 1. Jobs (Controller Layer)
Jobs represent **user intent** and **application state**:

```python
class Job:
    """
    Jobs are controller-level entities that:
    - Accept user requests
    - Track overall progress
    - Manage application state
    - Handle authentication/authorization
    - Return results to users
    """
    
    # Job responsibilities:
    - Request validation
    - Idempotency (SHA256 deduplication)
    - User-facing status reporting
    - Result aggregation
    - Error handling strategy
    - Retry policies
```

### 2. Tasks (Service Layer)
Tasks represent **atomic processing units**:

```python
class Task:
    """
    Tasks are service-level entities that:
    - Perform actual geospatial operations
    - Are stateless and atomic
    - Can be parallelized
    - Have clear inputs/outputs
    - Are technology-agnostic
    """
    
    # Task responsibilities:
    - Actual processing (COG conversion, reprojection, etc.)
    - Resource management (memory, disk)
    - Progress reporting to parent job
    - Output validation
    - Cleanup operations
```

## Proposed Implementation

### Abstract Base Classes

```python
# controllers/base_controller.py
from abc import ABC, abstractmethod
from typing import List, Dict, Any

class BaseJobController(ABC):
    """
    Base controller for all job types.
    Enforces job → task(s) pattern.
    """
    
    @abstractmethod
    def validate_request(self, request: Dict[str, Any]) -> bool:
        """Validate incoming request parameters"""
        pass
    
    @abstractmethod
    def create_tasks(self, job_id: str, request: Dict[str, Any]) -> List[str]:
        """
        Create task(s) for this job.
        MUST create at least one task, even for single operations.
        """
        pass
    
    @abstractmethod
    def aggregate_results(self, task_results: List[Dict]) -> Dict:
        """Aggregate task results into job result"""
        pass
    
    def process_job(self, request: Dict[str, Any]) -> str:
        """
        Standard job processing flow:
        1. Validate request
        2. Create job record
        3. Generate task(s)
        4. Queue task(s)
        5. Return job ID
        """
        # Validate
        if not self.validate_request(request):
            raise ValueError("Invalid request")
        
        # Create job
        job_id = self.generate_job_id(request)
        self.job_repo.create_job(job_id, request)
        
        # Create tasks (MUST create at least one)
        task_ids = self.create_tasks(job_id, request)
        if not task_ids:
            raise ValueError("Job must create at least one task")
        
        # Queue tasks
        for task_id in task_ids:
            self.queue_task(task_id)
        
        return job_id
```

```python
# services/base_service.py
from abc import ABC, abstractmethod

class BaseTaskService(ABC):
    """
    Base service for all task processing.
    Tasks are atomic units of work.
    """
    
    @abstractmethod
    def validate_inputs(self, **kwargs) -> bool:
        """Validate task can be processed"""
        pass
    
    @abstractmethod
    def process(self, task_id: str, **kwargs) -> Dict:
        """
        Process the task.
        MUST be atomic and idempotent.
        """
        pass
    
    @abstractmethod
    def validate_outputs(self, outputs: Dict) -> bool:
        """Validate task outputs before completion"""
        pass
    
    def execute_task(self, task_id: str, **kwargs) -> Dict:
        """
        Standard task execution flow:
        1. Validate inputs
        2. Process
        3. Validate outputs
        4. Update task status
        """
        try:
            # Validate
            if not self.validate_inputs(**kwargs):
                raise ValueError("Invalid task inputs")
            
            # Process
            result = self.process(task_id, **kwargs)
            
            # Validate outputs
            if not self.validate_outputs(result):
                raise ValueError("Task outputs failed validation")
            
            # Update status
            self.task_repo.update_task_status(task_id, "completed", result)
            
            return result
            
        except Exception as e:
            self.task_repo.update_task_status(task_id, "failed", {"error": str(e)})
            raise
```

### Example Implementations

#### Single Raster COG Conversion

```python
class COGConversionController(BaseJobController):
    """Controller for COG conversion jobs"""
    
    def validate_request(self, request: Dict) -> bool:
        return all(k in request for k in ['dataset_id', 'resource_id'])
    
    def create_tasks(self, job_id: str, request: Dict) -> List[str]:
        """Single raster = single task"""
        task_id = self.generate_task_id(job_id, "cog_conversion", 0)
        
        task_data = {
            'operation': 'cog_conversion',
            'input_container': request['dataset_id'],
            'input_blob': request['resource_id'],
            'output_container': 'rmhazuregeosilver',
            'parent_job_id': job_id
        }
        
        self.task_repo.create_task(task_id, job_id, task_data)
        return [task_id]
    
    def aggregate_results(self, task_results: List[Dict]) -> Dict:
        # Single task, single result
        return task_results[0] if task_results else {}
```

#### Tiled Raster Processing (Multiple Tasks)

```python
class TiledRasterController(BaseJobController):
    """Controller for tiled raster processing"""
    
    def validate_request(self, request: Dict) -> bool:
        return 'tiling_plan_id' in request or 'tiles' in request
    
    def create_tasks(self, job_id: str, request: Dict) -> List[str]:
        """Multiple tiles = multiple tasks"""
        # Get tiling plan
        tiles = self.get_tiles(request)
        
        task_ids = []
        for idx, tile in enumerate(tiles):
            task_id = self.generate_task_id(job_id, f"tile_{tile['id']}", idx)
            
            task_data = {
                'operation': 'process_tile',
                'tile_geometry': tile['geometry'],
                'tile_id': tile['id'],
                'parent_job_id': job_id,
                **request  # Pass through other params
            }
            
            self.task_repo.create_task(task_id, job_id, task_data)
            task_ids.append(task_id)
        
        return task_ids
    
    def aggregate_results(self, task_results: List[Dict]) -> Dict:
        """Aggregate tile results"""
        return {
            'total_tiles': len(task_results),
            'successful': sum(1 for r in task_results if r.get('status') == 'success'),
            'failed': sum(1 for r in task_results if r.get('status') == 'failed'),
            'output_files': [r.get('output_file') for r in task_results]
        }
```

### Enforcing the Pattern

```python
# decorators.py
def requires_task(func):
    """
    Decorator to enforce that service operations must be tasks.
    Prevents direct service calls without task context.
    """
    def wrapper(self, *args, **kwargs):
        if 'task_id' not in kwargs:
            raise ValueError(
                f"{func.__name__} must be called as a task. "
                "Use a controller to create a job and task."
            )
        return func(self, *args, **kwargs)
    return wrapper

# Usage in services
class RasterProcessorService(BaseTaskService):
    
    @requires_task
    def process(self, task_id: str, **kwargs):
        """This can only be called with a task_id"""
        # Processing logic here
        pass
```

## Migration Strategy

### Phase 1: Add Task Wrapper for Existing Operations
```python
class LegacyAdapter(BaseJobController):
    """Adapter to wrap existing services in job/task pattern"""
    
    def create_tasks(self, job_id: str, request: Dict) -> List[str]:
        # Create single task for legacy operation
        task_id = f"{job_id}_task"
        self.task_repo.create_task(task_id, job_id, request)
        return [task_id]
```

### Phase 2: Refactor Services to Task Pattern
- Update each service to inherit from `BaseTaskService`
- Add `@requires_task` decorator to processing methods
- Ensure all operations create tasks

### Phase 3: Enforce at Queue Level
```python
# function_app.py
@app.queue_trigger(name="msg", queue_name="geospatial-jobs")
def process_job_queue(msg: func.QueueMessage) -> None:
    """Jobs queue - creates tasks"""
    controller = ControllerFactory.get_controller(operation_type)
    job_id = controller.process_job(request)
    # Controller creates and queues tasks

@app.queue_trigger(name="msg", queue_name="geospatial-tasks")  
def process_task_queue(msg: func.QueueMessage) -> None:
    """Tasks queue - does actual work"""
    service = ServiceFactory.get_service(operation_type)
    result = service.execute_task(task_id, **params)
    # Service processes individual task
```

## Benefits of This Architecture

1. **Consistency**: Every operation follows the same pattern
2. **Scalability**: Tasks can be parallelized across workers
3. **Observability**: Clear job→task hierarchy for monitoring
4. **Fault Tolerance**: Failed tasks don't fail entire job
5. **Reusability**: Tasks can be reused across different job types
6. **Testing**: Controllers and services can be tested independently

## Practical Examples

### What Changes

**Before (inconsistent):**
```python
# Sometimes direct service call
result = RasterProcessorService().process(job_id, dataset_id, resource_id)

# Sometimes creates tasks
TiledRasterProcessor().process(job_id, dataset_id, tiles=tiles)
```

**After (consistent):**
```python
# Always: Controller → Job → Task(s) → Service

# Single raster
job_id = COGConversionController().process_job({
    'dataset_id': 'bronze',
    'resource_id': 'file.tif'
})
# Creates: 1 job, 1 task

# Multiple rasters  
job_id = BatchCOGController().process_job({
    'dataset_id': 'bronze',
    'resource_ids': ['file1.tif', 'file2.tif', 'file3.tif']
})
# Creates: 1 job, 3 tasks

# Tiled raster
job_id = TiledRasterController().process_job({
    'dataset_id': 'bronze',
    'resource_id': 'huge.tif',
    'tiling_plan_id': 'plan_123'
})
# Creates: 1 job, 35 tasks (one per tile)
```

## Decision Points

### When to Create Multiple Tasks?

Create multiple tasks when:
- Processing can be parallelized (tiles, multiple files)
- Inputs are independent
- Partial failure is acceptable
- Results can be aggregated

Keep as single task when:
- Operation is inherently sequential
- Intermediate state must be maintained
- Transaction semantics required
- Overhead of task creation exceeds benefit

### Task Granularity

**Too Fine**: Creating a task for every 1MB chunk
- High overhead
- Queue congestion
- Difficult aggregation

**Too Coarse**: Single task for 100GB file
- No parallelization
- Long running operations
- Difficult retry

**Just Right**: Task per logical unit
- Tile (2-10GB each)
- File (for batch operations)
- Processing stage (validate → reproject → convert)

## Implementation Checklist

- [ ] Create `BaseJobController` abstract class
- [ ] Create `BaseTaskService` abstract class  
- [ ] Add `@requires_task` decorator
- [ ] Update `ServiceFactory` to check for task context
- [ ] Refactor existing services to inherit from `BaseTaskService`
- [ ] Create controllers for each operation type
- [ ] Update queue handlers to enforce separation
- [ ] Add job→task relationship tracking in repositories
- [ ] Update monitoring to show job/task hierarchy
- [ ] Document the pattern for team

## Summary

By enforcing that **all geospatial operations must be tasks**, you achieve:

1. **Architectural Consistency**: One pattern to rule them all
2. **Clear Boundaries**: Controllers orchestrate, services process
3. **Better Observability**: Job/task hierarchy is explicit
4. **Improved Scalability**: Natural parallelization points
5. **Easier Testing**: Mock tasks for controller tests, mock repos for service tests

The key insight: **Jobs are about orchestration, Tasks are about execution**. This separation makes your system more maintainable, scalable, and predictable.