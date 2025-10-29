# TiTiler Deployment Documentation

**Date**: 28 OCT 2025
**Author**: Robert and Geospatial Claude Legion

## Overview

This folder contains documentation for TiTiler-PgSTAC deployment on Azure. TiTiler is a dynamic tile server that generates map tiles on-the-fly from Cloud-Optimized GeoTIFFs (COGs) cataloged in a PgSTAC database.

## Current Deployment

✅ **Web App (App Service)**: `rmhtitiler` - Active deployment
❌ **Container Apps**: `rmhtitiler-app` - Deprecated (overkill for this use case)

## Documentation Structure

```
titiler/
├── README.md                     # This file - overview and navigation
├── WEB_APP_DEPLOYMENT.md         # Current Web App deployment details
├── CONTAINER_APP_CONFIG.md       # Container Apps configuration (deprecated)
├── ENVIRONMENT_VARIABLES.md      # Complete environment variable reference
├── KEY_VAULT_INTEGRATION.md      # Secure credential management options
└── STORAGE_ACCESS.md             # Azure Storage integration and permissions
```

## Quick Start

### Access TiTiler
```bash
# Health check
curl https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/healthz

# API documentation
open https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/docs
```

### View Configuration
```bash
# Show current settings
az webapp config appsettings list \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --output table
```

### Monitor Logs
```bash
# Stream live logs
az webapp log tail \
  --resource-group rmhazure_rg \
  --name rmhtitiler
```

## Key Components

### 1. TiTiler-PgSTAC
- Generates map tiles dynamically from COGs
- Reads STAC metadata from PostgreSQL
- Accesses raster data from Azure Storage
- Provides OGC-compliant services (WMS, WMTS)

### 2. PostgreSQL/PostGIS Database
- **Host**: `rmhpgflex.postgres.database.azure.com`
- **Database**: `postgres`
- **Schema**: `pgstac`
- Contains STAC catalog metadata

### 3. Azure Storage
- **Account**: `rmhazuregeo`
- **Container**: `rmhazuregeocogs`
- Stores Cloud-Optimized GeoTIFFs
- Accessed via managed identity

### 4. Web App (App Service)
- **Name**: `rmhtitiler`
- **Plan**: Basic B2
- **Container**: `ghcr.io/stac-utils/titiler-pgstac:latest`
- Managed identity for secure storage access

## Architecture Flow

```
1. Client requests tile: /stac/tiles/{z}/{x}/{y}?url={stac_item}
                              ↓
2. TiTiler queries PgSTAC: SELECT * FROM pgstac.items WHERE id = ?
                              ↓
3. TiTiler reads COG: https://rmhazuregeo.blob.core.windows.net/cogs/...
                              ↓
4. TiTiler generates tile: Returns PNG/JPEG tile to client
```

## Security Configuration

### Current (Development)
- PostgreSQL password hardcoded in environment variables
- Managed identity for storage access
- Public endpoints (no authentication)

### Production Recommendations
1. Use Key Vault for PostgreSQL credentials
2. Enable authentication on Web App
3. Configure private endpoints
4. Set up Application Gateway with WAF
5. Implement rate limiting

## Common Operations

### Update PostgreSQL Connection
```bash
az webapp config appsettings set \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --settings \
    POSTGRES_HOST=rmhpgflex.postgres.database.azure.com \
    POSTGRES_USER=rob634 \
    POSTGRES_PASS='B@lamb634@'
```

### Grant Storage Access
```bash
# Get Web App identity
IDENTITY=$(az webapp identity show \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --query principalId -o tsv)

# Grant Storage Blob Data Reader role
az role assignment create \
  --assignee $IDENTITY \
  --role "Storage Blob Data Reader" \
  --scope /subscriptions/{subscription}/resourceGroups/rmhazure_rg/providers/Microsoft.Storage/storageAccounts/rmhazuregeo
```

### Restart Service
```bash
az webapp restart \
  --resource-group rmhazure_rg \
  --name rmhtitiler
```

## Troubleshooting

### Service Not Responding
- Check WEB_APP_DEPLOYMENT.md troubleshooting section
- Verify all environment variables are set
- Check PostgreSQL connectivity
- Ensure storage access is configured

### Tile Generation Errors
- Verify STAC items exist in database
- Check COG files exist in storage
- Validate COG format with `rio cogeo validate`
- Review logs for detailed error messages

## Related Documentation

- [TiTiler Documentation](https://developmentseed.org/titiler/)
- [PgSTAC Documentation](https://github.com/stac-utils/pgstac)
- [STAC Specification](https://stacspec.org/)
- [Cloud-Optimized GeoTIFF](https://www.cogeo.org/)

## Migration Path

Once Web App deployment is verified:
1. Update any client applications to use new URL
2. Monitor for 24-48 hours
3. Delete Container Apps deployment
4. Clean up unused resources

## Future Enhancements

- [ ] Add authentication layer
- [ ] Implement caching with Redis
- [ ] Set up CDN for tile delivery
- [ ] Add custom styling options
- [ ] Enable vector tile generation
- [ ] Implement usage analytics