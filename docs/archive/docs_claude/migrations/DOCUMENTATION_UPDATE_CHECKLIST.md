# Documentation Update Checklist - EP1 to B3 Migration

**Date**: 12 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Track required documentation updates after migration to B3 App Service Plan

---

## 📋 Required Updates Summary

### Old Configuration (EP1 Premium)
- **Function App**: `rmhgeoapibeta`
- **URL**: `https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net`
- **App Service Plan**: `ASP-rmhazurerg-8bec` (ElasticPremium EP1)
- **Tier**: ElasticPremium
- **Resources**: 1 vCPU, 3.5 GB RAM
- **Cost**: ~$165/month

### New Configuration (B3 Basic)
- **Function App**: `rmhazuregeoapi`
- **URL**: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net`
- **App Service Plan**: `ASP-rmhazure` (Basic B3)
- **Tier**: Basic
- **Resources**: 4 vCPU, 7 GB RAM
- **Cost**: ~$80/month

---

## 📄 Files Requiring Updates

### 1. CLAUDE.md ⚠️ **HIGH PRIORITY**

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/CLAUDE.md`

#### Lines 271-279: Key URLs Section
```markdown
**CURRENT (INCORRECT)**:
**Key URLs**:
- Function App: https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net (**ONLY** active app)
- Database: rmhpgflex.postgres.database.azure.com (geo schema)
- Resource Group: `rmhazure_rg` (NOT rmhresourcegroup)

**🚨 CRITICAL DEPLOYMENT INFO:**
- **ACTIVE FUNCTION APP**: `rmhgeoapibeta` (ONLY this one!)
- **DEPRECATED APPS**: `rmhazurefn`, `rmhgeoapi`, `rmhgeoapifn` (NEVER use these)
- **DEPLOYMENT COMMAND**: `func azure functionapp publish rmhgeoapibeta --python --build remote`

**UPDATE TO**:
**Key URLs**:
- Function App: https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net (**ONLY** active app)
- Database: rmhpgflex.postgres.database.azure.com (geo schema)
- Resource Group: `rmhazure_rg` (NOT rmhresourcegroup)

**🚨 CRITICAL DEPLOYMENT INFO:**
- **ACTIVE FUNCTION APP**: `rmhazuregeoapi` (B3 Basic - ONLY active app!)
- **DEPRECATED APPS**: `rmhazurefn`, `rmhgeoapi`, `rmhgeoapifn`, `rmhgeoapibeta` (NEVER use these)
- **DEPLOYMENT COMMAND**: `func azure functionapp publish rmhazuregeoapi --python --build remote`
- **MIGRATION**: Migrated from EP1 Premium to B3 Basic (12 NOV 2025) - See EP1_TO_B3_MIGRATION_SUMMARY.md
```

#### Lines 281-296: POST-DEPLOYMENT TESTING
**Find/Replace**: `rmhgeoapibeta-dzd8gyasenbkaqax` → `rmhazuregeoapi-a3dma3ctfdgngwf6`

Replace in these curl commands:
- Health Check (line 284)
- Schema Redeploy (line 287)
- Submit Test Job (line 290)
- Check Job Status (line 295)

#### Lines 305-337: STAC & OGC Features API Examples
**Find/Replace**: `rmhgeoapibeta-dzd8gyasenbkaqax` → `rmhazuregeoapi-a3dma3ctfdgngwf6`

Replace in 12 curl examples:
- STAC nuclear button commands (lines 305, 308, 311)
- OGC Features API examples (lines 318, 321, 324, 327, 330, 333, 336)

#### Lines 369-409: DATABASE DEBUGGING ENDPOINTS
**Find/Replace**: `rmhgeoapibeta-dzd8gyasenbkaqax` → `rmhazuregeoapi-a3dma3ctfdgngwf6`

Replace in 15 curl examples for database endpoints.

#### Lines 461-464: Application Insights Key Identifiers
**VERIFY (NO CHANGE NEEDED)** - App Insights ID remains same:
- **App ID**: `829adb94-5f5c-46ae-9f00-18e731529222`
- **Resource Group**: `rmhazure_rg`
- **Function App**: ~~`rmhgeoapibeta`~~ → **UPDATE TO** `rmhazuregeoapi`

#### Line 531: Current Architecture Monolith
```markdown
**CURRENT**:
Azure Function App: rmhgeoapibeta

**UPDATE TO**:
Azure Function App: rmhazuregeoapi (B3 Basic tier)
```

**Total URL References in CLAUDE.md**: ~30 instances

---

### 2. docs_claude/DEPLOYMENT_GUIDE.md ⚠️ **HIGH PRIORITY**

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/docs_claude/DEPLOYMENT_GUIDE.md`

#### Lines 10-12: Primary Deployment Command
```markdown
**CURRENT**:
func azure functionapp publish rmhgeoapibeta --build remote

**UPDATE TO**:
func azure functionapp publish rmhazuregeoapi --python --build remote
```

#### Lines 15-32: Post-Deployment Verification
**Find/Replace**: `rmhgeoapibeta-dzd8gyasenbkaqax` → `rmhazuregeoapi-a3dma3ctfdgngwf6`

Replace in 5 curl commands.

#### Lines 38-43: Azure Resources - Function App
```markdown
**CURRENT**:
### Function App
- **Name**: rmhgeoapibeta
- **URL**: https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net
- **Runtime**: Python 3.12
- **Plan**: Premium (Elastic)
- **Region**: East US

**UPDATE TO**:
### Function App
- **Name**: rmhazuregeoapi
- **URL**: https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net
- **Runtime**: Python 3.12
- **Plan**: Basic B3 (App Service Plan: ASP-rmhazure)
- **Region**: East US
- **Migrated**: 12 NOV 2025 from rmhgeoapibeta (EP1 Premium)
```

#### Lines 107-110: Using Azure CLI
```markdown
**CURRENT**:
az webapp log tail --name rmhgeoapibeta --resource-group rmhazure_rg
az webapp log download --name rmhgeoapibeta --resource-group rmhazure_rg --log-file webapp_logs.zip

**UPDATE TO**:
az webapp log tail --name rmhazuregeoapi --resource-group rmhazure_rg
az webapp log download --name rmhazuregeoapi --resource-group rmhazure_rg --log-file webapp_logs.zip
```

#### Lines 120-250: All Database/Monitoring Endpoints
**Find/Replace**: `rmhgeoapibeta-dzd8gyasenbkaqax` → `rmhazuregeoapi-a3dma3ctfdgngwf6`

Replace in ~20 curl examples throughout monitoring section.

#### Lines 267-290: Deployment Checklist
**Update app name**: `rmhgeoapibeta` → `rmhazuregeoapi`

Replace in:
- Deployment command (line 267)
- Rollback commands (lines 281, 283, 287, 289)

#### Lines 317: Critical Warnings
```markdown
**CURRENT**:
1. **NEVER** deploy to deprecated apps (rmhazurefn, rmhgeoapi, rmhgeoapifn)

**UPDATE TO**:
1. **NEVER** deploy to deprecated apps (rmhazurefn, rmhgeoapi, rmhgeoapifn, rmhgeoapibeta)
```

**Total URL References in DEPLOYMENT_GUIDE.md**: ~35 instances

---

### 3. docs_claude/CLAUDE_CONTEXT.md ⚠️ **MEDIUM PRIORITY**

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/docs_claude/CLAUDE_CONTEXT.md`

**Note**: Only check if there are any explicit references to the function app URL or name. Most of this file is architecture-focused, not deployment-focused.

**Scan for**: References to `rmhgeoapibeta` or the old URL (typically minimal in this file)

---

### 4. docs_claude/TODO.md ✅ **ALREADY UPDATED**

**Status**: ✅ Already updated during migration with new tasks

---

### 5. docs_claude/HISTORY.md 📝 **ADD ENTRY**

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/docs_claude/HISTORY.md`

**Action**: Add migration entry to history log

```markdown
## 12 NOV 2025 - Migration to B3 Basic App Service Plan

**Migration**: EP1 Premium → B3 Basic App Service Plan
**Author**: Robert and Geospatial Claude Legion

### Changes
- ✅ Migrated from `rmhgeoapibeta` (EP1 Premium) to `rmhazuregeoapi` (B3 Basic)
- ✅ 34 app settings migrated successfully
- ✅ Managed Identity configured with Service Bus & Storage roles
- ✅ Database schema deployed successfully
- ✅ Test job completed successfully (6 seconds)
- ✅ All systems operational

### Cost Impact
- Monthly savings: $85 (51% reduction: $165 → $80)
- Annual savings: $1,020

### Performance Improvement
- vCPUs: 1 → 4 (400% increase)
- RAM: 3.5 GB → 7 GB (100% increase)
- Timeout: Unbounded (same as EP1)

### Documentation
- Created: `EP1_TO_B3_MIGRATION_SUMMARY.md`
- Updated: `TODO.md` with migration tasks

**Commit**: 4f75ced - "Migrate Azure Functions from EP1 Premium to B3 Basic tier"
```

---

### 6. docs_claude/EP1_TO_B3_MIGRATION_SUMMARY.md ✅ **ALREADY CREATED**

**Status**: ✅ Created during migration (451 lines)

---

### 7. README.md (if exists) ⚠️ **CHECK IF EXISTS**

**Action**: Check if project has a README.md at root level that references the function app

---

## 🔍 Search Pattern for Finding All References

### Global Search Command
```bash
# From project root
grep -r "rmhgeoapibeta" . --exclude-dir=.git --exclude-dir=__pycache__ --exclude="*.pyc"

# Search for old URL
grep -r "rmhgeoapibeta-dzd8gyasenbkaqax" . --exclude-dir=.git --exclude-dir=__pycache__
```

### Files to Exclude from Search
- `*.pyc` - Compiled Python
- `__pycache__/` - Python cache
- `.git/` - Git history
- `node_modules/` - If any JS tools
- `.venv/` or `venv/` - Virtual environment

---

## 📊 Update Summary

| File | URL References | App Name References | Priority | Status |
|------|----------------|---------------------|----------|--------|
| **CLAUDE.md** | ~30 | ~5 | HIGH | ⏳ Pending |
| **DEPLOYMENT_GUIDE.md** | ~35 | ~10 | HIGH | ⏳ Pending |
| **CLAUDE_CONTEXT.md** | 0-2 | 0-2 | MEDIUM | ⏳ Pending |
| **TODO.md** | 0 | 0 | LOW | ✅ Complete |
| **HISTORY.md** | 0 | 1 | MEDIUM | ⏳ Pending (add entry) |
| **EP1_TO_B3_MIGRATION_SUMMARY.md** | N/A | N/A | N/A | ✅ Complete |

**Total Estimated Updates**: ~70-80 URL replacements + 15-20 app name updates

---

## ✅ Verification Checklist

After making updates, verify:

- [ ] All `rmhgeoapibeta` references updated to `rmhazuregeoapi`
- [ ] All old URLs updated to new URL
- [ ] Deployment commands reference correct app name
- [ ] Application Insights app name updated (but App ID stays same)
- [ ] Deprecated apps list includes `rmhgeoapibeta`
- [ ] Migration context added where appropriate
- [ ] HISTORY.md entry added for 12 NOV 2025
- [ ] Run global search to verify no old references remain

---

## 🚨 Important Notes

1. **Application Insights App ID**: Remains **same** across both function apps
   - App ID: `829adb94-5f5c-46ae-9f00-18e731529222`
   - Both apps report to same Application Insights instance

2. **Resource Group**: No change
   - Still `rmhazure_rg`

3. **Database**: No change
   - Still `rmhpgflex.postgres.database.azure.com`

4. **Storage Account**: No change
   - Still `rmhazuregeo`

5. **Service Bus**: No change
   - Still `rmhazure.servicebus.windows.net`

6. **Only Changes**: Function App name and URL

---

## 📅 Update Schedule

**Recommended**: Update all documentation **before** decommissioning EP1 app (48 hours from 12 NOV 2025)

**Deadline**: 14 NOV 2025 (before EP1 app deletion)

---

*Last Updated: 12 NOV 2025 22:52 UTC*
*Author: Robert and Geospatial Claude Legion*
