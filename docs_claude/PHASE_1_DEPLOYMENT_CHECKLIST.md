# Phase 1 Deployment Checklist

**Date**: 03 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Phase**: Database Admin API Implementation
**Status**: Ready for Deployment

---

## ✅ **Pre-Deployment Checklist**

### **Code Quality**
- [x] All Python files syntax valid
- [x] All imports tested (with expected env var requirements)
- [x] Function signatures consistent
- [x] Error handling implemented
- [x] Logging added throughout

### **Documentation**
- [x] PHASE_1_SUMMARY.md created
- [x] PHASE_1_DEPLOYMENT_CHECKLIST.md created (this file)
- [x] ADMIN_API_IMPLEMENTATION_PLAN.md exists
- [x] Inline docstrings complete

### **Files Created** (6 total)
- [x] `triggers/admin/__init__.py`
- [x] `triggers/admin/db_schemas.py`
- [x] `triggers/admin/db_tables.py`
- [x] `triggers/admin/db_queries.py`
- [x] `triggers/admin/db_health.py`
- [x] `triggers/admin/db_maintenance.py`

### **Files Modified** (1 total)
- [x] `function_app.py` (added imports + 16 routes)

---

## 🚀 **Deployment Steps**

### **Step 1: Commit Changes**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi

# Check git status
git status

# Add all new files
git add triggers/admin/
git add docs_claude/PHASE_1_*.md
git add docs_claude/ADMIN_API_IMPLEMENTATION_PLAN.md
git add function_app.py

# Commit with descriptive message
git commit -m "Phase 1: Database Admin API - 16 new endpoints under /api/admin/db/*

✨ New Features:
- Schema inspection (3 endpoints)
- Table operations with geometry support (4 endpoints)
- Query analysis and monitoring (4 endpoints)
- Health and performance metrics (2 endpoints)
- Maintenance operations (3 endpoints)

📁 Files Created:
- triggers/admin/__init__.py
- triggers/admin/db_schemas.py (410 lines)
- triggers/admin/db_tables.py (655 lines)
- triggers/admin/db_queries.py (490 lines)
- triggers/admin/db_health.py (425 lines)
- triggers/admin/db_maintenance.py (365 lines)

📝 Documentation:
- docs_claude/ADMIN_API_IMPLEMENTATION_PLAN.md
- docs_claude/PHASE_1_SUMMARY.md
- docs_claude/PHASE_1_DEPLOYMENT_CHECKLIST.md

🎯 Architecture:
- All endpoints under /api/admin/* for APIM consolidation
- Geometry-aware queries (ST_AsGeoJSON for geo schema)
- Singleton pattern for efficiency
- Comprehensive error handling

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### **Step 2: Push to Git (if desired)**

```bash
# Push to dev branch
git checkout dev
git push origin dev

# OR merge to master (if stable)
git checkout master
git merge dev
git push origin master
```

### **Step 3: Deploy to Azure Functions**

```bash
# Deploy with remote build
func azure functionapp publish rmhgeoapibeta --python --build remote

# Wait for deployment to complete (~2-3 minutes)
```

---

## 🧪 **Post-Deployment Testing**

### **Test 1: Health Check (Baseline)**

```bash
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health
```

**Expected**: HTTP 200, JSON response with system health

---

### **Test 2: Schema Operations**

#### **2.1: List All Schemas**
```bash
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/admin/db/schemas
```

**Expected**:
```json
{
  "schemas": [
    {
      "schema_name": "app",
      "table_count": 2,
      "total_size": "...",
      "data_size": "...",
      "index_size": "..."
    },
    {
      "schema_name": "geo",
      ...
    },
    {
      "schema_name": "pgstac",
      ...
    },
    {
      "schema_name": "public",
      ...
    }
  ],
  "count": 4,
  "timestamp": "2025-11-03T..."
}
```

**Validate**:
- [ ] HTTP 200 status
- [ ] 4 schemas returned (app, geo, pgstac, public)
- [ ] table_count > 0 for app schema
- [ ] Sizes show as human-readable (e.g., "128 KB")

---

#### **2.2: Get App Schema Details**
```bash
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/admin/db/schemas/app
```

**Expected**:
```json
{
  "schema_name": "app",
  "table_count": 2,
  "function_count": 5,
  "total_size": "...",
  "tables": [
    {"table_name": "jobs", "size": "..."},
    {"table_name": "tasks", "size": "..."}
  ],
  "functions": [...],
  "timestamp": "..."
}
```

**Validate**:
- [ ] HTTP 200 status
- [ ] tables array contains "jobs" and "tasks"
- [ ] function_count shows PostgreSQL functions
- [ ] Reasonable sizes

---

#### **2.3: List Tables in Geo Schema**
```bash
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/admin/db/schemas/geo/tables
```

**Expected**:
```json
{
  "schema_name": "geo",
  "tables": [
    {
      "table_name": "...",
      "row_count": ...,
      "total_size": "...",
      "data_size": "...",
      "index_size": "...",
      "last_vacuum": "...",
      "last_analyze": "..."
    }
  ],
  "count": ...,
  "timestamp": "..."
}
```

**Validate**:
- [ ] HTTP 200 status
- [ ] Tables listed (if any exist in geo schema)
- [ ] Row counts accurate
- [ ] Vacuum timestamps present

---

### **Test 3: Table Operations**

#### **3.1: Get app.jobs Table Details**
```bash
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/admin/db/tables/app.jobs
```

**Expected**:
```json
{
  "schema": "app",
  "table": "jobs",
  "row_count": ...,
  "total_size": "...",
  "data_size": "...",
  "index_size": "...",
  "column_count": 12,
  "index_count": 1,
  "columns": [...],
  "indexes": [...],
  "timestamp": "..."
}
```

**Validate**:
- [ ] HTTP 200 status
- [ ] Correct row count
- [ ] columns array has 12+ entries
- [ ] indexes array shows primary key

---

#### **3.2: Sample Rows from app.jobs**
```bash
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/admin/db/tables/app.jobs/sample?limit=5"
```

**Expected**:
```json
{
  "schema": "app",
  "table": "jobs",
  "rows": [
    {
      "job_id": "...",
      "job_type": "...",
      "status": "...",
      ...
    }
  ],
  "count": 5,
  "limit": 5,
  "offset": 0,
  "order_by": "...",
  "geometry_columns": [],
  "timestamp": "..."
}
```

**Validate**:
- [ ] HTTP 200 status
- [ ] Up to 5 rows returned
- [ ] All columns present
- [ ] geometry_columns empty (no geometry in app.jobs)

---

#### **3.3: Get Columns for app.jobs**
```bash
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/admin/db/tables/app.jobs/columns
```

**Expected**:
```json
{
  "schema": "app",
  "table": "jobs",
  "columns": [
    {
      "column_name": "job_id",
      "ordinal_position": 1,
      "data_type": "character varying",
      "is_nullable": false,
      "column_default": null,
      "is_geometry": false
    },
    ...
  ],
  "count": 12,
  "timestamp": "..."
}
```

**Validate**:
- [ ] HTTP 200 status
- [ ] All columns listed
- [ ] Data types accurate
- [ ] is_geometry correctly detected

---

#### **3.4: Test Geometry Handling (If geo schema has data)**
```bash
# First check if geo schema has any tables with data
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/admin/db/schemas/geo/tables

# If a table exists (e.g., "parcels"), sample it
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/admin/db/tables/geo.parcels/sample?limit=3"
```

**Expected** (if geo table exists):
```json
{
  "schema": "geo",
  "table": "parcels",
  "rows": [
    {
      "id": 1,
      "name": "...",
      "geom": {
        "type": "Polygon",
        "coordinates": [[[...]]]
      }
    }
  ],
  "geometry_columns": ["geom"],
  "timestamp": "..."
}
```

**Validate**:
- [ ] HTTP 200 status
- [ ] geometry_columns array lists "geom" (or other geometry column)
- [ ] geom field is valid GeoJSON
- [ ] Other fields present

---

### **Test 4: Query Analysis**

#### **4.1: Running Queries**
```bash
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/admin/db/queries/running
```

**Expected**:
```json
{
  "queries": [
    {
      "pid": ...,
      "user": "rmhgeoapi",
      "application": "...",
      "state": "active",
      "query": "...",
      "duration_seconds": 0.5,
      "wait_event_type": null,
      "wait_event": null
    }
  ],
  "count": ...,
  "timestamp": "..."
}
```

**Validate**:
- [ ] HTTP 200 status
- [ ] Queries array (may be empty)
- [ ] If queries exist, durations reasonable

---

#### **4.2: Slow Queries**
```bash
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/admin/db/queries/slow
```

**Expected** (if pg_stat_statements enabled):
```json
{
  "available": true,
  "queries": [...],
  "count": ...,
  "timestamp": "..."
}
```

**OR** (if not enabled):
```json
{
  "available": false,
  "message": "pg_stat_statements extension not installed",
  "timestamp": "..."
}
```

**Validate**:
- [ ] HTTP 200 status
- [ ] available field present
- [ ] If available=true, queries array present
- [ ] If available=false, helpful message

---

#### **4.3: Database Locks**
```bash
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/admin/db/locks
```

**Expected**:
```json
{
  "locks": [...],
  "blocking_count": 0,
  "total_count": ...,
  "timestamp": "..."
}
```

**Validate**:
- [ ] HTTP 200 status
- [ ] blocking_count = 0 (under normal operation)
- [ ] locks array present (may have entries)

---

#### **4.4: Connections**
```bash
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/admin/db/connections
```

**Expected**:
```json
{
  "total_connections": 15,
  "active_connections": 5,
  "idle_connections": 10,
  "max_connections": 100,
  "utilization_percent": 15.0,
  "connections_by_application": [...],
  "connections_by_state": [...],
  "timestamp": "..."
}
```

**Validate**:
- [ ] HTTP 200 status
- [ ] Utilization < 80% (healthy)
- [ ] Counts add up correctly
- [ ] connections_by_application shows "Azure Functions"

---

### **Test 5: Health & Performance**

#### **5.1: Database Health**
```bash
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/admin/db/health
```

**Expected**:
```json
{
  "status": "healthy",
  "connection_pool": {
    "total": 15,
    "active": 5,
    "idle": 10,
    "max": 100,
    "utilization_percent": 15.0
  },
  "database_size": {
    "total": "...",
    "app_schema": "...",
    "geo_schema": "...",
    "pgstac_schema": "..."
  },
  "vacuum_status": {
    "tables_needing_vacuum": 0,
    "tables_needing_analyze": 0
  },
  "replication": {
    "is_replica": false,
    "lag_seconds": null
  },
  "checks": [
    {"name": "connection_pool", "status": "healthy", "message": "..."},
    {"name": "table_maintenance", "status": "healthy", "message": "..."},
    {"name": "long_running_queries", "status": "healthy", "message": "..."}
  ],
  "timestamp": "..."
}
```

**Validate**:
- [ ] HTTP 200 status
- [ ] status = "healthy" (or "warning" if issues)
- [ ] All checks present
- [ ] Reasonable metrics

---

#### **5.2: Performance Metrics**
```bash
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/admin/db/health/performance
```

**Expected**:
```json
{
  "cache_hit_ratio": 0.99,
  "index_hit_ratio": 0.95,
  "sequential_scans": {
    "total": 1000,
    "tables_with_high_seqscans": [...]
  },
  "transaction_stats": {
    "commits": 10000,
    "rollbacks": 50,
    "rollback_ratio": 0.005
  },
  "timestamp": "..."
}
```

**Validate**:
- [ ] HTTP 200 status
- [ ] cache_hit_ratio > 0.90 (healthy)
- [ ] index_hit_ratio > 0.90 (healthy)
- [ ] rollback_ratio < 0.05 (healthy)

---

### **Test 6: Maintenance Operations** ⚠️

**WARNING**: These are DESTRUCTIVE operations. Test with caution!

#### **6.1: Test Confirmation Required**
```bash
# Try without confirmation (should fail)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/admin/db/maintenance/cleanup
```

**Expected**:
```json
{
  "error": "Cleanup requires explicit confirmation",
  "usage": "POST /api/admin/db/maintenance/cleanup?confirm=yes&days=30",
  "warning": "This will DELETE all completed jobs older than 30 days"
}
```

**Validate**:
- [ ] HTTP 400 status
- [ ] Error message clear
- [ ] Usage instructions provided

---

#### **6.2: Cleanup Old Records (Safe)**
```bash
# Clean up records older than 90 days (conservative)
curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/admin/db/maintenance/cleanup?confirm=yes&days=90"
```

**Expected**:
```json
{
  "status": "success",
  "deleted": {
    "jobs": 0,
    "tasks": 0
  },
  "cutoff_date": "2025-08-05T...",
  "days": 90,
  "timestamp": "..."
}
```

**Validate**:
- [ ] HTTP 200 status
- [ ] deleted counts returned
- [ ] cutoff_date correct (90 days ago)

---

#### **6.3: DO NOT Test Nuke/Redeploy** 🚨

**DO NOT RUN** these in production:
```bash
# ❌ DON'T RUN - Will destroy all data!
# curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/admin/db/maintenance/nuke?confirm=yes"

# ❌ DON'T RUN - Will destroy and rebuild schema!
# curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/admin/db/maintenance/redeploy?confirm=yes"
```

**Note**: Test these only in isolated dev environment!

---

## 📊 **Application Insights Monitoring**

### **Check for Errors**

```bash
# Login to Azure
az login

# Query recent errors
/tmp/check_ai_errors.sh
```

**Create helper script**:
```bash
cat > /tmp/check_ai_errors.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(30m) | where severityLevel >= 3 | order by timestamp desc | take 20" \
  -G | python3 -m json.tool
EOF

chmod +x /tmp/check_ai_errors.sh
```

**Validate**:
- [ ] No errors related to admin endpoints
- [ ] No import errors
- [ ] No 500 errors

---

### **Check for Admin Endpoint Usage**

```bash
cat > /tmp/check_admin_usage.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=requests | where timestamp >= ago(30m) | where url contains 'admin' | order by timestamp desc | take 20" \
  -G | python3 -m json.tool
EOF

chmod +x /tmp/check_admin_usage.sh
```

---

## ✅ **Success Criteria**

Phase 1 deployment is successful if:

### **Critical** (Must Pass)
- [ ] All 16 admin endpoints return HTTP 200
- [ ] No 500 errors in Application Insights
- [ ] Schema operations return correct schemas
- [ ] Table operations return correct tables
- [ ] Health endpoint returns reasonable metrics

### **Important** (Should Pass)
- [ ] Geometry columns converted to GeoJSON (if geo schema has data)
- [ ] Query analysis endpoints work
- [ ] Connection stats accurate
- [ ] Performance metrics reasonable

### **Nice to Have** (May Warn)
- [ ] pg_stat_statements available (slow queries work)
- [ ] Cache hit ratio > 90%
- [ ] No tables needing vacuum

---

## 🐛 **Troubleshooting**

### **Issue: 404 Not Found on Admin Endpoints**

**Cause**: Routes not registered or wrong path

**Fix**:
1. Check function_app.py has all routes
2. Verify deployment completed successfully
3. Check Azure Portal function list

---

### **Issue: 500 Internal Server Error**

**Cause**: Environment variables missing or database connection failed

**Fix**:
1. Check Application Insights for exact error
2. Verify database connection string in Azure Portal
3. Check POSTGIS_* environment variables

---

### **Issue: Geometry Columns Return Raw WKB**

**Cause**: ST_AsGeoJSON not applied

**Fix**:
1. Check db_tables.py has geometry detection logic
2. Verify information_schema query works
3. Check column type detection

---

### **Issue: Empty Results for geo Schema**

**Cause**: No tables in geo schema yet

**Fix**:
This is expected! geo schema populated by ETL workflows.
Test with app schema instead.

---

## 📝 **Post-Deployment Actions**

### **If All Tests Pass** ✅

1. Update TODO.md with Phase 1 complete
2. Update HISTORY.md with achievement
3. Document any edge cases found
4. Plan Phase 2 (STAC admin endpoints)

### **If Issues Found** ❌

1. Document all issues in a new file (PHASE_1_ISSUES.md)
2. Prioritize fixes
3. Re-test after fixes
4. Update this checklist with lessons learned

---

## 📋 **Deployment Summary Template**

After testing, fill this out:

```
# Phase 1 Deployment Results

**Date**: [DATE]
**Deployed By**: [NAME]
**Environment**: rmhgeoapibeta

## Test Results

- Schema Operations: [✅/❌] ([X]/3 passed)
- Table Operations: [✅/❌] ([X]/4 passed)
- Query Analysis: [✅/❌] ([X]/4 passed)
- Health & Performance: [✅/❌] ([X]/2 passed)
- Maintenance: [✅/❌] ([X]/1 passed)

## Issues Found

[List any issues]

## Notes

[Any additional observations]

## Next Steps

[What to do next]
```

---

**End of Checklist** ✅

Ready to deploy and test Phase 1! 🚀
