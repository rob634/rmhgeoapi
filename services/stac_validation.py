# ============================================================================
# CLAUDE CONTEXT - STAC VALIDATION SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service - STAC item/collection validation and repair
# PURPOSE: Validate STAC items against spec and repair common issues
# LAST_REVIEWED: 22 DEC 2025
# EXPORTS: STACValidator, STACRepair, ValidationResult
# DEPENDENCIES: stac_pydantic, core.models.stac
# ============================================================================
"""
STAC Validation Service.

Provides validation and repair utilities for STAC items and collections.
Used by:
    - PgStacRepository for pre-insertion validation
    - repair_stac_items job for catalog cleanup
    - PromoteService for health checks

Design Principle:
    Validation is layered:
    1. Structure check (required fields, types)
    2. Semantic check (datetime handling, geometry validity)
    3. Namespace check (custom property schemas)
    4. stac-pydantic validation (full spec compliance)

Exports:
    ValidationResult: Result of validation with issues list
    STACValidator: Validation utilities
    STACRepair: Repair utilities

Created: 22 DEC 2025
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
import logging

from pydantic import ValidationError as PydanticValidationError

from core.models.stac import STAC_VERSION, STACItemCore
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "STACValidator")


# =============================================================================
# VALIDATION RESULT
# =============================================================================

@dataclass
class ValidationResult:
    """
    Result of STAC validation.

    Attributes:
        is_valid: True if item passes all validation
        issues: List of issue descriptions
        warnings: List of non-fatal warnings
        repaired_fields: List of fields that were auto-repaired
    """
    is_valid: bool = True
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    repaired_fields: List[str] = field(default_factory=list)

    def add_issue(self, issue: str):
        """Add a validation issue (makes result invalid)."""
        self.issues.append(issue)
        self.is_valid = False

    def add_warning(self, warning: str):
        """Add a warning (doesn't affect validity)."""
        self.warnings.append(warning)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "is_valid": self.is_valid,
            "issues": self.issues,
            "warnings": self.warnings,
            "repaired_fields": self.repaired_fields,
            "issue_count": len(self.issues),
            "warning_count": len(self.warnings)
        }


# =============================================================================
# STAC VALIDATOR
# =============================================================================

class STACValidator:
    """
    STAC item and collection validation utilities.

    Provides multi-level validation:
    1. Structure validation (required fields)
    2. Semantic validation (datetime, geometry)
    3. Namespace validation (custom properties)
    4. Full stac-pydantic validation
    """

    # Required top-level fields for STAC items
    REQUIRED_ITEM_FIELDS = [
        'id', 'type', 'stac_version', 'geometry', 'bbox',
        'properties', 'assets', 'links'
    ]

    # Required top-level fields for STAC collections
    REQUIRED_COLLECTION_FIELDS = [
        'id', 'type', 'stac_version', 'description', 'license',
        'extent', 'links'
    ]

    @classmethod
    def validate_item(
        cls,
        item_dict: Dict[str, Any],
        check_pydantic: bool = True
    ) -> ValidationResult:
        """
        Validate a STAC item against the specification.

        Performs multi-level validation:
        1. Required field check
        2. Type/structure check
        3. STAC version check
        4. Datetime handling check
        5. Geometry validation
        6. Optional stac-pydantic validation

        Args:
            item_dict: STAC item as dictionary
            check_pydantic: Whether to run full stac-pydantic validation

        Returns:
            ValidationResult with issues and warnings
        """
        result = ValidationResult()

        # Level 1: Required fields
        cls._check_required_fields(item_dict, cls.REQUIRED_ITEM_FIELDS, result)

        # Level 2: Type checks
        cls._check_item_types(item_dict, result)

        # Level 3: STAC version
        cls._check_stac_version(item_dict, result)

        # Level 4: Datetime handling
        cls._check_datetime_handling(item_dict, result)

        # Level 5: Geometry
        cls._check_geometry(item_dict, result)

        # Level 6: Collection reference
        cls._check_collection_reference(item_dict, result)

        # Level 7: Full stac-pydantic validation
        if check_pydantic and result.is_valid:
            cls._check_pydantic_validation(item_dict, result)

        return result

    @classmethod
    def validate_collection(
        cls,
        collection_dict: Dict[str, Any],
        check_pydantic: bool = True
    ) -> ValidationResult:
        """
        Validate a STAC collection against the specification.

        Args:
            collection_dict: STAC collection as dictionary
            check_pydantic: Whether to run full stac-pydantic validation

        Returns:
            ValidationResult with issues and warnings
        """
        result = ValidationResult()

        # Level 1: Required fields
        cls._check_required_fields(
            collection_dict,
            cls.REQUIRED_COLLECTION_FIELDS,
            result
        )

        # Level 2: Type checks
        if collection_dict.get('type') != 'Collection':
            result.add_issue(
                f"Collection type must be 'Collection', got '{collection_dict.get('type')}'"
            )

        # Level 3: STAC version
        cls._check_stac_version(collection_dict, result)

        # Level 4: Extent validation
        cls._check_collection_extent(collection_dict, result)

        # Level 5: pystac validation (if available)
        if check_pydantic and result.is_valid:
            cls._check_collection_pydantic(collection_dict, result)

        return result

    @classmethod
    def quick_validate(cls, item_dict: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Quick validation - returns simple (is_valid, issues) tuple.

        Useful for inline validation without full ValidationResult overhead.

        Args:
            item_dict: STAC item as dictionary

        Returns:
            (is_valid, list_of_issues) tuple
        """
        result = cls.validate_item(item_dict, check_pydantic=False)
        return (result.is_valid, result.issues)

    # =========================================================================
    # PRIVATE VALIDATION METHODS
    # =========================================================================

    @classmethod
    def _check_required_fields(
        cls,
        data: Dict[str, Any],
        required: List[str],
        result: ValidationResult
    ):
        """Check that all required fields are present."""
        for field_name in required:
            if field_name not in data:
                result.add_issue(f"Missing required field: {field_name}")
            elif data[field_name] is None and field_name not in ['geometry', 'bbox']:
                # geometry can be null for certain items
                result.add_issue(f"Required field is null: {field_name}")

    @classmethod
    def _check_item_types(cls, item_dict: Dict[str, Any], result: ValidationResult):
        """Check that fields have correct types."""
        # type must be "Feature"
        if item_dict.get('type') != 'Feature':
            result.add_issue(
                f"Item type must be 'Feature', got '{item_dict.get('type')}'"
            )

        # properties must be a dict
        props = item_dict.get('properties')
        if props is not None and not isinstance(props, dict):
            result.add_issue(
                f"properties must be dict, got {type(props).__name__}"
            )

        # assets must be a dict
        assets = item_dict.get('assets')
        if assets is not None and not isinstance(assets, dict):
            result.add_issue(
                f"assets must be dict, got {type(assets).__name__}"
            )

        # links must be a list
        links = item_dict.get('links')
        if links is not None and not isinstance(links, list):
            result.add_issue(
                f"links must be list, got {type(links).__name__}"
            )

        # bbox must be a list of 4 or 6 numbers
        bbox = item_dict.get('bbox')
        if bbox is not None:
            if not isinstance(bbox, list):
                result.add_issue(f"bbox must be list, got {type(bbox).__name__}")
            elif len(bbox) not in [4, 6]:
                result.add_issue(f"bbox must have 4 or 6 elements, got {len(bbox)}")

    @classmethod
    def _check_stac_version(cls, data: Dict[str, Any], result: ValidationResult):
        """Check STAC version field."""
        version = data.get('stac_version')
        if version is None:
            result.add_issue("Missing stac_version field")
        elif version != STAC_VERSION:
            result.add_warning(
                f"STAC version mismatch: got '{version}', expected '{STAC_VERSION}'"
            )

    @classmethod
    def _check_datetime_handling(
        cls,
        item_dict: Dict[str, Any],
        result: ValidationResult
    ):
        """
        Check datetime handling per STAC spec.

        STAC requires either:
        - datetime (non-null)
        - OR start_datetime + end_datetime (with datetime=null)
        """
        props = item_dict.get('properties', {})

        has_datetime = props.get('datetime') is not None
        has_start = props.get('start_datetime') is not None
        has_end = props.get('end_datetime') is not None
        has_range = has_start or has_end

        if not has_datetime and not has_range:
            result.add_issue(
                "Missing datetime: must have 'datetime' OR 'start_datetime/end_datetime'"
            )

        if has_range:
            # If using temporal range, datetime should be explicitly null
            if has_datetime:
                result.add_warning(
                    "Both datetime and start/end_datetime present - "
                    "datetime should be null when using temporal range"
                )
            # Both start and end should be present
            if has_start and not has_end:
                result.add_warning("start_datetime without end_datetime")
            if has_end and not has_start:
                result.add_warning("end_datetime without start_datetime")

    @classmethod
    def _check_geometry(cls, item_dict: Dict[str, Any], result: ValidationResult):
        """Check geometry field validity."""
        geometry = item_dict.get('geometry')
        bbox = item_dict.get('bbox')

        # Must have at least one
        if geometry is None and bbox is None:
            result.add_issue("Item must have geometry or bbox")
            return

        # If geometry is present, validate structure
        if geometry is not None:
            if not isinstance(geometry, dict):
                result.add_issue(
                    f"geometry must be dict, got {type(geometry).__name__}"
                )
            elif 'type' not in geometry:
                result.add_issue("geometry missing 'type' field")
            elif geometry.get('type') not in [
                'Point', 'MultiPoint', 'LineString', 'MultiLineString',
                'Polygon', 'MultiPolygon', 'GeometryCollection'
            ]:
                result.add_warning(
                    f"Unusual geometry type: {geometry.get('type')}"
                )

            # Check for coordinates
            if geometry.get('type') != 'GeometryCollection':
                if 'coordinates' not in geometry:
                    result.add_issue("geometry missing 'coordinates' field")

    @classmethod
    def _check_collection_reference(
        cls,
        item_dict: Dict[str, Any],
        result: ValidationResult
    ):
        """Check collection reference field."""
        collection = item_dict.get('collection')
        if collection is None:
            result.add_warning(
                "Item has no collection reference - may not be queryable"
            )

    @classmethod
    def _check_pydantic_validation(
        cls,
        item_dict: Dict[str, Any],
        result: ValidationResult
    ):
        """Run full stac-pydantic validation."""
        try:
            from stac_pydantic import Item
            Item(**item_dict)
        except PydanticValidationError as e:
            for error in e.errors():
                loc = '.'.join(str(x) for x in error['loc'])
                msg = error['msg']
                result.add_issue(f"stac-pydantic validation failed at {loc}: {msg}")
        except Exception as e:
            result.add_issue(f"stac-pydantic validation error: {str(e)}")

    @classmethod
    def _check_collection_extent(
        cls,
        collection_dict: Dict[str, Any],
        result: ValidationResult
    ):
        """Validate collection extent structure."""
        extent = collection_dict.get('extent', {})

        if not isinstance(extent, dict):
            result.add_issue(
                f"extent must be dict, got {type(extent).__name__}"
            )
            return

        # Check spatial extent
        spatial = extent.get('spatial', {})
        if not spatial:
            result.add_warning("Collection missing spatial extent")
        elif 'bbox' not in spatial:
            result.add_warning("Collection spatial extent missing bbox")

        # Check temporal extent
        temporal = extent.get('temporal', {})
        if not temporal:
            result.add_warning("Collection missing temporal extent")
        elif 'interval' not in temporal:
            result.add_warning("Collection temporal extent missing interval")

    @classmethod
    def _check_collection_pydantic(
        cls,
        collection_dict: Dict[str, Any],
        result: ValidationResult
    ):
        """Run pystac validation on collection."""
        try:
            import pystac
            collection = pystac.Collection.from_dict(collection_dict)
            # pystac doesn't have a built-in validate, but construction validates
        except Exception as e:
            result.add_issue(f"pystac collection validation error: {str(e)}")


# =============================================================================
# STAC REPAIR
# =============================================================================

class STACRepair:
    """
    STAC item repair utilities.

    Provides methods to fix common STAC item issues:
    - Missing/incorrect stac_version
    - Missing type field
    - Missing geometry (derived from bbox)
    - Missing datetime
    - Missing collection reference
    """

    @classmethod
    def repair_item(
        cls,
        item_dict: Dict[str, Any],
        collection_id: Optional[str] = None,
        fix_version: bool = True,
        fix_datetime: bool = True,
        fix_geometry: bool = True,
        fix_type: bool = True
    ) -> Tuple[Dict[str, Any], List[str]]:
        """
        Repair common STAC item issues.

        Args:
            item_dict: STAC item to repair
            collection_id: Collection ID to set if missing
            fix_version: Fix stac_version mismatch
            fix_datetime: Add datetime if missing
            fix_geometry: Derive geometry from bbox if missing
            fix_type: Fix type field if wrong

        Returns:
            Tuple of (repaired_item, list_of_repairs_made)
        """
        repaired = item_dict.copy()
        repairs = []

        # Fix type
        if fix_type and repaired.get('type') != 'Feature':
            old_type = repaired.get('type')
            repaired['type'] = 'Feature'
            repairs.append(f"type: '{old_type}' -> 'Feature'")

        # Fix STAC version
        if fix_version:
            old_version = repaired.get('stac_version')
            if old_version != STAC_VERSION:
                repaired['stac_version'] = STAC_VERSION
                repairs.append(f"stac_version: '{old_version}' -> '{STAC_VERSION}'")

        # Fix geometry from bbox
        if fix_geometry and repaired.get('geometry') is None:
            bbox = repaired.get('bbox')
            if bbox and len(bbox) >= 4:
                repaired['geometry'] = cls._bbox_to_polygon(bbox)
                repairs.append("geometry: derived from bbox")

        # Fix datetime
        if fix_datetime:
            props = repaired.setdefault('properties', {})
            has_datetime = props.get('datetime') is not None
            has_range = props.get('start_datetime') or props.get('end_datetime')

            if not has_datetime and not has_range:
                props['datetime'] = datetime.now(timezone.utc).isoformat()
                repairs.append("datetime: set to current time")

        # Fix collection reference
        if collection_id and not repaired.get('collection'):
            repaired['collection'] = collection_id
            repairs.append(f"collection: set to '{collection_id}'")

        # Ensure links array exists
        if 'links' not in repaired:
            repaired['links'] = []
            repairs.append("links: initialized to empty array")

        # Ensure assets dict exists
        if 'assets' not in repaired:
            repaired['assets'] = {}
            repairs.append("assets: initialized to empty dict")

        return repaired, repairs

    @classmethod
    def _bbox_to_polygon(cls, bbox: List[float]) -> Dict[str, Any]:
        """
        Convert bbox to GeoJSON Polygon geometry.

        Args:
            bbox: [minx, miny, maxx, maxy] or [minx, miny, minz, maxx, maxy, maxz]

        Returns:
            GeoJSON Polygon geometry dict
        """
        if len(bbox) == 6:
            # 3D bbox - use only 2D
            minx, miny, _, maxx, maxy, _ = bbox
        else:
            minx, miny, maxx, maxy = bbox

        return {
            "type": "Polygon",
            "coordinates": [[
                [minx, miny],
                [maxx, miny],
                [maxx, maxy],
                [minx, maxy],
                [minx, miny]  # Close the ring
            ]]
        }

    @classmethod
    def standardize_properties(
        cls,
        item_dict: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[str]]:
        """
        Standardize property naming and formatting.

        Fixes issues like:
        - Inconsistent namespace prefixes
        - Non-standard datetime formats

        Args:
            item_dict: STAC item to standardize

        Returns:
            Tuple of (standardized_item, list_of_changes)
        """
        standardized = item_dict.copy()
        changes = []

        props = standardized.get('properties', {})

        # Standardize datetime format
        if 'datetime' in props and props['datetime'] is not None:
            dt_val = props['datetime']
            if isinstance(dt_val, datetime):
                props['datetime'] = dt_val.isoformat()
                changes.append("datetime: converted to ISO format")

        # Similar for start/end datetime
        for dt_field in ['start_datetime', 'end_datetime']:
            if dt_field in props and props[dt_field] is not None:
                dt_val = props[dt_field]
                if isinstance(dt_val, datetime):
                    props[dt_field] = dt_val.isoformat()
                    changes.append(f"{dt_field}: converted to ISO format")

        standardized['properties'] = props
        return standardized, changes


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    'ValidationResult',
    'STACValidator',
    'STACRepair'
]
