# ============================================================================
# CLAUDE CONTEXT - ACLED APPEND TO SILVER HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Service - DAG task handler for Silver table append
# PURPOSE: Bulk INSERT new ACLED events into existing PostGIS table via COPY
# LAST_REVIEWED: 20 MAR 2026
# EXPORTS: acled_append_to_silver
# DEPENDENCIES: pandas, psycopg, infrastructure.db_auth, infrastructure.db_connections
# ============================================================================

import logging
from io import StringIO
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Ordered column list matching ops.acled_new schema (Dec 2025 API revision).
# Order must match the COPY target column list exactly.
COLUMNS = [
    "event_id_cnty", "event_date", "year", "time_precision",
    "disorder_type", "event_type", "sub_event_type",
    "actor1", "assoc_actor_1", "inter1",
    "actor2", "assoc_actor_2", "inter2",
    "interaction", "civilian_targeting", "iso",
    "region", "country", "admin1", "admin2", "admin3",
    "location", "latitude", "longitude", "geo_precision",
    "source", "source_scale", "notes", "fatalities",
    "tags", "timestamp",
]


def acled_append_to_silver(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Bulk-insert new ACLED events into the Silver PostGIS table via COPY protocol.

    Receives `new_events` and `event_count` via DAG `receives:` mapping.
    Uses PostgreSQL COPY FROM STDIN (CSV mode) for high-throughput bulk insert.
    Schema and table name are taken from `target_schema` / `target_table` params.

    Args:
        params: Task parameters injected by the DAG runner.  Expected keys:
            new_events    (list[dict]): New ACLED event records from fetch-and-diff.
            event_count   (int):        Number of new events (used for fast skip guard).
            target_schema (str):        PostgreSQL schema (e.g. "ops").
            target_table  (str):        Table name (e.g. "acled_new").
        context: Optional DAG execution context (unused).

    Returns:
        dict: Handler result envelope.
            On skip:    {"success": True, "result": {"skipped": True, "reason": str}}
            On success: {"success": True, "result": {"rows_inserted": int,
                                                      "target_table": str}}
    """
    import pandas as pd
    from psycopg import sql
    from infrastructure.db_auth import ManagedIdentityAuth
    from infrastructure.db_connections import ConnectionManager

    new_events = params.get("new_events", [])
    event_count = params.get("event_count", 0)
    target_schema = params["target_schema"]
    target_table = params["target_table"]

    if not new_events or event_count == 0:
        logger.info(
            "acled_append_to_silver: no new events (event_count=%d) — skipping.",
            event_count,
        )
        return {"success": True, "result": {"skipped": True, "reason": "no new events"}}

    logger.info(
        "acled_append_to_silver: inserting %d events into %s.%s via COPY.",
        len(new_events),
        target_schema,
        target_table,
    )

    df = pd.DataFrame(new_events)

    # Ensure all expected columns are present (sparse API fields may be absent)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None

    df = df[COLUMNS]
    df = df.where(pd.notna(df), None)

    buffer = StringIO()
    df.to_csv(buffer, index=False, header=False, na_rep="")
    buffer.seek(0)

    copy_sql = sql.SQL(
        "COPY {schema}.{table} ({columns}) FROM STDIN WITH (FORMAT CSV, NULL '')"
    ).format(
        schema=sql.Identifier(target_schema),
        table=sql.Identifier(target_table),
        columns=sql.SQL(", ").join(sql.Identifier(c) for c in COLUMNS),
    )

    auth = ManagedIdentityAuth()
    manager = ConnectionManager(auth)

    with manager.get_connection() as conn:
        with conn.cursor() as cur:
            with cur.copy(copy_sql) as copy:
                copy.write(buffer.getvalue())
        conn.commit()

    rows_inserted = len(df)
    logger.info(
        "acled_append_to_silver: inserted %d rows into %s.%s.",
        rows_inserted,
        target_schema,
        target_table,
    )

    return {
        "success": True,
        "result": {
            "rows_inserted": rows_inserted,
            "target_table": f"{target_schema}.{target_table}",
        },
    }
