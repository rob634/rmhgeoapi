"""Unified STAC repository for PostGIS operations."""

import json
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from core.config import Config
from core.exceptions import DatabaseError
from utils.logger import logger


class STACRepository:
    """Unified STAC repository combining all PostGIS operations."""
    
    def __init__(self):
        """Initialize with connection parameters from config."""
        self.conn_params = {
            "host": Config.POSTGIS_HOST,
            "port": Config.POSTGIS_PORT,
            "database": Config.POSTGIS_DATABASE,
            "user": Config.POSTGIS_USER,
            "password": Config.POSTGIS_PASSWORD
        }
        self.schema = Config.POSTGIS_SCHEMA or "geo"
    
    def get_connection(self):
        """Get database connection."""
        try:
            return psycopg2.connect(**self.conn_params)
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise DatabaseError(f"Database connection failed: {e}")
    
    def upsert_collection(
        self,
        collection_id: str,
        title: str,
        description: str,
        spatial_extent: List[float] = None,
        temporal_extent: List[str] = None
    ) -> bool:
        """
        Insert or update a STAC collection.
        
        Args:
            collection_id: Unique collection identifier
            title: Collection title
            description: Collection description
            spatial_extent: Bounding box [minx, miny, maxx, maxy]
            temporal_extent: Time range [start, end]
            
        Returns:
            True if successful
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                # Default extents if not provided
                if not spatial_extent:
                    spatial_extent = [-180, -90, 180, 90]
                if not temporal_extent:
                    temporal_extent = [None, None]
                
                # Create bbox geometry
                bbox_wkt = f"POLYGON(({spatial_extent[0]} {spatial_extent[1]}, " \
                          f"{spatial_extent[2]} {spatial_extent[1]}, " \
                          f"{spatial_extent[2]} {spatial_extent[3]}, " \
                          f"{spatial_extent[0]} {spatial_extent[3]}, " \
                          f"{spatial_extent[0]} {spatial_extent[1]}))"
                
                query = f"""
                    INSERT INTO {self.schema}.collections (
                        id, title, description, 
                        spatial_extent, temporal_extent_start, temporal_extent_end,
                        created_at, updated_at
                    ) VALUES (
                        %s, %s, %s,
                        ST_GeomFromText(%s, 4326), %s, %s,
                        %s, %s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        description = EXCLUDED.description,
                        spatial_extent = EXCLUDED.spatial_extent,
                        temporal_extent_start = EXCLUDED.temporal_extent_start,
                        temporal_extent_end = EXCLUDED.temporal_extent_end,
                        updated_at = EXCLUDED.updated_at
                """
                
                now = datetime.now(timezone.utc)
                cur.execute(query, (
                    collection_id, title, description,
                    bbox_wkt, temporal_extent[0], temporal_extent[1],
                    now, now
                ))
                
                conn.commit()
                logger.info(f"Upserted collection: {collection_id}")
                return True
                
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to upsert collection: {e}")
            raise DatabaseError(f"Collection upsert failed: {e}")
        finally:
            conn.close()
    
    def upsert_item(
        self,
        collection_id: str,
        item_id: str,
        blob_name: str,
        metadata: Dict[str, Any]
    ) -> str:
        """
        Insert or update a STAC item.
        
        Args:
            collection_id: Collection this item belongs to
            item_id: Unique item identifier
            blob_name: Original blob name/path
            metadata: Item metadata including geometry and properties
            
        Returns:
            Item ID if successful
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                # Ensure collection exists
                self._ensure_collection_exists(cur, collection_id)
                
                # Extract geometry and bbox
                geometry = metadata.get("geometry", self._placeholder_geometry())
                bbox = metadata.get("bbox", [-0.001, -0.001, 0.001, 0.001])
                
                # Create bbox geometry for PostGIS
                bbox_wkt = f"POLYGON(({bbox[0]} {bbox[1]}, " \
                          f"{bbox[2]} {bbox[1]}, " \
                          f"{bbox[2]} {bbox[3]}, " \
                          f"{bbox[0]} {bbox[3]}, " \
                          f"{bbox[0]} {bbox[1]}))"
                
                # Prepare properties
                properties = {
                    k: v for k, v in metadata.items()
                    if k not in ["geometry", "bbox"]
                }
                properties["blob_name"] = blob_name
                
                query = f"""
                    INSERT INTO {self.schema}.items (
                        id, collection_id, geometry, bbox, properties,
                        datetime, created_at, updated_at
                    ) VALUES (
                        %s, %s, ST_GeomFromGeoJSON(%s), ST_GeomFromText(%s, 4326), %s,
                        %s, %s, %s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        geometry = EXCLUDED.geometry,
                        bbox = EXCLUDED.bbox,
                        properties = EXCLUDED.properties,
                        datetime = EXCLUDED.datetime,
                        updated_at = EXCLUDED.updated_at
                """
                
                now = datetime.now(timezone.utc)
                item_datetime = metadata.get("datetime", now.isoformat())
                
                cur.execute(query, (
                    item_id, collection_id, json.dumps(geometry), bbox_wkt,
                    json.dumps(properties), item_datetime, now, now
                ))
                
                conn.commit()
                logger.info(f"Upserted item: {item_id} in collection: {collection_id}")
                return item_id
                
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to upsert item: {e}")
            raise DatabaseError(f"Item upsert failed: {e}")
        finally:
            conn.close()
    
    def get_item(self, item_id: str) -> Optional[Dict]:
        """Get a STAC item by ID."""
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = f"""
                    SELECT 
                        id, collection_id,
                        ST_AsGeoJSON(geometry)::json as geometry,
                        ST_AsGeoJSON(bbox)::json as bbox,
                        properties,
                        datetime,
                        created_at,
                        updated_at
                    FROM {self.schema}.items
                    WHERE id = %s
                """
                cur.execute(query, (item_id,))
                result = cur.fetchone()
                
                if result:
                    return dict(result)
                return None
                
        except Exception as e:
            logger.error(f"Failed to get item: {e}")
            raise DatabaseError(f"Item retrieval failed: {e}")
        finally:
            conn.close()
    
    def search_items(
        self,
        collection_id: Optional[str] = None,
        bbox: Optional[List[float]] = None,
        datetime_range: Optional[tuple] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Search for STAC items.
        
        Args:
            collection_id: Filter by collection
            bbox: Spatial filter [minx, miny, maxx, maxy]
            datetime_range: Temporal filter (start, end)
            limit: Maximum results
            
        Returns:
            List of matching items
        """
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                conditions = []
                params = []
                
                if collection_id:
                    conditions.append("collection_id = %s")
                    params.append(collection_id)
                
                if bbox:
                    bbox_wkt = f"POLYGON(({bbox[0]} {bbox[1]}, " \
                              f"{bbox[2]} {bbox[1]}, " \
                              f"{bbox[2]} {bbox[3]}, " \
                              f"{bbox[0]} {bbox[3]}, " \
                              f"{bbox[0]} {bbox[1]}))"
                    conditions.append("ST_Intersects(geometry, ST_GeomFromText(%s, 4326))")
                    params.append(bbox_wkt)
                
                if datetime_range:
                    if datetime_range[0]:
                        conditions.append("datetime >= %s")
                        params.append(datetime_range[0])
                    if datetime_range[1]:
                        conditions.append("datetime <= %s")
                        params.append(datetime_range[1])
                
                where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                
                query = f"""
                    SELECT 
                        id, collection_id,
                        ST_AsGeoJSON(geometry)::json as geometry,
                        ST_AsGeoJSON(bbox)::json as bbox,
                        properties,
                        datetime
                    FROM {self.schema}.items
                    {where_clause}
                    ORDER BY datetime DESC
                    LIMIT %s
                """
                params.append(limit)
                
                cur.execute(query, params)
                results = cur.fetchall()
                
                return [dict(r) for r in results]
                
        except Exception as e:
            logger.error(f"Failed to search items: {e}")
            raise DatabaseError(f"Item search failed: {e}")
        finally:
            conn.close()
    
    def delete_item(self, item_id: str) -> bool:
        """Delete a STAC item."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                query = f"DELETE FROM {self.schema}.items WHERE id = %s"
                cur.execute(query, (item_id,))
                conn.commit()
                
                deleted = cur.rowcount > 0
                if deleted:
                    logger.info(f"Deleted item: {item_id}")
                return deleted
                
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to delete item: {e}")
            raise DatabaseError(f"Item deletion failed: {e}")
        finally:
            conn.close()
    
    def get_collection_stats(self, collection_id: str) -> Dict:
        """Get statistics for a collection."""
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = f"""
                    SELECT 
                        COUNT(*) as item_count,
                        MIN(datetime) as earliest_item,
                        MAX(datetime) as latest_item,
                        ST_Extent(geometry) as spatial_extent
                    FROM {self.schema}.items
                    WHERE collection_id = %s
                """
                cur.execute(query, (collection_id,))
                result = cur.fetchone()
                
                return dict(result) if result else {}
                
        except Exception as e:
            logger.error(f"Failed to get collection stats: {e}")
            raise DatabaseError(f"Collection stats failed: {e}")
        finally:
            conn.close()
    
    def _ensure_collection_exists(self, cursor, collection_id: str):
        """Ensure a collection exists, create if not."""
        check_query = f"SELECT id FROM {self.schema}.collections WHERE id = %s"
        cursor.execute(check_query, (collection_id,))
        
        if not cursor.fetchone():
            # Create basic collection
            insert_query = f"""
                INSERT INTO {self.schema}.collections (
                    id, title, description, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s)
            """
            now = datetime.now(timezone.utc)
            cursor.execute(insert_query, (
                collection_id,
                f"Collection: {collection_id}",
                f"Auto-created collection for {collection_id}",
                now, now
            ))
    
    def _placeholder_geometry(self) -> Dict:
        """Create placeholder polygon geometry."""
        return {
            "type": "Polygon",
            "coordinates": [[
                [-0.001, -0.001],
                [0.001, -0.001],
                [0.001, 0.001],
                [-0.001, 0.001],
                [-0.001, -0.001]
            ]]
        }