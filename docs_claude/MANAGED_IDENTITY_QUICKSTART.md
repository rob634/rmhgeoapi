# Managed Identity Quick Start Guide

**TL;DR**: 5-minute setup for passwordless PostgreSQL authentication

---

## 🚀 Quick Setup (Production)

### 1. Enable Managed Identity
```bash
az functionapp identity assign \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg
```

### 2. Setup PostgreSQL User
```bash
psql "host=rmhpgflex.postgres.database.azure.com dbname=geopgflex sslmode=require" \
  < scripts/setup_managed_identity_postgres.sql
```

### 3. Configure Function App
```bash
az functionapp config appsettings set \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --settings \
    USE_MANAGED_IDENTITY=true \
    MANAGED_IDENTITY_NAME=rmhazuregeoapi-identity
```

### 4. Deploy & Test
```bash
# Deploy
func azure functionapp publish rmhazuregeoapi --python --build remote

# Test
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health
```

**Done!** No passwords needed.

---

## 💻 Local Development Setup

### Option 1: Azure CLI (Recommended)
```bash
az login
# Your code works unchanged - no config needed!
```

### Option 2: Password Fallback
```json
// local.settings.json
{
  "Values": {
    "USE_MANAGED_IDENTITY": "false",
    "POSTGIS_PASSWORD": "your-dev-password"
  }
}
```

---

## 🔍 Verify It's Working

### Check Logs
```bash
cat > /tmp/check_mi.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(15m) | where message contains 'managed identity' | take 10" \
  -G | python3 -m json.tool
EOF
chmod +x /tmp/check_mi.sh && /tmp/check_mi.sh
```

Look for: `"🔐 Using Azure Managed Identity for PostgreSQL authentication"`

### Check Database Connection
```bash
# Should show auth_method: "managed_identity"
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health | jq .database
```

---

## 🚨 Troubleshooting

| Problem | Solution |
|---------|----------|
| "No credentials available" (local) | Run `az login` |
| "Authentication failed" (Azure) | Re-run PostgreSQL setup script |
| "Token acquisition failed" | Verify managed identity enabled on Function App |

---

## 📚 Full Documentation

See [MANAGED_IDENTITY_MIGRATION.md](./MANAGED_IDENTITY_MIGRATION.md) for complete guide.
