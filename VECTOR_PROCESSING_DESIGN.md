# Vector Processing Design for Serverless Architecture

## Executive Summary

Vector operations fit **perfectly** into the Job→Task serverless model because:
- **Feature-level parallelization**: Each feature/chunk can be a separate task
- **Stateless processing**: Perfect for Functions' ephemeral compute
- **Queue-based batching**: Natural fit for Azure Storage Queues
- **Auto-scaling**: Functions scale based on queue depth

## Vector Processing Pipeline

```mermaid
graph LR
    A[Vector File] --> B[Validation Job]
    B --> C[1 Task: Validate]
    C --> D[Chunking Job]
    D --> E[N Tasks: Split by Features]
    E --> F[Loading Job]
    F --> G[M Tasks: Parallel PostGIS Insert]
    G --> H[Index Job]
    H --> I[1 Task: Build Spatial Indexes]
```

## Architectural Design

### 1. Vector Validation Controller
```python
class VectorValidationController(BaseJobController):
    """
    Validates vector files before processing.
    Single task because validation needs full file context.
    """
    
    def create_tasks(self, job_id: str, request: Dict) -> List[str]:
        # Single validation task
        task_data = {
            'operation': 'validate_vector',
            'dataset_id': request['dataset_id'],
            'resource_id': request['resource_id'],  # shapefile.shp, data.geojson, etc.
            'validation_rules': {
                'check_geometry': True,
                'check_crs': True,
                'check_attributes': True,
                'max_features': 10_000_000,  # Circuit breaker
                'max_file_size_gb': 50
            }
        }
        
        task_id = self.generate_task_id(job_id, 'validate', 0)
        self.task_repo.create_task(task_id, job_id, task_data)
        return [task_id]
```

### 2. Vector Chunking Controller
```python
class VectorChunkingController(BaseJobController):
    """
    Splits large vector files into chunks for parallel processing.
    This is where the parallelization magic happens!
    """
    
    def create_tasks(self, job_id: str, request: Dict) -> List[str]:
        # First, get feature count from validation results
        validation_result = self.get_previous_job_result(request['validation_job_id'])
        feature_count = validation_result['feature_count']
        
        # Determine optimal chunk size based on feature complexity
        chunk_size = self.calculate_chunk_size(
            feature_count=feature_count,
            geometry_type=validation_result['geometry_type'],
            attribute_count=validation_result['attribute_count']
        )
        
        # Create chunking tasks
        task_ids = []
        for chunk_idx in range(0, feature_count, chunk_size):
            task_data = {
                'operation': 'extract_vector_chunk',
                'dataset_id': request['dataset_id'],
                'resource_id': request['resource_id'],
                'start_feature': chunk_idx,
                'end_feature': min(chunk_idx + chunk_size, feature_count),
                'output_format': 'geojson',  # Intermediate format
                'parent_job_id': job_id
            }
            
            task_id = self.generate_task_id(job_id, f'chunk_{chunk_idx}', chunk_idx)
            self.task_repo.create_task(task_id, job_id, task_data)
            task_ids.append(task_id)
        
        return task_ids
    
    def calculate_chunk_size(self, feature_count: int, geometry_type: str, 
                            attribute_count: int) -> int:
        """
        Smart chunk sizing based on complexity.
        Goal: Keep each task under 5 minutes execution time.
        """
        BASE_CHUNK_SIZE = 10000
        
        # Adjust for geometry complexity
        complexity_factors = {
            'Point': 1.0,
            'MultiPoint': 0.8,
            'LineString': 0.5,
            'MultiLineString': 0.3,
            'Polygon': 0.3,
            'MultiPolygon': 0.1,  # Complex polygons need smaller chunks
        }
        
        factor = complexity_factors.get(geometry_type, 0.5)
        
        # Adjust for attribute count (more attributes = more memory)
        if attribute_count > 50:
            factor *= 0.5
        elif attribute_count > 100:
            factor *= 0.25
        
        return int(BASE_CHUNK_SIZE * factor)
```

### 3. PostGIS Loading Controller
```python
class PostGISLoadController(BaseJobController):
    """
    Loads vector chunks into PostGIS in parallel.
    This is embarrassingly parallel!
    """
    
    def create_tasks(self, job_id: str, request: Dict) -> List[str]:
        # Get chunks from previous job
        chunking_result = self.get_previous_job_result(request['chunking_job_id'])
        chunks = chunking_result['chunks']
        
        task_ids = []
        for chunk in chunks:
            task_data = {
                'operation': 'load_to_postgis',
                'chunk_blob': chunk['blob_path'],  # Intermediate GeoJSON in storage
                'table_name': request['target_table'],
                'schema': request.get('schema', 'geo'),
                'load_method': request.get('method', 'insert'),  # insert, upsert, append
                'geometry_column': 'geom',
                'srid': request.get('srid', 4326),
                'create_table': chunk['index'] == 0,  # First chunk creates table
                'parent_job_id': job_id
            }
            
            task_id = self.generate_task_id(job_id, f'load_{chunk["index"]}', chunk['index'])
            self.task_repo.create_task(task_id, job_id, task_data)
            task_ids.append(task_id)
        
        return task_ids
```

### 4. Vector Processing Services (Task Level)

```python
class VectorChunkExtractor(BaseTaskService):
    """
    Extracts a chunk of features from vector file.
    Runs as an individual task in parallel with other chunks.
    """
    
    @requires_task
    def process(self, task_id: str, dataset_id: str, resource_id: str,
                start_feature: int, end_feature: int, **kwargs) -> Dict:
        
        # Get blob URL
        blob_url = self.storage.get_blob_sas_url(dataset_id, resource_id)
        
        # Use GDAL/Fiona with feature slicing
        with fiona.open(blob_url, 'r') as src:
            # Use iterator slicing for memory efficiency
            features = []
            for idx, feature in enumerate(src):
                if idx < start_feature:
                    continue
                if idx >= end_feature:
                    break
                features.append(feature)
            
            # Save chunk to intermediate storage
            chunk_name = f"chunks/{task_id}.geojson"
            chunk_url = self.save_geojson_chunk(features, chunk_name)
            
            return {
                'status': 'success',
                'chunk_url': chunk_url,
                'feature_count': len(features),
                'start_idx': start_feature,
                'end_idx': end_feature
            }
```

```python
class PostGISLoader(BaseTaskService):
    """
    Loads a chunk of vector data into PostGIS.
    Each task handles one chunk independently.
    """
    
    @requires_task
    def process(self, task_id: str, chunk_blob: str, table_name: str,
                schema: str, **kwargs) -> Dict:
        
        # Download chunk (small, already filtered)
        chunk_data = self.storage.download_json(chunk_blob)
        
        # Convert to GeoDataFrame for easy PostGIS insertion
        gdf = gpd.GeoDataFrame.from_features(chunk_data['features'])
        
        # Set CRS
        gdf.set_crs(epsg=kwargs.get('srid', 4326), inplace=True)
        
        # Batch insert to PostGIS
        with self.get_postgis_connection() as conn:
            # Use SQLAlchemy + GeoAlchemy2 for efficient insertion
            gdf.to_postgis(
                name=table_name,
                con=conn,
                schema=schema,
                if_exists='append' if not kwargs.get('create_table') else 'replace',
                index=False,  # Create indexes after all data loaded
                method='multi',  # Batch insert
                chunksize=1000  # Insert 1000 rows at a time
            )
            
            inserted_count = len(gdf)
        
        return {
            'status': 'success',
            'inserted_features': inserted_count,
            'table': f"{schema}.{table_name}",
            'chunk': chunk_blob
        }
```

## Parallelization Strategies

### 1. Feature-Based Chunking (Most Common)
```python
# Split 1 million features across 100 tasks (10k each)
# All tasks run in parallel across Function instances
Tasks: [0-9999], [10000-19999], [20000-29999], ...
```

### 2. Spatial Chunking (For Huge Datasets)
```python
class SpatialChunkingController(BaseJobController):
    """
    Chunks by spatial grid for better locality.
    Great for country/continent scale data.
    """
    
    def create_tasks(self, job_id: str, request: Dict) -> List[str]:
        # Create spatial grid
        bbox = validation_result['bbox']
        grid = self.create_spatial_grid(bbox, rows=10, cols=10)
        
        task_ids = []
        for cell in grid:
            task_data = {
                'operation': 'extract_by_bbox',
                'bbox': cell.bounds,
                'cell_id': f"{cell.row}_{cell.col}",
                # ...
            }
            # Create task for each grid cell
```

### 3. Attribute-Based Chunking
```python
# Split by attribute values (e.g., by state, category)
Tasks: [state='CA'], [state='TX'], [state='NY'], ...
```

## Optimizations for Serverless

### 1. Connection Pooling
```python
class PostGISConnectionPool:
    """
    Reuse connections within Function instance lifetime.
    Functions can stay warm for 5-20 minutes.
    """
    
    _connections = {}
    
    @classmethod
    def get_connection(cls, task_id: str):
        # Reuse connection if warm
        if task_id in cls._connections:
            conn = cls._connections[task_id]
            if not conn.closed:
                return conn
        
        # Create new connection
        conn = psycopg2.connect(...)
        cls._connections[task_id] = conn
        return conn
```

### 2. Streaming Processing
```python
class StreamingVectorProcessor(BaseTaskService):
    """
    Stream features without loading entire file.
    Perfect for Function's memory constraints.
    """
    
    def process(self, task_id: str, **kwargs):
        # Use generators and iterators
        with fiona.open(source) as src:
            # Process in batches
            batch = []
            for feature in src:
                batch.append(self.transform_feature(feature))
                
                if len(batch) >= 1000:
                    self.write_batch(batch)
                    batch = []
            
            # Write remaining
            if batch:
                self.write_batch(batch)
```

### 3. Smart Queue Management
```python
# Separate queues by priority and size
Queues:
- vector-validation-queue (priority: high, timeout: 5min)
- vector-chunking-queue (priority: medium, timeout: 10min)  
- vector-loading-queue (priority: low, timeout: 2min)
- vector-indexing-queue (priority: low, timeout: 10min)

# Function app scales independently per queue
```

## Complete Vector Pipeline Example

```python
# 1. User uploads 5GB shapefile with 2 million features
POST /api/jobs/process_vector
{
    "dataset_id": "rmhazuregeobronze",
    "resource_id": "counties_usa.shp",
    "target_table": "us_counties",
    "schema": "geo"
}

# 2. System creates job chain
ValidationJob (1 task) 
    ↓
ChunkingJob (200 tasks @ 10k features each)
    ↓
LoadingJob (200 parallel PostGIS inserts)
    ↓
IndexingJob (1 task for spatial index)

# 3. Execution (all automatic)
- Validation: 30 seconds
- Chunking: 200 tasks in parallel, ~2 minutes total
- Loading: 200 tasks in parallel, ~3 minutes total  
- Indexing: 1 minute
Total: ~6.5 minutes for 2 million features

# 4. Result
{
    "status": "completed",
    "table": "geo.us_counties",
    "features_loaded": 2000000,
    "processing_time": "6m 32s",
    "tasks_executed": 402,
    "parallel_efficiency": "94%"
}
```

## Why This Works So Well with Functions

1. **Auto-scaling**: Functions scale from 0 to 200 instances automatically
2. **Cost-effective**: Pay only for actual processing time
3. **No infrastructure**: No VMs, containers, or Kubernetes to manage
4. **Queue-driven**: Natural backpressure and retry mechanisms
5. **Stateless**: Each task is independent, perfect for Functions
6. **Memory efficient**: Stream processing fits in 1.5GB Function memory
7. **Timeout friendly**: Chunks sized to complete in <5 minutes

## Vector-Specific Considerations

### Geometry Validation
```python
class GeometryValidator(BaseTaskService):
    """Parallel geometry validation and repair"""
    
    def process(self, task_id: str, chunk_blob: str, **kwargs):
        features = self.load_chunk(chunk_blob)
        
        valid = []
        invalid = []
        repaired = []
        
        for feature in features:
            geom = shape(feature['geometry'])
            
            if geom.is_valid:
                valid.append(feature)
            else:
                # Try to repair
                fixed = geom.buffer(0)
                if fixed.is_valid:
                    feature['geometry'] = mapping(fixed)
                    repaired.append(feature)
                else:
                    invalid.append(feature)
        
        # Save results
        self.save_validated_chunk(valid, repaired, invalid)
```

### Topology Preservation
```python
# Process adjacent chunks with overlap
GridChunks: [overlap: 100m buffer per cell]
- Prevents edge artifacts
- Maintains topology across chunks
- De-duplicate features in overlap zones
```

### Attribute Processing
```python
class AttributeProcessor(BaseTaskService):
    """Clean and standardize attributes in parallel"""
    
    def process(self, task_id: str, **kwargs):
        # Each task handles attribute cleaning for its chunk
        - Standardize field names
        - Convert data types
        - Handle nulls/missing values
        - Apply business rules
        - Validate against schemas
```

## Summary

Vector operations are **ideal** for serverless because:

1. **Natural Parallelization**: Features are independent units
2. **Flexible Chunking**: By count, space, or attributes  
3. **Streaming Compatible**: Don't need entire file in memory
4. **Queue-Friendly**: Each chunk is a separate message
5. **Scale-to-Zero**: No cost when not processing
6. **Burst Capable**: Handle massive uploads with auto-scale

The Job→Task pattern makes this elegant:
- **1 vector file** = 1 validation job + 1 chunking job + 1 loading job
- **Each job** = Multiple parallel tasks (chunks)
- **Result** = Fast, scalable, cost-effective vector processing

This is exactly what serverless was designed for!