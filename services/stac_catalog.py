# ============================================================================
# STAC CATALOG SERVICES
# ============================================================================
# STATUS: Service layer - STAC metadata extraction handlers
# PURPOSE: Implement two-stage pattern for bulk STAC extraction (list + extract)
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: list_raster_files, extract_stac_metadata
# DEPENDENCIES: azure-storage-blob, stac-pydantic
# ============================================================================
"""
STAC Catalog Services - Two-Stage Pattern for Bulk STAC Extraction

Stage 1: list_raster_files - Returns list of raster file names
Stage 2: extract_stac_metadata - Extracts STAC metadata and inserts into PgSTAC

"""

from typing import Any
from datetime import datetime
from infrastructure.blob import BlobRepository

# F7.21: Type-safe result models (25 JAN 2026)
from core.models.raster_results import STACCreationData, STACCreationResult

# NOTE: StacMetadataService import moved inside extract_stac_metadata() to avoid
# stac-pydantic import at module load time (allows registry to build without STAC deps)


def list_raster_files(params: dict) -> dict[str, Any]:
    """
    Stage 1: List all raster files in container.

    Returns list of raster file names for Stage 2 fan-out.

    Args:
        params: {
            "container_name": str,
            "extension_filter": str (default: ".tif"),
            "prefix": str (default: ""),
            "file_limit": int | None
        }

    Returns:
        Dict with success status and raster file list:
        {
            "success": True,
            "result": {
                "raster_files": [list of raster file names],
                "total_count": int,
                "extension_filter": str,
                "execution_info": {...}
            }
        }
    """
    try:
        container_name = params["container_name"]
        extension_filter = params.get("extension_filter", ".tif").lower()
        prefix = params.get("prefix", "")
        file_limit = params.get("file_limit")

        # Silver zone - STAC catalog references processed data
        blob_repo = BlobRepository.for_zone("silver")

        start_time = datetime.utcnow()

        # Get all blobs
        blobs = blob_repo.list_blobs(
            container=container_name,
            prefix=prefix,
            limit=None  # Get all, then filter
        )

        # Filter by extension
        raster_files = []
        for blob in blobs:
            blob_name = blob['name']
            if blob_name.lower().endswith(extension_filter):
                raster_files.append(blob_name)

                # Apply file_limit if specified
                if file_limit and len(raster_files) >= file_limit:
                    break

        duration = (datetime.utcnow() - start_time).total_seconds()

        # SUCCESS - return raster file names for Stage 2
        return {
            "success": True,
            "result": {
                "raster_files": raster_files,
                "total_count": len(raster_files),
                "extension_filter": extension_filter,
                "container_name": container_name,
                "prefix": prefix,
                "execution_info": {
                    "scan_duration_seconds": round(duration, 2),
                    "total_blobs_scanned": len(blobs),
                    "raster_files_found": len(raster_files),
                    "file_limit_applied": file_limit is not None
                }
            }
        }

    except Exception as e:
        # FAILURE - return error
        return {
            "success": False,
            "error": str(e) or type(e).__name__,
            "error_type": type(e).__name__,
            "container_name": params.get("container_name")
        }


def extract_stac_metadata(params: dict) -> dict[str, Any]:
    """
    Stage 2: Extract STAC metadata for a single raster file.

    This function is called once per raster file in parallel.
    Extracts STAC Item metadata and inserts into PgSTAC database.

    Args:
        params: {
            "container_name": str,
            "blob_name": str,
            "collection_id": str (default: "dev"),
            "item_id": str (optional: custom STAC item ID, auto-generated if not provided)
        }

    Returns:
        Dict with success status and STAC metadata:
        {
            "success": True,
            "result": {
                "item_id": str,
                "blob_name": str,
                "collection_id": str,
                "bbox": [float, float, float, float],
                "geometry_type": str,
                "bands_count": int,
                "epsg": int,
                "inserted_to_pgstac": bool,
                "stac_item": {...}  # Full STAC Item
            }
        }
    """
    # CRITICAL: Log entry BEFORE any imports to confirm handler is called
    import sys
    print(f"🚀 HANDLER ENTRY: extract_stac_metadata called with params keys: {list(params.keys())}", file=sys.stderr, flush=True)
    print(f"🚀 HANDLER ENTRY: blob_name={params.get('blob_name', 'MISSING')}", file=sys.stderr, flush=True)

    # STEP 0: Import dependencies with explicit error handling
    # These imports are logged separately to catch import failures that prevent handler execution
    logger = None  # Initialize to None for error handling
    try:
        print(f"📦 STEP 0A: Importing LoggerFactory and traceback...", file=sys.stderr, flush=True)
        from util_logger import LoggerFactory, ComponentType
        import traceback
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "extract_stac_metadata")
        logger.info("✅ STEP 0A: Logger initialized successfully")
        print(f"✅ STEP 0A: Logger initialized", file=sys.stderr, flush=True)

        print(f"📦 STEP 0B: Importing StacMetadataService (lazy import - may trigger stac-pydantic)...", file=sys.stderr, flush=True)
        logger.info("📦 STEP 0B: Starting lazy import of StacMetadataService...")
        from .service_stac_metadata import StacMetadataService
        logger.info("✅ STEP 0B: StacMetadataService imported successfully")
        print(f"✅ STEP 0B: StacMetadataService imported", file=sys.stderr, flush=True)

        print(f"📦 STEP 0C: Importing StacInfrastructure...", file=sys.stderr, flush=True)
        logger.info("📦 STEP 0C: Importing StacInfrastructure...")
        from infrastructure.pgstac_bootstrap import PgStacBootstrap
        logger.info("✅ STEP 0C: StacInfrastructure imported successfully")
        print(f"✅ STEP 0C: All imports successful!", file=sys.stderr, flush=True)

    except ImportError as e:
        error_msg = f"IMPORT FAILED: {e}"
        print(f"❌ {error_msg}", file=sys.stderr, flush=True)
        if logger:
            logger.error(f"❌ {error_msg}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": error_msg,
            "error_type": "ImportError",
            "import_failed": True,
            "failed_module": str(e),
            "blob_name": params.get("blob_name"),
            "container_name": params.get("container_name"),
            "traceback": traceback.format_exc() if 'traceback' in dir() else str(e)
        }
    except Exception as e:
        error_msg = f"UNEXPECTED ERROR DURING IMPORTS: {type(e).__name__}: {e}"
        print(f"❌ {error_msg}", file=sys.stderr, flush=True)
        if logger:
            logger.error(f"❌ {error_msg}\n{traceback.format_exc() if 'traceback' in dir() else ''}")
        return {
            "success": False,
            "error": error_msg,
            "error_type": type(e).__name__,
            "import_phase_error": True,
            "blob_name": params.get("blob_name"),
            "container_name": params.get("container_name")
        }

    # =========================================================================
    # GRACEFUL DEGRADATION CHECK (6 DEC 2025, updated for JSON fallback)
    # =========================================================================
    # Check pgSTAC availability ONCE at start. If unavailable:
    # - Continue with STAC extraction (metadata is still valuable)
    # - Write JSON fallback to blob storage
    # - Skip pgSTAC insert
    # COGs are always accessible via TiTiler URLs.
    pgstac_available = PgStacBootstrap.is_available()
    if not pgstac_available:
        logger.warning(f"⚠️ pgSTAC unavailable - will extract STAC metadata and write JSON fallback for {params.get('blob_name')}")

    try:
        # STEP 1: Extract parameters
        try:
            from config import get_config  # Import config for default collection
            config = get_config()

            container_name = params["container_name"]
            blob_name = params["blob_name"]

            # Use config default if collection_id not specified
            collection_id = params.get("collection_id") or config.stac_default_collection
            item_id = params.get("item_id")  # Optional custom item ID
            collection_must_exist = params.get("collection_must_exist", False)  # 12 JAN 2026: Fail if collection doesn't exist

            using_default = params.get("collection_id") is None
            logger.info(
                f"📋 STEP 1: Parameters extracted - container={container_name}, "
                f"blob={blob_name[:50]}..., collection={collection_id}"
                f"{' (default)' if using_default else ''}, custom_item_id={item_id}"
            )
        except Exception as e:
            logger.error(f"❌ STEP 1 FAILED: Parameter extraction error: {e}")
            raise

        start_time = datetime.utcnow()

        # STEP 2: Initialize STAC service
        try:
            logger.debug(f"🔧 STEP 2: Initializing StacMetadataService...")
            stac_service = StacMetadataService()
            logger.info(f"✅ STEP 2: StacMetadataService initialized")
        except Exception as e:
            logger.error(f"❌ STEP 2 FAILED: StacMetadataService initialization error: {e}\n{traceback.format_exc()}")
            raise

        # STEP 3: Extract STAC item from blob (THIS IS THE SLOW PART)
        try:
            logger.info(f"📡 STEP 3: Starting STAC extraction from blob (this may take 30-60s)...")
            extract_start = datetime.utcnow()

            # STEP 3A: Extract platform and provenance metadata for STAC enrichment
            # V0.9 P2.6: Uses Pydantic models from core.models.stac
            platform_meta = None
            provenance = None
            try:
                from core.models.stac import PlatformProperties, ProvenanceProperties
                # Build PlatformProperties (ddh:*) from job params
                ddh_fields = {
                    'dataset_id': params.get('dataset_id'),
                    'resource_id': params.get('resource_id'),
                    'version_id': params.get('version_id'),
                    'access_level': params.get('access_level'),
                }
                # Check nested platform_metadata dict too
                nested = params.get('platform_metadata', {})
                if nested:
                    ddh_fields = {k: nested.get(k) or v for k, v in ddh_fields.items()}
                if any(ddh_fields.values()):
                    platform_meta = PlatformProperties(**{k: v for k, v in ddh_fields.items() if v})

                # Build ProvenanceProperties (geoetl:*) for job traceability
                raster_type_info = params.get('raster_type')
                detected_type = raster_type_info.get('detected_type') if isinstance(raster_type_info, dict) else None
                provenance = ProvenanceProperties(
                    job_id=params.get('_job_id'),
                    raster_type=detected_type,
                )
                logger.debug(f"   Step 3A: Platform/Provenance metadata extracted - job_id={params.get('_job_id')}")
            except Exception as meta_err:
                logger.warning(f"   Step 3A: Metadata extraction failed (non-critical): {meta_err}")

            # V0.9 P2.6: Renders are built inside extract_item_from_blob, no raster_meta needed
            item = stac_service.extract_item_from_blob(
                container=container_name,
                blob_name=blob_name,
                collection_id=collection_id,
                item_id=item_id,
                platform_meta=platform_meta,
                provenance_props=provenance,
                file_checksum=params.get('file_checksum'),
                file_size=params.get('file_size'),
            )

            extract_duration = (datetime.utcnow() - extract_start).total_seconds()
            item_id_str = item.get('id', 'unknown') if isinstance(item, dict) else item.id
            logger.info(f"✅ STEP 3: STAC extraction completed in {extract_duration:.2f}s - item_id={item_id_str}")
        except Exception as e:
            extract_duration = (datetime.utcnow() - extract_start).total_seconds() if 'extract_start' in locals() else 0
            logger.error(f"❌ STEP 3 FAILED after {extract_duration:.2f}s: STAC extraction error: {e}\n{traceback.format_exc()}")
            raise

        # =====================================================================
        # STEP 3.5: Write JSON STAC fallback to blob storage (6 DEC 2025)
        # =====================================================================
        # ALWAYS write JSON alongside COG - provides:
        # - Audit trail for every COG
        # - Fallback when pgSTAC unavailable
        # - External system integration
        # - Recovery path (bulk-insert JSONs later)
        json_blob_name = None
        json_blob_url = None
        try:
            import json as json_module

            # Convert item to JSON-serializable dict
            # V0.9 P2.5: extract_item_from_blob now returns plain dict
            if isinstance(item, dict):
                item_dict_for_json = item
            elif hasattr(item, 'model_dump'):
                item_dict_for_json = item.model_dump(mode='json', by_alias=True)
            else:
                item_dict_for_json = item

            # Generate JSON blob name (same as COG but .json extension)
            # dctest_cog_analysis.tif → dctest_cog_analysis.json
            json_blob_name = blob_name.rsplit('.', 1)[0] + '.json'
            json_content = json_module.dumps(item_dict_for_json, indent=2, default=str)

            # Get storage account name for URL (silver tier is where COGs are stored)
            storage_account = config.storage.silver.account_name

            # Write JSON to blob storage (silver tier is where COGs and their JSON live)
            blob_repo = BlobRepository.for_zone("silver")
            blob_repo.write_blob(
                container=container_name,
                blob_path=json_blob_name,
                data=json_content.encode('utf-8'),
                content_type='application/json',
                overwrite=True
            )

            json_blob_url = f"https://{storage_account}.blob.core.windows.net/{container_name}/{json_blob_name}"
            logger.info(f"✅ STEP 3.5: STAC JSON written: {container_name}/{json_blob_name}")

        except Exception as e:
            # JSON write failure IS a real error - don't swallow it
            logger.error(f"❌ STEP 3.5 FAILED: Failed to write JSON fallback: {e}\n{traceback.format_exc()}")
            raise

        # =====================================================================
        # STEPS 4, 4.5, 5: DEFERRED TO APPROVAL (19 FEB 2026)
        # =====================================================================
        # STAC as B2C materialized view: pgSTAC inserts happen at approval time.
        # Cache the STAC item dict in cog_metadata.stac_item_json instead.
        insert_result = None
        insert_duration = 0
        inserted_to_pgstac = False

        try:
            from infrastructure.raster_metadata_repository import get_raster_metadata_repository
            cog_repo = get_raster_metadata_repository()

            # item may be a pydantic model or dict
            if isinstance(item, dict):
                item_dict_for_cache = item
            elif hasattr(item, 'model_dump'):
                item_dict_for_cache = item.model_dump(mode='json', by_alias=True)
            else:
                item_dict_for_cache = item

            cache_item_id = item.id if hasattr(item, 'id') else item_dict_for_cache.get('id', item_id)
            cached = cog_repo.update_stac_item_json(
                cog_id=cache_item_id,
                stac_item_json=item_dict_for_cache
            )
            if cached:
                logger.info(f"✅ STEPS 4-5: STAC item cached in cog_metadata for {cache_item_id} (pgSTAC deferred to approval)")
            else:
                logger.warning(f"⚠️ STEPS 4-5: Could not cache STAC item in cog_metadata for {cache_item_id} (record may not exist)")

            insert_result = {
                'success': True,
                'cached': True,
                'reason': 'STAC item cached — pgSTAC deferred to approval'
            }
        except Exception as cache_err:
            logger.warning(f"⚠️ STEPS 4-5: STAC caching failed (non-fatal): {cache_err}")
            insert_result = {
                'success': True,
                'cached': False,
                'reason': f'STAC caching failed: {cache_err}'
            }

        # V0.9: Also cache STAC item dict on Release entity (21 FEB 2026)
        # This allows AssetApprovalServiceV2._materialize_stac() to read from Release
        release_id = params.get('release_id')
        if release_id:
            try:
                # Derive release_item_dict independently (item_dict_for_cache may not
                # be set if the cog_metadata caching block above raised an exception)
                if isinstance(item, dict):
                    release_item_dict = item
                elif hasattr(item, 'model_dump'):
                    release_item_dict = item.model_dump(mode='json', by_alias=True)
                else:
                    release_item_dict = item

                from infrastructure import ReleaseRepository
                release_repo = ReleaseRepository()
                release_repo.update_stac_item_json(release_id, release_item_dict)
                logger.info(f"STAC item cached on Release {release_id[:16]}...")
            except Exception as release_cache_err:
                logger.warning(f"Failed to cache STAC on Release (non-fatal): {release_cache_err}")

        duration = (datetime.utcnow() - start_time).total_seconds()

        # STEP 6: Extract metadata for summary
        try:
            logger.debug(f"📊 STEP 6: Extracting metadata summary...")
            item_dict = item.model_dump(mode='json', by_alias=True)
            bbox = item.bbox
            # FIX: item.geometry is Shapely object, not dict - use item_dict instead
            geometry_type = item_dict.get('geometry', {}).get('type', 'Unknown') if item_dict.get('geometry') else 'Unknown'

            # Count raster bands if present
            bands_count = 0
            if 'assets' in item_dict:
                for asset in item_dict['assets'].values():
                    if 'raster:bands' in asset:
                        bands_count = len(asset['raster:bands'])
                        break

            # Get EPSG code
            epsg = item_dict.get('properties', {}).get('proj:epsg')

            logger.info(f"✅ STEP 6: Metadata extracted - bbox={bbox}, epsg={epsg}, bands={bands_count}")
        except Exception as e:
            logger.error(f"❌ STEP 6 FAILED: Metadata extraction error: {e}\n{traceback.format_exc()}")
            raise

        # 19 FEB 2026: pgSTAC insertion deferred to approval — no failure check needed here

        # STEP 7: Upsert DDH refs to app.dataset_refs (09 JAN 2026 - F7.8)
        # This links internal dataset_id (COG blob path) to external DDH identifiers
        try:
            from infrastructure.dataset_refs_repository import get_dataset_refs_repository
            refs_repo = get_dataset_refs_repository()
            # Use blob_name as the internal dataset_id for rasters
            refs_repo.upsert_ref(
                dataset_id=blob_name,
                data_type="raster",
                ddh_dataset_id=params.get("dataset_id"),
                ddh_resource_id=params.get("resource_id"),
                ddh_version_id=params.get("version_id")
            )
            logger.debug(f"✅ STEP 7: Upserted app.dataset_refs for {blob_name}")
        except Exception as refs_error:
            # Non-fatal - STAC item was created
            logger.warning(f"⚠️ STEP 7: Failed to upsert dataset_refs: {refs_error}")

        # STEP 7.5: REMOVED (12 FEB 2026)
        # cog_metadata population moved to handler Phase 3a (source of truth).
        # When called from handler_process_raster_complete, cog_metadata is already
        # persisted BEFORE STAC. For backward-compatible callers that don't
        # pre-persist, cog_metadata will be empty but STAC still works.

        # SUCCESS - STAC metadata extracted (and inserted to pgstac if available)
        mode_msg = "degraded mode (JSON only)" if not pgstac_available else "full mode"
        logger.info(f"🎉 SUCCESS: STAC cataloging completed in {duration:.2f}s for {blob_name} [{mode_msg}]")

        # Build typed result using Pydantic models (F7.21)
        stac_data = STACCreationData(
            item_id=item.id,
            blob_name=blob_name,
            collection_id=collection_id,
            bbox=bbox,
            geometry_type=geometry_type,
            bands_count=bands_count,
            epsg=epsg,
            # JSON fallback (always written)
            stac_item_json_blob=json_blob_name,
            stac_item_json_url=json_blob_url,
            # pgSTAC status
            inserted_to_pgstac=inserted_to_pgstac,
            pgstac_available=pgstac_available,
            item_skipped=insert_skipped,
            skip_reason=insert_result.get('reason') if insert_result and insert_skipped else None,
            # Timing
            execution_time_seconds=round(duration, 2),
            extract_time_seconds=round(extract_duration, 2),
            insert_time_seconds=round(insert_duration, 2),
            # Full item for reference
            stac_item=item_dict
        )

        result = STACCreationResult(
            success=True,
            degraded=not pgstac_available,
            warning="pgSTAC unavailable - JSON fallback is authoritative" if not pgstac_available else None,
            result=stac_data
        )
        return result.model_dump()

    except Exception as e:
        # FAILURE - return error with context using typed result (F7.21)
        duration = (datetime.utcnow() - start_time).total_seconds() if 'start_time' in locals() else 0
        error_msg = str(e) or type(e).__name__
        logger.error(f"💥 COMPLETE FAILURE after {duration:.2f}s: {error_msg}\n{traceback.format_exc()}")

        error_result = STACCreationResult(
            success=False,
            error=error_msg,
            error_type=type(e).__name__,
            message=f"STAC creation failed for {params.get('blob_name')}",
            traceback=traceback.format_exc()
        )
        return error_result.model_dump()
