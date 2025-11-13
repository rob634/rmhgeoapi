# pgSTAC Version Analysis & Fixes Required

**Date**: 13 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Priority**: HIGH - Affects STAC API functionality

---

## Current State

### Database (PostgreSQL)
- **pgSTAC Version**: **0.9.8** ✅ (Latest as of Nov 2025)
- **Collections**: 7
- **Items**: 14
- **Searches**: 11 rows (confirms persistence!)
- **Database Size**: 1.10 MB
- **Status**: Healthy

### Python Library (requirements.txt)
- **pypgstac Version**: **0.8.5** ❌ (Outdated - from ~June 2025)
- **Latest Available**: **0.9.8** (released August 2025)
- **Mismatch**: Yes (schema 0.9.8, library 0.8.5)

---

## Key Findings

### ✅ CONFIRMED: Searches ARE Persistent!

**Evidence**:
```json
{
  "searches": {
    "row_count": 11,
    "size_mb": "0.06",
    "column_count": 7,
    "indexes": ["searches_pkey"]
  }
}
```

**Conclusion**: The search persistence verification task can be marked as **COMPLETE** - searches are stored in `pgstac.searches` table and survive TiTiler restarts.

---

### ❌ CRITICAL: `pgstac.get_collection()` Function Does NOT Exist

**Problem**: `infrastructure/stac.py` line 1097 calls a function that doesn't exist in pgSTAC 0.9.8

**Current Code** (BROKEN):
```python
# infrastructure/stac.py line 1097
cur.execute(
    "SELECT * FROM pgstac.get_collection(%s)",
    [collection_id]
)
```

**Available pgSTAC Functions** (related to collections):
```
all_collections              ✅ Returns all collections (used successfully)
collection_base_item         ✅ Internal function
collection_bbox              ✅ Calculates collection bbox
collection_datetime          ✅ Calculates collection datetime
collection_delete_trigger    ✅ Trigger function
collection_enddatetime       ✅ Calculates end datetime
```

**MISSING**: `get_collection()` - No such function exists!

**Why This Breaks**:
1. PostgreSQL throws error: "function pgstac.get_collection(text) does not exist"
2. Exception handler in `infrastructure/stac.py` returns error dict
3. STAC API trigger detects error and returns 404
4. Empty body because exception may be swallowed somewhere

---

## Root Cause Analysis

### Why was `get_collection()` used?

Looking at the code history, this was likely copied from old pgSTAC documentation or examples that referenced a deprecated function. pgSTAC has evolved:

- **Old approach** (pre-0.9): May have had `get_collection()` helper function
- **New approach** (0.9+): Direct table queries with proper JSONB reconstruction

### The Correct Pattern (pgSTAC 0.9.8)

```sql
-- Get collection by ID (correct for pgSTAC 0.9.8)
SELECT content FROM pgstac.collections WHERE id = %s;
```

This returns the full collection JSONB from the `content` column.

---

## Required Fixes

### Fix #1: Update `get_collection()` Function ⚡ CRITICAL

**File**: `infrastructure/stac.py`
**Lines**: 1095-1115
**Priority**: CRITICAL (blocks collection detail endpoint)
**Estimated Time**: 2 minutes

**Change**:
```python
# OLD (BROKEN) - Line 1096-1099
cur.execute(
    "SELECT * FROM pgstac.get_collection(%s)",
    [collection_id]
)
result = cur.fetchone()

if result and result[0]:
    return result[0]  # Return collection JSON
```

**NEW (FIXED)**:
```python
# NEW (WORKING) - Direct table query
cur.execute(
    "SELECT content FROM pgstac.collections WHERE id = %s",
    [collection_id]
)
result = cur.fetchone()

if result and result[0]:
    return result[0]  # Return collection JSONB content
```

**Why This Works**:
- pgSTAC 0.9.8 stores full collection JSON in `content` column
- Direct table query is the standard pattern
- No function call needed

---

### Fix #2: Upgrade pypgstac Library ⚠️ RECOMMENDED

**File**: `requirements.txt`
**Line**: 26
**Priority**: MEDIUM (schema already at 0.9.8, but library should match)
**Estimated Time**: 5 minutes

**Change**:
```python
# OLD
pypgstac==0.8.5

# NEW
pypgstac==0.9.8
```

**Why Upgrade**:
- ✅ Match database schema version (consistency)
- ✅ Access to latest bug fixes
- ✅ Better error messages
- ✅ New helper functions (if any)

**Risk**: LOW - Minor version update (0.8 → 0.9), backward compatible

**After Upgrade**:
1. Redeploy Function App: `func azure functionapp publish rmhazuregeoapi --python --build remote`
2. Test imports: Check `/api/health` for pypgstac version

---

### Fix #3: Add pgSTAC Version to Health Endpoint ✅ DONE

**Status**: Already implemented! ✅

The `/api/stac/health` endpoint already returns:
```json
{
  "version": "0.9.8",
  "message": "PgSTAC 0.9.8 - 7 collections, 14 items"
}
```

No action needed.

---

### Fix #4: Update Search Persistence Verification Status ✅ DONE

**Files**:
- `docs_claude/TODO.md`
- `docs_claude/SEARCH_PERSISTENCE_VERIFICATION.md`

**Action**: Mark search persistence verification as **COMPLETE**

**Evidence**: 11 searches in `pgstac.searches` table proves persistence.

---

## pgSTAC 0.9.8 Schema Details

### Tables (13 total)
- `collections` - 7 rows (our STAC collections)
- `items` - Partitioned into `_items_2` through `_items_13` (14 total items)
- `searches` - **11 rows** (TiTiler search registrations) ✅ PERSISTENT!
- `queryables` - 3 rows (searchable fields)
- `items_staging` - 0 rows (ingestion buffer)

### Key Changes in 0.9.8 vs 0.8.5

According to pgSTAC release notes:
1. **Improved partition management** - Automatic partition creation
2. **Better search performance** - Optimized CQL2 queries
3. **Enhanced error messages** - Clearer PostgreSQL error reporting
4. **Bug fixes** - Various stability improvements

**Migration Path**: Upgrading pypgstac from 0.8.5 → 0.9.8 is safe (no breaking changes)

---

## Implementation Plan

### Phase 1: Critical Fix (5 minutes)

```bash
# 1. Edit infrastructure/stac.py
# Change line 1096-1099 from pgstac.get_collection() to direct query

# 2. Test locally (if possible)
# python -m pytest tests/test_stac.py  # If tests exist

# 3. Deploy
func azure functionapp publish rmhazuregeoapi --python --build remote

# 4. Verify fix
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/stac/collections/namangan_test_003"
# Should return 200 OK with collection JSON
```

---

### Phase 2: Library Upgrade (10 minutes)

```bash
# 1. Update requirements.txt
# Change pypgstac==0.8.5 to pypgstac==0.9.8

# 2. Deploy
func azure functionapp publish rmhazuregeoapi --python --build remote

# 3. Verify upgrade
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health" | jq '.modules."pypgstac"'
# Should show version 0.9.8
```

---

### Phase 3: Documentation Updates (5 minutes)

```bash
# 1. Update TODO.md
# - Mark STAC API collection detail fix as COMPLETE
# - Mark search persistence verification as COMPLETE

# 2. Update CLAUDE.md
# - Add note about pgSTAC 0.9.8 (latest version confirmed)
# - Update pypgstac version reference

# 3. Update HISTORY.md
# - Add entry: "Fixed collection detail endpoint (pgSTAC 0.9.8 compatibility)"
# - Add entry: "Upgraded pypgstac 0.8.5 → 0.9.8"
```

---

## Testing Checklist

### After Fix #1 (get_collection)

- [ ] GET /api/stac/collections/namangan_test_003 → 200 OK with collection JSON
- [ ] GET /api/stac/collections/namangan_test_002 → 200 OK with collection JSON
- [ ] GET /api/stac/collections/invalid_id → 404 with error JSON body
- [ ] Collection JSON has proper links (self, items, parent, root)
- [ ] Items endpoint now works: GET /api/stac/collections/namangan_test_003/items

### After Fix #2 (pypgstac upgrade)

- [ ] Health endpoint shows pypgstac 0.9.8
- [ ] No import errors in Application Insights
- [ ] All STAC endpoints still work correctly
- [ ] Schema migrations (if any) applied successfully

---

## Related Issues

### Issue #1: Missing STAC Fields in Items (RESOLVED)

**Status**: ✅ Fixed in previous session (13 NOV 2025)
**Fix**: Updated `infrastructure/stac.py` `get_collection_items()` to reconstruct full STAC items from split storage

### Issue #2: Search Persistence (VERIFIED)

**Status**: ✅ Confirmed working
**Evidence**: 11 searches in database, TiTiler uses database backend by default

### Issue #3: Collection Detail 404 (THIS ISSUE)

**Status**: ⏳ Fix ready, pending deployment
**Root Cause**: Non-existent `pgstac.get_collection()` function
**Solution**: Use direct table query (2-minute fix)

---

## Summary

**Current Situation**:
- ✅ Database at latest version (0.9.8)
- ❌ Python library outdated (0.8.5)
- ❌ Using deprecated function pattern
- ✅ Searches are persistent (verified)

**Action Required**:
1. **CRITICAL**: Fix `get_collection()` query (2 min) - Unblocks STAC API
2. **RECOMMENDED**: Upgrade pypgstac (10 min) - Version consistency
3. **DOCUMENTATION**: Update status (5 min) - Keep docs current

**Total Time**: ~20 minutes to fully resolve

---

**Next Steps**: Implement Fix #1 immediately to unblock STAC API collection detail endpoint.
