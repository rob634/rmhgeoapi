# ============================================================================
# RASTER METADATA REPOSITORY
# ============================================================================
# STATUS: Infrastructure - COG metadata persistence
# PURPOSE: CRUD operations for app.cog_metadata table
# CREATED: 09 JAN 2026
# EPIC: E7 Pipeline Infrastructure -> F7.9 RasterMetadata Implementation
# ============================================================================
"""
Raster Metadata Repository.

Provides persistence for app.cog_metadata table which stores metadata
for Cloud-Optimized GeoTIFFs (COGs) in Azure blob storage.

This repository:
- Stores raster metadata after COG processing
- Enables STAC catalog generation from database
- Provides fast queries for COG properties without reading files

Usage:
    from infrastructure.raster_metadata_repository import RasterMetadataRepository

    repo = RasterMetadataRepository()

    # Upsert COG metadata
    repo.upsert(
        cog_id="fathom_fluvial_defended_2020",
        container="silver-fathom",
        blob_path="merged/fluvial_defended_2020.tif",
        cog_url="/vsiaz/silver-fathom/merged/fluvial_defended_2020.tif",
        width=10000,
        height=8000,
        band_count=8,
        dtype="float32"
    )

    # Get by ID
    metadata = repo.get_by_id("fathom_fluvial_defended_2020")

    # List by collection
    items = repo.list_by_collection("fathom-flood-data")

Exports:
    RasterMetadataRepository: Repository for app.cog_metadata CRUD
    get_raster_metadata_repository: Singleton factory
"""

import logging
import json
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from infrastructure.postgresql import PostgreSQLRepository

logger = logging.getLogger(__name__)


class RasterMetadataRepository:
    """
    Repository for app.cog_metadata table.

    Provides CRUD operations for COG metadata records.
    Gracefully handles missing table (logs warning, returns None).
    """

    def __init__(self):
        """Initialize with PostgreSQL connection."""
        self._pg_repo = PostgreSQLRepository()
        self._table_exists: Optional[bool] = None

    def _check_table_exists(self) -> bool:
        """
        Check if app.cog_metadata table exists.

        Caches result to avoid repeated checks.
        """
        if self._table_exists is not None:
            return self._table_exists

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'app'
                            AND table_name = 'cog_metadata'
                        ) as table_exists
                    """)
                    result = cur.fetchone()
                    self._table_exists = result['table_exists'] if result else False

                    if not self._table_exists:
                        logger.warning(
                            "app.cog_metadata table does not exist. "
                            "Run schema rebuild to create it."
                        )
                    return self._table_exists

        except Exception as e:
            logger.error(f"Error checking cog_metadata table: {e}")
            self._table_exists = False
            return False

    def upsert(
        self,
        cog_id: str,
        container: str,
        blob_path: str,
        cog_url: str,
        width: int,
        height: int,
        band_count: int = 1,
        dtype: str = "float32",
        nodata: Optional[float] = None,
        crs: str = "EPSG:4326",
        transform: Optional[List[float]] = None,
        resolution: Optional[List[float]] = None,
        band_names: Optional[List[str]] = None,
        band_units: Optional[List[str]] = None,
        bbox_minx: Optional[float] = None,
        bbox_miny: Optional[float] = None,
        bbox_maxx: Optional[float] = None,
        bbox_maxy: Optional[float] = None,
        temporal_start: Optional[datetime] = None,
        temporal_end: Optional[datetime] = None,
        is_cog: bool = True,
        overview_levels: Optional[List[int]] = None,
        compression: Optional[str] = None,
        blocksize: Optional[List[int]] = None,
        colormap: Optional[str] = None,
        rescale_range: Optional[List[float]] = None,
        eo_bands: Optional[List[Dict[str, Any]]] = None,
        raster_bands: Optional[List[Dict[str, Any]]] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        keywords: Optional[str] = None,
        license: Optional[str] = None,
        providers: Optional[List[Dict[str, Any]]] = None,
        stac_extensions: Optional[List[str]] = None,
        stac_item_id: Optional[str] = None,
        stac_collection_id: Optional[str] = None,
        etl_job_id: Optional[str] = None,
        source_file: Optional[str] = None,
        source_format: Optional[str] = None,
        source_crs: Optional[str] = None,
        sci_doi: Optional[str] = None,
        sci_citation: Optional[str] = None,
        custom_properties: Optional[Dict[str, Any]] = None,
        stac_item_json: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Insert or update COG metadata.

        Uses PostgreSQL UPSERT (INSERT ON CONFLICT UPDATE) for idempotency.

        Args:
            cog_id: Unique COG identifier
            container: Azure storage container name
            blob_path: Path within container
            cog_url: Full COG URL (/vsiaz/ or HTTPS)
            width: Raster width in pixels
            height: Raster height in pixels
            band_count: Number of bands
            dtype: Numpy dtype
            nodata: NoData value
            crs: CRS as EPSG code
            transform: Affine transform [a,b,c,d,e,f]
            resolution: Resolution [x_res, y_res]
            band_names: Band descriptions
            band_units: Units per band
            bbox_*: Bounding box coordinates
            temporal_*: Temporal extent
            is_cog: Cloud-optimized flag
            overview_levels: COG overview levels
            compression: Compression method
            blocksize: Tile size [width, height]
            colormap: Default colormap
            rescale_range: Default rescale [min, max]
            eo_bands: EO extension band metadata
            raster_bands: Raster extension band stats
            title: Human-readable title
            description: Dataset description
            keywords: Comma-separated tags
            license: SPDX license
            providers: STAC providers
            stac_extensions: Extension URIs
            stac_item_id: STAC item ID
            stac_collection_id: STAC collection ID
            etl_job_id: ETL job ID
            source_file: Original source filename
            source_format: Source file format
            source_crs: Original CRS
            sci_doi: Scientific DOI
            sci_citation: Citation text
            custom_properties: Additional properties

        Returns:
            True if successful, False otherwise
        """
        if not self._check_table_exists():
            logger.debug(f"Skipping cog_metadata upsert - table not available")
            return False

        try:
            now = datetime.now(timezone.utc)

            # psycopg3 type adapters handle dict/list -> JSONB automatically
            # via PostgreSQLRepository._register_type_adapters() (JsonbBinaryDumper)
            # No manual json.dumps() needed for SQL parameters.

            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO app.cog_metadata (
                            cog_id, container, blob_path, cog_url,
                            width, height, band_count, dtype, nodata, crs,
                            transform, resolution, band_names, band_units,
                            bbox_minx, bbox_miny, bbox_maxx, bbox_maxy,
                            temporal_start, temporal_end,
                            is_cog, overview_levels, compression, blocksize,
                            colormap, rescale_range, eo_bands, raster_bands,
                            title, description, keywords, license,
                            providers, stac_extensions,
                            stac_item_id, stac_collection_id,
                            etl_job_id, source_file, source_format, source_crs,
                            sci_doi, sci_citation, custom_properties,
                            stac_item_json,
                            created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s,
                            %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s,
                            %s, %s
                        )
                        ON CONFLICT (cog_id) DO UPDATE SET
                            container = EXCLUDED.container,
                            blob_path = EXCLUDED.blob_path,
                            cog_url = EXCLUDED.cog_url,
                            width = EXCLUDED.width,
                            height = EXCLUDED.height,
                            band_count = EXCLUDED.band_count,
                            dtype = EXCLUDED.dtype,
                            nodata = EXCLUDED.nodata,
                            crs = EXCLUDED.crs,
                            transform = EXCLUDED.transform,
                            resolution = EXCLUDED.resolution,
                            band_names = EXCLUDED.band_names,
                            band_units = EXCLUDED.band_units,
                            bbox_minx = EXCLUDED.bbox_minx,
                            bbox_miny = EXCLUDED.bbox_miny,
                            bbox_maxx = EXCLUDED.bbox_maxx,
                            bbox_maxy = EXCLUDED.bbox_maxy,
                            temporal_start = EXCLUDED.temporal_start,
                            temporal_end = EXCLUDED.temporal_end,
                            is_cog = EXCLUDED.is_cog,
                            overview_levels = EXCLUDED.overview_levels,
                            compression = EXCLUDED.compression,
                            blocksize = EXCLUDED.blocksize,
                            colormap = EXCLUDED.colormap,
                            rescale_range = EXCLUDED.rescale_range,
                            eo_bands = EXCLUDED.eo_bands,
                            raster_bands = EXCLUDED.raster_bands,
                            title = EXCLUDED.title,
                            description = EXCLUDED.description,
                            keywords = EXCLUDED.keywords,
                            license = EXCLUDED.license,
                            providers = EXCLUDED.providers,
                            stac_extensions = EXCLUDED.stac_extensions,
                            stac_item_id = EXCLUDED.stac_item_id,
                            stac_collection_id = EXCLUDED.stac_collection_id,
                            etl_job_id = EXCLUDED.etl_job_id,
                            source_file = EXCLUDED.source_file,
                            source_format = EXCLUDED.source_format,
                            source_crs = EXCLUDED.source_crs,
                            sci_doi = EXCLUDED.sci_doi,
                            sci_citation = EXCLUDED.sci_citation,
                            custom_properties = EXCLUDED.custom_properties,
                            stac_item_json = EXCLUDED.stac_item_json,
                            updated_at = EXCLUDED.updated_at
                    """, (
                        cog_id, container, blob_path, cog_url,
                        width, height, band_count, dtype, nodata, crs,
                        transform, resolution, band_names, band_units,
                        bbox_minx, bbox_miny, bbox_maxx, bbox_maxy,
                        temporal_start, temporal_end,
                        is_cog, overview_levels, compression, blocksize,
                        colormap, rescale_range, eo_bands, raster_bands,
                        title, description, keywords, license,
                        providers, stac_extensions,
                        stac_item_id, stac_collection_id,
                        etl_job_id, source_file, source_format, source_crs,
                        sci_doi, sci_citation, custom_properties,
                        stac_item_json,
                        now, now
                    ))
                    conn.commit()

            logger.info(f"Upserted cog_metadata: {cog_id} ({container}/{blob_path})")
            return True

        except Exception as e:
            logger.error(f"Error upserting cog_metadata for {cog_id}: {e}")
            return False

    def get_by_id(self, cog_id: str) -> Optional[Dict[str, Any]]:
        """
        Get COG metadata by ID.

        Args:
            cog_id: COG identifier

        Returns:
            Dict with metadata, or None if not found
        """
        if not self._check_table_exists():
            return None

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT * FROM app.cog_metadata
                        WHERE cog_id = %s
                    """, (cog_id,))
                    result = cur.fetchone()
                    return dict(result) if result else None

        except Exception as e:
            logger.error(f"Error getting cog_metadata for {cog_id}: {e}")
            return None

    def list_by_collection(
        self,
        stac_collection_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        List COG metadata by STAC collection ID.

        Args:
            stac_collection_id: STAC collection identifier
            limit: Maximum records to return
            offset: Number of records to skip

        Returns:
            List of metadata dicts
        """
        if not self._check_table_exists():
            return []

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT * FROM app.cog_metadata
                        WHERE stac_collection_id = %s
                        ORDER BY created_at DESC
                        LIMIT %s OFFSET %s
                    """, (stac_collection_id, limit, offset))
                    return [dict(row) for row in cur.fetchall()]

        except Exception as e:
            logger.error(f"Error listing cog_metadata for collection {stac_collection_id}: {e}")
            return []

    def list_by_container(
        self,
        container: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        List COG metadata by Azure container.

        Args:
            container: Azure storage container name
            limit: Maximum records to return
            offset: Number of records to skip

        Returns:
            List of metadata dicts
        """
        if not self._check_table_exists():
            return []

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT * FROM app.cog_metadata
                        WHERE container = %s
                        ORDER BY created_at DESC
                        LIMIT %s OFFSET %s
                    """, (container, limit, offset))
                    return [dict(row) for row in cur.fetchall()]

        except Exception as e:
            logger.error(f"Error listing cog_metadata for container {container}: {e}")
            return []

    def list_by_etl_job(self, etl_job_id: str) -> List[Dict[str, Any]]:
        """
        List COG metadata by ETL job ID.

        Args:
            etl_job_id: ETL job identifier

        Returns:
            List of metadata dicts
        """
        if not self._check_table_exists():
            return []

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT * FROM app.cog_metadata
                        WHERE etl_job_id = %s
                        ORDER BY created_at DESC
                    """, (etl_job_id,))
                    return [dict(row) for row in cur.fetchall()]

        except Exception as e:
            logger.error(f"Error listing cog_metadata for job {etl_job_id}: {e}")
            return []

    def delete(self, cog_id: str) -> bool:
        """
        Delete COG metadata by ID.

        Args:
            cog_id: COG identifier

        Returns:
            True if deleted, False otherwise
        """
        if not self._check_table_exists():
            return False

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        DELETE FROM app.cog_metadata
                        WHERE cog_id = %s
                    """, (cog_id,))
                    deleted = cur.rowcount > 0
                    conn.commit()

            if deleted:
                logger.info(f"Deleted cog_metadata: {cog_id}")
            return deleted

        except Exception as e:
            logger.error(f"Error deleting cog_metadata for {cog_id}: {e}")
            return False

    def update_stac_linkage(
        self,
        cog_id: str,
        stac_item_id: str,
        stac_collection_id: str
    ) -> bool:
        """
        Update STAC linkage for a COG.

        Called after STAC cataloging to backlink the COG to its STAC entries.

        Args:
            cog_id: COG identifier
            stac_item_id: STAC item ID
            stac_collection_id: STAC collection ID

        Returns:
            True if updated, False otherwise
        """
        if not self._check_table_exists():
            return False

        try:
            now = datetime.now(timezone.utc)

            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE app.cog_metadata
                        SET stac_item_id = %s,
                            stac_collection_id = %s,
                            updated_at = %s
                        WHERE cog_id = %s
                    """, (stac_item_id, stac_collection_id, now, cog_id))
                    updated = cur.rowcount > 0
                    conn.commit()

            if updated:
                logger.info(
                    f"Updated STAC linkage for {cog_id}: "
                    f"item={stac_item_id}, collection={stac_collection_id}"
                )
            return updated

        except Exception as e:
            logger.error(f"Error updating STAC linkage for {cog_id}: {e}")
            return False

    def get_stac_item_json(self, cog_id: str) -> Optional[Dict[str, Any]]:
        """
        Read cached STAC item dict by cog_id.

        Args:
            cog_id: COG identifier (draft stac_item_id at processing time)

        Returns:
            STAC item dict, or None if not found or not cached
        """
        if not self._check_table_exists():
            return None

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT stac_item_json FROM app.cog_metadata
                        WHERE cog_id = %s
                    """, (cog_id,))
                    result = cur.fetchone()
                    if result and result['stac_item_json']:
                        val = result['stac_item_json']
                        # psycopg3 auto-deserializes JSONB to dict
                        if isinstance(val, str):
                            return json.loads(val)
                        return val
                    return None

        except Exception as e:
            logger.error(f"Error reading stac_item_json for {cog_id}: {e}")
            return None

    def update_stac_item_json(self, cog_id: str, stac_item_json: Dict[str, Any]) -> bool:
        """
        Update cached STAC item dict for an existing cog_metadata record.

        Args:
            cog_id: COG identifier
            stac_item_json: Full STAC item dict to cache

        Returns:
            True if updated, False otherwise
        """
        if not self._check_table_exists():
            return False

        try:
            now = datetime.now(timezone.utc)

            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE app.cog_metadata
                        SET stac_item_json = %s,
                            updated_at = %s
                        WHERE cog_id = %s
                    """, (stac_item_json, now, cog_id))
                    updated = cur.rowcount > 0
                    conn.commit()

            if updated:
                logger.info(f"Updated stac_item_json for {cog_id}")
            return updated

        except Exception as e:
            logger.error(f"Error updating stac_item_json for {cog_id}: {e}")
            return False

    def count(self, stac_collection_id: Optional[str] = None) -> int:
        """
        Count COG metadata records.

        Args:
            stac_collection_id: Optional filter by collection

        Returns:
            Number of records
        """
        if not self._check_table_exists():
            return 0

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    if stac_collection_id:
                        cur.execute("""
                            SELECT COUNT(*) as count FROM app.cog_metadata
                            WHERE stac_collection_id = %s
                        """, (stac_collection_id,))
                    else:
                        cur.execute("SELECT COUNT(*) as count FROM app.cog_metadata")
                    result = cur.fetchone()
                    return result['count'] if result else 0

        except Exception as e:
            logger.error(f"Error counting cog_metadata: {e}")
            return 0


# Singleton instance
_instance: Optional[RasterMetadataRepository] = None


def get_raster_metadata_repository() -> RasterMetadataRepository:
    """Get singleton RasterMetadataRepository instance."""
    global _instance
    if _instance is None:
        _instance = RasterMetadataRepository()
    return _instance


__all__ = ['RasterMetadataRepository', 'get_raster_metadata_repository']
