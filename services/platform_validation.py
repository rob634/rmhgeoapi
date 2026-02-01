# ============================================================================
# PLATFORM VALIDATION SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service - Version lineage validation for platform submit
# PURPOSE: Validate previous_version_id before job creation (dry_run support)
# CREATED: 31 JAN 2026
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

See: docs_claude/DRY_RUN_IMPLEMENTATION.md

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
    asset_service: Optional[AssetService] = None
) -> VersionValidationResult:
    """
    Validate version lineage for platform submit.

    Implements the validation matrix from DRY_RUN_IMPLEMENTATION.md:

    | previous_version_id | Lineage State         | Result                           |
    |---------------------|----------------------|----------------------------------|
    | null                | Empty (no versions)  | OK - First version               |
    | null                | Has versions (v2.0)  | REJECT - "v2.0 exists, specify"  |
    | v2.0                | Empty                | REJECT - "v2.0 doesn't exist"    |
    | v2.0                | Latest is v2.0       | OK - Proceed                     |
    | v2.0                | Latest is v3.0       | REJECT - "v2.0 is not latest"    |

    Args:
        platform_id: Platform identifier (e.g., "ddh")
        platform_refs: Full platform refs including version_id
        previous_version_id: The previous version ID provided by B2B app (or None)
        asset_service: Optional AssetService instance (creates one if not provided)

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

    warnings: List[str] = []
    valid = True

    # Build suggested params
    suggested_version_ordinal = lineage_state.get('suggested_params', {}).get('version_ordinal', 1)
    suggested_previous = None
    if current_latest:
        suggested_previous = current_latest.get('version_id')

    logger.debug(
        f"Validating version lineage: previous_version_id={previous_version_id}, "
        f"lineage_exists={lineage_exists}, current_latest={current_latest}"
    )

    # Validation logic
    if previous_version_id is None:
        # First version case - lineage must be empty
        if current_latest:
            valid = False
            latest_version = current_latest.get('version_id', 'unknown')
            warnings.append(
                f"Version '{latest_version}' already exists for this dataset/resource. "
                f"Specify previous_version_id='{latest_version}' to submit a new version."
            )
            logger.warning(
                f"Validation failed: lineage exists but previous_version_id not provided. "
                f"Current latest: {latest_version}"
            )
    else:
        # Subsequent version case - must match current latest
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
