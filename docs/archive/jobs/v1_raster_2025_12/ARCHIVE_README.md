# V1 Raster Jobs Archive

**Archived**: 03 DEC 2025
**Author**: Robert and Geospatial Claude Legion

---

## Why These Files Were Archived

These files represent the **v1 (legacy) raster processing jobs** that have been superseded by the v2 mixin-pattern implementations.

### V2 Replacements (Production-Validated 03 DEC 2025)

| V1 Job (Archived) | V2 Replacement (Active) | Test Results |
|-------------------|------------------------|--------------|
| `process_raster.py` | `process_raster_v2.py` | dctest.tif (25 MB) |
| `process_large_raster.py` | `process_large_raster_v2.py` | WV2 (4.4 GB), Antigua (11 GB), DTM (986 MB) |
| `process_raster_collection.py` | `process_raster_collection_v2.py` | namangan/ (4 files, 1.7 GB) |

### Code Reduction

| Metric | V1 Total | V2 Total | Reduction |
|--------|----------|----------|-----------|
| Lines of Code | 2,437 | 894 | 63% |
| Files | 3 | 3 | Same |
| Pattern | Manual boilerplate | JobBaseMixin | DRY |

---

## Files in This Archive

| File | Lines | Original Purpose |
|------|-------|------------------|
| `process_raster.py` | 743 | Single raster → COG |
| `process_large_raster.py` | 789 | Large raster (1-30 GB) → Tiled COGs |
| `process_raster_collection.py` | 905 | Multi-tile collection → MosaicJSON + STAC |
| `hello_world_mixin.py` | 223 | Test version of mixin pattern |
| `hello_world_original_backup.py` | 351 | Pre-mixin backup of hello_world |

---

## If You Need to Restore

1. These files are preserved for historical reference
2. If v2 fails in production, files can be restored from this archive
3. Copy file back to `jobs/` directory
4. Add import and registry entry in `jobs/__init__.py`

---

## Related Documentation

- V2 implementation: See `jobs/process_raster_v2.py`, `jobs/process_large_raster_v2.py`
- Mixin pattern: See `jobs/raster_mixin.py`, `jobs/mixins.py`
- Job creation guide: See `JOB_CREATION_QUICKSTART.md`
