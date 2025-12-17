"""
Fathom ETL Task Handlers.

DATABASE-DRIVEN ARCHITECTURE (17 DEC 2025):
All inventory operations query app.etl_fathom table populated by
InventoryFathomContainerJob. Processing state is tracked inline:
- phase1_processed_at: Set by fathom_band_stack after successful COG creation
- phase2_processed_at: Set by fathom_spatial_merge after successful merge

Phase 1 (Band Stacking):
    - fathom_tile_inventory: Query DB for unprocessed tiles
    - fathom_band_stack: Stack 8 return periods into multi-band COG

Phase 2 (Spatial Merge):
    - fathom_grid_inventory: Query DB for Phase 1 completed, Phase 2 pending
    - fathom_spatial_merge: Merge tiles band-by-band

Shared:
    - fathom_stac_register: STAC collection/item creation

Exports:
    fathom_tile_inventory, fathom_band_stack, fathom_grid_inventory,
    fathom_spatial_merge, fathom_stac_register
"""

import re
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional

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


# =============================================================================
# INTERNAL HELPER FUNCTIONS
# =============================================================================

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
    Query app.etl_fathom to create tile_groups for Phase 1 processing.

    DATABASE-DRIVEN (17 DEC 2025):
    - Queries app.etl_fathom table populated by InventoryFathomContainerJob
    - Groups by phase1_group_key (tile + scenario)
    - Filters by phase1_processed_at IS NULL for unprocessed records
    - FAILS FAST if no records exist for region

    Args:
        params: Task parameters
            - region_code: ISO country code (e.g., "CI") - NOT USED, queries all
            - source_container: Container filter (default: bronze-fathom)
            - flood_types: Filter by flood types (optional)
            - years: Filter by years (optional)
            - ssp_scenarios: Filter by SSP scenarios (optional)
            - bbox: Optional bounding box [west, south, east, north] to filter tiles
            - collection_id: STAC collection ID for output naming
            - dry_run: If True, only create inventory

    Returns:
        dict with tile_groups (one per tile+scenario combination)
    """
    from infrastructure.postgresql import PostgreSQLRepository

    logger = LoggerFactory.create_logger(
        ComponentType.SERVICE,
        "fathom_tile_inventory"
    )

    # region_code is informational only - we query all unprocessed records
    region_code = params.get("region_code", "ALL").upper()
    source_container = params.get("source_container", FathomDefaults.SOURCE_CONTAINER)
    filter_flood_types = params.get("flood_types")
    filter_years = params.get("years")
    filter_ssp = params.get("ssp_scenarios")
    bbox = params.get("bbox")  # [west, south, east, north]
    collection_id = params.get("collection_id", FathomDefaults.PHASE1_COLLECTION_ID)
    dry_run = params.get("dry_run", False)

    logger.info(f"📋 Starting Fathom TILE inventory from database")
    logger.info(f"   Source container filter: {source_container}")
    if bbox:
        logger.info(f"   Spatial filter (bbox): {bbox}")

    # Build SQL query with filters
    where_clauses = [
        "phase1_processed_at IS NULL",
        "source_container = %(source_container)s"
    ]
    query_params = {"source_container": source_container}

    if filter_flood_types:
        # Convert raw flood types to normalized (e.g., COASTAL_DEFENDED → coastal, defended)
        flood_type_conditions = []
        for ft_raw in filter_flood_types:
            if ft_raw in FLOOD_TYPE_MAP:
                ft_info = FLOOD_TYPE_MAP[ft_raw]
                flood_type_conditions.append(
                    f"(flood_type = '{ft_info['flood_type']}' AND defense = '{ft_info['defense']}')"
                )
        if flood_type_conditions:
            where_clauses.append(f"({' OR '.join(flood_type_conditions)})")
        logger.info(f"   Filter: flood_types = {filter_flood_types}")

    if filter_years:
        where_clauses.append("year = ANY(%(years)s)")
        query_params["years"] = filter_years
        logger.info(f"   Filter: years = {filter_years}")

    if filter_ssp:
        # Normalize SSP values for query
        normalized_ssp = [SSP_MAP.get(s, s) for s in filter_ssp]
        where_clauses.append("(ssp = ANY(%(ssp)s) OR ssp IS NULL)")
        query_params["ssp"] = normalized_ssp
        logger.info(f"   Filter: ssp_scenarios = {filter_ssp}")

    if bbox:
        # Filter tiles by bbox - tile coordinate must be within bbox
        # We'll filter in Python after query since tile parsing is complex
        pass  # Applied post-query

    where_clause = " AND ".join(where_clauses)

    # Query grouped by phase1_group_key with return_period_files aggregation
    sql = f"""
        SELECT
            phase1_group_key,
            tile,
            flood_type,
            defense,
            year,
            ssp,
            json_object_agg(return_period, source_blob_path ORDER BY return_period) as return_period_files,
            COUNT(*) as file_count
        FROM app.etl_fathom
        WHERE {where_clause}
        GROUP BY phase1_group_key, tile, flood_type, defense, year, ssp
        ORDER BY phase1_group_key
    """

    repo = PostgreSQLRepository()
    with repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, query_params)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]

    logger.info(f"   Query returned {len(rows)} tile groups")

    # FAIL FAST if no records
    if not rows:
        error_msg = (
            f"No unprocessed records found in app.etl_fathom for container '{source_container}'. "
            f"Run inventory_fathom_container job first to populate the table."
        )
        logger.error(f"❌ {error_msg}")
        raise ValueError(error_msg)

    # Convert to tile_groups format
    tile_groups = []
    for row in rows:
        row_dict = dict(zip(columns, row))

        # Apply bbox filter if provided
        if bbox:
            try:
                lat, lon = _parse_tile_coordinate(row_dict["tile"])
                # Check if tile origin is within bbox [west, south, east, north]
                if not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
                    continue
            except ValueError:
                continue

        # Build output_name from phase1_group_key (already in correct format)
        output_name = row_dict["phase1_group_key"]

        # return_period_files is already a dict from json_object_agg
        rp_files = row_dict["return_period_files"]
        if isinstance(rp_files, str):
            import json
            rp_files = json.loads(rp_files)

        # Check for missing return periods
        missing_rps = [rp for rp in RETURN_PERIODS if rp not in rp_files]
        if missing_rps:
            logger.warning(f"   ⚠️ {output_name}: Missing return periods: {missing_rps}")

        # Reconstruct flood_type_raw for backward compatibility
        flood_type = row_dict["flood_type"]
        defense = row_dict["defense"]
        flood_type_raw = f"{flood_type.upper()}_{defense.upper()}"

        tile_groups.append({
            "output_name": output_name,
            "tile": row_dict["tile"],
            "flood_type_raw": flood_type_raw,
            "flood_type": flood_type,
            "defense": defense,
            "year": row_dict["year"],
            "ssp_raw": None,  # Not stored in DB, not needed
            "ssp": row_dict["ssp"],
            "return_period_files": rp_files,
            "file_count": row_dict["file_count"]
        })

    # Summary statistics
    unique_tiles = len(set(g["tile"] for g in tile_groups))
    all_flood_types = sorted(set(g["flood_type_raw"] for g in tile_groups)) if tile_groups else []
    all_years = sorted(set(g["year"] for g in tile_groups)) if tile_groups else []
    total_files = sum(g["file_count"] for g in tile_groups)

    logger.info(f"✅ Tile inventory complete (database-driven):")
    logger.info(f"   Total source files: {total_files}")
    logger.info(f"   Unique tiles: {unique_tiles}")
    logger.info(f"   Tile groups (output COGs): {len(tile_groups)}")
    logger.info(f"   Flood types: {all_flood_types}")
    logger.info(f"   Years: {all_years}")

    if dry_run:
        logger.info("   🔍 DRY RUN - no files will be processed")

    full_collection_id = f"{collection_id}-{region_code.lower()}"

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
            "skipped_existing_stac": 0,  # DB-driven idempotency via phase1_processed_at
            "stac_collection": full_collection_id,
            "bbox": bbox,
            "source": "database"  # Indicate database-driven inventory
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
    job_id = params.get("job_id")  # For tracking in app.etl_fathom

    tile = tile_group["tile"]
    output_name = tile_group["output_name"]
    logger.info(f"🔧 Band stacking tile: {output_name}")

    config = get_config()
    # Bronze zone for reading source tiles, Silver zone for writing output
    bronze_repo = BlobRepository.for_zone("bronze")
    silver_repo = BlobRepository.for_zone("silver")

    # Output path: fathom-stacked/{region}/{tile}/{scenario}.tif
    output_blob_path = f"{output_prefix}/{region_code}/{tile}/{output_name}.tif"

    # Idempotency check (check silver for existing output)
    if not force_reprocess and silver_repo.blob_exists(output_container, output_blob_path):
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

            # Download single file from bronze (source data)
            local_path = tmpdir / f"{return_period}.tif"
            blob_bytes = bronze_repo.read_blob(source_container, rp_path)
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

        # Upload to silver (processed data)
        with open(output_path, "rb") as f:
            silver_repo.write_blob(output_container, output_blob_path, f.read())

        logger.info(f"   ☁️ Uploaded: {output_container}/{output_blob_path}")

    # =========================================================================
    # INLINE STATE UPDATE (17 DEC 2025)
    # Update app.etl_fathom records for this phase1_group_key
    # =========================================================================
    _update_phase1_processed(output_name, output_blob_path, job_id, logger)

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


def _update_phase1_processed(phase1_group_key: str, output_blob: str, job_id: Optional[str], logger) -> None:
    """
    Update app.etl_fathom records to mark Phase 1 as processed.

    Args:
        phase1_group_key: The group key (same as output_name)
        output_blob: Path to the output COG
        job_id: Job ID for tracking
        logger: Logger instance
    """
    from infrastructure.postgresql import PostgreSQLRepository

    try:
        repo = PostgreSQLRepository()
        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE app.etl_fathom
                    SET phase1_processed_at = NOW(),
                        phase1_output_blob = %(output_blob)s,
                        phase1_job_id = %(job_id)s,
                        updated_at = NOW()
                    WHERE phase1_group_key = %(group_key)s
                    """,
                    {
                        "output_blob": output_blob,
                        "job_id": job_id,
                        "group_key": phase1_group_key
                    }
                )
                updated_count = cur.rowcount
                conn.commit()

        logger.info(f"   📝 Updated {updated_count} records in app.etl_fathom (phase1_processed_at)")
    except Exception as e:
        # Log but don't fail - processing succeeded, tracking is secondary
        logger.warning(f"   ⚠️ Failed to update app.etl_fathom: {e}")


# =============================================================================
# PHASE 2 HANDLERS: Spatial Merge (process_fathom_merge job)
# =============================================================================

def fathom_grid_inventory(params: dict, context: dict = None) -> dict:
    """
    Query app.etl_fathom to create grid_groups for Phase 2 processing.

    DATABASE-DRIVEN (17 DEC 2025):
    - Queries app.etl_fathom for Phase 1 completed, Phase 2 pending records
    - Groups by phase2_group_key (grid_cell + scenario)
    - Uses phase1_output_blob for tile blob paths
    - FAILS FAST if no Phase 1 completed records exist

    Args:
        params: Task parameters
            - region_code: ISO country code (informational only)
            - grid_size: Grid cell size in degrees (informational - DB already has grid_cell)
            - source_container: Container filter (default: bronze-fathom)
            - bbox: Optional bounding box [west, south, east, north] to filter
            - collection_id: STAC collection ID for output naming

    Returns:
        dict with grid_groups (one per grid cell + scenario)
    """
    from infrastructure.postgresql import PostgreSQLRepository

    logger = LoggerFactory.create_logger(
        ComponentType.SERVICE,
        "fathom_grid_inventory"
    )

    region_code = params.get("region_code", "all").lower()
    grid_size = params.get("grid_size", FathomDefaults.DEFAULT_GRID_SIZE)
    source_container = params.get("source_container", FathomDefaults.SOURCE_CONTAINER)
    bbox = params.get("bbox")  # [west, south, east, north]
    collection_id = params.get("collection_id", FathomDefaults.PHASE2_COLLECTION_ID)

    logger.info(f"📋 Starting grid inventory from database")
    logger.info(f"   Grid size: {grid_size}×{grid_size} degrees")
    if bbox:
        logger.info(f"   Spatial filter (bbox): {bbox}")

    # Query Phase 1 completed, Phase 2 pending records grouped by phase2_group_key
    sql = """
        SELECT
            phase2_group_key,
            grid_cell,
            flood_type,
            defense,
            year,
            ssp,
            json_agg(
                json_build_object('tile', tile, 'blob_path', phase1_output_blob)
                ORDER BY tile
            ) as tiles,
            COUNT(*) as tile_count
        FROM app.etl_fathom
        WHERE phase1_processed_at IS NOT NULL
          AND phase2_processed_at IS NULL
          AND grid_cell IS NOT NULL
          AND phase1_output_blob IS NOT NULL
          AND source_container = %(source_container)s
        GROUP BY phase2_group_key, grid_cell, flood_type, defense, year, ssp
        ORDER BY phase2_group_key
    """

    repo = PostgreSQLRepository()
    with repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"source_container": source_container})
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]

    logger.info(f"   Query returned {len(rows)} grid groups")

    # FAIL FAST if no records
    if not rows:
        error_msg = (
            f"No Phase 1 completed records found in app.etl_fathom for Phase 2 processing. "
            f"Run process_fathom_stack job first to complete Phase 1."
        )
        logger.error(f"❌ {error_msg}")
        raise ValueError(error_msg)

    # Convert to grid_groups format
    grid_groups = []
    for row in rows:
        row_dict = dict(zip(columns, row))
        grid_cell = row_dict["grid_cell"]

        # Apply bbox filter if provided
        if bbox:
            if not _grid_cell_in_bbox(grid_cell, bbox):
                continue

        # Build output_name from phase2_group_key (already in correct format)
        output_name = row_dict["phase2_group_key"]

        # tiles is already a list from json_agg
        tiles = row_dict["tiles"]
        if isinstance(tiles, str):
            import json
            tiles = json.loads(tiles)

        grid_groups.append({
            "output_name": output_name,
            "grid_cell": grid_cell,
            "flood_type": row_dict["flood_type"],
            "defense": row_dict["defense"],
            "year": row_dict["year"],
            "ssp": row_dict["ssp"],
            "tiles": tiles,
            "tile_count": row_dict["tile_count"]
        })

    unique_grid_cells = len(set(g["grid_cell"] for g in grid_groups)) if grid_groups else 0
    total_tiles = sum(g["tile_count"] for g in grid_groups)

    logger.info(f"✅ Grid inventory complete (database-driven):")
    logger.info(f"   Unique grid cells: {unique_grid_cells}")
    logger.info(f"   Grid groups (output COGs): {len(grid_groups)}")
    logger.info(f"   Total source tiles: {total_tiles}")

    full_collection_id = f"{collection_id}-{region_code}"

    return {
        "success": True,
        "result": {
            "region_code": region_code,
            "grid_size": grid_size,
            "unique_grid_cells": unique_grid_cells,
            "grid_group_count": len(grid_groups),
            "grid_groups": grid_groups,
            "total_tiles": total_tiles,
            "skipped_existing_stac": 0,  # DB-driven idempotency via phase2_processed_at
            "stac_collection": full_collection_id,
            "bbox": bbox,
            "source": "database"  # Indicate database-driven inventory
        }
    }


def _grid_cell_in_bbox(grid_cell: str, bbox: list) -> bool:
    """Check if grid cell overlaps with bbox."""
    # Parse grid cell: "n00-n05_w010-w005"
    try:
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
    job_id = params.get("job_id")  # For tracking in app.etl_fathom

    grid_cell = grid_group["grid_cell"]
    output_name = grid_group["output_name"]
    tiles = grid_group["tiles"]

    logger.info(f"🔧 Spatial merge for grid cell: {grid_cell}")
    logger.info(f"   Tiles to merge: {len(tiles)}")

    config = get_config()
    # Silver zone for both reading (stacked COGs) and writing (merged COGs)
    blob_repo = BlobRepository.for_zone("silver")

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

    # =========================================================================
    # INLINE STATE UPDATE (17 DEC 2025)
    # Update app.etl_fathom records for this phase2_group_key
    # =========================================================================
    _update_phase2_processed(output_name, output_blob_path, job_id, logger)

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


def _update_phase2_processed(phase2_group_key: str, output_blob: str, job_id: Optional[str], logger) -> None:
    """
    Update app.etl_fathom records to mark Phase 2 as processed.

    Args:
        phase2_group_key: The group key (same as output_name)
        output_blob: Path to the output merged COG
        job_id: Job ID for tracking
        logger: Logger instance
    """
    from infrastructure.postgresql import PostgreSQLRepository

    try:
        repo = PostgreSQLRepository()
        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE app.etl_fathom
                    SET phase2_processed_at = NOW(),
                        phase2_output_blob = %(output_blob)s,
                        phase2_job_id = %(job_id)s,
                        updated_at = NOW()
                    WHERE phase2_group_key = %(group_key)s
                    """,
                    {
                        "output_blob": output_blob,
                        "job_id": job_id,
                        "group_key": phase2_group_key
                    }
                )
                updated_count = cur.rowcount
                conn.commit()

        logger.info(f"   📝 Updated {updated_count} records in app.etl_fathom (phase2_processed_at)")
    except Exception as e:
        # Log but don't fail - processing succeeded, tracking is secondary
        logger.warning(f"   ⚠️ Failed to update app.etl_fathom: {e}")


# =============================================================================
# STAC REGISTRATION (Shared by both Phase 1 and Phase 2)
# =============================================================================

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
    from infrastructure.pgstac_bootstrap import PgStacBootstrap
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
    stac_repo = PgStacBootstrap()

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
                # Handle both Phase 1 (file_count) and Phase 2 (tile_count)
                "fathom:source_tiles": cog_result.get("tile_count", cog_result.get("file_count", 0)),
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

        # Insert item (note: PgStacBootstrap.insert_item signature is (item, collection_id))
        try:
            stac_repo.insert_item(item, full_collection_id)
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
