# Epoch 3 Schemas Archive

**Archived**: 30 SEP 2025
**Reason**: Replaced by organized core/models/ and core/schema/ structure

---

## Schemas That Will Be Archived Here

Once Epoch 4 is validated, these files will be moved here:

### Already Replaced (30 SEP 2025 Schema Migration):
- `schema_base.py` → Replaced by `core/models/` (enums.py, job.py, task.py, results.py)
- `schema_workflow.py` → Replaced by `core/schema/workflow.py`
- `schema_orchestration.py` → Replaced by `core/schema/orchestration.py`
- `schema_queue.py` → Replaced by `core/schema/queue.py`
- `schema_updates.py` → Replaced by `core/schema/updates.py`

### Still In Use (Keep):
- `schema_file_item.py` - File processing schemas
- `schema_geospatial.py` - Geospatial data models
- `schema_postgis.py` - PostGIS schemas
- `schema_stac.py` - STAC metadata

---

## Why These Were Replaced

**Problem**: Root-level schema files scattered across workspace with no clear organization.

**Solution**:
- Data models → `core/models/`
- Workflow definitions → `core/schema/`
- Clear imports: `from core.models import JobRecord`

---

Files will be moved here during Phase 6 of EPOCH4_IMPLEMENTATION.md
