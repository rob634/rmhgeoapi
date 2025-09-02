# Instructions for Human - HTTP Trigger Flow Trace

## Complete Flow: HTTP Request → Job Queue → Task Queue → Task Processing

### Step 1: HTTP Trigger - Job Submission
**File**: `function_app.py`  
**Lines**: 77-85  
**Entry Point**: `submit_job()` function  
**Trigger**: HTTP POST to `/api/jobs/{job_type}`

```python
@app.route(route="jobs/{job_type}", methods=["POST"])
def submit_job(req: func.HttpRequest) -> func.HttpResponse:
```

**What happens**: 
- Receives job parameters in HTTP request body
- Routes to appropriate controller (e.g., HelloWorldController)
- Controller creates job record in PostgreSQL database
- Controller queues job message to `geospatial-jobs` queue

### Step 2: Controller - Job Creation and Queuing
**File**: `controller_base.py`  
**Lines**: 323-350 (submit method)  
**Key Operations**:
- **Line 338**: `queue_client.send_message(message_json)` - Sends to `geospatial-jobs` queue
- **Line 339**: Job status set to `JobStatus.QUEUED`

**Queue Message Format**:
```json
{
  "job_id": "abc123...",
  "job_type": "hello_world",
  "parameters": {...}
}
```

### Step 3: Job Queue Trigger - Stage Processing
**File**: `function_app.py`  
**Lines**: 88-110  
**Entry Point**: `process_job_queue()` function  
**Trigger**: Azure Queue trigger on `geospatial-jobs` queue

```python
@app.queue_trigger(arg_name="msg", queue_name="geospatial-jobs", connection="AzureWebJobsStorage")
def process_job_queue(msg: func.QueueMessage) -> None:
```

**What happens**:
- **Line 99**: Decodes queue message from JSON
- **Line 105**: Routes to controller (e.g., `HelloWorldController`)
- **Line 106**: Calls `controller.process_job_stage(job_id, stage=1)`

### Step 4: Stage Processing - Task Creation
**File**: `controller_base.py`  
**Lines**: 722-774 (process_job_stage method)  
**Key Operations**:

**Step 4a - Database Setup (Lines 730-740)**:
- **Line 734**: Load job record from PostgreSQL
- **Line 738**: Update job status to `JobStatus.PROCESSING`

**Step 4b - Task Definition Creation (Lines 742-748)**:
- **Line 743**: Call `self.create_stage_tasks(job_record, stage)`
- This creates `TaskDefinition` objects for the stage

**Step 4c - Task Record Creation Loop (Lines 749-774)**:
For each TaskDefinition:
- **Line 754**: `task_record = task_repo.create_task(...)` - Creates task in PostgreSQL
- **Line 760**: Create task queue message JSON
- **Line 767**: `queue_client.send_message(message_json)` - Send to `geospatial-tasks` queue

### Step 5: Task Queue Trigger - Task Execution
**File**: `function_app.py`  
**Lines**: 113-139  
**Entry Point**: `process_task_queue()` function  
**Trigger**: Azure Queue trigger on `geospatial-tasks` queue

```python
@app.queue_trigger(arg_name="msg", queue_name="geospatial-tasks", connection="AzureWebJobsStorage")
def process_task_queue(msg: func.QueueMessage) -> None:
```

**What happens**:
- **Line 124**: Decodes task message from JSON
- **Line 130**: Routes to appropriate service (e.g., `HelloWorldService`)
- **Line 131**: Calls `service.execute_task(task_record)`

### Step 6: Task Execution - Business Logic
**File**: `service_hello_world.py`  
**Lines**: 45-80 (execute_task method)  
**Key Operations**:
- **Line 56**: Update task status to `TaskStatus.PROCESSING`
- **Lines 60-70**: Execute business logic based on task_type
- **Line 76**: Update task status to `TaskStatus.COMPLETED`
- **Line 78**: Call completion detection logic

### Step 7: Completion Detection - "Last Task Turns Out Lights"
**File**: `repository_data.py`  
**Lines**: 1143-1200 (check_stage_completion method)  
**Key Operations**:
- **Line 1150**: Query PostgreSQL to count completed vs total tasks in stage
- **Line 1167**: If all tasks complete, call `complete_task_and_check_stage()` PostgreSQL function
- **Line 1185**: If stage complete, advance to next stage or mark job complete

## Queue Message Formats

### Job Queue Message (`geospatial-jobs`)
```json
{
  "job_id": "39864a5f15c04a026e078cb67e1af97b177764ec913babe560554951278b436c",
  "job_type": "hello_world",
  "parameters": {
    "greeting": "Hello",
    "target": "World"
  }
}
```

### Task Queue Message (`geospatial-tasks`)  
```json
{
  "task_id": "task_39864a5f_stage1_task0",
  "job_id": "39864a5f15c04a026e078cb67e1af97b177764ec913babe560554951278b436c",
  "task_type": "greeting",
  "stage": 1,
  "parameters": {
    "greeting": "Hello",
    "target": "World"
  }
}
```

## Controller Implementations

### HelloWorld Controller
**File**: `controller_hello_world.py`  
**Stage Definitions**:
- **Stage 1**: Creates `n` "greeting" tasks (Line 89)
- **Stage 2**: Creates `n` "reply" tasks (Line 91)

**Task Creation Logic (Lines 80-95)**:
```python
def create_stage_tasks(self, job: JobRecord, stage: int) -> List[TaskDefinition]:
    if stage == 1:
        # Create greeting tasks
    elif stage == 2:
        # Create reply tasks
```

## Database Tables

### Jobs Table (PostgreSQL)
- **job_id** (Primary Key)
- **status** (queued → processing → completed)
- **stage** (1, 2, 3...)
- **parameters** (JSONB)
- **result_data** (JSONB)

### Tasks Table (PostgreSQL)
- **task_id** (Primary Key)
- **job_id** (Foreign Key)
- **status** (queued → processing → completed)
- **stage** (1, 2, 3...)
- **task_type** (greeting, reply, etc.)
- **parameters** (JSONB)
- **result_data** (JSONB)

## Critical PostgreSQL Functions (Missing - Root Cause)
- `complete_task_and_check_stage()` - Atomic stage completion detection
- `advance_job_stage()` - Safe stage transition with race condition prevention

## Flow Summary
1. **HTTP POST** → `function_app.py:submit_job()` → Controller creates job → Queues to `geospatial-jobs`
2. **Job Queue Trigger** → `function_app.py:process_job_queue()` → `controller_base.py:process_job_stage()` → Creates tasks → Queues to `geospatial-tasks`  
3. **Task Queue Trigger** → `function_app.py:process_task_queue()` → Service executes task → Updates database
4. **Completion Detection** → Repository checks if stage complete → Advances to next stage or completes job

## Current Issue
**Root Cause**: Missing PostgreSQL functions prevent "last task turns out lights" stage progression. Jobs get stuck in stage 1 because atomic stage completion cannot execute.