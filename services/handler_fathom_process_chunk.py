# ============================================================================
# CLAUDE CONTEXT - FATHOM PROCESS CHUNK HANDLER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Handler - Stage 2 of process_fathom_docker job (Docker worker)
# PURPOSE: Process one chunk: band stack + spatial merge + STAC items
# LAST_REVIEWED: 24 JAN 2026
# EXPORTS: fathom_process_chunk
# DEPENDENCIES: infrastructure, services.fathom_vrt_merge, services.stac_metadata_helper
# ============================================================================
"""
FATHOM Process Chunk Handler - Stage 2 (Docker Worker).

This handler runs on Docker workers and performs the heavy processing:
    Phase 1: Inventory tiles for this chunk
    Phase 2: Band stack all tiles (8 RPs → 1 COG per tile)
    Phase 3: Grid inventory for this chunk
    Phase 4: Spatial merge per grid cell (VRT streaming)
    Phase 5: Upsert STAC items + register mosaic search

Memory Efficiency:
    - Uses VRT-based merging instead of rasterio.merge
    - Streams data through Azure Files mount (CPL_TMPDIR)
    - Peak memory ~500MB regardless of grid size

Checkpointing:
    - Per-tile checkpoint during band stacking
    - Per-grid checkpoint during spatial merge
    - Graceful shutdown support (F7.18)

STAC Handling:
    - Collection already exists (created in Stage 1)
    - Upsert items (idempotent)
    - Re-register mosaic search per chunk
"""

import tempfile
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone

import numpy as np

from util_logger import LoggerFactory, ComponentType
from config import get_config
from config.defaults import FathomDefaults

# Return periods for FATHOM bands
RETURN_PERIODS = ["RP5", "RP10", "RP20", "RP50", "RP75", "RP100", "RP250", "RP500"]


def fathom_process_chunk(params: dict, context: dict = None) -> dict:
    """
    Process one chunk: band stack + spatial merge + STAC items.

    Runs on: Docker worker (heavy processing, Azure Files mount)
    Duration: 30 min - 4 hours depending on chunk size

    Args:
        params: Task parameters containing:
            - job_id: Job identifier
            - job_parameters: Original job parameters
            - chunk: Chunk definition with region_code, bbox, estimated_tiles
            - chunk_index: Index in chunks list
            - total_chunks: Total number of chunks

    Returns:
        dict with success status and result containing:
            - chunk_id: Chunk identifier
            - tiles_stacked: Number of tiles band-stacked
            - grids_merged: Number of grid cells merged
            - items_created: Number of STAC items created
    """
    logger = LoggerFactory.create_logger(
        ComponentType.SERVICE,
        "fathom_process_chunk"
    )

    job_id = params.get('job_id')
    job_params = params.get('job_parameters', {})
    chunk = params.get('chunk', {})
    chunk_index = params.get('chunk_index', 0)
    total_chunks = params.get('total_chunks', 1)

    chunk_id = chunk.get('chunk_id', 'unknown')
    region_code = chunk.get('region_code', '')
    grid_size = chunk.get('grid_size', job_params.get('grid_size', 5))

    logger.info(f"🔧 FATHOM Process Chunk [{chunk_index + 1}/{total_chunks}]: {chunk_id}")
    logger.info(f"   Region: {region_code}")
    logger.info(f"   Estimated tiles: {chunk.get('estimated_tiles', 'unknown')}")

    # Get Docker context for checkpointing and graceful shutdown
    docker_context = context.get('docker_context') if context else None
    checkpoint = docker_context.checkpoint if docker_context else None

    config = get_config()
    collection_id = f"{job_params.get('collection_id', 'fathom-flood')}-{region_code}"

    try:
        # ═══════════════════════════════════════════════════════════════
        # PHASE 1: Inventory tiles for this chunk
        # ═══════════════════════════════════════════════════════════════
        if checkpoint and checkpoint.should_skip(1):
            logger.info("   ⏭️ Phase 1: Skipping (checkpoint)")
            inventory = checkpoint.get_data('phase1_inventory')
        else:
            logger.info("   📋 Phase 1: Inventory tiles for chunk")
            inventory = _inventory_tiles_for_chunk(chunk, job_params, logger)

            if checkpoint:
                checkpoint.save(phase=1, data={'phase1_inventory': inventory})

            if docker_context:
                docker_context.report_progress(10, "Phase 1: Inventory complete")

        if not inventory.get('tile_groups'):
            logger.warning("   ⚠️ No tiles found for this chunk")
            return {
                'success': True,
                'result': {
                    'chunk_id': chunk_id,
                    'region_code': region_code,
                    'tiles_stacked': 0,
                    'grids_merged': 0,
                    'items_created': 0,
                    'collection_id': collection_id,
                    'message': 'No tiles found'
                }
            }

        # Check for graceful shutdown
        if docker_context and docker_context.should_stop():
            logger.info("   ⏸️ Graceful shutdown requested after Phase 1")
            return {'success': True, 'interrupted': True, 'resumable': True}

        # ═══════════════════════════════════════════════════════════════
        # PHASE 2: Band stack (with per-tile checkpoint)
        # ═══════════════════════════════════════════════════════════════
        if job_params.get('skip_phase1'):
            logger.info("   ⏭️ Phase 2: Skipping band stacking (skip_phase1=True)")
            stacked_tiles = inventory.get('existing_stacked', [])
        else:
            logger.info(f"   📦 Phase 2: Band stacking {len(inventory['tile_groups'])} tiles")

            stacked_tiles = _band_stack_tiles(
                tile_groups=inventory['tile_groups'],
                region_code=region_code,
                job_id=job_id,
                job_params=job_params,
                checkpoint=checkpoint,
                docker_context=docker_context,
                logger=logger
            )

            if docker_context:
                docker_context.report_progress(50, f"Phase 2: Stacked {len(stacked_tiles)} tiles")

        # Check for graceful shutdown
        if docker_context and docker_context.should_stop():
            logger.info("   ⏸️ Graceful shutdown requested after Phase 2")
            return {'success': True, 'interrupted': True, 'resumable': True}

        # ═══════════════════════════════════════════════════════════════
        # PHASE 3: Grid inventory
        # ═══════════════════════════════════════════════════════════════
        if job_params.get('skip_phase2'):
            logger.info("   ⏭️ Phase 3-4: Skipping spatial merge (skip_phase2=True)")
            # Phase 1 outputs are the final COGs
            cog_results = stacked_tiles
            grids_merged = 0
        else:
            if checkpoint and checkpoint.should_skip(3):
                logger.info("   ⏭️ Phase 3: Skipping (checkpoint)")
                grid_groups = checkpoint.get_data('phase3_grid_groups')
            else:
                logger.info("   🗺️ Phase 3: Grid inventory")
                grid_groups = _create_grid_groups(
                    stacked_tiles=stacked_tiles,
                    grid_size=grid_size,
                    chunk_bbox=chunk.get('bbox'),
                    logger=logger
                )

                if checkpoint:
                    checkpoint.save(phase=3, data={'phase3_grid_groups': grid_groups})

            if docker_context:
                docker_context.report_progress(55, f"Phase 3: {len(grid_groups)} grid cells")

            # ═══════════════════════════════════════════════════════════════
            # PHASE 4: Spatial merge (VRT streaming)
            # ═══════════════════════════════════════════════════════════════
            logger.info(f"   🔀 Phase 4: Spatial merge for {len(grid_groups)} grid cells")

            cog_results = _spatial_merge_grids(
                grid_groups=grid_groups,
                region_code=region_code,
                job_id=job_id,
                job_params=job_params,
                checkpoint=checkpoint,
                docker_context=docker_context,
                logger=logger
            )

            grids_merged = len(grid_groups)

            if docker_context:
                docker_context.report_progress(85, f"Phase 4: Merged {grids_merged} grids")

        # Check for graceful shutdown
        if docker_context and docker_context.should_stop():
            logger.info("   ⏸️ Graceful shutdown requested after Phase 4")
            return {'success': True, 'interrupted': True, 'resumable': True}

        # ═══════════════════════════════════════════════════════════════
        # PHASE 5: STAC items + mosaic search
        # ═══════════════════════════════════════════════════════════════
        if job_params.get('dry_run'):
            logger.info("   🔍 Phase 5: DRY RUN - skipping STAC registration")
            items_created = 0
        else:
            logger.info(f"   📚 Phase 5: Upserting {len(cog_results)} STAC items")

            items_created = _upsert_stac_items(
                cog_results=cog_results,
                collection_id=collection_id,
                region_code=region_code,
                job_id=job_id,
                logger=logger
            )

            # Re-register mosaic search
            _register_mosaic_search(collection_id, logger)

            if docker_context:
                docker_context.report_progress(100, f"Complete: {items_created} STAC items")

        # ═══════════════════════════════════════════════════════════════
        # RETURN RESULT
        # ═══════════════════════════════════════════════════════════════
        result = {
            'chunk_id': chunk_id,
            'region_code': region_code,
            'tiles_stacked': len(stacked_tiles),
            'grids_merged': grids_merged,
            'items_created': items_created,
            'collection_id': collection_id
        }

        logger.info(f"✅ Chunk complete: {chunk_id}")
        logger.info(f"   Tiles stacked: {result['tiles_stacked']}")
        logger.info(f"   Grids merged: {result['grids_merged']}")
        logger.info(f"   STAC items: {result['items_created']}")

        return {
            'success': True,
            'result': result
        }

    except Exception as e:
        logger.error(f"❌ Chunk processing failed: {chunk_id}")
        logger.error(f"   Error: {e}")
        import traceback
        logger.error(f"   Traceback: {traceback.format_exc()}")

        return {
            'success': False,
            'error': str(e),
            'chunk_id': chunk_id
        }


def _inventory_tiles_for_chunk(
    chunk: dict,
    job_params: dict,
    logger
) -> dict:
    """Inventory tiles for this specific chunk."""
    from infrastructure import PostgreSQLRepository

    repo = PostgreSQLRepository()
    region_code = chunk.get('region_code', '')
    chunk_bbox = chunk.get('bbox')
    grid_cell = chunk.get('grid_cell')

    # Build filter clauses
    filter_clauses = [
        "etl_type = 'fathom'",
        "source_metadata->>'region' = %(region)s"
    ]
    query_params = {'region': region_code}

    # Phase selection
    if job_params.get('skip_phase1'):
        filter_clauses.append("phase1_completed_at IS NOT NULL")
        filter_clauses.append("phase2_completed_at IS NULL")
    else:
        filter_clauses.append("phase1_completed_at IS NULL")

    # Grid cell filter if chunk is grid-cell based
    if grid_cell:
        filter_clauses.append("source_metadata->>'grid_cell' = %(grid_cell)s")
        query_params['grid_cell'] = grid_cell

    # Additional filters
    if job_params.get('flood_types'):
        filter_clauses.append("source_metadata->>'flood_type' = ANY(%(flood_types)s)")
        query_params['flood_types'] = job_params['flood_types']

    if job_params.get('years'):
        filter_clauses.append("(source_metadata->>'year')::int = ANY(%(years)s)")
        query_params['years'] = job_params['years']

    where_clause = " AND ".join(filter_clauses)

    # Query for tile groups (Phase 1 grouping)
    sql = f"""
        SELECT
            phase1_group_key,
            source_metadata->>'tile' as tile,
            source_metadata->>'flood_type' as flood_type,
            source_metadata->>'defense' as defense,
            (source_metadata->>'year')::int as year,
            source_metadata->>'ssp' as ssp,
            source_metadata->>'grid_cell' as grid_cell,
            json_object_agg(
                source_metadata->>'return_period',
                source_blob_path
                ORDER BY source_metadata->>'return_period'
            ) as return_period_files,
            MIN(phase1_output_blob) as phase1_output_blob
        FROM app.etl_source_files
        WHERE {where_clause}
        GROUP BY phase1_group_key, source_metadata->>'tile',
                 source_metadata->>'flood_type', source_metadata->>'defense',
                 (source_metadata->>'year')::int, source_metadata->>'ssp',
                 source_metadata->>'grid_cell'
        ORDER BY phase1_group_key
    """

    tile_groups = []
    existing_stacked = []

    with repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, query_params)
            for row in cur.fetchall():
                if job_params.get('skip_phase1') and row.get('phase1_output_blob'):
                    # Phase 2 mode: use existing stacked tiles
                    existing_stacked.append({
                        'phase1_group_key': row['phase1_group_key'],
                        'tile': row['tile'],
                        'flood_type': row['flood_type'],
                        'defense': row['defense'],
                        'year': row['year'],
                        'ssp': row.get('ssp'),
                        'grid_cell': row.get('grid_cell'),
                        'output_blob': row['phase1_output_blob']
                    })
                else:
                    # Phase 1 mode: need to stack
                    tile_groups.append({
                        'phase1_group_key': row['phase1_group_key'],
                        'tile': row['tile'],
                        'flood_type': row['flood_type'],
                        'defense': row['defense'],
                        'year': row['year'],
                        'ssp': row.get('ssp'),
                        'grid_cell': row.get('grid_cell'),
                        'return_period_files': row['return_period_files']
                    })

    logger.info(f"      Found {len(tile_groups)} tiles to stack, {len(existing_stacked)} already stacked")

    return {
        'tile_groups': tile_groups,
        'existing_stacked': existing_stacked
    }


def _band_stack_tiles(
    tile_groups: List[dict],
    region_code: str,
    job_id: str,
    job_params: dict,
    checkpoint,
    docker_context,
    logger
) -> List[dict]:
    """Band stack tiles (8 return periods → 1 multi-band COG per tile)."""
    import rasterio
    from rasterio.crs import CRS
    from infrastructure import BlobRepository, PostgreSQLRepository

    config = get_config()
    blob_repo = BlobRepository.for_zone("silver")
    source_container = FathomDefaults.SOURCE_CONTAINER
    output_container = FathomDefaults.PHASE1_OUTPUT_CONTAINER
    output_prefix = FathomDefaults.PHASE1_OUTPUT_PREFIX

    # Get already completed tiles from checkpoint
    completed_tiles = set()
    if checkpoint:
        completed_tiles = set(checkpoint.get_data('phase2_completed_tiles', []))

    stacked_results = []
    total = len(tile_groups)

    for idx, tile_group in enumerate(tile_groups):
        tile_id = tile_group['phase1_group_key']

        # Skip if already completed
        if tile_id in completed_tiles:
            logger.info(f"      ⏭️ [{idx + 1}/{total}] Skipping (checkpoint): {tile_id[:30]}...")
            # Need to reconstruct the result
            output_blob_path = f"{output_prefix}/{region_code}/{tile_group['tile']}/{tile_id}.tif"
            stacked_results.append({
                'phase1_group_key': tile_id,
                'tile': tile_group['tile'],
                'flood_type': tile_group['flood_type'],
                'defense': tile_group['defense'],
                'year': tile_group['year'],
                'ssp': tile_group.get('ssp'),
                'grid_cell': tile_group.get('grid_cell'),
                'output_blob': output_blob_path,
                'skipped': True
            })
            continue

        logger.info(f"      📦 [{idx + 1}/{total}] Stacking: {tile_id[:30]}...")

        # Output path
        output_blob_path = f"{output_prefix}/{region_code}/{tile_group['tile']}/{tile_id}.tif"

        # Check if already exists (idempotency)
        if not job_params.get('force_reprocess') and blob_repo.blob_exists(output_container, output_blob_path):
            logger.info(f"         ⏭️ Output exists, skipping")
            stacked_results.append({
                'phase1_group_key': tile_id,
                'tile': tile_group['tile'],
                'flood_type': tile_group['flood_type'],
                'defense': tile_group['defense'],
                'year': tile_group['year'],
                'ssp': tile_group.get('ssp'),
                'grid_cell': tile_group.get('grid_cell'),
                'output_blob': output_blob_path,
                'skipped': True
            })
            # Mark as completed in checkpoint
            if checkpoint:
                completed_tiles.add(tile_id)
                checkpoint.save(phase=2, data={'phase2_completed_tiles': list(completed_tiles)})
            continue

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir = Path(tmpdir)

                # Download and stack return period files
                return_period_files = tile_group['return_period_files']
                if isinstance(return_period_files, str):
                    import json
                    return_period_files = json.loads(return_period_files)

                bands = []
                profile = None

                for rp in RETURN_PERIODS:
                    blob_path = return_period_files.get(rp)
                    if not blob_path:
                        logger.warning(f"         ⚠️ Missing return period: {rp}")
                        continue

                    # Download
                    blob_bytes = blob_repo.read_blob(source_container, blob_path)
                    local_path = tmpdir / f"{rp}.tif"
                    with open(local_path, 'wb') as f:
                        f.write(blob_bytes)

                    # Read band
                    with rasterio.open(local_path) as src:
                        bands.append(src.read(1))
                        if profile is None:
                            profile = src.profile.copy()

                if not bands:
                    logger.warning(f"         ⚠️ No bands loaded, skipping")
                    continue

                # Stack bands
                stacked = np.stack(bands, axis=0)

                # Write output COG
                output_path = tmpdir / "stacked.tif"
                profile.update(
                    driver="GTiff",
                    count=len(bands),
                    dtype=np.int16,
                    compress="deflate",
                    predictor=2,
                    tiled=True,
                    blockxsize=512,
                    blockysize=512
                )

                with rasterio.open(output_path, 'w', **profile) as dst:
                    dst.write(stacked)
                    # Set band descriptions
                    for i, rp in enumerate(RETURN_PERIODS[:len(bands)]):
                        dst.set_band_description(i + 1, rp)

                # Upload to blob storage
                with open(output_path, 'rb') as f:
                    blob_repo.upload_blob(output_container, output_blob_path, f.read())

                # Update ETL tracking
                _update_phase1_tracking(tile_id, output_blob_path, job_id, logger)

                stacked_results.append({
                    'phase1_group_key': tile_id,
                    'tile': tile_group['tile'],
                    'flood_type': tile_group['flood_type'],
                    'defense': tile_group['defense'],
                    'year': tile_group['year'],
                    'ssp': tile_group.get('ssp'),
                    'grid_cell': tile_group.get('grid_cell'),
                    'output_blob': output_blob_path,
                    'skipped': False
                })

                # Update checkpoint
                if checkpoint:
                    completed_tiles.add(tile_id)
                    checkpoint.save(phase=2, data={'phase2_completed_tiles': list(completed_tiles)})

                # Report progress
                if docker_context:
                    pct = 10 + int(40 * (idx + 1) / total)
                    docker_context.report_progress(pct, f"Stacking tile {idx + 1}/{total}")

        except Exception as e:
            logger.error(f"         ❌ Failed to stack tile: {e}")
            # Continue with next tile
            continue

        # Check for graceful shutdown
        if docker_context and docker_context.should_stop():
            logger.info("      ⏸️ Graceful shutdown requested during band stacking")
            break

    return stacked_results


def _update_phase1_tracking(tile_id: str, output_blob: str, job_id: str, logger):
    """Update ETL tracking for Phase 1 completion."""
    from infrastructure import PostgreSQLRepository

    repo = PostgreSQLRepository()

    sql = """
        UPDATE app.etl_source_files
        SET phase1_completed_at = NOW(),
            phase1_output_blob = %(output_blob)s,
            phase1_job_id = %(job_id)s
        WHERE phase1_group_key = %(tile_id)s
          AND etl_type = 'fathom'
    """

    try:
        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, {
                    'tile_id': tile_id,
                    'output_blob': output_blob,
                    'job_id': job_id
                })
            conn.commit()
    except Exception as e:
        logger.warning(f"      ⚠️ Failed to update Phase 1 tracking: {e}")


def _create_grid_groups(
    stacked_tiles: List[dict],
    grid_size: int,
    chunk_bbox: Optional[List[float]],
    logger
) -> List[dict]:
    """Group stacked tiles by grid cell for spatial merge."""

    # Group tiles by grid_cell
    grid_groups = {}

    for tile in stacked_tiles:
        grid_cell = tile.get('grid_cell')
        if not grid_cell:
            # Compute grid cell from tile bounds if not present
            # For now, skip tiles without grid_cell
            logger.warning(f"      ⚠️ Tile missing grid_cell: {tile.get('tile')}")
            continue

        # Create group key from scenario attributes
        group_key = f"{tile['flood_type']}-{tile['defense']}-{tile['year']}"
        if tile.get('ssp'):
            group_key += f"-{tile['ssp']}"
        group_key += f"-{grid_cell}"

        if group_key not in grid_groups:
            grid_groups[group_key] = {
                'group_key': group_key,
                'grid_cell': grid_cell,
                'flood_type': tile['flood_type'],
                'defense': tile['defense'],
                'year': tile['year'],
                'ssp': tile.get('ssp'),
                'tiles': []
            }

        grid_groups[group_key]['tiles'].append(tile)

    result = list(grid_groups.values())
    logger.info(f"      Created {len(result)} grid groups from {len(stacked_tiles)} tiles")

    return result


def _spatial_merge_grids(
    grid_groups: List[dict],
    region_code: str,
    job_id: str,
    job_params: dict,
    checkpoint,
    docker_context,
    logger
) -> List[dict]:
    """Merge tiles per grid cell using VRT streaming."""
    from services.fathom_vrt_merge import merge_tiles_vrt
    from infrastructure import BlobRepository

    config = get_config()
    blob_repo = BlobRepository.for_zone("silver")
    source_container = FathomDefaults.PHASE1_OUTPUT_CONTAINER
    output_container = FathomDefaults.PHASE2_OUTPUT_CONTAINER
    output_prefix = FathomDefaults.PHASE2_OUTPUT_PREFIX

    # Use Azure Files mount if available
    mount_path = config.raster.etl_mount_path if config.raster.use_etl_mount else None

    # Get already completed grids from checkpoint
    completed_grids = set()
    if checkpoint:
        completed_grids = set(checkpoint.get_data('phase4_completed_grids', []))

    cog_results = []
    total = len(grid_groups)

    for idx, grid_group in enumerate(grid_groups):
        group_key = grid_group['group_key']

        # Skip if already completed
        if group_key in completed_grids:
            logger.info(f"      ⏭️ [{idx + 1}/{total}] Skipping (checkpoint): {group_key[:30]}...")
            output_blob_path = f"{output_prefix}/{region_code}/{group_key}.tif"
            cog_results.append({
                'output_name': group_key,
                'output_blob': output_blob_path,
                'output_container': output_container,
                'grid_cell': grid_group['grid_cell'],
                'flood_type': grid_group['flood_type'],
                'defense': grid_group['defense'],
                'year': grid_group['year'],
                'ssp': grid_group.get('ssp'),
                'region_code': region_code,
                'tile_count': len(grid_group['tiles']),
                'skipped': True
            })
            continue

        logger.info(f"      🔀 [{idx + 1}/{total}] Merging: {group_key[:30]}... ({len(grid_group['tiles'])} tiles)")

        # Output path
        output_blob_path = f"{output_prefix}/{region_code}/{group_key}.tif"

        # Check if already exists (idempotency)
        if not job_params.get('force_reprocess') and blob_repo.blob_exists(output_container, output_blob_path):
            logger.info(f"         ⏭️ Output exists, skipping")

            # Try to read bounds from existing file
            bounds = _read_bounds_from_blob(blob_repo, output_container, output_blob_path, logger)

            cog_results.append({
                'output_name': group_key,
                'output_blob': output_blob_path,
                'output_container': output_container,
                'grid_cell': grid_group['grid_cell'],
                'flood_type': grid_group['flood_type'],
                'defense': grid_group['defense'],
                'year': grid_group['year'],
                'ssp': grid_group.get('ssp'),
                'region_code': region_code,
                'tile_count': len(grid_group['tiles']),
                'bounds': bounds,
                'skipped': True
            })

            # Update checkpoint
            if checkpoint:
                completed_grids.add(group_key)
                checkpoint.save(phase=4, data={'phase4_completed_grids': list(completed_grids)})
            continue

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir = Path(tmpdir)

                # Download source tiles
                tile_paths = []
                for tile in grid_group['tiles']:
                    blob_path = tile['output_blob']
                    local_path = tmpdir / f"{tile['tile']}.tif"

                    blob_bytes = blob_repo.read_blob(source_container, blob_path)
                    with open(local_path, 'wb') as f:
                        f.write(blob_bytes)
                    tile_paths.append(str(local_path))

                # Output path (local)
                output_path = tmpdir / f"{group_key}.tif"

                # Merge using VRT
                merge_result = merge_tiles_vrt(
                    tile_paths=tile_paths,
                    output_path=str(output_path),
                    band_names=RETURN_PERIODS,
                    mount_path=mount_path or str(tmpdir)
                )

                if not merge_result.get('success'):
                    logger.error(f"         ❌ VRT merge failed: {merge_result.get('error')}")
                    continue

                # Upload to blob storage
                with open(output_path, 'rb') as f:
                    blob_repo.upload_blob(output_container, output_blob_path, f.read())

                # Update ETL tracking
                _update_phase2_tracking(group_key, output_blob_path, job_id, logger)

                cog_results.append({
                    'output_name': group_key,
                    'output_blob': output_blob_path,
                    'output_container': output_container,
                    'grid_cell': grid_group['grid_cell'],
                    'flood_type': grid_group['flood_type'],
                    'defense': grid_group['defense'],
                    'year': grid_group['year'],
                    'ssp': grid_group.get('ssp'),
                    'region_code': region_code,
                    'tile_count': len(grid_group['tiles']),
                    'bounds': merge_result.get('bounds'),
                    'skipped': False
                })

                # Update checkpoint
                if checkpoint:
                    completed_grids.add(group_key)
                    checkpoint.save(phase=4, data={'phase4_completed_grids': list(completed_grids)})

                # Report progress
                if docker_context:
                    pct = 55 + int(30 * (idx + 1) / total)
                    docker_context.report_progress(pct, f"Merging grid {idx + 1}/{total}")

        except Exception as e:
            logger.error(f"         ❌ Failed to merge grid: {e}")
            import traceback
            logger.error(f"         {traceback.format_exc()}")
            continue

        # Check for graceful shutdown
        if docker_context and docker_context.should_stop():
            logger.info("      ⏸️ Graceful shutdown requested during spatial merge")
            break

    return cog_results


def _read_bounds_from_blob(blob_repo, container: str, blob_path: str, logger) -> Optional[dict]:
    """Read bounds from existing COG."""
    import rasterio
    from io import BytesIO

    try:
        blob_bytes = blob_repo.read_blob(container, blob_path)
        with rasterio.open(BytesIO(blob_bytes)) as src:
            bounds = src.bounds
            return {
                'west': bounds.left,
                'south': bounds.bottom,
                'east': bounds.right,
                'north': bounds.top
            }
    except Exception as e:
        logger.warning(f"      ⚠️ Could not read bounds: {e}")
        return None


def _update_phase2_tracking(group_key: str, output_blob: str, job_id: str, logger):
    """Update ETL tracking for Phase 2 completion."""
    from infrastructure import PostgreSQLRepository

    repo = PostgreSQLRepository()

    sql = """
        UPDATE app.etl_source_files
        SET phase2_completed_at = NOW(),
            phase2_output_blob = %(output_blob)s,
            phase2_job_id = %(job_id)s
        WHERE phase2_group_key = %(group_key)s
          AND etl_type = 'fathom'
    """

    try:
        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, {
                    'group_key': group_key,
                    'output_blob': output_blob,
                    'job_id': job_id
                })
            conn.commit()
    except Exception as e:
        logger.warning(f"      ⚠️ Failed to update Phase 2 tracking: {e}")


def _upsert_stac_items(
    cog_results: List[dict],
    collection_id: str,
    region_code: str,
    job_id: str,
    logger
) -> int:
    """Upsert STAC items for COG results."""
    from infrastructure.pgstac_bootstrap import PgStacBootstrap
    from services.stac_metadata_helper import STACMetadataHelper, AppMetadata

    stac_repo = PgStacBootstrap()
    helper = STACMetadataHelper()
    items_created = 0

    for cog in cog_results:
        if not cog.get('bounds'):
            logger.warning(f"      ⚠️ Skipping STAC item (no bounds): {cog.get('output_name')}")
            continue

        try:
            bounds = cog['bounds']

            # Build STAC item
            item_dict = {
                "type": "Feature",
                "stac_version": "1.0.0",
                "stac_extensions": [
                    "https://stac-extensions.github.io/eo/v1.0.0/schema.json",
                    "https://stac-extensions.github.io/raster/v1.1.0/schema.json"
                ],
                "id": cog['output_name'],
                "collection": collection_id,
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [bounds['west'], bounds['south']],
                        [bounds['east'], bounds['south']],
                        [bounds['east'], bounds['north']],
                        [bounds['west'], bounds['north']],
                        [bounds['west'], bounds['south']]
                    ]]
                },
                "bbox": [bounds['west'], bounds['south'], bounds['east'], bounds['north']],
                "properties": {
                    "datetime": None,
                    "start_datetime": f"{cog['year']}-01-01T00:00:00Z",
                    "end_datetime": f"{cog['year']}-12-31T23:59:59Z",
                    "fathom:flood_type": cog['flood_type'],
                    "fathom:defense": cog['defense'],
                    "fathom:year": cog['year'],
                    "fathom:ssp": cog.get('ssp'),
                    "fathom:region": region_code,
                    "fathom:grid_cell": cog.get('grid_cell'),
                    "fathom:tile_count": cog.get('tile_count', 1)
                },
                "links": [
                    {"rel": "collection", "href": f"./collection.json"}
                ],
                "assets": {
                    "data": {
                        "href": f"/vsiaz/{cog['output_container']}/{cog['output_blob']}",
                        "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                        "roles": ["data"],
                        "title": "Flood Depth Data",
                        "eo:bands": [
                            {"name": rp, "description": f"Flood depth for {rp} return period"}
                            for rp in RETURN_PERIODS
                        ]
                    }
                }
            }

            # Augment with TiTiler links and app metadata
            item_dict = helper.augment_item(
                item_dict=item_dict,
                container=cog['output_container'],
                blob_name=cog['output_blob'],
                app=AppMetadata(job_id=job_id, job_type="process_fathom_docker"),
                include_iso3=True,
                include_titiler=True
            )

            # Upsert item
            stac_repo.upsert_item(item_dict, collection_id)
            items_created += 1

        except Exception as e:
            logger.error(f"      ❌ Failed to create STAC item: {cog.get('output_name')}: {e}")
            continue

    return items_created


def _register_mosaic_search(collection_id: str, logger):
    """Register or update mosaic search for collection."""
    try:
        from services.pgstac_search_registration import PgSTACSearchRegistration
        from config import get_config

        config = get_config()
        registrar = PgSTACSearchRegistration()

        search_id = registrar.register_collection_search(
            collection_id=collection_id,
            metadata={'name': f'{collection_id} mosaic'}
        )

        logger.info(f"      Mosaic search registered: {search_id[:16]}...")

    except Exception as e:
        logger.warning(f"      ⚠️ Mosaic search registration failed: {e}")


# Export handler
__all__ = ['fathom_process_chunk']
