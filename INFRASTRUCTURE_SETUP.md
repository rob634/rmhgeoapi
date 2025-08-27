# Infrastructure Setup and Validation

This document explains how the Azure Geospatial ETL Pipeline automatically ensures all required storage infrastructure exists and is properly configured.

## Overview

The system now includes comprehensive infrastructure initialization that:

✅ **Creates Azure Storage Tables** (Jobs, Tasks) with proper schemas  
✅ **Creates Azure Storage Queues** (processing and poison queues)  
✅ **Validates table and queue accessibility**  
✅ **Initializes PostgreSQL STAC schema** (optional)  
✅ **Provides health monitoring and diagnostics**  
✅ **Runs automatically on first request** (lazy initialization)

## Components

### InfrastructureInitializer Service
**File**: `infrastructure_initializer.py`

Handles creation and validation of all storage infrastructure:

```python
from infrastructure_initializer import InfrastructureInitializer

initializer = InfrastructureInitializer()
status = initializer.initialize_all()

if status.overall_success:
    print("✅ Infrastructure ready")
else:
    print(f"❌ Issues: {status.to_dict()}")
```

### Automatic Initialization
**File**: `function_app.py` (modified)

Infrastructure is initialized automatically:
- **First health check**: `/api/health`
- **First job submission**: `/api/jobs/{operation}`
- **Manual trigger**: `/api/infrastructure`

### Test Suite
**File**: `test_infrastructure_init.py`

Comprehensive testing script:
```bash
python test_infrastructure_init.py
```

## Infrastructure Components

### Storage Tables

| Table | Purpose | Schema |
|-------|---------|---------|
| **Jobs** | Job lifecycle tracking | `job_id`, `status`, `operation_type`, `dataset_id`, `resource_id`, `result_data`, etc. |
| **Tasks** | Task execution tracking | `task_id`, `parent_job_id`, `status`, `task_type`, `task_data`, etc. |

### Storage Queues

| Queue | Purpose |
|-------|---------|
| **geospatial-jobs** | Job processing queue |
| **geospatial-tasks** | Task processing queue |
| **geospatial-jobs-poison** | Failed job messages |
| **geospatial-tasks-poison** | Failed task messages |

### Database Schema (Optional)

| Component | Purpose |
|-----------|---------|
| **geo schema** | PostgreSQL schema for STAC data |
| **geo.collections** | STAC collections table |
| **geo.items** | STAC items table |

## API Endpoints

### Infrastructure Management
**Endpoint**: `/api/infrastructure`

**GET** - Check infrastructure status:
```json
{
  "initialized": true,
  "status": {
    "tables_created": ["Jobs", "Tasks"],
    "tables_validated": ["Jobs", "Tasks"],  
    "queues_created": ["geospatial-jobs", "geospatial-tasks"],
    "overall_success": true
  },
  "health": {
    "tables": {"Jobs": {"status": "healthy"}},
    "queues": {"geospatial-jobs": {"status": "healthy", "message_count": 0}}
  }
}
```

**POST** - Force re-initialization:
```bash
curl -X POST /api/infrastructure \
  -H "Content-Type: application/json" \
  -d '{"force_reinit": true}'
```

### Enhanced Health Check
**Endpoint**: `/api/health`

Now includes infrastructure validation and automatically initializes on first call.

## Usage Patterns

### 1. Automatic (Recommended)
Infrastructure initializes automatically on first use:

```python
# First request to any endpoint triggers initialization
response = requests.get("https://your-app.azurewebsites.net/api/health")
# Infrastructure is now ready
```

### 2. Manual Initialization
Force initialization before processing:

```python
import requests

# Force infrastructure setup
response = requests.post("https://your-app.azurewebsites.net/api/infrastructure", 
                        json={"force_reinit": true})

if response.status_code == 200:
    print("✅ Infrastructure ready")
```

### 3. Health Monitoring
Check infrastructure status:

```python
response = requests.get("https://your-app.azurewebsites.net/api/infrastructure")
data = response.json()

if data['status']['overall_success']:
    print("✅ All infrastructure healthy")
else:
    print("⚠️ Infrastructure issues detected")
```

## Testing

### Local Testing
```bash
# Set environment variables
export STORAGE_ACCOUNT_NAME="your_storage_account"
export AzureWebJobsStorage="DefaultEndpointsProtocol=https;..."

# Run comprehensive tests
python test_infrastructure_init.py
```

### Expected Output
```
🧪 Testing Infrastructure Initialization Service
============================================================
📋 Configuration:
  Storage Account: rmhazuregeo
  PostgreSQL Host: rmhpgflex.postgres.database.azure.com

1️⃣ Creating infrastructure initializer...
✅ Initializer created successfully

2️⃣ Checking current infrastructure health...
...

📊 SUMMARY
==============================
🎉 All tests PASSED!
✅ Tables: 2/2 healthy
✅ Queues: 4/4 healthy
✅ Idempotency: Working correctly
✅ Database: Initialized successfully
```

## Troubleshooting

### Common Issues

**❌ Missing STORAGE_ACCOUNT_NAME**
```
Solution: Set environment variable or check AzureWebJobsStorage configuration
```

**❌ Permission denied on table/queue creation**
```
Solution: Ensure managed identity has Storage Contributor role
```

**❌ Database connection failures**
```
Solution: Check POSTGIS_* environment variables and firewall rules
```

### Debug Mode

Enable detailed logging:
```python
import logging
logging.getLogger("infrastructure_initializer").setLevel(logging.DEBUG)
```

### Manual Recovery

If infrastructure gets corrupted:
```bash
# Force complete re-initialization
curl -X POST /api/infrastructure \
  -H "Content-Type: application/json" \
  -d '{"force_reinit": true, "include_database": true}'
```

## Best Practices

1. **Let it initialize automatically** - First health check or job submission will set up infrastructure
2. **Monitor infrastructure endpoint** - Use `/api/infrastructure` for status monitoring  
3. **Test after deployment** - Run `test_infrastructure_init.py` after each deployment
4. **Check poison queues** - Use `/api/monitor/poison` to check for failed messages
5. **Database is optional** - System works without PostgreSQL, just no STAC features

## Integration Points

### With Controllers
Controllers automatically get infrastructure via repository lazy loading:
```python
# In any controller
self.job_repo = JobRepository()  # Table created automatically
self.task_repo = TaskRepository()  # Table created automatically
```

### With Services
Services use repositories which handle infrastructure:
```python
# In any service
job_repo = JobRepository()  # Infrastructure ensured
job_repo.save_job(request)  # Table exists
```

### With Function App
Main endpoints ensure infrastructure before processing:
```python
@app.route(route="jobs/{operation_type}", methods=["POST"])
def submit_job(req: func.HttpRequest) -> func.HttpResponse:
    ensure_infrastructure_ready()  # Called automatically
    # ... rest of processing
```

This infrastructure setup ensures the system is always ready to process jobs and tasks without manual intervention.