# Vector ETL Error Handling Guide

**Date**: 26 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: IMPLEMENTED ✅

## Executive Summary

The Vector ETL workflows now have comprehensive error handling with granular try-except blocks, detailed logging, and recovery strategies. This guide documents the error handling patterns and how to use them.

## Error Handling Architecture

### Three-Layer Error Strategy

1. **Task Level** - High-level workflow errors
2. **Operation Level** - Specific operation failures
3. **Row Level** - Individual data record errors

### Custom Exception Hierarchy

```python
VectorTaskError (Base)
├── BlobAccessError      # Storage access issues
├── FormatConversionError # File format problems
├── ValidationError       # Data validation failures
└── PostGISError         # Database operation errors
    ├── ConnectionError   # Cannot connect to database
    ├── TableCreationError # DDL failures
    ├── DataInsertionError # DML failures
    └── GeometryValidationError # Spatial data issues
```

## Enhanced Files Created

### 1. `postgis_handler_enhanced.py`

**Key Features:**
- Granular error handling for each operation
- Connection retry logic (3 attempts)
- Transaction management with automatic rollback
- Row-level error tracking for batch operations
- Detailed logging with operation context

**Error Handling Pattern:**
```python
def upload_chunk(self, chunk, table_name, schema="geo"):
    conn = None
    try:
        # Connection with retry
        for attempt in range(3):
            try:
                conn = psycopg.connect(self.conn_string)
                break
            except psycopg.OperationalError as e:
                if attempt < 2:
                    logger.warning(f"Connection attempt {attempt+1} failed, retrying...")
                else:
                    raise ConnectionError(f"Cannot connect after 3 attempts: {e}")

        # Table creation
        try:
            self._create_table_if_not_exists_safe(cur, chunk, table_name, schema)
        except Exception as e:
            raise TableCreationError(f"Cannot create table: {e}")

        # Data insertion with row-level tracking
        try:
            rows_inserted = self._insert_features_safe(cur, chunk, table_name, schema)
        except Exception as e:
            raise DataInsertionError(f"Failed to insert data: {e}")

        conn.commit()

    except Exception as e:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()
```

### 2. `tasks_enhanced.py`

**Key Features:**
- Format-specific error messages
- Blob storage retry logic
- Validation with fallback strategies
- Partial data recovery
- Memory-efficient error handling

**Error Handling Examples:**

#### Blob Access with Retry
```python
for attempt in range(max_retries):
    try:
        blob_repo = BlobRepository.instance()

        # Check existence first
        if not blob_repo.blob_exists(container_name, blob_name):
            raise BlobAccessError(f"Blob not found: {container_name}/{blob_name}")

        file_data = blob_repo.read_blob_to_stream(container_name, blob_name)
        break

    except BlobAccessError:
        raise  # Don't retry if blob doesn't exist

    except Exception as e:
        if attempt < max_retries - 1:
            logger.warning(f"Attempt {attempt+1} failed, retrying...")
        else:
            raise BlobAccessError(f"Cannot access blob: {e}")
```

#### Format-Specific Error Handling
```python
try:
    gdf = converter_func(file_data, **converter_params)

except FileNotFoundError as e:
    # Missing file in archive
    raise FormatConversionError(f"Required file missing in {format_name}: {e}")

except ValueError as e:
    # Data format issues
    raise FormatConversionError(f"Invalid {format_name} format: {e}")

except MemoryError as e:
    # File too large
    raise FormatConversionError(f"File too large to process: {e}")
```

## Error Tracking and Reporting

### Session Error Tracking

The enhanced handlers track errors throughout a session:

```python
handler = VectorToPostGISHandler()
handler.upload_chunk(chunk, table_name)

# Get error summary
summary = handler.get_error_summary()
# {
#     "errors": ["Connection failed: ...", "Table creation failed: ..."],
#     "warnings": ["Invalid geometry at row 5", "Column name conflict resolved"],
#     "error_count": 2,
#     "warning_count": 2
# }
```

### Detailed Logging Format

All operations use structured logging with context:

```
2025-10-26 10:15:30 - postgis_handler - INFO - [upload_chunk:275] - 📤 Starting upload of 1000 features to geo.parcels
2025-10-26 10:15:30 - postgis_handler - DEBUG - [upload_chunk:281] - Connection attempt 1/3
2025-10-26 10:15:30 - postgis_handler - INFO - [upload_chunk:284] - ✅ Database connection established
2025-10-26 10:15:31 - postgis_handler - WARNING - [_insert_features_safe:425] - ⚠️ Failed to insert row 42: Invalid geometry
2025-10-26 10:15:32 - postgis_handler - INFO - [upload_chunk:312] - ✅ Successfully inserted 999/1000 rows
```

## Usage Patterns

### 1. Basic Usage with Error Handling

```python
from services.vector.postgis_handler_enhanced import VectorToPostGISHandler

handler = VectorToPostGISHandler()

try:
    # Prepare data with validation
    clean_gdf = handler.prepare_gdf(raw_gdf)

    # Upload with error tracking
    handler.upload_chunk(clean_gdf, "my_table", "geo")

    # Check for warnings
    summary = handler.get_error_summary()
    if summary["warning_count"] > 0:
        logger.warning(f"Upload completed with {summary['warning_count']} warnings")
        for warning in summary["warnings"]:
            logger.warning(f"  - {warning}")

except GeometryValidationError as e:
    logger.error(f"Geometry validation failed: {e}")
    # Handle geometry issues

except ConnectionError as e:
    logger.error(f"Database connection failed: {e}")
    # Handle connection issues

except PostGISError as e:
    logger.error(f"PostGIS operation failed: {e}")
    # Handle other PostGIS issues
```

### 2. Task Handler with Error Context

```python
from services.vector.tasks_enhanced import load_vector_file

try:
    result = load_vector_file({
        "blob_name": "data/parcels.gpkg",
        "file_extension": "gpkg",
        "container_name": "bronze"
    })

    # Check validation report
    if "validation_report" in result:
        report = result["validation_report"]
        logger.info(f"Processed {report['output_features']} features")

        if report["warnings"]:
            for warning in report["warnings"]:
                logger.warning(warning)

except BlobAccessError as e:
    # Storage access issue
    return {"success": False, "error": "storage_access", "message": str(e)}

except FormatConversionError as e:
    # File format issue
    return {"success": False, "error": "invalid_format", "message": str(e)}

except ValidationError as e:
    # Data validation issue
    return {"success": False, "error": "validation_failed", "message": str(e)}
```

### 3. Batch Processing with Row-Level Error Handling

```python
def process_vector_batch(chunks):
    results = {
        "successful_chunks": 0,
        "failed_chunks": 0,
        "partial_chunks": 0,
        "total_rows": 0,
        "successful_rows": 0,
        "failed_rows": []
    }

    handler = VectorToPostGISHandler()

    for i, chunk in enumerate(chunks):
        try:
            handler.clear_error_tracking()
            handler.upload_chunk(chunk, "my_table")

            summary = handler.get_error_summary()

            if summary["error_count"] == 0:
                results["successful_chunks"] += 1
            else:
                results["partial_chunks"] += 1
                results["failed_rows"].extend(
                    [f"Chunk {i}: {err}" for err in summary["errors"]]
                )

            results["total_rows"] += len(chunk)
            results["successful_rows"] += len(chunk) - summary["error_count"]

        except Exception as e:
            results["failed_chunks"] += 1
            results["failed_rows"].append(f"Chunk {i} failed completely: {e}")
            logger.error(f"Chunk {i} failed: {e}")

    return results
```

## Error Recovery Strategies

### 1. Geometry Repair

The enhanced handler attempts multiple repair strategies:

```python
# Strategy 1: Buffer(0) trick
if not geom.is_valid:
    fixed_geom = geom.buffer(0)

# Strategy 2: Shapely make_valid
if not fixed_geom.is_valid:
    fixed_geom = make_valid(geom)

# Strategy 3: Skip geometry
if still_invalid:
    logger.warning(f"Skipping unfixable geometry at row {idx}")
    continue
```

### 2. Connection Retry

Automatic retry with exponential backoff:

```python
for attempt in range(max_retries):
    try:
        conn = psycopg.connect(self.conn_string)
        break
    except psycopg.OperationalError:
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)  # Exponential backoff
            continue
        raise
```

### 3. Partial Data Recovery

Continue processing even with failures:

```python
failed_rows = []
for idx, row in chunk.iterrows():
    try:
        insert_row(row)
    except Exception as e:
        failed_rows.append(idx)
        logger.warning(f"Row {idx} failed: {e}")
        continue  # Process next row

if failed_rows:
    logger.warning(f"Partial success: {len(chunk) - len(failed_rows)}/{len(chunk)} rows inserted")
```

## Monitoring and Debugging

### Application Insights Integration

All error logs are structured for Application Insights:

```python
logger.error(f"PostGIS operation failed", extra={
    "custom_dimensions": {
        "operation": "upload_chunk",
        "table": table_name,
        "schema": schema,
        "error_type": type(e).__name__,
        "chunk_size": len(chunk)
    }
})
```

### Debug Mode

Enable verbose logging for development:

```python
import logging
logging.getLogger("services.vector").setLevel(logging.DEBUG)
```

## Testing Error Scenarios

### Unit Tests for Error Handling

```python
def test_handles_connection_failure():
    handler = VectorToPostGISHandler()
    handler.conn_string = "invalid_connection_string"

    with pytest.raises(ConnectionError) as exc_info:
        handler.upload_chunk(test_gdf, "test_table")

    assert "Cannot connect" in str(exc_info.value)

def test_handles_invalid_geometry():
    handler = VectorToPostGISHandler()

    # Create GDF with invalid geometry
    invalid_gdf = gpd.GeoDataFrame(
        {"col1": [1]},
        geometry=[Polygon([(0, 0), (1, 1), (0, 0)])]  # Invalid polygon
    )

    # Should fix and continue
    result = handler.prepare_gdf(invalid_gdf)
    assert len(result) > 0
    assert result.geometry[0].is_valid
```

## Best Practices

1. **Always use enhanced handlers** for production workflows
2. **Check error summaries** after operations
3. **Log warnings** even if operation succeeds
4. **Clear error tracking** between batch operations
5. **Use specific exception types** for different error handling
6. **Include context** in error messages (table name, row index, etc.)
7. **Test error scenarios** in development environment

## Migration Guide

To migrate existing code to use enhanced error handling:

1. Replace imports:
```python
# Old
from services.vector.postgis_handler import VectorToPostGISHandler
from services.vector.tasks import load_vector_file

# New
from services.vector.postgis_handler_enhanced import VectorToPostGISHandler
from services.vector.tasks_enhanced import load_vector_file
```

2. Add error handling:
```python
# Old
handler.upload_chunk(chunk, table_name)

# New
try:
    handler.upload_chunk(chunk, table_name)
    summary = handler.get_error_summary()
    if summary["warnings"]:
        logger.warning(f"Upload had {len(summary['warnings'])} warnings")
except PostGISError as e:
    logger.error(f"Upload failed: {e}")
    # Handle error appropriately
```

3. Use validation reports:
```python
result = validate_vector(params)
if "validation_report" in result:
    report = result["validation_report"]
    # Log issues for monitoring
    for warning in report["warnings"]:
        logger.warning(f"Validation warning: {warning}")
```

## Summary

The enhanced Vector ETL error handling provides:

- ✅ **Granular error tracking** at operation and row levels
- ✅ **Automatic retry logic** for transient failures
- ✅ **Detailed logging** with operation context
- ✅ **Recovery strategies** for common issues
- ✅ **Transaction safety** with automatic rollback
- ✅ **Error reporting** for monitoring and debugging

This ensures robust, production-ready vector data processing with comprehensive error visibility and recovery capabilities.