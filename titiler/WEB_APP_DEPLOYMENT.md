# TiTiler Web App Deployment

**Date**: 28 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: Active Deployment ✅

## Overview

TiTiler has been deployed as an Azure Web App (App Service) instead of Container Apps, as Container Apps is overkill (managed Kubernetes) for this simple tile server use case.

## Web App Details

- **Name**: `rmhtitiler`
- **URL**: https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net
- **Resource Group**: `rmhazure_rg`
- **App Service Plan**: `rmhtitiler_asp_Linux_eastus` (Basic B2)
- **Container Image**: `ghcr.io/stac-utils/titiler-pgstac:latest`
- **State**: Running

## Configuration

### PostgreSQL Connection
```bash
POSTGRES_HOST=rmhpgflex.postgres.database.azure.com
POSTGRES_PORT=5432
POSTGRES_USER=rob634
POSTGRES_PASS=B@lamb634@    # Hardcoded for simplicity
POSTGRES_DBNAME=postgres
POSTGRES_SCHEMA=pgstac       # STAC tables schema
```

### Azure Storage
```bash
AZURE_STORAGE_ACCOUNT_NAME=rmhazuregeo
AZURE_STORAGE_SAS_TOKEN=     # Optional - using managed identity
```

### Debug Settings
```bash
TITILER_PGSTAC_API_DEBUG=true
```

## Managed Identity

The Web App has a system-assigned managed identity with:
- **Principal ID**: Available but not yet configured
- **Storage Access**: Should have "Storage Blob Data Reader" role on `rmhazuregeo`

## Deployment Commands

### View Current Configuration
```bash
# Show all app settings
az webapp config appsettings list \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --output table

# Check Web App status
az webapp show \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --query state
```

### Update Configuration
```bash
# Set environment variables
az webapp config appsettings set \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --settings KEY=VALUE

# Restart to apply changes
az webapp restart \
  --resource-group rmhazure_rg \
  --name rmhtitiler
```

### Monitor Logs
```bash
# Stream logs
az webapp log tail \
  --resource-group rmhazure_rg \
  --name rmhtitiler

# Download logs
az webapp log download \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --log-file titiler-logs.zip
```

## Endpoints

### Health Check
```bash
curl https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/healthz
```

### API Documentation
- Swagger UI: https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/docs
- OpenAPI: https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/openapi.json

### STAC Search & Tiles
```bash
# Search STAC items
GET /search

# Get tile from STAC item
GET /stac/tiles/{z}/{x}/{y}?url={stac_item_url}

# Get WMS capabilities
GET /stac/WMTSCapabilities.xml?url={stac_item_url}
```

## Comparison: Web App vs Container Apps

### Web App (Current - Recommended)
- ✅ Simple deployment model
- ✅ Lower cost (Basic B2 tier)
- ✅ Built-in scaling options
- ✅ Easy configuration management
- ✅ Integrated logging

### Container Apps (Previous Attempt)
- ❌ Overkill for single container
- ❌ More complex (managed Kubernetes)
- ❌ Higher overhead
- ❌ Designed for microservices

## Troubleshooting

### App Not Responding
1. Check logs: `az webapp log tail --resource-group rmhazure_rg --name rmhtitiler`
2. Verify configuration: `az webapp config appsettings list`
3. Restart: `az webapp restart --resource-group rmhazure_rg --name rmhtitiler`
4. Check container status in Azure Portal

### Database Connection Issues
- Verify PostgreSQL firewall rules allow Azure services
- Check credentials in app settings
- Ensure `pgstac` schema exists with STAC tables

### Storage Access Issues
- Verify managed identity has "Storage Blob Data Reader" role
- Check storage account allows Azure services
- For private endpoints, ensure network configuration

## Migration from Container Apps

The original Container Apps deployment (`rmhtitiler-app`) can be deleted once this Web App is verified working:

```bash
# Delete Container App (when ready)
az containerapp delete \
  --resource-group rmhazure_rg \
  --name rmhtitiler-app \
  --yes
```

## Notes

- PostgreSQL password is hardcoded as a shortcut (should use Key Vault in production)
- Web App automatically handles container restarts and health checks
- Scaling can be configured through App Service Plan
- Custom domains and SSL certificates can be added through Azure Portal