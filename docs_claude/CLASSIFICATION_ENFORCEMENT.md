# Classification Enforcement & ADF Integration (E4)

**Last Updated**: 25 JAN 2026
**Epic**: E4 Security Zones / Externalization
**Goal**: Unify access_level data model and enforce across SQL ↔ Python ↔ Service Bus
**Context**: Colleague configuring ADF; we need Python side ready with correct parameters
**Status**: Phase 0 COMPLETE

---

## Background

Data classification (`access_level`) controls where data can be exported:
- **PUBLIC**: Can be copied to external-facing storage (ADF will handle this)
- **OUO** (Official Use Only): Internal only, ADF should reject export requests
- **RESTRICTED**: Highest restriction, no external access

**Current Problem**: Access level is fragmented across the codebase with:
- Two duplicate enums (`AccessLevel` and `Classification`)
- SQL ENUM missing RESTRICTED value
- No type safety at API entry point
- Plain strings in job parameters and Service Bus messages

This work:
1. **Unifies** the data model with a single source of truth (Phase 0)
2. **Makes it mandatory** at Platform API entry point (Phase 1)
3. **Enforces fail-fast** in pipeline tasks if missing (Phase 2)
4. **Tests ADF integration** for external delivery (Phase 3)

---

## Phase 0: Data Model Unification

**Goal**: Single `AccessLevel` model as source of truth for Python, SQL, and Service Bus

### Current State Analysis (25 JAN 2026)

| Location | Implementation | Values | Issue |
|----------|---------------|--------|-------|
| `core/models/stac.py:57-62` | `AccessLevel(str, Enum)` | public, ouo, restricted | ✅ Complete definition |
| `core/models/promoted.py:11-14` | `Classification(str, Enum)` | public, ouo | ❌ DUPLICATE, missing restricted |
| `core/models/platform.py:147-151` | `str` field | "OUO" default | ❌ Not using enum |
| `core/models/approval.py:5` | imports `Classification` | public, ouo | ❌ Uses wrong enum |
| `infrastructure/approval_repository.py:49-50` | `approved_schema.sql` | public, ouo | ❌ SQL ENUM missing restricted |
| `jobs/raster_mixin.py:93-98` | `'type': 'str'` | any string | ❌ No validation |
| Service Bus messages | JSON string | varies | ❌ No schema enforcement |

### Stories

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S4.DM.1 | Remove `Classification` enum from promoted.py | ✅ Done | `core/models/promoted.py` |
| S4.DM.2 | Update `DatasetApproval` to use `AccessLevel` | ✅ Done | `core/models/approval.py` |
| S4.DM.3 | Add `sql_type_name()` and `sql_create_type()` to `AccessLevel` | ✅ Done | `core/models/stac.py` |
| S4.DM.4 | SQL ENUM includes 'restricted' (schema rebuild) | ✅ Done | `core/schema/sql_generator.py` |
| S4.DM.5 | Update approval_repository to use AccessLevel | ✅ Done | `infrastructure/approval_repository.py` |
| S4.DM.6 | Add `normalize_access_level()` helper for reuse | ✅ Done | `core/models/stac.py` |

### Implementation Details

#### S4.DM.1: Remove Classification Enum

```python
# core/models/promoted.py - DELETE these lines:
class Classification(str, Enum):
    PUBLIC = "public"  # Public - openly accessible
    OUO = "ouo"        # Official Use Only - restricted access
```

#### S4.DM.2: Update DatasetApproval

```python
# core/models/approval.py - Change:
from core.models.stac import AccessLevel  # Instead of: from .promoted import Classification

class DatasetApproval(BaseModel):
    classification: AccessLevel = Field(
        default=AccessLevel.OUO,
        description="Data classification: public (triggers ADF), ouo, or restricted"
    )
```

#### S4.DM.3: Add SQL DDL Generation to AccessLevel

```python
# core/models/stac.py
from typing import ClassVar

class AccessLevel(str, Enum):
    """Data access classification levels - single source of truth."""
    PUBLIC = "public"
    OUO = "ouo"
    RESTRICTED = "restricted"

    # SQL DDL generation
    __sql_type__: ClassVar[str] = "access_level_enum"
    __sql_values__: ClassVar[list[str]] = ["public", "ouo", "restricted"]

    @classmethod
    def sql_create_type(cls) -> str:
        """Generate CREATE TYPE statement."""
        values = ", ".join(f"'{v}'" for v in cls.__sql_values__)
        return f"CREATE TYPE {cls.__sql_type__} AS ENUM ({values});"

    @classmethod
    def sql_add_value(cls, value: str, after: str | None = None) -> str:
        """Generate ALTER TYPE to add value."""
        position = f" AFTER '{after}'" if after else ""
        return f"ALTER TYPE {cls.__sql_type__} ADD VALUE IF NOT EXISTS '{value}'{position};"
```

#### S4.DM.4: SQL Migration for RESTRICTED Value

```sql
-- Run this migration BEFORE deploying new code
-- Safe: ADD VALUE IF NOT EXISTS is idempotent

-- Check if type exists with correct values
DO $$
BEGIN
    -- Add 'restricted' if not present
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum
        WHERE enumtypid = 'app.access_level_enum'::regtype
        AND enumlabel = 'restricted'
    ) THEN
        ALTER TYPE app.access_level_enum ADD VALUE 'restricted';
    END IF;
END $$;
```

#### S4.DM.6: Reusable Field Definition

```python
# core/models/stac.py - Add after AccessLevel class:
from pydantic import field_validator

def access_level_field(default: AccessLevel = AccessLevel.OUO, required: bool = False):
    """Create a reusable AccessLevel field with case normalization."""
    return Field(
        default=default if not required else ...,
        description="Data classification: public, ouo, or restricted"
    )

def access_level_validator(field_name: str = 'access_level'):
    """Create validator that normalizes case-insensitive input."""
    @field_validator(field_name, mode='before')
    @classmethod
    def normalize(cls, v):
        if isinstance(v, str):
            try:
                return AccessLevel(v.lower())
            except ValueError:
                raise ValueError(f"Invalid {field_name} '{v}'. Must be: public, ouo, restricted")
        return v
    return normalize
```

### Testing Checklist (Phase 0)

- [ ] `Classification` enum no longer exists in codebase
- [ ] `AccessLevel` has all 3 values (public, ouo, restricted)
- [ ] `DatasetApproval.classification` uses `AccessLevel` enum
- [ ] SQL ENUM `access_level_enum` includes 'restricted' value
- [ ] Existing approval records with 'public' or 'ouo' still work
- [ ] `AccessLevel.sql_create_type()` generates valid DDL
- [ ] Unit tests pass for case normalization (OUO → ouo)

### Migration Order

1. **Run SQL migration first** (add 'restricted' to ENUM)
2. Deploy code changes (delete Classification, update imports)
3. Verify approval endpoints still work
4. Proceed to Phase 1

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
