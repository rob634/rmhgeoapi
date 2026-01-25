# Classification Enforcement & ADF Integration (E4)

**Last Updated**: 24 JAN 2026
**Epic**: E4 Security Zones / Externalization
**Goal**: Make `access_level` (OUO/Public/Restricted) mandatory and prepare for ADF integration
**Context**: Colleague configuring ADF; we need Python side ready with correct parameters
**Status**: Planned

---

## Background

Data classification (`access_level`) controls where data can be exported:
- **PUBLIC**: Can be copied to external-facing storage (ADF will handle this)
- **OUO** (Official Use Only): Internal only, ADF should reject export requests
- **RESTRICTED**: Highest restriction, no external access

Currently `access_level` is inconsistently enforced across the codebase. This work makes it:
1. **Mandatory** at Platform API entry point
2. **Type-safe** using `AccessLevel` enum throughout
3. **Fail-fast** in pipeline tasks if somehow missing

---

## Current State Analysis (07 JAN 2026)

| Location | Type | Default | Required | Issue |
|----------|------|---------|----------|-------|
| `PlatformRequest` | `str` | `"OUO"` | Yes | Not using enum |
| `AccessLevel` enum | `Enum` | N/A | N/A | Exists but unused |
| Job parameter schemas | `str` | `None` | No | Loses value |
| `PlatformMetadata` dataclass | `Optional[str]` | `None` | No | Loses value |
| `PlatformProperties` model | `Optional[AccessLevel]` | `None` | No | Uses enum but optional |

### Key Files

| File | Current State |
|------|---------------|
| `core/models/stac.py:57-62` | `AccessLevel` enum definition |
| `core/models/platform.py:147-151` | `PlatformRequest.access_level` field |
| `triggers/trigger_platform.py` | Translation functions |
| `jobs/process_raster_v2.py:92` | Job parameter schema |
| `jobs/raster_mixin.py:93-98` | `PLATFORM_PASSTHROUGH_SCHEMA` |
| `services/stac_metadata_helper.py:69` | `PlatformMetadata` dataclass |
| `infrastructure/data_factory.py` | ADF repository (ready for testing) |

---

## Phase 1: Enforce at Platform Level

**Goal**: Reject requests with invalid/missing classification at API entry point

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S4.CL.1 | Update `PlatformRequest.access_level` to use `AccessLevel` enum | Pending | `core/models/platform.py` |
| S4.CL.2 | Add Pydantic validator to normalize case (accept "OUO" → store as "ouo") | Pending | `core/models/platform.py` |
| S4.CL.3 | Make `access_level` required (remove default) OR keep secure default "ouo" | Pending | `core/models/platform.py` |
| S4.CL.4 | Update `_translate_to_coremachine()` to pass enum value (lowercase string) | Pending | `triggers/trigger_platform.py` |
| S4.CL.5 | Add validation tests for Platform API rejection of invalid values | Pending | `tests/` |

### Implementation Notes

```python
# core/models/platform.py - Change from:
access_level: str = Field(default="OUO", max_length=50, ...)

# To:
from core.models.stac import AccessLevel

access_level: AccessLevel = Field(
    default=AccessLevel.OUO,
    description="Data classification: public, ouo, restricted"
)

@field_validator('access_level', mode='before')
@classmethod
def normalize_access_level(cls, v):
    """Accept case-insensitive input, normalize to enum."""
    if isinstance(v, str):
        try:
            return AccessLevel(v.lower())
        except ValueError:
            raise ValueError(f"Invalid access_level '{v}'. Must be: public, ouo, restricted")
    return v
```

**Decision Point**: Keep `default=AccessLevel.OUO` (secure by default) or make truly required (no default). **Recommend keeping default** since OUO is the safe choice.

---

## Phase 2: Fail-Fast in Pipeline Tasks

**Goal**: Defense-in-depth - tasks fail immediately if access_level missing (shouldn't happen if Phase 1 works)

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S4.CL.6 | Add `access_level` to job schemas with `required: True` | Pending | `jobs/raster_mixin.py`, `jobs/process_raster_v2.py`, `jobs/process_vector.py` |
| S4.CL.7 | Add validation in STAC metadata creation (fail if missing) | Pending | `services/stac_metadata_helper.py` |
| S4.CL.8 | Add validation in promote handlers (data export tasks) | Pending | `services/promote_service.py` |
| S4.CL.9 | Update `PlatformMetadata` dataclass to require access_level | Pending | `services/stac_metadata_helper.py` |
| S4.CL.10 | Add checkpoints logging for access_level at key stages | Pending | Various handlers |

### Implementation Notes for S4.CL.6

```python
# jobs/raster_mixin.py - Update PLATFORM_PASSTHROUGH_SCHEMA:
PLATFORM_PASSTHROUGH_SCHEMA = {
    'dataset_id': {'type': 'str', 'default': None},
    'resource_id': {'type': 'str', 'default': None},
    'version_id': {'type': 'str', 'default': None},
    'access_level': {
        'type': 'str',
        'required': True,  # Now required!
        'allowed': ['public', 'ouo', 'restricted']
    },
}
```

### Implementation Notes for S4.CL.7

```python
# services/stac_metadata_helper.py - Add validation in augment_item():
def augment_item(self, item_dict, ..., platform: Optional[PlatformMetadata] = None, ...):
    # Fail fast if platform metadata provided but access_level missing
    if platform and not platform.access_level:
        raise ValueError(
            "access_level is required for STAC item creation. "
            "This is a pipeline bug - access_level should be set at Platform API."
        )
```

---

## Phase 3: ADF Integration Testing

**Goal**: Verify Python can call ADF and pass classification parameter

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S4.ADF.1 | Create `/api/admin/adf/health` endpoint exposing health_check() | Pending | `triggers/admin/` |
| S4.ADF.2 | Create `/api/admin/adf/pipelines` endpoint listing available pipelines | Pending | `triggers/admin/` |
| S4.ADF.3 | Verify ADF env vars are set (`ADF_SUBSCRIPTION_ID`, `ADF_FACTORY_NAME`) | Pending | Azure portal |
| S4.ADF.4 | Test trigger_pipeline() with simple test pipeline (colleague creates) | Pending | Manual test |
| S4.ADF.5 | Add access_level to ADF pipeline parameters when triggering | Pending | Future promote job |

### ADF Test Endpoint Implementation

```python
# triggers/admin/adf.py (new file)
from infrastructure.data_factory import get_data_factory_repository

def adf_health(req: func.HttpRequest) -> func.HttpResponse:
    """GET /api/admin/adf/health - Test ADF connectivity."""
    try:
        adf_repo = get_data_factory_repository()
        result = adf_repo.health_check()
        return func.HttpResponse(json.dumps(result), status_code=200, ...)
    except Exception as e:
        return func.HttpResponse(json.dumps({
            "status": "error",
            "error": str(e),
            "hint": "Check ADF_SUBSCRIPTION_ID, ADF_RESOURCE_GROUP, ADF_FACTORY_NAME env vars"
        }), status_code=500, ...)
```

---

## Testing Checklist

After implementation, verify:

- [ ] `POST /api/platform/submit` with `access_level: "INVALID"` returns 400
- [ ] `POST /api/platform/submit` with `access_level: "OUO"` (uppercase) succeeds
- [ ] `POST /api/platform/submit` with `access_level: "ouo"` (lowercase) succeeds
- [ ] `POST /api/platform/submit` without `access_level` uses default "ouo"
- [ ] STAC items have `platform:access_level` property populated
- [ ] Job parameters include `access_level` in task parameters
- [ ] `GET /api/admin/adf/health` returns ADF status (Phase 3)

---

## Acceptance Criteria

**Phase 1 Complete When**:
- Platform API validates and normalizes access_level on entry
- Invalid values rejected with clear error message
- Existing Platform API tests pass

**Phase 2 Complete When**:
- Pipeline tasks fail fast if access_level missing
- All STAC items have access_level in metadata
- Checkpoints logged at key stages

**Phase 3 Complete When**:
- ADF health endpoint working
- Can list pipelines from Python
- Ready to trigger actual export pipeline (pending ADF build)
