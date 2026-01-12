# ============================================================================
# STAC REBUILD HANDLERS
# ============================================================================
# STATUS: Service layer - Handlers for rebuild_stac job
# PURPOSE: Validate sources and regenerate STAC items
# CREATED: 10 JAN 2026
# EPIC: E7 Pipeline Infrastructure -> F7.11 STAC Catalog Self-Healing
# ============================================================================
"""
STAC Rebuild Handlers.

Handlers for the rebuild_stac job that regenerates STAC items from source data.
Used to remediate broken backlinks detected by F7.10 Metadata Consistency.

Handlers:
    stac_rebuild_validate: Check which sources exist and can be rebuilt
    stac_rebuild_item: Regenerate STAC item for a single source

Exports:
    stac_rebuild_validate: Stage 1 handler
    stac_rebuild_item: Stage 2 handler
"""

from typing import Dict, Any, List
from datetime import datetime, timezone

from util_logger import LoggerFactory, ComponentType
from config.defaults import STACDefaults

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "rebuild_stac")


def stac_rebuild_validate(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate which sources exist and can have STAC items rebuilt.

    Stage 1 handler for rebuild_stac job.

    Args:
        params: {
            "data_type": "vector" | "raster",
            "items": ["table1", "table2", ...],
            "schema": "geo",
            "collection_id": optional override,
            "force_recreate": bool
        }

    Returns:
        {
            "success": True,
            "result": {
                "total_requested": int,
                "valid_items": [{"name": str, "exists": True, ...}],
                "invalid_items": [{"name": str, "reason": str}],
                "data_type": str,
                "collection_id": str
            }
        }
    """
    data_type = params.get("data_type")
    items = params.get("items", [])
    schema = params.get("schema", "geo")
    collection_id = params.get("collection_id")
    force_recreate = params.get("force_recreate", False)

    logger.info(f"🔍 Validating {len(items)} {data_type} items for STAC rebuild")

    if not items:
        return {
            "success": True,
            "result": {
                "total_requested": 0,
                "valid_items": [],
                "invalid_items": [],
                "data_type": data_type,
                "message": "No items provided"
            }
        }

    valid_items = []
    invalid_items = []

    if data_type == "vector":
        valid_items, invalid_items = _validate_vector_sources(items, schema)
        # Default collection for vectors
        if not collection_id:
            collection_id = STACDefaults.VECTOR_COLLECTION

    elif data_type == "raster":
        valid_items, invalid_items = _validate_raster_sources(items)
        # Default collection for rasters
        if not collection_id:
            collection_id = STACDefaults.RASTER_COLLECTION

    else:
        return {
            "success": False,
            "error": f"Unsupported data_type: {data_type}",
            "error_type": "ValidationError"
        }

    logger.info(
        f"✅ Validation complete: {len(valid_items)} valid, "
        f"{len(invalid_items)} invalid out of {len(items)} requested"
    )

    return {
        "success": True,
        "result": {
            "total_requested": len(items),
            "valid_items": valid_items,
            "invalid_items": invalid_items,
            "data_type": data_type,
            "schema": schema,
            "collection_id": collection_id,
            "force_recreate": force_recreate,
            "validated_at": datetime.now(timezone.utc).isoformat()
        }
    }


def _validate_vector_sources(
    items: List[str],
    schema: str = "geo"
) -> tuple[List[Dict], List[Dict]]:
    """
    Check which PostGIS tables exist.

    Returns:
        (valid_items, invalid_items)
    """
    from infrastructure.postgresql import PostgreSQLRepository

    valid = []
    invalid = []

    try:
        repo = PostgreSQLRepository(target_database="app")

        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                for table_name in items:
                    # Check if table exists in schema
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = %s AND table_name = %s
                        ) as exists
                    """, (schema, table_name))

                    result = cur.fetchone()
                    exists = result['exists'] if isinstance(result, dict) else result[0]

                    if exists:
                        # Also check if it has geometry
                        cur.execute("""
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema = %s
                            AND table_name = %s
                            AND udt_name = 'geometry'
                            LIMIT 1
                        """, (schema, table_name))

                        geom_row = cur.fetchone()

                        if geom_row:
                            geom_col = geom_row['column_name'] if isinstance(geom_row, dict) else geom_row[0]
                            valid.append({
                                "name": table_name,
                                "schema": schema,
                                "geometry_column": geom_col
                            })
                        else:
                            invalid.append({
                                "name": table_name,
                                "reason": "Table exists but has no geometry column"
                            })
                    else:
                        invalid.append({
                            "name": table_name,
                            "reason": f"Table does not exist in {schema} schema"
                        })

    except Exception as e:
        logger.error(f"Error validating vector sources: {e}")
        # Mark all as invalid on error
        for table_name in items:
            if not any(v.get("name") == table_name for v in valid):
                invalid.append({
                    "name": table_name,
                    "reason": f"Validation error: {str(e)}"
                })

    return valid, invalid


def _validate_raster_sources(items: List[str]) -> tuple[List[Dict], List[Dict]]:
    """
    Check which COG IDs exist in app.cog_metadata.

    Implemented: 12 JAN 2026 - S7.11.5

    Args:
        items: List of COG IDs to validate

    Returns:
        (valid_items, invalid_items)
    """
    from infrastructure.raster_metadata_repository import get_raster_metadata_repository

    valid = []
    invalid = []

    try:
        cog_repo = get_raster_metadata_repository()

        for cog_id in items:
            # Check if COG exists in cog_metadata
            cog_record = cog_repo.get_by_id(cog_id)

            if cog_record:
                valid.append({
                    "name": cog_id,
                    "container": cog_record.get("container"),
                    "blob_path": cog_record.get("blob_path"),
                    "collection_id": cog_record.get("stac_collection_id"),
                    "band_count": cog_record.get("band_count", 1)
                })
            else:
                invalid.append({
                    "name": cog_id,
                    "reason": "COG not found in app.cog_metadata"
                })

    except Exception as e:
        logger.error(f"Error validating raster sources: {e}")
        # If we can't query cog_metadata, mark all as invalid
        invalid = [
            {"name": item, "reason": f"Failed to query cog_metadata: {e}"}
            for item in items
        ]
        return [], invalid

    return valid, invalid


def stac_rebuild_item(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Rebuild STAC item for a single source.

    Stage 2 handler for rebuild_stac job. Calls existing create_vector_stac
    or extract_stac_metadata handlers.

    Args:
        params: {
            "data_type": "vector" | "raster",
            "item_name": str,
            "schema": "geo",
            "collection_id": str,
            "force_recreate": bool,
            "job_id": str
        }

    Returns:
        {
            "success": True,
            "result": {
                "rebuilt": True,
                "item_id": str,
                "item_name": str,
                ...
            }
        }
    """
    data_type = params.get("data_type")
    item_name = params.get("item_name")
    schema = params.get("schema", "geo")
    collection_id = params.get("collection_id")
    force_recreate = params.get("force_recreate", False)
    job_id = params.get("job_id", "unknown")

    logger.info(f"🔨 Rebuilding STAC for {data_type}: {schema}.{item_name}")

    start_time = datetime.now(timezone.utc)

    try:
        if data_type == "vector":
            result = _rebuild_vector_stac(
                table_name=item_name,
                schema=schema,
                collection_id=collection_id,
                force_recreate=force_recreate,
                job_id=job_id
            )

        elif data_type == "raster":
            result = _rebuild_raster_stac(
                cog_id=item_name,
                collection_id=collection_id,
                force_recreate=force_recreate,
                job_id=job_id
            )

        else:
            return {
                "success": False,
                "error": f"Unsupported data_type: {data_type}",
                "error_type": "ValidationError"
            }

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()

        if result.get("success"):
            logger.info(
                f"✅ Rebuilt STAC for {item_name} in {duration:.2f}s - "
                f"item_id={result.get('result', {}).get('item_id')}"
            )
            # Add rebuilt flag for finalize_job counting
            result["result"]["rebuilt"] = True
            result["result"]["duration_seconds"] = round(duration, 2)
        else:
            logger.error(f"❌ Failed to rebuild STAC for {item_name}: {result.get('error')}")

        return result

    except Exception as e:
        import traceback
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.error(f"❌ Exception rebuilding STAC for {item_name}: {e}")

        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "item_name": item_name,
            "data_type": data_type,
            "duration_seconds": round(duration, 2),
            "traceback": traceback.format_exc()
        }


def _rebuild_vector_stac(
    table_name: str,
    schema: str,
    collection_id: str,
    force_recreate: bool,
    job_id: str
) -> Dict[str, Any]:
    """
    Rebuild STAC item for a vector table.

    Uses existing create_vector_stac handler.
    """
    from infrastructure.pgstac_bootstrap import PgStacBootstrap

    # If force_recreate, delete existing STAC item first
    if force_recreate:
        stac_infra = PgStacBootstrap()
        # Expected item_id pattern: postgis-{schema}-{table_name}
        expected_item_id = f"postgis-{schema}-{table_name}"

        if stac_infra.item_exists(expected_item_id, collection_id):
            logger.info(f"🗑️ Deleting existing STAC item: {expected_item_id}")
            try:
                stac_infra.delete_item(expected_item_id, collection_id)
            except Exception as e:
                logger.warning(f"⚠️ Could not delete existing item: {e}")

    # Call existing create_vector_stac handler
    from services.stac_vector_catalog import create_vector_stac

    return create_vector_stac({
        "schema": schema,
        "table_name": table_name,
        "collection_id": collection_id,
        "job_id": job_id,
        "source_file": f"rebuild_stac:{job_id}"  # Track source
    })


def _rebuild_raster_stac(
    cog_id: str,
    collection_id: str,
    force_recreate: bool,
    job_id: str
) -> Dict[str, Any]:
    """
    Rebuild STAC item for a raster COG.

    Implemented: 12 JAN 2026 - S7.11.5

    Uses RasterMetadata from app.cog_metadata to regenerate STAC item.
    This is the reverse of extract_stac_metadata which populates cog_metadata.

    Args:
        cog_id: COG identifier (usually same as STAC item ID)
        collection_id: Target STAC collection
        force_recreate: Delete existing STAC item before creating
        job_id: Job ID for tracking

    Returns:
        Success dict with rebuilt item info or error dict
    """
    from infrastructure.raster_metadata_repository import get_raster_metadata_repository
    from infrastructure.pgstac_bootstrap import PgStacBootstrap
    from infrastructure.pgstac_repository import PgStacRepository
    from core.models.unified_metadata import RasterMetadata
    from config import get_config

    config = get_config()

    try:
        # Load COG metadata from database
        cog_repo = get_raster_metadata_repository()
        cog_record = cog_repo.get_by_id(cog_id)

        if not cog_record:
            return {
                "success": False,
                "error": f"COG not found in cog_metadata: {cog_id}",
                "error_type": "NotFoundError",
                "cog_id": cog_id
            }

        # Create RasterMetadata domain object from database row
        raster_meta = RasterMetadata.from_db_row(cog_record)

        # Use collection_id from parameter or fall back to stored value
        target_collection = collection_id or raster_meta.stac_collection_id or STACDefaults.RASTER_COLLECTION

        # Initialize pgSTAC infrastructure
        stac_infra = PgStacBootstrap()
        pgstac_repo = PgStacRepository()

        # If force_recreate, delete existing item first
        if force_recreate:
            expected_item_id = cog_id
            if stac_infra.item_exists(expected_item_id, target_collection):
                logger.info(f"🗑️ Deleting existing STAC item: {expected_item_id}")
                try:
                    stac_infra.delete_item(expected_item_id, target_collection)
                except Exception as e:
                    logger.warning(f"⚠️ Could not delete existing item: {e}")

        # Generate STAC item from RasterMetadata
        base_url = config.stac_base_url or "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net"
        titiler_url = config.titiler_base_url

        stac_item_dict = raster_meta.to_stac_item(
            base_url=base_url,
            titiler_base_url=titiler_url
        )

        # Insert into pgSTAC
        # Need to convert dict to pystac.Item for insertion
        import pystac
        stac_item = pystac.Item.from_dict(stac_item_dict)

        # Insert item
        insert_result = pgstac_repo.insert_item(stac_item, target_collection)

        if not insert_result:
            return {
                "success": False,
                "error": "Failed to insert STAC item into pgSTAC",
                "error_type": "InsertionError",
                "cog_id": cog_id
            }

        # Update cog_metadata with new STAC linkage
        cog_repo.update_stac_linkage(
            cog_id=cog_id,
            stac_item_id=cog_id,
            stac_collection_id=target_collection
        )

        logger.info(f"✅ Rebuilt raster STAC item: {cog_id} in collection {target_collection}")

        return {
            "success": True,
            "result": {
                "rebuilt": True,
                "item_id": cog_id,
                "item_name": cog_id,
                "collection_id": target_collection,
                "source": "cog_metadata",
                "job_id": job_id
            }
        }

    except Exception as e:
        logger.error(f"❌ Failed to rebuild raster STAC for {cog_id}: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "cog_id": cog_id
        }


# Module exports
__all__ = ['stac_rebuild_validate', 'stac_rebuild_item']
