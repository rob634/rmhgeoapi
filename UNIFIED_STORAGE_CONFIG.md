# Unified Storage Configuration

## Configuration Changes Made

All storage operations now use the **AzureWebJobsStorage** connection settings that Azure Functions automatically configures.

### How it Works:

1. **Storage Account Name Extraction** (`config.py`):
   - Automatically extracts storage account name from `AzureWebJobsStorage__blobServiceUri`
   - Example: `https://rmhazuregeo.blob.core.windows.net` → `rmhazuregeo`
   - Falls back to `STORAGE_ACCOUNT_NAME` environment variable if needed

2. **Queue Trigger** (`function_app.py`):
   - Uses `connection="AzureWebJobsStorage"`
   - Leverages Azure's managed identity configuration

3. **Queue Client** (`function_app.py`):
   - Uses the extracted storage account name
   - Creates queue service URL dynamically
   - Uses `DefaultAzureCredential()` for managed identity

4. **Table Storage** (`repositories.py`):
   - Uses the same extracted storage account name
   - Uses `DefaultAzureCredential()` for managed identity

## No Additional Settings Required!

Since your Azure Function App already has these settings configured:
- `AzureWebJobsStorage__blobServiceUri`
- `AzureWebJobsStorage__queueServiceUri`
- `AzureWebJobsStorage__tableServiceUri`
- `AzureWebJobsStorage__credential=managedidentity`

The app will automatically:
1. Extract `rmhazuregeo` as the storage account name
2. Use managed identity for all storage operations
3. Work with the same storage account for everything

## Testing

After deployment, test the endpoints:

```bash
# Health check
curl https://rmhgeoapiqfn-h3dza4gyffbsbre7.eastus-01.azurewebsites.net/api/health

# Submit a test job
curl -X POST https://rmhgeoapiqfn-h3dza4gyffbsbre7.eastus-01.azurewebsites.net/api/jobs/hello_world \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "test", "resource_id": "test", "version_id": "v1", "system": true}'
```

## Benefits

- ✅ Single storage account configuration
- ✅ No duplicate settings needed
- ✅ Automatic extraction of storage account name
- ✅ Consistent use of managed identity
- ✅ Works with Azure Functions' built-in settings