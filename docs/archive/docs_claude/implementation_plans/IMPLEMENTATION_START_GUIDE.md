# Application Layer Implementation - Getting Started

**Date**: 25 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Step-by-step guide to begin implementing the platform application layer

## Overview

We'll build the platform layer incrementally, starting with the simplest possible flow and adding features progressively. The goal is to have a working end-to-end demo within 2-3 days.

## Day 1: Foundation (4-6 hours)

### Step 1: Database Setup (30 minutes)

First, create the platform schema in PostgreSQL:

```sql
-- File: infrastructure/sql/platform_schema.sql

-- Create platform schema
CREATE SCHEMA IF NOT EXISTS platform;

-- Platform requests table (simplified for MVP)
CREATE TABLE IF NOT EXISTS platform.requests (
    request_id VARCHAR(32) PRIMARY KEY,
    client_id VARCHAR(50) NOT NULL DEFAULT 'ddh_v1',

    -- DDH identifiers
    dataset_id VARCHAR(255),
    resource_id VARCHAR(255),
    version_id VARCHAR(50),

    -- Processing
    request_type VARCHAR(50) NOT NULL,  -- 'vector', 'raster'
    source_path TEXT NOT NULL,
    processing_config JSONB DEFAULT '{}',

    -- Status
    status VARCHAR(20) DEFAULT 'pending',
    status_message TEXT,

    -- Tracking
    job_ids JSONB DEFAULT '[]',

    -- Results
    endpoints JSONB,
    stac_metadata JSONB,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    -- Unique constraint for idempotency
    CONSTRAINT unique_dataset_version UNIQUE(dataset_id, resource_id, version_id)
);

-- Index for status queries
CREATE INDEX idx_platform_status ON platform.requests(status);
CREATE INDEX idx_platform_created ON platform.requests(created_at);
```

Deploy this schema:

```bash
# Run via psql or your database tool
psql -h rmhpgflex.postgres.database.azure.com -U {db_superuser} -d geopgflex -f infrastructure/sql/platform_schema.sql
```

### Step 2: Create Platform Models (45 minutes)

```python
# File: platform/__init__.py
"""Platform service layer for external applications."""

# File: platform/models.py
"""Platform data models."""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

class RequestStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class PlatformRequest(BaseModel):
    """Request from DDH to process data."""
    dataset_id: str
    resource_id: str
    version_id: str
    request_type: str  # 'vector' or 'raster' for MVP
    source_path: str
    processing_config: Dict[str, Any] = Field(default_factory=dict)
    callback_url: Optional[str] = None

class PlatformResponse(BaseModel):
    """Response to DDH with tracking info."""
    request_id: str
    status: str = "accepted"
    status_url: str
    message: str = "Request accepted for processing"

class StatusResponse(BaseModel):
    """Status check response."""
    request_id: str
    status: RequestStatus
    message: Optional[str] = None

    # When completed
    endpoints: Optional[Dict[str, str]] = None
    stac_metadata: Optional[Dict[str, Any]] = None
```

### Step 3: Create Platform Repository (1 hour)

```python
# File: platform/repository.py
"""Platform request repository for database operations."""

import hashlib
import json
from typing import Optional, Dict, Any, List
from datetime import datetime
import psycopg
from psycopg.rows import dict_row

from platform.models import RequestStatus
from config import get_config

class PlatformRepository:
    """Manages platform requests in PostgreSQL."""

    def __init__(self):
        self.config = get_config()
        self.conn_string = (
            f"host={self.config.postgis_host} "
            f"dbname={self.config.postgis_database} "
            f"user={self.config.postgis_user} "
            f"password={self.config.postgis_password} "
            f"port={self.config.postgis_port}"
        )

    def create_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new platform request."""
        with psycopg.connect(self.conn_string, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO platform.requests (
                        request_id, dataset_id, resource_id, version_id,
                        request_type, source_path, processing_config, status
                    ) VALUES (
                        %(request_id)s, %(dataset_id)s, %(resource_id)s, %(version_id)s,
                        %(request_type)s, %(source_path)s, %(processing_config)s, 'pending'
                    )
                    ON CONFLICT (dataset_id, resource_id, version_id)
                    DO UPDATE SET request_id = EXCLUDED.request_id
                    RETURNING *
                """, {
                    **request_data,
                    'processing_config': json.dumps(request_data.get('processing_config', {}))
                })
                return cur.fetchone()

    def get_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Get request by ID."""
        with psycopg.connect(self.conn_string, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM platform.requests WHERE request_id = %s",
                    (request_id,)
                )
                return cur.fetchone()

    def update_status(self, request_id: str, status: str, message: str = None):
        """Update request status."""
        with psycopg.connect(self.conn_string) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE platform.requests
                    SET status = %s, status_message = %s
                    WHERE request_id = %s
                """, (status, message, request_id))

    def add_job_id(self, request_id: str, job_id: str):
        """Add a job ID to the request's job list."""
        with psycopg.connect(self.conn_string) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE platform.requests
                    SET job_ids = job_ids || %s::jsonb,
                        status = 'processing'
                    WHERE request_id = %s
                """, (json.dumps([job_id]), request_id))
```

### Step 4: Create Platform Router (1.5 hours)

```python
# File: platform/router.py
"""Platform request router - maps requests to jobs."""

import hashlib
import json
from typing import Dict, Any, Optional
from datetime import datetime

from platform.models import PlatformRequest, PlatformResponse
from platform.repository import PlatformRepository
from util_logger import LoggerFactory

logger = LoggerFactory.get_logger("platform_router")

class PlatformRouter:
    """Routes platform requests to CoreMachine jobs."""

    # Simple mapping for MVP
    JOB_MAPPING = {
        "vector": ["ingest_vector"],  # Start with single job
        "raster": ["process_raster"]  # Start with single job
    }

    def __init__(self):
        self.repository = PlatformRepository()

    def process_request(self, request: PlatformRequest) -> PlatformResponse:
        """Process a platform request from DDH."""

        # Generate unique request ID
        request_id = self._generate_request_id(request)
        logger.info(f"Processing platform request: {request_id}")

        # Check for existing request (idempotency)
        existing = self.repository.get_request(request_id)
        if existing:
            logger.info(f"Request {request_id} already exists with status: {existing['status']}")
            return PlatformResponse(
                request_id=request_id,
                status=existing['status'],
                status_url=f"/platform/status/{request_id}",
                message="Request already exists"
            )

        # Create platform request record
        request_record = self.repository.create_request({
            "request_id": request_id,
            "dataset_id": request.dataset_id,
            "resource_id": request.resource_id,
            "version_id": request.version_id,
            "request_type": request.request_type,
            "source_path": request.source_path,
            "processing_config": request.processing_config or {}
        })

        # Submit first job (MVP: single job per request)
        job_type = self.JOB_MAPPING[request.request_type][0]
        self._submit_job(request_id, job_type, request)

        return PlatformResponse(
            request_id=request_id,
            status="accepted",
            status_url=f"/platform/status/{request_id}",
            message=f"Processing {request.request_type} dataset"
        )

    def _generate_request_id(self, request: PlatformRequest) -> str:
        """Generate deterministic request ID."""
        unique_string = f"{request.dataset_id}:{request.resource_id}:{request.version_id}"
        return hashlib.sha256(unique_string.encode()).hexdigest()[:16]

    def _submit_job(self, request_id: str, job_type: str, request: PlatformRequest):
        """Submit job to CoreMachine."""
        # Import here to avoid circular dependency
        from triggers.submit_job import submit_job_trigger

        # Build job parameters based on type
        job_params = self._build_job_params(job_type, request)

        # Add platform tracking
        job_params["_platform_request_id"] = request_id

        # Submit job using existing infrastructure
        try:
            job_response = submit_job_trigger.submit_job(job_type, job_params)
            job_id = job_response.get("job_id")

            # Track job ID
            self.repository.add_job_id(request_id, job_id)
            logger.info(f"Submitted job {job_id} for platform request {request_id}")

        except Exception as e:
            logger.error(f"Failed to submit job for {request_id}: {e}")
            self.repository.update_status(request_id, "failed", str(e))

    def _build_job_params(self, job_type: str, request: PlatformRequest) -> Dict[str, Any]:
        """Build job parameters for CoreMachine."""

        if job_type == "ingest_vector":
            return {
                "source_path": request.source_path,
                "table_name": f"{request.dataset_id}_{request.resource_id}_{request.version_id}",
                "schema": "geo",
                **request.processing_config
            }

        elif job_type == "process_raster":
            return {
                "source_path": request.source_path,
                "output_path": f"silver/processed/{request.dataset_id}/{request.resource_id}/{request.version_id}",
                **request.processing_config
            }

        return {}

# Create singleton instance
platform_router = PlatformRouter()
```

### Step 5: Add HTTP Endpoints (1 hour)

```python
# File: Add to function_app.py

# Import platform components
from platform.models import PlatformRequest, StatusResponse
from platform.router import platform_router
from platform.repository import PlatformRepository

platform_repo = PlatformRepository()

@app.route(route="platform/submit", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def platform_submit(req: func.HttpRequest) -> func.HttpResponse:
    """
    Submit a platform processing request (DDH entry point).

    POST /platform/submit
    {
        "dataset_id": "census_2020",
        "resource_id": "blocks",
        "version_id": "v1.0",
        "request_type": "vector",
        "source_path": "bronze/uploads/census_blocks.gpkg"
    }
    """
    try:
        # Parse request
        request_data = req.get_json()
        platform_request = PlatformRequest(**request_data)

        # Process through router
        response = platform_router.process_request(platform_request)

        # Return 202 Accepted
        return func.HttpResponse(
            response.model_dump_json(),
            status_code=202,
            mimetype="application/json",
            headers={
                "Location": response.status_url
            }
        )

    except Exception as e:
        logger.error(f"Platform submit error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=400,
            mimetype="application/json"
        )

@app.route(route="platform/status/{request_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def platform_status(req: func.HttpRequest) -> func.HttpResponse:
    """
    Check platform request status.

    GET /platform/status/{request_id}
    """
    request_id = req.route_params.get('request_id')

    # Get request from database
    request = platform_repo.get_request(request_id)

    if not request:
        return func.HttpResponse(
            json.dumps({"error": "Request not found"}),
            status_code=404,
            mimetype="application/json"
        )

    # Build response
    response = StatusResponse(
        request_id=request['request_id'],
        status=request['status'],
        message=request.get('status_message')
    )

    # Add results if completed
    if request['status'] == 'completed':
        response.endpoints = request.get('endpoints')
        response.stac_metadata = request.get('stac_metadata')

    return func.HttpResponse(
        response.model_dump_json(),
        mimetype="application/json"
    )
```

## Day 2: Integration (4-6 hours)

### Step 6: Job Completion Handler (1.5 hours)

```python
# File: platform/completion.py
"""Handle job completion for platform requests."""

from typing import Dict, Any
from datetime import datetime
import json

from platform.repository import PlatformRepository
from util_logger import LoggerFactory

logger = LoggerFactory.get_logger("platform_completion")

class PlatformCompletionHandler:
    """Handles job completion for platform requests."""

    def __init__(self):
        self.repository = PlatformRepository()

    def handle_job_completion(self, job_id: str, job_result: Dict[str, Any]):
        """Called when a CoreMachine job completes."""

        # Find platform request by job ID
        request = self._find_request_by_job(job_id)
        if not request:
            return  # Not a platform job

        logger.info(f"Handling completion for platform request {request['request_id']}")

        # For MVP, single job = request complete
        if job_result.get('success'):
            self._complete_request(request, job_result)
        else:
            self._fail_request(request, job_result.get('error', 'Job failed'))

    def _complete_request(self, request: Dict[str, Any], job_result: Dict[str, Any]):
        """Mark request as completed."""

        # Generate endpoints based on type
        endpoints = self._generate_endpoints(request)

        # Extract STAC metadata if available
        stac_metadata = job_result.get('stac_metadata', {})

        # Update request
        with psycopg.connect(self.repository.conn_string) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE platform.requests
                    SET status = 'completed',
                        endpoints = %s::jsonb,
                        stac_metadata = %s::jsonb,
                        completed_at = NOW()
                    WHERE request_id = %s
                """, (
                    json.dumps(endpoints),
                    json.dumps(stac_metadata),
                    request['request_id']
                ))

        logger.info(f"Platform request {request['request_id']} completed successfully")

    def _generate_endpoints(self, request: Dict[str, Any]) -> Dict[str, str]:
        """Generate API endpoints for completed request."""

        base_path = f"/data/{request['dataset_id']}/{request['resource_id']}/{request['version_id']}"

        if request['request_type'] == 'vector':
            return {
                "features": f"{base_path}/ogc/features",
                "tiles": f"{base_path}/tiles/{{z}}/{{x}}/{{y}}",
                "download": f"{base_path}/download"
            }
        elif request['request_type'] == 'raster':
            return {
                "cog": f"{base_path}/cog",
                "tiles": f"{base_path}/cog/tiles/{{z}}/{{x}}/{{y}}",
                "metadata": f"{base_path}/metadata"
            }

        return {}

# Create singleton
platform_completion = PlatformCompletionHandler()
```

### Step 7: Wire Up Completion (30 minutes)

Add to existing job completion flow:

```python
# Modify core/machine.py or wherever job completion is handled

# In the job completion method:
def _handle_job_completion(self, job_id: str, result: Dict[str, Any]):
    """Handle job completion."""

    # Existing completion logic...

    # Check if this is a platform job
    if result.get('_platform_request_id'):
        from platform.completion import platform_completion
        platform_completion.handle_job_completion(job_id, result)
```

## Day 3: Testing (2-3 hours)

### Step 8: End-to-End Test Script

```python
# File: test_platform.py
"""Test platform layer end-to-end."""

import requests
import time
import json

# Test configuration
BASE_URL = "http://localhost:7071/api"  # Or Azure URL

def test_vector_processing():
    """Test vector dataset processing."""

    # 1. Submit request
    request_payload = {
        "dataset_id": "test_dataset",
        "resource_id": "test_resource",
        "version_id": "v1.0",
        "request_type": "vector",
        "source_path": "bronze/test/sample.gpkg",
        "processing_config": {
            "target_crs": "EPSG:4326"
        }
    }

    print("Submitting platform request...")
    response = requests.post(
        f"{BASE_URL}/platform/submit",
        json=request_payload
    )

    assert response.status_code == 202
    result = response.json()
    request_id = result['request_id']
    status_url = result['status_url']

    print(f"Request accepted: {request_id}")
    print(f"Status URL: {status_url}")

    # 2. Poll for status
    max_attempts = 30
    for i in range(max_attempts):
        print(f"Checking status (attempt {i+1}/{max_attempts})...")

        status_response = requests.get(f"{BASE_URL}{status_url}")
        status_data = status_response.json()

        print(f"Status: {status_data['status']}")

        if status_data['status'] == 'completed':
            print("✅ Processing completed!")
            print(f"Endpoints: {json.dumps(status_data['endpoints'], indent=2)}")
            return True

        elif status_data['status'] == 'failed':
            print(f"❌ Processing failed: {status_data.get('message')}")
            return False

        time.sleep(10)

    print("⏱️ Timeout waiting for completion")
    return False

if __name__ == "__main__":
    test_vector_processing()
```

## Deployment Checklist

### Prerequisites
- [ ] PostgreSQL access configured
- [ ] CoreMachine working (test with hello_world job)
- [ ] Storage account access configured

### Day 1 Checklist
- [ ] Platform schema created in database
- [ ] Platform models defined
- [ ] Platform repository working
- [ ] Platform router implemented
- [ ] HTTP endpoints added to function_app.py

### Day 2 Checklist
- [ ] Job completion handler created
- [ ] Completion wired to CoreMachine
- [ ] Endpoints generation working

### Day 3 Checklist
- [ ] End-to-end test passing locally
- [ ] Deploy to Azure
- [ ] Test with real data file

## Next Steps After MVP

Once the basic flow works:

1. **Add STAC Response** (Day 4)
   - Build STAC metadata in completion handler
   - Include in status response

2. **Add Multiple Jobs** (Day 5)
   - Extend router to handle job chains
   - Track progress through multiple jobs

3. **Add Webhook Support** (Day 6)
   - Send completion notifications to DDH
   - Implement retry logic

4. **Add APIM Integration** (Week 2)
   - Configure APIM endpoints
   - Add subscription key validation
   - Remove auth from function app

## Troubleshooting Guide

### Common Issues

**Database Connection Failed**
```python
# Check connection string
print(platform_repo.conn_string)
# Verify network access to PostgreSQL
```

**Job Not Submitting**
```python
# Check job exists in ALL_JOBS
from jobs import ALL_JOBS
print(ALL_JOBS.keys())
```

**Completion Not Firing**
```python
# Check if platform_request_id is in job parameters
# Add logging in completion handler
```

**Status Not Updating**
```sql
-- Check database directly
SELECT * FROM platform.requests WHERE request_id = 'your_id';
SELECT * FROM app.jobs WHERE parameters->>'_platform_request_id' = 'your_id';
```

This incremental approach gets you a working system quickly while building on your existing CoreMachine infrastructure!