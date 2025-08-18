# Azure Function HTTP Triggers Not Working - Diagnosis

## Problem
- Queue trigger is working and visible in logs
- HTTP triggers return 404 Not Found
- Function App is running (state: "Running")

## Configuration Details
- **Function App**: rmhgeoapiqfn
- **URL**: https://rmhgeoapiqfn-h3dza4gyffbsbre7.eastus-01.azurewebsites.net
- **Runtime**: Python 3.12
- **SKU**: ElasticPremium
- **Identity**: System-assigned managed identity enabled

## Likely Issues and Solutions

### 1. **Python Version Mismatch**
Your Function App is using Python 3.12, but Azure Functions v2 programming model might have issues with 3.12.

**Solution**: Downgrade to Python 3.11:
```bash
az functionapp config set --name rmhgeoapiqfn --resource-group rmhazure_rg --linux-fx-version "Python|3.11"
```

### 2. **Missing FUNCTIONS_WORKER_RUNTIME**
Check if this application setting exists:
```bash
az functionapp config appsettings list --name rmhgeoapiqfn --resource-group rmhazure_rg | grep FUNCTIONS_WORKER_RUNTIME
```

**Solution**: Set it if missing:
```bash
az functionapp config appsettings set --name rmhgeoapiqfn --resource-group rmhazure_rg --settings FUNCTIONS_WORKER_RUNTIME=python
```

### 3. **Missing AzureWebJobsFeatureFlags for V2 Model**
The v2 programming model needs a feature flag.

**Solution**: Add this setting:
```bash
az functionapp config appsettings set --name rmhgeoapiqfn --resource-group rmhazure_rg --settings AzureWebJobsFeatureFlags=EnableWorkerIndexing
```

### 4. **Check Function App File Structure**
Verify the deployment included all files:
```bash
# SSH into the function app
az webapp ssh --name rmhgeoapiqfn --resource-group rmhazure_rg
# Then run:
ls -la /home/site/wwwroot/
cat /home/site/wwwroot/function_app.py | head -50
```

### 5. **Check for Import Errors**
Look for startup errors in logs:
```bash
az webapp log tail --name rmhgeoapiqfn --resource-group rmhazure_rg
```

## Complete Fix Script

Run these commands in order:

```bash
# 1. Set Python 3.11
az functionapp config set --name rmhgeoapiqfn --resource-group rmhazure_rg --linux-fx-version "Python|3.11"

# 2. Set required app settings
az functionapp config appsettings set --name rmhgeoapiqfn --resource-group rmhazure_rg --settings \
  FUNCTIONS_WORKER_RUNTIME=python \
  AzureWebJobsFeatureFlags=EnableWorkerIndexing \
  PYTHON_ISOLATE_WORKER_DEPENDENCIES=1

# 3. Restart the function app
az functionapp restart --name rmhgeoapiqfn --resource-group rmhazure_rg

# 4. Wait 30 seconds then test
sleep 30
curl https://rmhgeoapiqfn-h3dza4gyffbsbre7.eastus-01.azurewebsites.net/api/health
```

## Alternative: Use Function Core Tools

If the above doesn't work, try redeploying with func tools:

```bash
# From your project directory
func azure functionapp publish rmhgeoapiqfn --python
```

## Testing After Fix

Test endpoints:
```bash
# Health check
curl https://rmhgeoapiqfn-h3dza4gyffbsbre7.eastus-01.azurewebsites.net/api/health

# Submit a job
curl -X POST https://rmhgeoapiqfn-h3dza4gyffbsbre7.eastus-01.azurewebsites.net/api/jobs/hello_world \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "test", "resource_id": "test", "version_id": "v1", "system": true}'

# Check job status
curl https://rmhgeoapiqfn-h3dza4gyffbsbre7.eastus-01.azurewebsites.net/api/jobs/{job_id}
```

## Root Cause
The most common cause is the missing `AzureWebJobsFeatureFlags=EnableWorkerIndexing` setting, which is required for the v2 programming model (using `@app.route()` decorators) to work properly in Azure.