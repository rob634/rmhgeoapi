# Vector Converter System - Usage Guide

## 🎯 Overview

The converter system provides a composable, extensible architecture for loading vector geospatial files into GeoDataFrames. It follows the same registry pattern as your job and task frameworks.

---

## 📦 Components

### 1. ConverterRegistry (Singleton)
Maps file extensions to converter classes.

### 2. Converter Classes
- `CSVConverter` - CSV files with lat/lon or WKT
- `GeoPackageConverter` - GeoPackage (.gpkg) files
- `GeoJSONConverter` - GeoJSON/JSON files
- `KMLConverter` - KML files
- `KMZConverter` - Compressed KML files
- `ShapefileConverter` - Shapefiles in zip archives

### 3. Helper Functions
- `xy_df_to_gdf()` - Convert lat/lon DataFrame to GeoDataFrame
- `wkt_df_to_gdf()` - Convert WKT DataFrame to GeoDataFrame
- `extract_zip_file()` - Extract files from zip archives

---

## 🔧 Usage Examples

### Standalone Usage (Outside Task Framework)

```python
from converters import ConverterRegistry
from api_clients import StorageHandler

# Get file from storage
storage = StorageHandler(workspace_container_name="uploads")
file_data = storage.blob_to_bytesio("data/parcels.gpkg")

# Get converter
converter = ConverterRegistry.instance().get_converter("gpkg")

# Convert to GeoDataFrame
gdf = converter.convert(file_data, layer_name="parcels")

print(f"Loaded {len(gdf)} features")
```

### Format-Specific Examples

#### CSV with Lat/Lon
```python
converter = ConverterRegistry.instance().get_converter("csv")

gdf = converter.convert(
    csv_data,
    lat_name='latitude',
    lon_name='longitude'
)
```

#### CSV with WKT
```python
converter = ConverterRegistry.instance().get_converter("csv")

gdf = converter.convert(
    csv_data,
    wkt_column='geometry'
)
```

#### GeoPackage (requires layer name)
```python
converter = ConverterRegistry.instance().get_converter("gpkg")

gdf = converter.convert(
    gpkg_data,
    layer_name='parcels'
)
```

#### GeoJSON (self-describing)
```python
converter = ConverterRegistry.instance().get_converter("geojson")

gdf = converter.convert(geojson_data)
```

#### KML (self-describing)
```python
converter = ConverterRegistry.instance().get_converter("kml")

gdf = converter.convert(kml_data)
```

#### KMZ (zipped KML)
```python
converter = ConverterRegistry.instance().get_converter("kmz")

# Use first KML found
gdf = converter.convert(kmz_data)

# Or specify KML file
gdf = converter.convert(kmz_data, kml_name='doc.kml')
```

#### Shapefile (in zip)
```python
converter = ConverterRegistry.instance().get_converter("shp")

# Use first shapefile found
gdf = converter.convert(zip_data)

# Or specify shapefile
gdf = converter.convert(zip_data, shp_name='roads.shp')
```

---

## 🔌 Integration with Task Framework

### In a Job Handler

```python
from jobs.registry import JobRegistry
from core.models.task import TaskDefinition

@JobRegistry.instance().register(job_type="upload_vector_to_postgis")
class UploadVectorToPostGISJob:
    """Job that loads vector file and uploads to PostGIS"""
    
    def create_stage_1_tasks(self, context):
        """Stage 1: Load vector file from blob storage"""
        return [
            TaskDefinition(
                task_type="load_vector_file",
                parameters={
                    "blob_name": context.parameters["file_name"],
                    "container_name": context.parameters["container_name"],
                    "file_extension": context.parameters["file_extension"],
                    
                    # Format-specific parameters
                    **context.parameters.get("converter_params", {})
                }
            )
        ]
    
    def create_stage_2_tasks(self, context):
        """Stage 2: Validate GeoDataFrame"""
        gdf = context.stage_results[1]["gdf"]
        
        return [
            TaskDefinition(
                task_type="validate_geodataframe",
                parameters={"gdf": gdf}
            )
        ]
    
    def create_stage_3_tasks(self, context):
        """Stage 3: Upload chunks to PostGIS"""
        gdf = context.stage_results[2]["validated_gdf"]
        
        # Split into chunks for parallel upload
        chunk_size = 1000
        chunks = [gdf[i:i+chunk_size] for i in range(0, len(gdf), chunk_size)]
        
        return [
            TaskDefinition(
                task_type="upload_gdf_chunk",
                task_index=i,
                parameters={
                    "chunk": chunk,
                    "table_name": context.parameters["table_name"]
                }
            )
            for i, chunk in enumerate(chunks)
        ]
```

### In a Task Handler

```python
from tasks.registry import TaskRegistry
from converters import ConverterRegistry
from api_clients import StorageHandler

@TaskRegistry.instance().register(task_type="load_vector_file")
class LoadVectorFileTask:
    """Task that loads a vector file using converters"""
    
    def execute(self, task_definition):
        params = task_definition.parameters
        
        # Get file from storage
        storage = StorageHandler(
            workspace_container_name=params["container_name"]
        )
        file_data = storage.blob_to_bytesio(params["blob_name"])
        
        # Get converter
        converter = ConverterRegistry.instance().get_converter(
            params["file_extension"]
        )
        
        # Convert with format-specific params
        converter_params = {
            k: v for k, v in params.items()
            if k not in ["blob_name", "container_name", "file_extension"]
        }
        
        gdf = converter.convert(file_data, **converter_params)
        
        return {
            "gdf": gdf,
            "row_count": len(gdf),
            "geometry_types": gdf.geometry.type.unique().tolist()
        }
```

---

## 🚀 Example: Complete Workflow

### Job Submission

```python
# Submit job via HTTP
POST /api/jobs/submit/upload_vector_to_postgis
{
    "file_name": "data/parcels.gpkg",
    "container_name": "uploads",
    "file_extension": "gpkg",
    "table_name": "public.parcels",
    "converter_params": {
        "layer_name": "parcels"
    }
}
```

### Execution Flow

```
1. CoreMachine gets job from JobRegistry
   job_class = JobRegistry.instance().get_job_class("upload_vector_to_postgis")

2. Job creates Stage 1 task
   task = TaskDefinition(
       task_type="load_vector_file",
       parameters={...}
   )

3. CoreMachine executes task via TaskRegistry
   task_handler = TaskRegistry.instance().get_task("load_vector_file")
   result = task_handler.execute(task)

4. Task handler uses converter
   converter = ConverterRegistry.instance().get_converter("gpkg")
   gdf = converter.convert(file_data, layer_name="parcels")

5. GeoDataFrame returned to CoreMachine
   result = {"gdf": gdf, "row_count": 1500, ...}

6. Job aggregates results and creates Stage 2
   ... validation stage ...

7. Job creates Stage 3 fan-out
   ... parallel chunk uploads ...
```

---

## 🎨 Architecture Benefits

### Separation of Concerns
- **Storage**: `StorageHandler` gets files from blob
- **Conversion**: `Converters` transform to GeoDataFrame
- **Validation**: `VectorHandler` cleans/prepares for database
- **Orchestration**: `Jobs` coordinate the workflow
- **Execution**: `Tasks` perform units of work

### Composability
```python
# Mix and match components
storage = StorageHandler(...)
converter = ConverterRegistry.get("csv")
validator = VectorHandler()

# Create custom workflows
gdf = converter.convert(storage.blob_to_bytesio(file))
clean_gdf = validator.prepare_gdf(gdf)
```

### Extensibility
Add new format by creating one file:
```python
# converters/my_new_format.py

@ConverterRegistry.instance().register('xyz')
class XYZConverter:
    @property
    def supported_extensions(self):
        return ['xyz']
    
    def convert(self, data, **kwargs):
        # Your conversion logic
        return gdf
```

That's it! No changes to existing code.

### Testability
```python
# Test converter in isolation
def test_csv_converter():
    converter = CSVConverter()
    
    csv_data = BytesIO(b"lat,lon\n40.7,-74.0")
    
    gdf = converter.convert(
        csv_data,
        lat_name='lat',
        lon_name='lon'
    )
    
    assert len(gdf) == 1
    assert gdf.geometry.type[0] == 'Point'
```

---

## 📋 Supported File Formats

| Extension | Format | Required Parameters | Optional Parameters |
|-----------|--------|---------------------|---------------------|
| `.csv` | CSV | `lat_name` + `lon_name` OR `wkt_column` | `crs` |
| `.gpkg` | GeoPackage | `layer_name` | - |
| `.geojson` | GeoJSON | None | - |
| `.json` | GeoJSON | None | - |
| `.kml` | KML | None | - |
| `.kmz` | Compressed KML | None | `kml_name` |
| `.shp` | Shapefile | None (must be in .zip) | `shp_name` |
| `.zip` | Shapefile archive | None | `shp_name` |

---

## 🔍 Introspection

```python
from converters import ConverterRegistry

registry = ConverterRegistry.instance()

# List supported extensions
extensions = registry.list_supported_extensions()
# ['csv', 'geojson', 'gpkg', 'json', 'kml', 'kmz', 'shp', 'zip']

# Check if format supported
is_supported = registry.is_supported('gpkg')  # True
is_supported = registry.is_supported('gdb')   # False

# Get converter info
converter = registry.get_converter('csv')
print(converter.supported_extensions)  # ['csv']
```

---

## ⚠️ Error Handling

All converters raise `ValueError` with descriptive messages:

```python
try:
    converter = registry.get_converter('unsupported')
except ValueError as e:
    # "No converter registered for '.unsupported'. 
    #  Available: csv, geojson, ..."
    print(e)

try:
    gdf = converter.convert(csv_data)  # Missing lat/lon
except ValueError as e:
    # "Must provide either (lat_name AND lon_name) OR wkt_column"
    print(e)

try:
    gdf = converter.convert(gpkg_data)  # Missing layer_name
except ValueError as e:
    # "layer_name is required for GeoPackage files"
    print(e)
```

---

## 🧪 Testing

```python
import pytest
from io import BytesIO
from converters import ConverterRegistry

def test_csv_latlon():
    converter = ConverterRegistry.instance().get_converter('csv')
    
    csv_data = BytesIO(b"lat,lon,name\n40.7,-74.0,NYC\n34.0,-118.2,LA")
    
    gdf = converter.convert(csv_data, lat_name='lat', lon_name='lon')
    
    assert len(gdf) == 2
    assert all(gdf.geometry.type == 'Point')
    assert gdf.crs.to_string() == 'EPSG:4326'

def test_csv_wkt():
    converter = ConverterRegistry.instance().get_converter('csv')
    
    csv_data = BytesIO(b'geom,name\n"POINT(-74.0 40.7)",NYC')
    
    gdf = converter.convert(csv_data, wkt_column='geom')
    
    assert len(gdf) == 1
    assert gdf.geometry.type[0] == 'Point'
```

---

## 🔄 Migration from Old Code

### Before (VectorLoader)
```python
from loader import VectorLoader

loader = VectorLoader(
    file_name="data.csv",
    lat_name="lat",
    lon_name="lon",
    container_name="uploads"
)

gdf = VectorLoader.from_blob_file(
    file_name="data.csv",
    file_type="csv",
    lat_name="lat",
    lon_name="lon"
)
```

### After (Converter System)
```python
from converters import ConverterRegistry
from api_clients import StorageHandler

# Get file
storage = StorageHandler(workspace_container_name="uploads")
file_data = storage.blob_to_bytesio("data.csv")

# Convert
converter = ConverterRegistry.instance().get_converter("csv")
gdf = converter.convert(
    file_data,
    lat_name="lat",
    lon_name="lon"
)
```

**Benefits of new approach:**
- ✅ Storage and conversion decoupled
- ✅ No class instantiation needed
- ✅ Registry enables dynamic lookup
- ✅ Each converter is independently testable
- ✅ Easy to use in different contexts (tasks, scripts, notebooks)

---

## 📚 Next Steps

1. **Create validate_geodataframe task** - Uses `VectorHandler` to clean GeoDataFrame
2. **Create upload_gdf_chunk task** - Uploads chunk to PostGIS
3. **Wire up complete job** - Upload vector to PostGIS workflow
4. **Add tests** - Unit tests for each converter
5. **Add monitoring** - Log metrics (file size, conversion time, row count)
