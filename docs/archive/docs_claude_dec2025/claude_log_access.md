# Application Insights Log Access Guide

**Date**: September 2, 2025  
**Author**: Claude Code Assistant  
**Purpose**: Document the step-by-step process for accessing Azure Application Insights logs via CLI and REST API

## Overview

This document outlines how to access Application Insights logs when the standard `az monitor app-insights query` command fails due to AAD authentication requirements. The solution uses bearer token authentication with the Application Insights REST API.

## Problem Statement

Initial attempts to access Application Insights logs failed with:
```bash
az monitor app-insights query --app rmhgeoapibeta --analytics-query "requests | take 10"
# ERROR: The Application Insight is not found. Please check the app id again.
```

The Function App configuration showed AAD authentication was required:
```
APPLICATIONINSIGHTS_AUTHENTICATION_STRING = Authorization=AAD
```

## Solution: Bearer Token Authentication

### Step 1: Azure CLI Login

First, authenticate with Azure CLI to establish proper credentials:

```bash
az login
```

**Output:**
```json
[
  {
    "cloudName": "AzureCloud",
    "homeTenantId": "086aef7e-db12-4161-8a9f-777deb499cfa",
    "id": "fc7a176b-9a1d-47eb-8a7f-08cc8058fcfa",
    "isDefault": true,
    "managedByTenants": [],
    "name": "rmhazure",
    "state": "Enabled",
    "tenantDefaultDomain": "{tenant}.onmicrosoft.com",
    "tenantDisplayName": "Rob634",
    "tenantId": "086aef7e-db12-4161-8a9f-777deb499cfa",
    "user": {
      "name": "{admin_email}",
      "type": "user"
    }
  }
]
```

### Step 2: Verify User Identity

Check the authenticated user details:

```bash
az ad signed-in-user show --query "{userPrincipalName: userPrincipalName, objectId: id}" --output table
```

**Output:**
```
UserPrincipalName                                  ObjectId
-------------------------------------------------  ------------------------------------
{admin_email}#EXT#@{tenant}.onmicrosoft.com  e6eec2c3-fa55-467a-81c7-1c0c0bb1d29d
```

### Step 3: Find Application Insights Configuration

List Application Insights components to find the correct App ID:

```bash
az monitor app-insights component show --resource-group rmhazure_rg --output table
```

**Key Output for rmhgeoapibeta:**
```
AppId                                 ApplicationId      Name               
------------------------------------  -----------------  -----------------  
829adb94-5f5c-46ae-9f00-18e731529222  rmhgeoapibeta      rmhgeoapibeta      
```

### Step 4: Check Function App Configuration

Verify Application Insights is properly configured:

```bash
az functionapp config appsettings list --name rmhgeoapibeta --resource-group rmhazure_rg --output table
```

**Critical Configuration Found:**
```
Name                                       Value
-----------------------------------------  --------------------------------------------------------------------------------------------------------------
APPLICATIONINSIGHTS_AUTHENTICATION_STRING  Authorization=AAD
APPLICATIONINSIGHTS_CONNECTION_STRING      InstrumentationKey=32ef235f-4bfc-416b-98e9-19b23fb266e1;IngestionEndpoint=https://eastus-8.in.applicationinsights.azure.com/;LiveEndpoint=https://eastus.livediagnostics.monitor.azure.com/;ApplicationId=829adb94-5f5c-46ae-9f00-18e731529222
```

### Step 5: Obtain Bearer Token

Get an access token for Application Insights API:

```bash
az account get-access-token --resource https://api.applicationinsights.io --query accessToken --output tsv
```

**Output:** (Token truncated for security)
```
eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsIng1dCI6IkpZaEFjVFBNWl9MWDZEQmxPV1E3SG4wTmVYRSIsImtpZCI6IkpZaEFjVFBNWl9MWDZEQmxPV1E3SG4wTmVYRSJ9...
```

### Step 6: Query Application Insights via REST API

Use the bearer token to access logs directly:

#### Method 1: Simple Query
```bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)

curl -H "Authorization: Bearer $TOKEN" \
     "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query?query=requests%20%7C%20take%2010"
```

#### Method 2: Complex Query with POST
```bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)

curl -H "Authorization: Bearer $TOKEN" \
     "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
     --data-urlencode 'query=traces | where timestamp >= ago(1h) | order by timestamp desc | take 20' \
     -G
```

## Key Identifiers

| Component | Value |
|-----------|-------|
| **App ID** | `829adb94-5f5c-46ae-9f00-18e731529222` |
| **Instrumentation Key** | `32ef235f-4bfc-416b-98e9-19b23fb266e1` |
| **Resource Group** | `rmhazure_rg` |
| **Function App** | `rmhgeoapibeta` |
| **User Object ID** | `e6eec2c3-fa55-467a-81c7-1c0c0bb1d29d` |

## Critical Findings from Logs

### Process Job Queue Failures
All `process_job_queue` functions show `"success":"False"` with `"LogLevel":"Error"`.

### Missing PostgreSQL Functions
Logs consistently show:
```
⚠️ Missing functions in schema 'app': ['complete_task_and_check_stage', 'advance_job_stage']
```

### Health Check Success
Health check functions execute successfully, confirming basic functionality works.

## Why Standard CLI Failed

1. **AAD Authentication Required**: Function App configured with `APPLICATIONINSIGHTS_AUTHENTICATION_STRING = Authorization=AAD`
2. **Bearer Token Needed**: CLI commands don't automatically handle AAD auth for Application Insights
3. **Permissions Model**: Bearer token approach uses the authenticated user's permissions directly

## Best Practices

### Reusable Query Script
Create a script for easy log querying:

```bash
#!/bin/bash
# app_insights_query.sh

APP_ID="829adb94-5f5c-46ae-9f00-18e731529222"
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)

QUERY="${1:-requests | take 10}"

curl -H "Authorization: Bearer $TOKEN" \
     "https://api.applicationinsights.io/v1/apps/$APP_ID/query" \
     --data-urlencode "query=$QUERY" \
     -G
```

**Usage:**
```bash
./app_insights_query.sh "traces | where timestamp >= ago(30m) | take 20"
```

### Common Queries

#### Recent Errors
```kql
traces 
| where timestamp >= ago(1h) 
| where severityLevel >= 3 
| order by timestamp desc 
| limit 20
```

#### Function Execution Status
```kql
requests 
| where timestamp >= ago(30m) 
| where name contains "process_job_queue" 
| project timestamp, name, success, resultCode, duration 
| order by timestamp desc
```

#### Job Processing Logs
```kql
traces 
| where timestamp >= ago(1h) 
| where message contains "job" or message contains "task" 
| order by timestamp desc 
| limit 50
```

## Troubleshooting

### Token Expiration
Bearer tokens expire after 1 hour. Re-run the token acquisition command:
```bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
```

### Invalid App ID
Verify the App ID matches the Function App configuration:
```bash
az functionapp config appsettings list --name rmhgeoapibeta --resource-group rmhazure_rg --query "[?name=='APPLICATIONINSIGHTS_CONNECTION_STRING']" --output table
```

### Query Syntax Errors
Use proper KQL (Kusto Query Language) syntax. Test queries in Azure Portal first.

## Security Considerations

- **Token Storage**: Never commit bearer tokens to version control
- **Token Scope**: Tokens are scoped to `https://api.applicationinsights.io`
- **User Permissions**: Access is based on the authenticated user's AAD permissions
- **Rotation**: Tokens automatically expire for security

## Conclusion

The bearer token approach successfully bypasses the CLI authentication issues and provides full access to Application Insights logs. This method is more reliable than the standard CLI commands when AAD authentication is required.

The critical discovery through this process was identifying the **missing PostgreSQL functions** that are causing job processing failures, which wouldn't have been visible without proper log access.