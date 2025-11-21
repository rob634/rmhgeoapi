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
        self.stac = PgStacRepository()  # 18 NOV 2025: Use PgStacRepository for data operations

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

        # STEP G.5: Convert asset URLs to /vsiaz/ paths for OAuth compatibility
        try:
            logger.debug("   Step G.5: Converting asset URLs to /vsiaz/ paths for OAuth...")
            converted_count = 0
            for asset_key, asset_value in item_dict.get('assets', {}).items():
                if 'href' in asset_value:
                    original_url = asset_value['href']

                    # Convert HTTPS URLs to /vsiaz/ paths for OAuth-based access
                    if original_url.startswith('https://'):
                        # Extract container and blob path from HTTPS URL
                        # Format: https://account.blob.core.windows.net/container/path/to/blob.tif?sas_token
                        # Target: /vsiaz/container/path/to/blob.tif

                        # Remove SAS token if present
                        base_url = original_url.split('?')[0]

                        # Extract path after blob.core.windows.net/
                        # Example: https://rmhazuregeo.blob.core.windows.net/silver-cogs/file.tif
                        #       -> silver-cogs/file.tif
                        if '.blob.core.windows.net/' in base_url:
                            path_part = base_url.split('.blob.core.windows.net/', 1)[1]
                            vsiaz_path = f"/vsiaz/{path_part}"
                            asset_value['href'] = vsiaz_path
                            converted_count += 1
                            logger.debug(f"      Converted asset '{asset_key}' to /vsiaz/ path")
                            logger.debug(f"         Before: {original_url[:100]}...")
                            logger.debug(f"         After:  {vsiaz_path}")
                        else:
                            logger.warning(f"      Could not parse HTTPS URL for asset '{asset_key}': {original_url[:100]}...")
                    elif original_url.startswith('/vsiaz/'):
                        # Already a /vsiaz/ path - no conversion needed
                        logger.debug(f"      Asset '{asset_key}' already uses /vsiaz/ path: {original_url}")
                    else:
                        logger.debug(f"      Asset '{asset_key}' uses non-HTTPS URL: {original_url[:100]}...")

            if converted_count > 0:
                logger.info(f"   ✅ Step G.5: Converted {converted_count} asset URL(s) to /vsiaz/ paths for OAuth")
            else:
                logger.debug(f"   ✅ Step G.5: No HTTPS URLs to convert (assets may already use /vsiaz/ paths)")
        except Exception as e:
            logger.error(f"❌ Step G.5 FAILED: Error converting asset URLs to /vsiaz/ paths")
            logger.error(f"   Error: {e}")
            logger.error(f"   Traceback:\n{traceback.format_exc()}")
            # CRITICAL (11 NOV 2025): /vsiaz/ paths required for OAuth-based TiTiler access
            # Fail fast rather than creating Items that won't work with TiTiler
            # If conversion fails, indicates URL format issue that needs to be fixed
            raise RuntimeError(f"/vsiaz/ path conversion failed: {e}")

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

        # STEP H.5: Add vanilla TiTiler visualization links and thumbnail asset
        try:
            logger.debug("   Step H.5: Adding vanilla TiTiler visualization links...")
            from config import get_config
            import urllib.parse

            config = get_config()
            titiler_base = config.titiler_base_url.rstrip('/')
            vsiaz_path = f"/vsiaz/{container}/{blob_name}"
            encoded_vsiaz = urllib.parse.quote(vsiaz_path, safe='')

            # Add thumbnail asset (overwrites rio-stac generated asset if present)
            item_dict['assets']['thumbnail'] = {
                'href': f"{titiler_base}/cog/preview.png?url={encoded_vsiaz}&max_size=256",
                'type': 'image/png',
                'roles': ['thumbnail'],
                'title': 'Thumbnail preview via TiTiler'
            }
            logger.debug("      Added thumbnail asset (vanilla TiTiler)")

            # Add vanilla TiTiler visualization links
            titiler_links = [
                {
                    'rel': 'preview',
                    'href': f"{titiler_base}/cog/WebMercatorQuad/map.html?url={encoded_vsiaz}",
                    'type': 'text/html',
                    'title': 'Interactive map viewer (vanilla TiTiler)'
                },
                {
                    'rel': 'tilejson',
                    'href': f"{titiler_base}/cog/WebMercatorQuad/tilejson.json?url={encoded_vsiaz}",
                    'type': 'application/json',
                    'title': 'TileJSON specification for web maps'
                }
            ]

            # Append to existing links or create new list
            if 'links' not in item_dict:
                item_dict['links'] = []
            item_dict['links'].extend(titiler_links)

            logger.debug(f"   ✅ Step H.5: Added {len(titiler_links)} vanilla TiTiler links + thumbnail asset")
        except Exception as e:
            logger.error(f"❌ Step H.5 FAILED: Error adding TiTiler visualization links")
            logger.error(f"   Error: {e}")
            logger.error(f"   Traceback:\n{traceback.format_exc()}")
            # CRITICAL (11 NOV 2025): If TiTiler link generation fails, indicates config/URL issue
            # Better to fail fast and fix the root cause than silently create incomplete Items
            # TiTiler URLs are a core feature - if they fail, something is wrong with config
            raise RuntimeError(f"TiTiler link generation failed: {e}")

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
