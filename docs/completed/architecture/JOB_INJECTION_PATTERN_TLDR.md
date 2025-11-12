# Job-Specific Method Injection Pattern - TL;DR

**Date**: 4 OCT 2025
**Audience**: Claude (browser) for refactoring work
**Author**: Robert and Geospatial Claude Legion

## 🎯 Core Concept

We have a **generic orchestration engine** (CoreMachine) that executes **job-specific business logic** without knowing the details. Job types inject their custom behavior into the core engine through **handler classes**.

---

## 📐 Architecture Pattern

```
HTTP Request → CoreMachine (Generic) → Job Handler (Specific) → Service → Repository
                    ↓                         ↓
              Orchestrates              Implements
              workflow                  business logic
```

**CoreMachine** = Framework (orchestrates workflow, manages state)
**Job Handlers** = Plugins (job-specific logic)

---

## 🔧 How Jobs Are Injected

### 1. Job Registration (Decorator Pattern)

**Location**: `jobs/` folder

**Pattern**:
```python
# jobs/hello_world.py

from jobs.registry import JobRegistry

@JobRegistry.instance().register(
    job_type="hello_world",
    description="Simple hello world job"
)
class HelloWorldJob:
    """Job-specific handler - injected into CoreMachine"""

    def create_stage_1_tasks(self, context: JobContext) -> List[TaskDefinition]:
        """Job defines WHAT tasks to create"""
        return [
            TaskDefinition(
                task_type="greet",
                parameters={"message": "Hello"}
            )
        ]

    def aggregate_stage_results(self, results: List[TaskResult]) -> Dict:
        """Job defines HOW to combine results"""
        return {"greeting": results[0].result_data["output"]}
```

**Key Points**:
- ✅ `@JobRegistry.instance().register()` - Auto-discovery decorator
- ✅ Each job is a **class** with specific methods
- ✅ Jobs **don't inherit from base class** (composition over inheritance)
- ✅ CoreMachine **calls these methods** during workflow execution

---

### 2. Job Registry (Singleton Registry Pattern)

**Location**: `jobs/registry.py`

**What it does**:
```python
class JobRegistry:
    _instance = None
    _jobs: Dict[str, Type] = {}  # {"hello_world": HelloWorldJob}

    @classmethod
    def instance(cls):
        """Singleton - one registry for entire app"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, job_type: str, description: str = ""):
        """Decorator - registers job class"""
        def wrapper(job_class: Type):
            self._jobs[job_type] = job_class
            return job_class
        return wrapper

    def get_job_class(self, job_type: str) -> Type:
        """CoreMachine calls this to get job handler"""
        if job_type not in self._jobs:
            raise ValueError(f"Unknown job type: {job_type}")
        return self._jobs[job_type]
```

**Key Points**:
- ✅ Singleton pattern - one registry instance
- ✅ Dictionary maps `job_type` → `JobClass`
- ✅ CoreMachine looks up job by string name
- ✅ Auto-discovery via decorators

---

### 3. CoreMachine Integration (Composition Pattern)

**Location**: `core/machine.py`

**How CoreMachine uses job handlers**:
```python
class CoreMachine:
    """Generic workflow orchestrator"""

    def execute_job(self, job_id: str, job_type: str, parameters: Dict):
        """Main orchestration method"""

        # 1. Get job-specific handler from registry
        job_class = JobRegistry.instance().get_job_class(job_type)
        job_handler = job_class()  # Instantiate

        # 2. Execute workflow using injected methods
        stage = 1
        while not self.job_complete(job_id):
            # Call job-specific method to create tasks
            tasks = job_handler.create_stage_1_tasks(context)

            # CoreMachine handles task execution (generic)
            results = self._execute_tasks(tasks)

            # Call job-specific method to aggregate
            stage_result = job_handler.aggregate_stage_results(results)

            # CoreMachine handles stage advancement (generic)
            stage = self._advance_stage(job_id, stage_result)
```

**Key Points**:
- ✅ CoreMachine **doesn't know** about HelloWorldJob
- ✅ It **dynamically loads** the handler at runtime
- ✅ Calls **job-specific methods** via composition
- ✅ Generic orchestration + specific business logic

---

## 📁 File Structure

```
jobs/
├── registry.py          # Singleton registry
├── hello_world.py       # Job handler (registered via decorator)
├── list_container.py    # Job handler
└── summarize.py         # Job handler

core/
├── machine.py           # Generic orchestrator (uses registry)
└── models/
    ├── job.py           # JobContext, JobDefinition
    └── task.py          # TaskDefinition, TaskResult

services/
├── hello_world.py       # Business logic (called by job handler)
└── container.py         # Business logic
```

---

## 🔄 Complete Flow Example

### 1. Job Submission
```python
# User submits job
POST /api/jobs/submit/hello_world
Body: {"message": "Hello World"}
```

### 2. CoreMachine Starts
```python
# core/machine.py
job_type = "hello_world"
job_class = JobRegistry.instance().get_job_class(job_type)  # → HelloWorldJob
job_handler = job_class()  # Instantiate
```

### 3. Stage 1 Execution
```python
# CoreMachine asks job: "What tasks for stage 1?"
tasks = job_handler.create_stage_1_tasks(context)
# Returns: [TaskDefinition(task_type="greet", ...)]

# CoreMachine executes tasks (generic)
for task in tasks:
    result = execute_task(task)  # Calls service layer

# CoreMachine asks job: "How to aggregate results?"
stage_result = job_handler.aggregate_stage_results(results)
# Returns: {"greeting": "Hello World"}
```

### 4. Job Completion
```python
# CoreMachine asks job: "Should we advance to next stage?"
should_advance = job_handler.should_advance_stage(stage_result)
# Returns: False (hello_world has only 1 stage)

# CoreMachine marks job complete
```

---

## 🎨 Design Patterns Used

| Pattern | Where | Why |
|---------|-------|-----|
| **Registry Pattern** | `JobRegistry` | Dynamic job discovery without imports |
| **Composition** | CoreMachine + Job Handlers | Inject behavior without inheritance |
| **Decorator** | `@JobRegistry.instance().register()` | Auto-registration at import time |
| **Singleton** | `JobRegistry.instance()` | Single source of truth for jobs |
| **Strategy** | Job handler methods | Swap algorithms at runtime |
| **Template Method** | CoreMachine workflow | Define skeleton, let jobs fill in steps |

---

## 🔑 Key Contracts (Required Methods)

Every job handler **must implement** these methods:

```python
class AnyJobHandler:
    def create_stage_1_tasks(self, context: JobContext) -> List[TaskDefinition]:
        """Define what tasks to run in stage 1"""
        pass

    def create_stage_N_tasks(self, context: JobContext, stage: int) -> List[TaskDefinition]:
        """Define tasks for subsequent stages (optional)"""
        pass

    def aggregate_stage_results(self, results: List[TaskResult]) -> Dict:
        """Combine task results into stage result"""
        pass

    def should_advance_stage(self, stage_result: Dict) -> bool:
        """Decide if workflow should continue"""
        pass

    def get_final_result(self, all_stage_results: Dict) -> Dict:
        """Generate final job output"""
        pass
```

**CoreMachine calls these methods in order during workflow execution.**

---

## 🚀 Adding a New Job Type

**Step 1**: Create job handler
```python
# jobs/my_new_job.py

from jobs.registry import JobRegistry

@JobRegistry.instance().register(
    job_type="my_new_job",
    description="Does something amazing"
)
class MyNewJob:
    def create_stage_1_tasks(self, context):
        # Your logic here
        return [TaskDefinition(...)]

    def aggregate_stage_results(self, results):
        # Your logic here
        return {"status": "success"}

    # ... implement other required methods
```

**Step 2**: Import in `jobs/__init__.py`
```python
# jobs/__init__.py
from .hello_world import HelloWorldJob
from .my_new_job import MyNewJob  # ← Add this

# Decorator auto-registers on import!
```

**Step 3**: That's it!
```bash
# Now you can submit jobs
POST /api/jobs/submit/my_new_job
```

CoreMachine will automatically:
1. Look up "my_new_job" in registry
2. Get MyNewJob class
3. Instantiate it
4. Call its methods during workflow

---

## 🎯 Why This Pattern?

### ✅ Advantages

1. **Separation of Concerns**
   - CoreMachine = orchestration (generic)
   - Job handlers = business logic (specific)

2. **No Tight Coupling**
   - CoreMachine doesn't import job classes
   - Jobs register themselves via decorator
   - Runtime dependency injection

3. **Easy to Extend**
   - Add new job = create one file
   - No changes to CoreMachine
   - Auto-discovered via decorator

4. **Type Safety**
   - Job handlers are classes (can use type hints)
   - Registry enforces contracts
   - IDE autocomplete works

5. **Testable**
   - Mock job handlers easily
   - Test CoreMachine with fake jobs
   - Test jobs without CoreMachine

### ❌ Alternatives We Avoided

**❌ Inheritance (BaseJob)**
```python
# BAD: Forces inheritance hierarchy
class HelloWorldJob(BaseJob):
    def execute(self):
        pass
```
- Tight coupling
- Hard to test
- Inflexible

**❌ If/Else Chain**
```python
# BAD: CoreMachine has to know all jobs
if job_type == "hello_world":
    do_hello_world()
elif job_type == "list_container":
    do_list_container()
```
- Violates Open/Closed Principle
- CoreMachine grows forever
- Hard to maintain

**✅ Our Pattern (Composition + Registry)**
```python
# GOOD: Dynamic lookup, composition
job_class = JobRegistry.instance().get_job_class(job_type)
job_handler = job_class()
tasks = job_handler.create_stage_1_tasks(context)
```
- Loose coupling
- Easy to extend
- Clean separation

---

## 🔍 Real Example: Container Jobs

```python
# jobs/list_container.py

@JobRegistry.instance().register(
    job_type="list_container_contents",
    description="List all blobs in container"
)
class ListContainerJob:
    """
    Stage 1: List all blobs (1 task)
    Stage 2: Analyze each blob (N tasks, parallel)
    """

    def create_stage_1_tasks(self, context: JobContext) -> List[TaskDefinition]:
        """Single task to list container"""
        return [
            TaskDefinition(
                task_type="list_blobs",
                parameters={
                    "container": context.parameters["container_name"],
                    "prefix": context.parameters.get("prefix", "")
                }
            )
        ]

    def aggregate_stage_results(self, results: List[TaskResult]) -> Dict:
        """Extract blob list from Stage 1 result"""
        if context.current_stage == 1:
            # Stage 1: Single result with blob list
            blob_list = results[0].result_data["blobs"]
            return {"blobs": blob_list, "count": len(blob_list)}

        elif context.current_stage == 2:
            # Stage 2: Multiple results from parallel analysis
            analyzed = [r.result_data for r in results]
            return {"analyzed_blobs": analyzed}

    def should_advance_stage(self, stage_result: Dict) -> bool:
        """Advance from Stage 1 → Stage 2"""
        if context.current_stage == 1:
            return stage_result["count"] > 0  # Only if blobs found
        return False  # Stage 2 is final

    def create_stage_2_tasks(self, context: JobContext) -> List[TaskDefinition]:
        """Fan-out: One task per blob"""
        blob_list = context.previous_stage_result["blobs"]

        tasks = []
        for i, blob in enumerate(blob_list):
            tasks.append(
                TaskDefinition(
                    task_type="analyze_blob",
                    task_index=i,
                    parameters={"blob_name": blob["name"]}
                )
            )
        return tasks  # Parallel execution!
```

**CoreMachine handles**:
- ✅ Task queueing
- ✅ Parallel execution
- ✅ Stage transitions
- ✅ Error handling
- ✅ Status tracking

**Job handler defines**:
- ✅ What tasks to create
- ✅ How to combine results
- ✅ When to advance stages
- ✅ Business logic

---

## 📊 Comparison: Before vs After

### Before (Monolithic)
```python
def execute_job(job_id, job_type, parameters):
    if job_type == "hello_world":
        # 200 lines of hello_world logic
    elif job_type == "list_container":
        # 300 lines of container logic
    elif job_type == "process_raster":
        # 500 lines of raster logic
    # ... 20 more job types
```
- 5000+ line function
- Impossible to test
- Violates SRP

### After (Job Injection)
```python
# CoreMachine (generic, ~200 lines)
def execute_job(job_id, job_type, parameters):
    job_class = JobRegistry.instance().get_job_class(job_type)
    job_handler = job_class()

    while not complete:
        tasks = job_handler.create_stage_tasks(context)
        results = self._execute_tasks(tasks)
        stage_result = job_handler.aggregate_stage_results(results)
        self._advance_stage(stage_result)

# Each job handler (50-200 lines)
# jobs/hello_world.py - 50 lines
# jobs/list_container.py - 150 lines
# jobs/process_raster.py - 200 lines
```
- Clean separation
- Easy to test
- Easy to extend

---

## 🎓 Summary for Refactoring

**When refactoring, preserve these principles**:

1. **CoreMachine = Generic Orchestrator**
   - No job-specific logic
   - Calls methods on job handlers
   - Manages workflow state

2. **Job Handlers = Specific Business Logic**
   - Registered via `@JobRegistry.instance().register()`
   - Implement required methods (create_tasks, aggregate_results, etc.)
   - Live in `jobs/` folder

3. **Registry = Dynamic Lookup**
   - `JobRegistry.instance().get_job_class(job_type)`
   - Singleton pattern
   - No imports of job classes in CoreMachine

4. **Composition > Inheritance**
   - Jobs don't inherit from base class
   - CoreMachine composes with job handlers
   - Loose coupling via registry

**If you break these patterns, you'll lose**:
- ❌ Extensibility (adding new jobs)
- ❌ Testability (mocking jobs)
- ❌ Separation of concerns

**Questions for refactoring**:
- Does CoreMachine remain job-agnostic? ✅
- Can I add a new job without modifying CoreMachine? ✅
- Are job handlers self-contained? ✅
- Does the registry enable dynamic lookup? ✅

---

## 📝 Quick Reference

```python
# Register a job
@JobRegistry.instance().register(job_type="my_job")
class MyJob:
    pass

# Get a job class
job_class = JobRegistry.instance().get_job_class("my_job")

# Instantiate and use
job_handler = job_class()
tasks = job_handler.create_stage_1_tasks(context)
```

**That's it!** Job injection via registry + composition. Simple, extensible, testable. 🚀
