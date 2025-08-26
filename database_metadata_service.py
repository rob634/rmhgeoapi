"""
Database Metadata Service for querying and summarizing STAC catalog contents.
Provides container-like metadata interface for database tables.
"""
import json
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
import logging

from services import BaseProcessingService
from database_client import DatabaseClient


@dataclass
class CollectionMetadata:
    """Metadata for a STAC collection"""
    id: str
    title: Optional[str]
    description: Optional[str]
    item_count: int
    total_size_gb: float
    spatial_extent: Dict[str, Any]
    temporal_extent: Dict[str, Any]
    providers: List[str]
    file_types: List[str]
    crs_list: List[str]
    last_updated: str


@dataclass
class DatabaseSummary:
    """Overall database statistics"""
    total_collections: int
    total_items: int
    total_size_gb: float
    last_updated: str
    spatial_extent: Dict[str, Any]
    temporal_extent: Dict[str, Any]
    unique_crs: List[str]
    unique_file_types: List[str]


class DatabaseMetadataService(BaseProcessingService):
    """Service for querying and summarizing database metadata"""
    
    def __init__(self, repositories: Dict, logger: Optional[logging.Logger] = None):
        """Initialize the database metadata service"""
        super().__init__()
        self.repositories = repositories
        self.logger = logger or logging.getLogger(__name__)
        self.storage = repositories.get('storage')
        self.db_client = DatabaseClient()
    
    def get_supported_operations(self) -> List[str]:
        """Get list of supported operations."""
        return [
            'list_collections',
            'list_items', 
            'get_database_summary',
            'get_collection_details',
            'export_metadata',
            'query_spatial',
            'get_statistics'
        ]
    
    def process(self, operation: str, **kwargs) -> Dict[str, Any]:
        """
        Process database metadata operations.
        
        Args:
            operation: The operation to perform
            **kwargs: Operation-specific parameters
            
        Returns:
            Operation results
        """
        if operation == 'list_collections':
            return self.list_collections(**kwargs)
        elif operation == 'list_items':
            return self.list_items(**kwargs)
        elif operation == 'get_database_summary':
            return self.get_database_summary(**kwargs)
        elif operation == 'get_collection_details':
            return self.get_collection_details(**kwargs)
        elif operation == 'export_metadata':
            return self.export_metadata(**kwargs)
        else:
            raise ValueError(f"Unknown operation: {operation}")
    
    def list_collections(self, include_stats: bool = True) -> List[Dict[str, Any]]:
        """
        List all collections with optional statistics.
        
        Args:
            include_stats: Whether to include item counts and statistics
            
        Returns:
            List of collection metadata dictionaries
        """
        try:
            # Get all collections from database
            query = """
                SELECT 
                    c.id,
                    c.title,
                    c.description,
                    c.properties,
                    c.extent,
                    c.created_at,
                    c.updated_at,
                    COUNT(i.id) as item_count,
                    COALESCE(SUM((i.properties->>'file_size')::float) / 1073741824, 0) as total_size_gb
                FROM geo.collections c
                LEFT JOIN geo.items i ON c.id = i.collection_id
                GROUP BY c.id, c.title, c.description, c.properties, c.extent, c.created_at, c.updated_at
                ORDER BY c.id
            """
            
            collections = self.db_client.execute(query)
            
            if not include_stats:
                return [self._format_collection_basic(c) for c in collections]
            
            # Get detailed stats for each collection
            result = []
            for collection in collections:
                metadata = self._get_collection_metadata(collection)
                result.append(asdict(metadata))
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error listing collections: {e}")
            raise
    
    def list_items(
        self,
        collection_id: Optional[str] = None,
        bbox: Optional[List[float]] = None,
        datetime_range: Optional[Tuple[str, str]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        List items with optional filtering.
        
        Args:
            collection_id: Filter by collection
            bbox: Bounding box filter [minx, miny, maxx, maxy]
            datetime_range: Tuple of (start_datetime, end_datetime)
            limit: Maximum items to return
            offset: Pagination offset
            
        Returns:
            Dictionary with items and metadata
        """
        try:
            # Build query with filters
            conditions = []
            params = []
            
            base_query = """
                SELECT 
                    i.id,
                    i.collection_id,
                    i.properties,
                    ST_AsGeoJSON(i.geometry) as geometry,
                    ST_AsGeoJSON(i.bbox) as bbox,
                    i.created_at,
                    i.updated_at
                FROM geo.items i
            """
            
            if collection_id:
                conditions.append("i.collection_id = %s")
                params.append(collection_id)
            
            if bbox and len(bbox) == 4:
                conditions.append("""
                    ST_Intersects(
                        i.geometry,
                        ST_MakeEnvelope(%s, %s, %s, %s, 4326)
                    )
                """)
                params.extend(bbox)
            
            if datetime_range:
                start_dt, end_dt = datetime_range
                conditions.append("(i.properties->>'datetime')::timestamp BETWEEN %s AND %s")
                params.extend([start_dt, end_dt])
            
            # Add conditions to query
            if conditions:
                base_query += " WHERE " + " AND ".join(conditions)
            
            # Get total count
            count_query = base_query.replace(
                "SELECT i.id, i.collection_id, i.properties, ST_AsGeoJSON(i.geometry) as geometry, ST_AsGeoJSON(i.bbox) as bbox, i.created_at, i.updated_at",
                "SELECT COUNT(*)"
            )
            total_count = self.db_client.execute(count_query, params)[0]['count']
            
            # Add pagination
            base_query += f" ORDER BY i.created_at DESC LIMIT {limit} OFFSET {offset}"
            
            items = self.db_client.execute(base_query, params)
            
            # Format items
            formatted_items = []
            for item in items:
                formatted_item = {
                    'id': item['id'],
                    'collection_id': item['collection_id'],
                    'properties': item['properties'],
                    'geometry': json.loads(item['geometry']) if item['geometry'] else None,
                    'bbox': json.loads(item['bbox']) if item['bbox'] else None,
                    'created_at': item['created_at'].isoformat() if item['created_at'] else None,
                    'updated_at': item['updated_at'].isoformat() if item['updated_at'] else None
                }
                formatted_items.append(formatted_item)
            
            return {
                'type': 'FeatureCollection',
                'features': formatted_items,
                'total_count': total_count,
                'limit': limit,
                'offset': offset,
                'filters': {
                    'collection_id': collection_id,
                    'bbox': bbox,
                    'datetime_range': datetime_range
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error listing items: {e}")
            raise
    
    def get_database_summary(self) -> Dict[str, Any]:
        """
        Get overall database statistics and summary.
        
        Returns:
            Dictionary with database summary statistics
        """
        try:
            # Get overall statistics
            stats_query = """
                WITH stats AS (
                    SELECT 
                        COUNT(DISTINCT c.id) as collection_count,
                        COUNT(DISTINCT i.id) as item_count,
                        COALESCE(SUM((i.properties->>'file_size')::float) / 1073741824, 0) as total_size_gb,
                        MIN((i.properties->>'datetime')::timestamp) as min_datetime,
                        MAX((i.properties->>'datetime')::timestamp) as max_datetime
                    FROM geo.collections c
                    LEFT JOIN geo.items i ON c.id = i.collection_id
                ),
                spatial_extent AS (
                    SELECT 
                        ST_Extent(i.geometry) as extent
                    FROM geo.items i
                    WHERE i.geometry IS NOT NULL
                ),
                unique_values AS (
                    SELECT 
                        array_agg(DISTINCT i.properties->>'crs') FILTER (WHERE i.properties->>'crs' IS NOT NULL) as crs_list,
                        array_agg(DISTINCT i.properties->>'file_extension') FILTER (WHERE i.properties->>'file_extension' IS NOT NULL) as file_types
                    FROM geo.items i
                )
                SELECT 
                    s.*,
                    ST_AsGeoJSON(se.extent) as spatial_extent,
                    uv.crs_list,
                    uv.file_types
                FROM stats s
                CROSS JOIN spatial_extent se
                CROSS JOIN unique_values uv
            """
            
            result = self.db_client.execute(stats_query)[0]
            
            # Parse spatial extent
            spatial_extent = None
            if result['spatial_extent']:
                extent_geom = json.loads(result['spatial_extent'])
                if extent_geom and 'coordinates' in extent_geom:
                    coords = extent_geom['coordinates'][0]
                    spatial_extent = {
                        'bbox': [
                            min(c[0] for c in coords),  # minx
                            min(c[1] for c in coords),  # miny
                            max(c[0] for c in coords),  # maxx
                            max(c[1] for c in coords)   # maxy
                        ]
                    }
            
            # Build summary
            summary = DatabaseSummary(
                total_collections=result['collection_count'] or 0,
                total_items=result['item_count'] or 0,
                total_size_gb=float(result['total_size_gb'] or 0),
                last_updated=datetime.utcnow().isoformat() + 'Z',
                spatial_extent=spatial_extent or {'bbox': None},
                temporal_extent={
                    'interval': [
                        [
                            result['min_datetime'].isoformat() if result['min_datetime'] else None,
                            result['max_datetime'].isoformat() if result['max_datetime'] else None
                        ]
                    ]
                },
                unique_crs=result['crs_list'] or [],
                unique_file_types=result['file_types'] or []
            )
            
            # Get additional statistics
            statistics = self._get_database_statistics()
            
            # Get collections list
            collections = self.list_collections(include_stats=True)
            
            return {
                'summary': asdict(summary),
                'collections': collections,
                'statistics': statistics
            }
            
        except Exception as e:
            self.logger.error(f"Error getting database summary: {e}")
            raise
    
    def get_collection_details(self, collection_id: str) -> Dict[str, Any]:
        """
        Get detailed metadata for a specific collection.
        
        Args:
            collection_id: The collection ID to query
            
        Returns:
            Detailed collection metadata dictionary
        """
        try:
            # Get collection with stats
            query = """
                SELECT 
                    c.*,
                    COUNT(i.id) as item_count,
                    COALESCE(SUM((i.properties->>'file_size')::float) / 1073741824, 0) as total_size_gb,
                    array_agg(DISTINCT i.properties->>'crs') FILTER (WHERE i.properties->>'crs' IS NOT NULL) as crs_list,
                    array_agg(DISTINCT i.properties->>'file_extension') FILTER (WHERE i.properties->>'file_extension' IS NOT NULL) as file_types,
                    array_agg(DISTINCT i.properties->>'provider') FILTER (WHERE i.properties->>'provider' IS NOT NULL) as providers,
                    ST_Extent(i.geometry) as spatial_extent,
                    MIN((i.properties->>'datetime')::timestamp) as min_datetime,
                    MAX((i.properties->>'datetime')::timestamp) as max_datetime
                FROM geo.collections c
                LEFT JOIN geo.items i ON c.id = i.collection_id
                WHERE c.id = %s
                GROUP BY c.id, c.title, c.description, c.properties, c.extent, c.created_at, c.updated_at
            """
            
            result = self.db_client.execute(query, [collection_id])
            
            if not result:
                raise ValueError(f"Collection '{collection_id}' not found")
            
            collection = result[0]
            
            # Get item statistics by date
            date_stats_query = """
                SELECT 
                    DATE((properties->>'datetime')::timestamp) as date,
                    COUNT(*) as item_count,
                    SUM((properties->>'file_size')::float) / 1073741824 as size_gb
                FROM geo.items
                WHERE collection_id = %s
                    AND properties->>'datetime' IS NOT NULL
                GROUP BY DATE((properties->>'datetime')::timestamp)
                ORDER BY date DESC
                LIMIT 30
            """
            
            date_stats = self.db_client.execute(date_stats_query, [collection_id])
            
            # Get sample items
            sample_items = self.list_items(
                collection_id=collection_id,
                limit=10
            )
            
            # Format spatial extent
            spatial_extent = None
            if collection['spatial_extent']:
                bbox = collection['spatial_extent']
                spatial_extent = {
                    'bbox': [bbox[0], bbox[1], bbox[2], bbox[3]]
                }
            
            return {
                'collection': {
                    'id': collection['id'],
                    'title': collection['title'],
                    'description': collection['description'],
                    'properties': collection['properties'],
                    'created_at': collection['created_at'].isoformat() if collection['created_at'] else None,
                    'updated_at': collection['updated_at'].isoformat() if collection['updated_at'] else None
                },
                'statistics': {
                    'item_count': collection['item_count'],
                    'total_size_gb': float(collection['total_size_gb'] or 0),
                    'crs_list': collection['crs_list'] or [],
                    'file_types': collection['file_types'] or [],
                    'providers': collection['providers'] or [],
                    'spatial_extent': spatial_extent,
                    'temporal_extent': {
                        'interval': [
                            [
                                collection['min_datetime'].isoformat() if collection['min_datetime'] else None,
                                collection['max_datetime'].isoformat() if collection['max_datetime'] else None
                            ]
                        ]
                    }
                },
                'recent_activity': [
                    {
                        'date': stat['date'].isoformat() if stat['date'] else None,
                        'item_count': stat['item_count'],
                        'size_gb': float(stat['size_gb'] or 0)
                    }
                    for stat in date_stats
                ],
                'sample_items': sample_items['features'][:5]  # Just first 5 for sample
            }
            
        except Exception as e:
            self.logger.error(f"Error getting collection details: {e}")
            raise
    
    def export_metadata(
        self,
        format: str = 'json',
        include_items: bool = False,
        output_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Export database metadata in specified format.
        
        Args:
            format: Export format ('json', 'geojson', 'csv')
            include_items: Whether to include all items in export
            output_path: Optional path to save export
            
        Returns:
            Exported metadata dictionary
        """
        try:
            # Get base metadata
            metadata = self.get_database_summary()
            
            # Optionally include all items
            if include_items:
                all_items = []
                offset = 0
                limit = 1000
                
                while True:
                    batch = self.list_items(limit=limit, offset=offset)
                    all_items.extend(batch['features'])
                    
                    if len(batch['features']) < limit:
                        break
                    offset += limit
                
                metadata['items'] = all_items
            
            # Format based on type
            if format == 'geojson':
                # Convert to GeoJSON FeatureCollection
                features = []
                
                # Add collections as features
                for collection in metadata['collections']:
                    if collection.get('spatial_extent') and collection['spatial_extent'].get('bbox'):
                        bbox = collection['spatial_extent']['bbox']
                        features.append({
                            'type': 'Feature',
                            'properties': {
                                'type': 'collection',
                                'id': collection['id'],
                                'title': collection.get('title'),
                                'item_count': collection.get('item_count', 0),
                                'total_size_gb': collection.get('total_size_gb', 0)
                            },
                            'geometry': {
                                'type': 'Polygon',
                                'coordinates': [[
                                    [bbox[0], bbox[1]],
                                    [bbox[2], bbox[1]],
                                    [bbox[2], bbox[3]],
                                    [bbox[0], bbox[3]],
                                    [bbox[0], bbox[1]]
                                ]]
                            }
                        })
                
                # Add items if included
                if include_items and 'items' in metadata:
                    features.extend(metadata['items'])
                
                result = {
                    'type': 'FeatureCollection',
                    'features': features,
                    'properties': metadata['summary']
                }
                
            elif format == 'csv':
                # For CSV, flatten the structure
                import csv
                import io
                
                output = io.StringIO()
                
                # Write collections CSV
                if metadata['collections']:
                    fieldnames = ['id', 'title', 'item_count', 'total_size_gb', 'crs_list', 'file_types']
                    writer = csv.DictWriter(output, fieldnames=fieldnames)
                    writer.writeheader()
                    
                    for collection in metadata['collections']:
                        row = {
                            'id': collection['id'],
                            'title': collection.get('title', ''),
                            'item_count': collection.get('item_count', 0),
                            'total_size_gb': collection.get('total_size_gb', 0),
                            'crs_list': ','.join(collection.get('crs_list', [])),
                            'file_types': ','.join(collection.get('file_types', []))
                        }
                        writer.writerow(row)
                
                result = {'csv': output.getvalue()}
                
            else:
                # Default to JSON
                result = metadata
            
            # Optionally save to file
            if output_path:
                if self.storage:
                    # Save to blob storage
                    container = 'rmhazuregeoinventory'
                    blob_name = f"database/{output_path}"
                    
                    content = json.dumps(result, indent=2) if format != 'csv' else result['csv']
                    self.storage.upload_blob(container, blob_name, content.encode('utf-8'))
                    
                    self.logger.info(f"Exported metadata to {container}/{blob_name}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error exporting metadata: {e}")
            raise
    
    def _get_collection_metadata(self, collection: Dict) -> CollectionMetadata:
        """Get detailed metadata for a collection"""
        try:
            # Get additional stats for this collection
            stats_query = """
                SELECT 
                    array_agg(DISTINCT properties->>'crs') FILTER (WHERE properties->>'crs' IS NOT NULL) as crs_list,
                    array_agg(DISTINCT properties->>'file_extension') FILTER (WHERE properties->>'file_extension' IS NOT NULL) as file_types,
                    array_agg(DISTINCT properties->>'provider') FILTER (WHERE properties->>'provider' IS NOT NULL) as providers,
                    ST_Extent(geometry) as spatial_extent,
                    MIN((properties->>'datetime')::timestamp) as min_datetime,
                    MAX((properties->>'datetime')::timestamp) as max_datetime
                FROM geo.items
                WHERE collection_id = %s
            """
            
            stats = self.db_client.execute(stats_query, [collection['id']])[0]
            
            # Parse spatial extent
            spatial_extent = {'bbox': None}
            if stats['spatial_extent']:
                bbox = stats['spatial_extent']
                spatial_extent = {
                    'bbox': [bbox[0], bbox[1], bbox[2], bbox[3]]
                }
            
            # Parse temporal extent
            temporal_extent = {
                'interval': [[
                    stats['min_datetime'].isoformat() if stats['min_datetime'] else None,
                    stats['max_datetime'].isoformat() if stats['max_datetime'] else None
                ]]
            }
            
            return CollectionMetadata(
                id=collection['id'],
                title=collection.get('title'),
                description=collection.get('description'),
                item_count=collection.get('item_count', 0),
                total_size_gb=float(collection.get('total_size_gb', 0)),
                spatial_extent=spatial_extent,
                temporal_extent=temporal_extent,
                providers=stats['providers'] or [],
                file_types=stats['file_types'] or [],
                crs_list=stats['crs_list'] or [],
                last_updated=collection['updated_at'].isoformat() if collection.get('updated_at') else datetime.utcnow().isoformat()
            )
            
        except Exception as e:
            self.logger.error(f"Error getting collection metadata: {e}")
            # Return basic metadata on error
            return CollectionMetadata(
                id=collection['id'],
                title=collection.get('title'),
                description=collection.get('description'),
                item_count=collection.get('item_count', 0),
                total_size_gb=float(collection.get('total_size_gb', 0)),
                spatial_extent={'bbox': None},
                temporal_extent={'interval': [[None, None]]},
                providers=[],
                file_types=[],
                crs_list=[],
                last_updated=datetime.utcnow().isoformat()
            )
    
    def _format_collection_basic(self, collection: Dict) -> Dict[str, Any]:
        """Format basic collection info without stats"""
        return {
            'id': collection['id'],
            'title': collection.get('title'),
            'description': collection.get('description'),
            'properties': collection.get('properties'),
            'created_at': collection['created_at'].isoformat() if collection.get('created_at') else None,
            'updated_at': collection['updated_at'].isoformat() if collection.get('updated_at') else None
        }
    
    def _get_database_statistics(self) -> Dict[str, Any]:
        """Get additional database statistics"""
        try:
            # Items by collection
            collection_stats_query = """
                SELECT 
                    collection_id,
                    COUNT(*) as count,
                    SUM((properties->>'file_size')::float) / 1073741824 as size_gb
                FROM geo.items
                GROUP BY collection_id
                ORDER BY count DESC
            """
            
            collection_stats = self.db_client.execute(collection_stats_query)
            
            # Items by file type
            file_type_stats_query = """
                SELECT 
                    properties->>'file_extension' as file_type,
                    COUNT(*) as count,
                    SUM((properties->>'file_size')::float) / 1073741824 as size_gb
                FROM geo.items
                WHERE properties->>'file_extension' IS NOT NULL
                GROUP BY properties->>'file_extension'
                ORDER BY count DESC
            """
            
            file_type_stats = self.db_client.execute(file_type_stats_query)
            
            # Items by date (last 30 days)
            date_stats_query = """
                SELECT 
                    DATE((properties->>'datetime')::timestamp) as date,
                    COUNT(*) as count
                FROM geo.items
                WHERE properties->>'datetime' IS NOT NULL
                    AND (properties->>'datetime')::timestamp > CURRENT_TIMESTAMP - INTERVAL '30 days'
                GROUP BY DATE((properties->>'datetime')::timestamp)
                ORDER BY date DESC
            """
            
            date_stats = self.db_client.execute(date_stats_query)
            
            return {
                'items_by_collection': {
                    stat['collection_id']: {
                        'count': stat['count'],
                        'size_gb': float(stat['size_gb'] or 0)
                    }
                    for stat in collection_stats
                },
                'items_by_file_type': {
                    stat['file_type']: {
                        'count': stat['count'],
                        'size_gb': float(stat['size_gb'] or 0)
                    }
                    for stat in file_type_stats
                },
                'items_by_date': [
                    {
                        'date': stat['date'].isoformat() if stat['date'] else None,
                        'count': stat['count']
                    }
                    for stat in date_stats
                ]
            }
            
        except Exception as e:
            self.logger.error(f"Error getting database statistics: {e}")
            return {}