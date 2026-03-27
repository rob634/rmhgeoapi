# ============================================================================
# CLAUDE CONTEXT - ZARR METADATA REPOSITORY
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.6)
# STATUS: Data access - PostgreSQL operations for zarr_metadata table
# PURPOSE: CRUD for app.zarr_metadata — source of truth for Zarr store metadata
# LAST_REVIEWED: 22 MAR 2026
# EXPORTS: ZarrMetadataRepository
# DEPENDENCIES: psycopg, infrastructure.postgresql
# ============================================================================
"""
Zarr Metadata Repository.

Provides database access for app.zarr_metadata table — the internal
source of truth for Zarr store metadata. Caches stac_item_json for
STAC materialization via stac_materialize_item handler.

Mirrors the pattern of RasterMetadataRepository for cog_metadata.
"""

import logging
import time
from typing import Any, Dict, Optional

from psycopg import sql
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


class ZarrMetadataRepository:
    """PostgreSQL repository for zarr_metadata table."""

    def __init__(self):
        from infrastructure.postgresql import PostgreSQLRepository
        self._pg_repo = PostgreSQLRepository()
        from config import get_config
        self._schema = get_config().database.app_schema

    def get_by_id(self, zarr_id: str) -> Optional[Dict[str, Any]]:
        """Get zarr metadata by zarr_id. Returns dict or None."""
        query = sql.SQL(
            "SELECT * FROM {schema}.zarr_metadata WHERE zarr_id = %s"
        ).format(schema=sql.Identifier(self._schema))

        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (zarr_id,))
                    row = cur.fetchone()
                    return dict(row) if row else None
        except Exception as exc:
            logger.error("zarr_metadata get_by_id failed: %s", exc)
            return None

    # Whitelist of allowed column names (from ZarrMetadataRecord)
    _ALLOWED_COLUMNS = frozenset({
        "zarr_id", "container", "store_prefix", "store_url",
        "zarr_format", "variables", "dimensions", "chunks", "compression",
        "bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy", "crs",
        "time_start", "time_end", "time_steps",
        "total_size_bytes", "chunk_count",
        "stac_item_id", "stac_collection_id", "stac_item_json",
        "pipeline", "etl_job_id", "source_file", "source_format",
        "created_at", "updated_at",
    })

    def upsert(self, **kwargs) -> bool:
        """
        Upsert a zarr_metadata record.

        Accepts fields from ZarrMetadataRecord as keyword arguments.
        Uses parameterized SQL — no f-string SQL construction.
        """
        zarr_id = kwargs.get("zarr_id")
        if not zarr_id:
            raise ValueError("zarr_id is required for upsert")

        # Validate column names against whitelist (prevents SQL injection)
        invalid_keys = set(kwargs.keys()) - self._ALLOWED_COLUMNS
        if invalid_keys:
            raise ValueError(f"Invalid column names for zarr_metadata: {invalid_keys}")

        # Build parameterized query using psycopg sql composition
        columns = []
        values = []

        for key, value in kwargs.items():
            columns.append(key)
            values.append(value)

        # Add updated_at
        columns.append("updated_at")

        col_identifiers = [sql.Identifier(c) for c in columns]
        # Placeholders: %s for each value column, NOW() for updated_at
        placeholders_list = [sql.Placeholder()] * len(kwargs) + [sql.SQL("NOW()")]
        update_set = sql.SQL(", ").join(
            sql.SQL("{col} = EXCLUDED.{col}").format(col=sql.Identifier(c))
            for c in columns
        )

        query = sql.SQL(
            "INSERT INTO {schema}.zarr_metadata ({cols}) VALUES ({vals}) "
            "ON CONFLICT (zarr_id) DO UPDATE SET {update}"
        ).format(
            schema=sql.Identifier(self._schema),
            cols=sql.SQL(", ").join(col_identifiers),
            vals=sql.SQL(", ").join(placeholders_list),
            update=update_set,
        )

        t0 = time.perf_counter()
        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, values)
                conn.commit()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "zarr_metadata upsert: zarr_id=%s elapsed_ms=%.1f",
                zarr_id, elapsed_ms,
            )
            return True

        except Exception as exc:
            logger.error("zarr_metadata upsert failed: %s", exc)
            return False
