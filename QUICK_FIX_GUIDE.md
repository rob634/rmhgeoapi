# Quick Fix Guide - Deployment Issue

**Problem**: `process_large_raster` job not registered in Azure Functions
**Root Cause**: Jobs module failing to import (jobs component missing from health endpoint)
**Impact**: Cannot submit jobs - deployment incomplete

---

## 🔍 What I Found

### Health Endpoint Analysis
```bash
$ curl https://rmhgeoapibeta-.../api/health | python3 -c "..."

Components Present:
  - imports ✅
  - service_bus ✅
  - tables ✅
  - vault ✅
  - database ✅
  - jobs ❌ MISSING!

Jobs Registered: 0
process_large_raster present: False
```

**Critical Finding**: The `jobs` component is completely missing from the health endpoint, which means the `jobs` module is failing to import during Azure Functions startup.

---

## 🛠️ Quick Fixes (In Order of Likelihood)

### Fix #1: Check Kudu Console (MOST LIKELY)

**Why**: Files might not have deployed

**Steps**:
1. Visit: https://rmhgeoapibeta.scm.azurewebsites.net/DebugConsole
2. Navigate to: `/home/site/wwwroot/jobs/`
3. Check if `process_large_raster.py` exists
4. If NOT present → Files didn't deploy (go to Fix #3)
5. If present → Import error (go to Fix #2)

### Fix #2: Test Import Manually in Kudu

**Why**: See exact import error

**Steps**:
1. In Kudu console, click "CMD" tab
2. Navigate: `cd D:\home\site\wwwroot`
3. Run: `python -c "from jobs import ALL_JOBS; print(list(ALL_JOBS.keys()))"`
4. This will show the exact import error

### Fix #3: Force Clean Deployment

**Why**: Deployment cache might be stale

**Steps**:
```bash
# From local machine
cd /Users/robertharrison/python_builds/rmhgeoapi

# Clean local cache
rm -rf .python_packages

# Force redeployment
func azure functionapp publish rmhgeoapibeta --python --build remote --force

# Wait for completion, then verify
curl -s https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health | \
  python3 -c "import sys, json; data = json.load(sys.stdin); print('jobs' in data.get('components', {}))"
# Should print: True
```

### Fix #4: Check Application Insights for Import Error

**Why**: See startup errors

**Steps**:
```bash
# Must be logged in first
az login

# Check for import errors
cat > /tmp/check_startup_errors.sh << 'EOF'
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(30m) | where message contains 'jobs' or message contains 'import' or message contains 'ERROR' | where severityLevel >= 2 | order by timestamp desc | take 30" \
  -G
EOF

chmod +x /tmp/check_startup_errors.sh && /tmp/check_startup_errors.sh | python3 -m json.tool
```

---

## ✅ Verification (After Fix)

```bash
# 1. Check jobs component exists
curl -s https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health | \
  python3 -c "import sys, json; data = json.load(sys.stdin); jobs = data.get('components', {}).get('jobs', {}); print('Jobs component:', 'PRESENT' if jobs else 'MISSING'); available = jobs.get('details', {}).get('available_jobs', []); print(f'Jobs registered: {len(available)}'); print('process_large_raster:', 'process_large_raster' in available)"

# Expected output:
# Jobs component: PRESENT
# Jobs registered: 13
# process_large_raster: True

# 2. Try submitting job
curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_large_raster" \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "antigua.tif", "tile_size": 5000, "overlap": 512}' | python3 -m json.tool

# Expected: Returns job_id (NOT "Invalid job type" error)
```

---

## 📋 Summary for Robert

**Current Status**:
- ✅ Code is perfect (local test 100% success)
- ✅ Deployment size is tiny (3.9 MB)
- ❌ Jobs module not importing in Azure (component missing)

**Most Likely Cause**:
Files didn't deploy OR there's an import error we can't see

**Quickest Fix**:
1. Check Kudu console for files
2. Try manual import in Kudu console
3. Force clean redeployment

**Once Fixed**:
Submit job and it should work immediately (code is already tested and working locally!)

---

**Next Step**: Start with Fix #1 (Kudu console) - takes 2 minutes to check
