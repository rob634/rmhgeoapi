# Application Insights Query Patterns - Complete Reference

**Date**: 3 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Comprehensive guide to querying Azure Application Insights logs with verified working patterns

---

## 🎯 Quick Start

### Prerequisites
```bash
# Must be logged in to Azure CLI first
az login

# Verify login
az account show --query "{subscription:name, user:user.name}" -o table
```

### Basic Query Pattern (Copy-Paste Ready)
```bash
cat > /tmp/query_ai.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(15m) | order by timestamp desc | take 10" \
  -G
EOF
chmod +x /tmp/query_ai.sh && /tmp/query_ai.sh | python3 -m json.tool
```

---

## ✅ What Works - Verified Patterns

### Pattern 1: Script File with Heredoc (RECOMMENDED)

**Why this works:**
- Script file isolates token acquisition from curl execution
- `--data-urlencode` handles URL encoding automatically
- `-G` flag sends as GET request with encoded parameters
- Clean separation of concerns avoids shell evaluation issues

**Basic Usage:**
```bash
cat > /tmp/query_ai.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=YOUR_KQL_QUERY_HERE" \
  -G
EOF
chmod +x /tmp/query_ai.sh && /tmp/query_ai.sh | python3 -m json.tool
```

**With Python Post-Processing:**
```bash
chmod +x /tmp/query_ai.sh && /tmp/query_ai.sh | python3 -c "
import sys, json
data = json.load(sys.stdin)
if 'tables' in data and data['tables'][0]['rows']:
    print('Results:')
    for row in data['tables'][0]['rows']:
        print(f'  {row[0]} | {row[1]} | {row[2] if len(row) > 2 else \"\"}')
else:
    print('No results found')
"
```

**Advanced: Custom Column Extraction:**
```bash
chmod +x /tmp/query_ai.sh && /tmp/query_ai.sh | python3 -c "
import sys, json
data = json.load(sys.stdin)
if 'tables' in data:
    table = data['tables'][0]
    columns = [col['name'] for col in table['columns']]
    print(f'Columns: {columns}')
    print(f'Rows: {len(table[\"rows\"])}')
    for row in table['rows'][:10]:  # First 10 rows
        print(dict(zip(columns, row)))
"
```

---

## ❌ What Doesn't Work - Avoid These Patterns

### ❌ Pattern 1: Inline Token + Curl in Single Command
```bash
# FAILS with: (eval):1: unknown file attribute:
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv) && \
curl -H "Authorization: Bearer $TOKEN" "https://..."
```
**Issue:** Shell evaluation problems with complex token handling

### ❌ Pattern 2: Token from File
```bash
# FAILS with: AuthorizationRequiredError
az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv > /tmp/token.txt
curl -H "Authorization: Bearer $(cat /tmp/token.txt)" "https://..."
```
**Issue:** Token not properly passed to curl, authentication fails

### ❌ Pattern 3: Manual URL Encoding
```bash
# FAILS - Hard to read, maintain, and debug
curl 'https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query?query=requests%20%7C%20where%20timestamp%20%3E%3D%20ago(5m)'
```
**Issue:** Difficult to read/debug, prone to encoding errors

---

## 📚 Common KQL Queries (Copy-Paste Ready)

### Query 1: Recent Activity (All Types)
```kql
union requests, traces
| where timestamp >= ago(30m)
| project timestamp, itemType, message, operation_Name, severityLevel
| order by timestamp desc
| take 10
```

**Usage:**
```bash
cat > /tmp/query_ai.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=union requests, traces | where timestamp >= ago(30m) | project timestamp, itemType, message, operation_Name | order by timestamp desc | take 10" \
  -G
EOF
chmod +x /tmp/query_ai.sh && /tmp/query_ai.sh | python3 -m json.tool
```

### Query 2: Retry-Related Logs
```kql
traces
| where timestamp >= ago(15m)
| where message contains "RETRY" or message contains "retry" or message contains "retry_count"
| project timestamp, message, severityLevel
| order by timestamp desc
```

### Query 3: Error Logs (Severity Level 3+)
```kql
traces
| where timestamp >= ago(1h)
| where severityLevel >= 3
| project timestamp, message, severityLevel, operation_Name
| order by timestamp desc
| limit 20
```

### Query 4: Task Processing Logs
```kql
traces
| where timestamp >= ago(15m)
| where message contains "Processing task" or message contains "Task failed" or message contains "task_id"
| project timestamp, message, severityLevel
| order by timestamp desc
```

### Query 5: Specific Job/Task Tracking
```kql
traces
| where timestamp >= ago(30m)
| where message contains "YOUR_JOB_ID" or message contains "YOUR_TASK_ID"
| project timestamp, message, operation_Name
| order by timestamp desc
```

### Query 6: Health Endpoint Executions
```kql
union requests, traces
| where timestamp >= ago(30m)
| where operation_Name contains "health" or message contains "health"
| project timestamp, itemType, message, operation_Name
| order by timestamp desc
| take 20
```

### Query 7: Function Execution Status
```kql
requests
| where timestamp >= ago(30m)
| where name contains "process_"
| project timestamp, name, success, resultCode, duration
| order by timestamp desc
```

### Query 8: Service Bus Operations
```kql
traces
| where timestamp >= ago(15m)
| where message contains "Service Bus" or message contains "queue" or message contains "message"
| project timestamp, message, severityLevel
| order by timestamp desc
```

---

## 🔧 Advanced Patterns

### Pattern: Filtering by Severity and Operation
```bash
cat > /tmp/query_errors.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(1h) | where severityLevel >= 3 | where operation_Name contains 'process_service_bus_task' | project timestamp, message, severityLevel | order by timestamp desc" \
  -G
EOF
chmod +x /tmp/query_errors.sh && /tmp/query_errors.sh | python3 -c "
import sys, json
data = json.load(sys.stdin)
if 'tables' in data and data['tables'][0]['rows']:
    print('Errors in last hour:')
    for row in data['tables'][0]['rows']:
        ts, msg, severity = row[0], row[1], row[2]
        print(f'{ts} | Severity {severity} | {msg[:100]}...')
else:
    print('No errors found')
"
```

### Pattern: Time-Based Aggregation
```kql
requests
| where timestamp >= ago(1h)
| summarize count() by bin(timestamp, 5m), success
| order by timestamp desc
```

### Pattern: Custom Dimensions Access
```kql
traces
| where timestamp >= ago(15m)
| extend jobId = tostring(customDimensions.job_id)
| where isnotempty(jobId)
| project timestamp, message, jobId
| order by timestamp desc
```

---

## 🎯 Debugging Workflow

### Step 1: Verify Function App is Running
```bash
curl -s https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health | python3 -c "import sys, json; print(json.load(sys.stdin)['status'])"
```

### Step 2: Check Recent Activity
```bash
cat > /tmp/query_ai.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=union requests, traces | where timestamp >= ago(10m) | summarize count() by itemType | order by count_ desc" \
  -G
EOF
chmod +x /tmp/query_ai.sh && /tmp/query_ai.sh | python3 -m json.tool
```

### Step 3: Find Errors
```bash
# Update the query in the script
cat > /tmp/query_ai.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(30m) | where severityLevel >= 3 | project timestamp, message | order by timestamp desc | take 5" \
  -G
EOF
chmod +x /tmp/query_ai.sh && /tmp/query_ai.sh | python3 -m json.tool
```

### Step 4: Drill Down on Specific Operation
```bash
# Replace OPERATION_NAME with your target
cat > /tmp/query_ai.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(15m) | where operation_Name == 'OPERATION_NAME' | project timestamp, message | order by timestamp asc" \
  -G
EOF
chmod +x /tmp/query_ai.sh && /tmp/query_ai.sh | python3 -m json.tool
```

---

## 📝 Key Identifiers

| Component | Value |
|-----------|-------|
| **App ID** | `829adb94-5f5c-46ae-9f00-18e731529222` |
| **Resource Group** | `rmhazure_rg` |
| **Function App** | `rmhgeoapibeta` |
| **Subscription** | `rmhazure` |

---

## 🚨 CRITICAL: Azure Functions Python Logging Severity Mapping Issue

**Date Discovered**: 28 OCT 2025
**Status**: KNOWN AZURE SDK BUG - No Fix Available

### The Problem

Azure Functions Python SDK **incorrectly maps Python logging levels to Application Insights severity levels**. Specifically:

| Python Level | Python Value | Expected AI Severity | Actual AI Severity | Status |
|--------------|--------------|---------------------|-------------------|--------|
| `logging.DEBUG` | 10 | 0 (DEBUG) | **1 (INFO)** | ❌ WRONG |
| `logging.INFO` | 20 | 1 (INFO) | 1 (INFO) | ✅ Correct |
| `logging.WARNING` | 30 | 2 (WARNING) | 2 (WARNING) | ✅ Correct |
| `logging.ERROR` | 40 | 3 (ERROR) | 3 (ERROR) | ✅ Correct |

**Impact**: All `logger.debug()` calls are captured but mis-categorized as severity 1 (INFO) instead of severity 0 (DEBUG).

### Evidence

When querying Application Insights, you'll see messages with `"level": "DEBUG"` in the JSON content, but Application Insights reports them as `severityLevel: 1`:

```json
{
  "timestamp": "2025-10-28T19:21:23.861Z",
  "severityLevel": 1,    // ❌ WRONG - should be 0
  "message": "{\"timestamp\": \"2025-10-28T19:21:23.861396+00:00\", \"level\": \"DEBUG\", \"message\": \"🔍 [CHECKPOINT_BLOB_REPO] Initializing...\"}"
}
```

### Root Cause

The issue occurs when Python loggers propagate to Azure's root logger:
1. `util_logger.py` creates loggers with `logger.propagate = True` (line 422)
2. Logs flow to Azure's Application Insights SDK
3. Azure SDK maps severity based on ordinal values, treating `logging.DEBUG` (10) as INFO instead of DEBUG

### Workaround: Query by Message Content, Not Severity

**❌ DON'T search by severity level:**
```kql
traces
| where timestamp >= ago(15m)
| where severityLevel == 0  // ❌ This returns ZERO DEBUG logs
| order by timestamp desc
```

**✅ DO search by JSON message content:**
```kql
traces
| where timestamp >= ago(15m)
| where message contains '"level": "DEBUG"'  // ✅ This works!
| order by timestamp desc
```

### Verified Working Pattern

```bash
cat > /tmp/query_debug_logs.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(15m) | where message contains '\"level\": \"DEBUG\"' | order by timestamp desc | take 20" \
  -G
EOF
chmod +x /tmp/query_debug_logs.sh && /tmp/query_debug_logs.sh | python3 -c "
import sys, json
data = json.load(sys.stdin)
rows = data.get('tables', [{}])[0].get('rows', [])
print(f'Found {len(rows)} DEBUG logs (all mis-categorized as severity 1)\n')
for row in rows[:10]:
    ts = row[0].split('T')[1][:12]
    msg_json = json.loads(row[1])
    msg = msg_json.get('message', '')[:100]
    print(f'🐛 {ts} | {msg}')
"
```

### Configuration Requirements

For DEBUG logs to be emitted (even if mis-categorized), ensure:

1. **Environment Variable Set** in Azure Functions:
   ```bash
   DEBUG_LOGGING=true
   ```

2. **host.json Configuration**:
   ```json
   {
     "logging": {
       "logLevel": {
         "default": "Debug"  // Can be "Warning" - Python logger controls emission
       }
     }
   }
   ```

The `DEBUG_LOGGING` environment variable is checked by `util_logger.py` (line 326):
```python
default_level = LogLevel.DEBUG if os.getenv('DEBUG_LOGGING', '').lower() == 'true' else LogLevel.INFO
```

### Verification

After setting `DEBUG_LOGGING=true` and restarting the function app, verify DEBUG logs appear:

```bash
# Check if DEBUG_LOGGING is set
az functionapp config appsettings list --name rmhgeoapibeta --resource-group rmhazure_rg --query "[?name=='DEBUG_LOGGING']"

# Search for DEBUG logs by content (not severity)
# Use the pattern above to query for '"level": "DEBUG"' in message content
```

### Why This Matters

DEBUG logs contain critical information like:
- `CHECKPOINT_*` markers for tracking execution flow
- Detailed parameter values for debugging
- Internal state information not exposed at INFO level

Without this workaround, these logs appear "invisible" when searching by severity level, making debugging nearly impossible.

---

## ⚠️ Important Notes

### Token Expiration
- Bearer tokens expire after **1 hour**
- If you get `AuthorizationRequiredError`, regenerate token:
  ```bash
  az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv
  ```

### Authentication Requirements
- **Must run `az login` first** - Standard CLI commands don't work due to AAD auth requirements
- Function App uses `APPLICATIONINSIGHTS_AUTHENTICATION_STRING = Authorization=AAD`
- Bearer token approach uses authenticated user's permissions

### Query Syntax
- Use **KQL (Kusto Query Language)** syntax
- Test complex queries in Azure Portal first
- Use `--data-urlencode` to avoid manual URL encoding

### Performance
- Limit result sets with `take` or `limit` for faster responses
- Use time filters (`where timestamp >= ago(Xm)`) to reduce data scanned
- Aggregate when possible instead of returning raw rows

---

## 🔗 Related Documentation

- **Quick Reference**: See `CLAUDE.md` for concise version
- **Detailed Guide**: See `docs_claude/claude_log_access.md` for authentication details
- **KQL Reference**: https://docs.microsoft.com/en-us/azure/data-explorer/kusto/query/

---

## 🎓 Learning from Failures

### Why Inline Commands Failed
The pattern `TOKEN=$(get-token) && curl -H "Bearer $TOKEN"` fails because:
1. Complex shell evaluation with nested command substitution
2. Token variable not properly passed to curl subprocess
3. Authentication header malformed in some execution contexts

### Why Script Files Work
Script files work because:
1. Token acquisition happens in script's own shell environment
2. Variable properly scoped within script execution
3. Curl inherits correct environment from script
4. Clean separation prevents evaluation issues

### Best Practice
**Always use script files for Application Insights queries** - more reliable, easier to debug, and reusable.

---

**Last Updated**: 28 OCT 2025
**Verified Working**: All patterns tested against `rmhgeoapibeta` Function App
**Critical Update**: Azure Functions Python severity mapping issue documented (28 OCT 2025)
