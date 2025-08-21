# Azure Geospatial ETL Pipeline - API Documentation

## Table of Contents
1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Base URL](#base-url)
4. [Common Headers](#common-headers)
5. [API Endpoints](#api-endpoints)
6. [Operations](#operations)
7. [Response Formats](#response-formats)
8. [Error Handling](#error-handling)
9. [Examples](#examples)

---

## Overview

The Azure Geospatial ETL Pipeline provides a RESTful API for processing geospatial data through Azure Functions. The system processes raster and vector data asynchronously using a queue-based architecture, supporting operations like Cloud Optimized GeoTIFF (COG) conversion, metadata extraction, reprojection, and more.

### Architecture
```
HTTP Request → API Gateway → Queue → Processing Service → Table Storage
                    ↓                         ↓
                Job Tracking            Blob Storage
```

### Key Features
- **Asynchronous Processing**: All operations are queued and processed asynchronously
- **Idempotent Operations**: Same parameters always produce the same job ID (SHA256 hash)
- **Comprehensive Metadata Extraction**: Extract TIFF tags, EXIF data, statistics, and geospatial properties
- **Raster Processing**: COG conversion, reprojection, validation
- **In-Memory Processing**: Efficient memory-based file processing
- **Managed Identity**: Secure authentication using Azure Managed Identity

---

## Authentication

### Function Key Authentication
All API requests require authentication using a function key passed in the headers:

```
x-functions-key: YOUR_FUNCTION_KEY
```

**Production Function Key**: `YOUR_FUNCTION_KEY_HERE`

---

## Base URL

**Production**: `https://rmhgeoapiqfn-h3dza4gyffbsbre7.eastus-01.azurewebsites.net`

**Local Development**: `http://localhost:7071`

---

## Common Headers

### Required Headers
```http
Content-Type: application/json
x-functions-key: YOUR_FUNCTION_KEY
```

---

## API Endpoints

### 1. Health Check
Check if the service is running and healthy.

**Endpoint**: `GET /api/health`

**Response**:
```json
{
    "status": "healthy",
    "timestamp": "2025-08-20T00:00:00.000000+00:00",
    "service": "Azure Geospatial ETL Pipeline",
    "version": "1.0.0"
}
```

### 2. Submit Job
Submit a new processing job to the queue.

**Endpoint**: `POST /api/jobs/{operation_type}`

**URL Parameters**:
- `operation_type`: The type of operation to perform (see [Operations](#operations))

**Request Body**:
```json
{
    "dataset_id": "container_name",
    "resource_id": "filename.tif",
    "version_id": "parameters",
    "system": true
}
```

**Parameters**:
- `dataset_id`: Source container name (when `system=true`) or logical dataset identifier
- `resource_id`: Filename of the resource to process
- `version_id`: Operation-specific parameters or version identifier
- `system`: Optional boolean flag for flexible parameter validation (default: false)

**Response**:
```json
{
    "job_id": "sha256_hash_of_parameters",
    "status": "queued",
    "message": "Job created and queued for processing",
    "is_duplicate": false,
    "dataset_id": "container_name",
    "resource_id": "filename.tif",
    "version_id": "parameters",
    "operation_type": "operation_type",
    "system": true,
    "log_list": ["log entries..."]
}
```

### 3. Get Job Status
Retrieve the status and results of a submitted job.

**Endpoint**: `GET /api/jobs/{job_id}`

**URL Parameters**:
- `job_id`: The SHA256 job identifier returned when submitting the job

**Response**:
```json
{
    "job_id": "job_id",
    "dataset_id": "container_name",
    "resource_id": "filename.tif",
    "version_id": "parameters",
    "operation_type": "operation_type",
    "system": true,
    "status": "completed|processing|queued|failed",
    "created_at": "2025-08-20T00:00:00.000000+00:00",
    "updated_at": "2025-08-20T00:00:00.000000+00:00",
    "error_message": null,
    "result_data": {
        // Operation-specific results
    },
    "request_parameters": {
        // Original request parameters
    }
}
```

---

## Operations

### Container Operations

#### 1. List Container (`list_container`)
List contents of a storage container with statistics.

**Parameters**:
- `dataset_id`: Container name (when `system=true`)
- `resource_id`: Prefix filter or "none" for all files
- `version_id`: Any value (not used)

**Example Request**:
```bash
curl -X POST https://rmhgeoapiqfn.../api/jobs/list_container \
  -H "Content-Type: application/json" \
  -H "x-functions-key: KEY" \
  -d '{
    "dataset_id": "rmhazuregeobronze",
    "resource_id": "none",
    "version_id": "v1",
    "system": true
  }'
```

**Response Data**:
```json
{
    "container": "rmhazuregeobronze",
    "file_count": 83,
    "total_size_gb": 71.23,
    "file_types": {
        "tif": 45,
        "json": 20,
        "shp": 10
    },
    "largest_files": [...],
    "newest_files": [...]
}
```

### Raster Processing Operations

#### 2. COG Conversion (`cog_conversion`)
Convert raster files to Cloud Optimized GeoTIFF format.

**Parameters**:
- `dataset_id`: Source container name
- `resource_id`: Input raster filename
- `version_id`: Processing parameters (format: "key1:value1,key2:value2")
  - `epsg`: Target EPSG code for reprojection (e.g., "epsg:3857")
  - `compress`: Compression type (lzw, deflate, jpeg, none)

**Example Request**:
```bash
curl -X POST https://rmhgeoapiqfn.../api/jobs/cog_conversion \
  -H "Content-Type: application/json" \
  -H "x-functions-key: KEY" \
  -d '{
    "dataset_id": "rmhazuregeobronze",
    "resource_id": "input.tif",
    "version_id": "epsg:3857,compress:lzw",
    "system": true
  }'
```

**Response Data**:
```json
{
    "status": "completed",
    "operation": "cog_conversion",
    "input": {
        "container": "rmhazuregeobronze",
        "raster": "input.tif",
        "epsg": 32637
    },
    "output": {
        "container": "rmhazuresilver",
        "raster": "input_abc123_cog.tif",
        "epsg": 3857,
        "format": "COG",
        "compression": "lzw",
        "valid_cog": true,
        "size_mb": 125.5
    }
}
```

#### 3. Reproject Raster (`reproject_raster`)
Reproject raster to a different coordinate reference system.

**Parameters**:
- `dataset_id`: Source container name
- `resource_id`: Input raster filename
- `version_id`: Target EPSG code (e.g., "epsg:4326")

**Example Request**:
```bash
curl -X POST https://rmhgeoapiqfn.../api/jobs/reproject_raster \
  -H "Content-Type: application/json" \
  -H "x-functions-key: KEY" \
  -d '{
    "dataset_id": "rmhazuregeobronze",
    "resource_id": "utm_raster.tif",
    "version_id": "epsg:4326",
    "system": true
  }'
```

#### 4. Raster Info (`raster_info`)
Get detailed information about a raster file.

**Parameters**:
- `dataset_id`: Container name
- `resource_id`: Raster filename
- `version_id`: Any value (not used)

**Example Request**:
```bash
curl -X POST https://rmhgeoapiqfn.../api/jobs/raster_info \
  -H "Content-Type: application/json" \
  -H "x-functions-key: KEY" \
  -d '{
    "dataset_id": "rmhazuregeobronze",
    "resource_id": "sample.tif",
    "version_id": "v1",
    "system": true
  }'
```

**Response Data**:
```json
{
    "filename": "sample.tif",
    "container": "rmhazuregeobronze",
    "dimensions": {
        "width": 5748,
        "height": 4156,
        "bands": 4
    },
    "crs": {
        "epsg": 32637,
        "wkt": "PROJCS[...]",
        "proj4": "+proj=utm +zone=37..."
    },
    "bounds": {
        "native": {
            "left": 221109.6,
            "bottom": 3533512.8,
            "right": 224558.4,
            "top": 3536006.4
        },
        "geographic": {
            "west": 36.050,
            "south": 31.903,
            "east": 36.087,
            "north": 31.926
        }
    },
    "pixel_size": {
        "x": 0.6,
        "y": 0.6
    },
    "dtypes": ["uint16", "uint16", "uint16", "uint16"],
    "compression": "lzw"
}
```

#### 5. Validate Raster (`validate_raster`)
Validate raster file and check if it's a valid COG.

**Parameters**:
- `dataset_id`: Container name
- `resource_id`: Raster filename
- `version_id`: Any value (not used)

### Metadata Extraction Operations

#### 6. Extract Comprehensive Metadata (`extract_metadata`)
Extract all available metadata from a geospatial file.

**Parameters**:
- `dataset_id`: Container name
- `resource_id`: Filename
- `version_id`: Any value (not used)

**Example Request**:
```bash
curl -X POST https://rmhgeoapiqfn.../api/jobs/extract_metadata \
  -H "Content-Type: application/json" \
  -H "x-functions-key: KEY" \
  -d '{
    "dataset_id": "rmhazuregeobronze",
    "resource_id": "sample.tif",
    "version_id": "comprehensive",
    "system": true
  }'
```

**Response Data**:
```json
{
    "status": "completed",
    "operation": "extract_metadata",
    "metadata": {
        "filename": "sample.tif",
        "container": "rmhazuregeobronze",
        "file_properties": {
            "size_bytes": 124715444,
            "size_mb": 118.94,
            "extension": "tif",
            "extraction_timestamp": "2025-08-20T00:00:00"
        },
        "checksums": {
            "md5": "f4d7a5058830edabbd9c428acda28fdc",
            "sha256": "87426b5743cdbf36d51e7318c2fc487b...",
            "sha1": "5b0e921d318ac9272b6ef176841da544..."
        },
        "raster": {
            "driver": "GTiff",
            "dimensions": {...},
            "crs": {...},
            "bounds": {...},
            "bands": [...]
        },
        "tiff_tags": {...},
        "exif": {...},
        "gps": {...}
    }
}
```

#### 7. Extract TIFF Tags (`extract_tiff_tags`)
Extract TIFF and GeoTIFF specific tags.

**Parameters**:
- `dataset_id`: Container name
- `resource_id`: TIFF filename
- `version_id`: Any value (not used)

#### 8. Extract EXIF Data (`extract_exif`)
Extract EXIF and GPS metadata from image files.

**Parameters**:
- `dataset_id`: Container name
- `resource_id`: Image filename
- `version_id`: Any value (not used)

#### 9. Extract Statistics (`extract_statistics`)
Calculate statistical information from raster bands.

**Parameters**:
- `dataset_id`: Container name
- `resource_id`: Raster filename
- `version_id`: Any value (not used)

**Response Data**:
```json
{
    "statistics": {
        "filename": "sample.tif",
        "bands": [
            {
                "band": 1,
                "min": 1.0,
                "max": 1778.0,
                "mean": 441.7,
                "std": 155.69,
                "median": 461.0,
                "valid_pixels": 23888688,
                "percentiles": {
                    "p25": 350.0,
                    "p50": 461.0,
                    "p75": 525.0,
                    "p90": 615.0,
                    "p95": 675.0,
                    "p99": 825.0
                },
                "histogram": {
                    "counts": [...],
                    "bin_edges": [...]
                }
            }
        ]
    }
}
```

### Test Operations

#### 10. Hello World (`hello_world`)
Test operation that echoes parameters.

**Parameters**:
- `dataset_id`: Any test value
- `resource_id`: Any test value
- `version_id`: Any test value

---

## Response Formats

### Job Status Values
- `pending`: Job created but not yet queued
- `queued`: Job in queue waiting for processing
- `processing`: Job currently being processed
- `completed`: Job completed successfully
- `failed`: Job failed with error

### Success Response Structure
```json
{
    "job_id": "unique_sha256_hash",
    "status": "completed",
    "result_data": {
        // Operation-specific results
    },
    "created_at": "ISO 8601 timestamp",
    "updated_at": "ISO 8601 timestamp"
}
```

### Error Response Structure
```json
{
    "job_id": "unique_sha256_hash",
    "status": "failed",
    "error_message": "Detailed error description",
    "created_at": "ISO 8601 timestamp",
    "updated_at": "ISO 8601 timestamp"
}
```

---

## Error Handling

### HTTP Status Codes
- `200 OK`: Successful request
- `400 Bad Request`: Invalid parameters or request format
- `401 Unauthorized`: Missing or invalid function key
- `404 Not Found`: Job or resource not found
- `500 Internal Server Error`: Server-side processing error

### Common Error Messages
1. **Invalid Operation Type**: "Unsupported operation: {operation_type}"
2. **Missing Parameters**: "Missing required parameter: {parameter}"
3. **File Not Found**: "Input file not found: {filename} in {container}"
4. **Processing Error**: "Error processing job: {error_details}"
5. **Invalid CRS**: "No CRS found in {filename}"

---

## Examples

### Complete Workflow Example

#### 1. Submit a COG Conversion Job
```bash
# Submit job
curl -X POST https://rmhgeoapiqfn-h3dza4gyffbsbre7.eastus-01.azurewebsites.net/api/jobs/cog_conversion \
  -H "Content-Type: application/json" \
  -H "x-functions-key: YOUR_FUNCTION_KEY_HERE" \
  -d '{
    "dataset_id": "rmhazuregeobronze",
    "resource_id": "05APR13082706.tif",
    "version_id": "epsg:3857,compress:lzw",
    "system": true
  }'

# Response with job_id
{
    "job_id": "abc123def456...",
    "status": "queued",
    ...
}
```

#### 2. Check Job Status
```bash
# Check status using job_id
curl https://rmhgeoapiqfn-h3dza4gyffbsbre7.eastus-01.azurewebsites.net/api/jobs/abc123def456 \
  -H "x-functions-key: YOUR_FUNCTION_KEY_HERE"

# Response when completed
{
    "job_id": "abc123def456...",
    "status": "completed",
    "result_data": {
        "output": {
            "container": "rmhazuresilver",
            "raster": "05APR13082706_xyz789_cog.tif",
            "size_mb": 125.5
        }
    }
}
```

### Python Client Example

```python
import requests
import json
import time

class GeospatialETLClient:
    def __init__(self, base_url, function_key):
        self.base_url = base_url
        self.headers = {
            "Content-Type": "application/json",
            "x-functions-key": function_key
        }
    
    def submit_job(self, operation_type, dataset_id, resource_id, version_id="v1", system=True):
        """Submit a processing job"""
        url = f"{self.base_url}/api/jobs/{operation_type}"
        payload = {
            "dataset_id": dataset_id,
            "resource_id": resource_id,
            "version_id": version_id,
            "system": system
        }
        
        response = requests.post(url, headers=self.headers, json=payload)
        return response.json()
    
    def get_job_status(self, job_id):
        """Get job status and results"""
        url = f"{self.base_url}/api/jobs/{job_id}"
        response = requests.get(url, headers=self.headers)
        return response.json()
    
    def wait_for_completion(self, job_id, timeout=300, poll_interval=5):
        """Wait for job to complete"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            status = self.get_job_status(job_id)
            
            if status["status"] == "completed":
                return status
            elif status["status"] == "failed":
                raise Exception(f"Job failed: {status.get('error_message')}")
            
            time.sleep(poll_interval)
        
        raise TimeoutError(f"Job {job_id} did not complete within {timeout} seconds")

# Usage
client = GeospatialETLClient(
    base_url="https://rmhgeoapiqfn-h3dza4gyffbsbre7.eastus-01.azurewebsites.net",
    function_key="YOUR_FUNCTION_KEY_HERE"
)

# Submit COG conversion
job = client.submit_job(
    operation_type="cog_conversion",
    dataset_id="rmhazuregeobronze",
    resource_id="input.tif",
    version_id="epsg:3857"
)

print(f"Job submitted: {job['job_id']}")

# Wait for completion
result = client.wait_for_completion(job['job_id'])
print(f"Job completed: {json.dumps(result['result_data'], indent=2)}")
```

### cURL Script Example

```bash
#!/bin/bash

# Configuration
BASE_URL="https://rmhgeoapiqfn-h3dza4gyffbsbre7.eastus-01.azurewebsites.net"
API_KEY="YOUR_FUNCTION_KEY_HERE"

# Function to submit job
submit_job() {
    local operation=$1
    local dataset=$2
    local resource=$3
    local version=$4
    
    curl -s -X POST "${BASE_URL}/api/jobs/${operation}" \
        -H "Content-Type: application/json" \
        -H "x-functions-key: ${API_KEY}" \
        -d "{
            \"dataset_id\": \"${dataset}\",
            \"resource_id\": \"${resource}\",
            \"version_id\": \"${version}\",
            \"system\": true
        }" | jq -r '.job_id'
}

# Function to check status
check_status() {
    local job_id=$1
    
    curl -s "${BASE_URL}/api/jobs/${job_id}" \
        -H "x-functions-key: ${API_KEY}" | jq -r '.status'
}

# Submit job
JOB_ID=$(submit_job "extract_metadata" "rmhazuregeobronze" "sample.tif" "v1")
echo "Job submitted: ${JOB_ID}"

# Wait for completion
while true; do
    STATUS=$(check_status "${JOB_ID}")
    echo "Status: ${STATUS}"
    
    if [ "${STATUS}" = "completed" ] || [ "${STATUS}" = "failed" ]; then
        break
    fi
    
    sleep 5
done

# Get full results
curl -s "${BASE_URL}/api/jobs/${JOB_ID}" \
    -H "x-functions-key: ${API_KEY}" | jq '.'
```

---

## Rate Limits and Quotas

### Azure Functions Limits
- **Concurrent Executions**: 200 (Consumption plan)
- **Max Request Size**: 100 MB
- **Timeout**: 5 minutes (default), configurable up to 10 minutes
- **Queue Message Size**: 64 KB (Base64 encoded)

### Storage Limits
- **Max Blob Size**: 5 TB
- **Container Name**: 3-63 characters, lowercase
- **Blob Name**: 1-1024 characters

### Best Practices
1. **Batch Operations**: Submit multiple jobs in parallel for better throughput
2. **Polling Interval**: Use 5-10 second intervals when checking job status
3. **Idempotency**: Leverage job ID determinism for retry logic
4. **File Naming**: Use descriptive names with timestamps for output files
5. **Error Handling**: Implement exponential backoff for retries

---

## Monitoring and Logging

### Application Insights
All operations are logged to Application Insights with the following custom dimensions:
- `job_id`: Unique job identifier
- `operation_type`: Type of operation
- `status`: Current job status
- `dataset_id`: Dataset/container identifier
- `resource_id`: Resource filename

### Log Queries
```kusto
// Get all failed jobs in last 24 hours
traces
| where timestamp > ago(24h)
| where customDimensions.status == "failed"
| project timestamp, job_id=customDimensions.job_id, error=message

// Average processing time by operation
traces
| where timestamp > ago(7d)
| where customDimensions.status == "completed"
| summarize avg_duration=avg(duration) by operation=customDimensions.operation_type
```

---

## Changelog

### Version 1.0.0 (2025-08-20)
- Initial release with core functionality
- COG conversion and reprojection operations
- Comprehensive metadata extraction
- TIFF tag and EXIF data extraction
- Statistical analysis for raster bands
- Container listing with statistics
- Queue-based asynchronous processing
- Idempotent job submission
- Azure Managed Identity support

---

## Support

For issues, questions, or feature requests:
- **GitHub Issues**: https://github.com/anthropics/claude-code/issues
- **Documentation**: https://docs.anthropic.com/en/docs/claude-code
- **Azure Status**: https://status.azure.com

---

## License

This API is provided as-is for geospatial data processing within the Azure ecosystem. See LICENSE file for details.