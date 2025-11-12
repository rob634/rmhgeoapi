# Service Bus Job Execution Trace

**Date**: 2 OCT 2025  
**Author**: Robert and Geospatial Claude Legion

## Complete Execution Flow with Debug Logging

This document traces the complete execution path of a Service Bus job from submission to completion.

### 🔄 Phase 1: Job Submission (HTTP → Database → Service Bus)

#### HTTP Trigger (`triggers/submit_job.py`)
```
1. HTTP POST /api/jobs/submit/hello_world
2. Extract job parameters from request body
3. Get job class from registry
4. Call HelloWorldJob.validate_job_parameters()
5. Call HelloWorldJob.generate_job_id()
6. Call HelloWorldJob.create_job_record() → Database
7. Call HelloWorldJob.queue_job() → Service Bus
```

#### HelloWorldJob.queue_job() Logging
```
🚀 STEP 1: Starting queue_job for job_id={job_id}
   Parameters: {params}

📋 STEP 2: Loading configuration...
✅ STEP 2: Config loaded - queue_name=geospatial-jobs

🚌 STEP 3: Creating ServiceBusRepository...
✅ STEP 3: ServiceBusRepository created

📨 STEP 4: Creating JobQueueMessage with correlation_id={correlation_id}
✅ STEP 4: JobQueueMessage created - job_type=hello_world, stage=1

📤 STEP 5: Sending message to Service Bus queue: geospatial-jobs
✅ STEP 5: Message sent successfully - message_id={message_id}

🎉 SUCCESS: Job queued successfully
```

### 🔄 Phase 2: Service Bus Trigger (Queue → CoreMachine)

#### Service Bus Trigger (`function_app.py::process_job_service_bus`)
```
🚀 TRIGGER STEP 1: Service Bus job trigger fired

📥 TRIGGER STEP 2: Decoding message body...
✅ TRIGGER STEP 2: Message body decoded ({bytes} bytes)
   Raw message: {first 200 chars}

📋 TRIGGER STEP 3: Parsing JobQueueMessage...
✅ TRIGGER STEP 3: JobQueueMessage parsed
   job_type=hello_world, job_id={id}, stage=1

🤖 TRIGGER STEP 4: Calling CoreMachine.process_job_message()...
✅ TRIGGER STEP 4: CoreMachine processing complete
   Result: {result}

🎉 TRIGGER SUCCESS: Job processing completed successfully
```

### 🔄 Phase 3: CoreMachine Processing (Job → Tasks)

#### CoreMachine.process_job_message() Logging
```
🎬 COREMACHINE STEP 1: Starting process_job_message
   job_id={id}, job_type=hello_world, stage=1

📋 COREMACHINE STEP 2: Looking up job_type 'hello_world' in registry...
✅ COREMACHINE STEP 2: Job class found - HelloWorldJob

💾 COREMACHINE STEP 3: Fetching job record from database...
✅ COREMACHINE STEP 3: Job record retrieved - parameters=['n', 'message']

📝 COREMACHINE STEP 4: Updating job status to PROCESSING...
✅ COREMACHINE STEP 4: Job status updated to PROCESSING

🏗️ COREMACHINE STEP 5: Creating tasks for stage 1...
✅ COREMACHINE STEP 5: Created N tasks for stage 1
   Task IDs: [task_id_1, task_id_2, ...]

📤 COREMACHINE STEP 6: Queuing N tasks...
✅ COREMACHINE STEP 6: Tasks queued successfully
```

## Error Handling

Each step has granular try/except blocks that will log:
- **✅ SUCCESS** - Step completed
- **❌ FAILED** - Step failed with specific error
- **⚠️ WARNING** - Non-critical issue

### Example Error Log
```
❌ COREMACHINE STEP 5 FAILED: Task creation error: {error}
   Traceback: {full traceback}
```

## Debugging Tips

1. **Follow the correlation_id** - Traces a single request across all components
2. **Check step numbers** - Identifies exactly where execution stopped
3. **Look for emojis** - Quick visual scanning:
   - 🚀 = Start
   - ✅ = Success
   - ❌ = Error
   - ⚠️ = Warning
   - 🎉 = Complete

## Key Components

| Component | File | Logging Prefix |
|-----------|------|----------------|
| Job Submission | `jobs/hello_world.py` | `STEP 1-5` |
| Service Bus Trigger | `function_app.py` | `TRIGGER STEP 1-4` |
| CoreMachine | `core/machine.py` | `COREMACHINE STEP 1-6` |

## Application Insights Query

```kql
traces
| where timestamp >= ago(1h)
| where message contains "STEP" or message contains "TRIGGER" or message contains "COREMACHINE"
| project timestamp, message, severityLevel
| order by timestamp asc
```

---

**Note**: This is a SERVICE BUS ONLY application. Storage Queues are NOT supported.
