# Discovery Automation — Vendor Delivery Scanning and Workflow Submission

**Date**: 03 APR 2026
**Status**: Design
**Version Scope**: v0.11.0 (does NOT block v0.10.10 switchover)
**Depends On**: `process_raster_collection` workflow (v0.10.10), `process_raster` workflow (v0.10.8)

---

## Problem

Raster imagery arrives in blob storage in vendor-specific packaging:

1. **Maxar deliveries** — nested prefix with `.MAN` manifest, `.TIL` tile layout, `R{n}C{n}` tiled GeoTIFFs, `.IMD`/`.RPB`/`.XML` sidecar metadata, `GIS_FILES/` shapefiles. TIFs are bare (not archived). Example: `rmhazuregeobronze/6682134166061933190/`.

2. **WBG Image Repository** — `{ISO3}/{YYYYMMDD}/{ISO3}_{geohash}_{bands}_{resolution}_{date}.{ext}` convention. Each image is a JSON+ZIP pair sharing a filename stem. The JSON contains pre-extracted metadata (vendor, resolution, bands, footprint WKT, capture date). The ZIP contains the actual imagery — 70% Maxar legacy deliveries (tiled TIFs + sidecars), 30% unknown formats. Lives in `rmhazurecold`.

Today, a human must inspect these structures, identify the raster files, and manually construct workflow submission payloads. This doesn't scale to the WBG repository's 63 countries, 501 date folders, and 467 ZIPs.

---

## Solution

Two **discovery workflows** that scan blob prefixes, classify contents, and submit appropriate processing workflows. Discovery and processing are cleanly separated — discovery produces a **manifest** (structured JSON describing what was found), then a shared `submit_from_manifest` handler translates manifest entries into workflow submissions.

Discovery workflows COMPLETE independently of spawned processing runs. No parent-child lifecycle coupling. No DAG engine changes required.

```
Discovery workflow (COMPLETED)
  → manifest: [ {classification, workflow, params}, ... ]
    → submit_from_manifest fires N independent processing runs
      → process_raster (run A)          ← independent lifecycle
      → process_raster (run B)          ← independent lifecycle
      → process_raster_collection (run C) ← independent lifecycle
```

### Design Principles

- **Workflows are specialized; handlers are generic.** Each vendor gets its own workflow YAML composing from a shared handler pool.
- **Discovery never blocks on processing.** The manifest is the contract boundary.
- **Unclassifiable items are reported, not blocking.** Mystery data appears in the manifest as `skipped` with diagnostic evidence. The batch continues.
- **`dry_run: true` by default.** Discovery shows what it *would* submit. Caller must explicitly opt into `dry_run: false`.
- **Traceability via `spawned_by_run_id`.** Every spawned workflow carries the discovery run ID in its params.
- **Bronze is the canonical source.** Cross-container data (e.g. cold→bronze) is copied before processing workflows reference it.

---

## Workflows

### 1. `discover_maxar_delivery`

Scans a known Maxar delivery prefix. No unzipping — TIFs are bare, structure is known.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prefix` | str | yes | Blob prefix to scan (e.g. `6682134166061933190/`) |
| `container_name` | str | yes | Container to scan (e.g. `rmhazuregeobronze`) |
| `collection_id` | str | yes | STAC collection name for the output |
| `dry_run` | bool | no | Default `true`. Set `false` to actually submit. |

**DAG Shape** (4 nodes, linear):

```
scan_prefix → classify_maxar_delivery → build_manifest → submit_workflows
```

| Node | Type | Handler | Purpose |
|------|------|---------|---------|
| `scan_prefix` | task | `discover_blob_prefix` | List all blobs under prefix, categorize by extension |
| `classify_delivery` | task | `classify_maxar_delivery` | Parse `.TIL` for tile layout, match TIFs to sidecars, extract `.IMD`/`.XML` metadata |
| `build_manifest` | task | `build_discovery_manifest` | Aggregate into manifest with workflow recommendation |
| `submit_workflows` | task | `submit_from_manifest` | Submit `process_raster_collection` with discovered `blob_list` |

**Output**: Typically submits a single `process_raster_collection` run with the discovered TIF blob paths as `blob_list`.

### 2. `discover_wbg_legacy`

Scans the WBG image repository. Each JSON+ZIP pair is independent — fan-out per pair, unzip, classify, aggregate, submit.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prefix` | str | yes | Blob prefix to scan (e.g. `wbgimagerepository/AFG/20130304/`) |
| `source_container` | str | no | Container to scan. Default `rmhazurecold`. |
| `container_name` | str | yes | Target bronze container for extracted data |
| `dry_run` | bool | no | Default `true`. Set `false` to actually submit. |

**DAG Shape** (7 nodes, fan-out/fan-in):

```
scan_prefix → identify_pairs → fan_out(process_pairs) → agg_results → build_manifest → submit_workflows
```

| Node | Type | Handler | Purpose |
|------|------|---------|---------|
| `scan_prefix` | task | `discover_blob_prefix` | List all blobs under prefix |
| `identify_pairs` | task | `wbg_match_json_zip_pairs` | Match JSON+ZIP by stem, read JSON metadata |
| `process_pairs` | fan_out | `wbg_process_single_pair` | Per pair: copy ZIP to bronze, unzip to mount, classify contents |
| `agg_results` | fan_in | (collect) | Aggregate classification results |
| `build_manifest` | task | `build_discovery_manifest` | Build manifest from aggregated results |
| `submit_workflows` | task | `submit_from_manifest` | Submit N processing workflows per manifest |

**Output**: Submits a mix of `process_raster` (single TIF) and `process_raster_collection` (tiled/multi-TIF) runs depending on what's inside each ZIP.

---

## Shared Handlers

### `discover_blob_prefix`

Scans a container+prefix, returns a categorized file inventory. Pure blob listing — no downloads.

```python
Input:  { container_name, prefix, source_container? }
Output: {
    "blobs": [ {"name": str, "size_bytes": int, "extension": str, "stem": str} ],
    "inventory": {
        "raster_files": [...],       # .tif, .tiff, .img, .vrt, .ecw, .jp2
        "archive_files": [...],      # .zip, .tar, .tar.gz
        "metadata_files": [...],     # .json, .xml, .imd, .rpb, .til, .man
        "preview_files": [...],      # .png, .jpg
        "shapefile_groups": [...],   # grouped .shp+.shx+.dbf+.prj by stem
        "other": [...]
    },
    "total_count": int,
    "total_size_bytes": int
}
```

Cross-container capable — `source_container` (defaults to `container_name`) controls where to list. This lets WBG scan cold storage while targeting bronze for output.

### `unzip_to_mount`

Downloads a ZIP from blob storage, extracts to mount, returns a content listing.

```python
Input:  { container_name, blob_name, source_container? }
Output: {
    "extract_path": "/mount/etl/{run_id}/{stem}/",
    "contents": [ {"relative_path": str, "size_bytes": int, "extension": str} ],
    "total_extracted_size_bytes": int
}
```

Safety limits:
- Max extracted size: configurable via `DISCOVERY_MAX_EXTRACT_SIZE_MB` (default from `RASTER_COLLECTION_MAX_FILE_SIZE_MB`)
- Max file count inside ZIP: configurable, default 100
- If exceeded, handler fails with diagnostic — does not silently truncate

ZIP bomb detection: if extracted size exceeds 10x the compressed size, abort with warning.

### `classify_raster_contents`

Given a directory listing (from `unzip_to_mount`), classifies what's inside.

```python
Input:  { extract_path, contents, metadata_json? }
Output: {
    "classification": "maxar_tiled" | "single_geotiff" | "multi_geotiff" | "non_raster" | "unclassifiable",
    "evidence": { ... },
    "raster_files": [...],
    "sidecar_files": [...],
    "recommended_workflow": "process_raster" | "process_raster_collection" | null,
    "recommended_params": { ... }
}
```

Classification logic (priority order):

1. **`maxar_tiled`** — `.TIL` file present AND `R{n}C{n}` pattern in TIF filenames
2. **`single_geotiff`** — exactly 1 raster file (`.tif`, `.tiff`, `.img`, `.vrt`)
3. **`multi_geotiff`** — 2+ raster files, no recognized tiling pattern
4. **`non_raster`** — no recognized raster files found. ECW, MrSID, JP2 are detected and reported but not currently processable.
5. **`unclassifiable`** — empty archive or doesn't fit any pattern

The optional `metadata_json` param lets the WBG workflow pass in the pre-extracted JSON sidecar (footprint, resolution, bands, vendor) for manifest enrichment.

### `build_discovery_manifest`

Aggregates classified results into a structured manifest.

```python
Input:  { classified_items: [...], discovery_source: str, discovery_prefix: str }
Output: {
    "manifest": {
        "source": "wbg_legacy" | "maxar_delivery",
        "prefix": str,
        "discovered_at": "ISO8601",
        "entries": [
            {
                "source_blob": str,
                "classification": str,
                "recommended_workflow": str | null,
                "recommended_params": { ... },
                "metadata": { ... }
            }
        ],
        "summary": {
            "total": int,
            "by_classification": {"single_geotiff": 35, "maxar_tiled": 8, "unclassifiable": 4},
            "by_workflow": {"process_raster": 35, "process_raster_collection": 8, "skipped": 4}
        }
    }
}
```

Entries with `recommended_workflow: null` (unclassifiable) are included in the manifest but marked for skipping. The manifest is stored as `result_data` on the build_manifest task — queryable after the run completes.

### `submit_from_manifest`

Reads manifest, submits workflows, records results. Rate-limited.

```python
Input:  {
    manifest: dict,
    max_concurrent_submissions: 5,
    spawned_by_run_id: str,
    dry_run: bool  # default true
}
Output: {
    "submitted": [ {"entry_index": int, "workflow": str, "run_id": str, "status": "accepted"} ],
    "rejected": [ {"entry_index": int, "workflow": str, "error": str, "status": "rejected"} ],
    "skipped": [ {"entry_index": int, "reason": str, "status": "skipped"} ],
    "summary": {"total": int, "submitted": int, "rejected": int, "skipped": int}
}
```

- **`dry_run: true` by default** (project convention). Returns what *would* be submitted without actually submitting.
- Calls the existing internal submission path (same code as the platform submit endpoint).
- Each spawned workflow's params include `spawned_by_run_id` for traceability.
- Rate-limited: submits at most `max_concurrent_submissions` at a time, sequentially.
- Duplicate submissions are caught by the existing SHA256 run_id dedup and recorded as `rejected`.

---

## Vendor-Specific Handlers

### `classify_maxar_delivery` (Maxar only)

Maxar-specific classification. Unlike the generic `classify_raster_contents` (which works on extracted ZIP contents), this operates on a live blob listing of a known Maxar prefix.

```python
Input:  { inventory (from discover_blob_prefix), prefix, container_name, collection_id }
Output: {
    "delivery_type": "maxar_tiled",
    "order_id": str,                  # extracted from prefix/manifest
    "product_parts": [
        {
            "part_id": str,           # e.g. "200007598595_01_P001_PSH"
            "tile_layout": {"rows": int, "cols": int},
            "tif_blobs": [str, ...],  # full blob paths for R{n}C{n} TIFs
            "sidecar_metadata": {     # parsed from .IMD/.XML
                "sensor": str,        # e.g. "WV02"
                "capture_date": str,
                "sun_azimuth": float,
                "sun_elevation": float,
                "off_nadir": float,
                "cloud_cover": float,
                "band_info": {...}
            }
        }
    ],
    "gis_files": { "order_shape": str, "product_shape": str, "tile_shape": str },
    "manifest_path": str
}
```

Parses the `.TIL` file to get authoritative tile layout rather than guessing from filenames. Extracts `.IMD`/`.XML` metadata for STAC enrichment. This metadata flows through the manifest into `process_raster_collection` params, and ultimately into STAC item properties.

### `wbg_match_json_zip_pairs` (WBG only)

Matches JSON+ZIP files by filename stem from the blob inventory.

```python
Input:  { inventory (from discover_blob_prefix), source_container }
Output: {
    "pairs": [
        {
            "stem": "AFG_tw30dz51mm65_3_0.5_20130304",
            "json_blob": "wbgimagerepository/AFG/20130304/AFG_tw30dz51mm65_3_0.5_20130304.json",
            "zip_blob": "wbgimagerepository/AFG/20130304/AFG_tw30dz51mm65_3_0.5_20130304.zip",
            "metadata": {             # pre-read from JSON sidecar
                "iso3": "AFG",
                "vendor": "MAXAR",
                "capture_date": "20130304",
                "resolution": "0.5",
                "nBands": "3",
                "ImageExtent": "POLYGON (...)",
                "securityClassification": "Official Use Only"
            }
        }
    ],
    "orphan_jsons": [...],            # JSONs without matching ZIP
    "orphan_zips": [...],             # ZIPs without matching JSON
    "total_pairs": int
}
```

Orphan files (JSON without ZIP or vice versa) are reported but don't block. The pairing handler also reads each JSON blob to extract metadata — this is lightweight (670 bytes per file) and avoids a second download round.

### `wbg_process_single_pair` (WBG only)

Composite handler for a single JSON+ZIP pair. Performs:

1. **Copy ZIP to bronze** — `source_container` (cold) → `container_name` (bronze) under `wbg_extracted/{stem}/`
2. **Unzip to mount** — extract to `/mount/etl/{run_id}/{stem}/`
3. **Classify contents** — call `classify_raster_contents` logic
4. **Upload extracted rasters to bronze** — bare TIFs uploaded to `wbg_extracted/{stem}/` so processing workflows can reference them via normal `raster_download_source`

```python
Input:  { json_blob, zip_blob, metadata, container_name, source_container, _run_id }
Output: {
    "stem": str,
    "classification": str,
    "evidence": { ... },
    "bronze_raster_paths": [str, ...],    # uploaded bare TIF paths in bronze
    "metadata": { ... },                  # from JSON sidecar
    "recommended_workflow": str | null,
    "recommended_params": { ... }
}
```

If classification is `unclassifiable`, the handler still returns `success: true` — classification is its job, and "unclassifiable" is a valid classification result. The manifest builder handles routing.

---

## Cross-Container Data Flow

### WBG Legacy Path

```
rmhazurecold/wbgimagerepository/AFG/20130304/AFG_tw30dz51mm65_3_0.5_20130304.zip
  ↓ copy to bronze
rmhazuregeobronze/wbg_extracted/AFG_tw30dz51mm65_3_0.5_20130304/
  ↓ unzip to mount (discovery + classification)
/mount/etl/{run_id}/AFG_tw30dz51mm65_3_0.5_20130304/
  ├── scene.tif                    ← classified as single_geotiff
  ├── scene.tfw                    ← world file (sidecar)
  └── metadata.xml
  ↓ upload extracted rasters to bronze
rmhazuregeobronze/wbg_extracted/AFG_tw30dz51mm65_3_0.5_20130304/scene.tif
  ↓ submit_from_manifest fires process_raster
process_raster run: blob_name = "wbg_extracted/AFG_tw30dz51mm65_3_0.5_20130304/scene.tif"
```

### Maxar Delivery Path

```
rmhazuregeobronze/6682134166061933190/.../R1C1.TIF    (already in bronze)
  ↓ discover_blob_prefix lists them
  ↓ classify_maxar_delivery parses .TIL, matches tiles
  ↓ submit_from_manifest fires process_raster_collection
process_raster_collection run: blob_list = ["6682134166061933190/.../R1C1.TIF", "...R2C1.TIF"]
```

No cross-container copy needed for Maxar — data is already in bronze.

---

## Error Handling

### Classification failures (unclassifiable contents)

- Fan-out child returns `success: true` with `classification: "unclassifiable"` and diagnostic evidence
- `build_discovery_manifest` includes the entry with `recommended_workflow: null`
- `submit_from_manifest` records it as `skipped`
- Discovery run COMPLETES — unclassifiable items do not block the batch

### Fan-out child failures (download error, corrupt ZIP, mount full)

- Failed fan-out child is FAILED with `error_details`
- Fan-in collects what succeeded
- `build_discovery_manifest` builds a partial manifest from successful results
- Discovery run COMPLETES with partial manifest
- Failed entries visible in fan-out task list

### Duplicate submission guard

- Same blob paths → same workflow params → same SHA256 run_id → submission rejected
- `submit_from_manifest` records these as `rejected` with `"error": "duplicate_run_id"`
- Safe to re-run discovery without creating duplicate processing runs

### ZIP safety limits

| Check | Default | Behavior on violation |
|-------|---------|----------------------|
| Max extracted size | `DISCOVERY_MAX_EXTRACT_SIZE_MB` env var | Handler fails with diagnostic |
| Max file count in ZIP | 100 | Handler fails with diagnostic |
| ZIP bomb (extracted > 10x compressed) | Always on | Handler aborts with warning |

### Manifest summary example

A scan of 50 WBG ZIPs where 4 are mystery data and 3 fail to unzip:

```json
{
    "summary": {
        "total_pairs": 50,
        "fan_out_succeeded": 47,
        "fan_out_failed": 3,
        "submitted": 39,
        "skipped": 4,
        "rejected": 0,
        "by_classification": {
            "single_geotiff": 31,
            "maxar_tiled": 8,
            "unclassifiable": 4,
            "multi_geotiff": 4
        },
        "by_workflow": {
            "process_raster": 35,
            "process_raster_collection": 8,
            "skipped": 4
        }
    }
}
```

The 3 `fan_out_failed` are children that failed before classification (corrupt ZIP, download error) — visible in the DAG task list but absent from the manifest. The 4 `skipped` are entries that classified successfully as `unclassifiable` — present in the manifest with diagnostic evidence for human review.

---

## Traceability

Every spawned workflow carries these params:

| Param | Source | Purpose |
|-------|--------|---------|
| `spawned_by_run_id` | Discovery run ID | Trace child back to parent |
| `discovery_source` | `"wbg_legacy"` or `"maxar_delivery"` | Origin system |
| `source_metadata` | WBG JSON or Maxar `.IMD` fields | Vendor metadata for STAC enrichment |

This metadata flows through processing into STAC materialization — final STAC items carry provenance from the original vendor metadata without processing workflows needing to know about discovery.

---

## Handler Inventory

| Handler | Type | Used By | I/O Profile |
|---------|------|---------|-------------|
| `discover_blob_prefix` | Shared | Both workflows | Blob API (list only) |
| `unzip_to_mount` | Shared | WBG (inside composite) | Blob download + mount write |
| `classify_raster_contents` | Shared | WBG (inside composite) | Pure logic (no I/O) |
| `build_discovery_manifest` | Shared | Both workflows | Pure logic (no I/O) |
| `submit_from_manifest` | Shared | Both workflows | Internal submission API |
| `classify_maxar_delivery` | Maxar | `discover_maxar_delivery` | Blob download (small sidecars only) |
| `wbg_match_json_zip_pairs` | WBG | `discover_wbg_legacy` | Blob download (JSON sidecars only) |
| `wbg_process_single_pair` | WBG | `discover_wbg_legacy` | Blob copy + download + mount write + blob upload |

**8 new handlers total.** 5 shared/utility, 1 Maxar-specific, 2 WBG-specific.

---

## Existing Code Disposition

### `services/delivery_discovery.py` (existing)

This module has the right structure (`detect_manifest_files`, `detect_tile_pattern`, `analyze_delivery_structure`) but:

- Not wired to any endpoint or handler
- `recommended_workflow.parameters` uses stale field names (`output_tier`, `output_folder`)
- Doesn't parse vendor metadata files (only detects their presence)
- Treats all blobs as flat list (doesn't reconstruct tree structure)

**Action**: Refactor into the new shared handlers. `detect_manifest_files` and `detect_tile_pattern` logic moves into `classify_raster_contents` and `classify_maxar_delivery`. The top-level `analyze_delivery_structure` function is superseded by the workflow-level composition. The file can be archived or deleted.

### `services/container_analysis.py` (existing)

General-purpose container analysis (pattern detection, duplicates, size distribution). Useful for diagnostics but not directly consumed by discovery workflows. **No changes needed.**

### `infrastructure/blob.py:list_blobs()` (existing)

Used by `discover_blob_prefix` handler internally. Already supports prefix filtering and `.gdb` folder aggregation. **No changes needed.**

---

## Scope and Versioning

**This feature is part of v0.11.0.** It does NOT block the v0.10.10 DAG switchover.

The v0.10.10 milestone completes the strangler fig (Epoch 4 → Epoch 5 migration). Discovery automation is a v0.11.0 enhancement that builds on top of the completed DAG infrastructure.

Implementation artifacts should be tracked in a `V11_` documentation series (separate from the existing `V10_DEFERRED_FIXES.md` and `V10_DECISIONS.md`).
