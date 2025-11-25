# Azure Service Bus Setup and Configuration Guide

**Date**: 24 NOV 2025
**Status**: Reference Documentation
**Wiki**: Azure DevOps Wiki - Service Bus configuration documentation
**Purpose**: Developer guide for configuring Azure Service Bus in an already-deployed Azure environment
**Audience**: Developers setting up the geospatial ETL pipeline in a new environment

---

## Purpose

This document provides **complete setup instructions** for Azure Service Bus in the rmhgeoapi geospatial data processing application. Use this guide when you have:

- **Azure infrastructure deployed** (Function App, Service Bus namespace, PostgreSQL, Storage)
- **Configuration not yet complete** (need to connect components)
- **Goal**: Get the ETL pipeline processing jobs and tasks

This is a **SERVICE BUS ONLY** application. Azure Storage Queues are **NOT supported** and will raise `NotImplementedError`.

---

## Table of Contents

1. [What Service Bus Does](#what-service-bus-does)
2. [Component Placeholder Details](#component-placeholder-details)
3. [Setup Instructions](#setup-instructions)
4. [Configuration Reference](#configuration-reference)
5. [Verification and Testing](#verification-and-testing)
6. [Troubleshooting](#troubleshooting)
7. [Related Documentation](#related-documentation)

---

## What Service Bus Does

### Role in ETL Architecture

Azure Service Bus is the **message orchestration backbone** of the entire geospatial data processing pipeline. It enables:

1. **Asynchronous job processing** - HTTP requests return immediately, processing happens in background
2. **Stage orchestration** - Sequential stage execution with parallel task processing
3. **High-performance batching** - 40x speedup for bulk operations (1,000 tasks in 2.5 seconds vs 100 seconds)
4. **Reliable retry handling** - Application-level retry logic with exponential backoff
5. **Distributed task execution** - Multiple Azure Functions workers process tasks in parallel

### Message Flow Architecture

```
USER REQUEST
    ↓
┌──────────────────────────────────────────────────────┐
│ 1. HTTP POST /api/jobs/submit/{job_type}            │
│    (triggers/submit_job.py)                          │
│    • Validates parameters                            │
│    • Creates JobQueueMessage                         │
│    • Returns job_id immediately                      │
└─────────────────┬────────────────────────────────────┘
                  ↓
┌──────────────────────────────────────────────────────┐
│ SERVICE BUS QUEUE: geospatial-jobs                   │
│ Message: JobQueueMessage                             │
│   {                                                  │
│     "job_id": "abc123...",                          │
│     "job_type": "hello_world",                      │
│     "stage": 1,                                     │
│     "parameters": {...}                             │
│   }                                                  │
└─────────────────┬────────────────────────────────────┘
                  ↓
┌──────────────────────────────────────────────────────┐
│ 2. Azure Functions Service Bus Trigger              │
│    (function_app.py::process_service_bus_job)       │
│    • Automatically triggered by message arrival     │
│    • Calls CoreMachine.process_job_message()        │
└─────────────────┬────────────────────────────────────┘
                  ↓
┌──────────────────────────────────────────────────────┐
│ 3. CoreMachine Orchestration                        │
│    (core/machine.py)                                 │
│    • Calls job.create_tasks_for_stage()             │
│    • Creates N TaskDefinitions (1 to 10,000+)       │
│    • Chooses batch vs individual queueing           │
│    • Sends TaskQueueMessages to Service Bus         │
└─────────────────┬────────────────────────────────────┘
                  ↓
┌──────────────────────────────────────────────────────┐
│ SERVICE BUS QUEUE: geospatial-tasks                  │
│ Messages: N × TaskQueueMessage                      │
│   {                                                  │
│     "task_id": "abc123-s1-t0",                      │
│     "parent_job_id": "abc123...",                   │
│     "task_type": "say_hello",                       │
│     "parameters": {...}                             │
│   }                                                  │
└─────────────────┬────────────────────────────────────┘
                  ↓
┌──────────────────────────────────────────────────────┐
│ 4. Azure Functions Service Bus Trigger (N parallel) │
│    (function_app.py::process_service_bus_task)      │
│    • N function instances triggered in parallel     │
│    • Each calls CoreMachine.process_task_message()  │
└─────────────────┬────────────────────────────────────┘
                  ↓
┌──────────────────────────────────────────────────────┐
│ 5. Task Execution                                    │
│    (core/machine.py)                                 │
│    • Looks up handler in registry                   │
│    • Executes handler (business logic)              │
│    • Marks task COMPLETED in database               │
│    • Checks if stage complete (advisory lock)       │
│    • Last task advances to next stage OR completes  │
└──────────────────────────────────────────────────────┘
```

### Who Uses Service Bus

**Components that SEND messages:**
- `jobs/hello_world.py` (and all job classes) - Send JobQueueMessage after job creation
- `core/machine.py` - Sends TaskQueueMessages after task generation
- `core/machine.py` - Sends delayed TaskQueueMessages for retries

**Components that RECEIVE messages:**
- `function_app.py::process_service_bus_job()` - Azure Functions trigger for job messages
- `function_app.py::process_service_bus_task()` - Azure Functions trigger for task messages

**Components that DON'T use Service Bus:**
- HTTP triggers (`triggers/*.py`) - Only create database records and send initial job message
- Database repositories (`infrastructure/postgresql.py`) - Direct PostgreSQL operations
- Service handlers (`services/*.py`) - Pure business logic, no queue interaction
- OGC Features API (`ogc_features/`) - Direct PostGIS queries, no queuing
- STAC API (`pgstac/`) - Direct pgstac queries, no queuing

### Integration with Other Components

```
┌─────────────────────────────────────────────────────────────┐
│ CLIENT REQUEST → HTTP Trigger → Database (job record)       │
│                            ↓                                 │
│                   Service Bus (job message)                  │
│                            ↓                                 │
│              CoreMachine (orchestration logic)               │
│                            ↓                                 │
│                   Service Bus (task messages)                │
│                            ↓                                 │
│              Task Handlers (business logic)                  │
│                            ↓                                 │
│              Database (task results, stage completion)       │
│                            ↓                                 │
│              Storage (COGs, tiles, GeoParquet)              │
│                            ↓                                 │
│              PostGIS + pgstac (spatial data, metadata)      │
└─────────────────────────────────────────────────────────────┘
```

**Key Takeaway**: Service Bus is the **glue** between HTTP requests and distributed task execution. It decouples request handling from processing, enabling horizontal scaling and fault tolerance.

---

## Component Placeholder Details

Use this section to populate infrastructure details from your deployed Azure environment.

### 1. Azure Service Bus Namespace

**What it is**: The parent Azure resource containing all queues and topics.

```yaml
# POPULATE FROM YOUR ENVIRONMENT:
Resource Group: _______________________________
Namespace Name: _______________________________
Region: _______________________________
Pricing Tier: _______________________________ (Standard recommended, Premium for VNet)
Fully Qualified Namespace: _______________________________.servicebus.windows.net
```

**How to find**:
```bash
# List all Service Bus namespaces in subscription
az servicebus namespace list --query "[].{name:name, resourceGroup:resourceGroup, location:location, sku:sku.name}" -o table

# Get details for specific namespace
az servicebus namespace show \
  --resource-group <YOUR_RG> \
  --name <YOUR_NAMESPACE> \
  --query "{name:name, fqdn:serviceBusEndpoint, sku:sku.name}" -o json
```

**Connection String (Sensitive - Do NOT commit)**:
```bash
# Get connection string (RootManageSharedAccessKey)
az servicebus namespace authorization-rule keys list \
  --resource-group <YOUR_RG> \
  --namespace-name <YOUR_NAMESPACE> \
  --name RootManageSharedAccessKey \
  --query primaryConnectionString -o tsv
```

**Store in Azure Functions Configuration**:
```bash
# Set as environment variable in Function App
az functionapp config appsettings set \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --settings ServiceBusConnection="<CONNECTION_STRING>"
```

### 2. Service Bus Queues

**What they are**: Message queues for job orchestration and task execution.

#### Queue 1: geospatial-jobs

```yaml
# POPULATE FROM YOUR ENVIRONMENT:
Queue Name: geospatial-jobs
Lock Duration: PT5M (5 minutes - CRITICAL, do not change)
Max Delivery Count: 1 (CRITICAL - disables Service Bus retries)
Default Message TTL: P7D (7 days)
Max Size: 1024 MB (1 GB)
Dead-Letter Queue: Enabled (automatic)
```

**How to verify**:
```bash
az servicebus queue show \
  --resource-group <YOUR_RG> \
  --namespace-name <YOUR_NAMESPACE> \
  --name geospatial-jobs \
  --query "{lockDuration:lockDuration, maxDeliveryCount:maxDeliveryCount, ttl:defaultMessageTimeToLive}" -o json
```

**How to create** (if doesn't exist):
```bash
az servicebus queue create \
  --resource-group <YOUR_RG> \
  --namespace-name <YOUR_NAMESPACE> \
  --name geospatial-jobs \
  --lock-duration PT5M \
  --max-delivery-count 1 \
  --default-message-time-to-live P7D \
  --max-size 1024 \
  --enable-dead-lettering-on-message-expiration true
```

#### Queue 2: geospatial-tasks

```yaml
# POPULATE FROM YOUR ENVIRONMENT:
Queue Name: geospatial-tasks
Lock Duration: PT5M (5 minutes - CRITICAL, do not change)
Max Delivery Count: 1 (CRITICAL - disables Service Bus retries)
Default Message TTL: P7D (7 days)
Max Size: 1024 MB (1 GB)
Dead-Letter Queue: Enabled (automatic)
```

**How to verify**:
```bash
az servicebus queue show \
  --resource-group <YOUR_RG> \
  --namespace-name <YOUR_NAMESPACE> \
  --name geospatial-tasks \
  --query "{lockDuration:lockDuration, maxDeliveryCount:maxDeliveryCount, ttl:defaultMessageTimeToLive}" -o json
```

**How to create** (if doesn't exist):
```bash
az servicebus queue create \
  --resource-group <YOUR_RG> \
  --namespace-name <YOUR_NAMESPACE> \
  --name geospatial-tasks \
  --lock-duration PT5M \
  --max-delivery-count 1 \
  --default-message-time-to-live P7D \
  --max-size 1024 \
  --enable-dead-lettering-on-message-expiration true
```

### 3. Azure Functions App

**What it is**: The compute environment running the ETL pipeline code.

```yaml
# POPULATE FROM YOUR ENVIRONMENT:
Function App Name: _______________________________
Resource Group: _______________________________
Region: _______________________________
Plan Type: _______________________________ (B3 Basic or higher recommended)
Runtime: Python 3.11
Runtime Version: ~4 (Azure Functions v4)
```

**How to find**:
```bash
# List all Function Apps
az functionapp list --query "[].{name:name, resourceGroup:resourceGroup, runtime:runtimeVersion, plan:kind}" -o table

# Get specific Function App details
az functionapp show \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --query "{name:name, runtime:runtimeVersion, location:location, plan:kind}" -o json
```

**Required Environment Variables**:
```bash
# Set Service Bus connection (REQUIRED)
az functionapp config appsettings set \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --settings ServiceBusConnection="<CONNECTION_STRING_FROM_STEP_1>"

# Optional: Override default queue names
az functionapp config appsettings set \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --settings SERVICE_BUS_JOBS_QUEUE="geospatial-jobs" \
           SERVICE_BUS_TASKS_QUEUE="geospatial-tasks"

# Optional: Batch processing tuning
az functionapp config appsettings set \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --settings SERVICE_BUS_MAX_BATCH_SIZE="100" \
           SERVICE_BUS_BATCH_THRESHOLD="50"
```

### 4. PostgreSQL Database

**What it is**: Persistent storage for job/task state and spatial data.

```yaml
# POPULATE FROM YOUR ENVIRONMENT:
Server Name: _______________________________
Resource Group: _______________________________
Admin Username: _______________________________
Database Name: _______________________________ (default: postgres)
Schema: app (jobs and tasks tables)
Connection String: postgresql://<USER>:<PASSWORD>@<SERVER>.postgres.database.azure.com:5432/<DATABASE>?sslmode=require
```

**How to find**:
```bash
# Get PostgreSQL server details
az postgres flexible-server show \
  --resource-group <YOUR_RG> \
  --name <YOUR_PG_SERVER> \
  --query "{name:name, fqdn:fullyQualifiedDomainName, version:version}" -o json
```

**How to configure Function App**:
```bash
# Set database connection string
az functionapp config appsettings set \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --settings DATABASE_CONNECTION_STRING="postgresql://<USER>:<PASSWORD>@<SERVER>.postgres.database.azure.com:5432/<DATABASE>?sslmode=require"
```

### 5. Azure Storage Account

**What it is**: Blob storage for raw data (Bronze), processed data (Silver), and exported data (Gold).

```yaml
# POPULATE FROM YOUR ENVIRONMENT:
Storage Account Name: _______________________________
Resource Group: _______________________________
Containers:
  - Bronze: _______________________________ (raw data uploads)
  - Silver: _______________________________ (COGs, tiles)
  - Gold: _______________________________ (GeoParquet exports - future)
Connection String: DefaultEndpointsProtocol=https;AccountName=<NAME>;AccountKey=<KEY>;EndpointSuffix=core.windows.net
```

**How to find**:
```bash
# Get storage account details
az storage account show \
  --resource-group <YOUR_RG> \
  --name <YOUR_STORAGE_ACCOUNT> \
  --query "{name:name, location:location, kind:kind}" -o json

# List containers
az storage container list \
  --account-name <YOUR_STORAGE_ACCOUNT> \
  --query "[].name" -o table

# Get connection string
az storage account show-connection-string \
  --resource-group <YOUR_RG> \
  --name <YOUR_STORAGE_ACCOUNT> \
  --query connectionString -o tsv
```

**How to configure Function App**:
```bash
# Set storage connection
az functionapp config appsettings set \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --settings AzureWebJobsStorage="<STORAGE_CONNECTION_STRING>"
```

---

## Setup Instructions

Follow these steps to configure Service Bus in an already-deployed Azure environment.

### Prerequisites Checklist

Before starting, verify you have:

- [ ] Azure CLI installed and logged in (`az login`)
- [ ] Access to Azure subscription with deployed resources
- [ ] Resource Group name
- [ ] Service Bus namespace name
- [ ] Function App name
- [ ] PostgreSQL server name
- [ ] Storage account name
- [ ] Admin access to all resources (Contributor role minimum)

### Step 1: Verify Service Bus Infrastructure

**1.1 Confirm Service Bus namespace exists**:
```bash
az servicebus namespace show \
  --resource-group <YOUR_RG> \
  --name <YOUR_NAMESPACE> \
  --query "{name:name, sku:sku.name, location:location}" -o json
```

**Expected output**:
```json
{
  "name": "your-namespace",
  "sku": "Standard",
  "location": "eastus"
}
```

**1.2 Verify both queues exist**:
```bash
# Check geospatial-jobs queue
az servicebus queue show \
  --resource-group <YOUR_RG> \
  --namespace-name <YOUR_NAMESPACE> \
  --name geospatial-jobs \
  --query "{name:name, lockDuration:lockDuration, maxDeliveryCount:maxDeliveryCount}" -o json

# Check geospatial-tasks queue
az servicebus queue show \
  --resource-group <YOUR_RG> \
  --namespace-name <YOUR_NAMESPACE> \
  --name geospatial-tasks \
  --query "{name:name, lockDuration:lockDuration, maxDeliveryCount:maxDeliveryCount}" -o json
```

**Expected output for BOTH queues**:
```json
{
  "name": "geospatial-jobs",
  "lockDuration": "PT5M",
  "maxDeliveryCount": 1
}
```

**🚨 CRITICAL**: If `maxDeliveryCount` is NOT 1, update it:
```bash
az servicebus queue update \
  --resource-group <YOUR_RG> \
  --namespace-name <YOUR_NAMESPACE> \
  --name geospatial-jobs \
  --max-delivery-count 1

az servicebus queue update \
  --resource-group <YOUR_RG> \
  --namespace-name <YOUR_NAMESPACE> \
  --name geospatial-tasks \
  --max-delivery-count 1
```

**Why this matters**: `maxDeliveryCount: 1` disables Service Bus automatic retries. The application handles ALL retries via CoreMachine logic. Multiple delivery attempts cause race conditions and duplicate processing.

### Step 2: Configure Azure Functions Connection

**2.1 Get Service Bus connection string**:
```bash
CONNECTION_STRING=$(az servicebus namespace authorization-rule keys list \
  --resource-group <YOUR_RG> \
  --namespace-name <YOUR_NAMESPACE> \
  --name RootManageSharedAccessKey \
  --query primaryConnectionString -o tsv)

echo $CONNECTION_STRING
```

**2.2 Set as Function App environment variable**:
```bash
az functionapp config appsettings set \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --settings ServiceBusConnection="$CONNECTION_STRING"
```

**2.3 Verify setting was applied**:
```bash
az functionapp config appsettings list \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --query "[?name=='ServiceBusConnection'].{name:name, value:'***REDACTED***'}" -o table
```

**Expected output**:
```
Name                    Value
----------------------  -------------
ServiceBusConnection    ***REDACTED***
```

### Step 3: Configure host.json (Runtime Settings)

**3.1 Verify host.json configuration** in your local codebase:
```bash
cat host.json | grep -A 10 "serviceBus"
```

**Expected output**:
```json
"serviceBus": {
  "prefetchCount": 1,
  "messageHandlerOptions": {
    "autoComplete": true,
    "maxConcurrentCalls": 1,
    "maxAutoLockRenewalDuration": "00:30:00"
  }
}
```

**Critical settings**:
- `prefetchCount: 1` - Fetch one message at a time (prevents overwhelming long-running tasks)
- `autoComplete: true` - Functions runtime completes messages on success
- `maxConcurrentCalls: 1` - Process 1 message at a time (prevents resource exhaustion)
- `maxAutoLockRenewalDuration: "00:30:00"` - Auto-renew locks for 30 minutes (prevents race conditions)

**3.2 If host.json needs updates**, edit and deploy:
```bash
# Edit host.json locally
vim host.json

# Deploy updated configuration
func azure functionapp publish <YOUR_FUNCTION_APP> --python --build remote
```

### Step 4: Configure Application Settings (config.py)

**4.1 Verify application configuration**:
```bash
grep -A 10 "class QueueConfig" config/queue_config.py
```

**Expected defaults**:
```python
jobs_queue: str = "geospatial-jobs"
tasks_queue: str = "geospatial-tasks"
max_batch_size: int = 100
batch_threshold: int = 50
retry_count: int = 3
```

**4.2 Override defaults** (if needed) via environment variables:
```bash
az functionapp config appsettings set \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --settings SERVICE_BUS_JOBS_QUEUE="geospatial-jobs" \
           SERVICE_BUS_TASKS_QUEUE="geospatial-tasks" \
           SERVICE_BUS_MAX_BATCH_SIZE="100" \
           SERVICE_BUS_BATCH_THRESHOLD="50" \
           SERVICE_BUS_RETRY_COUNT="3"
```

### Step 5: Configure IAM Permissions (if using Managed Identity)

**5.1 Enable Managed Identity** on Function App:
```bash
az functionapp identity assign \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP>
```

**5.2 Get Function App principal ID**:
```bash
PRINCIPAL_ID=$(az functionapp identity show \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --query principalId -o tsv)

echo "Principal ID: $PRINCIPAL_ID"
```

**5.3 Assign Service Bus roles**:
```bash
# Get Service Bus resource ID
SERVICEBUS_ID=$(az servicebus namespace show \
  --resource-group <YOUR_RG> \
  --namespace-name <YOUR_NAMESPACE> \
  --query id -o tsv)

# Assign Azure Service Bus Data Owner role
az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Azure Service Bus Data Owner" \
  --scope $SERVICEBUS_ID
```

**5.4 Update Function App** to use managed identity:
```bash
# Remove connection string
az functionapp config appsettings delete \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --setting-names ServiceBusConnection

# Set namespace instead
az functionapp config appsettings set \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --settings ServiceBusConnection__fullyQualifiedNamespace="<YOUR_NAMESPACE>.servicebus.windows.net"
```

### Step 6: Deploy Application Code

**6.1 Deploy Function App**:
```bash
# From repository root
func azure functionapp publish <YOUR_FUNCTION_APP> --python --build remote
```

**6.2 Monitor deployment**:
```bash
# Watch deployment logs
func azure functionapp logstream <YOUR_FUNCTION_APP>
```

**Expected output**:
```
INFO: Successfully deployed Function App
INFO: Service Bus triggers registered
INFO: Function app ready for requests
```

### Step 7: Initialize Database Schema

**7.1 Redeploy database schema** (creates jobs/tasks tables):
```bash
curl -X POST "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/maintenance/redeploy?confirm=yes"
```

**Expected response**:
```json
{
  "status": "success",
  "message": "Schema redeployed successfully",
  "tables_created": ["jobs", "tasks", "job_stages"]
}
```

**7.2 Verify tables exist**:
```bash
curl "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/stats"
```

**Expected response**:
```json
{
  "total_jobs": 0,
  "total_tasks": 0,
  "pending_jobs": 0,
  "processing_jobs": 0
}
```

---

## Configuration Reference

### Three-Layer Configuration Architecture

Service Bus configuration exists in **three separate places** that MUST be harmonized:

```
┌─────────────────────────────────────────────────────────────┐
│ LAYER 1: Azure Service Bus (Infrastructure)                 │
│ Location: Azure Portal / Azure CLI                          │
│ Settings:                                                    │
│   - lockDuration: PT5M (5 minutes)                          │
│   - maxDeliveryCount: 1 (disable Service Bus retries)      │
│   - defaultMessageTimeToLive: P7D (7 days)                  │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ LAYER 2: Azure Functions Runtime (host.json)                │
│ Location: /host.json in codebase                            │
│ Settings:                                                    │
│   - functionTimeout: "00:30:00" (30 minutes)                │
│   - maxAutoLockRenewalDuration: "00:30:00" (30 minutes)     │
│   - autoComplete: true                                       │
│   - maxConcurrentCalls: 1                                    │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ LAYER 3: Application Configuration (config.py)              │
│ Location: /config/queue_config.py                           │
│ Settings:                                                    │
│   - task_max_retries: 3 (CoreMachine retry limit)          │
│   - task_retry_base_delay: 5 (seconds)                      │
│   - task_retry_max_delay: 300 (5 minutes)                   │
│   - batch_threshold: 50 (use batch if >= 50 tasks)         │
└─────────────────────────────────────────────────────────────┘
```

### Critical Harmonization Rules

**Rule 1: Lock Duration ≤ Auto-Renewal Duration**
```
Azure Service Bus lockDuration (PT5M)
  ≤
host.json maxAutoLockRenewalDuration (00:30:00)
```

**Why**: If lock duration exceeds auto-renewal duration, locks expire during execution → Service Bus redelivers message → Race condition.

**Rule 2: Service Bus Retries DISABLED**
```
Azure Service Bus maxDeliveryCount = 1 (DISABLED)
  ↓ all retries handled by
config.py task_max_retries = 3 (ENABLED)
```

**Why**: Service Bus retries happen immediately without backoff → Multiple concurrent executions → Race conditions. CoreMachine handles retries with exponential backoff.

**Rule 3: Function Timeout = Lock Renewal Duration**
```
host.json functionTimeout (00:30:00)
  =
host.json maxAutoLockRenewalDuration (00:30:00)
```

**Why**: Lock renewal can't extend beyond function timeout. Matching values ensures locks stay valid for entire execution.

### Environment Variables Reference

| Variable Name | Type | Required | Default | Description |
|--------------|------|----------|---------|-------------|
| `ServiceBusConnection` | string | Yes* | None | Service Bus connection string (OR use managed identity) |
| `ServiceBusConnection__fullyQualifiedNamespace` | string | Yes* | None | Managed identity auth (alternative to connection string) |
| `SERVICE_BUS_JOBS_QUEUE` | string | No | geospatial-jobs | Job orchestration queue name |
| `SERVICE_BUS_TASKS_QUEUE` | string | No | geospatial-tasks | Task execution queue name |
| `SERVICE_BUS_MAX_BATCH_SIZE` | int | No | 100 | Maximum messages per batch (max 100) |
| `SERVICE_BUS_BATCH_THRESHOLD` | int | No | 50 | Minimum tasks to trigger batch send |
| `SERVICE_BUS_RETRY_COUNT` | int | No | 3 | Service Bus operation retry count |
| `DATABASE_CONNECTION_STRING` | string | Yes | None | PostgreSQL connection string |
| `AzureWebJobsStorage` | string | Yes | None | Storage account for Functions runtime |

\* **Either** `ServiceBusConnection` OR `ServiceBusConnection__fullyQualifiedNamespace` required (not both)

### Queue Configuration Values

#### geospatial-jobs Queue

| Setting | Value | Rationale |
|---------|-------|-----------|
| `lockDuration` | PT5M (5 minutes) | Maximum on Standard tier, sufficient for job message processing |
| `maxDeliveryCount` | 1 | Disable automatic retries (CoreMachine handles retries) |
| `defaultMessageTimeToLive` | P7D (7 days) | Allow long-running workflows, prevent queue bloat |
| `maxSizeInMegabytes` | 1024 (1 GB) | Sufficient for 100,000+ job messages |
| `enableDeadLetteringOnMessageExpiration` | true | Preserve expired messages for debugging |

#### geospatial-tasks Queue

| Setting | Value | Rationale |
|---------|-------|-----------|
| `lockDuration` | PT5M (5 minutes) | Maximum on Standard tier, auto-renewal extends to 30 minutes |
| `maxDeliveryCount` | 1 | Disable automatic retries (CoreMachine handles retries) |
| `defaultMessageTimeToLive` | P7D (7 days) | Long-running tile processing workflows |
| `maxSizeInMegabytes` | 1024 (1 GB) | Handle 10,000+ task messages for large raster jobs |
| `enableDeadLetteringOnMessageExpiration` | true | Preserve failed tasks for analysis |

### host.json Configuration

```json
{
  "version": "2.0",
  "functionTimeout": "00:30:00",
  "extensions": {
    "serviceBus": {
      "prefetchCount": 1,
      "messageHandlerOptions": {
        "autoComplete": true,
        "maxConcurrentCalls": 1,
        "maxAutoLockRenewalDuration": "00:30:00"
      }
    }
  }
}
```

| Setting | Value | Description |
|---------|-------|-------------|
| `prefetchCount` | 1 | Fetch 1 message at a time (long-running tasks) |
| `autoComplete` | true | Functions runtime completes messages on successful execution |
| `maxConcurrentCalls` | 1 | Process 1 message per instance (prevent resource exhaustion) |
| `maxAutoLockRenewalDuration` | 00:30:00 | Auto-renew locks for up to 30 minutes (long-running handlers) |
| `functionTimeout` | 00:30:00 | Maximum function execution time (B3 Basic tier supports 30 min) |

---

## Verification and Testing

Follow these steps to verify Service Bus is configured correctly.

### Step 1: Health Check

**Test Function App is running**:
```bash
curl https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/health
```

**Expected response**:
```json
{
  "status": "healthy",
  "timestamp": "2025-11-24T...",
  "checks": {
    "database": "connected",
    "service_bus": "connected",
    "storage": "connected"
  }
}
```

### Step 2: Queue Statistics

**Check queues are empty** (before first job):
```bash
curl https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/admin/servicebus/stats?queue_name=geospatial-jobs
```

**Expected response**:
```json
{
  "queue_name": "geospatial-jobs",
  "active_message_count": 0,
  "dead_letter_message_count": 0,
  "scheduled_message_count": 0,
  "size_in_bytes": 0
}
```

**Repeat for tasks queue**:
```bash
curl https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/admin/servicebus/stats?queue_name=geospatial-tasks
```

### Step 3: Submit Test Job

**Submit hello_world job**:
```bash
curl -X POST https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Service Bus test",
    "n": 5
  }'
```

**Expected response** (immediate):
```json
{
  "job_id": "abc123...",
  "job_type": "hello_world",
  "status": "PENDING",
  "message": "Job queued successfully",
  "queue_info": {
    "queue": "geospatial-jobs",
    "message_id": "msg_xyz..."
  }
}
```

### Step 4: Monitor Queue Activity

**Check job message was sent**:
```bash
# Wait 5 seconds for message to be processed
sleep 5

# Check queue stats
curl https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/admin/servicebus/stats?queue_name=geospatial-jobs
```

**Expected**: `active_message_count: 0` (message already processed)

**Check tasks were created**:
```bash
curl https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/admin/servicebus/stats?queue_name=geospatial-tasks
```

**Expected**: `active_message_count: 0` or low number (tasks processing)

### Step 5: Verify Job Completion

**Get job status**:
```bash
curl https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/jobs/status/<JOB_ID>
```

**Expected response** (after ~10 seconds):
```json
{
  "job_id": "abc123...",
  "job_type": "hello_world",
  "status": "COMPLETED",
  "stage": 2,
  "created_at": "2025-11-24T...",
  "updated_at": "2025-11-24T...",
  "result_data": {
    "greetings": ["Hello 0!", "Hello 1!", "Hello 2!", "Hello 3!", "Hello 4!"],
    "total_greetings": 5
  }
}
```

### Step 6: Check Dead-Letter Queue

**Verify no failures**:
```bash
curl https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/admin/servicebus/peek-dlq?queue_name=geospatial-jobs&limit=10
```

**Expected response**:
```json
{
  "queue_name": "geospatial-jobs/$DeadLetterQueue",
  "message_count": 0,
  "messages": []
}
```

**Repeat for tasks dead-letter queue**:
```bash
curl https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/admin/servicebus/peek-dlq?queue_name=geospatial-tasks&limit=10
```

### Step 7: Verify Batch Processing

**Submit job with 100+ tasks**:
```bash
curl -X POST https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Batch test",
    "n": 100
  }'
```

**Check Application Insights logs** for batch confirmation:
```kql
traces
| where timestamp >= ago(5m)
| where message contains "Batch send"
| project timestamp, message
```

**Expected log**:
```
Batch send: 100 messages in 2 batches (100 + 0) to geospatial-tasks
```

### Step 8: Full Integration Test

**Run complete raster processing workflow**:
```bash
# 1. Upload test raster to Bronze container
az storage blob upload \
  --account-name <YOUR_STORAGE_ACCOUNT> \
  --container-name bronze \
  --file test_raster.tif \
  --name test_raster.tif

# 2. Submit process_raster job
curl -X POST https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{
    "input_blob_path": "test_raster.tif",
    "target_crs": "EPSG:4326"
  }'

# 3. Monitor job progress
curl https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/jobs/status/<JOB_ID>

# 4. Verify COG created in Silver container
az storage blob list \
  --account-name <YOUR_STORAGE_ACCOUNT> \
  --container-name silver \
  --prefix cogs/
```

---

## Troubleshooting

### Issue 1: Messages Stuck in Queue

**Symptoms**:
- `active_message_count` > 0 and not decreasing
- Jobs stuck in PENDING status
- No task execution logs in Application Insights

**Diagnosis**:
```bash
# Check Function App is running
az functionapp show \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --query "{state:state, outboundIpAddresses:outboundIpAddresses}" -o json

# Check Service Bus triggers are registered
curl https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/health
```

**Solutions**:

1. **Restart Function App**:
```bash
az functionapp restart \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP>
```

2. **Check connection string is set**:
```bash
az functionapp config appsettings list \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --query "[?name=='ServiceBusConnection'].name" -o table
```

3. **Verify triggers deployed**:
```bash
# View deployed functions
az functionapp function list \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --query "[].{name:name, triggerType:config.bindings[0].type}" -o table
```

**Expected output**:
```
Name                          TriggerType
----------------------------  ---------------
process_service_bus_job       serviceBusTrigger
process_service_bus_task      serviceBusTrigger
submit_job                    httpTrigger
```

### Issue 2: Messages Going to Dead-Letter Queue

**Symptoms**:
- `dead_letter_message_count` > 0
- Jobs/tasks stuck in PROCESSING status
- Error logs in Application Insights

**Diagnosis**:
```bash
# Peek dead-letter messages
curl https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/admin/servicebus/peek-dlq?queue_name=geospatial-tasks&limit=5
```

**Common Causes**:

1. **Exception in handler**:
```kql
// Application Insights query
exceptions
| where timestamp >= ago(1h)
| where operation_Name contains "process_service_bus"
| project timestamp, problemId, outerMessage, innermostMessage
```

2. **maxDeliveryCount > 1** (wrong configuration):
```bash
# Check queue config
az servicebus queue show \
  --resource-group <YOUR_RG> \
  --namespace-name <YOUR_NAMESPACE> \
  --name geospatial-tasks \
  --query maxDeliveryCount -o tsv
```

**Expected**: `1`

**Fix if wrong**:
```bash
az servicebus queue update \
  --resource-group <YOUR_RG> \
  --namespace-name <YOUR_NAMESPACE> \
  --name geospatial-tasks \
  --max-delivery-count 1
```

3. **Lock expiration** (wrong host.json):
```bash
cat host.json | grep maxAutoLockRenewalDuration
```

**Expected**: `"maxAutoLockRenewalDuration": "00:30:00"`

**Solutions**:

1. **Fix handler exception** (see exception logs)
2. **Resubmit dead-letter message**:
```bash
# Manually peek, fix issue, resubmit via API
curl -X POST https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/admin/servicebus/resubmit-dlq \
  -H "Content-Type: application/json" \
  -d '{"queue_name": "geospatial-tasks", "message_id": "<MESSAGE_ID>"}'
```

### Issue 3: Duplicate Task Execution

**Symptoms**:
- Same task executed multiple times
- Multiple correlation IDs in logs
- Jobs advance to next stage prematurely

**Diagnosis**:
```kql
// Application Insights query
traces
| where timestamp >= ago(1h)
| where message contains "Processing task"
| where message contains "<TASK_ID>"
| project timestamp, message, operation_Id
```

**If multiple `operation_Id` values → Duplicate execution!**

**Root Cause**: Service Bus retries enabled (`maxDeliveryCount > 1`)

**Fix**:
```bash
# Update BOTH queues
az servicebus queue update \
  --resource-group <YOUR_RG> \
  --namespace-name <YOUR_NAMESPACE> \
  --name geospatial-jobs \
  --max-delivery-count 1

az servicebus queue update \
  --resource-group <YOUR_RG> \
  --namespace-name <YOUR_NAMESPACE> \
  --name geospatial-tasks \
  --max-delivery-count 1
```

**Verify fix**:
```bash
# Clear existing messages (DEV ONLY)
curl -X DELETE "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/admin/servicebus/clear?queue_name=geospatial-tasks&confirm=yes"

# Resubmit job
curl -X POST https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "retry test", "n": 5}'
```

### Issue 4: Batch Send Failing

**Symptoms**:
- Jobs with >= 50 tasks fail to create tasks
- Error: "Batch size exceeds limit"
- `batch_send_messages` errors in logs

**Diagnosis**:
```bash
# Check batch configuration
az functionapp config appsettings list \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --query "[?starts_with(name, 'SERVICE_BUS_')].{name:name, value:value}" -o table
```

**Common Issues**:

1. **Batch size > 100**:
```bash
# Fix: Set to 100 (Service Bus limit)
az functionapp config appsettings set \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --settings SERVICE_BUS_MAX_BATCH_SIZE="100"
```

2. **Message too large**:
```kql
// Check message sizes
traces
| where message contains "Message size"
| project timestamp, message
```

**Max message size**: 256 KB (Standard tier), 1 MB (Premium tier)

**Solution**: Reduce task parameter size or upgrade to Premium tier.

### Issue 5: Connection String Not Working

**Symptoms**:
- Health check fails with "Service Bus unavailable"
- Error: "Connection string invalid"
- Functions fail to start

**Diagnosis**:
```bash
# Test connection string locally
export CONNECTION_STRING="<YOUR_CONNECTION_STRING>"
python3 << EOF
from azure.servicebus import ServiceBusClient
client = ServiceBusClient.from_connection_string("$CONNECTION_STRING")
print("Connection successful!")
EOF
```

**Solutions**:

1. **Regenerate connection string**:
```bash
# Regenerate primary key
az servicebus namespace authorization-rule keys renew \
  --resource-group <YOUR_RG> \
  --namespace-name <YOUR_NAMESPACE> \
  --name RootManageSharedAccessKey \
  --key PrimaryKey

# Get new connection string
NEW_CONNECTION_STRING=$(az servicebus namespace authorization-rule keys list \
  --resource-group <YOUR_RG> \
  --namespace-name <YOUR_NAMESPACE> \
  --name RootManageSharedAccessKey \
  --query primaryConnectionString -o tsv)

# Update Function App
az functionapp config appsettings set \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --settings ServiceBusConnection="$NEW_CONNECTION_STRING"
```

2. **Switch to managed identity** (more secure):
```bash
# Follow Step 5 in Setup Instructions
```

### Issue 6: Lock Expiration During Long Tasks

**Symptoms**:
- Tasks processing for > 5 minutes fail
- Error: "Lock expired"
- Stage advancement happens prematurely

**Diagnosis**:
```kql
traces
| where timestamp >= ago(1h)
| where message contains "Lock expired" or message contains "redelivery"
| project timestamp, message
```

**Root Cause**: `maxAutoLockRenewalDuration` not configured or too short

**Fix**:

1. **Update host.json**:
```json
{
  "extensions": {
    "serviceBus": {
      "messageHandlerOptions": {
        "maxAutoLockRenewalDuration": "00:30:00"
      }
    }
  }
}
```

2. **Deploy changes**:
```bash
func azure functionapp publish <YOUR_FUNCTION_APP> --python --build remote
```

3. **Verify configuration**:
```bash
curl https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/health
```

---

## Related Documentation

### Core Documentation
- **[docs_claude/SERVICE_BUS_HARMONIZATION.md](docs_claude/SERVICE_BUS_HARMONIZATION.md)** - Three-layer configuration architecture (MUST READ)
- **[docs_claude/COREMACHINE_PLATFORM_ARCHITECTURE.md](docs_claude/COREMACHINE_PLATFORM_ARCHITECTURE.md)** - CoreMachine orchestration design
- **[docs_claude/CLAUDE_CONTEXT.md](docs_claude/CLAUDE_CONTEXT.md)** - Primary project context and overview

### Implementation Details
- **[infrastructure/service_bus.py](infrastructure/service_bus.py)** - ServiceBusRepository implementation (841 lines)
- **[core/machine.py](core/machine.py)** - CoreMachine orchestration logic (1,500+ lines)
- **[config/queue_config.py](config/queue_config.py)** - Queue configuration module (137 lines)
- **[host.json](host.json)** - Azure Functions runtime configuration

### Message Schemas
- **[core/schema/queue.py](core/schema/queue.py)** - JobQueueMessage and TaskQueueMessage Pydantic models (204 lines)

### API Reference
- **[docs/completed/architecture/SERVICE_BUS_EXECUTION_TRACE.md](docs/completed/architecture/SERVICE_BUS_EXECUTION_TRACE.md)** - Complete execution flow trace

### Deployment
- **[docs_claude/DEPLOYMENT_GUIDE.md](docs_claude/DEPLOYMENT_GUIDE.md)** - General deployment procedures
- **[CLAUDE.md](CLAUDE.md)** - Quick deployment commands and testing procedures

### Database Configuration
- **API_DATABASE.md** (TO BE CREATED) - PostgreSQL setup and configuration guide

### Storage Configuration
- **API_STORAGE.md** (TO BE CREATED) - Azure Blob Storage setup guide

---

## Key Concepts for New Developers

### 1. Service Bus vs Storage Queues

**This application uses Service Bus EXCLUSIVELY**. Why?

| Feature | Storage Queues | Service Bus |
|---------|---------------|-------------|
| Message size | 64 KB | 256 KB (Standard), 1 MB (Premium) |
| Ordering | Not guaranteed | FIFO with sessions |
| Batch operations | No | Yes (100 messages/batch) |
| Dead-letter queue | Manual | Automatic |
| Lock duration | 7 days max | 5 minutes (Standard tier) |
| Auto-lock renewal | No | Yes (via Azure Functions) |
| Performance | ~500 ops/sec | ~1,000 ops/sec (batched) |

**Result**: Service Bus provides 40 times faster performance for bulk operations and automatic failure handling.

### 2. Why maxDeliveryCount = 1?

**Problem**: Service Bus automatic retries cause race conditions:

```
14:01:28  Lock acquired, handler starts (15-minute task)
14:02:28  Lock expires (1 min duration, no renewal)
14:02:28  Service Bus retries → Second handler starts
14:08:29  First handler completes → Marks task done
14:08:30  Stage advances (tiles not uploaded yet!)
14:13:48  Second handler uploads tiles (5 min AFTER stage advanced)
14:13:48  Next stage fails: tiles don't exist
```

**Solution**: Disable Service Bus retries (`maxDeliveryCount: 1`), handle ALL retries in CoreMachine with exponential backoff.

### 3. Lock Renewal Prevents Race Conditions

**Without auto-renewal**:
- Lock expires after 5 minutes
- Service Bus thinks handler crashed
- Message redelivered → Duplicate execution

**With auto-renewal**:
- Azure Functions automatically renews lock every ~4.5 minutes
- Handler can run up to 30 minutes
- No premature redelivery

**Configuration**:
```json
"maxAutoLockRenewalDuration": "00:30:00"  // In host.json
```

### 4. Batch Processing Performance

**Individual send** (1,000 tasks):
- 1,000 HTTP requests to Service Bus
- Approximately 100ms each = 100 seconds total

**Batch send** (1,000 tasks):
- 10 batches of 100 messages each
- Approximately 250ms per batch = 2.5 seconds total
- **40 times faster**

**Automatic optimization**:
```python
if task_count >= 50:
    batch_send_messages(tasks)  # Fast path
else:
    send_individual_messages(tasks)  # Simple path
```

### 5. Message Correlation for Debugging

Every message gets a `correlation_id` for tracing:

```python
correlation_id = str(uuid.uuid4())[:8]  # for example, "a1b2c3d4"
```

**Application Insights query**:
```kql
traces
| where message contains "[a1b2c3d4]"
| order by timestamp asc
```

**Result**: See entire job execution in one trace.

### 6. Stage Advancement with Advisory Locks

**Problem**: Multiple tasks complete simultaneously, creating a race condition when detecting the last task

**Solution**: PostgreSQL advisory locks in `check_stage_complete()`:

```sql
SELECT pg_try_advisory_lock(hashtext('job_' || $1 || '_stage_' || $2))
-- Returns true ONLY for first caller
```

**Result**: Exactly ONE task advances stage, even with 204 parallel completions.

---

## Quick Start Checklist

For developers setting up a new environment, follow this checklist:

- [ ] **Step 1**: Verify Service Bus namespace exists
- [ ] **Step 2**: Verify both queues exist (geospatial-jobs, geospatial-tasks)
- [ ] **Step 3**: Verify `maxDeliveryCount: 1` on BOTH queues
- [ ] **Step 4**: Get Service Bus connection string
- [ ] **Step 5**: Set `ServiceBusConnection` environment variable in Function App
- [ ] **Step 6**: Verify host.json has correct Service Bus configuration
- [ ] **Step 7**: Deploy Function App code
- [ ] **Step 8**: Initialize database schema (redeploy endpoint)
- [ ] **Step 9**: Run health check
- [ ] **Step 10**: Submit test hello_world job
- [ ] **Step 11**: Verify job completes successfully
- [ ] **Step 12**: Check dead-letter queues are empty

**Estimated setup time**: 30-45 minutes for experienced Azure developer

---

**Last Updated**: 24 NOV 2025
**Next Review**: When adding new job types or changing Service Bus tier
