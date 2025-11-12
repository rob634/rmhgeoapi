# Task Registry Pattern - Core Architecture

**Date**: 4 OCT 2025
**Author**: Robert and Geospatial Claude Legion

## 🎯 Overview

The **Task Registry Pattern** is the core architectural pattern enabling dynamic job-specific behavior injection into a generic orchestration engine (CoreMachine). This pattern eliminates tight coupling while maintaining extensibility and type safety.

---

## 🏗️ Architecture Pattern

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                     HTTP Request                            │
│                  /api/jobs/hello_world                      │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                  JobRegistry (Singleton)                    │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Registry Map:                                        │  │
│  │  {                                                    │  │
│  │    "hello_world": HelloWorldJob,                     │  │
│  │    "list_container": ListContainerJob,               │  │
│  │    "stage_raster": StageRasterJob                    │  │
│  │  }                                                    │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────┬───────────────────────────────────────┘
                      │ .get_job_class("hello_world")
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              CoreMachine (Generic Orchestrator)             │
│                                                             │
│  1. job_class = registry.get("hello_world")                │
│  2. job_handler = job_class()                              │
│  3. tasks = job_handler.create_stage_1_tasks(context)      │
│  4. submit tasks to queue                                  │
│  5. wait for completion                                    │
│  6. results = job_handler.aggregate_stage_results()        │
│  7. advance = job_handler.should_advance_stage()           │
│                                                             │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              HelloWorldJob (Job-Specific Logic)             │
│                                                             │
│  def create_stage_1_tasks(context):                        │
│      return [TaskDefinition(                               │
│          task_type="greet",                                │
│          parameters={"message": "Hello"}                   │
│      )]                                                    │
│                                                             │
│  def aggregate_stage_results(results):                     │
│      return {"greeting": results[0]["output"]}            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔑 Key Design Principles

### 1. **Composition Over Inheritance**

CoreMachine **composes** with job handlers dynamically, rather than inheriting from them.

```python
# ❌ BAD: Tight coupling via inheritance
class CoreMachine(HelloWorldJob):
    def execute(self):
        self.create_tasks()  # Which job's tasks?

# ✅ GOOD: Loose coupling via composition
class CoreMachine:
    def execute(self, job_type: str):
        job_class = JobRegistry.get(job_type)
        job_handler = job_class()
        tasks = job_handler.create_stage_1_tasks(context)
```

**Benefits:**
- CoreMachine remains job-agnostic
- Add new jobs without modifying CoreMachine
- Test jobs in isolation

---

### 2. **Decorator-Based Registration**

Jobs self-register using Python decorators at import time.

```python
@JobRegistry.instance().register(job_type="hello_world")
class HelloWorldJob:
    """Job-specific implementation for hello_world workflow."""

    def create_stage_1_tasks(self, context: JobContext) -> List[TaskDefinition]:
        """Define WHAT tasks to create for this job type."""
        return [
            TaskDefinition(
                task_type="greet",
                parameters={"message": context.job_params.get("message", "Hello")}
            )
        ]
```

**Registration happens automatically when the module imports:**
```python
# function_app.py or jobs/__init__.py
from jobs.hello_world import HelloWorldJob  # Registration happens here!
```

---

### 3. **Singleton Registry Pattern**

The registry is a singleton ensuring one source of truth for job mappings.

```python
class JobRegistry:
    _instance = None

    @classmethod
    def instance(cls) -> 'JobRegistry':
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._jobs: Dict[str, Type] = {}

    def register(self, job_type: str):
        """Decorator to register a job class."""
        def decorator(job_class):
            self._jobs[job_type] = job_class
            return job_class
        return decorator

    def get_job_class(self, job_type: str) -> Type:
        """Lookup job class by type string."""
        if job_type not in self._jobs:
            raise ValueError(f"Unknown job type: {job_type}")
        return self._jobs[job_type]
```

---

## 🔄 Request Flow

### Step-by-Step Execution

```
1. HTTP Request arrives
   POST /api/jobs/hello_world
   {"message": "Welcome"}

2. Trigger extracts job_type
   job_type = "hello_world"

3. Registry lookup
   job_class = JobRegistry.instance().get_job_class("hello_world")
   # Returns: HelloWorldJob

4. Instantiate job handler
   job_handler = job_class()
   # Creates: HelloWorldJob()

5. CoreMachine calls job-specific methods
   tasks = job_handler.create_stage_1_tasks(context)
   # Returns: [TaskDefinition(task_type="greet", ...)]

6. CoreMachine submits tasks to queue
   for task in tasks:
       task_queue.send_message(task)

7. Task processors execute
   result = GreetTaskHandler.execute(task)

8. CoreMachine aggregates results
   final = job_handler.aggregate_stage_results(results)

9. CoreMachine checks stage advancement
   if job_handler.should_advance_stage(context):
       advance_to_stage_2()
```

---

## 📋 Job Handler Contract

Every job handler must implement this interface:

```python
class JobHandlerProtocol:
    """Protocol defining required methods for job handlers."""

    def create_stage_tasks(
        self,
        stage: int,
        context: JobContext
    ) -> List[TaskDefinition]:
        """
        Create tasks for a specific stage.

        Args:
            stage: Stage number (1, 2, 3, ...)
            context: Job execution context with parameters and previous results

        Returns:
            List of task definitions to execute in parallel
        """
        ...

    def aggregate_stage_results(
        self,
        stage: int,
        results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Aggregate results from all tasks in a stage.

        Args:
            stage: Completed stage number
            results: Results from all tasks in the stage

        Returns:
            Aggregated results for this stage
        """
        ...

    def should_advance_stage(
        self,
        stage: int,
        context: JobContext
    ) -> bool:
        """
        Determine if job should advance to next stage.

        Args:
            stage: Current stage number
            context: Job execution context

        Returns:
            True if should advance, False if job is complete
        """
        ...

    def get_final_result(
        self,
        context: JobContext
    ) -> Dict[str, Any]:
        """
        Generate final job result from all stage results.

        Args:
            context: Complete job execution context

        Returns:
            Final job result
        """
        ...
```

---

## 🌟 Real-World Examples

### Example 1: Simple Single-Stage Job

```python
@JobRegistry.instance().register(job_type="hello_world")
class HelloWorldJob:
    """Simple greeting job with one stage."""

    def create_stage_tasks(self, stage: int, context: JobContext) -> List[TaskDefinition]:
        if stage == 1:
            return [
                TaskDefinition(
                    task_type="greet",
                    parameters={"message": context.job_params["message"]}
                )
            ]
        return []

    def aggregate_stage_results(self, stage: int, results: List[Dict]) -> Dict:
        if stage == 1:
            return {"greeting": results[0]["output"]}
        return {}

    def should_advance_stage(self, stage: int, context: JobContext) -> bool:
        return False  # Only 1 stage

    def get_final_result(self, context: JobContext) -> Dict:
        return context.stage_results[1]  # Return stage 1 results
```

### Example 2: Complex Multi-Stage Job with Fan-Out

```python
@JobRegistry.instance().register(job_type="list_container")
class ListContainerJob:
    """
    Multi-stage container analysis job.

    Stage 1: List all blobs in container (single task)
    Stage 2: Analyze each blob in parallel (fan-out)
    """

    def create_stage_tasks(self, stage: int, context: JobContext) -> List[TaskDefinition]:
        if stage == 1:
            # Single task to list container
            return [
                TaskDefinition(
                    task_type="list_blobs",
                    parameters={"container": context.job_params["container_name"]}
                )
            ]

        elif stage == 2:
            # Fan-out: One task per blob
            blob_list = context.stage_results[1]["blobs"]
            return [
                TaskDefinition(
                    task_type="analyze_blob",
                    parameters={
                        "container": context.job_params["container_name"],
                        "blob_name": blob["name"]
                    }
                )
                for blob in blob_list
            ]

        return []

    def aggregate_stage_results(self, stage: int, results: List[Dict]) -> Dict:
        if stage == 1:
            # Single result from list operation
            return results[0]

        elif stage == 2:
            # Aggregate all blob analyses
            return {
                "total_blobs": len(results),
                "total_size": sum(r["size"] for r in results),
                "analyses": results
            }

        return {}

    def should_advance_stage(self, stage: int, context: JobContext) -> bool:
        return stage < 2  # Two stages total

    def get_final_result(self, context: JobContext) -> Dict:
        return {
            "container": context.job_params["container_name"],
            "blob_count": context.stage_results[1]["blob_count"],
            "analysis": context.stage_results[2]
        }
```

---

## 🎨 Design Patterns Used

### 1. **Registry Pattern**
- Central lookup table mapping job_type → JobClass
- Enables dynamic dispatch without if/elif chains

### 2. **Decorator Pattern**
- `@JobRegistry.instance().register(job_type="...")`
- Clean, declarative registration at class definition time

### 3. **Singleton Pattern**
- JobRegistry is a singleton
- One source of truth for job mappings

### 4. **Strategy Pattern**
- Each job class is a different strategy for job execution
- CoreMachine delegates to the strategy

### 5. **Template Method Pattern**
- CoreMachine defines the workflow skeleton
- Job handlers fill in the specific steps

### 6. **Composition Pattern**
- CoreMachine composes with job handlers
- Avoids inheritance-based coupling

---

## ✅ Benefits

### Extensibility
- **Add new job types without touching CoreMachine**
- Just create new job class with `@register` decorator
- No central switch/case statements to update

### Testability
- **Test job handlers in isolation**
- Mock CoreMachine interactions
- Unit test each job's business logic separately

### Maintainability
- **Clear separation of concerns**
- CoreMachine: Generic orchestration
- Job handlers: Job-specific business logic
- Registry: Dynamic lookup

### Type Safety
- **Protocol/ABC defines required methods**
- Static analysis can verify compliance
- Runtime errors for missing methods

### Discoverability
- **Registry provides introspection**
- List all registered job types
- Validate job type before execution

---

## 🚨 Critical Rules for Refactoring

When refactoring the codebase, **preserve these patterns**:

### ✅ DO:
- Keep CoreMachine job-agnostic
- Use decorator registration for new jobs
- Implement all protocol methods in job handlers
- Keep job-specific logic in job classes
- Use registry for dynamic lookup

### ❌ DON'T:
- Add job-specific logic to CoreMachine
- Use if/elif chains for job type dispatch
- Couple CoreMachine to specific job classes
- Skip protocol methods in job handlers
- Bypass registry with direct imports

---

## 📖 Related Patterns

- **Service Registry** (similar but for services)
- **Plugin Architecture** (jobs are like plugins)
- **Inversion of Control** (registry controls instantiation)
- **Dependency Injection** (CoreMachine receives job handlers)

---

## 🔍 Code Locations

**Registry Implementation:**
- `core/registry.py` - JobRegistry singleton class

**Job Implementations:**
- `jobs/hello_world.py` - Simple single-stage job example
- `jobs/list_container.py` - Complex multi-stage fan-out example
- `jobs/stage_raster.py` - Real-world geospatial workflow

**CoreMachine Integration:**
- `core/machine.py` - Generic orchestrator using registry

**Triggers:**
- `triggers/submit_job.py` - HTTP endpoint using registry lookup

---

## 💡 Key Insight

> **The registry pattern enables a generic orchestration engine to execute arbitrarily complex, job-specific workflows without knowing anything about those workflows ahead of time.**

This is the foundation that allows the system to scale from simple "hello world" jobs to complex multi-stage geospatial processing pipelines without architectural changes.
