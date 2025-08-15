# Logging System Improvements

## Overview

Implemented a centralized logging system based on the original/ancient code architecture - much better than the previous fragmented approach.

## Key Improvements

### ✅ **Before (Fragmented)**
```python
# In every module - different loggers:
self.logger = create_buffered_logger(
    name=f"{__name__}.JobRepository",  # Different names!
    capacity=200,
    flush_level=logging.ERROR
)
```

### ✅ **After (Centralized)**
```python
# Single import in all modules:
from logger_setup import logger

# Same logger instance everywhere:
logger.info("Message from any module")
```

## Architecture Benefits

### 1. **Single Log Stream**
- All modules write to the same logger instance
- Unified log output with consistent formatting
- Complete trace of job processing across all modules

### 2. **Environment Detection**
- **Local Development**: Colored output with direct logging
- **Azure Functions**: Buffered logging with auto-flush on warnings/errors
- Automatic detection via environment variables

### 3. **Enhanced Logging Methods**
```python
# Job processing stages
logger.log_job_stage(job_id, "queue_processing", "processing", duration=1.5)

# Storage operations
logger.log_storage_operation("list_container", "bronze", "file.json", "success")

# Queue operations
logger.log_queue_operation(job_id, "processing_start")

# Service processing
logger.log_service_processing("HelloWorldService", "hello_world", job_id, "completed")

# Geometry statistics
logger.log_geometry_stats(feature_count=150, invalid_count=2, bounds=(x1,y1,x2,y2))
```

### 4. **Automatic Log Collection**
```python
# Get warning/error messages for debugging
messages = get_log_messages()

# Clear collected messages
clear_log_messages()

# Manual flush for Azure Functions
flush_logs()
```

## Configuration

### **Environment Variables**
- `LOG_LEVEL`: Set logging level (DEBUG, INFO, WARNING, ERROR)
- Auto-detected Azure Functions environment

### **Buffer Settings**
- **Local Dev**: Direct logging with colors
- **Azure Functions**: Buffered (10 messages) with auto-flush on warnings/errors

## Example Log Output

### **Structured Job Processing Logs**
```
2025-08-15 18:21:27 - INFO - RMHGeoAPI_Azure - log_job_stage:100 - JOB_STAGE job_id=test123456789... stage=initialization status=success duration=1.50s
2025-08-15 18:21:27 - INFO - RMHGeoAPI_Azure - log_storage_operation:108 - STORAGE_OP operation=list_container container=bronze blob=test.json status=success
2025-08-15 18:21:27 - INFO - RMHGeoAPI_Azure - log_queue_operation:112 - QUEUE_OP job_id=test123456789... operation=added_to_queue queue=geospatial-jobs
2025-08-15 18:21:27 - INFO - RMHGeoAPI_Azure - log_service_processing:116 - SERVICE_PROC service=HelloWorldService operation=hello_world job_id=test123456789... status=completed
```

### **Colored Local Development**
- 🟢 INFO messages in green
- 🟡 WARNING messages in yellow  
- 🔴 ERROR messages in red
- 🔵 DEBUG messages in blue

## Debugging Benefits

### **Queue Processing Issues**
With the centralized logger, you'll now see complete traces like:
```
JOB_STAGE job_id=abc123... stage=queue_processing status=processing
QUEUE_OP job_id=abc123... operation=processing_start queue=geospatial-jobs
SERVICE_PROC service=HelloWorldService operation=hello_world job_id=abc123... status=processing
JOB_STAGE job_id=abc123... stage=hello_world_start status=processing
JOB_STAGE job_id=abc123... stage=hello_world_complete status=completed
SERVICE_PROC service=HelloWorldService operation=hello_world job_id=abc123... status=completed
JOB_STAGE job_id=abc123... stage=queue_processing status=completed
QUEUE_OP job_id=abc123... operation=processing_complete queue=geospatial-jobs
```

### **Missing Logs = Missing Processing**
If queue processing fails, you'll see exactly where it stops:
- ✅ Job submission logs
- ❌ Missing queue processing logs = queue trigger not firing
- ✅ Manual processing logs = business logic works

## Migration Status

### ✅ **Completed**
- `logger_setup.py` - Centralized logging system
- `function_app.py` - Updated to use centralized logger
- `repositories.py` - Updated to use centralized logger (partial)
- `services.py` - Updated with enhanced logging methods

### 🔄 **Still To Do**
- Complete all `self.logger` → `logger` replacements in `repositories.py`
- Update `models.py` if it has logging
- Update any other modules that use `create_buffered_logger`

## Usage Guidelines

### **Standard Logging**
```python
from logger_setup import logger

logger.debug("Debug information")
logger.info("General information") 
logger.warning("Warning message")
logger.error("Error message")
```

### **Enhanced Geospatial Logging**
```python
# Use structured logging methods for better debugging
logger.log_job_stage(job_id, stage, status, duration)
logger.log_storage_operation(operation, container, blob, status)
logger.log_queue_operation(job_id, operation)
logger.log_service_processing(service, operation_type, job_id, status)
```

### **Debugging Helpers**
```python
# Collect warning/error messages
messages = get_log_messages()

# Clear collected messages  
clear_log_messages()

# Force flush buffers (Azure Functions)
flush_logs()
```

## Result

This centralized logging system will make debugging the poison queue issue much easier. You'll see exactly:

1. ✅ **When jobs are submitted** (HTTP endpoint logs)
2. ✅ **When jobs are queued** (queue operation logs)  
3. ❌ **If queue processing starts** (missing = connection issue)
4. ✅ **Service processing details** (business logic logs)
5. ✅ **Job completion** (status update logs)

The poison queue issue will be immediately visible as a gap in the log sequence where queue processing should occur but doesn't.