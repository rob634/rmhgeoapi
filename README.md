# Geospatial ETL Pipeline - Azure Functions MVP

Minimum viable deployable Azure Functions app for geospatial data processing with proper architecture patterns.

## 🎯 MVP Goals

- ✅ HTTP job submission with parameter validation
- ✅ HTTP job status checking  
- ✅ Queue-based job processing
- ✅ Idempotency via SHA256 job IDs
- ✅ Azure Table Storage for job tracking
- ✅ ABC classes for production architecture
- ✅ Hello world processing (prints all parameters beautifully)

## 🏗️ Architecture

**Controller → Service → Repository Pattern**

- **Controllers**: Azure Functions (HTTP/Queue triggers)
- **Services**: ABC classes with HelloWorldService implementation  
- **Repository**: Azure Table Storage for job tracking
- **Models**: Pure Python classes (no Pydantic yet)

## 📦 Files Structure

```
├── function_app.py          # Main Azure Functions app
├── services.py              # ABC classes + HelloWorldService
├── repositories.py          # Azure Table Storage operations
├── models.py                # JobRequest/JobStatus models
├── requirements.txt         # Minimal Azure dependencies
├── host.json               # Azure Functions configuration
├── local.settings.json     # Local development settings
├── test_api.py             # API test script
└── README.md               # This file
```

## 🚀 Deployment Instructions

### Local Development (WSL2)

1. **Install Azure Functions Core Tools**:
   ```bash
   # Ubuntu/Debian
   curl https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > microsoft.gpg
   sudo mv microsoft.gpg /etc/apt/trusted.gpg.d/microsoft.gpg
   sudo sh -c 'echo "deb [arch=amd64] https://packages.microsoft.com/repos/microsoft-ubuntu-$(lsb_release -cs)-prod $(lsb_release -cs) main" > /etc/apt/sources.list.d/dotnetdev.list'
   sudo apt update
   sudo apt install azure-functions-core-tools-4
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Start Azurite (local storage emulator)**:
   ```bash
   # Install if needed
   npm install -g azurite
   
   # Start Azurite
   azurite --silent --location /tmp/azurite --debug /tmp/azurite/debug.log
   ```

4. **Start Functions locally**:
   ```bash
   func start
   ```

5. **Test the API**:
   ```bash
   python test_api.py
   ```

### Azure Deployment

1. **Create Function App**:
   ```bash
   # Create resource group
   az group create --name rg-geospatial-etl --location eastus
   
   # Create storage account
   az storage account create --name stgeospatialetl123 --resource-group rg-geospatial-etl --location eastus --sku Standard_LRS
   
   # Create function app
   az functionapp create --resource-group rg-geospatial-etl --consumption-plan-location eastus --runtime python --runtime-version 3.11 --functions-version 4 --name func-geospatial-etl-123 --storage-account stgeospatialetl123
   ```

2. **Deploy code**:
   ```bash
   func azure functionapp publish func-geospatial-etl-123
   ```

## 📋 API Endpoints

### Submit Job
```bash
POST /api/jobs
Content-Type: application/json

{
  "dataset_id": "rwanda_land_cover_study",
  "resource_id": "landcover2023.tif", 
  "version_id": "1",
  "operation_type": "cog_conversion"
}
```

**Response**:
```json
{
  "job_id": "abc123def456...",
  "status": "queued",
  "message": "Job created and queued for processing",
  "dataset_id": "rwanda_land_cover_study",
  "resource_id": "landcover2023.tif",
  "version_id": "1",
  "operation_type": "cog_conversion"
}
```

### Check Job Status
```bash
GET /api/jobs/{job_id}
```

**Response**:
```json
{
  "job_id": "abc123def456...",
  "dataset_id": "rwanda_land_cover_study",
  "resource_id": "landcover2023.tif",
  "version_id": "1",
  "operation_type": "cog_conversion", 
  "status": "completed",
  "created_at": "2025-01-15T10:30:00",
  "updated_at": "2025-01-15T10:30:05",
  "result_data": {
    "status": "completed",
    "message": "Hello world processing completed successfully",
    "processed_items": { ... }
  }
}
```

## 🔍 Job ID Generation (Idempotency)

Jobs are identified by SHA256 hash of:
```
{operation_type}:{dataset_id}:{resource_id}:{version_id}
```

Same parameters = same job_id = idempotent operation

## 🎨 Hello World Output

When a job processes, you'll see beautiful console output:
```
============================================================
🚀 GEOSPATIAL ETL PIPELINE - HELLO WORLD
============================================================
📋 Job ID: abc123def456...
📊 Dataset: rwanda_land_cover_study
📁 Resource: landcover2023.tif
🔢 Version: 1
⚙️  Operation: cog_conversion
------------------------------------------------------------
🎯 Processing Status: HELLO WORLD COMPLETE!
✅ All parameters received and validated
🎉 Ready for real geospatial processing
============================================================
```

## 🧪 Testing Idempotency

Run the test script to verify:
- Same job parameters produce same job_id
- Duplicate submissions return existing job
- Job status tracking works
- Parameter validation works

## 🔄 Next Steps

Once this MVP is deployed and working:

1. ✅ **Verify job tracking in Azure Storage Explorer**
2. ✅ **Confirm idempotency works in the cloud**  
3. ✅ **Check logs and queue processing**
4. 🔄 **Add real geospatial processing services**
5. 🔄 **Add STAC metadata generation**
6. 🔄 **Implement vector batching**
7. 🔄 **Add Container Apps migration**

## 🚨 Key Design Decisions

- **Table Storage only**: No databases yet (one complexity at a time)
- **Minimal dependencies**: Only Azure SDK packages
- **ABC architecture**: Production-ready patterns from day one  
- **Synchronous processing**: Azure Functions handles concurrency
- **Incremental approach**: Add one feature at a time to identify breaking changes

## 🎉 Success Criteria

- [ ] Deploys successfully to Azure Functions
- [ ] Job submission returns job_id
- [ ] Job status can be queried
- [ ] Queue processing shows hello world output
- [ ] Same parameters produce same job_id (idempotency)
- [ ] Jobs table visible in Azure Storage Explorer

Ready to tame the serverless primadonna! 🚀