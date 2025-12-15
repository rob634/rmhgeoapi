# Azure Autoscale Configuration for rmhazuregeoapi

**Date**: 24 NOV 2025

## Overview

This document describes the autoscale configuration for the `rmhazuregeoapi` Function App, which automatically scales the App Service Plan based on Service Bus queue depth.

## Architecture

```
Service Bus Queue (geospatial-tasks)
         │
         ▼ metrics
Azure Monitor Autoscale
         │
         ▼ scale actions
App Service Plan (ASP-rmhazure)
         │
         ▼ hosts
Function App (rmhazuregeoapi)
```

## Current Configuration

| Setting | Value |
|---------|-------|
| **Autoscale Name** | `rmhazure-autoscale` |
| **Target Resource** | `ASP-rmhazure` (App Service Plan, P2v3 tier) |
| **Min Instances** | 1 |
| **Max Instances** | 4 |
| **Default Instances** | 1 |
| **Status** | Enabled |

## Scaling Rules

### Scale OUT Rule (Add Instances)

| Parameter | Value |
|-----------|-------|
| **Metric Source** | Service Bus namespace `rmhazure` |
| **Metric** | `ActiveMessages` |
| **Queue** | `geospatial-tasks` |
| **Condition** | > 2 messages |
| **Time Window** | 1 minute average |
| **Action** | Add 1 instance |
| **Cooldown** | 3 minutes |

**Trigger**: When more than 2 messages are in the `geospatial-tasks` queue (averaged over 1 minute), add 1 instance to the App Service Plan.

### Scale IN Rule (Remove Instances)

| Parameter | Value |
|-----------|-------|
| **Metric Source** | Service Bus namespace `rmhazure` |
| **Metric** | `ActiveMessages` |
| **Queue** | `geospatial-tasks` |
| **Condition** | < 2 messages |
| **Time Window** | 10 minute average |
| **Action** | Remove 1 instance |
| **Cooldown** | 10 minutes |

**Trigger**: When fewer than 2 messages are in the `geospatial-tasks` queue (averaged over 10 minutes), remove 1 instance from the App Service Plan.

## Design Decisions

### Why Queue Depth (Not CPU/Memory)?

Traditional autoscaling uses CPU or memory metrics, but for queue-based workloads like ours, queue depth is a better indicator:

- **Proactive**: Scale up BEFORE work piles up, not after CPU spikes
- **Work-aware**: Directly measures pending work, not resource consumption
- **Responsive**: Queue depth changes immediately when jobs are submitted

### Why Asymmetric Thresholds?

| Direction | Threshold | Time Window | Cooldown |
|-----------|-----------|-------------|----------|
| Scale OUT | > 2 msgs | 1 min | 3 min |
| Scale IN | < 2 msgs | 10 min | 10 min |

**Scale OUT is aggressive**: We want to quickly add capacity when work is waiting.

**Scale IN is conservative**: We want to avoid "thrashing" (rapid up/down cycling) which:
- Wastes money (instances starting/stopping)
- Causes instability (cold starts, connection pool resets)
- Can miss actual load spikes

### Why Threshold of 2?

- **> 2 for scale out**: 3+ queued items indicates real work backlog
- **< 2 for scale in**: A single item could be a non-parallel test job; we don't want to scale down if there's any meaningful work

### Cooldown Periods

The **cooldown** is a quiet period after scaling during which no additional scaling occurs:

```
Without cooldown (BAD):
12:00:00 - Queue=5 → Scale to 2 instances
12:00:30 - Queue=5 → Scale to 3 instances (too fast!)
12:01:00 - Queue=5 → Scale to 4 instances (still scaling!)
12:01:30 - Instances finally start, queue drops
12:02:00 - Queue=0 → Scale to 3 instances (thrashing!)

With cooldown (GOOD):
12:00:00 - Queue=5 → Scale to 2 instances
12:00:30 - Queue=5 → BLOCKED (3 min cooldown)
12:03:00 - Cooldown ends, queue=1 → No action needed
```

## Cost Considerations

| Instances | P2v3 Cost/Hour | Daily Cost (24h) |
|-----------|----------------|------------------|
| 1 (min) | ~$0.30 | ~$7.20 |
| 2 | ~$0.60 | ~$14.40 |
| 3 | ~$0.90 | ~$21.60 |
| 4 (max) | ~$1.20 | ~$28.80 |

**Worst case exposure**: If all 4 instances run for 24 hours = ~$28.80/day

## CLI Commands Reference

### View Current Configuration

```bash
# Show autoscale settings
az monitor autoscale show \
  --name rmhazure-autoscale \
  --resource-group rmhazure_rg \
  -o json

# Check current instance count
az appservice plan show \
  --name ASP-rmhazure \
  --resource-group rmhazure_rg \
  --query "{currentWorkers:properties.numberOfWorkers, maxWorkers:sku.capacity}"
```

### Enable/Disable Autoscale

```bash
# Disable autoscale (emergency stop)
az monitor autoscale update \
  --name rmhazure-autoscale \
  --resource-group rmhazure_rg \
  --enabled false

# Re-enable autoscale
az monitor autoscale update \
  --name rmhazure-autoscale \
  --resource-group rmhazure_rg \
  --enabled true
```

### Modify Instance Limits

```bash
# Change max instances (e.g., to 6)
az monitor autoscale update \
  --name rmhazure-autoscale \
  --resource-group rmhazure_rg \
  --max-count 6
```

### Delete Autoscale Configuration

```bash
az monitor autoscale delete \
  --name rmhazure-autoscale \
  --resource-group rmhazure_rg
```

### List Scaling Rules

```bash
az monitor autoscale rule list \
  --autoscale-name rmhazure-autoscale \
  --resource-group rmhazure_rg \
  -o table
```

## Testing Autoscale

### Generate Queue Load

```bash
# Submit multiple jobs to create queue items
for i in {1..5}; do
  curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
    -H "Content-Type: application/json" \
    -d "{\"message\": \"scale test $i\"}"
  sleep 1
done
```

### Monitor Queue Depth

```bash
# Check Service Bus queue message count
az servicebus queue show \
  --namespace-name rmhazure \
  --resource-group rmhazure_rg \
  --name geospatial-tasks \
  --query "{activeMessages:countDetails.activeMessageCount, scheduledMessages:countDetails.scheduledMessageCount}"
```

### Monitor Instance Count

```bash
# Watch instance count (run in loop)
watch -n 30 'az appservice plan show --name ASP-rmhazure --resource-group rmhazure_rg --query "sku.capacity" -o tsv'
```

## Recreating This Configuration

If you need to recreate the autoscale configuration from scratch:

```bash
# Step 1: Create base autoscale settings
az monitor autoscale create \
  --resource-group rmhazure_rg \
  --resource /subscriptions/fc7a176b-9a1d-47eb-8a7f-08cc8058fcfa/resourceGroups/rmhazure_rg/providers/Microsoft.Web/serverfarms/ASP-rmhazure \
  --name rmhazure-autoscale \
  --min-count 1 \
  --max-count 4 \
  --count 1

# Step 2: Add scale-out rule (Queue > 2 for 1 min → Add 1 instance)
az monitor autoscale rule create \
  --resource-group rmhazure_rg \
  --autoscale-name rmhazure-autoscale \
  --condition "ActiveMessages > 2 avg 1m where EntityName == geospatial-tasks" \
  --scale out 1 \
  --cooldown 3 \
  --resource /subscriptions/fc7a176b-9a1d-47eb-8a7f-08cc8058fcfa/resourceGroups/rmhazure_rg/providers/Microsoft.ServiceBus/namespaces/rmhazure

# Step 3: Add scale-in rule (Queue < 2 for 10 min → Remove 1 instance)
az monitor autoscale rule create \
  --resource-group rmhazure_rg \
  --autoscale-name rmhazure-autoscale \
  --condition "ActiveMessages < 2 avg 10m where EntityName == geospatial-tasks" \
  --scale in 1 \
  --cooldown 10 \
  --resource /subscriptions/fc7a176b-9a1d-47eb-8a7f-08cc8058fcfa/resourceGroups/rmhazure_rg/providers/Microsoft.ServiceBus/namespaces/rmhazure
```

## Available Service Bus Metrics

These metrics can be used for autoscale rules:

| Metric | Description |
|--------|-------------|
| `ActiveMessages` | Messages ready to be processed |
| `Messages` | Total messages (active + scheduled + dead-lettered) |
| `DeadletteredMessages` | Messages in dead-letter queue |
| `ScheduledMessages` | Messages scheduled for future delivery |
| `IncomingMessages` | Messages received per time period |
| `OutgoingMessages` | Messages delivered per time period |

## Troubleshooting

### Autoscale Not Triggering

1. **Check if enabled**: `az monitor autoscale show --name rmhazure-autoscale --resource-group rmhazure_rg --query "enabled"`

2. **Check queue metrics**: Verify messages are actually in the queue:
   ```bash
   az servicebus queue show --namespace-name rmhazure --resource-group rmhazure_rg --name geospatial-tasks --query "countDetails"
   ```

3. **Check cooldown**: If recently scaled, cooldown may be active (3 min for scale-out, 10 min for scale-in)

4. **Check time window**: Scale-out needs > 2 msgs averaged over 1 min; scale-in needs < 2 msgs averaged over 10 min

### Instances Not Decreasing

Scale-in is intentionally conservative:
- Requires < 2 messages for 10 minutes straight
- Has 10 minute cooldown after each scale-in
- Will not scale below minimum (1 instance)

### Cost Running High

```bash
# Emergency: Disable autoscale
az monitor autoscale update --name rmhazure-autoscale --resource-group rmhazure_rg --enabled false

# Manually scale to 1 instance
az appservice plan update --name ASP-rmhazure --resource-group rmhazure_rg --number-of-workers 1
```

## Related Documentation

- [Azure Autoscale Overview](https://learn.microsoft.com/azure/azure-monitor/autoscale/autoscale-overview)
- [Service Bus Metrics](https://learn.microsoft.com/azure/service-bus-messaging/monitor-service-bus-reference)
- [App Service Plan Scaling](https://learn.microsoft.com/azure/app-service/manage-scale-up)
