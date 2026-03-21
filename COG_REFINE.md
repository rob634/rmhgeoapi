# Geotiler Service Layer — ETL-Side Improvements

Findings from API consumer assessment of `rmhtitiler v0.10.0.0`. All improvements originate from the master metadata table as source of truth.

## 1. COG Color Interpretation Stamping

**Problem:** `rio-cogeo`'s `cog_translate` rewrites the TIFF and drops band-level color interpretation. All bands end up as `gray`/`undefined`, so TiTiler can't auto-render RGB composites and the PNG encoder fails on 4-band files.

**Fix:** Post-translate header stamp using the ETL's existing band classification:

```python
import rasterio

COLORINTERP = {
    "RGB":  [ColorInterp.red, ColorInterp.green, ColorInterp.blue],
    "RGBA": [ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha],
    "RGBN": [ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.undefined],
    "DEM":  [ColorInterp.gray],
}

with rasterio.open(cog_path, "r+") as ds:
    ds.colorinterp = COLORINTERP[classification]
```

**Key detail:** Marking band 4 as `alpha` vs `undefined` is critical — TiTiler uses alpha as a transparency mask automatically, while `undefined`/NIR is treated as renderable data.

## 2. Nodata Value Assignment

**Problem:** COGs have no declared nodata value. Black border pixels (value 0) render as solid black instead of transparent, and will occlude valid pixels during mosaicking.

**Fix:** Stamp nodata during or after COG creation, based on data type:

- **Optical imagery (RGB, RGBN):** `nodata=0`
- **RGBA:** No nodata needed — alpha band handles transparency
- **DEMs:** `nodata=-9999` (or appropriate sentinel)
- **Thematic/categorical:** Dataset-specific

```python
with rasterio.open(cog_path, "r+") as ds:
    ds.nodata = nodata_value  # from master metadata table
```

## 3. STAC Band Metadata Enrichment

**Problem:** `raster:bands` in STAC items includes statistics and histograms but bands are anonymous — no `common_name` or nodata fields.

**Fix:** During STAC materialization, populate from master metadata table:

```json
"raster:bands": [
    {
        "common_name": "red",
        "data_type": "uint16",
        "nodata": 0,
        "statistics": { ... }
    }
]
```

This lets consuming apps construct correct `bidx` parameters and rendering defaults without guessing.

## 4. Default Tile URL Band Selection

**Problem:** Default TiTiler tile requests on 4-band COGs fail because the PNG encoder can't handle 4-band output.

**Fix:** Include explicit `bidx` parameters in the tile URL templates embedded in STAC items. For RGBN imagery, the TileJSON link should include `&bidx=1&bidx=2&bidx=3` so consuming apps get working tiles out of the box.

## 5. TiPG Catalog Cache Sync

**Problem:** TiPG's internal catalog refresh discovers only 2 meta-tables (`collections`, `last_updated`) instead of the 34 actual geo tables, despite `collections_discovered` reporting success. The live `/vector/collections` endpoint works correctly. This causes the Catalog UI to show "No collections available."

**Fix:** Investigate the catalog TTL refresh code path — the live enumeration and the cached catalog use different logic. The 60-second TTL refresh thinks it succeeded but is registering the wrong tables.

## Implementation Order

These are listed in dependency order — each builds on the previous:

1. **Color interpretation stamping** — unblocks correct default rendering
2. **Nodata assignment** — unblocks transparency and mosaicking
3. **STAC band metadata** — propagates 1 & 2 to the discovery layer
4. **Default tile URL bands** — makes STAC items render-ready for consumers
5. **TiPG catalog fix** — restores the human browsing experience