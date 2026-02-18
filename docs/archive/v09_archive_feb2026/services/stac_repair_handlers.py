# ============================================================================
# CLAUDE CONTEXT - STAC REPAIR HANDLERS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Task handlers - STAC catalog repair operations
# PURPOSE: Handle inventory and repair tasks for STAC catalog cleanup
# LAST_REVIEWED: 22 DEC 2025
# EXPORTS: stac_repair_inventory, stac_repair_item
# DEPENDENCIES: services.stac_validation, infrastructure.pgstac_repository
# ============================================================================
"""
STAC Repair Task Handlers.

Implements the task handlers for the repair_stac_items job:
    - stac_repair_inventory: Scan catalog and identify items with issues
    - stac_repair_item: Repair individual STAC item

Exports:
    stac_repair_inventory: Handler for inventory stage
    stac_repair_item: Handler for repair stage

Created: 22 DEC 2025
"""

from typing import Dict, Any, List, Optional
import json

from util_logger import LoggerFactory, ComponentType
from services.stac_validation import STACValidator, STACRepair, ValidationResult
from infrastructure.pgstac_repository import PgStacRepository

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "STACRepairHandlers")


def stac_repair_inventory(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Inventory stage: Scan STAC catalog and identify items with issues.

    Parameters:
        collection_id: Optional - limit to specific collection
        prioritize_promoted: If True, return promoted items first
        limit: Maximum items to process

    Returns:
        {
            "total_scanned": int,
            "items_with_issues": [
                {
                    "item_id": str,
                    "collection_id": str,
                    "issues": [str],
                    "warnings": [str],
                    "is_promoted": bool
                }
            ],
            "issues_by_type": {
                "version_mismatch": int,
                "missing_datetime": int,
                ...
            }
        }
    """
    logger.info("Starting STAC repair inventory")

    collection_id = params.get('collection_id')
    prioritize_promoted = params.get('prioritize_promoted', True)
    limit = params.get('limit', 1000)

    repo = PgStacRepository()
    items_with_issues: List[Dict[str, Any]] = []
    issues_by_type: Dict[str, int] = {}
    total_scanned = 0

    # Get promoted item IDs for prioritization
    promoted_item_ids = set()
    promoted_collection_ids = set()
    if prioritize_promoted:
        try:
            from infrastructure import PromotedDatasetRepository
            promoted_repo = PromotedDatasetRepository()
            promoted_datasets = promoted_repo.list_all()
            for pd in promoted_datasets:
                if pd.stac_item_id:
                    promoted_item_ids.add(pd.stac_item_id)
                if pd.stac_collection_id:
                    promoted_collection_ids.add(pd.stac_collection_id)
            logger.info(
                f"Loaded {len(promoted_item_ids)} promoted items, "
                f"{len(promoted_collection_ids)} promoted collections"
            )
        except Exception as e:
            logger.warning(f"Could not load promoted datasets: {e}")

    # Query items from pgSTAC
    try:
        items = _query_stac_items(repo, collection_id, limit)
        logger.info(f"Retrieved {len(items)} items to scan")

        for item_dict in items:
            total_scanned += 1
            item_id = item_dict.get('id', 'unknown')
            item_collection = item_dict.get('collection', 'unknown')

            # Validate item
            result = STACValidator.validate_item(item_dict, check_pydantic=False)

            if not result.is_valid or result.warnings:
                # Track issue types
                for issue in result.issues:
                    issue_type = _categorize_issue(issue)
                    issues_by_type[issue_type] = issues_by_type.get(issue_type, 0) + 1

                # Check if promoted
                is_promoted = (
                    item_id in promoted_item_ids or
                    item_collection in promoted_collection_ids
                )

                items_with_issues.append({
                    "item_id": item_id,
                    "collection_id": item_collection,
                    "issues": result.issues,
                    "warnings": result.warnings,
                    "is_promoted": is_promoted
                })

        # Sort: promoted items first, then by issue count
        items_with_issues.sort(
            key=lambda x: (not x['is_promoted'], -len(x['issues']))
        )

        logger.info(
            f"Inventory complete: {total_scanned} scanned, "
            f"{len(items_with_issues)} with issues"
        )

        return {
            "total_scanned": total_scanned,
            "items_with_issues": items_with_issues,
            "issues_by_type": issues_by_type,
            "promoted_items_affected": sum(
                1 for i in items_with_issues if i['is_promoted']
            )
        }

    except Exception as e:
        logger.error(f"Inventory failed: {e}")
        raise


def stac_repair_item(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Repair stage: Fix a single STAC item.

    Parameters:
        item_id: STAC item ID to repair
        collection_id: Collection the item belongs to
        issues: List of issues to fix
        fix_version: Repair STAC version
        fix_datetime: Add datetime if missing
        fix_geometry: Derive geometry from bbox

    Returns:
        {
            "item_id": str,
            "repaired": bool,
            "repairs_made": [str],
            "error": str (if failed)
        }
    """
    item_id = params.get('item_id')
    collection_id = params.get('collection_id')
    fix_version = params.get('fix_version', True)
    fix_datetime = params.get('fix_datetime', True)
    fix_geometry = params.get('fix_geometry', True)

    logger.info(f"Repairing STAC item: {item_id}")

    repo = PgStacRepository()

    try:
        # Fetch current item
        item_dict = _get_item_by_id(repo, item_id, collection_id)
        if not item_dict:
            return {
                "item_id": item_id,
                "repaired": False,
                "error": "Item not found"
            }

        # Repair item
        repaired_dict, repairs = STACRepair.repair_item(
            item_dict,
            collection_id=collection_id,
            fix_version=fix_version,
            fix_datetime=fix_datetime,
            fix_geometry=fix_geometry
        )

        if not repairs:
            logger.info(f"No repairs needed for {item_id}")
            return {
                "item_id": item_id,
                "repaired": False,
                "repairs_made": []
            }

        # Update item in database
        success = _update_item(repo, repaired_dict, collection_id)

        if success:
            logger.info(f"Repaired {item_id}: {', '.join(repairs)}")
            return {
                "item_id": item_id,
                "repaired": True,
                "repairs_made": repairs
            }
        else:
            return {
                "item_id": item_id,
                "repaired": False,
                "error": "Failed to update item in database"
            }

    except Exception as e:
        logger.error(f"Failed to repair {item_id}: {e}")
        return {
            "item_id": item_id,
            "repaired": False,
            "error": str(e)
        }


# =============================================================================
# PRIVATE HELPER FUNCTIONS
# =============================================================================

def _query_stac_items(
    repo: PgStacRepository,
    collection_id: Optional[str],
    limit: int
) -> List[Dict[str, Any]]:
    """
    Query STAC items from pgSTAC.

    Args:
        repo: PgStacRepository instance
        collection_id: Optional collection filter
        limit: Maximum items to return

    Returns:
        List of item dicts
    """
    from infrastructure.postgresql import PostgreSQLRepository

    pg_repo = PostgreSQLRepository(schema_name='pgstac')

    with pg_repo._get_connection() as conn:
        with conn.cursor() as cur:
            if collection_id:
                cur.execute(
                    """
                    SELECT content
                    FROM pgstac.items
                    WHERE collection = %s
                    LIMIT %s
                    """,
                    (collection_id, limit)
                )
            else:
                cur.execute(
                    """
                    SELECT content
                    FROM pgstac.items
                    LIMIT %s
                    """,
                    (limit,)
                )

            rows = cur.fetchall()
            return [row['content'] for row in rows]


def _get_item_by_id(
    repo: PgStacRepository,
    item_id: str,
    collection_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get a single STAC item by ID.

    Args:
        repo: PgStacRepository instance
        item_id: Item ID
        collection_id: Collection ID

    Returns:
        Item dict or None
    """
    from infrastructure.postgresql import PostgreSQLRepository

    pg_repo = PostgreSQLRepository(schema_name='pgstac')

    with pg_repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content
                FROM pgstac.items
                WHERE id = %s AND collection = %s
                """,
                (item_id, collection_id)
            )
            row = cur.fetchone()
            return row['content'] if row else None


def _update_item(
    repo: PgStacRepository,
    item_dict: Dict[str, Any],
    collection_id: str
) -> bool:
    """
    Update a STAC item in pgSTAC.

    Uses pgstac.upsert_item for atomic update.

    Args:
        repo: PgStacRepository instance
        item_dict: Updated item dict
        collection_id: Collection ID

    Returns:
        True if successful
    """
    from infrastructure.postgresql import PostgreSQLRepository

    pg_repo = PostgreSQLRepository(schema_name='pgstac')

    try:
        # Ensure collection field is set
        item_dict['collection'] = collection_id
        item_json = json.dumps(item_dict)

        with pg_repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Use upsert to update existing item
                cur.execute(
                    "SELECT * FROM pgstac.upsert_item(%s::jsonb)",
                    (item_json,)
                )
                conn.commit()
                return True

    except Exception as e:
        logger.error(f"Failed to update item: {e}")
        return False


def _categorize_issue(issue: str) -> str:
    """
    Categorize an issue string into a type.

    Args:
        issue: Issue description string

    Returns:
        Issue type category
    """
    issue_lower = issue.lower()

    if 'stac_version' in issue_lower or 'version' in issue_lower:
        return 'version_mismatch'
    elif 'datetime' in issue_lower:
        return 'missing_datetime'
    elif 'geometry' in issue_lower:
        return 'geometry_issue'
    elif 'bbox' in issue_lower:
        return 'bbox_issue'
    elif 'collection' in issue_lower:
        return 'collection_missing'
    elif 'required' in issue_lower or 'missing' in issue_lower:
        return 'missing_field'
    else:
        return 'other'


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    'stac_repair_inventory',
    'stac_repair_item'
]
