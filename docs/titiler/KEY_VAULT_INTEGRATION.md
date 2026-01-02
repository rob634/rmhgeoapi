# TiTiler Key Vault Integration Guide

**Date**: 26 OCT 2025
**Purpose**: Secure credential management for TiTiler using Azure Key Vault

## Overview

TiTiler-PgSTAC can integrate with Azure Key Vault to securely manage sensitive credentials like database passwords. This guide covers two approaches:

1. **Container Apps Secret References** (Recommended) - Native integration
2. **Dapr Secret Store** (Alternative) - More complex but flexible

## Current Key Vault

Your environment has:
- **Key Vault Name**: `rmhazurevault`
- **Resource Group**: `rmhazure_rg`
- **Location**: `eastus`

## Method 1: Container Apps Secret References (Recommended) ✅

This is the **simplest and most secure** approach for TiTiler.

### How It Works

```
Key Vault → Container App Secrets → Environment Variables → TiTiler
```

1. Store sensitive values in Key Vault
2. Container App references Key Vault secrets
3. Secrets are injected as environment variables
4. TiTiler reads them like normal env vars

### Step-by-Step Implementation

#### Step 1: Store PostgreSQL Password in Key Vault

```bash
# Store the password
az keyvault secret set \
  --vault-name rmhazurevault \
  --name postgres-password \
  --value "YOUR_ACTUAL_PASSWORD_HERE"

# Verify it's stored
az keyvault secret show \
  --vault-name rmhazurevault \
  --name postgres-password \
  --query "name" -o tsv
```

#### Step 2: Grant Container App Access to Key Vault

The container app's managed identity needs permission to read secrets:

```bash
# Get the managed identity principal ID
IDENTITY_ID=$(az containerapp identity show \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --query principalId -o tsv)

# Grant "Key Vault Secrets User" role
az role assignment create \
  --role "Key Vault Secrets User" \
  --assignee $IDENTITY_ID \
  --scope /subscriptions/$(az account show --query id -o tsv)/resourceGroups/rmhazure_rg/providers/Microsoft.KeyVault/vaults/rmhazurevault
```

#### Step 3: Create Container App Secret Reference

```bash
# Create a secret that references Key Vault
az containerapp secret set \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --secrets postgres-pass="keyvaultref:https://rmhazurevault.vault.azure.net/secrets/postgres-password,identityref:system"
```

#### Step 4: Use Secret in Environment Variable

```bash
# Reference the secret in an environment variable
az containerapp update \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --set-env-vars \
    POSTGRES_PASS="secretref:postgres-pass"
```

### Complete Configuration Example

```bash
# Set all environment variables with Key Vault reference for password
az containerapp update \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --set-env-vars \
    POSTGRES_HOST="rmhpgflex.postgres.database.azure.com" \
    POSTGRES_PORT="5432" \
    POSTGRES_USER="rmhadmin" \
    POSTGRES_DBNAME="postgres" \
    AZURE_STORAGE_ACCOUNT="rmhazuregeo" \
    AZURE_CLIENT_ID="managed_identity" \
  --secrets \
    postgres-pass="keyvaultref:https://rmhazurevault.vault.azure.net/secrets/postgres-password,identityref:system" \
  --set-env-vars \
    POSTGRES_PASS="secretref:postgres-pass"
```

### Advantages ✅
- No code changes in TiTiler
- Automatic secret rotation support
- Native Azure integration
- Simple to implement
- Secrets never in plain text

### Disadvantages ❌
- Requires container restart for secret updates
- Limited to environment variables

## Method 2: Dapr Secret Store (Alternative)

More complex but offers runtime secret access.

### How It Works

```
Key Vault ← Dapr Sidecar ← TiTiler (via HTTP API)
```

1. Enable Dapr on container app
2. Configure Dapr secret store component
3. TiTiler calls Dapr API to get secrets

### Implementation Steps

#### Step 1: Enable Dapr

```bash
az containerapp dapr enable \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --dapr-app-id titiler
```

#### Step 2: Configure Secret Store Component

```yaml
# Create dapr-secretstore.yaml
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: azurekeyvault
spec:
  type: secretstores.azure.keyvault
  metadata:
  - name: vaultName
    value: rmhazurevault
  - name: azureClientId
    value: [MANAGED_IDENTITY_CLIENT_ID]
```

#### Step 3: Apply Configuration

```bash
az containerapp dapr component set \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --yaml dapr-secretstore.yaml
```

### Advantages ✅
- Runtime secret access
- No restart needed for updates
- Can access multiple vaults

### Disadvantages ❌
- Requires code changes in TiTiler
- More complex setup
- Additional overhead

## Security Architecture

### How Credentials Flow in TiTiler

```
Client Request → TiTiler → PgSTAC Database
                    ↓
              Azure Storage

NO credentials in client requests!
```

1. **Client → TiTiler**:
   - Requests tiles via `/tiles/{z}/{x}/{y}`
   - No database credentials needed
   - Optional: API key for authentication

2. **TiTiler → PgSTAC**:
   - Uses `POSTGRES_PASS` from environment
   - Connection established on startup
   - Credentials never exposed to clients

3. **TiTiler → Storage**:
   - Uses managed identity (no password)
   - Or storage key from Key Vault
   - Streams COGs server-side

### Security Layers

| Layer | Protection | Implementation |
|-------|------------|----------------|
| **Storage** | Managed Identity RBAC | No secrets needed |
| **Database** | Key Vault secret | Password in Key Vault |
| **Network** | Private endpoints | Optional VNet integration |
| **Application** | API keys | Optional client auth |
| **Transport** | HTTPS/TLS | Enforced by Container Apps |

## Best Practices

### Do's ✅

1. **Use Key Vault for all secrets**
   ```bash
   # Store all sensitive values
   az keyvault secret set --vault-name rmhazurevault --name postgres-password --value "..."
   az keyvault secret set --vault-name rmhazurevault --name api-key --value "..."
   ```

2. **Use managed identity for storage**
   ```bash
   # No passwords needed
   AZURE_CLIENT_ID="managed_identity"
   ```

3. **Rotate secrets regularly**
   ```bash
   # Update in Key Vault - container auto-updates
   az keyvault secret set --vault-name rmhazurevault --name postgres-password --value "NEW_PASSWORD"
   ```

4. **Monitor access**
   ```bash
   # Check Key Vault access logs
   az monitor activity-log list --resource-id /subscriptions/.../providers/Microsoft.KeyVault/vaults/rmhazurevault
   ```

### Don'ts ❌

1. **Never hardcode passwords**
   ```bash
   # WRONG
   POSTGRES_PASS="ActualPassword123"  # ❌

   # RIGHT
   POSTGRES_PASS="secretref:postgres-pass"  # ✅
   ```

2. **Don't use storage keys if possible**
   ```bash
   # Prefer managed identity over keys
   AZURE_CLIENT_ID="managed_identity"  # ✅
   # Instead of
   AZURE_STORAGE_ACCESS_KEY="..."  # ❌
   ```

3. **Don't expose Key Vault to public**
   ```bash
   # Use private endpoints or firewall rules
   az keyvault update --name rmhazurevault --default-action Deny
   ```

## Validation and Testing

### 1. Verify Key Vault Access

```bash
# Check managed identity has access
IDENTITY_ID=$(az containerapp identity show --name rmhtitiler --resource-group rmhazure_rg --query principalId -o tsv)

az role assignment list \
  --assignee $IDENTITY_ID \
  --scope /subscriptions/$(az account show --query id -o tsv)/resourceGroups/rmhazure_rg/providers/Microsoft.KeyVault/vaults/rmhazurevault
```

### 2. Test Secret Resolution

```bash
# Check if secrets are configured
az containerapp secret list \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --query "[?contains(name, 'postgres')].name" -o table
```

### 3. Verify Container Startup

```bash
# Check logs for successful database connection
az containerapp logs show \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --tail 50 | grep -i "connect"
```

### 4. Test TiTiler Endpoints

```bash
# Health check
curl https://rmhtitiler.jollypond-54b50986.eastus.azurecontainerapps.io/

# List STAC collections (requires database connection)
curl https://rmhtitiler.jollypond-54b50986.eastus.azurecontainerapps.io/collections
```

## Troubleshooting

### Problem: "Access Denied" to Key Vault

```bash
# Fix: Grant role
az role assignment create \
  --role "Key Vault Secrets User" \
  --assignee $IDENTITY_ID \
  --scope /subscriptions/.../providers/Microsoft.KeyVault/vaults/rmhazurevault
```

### Problem: Secret not found

```bash
# Check secret exists
az keyvault secret list --vault-name rmhazurevault

# Check secret reference syntax
az containerapp secret list --name rmhtitiler --resource-group rmhazure_rg
```

### Problem: Container fails to start

```bash
# Check environment variables
az containerapp show --name rmhtitiler --resource-group rmhazure_rg --query "properties.template.containers[0].env"

# Check logs
az containerapp logs show --name rmhtitiler --resource-group rmhazure_rg --tail 100
```

## Quick Setup Script

Complete setup in one script:

```bash
#!/bin/bash

# Variables
KEYVAULT="rmhazurevault"
CONTAINER_APP="rmhtitiler"
RG="rmhazure_rg"
PG_PASSWORD="YOUR_SECURE_PASSWORD"

# 1. Store password in Key Vault
az keyvault secret set \
  --vault-name $KEYVAULT \
  --name postgres-password \
  --value "$PG_PASSWORD"

# 2. Get managed identity
IDENTITY_ID=$(az containerapp identity show \
  --name $CONTAINER_APP \
  --resource-group $RG \
  --query principalId -o tsv)

# 3. Grant Key Vault access
az role assignment create \
  --role "Key Vault Secrets User" \
  --assignee $IDENTITY_ID \
  --scope /subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RG/providers/Microsoft.KeyVault/vaults/$KEYVAULT

# 4. Configure container app with Key Vault reference
az containerapp update \
  --name $CONTAINER_APP \
  --resource-group $RG \
  --secrets postgres-pass="keyvaultref:https://$KEYVAULT.vault.azure.net/secrets/postgres-password,identityref:system" \
  --set-env-vars \
    POSTGRES_HOST="rmhpgflex.postgres.database.azure.com" \
    POSTGRES_PORT="5432" \
    POSTGRES_USER="rmhadmin" \
    POSTGRES_PASS="secretref:postgres-pass" \
    POSTGRES_DBNAME="postgres" \
    AZURE_STORAGE_ACCOUNT="rmhazuregeo" \
    AZURE_CLIENT_ID="managed_identity"

echo "✅ TiTiler configured with Key Vault integration"
```

## Summary

- **Use Method 1** (Container Apps Secret References) for simplicity
- Store all sensitive values in Key Vault
- Use managed identity for both Key Vault and Storage access
- Credentials are never exposed in client requests
- TiTiler handles all authentication server-side