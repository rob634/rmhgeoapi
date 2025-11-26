# ============================================================================
# CLAUDE CONTEXT - SERVICE - FATHOM ETL HANDLERS
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Service - Task handlers for Fathom flood hazard ETL pipeline
# PURPOSE: Inventory, merge/stack, and STAC registration for Fathom data
# LAST_REVIEWED: 26 NOV 2025
# EXPORTS: fathom_inventory, fathom_merge_stack, fathom_stac_register
# INTERFACES: Standard handler contract (params, context) -> dict
# PYDANTIC_MODELS: None
# DEPENDENCIES: pandas, rasterio, GDAL, azure.storage.blob
# SOURCE: bronze-fathom container (Fathom Global Flood Maps v3)
# SCOPE: Regional flood hazard data consolidation
# VALIDATION: Handler-level validation
# PATTERNS: Handler contract compliance, streaming blob access
# ENTRY_POINTS: Registered in services/__init__.py ALL_HANDLERS
# ============================================================================

"""
Fathom ETL Task Handlers

Three handlers for the ProcessFathomWorkflow:

1. fathom_inventory: Parse CSV, group files into merge targets
2. fathom_merge_stack: Merge tiles spatially + stack return periods as bands
3. fathom_stac_register: Create STAC collection and items in pgstac

Data Flow:
- Input: 15,392 small 1°×1° tiles (CI pilot)
- Output: 65 multi-band COGs with return periods as bands
- STAC: 65 items in fathom-flood collection

Author: Robert and Geospatial Claude Legion
Date: 26 NOV 2025
"""

import re
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional
from collections import defaultdict

from util_logger import LoggerFactory, ComponentType


# Return period band mapping (constant)
RETURN_PERIODS = ["1in5", "1in10", "1in20", "1in50", "1in100", "1in200", "1in500", "1in1000"]

# SSP scenario normalizations
SSP_MAP = {
    "SSP1_2.6": "ssp126",
    "SSP2_4.5": "ssp245",
    "SSP3_7.0": "ssp370",
    "SSP5_8.5": "ssp585"
}

# Flood type normalizations
FLOOD_TYPE_MAP = {
    "COASTAL_DEFENDED": {"flood_type": "coastal", "defense": "defended"},
    "COASTAL_UNDEFENDED": {"flood_type": "coastal", "defense": "undefended"},
    "FLUVIAL_DEFENDED": {"flood_type": "fluvial", "defense": "defended"},
    "FLUVIAL_UNDEFENDED": {"flood_type": "fluvial", "defense": "undefended"},
    "PLUVIAL_DEFENDED": {"flood_type": "pluvial", "defense": "defended"}
}


def fathom_inventory(params: dict, context: dict = None) -> dict:
    """
    Parse Fathom file list CSV and create merge groups.

    Groups files by: flood_type + year + ssp_scenario
    Each group will be merged spatially with return periods as bands.

    Args:
        params: Task parameters
            - region_code: ISO country code (e.g., "CI")
            - region_name: Human-readable name (optional)
            - source_container: Container with source files
            - file_list_csv: Path to CSV file (optional, auto-detected if None)
            - flood_types: List of flood types to process (optional, all if None)
            - years: List of years to process (optional, all if None)
            - ssp_scenarios: List of SSP scenarios (optional, all if None)
            - dry_run: If True, only create inventory

    Returns:
        dict with merge_groups and summary statistics
    """
    import pandas as pd
    from infrastructure import BlobRepository

    logger = LoggerFactory.create_logger(
        ComponentType.SERVICE,
        "fathom_inventory"
    )

    region_code = params["region_code"].upper()
    region_name = params.get("region_name")
    source_container = params.get("source_container", "bronze-fathom")
    file_list_csv = params.get("file_list_csv")
    filter_flood_types = params.get("flood_types")
    filter_years = params.get("years")
    filter_ssp = params.get("ssp_scenarios")
    dry_run = params.get("dry_run", False)

    logger.info(f"📋 Starting Fathom inventory for region: {region_code}")

    # Auto-detect CSV filename if not provided
    if not file_list_csv:
        # Pattern: CI_Côte_d'Ivoire_file_list.csv
        blob_repo = BlobRepository.instance()

        # List blobs to find CSV
        all_blobs = blob_repo.list_blobs(source_container)
        csv_blobs = [b for b in all_blobs if b.endswith('_file_list.csv')]
        matching = [c for c in csv_blobs if c.startswith(f"{region_code}_")]

        if not matching:
            return {
                "success": False,
                "error": f"No file list CSV found for region {region_code}. Available: {csv_blobs}"
            }

        file_list_csv = matching[0]
        if region_name is None:
            # Extract region name from CSV filename
            # "CI_Côte_d'Ivoire_file_list.csv" → "Côte d'Ivoire"
            parts = file_list_csv.replace("_file_list.csv", "").split("_", 1)
            if len(parts) > 1:
                region_name = parts[1].replace("_", " ")

    logger.info(f"   Using file list: {file_list_csv}")

    # Download and parse CSV
    blob_repo = BlobRepository.instance()
    csv_bytes = blob_repo.read_blob(source_container, file_list_csv)

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp.write(csv_bytes)
        tmp_path = tmp.name

    df = pd.read_csv(tmp_path)
    Path(tmp_path).unlink()  # Clean up

    logger.info(f"   Loaded {len(df)} file paths from CSV")

    # Parse file paths to extract metadata
    # Pattern: FLOOD_TYPE/YEAR/RETURN_PERIOD[_or_SSP]/filename.tif
    # Filename: 1in100-COASTAL-DEFENDED-2020_n04w006.tif
    # or: 1in100-COASTAL-DEFENDED-2050-SSP2_4.5_n04w006.tif

    parsed_files = []
    for path in df.iloc[:, 0]:  # First column is path
        parsed = _parse_fathom_path(path)
        if parsed:
            parsed_files.append(parsed)

    logger.info(f"   Parsed {len(parsed_files)} valid file records")

    # Apply filters
    if filter_flood_types:
        parsed_files = [f for f in parsed_files if f["flood_type_raw"] in filter_flood_types]
        logger.info(f"   After flood_type filter: {len(parsed_files)} files")

    if filter_years:
        parsed_files = [f for f in parsed_files if f["year"] in filter_years]
        logger.info(f"   After year filter: {len(parsed_files)} files")

    if filter_ssp:
        parsed_files = [f for f in parsed_files if f["ssp_raw"] in filter_ssp or f["ssp_raw"] is None]
        logger.info(f"   After SSP filter: {len(parsed_files)} files")

    # Group files by output target (flood_type + year + ssp)
    groups = defaultdict(lambda: {
        "flood_type_raw": None,
        "flood_type": None,
        "defense": None,
        "year": None,
        "ssp_raw": None,
        "ssp": None,
        "return_period_files": defaultdict(list),  # return_period → [file_paths]
        "tiles": set()
    })

    for f in parsed_files:
        # Group key: flood_type_raw + year + ssp
        key = (f["flood_type_raw"], f["year"], f["ssp_raw"])
        group = groups[key]

        group["flood_type_raw"] = f["flood_type_raw"]
        group["flood_type"] = f["flood_type"]
        group["defense"] = f["defense"]
        group["year"] = f["year"]
        group["ssp_raw"] = f["ssp_raw"]
        group["ssp"] = f["ssp"]
        group["return_period_files"][f["return_period"]].append(f["path"])
        group["tiles"].add(f["tile"])

    # Convert to output format
    merge_groups = []
    for key, group in groups.items():
        # Generate output filename
        flood_type_slug = f"{group['flood_type']}-{group['defense']}"
        year = group["year"]

        if group["ssp"]:
            output_name = f"fathom_{region_code.lower()}_{flood_type_slug}_{year}_{group['ssp']}"
        else:
            output_name = f"fathom_{region_code.lower()}_{flood_type_slug}_{year}"

        # Verify we have all 8 return periods
        rp_files = group["return_period_files"]
        missing_rps = [rp for rp in RETURN_PERIODS if rp not in rp_files]

        if missing_rps:
            logger.warning(f"   ⚠️ {output_name}: Missing return periods: {missing_rps}")

        merge_groups.append({
            "output_name": output_name,
            "flood_type_raw": group["flood_type_raw"],
            "flood_type": group["flood_type"],
            "defense": group["defense"],
            "year": group["year"],
            "ssp_raw": group["ssp_raw"],
            "ssp": group["ssp"],
            "tile_count": len(group["tiles"]),
            "tiles": sorted(group["tiles"]),
            "return_period_files": {rp: sorted(files) for rp, files in rp_files.items()},
            "file_count": sum(len(files) for files in rp_files.values())
        })

    # Sort by output name for consistent ordering
    merge_groups.sort(key=lambda x: x["output_name"])

    # Summary statistics
    all_flood_types = sorted(set(g["flood_type_raw"] for g in merge_groups))
    all_years = sorted(set(g["year"] for g in merge_groups))
    total_files = sum(g["file_count"] for g in merge_groups)

    logger.info(f"✅ Inventory complete:")
    logger.info(f"   Total source files: {total_files}")
    logger.info(f"   Merge groups: {len(merge_groups)}")
    logger.info(f"   Flood types: {all_flood_types}")
    logger.info(f"   Years: {all_years}")

    if dry_run:
        logger.info("   🔍 DRY RUN - no files will be processed")

    return {
        "success": True,
        "result": {
            "region_code": region_code,
            "region_name": region_name,
            "total_files": total_files,
            "merge_group_count": len(merge_groups),
            "merge_groups": merge_groups,
            "flood_types": all_flood_types,
            "years": all_years,
            "dry_run": dry_run
        }
    }


def _parse_fathom_path(path: str) -> Optional[Dict[str, Any]]:
    """
    Parse Fathom file path to extract metadata.

    Examples:
        COASTAL_DEFENDED/2020/1in100/1in100-COASTAL-DEFENDED-2020_n04w006.tif
        FLUVIAL_DEFENDED/2050/SSP2_4.5/1in100-FLUVIAL-DEFENDED-2050-SSP2_4.5_n07w005.tif

    Returns:
        Parsed metadata dict or None if parsing fails
    """
    try:
        parts = path.split("/")
        if len(parts) < 4:
            return None

        flood_type_raw = parts[0]  # e.g., "COASTAL_DEFENDED"
        year = int(parts[1])  # e.g., 2020
        filename = parts[-1]  # e.g., "1in100-COASTAL-DEFENDED-2020_n04w006.tif"

        # Extract return period from folder or filename
        # Folder could be return period (1in100) or SSP scenario (SSP2_4.5)
        folder_3 = parts[2]
        if folder_3.startswith("1in"):
            return_period = folder_3
            ssp_raw = None
        else:
            # SSP scenario folder - extract return period from filename
            ssp_raw = folder_3
            # Filename pattern: 1in100-COASTAL-DEFENDED-2050-SSP2_4.5_n07w005.tif
            match = re.match(r"(1in\d+)-", filename)
            if not match:
                return None
            return_period = match.group(1)

        # Extract tile coordinate from filename
        # Pattern: ..._n04w006.tif or ..._s10e020.tif
        tile_match = re.search(r"_([ns]\d+[ew]\d+)\.tif$", filename, re.IGNORECASE)
        if not tile_match:
            return None
        tile = tile_match.group(1).lower()

        # Normalize flood type
        ft_info = FLOOD_TYPE_MAP.get(flood_type_raw, {})

        # Normalize SSP
        ssp = SSP_MAP.get(ssp_raw) if ssp_raw else None

        return {
            "path": path,
            "flood_type_raw": flood_type_raw,
            "flood_type": ft_info.get("flood_type", "unknown"),
            "defense": ft_info.get("defense", "unknown"),
            "year": year,
            "ssp_raw": ssp_raw,
            "ssp": ssp,
            "return_period": return_period,
            "tile": tile
        }

    except Exception:
        return None


def fathom_merge_stack(params: dict, context: dict = None) -> dict:
    """
    Merge tiles spatially and stack return periods as bands.

    For each merge group:
    1. Download all source tiles (organized by return period)
    2. For each return period: build VRT for spatial merge
    3. Stack 8 VRTs as bands into single multi-band COG
    4. Upload to silver-cogs container

    Args:
        params: Task parameters
            - merge_group: Group definition from inventory
            - source_container: Container with source tiles
            - output_container: Container for output COG
            - output_prefix: Folder prefix in output container
            - region_code: ISO country code

    Returns:
        dict with output blob path and metadata
    """
    import rasterio
    from rasterio.merge import merge
    from rasterio.enums import Resampling
    import numpy as np
    from infrastructure import BlobRepository
    from config import get_config

    logger = LoggerFactory.create_logger(
        ComponentType.SERVICE,
        "fathom_merge_stack"
    )

    merge_group = params["merge_group"]
    source_container = params.get("source_container", "bronze-fathom")
    output_container = params.get("output_container", "silver-cogs")
    output_prefix = params.get("output_prefix", "fathom")
    region_code = params["region_code"].lower()
    force_reprocess = params.get("force_reprocess", False)

    output_name = merge_group["output_name"]
    logger.info(f"🔧 Processing merge group: {output_name}")
    logger.info(f"   Tiles: {merge_group['tile_count']}, Files: {merge_group['file_count']}")

    config = get_config()
    blob_repo = BlobRepository.instance()

    # =========================================================================
    # IDEMPOTENCY CHECK (26 NOV 2025)
    # Skip processing if output COG already exists (unless force_reprocess=True)
    # =========================================================================
    output_blob_path = f"{output_prefix}/{region_code}/{output_name}.tif"

    if not force_reprocess and blob_repo.blob_exists(output_container, output_blob_path):
        logger.info(f"⏭️ SKIP: Output already exists: {output_container}/{output_blob_path}")

        # Return success with skipped flag for tracking
        return {
            "success": True,
            "skipped": True,
            "result": {
                "output_blob": output_blob_path,
                "output_container": output_container,
                "output_name": output_name,
                "flood_type": merge_group["flood_type"],
                "defense": merge_group["defense"],
                "year": merge_group["year"],
                "ssp": merge_group.get("ssp"),
                "tile_count": merge_group["tile_count"],
                "file_count": merge_group["file_count"],
                "message": "Output COG already exists - skipped processing"
            }
        }

    # Create temp directory for processing
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Download and process each return period
        merged_arrays = []
        transform = None
        crs = None

        for rp_idx, return_period in enumerate(RETURN_PERIODS):
            rp_files = merge_group["return_period_files"].get(return_period, [])

            if not rp_files:
                logger.warning(f"   ⚠️ Missing return period: {return_period}")
                # Create empty band with nodata
                if merged_arrays:
                    empty = np.full_like(merged_arrays[0], -32768, dtype=np.int16)
                    merged_arrays.append(empty)
                continue

            logger.info(f"   📥 Downloading {len(rp_files)} files for {return_period}...")

            # Download tiles for this return period
            local_tiles = []
            for blob_path in rp_files:
                local_path = tmpdir / f"{return_period}_{Path(blob_path).name}"
                blob_bytes = blob_repo.read_blob(source_container, blob_path)
                with open(local_path, "wb") as f:
                    f.write(blob_bytes)
                local_tiles.append(str(local_path))

            # Merge tiles spatially using rasterio
            datasets = [rasterio.open(p) for p in local_tiles]

            # Get CRS and profile from first dataset
            if crs is None:
                crs = datasets[0].crs
                profile = datasets[0].profile.copy()

            # Merge all tiles for this return period
            merged_data, merged_transform = merge(
                datasets,
                resampling=Resampling.nearest,
                nodata=-32768
            )

            # merged_data shape: (1, height, width) - squeeze to (height, width)
            merged_arrays.append(merged_data[0])

            if transform is None:
                transform = merged_transform

            # Close datasets
            for ds in datasets:
                ds.close()

            # Clean up downloaded tiles to free space
            for p in local_tiles:
                Path(p).unlink()

            logger.info(f"   ✅ Merged {return_period}: shape {merged_data[0].shape}")

        # Stack all bands into single array
        if not merged_arrays:
            return {
                "success": False,
                "error": "No data to merge"
            }

        stacked = np.stack(merged_arrays, axis=0)
        logger.info(f"   📦 Stacked array shape: {stacked.shape} (bands, height, width)")

        # Write multi-band COG
        output_path = tmpdir / f"{output_name}.tif"

        # Update profile for multi-band COG
        profile.update(
            driver="GTiff",
            count=len(RETURN_PERIODS),
            dtype=np.int16,
            crs=crs,
            transform=transform,
            width=stacked.shape[2],
            height=stacked.shape[1],
            compress="DEFLATE",
            predictor=2,  # Horizontal differencing for int data
            tiled=True,
            blockxsize=512,
            blockysize=512,
            nodata=-32768
        )

        # Write COG directly using rasterio
        # (rasterio with overviews creates a COG-compatible structure)
        profile.update(
            BIGTIFF="IF_SAFER",
        )

        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(stacked)

            # Set band descriptions
            for i, rp in enumerate(RETURN_PERIODS, 1):
                dst.set_band_description(i, rp)

            # Build overviews for COG (power of 2)
            dst.build_overviews([2, 4, 8, 16, 32], Resampling.nearest)
            dst.update_tags(ns='rio_overview', resampling='nearest')

        logger.info(f"   📦 COG created: {output_path}")

        # Get output file size
        output_size = output_path.stat().st_size
        output_size_mb = output_size / (1024 * 1024)
        logger.info(f"   📏 Output size: {output_size_mb:.1f} MB")

        # Upload to silver container
        output_blob = f"{output_prefix}/{region_code}/{output_name}.tif"
        with open(output_path, "rb") as f:
            blob_repo.write_blob(output_container, output_blob, f.read())

        logger.info(f"   ☁️ Uploaded to: {output_container}/{output_blob}")

        # Get bounds for STAC
        with rasterio.open(output_path) as src:
            bounds = src.bounds

    return {
        "success": True,
        "result": {
            "output_blob": output_blob,
            "output_container": output_container,
            "output_name": output_name,
            "flood_type": merge_group["flood_type"],
            "defense": merge_group["defense"],
            "year": merge_group["year"],
            "ssp": merge_group.get("ssp"),
            "tile_count": merge_group["tile_count"],
            "file_count": merge_group["file_count"],
            "output_size_mb": output_size_mb,
            "bands": RETURN_PERIODS,
            "bounds": {
                "west": bounds.left,
                "south": bounds.bottom,
                "east": bounds.right,
                "north": bounds.top
            }
        }
    }


def fathom_stac_register(params: dict, context: dict = None) -> dict:
    """
    Create STAC collection and items for consolidated Fathom COGs.

    Creates:
    1. fathom-flood-{region} collection (if not exists)
    2. One STAC item per COG with band metadata

    Args:
        params: Task parameters
            - cog_results: List of successful COG outputs from Stage 2
            - region_code: ISO country code
            - collection_id: Base collection ID
            - output_container: Container with COGs

    Returns:
        dict with collection and item creation summary
    """
    from datetime import datetime, timezone
    from infrastructure.stac import STACRepository
    from config import get_config

    logger = LoggerFactory.create_logger(
        ComponentType.SERVICE,
        "fathom_stac_register"
    )

    cog_results = params.get("cog_results", [])
    region_code = params["region_code"].lower()
    collection_id = params.get("collection_id", "fathom-flood")
    output_container = params.get("output_container", "silver-cogs")
    dry_run = params.get("dry_run", False)

    if dry_run:
        logger.info("🔍 DRY RUN - STAC registration skipped")
        return {
            "success": True,
            "result": {
                "dry_run": True,
                "collection_id": f"{collection_id}-{region_code}",
                "items_created": 0
            }
        }

    logger.info(f"📚 Registering {len(cog_results)} STAC items for region: {region_code}")

    config = get_config()
    stac_repo = STACRepository()

    # Create collection ID with region suffix
    full_collection_id = f"{collection_id}-{region_code}"

    # Check if collection exists, create if not
    try:
        existing = stac_repo.get_collection(full_collection_id)
        logger.info(f"   Using existing collection: {full_collection_id}")
    except Exception:
        # Create collection
        logger.info(f"   Creating collection: {full_collection_id}")

        # Calculate collection bounds from all COGs
        all_bounds = [r["bounds"] for r in cog_results if "bounds" in r]
        if all_bounds:
            collection_bounds = [
                min(b["west"] for b in all_bounds),
                min(b["south"] for b in all_bounds),
                max(b["east"] for b in all_bounds),
                max(b["north"] for b in all_bounds)
            ]
        else:
            collection_bounds = [-180, -90, 180, 90]

        collection = {
            "type": "Collection",
            "stac_version": "1.0.0",
            "id": full_collection_id,
            "title": f"Fathom Global Flood Hazard Maps - {region_code.upper()}",
            "description": (
                f"Consolidated flood hazard data for {region_code.upper()} from Fathom Global v3. "
                "Multi-band COGs with return periods (1in5 to 1in1000) as bands. "
                "Flood depth values in centimeters."
            ),
            "license": "proprietary",
            "extent": {
                "spatial": {"bbox": [collection_bounds]},
                "temporal": {"interval": [["2020-01-01T00:00:00Z", "2080-12-31T23:59:59Z"]]}
            },
            "summaries": {
                "fathom:flood_type": ["coastal", "fluvial", "pluvial"],
                "fathom:defense_status": ["defended", "undefended"],
                "fathom:year": [2020, 2030, 2050, 2080],
                "fathom:ssp_scenario": ["ssp126", "ssp245", "ssp370", "ssp585"]
            },
            "links": [],
            "keywords": ["flood", "hazard", "fathom", "climate", region_code]
        }

        stac_repo.create_collection(collection)
        logger.info(f"   ✅ Collection created: {full_collection_id}")

    # Create STAC items for each COG
    items_created = 0
    storage_base = f"https://{config.storage_account_name}.blob.core.windows.net/{output_container}"

    for cog_result in cog_results:
        output_blob = cog_result["output_blob"]
        output_name = cog_result["output_name"]

        # Build STAC item
        item_id = output_name

        # Generate datetime based on year
        year = cog_result["year"]
        item_datetime = f"{year}-01-01T00:00:00Z"

        # Build asset URL
        asset_href = f"{storage_base}/{output_blob}"

        bounds = cog_result["bounds"]
        bbox = [bounds["west"], bounds["south"], bounds["east"], bounds["north"]]

        # Build geometry from bounds
        geometry = {
            "type": "Polygon",
            "coordinates": [[
                [bounds["west"], bounds["south"]],
                [bounds["east"], bounds["south"]],
                [bounds["east"], bounds["north"]],
                [bounds["west"], bounds["north"]],
                [bounds["west"], bounds["south"]]
            ]]
        }

        # Build band metadata
        eo_bands = []
        for i, rp in enumerate(RETURN_PERIODS):
            eo_bands.append({
                "name": rp,
                "description": f"Flood depth for {rp.replace('in', '-in-')} year return period (cm)"
            })

        item = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "stac_extensions": [
                "https://stac-extensions.github.io/eo/v1.0.0/schema.json",
                "https://stac-extensions.github.io/raster/v1.1.0/schema.json"
            ],
            "id": item_id,
            "collection": full_collection_id,
            "geometry": geometry,
            "bbox": bbox,
            "properties": {
                "datetime": item_datetime,
                "fathom:flood_type": cog_result["flood_type"],
                "fathom:defense_status": cog_result["defense"],
                "fathom:year": year,
                "fathom:ssp_scenario": cog_result.get("ssp"),
                "fathom:depth_unit": "cm",
                "fathom:source_tiles": cog_result["tile_count"],
                "fathom:source_files": cog_result["file_count"],
                "eo:bands": eo_bands
            },
            "assets": {
                "data": {
                    "href": asset_href,
                    "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                    "title": f"Flood depth COG ({cog_result['flood_type']} {cog_result['defense']})",
                    "roles": ["data"],
                    "raster:bands": [
                        {
                            "data_type": "int16",
                            "nodata": -32768,
                            "unit": "cm",
                            "description": f"Flood depth for {rp} return period"
                        }
                        for rp in RETURN_PERIODS
                    ]
                }
            },
            "links": [
                {
                    "rel": "collection",
                    "href": f"./collection.json",
                    "type": "application/json"
                }
            ]
        }

        # Insert item
        try:
            stac_repo.create_item(full_collection_id, item)
            items_created += 1
            logger.info(f"   ✅ Item created: {item_id}")
        except Exception as e:
            logger.warning(f"   ⚠️ Failed to create item {item_id}: {e}")

    logger.info(f"✅ STAC registration complete: {items_created} items in {full_collection_id}")

    return {
        "success": True,
        "result": {
            "collection_id": full_collection_id,
            "items_created": items_created,
            "stac_catalog_url": f"{config.base_url}/api/stac/collections/{full_collection_id}"
        }
    }
