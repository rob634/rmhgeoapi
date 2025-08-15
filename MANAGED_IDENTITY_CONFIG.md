# Azure Functions Managed Identity Configuration

## Queue Trigger Managed Identity Setup

The queue trigger now uses `connection="Storage"` which requires these app settings:

### Required App Settings (Azure Portal):

```
Storage__serviceUri = https://rmhazuregeo.queue.core.windows.net
Storage__queueServiceUri = https://rmhazuregeo.queue.core.windows.net
```

### Required Configuration Method

You must explicitly set the service URI app setting:
```
Storage__serviceUri = https://rmhazuregeo.queue.core.windows.net
```

**Note**: Azure Functions does NOT automatically construct service URIs from STORAGE_ACCOUNT_NAME.
You must manually configure the Storage__serviceUri app setting in Azure Portal.

### Managed Identity Permissions

Ensure the Function App's managed identity has these roles on the storage account:
- **Storage Queue Data Contributor** (to read from queues)
- **Storage Table Data Contributor** (to read/write job tracking table)
- **Storage Blob Data Contributor** (for container operations)

### Benefits:
✅ No connection strings in app settings
✅ Automatic key rotation
✅ Better security (no shared keys)
✅ Consistent with other Azure resources

### Local Development:
For local development, the code falls back to AzureWebJobsStorage connection string in local.settings.json