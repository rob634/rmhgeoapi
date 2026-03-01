# ============================================================================
# UNPUBLISH WORKFLOW HANDLERS
# ============================================================================
# STATUS: Service layer - Task handlers for unpublish jobs
# PURPOSE: Provide surgical data removal for raster and vector assets
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: inventory_raster_item, inventory_vector_item, inventory_zarr_item, delete_blob, drop_postgis_table, delete_stac_and_audit
# DEPENDENCIES: psycopg, azure-storage-blob
# ============================================================================
"""
Unpublish Workflow Handlers.

Task handlers for unpublish_raster and unpublish_vector jobs.
Provides surgical data removal - reverse of raster/vector processing.

Handlers:
    inventory_raster_item: Query STAC item, extract asset hrefs for blob deletion
    inventory_vector_item: Query geo.table_metadata for ETL/STAC linkage info
    delete_blob: Delete single blob from Azure Storage (idempotent)
    drop_postgis_table: Drop PostGIS table + delete metadata row (idempotent)
    delete_stac_and_audit: Delete STAC item (if linked), cleanup collection, record audit

Date: 12 DEC 2025 - Initial implementation
Date: 13 DEC 2025 - Refactored vector to use geo.table_metadata as primary source
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from psycopg import sql as psql

from util_logger import LoggerFactory, ComponentType
from config.defaults import STACDefaults
from config.vector_config import VectorConfig

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "UnpublishHandlers")


# =============================================================================
# INVENTORY HANDLERS (Stage 1)
# =============================================================================

def inventory_raster_item(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Query STAC item and extract asset hrefs for blob deletion.

    Stage 1 handler for unpublish_raster job.
    Uses pre-validated STAC item from params['_stac_item'] (populated by stac_item_exists validator).

    Extracts:
    - COG blobs from item['assets']['data']['href']
    - MosaicJSON from item['assets']['mosaic']['href'] (if present)
    - Tile COGs from item['assets']['tile_*']['href'] (large raster/collection workflows)

    Args:
        params: {
            'stac_item_id': str,
            'collection_id': str,
            'dry_run': bool,
            '_stac_item': dict (from validator),
            '_stac_item_assets': dict (from validator),
            '_stac_original_job_id': str (if available)
        }
        context: Optional job context

    Returns:
        {
            'success': True,
            'blobs_to_delete': [...],  # List of blob paths for Stage 2 fan-out
            'original_job_id': str or None,
            'stac_item_snapshot': dict  # For audit trail
        }
    """
    try:
        stac_item_id = params.get('stac_item_id')
        collection_id = params.get('collection_id')
        dry_run = params.get('dry_run', True)

        # Get pre-validated STAC item from validator
        stac_item = params.get('_stac_item')
        assets = params.get('_stac_item_assets', {})
        original_job_id = params.get('_stac_original_job_id')

        if not stac_item:
            return {
                "success": False,
                "error": "STAC item not found in params - stac_item_exists validator may have failed",
                "error_type": "ValidationError"
            }

        # Check if this item has an APPROVED release (V0.9 - 21 FEB 2026)
        # Approved items require force_approved=true to unpublish
        force_approved = params.get('force_approved', False)
        try:
            from infrastructure import ReleaseRepository
            from psycopg import sql as psql

            release_repo = ReleaseRepository()
            with release_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        psql.SQL("SELECT release_id, approval_state FROM {}.{} WHERE stac_item_id = %s ORDER BY created_at DESC LIMIT 1").format(
                            psql.Identifier(release_repo.schema),
                            psql.Identifier(release_repo.table)
                        ),
                        (stac_item_id,)
                    )
                    row = cur.fetchone()

            if row and row['approval_state'] == 'approved':
                if not force_approved:
                    return {
                        "success": False,
                        "error": f"Cannot unpublish approved release. Use force_approved=true.",
                        "error_type": "ApprovalBlocksUnpublish",
                        "release_id": row['release_id'],
                        "approval_state": row['approval_state'],
                        "hint": "Use force_approved=true to revoke approval and unpublish"
                    }
                logger.warning(f"Force-unpublishing approved release {row['release_id'][:16]}...")
        except Exception as e:
            logger.error(f"Cannot verify approval status for {stac_item_id}: {e}")
            return {
                "success": False,
                "error": f"Approval check failed — cannot proceed without verification: {e}",
                "error_type": "ApprovalCheckFailed",
                "hint": "Retry when database is available, or use force_approved=true to bypass."
            }

        # Extract blob paths from assets
        blobs_to_delete = []

        for asset_key, asset_value in assets.items():
            href = asset_value.get('href', '')

            # Only process Azure blob URLs or relative paths
            if href.startswith('https://') and '.blob.core.windows.net/' in href:
                # Parse blob path from full URL
                # Format: https://{account}.blob.core.windows.net/{container}/{blob_path}
                parts = href.split('.blob.core.windows.net/', 1)
                if len(parts) == 2:
                    container_and_blob = parts[1]
                    if '/' in container_and_blob:
                        container, blob_path = container_and_blob.split('/', 1)
                        blobs_to_delete.append({
                            'container': container,
                            'blob_path': blob_path,
                            'asset_key': asset_key,
                            'href': href
                        })
            elif href.startswith('/vsiaz/'):
                # GDAL /vsiaz/ virtual path: /vsiaz/{container}/{blob_path}
                vsiaz_path = href[len('/vsiaz/'):]  # strip '/vsiaz/'
                if '/' in vsiaz_path:
                    container, blob_path = vsiaz_path.split('/', 1)
                    blobs_to_delete.append({
                        'container': container,
                        'blob_path': blob_path,
                        'asset_key': asset_key,
                        'href': href
                    })
            elif href.startswith('/') or not href.startswith('http'):
                # Relative path - assume silver-cogs container
                blobs_to_delete.append({
                    'container': 'silver-cogs',
                    'blob_path': href.lstrip('/'),
                    'asset_key': asset_key,
                    'href': href
                })

        logger.info(
            f"{'[DRY-RUN] ' if dry_run else ''}Inventoried raster item {collection_id}/{stac_item_id}: "
            f"{len(blobs_to_delete)} blobs to delete"
        )

        return {
            "success": True,
            "stac_item_id": stac_item_id,
            "collection_id": collection_id,
            "blobs_to_delete": blobs_to_delete,
            "blob_count": len(blobs_to_delete),
            "original_job_id": original_job_id,
            "stac_item_snapshot": stac_item,
            "dry_run": dry_run
        }

    except Exception as e:
        logger.error(f"Failed to inventory raster item: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def inventory_vector_item(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Query geo.table_catalog + app.vector_etl_tracking for metadata.

    Stage 1 handler for unpublish_vector job.
    NOTE (21 JAN 2026): Queries TWO tables due to separation of concerns:
    - geo.table_catalog: Service layer (stac_item_id, feature_count, etc.)
    - app.vector_etl_tracking: ETL internals (etl_job_id, source_file, etc.)

    Args:
        params: {
            'table_name': str,
            'schema_name': str (default from VectorConfig),
            'dry_run': bool
        }
        context: Optional job context

    Returns:
        {
            'success': True,
            'table_name': str,
            'schema_name': str,
            'metadata_found': bool,
            'etl_job_id': str or None,
            'stac_item_id': str or None,
            'stac_collection_id': str or None,
            'metadata_snapshot': dict  # Full metadata from both tables
        }
    """
    from infrastructure.postgresql import PostgreSQLRepository

    try:
        table_name = params.get('table_name')
        # Get schema from params or from VectorConfig
        vector_config = VectorConfig.from_environment()
        schema_name = params.get('schema_name') or vector_config.target_schema
        dry_run = params.get('dry_run', True)

        if not table_name:
            return {
                "success": False,
                "error": "table_name is required",
                "error_type": "ValidationError"
            }

        metadata = None
        metadata_found = False
        etl_job_id = None
        stac_item_id = None
        stac_collection_id = None
        source_file = None
        source_format = None
        source_crs = None
        feature_count = None

        repo = PostgreSQLRepository()
        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Query geo.table_catalog for SERVICE LAYER metadata
                cur.execute(
                    psql.SQL("""
                    SELECT
                        table_name, schema_name,
                        stac_item_id, stac_collection_id,
                        feature_count, geometry_type,
                        created_at, updated_at,
                        bbox_minx, bbox_miny, bbox_maxx, bbox_maxy
                    FROM {}.{}
                    WHERE table_name = %s
                    """).format(
                        psql.Identifier('geo'),
                        psql.Identifier('table_catalog')
                    ),
                    (table_name,)
                )
                catalog_row = cur.fetchone()

                # Query app.vector_etl_tracking for ETL INTERNAL metadata
                # (Get latest ETL run for this table)
                cur.execute(
                    psql.SQL("""
                    SELECT
                        etl_job_id, source_file, source_format, source_crs,
                        created_at
                    FROM {}.{}
                    WHERE table_name = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """).format(
                        psql.Identifier('app'),
                        psql.Identifier('vector_etl_tracking')
                    ),
                    (table_name,)
                )
                etl_row = cur.fetchone()

                if catalog_row or etl_row:
                    metadata_found = True

                    # Extract from catalog (service layer)
                    if catalog_row:
                        stac_item_id = catalog_row.get('stac_item_id')
                        stac_collection_id = catalog_row.get('stac_collection_id')
                        feature_count = catalog_row.get('feature_count')

                    # Extract from ETL tracking (internal)
                    if etl_row:
                        etl_job_id = etl_row.get('etl_job_id')
                        source_file = etl_row.get('source_file')
                        source_format = etl_row.get('source_format')
                        source_crs = etl_row.get('source_crs')

                    # Build full metadata snapshot for audit (combines both tables)
                    metadata = {
                        'table_name': catalog_row['table_name'] if catalog_row else table_name,
                        'schema_name': catalog_row.get('schema_name', schema_name) if catalog_row else schema_name,
                        'etl_job_id': etl_job_id,
                        'source_file': source_file,
                        'source_format': source_format,
                        'source_crs': source_crs,
                        'stac_item_id': stac_item_id,
                        'stac_collection_id': stac_collection_id,
                        'feature_count': feature_count,
                        'geometry_type': catalog_row.get('geometry_type') if catalog_row else None,
                        'created_at': str(catalog_row['created_at']) if catalog_row and catalog_row.get('created_at') else None,
                        'updated_at': str(catalog_row['updated_at']) if catalog_row and catalog_row.get('updated_at') else None,
                        'bbox': [catalog_row['bbox_minx'], catalog_row['bbox_miny'], catalog_row['bbox_maxx'], catalog_row['bbox_maxy']]
                            if catalog_row and catalog_row.get('bbox_minx') is not None else None
                    }

                    logger.info(
                        f"{'[DRY-RUN] ' if dry_run else ''}Found metadata for {schema_name}.{table_name}: "
                        f"etl_job={etl_job_id[:16] if etl_job_id else 'none'}..., "
                        f"stac_item={stac_item_id or 'none'}, features={feature_count}"
                    )
                else:
                    # No metadata rows - table may have been created outside ETL
                    # This is OK - we can still drop the table
                    logger.info(
                        f"{'[DRY-RUN] ' if dry_run else ''}No metadata found for {schema_name}.{table_name} "
                        f"(created outside ETL). Table will still be dropped."
                    )

        # Check if linked STAC item has an APPROVED release (V0.9 - 21 FEB 2026)
        # Approved items require force_approved=true to unpublish
        force_approved = params.get('force_approved', False)
        if stac_item_id:
            try:
                from infrastructure import ReleaseRepository
                from psycopg import sql as psql

                release_repo = ReleaseRepository()
                with release_repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            psql.SQL("SELECT release_id, approval_state FROM {}.{} WHERE stac_item_id = %s ORDER BY created_at DESC LIMIT 1").format(
                                psql.Identifier(release_repo.schema),
                                psql.Identifier(release_repo.table)
                            ),
                            (stac_item_id,)
                        )
                        row = cur.fetchone()

                if row and row['approval_state'] == 'approved':
                    if not force_approved:
                        return {
                            "success": False,
                            "error": f"Cannot unpublish approved release. Use force_approved=true.",
                            "error_type": "ApprovalBlocksUnpublish",
                            "release_id": row['release_id'],
                            "approval_state": row['approval_state'],
                            "table_name": table_name,
                            "hint": "Use force_approved=true to revoke approval and unpublish"
                        }
                    logger.warning(f"Force-unpublishing approved release {row['release_id'][:16]}...")
            except Exception as e:
                logger.error(f"Cannot verify approval status for {stac_item_id}: {e}")
                return {
                    "success": False,
                    "error": f"Approval check failed — cannot proceed without verification: {e}",
                    "error_type": "ApprovalCheckFailed",
                    "hint": "Retry when database is available, or use force_approved=true to bypass."
                }

        return {
            "success": True,
            "table_name": table_name,
            "schema_name": schema_name,
            "metadata_found": metadata_found,
            "etl_job_id": etl_job_id,
            "stac_item_id": stac_item_id,
            "stac_collection_id": stac_collection_id,
            "source_file": source_file,
            "source_format": source_format,
            "feature_count": feature_count,
            "metadata_snapshot": metadata,
            "dry_run": dry_run
        }

    except Exception as e:
        logger.error(f"Failed to inventory vector item {params.get('table_name')}: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def inventory_zarr_item(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Discover all zarr artifacts, classify them, check approval state, return blob list.

    Stage 1 handler for unpublish_zarr job.
    Implements spec Component 3: inventory_zarr_item.

    Discovery chain (spec Component 3):
    1. Query pgstac.items for STAC item (fall back to Release record if not materialized)
    2. Extract combined_ref.json href from STAC assets["reference"]["href"]
    3. Derive ref_output_prefix from href (strip "/combined_ref.json")
    4. Read manifest.json at {ref_output_prefix}/manifest.json
    5. Extract data file paths from manifest["files"][]["silver_path"]
    6. If manifest read fails, fall back to BlobRepository.list_blobs(prefix=ref_output_prefix + "/data/")

    Error handling addresses Critic concern C's E-4 (data type guard)
    and Operator concern (approval check).

    Args:
        params: {
            'stac_item_id': str,
            'collection_id': str,
            'dry_run': bool,
            'delete_data_files': bool,
            'force_approved': bool,
        }
        context: Optional job context

    Returns:
        {
            'success': True,
            'stac_item_id': str,
            'collection_id': str,
            'blobs_to_delete': [{"container": str, "blob_path": str, "category": str}],
            'ref_blob_count': int,
            'data_file_count': int,
            'stac_item_snapshot': dict,
            'stac_materialized': bool,
            'original_job_id': str or None,
            'dry_run': bool,
            'delete_data_files': bool,
        }
    """
    try:
        stac_item_id = params.get('stac_item_id')
        collection_id = params.get('collection_id')
        dry_run = params.get('dry_run', True)
        delete_data_files = params.get('delete_data_files', True)
        force_approved = params.get('force_approved', False)

        if not stac_item_id or not collection_id:
            return {
                "success": False,
                "error": "stac_item_id and collection_id are required",
                "error_type": "ValidationError"
            }

        # =====================================================================
        # Step 1: Locate STAC item (pgstac first, Release fallback)
        # Spec Component 3: Discovery chain step 1
        # =====================================================================
        stac_item = None
        stac_materialized = False
        original_job_id = None

        # Try pgstac first
        try:
            from infrastructure.pgstac_repository import PgStacRepository
            pgstac_repo = PgStacRepository()
            stac_item = pgstac_repo.get_item(stac_item_id, collection_id)
            if stac_item:
                stac_materialized = True
                properties = stac_item.get('properties', {})
                original_job_id = properties.get('geoetl:job_id')
                logger.info(
                    f"{'[DRY-RUN] ' if dry_run else ''}Found zarr item in pgstac: "
                    f"{collection_id}/{stac_item_id}"
                )
        except Exception as pgstac_err:
            logger.warning(f"pgstac lookup failed for {stac_item_id}: {pgstac_err}")

        # Fall back to Release record if not in pgstac
        if not stac_item:
            try:
                from infrastructure import ReleaseRepository
                release_repo = ReleaseRepository()
                release = release_repo.get_by_stac_item_id(stac_item_id)
                if release and release.stac_item_json:
                    stac_item = release.stac_item_json
                    original_job_id = release.job_id
                    logger.info(
                        f"{'[DRY-RUN] ' if dry_run else ''}Found zarr item in Release record: "
                        f"{stac_item_id} (not materialized to pgstac)"
                    )
            except Exception as release_err:
                logger.warning(f"Release lookup failed for {stac_item_id}: {release_err}")

        if not stac_item:
            # Spec Component 3: STAC item not found error
            return {
                "success": False,
                "error": f"STAC item '{stac_item_id}' not found in pgstac or Release records for collection '{collection_id}'",
                "error_type": "NotFoundError"
            }

        # =====================================================================
        # Step 2: Data type guard (Critic concern C's E-4)
        # Spec Component 3: Check geoetl:data_type
        # =====================================================================
        properties = stac_item.get('properties', {})
        data_type = properties.get('geoetl:data_type')
        if data_type and data_type != 'zarr':
            return {
                "success": False,
                "error": (
                    f"STAC item '{stac_item_id}' has data_type='{data_type}', expected 'zarr'. "
                    f"Use the appropriate unpublish job for {data_type} data."
                ),
                "error_type": "DataTypeMismatch"
            }

        # =====================================================================
        # Step 3: Approval check (Operator concern)
        # Spec Component 3: Copy pattern from inventory_raster_item
        # =====================================================================
        try:
            from infrastructure import ReleaseRepository as _ReleaseRepo
            from psycopg import sql as _psql

            _release_repo = _ReleaseRepo()
            with _release_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        _psql.SQL(
                            "SELECT release_id, approval_state FROM {}.{} "
                            "WHERE stac_item_id = %s ORDER BY created_at DESC LIMIT 1"
                        ).format(
                            _psql.Identifier(_release_repo.schema),
                            _psql.Identifier(_release_repo.table)
                        ),
                        (stac_item_id,)
                    )
                    row = cur.fetchone()

            if row and row['approval_state'] == 'approved':
                if not force_approved:
                    return {
                        "success": False,
                        "error": "Cannot unpublish approved release. Use force_approved=true.",
                        "error_type": "ApprovalBlocksUnpublish",
                        "release_id": row['release_id'],
                        "approval_state": row['approval_state'],
                        "hint": "Use force_approved=true to revoke approval and unpublish"
                    }
                logger.warning(f"Force-unpublishing approved zarr release {row['release_id'][:16]}...")
        except Exception as e:
            # Addresses Operator concern: approval check failure is non-recoverable
            logger.error(f"Cannot verify approval status for {stac_item_id}: {e}")
            return {
                "success": False,
                "error": f"Approval check failed -- cannot proceed without verification: {e}",
                "error_type": "ApprovalCheckFailed",
                "hint": "Retry when database is available, or use force_approved=true to bypass."
            }

        # =====================================================================
        # Step 4: Extract reference href and derive ref_output_prefix
        # Spec Component 3: Discovery chain steps 2-3
        # =====================================================================
        assets = stac_item.get('assets', {})
        ref_asset = assets.get('reference', {})
        ref_href = ref_asset.get('href', '')

        if not ref_href:
            return {
                "success": False,
                "error": f"STAC item '{stac_item_id}' has no 'reference' asset href",
                "error_type": "ValidationError"
            }

        # Derive container and ref_output_prefix from href
        # href format: abfs://silver-netcdf/datasets/foo/v1/combined_ref.json
        # OR: silver-netcdf/datasets/foo/v1/combined_ref.json
        clean_href = ref_href.replace("abfs://", "")
        href_parts = clean_href.split("/", 1)
        container = href_parts[0]
        blob_path = href_parts[1] if len(href_parts) > 1 else ""

        # Strip /combined_ref.json to get ref_output_prefix
        combined_ref_suffix = "/combined_ref.json"
        if blob_path.endswith("combined_ref.json"):
            ref_output_prefix = blob_path[:blob_path.rfind("/combined_ref.json")]
        else:
            # Ambiguity note: href doesn't end with combined_ref.json.
            # Use the directory of the href as the prefix.
            ref_output_prefix = blob_path.rsplit("/", 1)[0] if "/" in blob_path else blob_path

        # =====================================================================
        # Step 5: Build blob list - always include reference files
        # Spec Component 3: Blob classification
        # =====================================================================
        blobs_to_delete = []

        # Always delete: combined_ref.json (category="reference")
        blobs_to_delete.append({
            "container": container,
            "blob_path": blob_path,
            "category": "reference"
        })

        # Always delete: manifest.json (category="reference")
        manifest_blob_path = f"{ref_output_prefix}/manifest.json"
        blobs_to_delete.append({
            "container": container,
            "blob_path": manifest_blob_path,
            "category": "reference"
        })

        # =====================================================================
        # Step 6: Discover data files from manifest (with list_blobs fallback)
        # Spec Component 3: Discovery chain steps 4-6
        # =====================================================================
        data_file_paths = []
        if delete_data_files:
            # Try reading manifest first
            manifest_read_success = False
            try:
                from infrastructure import BlobRepository
                silver_repo = BlobRepository.for_zone("silver")
                manifest_data = silver_repo.read_blob(container, manifest_blob_path)
                import json
                manifest = json.loads(manifest_data)
                files_list = manifest.get("files", [])
                for file_entry in files_list:
                    silver_path = file_entry.get("silver_path")
                    if silver_path:
                        data_file_paths.append(silver_path)
                manifest_read_success = True
                logger.info(
                    f"{'[DRY-RUN] ' if dry_run else ''}Read manifest: "
                    f"{len(data_file_paths)} data files found"
                )
            except Exception as manifest_err:
                # Spec Component 3: Manifest read fails - WARNING log, fall back to list_blobs
                logger.warning(
                    f"Manifest read failed for {container}/{manifest_blob_path}: {manifest_err}. "
                    f"Falling back to list_blobs."
                )

            # Fall back to list_blobs if manifest read failed
            if not manifest_read_success:
                try:
                    from infrastructure import BlobRepository
                    silver_repo = BlobRepository.for_zone("silver")
                    data_prefix = f"{ref_output_prefix}/data/"
                    blob_list = silver_repo.list_blobs(container, prefix=data_prefix)
                    for blob_info in blob_list:
                        data_file_paths.append(blob_info["name"])
                    logger.info(
                        f"{'[DRY-RUN] ' if dry_run else ''}list_blobs fallback: "
                        f"{len(data_file_paths)} data files found under {data_prefix}"
                    )
                except Exception as list_err:
                    # Spec Component 3: Both manifest and list_blobs fail -
                    # continue with ref-only deletion
                    logger.warning(
                        f"list_blobs fallback also failed for {container}/{ref_output_prefix}/data/: "
                        f"{list_err}. Continuing with reference-only deletion."
                    )

            # Add data files to blob list
            for data_path in data_file_paths:
                blobs_to_delete.append({
                    "container": container,
                    "blob_path": data_path,
                    "category": "data_file"
                })

        # Count by category
        ref_blob_count = sum(1 for b in blobs_to_delete if b["category"] == "reference")
        data_file_count = sum(1 for b in blobs_to_delete if b["category"] == "data_file")

        logger.info(
            f"{'[DRY-RUN] ' if dry_run else ''}Inventoried zarr item {collection_id}/{stac_item_id}: "
            f"{ref_blob_count} reference blobs, {data_file_count} data files to delete"
        )

        return {
            "success": True,
            "stac_item_id": stac_item_id,
            "collection_id": collection_id,
            "blobs_to_delete": blobs_to_delete,
            "ref_blob_count": ref_blob_count,
            "data_file_count": data_file_count,
            "stac_item_snapshot": stac_item,
            "stac_materialized": stac_materialized,
            "original_job_id": original_job_id,
            "dry_run": dry_run,
            "delete_data_files": delete_data_files,
        }

    except Exception as e:
        logger.error(f"Failed to inventory zarr item {params.get('stac_item_id')}: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


# =============================================================================
# DELETE HANDLERS (Stage 2)
# =============================================================================

def delete_blob(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Delete single blob from Azure Storage (idempotent).

    Uses BlobRepository.delete_blob().
    Returns success even if blob already deleted (idempotent).

    Args:
        params: {
            'container': str,
            'blob_path': str,
            'dry_run': bool
        }
        context: Optional job context

    Returns:
        {
            'success': True,
            'deleted': bool,  # True if actually deleted, False if already gone
            'container': str,
            'blob_path': str
        }
    """
    from infrastructure.blob import BlobRepository

    try:
        container = params.get('container')
        blob_path = params.get('blob_path')
        dry_run = params.get('dry_run', True)

        if not container or not blob_path:
            return {
                "success": False,
                "error": "Container and blob_path are required",
                "error_type": "ValidationError"
            }

        if dry_run:
            logger.info(f"[DRY-RUN] Would delete blob: {container}/{blob_path}")
            return {
                "success": True,
                "deleted": False,
                "dry_run": True,
                "container": container,
                "blob_path": blob_path
            }

        # Determine zone from container name
        zone = 'silver' if 'silver' in container.lower() else 'bronze'
        blob_repo = BlobRepository.for_zone(zone)

        # Check if blob exists first
        if not blob_repo.blob_exists(container, blob_path):
            logger.info(f"Blob already deleted (idempotent): {container}/{blob_path}")
            return {
                "success": True,
                "deleted": False,
                "already_gone": True,
                "container": container,
                "blob_path": blob_path
            }

        # Delete the blob
        blob_repo.delete_blob(container, blob_path)

        logger.info(f"Deleted blob: {container}/{blob_path}")
        return {
            "success": True,
            "deleted": True,
            "container": container,
            "blob_path": blob_path
        }

    except Exception as e:
        logger.error(f"Failed to delete blob {params.get('container')}/{params.get('blob_path')}: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def drop_postgis_table(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Drop PostGIS table and optionally delete metadata row (idempotent).

    DROP TABLE IF EXISTS {schema}.{table_name} CASCADE
    DELETE FROM geo.table_metadata WHERE table_name = ? (if delete_metadata=True)
    Respects dry_run parameter.

    Args:
        params: {
            'table_name': str,
            'schema_name': str (default from VectorConfig),
            'delete_metadata': bool (default True),
            'dry_run': bool
        }
        context: Optional job context

    Returns:
        {
            'success': True,
            'table_dropped': bool,
            'metadata_deleted': bool,
            'table_name': str,
            'schema_name': str
        }
    """
    from infrastructure.postgresql import PostgreSQLRepository
    from psycopg import sql

    try:
        table_name = params.get('table_name')
        # Get schema from params or from VectorConfig
        vector_config = VectorConfig.from_environment()
        schema_name = params.get('schema_name') or vector_config.target_schema
        delete_metadata = params.get('delete_metadata', True)
        dry_run = params.get('dry_run', True)

        if not table_name:
            return {
                "success": False,
                "error": "table_name is required",
                "error_type": "ValidationError"
            }

        # Curated table protection (15 DEC 2025)
        # Tables with curated_ prefix are system-managed and cannot be dropped
        # via normal unpublish workflow. Use curated dataset management API instead.
        force_curated = params.get('force_curated', False)
        if table_name.startswith('curated_') and not force_curated:
            logger.warning(
                f"Attempted to drop protected curated table: {table_name}. "
                f"Use force_curated=True or curated dataset management API."
            )
            return {
                "success": False,
                "error": f"Cannot drop curated table '{table_name}'. "
                         f"Curated tables are system-managed and protected. "
                         f"Use the curated dataset management API instead, "
                         f"or pass force_curated=True if authorized.",
                "error_type": "ProtectedTableError",
                "table_name": table_name,
                "is_curated": True
            }

        if dry_run:
            logger.info(
                f"[DRY-RUN] Would drop table: {schema_name}.{table_name}"
                f"{' and delete metadata' if delete_metadata else ''}"
            )
            return {
                "success": True,
                "table_dropped": False,
                "metadata_deleted": False,
                "dry_run": True,
                "table_name": table_name,
                "schema_name": schema_name,
                # Pass through Stage 1 inventory data for Stage 3
                "_inventory_data": params.get("_inventory_data", {})
            }

        repo = PostgreSQLRepository()
        table_dropped = False
        metadata_deleted = False

        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Check if table exists first
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = %s AND table_name = %s
                    ) as exists
                    """,
                    (schema_name, table_name)
                )
                exists = cur.fetchone()['exists']

                if not exists:
                    logger.info(f"Table already dropped (idempotent): {schema_name}.{table_name}")
                else:
                    # Drop the table with CASCADE
                    drop_query = sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                        sql.Identifier(schema_name),
                        sql.Identifier(table_name)
                    )
                    cur.execute(drop_query)
                    table_dropped = True
                    logger.info(f"Dropped table: {schema_name}.{table_name}")

                # Delete metadata rows if requested (21 JAN 2026: both tables)
                if delete_metadata:
                    # Delete from geo.table_catalog (service layer)
                    cur.execute(
                        psql.SQL("DELETE FROM {}.{} WHERE table_name = %s RETURNING table_name").format(
                            psql.Identifier('geo'),
                            psql.Identifier('table_catalog')
                        ),
                        (table_name,)
                    )
                    catalog_deleted = cur.fetchone()

                    # Delete from app.vector_etl_tracking (ETL internal - all rows for this table)
                    cur.execute(
                        psql.SQL("DELETE FROM {}.{} WHERE table_name = %s RETURNING table_name").format(
                            psql.Identifier('app'),
                            psql.Identifier('vector_etl_tracking')
                        ),
                        (table_name,)
                    )
                    etl_deleted = cur.fetchone()

                    metadata_deleted = catalog_deleted is not None or etl_deleted is not None

                    if metadata_deleted:
                        logger.info(f"Deleted metadata for: {table_name} (catalog={catalog_deleted is not None}, etl={etl_deleted is not None})")
                    else:
                        logger.info(f"No metadata rows found for: {table_name} (idempotent)")

                conn.commit()

        return {
            "success": True,
            "table_dropped": table_dropped,
            "metadata_deleted": metadata_deleted,
            "already_gone": not exists,
            "table_name": table_name,
            "schema_name": schema_name,
            # Pass through Stage 1 inventory data for Stage 3
            "_inventory_data": params.get("_inventory_data", {})
        }

    except Exception as e:
        logger.error(f"Failed to drop table {params.get('schema_name', 'geo')}.{params.get('table_name')}: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


# =============================================================================
# CLEANUP HANDLER (Stage 3)
# =============================================================================

def delete_stac_and_audit(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Delete STAC item (if linked), cleanup empty collection, record audit.

    Final stage handler for both unpublish_raster and unpublish_vector jobs.
    For vectors, STAC deletion is OPTIONAL - only if stac_item_id was found in metadata.

    Steps:
    1. If stac_item_id provided: DELETE FROM pgstac.items WHERE id = ? AND collection = ?
    2. If deleted: Check if collection empty: COUNT(*) FROM pgstac.items WHERE collection = ?
    3. If empty AND NOT IN STACDefaults.SYSTEM_COLLECTIONS: DELETE FROM pgstac.collections
    4. Record to app.unpublish_jobs audit table
    5. (Optional) Mark original job as unpublished for idempotency

    Args:
        params: {
            'stac_item_id': str or None (optional for vectors!),
            'collection_id': str or None,
            'unpublish_type': str ('raster' or 'vector'),
            'unpublish_job_id': str,  # The unpublish job's ID
            'original_job_id': str or None,
            'original_job_type': str or None,
            'metadata_snapshot': dict or None,  # For audit trail (vectors)
            'stac_item_snapshot': dict or None,  # For audit trail (rasters)
            'artifacts_deleted': dict,  # What was deleted in Stage 2
            'postgis_table': str or None,  # For vectors
            'table_dropped': bool,  # For vectors
            'dry_run': bool
        }
        context: Optional job context

    Returns:
        {
            'success': True,
            'stac_item_deleted': bool,
            'collection_deleted': bool,
            'audit_record_id': str
        }
    """
    from infrastructure.postgresql import PostgreSQLRepository
    from core.models.unpublish import UnpublishJobRecord, UnpublishType, UnpublishStatus
    import json

    try:
        stac_item_id = params.get('stac_item_id')
        collection_id = params.get('collection_id')
        unpublish_type = params.get('unpublish_type', 'raster')
        unpublish_job_id = params.get('unpublish_job_id')
        original_job_id = params.get('original_job_id')
        original_job_type = params.get('original_job_type')
        metadata_snapshot = params.get('metadata_snapshot')  # Vector metadata from geo.table_metadata
        stac_item_snapshot = params.get('stac_item_snapshot', {})  # Raster STAC item
        postgis_table = params.get('postgis_table')
        table_dropped = params.get('table_dropped', False)
        dry_run = params.get('dry_run', True)

        # For vectors: stac_item_id is OPTIONAL (may not have STAC item)
        # For rasters: stac_item_id is REQUIRED
        has_stac = stac_item_id is not None and collection_id is not None

        # Build artifacts_deleted from available data
        artifacts_deleted = {}
        if postgis_table:
            artifacts_deleted['table'] = postgis_table
            artifacts_deleted['table_dropped'] = table_dropped
        if metadata_snapshot:
            artifacts_deleted['metadata'] = metadata_snapshot
        if stac_item_snapshot:
            artifacts_deleted['stac_item'] = stac_item_snapshot

        # Create audit record
        audit_record = UnpublishJobRecord(
            unpublish_job_id=unpublish_job_id or 'unknown',
            unpublish_type=UnpublishType(unpublish_type),
            original_job_id=original_job_id,
            original_job_type=original_job_type,
            original_parameters=None,  # Will extract from snapshot if available
            stac_item_id=stac_item_id or 'none',
            collection_id=collection_id or 'none',
            artifacts_deleted=artifacts_deleted,
            dry_run=dry_run
        )

        if dry_run:
            stac_msg = f"STAC item {collection_id}/{stac_item_id}" if has_stac else "no STAC item"
            logger.info(
                f"[DRY-RUN] Would complete unpublish ({unpublish_type}): {stac_msg}, "
                f"table={postgis_table or 'n/a'}"
            )
            audit_record.status = UnpublishStatus.DRY_RUN
            return {
                "success": True,
                "stac_item_deleted": False,
                "collection_deleted": False,
                "dry_run": True,
                "stac_item_id": stac_item_id,
                "collection_id": collection_id,
                "postgis_table": postgis_table,
                "audit_record": audit_record.model_dump(mode='json')  # Pydantic v2: mode='json' for serialization
            }

        repo = PostgreSQLRepository()
        stac_deleted = False
        collection_deleted = False
        item_count = 0

        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Step 1: Delete STAC item (only if we have one)
                if has_stac:
                    cur.execute(
                        "DELETE FROM pgstac.items WHERE id = %s AND collection = %s RETURNING id",
                        (stac_item_id, collection_id)
                    )
                    deleted_row = cur.fetchone()
                    stac_deleted = deleted_row is not None

                    if stac_deleted:
                        logger.info(f"Deleted STAC item: {collection_id}/{stac_item_id}")

                        # Revoke release in SAME transaction as STAC delete
                        try:
                            cur.execute(
                                "SELECT release_id, approval_state FROM app.asset_releases WHERE stac_item_id = %s LIMIT 1",
                                (stac_item_id,)
                            )
                            rel_row = cur.fetchone()
                            if rel_row and rel_row.get('approval_state') == 'approved':
                                cur.execute(
                                    "UPDATE app.asset_releases SET approval_state = 'revoked', is_served = false, is_latest = false, revoked_at = NOW() WHERE release_id = %s",
                                    (rel_row['release_id'],)
                                )
                                logger.warning(f"AUDIT: Revoked release {rel_row['release_id'][:16]}... during unpublish (atomic with STAC delete)")
                        except Exception as revoke_err:
                            logger.error(f"Failed to revoke release during unpublish: {revoke_err}")
                            raise  # Fail the transaction — don't leave inconsistent state
                    else:
                        logger.warning(f"STAC item not found (already deleted?): {collection_id}/{stac_item_id}")

                    # Step 2: Check if collection is now empty
                    cur.execute(
                        "SELECT COUNT(*) as cnt FROM pgstac.items WHERE collection = %s",
                        (collection_id,)
                    )
                    item_count = cur.fetchone()['cnt']

                    # Step 3: Delete empty collection if not protected
                    if item_count == 0 and collection_id not in STACDefaults.SYSTEM_COLLECTIONS:
                        cur.execute(
                            "DELETE FROM pgstac.collections WHERE id = %s RETURNING id",
                            (collection_id,)
                        )
                        deleted_collection = cur.fetchone()
                        collection_deleted = deleted_collection is not None

                        if collection_deleted:
                            logger.info(f"Deleted empty collection: {collection_id}")
                    elif item_count == 0 and collection_id:
                        logger.info(f"Collection {collection_id} is empty but protected (system collection)")
                else:
                    logger.info(f"No STAC item to delete (vector without STAC linkage)")

                # Step 4: Record to audit table
                audit_record.status = UnpublishStatus.COMPLETED
                audit_record.collection_deleted = collection_deleted
                audit_record.completed_at = datetime.now(timezone.utc)

                # Serialize artifacts_deleted as JSON (must not be NULL per schema constraint)
                artifacts_json = json.dumps(audit_record.artifacts_deleted) if audit_record.artifacts_deleted else '{}'

                cur.execute(
                    """
                    INSERT INTO app.unpublish_jobs (
                        unpublish_id, unpublish_job_id, unpublish_type,
                        original_job_id, original_job_type, original_parameters,
                        stac_item_id, collection_id,
                        artifacts_deleted, collection_deleted,
                        status, dry_run, created_at, completed_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        audit_record.unpublish_id,
                        audit_record.unpublish_job_id,
                        audit_record.unpublish_type.value,
                        audit_record.original_job_id,
                        audit_record.original_job_type,
                        None,  # original_parameters - not storing for now
                        audit_record.stac_item_id,
                        audit_record.collection_id,
                        artifacts_json,
                        audit_record.collection_deleted,
                        audit_record.status.value,
                        audit_record.dry_run,
                        audit_record.created_at,
                        audit_record.completed_at
                    )
                )

                conn.commit()

        logger.info(
            f"Unpublish complete ({unpublish_type}): stac_deleted={stac_deleted}, "
            f"collection_deleted={collection_deleted}, table={postgis_table or 'n/a'}, "
            f"audit_id={audit_record.unpublish_id}"
        )

        return {
            "success": True,
            "stac_item_deleted": stac_deleted,
            "stac_item_id": stac_item_id,
            "collection_id": collection_id,
            "collection_deleted": collection_deleted,
            "collection_remaining_items": item_count if not collection_deleted else 0,
            "postgis_table": postgis_table,
            "audit_record_id": audit_record.unpublish_id,
            "blobs_deleted": params.get('blobs_deleted', []),
            "dry_run": False
        }

    except Exception as e:
        logger.error(f"Failed to complete unpublish and audit: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    'inventory_raster_item',
    'inventory_vector_item',
    'inventory_zarr_item',
    'delete_blob',
    'drop_postgis_table',
    'delete_stac_and_audit',
]
