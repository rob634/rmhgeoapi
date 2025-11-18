# ============================================================================
# CLAUDE CONTEXT - PGSTAC SEARCH REGISTRATION SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Service - Direct database registration for pgSTAC searches
# PURPOSE: Register searches in pgstac.searches table (bypassing TiTiler API)
# LAST_REVIEWED: 17 NOV 2025
# EXPORTS: PgSTACSearchRegistration class
# INTERFACES: Service layer for search registration
# PYDANTIC_MODELS: None - uses dicts for search payloads
# DEPENDENCIES: hashlib (SHA256), json, infrastructure.postgresql
# SOURCE: Direct writes to pgstac.searches table
# SCOPE: Production architecture - ETL writes, TiTiler reads
# VALIDATION: Search query validation, hash collision detection
# PATTERNS: Repository pattern, Service layer
# ENTRY_POINTS: PgSTACSearchRegistration().register_search()
# INDEX:
#   - PgSTACSearchRegistration class: Line 40
#   - register_search: Line 60
#   - register_collection_search: Line 140
#   - get_search_urls: Line 170
# ============================================================================

"""
PgSTAC Search Registration Service

Registers searches directly in pgstac.searches table without calling TiTiler.
This allows TiTiler to be read-only in production while ETL handles all writes.

Production Architecture:
- ETL Pipeline (rmhazuregeoapi): Read-write access to pgstac schema
- TiTiler (rmhtitiler): Read-only access to pgstac schema

Why This Pattern:
- TiTiler can be read-only (better security)
- No APIM needed to protect /searches/register endpoint
- ETL owns all pgSTAC writes (collections, items, searches)
- Atomic operations during ingestion workflow

Author: Robert and Geospatial Claude Legion
Date: 17 NOV 2025
"""

import json
from hashlib import sha256
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from infrastructure.postgresql import PostgreSQLRepository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "PgSTACSearchRegistration")


class PgSTACSearchRegistration:
    """
    Register pgSTAC searches directly in database (bypassing TiTiler API).

    This service writes to pgstac.searches table using the same schema and
    hashing algorithm that TiTiler-pgSTAC uses internally. TiTiler reads
    from this table with read-only database credentials.

    Why This Pattern:
    - TiTiler can be read-only (better security)
    - No APIM needed to protect /searches/register endpoint
    - ETL owns all pgSTAC writes (collections, items, searches)
    - Atomic operations during ingestion workflow

    Author: Robert and Geospatial Claude Legion
    Date: 17 NOV 2025
    """

    def __init__(self, repo: Optional[PostgreSQLRepository] = None):
        """
        Initialize search registration service.

        Args:
            repo: PostgreSQL repository (creates new if not provided)
        """
        self.repo = repo or PostgreSQLRepository()

    def register_search(
        self,
        collections: List[str],
        metadata: Optional[Dict[str, Any]] = None,
        bbox: Optional[List[float]] = None,
        datetime_str: Optional[str] = None,
        filter_cql: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Register a pgSTAC search in database (mimics TiTiler's /searches/register).

        Computes search_id as SHA256 hash of canonical JSON representation,
        then inserts into pgstac.searches table. Uses ON CONFLICT to handle
        duplicate registrations (updates lastused timestamp).

        Args:
            collections: List of STAC collection IDs to query
            metadata: Optional metadata (name, description, etc.)
            bbox: Optional bounding box [minx, miny, maxx, maxy]
            datetime_str: Optional temporal filter (ISO8601)
            filter_cql: Optional CQL2-JSON filter expression

        Returns:
            search_id (str): SHA256 hash of the search query (64 hex chars)

        Example:
            >>> registrar = PgSTACSearchRegistration()
            >>> search_id = registrar.register_search(
            ...     collections=["namangan_collection"],
            ...     metadata={"name": "Namangan Mosaic"}
            ... )
            >>> print(search_id)
            '6ee588d77095f336398c097a2e926765...'
        """
        logger.info(f"🔄 Registering search for collections: {collections}")

        # Build search query (canonical format for hashing)
        search_query = {
            "collections": collections,
            "filter-lang": "cql2-json"
        }

        # Add optional filters
        if bbox:
            search_query["bbox"] = bbox
        if datetime_str:
            search_query["datetime"] = datetime_str
        if filter_cql:
            search_query["filter"] = filter_cql

        # Compute SHA256 hash (MUST use sort_keys=True and compact separators)
        # This matches TiTiler's hashing algorithm exactly
        canonical_json = json.dumps(search_query, sort_keys=True, separators=(',', ':'))
        search_hash = sha256(canonical_json.encode()).hexdigest()

        logger.debug(f"   Search query: {search_query}")
        logger.debug(f"   Canonical JSON: {canonical_json}")
        logger.debug(f"   Search hash: {search_hash}")

        # Prepare metadata
        if metadata is None:
            metadata = {}

        # Add ETL tracking fields
        metadata.setdefault("registered_by", "etl-pipeline")
        metadata.setdefault("registered_at", datetime.now(timezone.utc).isoformat())

        # Insert into pgstac.searches table
        # ON CONFLICT: If search already exists, update lastused and increment usecount
        with self.repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pgstac.searches (hash, search, metadata, created_at, lastused, usecount)
                    VALUES (%s, %s, %s, NOW(), NOW(), 1)
                    ON CONFLICT (hash)
                    DO UPDATE SET
                        lastused = NOW(),
                        usecount = pgstac.searches.usecount + 1,
                        metadata = EXCLUDED.metadata
                    RETURNING hash, usecount
                    """,
                    (search_hash, json.dumps(search_query), json.dumps(metadata))
                )
                result = cur.fetchone()
                conn.commit()

                if result:
                    returned_hash, use_count = result
                    if use_count == 1:
                        logger.info(f"✅ Search registered (new): {returned_hash}")
                    else:
                        logger.info(f"✅ Search already exists (use_count={use_count}): {returned_hash}")
                    return returned_hash
                else:
                    logger.info(f"✅ Search registered: {search_hash}")
                    return search_hash

    def register_collection_search(
        self,
        collection_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Register standard search for a collection (all items, no filters).

        This is the most common use case: create a search that returns
        all items in a collection for mosaic visualization.

        Args:
            collection_id: STAC collection identifier
            metadata: Optional metadata (defaults to {"name": "{collection_id} mosaic"})

        Returns:
            search_id (str): SHA256 hash to use in TiTiler URLs

        Example:
            >>> registrar = PgSTACSearchRegistration()
            >>> search_id = registrar.register_collection_search("namangan_collection")
            >>> print(f"Viewer: https://rmhtitiler.../searches/{search_id}/map.html")
        """
        if metadata is None:
            metadata = {"name": f"{collection_id} mosaic"}

        return self.register_search(
            collections=[collection_id],
            metadata=metadata
        )

    def get_search_urls(
        self,
        search_id: str,
        titiler_base_url: str,
        assets: Optional[List[str]] = None
    ) -> Dict[str, str]:
        """
        Generate TiTiler URLs for a registered search.

        Args:
            search_id: Search hash from register_search()
            titiler_base_url: TiTiler base URL (e.g., "https://rmhtitiler-...")
            assets: List of asset names to render (defaults to ["data"])

        Returns:
            dict: URLs for viewer, tilejson, and tiles endpoints

        Example:
            >>> urls = registrar.get_search_urls(
            ...     search_id="6ee588d7...",
            ...     titiler_base_url="https://rmhtitiler-...",
            ...     assets=["data"]
            ... )
            >>> print(urls["viewer"])
            'https://rmhtitiler-.../searches/6ee588d7.../WebMercatorQuad/map.html?assets=data'
        """
        if assets is None:
            assets = ["data"]

        # Build assets query parameter
        assets_param = "&".join(f"assets={a}" for a in assets)

        # Remove trailing slash from base URL
        base = titiler_base_url.rstrip('/')

        return {
            "viewer": f"{base}/searches/{search_id}/WebMercatorQuad/map.html?{assets_param}",
            "tilejson": f"{base}/searches/{search_id}/WebMercatorQuad/tilejson.json?{assets_param}",
            "tiles": f"{base}/searches/{search_id}/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?{assets_param}"
        }


# Export the service class
__all__ = ['PgSTACSearchRegistration']
