# Error Troubleshooting Guide

**Last Updated**: 09 FEB 2026
**Status**: Complete (BUG_REFORM Phase 6)
**Audience**: Data Publishers, QA Testers, Support Team

---

## How to Use This Guide

1. **Find your error** - Search by error code or error message
2. **Understand the problem** - Read the description and likely causes
3. **Apply the fix** - Follow the step-by-step remediation
4. **Prevent recurrence** - Review the prevention tips

---

## Table of Contents

1. [DATA_MISSING Errors](#data_missing-errors) - File/resource not found
2. [DATA_QUALITY Errors](#data_quality-errors) - File content problems
3. [DATA_INCOMPATIBLE Errors](#data_incompatible-errors) - Collection mismatches
4. [PARAMETER_ERROR Errors](#parameter_error-errors) - Request problems
5. [SERVICE_UNAVAILABLE Errors](#service_unavailable-errors) - Temporary issues
6. [SYSTEM_ERROR Errors](#system_error-errors) - Internal problems
7. [CONFIGURATION Errors](#configuration-errors) - Setup problems

---

## DATA_MISSING Errors

### FILE_NOT_FOUND

**Error Message**: "File '{blob_name}' not found in container '{container}'"

**Likely Causes**:
1. Typo in file path
2. Upload not completed before job submission
3. File deleted after upload
4. Wrong container specified

**Fix**:
```bash
# 1. Verify the file exists
az storage blob list --container-name bronze-uploads --prefix "your/path/" --output table

# 2. If file missing, re-upload
az storage blob upload --container-name bronze-uploads --file ./local/file.tif --name "your/path/file.tif"

# 3. Wait for upload to complete before submitting job
```

**Prevention**:
- Always verify upload success before job submission
- Use exact paths from upload response
- Implement upload verification in your workflow

---

### CONTAINER_NOT_FOUND

**Error Message**: "Container '{container}' not found"

**Likely Causes**:
1. Typo in container name
2. Container doesn't exist
3. Permissions issue (can't see container)

**Fix**:
```bash
# 1. List available containers
az storage container list --output table

# 2. Use the correct container name
# Common containers: bronze-uploads, bronze-rasters, bronze-vectors
```

**Prevention**:
- Use constants for container names in code
- Validate container name before job submission

---

## DATA_QUALITY Errors

### CRS_MISSING

**Error Message**: "File has no coordinate reference system and no 'input_crs' parameter"

**Likely Causes**:
1. Source file lacks embedded CRS
2. Original data was in local/unknown coordinate system
3. CRS stripped during export

**Fix**:

Option A - Add `input_crs` parameter:
```json
{
    "blob_name": "data.tif",
    "input_crs": "EPSG:4326"
}
```

Option B - Embed CRS in source file:
```bash
# For raster (using GDAL)
gdal_edit.py -a_srs "EPSG:4326" your_file.tif

# For vector (using ogr2ogr)
ogr2ogr -a_srs "EPSG:4326" output.gpkg input.gpkg
```

**Prevention**:
- Always check CRS before uploading: `gdalinfo file.tif | grep EPSG`
- Include CRS specification in data delivery requirements

---

### CRS_MISMATCH

**Error Message**: "File has CRS {file_crs} but you specified {user_crs}"

**Likely Causes**:
1. File has embedded CRS different from specified
2. Copy-paste error in `input_crs` parameter
3. File was reprojected but parameter wasn't updated

**Fix**:

Option A - Remove `input_crs` (use file's CRS):
```json
{
    "blob_name": "data.tif"
    // Remove input_crs, let system use file's CRS
}
```

Option B - Re-export file with correct CRS:
```bash
gdalwarp -t_srs "EPSG:4326" input.tif output.tif
```

---

### RASTER_64BIT_REJECTED

**Error Message**: "File uses 64-bit data type ({dtype}) which is not accepted"

**Likely Causes**:
1. Scientific software defaulted to float64
2. Unnecessary precision for geospatial data
3. GIS software export settings

**Why Rejected**:
- 64-bit precision is never needed for geospatial elevation/imagery
- Doubles storage costs
- Slows processing

**Fix**:
```bash
# Convert to 32-bit float
gdal_translate -ot Float32 input.tif output.tif

# Or for integer data
gdal_translate -ot Int32 input.tif output.tif
```

**Prevention**:
- Configure export settings to use Float32
- Check dtype before upload: `gdalinfo file.tif | grep Type`

---

### RASTER_EMPTY

**Error Message**: "File is {percent}% nodata - effectively empty"

**Likely Causes**:
1. Processing error created mostly-nodata output
2. Wrong crop/clip extent
3. Source data was already sparse

**Fix**:
1. Check your processing workflow
2. Verify clip/crop boundaries
3. Ensure source data covers the expected area

```bash
# Check nodata statistics
gdalinfo -stats file.tif | grep -E "Minimum|Maximum|NoData"
```

**Prevention**:
- Add nodata percentage check to QA workflow
- Verify output visually before upload

---

### RASTER_NODATA_CONFLICT

**Error Message**: "Nodata value ({nodata}) appears in actual data, causing data loss"

**Likely Causes**:
1. Nodata value (e.g., -9999) exists as real data value
2. Default nodata conflicts with elevation range
3. Integer nodata used for float data

**Fix**:

Option A - Change nodata value:
```bash
# Set nodata to value not in data range
gdal_edit.py -a_nodata -99999 file.tif

# Or use NaN for float data
gdal_edit.py -a_nodata nan file.tif
```

Option B - Unset nodata:
```bash
gdal_edit.py -unsetnodata file.tif
```

**Prevention**:
- Check data range before setting nodata: `gdalinfo -mm file.tif`
- Use NaN for float data, extreme values for integers

---

### RASTER_EXTREME_VALUES

**Error Message**: "DEM contains extreme values (max: {max}) suggesting corrupt or unset nodata"

**Likely Causes**:
1. NoData value not properly set (1e38, 3.4e38 are common defaults)
2. Processing created invalid values
3. File corruption

**Fix**:
```bash
# 1. Check current values
gdalinfo -stats file.tif

# 2. Set proper nodata
gdal_edit.py -a_nodata 3.4028235e+38 file.tif  # If that's the nodata value

# Or remove invalid pixels
gdal_calc.py -A input.tif --outfile=output.tif --calc="where(A<1e30, A, -9999)" --NoDataValue=-9999
```

---

### VECTOR_UNREADABLE

**Error Message**: "File '{blob_name}' could not be parsed as {format}"

**Likely Causes**:
1. File is not the format it claims to be
2. File is corrupted/truncated
3. Encoding issues
4. Missing companion files (for Shapefile)

**Fix**:
```bash
# 1. Verify file format
ogrinfo -al -so file.gpkg

# 2. For Shapefile, ensure all companions exist
ls -la myfile.shp myfile.shx myfile.dbf myfile.prj

# 3. Try re-exporting from source
ogr2ogr -f "GPKG" output.gpkg input_source
```

**Prevention**:
- Use GeoPackage instead of Shapefile (single file, fewer issues)
- Validate files before upload: `ogrinfo -so file.gpkg`

---

### VECTOR_NO_FEATURES

**Error Message**: "File contains no features after removing invalid geometries"

**Likely Causes**:
1. Source file is empty
2. All geometries are invalid
3. Filter criteria excluded all features

**Fix**:
```bash
# 1. Check feature count
ogrinfo -al -so file.gpkg | grep "Feature Count"

# 2. Check for invalid geometries
ogrinfo -dialect sqlite -sql "SELECT COUNT(*) FROM (SELECT * FROM layer_name WHERE NOT ST_IsValid(geom))" file.gpkg
```

---

### VECTOR_GEOMETRY_INVALID

**Error Message**: "{count} features have invalid geometry that cannot be auto-repaired"

**Likely Causes**:
1. Self-intersecting polygons
2. Duplicate vertices
3. Topology errors from digitization

**Fix**:
```bash
# 1. Repair geometries using PostGIS
ogr2ogr -f "GPKG" -nlt PROMOTE_TO_MULTI \
    -dialect sqlite \
    -sql "SELECT ST_MakeValid(geom) as geom, * FROM layer_name" \
    output.gpkg input.gpkg

# 2. Or in QGIS: Vector > Geometry Tools > Fix Geometries
```

**Prevention**:
- Run geometry validation before upload
- Use topology-aware GIS tools for editing

---

### VECTOR_TABLE_NAME_INVALID

**Error Message**: "Table name '{name}' is invalid: {reason}"

**Rules**:
- Lowercase letters, numbers, underscores only
- Cannot start with a number
- Maximum 63 characters
- Cannot be a reserved word

**Examples**:
```
Invalid: 123_data        (starts with number)
Invalid: My Data         (spaces, uppercase)
Invalid: data-set        (hyphen)
Invalid: select          (reserved word)

Valid:   data_123
Valid:   my_data_set
Valid:   ethiopia_admin_boundaries
```

---

### VECTOR_ENCODING_ERROR

**Error Message**: "File contains invalid characters (encoding: {detected})"

**Likely Causes**:
1. File uses non-UTF-8 encoding
2. Special characters from legacy systems
3. Mixed encodings

**Fix**:
```bash
# 1. Convert to UTF-8
ogr2ogr -f "GPKG" -lco ENCODING=UTF-8 output.gpkg input.shp

# 2. Or specify source encoding
ogr2ogr -f "GPKG" output.gpkg input.shp --config SHAPE_ENCODING "ISO-8859-1"
```

---

## DATA_INCOMPATIBLE Errors

These errors occur when files are individually valid but incompatible as a collection.

### COLLECTION_BAND_MISMATCH

**Error Message**: "Files have different band counts"

**Example**:
```
tile_001.tif: 3 bands (RGB)
tile_015.tif: 1 band (DEM)
```

**Fix**:
1. Remove incompatible files from collection
2. Submit RGB and DEM as separate jobs

**Prevention**:
- Organize files by type before creating collections
- Use naming conventions: `rgb_*.tif`, `dem_*.tif`

---

### COLLECTION_CRS_MISMATCH

**Error Message**: "Files have different coordinate systems"

**Fix**:
```bash
# Reproject all files to same CRS
for f in *.tif; do
    gdalwarp -t_srs "EPSG:4326" "$f" "reprojected_$f"
done
```

---

### COLLECTION_RESOLUTION_MISMATCH

**Error Message**: "Resolution varies too much: {res1}m to {res2}m"

**Fix**:
```bash
# Resample to consistent resolution
gdalwarp -tr 10 10 -r bilinear input.tif output.tif
```

**Note**: Default tolerance is 20%. Can be adjusted via `resolution_tolerance_percent` parameter.

---

### COLLECTION_TYPE_MISMATCH

**Error Message**: "Collection mixes incompatible raster types"

**Example**:
```
RGB imagery mixed with elevation DEM
```

**Fix**:
- Don't mix imagery with elevation data
- Submit as separate collections
- Use `raster_type` parameter if auto-detection fails

---

## PARAMETER_ERROR Errors

### MISSING_PARAMETER

**Error Message**: "Required parameter '{param}' not provided"

**Fix**: Add the missing parameter to your request.

**Common Required Parameters**:

| Endpoint | Required |
|----------|----------|
| `/platform/submit` (raster) | `blob_name` |
| `/platform/submit` (vector) | `blob_name`, `table_name` |
| `/platform/submit` (CSV) | `blob_name`, `table_name`, `lat_name`, `lon_name` |

---

### INVALID_PARAMETER

**Error Message**: "Parameter '{param}' has invalid value"

**Fix**: Check parameter value against allowed values in API documentation.

---

## SERVICE_UNAVAILABLE Errors

These are temporary issues that typically resolve on their own.

### DATABASE_TIMEOUT / STORAGE_TIMEOUT / TIMEOUT

**Error Message**: "Operation timed out"

**What's Happening**: The system is under high load or experiencing temporary issues.

**Fix**:
1. Wait 1-2 minutes
2. Retry the request
3. If persistent, contact support

**Prevention**:
- Implement retry logic with exponential backoff
- Avoid submitting large batches simultaneously

---

### THROTTLED

**Error Message**: "Rate limited"

**What's Happening**: Too many requests in short time period.

**Fix**:
1. Wait longer between requests (5-10 seconds)
2. Implement rate limiting in your client

---

## SYSTEM_ERROR Errors

These are internal errors. Not your fault.

### COG_CREATION_FAILED / COG_TRANSLATE_FAILED

**Error Message**: "Failed to create Cloud Optimized GeoTIFF"

**What To Do**:
1. Note the `error_id` from the response
2. Retry once (might be transient)
3. If persistent, contact support with error_id

**Possible Hidden Causes**:
- Unusual CRS that GDAL can't handle
- Corrupted source file that passed initial validation
- Resource exhaustion (memory/disk)

---

### PROCESSING_FAILED

**Error Message**: "Processing failed"

**What To Do**:
1. Check if input data has unusual characteristics
2. Note the `error_id`
3. Contact support if persistent

---

## CONFIGURATION Errors

These indicate system setup problems.

### CONFIG_ERROR / SETUP_FAILED

**Error Message**: "Service configuration error" / "Service initialization failed"

**What's Happening**: The system is misconfigured. This is an ops issue.

**What To Do**:
1. This is NOT your fault
2. Contact support immediately with `error_id`
3. Do not retry - it won't help

---

## Quick Diagnostic Checklist

### Before Submitting a Raster Job

- [ ] File exists at specified path
- [ ] File has CRS (or `input_crs` provided)
- [ ] Data type is not 64-bit
- [ ] File is not mostly nodata
- [ ] NoData value doesn't conflict with real data

### Before Submitting a Vector Job

- [ ] File exists at specified path
- [ ] File can be opened by `ogrinfo`
- [ ] File has valid geometries
- [ ] File is UTF-8 encoded
- [ ] Table name is valid (lowercase, no spaces, no reserved words)

### Before Submitting a Collection

- [ ] All files have same band count
- [ ] All files have same data type
- [ ] All files have same CRS
- [ ] Resolutions are within 20%
- [ ] All files are same type (don't mix RGB and DEM)

---

## Getting Help

### Self-Service

1. Search this guide for your error code
2. Check [Error Code Reference](./ERROR_CODE_REFERENCE.md) for details
3. Review [B2B Error Handling Guide](./B2B_ERROR_HANDLING_GUIDE.md) for integration

### Contact Support

Include in your ticket:
- **error_id**: The unique identifier from the error response
- **Timestamp**: When the error occurred
- **Job ID**: If available
- **File name**: The file that caused the error
- **Steps to reproduce**: If the error is consistent

---

*Document maintained by: Engineering Team*
*Last updated: 09 FEB 2026*
