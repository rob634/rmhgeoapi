# TiTiler Testing Workflow (Non-STAC First)

**Date**: 28 OCT 2025
**Purpose**: Test TiTiler is working before implementing STAC

## Testing Strategy

**Phase 1**: Direct COG Testing (NOW) ✅
**Phase 2**: STAC Integration (LATER)

This allows us to verify TiTiler is properly configured without the complexity of STAC setup.

## Phase 1: Direct COG Testing

### Step 1: Upload Test COG to Azure Storage

```bash
# Using antigua.tif from current directory
az storage blob upload \
  --account-name rmhazuregeo \
  --container-name rmhazuregeocogs \
  --name antigua.tif \
  --file ./antigua.tif \
  --overwrite

# Verify upload
az storage blob show \
  --account-name rmhazuregeo \
  --container-name rmhazuregeocogs \
  --name antigua.tif \
  --query "{name:name, size:properties.contentLength}" \
  --output table
```

### Step 2: Test TiTiler Endpoints

Run these tests in order to verify each component:

#### A. Health Check
```bash
# Basic health - should return OK
curl -s https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/health
```

#### B. COG Metadata
```bash
# Get COG info - tests blob access and GDAL
curl -s "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info?url=https://rmhazuregeo.blob.core.windows.net/rmhazuregeocogs/antigua.tif" | python3 -m json.tool
```

Expected output:
```json
{
  "bounds": [...],
  "center": [...],
  "minzoom": ...,
  "maxzoom": ...,
  "band_metadata": [...],
  "dtype": "uint8",
  "colorinterp": ["red", "green", "blue"],
  "width": ...,
  "height": ...
}
```

#### C. COG Statistics
```bash
# Get band statistics - tests data reading
curl -s "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/statistics?url=https://rmhazuregeo.blob.core.windows.net/rmhazuregeocogs/antigua.tif" | python3 -m json.tool
```

#### D. Generate a Tile
```bash
# Get a single tile - tests tile generation
curl -s -o test_tile.png "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/tiles/10/300/400.png?url=https://rmhazuregeo.blob.core.windows.net/rmhazuregeocogs/antigua.tif"

# Check if tile was created
ls -la test_tile.png
```

#### E. Preview Image
```bash
# Generate preview - tests full image rendering
curl -s -o preview.png "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/preview.png?url=https://rmhazuregeo.blob.core.windows.net/rmhazuregeocogs/antigua.tif&max_size=512"

# Check preview
ls -la preview.png
```

#### F. Interactive Viewer
```bash
# Open in browser - visual confirmation
open "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/viewer?url=https://rmhazuregeo.blob.core.windows.net/rmhazuregeocogs/antigua.tif"
```

### Step 3: Troubleshooting Tests

If any of the above fail, run these diagnostic tests:

#### Check Managed Identity
```bash
# Verify managed identity is configured
az webapp identity show \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --query principalId
```

#### Check Storage Permissions
```bash
# Verify Storage Blob Data Reader role
az role assignment list \
  --assignee $(az webapp identity show --resource-group rmhazure_rg --name rmhtitiler --query principalId -o tsv) \
  --scope /subscriptions/$(az account show --query id -o tsv)/resourceGroups/rmhazure_rg/providers/Microsoft.Storage/storageAccounts/rmhazuregeo \
  --output table
```

#### Check Environment Variables
```bash
# Verify required environment variables
az webapp config appsettings list \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --query "[?name=='AZURE_STORAGE_ACCOUNT_NAME' || name=='POSTGRES_HOST' || name=='POSTGRES_SCHEMA'].{name:name, value:value}" \
  --output table
```

#### Check Application Logs
```bash
# Stream logs to see errors
az webapp log tail \
  --resource-group rmhazure_rg \
  --name rmhtitiler
```

## Success Criteria

✅ **TiTiler is working if:**
1. Health endpoint returns OK
2. COG info shows correct bounds and metadata
3. Tiles generate without errors
4. Preview image displays the raster
5. Interactive viewer shows the map

## Common Issues and Fixes

### Issue: 403 Forbidden on COG access
**Fix**: Managed identity needs Storage Blob Data Reader role
```bash
az role assignment create \
  --assignee $(az webapp identity show --resource-group rmhazure_rg --name rmhtitiler --query principalId -o tsv) \
  --role "Storage Blob Data Reader" \
  --scope /subscriptions/$(az account show --query id -o tsv)/resourceGroups/rmhazure_rg/providers/Microsoft.Storage/storageAccounts/rmhazuregeo
```

### Issue: Connection timeout
**Fix**: Restart the Web App
```bash
az webapp restart --resource-group rmhazure_rg --name rmhtitiler
```

### Issue: "Cannot connect to PostgreSQL"
**Note**: PostgreSQL errors are OK for non-STAC testing! The COG endpoints don't need PostgreSQL.

### Issue: COG not found
**Fix**: Verify blob exists and path is correct
```bash
az storage blob list \
  --account-name rmhazuregeo \
  --container-name rmhazuregeocogs \
  --output table
```

## Quick Test Script

Save this as `test_titiler.sh`:

```bash
#!/bin/bash

TITILER_URL="https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net"
COG_URL="https://rmhazuregeo.blob.core.windows.net/rmhazuregeocogs/antigua.tif"

echo "🧪 Testing TiTiler with direct COG access..."
echo "==========================================="

echo -n "1. Health Check: "
if curl -s -f "$TITILER_URL/health" > /dev/null; then
    echo "✅ PASS"
else
    echo "❌ FAIL"
fi

echo -n "2. COG Info: "
if curl -s -f "$TITILER_URL/cog/info?url=$COG_URL" | grep -q "bounds"; then
    echo "✅ PASS"
else
    echo "❌ FAIL"
fi

echo -n "3. COG Statistics: "
if curl -s -f "$TITILER_URL/cog/statistics?url=$COG_URL" | grep -q "statistics"; then
    echo "✅ PASS"
else
    echo "❌ FAIL"
fi

echo -n "4. Tile Generation: "
if curl -s -f -o /tmp/test_tile.png "$TITILER_URL/cog/tiles/10/300/400.png?url=$COG_URL"; then
    echo "✅ PASS"
    rm /tmp/test_tile.png
else
    echo "❌ FAIL"
fi

echo -n "5. Preview Generation: "
if curl -s -f -o /tmp/preview.png "$TITILER_URL/cog/preview.png?url=$COG_URL&max_size=256"; then
    echo "✅ PASS"
    rm /tmp/preview.png
else
    echo "❌ FAIL"
fi

echo ""
echo "📊 Test Complete!"
echo "View interactive map at:"
echo "$TITILER_URL/cog/viewer?url=$COG_URL"
```

Run with:
```bash
chmod +x test_titiler.sh
./test_titiler.sh
```

## Phase 2: STAC Integration (Future)

Once Phase 1 is confirmed working:

1. **Set up PgSTAC schema** in PostgreSQL
2. **Ingest STAC items** with COG references
3. **Test STAC endpoints**: `/stac/`, `/collections/`, `/search/`
4. **Migrate applications** to use STAC search instead of direct URLs

## Summary

- **Start Simple**: Test with direct COG URLs first
- **No STAC Required**: The `/cog/` endpoints work without any database
- **Same Authentication**: Managed identity works for both modes
- **Production Path**: STAC will be the standard, but not needed for testing
- **Immediate Testing**: You can test RIGHT NOW with the antigua.tif file