# TiTiler + Function App STAC - Success Summary

**Date**: 28 OCT 2025
**Status**: ✅ STAC Item Created Successfully | ⚠️ TiTiler Permissions Issue

## What We Accomplished ✅

### 1. TiTiler Web App Deployed and Configured
- **URL**: https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net
- **Container**: `ghcr.io/stac-utils/titiler-pgstac:latest`
- **Status**: Running and healthy
- **Managed Identity**: Configured with Storage Blob Data Reader on rmhazuregeo
- **Environment Variables**: All PostgreSQL settings configured

### 2. Function App STAC API Working
- **URL**: https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net
- **PgSTAC Schema**: Installed (v0.8.5, 26 tables)
- **Collections**: Multiple collections available including "cogs"
- **STAC Item Created**: Successfully added namangan GeoTIFF!

### 3. Namangan GeoTIFF Successfully Cataloged
```json
{
  "id": "cogs-namangan-namangan14aug2019_R1C2cog_analysis-tif",
  "collection": "cogs",
  "bbox": [71.668, 40.985, 71.722, 41.032],
  "assets": {
    "data": {
      "href": "https://rmhazuregeo.blob.core.windows.net/rmhazuregeosilver/namangan/namangan14aug2019_R1C2cog_analysis.tif",
      "type": "image/tiff; application=geotiff"
    }
  }
}
```

**Verified**:
- ✅ STAC item inserted into pgstac database
- ✅ Searchable via `/api/search?collections=cogs`
- ✅ Full metadata extracted (bounds, bands, statistics)
- ✅ Asset URL points to correct COG in Azure Storage

## Current Blocker ⚠️

**TiTiler Cannot Access pgstac Schema**

```json
{
  "detail": "schema \"pgstac\" does not exist\nLINE 1: SELECT pgstac.readonly()\n               ^"
}
```

**Diagnosis**:
- PgSTAC schema exists in database (verified via function app)
- TiTiler is connecting to the same PostgreSQL instance
- **Issue**: User {db_superuser} (TiTiler's DB user) lacks permissions to access `pgstac` schema

## Solution Required

Grant {db_superuser} user permissions to the `pgstac` schema:

```sql
-- Connect to PostgreSQL when you have direct access
GRANT USAGE ON SCHEMA pgstac TO {db_superuser};
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO {db_superuser};
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pgstac TO {db_superuser};

-- Or add {db_superuser} to pgstac_read role
GRANT pgstac_read TO {db_superuser};
```

**Alternative**: Check if the function app can grant permissions:

```bash
# Check if there's an endpoint to grant permissions
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/setup" | python3 -m json.tool
```

## What Works Right Now

### ✅ Via Function App (No Database Access Needed)
```bash
# List collections
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/collections"

# Search STAC items
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/search?collections=cogs&limit=10"

# Add new GeoTIFFs
curl -X POST "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/extract" \
  -H "Content-Type: application/json" \
  -d '{
    "container": "rmhazuregeosilver",
    "blob_name": "path/to/geotiff.tif",
    "collection_id": "cogs"
  }'
```

### ❌ TiTiler Endpoints (Need Permissions)
```bash
# These will fail until {db_superuser} has pgstac permissions
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/register"
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections"
```

## Next Steps

### Option 1: Grant Permissions via SQL (When You Have Access)
```sql
-- Connect to rmhpgflex.postgres.database.azure.com as admin
-- Database: postgres

-- Grant read access to {db_superuser}
GRANT USAGE ON SCHEMA pgstac TO {db_superuser};
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO {db_superuser};
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pgstac TO {db_superuser};

-- Make grants persistent for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT SELECT ON TABLES TO {db_superuser};
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT EXECUTE ON FUNCTIONS TO {db_superuser};
```

### Option 2: Use Admin User for TiTiler
If {db_superuser} is just a regular user, update TiTiler to use the PostgreSQL admin user:

```bash
# Get the admin username (usually postgres or similar)
# Update TiTiler environment variables
az webapp config appsettings set \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --settings POSTGRES_USER=postgres_admin_user

az webapp restart --resource-group rmhazure_rg --name rmhtitiler
```

### Option 3: Check if Function App Can Auto-Grant
The function app might have an endpoint to handle this. Check `/api/stac/setup` docs.

## Testing Commands

Once permissions are granted, test with:

```bash
# 1. Check TiTiler can see collections
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections"

# 2. Register a search
SEARCH=$(curl -s -X POST "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/register" \
  -H "Content-Type: application/json" \
  -d '{"collections": ["cogs"]}')

SEARCH_ID=$(echo "$SEARCH" | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")

# 3. Get a tile
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/$SEARCH_ID/tiles/10/725/394.png" -o tile.png

# 4. View the tile
open tile.png
```

## Architecture Diagram

```
Public Network (You)
       ↓
Function App STAC API (/api/stac/extract)
       ↓
PostgreSQL (rmhpgflex.postgres.database.azure.com)
       ├── pgstac schema (accessible by function app user)
       └── {db_superuser} user (❌ needs GRANT USAGE ON SCHEMA pgstac)
       ↓
TiTiler Web App (trying to read from pgstac)
       ↓
❌ Permission denied
```

## Summary

**What's Working**:
- ✅ STAC cataloging via function app
- ✅ GeoTIFF metadata extraction
- ✅ STAC item search
- ✅ Storage access via managed identity

**What's Blocked**:
- ❌ TiTiler tile generation (needs pgstac schema permissions)

**Quick Fix**:
```sql
GRANT pgstac_read TO {db_superuser};
-- OR --
GRANT USAGE ON SCHEMA pgstac TO {db_superuser};
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO {db_superuser};
```

## Files Created

All documentation is in `/titiler/`:
- `README.md` - Overview
- `WEB_APP_DEPLOYMENT.md` - TiTiler deployment details
- `MINIMAL_STAC_SETUP.md` - Manual STAC setup guide
- `FUNCTION_APP_STAC_SOLUTION.md` - Using function app for STAC
- `PGSTAC_SETUP_REQUIRED.md` - PgSTAC requirements
- `NON_STAC_USAGE.md` - Direct COG access (requires titiler-core)
- `TESTING_WORKFLOW.md` - Testing procedures
- `test_titiler.sh` - Automated test script
- `SUCCESS_SUMMARY.md` - This file

You're 95% there! Just need database permissions and TiTiler will work! 🚀