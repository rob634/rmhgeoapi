# Container List Jobs Archive (07 DEC 2025)

## Reason for Archive

These jobs and handlers were consolidated into a single unified job:
- **New Job**: `inventory_container_contents`
- **Location**: `jobs/inventory_container_contents.py`
- **Handlers**: `services/container_inventory.py`

## Consolidated Architecture

The new `inventory_container_contents` job provides:
1. **analysis_mode="basic"**: Simple file statistics (extension counts, sizes)
2. **analysis_mode="geospatial"**: Pattern detection, collection grouping, sidecar association

## Sync Endpoint

A synchronous blob listing endpoint was also enhanced:
- **Endpoint**: `GET /api/containers/{container_name}/blobs`
- **Location**: `triggers/list_container_blobs.py`
- **Features**: suffix filter, metadata toggle, limit=500 default

## Archived Files

| Original Location | Description |
|-------------------|-------------|
| `container_list.py` | Jobs - ListContainerContentsWorkflow |
| `container_list_diamond.py` | Jobs - ListContainerContentsDiamondWorkflow |
| `inventory_container_geospatial.py` | Jobs - InventoryContainerGeospatialJob |
| `services_container_list.py` | Services - list_container_blobs, analyze_single_blob, aggregate_blob_analysis |

## Migration Notes

Old job types are no longer registered:
- `list_container_contents` → Use `inventory_container_contents`
- `list_container_contents_diamond` → Use `inventory_container_contents`
- `inventory_container_geospatial` → Use `inventory_container_contents` with `analysis_mode="geospatial"`

## Author

Robert and Geospatial Claude Legion
