# Platform Standardization Assessment

**Date**: 06 MAR 2026
**Scope**: rmhgeoapi (ETL/Backend) + rmhtitiler (Service Layer API)
**Goal**: Assess seams between apps to enable "system in a box" deployment

---

## 1. Architecture Philosophy

These two apps sit at opposite ends of the CAP theorem and that's correct:

| Dimension | rmhgeoapi (ETL) | rmhtitiler (Service Layer) |
|-----------|-----------------|---------------------------|
| **CAP Priority** | Consistency + Partition tolerance | Availability + Partition tolerance |
| **Correctness vs Speed** | Correctness (pipelines can take minutes) | Speed (tiles in <1s, stale cache is fine) |
| **Error Philosophy** | Fail explicitly, no fallbacks | Degrade gracefully, serve what you can |
| **Scaling** | Queue-based, worker isolation | Stateless horizontal scaling |
| **State** | Rich (jobs, stages, tasks, releases, audits) | Minimal (token cache, DB pool) |

**They SHOULD remain separate processes.** Standardization means clean seams, not merging.

---

## 2. Integration Points (The Seams)

### 2.1 STAC Pipeline (ETL writes, TiTiler reads)

| Aspect | rmhgeoapi (Producer) | rmhtitiler (Consumer) |
|--------|---------------------|----------------------|
| **Library** | `pypgstac==0.9.8` (direct SQL) | `stac-fastapi.pgstac>=4.0.0` (read API) |
| **Table** | Writes to `pgstac.items`, `pgstac.collections` | Reads from same tables |
| **Item format** | STAC 1.0.0 with `ddh:*` properties, no `geoetl:*` | Expects standard STAC 1.0.0 |
| **Asset hrefs** | `/vsiaz/{container}/{path}` | Passes href to GDAL for tile rendering |
| **Trigger** | Writes at approval time (`trigger_approvals.py`) | Discovers via pgSTAC search |

**Seam contract**: STAC item in `pgstac.items` with valid `assets.*.href` pointing to accessible blobs.

**Risk**: pgSTAC schema version mismatch. ETL pins `pypgstac==0.9.8`, TiTiler uses `stac-fastapi.pgstac>=4.0.0` which has its own pgSTAC expectations.

**Recommendation**: Pin pgSTAC schema version as a platform-level constant. Both apps must agree on the schema version installed in the database.

### 2.2 Vector Pipeline (ETL writes, TiPG reads)

| Aspect | rmhgeoapi (Producer) | rmhtitiler (Consumer) |
|--------|---------------------|----------------------|
| **Schema** | Writes to `geo.*` tables | Discovers via `GEOTILER_TIPG_SCHEMAS=geo` |
| **Geometry col** | `geom` (PostGIS geometry) | Expects `geom` (`GEOTILER_TIPG_GEOMETRY_COLUMN`) |
| **PK** | `id` (UUID) | TiPG auto-detects `id` or first column |
| **CRS** | Stored in PostGIS metadata | Read from PostGIS metadata |
| **Spatial index** | `CREATE INDEX ... USING GIST(geom)` | Required for performant tile queries |
| **Refresh** | Creates tables during job execution | Manual webhook or TTL-based catalog refresh |

**Seam contract**: PostGIS table in `geo` schema with `id` PK, `geom` geometry column, GIST index, valid CRS.

**Risk**: ETL creates a table but TiTiler doesn't know about it until catalog refresh.

**Recommendation**: Wire the ETL completion callback to call `POST /admin/refresh-collections` on TiTiler. This webhook exists but isn't connected yet.

### 2.3 Blob Storage (ETL writes, TiTiler reads)

| Aspect | rmhgeoapi (Producer) | rmhtitiler (Consumer) |
|--------|---------------------|----------------------|
| **COG path** | `/vsiaz/{silver-container}/{dataset}/{file}.tif` | Reads via GDAL `/vsiaz/` with OAuth token |
| **Zarr path** | `abfs://{silver-container}/{dataset}/{store}.zarr` | Reads via fsspec/adlfs with OAuth token |
| **Auth** | `BlobRepository.for_zone()` singleton | `DefaultAzureCredential` + token cache → GDAL env vars |
| **Storage account** | Configured via `SILVER_STORAGE_ACCOUNT` | Configured via `GEOTILER_STORAGE_ACCOUNT` |

**Seam contract**: Valid Cloud Optimized GeoTIFF or Zarr store at the href path, accessible via the same Azure Managed Identity.

**Risk**: Storage account name is configured independently in both apps. If they disagree, TiTiler can't read what ETL wrote.

**Recommendation**: Both apps should derive the storage account from the same source (env var or shared config).

### 2.4 PostgreSQL (Shared database, different access patterns)

| Aspect | rmhgeoapi | rmhtitiler |
|--------|-----------|------------|
| **Host** | `POSTGIS_HOST` | `GEOTILER_PG_HOST` |
| **Database** | `POSTGIS_DATABASE` | `GEOTILER_PG_DB` |
| **User** | `POSTGIS_USER` / `DB_ADMIN_MANAGED_IDENTITY_NAME` | `GEOTILER_PG_USER` |
| **Auth** | Managed Identity (psycopg3 sync) | 3 modes: password / key_vault / managed_identity |
| **Driver** | psycopg3 sync (`psycopg[binary]`) | psycopg3 async (from titiler-pgstac base image) |
| **Schemas** | `app`, `pgstac`, `geo`, `h3` (read/write) | `pgstac`, `geo` (read-only) |
| **Type adapters** | dict→JSONB, Enum→.value (registered per connection) | None custom (uses titiler-pgstac defaults) |

**Seam contract**: Same PostgreSQL server, same database, same pgSTAC + geo schemas.

**Risk**: Different env var names for the same connection target. Easy to misconfigure during deployment.

---

## 3. Response Shape Divergence

This is the most visible inconsistency between the two apps:

### 3.1 Health Endpoints

| Field | rmhgeoapi | rmhtitiler |
|-------|-----------|------------|
| **Endpoint** | `GET /api/health` | `GET /health` |
| **Top-level** | `{status, version, components, warnings, errors, environment, identity, timestamp}` | `{status, version, timestamp, uptime_seconds, services, dependencies, hardware, issues, config}` |
| **Status values** | `healthy \| degraded \| unhealthy` | `healthy \| degraded` |
| **Component shape** | `{component, status, details, checked_at}` | `{status, available, description, endpoints, details}` |
| **HTTP codes** | 200 (healthy/degraded), 503 (unhealthy) | 200 (healthy/degraded), 503 (critical failure) |

**Liveness**:
| | rmhgeoapi | rmhtitiler |
|-|-----------|------------|
| **Endpoint** | `GET /api/livez` (not explicit, via health) | `GET /livez` |
| **Shape** | `{status: "alive", timestamp}` | `{status: "alive", message: "Container is running"}` |

**Readiness**:
| | rmhgeoapi | rmhtitiler |
|-|-----------|------------|
| **Endpoint** | N/A (health check covers this) | `GET /readyz` |
| **Shape** | — | `{ready: bool, version, issues}` |

**Recommendation**: Define a shared `PlatformHealthResponse` contract:
```json
{
  "status": "healthy|degraded|unhealthy",
  "version": "0.x.x.x",
  "app": "rmhgeoapi|rmhtitiler",
  "role": "etl|service-layer",
  "timestamp": "ISO-8601",
  "components": { "<name>": {"status": "...", "details": {...}} },
  "issues": ["..."]
}
```

### 3.2 Error Responses

| Aspect | rmhgeoapi | rmhtitiler |
|--------|-----------|------------|
| **Wrapper** | `{success: false, error, error_type, error_code, error_category, remediation, user_fixable}` | `{detail: "..."}` (FastAPI default) |
| **Middleware** | Custom auth: `{detail, error}` with 503 | TiTiler `DEFAULT_STATUS_CODES` |
| **Consistency** | Highly standardized across all endpoints | Varies by router (TiTiler vs custom) |

**This is the biggest gap.** rmhgeoapi has a rich, structured error contract. rmhtitiler uses FastAPI/TiTiler defaults.

**Recommendation**: For custom rmhtitiler endpoints (admin, downloads, H3), adopt the structured error shape. For TiTiler-proxied endpoints (tiles, STAC), keep native format (clients expect it).

### 3.3 Success Responses

| Aspect | rmhgeoapi | rmhtitiler |
|--------|-----------|------------|
| **Wrapper** | `{success: true, ...payload}` | No wrapper (direct payload) |
| **Pagination** | Custom (`limit`, `offset` params) | OGC/STAC standard (`links.next`) |

**Recommendation**: Don't force rmhtitiler to wrap tile/STAC responses. Those follow OGC/STAC standards. Only custom endpoints should align.

---

## 4. Shared Dependencies

### 4.1 Exact Overlap

| Package | rmhgeoapi | rmhtitiler | Notes |
|---------|-----------|------------|-------|
| `azure-identity` | `>=1.16.1` | `>=1.16.1` | Same — extract to shared |
| `azure-keyvault-secrets` | `>=4.8.0` | `>=4.7.0` | ETL is newer — align to `>=4.8.0` |
| `adlfs` | `>=2024.2.0` | `>=2024.4.1` | TiTiler is newer — align to `>=2024.4.1` |
| `psutil` | `>=5.9.0` | `>=5.9.0` | Same |
| `duckdb` | `>=1.1.0` | `>=1.1.0` | Same |
| `pydantic` | `>=2.0.0` | (from base image) | Same major version |
| `psycopg` | `>=3.1.0` | (from base image) | Same driver family |
| `asyncpg` | `>=0.29.0` | (from base image) | Both use for async DB |

### 4.2 ETL Only

| Package | Purpose |
|---------|---------|
| `azure-functions` | Azure Functions runtime |
| `azure-storage-blob` | Direct blob SDK operations |
| `azure-servicebus` | Queue-based orchestration |
| `geopandas`, `rasterio`, `rio-cogeo` | Heavy geospatial processing |
| `pypgstac==0.9.8` | STAC materialization |
| `h3>=4.0.0` | H3 spatial indexing |
| `numpy<2` | C-extension ABI pinning |

### 4.3 TiTiler Only

| Package | Purpose |
|---------|---------|
| `titiler.xarray[minimal]` | Zarr/NetCDF tile rendering |
| `tipg` | OGC Features + Vector Tiles |
| `stac-fastapi.pgstac` | STAC API read layer |
| `azure-monitor-opentelemetry` | App Insights (ETL uses different pattern) |
| `icechunk` | Virtual Zarr store |
| `PyJWT`, `cryptography` | Admin auth JWT validation |

---

## 5. Environment Variable Mapping

Same infrastructure, different names:

| Resource | rmhgeoapi | rmhtitiler | Value |
|----------|-----------|------------|-------|
| **DB Host** | `POSTGIS_HOST` | `GEOTILER_PG_HOST` | `rmhpostgres.postgres.database.azure.com` |
| **DB Name** | `POSTGIS_DATABASE` | `GEOTILER_PG_DB` | `geopgflex` |
| **DB User** | `POSTGIS_USER` | `GEOTILER_PG_USER` | `rob634` |
| **DB Port** | `POSTGIS_PORT` | `GEOTILER_PG_PORT` | `5432` |
| **DB Password** | `POSTGIS_PASSWORD` | `GEOTILER_PG_PASSWORD` | (managed identity preferred) |
| **Storage Account** | `SILVER_STORAGE_ACCOUNT` | `GEOTILER_STORAGE_ACCOUNT` | `rmhazuregeosilver` |
| **App Insights** | `APPLICATIONINSIGHTS_CONNECTION_STRING` | `APPLICATIONINSIGHTS_CONNECTION_STRING` | Same (no prefix) |
| **Managed Identity** | `DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID` | `GEOTILER_PG_MI_CLIENT_ID` | Same GUID |
| **Environment** | `ENVIRONMENT` | `GEOTILER_OBS_ENVIRONMENT` | `dev` |

**Observation**: rmhtitiler prefixes everything with `GEOTILER_` (Pydantic Settings convention). rmhgeoapi uses domain-specific prefixes (`POSTGIS_`, `APP_`, `SILVER_`).

**Recommendation**: Don't rename — both patterns are valid for their context. Instead, create a **platform manifest** that maps both sets of env vars from a single source:

```yaml
# platform.yaml (future: deployment config)
database:
  host: rmhpostgres.postgres.database.azure.com
  name: geopgflex
  user: rob634

  # Maps to:
  # rmhgeoapi:  POSTGIS_HOST, POSTGIS_DATABASE, POSTGIS_USER
  # rmhtitiler: GEOTILER_PG_HOST, GEOTILER_PG_DB, GEOTILER_PG_USER
```

---

## 6. Observability Divergence

| Aspect | rmhgeoapi | rmhtitiler |
|--------|-----------|------------|
| **Init pattern** | `config.observability.enabled` flag | `configure_azure_monitor()` before FastAPI import |
| **Toggle** | `OBSERVABILITY_MODE=true` | `GEOTILER_ENABLE_OBSERVABILITY=true` |
| **Logging** | `LoggerFactory` with component types | Python `logging` + JSON format when AI enabled |
| **App Insights** | Shared App ID `d3af3d37-...` | Same connection string |
| **Custom metrics** | `MetricsBlobLogger` (blob-based buffer) | Request timing middleware |
| **Service name** | `APP_NAME` | `GEOTILER_OBS_SERVICE_NAME` |

**They share the same App Insights instance** — this is good for cross-app correlation. The init patterns differ because rmhgeoapi is Azure Functions (auto-instrumented) and rmhtitiler is uvicorn (manual OpenTelemetry).

**Recommendation**: Standardize the `service.name` and `deployment.environment` resource attributes so App Insights queries can filter/correlate cleanly:
- ETL: `service.name = "rmhgeoapi"`, `service.namespace = "rmhgeo-platform"`
- TiTiler: `service.name = "rmhtitiler"`, `service.namespace = "rmhgeo-platform"`

---

## 7. Auth Pattern Comparison

### 7.1 Token Caching

| Aspect | rmhgeoapi | rmhtitiler |
|--------|-----------|------------|
| **Storage tokens** | `BlobRepository` singleton (implicit cache) | `TokenCache` dataclass with TTL + async lock |
| **DB tokens** | Background refresh thread (45 min) | Background refresh task (45 min) |
| **Refresh buffer** | ~5 min before expiry | `TOKEN_REFRESH_BUFFER_SECS = 300` (5 min) |
| **Concurrency** | `threading.Lock` | `asyncio.Lock` + `threading.Lock` fallback |
| **Scope (storage)** | Implicit via `DefaultAzureCredential` | `https://storage.azure.com/.default` |
| **Scope (postgres)** | `https://ossrdbms-aad.database.windows.net/.default` | Same scope |

**Same logic, different implementations.** Both use 45-min refresh with 5-min buffer against 1-hour Azure token TTL.

### 7.2 Credential Source

| | rmhgeoapi | rmhtitiler |
|-|-----------|------------|
| **Primary** | `DefaultAzureCredential()` singleton | `DefaultAzureCredential()` or `ManagedIdentityCredential(client_id=...)` |
| **GDAL integration** | Via `BlobRepository` (internal) | Via `AZURE_STORAGE_ACCESS_TOKEN` env var → GDAL config |
| **fsspec/adlfs** | Derives from `BlobRepository.for_zone()` | `_CachedTokenCredential` async wrapper |

**Recommendation**: A shared `rmhgeo-auth` module could provide:
- `TokenCache` with both sync and async refresh
- GDAL credential configuration
- fsspec/adlfs credential wrapping
- PostgreSQL OAuth scope constant

---

## 8. Data Format Contracts

### 8.1 STAC Items (pgSTAC)

Written by ETL, read by TiTiler. Contract:

```
REQUIRED:
  id:          string (format: {dataset}-{resource}-{type}-{version})
  type:        "Feature"
  geometry:    GeoJSON Polygon/MultiPolygon
  bbox:        [west, south, east, north]
  properties:
    datetime:  ISO-8601
    ddh:version_id:    string
    ddh:access_level:  "OUO"|"PUBLIC"
    ddh:dataset_id:    string
    ddh:resource_id:   string
  assets:
    cog|zarr:
      href:    "/vsiaz/{container}/{path}" (COG) or "abfs://{container}/{path}" (Zarr)
      type:    "image/tiff; application=geotiff" (COG) or "application/x-zarr" (Zarr)
      roles:   ["data"]
  collection:  string (format: {dataset}-{resource})

SANITIZATION:
  - No geoetl:* properties (internal pipeline metadata stripped)
  - No internal blob SAS tokens in hrefs
```

### 8.2 PostGIS Vector Tables (geo.*)

Written by ETL, read by TiPG. Contract:

```
REQUIRED:
  Schema:      geo
  PK:          id (UUID)
  Geometry:    geom (PostGIS geometry with SRID)
  Index:       GIST index on geom column
  CRS:         Registered in geometry_columns metadata

EXPECTED BY TIPG:
  - Table must be in schema listed in GEOTILER_TIPG_SCHEMAS
  - Geometry column name must match GEOTILER_TIPG_GEOMETRY_COLUMN (default: "geom")
  - All columns become GeoJSON properties
  - JSONB columns are serialized as nested objects
```

### 8.3 Blob Paths

```
COG (raster):
  Pattern:  /vsiaz/{container}/{dataset_id}/{resource_id}/{filename}.tif
  Example:  /vsiaz/rmhazuregeobronze/namangan/namangan14aug2019_R1C1cog.tif
  Access:   GDAL /vsiaz/ with AZURE_STORAGE_ACCESS_TOKEN env var

Zarr (multidimensional):
  Pattern:  abfs://{container}/{dataset_id}/{resource_id}/{store}.zarr
  Access:   fsspec/adlfs with DefaultAzureCredential or cached token

GeoParquet (H3/analytics):
  Pattern:  https://{account}.blob.core.windows.net/{container}/{path}.parquet
  Access:   DuckDB with httpfs or direct download + local cache
```

---

## 9. Standardization Roadmap

### Phase 1: Contract Alignment (No code sharing needed)

| Item | Effort | Impact |
|------|--------|--------|
| Document STAC item contract (this file) | Done | Prevents format drift |
| Document PostGIS table contract (this file) | Done | Prevents TiPG discovery failures |
| Document blob path conventions (this file) | Done | Prevents access failures |
| Align pgSTAC schema version pin | Small | Prevents schema mismatch |
| Wire ETL → TiTiler refresh webhook | Small | New tables visible immediately |
| Standardize health response top-level fields | Small | Enables platform-level health aggregation |

### Phase 2: Shared Infrastructure Package (`rmhgeo-common`)

Extractable modules (~800 lines):

| Module | Source | Purpose |
|--------|--------|---------|
| `rmhgeo.auth.token_cache` | TiTiler's `auth/cache.py` | Async-first token caching with TTL |
| `rmhgeo.auth.azure_credential` | Both apps | `DefaultAzureCredential` singleton + scopes |
| `rmhgeo.auth.gdal_config` | TiTiler's `auth/storage.py` | GDAL env var configuration |
| `rmhgeo.auth.postgres_oauth` | Both apps | PostgreSQL OAuth token acquisition |
| `rmhgeo.health.schema` | Both apps | Shared health response Pydantic models |
| `rmhgeo.constants` | Both apps | pgSTAC version, OAuth scopes, refresh intervals |

### Phase 3: Platform Manifest (Deployment unification)

```yaml
# platform.yaml — single source of truth for deployment
platform:
  name: rmhgeo
  version: 0.9.x
  pgstac_version: 0.9.8

apps:
  etl:
    name: rmhgeoapi
    image: rmhazureacr.azurecr.io/geospatial-worker
    app_service: rmhazuregeoapi
    role: etl-orchestrator

  service_layer:
    name: rmhtitiler
    image: rmhazureacr.azurecr.io/rmhtitiler
    app_service: rmhtitiler
    role: tile-server

shared:
  database:
    host: rmhpostgres.postgres.database.azure.com
    name: geopgflex
    schemas: [app, pgstac, geo, h3]

  storage:
    bronze: rmhazuregeobronze
    silver: rmhazuregeosilver
    gold: rmhazuregeo

  observability:
    app_insights_connection: "InstrumentationKey=..."
    namespace: rmhgeo-platform

  identity:
    managed_identity_client_id: "..."
    db_admin_name: rob634-db-admin
```

### Phase 4: System-in-a-Box CLI (Future)

```bash
rmhgeo deploy all          # Deploy both apps + verify health
rmhgeo deploy etl          # Deploy ETL only
rmhgeo deploy tiles        # Deploy tile server only
rmhgeo health              # Aggregate health from all apps
rmhgeo init                # First-time: create DB, schemas, storage, service bus
```

---

## 10. Contract Alignment — Implementation Status (06 MAR 2026)

Based on deep code analysis, here is the **complete** scope of contract alignment needed. No further exploration required.

### 10.1 Already Aligned (No work needed)

| Contract | Status | Notes |
|----------|--------|-------|
| STAC item format | Aligned | Standard STAC 1.0.0, `ddh:*` properties only, `geoetl:*` stripped at approval |
| STAC collection format | Aligned | Standard STAC 1.0.0 with `geo:iso3` extension. TiTiler has zero custom field dependencies |
| pgSTAC schema version | Aligned | Both use pgSTAC 0.9.8 tables. ETL pins `pypgstac==0.9.8`, TiTiler reads via `stac-fastapi.pgstac>=4.0.0` |
| PostGIS table structure | Aligned | ETL writes `id` (UUID PK) + `geom` (geometry with SRID) + GIST index. TiPG auto-discovers |
| Blob path conventions | Aligned | COG: `/vsiaz/{container}/{path}`, Zarr: `abfs://{container}/{path}` |
| Token refresh timing | Aligned | Both: 45-min refresh cycle, 5-min buffer, against 1-hour Azure token TTL |
| PostgreSQL OAuth scope | Aligned | Both: `https://ossrdbms-aad.database.windows.net/.default` |
| Storage OAuth scope | Aligned | Both: `https://storage.azure.com/.default` |
| App Insights instance | Aligned | Same `APPLICATIONINSIGHTS_CONNECTION_STRING` |

### 10.2 Webhook Integration — DEFERRED

**Not needed due to TiPG TTL-based catalog refresh** (`tipg_catalog_ttl_sec`, default 60s). New tables become visible within one TTL cycle without explicit webhook calls.

Vector pipeline already calls `refresh_tipg_collections()` for immediate visibility. Raster goes through pgSTAC, not TiPG, so no webhook needed.

### 10.3 Error Response Standardization — DONE (06 MAR 2026)

**Implemented**: `geotiler/errors.py` with `error_response()` helper and error code constants.

All custom endpoints now return the standard shape:
```json
{"error": "Human-readable message", "status": 503, "error_code": "CAPACITY_EXCEEDED"}
```

**Files updated:**
- `geotiler/errors.py` — NEW: `error_response()` + 10 error code constants
- `geotiler/routers/download.py` — 3 capacity errors, removed HTTPException import
- `geotiler/routers/h3_explorer.py` — 4 error returns (NOT_FOUND, SERVICE_UNAVAILABLE, BAD_REQUEST, QUERY_FAILED)
- `geotiler/routers/admin.py` — TiPG disabled (422), refresh failure (500)
- `geotiler/routers/diagnostics.py` — SQL validation (400), pool not initialized (503)
- `geotiler/middleware/azure_auth.py` — Auth failure (503, AUTH_UNAVAILABLE)

**Left unchanged**: TiTiler upstream endpoints (tiles, STAC, pgSTAC) — clients expect native shapes

### 10.4 Health Response Alignment — DONE (06 MAR 2026)

Both apps now share these top-level fields:

```json
{
  "status": "healthy|degraded|unhealthy",
  "app": "rmhgeoapi|rmhtitiler",
  "role": "etl-orchestrator|service-layer",
  "version": "0.x.x.x",
  "issues": ["..."]
}
```

**Changes made:**
- rmhtitiler `/health`: Added `app`, `role` fields. Added `unhealthy` status (all critical deps down)
- rmhtitiler `/livez`: Added `app` field
- rmhgeoapi `/api/health`: Added `app`, `role` fields. Added `issues` array (combines `warnings` + `errors`; originals kept for backward compat)
- rmhgeoapi `/api/livez`: Added `app` field
- Component detail structures remain app-specific (different concerns)

### 10.5 Observability Correlation — DONE (06 MAR 2026)

Both apps now use `service.namespace = "rmhgeo-platform"` for cross-app App Insights queries:

```kql
traces | where customDimensions["service.namespace"] == "rmhgeo-platform"
```

**Changes made:**
- `geotiler/infrastructure/telemetry.py`: `service.namespace` changed from `"geotiler"` to `"rmhgeo-platform"`
- `docker_service.py`: `service.namespace` changed from `"rmhgeoapi"` to `"rmhgeo-platform"`
- `service.name` stays app-specific (`geotiler`/`docker-worker` via env vars)
- `deployment.environment` stays sourced from `GEOTILER_OBS_ENVIRONMENT` / `ENVIRONMENT` respectively (different env var names, same values at deploy)

### 10.6 Dependency Version Alignment — DONE (06 MAR 2026)

| Package | Before | After |
|---------|--------|-------|
| `azure-keyvault-secrets` (TiTiler) | `>=4.7.0` | `>=4.8.0` |
| `adlfs` (ETL) | `>=2024.2.0` | `>=2024.4.1` |

### 10.7 Summary: Contract Alignment Status

| Category | Status | Date |
|----------|--------|------|
| Already aligned | 9 contracts verified | 06 MAR 2026 |
| Webhook wiring | Deferred — TiPG 60s TTL handles refresh | 06 MAR 2026 |
| Error response standardization | **DONE** — `geotiler/errors.py` + 6 files | 06 MAR 2026 |
| Health response alignment | **DONE** — `app`, `role`, `issues` in both apps | 06 MAR 2026 |
| Observability correlation | **DONE** — `service.namespace = "rmhgeo-platform"` | 06 MAR 2026 |
| Dependency versions | **DONE** — adlfs + keyvault aligned | 06 MAR 2026 |

**Phase 1 contract alignment is complete.** Phase 2 (shared package) and Phase 3 (platform manifest) remain future work.

---

## 11. Known Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| pgSTAC version drift between apps | High | Pin in platform manifest, validate at deploy |
| Storage account misconfiguration | High | Derive from single source (manifest or shared env) |
| TiPG can't find new tables | Medium | Wire refresh webhook from ETL completion |
| Health response incompatibility | Low | Phase 1 alignment, shared schema in Phase 2 |
| Token refresh race conditions | Low | Both apps handle this independently and correctly |
| DuckDB query compatibility | Low | Both use `>=1.1.0`, same parquet format |

---

## Appendix A: Full Environment Variable Cross-Reference

| Purpose | rmhgeoapi Env Var | rmhtitiler Env Var | Same Value? |
|---------|-------------------|-------------------|-------------|
| DB Host | `POSTGIS_HOST` | `GEOTILER_PG_HOST` | Yes |
| DB Name | `POSTGIS_DATABASE` | `GEOTILER_PG_DB` | Yes |
| DB User | `POSTGIS_USER` | `GEOTILER_PG_USER` | Yes |
| DB Port | `POSTGIS_PORT` | `GEOTILER_PG_PORT` | Yes |
| DB Password | `POSTGIS_PASSWORD` | `GEOTILER_PG_PASSWORD` | Yes |
| DB Auth Mode | `USE_MANAGED_IDENTITY` (bool) | `GEOTILER_PG_AUTH_MODE` (password/key_vault/managed_identity) | Equivalent |
| MI Client ID | `DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID` | `GEOTILER_PG_MI_CLIENT_ID` | Yes |
| Storage Account | `SILVER_STORAGE_ACCOUNT` | `GEOTILER_STORAGE_ACCOUNT` | Yes |
| App Insights | `APPLICATIONINSIGHTS_CONNECTION_STRING` | `APPLICATIONINSIGHTS_CONNECTION_STRING` | Yes (same key) |
| Environment | `ENVIRONMENT` | `GEOTILER_OBS_ENVIRONMENT` | Yes |
| App Name | `APP_NAME` | `GEOTILER_OBS_SERVICE_NAME` | Different values |
| Log Level | `LOG_LEVEL` | (Python logging default) | N/A |
| Observability | `OBSERVABILITY_MODE` | `GEOTILER_ENABLE_OBSERVABILITY` | Equivalent |
| TiTiler URL | `TITILER_BASE_URL` | (self) | ETL stores TiTiler's URL |
| Service Bus | `SERVICE_BUS_FQDN` | N/A | ETL only |
| App Mode | `APP_MODE` | N/A | ETL only |
| Key Vault | N/A | `GEOTILER_KEYVAULT_NAME` | TiTiler only |
| Feature: TiPG | N/A | `GEOTILER_ENABLE_TIPG` | TiTiler only |
| Feature: STAC | N/A | `GEOTILER_ENABLE_STAC_API` | TiTiler only |
| Feature: H3 | N/A | `GEOTILER_ENABLE_H3_DUCKDB` | TiTiler only |
| Feature: Downloads | N/A | `GEOTILER_ENABLE_DOWNLOADS` | TiTiler only |

## Appendix B: Dependency Version Alignment

Packages present in both apps (direct or transitive):

| Package | rmhgeoapi Pin | rmhtitiler Pin | Action |
|---------|--------------|----------------|--------|
| `azure-identity` | `>=1.16.1` | `>=1.16.1` | Aligned |
| `azure-keyvault-secrets` | `>=4.8.0` | `>=4.7.0` | Bump TiTiler to `>=4.8.0` |
| `adlfs` | `>=2024.2.0` | `>=2024.4.1` | Bump ETL to `>=2024.4.1` |
| `psutil` | `>=5.9.0` | `>=5.9.0` | Aligned |
| `duckdb` | `>=1.1.0` | `>=1.1.0` | Aligned |
| `pydantic` | `>=2.0.0` | (base image) | Aligned (both v2) |
| `psycopg` | `>=3.1.0` | (base image) | Aligned (both v3) |
| `asyncpg` | `>=0.29.0` | (base image) | Check base image version |
| `rasterio` | `>=1.3.1` | (base image) | Check base image version |
