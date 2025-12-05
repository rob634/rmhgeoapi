# Archived Wiki Documents

**Date Archived**: 03 DEC 2025
**Reason**: These documents reference the old v1 raster processing implementations that have been superseded by JobBaseMixin-based v2 implementations.

## Archived Files

| File | Original Location | Reason |
|------|-------------------|--------|
| WIKI_API_PROCESS_RASTER_TRACETHROUGH.md | Root | References `jobs/process_raster.py` (v1), not v2 JobBaseMixin pattern |
| WIKI_API_PROCESS_RASTER_COLLECTION_TRACETHROUGH.md | Root | References old collection job implementation |

## Current Documentation

For current raster processing documentation, see:
- `WIKI_JOB_PROCESS_RASTER_V2.md` - Authoritative v2 raster processing guide
- `WIKI_API_JOB_SUBMISSION.md` - Complete API reference including raster jobs

## Notes

The v2 implementations use JobBaseMixin which provides:
- 73% less code (280 lines vs 743 lines)
- Declarative parameter validation via `parameters_schema`
- Pre-flight resource validation (blob_exists check)
- Config integration for defaults

These archived traces may still be useful for understanding the historical evolution of the codebase.
