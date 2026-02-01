# Quick Start Guide

> **Navigation**: **Quick Start** | [Platform API](../api-reference/PLATFORM_API.md) | [Health](../api-reference/HEALTH.md) | [Errors](../api-reference/ERRORS.md) | [Glossary](GLOSSARY.md)

**Last Updated**: 01 FEB 2026
**Status**: Reference Documentation
**Purpose**: Get new developers running their first job in 5 minutes
**Audience**: New team members and developers unfamiliar with the system

---

## Prerequisites

Before starting, verify you have:

- [ ] Access to Azure subscription
- [ ] Azure CLI installed (`az --version`)
- [ ] curl or similar HTTP client
- [ ] Function App URL (see Base URL below)

---

## Base URL

All API requests use this base URL:

```
https://<platform-api-url>
```

---

## Step 1: Verify System Health (30 seconds)

Check that the system is operational:

```bash
curl https://<platform-api-url>/api/health
```

**Expected response**:
```json
{
  "status": "healthy",
  "timestamp": "2026-01-15T...",
  "version": "0.8.6.2"
}
```

If you receive an error, contact the platform team before proceeding.

---

## Step 2: Submit Your First Job (1 minute)

Submit a simple "hello world" job to verify the job processing system:

```bash
curl -X POST \
  https://<platform-api-url>/api/jobs/submit/hello_world \
  -H 'Content-Type: application/json' \
  -d '{"message": "My first job"}'
```

**Expected response**:
```json
{
  "job_id": "abc123...",
  "status": "created",
  "job_type": "hello_world",
  "message": "Job created and queued for processing"
}
```

**Save the `job_id` value** - you will need it for the next step.

---

## Step 3: Check Job Status (30 seconds)

Replace `{JOB_ID}` with the job_id from Step 2:

```bash
curl https://<platform-api-url>/api/jobs/status/{JOB_ID}
```

**Expected response** (after a few seconds):
```json
{
  "jobId": "abc123...",
  "jobType": "hello_world",
  "status": "completed",
  "stage": 2,
  "totalStages": 2,
  "resultData": {
    "greetings": ["Hello: My first job"],
    "total_greetings": 1
  }
}
```

**Congratulations** - you have successfully submitted and completed your first job.

---

## Step 4: View Available Collections (1 minute)

View vector data collections available through the OGC Features API:

```bash
curl https://<platform-api-url>/api/features/collections
```

This returns a list of all PostGIS tables available for querying.

---

## Step 5: Query Vector Features (1 minute)

If collections exist, query features from a collection:

```bash
curl "https://<platform-api-url>/api/features/collections/{COLLECTION_NAME}/items?limit=10"
```

Replace `{COLLECTION_NAME}` with a collection name from Step 4.

---

## Common Commands Reference

### Platform API (Recommended for DDH Integration)

The Platform API provides validation, version lineage tracking, and dry_run support:

```bash
# Validate parameters without creating job (dry_run)
curl -X POST ".../api/platform/submit?dry_run=true" \
  -H 'Content-Type: application/json' \
  -d '{
    "platform_id": "ddh",
    "dataset_id": "floods",
    "resource_id": "jakarta",
    "version_id": "v1.0",
    "job_type": "process_vector",
    "blob_name": "data.geojson",
    "file_extension": "geojson",
    "table_name": "flood_jakarta_v1"
  }'

# Submit job (creates version lineage record)
curl -X POST ".../api/platform/submit" \
  -H 'Content-Type: application/json' \
  -d '{...same payload without dry_run...}'
```

### Direct Job Submission (Power Users)

For direct access without platform tracking:

```bash
# Submit any job type
POST /api/jobs/submit/{job_type}

# Example: hello_world
curl -X POST .../api/jobs/submit/hello_world \
  -H 'Content-Type: application/json' \
  -d '{"message": "test"}'

# Example: process_vector
curl -X POST .../api/jobs/submit/process_vector \
  -H 'Content-Type: application/json' \
  -d '{
    "blob_name": "data.geojson",
    "file_extension": "geojson",
    "table_name": "my_table"
  }'
```

### Job Status

```bash
# Check single job status
GET /api/jobs/status/{job_id}

# List recent jobs
GET /api/dbadmin/jobs?limit=10&hours=24
```

### OGC Features API

```bash
# List collections
GET /api/features/collections

# Get collection metadata
GET /api/features/collections/{collection}/

# Query features
GET /api/features/collections/{collection}/items?limit=100

# Query with bounding box
GET /api/features/collections/{collection}/items?bbox=-74,40,-73,41&limit=50
```

### STAC API

```bash
# List STAC collections
GET /api/stac/collections

# Search STAC items
POST /api/stac/search
```

### System Health

```bash
# Health check
GET /api/health

# Readiness probe
GET /api/readyz

# Database statistics
GET /api/dbadmin/stats
```

---

## Job Types Quick Reference

| Job Type | Purpose | Processing | Required Parameters |
|----------|---------|------------|---------------------|
| `hello_world` | Test system | Function App | `message` (optional) |
| `process_vector` | Load vector data to PostGIS | Docker Worker | `blob_name`, `file_extension`, `table_name` |
| `process_raster` | Convert raster to COG | Docker Worker | `blob_name`, `container_name` |
| `process_raster_collection` | Process multiple rasters | Docker Worker | `blob_list`, `collection_id`, `container_name` |

**Note**: Heavy processing jobs (vector ETL, raster processing) are routed to the Docker Worker for efficient memory management.

For complete parameter documentation, see [Platform API](../api-reference/PLATFORM_API.md).

---

## Typical Workflows

### Workflow 1: Ingest Vector Data

1. Upload file to Bronze container (Azure Storage Explorer or `az storage blob upload`)
2. Submit `process_vector` job with file details
3. Check job status until completed
4. Query data via OGC Features API

### Workflow 2: Process Raster Data

1. Upload GeoTIFF to Bronze container
2. Submit `process_raster` job
3. Check job status until completed
4. Access COG via TiTiler URLs in job result

### Workflow 3: Create Raster Collection

1. Upload multiple GeoTIFF files to Bronze container
2. Submit `process_raster_collection` job with blob_list
3. Check job status until completed
4. Access collection via STAC API and TiTiler

### Workflow 4: Version Management (DDH Integration)

1. Use `dry_run=true` to check version lineage state
2. Submit with `previous_version_id` if updating existing data
3. Platform tracks version history automatically

---

## Job Status Values

| Status | Meaning |
|--------|---------|
| `pending` | Job received, waiting for processing |
| `processing` | Job is currently executing |
| `completed` | Job finished successfully |
| `failed` | Job encountered an error |
| `completed_with_errors` | Job finished but some tasks failed |

---

## Getting Help

### Documentation

- **[Platform API](../api-reference/PLATFORM_API.md)** - Platform API reference (submit, validate, version lineage)
- **[Glossary](GLOSSARY.md)** - Terminology and acronym definitions
- **[Technical Overview](../architecture/TECHNICAL_OVERVIEW.md)** - Architecture and technology stack
- **[Service Layer](../architecture/SERVICE_LAYER.md)** - Data access APIs (TiTiler, TiPG, STAC)
- **[Errors](../api-reference/ERRORS.md)** - Error codes and troubleshooting

### Support

For issues or questions:
1. Check the [Health endpoint](../api-reference/HEALTH.md) for system status
2. Review error messages in job status response
3. Use `dry_run=true` to validate parameters before submission
4. Contact the platform team

---

## Next Steps

After completing this quick start:

1. **Read the API Reference**: [Platform API](../api-reference/PLATFORM_API.md) for complete parameter documentation
2. **Understand the Architecture**: [Technical Overview](../architecture/TECHNICAL_OVERVIEW.md) for system design
3. **Learn the Terminology**: [Glossary](GLOSSARY.md) for definitions
4. **Explore the Service Layer**: [Service Layer](../architecture/SERVICE_LAYER.md) for TiTiler, TiPG, STAC APIs
5. **Try Real Data**: Upload your own files and process them

---

**Last Updated**: 01 FEB 2026
