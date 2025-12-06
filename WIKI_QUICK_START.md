# Quick Start Guide

**Date**: 24 NOV 2025
**Status**: Reference Documentation
**Wiki**: Azure DevOps Wiki - Getting started guide
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
https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net
```

---

## Step 1: Verify System Health (30 seconds)

Check that the system is operational:

```bash
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health
```

**Expected response**:
```json
{
  "status": "healthy",
  "timestamp": "2025-11-24T...",
  "version": "..."
}
```

If you receive an error, contact the platform team before proceeding.

---

## Step 2: Submit Your First Job (1 minute)

Submit a simple "hello world" job to verify the job processing system:

```bash
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
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
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
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
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections
```

This returns a list of all PostGIS tables available for querying.

---

## Step 5: Query Vector Features (1 minute)

If collections exist, query features from a collection:

```bash
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections/{COLLECTION_NAME}/items?limit=10"
```

Replace `{COLLECTION_NAME}` with a collection name from Step 4.

---

## Common Commands Reference

### Job Submission

```bash
# Submit any job type
POST /api/jobs/submit/{job_type}

# Example: hello_world
curl -X POST .../api/jobs/submit/hello_world \
  -H 'Content-Type: application/json' \
  -d '{"message": "test"}'

# Example: process_vector (idempotent)
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

# Database statistics
GET /api/dbadmin/stats
```

---

## Job Types Quick Reference

| Job Type | Purpose | Required Parameters |
|----------|---------|---------------------|
| `hello_world` | Test system | `message` (optional) |
| `process_vector` | Load vector data to PostGIS | `blob_name`, `file_extension`, `table_name` |
| `process_raster_v2` | Convert raster to COG (recommended) | `blob_name`, `container_name` |
| `process_raster` | Convert raster to COG (legacy) | `blob_name`, `container_name` |
| `process_raster_collection` | Process multiple rasters | `blob_list`, `collection_id`, `container_name` |

For complete parameter documentation, see [WIKI_API_JOB_SUBMISSION.md](WIKI_API_JOB_SUBMISSION.md).

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

---

## Job Status Values

| Status | Meaning |
|--------|---------|
| `queued` | Job received, waiting for processing |
| `processing` | Job is currently executing |
| `completed` | Job finished successfully |
| `failed` | Job encountered an error |
| `completed_with_errors` | Job finished but some tasks failed |

---

## Getting Help

### Documentation

- **[WIKI_API_JOB_SUBMISSION.md](WIKI_API_JOB_SUBMISSION.md)** - Complete API reference for all job types
- **[WIKI_API_GLOSSARY.md](WIKI_API_GLOSSARY.md)** - Terminology and acronym definitions
- **[WIKI_TECHNICAL_OVERVIEW.md](WIKI_TECHNICAL_OVERVIEW.md)** - Architecture and technology stack
- **[WIKI_API_SERVICE_BUS.md](WIKI_API_SERVICE_BUS.md)** - Service Bus configuration

### Workflow Trace Documentation

- **[WIKI_API_INGEST_VECTOR_TRACETHROUGH.md](WIKI_API_INGEST_VECTOR_TRACETHROUGH.md)** - Vector ingestion workflow details
- **[WIKI_API_PROCESS_RASTER_TRACETHROUGH.md](WIKI_API_PROCESS_RASTER_TRACETHROUGH.md)** - Raster processing workflow details
- **[WIKI_API_PROCESS_RASTER_COLLECTION_TRACETHROUGH.md](WIKI_API_PROCESS_RASTER_COLLECTION_TRACETHROUGH.md)** - Collection processing workflow details

### Support

For issues or questions:
1. Check the relevant workflow trace document
2. Review error messages in job status response
3. Contact the platform team

---

## Next Steps

After completing this quick start:

1. **Read the API Reference**: [WIKI_API_JOB_SUBMISSION.md](WIKI_API_JOB_SUBMISSION.md) for complete parameter documentation
2. **Understand the Architecture**: [WIKI_TECHNICAL_OVERVIEW.md](WIKI_TECHNICAL_OVERVIEW.md) for system design
3. **Learn the Terminology**: [WIKI_API_GLOSSARY.md](WIKI_API_GLOSSARY.md) for definitions
4. **Try Real Data**: Upload your own files and process them

---

**Last Updated**: 03 DEC 2025
