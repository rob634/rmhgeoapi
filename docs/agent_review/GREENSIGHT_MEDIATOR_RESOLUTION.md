# Greensight VirtualiZarr Pipeline -- Mediator Resolution

**Written by**: Agent M (Claude, 27 FEB 2026)
**Status**: RESOLUTION -- Ready for Builder (Agent B)

---

## CONFLICTS FOUND

### 1. A's Design vs O's Infrastructure Constraints

#### CONFLICT 1.1: DataType Enum -- The Blocker

**What A proposed**: Add `ZARR = "zarr"` to `DataType` in `core/models/platform.py`, and route on `data_type == DataType.ZARR` in `translate_to_coremachine()`.

**What O's constraint is**: There are TWO `DataType` enums. The platform enum (`core/models/platform.py:83`) has `{RASTER, VECTOR, POINTCLOUD, MESH_3D, TABULAR}`. The external_refs enum (`core/models/external_refs.py:52`) already has `ZARR`. Adding ZARR to the platform enum is necessary but insufficient -- every code path that switches on `data_type` must be updated.

**What the actual code shows**: The `PlatformRequest.data_type` property (line 382) is computed from file extension. `.nc` currently **raises ValueError** ("NetCDF (.nc) support is under development"). The Asset model (`core/models/asset.py:185`) constrains `data_type` to `Literal["vector", "raster"]`. The approval service (`asset_approval_service.py:645`) infers data_type as `'raster' if release.blob_path else 'vector'` -- a zarr release with a `blob_path` (pointing to the combined ref JSON) would be misidentified as raster.

**Resolution**: A three-part fix is required:

1. **Platform DataType enum**: Add `ZARR = "zarr"`. Update `PlatformRequest.data_type` property to return `DataType.ZARR` for `.nc` extension instead of raising.
2. **Asset model**: Widen `data_type` from `Literal["vector", "raster"]` to `Literal["vector", "raster", "zarr"]`.
3. **Approval service**: Replace the `'raster' if release.blob_path else 'vector'` inference with a proper lookup from `release.data_type` or `asset.data_type`. This is a bug fix independent of zarr -- any future data type that has a blob_path would be misidentified.

**Tradeoff**: Widening the Asset Literal is a schema-adjacent change. All existing assets have "vector" or "raster", so no migration is needed, but any code that does `if data_type == "raster"` must be audited. The approval service fix is necessary regardless.

---

#### CONFLICT 1.2: numpy<2 Pin vs VirtualiZarr/Kerchunk Dependencies

**What A proposed**: Add `virtualizarr` and `kerchunk` to `requirements-docker.txt`.

**What O's constraint is**: `requirements-docker.txt` pins `numpy<2` for GDAL C-extension ABI compatibility. VirtualiZarr >= 1.0 and kerchunk >= 0.2.7 may require numpy >= 2.0. The GDAL base image (`ghcr.io/osgeo/gdal:ubuntu-full-3.10.1`) ships its own numpy compiled against GDAL's C bindings.

**What the actual code shows**: The Dockerfile uses `--ignore-installed` which overrides the debian-packaged numpy. The `numpy<2` pin in requirements-docker.txt controls what version gets installed.

**Resolution**: Pin specific compatible versions:

- `virtualizarr>=1.0,<2.0` (test with numpy 1.x before building)
- `kerchunk>=0.2.6,<0.3.0` (0.2.x series supports numpy 1.x)
- `h5py>=3.10.0,<4.0` (already numpy 1.x compatible)

If VirtualiZarr 1.x hard-requires numpy >= 2, then either: (a) use VirtualiZarr 0.x series, or (b) accept a Docker image rebuild with numpy 2 and retest all GDAL paths. Option (a) is preferred for V1 to avoid destabilizing existing raster/vector pipelines.

**Tradeoff**: Pinning older versions trades access to newest features for deployment stability. This is the right call for a first version. The numpy 2 migration should be a separate enabler story.

---

#### CONFLICT 1.3: Service Bus 256KB Message Limit

**What A proposed**: Fan-out stages 2 and 3 pass file lists and ref results through task parameters in Service Bus messages.

**What O's constraint is**: Service Bus messages are limited to 256KB. A scan of 10,000 files at ~100 bytes per path = ~1MB, which exceeds the limit. Even 2,500 files would be tight.

**Resolution**: The scan stage (stage 1) writes the file list to blob storage as a JSON manifest (`refs/{dataset_id}/manifest.json`). Subsequent stages receive only the manifest URL (one string). The fan-out logic in `create_tasks_for_stage` reads the manifest to create individual tasks. Individual task messages contain a single file URL (~200 bytes), well within limits.

Similarly, stage 4 (combine) receives the manifest URL rather than the full list of nc_urls. The manifest is updated by stage 1 and remains the single source of truth for file enumeration.

**Tradeoff**: Adds one blob read before fan-out in stages 2-3 (milliseconds). Eliminates a hard scaling limit. Non-negotiable fix.

---

#### CONFLICT 1.4: Single Shared Queue Contention

**What A proposed**: Register all 5 virtualzarr task types in `DOCKER_TASKS` (routing to `container-tasks` queue).

**What O's constraint is**: All Docker tasks share one `container-tasks` queue. A 10,000-file zarr job creates 10,000+ tasks that compete with raster and vector jobs.

**Resolution**: Accept the shared queue for V1. The queue is FIFO within Service Bus, and existing raster/vector workloads are low-volume in the dev environment. Add a `max_files` parameter (default 500) to the scan stage. Jobs exceeding `max_files` are rejected at submit with a helpful error message. This caps fan-out at 500 tasks per job.

**Tradeoff**: Hard cap limits the largest datasets processable in V1. This can be lifted when independent queue routing is implemented (deferred decision). 500 files at ~30s each = ~15min wall-clock with sequential Docker processing, which is acceptable.

---

### 2. C's Edge Cases Requiring Changes to A's Design

#### CONFLICT 2.1: Asset Model Rejects data_type: "zarr" (C1, A1)

**What C found**: `Asset.data_type` is `Literal["vector", "raster"]`. Submitting `"zarr"` causes Pydantic validation to reject the Asset creation.

**How it affects A's design**: A's golden path assumes Asset creation works with `data_type="zarr"`. It does not.

**Resolution**: Covered in Conflict 1.1 above. Widen the Literal to include "zarr".

---

#### CONFLICT 2.2: PlatformRequest.data_type Property Rejects .nc (C1 extension)

**What C found**: The `data_type` property on `PlatformRequest` is derived from `file_name` extension. `.nc` raises `ValueError("NetCDF (.nc) support is under development")`.

**How it affects A's design**: A's design assumes the submit flow routes zarr through `data_type == DataType.ZARR`. But `PlatformRequest` never reaches `translate_to_coremachine()` because validation fails first.

**Resolution**: The zarr pipeline uses a different submit contract than raster/vector. Rather than `container_name` + `file_name` (blob within a known container), zarr uses `source_url` (an `abfs://` path to a prefix containing many files). Two changes are required:

1. Add `source_url` as an Optional field to `PlatformRequest`. When `source_url` is present and `processing_options.pipeline == "virtualzarr"`, the data_type is `ZARR` regardless of file extension.
2. In the `data_type` property: if `source_url` is set and non-empty, return `DataType.ZARR`. Otherwise, fall through to extension-based detection (which can also return ZARR for `.nc` files when used with the virtualzarr pipeline specification).

The `file_name` field becomes optional (with a sentinel value like `"virtualzarr.nc"`) when `source_url` is provided, to satisfy the existing `file_name` required constraint without changing the field signature.

**Tradeoff**: Adding `source_url` is a net-new field on `PlatformRequest`. It is the cleanest approach because zarr submissions fundamentally operate on a directory of files, not a single file. Making `file_name` optional would be a wider change with more downstream impact.

---

#### CONFLICT 2.3: Empty File List After Scan (E1)

**What C found**: If the scan finds zero `.nc` files, the spec says "returns empty list (not error)". But then stages 2-3 fan out to zero tasks, and CoreMachine may behave unexpectedly.

**Resolution**: The scan handler checks `file_count == 0` and returns `{"success": False, "error": "No .nc files found matching pattern ..."}`. This fails the task, which fails the job, which is the correct behavior. The spec's "returns empty list" contract is overridden: empty results are an error, not success. The user should fix their `source_url` or `file_pattern`.

**Tradeoff**: Stricter than the spec proposed, but prevents a confusing zero-task fan-out. No downside.

---

#### CONFLICT 2.4: Stage 3 Refs Unused by Stage 4 (C4)

**What C found**: The spec says Stage 4 (combine) takes `nc_urls` (original NetCDF paths), not `ref_urls` (the refs from Stage 3). If combine opens source NetCDFs directly via VirtualiZarr, then Stage 3's individual refs serve no purpose.

**Resolution**: Agent A's rationale ("combine opens source NetCDFs directly") is correct -- VirtualiZarr's `open_virtual_dataset()` works directly on NetCDF files and does not consume pre-generated kerchunk JSON. **Stage 3 (generate individual refs) is removed from V1**. The pipeline becomes 4 stages: Scan, Validate, Combine, Register. The combine stage uses VirtualiZarr to open all source NetCDFs and produce a single combined reference.

Individual per-file refs can be reintroduced as an optional output in V2 if needed for debugging or incremental updates.

**Tradeoff**: Removing a stage simplifies the pipeline significantly (fewer task types, fewer Service Bus messages, less blob storage). The combine stage does slightly more work (opens all NetCDFs, not just reads refs), but the I/O is still header-only. Net positive.

---

#### CONFLICT 2.5: STAC Collection Builder is Raster-Specific (C2, U8)

**What C found**: `build_raster_stac_collection()` in `services/stac_collection.py` is deeply raster-specific -- it references COGs, calculates extents from GeoTIFF metadata, and creates raster-specific STAC properties.

**Resolution**: Do NOT reuse `build_raster_stac_collection()`. The register handler builds its own STAC item dict inline, using zarr-specific properties:

- `xarray:open_kwargs` (storage options, engine, concat_dim)
- Asset href pointing to the combined ref JSON
- Media type `application/json` (for the kerchunk reference)
- `cube:dimensions` if the datacube STAC extension is warranted (deferred to V2)

The STAC collection is created via the existing `PgStacRepository.ensure_collection()` with a minimal collection dict. No new collection builder function is needed for V1.

**Tradeoff**: Inline STAC construction in the handler is less DRY than a shared builder, but zarr STAC items are structurally different from raster STAC items. Premature abstraction would be worse.

---

#### CONFLICT 2.6: Approval Materialization Has No Zarr Path (C, G10, Q3)

**What C found**: `materialize_item()` in `stac_materialization.py` has three code paths: tiled raster, vector (skipped), and single COG. There is no zarr path. The single COG path calls `_inject_titiler_urls()` which builds `/vsiaz/silver-cogs/{blob_path}` URLs -- inappropriate for zarr refs.

**Resolution**: Add a zarr-specific branch in `materialize_item()`. Detection: check if `release.data_type == 'zarr'` (requires adding `data_type` to the Release model, or inferring from `release.blob_path` ending in `.json` within a `refs/` prefix). The zarr materialization path:

1. Copies cached `stac_item_json` from release
2. Patches with versioned ID, collection, B2C approval properties
3. Sanitizes (strips `geoetl:*`)
4. Does NOT inject TiTiler COG URLs
5. Optionally injects TiTiler-xarray URLs if TiTiler-xarray is configured (deferred to V2; for V1, skip tile URL injection)
6. Upserts to pgSTAC

**Tradeoff**: For V1, zarr STAC items will not have tile visualization URLs. They will be discoverable via STAC API and accessible via the xarray API endpoint. TiTiler-xarray URL injection is a V2 feature.

---

#### CONFLICT 2.7: Dimension Mismatch During Combine (E5)

**What C found**: If NetCDF files have different variables, shapes, or coordinate systems, VirtualiZarr's `concat()` will fail with cryptic errors.

**Resolution**: The validate stage (stage 2) collects dimension/variable metadata per file. The combine stage (stage 3) pre-checks that all files share the same variable set and compatible dimension sizes (all dimensions except `concat_dim` must match exactly). If they do not match, the combine stage fails the task with a descriptive error listing the mismatched files and dimensions.

**Tradeoff**: The pre-check adds ~1 second per file (re-read header). Prevents a much more confusing VirtualiZarr traceback. Worth it.

---

### 3. O's Operational Requirements Adding Complexity

#### CONFLICT 3.1: Progress Reporting

**What O requires**: Per-stage progress updates (e.g., "validated 34 of 50 files").

**What it costs**: Requires writing progress to the database from each task. The existing CoreMachine tracks task completion counts via `app.tasks` -- no new mechanism needed. The job status endpoint (`/api/jobs/status/{job_id}`) already returns completed/total task counts per stage.

**Resolution**: No code change. The existing task completion tracking provides sufficient progress visibility. Explicitly document that the job status endpoint shows per-stage progress.

**Justified**: Yes, at zero cost.

---

#### CONFLICT 3.2: ETag Verification for Source Files

**What O requires**: Verify source NetCDF files have not been modified between scan and combine stages.

**What it costs**: Storing ETags at scan time, re-checking at combine time. Adds one HEAD request per file at combine start.

**Resolution**: Deferred to V2. The pipeline already has an invariant that source files are untouched ("read-only with respect to source container"). If a source file is modified mid-pipeline, the combine will either succeed with inconsistent data or fail with a VirtualiZarr error. Both outcomes are acceptable in a dev environment. ETag verification is a production hardening measure.

**Justified**: Not for V1. Low probability in dev, and the failure mode is detectable (resubmit fixes it).

---

#### CONFLICT 3.3: Checkpoint/Resume for Combine

**What O requires**: If the combine stage fails mid-way through a large concatenation, resume from where it left off.

**What it costs**: Significant complexity -- VirtualiZarr's `open_virtual_dataset()` is an in-memory operation. Checkpointing would require serializing partial xarray datasets.

**Resolution**: Deferred. For V1, combine failure = resubmit the job. The combine stage processes headers only (~1MB per file), so even 500 files should complete in <60 seconds. If it OOMs, the issue is the Docker worker memory limit, not the lack of checkpointing.

**Justified**: Not for V1. The cost/benefit ratio is very poor.

---

### 4. C's Concerns Already Addressed by O's Infrastructure

#### CONFLICT 4.1: OOM During Combine (C's E7 + O's F2)

**What C found**: Large/2D curvilinear coordinate variables could cause memory spikes during combine.

**What O found**: Docker worker has ~4GB RAM. VirtualiZarr opens headers only, but xarray may attempt to load coordinate variables into memory during concat.

**Combined resolution**: The validate stage flags files with coordinate variables exceeding a size threshold (e.g., 2D lat/lon arrays > 100MB estimated in-memory). If flagged, the combine stage uses `open_virtual_dataset(loadable_variables=[])` to skip loading coordinate data. The `max_files` cap (500) also limits total memory pressure. If OOM occurs despite these guards, the task fails and the user must reduce the file count.

---

#### CONFLICT 4.2: Blob Throttling During Fan-Out (O's F3)

**What O found**: Fan-out stages create many concurrent blob reads. Azure Blob Storage throttles at ~20,000 requests/second per account, but a single container may throttle earlier.

**What the infrastructure already handles**: Tasks in the `container-tasks` queue are processed sequentially by the single Docker worker. There is no true parallel fan-out -- tasks execute one at a time. Throttling is not a V1 concern.

**Resolution**: No action needed. The single Docker worker serializes all tasks. If a second worker is added in the future, implement exponential backoff on blob reads.

---

#### CONFLICT 4.3: Cold Start (O's F6)

**What O found**: First zarr task after deployment may fail if virtualizarr/kerchunk imports are slow.

**What the infrastructure already handles**: Docker worker startup runs health check before accepting tasks. Import-time failures are caught at startup (F1). Slow imports add to task processing time, not startup time.

**Resolution**: Add `import virtualizarr` and `import kerchunk` to the Docker worker's startup validation. If they fail to import, the health check fails and the container restarts. This is consistent with how GDAL/rasterio imports are validated today.

---

---

## RESOLVED SPEC

### Overview

The VirtualiZarr pipeline is a **4-stage job** that ingests pre-staged NetCDF files from Azure Blob Storage, produces a combined kerchunk reference JSON file, and registers a STAC item on the Release for later approval and materialization.

**Pipeline**: Scan -> Validate -> Combine -> Register STAC

All heavy processing runs on the Docker Worker (`rmhheavyapi`). The Orchestrator handles submit, job creation, and approval. The pipeline follows the existing Job -> Stage -> Task pattern using CoreMachine.

---

### Component 1: DataType Enum Extension

**Responsibility**: Add `ZARR` as a recognized data type throughout the platform model layer.

**Changes Required**:

```python
# core/models/platform.py — DataType enum (line 83)
class DataType(str, Enum):
    RASTER = "raster"
    VECTOR = "vector"
    ZARR = "zarr"              # NEW
    POINTCLOUD = "pointcloud"
    MESH_3D = "mesh_3d"
    TABULAR = "tabular"

# core/models/asset.py — Asset model (line 185)
data_type: Literal["vector", "raster", "zarr"] = Field(
    ...,
    description="Type of geospatial data"
)
```

**PlatformRequest.data_type property** (line 382): Add zarr detection:

```python
@property
def data_type(self) -> DataType:
    # If source_url is provided with virtualzarr pipeline, it's ZARR
    if getattr(self, 'source_url', None):
        return DataType.ZARR

    file_name = self.file_name[0] if isinstance(self.file_name, list) else self.file_name
    ext = file_name.lower().split('.')[-1]

    if ext == 'nc':
        return DataType.ZARR  # Changed from raising ValueError
    # ... rest unchanged
```

**normalize_data_type()** in `services/platform_translation.py`: Add zarr mapping:

```python
def normalize_data_type(data_type: str) -> Optional[str]:
    dt_lower = data_type.lower()
    if dt_lower in ('vector', 'unpublish_vector', 'process_vector'):
        return 'vector'
    if dt_lower in ('raster', 'unpublish_raster', 'process_raster', 'process_raster_v2', 'process_raster_docker'):
        return 'raster'
    if dt_lower in ('zarr', 'virtualzarr'):
        return 'zarr'
    return dt_lower
```

**Error handling**: If `DataType.ZARR` reaches a code path that does not support it (e.g., raster collection routing), raise `ValueError("ZARR data type is only supported with the virtualzarr pipeline")`.

**Operational requirements**: No logging or monitoring changes. This is a model-layer change.

---

### Component 2: ZarrProcessingOptions

**Responsibility**: Typed Pydantic model for zarr-specific processing options submitted at the platform boundary.

**Interface**:

```python
# core/models/processing_options.py — new class

class ZarrProcessingOptions(BaseProcessingOptions):
    """Processing options for VirtualiZarr pipeline."""
    model_config = ConfigDict(extra='ignore')

    pipeline: Literal["virtualzarr"] = Field(
        default="virtualzarr",
        description="Pipeline selector. Must be 'virtualzarr'."
    )
    concat_dim: str = Field(
        default="time",
        description="Dimension to concatenate along"
    )
    file_pattern: str = Field(
        default="*.nc",
        description="Glob pattern for source files"
    )
    fail_on_chunking_warnings: bool = Field(
        default=False,
        description="If True, fail validation on chunking warnings"
    )
    max_files: int = Field(
        default=500,
        ge=1,
        le=5000,
        description="Maximum number of files to process. Caps fan-out."
    )
```

**Registration**: In `PlatformRequest.resolve_processing_options()` (line 319), add:

```python
elif data_type == DataType.ZARR:
    model_cls = ZarrProcessingOptions
```

**Error handling**: Pydantic validation rejects unknown pipeline values, negative max_files, etc. at parse time. Standard `ValidationError` propagation.

**Operational requirements**: None. Model-layer only.

---

### Component 3: PlatformRequest Extension

**Responsibility**: Accept zarr submissions via the existing `/api/platform/submit` endpoint.

**Interface changes to PlatformRequest** (`core/models/platform.py`):

```python
# New optional field (after container_name/file_name)
source_url: Optional[str] = Field(
    default=None,
    max_length=500,
    description="abfs:// URL for source data directory. Required for zarr pipeline."
)

# file_name becomes Optional when source_url is provided
# Validation: model_validator checks that either (container_name + file_name) or source_url is provided
```

**Model validator addition**:

```python
@model_validator(mode='after')
def validate_source_fields(self):
    """Ensure either file_name or source_url is provided."""
    if self.source_url:
        if not self.source_url.startswith('abfs://'):
            raise ValueError("source_url must be an abfs:// path")
        # Default file_name if not provided (sentinel for downstream compat)
        if not self.file_name:
            object.__setattr__(self, 'file_name', 'virtualzarr.nc')
    elif not self.file_name:
        raise ValueError("Either file_name or source_url must be provided")
    return self
```

**Error handling**: `ValueError` on invalid `source_url` format. Pydantic `ValidationError` on missing required fields.

**Operational requirements**: Log `source_url` in the submit flow (same level as container_name/file_name logging).

---

### Component 4: Platform Translation -- Zarr Route

**Responsibility**: Translate a zarr `PlatformRequest` into a `virtualzarr` job with correct parameters.

**Interface** (addition to `translate_to_coremachine()` in `services/platform_translation.py`):

```python
# After the RASTER CREATE block (~line 282), before the closing else

# ========================================================================
# ZARR CREATE -> virtualzarr (VirtualiZarr reference pipeline)
# ========================================================================
elif data_type == DataType.ZARR:
    opts = request.processing_options  # ZarrProcessingOptions

    stac_item_id = platform_cfg.generate_stac_item_id(
        request.dataset_id,
        request.resource_id,
        request.version_id
    )
    collection_id = request.dataset_id  # One collection per dataset

    job_type = 'virtualzarr'

    return job_type, {
        # Source location
        'source_url': request.source_url,
        'file_pattern': opts.file_pattern,
        'concat_dim': opts.concat_dim,
        'fail_on_chunking_warnings': opts.fail_on_chunking_warnings,
        'max_files': opts.max_files,

        # Output location (silver zone)
        'ref_output_prefix': f"refs/{request.dataset_id}/{request.resource_id}",

        # STAC metadata
        'stac_item_id': stac_item_id,
        'collection_id': collection_id,
        'title': request.generated_title,
        'description': request.description,
        'tags': request.tags,
        'access_level': request.access_level.value,

        # DDH identifiers
        'dataset_id': request.dataset_id,
        'resource_id': request.resource_id,
        'version_id': request.version_id,
    }
```

**Error handling**: If `source_url` is missing on a zarr request, raise `ValueError("source_url is required for zarr pipeline")`.

**Operational requirements**: Log `[PLATFORM] Routing zarr ETL to Docker worker (virtualzarr)`.

---

### Component 5: VirtualZarrJob

**Responsibility**: Define the 4-stage job pipeline for VirtualiZarr processing.

**Interface**:

```python
# jobs/virtualzarr.py

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin

class VirtualZarrJob(JobBaseMixin, JobBase):
    """VirtualiZarr NetCDF -> kerchunk reference pipeline."""

    job_type = "virtualzarr"
    description = "Generate virtual Zarr references from NetCDF files"

    stages = [
        {"number": 1, "name": "scan",     "task_type": "virtualzarr_scan",     "parallelism": "single"},
        {"number": 2, "name": "validate", "task_type": "virtualzarr_validate", "parallelism": "fan_out"},
        {"number": 3, "name": "combine",  "task_type": "virtualzarr_combine",  "parallelism": "single"},
        {"number": 4, "name": "register", "task_type": "virtualzarr_register", "parallelism": "single"},
    ]

    parameters_schema = {
        'source_url':       {'type': 'str', 'required': True},
        'file_pattern':     {'type': 'str', 'required': False, 'default': '*.nc'},
        'concat_dim':       {'type': 'str', 'required': False, 'default': 'time'},
        'fail_on_chunking_warnings': {'type': 'bool', 'required': False, 'default': False},
        'max_files':        {'type': 'int', 'required': False, 'default': 500},
        'ref_output_prefix': {'type': 'str', 'required': True},
        'stac_item_id':     {'type': 'str', 'required': True},
        'collection_id':    {'type': 'str', 'required': True},
        'dataset_id':       {'type': 'str', 'required': True},
        'resource_id':      {'type': 'str', 'required': True},
    }

    @staticmethod
    def create_tasks_for_stage(stage_number, job_params, job_id, previous_results=None):
        prefix = job_id[:8]

        if stage_number == 1:
            # Scan: single task
            return [{
                "task_id": f"{prefix}-scan",
                "task_type": "virtualzarr_scan",
                "parameters": {
                    "source_url": job_params['source_url'],
                    "file_pattern": job_params.get('file_pattern', '*.nc'),
                    "max_files": job_params.get('max_files', 500),
                    "ref_output_prefix": job_params['ref_output_prefix'],
                }
            }]

        elif stage_number == 2:
            # Validate: fan-out, one task per file
            # Read manifest from blob (written by scan stage)
            manifest_url = previous_results.get('manifest_url')
            nc_files = _read_manifest(manifest_url)  # Helper reads JSON from blob

            return [{
                "task_id": f"{prefix}-val-{i:04d}",
                "task_type": "virtualzarr_validate",
                "parameters": {
                    "nc_url": nc_url,
                    "fail_on_warnings": job_params.get('fail_on_chunking_warnings', False),
                }
            } for i, nc_url in enumerate(nc_files)]

        elif stage_number == 3:
            # Combine: single task
            manifest_url = previous_results.get('manifest_url')
            return [{
                "task_id": f"{prefix}-combine",
                "task_type": "virtualzarr_combine",
                "parameters": {
                    "manifest_url": manifest_url,
                    "combined_ref_url": f"abfs://rmhazuregeosilver/{job_params['ref_output_prefix']}/combined.json",
                    "concat_dim": job_params.get('concat_dim', 'time'),
                    "dataset_id": job_params['dataset_id'],
                }
            }]

        elif stage_number == 4:
            # Register: single task
            return [{
                "task_id": f"{prefix}-register",
                "task_type": "virtualzarr_register",
                "parameters": {
                    "release_id": job_params.get('release_id'),
                    "dataset_id": job_params['dataset_id'],
                    "resource_id": job_params['resource_id'],
                    "collection_id": job_params['collection_id'],
                    "stac_item_id": job_params['stac_item_id'],
                    "combined_ref_url": f"abfs://rmhazuregeosilver/{job_params['ref_output_prefix']}/combined.json",
                    "title": job_params.get('title'),
                    "description": job_params.get('description'),
                    "tags": job_params.get('tags', []),
                    "access_level": job_params.get('access_level', 'OUO'),
                }
            }]
```

**Error handling**: `create_tasks_for_stage` raises `ValueError` if `manifest_url` is missing from `previous_results` (contract violation -- scan stage must produce it). Fan-out with zero files is a scan-stage failure, not a job-level issue.

**Operational requirements**: Job creation logged by CoreMachine. No custom logging needed.

**Registration** (two files):

1. `jobs/__init__.py`: Add `from jobs.virtualzarr import VirtualZarrJob` and register in `JOB_REGISTRY`.
2. `services/__init__.py`: Add handler registrations (see Component 6).

---

### Component 6: Task Handlers (`services/handler_virtualzarr.py`)

**Responsibility**: Four handler functions that execute the actual VirtualiZarr work on the Docker worker.

#### 6.1 `virtualzarr_scan(params, context) -> dict`

Scans a blob container prefix for NetCDF files.

```python
def virtualzarr_scan(params: dict, context: dict = None) -> dict:
    """
    Scan source_url for .nc files matching file_pattern.

    Writes file list to blob manifest (avoids Service Bus size limit).

    Args:
        params:
            source_url (str): abfs:// path to container/prefix
            file_pattern (str): glob pattern, default "*.nc"
            max_files (int): maximum files to include, default 500
            ref_output_prefix (str): silver zone prefix for output

    Returns:
        {"success": True, "result": {"manifest_url": "abfs://...", "file_count": N, "total_size_bytes": N}}

    Errors:
        - source_url not accessible -> {"success": False, "error": "Cannot access source_url: ..."}
        - zero files found -> {"success": False, "error": "No .nc files found ..."}
        - exceeds max_files -> {"success": False, "error": "Found N files, exceeds max_files=M ..."}
    """
```

**Implementation notes**:
- Use `adlfs.AzureBlobFileSystem` with `DefaultAzureCredential` (Managed Identity).
- Parse `source_url` to extract account, container, prefix.
- List blobs with prefix, filter by `file_pattern` using `fnmatch`.
- Sort alphabetically.
- Enforce `max_files` cap.
- Write manifest JSON to `abfs://rmhazuregeosilver/{ref_output_prefix}/manifest.json`.
- Return `manifest_url` in result.

**Logging**: INFO: source_url, file_pattern, file_count, total_size_bytes, manifest_url.

---

#### 6.2 `virtualzarr_validate(params, context) -> dict`

Validates a single NetCDF file's chunking suitability.

```python
def virtualzarr_validate(params: dict, context: dict = None) -> dict:
    """
    Validate NetCDF internal chunking for VirtualiZarr compatibility.

    Args:
        params:
            nc_url (str): abfs:// path to a single .nc file
            fail_on_warnings (bool): if True, warnings become errors

    Returns:
        {"success": True, "result": {"nc_url": "...", "status": "success|warning", "variables": {...}, "dimensions": {...}, "warnings": [...]}}

    Errors:
        - file not readable -> {"success": False, "error": "Cannot read ..."}
        - not HDF5 format -> {"success": False, "error": "File is not HDF5/NetCDF4 ..."}
        - fail_on_warnings=True and warnings present -> {"success": False, "error": "Chunking warnings: ..."}
    """
```

**Implementation notes**:
- Use `h5py.File` with `fsspec` file-like object (header-only read).
- For each variable: extract shape, dtype, chunks (HDF5 chunk layout), compression.
- **Chunking warnings** (well-defined criteria):
  - WARNING: Variable has no HDF5 chunking (contiguous layout) -- VirtualiZarr works but performance may suffer.
  - WARNING: Chunk size > 100MB -- may cause memory issues during access.
  - WARNING: 2D coordinate variable with total size > 50MB -- flag for combine stage.
  - ERROR: File is NetCDF3/Classic format (no HDF5 layer) -- cannot virtualize.

**Logging**: INFO: nc_url, variable count, dimension summary, warning count.

---

#### 6.3 `virtualzarr_combine(params, context) -> dict`

Combines multiple NetCDF files into a single virtual Zarr reference.

```python
def virtualzarr_combine(params: dict, context: dict = None) -> dict:
    """
    Open all source NetCDFs via VirtualiZarr and produce combined reference.

    Args:
        params:
            manifest_url (str): abfs:// path to manifest JSON with file list
            combined_ref_url (str): abfs:// path to write combined reference JSON
            concat_dim (str): dimension to concatenate along (e.g., "time")
            dataset_id (str): for logging

    Returns:
        {"success": True, "result": {"combined_ref_url": "...", "source_files": N,
         "dimensions": {...}, "variables": [...], "time_range": [...], "spatial_extent": [...]}}

    Errors:
        - manifest not readable -> {"success": False, "error": "Cannot read manifest ..."}
        - dimension mismatch -> {"success": False, "error": "Dimension mismatch: file X has lat=360, file Y has lat=720"}
        - VirtualiZarr error -> {"success": False, "error": "VirtualiZarr failed: ..."}
        - OOM -> process killed (Docker restarts; job marked FAILED by timeout)
    """
```

**Implementation notes**:
- Read manifest from blob to get list of nc_urls.
- Pre-check: open first file, record variable names and non-concat dimension sizes. Open each subsequent file and verify match. Fail fast on mismatch.
- Use `virtualizarr.open_virtual_dataset(nc_url, indexes={})` for each file. The `indexes={}` skips loading coordinate data (memory-safe).
- Concatenate with `xarray.concat(virtual_datasets, dim=concat_dim)`.
- Export with `combined.virtualize.to_kerchunk(combined_ref_url, format="json")`.
- Extract metadata:
  - `time_range`: from concat_dim coordinate min/max (if parseable as datetime).
  - `spatial_extent`: from lat/lon coordinate variables min/max.
  - `dimensions`: from combined dataset `.dims`.
  - `variables`: data variable names (exclude coordinates).

**Logging**: INFO: file count, concat_dim, combined ref size, dimension summary, time_range, spatial_extent.

---

#### 6.4 `virtualzarr_register(params, context) -> dict`

Builds STAC item dict and caches it on the Release.

```python
def virtualzarr_register(params: dict, context: dict = None) -> dict:
    """
    Build zarr STAC item and cache on Release.

    Args:
        params:
            release_id (str): Release to update
            dataset_id, resource_id, collection_id, stac_item_id (str): identifiers
            combined_ref_url (str): abfs:// path to combined reference
            title, description (str): metadata
            tags (list): tags
            access_level (str): OUO or public

            # Passed from combine stage via previous_results:
            dimensions (dict): {dim_name: size}
            variables (list): data variable names
            time_range (list): [start_iso, end_iso] or None
            spatial_extent (list): [west, south, east, north]

    Returns:
        {"success": True, "result": {"stac_item_cached": True, "release_updated": True, "blob_path": "..."}}

    Errors:
        - release_id not found -> {"success": False, "error": "Release not found: ..."}
        - database error -> {"success": False, "error": "Failed to update release: ..."}
    """
```

**STAC item structure**:

```python
stac_item = {
    "type": "Feature",
    "stac_version": "1.0.0",
    "id": stac_item_id,
    "collection": collection_id,
    "geometry": {
        "type": "Polygon",
        "coordinates": [[[w,s],[e,s],[e,n],[w,n],[w,s]]]
    },
    "bbox": [west, south, east, north],
    "properties": {
        "title": title,
        "description": description,
        "datetime": None,  # Use start/end instead
        "start_datetime": time_range[0] if time_range else None,
        "end_datetime": time_range[1] if time_range else None,
        "geoetl:data_type": "zarr",
        "geoetl:pipeline": "virtualzarr",
        "xarray:open_kwargs": {
            "engine": "kerchunk",
            "storage_options": {"fo": combined_ref_url},
            "chunks": {},
        },
        **{f"geoetl:tag:{t}": True for t in tags},
    },
    "assets": {
        "reference": {
            "href": combined_ref_url,
            "type": "application/json",
            "title": "Kerchunk Reference (Combined)",
            "roles": ["data"],
            "xarray:open_kwargs": {
                "engine": "kerchunk",
                "chunks": {},
            }
        }
    },
    "links": []
}
```

**Release updates** (via repository methods):
1. `release_repo.update_stac_item_json(release_id, stac_item)` -- cache STAC dict
2. `release_repo.update_physical_outputs(release_id, blob_path=ref_blob_path)` -- set blob_path to the silver-zone relative path of the combined ref
3. `release_repo.update_processing_status(release_id, "completed")` -- mark done

**Logging**: INFO: release_id, stac_item_id, collection_id, blob_path.

---

### Component 7: Task Routing Registration

**Responsibility**: Register the 4 virtualzarr task types so CoreMachine routes them to the Docker worker.

**Changes**:

```python
# config/defaults.py — TaskRoutingDefaults.DOCKER_TASKS

DOCKER_TASKS = frozenset([
    # ... existing tasks ...

    # =====================================================================
    # VIRTUALZARR PIPELINE (V0.9.x)
    # =====================================================================
    "virtualzarr_scan",
    "virtualzarr_validate",
    "virtualzarr_combine",
    "virtualzarr_register",
])
```

**Error handling**: Unmapped task types raise `ContractViolationError`. Adding to `DOCKER_TASKS` ensures routing.

**Operational requirements**: None beyond the registration.

---

### Component 8: Docker Dependencies

**Responsibility**: Add VirtualiZarr and kerchunk to the Docker image.

**Changes to `requirements-docker.txt`**:

```
# === VirtualiZarr Pipeline (V0.9.x) ===
virtualizarr>=1.0,<2.0
kerchunk>=0.2.6,<0.3.0
h5py>=3.10.0,<4.0
```

Note: `h5py` is explicitly listed even though it may be a transitive dependency, to pin the version and ensure numpy 1.x compatibility.

**Startup validation**: In `docker_service.py` startup, add import check:

```python
try:
    import virtualizarr
    import kerchunk
    import h5py
    logger.info(f"VirtualiZarr {virtualizarr.__version__}, kerchunk {kerchunk.__version__}, h5py {h5py.__version__}")
except ImportError as e:
    logger.error(f"STARTUP_FAILED: VirtualiZarr dependency missing: {e}")
    # Allow startup to continue (other pipelines still work)
    # but virtualzarr tasks will fail with clear import error
```

**Error handling**: If import fails at task execution time, return `{"success": False, "error": "virtualizarr not installed: ..."}`.

**Operational requirements**: Log library versions at startup. If HDF5 library conflicts arise with GDAL's bundled HDF5, the Docker build will fail -- this surfaces at build time, not runtime.

---

### Component 9: STAC Materialization -- Zarr Branch

**Responsibility**: Materialize zarr STAC items to pgSTAC at approval time.

**Changes to `services/stac_materialization.py`, `materialize_item()` method**:

```python
def materialize_item(self, release, reviewer, clearance_state):
    now_iso = datetime.now(timezone.utc).isoformat()

    # TILED OUTPUT
    if release.output_mode == 'tiled':
        return self._materialize_tiled_items(release, reviewer, clearance_state, now_iso)

    # VECTOR RELEASES
    if not release.blob_path and not release.stac_item_json:
        # ... existing vector skip logic ...

    # ZARR RELEASES (NEW)
    if release.stac_item_json and self._is_zarr_release(release):
        return self._materialize_zarr_item(release, reviewer, clearance_state, now_iso)

    # SINGLE COG OUTPUT (existing)
    # ... rest unchanged ...
```

**New method**:

```python
def _is_zarr_release(self, release) -> bool:
    """Detect zarr release from cached STAC properties."""
    if not release.stac_item_json:
        return False
    props = release.stac_item_json.get('properties', {})
    return props.get('geoetl:data_type') == 'zarr'

def _materialize_zarr_item(self, release, reviewer, clearance_state, now_iso):
    """Materialize zarr STAC item to pgSTAC (no TiTiler URL injection)."""
    stac_item_json = dict(release.stac_item_json)

    # Patch with versioned ID and collection
    versioned_id = release.stac_item_id
    stac_item_json['id'] = versioned_id
    stac_item_json['collection'] = release.stac_collection_id

    # Patch title and self-link
    props = stac_item_json.setdefault('properties', {})
    if versioned_id:
        props['title'] = versioned_id

    # Add B2C approval properties
    props['ddh:approved_by'] = reviewer
    props['ddh:approved_at'] = now_iso
    props['ddh:access_level'] = clearance_state.value
    if release.version_id:
        props['ddh:version_id'] = release.version_id

    # Sanitize: strip geoetl:* properties
    self.sanitize_item_properties(stac_item_json)

    # NO TiTiler URL injection for zarr (V1)
    # TiTiler-xarray integration is a V2 feature

    # Upsert to pgSTAC
    pgstac_id = self.pgstac.insert_item(stac_item_json, release.stac_collection_id)
    logger.info(f"Materialized zarr STAC item {versioned_id} in collection {release.stac_collection_id}")

    return {'success': True, 'pgstac_id': pgstac_id}
```

**Error handling**: Same as existing single COG path -- `insert_item` failure returns `{"success": False, "error": "..."}`.

**Operational requirements**: Log materialization. No new metrics.

---

### Component 10: Approval Service Fix

**Responsibility**: Fix `data_type` inference in `asset_approval_service.py` to handle zarr.

**Current code** (line 645):
```python
'data_type': 'raster' if release.blob_path else 'vector',
```

**Fix**: Use the asset's `data_type` field (which is set at creation time from the PlatformRequest):

```python
# Look up asset to get authoritative data_type
from infrastructure import AssetRepository
asset = AssetRepository().get_by_id(release.asset_id)
data_type = asset.data_type if asset else ('raster' if release.blob_path else 'vector')
```

Or, simpler and sufficient for V1: check the cached STAC item:

```python
data_type = 'vector'
if release.blob_path:
    if release.stac_item_json and release.stac_item_json.get('properties', {}).get('geoetl:data_type') == 'zarr':
        data_type = 'zarr'
    else:
        data_type = 'raster'
```

**Tradeoff**: The asset lookup is more correct but adds a DB query. The STAC property check is sufficient for V1 and avoids the extra query.

---

### Component 11: Submit Flow -- Zarr Ordinal Finalization

**Responsibility**: Handle ordinal-based name finalization for zarr submissions in `triggers/platform/submit.py`.

**Changes** (after the raster ordinal finalization block, ~line 370):

```python
elif platform_req.data_type.value == 'zarr':
    # Zarr: finalize stac_item_id and ref output prefix
    final_stac = generate_stac_item_id(
        platform_req.dataset_id, platform_req.resource_id,
        version_ordinal=ordinal
    )
    job_params['stac_item_id'] = final_stac

    # Update ref output prefix to include ordinal
    job_params['ref_output_prefix'] = f"refs/{platform_req.dataset_id}/{platform_req.resource_id}/ord{ordinal}"

    asset_service.update_physical_outputs(
        release.release_id, stac_item_id=final_stac
    )
    logger.info(f"  Finalized zarr stac_item_id: {final_stac} (ord={ordinal})")
```

---

## DEFERRED DECISIONS

### D1: TiTiler-xarray URL Injection

**What**: Inject TiTiler-xarray tile server URLs into STAC items at materialization time (similar to COG TiTiler URLs).

**Why it can wait**: TiTiler-xarray may not be deployed or configured. The zarr data is accessible via the xarray API endpoint (`/api/xarray/*`) and directly via the reference URL. Tile visualization is a nice-to-have, not a requirement for V1.

**Trigger to revisit**: When TiTiler-xarray is deployed and accessible at a known URL, add `_inject_titiler_xarray_urls()` to the zarr materialization path.

---

### D2: ETag Verification

**What**: Verify source NetCDF files have not been modified between scan and combine stages.

**Why it can wait**: In a dev environment, source files are pre-staged and rarely modified. The window between scan and combine is typically minutes.

**Trigger to revisit**: Production deployment, or a user report of data inconsistency in a combined reference.

---

### D3: Checkpoint/Resume for Combine

**What**: Resume combine stage from a partial state after failure.

**Why it can wait**: Combine processes headers only and should complete in <60 seconds for 500 files. Retry = resubmit the job.

**Trigger to revisit**: When datasets routinely exceed 1000 files, or combine stage regularly OOMs.

---

### D4: datacube STAC Extension

**What**: Add `cube:dimensions` and `cube:variables` to STAC items per the datacube STAC extension spec.

**Why it can wait**: The base STAC item with `xarray:open_kwargs` is sufficient for xarray access. The datacube extension adds discoverability for clients that understand it, but no current consumer requires it.

**Trigger to revisit**: When STAC API consumers (e.g., STAC browser, external clients) need to query by dimension or variable.

---

### D5: Partial Failure and Cleanup

**What**: If a job fails mid-pipeline, clean up intermediate artifacts (manifest, partial refs).

**Why it can wait**: Intermediate artifacts are small JSON files (<1MB each) in silver storage. Accumulation is negligible for dev. A periodic cleanup job (already exists: `action=cleanup`) can be extended to cover orphaned refs.

**Trigger to revisit**: When silver storage costs become meaningful, or when orphaned refs cause confusion.

---

### D6: Independent Queue for Zarr Tasks

**What**: Route zarr tasks to a dedicated Service Bus queue instead of sharing `container-tasks`.

**Why it can wait**: Dev environment has low task volume. The `max_files` cap (500) limits fan-out. No contention observed.

**Trigger to revisit**: When zarr and raster/vector jobs run concurrently at scale and cause queue starvation.

---

### D7: numpy 2 Migration

**What**: Upgrade to numpy >= 2.0 across the Docker image, enabling newer VirtualiZarr/kerchunk versions.

**Why it can wait**: Current pinned versions (VirtualiZarr 1.x, kerchunk 0.2.x) work with numpy 1.x. No feature is blocked.

**Trigger to revisit**: When VirtualiZarr drops numpy 1.x support, or when numpy 2.x features are needed.

---

### D8: Per-File Reference Output (Stage 3 Reintroduction)

**What**: Generate and persist individual per-file kerchunk reference JSON files (the removed Stage 3).

**Why it can wait**: The combined reference is the only artifact needed for access. Per-file refs are useful for debugging and incremental updates, but not required for V1.

**Trigger to revisit**: When incremental dataset updates are needed (add files to an existing combined ref without re-processing all files).

---

### D9: Non-Standard Calendar Handling

**What**: Handle NetCDF files with non-standard calendars (noleap, 360_day, julian) in time coordinate extraction.

**Why it can wait**: VirtualiZarr does not interpret time values -- it just references byte ranges. The combine stage extracts `time_range` for STAC metadata, which may produce incorrect ISO dates for non-standard calendars. This affects STAC discoverability, not data access.

**Trigger to revisit**: When climate model data with non-standard calendars is submitted and time-based STAC queries return wrong results.

---

## RISK REGISTER

### R1: VirtualiZarr numpy 1.x Compatibility

**Description**: VirtualiZarr 1.x may not be compatible with numpy < 2.0. The pip install could fail or produce runtime errors.

**Likelihood**: MEDIUM (VirtualiZarr targets numpy 2.x but may still support 1.x)

**Impact**: HIGH (blocks the entire pipeline -- cannot build Docker image)

**Mitigation**: Test `pip install virtualizarr kerchunk` with `numpy<2` in an isolated Docker build before writing any handler code. If incompatible, fall back to VirtualiZarr 0.x or accept numpy 2 migration as a prerequisite.

---

### R2: HDF5 Library Conflict in GDAL Docker Image

**Description**: The GDAL base image (`ubuntu-full-3.10.1`) bundles its own HDF5 libraries. Installing `h5py` via pip may link against a different HDF5 version, causing segfaults or import errors.

**Likelihood**: LOW (pip h5py ships binary wheels with bundled HDF5, isolated from system HDF5)

**Impact**: HIGH (segfault at runtime, all zarr tasks fail)

**Mitigation**: Test Docker build and run `python3 -c "import h5py; print(h5py.version.hdf5_version)"` in CI. If conflict exists, use `h5py` built against the system HDF5 via `pip install --no-binary h5py`.

---

### R3: VirtualiZarr API Instability

**Description**: VirtualiZarr is a young library (< 2 years old). The `open_virtual_dataset()` API and `.virtualize.to_kerchunk()` method may change between minor versions.

**Likelihood**: MEDIUM (active development, API still evolving)

**Impact**: MEDIUM (combine handler breaks, requires code update)

**Mitigation**: Pin VirtualiZarr to a specific minor version (e.g., `>=1.0,<1.1`). Wrap VirtualiZarr calls in a thin adapter module (`services/virtualzarr_adapter.py`) that isolates API-specific code. If the API changes, only the adapter needs updating.

---

### R4: Memory Exhaustion During Combine

**Description**: xarray's `concat()` on 500 virtual datasets may exceed 4GB if coordinate variables are loaded into memory.

**Likelihood**: LOW (using `indexes={}` prevents coordinate loading)

**Impact**: HIGH (OOM kills Docker worker, all in-flight tasks lost)

**Mitigation**: Use `indexes={}` in `open_virtual_dataset()`. Cap `max_files` at 500. Monitor Docker worker memory via Application Insights. If OOM occurs, reduce `max_files` or upgrade App Service plan.

---

### R5: abfs:// URL Scheme Incompatibility

**Description**: The spec uses `abfs://` URLs. Some Azure libraries expect `az://` or `https://*.blob.core.windows.net/` schemes. VirtualiZarr's fsspec backend must correctly resolve `abfs://` to Azure Blob Storage.

**Likelihood**: LOW (adlfs/fsspec standardize on `abfs://`)

**Impact**: MEDIUM (scan or combine stage fails with "unsupported scheme")

**Mitigation**: Validate URL scheme at submit time (reject non-`abfs://`). In the scan handler, test blob access before iterating (early fail with clear error). Document that `abfs://` is the only supported scheme.

---

### R6: Shared Queue Starvation

**Description**: A large zarr fan-out (500 validate tasks) could block raster/vector tasks in the `container-tasks` queue for the entire validation duration.

**Likelihood**: LOW (dev environment, low concurrent workload)

**Impact**: MEDIUM (raster/vector jobs delayed by 15+ minutes)

**Mitigation**: The `max_files` cap limits fan-out size. If this becomes a problem, implement priority-based dequeuing or a separate zarr queue (D6). For V1, accept the risk.

---

### R7: Alphabetical Ordering != Temporal Ordering

**Description**: The scan stage sorts files alphabetically. If file names do not encode temporal order (e.g., `file_001.nc` vs `tas_2020.nc`), the combined reference may have incorrect time ordering.

**Likelihood**: MEDIUM (depends on user's naming convention)

**Impact**: LOW (data is still accessible, but time-series queries return data in wrong order)

**Mitigation**: Document that file names must sort chronologically. The validate stage logs file order. The combine stage sets `concat_dim` order from file ordering. If users need custom ordering, they can rename files or a future version can add an explicit `sort_by` parameter.

---

### R8: Kerchunk JSON Format Compatibility

**Description**: VirtualiZarr may produce kerchunk JSON that is incompatible with the version of fsspec/zarr deployed on TiTiler-xarray or the xarray API endpoint.

**Likelihood**: LOW (kerchunk JSON format is relatively stable)

**Impact**: HIGH (combined reference cannot be opened by consumers)

**Mitigation**: After producing the combined reference, the combine handler performs a validation read: `xr.open_zarr(combined_ref_url)` to confirm the reference resolves. If validation fails, the task fails with a clear error. This adds ~5 seconds but catches format incompatibility at pipeline time, not discovery time.
