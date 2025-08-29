# Consolidated Redesign Architecture
**Created**: August 29, 2025  
**Purpose**: Complete architectural redesign specification with clear abstractions  
**Status**: Foundation phase - ready for implementation  

## 🎯 **CORE DESIGN PRINCIPLE**

**Job → Stage → Task abstraction with clear separation of concerns:**

```
JOB (Controller Layer - Orchestration)
 ├── STAGE 1 (Controller Layer - Sequential)
 │   ├── Task A (Service + Repository Layer - Parallel)
 │   ├── Task B (Service + Repository Layer - Parallel) 
 │   └── Task C (Service + Repository Layer - Parallel)
 │                     ↓ Last task completes stage
 ├── STAGE 2 (Controller Layer - Sequential)
 │   ├── Task D (Service + Repository Layer - Parallel)
 │   └── Task E (Service + Repository Layer - Parallel)
 │                     ↓ Last task completes stage
 └── COMPLETION (job_type specific aggregation)
```

## 📋 **ABSTRACTION HIERARCHY**

### **JOB** (Controller Layer - Orchestration)
- **Purpose**: One or more stages with job_type specific completion methods
- **Responsibility**: Stage orchestration, final result aggregation
- **Implicit**: Always has a completion stage (final stage)
- **Location**: Controller layer doing orchestration

### **STAGE** (Controller Layer - Sequential)  
- **Purpose**: Queue up one or more tasks that can run in parallel
- **Responsibility**: Task creation, stage completion detection
- **Completion**: Last task to finish completes the stage
- **Transition**: Moves job to next stage or completion stage
- **Location**: Controller layer doing orchestration

### **TASK** (Service + Repository Layer - Business Logic)
- **Purpose**: Where the service and repository layers live
- **Responsibility**: Actual work execution (file processing, database ops, API calls)
- **Execution**: Parallel execution within each stage
- **Completion**: "Last task turns out the lights" pattern
- **Location**: Service + Repository layers for business logic

---

## 🏗️ **IMPLEMENTATION ARCHITECTURE**

### **Queue-Driven Orchestration**
```
HTTP Request → Jobs Queue → Job Controller → Tasks Queue → Task Processors
                   ↓              ↓               ↓             ↓
               Job Record    Stage Creation   Task Records   Service Layer
```

### **Message Flow**
1. **HTTP Trigger**: Creates job record + jobs queue message
2. **Jobs Queue Trigger**: Creates tasks records + tasks queue messages  
3. **Tasks Queue Trigger**: Processes individual tasks via service layer
4. **Completion Detection**: Last task triggers stage/job completion

### **Database Schema (PostgreSQL)** WE WILL USE TABLE STORAGE FOR DEV 
```sql
-- Jobs table
jobs: job_id, job_type, status, stage, parameters, metadata, result_data, created_at, updated_at

-- Tasks table  
tasks: id, job_id, task_type, status, stage, parameters, heartbeat, retry_count, metadata, result_data, created_at, updated_at
```

---

## 🔑 **KEY DESIGN FEATURES**

### **Sequential Stages with Parallel Tasks**
- **Stages execute sequentially**: Stage 1 → Stage 2 → ... → Completion
- **Tasks execute in parallel**: All tasks in a stage run concurrently
- **Results flow forward**: Previous stage results passed to next stage

### **"Last Task Turns Out the Lights"**
- **Atomic detection**: SQL operations prevent race conditions (in production)
- **Stage completion**: Last task in stage triggers transition
- **Job completion**: Last task in final stage triggers job completion

### **Idempotent Operations**
- **Job IDs**: SHA256 hash of parameters for natural deduplication
- **Duplicate submissions**: Return existing job without creating new one
- **Parameter consistency**: Same inputs always produce same job ID

### **Atomic Completion Detection**
```sql
-- Atomic task completion with stage checking
UPDATE tasks SET status='completed' WHERE id=$1 RETURNING job_id;
UPDATE jobs SET status = CASE 
    WHEN NOT EXISTS (SELECT 1 FROM tasks WHERE job_id=$1 AND status NOT IN ('completed', 'failed')) 
    THEN 'completed' 
    ELSE status 
END WHERE id=$1 RETURNING status;
```

---

## 🏛️ **ABSTRACT BASE CLASSES**

### **BaseController** (Job Orchestration)
```python
class BaseController(ABC):
    @abstractmethod
    def get_job_type(self) -> str: pass
    
    @abstractmethod 
    def define_stages(self) -> List[StageDefinition]: pass
    
    @abstractmethod
    def create_stage_tasks(self, stage, job_id, params, previous_results) -> List[TaskDefinition]: pass
    
    @abstractmethod
    def aggregate_job_results(self, job_id, all_stage_results) -> Dict[str, Any]: pass
```

### **BaseStage** (Stage Coordination)
```python
class BaseStage(ABC):
    @abstractmethod
    def create_tasks(self, context: StageExecutionContext) -> List[Dict[str, Any]]: pass
    
    @abstractmethod
    def should_skip_stage(self, context: StageExecutionContext) -> bool: pass
    
    @abstractmethod
    def validate_prerequisites(self, context: StageExecutionContext) -> bool: pass
```

### **BaseTask** (Service Layer Execution)
```python
class BaseTask(ABC):
    @abstractmethod
    def execute(self, context: TaskExecutionContext) -> Dict[str, Any]: pass
    
    @abstractmethod
    def validate_task_parameters(self, context: TaskExecutionContext) -> bool: pass
```

### **BaseJob** (Job State Management)
```python
class BaseJob(ABC):
    @abstractmethod
    def should_proceed_to_next_stage(self, context, completed_stage_results) -> bool: pass
    
    @abstractmethod
    def aggregate_final_results(self, context: JobExecutionContext) -> Dict[str, Any]: pass
```

---

## 🎯 **FIRST IMPLEMENTATION: Hello World Controller**

### **Two-Stage Design**
```python
# Stage 1: "Hello Worlds" 
- Creates n tasks: "Hello from task_{i}!"
- Tasks execute in parallel
- Last task triggers stage transition

# Stage 2: "Worlds Reply"
- Creates n tasks: "Hello {previous_task_id} from {current_task_id}!"  
- Uses Stage 1 results as input
- Last task triggers job completion

# Completion: Job Result Aggregation
{
  "hello_statistics": {
    "total_hellos_requested": 5,
    "hellos_completed_successfully": 5, 
    "worlds_replies_generated": 5,
    "success_rate": "100%"
  },
  "stage_1_messages": ["Hello from task_1!", ...],
  "stage_2_messages": ["Hello task_1 from task_6!", ...],
  "processing_time": "45 seconds"
}
```

### **API Usage**
```bash
# Submit Hello World job
POST /api/jobs/hello_world
{"n": 5, "message": "Custom greeting"}

# Check status
GET /api/jobs/{job_id}
# Returns: stage progress, task counts, results when complete
```

---

## 🚀 **IMPLEMENTATION PHASES**

### **Phase 1: Foundation** ⏳ IN PROGRESS
- [x] Abstract base classes designed
- [ ] Base classes implemented and tested
- [ ] Database schema updates
- [ ] Core models and enums

### **Phase 2: Hello World Controller** ⏳ PENDING
- [ ] HelloWorldController implementation  
- [ ] Two-stage Hello World logic
- [ ] Task creation and execution
- [ ] Result aggregation

### **Phase 3: Queue Integration** ⏳ PENDING
- [ ] Function app routing updates
- [ ] Controller factory integration
- [ ] Queue message handling
- [ ] Stage transition logic

### **Phase 4: Completion Detection** ⏳ PENDING
- [ ] Atomic SQL completion queries
- [ ] "Last task turns out lights" implementation
- [ ] Job completion workflow
- [ ] Error handling and retries

### **Phase 5: Testing & Validation** ⏳ PENDING
- [ ] Unit tests for all base classes
- [ ] Integration tests for Hello World
- [ ] Performance tests with large n values
- [ ] Concurrent job processing tests

---

## ✅ **ARCHITECTURAL BENEFITS**

### **Scalability**
- **Horizontal**: Tasks scale with Azure Functions parallel execution
- **Sequential**: Stages provide ordered pipeline processing
- **Queue-driven**: Natural load balancing and backpressure handling

### **Maintainability**  
- **Clear boundaries**: Controllers orchestrate, Tasks execute
- **Service isolation**: Business logic contained in task layer
- **Staged failures**: Stage failures don't cascade to other stages

### **Flexibility**
- **Individual stages**: Can be executed as separate jobs
- **Task independence**: Tasks can be retried independently
- **Workflow variants**: Different parallelization strategies per stage

### **Reliability**
- **Atomic operations**: Race-condition free completion detection  
- **Retry logic**: Exponential backoff for transient failures
- **Heartbeat monitoring**: Zombie detection and recovery

---

## 🔧 **INFRASTRUCTURE INTEGRATION**

### **Azure Functions Configuration**
- **Premium EP3**: 14GB RAM, 4 vCPU, 30-minute timeout
- **Queue triggers**: Jobs queue and tasks queue processing
- **Connection pooling**: PostgreSQL connection management
- **Application Insights**: Monitoring and metrics

### **PostgreSQL Database**
- **Atomic operations**: Race condition prevention
- **JSONB support**: Flexible metadata storage  
- **Connection pooling**: PgBouncer for serverless scale
- **Proper indexing**: Performance optimization

### **Queue Configuration**
```json
{
  "jobs_queue": {
    "visibility_timeout": "300s",
    "max_delivery_count": 3,
    "message_ttl": "24h"
  },
  "tasks_queue": {
    "visibility_timeout": "1800s", 
    "max_delivery_count": 3,
    "message_ttl": "48h",
    "dead_letter_queue": "tasks-dlq"
  }
}
```

---

## 📍 **MIGRATION STRATEGY**

### **1. Deprecation Phase**
- Add deprecation warnings to all existing controllers
- Document migration path for each operation type
- Maintain backward compatibility temporarily

### **2. Parallel Implementation**  
- Implement new architecture alongside existing system
- Route new job types to new architecture
- Migrate existing job types incrementally

### **3. Complete Migration**
- Remove deprecated controllers once all operations migrated
- Clean up legacy code and documentation
- Update API documentation and examples

---

## 🎉 **SUCCESS CRITERIA**

### **Technical Requirements**
- ✅ Multi-stage jobs with parallel tasks within stages
- ✅ Atomic completion detection without race conditions
- ✅ Individual stages can be executed as separate jobs
- ✅ Service/Repository isolation in task layer
- ✅ Queue-driven orchestration with Azure Functions

### **Hello World Validation**
- ✅ Create job: `{"job_type": "hello_world", "n": 5}`
- ✅ Stage 1: Creates 5 parallel "Hello from task_X!" tasks
- ✅ Stage 2: Creates 5 parallel "Hello task_X from task_Y!" responses  
- ✅ Completion: Aggregated results with comprehensive statistics
- ✅ Concurrent jobs: Multiple Hello World jobs don't interfere

### **Production Readiness**
- ✅ Comprehensive error handling and retry logic
- ✅ Monitoring and metrics integration
- ✅ Performance testing with large workloads
- ✅ Documentation and developer onboarding materials

---

This consolidated design provides the foundation for a production-ready, scalable geospatial ETL platform with clear abstractions and proper separation of concerns.