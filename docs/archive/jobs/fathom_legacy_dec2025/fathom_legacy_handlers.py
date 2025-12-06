# ============================================================================
# ARCHIVED - LEGACY FATHOM ETL HANDLERS
# ============================================================================
# ARCHIVED: 05 DEC 2025
# REASON: Too memory intensive (~12GB/task) for Azure Functions
# REPLACED BY: Two-phase architecture (process_fathom_stack + process_fathom_merge)
#   - Phase 1 (fathom_band_stack): ~500MB/task
#   - Phase 2 (fathom_spatial_merge): ~2-3GB/task
# SEE: services/fathom_etl.py for active handlers
# ============================================================================

"""
ARCHIVED: Legacy Fathom ETL Handlers

These handlers were deprecated on 03 DEC 2025 due to memory issues:
- fathom_inventory: Country-wide grouping (used by process_fathom job)
- fathom_merge_stack: Country-wide spatial merge + band stack (~12GB/task)

The two-phase architecture that replaced these:
- Phase 1: fathom_tile_inventory + fathom_band_stack (~500MB/task)
- Phase 2: fathom_grid_inventory + fathom_spatial_merge (~2-3GB/task)

DO NOT USE THESE HANDLERS - ARCHIVED FOR REFERENCE ONLY
"""

import re
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional
from collections import defaultdict

# Note: These imports would fail if run - this is archived code for reference only
# from util_logger import LoggerFactory, ComponentType
# from config import FathomDefaults
# from infrastructure import BlobRepository

# Return period band mapping
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
    DEPRECATED: Parse Fathom file list CSV and create merge groups.

    Groups files by: flood_type + year + ssp_scenario
    Each group will be merged spatially with return periods as bands.

    REPLACED BY: fathom_tile_inventory (Phase 1) which groups by tile+scenario
    instead of country-wide, enabling much smaller memory footprint.

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
    raise DeprecationWarning(
        "fathom_inventory is deprecated. Use fathom_tile_inventory instead. "
        "See process_fathom_stack job for the new two-phase architecture."
    )


def fathom_merge_stack(params: dict, context: dict = None) -> dict:
    """
    DEPRECATED: Merge tiles spatially and stack return periods as bands.

    For each merge group:
    1. Download all source tiles (organized by return period)
    2. For each return period: build VRT for spatial merge
    3. Stack 8 VRTs as bands into single multi-band COG
    4. Upload to silver-cogs container

    REPLACED BY: Two-phase architecture
    - Phase 1 (fathom_band_stack): Stack 8 RPs into multi-band COG (~500MB/task)
    - Phase 2 (fathom_spatial_merge): Merge NxN tiles band-by-band (~2-3GB/task)

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
    raise DeprecationWarning(
        "fathom_merge_stack is deprecated. Use fathom_band_stack (Phase 1) + "
        "fathom_spatial_merge (Phase 2) instead. "
        "See process_fathom_stack and process_fathom_merge jobs."
    )


# ============================================================================
# ARCHIVED HELPER FUNCTION
# ============================================================================
# This was used by fathom_inventory to parse CSV paths
# It's been replaced by _parse_fathom_blob_path in fathom_container_inventory.py
# which parses actual blob paths instead of CSV paths
# ============================================================================

def _parse_fathom_path(path: str) -> Optional[Dict[str, Any]]:
    """
    ARCHIVED: Parse Fathom file path to extract metadata.

    Handles full paths from Fathom CSV file lists:
    - SSBN Flood Hazard Maps/Global flood hazard maps v3 2023/{region}/{flood_type}/...

    Supports two path structures after the prefix:
    1. Present-day (no SSP): flood_type/year/return_period/filename.tif
    2. Future projection (with SSP): flood_type/year/ssp/return_period/filename.tif

    Returns:
        Parsed metadata dict or None if parsing fails
    """
    try:
        parts = path.split("/")

        # Find the flood type part (starts with known flood type prefix)
        flood_type_idx = None
        for i, part in enumerate(parts):
            if part in FLOOD_TYPE_MAP:
                flood_type_idx = i
                break

        if flood_type_idx is None:
            return None

        parts = parts[flood_type_idx:]

        if len(parts) < 4:
            return None

        flood_type_raw = parts[0]
        year = int(parts[1])
        filename = parts[-1]

        if len(parts) == 4:
            return_period = parts[2]
            ssp_raw = None
        elif len(parts) == 5:
            ssp_raw = parts[2]
            return_period = parts[3]
        else:
            return None

        if not return_period.startswith("1in"):
            return None

        tile_match = re.search(r"_([ns]\d+[ew]\d+)\.tif$", filename, re.IGNORECASE)
        if not tile_match:
            return None
        tile = tile_match.group(1).lower()

        ft_info = FLOOD_TYPE_MAP.get(flood_type_raw, {})
        ssp = SSP_MAP.get(ssp_raw) if ssp_raw else None
        normalized_path = "/".join(parts)

        return {
            "path": normalized_path,
            "original_path": path,
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
