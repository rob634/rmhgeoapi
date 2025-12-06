"""
H3 Grid PostGIS Insertion Handler.

Loads H3 hexagonal grids from GeoParquet and inserts to geo.h3_grids table.

Workflow:
    Stage 1: Generate H3 grid → Save to GeoParquet
    Stage 2 (this handler): Load GeoParquet → Insert to PostGIS
    Stage 3: Create STAC record

Exports:
    insert_h3_to_postgis: Task handler function
"""

import time
import io
from typing import Dict, Any
from decimal import Decimal

import pandas as pd
import geopandas as gpd
from shapely import wkt
import psycopg
from psycopg import sql

from infrastructure.factory import RepositoryFactory
from config import get_config
from util_logger import LoggerFactory, ComponentType


def insert_h3_to_postgis(task_params: dict) -> dict:
    """
    Load H3 grid from GeoParquet and insert to PostGIS geo.h3_grids table.

    Core Machine Contract:
        - Takes task_params dict
        - Returns dict with success status and statistics
        - Raises exceptions for failures (caught by Core Machine)

    Args:
        task_params: Task parameters dict:
            - blob_path (str): GeoParquet blob path in gold container
            - grid_id (str): Grid identifier (e.g., "global_res4", "land_res4")
            - grid_type (str): Grid type ("global" or "land")
            - resolution (int): H3 resolution (0-15)
            - source_job_id (str): Originating job ID

    Returns:
        Success dict with:
            - success: True
            - result:
                - rows_inserted: Number of H3 cells inserted
                - table_name: "geo.h3_grids"
                - grid_id: Grid identifier
                - bbox: [minx, miny, maxx, maxy]
                - resolution: H3 resolution
                - file_size_mb: GeoParquet file size

    Raises:
        ValueError: Invalid parameters or data
        psycopg.Error: Database insertion error
        Exception: Blob storage or processing errors
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "insert_h3_to_postgis")
    start_time = time.time()

    logger.info("=" * 80)
    logger.info("🔷 H3 GRID POSTGIS INSERTION")
    logger.info("=" * 80)

    try:
        # Extract and validate parameters
        blob_path = task_params.get('blob_path')
        grid_id = task_params.get('grid_id')
        grid_type = task_params.get('grid_type')
        resolution = task_params.get('resolution')
        source_job_id = task_params.get('source_job_id')

        logger.info(f"📋 Parameters:")
        logger.info(f"   Blob path: {blob_path}")
        logger.info(f"   Grid ID: {grid_id}")
        logger.info(f"   Grid type: {grid_type}")
        logger.info(f"   Resolution: {resolution}")
        logger.info(f"   Source job: {source_job_id[:16]}...")

        # Validate required parameters
        if not blob_path:
            raise ValueError("blob_path is required")
        if not grid_id:
            raise ValueError("grid_id is required")
        if not grid_type:
            raise ValueError("grid_type is required")
        if resolution is None:
            raise ValueError("resolution is required")
        if not isinstance(resolution, int) or resolution < 0 or resolution > 15:
            raise ValueError(f"resolution must be 0-15, got {resolution}")

        # Get configuration and repositories
        config = get_config()
        blob_repo = RepositoryFactory.create_blob_repository()

        # STEP 1: Load GeoParquet from blob storage
        logger.info("📦 STEP 1: Loading GeoParquet from blob storage...")
        blob_data = blob_repo.read_blob(
            container=config.storage.gold.get_container('misc'),  # gold-h3-grids
            blob_path=blob_path
        )
        file_size_mb = len(blob_data) / (1024 * 1024)
        logger.info(f"   ✅ Loaded {file_size_mb:.2f} MB from {blob_path}")

        # Load GeoParquet using pandas (in-memory)
        logger.info("📊 STEP 2: Parsing GeoParquet...")
        df = pd.read_parquet(io.BytesIO(blob_data))
        total_cells = len(df)
        logger.info(f"   ✅ Parsed {total_cells:,} H3 cells")

        # STEP 2: Convert to GeoDataFrame with PostGIS-ready geometry
        logger.info("🗺️  STEP 3: Converting geometries...")

        # Convert WKT geometry column to shapely geometries
        geometry_col = 'geometry_wkt' if 'geometry_wkt' in df.columns else 'geometry'
        gdf = gpd.GeoDataFrame(
            df,
            geometry=df[geometry_col].apply(wkt.loads),
            crs='EPSG:4326'
        )
        logger.info(f"   ✅ Created GeoDataFrame with {len(gdf):,} polygons")

        # STEP 3: Add PostGIS metadata columns
        logger.info("📝 STEP 4: Adding metadata columns...")
        gdf['grid_id'] = grid_id
        gdf['grid_type'] = grid_type
        gdf['source_job_id'] = source_job_id
        gdf['source_blob_path'] = blob_path

        # For land grids, mark is_land=True
        if grid_type == 'land':
            gdf['is_land'] = True
            logger.info(f"   ✅ Marked {len(gdf):,} cells as land")
        else:
            gdf['is_land'] = None  # Global grids don't have land classification

        # Rename geometry column if needed (PostGIS expects 'geom')
        if gdf.geometry.name != 'geom':
            gdf = gdf.rename_geometry('geom')

        # STEP 4: Calculate bounding box
        logger.info("📐 STEP 5: Calculating bounding box...")
        bbox = gdf.total_bounds.tolist()  # [minx, miny, maxx, maxy]
        logger.info(f"   ✅ Bbox: [{bbox[0]:.2f}, {bbox[1]:.2f}, {bbox[2]:.2f}, {bbox[3]:.2f}]")

        # STEP 5: Batch insert to PostGIS
        logger.info("💾 STEP 6: Inserting to geo.h3_grids...")
        config = get_config()

        # Use to_postgis for efficient bulk insert
        # Note: This uses SQLAlchemy under the hood
        from sqlalchemy import create_engine

        # Build SQLAlchemy connection string
        db_url = (
            f"postgresql://{config.postgis_user}:{config.postgis_password}"
            f"@{config.postgis_host}:{config.postgis_port}/{config.postgis_database}"
        )
        engine = create_engine(db_url)

        # Prepare columns for insertion (match table schema)
        insert_gdf = gdf[[
            'h3_index',
            'resolution',
            'geom',
            'grid_id',
            'grid_type',
            'source_job_id',
            'source_blob_path',
            'is_land'
        ]].copy()

        # Insert with to_postgis (handles spatial index automatically)
        insert_gdf.to_postgis(
            name='h3_grids',
            con=engine,
            schema='geo',
            if_exists='append',
            index=False,
            chunksize=1000  # Batch size for large grids
        )

        processing_time = time.time() - start_time
        logger.info(f"   ✅ Inserted {total_cells:,} cells in {processing_time:.2f}s")
        logger.info(f"   ✅ Table: geo.h3_grids")
        logger.info(f"   ✅ Grid ID: {grid_id}")

        logger.info("=" * 80)
        logger.info("✅ H3 GRID POSTGIS INSERTION COMPLETE")
        logger.info("=" * 80)

        return {
            "success": True,
            "result": {
                "rows_inserted": total_cells,
                "table_name": "geo.h3_grids",
                "grid_id": grid_id,
                "grid_type": grid_type,
                "bbox": bbox,
                "resolution": resolution,
                "file_size_mb": round(file_size_mb, 2),
                "processing_time_seconds": round(processing_time, 2)
            }
        }

    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"❌ H3 PostGIS insertion failed after {processing_time:.2f}s: {e}")
        logger.exception("Full traceback:")

        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "processing_time_seconds": round(processing_time, 2)
        }
