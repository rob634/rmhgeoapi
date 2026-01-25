# Epic E4: Security & Externalization

**Type**: Enabler (Compliance)
**Status**: Operational (F4.2 ✅, F4.1/F4.3 need type-safety work)
**Last Updated**: 25 JAN 2026

---

## Value Statement

Control data classification and enable secure external delivery. Ensures PUBLIC data can be exported to external systems while OUO/RESTRICTED data remains internal.

---

## Architecture

```
Job Completion                Approval                      Delivery
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│ STAC item       │         │ Human Review    │         │ OUO: Internal   │
│ created with    │────────▶│ (approve/reject)│────────▶│ only            │
│ published=false │         │                 │         ├─────────────────┤
└─────────────────┘         └─────────────────┘         │ PUBLIC: Trigger │
                                                        │ ADF pipeline    │
                                                        └─────────────────┘
```

**Key Principle**: All data defaults to OUO (Official Use Only). Classification must be explicit. PUBLIC classification triggers ADF pipeline for external delivery upon approval.

---

## Features

| Feature | Status | Scope |
|---------|--------|-------|
| F4.1 Classification Enforcement | 🚧 | AccessLevel enum exists but not enforced at API entry |
| F4.2 Approval Workflow | ✅ | Complete: models, repository, service, endpoints, auto-creation |
| F4.3 ADF External Delivery | 🚧 | Code complete, needs env config and HTTP endpoints |

---

## Feature Summaries

### F4.1: Classification Enforcement 🚧

**Current State**:
- `AccessLevel` enum defined in `core/models/stac.py`
- `Classification` enum defined in `core/models/promoted.py` (duplicate)
- `PlatformRequest.access_level` uses `str` type (not enum)
- Classification flows through pipeline but not type-safe

**Needed**:
- Unified `AccessLevel` Pydantic model for SQL ↔ Python ↔ Service Bus
- Use enum in `PlatformRequest` with validator
- Consistent case normalization

**Classifications**:
| Level | Meaning | On Approval |
|-------|---------|-------------|
| `ouo` | Official Use Only (default) | Update STAC only |
| `public` | Can be externalized | Trigger ADF pipeline |
| `restricted` | Highest restriction | Update STAC only |

### F4.2: Approval Workflow ✅ COMPLETE

**Implemented (16-22 JAN 2026)**:
- `DatasetApproval` model with full lifecycle
- `ApprovalStatus` enum: pending, approved, rejected, revoked
- `ApprovalRepository` with CRUD operations (729 lines)
- `ApprovalService` with business logic (619 lines)
- Auto-creation hook in CoreMachine job completion
- STAC item updates on approval/revocation

**Admin Endpoints** (`/api/approvals/*`):
| Route | Method | Purpose |
|-------|--------|---------|
| `/api/approvals` | GET | List with filters |
| `/api/approvals/{id}` | GET | Get specific |
| `/api/approvals/{id}/approve` | POST | Approve |
| `/api/approvals/{id}/reject` | POST | Reject |
| `/api/approvals/{id}/resubmit` | POST | Retry rejected |
| `/api/approvals/test` | POST | Create test (dev) |

**Platform Endpoints** (`/api/platform/*`):
| Route | Method | Purpose |
|-------|--------|---------|
| `/api/platform/approve` | POST | Approve by any ID type |
| `/api/platform/revoke` | POST | Revoke approved |
| `/api/platform/approvals` | GET | List |
| `/api/platform/approvals/{id}` | GET | Get single |
| `/api/platform/approvals/status` | GET | Bulk status lookup |

### F4.3: ADF External Delivery 🚧

**Implemented**:
- `AzureDataFactoryRepository` (647 lines)
- `trigger_pipeline()`, `health_check()`, `list_pipelines()`
- Integration in `ApprovalService._trigger_adf_pipeline()`
- Called automatically when PUBLIC data approved

**Needs**:
- Environment variables: `ADF_SUBSCRIPTION_ID`, `ADF_FACTORY_NAME`
- HTTP endpoints for health/testing (`/api/admin/adf/*`)
- ADF pipeline creation (external to this codebase)

---

## Approval Status Flow

```
PENDING ──▶ APPROVED ──▶ (published=true)
    │           │
    │           └──▶ REVOKED (unpublish)
    │
    └────▶ REJECTED ──▶ (can resubmit) ──▶ PENDING
```

---

## Database Schema

**Table**: `app.dataset_approvals`

| Column | Type | Description |
|--------|------|-------------|
| `approval_id` | VARCHAR(64) PK | SHA256-based ID (apr-{hash}) |
| `job_id` | VARCHAR(64) | Reference to completed job |
| `job_type` | VARCHAR(100) | Type of job |
| `classification` | ENUM | `public` or `ouo` |
| `status` | ENUM | `pending`, `approved`, `rejected`, `revoked` |
| `stac_item_id` | VARCHAR(100) | STAC item reference |
| `stac_collection_id` | VARCHAR(100) | STAC collection reference |
| `reviewer` | VARCHAR(200) | Who approved/rejected |
| `notes` | TEXT | Review notes |
| `rejection_reason` | TEXT | Rejection reason |
| `adf_run_id` | VARCHAR(100) | ADF pipeline run ID |
| `revoked_at` | TIMESTAMP | Revocation timestamp |
| `revoked_by` | VARCHAR(200) | Who revoked |
| `revocation_reason` | TEXT | Why revoked |
| `created_at` | TIMESTAMP | Record creation |
| `reviewed_at` | TIMESTAMP | When reviewed |
| `updated_at` | TIMESTAMP | Last update |

---

## Key Files

| File | Lines | Purpose |
|------|-------|---------|
| `core/models/approval.py` | 225 | DatasetApproval model, ApprovalStatus enum |
| `core/models/stac.py` | - | AccessLevel enum |
| `infrastructure/approval_repository.py` | 729 | CRUD operations |
| `infrastructure/data_factory.py` | 647 | ADF repository |
| `services/approval_service.py` | 619 | Business logic |
| `triggers/admin/admin_approvals.py` | 478 | Admin HTTP endpoints |
| `triggers/trigger_approvals.py` | 837 | Platform HTTP endpoints |

---

## Dependencies

| Depends On | Enables |
|------------|---------|
| E7 Job Lifecycle | External data delivery |
| Azure Data Factory | Partner data sharing |

---

## Implementation Details

See `docs_claude/`:
- `APPROVAL_WORKFLOW.md` - Approval system details
- `CLASSIFICATION_ENFORCEMENT.md` - Classification implementation plan
