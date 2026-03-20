# ============================================================================
# CLAUDE CONTEXT - ACLED FETCH AND DIFF HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Service - DAG task handler for ACLED API sync
# PURPOSE: Fetch new ACLED events and diff against existing Silver table
# LAST_REVIEWED: 20 MAR 2026
# EXPORTS: acled_fetch_and_diff
# DEPENDENCIES: infrastructure.acled_repository
# ============================================================================

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def acled_fetch_and_diff(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    DAG task handler: fetch new ACLED conflict events and diff against Silver.

    Instantiates ACLEDRepository, authenticates via OAuth 2.0 (credentials
    from ACLED_USERNAME / ACLED_PASSWORD environment variables), pages through
    the ACLED API, and returns only events not already present in the target
    PostGIS table.

    Args:
        params: Task parameter dict. Recognised keys:
            max_pages (int):     Pages to process. 0 = unlimited. Default: 0.
            batch_size (int):    Records per API page (max 5000). Default: 5000.
            target_schema (str): PostGIS schema for diff table. Default: "ops".
            target_table (str):  Table name for diff. Default: "acled_new".
        context: DAG execution context (unused; reserved for future use).

    Returns:
        {"success": True, "result": {
            "new_events":    list[dict],   # events not yet in target table
            "raw_responses": list[dict],   # full per-page API payloads
            "metadata": {
                "pages_processed":   int,
                "total_fetched":     int,
                "duplicates_skipped": int,
                "new_count":         int,
                "db_max_timestamp":  int | None,
            }
        }}

    Raises:
        ValueError:             If ACLED credentials env vars are missing.
        requests.HTTPError:     On non-transient ACLED API errors.
        psycopg.Error:          On database connectivity or query failure.
    """
    from infrastructure.acled_repository import ACLEDRepository

    max_pages = int(params.get("max_pages", 0))
    batch_size = int(params.get("batch_size", 5000))
    target_schema = params.get("target_schema", "ops")
    target_table = params.get("target_table", "acled_new")

    logger.info(
        "acled_fetch_and_diff starting: max_pages=%d batch_size=%d target=%s.%s",
        max_pages,
        batch_size,
        target_schema,
        target_table,
    )

    repo = ACLEDRepository()
    result = repo.fetch_and_diff(
        max_pages=max_pages,
        batch_size=batch_size,
        target_schema=target_schema,
        target_table=target_table,
    )

    logger.info(
        "acled_fetch_and_diff complete: new=%d dupes=%d pages=%d",
        result["metadata"]["new_count"],
        result["metadata"]["duplicates_skipped"],
        result["metadata"]["pages_processed"],
    )

    return {"success": True, "result": result}
