# ============================================================================
# CLAUDE CONTEXT - VECTOR REFRESH TIPG ATOMIC HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.5 handler decomposition)
# STATUS: Atomic handler - Refresh TiPG collection cache after vector ETL
# PURPOSE: Standalone DAG node wrapping ServiceLayerClient.refresh_tipg_collections()
# LAST_REVIEWED: 19 MAR 2026
# EXPORTS: vector_refresh_tipg
# DEPENDENCIES: infrastructure.service_layer_client
# ============================================================================
"""
Vector Refresh TiPG — atomic handler for DAG workflows.

Refreshes TiPG's collection catalog so newly created PostGIS tables become
discoverable as OGC Feature collections. TiPG failure is tolerable — the
handler returns success with a warning rather than failing the workflow.

Extracted from: handler_vector_docker_complete._refresh_tipg() (line 851)
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def vector_refresh_tipg(params: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """
    Refresh TiPG catalog after vector table creation.

    Params:
        table_name: PostGIS table name (used to build collection_id)
        schema_name: PostGIS schema (default: "geo")

    Returns:
        success=True if TiPG responded (even with error status).
        success=False only if handler itself crashed (TiPG unreachable).
        result.status reports actual TiPG outcome ("success" or "error").
    """
    table_name = params.get('table_name')
    schema_name = params.get('schema_name', 'geo')

    if not table_name:
        return {"success": False, "error": "table_name is required"}

    collection_id = f"{schema_name}.{table_name}"

    try:
        from infrastructure.service_layer_client import ServiceLayerClient
        client = ServiceLayerClient()

        logger.info(f"Refreshing TiPG catalog for {collection_id}")
        refresh_result = client.refresh_tipg_collections()

        if refresh_result.status == "success":
            result = {
                "collection_id": collection_id,
                "status": "success",
                "collections_before": refresh_result.collections_before,
                "collections_after": refresh_result.collections_after,
                "new_collections": refresh_result.new_collections,
                "collection_discovered": collection_id in refresh_result.new_collections,
            }
        else:
            result = {
                "collection_id": collection_id,
                "status": "error",
                "error": refresh_result.error,
            }

        # Probe the specific collection
        try:
            probe = client.probe_collection(collection_id)
            result['probe'] = probe
        except Exception as probe_err:
            result['probe'] = {'status': 'failed', 'error': str(probe_err)}

        # Handler succeeded (it called TiPG and got a response).
        # TiPG's own status is reported in result — not a handler failure.
        return {"success": True, "result": result}

    except Exception as e:
        # Handler itself failed (TiPG unreachable, network error, etc.)
        logger.warning(f"TiPG refresh for {collection_id} failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "result": {
                "collection_id": collection_id,
                "status": "failed",
                "error": str(e),
            },
        }
