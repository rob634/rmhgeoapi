# Agent O (Operator) Review: VirtualiZarr NetCDF Pipeline

**Reviewed by**: Agent O (Claude, 27 FEB 2026)
**Spec reviewed**: `GREENSIGHT_VIRTUALZARR_SPEC.md`
**Status**: OPERATOR ASSESSMENT

---

## INFRASTRUCTURE FIT

### Good Fit

1. **Header-only I/O matches the Docker worker profile well.** The spec claims ~1MB I/O per file for reference generation and header-only reads for validation. This is dramatically lighter than the raster COG pipeline that processes full pixel data. The 4GB RAM on P0v3 is more than sufficient for this workload — there is no decompression of the full dataset, no pixel-level reprojection, no GDAL temp files.

2. **The Job/Stage/Task pattern is a natural fit.** The 5-stage sequential pipeline (Scan -> Validate -> Generate Refs -> Combine -> Register STAC) maps cleanly to the existing CoreMachine stage progression model. The fan-out at Stage 2 (validate each file) and Stage 3 (generate ref per file) mirrors the existing tiled raster fan-out pattern.

3. **Blob storage auth via Managed Identity is already solved.** The Docker worker uses `AZURE_STORAGE_AUTH_TYPE=AZURE_AD` for all `rasterio` operations, and `adlfs` + `fsspec` are already in the image with DefaultAzureCredential support. The spec correctly references `abfs://` paths and Managed Identity.

4. **Service Bus queue routing already handles new task types.** Adding new task types to `TaskRoutingDefaults.DOCKER_TASKS` is a one-line change per task type, and the startup validation in `services/__init__.py` will catch any misregistration immediately at import time.

### Constraints the Spec Does Not Acknowledge

1. **`data_type="zarr"` does not exist in the DataType enum.** The spec says to submit with `data_type: "zarr"` but the `DataType` enum in `core/models/platform.py` (line 83-93) only has RASTER, VECTOR, POINTCLOUD, MESH_3D, and TABULAR. The `translate_to_coremachine()` function in `services/platform_translation.py` has explicit `if data_type == DataType.VECTOR` / `elif data_type == DataType.RASTER` branches and falls through to `raise ValueError("Unsupported data type")`. Adding `"zarr"` requires modifications across at least 8-10 files that switch on data_type — this is NOT a simple addition. The `normalize_data_type()` function also only knows about "vector" and "raster" variants.

2. **The Docker image uses `numpy<2` pinning.** VirtualiZarr and recent versions of zarr (v3+) may require or strongly prefer numpy>=2. The `requirements-docker.txt` explicitly pins `numpy<2` with a comment about C-extension ABI compatibility. This could cause version conflicts during pip resolution that block the Docker image build entirely.

3. **P0v3 is a single-core plan.** The spec does not mention CPU, but VirtualiZarr's `open_virtual_dataset()` and kerchunk reference generation can be CPU-intensive for coordinate parsing and JSON serialization. With 1 vCPU per instance and 4 instances, each instance can only process one task at a time. If the Docker worker is also servicing raster/vector tasks on the same queue (`container-tasks`), a batch of 50 VirtualiZarr files will monopolize the worker pool.

4. **Service Bus message size limit: 256KB.** The spec's Stage 3 output (per-file reference metadata) is small, but Stage 4 (Combine) receives `nc_urls` — a list of all file paths from Stage 1. For 10,000 files (the stated scan limit), the file path list alone could approach or exceed 256KB depending on path length. The task parameters for the combine stage must fit in a single Service Bus message.

5. **The Dockerfile base image is GDAL-focused (`ghcr.io/osgeo/gdal:ubuntu-full-3.10.1`).** VirtualiZarr and kerchunk are pure-Python packages that do not need GDAL. Adding them increases the Docker image size and build time, but more critically, they pull in their own dependency trees that may conflict with the GDAL image's pre-installed system packages (particularly HDF5 C libraries). The GDAL image ships its own libhdf5; kerchunk/h5py might link against a different version.

### Infrastructure Capabilities the Spec Could Use But Does Not Mention

1. **Azure Files mount (`/mounts/etl-temp`).** The Docker worker has an Azure Files mount configured (`DockerDefaults.ETL_MOUNT_PATH = "/mounts/etl-temp"`). For the Combine stage, writing intermediate combined references to the mount instead of holding them in memory would provide resilience against OOM on very large reference sets. The spec does not mention local scratch storage.

2. **Checkpoint/Resume framework.** The existing Docker handlers (`process_raster_complete`, `vector_docker_complete`) all use a phase-based checkpoint/resume pattern with `DockerTaskContext`. The spec describes a multi-stage pipeline but does not mention checkpointing within the Combine stage, which is the most likely place for a long-running failure.

3. **Progress reporting for Workflow Monitor.** Existing handlers report phase progress via `docker_context.report_progress()`. The spec does not mention progress reporting, which would be critical for operators monitoring a 50-file pipeline running for 15 minutes.

---

## DEPLOYMENT REQUIREMENTS

### New Dependencies to Add

| Package | Where | Risk |
|---------|-------|------|
| `virtualizarr` | `requirements-docker.txt` | Not yet installed; API stability unknown; numpy compatibility unverified |
| `kerchunk` | `requirements-docker.txt` | May conflict with system HDF5 in GDAL base image |

**Neither package is currently installed in any environment.** They need to be tested in the actual Docker image (`ghcr.io/osgeo/gdal:ubuntu-full-3.10.1`) before any code is written. A pip install that succeeds locally on macOS may fail in the Docker image due to HDF5 header mismatches.

### Configuration Changes Required

1. **`DataType` enum**: Add `ZARR = "zarr"` to `core/models/platform.py`
2. **`normalize_data_type()`**: Add zarr recognition to `services/platform_translation.py`
3. **`translate_to_coremachine()`**: Add `elif data_type == DataType.ZARR:` branch
4. **`TaskRoutingDefaults.DOCKER_TASKS`**: Add all 5 new task type strings (scan, validate, generate_ref, combine, register_zarr_stac)
5. **`ALL_HANDLERS`** in `services/__init__.py`: Register all 5 handlers
6. **`ALL_JOBS`** in `jobs/__init__.py`: Register the new job class
7. **`STACDefaults`**: No container for refs currently defined. Need a refs output path convention.
8. **Asset/Release approval flow**: The `asset_approval_service.py` line 645 infers `data_type` from `blob_path vs table_name` — zarr releases have a blob_path (the combined ref JSON) but are NOT raster. This logic will misclassify zarr as raster.

### Database Migrations

None required. The existing Asset/Release tables and `stac_item_json` caching mechanism support this pipeline without schema changes. The spec correctly leverages `update_stac_item_json()` and the existing approval workflow.

### Rollback Plan

- **Docker image rollback**: Revert to previous Docker tag in ACR. The deploy script tags images with version numbers (`geospatial-worker:0.9.8.1`), so rollback is `az webapp config container set --docker-custom-image-name "rmhazureacr.azurecr.io/geospatial-worker:PREVIOUS_VERSION"`.
- **Code rollback**: The new handlers, job class, and task routing entries are all additive. Removing them from the registries and reverting `requirements-docker.txt` fully rolls back.
- **No database migration to reverse** — this is a clean deployment property.

### Zero-Downtime Deployment

**Yes, possible.** The Docker worker runs on Azure App Service with 4 instances. Deployment uses slot-based or rolling container updates. New task types will fail with "Unknown task type" on old instances until they receive the new image, but this is non-destructive — CoreMachine retries the task when it hits the new instance. However, during the rolling update window (60-120 seconds), a task could be picked up by an old instance, fail, and consume a retry.

---

## FAILURE MODES

### F1: VirtualiZarr/Kerchunk Import Failure at Container Start

**Trigger**: pip install succeeds but import fails at runtime due to HDF5 library mismatch between GDAL base image and h5py/kerchunk expectations.

**Detection**: Docker worker health check (`/livez`) passes (FastAPI starts), but readiness check (`/readyz`) may also pass since handler registration is lazy. The failure surfaces only when the first VirtualiZarr task runs — the handler `import virtualizarr` raises `ImportError`.

**Blast radius**: Only VirtualiZarr tasks fail. All raster/vector tasks continue working.

**Recovery**: Fix the dependency conflict in `requirements-docker.txt`, rebuild the Docker image, redeploy. Re-submit the failed job.

**Mitigation**: Add a startup-time import check in the handler module (like the existing `validate_handler_registry()`). If `import virtualizarr` fails at import time, the service should log `STARTUP_FAILED: virtualizarr` and exclude those handlers, rather than silently registering broken handlers.

### F2: Memory Exhaustion During Combine Stage

**Trigger**: The Combine stage loads multiple VirtualiZarr `ManifestArray` objects and concatenates them in memory. For datasets with many variables and high-resolution coordinate arrays, memory usage could exceed 4GB.

**Detection**: Container OOM kill. The Azure App Service platform restarts the container. The task that was running gets stuck in PROCESSING state because the process died before marking it FAILED.

**Blast radius**: The container restart kills ALL in-flight tasks on that instance, not just the VirtualiZarr task. Any raster or vector task running concurrently on the same instance is also killed.

**Recovery**: CoreMachine does not automatically retry tasks after OOM. The orphaned PROCESSING tasks must be manually failed or the job re-submitted. Consider the `cleanup` maintenance action for stuck tasks.

**Mitigation**: The Combine stage should implement chunked concatenation or use the Azure Files mount as scratch space. Set explicit memory limits and fail gracefully before OOM kill.

### F3: Azure Blob Storage Throttling During Fan-Out

**Trigger**: Stage 3 (Generate Reference) fans out to N parallel tasks, each making byte-range GET requests to Azure Blob Storage. For 50+ files, this creates a burst of concurrent storage requests. Azure Blob Storage throttles at ~20,000 requests/second per storage account, which is unlikely to hit, but throttling at the network interface level (App Service outbound connections) is more realistic.

**Detection**: Tasks fail with `azure.core.exceptions.ServiceResponseError` or `requests.ConnectionError`. Task failure is logged in Application Insights.

**Blast radius**: Individual task failures. CoreMachine marks the job as FAILED when any task in a stage fails (per the spec's "no partial results" invariant).

**Recovery**: Re-submit the job. The reference files from successful tasks are already written (idempotent).

### F4: Source NetCDF File Modified During Pipeline Execution

**Trigger**: Someone uploads a new version of a NetCDF file to the bronze container while the pipeline is running. The Scan stage found the file, the Validate stage read its headers, but the Generate Reference stage reads different headers because the file changed.

**Detection**: The generated reference points to byte offsets that no longer correspond to valid HDF5 chunks. This produces a silently corrupt reference file. Detection requires downstream validation (xarray open + data read).

**Blast radius**: The combined reference is invalid. TiTiler-xarray or any xarray client reading the virtual Zarr store will get corrupt data or read errors.

**Recovery**: Re-run the pipeline after the source files are stable. There is no automated detection.

**Mitigation**: The Scan stage should record file ETags or modification timestamps. The Generate Reference stage should verify the ETag matches before generating the reference. If it does not match, fail the task with a clear error.

### F5: Service Bus Message Exceeding 256KB

**Trigger**: A container with thousands of NetCDF files produces a file list that exceeds the 256KB Service Bus message limit when passed as task parameters to Stage 4 (Combine).

**Detection**: `azure.servicebus.exceptions.MessageSizeExceededError` when CoreMachine tries to enqueue the Combine task.

**Blast radius**: The job hangs in PROCESSING state at stage transition. The Combine task is never created. No automatic recovery.

**Recovery**: Manual intervention to fail the job. Re-design to use fan-in database references (like the existing `fan_in_source` pattern) instead of passing file lists in message parameters.

**Mitigation**: This is a known pattern in the codebase — `core/fan_in.py` exists specifically for this. The Combine stage MUST use database-based fan-in, not message-carried file lists. The spec should mandate this.

### F6: Cold Start After Scale-to-Zero

**Trigger**: Azure App Service with P0v3 does not scale to zero by default, but if the container crashes and restarts, the first task hits a cold instance where the Python process, h5py, and Azure identity token are all initializing.

**Detection**: The first task after restart takes significantly longer (30-60 seconds for container start + 15-20 seconds for identity token acquisition). If the task has a tight timeout, it may fail.

**Blast radius**: Single task failure.

**Recovery**: Automatic — the container restart completes and subsequent tasks succeed.

---

## OBSERVABILITY

### What Must Be Logged

1. **Scan stage**: Container path, file count, total size in bytes, time taken. This is the first indication of pipeline scale.
2. **Validate stage (per file)**: File path, chunk layout summary, any warnings, recommendation (suitable/unsuitable), time taken. Validation failures must include the specific chunking issue (e.g., "no internal chunks — single chunk larger than file").
3. **Generate Reference stage (per file)**: File path, output ref path, ref size bytes, time taken. Log the VirtualiZarr/kerchunk version used.
4. **Combine stage**: Number of source files, concat dimension, combined dimensions, combined ref size, time taken, peak memory usage.
5. **Register STAC stage**: Release ID, STAC item properties cached, blob_path set on Release.

### Health Metrics

| Metric | Source | Healthy Threshold |
|--------|--------|-------------------|
| Task duration (per stage) | Application Insights traces | Scan <10s, Validate <5s/file, Generate <30s/file, Combine <60s |
| Docker worker queue depth | `/queue/status` endpoint | <50 pending messages |
| Container memory usage | `psutil` (already in image) | <80% of 4GB = <3.2GB |
| Failed task ratio | `app.tasks` table | <5% per job |
| Reference file size | Handler output | <10MB per combined ref (anomaly above this) |

### Alerts

| Alert | Threshold | Why |
|-------|-----------|-----|
| VirtualiZarr task failure rate >20% in 1 hour | Application Insights query | Indicates systematic issue (dependency, auth, blob access) |
| Combine stage duration >5 minutes | Task duration metric | Indicates memory pressure or unexpectedly large dataset |
| Container restart during VirtualiZarr job | App Service platform events | OOM or crash during processing |
| Stuck PROCESSING tasks >30 minutes old | `app.tasks WHERE status='processing' AND updated_at < now() - 30min` | Orphaned task from crash |

### 3am Diagnosis Capability

**Partially sufficient.** The existing Application Insights integration captures structured logs from all handlers, and the `/api/dbadmin/tasks/{job_id}` endpoint shows task status and error messages. An operator can determine:
- Which stage failed (from task_type)
- What the error was (from task error field)
- How many files were processed (from previous stage results)

**Gap**: There is no dashboard for VirtualiZarr-specific metrics. An operator at 3am would need to run KQL queries in Application Insights to correlate task failures with container restarts. Consider pre-building a dashboard or workbook for VirtualiZarr pipeline health.

---

## SCALING BEHAVIOR

### Load Profile

The VirtualiZarr pipeline is I/O-bound, not CPU-bound. Each task makes 1-2 HTTP requests to Azure Blob Storage (header reads) and writes one small JSON file. The Combine stage is memory-bound (loading N reference metadata objects).

### First Bottleneck

**The single `container-tasks` queue shared with ALL other Docker tasks.** If a user submits 10 VirtualiZarr jobs each with 50 files (500 tasks at Stage 3), those 500 tasks compete with ongoing raster COG and vector ETL tasks for the same 4 Docker worker instances. The raster/vector tasks are much heavier (minutes each), so the 500 lightweight VirtualiZarr tasks will wait behind them.

### Scaling Model

| Dimension | Current | Limit | Scaling Type |
|-----------|---------|-------|--------------|
| Worker instances | 4 | Manual scale on App Service Plan | Manual |
| Queue throughput | ~4 tasks/minute (if all workers busy with heavy tasks) | Depends on task duration | N/A |
| Blob storage I/O | ~1MB per file | 20,000 req/s per account | Not a concern |
| Database writes | 1 per Combine + 1 per Register | 20 max connections | Not a concern |
| Service Bus | 256KB message limit | Firm limit | Fan-in pattern required |

### Scaling is manual and coarse-grained.

The P0v3 App Service Plan allows scaling to more instances, but each new instance runs the same Docker image servicing all task types. There is no way to scale VirtualiZarr capacity independently of raster/vector capacity. If VirtualiZarr pipelines become high-volume, a dedicated queue and worker pool would be needed — but that is an architecture change, not a configuration change.

---

## OPERATIONAL HANDOFF

### What a New Operator Needs to Know

1. **VirtualiZarr tasks are lightweight but numerous.** A single job can create 50-10,000 tasks at Stages 2 and 3. Do not confuse high task counts with high resource usage.

2. **The combined reference file is the only critical artifact.** Individual per-file reference files are intermediate. If the Combine stage succeeds, the individual refs can be regenerated if needed. If the Combine stage fails, re-run the entire job.

3. **Reference validity depends on source file immutability.** If the source NetCDF files are modified after reference generation, the references become invalid. There is no automated detection.

4. **The `data_type="zarr"` path through the platform layer is new.** All existing automation (approval service, catalog service, status endpoints) was written for raster/vector. Test the full lifecycle (submit -> process -> approve -> STAC materialization -> unpublish) before considering this production-ready.

5. **VirtualiZarr and kerchunk are young libraries.** Expect API changes. Pin exact versions in `requirements-docker.txt`.

### Documentation That Must Exist Before Ship

1. **Runbook**: "Diagnosing a failed VirtualiZarr job" — KQL queries for Application Insights, how to find which file caused the failure, how to re-submit.
2. **Runbook**: "Rebuilding Docker image after VirtualiZarr/kerchunk update" — how to test the new version locally before pushing to ACR.
3. **Architecture decision record**: Why `data_type="zarr"` was added and what code paths were modified (for the next developer who greps for data_type).
4. **Pin versions documentation**: Exact tested versions of virtualizarr, kerchunk, h5py that work with the GDAL base image.

### Runbooks Needed

| Runbook | Trigger |
|---------|---------|
| "VirtualiZarr job stuck in PROCESSING" | Task orphaned after container restart |
| "Reference file produces corrupt data in xarray" | User reports bad data through TiTiler-xarray |
| "Docker image build fails after dependency update" | numpy/HDF5 version conflict |
| "VirtualiZarr tasks blocking raster/vector pipeline" | Queue backlog from large submission |

---

## COST MODEL

### Primary Cost Drivers

| Resource | Current Cost Driver | VirtualiZarr Impact |
|----------|-------------------|---------------------|
| App Service Plan (P0v3 x4) | Always-on compute | **No increase** — uses existing instances |
| Azure Blob Storage (reads) | Per-transaction + egress | **Minimal** — header-only reads, ~1MB per file |
| Azure Blob Storage (writes) | Per-transaction | **Minimal** — ~1MB reference JSON per file, one combined ref |
| Service Bus | Per-message | **Low** — 5 messages per file (one per stage task) |
| Application Insights | Per-GB ingested | **Low** — INFO-level logging, small payloads |

### Cost Scaling

VirtualiZarr is dramatically cheaper per dataset than the raster COG pipeline because:
- No data conversion (no storage doubling)
- No GDAL compute (header reads only)
- No large temp files on Azure Files mount
- Reference files are ~1MB vs multi-GB COGs

For 1,000 NetCDF files totaling 50TB, the pipeline generates ~1GB of reference files. Storage cost for references: ~$0.02/month.

The dominant cost is the App Service Plan, which is already running. VirtualiZarr adds no incremental compute cost unless the task volume is high enough to require scaling beyond 4 instances.

### Cost Traps

1. **Leaving 4 instances running when VirtualiZarr is the primary workload.** If the raster/vector pipeline goes quiet and VirtualiZarr is the main consumer, 4 P0v3 instances at ~$75/month each = $300/month for a workload that barely uses one core. Consider autoscaling rules.

2. **Application Insights log volume.** If the pipeline logs at INFO level for every file in a 10,000-file dataset, that is 50,000+ trace entries per job (5 stages x 10,000 files). At Application Insights pricing of ~$2.76/GB, verbose logging on frequent large jobs adds up. Consider reducing per-file logging to DEBUG for Stage 2 and 3.

---

## SUMMARY OF CRITICAL FINDINGS

### Must-Fix Before Implementation

| # | Finding | Severity | Reason |
|---|---------|----------|--------|
| 1 | `DataType` enum does not include "zarr" | **BLOCKER** | Submit endpoint will reject `data_type="zarr"` with 400 error |
| 2 | `numpy<2` pin may conflict with virtualizarr/kerchunk | **BLOCKER** | Docker image build may fail; must verify before writing code |
| 3 | Service Bus 256KB limit on Combine stage parameters | **HIGH** | Large file lists will fail silently at stage transition |
| 4 | Asset approval service infers data_type from blob_path | **HIGH** | Zarr releases will be misclassified as "raster" during approval |

### Should-Fix Before Ship

| # | Finding | Severity | Reason |
|---|---------|----------|--------|
| 5 | No progress reporting in spec | **MEDIUM** | Operator blindness during 15-minute pipeline runs |
| 6 | No ETag verification for source files | **MEDIUM** | Silent data corruption if source files change during processing |
| 7 | No checkpoint/resume for Combine stage | **MEDIUM** | OOM during combine loses all work, requires full re-run |
| 8 | Shared queue with raster/vector tasks | **LOW** | Queue contention under load, but acceptable for current volume |

---

*This review assesses operational readiness only. Application logic and API design are out of scope.*
