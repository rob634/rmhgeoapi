# Core Machine Architecture: Separating Instructions from Machinery

**Author**: Robert and Geospatial Claude Legion
**Date**: 29 SEP 2025
**Purpose**: Define the vision for abstracting all orchestration machinery into core classes, leaving job-specific code as pure declarations

## Executive Summary

The fundamental principle: **Job-specific code should be declarative instructions, not imperative machinery**.

Currently, job controllers contain ~1,000 lines of orchestration code that's identical across all jobs. This violates DRY and makes job creation complex. The vision is to abstract ALL machinery into core classes, leaving job-specific code as simple declarations of what to do, not how to do it.

## The Problem: Current State

### What's Currently in Job Controllers (BAD)
```python
# controller_service_bus_hello.py - 1,019 lines!
class ServiceBusHelloWorldController:
    # ❌ 200+ lines of stage advancement logic
    # ❌ 100+ lines of job completion logic
    # ❌ 250+ lines of task queuing logic
    # ❌ 150+ lines of batch processing logic
    # ❌ Error handling, retries, status updates...
    # ✅ Only ~50 lines of actual job-specific logic
```

### The Same Code Repeated in EVERY Controller
- Stage advancement: "if all tasks done, advance stage"
- Job completion: "if final stage done, complete job"
- Task distribution: "if >50 tasks, use batching"
- Error handling: "if task fails, mark failed"

This machinery is **identical for every job** but copy-pasted into each controller!

## The Vision: Pure Declaration

### What Job-Specific Code SHOULD Look Like
```python
# hello_world_job.py - ~50 lines total!
class HelloWorldJob:
    """Pure declaration - WHAT this job does, not HOW"""

    # Job metadata
    JOB_TYPE = "hello_world"
    BATCH_THRESHOLD = 50

    # Stage definitions (declarative)
    STAGES = [
        {
            "number": 1,
            "name": "greeting",
            "task_type": "hello_world_greeting",
            "parallelism": "dynamic",  # Creates n tasks based on params
            "count_param": "n"         # Which parameter controls count
        },
        {
            "number": 2,
            "name": "reply",
            "task_type": "hello_world_reply",
            "parallelism": "match_previous",  # Same count as stage 1
            "depends_on": 1,
            "uses_lineage": True  # Access predecessor results
        }
    ]

    # Parameter schema
    PARAMETERS = {
        "n": {"type": "int", "min": 1, "max": 1000, "default": 3},
        "message": {"type": "str", "default": "Hello World"}
    }

    # The ONLY custom logic - task creation
    def create_tasks_for_stage(self, stage: int, params: dict) -> List[TaskDefinition]:
        """Generate task definitions for a stage"""
        n = params.get('n', 3)

        if stage == 1:
            return [
                TaskDefinition(
                    task_id=f"greet_{i}",
                    parameters={"index": i, "message": params['message']}
                )
                for i in range(n)
            ]
        elif stage == 2:
            return [
                TaskDefinition(
                    task_id=f"reply_{i}",
                    parameters={"index": i}
                )
                for i in range(n)
            ]
```

### Business Logic Handlers (Separate File)
```python
# service_hello_world.py
@register_handler("hello_world_greeting")
def handle_greeting(params: dict) -> dict:
    """Pure business logic - no orchestration"""
    return {
        "greeting": f"Hello from task {params['index']}",
        "timestamp": datetime.now().isoformat()
    }

@register_handler("hello_world_reply")
def handle_reply(params: dict, context: TaskContext) -> dict:
    """Can access predecessor via context"""
    predecessor = context.get_predecessor_result()
    return {
        "reply": f"Replying to: {predecessor['greeting']}",
        "timestamp": datetime.now().isoformat()
    }
```

## What Moves to Core Classes

### 1. CoreMachine (New Class)
**Purpose**: Contains ALL generic orchestration machinery

```python
class CoreMachine:
    """
    The universal orchestration engine.
    Works identically for ALL jobs - no job-specific code here.
    """

    def __init__(self, job_declaration: JobDeclaration):
        self.job = job_declaration
        self.state_manager = StateManager()
        self.orchestrator = OrchestrationManager()

    def process_job_message(self, message: JobQueueMessage):
        """Generic job processing - same for ALL jobs"""
        # 1. Validate message
        # 2. Create tasks from declaration
        # 3. Queue tasks (batch or individual)
        # 4. Update status
        # All generic - no job-specific code!

    def process_task_message(self, message: TaskQueueMessage):
        """Generic task processing - same for ALL jobs"""
        # 1. Get handler from registry
        # 2. Execute with context
        # 3. Check stage completion
        # 4. Advance or complete job
        # All generic - no job-specific code!

    def handle_stage_completion(self, stage: int, job_id: str):
        """Generic stage advancement - same for ALL jobs"""
        if self.should_advance_stage(stage):
            self.queue_next_stage(stage + 1)
        elif self.is_final_stage(stage):
            self.complete_job(job_id)

    def queue_tasks(self, tasks: List[TaskDefinition]):
        """Generic task distribution - same for ALL jobs"""
        if len(tasks) >= self.job.BATCH_THRESHOLD:
            return self.batch_queue_tasks(tasks)
        else:
            return self.individual_queue_tasks(tasks)
```

### 2. StateManager (Enhanced)
**Already has**: Database operations, advisory locks
**Should add**: Generic stage advancement, job completion

```python
class StateManager:
    def advance_stage_generic(self, job_id: str, current_stage: int):
        """Works for ANY job - not job-specific"""
        # Check if all tasks complete
        # Update job stage
        # Queue next stage message

    def complete_job_generic(self, job_id: str):
        """Works for ANY job - not job-specific"""
        # Get all task results
        # Call aggregation function
        # Mark job complete
        # Trigger notifications
```

### 3. OrchestrationManager (Enhanced)
**Already has**: Dynamic task creation
**Should add**: Batch vs individual decisions, retry logic

```python
class OrchestrationManager:
    def determine_distribution_strategy(self, task_count: int) -> str:
        """Decides how to queue tasks - same for ALL jobs"""
        if task_count >= BATCH_THRESHOLD:
            return "batch"
        else:
            return "individual"

    def handle_task_failure(self, task: TaskRecord):
        """Generic retry logic - same for ALL jobs"""
        if task.retry_count < MAX_RETRIES:
            self.queue_retry(task)
        else:
            self.mark_permanently_failed(task)
```

## Implementation Roadmap

### Phase 1: Create CoreMachine Class
1. Extract all generic orchestration from `controller_service_bus_hello.py`
2. Move to new `core_machine.py` class
3. Make controller inherit from CoreMachine

### Phase 2: Refactor Existing Controllers
1. Remove all generic code from job controllers
2. Leave only job declarations and task creation
3. Each controller should shrink from ~1,000 lines to ~50 lines

### Phase 3: Create Job Declaration Schema
1. Define Pydantic model for job declarations
2. Validate stage definitions, parameters, etc.
3. Enable JSON/YAML job definitions

### Phase 4: Job Registry
1. Auto-discover job declarations
2. Register handlers automatically
3. Support hot-reloading of job definitions

## Success Metrics

### Before (Current State)
- New job requires: ~1,000 lines of code
- Bug fixes needed in: Every controller
- Testing required for: Each controller's orchestration
- Time to add new job: Days

### After (Target State)
- New job requires: ~50 lines of declarations
- Bug fixes needed in: One place (CoreMachine)
- Testing required for: Business logic only
- Time to add new job: Minutes

## Example: Complete Job Implementation (After Refactoring)

```python
# complete_hello_world.py - THE ENTIRE FILE!

from core_machine import JobDeclaration, register_job

@register_job
class HelloWorldJob(JobDeclaration):
    TYPE = "hello_world"
    STAGES = 2
    BATCH_THRESHOLD = 50

    def create_stage_tasks(self, stage: int, params: dict):
        n = params['n']
        if stage == 1:
            return [f"greet_{i}" for i in range(n)]
        elif stage == 2:
            return [f"reply_{i}" for i in range(n)]

# That's it! 13 lines for a complete job definition!
# All orchestration handled by CoreMachine
```

## Key Principles

1. **Separation of Concerns**: Business logic vs orchestration machinery
2. **DRY**: Write orchestration once, use everywhere
3. **Declarative > Imperative**: Describe what, not how
4. **Convention over Configuration**: Smart defaults
5. **Testability**: Test machinery once, test business logic separately

## Migration Strategy

1. **Don't break existing code**: Keep BaseController working
2. **Parallel implementation**: Build CoreMachine alongside
3. **Gradual migration**: Move one controller at a time
4. **Validate equivalence**: Ensure same behavior

## Conclusion

The current architecture mixes instructions with machinery, creating 1,000-line controllers that are 95% boilerplate. By extracting all orchestration into CoreMachine, we can reduce job definitions to their essence: what tasks to create and what business logic to run.

This isn't just about reducing code - it's about making the system comprehensible. When a developer looks at a job definition, they should see the business logic, not the plumbing. The machinery should be invisible, reliable, and shared across all jobs.

**The goal: Adding a new job should require writing ONLY what makes that job unique, nothing more.**

---

*"The best code is no code. The second best is declarative code. The worst is imperative orchestration code copy-pasted into every controller."* - Architecture Principle