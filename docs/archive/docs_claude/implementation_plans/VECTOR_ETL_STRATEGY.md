# Vector ETL Strategy

**Date**: 14 SEP 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Design patterns and strategy for vector data ETL operations

## Executive Summary

Based on analysis of `reference/oldvector.py`, this document outlines the strategy for implementing vector ETL operations in the Azure Geospatial Pipeline. The approach leverages proven patterns while adapting them to our Job→Stage→Task orchestration architecture.

## Key Patterns Identified from Legacy Code

### 1. Multi-Format Support Pattern
The legacy code supports multiple vector formats through a loader registry:
```python
loaders = {
    'csv': csv_to_gdf,      # Coordinate or WKT columns
    'gdb': None,            # Esri File Geodatabase
    'geojson': geojson_to_gdf,
    'gpkg': gpkg_to_gdf,    # GeoPackage with layers
    'kml': kml_to_gdf,
    'kmz': kmz_to_gdf,      # Compressed KML
    'shp': shp_zip_to_gdf,  # Shapefile in ZIP
}
```

### 2. Validation Hierarchy
Three-tier validation approach:
1. **Format Validation**: File extension and structure
2. **Geometry Validation**: Single geometry type, no Z values, valid geometries
3. **Database Validation**: Column names, reserved words, data types

### 3. Storage Integration
- Direct blob-to-GeoDataFrame conversion using BytesIO
- Temporary file handling for formats requiring disk access
- ZIP file content inspection and extraction

### 4. PostGIS Preparation
Strong typing and validation for database compatibility:
- Lowercase column enforcement
- Reserved word handling with suffix pattern
- Character validation (alphanumeric + underscore only)
- Geometry column standardization

## Proposed Vector ETL Architecture

### Service Layer: `service_vector.py`

#### Core Task Handlers

```python
@TaskRegistry.register("analyze_vector_source")
async def analyze_vector_source(task_context: TaskContext) -> TaskResult:
    """
    Stage 1: Analyze vector file/container
    - Detect format (shp, gpkg, gdb, geojson, etc.)
    - Extract layer information
    - Count features
    - Get bounding box
    - Identify CRS
    """

@TaskRegistry.register("validate_vector_geometry")
async def validate_vector_geometry(task_context: TaskContext) -> TaskResult:
    """
    Stage 2: Validate geometries
    - Check for mixed geometry types
    - Remove Z dimensions
    - Fix invalid geometries
    - Standardize to single type
    """

@TaskRegistry.register("prepare_for_postgis")
async def prepare_for_postgis(task_context: TaskContext) -> TaskResult:
    """
    Stage 3: Prepare for database insertion
    - Lowercase columns
    - Handle reserved words
    - Validate data types
    - Set standard geometry column name
    """

@TaskRegistry.register("load_to_geo_schema")
async def load_to_geo_schema(task_context: TaskContext) -> TaskResult:
    """
    Stage 4: Load to geo schema
    - Create table if not exists
    - Batch insert with psycopg
    - Create spatial indexes
    - Update statistics
    """

@TaskRegistry.register("register_in_stac")
async def register_in_stac(task_context: TaskContext) -> TaskResult:
    """
    Stage 5: Register in STAC catalog
    - Create/update STAC item
    - Add to appropriate collection
    - Generate thumbnail
    - Update extent
    """
```

### Controller Layer: `controller_vector.py`

#### IngestVectorController
**Purpose**: Full vector ingestion pipeline
**Stages**:
1. Analyze source (format detection, layer discovery)
2. Validate geometry (fix issues, standardize)
3. Prepare for PostGIS (column validation)
4. Load to geo schema (batch insert)
5. Register in STAC catalog

#### ValidateVectorController
**Purpose**: Validation-only workflow
**Stages**:
1. Analyze source
2. Validate geometry
3. Generate validation report

### Repository Layer: `repository_vector.py`

```python
class VectorRepository:
    """
    Centralized vector operations repository
    """

    def read_vector_from_blob(
        self,
        container: str,
        blob_path: str,
        layer: Optional[str] = None
    ) -> gpd.GeoDataFrame:
        """Read vector data directly from blob storage"""

    def detect_vector_format(
        self,
        blob_path: str
    ) -> VectorFormat:
        """Detect vector format from extension and content"""

    def list_layers(
        self,
        blob_path: str
    ) -> List[str]:
        """List layers in multi-layer formats (gpkg, gdb)"""

    def batch_insert_to_postgis(
        self,
        gdf: gpd.GeoDataFrame,
        schema: str,
        table: str,
        batch_size: int = 1000
    ) -> int:
        """Efficient batch insertion to PostGIS"""
```

### Schema Layer: `schema_vector.py`

```python
class VectorFormat(str, Enum):
    """Supported vector formats"""
    SHAPEFILE = "shp"
    GEOPACKAGE = "gpkg"
    GEOJSON = "geojson"
    KML = "kml"
    KMZ = "kmz"
    CSV = "csv"
    GEODATABASE = "gdb"

class VectorMetadata(BaseModel):
    """Vector dataset metadata"""
    format: VectorFormat
    layer_count: int
    feature_count: int
    geometry_type: str
    crs: str
    bbox: List[float]
    attributes: Dict[str, str]  # column: dtype

class VectorValidation(BaseModel):
    """Validation results"""
    is_valid: bool
    geometry_issues: List[str]
    column_issues: List[str]
    fixed_count: int
    dropped_count: int
```

## Implementation Strategy

### Phase 1: Core Vector Support (Week 1)
- [ ] Implement `repository_vector.py` with blob reading
- [ ] Support Shapefile, GeoPackage, GeoJSON
- [ ] Basic geometry validation
- [ ] PostGIS table creation

### Phase 2: Advanced Formats (Week 2)
- [ ] Add KML/KMZ support
- [ ] Handle Esri File Geodatabases (.gdb)
- [ ] CSV with coordinates/WKT
- [ ] Multi-layer handling for GeoPackage

### Phase 3: Validation & Repair (Week 3)
- [ ] Geometry repair toolkit
- [ ] CRS transformation
- [ ] Attribute validation
- [ ] Data type conversion

### Phase 4: Performance & Scale (Week 4)
- [ ] Parallel processing for large datasets
- [ ] Streaming for huge files
- [ ] Spatial indexing strategies
- [ ] Partitioning for massive tables

## Key Design Decisions

### 1. BytesIO Over Temporary Files
**Pattern**: Read directly from blob storage into memory
**Rationale**: Avoids disk I/O, faster for cloud-native operations
**Exception**: Use temp files only for formats that require it (e.g., .gdb folders)

### 2. Validation as Separate Stage
**Pattern**: Dedicated validation stage before database operations
**Rationale**: Fail fast, provide clear error messages, enable validation-only workflows

### 3. Batch Operations
**Pattern**: Process vectors in configurable batch sizes
**Rationale**: Balance memory usage with performance, handle large datasets

### 4. STAC Integration
**Pattern**: Automatic STAC registration for all vector ingests
**Rationale**: Unified catalog for all spatial data, enables discovery

### 5. Schema Flexibility
**Pattern**: Tables created in `geo` schema with project prefixes
**Rationale**: Allows schema to grow organically while maintaining organization

## Error Handling Strategy

### Geometry Errors
- **Invalid geometries**: Attempt repair with `buffer(0)`
- **Mixed types**: Split into separate tables by type
- **Z dimensions**: Strip Z values, log warning
- **Empty geometries**: Remove rows, report count

### Column Errors
- **Reserved words**: Add suffix (e.g., `_v1`)
- **Invalid characters**: Replace with underscore
- **Numeric start**: Prefix with 'c'
- **Duplicates**: Add numeric suffix

### Format Errors
- **Corrupted files**: Fail with clear message
- **Missing components**: Check for required files (e.g., .shx for .shp)
- **Unknown format**: Attempt GDAL/OGR fallback

## Performance Considerations

### Memory Management
- Stream large files when possible
- Use chunked reading for huge CSVs
- Clear GeoDataFrame after database insert
- Monitor memory usage in task metadata

### Database Optimization
- Create spatial indexes after bulk insert
- Use COPY protocol for large inserts
- Analyze tables after loading
- Consider partitioning for >1M features

### Parallel Processing
- Layer processing in parallel for multi-layer formats
- Tile-based processing for massive single layers
- Concurrent STAC registration
- Parallel validation for multiple files

## Integration Points

### With Blob Storage
- Use existing `repository_blob.py` for file operations
- Leverage connection pooling
- Support both individual files and batch operations

### With PostgreSQL/PostGIS
- Use `repository_postgresql.py` for connections
- Extend with vector-specific operations
- Maintain transaction safety

### With STAC Catalog
- Auto-generate STAC items for vectors
- Include layer information in assets
- Update collection extents

### With Job Orchestration
- Leverage existing Job→Stage→Task pattern
- Support both single-file and batch workflows
- Enable partial success handling

## Monitoring & Logging

### Metrics to Track
- Features processed per second
- Validation error rates
- Geometry repair success rate
- Database insertion throughput
- Memory usage patterns

### Logging Strategy
- INFO: Stage completion, feature counts
- WARNING: Geometry repairs, column renames
- ERROR: Validation failures, database errors
- DEBUG: Format detection, layer discovery

## Testing Strategy

### Unit Tests
- Format detection accuracy
- Geometry validation logic
- Column name handling
- Batch processing logic

### Integration Tests
- End-to-end ingestion workflows
- Multi-format support
- Large file handling
- Error recovery

### Performance Tests
- Throughput benchmarks by format
- Memory usage under load
- Database insertion rates
- Parallel processing efficiency

## Future Enhancements

### Advanced Features
- Topology validation
- Attribute domain validation
- Spatial joins during ingestion
- Change detection for updates
- Vector tiling for web services

### Format Extensions
- CAD formats (DWG, DXF)
- GPS formats (GPX)
- OpenStreetMap data (PBF)
- Cloud-optimized vectors (FlatGeobuf)

### Processing Capabilities
- Simplification for web display
- Generalization for scale
- Buffering operations
- Spatial aggregations

## Conclusion

This strategy builds upon proven patterns from the legacy code while modernizing for cloud-native operations. The approach prioritizes:

1. **Flexibility**: Support for multiple formats and workflows
2. **Reliability**: Strong validation and error handling
3. **Performance**: Batch operations and parallel processing
4. **Integration**: Seamless fit with existing architecture
5. **Maintainability**: Clear separation of concerns

The phased implementation allows for incremental delivery while maintaining system stability.