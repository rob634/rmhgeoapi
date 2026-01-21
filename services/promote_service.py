# ============================================================================
# PROMOTE SERVICE
# ============================================================================
# STATUS: Services - Dataset promotion and gallery management
# PURPOSE: Promote/demote STAC collections/items, manage featured datasets
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Promote Service.

Business logic for the dataset promotion system. Handles:
- Promoting STAC collections/items
- Gallery management (add/remove)
- Demoting (removing from promoted)
- STAC metadata lookup for defaults

Design Principle:
    ALL data is in STAC. This service just manages the "favorites/featured" layer.

Exports:
    PromoteService: Service for dataset promotion operations

Created: 22 DEC 2025
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import logging

from util_logger import LoggerFactory, ComponentType
from core.models import PromotedDataset
from core.models.promoted import SystemRole, Classification
from infrastructure import PromotedDatasetRepository
from infrastructure.pgstac_repository import PgStacRepository
from infrastructure.pgstac_bootstrap import get_item_by_id

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "PromoteService")


class PromoteService:
    """
    Service for dataset promotion operations.

    Manages the lifecycle of promoted datasets:
    - Promote: Add STAC collection/item to promoted list
    - Demote: Remove from promoted list entirely
    - Gallery: Add/remove from featured gallery

    All operations work with STAC references - no raw storage paths.
    """

    def __init__(self):
        """Initialize service with repositories."""
        self._repo = PromotedDatasetRepository()
        self._pgstac = PgStacRepository()

    # =========================================================================
    # PROMOTE OPERATIONS
    # =========================================================================

    def promote(
        self,
        promoted_id: str,
        stac_collection_id: Optional[str] = None,
        stac_item_id: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        gallery: bool = False,
        gallery_order: Optional[int] = None,
        viewer_config: Optional[Dict[str, Any]] = None,
        style_id: Optional[str] = None,
        is_system_reserved: bool = False,
        system_role: Optional[str] = None,
        classification: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Promote a STAC collection or item.

        If the item is already promoted:
        - If gallery=True, adds to gallery (if not already there)
        - Otherwise, updates the existing entry

        Args:
            promoted_id: Unique identifier for the promoted entry
            stac_collection_id: STAC collection ID (mutually exclusive with stac_item_id)
            stac_item_id: STAC item ID (mutually exclusive with stac_collection_id)
            title: Optional title override (falls back to STAC title)
            description: Optional description override (falls back to STAC description)
            tags: Optional tags for categorization
            gallery: If True, also add to gallery
            gallery_order: Optional gallery order (auto-assigned if not provided)
            viewer_config: Optional viewer customization
            style_id: Optional OGC Style ID
            is_system_reserved: If True, marks as critical system dataset (protected from demotion)
            system_role: System role identifier (e.g., 'admin0_boundaries') for discovery

        Returns:
            {
                "success": bool,
                "promoted_id": str,
                "action": "created" | "updated" | "gallery_added",
                "in_gallery": bool,
                "is_system_reserved": bool,
                "system_role": str (if set),
                "data": PromotedDataset dict
            }
        """
        logger.info(f"Promoting dataset: {promoted_id}")

        # Validate STAC reference
        if not stac_collection_id and not stac_item_id:
            return {
                "success": False,
                "error": "Must specify either stac_collection_id or stac_item_id"
            }
        if stac_collection_id and stac_item_id:
            return {
                "success": False,
                "error": "Cannot specify both stac_collection_id and stac_item_id"
            }

        # Verify STAC reference exists (or OGC Features collection for system tables)
        if stac_collection_id:
            stac_exists = self._verify_stac_collection_exists(stac_collection_id)
            ogc_exists = self._verify_ogc_features_collection_exists(stac_collection_id) if not stac_exists else False

            if not stac_exists and not ogc_exists:
                return {
                    "success": False,
                    "error": f"Collection '{stac_collection_id}' not found in PgSTAC or OGC Features"
                }

            # Log if using OGC-only collection
            if ogc_exists and not stac_exists:
                logger.info(f"Using OGC Features collection (not in STAC): {stac_collection_id}")
        else:
            if not self._verify_stac_item_exists(stac_item_id):
                return {
                    "success": False,
                    "error": f"STAC item '{stac_item_id}' not found in PgSTAC"
                }

        # Check if already promoted
        existing = self._repo.get_by_id(promoted_id)

        if existing:
            # Already promoted - handle update or gallery add
            if gallery and not existing.in_gallery:
                # Add to gallery
                updated = self._repo.add_to_gallery(promoted_id, gallery_order)
                logger.info(f"Added to gallery: {promoted_id}")
                return {
                    "success": True,
                    "promoted_id": promoted_id,
                    "action": "gallery_added",
                    "in_gallery": True,
                    "data": updated.model_dump() if updated else None
                }
            else:
                # Update existing entry
                updates = {}
                if title is not None:
                    updates['title'] = title
                if description is not None:
                    updates['description'] = description
                if tags is not None:
                    updates['tags'] = tags
                if viewer_config is not None:
                    updates['viewer_config'] = viewer_config
                if style_id is not None:
                    updates['style_id'] = style_id
                if gallery and gallery_order is not None:
                    updates['gallery_order'] = gallery_order

                if updates:
                    updated = self._repo.update(promoted_id, updates)
                    logger.info(f"Updated promoted dataset: {promoted_id}")
                    return {
                        "success": True,
                        "promoted_id": promoted_id,
                        "action": "updated",
                        "in_gallery": updated.in_gallery if updated else existing.in_gallery,
                        "data": updated.model_dump() if updated else existing.model_dump()
                    }
                else:
                    return {
                        "success": True,
                        "promoted_id": promoted_id,
                        "action": "no_changes",
                        "in_gallery": existing.in_gallery,
                        "data": existing.model_dump()
                    }

        # Validate system_role if provided
        if system_role:
            valid_roles = [r.value for r in SystemRole]
            if system_role not in valid_roles:
                return {
                    "success": False,
                    "error": f"Invalid system_role '{system_role}'. Valid roles: {valid_roles}"
                }
            # Check if role is already assigned to another dataset
            existing_role = self._repo.get_by_system_role(system_role)
            if existing_role and existing_role.promoted_id != promoted_id:
                return {
                    "success": False,
                    "error": f"System role '{system_role}' is already assigned to '{existing_role.promoted_id}'"
                }

        # Parse classification (24 DEC 2025)
        classification_enum = Classification.PUBLIC  # Default
        if classification:
            try:
                classification_enum = Classification(classification)
            except ValueError:
                return {
                    "success": False,
                    "error": f"Invalid classification '{classification}'. Valid: {[c.value for c in Classification]}"
                }

        # Create new promoted entry
        dataset = PromotedDataset(
            promoted_id=promoted_id,
            stac_collection_id=stac_collection_id,
            stac_item_id=stac_item_id,
            title=title,
            description=description,
            tags=tags or [],
            in_gallery=gallery,
            gallery_order=gallery_order if gallery else None,
            viewer_config=viewer_config or {},
            style_id=style_id,
            is_system_reserved=is_system_reserved,
            system_role=system_role,
            classification=classification_enum
        )

        try:
            created = self._repo.create(dataset)
            logger.info(f"Created promoted dataset: {promoted_id}")

            # Check STAC health and include warnings (22 DEC 2025)
            stac_warnings = self.get_stac_warnings_for_promote(
                stac_collection_id=stac_collection_id,
                stac_item_id=stac_item_id
            )

            result = {
                "success": True,
                "promoted_id": promoted_id,
                "action": "created",
                "in_gallery": created.in_gallery,
                "is_system_reserved": created.is_system_reserved,
                "system_role": created.system_role,
                "data": created.model_dump()
            }

            # Add STAC warnings if any
            if stac_warnings:
                result["stac_warnings"] = stac_warnings

            return result
        except ValueError as e:
            return {
                "success": False,
                "error": str(e)
            }

    # =========================================================================
    # DEMOTE OPERATIONS
    # =========================================================================

    def demote(self, promoted_id: str, confirm_system: bool = False) -> Dict[str, Any]:
        """
        Demote a dataset (remove from promoted entirely).

        Args:
            promoted_id: Dataset to demote
            confirm_system: Must be True to demote system-reserved datasets

        Returns:
            {"success": bool, "promoted_id": str}

        Note:
            System-reserved datasets require confirm_system=True to demote.
            This protects critical system datasets from accidental removal.
        """
        logger.info(f"Demoting dataset: {promoted_id}")

        try:
            if self._repo.delete(promoted_id, confirm_system=confirm_system):
                return {
                    "success": True,
                    "promoted_id": promoted_id,
                    "action": "demoted"
                }
            else:
                return {
                    "success": False,
                    "error": f"Promoted dataset '{promoted_id}' not found"
                }
        except ValueError as e:
            # Raised when trying to delete system-reserved without confirm
            return {
                "success": False,
                "error": str(e)
            }

    # =========================================================================
    # GALLERY OPERATIONS
    # =========================================================================

    def add_to_gallery(
        self,
        promoted_id: str,
        order: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Add a promoted dataset to the gallery.

        Args:
            promoted_id: Dataset to add to gallery
            order: Optional gallery order

        Returns:
            {"success": bool, "promoted_id": str, "gallery_order": int}
        """
        logger.info(f"Adding to gallery: {promoted_id}")

        # Verify exists
        existing = self._repo.get_by_id(promoted_id)
        if not existing:
            return {
                "success": False,
                "error": f"Promoted dataset '{promoted_id}' not found. Promote it first."
            }

        if existing.in_gallery:
            return {
                "success": True,
                "promoted_id": promoted_id,
                "action": "already_in_gallery",
                "gallery_order": existing.gallery_order
            }

        updated = self._repo.add_to_gallery(promoted_id, order)
        if updated:
            return {
                "success": True,
                "promoted_id": promoted_id,
                "action": "added_to_gallery",
                "gallery_order": updated.gallery_order
            }
        else:
            return {
                "success": False,
                "error": f"Failed to add '{promoted_id}' to gallery"
            }

    def remove_from_gallery(self, promoted_id: str) -> Dict[str, Any]:
        """
        Remove a promoted dataset from the gallery (keep promoted).

        Args:
            promoted_id: Dataset to remove from gallery

        Returns:
            {"success": bool, "promoted_id": str}
        """
        logger.info(f"Removing from gallery: {promoted_id}")

        existing = self._repo.get_by_id(promoted_id)
        if not existing:
            return {
                "success": False,
                "error": f"Promoted dataset '{promoted_id}' not found"
            }

        if not existing.in_gallery:
            return {
                "success": True,
                "promoted_id": promoted_id,
                "action": "not_in_gallery"
            }

        updated = self._repo.remove_from_gallery(promoted_id)
        if updated:
            return {
                "success": True,
                "promoted_id": promoted_id,
                "action": "removed_from_gallery"
            }
        else:
            return {
                "success": False,
                "error": f"Failed to remove '{promoted_id}' from gallery"
            }

    # =========================================================================
    # READ OPERATIONS
    # =========================================================================

    def get(self, promoted_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a promoted dataset by ID.

        Args:
            promoted_id: Dataset identifier

        Returns:
            PromotedDataset dict or None
        """
        dataset = self._repo.get_by_id(promoted_id)
        return dataset.model_dump() if dataset else None

    def list_all(self) -> List[Dict[str, Any]]:
        """
        List all promoted datasets.

        Returns:
            List of PromotedDataset dicts
        """
        datasets = self._repo.list_all()
        return [d.model_dump() for d in datasets]

    def list_gallery(self) -> List[Dict[str, Any]]:
        """
        List gallery items in order.

        Returns:
            List of PromotedDataset dicts in gallery order
        """
        datasets = self._repo.list_gallery()
        return [d.model_dump() for d in datasets]

    # =========================================================================
    # SYSTEM DATASET OPERATIONS (23 DEC 2025)
    # =========================================================================

    def get_by_system_role(self, system_role: str) -> Optional[Dict[str, Any]]:
        """
        Get a promoted dataset by system role.

        System roles are unique - only one dataset can have a given role.
        Used by H3 and other workflows to discover system datasets dynamically.

        Args:
            system_role: System role identifier (e.g., 'admin0_boundaries')

        Returns:
            PromotedDataset dict or None
        """
        dataset = self._repo.get_by_system_role(system_role)
        return dataset.model_dump() if dataset else None

    def list_system_reserved(self) -> List[Dict[str, Any]]:
        """
        List all system-reserved datasets.

        Returns:
            List of PromotedDataset dicts that are system-reserved
        """
        datasets = self._repo.list_system_reserved()
        return [d.model_dump() for d in datasets]

    def get_system_table_name(self, system_role: str) -> Optional[str]:
        """
        Get the PostGIS table name for a system role.

        Convenience method for workflows that need to look up system tables.
        Extracts the table name from the STAC item properties.

        Args:
            system_role: System role identifier (e.g., 'admin0_boundaries')

        Returns:
            Table name (e.g., 'curated_admin0') or None if not found
        """
        dataset = self._repo.get_by_system_role(system_role)
        if not dataset:
            logger.warning(f"No system dataset found for role: {system_role}")
            return None

        # Get the STAC item to extract table name (for raster datasets)
        if dataset.stac_item_id:
            item = self._get_item_for_validation(dataset.stac_item_id)
            if item and 'properties' in item:
                # Look for postgis:table property
                table = item['properties'].get('postgis:table')
                if table:
                    return table
                # Fallback: extract from title or id
                logger.warning(
                    f"STAC item '{dataset.stac_item_id}' missing postgis:table property"
                )

        # For vector datasets: stac_collection_id IS the table name (21 JAN 2026)
        # Vector tables are registered as STAC collections, not items
        if dataset.stac_collection_id:
            logger.info(f"Using stac_collection_id as table name: {dataset.stac_collection_id}")
            return dataset.stac_collection_id

        # Final fallback: derive from promoted_id
        # Convention: promoted_id should match table name for system datasets
        logger.info(f"Using promoted_id as table name fallback: {dataset.promoted_id}")
        return dataset.promoted_id.replace('-', '_')

    # =========================================================================
    # STAC VERIFICATION
    # =========================================================================

    def _verify_stac_collection_exists(self, collection_id: str) -> bool:
        """Check if a STAC collection exists in PgSTAC."""
        try:
            collection = self._pgstac.get_collection(collection_id)
            return collection is not None
        except Exception as e:
            logger.warning(f"Failed to verify STAC collection '{collection_id}': {e}")
            return False

    def _verify_ogc_features_collection_exists(self, collection_id: str) -> bool:
        """
        Check if an OGC Features collection exists.

        Uses OGCFeaturesRepository which properly handles geometry_columns lookup.
        """
        try:
            from ogc_features.repository import OGCFeaturesRepository

            ogc_repo = OGCFeaturesRepository()
            # get_collection_metadata raises ValueError if not found
            metadata = ogc_repo.get_collection_metadata(collection_id)
            logger.info(f"✅ Verified OGC Features collection exists: {collection_id}")
            return True
        except ValueError:
            # Collection not found
            logger.warning(f"⚠️ OGC collection not found: {collection_id}")
            return False
        except Exception as e:
            logger.warning(f"Failed to verify OGC collection '{collection_id}': {e}")
            return False

    def _verify_stac_item_exists(self, item_id: str) -> bool:
        """Check if a STAC item exists in PgSTAC."""
        try:
            from infrastructure.pgstac_bootstrap import get_item_by_id

            result = get_item_by_id(item_id)
            # get_item_by_id returns error dict if not found
            if 'error' in result:
                logger.warning(f"⚠️ STAC item not found: {item_id}")
                return False

            logger.info(f"✅ Verified STAC item exists: {item_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to verify STAC item '{item_id}': {e}")
            # If we can't verify, allow it (may be external STAC)
            return True

    # =========================================================================
    # STAC HEALTH VALIDATION (22 DEC 2025)
    # =========================================================================

    def check_stac_health(
        self,
        stac_collection_id: Optional[str] = None,
        stac_item_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Check the health/validity of a STAC collection or item.

        Validates the STAC entity against the specification and returns
        any issues or warnings found. Used to surface STAC quality issues
        when promoting datasets.

        Args:
            stac_collection_id: Collection ID to check
            stac_item_id: Item ID to check (provide one or the other)

        Returns:
            {
                "exists": bool,
                "valid": bool,
                "issues": [str],
                "warnings": [str],
                "stac_version": str (if found)
            }
        """
        from services.stac_validation import STACValidator

        result = {
            "exists": False,
            "valid": False,
            "issues": [],
            "warnings": [],
            "stac_version": None
        }

        try:
            if stac_collection_id:
                # Check collection
                collection = self._pgstac.get_collection(stac_collection_id)
                if not collection:
                    result["issues"].append(f"Collection '{stac_collection_id}' not found")
                    return result

                result["exists"] = True
                result["stac_version"] = collection.get('stac_version')

                # Validate collection
                validation = STACValidator.validate_collection(collection)
                result["valid"] = validation.is_valid
                result["issues"] = validation.issues
                result["warnings"] = validation.warnings

            elif stac_item_id:
                # Check item - need to search for it
                item = self._get_item_for_validation(stac_item_id)
                if not item:
                    result["issues"].append(f"Item '{stac_item_id}' not found")
                    return result

                result["exists"] = True
                result["stac_version"] = item.get('stac_version')

                # Validate item
                validation = STACValidator.validate_item(item)
                result["valid"] = validation.is_valid
                result["issues"] = validation.issues
                result["warnings"] = validation.warnings

            return result

        except Exception as e:
            logger.error(f"STAC health check failed: {e}")
            result["issues"].append(f"Health check failed: {str(e)}")
            return result

    def _get_item_for_validation(self, item_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a STAC item by ID for validation.

        Searches across all collections to find the item.

        Args:
            item_id: Item ID to find

        Returns:
            Item dict or None
        """
        from infrastructure.postgresql import PostgreSQLRepository

        try:
            pg_repo = PostgreSQLRepository(schema_name='pgstac')
            with pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT content FROM pgstac.items WHERE id = %s LIMIT 1",
                        (item_id,)
                    )
                    row = cur.fetchone()
                    return row['content'] if row else None
        except Exception as e:
            logger.warning(f"Failed to get item '{item_id}': {e}")
            return None

    def get_stac_warnings_for_promote(
        self,
        stac_collection_id: Optional[str] = None,
        stac_item_id: Optional[str] = None
    ) -> List[str]:
        """
        Get STAC warnings to include in promote response.

        Performs a quick health check and returns any warnings that should
        be surfaced to the user when promoting a dataset.

        Args:
            stac_collection_id: Collection being promoted
            stac_item_id: Item being promoted

        Returns:
            List of warning strings (empty if healthy)
        """
        warnings = []

        health = self.check_stac_health(
            stac_collection_id=stac_collection_id,
            stac_item_id=stac_item_id
        )

        # Include issues as warnings (don't block promotion, but inform user)
        if not health["valid"]:
            warnings.extend([f"STAC issue: {i}" for i in health["issues"]])

        warnings.extend(health["warnings"])

        return warnings


# Module exports
__all__ = ['PromoteService']
