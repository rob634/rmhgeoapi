# Queue Trigger Managed Identity Configuration

## Problem
The queue trigger wasn't firing because it was configured to use `AzureWebJobsStorage` connection string while the rest of the app uses managed identity.

## Solution
Changed the queue trigger connection from `"AzureWebJobsStorage"` to `"Storage"` to use managed identity.

## Required Azure Function App Settings

For the queue trigger to work with managed identity, you need these Application Settings in your Azure Function App:

```json
{
  "Storage__queueServiceUri": "https://<your-storage-account>.queue.core.windows.net/",
  "STORAGE_ACCOUNT_NAME": "<your-storage-account>"
}
```

### Key Points:
1. **Connection Name**: The queue trigger now uses `connection="Storage"`
2. **Service URI Format**: Azure Functions expects `{ConnectionName}__queueServiceUri` format for managed identity
3. **Double Underscore**: Note the double underscore (`__`) between connection name and `queueServiceUri`

## Local Development

For local development, you have two options:

### Option 1: Use Connection String (Easier for local)
In `local.settings.json`:
```json
{
  "IsEncrypted": false,
  "Values": {
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "Storage": "DefaultEndpointsProtocol=https;AccountName=<account>;AccountKey=<key>;EndpointSuffix=core.windows.net",
    "STORAGE_ACCOUNT_NAME": "<your-storage-account>"
  }
}
```

### Option 2: Use Azure CLI Login (Matches production)
In `local.settings.json`:
```json
{
  "IsEncrypted": false,
  "Values": {
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "Storage__queueServiceUri": "https://<your-storage-account>.queue.core.windows.net/",
    "STORAGE_ACCOUNT_NAME": "<your-storage-account>"
  }
}
```
Then login with: `az login`

## Verification Steps

1. **Check Function App Identity**: Ensure your Function App has a system-assigned managed identity enabled
2. **Check RBAC**: The identity needs these roles on the storage account:
   - `Storage Queue Data Contributor` (for queue operations)
   - `Storage Table Data Contributor` (for job tracking table)
   - `Storage Blob Data Contributor` (if accessing blobs)

3. **Check Application Settings**: Verify the `Storage__queueServiceUri` is set correctly

## Debugging

The enhanced logging in the queue trigger will now show:
- When the trigger fires
- Message ID and dequeue count
- Message content details
- Any parsing errors

## Code Changes Made

1. **function_app.py:257**: Changed `connection="AzureWebJobsStorage"` to `connection="Storage"`
2. **function_app.py:264-315**: Added comprehensive logging for debugging queue message processing

## Why This Works

- Azure Functions runtime automatically uses `DefaultAzureCredential` when it sees the `__queueServiceUri` pattern
- The connection name "Storage" matches what's defined in `config.py:220` as `MANAGED_IDENTITY_CONNECTION`
- Both the queue client (for sending) and queue trigger (for receiving) now use the same storage account via managed identity