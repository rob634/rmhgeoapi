# Handler Naming Convention Migration Plan

**Created**: 29 DEC 2025
**Purpose**: Standardize handler names to `{domain}_{action}` convention
**Risk Level**: HIGH - Breaking change affecting job definitions
**Estimated Scope**: ~25 handlers to rename across 4 domains

---

## Executive Summary

Handler names are inconsistent. Some use `{action}_{object}` (e.g., `validate_raster`), others use `{domain}_{action}` (e.g., `fathom_band_stack`). This causes:
- Confusion when adding new handlers
- Difficulty identifying which job a handler belongs to
- Past bugs from naming mismatches between registries

**Target Convention**: `{domain}_{action}` or `{domain}_{stage}_{action}`

**Examples**:
- `validate_raster` → `raster_validate`
- `create_cog` → `raster_create_cog`
- `delete_blob` → `unpublish_delete_blob`

---

## Pre-Migration Checklist

- [ ] **BACKUP**: Create git branch `handler-naming-migration` from current state
- [ ] **VERIFY**: Run `func start` locally to confirm current state works
- [ ] **VERIFY**: Run all tests pass before starting migration
- [ ] **DOCUMENT**: Note current handler count in ALL_HANDLERS: `len(ALL_HANDLERS)` = ___

---

## Phase 1: Raster Handlers (8 handlers) ✅ COMPLETE (29 DEC 2025)

**Domain**: `raster`
**Risk**: MEDIUM - These are core ETL handlers used frequently

### Handlers to Rename

| Step | Current Name | New Name | Status |
|------|--------------|----------|--------|
| 1.1 | `validate_raster` | `raster_validate` | [x] |
| 1.2 | `create_cog` | `raster_create_cog` | [x] |
| 1.3 | `extract_stac_metadata` | `raster_extract_stac_metadata` | [x] |
| 1.4 | `list_raster_files` | `raster_list_files` | [x] |
| 1.5 | `generate_tiling_scheme` | `raster_generate_tiling_scheme` | [x] |
| 1.6 | `extract_tiles` | `raster_extract_tiles` | [x] |
| 1.7 | `create_mosaicjson` | `raster_create_mosaicjson` | [x] |
| 1.8 | `create_stac_collection` | `raster_create_stac_collection` | [x] |

### Files to Update for Each Handler

For each handler rename, update these files in order:

1. **Handler function file** (e.g., `services/raster_validation.py`)
   - [ ] Rename the function itself (if function name matches handler name)
   - [ ] Update any internal logging that references the handler name

2. **Handler registry** (`services/__init__.py`)
   - [ ] Update the key in `ALL_HANDLERS` dict
   - [ ] Update the import if function was renamed

3. **Task routing** (`config/defaults.py`)
   - [ ] Update entry in `RASTER_TASKS` list

4. **Job definitions** (search with `grep -r "old_handler_name" jobs/`)
   - [ ] Update `task_type` in stage definitions
   - [ ] Common files: `jobs/process_raster_v2.py`, `jobs/process_large_raster_v2.py`, `jobs/process_raster_collection_v2.py`

### Phase 1 Verification

- [ ] `python -c "from services import ALL_HANDLERS; print(len(ALL_HANDLERS))"` - Count unchanged
- [ ] `python -c "from config.defaults import TaskRoutingDefaults; print('OK')"` - No import errors
- [ ] `func start` - App starts without errors
- [ ] Submit test job: `process_raster_v2` with a small test file
- [ ] Verify job completes successfully

### Phase 1 Rollback

If issues occur:
```bash
git checkout services/__init__.py config/defaults.py jobs/process_raster*.py
```

---

## Phase 2: Vector Handlers (2 handlers) ✅ COMPLETE (29 DEC 2025)

**Domain**: `vector`
**Risk**: LOW - Only 2 handlers, clear scope

### Handlers to Rename

| Step | Current Name | New Name | Status |
|------|--------------|----------|--------|
| 2.1 | `create_vector_stac` | `vector_create_stac` | [x] |
| 2.2 | `extract_vector_stac_metadata` | `vector_extract_stac_metadata` | [x] |

### Files to Update

1. **Handler function file**: `services/vector/stac_handlers.py` or similar
2. **Handler registry**: `services/__init__.py`
3. **Task routing**: `config/defaults.py` → `VECTOR_TASKS`
4. **Job definitions**: `jobs/process_vector.py`

### Phase 2 Verification

- [ ] Handler count unchanged
- [ ] `func start` works
- [ ] Submit test job: `process_vector` with small shapefile
- [ ] Verify job completes successfully

---

## Phase 3: H3 Handlers (5 handlers) ✅ COMPLETE (29 DEC 2025)

**Domain**: `h3`
**Risk**: MEDIUM - H3 is complex with multiple job types

### Handlers to Rename

| Step | Current Name | New Name | Status |
|------|--------------|----------|--------|
| 3.1 | `insert_h3_to_postgis` | `h3_insert_to_postgis` | [x] |
| 3.2 | `create_h3_stac` | `h3_create_stac` | [x] |
| 3.3 | `generate_h3_grid` | `h3_generate_grid` | [x] |
| 3.4 | `cascade_h3_descendants` | `h3_cascade_descendants` | [x] |
| 3.5 | `finalize_h3_pyramid` | `h3_finalize_pyramid` | [x] |

### Files Updated

1. **Handler registry**: `services/__init__.py`
2. **Task routing**: `config/defaults.py` → `VECTOR_TASKS`
3. **Job definitions**: `jobs/bootstrap_h3_land_grid_pyramid.py`, `jobs/generate_h3_level4.py`, `jobs/create_h3_base.py`

### Phase 3 Verification

- [x] Handler count unchanged (59 handlers)
- [x] Task routing validation passes

---

## Phase 4: Inventory Handlers (6 handlers) ✅ COMPLETE (29 DEC 2025)

**Domain**: `inventory`
**Risk**: LOW - Container inventory is auxiliary functionality

### Handlers to Rename

| Step | Current Name | New Name | Status |
|------|--------------|----------|--------|
| 4.1 | `container_summary_task` | `inventory_container_summary` | [x] |
| 4.2 | `list_blobs_with_metadata` | `inventory_list_blobs` | [x] |
| 4.3 | `analyze_blob_basic` | `inventory_analyze_blob` | [x] |
| 4.4 | `aggregate_blob_analysis` | `inventory_aggregate_analysis` | [x] |
| 4.5 | `classify_geospatial_file` | `inventory_classify_geospatial` | [x] |
| 4.6 | `aggregate_geospatial_inventory` | `inventory_aggregate_geospatial` | [x] |

### Files Updated

1. **Handler registry**: `services/__init__.py`
2. **Task routing**: `config/defaults.py` → `VECTOR_TASKS`
3. **Job definitions**: `jobs/inventory_container_contents.py`, `jobs/container_summary.py`

### Phase 4 Verification

- [x] Handler count unchanged (59 handlers)
- [x] Task routing validation passes

---

## Phase 5: Unpublish Handlers (5 handlers) ✅ COMPLETE (29 DEC 2025)

**Domain**: `unpublish`
**Risk**: LOW - Unpublish is infrequently used

### Handlers to Rename

| Step | Current Name | New Name | Status |
|------|--------------|----------|--------|
| 5.1 | `inventory_raster_item` | `unpublish_inventory_raster` | [x] |
| 5.2 | `inventory_vector_item` | `unpublish_inventory_vector` | [x] |
| 5.3 | `delete_blob` | `unpublish_delete_blob` | [x] |
| 5.4 | `drop_postgis_table` | `unpublish_drop_table` | [x] |
| 5.5 | `delete_stac_and_audit` | `unpublish_delete_stac` | [x] |

### Files Updated

1. **Handler registry**: `services/__init__.py`
2. **Task routing**: `config/defaults.py` → `VECTOR_TASKS`
3. **Job definitions**: `jobs/unpublish_raster.py`, `jobs/unpublish_vector.py`

### Phase 5 Verification

- [x] Handler count unchanged (59 handlers)
- [x] Task routing validation passes

---

## Post-Migration Tasks

### Validation

- [ ] **Total handler count**: Confirm `len(ALL_HANDLERS)` is unchanged from pre-migration
- [ ] **Startup validation passes**: `python -c "from services import validate_handler_registry; validate_handler_registry()"`
- [ ] **Task routing validation passes**: `python -c "from services import validate_task_routing_coverage; validate_task_routing_coverage()"`
- [ ] **Full test suite**: Run all integration tests

### Documentation Updates

- [ ] Update `docs_claude/JOB_CREATION_QUICKSTART.md` with naming convention
- [ ] Update `docs_claude/ARCHITECTURE_REFERENCE.md` if handler naming is documented
- [ ] Add naming convention to `services/__init__.py` header comment

### Enforcement

- [ ] Add naming validation to `validate_handler_registry()`:
```python
def validate_handler_naming_convention():
    """Validate all handlers follow {domain}_{action} naming convention."""
    VALID_PREFIXES = [
        'raster_', 'vector_', 'h3_', 'fathom_', 'inventory_',
        'unpublish_', 'curated_', 'stac_', 'ingest_', 'hello_'
    ]
    for handler_name in ALL_HANDLERS.keys():
        if not any(handler_name.startswith(prefix) for prefix in VALID_PREFIXES):
            raise ValueError(
                f"Handler '{handler_name}' does not follow naming convention. "
                f"Must start with one of: {VALID_PREFIXES}"
            )
```

### Cleanup

- [ ] Delete this migration plan file or move to `docs/archive/`
- [ ] Create git tag: `handler-naming-migration-complete`

---

## Risk Mitigation

### Risk 1: In-Flight Jobs During Migration

**Risk**: Jobs queued before migration may reference old handler names.

**Mitigation**:
1. Check for pending/processing jobs before starting: `GET /api/dbadmin/jobs?status=processing`
2. Wait for all jobs to complete before migration
3. If urgent, can add temporary aliases in ALL_HANDLERS (NOT recommended, violates no-fallback policy)

### Risk 2: Cached Handler References

**Risk**: CoreMachine or other components may cache handler lookups.

**Mitigation**:
1. CoreMachine looks up handlers fresh each time from ALL_HANDLERS dict
2. Restart app after migration to clear any Python module caches
3. Verify with `func start` before deploying

### Risk 3: Task Routing Mismatch

**Risk**: Handler renamed in ALL_HANDLERS but not in TaskRoutingDefaults.

**Mitigation**:
1. `validate_task_routing_coverage()` runs at startup and will fail if mismatch
2. Always update both files in same commit
3. Test locally before deploying

### Risk 4: Partial Migration Deployed

**Risk**: Migration partially complete, some handlers renamed, others not.

**Mitigation**:
1. Complete one phase fully before moving to next
2. Each phase is independently deployable
3. Git commit after each phase verification passes

### Risk 5: Job Definition References Old Name

**Risk**: Forgot to update a job file that references old handler name.

**Mitigation**:
1. Use grep to find all references before renaming:
   ```bash
   grep -r "old_handler_name" jobs/ services/ config/
   ```
2. Startup validation will fail if handler name not found in ALL_HANDLERS
3. Job submission will fail fast if task_type not in registry

---

## Grep Commands for Finding References

Before renaming each handler, run these commands to find all references:

```bash
# Find all references to a handler name
grep -rn "validate_raster" jobs/ services/ config/ --include="*.py"

# Find all handler name strings (quoted)
grep -rn '"validate_raster"' jobs/ services/ config/ --include="*.py"

# Find function definitions
grep -rn "def validate_raster" services/ --include="*.py"
```

---

## Implementation Notes for Claude

1. **One handler at a time**: Complete all 4 file updates for one handler before moving to the next
2. **Test after each phase**: Don't batch multiple phases without testing
3. **Preserve comments**: When updating registry entries, preserve the inline comments
4. **No function renames required**: The Python function names don't need to change, only the string keys in the registries
5. **Check imports**: If the handler function name changes, update the import statement in `services/__init__.py`

---

## Summary

| Phase | Domain | Handler Count | Risk | Status |
|-------|--------|---------------|------|--------|
| 1 | raster | 8 | MEDIUM | ✅ COMPLETE |
| 2 | vector | 2 | LOW | ✅ COMPLETE |
| 3 | h3 | 5 | MEDIUM | ✅ COMPLETE |
| 4 | inventory | 6 | LOW | ✅ COMPLETE |
| 5 | unpublish | 5 | LOW | ✅ COMPLETE |
| **Total** | | **26** | | **26/26 done** |

**Completed 29 DEC 2025**: All phases complete (raster, vector, h3, inventory, unpublish)
