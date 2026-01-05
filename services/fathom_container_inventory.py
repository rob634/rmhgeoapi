# ============================================================================
# FATHOM CONTAINER INVENTORY HANDLERS
# ============================================================================
# STATUS: Services - Blob scanning and etl_source_files population for Fathom
# PURPOSE: Generate scan prefixes, scan blobs, assign grid cells, summarize
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Fathom Container Inventory Handlers.

Handlers for scanning blob storage and populating the app.etl_source_files
tracking table with etl_type='fathom'.

Handler Functions:
    fathom_generate_scan_prefixes: Generate prefixes for parallel scanning
    fathom_scan_prefix: Scan blobs by prefix and batch insert to database
    fathom_assign_grid_cells: Calculate grid cell assignments
    fathom_inventory_summary: Generate statistics summary

NOTE (21 DEC 2025): Migrated from FATHOM-specific etl_fathom table to
general-purpose etl_source_files table with JSONB metadata.
"""

import re
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

from infrastructure.blob import BlobRepository
from infrastructure.postgresql import PostgreSQLRepository
from psycopg import sql
from config import FathomDefaults

logger = logging.getLogger(__name__)


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

    Present-day (2020): [base_prefix/]FLOOD_TYPE/2020/
    Future projections: [base_prefix/]FLOOD_TYPE/YEAR/SSP/

    Args:
        params: {
            source_container: Container name (default: bronze-fathom)
            base_prefix: Optional country/region prefix (e.g., "rwa" for Rwanda)
            flood_types: List of flood types to include (default: all)
            years: List of years to include (default: all)
            ssp_scenarios: List of SSP scenarios (default: all)
            dry_run: If True, log only
        }

    Returns:
        {success: True, result: {prefixes: [...], count: N}}
    """
    source_container = params.get("source_container", FathomDefaults.SOURCE_CONTAINER)
    base_prefix = params.get("base_prefix", "")  # e.g., "rwa" for Rwanda
    flood_types = params.get("flood_types") or ALL_FLOOD_TYPES
    years = params.get("years") or ALL_YEARS
    ssp_scenarios = params.get("ssp_scenarios") or ALL_SSPS
    dry_run = params.get("dry_run", False)

    # Normalize base_prefix (add trailing slash if present, remove if empty)
    if base_prefix:
        base_prefix = base_prefix.rstrip("/") + "/"

    logger.info(f"📋 Generating scan prefixes for {source_container}")
    if base_prefix:
        logger.info(f"   Base prefix: {base_prefix}")
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
                # Prefix: [base_prefix/]FLOOD_TYPE/2020/
                prefix = f"{base_prefix}{flood_type}/{year}/"
                prefixes.append(prefix)
            else:
                # Future projections: include SSP
                # Prefix: [base_prefix/]FLOOD_TYPE/YEAR/SSP/
                for ssp in ssp_scenarios:
                    prefix = f"{base_prefix}{flood_type}/{year}/{ssp}/"
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
            "base_prefix": base_prefix.rstrip("/") if base_prefix else None,
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

    # NOTE: Table app.etl_source_files is created by schema deployment (IaC)
    # No ad-hoc table creation - use POST /api/dbadmin/maintenance/full-rebuild

    # Get blob repository for bronze zone (source data)
    blob_repo = BlobRepository.for_zone("bronze")

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

    Paths (with optional country prefix):
    - Present-day: [country/]FLOOD_TYPE/YEAR/RETURN_PERIOD/filename_TILE.tif
    - Future: [country/]FLOOD_TYPE/YEAR/SSP/RETURN_PERIOD/filename_TILE.tif

    Examples:
        COASTAL_DEFENDED/2020/1in100/... (CI at root)
        rwa/FLUVIAL_DEFENDED/2020/1in100/... (RWA with prefix)

    Returns:
        Dict with flood_type, defense, year, ssp, return_period, tile, phase1_group_key
    """
    try:
        parts = path.split("/")

        if len(parts) < 4:
            return None

        # Check if first part is a flood type or a country prefix
        flood_type_raw = parts[0]
        offset = 0

        if flood_type_raw not in FLOOD_TYPE_MAP:
            # First part might be country prefix (e.g., "rwa", "ci")
            # Try next part
            if len(parts) < 5:
                return None
            flood_type_raw = parts[1]
            offset = 1
            if flood_type_raw not in FLOOD_TYPE_MAP:
                return None

        year = int(parts[1 + offset])
        filename = parts[-1]

        # Determine if SSP is present based on adjusted part count
        effective_parts = len(parts) - offset
        if effective_parts == 4:
            # Present-day: FLOOD_TYPE/YEAR/RETURN_PERIOD/filename
            return_period = parts[2 + offset]
            ssp_raw = None
            ssp = None
        elif effective_parts == 5:
            # Future: FLOOD_TYPE/YEAR/SSP/RETURN_PERIOD/filename
            ssp_raw = parts[2 + offset]
            return_period = parts[3 + offset]
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
    Batch insert records into app.etl_source_files table.

    Uses etl_type='fathom' namespace and source_metadata JSONB for parsed fields.
    ON CONFLICT on (etl_type, source_blob_path) for idempotency.
    """
    if not records:
        return 0

    repo = PostgreSQLRepository()
    inserted = 0

    # Process in batches
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]

        try:
            with repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Build batch INSERT with ON CONFLICT
                    for record in batch:
                        # Build source_metadata JSONB from parsed fields
                        source_metadata = {
                            "flood_type": record["flood_type"],
                            "defense": record["defense"],
                            "year": record["year"],
                            "ssp": record["ssp"],
                            "return_period": record["return_period"],
                            "tile": record["tile"]
                        }

                        cur.execute(
                            sql.SQL("""
                                INSERT INTO {schema}.etl_source_files (
                                    etl_type, source_blob_path, source_container,
                                    file_size_bytes, source_metadata, phase1_group_key,
                                    created_at, updated_at
                                ) VALUES (
                                    'fathom', %s, %s, %s, %s, %s, NOW(), NOW()
                                )
                                ON CONFLICT (etl_type, source_blob_path) DO UPDATE SET
                                    file_size_bytes = EXCLUDED.file_size_bytes,
                                    source_metadata = EXCLUDED.source_metadata,
                                    updated_at = NOW()
                            """).format(schema=sql.Identifier("app")),
                            (
                                record["source_blob_path"],
                                record["source_container"],
                                record["file_size_bytes"],
                                json.dumps(source_metadata),
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

    Updates all etl_source_files records (etl_type='fathom') with their grid_cell
    in source_metadata and phase2_group_key based on tile coordinates.

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
        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("""
                        SELECT COUNT(*) FROM {schema}.etl_source_files
                        WHERE etl_type = 'fathom'
                          AND (source_metadata->>'grid_cell') IS NULL
                    """).format(schema=sql.Identifier("app"))
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

    # Update all records with grid_cell in source_metadata and phase2_group_key
    # Grid cell format: nXX-nYY_wZZ-wAA (e.g., n00-n05_w010-w005)
    #
    # IMPORTANT: Split into two UPDATEs because PostgreSQL SET clause uses OLD values.
    repo = PostgreSQLRepository()

    with repo._get_connection() as conn:
        with conn.cursor() as cur:
            # Step 1: Calculate and set grid_cell in source_metadata from tile
            # tile is stored in source_metadata->>'tile'
            cur.execute(sql.SQL("""
                UPDATE {schema}.etl_source_files
                SET
                    source_metadata = jsonb_set(
                        source_metadata,
                        '{{grid_cell}}',
                        to_jsonb(
                            CASE
                                WHEN (source_metadata->>'tile') ~ '^[ns]\\d+[ew]\\d+$' THEN
                                    (
                                        SELECT
                                            lat_dir || lpad((floor(lat::int / %s)::int * %s)::text, 2, '0') || '-' ||
                                            lat_dir || lpad(((floor(lat::int / %s)::int + 1) * %s)::text, 2, '0') || '_' ||
                                            lon_dir || lpad((floor(lon::int / %s)::int * %s)::text, 3, '0') || '-' ||
                                            lon_dir || lpad(((floor(lon::int / %s)::int + 1) * %s)::text, 3, '0')
                                        FROM (
                                            SELECT
                                                substring(source_metadata->>'tile' from 1 for 1) as lat_dir,
                                                substring(source_metadata->>'tile' from 2 for 2)::int as lat,
                                                substring(source_metadata->>'tile' from 4 for 1) as lon_dir,
                                                substring(source_metadata->>'tile' from 5)::int as lon
                                        ) parsed
                                    )
                                ELSE NULL
                            END
                        )
                    ),
                    updated_at = NOW()
                WHERE etl_type = 'fathom'
                  AND (source_metadata->>'grid_cell') IS NULL
            """).format(schema=sql.Identifier("app")),
                        (grid_size, grid_size, grid_size, grid_size, grid_size, grid_size, grid_size, grid_size))

            grid_cell_updated = cur.rowcount
            logger.info(f"   Step 1: Set grid_cell for {grid_cell_updated} records")

            # Step 2: Calculate phase2_group_key using source_metadata fields
            # Format: {flood_type}-{defense}-{year}[-{ssp}]-{grid_cell}
            # Example: fluvial-defended-2020-n00-n05_w005-w010
            cur.execute(sql.SQL("""
                UPDATE {schema}.etl_source_files
                SET
                    phase2_group_key = (source_metadata->>'flood_type') || '-' ||
                                       (source_metadata->>'defense') || '-' ||
                                       (source_metadata->>'year') ||
                                       COALESCE('-' || (source_metadata->>'ssp'), '') || '-' ||
                                       (source_metadata->>'grid_cell'),
                    updated_at = NOW()
                WHERE etl_type = 'fathom'
                  AND (source_metadata->>'grid_cell') IS NOT NULL
                  AND phase2_group_key IS NULL
            """).format(schema=sql.Identifier("app")))

            phase2_key_updated = cur.rowcount
            logger.info(f"   Step 2: Set phase2_group_key for {phase2_key_updated} records")

            conn.commit()

    logger.info(f"✅ Updated {grid_cell_updated} records with grid cells")

    return {
        "success": True,
        "result": {
            "records_updated": grid_cell_updated,
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

    Queries app.etl_source_files with etl_type='fathom'.

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

    try:
        repo = PostgreSQLRepository()

        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Total files
                cur.execute(sql.SQL("""
                    SELECT COUNT(*) as cnt FROM {schema}.etl_source_files
                    WHERE etl_type = 'fathom'
                """).format(schema=sql.Identifier("app")))
                total_files = cur.fetchone()["cnt"]

                # Unique tiles (from source_metadata JSONB)
                cur.execute(sql.SQL("""
                    SELECT COUNT(DISTINCT source_metadata->>'tile') as cnt
                    FROM {schema}.etl_source_files
                    WHERE etl_type = 'fathom'
                """).format(schema=sql.Identifier("app")))
                unique_tiles = cur.fetchone()["cnt"]

                # Unique phase1 groups
                cur.execute(sql.SQL("""
                    SELECT COUNT(DISTINCT phase1_group_key) as cnt
                    FROM {schema}.etl_source_files
                    WHERE etl_type = 'fathom'
                """).format(schema=sql.Identifier("app")))
                phase1_groups = cur.fetchone()["cnt"]

                # Unique phase2 groups
                cur.execute(sql.SQL("""
                    SELECT COUNT(DISTINCT phase2_group_key) as cnt
                    FROM {schema}.etl_source_files
                    WHERE etl_type = 'fathom' AND phase2_group_key IS NOT NULL
                """).format(schema=sql.Identifier("app")))
                phase2_groups = cur.fetchone()["cnt"]

                # By flood type (from source_metadata JSONB)
                cur.execute(sql.SQL("""
                    SELECT source_metadata->>'flood_type' as flood_type,
                           source_metadata->>'defense' as defense,
                           COUNT(*) as cnt
                    FROM {schema}.etl_source_files
                    WHERE etl_type = 'fathom'
                    GROUP BY source_metadata->>'flood_type', source_metadata->>'defense'
                    ORDER BY 1, 2
                """).format(schema=sql.Identifier("app")))
                by_flood_type = {f"{row['flood_type']}_{row['defense']}": row['cnt'] for row in cur.fetchall()}

                # By year (from source_metadata JSONB)
                cur.execute(sql.SQL("""
                    SELECT source_metadata->>'year' as year, COUNT(*) as cnt
                    FROM {schema}.etl_source_files
                    WHERE etl_type = 'fathom'
                    GROUP BY source_metadata->>'year'
                    ORDER BY 1
                """).format(schema=sql.Identifier("app")))
                by_year = {str(row['year']): row['cnt'] for row in cur.fetchall()}

                # Total file size
                cur.execute(sql.SQL("""
                    SELECT COALESCE(SUM(file_size_bytes), 0) as total_bytes
                    FROM {schema}.etl_source_files
                    WHERE etl_type = 'fathom'
                """).format(schema=sql.Identifier("app")))
                total_size_bytes = cur.fetchone()["total_bytes"]

        # Handle potential Decimal type from SUM
        if total_size_bytes is not None:
            total_size_bytes = int(total_size_bytes)

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

    except Exception as e:
        logger.error(f"❌ SUMMARY ERROR: {type(e).__name__}: {e}")
        raise  # Re-raise to let CoreMachine handle it


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    "fathom_generate_scan_prefixes",
    "fathom_scan_prefix",
    "fathom_assign_grid_cells",
    "fathom_inventory_summary"
]
