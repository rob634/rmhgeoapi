# Application Insights Log Access - Definitive Guide

**Date**: 12 DEC 2025
**Purpose**: THE ONE CORRECT PATTERN for querying Azure Application Insights logs

---

## 🎯 TL;DR - Copy This Exact Pattern

### Application Insights App IDs (VERIFIED 12 DEC 2025)

| Function App | App ID | Purpose |
|--------------|--------|---------|
| **rmhazuregeoapi** | `d3af3d37-cfe3-411f-adef-bc540181cbca` | Main API (HTTP triggers, jobs) |
| **rmhgeoapi-worker** | `60530c92-dc55-4d1f-a528-4d523fd5a135` | Worker (Service Bus processing) |

**Resource Group**: `rmhazure_rg`

### The One Correct Pattern

```bash
# Step 1: Login (if not already logged in)
az login

# Step 2: Create and run query script (using rmhazuregeoapi App ID)
cat > /tmp/query_ai.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/d3af3d37-cfe3-411f-adef-bc540181cbca/query" \
  --data-urlencode "query=traces | where timestamp >= ago(15m) | order by timestamp desc | take 20" \
  -G
EOF
chmod +x /tmp/query_ai.sh && /tmp/query_ai.sh | python3 -m json.tool
```

**For worker logs, replace App ID with**: `60530c92-dc55-4d1f-a528-4d523fd5a135`

**That's it. This pattern works. Use it.**

---

## ❌ What Does NOT Work (Stop Trying These)

### ❌ Standard Azure CLI Command
```bash
# FAILS - AAD auth not supported
az monitor app-insights query --app rmhazuregeoapi --analytics-query "requests | take 10"
```

### ❌ Inline Token + Curl
```bash
# FAILS - Shell evaluation issues
TOKEN=$(az account get-access-token ...) && curl -H "Authorization: Bearer $TOKEN" ...
```

### ❌ Token from File
```bash
# FAILS - Token not properly passed
az account get-access-token ... > /tmp/token.txt
curl -H "Authorization: Bearer $(cat /tmp/token.txt)" ...
```

### ❌ Manual URL Encoding
```bash
# FAILS - Encoding errors, hard to debug
curl 'https://...?query=requests%20%7C%20where%20...'
```

---

## ✅ Why The Script Pattern Works

1. **Script file isolates token acquisition** - Variable scoped correctly within script
2. **`--data-urlencode`** - Handles URL encoding automatically (no manual encoding!)
3. **`-G` flag** - Sends as GET request with encoded parameters
4. **Token regenerates each run** - No stale token issues

---

## 📋 Common Queries (Replace in Script)

### Recent Errors
```kql
traces | where timestamp >= ago(1h) | where severityLevel >= 3 | order by timestamp desc | take 20
```

### Task Processing
```kql
traces | where timestamp >= ago(15m) | where message contains "Processing task" or message contains "task_id" | order by timestamp desc | take 20
```

### Specific Job/Task
```kql
traces | where timestamp >= ago(30m) | where message contains "YOUR_JOB_ID_HERE" | order by timestamp desc
```

### Service Bus Operations
```kql
traces | where timestamp >= ago(15m) | where message contains "Service Bus" or message contains "queue" | order by timestamp desc | take 20
```

### Health Endpoint
```kql
union requests, traces | where timestamp >= ago(30m) | where operation_Name contains "health" | take 20
```

### Function Execution Status
```kql
requests | where timestamp >= ago(30m) | where name contains "process_" | project timestamp, name, success, resultCode, duration | order by timestamp desc
```

### Service Latency Metrics (10 JAN 2026)

When `METRICS_DEBUG_MODE=true`, service layer operations log latency with `[SERVICE_LATENCY]` and `[DB_LATENCY]` prefixes.

```kql
// Find slow service operations (> 1s)
traces
| where timestamp >= ago(1h)
| where message contains "[SERVICE_LATENCY]"
| extend duration_ms = todouble(customDimensions.duration_ms)
| where duration_ms > 1000
| project timestamp, customDimensions.operation, duration_ms, customDimensions.status
| order by duration_ms desc

// P90 latency by operation
traces
| where timestamp >= ago(1h)
| where message contains "[SERVICE_LATENCY]"
| extend op = tostring(customDimensions.operation)
| extend duration_ms = todouble(customDimensions.duration_ms)
| summarize p50=percentile(duration_ms, 50), p90=percentile(duration_ms, 90), p99=percentile(duration_ms, 99), count=count() by op
| order by p90 desc

// Database operation latency
traces
| where timestamp >= ago(1h)
| where message contains "[DB_LATENCY]"
| extend op = tostring(customDimensions.operation)
| extend duration_ms = todouble(customDimensions.duration_ms)
| summarize avg_ms=avg(duration_ms), max_ms=max(duration_ms), count=count() by op
| order by avg_ms desc

// Slow operations with error details
traces
| where timestamp >= ago(1h)
| where message contains "SLOW"
| extend op = tostring(customDimensions.operation)
| extend duration_ms = todouble(customDimensions.duration_ms)
| extend error = tostring(customDimensions.error)
| project timestamp, op, duration_ms, error
| order by timestamp desc
```

---

## 🔧 Pretty Output with Python Parsing

```bash
cat > /tmp/query_ai.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/d3af3d37-cfe3-411f-adef-bc540181cbca/query" \
  --data-urlencode "query=traces | where timestamp >= ago(15m) | order by timestamp desc | take 10" \
  -G
EOF
chmod +x /tmp/query_ai.sh && /tmp/query_ai.sh | python3 -c "
import sys, json
data = json.load(sys.stdin)
if 'tables' in data and data['tables'][0]['rows']:
    cols = [c['name'] for c in data['tables'][0]['columns']]
    print(f'Columns: {cols}')
    for row in data['tables'][0]['rows']:
        ts = row[0].split('T')[1][:12] if row[0] else 'N/A'
        msg = str(row[1])[:100] if len(row) > 1 else ''
        print(f'{ts} | {msg}')
else:
    print('No results found')
"
```

---

## 🚨 Known Bug: DEBUG Log Severity Mapping

Azure Functions Python SDK **incorrectly maps `logging.DEBUG` to severity 1 (INFO)** instead of 0 (DEBUG).

### ❌ WRONG - Don't search by severity
```kql
traces | where severityLevel == 0  # Returns ZERO DEBUG logs!
```

### ✅ CORRECT - Search by message content
```kql
traces | where message contains '"level": "DEBUG"' | order by timestamp desc
```

**Requires**: `DEBUG_LOGGING=true` environment variable set in Azure Functions.

---

## 🔑 Key Identifiers Reference

| Component | Value |
|-----------|-------|
| **rmhazuregeoapi App ID** | `d3af3d37-cfe3-411f-adef-bc540181cbca` |
| **rmhgeoapi-worker App ID** | `60530c92-dc55-4d1f-a528-4d523fd5a135` |
| **Resource Group** | `rmhazure_rg` |
| **API Endpoint** | `https://api.applicationinsights.io/v1/apps/{APP_ID}/query` |

---

## ⚠️ Troubleshooting

### "AuthorizationRequiredError"
- Run `az login` first (opens browser)
- Token expired - script auto-regenerates, just run again

### No Results
- Check time range (`ago(15m)` vs `ago(1h)`)
- Check query syntax (use KQL, not SQL)
- Verify function app is generating logs

### Token Issues
- Tokens expire after 1 hour
- Script pattern regenerates token each run (no manual refresh needed)

---

## 📚 Why Other Approaches Fail

The AAD authentication requirement (`APPLICATIONINSIGHTS_AUTHENTICATION_STRING = Authorization=AAD`) breaks standard Azure CLI commands. The REST API with bearer token bypasses this limitation.

Shell evaluation issues cause inline commands to fail - the script file pattern isolates the token acquisition and curl execution properly.

---

## 📖 KQL Query Language Reference

**Official Docs**: https://docs.microsoft.com/en-us/azure/data-explorer/kusto/query/

### Application Insights Tables

| Table | Contains |
|-------|----------|
| `traces` | Custom logs (logger.info, logger.error, etc.) |
| `requests` | HTTP requests to your function app |
| `exceptions` | Unhandled exceptions with stack traces |
| `dependencies` | Outbound calls (DB, HTTP, Service Bus, etc.) |
| `customEvents` | Custom telemetry events |

### KQL Syntax Quick Reference

```kql
// Time filters
| where timestamp >= ago(15m)      // Last 15 minutes
| where timestamp >= ago(1h)       // Last hour
| where timestamp >= ago(24h)      // Last 24 hours

// Text filters
| where message contains "error"           // Case-insensitive contains
| where message has "error"                // Word boundary match
| where message startswith "Starting"      // Starts with
| where message matches regex "task_[0-9]+" // Regex match

// Severity filters (0=Verbose, 1=INFO, 2=WARN, 3=ERROR, 4=CRITICAL)
| where severityLevel >= 3                 // Errors and above

// Combine tables
union traces, requests, exceptions

// Select specific columns
| project timestamp, message, severityLevel, operation_Name

// Order and limit
| order by timestamp desc
| take 20

// Aggregations
| summarize count() by bin(timestamp, 5m)  // Count per 5-min bucket
| summarize count() by severityLevel       // Count by severity
```

### Common Patterns

```kql
// All errors in last hour
traces | where timestamp >= ago(1h) | where severityLevel >= 3 | order by timestamp desc

// HTTP requests with failures
requests | where timestamp >= ago(1h) | where success == false | project timestamp, name, resultCode, duration

// Exceptions with stack traces
exceptions | where timestamp >= ago(1h) | project timestamp, type, outerMessage, details

// Dependency calls (DB, HTTP, etc.)
dependencies | where timestamp >= ago(1h) | project timestamp, name, type, success, duration
```

---

**Last Updated**: 10 JAN 2026
**Status**: PRODUCTION VERIFIED