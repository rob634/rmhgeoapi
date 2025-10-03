# Service Bus Hello World Execution Trace
**Date**: 28 SEP 2025
**Purpose**: Detailed line-by-line execution trace for sb_hello_world job processing through stage 1 completion

## Overview
This trace follows the complete execution path from HTTP job submission through task completion and stage advancement for the Service Bus pipeline.

---

## Phase 1: Job Submission (HTTP Trigger)

### 1.1 HTTP Request Entry
**File**: `function_app.py`
**Function**: `submit_job` (Line ~577)

```
Line 577: @app.function_name(name="submit_job")
Line 578: @app.route(route="jobs/submit/{job_type}", methods=["POST"])
Line 579: def submit_job(req: func.HttpRequest) -> func.HttpResponse:
```

### 1.2 Job Type Validation
**File**: `function_app.py`
```
Line 586: job_type = req.route_params.get('job_type')
Line 588: if job_type == "sb_hello_world":
Line 589:     # Creates ServiceBusHelloWorldController
```

### 1.3 Controller Creation
**File**: `controller_factories.py`
```
Line 89: if use_service_bus:
Line 90:     sb_job_type = f"sb_{job_type}"  # Creates "sb_hello_world"
Line 93:     controller_class = JobFactory._catalog.get_controller(sb_job_type)
Line 108: controller = controller_class()  # ServiceBusHelloWorldController instance
```

### 1.4 Job Creation & Queueing
**File**: `controller_service_bus_hello.py`
```
Line 163: def process_job_request(self, parameters: Dict[str, Any]) -> JobSubmissionResponse:
Line 178:     job_id = self.calculate_job_id(job_type, canonical_params)
Line 194:     job_record = JobRecord(...)
Line 208:     job_repo.create_job(job_record)
Line 221:     job_message = JobQueueMessage(...)
Line 240:     service_bus_repo.send_message(
Line 241:         queue_name=config.AZURE_SERVICE_BUS_JOB_QUEUE_NAME,  # "geospatial-jobs"
Line 242:         message=job_message
Line 243:     )
```

---

## Phase 2: Job Queue Processing (Service Bus Trigger)

### 2.1 Service Bus Job Queue Trigger
**File**: `function_app.py`
```
Line 970: @app.function_name(name="process_service_bus_job")
Line 971: @app.service_bus_queue_trigger(
Line 972:     queue_name="geospatial-jobs",
Line 973:     connection="ServiceBusConnection"
Line 974: )
Line 975: def process_service_bus_job(msg: func.ServiceBusMessage) -> None:
```

### 2.2 Job Message Deserialization
**File**: `function_app.py`
```
Line 992:  message_body = msg.get_body().decode('utf-8')
Line 993:  job_message = JobQueueMessage.model_validate_json(message_body)
```

### 2.3 Controller Routing
**File**: `function_app.py`
```
Line 998:  if job_message.job_type == "sb_hello_world":
Line 999:      from controller_service_bus_hello import ServiceBusHelloWorldController
Line 1000:     controller = ServiceBusHelloWorldController()
```

### 2.4 Job Processing
**File**: `function_app.py`
```
Line 1004: controller.process_job_queue_message(job_message)
```

**File**: `controller_service_bus_hello.py`
```
Line 283: def process_job_queue_message(self, job_message: JobQueueMessage) -> Dict[str, Any]:
Line 295:     job_record = job_repo.get_job(job_message.job_id)
Line 309:     if job_message.stage == 1:
Line 310:         return self._process_stage_1(job_message, job_record)
```

### 2.5 Stage 1 Task Creation
**File**: `controller_service_bus_hello.py`
```
Line 398: def _process_stage_1(self, job_message: JobQueueMessage, job_record: JobRecord):
Line 404:     n = job_record.parameters.get('n', 3)
Line 407:     tasks = []
Line 408:     for i in range(n):
Line 409:         task_message = TaskQueueMessage(
Line 410:             task_id=f"{job_message.job_id[:8]}-s1-greet-{i:04d}",
Line 411:             parent_job_id=job_message.job_id,
Line 412:             job_type=self.get_job_type(),  # "sb_hello_world"
Line 413:             task_type="hello_world_greeting",
Line 414:             stage=1,
Line 415:             task_index=str(i),
Line 416:             parameters={
Line 417:                 "name": f"User_{i}",
Line 418:                 "index": i,
Line 419:                 "message": job_record.parameters.get('message', 'Hello')
Line 420:             }
Line 421:         )
Line 422:         tasks.append(task_message)
```

### 2.6 Task Record Creation & Queueing
**File**: `controller_service_bus_hello.py`
```
Line 426:     for task_message in tasks:
Line 427:         task_record = TaskRecord(...)
Line 436:         task_repo.create_task(task_record)
Line 439:         service_bus_repo.send_message(
Line 440:             queue_name=config.AZURE_SERVICE_BUS_TASK_QUEUE_NAME,  # "geospatial-tasks"
Line 441:             message=task_message
Line 442:         )
```

---

## Phase 3: Task Queue Processing (Service Bus Trigger)

### 3.1 Service Bus Task Queue Trigger
**File**: `function_app.py`
```
Line 1144: @app.function_name(name="process_service_bus_task")
Line 1145: @app.service_bus_queue_trigger(
Line 1146:     queue_name="geospatial-tasks",
Line 1147:     connection="ServiceBusConnection"
Line 1148: )
Line 1149: def process_service_bus_task(msg: func.ServiceBusMessage) -> None:
```

### 3.2 Task Message Deserialization
**File**: `function_app.py`
```
Line 1169: message_body = msg.get_body().decode('utf-8')
Line 1173: task_message = TaskQueueMessage.model_validate_json(message_body)
```

### 3.3 Mark Task as Processing
**File**: `function_app.py`
```
Line 1180: repos = RepositoryFactory.create_repositories()
Line 1181: task_repo = repos['task_repo']
Line 1184: task_repo.update_task_status_with_validation(
Line 1185:     task_message.task_id,
Line 1186:     TaskStatus.PROCESSING
Line 1187: )
```

### 3.4 Get Controller for Task Processing
**File**: `function_app.py`
```
Line 1198: from controller_factories import JobFactory
Line 1201: job_type = task_message.job_type  # "sb_hello_world"
Line 1209: controller = JobFactory.create_controller(job_type)
```

### 3.5 Controller Processes Task
**File**: `function_app.py`
```
Line 1213: result = controller.process_task_queue_message(task_message)
```

**File**: `controller_service_bus_hello.py`
```
Line 669: def process_task_queue_message(self, task_message) -> Dict[str, Any]:
Line 690: # Get task handler - needs both task_message and repository
Line 691: from repositories.factories import RepositoryFactory
Line 692: repos = RepositoryFactory.create_repositories()
Line 693: task_repo = repos['task_repo']
Line 694: handler = TaskHandlerFactory.get_handler(task_message, task_repo)
Line 697: result = handler(task_message.parameters)
```

### 3.6 Task Handler Execution
**File**: `task_factory.py`
```
Line 82: def get_handler(task_message: TaskQueueMessage, repository: Optional[BaseRepository] = None):
Line 107: handler_factory = TaskHandlerFactory._catalog.get_handler(task_message.task_type)
Line 109: base_handler = handler_factory()  # Gets hello_world_greeting handler
Line 121: def handler_with_context(params: Dict[str, Any]) -> TaskResult:
Line 131:     result_data = base_handler(params, context)  # Executes actual task
Line 154:     return TaskResult(
Line 155:         task_id=context.task_id,
Line 159:         status=TaskStatus.COMPLETED,
Line 160:         result_data=result_data,
Line 163:     )
```

### 3.7 Task Completion with Stage Check (CRITICAL PATH)
**File**: `controller_service_bus_hello.py`
```
Line 708: completion = self.state_manager.complete_task_with_sql(
Line 709:     task_message.task_id,
Line 710:     task_message.parent_job_id,
Line 711:     task_message.stage,
Line 712:     result  # TaskResult object
Line 713: )
```

**File**: `state_manager.py`
```
Line 473: def complete_task_with_sql(self, task_id: str, job_id: str, stage: int, task_result: Optional[TaskResult] = None):
Line 501: repos = RepositoryFactory.create_repositories()
Line 502: completion_repo = repos['stage_completion_repo']
Line 506: if task_result and task_result.success:
Line 507:     stage_completion = completion_repo.complete_task_and_check_stage(
Line 508:         task_id=task_id,
Line 509:         job_id=job_id,
Line 510:         stage=stage,
Line 511:         result_data=task_result.result_data if task_result.result_data else {},
Line 512:         error_details=None
Line 513:     )
```

**File**: `repositories/postgresql.py`
```
Line 1532: def complete_task_and_check_stage(self, task_id: str, job_id: str, stage: int, ...):
Line 1551: query = sql.SQL("""
Line 1552:     SELECT * FROM app.complete_task_and_check_stage(
Line 1553:         %s::VARCHAR,  -- task_id
Line 1554:         %s::VARCHAR,  -- job_id
Line 1555:         %s::INTEGER,  -- stage
Line 1556:         %s::JSONB,    -- result_data
Line 1557:         %s::TEXT      -- error_details
Line 1558:     );
Line 1559: """)
Line 1565: cursor.execute(query, (task_id, job_id, stage, Json(result_data), error_details))
Line 1566: result = cursor.fetchone()
```

### 3.8 PostgreSQL Function Execution (Database)
**SQL Function**: `app.complete_task_and_check_stage`
```sql
-- This function atomically:
-- 1. Updates task status to COMPLETED
-- 2. Checks if all tasks in stage are complete
-- 3. Returns stage_complete flag
-- 4. Uses advisory locks to prevent race conditions
```

### 3.9 Stage Completion Check
**File**: `controller_service_bus_hello.py`
```
Line 716: if completion.stage_complete:
Line 717:     self.logger.info(f"🎯 Stage {task_message.stage} complete for job {task_message.parent_job_id}")
Line 719:     repos = RepositoryFactory.create_repositories()
Line 720:     job_repo = repos['job_repo']
Line 721:     job_record = job_repo.get_job(task_message.parent_job_id)
```

---

## Phase 4: Stage Advancement (If Last Task)

### 4.1 Check if Should Advance
**File**: `controller_service_bus_hello.py`
```
Line 722: should_advance = self.should_advance_stage(
Line 723:     task_message.parent_job_id,
Line 724:     task_message.stage,
Line 725:     {}
Line 726: )
```

**File**: `controller_service_bus_hello.py`
```
Line 144: def should_advance_stage(self, job_id: str, current_stage: int, stage_results: Dict[str, Any]) -> bool:
Line 150:     if current_stage < 2:  # Stage 1 -> advance to Stage 2
Line 151:         return True
```

### 4.2 Queue Next Stage
**File**: `controller_service_bus_hello.py`
```
Line 731: if should_advance:
Line 733:     next_message = JobQueueMessage(
Line 734:         job_id=task_message.parent_job_id,
Line 735:         job_type=self.get_job_type(),
Line 736:         parameters=job_record.parameters,
Line 737:         stage=task_message.stage + 1,  # Stage 2
Line 738:         correlation_id=str(uuid.uuid4())[:8]
Line 739:     )
Line 742:     config = AppConfig.from_environment()
Line 743:     service_bus_repo = RepositoryFactory.create_service_bus_repository()
Line 744:     service_bus_repo.send_message(
Line 745:         queue_name=config.AZURE_SERVICE_BUS_JOB_QUEUE_NAME,
Line 746:         message=next_message
Line 747:     )
```

### 4.3 Return Success
**File**: `controller_service_bus_hello.py`
```
Line 769: return {
Line 770:     'success': True,
Line 771:     'task_id': task_message.task_id,
Line 772:     'stage_complete': completion.stage_complete if hasattr(completion, 'stage_complete') else False
Line 773: }
```

---

## Critical Points of Failure

### ❌ Point 1: TaskHandlerFactory.get_handler
**Issue**: Was passing just `task_message.task_type` instead of full `task_message` and `task_repo`
**Fixed**: Line 694 now correctly calls with both parameters

### ❌ Point 2: AttributeError on task_message.job_id
**Issue**: TaskQueueMessage has `parent_job_id`, not `job_id`
**Fixed**: All references updated to use `parent_job_id`

### ❌ Point 3: Error Handling Fallback
**Issue**: function_app.py had fallback that hid controller errors
**Fixed**: Removed fallback, now properly marks tasks as failed

### ⚠️ Point 4: Stage Completion Detection
**Location**: Line 716 - Relies on PostgreSQL function returning correct `stage_complete` flag
**Potential Issue**: If SQL function fails or returns wrong result, stage won't advance

### ⚠️ Point 5: Service Bus Message Completion
**Location**: After Line 773 return - Azure Functions SDK must complete the Service Bus message
**Potential Issue**: If exception occurs, message may retry indefinitely

---

## Expected Flow for 3 Tasks

1. **Task 1 Completes**:
   - SQL function returns `stage_complete: false, remaining_tasks: 2`
   - No stage advancement

2. **Task 2 Completes**:
   - SQL function returns `stage_complete: false, remaining_tasks: 1`
   - No stage advancement

3. **Task 3 Completes** (Last Task):
   - SQL function returns `stage_complete: true, remaining_tasks: 0`
   - Stage advancement triggered
   - Stage 2 JobQueueMessage sent to Service Bus

---

## Current Status
Tasks are getting stuck in "processing" status at Line 1186 in function_app.py and never reaching the completion logic. The fixes have been deployed but may take time for Azure Functions to pick up the new code.