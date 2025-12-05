# Database Setup Guide: Managed Identity and Dual Database Architecture

**Date**: 30 NOV 2025
**Author**: Robert Harrison
**Audience**: Cloud and Database Teams
**Purpose**: Step-by-step SQL commands to set up managed identity access for Azure PostgreSQL

---

## Overview

This guide explains how to:
1. **Create** a PostgreSQL user for Azure Managed Identity
2. **Grant** full admin access on the App Database (for schema rebuild operations)
3. **Create** a new Business Database with PostGIS enabled
4. **Grant** restricted CRUD-only access on the Business Database (protected from accidental deletion)

### Architecture Diagram

```
Azure Function App (rmhazuregeoapi)
        |
        | Uses managed identity: rmhpgflexadmin
        |
        v
+------------------+     +------------------+
|  APP DATABASE    |     | BUSINESS DATABASE|
|   (geopgflex)    |     |    (ddhgeodb)    |
+------------------+     +------------------+
| Full DDL Access  |     | CRUD Only Access |
| - CREATE SCHEMA  |     | - SELECT         |
| - DROP SCHEMA    |     | - INSERT         |
| - CREATE TABLE   |     | - UPDATE         |
| - DROP TABLE     |     | - DELETE         |
+------------------+     +------------------+
| Schemas:         |     | Schemas:         |
| - app (jobs)     |     | - geo (ETL data) |
| - pgstac (STAC)  |     |                  |
| - geo (reference)|     |                  |
| - h3 (hex grids) |     |                  |
+------------------+     +------------------+
```

---

## Prerequisites

### What You Need Before Starting

| Requirement | Description | How to Check |
|-------------|-------------|--------------|
| **Entra ID Admin** | You must be the Azure AD administrator for the PostgreSQL server | Check Azure Portal > PostgreSQL > Authentication |
| **User-Assigned Managed Identity** | The identity `rmhpgflexadmin` must exist in Azure | `az identity show --name rmhpgflexadmin --resource-group rmhazure_rg` |
| **Client ID** | You need the Client ID of the managed identity | See table below |

### Identity Information

| Property | Value |
|----------|-------|
| **Identity Name** | `rmhpgflexadmin` |
| **Client ID** | `a533cb80-a590-4fad-8e52-1eb1f72659d7` |
| **Resource Group** | `rmhazure_rg` |
| **PostgreSQL Server** | `rmhpgflex.postgres.database.azure.com` |

**Important**: The Client ID is used by the application code to acquire tokens. The Identity Name becomes the PostgreSQL username.

---

## Step 1: Create PostgreSQL User for Managed Identity

### What This Does
- Creates a PostgreSQL role that can authenticate using Azure AD tokens
- The role name MUST match the managed identity name exactly
- No password is stored - authentication uses Azure AD tokens

### How to Connect

You must connect as the Entra ID Administrator:

```bash
# Get your Azure AD token
TOKEN=$(az account get-access-token --resource-type oss-rdbms --query accessToken --output tsv)

# Connect to the 'postgres' database (NOT geopgflex!)
PGPASSWORD="$TOKEN" psql \
    -h rmhpgflex.postgres.database.azure.com \
    -U "YOUR_AZURE_AD_ADMIN_EMAIL" \
    -d postgres
```

Replace `YOUR_AZURE_AD_ADMIN_EMAIL` with your Azure AD administrator email.

### SQL Command

```sql
-- ============================================================================
-- STEP 1: CREATE MANAGED IDENTITY USER
-- ============================================================================
-- This command creates a PostgreSQL role for the Azure managed identity.
--
-- IMPORTANT:
--   - Run this on the 'postgres' database, NOT on geopgflex or ddhgeodb
--   - The name 'rmhpgflexadmin' must exactly match the Azure identity name
--   - First parameter: role name
--   - Second parameter (true): is_admin - grants azure_pg_admin membership
--   - Third parameter (false): is_mfa - no MFA required for service accounts
-- ============================================================================

SELECT * FROM pgaadauth_create_principal('rmhpgflexadmin', true, false);
```

### Expected Output

```
      pgaadauth_create_principal
---------------------------------------
 Created role for rmhpgflexadmin
(1 row)
```

### Verify the User Was Created

```sql
-- Check that user exists and has admin privileges
SELECT
    rolname,
    rolcanlogin,
    rolcreaterole,
    rolcreatedb
FROM pg_roles
WHERE rolname = 'rmhpgflexadmin';
```

Expected output:
```
    rolname     | rolcanlogin | rolcreaterole | rolcreatedb
----------------+-------------+---------------+-------------
 rmhpgflexadmin | t           | t             | t
(1 row)
```

---

## Step 2: Grant Full Access on App Database (geopgflex)

### What This Does
- Grants FULL administrative access to the App Database
- Allows CREATE SCHEMA, DROP SCHEMA, and all other DDL operations
- Required for schema rebuild operations during deployments

### How to Connect

Connect to the `geopgflex` database as the schema owner:

```bash
PGPASSWORD='YOUR_PASSWORD' psql \
    -h rmhpgflex.postgres.database.azure.com \
    -U rob634 \
    -d geopgflex
```

### SQL Commands

```sql
-- ============================================================================
-- STEP 2: GRANT FULL ADMIN ACCESS ON APP DATABASE (geopgflex)
-- ============================================================================
-- These grants give rmhpgflexadmin full control over the app database.
-- This is needed for:
--   - Schema rebuilds (DROP SCHEMA, CREATE SCHEMA)
--   - Table management (CREATE TABLE, DROP TABLE, ALTER TABLE)
--   - Function deployment (CREATE FUNCTION)
--   - Data operations (INSERT, UPDATE, DELETE, SELECT)
-- ============================================================================

-- --------------------------------------
-- Grant database-level privileges
-- --------------------------------------
GRANT CONNECT ON DATABASE geopgflex TO rmhpgflexadmin;
GRANT CREATE ON DATABASE geopgflex TO rmhpgflexadmin;

-- --------------------------------------
-- Schema: app (jobs, tasks, api_requests tables)
-- --------------------------------------
GRANT ALL PRIVILEGES ON SCHEMA app TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA app TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA app TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA app TO rmhpgflexadmin;

-- Future objects in app schema
ALTER DEFAULT PRIVILEGES IN SCHEMA app
    GRANT ALL PRIVILEGES ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA app
    GRANT ALL PRIVILEGES ON SEQUENCES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA app
    GRANT ALL PRIVILEGES ON FUNCTIONS TO rmhpgflexadmin;

-- --------------------------------------
-- Schema: pgstac (STAC metadata catalog)
-- --------------------------------------
GRANT ALL PRIVILEGES ON SCHEMA pgstac TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA pgstac TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA pgstac TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA pgstac TO rmhpgflexadmin;

-- Future objects in pgstac schema
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac
    GRANT ALL PRIVILEGES ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac
    GRANT ALL PRIVILEGES ON SEQUENCES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac
    GRANT ALL PRIVILEGES ON FUNCTIONS TO rmhpgflexadmin;

-- --------------------------------------
-- Schema: geo (reference geographic data)
-- --------------------------------------
GRANT ALL PRIVILEGES ON SCHEMA geo TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA geo TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA geo TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA geo TO rmhpgflexadmin;

-- Future objects in geo schema
ALTER DEFAULT PRIVILEGES IN SCHEMA geo
    GRANT ALL PRIVILEGES ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA geo
    GRANT ALL PRIVILEGES ON SEQUENCES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA geo
    GRANT ALL PRIVILEGES ON FUNCTIONS TO rmhpgflexadmin;

-- --------------------------------------
-- Schema: h3 (H3 hexagon grids)
-- --------------------------------------
GRANT ALL PRIVILEGES ON SCHEMA h3 TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA h3 TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA h3 TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA h3 TO rmhpgflexadmin;

-- Future objects in h3 schema
ALTER DEFAULT PRIVILEGES IN SCHEMA h3
    GRANT ALL PRIVILEGES ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA h3
    GRANT ALL PRIVILEGES ON SEQUENCES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA h3
    GRANT ALL PRIVILEGES ON FUNCTIONS TO rmhpgflexadmin;
```

### Verify Permissions

```sql
-- Check schema privileges
SELECT
    n.nspname AS schema_name,
    has_schema_privilege('rmhpgflexadmin', n.nspname, 'USAGE') AS has_usage,
    has_schema_privilege('rmhpgflexadmin', n.nspname, 'CREATE') AS has_create
FROM pg_namespace n
WHERE n.nspname IN ('app', 'pgstac', 'geo', 'h3')
ORDER BY n.nspname;
```

Expected output:
```
 schema_name | has_usage | has_create
-------------+-----------+------------
 app         | t         | t
 geo         | t         | t
 h3          | t         | t
 pgstac      | t         | t
(4 rows)
```

---

## Step 3: Create Business Database with PostGIS

### What This Does
- Creates a new database for ETL output data
- Enables the PostGIS extension for geographic data
- Creates a `geo` schema for storing processed vector data

### How to Connect

Connect as the database administrator:

```bash
PGPASSWORD='YOUR_PASSWORD' psql \
    -h rmhpgflex.postgres.database.azure.com \
    -U rob634 \
    -d postgres
```

### SQL Commands

```sql
-- ============================================================================
-- STEP 3A: CREATE THE BUSINESS DATABASE
-- ============================================================================
-- This creates a separate database for ETL output data.
-- The business database is protected from accidental schema deletion.
-- ============================================================================

-- Create the database
CREATE DATABASE ddhgeodb
    WITH
    OWNER = rob634
    ENCODING = 'UTF8'
    LC_COLLATE = 'en_US.utf8'
    LC_CTYPE = 'en_US.utf8'
    TEMPLATE = template0;

-- Grant connection rights to the managed identity
GRANT CONNECT ON DATABASE ddhgeodb TO rmhpgflexadmin;
```

Now connect to the new database to enable PostGIS:

```bash
PGPASSWORD='YOUR_PASSWORD' psql \
    -h rmhpgflex.postgres.database.azure.com \
    -U rob634 \
    -d ddhgeodb
```

```sql
-- ============================================================================
-- STEP 3B: ENABLE POSTGIS EXTENSION
-- ============================================================================
-- PostGIS is required for storing and querying geographic data.
-- This must be done by a superuser or database owner.
-- ============================================================================

-- Enable PostGIS extension
CREATE EXTENSION IF NOT EXISTS postgis;

-- Verify PostGIS is installed
SELECT PostGIS_Version();
```

Expected output:
```
            postgis_version
---------------------------------------
 3.4 USE_GEOS=1 USE_PROJ=1 USE_STATS=1
(1 row)
```

```sql
-- ============================================================================
-- STEP 3C: CREATE GEO SCHEMA FOR ETL DATA
-- ============================================================================
-- This schema will store all vector data from the ETL pipeline.
-- ============================================================================

-- Create the geo schema
CREATE SCHEMA IF NOT EXISTS geo;

-- Set default search path
ALTER DATABASE ddhgeodb SET search_path TO geo, public;
```

---

## Step 4: Grant Restricted CRUD Access on Business Database

### What This Does
- Grants ONLY data manipulation permissions (SELECT, INSERT, UPDATE, DELETE)
- Does NOT grant DROP SCHEMA permission
- Does NOT grant DROP TABLE permission (only implicit via CASCADE, if needed)
- Protects business data from accidental deletion

### Key Difference from App Database

| Permission | App Database (geopgflex) | Business Database (ddhgeodb) |
|------------|--------------------------|------------------------------|
| CREATE SCHEMA | YES | NO |
| DROP SCHEMA | YES | NO |
| CREATE TABLE | YES | YES (in geo schema only) |
| DROP TABLE | YES | NO |
| SELECT | YES | YES |
| INSERT | YES | YES |
| UPDATE | YES | YES |
| DELETE | YES | YES |

### SQL Commands

Connect to the business database:

```bash
PGPASSWORD='YOUR_PASSWORD' psql \
    -h rmhpgflex.postgres.database.azure.com \
    -U rob634 \
    -d ddhgeodb
```

```sql
-- ============================================================================
-- STEP 4: GRANT RESTRICTED CRUD ACCESS ON BUSINESS DATABASE (ddhgeodb)
-- ============================================================================
-- IMPORTANT: These grants are INTENTIONALLY LIMITED.
--
-- What IS granted:
--   - USAGE on geo schema (can use the schema)
--   - CREATE on geo schema (can create tables)
--   - SELECT, INSERT, UPDATE, DELETE on tables (CRUD operations)
--   - USAGE on sequences (for auto-increment columns)
--   - EXECUTE on functions (for PostGIS functions)
--
-- What is NOT granted:
--   - DROP on schema (cannot delete the schema)
--   - DROP on tables (cannot delete tables, only rows)
--   - CREATE DATABASE (cannot create new databases)
--   - CREATE SCHEMA (cannot create new schemas)
-- ============================================================================

-- --------------------------------------
-- Schema: geo (ETL output data)
-- --------------------------------------

-- Grant schema usage and table creation
GRANT USAGE ON SCHEMA geo TO rmhpgflexadmin;
GRANT CREATE ON SCHEMA geo TO rmhpgflexadmin;

-- Grant CRUD operations on all existing tables
GRANT SELECT, INSERT, UPDATE, DELETE
    ON ALL TABLES IN SCHEMA geo
    TO rmhpgflexadmin;

-- Grant sequence usage (for auto-increment columns)
GRANT USAGE
    ON ALL SEQUENCES IN SCHEMA geo
    TO rmhpgflexadmin;

-- Grant function execution (for PostGIS functions)
GRANT EXECUTE
    ON ALL FUNCTIONS IN SCHEMA geo
    TO rmhpgflexadmin;

-- --------------------------------------
-- Future objects (new tables created by ETL)
-- --------------------------------------

-- Future tables get CRUD permissions
ALTER DEFAULT PRIVILEGES IN SCHEMA geo
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO rmhpgflexadmin;

-- Future sequences get usage permissions
ALTER DEFAULT PRIVILEGES IN SCHEMA geo
    GRANT USAGE ON SEQUENCES TO rmhpgflexadmin;

-- Future functions get execute permissions
ALTER DEFAULT PRIVILEGES IN SCHEMA geo
    GRANT EXECUTE ON FUNCTIONS TO rmhpgflexadmin;

-- --------------------------------------
-- Public schema (for PostGIS functions)
-- --------------------------------------

-- Grant usage on public schema for PostGIS extension functions
GRANT USAGE ON SCHEMA public TO rmhpgflexadmin;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO rmhpgflexadmin;
```

### Verify Permissions

```sql
-- Check schema privileges
SELECT
    n.nspname AS schema_name,
    has_schema_privilege('rmhpgflexadmin', n.nspname, 'USAGE') AS has_usage,
    has_schema_privilege('rmhpgflexadmin', n.nspname, 'CREATE') AS has_create
FROM pg_namespace n
WHERE n.nspname IN ('geo', 'public')
ORDER BY n.nspname;
```

Expected output:
```
 schema_name | has_usage | has_create
-------------+-----------+------------
 geo         | t         | t
 public      | t         | f
(2 rows)
```

**Note**: `has_create = t` for geo schema means the identity can create tables, but it CANNOT drop the schema because we did not grant `DROP` privilege.

---

## Step 5: Assign Identity to Azure Function App

### What This Does
- Attaches the managed identity to the Function App
- Allows the application code to acquire Azure AD tokens
- The application uses the Client ID to identify which identity to use

### Azure CLI Commands

```bash
# Get the full resource ID of the managed identity
IDENTITY_ID=$(az identity show \
    --name rmhpgflexadmin \
    --resource-group rmhazure_rg \
    --query id \
    --output tsv)

echo "Identity ID: $IDENTITY_ID"

# Assign the identity to the Function App
az functionapp identity assign \
    --name rmhazuregeoapi \
    --resource-group rmhazure_rg \
    --identities "$IDENTITY_ID"
```

### Configure Application Settings

```bash
az functionapp config appsettings set \
    --name rmhazuregeoapi \
    --resource-group rmhazure_rg \
    --settings \
        "USE_MANAGED_IDENTITY=true" \
        "MANAGED_IDENTITY_CLIENT_ID=a533cb80-a590-4fad-8e52-1eb1f72659d7" \
        "MANAGED_IDENTITY_NAME=rmhpgflexadmin" \
        "BUSINESS_DB_HOST=rmhpgflex.postgres.database.azure.com" \
        "BUSINESS_DB_NAME=ddhgeodb" \
        "BUSINESS_DB_SCHEMA=geo"
```

### Setting Explanations

| Setting | Value | Purpose |
|---------|-------|---------|
| `USE_MANAGED_IDENTITY` | `true` | Enable token-based authentication |
| `MANAGED_IDENTITY_CLIENT_ID` | `a533cb80-...` | Which identity to use for tokens |
| `MANAGED_IDENTITY_NAME` | `rmhpgflexadmin` | PostgreSQL username (must match) |
| `BUSINESS_DB_HOST` | `rmhpgflex...` | Business database server |
| `BUSINESS_DB_NAME` | `ddhgeodb` | Business database name |
| `BUSINESS_DB_SCHEMA` | `geo` | Schema for ETL data |

---

## Troubleshooting

### Error: "function pgaadauth_create_principal does not exist"

**Cause**: You are connected to the wrong database.

**Solution**: Connect to the `postgres` database, not `geopgflex`:

```bash
# Wrong
PGPASSWORD="$TOKEN" psql -h ... -d geopgflex

# Correct
PGPASSWORD="$TOKEN" psql -h ... -d postgres
```

### Error: "role rmhpgflexadmin already exists"

**Cause**: The role was already created previously.

**Solution**: This is OK - skip to the GRANT statements.

### Error: "permission denied for schema"

**Cause**: You are not connected as the schema owner.

**Solution**: Connect as `rob634` (or whoever owns the schema) to run GRANT statements.

### Error: "password authentication failed"

**Cause**: Using wrong authentication method.

**Solution**: For managed identity users, use Azure AD token as password:

```bash
TOKEN=$(az account get-access-token --resource-type oss-rdbms --query accessToken --output tsv)
PGPASSWORD="$TOKEN" psql -h ... -U "rmhpgflexadmin" -d geopgflex
```

---

## Summary Checklist

### For Database Team

- [ ] **Step 1**: Create managed identity user on `postgres` database
- [ ] **Step 2**: Grant full privileges on `geopgflex` database
- [ ] **Step 3**: Create `ddhgeodb` database and enable PostGIS
- [ ] **Step 4**: Grant restricted CRUD privileges on `ddhgeodb` database

### For Cloud Team

- [ ] **Step 5a**: Assign managed identity to Function App
- [ ] **Step 5b**: Configure application settings

### Verification

- [ ] User `rmhpgflexadmin` exists in PostgreSQL
- [ ] User can connect to both databases
- [ ] User can DROP SCHEMA on `geopgflex` (test with empty schema)
- [ ] User CANNOT DROP SCHEMA on `ddhgeodb` (should get permission denied)

---

## Contact

For questions about this setup:
- **Application**: Robert Harrison
- **Azure Resources**: rmhazure_rg resource group

---

## Quick Reference: Connection Strings

### App Database (geopgflex)
```
host=rmhpgflex.postgres.database.azure.com
port=5432
dbname=geopgflex
user=rmhpgflexadmin
sslmode=require
```

### Business Database (ddhgeodb)
```
host=rmhpgflex.postgres.database.azure.com
port=5432
dbname=ddhgeodb
user=rmhpgflexadmin
sslmode=require
```

**Note**: Password is an Azure AD token acquired using the Client ID: `a533cb80-a590-4fad-8e52-1eb1f72659d7`
