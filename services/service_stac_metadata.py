# ============================================================================
# CLAUDE CONTEXT - SERVICE
# ============================================================================
# PURPOSE: Extract STAC metadata from raster files using rio-stac + stac-pydantic
# EXPORTS: StacMetadataService class
# PYDANTIC_MODELS: stac_pydantic.Item, stac_pydantic.Asset
# DEPENDENCIES: stac-pydantic, rio-stac, rasterio, azure-storage-blob
# PATTERNS: Service Layer, DRY (leverage libraries for metadata extraction)
# ENTRY_POINTS: StacMetadataService().extract_item_from_blob()
# ============================================================================

"""
STAC Metadata Extraction Service

Extracts STAC Item metadata from raster files using rio-stac library.
Validates with stac-pydantic for type safety and STAC spec compliance.

Strategy: DRY - Leverage libraries for heavy lifting
- rio-stac: Geometry, bbox, projection, raster metadata extraction
- stac-pydantic: Validation and type safety
- Our code: Azure metadata, collection determination, custom properties

Author: Robert and Geospatial Claude Legion
Date: 5 OCT 2025
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
from infrastructure.stac import StacInfrastructure

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
        self.blob_repo = BlobRepository.instance()
        self.stac = StacInfrastructure()

    def extract_item_from_blob(
        self,
        container: str,
        blob_name: str,
        collection_id: str = 'dev',
        existing_metadata: Optional[Dict[str, Any]] = None,
        item_id: Optional[str] = None
    ) -> Item:
        """
        Extract STAC Item from raster blob using rio-stac.

        Args:
            container: Azure container name
            blob_name: Blob path within container
            collection_id: STAC collection ID (default: 'dev')
            existing_metadata: Optional metadata from analyze_single_blob()
            item_id: Optional custom STAC item ID (auto-generated if not provided)

        Returns:
            Validated stac-pydantic Item

        Raises:
            ValidationError: If extracted metadata fails STAC validation
            rasterio.errors.RasterioIOError: If blob cannot be read as raster

        Strategy:
            1. Generate SAS URL for rasterio access
            2. Let rio-stac extract geometry, bbox, projection, raster metadata
            3. Supplement with Azure blob metadata
            4. Validate with stac-pydantic
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

            SIZE_THRESHOLD_MB = 1000  # 1 GB threshold
            extract_statistics = file_size_mb <= SIZE_THRESHOLD_MB

            if not extract_statistics:
                logger.warning(
                    f"   ⚠️  File {blob_name} is {file_size_mb:.1f} MB (> {SIZE_THRESHOLD_MB} MB) - "
                    f"skipping raster statistics to avoid timeout."
                )
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
                        asset_media_type="image/tiff; application=geotiff",
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

        # STEP G.5: Remove SAS tokens from asset URLs
        try:
            logger.debug("   Step G.5: Sanitizing asset URLs (removing SAS tokens)...")
            sanitized_count = 0
            for asset_key, asset_value in item_dict.get('assets', {}).items():
                if 'href' in asset_value:
                    original_url = asset_value['href']
                    # Check if URL contains SAS token parameters
                    if '?' in original_url:
                        # Remove everything after '?' to strip SAS token
                        base_url = original_url.split('?')[0]
                        asset_value['href'] = base_url
                        sanitized_count += 1
                        logger.debug(f"      Sanitized asset '{asset_key}': removed SAS token")
                        logger.debug(f"         Before: {original_url[:100]}...")
                        logger.debug(f"         After:  {base_url}")

            if sanitized_count > 0:
                logger.info(f"   ✅ Step G.5: Sanitized {sanitized_count} asset URL(s) - removed SAS tokens")
            else:
                logger.debug(f"   ✅ Step G.5: No SAS tokens found in asset URLs")
        except Exception as e:
            logger.error(f"❌ Step G.5 FAILED: Error sanitizing asset URLs")
            logger.error(f"   Error: {e}")
            logger.error(f"   Traceback:\n{traceback.format_exc()}")
            # Don't raise - this is not critical enough to fail the entire operation
            logger.warning(f"   ⚠️  Continuing with unsanitized URLs")

        # STEP H: Supplement with Azure-specific properties
        try:
            logger.debug("   Step H: Adding Azure-specific properties...")
            item_dict['properties']['azure:container'] = container
            item_dict['properties']['azure:blob_path'] = blob_name
            item_dict['properties']['azure:tier'] = self._determine_tier(container)
            item_dict['properties']['azure:size_mb'] = file_size_mb
            item_dict['properties']['azure:statistics_extracted'] = extract_statistics

            if existing_metadata:
                item_dict['properties']['azure:etag'] = existing_metadata.get('etag')
                item_dict['properties']['azure:content_type'] = existing_metadata.get('content_type')

            logger.debug(f"   ✅ Step H: Azure properties added")
        except Exception as e:
            logger.error(f"❌ Step H FAILED: Error adding Azure properties")
            logger.error(f"   Error: {e}")
            logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise ValueError(f"Failed to add Azure properties: {e}")

        # STEP I: Validate with stac-pydantic
        try:
            logger.debug("   Step I: Validating with stac-pydantic...")
            item = Item(**item_dict)
            logger.debug(f"   ✅ Step I: STAC Item validated successfully")
        except Exception as e:
            logger.error(f"❌ Step I FAILED: stac-pydantic validation error")
            logger.error(f"   Error: {e}")
            logger.error(f"   Error type: {type(e).__name__}")
            logger.error(f"   Item dict keys: {list(item_dict.keys())}")
            logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise ValueError(f"STAC Item validation failed: {e}")

        logger.info(f"✅ STAC ITEM EXTRACTION COMPLETE: {item.id}")
        return item

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

    def create_cog_asset(
        self,
        blob_url: str,
        title: Optional[str] = None,
        roles: Optional[list] = None
    ) -> Asset:
        """
        Create a validated STAC Asset for a Cloud Optimized GeoTIFF.

        Args:
            blob_url: Full URL to COG in Azure Storage
            title: Human-readable asset title
            roles: Asset roles (data, thumbnail, overview, etc.)

        Returns:
            Validated stac-pydantic Asset
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
