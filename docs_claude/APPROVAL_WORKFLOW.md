# Dataset Approval Workflow (F4.AP)

**Last Updated**: 24 JAN 2026
**Epic**: E4 Security Zones / Externalization
**Goal**: QA workflow for reviewing datasets before STAC publication
**Status**: IN PROGRESS

---

## Background

When ETL jobs complete, datasets need human review before being marked "published" in STAC.
Classification determines post-approval action:
- **OUO** (Official Use Only): Just update STAC `app:published=true`
- **PUBLIC**: Trigger ADF pipeline for external distribution + update STAC

---

## Database Schema

### Table: `app.dataset_approvals`

| Column | Type | Description |
|--------|------|-------------|
| `approval_id` | VARCHAR(64) PK | Unique approval ID |
| `job_id` | VARCHAR(64) | Reference to completed job |
| `job_type` | VARCHAR(100) | Type of job (process_vector, etc.) |
| `classification` | ENUM | `public` or `ouo` |
| `status` | ENUM | `pending`, `approved`, `rejected` |
| `stac_item_id` | VARCHAR(100) | The STAC item to publish |
| `stac_collection_id` | VARCHAR(100) | The STAC collection |
| `reviewer` | VARCHAR(200) | Who approved/rejected |
| `notes` | TEXT | Review notes |
| `rejection_reason` | TEXT | Rejection reason (if rejected) |
| `adf_run_id` | VARCHAR(100) | ADF pipeline run ID (if public) |
| `created_at` | TIMESTAMP | When approval was created |
| `reviewed_at` | TIMESTAMP | When reviewed |
| `updated_at` | TIMESTAMP | Last update |

### Enum: `ApprovalStatus`

Values: `pending`, `approved`, `rejected`

### STAC Item Updates (on approval)

- `app:published` = true
- `app:published_at` = timestamp
- `app:approved_by` = reviewer

---

## Implementation Status

### Phase 1: Core Infrastructure - COMPLETE (16 JAN 2026)

| Story | Description | Status |
|-------|-------------|--------|
| S4.AP.1 | Create `core/models/approval.py` with `DatasetApproval` model + `ApprovalStatus` enum | Done |
| S4.AP.2 | Export from `core/models/__init__.py` | Done |
| S4.AP.3 | Add table/indexes to `core/schema/sql_generator.py` | Done |
| S4.AP.4 | Create `infrastructure/approval_repository.py` with CRUD | Done |
| S4.AP.5 | Create `services/approval_service.py` with business logic | Done |
| S4.AP.6 | Create `triggers/admin/admin_approvals.py` HTTP endpoints | Done |
| S4.AP.7 | Register blueprint in `function_app.py` | Done |
| S4.AP.8 | Deploy + rebuild schema | Pending |

### Phase 2: Integration (Future)

| Story | Description | Status |
|-------|-------------|--------|
| S4.AP.9 | Hook job completion to create approval records | Done (22 JAN) |
| S4.AP.10 | Wire viewer UI approve/reject buttons | Pending |
| S4.AP.11 | ADF integration for public data | Pending |

---

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/approvals` | List approvals (query: ?status=pending&limit=50) |
| GET | `/api/approvals/{id}` | Get specific approval with full details |
| POST | `/api/approvals/{id}/approve` | Approve (body: {reviewer, notes}) |
| POST | `/api/approvals/{id}/reject` | Reject (body: {reviewer, reason} - reason required) |
| POST | `/api/approvals/{id}/resubmit` | Resubmit rejected item back to pending |
| POST | `/api/approvals/test` | Create test approval (dev only) |

---

## Key Files

| File | Purpose |
|------|---------|
| `core/models/approval.py` | DatasetApproval model + ApprovalStatus enum |
| `infrastructure/approval_repository.py` | Database CRUD |
| `services/approval_service.py` | Business logic (approve/reject/STAC update) |
| `triggers/admin/admin_approvals.py` | HTTP endpoints |
| `core/schema/sql_generator.py` | DDL generation |

---

## Verification Commands

```bash
# After deploy - use ensure (SAFE - additive, creates missing tables without dropping data)
curl -X POST ".../api/dbadmin/maintenance?action=ensure&confirm=yes"

# Or full rebuild (DESTRUCTIVE - drops ALL data, use only for fresh start)
# curl -X POST ".../api/dbadmin/maintenance?action=rebuild&confirm=yes"

# Create test approval
curl -X POST .../api/approvals/test \
  -H "Content-Type: application/json" \
  -d '{"job_id": "test-job-123", "classification": "ouo"}'

# List pending
curl ".../api/approvals?status=pending"

# Approve
curl -X POST .../api/approvals/{id}/approve \
  -H "Content-Type: application/json" \
  -d '{"reviewer": "test@example.com", "notes": "Looks good"}'
```

---

## Workflow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      JOB COMPLETION                              │
├─────────────────────────────────────────────────────────────────┤
│  Job Completes                                                   │
│       ↓                                                          │
│  STAC item created with app:published=false                      │
│       ↓                                                          │
│  _global_platform_callback() triggered                           │
│       ↓                                                          │
│  Approval record created (status=PENDING)                        │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                      HUMAN REVIEW                                │
├─────────────────────────────────────────────────────────────────┤
│  Reviewer views /api/approvals?status=pending                    │
│       ↓                                                          │
│  Reviewer inspects data in viewer                                │
│       ↓                                                          │
│  APPROVE or REJECT                                               │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌───────────────────────┬─────────────────────────────────────────┐
│      APPROVED         │              REJECTED                    │
├───────────────────────┼─────────────────────────────────────────┤
│  Update STAC item:    │  Record rejection_reason                 │
│  app:published=true   │  Status → REJECTED                       │
│  app:published_at=now │  Notify submitter (future)               │
│  app:approved_by=who  │                                          │
│       ↓               │                                          │
│  If classification=   │                                          │
│  PUBLIC:              │                                          │
│  Trigger ADF pipeline │                                          │
└───────────────────────┴─────────────────────────────────────────┘
```
