# PostgreSQL Database Setup and Configuration Guide

> **Navigation**: [Quick Start](WIKI_QUICK_START.md) | [Platform API](WIKI_PLATFORM_API.md) | [All Jobs](WIKI_API_JOB_SUBMISSION.md) | [Errors](WIKI_API_ERRORS.md) | [Glossary](WIKI_API_GLOSSARY.md)

**Date**: 24 NOV 2025
**Status**: Reference Documentation
**Wiki**: Azure DevOps Wiki - Database configuration documentation
**Purpose**: Developer guide for configuring PostgreSQL/PostGIS in the geospatial ETL pipeline
**Audience**: Developers setting up or maintaining database infrastructure

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
├── app (CoreMachine)
│   ├── jobs          # Job records with status and results
│   ├── tasks         # Task records with execution details
│   └── functions     # PostgreSQL functions for atomic operations
│
├── geo (Vector Data)
│   ├── {user_tables} # PostGIS tables created by ingest_vector jobs
│   └── spatial indexes
│
└── pgstac (STAC Metadata)
    ├── collections   # STAC collection records
    ├── items         # STAC item records
    └── searches      # Registered search configurations
```

---

## Component Details

### 1. Azure PostgreSQL Flexible Server

```yaml
# POPULATE FROM YOUR ENVIRONMENT:
Server Name: _______________________________
Resource Group: _______________________________
Region: _______________________________
PostgreSQL Version: 16
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

| Extension | Version | Purpose | Required For |
|-----------|---------|---------|--------------|
| **postgis** | 3.4+ | Spatial data types and functions | All geospatial operations |
| **btree_gist** | - | GiST indexes with B-tree behavior | pypgstac (exclusion constraints) |
| **unaccent** | - | Accent-insensitive text search | pypgstac (search functionality) |
| uuid-ossp | - | UUID generation | App schema |

**Installation Process** (two steps required):

1. **Azure Portal**: Add to `azure.extensions` server parameter (allowlist)
2. **SQL**: Run as `azure_pg_admin` member:
   ```sql
   CREATE EXTENSION IF NOT EXISTS postgis;
   CREATE EXTENSION IF NOT EXISTS btree_gist;
   CREATE EXTENSION IF NOT EXISTS unaccent;
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

#### 5. Grant Reader Identity Permissions

Run AFTER admin identity has created schemas:

```sql
GRANT USAGE ON SCHEMA <schema_name> TO "<reader_identity>";
GRANT SELECT ON ALL TABLES IN SCHEMA <schema_name> TO "<reader_identity>";

-- For future tables created by admin
ALTER DEFAULT PRIVILEGES FOR ROLE "<admin_identity>" IN SCHEMA <schema_name>
    GRANT SELECT ON TABLES TO "<reader_identity>";
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

#### 6. Configure Application Settings

```bash
az functionapp config appsettings set \
    --name <YOUR_FUNCTION_APP> \
    --resource-group <YOUR_RG> \
    --settings \
        "USE_MANAGED_IDENTITY=true" \
        "AZURE_CLIENT_ID=<CLIENT_ID_OF_IDENTITY>" \
        "POSTGIS_USER=<IDENTITY_NAME>"
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
  --version 16 \
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

Connect to the database and enable extensions:

```sql
-- Connect as admin user
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- pgstac requires separate installation (see pgSTAC documentation)
```

### Step 4: Configure Function App Connection

```bash
# Set connection string in Function App
az functionapp config appsettings set \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --settings DATABASE_CONNECTION_STRING="postgresql://<USER>:<PASSWORD>@<SERVER>.postgres.database.azure.com:5432/<DATABASE>?sslmode=require"
```

### Step 5: Deploy Schema

After deploying the Function App, initialize the database schema:

```bash
# Deploy schema via API endpoint
curl -X POST "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/maintenance/redeploy?confirm=yes"
```

**Expected response**:
```json
{
  "status": "success",
  "message": "Schema redeployed successfully",
  "schemas_created": ["app", "geo"],
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

Stores job records for the CoreMachine orchestration engine.

```sql
CREATE TABLE app.jobs (
    job_id VARCHAR(64) PRIMARY KEY,
    job_type VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'queued',
    stage INTEGER NOT NULL DEFAULT 1,
    total_stages INTEGER NOT NULL DEFAULT 1,
    parameters JSONB NOT NULL DEFAULT '{}',
    stage_results JSONB NOT NULL DEFAULT '{}',
    result_data JSONB,
    metadata JSONB NOT NULL DEFAULT '{}',
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

Stores task records for individual work units.

```sql
CREATE TABLE app.tasks (
    task_id VARCHAR(128) PRIMARY KEY,
    job_id VARCHAR(64) NOT NULL REFERENCES app.jobs(job_id),
    task_type VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    stage INTEGER NOT NULL,
    parameters JSONB NOT NULL DEFAULT '{}',
    result_data JSONB,
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    heartbeat TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_tasks_job_id ON app.tasks(job_id);
CREATE INDEX idx_tasks_status ON app.tasks(status);
CREATE INDEX idx_tasks_stage ON app.tasks(job_id, stage);
```

**Status values**: pending, processing, completed, failed

### geo Schema

Contains user vector data tables created by `ingest_vector` jobs. Each table includes:

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

### Connection String Format

```
postgresql://<username>:<password>@<server>.postgres.database.azure.com:5432/<database>?sslmode=require
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_CONNECTION_STRING` | Full connection string |
| `PGHOST` | Server hostname (alternative) |
| `PGUSER` | Username (alternative) |
| `PGPASSWORD` | Password (alternative) |
| `PGDATABASE` | Database name (alternative) |

### Connection Pooling

**⚠️ CRITICAL: Serverless Connection Pattern**

Traditional connection pooling does NOT work effectively in Azure Functions due to ephemeral instances. Instead, use the **memory-first, single-connection burst** pattern:

1. Do all computation in memory first (RAM is cheap)
2. Open ONE connection for fast bulk insert
3. Release connection immediately

**See [WIKI_TECHNICAL_OVERVIEW.md → Serverless Database Connection Pattern](WIKI_TECHNICAL_OVERVIEW.md#serverless-database-connection-pattern)** for the full explanation, code examples, and the 23 DEC 2025 incident that taught us this lesson.

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
# Redeploy schema (drops and recreates all tables)
curl -X POST "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/maintenance/redeploy?confirm=yes"

# Cleanup old records (delete completed jobs older than N days)
curl -X POST "https://<YOUR_FUNCTION_APP>.azurewebsites.net/api/dbadmin/maintenance/cleanup?confirm=yes&days=30"
```

**WARNING**: Schema operations delete data. Use only in development/test environments.

### Geo Schema Management (11 DEC 2025)

The geo schema contains vector tables created by `process_vector` jobs. These endpoints help manage and audit geo tables.

#### List Geo Table Metadata

Query all records in `geo.table_metadata` (the source of truth for vector datasets):

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
      "stac_collection_id": "system-vectors",
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
2. Delete metadata row from `geo.table_metadata` (if exists)
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

**Solution**:
```sql
-- Grant permissions to application user
GRANT ALL PRIVILEGES ON SCHEMA app TO <app_user>;
GRANT ALL PRIVILEGES ON SCHEMA geo TO <app_user>;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA app TO <app_user>;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA geo TO <app_user>;
```

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

- **[WIKI_API_SERVICE_BUS.md](WIKI_API_SERVICE_BUS.md)** - Service Bus configuration
- **[WIKI_API_STORAGE.md](WIKI_API_STORAGE.md)** - Azure Storage configuration
- **[WIKI_TECHNICAL_OVERVIEW.md](WIKI_TECHNICAL_OVERVIEW.md)** - Architecture overview
- **[docs_claude/CLAUDE_CONTEXT.md](docs_claude/CLAUDE_CONTEXT.md)** - Primary project context

---

**Last Updated**: 23 DEC 2025
