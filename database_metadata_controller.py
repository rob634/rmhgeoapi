"""
Database Metadata Controller for exposing database query capabilities via HTTP.
"""
import json
from typing import Dict, Any, Optional, List
import logging

from base_controller import BaseJobController
from database_metadata_service import DatabaseMetadataService


class DatabaseMetadataController(BaseJobController):
    """Controller for database metadata operations"""
    
    def __init__(self):
        """Initialize the database metadata controller"""
        # Initialize base controller
        super().__init__()
        
        # Create repositories for the metadata service
        from repositories import StorageRepository
        from database_client import DatabaseClient
        from logger_setup import get_logger
        
        logger = get_logger(self.__class__.__name__)
        
        repositories = {
            'storage': StorageRepository()
        }
        
        self.metadata_service = DatabaseMetadataService(repositories, logger)
    
    def validate_request(self, request: Dict[str, Any]) -> None:
        """
        Validate request parameters for database operations.
        
        Args:
            request: Request parameters to validate
            
        Raises:
            InvalidRequestError: If request is invalid
        """
        # Get job type
        job_type = request.get('job_type')
        if not job_type:
            from controller_exceptions import InvalidRequestError
            raise InvalidRequestError("Job type is required")
        
        # Validate based on job type
        if job_type == 'get_collection_details':
            if not request.get('collection_id'):
                from controller_exceptions import InvalidRequestError
                raise InvalidRequestError("collection_id is required for get_collection_details")
        
        elif job_type == 'query_spatial':
            if not request.get('geometry'):
                from controller_exceptions import InvalidRequestError
                raise InvalidRequestError("geometry is required for spatial queries")
    
    def create_tasks(self, request: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Create tasks for database operations.
        
        Most database operations are synchronous queries, so we create
        a single task that will be executed immediately.
        
        Args:
            request: Validated request parameters
            
        Returns:
            List containing single task for database operation
        """
        job_type = request.get('job_type')
        
        # Database operations are typically single tasks
        task = {
            'operation': job_type,  # Keep 'operation' for task data compatibility
            'parameters': request
        }
        
        return [task]
    
    def aggregate_results(self, task_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Aggregate results from tasks.
        
        For database operations, we typically have a single task,
        so we just return its result.
        
        Args:
            task_results: Results from completed tasks
            
        Returns:
            Aggregated result
        """
        if not task_results:
            return {'status': 'error', 'error': 'No results to aggregate'}
        
        # For database operations, we typically have single task
        if len(task_results) == 1:
            return task_results[0]
        
        # If multiple results (shouldn't happen for database ops),
        # combine them
        return {
            'status': 'success',
            'results': task_results,
            'count': len(task_results)
        }
    
    async def list_collections(self, **kwargs) -> Dict[str, Any]:
        """
        List all STAC collections with statistics.
        
        Query Parameters:
            include_stats (bool): Include detailed statistics (default: True)
        
        Returns:
            List of collections with metadata
        """
        try:
            include_stats = kwargs.get('include_stats', True)
            if isinstance(include_stats, str):
                include_stats = include_stats.lower() == 'true'
            
            collections = self.metadata_service.list_collections(include_stats=include_stats)
            
            return {
                'status': 'success',
                'collections': collections,
                'count': len(collections)
            }
            
        except Exception as e:
            self.logger.error(f"Error listing collections: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    async def list_items(self, **kwargs) -> Dict[str, Any]:
        """
        List STAC items with optional filtering.
        
        Query Parameters:
            collection_id (str): Filter by collection
            bbox (str): Comma-separated bbox "minx,miny,maxx,maxy"
            datetime (str): ISO datetime or range "start/end"
            limit (int): Maximum items to return (default: 100)
            offset (int): Pagination offset (default: 0)
        
        Returns:
            GeoJSON FeatureCollection of items
        """
        try:
            # Parse parameters
            collection_id = kwargs.get('collection_id')
            limit = int(kwargs.get('limit', 100))
            offset = int(kwargs.get('offset', 0))
            
            # Parse bbox if provided
            bbox = None
            if 'bbox' in kwargs and kwargs['bbox']:
                bbox_str = kwargs['bbox']
                bbox = [float(x) for x in bbox_str.split(',')]
                if len(bbox) != 4:
                    raise ValueError("Bbox must have 4 values: minx,miny,maxx,maxy")
            
            # Parse datetime range if provided
            datetime_range = None
            if 'datetime' in kwargs and kwargs['datetime']:
                dt_str = kwargs['datetime']
                if '/' in dt_str:
                    parts = dt_str.split('/')
                    datetime_range = (parts[0], parts[1])
                else:
                    # Single datetime becomes a range for that instant
                    datetime_range = (dt_str, dt_str)
            
            # Query items
            result = self.metadata_service.list_items(
                collection_id=collection_id,
                bbox=bbox,
                datetime_range=datetime_range,
                limit=limit,
                offset=offset
            )
            
            return {
                'status': 'success',
                **result
            }
            
        except Exception as e:
            self.logger.error(f"Error listing items: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    async def get_database_summary(self, **kwargs) -> Dict[str, Any]:
        """
        Get overall database statistics and summary.
        
        Returns:
            Comprehensive database metadata summary
        """
        try:
            summary = self.metadata_service.get_database_summary()
            
            return {
                'status': 'success',
                **summary
            }
            
        except Exception as e:
            self.logger.error(f"Error getting database summary: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    async def get_collection_details(self, **kwargs) -> Dict[str, Any]:
        """
        Get detailed metadata for a specific collection.
        
        Required Parameters:
            collection_id (str): The collection ID to query
        
        Returns:
            Detailed collection metadata and statistics
        """
        try:
            # Validate required parameter
            collection_id = self._validate_required_param(kwargs, 'collection_id', str)
            
            details = self.metadata_service.get_collection_details(collection_id)
            
            return {
                'status': 'success',
                **details
            }
            
        except Exception as e:
            self.logger.error(f"Error getting collection details: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    async def export_metadata(self, **kwargs) -> Dict[str, Any]:
        """
        Export database metadata in specified format.
        
        Query Parameters:
            format (str): Export format - 'json', 'geojson', 'csv' (default: 'json')
            include_items (bool): Include all items in export (default: False)
            output_path (str): Optional blob storage path for saving export
        
        Returns:
            Exported metadata in requested format
        """
        try:
            # Parse parameters
            export_format = kwargs.get('format', 'json')
            if export_format not in ['json', 'geojson', 'csv']:
                raise ValueError(f"Invalid format '{export_format}'. Must be 'json', 'geojson', or 'csv'")
            
            include_items = kwargs.get('include_items', False)
            if isinstance(include_items, str):
                include_items = include_items.lower() == 'true'
            
            output_path = kwargs.get('output_path')
            
            # Export metadata
            result = self.metadata_service.export_metadata(
                format=export_format,
                include_items=include_items,
                output_path=output_path
            )
            
            # For CSV, return as text
            if export_format == 'csv' and 'csv' in result:
                return {
                    'status': 'success',
                    'format': 'csv',
                    'data': result['csv'],
                    'message': 'CSV data generated successfully'
                }
            
            return {
                'status': 'success',
                'format': export_format,
                'data': result,
                'output_path': output_path
            }
            
        except Exception as e:
            self.logger.error(f"Error exporting metadata: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    async def query_spatial(self, **kwargs) -> Dict[str, Any]:
        """
        Perform spatial queries on the database.
        
        Query Parameters:
            geometry (str): GeoJSON geometry for spatial query
            operation (str): Spatial operation - 'intersects', 'contains', 'within' (default: 'intersects')
            collection_id (str): Optional collection filter
            limit (int): Maximum results (default: 100)
        
        Returns:
            Items matching the spatial query
        """
        try:
            # Parse geometry
            geometry_str = self._validate_required_param(kwargs, 'geometry', str)
            geometry = json.loads(geometry_str) if isinstance(geometry_str, str) else geometry_str
            
            operation = kwargs.get('operation', 'intersects')
            if operation not in ['intersects', 'contains', 'within']:
                raise ValueError(f"Invalid operation '{operation}'")
            
            collection_id = kwargs.get('collection_id')
            limit = int(kwargs.get('limit', 100))
            
            # Build and execute spatial query
            query = f"""
                SELECT 
                    i.id,
                    i.collection_id,
                    i.properties,
                    ST_AsGeoJSON(i.geometry) as geometry,
                    ST_AsGeoJSON(i.bbox) as bbox
                FROM geo.items i
                WHERE ST_{operation.capitalize()}(
                    i.geometry,
                    ST_GeomFromGeoJSON(%s)
                )
            """
            
            params = [json.dumps(geometry)]
            
            if collection_id:
                query += " AND i.collection_id = %s"
                params.append(collection_id)
            
            query += f" LIMIT {limit}"
            
            items = self.metadata_service.db_client.execute(query, params)
            
            # Format results
            features = []
            for item in items:
                features.append({
                    'type': 'Feature',
                    'id': item['id'],
                    'properties': {
                        **item['properties'],
                        'collection_id': item['collection_id']
                    },
                    'geometry': json.loads(item['geometry']) if item['geometry'] else None,
                    'bbox': json.loads(item['bbox']) if item['bbox'] else None
                })
            
            return {
                'status': 'success',
                'type': 'FeatureCollection',
                'features': features,
                'count': len(features),
                'query': {
                    'operation': operation,
                    'collection_id': collection_id
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error in spatial query: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    async def get_statistics(self, **kwargs) -> Dict[str, Any]:
        """
        Get detailed statistics for collections or items.
        
        Query Parameters:
            group_by (str): Group statistics by 'collection', 'date', 'file_type', 'crs'
            collection_id (str): Optional collection filter
            days (int): Number of days for temporal statistics (default: 30)
        
        Returns:
            Statistical analysis of the database
        """
        try:
            group_by = kwargs.get('group_by', 'collection')
            collection_id = kwargs.get('collection_id')
            days = int(kwargs.get('days', 30))
            
            # Build appropriate query based on grouping
            if group_by == 'collection':
                query = """
                    SELECT 
                        collection_id as group_key,
                        COUNT(*) as item_count,
                        SUM((properties->>'file_size')::float) / 1073741824 as total_size_gb,
                        AVG((properties->>'file_size')::float) / 1048576 as avg_size_mb,
                        MIN((properties->>'datetime')::timestamp) as min_date,
                        MAX((properties->>'datetime')::timestamp) as max_date
                    FROM geo.items
                    GROUP BY collection_id
                    ORDER BY item_count DESC
                """
                params = []
                
            elif group_by == 'date':
                query = f"""
                    SELECT 
                        DATE((properties->>'datetime')::timestamp)::text as group_key,
                        COUNT(*) as item_count,
                        SUM((properties->>'file_size')::float) / 1073741824 as total_size_gb,
                        COUNT(DISTINCT collection_id) as collection_count
                    FROM geo.items
                    WHERE properties->>'datetime' IS NOT NULL
                        AND (properties->>'datetime')::timestamp > CURRENT_TIMESTAMP - INTERVAL '{days} days'
                """
                if collection_id:
                    query += " AND collection_id = %s"
                    params = [collection_id]
                else:
                    params = []
                query += """
                    GROUP BY DATE((properties->>'datetime')::timestamp)
                    ORDER BY group_key DESC
                """
                
            elif group_by == 'file_type':
                query = """
                    SELECT 
                        COALESCE(properties->>'file_extension', 'unknown') as group_key,
                        COUNT(*) as item_count,
                        SUM((properties->>'file_size')::float) / 1073741824 as total_size_gb,
                        COUNT(DISTINCT collection_id) as collection_count
                    FROM geo.items
                """
                if collection_id:
                    query += " WHERE collection_id = %s"
                    params = [collection_id]
                else:
                    params = []
                query += """
                    GROUP BY COALESCE(properties->>'file_extension', 'unknown')
                    ORDER BY item_count DESC
                """
                
            elif group_by == 'crs':
                query = """
                    SELECT 
                        COALESCE(properties->>'crs', 'unknown') as group_key,
                        COUNT(*) as item_count,
                        COUNT(DISTINCT collection_id) as collection_count,
                        array_agg(DISTINCT properties->>'file_extension') as file_types
                    FROM geo.items
                """
                if collection_id:
                    query += " WHERE collection_id = %s"
                    params = [collection_id]
                else:
                    params = []
                query += """
                    GROUP BY COALESCE(properties->>'crs', 'unknown')
                    ORDER BY item_count DESC
                """
                
            else:
                raise ValueError(f"Invalid group_by value '{group_by}'")
            
            # Execute query
            results = self.metadata_service.db_client.execute(query, params)
            
            # Format results
            statistics = []
            for row in results:
                stat = {
                    'group': row['group_key'],
                    'item_count': row['item_count']
                }
                
                # Add additional fields based on group type
                if 'total_size_gb' in row:
                    stat['total_size_gb'] = float(row['total_size_gb'] or 0)
                if 'avg_size_mb' in row:
                    stat['avg_size_mb'] = float(row['avg_size_mb'] or 0)
                if 'collection_count' in row:
                    stat['collection_count'] = row['collection_count']
                if 'min_date' in row and row['min_date']:
                    stat['min_date'] = row['min_date'].isoformat()
                if 'max_date' in row and row['max_date']:
                    stat['max_date'] = row['max_date'].isoformat()
                if 'file_types' in row:
                    stat['file_types'] = row['file_types']
                
                statistics.append(stat)
            
            return {
                'status': 'success',
                'group_by': group_by,
                'statistics': statistics,
                'count': len(statistics),
                'filters': {
                    'collection_id': collection_id,
                    'days': days if group_by == 'date' else None
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error getting statistics: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }