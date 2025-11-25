# PostgreSQL Database Setup and Configuration Guide

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
2. [Component Details](#component-details)
3. [Setup Instructions](#setup-instructions)
4. [Schema Reference](#schema-reference)
5. [Connection Configuration](#connection-configuration)
6. [Maintenance Operations](#maintenance-operations)
7. [Troubleshooting](#troubleshooting)

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

| Extension | Version | Purpose |
|-----------|---------|---------|
| postgis | 3.4+ | Spatial data types and functions |
| pgstac | 0.8+ | STAC metadata storage |
| uuid-ossp | - | UUID generation |

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

The application uses psycopg3 connection pooling:

```python
# config/database_config.py
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

**Last Updated**: 24 NOV 2025
