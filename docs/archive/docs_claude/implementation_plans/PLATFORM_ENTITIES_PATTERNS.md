# Platform Entities Following CoreMachine Patterns

**Date**: 25 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Document how Platform Service entities follow Job/Task patterns from CoreMachine

## Entity Hierarchy Comparison

### CoreMachine Pattern (Existing)
```
Job (Orchestration Unit)
├── Stage 1 (Sequential)
│   ├── Task A (Parallel Execution)
│   ├── Task B (Parallel Execution)
│   └── Task C (Parallel Execution)
├── Stage 2 (Sequential)
│   └── Task D (Single Task)
└── Completion (Aggregation)
```

### Platform Service Pattern (New)
```
PlatformRequest (Application-Level Orchestration)
├── Job 1: validate_dataset (CoreMachine Job)
│   └── [CoreMachine handles stages/tasks]
├── Job 2: process_raster (CoreMachine Job)
│   └── [CoreMachine handles stages/tasks]
├── Job 3: create_stac_item (CoreMachine Job)
│   └── [CoreMachine handles stages/tasks]
└── Completion (Platform-level aggregation)
```

## Entity Pattern Mapping

### 1. Record Entities (Database Models)

```python
# ============================================================================
# EXISTING: CoreMachine Entities
# ============================================================================

class JobRecord:
    """CoreMachine Job - Orchestrates stages and tasks"""
    job_id: str          # SHA256(job_type + params)
    job_type: str        # "process_raster", "create_cog", etc.
    status: str          # PENDING → PROCESSING → COMPLETED/FAILED
    stage: int           # Current stage number
    parameters: dict     # Job input parameters
    metadata: dict       # Runtime metadata
    result_data: dict    # Aggregated results
    created_at: datetime
    updated_at: datetime

class TaskRecord:
    """CoreMachine Task - Individual unit of work"""
    task_id: str         # Semantic ID like "tile_x5_y10"
    job_id: str          # Parent job reference
    task_type: str       # "validate_raster", "create_cog", etc.
    status: str          # PENDING → PROCESSING → COMPLETED/FAILED
    stage: int           # Stage number
    parameters: dict     # Task input parameters
    result_data: dict    # Task results
    retry_count: int     # Retry tracking
    created_at: datetime
    updated_at: datetime

# ============================================================================
# NEW: Platform Service Entities (Following Same Pattern)
# ============================================================================

class PlatformRecord:
    """Platform Request - Application-level orchestration"""
    request_id: str      # SHA256(dataset_id + resource_id + version_id + timestamp)
    dataset_id: str      # DDH dataset identifier
    resource_id: str     # DDH resource identifier
    version_id: str      # DDH version identifier
    status: str          # PENDING → PROCESSING → COMPLETED/FAILED
    job_ids: List[str]   # List of CoreMachine job IDs (like Job has task_ids)
    parameters: dict     # Request parameters from DDH
    metadata: dict       # Platform metadata (client_id, request_type, etc.)
    result_data: dict    # Aggregated results (API endpoints created, etc.)
    created_at: datetime
    updated_at: datetime

class PlatformJobMapping:
    """Maps Platform Requests to CoreMachine Jobs (like Stage maps Jobs to Tasks)"""
    request_id: str      # Parent platform request
    job_id: str          # CoreMachine job ID
    job_type: str        # Type of job created
    sequence: int        # Order of execution (like stage number)
    status: str          # Job status (mirrors from CoreMachine)
    created_at: datetime
```

### 2. Status Tracking Pattern

Both follow the same state machine:

```python
# CoreMachine Pattern (Existing)
class JobStatus(Enum):
    PENDING = "pending"        # Created, waiting in queue
    PROCESSING = "processing"  # Picked up, being processed
    COMPLETED = "completed"    # Successfully finished
    FAILED = "failed"         # Error occurred

# Platform Pattern (New - Identical)
class PlatformRequestStatus(Enum):
    PENDING = "pending"        # Request received, jobs not created
    PROCESSING = "processing"  # Jobs created and running
    COMPLETED = "completed"    # All jobs completed successfully
    FAILED = "failed"         # One or more jobs failed
```

### 3. Completion Detection Pattern

**"Last Task Turns Out the Lights" - Applied at Both Levels**

```python
# ============================================================================
# CoreMachine Pattern (Existing)
# ============================================================================
class JobRepository:
    def check_job_completion(self, job_id: str) -> bool:
        """Last task in job triggers completion"""
        with self.get_connection() as conn:
            # Atomic check: Are all tasks for this job complete?
            incomplete = conn.execute("""
                SELECT COUNT(*) FROM tasks
                WHERE job_id = %s AND status IN ('pending', 'processing')
            """, (job_id,))

            if incomplete == 0:
                # Last task turns out the lights
                conn.execute("""
                    UPDATE jobs SET status = 'completed'
                    WHERE job_id = %s
                """, (job_id,))
                return True
            return False

# ============================================================================
# Platform Pattern (New - Same Logic, Higher Level)
# ============================================================================
class PlatformRepository:
    def check_request_completion(self, request_id: str) -> bool:
        """Last job in request triggers completion"""
        with self.get_connection() as conn:
            # Atomic check: Are all jobs for this request complete?
            incomplete = conn.execute("""
                SELECT COUNT(*) FROM platform_jobs
                WHERE request_id = %s AND status IN ('pending', 'processing')
            """, (request_id,))

            if incomplete == 0:
                # Last job turns out the lights
                conn.execute("""
                    UPDATE platform_requests SET status = 'completed'
                    WHERE request_id = %s
                """, (request_id,))
                return True
            return False
```

### 4. ID Generation Pattern

Both use deterministic SHA256 hashing:

```python
# CoreMachine Pattern (Existing)
def generate_job_id(job_type: str, params: dict) -> str:
    """Deterministic job ID from parameters"""
    canonical = f"{job_type}:{json.dumps(params, sort_keys=True)}"
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]

# Platform Pattern (New - Same Approach)
def generate_request_id(dataset_id: str, resource_id: str, version_id: str) -> str:
    """Deterministic request ID from DDH identifiers"""
    # Add timestamp to allow reprocessing same dataset
    timestamp = datetime.utcnow().isoformat()
    canonical = f"{dataset_id}:{resource_id}:{version_id}:{timestamp}"
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]
```

### 5. Repository Pattern

Both follow identical repository patterns:

```python
# ============================================================================
# CoreMachine Pattern (Existing)
# ============================================================================
class JobRepository:
    def create_job(self, job: JobRecord) -> JobRecord
    def get_job(self, job_id: str) -> Optional[JobRecord]
    def update_job_status(self, job_id: str, status: str) -> bool
    def get_job_tasks(self, job_id: str) -> List[TaskRecord]
    def check_job_completion(self, job_id: str) -> bool

class TaskRepository:
    def create_task(self, task: TaskRecord) -> TaskRecord
    def get_task(self, task_id: str) -> Optional[TaskRecord]
    def update_task_status(self, task_id: str, status: str) -> bool
    def get_tasks_by_job(self, job_id: str) -> List[TaskRecord]

# ============================================================================
# Platform Pattern (New - Identical Structure)
# ============================================================================
class PlatformRepository:
    def create_request(self, request: PlatformRecord) -> PlatformRecord
    def get_request(self, request_id: str) -> Optional[PlatformRecord]
    def update_request_status(self, request_id: str, status: str) -> bool
    def get_request_jobs(self, request_id: str) -> List[JobRecord]
    def check_request_completion(self, request_id: str) -> bool

class PlatformJobRepository:
    def create_mapping(self, mapping: PlatformJobMapping) -> PlatformJobMapping
    def get_jobs_for_request(self, request_id: str) -> List[PlatformJobMapping]
    def update_job_status(self, request_id: str, job_id: str, status: str) -> bool
```

### 6. Message Flow Pattern

Both use Service Bus for asynchronous processing:

```
# CoreMachine Flow (Existing)
HTTP → Jobs Queue → CoreMachine.process_job → Tasks Queue → CoreMachine.process_task

# Platform Flow (New - Adds Layer Above)
HTTP → Platform Queue → PlatformOrchestrator.process_request → Jobs Queue → CoreMachine
```

### 7. Error Handling Pattern

Both follow the same error propagation:

```python
# CoreMachine Pattern (Existing)
- Task fails → Task marked FAILED
- All tasks complete → Check if any failed
- Any task failed → Job marked FAILED
- All tasks success → Job marked COMPLETED

# Platform Pattern (New - Same Logic)
- Job fails → Job marked FAILED (by CoreMachine)
- All jobs complete → Check if any failed
- Any job failed → Request marked FAILED
- All jobs success → Request marked COMPLETED
```

## Database Schema Following Pattern

```sql
-- ============================================================================
-- Platform tables mirror job/task structure
-- ============================================================================

-- Platform Request table (mirrors jobs table)
CREATE TABLE platform.requests (
    request_id VARCHAR(32) PRIMARY KEY,
    dataset_id VARCHAR(255) NOT NULL,
    resource_id VARCHAR(255) NOT NULL,
    version_id VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    parameters JSONB NOT NULL DEFAULT '{}',
    metadata JSONB NOT NULL DEFAULT '{}',
    result_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Indexes matching job table pattern
    INDEX idx_platform_status (status),
    INDEX idx_platform_dataset (dataset_id),
    INDEX idx_platform_created (created_at DESC)
);

-- Platform-Job mapping table (mirrors task relationship to job)
CREATE TABLE platform.request_jobs (
    request_id VARCHAR(32) NOT NULL,
    job_id VARCHAR(32) NOT NULL,
    job_type VARCHAR(100) NOT NULL,
    sequence INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),

    PRIMARY KEY (request_id, job_id),
    FOREIGN KEY (request_id) REFERENCES platform.requests(request_id),
    INDEX idx_request_jobs_status (request_id, status)
);
```

## Code Example: Platform Request Handler

Following the exact pattern of CoreMachine's job handler:

```python
class PlatformOrchestrator:
    """Mirrors CoreMachine but at platform level"""

    def process_platform_request(self, message: ServiceBusMessage):
        """Process platform request - mirrors process_job_message"""
        try:
            # 1. Parse message (same as CoreMachine)
            request_data = json.loads(str(message))
            request_id = request_data["request_id"]

            # 2. Get request from database (same as get_job)
            request = self.platform_repo.get_request(request_id)
            if not request:
                logger.error(f"Request {request_id} not found")
                return

            # 3. Update status to processing (same as job)
            self.platform_repo.update_request_status(
                request_id,
                PlatformRequestStatus.PROCESSING
            )

            # 4. Create jobs based on data type (like job creates tasks)
            jobs = self._create_jobs_for_request(request)

            # 5. Submit jobs to CoreMachine (like job submits tasks)
            for job in jobs:
                self._submit_job_to_coremachine(job)

            # 6. Completion handled by callbacks (same pattern)
            # When CoreMachine completes a job, it notifies platform
            # Last job completion triggers request completion

        except Exception as e:
            logger.error(f"Failed processing request: {e}")
            self.platform_repo.update_request_status(
                request_id,
                PlatformRequestStatus.FAILED
            )

    def handle_job_completion(self, job_id: str):
        """Called when CoreMachine job completes - mirrors task completion"""
        # 1. Find platform request for this job
        mapping = self.platform_job_repo.get_mapping_by_job(job_id)
        if not mapping:
            return

        # 2. Update job status in mapping
        job = self.job_repo.get_job(job_id)
        self.platform_job_repo.update_job_status(
            mapping.request_id,
            job_id,
            job.status
        )

        # 3. Check if all jobs complete (last job turns out lights)
        if self.platform_repo.check_request_completion(mapping.request_id):
            # 4. Aggregate results (like job aggregates task results)
            self._aggregate_request_results(mapping.request_id)

            # 5. Notify DDH of completion
            self._notify_ddh_completion(mapping.request_id)
```

## Pattern Benefits

By following CoreMachine patterns exactly:

1. **Consistency**: Same mental model at both layers
2. **Predictability**: Developers know what to expect
3. **Reusability**: Can reuse validation, error handling, completion logic
4. **Testability**: Same testing patterns apply
5. **Maintainability**: Changes to pattern apply uniformly

## Key Parallels

| CoreMachine | Platform Service | Purpose |
|------------|------------------|---------|
| Job | PlatformRequest | Orchestration unit |
| Task | Job (CoreMachine) | Unit of work |
| JobRecord | PlatformRecord | Database entity |
| TaskRecord | PlatformJobMapping | Child entity |
| JobRepository | PlatformRepository | Data access |
| process_job_message | process_platform_request | Message handler |
| check_job_completion | check_request_completion | Completion detection |
| JobStatus | PlatformRequestStatus | State machine |
| job_id (SHA256) | request_id (SHA256) | Deterministic ID |

## Implementation Order

Following CoreMachine's implementation:

1. **Database Schema** (like job/task tables)
2. **Pydantic Models** (like JobRecord/TaskRecord)
3. **Repository Layer** (like JobRepository/TaskRepository)
4. **Orchestrator** (like CoreMachine)
5. **Service Bus Integration** (like job/task queues)
6. **HTTP Endpoints** (like job submission endpoints)
7. **Completion Callbacks** (like task completion handling)

This ensures the Platform Service Layer is a natural extension of CoreMachine, not a foreign addition.