# Folder Structure Assessment & Cleanup Plan

**Created**: 02 JAN 2026
**Updated**: 02 JAN 2026
**Status**: In Progress
**Purpose**: Document folder structure analysis and consolidation recommendations

---

## Executive Summary

The rmhgeoapi project has 26 root-level folders. Analysis identified:
- **16 folders** with solid organization (keep as-is)
- **6 folders** recommended for consolidation (move/merge)
- **2 folders** to consider moving (optional)

Consolidation would reduce root folders from 26 to ~20 and improve discoverability.

---

## Current Folder Structure

### Core Architecture (Well-Organized)

| Folder | Purpose | Files | Status |
|--------|---------|-------|--------|
| `config/` | Configuration modules | 14 | ✅ Clean - domain-specific configs |
| `core/` | CoreMachine engine | 16 + 4 subfolders | ✅ Clean - models, logic, schema, contracts |
| `infrastructure/` | Repository layer | 31 | ✅ Clean - DB, blob, service bus |
| `jobs/` | ETL job definitions | 30 | ✅ Clean - one file per job type |
| `services/` | Business logic handlers | 47 + 4 subfolders | ✅ Clean - organized by domain |
| `triggers/` | Azure Functions endpoints | 25 + 3 subfolders | ✅ Clean - HTTP/timer triggers |

### API Modules (Consistent Pattern)

All follow the same pattern: `__init__.py` + `triggers.py` + `service.py` + optional `config.py`/`models.py`

| Folder | Purpose | Status |
|--------|---------|--------|
| `ogc_features/` | OGC Features API | ✅ Well-structured |
| `ogc_styles/` | OGC Styles API | ✅ Well-structured |
| `raster_api/` | Raster extraction API | ✅ Well-structured |
| `stac_api/` | STAC catalog API | ✅ Well-structured |
| `xarray_api/` | XArray/Zarr API | ✅ Well-structured |
| `raster_collection_viewer/` | Raster collection viewer | ✅ Well-structured |
| `vector_viewer/` | Vector viewer | ✅ Well-structured |

### Web Interfaces

| Folder | Subfolders | Status |
|--------|------------|--------|
| `web_interfaces/` | 28 interface modules | ✅ Each interface has own folder |

### Documentation

| Folder | Purpose | Status |
|--------|---------|--------|
| `docs/` | User documentation | ✅ Well-organized with subfolders |
| `docs_claude/` | Claude-specific docs | ✅ Good - 33 planning/reference docs |

### Test & Support

| Folder | Purpose | Status |
|--------|---------|--------|
| `test/` | Test files | ✅ Keep |

---

## Issues Identified

### 1. ~~`titiler/` - Documentation Only, No Code~~ ✅ RESOLVED

**Status**: Moved to `docs/titiler/` on 02 JAN 2026

**Contents** (18 files - now in `docs/titiler/`):
- 15 markdown documentation files
- 2 SQL scripts
- 1 shell script

---

### 2. ~~`fathom/` - Single Markdown File~~ ✅ RESOLVED

**Status**: Moved `FATHOM.md` to `docs_claude/` on 02 JAN 2026

---

### 3. ~~`models/` - Underutilized (2 files)~~ ✅ RESOLVED

**Status**: Consolidated on 02 JAN 2026
- `band_mapping.py` → `core/models/band_mapping.py` (active, imports updated)
- `h3_base.py` → `docs/archive/models/` (dead code, archived)
- `models/` folder deleted

---

### 4. ~~`routes/` - Only 2 Files~~ ✅ RESOLVED

**Status**: Consolidated on 02 JAN 2026
- `admin_db.py` → `triggers/admin/admin_db.py`
- `admin_servicebus.py` → `triggers/admin/admin_servicebus.py`
- Updated `triggers/admin/__init__.py` to export blueprints
- Updated `function_app.py` import
- `routes/` folder deleted

---

### 5. `utils/` - Only 2 Files

**Current Contents**:
```
utils/
├── contract_validator.py
└── import_validator.py
```

**Problem**: Only 2 files - `core/` already has `utils.py` and `infrastructure/` has `validators.py`

**Recommendation**: Merge into `core/` or `infrastructure/`
- `contract_validator.py` → `core/`
- `import_validator.py` → `infrastructure/`

---

### 6. `sql/` - Only Contains Subfolder

**Current Contents**:
```
sql/
└── init/
    └── (initialization scripts)
```

**Problem**: Unnecessary nesting - folder only contains one subfolder

**Recommendation**: Flatten `sql/init/*` to `sql/` or move to `infrastructure/sql/`

---

### 7. `scripts/` - Utility Scripts (Consider)

**Current Contents**:
```
scripts/
├── copy_era5_subset.py
├── copy_gridmet_subset.py
├── setup_managed_identity_postgres.sql
├── test_database_stats.py
├── validate_config.py
└── verify_managed_identity_setup.sql
```

**Recommendation**: Keep, but consider:
- Move SQL scripts to `sql/`
- Move test script to `test/`

---

### 8. `openapi/` - API Specs (Consider)

**Current Contents**:
```
openapi/
├── ddhapiv1.csv
├── platform-api-v1.json
└── platform-api-v1.yaml
```

**Recommendation**: Keep, or move to `docs/api/`

---

## Cleanup TODO

### Phase 1: Documentation Folders

- [x] **TODO-1.1**: Move `titiler/` contents to `docs/titiler/` ✅ 02 JAN 2026
- [x] **TODO-1.2**: Delete empty `titiler/` folder ✅ 02 JAN 2026
- [x] **TODO-1.3**: Move `fathom/FATHOM.md` to `docs_claude/` ✅ 02 JAN 2026
- [x] **TODO-1.4**: Delete empty `fathom/` folder ✅ 02 JAN 2026

### Phase 2: Model Consolidation

- [x] **TODO-2.1**: Move `models/band_mapping.py` to `core/models/` ✅ 02 JAN 2026
- [x] **TODO-2.2**: Archive `models/h3_base.py` (dead code) → `docs/archive/models/` ✅ 02 JAN 2026
- [x] **TODO-2.3**: Update imports in `services/tiling_scheme.py`, `services/tiling_extraction.py` ✅ 02 JAN 2026
- [x] **TODO-2.4**: Delete `models/` folder ✅ 02 JAN 2026

### Phase 3: Routes Consolidation

- [x] **TODO-3.1**: Move `routes/admin_db.py` to `triggers/admin/` ✅ 02 JAN 2026
- [x] **TODO-3.2**: Move `routes/admin_servicebus.py` to `triggers/admin/` ✅ 02 JAN 2026
- [x] **TODO-3.3**: Update imports in `function_app.py` and `triggers/admin/__init__.py` ✅ 02 JAN 2026
- [x] **TODO-3.4**: Delete `routes/` folder ✅ 02 JAN 2026

### Phase 4: Utils Consolidation

- [ ] **TODO-4.1**: Move `utils/contract_validator.py` to `core/`
- [ ] **TODO-4.2**: Move `utils/import_validator.py` to `infrastructure/`
- [ ] **TODO-4.3**: Update imports across codebase
- [ ] **TODO-4.4**: Delete empty `utils/` folder

### Phase 5: SQL Consolidation

- [ ] **TODO-5.1**: Flatten `sql/init/*` to `sql/`
- [ ] **TODO-5.2**: Move SQL scripts from `scripts/` to `sql/`

### Phase 6: Optional Moves

- [ ] **TODO-6.1**: Consider moving `openapi/` to `docs/api/`
- [ ] **TODO-6.2**: Consider moving test scripts from `scripts/` to `test/`

---

## Impact Summary

| Metric | Before | After |
|--------|--------|-------|
| Root folders | 26 | ~20 |
| Empty/near-empty folders | 6 | 0 |
| Documentation in code folders | 2 | 0 |
| Model locations | 2 | 1 |

---

## Execution Commands

### Phase 1: Documentation
```bash
# Move titiler docs
mkdir -p docs/titiler
mv titiler/* docs/titiler/
rmdir titiler

# Move fathom doc
mv fathom/FATHOM.md docs_claude/
rmdir fathom
```

### Phase 2: Models
```bash
# Move model files
mv models/band_mapping.py core/models/
mv models/h3_base.py core/models/

# Update imports (grep to find affected files first)
grep -r "from models\." --include="*.py" .
grep -r "import models\." --include="*.py" .

# After updating imports:
rmdir models
```

### Phase 3: Routes
```bash
# Move route files
mv routes/admin_db.py triggers/admin/
mv routes/admin_servicebus.py triggers/admin/

# Update imports
grep -r "from routes\." --include="*.py" .

# After updating imports:
rmdir routes
```

### Phase 4: Utils
```bash
# Move util files
mv utils/contract_validator.py core/
mv utils/import_validator.py infrastructure/

# Update imports
grep -r "from utils\." --include="*.py" .

# After updating imports:
rmdir utils
```

---

## Notes

- All moves require updating imports across the codebase
- Test after each phase to ensure nothing breaks
- Consider creating git branch for cleanup work
- Some files may have circular import issues after moving

---

## Appendix: Full Folder Tree (Current)

```
rmhgeoapi/
├── config/              # ✅ Keep - Configuration modules
├── core/                # ✅ Keep - CoreMachine engine
│   ├── contracts/
│   ├── logic/
│   ├── models/
│   └── schema/
├── docs/                # ✅ Keep - User documentation
│   └── titiler/         # ✅ Moved here 02 JAN 2026
├── docs_claude/         # ✅ Keep - Claude documentation (FATHOM.md moved here)
├── infrastructure/      # ✅ Keep - Repository layer
├── jobs/                # ✅ Keep - Job definitions
├── ogc_features/        # ✅ Keep - OGC Features API
├── ogc_styles/          # ✅ Keep - OGC Styles API
├── openapi/             # ⚠️ Consider - API specs
├── raster_api/          # ✅ Keep - Raster API
├── raster_collection_viewer/  # ✅ Keep - Viewer
├── scripts/             # ⚠️ Consider - Utility scripts
├── services/            # ✅ Keep - Business logic
│   ├── curated/
│   ├── h3_aggregation/
│   ├── ingest/
│   └── vector/
├── sql/                 # ⚠️ Flatten - Unnecessary nesting
├── stac_api/            # ✅ Keep - STAC API
├── test/                # ✅ Keep - Tests
├── triggers/            # ✅ Keep - Azure Functions
│   ├── admin/
│   ├── curated/
│   └── janitor/
├── utils/               # ❌ Merge - Only 2 files
├── vector_viewer/       # ✅ Keep - Viewer
├── web_interfaces/      # ✅ Keep - UI interfaces
└── xarray_api/          # ✅ Keep - XArray API
```

Legend:
- ✅ Keep as-is
- ❌ Move/merge recommended
- ⚠️ Consider moving (optional)

---

## Change Log

| Date | Action | Details |
|------|--------|---------|
| 02 JAN 2026 | Created | Initial folder assessment |
| 02 JAN 2026 | TODO-1.1, 1.2 | Moved `titiler/` (18 files) → `docs/titiler/` |
| 02 JAN 2026 | TODO-1.3, 1.4 | Moved `fathom/FATHOM.md` → `docs_claude/`, deleted folder |
| 02 JAN 2026 | TODO-2.1-2.4 | Consolidated `models/`: `band_mapping.py` → `core/models/`, `h3_base.py` archived |
| 02 JAN 2026 | TODO-3.1-3.4 | Consolidated `routes/`: blueprints → `triggers/admin/`, updated imports |
