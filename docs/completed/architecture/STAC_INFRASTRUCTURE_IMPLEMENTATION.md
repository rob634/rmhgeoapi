# STAC Infrastructure Implementation

**Date**: 4 OCT 2025
**Author**: Robert and Geospatial Claude Legion

## Executive Summary

Implemented complete STAC (SpatioTemporal Asset Catalog) infrastructure for PgSTAC installation, management, and verification. The implementation provides idempotent schema detection and safe installation mechanisms suitable for both development and production environments.

## Architecture Overview

### Schema Naming (Controlled by PgSTAC Library)

**100% Fixed by PgSTAC - Cannot be Changed:**
- ✅ Schema name: `pgstac` (hardcoded in library)
- ✅ Role names: `pgstac_admin`, `pgstac_ingest`, `pgstac_read`
- ✅ Table names: `collections`, `items`, `partitions`, etc.
- ✅ Function names: `pgstac.search()`, `pgstac.get_version()`, etc.

**Our Control:**
- ✅ App schema: `app` (jobs, tasks) - completely separate
- ✅ STAC collections: Create with custom IDs
- ✅ Installation timing: Manual or automated

### Two-Tier Approach

**1. Fast Idempotent Check** (Startup Validation)
```python
from infrastructure import check_stac_installation

status = check_stac_installation()
# Returns: {installed, schema_exists, version, needs_migration}
```

**2. Full Installation** (One-Time Setup)
```bash
POST /api/stac/setup?confirm=yes
```

## Files Created

### 1. `infrastructure/stac.py` (~450 lines)

**Core Class**: `StacInfrastructure`

**Methods**:
- `check_installation()` - Fast, idempotent status check
- `install_pgstac()` - Run pypgstac migrate
- `verify_installation()` - Comprehensive verification
- `create_bronze_collection()` - Initial collection setup

**Safety Features**:
- Idempotent operations (safe to run multiple times)
- Explicit confirmation required for installation
- Double confirmation for DROP operations
- Environment variable protection (`PGSTAC_CONFIRM_DROP`)

**Key Design**:
```python
class StacInfrastructure:
    # PgSTAC constants (controlled by library)
    PGSTAC_SCHEMA = "pgstac"
    PGSTAC_ROLES = ["pgstac_admin", "pgstac_ingest", "pgstac_read"]

    def check_installation(self) -> Dict[str, Any]:
        """Fast check - suitable for startup validation"""

    def install_pgstac(self, drop_existing=False) -> Dict[str, Any]:
        """Run pypgstac migrate via subprocess"""

    def verify_installation(self) -> Dict[str, Any]:
        """Comprehensive 5-point verification"""
```

### 2. `triggers/stac_setup.py` (~250 lines)

**HTTP Endpoints**:

**GET Requests**:
```bash
# Quick status
GET /api/stac/setup

# Full verification
GET /api/stac/setup?verify=true
```

**POST Requests**:
```bash
# Install PgSTAC
POST /api/stac/setup?confirm=yes

# Reinstall (DESTRUCTIVE - requires env var)
POST /api/stac/setup?confirm=yes&drop=true
```

**Response Format**:
```json
{
  "operation": "install",
  "success": true,
  "version": "0.8.5",
  "schema": "pgstac",
  "tables_created": 15,
  "roles_created": ["pgstac_admin", "pgstac_ingest", "pgstac_read"],
  "verification": {...},
  "message": "✅ PgSTAC 0.8.5 installed successfully",
  "next_steps": [...]
}
```

### 3. Updated Files

- `function_app.py` - Added `/api/stac/setup` route
- `infrastructure/__init__.py` - Export STAC classes (would need lazy loading)

## Installation Process

### How pypgstac migrate Works

**Environment Variables Required**:
```bash
PGHOST=rmhpgflex.postgres.database.azure.com
PGPORT=5432
PGDATABASE=rmhgeo
PGUSER={db_superuser}
PGPASSWORD=<from_keyvault>
```

**What It Does**:
1. Connects to PostgreSQL
2. Creates `pgstac` schema
3. Creates roles (`pgstac_admin`, `pgstac_ingest`, `pgstac_read`)
4. Runs all migrations (creates tables, functions, indexes)
5. Sets permissions

**Idempotent**: Safe to run multiple times - checks version and only applies new migrations.

## Safety Mechanisms

### Development vs Production

**Development (Red Button Scenario)**:
```bash
# This is SAFE for development:
POST /api/db/schema/redeploy?confirm=yes

# Result:
# ✅ Drops `app` schema (jobs, tasks)
# ✅ Preserves `pgstac` schema (STAC data)
# ✅ Recreates app.jobs, app.tasks from Pydantic models
```

**Production**:
- No red button access
- PgSTAC already installed
- Only app schema gets migrated
- STAC data preserved

### Drop Protection

**To DROP pgstac schema** (DESTRUCTIVE):
```bash
# Requires TWO confirmations:
1. ?drop=true query parameter
2. PGSTAC_CONFIRM_DROP=true environment variable

# Example:
POST /api/stac/setup?confirm=yes&drop=true
# + Environment: PGSTAC_CONFIRM_DROP=true
```

Without both confirmations, DROP fails with safety error.

## Verification Checks

**5-Point Verification System**:

1. **Schema exists**: `SELECT EXISTS FROM pg_namespace WHERE nspname='pgstac'`
2. **Version query**: `SELECT pgstac.get_version()`
3. **Tables exist**: Count tables in pgstac schema
4. **Roles configured**: Check for 3+ pgstac_* roles
5. **Search available**: Test `SELECT pgstac.search('{}') LIMIT 1`

**Result**:
```json
{
  "valid": true,
  "schema_exists": true,
  "version_query": true,
  "version": "0.8.5",
  "tables_exist": true,
  "tables_count": 15,
  "roles_configured": true,
  "roles": ["pgstac_admin", "pgstac_ingest", "pgstac_read"],
  "search_available": true,
  "errors": []
}
```

## Usage Examples

### Check Status
```bash
curl https://rmhgeoapibeta-.../api/stac/setup
```

### Install PgSTAC (First Time)
```bash
curl -X POST "https://rmhgeoapibeta-.../api/stac/setup?confirm=yes"
```

### Full Verification
```bash
curl "https://rmhgeoapibeta-.../api/stac/setup?verify=true"
```

### Reinstall (Development Only)
```bash
# Set environment variable first
export PGSTAC_CONFIRM_DROP=true

# Then call endpoint
curl -X POST "https://rmhgeoapibeta-.../api/stac/setup?confirm=yes&drop=true"
```

## Integration with Existing System

### Separation of Concerns

**App Schema** (`app`):
- jobs table
- tasks table
- Job→Stage→Task orchestration
- Managed by Pydantic models
- Red button redeployable

**STAC Schema** (`pgstac`):
- collections table
- items table
- STAC catalog operations
- Managed by pypgstac
- Preserved during app schema redeploys

### No Conflicts

Both schemas coexist peacefully:
```sql
-- App operations
SELECT * FROM app.jobs WHERE status = 'completed';

-- STAC operations
SELECT * FROM pgstac.search('{"bbox": [-180,-90,180,90]}');
```

## Next Steps

1. **Deploy to Azure Functions** - Test in production environment
2. **Create Bronze Collection** - Initial STAC collection for raw data
3. **Implement STAC Ingestion Jobs** - Job→Stage→Task workflows for STAC items
4. **Add STAC Search Endpoints** - Expose pgstac.search() via HTTP API
5. **Integrate with Raster Jobs** - Auto-create STAC items during COG creation

## Testing Checklist

- [ ] Deploy to rmhgeoapibeta
- [ ] Check health endpoint (imports)
- [ ] GET /api/stac/setup (status check)
- [ ] POST /api/stac/setup?confirm=yes (installation)
- [ ] GET /api/stac/setup?verify=true (verification)
- [ ] Redeploy app schema (verify STAC preserved)
- [ ] Create test STAC collection
- [ ] Test pgstac.search() function

## Production Deployment Notes

**First Deployment**:
1. Deploy Azure Functions app
2. Run `POST /api/stac/setup?confirm=yes` (one time)
3. Verify installation
4. Create initial collections
5. Never run DROP in production

**Subsequent Deployments**:
- App schema can be redeployed (red button)
- STAC schema is preserved
- Functions app updates don't affect database

## Dependencies

**Python Packages** (already in requirements.txt):
```
pypgstac==0.8.5
psycopg[binary]
psycopg-pool>=3.1.0
pystac>=1.13.0
pystac-client>=0.7.0
rio-stac>=0.9.0
```

## Technical Notes

### Why Subprocess for pypgstac?

```python
# pypgstac migrate runs as subprocess because:
1. It's a CLI tool, not Python library
2. Reads env vars (PGHOST, PGDATABASE, etc.)
3. Runs migrations atomically
4. Provides clean separation from app code
```

### Why Separate Schemas?

```
app schema:     Frequently redeployed in development
pgstac schema:  One-time install, preserves data
Result:         Safe development workflow
```

### Error Handling

All operations return structured dicts with:
- `success: bool` - Operation succeeded
- `error: str` - Error message if failed
- `version: str` - PgSTAC version if available
- `details: dict` - Additional context

## Conclusion

The STAC infrastructure implementation provides:
✅ **Safe** - Multiple confirmation layers prevent accidents
✅ **Idempotent** - Safe to run multiple times
✅ **Separated** - App and STAC schemas don't conflict
✅ **Production-Ready** - Designed for both dev and prod
✅ **Well-Documented** - Clear usage examples and safety notes

Ready for deployment and testing!
