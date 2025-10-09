# Vector Converter Classes - Design Document

## 🎯 Goal
Extract file format conversion logic from `VectorLoader` into small, composable converter classes that can be dependency-injected into tasks within the job framework.

---

## 🏗️ Architecture Principles

1. **Single Responsibility**: Each converter handles ONE file format
2. **Storage Agnostic**: Converters accept BytesIO/file paths, not StorageHandler
3. **No Inheritance**: Use composition and registry pattern (like job handlers)
4. **Testable**: Can be tested without storage/blob dependencies
5. **Reusable**: Can be used outside the job framework

---

## 📐 Converter Interface

Each converter implements a common interface:

```python
class VectorConverter:
    """Base protocol (not inherited - just for reference)"""
    
    def convert(self, data: BytesIO, **kwargs) -> GeoDataFrame:
        """
        Convert file data to GeoDataFrame
        
        Args:
            data: BytesIO object containing file data
            **kwargs: Format-specific parameters
            
        Returns:
            GeoDataFrame with geometries
        """
        raise NotImplementedError
    
    @property
    def supported_extensions(self) -> List[str]:
        """File extensions this converter handles"""
        raise NotImplementedError
```

---

## 🔧 Converter Classes

### 1. CSVConverter
**Handles**: CSV files with lat/lon OR WKT columns

**Parameters**:
- `lat_name: str` - Latitude column name
- `lon_name: str` - Longitude column name
- `wkt_column: str` - WKT geometry column name

**Logic**:
- Read CSV to DataFrame
- If `wkt_column` provided → use `wkt_df_to_gdf()`
- If `lat_name` + `lon_name` → use `xy_df_to_gdf()`
- Validate coordinates are within bounds

**Dependencies**:
- `pandas.read_csv()`
- Helper functions: `xy_df_to_gdf()`, `wkt_df_to_gdf()`

---

### 2. GeoPackageConverter
**Handles**: `.gpkg` files

**Parameters**:
- `layer_name: str` (required) - Layer to extract

**Logic**:
- Use `geopandas.read_file(data, layer=layer_name)`
- Validate layer exists

**Dependencies**:
- `geopandas.read_file()`

---

### 3. GeoJSONConverter
**Handles**: `.geojson`, `.json` files

**Parameters**:
- None (GeoJSON is self-describing)

**Logic**:
- Use `geopandas.read_file(data)`

**Dependencies**:
- `geopandas.read_file()`

---

### 4. KMLConverter
**Handles**: `.kml` files

**Parameters**:
- None

**Logic**:
- Use `geopandas.read_file(data)`

**Dependencies**:
- `geopandas.read_file()`

---

### 5. KMZConverter
**Handles**: `.kmz` files (zipped KML)

**Parameters**:
- `kml_name: str` (optional) - Specific KML file in archive

**Logic**:
- Extract zip to temp directory
- Find `.kml` file (by name or first found)
- Use `geopandas.read_file()` on extracted KML

**Dependencies**:
- `zipfile.ZipFile()`
- `tempfile.TemporaryDirectory()`
- `geopandas.read_file()`

---

### 6. ShapefileConverter
**Handles**: `.shp` files in `.zip` archives

**Parameters**:
- `shp_name: str` (optional) - Specific shapefile in archive

**Logic**:
- Extract zip to temp directory
- Find `.shp` file (by name or first found)
- Use `geopandas.read_file()` on extracted shapefile

**Dependencies**:
- `zipfile.ZipFile()`
- `tempfile.TemporaryDirectory()`
- `geopandas.read_file()`

---

## 🗂️ Converter Registry

Similar to `JobRegistry`, we'll have a `ConverterRegistry`:

```python
class ConverterRegistry:
    """Singleton registry mapping file extensions to converters"""
    
    _instance = None
    _converters: Dict[str, VectorConverter] = {}
    
    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def register(self, *extensions: str):
        """Decorator to register converter for file extensions"""
        def wrapper(converter_class):
            for ext in extensions:
                self._converters[ext.lower()] = converter_class
            return converter_class
        return wrapper
    
    def get_converter(self, extension: str) -> VectorConverter:
        """Get converter for file extension"""
        ext = extension.lower().lstrip('.')
        if ext not in self._converters:
            raise ValueError(f"No converter registered for .{ext}")
        return self._converters[ext]()  # Instantiate
```

---

## 📦 Helper Functions (Extracted)

These become standalone utility functions:

### `xy_df_to_gdf(df, lat_name, lon_name, crs=DEFAULT_CRS_STRING)`
- Validates lat/lon are within ±180 (could refine to ±90 for lat)
- Creates Point geometries
- Returns GeoDataFrame

### `wkt_df_to_gdf(df, wkt_column, crs=DEFAULT_CRS_STRING)`
- Parses WKT strings using `shapely.wkt.loads()`
- Handles errors (WKTReadingError, ShapelyError)
- Returns GeoDataFrame

### `extract_zip_file(zip_data: BytesIO, target_extension: str, target_name: str = None)`
- Generic zip extraction helper
- Finds file by extension or name
- Returns file path in temp directory
- Used by KMZ and Shapefile converters

---

## 🔌 Integration with Job Framework

### Task Definition
```python
# In a job handler
def create_stage_1_tasks(self, context: JobContext) -> List[TaskDefinition]:
    return [
        TaskDefinition(
            task_type="load_vector_file",
            parameters={
                "blob_name": context.parameters["file_name"],
                "container_name": context.parameters["container_name"],
                "file_extension": "gpkg",
                "layer_name": "parcels",  # Format-specific params
            }
        )
    ]
```

### Task Execution (in service layer)
```python
# services/vector_loader.py

def load_vector_file(blob_name: str, container_name: str, file_extension: str, **converter_params):
    """
    Task that loads a vector file from blob storage
    
    This is what gets called by CoreMachine
    """
    # 1. Get file from storage (dependency injected)
    storage = StorageHandler(container_name=container_name)
    file_data = storage.blob_to_bytesio(blob_name)
    
    # 2. Get appropriate converter from registry
    converter = ConverterRegistry.instance().get_converter(file_extension)
    
    # 3. Convert to GeoDataFrame
    gdf = converter.convert(file_data, **converter_params)
    
    # 4. Return result
    return {
        "gdf": gdf,  # Or serialize it
        "row_count": len(gdf),
        "geometry_type": gdf.geometry.type[0]
    }
```

---

## 📁 File Structure

```
converters/
├── __init__.py              # Auto-import all converters
├── registry.py              # ConverterRegistry
├── base.py                  # Protocol/interface definition
├── helpers.py               # xy_df_to_gdf, wkt_df_to_gdf, extract_zip_file
├── csv_converter.py         # CSVConverter
├── geopackage_converter.py  # GeoPackageConverter
├── geojson_converter.py     # GeoJSONConverter
├── kml_converter.py         # KMLConverter
├── kmz_converter.py         # KMZConverter
└── shapefile_converter.py   # ShapefileConverter

services/
├── vector_loader.py         # load_vector_file task implementation

jobs/
├── upload_vector.py         # Job that uses vector loading task
```

---

## 🎨 Example: CSV Converter Implementation

```python
# converters/csv_converter.py

from io import BytesIO
from typing import List
from geopandas import GeoDataFrame
from pandas import read_csv

from .registry import ConverterRegistry
from .helpers import xy_df_to_gdf, wkt_df_to_gdf
from utils import logger, DEFAULT_CRS_STRING


@ConverterRegistry.instance().register('csv')
class CSVConverter:
    """Converts CSV files with lat/lon or WKT to GeoDataFrame"""
    
    @property
    def supported_extensions(self) -> List[str]:
        return ['csv']
    
    def convert(
        self,
        data: BytesIO,
        lat_name: str = None,
        lon_name: str = None,
        wkt_column: str = None,
        **kwargs
    ) -> GeoDataFrame:
        """
        Convert CSV to GeoDataFrame
        
        Args:
            data: BytesIO containing CSV data
            lat_name: Latitude column name
            lon_name: Longitude column name
            wkt_column: WKT geometry column name
            
        Returns:
            GeoDataFrame
            
        Raises:
            ValueError: If neither lat/lon nor wkt_column provided
        """
        if not (wkt_column or (lat_name and lon_name)):
            raise ValueError("Must provide either wkt_column or lat_name+lon_name")
        
        # Read CSV to DataFrame
        logger.debug("Reading CSV file")
        df = read_csv(data)
        logger.info(f"DataFrame created with {len(df)} rows")
        
        # Convert based on provided parameters
        if wkt_column:
            logger.debug(f"Converting using WKT column: {wkt_column}")
            gdf = wkt_df_to_gdf(df, wkt_column)
        else:
            logger.debug(f"Converting using lat/lon: {lat_name}, {lon_name}")
            gdf = xy_df_to_gdf(df, lat_name, lon_name)
        
        logger.info(f"GeoDataFrame created with {len(gdf)} rows")
        return gdf
```

---

## ✅ Benefits of This Design

1. **Separation of Concerns**
   - Storage handling → `StorageHandler` (unchanged)
   - Format conversion → Converter classes (new)
   - Validation → `VectorHandler` (unchanged)

2. **Dependency Injection**
   - Converters don't know about storage
   - Task service composes: storage + converter + validator
   - Easy to test each piece

3. **Extensibility**
   - Add new format? Create one converter class
   - Register with decorator
   - No changes to existing code

4. **Reusability**
   - Converters work with any BytesIO source
   - Can be used outside job framework
   - Helper functions are pure utilities

5. **Type Safety**
   - Clear interfaces
   - IDE autocomplete
   - Runtime validation via registry

---

## 🔄 Usage Flow

```
User submits job: "upload_vector_to_postgis"
    ↓
Job handler creates Stage 1 task: "load_vector_file"
    ↓
CoreMachine executes task → calls service function
    ↓
Service function:
    1. Get file from storage (StorageHandler)
    2. Get converter from registry (ConverterRegistry)
    3. Convert to GeoDataFrame (Converter.convert())
    ↓
Task result: GeoDataFrame (or serialized)
    ↓
Job handler creates Stage 2 task: "validate_gdf"
    ↓
Service function:
    1. Deserialize GeoDataFrame
    2. Run VectorHandler.prepare_gdf()
    ↓
Task result: Validated GeoDataFrame
    ↓
Job handler creates Stage 3 tasks: Fan-out chunk uploads
    [... parallel PostGIS uploads ...]
```

---

## 🚀 Next Steps

1. Implement `ConverterRegistry`
2. Implement helper functions (`xy_df_to_gdf`, `wkt_df_to_gdf`, `extract_zip_file`)
3. Implement each converter class
4. Create `vector_loader.py` service
5. Update/create job handler for "upload_vector_to_postgis"
6. Write tests for each converter

---

## ❓ Questions to Consider

1. **GeoDataFrame Serialization**: How do we pass GeoDataFrames between stages?
   - Option A: Keep in memory (if same worker)
   - Option B: Serialize to GeoJSON/Parquet and store temporarily
   - Option C: Store in blob storage between stages

2. **Error Handling**: Where do we validate file extensions?
   - Option A: In job handler (before creating task)
   - Option B: In service function (let it fail gracefully)
   - Option C: Both (early validation + defensive service)

3. **Logging**: Do converters log, or only the service?
   - Current design: Converters log (extracted from VectorLoader)
   - Alternative: Silent converters, service logs

What do you think? Should I proceed with implementation, or do you want to refine the design first?
