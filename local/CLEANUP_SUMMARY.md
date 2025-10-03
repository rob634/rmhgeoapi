# Root Folder Cleanup - 2 OCT 2025

## Summary
Cleaned up root folder by moving all local development scripts to `/local` folder.

## Files Remaining in Root (Application Core - 4 files)
```
config.py              # ✅ Application configuration (Epoch 4)
exceptions.py          # ✅ Exception definitions
function_app.py        # ✅ Azure Functions entry point
util_logger.py         # ✅ Logging utilities
```

## Files Moved to /local (34 files)

### Shell Scripts (13 files)
- check_all_activity.sh
- check_errors.sh
- check_functions.sh
- check_logs.sh
- check_queue_messages.sh
- check_queue_triggers.sh
- check_schema_logs.sh
- check_service_bus.sh
- start_local_test.sh
- (and more .sh files)

### Python Scripts (21 files)
- controller_service_bus_container.py
- controller_service_bus_hello.py
- debug_service_bus.py
- test_core_machine.py
- test_deployment_ready.py
- update_epoch_headers.py
- update_to_descriptive_categories.py
- (and more .py files)

## Changes to config.py
Updated header to reflect Epoch 3 deprecation:
```python
# EPOCH: 4 - ACTIVE ✅
# STATUS: Epoch 3 COMPLETELY DEPRECATED - Service Bus only application
# NOTE: This is a SERVICE BUS ONLY application - Storage Queues are NOT supported
```

## Result
Root folder now contains ONLY essential application files.
All development/testing scripts are in `/local` folder.

**Author**: Robert and Geospatial Claude Legion  
**Date**: 2 OCT 2025
