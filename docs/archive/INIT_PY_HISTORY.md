# __init__.py Historical Comments Archive

**Archived**: 14 JAN 2026
**Reason**: Cleanup of dated inline comments from package __init__.py files

This document preserves historical context that was removed during the 14 JAN 2026 cleanup of __init__.py files. The cleanup removed inline dates and verbose comments to improve readability while preserving this history for reference.

---

## services/__init__.py

### Historical Context

The explicit handler registration pattern was adopted after experiencing silent registration failures with decorator-based registration on 10 SEP 2025. Decorators only execute when modules are imported, and if a module is never imported, its decorators never run.

### Archived Handler Comments

```
# Old container_list handlers - ARCHIVED (07 DEC 2025)
# list_container_blobs: replaced by list_blobs_with_metadata
# analyze_single_blob: replaced by analyze_blob_basic
# aggregate_blob_analysis: replaced by container_inventory.aggregate_blob_analysis

# test_minimal removed (30 NOV 2025) - file doesn't exist

# Old ingest_vector handlers REMOVED (27 NOV 2025) - process_vector uses new idempotent handlers
# from .vector.tasks import prepare_vector_chunks, upload_pickled_chunk

# Fathom ETL handlers - Two-Phase Architecture (03 DEC 2025)
# Phase 1: Band stacking (~500MB/task, 16+ concurrent)
# Phase 2: Spatial merge (~2-3GB/task, 4-5 concurrent)

# Legacy handlers ARCHIVED (05 DEC 2025) -> docs/archive/jobs/fathom_legacy_dec2025/
```

### Feature Addition Timeline

| Date | Feature |
|------|---------|
| 09 NOV 2025 | H3 PostGIS + STAC handlers (Phase 2) |
| 09 NOV 2025 | H3 Native Streaming Handler (Phase 3) |
| 14-15 NOV 2025 | H3 Universal Handlers (DRY Architecture) |
| 20 OCT 2025 | Raster collection handlers |
| 24 OCT 2025 | Big Raster ETL handlers |
| 25 NOV 2025 | STAC Metadata Helper |
| 26 NOV 2025 | Idempotent Vector ETL handlers |
| 03 DEC 2025 | Fathom ETL Two-Phase Architecture |
| 05 DEC 2025 | Fathom Container Inventory handlers |
| 07 DEC 2025 | Container Inventory handlers consolidated |
| 12 DEC 2025 | Unpublish handlers, Task routing validation |
| 15 DEC 2025 | Curated dataset update handlers, GAP-006 FIX |
| 17 DEC 2025 | H3 Aggregation handlers |
| 22 DEC 2025 | STAC Repair handlers |
| 28 DEC 2025 | H3 Export handlers |
| 29 DEC 2025 | Handler naming migration, Ingest Collection handlers |
| 09 JAN 2026 | STAC Rebuild handlers (F7.11) |
| 11 JAN 2026 | Docker consolidated handlers (F7.13, F7.18) |

---

## infrastructure/__init__.py

### Historical Context

The lazy loading pattern was implemented to solve Azure Functions cold start issues. The runtime has a specific initialization sequence where environment variables are not available during initial module imports.

### Original Docstring Note
```
Updated: 27 SEP 2025 - Added Azure Functions runtime explanation
```

### Feature Addition Timeline

| Date | Feature |
|------|---------|
| 22 NOV 2025 | Platform repositories simplified (thin tracking) |
| 22 NOV 2025 | PlatformStatusRepository REMOVED |
| 26 NOV 2025 | H3BatchTracker (idempotency framework) |
| 28 NOV 2025 | Resource validators (pre-flight validation) |
| 29 NOV 2025 | Azure Data Factory repository |
| 15 DEC 2025 | Curated dataset repositories |
| 23 DEC 2025 | Promoted dataset repository |
| 28 DEC 2025 | Pipeline Observability (E13) |
| 11 JAN 2026 | Checkpoint Manager (Docker resume) |

---

## jobs/__init__.py

### Historical Context

Job registration follows the same explicit pattern as handlers to avoid silent registration failures.

### Archived Job Comments

```
# ARCHIVED (07 DEC 2025) - replaced by inventory_container_contents
# from .container_list import ListContainerContentsWorkflow
# from .container_list_diamond import ListContainerContentsDiamondWorkflow
# from .inventory_container_geospatial import InventoryContainerGeospatialJob

# ARCHIVED (07 DEC 2025) - use inventory_container_contents instead
# "list_container_contents": ListContainerContentsWorkflow,
# "list_container_contents_diamond": ListContainerContentsDiamondWorkflow,
# "inventory_container_geospatial": InventoryContainerGeospatialJob,
```

### Feature Addition Timeline

| Date | Feature |
|------|---------|
| 07 DEC 2025 | Consolidated container inventory |
| 12 DEC 2025 | Unpublish workflows |
| 15 DEC 2025 | Curated dataset update |
| 17 DEC 2025 | H3 Aggregation, H3 Register Dataset |
| 22 DEC 2025 | STAC Repair |
| 28 DEC 2025 | H3 Export |
| 29 DEC 2025 | Ingest Collection |
| 10 JAN 2026 | STAC Rebuild (F7.11) |
| 11 JAN 2026 | Docker Jobs (F7.13, F7.18) |

---

## core/models/__init__.py

### Feature Addition Timeline

| Date | Feature |
|------|---------|
| 21 NOV 2025 | Janitor models |
| 22 NOV 2025 | Platform models simplified |
| 12 DEC 2025 | Unpublish audit models |
| 15 DEC 2025 | Curated dataset models, GAP-006 FIX |
| 21 DEC 2025 | ETL tracking models |
| 23 DEC 2025 | Promoted dataset models |
| 04 JAN 2026 | System snapshot models |
| 09 JAN 2026 | Unified metadata models (F7.8), External refs, Raster metadata (F7.9) |

---

## Notes

- All LAST_REVIEWED headers were updated to 14 JAN 2026
- Inline date comments were removed for cleaner code
- Feature tracking is maintained in this archive document
- The explicit registration pattern (no decorators) remains the standard
