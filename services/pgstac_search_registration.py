# ============================================================================
# CLAUDE CONTEXT - PGSTAC SEARCH REGISTRATION SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Service - Direct database registration for pgSTAC searches
# PURPOSE: Register searches in pgstac.searches table (bypassing TiTiler API)
# LAST_REVIEWED: 25 NOV 2025
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

IMPORTANT: pgSTAC GENERATED Column Workaround (25 NOV 2025)
============================================================

This service uses a SELECT-then-INSERT/UPDATE pattern instead of a standard
UPSERT (INSERT...ON CONFLICT) due to a PostgreSQL bug with GENERATED columns.

THE BUG:
--------
The pgstac.searches table has a GENERATED column:
    hash TEXT GENERATED ALWAYS AS (search_hash(search, metadata))

When using ON CONFLICT (hash), PostgreSQL's query planner "inlines" the
GENERATED column expression during conflict detection. This causes it to
look for search_tohash(jsonb) with 1 argument, but the function is defined
as search_tohash(jsonb, jsonb) with 2 arguments.

Error: "function search_tohash(jsonb) does not exist"

This happens because search_hash() internally calls search_tohash() and
during query inlining, PostgreSQL gets confused about the function signature.

THE WORKAROUND:
---------------
Instead of:
    INSERT INTO pgstac.searches (search, metadata)
    VALUES ($1, $2)
    ON CONFLICT (hash) DO UPDATE SET lastused = NOW()  -- FAILS!

We use:
    1. Compute hash in Python (SHA256 of canonical JSON)
    2. SELECT to check if hash exists
    3. If exists: UPDATE the row
    4. If not: INSERT new row (GENERATED column computes hash on INSERT)

This avoids ON CONFLICT entirely, which is the only operation that triggers
the bug.

ROOT CAUSE FIX:
---------------
A fresh pgSTAC installation via `DROP SCHEMA pgstac CASCADE` followed by
`pypgstac migrate` creates functions with correct signatures. The endpoint
POST /api/dbadmin/maintenance/full-rebuild?confirm=yes performs this.

After a clean rebuild, the workaround is technically unnecessary, but we
keep it as defensive programming to protect against:
- Future partial migration failures
- Environments that haven't been rebuilt
- Edge cases where pgstac schema gets corrupted

VERIFICATION:
-------------
To check if your pgSTAC functions have correct signatures:

    SELECT p.proname, pg_get_function_arguments(p.oid)
    FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'pgstac'
    AND p.proname IN ('search_tohash', 'search_hash');

Expected (correct):
    search_hash    | search jsonb, metadata jsonb
    search_tohash  | search jsonb                   <- 1 argument

Broken (bug present):
    search_hash    | search jsonb, metadata jsonb
    search_tohash  | search jsonb, metadata jsonb   <- 2 arguments (WRONG)

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

        # Insert into pgstac.searches table using SELECT-then-INSERT/UPDATE pattern
        #
        # FIX (25 NOV 2025): Avoid ON CONFLICT (hash) due to PostgreSQL GENERATED column inlining bug
        # - pgstac.searches.hash is GENERATED ALWAYS AS (search_tohash(search, metadata))
        # - ON CONFLICT (hash) triggers query inlining which looks for search_tohash(jsonb) (1 param)
        #   instead of search_tohash(jsonb, jsonb) (2 params), causing "function does not exist" error
        # - Workaround: Use Python-computed hash for lookup, then INSERT or UPDATE separately
        #
        # Actual columns: hash (generated), search, metadata, lastused, usecount
        with self.repo._get_connection() as conn:
            with conn.cursor() as cur:
                # FIX (25 NOV 2025): Set search_path to include pgstac for GENERATED column computation
                # The hash column is GENERATED ALWAYS AS (search_hash(search, metadata))
                # search_hash() internally calls search_tohash() WITHOUT schema prefix
                # Without pgstac in search_path, PostgreSQL can't find search_tohash()
                cur.execute("SET search_path TO pgstac, public")

                # Step 1: Check if search already exists using Python-computed hash
                cur.execute(
                    """
                    SELECT hash, usecount FROM pgstac.searches WHERE hash = %s
                    """,
                    (search_hash,)
                )
                existing = cur.fetchone()

                if existing:
                    # Step 2a: Update existing search (increment usecount, update metadata)
                    cur.execute(
                        """
                        UPDATE pgstac.searches
                        SET lastused = NOW(),
                            usecount = usecount + 1,
                            metadata = %s
                        WHERE hash = %s
                        RETURNING hash, usecount
                        """,
                        (json.dumps(metadata), search_hash)
                    )
                    result = cur.fetchone()
                    conn.commit()

                    returned_hash = result['hash']
                    use_count = result['usecount']
                    logger.info(f"✅ Search already exists (use_count={use_count}): {returned_hash}")
                    return returned_hash
                else:
                    # Step 2b: Insert new search (let PostgreSQL compute hash via GENERATED column)
                    cur.execute(
                        """
                        INSERT INTO pgstac.searches (search, metadata, lastused, usecount)
                        VALUES (%s, %s, NOW(), 1)
                        RETURNING hash, usecount
                        """,
                        (json.dumps(search_query), json.dumps(metadata))
                    )
                    result = cur.fetchone()
                    conn.commit()

                    if result:
                        returned_hash = result['hash']
                        logger.info(f"✅ Search registered (new): {returned_hash}")
                        return returned_hash
                    else:
                        # Fallback: return Python-computed hash
                        logger.info(f"✅ Search registered: {search_hash}")
                        return search_hash

    def register_collection_search(
        self,
        collection_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        bbox: Optional[List[float]] = None
    ) -> str:
        """
        Register standard search for a collection (all items, no filters).

        This is the most common use case: create a search that returns
        all items in a collection for mosaic visualization.

        Args:
            collection_id: STAC collection identifier
            metadata: Optional metadata (defaults to {"name": "{collection_id} mosaic"})
            bbox: Optional bounding box [minx, miny, maxx, maxy] for TileJSON bounds.
                  When provided, TiTiler's map.html viewer will auto-zoom to this extent
                  instead of showing world bounds. Should be the collection's spatial extent.

        Returns:
            search_id (str): SHA256 hash to use in TiTiler URLs

        Example:
            >>> registrar = PgSTACSearchRegistration()
            >>> search_id = registrar.register_collection_search(
            ...     "namangan_collection",
            ...     bbox=[71.6063, 40.9806, 71.7219, 40.9850]
            ... )
            >>> print(f"Viewer: https://rmhtitiler.../searches/{search_id}/map.html")
        """
        if metadata is None:
            metadata = {"name": f"{collection_id} mosaic"}

        # Include bounds in metadata for TiTiler TileJSON auto-zoom (21 NOV 2025)
        # When TiTiler-PgSTAC generates TileJSON, it uses metadata.bounds if present
        # This allows map.html fitBounds() to zoom to actual collection extent
        if bbox:
            metadata["bounds"] = bbox
            logger.debug(f"   Added bounds to metadata: {bbox}")

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
