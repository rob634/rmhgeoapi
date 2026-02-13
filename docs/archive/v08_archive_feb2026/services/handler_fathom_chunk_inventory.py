# ============================================================================
# CLAUDE CONTEXT - FATHOM CHUNK INVENTORY HANDLER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Handler - Stage 1 of process_fathom_docker job
# PURPOSE: Create work chunks and pre-create STAC collections
# LAST_REVIEWED: 24 JAN 2026
# EXPORTS: fathom_chunk_inventory
# DEPENDENCIES: infrastructure.postgresql, infrastructure.pgstac_bootstrap
# ============================================================================
"""
FATHOM Chunk Inventory Handler - Stage 1.

This handler runs on Azure Functions and performs:
    1. Determine scope (continent → regions or explicit list)
    2. Query database for tile counts per region
    3. Create work chunks based on strategy
    4. Pre-create STAC collections (eliminates race conditions in Stage 2)
    5. Return chunks for fan-out to Docker workers

Chunking Strategies:
    - region: One chunk per country (default)
    - grid_cell: One chunk per grid cell (finer granularity)
    - adaptive: Split large regions by grid cell, keep small ones whole

Collection Strategy:
    - One collection per region: fathom-flood-{region}
    - Collections are created in Stage 1 before any processing
    - Stage 2 chunks just upsert items into existing collections
"""

from typing import Dict, List, Any, Optional
from util_logger import LoggerFactory, ComponentType
from config.defaults import FathomDefaults

# Use continent mappings from FathomDefaults (single source of truth)
# Includes: africa, asia, europe, north_america, south_america, oceania
CONTINENT_REGIONS = FathomDefaults.CONTINENT_REGIONS.copy()

# Add 'global' = all continents combined
if 'global' not in CONTINENT_REGIONS:
    CONTINENT_REGIONS['global'] = []
    for regions in CONTINENT_REGIONS.values():
        if isinstance(regions, list):
            CONTINENT_REGIONS['global'].extend(regions)


def fathom_chunk_inventory(params: dict, context: dict = None) -> dict:
    """
    Create work chunks and pre-create STAC collections.

    Runs on: Azure Functions (fast, low memory)
    Duration: ~10-30 seconds

    Args:
        params: Task parameters containing:
            - job_id: Job identifier
            - job_parameters: Original job parameters with scope, filters, etc.

    Returns:
        dict with:
            - success: True if completed
            - result: Contains chunks list, collections created, etc.
    """
    from infrastructure import PostgreSQLRepository
    from infrastructure.pgstac_bootstrap import PgStacBootstrap

    logger = LoggerFactory.create_logger(
        ComponentType.SERVICE,
        "fathom_chunk_inventory"
    )

    job_id = params.get('job_id')
    job_params = params.get('job_parameters', {})

    logger.info(f"📋 FATHOM Chunk Inventory - Job: {job_id[:8] if job_id else 'N/A'}")

    # ═══════════════════════════════════════════════════════════════
    # STEP 1: Determine regions in scope
    # ═══════════════════════════════════════════════════════════════
    regions = _determine_regions(job_params, logger)

    if not regions:
        return {
            'success': False,
            'error': 'No regions determined from scope parameters'
        }

    logger.info(f"   Regions in scope: {len(regions)}")
    if len(regions) <= 10:
        logger.info(f"   Region list: {regions}")

    # ═══════════════════════════════════════════════════════════════
    # STEP 2: Query database for tile counts per region
    # ═══════════════════════════════════════════════════════════════
    tile_counts = _get_tile_counts_by_region(regions, job_params, logger)

    total_tiles = sum(tile_counts.values())
    logger.info(f"   Total pending tiles: {total_tiles}")

    if total_tiles == 0:
        logger.warning("   ⚠️ No pending tiles found - nothing to process")
        return {
            'success': True,
            'result': {
                'chunks': [],
                'total_chunks': 0,
                'total_estimated_tiles': 0,
                'collections_created': [],
                'regions_in_scope': regions,
                'message': 'No pending tiles found'
            }
        }

    # ═══════════════════════════════════════════════════════════════
    # STEP 3: Create chunks based on strategy
    # ═══════════════════════════════════════════════════════════════
    chunks = _create_chunks(
        tile_counts=tile_counts,
        job_params=job_params,
        logger=logger
    )

    logger.info(f"   Created {len(chunks)} chunks")

    # ═══════════════════════════════════════════════════════════════
    # STEP 4: Pre-create STAC collections
    # ═══════════════════════════════════════════════════════════════
    if job_params.get('dry_run'):
        logger.info("   🔍 DRY RUN - skipping collection creation")
        collections_created = []
    else:
        collections_created = _precreate_collections(
            chunks=chunks,
            job_params=job_params,
            logger=logger
        )

    # ═══════════════════════════════════════════════════════════════
    # STEP 5: Return result
    # ═══════════════════════════════════════════════════════════════
    regions_in_scope = list(set(chunk['region_code'] for chunk in chunks))

    result = {
        'chunks': chunks,
        'total_chunks': len(chunks),
        'total_estimated_tiles': sum(c.get('estimated_tiles', 0) for c in chunks),
        'collections_created': collections_created,
        'regions_in_scope': regions_in_scope,
        'tile_counts_by_region': tile_counts
    }

    logger.info(f"✅ Chunk inventory complete:")
    logger.info(f"   Chunks: {len(chunks)}")
    logger.info(f"   Collections created: {len(collections_created)}")
    logger.info(f"   Estimated tiles: {result['total_estimated_tiles']}")

    return {
        'success': True,
        'result': result
    }


def _determine_regions(job_params: dict, logger) -> List[str]:
    """Determine regions from scope parameters."""

    # Priority: continent > regions > region_code
    if job_params.get('continent'):
        continent = job_params['continent'].lower()
        if continent not in CONTINENT_REGIONS:
            raise ValueError(f"Unknown continent: {continent}")
        regions = CONTINENT_REGIONS[continent]
        logger.info(f"   Scope: continent={continent} ({len(regions)} regions)")
        return regions

    elif job_params.get('regions'):
        regions = [r.lower() for r in job_params['regions']]
        logger.info(f"   Scope: regions={regions}")
        return regions

    elif job_params.get('region_code'):
        region = job_params['region_code'].lower()
        logger.info(f"   Scope: region_code={region}")
        return [region]

    else:
        logger.error("   ❌ No scope specified")
        return []


def _get_tile_counts_by_region(
    regions: List[str],
    job_params: dict,
    logger
) -> Dict[str, int]:
    """Query database for pending tile counts per region."""
    from infrastructure import PostgreSQLRepository

    repo = PostgreSQLRepository()

    # Build filter clauses
    filter_clauses = ["etl_type = 'fathom'"]
    query_params = {}

    # Phase 1 pending or Phase 2 pending based on skip flags
    if job_params.get('skip_phase1'):
        # Phase 2 only: need Phase 1 completed, Phase 2 pending
        filter_clauses.append("phase1_completed_at IS NOT NULL")
        filter_clauses.append("phase2_completed_at IS NULL")
    else:
        # Full pipeline: need Phase 1 pending
        filter_clauses.append("phase1_completed_at IS NULL")

    # Region filter
    if regions:
        filter_clauses.append("source_metadata->>'region' = ANY(%(regions)s)")
        query_params['regions'] = regions

    # Additional filters
    if job_params.get('flood_types'):
        filter_clauses.append("source_metadata->>'flood_type' = ANY(%(flood_types)s)")
        query_params['flood_types'] = job_params['flood_types']

    if job_params.get('years'):
        filter_clauses.append("(source_metadata->>'year')::int = ANY(%(years)s)")
        query_params['years'] = job_params['years']

    if job_params.get('ssp_scenarios'):
        filter_clauses.append(
            "(source_metadata->>'ssp' = ANY(%(ssp)s) OR source_metadata->>'ssp' IS NULL)"
        )
        query_params['ssp'] = job_params['ssp_scenarios']

    where_clause = " AND ".join(filter_clauses)

    sql = f"""
        SELECT
            source_metadata->>'region' as region,
            COUNT(DISTINCT phase1_group_key) as tile_count
        FROM app.etl_source_files
        WHERE {where_clause}
        GROUP BY source_metadata->>'region'
        ORDER BY tile_count DESC
    """

    tile_counts = {}
    with repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, query_params)
            for row in cur.fetchall():
                if row['region']:
                    tile_counts[row['region'].lower()] = row['tile_count']

    logger.info(f"   Tile counts: {len(tile_counts)} regions with pending work")

    return tile_counts


def _create_chunks(
    tile_counts: Dict[str, int],
    job_params: dict,
    logger
) -> List[dict]:
    """Create work chunks based on strategy."""

    strategy = job_params.get('chunk_strategy', 'region')
    max_tiles = job_params.get('max_tiles_per_chunk', 500)
    grid_size = job_params.get('grid_size', 5)

    chunks = []

    for region, count in tile_counts.items():
        if count == 0:
            continue

        if strategy == 'region':
            # One chunk per region regardless of size
            chunks.append({
                'chunk_id': region,
                'region_code': region,
                'bbox': None,
                'estimated_tiles': count,
                'grid_size': grid_size
            })

        elif strategy == 'adaptive':
            # Split large regions by grid cell
            if count > max_tiles:
                logger.info(f"   Splitting {region} ({count} tiles > {max_tiles})")
                grid_chunks = _split_region_by_grid(region, grid_size, job_params, logger)
                chunks.extend(grid_chunks)
            else:
                chunks.append({
                    'chunk_id': region,
                    'region_code': region,
                    'bbox': None,
                    'estimated_tiles': count,
                    'grid_size': grid_size
                })

        elif strategy == 'grid_cell':
            # Always split by grid cell
            grid_chunks = _split_region_by_grid(region, grid_size, job_params, logger)
            chunks.extend(grid_chunks)

    # Sort by estimated tiles (largest first for better load balancing)
    chunks.sort(key=lambda c: c.get('estimated_tiles', 0), reverse=True)

    return chunks


def _split_region_by_grid(
    region: str,
    grid_size: int,
    job_params: dict,
    logger
) -> List[dict]:
    """Split a region into grid cell-based chunks."""
    from infrastructure import PostgreSQLRepository

    repo = PostgreSQLRepository()

    # Query for distinct grid cells in this region
    filter_clauses = [
        "etl_type = 'fathom'",
        "source_metadata->>'region' = %(region)s",
        "source_metadata->>'grid_cell' IS NOT NULL"
    ]
    query_params = {'region': region}

    if job_params.get('skip_phase1'):
        filter_clauses.append("phase1_completed_at IS NOT NULL")
        filter_clauses.append("phase2_completed_at IS NULL")
    else:
        filter_clauses.append("phase1_completed_at IS NULL")

    where_clause = " AND ".join(filter_clauses)

    sql = f"""
        SELECT
            source_metadata->>'grid_cell' as grid_cell,
            COUNT(DISTINCT phase1_group_key) as tile_count
        FROM app.etl_source_files
        WHERE {where_clause}
        GROUP BY source_metadata->>'grid_cell'
    """

    grid_chunks = []
    with repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, query_params)
            for row in cur.fetchall():
                grid_cell = row['grid_cell']
                if grid_cell:
                    # Parse grid cell to bbox
                    bbox = _parse_grid_cell_to_bbox(grid_cell)
                    grid_chunks.append({
                        'chunk_id': f"{region}-{grid_cell}",
                        'region_code': region,
                        'grid_cell': grid_cell,
                        'bbox': bbox,
                        'estimated_tiles': row['tile_count'],
                        'grid_size': grid_size
                    })

    logger.info(f"      Split into {len(grid_chunks)} grid chunks")
    return grid_chunks


def _parse_grid_cell_to_bbox(grid_cell: str) -> Optional[List[float]]:
    """Parse grid cell string to bbox [west, south, east, north]."""
    import re

    # Format: "n00-n05_w010-w005" or "s10-s05_e030-e035"
    match = re.match(r"([ns])(\d+)-([ns])(\d+)_([ew])(\d+)-([ew])(\d+)", grid_cell)
    if not match:
        return None

    lat_min_sign = 1 if match.group(1) == 'n' else -1
    lat_min = int(match.group(2)) * lat_min_sign
    lat_max_sign = 1 if match.group(3) == 'n' else -1
    lat_max = int(match.group(4)) * lat_max_sign

    lon_min_sign = -1 if match.group(5) == 'w' else 1
    lon_min = int(match.group(6)) * lon_min_sign
    lon_max_sign = -1 if match.group(7) == 'w' else 1
    lon_max = int(match.group(8)) * lon_max_sign

    return [lon_min, lat_min, lon_max, lat_max]


def _precreate_collections(
    chunks: List[dict],
    job_params: dict,
    logger
) -> List[str]:
    """Pre-create STAC collections for all regions in chunks."""
    from infrastructure.pgstac_bootstrap import PgStacBootstrap

    stac_repo = PgStacBootstrap()
    collection_base = job_params.get('collection_id', 'fathom-flood')

    # Get unique regions
    regions = set(chunk['region_code'] for chunk in chunks)
    collections_created = []

    # FATHOM provider
    fathom_provider = {
        "name": "FATHOM",
        "description": "Global flood hazard mapping",
        "roles": ["producer", "licensor"],
        "url": "https://www.fathom.global/"
    }

    for region in regions:
        collection_id = f"{collection_base}-{region}"

        try:
            if stac_repo.collection_exists(collection_id):
                logger.info(f"   Collection exists: {collection_id}")
            else:
                logger.info(f"   Creating collection: {collection_id}")

                stac_repo.create_collection(
                    container=FathomDefaults.PHASE2_OUTPUT_CONTAINER,
                    tier="silver",
                    collection_id=collection_id,
                    title=f"FATHOM Flood Hazard - {region.upper()}",
                    description=f"FATHOM global flood model data for {region.upper()}. "
                               f"Contains flood depth maps for multiple return periods, "
                               f"flood types, and climate scenarios.",
                    providers=[fathom_provider],
                    keywords=["flood", "hazard", "fathom", region, "depth"],
                    # Placeholder extent - will be updated by finalization
                    extent={
                        "spatial": {"bbox": [[-180, -90, 180, 90]]},
                        "temporal": {"interval": [[None, None]]}
                    }
                )
                collections_created.append(collection_id)

        except Exception as e:
            logger.error(f"   ❌ Failed to create collection {collection_id}: {e}")
            # Continue with other collections
            continue

    return collections_created


# Export handler
__all__ = ['fathom_chunk_inventory', 'CONTINENT_REGIONS']
