# Service Bus + Azure Functions Configuration Harmonization

**Date**: 27 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: ✅ PRODUCTION - Configuration Harmonized
**Context**: Critical bug fix for Stage 2 race condition in `process_large_raster` workflow

## 🎯 Purpose

This document explains the **three-layer configuration architecture** required for Azure Service Bus + Azure Functions to work as "one system" without race conditions or retry conflicts.

**Key Insight**: Configuration lives in THREE separate places (Azure resources, host.json, config.py) that MUST be harmonized to prevent race conditions like the Stage 2 premature completion bug.

---

## 📊 Configuration Layer Architecture

### Layer 1: Azure Service Bus (Infrastructure)

**Location**: Azure Portal → Service Bus Namespace → Queues
**Language**: ISO 8601 duration format (PT5M, P7D)
**Set via**: Azure CLI or Azure Portal
**Scope**: Queue-level settings (NOT in code)

```bash
az servicebus queue show \
  --resource-group rmhazure_rg \
  --namespace-name rmhazure \
  --name geospatial-tasks
```

**Current Configuration** (27 OCT 2025):
```json
{
  "lockDuration": "PT5M",           // 5 minutes (max allowed)
  "maxDeliveryCount": 1,            // Disable Service Bus retries
  "defaultMessageTimeToLive": "P7D", // 7 days
  "maxSizeInMegabytes": 1024        // 1 GB
}
```

**Parameters:**

- **lockDuration** (PT5M = 5 minutes)
  - **What**: How long Service Bus locks a message before redelivery
  - **Why 5 minutes**: Maximum allowed on Standard tier
  - **Critical**: Must be ≤ `maxAutoLockRenewalDuration` in host.json

- **maxDeliveryCount** (1)
  - **What**: How many times Service Bus will attempt delivery
  - **Why 1**: Disable Service Bus retries, use ONLY CoreMachine retry logic
  - **Critical**: Prevents double-retry (Service Bus + CoreMachine)

- **defaultMessageTimeToLive** (P7D = 7 days)
  - **What**: How long messages stay in queue before expiring
  - **Why 7 days**: Sufficient for long-running workflows

---

### Layer 2: Azure Functions Runtime (host.json)

**Location**: `/rmhgeoapi/host.json`
**Language**: JSON (HH:MM:SS format)
**Set via**: Deploy with code (`func azure functionapp publish`)
**Scope**: Function App-wide configuration

**Current Configuration** (27 OCT 2025):
```json
{
  "version": "2.0",
  "functionTimeout": "00:30:00",
  "extensions": {
    "serviceBus": {
      "prefetchCount": 0,
      "messageHandlerOptions": {
        "autoComplete": true,
        "maxConcurrentCalls": 4,
        "maxAutoLockRenewalDuration": "00:30:00"
      }
    }
  }
}
```

**Parameters:**

- **functionTimeout** (00:30:00 = 30 minutes)
  - **What**: Maximum time a function can execute
  - **Why 30 minutes**: Premium EP1 plan supports up to 30 minutes
  - **Critical**: Must match `maxAutoLockRenewalDuration` and `config.py` setting

- **prefetchCount** (0)
  - **What**: Number of messages to pre-fetch from queue
  - **Why 0**: Fetch one message at a time (long-running tasks)

- **autoComplete** (true)
  - **What**: Whether Functions runtime automatically completes messages
  - **Why true**: Function completion = message completion (standard pattern)

- **maxConcurrentCalls** (4)
  - **What**: Maximum concurrent function executions
  - **Why 4**: Prevent resource exhaustion from concurrent large raster processing
  - **Note**: Each `extract_tiles` execution uses significant RAM/CPU

- **maxAutoLockRenewalDuration** (00:30:00 = 30 minutes)
  - **What**: How long Azure Functions automatically renews message locks
  - **Why 30 minutes**: Allows long-running tasks without manual renewal
  - **Critical**: Must be ≥ longest expected task duration

---

### Layer 3: Application Configuration (config.py)

**Location**: `/rmhgeoapi/config.py`
**Language**: Python (Pydantic)
**Set via**: Deploy with code or override with environment variables
**Scope**: Application logic configuration

**Current Configuration** (27 OCT 2025):
```python
class AppConfig(BaseModel):
    # Function execution
    function_timeout_minutes: int = 30

    # CoreMachine retry logic
    task_max_retries: int = 3
    task_retry_base_delay: int = 5
    task_retry_max_delay: int = 300
```

**Parameters:**

- **function_timeout_minutes** (30)
  - **What**: Expected function timeout (documentation/validation)
  - **Why 30**: Must match `host.json` functionTimeout
  - **Critical**: Used for validation and error messages

- **task_max_retries** (3)
  - **What**: CoreMachine retry limit (application-level)
  - **Why 3**: Balance between recovery and fast failure
  - **Critical**: ONLY retry mechanism (Service Bus retries disabled)

- **task_retry_base_delay** (5 seconds)
  - **What**: Initial retry delay for exponential backoff
  - **Why 5s**: Quick first retry, then exponential

- **task_retry_max_delay** (300 seconds = 5 minutes)
  - **What**: Maximum delay between retries
  - **Why 5 minutes**: Sufficient for transient failures

---

## 🔗 Configuration Harmonization Requirements

### Critical Relationships:

```
┌─────────────────────────────────────────────────────────────┐
│ Azure Service Bus lockDuration          PT5M (5 minutes)    │
└───────────────────────────┬─────────────────────────────────┘
                            │ must be ≤
┌───────────────────────────▼─────────────────────────────────┐
│ host.json maxAutoLockRenewalDuration  00:30:00 (30 minutes) │
└───────────────────────────┬─────────────────────────────────┘
                            │ should equal
┌───────────────────────────▼─────────────────────────────────┐
│ host.json functionTimeout             00:30:00 (30 minutes) │
└───────────────────────────┬─────────────────────────────────┘
                            │ should equal
┌───────────────────────────▼─────────────────────────────────┐
│ config.py function_timeout_minutes    30 (minutes)          │
└─────────────────────────────────────────────────────────────┘
```

### Retry Logic Separation:

```
┌─────────────────────────────────────────────────────────────┐
│ Azure Service Bus maxDeliveryCount    1                     │
│ (Service Bus retries DISABLED)                              │
└───────────────────────────┬─────────────────────────────────┘
                            │ all retries handled by
┌───────────────────────────▼─────────────────────────────────┐
│ config.py task_max_retries            3                     │
│ (CoreMachine handles ALL retries)                           │
└─────────────────────────────────────────────────────────────┘
```

### Concurrency Management:

```
┌─────────────────────────────────────────────────────────────┐
│ host.json maxConcurrentCalls          4                     │
│ (Limit concurrent long-running tasks)                       │
└───────────────────────────┬─────────────────────────────────┘
                            │ prevents
┌───────────────────────────▼─────────────────────────────────┐
│ Resource Exhaustion                                         │
│ (4 concurrent extract_tiles = manageable)                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚨 What Happens When Not Harmonized

### The Stage 2 Race Condition Bug (Pre-27 OCT 2025)

**Problem Configuration:**
```
Service Bus lockDuration:    PT1M (1 minute)    ❌ TOO SHORT!
host.json maxAutoLockRenewal: (not configured)  ❌ MISSING!
Service Bus maxDeliveryCount: 5                 ❌ ENABLES RETRIES!
```

**Timeline of Failure:**
```
14:01:28  Lock acquired, handler starts (extract_tiles)
14:02:28  Lock expires ❌ (handler still running)
14:02:28  Service Bus redelivers message (automatic retry #1)
14:07:28  Lock expires again ❌ (both handlers still running)
14:07:28  Service Bus redelivers message (automatic retry #2)
14:08:29  First handler completes, marks task done, advances to Stage 3
14:08:30  Stage 3 starts ❌ (tiles not uploaded yet!)
14:13:48  Tiles actually uploaded (5+ minutes AFTER Stage 3 started)
14:13:48  Stage 3 fails: SETUP_FAILED (blobs don't exist)
```

**Root Causes:**
1. **Lock too short** (1 min) for long-running task (15 min)
2. **No auto-renewal** → Service Bus thinks handler crashed
3. **Service Bus retries** (maxDeliveryCount=5) → Multiple concurrent executions
4. **Race condition** → First execution marks complete before tiles uploaded

**Database Evidence:**
- `retry_count: 0` (NOT CoreMachine retry)
- 4 separate correlation IDs (4 separate executions)
- Task marked "completed" before tiles exist

---

## ✅ Fixed Configuration (27 OCT 2025)

### Azure Service Bus Queues:

```bash
# Updated BOTH queues
az servicebus queue update \
  --resource-group rmhazure_rg \
  --namespace-name rmhazure \
  --name geospatial-tasks \
  --lock-duration PT5M \
  --max-delivery-count 1

az servicebus queue update \
  --resource-group rmhazure_rg \
  --namespace-name rmhazure \
  --name geospatial-jobs \
  --lock-duration PT5M \
  --max-delivery-count 1
```

### host.json:

```json
{
  "functionTimeout": "00:30:00",
  "extensions": {
    "serviceBus": {
      "prefetchCount": 0,
      "messageHandlerOptions": {
        "autoComplete": true,
        "maxConcurrentCalls": 4,
        "maxAutoLockRenewalDuration": "00:30:00"
      }
    }
  }
}
```

### config.py:

```python
function_timeout_minutes: int = 30  # Changed from 5
```

---

## 🎯 Expected Behavior After Fix

### Correct Timeline (Post-27 OCT 2025):

```
T+0:00   Lock acquired (5 minutes), handler starts
T+0:45   Lock auto-renewed (Functions runtime handles this)
T+1:30   Lock auto-renewed again
T+2:15   Lock auto-renewed again
...      (continues auto-renewing up to 30 minutes)
T+15:00  Handler completes, ALL tiles uploaded
T+15:00  CoreMachine marks task complete
T+15:01  Stage 3 starts (tiles exist! ✅)
T+15:01  Stage 3 processes successfully
```

**Key Success Indicators:**
- ✅ Only ONE correlation ID per task (no Service Bus redelivery)
- ✅ `retry_count: 0` (no retries needed)
- ✅ Stage transitions only AFTER handler completes
- ✅ No SETUP_FAILED errors

---

## 📋 Configuration Checklist

### Before Every Deployment:

**1. Verify Azure Service Bus Configuration:**
```bash
az servicebus queue show \
  --resource-group rmhazure_rg \
  --namespace-name rmhazure \
  --name geospatial-tasks \
  --query "{lockDuration:lockDuration, maxDeliveryCount:maxDeliveryCount}"

# Expected output:
# {
#   "lockDuration": "PT5M",
#   "maxDeliveryCount": 1
# }
```

**2. Verify host.json Configuration:**
```bash
cat host.json | grep -A 10 "serviceBus"

# Expected:
# "serviceBus": {
#   "prefetchCount": 0,
#   "messageHandlerOptions": {
#     "autoComplete": true,
#     "maxConcurrentCalls": 4,
#     "maxAutoLockRenewalDuration": "00:30:00"
#   }
# }
```

**3. Verify config.py Configuration:**
```bash
grep "function_timeout_minutes" config.py

# Expected:
# function_timeout_minutes: int = 30
```

**4. Verify Harmonization:**
- ✅ Service Bus lockDuration (PT5M) ≤ maxAutoLockRenewalDuration (00:30:00)
- ✅ functionTimeout (00:30:00) = maxAutoLockRenewalDuration (00:30:00)
- ✅ function_timeout_minutes (30) = functionTimeout (00:30:00)
- ✅ maxDeliveryCount (1) disables Service Bus retries
- ✅ task_max_retries (3) enables CoreMachine retries

---

## 🔄 Configuration Update Procedures

### Changing Lock Duration:

```bash
# 1. Update Azure Service Bus queue
az servicebus queue update \
  --resource-group rmhazure_rg \
  --namespace-name rmhazure \
  --name geospatial-tasks \
  --lock-duration PT10M

# 2. Update host.json maxAutoLockRenewalDuration (must be >= lockDuration)
# Edit host.json manually

# 3. Deploy changes
func azure functionapp publish rmhgeoapibeta --python --build remote
```

### Changing Function Timeout:

```bash
# 1. Update host.json functionTimeout
# Edit host.json manually

# 2. Update config.py function_timeout_minutes (must match)
# Edit config.py manually

# 3. Deploy changes
func azure functionapp publish rmhgeoapibeta --python --build remote
```

### Changing Retry Configuration:

```bash
# Service Bus retries (should always be 1)
az servicebus queue update \
  --resource-group rmhazure_rg \
  --namespace-name rmhazure \
  --name geospatial-tasks \
  --max-delivery-count 1

# CoreMachine retries (edit config.py)
# task_max_retries: int = 3
# task_retry_base_delay: int = 5
# task_retry_max_delay: int = 300

# Deploy
func azure functionapp publish rmhgeoapibeta --python --build remote
```

---

## 📚 Related Documentation

- **DEPLOYMENT_GUIDE.md** - General deployment procedures
- **CLAUDE_CONTEXT.md** - Project overview and quick reference
- **ARCHITECTURE_REFERENCE.md** - Deep technical specifications
- **APPLICATION_INSIGHTS_QUERY_PATTERNS.md** - Log analysis and debugging

---

## 🎓 Key Lessons Learned

### "One System" Principle

Azure Service Bus + Azure Functions + CoreMachine work as ONE system only when:
1. **Lock duration** allows handler to complete
2. **Auto-renewal** extends lock as needed
3. **Service Bus retries disabled** (CoreMachine handles ALL retries)
4. **Timeouts harmonized** across all layers
5. **Concurrency limited** to prevent resource exhaustion

### Configuration Is Infrastructure

Configuration isn't just settings - it's **infrastructure code**. Mismatched configuration creates race conditions, duplicate processing, and data corruption.

### Three-Layer Architecture Requires Three-Layer Validation

Always validate:
1. **Azure resources** (Azure CLI queries)
2. **Runtime configuration** (host.json review)
3. **Application configuration** (config.py review)

### Lock Duration vs Function Timeout

- **Lock Duration**: How long Service Bus waits before redelivery
- **Function Timeout**: How long handler can execute
- **Lock Renewal**: Bridge between short locks and long execution

**Rule**: `lockDuration ≤ maxAutoLockRenewalDuration = functionTimeout`

---

**Document Status**: ✅ PRODUCTION
**Last Verified**: 27 OCT 2025
**Next Review**: When changing Service Bus tier or adding new long-running workflows
