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

import json
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

    def upsert(self, **kwargs) -> bool:
        """
        Upsert a zarr_metadata record.

        Accepts any fields from ZarrMetadataRecord as keyword arguments.
        Uses INSERT ... ON CONFLICT (zarr_id) DO UPDATE.
        """
        zarr_id = kwargs.get("zarr_id")
        if not zarr_id:
            raise ValueError("zarr_id is required for upsert")

        # Build column list and values from kwargs
        columns = []
        values = []
        update_parts = []

        for key, value in kwargs.items():
            columns.append(key)
            if isinstance(value, (dict, list)):
                values.append(json.dumps(value))
                update_parts.append(f"{key} = EXCLUDED.{key}")
            else:
                values.append(value)
                update_parts.append(f"{key} = EXCLUDED.{key}")

        # Add updated_at
        columns.append("updated_at")
        values.append("NOW()")
        update_parts.append("updated_at = NOW()")

        col_names = ", ".join(columns)
        placeholders = ", ".join(
            "NOW()" if v == "NOW()" else "%s" for v in values
        )
        update_clause = ", ".join(update_parts)
        actual_values = [v for v in values if v != "NOW()"]

        # Build raw SQL (can't use sql.SQL for all parts due to dynamic columns)
        query_str = (
            f"INSERT INTO {self._schema}.zarr_metadata ({col_names}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT (zarr_id) DO UPDATE SET {update_clause}"
        )

        t0 = time.perf_counter()
        try:
            with self._pg_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query_str, actual_values)
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
