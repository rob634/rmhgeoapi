# ============================================================================
# H3 ADMIN BLUEPRINT
# ============================================================================
# STATUS: Trigger layer - Blueprint for /api/h3/* admin routes
# PURPOSE: H3 hierarchical grid debugging and management endpoints
# CREATED: 12 JAN 2026 (Consolidated from function_app.py)
# EXPORTS: bp (Blueprint)
# ============================================================================
"""
H3 Admin Blueprint - H3 grid administration routes.

Routes (3 total):
    GET|POST /api/h3/debug      - H3 debug operations (schema, grids, filters)
    GET|POST|DELETE /api/h3/datasets - H3 dataset registry CRUD
    GET /api/h3/admin/stats     - H3 cell counts by resolution (admin)

NOTE: Changed from /api/admin/h3 to /api/h3/* because Azure Functions
reserves /api/admin/* for built-in admin UI (returns 404).
"""

import azure.functions as func
from azure.functions import Blueprint
import json
from datetime import datetime, timezone

bp = Blueprint()


# ============================================================================
# H3 DEBUG & MANAGEMENT (3 routes)
# ============================================================================

@bp.route(route="h3/debug", methods=["GET", "POST"])
def admin_h3_debug(req: func.HttpRequest) -> func.HttpResponse:
    """
    H3 debug operations: GET/POST /api/h3/debug?operation={op}&{params}

    Available operations:
    - schema_status: Check h3 schema exists
    - grid_summary: Grid metadata for all resolutions
    - grid_details: Detailed stats for specific grid (requires grid_id)
    - reference_filters: List all reference filters
    - reference_filter_details: Details for specific filter (requires filter_name)
    - sample_cells: Sample cells from grid (requires grid_id)
    - parent_child_check: Validate hierarchy (requires parent_id)
    - delete_grids: Delete grids by prefix (POST, requires confirm=yes)
    - nuke_h3: Truncate all H3 tables (POST, requires confirm=yes)
    """
    from triggers.admin.h3_debug import admin_h3_debug_trigger
    return admin_h3_debug_trigger.handle_request(req)


@bp.route(route="h3/datasets", methods=["GET", "POST", "DELETE"])
def h3_datasets(req: func.HttpRequest) -> func.HttpResponse:
    """
    H3 Dataset Registry CRUD: /api/h3/datasets

    GET  /api/h3/datasets              - List all datasets
    GET  /api/h3/datasets?id={id}      - Get single dataset
    POST /api/h3/datasets              - Register new dataset (UPSERT)
    DELETE /api/h3/datasets?id={id}    - Delete dataset (requires confirm=yes)

    Development endpoint for managing h3.dataset_registry. For production use,
    prefer the h3_register_dataset job which provides async processing.
    """
    from triggers.admin.h3_datasets import admin_h3_datasets_trigger
    return admin_h3_datasets_trigger.handle_request(req)


@bp.route(route="h3/admin/stats", methods=["GET"])
def h3_stats(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get H3 grid cell counts by resolution: GET /api/h3/admin/stats

    Returns cell counts for each resolution level (2-7) in the h3.cells table.

    Response:
        {
            "stats": {
                "2": 12345,
                "3": 86412,
                ...
            },
            "timestamp": "2025-12-16T00:00:00Z"
        }
    """
    try:
        from infrastructure.postgresql import PostgreSQLRepository

        repo = PostgreSQLRepository(schema_name='h3')

        # Query cell counts by resolution from normalized h3.cells table
        query = """
            SELECT resolution, COUNT(*) as count
            FROM h3.cells
            GROUP BY resolution
            ORDER BY resolution
        """

        with repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()

        # Build stats dict (rows are dict_row objects from psycopg)
        stats = {str(row['resolution']): row['count'] for row in rows}

        return func.HttpResponse(
            json.dumps({
                "stats": stats,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        return func.HttpResponse(
            json.dumps({
                "error": str(e),
                "stats": {},
                "timestamp": datetime.now(timezone.utc).isoformat()
            }),
            mimetype="application/json",
            status_code=200  # Return 200 with empty stats so UI doesn't break
        )
