# Debugging Poison Queue Issues

## What's Happening
Jobs are being moved to `geospatial-jobs-poison` because the queue processing function is throwing unhandled exceptions.

## Step 1: Check Azure Function Logs
```bash
# View recent logs in Azure portal
# Go to Function App → Functions → process_job_queue → Monitor
# Look for error messages around the time jobs were submitted
```

## Step 2: Check Environment Variables
The function needs these environment variables in production:

```bash
# Required for queue processing:
STORAGE_ACCOUNT_NAME=<your_storage_account>
BRONZE_CONTAINER_NAME=<bronze_container>
SILVER_CONTAINER_NAME=<silver_container>  
GOLD_CONTAINER_NAME=<gold_container>

# OR use connection string:
AzureWebJobsStorage=<connection_string>
```

## Step 3: Check Storage Account Configuration
Verify the managed identity has access:
1. Storage Account → Access Control (IAM)
2. Function App's managed identity should have:
   - Storage Blob Data Contributor
   - Storage Queue Data Contributor  
   - Storage Table Data Contributor

## Step 4: Test with Manual Processing
Use the manual processing endpoint to see exact error:

```bash
# Submit a job
JOB_RESPONSE=$(curl -X POST "https://rmhgeoapi-akdsa0fwd3hahtgx.eastus-01.azurewebsites.net/api/jobs/hello_world?code=XBQzu2hA7sprVAvfA9UN0FPD4yrD3c3tANMNCdZqeOqZAzFuNElLEA==" \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "debug-test", "resource_id": "test", "version_id": "v1.0.0"}')

# Extract job ID  
JOB_ID=$(echo $JOB_RESPONSE | jq -r '.job_id')

# Try manual processing to see the exact error
curl -X POST "https://rmhgeoapi-akdsa0fwd3hahtgx.eastus-01.azurewebsites.net/api/jobs/$JOB_ID/process?code=XBQzu2hA7sprVAvfA9UN0FPD4yrD3c3tANMNCdZqeOqZAzFuNElLEA=="
```

## Step 5: Check Poison Queue Messages
In Azure Storage Explorer or Portal:
1. Go to Storage Account → Queues
2. Look at `geospatial-jobs-poison` queue
3. Peek at messages to see what jobs are failing

## Step 6: Common Fixes

### Fix 1: Storage Connection Configuration
```python
# In Azure Function App Settings, ensure either:

# Option A: Connection String
AzureWebJobsStorage = "DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net"

# Option B: Managed Identity  
Storage__serviceUri = "https://yourstorageaccount.blob.core.windows.net"
Storage__queueServiceUri = "https://yourstorageaccount.queue.core.windows.net"  
Storage__tableServiceUri = "https://yourstorageaccount.table.core.windows.net"
```

### Fix 2: Container Configuration
```bash
# Set these in Function App Configuration:
STORAGE_ACCOUNT_NAME = "yourstorageaccount"
BRONZE_CONTAINER_NAME = "bronze"
SILVER_CONTAINER_NAME = "silver"
GOLD_CONTAINER_NAME = "gold"
```

### Fix 3: Queue Configuration Fix
If queue trigger connection is wrong, update function_app.py:
```python
# Change from:
@app.queue_trigger(arg_name="msg", queue_name="geospatial-jobs", connection="Storage")

# To match your connection string name:
@app.queue_trigger(arg_name="msg", queue_name="geospatial-jobs", connection="AzureWebJobsStorage")
```

## Step 7: Test Queue Processing
After fixes, test with a simple job:
```bash
curl -X POST "https://rmhgeoapi-akdsa0fwd3hahtgx.eastus-01.azurewebsites.net/api/jobs/hello_world?code=XBQzu2hA7sprVAvfA9UN0FPD4yrD3c3tANMNCdZqeOqZAzFuNElLEA==" \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "test", "resource_id": "test", "version_id": "v1.0.0"}'

# Wait 30 seconds then check status
JOB_ID="<job_id_from_response>"
curl "https://rmhgeoapi-akdsa0fwd3hahtgx.eastus-01.azurewebsites.net/api/jobs/$JOB_ID?code=XBQzu2hA7sprVAvfA9UN0FPD4yrD3c3tANMNCdZqeOqZAzFuNElLEA=="
```

## Most Likely Root Cause
Based on the code, the most likely issue is that the queue processing function can't access the storage account properly, causing repository initialization to fail when trying to:
1. Initialize JobRepository (Table Storage)
2. Initialize StorageRepository for container operations
3. Access containers that don't exist or lack permissions

The function fails immediately when trying to create these repository instances, leading to poison queue behavior.