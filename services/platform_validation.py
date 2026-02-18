# ============================================================================
# PLATFORM VALIDATION SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service - Version lineage validation for platform submit
# PURPOSE: Validate previous_version_id before job creation (dry_run support)
# CREATED: 31 JAN 2026
# UPDATED: 09 FEB 2026 - Approval-aware overwrite and version validation
# EXPORTS: validate_version_lineage, VersionValidationResult
# DEPENDENCIES: services.asset_service
# ============================================================================
"""
Platform Validation Service - V0.8 Release Control.

Provides validation logic for platform submit operations, specifically
for version lineage validation to prevent race conditions.

This service is used by both:
- dry_run=true requests (return validation result without job creation)
- Actual submit requests (enforce validation before job creation)

V0.8.16 Approval-Aware Validation (09 FEB 2026):
- Overwrite blocked if asset is APPROVED (must revoke first)
- Overwrite allowed for PENDING_REVIEW, REJECTED, REVOKED
- Semantic versions require previous version to be APPROVED

See: docs_claude/DRY_RUN_IMPLEMENTATION.md
See: docs_claude/APPROVAL_OVERWRITE_VALIDATION.md

Exports:
    validate_version_lineage: Validate previous_version_id against lineage state
    VersionValidationResult: Typed result from validation
"""

from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from util_logger import LoggerFactory, ComponentType
from services.asset_service import AssetService

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "PlatformValidation")


@dataclass
class VersionValidationResult:
    """
    Result of version lineage validation.

    Attributes:
        valid: True if validation passed
        lineage_id: Computed lineage ID for this dataset/resource
        lineage_exists: True if lineage has existing versions
        current_latest: Info about current latest version (if exists)
        warnings: List of validation warnings/errors
        suggested_params: Suggested parameters for submit
    """
    valid: bool
    lineage_id: str
    lineage_exists: bool
    current_latest: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    suggested_params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON response."""
        return {
            'valid': self.valid,
            'lineage_id': self.lineage_id,
            'lineage_exists': self.lineage_exists,
            'current_latest': self.current_latest,
            'warnings': self.warnings,
            'suggested_params': self.suggested_params
        }


def validate_version_lineage(
    platform_id: str,
    platform_refs: Dict[str, Any],
    previous_version_id: Optional[str],
    asset_service: Optional[AssetService] = None,
    overwrite: bool = False
) -> VersionValidationResult:
    """
    Validate version lineage for platform submit.

    Implements the validation matrix from DRY_RUN_IMPLEMENTATION.md with
    approval-aware extensions from APPROVAL_OVERWRITE_VALIDATION.md.

    Version Lineage Rules:
    | previous_version_id | Lineage State         | Result                           |
    |---------------------|----------------------|----------------------------------|
    | null                | Empty (no versions)  | OK - First version               |
    | null                | Has versions (v2.0)  | REJECT - "v2.0 exists, specify"  |
    | v2.0                | Empty                | REJECT - "v2.0 doesn't exist"    |
    | v2.0                | Latest is v2.0       | OK - Proceed (if v2.0 APPROVED)  |
    | v2.0                | Latest is v3.0       | REJECT - "v2.0 is not latest"    |

    Overwrite Rules (09 FEB 2026):
    | Approval State   | overwrite=True | Result                              |
    |------------------|----------------|-------------------------------------|
    | APPROVED         | True           | REJECT - Must revoke first          |
    | PENDING_REVIEW   | True           | OK - Overwrite, keep pending        |
    | REJECTED         | True           | OK - Overwrite, reset to pending    |
    | REVOKED          | True           | OK - Overwrite, reset to pending    |

    Semantic Version Rules (09 FEB 2026):
    | Previous State   | Result                                      |
    |------------------|---------------------------------------------|
    | APPROVED         | OK - Chain allowed                          |
    | PENDING_REVIEW   | REJECT - Previous must be approved first    |
    | REJECTED         | REJECT - Previous must be approved first    |
    | REVOKED          | REJECT - Previous must be approved first    |

    Args:
        platform_id: Platform identifier (e.g., "ddh")
        platform_refs: Full platform refs including version_id
        previous_version_id: The previous version ID provided by B2B app (or None)
        asset_service: Optional AssetService instance (creates one if not provided)
        overwrite: If True, attempting to replace existing version

    Returns:
        VersionValidationResult with validation outcome and suggestions
    """
    if asset_service is None:
        asset_service = AssetService()

    # Nominal refs for lineage (excludes version)
    nominal_refs = ["dataset_id", "resource_id"]

    # Get lineage state from asset service
    lineage_state = asset_service.get_lineage_state(
        platform_id=platform_id,
        platform_refs=platform_refs,
        nominal_refs=nominal_refs
    )

    lineage_id = lineage_state['lineage_id']
    current_latest = lineage_state.get('current_latest')
    lineage_exists = lineage_state.get('lineage_exists', False)
    existing_asset = lineage_state.get('existing_asset')
    version_exists = lineage_state.get('version_exists', False)

    warnings: List[str] = []
    valid = True

    # Build suggested params
    suggested_version_ordinal = lineage_state.get('suggested_params', {}).get('version_ordinal', 1)
    suggested_previous = None
    if current_latest:
        suggested_previous = current_latest.get('version_id')

    logger.debug(
        f"Validating version lineage: previous_version_id={previous_version_id}, "
        f"lineage_exists={lineage_exists}, current_latest={current_latest}, "
        f"overwrite={overwrite}, version_exists={version_exists}"
    )

    # =========================================================================
    # PHASE 1: Overwrite Approval Check (09 FEB 2026)
    # =========================================================================
    if overwrite and version_exists and existing_asset:
        approval_state = existing_asset.get('approval_state', 'pending_review')

        if approval_state == 'approved':
            # APPROVED assets cannot be overwritten - must revoke first
            valid = False
            warnings.append(
                "Asset is approved. Revoke approval before overwriting. "
                "Use POST /api/platform/revoke first."
            )
            logger.warning(
                f"Validation failed: overwrite blocked - asset is APPROVED. "
                f"asset_id={existing_asset.get('asset_id', 'unknown')[:16]}"
            )
        elif approval_state in ('rejected', 'revoked'):
            # Info message - approval will be reset to pending_review
            warnings.append(
                f"Asset state '{approval_state}' will be reset to 'pending_review' after overwrite."
            )
            logger.info(
                f"Overwrite will reset approval state from '{approval_state}' to 'pending_review'"
            )
        # PENDING_REVIEW: no message needed, just proceed

        # If overwrite is valid (not APPROVED), skip the normal version checks
        if valid:
            result = VersionValidationResult(
                valid=True,
                lineage_id=lineage_id,
                lineage_exists=lineage_exists,
                current_latest=current_latest,
                warnings=warnings,
                suggested_params={
                    'version_ordinal': suggested_version_ordinal,
                    'previous_version_id': suggested_previous,
                    'reset_approval': approval_state in ('rejected', 'revoked')
                }
            )
            logger.info(
                f"Overwrite validation passed: lineage_id={lineage_id[:8]}..., "
                f"approval_state={approval_state}"
            )
            return result

    # =========================================================================
    # PHASE 2: Version Lineage Validation
    # =========================================================================
    if previous_version_id is None:
        # First version case - lineage must be empty OR overwrite=True for same version
        if current_latest and not (overwrite and version_exists):
            valid = False
            latest_version = current_latest.get('version_id') or 'draft'
            warnings.append(
                f"Version '{latest_version}' already exists for this dataset/resource. "
                f"Specify previous_version_id='{latest_version}' to submit a new version, "
                f"or use overwrite=true to replace the existing version."
            )
            logger.warning(
                f"Validation failed: lineage exists but previous_version_id not provided. "
                f"Current latest: {latest_version}"
            )
    else:
        # Subsequent version case - must match current latest AND be approved
        if not current_latest:
            valid = False
            warnings.append(
                f"previous_version_id '{previous_version_id}' specified but no versions exist. "
                f"Omit previous_version_id for first version."
            )
            logger.warning(
                f"Validation failed: previous_version_id='{previous_version_id}' but lineage is empty"
            )
        elif current_latest.get('version_id') != previous_version_id:
            valid = False
            latest_version = current_latest.get('version_id')
            warnings.append(
                f"previous_version_id '{previous_version_id}' is not the current latest version. "
                f"Current latest is '{latest_version}'."
            )
            logger.warning(
                f"Validation failed: previous_version_id='{previous_version_id}' != "
                f"current_latest='{latest_version}'"
            )
        else:
            # =========================================================================
            # PHASE 2 continued: Semantic Version Approval Check (09 FEB 2026)
            # Previous version must be APPROVED to chain a new version
            # =========================================================================
            prev_approval_state = current_latest.get('approval_state', 'pending_review')
            if prev_approval_state != 'approved':
                valid = False
                warnings.append(
                    f"Previous version '{previous_version_id}' must be approved before creating "
                    f"a new version. Current state: '{prev_approval_state}'."
                )
                logger.warning(
                    f"Validation failed: previous version '{previous_version_id}' "
                    f"is not approved (state={prev_approval_state})"
                )

    result = VersionValidationResult(
        valid=valid,
        lineage_id=lineage_id,
        lineage_exists=lineage_exists,
        current_latest=current_latest,
        warnings=warnings,
        suggested_params={
            'version_ordinal': suggested_version_ordinal,
            'previous_version_id': suggested_previous
        }
    )

    logger.info(
        f"Version validation complete: valid={valid}, lineage_id={lineage_id[:8]}..., "
        f"warnings={len(warnings)}"
    )

    return result
