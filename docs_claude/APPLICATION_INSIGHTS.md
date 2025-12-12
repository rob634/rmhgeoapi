# Application Insights Log Access - Definitive Guide

**Date**: 12 DEC 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: THE ONE CORRECT PATTERN for querying Azure Application Insights logs

---

## 🎯 TL;DR - Copy This Exact Pattern

**App ID**: `829adb94-5f5c-46ae-9f00-18e731529222`
**Function App**: `rmhazuregeoapi`
**Resource Group**: `rmhazure_rg`

### The One Correct Pattern

```bash
# Step 1: Login (if not already logged in)
az login

# Step 2: Create and run query script
cat > /tmp/query_ai.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(15m) | order by timestamp desc | take 20" \
  -G
EOF
chmod +x /tmp/query_ai.sh && /tmp/query_ai.sh | python3 -m json.tool
```

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

---

## 🔧 Pretty Output with Python Parsing

```bash
cat > /tmp/query_ai.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
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
| **App ID** | `829adb94-5f5c-46ae-9f00-18e731529222` |
| **Function App** | `rmhazuregeoapi` |
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

**Last Updated**: 12 DEC 2025
**Status**: PRODUCTION VERIFIED