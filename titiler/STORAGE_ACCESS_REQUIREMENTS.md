# TiTiler Storage Access Requirements

**Date**: 26 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Document storage permissions required for TiTiler Container App

## Current Status ⚠️

The TiTiler container app currently has **NO managed identity** configured, meaning it cannot authenticate to Azure Storage using Azure AD RBAC roles.

```json
Identity Configuration: {
  "type": "None"
}
```

## Storage Access Requirements

TiTiler needs to read raster files (COGs) from Azure Storage to generate tiles dynamically. The required access level is:

### **Required Role: Storage Blob Data Reader**

This role provides:
- ✅ Read blob data
- ✅ List blobs in containers
- ✅ Get blob properties and metadata
- ❌ Cannot write or delete blobs (good for security)

### Containers to Access

TiTiler needs read access to these containers:

1. **`silver`** - Primary container for Cloud Optimized GeoTIFFs (COGs)
   - Contains processed, analysis-ready rasters
   - EPSG:4326 projection
   - Optimized for streaming

2. **`bronze`** (optional) - Raw data container
   - May contain source rasters
   - Only if serving tiles from unprocessed data

3. **`gold`** (future) - Optimized outputs
   - GeoParquet files
   - Mosaic definitions

## Access Methods

### Option 1: Managed Identity with RBAC (Recommended) ✅

**Advantages:**
- No secrets to manage
- Automatic credential rotation
- Granular permissions per container
- Best security practice

**Implementation Steps:**

1. **Enable System-Assigned Managed Identity**
```bash
az containerapp identity assign \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --system-assigned
```

2. **Get the Identity Principal ID**
```bash
IDENTITY_ID=$(az containerapp identity show \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --query principalId -o tsv)
```

3. **Assign Storage Blob Data Reader Role**
```bash
# For entire storage account
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee $IDENTITY_ID \
  --scope /subscriptions/{subscription-id}/resourceGroups/rmhazure_rg/providers/Microsoft.Storage/storageAccounts/rmhazuregeo

# OR for specific containers only (more secure)
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee $IDENTITY_ID \
  --scope /subscriptions/{subscription-id}/resourceGroups/rmhazure_rg/providers/Microsoft.Storage/storageAccounts/rmhazuregeo/blobServices/default/containers/silver

az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee $IDENTITY_ID \
  --scope /subscriptions/{subscription-id}/resourceGroups/rmhazure_rg/providers/Microsoft.Storage/storageAccounts/rmhazuregeo/blobServices/default/containers/bronze
```

4. **Configure TiTiler Environment Variables**
```bash
az containerapp update \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --set-env-vars \
    AZURE_STORAGE_ACCOUNT=rmhazuregeo \
    AZURE_CLIENT_ID=managed_identity
```

### Option 2: Storage Account Key (Not Recommended) ⚠️

**Disadvantages:**
- Secret management required
- Manual rotation needed
- Less secure
- All-or-nothing access

**Implementation:**
```bash
# Get storage key
STORAGE_KEY=$(az storage account keys list \
  --account-name rmhazuregeo \
  --resource-group rmhazure_rg \
  --query "[0].value" -o tsv)

# Set as environment variable
az containerapp update \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --set-env-vars \
    AZURE_STORAGE_ACCOUNT=rmhazuregeo \
    AZURE_STORAGE_ACCESS_KEY=$STORAGE_KEY
```

### Option 3: SAS Token (Medium Security) 🔐

**Use Case:** Time-limited access or delegated access

**Implementation:**
```bash
# Generate SAS token for read access
END_DATE=$(date -u -d "1 year" '+%Y-%m-%dT%H:%MZ')

SAS_TOKEN=$(az storage container generate-sas \
  --account-name rmhazuregeo \
  --name silver \
  --permissions lr \
  --expiry $END_DATE \
  --auth-mode key \
  --as-user \
  -o tsv)

# Set as environment variable
az containerapp update \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --set-env-vars \
    AZURE_STORAGE_ACCOUNT=rmhazuregeo \
    AZURE_STORAGE_SAS_TOKEN=$SAS_TOKEN
```

### Option 4: Public Anonymous Access (Development Only) 🚫

**Current Status:** Storage account allows public access but containers are private

**Not Recommended:** Security risk, should not be used in production

## GDAL/Rasterio VSI Configuration

TiTiler uses GDAL's Virtual File System (VSI) to access cloud storage. Required environment variables:

```bash
# For Managed Identity
AZURE_STORAGE_ACCOUNT=rmhazuregeo
AZURE_NO_SIGN_REQUEST=NO

# Performance optimization
GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR
CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.tiff,.TIF,.TIFF
VSI_CACHE=TRUE
VSI_CACHE_SIZE=5000000
GDAL_CACHEMAX=200

# Azure-specific optimizations
AZURE_STORAGE_ACCESS_TOKEN={managed_identity_token}
AZURE_REQUEST_TIMEOUT=30
```

## Verification Steps

After configuring storage access:

1. **Test Container App Identity**
```bash
az containerapp identity show \
  --name rmhtitiler \
  --resource-group rmhazure_rg
```

2. **Verify Role Assignment**
```bash
az role assignment list \
  --assignee $IDENTITY_ID \
  --scope /subscriptions/{subscription-id}/resourceGroups/rmhazure_rg/providers/Microsoft.Storage/storageAccounts/rmhazuregeo
```

3. **Test TiTiler Access**
```bash
# Test with a known COG file
curl "https://rmhtitiler.jollypond-54b50986.eastus.azurecontainerapps.io/info?url=https://rmhazuregeo.blob.core.windows.net/silver/test.tif"
```

## Security Best Practices

1. ✅ **Use Managed Identity** - No secrets in code or config
2. ✅ **Least Privilege** - Only Storage Blob Data Reader role
3. ✅ **Scope to Containers** - Don't grant account-wide access
4. ✅ **Monitor Access** - Use Azure Monitor to track usage
5. ✅ **Regular Audits** - Review role assignments quarterly
6. ❌ **Avoid Keys** - Don't use storage account keys in production
7. ❌ **No Public Access** - Keep containers private

## Troubleshooting

### Error: 403 Forbidden
- Check managed identity is enabled
- Verify role assignment is active
- Ensure correct storage account name
- Check container exists and name is correct

### Error: 404 Not Found
- Verify blob path is correct
- Check file exists in container
- Ensure URL encoding is proper

### Error: Authentication Failed
- Check environment variables are set
- Verify managed identity principal ID
- Ensure role propagation complete (can take 5 minutes)

## Summary

**Recommended Configuration:**
1. Enable system-assigned managed identity on container app
2. Grant "Storage Blob Data Reader" role on silver and bronze containers
3. Set environment variables for AZURE_STORAGE_ACCOUNT
4. Configure GDAL optimization variables

This provides secure, credential-free access to storage for TiTiler to read COGs and generate tiles dynamically.