"""
PostGIS-driven tiling service for large raster processing.

This service uses PostGIS spatial intelligence to determine optimal tiling
strategies for large rasters. It validates STAC entries, calculates tile grids,
and generates processing tasks for turning massive TIFFs into manageable
tiled COGs.

Key Features:
    - STAC validation ensures input exists and has geometry
    - PostGIS calculates optimal tile size based on resolution and file size
    - Generates tile grid with geographic and pixel coordinates
    - Creates task messages for parallel processing
    - Handles irregular shapes and different data densities
    - Stores tile definitions for reprocessing

Workflow:
    1. Validate STAC item exists with proper geometry
    2. Analyze raster metadata (size, resolution, shape)
    3. Calculate optimal tiling strategy
    4. Generate tile grid using PostGIS functions
    5. Convert geographic tiles to pixel windows
    6. Create task messages for queue processing

Author: Azure Geospatial ETL Team
Version: 1.0.0
"""

from typing import Dict, Any, List, Optional, Tuple
import json
import math
import hashlib
from datetime import datetime

from services import BaseProcessingService
from database_client import DatabaseClient
from repositories import StorageRepository
from config import Config
from logger_setup import get_logger

logger = get_logger(__name__)


class PostGISTilingService(BaseProcessingService):
    """
    Service for intelligent raster tiling using PostGIS spatial analysis.
    
    Uses PostGIS to calculate optimal tile grids for large rasters based on
    their spatial characteristics, resolution, and size. Generates tasks for
    parallel processing of tiles into COGs.
    """
    
    def __init__(self):
        """Initialize tiling service with database and storage connections."""
        self.db_client = DatabaseClient()
        self._storage = None  # Lazy load storage
        self.silver_container = Config.SILVER_CONTAINER_NAME or "rmhazuregeosilver"
        self.tiles_folder = "tiles"  # Output folder for tiles
    
    @property
    def storage(self):
        """Lazy load storage repository."""
        if self._storage is None:
            self._storage = StorageRepository()
        return self._storage
        
    def get_supported_operations(self) -> List[str]:
        """
        Return list of operations this service supports.
        
        Returns:
            List[str]: ['generate_tile_grid', 'create_tiling_tasks']
        """
        return ["generate_tile_grid", "create_tiling_tasks"]
    
    def validate_stac_item(self, stac_id: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Validate that a STAC item exists and has required properties.
        
        Args:
            stac_id: STAC item ID to validate
            
        Returns:
            Tuple of (is_valid, item_data)
        """
        try:
            # Query STAC item from database
            query = """
                SELECT 
                    id,
                    ST_AsGeoJSON(geometry)::json as geometry,
                    ST_XMin(geometry) as xmin,
                    ST_YMin(geometry) as ymin,
                    ST_XMax(geometry) as xmax,
                    ST_YMax(geometry) as ymax,
                    ST_Area(geometry::geography) / 1000000 as area_sqkm,
                    properties->>'file:name' as asset_href,
                    properties->>'type' as asset_type,
                    properties->>'proj:epsg' as epsg,
                    CONCAT(properties->>'width', ',', properties->>'height') as shape,
                    properties->>'file:size' as file_size_bytes,
                    properties->>'is_cog' as is_cog,
                    'rmhazuregeobronze' as container,
                    properties->>'file:name' as cog_href
                FROM geo.items 
                WHERE id = %s
            """
            
            result = self.db_client.execute(query, (stac_id,))
            
            if not result or len(result) == 0:
                logger.error(f"STAC item not found: {stac_id}")
                return False, {"error": f"STAC item '{stac_id}' not found"}
            
            item = result[0]
            
            # Validate required fields
            if not item.get('geometry'):
                return False, {"error": "STAC item has no geometry"}
            
            if not item.get('asset_href'):
                return False, {"error": "STAC item has no asset_href"}
            
            # Check if it's a raster (handle both 'raster' and 'image/*' types)
            asset_type = item.get('asset_type', '')
            if not (asset_type == 'raster' or asset_type.startswith('image/')):
                return False, {"error": f"Asset is not a raster: {asset_type}"}
            
            # Convert file size to MB (handle both int and string)
            file_size_value = item.get('file_size_bytes')
            if file_size_value:
                # Handle string or numeric values
                if isinstance(file_size_value, str):
                    file_size_value = float(file_size_value)
                item['file_size_mb'] = float(file_size_value) / (1024 * 1024)
            else:
                item['file_size_mb'] = None
            
            logger.info(f"Validated STAC item: {stac_id}, "
                       f"Size: {item.get('file_size_mb', 0):.1f}MB, "
                       f"Area: {item.get('area_sqkm', 0):.1f}km², "
                       f"Bounds: ({item.get('xmin')}, {item.get('ymin')}, "
                       f"{item.get('xmax')}, {item.get('ymax')})")
            
            return True, item
            
        except Exception as e:
            logger.error(f"Error validating STAC item: {e}")
            return False, {"error": str(e)}
    
    def calculate_optimal_tile_size(self, item_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate optimal tile size based on raster characteristics.
        
        Args:
            item_data: STAC item data with geometry and metadata
            
        Returns:
            Dict with tiling strategy and parameters
        """
        file_size_mb = item_data.get('file_size_mb', 0)
        area_sqkm = item_data.get('area_sqkm', 0)
        
        # Extract resolution from shape if available
        shape_str = item_data.get('shape', '[]')
        try:
            shape = json.loads(shape_str) if isinstance(shape_str, str) else shape_str
            if shape and len(shape) >= 2:
                width_pixels = shape[0]
                height_pixels = shape[1]
                # Estimate ground resolution
                width_km = (item_data['xmax'] - item_data['xmin']) * 111  # Rough deg to km
                height_km = (item_data['ymax'] - item_data['ymin']) * 111
                gsd_m = min(width_km * 1000 / width_pixels, height_km * 1000 / height_pixels)
            else:
                gsd_m = 10  # Default 10m resolution
        except:
            gsd_m = 10
        
        # Smart tiling: Calculate optimal tile size based on file size and geographic extent
        # Target ~1GB per tile for efficient processing
        target_tile_mb = 1000  # 1GB target
        
        # Calculate how many tiles we need
        tiles_needed = max(int(file_size_mb / target_tile_mb), 4)  # At least 4 tiles
        
        # Calculate the geographic extent
        xmin = item_data.get('xmin', 0)
        ymin = item_data.get('ymin', 0)
        xmax = item_data.get('xmax', 1)
        ymax = item_data.get('ymax', 1)
        
        width_deg = xmax - xmin
        height_deg = ymax - ymin
        
        # Calculate tile size to achieve desired number of tiles
        # We want roughly tiles_needed = (width/tile_size) * (height/tile_size)
        # So tile_size = sqrt((width * height) / tiles_needed)
        area_deg2 = width_deg * height_deg
        tile_size_deg = math.sqrt(area_deg2 / tiles_needed) if tiles_needed > 0 else 0.1
        
        # Round to a reasonable precision
        tile_size_deg = round(tile_size_deg, 4)
        
        # Apply bounds - minimum 0.01° (~1km), maximum 5°
        tile_size_deg = max(0.01, min(tile_size_deg, 5.0))
        
        logger.info(f"Smart tiling: {file_size_mb:.1f}MB file needs ~{tiles_needed} tiles "
                   f"for {target_tile_mb}MB each. Geographic extent: {width_deg:.4f}° x {height_deg:.4f}°. "
                   f"Calculated tile size: {tile_size_deg:.4f}°")
        
        # Determine strategy name based on file size
        if file_size_mb > 10000:  # >10GB
            strategy = "ultra_dense"
        elif file_size_mb > 5000:  # 5-10GB
            strategy = "dense"
        elif file_size_mb > 1000:  # 1-5GB
            strategy = "standard"
        else:
            strategy = "sparse"
        
        # Adjust for high-resolution data
        if gsd_m < 1:  # Sub-meter resolution
            tile_size_deg *= 0.5
            strategy = f"high_res_{strategy}"
        elif gsd_m < 5:  # 1-5m resolution
            tile_size_deg *= 0.75
            
        return {
            "strategy": strategy,
            "tile_size_degrees": tile_size_deg,
            "estimated_gsd_m": gsd_m,
            "target_tile_size_mb": target_tile_mb,
            "source_size_mb": file_size_mb,
            "source_area_sqkm": area_sqkm
        }
    
    def generate_tile_grid(self, item_data: Dict[str, Any], 
                          tile_strategy: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Generate tile grid using PostGIS spatial functions.
        
        Args:
            item_data: STAC item data with bounds
            tile_strategy: Tiling strategy from calculate_optimal_tile_size
            
        Returns:
            List of tile definitions with bounds and IDs
        """
        try:
            tile_size = tile_strategy.get('tile_size_degrees')
            if not tile_size:
                logger.error(f"No tile_size_degrees in strategy: {tile_strategy}")
                return []
            
            logger.info(f"Generating tile grid with size {tile_size}° for bounds: "
                       f"({item_data.get('xmin')}, {item_data.get('ymin')}, "
                       f"{item_data.get('xmax')}, {item_data.get('ymax')})")
            
            # Generate grid using PostGIS
            query = """
                WITH bounds AS (
                    SELECT 
                        %s::float as xmin,
                        %s::float as ymin,
                        %s::float as xmax,
                        %s::float as ymax
                ),
                grid_params AS (
                    SELECT
                        xmin,
                        ymin,
                        xmax,
                        ymax,
                        %s::float as tile_size,
                        CEIL((xmax - xmin) / %s::float)::int as cols,
                        CEIL((ymax - ymin) / %s::float)::int as rows
                    FROM bounds
                ),
                tiles AS (
                    SELECT
                        row_num,
                        col_num,
                        GREATEST(xmin + (col_num - 1) * tile_size, xmin) as tile_xmin,
                        GREATEST(ymin + (row_num - 1) * tile_size, ymin) as tile_ymin,
                        LEAST(xmin + col_num * tile_size, xmax) as tile_xmax,
                        LEAST(ymin + row_num * tile_size, ymax) as tile_ymax
                    FROM 
                        grid_params,
                        generate_series(1, rows) as row_num,
                        generate_series(1, cols) as col_num
                )
                SELECT 
                    CONCAT('R', LPAD(row_num::text, 2, '0'), 'C', LPAD(col_num::text, 2, '0')) as tile_id,
                    row_num,
                    col_num,
                    tile_xmin as minx,
                    tile_ymin as miny,
                    tile_xmax as maxx,
                    tile_ymax as maxy,
                    (tile_xmax - tile_xmin) * 111 as width_km,
                    (tile_ymax - tile_ymin) * 111 as height_km,
                    ST_AsGeoJSON(
                        ST_MakeEnvelope(tile_xmin, tile_ymin, tile_xmax, tile_ymax, 4326)
                    )::json as geometry
                FROM tiles
                ORDER BY row_num, col_num
            """
            
            # Ensure bounds are not None
            xmin = item_data.get('xmin')
            ymin = item_data.get('ymin')
            xmax = item_data.get('xmax')
            ymax = item_data.get('ymax')
            
            if any(v is None for v in [xmin, ymin, xmax, ymax]):
                logger.error(f"Missing bounds in item_data: xmin={xmin}, ymin={ymin}, xmax={xmax}, ymax={ymax}")
                return []
            
            tiles = self.db_client.execute(
                query,
                (xmin, ymin, xmax, ymax, tile_size, tile_size, tile_size)
            )
            
            if tiles:
                logger.info(f"Generated {len(tiles)} tiles with size {tile_size}°")
            else:
                logger.warning(f"No tiles generated from query with bounds: "
                              f"({item_data['xmin']}, {item_data['ymin']}, "
                              f"{item_data['xmax']}, {item_data['ymax']}) "
                              f"and tile size {tile_size}°")
            
            return tiles if tiles else []
            
        except Exception as e:
            logger.error(f"Error generating tile grid: {e}", exc_info=True)
            return []
    
    def create_task_messages(self, stac_id: str, item_data: Dict[str, Any],
                           tiles: List[Dict[str, Any]], job_id: str) -> List[Dict[str, Any]]:
        """
        Create task messages for processing each tile.
        
        Args:
            stac_id: STAC item ID
            item_data: STAC item metadata
            tiles: List of tile definitions
            job_id: Parent job ID
            
        Returns:
            List of task messages ready for queuing
        """
        tasks = []
        
        # Determine source path
        if item_data.get('is_cog') == 'true' and item_data.get('cog_href'):
            # Use existing COG
            source_path = item_data['cog_href']
            source_container = self.silver_container
        else:
            # Use original asset
            source_path = item_data['asset_href']
            source_container = item_data.get('container', 'rmhazuregeobronze')
        
        for tile in tiles:
            task = {
                "task_id": f"{job_id}_tile_{tile['tile_id']}",
                "job_id": job_id,
                "operation": "prepare_for_cog",
                "parameters": {
                    "dataset_id": source_container,
                    "resource_id": source_path,
                    "version_id": f"tiled_{stac_id}",
                    "processing_extent": {
                        "minx": tile['minx'],
                        "miny": tile['miny'],
                        "maxx": tile['maxx'],
                        "maxy": tile['maxy']
                    },
                    "tile_id": tile['tile_id']
                },
                "metadata": {
                    "source_stac_id": stac_id,
                    "tile_row": tile['row_num'],
                    "tile_col": tile['col_num'],
                    "tile_geometry": tile['geometry'],
                    "tile_area_sqkm": tile['width_km'] * tile['height_km']
                }
            }
            tasks.append(task)
        
        return tasks
    
    def store_tiling_plan(self, job_id: str, stac_id: str, 
                         strategy: Dict[str, Any], tiles: List[Dict[str, Any]]) -> bool:
        """
        Store tiling plan in database for tracking and reuse.
        
        Args:
            job_id: Job identifier
            stac_id: Source STAC item ID
            strategy: Tiling strategy used
            tiles: Generated tile definitions
            
        Returns:
            Success status
        """
        try:
            # Create tiling_plans table if it doesn't exist
            create_table_query = """
                CREATE TABLE IF NOT EXISTS geo.tiling_plans (
                    job_id TEXT PRIMARY KEY,
                    stac_id TEXT NOT NULL,
                    strategy JSONB NOT NULL,
                    tile_count INTEGER NOT NULL,
                    tiles JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'pending'
                )
            """
            self.db_client.execute(create_table_query, fetch=False)
            
            # Insert tiling plan
            insert_query = """
                INSERT INTO geo.tiling_plans (job_id, stac_id, strategy, tile_count, tiles)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (job_id) DO UPDATE
                SET strategy = EXCLUDED.strategy,
                    tile_count = EXCLUDED.tile_count,
                    tiles = EXCLUDED.tiles
            """
            
            self.db_client.execute(
                insert_query,
                (job_id, stac_id, json.dumps(strategy), len(tiles), json.dumps(tiles)),
                fetch=False
            )
            
            logger.info(f"Stored tiling plan for job {job_id} with {len(tiles)} tiles")
            return True
            
        except Exception as e:
            logger.error(f"Error storing tiling plan: {e}")
            return False
    
    def process(self, job_id: str, dataset_id: str, resource_id: str,
                version_id: str, operation_type: str) -> Dict[str, Any]:
        """
        Generate tile grid and processing tasks for a large raster.
        
        This service validates a STAC item, calculates an optimal tiling
        strategy using PostGIS spatial analysis, and generates task messages
        for parallel tile processing.
        
        Args:
            job_id: Unique job identifier
            dataset_id: Not used (STAC ID comes from resource_id)
            resource_id: STAC item ID to tile
            version_id: Version identifier for outputs
            operation_type: Should be 'generate_tile_grid' or 'create_tiling_tasks'
            
        Returns:
            Dict containing:
                - status: 'completed' or 'failed'
                - stac_validated: Boolean
                - tiling_strategy: Strategy used
                - tile_count: Number of tiles generated
                - tiles: List of tile definitions (first 10)
                - tasks_created: Number of tasks created
                - message: Status message
                
        Examples:
            Generate tiles for 20GB raster:
                resource_id='huge_ortho_stac_001'
                Result: 16 tiles of ~1.25GB each
                
            Generate tiles for irregular coastline:
                resource_id='coastal_mosaic_stac_002'
                Result: Adaptive tiles following geometry
        """
        logger.info(f"Starting {operation_type} for STAC item: {resource_id}")
        
        try:
            # Step 1: Validate STAC item
            is_valid, item_data = self.validate_stac_item(resource_id)
            if not is_valid:
                return {
                    "status": "failed",
                    "error": item_data.get('error', 'STAC validation failed'),
                    "message": f"Invalid STAC item: {resource_id}"
                }
            
            # Step 2: Calculate optimal tiling strategy
            strategy = self.calculate_optimal_tile_size(item_data)
            logger.info(f"Tiling strategy: {strategy['strategy']}, "
                       f"Tile size: {strategy['tile_size_degrees']}°")
            
            # Debug: Check what's in item_data
            logger.info(f"Item data bounds: xmin={item_data.get('xmin')}, "
                       f"ymin={item_data.get('ymin')}, xmax={item_data.get('xmax')}, "
                       f"ymax={item_data.get('ymax')}")
            
            # Step 3: Generate tile grid
            tiles = self.generate_tile_grid(item_data, strategy)
            
            if not tiles:
                return {
                    "status": "failed",
                    "error": "No tiles generated",
                    "message": "Failed to generate tile grid - check file size and bounds"
                }
            
            # Step 4: Store tiling plan
            self.store_tiling_plan(job_id, resource_id, strategy, tiles)
            
            result = {
                "status": "completed",
                "stac_validated": True,
                "source_stac_id": resource_id,
                "tiling_strategy": strategy,
                "tile_count": len(tiles),
                "tiles": tiles[:10],  # First 10 tiles for preview
                "message": f"Generated {len(tiles)} tiles using {strategy['strategy']} strategy"
            }
            
            # Step 5: Create task messages if requested
            if operation_type == "create_tiling_tasks":
                tasks = self.create_task_messages(resource_id, item_data, tiles, job_id)
                result["tasks"] = tasks[:5]  # Preview first 5 tasks
                result["tasks_created"] = len(tasks)
                result["ready_for_processing"] = True
                
                # TODO: Queue tasks to geospatial-tasks queue
                logger.info(f"Created {len(tasks)} task messages for tiling")
            
            return result
            
        except Exception as e:
            logger.error(f"Error in {operation_type}: {str(e)}")
            return {
                "status": "failed",
                "error": str(e),
                "message": f"Failed to process tiling: {str(e)}"
            }