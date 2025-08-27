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
            'get_statistics',
            'verify_stac_tables',
            'clear_stac_tables'  # DANGEROUS - for testing only
        ]
    
    def process(self, job_id: str, dataset_id: str, resource_id: str, 
                version_id: str, operation_type: str, **kwargs) -> Dict[str, Any]:
        """
        Process database metadata operations.
        
        Args:
            job_id: Unique job identifier
            dataset_id: Dataset identifier
            resource_id: Resource identifier
            version_id: Version identifier
            operation_type: The operation to perform
            **kwargs: Operation-specific parameters
            
        Returns:
            Operation results
        """
        if operation_type == 'list_collections':
            return self.list_collections(**kwargs)
        elif operation_type == 'list_items':
            return self.list_items(**kwargs)
        elif operation_type == 'get_database_summary':
            return self.get_database_summary(**kwargs)
        elif operation_type == 'get_collection_details':
            return self.get_collection_details(**kwargs)
        elif operation_type == 'export_metadata':
            return self.export_metadata(**kwargs)
        elif operation_type == 'verify_stac_tables':
            return self.verify_stac_tables(**kwargs)
        elif operation_type == 'clear_stac_tables':
            return self.clear_stac_tables(**kwargs)
        else:
            raise ValueError(f"Unknown operation: {operation_type}")
    
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
    
    def verify_stac_tables(self, detailed: bool = False) -> Dict[str, Any]:
        """
        Comprehensive STAC database validation and health check.
        
        Validates table structure, data integrity, spatial accuracy, and performance.
        Useful for corporate networks where direct database access is blocked.
        
        Args:
            detailed: Include detailed analysis (slower but more comprehensive)
            
        Returns:
            Comprehensive validation report
        """
        self.logger.info("🔍 Starting comprehensive STAC table validation")
        validation_report = {
            'status': 'unknown',
            'timestamp': datetime.utcnow().isoformat(),
            'checks': {}
        }
        
        try:
            # 1. Table Existence and Structure
            self.logger.info("📋 Checking table structure...")
            structure_check = self._validate_table_structure()
            validation_report['checks']['table_structure'] = structure_check
            
            # 2. Data Integrity
            self.logger.info("🔍 Validating data integrity...")
            integrity_check = self._validate_data_integrity()
            validation_report['checks']['data_integrity'] = integrity_check
            
            # 3. Spatial Data Validation
            self.logger.info("🌍 Checking spatial data accuracy...")
            spatial_check = self._validate_spatial_data()
            validation_report['checks']['spatial_validation'] = spatial_check
            
            # 4. Performance and Indexes
            self.logger.info("⚡ Analyzing performance and indexes...")
            performance_check = self._validate_performance()
            validation_report['checks']['performance'] = performance_check
            
            # 5. Collection Completeness
            self.logger.info("📊 Checking collection completeness...")
            completeness_check = self._validate_collection_completeness()
            validation_report['checks']['collection_completeness'] = completeness_check
            
            if detailed:
                # 6. Detailed Asset Validation (slower)
                self.logger.info("🔗 Validating asset URLs and metadata...")
                asset_check = self._validate_assets_detailed()
                validation_report['checks']['asset_validation'] = asset_check
                
                # 7. Quality Metrics
                self.logger.info("📈 Generating quality metrics...")
                quality_metrics = self._generate_quality_metrics()
                validation_report['checks']['quality_metrics'] = quality_metrics
            
            # Determine overall status
            failed_checks = sum(1 for check in validation_report['checks'].values() 
                              if check.get('status') == 'failed')
            warning_checks = sum(1 for check in validation_report['checks'].values() 
                               if check.get('status') == 'warning')
            
            if failed_checks > 0:
                validation_report['status'] = 'failed'
                validation_report['summary'] = f"{failed_checks} critical issues found"
            elif warning_checks > 0:
                validation_report['status'] = 'warning'
                validation_report['summary'] = f"{warning_checks} warnings found"
            else:
                validation_report['status'] = 'healthy'
                validation_report['summary'] = "All checks passed"
            
            self.logger.info(f"✅ STAC validation complete: {validation_report['summary']}")
            return validation_report
            
        except Exception as e:
            self.logger.error(f"❌ Error during STAC validation: {e}")
            validation_report['status'] = 'error'
            validation_report['error'] = str(e)
            return validation_report
    
    def _validate_table_structure(self) -> Dict[str, Any]:
        """Validate STAC table structure and schema"""
        try:
            # Check required tables exist
            tables_query = """
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'geo' 
                AND table_name IN ('collections', 'items')
            """
            tables = self.db_client.execute(tables_query)
            table_names = [t['table_name'] for t in tables]
            
            # Check required columns
            items_columns_query = """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns 
                WHERE table_schema = 'geo' AND table_name = 'items'
                ORDER BY ordinal_position
            """
            items_columns = self.db_client.execute(items_columns_query)
            
            # Validate essential columns exist
            required_columns = ['id', 'collection_id', 'geometry', 'bbox', 'properties', 'assets']
            existing_columns = [col['column_name'] for col in items_columns]
            missing_columns = [col for col in required_columns if col not in existing_columns]
            
            return {
                'status': 'passed' if not missing_columns else 'failed',
                'tables_found': table_names,
                'required_tables': ['collections', 'items'],
                'missing_tables': [t for t in ['collections', 'items'] if t not in table_names],
                'items_columns': len(items_columns),
                'missing_columns': missing_columns,
                'message': 'Table structure valid' if not missing_columns else f'Missing columns: {missing_columns}'
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
                'message': 'Failed to validate table structure'
            }
    
    def _validate_data_integrity(self) -> Dict[str, Any]:
        """Validate data integrity and consistency"""
        try:
            integrity_query = """
                WITH integrity_stats AS (
                    SELECT 
                        COUNT(*) as total_items,
                        COUNT(CASE WHEN id IS NULL THEN 1 END) as null_ids,
                        COUNT(CASE WHEN collection_id IS NULL THEN 1 END) as null_collections,
                        COUNT(CASE WHEN geometry IS NULL THEN 1 END) as null_geometries,
                        COUNT(CASE WHEN bbox IS NULL THEN 1 END) as null_bboxes,
                        COUNT(CASE WHEN properties IS NULL THEN 1 END) as null_properties,
                        COUNT(CASE WHEN assets IS NULL THEN 1 END) as null_assets
                    FROM geo.items
                ),
                collection_stats AS (
                    SELECT 
                        COUNT(DISTINCT i.collection_id) as collections_in_items,
                        COUNT(DISTINCT c.id) as collections_in_table
                    FROM geo.items i
                    FULL OUTER JOIN geo.collections c ON i.collection_id = c.id
                )
                SELECT 
                    i.*,
                    c.collections_in_items,
                    c.collections_in_table
                FROM integrity_stats i, collection_stats c
            """
            
            result = self.db_client.execute(integrity_query)[0]
            
            # Check for integrity issues
            issues = []
            if result['null_ids'] > 0:
                issues.append(f"{result['null_ids']} items with null IDs")
            if result['null_collections'] > 0:
                issues.append(f"{result['null_collections']} items with null collection_id")
            if result['null_geometries'] > 0:
                issues.append(f"{result['null_geometries']} items with null geometry")
            if result['collections_in_items'] != result['collections_in_table']:
                issues.append(f"Collection mismatch: {result['collections_in_items']} referenced vs {result['collections_in_table']} exist")
            
            return {
                'status': 'passed' if not issues else 'warning',
                'total_items': result['total_items'],
                'collections_referenced': result['collections_in_items'],
                'collections_exist': result['collections_in_table'],
                'integrity_issues': issues,
                'message': 'Data integrity good' if not issues else f"{len(issues)} integrity issues found"
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
                'message': 'Failed to validate data integrity'
            }
    
    def _validate_spatial_data(self) -> Dict[str, Any]:
        """Validate spatial data accuracy and consistency"""
        try:
            spatial_query = """
                WITH spatial_stats AS (
                    SELECT 
                        COUNT(*) as total_items,
                        COUNT(CASE WHEN ST_IsValid(geometry) THEN 1 END) as valid_geometries,
                        COUNT(CASE WHEN ST_IsValid(bbox) THEN 1 END) as valid_bboxes,
                        COUNT(CASE WHEN geometry IS NOT NULL AND bbox IS NOT NULL 
                                   AND ST_Contains(ST_Envelope(geometry), bbox) THEN 1 END) as consistent_bounds,
                        AVG(ST_Area(geometry::geography)) / 1000000 as avg_area_km2,
                        COUNT(CASE WHEN ST_SRID(geometry) = 4326 THEN 1 END) as wgs84_items
                    FROM geo.items 
                    WHERE geometry IS NOT NULL
                )
                SELECT * FROM spatial_stats
            """
            
            result = self.db_client.execute(spatial_query)[0]
            
            # Calculate percentages
            total = result['total_items']
            valid_geom_pct = (result['valid_geometries'] / total * 100) if total > 0 else 0
            valid_bbox_pct = (result['valid_bboxes'] / total * 100) if total > 0 else 0
            wgs84_pct = (result['wgs84_items'] / total * 100) if total > 0 else 0
            
            # Determine status
            issues = []
            if valid_geom_pct < 95:
                issues.append(f"Only {valid_geom_pct:.1f}% geometries are valid")
            if valid_bbox_pct < 95:
                issues.append(f"Only {valid_bbox_pct:.1f}% bboxes are valid")
            if wgs84_pct < 90:
                issues.append(f"Only {wgs84_pct:.1f}% items use WGS84")
            
            return {
                'status': 'passed' if not issues else 'warning',
                'total_items': total,
                'valid_geometries': f"{valid_geom_pct:.1f}%",
                'valid_bboxes': f"{valid_bbox_pct:.1f}%", 
                'wgs84_compliance': f"{wgs84_pct:.1f}%",
                'avg_area_km2': round(result['avg_area_km2'], 2) if result['avg_area_km2'] else 0,
                'spatial_issues': issues,
                'message': 'Spatial data accurate' if not issues else f"{len(issues)} spatial issues found"
            }
            
        except Exception as e:
            return {
                'status': 'error', 
                'error': str(e),
                'message': 'Failed to validate spatial data'
            }
    
    def _validate_performance(self) -> Dict[str, Any]:
        """Validate database performance and indexes"""
        try:
            # Check for spatial indexes
            index_query = """
                SELECT 
                    schemaname,
                    tablename,
                    indexname,
                    indexdef
                FROM pg_indexes 
                WHERE schemaname = 'geo' 
                AND tablename IN ('items', 'collections')
                AND indexdef ILIKE '%gist%'
            """
            
            indexes = self.db_client.execute(index_query)
            
            # Check query performance with EXPLAIN
            perf_query = """
                EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                SELECT id, collection_id, ST_AsGeoJSON(geometry) as geom
                FROM geo.items 
                WHERE ST_Intersects(geometry, ST_MakeEnvelope(-180, -90, 180, 90, 4326))
                LIMIT 100
            """
            
            try:
                perf_result = self.db_client.execute(perf_query)
                execution_time = perf_result[0]['QUERY PLAN'][0]['Execution Time']
            except:
                execution_time = None
            
            # Performance recommendations
            recommendations = []
            has_geometry_index = any('geometry' in idx['indexdef'] for idx in indexes)
            has_bbox_index = any('bbox' in idx['indexdef'] for idx in indexes)
            
            if not has_geometry_index:
                recommendations.append("Add GIST index on geometry column")
            if not has_bbox_index:
                recommendations.append("Add GIST index on bbox column")
            if execution_time and execution_time > 1000:  # >1 second
                recommendations.append("Query performance is slow, consider index optimization")
            
            return {
                'status': 'passed' if not recommendations else 'warning',
                'spatial_indexes': len(indexes),
                'has_geometry_index': has_geometry_index,
                'has_bbox_index': has_bbox_index,
                'query_time_ms': execution_time,
                'recommendations': recommendations,
                'message': 'Performance optimal' if not recommendations else f"{len(recommendations)} performance recommendations"
            }
            
        except Exception as e:
            return {
                'status': 'warning',
                'error': str(e),
                'message': 'Could not fully validate performance'
            }
    
    def _validate_collection_completeness(self) -> Dict[str, Any]:
        """Validate collection metadata completeness"""
        try:
            completeness_query = """
                SELECT 
                    c.id,
                    c.title IS NOT NULL as has_title,
                    c.description IS NOT NULL as has_description,
                    c.extent IS NOT NULL as has_extent,
                    COUNT(i.id) as item_count
                FROM geo.collections c
                LEFT JOIN geo.items i ON c.id = i.collection_id
                GROUP BY c.id, c.title, c.description, c.extent
                ORDER BY item_count DESC
            """
            
            collections = self.db_client.execute(completeness_query)
            
            # Analyze completeness
            total_collections = len(collections)
            collections_with_items = sum(1 for c in collections if c['item_count'] > 0)
            complete_metadata = sum(1 for c in collections 
                                  if c['has_title'] and c['has_description'] and c['has_extent'])
            
            incomplete_collections = [c['id'] for c in collections 
                                    if not (c['has_title'] and c['has_description'] and c['has_extent'])]
            
            return {
                'status': 'passed' if not incomplete_collections else 'warning',
                'total_collections': total_collections,
                'collections_with_items': collections_with_items,
                'complete_metadata': f"{complete_metadata}/{total_collections}",
                'incomplete_collections': incomplete_collections,
                'collection_details': collections,
                'message': 'All collections complete' if not incomplete_collections else f"{len(incomplete_collections)} collections need metadata"
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
                'message': 'Failed to validate collection completeness'
            }
    
    def _validate_assets_detailed(self) -> Dict[str, Any]:
        """Detailed validation of asset URLs and metadata (slower)"""
        try:
            # Sample asset validation (don't check all assets as it would be too slow)
            asset_query = """
                SELECT 
                    id,
                    collection_id,
                    assets
                FROM geo.items
                WHERE assets IS NOT NULL
                ORDER BY RANDOM()
                LIMIT 50
            """
            
            items = self.db_client.execute(asset_query)
            
            asset_issues = []
            total_assets = 0
            valid_urls = 0
            
            for item in items:
                assets = item['assets'] if isinstance(item['assets'], dict) else {}
                for asset_key, asset_info in assets.items():
                    total_assets += 1
                    href = asset_info.get('href', '')
                    
                    # Basic URL validation
                    if href.startswith('https://') and 'blob.core.windows.net' in href:
                        valid_urls += 1
                    else:
                        asset_issues.append(f"Invalid URL in {item['id']}: {asset_key}")
            
            url_validity_pct = (valid_urls / total_assets * 100) if total_assets > 0 else 0
            
            return {
                'status': 'passed' if url_validity_pct > 90 else 'warning',
                'items_checked': len(items),
                'total_assets_checked': total_assets,
                'valid_url_percentage': f"{url_validity_pct:.1f}%",
                'asset_issues': asset_issues[:10],  # Limit to first 10 issues
                'message': f'Asset validation: {url_validity_pct:.1f}% URLs valid'
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
                'message': 'Failed to validate assets'
            }
    
    def _generate_quality_metrics(self) -> Dict[str, Any]:
        """Generate comprehensive quality metrics"""
        try:
            metrics_query = """
                WITH quality_metrics AS (
                    SELECT 
                        COUNT(*) as total_items,
                        COUNT(CASE WHEN properties->>'vendor' IS NOT NULL THEN 1 END) as items_with_vendor,
                        COUNT(CASE WHEN properties->>'is_cog' = 'true' THEN 1 END) as cog_items,
                        COUNT(CASE WHEN properties->>'datetime' IS NOT NULL THEN 1 END) as items_with_datetime,
                        COUNT(CASE WHEN properties->>'proj:epsg' IS NOT NULL THEN 1 END) as items_with_crs,
                        COUNT(CASE WHEN ST_Area(geometry::geography) > 0 THEN 1 END) as items_with_area,
                        SUM((properties->>'file:size')::bigint) / 1073741824 as total_size_gb
                    FROM geo.items
                ),
                vendor_breakdown AS (
                    SELECT 
                        properties->>'vendor' as vendor,
                        COUNT(*) as count
                    FROM geo.items
                    WHERE properties->>'vendor' IS NOT NULL
                    GROUP BY properties->>'vendor'
                    ORDER BY count DESC
                )
                SELECT 
                    q.*,
                    json_agg(json_build_object('vendor', v.vendor, 'count', v.count)) as vendor_breakdown
                FROM quality_metrics q, vendor_breakdown v
                GROUP BY q.total_items, q.items_with_vendor, q.cog_items, 
                         q.items_with_datetime, q.items_with_crs, q.items_with_area, q.total_size_gb
            """
            
            result = self.db_client.execute(metrics_query)[0]
            
            total = result['total_items']
            
            # Calculate quality percentages
            vendor_id_pct = (result['items_with_vendor'] / total * 100) if total > 0 else 0
            cog_optimized_pct = (result['cog_items'] / total * 100) if total > 0 else 0
            datetime_complete_pct = (result['items_with_datetime'] / total * 100) if total > 0 else 0
            crs_complete_pct = (result['items_with_crs'] / total * 100) if total > 0 else 0
            
            return {
                'status': 'passed',
                'total_catalogued_items': total,
                'total_size_gb': round(result['total_size_gb'], 2),
                'vendor_identification': f"{vendor_id_pct:.1f}%",
                'cog_optimization': f"{cog_optimized_pct:.1f}%", 
                'datetime_completeness': f"{datetime_complete_pct:.1f}%",
                'crs_completeness': f"{crs_complete_pct:.1f}%",
                'vendor_breakdown': result['vendor_breakdown'],
                'message': f'Quality metrics: {vendor_id_pct:.1f}% vendor ID, {cog_optimized_pct:.1f}% COG optimized'
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
                'message': 'Failed to generate quality metrics'
            }
    
    def clear_stac_tables(self, confirm: str = None) -> Dict[str, Any]:
        """
        ⚠️  DANGEROUS METHOD - Clear all STAC catalog data for testing purposes.
        
        This method will DELETE ALL DATA from the STAC collections and items tables.
        Use with EXTREME CAUTION - this action is IRREVERSIBLE.
        
        Args:
            confirm: Must be exactly "YES_DELETE_ALL_STAC_DATA" to proceed
            
        Returns:
            Results of the clear operation
            
        Raises:
            ValueError: If confirmation string is not provided correctly
        """
        # Safety check - require explicit confirmation
        if confirm != "YES_DELETE_ALL_STAC_DATA":
            raise ValueError(
                "⚠️  SAFETY CHECK FAILED: This method will DELETE ALL STAC DATA. "
                "To confirm, set confirm='YES_DELETE_ALL_STAC_DATA'. "
                "This action is IRREVERSIBLE and should only be used for testing."
            )
        
        self.logger.warning("🚨 DANGER: Starting STAC table clearing operation")
        
        try:
            # Get counts before clearing
            collections_query = "SELECT COUNT(*) as count FROM geo.collections"
            items_query = "SELECT COUNT(*) as count FROM geo.items"
            
            collections_before = self.db_client.execute(collections_query)[0]['count']
            items_before = self.db_client.execute(items_query)[0]['count']
            
            # Clear items table first (due to foreign key constraints)
            self.logger.warning(f"🗑️  Deleting {items_before} STAC items...")
            delete_items_query = "DELETE FROM geo.items"
            self.db_client.execute(delete_items_query)
            
            # Clear collections table
            self.logger.warning(f"🗑️  Deleting {collections_before} STAC collections...")
            delete_collections_query = "DELETE FROM geo.collections"  
            self.db_client.execute(delete_collections_query)
            
            # Reset sequences to start from 1 again
            reset_items_seq = "ALTER SEQUENCE geo.items_id_seq RESTART WITH 1"
            reset_collections_seq = "ALTER SEQUENCE geo.collections_id_seq RESTART WITH 1"
            self.db_client.execute(reset_items_seq)
            self.db_client.execute(reset_collections_seq)
            
            # Verify tables are empty
            collections_after = self.db_client.execute(collections_query)[0]['count']
            items_after = self.db_client.execute(items_query)[0]['count']
            
            result = {
                'status': 'completed',
                'operation': 'clear_stac_tables',
                'timestamp': datetime.utcnow().isoformat(),
                'collections_deleted': collections_before,
                'items_deleted': items_before,
                'collections_remaining': collections_after,
                'items_remaining': items_after,
                'sequences_reset': True,
                'warning': '⚠️  ALL STAC DATA HAS BEEN PERMANENTLY DELETED',
                'message': f'Successfully deleted {collections_before} collections and {items_before} items'
            }
            
            self.logger.warning(f"💥 STAC clear operation completed: {result['message']}")
            
            return result
            
        except Exception as e:
            error_msg = f"Failed to clear STAC tables: {str(e)}"
            self.logger.error(f"🔥 CLEAR OPERATION FAILED: {error_msg}")
            return {
                'status': 'failed',
                'operation': 'clear_stac_tables',
                'timestamp': datetime.utcnow().isoformat(),
                'error': str(e),
                'message': error_msg,
                'warning': '⚠️  Partial deletion may have occurred - check database state'
            }