# IBAT API v2 Reference

> **World Bank Enterprise Plus Account**  
> Internal documentation for DDH Geospatial Integration Pipeline

## Authentication

All requests require query parameter authentication:

| Parameter | Value |
|-----------|-------|
| `auth_key` | `7eEEdt59VqWZ4_AGnGDF` |
| `auth_token` | `8E_M1Godrvh1PNFLZZa-kGh9v6ZRgQ` |

**Base URL:** `https://app.ibat-alliance.org/api/v2`

---

## Data Downloads Endpoint

This is the primary endpoint for bulk data acquisition.

### `GET /data-downloads`

Returns a presigned S3 URL for downloading complete dataset dumps.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `dataset_name` | string | Yes | One of: `wdpa`, `kba`, `redlist`, `star_t`, `star` |
| `auth_key` | string | Yes | Authentication key |
| `auth_token` | string | Yes | Authentication token |

**Available Datasets:**

| Dataset | Description | Notes |
|---------|-------------|-------|
| `wdpa` | World Database on Protected Areas | ~295,000+ sites globally |
| `kba` | Key Biodiversity Areas | Updated twice per year |
| `redlist` | IUCN Red List of Threatened Species | 155,000+ species |
| `star_t` | STAR Threat Abatement | **1x1 km² resolution** (newer) |
| `star` | STAR (legacy) | 5x5 km², latest Restoration but older Threat |

**Response:**

```json
{
  "download_url": "https://amazonpresignedurl.com/...",
  "update_date": "May 2023"
}
```

---

## Python Examples

### Basic Download Function

```python
import httpx
from pathlib import Path
from datetime import datetime

IBAT_BASE_URL = "https://app.ibat-alliance.org/api/v2"
IBAT_AUTH = {
    "auth_key": "7eEEdt59VqWZ4_AGnGDF",
    "auth_token": "8E_M1Godrvh1PNFLZZa-kGh9v6ZRgQ"
}

DATASETS = ["wdpa", "kba", "redlist", "star_t", "star"]


def get_download_url(dataset_name: str) -> dict:
    """
    Get presigned download URL for an IBAT dataset.
    
    Returns dict with 'download_url' and 'update_date'
    """
    if dataset_name not in DATASETS:
        raise ValueError(f"Invalid dataset: {dataset_name}. Must be one of {DATASETS}")
    
    response = httpx.get(
        f"{IBAT_BASE_URL}/data-downloads",
        params={"dataset_name": dataset_name, **IBAT_AUTH},
        timeout=30.0
    )
    response.raise_for_status()
    return response.json()


def download_dataset(dataset_name: str, output_dir: Path) -> Path:
    """
    Download an IBAT dataset to the specified directory.
    
    Returns path to downloaded file.
    """
    # Get the presigned URL
    info = get_download_url(dataset_name)
    download_url = info["download_url"]
    update_date = info["update_date"]
    
    # Parse filename from URL or construct one
    # Presigned URLs typically have the filename in the path
    url_path = download_url.split("?")[0]
    original_filename = url_path.split("/")[-1]
    
    # Create output filename with date stamp
    timestamp = datetime.utcnow().strftime("%Y%m%d")
    output_path = output_dir / f"{dataset_name}_{timestamp}_{original_filename}"
    
    # Stream download (these files can be large)
    with httpx.stream("GET", download_url, timeout=None, follow_redirects=True) as response:
        response.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in response.iter_bytes(chunk_size=8192):
                f.write(chunk)
    
    return output_path
```

### Task Worker Integration

For your "oops I built durable functions" orchestrator:

```python
import httpx
import logging
from pathlib import Path
from azure.storage.blob import BlobServiceClient
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class IbatDownloadTask:
    """Task payload for IBAT download stage"""
    dataset_name: str
    blob_container: str = "ibat-staging"
    check_update_date: bool = True


class IbatDownloader:
    """
    IBAT data downloader for DDH Vector ETL pipeline.
    
    Designed to run as a task worker in job stage execution.
    """
    
    BASE_URL = "https://app.ibat-alliance.org/api/v2"
    AUTH = {
        "auth_key": "7eEEdt59VqWZ4_AGnGDF",
        "auth_token": "8E_M1Godrvh1PNFLZZa-kGh9v6ZRgQ"
    }
    
    def __init__(self, blob_connection_string: str):
        self.blob_service = BlobServiceClient.from_connection_string(blob_connection_string)
        self.http_client = httpx.Client(timeout=30.0)
    
    def get_dataset_info(self, dataset_name: str) -> dict:
        """Fetch download URL and update date from IBAT API"""
        response = self.http_client.get(
            f"{self.BASE_URL}/data-downloads",
            params={"dataset_name": dataset_name, **self.AUTH}
        )
        response.raise_for_status()
        return response.json()
    
    def get_last_processed_date(self, dataset_name: str) -> str | None:
        """
        Check blob metadata or your PostgreSQL state table for last processed date.
        
        Implement based on your state management approach.
        """
        # Option 1: Check blob metadata
        container = self.blob_service.get_container_client("ibat-staging")
        try:
            # Look for a marker blob with metadata
            marker = container.get_blob_client(f"{dataset_name}/.last_update")
            props = marker.get_blob_properties()
            return props.metadata.get("update_date")
        except:
            return None
        
        # Option 2: Query your PostgreSQL job state table
        # cursor.execute(
        #     "SELECT last_update_date FROM etl_dataset_state WHERE dataset = %s",
        #     (f"ibat_{dataset_name}",)
        # )
    
    def set_last_processed_date(self, dataset_name: str, update_date: str):
        """Record that we've processed this update"""
        container = self.blob_service.get_container_client("ibat-staging")
        marker = container.get_blob_client(f"{dataset_name}/.last_update")
        marker.upload_blob(b"", overwrite=True, metadata={"update_date": update_date})
    
    def execute(self, task: IbatDownloadTask) -> dict:
        """
        Execute download task. Returns result dict for orchestrator.
        
        This is your task worker entry point.
        """
        logger.info(f"Starting IBAT download: {task.dataset_name}")
        
        # Get current dataset info from IBAT
        info = self.get_dataset_info(task.dataset_name)
        download_url = info["download_url"]
        update_date = info["update_date"]
        
        logger.info(f"IBAT {task.dataset_name} update_date: {update_date}")
        
        # Check if we need to download
        if task.check_update_date:
            last_processed = self.get_last_processed_date(task.dataset_name)
            if last_processed == update_date:
                logger.info(f"Already processed {task.dataset_name} for {update_date}, skipping")
                return {
                    "status": "skipped",
                    "reason": "already_processed",
                    "dataset": task.dataset_name,
                    "update_date": update_date
                }
        
        # Stream download directly to blob storage
        container = self.blob_service.get_container_client(task.blob_container)
        
        # Determine blob name from URL
        url_filename = download_url.split("?")[0].split("/")[-1]
        blob_name = f"{task.dataset_name}/{update_date.replace(' ', '_')}_{url_filename}"
        
        blob_client = container.get_blob_client(blob_name)
        
        # Stream from IBAT to Azure Blob
        with httpx.stream("GET", download_url, timeout=None, follow_redirects=True) as response:
            response.raise_for_status()
            
            # Get content length if available
            content_length = response.headers.get("content-length")
            if content_length:
                logger.info(f"Downloading {int(content_length) / 1024 / 1024:.1f} MB")
            
            # Upload in blocks
            blob_client.upload_blob(
                response.iter_bytes(chunk_size=4 * 1024 * 1024),  # 4MB chunks
                overwrite=True,
                metadata={
                    "source": "ibat",
                    "dataset": task.dataset_name,
                    "update_date": update_date
                }
            )
        
        # Record successful download
        self.set_last_processed_date(task.dataset_name, update_date)
        
        blob_url = blob_client.url
        logger.info(f"Downloaded to {blob_url}")
        
        return {
            "status": "success",
            "dataset": task.dataset_name,
            "update_date": update_date,
            "blob_url": blob_url,
            "blob_name": blob_name
        }
    
    def close(self):
        self.http_client.close()


# Usage in your task worker:
def handle_ibat_download_task(task_payload: dict, context: dict) -> dict:
    """Entry point called by your orchestrator"""
    task = IbatDownloadTask(**task_payload)
    
    downloader = IbatDownloader(
        blob_connection_string=context["blob_connection_string"]
    )
    try:
        return downloader.execute(task)
    finally:
        downloader.close()
```

### Download All Datasets (One-shot Script)

```python
#!/usr/bin/env python3
"""
Quick script to download all IBAT datasets.
Run manually or schedule as needed.
"""

import httpx
from pathlib import Path
from datetime import datetime
import sys

IBAT_BASE_URL = "https://app.ibat-alliance.org/api/v2"
IBAT_AUTH = {
    "auth_key": "7eEEdt59VqWZ4_AGnGDF",
    "auth_token": "8E_M1Godrvh1PNFLZZa-kGh9v6ZRgQ"
}

DATASETS = ["wdpa", "kba", "redlist", "star_t", "star"]


def main(output_dir: str = "./ibat_data"):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.utcnow().strftime("%Y%m%d")
    
    for dataset in DATASETS:
        print(f"\n{'='*50}")
        print(f"Downloading: {dataset}")
        print('='*50)
        
        # Get download URL
        response = httpx.get(
            f"{IBAT_BASE_URL}/data-downloads",
            params={"dataset_name": dataset, **IBAT_AUTH},
            timeout=30.0
        )
        response.raise_for_status()
        info = response.json()
        
        download_url = info["download_url"]
        update_date = info["update_date"]
        print(f"Update date: {update_date}")
        
        # Get filename from URL
        url_filename = download_url.split("?")[0].split("/")[-1]
        local_filename = f"{dataset}_{timestamp}_{url_filename}"
        local_path = output_path / local_filename
        
        # Download with progress
        with httpx.stream("GET", download_url, timeout=None, follow_redirects=True) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            
            with open(local_path, "wb") as f:
                downloaded = 0
                for chunk in r.iter_bytes(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = (downloaded / total) * 100
                        print(f"\r  {downloaded / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} MB ({pct:.1f}%)", end="")
        
        print(f"\n  Saved: {local_path}")
    
    print(f"\n\nAll downloads complete in {output_path}")


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "./ibat_data"
    main(output)
```

---

## Other API Endpoints (Reference)

These are available but probably not needed for bulk ETL - the data downloads give you everything. Useful for spot checks or if you need to query specific features.

### Key Biodiversity Areas

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/kba/{sitrecid}` | Single KBA by ID |
| GET | `/kba/countries/{iso_3}/summary` | Count of KBAs in country |
| GET | `/kba/countries/{iso_3}/areas` | List KBAs in country (paginated) |
| POST | `/kba/intersect/summary` | Count of KBAs intersecting geometry |
| POST | `/kba/intersect/areas` | List KBAs intersecting geometry |

### Protected Areas (WDPA)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/wdpa/{wdpaid}` | Single PA by ID |
| GET | `/wdpa/countries/{iso_3}/summary` | Count of PAs in country |
| GET | `/wdpa/countries/{iso_3}/areas` | List PAs in country (paginated) |
| POST | `/wdpa/intersect/summary` | Count of PAs intersecting geometry |
| POST | `/wdpa/intersect/areas` | List PAs intersecting geometry |

### IUCN Red List Species

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/redlist/intersect/species` | Species intersecting geometry (50km buffer) |

### Common Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `with_geojson` | false | Include geometry in response |
| `page` | 1 | Page number |
| `per_page` | 25 (max 50) | Results per page |

### Intersection Request Body

```json
{
  "type": "POINT",  // or "LINESTRING", "POLYGON"
  "buffers": [10000, 50000],  // meters
  "coordinates": [5.91, 51.26]  // [lon, lat]
}
```

**Max area:** 500,000 km²

---

## Rate Limits & Error Handling

IBAT rate limits based on system load. Handle these responses:

| Code | Response | Action |
|------|----------|--------|
| 200 | Success | Process response |
| 400 | Bad Request | Check parameters |
| 401 | Unauthorized | Check auth credentials |
| 429 | Rate limit exceeded | Retry with backoff |
| 500 | Internal server error | Retry later |

```python
import time
from httpx import HTTPStatusError

def get_with_retry(url: str, params: dict, max_retries: int = 3) -> dict:
    """GET with exponential backoff for rate limits"""
    for attempt in range(max_retries):
        try:
            response = httpx.get(url, params=params, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except HTTPStatusError as e:
            if e.response.status_code == 429:
                wait = 2 ** attempt * 10  # 10s, 20s, 40s
                logger.warning(f"Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                raise
    raise Exception(f"Max retries exceeded for {url}")
```

---

## Notes

- WDPA updates monthly (start of each month)
- KBA updates twice per year
- Red List updates throughout the year
- STAR data: prefer `star_t` (1km resolution) over `star` (5km) for new work
- Downloaded files are typically GeoPackage or Shapefile format
- Coordinate order is always `[longitude, latitude]`

---

*Last updated: January 2026*  
*Account: World Bank Enterprise Plus*
