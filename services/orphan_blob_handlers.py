# ============================================================================
# ORPHAN BLOB HANDLERS
# ============================================================================
# STATUS: Service layer - Handlers for orphan detection and registration
# PURPOSE: Detect and register orphaned silver blobs as STAC items
# CREATED: 14 JAN 2026
# EPIC: E7 Pipeline Infrastructure -> F7.11 STAC Catalog Self-Healing
# ============================================================================
"""
Orphan Blob Task Handlers.

Handlers for detect_orphan_blobs and register_silver_blobs jobs:

    - orphan_blob_inventory: Scan container, compare to cog_metadata
    - silver_blob_validate: Verify blobs exist, check registration status
    - silver_blob_register: Extract COG metadata, create cog_metadata + STAC

Schema Profiles:
    Built-in profiles define domain-specific STAC properties:
    - "default": Standard COG with azure:*, proj:* extensions
    - "fathom": FATHOM flood data with fathom:* properties

    Custom profiles can be passed as dicts with properties to add.

Exports:
    orphan_blob_inventory, silver_blob_validate, silver_blob_register
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
from pathlib import Path
import re

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "OrphanBlobHandlers")


# =============================================================================
# SCHEMA PROFILES
# =============================================================================

SCHEMA_PROFILES = {
    "default": {
        "stac_extensions": [
            "https://stac-extensions.github.io/projection/v1.1.0/schema.json",
            "https://stac-extensions.github.io/raster/v1.1.0/schema.json"
        ],
        "properties": {}  # No extra properties for default
    },
    "fathom": {
        "stac_extensions": [
            "https://stac-extensions.github.io/projection/v1.1.0/schema.json",
            "https://stac-extensions.github.io/raster/v1.1.0/schema.json",
            "https://stac-extensions.github.io/eo/v1.0.0/schema.json"
        ],
        "property_extractor": "_extract_fathom_properties"  # Function name to call
    }
}


def _extract_fathom_properties(blob_path: str, cog_info: dict = None) -> Dict[str, Any]:
    """
    Extract FATHOM-specific properties from blob path naming convention.

    FATHOM COG naming pattern:
        Phase 1: {tile}_{flood_type}_{defense}_{year}_{ssp}.tif
        Phase 2: {grid_cell}_{flood_type}_{defense}_{year}_{ssp}.tif

    Examples:
        n00w006_coastal_defended_2020_ssp126.tif
        n00-n05_w005-w000_fluvial_undefended_2050_ssp585.tif

    Returns:
        Dict with fathom:* properties
    """
    # Fathom return periods (inlined - FathomDefaults archived 13 FEB 2026)
    FATHOM_RETURN_PERIODS = ["1in5", "1in10", "1in20", "1in50", "1in100", "1in200", "1in500", "1in1000"]

    properties = {
        "fathom:depth_unit": "cm",
    }

    filename = Path(blob_path).stem.lower()

    # Try to extract flood type
    for flood_type in ["coastal", "fluvial", "pluvial"]:
        if flood_type in filename:
            properties["fathom:flood_type"] = flood_type
            break

    # Try to extract defense status
    if "defended" in filename:
        if "undefended" in filename:
            properties["fathom:defense_status"] = "undefended"
        else:
            properties["fathom:defense_status"] = "defended"

    # Try to extract year
    year_match = re.search(r'_(20[2-8]0)_', filename)
    if year_match:
        properties["fathom:year"] = int(year_match.group(1))

    # Try to extract SSP scenario
    ssp_match = re.search(r'_(ssp\d{3})\.?', filename)
    if ssp_match:
        properties["fathom:ssp_scenario"] = ssp_match.group(1)

    # Add band metadata if available
    if cog_info and cog_info.get("band_count", 0) == 8:
        # Standard 8-band FATHOM COG
        properties["fathom:return_periods"] = FATHOM_RETURN_PERIODS
        properties["eo:bands"] = [
            {"name": rp, "description": f"Flood depth for {rp.replace('in', '-in-')} year return period (cm)"}
            for rp in FATHOM_RETURN_PERIODS
        ]

    return properties


# =============================================================================
# HANDLER: orphan_blob_inventory
# =============================================================================

def orphan_blob_inventory(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Scan container and identify orphaned blobs (no cog_metadata entry).

    Stage 1 handler for detect_orphan_blobs job.

    Args:
        params: {
            "container": str,
            "zone": "silver" | "silverext",
            "prefix": str,
            "suffix": str,
            "limit": int,
            "job_id": str
        }

    Returns:
        {
            "success": True,
            "result": {
                "container": str,
                "blobs_scanned": int,
                "registered_count": int,
                "orphan_count": int,
                "orphan_total_mb": float,
                "orphans": [{"container": str, "blob_path": str, "size_mb": float}, ...]
            }
        }
    """
    from infrastructure.blob import BlobRepository
    from infrastructure.raster_metadata_repository import get_raster_metadata_repository

    container = params.get("container")
    zone = params.get("zone", "silver")
    prefix = params.get("prefix", "")
    suffix = params.get("suffix", ".tif").lower()
    limit = params.get("limit", 1000)

    logger.info(f"📋 Starting orphan blob inventory")
    logger.info(f"   Container: {container}")
    logger.info(f"   Zone: {zone}")
    logger.info(f"   Prefix: '{prefix}' | Suffix: '{suffix}' | Limit: {limit}")

    # Get blob repository for zone
    blob_repo = BlobRepository.for_zone(zone)

    # List blobs in container
    blobs = blob_repo.list_blobs(container=container, prefix=prefix, limit=limit)

    # Filter by suffix
    if suffix and not suffix.startswith('.'):
        suffix = '.' + suffix
    filtered_blobs = [b for b in blobs if b['name'].lower().endswith(suffix)]

    logger.info(f"   Found {len(filtered_blobs)} blobs matching suffix '{suffix}'")

    # Get cog_metadata repository
    cog_repo = get_raster_metadata_repository()

    # Check each blob against cog_metadata
    orphans = []
    registered_count = 0

    for blob in filtered_blobs:
        blob_path = blob['name']
        size_mb = blob.get('size', 0) / (1024 * 1024) if blob.get('size') else 0

        # Generate potential cog_id patterns to check
        # Common patterns: filename stem, container-path, etc.
        potential_ids = _generate_cog_id_candidates(container, blob_path)

        # Check if any potential ID exists in cog_metadata
        is_registered = False
        for cog_id in potential_ids:
            if cog_repo.get_by_id(cog_id):
                is_registered = True
                break

        if is_registered:
            registered_count += 1
        else:
            orphans.append({
                "container": container,
                "blob_path": blob_path,
                "size_mb": round(size_mb, 2)
            })

    orphan_total_mb = sum(o['size_mb'] for o in orphans)

    logger.info(f"✅ Orphan inventory complete:")
    logger.info(f"   Scanned: {len(filtered_blobs)}")
    logger.info(f"   Registered: {registered_count}")
    logger.info(f"   Orphans: {len(orphans)} ({orphan_total_mb:.1f} MB)")

    return {
        "success": True,
        "result": {
            "container": container,
            "zone": zone,
            "prefix": prefix,
            "suffix": suffix,
            "blobs_scanned": len(filtered_blobs),
            "registered_count": registered_count,
            "orphan_count": len(orphans),
            "orphan_total_mb": round(orphan_total_mb, 2),
            "orphans": orphans
        }
    }


def _generate_cog_id_candidates(container: str, blob_path: str) -> List[str]:
    """
    Generate potential cog_id values for a blob.

    Different ETL pipelines use different ID patterns. Check common ones.

    Returns:
        List of potential cog_id strings
    """
    stem = Path(blob_path).stem
    path_safe = blob_path.replace('/', '-').replace('.', '-')

    candidates = [
        stem,                               # Just filename stem
        f"{container}-{stem}",              # container-stem
        f"{container}-{path_safe}",         # container-full-path
        path_safe.rstrip('-tif'),           # path without extension
        blob_path,                          # Full path as-is
    ]

    return candidates


# =============================================================================
# HANDLER: silver_blob_validate
# =============================================================================

def silver_blob_validate(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate blobs exist and check registration status.

    Stage 1 handler for register_silver_blobs job.

    Args:
        params: {
            "blobs": [{"container": str, "blob_path": str}, ...],
            "zone": "silver" | "silverext",
            "collection_id": str (optional),
            "force_recreate": bool,
            "job_id": str
        }

    Returns:
        {
            "success": True,
            "result": {
                "total_requested": int,
                "valid_blobs": [{"container": str, "blob_path": str, "size_mb": float}, ...],
                "invalid_blobs": [{"blob": dict, "reason": str}, ...],
                "collection_id": str,
                "dry_run": bool
            }
        }
    """
    from infrastructure.blob import BlobRepository
    from infrastructure.raster_metadata_repository import get_raster_metadata_repository
    from config.defaults import STACDefaults

    blobs = params.get("blobs", [])
    zone = params.get("zone", "silver")
    collection_id = params.get("collection_id")
    force_recreate = params.get("force_recreate", False)

    logger.info(f"🔍 Validating {len(blobs)} blobs for registration")

    if not blobs:
        return {
            "success": True,
            "result": {
                "total_requested": 0,
                "valid_blobs": [],
                "invalid_blobs": [],
                "message": "No blobs provided"
            }
        }

    blob_repo = BlobRepository.for_zone(zone)
    cog_repo = get_raster_metadata_repository()

    valid_blobs = []
    invalid_blobs = []

    for blob_info in blobs:
        container = blob_info.get("container")
        blob_path = blob_info.get("blob_path")

        if not container or not blob_path:
            invalid_blobs.append({
                "blob": blob_info,
                "reason": "Missing container or blob_path"
            })
            continue

        # Check blob exists
        try:
            blob_props = blob_repo.get_blob_properties(container, blob_path)
            if not blob_props:
                invalid_blobs.append({
                    "blob": blob_info,
                    "reason": f"Blob not found in {container}"
                })
                continue

            size_mb = blob_props.get('size', 0) / (1024 * 1024)

        except Exception as e:
            invalid_blobs.append({
                "blob": blob_info,
                "reason": f"Error checking blob: {str(e)}"
            })
            continue

        # Check if already registered (unless force_recreate)
        if not force_recreate:
            potential_ids = _generate_cog_id_candidates(container, blob_path)
            for cog_id in potential_ids:
                if cog_repo.get_by_id(cog_id):
                    invalid_blobs.append({
                        "blob": blob_info,
                        "reason": f"Already registered as cog_id: {cog_id}"
                    })
                    break
            else:
                # Not registered, add to valid
                valid_blobs.append({
                    "container": container,
                    "blob_path": blob_path,
                    "size_mb": round(size_mb, 2)
                })
        else:
            # force_recreate - always valid
            valid_blobs.append({
                "container": container,
                "blob_path": blob_path,
                "size_mb": round(size_mb, 2)
            })

    # Determine collection_id
    if not collection_id:
        collection_id = STACDefaults.RASTER_COLLECTION

    logger.info(f"✅ Validation complete:")
    logger.info(f"   Valid: {len(valid_blobs)}")
    logger.info(f"   Invalid: {len(invalid_blobs)}")
    logger.info(f"   Collection: {collection_id}")

    return {
        "success": True,
        "result": {
            "total_requested": len(blobs),
            "valid_blobs": valid_blobs,
            "invalid_blobs": invalid_blobs,
            "collection_id": collection_id,
            "force_recreate": force_recreate,
            "validated_at": datetime.now(timezone.utc).isoformat()
        }
    }


# =============================================================================
# HANDLER: silver_blob_register
# =============================================================================

def silver_blob_register(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Register a single silver blob with cog_metadata and STAC.

    Stage 2 handler for register_silver_blobs job.

    Process:
        1. Read COG headers via rasterio
        2. Create/update app.cog_metadata entry
        3. Create STAC item in pgstac.items

    Args:
        params: {
            "container": str,
            "blob_path": str,
            "zone": "silver" | "silverext",
            "collection_id": str,
            "schema_profile": "default" | "fathom" | dict,
            "force_recreate": bool,
            "job_id": str
        }

    Returns:
        {
            "success": True,
            "result": {
                "registered": True,
                "cog_id": str,
                "stac_item_id": str,
                "collection_id": str,
                ...
            }
        }
    """
    from infrastructure.blob import BlobRepository
    from infrastructure.raster_metadata_repository import get_raster_metadata_repository
    from infrastructure.pgstac_bootstrap import PgStacBootstrap
    from config import get_config
    from config.defaults import STACDefaults

    container = params.get("container")
    blob_path = params.get("blob_path")
    zone = params.get("zone", "silver")
    collection_id = params.get("collection_id", STACDefaults.RASTER_COLLECTION)
    schema_profile = params.get("schema_profile", "default")
    force_recreate = params.get("force_recreate", False)
    job_id = params.get("job_id", "unknown")

    logger.info(f"🔨 Registering blob: {container}/{blob_path}")

    start_time = datetime.now(timezone.utc)
    config = get_config()

    try:
        # Step 1: Read COG metadata via rasterio
        cog_info = _extract_cog_info(container, blob_path, zone)

        if not cog_info.get("success"):
            return {
                "success": False,
                "error": cog_info.get("error", "Failed to read COG"),
                "error_type": "COGReadError",
                "container": container,
                "blob_path": blob_path
            }

        # Step 2: Generate cog_id (use filename stem as default)
        cog_id = Path(blob_path).stem

        # Step 3: Create cog_metadata entry
        cog_repo = get_raster_metadata_repository()

        # Build vsiaz path for COG URL
        cog_url = f"/vsiaz/{container}/{blob_path}"

        # Get schema profile
        profile_props, stac_extensions = _get_schema_profile(schema_profile, blob_path, cog_info)

        # Upsert to cog_metadata
        upsert_result = cog_repo.upsert(
            cog_id=cog_id,
            container=container,
            blob_path=blob_path,
            cog_url=cog_url,
            width=cog_info.get("width", 0),
            height=cog_info.get("height", 0),
            band_count=cog_info.get("band_count", 1),
            dtype=cog_info.get("dtype", "float32"),
            nodata=cog_info.get("nodata"),
            crs=cog_info.get("crs", "EPSG:4326"),
            transform=cog_info.get("transform"),
            resolution=cog_info.get("resolution"),
            bbox_minx=cog_info.get("bbox", [None])[0],
            bbox_miny=cog_info.get("bbox", [None, None])[1] if len(cog_info.get("bbox", [])) > 1 else None,
            bbox_maxx=cog_info.get("bbox", [None, None, None])[2] if len(cog_info.get("bbox", [])) > 2 else None,
            bbox_maxy=cog_info.get("bbox", [None, None, None, None])[3] if len(cog_info.get("bbox", [])) > 3 else None,
            is_cog=cog_info.get("is_cog", True),
            compression=cog_info.get("compression"),
            stac_item_id=cog_id,
            stac_collection_id=collection_id,
            etl_job_id=job_id,
            source_file=blob_path,
            custom_properties=profile_props if profile_props else None
        )

        if not upsert_result:
            logger.warning(f"   ⚠️ cog_metadata upsert returned False for {cog_id}")

        # Step 4: Create STAC item
        stac_repo = PgStacBootstrap()

        # If force_recreate, delete existing item first
        if force_recreate and stac_repo.item_exists(cog_id, collection_id):
            logger.info(f"   🗑️ Deleting existing STAC item: {cog_id}")
            try:
                stac_repo.delete_item(cog_id, collection_id)
            except Exception as e:
                logger.warning(f"   ⚠️ Could not delete existing item: {e}")

        # Build STAC item
        bbox = cog_info.get("bbox", [-180, -90, 180, 90])
        geometry = _bbox_to_geometry(bbox)

        item_datetime = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        # Build TiTiler URLs
        titiler_base = config.titiler_base_url.rstrip('/')
        import urllib.parse
        vsiaz_encoded = urllib.parse.quote(cog_url, safe='')

        stac_item = {
            "type": "Feature",
            "stac_version": "1.1.0",
            "stac_extensions": stac_extensions,
            "id": cog_id,
            "collection": collection_id,
            "geometry": geometry,
            "bbox": bbox,
            "properties": {
                "datetime": item_datetime,
                "azure:container": container,
                "azure:blob_path": blob_path,
                "proj:epsg": _crs_to_epsg(cog_info.get("crs")),
                **profile_props
            },
            "assets": {
                "data": {
                    "href": cog_url,
                    "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                    "title": f"Cloud-Optimized GeoTIFF",
                    "roles": ["data"],
                    "raster:bands": cog_info.get("raster_bands", [])
                },
                "thumbnail": {
                    "href": f"{titiler_base}/cog/preview.png?url={vsiaz_encoded}&max_size=256",
                    "type": "image/png",
                    "roles": ["thumbnail"],
                    "title": "Preview thumbnail"
                }
            },
            "links": [
                {
                    "rel": "collection",
                    "href": f"./collection.json",
                    "type": "application/json"
                },
                {
                    "rel": "preview",
                    "href": f"{titiler_base}/cog/WebMercatorQuad/map.html?url={vsiaz_encoded}",
                    "type": "text/html",
                    "title": "Interactive map viewer (TiTiler)"
                }
            ]
        }

        # Insert STAC item
        stac_repo.insert_item(stac_item, collection_id)

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()

        logger.info(f"✅ Registered {cog_id} in {duration:.2f}s")

        return {
            "success": True,
            "result": {
                "registered": True,
                "cog_id": cog_id,
                "stac_item_id": cog_id,
                "collection_id": collection_id,
                "container": container,
                "blob_path": blob_path,
                "bbox": bbox,
                "band_count": cog_info.get("band_count", 1),
                "schema_profile": schema_profile if isinstance(schema_profile, str) else "custom",
                "duration_seconds": round(duration, 2)
            }
        }

    except Exception as e:
        import traceback
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.error(f"❌ Failed to register {container}/{blob_path}: {e}")

        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "container": container,
            "blob_path": blob_path,
            "duration_seconds": round(duration, 2),
            "traceback": traceback.format_exc()
        }


def _extract_cog_info(container: str, blob_path: str, zone: str) -> Dict[str, Any]:
    """
    Extract COG information via rasterio.

    Returns:
        Dict with COG properties or error info
    """
    import rasterio

    from infrastructure.blob import BlobRepository

    blob_repo = BlobRepository.for_zone(zone)

    try:
        # Generate SAS URL for rasterio access
        blob_url = blob_repo.get_blob_url_with_sas(
            container_name=container,
            blob_name=blob_path,
            hours=1
        )

        with rasterio.open(blob_url) as dataset:
            # Get bounds in WGS84
            from rasterio.warp import transform_bounds

            try:
                bounds = transform_bounds(
                    dataset.crs,
                    "EPSG:4326",
                    *dataset.bounds
                )
                bbox = list(bounds)
            except Exception:
                # If transform fails, use raw bounds
                bbox = list(dataset.bounds)

            # Build raster:bands info
            raster_bands = []
            for i in range(1, dataset.count + 1):
                band_info = {
                    "data_type": str(dataset.dtypes[i - 1]),
                }
                if dataset.nodata is not None:
                    band_info["nodata"] = dataset.nodata
                raster_bands.append(band_info)

            return {
                "success": True,
                "width": dataset.width,
                "height": dataset.height,
                "band_count": dataset.count,
                "dtype": str(dataset.dtypes[0]),
                "nodata": dataset.nodata,
                "crs": str(dataset.crs),
                "transform": list(dataset.transform),
                "resolution": [abs(dataset.transform[0]), abs(dataset.transform[4])],
                "bbox": bbox,
                "is_cog": True,  # Assume COG if readable
                "compression": dataset.compression.value if dataset.compression else None,
                "raster_bands": raster_bands
            }

    except Exception as e:
        logger.error(f"Failed to read COG {container}/{blob_path}: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def _get_schema_profile(
    schema_profile: Any,
    blob_path: str,
    cog_info: dict
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Get properties and extensions for schema profile.

    Args:
        schema_profile: "default", "fathom", or custom dict
        blob_path: Blob path for property extraction
        cog_info: COG info dict

    Returns:
        (properties_dict, stac_extensions_list)
    """
    if isinstance(schema_profile, dict):
        # Custom properties passed directly
        default_extensions = SCHEMA_PROFILES["default"]["stac_extensions"]
        return schema_profile, default_extensions

    if schema_profile not in SCHEMA_PROFILES:
        schema_profile = "default"

    profile = SCHEMA_PROFILES[schema_profile]
    extensions = profile.get("stac_extensions", [])

    # Get properties
    if "property_extractor" in profile:
        # Call extractor function
        extractor_name = profile["property_extractor"]
        if extractor_name == "_extract_fathom_properties":
            properties = _extract_fathom_properties(blob_path, cog_info)
        else:
            properties = {}
    else:
        properties = profile.get("properties", {})

    return properties, extensions


def _bbox_to_geometry(bbox: List[float]) -> Dict[str, Any]:
    """Convert bbox [minx, miny, maxx, maxy] to GeoJSON Polygon."""
    if not bbox or len(bbox) != 4:
        return None

    minx, miny, maxx, maxy = bbox
    return {
        "type": "Polygon",
        "coordinates": [[
            [minx, miny],
            [maxx, miny],
            [maxx, maxy],
            [minx, maxy],
            [minx, miny]
        ]]
    }


def _crs_to_epsg(crs_str: str) -> Optional[int]:
    """Extract EPSG code from CRS string."""
    if not crs_str:
        return None

    if crs_str.upper().startswith("EPSG:"):
        try:
            return int(crs_str.split(":")[1])
        except (IndexError, ValueError):
            pass

    # Try to parse WKT or other formats
    try:
        from rasterio.crs import CRS
        crs = CRS.from_string(crs_str)
        return crs.to_epsg()
    except Exception:
        return None


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    'orphan_blob_inventory',
    'silver_blob_validate',
    'silver_blob_register',
    'SCHEMA_PROFILES'
]
