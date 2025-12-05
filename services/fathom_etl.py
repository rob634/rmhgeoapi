# ============================================================================
# CLAUDE CONTEXT - SERVICE - FATHOM ETL HANDLERS
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Service - Task handlers for Fathom flood hazard ETL pipeline
# PURPOSE: Inventory, merge/stack, and STAC registration for Fathom data
# LAST_REVIEWED: 03 DEC 2025
# EXPORTS: Phase 1 (band stack): fathom_tile_inventory, fathom_band_stack
#          Phase 2 (spatial merge): fathom_grid_inventory, fathom_spatial_merge
#          Shared: fathom_stac_register
#          Legacy: fathom_inventory, fathom_merge_stack (deprecated - too memory intensive)
# INTERFACES: Standard handler contract (params, context) -> dict
# PYDANTIC_MODELS: None
# DEPENDENCIES: pandas, rasterio, GDAL, azure.storage.blob, pgstac
# SOURCE: bronze-fathom container (Fathom Global Flood Maps v3)
# SCOPE: Regional flood hazard data consolidation
# VALIDATION: Handler-level validation, STAC-driven idempotency
# PATTERNS: Handler contract compliance, streaming blob access, STAC idempotency
# ENTRY_POINTS: Registered in services/__init__.py ALL_HANDLERS
# IDEMPOTENCY: Two-tier: STAC query at inventory (skip processed), blob check at processing
# ============================================================================

"""
Fathom ETL Task Handlers - Two-Phase Architecture (03 DEC 2025)

PHASE 1: Band Stacking (process_fathom_stack job)
- fathom_tile_inventory: Group by tile + scenario (not country)
- fathom_band_stack: Stack 8 return periods into multi-band COG (~500MB/task)
- Output: 1M files (8× reduction from 8M source files)

PHASE 2: Spatial Merge (process_fathom_merge job)
- fathom_grid_inventory: Group Phase 1 outputs by NxN grid cell
- fathom_spatial_merge: Merge NxN tiles band-by-band (~2-3GB/task)
- Output: 40K files with 5×5 grid (additional 25× reduction)

Shared:
- fathom_stac_register: STAC collection/item creation (works for both phases)

STAC-DRIVEN IDEMPOTENCY (03 DEC 2025):
- Submit with bbox: Only process tiles within bounding box
- Inventory stage queries STAC catalog for already-processed items
- Tiles/grid cells already in STAC are excluded from processing
- Enables resumable global runs: interrupt → resume → skip completed
- Two-tier idempotency:
  1. STAC query at inventory (skip tiles/grid cells with STAC items)
  2. Blob existence check at processing (fallback for crash recovery)

Usage Examples:
    # Process single region with bbox filter
    curl -X POST .../api/jobs/submit/process_fathom_stack \\
      -d '{"region_code": "CI", "bbox": [-8, 4, -2, 10]}'

    # Resume interrupted global run (skips already-processed tiles)
    curl -X POST .../api/jobs/submit/process_fathom_stack \\
      -d '{"region_code": "CI"}'  # No bbox = process all, STAC skips completed

Legacy (deprecated - too memory intensive for Azure Functions):
- fathom_inventory: Country-wide grouping
- fathom_merge_stack: Country-wide spatial merge + band stack (~12GB/task)

Author: Robert and Geospatial Claude Legion
Date: 03 DEC 2025
"""

import re
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional
from collections import defaultdict

from util_logger import LoggerFactory, ComponentType
from config import FathomDefaults


# Return period band mapping (use FathomDefaults as source of truth)
RETURN_PERIODS = FathomDefaults.RETURN_PERIODS

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
    source_container = params.get("source_container", FathomDefaults.SOURCE_CONTAINER)
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

    Handles full paths from Fathom CSV file lists:
    - SSBN Flood Hazard Maps/Global flood hazard maps v3 2023/{region}/{flood_type}/...

    Supports two path structures after the prefix:
    1. Present-day (no SSP): flood_type/year/return_period/filename.tif
       COASTAL_DEFENDED/2020/1in100/1in100-COASTAL-DEFENDED-2020_n04w006.tif

    2. Future projection (with SSP): flood_type/year/ssp/return_period/filename.tif
       COASTAL_DEFENDED/2030/SSP2_4.5/1in100/1in100-COASTAL-DEFENDED-2030-SSP2_4.5_n05w004.tif

    Returns:
        Parsed metadata dict or None if parsing fails
    """
    try:
        parts = path.split("/")

        # Find the flood type part (starts with known flood type prefix)
        # Skip any leading path components (e.g., "SSBN Flood Hazard Maps/...")
        flood_type_idx = None
        for i, part in enumerate(parts):
            if part in FLOOD_TYPE_MAP:
                flood_type_idx = i
                break

        if flood_type_idx is None:
            return None

        # Re-slice from flood type onwards
        parts = parts[flood_type_idx:]

        if len(parts) < 4:
            return None

        flood_type_raw = parts[0]  # e.g., "COASTAL_DEFENDED"
        year = int(parts[1])  # e.g., 2020 or 2030
        filename = parts[-1]  # e.g., "1in100-COASTAL-DEFENDED-2020_n04w006.tif"

        # Determine path structure based on number of parts
        # 4 parts: flood_type/year/return_period/filename (no SSP)
        # 5 parts: flood_type/year/ssp/return_period/filename (with SSP)
        if len(parts) == 4:
            # Present-day: flood_type/year/return_period/filename
            return_period = parts[2]  # e.g., "1in100"
            ssp_raw = None
        elif len(parts) == 5:
            # Future projection: flood_type/year/ssp/return_period/filename
            ssp_raw = parts[2]  # e.g., "SSP2_4.5"
            return_period = parts[3]  # e.g., "1in100"
        else:
            return None

        # Validate return period format
        if not return_period.startswith("1in"):
            return None

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

        # Build the normalized blob path (from flood_type onwards)
        # This is the actual path in Azure blob storage
        normalized_path = "/".join(parts)

        return {
            "path": normalized_path,  # Normalized path for blob storage
            "original_path": path,    # Original path from CSV (for debugging)
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


def _parse_tile_coordinate(tile: str) -> tuple:
    """
    Parse tile coordinate string to (lat, lon).

    Examples:
        "n04w006" → (4, -6)
        "s10e020" → (-10, 20)
        "n00w001" → (0, -1)

    Returns:
        (lat, lon) tuple as integers
    """
    match = re.match(r"([ns])(\d+)([ew])(\d+)", tile.lower())
    if not match:
        raise ValueError(f"Invalid tile coordinate: {tile}")

    lat_sign = 1 if match.group(1) == 'n' else -1
    lat = int(match.group(2)) * lat_sign

    lon_sign = -1 if match.group(3) == 'w' else 1
    lon = int(match.group(4)) * lon_sign

    return (lat, lon)


def _tile_to_grid_cell(tile: str, grid_size: int) -> str:
    """
    Convert tile coordinate to grid cell ID.

    Grid cells are aligned to grid_size boundaries.
    Example (5×5 grid):
        "n04w006" → "n00-n05_w010-w005" (lat 0-5, lon -10 to -5)
        "n07w008" → "n05-n10_w010-w005" (lat 5-10, lon -10 to -5)

    Args:
        tile: Tile coordinate string (e.g., "n04w006")
        grid_size: Grid cell size in degrees (e.g., 5 for 5×5)

    Returns:
        Grid cell ID string
    """
    lat, lon = _parse_tile_coordinate(tile)

    # Floor to grid boundary
    lat_min = (lat // grid_size) * grid_size
    lat_max = lat_min + grid_size

    lon_min = (lon // grid_size) * grid_size
    lon_max = lon_min + grid_size

    # Format lat part
    lat_min_str = f"n{abs(lat_min):02d}" if lat_min >= 0 else f"s{abs(lat_min):02d}"
    lat_max_str = f"n{abs(lat_max):02d}" if lat_max >= 0 else f"s{abs(lat_max):02d}"

    # Format lon part
    lon_min_str = f"e{abs(lon_min):03d}" if lon_min >= 0 else f"w{abs(lon_min):03d}"
    lon_max_str = f"e{abs(lon_max):03d}" if lon_max >= 0 else f"w{abs(lon_max):03d}"

    return f"{lat_min_str}-{lat_max_str}_{lon_min_str}-{lon_max_str}"


# =============================================================================
# PHASE 1 HANDLERS: Band Stacking (process_fathom_stack job)
# =============================================================================

def fathom_tile_inventory(params: dict, context: dict = None) -> dict:
    """
    Parse Fathom file list and group by TILE + scenario (not country-wide).

    Unlike fathom_inventory which groups all tiles for a scenario together,
    this groups files so each output is a single 1×1 tile with 8 bands.

    STAC-driven idempotency (03 DEC 2025):
    - If collection_id provided, queries STAC for already-processed tiles
    - Filters out tile_groups that already have STAC items
    - Enables resumable global runs: interrupt → resume → skip completed

    Args:
        params: Task parameters
            - region_code: ISO country code (e.g., "CI")
            - source_container: Container with source files
            - file_list_csv: Path to CSV file (optional, auto-detected)
            - flood_types: Filter by flood types (optional)
            - years: Filter by years (optional)
            - ssp_scenarios: Filter by SSP scenarios (optional)
            - bbox: Optional bounding box [west, south, east, north] to filter tiles
            - collection_id: STAC collection ID for idempotency check
            - skip_existing_stac: If True, skip tiles already in STAC (default: True)
            - dry_run: If True, only create inventory

    Returns:
        dict with tile_groups (one per tile+scenario combination)
    """
    import pandas as pd
    from infrastructure import BlobRepository

    logger = LoggerFactory.create_logger(
        ComponentType.SERVICE,
        "fathom_tile_inventory"
    )

    region_code = params["region_code"].upper()
    source_container = params.get("source_container", FathomDefaults.SOURCE_CONTAINER)
    file_list_csv = params.get("file_list_csv")
    filter_flood_types = params.get("flood_types")
    filter_years = params.get("years")
    filter_ssp = params.get("ssp_scenarios")
    bbox = params.get("bbox")  # [west, south, east, north]
    collection_id = params.get("collection_id", FathomDefaults.PHASE1_COLLECTION_ID)
    skip_existing_stac = params.get("skip_existing_stac", True)
    dry_run = params.get("dry_run", False)

    logger.info(f"📋 Starting Fathom TILE inventory for region: {region_code}")
    if bbox:
        logger.info(f"   Spatial filter (bbox): {bbox}")

    # Auto-detect CSV filename if not provided
    blob_repo = BlobRepository.instance()
    if not file_list_csv:
        # Use prefix filter to avoid listing millions of tiles
        # CSV files are named like "CI_Côte_d'Ivoire_file_list.csv"
        csv_blobs = blob_repo.list_blobs(source_container, prefix=f"{region_code}_")
        matching = [b["name"] if isinstance(b, dict) else b for b in csv_blobs
                   if (b["name"] if isinstance(b, dict) else b).endswith('_file_list.csv')]

        if not matching:
            # Fallback: try without prefix in case naming varies (limited search)
            logger.warning(f"No CSV found with prefix {region_code}_, trying root-level search...")
            root_blobs = blob_repo.list_blobs(source_container, limit=1000)
            matching = [b["name"] if isinstance(b, dict) else b for b in root_blobs
                       if (b["name"] if isinstance(b, dict) else b).endswith('_file_list.csv') and
                       (b["name"] if isinstance(b, dict) else b).startswith(f"{region_code}_")]

        if not matching:
            return {
                "success": False,
                "error": f"No file list CSV found for region {region_code}. Expected format: {region_code}_*_file_list.csv"
            }
        file_list_csv = matching[0]

    logger.info(f"   Using file list: {file_list_csv}")

    # Download and parse CSV
    csv_bytes = blob_repo.read_blob(source_container, file_list_csv)

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp.write(csv_bytes)
        tmp_path = tmp.name

    df = pd.read_csv(tmp_path)
    Path(tmp_path).unlink()

    logger.info(f"   Loaded {len(df)} file paths from CSV")

    # Parse file paths
    parsed_files = []
    for path in df.iloc[:, 0]:
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

    # Apply bbox filter if provided
    if bbox:
        def _tile_in_bbox(tile: str, bbox: list) -> bool:
            """Check if tile coordinate falls within bbox."""
            try:
                lat, lon = _parse_tile_coordinate(tile)
                # Tile is 1x1 degree, check if tile origin is within bbox
                # bbox = [west, south, east, north]
                return (bbox[0] <= lon <= bbox[2]) and (bbox[1] <= lat <= bbox[3])
            except ValueError:
                return False

        before_count = len(parsed_files)
        parsed_files = [f for f in parsed_files if _tile_in_bbox(f["tile"], bbox)]
        logger.info(f"   After bbox filter: {len(parsed_files)} files (was {before_count})")

    # Group by TILE + flood_type + year + ssp (not just flood_type + year + ssp)
    groups = defaultdict(lambda: {
        "tile": None,
        "flood_type_raw": None,
        "flood_type": None,
        "defense": None,
        "year": None,
        "ssp_raw": None,
        "ssp": None,
        "return_period_files": {}  # return_period → file_path (single file per RP)
    })

    for f in parsed_files:
        # Group key includes tile coordinate
        key = (f["tile"], f["flood_type_raw"], f["year"], f["ssp_raw"])
        group = groups[key]

        group["tile"] = f["tile"]
        group["flood_type_raw"] = f["flood_type_raw"]
        group["flood_type"] = f["flood_type"]
        group["defense"] = f["defense"]
        group["year"] = f["year"]
        group["ssp_raw"] = f["ssp_raw"]
        group["ssp"] = f["ssp"]
        # Each tile has exactly one file per return period
        group["return_period_files"][f["return_period"]] = f["path"]

    # Convert to output format
    tile_groups = []
    for key, group in groups.items():
        tile = group["tile"]
        flood_type_slug = f"{group['flood_type']}-{group['defense']}"
        year = group["year"]

        if group["ssp"]:
            output_name = f"{tile}_{flood_type_slug}_{year}_{group['ssp']}"
        else:
            output_name = f"{tile}_{flood_type_slug}_{year}"

        # Check for missing return periods
        rp_files = group["return_period_files"]
        missing_rps = [rp for rp in RETURN_PERIODS if rp not in rp_files]

        if missing_rps:
            logger.warning(f"   ⚠️ {output_name}: Missing return periods: {missing_rps}")

        tile_groups.append({
            "output_name": output_name,
            "tile": tile,
            "flood_type_raw": group["flood_type_raw"],
            "flood_type": group["flood_type"],
            "defense": group["defense"],
            "year": group["year"],
            "ssp_raw": group["ssp_raw"],
            "ssp": group["ssp"],
            "return_period_files": rp_files,
            "file_count": len(rp_files)
        })

    # Sort for consistent ordering
    tile_groups.sort(key=lambda x: x["output_name"])

    # =========================================================================
    # STAC-DRIVEN IDEMPOTENCY (03 DEC 2025)
    # Query existing STAC items and filter out already-processed tile groups
    # =========================================================================
    skipped_count = 0
    full_collection_id = f"{collection_id}-{region_code.lower()}"

    if skip_existing_stac and not dry_run:
        try:
            from infrastructure.pgstac_bootstrap import PgStacBootstrap

            stac = PgStacBootstrap()
            existing_item_ids = stac.get_existing_item_ids(
                collection_id=full_collection_id,
                bbox=bbox  # Use same bbox filter for STAC query
            )

            if existing_item_ids:
                before_count = len(tile_groups)
                tile_groups = [
                    g for g in tile_groups
                    if g["output_name"] not in existing_item_ids
                ]
                skipped_count = before_count - len(tile_groups)
                logger.info(
                    f"   🔄 STAC idempotency: {skipped_count} tile groups already in STAC, "
                    f"{len(tile_groups)} remaining to process"
                )
        except Exception as e:
            logger.warning(f"   ⚠️ STAC idempotency check failed (will process all): {e}")

    # Summary statistics
    unique_tiles = len(set(g["tile"] for g in tile_groups))
    all_flood_types = sorted(set(g["flood_type_raw"] for g in tile_groups)) if tile_groups else []
    all_years = sorted(set(g["year"] for g in tile_groups)) if tile_groups else []
    total_files = sum(g["file_count"] for g in tile_groups)

    logger.info(f"✅ Tile inventory complete:")
    logger.info(f"   Total source files: {total_files}")
    logger.info(f"   Unique tiles: {unique_tiles}")
    logger.info(f"   Tile groups (output COGs): {len(tile_groups)}")
    if skipped_count > 0:
        logger.info(f"   Skipped (already in STAC): {skipped_count}")
    logger.info(f"   Flood types: {all_flood_types}")
    logger.info(f"   Years: {all_years}")

    if dry_run:
        logger.info("   🔍 DRY RUN - no files will be processed")

    return {
        "success": True,
        "result": {
            "region_code": region_code,
            "total_files": total_files,
            "unique_tiles": unique_tiles,
            "tile_group_count": len(tile_groups),
            "tile_groups": tile_groups,
            "flood_types": all_flood_types,
            "years": all_years,
            "dry_run": dry_run,
            "skipped_existing_stac": skipped_count,
            "stac_collection": full_collection_id,
            "bbox": bbox
        }
    }


def fathom_band_stack(params: dict, context: dict = None) -> dict:
    """
    Stack 8 return period files into a single multi-band COG (no spatial merge).

    This is much simpler and memory-efficient than fathom_merge_stack:
    - Downloads 8 files (~50KB each = 400KB total)
    - Stacks into single 8-band COG (~400KB output)
    - Peak memory: ~500MB (vs 12GB for country-wide merge)

    Args:
        params: Task parameters
            - tile_group: Group definition from tile inventory
            - source_container: Container with source tiles
            - output_container: Container for output COG
            - output_prefix: Folder prefix in output container
            - region_code: ISO country code
            - force_reprocess: Skip idempotency check if True

    Returns:
        dict with output blob path and metadata
    """
    import rasterio
    from rasterio.enums import Resampling
    import numpy as np
    from infrastructure import BlobRepository
    from config import get_config

    logger = LoggerFactory.create_logger(
        ComponentType.SERVICE,
        "fathom_band_stack"
    )

    tile_group = params["tile_group"]
    source_container = params.get("source_container", FathomDefaults.SOURCE_CONTAINER)
    output_container = params.get("output_container", FathomDefaults.PHASE1_OUTPUT_CONTAINER)
    output_prefix = params.get("output_prefix", FathomDefaults.PHASE1_OUTPUT_PREFIX)
    region_code = params["region_code"].lower()
    force_reprocess = params.get("force_reprocess", False)

    tile = tile_group["tile"]
    output_name = tile_group["output_name"]
    logger.info(f"🔧 Band stacking tile: {output_name}")

    config = get_config()
    blob_repo = BlobRepository.instance()

    # Output path: fathom-stacked/{region}/{tile}/{scenario}.tif
    output_blob_path = f"{output_prefix}/{region_code}/{tile}/{output_name}.tif"

    # Idempotency check
    if not force_reprocess and blob_repo.blob_exists(output_container, output_blob_path):
        logger.info(f"⏭️ SKIP: Output already exists: {output_container}/{output_blob_path}")
        return {
            "success": True,
            "skipped": True,
            "result": {
                "output_blob": output_blob_path,
                "output_container": output_container,
                "output_name": output_name,
                "tile": tile,
                "flood_type": tile_group["flood_type"],
                "defense": tile_group["defense"],
                "year": tile_group["year"],
                "ssp": tile_group.get("ssp"),
                "message": "Output COG already exists - skipped processing"
            }
        }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Download and stack each return period
        bands = []
        profile = None
        transform = None
        crs = None

        for rp_idx, return_period in enumerate(RETURN_PERIODS):
            rp_path = tile_group["return_period_files"].get(return_period)

            if not rp_path:
                logger.warning(f"   ⚠️ Missing return period: {return_period}")
                # Create nodata band
                if bands:
                    empty = np.full_like(bands[0], -32768, dtype=np.int16)
                    bands.append(empty)
                continue

            # Download single file
            local_path = tmpdir / f"{return_period}.tif"
            blob_bytes = blob_repo.read_blob(source_container, rp_path)
            with open(local_path, "wb") as f:
                f.write(blob_bytes)

            # Read raster data
            with rasterio.open(local_path) as src:
                data = src.read(1)  # Single band
                bands.append(data)

                if profile is None:
                    profile = src.profile.copy()
                    transform = src.transform
                    crs = src.crs
                    bounds = src.bounds

            # Clean up
            local_path.unlink()

        if not bands:
            return {
                "success": False,
                "error": f"No data found for tile {tile}"
            }

        # Stack all bands
        stacked = np.stack(bands, axis=0)
        logger.info(f"   📦 Stacked shape: {stacked.shape}")

        # Write multi-band COG
        output_path = tmpdir / f"{output_name}.tif"

        profile.update(
            driver="GTiff",
            count=len(RETURN_PERIODS),
            dtype=np.int16,
            compress="DEFLATE",
            predictor=2,
            tiled=True,
            blockxsize=512,
            blockysize=512,
            nodata=-32768
        )

        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(stacked)

            for i, rp in enumerate(RETURN_PERIODS, 1):
                dst.set_band_description(i, rp)

            # Build overviews (fewer levels for small tiles)
            dst.build_overviews([2, 4], Resampling.nearest)
            dst.update_tags(ns='rio_overview', resampling='nearest')

        # Get output size
        output_size = output_path.stat().st_size
        output_size_kb = output_size / 1024
        logger.info(f"   📏 Output size: {output_size_kb:.1f} KB")

        # Upload
        with open(output_path, "rb") as f:
            blob_repo.write_blob(output_container, output_blob_path, f.read())

        logger.info(f"   ☁️ Uploaded: {output_container}/{output_blob_path}")

    return {
        "success": True,
        "result": {
            "output_blob": output_blob_path,
            "output_container": output_container,
            "output_name": output_name,
            "tile": tile,
            "flood_type": tile_group["flood_type"],
            "defense": tile_group["defense"],
            "year": tile_group["year"],
            "ssp": tile_group.get("ssp"),
            "file_count": tile_group["file_count"],
            "output_size_kb": output_size_kb,
            "bands": RETURN_PERIODS,
            "bounds": {
                "west": bounds.left,
                "south": bounds.bottom,
                "east": bounds.right,
                "north": bounds.top
            }
        }
    }


# =============================================================================
# PHASE 2 HANDLERS: Spatial Merge (process_fathom_merge job)
# =============================================================================

def fathom_grid_inventory(params: dict, context: dict = None) -> dict:
    """
    List Phase 1 outputs and group by NxN grid cell.

    Reads the stacked COGs from Phase 1 and groups them into grid cells
    for spatial merging.

    STAC-driven idempotency (03 DEC 2025):
    - If collection_id provided, queries STAC for already-processed grid cells
    - Filters out grid_groups that already have STAC items
    - Enables resumable global runs: interrupt → resume → skip completed

    Args:
        params: Task parameters
            - region_code: ISO country code
            - grid_size: Grid cell size in degrees (default: 5)
            - source_container: Container with Phase 1 outputs
            - source_prefix: Folder prefix for Phase 1 outputs
            - bbox: Optional bounding box [west, south, east, north] to filter
            - collection_id: STAC collection ID for idempotency check
            - skip_existing_stac: If True, skip grid cells already in STAC (default: True)

    Returns:
        dict with grid_groups (one per grid cell + scenario)
    """
    from infrastructure import BlobRepository

    logger = LoggerFactory.create_logger(
        ComponentType.SERVICE,
        "fathom_grid_inventory"
    )

    region_code = params["region_code"].lower()
    grid_size = params.get("grid_size", FathomDefaults.DEFAULT_GRID_SIZE)
    source_container = params.get("source_container", FathomDefaults.PHASE1_OUTPUT_CONTAINER)
    source_prefix = params.get("source_prefix", FathomDefaults.PHASE1_OUTPUT_PREFIX)
    bbox = params.get("bbox")  # [west, south, east, north]
    collection_id = params.get("collection_id", FathomDefaults.PHASE2_COLLECTION_ID)
    skip_existing_stac = params.get("skip_existing_stac", True)

    logger.info(f"📋 Starting grid inventory for region: {region_code}")
    logger.info(f"   Grid size: {grid_size}×{grid_size} degrees")
    if bbox:
        logger.info(f"   Spatial filter (bbox): {bbox}")

    blob_repo = BlobRepository.instance()

    # List all stacked COGs for this region
    prefix = f"{source_prefix}/{region_code}/"
    all_blobs = blob_repo.list_blobs(source_container, prefix=prefix)
    cog_blobs = [b for b in all_blobs if b.endswith('.tif')]

    logger.info(f"   Found {len(cog_blobs)} stacked COGs")

    if not cog_blobs:
        return {
            "success": False,
            "error": f"No stacked COGs found at {source_container}/{prefix}"
        }

    # Parse blob paths to extract tile and scenario info
    # Path format: fathom-stacked/{region}/{tile}/{scenario}.tif
    groups = defaultdict(lambda: {
        "grid_cell": None,
        "flood_type": None,
        "defense": None,
        "year": None,
        "ssp": None,
        "tiles": []  # List of (tile, blob_path) tuples
    })

    for blob_path in cog_blobs:
        # Parse: fathom-stacked/ci/n04w006/n04w006_coastal-defended_2020.tif
        parts = blob_path.split("/")
        if len(parts) < 4:
            continue

        tile = parts[2]  # e.g., "n04w006"
        filename = parts[3]  # e.g., "n04w006_coastal-defended_2020.tif"

        # Parse filename: {tile}_{flood_type}-{defense}_{year}[_{ssp}].tif
        name_parts = filename.replace(".tif", "").split("_")
        if len(name_parts) < 3:
            continue

        # tile = name_parts[0]  # Already have from path
        flood_defense = name_parts[1]  # e.g., "coastal-defended"
        year = int(name_parts[2])  # e.g., 2020
        ssp = name_parts[3] if len(name_parts) > 3 else None  # e.g., "ssp245"

        flood_type, defense = flood_defense.split("-") if "-" in flood_defense else (flood_defense, "unknown")

        # Calculate grid cell
        grid_cell = _tile_to_grid_cell(tile, grid_size)

        # Group key: grid_cell + scenario
        key = (grid_cell, flood_type, defense, year, ssp)
        group = groups[key]

        group["grid_cell"] = grid_cell
        group["flood_type"] = flood_type
        group["defense"] = defense
        group["year"] = year
        group["ssp"] = ssp
        group["tiles"].append({
            "tile": tile,
            "blob_path": blob_path
        })

    # Convert to output format
    grid_groups = []
    for key, group in groups.items():
        grid_cell = group["grid_cell"]
        flood_type_slug = f"{group['flood_type']}-{group['defense']}"
        year = group["year"]

        if group["ssp"]:
            output_name = f"{grid_cell}_{flood_type_slug}_{year}_{group['ssp']}"
        else:
            output_name = f"{grid_cell}_{flood_type_slug}_{year}"

        grid_groups.append({
            "output_name": output_name,
            "grid_cell": grid_cell,
            "flood_type": group["flood_type"],
            "defense": group["defense"],
            "year": group["year"],
            "ssp": group["ssp"],
            "tiles": group["tiles"],
            "tile_count": len(group["tiles"])
        })

    # Sort for consistent ordering
    grid_groups.sort(key=lambda x: x["output_name"])

    # Apply bbox filter if provided (filter grid cells by their center point)
    if bbox:
        def _grid_cell_in_bbox(grid_cell: str, bbox: list) -> bool:
            """Check if grid cell overlaps with bbox."""
            # Parse grid cell: "n00-n05_w010-w005"
            try:
                import re
                match = re.match(r"([ns])(\d+)-([ns])(\d+)_([ew])(\d+)-([ew])(\d+)", grid_cell)
                if not match:
                    return True  # Can't parse, include it

                lat_min_sign = 1 if match.group(1) == 'n' else -1
                lat_min = int(match.group(2)) * lat_min_sign
                lat_max_sign = 1 if match.group(3) == 'n' else -1
                lat_max = int(match.group(4)) * lat_max_sign

                lon_min_sign = -1 if match.group(5) == 'w' else 1
                lon_min = int(match.group(6)) * lon_min_sign
                lon_max_sign = -1 if match.group(7) == 'w' else 1
                lon_max = int(match.group(8)) * lon_max_sign

                # Check if grid cell bbox overlaps with filter bbox
                # bbox = [west, south, east, north]
                return not (
                    lon_max < bbox[0] or  # Grid is west of bbox
                    lon_min > bbox[2] or  # Grid is east of bbox
                    lat_max < bbox[1] or  # Grid is south of bbox
                    lat_min > bbox[3]     # Grid is north of bbox
                )
            except Exception:
                return True  # On error, include it

        before_count = len(grid_groups)
        grid_groups = [g for g in grid_groups if _grid_cell_in_bbox(g["grid_cell"], bbox)]
        logger.info(f"   After bbox filter: {len(grid_groups)} grid groups (was {before_count})")

    # =========================================================================
    # STAC-DRIVEN IDEMPOTENCY (03 DEC 2025)
    # Query existing STAC items and filter out already-processed grid groups
    # =========================================================================
    skipped_count = 0
    full_collection_id = f"{collection_id}-{region_code}"

    if skip_existing_stac and grid_groups:
        try:
            from infrastructure.pgstac_bootstrap import PgStacBootstrap

            stac = PgStacBootstrap()
            existing_item_ids = stac.get_existing_item_ids(
                collection_id=full_collection_id,
                bbox=bbox  # Use same bbox filter for STAC query
            )

            if existing_item_ids:
                before_count = len(grid_groups)
                grid_groups = [
                    g for g in grid_groups
                    if g["output_name"] not in existing_item_ids
                ]
                skipped_count = before_count - len(grid_groups)
                logger.info(
                    f"   🔄 STAC idempotency: {skipped_count} grid groups already in STAC, "
                    f"{len(grid_groups)} remaining to process"
                )
        except Exception as e:
            logger.warning(f"   ⚠️ STAC idempotency check failed (will process all): {e}")

    unique_grid_cells = len(set(g["grid_cell"] for g in grid_groups)) if grid_groups else 0
    total_tiles = sum(g["tile_count"] for g in grid_groups)

    logger.info(f"✅ Grid inventory complete:")
    logger.info(f"   Unique grid cells: {unique_grid_cells}")
    logger.info(f"   Grid groups (output COGs): {len(grid_groups)}")
    if skipped_count > 0:
        logger.info(f"   Skipped (already in STAC): {skipped_count}")
    logger.info(f"   Total source tiles: {total_tiles}")

    return {
        "success": True,
        "result": {
            "region_code": region_code,
            "grid_size": grid_size,
            "unique_grid_cells": unique_grid_cells,
            "grid_group_count": len(grid_groups),
            "grid_groups": grid_groups,
            "total_tiles": total_tiles,
            "skipped_existing_stac": skipped_count,
            "stac_collection": full_collection_id,
            "bbox": bbox
        }
    }


def fathom_spatial_merge(params: dict, context: dict = None) -> dict:
    """
    Merge NxN tiles into single COG, processing band-by-band for memory efficiency.

    Memory-efficient approach:
    - Process each band separately (~650MB per band)
    - Stack at the end (~1.3GB)
    - Total peak: ~2-3GB (vs 12GB for all-at-once)

    Args:
        params: Task parameters
            - grid_group: Group definition from grid inventory
            - source_container: Container with stacked COGs
            - output_container: Container for merged output
            - output_prefix: Folder prefix in output container
            - region_code: ISO country code
            - force_reprocess: Skip idempotency check if True

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
        "fathom_spatial_merge"
    )

    grid_group = params["grid_group"]
    source_container = params.get("source_container", FathomDefaults.PHASE1_OUTPUT_CONTAINER)
    output_container = params.get("output_container", FathomDefaults.PHASE2_OUTPUT_CONTAINER)
    output_prefix = params.get("output_prefix", FathomDefaults.PHASE2_OUTPUT_PREFIX)
    region_code = params["region_code"].lower()
    force_reprocess = params.get("force_reprocess", False)

    grid_cell = grid_group["grid_cell"]
    output_name = grid_group["output_name"]
    tiles = grid_group["tiles"]

    logger.info(f"🔧 Spatial merge for grid cell: {grid_cell}")
    logger.info(f"   Tiles to merge: {len(tiles)}")

    config = get_config()
    blob_repo = BlobRepository.instance()

    # Output path
    output_blob_path = f"{output_prefix}/{region_code}/{grid_cell}/{output_name}.tif"

    # Idempotency check
    if not force_reprocess and blob_repo.blob_exists(output_container, output_blob_path):
        logger.info(f"⏭️ SKIP: Output already exists: {output_container}/{output_blob_path}")
        return {
            "success": True,
            "skipped": True,
            "result": {
                "output_blob": output_blob_path,
                "output_container": output_container,
                "output_name": output_name,
                "grid_cell": grid_cell,
                "flood_type": grid_group["flood_type"],
                "defense": grid_group["defense"],
                "year": grid_group["year"],
                "ssp": grid_group.get("ssp"),
                "tile_count": len(tiles),
                "message": "Output COG already exists - skipped processing"
            }
        }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Download all source tiles
        logger.info(f"   📥 Downloading {len(tiles)} tiles...")
        local_tiles = []
        for tile_info in tiles:
            blob_path = tile_info["blob_path"]
            local_path = tmpdir / f"{tile_info['tile']}.tif"
            blob_bytes = blob_repo.read_blob(source_container, blob_path)
            with open(local_path, "wb") as f:
                f.write(blob_bytes)
            local_tiles.append(str(local_path))

        # Process band-by-band to limit memory
        merged_bands = []
        merged_transform = None
        crs = None
        profile = None

        for band_idx in range(len(RETURN_PERIODS)):
            band_num = band_idx + 1  # rasterio is 1-indexed
            logger.info(f"   🔄 Merging band {band_num}: {RETURN_PERIODS[band_idx]}")

            # Open all tiles, read only this band
            datasets = []
            for local_path in local_tiles:
                # Open in read mode, we'll extract just one band
                ds = rasterio.open(local_path)
                datasets.append(ds)

            if crs is None:
                crs = datasets[0].crs
                profile = datasets[0].profile.copy()

            # Create single-band views for merge
            # rasterio.merge expects full datasets, so we need to read band data
            band_data_list = []
            transforms = []
            for ds in datasets:
                band_data_list.append(ds.read(band_num))
                transforms.append(ds.transform)

            # Use merge with the band data
            # Actually, rasterio.merge works on datasets, so we merge full and extract
            merged_data, merged_transform = merge(
                datasets,
                indexes=[band_num],  # Only merge this band
                resampling=Resampling.nearest,
                nodata=-32768
            )

            merged_bands.append(merged_data[0])  # Remove band dimension

            # Close datasets to free memory
            for ds in datasets:
                ds.close()

        # Stack all merged bands
        stacked = np.stack(merged_bands, axis=0)
        logger.info(f"   📦 Merged shape: {stacked.shape}")

        # Write output COG
        output_path = tmpdir / f"{output_name}.tif"

        profile.update(
            driver="GTiff",
            count=len(RETURN_PERIODS),
            dtype=np.int16,
            crs=crs,
            transform=merged_transform,
            width=stacked.shape[2],
            height=stacked.shape[1],
            compress="DEFLATE",
            predictor=2,
            tiled=True,
            blockxsize=512,
            blockysize=512,
            nodata=-32768,
            BIGTIFF="IF_SAFER"
        )

        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(stacked)

            for i, rp in enumerate(RETURN_PERIODS, 1):
                dst.set_band_description(i, rp)

            # Build overviews
            dst.build_overviews([2, 4, 8, 16], Resampling.nearest)
            dst.update_tags(ns='rio_overview', resampling='nearest')

        # Get output size
        output_size = output_path.stat().st_size
        output_size_mb = output_size / (1024 * 1024)
        logger.info(f"   📏 Output size: {output_size_mb:.1f} MB")

        # Get bounds
        with rasterio.open(output_path) as src:
            bounds = src.bounds

        # Upload
        with open(output_path, "rb") as f:
            blob_repo.write_blob(output_container, output_blob_path, f.read())

        logger.info(f"   ☁️ Uploaded: {output_container}/{output_blob_path}")

    return {
        "success": True,
        "result": {
            "output_blob": output_blob_path,
            "output_container": output_container,
            "output_name": output_name,
            "grid_cell": grid_cell,
            "flood_type": grid_group["flood_type"],
            "defense": grid_group["defense"],
            "year": grid_group["year"],
            "ssp": grid_group.get("ssp"),
            "tile_count": len(tiles),
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


# =============================================================================
# LEGACY HANDLERS (deprecated - too memory intensive)
# =============================================================================

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
    source_container = params.get("source_container", FathomDefaults.SOURCE_CONTAINER)
    output_container = params.get("output_container", FathomDefaults.PHASE2_OUTPUT_CONTAINER)
    output_prefix = params.get("output_prefix", FathomDefaults.PHASE2_OUTPUT_PREFIX)
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
    collection_id = params.get("collection_id", FathomDefaults.PHASE2_COLLECTION_ID)
    output_container = params.get("output_container", FathomDefaults.PHASE2_OUTPUT_CONTAINER)
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
