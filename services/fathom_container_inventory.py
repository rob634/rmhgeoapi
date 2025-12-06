"""
Fathom Container Inventory Handlers.

Handlers for scanning blob storage and populating the etl_fathom tracking table.

Handler Functions:
    fathom_generate_scan_prefixes: Generate prefixes for parallel scanning
    fathom_scan_prefix: Scan blobs by prefix and batch insert to database
    fathom_assign_grid_cells: Calculate grid cell assignments
    fathom_inventory_summary: Generate statistics summary
"""

import re
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

from infrastructure.blob import BlobRepository
from infrastructure.postgresql import PostgreSQLRepository
from psycopg import sql
from config import FathomDefaults

logger = logging.getLogger(__name__)

# Track if table has been ensured this session (avoid repeated checks)
_table_ensured = False


# ============================================================================
# Database Table Creation (Self-Contained)
# ============================================================================

def _ensure_etl_fathom_table() -> bool:
    """
    Ensure app.etl_fathom table exists, creating it if necessary.

    This allows the Fathom ETL jobs to be self-contained without requiring
    a full schema rebuild. Uses CREATE TABLE IF NOT EXISTS for idempotency.

    Returns:
        True if table exists (created or already existed)
    """
    global _table_ensured
    if _table_ensured:
        return True

    logger.info("🔧 Ensuring app.etl_fathom table exists...")

    repo = PostgreSQLRepository()

    create_table_sql = """
    CREATE TABLE IF NOT EXISTS app.etl_fathom (
        -- Primary Key
        id SERIAL PRIMARY KEY,

        -- Source file identification
        source_blob_path VARCHAR(512) NOT NULL,
        source_container VARCHAR(64) NOT NULL DEFAULT 'bronze-fathom',
        file_size_bytes BIGINT,

        -- Parsed metadata from blob path
        flood_type VARCHAR(20) NOT NULL,
        defense VARCHAR(20) NOT NULL,
        year INTEGER NOT NULL,
        ssp VARCHAR(10),
        return_period VARCHAR(10) NOT NULL,
        tile VARCHAR(20) NOT NULL,

        -- Phase 1 (Band Stacking) tracking
        phase1_group_key VARCHAR(100),
        phase1_output_blob VARCHAR(512),
        phase1_job_id VARCHAR(64),
        phase1_processed_at TIMESTAMPTZ,

        -- Phase 2 (Spatial Merge) tracking
        grid_cell VARCHAR(30),
        phase2_group_key VARCHAR(100),
        phase2_output_blob VARCHAR(512),
        phase2_job_id VARCHAR(64),
        phase2_processed_at TIMESTAMPTZ,

        -- Timestamps
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),

        -- Constraints
        CONSTRAINT etl_fathom_source_blob_path_unique UNIQUE (source_blob_path)
    );

    -- Create indexes for common queries (IF NOT EXISTS for idempotency)
    CREATE INDEX IF NOT EXISTS idx_etl_fathom_tile ON app.etl_fathom(tile);
    CREATE INDEX IF NOT EXISTS idx_etl_fathom_phase1_group ON app.etl_fathom(phase1_group_key);
    CREATE INDEX IF NOT EXISTS idx_etl_fathom_phase2_group ON app.etl_fathom(phase2_group_key);
    CREATE INDEX IF NOT EXISTS idx_etl_fathom_flood_type ON app.etl_fathom(flood_type, defense);
    CREATE INDEX IF NOT EXISTS idx_etl_fathom_year_ssp ON app.etl_fathom(year, ssp);

    -- Partial indexes for finding unprocessed records
    CREATE INDEX IF NOT EXISTS idx_etl_fathom_p1_pending ON app.etl_fathom(phase1_group_key)
        WHERE phase1_processed_at IS NULL;
    CREATE INDEX IF NOT EXISTS idx_etl_fathom_p2_pending ON app.etl_fathom(phase2_group_key)
        WHERE phase1_processed_at IS NOT NULL AND phase2_processed_at IS NULL;
    """

    try:
        with repo.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(create_table_sql)
                conn.commit()

        _table_ensured = True
        logger.info("✅ app.etl_fathom table ready")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to create etl_fathom table: {e}")
        raise


# ============================================================================
# Flood Type and SSP Mappings
# ============================================================================

FLOOD_TYPE_MAP = {
    "COASTAL_DEFENDED": {"flood_type": "coastal", "defense": "defended"},
    "COASTAL_UNDEFENDED": {"flood_type": "coastal", "defense": "undefended"},
    "FLUVIAL_DEFENDED": {"flood_type": "fluvial", "defense": "defended"},
    "FLUVIAL_UNDEFENDED": {"flood_type": "fluvial", "defense": "undefended"},
    "PLUVIAL_DEFENDED": {"flood_type": "pluvial", "defense": "defended"}
}

SSP_MAP = {
    "SSP1_2.6": "ssp126",
    "SSP2_4.5": "ssp245",
    "SSP3_7.0": "ssp370",
    "SSP5_8.5": "ssp585"
}

ALL_FLOOD_TYPES = list(FLOOD_TYPE_MAP.keys())
ALL_YEARS = [2020, 2030, 2050, 2080]
ALL_SSPS = list(SSP_MAP.keys())


# ============================================================================
# Handler 1: Generate Scan Prefixes
# ============================================================================

def fathom_generate_scan_prefixes(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate list of blob prefixes to scan in parallel.

    Creates prefixes for each combination of flood_type/year/[ssp]/
    to enable parallel container scanning.

    Present-day (2020): FLOOD_TYPE/2020/
    Future projections: FLOOD_TYPE/YEAR/SSP/

    Args:
        params: {
            source_container: Container name (default: bronze-fathom)
            flood_types: List of flood types to include (default: all)
            years: List of years to include (default: all)
            ssp_scenarios: List of SSP scenarios (default: all)
            dry_run: If True, log only
        }

    Returns:
        {success: True, result: {prefixes: [...], count: N}}
    """
    source_container = params.get("source_container", FathomDefaults.SOURCE_CONTAINER)
    flood_types = params.get("flood_types") or ALL_FLOOD_TYPES
    years = params.get("years") or ALL_YEARS
    ssp_scenarios = params.get("ssp_scenarios") or ALL_SSPS
    dry_run = params.get("dry_run", False)

    logger.info(f"📋 Generating scan prefixes for {source_container}")
    logger.info(f"   Flood types: {flood_types}")
    logger.info(f"   Years: {years}")
    logger.info(f"   SSP scenarios: {ssp_scenarios}")

    prefixes = []

    for flood_type in flood_types:
        if flood_type not in FLOOD_TYPE_MAP:
            logger.warning(f"⚠️ Unknown flood type: {flood_type}, skipping")
            continue

        for year in years:
            if year == 2020:
                # Present-day: no SSP folder
                # Prefix: FLOOD_TYPE/2020/
                prefix = f"{flood_type}/{year}/"
                prefixes.append(prefix)
            else:
                # Future projections: include SSP
                # Prefix: FLOOD_TYPE/YEAR/SSP/
                for ssp in ssp_scenarios:
                    prefix = f"{flood_type}/{year}/{ssp}/"
                    prefixes.append(prefix)

    logger.info(f"✅ Generated {len(prefixes)} scan prefixes")

    if dry_run:
        logger.info("🔍 DRY RUN - Prefix list generated but no scanning will occur")

    return {
        "success": True,
        "result": {
            "prefixes": prefixes,
            "count": len(prefixes),
            "source_container": source_container,
            "dry_run": dry_run
        }
    }


# ============================================================================
# Handler 2: Scan Prefix and Insert to Database
# ============================================================================

def fathom_scan_prefix(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Scan blobs under a prefix and batch insert to etl_fathom table.

    Lists all blobs with the given prefix, parses metadata from paths,
    and inserts records in batches using ON CONFLICT DO UPDATE.

    Args:
        params: {
            prefix: Blob prefix to scan (e.g., "COASTAL_DEFENDED/2020/")
            source_container: Container name
            batch_size: Number of records per INSERT (default: 1000)
            dry_run: If True, count but don't insert
        }

    Returns:
        {success: True, result: {prefix: ..., files_found: N, records_inserted: N}}
    """
    prefix = params.get("prefix")
    source_container = params.get("source_container", FathomDefaults.SOURCE_CONTAINER)
    batch_size = params.get("batch_size", 1000)
    dry_run = params.get("dry_run", False)

    if not prefix:
        return {"success": False, "error": "Missing required parameter: prefix"}

    logger.info(f"🔍 Scanning prefix: {prefix}")

    # Ensure table exists before inserting (self-contained, no schema rebuild needed)
    _ensure_etl_fathom_table()

    # Get blob repository
    blob_repo = BlobRepository.instance()

    # List all blobs with this prefix
    blobs = blob_repo.list_blobs(source_container, prefix=prefix)

    # Parse each blob and collect records
    records = []
    parse_errors = 0

    for blob in blobs:
        blob_name = blob["name"] if isinstance(blob, dict) else blob

        # Skip non-TIF files
        if not blob_name.lower().endswith(".tif"):
            continue

        # Parse the blob path
        parsed = _parse_fathom_blob_path(blob_name)
        if not parsed:
            parse_errors += 1
            continue

        # Add file size if available
        file_size = blob.get("size") if isinstance(blob, dict) else None

        records.append({
            "source_blob_path": blob_name,
            "source_container": source_container,
            "file_size_bytes": file_size,
            "flood_type": parsed["flood_type"],
            "defense": parsed["defense"],
            "year": parsed["year"],
            "ssp": parsed["ssp"],
            "return_period": parsed["return_period"],
            "tile": parsed["tile"],
            "phase1_group_key": parsed["phase1_group_key"]
        })

    logger.info(f"   Found {len(records)} TIF files, {parse_errors} parse errors")

    if dry_run:
        logger.info("🔍 DRY RUN - Files counted but not inserted")
        return {
            "success": True,
            "result": {
                "prefix": prefix,
                "files_found": len(records),
                "records_inserted": 0,
                "parse_errors": parse_errors,
                "dry_run": True
            }
        }

    # Insert records in batches
    records_inserted = 0
    if records:
        records_inserted = _batch_insert_etl_records(records, batch_size)

    logger.info(f"✅ Inserted {records_inserted} records from prefix {prefix}")

    return {
        "success": True,
        "result": {
            "prefix": prefix,
            "files_found": len(records),
            "records_inserted": records_inserted,
            "parse_errors": parse_errors,
            "dry_run": False
        }
    }


def _parse_fathom_blob_path(path: str) -> Optional[Dict[str, Any]]:
    """
    Parse Fathom blob path to extract metadata.

    Paths:
    - Present-day: FLOOD_TYPE/YEAR/RETURN_PERIOD/filename_TILE.tif
    - Future: FLOOD_TYPE/YEAR/SSP/RETURN_PERIOD/filename_TILE.tif

    Returns:
        Dict with flood_type, defense, year, ssp, return_period, tile, phase1_group_key
    """
    try:
        parts = path.split("/")

        if len(parts) < 4:
            return None

        flood_type_raw = parts[0]
        if flood_type_raw not in FLOOD_TYPE_MAP:
            return None

        year = int(parts[1])
        filename = parts[-1]

        # Determine if SSP is present (5 parts) or not (4 parts)
        if len(parts) == 4:
            # Present-day: FLOOD_TYPE/YEAR/RETURN_PERIOD/filename
            return_period = parts[2]
            ssp_raw = None
            ssp = None
        elif len(parts) == 5:
            # Future: FLOOD_TYPE/YEAR/SSP/RETURN_PERIOD/filename
            ssp_raw = parts[2]
            return_period = parts[3]
            ssp = SSP_MAP.get(ssp_raw)
        else:
            return None

        # Validate return period format
        if not return_period.startswith("1in"):
            return None

        # Extract tile coordinate from filename
        tile_match = re.search(r"_([ns]\d+[ew]\d+)\.tif$", filename, re.IGNORECASE)
        if not tile_match:
            return None
        tile = tile_match.group(1).lower()

        # Get normalized flood type and defense
        ft_info = FLOOD_TYPE_MAP[flood_type_raw]
        flood_type = ft_info["flood_type"]
        defense = ft_info["defense"]

        # Compute phase1_group_key
        base_key = f"{tile}_{flood_type}-{defense}_{year}"
        phase1_group_key = f"{base_key}_{ssp}" if ssp else base_key

        return {
            "flood_type": flood_type,
            "defense": defense,
            "year": year,
            "ssp": ssp,
            "return_period": return_period,
            "tile": tile,
            "phase1_group_key": phase1_group_key
        }

    except Exception as e:
        logger.debug(f"Parse error for path {path}: {e}")
        return None


def _batch_insert_etl_records(records: List[Dict[str, Any]], batch_size: int) -> int:
    """
    Batch insert records into app.etl_fathom table.

    Uses ON CONFLICT DO UPDATE for idempotency.
    """
    if not records:
        return 0

    repo = PostgreSQLRepository()
    inserted = 0

    # Process in batches
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]

        try:
            with repo.get_connection() as conn:
                with conn.cursor() as cur:
                    # Build batch INSERT with ON CONFLICT
                    for record in batch:
                        cur.execute(
                            sql.SQL("""
                                INSERT INTO {schema}.etl_fathom (
                                    source_blob_path, source_container, file_size_bytes,
                                    flood_type, defense, year, ssp, return_period, tile,
                                    phase1_group_key, created_at, updated_at
                                ) VALUES (
                                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                                )
                                ON CONFLICT (source_blob_path) DO UPDATE SET
                                    file_size_bytes = EXCLUDED.file_size_bytes,
                                    updated_at = NOW()
                            """).format(schema=sql.Identifier("app")),
                            (
                                record["source_blob_path"],
                                record["source_container"],
                                record["file_size_bytes"],
                                record["flood_type"],
                                record["defense"],
                                record["year"],
                                record["ssp"],
                                record["return_period"],
                                record["tile"],
                                record["phase1_group_key"]
                            )
                        )

                    conn.commit()
                    inserted += len(batch)

        except Exception as e:
            logger.error(f"❌ Batch insert error: {e}")
            raise

    return inserted


# ============================================================================
# Handler 3: Assign Grid Cells
# ============================================================================

def fathom_assign_grid_cells(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate and assign grid cells for phase 2 grouping.

    Updates all etl_fathom records with their grid_cell and phase2_group_key
    based on tile coordinates.

    Args:
        params: {
            grid_size: Grid cell size in degrees (default: 5)
            dry_run: If True, count but don't update
        }

    Returns:
        {success: True, result: {records_updated: N}}
    """
    grid_size = params.get("grid_size", 5)
    dry_run = params.get("dry_run", False)

    logger.info(f"📐 Assigning grid cells (size: {grid_size}°)")

    if dry_run:
        # Count records needing grid assignment
        repo = PostgreSQLRepository()
        with repo.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT COUNT(*) FROM {schema}.etl_fathom WHERE grid_cell IS NULL").format(
                        schema=sql.Identifier("app")
                    )
                )
                count = cur.fetchone()[0]

        logger.info(f"🔍 DRY RUN - {count} records would be updated")
        return {
            "success": True,
            "result": {
                "records_needing_update": count,
                "records_updated": 0,
                "dry_run": True
            }
        }

    # Update all records with grid_cell and phase2_group_key
    # Grid cell format: nXX-nYY_wZZ-wAA (e.g., n00-n05_w010-w005)
    repo = PostgreSQLRepository()

    with repo.get_connection() as conn:
        with conn.cursor() as cur:
            # Use SQL function to calculate grid cell from tile
            cur.execute(sql.SQL("""
                UPDATE {schema}.etl_fathom
                SET
                    grid_cell = (
                        -- Calculate grid cell from tile coordinate
                        -- tile format: n04w006 (lat direction + lat + lon direction + lon)
                        CASE
                            WHEN tile ~ '^[ns]\\d+[ew]\\d+$' THEN
                                -- Extract lat/lon, calculate grid bounds
                                (
                                    SELECT
                                        lat_dir || lpad(floor(lat::int / %s)::int * %s, 2, '0') || '-' ||
                                        lat_dir || lpad((floor(lat::int / %s)::int + 1) * %s, 2, '0') || '_' ||
                                        lon_dir || lpad(floor(lon::int / %s)::int * %s, 3, '0') || '-' ||
                                        lon_dir || lpad((floor(lon::int / %s)::int + 1) * %s, 3, '0')
                                    FROM (
                                        SELECT
                                            substring(tile from 1 for 1) as lat_dir,
                                            substring(tile from 2 for 2)::int as lat,
                                            substring(tile from 4 for 1) as lon_dir,
                                            substring(tile from 5)::int as lon
                                    ) parsed
                                )
                            ELSE NULL
                        END
                    ),
                    phase2_group_key = grid_cell || '_' || flood_type || '-' || defense || '_' || year || COALESCE('_' || ssp, ''),
                    updated_at = NOW()
                WHERE grid_cell IS NULL
            """).format(schema=sql.Identifier("app")),
                        (grid_size, grid_size, grid_size, grid_size, grid_size, grid_size, grid_size, grid_size))

            updated = cur.rowcount
            conn.commit()

    logger.info(f"✅ Updated {updated} records with grid cells")

    return {
        "success": True,
        "result": {
            "records_updated": updated,
            "grid_size": grid_size,
            "dry_run": False
        }
    }


# ============================================================================
# Handler 4: Generate Inventory Summary
# ============================================================================

def fathom_inventory_summary(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate summary statistics of the inventory.

    Args:
        params: {
            source_container: Container name
            dry_run: If True, indicate this was a dry run
        }

    Returns:
        {success: True, result: {total_files: N, by_flood_type: {...}, ...}}
    """
    source_container = params.get("source_container", FathomDefaults.SOURCE_CONTAINER)
    dry_run = params.get("dry_run", False)

    logger.info(f"📊 Generating inventory summary for {source_container}")

    repo = PostgreSQLRepository()

    with repo.get_connection() as conn:
        with conn.cursor() as cur:
            # Total files
            cur.execute(sql.SQL("SELECT COUNT(*) FROM {schema}.etl_fathom").format(
                schema=sql.Identifier("app")
            ))
            total_files = cur.fetchone()[0]

            # Unique tiles
            cur.execute(sql.SQL("SELECT COUNT(DISTINCT tile) FROM {schema}.etl_fathom").format(
                schema=sql.Identifier("app")
            ))
            unique_tiles = cur.fetchone()[0]

            # Unique phase1 groups
            cur.execute(sql.SQL("SELECT COUNT(DISTINCT phase1_group_key) FROM {schema}.etl_fathom").format(
                schema=sql.Identifier("app")
            ))
            phase1_groups = cur.fetchone()[0]

            # Unique phase2 groups
            cur.execute(sql.SQL("SELECT COUNT(DISTINCT phase2_group_key) FROM {schema}.etl_fathom WHERE phase2_group_key IS NOT NULL").format(
                schema=sql.Identifier("app")
            ))
            phase2_groups = cur.fetchone()[0]

            # By flood type
            cur.execute(sql.SQL("""
                SELECT flood_type, defense, COUNT(*)
                FROM {schema}.etl_fathom
                GROUP BY flood_type, defense
                ORDER BY flood_type, defense
            """).format(schema=sql.Identifier("app")))
            by_flood_type = {f"{row[0]}_{row[1]}": row[2] for row in cur.fetchall()}

            # By year
            cur.execute(sql.SQL("""
                SELECT year, COUNT(*)
                FROM {schema}.etl_fathom
                GROUP BY year
                ORDER BY year
            """).format(schema=sql.Identifier("app")))
            by_year = {str(row[0]): row[1] for row in cur.fetchall()}

            # Total file size
            cur.execute(sql.SQL("""
                SELECT COALESCE(SUM(file_size_bytes), 0)
                FROM {schema}.etl_fathom
            """).format(schema=sql.Identifier("app")))
            total_size_bytes = cur.fetchone()[0]

    summary = {
        "total_files": total_files,
        "unique_tiles": unique_tiles,
        "phase1_groups": phase1_groups,
        "phase2_groups": phase2_groups,
        "by_flood_type": by_flood_type,
        "by_year": by_year,
        "total_size_bytes": total_size_bytes,
        "total_size_gb": round(total_size_bytes / (1024**3), 2) if total_size_bytes else 0,
        "source_container": source_container,
        "dry_run": dry_run
    }

    logger.info(f"✅ Inventory summary: {total_files} files, {unique_tiles} tiles, {phase1_groups} phase1 groups")

    return {
        "success": True,
        "result": summary
    }


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    "fathom_generate_scan_prefixes",
    "fathom_scan_prefix",
    "fathom_assign_grid_cells",
    "fathom_inventory_summary"
]
