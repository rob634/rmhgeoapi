# WIKI Documentation Review

**Date**: 03 DEC 2025
**Purpose**: Assess freshness and accuracy of all WIKI_*.md files before transfer to Azure DevOps Wiki
**Author**: Robert and Geospatial Claude Legion

---

## Summary

| File | Lines | Last Updated | Status | Action Needed |
|------|-------|--------------|--------|---------------|
| WIKI_QUICK_START.md | 286 | 24 NOV 2025 | ✅ CURRENT | Minor update (add process_raster_v2) |
| WIKI_TECHNICAL_OVERVIEW.md | 698 | 18 NOV 2025 | ✅ CURRENT | None |
| WIKI_API_JOB_SUBMISSION.md | 1611 | 28 NOV 2025 | ✅ CURRENT | None |
| WIKI_API_DATABASE.md | 442 | 24 NOV 2025 | ✅ CURRENT | None |
| WIKI_API_ERRORS.md | 848 | 29 NOV 2025 | ✅ CURRENT | None |
| WIKI_API_GLOSSARY.md | 262 | 24 NOV 2025 | ✅ CURRENT | None |
| WIKI_API_SERVICE_BUS.md | 1467 | 24 NOV 2025 | ✅ CURRENT | None |
| WIKI_API_STORAGE.md | 514 | 24 NOV 2025 | ✅ CURRENT | None |
| WIKI_JOB_PROCESS_RASTER_V2.md | 378 | 28 NOV 2025 | ✅ CURRENT | None - this IS the v2 doc |
| WIKI_SCHEMA_REBUILD_SQL.md | 636 | 25 NOV 2025 | ✅ CURRENT | None |
| WIKI_API_PROCESS_RASTER_TRACETHROUGH.md | 1442 | 22 NOV 2025 | ⚠️ OUTDATED | Update to v2 or archive |
| WIKI_API_PROCESS_RASTER_COLLECTION_TRACETHROUGH.md | ~1300 | 22 NOV 2025 | ⚠️ OUTDATED | Update to v2 or archive |

**Status Legend**:
- ✅ CURRENT - Documentation matches current codebase
- ⚠️ OUTDATED - References deprecated code/patterns
- ❌ OBSOLETE - Should be archived, no longer relevant

---

## Detailed File Reviews

---

### WIKI_QUICK_START.md

**Status**: ✅ CURRENT (Minor update needed)

| Attribute | Value |
|-----------|-------|
| Lines | 286 |
| Last Updated | 24 NOV 2025 |
| Audience | New team members and developers |

**Content Summary**:
- Prerequisites checklist
- Base URL reference
- Step-by-step first job submission (hello_world)
- Job status checking
- OGC Features API usage
- Common commands reference
- Typical workflows (ingest vector, process raster, create collection)

**Accuracy Assessment**:
- ✅ Base URL correct: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net`
- ✅ hello_world job example current
- ✅ Job status endpoint correct
- ✅ OGC Features API endpoints correct
- ⚠️ Job Types table lists `process_raster` but not `process_raster_v2`

**Action Items**:
1. Add `process_raster_v2` to Job Types Quick Reference table
2. Consider updating "Workflow 2: Process Raster Data" section to mention v2

---

### WIKI_TECHNICAL_OVERVIEW.md

**Status**: ✅ CURRENT

| Attribute | Value |
|-----------|-------|
| Lines | 698 |
| Last Updated | 18 NOV 2025 |
| Audience | Development team (all disciplines) |

**Content Summary**:
- High-level platform architecture explanation
- Serverless (Azure Functions) concepts for non-experts
- Fan-out/Fan-in distributed patterns
- Idempotency explanation
- Last Task Completion Detection pattern
- FOSS stack overview (GDAL, Shapely, GeoPandas, Rasterio, PostGIS, COG, TiTiler, STAC, OGC API)
- Complete workflow example
- Front-end consumption patterns

**Accuracy Assessment**:
- ✅ Architecture patterns correctly explained
- ✅ Distributed systems concepts accurate
- ✅ FOSS stack descriptions current
- ✅ Code examples use correct libraries
- ✅ Conceptual explanations still valid

**Action Items**: None - This is conceptual documentation that remains accurate.

---

### WIKI_API_JOB_SUBMISSION.md

**Status**: ✅ CURRENT

| Attribute | Value |
|-----------|-------|
| Lines | 1611 |
| Last Updated | 28 NOV 2025 |
| Audience | API consumers, developers |

**Content Summary**:
- Two API patterns: CoreMachine vs Platform
- All job types with parameters
- hello_world, process_vector, process_raster, process_raster_collection docs
- Real test results with verified data (ACLED 2.57M rows, Namangan imagery)
- Admin/maintenance endpoints with safety warnings
- Testing workflow

**Accuracy Assessment**:
- ✅ CoreMachine vs Platform distinction correct
- ✅ Base URL correct
- ✅ process_vector documentation comprehensive and current
- ✅ process_raster documentation current (includes output_tier)
- ✅ process_raster_collection documentation current
- ✅ Admin endpoints documented with safety warnings
- ✅ Real test results from 21-28 NOV 2025

**Action Items**: None - Comprehensive and current as of 28 NOV 2025.

---

### WIKI_API_DATABASE.md

**Status**: ✅ CURRENT

| Attribute | Value |
|-----------|-------|
| Lines | 442 |
| Last Updated | 24 NOV 2025 |
| Audience | Developers setting up/maintaining database |

**Content Summary**:
- Database architecture (PostgreSQL Flexible Server)
- Schema organization (app, geo, pgstac)
- Setup instructions (Azure CLI commands)
- Schema reference (app.jobs, app.tasks tables)
- Connection configuration
- Maintenance operations
- Troubleshooting guide

**Accuracy Assessment**:
- ✅ Schema structure correct (app, geo, pgstac)
- ✅ Table definitions accurate
- ✅ Connection configuration patterns correct
- ✅ Troubleshooting scenarios valid

**Action Items**: None

---

### WIKI_API_ERRORS.md

**Status**: ✅ CURRENT

| Attribute | Value |
|-----------|-------|
| Lines | 848 |
| Last Updated | 29 NOV 2025 |
| Audience | Developers, operators |

**Content Summary**:
- Error response format
- HTTP status codes
- Pre-flight validation errors
- Parameter validation errors
- Job status errors
- CSV-specific errors
- Database errors
- STAC/Raster errors
- Internal error handling architecture
- Exception hierarchy (ContractViolation vs BusinessLogic)
- Retry telemetry
- Service Bus error categories
- Application Insights dashboard queries

**Accuracy Assessment**:
- ✅ Error handling architecture documented
- ✅ Exception hierarchy correct
- ✅ Retry logic documented with checkpoints
- ✅ Application Insights queries functional
- ✅ Most recent update (29 NOV 2025)

**Action Items**: None - Most recently updated WIKI file.

---

### WIKI_API_GLOSSARY.md

**Status**: ✅ CURRENT

| Attribute | Value |
|-----------|-------|
| Lines | 262 |
| Last Updated | 24 NOV 2025 |
| Audience | All team members, including ESL speakers |

**Content Summary**:
- Acronyms and abbreviations (55 entries)
- Architecture terms (CoreMachine, Platform Layer, Fan-Out/In, etc.)
- Data storage terms (Bronze/Silver/Gold containers)
- Geospatial terms (bbox, COG, CRS, PostGIS, etc.)
- Job processing terms (Job, Stage, Task, Handler, Queue)
- Database terms (Schema, Advisory Lock, JSONB)
- API and protocol terms
- Azure terms
- Standardized pattern names

**Accuracy Assessment**:
- ✅ Terminology definitions accurate
- ✅ Pattern names standardized
- ✅ Good reference for non-geospatial developers

**Action Items**: None

---

### WIKI_API_SERVICE_BUS.md

**Status**: ✅ CURRENT

| Attribute | Value |
|-----------|-------|
| Lines | 1467 |
| Last Updated | 24 NOV 2025 |
| Audience | Developers setting up Service Bus |

**Content Summary**:
- Role in ETL architecture
- Message flow architecture diagram
- Complete setup instructions
- Three-layer configuration architecture
- Critical harmonization rules
- Environment variables reference
- Queue configuration values
- Verification and testing steps
- Troubleshooting (6 common issues)
- Key concepts for new developers

**Accuracy Assessment**:
- ✅ Architecture diagrams accurate
- ✅ Setup instructions complete
- ✅ Configuration values current
- ✅ Troubleshooting scenarios valid
- ✅ Key concepts well-explained

**Action Items**: None

---

### WIKI_API_STORAGE.md

**Status**: ✅ CURRENT

| Attribute | Value |
|-----------|-------|
| Lines | 514 |
| Last Updated | 24 NOV 2025 |
| Audience | Developers setting up storage |

**Content Summary**:
- Storage architecture (Bronze/Silver/Gold pattern)
- Access patterns by container
- Setup instructions
- Container configuration
- Access configuration
- SAS token management
- Troubleshooting guide
- Performance optimization

**Accuracy Assessment**:
- ✅ Medallion architecture correctly explained
- ✅ Container names accurate
- ✅ SAS token patterns current
- ✅ Troubleshooting valid

**Action Items**: None

---

### WIKI_JOB_PROCESS_RASTER_V2.md

**Status**: ✅ CURRENT

| Attribute | Value |
|-----------|-------|
| Lines | 378 |
| Last Updated | 28 NOV 2025 |
| Audience | Developers using raster processing |

**Content Summary**:
- JobBaseMixin implementation overview
- 73% less code than v1 (280 lines vs 743 lines)
- Quick start examples
- Full parameters table
- Platform passthrough parameters (DDH integration)
- Output tiers explanation
- Execution chain diagram
- Architecture: REUSED vs CREATED components
- Config integration
- Key design decisions
- Response examples
- Comparison: process_raster vs process_raster_v2
- Migration guide from v1

**Accuracy Assessment**:
- ✅ This IS the current v2 documentation
- ✅ JobBaseMixin pattern correctly documented
- ✅ Execution chain diagram accurate
- ✅ Parameter tables current
- ✅ Migration guide helpful

**Action Items**: None - This is THE authoritative raster processing doc.

---

### WIKI_SCHEMA_REBUILD_SQL.md

**Status**: ✅ CURRENT

| Attribute | Value |
|-----------|-------|
| Lines | 636 |
| Last Updated | 25 NOV 2025 |
| Audience | Developers, database administrators |

**Content Summary**:
- Schema overview (app, pgstac, geo, h3)
- App schema SQL (jobs, tasks, orchestration_jobs, api_requests)
- PostgreSQL functions (complete_task_and_check_stage, etc.)
- pgSTAC migration (pypgstac commands)
- Full rebuild endpoint
- Schema rebuild order (matters!)
- Troubleshooting

**Accuracy Assessment**:
- ✅ Schema definitions accurate
- ✅ SQL statements valid
- ✅ pypgstac migration documented
- ✅ Rebuild order correct

**Action Items**: None

---

### WIKI_API_PROCESS_RASTER_TRACETHROUGH.md

**Status**: ⚠️ OUTDATED

| Attribute | Value |
|-----------|-------|
| Lines | 1442 |
| Last Updated | 22 NOV 2025 |
| Audience | Developers understanding raster workflow |

**Content Summary**:
- Deep execution trace of `process_raster` job
- Line-by-line code walkthrough
- Stage-by-stage execution flow
- Service handler details

**Accuracy Assessment**:
- ❌ References `jobs/process_raster.py` (OLD v1 implementation)
- ❌ Does NOT use JobBaseMixin pattern
- ❌ References parameters that changed in v2 (compression → output_tier)
- ⚠️ Core concepts (Stage flow) still valid

**Issues**:
1. Line 45-50: References `from jobs.process_raster import ProcessRasterJob`
2. References 743-line implementation (v2 is 280 lines)
3. Parameter handling doesn't show declarative schema pattern
4. Missing pre-flight validation (blob_exists) which v2 has

**Action Items**:
1. **Option A**: Archive to `docs/archive/` - Replace with updated v2 trace
2. **Option B**: Update document to trace v2 implementation
3. **Option C**: Add prominent deprecation notice, link to WIKI_JOB_PROCESS_RASTER_V2.md

**Recommendation**: Option A (archive) - The v2 wiki doc is comprehensive and this level of trace detail may not be needed.

---

### WIKI_API_PROCESS_RASTER_COLLECTION_TRACETHROUGH.md

**Status**: ⚠️ OUTDATED

| Attribute | Value |
|-----------|-------|
| Lines | ~1300 |
| Last Updated | 22 NOV 2025 |
| Audience | Developers understanding collection workflow |

**Content Summary**:
- Deep execution trace of `process_raster_collection` job
- Line-by-line code walkthrough
- Stage-by-stage execution flow
- MosaicJSON creation details
- STAC collection creation

**Accuracy Assessment**:
- ❌ References `jobs/process_raster_collection.py` (OLD implementation)
- ❌ Does NOT use JobBaseMixin pattern
- ⚠️ Core concepts (collection processing flow) still valid
- ⚠️ MosaicJSON and STAC patterns may still be accurate

**Issues**:
1. References old job implementation file
2. Parameter handling doesn't show declarative schema pattern
3. Missing JobBaseMixin benefits documentation

**Action Items**:
1. **Option A**: Archive to `docs/archive/` - Create new v2 collection trace if needed
2. **Option B**: Update document to trace v2 implementation
3. **Option C**: Add prominent deprecation notice

**Recommendation**: Option A (archive) - The collection workflow follows same JobBaseMixin pattern as raster v2.

---

## Recommendations Summary

### Immediate Actions (Pre-ADO Transfer)

1. **WIKI_QUICK_START.md**: Add `process_raster_v2` to Job Types table
2. **WIKI_API_PROCESS_RASTER_TRACETHROUGH.md**: Move to `docs/archive/wiki_outdated/`
3. **WIKI_API_PROCESS_RASTER_COLLECTION_TRACETHROUGH.md**: Move to `docs/archive/wiki_outdated/`

### Files Ready for ADO Wiki (No Changes Needed)

1. WIKI_TECHNICAL_OVERVIEW.md
2. WIKI_API_JOB_SUBMISSION.md
3. WIKI_API_DATABASE.md
4. WIKI_API_ERRORS.md
5. WIKI_API_GLOSSARY.md
6. WIKI_API_SERVICE_BUS.md
7. WIKI_API_STORAGE.md
8. WIKI_JOB_PROCESS_RASTER_V2.md
9. WIKI_SCHEMA_REBUILD_SQL.md

### Post-Archive Considerations

The two archived tracethrough documents provided deep execution traces. Consider whether this level of detail is needed for v2 jobs. The JobBaseMixin pattern significantly simplifies the code, so traces may be shorter and more valuable.

---

## ADO Wiki Structure Proposal

```
Azure DevOps Wiki/
├── Home.md (link from README)
├── Getting Started/
│   └── Quick Start Guide (WIKI_QUICK_START.md)
├── Architecture/
│   ├── Technical Overview (WIKI_TECHNICAL_OVERVIEW.md)
│   └── Glossary (WIKI_API_GLOSSARY.md)
├── API Reference/
│   ├── Job Submission (WIKI_API_JOB_SUBMISSION.md)
│   ├── Error Handling (WIKI_API_ERRORS.md)
│   └── Raster Processing V2 (WIKI_JOB_PROCESS_RASTER_V2.md)
├── Infrastructure/
│   ├── Database Setup (WIKI_API_DATABASE.md)
│   ├── Service Bus (WIKI_API_SERVICE_BUS.md)
│   ├── Storage (WIKI_API_STORAGE.md)
│   └── Schema Rebuild (WIKI_SCHEMA_REBUILD_SQL.md)
```

---

## Other Root Markdown Files

These files are not WIKI_ prefixed but exist in the root directory. Assessment for cleanup:

### Files to Keep in Root

| File | Lines | Last Updated | Reason |
|------|-------|--------------|--------|
| README.md | 700+ | - | Standard project readme |
| CLAUDE.md | - | - | Claude entry point - stays private |
| JOB_CREATION_QUICKSTART.md | 359 | 14 NOV 2025 | Referenced in CLAUDE.md, critical for new jobs |

### Files to Consolidate into Wiki

| File | Lines | Last Updated | Target | Notes |
|------|-------|--------------|--------|-------|
| DATABASE_SETUP_GUIDE.md | ~450 | 30 NOV 2025 | WIKI_API_DATABASE.md | Dual DB architecture, managed identity |
| DB_ADMIN_SQL.md | ~350 | Production | WIKI_API_DATABASE.md | Admin identity (rmhpgflexadmin) setup |
| DB_READER_SQL.md | ~300 | Production | WIKI_API_DATABASE.md | Reader identity (rmhpgflexreader) setup |
| COREMACHINE_API_GUIDE.md | ~500 | 20 NOV 2025 | Review | May overlap with WIKI_API_JOB_SUBMISSION.md |
| onboarding.md | 1400+ | 18 NOV 2025 | New wiki page | Excellent comprehensive onboarding |

### Files to Archive

| File | Lines | Issue | Reason |
|------|-------|-------|--------|
| PROCESS_RASTER_TRACE.md | ~800 | 24 NOV 2025 | Same content as archived WIKI version - old v1 trace |
| APP_REFACTOR.md | ~450 | 22 NOV 2025 | IN PROGRESS plan for function_app.py (separate effort) |
| QA_DATABASE_SETUP.md | ~150 | 30 NOV 2025 | Subset of DATABASE_SETUP_GUIDE.md content |

### Files - Active Development (Keep in Root)

| File | Lines | Last Updated | Notes |
|------|-------|--------------|-------|
| SCALE_OUT.md | ~200 | 24 NOV 2025 | Active development - KEEP |
| UI_INTERFACE.md | ~300 | 21 NOV 2025 | Active development - KEEP |

---

## Detailed Redundancy Analysis

### DATABASE_SETUP_GUIDE.md (635 lines) - 30 NOV 2025
**Content**: Dual database architecture (App DB + Business DB), managed identity setup

**Unique Content NOT in WIKI_API_DATABASE.md**:
- Dual database architecture diagram (geopgflex vs ddhgeodb)
- Full DDL vs CRUD-only permission model
- Business database setup with PostGIS
- Restricted CRUD access SQL for business data protection

**Overlap**: Schema organization, basic setup, extension installation

**Recommendation**: Keep as operational reference (contains specific architecture decisions)

---

### DB_ADMIN_SQL.md (429 lines) - Production
**Content**: rmhpgflexadmin managed identity setup (ADMIN access)

**Unique Content**:
- Admin identity Client ID: `a533cb80-a590-4fad-8e52-1eb1f72659d7`
- Principal ID: `ab45e154-ae11-4e99-9e96-76da5fe51656`
- ALL PRIVILEGES grants for all schemas
- Admin vs Reader comparison table
- Python code example for token acquisition

**Recommendation**: Keep as operational reference (contains actual Client IDs needed for ops)

---

### DB_READER_SQL.md (482 lines) - Production
**Content**: rmhpgflexreader managed identity setup (READ-ONLY access)

**Unique Content**:
- Read-only identity Client ID: `1c79a2fe-42cb-4f30-8fe9-c1dfc04f142f`
- SELECT-only grants (no INSERT/UPDATE/DELETE)
- Used by: rmhogcapi, TiTiler

**Recommendation**: Keep as operational reference (contains actual Client IDs)

---

### COREMACHINE_API_GUIDE.md (670 lines) - 20 NOV 2025
**Content**: API reference for job submission

**Overlap with WIKI_API_JOB_SUBMISSION.md**:
- Same job types documented
- Same endpoint patterns
- WIKI version is MORE comprehensive (1611 lines vs 670)
- WIKI includes Platform layer, real test results

**CRITICAL ISSUE**: Uses `ingest_vector` but current code uses `process_vector`

**Recommendation**: **ARCHIVE** - WIKI_API_JOB_SUBMISSION.md is more comprehensive and current

---

### onboarding.md (1917 lines) - 18 NOV 2025
**Content**: Comprehensive developer onboarding guide

**Unique Content (NOT in any WIKI file)**:
- "What This System Does" high-level overview
- Core Design Principles (5 principles)
- Detailed orchestration flow diagrams with SQL
- "Last One Turns Off the Lights" pattern explanation
- Vector Processing Workflow code examples (Stage 1-4)
- Raster Processing Workflows code examples
- Standards-Based API Outputs section
- JobBaseMixin tutorial with full code
- Development Environment Setup
- Python Environment setup with dependencies
- Local Configuration (local.settings.json template)
- Debugging with Application Insights
- Git Workflow (Dev Branch Strategy)
- Performance Considerations (chunking, indexing, COG)
- Security & Access Patterns (RBAC vs POSIX)

**Assessment**: EXCELLENT comprehensive guide - most content unique and valuable

**Recommendation**: Rename to **WIKI_ONBOARDING.md** - should be primary onboarding doc in ADO Wiki

---

## Consolidation Decision - COMPLETED

### Files Archived
| File | Reason |
|------|--------|
| COREMACHINE_API_GUIDE.md | Redundant - WIKI_API_JOB_SUBMISSION.md is more comprehensive |
| DATABASE_SETUP_GUIDE.md | Consolidated into DATABASE_IDENTITY_RUNBOOK.md |
| DB_ADMIN_SQL.md | Consolidated into DATABASE_IDENTITY_RUNBOOK.md |
| DB_READER_SQL.md | Consolidated into DATABASE_IDENTITY_RUNBOOK.md |

### Files Renamed
| Original | New | Status |
|----------|-----|--------|
| onboarding.md | WIKI_ONBOARDING.md | ✅ DONE |

### New Files Created
| File | Purpose |
|------|---------|
| DATABASE_IDENTITY_RUNBOOK.md | Operational runbook with actual Client IDs, consolidates 3 DB files |

---

## Cleanup Status - COMPLETED

### Phase 1: Archive Outdated Files ✅ DONE
```
docs/archive/wiki_outdated_dec2025/
├── WIKI_API_PROCESS_RASTER_TRACETHROUGH.md
├── WIKI_API_PROCESS_RASTER_COLLECTION_TRACETHROUGH.md
└── ARCHIVE_README.md

docs/archive/root_cleanup_dec2025/
├── PROCESS_RASTER_TRACE.md
├── APP_REFACTOR.md
├── QA_DATABASE_SETUP.md
├── COREMACHINE_API_GUIDE.md
├── DATABASE_SETUP_GUIDE.md
├── DB_ADMIN_SQL.md
├── DB_READER_SQL.md
└── ARCHIVE_README.md
```

### Phase 2: Consolidate Database Docs ✅ DONE
- Created `DATABASE_IDENTITY_RUNBOOK.md` with all operational values
- Updated `WIKI_API_DATABASE.md` with generic managed identity section

### Phase 3: Rename for Wiki ✅ DONE
- `onboarding.md` → `WIKI_ONBOARDING.md`

### Files Kept As-Is
- SCALE_OUT.md - Active development
- UI_INTERFACE.md - Active development

### Phase 4: Job Creation Documentation ✅ DONE (05 DEC 2025)

**JOB_CREATION_QUICKSTART.md** - Reviewed and fixed:
- Fixed broken file references:
  - `jobs/hello_world_mixin.py` → `jobs/hello_world.py`
  - `jobs/process_large_raster.py` → `jobs/process_large_raster_v2.py`
- Updated date to 05 DEC 2025

**Action Taken**: Moved to `docs_claude/JOB_CREATION_QUICKSTART.md`
- Has CLAUDE CONTEXT header - Claude reference doc
- Updated CLAUDE.md references to new location
- WIKI_ONBOARDING.md Section 5.2 covers JobBaseMixin for human readers

### Phase 5: docs_claude/ Cleanup ✅ DONE (05 DEC 2025)

**CLAUDE_CONTEXT.md** - Complete rewrite:
- OLD: 419 lines, outdated (referenced rmhgeoapibeta, legacy architecture split)
- NEW: 264 lines, current (correct Function App, unified architecture)
- Removed obsolete "Two Parallel Implementations" section
- Updated all URLs and commands

**TODO.md** - Massive cleanup:
- OLD: 4,228 lines (11 completed sections mixed with active tasks)
- NEW: 199 lines (only active tasks)
- **95% reduction** in file size

**HISTORY2.md** - Created:
- New file for completed work moved from TODO.md
- Contains 12 completed sections with full details
- 321 lines of archived completed work

### Phase 6: docs_claude/ Consolidation ✅ DONE (05 DEC 2025)

**DEPLOYMENT_GUIDE.md** - Consolidated from 4 files:
- OLD: 327 lines (deployment only)
- NEW: 403 lines (deployment + logging + identity + troubleshooting)
- Merged in: APPLICATION_INSIGHTS_QUERY_PATTERNS.md, claude_log_access.md, MANAGED_IDENTITY_QUICKSTART.md

**Files Archived** (moved to docs/archive/docs_claude_dec2025/):
- APPLICATION_INSIGHTS_QUERY_PATTERNS.md (496 lines) - Merged into DEPLOYMENT_GUIDE.md
- claude_log_access.md (248 lines) - Merged into DEPLOYMENT_GUIDE.md
- MANAGED_IDENTITY_QUICKSTART.md (103 lines) - Merged into DEPLOYMENT_GUIDE.md
- FILE_CATALOG.md (541 lines) - Outdated (29 OCT 2025), CLAUDE_CONTEXT.md has structure

### Final docs_claude/ Structure

```
docs_claude/ (10 files - down from 14)
├── CLAUDE_CONTEXT.md          # 264 lines - START HERE
├── TODO.md                    # 199 lines - Active tasks only
├── HISTORY.md                 # ~172K - Completed work (pre-DEC 2025)
├── HISTORY2.md                # 321 lines - Completed work (DEC 2025)
├── JOB_CREATION_QUICKSTART.md # 526 lines - Job creation guide
├── DEPLOYMENT_GUIDE.md        # 403 lines - Ops, logging, identity, troubleshooting
├── ARCHITECTURE_REFERENCE.md  # ~45K - Deep technical specs
├── SCHEMA_ARCHITECTURE.md     # ~21K - PostgreSQL design
├── SERVICE_BUS_HARMONIZATION.md # ~16K - Queue config
└── COREMACHINE_PLATFORM_ARCHITECTURE.md # ~17K - Two-layer design
```

**Summary**: 14 files → 10 files (29% reduction in file count)

---

**Last Updated**: 05 DEC 2025
