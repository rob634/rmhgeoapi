# PostgreSQL Requirements for rmhgeoapi

**Date**: 5 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: ✅ Production Ready - PostgreSQL 17 + PostGIS 3.6 + PgSTAC 0.8.5 deployed and verified

---

## 🎯 Overview

This document specifies all PostgreSQL requirements for the rmhgeoapi geospatial processing application, including version requirements, required extensions, configuration parameters, and schema setup.

---

## 📋 PostgreSQL Version

### Current Version (Deployed)
- **PostgreSQL 17.6** on Azure Flexible Server
- **Server**: rmhpgflex.postgres.database.azure.com
- **Database**: geopgflex
- **Resource Group**: rmhazure_rg

### Minimum Version
- **PostgreSQL 17.x** required

### Rationale
- PostGIS 3.6 requires PostgreSQL 14+
- PgSTAC 0.8.5 requires PostgreSQL 12+
- PostgreSQL 17 provides latest performance and security features
- **Note**: PostgreSQL 14 → 17 upgrade completed on 5 OCT 2025

---

## 🔌 Required Extensions

### Core Spatial Extension
**PostGIS 3.6+**
```sql
CREATE EXTENSION IF NOT EXISTS postgis;
```

**Purpose**: Spatial data types (geometry, geography) and spatial operations

**Sub-extensions** (optional but recommended):
```sql
CREATE EXTENSION IF NOT EXISTS postgis_raster;     -- Raster data support
CREATE EXTENSION IF NOT EXISTS postgis_topology;   -- Topology data types
CREATE EXTENSION IF NOT EXISTS postgis_sfcgal;     -- 3D operations
CREATE EXTENSION IF NOT EXISTS postgis_tiger_geocoder;  -- US geocoding
```

---

### STAC Catalog Extension
**PgSTAC 0.8.5**

Installed via `pypgstac migrate` command (not a SQL extension).

**Required PostgreSQL Extensions**:
```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;   -- REQUIRED for PgSTAC
CREATE EXTENSION IF NOT EXISTS postgis;      -- REQUIRED for PgSTAC
```

**Purpose**:
- SpatioTemporal Asset Catalog (STAC) metadata storage
- Efficient querying of geospatial assets by time and location
- STAC API backend

---

### Utility Extensions
**postgres_fdw** (Foreign Data Wrapper)
```sql
CREATE EXTENSION IF NOT EXISTS postgres_fdw;
```

**Purpose**: Future federation with other PostgreSQL instances

---

## ⚙️ Azure PostgreSQL Flexible Server Configuration

### Server Parameters

**azure.extensions** (allowlist)
```
POSTGIS,
POSTGIS_RASTER,
POSTGIS_SFCGAL,
POSTGIS_TOPOLOGY,
POSTGRES_FDW,
POSTGIS_TIGER_GEOCODER,
BTREE_GIST
```

**How to Configure**:
```bash
az postgres flexible-server parameter set \
  --resource-group rmhazure_rg \
  --server-name rmhpgflex \
  --name azure.extensions \
  --value "POSTGIS,POSTGIS_RASTER,POSTGIS_SFCGAL,POSTGIS_TOPOLOGY,POSTGRES_FDW,POSTGIS_TIGER_GEOCODER,BTREE_GIST"
```

---

## 🗄️ Schema Structure

### Application Schema: `app`
**Purpose**: Job orchestration, task tracking, workflow state

**Tables**:
```sql
-- Jobs table
CREATE TABLE app.jobs (
    id TEXT PRIMARY KEY,                    -- SHA256 hash of job_type + params
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,                   -- pending, processing, completed, failed
    stage INTEGER NOT NULL DEFAULT 1,
    parameters JSONB NOT NULL,
    metadata JSONB,
    result_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Tasks table
CREATE TABLE app.tasks (
    id TEXT PRIMARY KEY,                    -- job_id + stage + semantic_id
    job_id TEXT NOT NULL REFERENCES app.jobs(id),
    task_type TEXT NOT NULL,
    status TEXT NOT NULL,                   -- pending, processing, completed, failed
    stage INTEGER NOT NULL,
    parameters JSONB NOT NULL,
    heartbeat TIMESTAMPTZ,
    retry_count INTEGER DEFAULT 0,
    metadata JSONB,
    result_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_jobs_status ON app.jobs(status);
CREATE INDEX idx_jobs_created ON app.jobs(created_at);
CREATE INDEX idx_tasks_job_id ON app.tasks(job_id);
CREATE INDEX idx_tasks_status ON app.tasks(status);
```

---

### STAC Schema: `pgstac`
**Purpose**: STAC metadata catalog (managed by PgSTAC)

**Installation**:
```bash
# Via HTTP endpoint
POST /api/stac/setup?confirm=yes

# Or via pypgstac CLI
pypgstac migrate
```

**Schema Owner**: `pgstac_admin` role (auto-created)

**Key Tables** (22 total, managed by PgSTAC):
- `pgstac.collections` - STAC collections
- `pgstac.items` - STAC items (partitioned by collection)
- `pgstac.searches` - Saved searches
- `pgstac.queryables` - Query configuration
- `pgstac.migrations` - Migration history
- `pgstac.pgstac_settings` - Configuration
- Plus 16 other system tables

**DO NOT MODIFY** - Managed by PgSTAC migrations

**Current Status** (Verified 5 OCT 2025):
- ✅ PgSTAC 0.8.5 installed
- ✅ 22 tables created
- ✅ 3 roles configured (pgstac_admin, pgstac_read, pgstac_ingest)
- ✅ Accessible via `/api/stac/setup` endpoint

---

### Future Schema: `geo`
**Purpose**: Geospatial data storage (rasters, vectors)

**Planned Tables**:
```sql
-- Raster catalog
CREATE TABLE geo.rasters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    bounds GEOMETRY(POLYGON, 4326),
    resolution NUMERIC,
    bands INTEGER,
    cog_url TEXT,  -- Cloud-Optimized GeoTIFF URL
    stac_item_id TEXT,  -- Link to pgstac.items
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Vector catalog
CREATE TABLE geo.vectors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    bounds GEOMETRY(POLYGON, 4326),
    geometry_type TEXT,
    parquet_url TEXT,  -- GeoParquet URL
    stac_item_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 🔒 Roles and Permissions

### Application Role: `app_user`
```sql
CREATE ROLE app_user WITH LOGIN PASSWORD 'xxx';
GRANT CONNECT ON DATABASE geo TO app_user;
GRANT USAGE ON SCHEMA app TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO app_user;
```

### STAC Roles (auto-created by PgSTAC)
```sql
pgstac_admin   -- Full schema management
pgstac_ingest  -- Insert/update STAC items
pgstac_read    -- Read-only queries
```

**Application uses**: `pgstac_admin` for installation, `pgstac_ingest` for operations

---

## 🚀 Initial Setup Checklist

### 1. Create PostgreSQL Flexible Server
```bash
az postgres flexible-server create \
  --resource-group rmhazure_rg \
  --name rmhpgflex \
  --location eastus \
  --admin-user pgadmin \
  --admin-password <secure-password> \
  --sku-name Standard_B2s \
  --tier Burstable \
  --version 17 \
  --storage-size 32 \
  --public-access 0.0.0.0
```

### 2. Configure Extensions Allowlist
```bash
az postgres flexible-server parameter set \
  --resource-group rmhazure_rg \
  --server-name rmhpgflex \
  --name azure.extensions \
  --value "POSTGIS,POSTGIS_RASTER,POSTGIS_SFCGAL,POSTGIS_TOPOLOGY,POSTGRES_FDW,POSTGIS_TIGER_GEOCODER,BTREE_GIST"
```

### 3. Create Database and Extensions
```sql
-- Create database
CREATE DATABASE geo;

-- Connect to database
\c geo

-- Install PostGIS
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_raster;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- Install btree_gist (required for PgSTAC)
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Install postgres_fdw (for federation)
CREATE EXTENSION IF NOT EXISTS postgres_fdw;
```

### 4. Install PgSTAC
```bash
# Via HTTP endpoint (recommended)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/setup?confirm=yes

# Verify installation
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/setup
```

### 5. Deploy Application Schema
```bash
# Via "Nuclear Red Button"
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes
```

---

## 📊 Extension Dependencies

```
PgSTAC 0.8.5
├── PostgreSQL 12+ (using 17)
├── PostGIS 3.x+ (using 3.6)
└── btree_gist (required for temporal indexing)

PostGIS 3.6
├── PostgreSQL 14+ (using 17)
└── GEOS, PROJ, GDAL (auto-included in Azure)

Application
├── PostgreSQL 17
├── PostGIS 3.6
├── PgSTAC 0.8.5
└── psycopg 3.2.10 (Python driver)
```

---

## 🔍 Verification Commands

### Check PostgreSQL Version
```sql
SELECT version();
-- Expected: PostgreSQL 17.x
```

### Check PostGIS Version
```sql
SELECT PostGIS_Version();
-- Expected: 3.6 USE_GEOS=1 USE_PROJ=1 USE_STATS=1
```

### Check PgSTAC Version
```sql
SELECT pgstac.get_version();
-- Expected: 0.8.5
```

### List Installed Extensions
```sql
SELECT name, default_version, installed_version
FROM pg_available_extensions
WHERE installed_version IS NOT NULL
ORDER BY name;
```

### Check Schemas
```sql
SELECT schema_name
FROM information_schema.schemata
WHERE schema_name IN ('app', 'pgstac', 'geo')
ORDER BY schema_name;
-- Expected: app, pgstac
```

---

## 🐛 Troubleshooting

### Extension Not Allowlisted
**Error**: `extension "X" is not allow-listed for users`

**Solution**:
```bash
az postgres flexible-server parameter set \
  --resource-group rmhazure_rg \
  --server-name rmhpgflex \
  --name azure.extensions \
  --value "POSTGIS,...,X"  # Add extension name
```

### PgSTAC Installation Fails
**Check Prerequisites**:
```sql
-- Must both return TRUE
SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'postgis');
SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'btree_gist');
```

### Connection Issues

**CRITICAL: Single Connection String Pattern**
- All database connections MUST use `config.postgis_connection_string`
- DO NOT create custom connection strings in individual modules
- This ensures consistent SSL settings, encoding, and authentication

**Example Error**:
```
connection failed: no pg_hba.conf entry for host "X.X.X.X", user "{db_superuser}", database "geopgflex", no encryption
```

**Solution**: Verify module uses `config.postgis_connection_string` instead of building its own.

**Check Firewall Rules**:
```bash
az postgres flexible-server firewall-rule list \
  --resource-group rmhazure_rg \
  --name rmhpgflex
```

**Check Connection String**:
```bash
# From environment variables
echo $POSTGIS_HOST
echo $POSTGIS_DATABASE
echo $POSTGIS_USER
```

**Verify Connection String Usage**:
```python
# CORRECT - Use centralized connection string
from config import get_config
config = get_config()
conn_string = config.postgis_connection_string

# WRONG - Do not build custom connection strings
conn_string = f"postgresql://{user}:{password}@{host}:{port}/{database}"
```

---

## 📚 Reference Documentation

- **PostgreSQL 17**: https://www.postgresql.org/docs/17/
- **PostGIS 3.6**: https://postgis.net/docs/manual-3.6/
- **PgSTAC 0.8.5**: https://github.com/stac-utils/pgstac
- **Azure PostgreSQL Flexible Server**: https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/
- **Azure Extensions Allowlist**: https://go.microsoft.com/fwlink/?linkid=2301063

---

## 🔄 Upgrade Paths

### PostgreSQL 14 → 17
1. Create new PostgreSQL 17 server
2. Dump data from old server
3. Update azure.extensions allowlist
4. Restore data to new server
5. Reinstall PgSTAC
6. Update connection strings

### PostGIS 3.4 → 3.6
```sql
ALTER EXTENSION postgis UPDATE TO '3.6';
```

### PgSTAC Upgrades
```bash
# Automatic via pypgstac
pypgstac migrate
```

---

## ⚠️ Production Considerations

1. **Backups**: Enable automated backups (7-35 day retention)
2. **High Availability**: Enable zone-redundant HA for production
3. **Monitoring**: Enable Query Performance Insights
4. **Scaling**: Use Standard tier for production workloads
5. **Security**:
   - Disable public access
   - Use VNet integration
   - Enable SSL/TLS enforcement
   - Use Azure Active Directory authentication

---

## 📝 Notes

- **Geometry Field Name**: Currently hardcoded, will be configurable for ArcGIS Enterprise Geodatabase compatibility (uses "shape" instead of "geom")
- **Schema Separation**: `app` schema (redeployable in dev) vs `pgstac` schema (preserved)
- **PgSTAC Schema Naming**: 100% controlled by PgSTAC library, cannot be changed
- **Connection String**: Single source of truth in `config.postgis_connection_string` - all modules MUST use this
- **SSL/TLS**: Not explicitly required in connection string (psycopg3 handles automatically for Azure)
- **btree_gist Extension**: Required by PgSTAC for temporal indexing, must be allowlisted in Azure before installation

---

## 🎉 Deployment History

### 5 OCT 2025 - PostgreSQL 17 + PgSTAC Installation
- ✅ Upgraded PostgreSQL 14 → 17.6
- ✅ Enabled btree_gist extension in azure.extensions
- ✅ Installed PgSTAC 0.8.5 (22 tables)
- ✅ Fixed StacInfrastructure to use centralized connection string
- ✅ Verified STAC endpoints working
- **Issue Resolved**: StacInfrastructure was building custom connection string instead of using `config.postgis_connection_string`
