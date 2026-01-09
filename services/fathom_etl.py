# ============================================================================
# FATHOM ETL TASK HANDLERS
# ============================================================================
# STATUS: Services - Phase 1 band stacking + Phase 2 spatial merge handlers
# PURPOSE: Transform 8M raw Fathom tiles → 1M stacked → 40K merged COGs
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Fathom ETL Task Handlers.

DATABASE-DRIVEN ARCHITECTURE (21 DEC 2025):
All inventory operations query app.etl_source_files table (etl_type='fathom')
populated by InventoryFathomContainerJob. Processing state is tracked inline:
- phase1_completed_at: Set by fathom_band_stack after successful COG creation
- phase2_completed_at: Set by fathom_spatial_merge after successful merge

Phase 1 (Band Stacking):
    - fathom_tile_inventory: Query DB for unprocessed tiles
    - fathom_band_stack: Stack 8 return periods into multi-band COG

Phase 2 (Spatial Merge):
    - fathom_grid_inventory: Query DB for Phase 1 completed, Phase 2 pending
    - fathom_spatial_merge: Merge tiles band-by-band

Shared:
    - fathom_stac_register: STAC collection/item creation

NOTE (21 DEC 2025): Migrated from FATHOM-specific etl_fathom table to
general-purpose etl_source_files table with JSONB metadata.

Exports:
    fathom_tile_inventory, fathom_band_stack, fathom_grid_inventory,
    fathom_spatial_merge, fathom_stac_register
"""

import re
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional

from util_logger import LoggerFactory, ComponentType, log_memory_checkpoint
from config import FathomDefaults

# E13: Pipeline Observability (28 DEC 2025)
# Lazy import to avoid circular dependencies
_tracker_class = None

def _get_tracker_class():
    """Lazy load FathomETLTracker to avoid import-time issues."""
    global _tracker_class
    if _tracker_class is None:
        from infrastructure.job_progress_contexts import FathomETLTracker
        _tracker_class = FathomETLTracker
    return _tracker_class


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
    Query app.etl_source_files to create tile_groups for Phase 1 processing.

    DATABASE-DRIVEN (21 DEC 2025):
    - Queries app.etl_source_files table (etl_type='fathom')
    - Groups by phase1_group_key (tile + scenario)
    - Filters by phase1_completed_at IS NULL for unprocessed records
    - FAILS FAST if no records exist for region

    Args:
        params: Task parameters
            - region_code: ISO country code (e.g., "rwa") - FILTERS by source_metadata->>'region'
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

    # region_code filters by source_metadata->>'region' (07 JAN 2026 fix)
    region_code = params.get("region_code", "").lower() if params.get("region_code") else None
    source_container = params.get("source_container", FathomDefaults.SOURCE_CONTAINER)
    filter_flood_types = params.get("flood_types")
    filter_years = params.get("years")
    filter_ssp = params.get("ssp_scenarios")
    bbox = params.get("bbox")  # [west, south, east, north]
    collection_id = params.get("collection_id", FathomDefaults.PHASE1_COLLECTION_ID)
    dry_run = params.get("dry_run", False)

    logger.info(f"📋 Starting Fathom TILE inventory from database")
    logger.info(f"   Region filter: {region_code or 'ALL (no filter)'}")
    logger.info(f"   Source container filter: {source_container}")
    if bbox:
        logger.info(f"   Spatial filter (bbox): {bbox}")

    # Build SQL query with filters
    # NOTE: source_metadata contains FATHOM-specific fields as JSONB
    where_clauses = [
        "etl_type = 'fathom'",
        "phase1_completed_at IS NULL",
        "source_container = %(source_container)s"
    ]
    query_params = {"source_container": source_container}

    # Filter by region (07 JAN 2026 fix for multi-region support)
    if region_code:
        where_clauses.append("source_metadata->>'region' = %(region)s")
        query_params["region"] = region_code
        logger.info(f"   Filter: region = {region_code}")

    if filter_flood_types:
        # Convert raw flood types to normalized (e.g., COASTAL_DEFENDED → coastal, defended)
        flood_type_conditions = []
        for ft_raw in filter_flood_types:
            if ft_raw in FLOOD_TYPE_MAP:
                ft_info = FLOOD_TYPE_MAP[ft_raw]
                flood_type_conditions.append(
                    f"(source_metadata->>'flood_type' = '{ft_info['flood_type']}' AND source_metadata->>'defense' = '{ft_info['defense']}')"
                )
        if flood_type_conditions:
            where_clauses.append(f"({' OR '.join(flood_type_conditions)})")
        logger.info(f"   Filter: flood_types = {filter_flood_types}")

    if filter_years:
        where_clauses.append("(source_metadata->>'year')::int = ANY(%(years)s)")
        query_params["years"] = filter_years
        logger.info(f"   Filter: years = {filter_years}")

    if filter_ssp:
        # Normalize SSP values for query
        normalized_ssp = [SSP_MAP.get(s, s) for s in filter_ssp]
        where_clauses.append("(source_metadata->>'ssp' = ANY(%(ssp)s) OR source_metadata->>'ssp' IS NULL)")
        query_params["ssp"] = normalized_ssp
        logger.info(f"   Filter: ssp_scenarios = {filter_ssp}")

    if bbox:
        # Filter tiles by bbox - tile coordinate must be within bbox
        # We'll filter in Python after query since tile parsing is complex
        pass  # Applied post-query

    where_clause = " AND ".join(where_clauses)

    # Query grouped by phase1_group_key with return_period_files aggregation
    # Extract FATHOM-specific fields from source_metadata JSONB
    sql = f"""
        SELECT
            phase1_group_key,
            source_metadata->>'tile' as tile,
            source_metadata->>'flood_type' as flood_type,
            source_metadata->>'defense' as defense,
            (source_metadata->>'year')::int as year,
            source_metadata->>'ssp' as ssp,
            json_object_agg(source_metadata->>'return_period', source_blob_path ORDER BY source_metadata->>'return_period') as return_period_files,
            COUNT(*) as file_count
        FROM app.etl_source_files
        WHERE {where_clause}
        GROUP BY phase1_group_key, source_metadata->>'tile', source_metadata->>'flood_type',
                 source_metadata->>'defense', source_metadata->>'year', source_metadata->>'ssp'
        ORDER BY phase1_group_key
    """

    repo = PostgreSQLRepository()
    with repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, query_params)
            rows = cur.fetchall()  # Returns list of dicts due to dict_row factory

    logger.info(f"   Query returned {len(rows)} tile groups")

    # FAIL FAST if no records
    if not rows:
        error_msg = (
            f"No unprocessed records found in app.etl_source_files (etl_type='fathom') for container '{source_container}'. "
            f"Run inventory_fathom_container job first to populate the table."
        )
        logger.error(f"❌ {error_msg}")
        raise ValueError(error_msg)

    # Convert to tile_groups format
    # NOTE: rows are dicts due to PostgreSQLRepository's dict_row factory
    tile_groups = []
    for idx, row in enumerate(rows):
        if idx < 3:  # Log first 3 rows for debugging
            logger.debug(f"   🔍 Row {idx}: keys={list(row.keys())}")
            logger.debug(f"   🔍 Row {idx}: values={[repr(v)[:100] for v in row.values()]}")
        row_dict = row  # Already a dict from dict_row factory

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

        # return_period_files from json_object_agg - handle various formats
        rp_files = row_dict["return_period_files"]
        logger.debug(f"   🔍 {output_name}: return_period_files type={type(rp_files).__name__}, value={repr(rp_files)[:200]}")
        if rp_files is None:
            logger.warning(f"   ⚠️ {output_name}: return_period_files is NULL - skipping")
            continue
        if isinstance(rp_files, str):
            import json
            # Handle empty string case
            if not rp_files or rp_files.strip() == "":
                logger.warning(f"   ⚠️ {output_name}: return_period_files is empty string - skipping")
                continue
            try:
                rp_files = json.loads(rp_files)
            except json.JSONDecodeError as e:
                logger.warning(f"   ⚠️ {output_name}: Failed to parse return_period_files: {e} - skipping")
                continue
        if not rp_files:
            logger.warning(f"   ⚠️ {output_name}: return_period_files is empty - skipping")
            continue

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

    full_collection_id = f"{collection_id}-{region_code}" if region_code else collection_id

    return {
        "success": True,
        "result": {
            "region_code": region_code or "all",
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
    job_id = params.get("job_id")  # For tracking in app.etl_source_files

    tile = tile_group["tile"]
    output_name = tile_group["output_name"]
    context_id = job_id or output_name  # Use job_id for correlation, fallback to output_name
    logger.info(f"🔧 Band stacking tile: {output_name}")

    # E13: Pipeline Observability - Create tracker for metrics (28 DEC 2025)
    tracker = None
    if job_id:
        try:
            TrackerClass = _get_tracker_class()
            tracker = TrackerClass(
                job_id=job_id,
                job_type="process_fathom_stack",
                auto_persist=True
            )
            tracker.set_tiles_total(1)  # One tile per band_stack task
        except Exception as e:
            logger.warning(f"Could not create metrics tracker: {e}")
            tracker = None

    # Memory checkpoint: start of band stacking
    log_memory_checkpoint(logger, "band_stack START", context_id=context_id)

    config = get_config()
    # Bronze zone for reading source tiles, Silver zone for writing output
    bronze_repo = BlobRepository.for_zone("bronze")
    silver_repo = BlobRepository.for_zone("silver")

    # Output path: fathom-stacked/{region}/{tile}/{scenario}.tif
    output_blob_path = f"{output_prefix}/{region_code}/{tile}/{output_name}.tif"

    # Idempotency check (check silver for existing output)
    if not force_reprocess and silver_repo.blob_exists(output_container, output_blob_path):
        logger.info(f"⏭️ SKIP: Output already exists: {output_container}/{output_blob_path}")

        # Read bounds from existing file for STAC registration
        bounds_dict = None
        try:
            import rasterio
            from io import BytesIO
            blob_bytes = silver_repo.read_blob(output_container, output_blob_path)
            with rasterio.open(BytesIO(blob_bytes)) as src:
                bounds = src.bounds
                bounds_dict = {
                    "west": bounds.left,
                    "south": bounds.bottom,
                    "east": bounds.right,
                    "north": bounds.top
                }
            logger.info(f"   📐 Read bounds from existing COG: {bounds_dict}")
        except Exception as e:
            logger.warning(f"   ⚠️ Could not read bounds from existing COG: {e}")

        result = {
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
        if bounds_dict:
            result["bounds"] = bounds_dict

        # Update ETL tracking even on skip (04 JAN 2026)
        # Phase 2 depends on phase1_completed_at being set
        _update_phase1_processed(output_name, output_blob_path, job_id, logger)

        return {
            "success": True,
            "skipped": True,
            "result": result
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

        # Memory checkpoint: after downloading all return periods
        log_memory_checkpoint(logger, "band_stack after_download", context_id=context_id,
                              file_count=len(bands))

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

        # Memory checkpoint: after COG creation
        log_memory_checkpoint(logger, "band_stack after_cog_write", context_id=context_id)

        # Get output size
        output_size = output_path.stat().st_size
        output_size_kb = output_size / 1024
        logger.info(f"   📏 Output size: {output_size_kb:.1f} KB")

        # Upload to silver (processed data)
        with open(output_path, "rb") as f:
            silver_repo.write_blob(output_container, output_blob_path, f.read())

        logger.info(f"   ☁️ Uploaded: {output_container}/{output_blob_path}")

    # Memory checkpoint: after upload complete
    log_memory_checkpoint(logger, "band_stack END", context_id=context_id,
                          output_size_kb=output_size_kb)

    # E13: Record tile completion in tracker
    if tracker:
        tracker.record_tile(
            tile_id=output_name,
            size_bytes=int(output_size_kb * 1024),
            region=region_code
        )

    # =========================================================================
    # INLINE STATE UPDATE (21 DEC 2025)
    # Update app.etl_source_files records for this phase1_group_key
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
    Update app.etl_source_files records to mark Phase 1 as processed.

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
                    UPDATE app.etl_source_files
                    SET phase1_completed_at = NOW(),
                        phase1_output_blob = %(output_blob)s,
                        phase1_job_id = %(job_id)s,
                        updated_at = NOW()
                    WHERE etl_type = 'fathom'
                      AND phase1_group_key = %(group_key)s
                    """,
                    {
                        "output_blob": output_blob,
                        "job_id": job_id,
                        "group_key": phase1_group_key
                    }
                )
                updated_count = cur.rowcount
                conn.commit()

        logger.info(f"   📝 Updated {updated_count} records in app.etl_source_files (phase1_completed_at)")
    except Exception as e:
        # Log but don't fail - processing succeeded, tracking is secondary
        logger.warning(f"   ⚠️ Failed to update app.etl_source_files: {e}")


# =============================================================================
# PHASE 2 HANDLERS: Spatial Merge (process_fathom_merge job)
# =============================================================================

def fathom_grid_inventory(params: dict, context: dict = None) -> dict:
    """
    Query app.etl_source_files to create grid_groups for Phase 2 processing.

    DATABASE-DRIVEN (21 DEC 2025):
    - Queries app.etl_source_files (etl_type='fathom') for Phase 1 completed, Phase 2 pending
    - Groups by phase2_group_key (grid_cell + scenario)
    - Uses phase1_output_blob for tile blob paths
    - FAILS FAST if no Phase 1 completed records exist

    Args:
        params: Task parameters
            - region_code: ISO country code - FILTERS by source_metadata->>'region'
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

    # region_code filters by source_metadata->>'region' (07 JAN 2026 fix)
    region_code = params.get("region_code", "").lower() if params.get("region_code") else None
    grid_size = params.get("grid_size", FathomDefaults.DEFAULT_GRID_SIZE)
    source_container = params.get("source_container", FathomDefaults.SOURCE_CONTAINER)
    bbox = params.get("bbox")  # [west, south, east, north]
    collection_id = params.get("collection_id", FathomDefaults.PHASE2_COLLECTION_ID)

    logger.info(f"📋 Starting grid inventory from database")
    logger.info(f"   Region filter: {region_code or 'ALL (no filter)'}")
    logger.info(f"   Grid size: {grid_size}×{grid_size} degrees")
    if bbox:
        logger.info(f"   Spatial filter (bbox): {bbox}")

    # Query Phase 1 completed, Phase 2 pending records grouped by phase2_group_key
    # NOTE: source_metadata contains FATHOM-specific fields as JSONB
    # NOTE: We don't filter by source_container here because:
    # - source_container stores the ORIGINAL source (bronze-fathom)
    # - The job's source_container param refers to Phase 1 OUTPUT location (silver-fathom)
    # - Filtering by phase1_completed_at IS NOT NULL is sufficient
    # BUG FIX (05 JAN 2026): Use DISTINCT to deduplicate tiles
    # Each tile+scenario has 8 source files (one per return period) that all share
    # the same phase1_output_blob. Without DISTINCT, we'd get 8x duplicates.
    # BUG FIX (07 JAN 2026): Add region filter to prevent cross-region contamination

    # Build region filter clause
    region_filter = ""
    query_params = {}
    if region_code:
        region_filter = "AND source_metadata->>'region' = %(region)s"
        query_params["region"] = region_code
        logger.info(f"   Filter: region = {region_code}")

    sql = f"""
        WITH unique_tiles AS (
            SELECT DISTINCT ON (phase2_group_key, source_metadata->>'tile')
                phase2_group_key,
                source_metadata->>'grid_cell' as grid_cell,
                source_metadata->>'flood_type' as flood_type,
                source_metadata->>'defense' as defense,
                (source_metadata->>'year')::int as year,
                source_metadata->>'ssp' as ssp,
                source_metadata->>'tile' as tile,
                phase1_output_blob
            FROM app.etl_source_files
            WHERE etl_type = 'fathom'
              AND phase1_completed_at IS NOT NULL
              AND phase2_completed_at IS NULL
              AND source_metadata->>'grid_cell' IS NOT NULL
              AND phase1_output_blob IS NOT NULL
              {region_filter}
            ORDER BY phase2_group_key, source_metadata->>'tile'
        )
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
        FROM unique_tiles
        GROUP BY phase2_group_key, grid_cell, flood_type, defense, year, ssp
        ORDER BY phase2_group_key
    """

    repo = PostgreSQLRepository()
    with repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, query_params)
            rows = cur.fetchall()  # Returns list of dicts due to dict_row factory

    logger.info(f"   Query returned {len(rows)} grid groups")

    # FAIL FAST if no records
    if not rows:
        error_msg = (
            f"No Phase 1 completed records found in app.etl_source_files (etl_type='fathom') for Phase 2 processing. "
            f"Run process_fathom_stack job first to complete Phase 1."
        )
        logger.error(f"❌ {error_msg}")
        raise ValueError(error_msg)

    # Convert to grid_groups format
    # NOTE: rows are dicts due to PostgreSQLRepository's dict_row factory
    grid_groups = []
    for row in rows:
        row_dict = row  # Already a dict from dict_row factory
        grid_cell = row_dict["grid_cell"]

        # Apply bbox filter if provided
        if bbox:
            if not _grid_cell_in_bbox(grid_cell, bbox):
                continue

        # Build output_name from phase2_group_key (already in correct format)
        output_name = row_dict["phase2_group_key"]

        # tiles from json_agg - handle various formats
        tiles = row_dict["tiles"]
        if tiles is None:
            logger.warning(f"   ⚠️ {output_name}: tiles is NULL - skipping")
            continue
        if isinstance(tiles, str):
            import json
            if not tiles or tiles.strip() == "":
                logger.warning(f"   ⚠️ {output_name}: tiles is empty string - skipping")
                continue
            try:
                tiles = json.loads(tiles)
            except json.JSONDecodeError as e:
                logger.warning(f"   ⚠️ {output_name}: Failed to parse tiles: {e} - skipping")
                continue
        if not tiles:
            logger.warning(f"   ⚠️ {output_name}: tiles is empty - skipping")
            continue

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

    full_collection_id = f"{collection_id}-{region_code}" if region_code else collection_id

    return {
        "success": True,
        "result": {
            "region_code": region_code or "all",
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
    job_id = params.get("job_id")  # For tracking in app.etl_source_files

    grid_cell = grid_group["grid_cell"]
    output_name = grid_group["output_name"]
    tiles = grid_group["tiles"]
    context_id = job_id or output_name  # Use job_id for correlation, fallback to output_name

    logger.info(f"🔧 Spatial merge for grid cell: {grid_cell}")
    logger.info(f"   Tiles to merge: {len(tiles)}")

    # E13: Pipeline Observability - Create tracker for metrics (28 DEC 2025)
    tracker = None
    if job_id:
        try:
            TrackerClass = _get_tracker_class()
            tracker = TrackerClass(
                job_id=job_id,
                job_type="process_fathom_merge",
                auto_persist=True
            )
            tracker.set_tiles_total(len(tiles))
            tracker.start_region(grid_cell)
        except Exception as e:
            logger.warning(f"Could not create metrics tracker: {e}")
            tracker = None

    # Memory checkpoint: start of spatial merge
    log_memory_checkpoint(logger, "spatial_merge START", context_id=context_id,
                          tile_count=len(tiles))

    config = get_config()
    # Silver zone for both reading (stacked COGs) and writing (merged COGs)
    blob_repo = BlobRepository.for_zone("silver")

    # Output path - flat structure (no grid_cell subfolder)
    # Format: {prefix}/{region}/{flood_type}-{defense}-{year}[-{ssp}]-{grid_cell}.tif
    output_blob_path = f"{output_prefix}/{region_code}/{output_name}.tif"

    # Idempotency check
    if not force_reprocess and blob_repo.blob_exists(output_container, output_blob_path):
        logger.info(f"⏭️ SKIP: Output already exists: {output_container}/{output_blob_path}")

        # Read bounds from existing file for STAC registration
        bounds_dict = None
        try:
            import rasterio
            from io import BytesIO
            blob_bytes = blob_repo.read_blob(output_container, output_blob_path)
            with rasterio.open(BytesIO(blob_bytes)) as src:
                bounds = src.bounds
                bounds_dict = {
                    "west": bounds.left,
                    "south": bounds.bottom,
                    "east": bounds.right,
                    "north": bounds.top
                }
            logger.info(f"   📐 Read bounds from existing COG: {bounds_dict}")
        except Exception as e:
            logger.warning(f"   ⚠️ Could not read bounds from existing COG: {e}")

        result = {
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
        if bounds_dict:
            result["bounds"] = bounds_dict

        # Update ETL tracking even on skip (04 JAN 2026)
        # This ensures phase2_completed_at is set for tracking purposes
        _update_phase2_processed(output_name, output_blob_path, job_id, logger)

        return {
            "success": True,
            "skipped": True,
            "result": result
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

        # Memory checkpoint: after downloading all tiles
        log_memory_checkpoint(logger, "spatial_merge after_download", context_id=context_id,
                              tiles_downloaded=len(local_tiles))

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

            # Memory checkpoint: after each band merge (track peak memory per band)
            if band_num == 1 or band_num == len(RETURN_PERIODS):  # First and last band only
                log_memory_checkpoint(logger, f"spatial_merge band_{band_num}_complete",
                                      context_id=context_id, return_period=RETURN_PERIODS[band_idx])

        # Stack all merged bands
        stacked = np.stack(merged_bands, axis=0)
        logger.info(f"   📦 Merged shape: {stacked.shape}")

        # Memory checkpoint: after stacking all bands (peak memory expected here)
        log_memory_checkpoint(logger, "spatial_merge after_stack", context_id=context_id,
                              shape=f"{stacked.shape}")

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

        # Memory checkpoint: after COG write
        log_memory_checkpoint(logger, "spatial_merge after_cog_write", context_id=context_id)

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

    # Memory checkpoint: after upload complete
    log_memory_checkpoint(logger, "spatial_merge END", context_id=context_id,
                          output_size_mb=output_size_mb, tile_count=len(tiles))

    # E13: Record merged tile completion in tracker
    if tracker:
        tracker.record_tile(
            tile_id=output_name,
            size_bytes=int(output_size_mb * 1024 * 1024),
            region=grid_cell
        )
        tracker.complete_region(grid_cell)

    # =========================================================================
    # INLINE STATE UPDATE (21 DEC 2025)
    # Update app.etl_source_files records for this phase2_group_key
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
    Update app.etl_source_files records to mark Phase 2 as processed.

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
                    UPDATE app.etl_source_files
                    SET phase2_completed_at = NOW(),
                        phase2_output_blob = %(output_blob)s,
                        phase2_job_id = %(job_id)s,
                        updated_at = NOW()
                    WHERE etl_type = 'fathom'
                      AND phase2_group_key = %(group_key)s
                    """,
                    {
                        "output_blob": output_blob,
                        "job_id": job_id,
                        "group_key": phase2_group_key
                    }
                )
                updated_count = cur.rowcount
                conn.commit()

        logger.info(f"   📝 Updated {updated_count} records in app.etl_source_files (phase2_completed_at)")
    except Exception as e:
        # Log but don't fail - processing succeeded, tracking is secondary
        logger.warning(f"   ⚠️ Failed to update app.etl_source_files: {e}")


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

    # ==========================================================================
    # LOAD COG RESULTS - Universal Database Reference Pattern (05 JAN 2026)
    # ==========================================================================
    # CoreMachine fan-in tasks now use database reference pattern:
    #   - fan_in_source: {job_id, source_stage, expected_count}
    #   - job_parameters: original job parameters
    # Handler queries database directly instead of receiving embedded results.
    # ==========================================================================

    if "fan_in_source" in params:
        # NEW PATTERN: CoreMachine database reference (05 JAN 2026)
        from core.fan_in import load_fan_in_results, get_job_parameters
        cog_results = load_fan_in_results(params)
        job_params = get_job_parameters(params)
        region_code = job_params["region_code"].lower()
        collection_id = job_params.get("collection_id", FathomDefaults.PHASE1_COLLECTION_ID)
        output_container = job_params.get("output_container", FathomDefaults.PHASE1_OUTPUT_CONTAINER)
        dry_run = job_params.get("dry_run", False)
        logger.info(f"📚 Fan-in mode (DB reference): loaded {len(cog_results)} COG results")

    elif "job_parameters" in params:
        # LEGACY: Old CoreMachine fan-in with embedded previous_results
        # Kept for backward compatibility during transition
        job_params = params["job_parameters"]
        previous_results = params.get("previous_results", [])
        cog_results = [
            r.get("result", r) for r in previous_results
            if r.get("success") and r.get("result")
        ]
        region_code = job_params["region_code"].lower()
        collection_id = job_params.get("collection_id", FathomDefaults.PHASE1_COLLECTION_ID)
        output_container = job_params.get("output_container", FathomDefaults.PHASE1_OUTPUT_CONTAINER)
        dry_run = job_params.get("dry_run", False)
        logger.info(f"📚 Fan-in mode (legacy embedded): {len(cog_results)} COGs from {len(previous_results)} results")

    elif "job_id" in params and "cog_results" not in params:
        # DIRECT: Job-level database reference (from process_fathom_stack/merge)
        source_job_id = params["job_id"]
        source_stage = params.get("stage", 2)
        expected_count = params.get("cog_count", 0)
        logger.info(f"📊 Direct DB query: {expected_count} Stage {source_stage} results from job {source_job_id[:16]}...")

        from infrastructure.jobs_tasks import TaskRepository
        task_repo = TaskRepository()
        tasks = task_repo.get_tasks_for_job(source_job_id)

        cog_results = []
        for task in tasks:
            if task.stage == source_stage and task.status.value == "completed" and task.result_data:
                result = task.result_data.get("result")
                if result:
                    cog_results.append(result)

        logger.info(f"   Retrieved {len(cog_results)} COG results from database")
        if expected_count and len(cog_results) != expected_count:
            logger.warning(f"   ⚠️ Expected {expected_count} but got {len(cog_results)} results")

        region_code = params["region_code"].lower()
        collection_id = params.get("collection_id", FathomDefaults.PHASE2_COLLECTION_ID)
        output_container = params.get("output_container", FathomDefaults.PHASE2_OUTPUT_CONTAINER)
        dry_run = params.get("dry_run", False)

    else:
        # LEGACY: Direct params with embedded cog_results
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
    if stac_repo.collection_exists(full_collection_id):
        logger.info(f"   Using existing collection: {full_collection_id}")
    else:
        # Create collection using new API
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

        # Use new create_collection API (requires container and tier)
        result = stac_repo.create_collection(
            container=output_container,
            tier="silver",
            collection_id=full_collection_id,
            title=f"Fathom Global Flood Hazard Maps - {region_code.upper()}",
            description=(
                f"Consolidated flood hazard data for {region_code.upper()} from Fathom Global v3. "
                "Multi-band COGs with return periods (1in5 to 1in1000) as bands. "
                "Flood depth values in centimeters."
            ),
            summaries={
                "fathom:flood_type": ["coastal", "fluvial", "pluvial"],
                "fathom:defense_status": ["defended", "undefended"],
                "fathom:year": [2020, 2030, 2050, 2080],
                "fathom:ssp_scenario": ["ssp126", "ssp245", "ssp370", "ssp585"]
            },
            # Additional STAC properties via **kwargs
            license="proprietary",
            extent={
                "spatial": {"bbox": [collection_bounds]},
                "temporal": {"interval": [["2020-01-01T00:00:00Z", "2080-12-31T23:59:59Z"]]}
            },
            keywords=["flood", "hazard", "fathom", "climate", region_code]
        )
        if result.get("success"):
            logger.info(f"   ✅ Collection created: {full_collection_id}")
        else:
            logger.warning(f"   ⚠️ Collection creation result: {result}")

    # Create STAC items for each COG
    items_created = 0
    # Use /vsiaz/ path format for OAuth-compatible TiTiler-pgSTAC access
    # Pattern matches service_stac_metadata.py Step G.5 and stac_collection.py
    storage_base = f"/vsiaz/{output_container}"

    for cog_result in cog_results:
        output_blob = cog_result["output_blob"]
        output_name = cog_result["output_name"]

        # Skip items without bounds (e.g., skipped due to idempotency)
        if "bounds" not in cog_result:
            logger.warning(f"   ⚠️ Skipping STAC item for {output_name} - no bounds (likely skipped task)")
            continue

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

        # Add TiTiler visualization links (04 JAN 2026)
        # 8-band COGs need bidx parameter; default to band 5 (1-in-100 year return period)
        # Pattern matches service_stac_metadata.py and stac_metadata_helper.py
        import urllib.parse
        titiler_base = config.titiler_base_url.rstrip('/')
        vsiaz_encoded = urllib.parse.quote(asset_href, safe='')
        # Visualization params: band 5, rescale 0-300cm, blues colormap
        viz_params = "bidx=5&rescale=0,300&colormap_name=blues"

        item["links"].extend([
            {
                "rel": "preview",
                "href": f"{titiler_base}/cog/WebMercatorQuad/map.html?url={vsiaz_encoded}&{viz_params}",
                "type": "text/html",
                "title": "Interactive map viewer (TiTiler) - 1-in-100 year flood"
            },
            {
                "rel": "tilejson",
                "href": f"{titiler_base}/cog/WebMercatorQuad/tilejson.json?url={vsiaz_encoded}&{viz_params}",
                "type": "application/json",
                "title": "TileJSON specification"
            }
        ])

        # Add thumbnail asset
        item["assets"]["thumbnail"] = {
            "href": f"{titiler_base}/cog/preview.png?url={vsiaz_encoded}&max_size=256&{viz_params}",
            "type": "image/png",
            "roles": ["thumbnail"],
            "title": "Preview thumbnail (1-in-100 year flood depth)"
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
            "stac_catalog_url": f"{config.etl_app_base_url}/api/stac/collections/{full_collection_id}"
        }
    }


# =============================================================================
# STAC REBUILD (From Existing COGs - 09 JAN 2026)
# =============================================================================

def fathom_stac_rebuild(params: dict, context: dict = None) -> dict:
    """
    Rebuild STAC collection and items from existing FATHOM COGs.

    This allows recreating STAC entries without reprocessing the GeoTIFFs.
    Scans blob storage, extracts metadata from filenames and COG headers,
    and creates/updates STAC collection and items.

    Args:
        params: Task parameters
            - region_code: ISO country code (e.g., "rwa")
            - phase: 1 or 2 (default: 2)
            - dry_run: If True, only scan and report (no STAC writes)
            - force_recreate: If True, delete existing items before recreating

    Returns:
        dict with rebuild summary

    Example:
        # Rebuild Rwanda Phase 2 STAC
        curl -X POST .../api/jobs/submit/fathom_stac_rebuild -d '{"region_code": "rwa", "phase": 2}'
    """
    import re
    from datetime import datetime, timezone
    from infrastructure.pgstac_bootstrap import PgStacBootstrap
    from infrastructure.blob import BlobRepository
    from config import get_config

    logger = LoggerFactory.create_logger(
        ComponentType.SERVICE,
        "fathom_stac_rebuild"
    )

    region_code = params.get("region_code", "").lower()
    phase = params.get("phase", 2)
    dry_run = params.get("dry_run", False)
    force_recreate = params.get("force_recreate", False)

    if not region_code:
        return {"success": False, "error": "region_code is required"}

    logger.info(f"🔄 STAC Rebuild: Phase {phase} for region {region_code.upper()}")
    logger.info(f"   dry_run={dry_run}, force_recreate={force_recreate}")

    config = get_config()

    # Determine container and prefix based on phase
    if phase == 1:
        container = FathomDefaults.PHASE1_OUTPUT_CONTAINER
        prefix = f"{FathomDefaults.PHASE1_OUTPUT_PREFIX}/{region_code}/"
        collection_base = FathomDefaults.PHASE1_COLLECTION_ID
    else:
        container = FathomDefaults.PHASE2_OUTPUT_CONTAINER
        prefix = f"{FathomDefaults.PHASE2_OUTPUT_PREFIX}/{region_code}/"
        collection_base = FathomDefaults.PHASE2_COLLECTION_ID

    full_collection_id = f"{collection_base}-{region_code}"

    # List existing COGs
    logger.info(f"📂 Scanning {container}/{prefix}...")
    blob_repo = BlobRepository(zone="silver")
    blobs = blob_repo.list_blobs(container, prefix=prefix, suffix=".tif")

    if not blobs:
        logger.warning(f"   No COGs found in {container}/{prefix}")
        return {
            "success": True,
            "result": {
                "collection_id": full_collection_id,
                "cogs_found": 0,
                "items_created": 0,
                "message": "No COGs found to rebuild"
            }
        }

    logger.info(f"   Found {len(blobs)} COGs")

    if dry_run:
        logger.info("🔍 DRY RUN - listing COGs only")
        return {
            "success": True,
            "result": {
                "dry_run": True,
                "collection_id": full_collection_id,
                "cogs_found": len(blobs),
                "cog_list": [b["name"] for b in blobs[:20]],
                "message": f"Found {len(blobs)} COGs (showing first 20)"
            }
        }

    # Parse COG metadata from filenames and extract bounds
    # Filename pattern: {flood_type}-{defense}-{year}[-{ssp}]-{grid}.tif
    # Example: fluvial-defended-2030-ssp245-s00-s04_e028-e032.tif
    cog_results = []

    for blob in blobs:
        blob_name = blob["name"]
        filename = blob_name.split("/")[-1].replace(".tif", "")

        # Parse filename components
        parts = filename.split("-")
        if len(parts) < 4:
            logger.warning(f"   ⚠️ Cannot parse filename: {filename}")
            continue

        flood_type = parts[0]  # fluvial, pluvial, coastal
        defense = parts[1]     # defended, undefended
        year = int(parts[2])   # 2020, 2030, 2050, 2080

        # SSP scenario (optional - only for future years)
        if year > 2020 and len(parts) >= 5:
            ssp = parts[3]  # ssp126, ssp245, ssp370, ssp585
            grid_parts = parts[4:]
        else:
            ssp = None
            grid_parts = parts[3:]

        grid = "-".join(grid_parts)  # s00-s04_e028-e032

        # Extract bounds from COG using rasterio
        try:
            import rasterio
            from azure.storage.blob import BlobServiceClient

            # Get blob URL with SAS or use managed identity
            silver_account = config.silver_storage_account
            blob_url = f"https://{silver_account}.blob.core.windows.net/{container}/{blob_name}"

            # Use /vsiaz/ for GDAL/rasterio access
            vsi_path = f"/vsiaz/{container}/{blob_name}"

            with rasterio.open(vsi_path) as src:
                bounds = src.bounds
                cog_bounds = {
                    "west": bounds.left,
                    "south": bounds.bottom,
                    "east": bounds.right,
                    "north": bounds.top
                }

            cog_results.append({
                "output_blob": blob_name,
                "output_name": filename,
                "bounds": cog_bounds,
                "year": year,
                "flood_type": flood_type,
                "defense_status": defense,
                "ssp_scenario": ssp,
                "grid_cell": grid
            })

        except Exception as e:
            logger.warning(f"   ⚠️ Cannot read bounds for {filename}: {e}")
            # Try without bounds - use approximate from grid name
            # Grid format: s{lat1}-s{lat2}_e{lon1}-e{lon2}
            try:
                grid_match = re.match(r's(\d+)-s(\d+)_e(\d+)-e(\d+)', grid)
                if grid_match:
                    s1, s2, e1, e2 = map(int, grid_match.groups())
                    cog_bounds = {
                        "west": e1,
                        "south": -s2,
                        "east": e2,
                        "north": -s1
                    }
                    cog_results.append({
                        "output_blob": blob_name,
                        "output_name": filename,
                        "bounds": cog_bounds,
                        "year": year,
                        "flood_type": flood_type,
                        "defense_status": defense,
                        "ssp_scenario": ssp,
                        "grid_cell": grid
                    })
            except Exception:
                logger.warning(f"   ⚠️ Skipping {filename} - cannot determine bounds")

    logger.info(f"   Parsed {len(cog_results)} COGs with metadata")

    if not cog_results:
        return {
            "success": False,
            "error": "Could not parse any COG metadata"
        }

    # Now use fathom_stac_register logic to create collection and items
    stac_repo = PgStacBootstrap()

    # Handle force_recreate - delete existing collection
    if force_recreate and stac_repo.collection_exists(full_collection_id):
        logger.info(f"   🗑️ Deleting existing collection: {full_collection_id}")
        try:
            stac_repo.delete_collection(full_collection_id)
        except Exception as e:
            logger.warning(f"   ⚠️ Could not delete collection: {e}")

    # Create collection if not exists
    if not stac_repo.collection_exists(full_collection_id):
        logger.info(f"   📚 Creating collection: {full_collection_id}")

        # Calculate collection bounds from all COGs
        all_bounds = [r["bounds"] for r in cog_results]
        collection_bounds = [
            min(b["west"] for b in all_bounds),
            min(b["south"] for b in all_bounds),
            max(b["east"] for b in all_bounds),
            max(b["north"] for b in all_bounds)
        ]

        result = stac_repo.create_collection(
            container=container,
            tier="silver",
            collection_id=full_collection_id,
            title=f"Fathom Global Flood Hazard Maps - {region_code.upper()}",
            description=(
                f"Consolidated flood hazard data for {region_code.upper()} from Fathom Global v3. "
                "Multi-band COGs with return periods (1in5 to 1in1000) as bands. "
                "Flood depth values in centimeters."
            ),
            summaries={
                "fathom:flood_type": list(set(r["flood_type"] for r in cog_results)),
                "fathom:defense_status": list(set(r["defense_status"] for r in cog_results)),
                "fathom:year": list(set(r["year"] for r in cog_results)),
                "fathom:ssp_scenario": [s for s in set(r.get("ssp_scenario") for r in cog_results) if s]
            },
            license="proprietary",
            extent={
                "spatial": {"bbox": [collection_bounds]},
                "temporal": {"interval": [["2020-01-01T00:00:00Z", "2080-12-31T23:59:59Z"]]}
            },
            keywords=["flood", "hazard", "fathom", "climate", region_code]
        )
        if result.get("success"):
            logger.info(f"   ✅ Collection created")
        else:
            logger.warning(f"   ⚠️ Collection creation: {result}")

    # Create STAC items (matching fathom_stac_register pattern)
    items_created = 0
    items_skipped = 0
    storage_base = f"/vsiaz/{container}"

    # TiTiler setup for visualization links
    import urllib.parse
    titiler_base = config.titiler_base_url.rstrip('/')

    for cog_result in cog_results:
        output_blob = cog_result["output_blob"]
        output_name = cog_result["output_name"]
        bounds = cog_result["bounds"]

        item_id = output_name
        year = cog_result["year"]
        item_datetime = f"{year}-01-01T00:00:00Z"

        asset_href = f"{storage_base}/{output_blob}"
        bbox = [bounds["west"], bounds["south"], bounds["east"], bounds["north"]]

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

        # Check if item already exists
        if stac_repo.item_exists(item_id, full_collection_id):
            items_skipped += 1
            continue

        # Build eo:bands metadata (matching fathom_stac_register)
        eo_bands = []
        for rp in RETURN_PERIODS:
            eo_bands.append({
                "name": rp,
                "description": f"Flood depth for {rp.replace('in', '-in-')} year return period (cm)"
            })

        # Build STAC item (consistent with fathom_stac_register)
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
                "fathom:defense_status": cog_result["defense_status"],
                "fathom:year": year,
                "fathom:ssp_scenario": cog_result.get("ssp_scenario"),
                "fathom:depth_unit": "cm",
                "fathom:grid_cell": cog_result["grid_cell"],
                "eo:bands": eo_bands
            },
            "assets": {
                "data": {
                    "href": asset_href,
                    "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                    "title": f"Flood depth COG ({cog_result['flood_type']} {cog_result['defense_status']})",
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

        # Add TiTiler visualization links (consistent with fathom_stac_register)
        # 8-band COGs need bidx parameter; default to band 5 (1-in-100 year return period)
        vsiaz_encoded = urllib.parse.quote(asset_href, safe='')
        viz_params = "bidx=5&rescale=0,300&colormap_name=blues"

        item["links"].extend([
            {
                "rel": "preview",
                "href": f"{titiler_base}/cog/WebMercatorQuad/map.html?url={vsiaz_encoded}&{viz_params}",
                "type": "text/html",
                "title": "Interactive map viewer (TiTiler) - 1-in-100 year flood"
            },
            {
                "rel": "tilejson",
                "href": f"{titiler_base}/cog/WebMercatorQuad/tilejson.json?url={vsiaz_encoded}&{viz_params}",
                "type": "application/json",
                "title": "TileJSON specification"
            }
        ])

        # Add thumbnail asset
        item["assets"]["thumbnail"] = {
            "href": f"{titiler_base}/cog/preview.png?url={vsiaz_encoded}&max_size=256&{viz_params}",
            "type": "image/png",
            "roles": ["thumbnail"],
            "title": "Preview thumbnail (1-in-100 year flood depth)"
        }

        try:
            stac_repo.insert_item(item, full_collection_id)
            items_created += 1
        except Exception as e:
            logger.warning(f"   ⚠️ Failed to create item {item_id}: {e}")

    logger.info(f"✅ STAC rebuild complete: {items_created} created, {items_skipped} skipped (already exist)")

    return {
        "success": True,
        "result": {
            "collection_id": full_collection_id,
            "cogs_found": len(blobs),
            "cogs_parsed": len(cog_results),
            "items_created": items_created,
            "items_skipped": items_skipped,
            "stac_catalog_url": f"{config.etl_app_base_url}/api/stac/collections/{full_collection_id}"
        }
    }
