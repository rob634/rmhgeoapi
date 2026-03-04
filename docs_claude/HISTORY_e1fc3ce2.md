# Project History Archive — JAN 2026 and Earlier

**Archived**: 04 MAR 2026
**Covers**: 21 DEC 2025 - 21 JAN 2026

---

## 21 JAN 2026: Docker Worker Application Insights AAD Auth Fix ✅

**Status**: ✅ **COMPLETE**
**Epic**: E7 Pipeline Infrastructure
**Feature**: F7.12.E Docker Worker OpenTelemetry

### Problem

Docker worker logs were not appearing in Application Insights. Investigation revealed three issues:
1. Wrong App Insights connection string (different instrumentation key)
2. App Insights has `DisableLocalAuth=true` requiring Entra ID authentication
3. Missing RBAC role for managed identity

### Solution

1. **Updated connection string** - Pointed Docker worker to same App Insights as Function App (`rmhazuregeoapi`)
2. **Added AAD authentication support** - Updated `configure_azure_monitor_telemetry()` to detect `APPLICATIONINSIGHTS_AUTHENTICATION_STRING=Authorization=AAD` and pass `DefaultAzureCredential`
3. **Assigned RBAC role** - "Monitoring Metrics Publisher" to Docker worker's managed identity

---

## 21 JAN 2026: Platform Routing Improvements ✅

**Status**: ✅ **COMPLETE**

1. **Platform Default to Docker** - When `docker_worker_enabled=true`, platform raster jobs automatically route to Docker worker
2. **Endpoint Consolidation** - Removed `/api/platform/raster` and `/api/platform/raster-collection`. All via unified `/api/platform/submit`
3. **Expected Data Type Validation** - Added validation for `expected_data_type` parameter

---

## 21 JAN 2026: Artifact Registry - Blob Version Tracking ✅

Added `blob_version_id` field to artifact tracking. Captures Azure blob version ID for recovery and audit.

---

## 20-21 JAN 2026: Artifact Registry (Core) ✅

Internal artifact registry with supersession/lineage support. `artifact_id` (UUID), `content_hash`, `supersedes`/`superseded_by` links, `client_refs` JSONB.

---

## 15 JAN 2026: Platform API Diagnostics (F7.12) ✅

Endpoints: `/api/platform/health`, `/api/platform/failures`, `/api/platform/lineage/{request_id}`, `/api/platform/validate`. Note: lineage and validate later removed in v0.9.12.1.

---

## 12 JAN 2026: F7.12 Docker Worker Infrastructure ✅

Deployed Docker worker (`rmhheavyapi`) for long-running tasks. Same CoreMachine, different trigger. FastAPI + health endpoints. Identity-based auth (no secrets).

---

## 12 JAN 2026: F7.13 Docker Job Definitions (Phase 1) ✅

Checkpoint/resume infrastructure: `checkpoint_phase`, `checkpoint_data`, `checkpoint_updated_at`. BackgroundQueueWorker integrated into FastAPI service.

---

## 12 JAN 2026: F7.12 Logging Architecture Consolidation ✅

Global log context, consolidated debug flags (4→2), App Insights export, JSONL log dump system.

---

## 12 JAN 2026: F7.16 Code Maintenance (Phase 1) ✅

Split `db_maintenance.py` from 2,673 to 1,922 lines. Extracted `data_cleanup.py` and `geo_table_operations.py`.

---

## 09 JAN 2026: F7.8 Unified Metadata Architecture ✅

Pydantic-based metadata models: `BaseMetadata` → `VectorMetadata` → `RasterMetadata`. External refs via `app.dataset_refs`.

---

## 09 JAN 2026: F12.5 Web Interface DRY Consolidation ✅

Consolidated duplicate CSS/JS across web interfaces into `COMMON_CSS` and `COMMON_JS`.

---

## 07 JAN 2026: F9.1 FATHOM Rwanda Pipeline ✅

End-to-end FATHOM flood data on Rwanda: 1,872 TIF files, 234 Phase 1 tasks + 39 Phase 2 tasks, ~17 min total.

---

## 06 JAN 2026: System Diagnostics & Configuration Drift Detection ✅

System snapshot infrastructure with drift detection via SHA256 hash of config fields.

---

## 05 JAN 2026: Thread Safety Fix for BlobRepository ✅

Double-checked locking pattern for container client caching race condition.

---

## 02 JAN 2026: Root Folder Cleanup & Consolidation ✅

Reduced root folders 26→22, cleaned 52 root files (~1.8MB).

---

## 01 JAN 2026: DDL Utilities Consolidation ✅

Centralized `ddl_utils.py` with IndexBuilder, TriggerBuilder, CommentBuilder, SchemaUtils.

---

## 21 DEC 2025: FATHOM Flood Data ETL Pipeline ✅

Two-phase ETL pipeline for FATHOM global flood data. Test region: Cote d'Ivoire.

---
