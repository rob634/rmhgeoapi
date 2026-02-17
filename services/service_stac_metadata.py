# ============================================================================
# STAC METADATA EXTRACTION SERVICE
# ============================================================================
# STATUS: Service layer - STAC metadata extraction from raster files
# PURPOSE: Extract and validate STAC Item metadata using rio-stac library
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: StacMetadataService
# DEPENDENCIES: rio-stac, stac-pydantic, rasterio
# ============================================================================
"""
STAC Metadata Extraction Service.

Extracts STAC Item metadata from raster files using rio-stac library.
Validates with stac-pydantic for type safety and STAC spec compliance.

Uses:
    - rio-stac: Geometry, bbox, projection, raster metadata extraction
    - stac-pydantic: Validation and type safety

Exports:
    StacMetadataService: Main service class for STAC metadata extraction
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone
import logging

# STAC validation models - lightweight, safe to import at module level
from stac_pydantic import Item
from stac_pydantic.shared import Asset

# LAZY LOADING: Heavy GDAL dependencies
# These imports are logged explicitly to track cold start timing
import traceback as _traceback
from util_logger import LoggerFactory, ComponentType

# Temporary logger for import diagnostics (before main logger is created)
_import_logger = LoggerFactory.create_logger(
    ComponentType.SERVICE,
    "stac_metadata_import"
)

try:
    _import_logger.info("🔄 SERVICE MODULE: Loading rio-stac (depends on rasterio/GDAL)...")
    from rio_stac import stac as rio_stac
    _import_logger.info("✅ SERVICE MODULE: rio-stac loaded successfully")
except ImportError as e:
    _import_logger.error(f"❌ SERVICE MODULE IMPORT FAILED: rio-stac ImportError")
    _import_logger.error(f"   Error: {e}")
    _import_logger.error(f"   Traceback:\n{_traceback.format_exc()}")
    raise
except Exception as e:
    _import_logger.error(f"❌ SERVICE MODULE IMPORT FAILED: rio-stac unexpected error")
    _import_logger.error(f"   Error: {e}")
    _import_logger.error(f"   Traceback:\n{_traceback.format_exc()}")
    raise

try:
    _import_logger.info("🔄 SERVICE MODULE: Loading rasterio (GDAL C++ library)...")
    import rasterio
    _import_logger.info("✅ SERVICE MODULE: rasterio loaded successfully")
except ImportError as e:
    _import_logger.error(f"❌ SERVICE MODULE IMPORT FAILED: rasterio ImportError")
    _import_logger.error(f"   Error: {e}")
    _import_logger.error(f"   Traceback:\n{_traceback.format_exc()}")
    raise
except Exception as e:
    _import_logger.error(f"❌ SERVICE MODULE IMPORT FAILED: rasterio unexpected error")
    _import_logger.error(f"   Error: {e}")
    _import_logger.error(f"   Traceback:\n{_traceback.format_exc()}")
    raise

from infrastructure.blob import BlobRepository
from infrastructure.pgstac_repository import PgStacRepository
from config.defaults import STACDefaults

# Component-specific logger for structured logging (Application Insights)
logger = LoggerFactory.create_logger(
    ComponentType.SERVICE,
    "stac_metadata_service"
)


class StacMetadataService:
    """
    Extract and validate STAC metadata from raster files.

    Uses rio-stac for spatial metadata extraction and stac-pydantic for validation.
    Supplements with Azure blob metadata and custom properties.
    """

    def __init__(self):
        """Initialize STAC metadata service."""
        # Silver zone - STAC items reference processed data
        self.blob_repo = BlobRepository.for_zone("silver")
        self.stac = PgStacRepository()  # 18 NOV 2025: Use PgStacRepository for data operations

    def extract_item_from_blob(
        self,
        container: str,
        blob_name: str,
        collection_id: str = STACDefaults.DEV_COLLECTION,
        existing_metadata: Optional[Dict[str, Any]] = None,
        item_id: Optional[str] = None,
        platform_meta: Optional['PlatformProperties'] = None,
        app_meta: Optional['ProvenanceProperties'] = None,
        raster_meta=None,  # DEPRECATED V0.9: raster_type now read from app_meta.raster_type
        file_checksum: Optional[str] = None,  # STAC file extension (21 JAN 2026)
        file_size: Optional[int] = None,  # STAC file extension (21 JAN 2026)
        skip_stats: bool = False,  # V0.9 P2.2: Override to skip statistics extraction
    ) -> Dict[str, Any]:
        """
        Extract STAC Item from raster blob using rio-stac.

        Args:
            container: Azure container name
            blob_name: Blob path within container
            collection_id: STAC collection ID (default: 'dev')
            existing_metadata: Optional metadata from analyze_single_blob()
            item_id: Optional custom STAC item ID (auto-generated if not provided)
            platform_meta: Optional PlatformProperties for DDH identifiers (V0.9: ddh:*)
            app_meta: Optional ProvenanceProperties for job linkage (V0.9: geoetl:*)
            raster_meta: DEPRECATED V0.9 — raster_type now read from app_meta.raster_type

        Returns:
            Validated stac-pydantic Item

        Raises:
            ValidationError: If extracted metadata fails STAC validation
            rasterio.errors.RasterioIOError: If blob cannot be read as raster

        Strategy:
            1. Generate SAS URL for rasterio access
            2. Let rio-stac extract geometry, bbox, projection, raster metadata
            3. Supplement with Azure blob metadata
            4. Add platform/app metadata via STACMetadataHelper (25 NOV 2025)
            5. Validate with stac-pydantic
        """
        import traceback

        logger.info(f"🔄 EXTRACTION START: {container}/{blob_name}")

        # STEP A: Generate SAS URL for rasterio access
        try:
            logger.debug("   Step A: Generating SAS URL for blob access...")
            blob_url = self.blob_repo.get_blob_url_with_sas(
                container_name=container,
                blob_name=blob_name,
                hours=1
            )
            logger.debug(f"   ✅ Step A: SAS URL generated - {blob_url[:100]}...")
        except Exception as e:
            logger.error(f"❌ Step A FAILED: Error generating SAS URL")
            logger.error(f"   Container: {container}, Blob: {blob_name}")
            logger.error(f"   Error: {e}")
            logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise ValueError(f"Failed to generate SAS URL for {container}/{blob_name}: {e}")

        # STEP B: Determine datetime
        try:
            logger.debug("   Step B: Determining item datetime...")
            if existing_metadata and existing_metadata.get('last_modified'):
                item_datetime = datetime.fromisoformat(existing_metadata['last_modified'])
                logger.debug(f"   ✅ Step B: Using existing metadata datetime: {item_datetime}")
            else:
                item_datetime = datetime.now(timezone.utc)
                logger.debug(f"   ✅ Step B: Using current datetime: {item_datetime}")
        except Exception as e:
            logger.error(f"❌ Step B FAILED: Error determining datetime")
            logger.error(f"   Error: {e}")
            logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise ValueError(f"Failed to determine datetime: {e}")

        # STEP C: Determine item ID (use custom if provided, otherwise auto-generate)
        try:
            if item_id:
                logger.debug(f"   Step C: Using custom item ID: {item_id}")
            else:
                logger.debug("   Step C: Auto-generating semantic item ID...")
                item_id = self._generate_item_id(container, blob_name, collection_id)
                logger.debug(f"   ✅ Step C: Item ID generated: {item_id}")
        except Exception as e:
            logger.error(f"❌ Step C FAILED: Error determining item ID")
            logger.error(f"   Error: {e}")
            logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise ValueError(f"Failed to determine item ID: {e}")

        # STEP D: Determine file size and statistics extraction strategy
        # V0.9 P2.2: Always extract statistics (reading from mounted filestore).
        # skip_stats parameter allows override for edge cases.
        try:
            logger.debug("   Step D: Determining file size and extraction strategy...")
            file_size_mb = 0
            if existing_metadata and existing_metadata.get('size_mb'):
                file_size_mb = existing_metadata['size_mb']
                logger.debug(f"   → Using cached size: {file_size_mb:.1f} MB")
            else:
                logger.debug(f"   → Fetching blob properties to get size...")
                blob_properties = self.blob_repo.get_blob_properties(container, blob_name)
                file_size_mb = blob_properties.get('size', 0) / (1024.0 * 1024.0)
                logger.debug(f"   → Retrieved size: {file_size_mb:.1f} MB")

            extract_statistics = not skip_stats

            if skip_stats:
                logger.info(
                    f"   ⚠️  skip_stats=True for {blob_name} ({file_size_mb:.1f} MB) - "
                    f"skipping raster statistics extraction."
                )
            else:
                logger.debug(f"   → Statistics will be extracted ({file_size_mb:.1f} MB)")
            logger.debug(f"   ✅ Step D: Strategy determined - extract_statistics={extract_statistics}")
        except Exception as e:
            logger.error(f"❌ Step D FAILED: Error determining file size")
            logger.error(f"   Error: {e}")
            logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise ValueError(f"Failed to determine file size: {e}")

        # STEP E: Open raster file with rasterio
        logger.info(f"🔄 RASTERIO OPERATION: Opening {blob_name} ({file_size_mb:.1f} MB)")
        try:
            logger.debug(f"   Step E: Calling rasterio.open()...")
            logger.debug(f"   Blob URL: {blob_url[:100]}...")

            with rasterio.open(blob_url) as dataset:
                logger.info(f"   ✅ Step E: File opened - CRS: {dataset.crs}, Shape: {dataset.shape}, Bands: {dataset.count}")

                # STEP F: Extract STAC metadata with rio-stac
                try:
                    logger.info("   🔄 Step F: Calling rio_stac.create_stac_item()...")
                    logger.debug(f"      Parameters: id={item_id}, collection={collection_id}")
                    logger.debug(f"      Extensions: with_proj=True, with_raster={extract_statistics}, with_eo=False")

                    rio_item = rio_stac.create_stac_item(
                        dataset,
                        id=item_id,
                        collection=collection_id,
                        input_datetime=item_datetime,
                        asset_name="data",
                        asset_roles=["data"],
                        asset_media_type=STACDefaults.MEDIA_TYPE_GEOTIFF,
                        with_proj=True,
                        with_raster=extract_statistics,
                        with_eo=False
                    )
                    logger.info(f"   ✅ Step F: create_stac_item() completed successfully")

                except Exception as e:
                    logger.error(f"   ❌ Step F FAILED: rio_stac.create_stac_item() error")
                    logger.error(f"      Error: {e}")
                    logger.error(f"      Error type: {type(e).__name__}")
                    logger.error(f"      Traceback:\n{traceback.format_exc()}")
                    raise RuntimeError(f"rio-stac extraction failed: {e}")

        except Exception as e:
            # This catches both rasterio.open() failures and rio_stac failures
            error_type = type(e).__name__
            logger.error(f"❌ RASTERIO/RIO-STAC OPERATION FAILED")
            logger.error(f"   Operation: Opening raster or extracting metadata")
            logger.error(f"   Blob: {container}/{blob_name}")
            logger.error(f"   Error type: {error_type}")
            logger.error(f"   Error: {e}")
            logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise RuntimeError(f"Failed to process raster file: {e}")

        logger.info(f"✅ RASTERIO/RIO-STAC COMPLETE: Metadata extracted for {item_id}")

        # STEP G: Convert pystac.Item to dict
        try:
            logger.debug("   Step G: Converting rio_stac result to dict...")
            if hasattr(rio_item, 'to_dict'):
                item_dict = rio_item.to_dict()
            else:
                item_dict = rio_item
            logger.debug(f"   ✅ Step G: Converted - {len(item_dict)} top-level keys")
        except Exception as e:
            logger.error(f"❌ Step G FAILED: Error converting rio_item to dict")
            logger.error(f"   Error: {e}")
            logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise ValueError(f"Failed to convert STAC item to dict: {e}")

        # STEP G.0a: Validate bbox values (01 JAN 2026, enhanced 26 JAN 2026)
        # rio_stac returns bbox with None values when CRS can't be transformed to WGS84
        # or when geotransform is missing/invalid. Fail early with clear error.
        # Also validate that bbox is in valid WGS84 range - projected coordinates
        # (like UTM meters) indicate transformation failed.
        try:
            bbox = item_dict.get('bbox', [])
            if bbox and any(v is None for v in bbox):
                logger.error(f"❌ Step G.0a FAILED: rio_stac returned bbox with None values")
                logger.error(f"   Blob: {container}/{blob_name}")
                logger.error(f"   bbox: {bbox}")
                logger.error(f"   This usually means:")
                logger.error(f"   - The raster has no valid geotransform")
                logger.error(f"   - The CRS cannot be transformed to WGS84")
                logger.error(f"   - The raster bounds are invalid")
                raise ValueError(
                    f"Cannot create STAC Item: raster '{blob_name}' has invalid bounds (bbox={bbox}). "
                    f"Verify the source file has a valid CRS and geotransform. "
                    f"You may need to reprocess with explicit source_crs parameter."
                )

            # Validate bbox is in WGS84 range (26 JAN 2026)
            # Valid WGS84: lon [-180, 180], lat [-90, 90]
            # bbox format: [minx/lon, miny/lat, maxx/lon, maxy/lat]
            if bbox and len(bbox) >= 4:
                minx, miny, maxx, maxy = bbox[:4]
                is_projected = (
                    abs(minx) > 180 or abs(maxx) > 180 or
                    abs(miny) > 90 or abs(maxy) > 90
                )
                if is_projected:
                    logger.error(f"❌ Step G.0a FAILED: bbox appears to be in projected coordinates, not WGS84")
                    logger.error(f"   Blob: {container}/{blob_name}")
                    logger.error(f"   bbox: {bbox}")
                    logger.error(f"   Expected range: lon [-180, 180], lat [-90, 90]")
                    logger.error(f"   This usually means rio-stac failed to transform the CRS to WGS84")
                    raise ValueError(
                        f"Cannot create STAC Item: bbox {bbox} appears to be in projected coordinates "
                        f"(values outside WGS84 range). The raster CRS may not be properly defined. "
                        f"Expected: lon [-180, 180], lat [-90, 90]. "
                        f"Check that the source raster has a valid CRS definition."
                    )

            logger.debug(f"   ✅ Step G.0a: bbox validated: {bbox}")
        except ValueError:
            raise  # Re-raise our own ValueError
        except Exception as e:
            logger.warning(f"   ⚠️  Step G.0a: bbox validation check failed (non-fatal): {e}")

        # STEP G.1: Add required STAC fields for pgSTAC search compatibility (12 NOV 2025)
        try:
            logger.debug("   Step G.1: Adding required STAC fields for pgSTAC compatibility...")

            # 1. Ensure 'type' field = "Feature" (GeoJSON requirement)
            if item_dict.get('type') != 'Feature':
                item_dict['type'] = 'Feature'
                logger.debug("      Set type='Feature' (GeoJSON requirement)")

            # 2. Ensure 'id' field exists (should be set by rio-stac, but verify)
            if not item_dict.get('id'):
                # Fallback: use generate_stac_item_id if rio-stac didn't set it
                fallback_id = self.generate_stac_item_id(blob_name)
                item_dict['id'] = fallback_id
                logger.warning(f"      rio-stac didn't set id - using generated: {fallback_id}")
            else:
                logger.debug(f"      id={item_dict['id']} (set by rio-stac)")

            # 3. Ensure 'collection' field exists
            if not item_dict.get('collection'):
                item_dict['collection'] = collection_id
                logger.debug(f"      Set collection='{collection_id}'")
            else:
                # Verify collection matches parameter
                if item_dict['collection'] != collection_id:
                    logger.warning(
                        f"      Collection mismatch: item has '{item_dict['collection']}' "
                        f"but parameter is '{collection_id}' - using parameter"
                    )
                    item_dict['collection'] = collection_id

            # 4. Ensure 'stac_version' exists
            if not item_dict.get('stac_version'):
                item_dict['stac_version'] = '1.1.0'
                logger.debug("      Set stac_version='1.1.0'")

            # 5. CRITICAL: Ensure 'geometry' field exists (required for pgSTAC searches)
            if not item_dict.get('geometry'):
                logger.warning("      ⚠️  geometry field missing - deriving from bbox")
                bbox = item_dict.get('bbox')
                if bbox:
                    item_dict['geometry'] = self.bbox_to_geometry(bbox)
                    logger.debug(f"      ✅ Derived geometry from bbox: {bbox}")
                else:
                    # Critical error: no geometry and no bbox
                    raise ValueError(
                        "STAC item missing both 'geometry' and 'bbox' - cannot create valid item"
                    )
            else:
                logger.debug(f"      geometry exists: {item_dict['geometry']['type']}")

            logger.debug(f"   ✅ Step G.1: Required STAC fields validated/added")
        except Exception as e:
            logger.error(f"❌ Step G.1 FAILED: Error adding required STAC fields")
            logger.error(f"   Error: {e}")
            logger.error(f"   Traceback:\n{traceback.format_exc()}")
            # CRITICAL (12 NOV 2025): Items without proper fields break pgSTAC searches
            # Fail fast - these fields are mandatory for pgSTAC compatibility
            raise RuntimeError(f"Failed to add required STAC fields: {e}")

        # =====================================================================
        # V0.9 P2.5: Build STAC item via RasterMetadata.to_stac_item()
        # Replaces old Steps G.1b, G.2, G.5, H, I with canonical builder.
        # =====================================================================

        # STEP N.1: Extract band statistics and raster type from rio-stac output
        try:
            logger.debug("   Step N.1: Extracting band stats and raster type...")
            data_asset = item_dict.get('assets', {}).get('data', {})
            raster_bands = data_asset.get('raster:bands', [])

            # Detect raster type from band count + dtype
            rio_props = item_dict.get('properties', {})
            band_count = len(raster_bands) if raster_bands else 1
            dtype = raster_bands[0].get('data_type', 'float32') if raster_bands else 'float32'

            # Use raster_meta.detected_type if provided, else auto-detect
            detected_type = 'unknown'
            if raster_meta and hasattr(raster_meta, 'detected_type') and raster_meta.detected_type:
                detected_type = raster_meta.detected_type
            elif app_meta and hasattr(app_meta, 'raster_type') and app_meta.raster_type:
                detected_type = app_meta.raster_type

            # Convert rio-stac raster:bands to band_stats format for renders builder
            band_stats = []
            for i, rb in enumerate(raster_bands):
                stats = rb.get('statistics', {})
                if stats:
                    band_stats.append({
                        'band': i + 1,
                        'statistics': {
                            'minimum': stats.get('minimum', 0),
                            'maximum': stats.get('maximum', 0),
                        }
                    })

            logger.debug(f"   ✅ Step N.1: {band_count} bands, dtype={dtype}, "
                         f"type={detected_type}, stats={len(band_stats)} bands")
        except Exception as e:
            logger.warning(f"   ⚠️  Step N.1: Band stats extraction failed (non-fatal): {e}")
            band_stats = []
            band_count = 1
            dtype = 'float32'
            detected_type = 'unknown'

        # STEP N.2: Build renders via renders builder (P2.1)
        renders = None
        try:
            logger.debug("   Step N.2: Building STAC renders...")
            from services.stac_renders import build_renders

            renders = build_renders(
                raster_type=detected_type,
                band_count=band_count,
                dtype=dtype,
                band_stats=band_stats if band_stats else None,
            )
            if renders:
                logger.info(f"   ✅ Step N.2: Renders built - {list(renders.keys())}")
            else:
                logger.debug("   ⚠️  Step N.2: No renders built (insufficient data)")
        except Exception as e:
            logger.warning(f"   ⚠️  Step N.2: Renders build failed (non-fatal): {e}")

        # STEP N.3: Build RasterMetadata from rio-stac extraction
        try:
            logger.debug("   Step N.3: Building RasterMetadata from extracted data...")
            from core.models.unified_metadata import RasterMetadata, SpatialExtent, Extent

            bbox = item_dict.get('bbox')
            spatial = None
            if bbox and len(bbox) >= 4:
                spatial = SpatialExtent.from_flat_bbox(bbox[0], bbox[1], bbox[2], bbox[3])

            extent = Extent(spatial=spatial) if spatial else None

            # Extract proj:epsg from rio-stac properties
            proj_epsg = rio_props.get('proj:epsg')
            crs = f"EPSG:{proj_epsg}" if proj_epsg else 'EPSG:4326'

            # Extract transform from rio-stac properties
            transform = rio_props.get('proj:transform')

            raster_metadata = RasterMetadata(
                id=item_dict.get('id', item_id),
                title=rio_props.get('title') or item_id,
                cog_url=f"/vsiaz/{container}/{blob_name}",
                container=container,
                blob_path=blob_name,
                width=rio_props.get('proj:shape', [0, 0])[1] if rio_props.get('proj:shape') else 0,
                height=rio_props.get('proj:shape', [0, 0])[0] if rio_props.get('proj:shape') else 0,
                band_count=band_count,
                dtype=dtype,
                nodata=raster_bands[0].get('nodata') if raster_bands else None,
                crs=crs,
                transform=transform,
                extent=extent,
                stac_item_id=item_dict.get('id', item_id),
                stac_collection_id=collection_id,
                etl_job_id=app_meta.job_id if app_meta and hasattr(app_meta, 'job_id') else None,
                source_file=blob_name,
                raster_bands=raster_bands if raster_bands else None,
            )
            logger.debug(f"   ✅ Step N.3: RasterMetadata built - {raster_metadata.id}")
        except Exception as e:
            logger.error(f"❌ Step N.3 FAILED: Error building RasterMetadata: {e}")
            logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise RuntimeError(f"Failed to build RasterMetadata: {e}")

        # STEP N.4: Build namespace properties
        try:
            logger.debug("   Step N.4: Building namespace properties...")
            from core.models.stac import ProvenanceProperties, PlatformProperties, GeoProperties

            # geoetl:* provenance
            provenance_props = ProvenanceProperties(
                job_id=app_meta.job_id if app_meta and hasattr(app_meta, 'job_id') else None,
                raster_type=detected_type if detected_type != 'unknown' else None,
                statistics_extracted=extract_statistics,
            )

            # ddh:* platform passthrough
            platform_props = None
            if platform_meta:
                platform_props = PlatformProperties(
                    dataset_id=getattr(platform_meta, 'dataset_id', None),
                    resource_id=getattr(platform_meta, 'resource_id', None),
                    version_id=getattr(platform_meta, 'version_id', None),
                    access_level=getattr(platform_meta, 'access_level', None),
                )

            # geo:* attribution (from ISO3 service)
            geo_props = None
            try:
                from services.iso3_attribution import ISO3AttributionService
                iso3_service = ISO3AttributionService()
                if bbox and len(bbox) >= 4:
                    attribution = iso3_service.get_attribution_for_bbox(bbox)
                    if attribution and attribution.available:
                        geo_props = GeoProperties(
                            iso3=attribution.iso3_codes or [],
                            primary_iso3=attribution.primary_iso3,
                            countries=attribution.countries or [],
                        )
            except Exception as geo_err:
                logger.warning(f"   ⚠️  ISO3 attribution failed (non-fatal): {geo_err}")

            logger.debug(f"   ✅ Step N.4: Namespace props built")
        except Exception as e:
            logger.warning(f"   ⚠️  Step N.4: Namespace props failed (non-fatal): {e}")
            provenance_props = ProvenanceProperties(statistics_extracted=extract_statistics)
            platform_props = None
            geo_props = None

        # STEP N.5: Build final STAC item via canonical builder
        try:
            logger.debug("   Step N.5: Calling RasterMetadata.to_stac_item()...")
            from config import get_config
            config = get_config()
            base_url = getattr(config.platform, 'etl_app_base_url', '') or ''
            titiler_url = getattr(config.platform, 'titiler_base_url', None)

            final_item = raster_metadata.to_stac_item(
                base_url=base_url,
                provenance_props=provenance_props,
                platform_props=platform_props,
                geo_props=geo_props,
                titiler_base_url=titiler_url,
                renders=renders,
            )
            logger.debug(f"   ✅ Step N.5: STAC item built via to_stac_item()")
        except Exception as e:
            logger.error(f"❌ Step N.5 FAILED: to_stac_item() error: {e}")
            logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise RuntimeError(f"Failed to build STAC item: {e}")

        logger.info(f"✅ STAC ITEM EXTRACTION COMPLETE: {final_item.get('id', 'unknown')}")
        return final_item

    def generate_stac_item_id(self, blob_name: str) -> str:
        """
        Generate STAC-compliant item ID from blob path.

        CRITICAL (12 NOV 2025): Required for pgSTAC search compatibility.
        Items MUST have unique IDs for pgSTAC queries to work correctly.

        Strategy:
            - Use filename stem (without extension) as base
            - Prepend parent directory path (replace / with -)
            - Result is unique and human-readable

        Args:
            blob_name: Blob path (e.g., "folder/subfolder/file.tif")

        Returns:
            STAC item ID (e.g., "folder-subfolder-file")

        Examples:
            "file.tif" → "file"
            "folder/file.tif" → "folder-file"
            "a/b/c/file.tif" → "a-b-c-file"
            "namangan/R1C1.tif" → "namangan-R1C1"
        """
        from pathlib import Path

        # Remove extension
        stem = Path(blob_name).stem

        # Get parent path
        parent = str(Path(blob_name).parent)

        # Build ID
        if parent and parent != ".":
            # Has subdirectory: folder/file.tif → folder-file
            item_id = f"{parent}-{stem}".replace("/", "-").replace("\\", "-")
        else:
            # No subdirectory: file.tif → file
            item_id = stem

        logger.debug(f"   Generated STAC item ID: '{blob_name}' → '{item_id}'")
        return item_id

    def bbox_to_geometry(self, bbox: list) -> dict:
        """
        Convert bbox [minx, miny, maxx, maxy] to GeoJSON Polygon geometry.

        CRITICAL (12 NOV 2025): Required for pgSTAC search compatibility.
        pgSTAC searches query the geometry field. If missing, searches return
        world extent bounds [-180, -85, 180, 85] instead of actual collection extent.

        Args:
            bbox: Bounding box [minx, miny, maxx, maxy] in EPSG:4326

        Returns:
            GeoJSON Polygon geometry dict

        Example:
            bbox_to_geometry([-70.7, -56.3, -70.6, -56.2])
            → {
                "type": "Polygon",
                "coordinates": [[
                    [-70.7, -56.3],
                    [-70.6, -56.3],
                    [-70.6, -56.2],
                    [-70.7, -56.2],
                    [-70.7, -56.3]
                ]]
            }
        """
        if not bbox or len(bbox) != 4:
            raise ValueError(f"Invalid bbox: expected [minx, miny, maxx, maxy], got {bbox}")

        minx, miny, maxx, maxy = bbox
        geometry = {
            "type": "Polygon",
            "coordinates": [[
                [minx, miny],
                [maxx, miny],
                [maxx, maxy],
                [minx, maxy],
                [minx, miny]  # Close the ring
            ]]
        }

        logger.debug(f"   Converted bbox {bbox} to GeoJSON Polygon")
        return geometry

    def _generate_item_id(self, container: str, blob_name: str, collection_id: str = None) -> str:
        """
        Generate semantic STAC Item ID.

        Args:
            container: Container name
            blob_name: Blob path
            collection_id: STAC collection ID (if provided, use as prefix instead of tier)

        Returns:
            Unique item ID

        Example:
            _generate_item_id('bronze', 'path/to/file.tif', 'cogs')
            → 'cogs-path-to-file-tif'
        """
        # FIX: Use collection_id as prefix if provided, otherwise fallback to tier
        prefix = collection_id if collection_id else self._determine_tier(container)
        safe_name = blob_name.replace('/', '-').replace('.', '-')
        return f"{prefix}-{safe_name}"

    def _determine_tier(self, container: str) -> str:
        """
        Determine tier from container name.

        Args:
            container: Azure Storage container name

        Returns:
            Tier string ('bronze', 'silver', 'gold', or 'dev')
        """
        container_lower = container.lower()
        if 'bronze' in container_lower:
            return 'dev'  # Bronze is dev/test only
        elif 'silver' in container_lower:
            return 'silver'
        elif 'gold' in container_lower:
            return 'gold'
        return 'dev'

    # _get_countries_for_bbox() REMOVED (25 NOV 2025)
    # ISO3 country attribution now handled by services/iso3_attribution.py
    # Use: from services.iso3_attribution import ISO3AttributionService
    # This eliminates ~190 lines of duplicated code across service files

    def create_cog_asset(
        self,
        blob_url: str,
        title: Optional[str] = None,
        roles: Optional[list] = None
    ) -> Asset:
        """
        Create a validated STAC Asset for a Cloud Optimized GeoTIFF.

        Args:
            blob_url: Asset href - can be either:
                      - /vsiaz/ path (recommended for OAuth): /vsiaz/container/blob
                      - HTTPS URL (for SAS token access): https://account.blob.core.windows.net/...
            title: Human-readable asset title
            roles: Asset roles (data, thumbnail, overview, etc.)

        Returns:
            Validated stac-pydantic Asset

        Note:
            For OAuth-based access in TiTiler-pgSTAC, use /vsiaz/ paths.
            HTTPS URLs will bypass OAuth authentication.
        """
        asset = Asset(
            href=blob_url,
            type="image/tiff; application=geotiff; profile=cloud-optimized",
            title=title or "Cloud Optimized GeoTIFF",
            roles=roles or ["data"]
        )

        logger.debug(f"Created COG asset: {blob_url}")
        return asset

    def validate_item_dict(self, item_dict: Dict[str, Any]) -> Item:
        """
        Validate arbitrary dict against STAC Item schema.

        Args:
            item_dict: Dictionary to validate

        Returns:
            Validated Item if valid

        Raises:
            ValidationError: If dict doesn't match STAC Item spec
        """
        return Item(**item_dict)


# Export the service class
__all__ = ['StacMetadataService']
