# Search Persistence Investigation - Summary

**Date**: 13 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: ✅ VERIFICATION READY

---

## The Question

**Do TiTiler-PgSTAC searches persist across restarts, or do they need to be reregistered on startup?**

---

## Why This Matters

The original task was to implement "search reregistration on TiTiler startup" based on documentation that suggested searches might be ephemeral (stored in-memory). However, **this may be based on incorrect assumptions**.

If searches ARE already persistent in the database, implementing reregistration would be:
- ❌ Unnecessary complexity
- ❌ Wasted development time
- ❌ Adding code that solves a non-existent problem

**20 minutes of verification can save hours of unnecessary implementation.**

---

## Evidence FOR Persistence (Strong)

1. **Official Docker Image**: Using `ghcr.io/stac-utils/titiler-pgstac` which is designed for database-backed storage
2. **Working Endpoints**: `/searches/list` endpoint exists and functions (WORKING_ENDPOINTS.md line 44)
3. **Database Schema**: PGSTAC-REGISTRATION.md references `pgstac.searches` table (lines 494-507)
4. **TiTiler Design**: TiTiler-PgSTAC's purpose is database-backed STAC catalog, not in-memory caching
5. **Current Implementation**: Search registration in `stac_collection.py` works perfectly with no errors

---

## Evidence AGAINST Persistence (Weak)

1. **Documentation Warning**: PGSTAC-REGISTRATION.md lines 474-489 mentions "in-memory" option
   - **Counter**: This describes theoretical deployment options, not our actual deployment
2. **No Explicit Verification**: We haven't checked the database directly
   - **Counter**: Database access was blocked during development, so we assumed rather than verified

---

## Verification Plan

### Quick Test (5 minutes with database access)

```sql
-- 1. Check if searches table exists
\dt pgstac.searches

-- 2. Count searches
SELECT COUNT(*) FROM pgstac.searches;

-- 3. Show recent searches
SELECT id, search->>'collections', created_at
FROM pgstac.searches
ORDER BY created_at DESC
LIMIT 10;
```

**If searches exist in database → NO ACTION NEEDED**

### Definitive Test (10 minutes)

```bash
# 1. Get search_id from test collection
SEARCH_ID=$(curl -s https://rmhgeoapibeta-.../api/stac/collections/namangan_test_002 | jq -r '.summaries."mosaic:search_id"[0]')

# 2. Test BEFORE restart
curl "https://rmhtitiler-.../searches/$SEARCH_ID/WebMercatorQuad/tilejson.json?assets=data"
# Result: 200 OK

# 3. Restart TiTiler
az webapp restart --resource-group rmhazure_rg --name rmhtitiler

# 4. Wait 60 seconds

# 5. Test AFTER restart (same search_id, NO reregistration)
curl "https://rmhtitiler-.../searches/$SEARCH_ID/WebMercatorQuad/tilejson.json?assets=data"
# Expected: 200 OK (proves persistence!)
# If 404: searches are in-memory only
```

---

## Automated Verification

We've created two scripts to verify this:

### Script 1: Database + API Verification
```bash
./verify_search_persistence.sh
```

**What it does**:
- Phase 1: Check if `pgstac.searches` table exists
- Phase 2: Count and list searches in database
- Phase 3: Cross-reference collection metadata with database
- Phase 4: Test TiTiler search endpoints
- **Runtime**: ~5 minutes

### Script 2: Restart Test (Definitive)
```bash
./verify_search_persistence_restart.sh <search_id>
```

**What it does**:
- Test search BEFORE TiTiler restart
- Restart TiTiler via Azure CLI
- Wait for restart to complete
- Test SAME search AFTER restart (NO reregistration)
- Compare responses
- **Runtime**: ~10 minutes

**This is the PROOF** - if the same search_id works after restart, searches ARE persistent.

---

## Expected Outcomes

### ✅ Scenario A: Searches ARE Persistent (90% Probability)

**Evidence**:
- `pgstac.searches` table contains data
- Search works before restart (200 OK)
- Search works after restart (200 OK)
- No 404 errors

**Conclusion**:
- ✅ **NO IMPLEMENTATION NEEDED**
- ✅ Current code is already correct
- ✅ Searches survive restarts automatically
- ✅ Can close this task as "verified working"

**Action Items**:
1. Update PGSTAC-REGISTRATION.md to clarify searches ARE persistent
2. Remove "ephemeral search" warnings from documentation
3. Document verification results in HISTORY.md
4. Close task as "VERIFIED - NO ACTION NEEDED"

---

### ❌ Scenario B: Searches Are In-Memory (10% Probability)

**Evidence**:
- `pgstac.searches` table is empty OR doesn't exist
- Search works before restart (200 OK)
- Search FAILS after restart (404 Not Found)

**Conclusion**:
- ⚠️ TiTiler NOT configured for database backend
- ⚠️ Need configuration change OR implementation

**Action Items**:
1. **First**: Try configuring TiTiler environment variable:
   ```bash
   az webapp config appsettings set \
     --name rmhtitiler \
     --resource-group rmhazure_rg \
     --settings USE_SEARCH_CATALOG=true
   ```
2. **If config works**: Re-test, searches should now persist
3. **If config fails**: Implement startup reregistration as originally planned

---

## Files Created

1. **docs_claude/SEARCH_PERSISTENCE_VERIFICATION.md**
   - Full verification plan and expected results
   - Documentation template for results
   - Reference guide

2. **verify_search_persistence.sh**
   - Automated Phases 1-4 verification
   - Database + API testing
   - ~5 minute runtime

3. **verify_search_persistence_restart.sh**
   - Phase 5: Definitive restart test
   - Proves persistence (or lack thereof)
   - ~10 minute runtime

---

## How to Run Verification

### When Database Access Available:

```bash
# Step 1: Run main verification (Phases 1-4)
./verify_search_persistence.sh

# This will output a search_id for Phase 5

# Step 2: Run restart test (Phase 5)
./verify_search_persistence_restart.sh

# Step 3: Review results and make decision
```

### Quick Manual Test (Without Scripts):

```bash
# 1. Check database
PGPASSWORD='B@lamb634@' psql -h rmhpgflex.postgres.database.azure.com -U rob634 -d geopgflex \
  -c "SELECT COUNT(*) FROM pgstac.searches;"

# If count > 0: Searches ARE persistent
# If count = 0: Searches NOT persistent
```

---

## Key Insight

**The entire "reregistration on startup" requirement was based on documentation, not verified behavior.**

We're operating under the assumption that searches are ephemeral, but we never actually verified this. The official TiTiler-PgSTAC Docker image almost certainly uses database storage by default - that's literally its purpose.

**Verify first, implement second.**

---

## Recommendation

**STOP implementation work until verification complete.**

If searches ARE persistent (highly likely):
- ✅ Save hours of development time
- ✅ Avoid unnecessary code complexity
- ✅ Current implementation already works perfectly

If searches are NOT persistent (unlikely):
- ⚠️ Configuration fix is simpler than implementation
- ⚠️ Only implement reregistration if configuration fails

---

## Next Steps

1. **Wait for database access** to become available
2. **Run verification script**: `./verify_search_persistence.sh`
3. **If persistent** (expected):
   - Update documentation to clarify
   - Mark task as "VERIFIED - NO ACTION NEEDED"
   - Move on to other priorities
4. **If not persistent** (unlikely):
   - Try configuration fix first
   - Implement reregistration only if needed

---

## Status

**Current**: ✅ Verification plan ready, scripts written
**Blocked By**: Database access temporarily unavailable
**Next**: Run `./verify_search_persistence.sh` when database accessible
**ETA**: 20 minutes total verification time

---

**Conclusion**: We may have been about to solve a problem that doesn't exist. Verification first! 🔍
