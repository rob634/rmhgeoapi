# PostgreSQL Database Setup and Configuration Guide

> **Navigation**: [Quick Start](../getting-started/QUICK_START.md) | [Platform API](../api-reference/PLATFORM_API.md) | [Errors](../api-reference/ERRORS.md) | [Glossary](../getting-started/GLOSSARY.md)

**Last Updated**: 12 FEB 2026
**Status**: Reference Documentation
**Purpose**: Developer guide for configuring PostgreSQL/PostGIS in the geospatial ETL pipeline
**Audience**: Developers and DevOps setting up or maintaining database infrastructure

---

## Purpose

This document provides setup and configuration instructions for the PostgreSQL database used by the geospatial ETL pipeline. The database stores:

- Job and task records (CoreMachine state)
- Vector data (PostGIS geometries)
- STAC metadata (pgSTAC catalog)

---

## Table of Contents

1. [Database Architecture](#database-architecture)
2. [Managed Identity Authentication](#managed-identity-authentication)
3. [Component Details](#component-details)
4. [Setup Instructions](#setup-instructions)
5. [Schema Reference](#schema-reference)
6. [Connection Configuration](#connection-configuration)
7. [Maintenance Operations](#maintenance-operations)
8. [Troubleshooting](#troubleshooting)

---

## Database Architecture

### PostgreSQL Flexible Server

The platform uses Azure Database for PostgreSQL Flexible Server with the following extensions:

- **PostGIS**: Spatial data types and functions
- **pgSTAC**: STAC metadata storage and search
- **uuid-ossp**: UUID generation

### Schema Organization

```
PostgreSQL Database
├── app (CoreMachine + ETL Tracking)
│   ├── jobs                    # Job records with status and results
│   ├── tasks                   # Task records with execution details
│   ├── vector_etl_tracking     # Internal ETL traceability (22 JAN 2026)
│   ├── raster_etl_tracking     # Internal ETL traceability (22 JAN 2026)
│   └── functions               # PostgreSQL functions for atomic operations
│
├── geo (Service Layer - Replicable to External DBs)
│   ├── table_catalog           # Vector table metadata (replaces table_metadata)
│   ├── feature_collection_styles # OGC API Styles (CartoSym-JSON)
│   ├── {user_tables}           # PostGIS tables created by process_vector jobs
│   └── spatial indexes
│
└── pgstac (STAC Metadata)
    ├── collections   # STAC collection records
    ├── items         # STAC item records
    └── searches      # Registered search configurations
```

**Architecture Note (22 JAN 2026)**: The `geo` schema contains only **service layer metadata** suitable for replication to external/partner databases. Internal ETL traceability (source files, processing timestamps) is stored in `app.vector_etl_tracking` which is **never replicated**. DDL for all tables is generated from Pydantic models via `PydanticToSQL` (Infrastructure as Code pattern).

---

## Component Details

### 1. Azure PostgreSQL Flexible Server

```yaml
# POPULATE FROM YOUR ENVIRONMENT:
Server Name: _______________________________
Resource Group: _______________________________
Region: _______________________________
PostgreSQL Version: 16+ (current: 17)
Compute Tier: _______________________________ (Burstable B1ms minimum)
Storage: _______________________________ GB
Backup Retention: 7 days (default)
```

**How to find server details**:
```bash
az postgres flexible-server show \
  --resource-group <YOUR_RG> \
  --name <YOUR_SERVER> \
  --query "{name:name, fqdn:fullyQualifiedDomainName, version:version, tier:sku.tier}" -o json
```

### 2. Database Configuration

```yaml
Database Name: postgres (default) or custom
Admin Username: _______________________________
SSL Mode: require (mandatory for Azure)
Connection Pooling: Application-level (psycopg3 pool)
Max Connections: Depends on tier (B1ms: 50, GP: 100+)
```

### 3. Required Extensions

**⚠️ IMPORTANT**: Extensions must be created by `azure_pg_admin` role (requires Azure Portal allowlist + SQL installation).

| Extension | Purpose | Required For |
|-----------|---------|--------------|
| **postgis** | Spatial data types and functions | All geospatial operations |
| **postgis_raster** | Raster data support | Raster operations |
| **btree_gist** | GiST indexes with B-tree behavior | pypgstac (exclusion constraints) |
| **btree_gin** | GIN indexes with B-tree behavior | pypgstac (composite indexing) |
| **uuid-ossp** | UUID generation | App schema |

**Installation Process** (two steps required):

1. **Azure Portal**: Add to `azure.extensions` server parameter (allowlist)
2. **SQL**: Run as `azure_pg_admin` member:
   ```sql
   CREATE EXTENSION IF NOT EXISTS postgis;
   CREATE EXTENSION IF NOT EXISTS postgis_raster;
   CREATE EXTENSION IF NOT EXISTS btree_gist;
   CREATE EXTENSION IF NOT EXISTS btree_gin;
   CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
   ```

**Note**: `pgstac` is not a PostgreSQL extension - it's deployed via `pypgstac migrate` CLI tool.

---

## Managed Identity Authentication

Azure PostgreSQL Flexible Server supports Microsoft Entra ID (Azure AD) authentication using User-Assigned Managed Identities. This eliminates the need to store database passwords in application settings.

### Identity Types

The platform uses two managed identities with different permission levels:

| Identity Type | Purpose | Permissions | Assigned To |
|---------------|---------|-------------|-------------|
| **Admin Identity** | ETL operations, schema management | Full DDL + DML (CREATE, DROP, INSERT, UPDATE, DELETE) | ETL Function Apps |
| **Reader Identity** | Read-only API access | SELECT only | OGC API, TiTiler, other read-only services |

### How Managed Identity Authentication Works

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Function App   │────>│    Azure AD     │────>│   PostgreSQL    │
│                 │     │                 │     │                 │
│ 1. Request      │     │ 2. Validate     │     │ 3. Authenticate │
│    AD token     │     │    identity     │     │    with token   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

1. **Function App** requests an Azure AD token using its assigned managed identity
2. **Azure AD** validates the identity and returns a short-lived token (~1 hour)
3. **PostgreSQL** accepts the token as the password, authenticating the connection

### Setup Requirements

To configure managed identity authentication:

#### 1. Create User-Assigned Managed Identity in Azure

```bash
az identity create \
  --name <IDENTITY_NAME> \
  --resource-group <YOUR_RG>
```

#### 2. Enable Entra ID Authentication on PostgreSQL Server

- In Azure Portal: PostgreSQL Server → Authentication → Enable Microsoft Entra authentication
- Set an Entra ID Administrator for the server

#### 3. Create PostgreSQL Role for the Identity

Connect to the `postgres` database (NOT your application database) as the Entra ID Administrator:

```sql
-- For Admin identity (NOT as azure_pg_admin - use is_admin=false)
SELECT * FROM pgaadauth_create_principal('<ADMIN_IDENTITY_NAME>', false, false);

-- For Reader identity (read-only)
SELECT * FROM pgaadauth_create_principal('<READER_IDENTITY_NAME>', false, false);
```

**Parameters**:
- First parameter: Role name (must match the managed identity name exactly)
- Second parameter (`is_admin`): `false` - do NOT grant azure_pg_admin (not needed!)
- Third parameter (`is_mfa`): `false` for service accounts

#### 4. Grant Admin Identity Permissions

The admin identity needs minimal permissions - no azure_pg_admin required:

```sql
-- Database-level: allows CREATE SCHEMA
GRANT CREATE ON DATABASE <database_name> TO "<admin_identity>";

-- pgstac roles WITH ADMIN OPTION (required for pypgstac migrate)
GRANT pgstac_admin TO "<admin_identity>" WITH ADMIN OPTION;
GRANT pgstac_ingest TO "<admin_identity>" WITH ADMIN OPTION;
GRANT pgstac_read TO "<admin_identity>" WITH ADMIN OPTION;

-- PostGIS access
GRANT USAGE ON SCHEMA public TO "<admin_identity>";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO "<admin_identity>";
```

**Note**: The admin identity creates schemas itself via `CREATE SCHEMA IF NOT EXISTS`, so it automatically owns them.

#### 5. Grant Reader Identity Default Privileges

Configure default privileges **before** the admin creates schemas/tables. This ensures that when the admin identity creates objects, the reader automatically gets SELECT access.

```sql
-- Auto-grant SELECT on all future tables/sequences created by admin
ALTER DEFAULT PRIVILEGES FOR ROLE "<admin_identity>"
    GRANT SELECT ON TABLES TO "<reader_identity>";
ALTER DEFAULT PRIVILEGES FOR ROLE "<admin_identity>"
    GRANT SELECT ON SEQUENCES TO "<reader_identity>";
ALTER DEFAULT PRIVILEGES FOR ROLE "<admin_identity>"
    GRANT USAGE ON SCHEMAS TO "<reader_identity>";
```

After schemas exist, also grant access to existing objects:

```sql
GRANT USAGE ON SCHEMA <schema_name> TO "<reader_identity>";
GRANT SELECT ON ALL TABLES IN SCHEMA <schema_name> TO "<reader_identity>";
```

See [DATABASE_IDENTITY_RUNBOOK.md](DATABASE_IDENTITY_RUNBOOK.md) for complete setup instructions.

#### 6. Assign Identity to Function App

```bash
IDENTITY_ID=$(az identity show \
    --name <IDENTITY_NAME> \
    --resource-group <YOUR_RG> \
    --query id --output tsv)

az functionapp identity assign \
    --name <YOUR_FUNCTION_APP> \
    --resource-group <YOUR_RG> \
    --identities "$IDENTITY_ID"
```

#### 7. Configure Application Settings

```bash
az functionapp config appsettings set \
    --name <YOUR_FUNCTION_APP> \
    --resource-group <YOUR_RG> \
    --settings \
        "USE_MANAGED_IDENTITY=true" \
        "DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID=<CLIENT_ID_OF_IDENTITY>" \
        "DB_ADMIN_MANAGED_IDENTITY_NAME=<IDENTITY_NAME>"
```

### Application Code Pattern

```python
from azure.identity import ManagedIdentityCredential

# Acquire token using the assigned identity
credential = ManagedIdentityCredential(client_id="<CLIENT_ID>")
token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default")

# Use token as password
conn_string = f"postgresql://<identity_name>:{token.token}@<server>.postgres.database.azure.com:5432/<database>?sslmode=require"
```

### Security Benefits

- **No stored passwords**: Tokens are acquired at runtime, no secrets in configuration
- **Automatic rotation**: Tokens expire after ~1 hour, automatically refreshed
- **Audit trail**: All access logged through Azure AD
- **Least privilege**: Separate identities for different access patterns

### Operational Runbook

For environment-specific values (Client IDs, Principal IDs, exact GRANT statements), see the internal operational runbook: `DATABASE_IDENTITY_RUNBOOK.md`

---

## Setup Instructions

### Step 1: Create PostgreSQL Flexible Server

```bash
# Create server (if not exists)
az postgres flexible-server create \
  --resource-group <YOUR_RG> \
  --name <YOUR_SERVER> \
  --location eastus \
  --admin-user <ADMIN_USERNAME> \
  --admin-password <ADMIN_PASSWORD> \
  --sku-name Standard_B1ms \
  --tier Burstable \
  --storage-size 32 \
  --version 17 \
  --yes
```

### Step 2: Configure Firewall Rules

```bash
# Allow Azure services
az postgres flexible-server firewall-rule create \
  --resource-group <YOUR_RG> \
  --name <YOUR_SERVER> \
  --rule-name AllowAzureServices \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0

# Allow your development IP (optional)
az postgres flexible-server firewall-rule create \
  --resource-group <YOUR_RG> \
  --name <YOUR_SERVER> \
  --rule-name DevMachine \
  --start-ip-address <YOUR_IP> \
  --end-ip-address <YOUR_IP>
```

### Step 3: Enable Required Extensions

Connect to the database as `azure_pg_admin` and enable extensions:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_raster;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS btree_gin;
```

**Note**: `pgstac` is not a PostgreSQL extension — it is deployed via `pypgstac migrate` at schema creation time.

### Step 4: Configure Function App Connection

The application uses managed identity authentication — no connection strings or passwords are stored. Configure the required environment variables:

```bash
az functionapp config appsettings set \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --settings \
    "POSTGIS_HOST=<SERVER>.postgres.database.azure.com" \
    "POSTGIS_DATABASE=<DATABASE>" \
    "POSTGIS_SCHEMA=geo" \
    "APP_SCHEMA=app" \
    "PGSTAC_SCHEMA=pgstac" \
    "H3_SCHEMA=h3" \
    "USE_MANAGED_IDENTITY=true" \
    "DB_ADMIN_MANAGED_IDENTITY_NAME=<ADMIN_IDENTITY_NAME>" \
    "DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID=<ADMIN_CLIENT_ID>"
```

For read-only services (OGC API, TiTiler), also set:
```bash
az functionapp config appsettings set \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --settings \
    "DB_READER_MANAGED_IDENTITY_NAME=<READER_IDENTITY_NAME>"
```

### Step 5: Deploy Schema

After deploying the Function App, initialize the database schema:

```bash
# Deploy schema via API endpoint (rebuilds both app and pgstac schemas)
curl -X POST "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/maintenance?action=rebuild&confirm=yes"
```

**Expected response**:
```json
{
  "status": "success",
  "operation": "full_rebuild",
  "schemas_created": ["app", "pgstac"],
  "tables_created": ["jobs", "tasks"]
}
```

### Step 6: Verify Installation

```bash
# Check database statistics
curl "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/stats"
```

**Expected response**:
```json
{
  "total_jobs": 0,
  "total_tasks": 0,
  "schemas": ["app", "geo", "pgstac"]
}
```

---

## Schema Reference

### app.jobs Table

Stores job records for the CoreMachine orchestration engine. DDL is generated from the `JobRecord` Pydantic model (`core/models/job.py`) via `PydanticToSQL`.

```sql
CREATE TABLE app.jobs (
    -- Identity
    job_id VARCHAR(64) PRIMARY KEY,
    job_type VARCHAR(100) NOT NULL,
    parameters JSONB NOT NULL DEFAULT '{}',

    -- Status tracking
    status VARCHAR(50) NOT NULL DEFAULT 'queued',
    stage INTEGER NOT NULL DEFAULT 1,
    total_stages INTEGER NOT NULL DEFAULT 1,

    -- V0.8 Release Control: Asset & Platform linkage (30 JAN 2026)
    asset_id VARCHAR(64),                -- FK to geospatial_assets
    platform_id VARCHAR(50),             -- FK to platforms (B2B source)
    request_id VARCHAR(64),              -- B2B request ID for callback routing
    etl_version VARCHAR(20),             -- Version of ETL app that executed this job

    -- Data fields
    stage_results JSONB NOT NULL DEFAULT '{}',
    metadata JSONB NOT NULL DEFAULT '{}',
    result_data JSONB,
    error_details TEXT,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_jobs_status ON app.jobs(status);
CREATE INDEX idx_jobs_job_type ON app.jobs(job_type);
CREATE INDEX idx_jobs_created_at ON app.jobs(created_at DESC);
```

**Status values**: queued, processing, completed, failed, completed_with_errors

### app.tasks Table

Stores task records for individual work units. DDL is generated from the `TaskRecord` Pydantic model (`core/models/task.py`) via `PydanticToSQL`.

```sql
CREATE TABLE app.tasks (
    -- Identity
    task_id VARCHAR(128) PRIMARY KEY,
    parent_job_id VARCHAR(64) NOT NULL REFERENCES app.jobs(job_id),
    job_type VARCHAR(100) NOT NULL,
    task_type VARCHAR(100) NOT NULL,
    stage INTEGER NOT NULL,
    task_index INTEGER NOT NULL DEFAULT 0,
    parameters JSONB NOT NULL DEFAULT '{}',

    -- Status tracking
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_pulse TIMESTAMP WITH TIME ZONE,         -- Docker long-running task heartbeat
    next_stage_params JSONB,                      -- Parameters for next stage

    -- Checkpoint tracking (11 JAN 2026 - Docker worker resume support)
    checkpoint_phase INTEGER,
    checkpoint_data JSONB,
    checkpoint_updated_at TIMESTAMP WITH TIME ZONE,

    -- Multi-app tracking (07 DEC 2025 - Multi-Function App Architecture)
    target_queue VARCHAR(100),                    -- Service Bus queue routed to
    executed_by_app VARCHAR(100),                 -- APP_NAME of processing Function App
    execution_started_at TIMESTAMP WITH TIME ZONE,

    -- Data fields
    result_data JSONB,
    metadata JSONB NOT NULL DEFAULT '{}',
    error_details TEXT,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_tasks_job_id ON app.tasks(parent_job_id);
CREATE INDEX idx_tasks_status ON app.tasks(status);
CREATE INDEX idx_tasks_stage ON app.tasks(parent_job_id, stage);
```

**Status values**: pending, processing, completed, failed

**Note**: The Pydantic models in `core/models/` are the source of truth for DDL. The SQL above is a reference snapshot — actual DDL is generated by `PydanticToSQL` at schema creation time.

### geo Schema

Contains user vector data tables created by `process_vector` jobs. Each table includes:

- Geometry column (PostGIS GEOMETRY type)
- GIST spatial index
- User-defined attribute columns

### pgstac Schema

Managed by the pgSTAC extension. Contains:

- `collections`: STAC collection metadata
- `items`: STAC item metadata with spatial index
- `searches`: Registered search configurations for TiTiler

---

## Connection Configuration

### Authentication: Managed Identity (UMI)

The application uses Azure Managed Identity for database authentication. No passwords or connection strings are stored. Tokens are acquired at runtime from Azure AD and used as the PostgreSQL password.

```
Token flow:  Function App → Azure AD → short-lived token (~1 hour) → PostgreSQL
```

### Environment Variables

**Required:**

| Variable | Description | Example |
|----------|-------------|---------|
| `POSTGIS_HOST` | PostgreSQL server hostname | `rmhpostgres.postgres.database.azure.com` |
| `POSTGIS_DATABASE` | Database name | `geoapp` |
| `POSTGIS_SCHEMA` | Geo/vector schema name | `geo` |
| `APP_SCHEMA` | Application schema name | `app` |
| `PGSTAC_SCHEMA` | pgSTAC schema name | `pgstac` |
| `H3_SCHEMA` | H3 hexagonal schema name | `h3` |

**Managed Identity:**

| Variable | Description | Default |
|----------|-------------|---------|
| `USE_MANAGED_IDENTITY` | Enable UMI auth | `true` |
| `DB_ADMIN_MANAGED_IDENTITY_NAME` | Admin UMI display name (PostgreSQL username) | — |
| `DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID` | Admin UMI client ID (for token acquisition) | — |
| `DB_READER_MANAGED_IDENTITY_NAME` | Reader UMI display name | — |

**Optional:**

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGIS_PORT` | PostgreSQL port | `5432` |
| `DB_CONNECTION_TIMEOUT` | Connection timeout (seconds) | `30` |
| `POSTGIS_USER` | Username (local dev / password auth only) | — |
| `POSTGIS_PASSWORD` | Password (local dev only — not used in production) | — |

### Connection Pooling

**⚠️ CRITICAL: Serverless Connection Pattern**

Traditional connection pooling does NOT work effectively in Azure Functions due to ephemeral instances. Instead, use the **memory-first, single-connection burst** pattern:

1. Do all computation in memory first (RAM is cheap)
2. Open ONE connection for fast bulk insert
3. Release connection immediately

**See [TECHNICAL_OVERVIEW.md → Serverless Database Connection Pattern](../architecture/TECHNICAL_OVERVIEW.md#serverless-database-connection-pattern)** for the full explanation, code examples, and the 23 DEC 2025 incident that taught us this lesson.

**Connection budget formula**:
```
Available = max_connections × 0.5 (safety margin)
Per task = Available ÷ concurrent_tasks
```

The application configuration below is for local development only:

```python
# config/database_config.py (local dev only)
pool_min_size: int = 1
pool_max_size: int = 10
pool_timeout: int = 30  # seconds
```

---

## Maintenance Operations

### View Database Statistics

```bash
curl https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/stats
```

### Query Jobs

```bash
# All jobs from last 24 hours
curl "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/jobs?hours=24&limit=100"

# Failed jobs only
curl "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/jobs?status=failed"

# Specific job
curl "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/jobs/{JOB_ID}"
```

### Query Tasks

```bash
# Tasks for a specific job
curl "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/tasks/{JOB_ID}"

# Failed tasks
curl "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/tasks?status=failed&limit=50"
```

### Schema Operations (Development Only)

```bash
# Rebuild both app and pgstac schemas (RECOMMENDED)
curl -X POST "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/maintenance?action=rebuild&confirm=yes"

# Rebuild app schema only (with warning about orphaned STAC items)
curl -X POST "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/maintenance?action=rebuild&target=app&confirm=yes"

# Rebuild pgstac schema only (with warning about orphaned job references)
curl -X POST "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/maintenance?action=rebuild&target=pgstac&confirm=yes"

# Cleanup old records (delete completed jobs older than N days)
curl -X POST "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/maintenance?action=cleanup&confirm=yes&days=30"
```

**WARNING**: Schema operations delete data. Use only in development/test environments.
**RECOMMENDED**: Use `action=rebuild` without a target to rebuild both schemas atomically. This maintains referential integrity between app.jobs and pgstac.items.

### Geo Schema Management (Updated 22 JAN 2026)

The geo schema contains vector tables created by `process_vector` jobs plus service layer metadata. These endpoints help manage and audit geo tables.

**Schema Structure (IaC Pattern)**:
- `geo.table_catalog` - Service layer metadata (title, description, bbox, STAC linkage)
- `geo.feature_collection_styles` - OGC API Styles (CartoSym-JSON storage)
- `geo.{user_tables}` - Actual vector data tables with PostGIS geometries

**Note**: DDL is generated from Pydantic models (`GeoTableCatalog`, `FeatureCollectionStyles`) via `PydanticToSQL`. See `core/models/geo.py` for the source of truth.

#### List Geo Table Metadata

Query all records in `geo.table_catalog` (the source of truth for vector datasets):

```bash
# List all metadata records
curl "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/geo/metadata"

# Filter by job ID
curl "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/geo/metadata?job_id=abc123"

# Filter by STAC linkage status
curl "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/geo/metadata?has_stac=true"
curl "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/geo/metadata?has_stac=false"

# Pagination
curl "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/geo/metadata?limit=50&offset=0"
```

**Response**:
```json
{
  "metadata": [
    {
      "table_name": "world_countries",
      "schema_name": "geo",
      "title": "World Country Boundaries",
      "description": "Administrative boundaries...",
      "attribution": "Natural Earth",
      "license": "CC0-1.0",
      "keywords": "boundaries,countries,admin",
      "feature_count": 250,
      "geometry_type": "MultiPolygon",
      "source_file": "world_countries.geojson",
      "source_format": "geojson",
      "etl_job_id": "abc123...",
      "stac_item_id": "postgis-geo-world_countries",
      "stac_collection_id": "vectors",
      "bbox": [-180, -90, 180, 90],
      "created_at": "2025-12-09T10:00:00Z"
    }
  ],
  "total": 15,
  "limit": 100,
  "offset": 0,
  "filters_applied": {}
}
```

#### Check for Orphaned Tables

Detect tables without metadata (orphaned tables) or metadata without tables (orphaned metadata):

```bash
curl "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/geo/orphans"
```

**Response**:
```json
{
  "success": true,
  "timestamp": "2025-12-10T12:00:00Z",
  "orphaned_tables": [
    {
      "table_name": "mystery_data",
      "row_count": 1500,
      "reason": "Table exists in geo schema but has no metadata record"
    }
  ],
  "orphaned_metadata": [
    {
      "table_name": "deleted_table",
      "etl_job_id": "xyz789",
      "created_at": "2025-12-01T10:00:00Z",
      "reason": "Metadata exists but table was dropped"
    }
  ],
  "tracked_tables": ["world_countries", "admin_boundaries"],
  "summary": {
    "total_geo_tables": 3,
    "total_metadata_records": 3,
    "tracked": 2,
    "orphaned_tables": 1,
    "orphaned_metadata": 1,
    "health_status": "ORPHANS_DETECTED"
  }
}
```

**Note**: Orphan check also runs automatically every 6 hours via timer trigger and logs findings to Application Insights.

#### Unpublish (Delete) Geo Table

Cascade delete a vector table from the geo schema. Handles both tracked tables (with metadata) and orphaned tables.

**Deletion order** (with SAVEPOINT isolation for fault tolerance):
1. Delete STAC item from `pgstac.items` (if exists) - *isolated with SAVEPOINT*
2. Delete metadata row from `geo.table_catalog` (if exists)
3. DROP TABLE `geo.{table_name}` CASCADE

**Fault Tolerance**: STAC deletion uses PostgreSQL SAVEPOINTs so that if pgSTAC triggers fail (e.g., missing partition tables after schema rebuild), the operation rolls back only the STAC deletion and continues with metadata/table cleanup.

```bash
# Unpublish a table (requires confirmation)
curl -X POST "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/geo/unpublish?table_name=world_countries&confirm=yes"
```

**Parameters**:
| Parameter | Required | Description |
|-----------|----------|-------------|
| `table_name` | Yes | Table name in geo schema (without schema prefix) |
| `confirm` | Yes | Must be "yes" to execute (safety measure) |

**Response (Success)**:
```json
{
  "success": true,
  "table_name": "world_countries",
  "deleted": {
    "stac_item": "postgis-geo-world_countries",
    "metadata_row": true,
    "geo_table": true
  },
  "warnings": [],
  "was_orphaned": false
}
```

**Response (Orphaned Table)**:
```json
{
  "success": true,
  "table_name": "mystery_table",
  "deleted": {
    "stac_item": null,
    "metadata_row": false,
    "geo_table": true
  },
  "warnings": [
    "No metadata found - table was orphaned (created outside ETL or metadata wiped)",
    "No STAC item ID in metadata (STAC cataloging may have been skipped)"
  ],
  "was_orphaned": true
}
```

**Response (STAC Deletion Failed - Graceful Degradation)**:

When pgSTAC has issues (e.g., missing partition tables after schema rebuild), the STAC deletion is isolated using PostgreSQL SAVEPOINTs. The metadata and table are still deleted successfully:

```json
{
  "success": true,
  "table_name": "vector_worker_test",
  "deleted": {
    "stac_item": null,
    "metadata_row": true,
    "geo_table": true
  },
  "warnings": [
    "STAC item deletion failed (pgstac trigger error): relation \"partition_sys_meta\" does not exist..."
  ],
  "was_orphaned": false
}
```

**Note**: The `warnings` array captures any non-fatal issues. STAC deletion failures are isolated so metadata and table cleanup still proceed.

**Response (Table Not Found)**:
```json
{
  "success": false,
  "error": "Table 'nonexistent_table' does not exist in geo schema",
  "table_name": "nonexistent_table"
}
```

**WARNING**: Unpublish permanently deletes the table and associated metadata. This operation cannot be undone.

---

### External Database Initialization (Updated 12 FEB 2026)

Initialize external/partner databases with `geo` and `pgstac` schemas. This is a **setup operation** run by DevOps using a temporary admin identity - the production app does NOT have write access to external databases.

> **Route Note**: These endpoints use `/api/dbadmin/external/*` (not `/api/admin/`). Azure App Service reserves the `/admin` path prefix — any routes under `/api/admin/*` return 404.

#### Complete Call Sequence

```
Step 0: DBA Setup (az cli + psql)          ← One-time per database
Step 1: GET  /api/dbadmin/external/prereqs  ← Verify DBA setup is complete
Step 2: POST /api/dbadmin/external/initialize (dry_run: true)   ← Validate
Step 3: POST /api/dbadmin/external/initialize (dry_run: false)  ← Execute
```

---

#### Step 0: DBA Setup (One-Time Per Database)

Create the database, extensions, roles, and admin UMI user. This must be done by a DBA with `azure_pg_admin` privileges.

**0a. Create database:**
```bash
az postgres flexible-server db create \
  --resource-group <RESOURCE_GROUP> \
  --server-name <SERVER_NAME> \
  --database-name <DATABASE_NAME>
```

**0b. Enable extensions** (connect as superuser):
```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_raster;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS btree_gin;
```

**0c. Create pgSTAC roles:**
```sql
DO $$ BEGIN CREATE ROLE pgstac_admin; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE pgstac_ingest; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE pgstac_read; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
```

**0d. Create admin UMI user with roles:**
```sql
-- Create AAD principal (run on postgres database, then switch back)
SELECT * FROM pgaadauth_create_principal('<ADMIN_UMI_NAME>', false, false);

-- Grant pgstac roles WITH ADMIN OPTION (required for pypgstac migrate)
GRANT pgstac_admin TO <ADMIN_UMI_NAME> WITH ADMIN OPTION;
GRANT pgstac_ingest TO <ADMIN_UMI_NAME>;
GRANT pgstac_read TO <ADMIN_UMI_NAME>;

-- Allow schema creation
GRANT CREATE ON DATABASE <DATABASE_NAME> TO <ADMIN_UMI_NAME>;
```

**0e. Create reader UMI with default privileges:**

Set up the reader identity and configure default privileges **before** the initializer runs. This ensures that when the initializer creates tables in `geo` and `pgstac`, the reader automatically gets SELECT access.

```sql
-- Create reader AAD principal (run on postgres database, then switch back)
SELECT * FROM pgaadauth_create_principal('<READER_UMI_NAME>', false, false);

-- Auto-grant SELECT on all future tables/sequences created by admin
ALTER DEFAULT PRIVILEGES FOR ROLE <ADMIN_UMI_NAME>
    GRANT SELECT ON TABLES TO <READER_UMI_NAME>;
ALTER DEFAULT PRIVILEGES FOR ROLE <ADMIN_UMI_NAME>
    GRANT SELECT ON SEQUENCES TO <READER_UMI_NAME>;
ALTER DEFAULT PRIVILEGES FOR ROLE <ADMIN_UMI_NAME>
    GRANT USAGE ON SCHEMAS TO <READER_UMI_NAME>;
```

---

#### Step 1: Check Prerequisites

Verify all DBA setup is complete before attempting initialization. The endpoint checks 7 prerequisites and returns exact SQL to fix anything missing.

```bash
curl -G "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/external/prereqs" \
  --data-urlencode "target_host=<HOST>.postgres.database.azure.com" \
  --data-urlencode "target_database=<DATABASE_NAME>" \
  --data-urlencode "admin_umi_client_id=<CLIENT_ID>" \
  --data-urlencode "admin_umi_name=<ADMIN_UMI_NAME>"
```

**Query Parameters**:
| Parameter | Required | Description |
|-----------|----------|-------------|
| `target_host` | Yes | External database hostname |
| `target_database` | Yes | External database name |
| `admin_umi_client_id` | Yes | Client ID of admin UMI |
| `admin_umi_name` | Yes | Display name of admin UMI (PostgreSQL username) |

**Response (Ready)**:
```json
{
  "checked_at": "2026-02-12T03:43:32.622854",
  "target_host": "rmhpostgres.postgres.database.azure.com",
  "target_database": "d360geo",
  "ready": true,
  "checks": {
    "admin_token": true,
    "connection": true,
    "postgis_extension": true,
    "role_pgstac_admin": true,
    "role_pgstac_ingest": true,
    "role_pgstac_read": true,
    "create_privilege": true
  },
  "missing": [],
  "dba_sql": []
}
```

**Response (Not Ready)** — includes DBA remediation SQL:
```json
{
  "ready": false,
  "checks": {
    "admin_token": true,
    "connection": true,
    "postgis_extension": false,
    "role_pgstac_admin": false,
    "role_pgstac_ingest": false,
    "role_pgstac_read": false,
    "create_privilege": true
  },
  "missing": [
    "PostGIS extension not installed",
    "Role 'pgstac_admin' does not exist",
    "Role 'pgstac_ingest' does not exist",
    "Role 'pgstac_read' does not exist"
  ],
  "dba_sql": [
    "CREATE EXTENSION IF NOT EXISTS postgis;",
    "DO $$ BEGIN CREATE ROLE pgstac_admin; EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
    "DO $$ BEGIN CREATE ROLE pgstac_ingest; EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
    "DO $$ BEGIN CREATE ROLE pgstac_read; EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
  ]
}
```

---

#### Step 2: Dry Run

Validate what will be created without touching the database:

```bash
curl -X POST "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/external/initialize" \
  -H "Content-Type: application/json" \
  -d '{
    "target_host": "<HOST>.postgres.database.azure.com",
    "target_database": "<DATABASE_NAME>",
    "admin_umi_client_id": "<CLIENT_ID>",
    "admin_umi_name": "<ADMIN_UMI_NAME>",
    "dry_run": true
  }'
```

**Response (Dry Run)**:
```json
{
  "target_host": "rmhpostgres.postgres.database.azure.com",
  "target_database": "d360geo",
  "dry_run": true,
  "success": true,
  "steps": [
    {
      "name": "check_prerequisites",
      "status": "success",
      "message": "All prerequisites met"
    },
    {
      "name": "initialize_geo_schema",
      "status": "dry_run",
      "message": "Would execute 11 statements",
      "sql_count": 11
    },
    {
      "name": "initialize_pgstac_schema",
      "status": "dry_run",
      "message": "Would run: pypgstac migrate",
      "sql_count": 1
    }
  ],
  "summary": {
    "total_steps": 3,
    "successful": 1,
    "failed": 0,
    "dry_run": 2
  }
}
```

---

#### Step 3: Execute

Run the actual initialization:

```bash
curl -X POST "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/external/initialize" \
  -H "Content-Type: application/json" \
  -d '{
    "target_host": "<HOST>.postgres.database.azure.com",
    "target_database": "<DATABASE_NAME>",
    "admin_umi_client_id": "<CLIENT_ID>",
    "admin_umi_name": "<ADMIN_UMI_NAME>",
    "dry_run": false
  }'
```

**Request Parameters**:
| Parameter | Required | Description |
|-----------|----------|-------------|
| `target_host` | Yes | External database hostname |
| `target_database` | Yes | External database name |
| `admin_umi_client_id` | Yes | Client ID of admin UMI |
| `admin_umi_name` | Yes | Display name of admin UMI (PostgreSQL username) |
| `dry_run` | No | If true, validate without executing (default: false) |
| `schemas` | No | List of schemas to create: `["geo", "pgstac"]` (default: both) |

**Response (Success)**:
```json
{
  "target_host": "rmhpostgres.postgres.database.azure.com",
  "target_database": "d360geo",
  "dry_run": false,
  "success": true,
  "steps": [
    {
      "name": "check_prerequisites",
      "status": "success",
      "message": "All prerequisites met",
      "details": {
        "admin_token": true,
        "connection": true,
        "postgis_extension": true,
        "role_pgstac_admin": true,
        "role_pgstac_ingest": true,
        "role_pgstac_read": true,
        "create_privilege": true
      }
    },
    {
      "name": "initialize_geo_schema",
      "status": "success",
      "message": "Geo schema 'geo' initialized (11 statements)",
      "sql_count": 11,
      "details": {
        "schema": "geo",
        "statements_executed": 11,
        "tables_created": ["table_catalog"],
        "source": "PydanticToSQL.generate_geo_schema_ddl()"
      }
    },
    {
      "name": "initialize_pgstac_schema",
      "status": "success",
      "message": "pypgstac migrate completed successfully",
      "details": {
        "stdout": "0.9.8\n",
        "returncode": 0,
        "post_migration_fixes": [
          "pgstac.partition_after_triggerfunc()",
          "pgstac.collection_delete_trigger_func()"
        ]
      }
    }
  ],
  "summary": {
    "total_steps": 3,
    "successful": 3,
    "failed": 0,
    "skipped": 0,
    "dry_run": 0
  }
}
```

**What gets created**:
- **`geo` schema** with:
  - `table_catalog` table (vector metadata - same structure as internal DB)
  - DDL generated from Pydantic models via `PydanticToSQL`
- **`pgstac` schema** with:
  - Full pgSTAC 0.9.8 (collections, items, partitioning, search functions)
  - Post-migration `search_path` fixes applied to trigger functions

---

#### Architecture Notes

- The initializer uses a **temporary admin UMI** passed by DevOps. The production Function App identity has **read-only access** to external databases.
- External databases contain **only `geo` and `pgstac` schemas** (no `app` schema) — they hold public/partner data only.
- After running this endpoint, DevOps should revoke or scope down the admin UMI as appropriate.
- The post-migration fixes patch pypgstac 0.9.8 trigger functions (`partition_after_triggerfunc`, `collection_delete_trigger_func`) with correct `search_path = pgstac, public` to prevent runtime errors.

---

## Troubleshooting

### Issue 1: Connection Refused

**Symptoms**: Function App cannot connect to database

**Diagnosis**:
```bash
# Check server status
az postgres flexible-server show \
  --resource-group <YOUR_RG> \
  --name <YOUR_SERVER> \
  --query state -o tsv
```

**Solutions**:
1. Verify server is running (state: "Ready")
2. Check firewall rules allow Azure services
3. Verify connection string format
4. Confirm SSL mode is "require"

### Issue 2: Extension Not Found

**Symptoms**: Error "extension postgis does not exist"

**Solution**:
```sql
-- Connect as admin and create extension
CREATE EXTENSION IF NOT EXISTS postgis;
```

### Issue 3: Permission Denied

**Symptoms**: Cannot create tables or insert data

**Diagnosis**: Check which identity is connecting and what permissions it has:
```sql
SELECT current_user, session_user;
SELECT has_database_privilege(current_user, current_database(), 'CREATE') as can_create;
```

**Solutions**:
- Verify the admin UMI has `CREATE ON DATABASE` (see Managed Identity Authentication § 4)
- Verify pgstac roles are granted `WITH ADMIN OPTION` (required for pypgstac migrate)
- Verify default privileges are configured for the reader identity (see § 5)
- Check that the Function App is assigned the correct managed identity

### Issue 4: Connection Pool Exhausted

**Symptoms**: "too many connections" error

**Diagnosis**:
```sql
-- Check active connections
SELECT count(*) FROM pg_stat_activity WHERE datname = '<database>';
```

**Solutions**:
1. Increase pool_max_size in configuration
2. Upgrade to higher tier with more connections
3. Review application for connection leaks

### Issue 5: Slow Queries

**Symptoms**: API responses are slow

**Diagnosis**:
```sql
-- Check for missing indexes
EXPLAIN ANALYZE SELECT * FROM app.jobs WHERE status = 'processing';
```

**Solutions**:
1. Verify indexes exist (see Schema Reference)
2. Run VACUUM ANALYZE on affected tables
3. Check for table bloat

---

## Related Documentation

- **[STORAGE.md](STORAGE.md)** - Azure Storage configuration
- **[TECHNICAL_OVERVIEW.md](../architecture/TECHNICAL_OVERVIEW.md)** - Architecture overview (includes Service Bus configuration)
- **[DATABASE_IDENTITY_RUNBOOK.md](DATABASE_IDENTITY_RUNBOOK.md)** - Managed identity setup details

---

**Last Updated**: 12 FEB 2026
