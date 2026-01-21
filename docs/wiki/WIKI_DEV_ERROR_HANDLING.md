# Internal Error Handling Architecture

> **Navigation**: [Quick Start](WIKI_QUICK_START.md) | [Platform API](WIKI_PLATFORM_API.md) | [Errors](WIKI_API_ERRORS.md) | [Glossary](WIKI_API_GLOSSARY.md)

**Date**: 29 DEC 2025
**Purpose**: Internal error handling architecture for developers and operators
**Wiki**: Azure DevOps Wiki - Developer reference
**Audience**: Platform developers, DevOps engineers

---

## Exception Hierarchy

### Contract Violations vs Business Errors

The platform distinguishes between two fundamental error categories:

| Category | Base Class | Handling | When |
|----------|------------|----------|------|
| **Contract Violations** | `ContractViolationError(TypeError)` | NEVER catch - bubble up | Programming bugs (wrong types, missing fields) |
| **Business Logic Errors** | `BusinessLogicError(Exception)` | Catch and handle gracefully | Expected runtime failures |

### Exception Classes (`exceptions.py`)

```
ContractViolationError (TypeError) - NEVER CATCH, indicates bugs
├── Wrong types passed to functions
├── Missing required fields
└── Interface contract violations

BusinessLogicError (Exception) - Base for expected runtime failures
├── ServiceBusError        - Queue communication failures
├── DatabaseError          - PostgreSQL operation failures
├── TaskExecutionError     - Task failed during execution
├── ResourceNotFoundError  - Blob/job/queue not found
└── ValidationError        - Business rule validation failed

ConfigurationError (Exception) - Fatal misconfiguration
├── Missing environment variables
├── Invalid connection strings
└── Malformed configuration files
```

### Error Classification for Retry Decisions

```python
# From core/machine.py
RETRYABLE_EXCEPTIONS = (
    IOError, OSError, TimeoutError, ConnectionError,
    ServiceBusError, DatabaseError
)

PERMANENT_EXCEPTIONS = (
    ValueError, TypeError, KeyError, AttributeError,
    ContractViolationError, ResourceNotFoundError
)
```

---

## Error Source Identification

All structured error logs include an `error_source` field for filtering in Application Insights:

| error_source | Layer | Files |
|--------------|-------|-------|
| `orchestration` | Job/Task coordination | `core/machine.py` |
| `state` | State management | `core/state_manager.py` |
| `infrastructure` | External services | `infrastructure/service_bus.py` |

### Filtering by Error Source

```kql
-- Find all orchestration errors
traces | where customDimensions.error_source == "orchestration"

-- Find all infrastructure errors (Service Bus, PostgreSQL)
traces | where customDimensions.error_source == "infrastructure"

-- Find all state management errors
traces | where customDimensions.error_source == "state"

-- Count errors by source
traces
| where severityLevel >= 3
| summarize count() by tostring(customDimensions.error_source)
```

---

## Structured Logging Checkpoints

### Orchestration Checkpoints (`core/machine.py`)

| Checkpoint | Severity | Description |
|------------|----------|-------------|
| `STAGE_ADVANCE_FAILED` | ERROR | Failed to advance to next stage |
| `JOB_FINALIZE_FAILED` | ERROR | finalize_job() threw exception |
| `JOB_COMPLETE_FAILED` | ERROR | Job completion process failed |
| `RETRY_LOGIC_START` | INFO | Retry logic triggered |
| `RETRY_CONDITION_MET` | INFO | Task eligible for retry |
| `RETRY_SCHEDULED` | INFO | Retry message prepared |
| `RETRY_QUEUED_SUCCESS` | INFO | Retry message sent to queue |
| `RETRY_MAX_EXCEEDED` | ERROR | Max retries reached |
| `JOB_FAILED_MAX_RETRIES` | ERROR | Job failed due to task max retries |

### State Management Checkpoints (`core/state_manager.py`)

| Checkpoint | Severity | Description |
|------------|----------|-------------|
| `STATE_JOB_COMPLETE_FAILED` | ERROR | Failed to mark job complete |
| `STATE_STAGE_COMPLETE_FAILED` | ERROR | Stage completion handling failed |
| `STATE_TASK_COMPLETE_SQL_FAILED` | ERROR | Task completion SQL failed |
| `STATE_MARK_JOB_FAILED_ERROR` | ERROR | Failed to mark job as failed |
| `STATE_MARK_TASK_FAILED_ERROR` | ERROR | Failed to mark task as failed |

### Infrastructure Checkpoints (`infrastructure/service_bus.py`)

| error_category | Retryable | Description |
|----------------|-----------|-------------|
| `auth` | No | Authentication/authorization failed |
| `config` | No | Queue/entity not found |
| `quota` | No | Service Bus quota exceeded |
| `validation` | No | Message size exceeded (256KB) |
| `transient` | Yes | Timeout, server busy, connection error |
| `connection` | Yes | Connection/communication error |
| `service_bus_other` | Yes | Other Service Bus errors |
| `unexpected` | No | Non-Service Bus errors |

---

## Retry Telemetry

### Retry Event Flow

```
Task Fails
    ↓
RETRY_LOGIC_START (retry_event: 'start')
    ↓
[Check retry count < max]
    ↓
RETRY_CONDITION_MET (retry_event: 'condition_met')
    ↓
[Calculate exponential backoff]
    ↓
RETRY_SCHEDULED (retry_event: 'scheduled')
    ↓
[Send to Service Bus with delay]
    ↓
RETRY_QUEUED_SUCCESS (retry_event: 'queued')

--- OR if max exceeded ---

RETRY_MAX_EXCEEDED (retry_event: 'max_exceeded')
    ↓
JOB_FAILED_MAX_RETRIES (retry_event: 'job_failed')
```

### Retry Configuration

| Setting | Default | Environment Variable |
|---------|---------|---------------------|
| Max Retries | 3 | `TASK_MAX_RETRIES` |
| Base Delay | 5s | `TASK_RETRY_BASE_DELAY` |
| Max Delay | 300s | `TASK_RETRY_MAX_DELAY` |

**Exponential Backoff Formula**:
```python
delay = min(base_delay * (2 ** retry_count), max_delay)
# Retry 1: 5s, Retry 2: 10s, Retry 3: 20s (capped at max_delay)
```

### Retry Analysis Queries

```kql
-- Retry frequency by task type
traces
| where customDimensions.retry_event == "scheduled"
| summarize retry_count=count() by tostring(customDimensions.task_type)
| order by retry_count desc

-- Retry success rate
traces
| where customDimensions.retry_event in ("scheduled", "max_exceeded")
| summarize
    scheduled=countif(customDimensions.retry_event == "scheduled"),
    max_exceeded=countif(customDimensions.retry_event == "max_exceeded")
| extend success_rate = 100.0 * (scheduled - max_exceeded) / scheduled

-- Retry timeline for specific job
traces
| where customDimensions.job_id contains "abc123"
| where customDimensions.retry_event != ""
| project timestamp,
    customDimensions.retry_event,
    customDimensions.retry_attempt,
    customDimensions.delay_seconds
| order by timestamp asc

-- Tasks exceeding max retries (need investigation)
traces
| where customDimensions.checkpoint == "RETRY_MAX_EXCEEDED"
| project timestamp,
    customDimensions.task_id,
    customDimensions.task_type,
    customDimensions.error_details
| order by timestamp desc
| take 50
```

---

## Service Bus Error Categories

### Permanent Errors (Never Retry)

| Exception | error_category | Action |
|-----------|----------------|--------|
| `ServiceBusAuthenticationError` | `auth` | Check credentials/identity |
| `ServiceBusAuthorizationError` | `auth` | Check RBAC permissions |
| `MessagingEntityNotFoundError` | `config` | Queue doesn't exist |
| `ServiceBusQuotaExceededError` | `quota` | Upgrade tier or reduce load |
| `MessageSizeExceededError` | `validation` | Reduce message size (<256KB) |

### Transient Errors (Auto-Retry)

| Exception | error_category | Default Retries |
|-----------|----------------|-----------------|
| `OperationTimeoutError` | `transient` | 3 with exponential backoff |
| `ServiceBusServerBusyError` | `transient` | 3 with exponential backoff |
| `ServiceBusConnectionError` | `connection` | 3 with exponential backoff |
| `ServiceBusCommunicationError` | `connection` | 3 with exponential backoff |

---

## Nested Error Handling

When cleanup operations fail after a primary error, both errors are logged with `log_nested_error()`:

```python
except Exception as stage_error:
    try:
        self.state_manager.mark_job_failed(job_id, str(stage_error))
    except Exception as cleanup_error:
        log_nested_error(
            self.logger,
            primary_error=stage_error,
            cleanup_error=cleanup_error,
            operation="stage_advancement",
            job_id=job_id
        )
```

### Finding Nested Errors

```kql
-- All nested errors (cleanup failed after primary error)
traces
| where customDimensions.nested_error == true
| project timestamp,
    customDimensions.operation,
    customDimensions.primary_error_type,
    customDimensions.primary_error,
    customDimensions.cleanup_error_type,
    customDimensions.cleanup_error,
    customDimensions.job_id
| order by timestamp desc
```

---

## Application Insights Dashboard Queries

### Error Overview Dashboard

```kql
// Error count by source (last 24h)
traces
| where timestamp >= ago(24h)
| where severityLevel >= 3
| summarize count() by tostring(customDimensions.error_source)
| render piechart

// Error timeline
traces
| where timestamp >= ago(24h)
| where severityLevel >= 3
| summarize count() by bin(timestamp, 1h), tostring(customDimensions.error_source)
| render timechart

// Top 10 error types
traces
| where timestamp >= ago(24h)
| where severityLevel >= 3
| summarize count() by tostring(customDimensions.error_type)
| top 10 by count_
| render barchart
```

### Job Health Dashboard

```kql
// Failed jobs in last 24h
traces
| where timestamp >= ago(24h)
| where customDimensions.checkpoint in ("JOB_COMPLETE_FAILED", "JOB_FAILED_MAX_RETRIES")
| project timestamp,
    customDimensions.job_id,
    customDimensions.job_type,
    customDimensions.error_message
| order by timestamp desc

// Job completion rate
traces
| where timestamp >= ago(24h)
| where customDimensions.checkpoint in ("JOB_COMPLETE_SUCCESS", "JOB_COMPLETE_FAILED", "JOB_FAILED_MAX_RETRIES")
| summarize
    completed=countif(customDimensions.checkpoint == "JOB_COMPLETE_SUCCESS"),
    failed=countif(customDimensions.checkpoint != "JOB_COMPLETE_SUCCESS")
| extend success_rate = 100.0 * completed / (completed + failed)
```

### Service Bus Health Dashboard

```kql
// Service Bus errors by category
traces
| where timestamp >= ago(24h)
| where customDimensions.error_source == "infrastructure"
| where customDimensions.error_category != ""
| summarize count() by tostring(customDimensions.error_category)
| render piechart

// Queue-specific errors
traces
| where timestamp >= ago(24h)
| where customDimensions.error_source == "infrastructure"
| summarize count() by tostring(customDimensions.queue)
| order by count_ desc
```

---

## Debugging Workflows

### Investigating a Failed Job

1. **Find the job**:
```kql
traces
| where customDimensions.job_id contains "abc123"
| order by timestamp asc
| project timestamp, message, customDimensions
```

2. **Check for retry attempts**:
```kql
traces
| where customDimensions.job_id contains "abc123"
| where customDimensions.retry_event != ""
| order by timestamp asc
```

3. **Find root cause error**:
```kql
traces
| where customDimensions.job_id contains "abc123"
| where severityLevel >= 3
| project timestamp, customDimensions.checkpoint, customDimensions.error_message
| take 10
```

### Investigating Infrastructure Issues

1. **Service Bus connectivity**:
```kql
traces
| where timestamp >= ago(1h)
| where customDimensions.error_category in ("connection", "transient")
| summarize count() by bin(timestamp, 5m)
| render timechart
```

2. **Authentication failures**:
```kql
traces
| where timestamp >= ago(1h)
| where customDimensions.error_category == "auth"
| project timestamp, message, customDimensions.queue
```

---

## Error Handling Files Reference

| File | Purpose |
|------|---------|
| `exceptions.py` | Exception class hierarchy |
| `core/machine.py` | CoreMachine orchestration + retry logic |
| `core/state_manager.py` | Job/task state management |
| `core/error_handler.py` | Centralized error handling utilities |
| `infrastructure/service_bus.py` | Service Bus operations + error handling |
| `infrastructure/postgresql.py` | Database operations + error handling |

---

## Related Documentation

- **API Errors**: [WIKI_API_ERRORS.md](WIKI_API_ERRORS.md) - External API error reference
- **Platform API**: [WIKI_PLATFORM_API.md](WIKI_PLATFORM_API.md) - Full API reference
- **Architecture**: [docs_claude/CLAUDE_CONTEXT.md](docs_claude/CLAUDE_CONTEXT.md) - System architecture
- **Log Access**: [docs_claude/APPLICATION_INSIGHTS.md](docs_claude/APPLICATION_INSIGHTS.md) - Querying logs

---

**Last Updated**: 29 DEC 2025
