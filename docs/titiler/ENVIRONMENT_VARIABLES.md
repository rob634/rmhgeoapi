# TiTiler Environment Variables Reference

**Date**: 26 OCT 2025
**Purpose**: Complete reference of environment variables for TiTiler-PgSTAC container

## Overview

TiTiler-PgSTAC requires environment variables for:
1. **PostgreSQL/PgSTAC connection** (REQUIRED)
2. **Azure Storage access** (REQUIRED for COG access)
3. **Performance optimization** (RECOMMENDED)
4. **Security and CORS** (OPTIONAL)

## Required Environment Variables

### PostgreSQL/PgSTAC Connection

These variables are **REQUIRED** for TiTiler to connect to the STAC catalog:

| Variable | Description | Example | Sensitive |
|----------|-------------|---------|-----------|
| `POSTGRES_HOST` | PostgreSQL server hostname | `rmhpgflex.postgres.database.azure.com` | No |
| `POSTGRES_PORT` | PostgreSQL server port | `5432` | No |
| `POSTGRES_USER` | PostgreSQL username | `rmhadmin` | No |
| `POSTGRES_PASS` | PostgreSQL password | `[KEY_VAULT_REFERENCE]` | **Yes** ⚠️ |
| `POSTGRES_DBNAME` | Database name | `postgres` | No |
| `POSTGRES_SCHEMA` | STAC schema name | `pgstac` | No |

**Alternative: Connection String**
| Variable | Description | Example | Sensitive |
|----------|-------------|---------|-----------|
| `DATABASE_URL` | Full PostgreSQL connection string | `postgresql://user:pass@host:5432/dbname` | **Yes** ⚠️ |

### Azure Storage Access

For reading COGs from Azure Blob Storage:

| Variable | Description | Example | Sensitive |
|----------|-------------|---------|-----------|
| `AZURE_STORAGE_ACCOUNT` | Storage account name | `rmhazuregeo` | No |
| `AZURE_CLIENT_ID` | Managed identity client ID or `managed_identity` | `managed_identity` | No |

**Alternative: Storage Key (Not Recommended)**
| Variable | Description | Example | Sensitive |
|----------|-------------|---------|-----------|
| `AZURE_STORAGE_ACCESS_KEY` | Storage account key | `[KEY_VAULT_REFERENCE]` | **Yes** ⚠️ |

**Alternative: SAS Token**
| Variable | Description | Example | Sensitive |
|----------|-------------|---------|-----------|
| `AZURE_STORAGE_SAS_TOKEN` | Shared Access Signature | `[KEY_VAULT_REFERENCE]` | **Yes** ⚠️ |

## Recommended Performance Variables

### GDAL/Rasterio Optimization

These improve COG streaming performance:

| Variable | Description | Default | Recommended |
|----------|-------------|---------|-------------|
| `GDAL_CACHEMAX` | GDAL block cache size (MB) | `75` | `200` |
| `GDAL_DISABLE_READDIR_ON_OPEN` | Skip directory listing | `FALSE` | `EMPTY_DIR` |
| `GDAL_HTTP_MERGE_CONSECUTIVE_RANGES` | Merge HTTP range requests | `YES` | `YES` |
| `GDAL_HTTP_MULTIPLEX` | Enable HTTP/2 multiplexing | `YES` | `YES` |
| `GDAL_HTTP_VERSION` | HTTP version to use | `2` | `2` |

### VSI (Virtual File System) Cache

| Variable | Description | Default | Recommended |
|----------|-------------|---------|-------------|
| `VSI_CACHE` | Enable VSI cache | `FALSE` | `TRUE` |
| `VSI_CACHE_SIZE` | Cache size in bytes | `25000000` | `5000000` |
| `CPL_VSIL_CURL_CACHE_SIZE` | CURL cache size | `16000000` | `128000000` |
| `CPL_VSIL_CURL_ALLOWED_EXTENSIONS` | Allowed file extensions | `.tif` | `.tif,.tiff,.TIF,.TIFF` |

### Azure-Specific Optimizations

| Variable | Description | Default | Recommended |
|----------|-------------|---------|-------------|
| `AZURE_NO_SIGN_REQUEST` | Use unsigned requests | `YES` | `NO` (with managed identity) |
| `AZURE_REQUEST_TIMEOUT` | Request timeout (seconds) | `30` | `30` |
| `CPL_AZURE_USE_HTTPS` | Use HTTPS for Azure | `YES` | `YES` |

## Optional Application Variables

### TiTiler Configuration

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `HOST` | Bind host | `0.0.0.0` | `0.0.0.0` |
| `PORT` | Bind port | `8000` | `8000` |
| `WORKERS` | Number of worker processes | `1` | `4` |
| `ROOT_PATH` | API root path | `/` | `/api/tiles` |
| `MOSAIC_CONCURRENCY` | Mosaic processing threads | `1` | `4` |

### CORS Settings

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `TITILER_CORS_ORIGINS` | Allowed origins | `*` | `https://app.example.com` |
| `TITILER_CORS_METHODS` | Allowed methods | `GET` | `GET,POST` |
| `TITILER_CORS_HEADERS` | Allowed headers | `*` | `Content-Type,Authorization` |

### Logging and Monitoring

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `LOG_LEVEL` | Logging level | `INFO` | `DEBUG` |
| `ACCESS_LOG` | Enable access logs | `TRUE` | `TRUE` |
| `FORWARDED_ALLOW_IPS` | Trusted proxy IPs | `*` | `10.0.0.0/8` |

## Security Considerations

### Sensitive Variables ⚠️

These variables should **NEVER** be hardcoded:
- `POSTGRES_PASS`
- `DATABASE_URL` (if contains password)
- `AZURE_STORAGE_ACCESS_KEY`
- `AZURE_STORAGE_SAS_TOKEN`

**Best Practice**: Use Key Vault references (see KEY_VAULT_INTEGRATION.md)

### How Credentials Are Used

1. **PostgreSQL Password**:
   - Used **only server-side** by TiTiler to connect to PgSTAC
   - Never exposed in tile URLs or client requests
   - Connection established on container startup

2. **Storage Access**:
   - Managed identity preferred (no secrets)
   - Credentials used server-side to stream COGs
   - Client requests never include storage credentials

3. **Client Requests**:
   - Tile URLs like `/tiles/{z}/{x}/{y}` contain no credentials
   - TiTiler handles all authentication internally
   - Optional: Add API key authentication for clients

## Complete Configuration Example

### Using Key Vault (Secure) ✅

```bash
az containerapp update \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --set-env-vars \
    POSTGRES_HOST="rmhpgflex.postgres.database.azure.com" \
    POSTGRES_PORT="5432" \
    POSTGRES_USER="rmhadmin" \
    POSTGRES_DBNAME="postgres" \
    POSTGRES_SCHEMA="pgstac" \
    AZURE_STORAGE_ACCOUNT="rmhazuregeo" \
    AZURE_CLIENT_ID="managed_identity" \
    GDAL_CACHEMAX="200" \
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR" \
    VSI_CACHE="TRUE" \
    VSI_CACHE_SIZE="5000000" \
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff,.TIF,.TIFF" \
  --secrets \
    postgres-pass="keyvaultref:https://rmhazurevault.vault.azure.net/secrets/postgres-password,identityref:system" \
  --set-env-vars \
    POSTGRES_PASS="secretref:postgres-pass"
```

### Using Direct Values (Development Only) ⚠️

```bash
# NOT RECOMMENDED FOR PRODUCTION
az containerapp update \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --set-env-vars \
    POSTGRES_HOST="rmhpgflex.postgres.database.azure.com" \
    POSTGRES_PORT="5432" \
    POSTGRES_USER="rmhadmin" \
    POSTGRES_PASS="ActualPasswordHere" \  # ⚠️ INSECURE
    POSTGRES_DBNAME="postgres" \
    POSTGRES_SCHEMA="pgstac" \
    AZURE_STORAGE_ACCOUNT="rmhazuregeo" \
    AZURE_CLIENT_ID="managed_identity"
```

## Validation Checklist

After setting environment variables, verify:

1. ✅ PostgreSQL variables set (check logs for connection success)
2. ✅ Azure Storage variables set
3. ✅ No sensitive values in plain text
4. ✅ Container starts without errors
5. ✅ Health endpoint responds: `GET /`
6. ✅ Can list collections: `GET /collections`
7. ✅ Can generate tiles from COGs

## Troubleshooting

### Container Won't Start

**Error**: `TypeError: quote_from_bytes() expected bytes`
- **Cause**: `POSTGRES_PASS` is not set or is None
- **Fix**: Ensure password is set via environment variable or Key Vault

**Error**: `Connection refused`
- **Cause**: Wrong `POSTGRES_HOST` or `POSTGRES_PORT`
- **Fix**: Verify PostgreSQL server address

### Storage Access Issues

**Error**: `403 Forbidden` on COG access
- **Cause**: Missing storage permissions
- **Fix**: Ensure managed identity has "Storage Blob Data Reader" role

**Error**: `404 Not Found` for tiles
- **Cause**: COG file doesn't exist or wrong path
- **Fix**: Verify blob exists in storage container

### Performance Issues

**Symptom**: Slow tile generation
- **Fix**: Increase `GDAL_CACHEMAX` and enable `VSI_CACHE`

**Symptom**: High memory usage
- **Fix**: Reduce `VSI_CACHE_SIZE` and `GDAL_CACHEMAX`

## Related Documentation

- [KEY_VAULT_INTEGRATION.md](./KEY_VAULT_INTEGRATION.md) - Secure credential management
- [CONTAINER_APP_CONFIGURATION.md](./CONTAINER_APP_CONFIGURATION.md) - Container app setup
- [TiTiler Environment Docs](https://developmentseed.org/titiler/deployment/azure/)