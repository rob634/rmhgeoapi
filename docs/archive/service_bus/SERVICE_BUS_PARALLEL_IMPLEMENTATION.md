# Service Bus Parallel Implementation Plan

**Date**: 25 SEP 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: DESIGN PHASE

## 🎯 Objective

Implement a completely parallel Service Bus processing pipeline alongside the existing Queue Storage pipeline, with a toggle parameter to route jobs between systems.

## 🏗️ Architecture

```
HTTP Request
    ↓
    ├─[use_service_bus=false]→ Queue Storage → Queue Triggers → Task Handlers
    │                              (current)        (current)       (shared)
    │
    └─[use_service_bus=true]→ Service Bus → SB Triggers → Task Handlers
                                  (new)         (new)        (shared)
```

## 📋 Implementation Steps

### Phase 1: HTTP Toggle Parameter
```python
# In submit_job endpoint
req_body = {
    "dataset_id": "...",
    "use_service_bus": true,  # ← NEW TOGGLE
    "parameters": {...}
}
```

### Phase 2: Repository Selection Logic
```python
# In controller_base.py queue_job()
if job_params.get('use_service_bus', False):
    queue_repo = RepositoryFactory.create_service_bus_repository()
    queue_name = f"sb-{config.job_processing_queue}"  # Different queue names
else:
    queue_repo = RepositoryFactory.create_queue_repository()
    queue_name = config.job_processing_queue
```

### Phase 3: Service Bus Trigger Functions
```python
# In function_app.py - NEW FUNCTIONS

@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="sb-jobs",
    connection="ServiceBusConnection"
)
def process_service_bus_job(msg: func.ServiceBusMessage) -> None:
    """Process job messages from Service Bus."""
    # Reuse existing job processing logic
    message_body = msg.get_body().decode('utf-8')
    job_message = JobQueueMessage.model_validate_json(message_body)

    # Same processing as queue trigger
    controller = JobFactory.create_controller(job_message.job_type)
    controller.process_job_queue_message(job_message)

@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="sb-tasks",
    connection="ServiceBusConnection"
)
def process_service_bus_task(msg: func.ServiceBusMessage) -> None:
    """Process task messages from Service Bus."""
    # Reuse existing task processing logic
    message_body = msg.get_body().decode('utf-8')
    task_message = TaskQueueMessage.model_validate_json(message_body)

    # Same handler execution
    handler = TaskHandlerFactory.get_handler(task_message, repository)
    result = handler(task_message.parameters)
```

### Phase 4: Configuration Updates
```json
// local.settings.json
{
  "Values": {
    "STORAGE_ACCOUNT_NAME": "...",
    "SERVICE_BUS_NAMESPACE": "rmhgeoapi",
    "SERVICE_BUS_CONNECTION_STRING": "Endpoint=sb://...",
    "ENABLE_SERVICE_BUS": "true"
  }
}
```

### Phase 5: Performance Monitoring Endpoints
```python
# New endpoint: /api/metrics/comparison
{
  "queue_storage": {
    "jobs_processed": 1234,
    "avg_latency_ms": 450,
    "timeout_rate": 0.02,
    "tasks_per_second": 20
  },
  "service_bus": {
    "jobs_processed": 567,
    "avg_latency_ms": 120,
    "timeout_rate": 0.0,
    "tasks_per_second": 500
  },
  "comparison": {
    "latency_improvement": "73%",
    "throughput_improvement": "2400%",
    "timeout_reduction": "100%"
  }
}
```

## 🔄 Migration Strategy

### Stage 1: Silent Testing (Week 1)
- Deploy Service Bus infrastructure
- Route 1% of jobs with internal flag
- Monitor for errors

### Stage 2: Opt-in Beta (Week 2)
- Add `use_service_bus` parameter to API
- Document for power users
- Monitor performance metrics

### Stage 3: Gradual Rollout (Week 3-4)
- Default certain job types to Service Bus
- High-volume jobs (container_list, h3_hexagons)
- Keep low-volume on Queue Storage

### Stage 4: Full Migration (Week 5+)
- Default all new jobs to Service Bus
- Keep Queue Storage for backwards compatibility
- Phase out Queue Storage over time

## 📊 Success Metrics

1. **Timeout Elimination**
   - Current: 5-10% timeout rate for large jobs
   - Target: 0% timeouts with Service Bus

2. **Throughput Increase**
   - Current: ~50 messages/second (Queue Storage)
   - Target: 1000+ messages/second (Service Bus)

3. **Job Completion Time**
   - Container listing (10K files)
     - Current: 5-10 minutes
     - Target: 30 seconds
   - H3 Hexagon processing (100K hexagons)
     - Current: Times out
     - Target: 2-5 minutes

## 🚦 Decision Points

### When to Use Service Bus Path:
```python
def should_use_service_bus(job_type: str, params: dict) -> bool:
    # Explicit user choice
    if 'use_service_bus' in params:
        return params['use_service_bus']

    # High-volume job types
    if job_type in ['list_container', 'h3_hexagon_stats']:
        return True

    # Large task counts
    estimated_tasks = estimate_task_count(job_type, params)
    if estimated_tasks > 1000:
        return True

    # Default to Queue Storage for now
    return False
```

## 🔧 Implementation Details

### Service Bus Queue Names
- Jobs: `sb-jobs` (Service Bus) vs `jobs` (Queue Storage)
- Tasks: `sb-tasks` (Service Bus) vs `tasks` (Queue Storage)
- Poison: `sb-poison` (Service Bus) vs `poison` (Queue Storage)

### Message Format Compatibility
Both systems use the same Pydantic models:
- `JobQueueMessage`
- `TaskQueueMessage`

Service Bus adds metadata in application_properties for tracing.

### Database Recording
Add column to track processing path:
```sql
ALTER TABLE jobs ADD COLUMN processing_path VARCHAR(20) DEFAULT 'queue_storage';
-- Values: 'queue_storage', 'service_bus'
```

## 🎯 Key Benefits

1. **Zero-risk Testing**: Parallel implementation means no disruption
2. **Real Performance Data**: Compare identical workloads
3. **Gradual Migration**: Move job types one at a time
4. **Rollback Capability**: Can instantly switch back
5. **Cost Optimization**: Route based on job characteristics

## 📝 Code Changes Required

### 1. Update controller_base.py
- Add `use_service_bus` parameter handling
- Conditional repository selection
- Different queue name prefixes

### 2. Add to repositories/factory.py
```python
@staticmethod
def create_service_bus_repository() -> 'ServiceBusRepository':
    from .service_bus import ServiceBusRepository
    return ServiceBusRepository.instance()
```

### 3. New triggers in function_app.py
- `process_service_bus_job` function
- `process_service_bus_task` function
- Reuse existing processing logic

### 4. Update submit_job.py
- Accept `use_service_bus` parameter
- Pass through to controller

### 5. Add monitoring endpoints
- Track metrics per processing path
- Compare performance in real-time

## 🚀 Next Steps

1. **Confirm Service Bus namespace creation in Azure**
2. **Add SERVICE_BUS_CONNECTION to Key Vault**
3. **Implement Phase 1-2 (toggle + repository)**
4. **Deploy and test with hello_world job**
5. **Add Service Bus triggers (Phase 3)**
6. **Test high-volume scenarios**
7. **Build comparison dashboard**

## 📊 Expected Outcomes

### Week 1 Results:
- Both pipelines operational
- Basic performance metrics collected
- No production impact

### Month 1 Results:
- 90% reduction in timeout errors
- 10-20x throughput improvement for large jobs
- Clear data on cost implications

### Month 3 Results:
- Optimal routing logic established
- Automatic path selection based on job characteristics
- Full migration plan with timeline

---

**This parallel implementation approach provides:**
- ✅ Risk-free testing environment
- ✅ Real performance comparisons
- ✅ Gradual migration path
- ✅ Instant rollback capability
- ✅ Cost/performance optimization data