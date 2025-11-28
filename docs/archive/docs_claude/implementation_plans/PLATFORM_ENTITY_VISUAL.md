# Platform Entity Visual Comparison

**Date**: 25 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Visual representation of how Platform entities mirror CoreMachine patterns

## Side-by-Side Entity Comparison

```
┌─────────────────────────────────────┬─────────────────────────────────────┐
│      COREMACHINE (EXISTING)         │    PLATFORM SERVICE (NEW)           │
├─────────────────────────────────────┼─────────────────────────────────────┤
│                                     │                                     │
│  ┌─────────────┐                   │  ┌──────────────────┐              │
│  │  JobRecord  │                   │  │ PlatformRecord   │              │
│  └──────┬──────┘                   │  └────────┬─────────┘              │
│         │                           │           │                         │
│         │ 1:N                       │           │ 1:N                     │
│         ▼                           │           ▼                         │
│  ┌─────────────┐                   │  ┌──────────────────┐              │
│  │ TaskRecord  │                   │  │   JobRecord      │              │
│  └─────────────┘                   │  │  (CoreMachine)   │              │
│                                     │  └────────┬─────────┘              │
│                                     │           │                         │
│                                     │           │ 1:N                     │
│                                     │           ▼                         │
│                                     │  ┌──────────────────┐              │
│                                     │  │   TaskRecord     │              │
│                                     │  │  (CoreMachine)   │              │
│                                     │  └──────────────────┘              │
│                                     │                                     │
└─────────────────────────────────────┴─────────────────────────────────────┘
```

## Execution Flow Comparison

### CoreMachine Flow (Current)
```
User Request
    │
    ▼
┌─────────────────┐
│   HTTP Trigger  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Jobs Queue     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  CoreMachine    │──┐
│ process_job()   │  │
└────────┬────────┘  │
         │           │
         ▼           │ Monitors
┌─────────────────┐  │
│  Tasks Queue    │  │
└────────┬────────┘  │
         │           │
         ▼           │
┌─────────────────┐  │
│  CoreMachine    │◀─┘
│ process_task()  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Task Handler   │
│   (Service)     │
└─────────────────┘
```

### Platform + CoreMachine Flow (New)
```
External Request (DDH)
    │
    ▼
┌─────────────────┐
│   HTTP Trigger  │
│  (Platform API) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Platform Queue  │ ← NEW LAYER
└────────┬────────┘
         │
         ▼
┌─────────────────────┐
│ PlatformOrchestrator│ ← NEW LAYER
│ process_request()   │
└──────────┬──────────┘
           │
           │ Creates multiple jobs
           ▼
    ┌──────┴──────┬──────────┬───────────┐
    ▼             ▼          ▼           ▼
┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐
│ Job 1  │  │ Job 2  │  │ Job 3  │  │ Job N  │
└───┬────┘  └───┬────┘  └───┬────┘  └───┬────┘
    │           │           │           │
    ▼           ▼           ▼           ▼
         [CoreMachine handles each job]
```

## Status State Machines

### Both Use Identical State Transitions

```
           ┌─────────┐
           │ PENDING │
           └────┬────┘
                │ Picked up for processing
                ▼
         ┌────────────┐
         │ PROCESSING │
         └─────┬──────┘
               │
         ┌─────┴──────┐
         ▼            ▼
    ┌─────────┐  ┌────────┐
    │COMPLETED│  │ FAILED │
    └─────────┘  └────────┘
```

## Completion Detection Pattern

### "Last Task Turns Out the Lights" at Each Level

```
CoreMachine Level:
─────────────────
Job
├── Task 1 ✓
├── Task 2 ✓
└── Task 3 ✓ ← Last task completes
            └─→ Job marked COMPLETED

Platform Level:
──────────────
PlatformRequest
├── Job 1 ✓
├── Job 2 ✓
└── Job 3 ✓ ← Last job completes
            └─→ Request marked COMPLETED
```

## Database Relationship Diagram

```sql
┌─────────────────────────┐
│  platform.requests      │
├─────────────────────────┤
│ request_id (PK)         │◀──┐
│ dataset_id              │   │
│ resource_id             │   │
│ version_id              │   │
│ status                  │   │
│ parameters (JSONB)      │   │
│ result_data (JSONB)     │   │
└─────────────────────────┘   │
                               │ 1:N
┌─────────────────────────┐   │
│  platform.request_jobs  │   │
├─────────────────────────┤   │
│ request_id (FK) ────────────┘
│ job_id (FK) ────────────────┐
│ job_type                │   │
│ sequence                │   │
│ status                  │   │
└─────────────────────────┘   │
                               │ 1:1
┌─────────────────────────┐   │
│  app.jobs               │   │
├─────────────────────────┤   │
│ job_id (PK)             │◀──┘
│ job_type                │
│ status                  │◀──┐
│ stage                   │   │
│ parameters (JSONB)      │   │ Mirrors status
│ result_data (JSONB)     │   │
└─────────────────────────┘   │
                               │
┌─────────────────────────┐   │
│  app.tasks              │   │
├─────────────────────────┤   │
│ task_id (PK)            │   │
│ job_id (FK)             │   │
│ task_type               │   │
│ status ─────────────────────┘
│ parameters (JSONB)      │
│ result_data (JSONB)     │
└─────────────────────────┘
```

## Message Queue Architecture

```
                 Platform Service Layer (NEW)
┌──────────────────────────────────────────────────────┐
│                                                      │
│  ┌──────────────┐        ┌──────────────────┐      │
│  │Platform Queue│───────▶│Platform Orchestr.│      │
│  └──────────────┘        └─────────┬────────┘      │
│                                     │               │
└─────────────────────────────────────┼───────────────┘
                                      │ Creates Jobs
                                      ▼
                 CoreMachine Layer (EXISTING)
┌──────────────────────────────────────────────────────┐
│                                                      │
│  ┌──────────────┐        ┌──────────────────┐      │
│  │ Jobs Queue   │───────▶│   CoreMachine    │      │
│  └──────────────┘        └─────────┬────────┘      │
│                                     │               │
│                                     ▼               │
│  ┌──────────────┐        ┌──────────────────┐      │
│  │ Tasks Queue  │◀───────│  Task Creation   │      │
│  └──────┬───────┘        └──────────────────┘      │
│         │                                           │
│         ▼                                           │
│  ┌──────────────────┐                              │
│  │  Task Handlers   │                              │
│  └──────────────────┘                              │
│                                                      │
└──────────────────────────────────────────────────────┘
```

## Pattern Inheritance

```
BaseOrchestrator (Abstract)
├── CoreMachine (Existing)
│   ├── process_job_message()
│   ├── process_task_message()
│   └── check_completion()
│
└── PlatformOrchestrator (New)
    ├── process_request_message()
    ├── monitor_job_completion()
    └── check_completion()

BaseRepository (Abstract)
├── JobRepository (Existing)
│   ├── create_job()
│   ├── get_job()
│   └── update_status()
│
├── TaskRepository (Existing)
│   ├── create_task()
│   ├── get_task()
│   └── update_status()
│
└── PlatformRepository (New)
    ├── create_request()
    ├── get_request()
    └── update_status()
```

## Key Design Principles

Both layers follow identical principles:

1. **Idempotency**: SHA256 IDs ensure same inputs = same ID
2. **Atomic Operations**: Database transactions prevent race conditions
3. **Status Propagation**: Failures bubble up the hierarchy
4. **Completion Detection**: "Last unit turns out the lights"
5. **Queue-Driven**: Asynchronous processing via Service Bus
6. **Repository Pattern**: Clean separation of data access
7. **Strong Typing**: Pydantic models for validation

## Example: Dataset Processing Request

```python
# 1. Platform receives request from DDH
request = PlatformRequest(
    dataset_id="landsat-8",
    resource_id="LC08_L1TP_044034_20210622",
    version_id="v1.0"
)

# 2. Platform creates multiple CoreMachine jobs
jobs = [
    Job(job_type="validate_raster", ...),      # Stage 1
    Job(job_type="create_cog", ...),          # Stage 2
    Job(job_type="create_stac_item", ...),    # Stage 3
    Job(job_type="update_mosaic", ...)        # Stage 4
]

# 3. Each job creates its own tasks (handled by CoreMachine)
Job["validate_raster"] → [
    Task("check_projection"),
    Task("validate_bands"),
    Task("check_nodata")
]

# 4. Completion flows up
All tasks complete → Job completes → All jobs complete → Request completes

# 5. Platform notifies DDH with results
{
    "request_id": "abc123",
    "status": "completed",
    "endpoints": {
        "tiles": "https://.../tiles/{z}/{x}/{y}",
        "stac": "https://.../stac/items/LC08_...",
        "cog": "https://.../data/LC08_..._cog.tif"
    }
}
```