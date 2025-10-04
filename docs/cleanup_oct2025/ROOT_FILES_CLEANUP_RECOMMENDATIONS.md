# Root Files - Cleanup Recommendations

**Date**: 4 OCT 2025
**Current**: 24 files in root
**Target**: ~12 essential files

---

## 📋 Analysis Results

### ✅ KEEP - Essential Files (12 files)

**Azure Functions Core (4 files):**
- `.funcignore` - Azure Functions ignore patterns ✅
- `function_app.py` - Main entry point ✅
- `host.json` - Runtime config ✅
- `requirements.txt` - Dependencies ✅

**Application Code (3 files):**
- `config.py` - Pydantic configuration ✅
- `exceptions.py` - Custom exceptions ✅
- `util_logger.py` - Centralized logging ✅

**Configuration (3 files):**
- `local.settings.json` - Local dev settings ✅
- `local.settings.example.json` - Settings template ✅
- `.gitignore` - Git ignore patterns ✅

**Docker & Docs (2 files):**
- `docker-compose.yml` - PostgreSQL setup ✅ (for local dev)
- `CLAUDE.md` - Primary documentation ✅

---

### ⚠️ CONDITIONALLY KEEP (1 file)

**import_validation_registry.json** (8.5 KB)
- **Used By**: `triggers/health.py` (checks file existence and size)
- **Purpose**: Import validation tracking for health endpoint
- **Decision**: ✅ **KEEP** - Actively used by health endpoint

---

### ❌ DELETE - Obsolete Files (2 files, ~20 KB)

1. **missing_methods_analysis.txt** (920 B)
   - Temporary analysis file
   - Not referenced anywhere
   - **Action**: DELETE

2. **service_stac_setup.py.backup** (19 KB)
   - Old backup file
   - Real version exists in `services/service_stac_setup.py`
   - **Action**: DELETE

---

### 📁 MOVE - Documentation & Config (8 files, ~76 KB)

#### Analysis Documents (6 files, ~58 KB)
Move to `docs/cleanup_oct2025/` or DELETE:

1. CLEANUP_SUMMARY_4OCT2025.md (5.1 KB)
2. FINAL_CLEANUP_SUMMARY.md (8.8 KB)
3. INTERFACES_ARCHITECTURE_ANALYSIS.md (6.7 KB)
4. INTERFACES_FOLDER_FINDINGS.md (3.3 KB)
5. PROJECT_INVENTORY.md (17 KB)
6. ROOT_FOLDERS_ANALYSIS.md (8 KB)
7. TEST_FILES_ANALYSIS.md (9 KB)

**Recommendation**: Move to `docs/cleanup_oct2025/` for historical reference

#### Config Files (2 files, ~9 KB)
Move to `local/`:

8. **local.settings.test.json** (1 KB)
   - Test environment settings
   - Not referenced in code
   - **Action**: Move to `local/`

9. **service_bus.json** (8 KB)
   - Service Bus documentation/planning file (not config)
   - Contains H3 hexagon processing notes
   - Not referenced in code
   - **Action**: Move to `docs/` or `archive/reference/`

---

## 🎯 Execution Plan

### Step 1: Delete Obsolete (2 files)
```bash
rm missing_methods_analysis.txt
rm service_stac_setup.py.backup
```

### Step 2: Move Analysis Docs (6 files)
```bash
mkdir -p docs/cleanup_oct2025
mv CLEANUP_SUMMARY_4OCT2025.md docs/cleanup_oct2025/
mv FINAL_CLEANUP_SUMMARY.md docs/cleanup_oct2025/
mv INTERFACES_ARCHITECTURE_ANALYSIS.md docs/cleanup_oct2025/
mv INTERFACES_FOLDER_FINDINGS.md docs/cleanup_oct2025/
mv PROJECT_INVENTORY.md docs/cleanup_oct2025/
mv ROOT_FOLDERS_ANALYSIS.md docs/cleanup_oct2025/
mv TEST_FILES_ANALYSIS.md docs/cleanup_oct2025/
```

### Step 3: Move Config/Planning Files (2 files)
```bash
mv local.settings.test.json local/
mv service_bus.json docs/  # Planning/documentation file
```

---

## ✅ Final Root Files (13 files, ~115 KB)

After cleanup, only these files remain in root:

```
.funcignore                      # Azure Functions ignore
.gitignore                       # Git ignore
CLAUDE.md                        # Primary documentation
config.py                        # Pydantic configuration
docker-compose.yml               # Docker PostgreSQL
exceptions.py                    # Custom exceptions
function_app.py                  # Azure Functions entry
host.json                        # Functions runtime config
import_validation_registry.json  # Health endpoint tracking
local.settings.example.json      # Settings template
local.settings.json              # Local settings
requirements.txt                 # Python dependencies
util_logger.py                   # Centralized logging
```

**All essential, no clutter!**

---

## 📊 Impact

### Before Cleanup:
- 24 files in root
- Mix of code, docs, config, backups
- Cluttered and confusing

### After Cleanup:
- 13 files in root (54% reduction)
- Only essential application files
- Clean, professional structure

### Files Moved:
- 6 analysis docs → `docs/cleanup_oct2025/`
- 2 config files → `local/` or `docs/`
- 2 obsolete files → deleted

**Total Space**: ~96 KB moved/deleted, ~115 KB remaining

---

## 🚀 Execute Now?

**Safe to execute immediately:**
1. ✅ Delete 2 obsolete files (backup + analysis)
2. ✅ Move 6 analysis docs to docs/cleanup_oct2025/
3. ✅ Move 2 config files to appropriate locations

**Result**: Clean root with only 13 essential files!
