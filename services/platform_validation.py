# ============================================================================
# PLATFORM VALIDATION SERVICE
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Service - V0.9 validation using Asset + Release repos
# PURPOSE: Validate submit parameters before job creation (dry_run support)
# CREATED: 31 JAN 2026
# LAST_REVIEWED: 22 FEB 2026
# EXPORTS: validate_version_lineage, VersionValidationResult
# DEPENDENCIES: infrastructure.AssetRepository, infrastructure.ReleaseRepository
# ============================================================================
"""
Platform Validation Service - V0.9 Asset/Release semantics.

Provides validation logic for platform submit operations, specifically
for version lineage validation to prevent race conditions.

This service is used by:
- dry_run=true requests (return validation result without job creation)
  via triggers/trigger_platform_status.py

V0.9 Semantics (22 FEB 2026):
- Asset IS the lineage container — asset_id replaces lineage_id
- Overwrite targets draft releases only — approved releases are immutable
- No revoke-first workflow — drafts coexist with approved versions
- Multiple approved releases allowed (v1+v2 simultaneously)
- Version assigned at approval, not at submit

Overwrite Rules (V0.9):
| Release State    | overwrite=True | Result                                   |
|------------------|----------------|------------------------------------------|
| Draft exists     | True           | OK - Re-process draft (revision++)       |
| Draft exists     | False          | OK - Idempotent return of existing draft  |
| No draft exists  | True or False  | OK - Create new draft release             |
| (Approved releases are never overwritten — they are immutable)            |

Version Chaining Rules (V0.9):
| previous_version_id | Asset State               | Result                          |
|---------------------|---------------------------|---------------------------------|
| null                | No asset or no releases   | OK - First submission           |
| null                | Has approved versions     | OK - Creates new draft release  |
| v2.0                | v2.0 exists and approved  | OK - Chain from v2.0            |
| v2.0                | v2.0 not approved         | WARN - v2.0 not yet approved    |
| v2.0                | v2.0 doesn't exist        | REJECT - v2.0 not found         |

Exports:
    validate_version_lineage: Validate submit parameters against asset/release state
    VersionValidationResult: Typed result from validation
"""

from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "PlatformValidation")


@dataclass
class VersionValidationResult:
    """
    Result of version lineage validation.

    Attributes:
        valid: True if validation passed
        asset_id: Asset ID (the asset IS the lineage container)
        asset_exists: True if asset has existing releases
        current_latest: Info about current latest approved version (if exists)
        draft_in_progress: Info about existing draft release (if exists)
        warnings: List of validation warnings/errors
        suggested_params: Suggested parameters for submit
    """
    valid: bool
    asset_id: str
    asset_exists: bool
    current_latest: Optional[Dict[str, Any]] = None
    draft_in_progress: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    suggested_params: Dict[str, Any] = field(default_factory=dict)

    # Backward-compat aliases for callers that still use lineage_id
    @property
    def lineage_id(self) -> str:
        return self.asset_id

    @property
    def lineage_exists(self) -> bool:
        return self.asset_exists

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON response."""
        return {
            'valid': self.valid,
            'asset_id': self.asset_id,
            'asset_exists': self.asset_exists,
            'current_latest': self.current_latest,
            'draft_in_progress': self.draft_in_progress,
            'warnings': self.warnings,
            'suggested_params': self.suggested_params,
            # Backward-compat keys for existing callers
            'lineage_id': self.asset_id,
            'lineage_exists': self.asset_exists,
        }


def validate_version_lineage(
    platform_id: str,
    platform_refs: Dict[str, Any],
    previous_version_id: Optional[str],
    overwrite: bool = False,
    **kwargs  # Accept but ignore legacy params
) -> VersionValidationResult:
    """
    Validate submit parameters for platform submit.

    V0.9: Uses Asset + Release repos directly. The Asset IS the lineage.
    Drafts coexist with approved versions — no revoke-first workflow.
    Overwrite targets draft releases only — approved releases are immutable.

    Args:
        platform_id: Platform identifier (e.g., "ddh")
        platform_refs: Full platform refs including version_id
        previous_version_id: The previous version ID provided by B2B app (or None)
        overwrite: If True, attempting to re-process existing draft
        **kwargs: Accepts legacy params silently

    Returns:
        VersionValidationResult with validation outcome and suggestions
    """
    from infrastructure import AssetRepository, ReleaseRepository
    from core.models.asset import Asset

    dataset_id = platform_refs.get('dataset_id')
    resource_id = platform_refs.get('resource_id')

    asset_repo = AssetRepository()
    release_repo = ReleaseRepository()

    # Find asset (the lineage container in V0.9)
    asset = asset_repo.get_by_identity(platform_id, dataset_id, resource_id)
    asset_id = asset.asset_id if asset else Asset.generate_asset_id(platform_id, dataset_id, resource_id)
    asset_exists = asset is not None

    # Get latest approved release
    latest_release = release_repo.get_latest(asset.asset_id) if asset else None
    current_latest = None
    if latest_release:
        current_latest = {
            'version_id': latest_release.version_id,
            'approval_state': latest_release.approval_state.value if hasattr(latest_release.approval_state, 'value') else str(latest_release.approval_state)
        }

    # Get existing draft (if any)
    existing_draft = release_repo.get_draft(asset.asset_id) if asset else None
    draft_in_progress = None
    if existing_draft:
        draft_in_progress = {
            'release_id': existing_draft.release_id,
            'processing_status': existing_draft.processing_status.value if hasattr(existing_draft.processing_status, 'value') else str(existing_draft.processing_status),
            'revision': existing_draft.revision,
        }

    warnings: List[str] = []
    valid = True

    # Compute suggested version ordinal
    suggested_version_ordinal = 1
    if asset:
        releases = release_repo.list_by_asset(asset.asset_id)
        if releases:
            max_ordinal = max((r.version_ordinal or 0) for r in releases)
            suggested_version_ordinal = max_ordinal + 1

    suggested_previous = None
    if current_latest:
        suggested_previous = current_latest.get('version_id')

    logger.debug(
        f"Validating: previous_version_id={previous_version_id}, "
        f"asset_exists={asset_exists}, current_latest={current_latest}, "
        f"overwrite={overwrite}, draft_exists={existing_draft is not None}"
    )

    # =========================================================================
    # PHASE 1: Overwrite Validation (V0.9 semantics)
    # Overwrite targets DRAFT releases only. Approved releases are immutable.
    # =========================================================================
    if overwrite and existing_draft:
        # Draft exists and overwrite requested — always valid
        # The draft will be re-processed (revision incremented)
        draft_state = existing_draft.approval_state.value if hasattr(existing_draft.approval_state, 'value') else str(existing_draft.approval_state)
        if draft_state in ('rejected', 'revoked'):
            warnings.append(
                f"Draft release state '{draft_state}' will be reset to "
                f"'pending_review' after overwrite."
            )

        if current_latest:
            warnings.append(
                f"Approved version '{current_latest.get('version_id')}' "
                f"remains active — overwrite targets the draft only."
            )

        result = VersionValidationResult(
            valid=True,
            asset_id=asset_id,
            asset_exists=asset_exists,
            current_latest=current_latest,
            draft_in_progress=draft_in_progress,
            warnings=warnings,
            suggested_params={
                'version_ordinal': suggested_version_ordinal,
                'previous_version_id': suggested_previous,
            }
        )
        logger.info(
            f"Overwrite validation passed: asset_id={asset_id[:8]}..., "
            f"draft_state={draft_state}"
        )
        return result

    if overwrite and not existing_draft:
        # Overwrite requested but no draft to overwrite — informational
        warnings.append(
            "overwrite=true specified but no draft release exists. "
            "A new draft release will be created."
        )
        # Fall through to normal validation — still valid

    # =========================================================================
    # PHASE 2: Draft coexistence check
    # V0.9: Drafts coexist with approved versions. Inform the caller.
    # =========================================================================
    if existing_draft and not overwrite:
        # Draft already in progress, no overwrite — idempotent return
        warnings.append(
            "Draft release already in progress. Submit will return the "
            "existing draft (idempotent). Use overwrite=true to re-process."
        )
        result = VersionValidationResult(
            valid=True,
            asset_id=asset_id,
            asset_exists=asset_exists,
            current_latest=current_latest,
            draft_in_progress=draft_in_progress,
            warnings=warnings,
            suggested_params={
                'version_ordinal': suggested_version_ordinal,
                'previous_version_id': suggested_previous,
            }
        )
        logger.info(
            f"Draft exists (idempotent): asset_id={asset_id[:8]}..., "
            f"release_id={existing_draft.release_id[:8]}..."
        )
        return result

    # =========================================================================
    # PHASE 3: Version Chaining Validation (previous_version_id)
    # =========================================================================
    if previous_version_id is not None:
        # Caller specified a previous version — validate it exists
        if not asset or not latest_release:
            valid = False
            warnings.append(
                f"previous_version_id '{previous_version_id}' specified but "
                f"no approved versions exist. Omit previous_version_id for "
                f"first submission."
            )
            logger.warning(
                f"Validation failed: previous_version_id='{previous_version_id}' "
                f"but no approved releases"
            )
        elif current_latest.get('version_id') != previous_version_id:
            # Specified version doesn't match latest — warn but allow
            latest_version = current_latest.get('version_id')
            warnings.append(
                f"previous_version_id '{previous_version_id}' is not the "
                f"current latest version ('{latest_version}'). Submission "
                f"will still create a new draft release."
            )
            logger.info(
                f"Version chain mismatch (non-blocking): "
                f"previous='{previous_version_id}' != latest='{latest_version}'"
            )

    # Informational: if approved versions exist and this is a new submission
    if current_latest and not overwrite and not existing_draft:
        warnings.append(
            f"Approved version '{current_latest.get('version_id')}' exists. "
            f"New submission will create a draft release alongside it."
        )

    result = VersionValidationResult(
        valid=valid,
        asset_id=asset_id,
        asset_exists=asset_exists,
        current_latest=current_latest,
        draft_in_progress=draft_in_progress,
        warnings=warnings,
        suggested_params={
            'version_ordinal': suggested_version_ordinal,
            'previous_version_id': suggested_previous,
        }
    )

    logger.info(
        f"Version validation complete: valid={valid}, asset_id={asset_id[:8]}..., "
        f"warnings={len(warnings)}"
    )

    return result
