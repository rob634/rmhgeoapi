# GitHub Project SAFe Setup - Remaining Tasks

**Created**: 29 DEC 2025
**Purpose**: Hand-off document for completing GitHub Project SAFe structure
**Project URL**: https://github.com/users/rob634/projects/1

---

## Completed Work

### 1. GitHub Project Created
- Project: `rmhgeoapi` (Project #1)
- Owner: `rob634`
- Status: Open, 0 items currently

### 2. Custom Fields Added
| Field | Type | Options |
|-------|------|---------|
| Type | Single Select | Epic, Feature, Story, Enabler, Spike |
| Epic | Text | For linking features/stories to parent epic |
| Priority | Number | WSJF-based priority ranking |
| Status | Single Select | Todo, In Progress, Done (default) |

### 3. Labels Created
| Label | Color | Description |
|-------|-------|-------------|
| `epic` | #8B0000 (dark red) | SAFe Epic - Strategic initiative |
| `feature` | #0052CC (blue) | SAFe Feature - Deliverable capability |
| `story` | #2E7D32 (green) | SAFe Story - Smallest work unit |
| `enabler` | #6A1B9A (purple) | SAFe Enabler - Technical foundation |

### 4. Epic Issues Created (4 of 9)
| Issue # | Epic | Title | Status |
|---------|------|-------|--------|
| #1 | E1 | Vector Data as API | Created |
| #2 | E2 | Raster Data as API | Created |
| #3 | E3 | DDH Platform Integration | Created |
| #4 | E4 | Data Externalization | Created |

---

## Remaining Tasks

### Task 1: Create Remaining Epic Issues

Create issues for E5, E7, E8, E9, E12 using this pattern:

```bash
gh issue create --repo rob634/rmhgeoapi \
  --title "E5: OGC Styles" \
  --body "$(cat <<'EOF'
## Epic: OGC Styles

**Status**: 🚧 Partial
**Priority**: 6
**WSJF**: 3.7

### Description
Implement OGC API Styles for consistent data visualization.

### Features
- F5.1: Style Registry ✅
- F5.2: ETL Integration 📋

### WSJF Rationale
- Business Value: 5 (styling metadata)
- Time Criticality: 3
- Risk Reduction: 3
EOF
)" \
  --label "epic"
```

**Epics to create:**

| Epic | Title | Priority | WSJF | Key Features |
|------|-------|----------|------|--------------|
| E5 | OGC Styles | 6 | 3.7 | F5.1 Style Registry ✅, F5.2 ETL Integration |
| E7 | Pipeline Extensibility | 5 | 2.6 | F7.1-F7.7 (consolidated from E10, E11, E13, E15) |
| E8 | H3 Analytics Pipeline | 7 | 1.2 | F8.1-F8.12 (consolidated from E14) |
| E9 | Zarr/Climate Data as API | 4 | 2.0 | F9.1-F9.3 |
| E12 | Interface Modernization | — | — | F12.1-F12.4, Phase 1 Complete |

### Task 2: Add Issues to Project

After creating issues, add them to the project:

```bash
# Add issue to project (repeat for each issue)
gh project item-add 1 --owner rob634 --url https://github.com/rob634/rmhgeoapi/issues/1
gh project item-add 1 --owner rob634 --url https://github.com/rob634/rmhgeoapi/issues/2
# ... etc for all issues
```

### Task 3: Set Custom Field Values

After adding to project, set the Type and Priority fields:

```bash
# Get item IDs first
gh project item-list 1 --owner rob634 --format json

# Then update fields (need item ID from above)
gh project item-edit --project-id PVT_kwHOAK7mpM4BLi8z --id <ITEM_ID> \
  --field-id PVTSSF_lAHOAK7mpM4BLi8zzg7Fm_Y --single-select-option-id 1a12aab1

# Field IDs (from field-list):
# Type field: PVTSSF_lAHOAK7mpM4BLi8zzg7Fm_Y
#   Epic option: 1a12aab1
#   Feature option: ae512a81
#   Story option: 9a6c5393
# Priority field: PVTF_lAHOAK7mpM4BLi8zzg7FnAU
# Epic (text) field: PVTF_lAHOAK7mpM4BLi8zzg7Fm_g
```

### Task 4: Create Feature Issues (Optional - Phase 2)

For active features, create child issues with `feature` label:

```bash
gh issue create --repo rob634/rmhgeoapi \
  --title "F7.4: FATHOM ETL Operations" \
  --body "$(cat <<'EOF'
## Feature: FATHOM ETL Operations

**Parent Epic**: E7 - Pipeline Extensibility
**Status**: 🚧 46/47 tasks complete

### Description
Band stacking and spatial merge for FATHOM flood data.

### Stories
- S7.4.1: Phase 1 - CI processing ✅
- S7.4.2: Phase 2 - Global processing 🚧

### Current Issue
Task `n10-n15_w005-w010` failed. Need retry with `force_reprocess=true`.
EOF
)" \
  --label "feature"
```

---

## Reference: Epic Details from EPICS.md

### E7: Pipeline Extensibility (Consolidated)
Absorbed: E10, E11, E13, E15

| Feature | Description | Status |
|---------|-------------|--------|
| F7.1 | External Data Ingestion | 📋 |
| F7.2 | ADF Pipeline Integration | 📋 |
| F7.3 | Data Gateway | 📋 |
| F7.4 | FATHOM ETL Operations (~~E10~~) | 🚧 |
| F7.5 | Collection Ingestion (~~E15~~) | ✅ |
| F7.6 | Pipeline Observability (~~E13~~) | ✅ |
| F7.7 | Pipeline Builder UI (~~E11~~) | 📋 |

### E8: H3 Analytics Pipeline (Consolidated)
Absorbed: E14

| Feature | Description | Status |
|---------|-------------|--------|
| F8.1-F8.3 | Grid infrastructure, bootstrap, raster aggregation | ✅ |
| F8.4 | Vector→H3 Aggregation | ⬜ Ready |
| F8.5 | GeoParquet Export | 📋 |
| F8.6 | Analytics API | 📋 |
| F8.7 | Building Exposure | 📋 |
| F8.8 | Source Catalog | ✅ |
| F8.9-F8.11 | Pipeline Framework, Multi-Step, Rwanda Demo | 📋 |
| F8.12 | H3 Export Pipeline (~~E14~~) | ✅ |

### E9: Zarr/Climate Data as API

| Feature | Description | Status |
|---------|-------------|--------|
| F9.1 | Zarr TiTiler Integration | 📋 |
| F9.2 | Virtual Zarr Pipeline | 📋 |
| F9.3 | Reader Migration | ⬜ Ready |

### E12: Interface Modernization

| Feature | Description | Status |
|---------|-------------|--------|
| F12.1 | Cleanup (CSS, JS, Python) | ✅ |
| F12.2 | HTMX Integration | ✅ |
| F12.3 | Interface Migration | ✅ |
| F12.4 | NiceGUI Evaluation | 📋 Future |

---

## Quick Commands Reference

```bash
# Check auth
gh auth status

# List projects
gh project list --owner rob634

# View project
gh project view 1 --owner rob634

# List fields
gh project field-list 1 --owner rob634 --format json

# List items in project
gh project item-list 1 --owner rob634 --format json

# List issues in repo
gh issue list --repo rob634/rmhgeoapi --label epic

# Create issue
gh issue create --repo rob634/rmhgeoapi --title "Title" --body "Body" --label "epic"

# Add issue to project
gh project item-add 1 --owner rob634 --url <issue-url>
```

---

## Notes

- Project ID: `PVT_kwHOAK7mpM4BLi8z`
- All gh commands require authentication with `project` scope (already configured)
- EPICS.md is the source of truth for epic/feature definitions
- TODO.md tracks sprint-level work items
