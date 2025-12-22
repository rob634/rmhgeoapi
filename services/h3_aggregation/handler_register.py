# ============================================================================
# CLAUDE CONTEXT - H3 DATASET REGISTRATION HANDLER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Service Handler - Dataset Registration
# PURPOSE: Register datasets in h3.dataset_registry
# LAST_REVIEWED: 22 DEC 2025
# EXPORTS: h3_register_dataset
# DEPENDENCIES: infrastructure.h3_repository
# ============================================================================
"""
H3 Dataset Registration Handler.

Registers datasets in h3.dataset_registry. This is Stage 1 of the
h3_register_dataset job workflow. Provides UPSERT semantics (create
or update existing dataset).

Usage:
    result = h3_register_dataset({
        "id": "copdem_glo30",
        "display_name": "Copernicus DEM GLO-30",
        "theme": "terrain",
        "data_category": "elevation",
        "source_type": "planetary_computer",
        "source_config": {
            "collection": "cop-dem-glo-30",
            "asset": "data"
        },
        "stat_types": ["mean", "min", "max"]
    })
"""

from typing import Dict, Any
from util_logger import LoggerFactory, ComponentType

from .base import validate_dataset_id


def h3_register_dataset(params: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Register dataset in h3.dataset_registry.

    Handler that:
    1. Validates required parameters
    2. Calls H3Repository.register_dataset() (UPSERT)
    3. Returns registration result

    Args:
        params: Task parameters containing:
            Required:
            - id (str): Unique dataset identifier
            - display_name (str): Human-readable name
            - theme (str): Data theme for partitioning
            - data_category (str): Specific category
            - source_type (str): Source type (planetary_computer, azure, url)
            - source_config (dict): Source-specific configuration

            Optional:
            - stat_types (list): Default stat types
            - unit (str): Unit of measurement
            - description (str): Dataset description
            - source_name (str): Attribution name
            - source_url (str): Source URL
            - source_license (str): License identifier
            - recommended_h3_res (int): Recommended resolution
            - nodata_value (float): Default nodata value
            - source_job_id (str): Job ID for tracking

        context: Optional execution context (not used)

    Returns:
        Success dict with registration result:
        {
            "success": True,
            "result": {
                "id": str,
                "action": "registered" | "updated",
                "created": bool,
                "theme": str,
                "source_type": str
            }
        }

    Raises:
        ValueError: If required parameters missing or invalid
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "h3_register_dataset")

    # STEP 1: Extract and validate required parameters
    dataset_id = params.get('id')
    display_name = params.get('display_name')
    theme = params.get('theme')
    data_category = params.get('data_category')
    source_type = params.get('source_type')
    source_config = params.get('source_config')

    # Validate required fields
    if not dataset_id:
        raise ValueError("'id' is required")
    if not display_name:
        raise ValueError("'display_name' is required")
    if not theme:
        raise ValueError("'theme' is required")
    if not data_category:
        raise ValueError("'data_category' is required")
    if not source_type:
        raise ValueError("'source_type' is required")
    if not source_config:
        raise ValueError("'source_config' is required")
    if not isinstance(source_config, dict):
        raise ValueError("'source_config' must be a dict/object")

    validate_dataset_id(dataset_id)

    # Extract optional parameters
    stat_types = params.get('stat_types', ['mean', 'sum', 'count'])
    unit = params.get('unit')
    description = params.get('description')
    source_name = params.get('source_name')
    source_url = params.get('source_url')
    source_license = params.get('source_license')
    recommended_h3_res = params.get('recommended_h3_res')
    nodata_value = params.get('nodata_value')
    source_job_id = params.get('source_job_id')

    logger.info(f"📝 Registering dataset: {dataset_id}")
    logger.info(f"   Theme: {theme}, Category: {data_category}")
    logger.info(f"   Source type: {source_type}")
    logger.debug(f"   Source config: {source_config}")

    try:
        from infrastructure.h3_repository import H3Repository

        h3_repo = H3Repository()

        # STEP 2: Register dataset (UPSERT)
        result = h3_repo.register_dataset(
            id=dataset_id,
            display_name=display_name,
            theme=theme,
            data_category=data_category,
            source_type=source_type,
            source_config=source_config,
            stat_types=stat_types,
            unit=unit,
            description=description,
            source_name=source_name,
            source_url=source_url,
            source_license=source_license,
            recommended_h3_res=recommended_h3_res,
            nodata_value=nodata_value
        )

        # STEP 3: Determine action (created vs updated)
        created = result.get('created', False)
        action = "registered" if created else "updated"

        logger.info(f"✅ Dataset '{dataset_id}' {action} successfully")
        if source_job_id:
            logger.debug(f"   Source job: {source_job_id[:8]}...")

        return {
            "success": True,
            "result": {
                "id": dataset_id,
                "action": action,
                "created": created,
                "theme": theme,
                "data_category": data_category,
                "source_type": source_type,
                "stat_types": stat_types,
                "updated_at": result.get('updated_at'),
                "source_job_id": source_job_id
            }
        }

    except ValueError as e:
        # Validation errors (theme, source_type, etc.)
        logger.error(f"❌ Validation error: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": "ValidationError"
        }

    except Exception as e:
        logger.error(f"❌ Registration failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

        return {
            "success": False,
            "error": f"Registration failed: {str(e)}",
            "error_type": type(e).__name__
        }


# Export for handler registration
__all__ = ['h3_register_dataset']
