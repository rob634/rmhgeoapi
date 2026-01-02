# Azure Blob Storage Setup and Configuration Guide

> **Navigation**: [Quick Start](WIKI_QUICK_START.md) | [Platform API](WIKI_PLATFORM_API.md) | [All Jobs](WIKI_API_JOB_SUBMISSION.md) | [Errors](WIKI_API_ERRORS.md) | [Glossary](WIKI_API_GLOSSARY.md)

**Date**: 29 DEC 2025
**Status**: Reference Documentation
**Wiki**: Azure DevOps Wiki - Storage configuration documentation
**Purpose**: Developer guide for configuring Azure Blob Storage in the geospatial ETL pipeline
**Audience**: Developers setting up or maintaining storage infrastructure

---

## Purpose

This document provides setup and configuration instructions for Azure Blob Storage used by the geospatial ETL pipeline. Storage is organized into three tiers:

- **Bronze**: Raw data uploaded by users (input)
- **Silver**: Processed data (COGs, validated vectors)
- **Gold**: Final exports (GeoParquet, aggregated data) - Future

---

## Table of Contents

1. [Storage Architecture](#storage-architecture)
2. [Component Details](#component-details)
3. [Setup Instructions](#setup-instructions)
4. [Container Configuration](#container-configuration)
5. [Access Configuration](#access-configuration)
6. [SAS Token Management](#sas-token-management)
7. [Troubleshooting](#troubleshooting)

---

## Storage Architecture

### Data Lake Pattern

The platform uses a medallion architecture (Bronze/Silver/Gold) for data organization. See [Glossary: Data Storage Terms](WIKI_API_GLOSSARY.md#data-storage-terms) for tier definitions.

```
Azure Storage Account
├── Bronze Container (Raw Data)
│   ├── user_uploads/
│   │   ├── shapefile.zip
│   │   ├── data.geojson
│   │   └── imagery.tif
│   └── external_feeds/
│
├── Silver Container (Processed Data)
│   ├── cogs/
│   │   ├── imagery_cog.tif
│   │   └── dem_cog.tif
│   ├── vectors/
│   │   └── validated_features.parquet
│   └── tiles/
│       └── mosaicjson/
│
└── Gold Container (Exports) - Future
    ├── geoparquet/
    └── aggregations/
```

### Access Patterns

| Container | Read Access | Write Access | Typical Size |
|-----------|-------------|--------------|--------------|
| Bronze | Job handlers | Users, external systems | 10 GB - 1 TB |
| Silver | TiTiler, STAC API | Job handlers only | 50 GB - 5 TB |
| Gold | External consumers | Aggregation jobs | Variable |

---

## Component Details

### 1. Azure Storage Account

```yaml
# POPULATE FROM YOUR ENVIRONMENT:
Storage Account Name: _______________________________
Resource Group: _______________________________
Region: _______________________________
Account Kind: StorageV2 (general-purpose v2)
Replication: LRS (Locally Redundant Storage) or GRS
Access Tier: Hot
Performance: Standard
```

**How to find account details**:
```bash
az storage account show \
  --resource-group <YOUR_RG> \
  --name <YOUR_STORAGE_ACCOUNT> \
  --query "{name:name, location:location, kind:kind, sku:sku.name}" -o json
```

### 2. Container Names

| Tier | Container Name | Purpose |
|------|---------------|---------|
| Bronze | rmhazuregeobronze | Raw user uploads |
| Silver | rmhazuregeosilver | Processed COGs and tiles |
| Gold | rmhazuregeogold | Final exports (future) |
| Intermediate | rmhazuregeotiles | MosaicJSON and tile indexes |

### 3. Access Keys

```yaml
# Connection String (Sensitive - Do NOT commit)
Connection String: DefaultEndpointsProtocol=https;AccountName=<NAME>;AccountKey=<KEY>;EndpointSuffix=core.windows.net

# Account Key (Sensitive - Do NOT commit)
Account Key: _______________________________
```

**How to retrieve**:
```bash
# Get connection string
az storage account show-connection-string \
  --resource-group <YOUR_RG> \
  --name <YOUR_STORAGE_ACCOUNT> \
  --query connectionString -o tsv

# Get account key
az storage account keys list \
  --resource-group <YOUR_RG> \
  --name <YOUR_STORAGE_ACCOUNT> \
  --query "[0].value" -o tsv
```

---

## Setup Instructions

### Step 1: Create Storage Account

```bash
# Create storage account (if not exists)
az storage account create \
  --resource-group <YOUR_RG> \
  --name <YOUR_STORAGE_ACCOUNT> \
  --location eastus \
  --sku Standard_LRS \
  --kind StorageV2 \
  --access-tier Hot \
  --min-tls-version TLS1_2
```

### Step 2: Create Containers

```bash
# Get connection string
CONNECTION_STRING=$(az storage account show-connection-string \
  --resource-group <YOUR_RG> \
  --name <YOUR_STORAGE_ACCOUNT> \
  --query connectionString -o tsv)

# Create Bronze container
az storage container create \
  --name rmhazuregeobronze \
  --connection-string "$CONNECTION_STRING" \
  --public-access off

# Create Silver container
az storage container create \
  --name rmhazuregeosilver \
  --connection-string "$CONNECTION_STRING" \
  --public-access off

# Create Tiles container (for MosaicJSON)
az storage container create \
  --name rmhazuregeotiles \
  --connection-string "$CONNECTION_STRING" \
  --public-access off
```

### Step 3: Configure CORS (Required for TiTiler)

```bash
# Enable CORS for TiTiler access
az storage cors add \
  --services b \
  --methods GET HEAD OPTIONS \
  --origins "*" \
  --allowed-headers "*" \
  --exposed-headers "*" \
  --max-age 3600 \
  --account-name <YOUR_STORAGE_ACCOUNT>
```

### Step 4: Configure Function App Connection

```bash
# Set storage connection in Function App
az functionapp config appsettings set \
  --resource-group <YOUR_RG> \
  --name <YOUR_FUNCTION_APP> \
  --settings AzureWebJobsStorage="$CONNECTION_STRING" \
           STORAGE_CONNECTION_STRING="$CONNECTION_STRING" \
           BRONZE_STORAGE_ACCOUNT="<YOUR_STORAGE_ACCOUNT>" \
           SILVER_STORAGE_ACCOUNT="<YOUR_STORAGE_ACCOUNT>"
```

### Step 5: Verify Configuration

```bash
# List containers
az storage container list \
  --account-name <YOUR_STORAGE_ACCOUNT> \
  --query "[].name" -o table
```

**Expected output**:
```
Name
-------------------
rmhazuregeobronze
rmhazuregeosilver
rmhazuregeotiles
```

---

## Container Configuration

### Bronze Container

**Purpose**: Store raw, unprocessed data uploaded by users

**Configuration**:
```yaml
Name: rmhazuregeobronze
Public Access: None (private)
Default Tier: Hot
Lifecycle Policy: Optional - move to Cool after 90 days
```

**Typical contents**:
- Shapefiles (.shp, .dbf, .shx, .prj)
- GeoJSON files
- GeoPackage files (.gpkg)
- GeoTIFF files (unprocessed)
- CSV files with coordinates

### Silver Container

**Purpose**: Store processed, cloud-optimized data

**Configuration**:
```yaml
Name: rmhazuregeosilver
Public Access: None (private)
Default Tier: Hot
Lifecycle Policy: None (frequently accessed)
```

**Typical contents**:
- Cloud-Optimized GeoTIFFs (COGs)
- Validated and indexed vector data
- Intermediate processing results

**Folder structure**:
```
rmhazuregeosilver/
├── cogs/
│   ├── visualization/    # JPEG compression, smaller files
│   ├── analysis/        # DEFLATE compression, full precision
│   └── archive/         # LZW compression, maximum compression
└── vectors/
    └── validated/
```

### Tiles Container

**Purpose**: Store MosaicJSON indexes and tile metadata

**Configuration**:
```yaml
Name: rmhazuregeotiles
Public Access: None (private)
Default Tier: Hot
Lifecycle Policy: None
```

**Typical contents**:
- MosaicJSON files (.json)
- Tile index metadata

---

## Access Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `STORAGE_CONNECTION_STRING` | Full connection string | Yes |
| `BRONZE_STORAGE_ACCOUNT` | Bronze tier storage account name | Yes |
| `SILVER_STORAGE_ACCOUNT` | Silver tier storage account name | Yes |
| `SILVEREXT_STORAGE_ACCOUNT` | Silver extended tier storage account name | No |
| `GOLD_STORAGE_ACCOUNT` | Gold tier storage account name | No |
| `STORAGE_ACCOUNT_KEY` | Account key (alternative to connection string) | No |
| `AzureWebJobsStorage` | Functions runtime storage | Yes |

### Blob Repository Configuration

The application uses `BlobRepository` class for all storage operations:

```python
# infrastructure/blob.py
class BlobRepository:
    @classmethod
    def instance(cls) -> "BlobRepository":
        """Get singleton instance"""

    def container_exists(self, container_name: str) -> bool:
        """Check if container exists"""

    def blob_exists(self, container_name: str, blob_name: str) -> bool:
        """Check if blob exists"""

    def get_blob_url_with_sas(
        self,
        container_name: str,
        blob_name: str,
        hours: int = 2
    ) -> str:
        """Generate SAS URL with expiration"""

    def write_blob(
        self,
        container_name: str,
        blob_name: str,
        data: bytes
    ) -> None:
        """Upload blob data"""
```

---

## Container Operations API

The platform provides HTTP endpoints for exploring and inventorying storage containers without direct Azure portal access.

### List All Containers (Sync)

**Endpoint**: `GET /api/storage/containers`

Lists all containers across all configured storage zones (Bronze, Silver, SilverExt, Gold).

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `zone` | string | all | Filter to specific zone: `bronze`, `silver`, `silverext`, `gold` |
| `prefix` | string | none | Container name prefix filter |

**Example Requests**:
```bash
# List all containers across all zones
curl https://rmhazuregeoapi-.../api/storage/containers

# Filter to bronze zone only
curl "https://rmhazuregeoapi-.../api/storage/containers?zone=bronze"

# Filter by container name prefix
curl "https://rmhazuregeoapi-.../api/storage/containers?prefix=silver-"
```

**Example Response**:
```json
{
  "zones": {
    "bronze": {
      "account": "rmhazuregeo",
      "containers": ["rmhazuregeobronze"],
      "container_count": 1
    },
    "silver": {
      "account": "rmhazuregeo",
      "containers": ["silver-cogs"],
      "container_count": 1,
      "note": "MosaicJSON files stored in silver-cogs alongside COGs (19 DEC 2025)"
    },
    "silverext": {
      "account": "rmhazuregeo",
      "containers": [],
      "container_count": 0
    },
    "gold": {
      "account": "rmhazuregeo",
      "containers": [],
      "container_count": 0
    }
  },
  "total_containers": 3,
  "query_time_seconds": 0.234
}
```

### List Blobs in Container (Sync)

**Endpoint**: `GET /api/containers/{container_name}/blobs`

Lists blobs within a specific container with filtering options. Returns immediately (synchronous).

**Path Parameters**:
| Parameter | Description |
|-----------|-------------|
| `container_name` | Azure Blob Storage container name |

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `zone` | string | `bronze` | Storage zone: `bronze`, `silver`, `silverext`, `gold` |
| `prefix` | string | none | Blob path prefix filter |
| `suffix` | string | none | File extension filter (e.g., `.tif`, `.geojson`) |
| `metadata` | bool | `true` | Return full metadata dict vs just blob names |
| `limit` | int | 500 | Max blobs to return (max: 10000) |

**Example Requests**:
```bash
# List first 10 TIF files with full metadata
curl "https://rmhazuregeoapi-.../api/containers/rmhazuregeobronze/blobs?suffix=.tif&limit=10"

# List blob names only (lightweight)
curl "https://rmhazuregeoapi-.../api/containers/rmhazuregeobronze/blobs?metadata=false&limit=100"

# List from silver zone with prefix filter
curl "https://rmhazuregeoapi-.../api/containers/silver-cogs/blobs?zone=silver&prefix=maxar/"
```

**Example Response** (metadata=true):
```json
{
  "zone": "bronze",
  "container": "rmhazuregeobronze",
  "prefix": null,
  "suffix": ".tif",
  "metadata": true,
  "limit": 10,
  "count": 2,
  "blobs": [
    {
      "name": "maxar/tile_001.tif",
      "size": 52428800,
      "size_mb": 50.0,
      "last_modified": "2025-12-09T15:30:00+00:00",
      "content_type": "image/tiff",
      "etag": "0x8DC...",
      "metadata": {}
    }
  ]
}
```

### Container Inventory Job (Async)

**Endpoint**: `POST /api/jobs/submit/inventory_container_contents`

Submits an async job to inventory container contents with detailed analysis. Uses CoreMachine job orchestration (fan-out pattern).

**Request Body**:
```json
{
  "container_name": "rmhazuregeobronze",
  "prefix": "maxar/",
  "suffix": ".tif",
  "limit": 500,
  "analysis_mode": "basic",
  "grouping_mode": "auto",
  "min_collection_size": 2,
  "include_unrecognized": true
}
```

**Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `container_name` | string | required | Container to inventory |
| `prefix` | string | none | Path prefix filter |
| `suffix` | string | none | Extension filter |
| `limit` | int | 500 | Max blobs to analyze |
| `analysis_mode` | string | `basic` | `basic` (file stats) or `geospatial` (pattern detection) |
| `grouping_mode` | string | `auto` | How to group files: `auto`, `folder`, `prefix`, `manifest`, `all_singles`, `all_collection` |
| `min_collection_size` | int | 2 | Minimum files to form a collection |
| `include_unrecognized` | bool | `true` | Include unknown file types in results |

**Analysis Modes**:

| Mode | Stage 2 Handler | Stage 3 Handler | Use Case |
|------|-----------------|-----------------|----------|
| `basic` | `analyze_blob_basic` | `aggregate_blob_analysis` | File counts, sizes, extensions |
| `geospatial` | `classify_geospatial_file` | `aggregate_geospatial_inventory` | Vendor pattern detection, collection grouping, sidecar association |

**Example Requests**:
```bash
# Basic inventory
curl -X POST "https://rmhazuregeoapi-.../api/jobs/submit/inventory_container_contents" \
  -H "Content-Type: application/json" \
  -d '{"container_name": "rmhazuregeobronze", "limit": 100}'

# Geospatial inventory with TIF filter
curl -X POST "https://rmhazuregeoapi-.../api/jobs/submit/inventory_container_contents" \
  -H "Content-Type: application/json" \
  -d '{"container_name": "rmhazuregeobronze", "analysis_mode": "geospatial", "suffix": ".tif"}'
```

**Job Result** (basic mode):
```json
{
  "summary": {
    "total_files": 100,
    "total_size_mb": 2924.4,
    "average_size_mb": 29.24,
    "by_extension": {
      ".tif": {"count": 28, "total_size_mb": 2877.87, "percentage": 28.0},
      ".geojson": {"count": 25, "total_size_mb": 9.86, "percentage": 25.0}
    },
    "largest_file": {"name": "raster.tif", "size_mb": 284.37},
    "smallest_file": {"name": "meta.json", "size_mb": 0.01}
  }
}
```

### Comparison: Sync vs Async

| Feature | Sync Endpoint | Async Job |
|---------|---------------|-----------|
| Response time | Immediate | Minutes (depends on blob count) |
| Max blobs | 10,000 | 50,000 |
| Analysis depth | Basic metadata only | Full geospatial classification |
| Pattern detection | No | Yes (geospatial mode) |
| Collection grouping | No | Yes (geospatial mode) |
| Use case | Quick lookups, UI | Deep analysis, inventory reports |

---

## SAS Token Management

### What is a SAS Token?

A Shared Access Signature (SAS) token provides limited access to blobs without exposing account keys. The platform generates SAS tokens for:

- Job handlers reading source files
- TiTiler accessing COGs
- External services reading results

### SAS Token Generation

```python
# Example: Generate 2-hour SAS URL
from infrastructure.blob import BlobRepository

blob_repo = BlobRepository.instance()
sas_url = blob_repo.get_blob_url_with_sas(
    container_name="rmhazuregeobronze",
    blob_name="data/imagery.tif",
    hours=2
)
# Returns: https://account.blob.core.windows.net/container/blob?sv=2021-06-08&se=2025-11-24T...
```

### SAS Token Lifetimes

| Use Case | Lifetime | Reason |
|----------|----------|--------|
| Job processing | 2 hours | Sufficient for most tasks |
| MosaicJSON references | 24 hours | Longer validity for tile serving |
| TiTiler access | 1 hour | Short-lived for security |
| External sharing | Variable | Set based on requirements |

### Best Practices

1. **Use short lifetimes**: Generate SAS tokens with minimum required lifetime
2. **Do not store SAS tokens**: Generate on demand, do not persist
3. **Use HTTPS only**: SAS URLs should always use HTTPS
4. **Limit permissions**: Grant only required permissions (read-only when possible)

---

## Troubleshooting

### Issue 1: Container Not Found

**Symptoms**: Error "ContainerNotFound" when accessing blobs

**Diagnosis**:
```bash
# List containers
az storage container list \
  --account-name <YOUR_STORAGE_ACCOUNT> \
  --query "[].name" -o table
```

**Solutions**:
1. Verify container name spelling (case-sensitive)
2. Create container if missing (see Setup Instructions)
3. Check connection string points to correct account

### Issue 2: Access Denied

**Symptoms**: Error "AuthorizationFailure" or "AuthorizationPermissionMismatch"

**Diagnosis**:
```bash
# Verify account key is valid
az storage container list \
  --account-name <YOUR_STORAGE_ACCOUNT> \
  --account-key <YOUR_KEY>
```

**Solutions**:
1. Regenerate and update account key
2. Check Function App has correct connection string
3. Verify container access level (should be private)

### Issue 3: CORS Errors (TiTiler)

**Symptoms**: Browser console shows "CORS policy" errors

**Diagnosis**:
```bash
# Check CORS settings
az storage cors list \
  --services b \
  --account-name <YOUR_STORAGE_ACCOUNT>
```

**Solutions**:
```bash
# Clear and reset CORS
az storage cors clear \
  --services b \
  --account-name <YOUR_STORAGE_ACCOUNT>

az storage cors add \
  --services b \
  --methods GET HEAD OPTIONS \
  --origins "*" \
  --allowed-headers "*" \
  --exposed-headers "*" \
  --max-age 3600 \
  --account-name <YOUR_STORAGE_ACCOUNT>
```

### Issue 4: SAS Token Expired

**Symptoms**: Error "AuthenticationFailed" with message about token expiration

**Solutions**:
1. Generate new SAS token with longer lifetime
2. Check system clock synchronization
3. Review token lifetime requirements for use case

### Issue 5: Blob Upload Fails

**Symptoms**: Error when uploading blobs to container

**Diagnosis**:
```bash
# Check account status
az storage account show \
  --resource-group <YOUR_RG> \
  --name <YOUR_STORAGE_ACCOUNT> \
  --query provisioningState -o tsv
```

**Solutions**:
1. Verify account is "Succeeded" state
2. Check storage quota not exceeded
3. Verify network access rules allow Azure services

### Issue 6: Large File Upload Timeout

**Symptoms**: Uploads fail for files larger than 100 MB

**Solutions**:
1. Use chunked upload (BlobRepository handles automatically)
2. Increase Function App timeout in host.json
3. Consider using Azure Data Factory for very large files

---

## Performance Optimization

### Recommendations

1. **Use Hot tier** for frequently accessed data (Bronze, Silver)
2. **Enable CORS** before deploying TiTiler integration
3. **Use SAS tokens** instead of account keys in URLs
4. **Organize by folder** for easier management and lifecycle policies
5. **Monitor costs** - storage costs increase with data volume

### Lifecycle Management

For large deployments, consider lifecycle policies:

```bash
# Move Bronze data to Cool tier after 90 days
az storage account management-policy create \
  --account-name <YOUR_STORAGE_ACCOUNT> \
  --policy @lifecycle-policy.json
```

---

## Related Documentation

- **[WIKI_API_SERVICE_BUS.md](WIKI_API_SERVICE_BUS.md)** - Service Bus configuration
- **[WIKI_API_DATABASE.md](WIKI_API_DATABASE.md)** - Database configuration
- **[WIKI_TECHNICAL_OVERVIEW.md](WIKI_TECHNICAL_OVERVIEW.md)** - Architecture overview
- **[docs_claude/CLAUDE_CONTEXT.md](docs_claude/CLAUDE_CONTEXT.md)** - Primary project context

---

**Last Updated**: 29 DEC 2025
