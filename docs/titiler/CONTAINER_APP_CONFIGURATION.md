# TiTiler Container App Configuration

**Container App Name**: rmhtitiler
**Created**: 24 OCT 2025
**Last Updated**: 26 OCT 2025

## Overview

This document details the Azure Container App configuration for the TiTiler-PgSTAC service that provides dynamic tile serving capabilities for the geospatial platform.

## Container App Details

### Basic Information
- **Name**: `rmhtitiler`
- **Resource Group**: `rmhazure_rg`
- **Location**: `East US`
- **Provisioning State**: `Succeeded`
- **Container Apps Environment**: `jollypond-54b50986`

### Public Access
- **FQDN**: `rmhtitiler.jollypond-54b50986.eastus.azurecontainerapps.io`
- **URL**: https://rmhtitiler.jollypond-54b50986.eastus.azurecontainerapps.io
- **External Access**: Enabled
- **Allow Insecure**: True (HTTP allowed internally)

## Container Configuration

### Image Details
- **Container Image**: `ghcr.io/stac-utils/titiler-pgstac`
- **Container Name**: `rmhtitiler`
- **Image Source**: GitHub Container Registry (GHCR)
- **Image Type**: TiTiler-PgSTAC (STAC-aware dynamic tile server)

### Resource Allocation
```yaml
Resources:
  CPU: 1.0 cores
  Memory: 2 GB
  Ephemeral Storage: 4 GB
```

### Networking
```yaml
Ingress:
  External: true
  Target Port: 8000
  Transport: HTTP
  Exposed Port: 0 (auto-assigned)

Traffic Routing:
  - Latest Revision: true
    Weight: 100%

Sticky Sessions:
  Affinity: none
```

## Scaling Configuration

### Auto-scaling Rules
```yaml
Scale:
  Min Replicas: 0  # Scales to zero when idle
  Max Replicas: 10

Timing:
  Cooldown Period: 300 seconds (5 minutes)
  Polling Interval: 30 seconds

Current State:
  Active Replicas: 0 (scaled to zero)
  Active Revision: rmhtitiler--4a8qtcr
```

### Scale-to-Zero Behavior
- Container automatically scales to 0 replicas when not in use
- First request triggers container startup (cold start ~30-60 seconds)
- Remains active for 5 minutes after last request
- Cost-optimized for intermittent usage

## Revision Management

### Current Revision
- **Name**: `rmhtitiler--4a8qtcr`
- **Created**: `2025-10-24T18:39:58+00:00`
- **Status**: Active
- **Traffic**: 100%

### Revision Settings
```yaml
Active Revisions Mode: Single
Max Inactive Revisions: 100
```

## TiTiler-PgSTAC Features

### Supported Endpoints
The container provides these TiTiler endpoints:

```
GET  /                        # Health check / welcome
GET  /docs                    # Interactive API documentation
GET  /openapi.json           # OpenAPI specification

# STAC endpoints
GET  /collections            # List STAC collections
GET  /collections/{id}/items # List items in collection
GET  /collections/{id}/tiles # Tile endpoints for collection

# Tile endpoints
GET  /tiles/{z}/{x}/{y}      # XYZ tiles
GET  /tiles/{z}/{x}/{y}.png  # PNG tiles
GET  /tiles/{z}/{x}/{y}.jpg  # JPEG tiles
GET  /tiles/{z}/{x}/{y}.webp # WebP tiles

# TileJSON
GET  /tilejson.json          # TileJSON metadata

# Statistics
GET  /statistics             # Raster statistics
GET  /info                   # Raster information

# STAC Search
POST /search                 # Search STAC items
GET  /search                 # Search with query parameters
```

### Connection Requirements
TiTiler-PgSTAC requires connection to:
1. **PostgreSQL/PgSTAC database** for STAC catalog
2. **Azure Blob Storage** for raster data access

## Azure CLI Commands

### View Container App
```bash
# Show basic info
az containerapp show \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --output table

# Show detailed configuration
az containerapp show \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --output json
```

### Manage Revisions
```bash
# List all revisions
az containerapp revision list \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --output table

# Get active revision details
az containerapp revision show \
  --name rmhtitiler--4a8qtcr \
  --app rmhtitiler \
  --resource-group rmhazure_rg
```

### Update Configuration
```bash
# Update scaling rules
az containerapp update \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --min-replicas 0 \
  --max-replicas 10

# Update container image
az containerapp update \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --image ghcr.io/stac-utils/titiler-pgstac:latest
```

### Monitor and Logs
```bash
# View logs
az containerapp logs show \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --follow

# View metrics
az monitor metrics list \
  --resource /subscriptions/{subscription-id}/resourceGroups/rmhazure_rg/providers/Microsoft.App/containerApps/rmhtitiler \
  --metric "Requests" \
  --interval PT1M
```

## Testing the Service

### Health Check
```bash
# Basic health check (will trigger container start if scaled to zero)
curl https://rmhtitiler.jollypond-54b50986.eastus.azurecontainerapps.io/

# API documentation
curl https://rmhtitiler.jollypond-54b50986.eastus.azurecontainerapps.io/docs
```

### STAC Integration Test
```bash
# List collections (requires PgSTAC connection)
curl https://rmhtitiler.jollypond-54b50986.eastus.azurecontainerapps.io/collections

# Search items
curl -X POST https://rmhtitiler.jollypond-54b50986.eastus.azurecontainerapps.io/search \
  -H "Content-Type: application/json" \
  -d '{
    "collections": ["cogs"],
    "limit": 10
  }'
```

### Tile Request Example
```bash
# Get a tile (z/x/y format)
curl https://rmhtitiler.jollypond-54b50986.eastus.azurecontainerapps.io/tiles/10/256/512.png

# Get TileJSON metadata
curl https://rmhtitiler.jollypond-54b50986.eastus.azurecontainerapps.io/tilejson.json
```

## Environment Variables Required

For full functionality, TiTiler-PgSTAC needs these environment variables:

```bash
# PostgreSQL/PgSTAC connection
POSTGRES_HOST=rmhpgflex.postgres.database.azure.com
POSTGRES_PORT=5432
POSTGRES_DBNAME=postgres
POSTGRES_USER=rmhadmin
POSTGRES_PASS=<password>

# Optional: Azure Storage for COG access
AZURE_STORAGE_ACCOUNT=rmhazuregeo
AZURE_STORAGE_ACCESS_KEY=<key>

# Optional: Performance tuning
GDAL_CACHEMAX=200
GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR
CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.tiff
VSI_CACHE=TRUE
VSI_CACHE_SIZE=5000000
```

## Cost Optimization

### Current Configuration
- **Scale to Zero**: Enabled (no cost when idle)
- **Min Replicas**: 0
- **Estimated Cost**: ~$0 when idle, ~$50/month if running continuously

### Recommendations
1. Keep scale-to-zero enabled for development/testing
2. Consider min-replicas=1 for production to avoid cold starts
3. Monitor actual usage patterns to optimize scaling rules
4. Use Application Insights for performance monitoring

## Troubleshooting

### Container Won't Start
```bash
# Check logs for errors
az containerapp logs show --name rmhtitiler --resource-group rmhazure_rg --tail 50

# Check revision status
az containerapp revision list --name rmhtitiler --resource-group rmhazure_rg
```

### Connection Issues
1. Verify PostgreSQL connection string in environment variables
2. Check network security groups and firewall rules
3. Ensure PgSTAC schema is installed in database
4. Verify Azure Storage access for COG files

### Performance Issues
1. Check if container is scaled to zero (cold start delay)
2. Monitor CPU and memory usage
3. Review GDAL environment variables for optimization
4. Consider increasing min-replicas for consistent performance

## Related Documentation

- [TiTiler Documentation](https://developmentseed.org/titiler/)
- [TiTiler-PgSTAC](https://github.com/stac-utils/titiler-pgstac)
- [Azure Container Apps](https://docs.microsoft.com/en-us/azure/container-apps/)
- [PgSTAC Documentation](https://github.com/stac-utils/pgstac)