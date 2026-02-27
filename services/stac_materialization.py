# ============================================================================
# CLAUDE CONTEXT - STAC MATERIALIZATION ENGINE
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Service - Core STAC materialization (DB → pgSTAC)
# PURPOSE: Build B2C-clean STAC from internal DB; all pgSTAC writes go here
# LAST_REVIEWED: 26 FEB 2026
# EXPORTS: STACMaterializer
# DEPENDENCIES: infrastructure.pgstac_repository, infrastructure.release_repository
# ============================================================================
"""
STAC Materialization Engine.

Central service that builds B2C-clean STAC from internal DB tables.
All pgSTAC writes go through this service. pgSTAC is a materialized view
of our internal metadata — it contains zero internal artifacts and can be
fully rebuilt from our DB.

Design Principle:
    pgSTAC = deterministic function(internal DB)
    Every item in pgSTAC can be reconstructed from asset_releases + cog_metadata.

Key Operations:
    - materialize_item(): Build clean STAC item from Release → pgSTAC
    - materialize_collection(): Build/update collection extent from items
    - materialize_release(): Full approval flow (item + collection)
    - dematerialize_item(): Remove item, recalc extent or delete collection
    - rebuild_collection_from_db(): Nuclear rebuild from internal DB
    - rebuild_all_from_db(): Full catalog rebuild

B2C Sanitization:
    All geoetl:* (internal provenance) properties are stripped.
    Only ddh:*, geo:*, and standard STAC properties are exposed.

Exports:
    STACMaterializer: Core materialization engine
"""

import urllib.parse
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "STACMaterializer")


class STACMaterializer:
    """
    Core STAC materialization engine.

    Bridges internal DB (source of truth) to pgSTAC (materialized B2C view).
    All pgSTAC writes should go through this service to ensure consistency
    and B2C cleanliness.

    Usage:
        materializer = STACMaterializer()
        result = materializer.materialize_release(release, reviewer, clearance_state)
    """

    def __init__(self):
        """Initialize with lazy-loaded repository dependencies."""
        self._pgstac = None
        self._release_repo = None
        self._cog_repo = None

    @property
    def pgstac(self):
        """Lazy-load PgStacRepository."""
        if self._pgstac is None:
            from infrastructure.pgstac_repository import PgStacRepository
            self._pgstac = PgStacRepository()
        return self._pgstac

    @property
    def release_repo(self):
        """Lazy-load ReleaseRepository."""
        if self._release_repo is None:
            from infrastructure.release_repository import ReleaseRepository
            self._release_repo = ReleaseRepository()
        return self._release_repo

    @property
    def cog_repo(self):
        """Lazy-load RasterMetadataRepository."""
        if self._cog_repo is None:
            from infrastructure.raster_metadata_repository import RasterMetadataRepository
            self._cog_repo = RasterMetadataRepository.instance()
        return self._cog_repo

    # =========================================================================
    # SANITIZATION
    # =========================================================================

    def sanitize_item_properties(self, item_dict: dict) -> dict:
        """
        Remove internal (geoetl:*) properties, keep B2C-facing ones.

        B2C properties retained: ddh:*, geo:*, standard STAC (datetime, title, etc.)
        Internal properties stripped: geoetl:* (provenance, job tracking, etc.)

        Args:
            item_dict: STAC item dict (mutated in place and returned)

        Returns:
            The same item_dict with geoetl:* properties removed
        """
        props = item_dict.get('properties', {})
        clean_props = {
            k: v for k, v in props.items()
            if not k.startswith('geoetl:')
        }
        item_dict['properties'] = clean_props
        return item_dict

    # =========================================================================
    # MATERIALIZE (DB → pgSTAC)
    # =========================================================================

    def materialize_item(
        self,
        release,
        reviewer: str,
        clearance_state
    ) -> Dict[str, Any]:
        """
        Build a clean STAC item from a Release and write to pgSTAC.

        Handles both single COG and tiled output modes.

        For single COG:
            1. Copy cached release.stac_item_json
            2. Set id, collection, versioned title + self-link
            3. Add B2C properties (ddh:version_id, ddh:access_level)
            4. Sanitize (strip geoetl:*)
            5. Inject TiTiler visualization URLs
            6. Upsert to pgSTAC

        For tiled output:
            1. Get all item IDs from pgSTAC (inserted at processing time)
            2. Patch each with B2C approval properties
            3. Sanitize each (strip geoetl:*)

        Args:
            release: AssetRelease model
            reviewer: Who approved
            clearance_state: ClearanceState enum (OUO or PUBLIC)

        Returns:
            Dict with success, pgstac_id/items_updated, optional mosaic_viewer_url
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        # =================================================================
        # TILED OUTPUT
        # =================================================================
        if release.output_mode == 'tiled':
            return self._materialize_tiled_items(release, reviewer, clearance_state, now_iso)

        # =================================================================
        # VECTOR RELEASES — not yet supported for STAC materialization
        # =================================================================
        if not release.blob_path and not release.stac_item_json:
            logger.info(
                f"Skipping STAC materialization for vector release "
                f"{release.release_id[:16]}... (no blob_path or cached STAC JSON)"
            )
            return {
                'success': True,
                'skipped': True,
                'reason': 'vector_release',
                'message': 'Vector STAC materialization not yet implemented',
            }

        # =================================================================
        # SINGLE COG OUTPUT
        # =================================================================
        if not release.stac_item_json:
            logger.warning(
                f"No cached STAC item JSON on release {release.release_id[:16]}..."
            )
            return {
                'success': False,
                'error': (
                    f'STAC metadata not cached on release {release.release_id[:16]}... '
                    f'-- resubmit data'
                )
            }

        # Copy to avoid mutating model
        stac_item_json = dict(release.stac_item_json)

        # Patch with versioned ID and collection
        versioned_id = release.stac_item_id
        stac_item_json['id'] = versioned_id
        stac_item_json['collection'] = release.stac_collection_id

        # Patch title and self-link
        props = stac_item_json.setdefault('properties', {})
        if versioned_id:
            props['title'] = versioned_id
            for link in stac_item_json.get('links', []):
                if link.get('rel') == 'self':
                    href = link.get('href', '')
                    items_prefix = '/items/'
                    idx = href.rfind(items_prefix)
                    if idx >= 0:
                        link['href'] = href[:idx + len(items_prefix)] + versioned_id

        # Add B2C approval properties
        props['ddh:approved_by'] = reviewer
        props['ddh:approved_at'] = now_iso
        props['ddh:access_level'] = clearance_state.value
        if release.version_id:
            props['ddh:version_id'] = release.version_id

        # Sanitize: strip all geoetl:* properties
        self.sanitize_item_properties(stac_item_json)

        # Inject TiTiler visualization URLs
        self._inject_titiler_urls(stac_item_json, release.blob_path)

        # Upsert item to pgSTAC
        pgstac_id = self.pgstac.insert_item(stac_item_json, release.stac_collection_id)
        logger.info(
            f"Materialized STAC item {versioned_id} in collection "
            f"{release.stac_collection_id}"
        )

        return {'success': True, 'pgstac_id': pgstac_id}

    def _materialize_tiled_items(
        self,
        release,
        reviewer: str,
        clearance_state,
        now_iso: str
    ) -> Dict[str, Any]:
        """
        Handle tiled output materialization.

        Patches existing pgSTAC items with B2C approval properties
        and strips internal geoetl:* properties.
        """
        # B2C approval properties (no geoetl: namespace)
        approval_props = {
            'ddh:approved_by': reviewer,
            'ddh:approved_at': now_iso,
            'ddh:access_level': clearance_state.value,
        }
        if release.version_id:
            approval_props['ddh:version_id'] = release.version_id
        if release.release_id:
            approval_props['ddh:release_id'] = release.release_id

        item_ids = self.pgstac.get_collection_item_ids(release.stac_collection_id)

        if not item_ids:
            # Fallback: items weren't inserted at processing time.
            # Insert from cog_metadata now.
            logger.warning(
                f"No pgSTAC items found for tiled collection "
                f"{release.stac_collection_id} — inserting from cog_metadata"
            )
            return self._materialize_tiled_from_cog_metadata(
                release, approval_props
            )

        # Patch each existing item: add B2C props, strip geoetl:*
        for item_id in item_ids:
            # Get full item, sanitize, add approval props, upsert back
            item_dict = self.pgstac.get_item(item_id, release.stac_collection_id)
            if not item_dict:
                continue

            props = item_dict.setdefault('properties', {})
            props.update(approval_props)

            # Sanitize: strip geoetl:*
            self.sanitize_item_properties(item_dict)

            # Upsert back (full item replacement)
            self.pgstac.insert_item(item_dict, release.stac_collection_id)

        logger.info(
            f"Materialized {len(item_ids)} tiled items in {release.stac_collection_id}"
        )

        # Build mosaic URL from search_id
        mosaic_viewer_url = None
        if release.search_id:
            try:
                from services.pgstac_search_registration import PgSTACSearchRegistration
                from config import get_config
                config = get_config()
                registrar = PgSTACSearchRegistration()
                urls = registrar.get_search_urls(
                    release.search_id, config.titiler_base_url, assets=['data']
                )
                mosaic_viewer_url = urls.get('viewer')
            except Exception as e:
                logger.warning(f"Failed to build mosaic URL: {e}")

        return {
            'success': True,
            'items_updated': len(item_ids),
            'mosaic_viewer_url': mosaic_viewer_url,
        }

    def _materialize_tiled_from_cog_metadata(
        self,
        release,
        approval_props: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Fallback: insert tiled items from cog_metadata table."""
        from services.stac_collection import build_raster_stac_collection

        cog_records = self.cog_repo.list_by_collection(release.stac_collection_id)

        # Upsert collection first
        if cog_records:
            first_item = cog_records[0].get('stac_item_json', {})
            bbox = first_item.get('bbox', [-180, -90, 180, 90])
            collection_dict = build_raster_stac_collection(
                collection_id=release.stac_collection_id,
                bbox=bbox,
            )
            self.pgstac.insert_collection(collection_dict)

        item_ids = []
        for rec in cog_records:
            stac_json = rec.get('stac_item_json')
            if not stac_json:
                continue
            item_dict = dict(stac_json)
            props = item_dict.setdefault('properties', {})
            props.update(approval_props)

            # Sanitize
            self.sanitize_item_properties(item_dict)

            self.pgstac.insert_item(item_dict, release.stac_collection_id)
            item_ids.append(item_dict.get('id'))

        logger.info(
            f"Inserted {len(item_ids)} tiled items from cog_metadata "
            f"(B2C clean)"
        )

        return {
            'success': True,
            'items_updated': len(item_ids),
        }

    def materialize_collection(self, collection_id: str) -> Dict[str, Any]:
        """
        Build/update a STAC collection from ALL items currently in pgSTAC.

        Computes union extent from all items and upserts the collection.

        Args:
            collection_id: STAC collection ID

        Returns:
            Dict with success and collection details
        """
        from services.stac_collection import build_raster_stac_collection

        extent = self.pgstac.compute_collection_extent(collection_id)
        if not extent:
            logger.warning(f"No items in collection '{collection_id}' — skipping update")
            return {'success': False, 'error': f"No items in collection '{collection_id}'"}

        # Get existing collection for description preservation
        existing = self.pgstac.get_collection(collection_id)
        description = None
        if existing:
            description = existing.get('description')

        # Build collection with union extent
        collection_dict = build_raster_stac_collection(
            collection_id=collection_id,
            bbox=extent['bbox'],
            description=description,
            temporal_start=extent['temporal'][0] if extent.get('temporal') else None,
        )

        # Set temporal end if available
        if extent.get('temporal') and extent['temporal'][1]:
            collection_dict['extent']['temporal']['interval'] = [
                [extent['temporal'][0], extent['temporal'][1]]
            ]

        self.pgstac.insert_collection(collection_dict)
        logger.info(
            f"Collection '{collection_id}' updated: bbox={extent['bbox']}, "
            f"items={extent['item_count']}"
        )

        return {
            'success': True,
            'collection_id': collection_id,
            'bbox': extent['bbox'],
            'item_count': extent['item_count'],
        }

    def materialize_release(
        self,
        release,
        reviewer: str,
        clearance_state
    ) -> Dict[str, Any]:
        """
        Full approval materialization (replaces _materialize_stac).

        1. Materialize item (write clean item to pgSTAC)
        2. Materialize collection (update extent from all items)

        Args:
            release: AssetRelease model
            reviewer: Who approved
            clearance_state: ClearanceState enum

        Returns:
            Combined result dict
        """
        if not release.stac_item_id or not release.stac_collection_id:
            return {
                'success': False,
                'error': 'Release has no STAC item/collection ID'
            }

        try:
            # Step 1: Materialize item
            item_result = self.materialize_item(release, reviewer, clearance_state)

            if not item_result.get('success'):
                return item_result

            # Step 2: Update collection extent
            coll_result = self.materialize_collection(release.stac_collection_id)

            # Merge results
            result = dict(item_result)
            result['collection_updated'] = coll_result.get('success', False)
            result['collection_bbox'] = coll_result.get('bbox')
            result['collection_item_count'] = coll_result.get('item_count')

            return result

        except Exception as e:
            logger.error(f"Error materializing release: {e}")
            return {'success': False, 'error': str(e)}

    # =========================================================================
    # DEMATERIALIZE (pgSTAC → remove)
    # =========================================================================

    def dematerialize_item(
        self,
        collection_id: str,
        item_id: str
    ) -> Dict[str, Any]:
        """
        Remove an item and update collection (or delete if empty).

        1. Delete item from pgSTAC
        2. If collection still has items: recalculate extent
        3. If collection is now empty: delete collection

        Args:
            collection_id: STAC collection ID
            item_id: STAC item ID to remove

        Returns:
            Dict with success, deleted, and cleanup actions taken
        """
        logger.info(f"Dematerializing item '{item_id}' from '{collection_id}'")

        try:
            deleted = self.pgstac.delete_item(collection_id, item_id)

            if not deleted:
                return {
                    'success': True,
                    'deleted': False,
                    'reason': f"Item '{item_id}' not found in collection '{collection_id}'"
                }

            # Check remaining items
            remaining = self.pgstac.get_collection_item_count(collection_id)

            if remaining > 0:
                # Recalculate extent from remaining items
                self.materialize_collection(collection_id)
                logger.info(
                    f"Recalculated extent for '{collection_id}' ({remaining} items remaining)"
                )
                return {
                    'success': True,
                    'deleted': True,
                    'collection_action': 'extent_recalculated',
                    'remaining_items': remaining,
                }
            else:
                # Empty collection — delete it
                self.pgstac.delete_collection(collection_id)
                logger.info(f"Deleted empty collection '{collection_id}'")
                return {
                    'success': True,
                    'deleted': True,
                    'collection_action': 'deleted_empty',
                    'remaining_items': 0,
                }

        except Exception as e:
            logger.error(f"Error dematerializing item '{item_id}': {e}")
            return {'success': False, 'error': str(e)}

    # =========================================================================
    # REBUILD (nuclear: internal DB → fresh pgSTAC)
    # =========================================================================

    def rebuild_collection_from_db(self, collection_id: str) -> Dict[str, Any]:
        """
        Nuclear rebuild — reads internal DB, writes fresh to pgSTAC.

        1. Query all APPROVED releases with stac_collection_id = collection_id
        2. For each release: build clean item dict from stac_item_json
        3. Delete existing collection + items from pgSTAC
        4. Insert fresh collection + all items

        Args:
            collection_id: STAC collection ID to rebuild

        Returns:
            Dict with items_created, extent, etc.
        """
        from core.models.asset import ApprovalState
        from services.stac_collection import build_raster_stac_collection

        logger.info(f"Rebuilding collection '{collection_id}' from internal DB")

        # Query approved releases for this collection
        releases = self.release_repo.list_by_approval_state(ApprovalState.APPROVED, limit=1000)
        matching_releases = [
            r for r in releases
            if r.stac_collection_id == collection_id
        ]

        if not matching_releases:
            logger.warning(f"No approved releases for collection '{collection_id}'")
            return {
                'success': True,
                'collection_id': collection_id,
                'items_created': 0,
                'action': 'no_approved_releases',
            }

        # Delete existing collection + items from pgSTAC
        existing_items = self.pgstac.get_collection_item_ids(collection_id)
        for item_id in existing_items:
            self.pgstac.delete_item(collection_id, item_id)

        if self.pgstac.collection_exists(collection_id):
            self.pgstac.delete_collection(collection_id)

        # Single pass: build all items, collect bboxes
        prepared_items = []

        for release in matching_releases:
            if not release.stac_item_json:
                logger.warning(
                    f"Release {release.release_id[:16]} has no stac_item_json, skipping"
                )
                continue

            if release.output_mode == 'tiled':
                cog_records = self.cog_repo.list_by_collection(collection_id)
                for rec in cog_records:
                    stac_json = rec.get('stac_item_json')
                    if not stac_json:
                        continue
                    item_dict = dict(stac_json)
                    self.sanitize_item_properties(item_dict)

                    props = item_dict.setdefault('properties', {})
                    props['ddh:access_level'] = release.clearance_state.value if release.clearance_state else 'ouo'
                    if release.version_id:
                        props['ddh:version_id'] = release.version_id

                    prepared_items.append(item_dict)
                continue

            # Single COG
            item_dict = dict(release.stac_item_json)
            item_dict['id'] = release.stac_item_id
            item_dict['collection'] = collection_id
            self.sanitize_item_properties(item_dict)

            props = item_dict.setdefault('properties', {})
            props['ddh:access_level'] = release.clearance_state.value if release.clearance_state else 'ouo'
            if release.version_id:
                props['ddh:version_id'] = release.version_id

            prepared_items.append(item_dict)

        # Compute union extent from collected bboxes
        bboxes = [item['bbox'] for item in prepared_items if item.get('bbox')]
        if bboxes:
            union_bbox = [
                min(b[0] for b in bboxes),
                min(b[1] for b in bboxes),
                max(b[2] for b in bboxes),
                max(b[3] for b in bboxes),
            ]
        else:
            union_bbox = [-180, -90, 180, 90]

        # Create collection, then insert all items
        collection_dict = build_raster_stac_collection(
            collection_id=collection_id,
            bbox=union_bbox,
        )
        self.pgstac.insert_collection(collection_dict)

        for item_dict in prepared_items:
            self.pgstac.insert_item(item_dict, collection_id)

        logger.info(
            f"Rebuilt collection '{collection_id}': {len(prepared_items)} items, "
            f"bbox={union_bbox}"
        )

        return {
            'success': True,
            'collection_id': collection_id,
            'items_created': len(prepared_items),
            'bbox': union_bbox,
        }

    def rebuild_all_from_db(self) -> Dict[str, Any]:
        """
        Full catalog rebuild: reconstruct all pgSTAC from internal DB.

        1. Query all distinct stac_collection_id from approved releases
        2. For each: rebuild_collection_from_db()

        Returns:
            Dict with collections_rebuilt, items_rebuilt, errors
        """
        from core.models.asset import ApprovalState

        logger.info("FULL CATALOG REBUILD: Starting rebuild of all collections from DB")

        # Get all approved releases
        releases = self.release_repo.list_by_approval_state(ApprovalState.APPROVED, limit=10000)

        # Get distinct collection IDs
        collection_ids = set()
        for r in releases:
            if r.stac_collection_id:
                collection_ids.add(r.stac_collection_id)

        if not collection_ids:
            logger.info("No approved releases with STAC collection IDs found")
            return {
                'success': True,
                'collections_rebuilt': 0,
                'items_rebuilt': 0,
            }

        collections_rebuilt = 0
        items_rebuilt = 0
        errors = []

        for coll_id in sorted(collection_ids):
            try:
                result = self.rebuild_collection_from_db(coll_id)
                if result.get('success'):
                    collections_rebuilt += 1
                    items_rebuilt += result.get('items_created', 0)
                else:
                    errors.append({'collection_id': coll_id, 'error': result.get('error')})
            except Exception as e:
                logger.error(f"Error rebuilding collection '{coll_id}': {e}")
                errors.append({'collection_id': coll_id, 'error': str(e)})

        logger.info(
            f"FULL CATALOG REBUILD COMPLETE: {collections_rebuilt} collections, "
            f"{items_rebuilt} items, {len(errors)} errors"
        )

        return {
            'success': len(errors) == 0,
            'collections_rebuilt': collections_rebuilt,
            'items_rebuilt': items_rebuilt,
            'errors': errors if errors else None,
        }

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _inject_titiler_urls(self, stac_item_json: dict, blob_path: Optional[str]) -> None:
        """
        Inject TiTiler visualization URLs into STAC item.

        Ensures thumbnail, tiles, and viewer links use the Function App's
        TiTiler config (not whatever the Docker worker may have cached).

        Args:
            stac_item_json: STAC item dict (mutated in place)
            blob_path: COG blob path in silver-cogs container
        """
        if not blob_path:
            return

        try:
            from config import get_config
            config = get_config()
            titiler_base = config.titiler_base_url.rstrip('/')
            vsiaz_url = f"/vsiaz/silver-cogs/{blob_path}"
            encoded_url = urllib.parse.quote(vsiaz_url, safe='')

            # Thumbnail asset
            assets = stac_item_json.setdefault('assets', {})
            thumbnail_params = f"url={encoded_url}&max_size=512"
            # Carry over render params from existing thumbnail if present
            existing_thumb = assets.get('thumbnail', {}).get('href', '')
            for param in ['rescale', 'colormap_name', 'bidx']:
                if f'&{param}=' in existing_thumb:
                    val = existing_thumb.split(f'&{param}=')[1].split('&')[0]
                    thumbnail_params += f"&{param}={val}"

            assets['thumbnail'] = {
                "href": f"{titiler_base}/cog/preview.png?{thumbnail_params}",
                "type": "image/png",
                "title": "Thumbnail",
                "roles": ["thumbnail"]
            }

            # TiTiler links (viewer, tilejson)
            links = stac_item_json.setdefault('links', [])
            # Remove stale tiles/viewer links, then re-add
            links[:] = [l for l in links if l.get('rel') not in ('tiles', 'viewer')]
            links.append({
                "rel": "tiles",
                "href": f"{titiler_base}/cog/tilejson.json?url={encoded_url}",
                "type": "application/json",
                "title": "TileJSON"
            })
            links.append({
                "rel": "viewer",
                "href": f"{titiler_base}/cog/WebMercatorQuad/map.html?url={encoded_url}",
                "type": "text/html",
                "title": "Map Viewer"
            })
        except Exception as titiler_err:
            logger.warning(f"Failed to inject TiTiler URLs (non-fatal): {titiler_err}")


# Module exports
__all__ = ['STACMaterializer']
