# Deployment and Log Access Guide for Future Claudes

**Last Updated**: 11 September 2025  
**Author**: Robert and Geospatial Claude Legion  

## 🚀 Quick Deployment Steps

### 1. Azure Login
```bash
az login
```
Select the correct subscription if multiple exist.

### 2. Deploy Function App
```bash
func azure functionapp publish rmhgeoapibeta --python --build remote
```

**Expected Output**: 
- "Remote build succeeded!"
- Takes ~2-3 minutes

### 3. Redeploy Database Schema (CRITICAL!)
```bash
curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes" -s | python3 -m json.tool
```

**Expected Response**:
```json
{
    "overall_status": "success",
    "message": "Schema redeployed successfully",
    "objects_created": {
        "tables_created": 2,
        "functions_created": 4,
        "enums_processed": 2
    }
}
```

### 4. Verify Deployment
```bash
# Health check
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health -s | python3 -m json.tool
```

## 📊 Log Access (Application Insights)

### Why Special Access Method?
- Function App uses AAD authentication: `APPLICATIONINSIGHTS_AUTHENTICATION_STRING = Authorization=AAD`
- Standard `az monitor` commands fail
- Must use bearer token with REST API

### Quick Log Query Script
```bash
# Get bearer token and query logs
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)

# Recent errors (last 5 minutes)
curl -H "Authorization: Bearer $TOKEN" \
     "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
     --data-urlencode 'query=traces | where timestamp >= ago(5m) | where severityLevel >= 3 | project timestamp, message, severityLevel | order by timestamp desc | limit 20' \
     -G -s | python3 -c "import sys, json; data = json.load(sys.stdin); [print(f\"{row[0]}: [{row[2]}] {row[1][:200]}\") for row in data['tables'][0]['rows'] if data.get('tables')]"
```

### Common Log Queries

#### Task Execution Logs
```bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -H "Authorization: Bearer $TOKEN" \
     "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
     --data-urlencode 'query=traces | where timestamp >= ago(10m) | where message contains "task" or message contains "handler" or message contains "TaskResult" | order by timestamp desc | limit 50' \
     -G -s | python3 -m json.tool
```

#### Queue Processing Status
```bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -H "Authorization: Bearer $TOKEN" \
     "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
     --data-urlencode 'query=requests | where timestamp >= ago(10m) | where name contains "process_job_queue" or name contains "process_task_queue" | project timestamp, name, success, duration | order by timestamp desc' \
     -G -s | python3 -m json.tool
```

## 🧪 Testing Workflow

### 1. Submit Test Job
```bash
curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/hello_world" \
  -H "Content-Type: application/json" \
  -d '{"message": "test message"}' -s | python3 -m json.tool
```

Save the `job_id` from response.

### 2. Check Job Status
```bash
# Replace {JOB_ID} with actual ID
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}" -s | python3 -m json.tool
```

### 3. Check Database State
```bash
# All jobs and tasks
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/debug/all?limit=10" -s | python3 -m json.tool

# Specific job tasks
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks/{JOB_ID}" -s | python3 -m json.tool
```

## 🔍 Troubleshooting

### Problem: Tasks Stuck in "processing"
**Check**: TaskResult validation errors in logs
```bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -H "Authorization: Bearer $TOKEN" \
     "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
     --data-urlencode 'query=traces | where timestamp >= ago(10m) | where message contains "validation error" or message contains "TaskResult" | limit 20' \
     -G -s
```

### Problem: "No handler registered for task_type"
**Fix**: Ensure service modules are imported in function_app.py
- Check `import service_hello_world` exists
- Check `auto_discover_handlers()` is called

### Problem: Token Expired
**Fix**: Re-acquire token (expires after 1 hour)
```bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
```

### Problem: Schema Out of Sync
**Fix**: Always redeploy schema after code deployment
```bash
curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes"
```

## 📝 Key Identifiers

| Component | Value |
|-----------|-------|
| **App Insights ID** | `829adb94-5f5c-46ae-9f00-18e731529222` |
| **Function App** | `rmhgeoapibeta` |
| **Resource Group** | `rmhazure_rg` |
| **Job Queue** | `job-processing` |
| **Task Queue** | `task-processing` |

## ⚠️ Critical Notes

1. **ALWAYS redeploy schema** after function app deployment
2. **Use bearer token** for Application Insights (not `az monitor` CLI)
3. **Check logs immediately** after deployment to catch issues
4. **Job IDs are deterministic** - same parameters = same job ID
5. **Tasks fail silently** if Pydantic validation fails - check logs!

## 📊 Success Indicators

After deployment, you should see:
1. Health endpoint returns `"status": "healthy"`
2. Schema redeploy shows all objects created
3. No validation errors in logs
4. Test job advances through stages
5. Tasks transition from "pending" → "processing" → "completed"

## 🔄 Full Test Cycle

```bash
# 1. Deploy
func azure functionapp publish rmhgeoapibeta --python --build remote

# 2. Redeploy schema
curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes"

# 3. Submit test job
JOB_ID=$(curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/hello_world" \
  -H "Content-Type: application/json" \
  -d '{"message": "test"}' -s | python3 -c "import sys, json; print(json.load(sys.stdin)['job_id'])")

echo "Job ID: $JOB_ID"

# 4. Wait 10 seconds for processing
sleep 10

# 5. Check status
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/$JOB_ID" -s | python3 -m json.tool

# 6. Check logs for errors
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -H "Authorization: Bearer $TOKEN" \
     "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
     --data-urlencode "query=traces | where timestamp >= ago(2m) | where message contains '$JOB_ID' | limit 20" \
     -G -s | python3 -m json.tool
```

## 📚 Reference Documents

- **claude_log_access.md** - Detailed Application Insights access
- **CLAUDE.md** - Project context and architecture
- **TODO.md** - Current issues and tasks
- **ARCHITECTURE_CORE.md** - System design details