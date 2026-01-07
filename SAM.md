# SAM Building Footprint Extraction: Proof of Concept Plan

## Overview

This document outlines a proof-of-concept implementation for extracting building footprints from high-resolution satellite imagery using Meta's Segment Anything Model (SAM), targeting urban risk analysis for World Bank projects.

### Use Case
- Extract building footprints from Maxar/Vantor imagery for cities like Juba and Kigali
- Support urban risk analysis workflows
- Demonstrate a "real Databricks use case" for future scale-up (not CSV management)

### Why This Matters
The deduplication step after SAM inference is a genuinely distributed computing problem. When you tile imagery with overlap (necessary for buildings at tile boundaries), you generate millions of candidate polygons that must be spatially joined and merged. This is the legitimate justification for Databricks—not at PoC scale, but when processing dozens of cities.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  EXISTING: rmhgeoapi (Azure Functions)                              │
│  ───────────────────────────────────────────────────────────────────│
│  Maxar COG ingestion → MosaicJSON → Blob Storage (bronze tier)      │
│  TiTiler integration, H3 infrastructure, PostGIS, DuckDB            │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  NEW: SAM Inference (Azure GPU VM - External)                       │
│  ───────────────────────────────────────────────────────────────────│
│  - Data Science VM with V100 GPU (spot pricing)                     │
│  - SAM ViT-H model inference on each tile                           │
│  - Filter for building-like masks                                   │
│  - Convert masks to georeferenced polygons                          │
│  Output: GeoParquet files in Blob Storage (bronze tier)             │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  EXISTING: rmhgeoapi Deduplication Job                              │
│  ───────────────────────────────────────────────────────────────────│
│  - DuckDB: Query GeoParquet directly from blob (no ingestion)       │
│  - H3 spatial indexing (existing infrastructure)                    │
│  - ST_Union / ST_ClusterDBSCAN for polygon merging                  │
│  - PostGIS: Final storage for OGC Features API serving              │
│  Output: Deduplicated footprints (GeoParquet + PostGIS + STAC)      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## rmhgeoapi Integration (07 JAN 2026)

### What Already Exists in rmhgeoapi

The following infrastructure is already implemented and can be leveraged for SAM workflows:

| Component | Status | rmhgeoapi Location |
|-----------|--------|-------------------|
| **COG Ingestion** | ✅ Full | Raster pipeline, multi-tier storage |
| **MosaicJSON Generation** | ✅ Full | `services/raster_mosaicjson.py` |
| **Blob Storage** | ✅ Full | Bronze/silver/gold tiers, multi-account |
| **H3 Spatial Indexing** | ✅ Full | 88+ files, `config/h3_config.py`, `infrastructure/h3_repository.py` |
| **PostGIS** | ✅ Full | Managed identity auth, spatial operations |
| **DuckDB + Spatial** | ✅ Full | `infrastructure/duckdb.py` with spatial, H3, Azure extensions |
| **GeoParquet I/O** | ✅ Full | Export jobs, DuckDB direct queries |
| **Job Orchestration** | ✅ Full | Job → Stage → Task pattern |
| **STAC Catalog** | ✅ Full | Vector items with postgis:// asset links |
| **OGC Features API** | ✅ Full | Public-facing feature serving |

### What Requires GPU VM (External)

These components require PyTorch + CUDA and must run on a GPU VM:

| Component | Why External |
|-----------|--------------|
| **SAM Model Loading** | ViT-H weights require GPU memory (16GB VRAM) |
| **Mask Inference** | CUDA-accelerated neural network forward pass |
| **Mask → Polygon Conversion** | Part of inference pipeline, co-located with model |
| **Building Classification Heuristics** | Domain-specific filtering (area, shape, confidence) |

### Recommended Workflow

```
GPU VM (SAM Inference)                    rmhgeoapi (Orchestration + Storage)
─────────────────────                     ─────────────────────────────────────
1. Read COG tiles from blob        ←────  COGs already in bronze tier
2. Run SAM inference (GPU)
3. Filter building-like masks
4. Convert to polygons
5. Write GeoParquet to blob        ────→  SAM output lands in bronze tier
                                          6. Submit dedup job via API
                                          7. DuckDB queries GeoParquet in-place
                                          8. H3 clustering + ST_Union
                                          9. Write to PostGIS (geo.buildings)
                                          10. Create STAC item
                                          11. Available via OGC Features API
```

### New Job Required: `deduplicate_building_polygons`

A single new job to be created in rmhgeoapi:

```
Job: deduplicate_building_polygons
├── Stage 1: DuckDB deduplication (query blob GeoParquet directly)
│   - Add H3 cell index
│   - ST_ClusterDBSCAN or H3-based grouping
│   - ST_Union_Agg per cluster
│   - Write deduplicated GeoParquet to silver tier
├── Stage 2: Ingest to PostGIS (existing vector pattern)
│   - Load GeoParquet → geo.buildings table
├── Stage 3: Create STAC item (existing pattern)
│   - postgis:// asset link
│   - Metadata from table extent
└── Output: OGC Features API ready
```

---

## Tools and Libraries

### SAM Inference

| Component | Library/Tool | Notes |
|-----------|--------------|-------|
| Segmentation model | `segment-anything` | Meta's SAM, ViT-H variant |
| Deep learning | `torch`, `torchvision` | PyTorch with CUDA |
| Raster I/O | `rasterio` | Read GeoTIFFs, get transforms |
| Geometry conversion | `shapely` | Mask to polygon conversion |
| Geospatial dataframes | `geopandas` | Output handling |
| Coordinate transforms | `pyproj` | CRS management |
| Image processing | `opencv-python` | Required by SAM |

### Deduplication

| Component | Library/Tool | Notes |
|-----------|--------------|-------|
| Spatial indexing | `h3` (h3-py) | Uber's hexagonal grid system |
| Graph algorithms | `networkx` | Connected components for merging |
| Spatial operations | `geopandas` + `shapely` | Intersection, union operations |
| Alternative: SQL | PostGIS + `h3-pg` | If memory constrained |
| Alternative: Fast analytics | DuckDB + spatial extension | Surprisingly capable |

### Storage Format

| Format | Use Case |
|--------|----------|
| GeoParquet | Intermediate results, columnar and fast |
| GeoPackage (GPKG) | Final outputs, portable single-file |
| Delta Lake | Future Databricks integration |

---

## Compute Options Considered

### GPU Inference

| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| **Azure Data Science VM** | Pre-configured CUDA/PyTorch, JupyterHub included, spot pricing | Manual management | ✅ **Recommended for PoC** |
| Azure ML Compute Instance | Fully managed, notebook in browser | Requires ML Workspace overhead | Good alternative |
| Azure Container Instances | Familiar container model | GPU support limited/preview | Not recommended |
| Azure Batch with GPU pool | Good for large scale | Overkill for PoC | Future consideration |

**Selected: Data Science VM (Ubuntu) with NC6s_v3**

### Deduplication

| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| **DuckDB + H3** | Query GeoParquet in-place (no ingestion), disk spillover, fast | Analytical only (no persistence) | ✅ **Recommended for compute** |
| **PostGIS + h3-pg** | Persistent storage, OGC Features ready, STAC integration | Requires ingestion step | ✅ **Recommended for storage** |
| Geopandas + H3 on VM | Simple, Pythonic, single environment | Memory limits at ~5M polygons | Alternative for small datasets |
| Databricks + Mosaic | Industrial scale, built for this | Expensive, overkill for 2 cities | Future scale-up |

#### DuckDB vs PostGIS: Detailed Comparison (07 JAN 2026)

| Factor | DuckDB | PostGIS |
|--------|--------|---------|
| **Memory Model** | Disk spillover (configurable via `temp_directory`) | Disk-backed (no limit) |
| **Max Dataset Size** | Can exceed RAM with spillover | Disk-limited only |
| **Query GeoParquet** | Direct from blob (no copy!) | Must ingest first |
| **H3 Support** | h3 extension ✅ | h3-pg extension ✅ |
| **Spatial Ops** | ST_* (spatial extension) | ST_* (mature, full PostGIS) |
| **Clustering** | ST_ClusterDBSCAN | ST_ClusterDBSCAN |
| **Persistence** | Analytical (query results only) | Tables persist |
| **OGC Features API** | ❌ Not directly | ✅ Native serving |
| **STAC Integration** | ❌ Export required | ✅ postgis:// asset links |
| **Already in rmhgeoapi** | ✅ Full | ✅ Full |

#### Recommended Hybrid Approach

Use DuckDB for compute, PostGIS for persistence:

```
SAM output (GeoParquet in blob)
    ↓
DuckDB: H3 clustering + ST_Union_Agg
    - Query directly from blob (no ingestion!)
    - Handles larger-than-memory via disk spillover
    - Write deduplicated GeoParquet to silver tier
    ↓
PostGIS: Final storage
    - Ingest deduplicated GeoParquet (much smaller)
    - geo.buildings table
    - OGC Features API serving
    ↓
STAC: Catalog entry
    - postgis:// asset link
    - Discoverable via STAC API
```

#### DuckDB Deduplication Query Example

```sql
-- Query GeoParquet DIRECTLY from Azure blob storage
-- No download, no ingestion - DuckDB streams from blob
SELECT
    h3_latlng_to_cell(
        ST_Y(ST_Centroid(geometry)),
        ST_X(ST_Centroid(geometry)),
        10  -- H3 resolution 10 (~15,000 m² cells)
    ) AS h3_cell,
    ST_Union_Agg(geometry) AS merged_geom,
    COUNT(*) AS building_count,
    SUM(area_sqm) AS total_area
FROM read_parquet('azure://bronze/sam_output/juba_buildings_*.parquet')
GROUP BY h3_cell;
```

#### PostGIS Deduplication Query Example

```sql
-- Alternative: Pure PostGIS approach using ST_ClusterDBSCAN
WITH clustered AS (
    SELECT
        id,
        geom,
        ST_ClusterDBSCAN(geom, eps := 0, minpoints := 1) OVER () AS cluster_id
    FROM geo.buildings_raw
)
SELECT
    cluster_id,
    ST_Union(geom) AS geom,
    COUNT(*) AS merged_count
FROM clustered
GROUP BY cluster_id;
```

---

## VM Specifications

### GPU VM for SAM Inference

```
Name:     Standard_NC6s_v3
GPU:      1x NVIDIA V100 (16GB)
vCPUs:    6
RAM:      112 GB
Pricing:  ~$0.27/hr (spot) | ~$0.90/hr (pay-as-you-go)
Image:    Data Science Virtual Machine - Ubuntu
```

### Deduplication VM - NOT REQUIRED

Deduplication runs within rmhgeoapi using existing DuckDB + PostGIS infrastructure.
No separate VM needed - eliminates ~$0.80/hr compute cost for deduplication.

---

## Setup Steps

### 1. Create the GPU VM

**Via Azure Portal:**
1. Create Resource → "Data Science Virtual Machine"
2. Select **Ubuntu** (not Windows)
3. Size: `Standard_NC6s_v3`
4. **Enable Spot pricing** (set max price ~$0.30)
5. Authentication: SSH key (let Azure generate)
6. **Region: Same as your blob storage** (critical for free data transfer)
7. OS Disk: Change to Standard SSD to save ~$5/month

**Via CLI:**
```bash
az vm create \
  --resource-group your-rg \
  --name sam-inference \
  --image microsoft-dsvm:ubuntu-hpc:2204:latest \
  --size Standard_NC6s_v3 \
  --admin-username azureuser \
  --generate-ssh-keys \
  --priority Spot \
  --max-price 0.30 \
  --os-disk-size-gb 128 \
  --storage-sku Standard_LRS
```

### 2. Connect to VM

**Option A: JupyterHub (Recommended for interactive work)**
```
https://<VM_PUBLIC_IP>:8000
Username: azureuser
Password: (your VM password)
```

**Option B: SSH**
```bash
ssh azureuser@<VM_PUBLIC_IP>
```

**Option C: VS Code Remote SSH**
```
Ctrl+Shift+P → "Remote-SSH: Connect to Host" → azureuser@<IP>
```

### 3. Environment Setup

```bash
# DSVM already has conda - create isolated environment
conda create -n sam python=3.10 -y
conda activate sam

# Verify GPU is visible
nvidia-smi
# Should show V100 GPU

# PyTorch with CUDA (ensure correct version)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118

# SAM
pip install segment-anything

# Geospatial
pip install rasterio geopandas pyproj shapely
pip install pyarrow  # For GeoParquet output

# Azure blob access
pip install azure-storage-blob azure-identity

# Image processing (SAM dependency)
pip install opencv-python-headless
```

### 4. Download SAM Model Weights

```bash
mkdir -p ~/models
cd ~/models

# SAM ViT-H (largest, best quality) - 2.4GB
wget https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth

# Verify download
ls -lh sam_vit_h_4b8939.pth
# Should show ~2.4GB
```

**Alternative models** (if memory constrained):
```bash
# ViT-L (1.2GB) - good balance
wget https://dl.fbaipublicfiles.com/segment_anything/sam_vit_l_0b3195.pth

# ViT-B (375MB) - fastest, lower quality
wget https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth
```

### 5. Configure Blob Storage Access

**Option A: Connection String (Simple)**
```bash
# Add to ~/.bashrc
export AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=rmhazuregeobronze;AccountKey=..."
source ~/.bashrc
```

**Option B: Managed Identity (Recommended for production)**
```bash
# Assign identity to VM in Azure Portal:
# VM → Identity → System assigned → On
# Then grant "Storage Blob Data Reader" role on storage account
```

**Create blob access helper** (`~/blob_config.py`):
```python
import os
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential

def get_blob_client():
    """Get blob client using connection string or managed identity."""
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if conn_str:
        return BlobServiceClient.from_connection_string(conn_str)
    else:
        # Falls back to managed identity
        return BlobServiceClient(
            account_url="https://rmhazuregeobronze.blob.core.windows.net",
            credential=DefaultAzureCredential()
        )
```

### 6. Verify SAM Installation

Create `~/test_sam.py`:
```python
#!/usr/bin/env python3
"""Quick SAM verification script."""

import torch
from segment_anything import sam_model_registry, SamAutomaticMaskGenerator

print(f"PyTorch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
print(f"GPU: {torch.cuda.get_device_name(0)}")

# Load model
print("\nLoading SAM model...")
sam = sam_model_registry["vit_h"](checkpoint="/home/azureuser/models/sam_vit_h_4b8939.pth")
sam.to("cuda")
print("✅ SAM loaded successfully on GPU!")

# Create mask generator
mask_generator = SamAutomaticMaskGenerator(
    sam,
    points_per_side=32,
    pred_iou_thresh=0.86,
    stability_score_thresh=0.92,
    min_mask_region_area=100,
)
print("✅ Mask generator ready!")

# Test with dummy image
import numpy as np
dummy_image = np.random.randint(0, 255, (1024, 1024, 3), dtype=np.uint8)
print("\nRunning inference on dummy image...")
masks = mask_generator.generate(dummy_image)
print(f"✅ Generated {len(masks)} masks!")

print("\n🎉 SAM is working correctly!")
```

Run verification:
```bash
conda activate sam
python ~/test_sam.py
```

### 7. SAM Inference Script

Create `~/sam_inference.py`:
```python
#!/usr/bin/env python3
"""
SAM Building Footprint Extraction.

Reads COG tiles from Azure Blob, runs SAM inference, outputs GeoParquet.
"""

import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window
import geopandas as gpd
from shapely.geometry import shape
from shapely.affinity import affine_transform
import torch
from segment_anything import sam_model_registry, SamAutomaticMaskGenerator
from azure.storage.blob import BlobServiceClient

# ============================================================================
# CONFIGURATION - Update these for your project
# ============================================================================
MODEL_PATH = "/home/azureuser/models/sam_vit_h_4b8939.pth"
INPUT_CONTAINER = "bronze"
INPUT_PREFIX = "maxar/juba/"  # Folder containing COG tiles
OUTPUT_CONTAINER = "bronze"
OUTPUT_PREFIX = "sam_output/juba/"

# Building filter thresholds
MIN_AREA_SQM = 20       # Minimum building size
MAX_AREA_SQM = 50000    # Maximum (filter out large non-buildings)
MIN_SOLIDITY = 0.7      # How "solid" vs irregular (buildings are usually solid)


def get_blob_client():
    """Get Azure blob client."""
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    return BlobServiceClient.from_connection_string(conn_str)


def load_sam_model():
    """Load SAM model to GPU."""
    print("Loading SAM model...")
    sam = sam_model_registry["vit_h"](checkpoint=MODEL_PATH)
    sam.to("cuda")

    mask_generator = SamAutomaticMaskGenerator(
        sam,
        points_per_side=32,
        pred_iou_thresh=0.86,
        stability_score_thresh=0.92,
        min_mask_region_area=100,
    )
    print("✅ Model loaded!")
    return mask_generator


def mask_to_polygon(mask, transform):
    """Convert binary mask to georeferenced polygon."""
    from rasterio.features import shapes

    polygons = []
    for geom, value in shapes(mask.astype(np.uint8), transform=transform):
        if value == 1:
            polygons.append(shape(geom))

    return polygons


def filter_buildings(polygons, crs):
    """Filter polygons that look like buildings."""
    buildings = []

    for poly in polygons:
        # Calculate area in square meters (approximate)
        area = poly.area

        # Solidity = area / convex_hull_area
        if poly.convex_hull.area > 0:
            solidity = area / poly.convex_hull.area
        else:
            solidity = 0

        # Apply filters
        if MIN_AREA_SQM <= area <= MAX_AREA_SQM and solidity >= MIN_SOLIDITY:
            buildings.append({
                'geometry': poly,
                'area_sqm': area,
                'solidity': solidity
            })

    return buildings


def process_tile(blob_name: str, mask_generator, blob_client) -> list:
    """Process a single COG tile through SAM."""
    print(f"Processing: {blob_name}")

    # Download tile to temp file
    container = blob_client.get_container_client(INPUT_CONTAINER)
    blob_data = container.download_blob(blob_name).readall()

    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
        tmp.write(blob_data)
        tmp_path = tmp.name

    try:
        with rasterio.open(tmp_path) as src:
            # Read RGB bands
            rgb = src.read([1, 2, 3]).transpose(1, 2, 0)  # CHW -> HWC
            transform = src.transform
            crs = src.crs

        # Run SAM inference
        masks = mask_generator.generate(rgb)
        print(f"  Generated {len(masks)} masks")

        # Convert masks to polygons
        all_buildings = []
        for mask_data in masks:
            mask = mask_data['segmentation']
            confidence = mask_data['predicted_iou']

            polygons = mask_to_polygon(mask, transform)
            buildings = filter_buildings(polygons, crs)

            for b in buildings:
                b['confidence'] = confidence
                b['source_tile'] = blob_name

            all_buildings.extend(buildings)

        print(f"  Filtered to {len(all_buildings)} building candidates")
        return all_buildings, crs

    finally:
        os.unlink(tmp_path)


def main():
    """Main inference pipeline."""
    blob_client = get_blob_client()
    mask_generator = load_sam_model()

    # List input tiles
    container = blob_client.get_container_client(INPUT_CONTAINER)
    blobs = list(container.list_blobs(name_starts_with=INPUT_PREFIX))
    tif_blobs = [b.name for b in blobs if b.name.endswith('.tif')]

    print(f"Found {len(tif_blobs)} tiles to process")

    # Process all tiles
    all_buildings = []
    crs = None

    for blob_name in tif_blobs:
        buildings, tile_crs = process_tile(blob_name, mask_generator, blob_client)
        all_buildings.extend(buildings)
        crs = tile_crs  # Assume all tiles have same CRS

    print(f"\nTotal buildings extracted: {len(all_buildings)}")

    # Create GeoDataFrame
    gdf = gpd.GeoDataFrame(all_buildings, crs=crs)

    # Save to GeoParquet
    output_path = f"/tmp/buildings_raw.parquet"
    gdf.to_parquet(output_path)
    print(f"Saved to {output_path}")

    # Upload to blob storage
    output_blob = f"{OUTPUT_PREFIX}buildings_raw.parquet"
    output_container = blob_client.get_container_client(OUTPUT_CONTAINER)
    with open(output_path, "rb") as f:
        output_container.upload_blob(output_blob, f, overwrite=True)

    print(f"✅ Uploaded to {OUTPUT_CONTAINER}/{output_blob}")


if __name__ == "__main__":
    main()
```

Run the inference:
```bash
conda activate sam
python ~/sam_inference.py
```

### 8. Trigger rmhgeoapi Deduplication

Once SAM output is in blob storage, call rmhgeoapi to deduplicate and ingest:

```bash
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/deduplicate_building_polygons" \
  -H "Content-Type: application/json" \
  -d '{
    "input_blob": "sam_output/juba/buildings_raw.parquet",
    "city": "juba",
    "h3_resolution": 10
  }'
```

### 9. File Locations Reference

```
~/models/
  └── sam_vit_h_4b8939.pth     # SAM weights (2.4GB)

~/
  ├── blob_config.py           # Azure blob helper
  ├── test_sam.py              # Verification script
  └── sam_inference.py         # Main inference script

/tmp/
  └── buildings_raw.parquet    # Local output before upload
```

### 10. Cleanup

**Stop VM (preserves disk, stops compute charges):**
```bash
az vm deallocate --resource-group your-rg --name sam-inference
```

**Delete everything when done:**
```bash
az vm delete --resource-group your-rg --name sam-inference --yes
# Also delete associated resources:
az disk delete --resource-group your-rg --name sam-inference_OsDisk_1_xxx --yes
az network nic delete --resource-group your-rg --name sam-inferenceVMNic --yes
az network public-ip delete --resource-group your-rg --name sam-inferencePublicIP --yes
```

**Check for orphaned disks:**
```
Azure Portal → Disks → Filter by "Unattached" → Delete any leftovers
```

---

## Cost Estimates

### PoC Budget (Juba + Kigali)

| Item | Low | High | Notes |
|------|-----|------|-------|
| GPU compute (Juba) | $2 | $10 | 3-6 hrs spot |
| GPU compute (Kigali) | $3 | $15 | Larger city |
| VM disk (1 month) | $10 | $20 | Delete when done |
| Deduplication compute | $0 | $0 | ~~E16s_v5~~ Uses rmhgeoapi (no extra cost) |
| Storage (blob) | $2 | $5 | Negligible |
| Egress (download results) | $0 | $2 | ~$0.087/GB |
| Mistakes/reruns | $10 | $50 | Learning curve buffer |
| **Total** | **$27** | **$102** | Reduced by using rmhgeoapi for dedup |

### Cost Safeguards

1. **Set budget alert:**
   ```
   Azure Portal → Cost Management → Budgets → Create
   Amount: $150 | Alert at: 50%, 80%, 100%
   ```

2. **Use spot pricing** for GPU VMs

3. **Same region** for storage and compute (free intra-region transfer)

4. **Stop VMs** when not actively using

5. **Delete disks** when PoC complete

---

## Scale-Up Path: When to Use Databricks

Stay on single-VM approach when:
- Processing 1-5 cities
- Polygon count < 5M per run
- Iterating on methodology

Move to Databricks + Mosaic when:
- Processing 10+ cities
- Polygon count > 5M
- Temporal analysis (change detection across years)
- Production pipeline with scheduling
- Need to demonstrate "enterprise" solution

### Databricks Setup (Future)

```python
# Mosaic library for Databricks
%pip install geopandas==0.14.3 databricks-mosaic

from mosaic import enable_mosaic
enable_mosaic(spark)

# H3 indexing and spatial joins at scale
from mosaic.functions import grid_tessellateexplode, st_intersection
```

**Requirements:**
- DBR 13.x with Photon enabled
- GPU cluster for inference (ML Runtime)
- Mosaic 0.4.x

**Reference:** Mosaic has an existing "EO Gridded STAC" example showing Sentinel-2 + SAM workflow:
https://github.com/databrickslabs/mosaic

---

## Key Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| GPU VM type | NC6s_v3 (V100) | Sufficient for SAM, good spot availability |
| SAM inference | Standalone GPU VM | PyTorch + CUDA required, external to rmhgeoapi |
| Deduplication compute | DuckDB (in rmhgeoapi) | Query GeoParquet in-place, no ingestion step, disk spillover |
| Final storage | PostGIS (in rmhgeoapi) | OGC Features API serving, STAC integration |
| Spatial index | H3 | Industry standard, already implemented in rmhgeoapi |
| Output format | GeoParquet | Columnar, fast, DuckDB-native, Databricks-compatible |
| Storage mount | Blobfuse2 | Transparent file access on GPU VM |
| Separate dedup VM | NOT NEEDED | rmhgeoapi handles via existing infrastructure |

---

## Open Questions / Next Steps

1. **SAM tuning**: What filtering thresholds work best for African urban building morphology?
   - Min/max area bounds
   - Confidence threshold
   - Shape metrics (rectangularity, aspect ratio)

2. **Tile overlap**: Current overlap for visualization may need adjustment for building extraction

3. **Validation**: How to assess accuracy without ground truth?
   - Visual inspection sample
   - Comparison to OSM (where available)
   - Comparison to existing World Bank building datasets

4. **SAM2 vs SAM**: SAM2 has text prompts ("building") - worth testing?

5. **Fine-tuning**: Worth fine-tuning SAM on African building examples?

---

## References

- [Segment Anything Model (SAM)](https://github.com/facebookresearch/segment-anything)
- [Databricks Mosaic](https://github.com/databrickslabs/mosaic)
- [H3 Spatial Index](https://h3geo.org/)
- [Azure Data Science VM](https://docs.microsoft.com/en-us/azure/machine-learning/data-science-virtual-machine/)
- [SAM for Building Extraction (research)](https://www.mdpi.com/2072-4292/16/14/2661)
