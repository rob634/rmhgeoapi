# UAT Environment: eService Request Templates

**Created**: 20 JAN 2026
**Project**: Geospatial ETL Platform
**Environment**: UAT
**Based On**: QA deployment experience

---

## Table of Contents

1. [Request Summary](#request-summary)
2. [Request 1: Resource Group Creation](#request-1-resource-group-creation)
3. [Request 2: PostgreSQL Flexible Servers](#request-2-postgresql-flexible-servers)
4. [Request 3: Storage Accounts](#request-3-storage-accounts)
5. [Request 4: Service Bus Namespace](#request-4-service-bus-namespace)
6. [Request 5: Managed Identity Creation](#request-5-managed-identity-creation)
7. [Request 6: RBAC Role Assignments](#request-6-rbac-role-assignments)
8. [Request 7: PostgreSQL Configuration - Internal](#request-7-postgresql-configuration---internal)
9. [Request 8: PostgreSQL Configuration - External](#request-8-postgresql-configuration---external)
10. [Request 9: App Service Environment](#request-9-app-service-environment)
11. [Request 10: Container Apps Environment](#request-10-container-apps-environment)
12. [Request 11: Azure Data Factory](#request-11-azure-data-factory)
13. [Request 12: Application Insights](#request-12-application-insights)
14. [Post-Deployment Requests](#post-deployment-requests)
15. [Verification Queries](#verification-queries)
16. [Troubleshooting Reference](#troubleshooting-reference)

---

## Request Summary

| # | Request Type | Resources | Dependencies | Priority |
|---|--------------|-----------|--------------|----------|
| 1 | Resource Groups | 2 RGs | None | P1 - First |
| 2 | PostgreSQL Servers | 2 servers + databases | RG creation | P1 |
| 3 | Storage Accounts | 3 accounts | RG creation | P1 |
| 4 | Service Bus | 1 namespace + 3 queues | RG creation | P1 |
| 5 | Managed Identities | 4 UMIs | RG creation | P1 |
| 6 | RBAC Assignments | Storage + Service Bus | MI creation, Storage creation | P2 |
| 7 | PostgreSQL Config (Internal) | Extensions, users, roles | PG server, MIs exist | P2 |
| 8 | PostgreSQL Config (External) | Extensions, users, roles | PG server, MIs exist | P2 |
| 9 | App Service Environment | ASE + App Service Plan | RG, VNet | P2 |
| 10 | Container Apps Environment | CAE | RG | P2 |
| 11 | Azure Data Factory | ADF instance | RG, MIs | P3 |
| 12 | Application Insights | 2 AI instances | RG | P2 |
| PD-1 | Post-Schema Reader Grants | SQL grants | Schemas created by app | P4 - Last |

**Estimated Total Requests**: 8-12 eService tickets (depending on bundling)

---

## Request 1: Resource Group Creation

**Title**: Create Resource Groups for Geospatial UAT Environment

### Requested Resources

| Resource Group Name | Location | Purpose |
|---------------------|----------|---------|
| `rg-geoetl-uat-internal` | East US | ETL pipelines + Internal Service Layer |
| `rg-geoetl-uat-external` | East US | External Service Layer (airgapped) |

### Azure CLI (Reference)

```bash
az group create --name rg-geoetl-uat-internal --location eastus
az group create --name rg-geoetl-uat-external --location eastus
```

### Tags (Apply to Both)

| Tag | Value |
|-----|-------|
| Environment | UAT |
| Project | GeoETL |
| CostCenter | [YOUR_COST_CENTER] |
| Owner | [YOUR_EMAIL] |

---

## Request 2: PostgreSQL Flexible Servers

**Title**: Create PostgreSQL Flexible Servers for Geospatial UAT

### Server 1: Internal Database

| Property | Value |
|----------|-------|
| Server Name | `pg-geoetl-uat-internal` |
| Resource Group | `rg-geoetl-uat-internal` |
| Location | East US |
| PostgreSQL Version | 16 |
| SKU | Standard_D4s_v3 (4 vCores, 16 GB RAM) |
| Storage | 128 GB |
| Backup Retention | 7 days |
| Geo-Redundant Backup | No |
| High Availability | Zone redundant (optional) |

### Server 2: External Database

| Property | Value |
|----------|-------|
| Server Name | `pg-geoetl-uat-external` |
| Resource Group | `rg-geoetl-uat-external` |
| Location | East US |
| PostgreSQL Version | 16 |
| SKU | Standard_D2s_v3 (2 vCores, 8 GB RAM) |
| Storage | 64 GB |
| Backup Retention | 7 days |
| Geo-Redundant Backup | No |

### Configuration Required for Both Servers

#### 2a. Enable Azure AD Authentication

| Setting | Value |
|---------|-------|
| Azure AD Admin | [YOUR_AAD_ADMIN_UPN] |
| Azure AD Admin Object ID | [YOUR_AAD_ADMIN_OBJECT_ID] |

#### 2b. Firewall Rules

| Rule Name | Start IP | End IP | Purpose |
|-----------|----------|--------|---------|
| AllowAzureServices | 0.0.0.0 | 0.0.0.0 | Allow Azure PaaS services |

#### 2c. Server Parameters (azure.extensions)

**CRITICAL**: These extensions must be allowlisted before CREATE EXTENSION can run.

Navigate to: Azure Portal → PostgreSQL Server → Server Parameters → `azure.extensions`

Set value to:
```
btree_gin,btree_gist,hstore,pgcrypto,pg_trgm,plpgsql,postgis,postgis_topology,unaccent,uuid-ossp
```

#### 2d. Create Databases

| Server | Database Name |
|--------|---------------|
| pg-geoetl-uat-internal | `geoetldb` |
| pg-geoetl-uat-external | `geoetldb` |

### Azure CLI (Reference)

```bash
# Internal Server
az postgres flexible-server create \
  --resource-group rg-geoetl-uat-internal \
  --name pg-geoetl-uat-internal \
  --location eastus \
  --sku-name Standard_D4s_v3 \
  --storage-size 128 \
  --version 16 \
  --admin-user pgadmin \
  --admin-password '<SECURE_PASSWORD>' \
  --yes

# Enable Azure AD auth
az postgres flexible-server ad-admin create \
  --resource-group rg-geoetl-uat-internal \
  --server-name pg-geoetl-uat-internal \
  --display-name "AzureAD Admin" \
  --object-id <YOUR_AAD_ADMIN_OBJECT_ID> \
  --type User

# Firewall
az postgres flexible-server firewall-rule create \
  --resource-group rg-geoetl-uat-internal \
  --name pg-geoetl-uat-internal \
  --rule-name AllowAzureServices \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0

# Extensions
az postgres flexible-server parameter set \
  --resource-group rg-geoetl-uat-internal \
  --server-name pg-geoetl-uat-internal \
  --name azure.extensions \
  --value "POSTGIS,UUID-OSSP,PG_TRGM,BTREE_GIN,BTREE_GIST,HSTORE,PGCRYPTO,UNACCENT"
```

---

## Request 3: Storage Accounts

**Title**: Create Storage Accounts for Geospatial UAT

### Storage Account Details

| Account Name | Resource Group | Purpose | SKU |
|--------------|---------------|---------|-----|
| `stageoetluatbronze` | rg-geoetl-uat-internal | Raw data (ETL input) | Standard_LRS |
| `stageoetluatsilver` | rg-geoetl-uat-internal | Processed COGs (ETL output) | Standard_LRS |
| `stageoetluatexternal` | rg-geoetl-uat-external | Airgapped data (External Service Layer) | Standard_LRS |

### Configuration for All Accounts

| Setting | Value |
|---------|-------|
| Kind | StorageV2 |
| Performance | Standard |
| Replication | LRS |
| Allow Blob Public Access | **Disabled** |
| Minimum TLS Version | TLS 1.2 |
| Hierarchical Namespace | Disabled |

### Containers to Create

#### Bronze Storage (`stageoetluatbronze`)

| Container | Purpose |
|-----------|---------|
| `bronze-vectors` | Raw vector data (GeoJSON, Shapefile, etc.) |
| `bronze-rasters` | Raw raster data (GeoTIFF, NetCDF, etc.) |
| `bronze-misc` | Other input files |
| `bronze-temp` | Temporary processing |

#### Silver Storage (`stageoetluatsilver`)

| Container | Purpose |
|-----------|---------|
| `silver-cogs` | Cloud-Optimized GeoTIFFs |
| `silver-vectors` | Processed vector data |
| `silver-tiles` | Pre-rendered tiles |
| `silver-temp` | Temporary processing |
| `pickles` | Serialized Python objects |

#### External Storage (`stageoetluatexternal`)

| Container | Purpose |
|-----------|---------|
| `cogs` | Promoted COGs from Silver |
| `vectors` | Promoted vectors from Silver |
| `tiles` | Promoted tiles from Silver |

### CORS Configuration (Silver + External only)

| Setting | Value |
|---------|-------|
| Allowed Origins | `*` |
| Allowed Methods | GET, HEAD, OPTIONS |
| Allowed Headers | `*` |
| Exposed Headers | `*` |
| Max Age | 3600 |

### Azure CLI (Reference)

```bash
# Bronze
az storage account create \
  --resource-group rg-geoetl-uat-internal \
  --name stageoetluatbronze \
  --location eastus \
  --sku Standard_LRS \
  --kind StorageV2 \
  --allow-blob-public-access false

# Create containers
az storage container create --account-name stageoetluatbronze --name bronze-vectors --auth-mode login
az storage container create --account-name stageoetluatbronze --name bronze-rasters --auth-mode login
az storage container create --account-name stageoetluatbronze --name bronze-misc --auth-mode login
az storage container create --account-name stageoetluatbronze --name bronze-temp --auth-mode login
```

---

## Request 4: Service Bus Namespace

**Title**: Create Service Bus Namespace for Geospatial UAT

### Namespace Details

| Property | Value |
|----------|-------|
| Namespace Name | `sb-geoetl-uat` |
| Resource Group | `rg-geoetl-uat-internal` |
| Location | East US |
| SKU | Standard |

### Queues to Create

**CRITICAL**: `maxDeliveryCount` MUST be **1** — retries are handled by CoreMachine, not Service Bus.

| Queue Name | Lock Duration | Max Delivery Count | TTL | Purpose |
|------------|--------------|-------------------|-----|---------|
| `geospatial-jobs` | 5 minutes | **1** | 14 days | Platform → Orchestrator |
| `function-tasks` | 5 minutes | **1** | 14 days | Orchestrator → Function Worker |
| `docker-tasks` | 5 minutes | **1** | 14 days | Orchestrator → Docker Worker |

### Azure CLI (Reference)

```bash
# Create namespace
az servicebus namespace create \
  --resource-group rg-geoetl-uat-internal \
  --name sb-geoetl-uat \
  --location eastus \
  --sku Standard

# Create queues (CRITICAL: max-delivery-count=1)
az servicebus queue create \
  --resource-group rg-geoetl-uat-internal \
  --namespace-name sb-geoetl-uat \
  --name geospatial-jobs \
  --lock-duration PT5M \
  --max-delivery-count 1 \
  --default-message-time-to-live P14D

az servicebus queue create \
  --resource-group rg-geoetl-uat-internal \
  --namespace-name sb-geoetl-uat \
  --name function-tasks \
  --lock-duration PT5M \
  --max-delivery-count 1 \
  --default-message-time-to-live P14D

az servicebus queue create \
  --resource-group rg-geoetl-uat-internal \
  --namespace-name sb-geoetl-uat \
  --name docker-tasks \
  --lock-duration PT5M \
  --max-delivery-count 1 \
  --default-message-time-to-live P14D
```

### Verification

```bash
for QUEUE in geospatial-jobs function-tasks docker-tasks; do
  az servicebus queue show \
    --resource-group rg-geoetl-uat-internal \
    --namespace-name sb-geoetl-uat \
    --name $QUEUE \
    --query "{name:name, maxDeliveryCount:maxDeliveryCount}" -o table
done
# ALL must show maxDeliveryCount = 1
```

---

## Request 5: Managed Identity Creation

**Title**: Create User-Assigned Managed Identities for Geospatial UAT

### Identity Details

| Identity Name | Resource Group | Purpose |
|---------------|---------------|---------|
| `mi-geoetl-uat-internal-db-admin` | rg-geoetl-uat-internal | ETL pipeline apps (write access) |
| `mi-geoetl-uat-internal-db-reader` | rg-geoetl-uat-internal | Internal Service Layer (read-only) |
| `mi-geoetl-uat-external-db-admin` | rg-geoetl-uat-external | Azure Data Factory (write to External) |
| `mi-geoetl-uat-external-db-reader` | rg-geoetl-uat-external | External Service Layer (read-only) |

### Azure CLI (Reference)

```bash
# Internal identities
az identity create \
  --resource-group rg-geoetl-uat-internal \
  --name mi-geoetl-uat-internal-db-admin

az identity create \
  --resource-group rg-geoetl-uat-internal \
  --name mi-geoetl-uat-internal-db-reader

# External identities
az identity create \
  --resource-group rg-geoetl-uat-external \
  --name mi-geoetl-uat-external-db-admin

az identity create \
  --resource-group rg-geoetl-uat-external \
  --name mi-geoetl-uat-external-db-reader
```

### Capture Identity Details (Required for Later Steps)

```bash
# Get all identity details - SAVE THESE VALUES
for MI in mi-geoetl-uat-internal-db-admin mi-geoetl-uat-internal-db-reader; do
  echo "=== $MI ==="
  az identity show --resource-group rg-geoetl-uat-internal --name $MI \
    --query "{name:name, clientId:clientId, principalId:principalId, id:id}" -o table
done

for MI in mi-geoetl-uat-external-db-admin mi-geoetl-uat-external-db-reader; do
  echo "=== $MI ==="
  az identity show --resource-group rg-geoetl-uat-external --name $MI \
    --query "{name:name, clientId:clientId, principalId:principalId, id:id}" -o table
done
```

**Record the following for each identity**:

| Identity | Client ID | Principal ID | Resource ID |
|----------|-----------|--------------|-------------|
| mi-geoetl-uat-internal-db-admin | `________` | `________` | `________` |
| mi-geoetl-uat-internal-db-reader | `________` | `________` | `________` |
| mi-geoetl-uat-external-db-admin | `________` | `________` | `________` |
| mi-geoetl-uat-external-db-reader | `________` | `________` | `________` |

---

## Request 6: RBAC Role Assignments

**Title**: Assign RBAC Roles to Managed Identities for Geospatial UAT

**Prerequisite**: Managed identities and storage accounts must exist.

### Storage RBAC Assignments

| Identity | Storage Account | Role | Scope |
|----------|----------------|------|-------|
| mi-geoetl-uat-internal-db-admin | stageoetluatbronze | Storage Blob Data Contributor | Account |
| mi-geoetl-uat-internal-db-admin | stageoetluatsilver | Storage Blob Data Contributor | Account |
| mi-geoetl-uat-internal-db-reader | stageoetluatsilver | Storage Blob Data Reader | Account |
| mi-geoetl-uat-external-db-admin | stageoetluatexternal | Storage Blob Data Contributor | Account |
| mi-geoetl-uat-external-db-reader | stageoetluatexternal | Storage Blob Data Reader | Account |

### Service Bus RBAC Assignments

| Identity | Service Bus | Role | Scope |
|----------|-------------|------|-------|
| mi-geoetl-uat-internal-db-admin | sb-geoetl-uat | Azure Service Bus Data Owner | Namespace |

### Azure CLI (Reference)

```bash
# Get Principal IDs
INTERNAL_ADMIN_PRINCIPAL=$(az identity show --resource-group rg-geoetl-uat-internal \
  --name mi-geoetl-uat-internal-db-admin --query principalId -o tsv)

INTERNAL_READER_PRINCIPAL=$(az identity show --resource-group rg-geoetl-uat-internal \
  --name mi-geoetl-uat-internal-db-reader --query principalId -o tsv)

EXTERNAL_ADMIN_PRINCIPAL=$(az identity show --resource-group rg-geoetl-uat-external \
  --name mi-geoetl-uat-external-db-admin --query principalId -o tsv)

EXTERNAL_READER_PRINCIPAL=$(az identity show --resource-group rg-geoetl-uat-external \
  --name mi-geoetl-uat-external-db-reader --query principalId -o tsv)

# Storage assignments
az role assignment create \
  --role "Storage Blob Data Contributor" \
  --assignee $INTERNAL_ADMIN_PRINCIPAL \
  --scope /subscriptions/<SUB_ID>/resourceGroups/rg-geoetl-uat-internal/providers/Microsoft.Storage/storageAccounts/stageoetluatbronze

az role assignment create \
  --role "Storage Blob Data Contributor" \
  --assignee $INTERNAL_ADMIN_PRINCIPAL \
  --scope /subscriptions/<SUB_ID>/resourceGroups/rg-geoetl-uat-internal/providers/Microsoft.Storage/storageAccounts/stageoetluatsilver

az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee $INTERNAL_READER_PRINCIPAL \
  --scope /subscriptions/<SUB_ID>/resourceGroups/rg-geoetl-uat-internal/providers/Microsoft.Storage/storageAccounts/stageoetluatsilver

az role assignment create \
  --role "Storage Blob Data Contributor" \
  --assignee $EXTERNAL_ADMIN_PRINCIPAL \
  --scope /subscriptions/<SUB_ID>/resourceGroups/rg-geoetl-uat-external/providers/Microsoft.Storage/storageAccounts/stageoetluatexternal

az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee $EXTERNAL_READER_PRINCIPAL \
  --scope /subscriptions/<SUB_ID>/resourceGroups/rg-geoetl-uat-external/providers/Microsoft.Storage/storageAccounts/stageoetluatexternal

# Service Bus assignment
az role assignment create \
  --role "Azure Service Bus Data Owner" \
  --assignee $INTERNAL_ADMIN_PRINCIPAL \
  --scope /subscriptions/<SUB_ID>/resourceGroups/rg-geoetl-uat-internal/providers/Microsoft.ServiceBus/namespaces/sb-geoetl-uat
```

---

## Request 7: PostgreSQL Configuration - Internal

**Title**: PostgreSQL Setup for Internal Database - Extensions, Users, and PGSTAC Roles

**Prerequisites**:
1. PostgreSQL server `pg-geoetl-uat-internal` exists
2. Database `geoetldb` exists
3. Extensions allowlisted in server parameters
4. Managed identities `mi-geoetl-uat-internal-db-admin` and `mi-geoetl-uat-internal-db-reader` exist in Azure

### Part 1: Install Extensions

**Run as**: `azure_pg_admin`
**Connect to**: `geoetldb` on `pg-geoetl-uat-internal`

```sql
-- ============================================================
-- INSTALL POSTGRESQL EXTENSIONS
-- ============================================================
-- These must be allowlisted in azure.extensions server parameter first

CREATE EXTENSION IF NOT EXISTS btree_gin;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS hstore;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Verification
SELECT extname, extversion FROM pg_extension ORDER BY extname;
-- Expected: 9 extensions listed
SELECT PostGIS_Version();
-- Expected: Returns PostGIS version string
```

### Part 2: Create Admin Database User

**CRITICAL**: The managed identity MUST exist in Azure BEFORE running `pgaadauth_create_principal`.

```sql
-- ============================================================
-- CREATE ADMIN USER (mi-geoetl-uat-internal-db-admin)
-- ============================================================
-- This identity is used by: Platform, Orchestrator, Function Worker, Docker Worker

-- Step 2a: Create Entra-authenticated user
-- NEVER use CREATE ROLE for managed identities!
SELECT * FROM pgaadauth_create_principal('mi-geoetl-uat-internal-db-admin', false, false);

-- Step 2b: Grant database-level privileges
GRANT CONNECT ON DATABASE geoetldb TO "mi-geoetl-uat-internal-db-admin";
GRANT CREATE ON DATABASE geoetldb TO "mi-geoetl-uat-internal-db-admin";

-- Step 2c: Grant public schema access (for PostGIS functions)
GRANT USAGE ON SCHEMA public TO "mi-geoetl-uat-internal-db-admin";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO "mi-geoetl-uat-internal-db-admin";
```

### Part 3: Create PGSTAC Application Roles

```sql
-- ============================================================
-- CREATE PGSTAC ROLES
-- ============================================================
-- These are non-login roles for permission grouping

CREATE ROLE pgstac_admin;
CREATE ROLE pgstac_ingest;
CREATE ROLE pgstac_read;

-- Grant to admin WITH ADMIN OPTION (allows admin to grant to others)
GRANT pgstac_admin TO "mi-geoetl-uat-internal-db-admin" WITH ADMIN OPTION;
GRANT pgstac_ingest TO "mi-geoetl-uat-internal-db-admin" WITH ADMIN OPTION;
GRANT pgstac_read TO "mi-geoetl-uat-internal-db-admin" WITH ADMIN OPTION;

-- Verification
SELECT r.rolname AS role_name, m.rolname AS granted_to, am.admin_option
FROM pg_auth_members am
JOIN pg_roles r ON am.roleid = r.oid
JOIN pg_roles m ON am.member = m.oid
WHERE r.rolname IN ('pgstac_admin', 'pgstac_ingest', 'pgstac_read')
  AND m.rolname = 'mi-geoetl-uat-internal-db-admin';
-- Expected: 3 rows, all with admin_option = true
```

### Part 4: Create Reader Database User

```sql
-- ============================================================
-- CREATE READER USER (mi-geoetl-uat-internal-db-reader)
-- ============================================================
-- This identity is used by: Internal Service Layer (TiTiler, TiPG, STAC API)

-- Step 4a: Create Entra-authenticated user
SELECT * FROM pgaadauth_create_principal('mi-geoetl-uat-internal-db-reader', false, false);

-- Step 4b: Grant connect
GRANT CONNECT ON DATABASE geoetldb TO "mi-geoetl-uat-internal-db-reader";

-- NOTE: Schema-level grants (USAGE, SELECT) applied AFTER schemas are created
-- See "Post-Deployment Requests" section
```

### Part 5: Verification Queries

```sql
-- ============================================================
-- VERIFICATION QUERIES
-- ============================================================

-- 1. Verify roles exist
SELECT rolname, rolcanlogin, rolcreaterole, rolcreatedb
FROM pg_roles
WHERE rolname IN ('mi-geoetl-uat-internal-db-admin', 'mi-geoetl-uat-internal-db-reader',
                  'pgstac_admin', 'pgstac_ingest', 'pgstac_read')
ORDER BY rolname;
-- Expected: 5 rows
-- Admin/Reader: rolcanlogin = true
-- pgstac_*: rolcanlogin = false

-- 2. Verify Entra authentication configured
SELECT rolname, principaltype, objectid
FROM pgaadauth_list_principals()
WHERE rolname IN ('mi-geoetl-uat-internal-db-admin', 'mi-geoetl-uat-internal-db-reader');
-- Expected: 2 rows with Object IDs
-- If empty: Role exists but NOT configured for Entra auth!

-- 3. Verify CREATE privilege
SELECT has_database_privilege('mi-geoetl-uat-internal-db-admin', 'geoetldb', 'CREATE');
-- Expected: true
```

---

## Request 8: PostgreSQL Configuration - External

**Title**: PostgreSQL Setup for External Database - Extensions, Users, and Roles

**Prerequisites**:
1. PostgreSQL server `pg-geoetl-uat-external` exists
2. Database `geoetldb` exists
3. Extensions allowlisted in server parameters
4. Managed identities `mi-geoetl-uat-external-db-admin` and `mi-geoetl-uat-external-db-reader` exist in Azure

### Part 1: Install Extensions

**Run as**: `azure_pg_admin`
**Connect to**: `geoetldb` on `pg-geoetl-uat-external`

```sql
-- ============================================================
-- INSTALL POSTGRESQL EXTENSIONS (subset for external)
-- ============================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Verification
SELECT extname, extversion FROM pg_extension ORDER BY extname;
SELECT PostGIS_Version();
```

### Part 2: Create Admin Database User

```sql
-- ============================================================
-- CREATE ADMIN USER (mi-geoetl-uat-external-db-admin)
-- ============================================================
-- This identity is used by: Azure Data Factory

SELECT * FROM pgaadauth_create_principal('mi-geoetl-uat-external-db-admin', false, false);

GRANT CONNECT ON DATABASE geoetldb TO "mi-geoetl-uat-external-db-admin";
GRANT CREATE ON DATABASE geoetldb TO "mi-geoetl-uat-external-db-admin";
GRANT USAGE ON SCHEMA public TO "mi-geoetl-uat-external-db-admin";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO "mi-geoetl-uat-external-db-admin";
```

### Part 3: Create Reader Database User

```sql
-- ============================================================
-- CREATE READER USER (mi-geoetl-uat-external-db-reader)
-- ============================================================
-- This identity is used by: External Service Layer

SELECT * FROM pgaadauth_create_principal('mi-geoetl-uat-external-db-reader', false, false);

GRANT CONNECT ON DATABASE geoetldb TO "mi-geoetl-uat-external-db-reader";

-- NOTE: Schema-level grants applied AFTER ADF creates schemas
-- See "Post-Deployment Requests" section
```

### Part 4: Verification

```sql
-- Verify Entra authentication configured
SELECT rolname, principaltype, objectid
FROM pgaadauth_list_principals()
WHERE rolname IN ('mi-geoetl-uat-external-db-admin', 'mi-geoetl-uat-external-db-reader');
-- Expected: 2 rows with Object IDs
```

---

## Request 9: App Service Environment

**Title**: Create App Service Environment for Service Layer Docker Apps

### ASE Details

| Property | Value |
|----------|-------|
| ASE Name | `ase-geoetl-uat` |
| Resource Group | `rg-geoetl-uat-internal` |
| Location | East US |
| ASE Version | ASEv3 |
| VNet | [SPECIFY_VNET_NAME] |
| Subnet | [SPECIFY_SUBNET_NAME] |

### App Service Plan in ASE

| Property | Value |
|----------|-------|
| Plan Name | `asp-servicelayer-uat` |
| SKU | I1V2 (Isolated V2) |
| OS | Linux |
| Zone Redundancy | Optional |

**Note**: ASE creation typically requires VNet configuration and may need to be done via Azure Portal or ARM template.

---

## Request 10: Container Apps Environment

**Title**: Create Container Apps Environment for Docker Worker

### Environment Details

| Property | Value |
|----------|-------|
| Environment Name | `cae-geoetl-uat` |
| Resource Group | `rg-geoetl-uat-internal` |
| Location | East US |
| Log Analytics | Create new or use existing |

### Azure CLI (Reference)

```bash
az containerapp env create \
  --resource-group rg-geoetl-uat-internal \
  --name cae-geoetl-uat \
  --location eastus
```

---

## Request 11: Azure Data Factory

**Title**: Create Azure Data Factory for Silver → External Data Promotion

### ADF Details

| Property | Value |
|----------|-------|
| Factory Name | `adf-geoetl-uat` |
| Resource Group | `rg-geoetl-uat-internal` |
| Location | East US |
| Git Integration | Optional (ADO or GitHub) |

### RBAC for ADF System Identity

After ADF is created, grant its system-assigned managed identity:

| Resource | Role |
|----------|------|
| stageoetluatsilver (Internal Silver) | Storage Blob Data Reader |
| stageoetluatexternal (External) | Storage Blob Data Contributor |

### Azure CLI (Reference)

```bash
# Create ADF
az datafactory create \
  --resource-group rg-geoetl-uat-internal \
  --factory-name adf-geoetl-uat \
  --location eastus

# Get ADF system identity principal ID
ADF_PRINCIPAL=$(az datafactory show --resource-group rg-geoetl-uat-internal \
  --factory-name adf-geoetl-uat --query identity.principalId -o tsv)

# Grant storage access
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee $ADF_PRINCIPAL \
  --scope /subscriptions/<SUB_ID>/resourceGroups/rg-geoetl-uat-internal/providers/Microsoft.Storage/storageAccounts/stageoetluatsilver

az role assignment create \
  --role "Storage Blob Data Contributor" \
  --assignee $ADF_PRINCIPAL \
  --scope /subscriptions/<SUB_ID>/resourceGroups/rg-geoetl-uat-external/providers/Microsoft.Storage/storageAccounts/stageoetluatexternal
```

---

## Request 12: Application Insights

**Title**: Create Application Insights for Monitoring

### Application Insights Details

| Instance Name | Resource Group | Purpose |
|---------------|---------------|---------|
| `ai-geoetl-uat-internal` | rg-geoetl-uat-internal | ETL + Internal Service Layer |
| `ai-geoetl-uat-external` | rg-geoetl-uat-external | External Service Layer |

### Azure CLI (Reference)

```bash
az monitor app-insights component create \
  --resource-group rg-geoetl-uat-internal \
  --app ai-geoetl-uat-internal \
  --location eastus \
  --kind web \
  --application-type web

az monitor app-insights component create \
  --resource-group rg-geoetl-uat-external \
  --app ai-geoetl-uat-external \
  --location eastus \
  --kind web \
  --application-type web
```

---

## Post-Deployment Requests

These requests are submitted AFTER the application creates schemas.

### PD-1: Internal Reader Schema Grants

**Title**: Grant Read Access to Internal Database Schemas for Service Layer

**Prerequisite**: Orchestrator app has run `action=ensure` to create schemas.

**Run as**: `azure_pg_admin`
**Connect to**: `geoetldb` on `pg-geoetl-uat-internal`

```sql
-- ============================================================
-- GRANT READER ACCESS TO SCHEMAS
-- Run AFTER app creates geo, pgstac schemas
-- ============================================================

-- Grant schema usage
GRANT USAGE ON SCHEMA geo TO "mi-geoetl-uat-internal-db-reader";
GRANT USAGE ON SCHEMA pgstac TO "mi-geoetl-uat-internal-db-reader";

-- Grant SELECT on existing tables
GRANT SELECT ON ALL TABLES IN SCHEMA geo TO "mi-geoetl-uat-internal-db-reader";
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO "mi-geoetl-uat-internal-db-reader";

-- Grant EXECUTE on pgstac functions (required for STAC API queries)
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pgstac TO "mi-geoetl-uat-internal-db-reader";

-- Grant for FUTURE tables/functions created by admin
ALTER DEFAULT PRIVILEGES FOR ROLE "mi-geoetl-uat-internal-db-admin" IN SCHEMA geo
  GRANT SELECT ON TABLES TO "mi-geoetl-uat-internal-db-reader";

ALTER DEFAULT PRIVILEGES FOR ROLE "mi-geoetl-uat-internal-db-admin" IN SCHEMA pgstac
  GRANT SELECT ON TABLES TO "mi-geoetl-uat-internal-db-reader";

ALTER DEFAULT PRIVILEGES FOR ROLE "mi-geoetl-uat-internal-db-admin" IN SCHEMA pgstac
  GRANT EXECUTE ON FUNCTIONS TO "mi-geoetl-uat-internal-db-reader";

-- NO access to app schema for reader (intentional)
```

### PD-2: External Reader Schema Grants

**Title**: Grant Read Access to External Database Schemas for External Service Layer

**Prerequisite**: ADF has promoted data and created schemas.

**Run as**: `azure_pg_admin`
**Connect to**: `geoetldb` on `pg-geoetl-uat-external`

```sql
-- ============================================================
-- GRANT READER ACCESS TO EXTERNAL SCHEMAS
-- Run AFTER ADF creates geo, pgstac schemas
-- ============================================================

-- Grant schema usage
GRANT USAGE ON SCHEMA geo TO "mi-geoetl-uat-external-db-reader";
GRANT USAGE ON SCHEMA pgstac TO "mi-geoetl-uat-external-db-reader";

-- Grant SELECT on existing tables
GRANT SELECT ON ALL TABLES IN SCHEMA geo TO "mi-geoetl-uat-external-db-reader";
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO "mi-geoetl-uat-external-db-reader";

-- Grant EXECUTE on pgstac functions
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pgstac TO "mi-geoetl-uat-external-db-reader";

-- Grant for FUTURE tables/functions
ALTER DEFAULT PRIVILEGES FOR ROLE "mi-geoetl-uat-external-db-admin" IN SCHEMA geo
  GRANT SELECT ON TABLES TO "mi-geoetl-uat-external-db-reader";

ALTER DEFAULT PRIVILEGES FOR ROLE "mi-geoetl-uat-external-db-admin" IN SCHEMA pgstac
  GRANT SELECT ON TABLES TO "mi-geoetl-uat-external-db-reader";

ALTER DEFAULT PRIVILEGES FOR ROLE "mi-geoetl-uat-external-db-admin" IN SCHEMA pgstac
  GRANT EXECUTE ON FUNCTIONS TO "mi-geoetl-uat-external-db-reader";
```

---

## Verification Queries

Use these queries to verify the configuration is correct.

### Extensions Verification

```sql
SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('postgis', 'postgis_topology', 'hstore', 'pgcrypto',
                  'pg_trgm', 'btree_gin', 'btree_gist', 'unaccent', 'uuid-ossp')
ORDER BY extname;
-- Internal: Expected 9 rows
-- External: Expected 2 rows (postgis, uuid-ossp)
```

### Role Verification

```sql
-- Check roles exist
SELECT rolname, rolcanlogin, rolcreaterole, rolcreatedb
FROM pg_roles
WHERE rolname LIKE 'mi-geoetl-uat%' OR rolname LIKE 'pgstac_%'
ORDER BY rolname;

-- Check Entra auth configured
SELECT rolname, principaltype, objectid
FROM pgaadauth_list_principals()
WHERE rolname LIKE 'mi-geoetl-uat%';
```

### Permission Verification

```sql
-- Check CREATE privilege
SELECT has_database_privilege('mi-geoetl-uat-internal-db-admin', current_database(), 'CREATE');

-- Check schema permissions (after schemas exist)
SELECT nspname AS schema,
  pg_catalog.has_schema_privilege('mi-geoetl-uat-internal-db-admin', nspname, 'CREATE') AS admin_create,
  pg_catalog.has_schema_privilege('mi-geoetl-uat-internal-db-reader', nspname, 'USAGE') AS reader_usage
FROM pg_namespace
WHERE nspname IN ('geo', 'pgstac', 'public')
ORDER BY nspname;
```

### PGSTAC Roles Verification

```sql
SELECT r.rolname AS role_name, m.rolname AS granted_to, am.admin_option
FROM pg_auth_members am
JOIN pg_roles r ON am.roleid = r.oid
JOIN pg_roles m ON am.member = m.oid
WHERE r.rolname IN ('pgstac_admin', 'pgstac_ingest', 'pgstac_read')
ORDER BY r.rolname, m.rolname;
```

---

## Troubleshooting Reference

### Error: 28P01 Password authentication failed

**Symptom**: Connection fails with `Password authentication failed for user "mi-geoetl-uat-..."`

**Root Cause**: Role was created with `CREATE ROLE` instead of `pgaadauth_create_principal`

**Diagnostic**:
```sql
SELECT * FROM pgaadauth_list_principals() WHERE rolname = 'mi-geoetl-uat-internal-db-admin';
-- If empty: Role exists but NOT configured for Entra auth
```

**Resolution**:
```sql
-- Drop incorrectly created role
DROP ROLE IF EXISTS "mi-geoetl-uat-internal-db-admin";

-- Recreate using Entra function
SELECT * FROM pgaadauth_create_principal('mi-geoetl-uat-internal-db-admin', false, false);

-- Re-apply all grants
```

### Error: Role does not exist

**Symptom**: `pgaadauth_create_principal` appears to succeed but auth still fails

**Root Cause**: Managed identity didn't exist in Azure when command was run

**Resolution**: Verify MI exists in Azure Portal, then re-run `pgaadauth_create_principal`

### Error: Permission denied for schema

**Symptom**: Queries fail with `permission denied for schema`

**Root Cause**: Missing `GRANT USAGE ON SCHEMA`

**Resolution**:
```sql
GRANT USAGE ON SCHEMA geo TO "mi-geoetl-uat-internal-db-reader";
GRANT USAGE ON SCHEMA pgstac TO "mi-geoetl-uat-internal-db-reader";
```

### Error: Duplicate task execution

**Symptom**: Same task runs multiple times

**Root Cause**: Service Bus queue `maxDeliveryCount` > 1

**Resolution**: Verify queue configuration:
```bash
az servicebus queue show --resource-group rg-geoetl-uat-internal \
  --namespace-name sb-geoetl-uat --name docker-tasks \
  --query maxDeliveryCount
# Must be 1
```

---

## Appendix: Naming Conventions

### Resource Naming Pattern

| Resource Type | Pattern | Example |
|---------------|---------|---------|
| Resource Group | `rg-{project}-{env}-{zone}` | `rg-geoetl-uat-internal` |
| PostgreSQL | `pg-{project}-{env}-{zone}` | `pg-geoetl-uat-internal` |
| Storage | `st{project}{env}{tier}` | `stageoetluatsilver` |
| Service Bus | `sb-{project}-{env}` | `sb-geoetl-uat` |
| Managed Identity | `mi-{project}-{env}-{zone}-{role}` | `mi-geoetl-uat-internal-db-admin` |
| Function App | `func-{role}-{env}` | `func-platform-uat` |
| Container App | `ca-{role}-{env}` | `ca-docker-worker-uat` |
| Web App | `app-{role}-{env}-{zone}` | `app-servicelayer-uat-internal` |

### Identity Role Summary

| Identity Suffix | Access Level | Used By |
|-----------------|--------------|---------|
| `-db-admin` | Read/Write database, Read/Write storage | ETL apps, ADF |
| `-db-reader` | Read-only database, Read-only storage | Service Layer apps |

---

**Document Version**: 1.0
**Last Updated**: 20 JAN 2026
**Based On**: QA deployment experience
