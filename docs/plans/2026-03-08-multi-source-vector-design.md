# Multi-Source Vector ETL — Design Document

**Created**: 08 MAR 2026
**Status**: DRAFT
**Relates to**: V0.9_VIEWS.md (Split Views), multi-table-release-design.md, geometry-type-splitting.md

---

## Problem

The vector ETL pipeline processes exactly one file into one PostGIS table (with optional geometry-type splitting). Three real-world patterns require multi-table output:

1. **Multi-file (P1)**: N files submitted together, each becomes a separate PostGIS table with its own TiPG endpoint. Example: `roads.gpkg`, `bridges.gpkg`, `tunnels.gpkg` all part of `kigali_infrastructure`.

2. **Split views (P2)**: One file, one table, but a categorical column generates N PostgreSQL VIEWs, each with its own TiPG endpoint. Example: `admin_boundaries` split on `admin_level` into admin0, admin1, admin2 views. **Already fully specified in V0.9_VIEWS.md (1235 lines).**

3. **GPKG multi-layer (P3)**: One GeoPackage file containing N named layers, each becomes a separate PostGIS table. Example: `kigali_master.gpkg` with layers `transport`, `buildings`, `parcels`.

---

## Architecture Decision: Option C (Hybrid)

P1 (multi-file) and P3 (GPKG multi-layer) are structurally identical: **list of sources -> list of tables**. They share a single new job type.

P2 (split views) is orthogonal: it runs *after* a table exists. It stays on the existing single-file `vector_docker_etl` job as specified in V0.9_VIEWS.md.

```
                          vector_docker_etl (existing)
                         /                            \
                single file -> 1 table          single file -> 1 table + N views (P2)
                  (today)                         (V0.9_VIEWS.md, future)

                      vector_multi_source_docker (NEW)
                     /                                \
            N files -> N tables (P1)         1 GPKG -> N layers -> N tables (P3)
```

**Only one multi-source mode per job.** P1, P2, and P3 are mutually exclusive.

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Job architecture | New `vector_multi_source_docker` job type | Keeps existing single-file job untouched |
| Source detection | Implicit: `file_name: list` = P1, `layer_names: list` = P3 | Clean API, no new enum |
| Mutual exclusivity | Pre-flight validator rejects combining modes | One multi-source mode per job |
| Max sources | Hard cap of 10, env var `MAX_VECTOR_SOURCES` | Prevents runaway table creation |
| Table naming | `{base_prefix}_{source_suffix}_ord{N}` | Groups naturally with `table_group` |
| Base prefix | User's `table_name` or `{dataset_id}_{resource_id}` (default) | Consistent with existing `generate_vector_table_name()` |
| Source suffix | Filename stem (P1) or GPKG layer name (P3), sanitized | Descriptive, unique within group |
| Geometry-split | Applies per source table (source suffix + geom suffix) | Orthogonal, composable |
| Split views (P2) | NOT composable with multi-source | Indulgent enough as single-file feature |
| Routing | One route per output table (bug fixed in this session) | Each table independently discoverable |
| Unpublish | Required — symmetric teardown, drops all N tables | Every ETL has an equal and opposite unpublish |
| GPKG layer listing | `pyogrio.list_layers()` (already in handler) | pyogrio is the default engine in geopandas 1.1+ |
| Parallelism | Sequential processing within single handler | Docker worker handles one source at a time |

---

## Constraint Matrix

| `file_name` | `layer_names` | `split_column` | Valid? | Mode |
|-------------|---------------|----------------|--------|------|
| `str` | -- | -- | Yes | Single file (today) |
| `str` | -- | set | Yes | Single file + split views (P2) |
| `str` (.gpkg) | `list` | -- | Yes | GPKG multi-layer (P3) |
| `list` | -- | -- | Yes | Multi-file (P1) |
| `list` | `list` | -- | **No** | Rejected: only one multi-source mode |
| `list` | -- | set | **No** | Rejected: split views only on single-file |
| `str` (.gpkg) | `list` | set | **No** | Rejected: only one multi-source mode |
| `str` (non-gpkg) | `list` | -- | **No** | Rejected: `layer_names` only valid for GPKG |

Pre-flight resource validators enforce all rejections with explanatory error messages.

---

## Table Naming Convention

### Base Prefix

| Scenario | Base Prefix |
|----------|-------------|
| User provides `table_name` in processing_options | `{table_name}` (e.g., `kigali_infra`) |
| No `table_name` provided | `{dataset_id}_{resource_id}` sanitized (e.g., `kigali_infrastructure`) |

### Full Table Name

```
{base_prefix}_{source_suffix}_ord{N}
```

| Mode | Source Suffix | Example Table |
|------|-------------|---------------|
| Multi-file (P1) | filename stem | `kigali_infra_roads_ord1` |
| GPKG multi-layer (P3) | layer name | `kigali_infra_transport_ord1` |
| + geometry split | source + geom | `kigali_infra_roads_polygon_ord1` |

### Catalog Grouping

- `geo.table_catalog.table_group` = base prefix (without source suffix)
- All output tables from one submission share the same `table_group`
- Consistent with geometry-split grouping pattern

### Slug Convention (Routes)

- Base slug: `{dataset_id}-{resource_id}` (via `_slugify_for_stac`)
- Per-table slug: `{base_slug}-{source_suffix}` (e.g., `kigali-infrastructure-roads`)
- Geometry-split adds another suffix: `kigali-infrastructure-roads-polygon`

### Truncation

PostgreSQL identifier limit is 63 characters. Strategy (same as `_compute_view_name()` in V0.9_VIEWS.md):
1. If full name fits, use it
2. Otherwise, shorten base prefix (keep source suffix + ordinal)
3. Raise `ValueError` if impossible (pathological)

---

## New Model Fields

### `VectorProcessingOptions` additions

```python
# In core/models/processing_options.py

layer_names: Optional[List[str]] = Field(
    default=None,
    description=(
        "GeoPackage layer names to extract as separate tables. "
        "Only valid for .gpkg files. Max 10 layers."
    )
)
```

Note: `layer_name` (singular) remains for single-layer extraction. `layer_names` (plural) triggers multi-layer mode.

### `PlatformRequest` — no changes needed

`file_name: Optional[Union[str, List[str]]]` already accepts lists. `is_raster_collection` detection already uses `isinstance(file_name, list)`.

### New detection property

```python
# In core/models/platform.py

@property
def is_vector_collection(self) -> bool:
    """True when file_name is a list AND data_type is vector."""
    return (
        isinstance(self.file_name, list)
        and len(self.file_name) > 1
        and self.data_type == DataType.VECTOR
    )
```

---

## New Configuration

```python
# In config/defaults.py

MAX_VECTOR_SOURCES = int(os.environ.get("MAX_VECTOR_SOURCES", "10"))
```

---

## Job Definition: `vector_multi_source_docker`

### Parameters Schema

```python
parameters_schema = {
    # Source specification (one of two modes)
    'blob_list': {'type': 'list', 'required': False},       # P1: multi-file
    'blob_name': {'type': 'str', 'required': False},         # P3: single GPKG
    'layer_names': {'type': 'list', 'required': False},      # P3: layers to extract

    # Common fields
    'container_name': {'type': 'str', 'required': True},
    'file_extension': {'type': 'str', 'required': True},
    'base_table_name': {'type': 'str', 'required': True},   # Base prefix
    'schema': {'type': 'str', 'required': True, 'default': 'geo'},
    'overwrite': {'type': 'bool', 'required': False, 'default': False},

    # Metadata passthrough
    'dataset_id': {'type': 'str', 'required': True},
    'resource_id': {'type': 'str', 'required': True},
    'version_ordinal': {'type': 'int', 'required': True},
    'stac_item_id': {'type': 'str', 'required': False},
    'release_id': {'type': 'str', 'required': False},
}
```

### Stages

```python
stages = [
    {
        "number": 1,
        "name": "process_sources",
        "task_type": "vector_multi_source_complete",
        "parallelism": "single"
    }
]
```

Single stage, single task — the handler loops internally over sources. This avoids N tasks competing for database connections and keeps checkpoint/progress tracking simple.

### Resource Validators (Pre-flight)

1. **`multi_source_exclusivity`**: Rejects `blob_list` + `layer_names` together
2. **`source_count_limit`**: Rejects if `len(blob_list)` or `len(layer_names)` > `MAX_VECTOR_SOURCES`
3. **`gpkg_layer_names_only`**: Rejects `layer_names` if `file_extension != 'gpkg'`
4. **`blobs_exist`**: For P1, validates all files in `blob_list` exist in blob storage
5. **`gpkg_layers_exist`**: For P3, validates all `layer_names` exist in the GPKG (via `pyogrio.list_layers()`)
6. **`split_column_blocked`**: Rejects `split_column` on multi-source jobs

### Task Creation

```python
@staticmethod
def create_tasks_for_stage(stage, job_params, job_id, previous_results=None):
    # Single task receives all sources
    return [{
        'task_id': generate_deterministic_task_id(job_id, stage, 0),
        'task_type': 'vector_multi_source_complete',
        'parameters': {
            # Pass all job_params through — handler determines mode
            **job_params
        }
    }]
```

### Job Finalization

```python
def finalize_job(context):
    task_result = context.task_results[0]

    # Collect all created tables
    tables_created = task_result.get('tables', [])
    table_names = [t['table_name'] for t in tables_created]
    total_rows = sum(t.get('feature_count', 0) for t in tables_created)

    # Generate URLs for each table
    endpoints = {}
    for t in tables_created:
        name = t['table_name']
        collection_id = f"geo.{name}"
        endpoints[name] = {
            'features': f"/api/features/collections/{collection_id}/items",
            'tiles': config.generate_vector_tile_urls(name, 'geo'),
        }

    return {
        'table_names': table_names,
        'total_rows': total_rows,
        'sources_processed': len(tables_created),
        'endpoints': endpoints,
    }
```

---

## Handler: `vector_multi_source_complete`

### Execution Flow

```
1. Determine mode (P1 or P3) from parameters
2. Build source list:
   P1: [(blob_name, source_suffix) for blob in blob_list]
   P3: [(layer_name, source_suffix) for layer in layer_names]
3. For each source:
   a. Load data:
      P1: download/mount blob -> converter -> GeoDataFrame
      P3: pyogrio read_dataframe(gpkg_path, layer=name) -> GeoDataFrame
   b. Validate & prepare (reuse existing prepare_gdf())
   c. Handle geometry-type splitting (reuse existing logic)
   d. For each (sub)table:
      - Compute table name: {base}_{source_suffix}[_{geom_suffix}]_ord{N}
      - Create PostGIS table (reuse _process_single_table())
      - Register in geo.table_catalog (table_group = base)
      - Write to app.release_tables (table_role = 'multi_source' or 'geometry_split')
   e. Checkpoint per source
4. Refresh TiPG catalog (single call after all tables created)
5. Return aggregated result
```

### Code Reuse

The handler delegates to existing helpers for all heavy lifting:

| Helper | Source | Reused For |
|--------|--------|------------|
| `load_vector_source()` | `services/vector/core.py` | Loading each file |
| `_convert_geopackage()` | `services/vector/converters.py` | Format conversion |
| `prepare_gdf()` | `services/vector/postgis_handler.py` | Validation + geometry split |
| `_process_single_table()` | `handler_vector_docker_complete.py` | Table creation + insert |
| `_refresh_tipg()` | `handler_vector_docker_complete.py` | TiPG catalog refresh |
| `pyogrio.list_layers()` | stdlib | GPKG layer enumeration |

### New `table_role` Value

```
'multi_source' — table created from one source in a multi-source job
```

Added to `release_tables.table_role` alongside existing `'primary'`, `'geometry_split'`, `'view'`.

---

## Platform Translation

### Detection and Routing

```python
# In services/platform_translation.py — translate_to_coremachine()

if request.data_type == DataType.VECTOR:
    # Check for multi-source modes
    is_multi_file = isinstance(request.file_name, list) and len(request.file_name) > 1
    has_layer_names = bool(opts.layer_names)

    if is_multi_file or has_layer_names:
        # Route to multi-source job
        return 'vector_multi_source_docker', {
            'blob_list': request.file_name if is_multi_file else None,
            'blob_name': request.file_name if not is_multi_file else None,
            'layer_names': opts.layer_names if has_layer_names else None,
            'container_name': request.container_name,
            'file_extension': file_ext,
            'base_table_name': base_table_name,
            'schema': 'geo',
            'overwrite': opts.overwrite,
            # ... metadata passthrough
        }
    else:
        # Existing single-file flow (unchanged)
        return 'vector_docker_etl', { ... }
```

### Base Table Name Generation

```python
# Use table_name from processing_options if provided, else derive from DDH identifiers
if opts.table_name:
    base_table_name = _slugify_for_postgres(opts.table_name)
else:
    base_table_name = _slugify_for_postgres(f"{request.dataset_id}_{request.resource_id}")
```

The `_ord{N}` segment is NOT included in the base — it's appended per-table during handler execution when the version_ordinal is known.

---

## Unpublish: `unpublish_vector_multi_source`

### Symmetric Teardown

Every ETL pipeline has an equal and opposite unpublish. The multi-source unpublish:

1. **Inventory**: Query `release_tables` for all tables owned by the release
2. **Drop tables**: `DROP TABLE IF EXISTS {schema}.{table} CASCADE` for each
   - `CASCADE` also drops any split views (P2) attached to these tables
3. **Cleanup metadata**:
   - Delete from `geo.table_catalog` (all tables in the group)
   - Delete from `app.release_tables` (all rows for the release)
   - Delete from `geo.feature_collection_styles` (per-table styles)
4. **Refresh TiPG**: Single `/admin/refresh-collections` call
5. **Routes**: Handled by `_delete_routes()` in approval service (already fixed)

### Job Definition

```python
class UnpublishVectorMultiSourceJob(JobBaseMixin, JobBase):
    job_type = "unpublish_vector_multi_source"
    stages = [
        {"number": 1, "name": "inventory", "task_type": "inventory_multi_source", "parallelism": "single"},
        {"number": 2, "name": "drop_tables", "task_type": "drop_multi_source_tables", "parallelism": "single"},
        {"number": 3, "name": "cleanup", "task_type": "cleanup_multi_source_metadata", "parallelism": "single"},
    ]
```

Three stages (inventory -> drop -> cleanup) mirrors the existing `unpublish_vector` pattern.

---

## Affected Files

### New Files (4)

| File | Purpose |
|------|---------|
| `jobs/vector_multi_source_docker.py` | Job definition + parameter schema + validators |
| `services/handler_vector_multi_source.py` | Handler: loops over sources, delegates to existing helpers |
| `jobs/unpublish_vector_multi_source.py` | Unpublish job definition |
| `services/handler_unpublish_multi_source.py` | Unpublish handlers (inventory, drop, cleanup) |

### Modified Files (8)

| File | Change |
|------|--------|
| `core/models/processing_options.py` | Add `layer_names: Optional[List[str]]` to `VectorProcessingOptions` |
| `core/models/platform.py` | Add `is_vector_collection` property |
| `services/platform_translation.py` | Route multi-source requests to new job type |
| `config/defaults.py` | Add `MAX_VECTOR_SOURCES = 10` |
| `jobs/__init__.py` | Register `vector_multi_source_docker` + unpublish job |
| `services/__init__.py` | Register handler functions |
| `services/asset_approval_service.py` | Already fixed: per-table route creation |
| `V0.9_VIEWS.md` | Add note: split views not composable with multi-source |

### Unchanged (critical to verify)

| File | Why Unchanged |
|------|---------------|
| `jobs/vector_docker_etl.py` | Single-file job untouched |
| `services/handler_vector_docker_complete.py` | Single-file handler untouched (helpers extracted, not modified) |
| `infrastructure/route_repository.py` | Schema unchanged, PK remains `(slug, version_id)` |
| `infrastructure/release_table_repository.py` | Already supports N rows per release |

---

## Data Flow: Multi-File (P1)

```
Client submits:
  file_name: ["roads.gpkg", "bridges.gpkg", "tunnels.gpkg"]
  dataset_id: "kigali", resource_id: "infrastructure"
    |
    v
translate_to_coremachine() detects is_vector_collection
  -> job_type = 'vector_multi_source_docker'
  -> blob_list = ["roads.gpkg", "bridges.gpkg", "tunnels.gpkg"]
  -> base_table_name = "kigali_infrastructure"
    |
    v
Handler loops over blob_list:
  Source 1: roads.gpkg
    -> load_vector_source("roads.gpkg")
    -> prepare_gdf() -> {polygon: gdf}
    -> _process_single_table("kigali_infrastructure_roads_ord1")
    -> release_tables.create(table_role='multi_source')
    -> table_catalog.register(table_group='kigali_infrastructure')

  Source 2: bridges.gpkg
    -> load_vector_source("bridges.gpkg")
    -> prepare_gdf() -> {point: gdf, line: gdf}  (mixed geometry!)
    -> _process_single_table("kigali_infrastructure_bridges_point_ord1")
    -> _process_single_table("kigali_infrastructure_bridges_line_ord1")
    -> release_tables.create(table_role='geometry_split') x2

  Source 3: tunnels.gpkg
    -> ... same pattern
    |
    v
TiPG refresh (single call)
    |
    v
On approval:
  _create_routes() writes:
    slug "kigali-infrastructure-roads"     -> b2c_routes
    slug "kigali-infrastructure-bridges-point" -> b2c_routes
    slug "kigali-infrastructure-bridges-line"  -> b2c_routes
    slug "kigali-infrastructure-tunnels"   -> b2c_routes
    |
    v
TiPG auto-discovers all 4 tables as OGC Feature collections
```

## Data Flow: GPKG Multi-Layer (P3)

```
Client submits:
  file_name: "kigali_master.gpkg"
  processing_options: { layer_names: ["transport", "buildings", "parcels"] }
  dataset_id: "kigali", resource_id: "master"
    |
    v
translate_to_coremachine() detects layer_names present
  -> job_type = 'vector_multi_source_docker'
  -> blob_name = "kigali_master.gpkg"
  -> layer_names = ["transport", "buildings", "parcels"]
  -> base_table_name = "kigali_master"
    |
    v
Handler pre-validates layers via pyogrio.list_layers():
  Available: [("transport", "MultiLineString"), ("buildings", "MultiPolygon"),
              ("parcels", "MultiPolygon"), ("layer_styles", None)]
  Requested all exist and are spatial: OK
    |
    v
Handler loops over layer_names:
  Source 1: layer "transport"
    -> gpd.read_file(gpkg_path, layer="transport", engine="pyogrio")
    -> prepare_gdf() -> {line: gdf}
    -> _process_single_table("kigali_master_transport_ord1")

  Source 2: layer "buildings"
    -> gpd.read_file(gpkg_path, layer="buildings", engine="pyogrio")
    -> prepare_gdf() -> {polygon: gdf}
    -> _process_single_table("kigali_master_buildings_ord1")

  Source 3: layer "parcels"
    -> ... same pattern
    |
    v
Same approval + routing flow as P1
```

---

## Agent Review Pipeline

After implementation, run **SIEGE** with new test sequences:

### Sequence 20: Multi-File Vector Lifecycle
1. Submit 3 vector files as `file_name: [...]`
2. Poll until completed
3. Verify 3 tables created in PostGIS
4. Approve
5. Verify 3 routes in `b2c_routes`
6. Probe TiPG for all 3 collections
7. Unpublish -> verify all 3 tables dropped

### Sequence 21: GPKG Multi-Layer Lifecycle
1. Submit GPKG with `layer_names: [...]`
2. Poll until completed
3. Verify N tables (one per layer)
4. Approve -> verify N routes
5. Probe TiPG
6. Unpublish -> verify cleanup

### Sequence 22: Multi-Source Validation
1. Submit `file_name: list` + `layer_names: list` -> expect 400
2. Submit non-GPKG + `layer_names` -> expect 400
3. Submit `file_name: list` + `split_column` -> expect 400
4. Submit 11 files (exceeds MAX_VECTOR_SOURCES) -> expect 400

### Test Fixtures (add to `siege_config.json`)

```json
{
  "vector_multi_file": {
    "dataset_id_suffix": "multi-vector-test",
    "resource_id": "infra",
    "file_names": ["sg_roads.geojson", "sg_buildings.geojson"],
    "container_name": "rmhazuregeobronze",
    "description": "Multi-file vector test (2 GeoJSON files)"
  },
  "vector_multi_layer_gpkg": {
    "dataset_id_suffix": "gpkg-layer-test",
    "resource_id": "master",
    "file_name": "sg_multi_layer.gpkg",
    "layer_names": ["roads", "buildings"],
    "container_name": "rmhazuregeobronze",
    "description": "Multi-layer GPKG test (2 layers)"
  }
}
```

---

## Implementation Order

Tasks are ordered by dependency. Tasks 1-3 have no dependencies between them.

```
Task 1: Model changes (processing_options, platform.py, defaults.py)
Task 2: Job definition (vector_multi_source_docker.py) + validators
Task 3: Platform translation routing
   |
Task 4: Handler (vector_multi_source_complete) — depends on Tasks 1-3
Task 5: Job + handler registration (__init__.py files) — depends on Tasks 2, 4
   |
Task 6: Unpublish job + handler — depends on Task 2
Task 7: Integration testing + SIEGE sequences — depends on all above
```

---

## Scope Boundaries

### In Scope
- Multi-file vector ingestion (P1)
- GPKG multi-layer extraction (P3)
- Per-table routing (already fixed)
- Symmetric unpublish
- Pre-flight validation of mutual exclusivity
- SIEGE test sequences

### Out of Scope
- Split views (P2) — already specified in V0.9_VIEWS.md, separate implementation
- Parallel source processing (sequential is sufficient for N <= 10)
- Cross-source deduplication or schema merging
- Raster collection enablement (separate feature)
- Web dashboard multi-file upload UI (separate feature)
