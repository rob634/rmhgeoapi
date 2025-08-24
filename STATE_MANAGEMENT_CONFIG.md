# State Management Configuration Reference

## Overview
This document shows where the state management system's storage resources are configured and how they're used.

## Storage Resources Used

### 1. **Jobs Table** (Azure Table Storage)
- **Table Name**: `jobs`
- **Connection**: Uses `AzureWebJobsStorage` connection
- **Configuration Location**: 
  - Defined in: `config.py` line 240: `JOB_TRACKING_TABLE = "jobs"`
  - Created in: `state_manager.py` line 48: `self.table_service.create_table_if_not_exists("jobs")`
  - Also used by: `repositories.py` (JobRepository class)

### 2. **Tasks Table** (Azure Table Storage)
- **Table Name**: `tasks`
- **Connection**: Uses `AzureWebJobsStorage` connection
- **Configuration Location**:
  - Created in: `state_manager.py` line 52: `self.table_service.create_table_if_not_exists("tasks")`
  - Also used by: `repositories.py` (TaskRepository class, line 751)

### 3. **Metadata Blob Container** (Azure Blob Storage)
- **Container Name**: `geospatial-table-blobs`
- **Purpose**: Stores large metadata that exceeds Table Storage's 64KB limit
- **Configuration Location**:
  - Hardcoded in: `state_manager.py` line 39: `self.metadata_container = "geospatial-table-blobs"`
  - Created automatically on first use

## Environment Variables (Azure Function App Settings)

### Currently Configured in Azure:
```
BRONZE_CONTAINER_NAME = rmhazuregeobronze
SILVER_CONTAINER_NAME = rmhazuregeosilver  
GOLD_CONTAINER_NAME = rmhazuregeogold
STORAGE_ACCOUNT_NAME = rmhazuregeo

# Managed Identity Connection (automatic)
AzureWebJobsStorage__blobServiceUri = https://rmhazuregeo.blob.core.windows.net
AzureWebJobsStorage__queueServiceUri = https://rmhazuregeo.queue.core.windows.net
AzureWebJobsStorage__tableServiceUri = https://rmhazuregeo.table.core.windows.net
AzureWebJobsStorage__credential = managedidentity
```

### Storage Folder Configuration (within Silver container):
```python
# From config.py lines 59-62:
SILVER_TEMP_FOLDER = os.environ.get('SILVER_TEMP_FOLDER', 'temp')      # Default: temp/
SILVER_COGS_FOLDER = os.environ.get('SILVER_COGS_FOLDER', 'cogs')      # Default: cogs/
SILVER_CHUNKS_FOLDER = os.environ.get('SILVER_CHUNKS_FOLDER', 'chunks') # Default: chunks/
```

## How State Management Connects

### 1. Table Storage Connection (for jobs and tasks tables):
```python
# state_manager.py lines 29-31:
self.table_service = TableServiceClient.from_connection_string(
    Config.AZURE_WEBJOBS_STORAGE
)
```

### 2. Blob Storage Connection (for metadata blobs):
```python
# state_manager.py lines 34-36:
self.blob_service = BlobServiceClient.from_connection_string(
    Config.AZURE_WEBJOBS_STORAGE
)
```

### 3. Queue Connections:
- **Jobs Queue**: `geospatial-jobs` (defined in config.py line 239)
- **Tasks Queue**: `geospatial-tasks` (hardcoded in various places)

## Storage Structure

### Table Storage Structure:
```
jobs table:
  PartitionKey: "job"
  RowKey: {job_id}
  Fields: status, operation_type, input_paths, output_path, etc.

tasks table:
  PartitionKey: {job_id}
  RowKey: {task_id}
  Fields: status, task_type, sequence_number, input_path, output_path, etc.
```

### Blob Storage Structure:
```
geospatial-table-blobs/
  metadata/
    {job_id}/
      validation_results_{timestamp}.json
      task_metadata_{task_id}.json
      processing_logs_{timestamp}.json
```

### Silver Container Structure (for processing):
```
rmhazuregeosilver/
  temp/           # Temporary processing files
    {job_id}/
      output_cog.tif
  chunks/         # Chunked processing data
    {job_id}/
      chunk_001.npy
  cogs/           # Final COG outputs
    final_output_cog.tif
```

## Verification Commands

### Check if tables exist:
```bash
az storage table list --account-name rmhazuregeo --auth-mode login
```

### Check if metadata blob container exists:
```bash
az storage container list --account-name rmhazuregeo --auth-mode login --query "[?name=='geospatial-table-blobs']"
```

### Create metadata blob container if needed:
```bash
az storage container create --name geospatial-table-blobs --account-name rmhazuregeo --auth-mode login
```

## Connection String Format

The system uses managed identity, so the connection is automatic through:
- `AzureWebJobsStorage__credential = managedidentity`
- Service URIs are automatically resolved

For local development, you would need:
```
AzureWebJobsStorage=DefaultEndpointsProtocol=https;AccountName=rmhazuregeo;AccountKey=[KEY];EndpointSuffix=core.windows.net
```

## Current Status

✅ **Environment Variables**: All container names are configured in Azure
✅ **Managed Identity**: Properly configured with service URIs
✅ **Tables**: Created automatically on first use
❓ **Metadata Container**: Needs to be created (geospatial-table-blobs)

## Required Action

Create the metadata blob container:
```bash
az storage container create \
  --name geospatial-table-blobs \
  --account-name rmhazuregeo \
  --auth-mode login
```

This container is essential for storing large metadata that exceeds Azure Table Storage's 64KB entity size limit.