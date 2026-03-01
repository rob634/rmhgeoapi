# REFLEXION Pipeline: SG-5 Fix

**Date**: 01 MAR 2026
**Target**: Unpublish raster pipeline — blobs not actually deleted
**Bug**: `blobs_deleted: 0` and COG blob remains in Azure Storage after successful unpublish
**Root Cause**: `/vsiaz/` asset hrefs misparse produces invalid blob paths; delete_blob silently succeeds on nonexistent paths; finalize_job always reports 0
**Pipeline**: R → F → P → J (sequential)
**Run**: 15 (REFLEXION)

---

## Token Usage

| Agent | Tokens | Duration |
|-------|--------|----------|
| R (Reverse Engineer) | 90,426 | 3m 08s |
| F (Fault Injector) | 100,721 | 6m 27s |
| P (Patch Author) | 37,444 | 2m 38s |
| J (Judge) | 50,309 | 2m 46s |
| **Total** | **278,900** | **~15m 00s** |

---

## Three-Bug Cascade

SG-5 is caused by three bugs working in concert:

### Bug A (ROOT CAUSE — CRITICAL)

`inventory_raster_item` at `services/unpublish_handlers.py:152` does not handle `/vsiaz/` prefixed asset hrefs. STAC items built by `RasterMetadata.to_stac_item()` use `/vsiaz/{container}/{blob_path}` format. The handler's URL parser treated this as a "relative path" (because it starts with `/`), stripped the leading slash, and produced `blob_path='vsiaz/silver-cogs/{actual_path}'` in hardcoded container `silver-cogs`. This path does not exist in Azure Storage.

### Bug B (MASKING — HIGH)

`delete_stac_and_audit` at `services/unpublish_handlers.py:1174` did not include `blobs_deleted` in its return dict. `finalize_job` reads `cleanup.get("blobs_deleted", [])` which always returned `[]`, so the job result always reported `blobs_deleted: 0`.

### Bug C (SILENT FAILURE — MEDIUM)

`delete_blob` at `services/unpublish_handlers.py:760` treats "blob not found" as idempotent success (`already_gone: True`). When Bug A sent it a wrong path, `blob_exists` returned False, and the handler returned success. No error raised, real blob untouched.

---

## Verdicts

| Patch | Fault | Severity | Verdict |
|-------|-------|----------|---------|
| 1 | Bug A (/vsiaz/ href misparse) | CRITICAL | **APPROVE** |
| 2 | Bug B (missing blobs_deleted return) | HIGH | **APPROVE** |
| 3 | Bug B+C (accurate blob count) | MEDIUM | **APPROVE** |

---

## Patches Applied

### Patch 1: /vsiaz/ href parsing (CRITICAL)

**File**: `services/unpublish_handlers.py` lines 152-162

Added `elif href.startswith('/vsiaz/'):` branch before generic relative-path catch-all:

```python
elif href.startswith('/vsiaz/'):
    # GDAL /vsiaz/ virtual path: /vsiaz/{container}/{blob_path}
    vsiaz_path = href[len('/vsiaz/'):]
    if '/' in vsiaz_path:
        container, blob_path = vsiaz_path.split('/', 1)
        blobs_to_delete.append({
            'container': container,
            'blob_path': blob_path,
            'asset_key': asset_key,
            'href': href
        })
```

### Patch 2: blobs_deleted passthrough (HIGH)

**File**: `services/unpublish_handlers.py` line 1183

Added to `delete_stac_and_audit` return dict:

```python
"blobs_deleted": params.get('blobs_deleted', []),
```

### Patch 3: Accurate blob count (MEDIUM)

**File**: `jobs/unpublish_raster.py` lines 290-293

Changed `len(cleanup.get("blobs_deleted", []))` to:

```python
"blobs_deleted": sum(
    1 for b in cleanup.get("blobs_deleted", [])
    if isinstance(b, dict) and b.get("deleted") is True
),
```

---

## Key Insight (Agent J)

> This three-bug cascade reveals that idempotency patterns (designed to handle retries) can mask data-integrity bugs when not paired with observability. The `delete_blob` handler silently succeeded on nonexistent paths, the missing `blobs_deleted` passthrough ensured no one could detect the difference, and the URL parser's failure to handle `/vsiaz/` meant every raster unpublish silently left orphaned blobs. The core lesson: idempotent operations must log expected-vs-actual state so parsing errors surface in monitoring rather than hiding behind graceful degradation.

---

## Residual Risks

| Risk | Priority |
|------|----------|
| `unpublish_zarr.py` `finalize_job` does not report `blobs_deleted` | LOW |
| Bug C unpatched — `delete_blob` still masks wrong paths | MEDIUM |
| No end-to-end integration test for raster unpublish | MEDIUM |
| Dry-run return missing `blobs_deleted` field (inconsistent) | LOW |

---

## Verification Steps

After deploying:

1. Submit raster unpublish job with `dry_run=false`
2. Verify Stage 1 inventory shows correct blob path (no `vsiaz/` prefix)
3. Verify Stage 2 `delete_blob` returns `deleted: True`
4. Verify final result shows `blobs_deleted: 1`
5. Verify blob no longer exists in Azure Storage
