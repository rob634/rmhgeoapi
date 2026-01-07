# Azure Functions Scaling & Resource Management

**Last Updated**: 06 JAN 2026
**Data Source**: FATHOM spatial merge job (RWA region)

---

## Executive Summary

Azure Functions running memory-intensive GDAL/rasterio workloads require careful tuning. Our spatial merge tasks (merging 8-band COGs across tiles) can consume **4-6 GB RAM per task** and saturate CPU at **95-100%**. With default concurrency settings, the platform becomes severely oversubscribed.

---

## Hardware Environment

| Setting | Value |
|---------|-------|
| SKU | PremiumV3 (P1V3) |
| vCPUs per instance | 2 |
| RAM per instance | 7.7 GB |
| Instance count | 4 (configurable 1-10) |
| Total vCPUs | 8 |
| Total RAM | 30.8 GB |

---

## Concurrency Configuration

### host.json Settings

```json
{
  "extensions": {
    "serviceBus": {
      "prefetchCount": 4,
      "messageHandlerOptions": {
        "maxConcurrentCalls": 4,
        "maxAutoLockRenewalDuration": "00:30:00"
      }
    }
  },
  "functionTimeout": "00:30:00"
}
```

### App Settings

| Setting | Value | Purpose |
|---------|-------|---------|
| `FUNCTIONS_WORKER_PROCESS_COUNT` | 2 | Python processes per instance |
| `FUNCTIONS_WORKER_RUNTIME` | python | Runtime type |

### Concurrency Math

```
Total concurrent tasks = Instances × Worker Processes × maxConcurrentCalls
                       = 4 × 2 × 4
                       = 32 concurrent tasks possible
```

---

## Service Bus Queue Configuration

| Queue | Lock Duration | Max Delivery Count | Purpose |
|-------|---------------|-------------------|---------|
| `geospatial-jobs` | PT5M (5 min) | 10 | Job orchestration |
| `raster-tasks` | PT5M (5 min) | 10 | GDAL/rasterio operations |
| `vector-tasks` | PT1M (1 min) | 10 | Database operations |

### Lock Duration Explained

When a consumer receives a message:
1. **Message is locked** - other consumers can't see it
2. **Lock expires after duration** - message becomes visible again (retry)
3. **MessageLockLost** error if task completes after lock expired

**Critical**: Set lock duration > expected task duration to prevent duplicate processing.

```bash
# Update lock duration
az servicebus queue update --resource-group rmhazure_rg \
  --namespace-name rmhazure --name raster-tasks --lock-duration PT5M
```

---

## Observed Resource Usage: Spatial Merge Tasks

### Memory Progression by Checkpoint

| Checkpoint | Tiles | Process RSS | System Available | System % | CPU % |
|------------|-------|-------------|------------------|----------|-------|
| START | 24 | 48-185 MB | 6,100-6,400 MB | 19-22% | 0-81% |
| after_download | 24 | 1,750-2,700 MB | 3,200-4,300 MB | 45-59% | 80-98% |
| band_1_complete | 24 | 2,800-6,100 MB | 150-900 MB | 88-98% | 95-100% |

### Peak Memory Observations

| Metric | Value | Notes |
|--------|-------|-------|
| **Peak process RSS** | 6,090 MB | Single spatial merge task |
| **Peak system utilization** | 98.1% | Only 147 MB available |
| **Peak CPU** | 99.9% | Fully saturated |

### Memory vs Tile Count

| Tiles | Peak Process RSS | Notes |
|-------|------------------|-------|
| 3-5 | ~1,200-1,500 MB | Small grids |
| 10 | ~2,000-2,800 MB | Medium grids |
| 24 | ~4,000-6,100 MB | Full grids (worst case) |

---

## Task Execution Times

### Summary Statistics (30 min window)

| Metric | Value |
|--------|-------|
| **Average** | 126 seconds (2.1 min) |
| **Maximum** | 1,070 seconds (17.8 min) |
| **Minimum** | 97 ms |
| **Sample Size** | 209 tasks |

### Duration Distribution

| Duration Range | Implication |
|----------------|-------------|
| < 60 sec | Safe with 1 min lock |
| 60-300 sec | Need 5 min lock |
| > 300 sec | Need lock renewal or longer timeout |

---

## Exception Analysis

### Exception Counts (30 min window)

| Exception Type | Count | Cause |
|----------------|-------|-------|
| `Azure.RequestFailedException` | 12 | Blob lease conflicts (concurrent access) |
| `Azure.Messaging.ServiceBus.ServiceBusException` | 11 | MessageLockLost (task > lock duration) |
| `System.InvalidOperationException` | 6 | Various internal errors |
| `System.Exception` | 2 | Generic failures |

### Root Causes

1. **MessageLockLost**: Tasks taking longer than Service Bus lock duration
2. **LeaseIdMismatchWithLeaseOperation**: Multiple instances accessing same blob
3. **OOM (out of memory)**: PostgreSQL ran out of memory with 32 concurrent connections

---

## The Oversubscription Problem

### Resource Demand vs Supply

| Resource | Available | Demand (32 concurrent) | Ratio |
|----------|-----------|------------------------|-------|
| vCPUs | 8 | 32 (1 per task) | 4x oversubscribed |
| RAM | 31 GB | 64-128 GB | 2-4x oversubscribed |

### What Happens Under Oversubscription

1. **Memory pressure** → System available drops to < 200 MB
2. **CPU contention** → Tasks slow down, exceed lock duration
3. **Lock expiry** → Messages redelivered, duplicate processing
4. **Cascade failures** → Database OOM from too many connections

---

## Recommended Configurations

### For Memory-Intensive Workloads (GDAL/rasterio)

```json
// host.json
{
  "extensions": {
    "serviceBus": {
      "prefetchCount": 1,
      "messageHandlerOptions": {
        "maxConcurrentCalls": 1,  // REDUCED from 4
        "maxAutoLockRenewalDuration": "00:30:00"
      }
    }
  }
}
```

**Result**: 4 instances × 2 workers × 1 call = **8 concurrent tasks** (matches vCPU count)

### For I/O-Bound Workloads (Database, HTTP)

```json
{
  "extensions": {
    "serviceBus": {
      "prefetchCount": 4,
      "messageHandlerOptions": {
        "maxConcurrentCalls": 4
      }
    }
  }
}
```

### Instance Scaling Guidelines

| Workload Type | vCPU:Task Ratio | RAM per Task | Max Concurrent |
|---------------|-----------------|--------------|----------------|
| Spatial merge | 1:1 | 4-6 GB | 1-2 per instance |
| Band stacking | 1:1 | 2-4 GB | 2 per instance |
| Database ops | 1:4 | 100-500 MB | 4-8 per instance |

---

## Monitoring Queries

### Memory Checkpoints (Application Insights)

```kusto
traces
| where timestamp >= ago(30m)
| where message contains 'process_rss_mb'
| order by timestamp desc
| take 50
```

### Task Execution Times

```kusto
requests
| where timestamp >= ago(30m)
| where name contains 'process_raster'
| summarize avg_ms=avg(duration), max_ms=max(duration), count=count() by success
```

### Exception Summary

```kusto
exceptions
| where timestamp >= ago(30m)
| summarize count() by type
| order by count_ desc
```

---

## Key Learnings

1. **GDAL/rasterio operations are not suitable for high concurrency** - Each task needs dedicated CPU and significant RAM

2. **Service Bus lock duration must exceed task duration** - Default 60 sec is too short for spatial operations

3. **Memory grows non-linearly with tile count** - 24 tiles uses 4x more memory than 10 tiles (not 2.4x)

4. **PostgreSQL is also a bottleneck** - Too many concurrent connections can cause DB OOM

5. **"Successful" tasks may show as failed in App Insights** - MessageLockLost causes retry even if work completed

6. **5×5 grid causes OOM at scale (06 JAN 2026)** - With 8 concurrent tasks × 5-6 GB each = 40-48 GB demand vs 31 GB available. Changed to 4×4 grid (max 16 tiles, ~3-4 GB peak)

---

## Configuration Checklist

- [ ] Set `maxConcurrentCalls` appropriate for workload type
- [ ] Set Service Bus lock duration > max expected task time
- [ ] Monitor memory checkpoints during initial runs
- [ ] Watch for MessageLockLost exceptions
- [ ] Consider separate queues for different workload intensities
- [ ] Scale instances based on throughput needs, not raw parallelism

---

## Related Documentation

- [Service Bus Lock Renewal](https://docs.microsoft.com/azure/service-bus-messaging/message-sessions)
- [Azure Functions Scaling](https://docs.microsoft.com/azure/azure-functions/functions-scale)
- [Python Worker Configuration](https://docs.microsoft.com/azure/azure-functions/python-scale-performance-reference)
