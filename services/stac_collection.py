# ============================================================================
# STAC COLLECTION SERVICE
# ============================================================================
# STATUS: Service layer - STAC collection creation for raster datasets
# PURPOSE: Create STAC collections with pgSTAC search for raster datasets
# LAST_REVIEWED: 17 FEB 2026
# EXPORTS: build_raster_stac_collection, create_stac_collection
# DEPENDENCIES: pystac, psycopg, azure-storage-blob
# ============================================================================
"""
STAC Collection Service.

Creates STAC collections for raster datasets (both single COG and tiled).

Key Features:
    - build_raster_stac_collection(): Canonical collection builder (dict) for ALL raster ETL
    - Collection with STAC Items for each COG tile
    - Spatial/temporal extent calculation from constituent tiles
    - PgSTAC collections table integration
    - pgSTAC search registration for TiTiler mosaic visualization (tiled)

Call Modes:
    1. Direct call: receives cog_blobs/cog_container directly in params
    2. Fan-in pattern: receives previous_results from earlier stage (legacy)

Exports:
    build_raster_stac_collection: Canonical collection dict builder (single COG + tiled)
    create_stac_collection: Task handler for tiled raster collection creation
"""

import os
import json
import traceback  # For fail-fast error reporting (11 NOV 2025)
# asyncio removed (17 NOV 2025) - direct database writes are synchronous
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
import psycopg  # Simple connections - NO pooling for Azure Functions (11 NOV 2025)
from azure.storage.blob import BlobServiceClient

import pystac
from pystac import Collection, Extent, SpatialExtent, TemporalExtent

from util_logger import LoggerFactory, ComponentType
from config import get_config  # For TiTiler base URL and other config (17 NOV 2025)
from infrastructure.pgstac_repository import PgStacRepository  # For collection/item operations (Phase 2B: 17 NOV 2025)
from services.pgstac_search_registration import PgSTACSearchRegistration  # NEW (17 NOV 2025): Direct database registration (Option A)
from core.models.stac import ProvenanceProperties  # V0.9 P2.6: Replaces AppMetadata


# Logger
logger = LoggerFactory.create_logger(
    ComponentType.SERVICE,
    "STACCollectionService"
)


def create_stac_collection(
    params: dict,
    context: dict = None
) -> dict:
    """
    Create STAC collection for tiled raster datasets.

    V0.8 (25 JAN 2026): Supports two call modes:
        1. Direct call: cog_blobs/cog_container passed directly in params
        2. Fan-in pattern: previous_results from earlier stage (legacy)

    Task Handler Contract:
        - Receives: params (dict), context (dict, optional)
        - Returns: {"success": bool, ...}

    Args:
        params: Task parameters containing:
            Direct call mode (V0.8):
                - cog_blobs: List of COG blob paths
                - cog_container: Container where COGs are stored
                - collection_id: Collection identifier
                - item_id: Optional STAC item ID
                - title: Collection title
                - description: Collection description

            Fan-in mode (legacy):
                - previous_results: List with previous stage result
                - collection_id: Collection identifier

            Common:
                - license: STAC license (default: "proprietary")
                - dataset_id, resource_id, version_id: Platform passthrough
                - access_level: Access level for collection
        context: Optional task context (unused)

    Returns:
        {
            "success": bool,
            "collection_id": str,
            "item_id": str,
            "tile_count": int,
            "spatial_extent": [minx, miny, maxx, maxy],
            "search_id": str,
            "viewer_url": str
        }

    Error Return:
        {
            "success": False,
            "error": str,
            "error_type": str
        }
    """
    try:
        from config import get_config
        config = get_config()

        # =====================================================================
        # DIRECT CALL MODE: Handler passes cog_blobs/cog_container directly
        # =====================================================================
        if params.get("cog_blobs") and params.get("cog_container"):
            logger.info(f"🔄 STAC collection - DIRECT CALL MODE")

            # Extract parameters directly
            tile_blobs = params.get("cog_blobs", [])
            cog_container = params.get("cog_container")
            collection_id = params.get("collection_id")
            item_id = params.get("item_id")
            title = params.get("title", f"Tiled Raster: {collection_id}")
            description = params.get("description", f"Tiled COG collection: {collection_id}")
            license_val = params.get("license", "proprietary")
            spatial_extent = params.get("spatial_extent")  # Optional, will be calculated if None

            # Use item_id as collection_id if provided (for single-item collections)
            final_collection_id = item_id if item_id else collection_id

            if not collection_id:
                logger.error("❌ [STAC-ERROR] collection_id is required")
                return {
                    "success": False,
                    "error": "collection_id is required",
                    "error_type": "ValueError"
                }

            if not tile_blobs:
                logger.error("❌ [STAC-ERROR] cog_blobs is empty")
                return {
                    "success": False,
                    "error": "cog_blobs cannot be empty",
                    "error_type": "ValueError"
                }

            logger.info(f"   Collection: {collection_id}")
            logger.info(f"   Final ID: {final_collection_id}")
            logger.info(f"   Tile count: {len(tile_blobs)}")
            logger.info(f"   COG container: {cog_container}")

            # BUG-006 FIX (27 JAN 2026): Extract raster_type for TiTiler bidx params
            raster_type = params.get("raster_type")
            if raster_type:
                logger.info(f"   Raster type: {raster_type.get('detected_type')}, {raster_type.get('band_count')} bands")

            # Job traceability (02 FEB 2026): Extract job_id and job_type
            job_id = params.get("_job_id")
            job_type = params.get("_job_type")
            if job_id:
                logger.info(f"   Job traceability: {job_id[:8]}... ({job_type})")

            container = params.get("container", config.storage.silver.cogs)
            result = _create_stac_collection_impl(
                collection_id=final_collection_id,
                description=description,
                tile_blobs=tile_blobs,
                container=container,
                cog_container=cog_container,
                license_val=license_val,
                spatial_extent=spatial_extent,
                temporal_extent=None,
                raster_type=raster_type,  # BUG-006: Pass for TiTiler URLs
                job_id=job_id,  # Job traceability (02 FEB 2026)
                job_type=job_type  # Job traceability (02 FEB 2026)
            )

            return result

        # =====================================================================
        # LEGACY: FAN-IN MODE (receives previous_results from earlier stage)
        # =====================================================================
        logger.info(f"🔄 STAC collection - FAN-IN MODE (legacy)")

        # Extract parameters from fan_in pattern
        if "fan_in_source" in params:
            from core.fan_in import load_fan_in_results, get_job_parameters
            previous_results = load_fan_in_results(params)
            job_parameters = get_job_parameters(params)
            logger.info(f"Fan-in DB reference: loaded {len(previous_results)} results")
        else:
            previous_results = params.get("previous_results", [])
            job_parameters = params.get("job_parameters", {})

        collection_id = job_parameters.get("collection_id") or params.get("collection_id")
        stac_item_id = job_parameters.get("stac_item_id") or params.get("stac_item_id")
        description = job_parameters.get("collection_description") or params.get("description") or f"Raster collection: {collection_id}"
        license_val = params.get("license", "proprietary")
        container = params.get("container", config.storage.silver.cogs)

        final_collection_id = stac_item_id if stac_item_id else collection_id

        logger.info(f"   Collection: {collection_id}")
        logger.info(f"   Final ID: {final_collection_id}")
        logger.info(f"   Previous results count: {len(previous_results)}")

        if not previous_results:
            logger.error("❌ [STAC-ERROR] No previous_results and no direct cog_blobs/cog_container")
            return {
                "success": False,
                "error": "No previous_results provided. For direct mode, pass cog_blobs and cog_container.",
                "error_type": "ValueError"
            }

        stage_result = previous_results[0]

        if not stage_result.get("success"):
            error_detail = stage_result.get("error", "Unknown error")
            error_type = stage_result.get("error_type", "Unknown")
            logger.error(f"❌ [STAC-ERROR] Previous stage failed: {error_detail}")
            return {
                "success": False,
                "error": f"Previous stage failed: {error_detail}",
                "error_type": error_type
            }

        spatial_extent = stage_result.get("bounds")
        tile_blobs = stage_result.get("cog_blobs", [])
        cog_container = stage_result.get("cog_container")

        if not cog_container:
            logger.error(f"❌ [STAC-ERROR] No cog_container in previous result")
            return {
                "success": False,
                "error": "No cog_container in previous result - cannot create STAC Items",
                "error_type": "ValueError"
            }

        logger.info(f"   Tile count: {len(tile_blobs)}")
        logger.info(f"   COG container: {cog_container}")

        job_id = params.get("_job_id") or job_parameters.get("_job_id")
        job_type = params.get("_job_type") or job_parameters.get("_job_type")
        if job_id:
            logger.info(f"   Job traceability: {job_id[:8]}... ({job_type})")

        result = _create_stac_collection_impl(
            collection_id=final_collection_id,
            description=description,
            tile_blobs=tile_blobs,
            container=container,
            cog_container=cog_container,
            license_val=license_val,
            spatial_extent=spatial_extent,
            temporal_extent=None,
            job_id=job_id,
            job_type=job_type
        )

        return result

    except Exception as e:
        logger.error(f"❌ STAC collection task handler failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def build_raster_stac_collection(
    collection_id: str,
    bbox: List[float],
    description: Optional[str] = None,
    temporal_start: Optional[str] = None,
    license_val: str = "proprietary",
) -> Dict[str, Any]:
    """
    Build a STAC collection dict for raster data.

    CANONICAL COLLECTION BUILDER (17 FEB 2026):
    Single pattern for ALL raster ETL — both single COG and tiled flows.
    Creates a collection dict with ISO3 attribution, ready for pgSTAC upsert.

    Args:
        collection_id: Collection identifier
        bbox: Spatial extent [minx, miny, maxx, maxy]
        description: Optional description (auto-generated if None)
        temporal_start: Optional ISO8601 datetime string (default: now)
        license_val: STAC license (default: "proprietary")

    Returns:
        STAC Collection dict ready for PgStacRepository.insert_collection()
    """
    now = datetime.now(timezone.utc).isoformat()
    temporal = temporal_start or now

    collection_dict = {
        "type": "Collection",
        "id": collection_id,
        "stac_version": "1.0.0",
        "description": description or f"Raster collection: {collection_id}",
        "links": [],
        "license": license_val,
        "extent": {
            "spatial": {"bbox": [bbox]},
            "temporal": {"interval": [[temporal, None]]},
        },
        "stac_extensions": [],
    }

    # Add ISO3 country attribution
    from services.iso3_attribution import get_geo_properties_for_bbox
    geo_props = get_geo_properties_for_bbox(bbox)
    if geo_props:
        collection_dict['geo:iso3'] = geo_props.iso3
        collection_dict['geo:primary_iso3'] = geo_props.primary_iso3
        if geo_props.countries:
            collection_dict['geo:countries'] = geo_props.countries
        logger.debug(f"   Added ISO3 attribution to collection: {geo_props.primary_iso3}")

    return collection_dict


def _create_stac_collection_impl(
    collection_id: str,
    description: str,
    tile_blobs: List[str],
    container: str,
    cog_container: str,
    license_val: str,
    spatial_extent: Optional[List[float]],
    temporal_extent: Optional[List[str]],
    raster_type: Optional[Dict[str, Any]] = None,
    job_id: Optional[str] = None,
    job_type: Optional[str] = None
) -> dict:
    """
    Internal implementation: Create STAC collection with Items for tiled rasters.

    ORTHODOX STAC PATTERN (11 NOV 2025):
    1. Create STAC Collection (with extent, ISO3)
    2. Insert into pgSTAC (creates partition)
    3. Create STAC Items for each COG tile
    4. Register pgSTAC search for TiTiler mosaic visualization

    Args:
        collection_id: Collection identifier
        description: Collection description
        tile_blobs: COG blob paths
        container: Container for tiles (silver-tiles or silver-cogs)
        cog_container: COG files container (silver-cogs)
        license_val: STAC license
        spatial_extent: Spatial bounds or None to calculate
        temporal_extent: Temporal range or None for current time
        raster_type: Raster type dict with band_count, data_type for TiTiler URLs
        job_id: Job ID for STAC item traceability
        job_type: Job type for STAC item traceability

    Returns:
        Dict with success=True and STAC collection details

    Raises:
        Exception: STAC creation or PgSTAC insertion failures
    """
    logger.info(f"Creating STAC collection: {collection_id}")

    try:
        # Get Azure storage account name from config (08 DEC 2025)
        from config import get_config
        config = get_config()
        storage_account = config.storage.silver.account_name

        # Calculate spatial extent if not provided
        if spatial_extent is None:
            logger.info(f"Calculating spatial extent from {len(tile_blobs)} tiles")
            spatial_extent = _calculate_spatial_extent_from_tiles(tile_blobs, container)

        # Calculate temporal extent if not provided
        if temporal_extent is None:
            # Use current time as single timestamp
            now = datetime.now(timezone.utc).isoformat()
            temporal_extent = [now, now]

        # Create STAC collection
        collection = Collection(
            id=collection_id,
            description=description,
            license=license_val,
            extent=Extent(
                spatial=SpatialExtent(bboxes=[spatial_extent]),
                temporal=TemporalExtent(intervals=[[
                    datetime.fromisoformat(temporal_extent[0].replace('Z', '+00:00')),
                    datetime.fromisoformat(temporal_extent[1].replace('Z', '+00:00'))
                ]])
            ),
            stac_extensions=[],
            extra_fields={
                "tile_count": len(tile_blobs),
                "created": datetime.now(timezone.utc).isoformat()
            }
        )

        # Add ISO3 country attribution to collection extra_fields
        from services.iso3_attribution import get_geo_properties_for_bbox
        geo_props = get_geo_properties_for_bbox(spatial_extent)
        if geo_props:
            collection.extra_fields['geo:iso3'] = geo_props.iso3
            collection.extra_fields['geo:primary_iso3'] = geo_props.primary_iso3
            if geo_props.countries:
                collection.extra_fields['geo:countries'] = geo_props.countries
            logger.debug(f"   Added ISO3 attribution to collection: {geo_props.primary_iso3}")

        # CRITICAL (12 NOV 2025): CREATE COLLECTION FIRST before Items
        # PgSTAC requires collections to exist before items because collections
        # create table partitions that items use. Without collection, item insertion
        # fails with: "no partition of relation 'items' found for row"

        # Validate STAC collection
        collection.validate()
        logger.info(f"✅ STAC collection validated: {collection.id}")

        # CRITICAL FIX (18 NOV 2025): Use SINGLE repository instance
        # Two instances = two connections = READ AFTER WRITE consistency issue
        # Solution: Create repository once, use for both insert and verification
        from infrastructure.pgstac_repository import PgStacRepository
        pgstac_repo = PgStacRepository()

        # Insert collection into PgSTAC FIRST (creates partition for items)
        pgstac_id = pgstac_repo.insert_collection(collection)
        logger.info(f"✅ Collection inserted into PgSTAC: {pgstac_id}")

        # Validate collection exists before creating Items (18 NOV 2025: Use SAME repository!)
        # This defensive check ensures PgSTAC partition is ready
        if not pgstac_repo.collection_exists(collection_id):
            raise RuntimeError(
                f"Collection '{collection_id}' was not found in PgSTAC after insertion. "
                f"Cannot create STAC Items without a collection partition. "
                f"This indicates a PgSTAC insertion failure."
            )
        logger.info(f"✅ Collection '{collection_id}' verified in PgSTAC - ready for Items")

        # Import STAC metadata service for item creation
        from services.service_stac_metadata import StacMetadataService
        stac_service = StacMetadataService()

        # V0.9 P2.6: ProvenanceProperties replaces AppMetadata for job traceability
        # Raster visualization is now handled by renders builder inside extract_item_from_blob
        provenance = None
        if job_id:
            detected = raster_type.get('detected_type') if raster_type else None
            provenance = ProvenanceProperties(
                job_id=job_id,
                raster_type=detected,
            )
            logger.info(f"   Job traceability: job_id={job_id[:8]}..., job_type={job_type}")

        # ORTHODOX STAC (11 NOV 2025): Create STAC Items for each COG tile
        # Items are searchable with geometry, datetime, and properties
        # NOW collection partition exists, so Items can be inserted safely
        logger.info(f"📝 Creating STAC Items for {len(tile_blobs)} COG tiles...")

        created_items = []
        failed_items = []

        for i, tile_blob in enumerate(tile_blobs):
            try:
                logger.info(f"   Creating STAC Item {i+1}/{len(tile_blobs)}: {tile_blob}")

                # Generate semantic item ID from blob name
                tile_name = tile_blob.split('/')[-1].replace('_cog.tif', '').replace('.tif', '')
                item_id = f"{collection_id}_{tile_name}"

                # V0.9 P2.6: extract_item_from_blob now builds renders internally
                # V0.9: ProvenanceProperties for job traceability (geoetl:*)
                item = stac_service.extract_item_from_blob(
                    container=cog_container,
                    blob_name=tile_blob,
                    collection_id=collection_id,
                    item_id=item_id,
                    provenance_props=provenance,
                )

                # Insert Item into PgSTAC
                # CRITICAL (12 NOV 2025): Use Pydantic model_dump() for proper JSON serialization
                # stac-pydantic.Item is a Pydantic model - use model_dump(mode='json') pattern
                # This properly serializes datetime objects to ISO strings
                pgstac_id = stac_service.stac.insert_item(item, collection_id)
                created_items.append(item_id)
                logger.debug(f"   ✅ STAC Item created: {item_id} (pgstac_id: {pgstac_id})")

            except Exception as e:
                logger.error(f"   ❌ Failed to create STAC Item for {tile_blob}: {e}")
                logger.error(f"      Container: {cog_container}")
                logger.error(f"      Item ID: {item_id}")
                logger.error(f"      Progress: {i+1}/{len(tile_blobs)}")
                logger.error(f"      Traceback: {traceback.format_exc()}")
                failed_items.append(tile_blob)
                # CRITICAL (11 NOV 2025): Fail fast if Item creation fails
                # Orthodox STAC requires Items - if they fail, the collection is incomplete
                # Better to fail with clear error than succeed with broken/missing Items
                raise RuntimeError(
                    f"STAC Item creation failed for tile {i+1}/{len(tile_blobs)}: {tile_blob} "
                    f"in container {cog_container}. "
                    f"Created {len(created_items)} items before failure. "
                    f"Error: {e}"
                )

        logger.info(f"✅ Created {len(created_items)} STAC Items successfully")
        if len(created_items) != len(tile_blobs):
            logger.warning(
                f"   ⚠️  Only {len(created_items)} of {len(tile_blobs)} items created - "
                f"this should not happen with fail-fast error handling!"
            )

        # =========================================================================
        # Phase 4: Register pgSTAC Search (Direct Database - 17 NOV 2025)
        # =========================================================================
        # OPTION A ARCHITECTURE (Production Security):
        # - ETL pipeline writes directly to pgstac.searches table
        # - TiTiler has read-only database access (better security)
        # - No APIM needed to protect /searches/register endpoint
        # - Atomic operations (collection + search in same workflow)
        # - search_id computed as SHA256 hash (deterministic, permanent)
        # =========================================================================

        search_id = None
        viewer_url = None
        tilejson_url = None
        tiles_url = None

        try:
            logger.info(f"🔍 Registering pgSTAC search (direct database write) for collection: {collection_id}")

            # Initialize search registration service (17 NOV 2025 - Option A: Direct database writes)
            search_registrar = PgSTACSearchRegistration()

            # Register search directly in database (NO TiTiler API call)
            # Pass collection bbox so TileJSON returns correct bounds for auto-zoom (21 NOV 2025)
            # Extract bbox from collection extent (pystac Collection object)
            collection_bbox = None
            if collection.extent and collection.extent.spatial and collection.extent.spatial.bboxes:
                collection_bbox = collection.extent.spatial.bboxes[0]  # First bbox
                logger.debug(f"   Collection bbox for TileJSON: {collection_bbox}")

            search_id = search_registrar.register_collection_search(
                collection_id=collection_id,
                metadata={"name": f"{collection_id} mosaic"},
                bbox=collection_bbox
            )

            logger.info(f"✅ Search registered: {search_id}")
            logger.info(f"🔍 DEBUG: search_id type={type(search_id)}, value='{search_id}', len={len(search_id) if isinstance(search_id, str) else 'N/A'}")

            # Generate visualization URLs
            # BUG-011 FIX (28 JAN 2026): Pass band_indexes for multi-band imagery
            # Without bidx params, TiTiler returns HTTP 500 for 3+ band COGs
            config = get_config()

            # Extract band indexes from raster_type dict (passed as function parameter)
            # BUG-012 FIX (17 FEB 2026): was referencing undefined `raster_meta` variable
            band_indexes = None
            band_count = raster_type.get('band_count') if raster_type else None
            if band_count and band_count > 3:
                band_indexes = [1, 2, 3]
                logger.info(f"   Multi-band imagery ({band_count} bands) - defaulting to RGB bands [1,2,3]")

            urls = search_registrar.get_search_urls(
                search_id=search_id,
                titiler_base_url=config.titiler_base_url,
                assets=["data"],
                band_indexes=band_indexes
            )
            viewer_url = urls["viewer"]
            tilejson_url = urls["tilejson"]
            tiles_url = urls["tiles"]

            logger.info(f"📊 Generated visualization URLs:")
            logger.info(f"   Viewer: {viewer_url}")
            logger.info(f"   TileJSON: {tilejson_url}")
            logger.info(f"   Tiles: {tiles_url}")

            # Update collection metadata with search info
            logger.info(f"🔄 Updating collection with search metadata...")

            # Serialize existing links to dicts (pystac Link objects need conversion)
            existing_links = []
            for link in collection.links:
                if hasattr(link, 'to_dict'):
                    existing_links.append(link.to_dict())
                elif isinstance(link, dict):
                    existing_links.append(link)
                else:
                    # Fallback: convert to dict manually
                    existing_links.append({
                        "rel": getattr(link, 'rel', 'related'),
                        "href": getattr(link, 'href', str(link))
                    })

            # Add search_id to summaries and links to collection
            metadata_update = {
                "summaries": {
                    "mosaic:search_id": [search_id]  # STAC summaries use arrays
                },
                "links": existing_links + [
                    {
                        "rel": "preview",
                        "href": viewer_url,
                        "type": "text/html",
                        "title": "Interactive map preview (TiTiler-PgSTAC)"
                    },
                    {
                        "rel": "tilejson",
                        "href": tilejson_url,
                        "type": "application/json",
                        "title": "TileJSON specification for web maps"
                    },
                    {
                        "rel": "tiles",
                        "href": tiles_url,
                        "type": "image/png",
                        "title": "XYZ tile endpoint (templated)"
                    }
                ]
            }

            # Update collection in pgSTAC
            pgstac_repo = PgStacRepository()
            pgstac_repo.update_collection_metadata(collection_id, metadata_update)

            logger.info(f"✅ Collection metadata updated with search_id: {search_id}")

        except Exception as e:
            # CRITICAL FIX (18 NOV 2025): Eliminate silent errors - propagate exception to task record
            # Search registration failures should fail the entire collection creation task
            # This ensures we know WHY visualization URLs are missing (not silent nulls)
            logger.error(f"❌ Search registration failed - failing task to expose root cause")
            logger.error(f"   Collection: {collection_id}")
            logger.error(f"   Error: {e}")
            logger.error(f"   Error type: {type(e).__name__}")
            logger.error(f"   Traceback: {traceback.format_exc()}")

            # Clean up: Remove collection from PgSTAC since we can't provide visualization
            try:
                logger.info(f"🧹 Cleaning up collection '{collection_id}' due to search registration failure...")
                pgstac_repo = PgStacRepository()
                with pgstac_repo._pg_repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        # Delete collection (CASCADE will delete items)
                        cur.execute("DELETE FROM pgstac.collections WHERE id = %s", (collection_id,))
                        conn.commit()
                logger.info(f"✅ Collection cleanup complete")
            except Exception as cleanup_error:
                logger.error(f"⚠️  Failed to cleanup collection: {cleanup_error}")
                # Don't mask original error with cleanup failure

            # Propagate original exception to task record (fail task)
            raise RuntimeError(
                f"Search registration failed for collection '{collection_id}': {e}"
            ) from e

        # Collection already validated and inserted above (12 NOV 2025)
        # search_id, URLs added if search registration succeeded

        # V0.8 FIX (27 JAN 2026): Return with "result" wrapper to match handler contract
        # Handler expects: {"success": True, "result": {...}}
        # Previously returned data at top level, causing stac_response.get('result', {}) = {}
        return {
            "success": True,
            "result": {
                "collection_id": collection_id,
                "stac_id": collection.id,
                "pgstac_id": pgstac_id,
                "tile_count": len(tile_blobs),
                "items_created": len(created_items),
                "items_failed": len(failed_items),
                "spatial_extent": spatial_extent,
                # pgSTAC search provides mosaic access for tiled collections
                "search_id": search_id,
                "viewer_url": viewer_url,
                "tilejson_url": tilejson_url,
                "tiles_url": tiles_url
            }
        }

    except Exception as e:
        logger.error(f"Failed to create STAC collection: {e}", exc_info=True)
        raise


def _calculate_spatial_extent_from_tiles(
    tile_blobs: List[str],
    container: str
) -> List[float]:
    """
    Calculate spatial extent (bbox) from constituent COG tiles.

    Reads the bounding box from each COG's metadata and computes the
    union of all bboxes to determine the collection extent.

    Args:
        tile_blobs: List of COG blob paths
        container: Azure storage container

    Returns:
        [minx, miny, maxx, maxy] in WGS84

    Raises:
        Exception: If unable to read tile metadata
    """
    import rasterio
    from rasterio.warp import transform_bounds

    logger.info(f"Calculating spatial extent from {len(tile_blobs)} tiles")

    # Initialize extent with extreme values
    minx, miny = float('inf'), float('inf')
    maxx, maxy = float('-inf'), float('-inf')

    # Get Azure credentials from config (08 DEC 2025)
    from config import get_config
    config = get_config()
    storage_account = config.storage.silver.account_name
    storage_key = os.environ.get("AZURE_STORAGE_KEY")

    tiles_read = 0
    for tile_blob in tile_blobs:
        try:
            # Construct vsi path for Azure
            vsi_path = f"/vsiaz/{container}/{tile_blob}"

            # Set Azure credentials for GDAL
            with rasterio.Env(
                AZURE_STORAGE_ACCOUNT=storage_account,
                AZURE_STORAGE_ACCESS_KEY=storage_key
            ):
                with rasterio.open(vsi_path) as src:
                    # Get bounds in source CRS
                    bounds = src.bounds
                    src_crs = src.crs

                    # Transform to WGS84 if needed
                    if src_crs and src_crs.to_string() != 'EPSG:4326':
                        tile_bounds = transform_bounds(
                            src_crs,
                            'EPSG:4326',
                            bounds.left, bounds.bottom,
                            bounds.right, bounds.top
                        )
                    else:
                        tile_bounds = (bounds.left, bounds.bottom, bounds.right, bounds.top)

                    # Update extent
                    minx = min(minx, tile_bounds[0])
                    miny = min(miny, tile_bounds[1])
                    maxx = max(maxx, tile_bounds[2])
                    maxy = max(maxy, tile_bounds[3])

                    tiles_read += 1
                    logger.debug(f"Tile {tiles_read}/{len(tile_blobs)}: {tile_blob} → {tile_bounds}")

        except Exception as e:
            logger.warning(f"Could not read extent from {tile_blob}: {e}")
            continue

    if tiles_read == 0:
        raise Exception("Could not read spatial extent from any tiles")

    extent = [minx, miny, maxx, maxy]
    logger.info(f"Calculated extent from {tiles_read} tiles: {extent}")
    return extent


