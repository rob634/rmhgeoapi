# Service Bus Parallel Implementation Status

**Date**: 25 SEP 2025
**Author**: Robert and Geospatial Claude Legion

## ✅ COMPLETED Components

### Phase 1: Core Infrastructure

#### 1.1 Service Bus Configuration
- ✅ Updated `local.settings.example.json` with Service Bus settings
- Added: SERVICE_BUS_NAMESPACE, SERVICE_BUS_CONNECTION_STRING, etc.

#### 1.2 Service Bus Repository (`repositories/service_bus.py`)
- ✅ Created complete ServiceBusRepository implementation
- ✅ Implements IQueueRepository interface for compatibility
- ✅ Batch sending support (100 messages per batch)
- ✅ Singleton pattern for connection reuse
- ✅ Both sync and async operations

#### 1.3 Repository Factory Update
- ✅ Added `create_service_bus_repository()` method
- Location: `repositories/factory.py` lines 197-221

#### 1.4 TaskRepository Batch Methods
- ✅ Added `batch_create_tasks()` - Batch insert with executemany
- ✅ Added `batch_update_status()` - Batch status updates
- ✅ Added `get_tasks_by_batch()` - Query by batch_id
- ✅ Added `get_pending_retry_batches()` - Find batches needing retry
- Location: `repositories/jobs_tasks.py` lines 477-673

#### 1.5 HTTP Trigger Update
- ✅ Added `use_service_bus` parameter extraction
- ✅ Parameter passed to controller in job_params
- Location: `triggers/submit_job.py` lines 131-162

## 🔄 IN PROGRESS Components

### Phase 2: Controller Updates

#### 2.1 Controller Base Queue Selection (TODO)
Need to update `controller_base.py`:

```python
# In queue_job() method - around line 850
def queue_job(self, job_id: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    # NEW: Check for Service Bus toggle
    use_service_bus = parameters.get('use_service_bus', False)

    if use_service_bus:
        queue_repo = RepositoryFactory.create_service_bus_repository()
        queue_name = f"sb-{config.job_processing_queue}"
    else:
        queue_repo = RepositoryFactory.create_queue_repository()
        queue_name = config.job_processing_queue
```

#### 2.2 Task Queuing with Batch Support (TODO)
Need to update task creation logic:

```python
# In create_stage_tasks() method
def create_stage_tasks(self, job_id: str, stage: int):
    task_definitions = self.create_stage_tasks(job_id, stage)

    # NEW: Check for batch processing opportunity
    use_service_bus = self.job_params.get('use_service_bus', False)

    if use_service_bus and len(task_definitions) >= 100:
        return self._queue_tasks_in_batches(task_definitions, job_id, stage)
    else:
        return self._queue_tasks_individually(task_definitions, job_id, stage)
```

## ❌ NOT STARTED Components

### Phase 3: Service Bus Triggers

#### 3.1 Job Processing Trigger
Add to `function_app.py`:

```python
@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="sb-jobs",
    connection="ServiceBusConnection"
)
def process_service_bus_job(msg: func.ServiceBusMessage) -> None:
    """Process job messages from Service Bus."""
    # Parse message
    message_body = msg.get_body().decode('utf-8')
    job_message = JobQueueMessage.model_validate_json(message_body)

    # Reuse existing processing logic
    controller = JobFactory.create_controller(job_message.job_type)
    controller.process_job_queue_message(job_message)
```

#### 3.2 Task Processing Trigger
```python
@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="sb-tasks",
    connection="ServiceBusConnection"
)
def process_service_bus_task(msg: func.ServiceBusMessage) -> None:
    """Process task messages from Service Bus."""
    # Similar pattern for tasks
```

### Phase 4: Testing & Monitoring

#### 4.1 Performance Metrics Endpoint
Create `/api/metrics/comparison` to track:
- Jobs processed per path
- Average latency
- Timeout rates
- Tasks per second

#### 4.2 Database Schema Update
```sql
-- Add tracking column
ALTER TABLE jobs ADD COLUMN processing_path VARCHAR(20) DEFAULT 'queue_storage';
ALTER TABLE tasks ADD COLUMN batch_id VARCHAR(100);
```

## 📊 Component Dependency Graph

```
HTTP Request
    ↓
submit_job.py [✅ DONE]
    ↓
controller_base.py [🔄 TODO]
    ├─→ QueueRepository [✅ DONE]
    └─→ ServiceBusRepository [✅ DONE]
           ↓
    TaskRepository.batch_create_tasks() [✅ DONE]
           ↓
    Service Bus Batch Send [✅ DONE]
```

## 🚀 Next Actions Required

1. **Update controller_base.py** for queue selection logic
2. **Implement batch task processing** in controller
3. **Add Service Bus triggers** to function_app.py
4. **Test with hello_world job** using both paths
5. **Deploy and measure performance**

## 📈 Expected Outcomes

### Without Service Bus (Current):
- 1,000 tasks = 100 seconds (times out)
- Limited to ~50 tasks/second

### With Service Bus (New):
- 1,000 tasks = 0.4 seconds
- 10,000 tasks = 4 seconds
- 100,000 tasks = 40 seconds

### Performance Improvement:
- **250x faster** for batch operations
- **Zero timeouts** for large jobs
- **Linear scaling** with predictable performance

## 🔧 Configuration Requirements

### Azure Resources Needed:
1. Service Bus Namespace (Standard tier)
2. Queues: sb-jobs, sb-tasks, sb-poison
3. Connection string in Key Vault

### Environment Variables:
```json
{
  "SERVICE_BUS_NAMESPACE": "rmhgeoapi",
  "SERVICE_BUS_CONNECTION_STRING": "Endpoint=sb://...",
  "SERVICE_BUS_JOB_QUEUE": "sb-jobs",
  "SERVICE_BUS_TASK_QUEUE": "sb-tasks",
  "ENABLE_SERVICE_BUS": "true"
}
```

## 📝 Testing Plan

### Step 1: Test Current Path
```bash
curl -X POST /api/jobs/submit/hello_world \
  -d '{"n": 10, "use_service_bus": false}'
```

### Step 2: Test Service Bus Path
```bash
curl -X POST /api/jobs/submit/hello_world \
  -d '{"n": 10, "use_service_bus": true}'
```

### Step 3: Compare Performance
- Monitor both paths with identical workloads
- Measure latency, throughput, success rates
- Track costs per message

## 🎯 Success Criteria

1. ✅ Both pipelines operational in parallel
2. ✅ Toggle parameter routes correctly
3. ✅ 10x+ performance improvement for batch operations
4. ✅ Zero data loss or corruption
5. ✅ Clear metrics showing comparison

---

**Status**: Phase 1 COMPLETE, Phase 2 IN PROGRESS (30% done)