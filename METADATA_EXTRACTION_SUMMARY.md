# Metadata Extraction Service - Complete Field Summary

## Overview
The Azure Geospatial ETL Pipeline's metadata extraction service provides comprehensive metadata extraction from geospatial files, particularly raster data. The service extracts metadata at multiple levels, from basic file properties to detailed band statistics.

---

## 1. File Properties
Basic file-level metadata extracted for all files:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `size_bytes` | integer | File size in bytes | 124715444 |
| `size_mb` | float | File size in megabytes | 118.94 |
| `extension` | string | File extension | "tif" |
| `extraction_timestamp` | string | ISO 8601 timestamp of extraction | "2025-08-20T00:00:00" |

## 2. Checksums
Cryptographic hashes for file integrity verification:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `md5` | string | MD5 hash (128-bit) | "f4d7a5058830edabbd9c428acda28fdc" |
| `sha256` | string | SHA-256 hash (256-bit) | "87426b5743cdbf36d51e7318c2fc487b..." |
| `sha1` | string | SHA-1 hash (160-bit) | "5b0e921d318ac9272b6ef176841da544..." |

## 3. Raster Metadata
Comprehensive raster-specific metadata using rasterio:

### 3.1 Basic Properties
| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `driver` | string | GDAL driver name | "GTiff" |
| `compression` | string | Compression type | "lzw", "deflate", "jpeg", "none" |
| `nodata` | varies | NoData value(s) | null, 0, -9999 |

### 3.2 Dimensions
| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `width` | integer | Raster width in pixels | 5748 |
| `height` | integer | Raster height in pixels | 4156 |
| `bands` | integer | Number of bands | 4 |
| `cells` | integer | Total pixel count | 23888688 |

### 3.3 Data Types
| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `dtypes` | array | Data type per band | ["uint16", "uint16", "uint16", "uint16"] |

### 3.4 Coordinate Reference System (CRS)
| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `epsg` | integer | EPSG code | 32637 |
| `wkt` | string | Well-Known Text representation | "PROJCS[\"WGS 84 / UTM zone 37N\"..." |
| `proj4` | string | PROJ4 string | "+proj=utm +zone=37 +datum=WGS84..." |
| `units` | string | CRS units | "metre", "degree" |

### 3.5 Spatial Bounds
#### Native Coordinates
| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `left` | float | Western boundary | 221109.6 |
| `bottom` | float | Southern boundary | 3533512.8 |
| `right` | float | Eastern boundary | 224558.4 |
| `top` | float | Northern boundary | 3536006.4 |

#### Geographic Coordinates (WGS84)
| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `west` | float | Western longitude | 36.050 |
| `south` | float | Southern latitude | 31.903 |
| `east` | float | Eastern longitude | 36.087 |
| `north` | float | Northern latitude | 31.926 |

### 3.6 Transform & Resolution
| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `affine` | array | Affine transformation matrix (6 values) | [0.6, 0.0, 221109.6, 0.0, -0.6, 3536006.4] |
| `pixel_size.x` | float | Pixel width in CRS units | 0.6 |
| `pixel_size.y` | float | Pixel height in CRS units | 0.6 |

### 3.7 Band Information
For each band in the raster:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `index` | integer | Band number (1-based) | 1 |
| `dtype` | string | Data type | "uint16" |
| `color_interpretation` | string | Color interpretation | "red", "green", "blue", "alpha", "gray" |
| `description` | string | Band description | "Near Infrared" |
| `tags` | object | Band-specific tags | {"STATISTICS_MEAN": "441.7"} |

## 4. TIFF Tags
Standard TIFF and GeoTIFF specific tags:

### 4.1 Standard TIFF Tags
| Tag Name | Description | Example Value |
|----------|-------------|---------------|
| `ImageWidth` | Image width in pixels | 5748 |
| `ImageLength` | Image height in pixels | 4156 |
| `BitsPerSample` | Bits per channel | [16, 16, 16, 16] |
| `Compression` | Compression scheme | 5 (LZW) |
| `PhotometricInterpretation` | Color space | 2 (RGB) |
| `SamplesPerPixel` | Number of channels | 4 |
| `PlanarConfiguration` | Data organization | 1 (Chunky) |
| `Software` | Software used | "GDAL 3.4.1" |
| `DateTime` | Creation timestamp | "2013:04:05 08:27:06" |
| `TileWidth` | Tile width (if tiled) | 256 |
| `TileLength` | Tile height (if tiled) | 256 |

### 4.2 GeoTIFF Tags
| Tag Category | Fields | Description |
|--------------|--------|-------------|
| `dataset` | Various | Dataset-level tags |
| `tiff` | TIFF namespace | TIFF-specific metadata |
| `image_structure` | `INTERLEAVE`, `COMPRESSION` | Image structure info |
| `geotiff` | GeoTIFF keys | Georeferencing information |

## 5. EXIF Data
Exchangeable Image File Format metadata:

### 5.1 Standard EXIF Tags
| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `Make` | string | Camera manufacturer | "DJI" |
| `Model` | string | Camera model | "FC6310" |
| `DateTime` | string | Capture timestamp | "2023:06:15 14:30:00" |
| `ExposureTime` | fraction | Exposure time | [1, 2000] |
| `FNumber` | float | F-stop | 2.8 |
| `ISO` | integer | ISO speed | 100 |
| `FocalLength` | float | Focal length (mm) | 8.8 |
| `ImageWidth` | integer | Image width | 5748 |
| `ImageHeight` | integer | Image height | 4156 |

### 5.2 GPS Data
| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `GPSLatitude` | array | Latitude (degrees, minutes, seconds) | [[31, 1], [54, 1], [30, 100]] |
| `GPSLatitudeRef` | string | Latitude hemisphere | "N" or "S" |
| `GPSLongitude` | array | Longitude (degrees, minutes, seconds) | [[36, 1], [3, 1], [15, 100]] |
| `GPSLongitudeRef` | string | Longitude hemisphere | "E" or "W" |
| `GPSAltitude` | fraction | Altitude in meters | [350, 1] |
| `GPSAltitudeRef` | integer | Altitude reference | 0 (above sea level) |
| `coordinates.latitude` | float | Decimal degrees latitude | 31.908333 |
| `coordinates.longitude` | float | Decimal degrees longitude | 36.054167 |
| `coordinates.altitude` | float | Altitude in meters | 350.0 |

## 6. Statistical Analysis
Comprehensive statistical analysis per raster band:

### 6.1 Basic Statistics
| Field | Type | Description | Range/Example |
|-------|------|-------------|---------------|
| `band` | integer | Band number | 1, 2, 3, 4 |
| `min` | float | Minimum value | 0.0 - varies |
| `max` | float | Maximum value | 1778.0 |
| `mean` | float | Average value | 441.71 |
| `std` | float | Standard deviation | 155.69 |
| `median` | float | Median value | 461.0 |
| `valid_pixels` | integer | Non-nodata pixel count | 23888688 |
| `total_pixels` | integer | Total pixel count | 23888688 |

### 6.2 Percentiles
| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `p25` | float | 25th percentile | 350.0 |
| `p50` | float | 50th percentile (median) | 461.0 |
| `p75` | float | 75th percentile | 525.0 |
| `p90` | float | 90th percentile | 615.0 |
| `p95` | float | 95th percentile | 675.0 |
| `p99` | float | 99th percentile | 825.0 |

### 6.3 Histogram
| Field | Type | Description | Details |
|-------|------|-------------|---------|
| `counts` | array[256] | Frequency per bin | Pixel count distribution |
| `bin_edges` | array[257] | Bin boundaries | Value ranges for histogram |

## 7. Processing Metadata
Metadata about the processing operation itself:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `status` | string | Processing status | "completed", "failed" |
| `operation` | string | Operation type | "extract_metadata" |
| `filename` | string | Source filename | "sample.tif" |
| `container` | string | Azure container name | "rmhazuregeobronze" |
| `job_id` | string | Unique job identifier | "sha256_hash..." |
| `created_at` | string | Job creation time | "2025-08-20T00:00:00Z" |
| `updated_at` | string | Last update time | "2025-08-20T00:01:00Z" |

---

## Operation-Specific Metadata

### `extract_metadata` Operation
Returns ALL metadata categories above in a single comprehensive response.

### `extract_tiff_tags` Operation
Returns only:
- TIFF tags (Section 4.1)
- GeoTIFF tags (Section 4.2)
- Image info (format, mode, size)

### `extract_exif` Operation
Returns only:
- EXIF data (Section 5.1)
- GPS data (Section 5.2)

### `extract_statistics` Operation
Returns only:
- Band statistics (Section 6)
- Summary information (band count, dimensions, data types)

### `raster_info` Operation
Returns:
- Dimensions (Section 3.2)
- CRS information (Section 3.4)
- Spatial bounds (Section 3.5)
- Transform & resolution (Section 3.6)
- Data types and compression

---

## Example Use Cases

### 1. Data Validation
- Verify file integrity using checksums
- Validate CRS and spatial extent
- Check data types and NoData values

### 2. Data Cataloging
- Build searchable metadata catalogs
- Index by spatial extent, CRS, or resolution
- Track data lineage and processing history

### 3. Quality Control
- Analyze band statistics for anomalies
- Check histogram distribution for data issues
- Verify compression and optimization

### 4. Spatial Analysis
- Extract coordinate bounds for spatial queries
- Determine pixel resolution for scale analysis
- Convert between coordinate systems

### 5. Data Discovery
- Search by GPS coordinates
- Filter by acquisition date/time
- Group by sensor or camera model

---

## Performance Characteristics

| File Size | Extraction Time | Memory Usage |
|-----------|----------------|--------------|
| < 10 MB | < 2 seconds | < 100 MB |
| 10-100 MB | 2-5 seconds | < 500 MB |
| 100-500 MB | 5-15 seconds | < 1 GB |
| > 500 MB | 15-30 seconds | < 2 GB |

*Note: Statistics extraction takes longer due to full raster scanning*

---

## Future Enhancements

### Planned Metadata Additions
1. **Vector Metadata** - Geometry types, feature counts, attribute schemas
2. **Cloud Optimized** - COG validation details, overview levels
3. **Temporal Metadata** - Time series information, acquisition dates
4. **Quality Metrics** - Cloud cover, image quality scores
5. **Provenance** - Processing history, source tracking
6. **Spectral Information** - Wavelength ranges, band names
7. **Sensor Metadata** - Platform, sensor type, acquisition parameters

### Planned Format Support
- **Vector Formats**: Shapefile, GeoJSON, GeoPackage, KML/KMZ
- **Point Clouds**: LAS/LAZ metadata
- **NetCDF/HDF**: Scientific data formats
- **STAC**: Spatio-Temporal Asset Catalog integration