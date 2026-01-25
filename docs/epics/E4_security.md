# Epic E4: Security & Externalization

**Type**: Enabler (Compliance)
**Status**: Partial
**Last Updated**: 24 JAN 2026

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
| F4.1 Classification Enforcement | 🚧 | access_level mandatory at Platform API |
| F4.2 Approval Workflow | ✅ | QA review before STAC publication |
| F4.3 ADF External Delivery | 📋 | Trigger ADF for PUBLIC data |

---

## Feature Summaries

### F4.1: Classification Enforcement
Make `access_level` (OUO/Public/Restricted) mandatory:
- Validate at Platform API entry point (PlatformRequest)
- Normalize case (accept "OUO" → store as "ouo")
- Fail-fast in pipeline tasks if somehow missing
- Pass to STAC item properties

**Classifications**:
| Level | Meaning | On Approval |
|-------|---------|-------------|
| `ouo` | Official Use Only (default) | Update STAC only |
| `public` | Can be externalized | Trigger ADF pipeline |
| `restricted` | Highest restriction | Update STAC only |

### F4.2: Approval Workflow
QA gate for datasets before publication:
1. Job completes → STAC item created with `app:published=false`
2. Approval record created automatically
3. Reviewer approves/rejects via `/api/approvals/{id}/approve`
4. On approval: STAC updated with `app:published=true`

**API Endpoints**:
- `GET /api/approvals?status=pending` - List pending
- `POST /api/approvals/{id}/approve` - Approve
- `POST /api/approvals/{id}/reject` - Reject

### F4.3: ADF External Delivery (Planned)
Azure Data Factory integration for PUBLIC data:
- Health check endpoint for ADF connectivity
- Trigger pipeline with classification parameter
- Track ADF run ID in approval record

---

## Approval Status Flow

```
PENDING ──▶ APPROVED ──▶ (published=true)
    │
    └────▶ REJECTED ──▶ (can resubmit)
```

---

## Database Schema

**Table**: `app.dataset_approvals`
- `approval_id`, `job_id`, `job_type`
- `classification` (ouo/public)
- `status` (pending/approved/rejected)
- `stac_item_id`, `stac_collection_id`
- `reviewer`, `notes`, `rejection_reason`
- `adf_run_id` (for PUBLIC data)

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
- `CLASSIFICATION_ENFORCEMENT.md` - Classification implementation
