# Final Fix Required: Schema Permissions

**Date**: 28 OCT 2025
**Status**: ✅ SSL Fixed | ⚠️ Schema Permissions Needed

## What We Fixed ✅

### SSL Connection Issue
**Problem**: PostgreSQL requires SSL, TiTiler wasn't using it
**Solution**: Added `PGSSLMODE=require` environment variable
**Result**: ✅ TiTiler now connects to PostgreSQL successfully

**Proof**:
```json
{
  "database_online": true  // ← Connection works!
}
```

## Remaining Issue ⚠️

### Schema Visibility Problem
**Error**:
```json
{
  "detail": "schema \"pgstac\" does not exist\nLINE 1: SELECT * FROM pgstac.all_collections();\n                      ^"
}
```

**Diagnosis**: User {db_superuser} can connect to PostgreSQL but doesn't have permissions to see/use the `pgstac` schema.

### Why This Happens
PostgreSQL has two levels of access:
1. **Connection** (✅ Working now with SSL)
2. **Schema Usage** (❌ Missing permissions)

Even though {db_superuser} can connect, the pgstac schema is not in their search path or they lack USAGE permission.

## The Fix: Grant Schema Permissions

When you have database access, run these SQL commands:

### Option 1: Grant Direct Permissions (Recommended)
```sql
-- Connect to database
\c postgres

-- Grant usage on schema
GRANT USAGE ON SCHEMA pgstac TO {db_superuser};

-- Grant select on all tables
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO {db_superuser};

-- Grant execute on all functions
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pgstac TO {db_superuser};

-- Make it persist for future objects
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac
  GRANT SELECT ON TABLES TO {db_superuser};

ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac
  GRANT EXECUTE ON FUNCTIONS TO {db_superuser};
```

### Option 2: Add to pgstac_read Role (Cleaner)
```sql
-- Connect to database
\c postgres

-- Add {db_superuser} to the pgstac_read role
GRANT pgstac_read TO {db_superuser};
```

The `pgstac_read` role was created by PgSTAC installation and already has all necessary read permissions.

## Verification After Fix

Run this SQL to verify permissions:
```sql
-- Check if {db_superuser} has usage on pgstac schema
SELECT has_schema_privilege('{db_superuser}', 'pgstac', 'USAGE');
-- Should return: true

-- Check if {db_superuser} can read pgstac tables
SELECT has_table_privilege('{db_superuser}', 'pgstac.collections', 'SELECT');
-- Should return: true
```

## Testing After SQL Fix

Once you run the GRANT commands:

```bash
# 1. Check collections endpoint (should list collections)
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections"

# 2. Register a search
curl -X POST "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/register" \
  -H "Content-Type: application/json" \
  -d '{"collections": ["cogs"]}'

# Expected response:
{
  "id": "abc123...",  # search hash
  "links": [...],
  "search": {...}
}

# 3. Get a tile from your namangan GeoTIFF
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/{search_id}/tiles/10/725/394.png" -o namangan_tile.png

# 4. View the tile
open namangan_tile.png
```

## Why Your Function App Works

Your function app likely connects as a different user (possibly the admin user or a user with broader permissions). Check with:

```bash
# Compare connection settings
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/setup" | python3 -c "import sys, json; print(json.load(sys.stdin).get('connection_info', 'N/A'))"
```

## Alternative: Use Same User as Function App

If you don't want to grant permissions to {db_superuser}, you could configure TiTiler to use the same PostgreSQL user as your function app:

```bash
# Find what user the function app uses
az webapp config appsettings list \
  --resource-group rmhazure_rg \
  --name rmhgeoapibeta \
  --query "[?name=='POSTGIS_USER'].value" -o tsv

# Then update TiTiler to use same user
az webapp config appsettings set \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --settings POSTGRES_USER=<function_app_user>

# Would also need the password for that user
```

## Summary of Configuration Changes

### What We Set in TiTiler:
```bash
POSTGRES_HOST=rmhpgflex.postgres.database.azure.com
POSTGRES_PORT=5432
POSTGRES_USER={db_superuser}
POSTGRES_PASS={db_password}
POSTGRES_DBNAME=postgres
POSTGRES_SCHEMA=pgstac
PGSSLMODE=require              # ← Added today (SSL fix)
```

### What Still Needs SQL:
```sql
GRANT pgstac_read TO {db_superuser};   # ← Run this when you have DB access
```

## Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| TiTiler Deployed | ✅ | Running on Web App |
| Managed Identity | ✅ | Storage access configured |
| Environment Variables | ✅ | All set correctly |
| SSL Connection | ✅ | Fixed with PGSSLMODE=require |
| Network/Firewall | ✅ | Azure services allowed |
| PostgreSQL Connection | ✅ | Health shows database_online: true |
| Schema Permissions | ❌ | **Need: GRANT pgstac_read TO {db_superuser}** |

## One Command Fix

When you're on a network with database access:

```bash
# Connect and grant permissions (one line)
PGPASSWORD='{db_password}' psql -h rmhpgflex.postgres.database.azure.com -U {db_superuser} -d postgres -c "GRANT pgstac_read TO {db_superuser};"
```

Wait, {db_superuser} can't grant themselves permissions! You'll need to connect as an admin user:

```bash
# Connect as PostgreSQL admin
PGPASSWORD='<admin_password>' psql -h rmhpgflex.postgres.database.azure.com -U <admin_user> -d postgres -c "GRANT pgstac_read TO {db_superuser};"
```

## Next Steps

1. When you have database access (not public network)
2. Connect as PostgreSQL admin user
3. Run: `GRANT pgstac_read TO {db_superuser};`
4. Test TiTiler endpoints
5. Generate tiles! 🎉

You're literally one SQL command away from having working TiTiler! 🚀