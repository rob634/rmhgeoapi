# GitHub Project SAFe Setup - COMPLETE

**Created**: 29 DEC 2025
**Completed**: 29 DEC 2025
**Purpose**: Reference document for GitHub Project SAFe structure
**Project URL**: https://github.com/users/rob634/projects/1

---

## Setup Complete ✅

### 1. GitHub Project Created ✅
- Project: `rmhgeoapi` (Project #1)
- Owner: `rob634`
- Status: **30+ items tracked**

### 2. Custom Fields Added ✅
| Field | Type | Options |
|-------|------|---------|
| Type | Single Select | Epic, Feature, Story, Enabler, Spike |
| Epic | Text | For linking features/stories to parent epic |
| Priority | Number | WSJF-based priority ranking |
| Status | Single Select | Todo, In Progress, Done (default) |

### 3. Labels Created ✅
| Label | Color | Description |
|-------|-------|-------------|
| `epic` | #8B0000 (dark red) | SAFe Epic - Strategic initiative |
| `feature` | #0052CC (blue) | SAFe Feature - Deliverable capability |
| `story` | #2E7D32 (green) | SAFe Story - Smallest work unit |
| `enabler` | #6A1B9A (purple) | SAFe Enabler - Technical foundation |

### 4. All Epic Issues Created ✅ (9 of 9)
| Issue # | Epic | Title | Status |
|---------|------|-------|--------|
| #1 | E1 | Vector Data as API | CLOSED |
| #2 | E2 | Raster Data as API | OPEN |
| #3 | E3 | DDH Platform Integration | OPEN |
| #4 | E4 | Data Externalization | OPEN |
| #5 | E5 | OGC Styles | OPEN |
| #6 | E7 | Pipeline Extensibility | OPEN |
| #7 | E8 | H3 Analytics Pipeline | OPEN |
| #8 | E9 | Zarr/Climate Data as API | OPEN |
| #9 | E12 | Interface Modernization | CLOSED |

### 5. Feature Issues Created ✅ (45+ features)
All features from EPICS.md imported with proper labels and parent epic references.

---

## Reference: gh CLI Commands

### Create New Epic Issue

```bash
gh issue create --repo rob634/rmhgeoapi \
  --title "E##: Epic Title" \
  --body "$(cat <<'EOF'
## Epic: Title

**Status**: 📋 Planned
**Priority**: #
**WSJF**: #.#

### Description
Brief description of the epic.

### Features
- F#.1: Feature name 📋
- F#.2: Feature name 📋
EOF
)" \
  --label "epic"
```

### Create New Feature Issue

```bash
gh issue create --repo rob634/rmhgeoapi \
  --title "F#.#: Feature Title" \
  --body "$(cat <<'EOF'
## Feature: Title

**Parent Epic**: E# - Epic Name
**Status**: 📋 Planned

### Description
Brief description.

### Stories
- S#.#.1: Story description 📋
EOF
)" \
  --label "feature"
```

### Add Issue to Project

```bash
gh project item-add 1 --owner rob634 --url https://github.com/rob634/rmhgeoapi/issues/##
```

### Set Custom Field Values

```bash
# Get item IDs
gh project item-list 1 --owner rob634 --format json

# Field IDs:
# Type field: PVTSSF_lAHOAK7mpM4BLi8zzg7Fm_Y
#   Epic option: 1a12aab1
#   Feature option: ae512a81
#   Story option: 9a6c5393
# Priority field: PVTF_lAHOAK7mpM4BLi8zzg7FnAU
# Epic (text) field: PVTF_lAHOAK7mpM4BLi8zzg7Fm_g

gh project item-edit --project-id PVT_kwHOAK7mpM4BLi8z --id <ITEM_ID> \
  --field-id PVTSSF_lAHOAK7mpM4BLi8zzg7Fm_Y --single-select-option-id <OPTION_ID>
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
| F12.5 | Promote Vector Interface | ✅ |

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
