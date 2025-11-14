# pgSTAC Search Persistence Verification

**Date**: 13 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: 🔍 VERIFICATION IN PROGRESS

---

## Purpose

Verify whether TiTiler-PgSTAC searches are stored persistently in the PostgreSQL database or ephemerally in memory.

**Hypothesis**: Searches ARE persistent (stored in `pgstac.searches` table), making startup reregistration unnecessary.

---

## Background

During implementation of pgSTAC search-based mosaics, documentation (PGSTAC-REGISTRATION.md) suggested searches might be ephemeral and require reregistration on TiTiler restart. However, evidence suggests this may be incorrect for our deployment.

**Key Evidence for Persistence**:
1. Using official `ghcr.io/stac-utils/titiler-pgstac` Docker image
2. `/searches/list` endpoint exists and works
3. Documentation references `pgstac.searches` table
4. TiTiler-PgSTAC designed for database-backed storage by default

---

## Verification Plan

### Phase 1: Database Schema Check ✅ READY

**Goal**: Confirm `pgstac.searches` table exists

```sql
-- Check table existence
\dt pgstac.searches

-- Show table structure
\d pgstac.searches

-- Expected columns:
-- - id (text, primary key)
-- - search (jsonb) - CQL2 query definition
-- - metadata (jsonb) - optional metadata
-- - created_at (timestamp)
```

**Status**: ⏳ Waiting for database access

---

### Phase 2: Search Data Verification ✅ READY

**Goal**: Confirm test searches are stored in database

```sql
-- List all stored searches
SELECT
    id,
    search->>'collections' as collections,
    metadata->>'name' as name,
    created_at
FROM pgstac.searches
ORDER BY created_at DESC
LIMIT 20;

-- Look for our test collections
SELECT id, search, metadata
FROM pgstac.searches
WHERE search->'collections' @> '["namangan_test_002"]'::jsonb
   OR search->'collections' @> '["namangan_test_003"]'::jsonb;

-- Count total searches
SELECT COUNT(*) as total_searches FROM pgstac.searches;
```

**Status**: ⏳ Waiting for database access

---

### Phase 3: Collection Metadata Cross-Reference ✅ READY

**Goal**: Verify collection metadata matches database searches

```sql
-- Get collections with search_id
SELECT
    id as collection_id,
    summaries->'mosaic:search_id'->>0 as stored_search_id
FROM pgstac.collections
WHERE summaries ? 'mosaic:search_id'
ORDER BY id;

-- Cross-reference with searches table
SELECT
    c.id as collection_id,
    c.summaries->'mosaic:search_id'->>0 as search_id_in_collection,
    s.id as search_id_in_searches_table,
    s.created_at as search_created_at,
    CASE
        WHEN c.summaries->'mosaic:search_id'->>0 = s.id THEN '✅ MATCH'
        ELSE '❌ MISMATCH'
    END as status
FROM pgstac.collections c
LEFT JOIN pgstac.searches s ON c.summaries->'mosaic:search_id'->>0 = s.id
WHERE c.summaries ? 'mosaic:search_id';
```

**Status**: ⏳ Waiting for database access

---

### Phase 4: TiTiler API Verification ✅ READY

**Goal**: Confirm TiTiler can retrieve searches without reregistration

```bash
# 1. Get list of all searches from TiTiler
curl https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/list

# 2. Get specific collection to extract search_id
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/collections/namangan_test_002 \
  | jq '.summaries."mosaic:search_id"[0]'

# 3. Test search endpoint with extracted ID
SEARCH_ID="<from step 2>"
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/${SEARCH_ID}"

# 4. Test TileJSON endpoint
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/${SEARCH_ID}/WebMercatorQuad/tilejson.json?assets=data"

# 5. Test viewer URL (open in browser)
open "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/${SEARCH_ID}/WebMercatorQuad/map.html?assets=data"
```

**Status**: ⏳ Ready to run when database verification complete

---

### Phase 5: TiTiler Restart Test 🔥 CRITICAL

**Goal**: PROVE searches survive restart (definitive test)

```bash
# 1. Get current search_id from test collection
SEARCH_ID=$(curl -s https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/collections/namangan_test_002 \
  | jq -r '.summaries."mosaic:search_id"[0]')

echo "Testing search_id: $SEARCH_ID"

# 2. Test viewer BEFORE restart
echo "=== BEFORE RESTART ==="
curl -s "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/${SEARCH_ID}/WebMercatorQuad/tilejson.json?assets=data" \
  | jq '.tilejson, .bounds'

# Expected: 200 OK with valid TileJSON

# 3. Restart TiTiler
echo "=== RESTARTING TITILER ==="
az webapp restart --resource-group rmhazure_rg --name rmhtitiler

# 4. Wait for restart
echo "Waiting 60 seconds for restart..."
sleep 60

# 5. Test SAME search_id AFTER restart (NO reregistration!)
echo "=== AFTER RESTART ==="
curl -s "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/${SEARCH_ID}/WebMercatorQuad/tilejson.json?assets=data" \
  | jq '.tilejson, .bounds'

# Expected: 200 OK with identical response - PROVES PERSISTENCE!

# 6. Test viewer in browser
echo "=== VIEWER TEST ==="
echo "Open this URL in browser (should work without errors):"
echo "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/${SEARCH_ID}/WebMercatorQuad/map.html?assets=data"
```

**Status**: ⏳ Ready to run after API verification

---

## Automated Verification Script

Save as `verify_search_persistence.sh`:

```bash
#!/bin/bash
set -e

echo "=========================================="
echo "pgSTAC Search Persistence Verification"
echo "=========================================="
echo ""

# Database connection
DB_HOST="rmhpgflex.postgres.database.azure.com"
DB_USER="rob634"
DB_NAME="geopgflex"
export PGPASSWORD='B@lamb634@'

# API URLs
FUNCTION_APP="https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net"
TITILER="https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net"

echo "Phase 1: Database Schema Check"
echo "==============================="
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "\dt pgstac.searches"
echo ""

echo "Phase 2: Search Data Verification"
echo "=================================="
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c \
  "SELECT id, search->>'collections' as collections, created_at FROM pgstac.searches ORDER BY created_at DESC LIMIT 10;"
echo ""

echo "Phase 3: Collection Metadata Cross-Reference"
echo "============================================="
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c \
  "SELECT c.id, c.summaries->'mosaic:search_id'->>0 as search_id, s.id as db_search_id
   FROM pgstac.collections c
   LEFT JOIN pgstac.searches s ON c.summaries->'mosaic:search_id'->>0 = s.id
   WHERE c.summaries ? 'mosaic:search_id';"
echo ""

echo "Phase 4: TiTiler API Verification"
echo "=================================="
echo "TiTiler searches list:"
curl -s $TITILER/searches/list | jq '.'
echo ""

echo "Getting search_id from namangan_test_002:"
SEARCH_ID=$(curl -s $FUNCTION_APP/api/stac/collections/namangan_test_002 | jq -r '.summaries."mosaic:search_id"[0]')
echo "Search ID: $SEARCH_ID"
echo ""

echo "Testing search endpoint:"
curl -s "$TITILER/searches/$SEARCH_ID" | jq '.'
echo ""

echo "Testing TileJSON endpoint:"
curl -s "$TITILER/searches/$SEARCH_ID/WebMercatorQuad/tilejson.json?assets=data" | jq '.tilejson, .bounds, .center'
echo ""

echo "=========================================="
echo "VERIFICATION COMPLETE"
echo "=========================================="
echo ""
echo "Next: Run Phase 5 restart test manually"
echo "Viewer URL: $TITILER/searches/$SEARCH_ID/WebMercatorQuad/map.html?assets=data"
```

**Usage**:
```bash
chmod +x verify_search_persistence.sh
./verify_search_persistence.sh
```

---

## Expected Results

### ✅ Scenario A: Searches ARE Persistent (EXPECTED)

**Database Evidence**:
- `pgstac.searches` table exists with data
- Searches from test jobs are present
- Collection metadata matches database search IDs

**API Evidence**:
- `/searches/list` returns searches
- Individual search endpoints return 200 OK
- TileJSON and viewer work correctly

**Restart Test Evidence**:
- Same search_id works before AND after TiTiler restart
- No 404 errors after restart
- Viewer loads correctly after restart

**Conclusion**: ✅ **NO IMPLEMENTATION NEEDED** - Searches already persist correctly!

---

### ❌ Scenario B: Searches Are In-Memory (UNLIKELY)

**Database Evidence**:
- `pgstac.searches` table empty OR doesn't exist
- No search records in database

**API Evidence**:
- `/searches/list` returns empty array OR 404
- Search endpoints return 404 after checking TiTiler

**Restart Test Evidence**:
- Same search_id works BEFORE restart
- Same search_id returns 404 AFTER restart
- Viewer breaks after restart

**Conclusion**: ⚠️ Need to configure TiTiler database backend OR implement startup reregistration

---

## Verification Results

### Test Run #1: [DATE]

**Phase 1 - Database Schema**:
```
[Results pending database access]
```

**Phase 2 - Search Data**:
```
[Results pending database access]
```

**Phase 3 - Cross-Reference**:
```
[Results pending database access]
```

**Phase 4 - API Verification**:
```
[Results pending]
```

**Phase 5 - Restart Test**:
```
[Results pending]
```

**Overall Result**: ⏳ PENDING

---

## Next Steps

### After Verification - If Persistent:
1. ✅ Update PGSTAC-REGISTRATION.md to clarify persistence
2. ✅ Remove misleading "in-memory" discussion
3. ✅ Document verification results
4. ✅ Mark task as "VERIFIED - NO ACTION NEEDED"

### After Verification - If In-Memory:
1. ⚠️ Configure TiTiler environment variable: `USE_SEARCH_CATALOG=true`
2. ⚠️ If configuration fails, implement startup reregistration
3. ⚠️ Re-test after configuration

---

## References

- PGSTAC-REGISTRATION.md (lines 452-507) - Search storage discussion
- services/stac_collection.py (lines 397-477) - Current search registration implementation
- services/titiler_search_service.py - TiTiler API integration
- titiler/WORKING_ENDPOINTS.md (line 44) - `/searches/list` endpoint evidence

---

**Status**: 🔍 Verification phase - database access required
**Next Action**: Run verification script when database access available
